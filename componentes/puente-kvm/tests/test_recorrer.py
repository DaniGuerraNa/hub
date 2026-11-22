"""Recorrer una pantalla de arriba abajo en una sola llamada, y ver sólo una zona.

En la primera prueba con el aparato, Claude recorrió una hoja con unas 40
llamadas: rueda, mirar la pantalla entera, «me pasé, vuelvo». Aquí el puente
baja solo, para cuando la zona deja de cambiar y dice cuánto subió cada vez.
"""

import asyncio
import io
import re

import pytest
from PIL import Image

from puente_kvm import mcp_servidor
from puente_kvm.motor import desplazamiento
from puente_kvm.simulador import ALTO_LINEA, REGION_EDITOR

from .ayuda import PERSONA, mcp_contra, puente_simulado

X, Y, W, H = REGION_EDITOR


def dar(c):
    assert c.post("/api/control", json={"accion": "dar"}, headers=PERSONA).status_code == 200


def test_recorre_la_zona_hasta_el_final_y_mide_lo_que_sube_cada_vez():
    with puente_simulado(lineas=300) as (c, sim):
        dar(c)
        r = c.post("/api/recorrer", json={"x": X, "y": Y, "ancho": W, "alto": H, "pasos": 4, "max_paginas": 40})
        assert r.status_code == 200, r.text
        d = r.json()
        e = sim.editor
        assert d["final"] is True
        assert e.arriba == len(e.lineas) - e.filas  # llegó abajo del todo
        # Uno por página; la primera no viene de ninguna. La primera bajada son los
        # pasos pedidos (3 líneas por paso en el simulador); después se recalibra
        # hacia las tres cuartas partes de la zona, sin pasarse de ella.
        assert len(d["subio"]) == d["paginas"] and d["subio"][0] is None
        assert d["subio"][1] == 4 * 3 * ALTO_LINEA
        assert all(s and s < H for s in d["subio"][2:-1])
        assert max(d["subio"][2:]) > d["subio"][1]
        img = Image.open(io.BytesIO(c.get(f"/api/recorridos/{d['id']}/1.png").content))
        assert img.size == (W, H)
        assert c.get(f"/api/recorridos/{d['id']}/{d['paginas'] + 1}.png").status_code == 404


def test_las_paginas_de_un_recorrido_no_se_mezclan_con_las_del_siguiente():
    with puente_simulado(lineas=300) as (c, sim):
        dar(c)
        zona = {"x": X, "y": Y, "ancho": W, "alto": H, "max_paginas": 2}
        primero = c.post("/api/recorrer", json=zona).json()["id"]
        segundo = c.post("/api/recorrer", json=zona).json()["id"]
        assert c.get(f"/api/recorridos/{primero}/1.png").status_code == 404
        assert c.get(f"/api/recorridos/{segundo}/1.png").status_code == 200


def test_para_al_tope_de_paginas_y_dice_que_no_llego_al_final():
    with puente_simulado(lineas=300) as (c, sim):
        dar(c)
        d = c.post("/api/recorrer", json={"x": X, "y": Y, "ancho": W, "alto": H, "pasos": 1,
                                          "max_paginas": 3}).json()
        assert d["paginas"] == 3 and d["final"] is False


def test_sin_el_control_no_recorre_nada():
    with puente_simulado(lineas=300) as (c, sim):
        r = c.post("/api/recorrer", json={"x": X, "y": Y, "ancho": W, "alto": H})
        assert r.status_code == 423
        assert sim.editor.arriba == 0


@pytest.mark.parametrize("zona", [{"x": 0, "y": 0, "ancho": 10, "alto": 10},
                                  {"x": 1900, "y": 0, "ancho": 400, "alto": 400}])
def test_una_zona_minuscula_o_fuera_de_la_pantalla_se_rechaza(zona):
    with puente_simulado(lineas=50) as (c, sim):
        dar(c)
        assert c.post("/api/recorrer", json=zona).status_code == 400


def test_el_desplazamiento_no_se_inventa_si_las_imagenes_no_se_parecen():
    a = Image.new("RGB", (400, 300), "white")
    b = Image.effect_noise((400, 300), 90).convert("RGB")
    assert desplazamiento(a, b) is None
    assert desplazamiento(a, a.copy()) == 0


def test_ver_pantalla_devuelve_solo_la_zona_a_tamano_real(monkeypatch):
    async def bajar(ruta):
        return Image.new("RGB", (1920, 1080), "white")
    monkeypatch.setattr(mcp_servidor, "_bajar", bajar)
    texto, img = asyncio.run(mcp_servidor.ver_pantalla(x=100, y=200, ancho=600, alto=300))
    assert "600×300" in texto and "(100, 200)" in texto
    assert Image.open(io.BytesIO(img.data)).size == (600, 300)


def test_recorrer_pantalla_devuelve_cada_pagina_con_lo_que_subio(monkeypatch):
    async def llamar(metodo, ruta, cuerpo=None, timeout=60):
        assert ruta == "/api/recorrer" and cuerpo["ancho"] == 500
        return {"id": "abc", "paginas": 2, "subio": [None, 120], "final": True, "pasos": 4}

    async def bajar(ruta):
        assert ruta.startswith("/api/recorridos/abc/")
        return Image.new("RGB", (500, 400), "white")
    monkeypatch.setattr(mcp_servidor, "_llamar", llamar)
    monkeypatch.setattr(mcp_servidor, "_bajar", bajar)
    salida = asyncio.run(mcp_servidor.recorrer_pantalla(x=10, y=20, ancho=500, alto=400))
    textos = [s for s in salida if isinstance(s, str)]
    assert len(salida) - len(textos) == 2  # dos imágenes
    assert "120 px" in textos[1] and "final" in textos[-1].lower()


def test_lo_que_recorrer_pantalla_le_manda_cubre_todas_las_lineas_sin_repetir_paginas_enteras(monkeypatch):
    # El puente sigue bajando con solape (lo necesita para medir cuánto subió),
    # pero de la segunda página en adelante sólo le manda lo nuevo y una franja
    # para empalmar. Ninguna línea puede quedarse sin llegarle.
    ancho = 1600  # sin pasar de ANCHO_IMAGEN: así no se reduce y lo recortado se mide en px de la zona
    with puente_simulado(lineas=300) as (c, sim):
        mcp_contra(c, monkeypatch)
        dar(c)
        arribas = [sim.editor.arriba]
        girar = sim.rueda

        async def rueda(pasos):
            await girar(pasos)
            arribas.append(sim.editor.arriba)
        monkeypatch.setattr(sim, "rueda", rueda)
        salida = asyncio.run(mcp_servidor.recorrer_pantalla(x=X, y=Y, ancho=ancho, alto=H, max_paginas=20))
        assert "final" in salida[-1].lower()
        pares = list(zip(salida[:-1:2], salida[1:-1:2]))
        recortadas = 0
        vistas = set()
        for k, (texto, img) in enumerate(pares):
            w, h = Image.open(io.BytesIO(img.data)).size
            assert w == ancho
            corte = H - h
            if corte:
                recortadas += 1
                m = re.search(r"subió (\d+) px\. Te llega desde (\d+) px.*primeros (\d+) px repiten", texto)
                assert m and int(m[2]) == corte, texto
                assert int(m[3]) == H - int(m[1]) - corte >= max(H // 8, 64)
            # Cada línea del editor simulado ocupa su fila a partir de 4 px del borde de arriba.
            for fila in range(sim.editor.filas):
                if 4 + fila * ALTO_LINEA >= corte and 4 + (fila + 1) * ALTO_LINEA <= H:
                    vistas.add(arribas[k] + fila)
        assert vistas >= set(range(len(sim.editor.lineas)))
        assert recortadas >= len(pares) - 2  # todas menos la primera (y, si acaso, la última)


@pytest.mark.parametrize("subio", [None, 0, 400, 900])
def test_una_pagina_sin_medida_de_lo_que_subio_o_sin_nada_en_comun_llega_entera(monkeypatch, subio):
    async def llamar(metodo, ruta, cuerpo=None, timeout=60):
        return {"id": "abc", "paginas": 2, "subio": [None, subio], "final": True, "pasos": 4}

    async def bajar(ruta):
        return Image.new("RGB", (500, 400), "white")
    monkeypatch.setattr(mcp_servidor, "_llamar", llamar)
    monkeypatch.setattr(mcp_servidor, "_bajar", bajar)
    salida = asyncio.run(mcp_servidor.recorrer_pantalla(x=10, y=20, ancho=500, alto=400))
    assert [Image.open(io.BytesIO(i.data)).size for i in salida if not isinstance(i, str)] == [(500, 400)] * 2
    assert "Te llega desde" not in salida[2]


def test_una_pagina_que_subio_poco_llega_sin_lo_repetido_salvo_la_franja_para_empalmar(monkeypatch):
    async def llamar(metodo, ruta, cuerpo=None, timeout=60):
        return {"id": "abc", "paginas": 2, "subio": [None, 300], "final": True, "pasos": 4}

    async def bajar(ruta):
        return Image.new("RGB", (500, 400), "white")
    monkeypatch.setattr(mcp_servidor, "_llamar", llamar)
    monkeypatch.setattr(mcp_servidor, "_bajar", bajar)
    salida = asyncio.run(mcp_servidor.recorrer_pantalla(x=10, y=20, ancho=500, alto=400))
    # 400 − 300 = 100 px ya vistos; se quedan 64 (un octavo de 400 es menos) para empalmar.
    assert Image.open(io.BytesIO(salida[3].data)).size == (500, 364)
    assert "desde 36 px" in salida[2] and "primeros 64 px repiten" in salida[2]


@pytest.mark.parametrize("de_menos", [40, 200])
def test_si_la_medida_de_lo_que_subio_se_queda_corta_la_pagina_llega_entera_y_no_se_pierde_ninguna_linea(
        monkeypatch, de_menos):
    # `desplazamiento` mide en una copia reducida. Si se quedara corto —por menos
    # del margen para empalmar (40) o por más (200)—, recortar a ciegas se llevaría
    # filas nuevas: lo recortado se comprueba contra la página anterior entera.
    ancho = 1600
    with puente_simulado(lineas=300) as (c, sim):
        mcp_contra(c, monkeypatch)
        dar(c)
        arribas = [sim.editor.arriba]
        girar = sim.rueda

        async def rueda(pasos):
            await girar(pasos)
            arribas.append(sim.editor.arriba)
        monkeypatch.setattr(sim, "rueda", rueda)
        llamar = mcp_servidor._llamar

        async def corta(metodo, ruta, cuerpo=None, timeout=60):
            r = await llamar(metodo, ruta, cuerpo, timeout)
            if ruta == "/api/recorrer":
                r["subio"] = [s if not s else max(1, s - de_menos) for s in r["subio"]]
            return r
        monkeypatch.setattr(mcp_servidor, "_llamar", corta)
        salida = asyncio.run(mcp_servidor.recorrer_pantalla(x=X, y=Y, ancho=ancho, alto=H, max_paginas=20))
        pares = list(zip(salida[:-1:2], salida[1:-1:2]))
        vistas = set()
        for k, (texto, img) in enumerate(pares):
            corte = H - Image.open(io.BytesIO(img.data)).size[1]
            if k:
                assert corte == 0 and "no casa del todo" in texto, texto
            for fila in range(sim.editor.filas):
                if 4 + fila * ALTO_LINEA >= corte and 4 + (fila + 1) * ALTO_LINEA <= H:
                    vistas.add(arribas[k] + fila)
        assert vistas >= set(range(len(sim.editor.lineas)))
