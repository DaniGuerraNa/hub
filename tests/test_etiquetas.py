"""La etiqueta es lo que hace legible la pantalla de recuperación.

Claude Code ya escribe en pane_title una descripción viva de la sesión; para
shells sueltas hay que componerla.
"""

from __future__ import annotations

import socket

from hub import tmux


def test_quita_el_glifo_de_estado_de_claude_code():
    assert tmux.limpiar_titulo("⠂ Continuar con los pendientes") == "Continuar con los pendientes"
    assert tmux.limpiar_titulo("✳ Debugar lambda de notificaciones con SQS") == (
        "Debugar lambda de notificaciones con SQS"
    )


def test_conserva_acentos_y_signos_de_apertura():
    assert tmux.limpiar_titulo("⠋ ¿Por qué falla el gate?") == "¿Por qué falla el gate?"
    assert tmux.limpiar_titulo("Diseñar índice") == "Diseñar índice"


def test_usa_el_titulo_de_claude_cuando_existe():
    etiqueta = tmux.inferir_etiqueta("⠂ Retomar el motor fiscal", "/tmp/x", "claude")
    assert etiqueta == "Retomar el motor fiscal"


def test_el_hostname_no_cuenta_como_titulo(monkeypatch, tmp_path):
    """tmux pone el hostname por defecto; eso no es una etiqueta."""
    monkeypatch.setattr(tmux, "rama_git", lambda cwd: None)
    carpeta = tmp_path / "mi-proyecto"
    carpeta.mkdir()
    # "DESKTOP" y no `socket.gethostname()`: el conftest fija ese hostname.
    etiqueta = tmux.inferir_etiqueta("DESKTOP", str(carpeta), "bash")
    assert etiqueta == "mi-proyecto"


def test_compone_con_comando_y_rama_para_shells(monkeypatch, tmp_path):
    monkeypatch.setattr(tmux, "rama_git", lambda cwd: "feat/mfa")
    carpeta = tmp_path / "api"
    carpeta.mkdir()
    etiqueta = tmux.inferir_etiqueta("", str(carpeta), "uvicorn")
    assert etiqueta == "api · uvicorn · feat/mfa"


def test_no_repite_el_nombre_de_la_shell(monkeypatch, tmp_path):
    monkeypatch.setattr(tmux, "rama_git", lambda cwd: None)
    carpeta = tmp_path / "api"
    carpeta.mkdir()
    assert tmux.inferir_etiqueta("", str(carpeta), "bash") == "api"
