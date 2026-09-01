"""El puente entre el índice y la terminal.

Abrir un slot tiene que llevarte exactamente a donde vive ese trabajo, sin mover
de sitio a quien esté atacado en la terminal nativa.
"""

from __future__ import annotations

import pytest

from hub import api, slots, snapshotter, terminal, tmux
from hub.models import Proyecto
from hub.registry import Atribuidor


@pytest.fixture
def escena(con, monkeypatch):
    con.execute("INSERT INTO proyecto (id, nombre, asiento) VALUES ('demo','Demo','/tmp/demo')")
    monkeypatch.setattr(tmux, "servidor_pid", lambda: 100)
    monkeypatch.setattr(tmux, "rama_git", lambda cwd: None)
    monkeypatch.setattr(
        tmux,
        "listar_paneles",
        lambda *a, **k: [
            {"session": "work", "window_idx": 0, "pane_idx": 0, "pane_id": "%1",
             "cwd": "/tmp/demo", "titulo": "⠂ Back", "comando": "claude", "activo": True},
            {"session": "work", "window_idx": 2, "pane_idx": 0, "pane_id": "%2",
             "cwd": "/tmp/demo", "titulo": "⠂ Front", "comando": "claude", "activo": False},
        ],
    )
    snapshotter.capturar(
        con, Atribuidor([Proyecto(id="demo", nombre="Demo", asiento="/tmp/demo")])
    )
    return con


def test_panel_de_slot_localiza_sesion_y_ventana(escena):
    slot_id = slots.crear(escena, "demo", "front")
    slots.vincular(escena, "%2", slot_id)

    panel = api.panel_de_slot(escena, slot_id)
    assert panel["session"] == "work"
    assert panel["window_idx"] == 2


def test_un_slot_sin_panel_abierto_no_localiza_nada(escena):
    slot_id = slots.crear(escena, "demo", "dormido")
    assert api.panel_de_slot(escena, slot_id) is None


def test_contexto_de_trabajo_resuelve_el_destino_del_slot(escena):
    slot_id = slots.crear(escena, "demo", "front")
    slots.vincular(escena, "%2", slot_id)

    ctx = api.contexto_trabajo(escena, slot_id=slot_id)
    assert ctx["session"] == "work"
    assert ctx["ventana"] == 2
    assert ctx["slot"]["abierto"] is True
    assert ctx["proyectos"][0]["paneles_abiertos"] == 2


def test_contexto_marca_el_slot_cerrado_pero_lo_devuelve(escena):
    slot_id = slots.crear(escena, "demo", "dormido", nota="lo que quedó pendiente")

    ctx = api.contexto_trabajo(escena, slot_id=slot_id)
    assert ctx["slot"]["abierto"] is False
    assert ctx["slot"]["nota"] == "lo que quedó pendiente"
    assert ctx["ventana"] is None


def test_la_nota_se_guarda_y_persiste(escena):
    slot_id = slots.crear(escena, "demo", "back")
    api.guardar_nota(escena, slot_id, "medio arreglado el gate; falta el seed")
    assert api.obtener_slot(escena, slot_id)["nota"] == "medio arreglado el gate; falta el seed"


def test_el_espejo_se_posiciona_en_la_ventana_del_slot(monkeypatch):
    """select-window sobre el espejo, nunca sobre la sesión original."""
    llamadas = []
    monkeypatch.setattr(tmux, "_correr", lambda args: llamadas.append(args) or "")

    nombre = terminal.crear_espejo("work", ventana=2)

    # El "=" fuerza coincidencia exacta de nombre en tmux, sin búsqueda difusa.
    assert ["select-window", "-t", f"={nombre}:2"] in llamadas
    assert not any(a[0] == "select-window" and "work:2" == a[2].lstrip("=") for a in llamadas)


def test_sin_ventana_no_se_toca_la_posicion(monkeypatch):
    llamadas = []
    monkeypatch.setattr(tmux, "_correr", lambda args: llamadas.append(args) or "")
    terminal.crear_espejo("work")
    assert not any(a[0] == "select-window" for a in llamadas)
