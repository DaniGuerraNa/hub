"""El cliente del JetKVM contra un JetKVM falso por WebRTC de verdad (ver `jetkvm_falso`)."""

import asyncio
import time
import wave

import pytest

from puente_kvm import hid, reunion
from puente_kvm.dispositivo import AparatoNoDisponible
from puente_kvm.jetkvm import JetKVM
from puente_kvm.motor import diferencia_local
from puente_kvm.simulador import Simulador

from .jetkvm_falso import JetKVMFalso


def correr(coro):
    return asyncio.run(asyncio.wait_for(coro, 90))


def test_entra_ve_la_pantalla_teclea_y_hace_clic_como_la_web_del_aparato():
    async def prueba():
        sim = Simulador(lineas=["SELECT 1;", "", "-- fin"])
        falso = JetKVMFalso(sim)
        url = await falso.arrancar()
        kvm = JetKVM(url, "secreta")
        try:
            await kvm.conectar()
            assert kvm.conectado and kvm.version == "0.5.11-falso"

            # Ve la pantalla: el fotograma H.264 decodificado se parece a la del Mac.
            img = await kvm.captura()
            assert img.size == (1920, 1080)
            assert diferencia_local(img, await sim.captura()) < 0.5
            # Para el directo, reducida desde el vídeo y fuera del bucle.
            mini = await kvm.miniatura(1280)
            assert mini.size == (1280, 720) and mini.mode == "RGB"

            # Teclea por el canal binario: informe completo y luego soltar.
            await kvm.informe_teclado(0, [])
            for p in hid.secuencia("Año\n"):
                await kvm.informe_teclado(p.modificadores, [p.tecla])
                await asyncio.sleep(0.01)
                await kvm.informe_teclado(0, [])
                await asyncio.sleep(0.01)
            await asyncio.sleep(0.3)
            assert sim.editor.lineas[0] == "Año"

            # Clic absoluto: el puntero llega a las mismas coordenadas de pantalla.
            await kvm.raton(1500, 600, 0)
            await kvm.raton(1500, 600, 1)
            await kvm.raton(1500, 600, 0)
            await asyncio.sleep(0.3)
            assert abs(sim.puntero[0] - 1500) <= 1 and abs(sim.puntero[1] - 600) <= 1

            # La rueda va por JSON-RPC, con el signo del aparato (positivo sube).
            await kvm.rueda(2)
            assert any(r["method"] == "wheelReport" and r["params"]["wheelY"] == -1 for r in falso.rpc)
            # La de la persona, un solo informe y sin esperar (como su web), acotado al int8.
            antes = len(falso.rpc)
            await kvm.girar(5)
            await kvm.girar(-300)
            await asyncio.sleep(0.3)
            assert [r["params"]["wheelY"] for r in falso.rpc[antes:] if r["method"] == "wheelReport"] == [-5, 127]

            # El saludo HID fue lo primero en el canal binario, y nada viajó como texto.
            assert falso.mensajes_hid[0] == b"\x01\x01"
        finally:
            await kvm.cerrar()
            await falso.parar()

    correr(prueba())


def test_sin_la_contrasena_no_conecta_y_lo_dice():
    async def prueba():
        falso = JetKVMFalso(Simulador(lineas=["x"]))
        url = await falso.arrancar()
        try:
            with pytest.raises(AparatoNoDisponible, match="contraseña"):
                await JetKVM(url, "").conectar()
            with pytest.raises(AparatoNoDisponible, match="rechaza"):
                await JetKVM(url, "otra").conectar()
        finally:
            await falso.parar()

    correr(prueba())


def test_al_conectar_no_deja_respuestas_http_sin_liberar():
    # Cada respuesta sin leer ni cerrar retiene su conexión: tras conectar sólo
    # debe quedar tomada la del WebSocket de señalización.
    async def prueba():
        falso = JetKVMFalso(Simulador(lineas=["x"]))
        url = await falso.arrancar()
        kvm = JetKVM(url, "secreta")
        try:
            await kvm.conectar()
            assert len(kvm._http.connector._acquired) == 1
        finally:
            await kvm.cerrar()
            await falso.parar()

    correr(prueba())


@pytest.mark.parametrize("version, contrastado", [("0.5.10", True), ("0.6.2", False)])
def test_dice_que_firmware_ve_y_avisa_si_esta_fuera_de_lo_contrastado(version, contrastado):
    async def prueba():
        falso = JetKVMFalso(Simulador(lineas=["x"]), version=version)
        url = await falso.arrancar()
        kvm = JetKVM(url, "secreta")
        try:
            await kvm.conectar()
            return kvm.estado()
        finally:
            await kvm.cerrar()
            await falso.parar()

    e = correr(prueba())
    assert e["firmware"] == version
    assert e["firmware_contrastado"] is contrastado
    assert bool(e.get("aviso")) is not contrastado
    if not contrastado:
        assert "0.5.10" in e["aviso"] and version in e["aviso"]


def test_al_conectar_la_bitacora_dice_el_firmware_y_el_aviso():
    from puente_kvm.app import Puente

    async def prueba():
        falso = JetKVMFalso(Simulador(lineas=["x"]), version="0.6.2")
        url = await falso.arrancar()
        p = Puente(JetKVM(url, "secreta"))
        try:
            await p.conectar()
            return p.bitacora.ultimas()
        finally:
            await p.dispositivo.cerrar()
            await falso.parar()

    entradas = correr(prueba())
    assert any(e["tipo"] == "conexion" and "firmware 0.6.2" in e["detalle"] for e in entradas)
    assert any(e["tipo"] == "aviso" and "fuera de lo contrastado" in e["detalle"] for e in entradas)


def test_el_sonido_del_mac_llega_en_g722_a_su_hora_y_una_pausa_queda_en_silencio():
    async def prueba():
        falso = JetKVMFalso(Simulador(lineas=["x"]))
        falso.pausas = {100: 1.5}  # 2 s sonando, 1,5 s callado, y sigue
        url = await falso.arrancar()
        kvm = JetKVM(url, "secreta")
        try:
            await kvm.conectar()
            assert not kvm.da_sonido  # su audio viene apagado: la línea queda inactiva
            assert await kvm.encender_sonido()  # encendido, pero sólo vale para la conexión siguiente
            assert {"params": {"enabled": True}} in [r["params"] for r in falso.rpc if r["method"] == "setAudioConfig"]
            oidos = []
            kvm.oido = lambda pcm, t: oidos.append((pcm, t))
            await kvm.conectar()
            assert kvm.da_sonido and not await kvm.encender_sonido()
            fin = time.monotonic() + 15
            while (not oidos or oidos[-1][1] - oidos[0][1] < 4.5) and time.monotonic() < fin:
                await asyncio.sleep(0.1)
            # 20 ms a 16 kHz, mono de 16 bits: lo que pide la transcripción, sin convertir.
            assert oidos and all(len(pcm) == 640 for pcm, _ in oidos)
            tiempos = [t for _, t in oidos]
            assert max(b - a for a, b in zip(tiempos, tiempos[1:])) > 1.2  # en la pausa no llega nada
            # La grabación pone el silencio por la hora de llegada: dura lo que pasó.
            g = reunion.Grabacion(ahora=tiempos[0])
            for pcm, t in oidos:
                g.oir(pcm, t)
            g.terminar(fin=tiempos[-1])
            with wave.open(str(g.dir / "reunion.wav")) as w:
                assert abs(w.getnframes() / 16000 - (tiempos[-1] - g.inicio)) < 0.3
            await kvm.apagar_sonido()
            assert not falso.audio and not kvm.da_sonido
        finally:
            await kvm.cerrar()
            await falso.parar()

    correr(prueba())


def test_un_firmware_sin_audio_o_sin_el_audio_usb_lo_dice_claro():
    async def prueba():
        falso = JetKVMFalso(Simulador(lineas=["x"]))
        url = await falso.arrancar()
        kvm = JetKVM(url, "secreta")
        try:
            await kvm.conectar()
            falso.sabe_audio = False
            with pytest.raises(AparatoNoDisponible, match="0.5.9"):
                await kvm.encender_sonido()
            falso.sabe_audio, falso.audio_usb = True, False
            with pytest.raises(AparatoNoDisponible, match="Activar audio USB"):
                await kvm.encender_sonido()
        finally:
            await kvm.cerrar()
            await falso.parar()

    correr(prueba())


# ── el jiggler y despertar el Mac (C-0463) ──────────────────────────────────
def test_el_jiggler_se_lee_al_conectar_y_se_enciende_con_el_horario_que_se_le_da():
    async def prueba():
        falso = JetKVMFalso(Simulador(lineas=["x"]))
        url = await falso.arrancar()
        kvm = JetKVM(url, "secreta")
        try:
            await kvm.conectar()
            # Leído al conectar, sin preguntar en cada vuelta de la pantalla.
            assert kvm.estado()["jiggler"] == {"encendido": False, "config": falso.jiggler_config}
            horario = {"inactivity_limit_seconds": 30, "jitter_percentage": 25,
                       "schedule_cron_tab": "*/30 * 9-17 * * 1-5", "timezone": "America/Mexico_City"}
            leido = await kvm.poner_jiggler(True, horario)
            assert falso.jiggler is True and falso.jiggler_config == horario
            assert leido == {"encendido": True, "config": horario} == kvm.estado()["jiggler"]
            assert "America/Mexico_City" in await kvm.zonas()
            await kvm.poner_jiggler(False)
            assert falso.jiggler is False and falso.jiggler_config == horario  # apagarlo no lo borra
        finally:
            await kvm.cerrar()
            await falso.parar()

    correr(prueba())


def test_un_horario_que_el_aparato_rechaza_repone_el_de_antes_y_no_lo_enciende():
    # El firmware se queda con el malo en memoria y sin jiggler hasta reiniciarse.
    async def prueba():
        falso = JetKVMFalso(Simulador(lineas=["x"]))
        url = await falso.arrancar()
        kvm = JetKVM(url, "secreta")
        try:
            await kvm.conectar()
            antes = dict(falso.jiggler_config)
            falso.rechazar_horario = True
            with pytest.raises(ValueError, match="no aceptó el horario"):
                await kvm.poner_jiggler(True, {**antes, "schedule_cron_tab": "*/7 * * * * *"})
            assert falso.jiggler_config == antes and falso.jiggler is False
        finally:
            await kvm.cerrar()
            await falso.parar()

    correr(prueba())


def test_despertar_manda_la_senal_y_espera_a_que_el_usb_y_la_imagen_vuelvan():
    async def prueba():
        falso = JetKVMFalso(Simulador(lineas=["x"]))
        url = await falso.arrancar()
        kvm = JetKVM(url, "secreta")
        try:
            await kvm.conectar()
            # Despierto y con imagen: no se manda nada ni se dice «despertó».
            r = await kvm.despertar(tope=2)
            assert r["ya_despierto"] is True and falso.despertares == 0
            falso.usb = "suspended"  # el Mac en reposo: sin vídeo
            await asyncio.sleep(1)
            r = await kvm.despertar(tope=5)
            assert falso.despertares == 1
            assert r == {"antes": "suspended", "despues": "configured", "imagen": True}
            # Sin el cable USB, `wakeHost` contesta bien sin hacer nada: no se da por despertado.
            for sin_cable in ("not attached", "unknown"):
                falso.usb = sin_cable
                with pytest.raises(AparatoNoDisponible, match="USB"):
                    await kvm.despertar(tope=1)
            assert falso.despertares == 1
        finally:
            await kvm.cerrar()
            await falso.parar()

    correr(prueba())


def test_si_el_usb_despierta_pero_no_llega_imagen_no_se_dice_que_hay():
    async def prueba():
        falso = JetKVMFalso(Simulador(lineas=["x"]))
        url = await falso.arrancar()
        kvm = JetKVM(url, "secreta")
        try:
            await kvm.conectar()
            falso.usb, falso.video = "suspended", False  # despierta, pero su pantalla sigue a oscuras
            await asyncio.sleep(1)
            r = await kvm.despertar(tope=2)
            assert r == {"antes": "suspended", "despues": "configured", "imagen": False}
        finally:
            await kvm.cerrar()
            await falso.parar()

    correr(prueba())


def test_conectado_con_el_mac_dormido_vuelve_solo_al_despertarlo():
    # Sin vídeo la conexión se da por fallida, pero el canal rpc está: se despierta por él.
    async def prueba():
        falso = JetKVMFalso(Simulador(lineas=["x"]))
        falso.usb = "suspended"
        url = await falso.arrancar()
        kvm = JetKVM(url, "secreta")
        try:
            with pytest.raises(AparatoNoDisponible, match="dormido"):
                await kvm.conectar()
            assert kvm.estado()["conectado"] is False
            assert kvm.estado()["jiggler"] is not None  # leído antes de esperar el vídeo
            r = await kvm.despertar(tope=5)
            assert r["imagen"] is True and kvm.estado()["conectado"] is True
            await kvm.informe_teclado(0, [hid.TECLAS["a"]])  # el teclado ya va
            await kvm.informe_teclado(0, [])
        finally:
            await kvm.cerrar()
            await falso.parar()

    correr(prueba())
