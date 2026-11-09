#!/usr/bin/env python3
"""Monta las imágenes de los talleres (C-0220). A mano, como `personajes.py`.

    uv run --with pillow --with numpy python scripts/talleres.py <carpeta>

`<carpeta>` es la de quien dibuja, con:

    <carpeta>/escena/fondo/casa-a2/casa.png       el fondo (la casa de dos plantas)
    <carpeta>/taberna-v7/<id>/<id>.png            cada rana de `talleres.RANAS`, de pie
    <carpeta>/animacion/<id>/fN/fN.png            los cuadros de trabajo de quien los tenga

y deja en `src/hub/static/talleres/`:

    fondo.webp
    ranas/<id>.webp                               sólo las de `talleres.RANAS`
    cuadros/<id>/fN.webp
    cuadros.json                                  dónde va cada capa de cuadros

Lo que hace, y por qué:

- **Quita el fondo** con `personajes.sin_fondo`, la misma función que las
  hojas del secretario: dos recortadores darían dos halos distintos.
- **Los cuadros de una rana se recortan por la misma caja** (la unión): al
  pasar de uno a otro no salta de sitio.
- **Los cuadros encajan con la rana de andar**: se iguala la altura del
  personaje en `f0` con la de andar, y el centro de la cabeza (el 30 % de
  arriba, donde no llegan el yunque ni el martillo a media altura). Así no
  cambia de tamaño al ponerse a trabajar. `cuadros.json` guarda esa capa en %
  del ancho de la rana de andar.
- **A la herrera se le quita su yunque** (`OBJETO_FIJO`): el yunque es del
  fondo, que es donde está siempre. Se borra la pieza suelta de abajo a la
  derecha en `f0` y `f1`, y en `f2`, que es el golpe, se respeta lo que queda
  por encima del borde del yunque. `cuadros.json` guarda dónde estaba
  (`objeto`), y la página coloca a la herrera para que su golpe caiga sobre
  el yunque del fondo.
- **Sin metadatos**: los PNG generados traen C2PA; todo se escribe nuevo y se
  comprueba con `personajes.trozos_webp`, como las hojas.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import deque
from pathlib import Path

import numpy as np
from PIL import Image

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "scripts"))
sys.path.insert(0, str(RAIZ / "src"))

import personajes as imp  # noqa: E402 — el recortador de las hojas, el mismo
from hub import talleres  # noqa: E402 — qué ranas se pintan: ni una más

DESTINO = RAIZ / "src" / "hub" / "static" / "talleres"
TOLERANCIA = {"rana-herrera": 90}
# Lo que el personaje NO se lleva: está en el fondo (decisión 391).
OBJETO_FIJO = {"rana-herrera"}
LADO_RANA = 360        # px del lado mayor de cada rana
LADO_CUADRO = 480      # px del lado mayor de cada capa de cuadros


def recortar(png: Path, pid: str) -> Image.Image:
    return imp.sin_fondo(Image.open(png).convert("RGBA"), TOLERANCIA.get(pid, imp.TOLERANCIA_POR_OMISION))


def guardar_webp(im: Image.Image, ruta: Path, calidad: int = 82) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    # Una imagen nueva, píxel a píxel: no hereda ningún trozo del original.
    limpia = Image.frombytes(im.mode, im.size, im.tobytes())
    limpia.save(ruta, "WEBP", quality=calidad, method=6)
    sobra = [t for t in imp.trozos_webp(ruta) if t not in imp.TROZOS_DE_IMAGEN]
    if sobra:
        raise SystemExit(f"{ruta}: lleva trozos que no son de imagen {sobra}")


def centro_cabeza(alfa: np.ndarray) -> float:
    """El centro horizontal de lo que hay en el 30 % de arriba de lo dibujado."""
    filas = np.where((alfa > 128).any(axis=1))[0]
    y0, y1 = filas.min(), filas.max()
    franja = alfa[y0:y0 + max(1, int((y1 - y0) * 0.3))] > 128
    cols = np.where(franja.any(axis=0))[0]
    return (cols.min() + cols.max()) / 2


def piezas(mascara: np.ndarray) -> list[np.ndarray]:
    """Las piezas sueltas de una máscara, de mayor a menor. Sin scipy: se
    etiqueta a un cuarto del tamaño (sobra para separar la rana de su yunque)."""
    peq = mascara[::4, ::4]
    etiqueta = np.zeros(peq.shape, dtype=np.int32)
    n = 0
    for y, x in zip(*np.nonzero(peq)):
        if etiqueta[y, x]:
            continue
        n += 1
        cola = deque([(y, x)])
        etiqueta[y, x] = n
        while cola:
            cy, cx = cola.popleft()
            for ny, nx in ((cy + 1, cx), (cy - 1, cx), (cy, cx + 1), (cy, cx - 1)):
                if 0 <= ny < peq.shape[0] and 0 <= nx < peq.shape[1] and peq[ny, nx] and not etiqueta[ny, nx]:
                    etiqueta[ny, nx] = n
                    cola.append((ny, nx))
    grandes = np.kron(etiqueta, np.ones((4, 4), dtype=np.int32))[:mascara.shape[0], :mascara.shape[1]]
    salida = [(grandes == k) & mascara for k in range(1, n + 1)]
    return sorted(salida, key=lambda m: -int(m.sum()))


def objeto_suelto(alfa: np.ndarray) -> np.ndarray | None:
    """La pieza suelta que no es la rana, abajo a la derecha (el yunque)."""
    alto, ancho = alfa.shape
    for m in piezas(alfa > 40)[1:4]:
        ys, xs = np.nonzero(m)
        if len(xs) and xs.mean() > ancho * 0.55 and ys.mean() > alto * 0.55:
            return m
    return None


def engordar(m: np.ndarray, veces: int) -> np.ndarray:
    for _ in range(veces):
        g = m.copy()
        g[1:] |= m[:-1]; g[:-1] |= m[1:]; g[:, 1:] |= m[:, :-1]; g[:, :-1] |= m[:, 1:]
        m = g
    return m


def montar_cuadros(pid: str, carpeta: Path, andar: Image.Image) -> dict:
    nombres = sorted(p.name for p in carpeta.iterdir() if (p / f"{p.name}.png").exists())
    imgs = {n: np.array(recortar(carpeta / n / f"{n}.png", pid)) for n in nombres}
    if len({a.shape for a in imgs.values()}) != 1:
        raise SystemExit(f"{pid}: los cuadros no miden lo mismo")
    objeto = None
    if pid in OBJETO_FIJO:
        sueltos = [m for m in (objeto_suelto(imgs[n][:, :, 3]) for n in nombres if n != "f2") if m is not None]
        if not sueltos:
            raise SystemExit(f"{pid}: no encuentro el objeto que hay que quitar")
        union = np.logical_or.reduce(sueltos)
        ys, xs = np.nonzero(union)
        caja = (xs.min(), ys.min(), xs.max(), ys.max())
        borrar = engordar(union, 4)
        for n, a in imgs.items():
            m = borrar.copy()
            if n == "f2":  # el golpe: el martillo toca la pieza, se respeta lo de encima
                m[:caja[1] + int((caja[3] - caja[1]) * 0.12)] = False
            a[m, 3] = 0
        objeto = caja
    cajas = [Image.fromarray(a).getbbox() for a in imgs.values()]
    u = (min(c[0] for c in cajas), min(c[1] for c in cajas), max(c[2] for c in cajas), max(c[3] for c in cajas))
    ancho_u, alto_u = u[2] - u[0], u[3] - u[1]
    escala = LADO_CUADRO / max(ancho_u, alto_u)
    for n, a in imgs.items():
        im = Image.fromarray(a).crop(u).resize((round(ancho_u * escala), round(alto_u * escala)), Image.LANCZOS)
        guardar_webp(im, DESTINO / "cuadros" / pid / f"{n}.webp")

    # Dónde va la capa respecto a la rana de andar (en % de su ancho).
    aa = np.array(andar)[:, :, 3]
    a0 = imgs["f0"][:, :, 3]
    c0 = Image.fromarray(imgs["f0"]).getbbox()
    k = andar.height / (c0[3] - c0[1])
    datos = {
        "cuadros": nombres,
        "ancho": round(ancho_u * k / andar.width * 100, 2),
        "alto": round(alto_u * k / andar.width * 100, 2),
        "izquierda": round((centro_cabeza(aa) - (centro_cabeza(a0) - u[0]) * k) / andar.width * 100, 2),
        "bajar": round((u[3] - c0[3]) / alto_u * 100, 2),
    }
    if objeto:
        x0, y0, x1, y1 = objeto
        datos["objeto"] = {"u": round(((x0 + x1) / 2 - u[0]) / ancho_u, 4),
                           "v_arriba": round((y0 - u[1]) / alto_u, 4),
                           "v_base": round((y1 - u[1]) / alto_u, 4)}
    return datos


def main() -> int:
    partes = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    partes.add_argument("carpeta", type=Path)
    args = partes.parse_args()
    c = args.carpeta

    guardar_webp(Image.open(c / "escena/fondo/casa-a2/casa.png").convert("RGB"), DESTINO / "fondo.webp", 80)

    andar = {}
    for pid in sorted(talleres.RANAS):
        carpeta = c / "taberna-v7" / pid
        im = recortar(carpeta / f"{pid}.png", pid)
        im = im.crop(im.getbbox())
        im.thumbnail((LADO_RANA, LADO_RANA), Image.LANCZOS)
        guardar_webp(im, DESTINO / "ranas" / f"{pid}.webp")
        andar[pid] = im

    cuadros = {}
    for carpeta in sorted(p for p in (c / "animacion").iterdir() if p.is_dir() and p.name in andar):
        cuadros[carpeta.name] = montar_cuadros(carpeta.name, carpeta, andar[carpeta.name])
    (DESTINO / "cuadros.json").write_text(json.dumps(cuadros, indent=1, ensure_ascii=False) + "\n")
    print(f"{len(andar)} ranas, cuadros de {', '.join(cuadros)}, en {DESTINO.relative_to(RAIZ)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
