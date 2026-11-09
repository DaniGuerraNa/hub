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

from ..reloj import a_local, zona

__all__ = ["a_local", "a_utc", "ahora_local", "zona"]


def ahora_local() -> datetime:
    return datetime.now(ZoneInfo(zona()))


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
