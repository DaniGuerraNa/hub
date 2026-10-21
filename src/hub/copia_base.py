"""La copia diaria de `hub.db` (decisión 277).

La regla dura 1 dice que la base es un índice, y para lo derivado lo es. Pero
hay datos que sólo viven ahí —los slots y sus notas, el canal, los programados,
los encargos; la lista entera está en `db.BaseIlegible`—, y un dato que sólo
vive en un sitio no está respaldado. Volcarlos a archivos para que la regla
vuelva a ser verdad era mucho trabajo para poco; copiar la base cada día, no.

🔴 **Con la API de copia de SQLite, nunca con `cp`.** La base va en WAL: lo
último escrito puede estar todavía en `hub.db-wal`, y copiar sólo el archivo
principal mientras el snapshotter escribe da una copia a medias que abre bien
y le faltan cosas — el peor tipo de respaldo, porque nadie lo descubre hasta
que lo necesita.
"""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from . import config

PREFIJO = "hub-"
CONSERVAR = 14
# Más que esto sin copia nueva es que algo no va: el snapshotter la intenta
# cada diez minutos, así que dos días sin ninguna no es mala suerte.
VIEJA_A_LOS = timedelta(days=2)


def carpeta() -> Path:
    """Dónde van las copias. Se resuelve en cada llamada: los tests la mueven."""
    declarada = os.environ.get("HUB_RESPALDO")
    return Path(declarada) if declarada else config.HUB_HOME / "respaldos"


def _copias(donde: Path) -> list[Path]:
    if not donde.is_dir():
        return []
    return sorted(donde.glob(f"{PREFIJO}*.db"))


def hacer(con: sqlite3.Connection, ahora: datetime | None = None,
          conservar: int = CONSERVAR) -> Path | None:
    """Una copia por día; si la de hoy ya existe, no hace nada y devuelve None.

    Se escribe primero a `.tmp` y se renombra: un corte a mitad de la copia
    deja un `.tmp` suelto, nunca un `hub-<fecha>.db` que parece bueno.
    """
    ahora = ahora or datetime.now()
    donde = carpeta()
    destino = donde / f"{PREFIJO}{ahora:%Y%m%d}.db"
    if destino.exists():
        return None
    donde.mkdir(parents=True, exist_ok=True)
    temporal = destino.with_suffix(".db.tmp")
    copia = sqlite3.connect(temporal)
    try:
        con.backup(copia)
    finally:
        copia.close()
    temporal.replace(destino)
    for sobra in _copias(donde)[:-conservar]:
        sobra.unlink(missing_ok=True)
    return destino


def estado(ahora: datetime | None = None) -> dict:
    """Lo que enseña `/respaldo`: dónde, cuántas, y si la última es vieja."""
    ahora = ahora or datetime.now()
    donde = carpeta()
    copias = _copias(donde)
    if not copias:
        return {"carpeta": str(donde), "copias": 0, "ultima": None,
                "tamano": None, "vieja": True, "conservar": CONSERVAR}
    ultima = copias[-1]
    cuando = datetime.fromtimestamp(ultima.stat().st_mtime)
    return {
        "carpeta": str(donde),
        "copias": len(copias),
        "ultima": cuando.isoformat(timespec="minutes"),
        "tamano": ultima.stat().st_size,
        "vieja": ahora - cuando > VIEJA_A_LOS,
        "conservar": CONSERVAR,
    }
