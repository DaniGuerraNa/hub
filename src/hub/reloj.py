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


def _en_casa(iso: str) -> datetime:
    """Una fecha para ENSEÑAR, ya en la hora de la casa. Lanza `ValueError` si
    no es una fecha.

    Sin zona es de la casa, como la entiende `secretario.tiempo.a_utc` al
    guardarla (y como la guardan `copia_base` o `intercambio`). Es el lector
    de `a_local` y de `cuando`, y tiene que ser el mismo: con `instante`, que
    lee lo de sin zona como UTC, el «hace» y la hora de la misma fecha
    discreparían seis horas (regla 19, C-0396).
    """
    momento = datetime.fromisoformat(iso)
    casa = ZoneInfo(zona())
    if momento.tzinfo is None:
        momento = momento.replace(tzinfo=casa)
    return momento.astimezone(casa)


def a_local(iso: str | None, formato: str = "%Y-%m-%d %H:%M") -> str:
    """Una fecha de la base, en la hora de la casa y con el formato que se pida.

    Vacía no dice nada; lo que no es una fecha sale tal cual, que enseñarlo
    crudo es mejor que romper la página. Una fecha sin zona ya es de la casa.
    Para enseñarla en una pantalla está `cuando`; esto queda para las frases y
    los formatos que pide otro (un `datetime-local`, el prompt del modelo).
    """
    if not iso:
        return ""
    try:
        return _en_casa(iso).strftime(formato)
    except ValueError:
        return iso


def duracion(segundos: float) -> str:
    """Un lapso, en la unidad en que se lee: «40 s», «12 min», «5 h», «9 d».

    Cada unidad aguanta hasta dos de la siguiente —119 min y no «1 h»—
    porque el redondeo hacia abajo en la unidad grande miente por casi la
    mitad: «1 h» para 119 minutos. Había dos copias de esto (`salud`, la
    fuente de WhatsApp) con cortes distintos.
    """
    s = int(abs(segundos))
    if s < 120:
        return f"{s} s"
    if s < 7200:
        return f"{s // 60} min"
    if s < 172800:
        return f"{s // 3600} h"
    return f"{s // 86400} d"


def cuando(valor, ahora: datetime | None = None) -> dict | None:
    """Un instante, listo para enseñarlo: `{iso, local, dia, hora, hace, edad_s}`.

    Es la puerta de toda fecha de pantalla (C-0396): había ocho formatos, la
    mitad en UTC, y un dato de hace 62 días se leía igual que uno de hoy. Lo
    pinta `ui.cuando` de `_ui.html`, que es quien decide qué pieza se ve.

    - `valor`: ISO con o sin zona (sin zona = hora de la casa, como `a_local`),
      sólo la fecha (`2026-11-13`), o un epoch en segundos.
    - `local`: «13/11 14:41»; con el año si no es el de ahora; sin hora si el
      valor no la trae. `dia` y `hora` son sus dos mitades.
    - `hace`: «hace 3 h», «en 2 d» si está por venir, «hoy»/«ayer»/«mañana»
      sin hora. No baja de «hace un momento»: unos segundos que cambian en
      cada sondeo repintarían la región sin decir nada.
    - `edad_s`: segundos desde entonces, negativa si está por venir. Es con lo
      que `ui.cuando` compara su umbral.

    `None` si está vacío o no es una fecha: la plantilla decide qué enseñar.
    """
    ahora = ahora or datetime.now(timezone.utc)
    casa = ZoneInfo(zona())
    hoy = ahora.astimezone(casa)
    sin_hora = False
    try:
        if isinstance(valor, bool) or valor is None or valor == "":
            return None
        if isinstance(valor, (int, float)):
            momento = datetime.fromtimestamp(valor, timezone.utc).astimezone(casa)
        elif isinstance(valor, str):
            sin_hora = len(valor.strip()) == 10
            momento = _en_casa(valor.strip())
        else:
            return None
    except (ValueError, OverflowError, OSError):
        return None
    con_ano = "" if momento.year == hoy.year else "/%Y"
    dia = momento.strftime("%d/%m" + con_ano)
    if sin_hora:
        dias = (hoy.date() - momento.date()).days
        hace = {0: "hoy", 1: "ayer", -1: "mañana"}.get(
            dias, f"hace {dias} d" if dias > 0 else f"en {-dias} d")
        return {"iso": momento.date().isoformat(), "local": dia, "dia": dia, "hora": "",
                "hace": hace, "edad_s": int((ahora - momento).total_seconds())}
    edad = int((ahora - momento).total_seconds())
    if abs(edad) < 60:
        hace = "hace un momento"
    else:
        lapso = "1 min" if abs(edad) < 120 else duracion(edad)
        hace = f"hace {lapso}" if edad > 0 else f"en {lapso}"
    hora = momento.strftime("%H:%M")
    return {"iso": momento.isoformat(timespec="seconds"), "local": f"{dia} {hora}", "dia": dia,
            "hora": hora, "hace": hace, "edad_s": edad}
