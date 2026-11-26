"""El recorrido completo contra el Mac simulado, por la API, como lo haría Claude.

Leer → transcribir → verificar con la huella → proponer → aprobar (la
persona) → escribir → guardar (la persona) → verificar otra vez. Y las
puertas: sin control no se toca nada, sin aprobación no se escribe, Claude no
puede aprobar ni darse el control, y Parar corta a mitad.
"""

import asyncio
import io
import time

import pytest
from PIL import Image

from puente_kvm import cambios, mcp_servidor
from puente_kvm.motor import filas_cambiadas

from .ayuda import PERSONA, esperar, leer, mcp_contra, puente_simulado, transcribir_como_oraculo


@pytest.fixture
def entorno():
    with puente_simulado() as (c, sim):
        yield c, sim


def test_lee_el_documento_entero_y_la_copia_es_exacta_segun_la_huella(entorno):
    c, sim = entorno
    lid = leer(c)
    r = c.get(f"/api/lecturas/{lid}").json()
    assert r["estado"] == "capturada"
    assert r["paginas"] >= len(sim.editor.guardado) // sim.editor.filas + 1
    transcribir_como_oraculo(c, sim, lid)
    r = c.get(f"/api/lecturas/{lid}").json()
    assert r["completo"] and r["lineas"] == len(sim.editor.guardado) and r["conflictos"] == 0
    h = c.post(f"/api/lecturas/{lid}/huella", json={"referencia": sim.estado()["huella_base"]}).json()
    assert h["verificada"]
    assert c.get(f"/api/lecturas/{lid}/texto").text.splitlines() == sim.editor.guardado


def test_una_letra_mal_leida_no_pasa_la_huella(entorno):
    c, sim = entorno
    lid = leer(c)
    transcribir_como_oraculo(c, sim, lid, estropear=45)
    h = c.post(f"/api/lecturas/{lid}/huella", json={"referencia": sim.estado()["huella_base"]}).json()
    assert not h["verificada"]


def test_escribe_solo_lo_aprobado_y_la_base_queda_con_exactamente_lo_acordado(entorno):
    c, sim = entorno
    lid = leer(c)
    transcribir_como_oraculo(c, sim, lid)
    assert c.post(f"/api/lecturas/{lid}/huella", json={"referencia": sim.estado()["huella_base"]}).json()["verificada"]

    original = list(sim.editor.guardado)
    nuevo = list(original)
    nuevo[20] = nuevo[20] + "  -- revisado: año fiscal"  # cambiar una línea
    nuevo[60:60] = ["    -- Señal nueva: ¿cuadra?", "    SET @Filas = 0;"]  # insertar
    del nuevo[100]  # borrar
    nuevo[-1] = "END; -- fin"  # tocar la última
    r = c.post("/api/cambios", json={"lectura": lid, "texto": "\n".join(nuevo), "descripcion": "Prueba"})
    assert r.status_code == 200, r.text
    cid = r.json()["id"]

    # Claude no puede escribir lo que la persona no aprobó, ni aprobárselo.
    assert c.post(f"/api/cambios/{cid}/escribir").status_code == 400
    assert c.post(f"/api/cambios/{cid}/aprobar").status_code == 403
    assert c.post(f"/api/cambios/{cid}/aprobar", headers=PERSONA).status_code == 200

    c.post("/api/control", json={"accion": "dar"}, headers=PERSONA)
    assert c.post(f"/api/cambios/{cid}/escribir").status_code == 200
    esperar(c)
    cambio = c.get(f"/api/cambios/{cid}").json()
    assert cambio["estado"] == "escrito", cambio["error"]
    assert sim.editor.lineas == nuevo
    assert sim.editor.guardado == original  # escrito no es guardado

    c.post("/api/simulador/guardar", headers=PERSONA)
    h = c.post(f"/api/cambios/{cid}/huella", json={"referencia": sim.estado()["huella_base"]}).json()
    assert h["verificado"]


def test_si_la_pantalla_no_es_la_que_se_leyo_no_escribe_nada(entorno):
    c, sim = entorno
    lid = leer(c)
    transcribir_como_oraculo(c, sim, lid)
    nuevo = list(sim.editor.guardado)
    nuevo[10] = "-- cambio"
    cid = c.post("/api/cambios", json={"lectura": lid, "texto": "\n".join(nuevo), "descripcion": "x"}).json()["id"]
    c.post(f"/api/cambios/{cid}/aprobar", headers=PERSONA)
    # Alguien toca el documento entre la lectura y la escritura.
    sim.editor.lineas[2] = "    @FechaCorte DATETIME,"
    sim.editor.version += 1
    antes = list(sim.editor.lineas)
    c.post("/api/control", json={"accion": "dar"}, headers=PERSONA)
    c.post(f"/api/cambios/{cid}/escribir")
    esperar(c)
    cambio = c.get(f"/api/cambios/{cid}").json()
    assert cambio["estado"] == "fallido"
    assert "no es la que se leyó" in cambio["error"]
    assert sim.editor.lineas == antes


def test_sin_control_claude_no_puede_tocar_el_mac_ni_darse_el_control(entorno):
    c, sim = entorno
    r = c.post("/api/teclear", json={"texto": "hola"})
    assert r.status_code == 423
    assert c.post("/api/control", json={"accion": "dar"}).status_code == 403
    assert c.post("/api/lecturas", json={"nombre": "x"}).status_code == 423
    assert sim.pulsaciones == 0


def test_otra_pestana_del_navegador_no_puede_teclear(entorno):
    c, _ = entorno
    c.post("/api/control", json={"accion": "dar"}, headers=PERSONA)
    r = c.post("/api/teclear", json={"texto": "x"}, headers={"Origin": "http://malo.example"})
    assert r.status_code == 403


def test_parar_corta_una_lectura_a_medias(entorno):
    c, sim = entorno
    c.post("/api/control", json={"accion": "dar"}, headers=PERSONA)
    lid = c.post("/api/lecturas", json={"nombre": "larga"}).json()["id"]
    time.sleep(0.4)
    c.post("/api/control", json={"accion": "parar"}, headers=PERSONA)
    esperar(c)
    r = c.get(f"/api/lecturas/{lid}").json()
    assert r["estado"] == "cortada"
    pulsaciones = sim.pulsaciones
    time.sleep(0.3)
    assert sim.pulsaciones == pulsaciones  # ya no sale ninguna tecla


def test_las_paginas_del_html_se_sirven(entorno):
    c, sim = entorno
    lid = leer(c)
    assert c.get("/").status_code == 200
    assert c.get(f"/lecturas/{lid}").status_code == 200
    assert c.get("/ajustes").status_code == 200
    assert c.get("/api/pantalla.jpg").headers["content-type"] == "image/jpeg"


def test_el_control_vuelve_solo_a_la_persona_si_claude_no_hace_nada(entorno, monkeypatch):
    c, sim = entorno
    from puente_kvm import control

    c.post("/api/control", json={"accion": "dar"}, headers=PERSONA)
    assert c.post("/api/atajo", json={"atajo": "down"}).status_code == 200
    monkeypatch.setattr(control, "INACTIVIDAD_S", 0)
    time.sleep(0.05)
    assert c.get("/api/estado").json()["control"]["modo"] == "libre"
    assert c.post("/api/teclear", json={"texto": "x"}).status_code == 423


def test_sin_hooks_de_claude_al_terminar_de_leer_o_de_escribir_el_mac_vuelve_a_la_persona(entorno):
    """Sin conversación del registro ni hooks, el puente no sabe qué turno corre:
    cada tarea devuelve el Mac, como antes de C-0486. Con hooks, lo devuelve el
    final del encargo (`test_control_por_turno.py`)."""
    c, sim = entorno
    lid = leer(c)
    assert c.get("/api/estado").json()["control"]["modo"] == "libre"
    transcribir_como_oraculo(c, sim, lid)
    nuevo = list(sim.editor.guardado)
    nuevo[5] = nuevo[5] + " -- x"
    cid = c.post("/api/cambios", json={"lectura": lid, "texto": "\n".join(nuevo), "descripcion": "x"}).json()["id"]
    c.post(f"/api/cambios/{cid}/aprobar", headers=PERSONA)
    assert c.post(f"/api/cambios/{cid}/escribir").status_code == 423  # sin control, ni aprobado basta
    c.post("/api/control", json={"accion": "dar"}, headers=PERSONA)
    c.post(f"/api/cambios/{cid}/escribir")
    esperar(c)
    assert c.get(f"/api/cambios/{cid}").json()["estado"] == "escrito"
    assert c.get("/api/estado").json()["control"]["modo"] == "libre"


# ── lo que se le enseña a Claude de cada tramo (C-0474) ─────────────────────
def cuatro_tramos(original: list[str]) -> list[str]:
    """El cambio de arriba: cambiar una línea, insertar dos, borrar una y tocar la última."""
    nuevo = list(original)
    nuevo[20] = nuevo[20] + "  -- revisado: año fiscal"
    nuevo[60:60] = ["    -- Señal nueva: ¿cuadra?", "    SET @Filas = 0;"]
    del nuevo[100]
    nuevo[-1] = "END; -- fin"
    return nuevo


def escribir_cambio(c, sim, nuevo: list[str], verificar: bool = True) -> str:
    lid = leer(c)
    transcribir_como_oraculo(c, sim, lid, estropear=None if verificar else 46)
    if verificar:
        assert c.post(f"/api/lecturas/{lid}/huella",
                      json={"referencia": sim.estado()["huella_base"]}).json()["verificada"]
    cid = c.post("/api/cambios", json={"lectura": lid, "texto": "\n".join(nuevo), "descripcion": "x"}).json()["id"]
    assert c.post(f"/api/cambios/{cid}/aprobar", headers=PERSONA).status_code == 200
    c.post("/api/control", json={"accion": "dar"}, headers=PERSONA)
    assert c.post(f"/api/cambios/{cid}/escribir").status_code == 200
    esperar(c)
    assert c.get(f"/api/cambios/{cid}").json()["estado"] == "escrito"
    return cid


def png(dato) -> Image.Image:
    return Image.open(io.BytesIO(dato.data if hasattr(dato, "data") else dato)).convert("RGB")


def test_ver_tramo_ensena_solo_las_filas_que_cambiaron_y_fuera_de_ellas_todo_quedo_igual(monkeypatch):
    with puente_simulado() as (c, sim):
        mcp_contra(c, monkeypatch)
        vistas = []
        capturar = cambios._vista

        async def vista(motor, cambio, zona):
            img = await capturar(motor, cambio, zona)
            vistas.append(img)
            return img
        monkeypatch.setattr(cambios, "_vista", vista)
        cid = escribir_cambio(c, sim, cuatro_tramos(sim.editor.guardado))
        tramos = c.get(f"/api/cambios/{cid}").json()["tramos"]
        # Se escriben de abajo arriba: la primera vista es la del tramo más bajo.
        antes = dict(zip(sorted((t["i"] for t in tramos), key=lambda i: -tramos[i - 1]["desde"]), vistas))
        recortados = 0
        for t in tramos:
            entera = png(c.get(f"/api/cambios/{cid}/tramos/{t['i']}.png").content)
            texto, img = asyncio.run(mcp_servidor.ver_tramo(cid, t["i"]))
            desde, hasta = t["franja"]
            cambiadas = filas_cambiadas(antes[t["i"]], entera)
            assert cambiadas and desde <= cambiadas[0] and cambiadas[1] <= hasta  # nada cambiado se queda fuera
            if desde == 0 and hasta == entera.height:
                assert png(img).size == entera.size and "de arriba abajo" in texto
                continue
            recortados += 1
            assert f"filas {desde}–{hasta} px" in texto and "por debajo del umbral de ruido" in texto
            assert png(img).tobytes() == entera.crop((0, desde, entera.width, hasta)).tobytes()
            # Lo que no se le manda está igual que antes de teclear el tramo.
            for zona in ((0, 0, entera.width, desde), (0, hasta, entera.width, entera.height)):
                if zona[1] < zona[3]:
                    assert filas_cambiadas(antes[t["i"]].crop(zona), entera.crop(zona)) is None
        # El que cambia una línea y el que toca la última: unas pocas filas, no el editor entero.
        for i in (1, 4):
            desde, hasta = tramos[i - 1]["franja"]
            assert hasta - desde <= 6 * 27
        assert recortados >= 2


def test_un_tramo_que_no_cambia_nada_visible_llega_entero_y_lo_dice(monkeypatch):
    # La lectura se transcribió mal (línea 46) y no se verificó: el «cambio» que la
    # corrige teclea justo lo que ya hay en la pantalla. Eso es lo que hay que ver.
    with puente_simulado() as (c, sim):
        mcp_contra(c, monkeypatch)
        cid = escribir_cambio(c, sim, list(sim.editor.guardado), verificar=False)
        tramo = c.get(f"/api/cambios/{cid}").json()["tramos"][0]
        assert tramo["franja"] == []
        texto, img = asyncio.run(mcp_servidor.ver_tramo(cid, tramo["i"]))
        assert png(img).size == (1620, 952)
        assert "apenas cambió nada visible" in texto and "quizá sólo el cursor" in texto


def test_la_web_y_ver_tramo_con_entera_dan_la_captura_entera(monkeypatch):
    with puente_simulado() as (c, sim):
        mcp_contra(c, monkeypatch)
        cid = escribir_cambio(c, sim, cuatro_tramos(sim.editor.guardado))
        web = png(c.get(f"/api/cambios/{cid}/tramos/1.png").content)
        assert web.size == (1620, 952)
        texto, img = asyncio.run(mcp_servidor.ver_tramo(cid, 1, entera=True))
        assert png(img).tobytes() == web.tobytes() and "entera" in texto
        assert c.get(f"/cambios/{cid}").status_code == 200


@pytest.mark.parametrize("franja,dice", [(None, "no sé qué cambió"), ([0, 952], "de arriba abajo")])
def test_un_tramo_sin_franja_o_que_cambio_de_arriba_abajo_llega_entero(monkeypatch, franja, dice):
    async def llamar(metodo, ruta, cuerpo=None, timeout=60):
        return {"tramos": [{"i": 1, "desde": 5, "hasta": 5, "franja": franja}]}

    async def bajar(ruta):
        return Image.new("RGB", (1620, 952), "white")
    monkeypatch.setattr(mcp_servidor, "_llamar", llamar)
    monkeypatch.setattr(mcp_servidor, "_bajar", bajar)
    texto, img = asyncio.run(mcp_servidor.ver_tramo("x", 1))
    assert png(img).size == (1620, 952) and dice in texto


# Lo que llegaba al Mac simulado al escribir `cuatro_tramos` con el código de
# antes de C-0474 (`d9856b8`): 360 sucesos de teclado, ratón y rueda, en orden,
# medido por el revisor y recalculado con ese código el 22-nov. Si algún día se
# cambia a propósito lo que se teclea, se actualiza aquí a sabiendas.
TECLAS_DE_SIEMPRE = (360, "d7c34b3c97618a577b8361093249a7c6226ca8d6eddb8b4b05dfc86e353b8740")


def test_escribir_un_cambio_manda_al_mac_exactamente_las_teclas_de_antes_de_capturar_el_tramo():
    # Es la pieza que escribe en el Mac: la captura de antes de cada tramo sólo
    # mira, y lo que llega al aparato tiene que ser lo de siempre.
    import hashlib

    with puente_simulado() as (c, sim):
        nuevo = cuatro_tramos(sim.editor.guardado)
        lid = leer(c)
        transcribir_como_oraculo(c, sim, lid)
        cid = c.post("/api/cambios", json={"lectura": lid, "texto": "\n".join(nuevo), "descripcion": "x"}).json()["id"]
        c.post(f"/api/cambios/{cid}/aprobar", headers=PERSONA)
        c.post("/api/control", json={"accion": "dar"}, headers=PERSONA)
        sucesos = []
        teclado, raton, rueda = sim.informe_teclado, sim.raton, sim.rueda

        async def informe_teclado(mods, teclas):
            sucesos.append(("t", mods, tuple(teclas)))
            await teclado(mods, teclas)

        async def mover(x, y, botones=0):
            sucesos.append(("r", x, y, botones))
            await raton(x, y, botones)

        async def girar(pasos):
            sucesos.append(("w", pasos))
            await rueda(pasos)
        sim.informe_teclado, sim.raton, sim.rueda = informe_teclado, mover, girar
        c.post(f"/api/cambios/{cid}/escribir")
        esperar(c)
        assert c.get(f"/api/cambios/{cid}").json()["estado"] == "escrito"
        assert sim.editor.lineas == nuevo
        assert (len(sucesos), hashlib.sha256(repr(sucesos).encode()).hexdigest()) == TECLAS_DE_SIEMPRE


def test_si_comparar_el_tramo_falla_el_cambio_se_escribe_igual_y_el_tramo_llega_entero(monkeypatch):
    def rota(*_):
        raise MemoryError("sin memoria para comparar")
    monkeypatch.setattr(cambios, "franja", rota)
    with puente_simulado() as (c, sim):
        mcp_contra(c, monkeypatch)
        nuevo = cuatro_tramos(sim.editor.guardado)
        cid = escribir_cambio(c, sim, nuevo)  # comprueba que queda «escrito»
        assert sim.editor.lineas == nuevo
        tramos = c.get(f"/api/cambios/{cid}").json()["tramos"]
        assert all(t["estado"] == "escrito" and t["franja"] is None for t in tramos)
        texto, img = asyncio.run(mcp_servidor.ver_tramo(cid, 1))
        assert png(img).size == (1620, 952) and "entera" in texto
        fallos = [e for e in c.get("/api/bitacora").json() if "no pude comparar el tramo" in e["detalle"]]
        assert len(fallos) == len(tramos) and all(e["cambio"] == cid for e in fallos)


def test_un_cursor_que_parpadea_entre_las_dos_capturas_no_se_ensena_como_lo_que_cambio(monkeypatch):
    # En un editor real el cursor parpadea: si sale en la captura de antes y no en
    # la de después, son 2 px de ancho «cambiados». Si eso fuera la franja, Claude
    # vería una tira con el cursor y nada de lo escrito.
    from PIL import ImageDraw

    with puente_simulado() as (c, sim):
        mcp_contra(c, monkeypatch)
        capturar = cambios._vista

        async def con_cursor(motor, cambio, zona):
            img = await capturar(motor, cambio, zona)
            ImageDraw.Draw(img).rectangle([600, 400, 601, 421], fill="#000")  # 2×22, como el del simulador
            return img
        monkeypatch.setattr(cambios, "_vista", con_cursor)
        cid = escribir_cambio(c, sim, list(sim.editor.guardado), verificar=False)  # teclea lo que ya había
        tramo = c.get(f"/api/cambios/{cid}").json()["tramos"][0]
        assert tramo["franja"] == []
        texto, img = asyncio.run(mcp_servidor.ver_tramo(cid, tramo["i"]))
        assert png(img).size == (1620, 952) and "quizá sólo el cursor" in texto


def test_una_caja_cambiada_de_la_anchura_de_un_cursor_no_es_franja_y_una_letra_si():
    from PIL import ImageDraw

    antes = Image.new("RGB", (400, 300), "white")
    cursor, letra = antes.copy(), antes.copy()
    ImageDraw.Draw(cursor).rectangle([100, 50, 101 + cambios.ANCHO_CURSOR - 2, 71], fill="#000")
    ImageDraw.Draw(letra).rectangle([100, 50, 111, 71], fill="#000")  # ~ el ancho de un carácter
    assert cambios.franja(antes, cursor, 27) == []
    assert cambios.franja(antes, letra, 27) == [0, 72 + 54]
