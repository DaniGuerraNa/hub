"""Actualizar el hub con un botón (decisión 296).

Es `bash scripts/actualizar.sh`, el mismo y entero, lanzado desde la pantalla
Actualizaciones en vez de copiado a una terminal. Lo que importa es DÓNDE corre.

🔴 **Fuera del grupo de procesos de `hub-web`.** `actualizar.sh` reinicia
`hub-web`, y systemd mata al reiniciar todo lo que cuelga de su cgroup: lanzado
como hijo normal, la actualización moriría a medias justo al reiniciar el
servicio que la lanzó —la decisión 153 cuenta lo mismo con tmux—. Por eso va en
una unidad transitoria propia (`systemd-run --user`), que sobrevive al
reinicio. Sin systemd, en una sesión nueva (`setsid`), y detrás se rearranca el
hub con `arrancar.sh`, que es lo que ahí hace las veces de servicio.

Lo que pasa se escribe en `HUB_HOME/actualizacion/`: el registro entero y el
resultado. La pantalla lo va leyendo, también cuando el hub vuelve del reinicio
—por eso no puede vivir en la memoria del proceso que se reinicia—.

No hay nada automático: lo lanza la persona, después de confirmar (regla dura 3).
"""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import time
from pathlib import Path

from . import config

UNIDAD = "hub-actualizar"


def carpeta() -> Path:
    d = config.HUB_HOME / "actualizacion"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _registro() -> Path:
    return carpeta() / "registro.log"


def _resultado() -> Path:
    return carpeta() / "resultado.json"


def _inicio() -> Path:
    return carpeta() / "inicio.json"


def cambios_locales(raiz: Path | None = None) -> list[str]:
    """Lo que `actualizar.sh` encontraría en su paso 1 y le haría parar.

    Se enseña ANTES del botón: descubrirlo después, en un registro, es lo que
    le pasó a la primera persona que actualizó (23-oct)."""
    try:
        r = subprocess.run(["git", "-C", str(raiz or config.RAIZ_REPO), "status", "--porcelain",
                            "--untracked-files=no"], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return []
    return [l for l in r.stdout.splitlines() if l.strip()]


def _con_systemd() -> bool:
    if not shutil.which("systemd-run"):
        return False
    try:
        return subprocess.run(["systemctl", "--user", "show-environment"], capture_output=True,
                              timeout=5).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def en_marcha() -> bool:
    """Si hay una actualización corriendo: empezó y aún no dejó su resultado."""
    inicio = _leer(_inicio())
    if not inicio:
        return False
    resultado = _leer(_resultado())
    if resultado and resultado.get("t", 0) >= inicio.get("t", 0):
        return False
    # Una que lleva más de media hora sin resultado no está corriendo: murió.
    return time.time() - inicio.get("t", 0) < 1800


def _leer(ruta: Path) -> dict | None:
    try:
        return json.loads(ruta.read_text())
    except (OSError, ValueError):
        return None


def lanzar(sin_bajar: bool = False) -> dict:
    """Arranca `actualizar.sh` por su cuenta y vuelve en el acto."""
    from . import tmux

    if en_marcha():
        raise RuntimeError("ya hay una actualización en marcha")
    raiz = config.RAIZ_REPO
    guion = raiz / "scripts" / "actualizar.sh"
    if not guion.is_file():
        raise RuntimeError(f"no encuentro {guion}")
    con_systemd = _con_systemd()
    orden = f"bash {shlex.quote(str(guion))}" + (" --sin-bajar" if sin_bajar else "")
    if not con_systemd:
        # Sin servicios, actualizar.sh no reinicia nada: lo hace arrancar.sh.
        orden += f" && bash {shlex.quote(str(raiz / 'scripts' / 'arrancar.sh'))}"
    resultado = shlex.quote(str(_resultado()))
    linea = (f"cd {shlex.quote(str(raiz))} && {{ {orden}; }} > {shlex.quote(str(_registro()))} 2>&1; "
             f"rc=$?; printf '{{\"rc\": %d, \"t\": %d}}\\n' \"$rc\" \"$(date +%s)\" > {resultado}")
    entorno = {**os.environ, "PATH": tmux.path_de_usuario(), "HUB_HOME": str(config.HUB_HOME)}
    _registro().write_text("")
    _inicio().write_text(json.dumps({"t": int(time.time()), "sin_bajar": sin_bajar}))
    if con_systemd:
        cmd = ["systemd-run", "--user", "--quiet", "--collect", f"--unit={UNIDAD}-{int(time.time())}",
               f"--setenv=PATH={entorno['PATH']}", f"--setenv=HUB_HOME={config.HUB_HOME}",
               "bash", "-c", linea]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=20, env=entorno)
        if r.returncode != 0:
            _inicio().unlink(missing_ok=True)
            raise RuntimeError((r.stderr or "systemd-run falló").strip()[:300])
    else:
        subprocess.Popen(["bash", "-c", linea], env=entorno, start_new_session=True,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return {"systemd": con_systemd}


def estado() -> dict:
    """Lo que pinta la pantalla mientras actualiza, y cuando vuelve del reinicio."""
    inicio = _leer(_inicio())
    resultado = _leer(_resultado())
    if resultado and inicio and resultado.get("t", 0) < inicio.get("t", 0):
        resultado = None
    try:
        texto = _registro().read_text(errors="replace")
    except OSError:
        texto = ""
    return {
        "en_marcha": en_marcha(),
        "lanzada": inicio.get("t") if inicio else None,
        "rc": resultado.get("rc") if resultado else None,
        "registro": _limpio(texto)[-12000:],
    }


def _limpio(texto: str) -> str:
    """Sin los códigos de color de la terminal, que en la página son basura."""
    import re
    return re.sub(r"\x1b\[[0-9;]*m", "", texto)
