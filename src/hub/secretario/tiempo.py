"""La hora del dueño. Todo se guarda en UTC y se le enseña en su hora.

Vive aparte y no en un proveedor de calendario: la zona es de la máquina, no de
Google, y cambiar de calendario no puede mover la hora de los recordatorios.

La zona y cómo se enseña una hora son del hub entero, no sólo del secretario
(`reloj.zona`, `reloj.a_local`, C-0051): la web las usa igual, y dos ideas de
hora local acababan en un recordatorio a la hora equivocada. Aquí queda
lo que es del secretario: la hora de ahora en la casa y pasar lo que dice el
dueño a UTC.
"""

from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from ..reloj import a_local, instante, zona

__all__ = ["a_local", "a_utc", "ahora_local", "dicho_el", "limite_utc", "tiene_hora", "zona"]

DIAS = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")


def ahora_local() -> datetime:
    return datetime.now(ZoneInfo(zona()))


def dicho_el(iso: str | None) -> str:
    """Cuándo dijo algo el dueño, como se le pone delante al modelo (C-0272):
    «Te lo dice el jueves 2026-11-12 a las 16:42, hora de <zona>.», con la
    zona de `reloj.zona()` (la de la máquina).

    Con el día de la semana, que es lo que hace falta para «el jueves», y la
    fecha como la piden sus herramientas. Lo que no sea una fecha se toma
    como ahora: la marca no puede tumbar el turno."""
    try:
        momento = instante(iso)
    except (TypeError, ValueError):
        momento = instante()
    local = momento.astimezone(ZoneInfo(zona()))
    return f"Te lo dice el {DIAS[local.weekday()]} {local:%Y-%m-%d} a las {local:%H:%M}, hora de {zona()}."


def a_utc(local: str | None) -> str | None:
    """'AAAA-MM-DD[THH:MM]' en hora local → ISO en UTC. Un día sin hora es a las 9."""
    if not local:
        return None
    texto = local.strip()
    try:
        if len(texto) == 10:
            texto += "T09:00"
        d = datetime.fromisoformat(texto)
    except ValueError as exc:
        raise ValueError(f"fecha no válida: «{local}» (se espera AAAA-MM-DDTHH:MM)") from exc
    if d.tzinfo is None:
        d = d.replace(tzinfo=ZoneInfo(zona()))
    return d.astimezone(timezone.utc).isoformat(timespec="seconds")


def tiene_hora(local: str | None) -> bool:
    """Si lo que dijo lleva hora o es sólo un día, que `a_utc` pone a las 9:
    el aviso de un plazo depende de eso (`memoria.cuando_avisar`)."""
    return len((local or "").strip()) > 10


def limite_utc(local: str | None, *, fin: bool = False) -> str | None:
    """Un límite de lo que se busca (`desde`, o `hasta` con `fin`), en hora
    local → ISO en UTC. Un día sin hora es su principio, o su final con
    `fin`: las 9 de `a_utc` son para un recordatorio, y como `hasta` dejaban
    fuera la tarde de ese día (SEC-01)."""
    texto = (local or "").strip()
    if len(texto) == 10:
        texto += "T23:59:59" if fin else "T00:00"
    return a_utc(texto)
