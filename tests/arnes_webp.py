"""Leer los trozos RIFF de un WebP, para comprobar que una imagen generada no
lleva nada que no sea imagen (los PNG de origen traen C2PA y la revisión de lo
publicado no lee binarios). Lo usan las hojas del secretario y los talleres."""

from __future__ import annotations


def trozos(datos: bytes) -> list[tuple[bytes, bytes]]:
    """Cada trozo como (nombre, contenido)."""
    assert datos[:4] == b"RIFF" and datos[8:12] == b"WEBP"
    salida, i = [], 12
    while i + 8 <= len(datos):
        largo = int.from_bytes(datos[i + 4:i + 8], "little")
        salida.append((datos[i:i + 4], datos[i + 8:i + 8 + largo]))
        i += 8 + largo + (largo & 1)
    return salida


#: Los únicos trozos que puede llevar una imagen nuestra.
DE_IMAGEN = {b"VP8X", b"VP8 ", b"VP8L", b"ALPH"}
