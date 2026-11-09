"""Proveedor de agenda: la dirección secreta iCal, sólo lectura (decisión 327).

Google Calendar (y Outlook, y casi cualquier calendario) da una «dirección
secreta en formato iCal»: una URL que devuelve el calendario entero. Leerla no
pide crear nada en Google Cloud ni pasar por OAuth: se copia y se pega. Para
leer la agenda —lo que usan `agenda`, el resumen del día y los disparadores
`antes_de_evento`— basta. Para **crear** eventos sigue haciendo falta el
proveedor `google`.

🔴 **La URL es una llave de su calendario** (regla dura 5): quien la tenga lo lee
entero. Vive en `~/.secretos/secretario-ical/url` con permisos 600 y sólo la
abre `hub-secretario`. Si se filtra, en Google se «restablece» y deja de valer.

Lo leído se guarda **en memoria** y unos minutos, nunca en disco: es el
calendario del dueño, y una copia en `HUB_HOME` sería una más que proteger.
Las repeticiones (`RRULE`) las expande `recurring_ical_events`: a mano es justo
donde se equivoca uno (excepciones, zonas, días festivos movidos).
"""

from __future__ import annotations

import os
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from ..tiempo import zona
from ... import llavero
from . import Calendario

#: Cuánto vale lo descargado. Los disparadores preguntan cada 5 minutos.
VIGENCIA_S = 240
TIMEOUT_S = 20
MAX_BYTES = 20 * 1024 * 1024

_CACHE: dict = {"t": 0.0, "url": "", "cal": None}


def carpeta() -> Path:
    return Path(os.environ.get("HUB_SECRETARIO_ICAL", "~/.secretos/secretario-ical")).expanduser()


#: Para el inventario del llavero (C-0143): dónde vive, nunca el valor.
LLAVES = (llavero.Llave("secretario-ical", "la dirección privada de tu agenda iCal", lambda: str(carpeta())),)


def _url() -> str | None:
    try:
        u = (carpeta() / "url").read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return u or None


def disponible() -> str | None:
    if not _url():
        return ("falta la dirección secreta iCal: en Google Calendar (web) → Configuración → tu calendario → "
                "«Dirección secreta en formato iCal», cópiala y corre: "
                "uv run python -m hub.secretario ical-entrar")
    return None


def _descargar(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "hub-secretario"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as r:
            return r.read(MAX_BYTES)
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403, 404):
            raise RuntimeError("el calendario no acepta la dirección iCal: puede que la restablecieran. "
                               "Copia la nueva y corre ical-entrar") from None
        raise RuntimeError(f"el calendario contestó {exc.code}") from None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise RuntimeError(f"no se pudo leer el calendario: {exc}") from None


def _calendario():
    import icalendar

    url = _url()
    if not url:
        raise RuntimeError(disponible())
    if _CACHE["cal"] is not None and _CACHE["url"] == url and time.monotonic() - _CACHE["t"] < VIGENCIA_S:
        return _CACHE["cal"]
    try:
        cal = icalendar.Calendar.from_ical(_descargar(url))
    except ValueError:
        raise RuntimeError("lo que devolvió la dirección no es un calendario iCal") from None
    _CACHE.update(t=time.monotonic(), url=url, cal=cal)
    return cal


def _iso(valor, z: ZoneInfo) -> str:
    """Como Google: `AAAA-MM-DD` si es de todo el día; si no, ISO con su zona, en hora local."""
    if isinstance(valor, datetime):
        if valor.tzinfo is None:
            valor = valor.replace(tzinfo=z)
        return valor.astimezone(z).isoformat()
    if isinstance(valor, date):
        return valor.isoformat()
    return str(valor or "")


def eventos(desde: datetime, hasta: datetime, n: int = 50) -> list[dict]:
    import recurring_ical_events

    z = ZoneInfo(zona())
    cal = _calendario()
    out = []
    for e in recurring_ical_events.of(cal).between(desde, hasta):
        ini = e.get("DTSTART")
        fin = e.get("DTEND")
        ini_v = ini.dt if ini is not None else None
        fin_v = fin.dt if fin is not None else None
        if fin_v is None and ini_v is not None and e.get("DURATION") is not None:
            fin_v = ini_v + e.get("DURATION").dt
        out.append({"id": f"{e.get('UID', '')}@{_iso(ini_v, z)}", "titulo": str(e.get("SUMMARY", "") or ""),
                    "inicio": _iso(ini_v, z), "fin": _iso(fin_v, z), "lugar": str(e.get("LOCATION", "") or ""),
                    "enlace": str(e.get("URL", "") or "")})

    def clave(x):
        v = x["inicio"]
        return v if "T" in v else v + "T00:00"
    out.sort(key=clave)
    return out[:n]


def entrar() -> None:  # pragma: no cover - interactivo
    """Pide la dirección, comprueba que es un calendario y sólo entonces la guarda."""
    import getpass
    print("Google Calendar (web) → ⚙ Configuración → en «Configuración de mis calendarios», tu calendario →\n"
          "«Integrar el calendario» → «Dirección secreta en formato iCal». Cópiala (no se verá al pegarla).\n")
    url = getpass.getpass("Dirección secreta iCal: ").strip()
    if not url.startswith("https://"):
        raise SystemExit("tiene que empezar por https://")
    import icalendar
    cal = icalendar.Calendar.from_ical(_descargar(url))
    n = sum(1 for _ in cal.walk("VEVENT"))
    d = carpeta()
    d.mkdir(parents=True, exist_ok=True)
    os.chmod(d, 0o700)
    ruta = d / "url"
    ruta.write_text(url + "\n", encoding="utf-8")
    os.chmod(ruta, 0o600)
    print(f"Leído: {n} eventos. Guardada en {ruta}. Para usarla, `agenda: ical` en secretario.yml "
          "(si no tienes Google conectado, se usa sola).")


class ProveedorIcal(Calendario):
    id = "ical"
    nombre = "Calendario por dirección iCal (sólo lectura)"

    def disponible(self) -> str | None:
        return disponible()

    def eventos(self, desde, hasta, n=50):
        return eventos(desde, hasta, n)

    def crear(self, titulo, inicio, fin=None, descripcion="", minutos_aviso=30):
        raise RuntimeError("con la dirección iCal la agenda es de sólo lectura: para crear eventos conecta "
                           "Google Calendar (google-entrar) y pon `agenda: google`")

    def entrar(self):  # pragma: no cover - interactivo
        entrar()


PROVEEDOR = ProveedorIcal()
