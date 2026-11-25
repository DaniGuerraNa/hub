"""El vídeo directo: las tramas H.264 del aparato, sin recomprimir, para el navegador (C-0469).

Contra el JetKVM falso, que codifica como el aparato (perfil High, una clave
cada medio segundo) y sabe hacer lo que el aparato podría hacer distinto
(Baseline, SPS sólo al empezar). Lo que importa además de que llegue: que
nunca le quite nada al decodificador del puente, del que viven las capturas de
Claude, las comprobaciones y las reuniones.
"""

import asyncio
import contextlib
import inspect
import json
import queue
import struct
import threading
import time

import av
import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from puente_kvm import video
from puente_kvm.app import crear_app
from puente_kvm.jetkvm import JetKVM
from puente_kvm.simulador import Simulador

from .ayuda import PERSONA, puente_simulado
from .jetkvm_falso import JetKVMFalso, sin_sps_ni_pps, tipos_nal


def correr(coro):
    return asyncio.run(asyncio.wait_for(coro, 90))


@contextlib.asynccontextmanager
async def conectado(**variantes):
    falso = JetKVMFalso(Simulador(lineas=["SELECT 1;"]))
    for k, v in variantes.items():
        setattr(falso, k, v)
    kvm = JetKVM(await falso.arrancar(), "secreta")
    try:
        await kvm.conectar()
        yield kvm, falso
    finally:
        await kvm.cerrar()
        await falso.parar()


def decodificables(tramas: list[video.Trama]) -> int:
    """Cuántos fotogramas saca un decodificador recién creado, como el del navegador."""
    d = av.CodecContext.create("h264", "r")
    return sum(len(d.decode(av.Packet(t.datos))) for t in tramas)


async def recibir(s: video.Suscripcion, n: int) -> list[video.Trama]:
    return [await asyncio.wait_for(s.siguiente(), 5) for _ in range(n)]


# ── con el JetKVM falso ─────────────────────────────────────────────────────
@pytest.mark.parametrize("perfil, codec", [("high", "avc1.64"), ("baseline", "avc1.42")])
def test_la_suscripcion_empieza_por_sps_pps_y_una_clave_y_dice_el_codec_real(perfil, codec):
    async def prueba():
        async with conectado(perfil=perfil) as (kvm, _):
            assert kvm.video == "h264" and kvm.estado()["video"] == "h264"
            s = kvm.video_codificado()
            tramas = await recibir(s, 20)
            assert tramas[0].clave and tipos_nal(tramas[0].datos)[:2] == [7, 8]
            assert 5 in tipos_nal(tramas[0].datos)
            assert tramas[0].codec.startswith(codec)
            # Un decodificador que empieza aquí lo saca todo, sin lo de antes.
            assert decodificables(tramas) == 20
            assert all(b.marca > a.marca for a, b in zip(tramas, tramas[1:]))
            s.cerrar()

    correr(prueba())


def test_si_el_aparato_solo_manda_el_sps_al_empezar_quien_llega_tarde_lo_recibe_igual():
    async def prueba():
        async with conectado(sps_solo_al_principio=True) as (kvm, _):
            await asyncio.sleep(1.2)  # ya pasaron la primera clave y su SPS
            s = kvm.video_codificado()
            tramas = await recibir(s, 20)
            assert tramas[0].clave and tipos_nal(tramas[0].datos)[:2] == [7, 8]
            # Las claves que siguen llegan sin él: es el guardado el que lo hace posible.
            assert all(7 not in tipos_nal(t.datos) for t in tramas[1:])
            assert decodificables(tramas) == 20

    correr(prueba())


def test_la_captura_sigue_al_dia_con_alguien_mirando_que_no_lee_nada():
    async def prueba():
        async with conectado() as (kvm, falso):
            lento = kvm.video_codificado()  # nunca lee: su cola se llena
            await asyncio.sleep(2)
            assert lento._cola.qsize() <= video.TOPE and lento.descartes > 0
            # Lo decodificado sigue llegando, y la captura ve lo que pasa ahora.
            assert kvm.estado()["ultimo_fotograma_s"] < 0.5
            falso.sim.editor.lineas = ["cambiado mientras alguien miraba"]
            falso.sim.editor.version += 1
            await asyncio.sleep(0.5)
            img = await kvm.captura()
            assert img.size == (1920, 1080)
            # Y al leer, empieza otra vez por una clave: nada a medias.
            t = await asyncio.wait_for(lento.siguiente(), 5)
            while not t.clave:  # lo que quedaba en su cola antes de descartar
                t = await asyncio.wait_for(lento.siguiente(), 5)
            assert tipos_nal(t.datos)[:2] == [7, 8]

    correr(prueba())


def test_si_derivar_falla_se_apaga_lo_dice_y_el_decodificador_sigue_intacto(monkeypatch):
    avisos = []

    def revienta(self, datos, marca):
        raise ValueError("trama rara")

    monkeypatch.setattr(video.Derivacion, "alimentar", revienta)

    async def prueba():
        falso = JetKVMFalso(Simulador(lineas=["x"]))
        kvm = JetKVM(await falso.arrancar(), "secreta")
        kvm.avisar = avisos.append
        try:
            await kvm.conectar()
            assert kvm.conectado  # el primer fotograma decodificado llegó igual
            t0 = kvm._trama_t
            await asyncio.sleep(0.6)
            assert kvm._trama_t > t0  # y siguen llegando
            assert (await kvm.captura()).size == (1920, 1080)
            assert kvm.video == "mjpeg" and kvm.video_codificado() is None
            assert "trama rara" in kvm.estado()["aviso_video"]
            assert len(avisos) == 1 and "imágenes" in avisos[0]
        finally:
            await kvm.cerrar()
            await falso.parar()

    correr(prueba())


def test_con_otra_version_de_aiortc_no_se_engancha_y_el_directo_va_por_imagenes(monkeypatch):
    import aiortc
    monkeypatch.setattr(aiortc, "__version__", "1.17.0")

    async def prueba():
        avisos = []
        falso = JetKVMFalso(Simulador(lineas=["x"]))
        kvm = JetKVM(await falso.arrancar(), "secreta")
        kvm.avisar = avisos.append
        try:
            await kvm.conectar()
            assert kvm.conectado and kvm.video == "mjpeg" and kvm.video_codificado() is None
            assert "1.17.0" in avisos[0]
        finally:
            await kvm.cerrar()
            await falso.parar()

    correr(prueba())


def test_aiortc_sigue_teniendo_la_cola_del_decodificador_que_se_envuelve():
    """🔴 Si esto falla, aiortc cambió por dentro: el directo iría por imágenes en
    silencio. Hay que volver a leer `rtcrtpreceiver.py` antes de mover la versión."""
    import aiortc
    from aiortc import RTCPeerConnection
    from aiortc.rtcrtpreceiver import decoder_worker

    assert aiortc.__version__.startswith(video.AIORTC_FIJADA)
    assert list(inspect.signature(decoder_worker).parameters)[:2] == ["loop", "input_q"]

    async def prueba():
        pc = RTCPeerConnection()
        t = pc.addTransceiver("video", direction="recvonly")
        assert isinstance(t.receiver._RTCRtpReceiver__decoder_queue, queue.Queue)
        await pc.close()

    correr(prueba())


# ── el reparto, sin red ─────────────────────────────────────────────────────
SPS_HIGH = b"\x67\x64\x00\x28\xac"
PPS_ = b"\x68\xee\x3c\x80"
INI = b"\x00\x00\x00\x01"


def au(*nales: bytes) -> bytes:
    return b"".join(INI + n for n in nales)


def test_si_se_llena_la_cola_descarta_hasta_la_siguiente_clave():
    async def prueba():
        d = video.Derivacion()
        s = d.suscribir(tope=3)
        d.alimentar(au(SPS_HIGH, PPS_, b"\x65clave1"), 0)
        for i in range(5):  # nadie lee: a la tercera se llena
            d.alimentar(au(b"\x41p" + bytes([i])), 3000 * (i + 1))
        assert s.descartes == 1 and s.esperando_clave
        d.alimentar(au(b"\x41perdida"), 30000)  # sin clave delante no sirve: no entra
        d.alimentar(au(b"\x65clave2"), 33000)  # la siguiente clave, sin SPS: se le pone el guardado
        primero = await s.siguiente()
        assert primero.clave and primero.datos == au(SPS_HIGH, PPS_, b"\x65clave2")
        assert primero.codec == "avc1.640028"

    correr(prueba())


def test_al_reconectar_quien_mira_espera_la_primera_clave_de_la_conexion_nueva():
    async def prueba():
        d = video.Derivacion()
        s = d.suscribir()
        d.alimentar(au(SPS_HIGH, PPS_, b"\x65a"), 0)
        d.alimentar(au(b"\x41b"), 3000)
        d.nueva_conexion()
        d.alimentar(au(b"\x41de-la-nueva-sin-clave"), 0)
        sps2 = b"\x67\x42\xe0\x1f\x00"
        d.alimentar(au(sps2, PPS_, b"\x65nueva"), 3000)
        t = await s.siguiente()
        assert t.datos == au(sps2, PPS_, b"\x65nueva") and t.codec == "avc1.42e01f"
        d.apagar("se acabó")
        assert await s.siguiente() is None and s.motivo == "se acabó"
        assert d.suscribir() is None

    correr(prueba())


def test_las_unidades_se_parten_con_codigos_de_inicio_de_3_y_de_4_bytes():
    datos = b"\x00\x00\x00\x01\x67\x64\x00\x28" + b"\x00\x00\x01\x68\xee" + b"\x00\x00\x00\x01\x65\x88"
    assert video.unidades(datos) == [b"\x67\x64\x00\x28", b"\x68\xee", b"\x65\x88"]
    assert tipos_nal(sin_sps_ni_pps(datos)) == [5]


# ── /ws/pantalla ────────────────────────────────────────────────────────────
@pytest.mark.parametrize("cabeceras", [{"Origin": "http://otra.web"},
                                       {"Origin": "http://otra.web", "Host": "otra.web"},
                                       {}])
def test_otra_web_ni_otro_nombre_abren_la_pantalla(cabeceras):
    with puente_simulado(lineas=3) as (c, _):
        with pytest.raises(WebSocketDisconnect) as e:
            with c.websocket_connect("/ws/pantalla", headers=cabeceras) as ws:
                ws.receive_text()
        assert e.value.code == 4403


def test_con_el_simulador_la_pantalla_dice_que_va_por_imagenes_y_mirar_no_es_usar_el_mac():
    with puente_simulado(lineas=3) as (c, _):
        assert c.get("/api/estado").json()["video"] == "mjpeg"
        with c.websocket_connect("/ws/pantalla", headers=PERSONA) as ws:
            assert "imágenes" in ws.receive_json()["no"]
        assert c.get("/api/estado").json()["mando"] is False


class FalsoAparte:
    """El falso en su propio hilo: el puente de `TestClient` corre en otro bucle."""

    def __init__(self, **variantes):
        self.falso = JetKVMFalso(Simulador(lineas=["SELECT 1;"]))
        for k, v in variantes.items():
            setattr(self.falso, k, v)
        self.bucle = asyncio.new_event_loop()
        threading.Thread(target=self.bucle.run_forever, daemon=True).start()
        self.url = asyncio.run_coroutine_threadsafe(self.falso.arrancar(), self.bucle).result(30)

    def poner_usb(self, valor: str):
        """El Mac se duerme o despierta solo, desde el hilo del falso (C-0477)."""
        self.bucle.call_soon_threadsafe(self.falso.poner_usb, valor)

    def poner_video(self, hay: bool):
        """La pantalla del Mac se enciende o se apaga, desde el hilo del falso."""
        self.bucle.call_soon_threadsafe(setattr, self.falso, "video", hay)

    def apagar(self):
        """El aparato se va (sin parar su hilo): `volver` lo arranca otra vez en su puerto."""
        asyncio.run_coroutine_threadsafe(self.falso.parar(), self.bucle).result(10)

    def volver(self):
        puerto = int(self.url.rsplit(":", 1)[1])
        asyncio.run_coroutine_threadsafe(self.falso.arrancar(puerto), self.bucle).result(30)

    def parar(self):
        with contextlib.suppress(Exception):
            self.apagar()
        self.bucle.call_soon_threadsafe(self.bucle.stop)


def test_la_pantalla_manda_el_codec_y_despues_tramas_que_empiezan_por_una_clave():
    falso = FalsoAparte()
    try:
        with TestClient(crear_app(JetKVM(falso.url, "secreta"), hosts={"testserver"})) as c:
            estado = c.get("/api/estado").json()
            assert estado["dispositivo"]["conectado"] and estado["video"] == "h264"
            with c.websocket_connect("/ws/pantalla", headers=PERSONA) as ws:
                cabecera = ws.receive_json()
                assert cabecera["codec"].startswith("avc1.64") and (cabecera["ancho"], cabecera["alto"]) == (1920, 1080)
                tramas = [ws.receive_bytes() for _ in range(10)]
                # Mirarla no es usar el Mac: se puede reiniciar el puente.
                assert c.get("/api/estado").json()["mando"] is False
            assert tramas[0][0] & 1 and tipos_nal(tramas[0][9:])[:2] == [7, 8]
            marcas = [struct.unpack(">Q", t[1:9])[0] for t in tramas]
            assert marcas == sorted(marcas) and len(set(marcas)) == 10
            d = av.CodecContext.create("h264", "r")
            assert sum(len(d.decode(av.Packet(t[9:]))) for t in tramas) == 10
    finally:
        falso.parar()


def test_cerrar_la_pantalla_suelta_su_suscripcion():
    falso = FalsoAparte()
    try:
        aparato = JetKVM(falso.url, "secreta")
        with TestClient(crear_app(aparato, hosts={"testserver"})) as c:
            assert aparato.conectado
            with c.websocket_connect("/ws/pantalla", headers=PERSONA) as ws:
                ws.receive_json()
                ws.receive_bytes()
                assert len(aparato.derivacion._suscripciones) == 1
            fin = time.time() + 5
            while aparato.derivacion._suscripciones and time.time() < fin:
                time.sleep(0.05)
            assert not aparato.derivacion._suscripciones
    finally:
        falso.parar()


def test_el_estado_no_lleva_el_video_a_la_bitacora_si_todo_va_bien():
    falso = FalsoAparte()
    try:
        with TestClient(crear_app(JetKVM(falso.url, "secreta"), hosts={"testserver"})) as c:
            entradas = c.get("/api/bitacora").json()
            assert not any("directo" in e["detalle"] for e in entradas)
            assert json.dumps(c.get("/api/estado").json()["dispositivo"]).count("aviso_video") == 0
    finally:
        falso.parar()


def test_parar_el_puente_no_espera_a_quien_mira_el_video():
    """El directo de imágenes no termina mientras se mira, y por eso el puente se
    para con un tope de 5 s (README, «Reiniciar con el botón»). El vídeo no
    necesita ese tope: al parar, su WebSocket se cierra en el acto."""
    import uvicorn
    from websockets.sync.client import connect

    from .conftest import puerto_libre

    falso = FalsoAparte()
    try:
        puerto = puerto_libre()
        app = crear_app(JetKVM(falso.url, "secreta"), hosts={f"127.0.0.1:{puerto}"})
        servidor = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=puerto, log_level="error"))
        hilo = threading.Thread(target=servidor.run, daemon=True)
        hilo.start()
        fin = time.time() + 30
        while not servidor.started and time.time() < fin:
            time.sleep(0.05)
        with connect(f"ws://127.0.0.1:{puerto}/ws/pantalla", origin=f"http://127.0.0.1:{puerto}") as ws:
            assert json.loads(ws.recv(timeout=10))["codec"].startswith("avc1.")
            ws.recv(timeout=5)
            t0 = time.monotonic()
            servidor.should_exit = True
            hilo.join(10)
            assert not hilo.is_alive() and time.monotonic() - t0 < 3
    finally:
        falso.parar()


def test_el_arnes_de_medir_no_corre_contra_los_datos_de_verdad(tmp_path):
    from pathlib import Path

    from .medir_directo import datos_de_verdad
    for entorno in ({}, {"PUENTE_HOME": str(Path.home() / ".local/share/puente-kvm")},
                    {"PUENTE_HOME": "~/.local/share/puente-kvm/"}):
        with pytest.raises(SystemExit):
            datos_de_verdad(entorno)
    datos_de_verdad({"PUENTE_HOME": str(tmp_path)})


@pytest.mark.parametrize("cabeceras, sale", [
    ({}, 200),                                          # las herramientas de Claude
    ({"Sec-Fetch-Site": "same-origin"}, 200),           # el <img> de la propia página
    ({"Sec-Fetch-Site": "none"}, 200),                  # la dirección escrita a mano
    ({"Sec-Fetch-Site": "cross-site"}, 403),            # otra web que la incrusta
    ({"Sec-Fetch-Site": "same-site"}, 403),             # otra web de 127.0.0.1, en otro puerto
    ({"Origin": "http://otra.web"}, 403),
])
@pytest.mark.parametrize("ruta", ["/api/pantalla.jpg", "/api/pantalla.png"])
def test_la_pantalla_por_get_solo_la_ve_esta_web(cabeceras, sale, ruta):
    with puente_simulado(lineas=3) as (c, _):
        assert c.get(ruta, headers=cabeceras).status_code == sale


def test_el_directo_de_imagenes_tampoco_sale_a_otra_web():
    with puente_simulado(lineas=3) as (c, _):
        assert c.get("/api/pantalla.mjpg", headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403
