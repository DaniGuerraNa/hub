"""¿Está el hub en condiciones de hacer lo que promete? (decisión 289)

Lo pidió el dueño tras un fallo de un usuario: apagó el equipo, lo encendió al
día siguiente y no le volvió ninguna ventana. Desde fuera no se sabía si fue
porque el muestreo no corría, porque no había ningún slot marcado o por otra
cosa — y ninguna pantalla lo había advertido ANTES del apagón, que es cuando
tenía arreglo.

Cada comprobación dice tres cosas: qué mira, cómo está (`ok`, `aviso`, `mal`)
y qué hacer. Se miden de verdad (regla dura 13): lo que no se puede comprobar
desde aquí no sale con un «ok» puesto por defecto.

🔴 **El latido es del snapshotter, no de las muestras.** Sin tmux abierto —lo
normal nada más encender— el muestreo no escribe muestra (regla dura 4), así
que «la última muestra es de hace horas» no distingue un snapshotter muerto de
uno vivo esperando. Por eso el bucle deja su propio latido en cada vuelta.
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
from datetime import datetime, timezone

from . import config, copia_base, tmux

ARCHIVO_LATIDO = "latido-snapshotter.json"
# El muestreo late cada `INTERVALO_SEGUNDOS` (20 s). Unas cuantas vueltas
# perdidas son un ciclo lento o una base ocupada; minutos, que no corre.
AVISO_SEGUNDOS = 120
MAL_SEGUNDOS = 300

SERVICIOS = ("hub-web", "hub-snapshotter", "hub-canal", "hub-encargos")
# Los que el hub necesita siempre. Canal y encargos son opcionales: sólo
# cuentan si están habilitados.
IMPRESCINDIBLES = ("hub-web", "hub-snapshotter")


def latir() -> None:
    """Lo llama el bucle del snapshotter en cada vuelta, haya tmux o no."""
    destino = config.HUB_HOME / ARCHIVO_LATIDO
    tmp = destino.with_suffix(".tmp")
    tmp.write_text(json.dumps({"en": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                               "pid": os.getpid()}))
    tmp.replace(destino)


def _edad_latido(ahora: datetime | None = None) -> int | None:
    try:
        datos = json.loads((config.HUB_HOME / ARCHIVO_LATIDO).read_text())
        cuando = datetime.fromisoformat(datos["en"])
    except (OSError, ValueError, KeyError):
        return None
    ahora = ahora or datetime.now(timezone.utc)
    return max(0, int((ahora - cuando).total_seconds()))


def _hace(segundos: int) -> str:
    if segundos < 120:
        return f"{segundos} s"
    if segundos < 7200:
        return f"{segundos // 60} min"
    return f"{segundos // 3600} h"


def muestreo(ahora: datetime | None = None) -> dict:
    """Barato: un archivo. Es lo que se mira en TODAS las pantallas."""
    edad = _edad_latido(ahora)
    arreglo = ("systemctl --user restart hub-snapshotter   "
               "(y si no arranca: journalctl --user -u hub-snapshotter -n 40)")
    if edad is None:
        return {"clave": "muestreo", "nombre": "Muestreo", "estado": "mal",
                "detalle": "El snapshotter no ha latido nunca: no está corriendo. Sin él no se "
                           "guarda qué ventanas tenías y tras un apagón no hay nada que restaurar.",
                "arreglo": arreglo}
    if edad >= MAL_SEGUNDOS:
        return {"clave": "muestreo", "nombre": "Muestreo", "estado": "mal",
                "detalle": f"El snapshotter no late desde hace {_hace(edad)}. Mientras no "
                           "corra, no se guarda qué ventanas tienes: un apagón ahora no se "
                           "podría restaurar.",
                "arreglo": arreglo, "edad": edad}
    if edad >= AVISO_SEGUNDOS:
        return {"clave": "muestreo", "nombre": "Muestreo", "estado": "aviso",
                "detalle": f"Último latido hace {_hace(edad)}: va con retraso.",
                "arreglo": arreglo, "edad": edad}
    return {"clave": "muestreo", "nombre": "Muestreo", "estado": "ok",
            "detalle": f"Late cada {config.INTERVALO_SEGUNDOS} s (último hace {_hace(edad)}).",
            "edad": edad}


def _tmux() -> dict:
    abierto = tmux.servidor_pid() is not None
    if abierto:
        return {"clave": "tmux", "nombre": "tmux", "estado": "ok",
                "detalle": "Hay un servidor de tmux con ventanas que vigilar."}
    return {"clave": "tmux", "nombre": "tmux", "estado": "aviso",
            "detalle": "No hay tmux abierto. Es normal nada más encender el equipo; si tenías "
                       "ventanas, mira en Panorama si te ofrece restaurarlas.",
            "arreglo": "Panorama → «Puedes volver a dejarlo como estaba»"}


def _restauracion(con: sqlite3.Connection) -> dict:
    activos = con.execute("SELECT COUNT(*) FROM slot WHERE status='activo'").fetchone()[0]
    marcados = con.execute(
        "SELECT COUNT(*) FROM slot WHERE status='activo' AND restaurar=1").fetchone()[0]
    if not activos:
        return {"clave": "restauracion", "nombre": "Restaurar tras un apagón", "estado": "ok",
                "detalle": "Todavía no hay slots: no hay nada que devolver."}
    if not marcados:
        return {"clave": "restauracion", "nombre": "Restaurar tras un apagón", "estado": "aviso",
                "detalle": f"Ninguno de tus {activos} slots vuelve tras un apagón: si se apaga "
                           "el equipo, «Restaurar» no tendrá nada que abrir.",
                "arreglo": "En Trabajo, en la cabecera de cada slot, pulsa «↻ No vuelve tras un "
                           "apagón» para que vuelva"}
    return {"clave": "restauracion", "nombre": "Restaurar tras un apagón", "estado": "ok",
            "detalle": f"{marcados} de {activos} slots vuelven tras un apagón (marcados con ↻)."}


def _systemctl(*args: str) -> str | None:
    if not shutil.which("systemctl"):
        return None
    try:
        r = subprocess.run(["systemctl", "--user", *args], capture_output=True, text=True,
                           timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout.strip()


def _servicios() -> list[dict]:
    if _systemctl("show-environment") is None:
        return [{"clave": "servicios", "nombre": "Servicios", "estado": "aviso",
                 "detalle": "No hay systemd de usuario: el hub no arranca solo ni se levanta "
                            "si se cae. Lo arrancas tú con scripts/arrancar.sh.",
                 "arreglo": "INSTALAR.md, «Servicios»"}]
    salida = []
    for nombre in SERVICIOS:
        habilitado = _systemctl("is-enabled", nombre) == "enabled"
        activo = _systemctl("is-active", nombre) == "active"
        if not habilitado and nombre not in IMPRESCINDIBLES:
            continue   # canal o encargos sin configurar: no es un fallo
        if activo and habilitado:
            estado, detalle = "ok", "En marcha, y arranca solo."
        elif activo:
            estado, detalle = "aviso", "En marcha, pero no arranca solo al encender."
        else:
            estado, detalle = "mal", "Parado."
        salida.append({"clave": f"servicio:{nombre}", "nombre": nombre, "estado": estado,
                       "detalle": detalle,
                       "arreglo": None if estado == "ok" else
                       f"systemctl --user enable --now {nombre}"})
    return salida


def _linger() -> dict | None:
    usuario = os.environ.get("USER") or ""
    if not usuario or not shutil.which("loginctl"):
        return None
    try:
        r = subprocess.run(["loginctl", "show-user", usuario, "-p", "Linger"],
                           capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    if "Linger=yes" in r.stdout:
        return {"clave": "linger", "nombre": "Seguir vivo sin terminal", "estado": "ok",
                "detalle": "El hub sigue corriendo aunque cierres todas las terminales."}
    if "Linger=no" in r.stdout:
        return {"clave": "linger", "nombre": "Seguir vivo sin terminal", "estado": "aviso",
                "detalle": "Al cerrar la última terminal se apagan los servicios del hub, y el "
                           "muestreo con ellos.",
                "arreglo": f"loginctl enable-linger {usuario}"}
    return None


def _copia() -> dict:
    e = copia_base.estado()
    if not e["copias"]:
        return {"clave": "copia", "nombre": "Copia de la base", "estado": "aviso",
                "detalle": "Todavía no hay ninguna copia de hub.db (se hace sola una vez al día).",
                "arreglo": "Mira que el muestreo corra: la copia la hace él."}
    if e["vieja"]:
        return {"clave": "copia", "nombre": "Copia de la base", "estado": "aviso",
                "detalle": f"La última copia de hub.db es del {e['ultima'].replace('T', ' ')}.",
                "arreglo": "Mira que el muestreo corra: la copia la hace él."}
    return {"clave": "copia", "nombre": "Copia de la base", "estado": "ok",
            "detalle": f"Última del {e['ultima'].replace('T', ' ')}, {e['copias']} guardadas."}


def revisar(con: sqlite3.Connection) -> list[dict]:
    """Todas las comprobaciones, lo que peor está primero."""
    revisiones = [muestreo(), _tmux(), _restauracion(con), *_servicios()]
    for extra in (_linger(), _copia()):
        if extra:
            revisiones.append(extra)
    orden = {"mal": 0, "aviso": 1, "ok": 2}
    return sorted(revisiones, key=lambda r: orden[r["estado"]])
