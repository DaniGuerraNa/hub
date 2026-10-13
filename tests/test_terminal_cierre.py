"""🔴 El orden en que se desmonta una terminal, y por qué mata al proceso.

`hub-web` se murió 15 veces entre el 2 y el 4 de septiembre con SIGABRT, sin
excepción, sin traza y sin una línea en el registro: sólo «se cayó el hub». La
causa es de una línea y no se ve leyendo el código —`cancel()` seguido de
`cerrar()` parece obviamente correcto—, porque `cancel()` sólo AGENDA la
cancelación: el `finally` que suelta el vigilante del descriptor todavía no ha
corrido cuando se cierra el fd. uvloop es libuv, en C, y ante un `epoll_ctl`
sobre un descriptor muerto llama a `abort()` (decisión 156).

Medido: con el código anterior, 8 conexiones cortadas en seco tumbaban el
proceso en **1 segundo**; con éste aguanta los 90 s de la prueba entera.
"""

from __future__ import annotations

import asyncio
import os
import pty
import subprocess

import pytest

from hub import terminal


def _adjunto_sobre_un_pty_real():
    """Un `Adjunto` de verdad, con un hijo de verdad al que mandar SIGTERM.

    El hijo importa: `cerrar()` hace `os.kill(self.pid, ...)`, y un `pid` de
    mentira como 0 se lo mandaría al grupo de procesos entero — o sea, a la
    suite.
    """
    maestro, esclavo = pty.openpty()
    hijo = subprocess.Popen(["sleep", "30"])
    adjunto = terminal.Adjunto.__new__(terminal.Adjunto)
    adjunto.pid, adjunto.fd = hijo.pid, maestro
    os.set_blocking(adjunto.fd, False)
    adjunto._pendiente = bytearray()
    adjunto._esperando = False
    adjunto._leyendo = False
    return adjunto, esclavo


def _sigue_vigilado(bucle, fd) -> bool:
    try:
        bucle._selector.get_key(fd)
        return True
    except KeyError:
        return False


def test_cerrar_suelta_el_vigilante_antes_de_cerrar_el_descriptor(monkeypatch):
    """La invariante entera: nunca un fd cerrado que el bucle siga vigilando."""

    async def prueba():
        adjunto, esclavo = _adjunto_sobre_un_pty_real()
        bucle = asyncio.get_running_loop()
        adjunto.vigilar_lectura(lambda: None)
        assert _sigue_vigilado(bucle, adjunto.fd)

        visto = {}
        cerrar_real = os.close

        def espiar(fd):
            if fd == adjunto.fd:
                visto["vigilado"] = _sigue_vigilado(bucle, fd)
            return cerrar_real(fd)

        monkeypatch.setattr(os, "close", espiar)
        adjunto.cerrar()
        monkeypatch.undo()
        cerrar_real(esclavo)
        return visto

    visto = asyncio.run(prueba())
    assert visto["vigilado"] is False, (
        "el fd se cerró con el bucle todavía vigilándolo: eso es el abort"
    )


def test_soltar_espera_al_bombeo_antes_de_cerrar():
    """`cancel()` no basta: hay que ver terminar la tarea."""

    async def prueba():
        adjunto, esclavo = _adjunto_sobre_un_pty_real()
        orden = []

        async def bombeo():
            try:
                await asyncio.sleep(3600)
            finally:
                orden.append("bombeo suelta el fd")

        adjunto.cerrar = lambda: orden.append("se cierra el fd")
        tarea = asyncio.create_task(bombeo())
        # Que arranque de verdad: una tarea cancelada antes de su primer paso no
        # llega a ejecutar su `finally`, y el test pasaría sin probar nada.
        await asyncio.sleep(0)
        await terminal.soltar(adjunto, tarea)
        os.close(adjunto.fd)
        os.close(esclavo)
        return orden

    assert asyncio.run(prueba()) == ["bombeo suelta el fd", "se cierra el fd"]


def test_soltar_no_deja_escapar_el_fallo_del_bombeo():
    """Si la excepción escapa, el `finally` del WebSocket no destruye el espejo.

    Pasó al arreglar lo de arriba: `send_bytes` sobre un socket cortado en seco
    lanza `RuntimeError`, esperar la tarea lo destapó, y la prueba dejó 42
    espejos colgando hasta que la web dejó de contestar de tanto barrerlos.
    """

    async def prueba():
        adjunto, esclavo = _adjunto_sobre_un_pty_real()
        cerrado = []

        async def bombeo():
            raise RuntimeError("el cliente cortó en seco")

        adjunto.cerrar = lambda: cerrado.append(True)
        await terminal.soltar(adjunto, asyncio.create_task(bombeo()))
        os.close(adjunto.fd)
        os.close(esclavo)
        return cerrado

    assert asyncio.run(prueba()) == [True]


def test_soltar_aguanta_que_no_haya_bombeo():
    """El espejo pudo fallar antes de crear la tarea."""

    async def prueba():
        adjunto, esclavo = _adjunto_sobre_un_pty_real()
        cerrado = []
        adjunto.cerrar = lambda: cerrado.append(True)
        await terminal.soltar(adjunto, None)
        os.close(adjunto.fd)
        os.close(esclavo)
        return cerrado

    assert asyncio.run(prueba()) == [True]
