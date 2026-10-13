#!/usr/bin/env python3
"""Genera los iconos del hub a partir de su marca. Se ejecuta a mano, no al arrancar.

    uv run python scripts/generar-iconos.py

🔴 Los PNG se **commitean**, como `inter.woff2`: la web no debe depender de nada
externo en runtime, y menos aún de que exista un rasterizador en la máquina. Este
script existe para poder rehacerlos cuando cambie la marca, no para ejecutarse en
cada arranque.

Se rasteriza a mano —la marca son cuatro cuadrados redondeados— porque en esta
máquina no hay ni ImageMagick ni rsvg ni cairo, y añadir uno de esos como
dependencia de un icono que cambia una vez al año es peor negocio que treinta
líneas de aritmética. El PNG se escribe con `zlib` y `struct`, que están en la
biblioteca estándar.
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
ESTATICOS = RAIZ / "src" / "hub" / "static"

# Los mismos tokens del sistema visual (`base.html`). Aquí van en literal porque
# un PNG no tiene variables CSS; si la paleta cambia, se vuelve a lanzar esto.
LIENZO = (0x0D, 0x11, 0x17)
ACENTO = (0x3F, 0xB9, 0xD4)

# La marca, en el mismo viewBox de 20 que el SVG del raíl: cuatro cuadrados con
# la misma opacidad decreciente.
CUADRADOS = [
    (2.5, 2.5, 1.00),
    (11.5, 2.5, 0.50),
    (2.5, 11.5, 0.50),
    (11.5, 11.5, 0.25),
]
LADO, RADIO, CAJA = 6.0, 2.0, 20.0

# Cuántas muestras por píxel y lado. 4 son 16 muestras: suficiente para que un
# borde curvo no se vea escalonado a 192 px, y barato de calcular.
MUESTRAS = 4


def _dentro(x: float, y: float, cx: float, cy: float) -> bool:
    """¿Cae el punto dentro del cuadrado redondeado que empieza en (cx, cy)?"""
    dx = max(cx - x, x - (cx + LADO), 0.0)
    dy = max(cy - y, y - (cy + LADO), 0.0)
    if dx == 0.0 and dy == 0.0:
        # Dentro del rectángulo: sólo falta descartar las cuatro esquinas.
        ex = min(x - cx, cx + LADO - x)
        ey = min(y - cy, cy + LADO - y)
        if ex >= RADIO or ey >= RADIO:
            return True
        qx, qy = RADIO - ex, RADIO - ey
        return qx * qx + qy * qy <= RADIO * RADIO
    return False


def _pintar(lado_px: int) -> bytes:
    escala = CAJA / lado_px
    paso = escala / MUESTRAS
    filas = bytearray()
    for py in range(lado_px):
        filas.append(0)  # filtro PNG «None» al principio de cada fila
        for px in range(lado_px):
            # Cobertura de cada cuadrado por separado, para poder mezclar su
            # opacidad propia: se superponen sólo en el borde, y ahí gana el
            # más opaco en vez de sumarse (sumar daría una costura clara).
            alfa = 0.0
            for cx, cy, opacidad in CUADRADOS:
                dentro = 0
                for sy in range(MUESTRAS):
                    y = (py * escala) + (sy + 0.5) * paso
                    for sx in range(MUESTRAS):
                        x = (px * escala) + (sx + 0.5) * paso
                        dentro += _dentro(x, y, cx, cy)
                if dentro:
                    alfa = max(alfa, opacidad * dentro / (MUESTRAS * MUESTRAS))
            filas.extend(
                round(f + (a - f) * alfa) for f, a in zip(LIENZO, ACENTO)
            )
            filas.append(255)  # opaco: el icono lleva su propio fondo
    return bytes(filas)


def _png(lado_px: int) -> bytes:
    def trozo(etiqueta: bytes, datos: bytes) -> bytes:
        cuerpo = etiqueta + datos
        return (struct.pack(">I", len(datos)) + cuerpo
                + struct.pack(">I", zlib.crc32(cuerpo) & 0xFFFFFFFF))

    cabecera = struct.pack(">IIBBBBB", lado_px, lado_px, 8, 6, 0, 0, 0)  # 8 bits, RGBA
    return (b"\x89PNG\r\n\x1a\n"
            + trozo(b"IHDR", cabecera)
            + trozo(b"IDAT", zlib.compress(_pintar(lado_px), 9))
            + trozo(b"IEND", b""))


def _svg() -> str:
    """El mismo dibujo en vectorial, para la pestaña del navegador."""
    piezas = "".join(
        f'<rect x="{x}" y="{y}" width="{LADO}" height="{LADO}" rx="{RADIO}" '
        f'fill="#3fb9d4" opacity="{o}"/>'
        for x, y, o in CUADRADOS
    )
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 20 20">'
            f'<rect width="20" height="20" rx="4.5" fill="#0d1117"/>{piezas}</svg>\n')


def main() -> None:
    ESTATICOS.mkdir(parents=True, exist_ok=True)
    (ESTATICOS / "icono.svg").write_text(_svg(), encoding="utf-8")
    print(f"  ✓ icono.svg")
    for lado in (192, 512):
        destino = ESTATICOS / f"icono-{lado}.png"
        destino.write_bytes(_png(lado))
        print(f"  ✓ icono-{lado}.png   {destino.stat().st_size:,} bytes")


if __name__ == "__main__":
    main()
