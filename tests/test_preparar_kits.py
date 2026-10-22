"""«Aplícale los kits» desde el chat: el hub prepara la ventana y no la lanza.

🔴 21-oct: se lo pidieron al asistente sobre un proyecto recién creado y
contestó que no podía; ni siquiera sabía que «lienzos» y «telegram» eran kits.
Ahora el hub abre una ventana en la carpeta del proyecto con el encargo
escrito y SIN Enter (decisión 287, tercer caso de la regla dura 15). Se prueba
con el tmux aparte de los tests, de verdad.
"""
from __future__ import annotations

import time

import pytest

from hub import agentes, kits, tmux


@pytest.fixture
def proyecto(con, tmp_path, monkeypatch):
    carpeta = tmp_path / "comercio"
    carpeta.mkdir()
    con.execute("INSERT INTO proyecto (id, nombre, asiento, guardrail) VALUES "
                "('comercio','Comercio',?,'ask'), ('quieto','Quieto',?,'never')",
                (str(carpeta), str(carpeta)))
    monkeypatch.setattr(kits, "catalogo", lambda: {
        "base": {"nombre": "Capa base"}, "lienzos": {"nombre": "Lienzos"},
        "telegram": {"nombre": "Telegram"}})
    yield carpeta
    for s in ("comercio", "hub"):
        if tmux.existe_sesion(s):
            tmux._correr(["kill-session", "-t", f"={s}"])


def _pantalla(pane_id: str) -> str:
    for _ in range(30):
        texto = tmux._correr(["capture-pane", "-p", "-J", "-t", pane_id])
        if "aplicar-kit" in texto:
            return texto
        time.sleep(0.1)
    return texto


def test_deja_el_encargo_escrito_en_la_carpeta_del_proyecto_sin_lanzarlo(con, proyecto):
    hecho = agentes.preparar_kits(con, "comercio", ["lienzos", "telegram", "lienzos"])

    assert hecho["kits"] == ["lienzos", "telegram"]
    panel = next(p for p in tmux.listar_paneles()
                 if p["session"] == hecho["session"] and p["window_idx"] == hecho["ventana"])
    assert panel["cwd"] == str(proyecto)
    pantalla = _pantalla(panel["pane_id"])
    assert "`lienzos`, `telegram`" in pantalla
    # Sin Enter: lo que corre es la shell, no claude.
    assert panel["comando"] != "claude"
    assert tmux._correr(["display-message", "-p", "-t", panel["pane_id"],
                         "#{pane_current_command}"]).strip() in ("bash", "zsh", "sh", "fish")


def test_un_kit_que_no_esta_en_el_catalogo_no_abre_nada(con, proyecto):
    with pytest.raises(ValueError, match="orquestador"):
        agentes.preparar_kits(con, "comercio", ["lienzos", "orquestador"])
    assert not tmux.existe_sesion("comercio")


def test_con_guardrail_never_no_se_prepara(con, proyecto):
    with pytest.raises(agentes.GuardrailBloqueado):
        agentes.preparar_kits(con, "quieto", ["lienzos"])
