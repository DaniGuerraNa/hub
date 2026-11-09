"""Leer la pantalla que mira el dueño (C-0162, decisión 356).

El modelo no elige qué panel leer: sólo el del turno que contesta. Lo leído
no se guarda, las llaves se tapan y cada lectura se ve en el chat.
"""

from __future__ import annotations

import json

import pytest

from hub import api, tmux
from hub.secretario import conversacion, herramientas, memoria


@pytest.fixture
def con():
    c = memoria.conectar()
    yield c
    c.close()


@pytest.fixture
def ventana(monkeypatch):
    leidos = []
    monkeypatch.setattr(api, "paneles_abiertos", lambda h: [
        {"session": "hub", "window_idx": 2, "pane_id": "%7", "slot_nombre": "Login", "proyecto_id": "web",
         "cwd": "/w", "comando": "claude", "etiqueta": ""},
        {"session": "otra", "window_idx": 0, "pane_id": "%9", "slot_nombre": "Privado", "proyecto_id": "x",
         "cwd": "/x", "comando": "bash", "etiqueta": ""}])

    def capturar(pane_id, **k):
        leidos.append(pane_id)
        return "Error: 401\nANTHROPIC_API_KEY=sk-ant-api03-abcdefghijklmnopqrstuvwxyz0123456789\n\n\n"
    monkeypatch.setattr(tmux, "capturar_panel", capturar)
    return leidos


def _contestando(con, monkeypatch, enfoque):
    t = conversacion.recibir(con, "¿qué es este error?", enfoque=enfoque)
    rid = conversacion.decir(con, t["hilo"], "…")
    memoria.poner(con, f"turno_en_curso:{t['hilo']}", rid)
    monkeypatch.setenv("SECRETARIO_HILO", str(t["hilo"]))
    return rid


def test_lee_solo_la_ventana_del_turno_tapa_llaves_y_lo_deja_a_la_vista(con, monkeypatch, ventana):
    rid = _contestando(con, monkeypatch, "hub:2")
    r = herramientas.todas()["pantalla_actual"].funcion(con, {"ventana": "otra:0"})   # pedir otra no sirve
    assert ventana == ["%7"] and r["slot"] == "Login"
    assert "Error: 401" in r["pantalla"] and "sk-ant-api03" not in r["pantalla"]
    tarjetas = json.loads(con.execute("SELECT tarjetas FROM turno WHERE id = ?", (rid,)).fetchone()[0])
    assert tarjetas[0]["titulo"] == "Miré tu pantalla"
    assert con.execute("SELECT accion FROM bitacora WHERE accion = 'pantalla_actual'").fetchone()


def test_lo_leido_no_se_guarda_en_la_memoria(con, monkeypatch, ventana):
    _contestando(con, monkeypatch, "hub:2")
    herramientas.todas()["pantalla_actual"].funcion(con, {})
    volcado = "\n".join(con.iterdump())
    assert "Error: 401" not in volcado


def test_sin_ventana_de_trabajo_no_hay_nada_que_mirar(con, monkeypatch, ventana):
    _contestando(con, monkeypatch, "")
    assert "error" in herramientas.todas()["pantalla_actual"].funcion(con, {})
    assert ventana == []


@pytest.mark.parametrize("malo", ["hub", "hub:x", "hub;rm -rf /:1", "../a:1", ":3"])
def test_un_enfoque_con_otra_forma_se_descarta(con, malo):
    t = conversacion.recibir(con, "hola", enfoque=malo)
    assert con.execute("SELECT enfoque FROM turno WHERE id = ?", (t["turno"],)).fetchone()[0] == ""


def test_la_regla_de_cuando_mirar_va_en_el_sistema():
    assert "`pantalla_actual`" in conversacion.SISTEMA and "nunca \\\npor tu cuenta" not in conversacion.SISTEMA
    assert "SÓLO cuando él hable de lo que tiene en pantalla" in conversacion.SISTEMA


def test_una_ventana_que_no_se_pudo_leer_no_cuenta_como_mirada(con, monkeypatch, ventana):
    monkeypatch.setattr(tmux, "capturar_panel", lambda pane_id, **k: "")
    rid = _contestando(con, monkeypatch, "hub:2")
    assert "error" in herramientas.todas()["pantalla_actual"].funcion(con, {})
    assert con.execute("SELECT tarjetas FROM turno WHERE id = ?", (rid,)).fetchone()[0] == "[]"
