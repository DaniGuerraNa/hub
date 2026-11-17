"""Apagar un servidor de tmux de pruebas sin dejar rastro.

🔴 `kill-server` no basta: tmux 3.4 deja el archivo del socket en
`/tmp/tmux-<uid>/` también cuando su servidor se va solo al cerrar la última
sesión. Cada servidor de pruebas con nombre propio (uno por pasada, uno por
recorrido de pantallas) dejaba el suyo: el 11-nov había 144 muertos, y el
13-nov 147 sólo del recorrido de pantallas (C-0325).
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path


def ruta_del_socket(zocalo: str) -> Path:
    """Donde lo pone tmux para `-L <zocalo>`: `$TMUX_TMPDIR` o `/tmp`, y dentro
    `tmux-<uid>`."""
    return Path(os.environ.get("TMUX_TMPDIR") or "/tmp") / f"tmux-{os.getuid()}" / zocalo


def apagar(zocalo: str) -> None:
    """`kill-server` sobre ese socket y fuera su archivo.

    🔴 Sólo para servidores de pruebas con nombre propio: con `default`, o con
    el nombre del servidor de quien ejecuta la suite, esto le cerraría todas las
    sesiones. Por eso se niega a apagar uno sin nombre.
    """
    if not zocalo or zocalo == "default":
        raise ValueError("sólo se apaga un servidor de pruebas con nombre propio")
    if shutil.which("tmux"):
        # Sin servidor, `kill-server` falla y no pasa nada: era lo que se quería.
        subprocess.run(["tmux", "-L", zocalo, "kill-server"], capture_output=True,
                       check=False, timeout=10)
    try:
        ruta_del_socket(zocalo).unlink()
    except FileNotFoundError:
        pass
