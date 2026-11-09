"""La hora del hub: «ahora» y la hora local, cada una en un solo sitio (C-0051).

Había nueve `ahora()` idénticos, uno por módulo, y dos más con otro nombre.
Copiados así, el día que uno cambia —otra precisión, otra zona— los demás
siguen como estaban, y dos fechas de la misma base dejan de compararse.

Y había dos ideas de hora local: el secretario leía `TZ` o `/etc/timezone` y
si no, UTC; la web convertía con la de la máquina (`/etc/localtime`). Aquí
coincidían, pero en una distribución sin `/etc/timezone` el secretario
recordaba en UTC mientras la web enseñaba bien la hora. Ahora las dos
preguntan a `zona()`.

🔴 **Módulo hoja: sólo librería estándar.** Lo importan el snapshotter, los
relés, el secretario y `maquina`, que tenía su copia porque importar la de
`snapshotter` cerraba un círculo. Si esto importa algo del hub, el círculo
vuelve.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

# Dónde dice la máquina su zona. Nombres del módulo y no literales para que
# las pruebas quiten uno sin tocar la máquina.
ETC_TIMEZONE = Path("/etc/timezone")
ETC_LOCALTIME = Path("/etc/localtime")


def ahora() -> str:
    """Ahora en UTC, al segundo: como se guarda todo en las bases del hub.

    Siempre con zona (`+00:00`): una fecha sin zona se lee como hora local en
    un sitio y como UTC en otro, y ésa es la confusión que esto evita.
    """
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def instante(valor: str | None = None) -> datetime:
    """Una fecha guardada con `ahora()`, para comparar o restar; sin valor, ahora.

    Sin zona se lee como UTC, que es como se guarda todo: comparar una fecha sin
    zona con una con zona lanza, y donde se compara suele ser en mitad de tratar
    algo (C-0186). No es `a_local`, que es para enseñar y lee la fecha sin zona
    como hora de la casa (375). Quedan copias de esto como `_momento` en
    `avisos`, `orquestador` y `programados`.

    «Ahora» es `ahora()`, al segundo, y no `datetime.now()`: lo guardado va al
    segundo, y un plazo de 300 s medido con microsegundos de más se pasaba.
    """
    fecha = datetime.fromisoformat(valor or ahora())
    return fecha if fecha.tzinfo else fecha.replace(tzinfo=timezone.utc)


def _si_es_zona(nombre: str | None) -> str | None:
    """El nombre, si `ZoneInfo` lo conoce. Una `TZ` mal puesta lanzaba en cada
    página que enseña una hora: mejor seguir buscando que romper."""
    nombre = (nombre or "").strip().lstrip(":")
    if not nombre:
        return None
    try:
        ZoneInfo(nombre)
    except (KeyError, ValueError, OSError):   # ZoneInfoNotFoundError es un KeyError
        return None
    return nombre


def _del_enlace_de_localtime() -> str | None:
    """Con systemd (`timedatectl`), `/etc/localtime` es un enlace a
    `…/zoneinfo/<zona>`, y en Fedora o Arch es lo único que hay. Un archivo
    copiado no dice su nombre, y no se adivina."""
    try:
        destino = ETC_LOCALTIME.resolve(strict=True).as_posix()
    except (OSError, RuntimeError):
        return None
    _, marca, nombre = destino.rpartition("/zoneinfo/")
    if not marca:
        return None
    for copia in ("posix/", "right/"):
        nombre = nombre.removeprefix(copia)
    return _si_es_zona(nombre)


def zona() -> str:
    """La zona de la casa: una cita a las 10 es a las 10 de aquí (decisión 375).

    `TZ` → `/etc/timezone` → el enlace de `/etc/localtime` → UTC. `TZ` va
    primero porque es lo que se pone a propósito. `/etc/timezone` antes que el
    enlace conserva la zona con que el secretario ya ponía los recordatorios;
    el precio es que libc y `date` siguen el enlace, así que si alguien rehace
    sólo el enlace, la web pasa a seguir un `/etc/timezone` atrasado. En WSL
    los dos se reescriben juntos (medido: 2 ms de diferencia). Si un día
    discrepan de verdad, el enlace debería ir antes.
    """
    hallada = _si_es_zona(os.environ.get("TZ"))
    if hallada:
        return hallada
    try:
        hallada = _si_es_zona(ETC_TIMEZONE.read_text(encoding="utf-8"))
    except OSError:
        hallada = None
    return hallada or _del_enlace_de_localtime() or "UTC"


def a_local(iso: str | None, formato: str = "%Y-%m-%d %H:%M") -> str:
    """Una fecha de la base, en la hora de la casa y con el formato que se pida.

    Vacía no dice nada; lo que no es una fecha sale tal cual, que enseñarlo
    crudo es mejor que romper la página. Una fecha sin zona ya es de la casa,
    como la entiende `secretario.tiempo.a_utc` al guardarla.
    """
    if not iso:
        return ""
    try:
        momento = datetime.fromisoformat(iso)
    except ValueError:
        return iso
    casa = ZoneInfo(zona())
    if momento.tzinfo is None:
        momento = momento.replace(tzinfo=casa)
    return momento.astimezone(casa).strftime(formato)
