"""Una sesión que trabaja con el título en reposo (C-0222, decisión 393).

Con una herramienta larga, Claude Code deja el título en ✳ —reposo— mientras
la pantalla dice que trabaja. Medido el 22-sep y otra vez el 9-nov: el dueño
tenía una sesión «Embellishing… (7m 6s)» y los talleres la enseñaban dormida.
Las pantallas de aquí son capturas reales, recortadas.
"""
from __future__ import annotations

import pytest

from hub import api, db, snapshotter, tmux
from hub.models import Proyecto
from hub.registry import Atribuidor

REGLA = "─" * 60

# Un panel real el 9-nov, con el título en «✳ …» todo el rato.
TRABAJANDO = "\n".join([
    "✢ Embellishing… (7m 6s · ↓ 33.1k tokens)",
    "  ⎿  Tip: Use /btw to ask a quick side question without interrupting Claude's current work",
    "",
    REGLA,
    "❯ ",
    REGLA,
    "  [Opus 5.5] │ hub git:(main*)",
    "  ⏵⏵ bypass permissions on (shift+tab to cycle) · ← for agents",
])

# Un Claude en modo manual pidiendo permiso para escribir, medido el 9-nov en
# un tmux aparte: no queda línea «…(Ns» y el título sigue en ✳.
PERMISO = "\n".join([
    "❯ Crea con la herramienta Write el archivo nota.txt con el texto hola. Nada más.",
    "● Write(nota.txt)",
    REGLA,
    " Create file",
    " nota.txt",
    "╌" * 60,
    "  1 hola",
    "╌" * 60,
    " Do you want to create nota.txt?",
    " ❯ 1. Yes",
    "   2. Yes, and allow Claude to edit files in its ~/.claude folder for this session",
    "   3. No",
    "",
    " Esc to cancel · Tab to amend",
])

# Codex trabajando, como lo midió `tui` el 12-sep.
CODEX = "• Working (18s • esc to interrupt)\n\n› Ask Codex to do anything\n"


@pytest.fixture
def atribuidor(con):
    con.execute("INSERT INTO proyecto (id, nombre, asiento) VALUES ('demo','Demo','/tmp/demo')")
    return Atribuidor([Proyecto(id="demo", nombre="Demo", asiento="/tmp/demo")])


def _muestrear(con, atribuidor, monkeypatch, comando, titulo, pantalla):
    capturas = []

    def capturar(pane_id, *a, **k):
        capturas.append(pane_id)
        return pantalla

    monkeypatch.setattr(tmux, "servidor_pid", lambda: 100)
    monkeypatch.setattr(tmux, "rama_git", lambda cwd: None)
    monkeypatch.setattr(tmux, "listar_paneles", lambda: [{
        "session": "demo", "window_idx": 0, "pane_idx": 0, "pane_id": "%7",
        "cwd": "/tmp/demo", "titulo": titulo, "comando": comando, "activo": True}])
    monkeypatch.setattr(tmux, "titulo_panel", lambda pane_id: titulo)
    monkeypatch.setattr(tmux, "capturar_panel", capturar)
    snapshotter.capturar(con, atribuidor)
    (panel,) = api.paneles_abiertos(con)
    return panel, capturas


def _taller(con):
    (taller,) = api.talleres(con)["talleres"]
    return taller


def test_claude_con_el_titulo_en_reposo_y_la_pantalla_trabajando_es_un_taller_que_trabaja(
        con, atribuidor, monkeypatch):
    panel, _ = _muestrear(con, atribuidor, monkeypatch, "claude", "✳ Interfaz", TRABAJANDO)

    assert panel["ocupado"] == 1
    assert api.estado_de_panel(panel) == "trabajando"
    assert _taller(con)["estado"] == "trabajando"


def test_una_shell_con_la_pantalla_de_claude_no_se_lee_ni_trabaja(con, atribuidor, monkeypatch):
    """Lo que restaura tmux-resurrect: `bash` con el título y la pantalla de antes (261)."""
    panel, capturas = _muestrear(con, atribuidor, monkeypatch, "bash", "✳ Interfaz", TRABAJANDO)

    assert panel["ocupado"] == 0 and capturas == []
    assert api.estado_de_panel(panel) == "detenido"


def test_con_el_cuadro_de_permiso_abierto_no_trabaja_y_sigue_pidiendo_atencion(
        con, atribuidor, monkeypatch):
    """Si contara como «trabajando», el relé no miraría el permiso: sólo lo
    busca en un panel quieto. Lo medido es que el panel queda «detenido»; que
    ese cuadro concreto («Do you want to create…») salga como «preguntando» es
    otra cosa, y hoy no sale (C-0223)."""
    panel, _ = _muestrear(con, atribuidor, monkeypatch, "claude", "✳ Hub", PERMISO)

    assert panel["ocupado"] == 0
    assert api.estado_de_panel(panel) == "detenido"


def test_codex_trabajando_lo_dice_su_pantalla_y_en_reposo_sigue_neutro(con, atribuidor, monkeypatch):
    _muestrear(con, atribuidor, monkeypatch, "codex", "codex", CODEX)
    assert _taller(con)["estado"] == "trabajando"

    _muestrear(con, atribuidor, monkeypatch, "codex", "codex", "› Ask Codex to do anything\n")
    assert _taller(con)["estado"] == "neutro"


def test_un_panel_que_no_se_deja_leer_no_tumba_la_muestra(con, atribuidor, monkeypatch, capsys):
    def revienta(*a, **k):
        raise RuntimeError("tmux se fue")

    monkeypatch.setattr(snapshotter.tui, "ocupado", revienta)
    panel, _ = _muestrear(con, atribuidor, monkeypatch, "claude", "✳ Interfaz", TRABAJANDO)

    assert panel["ocupado"] == 0
    assert "no se pudo leer si %7 trabaja" in capsys.readouterr().out


def test_el_titulo_que_gira_sigue_bastando():
    assert api.estado_de_panel({"titulo": "⠂ Tarea", "ocupado": 0}) == "trabajando"
    assert api.estado_de_panel({"titulo": "✳ Tarea"}) == "detenido"


def test_una_base_nueva_crea_la_columna_sola(tmp_path):
    con = db.conectar(tmp_path / "nueva.db")
    db.inicializar(con)
    columnas = {f["name"] for f in con.execute("PRAGMA table_info(panel)")}
    assert "ocupado" in columnas


def test_si_el_titulo_ya_gira_no_se_vuelve_a_leer_el_panel(con, atribuidor, monkeypatch):
    """Regla dura 14: la lista de paneles ya trae el título."""
    def no_debia(*a, **k):
        raise AssertionError("no hacía falta leer el panel")

    monkeypatch.setattr(snapshotter.tui, "ocupado", no_debia)
    panel, capturas = _muestrear(con, atribuidor, monkeypatch, "claude", "⠂ Tarea", "")
    assert panel["ocupado"] == 1 and capturas == []


def test_la_muestra_nueva_no_se_ve_a_medias_mientras_se_leen_las_pantallas(
        con, atribuidor, monkeypatch):
    """Las pantallas se leen antes de escribir la muestra: si no, quien lee en
    ese hueco ve la muestra nueva sin paneles (revisor de C-0222)."""
    vistos = []

    def ocupado(agente, pane_id):
        vistos.append(len(api.paneles_abiertos(con)))
        return False

    _muestrear(con, atribuidor, monkeypatch, "claude", "✳ Primera", "")
    monkeypatch.setattr(snapshotter.tui, "ocupado", ocupado)
    _muestrear(con, atribuidor, monkeypatch, "claude", "✳ Segunda", "")
    assert vistos == [1]   # la muestra anterior, entera
