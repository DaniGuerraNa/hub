"""La agenda por dirección secreta iCal (decisión 327), contra un servidor HTTP
de verdad que sirve un .ics con un evento que se repite."""
from __future__ import annotations

import http.server
import threading
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from hub.secretario import agenda
from hub.secretario.agenda import ical

ICS = b"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//prueba//ES
BEGIN:VEVENT
UID:daily-1
DTSTART;TZID=America/Mexico_City:20261102T100000
DTEND;TZID=America/Mexico_City:20261102T101500
RRULE:FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR
EXDATE;TZID=America/Mexico_City:20261104T100000
SUMMARY:Daily del equipo
LOCATION:Teams
END:VEVENT
BEGIN:VEVENT
UID:dia-1
DTSTART;VALUE=DATE:20261103
DTEND;VALUE=DATE:20261104
SUMMARY:Entrega de lambdas
END:VEVENT
END:VCALENDAR
"""


@pytest.fixture
def servidor(tmp_path, monkeypatch):
    pedidos = []

    class Manejador(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            pedidos.append(self.path)
            if self.path != "/secreto/basic.ics":
                self.send_response(404)
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/calendar")
            self.end_headers()
            self.wfile.write(ICS)

        def log_message(self, *a):
            pass

    s = http.server.HTTPServer(("127.0.0.1", 0), Manejador)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    monkeypatch.setenv("HUB_SECRETARIO_ICAL", str(tmp_path / "ical"))
    monkeypatch.setenv("HUB_SECRETARIO_GOOGLE", str(tmp_path / "google"))
    monkeypatch.setenv("TZ", "America/Mexico_City")
    monkeypatch.setattr(ical, "_CACHE", {"t": 0.0, "url": "", "cal": None})
    (tmp_path / "ical").mkdir()
    (tmp_path / "ical" / "url").write_text(f"http://127.0.0.1:{s.server_port}/secreto/basic.ics\n")
    yield pedidos
    s.shutdown()


def test_expande_las_repeticiones_salta_las_excepciones_y_da_horas_locales(servidor):
    z = ZoneInfo("America/Mexico_City")
    ev = ical.eventos(datetime(2026, 11, 2, tzinfo=z), datetime(2026, 11, 6, 23, 59, tzinfo=z))
    titulos = [(e["titulo"], e["inicio"]) for e in ev]
    assert titulos == [
        ("Daily del equipo", "2026-11-02T10:00:00-06:00"),
        ("Entrega de lambdas", "2026-11-03"),
        ("Daily del equipo", "2026-11-03T10:00:00-06:00"),
        ("Daily del equipo", "2026-11-05T10:00:00-06:00"),   # el miércoles 4 está exceptuado
        ("Daily del equipo", "2026-11-06T10:00:00-06:00"),
    ]
    assert ev[0]["fin"] == "2026-11-02T10:15:00-06:00" and ev[0]["lugar"] == "Teams"


def test_lo_descargado_se_reusa_unos_minutos_y_no_se_guarda_en_disco(servidor, tmp_path):
    z = ZoneInfo("America/Mexico_City")
    for _ in range(3):
        ical.eventos(datetime(2026, 11, 2, tzinfo=z), datetime(2026, 11, 3, tzinfo=z))
    assert len(servidor) == 1
    assert sorted(p.name for p in (tmp_path / "ical").iterdir()) == ["url"]


def test_sin_google_conectado_la_agenda_usa_ical_sola_y_no_crea(servidor):
    assert agenda.actual().id == "ical" and agenda.disponible() is None
    with pytest.raises(RuntimeError, match="sólo lectura"):
        agenda.crear("algo", "2026-11-03T10:00")


def test_una_direccion_restablecida_lo_dice(servidor, tmp_path):
    url = (tmp_path / "ical" / "url").read_text().replace("basic.ics", "vieja.ics")
    (tmp_path / "ical" / "url").write_text(url)
    with pytest.raises(RuntimeError, match="restablecieran"):
        ical.eventos(datetime(2026, 11, 2), datetime(2026, 11, 3))


def test_sin_direccion_dice_donde_sacarla(tmp_path, monkeypatch):
    monkeypatch.setenv("HUB_SECRETARIO_ICAL", str(tmp_path / "nada"))
    assert "Dirección secreta en formato iCal" in ical.disponible()
