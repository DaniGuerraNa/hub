"""La fuente de correo (IMAP, sólo lectura).

Lo de interpretar un correo se prueba con mensajes de verdad hechos con la
biblioteca estándar. La lectura, contra un servidor IMAP real: GreenMail en
Docker (`HUB_PRUEBA_IMAP=127.0.0.1:3143`, SMTP en 3025). Sin él, esos tests se
saltan y lo dicen; con un doble de `imaplib` sólo probarían que no revienta.
"""

from __future__ import annotations

import imaplib
import json
import os
import smtplib
import socket
import uuid
from email.message import EmailMessage
from pathlib import Path

import pytest

from hub.secretario.fuentes import correo


def _correo(de="Ana Pérez <ana@ejemplo.org>", para="dueno@hub.local", asunto="Reporte", texto="Hola", **cab) -> EmailMessage:
    m = EmailMessage()
    m["From"], m["To"], m["Subject"] = de, para, asunto
    m["Date"] = "Fri, 24 Oct 2026 10:00:00 -0600"
    m["Message-ID"] = f"<{uuid.uuid4()}@ejemplo.org>"
    for k, v in cab.items():
        m[k.replace("_", "-")] = v
    m.set_content(texto)
    return m


# ── interpretar un correo ────────────────────────────────────────────────────

def test_un_correo_normal_es_un_evento_con_asunto_remitente_y_fecha_en_utc():
    ev, masivo = correo.evento(_correo(texto="¿Me mandas el reporte el viernes?").as_bytes(), "7", "INBOX", {"dueno@hub.local"})
    assert not masivo
    assert ev.fuente == "correo" and ev.autor == "Ana Pérez" and ev.conversacion == "Ana Pérez <ana@ejemplo.org>"
    assert ev.fecha == "2026-10-24T16:00:00+00:00"
    assert ev.texto.startswith("Asunto: Reporte\n") and "¿Me mandas el reporte el viernes?" in ev.texto


def test_lo_que_mando_el_dueño_es_suyo():
    ev, _ = correo.evento(_correo(de="Yo <dueno@hub.local>", para="Ana <ana@ejemplo.org>").as_bytes(), "8", "Sent",
                          {"dueno@hub.local"})
    assert ev.autor == "Yo" and ev.conversacion == "Enviados: Ana"


def test_un_boletin_o_un_aviso_automatico_son_masivos():
    assert correo.evento(_correo(List_Unsubscribe="<mailto:baja@x.org>").as_bytes(), "1", "INBOX", set())[1]
    assert correo.evento(_correo(Auto_Submitted="auto-generated").as_bytes(), "1", "INBOX", set())[1]
    assert correo.evento(_correo(Precedence="bulk").as_bytes(), "1", "INBOX", set())[1]


def test_de_un_html_queda_el_texto_y_de_un_adjunto_el_nombre():
    m = _correo()
    m.set_content("<html><head><style>p{}</style></head><body><p>Te paso el <b>contrato</b>.</p></body></html>",
                  subtype="html")
    m.add_attachment(b"%PDF", maintype="application", subtype="pdf", filename="contrato.pdf")
    ev, _ = correo.evento(m.as_bytes(), "2", "INBOX", set())
    assert "Te paso el contrato ." in ev.texto and "<b>" not in ev.texto and "p{}" not in ev.texto
    assert "Adjuntos: contrato.pdf" in ev.texto and ev.adjuntos == ["contrato.pdf"]


def test_una_respuesta_no_trae_otra_vez_el_hilo_citado():
    texto = "Sí, el viernes está bien.\n\nEl jue, 23 oct 2026 a las 9:00, Yo <dueno@hub.local> escribió:\n> ¿Te va el viernes?\n> Gracias"
    ev, _ = correo.evento(_correo(texto=texto).as_bytes(), "3", "INBOX", set())
    assert "Sí, el viernes está bien." in ev.texto and "¿Te va el viernes?" not in ev.texto


def test_sin_cuenta_lo_dice_y_como_crearla(tmp_path, monkeypatch):
    monkeypatch.setenv("HUB_SECRETARIO_CORREO", str(tmp_path / "nada"))
    assert "correo-entrar" in correo.FUENTE.disponible()


def test_saber_si_hay_cuenta_no_abre_la_llave(tmp_path, monkeypatch):
    """`disponible` lo pinta también `hub-web` en /secretario, y la web no abre
    las llaves de las fuentes (decisión 298): sólo mira que el archivo existe,
    como Telegram. Leía `cuenta.env`, con la contraseña, en cada visita (C-0183)."""
    monkeypatch.setenv("HUB_SECRETARIO_CORREO", str(tmp_path))
    (tmp_path / "cuenta.env").write_text("IMAP_SERVIDOR=imap.ejemplo.org\n", encoding="utf-8")

    def no_la_abras(*a, **k):
        raise AssertionError("disponible() abrió cuenta.env")
    monkeypatch.setattr(correo, "cuenta", no_la_abras)
    leer = Path.read_text
    monkeypatch.setattr(Path, "read_text",
                        lambda self, *a, **k: no_la_abras() if self.name == "cuenta.env" else leer(self, *a, **k))
    assert correo.FUENTE.disponible() is None


def test_una_cuenta_a_medias_lo_dice_al_leer_con_lo_que_falta(tmp_path, monkeypatch):
    monkeypatch.setenv("HUB_SECRETARIO_CORREO", str(tmp_path))
    (tmp_path / "cuenta.env").write_text("IMAP_SERVIDOR=imap.ejemplo.org\nIMAP_USUARIO=yo\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="IMAP_CLAVE"):
        correo.FUENTE.leer("", {})


def test_imap_sin_cifrar_solo_contra_la_propia_maquina():
    with pytest.raises(RuntimeError, match="127.0.0.1"):
        correo.conectar({"IMAP_SERVIDOR": "imap.ejemplo.org", "IMAP_USUARIO": "x", "IMAP_CLAVE": "y",
                         "IMAP_SEGURIDAD": "ninguna"})


# ── contra un servidor IMAP de verdad ────────────────────────────────────────

IMAP = os.environ.get("HUB_PRUEBA_IMAP", "127.0.0.1:3143")


def _hay_servidor() -> bool:
    host, puerto = IMAP.split(":")
    try:
        socket.create_connection((host, int(puerto)), timeout=1).close()
        return True
    except OSError:
        return False


imap_real = pytest.mark.skipif(not _hay_servidor(), reason=f"sin servidor IMAP de prueba en {IMAP} (GreenMail)")


@pytest.fixture
def buzon(tmp_path, monkeypatch):
    """Un usuario nuevo en el servidor de prueba, con su `cuenta.env`."""
    usuario = f"u{uuid.uuid4().hex[:8]}@hub.local"
    host, puerto = IMAP.split(":")
    d = tmp_path / "correo"
    d.mkdir()
    (d / "cuenta.env").write_text(f"IMAP_SERVIDOR={host}\nIMAP_PUERTO={puerto}\nIMAP_USUARIO={usuario}\n"
                                  f"IMAP_CLAVE={usuario}\nIMAP_SEGURIDAD=ninguna\n", encoding="utf-8")
    monkeypatch.setenv("HUB_SECRETARIO_CORREO", str(d))

    def mandar(m: EmailMessage):
        del m["To"]
        m["To"] = usuario
        with smtplib.SMTP(host, 3025, timeout=5) as s:
            s.send_message(m)

    # GreenMail crea el usuario al primer correo que recibe.
    return {"usuario": usuario, "mandar": mandar, "cuenta": correo.cuenta({})}


@imap_real
def test_lee_lo_nuevo_sin_lo_masivo_y_sin_marcar_nada_como_leido(buzon):
    buzon["mandar"](_correo(asunto="Contrato", texto="¿Lo firmas el lunes?"))
    buzon["mandar"](_correo(de="Boletín <news@tienda.com>", asunto="Ofertas", List_Unsubscribe="<mailto:b@t.com>"))
    eventos, cursor = correo.FUENTE.leer("", {"activa": True})
    assert [e.texto.splitlines()[0] for e in eventos] == ["Asunto: Contrato"]
    # 🔴 Sólo lectura: los dos siguen sin leer en el buzón del dueño.
    m = correo.conectar(buzon["cuenta"])
    m.select("INBOX", readonly=True)
    assert len(m.search(None, "UNSEEN")[1][0].split()) == 2
    m.logout()

    buzon["mandar"](_correo(asunto="Segundo", texto="otra cosa"))
    eventos2, cursor2 = correo.FUENTE.leer(cursor, {"activa": True})
    assert [e.texto.splitlines()[0] for e in eventos2] == ["Asunto: Segundo"], "sólo lo nuevo desde el cursor"
    assert correo.FUENTE.leer(cursor2, {"activa": True})[0] == []
    assert json.loads(cursor2)["INBOX"]["uid"] == 3


@imap_real
def test_solo_estas_por_fragmento_tambien_deja_pasar_un_boletin_pedido(buzon):
    buzon["mandar"](_correo(de="GitHub <noreply@github.com>", asunto="PR #12", List_Id="<repo.github.com>"))
    buzon["mandar"](_correo(asunto="De Ana"))
    eventos, _ = correo.FUENTE.leer("", {"activa": True, "incluir": ["github.com"]})
    assert [e.texto.splitlines()[0] for e in eventos] == ["Asunto: PR #12"]


@imap_real
def test_menos_estas_quita_por_fragmento(buzon):
    buzon["mandar"](_correo(asunto="De Ana"))
    buzon["mandar"](_correo(de="Jefe <jefe@trabajo.com>", asunto="Del jefe"))
    eventos, _ = correo.FUENTE.leer("", {"activa": True, "excluir": ["ejemplo.org"]})
    assert [e.texto.splitlines()[0] for e in eventos] == ["Asunto: Del jefe"]
