"""Resumir una sesión de trabajo larga (C-0163): se encarga y lo hace el servicio."""

from __future__ import annotations

import json

import pytest

from hub import transcripts
from hub.secretario import conversacion, memoria, motor, sesiones


@pytest.fixture
def con():
    c = memoria.conectar()
    yield c
    c.close()


@pytest.fixture
def sesion(tmp_path, monkeypatch):
    sid = "0b9f3c1e-1111-4222-8333-444455556666"
    ruta = tmp_path / f"{sid}.jsonl"
    filas = [{"type": "user", "uuid": "u1", "timestamp": "2026-11-05T09:00:00Z",
              "message": {"role": "user", "content": "migra el login a OAuth"}},
             {"type": "assistant", "uuid": "a1", "timestamp": "2026-11-05T16:40:00Z",
              "message": {"role": "assistant", "content": [{"type": "text", "text": "Hecho, falta el logout."}]}}]
    ruta.write_text("\n".join(json.dumps(f) for f in filas))
    monkeypatch.setattr(transcripts, "_todos_los_directorios", lambda: [tmp_path])
    return sid


def test_se_encarga_y_el_servicio_deja_el_resumen_en_el_hilo(con, sesion, monkeypatch):
    pedidos = []
    monkeypatch.setattr(motor, "llamar", lambda prompt, **kw: pedidos.append((prompt, kw)) or motor.Respuesta(
        texto="Se migró el login; falta el logout.", sesion="s", estructurada=None, segundos=1, coste=0,
        modelo=kw["modelo"]))
    hilo = conversacion.recibir(con, "¿qué se hizo ayer?")["hilo"]
    assert sesiones.encargar(con, sesion, hilo)["encargado"] is True
    assert sesiones.encargar(con, sesion, hilo)["nota"].startswith("Ya la estaba")   # no se encola dos veces
    assert sesiones.atender(con) == 1 and sesiones.atender(con) == 0
    prompt, kw = pedidos[0]
    assert "migra el login a OAuth" in prompt and "Hecho, falta el logout." in prompt
    assert kw["herramientas"] is False and kw["persistir"] is False
    assert conversacion.turnos(con, hilo)[-1]["texto"].endswith("Se migró el login; falta el logout.")


def test_una_sesion_que_no_existe_se_dice_y_no_se_encola(con, sesion):
    assert "error" in sesiones.encargar(con, "no-es-un-id", None)
    assert memoria.leer(con, sesiones.CLAVE) is None


def test_si_algo_falla_al_leerla_se_dice_en_el_hilo_y_no_se_pierde_en_silencio(con, sesion, monkeypatch):
    def rota(ruta, **k):
        raise OSError("disco")
    monkeypatch.setattr(transcripts, "esqueleto", rota)
    hilo = conversacion.recibir(con, "resúmela")["hilo"]
    sesiones.encargar(con, sesion, hilo)
    assert sesiones.atender(con) == 1
    assert "No pude resumir" in conversacion.turnos(con, hilo)[-1]["texto"]


def test_sin_hilo_el_resumen_abre_uno_en_vez_de_perderse(con, sesion, monkeypatch):
    """Antes, sin hilo abierto no se escribía y nadie se enteraba (C-0171)."""
    def rota(ruta, **k):
        raise OSError("disco")
    monkeypatch.setattr(transcripts, "esqueleto", rota)
    sesiones.encargar(con, sesion, None)
    assert sesiones.atender(con) == 1
    h = conversacion.hilo_abierto(con)
    assert "No pude resumir" in conversacion.turnos(con, h["id"])[-1]["texto"]
