#!/usr/bin/env python3
"""Monta la hoja de cada personaje dibujado del secretario (C-0188, decisión 377). A mano.

    uv run --with pillow --with numpy python scripts/personajes.py <carpeta> [--solo <id>]

`<carpeta>` trae, por personaje de `personaje.PERSONAJES`, su dibujo base y
sus poses, cada uno en un PNG cuadrado con el fondo liso:

    <carpeta>/propuestas/<id>/<id>.png
    <carpeta>/acciones/<id>/<pose>/<pose>.png

y deja `src/hub/static/personajes/<id>.webp`: nueve celdas de 256 px, tres por
fila, en el orden de `personaje.POSES`. Una sola imagen por personaje y no
nueve: los estáticos se revalidan en cada carga (`_EstaticosSinCache`), y cada
pantalla haría nueve peticiones por un adorno.

🔴 Las hojas se **commitean**, como los iconos de `generar-iconos.py`: la web no
depende de que haya Pillow en la máquina. Pillow y numpy entran sólo con
`--with`, nunca en `pyproject.toml`. La carpeta de origen va siempre como
argumento: es de quien dibuja, no del hub.

Lo que hace con cada dibujo, y por qué:

- **Quita el fondo.** El color del fondo es la mediana del borde; desde el
  borde se inunda lo que se parece a él (`TOLERANCIA`), y en esa zona la
  opacidad sube con la distancia al fondo, así que el contorno queda suave. El
  color de ese contorno se limpia de la mezcla con el fondo (si no, queda un
  halo del pastel de origen sobre el tema oscuro), y lo que es el fondo
  oscurecido —la sombra en el suelo— se quita entera: limpiada, salía como un
  borde gris deshilachado. Sólo desde el borde: lo encerrado (entre un brazo
  y el cuerpo) se queda, porque quitar por color se comería el cuerpo de un
  personaje del mismo tono que su fondo. Al que ni así sale limpio
  (`BALDOSA`) se le deja su fondo, en una baldosa de esquinas redondeadas.
- **Una pose que falta se rellena con la base**, y se dice al acabar: se
  vuelve a lanzar cuando estén todas.
- **Todas las poses de un personaje se recortan por la misma caja** (la unión
  de lo que ocupan, cuadrada y con margen): al cambiar de pose no salta de
  sitio ni de tamaño, y el margen evita que una celda sangre en la de al lado.
- **Sin metadatos.** Los PNG generados traen un bloque de procedencia (C2PA,
  `caBX`) y la revisión de lo publicado no lee binarios: la hoja se crea nueva,
  píxel a píxel, y al acabar se comprueba que sólo lleva los trozos de imagen
  de un WebP (`TROZOS_DE_IMAGEN`). Lo mismo comprueba un test.
"""

from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

from hub.secretario import personaje  # noqa: E402 — después de poner `src` en la ruta

DESTINO = RAIZ / "src" / "hub" / "static" / "personajes"
CELDA = 256
POR_FILA = 3
MARGEN = 0.04

# Cuánto se puede parecer al fondo lo que se quita (máximo por canal, 0-255).
# 48 limpia el contorno de los que tienen trazo. El de luz tiene un resplandor
# que se funde con su fondo oscuro: con 160 queda como luz semitransparente;
# con 48 dejaba un aro azul. Medido a ojo sobre el tema, en sus hojas.
TOLERANCIA_POR_OMISION = 48
TOLERANCIA = {"hongo-luz": 160}

# Los que no se recortan: van en una baldosa redondeada con su propio fondo.
# El amanita no tiene trazo y su pie es del color del fondo, que además tiene
# grano cerca de él: con 48 se comía el pie; con 8, 4 o limpiando motas
# quedaba un borde gris y polvo alrededor. Mejor su fondo que un borde feo.
BALDOSA = {"hongo-amanita"}
RADIO_BALDOSA = 0.22

TROZOS_DE_IMAGEN = {b"VP8X", b"VP8 ", b"VP8L", b"ALPH"}


def _fondo(a: np.ndarray) -> np.ndarray:
    borde = np.concatenate([a[:4].reshape(-1, 3), a[-4:].reshape(-1, 3),
                            a[:, :4].reshape(-1, 3), a[:, -4:].reshape(-1, 3)])
    return np.median(borde, axis=0)


def sin_fondo(im: Image.Image, tolerancia: int) -> Image.Image:
    """El dibujo con el fondo transparente (ver el docstring del módulo)."""
    a = np.asarray(im.convert("RGB")).astype(np.float32)
    alto, ancho, _ = a.shape
    fondo = _fondo(a)
    distancia = np.abs(a - fondo).max(axis=2)
    # `.copy()`: la imagen que sale de un array es de sólo lectura, y el
    # relleno escribiría en otra sin decir nada.
    marca = Image.fromarray(((distancia < tolerancia) * 255).astype(np.uint8)).copy()
    semillas = [(x, y) for x in range(0, ancho, 8) for y in (0, alto - 1)]
    semillas += [(x, y) for y in range(0, alto, 8) for x in (0, ancho - 1)]
    for xy in semillas:
        if marca.getpixel(xy) == 255:
            ImageDraw.floodfill(marca, xy, 128)
    zona = np.asarray(marca) == 128
    suave = tolerancia / 4
    alfa = np.ones((alto, ancho), np.float32)
    alfa[zona] = np.clip((distancia[zona] - suave) / (tolerancia - suave), 0, 1)
    # La sombra: el fondo con menos luz, del mismo tono.
    razon = a / np.maximum(fondo, 1)
    sombra = zona & (razon.max(axis=2) <= 1.0) & (razon.max(axis=2) - razon.min(axis=2) < 0.04)
    alfa[sombra] = 0
    mezcla = zona & (alfa > 0) & (alfa < 1)
    al = alfa[mezcla][:, None]
    a[mezcla] = np.clip((a[mezcla] - (1 - al) * fondo) / al, 0, 255)
    return Image.fromarray(np.dstack([a, alfa * 255]).round().astype(np.uint8), "RGBA")


def en_baldosa(im: Image.Image) -> Image.Image:
    """El dibujo entero con su fondo, con las esquinas redondeadas."""
    rgba = im.convert("RGBA")
    lado = min(rgba.size)
    mascara = Image.new("L", rgba.size, 0)
    ImageDraw.Draw(mascara).rounded_rectangle((0, 0, rgba.width - 1, rgba.height - 1),
                                              radius=round(lado * RADIO_BALDOSA), fill=255)
    rgba.putalpha(mascara)
    return rgba


def _caja(dibujos: list[Image.Image]) -> tuple[int, int, int, int]:
    """La caja cuadrada que contiene lo que ocupan todas las poses, con margen."""
    cajas = [d.getchannel("A").point(lambda v: 255 if v > 8 else 0).getbbox() for d in dibujos]
    cajas = [c for c in cajas if c]
    x0, y0 = min(c[0] for c in cajas), min(c[1] for c in cajas)
    x1, y1 = max(c[2] for c in cajas), max(c[3] for c in cajas)
    lado = max(x1 - x0, y1 - y0) * (1 + 2 * MARGEN)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    return (round(cx - lado / 2), round(cy - lado / 2), round(cx + lado / 2), round(cy + lado / 2))


def trozos_webp(ruta: Path) -> list[bytes]:
    """Los trozos RIFF de un WebP, para comprobar que no lleva metadatos."""
    datos = ruta.read_bytes()
    if datos[:4] != b"RIFF" or datos[8:12] != b"WEBP":
        raise ValueError(f"{ruta.name} no es un WebP")
    trozos, i = [], 12
    while i + 8 <= len(datos):
        nombre, largo = datos[i:i + 4], struct.unpack("<I", datos[i + 4:i + 8])[0]
        trozos.append(nombre)
        i += 8 + largo + (largo & 1)
    return trozos


def montar(pid: str, carpeta: Path) -> list[str]:
    """Escribe la hoja de un personaje. Devuelve las poses que faltaban."""
    base = carpeta / "propuestas" / pid / f"{pid}.png"
    if not base.is_file():
        raise FileNotFoundError(f"falta su dibujo base: {base.relative_to(carpeta)}")
    tolerancia = TOLERANCIA.get(pid, TOLERANCIA_POR_OMISION)
    faltan, dibujos = [], []
    for pose in personaje.POSES:
        ruta = base if pose == "base" else carpeta / "acciones" / pid / pose / f"{pose}.png"
        if not ruta.is_file():
            faltan.append(pose)
            ruta = base
        with Image.open(ruta) as im:
            dibujos.append(en_baldosa(im) if pid in BALDOSA else sin_fondo(im, tolerancia))
    caja = _caja(dibujos)
    # Una hoja nueva: de los PNG de origen no pasa nada más que los píxeles.
    hoja = Image.new("RGBA", (CELDA * POR_FILA, CELDA * ((len(personaje.POSES) + POR_FILA - 1) // POR_FILA)))
    for i, d in enumerate(dibujos):
        # Premultiplicado al reducir: si no, lo transparente tiñe el contorno.
        celda = d.crop(caja).convert("RGBa").resize((CELDA, CELDA), Image.LANCZOS).convert("RGBA")
        hoja.paste(celda, ((i % POR_FILA) * CELDA, (i // POR_FILA) * CELDA))
    DESTINO.mkdir(parents=True, exist_ok=True)
    destino = DESTINO / f"{pid}.webp"
    hoja.save(destino, "WEBP", quality=90, alpha_quality=100, method=6)
    sobran = set(trozos_webp(destino)) - TROZOS_DE_IMAGEN
    if sobran:
        destino.unlink()
        raise RuntimeError(f"la hoja salió con metadatos ({', '.join(t.decode() for t in sobran)}): no se deja")
    return faltan


def main() -> int:
    p = argparse.ArgumentParser(description="Monta las hojas de los personajes dibujados del secretario.")
    p.add_argument("carpeta", type=Path, help="la carpeta con propuestas/ y acciones/")
    p.add_argument("--solo", help="sólo este personaje (su id)")
    args = p.parse_args()
    dibujados = [k for k in personaje.PERSONAJES if k != personaje.POR_OMISION]
    if args.solo and args.solo not in dibujados:
        p.error(f"«{args.solo}» no es un personaje dibujado: {', '.join(dibujados)}")
    if not (args.carpeta / "propuestas").is_dir():
        p.error(f"{args.carpeta} no tiene propuestas/")
    incompletos, fallos = {}, {}
    for pid in [args.solo] if args.solo else dibujados:
        try:
            faltan = montar(pid, args.carpeta)
        except (OSError, ValueError, RuntimeError) as exc:
            fallos[pid] = str(exc)
            print(f"{pid}: NO — {exc}")
            continue
        destino = DESTINO / f"{pid}.webp"
        print(f"{pid}: {destino.stat().st_size // 1024} KB" + (f" · con la base en: {', '.join(faltan)}" if faltan else ""))
        if faltan:
            incompletos[pid] = faltan
    if incompletos:
        print(f"\n{len(incompletos)} con poses rellenadas con la base: vuelve a lanzarlo cuando estén.")
    return 1 if fallos else 0


if __name__ == "__main__":
    sys.exit(main())
