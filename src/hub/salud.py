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
import re
import shutil
import subprocess
from datetime import datetime, timezone

from . import acceso, config, copia_base, tmux

ARCHIVO_LATIDO = "latido-snapshotter.json"
# El muestreo late cada `INTERVALO_SEGUNDOS` (20 s). Unas cuantas vueltas
# perdidas son un ciclo lento o una base ocupada; minutos, que no corre.
AVISO_SEGUNDOS = 120
MAL_SEGUNDOS = 300


def _servicios_del_hub() -> tuple[str, ...]:
    """Los que instala `scripts/lib/unidades.sh`, leídos de ahí (C-0115).

    Estaban también aquí y en `desinstalar.sh`, y ya habían divergido: un
    servicio nuevo que no se añade en los tres sitios se instala pero no se
    vigila, o se vigila pero no se quita. Que cada uno tenga su plantilla lo
    comprueba `tests/test_salud.py`."""
    texto = (config.RAIZ_REPO / "scripts" / "lib" / "unidades.sh").read_text(encoding="utf-8")
    m = re.search(r'^SERVICIOS_HUB="([^"]*)"', texto, re.M)
    if not m:
        raise RuntimeError("scripts/lib/unidades.sh no declara SERVICIOS_HUB")
    return tuple(m.group(1).split())


SERVICIOS = _servicios_del_hub()
# Los que el hub necesita siempre. Canal, encargos y secretario son opcionales: sólo
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
                           "guarda qué ventanas tenías y al reiniciar no habrá nada que reabrir.",
                "arreglo": arreglo}
    if edad >= MAL_SEGUNDOS:
        return {"clave": "muestreo", "nombre": "Muestreo", "estado": "mal",
                "detalle": f"El snapshotter no late desde hace {_hace(edad)}. Mientras no "
                           "corra, no se guarda qué ventanas tienes: si reinicias ahora, no se "
                           "podrán reabrir.",
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
                       "slots persistentes, Panorama te ofrece reabrirlos.",
            "arreglo": "Panorama → «Reabrir tus slots persistentes»"}


def _restauracion(slots: list[dict]) -> dict:
    """`slots` son los activos, leídos por `api.py` (una sola costura, C-0056)."""
    activos = len(slots)
    marcados = sum(1 for s in slots if s.get("restaurar"))
    if not activos:
        return {"clave": "restauracion", "nombre": "Slots persistentes", "estado": "ok",
                "detalle": "Todavía no hay slots: no hay nada que reabrir."}
    if not marcados:
        return {"clave": "restauracion", "nombre": "Slots persistentes", "estado": "aviso",
                "detalle": f"Ninguno de tus {activos} slots es persistente: si reinicias el "
                           "equipo, no habrá nada que reabrir.",
                "arreglo": "En Trabajo, en la cabecera de cada slot que quieras conservar, "
                           "pulsa «↻ No persistente» para que pase a «↻ Persistente»"}
    return {"clave": "restauracion", "nombre": "Slots persistentes", "estado": "ok",
            "detalle": f"{marcados} de {activos} slots son persistentes (marcados con ↻)."}


def _systemctl(*args: str) -> str | None:
    if not shutil.which("systemctl"):
        return None
    try:
        r = subprocess.run(["systemctl", "--user", *args], capture_output=True, text=True,
                           timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout.strip()


def hay_systemd_de_usuario() -> bool:
    """Si hay un systemd de usuario que gestione los servicios del hub.

    La única pregunta (C-0115; la usa también `actualizacion`). Por el código
    de salida de `show-environment`: con `systemctl` instalado y sin sesión de
    usuario, la salida vacía se tomaba por «sí» y web y muestreo salían como
    parados en vez de decir que no hay systemd."""
    if not shutil.which("systemctl"):
        return False
    try:
        return subprocess.run(["systemctl", "--user", "show-environment"], capture_output=True,
                              timeout=5).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _servicios() -> list[dict]:
    if not hay_systemd_de_usuario():
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


def _con_nombre_remoto() -> bool:
    """Si se entra desde otro aparato: sólo entonces importa volver sin nadie."""
    try:
        return any(h not in acceso.HOSTS_LOCALES for h in acceso.hosts())
    except acceso.AccesoInvalido:
        return False   # eso ya lo dice /acceso, con el archivo que falla


def _desatendido(medidas: dict[str, dict]) -> list[dict]:
    """Lo que hace falta para que un apagón tenga vuelta sin nadie delante (C-0214).

    Lo midió el ciclo lento (`maquina._tailscale` y `maquina._arranque`); aquí
    sólo se juzga. Lo que no se pudo medir no sale: un «ok» puesto por defecto
    es justo lo que esta pantalla no hace. Y sólo con un nombre remoto en
    `acceso.yml`: quien usa el hub delante de la máquina inicia sesión él.
    """
    if not _con_nombre_remoto():
        return []

    # 🔴 Sólo cuenta lo de la última vuelta lenta. Una medida que dejó de
    # poderse tomar conserva la anterior (`maquina`), y con Tailscale parado o
    # desinstalado eso enseñaba su último «bien» justo cuando no se puede
    # entrar. El SAI se mide aparte, cada minuto: no marca la vuelta.
    vuelta = max((m.get("medido_en") or "" for k, m in medidas.items()
                  if not k.startswith("ups.")), default="")

    def vieja(clave: str) -> bool:
        m = medidas.get(clave)
        return bool(m) and (m.get("medido_en") or "") < vuelta

    def medida(clave: str) -> dict | None:
        m = medidas.get(clave)
        return m if m and m.get("valor") is not None and not vieja(clave) else None

    nombre = "Volver sola tras un apagón"
    salida = []
    if vieja("desatendido.serve") or vieja("desatendido.tailscale"):
        salida.append({"clave": "desatendido:sin-medir", "nombre": "Entrar desde fuera",
                       "estado": "aviso",
                       "detalle": "En la última medición no se pudo leer Tailscale. Si está "
                                  "parado, desde otro aparato no se entra.",
                       "arreglo": "En la máquina del hub: tailscale status"})
    if serve := medida("desatendido.serve"):
        if serve["valor"]:
            salida.append({"clave": "desatendido:serve", "nombre": "Entrar desde fuera",
                           "estado": "ok",
                           "detalle": f"La red privada lleva al hub ({serve['texto']})."})
        else:
            salida.append({"clave": "desatendido:serve", "nombre": "Entrar desde fuera",
                           "estado": "mal",
                           "detalle": "tailscale serve no lleva al hub: desde otro aparato "
                                      "no se llega, aunque el nombre esté en Acceso.",
                           "arreglo": f"En la máquina del hub: tailscale serve --bg {config.WEB_PORT}"})
    if ts := medida("desatendido.tailscale"):
        if ts["valor"]:
            salida.append({"clave": "desatendido:tailscale", "nombre": nombre, "estado": "ok",
                           "detalle": "Tailscale conecta al encender aunque nadie inicie "
                                      "sesión en Windows."})
        else:
            salida.append({"clave": "desatendido:tailscale", "nombre": nombre, "estado": "aviso",
                           "detalle": "Tailscale sólo conecta con la sesión de Windows "
                                      "iniciada: tras un apagón no se podrá entrar desde fuera "
                                      "hasta que alguien entre en Windows.",
                           "arreglo": "En Windows, en PowerShell: tailscale set --unattended=true"})
    if tarea := medida("desatendido.tarea"):
        if tarea["valor"]:
            salida.append({"clave": "desatendido:tarea", "nombre": nombre, "estado": "ok",
                           "detalle": f"Al encender, la tarea «{tarea['texto']}» levanta WSL "
                                      "sin que nadie inicie sesión."})
        else:
            salida.append({"clave": "desatendido:tarea", "nombre": nombre, "estado": "aviso",
                           "detalle": "Al encender, WSL —y el hub con él— no arranca hasta que "
                                      "alguien inicia sesión en Windows.",
                           "arreglo": "scripts/arrancar-sin-sesion.ps1, en PowerShell "
                                      "como administrador (INSTALAR.md, «El hub en una "
                                      "máquina aparte»)"})
    if susp := medida("desatendido.suspender"):
        if not susp["valor"]:
            salida.append({"clave": "desatendido:suspender", "nombre": "No suspenderse",
                           "estado": "ok", "detalle": "Con corriente, Windows no se suspende."})
        else:
            salida.append({"clave": "desatendido:suspender", "nombre": "No suspenderse",
                           "estado": "aviso",
                           "detalle": f"Con corriente, Windows se suspende tras "
                                      f"{_hace(int(susp['valor']))} sin nadie delante, y "
                                      "el hub deja de contestar.",
                           "arreglo": "En Windows: powercfg /change standby-timeout-ac 0"})
    return salida


def revisar(slots: list[dict], medidas: dict[str, dict] | None = None) -> list[dict]:
    """Todas las comprobaciones, lo que peor está primero. `slots`, los activos;
    `medidas`, lo último que midió el ciclo lento (`maquina.ultimas`)."""
    revisiones = [muestreo(), _tmux(), _restauracion(slots), *_servicios(),
                  *_desatendido(medidas or {})]
    for extra in (_linger(), _copia()):
        if extra:
            revisiones.append(extra)
    orden = {"mal": 0, "aviso": 1, "ok": 2}
    return sorted(revisiones, key=lambda r: orden[r["estado"]])
