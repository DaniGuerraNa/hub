"""Reiniciar el puente con un botón de su pantalla, sin comandos (C-0470, decisión 446 del hub).

Tras actualizar, el puente sigue con el código de antes hasta reiniciarlo, y
quien lo usa no es técnico: un comando a mano es donde se atasca. El botón
sólo vale cuando el puente corre como servicio de usuario de systemd y este
proceso es **el de su unidad**: entonces basta pedirle a systemd que lo
reinicie, y lo vuelve a arrancar igual que arrancó (su entorno, su carpeta y
su contraseña). Sin systemd no se ofrece: relanzarse a sí mismo dejaría un
proceso que no es de nadie, o uno que se salta su unidad.

Que es el de su unidad se sabe por `INVOCATION_ID`, que systemd pone a cada
arranque de una unidad y que `systemctl show -p InvocationID` da igual (medido
con una unidad de prueba). El `MainPID` no sirve: el proceso principal es `uv`,
y el puente es su hijo.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import time

# Cuándo arrancó este proceso. Tras pedir el reinicio, la pantalla espera a que
# `/api/estado` dé otro: entonces ya contesta el nuevo, y recarga.
ARRANQUE = time.time()

# Un nombre de unidad y nada más: es lo que llega a la línea de órdenes.
NOMBRE = re.compile(r"[A-Za-z0-9][A-Za-z0-9@._-]{0,120}")
# Lo sabido por (INVOCATION_ID, unidad). "systemd" no cambia mientras viva el
# proceso; "a_mano" se vuelve a mirar pasado un minuto, por si systemctl no
# contestó a tiempo. Así el estado, que se pide cada segundo, no lanza una
# orden en cada vuelta.
_sabido: dict[tuple[str, str], tuple[str, float]] = {}
VOLVER_A_MIRAR = 60.0


def servicio() -> str:
    """La unidad del puente: la de `PUENTE_SERVICIO`, como en `scripts/servicio.sh`."""
    return os.environ.get("PUENTE_SERVICIO") or "puente-kvm"


def _clave() -> tuple[str, str] | None:
    """(INVOCATION_ID, unidad) si este proceso puede ser el de una unidad; None si seguro que no."""
    propio = os.environ.get("INVOCATION_ID", "")
    nombre = servicio()
    if not propio or not NOMBRE.fullmatch(nombre) or not shutil.which("systemctl"):
        return None
    return propio, nombre


def sabido() -> tuple[str, bool]:
    """Lo que ya se sabe, sin preguntarle a nadie: (cómo, si toca volver a mirar).

    Para `/api/estado`, que se contesta desde el bucle cada segundo: un
    `systemctl show` que tarda lo pararía todo. Volver a mirar es `como()`,
    en un hilo aparte (C-0470).
    """
    clave = _clave()
    if clave is None:
        return "a_mano", False
    if clave not in _sabido:
        return "a_mano", True
    resultado, cuando = _sabido[clave]
    return resultado, resultado != "systemd" and time.monotonic() - cuando >= VOLVER_A_MIRAR


def como() -> str:
    """"systemd" si este proceso es el de su unidad (el botón vale); "a_mano" si no.

    Puede preguntarle a systemd y esperar su respuesta: fuera del bucle (un hilo).
    """
    clave = _clave()
    if clave is None:
        return "a_mano"
    propio, nombre = clave
    resultado, mirar = sabido()
    if not mirar:
        return resultado
    try:
        r = subprocess.run(["systemctl", "--user", "show", "-p", "InvocationID", "--value", nombre],
                           capture_output=True, text=True, timeout=5)
        resultado = "systemd" if r.returncode == 0 and r.stdout.strip() == propio else "a_mano"
    except (OSError, subprocess.SubprocessError) as e:
        print(f"[reinicio] no pude preguntarle a systemd por {nombre}: {e}", flush=True)
        resultado = "a_mano"
    _sabido[clave] = (resultado, time.monotonic())
    return resultado


def pedir() -> bool:
    """Pide a systemd que reinicie la unidad, y vuelve en el acto. True si lo aceptó.

    🔴 Con `--no-block`. El `restart` normal espera a que la unidad pare, y
    lanzado desde dentro de ella es parte de lo que hay que parar: no vuelve
    nunca (systemd lo mata con el puente) y, mientras, esta tarea sigue abierta
    y retiene la parada. Medido con una unidad de prueba: el reinicio llega
    igual, pero el `systemctl` que espera no vuelve, y con `--no-block` vuelve
    con 0 en el acto. Se llama después de contestar a la página (una tarea de
    fondo de la respuesta), para que la respuesta llegue antes.
    """
    nombre = servicio()
    if not NOMBRE.fullmatch(nombre):
        print(f"[reinicio] nombre de unidad no admitido: {nombre!r}", flush=True)
        return False
    try:
        r = subprocess.run(["systemctl", "--user", "--no-block", "restart", nombre],
                           capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.SubprocessError) as e:
        print(f"[reinicio] no se pudo pedir el reinicio de {nombre}: {e}", flush=True)
        return False
    if r.returncode != 0:
        print(f"[reinicio] systemctl no aceptó el reinicio de {nombre}: {r.stderr.strip()}", flush=True)
        return False
    return True
