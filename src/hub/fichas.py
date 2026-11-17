"""Leer las fichas de cambios (`C-NNNN-titulo.md`): su cabecera y nada más (decisión 360).

Las crea el guion de cambios, que es del flujo de desarrollo y no viaja con el
producto. Leerlas es otra cosa: el secretario dice en su parte cuáles esperan
al dueño, y lo hace por aquí y no con su propio lector de YAML. Dos lectores
del mismo formato acaban entendiendo cosas distintas (C-0040, C-0116).

Sólo lectura: el estado de una ficha lo cambia quien la trabaja, a mano.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from datetime import date
from pathlib import Path

import yaml

from . import config

ESTADOS = ("anotada", "en-curso", "esperando", "hecha", "descartada")
ABIERTOS = ("anotada", "en-curso", "esperando")

_CABECERA = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.S)


def leer(ruta: Path) -> dict:
    """La cabecera de una ficha, o {} si no tiene o no se entiende."""
    try:
        m = _CABECERA.match(ruta.read_text(encoding="utf-8"))
        datos = config.leer_yaml(m.group(1)) if m else None
    except (OSError, UnicodeDecodeError, yaml.YAMLError):
        return {}
    return datos if isinstance(datos, dict) else {}


def desde(ficha: dict) -> str | None:
    """Desde cuándo está pedido lo que pide la ficha: su `origen` si lo dice y,
    si no, el día en que se abrió.

    `origen` existe porque `abierta` miente en las que se pasaron de un
    documento viejo: dicen el día en que se pasaron, no el día en que se
    apuntó lo que piden, y una edad que esconde justo lo más viejo no se puede
    defender (C-0333).
    """
    valor = ficha.get("origen") or ficha.get("abierta")
    return str(valor) if valor else None


def edad(ficha: dict, hoy: date) -> int | None:
    """Los días que lleva pedida (`desde`), o None si no lo dice o no se entiende."""
    try:
        return (hoy - date.fromisoformat(desde(ficha) or "")).days
    except ValueError:
        return None


def resuelve(ficha: dict) -> list[str]:
    """Las herramientas del secretario que, según la ficha, resuelven el hueco
    del que nació (`resuelve:` en su cabecera, C-0252): texto o lista, con
    los nombres tal como salen en `herramientas.todas()`. Se declara a mano al
    cerrarla; lo que no se entiende es como no declararlo, y entonces no se
    anuncia nada (regla dura 13)."""
    valor = ficha.get("resuelve")
    if isinstance(valor, str):
        valor = [valor]
    if not isinstance(valor, list):
        return []
    return [n for n in (str(v).strip() for v in valor if isinstance(v, str)) if n]


def listar(carpeta: Path, *, estado: str | Iterable[str] | None = None,
           quien: str | None = None) -> list[dict]:
    """Las cabeceras de las fichas de `carpeta`, por número, cada una con su `ruta`.

    `estado` es uno o varios (`ABIERTOS`); `quien`, `claude` o `dueno`. Una
    carpeta que no existe es una lista vacía: el parte no se cae por ella.
    """
    estados = {estado} if isinstance(estado, str) else (set(estado) if estado is not None else None)
    out = []
    for ruta in sorted(Path(carpeta).glob("C-*.md")):
        f = leer(ruta)
        if estados is not None and f.get("estado") not in estados:
            continue
        if quien is not None and f.get("quien") != quien:
            continue
        out.append(f | {"ruta": ruta})
    return out
