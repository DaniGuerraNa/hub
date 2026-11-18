"""El cliente del JetKVM contra un JetKVM falso por WebRTC de verdad (ver `jetkvm_falso`)."""

import asyncio

import pytest

from puente_kvm import hid
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
