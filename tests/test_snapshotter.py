"""Lo que de verdad tiene que aguantar: perder tmux sin previo aviso.

Un cierre abrupto no dispara ningún hook, así que la detección se basa en
comparar el PID del servidor entre muestras.
"""

from __future__ import annotations

import pytest

from hub import api, snapshotter, tmux
from hub.registry import Atribuidor
from hub.models import Proyecto


@pytest.fixture
def atribuidor(con):
    con.execute(
        "INSERT INTO proyecto (id, nombre, asiento) VALUES ('demo','Demo','/tmp/demo')"
    )
    return Atribuidor([Proyecto(id="demo", nombre="Demo", asiento="/tmp/demo")])


def _paneles(n=2, base="%"):
    return [
        {
            "session": "demo",
            "window_idx": i,
            "pane_idx": 0,
            "pane_id": f"{base}{i}",
            "cwd": "/tmp/demo",
            "titulo": f"⠂ Tarea {i}",
            "comando": "claude",
            "activo": i == 0,
        }
        for i in range(n)
    ]


def _falsear(monkeypatch, pid, paneles):
    monkeypatch.setattr(tmux, "servidor_pid", lambda: pid)
    monkeypatch.setattr(tmux, "listar_paneles", lambda: paneles)
    monkeypatch.setattr(tmux, "rama_git", lambda cwd: None)


def test_captura_atribuye_y_limpia_la_etiqueta(con, atribuidor, monkeypatch):
    _falsear(monkeypatch, 100, _paneles(2))
    snapshotter.capturar(con, atribuidor)

    paneles = api.paneles_abiertos(con)
    assert len(paneles) == 2
    assert paneles[0]["proyecto_id"] == "demo"
    assert paneles[0]["etiqueta"] == "Tarea 0"
    assert paneles[0]["comando"] == "claude"


def test_detecta_el_corte_y_preserva_la_ultima_muestra(con, atribuidor, monkeypatch):
    _falsear(monkeypatch, 100, _paneles(3))
    snapshotter.capturar(con, atribuidor)
    snapshotter.capturar(con, atribuidor)

    # WSL se cae y tmux vuelve con otro PID y un solo panel.
    _falsear(monkeypatch, 200, _paneles(1, base="%n"))
    snapshotter.capturar(con, atribuidor)

    perdido = api.recuperacion_pendiente(con)
    assert perdido is not None
    assert len(perdido["paneles"]) == 3, "debe mostrar lo que había ANTES del corte"
    assert perdido["server_pid"] == 100


def test_sin_servidor_no_pisa_la_ultima_muestra_buena(con, atribuidor, monkeypatch):
    _falsear(monkeypatch, 100, _paneles(3))
    snapshotter.capturar(con, atribuidor)

    # tmux muerto: ni PID ni paneles. No debe escribirse un snapshot vacío.
    _falsear(monkeypatch, None, [])
    assert snapshotter.capturar(con, atribuidor) is None

    perdido = api.recuperacion_pendiente(con)
    assert perdido is not None and len(perdido["paneles"]) == 3


def test_marcar_revisada_deja_de_anunciar(con, atribuidor, monkeypatch):
    _falsear(monkeypatch, 100, _paneles(2))
    snapshotter.capturar(con, atribuidor)
    _falsear(monkeypatch, 200, _paneles(1))
    snapshotter.capturar(con, atribuidor)

    perdido = api.recuperacion_pendiente(con)
    api.marcar_recuperacion_revisada(con, perdido["id"])
    assert api.recuperacion_pendiente(con) is None


def test_la_poda_respeta_los_preservados(con, atribuidor, monkeypatch):
    _falsear(monkeypatch, 100, _paneles(2))
    snapshotter.capturar(con, atribuidor)
    _falsear(monkeypatch, 200, _paneles(2))
    for _ in range(12):
        snapshotter.capturar(con, atribuidor)

    snapshotter.podar(con, retencion=3)
    filas = con.execute("SELECT preservado FROM snapshot").fetchall()
    assert sum(1 for f in filas if f["preservado"] == 1) == 1
    assert sum(1 for f in filas if f["preservado"] == 0) == 3


def test_el_binding_sobrevive_entre_muestras(con, atribuidor, monkeypatch):
    from hub import slots

    _falsear(monkeypatch, 100, _paneles(1))
    snapshotter.capturar(con, atribuidor)
    slot_id = slots.crear(con, "demo", "back", ruta="/tmp/demo")
    slots.vincular(con, "%0", slot_id)

    snapshotter.capturar(con, atribuidor)
    panel = api.paneles_abiertos(con)[0]
    assert panel["slot_id"] == slot_id
    assert panel["slot_nombre"] == "back"

    # Y registra actividad en el slot, que es dato para ordenar, no gestión.
    assert api.obtener_slot(con, slot_id)["ultima_actividad"] is not None


def test_el_ciclo_barre_espejos_huerfanos(con, atribuidor, monkeypatch):
    """Si el navegador muere sin avisar, el espejo queda: el latido lo limpia."""
    from hub import registry, terminal

    barridos = []
    monkeypatch.setattr(registry, "cargar", lambda *a, **k: [])
    monkeypatch.setattr(terminal, "limpiar_espejos_huerfanos",
                        lambda *a, **k: barridos.append(True) or [])
    _falsear(monkeypatch, 100, _paneles(1))

    snapshotter.un_ciclo(con)
    assert barridos == [True]


def test_un_barrido_fallido_no_tumba_el_ciclo(con, atribuidor, monkeypatch):
    """El snapshotter existe para funcionar el día que todo lo demás falla."""
    from hub import registry, terminal

    monkeypatch.setattr(registry, "cargar", lambda *a, **k: [])
    monkeypatch.setattr(terminal, "limpiar_espejos_huerfanos",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("tmux caído")))
    _falsear(monkeypatch, 100, _paneles(2))

    assert snapshotter.un_ciclo(con) is not None
