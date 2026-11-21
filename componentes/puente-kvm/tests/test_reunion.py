"""Grabar una reunión del Mac con el botón de la persona (C-0461).

Lo grabado lo procesa Reuniones del hub, que lee la carpeta en su sitio: el
contrato (`meta.json` con `fin` lo último, `reunion.wav`, `fotos/%06d.jpg`)
es lo que aquí se comprueba.
"""

import asyncio
import json
import math
import struct
import time
import wave

import pytest
from PIL import Image

from puente_kvm import comprobar, reunion
from puente_kvm.dispositivo import AparatoNoDisponible
from puente_kvm.simulador import Simulador

from .ayuda import PERSONA, puente_simulado


def tono(segundos: float, amplitud: int = 8000) -> bytes:
    n = round(segundos * reunion.TASA)
    return struct.pack(f"<{n}h", *(round(amplitud * math.sin(2 * math.pi * 440 * i / reunion.TASA)) for i in range(n)))


def oir_por_paquetes(g: reunion.Grabacion, desde: float, segundos: float, vaiven: float = 0.0) -> None:
    """Como llega del JetKVM: 20 ms por paquete, cada uno a su hora (y con algo de retraso si se pide)."""
    paquete = tono(0.02)
    for k in range(round(segundos / 0.02)):
        g.oir(paquete, desde + (k + 1) * 0.02 + (vaiven if k % 7 == 3 else 0.0))


def leer_wav(ruta) -> tuple[int, bytes]:
    with wave.open(str(ruta)) as w:
        assert (w.getnchannels(), w.getsampwidth(), w.getframerate()) == (1, 2, 16000)
        return w.getnframes(), w.readframes(w.getnframes())


def energia(datos: bytes, desde_s: float, hasta_s: float) -> float:
    a, b = round(desde_s * reunion.TASA) * 2, round(hasta_s * reunion.TASA) * 2
    trozo = struct.unpack(f"<{(b - a) // 2}h", datos[a:b])
    return sum(abs(x) for x in trozo) / max(1, len(trozo))


def test_el_silencio_del_mac_se_pone_por_la_hora_de_llegada():
    # En silencio el JetKVM no manda nada y su reloj no avanza: sin rellenar,
    # la grabación se encogería y lo dicho no casaría con las fotos.
    t0 = 1_800_000_000.0
    g = reunion.Grabacion(ahora=t0)
    oir_por_paquetes(g, t0, 1.0)
    oir_por_paquetes(g, t0 + 3.0, 1.0)
    g.terminar(fin=t0 + 5.0)
    n, datos = leer_wav(g.dir / "reunion.wav")
    assert abs(n / reunion.TASA - 5.0) < 0.05
    assert energia(datos, 0.1, 0.9) > 3000
    assert energia(datos, 1.2, 2.8) == 0
    assert energia(datos, 3.1, 3.9) > 3000
    assert energia(datos, 4.2, 4.9) == 0


def test_el_vaiven_de_la_red_no_mete_cortes():
    t0 = 1_800_000_000.0
    g = reunion.Grabacion(ahora=t0)
    oir_por_paquetes(g, t0, 2.0, vaiven=0.15)
    assert g.muestras == round(2.0 * reunion.TASA)  # ni una muestra de silencio en medio


def test_las_fotos_se_guardan_solo_cuando_la_pantalla_cambia():
    t0 = 1_800_000_000.0
    g = reunion.Grabacion(ahora=t0)
    blanca, negra = Image.new("RGB", (1920, 1080), "white"), Image.new("RGB", (1920, 1080), "black")
    assert g.mirar(blanca, t0 + 0.4)
    assert not g.mirar(blanca, t0 + 1.4)
    assert g.mirar(negra, t0 + 75.2)
    fotos = sorted(f.name for f in (g.dir / "fotos").iterdir())
    assert fotos == ["000000.jpg", "000075.jpg"]
    assert Image.open(g.dir / "fotos" / "000075.jpg").width == reunion.ANCHO_FOTO


def test_la_carpeta_cumple_el_contrato_de_reuniones_y_fin_va_lo_ultimo():
    t0 = 1_800_000_000.0
    g = reunion.Grabacion(titulo="  Revisión semanal ", ahora=t0)
    meta = json.loads((g.dir / "meta.json").read_text())
    assert "fin" not in meta  # mientras graba, Reuniones no la toca
    assert g.id.endswith("-kvm") and g.dir.parent == reunion.raiz()
    oir_por_paquetes(g, t0, 0.5)
    r = g.terminar(fin=t0 + 60)
    meta = json.loads((g.dir / "meta.json").read_text())
    assert meta["fin"] == t0 + 60 and meta["inicio"] == t0
    assert meta["origen"] == "jetkvm" and meta["proceso"]["nombre"] == "Mac (JetKVM)"
    assert meta["titulo"] == "Revisión semanal" and meta["con_sonido"] is True
    assert r == {"id": g.id, "segundos": 60, "fotos": 0, "con_sonido": True, "cortada": ""}
    assert not (g.dir / "micro.wav").exists()  # su voz no pasa por el JetKVM


def test_dos_seguidas_en_el_mismo_segundo_no_se_pisan():
    t0 = 1_800_000_000.0
    a = reunion.Grabacion(ahora=t0)
    a.terminar(fin=t0)
    b = reunion.Grabacion(ahora=t0)
    assert a.id != b.id and b.inicio == t0 + 1


def test_la_que_se_corto_a_medias_se_cierra_al_arrancar_y_se_puede_procesar():
    g = reunion.Grabacion(ahora=time.time() - 30)
    t0 = g.inicio  # en segundos enteros, como su id
    oir_por_paquetes(g, t0, 1.0)
    g._wav.close()  # el proceso murió: la cabecera sigue diciendo 0 muestras
    assert reunion.cerrar_cortadas() == [g.id]
    meta = json.loads((g.dir / "meta.json").read_text())
    assert meta["fin"] >= t0 and meta["cortada"] and meta["origen"] == "jetkvm"
    n, _ = leer_wav(g.dir / "reunion.wav")
    assert n == reunion.TASA
    assert reunion.cerrar_cortadas() == []  # y no se vuelve a tocar


def test_la_persona_empieza_y_termina_la_reunion_y_mientras_el_puente_esta_ocupado():
    with puente_simulado(lineas=3) as (c, sim):
        assert c.get("/api/estado").json()["reunion"] == {"grabando": False, "ultima": None}
        r = c.post("/api/reunion/empezar", json={}, headers=PERSONA)
        assert r.status_code == 200, r.text
        assert r.json()["grabando"] and sim.sonido
        sim.sonar(tono(0.5), time.time())
        estado = c.get("/api/estado").json()
        assert estado["reunion"]["con_sonido"]
        # Actualizar el hub no reinicia el puente a media reunión (decisión 442).
        assert comprobar.ocupado(estado) == "está grabando una reunión"
        assert c.post("/api/reunion/empezar", json={}, headers=PERSONA).status_code == 400
        time.sleep(1.2)  # al menos una foto de la pantalla
        r = c.post("/api/reunion/parar", headers=PERSONA)
        assert r.status_code == 200, r.text
        fin = r.json()
        assert fin["con_sonido"] and fin["fotos"] >= 1 and not sim.sonido
        d = reunion.raiz() / fin["id"]
        assert json.loads((d / "meta.json").read_text())["fin"]
        assert leer_wav(d / "reunion.wav")[0] >= 0.5 * reunion.TASA
        assert c.get("/api/estado").json()["reunion"]["ultima"]["id"] == fin["id"]


def test_grabar_lo_decide_la_persona_y_no_claude():
    with puente_simulado(lineas=3) as (c, sim):
        # Sin el Origin de la pantalla (así llama el MCP), no.
        assert c.post("/api/reunion/empezar", json={}).status_code == 403
        assert c.post("/api/reunion/parar").status_code == 403
        assert not sim.sonido


def test_el_mcp_no_tiene_nada_para_grabar_reuniones():
    from puente_kvm import mcp_servidor
    nombres = {t.name for t in mcp_servidor.mcp._tool_manager.list_tools()}
    assert nombres and not any("reunion" in n or "grabar" in n for n in nombres)


def test_con_una_tarea_de_claude_en_marcha_no_empieza():
    with puente_simulado(lineas=3) as (c, sim):
        c.app.state.puente.motor.tarea = "capturando"
        r = c.post("/api/reunion/empezar", json={}, headers=PERSONA)
        assert r.status_code == 409 and "capturando" in r.json()["detail"]
        assert not sim.sonido


def test_sin_parar_la_reunion_no_se_cambia_de_aparato():
    with puente_simulado(lineas=3) as (c, sim):
        assert c.post("/api/reunion/empezar", json={}, headers=PERSONA).status_code == 200
        r = c.post("/api/ajustes", json={"dispositivo": {"tipo": "jetkvm"}}, headers=PERSONA)
        assert r.status_code == 409 and "Salí de la reunión" in r.json()["detail"]
        assert c.post("/api/reunion/parar", headers=PERSONA).status_code == 200


def test_si_el_puente_se_para_grabando_la_reunion_queda_cerrada():
    with puente_simulado(lineas=3) as (c, sim):
        ident = c.post("/api/reunion/empezar", json={}, headers=PERSONA).json()["id"]
    meta = json.loads((reunion.raiz() / ident / "meta.json").read_text())
    assert meta["fin"] and "se paró" in meta["cortada"]


class MacQueReconecta(Simulador):
    """Como el JetKVM: el sonido sólo llega tras reconectar."""

    async def encender_sonido(self) -> bool:
        self.sonido = True
        return True


def test_mientras_se_conecta_el_sonido_no_se_puede_empezar_otra():
    # Dos pestañas, o la PC y el teléfono: la segunda dejaba una grabación huérfana.
    async def prueba():
        sim = MacQueReconecta(lineas=["x"])
        g = reunion.Grabadora(sim)
        suelta = asyncio.Event()

        async def reconectar():
            await suelta.wait()

        primera = asyncio.create_task(g.empezar("", reconectar))
        await asyncio.sleep(0.05)
        with pytest.raises(ValueError, match="ya se está grabando"):
            await g.empezar("", reconectar)
        suelta.set()
        await primera
        assert g.actual is not None
        await g.parar()
        assert len(list(reunion.raiz().iterdir())) == 1

    asyncio.run(prueba())


def test_si_no_llega_a_conectar_el_sonido_se_apaga_en_el_aparato():
    async def prueba():
        sim = MacQueReconecta(lineas=["x"])
        g = reunion.Grabadora(sim)

        async def reconectar():
            raise AparatoNoDisponible("el JetKVM no responde")

        with pytest.raises(AparatoNoDisponible):
            await g.empezar("", reconectar)
        assert not sim.sonido and g.actual is None and not g.empezando

    asyncio.run(prueba())


def test_tras_fin_no_se_guarda_ninguna_foto():
    g = reunion.Grabacion(ahora=1_800_000_000.0)
    g.terminar(fin=g.inicio + 5)
    assert not g.mirar(Image.new("RGB", (800, 600), "white"), g.inicio + 6)
    assert not any((g.dir / "fotos").iterdir())


def test_un_silencio_largo_no_se_escribe_de_golpe():
    # Media hora sin sonido son 57 MB: escritos en el bucle pararían el vídeo y el ratón.
    t0 = 1_800_000_000.0
    g = reunion.Grabacion(ahora=t0)
    oir_por_paquetes(g, t0, 0.2)
    antes = time.perf_counter()
    oir_por_paquetes(g, t0 + 1800, 0.2)
    assert time.perf_counter() - antes < 0.5
    g.terminar(fin=t0 + 1801)
    n, datos = leer_wav(g.dir / "reunion.wav")
    assert abs(n / reunion.TASA - 1801) < 0.1
    assert energia(datos, 0.05, 0.15) > 3000 and energia(datos, 900, 901) == 0


def test_guardar_ajustes_sin_cambiar_de_aparato_si_se_puede_mientras_graba():
    with puente_simulado(lineas=3) as (c, sim):
        assert c.post("/api/reunion/empezar", json={}, headers=PERSONA).status_code == 200
        ajustes = c.app.state.puente.ajustes
        r = c.post("/api/ajustes", json={"dispositivo": dict(ajustes["dispositivo"]), "perfil": dict(ajustes["perfil"])},
                   headers=PERSONA)
        assert r.status_code == 200, r.text
        assert c.post("/api/reunion/parar", headers=PERSONA).status_code == 200
