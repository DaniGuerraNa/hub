"""Preguntarle algo a un programa aparte que escucha en loopback (decisiones 438 y 461).

El hub apunta a programas que no son suyos —el Puente KVM, el estudio— y de
cada uno sólo quiere saber si contesta y poco más. Este es el único cliente
HTTP para eso: una pregunta GET, corta y sin sorpresas. Lo que cada programa
deja pasar de su respuesta es de su módulo (`puente.py`, `estudio.py`), con su
lista cerrada de claves.

Por un socket propio y no por `urllib` ni `http.client`: `urllib` obedece a
`http_proxy` del entorno y sigue redirecciones, y los dos ponen el plazo a
cada lectura, no a la pregunta entera: un puente que gotea las cabeceras de
byte en byte tenía `/puente` esperando seis segundos (medido). Aquí el plazo
es uno y absoluto, desde que se conecta hasta el último byte, y la pregunta
es HTTP/1.0 con `Connection: close`: una sola respuesta, sin trozos, hasta
que cierra o hasta su `Content-Length`.

🔴 Sólo GET y sólo a `127.0.0.1`: la dirección es literal, nunca sacada de
la petición, y aquí no hay forma de mandar un cuerpo.
"""

from __future__ import annotations

import json
import re
import socket
import time
from typing import Any

ANFITRION = "127.0.0.1"

_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]+")


class NoContesta(Exception):
    """No contestó con algo que se entienda. `motivo` lo dice en llano, sin
    la dirección: quien mira desde otro aparato no la necesita."""

    def __init__(self, motivo: str):
        super().__init__(motivo)
        self.motivo = motivo


class _Demasiado(Exception):
    """Contestó más del tope."""


class _Rara(Exception):
    """Lo que contestó no es una respuesta HTTP que se entienda."""


def recortar(texto: object, maximo: int) -> str | None:
    """Un texto de fuera, en una línea, sin caracteres de control y como
    mucho de `maximo`; None si no es texto o queda vacío."""
    if not isinstance(texto, str):
        return None
    limpio = " ".join(_CONTROL.sub(" ", texto).split())
    if not limpio:
        return None
    return limpio if len(limpio) <= maximo else limpio[:maximo - 1] + "…"


def _quedan(limite: float) -> float:
    quedan = limite - time.monotonic()
    if quedan <= 0:
        raise TimeoutError("se acabó el tiempo")
    return quedan


def _partir(crudo: bytes) -> tuple[int, dict[str, str], bytes] | None:
    """El código, las cabeceras y el cuerpo, o None si aún no han llegado las
    cabeceras enteras. El cuerpo, cortado a su `Content-Length` si lo dice."""
    cabeza, separador, cuerpo = crudo.partition(b"\r\n\r\n")
    if not separador:
        return None
    lineas = cabeza.decode("latin-1").split("\r\n")
    primera = lineas[0].split(" ", 2)
    if len(primera) < 2 or not primera[0].startswith("HTTP/") or not primera[1].isdigit():
        raise _Rara
    cabeceras = {}
    for linea in lineas[1:]:
        nombre, _, valor = linea.partition(":")
        cabeceras[nombre.strip().lower()] = valor.strip()
    if "transfer-encoding" in cabeceras:
        # A una pregunta HTTP/1.0 no se contesta por trozos.
        raise _Rara
    largo = cabeceras.get("content-length")
    if largo is not None:
        if not largo.isdigit():
            raise _Rara
        cuerpo = cuerpo[:int(largo)]
    return int(primera[1]), cabeceras, cuerpo


def _preguntar(puerto: int, camino: str, espera: float, tope: int) -> tuple[int, bytes]:
    """Un GET con un plazo absoluto: conectar, mandar, cada lectura y las
    cabeceras entran todas en `espera`."""
    limite = time.monotonic() + espera
    peticion = (f"GET {camino} HTTP/1.0\r\nHost: {ANFITRION}:{puerto}\r\n"
                "Accept: application/json\r\nConnection: close\r\n\r\n").encode("ascii")
    with socket.create_connection((ANFITRION, puerto), timeout=_quedan(limite)) as s:
        s.settimeout(_quedan(limite))
        s.sendall(peticion)
        crudo = bytearray()
        while True:
            s.settimeout(_quedan(limite))
            trozo = s.recv(64 * 1024)
            if trozo:
                crudo += trozo
                if len(crudo) > tope:
                    raise _Demasiado
            partes = _partir(bytes(crudo))
            if partes is not None:
                codigo, cabeceras, cuerpo = partes
                largo = cabeceras.get("content-length")
                entero = largo is not None and len(cuerpo) >= int(largo)
                # Con su largo, en cuanto llega entero; sin él, cuando cierra.
                if entero or (not trozo and largo is None):
                    return codigo, cuerpo
            if not trozo:
                # Cerró sin dar las cabeceras enteras, o con el cuerpo a medias.
                raise _Rara


def pedir_json(puerto: int, camino: str, espera: float, tope: int, que: str = "su estado") -> Any:
    """Lo que contesta un GET a `camino`, ya leído como JSON.

    Si no contesta, o contesta algo que no es un 200 con JSON, lanza
    `NoContesta` con el porqué; `que` es lo que se le pidió, dicho en llano
    («su estado»), para ese porqué. Nada más se lanza."""
    if not camino.startswith("/") or any(c in camino for c in " \r\n"):
        raise ValueError(f"camino raro: {camino!r}")
    if espera <= 0:
        raise NoContesta("no contestó a tiempo")
    try:
        codigo, cuerpo = _preguntar(puerto, camino, espera, tope)
    except ConnectionRefusedError:
        raise NoContesta("no hay nada escuchando en su puerto") from None
    except TimeoutError:
        raise NoContesta("no contestó a tiempo") from None
    except _Demasiado:
        raise NoContesta(f"contesta demasiado: eso no es {que}") from None
    except _Rara:
        raise NoContesta(f"contesta algo que no es {que}") from None
    except OSError:
        raise NoContesta("no se pudo hablar con él") from None
    if codigo != 200:
        raise NoContesta(f"contesta, pero con un error (HTTP {codigo})")
    try:
        return json.loads(cuerpo)
    except (ValueError, RecursionError):
        raise NoContesta(f"contesta algo que no es {que}") from None
