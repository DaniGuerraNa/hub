"""La línea de `claude` que el hub lanza en tmux la arma una sola puerta (decisión 340, C-0042).

Ocho sitios la armaban cada uno a su manera. Estos tests fijan qué hace la
puerta y vigilan que nadie vuelva a escribir las banderas por su cuenta.
"""

from __future__ import annotations

import re
import shlex
from pathlib import Path

import pytest

from hub import agentes, modelos, restauracion, tmux

SRC = Path(__file__).resolve().parents[1] / "src" / "hub"
U = "0b1c2d3e-4f50-6172-8394-a5b6c7d8e9f0"


def test_el_orden_es_fijo_y_el_prompt_va_el_ultimo_entrecomillado_una_vez():
    l = modelos.linea_claude("opus", esfuerzo="high", permisos="dontAsk", reanudar=U, prompt="haz 'x'")
    assert shlex.split(l.comando) == ["claude", "--model", "claude-opus-5-5", "--effort", "high",
                                      "--permission-mode", "dontAsk", "--resume", U, "haz 'x'"]
    assert l.entorno == {}


def test_heredar_no_pone_model_y_es_la_unica_forma_de_usar_otro_programa():
    assert modelos.linea_claude(modelos.HEREDA).comando == "claude"
    assert modelos.linea_claude(modelos.HEREDA, programa="claude --x", reanudar=U).comando == f"claude --x --resume {U}"
    with pytest.raises(ValueError, match="hereda"):
        modelos.linea_claude("sonnet", programa="otro")


@pytest.mark.parametrize("malo", [
    {"modelo": "fable"}, {"esfuerzo": "ultra"}, {"permisos": "yolo"}, {"reanudar": "s-1; rm -rf ~"},
])
def test_rechaza_lo_que_no_vale_antes_de_llegar_a_una_terminal(malo):
    modelo = malo.pop("modelo", "sonnet")
    with pytest.raises(ValueError):
        modelos.linea_claude(modelo, **malo)


def test_compactar_va_en_el_entorno_y_completa_lo_deja_en_un_solo_env():
    l = modelos.linea_claude("opus", compactar=True)
    assert l.entorno == {"CLAUDE_AUTOCOMPACT_PCT_OVERRIDE": "70"}
    assert l.completa() == "env CLAUDE_AUTOCOMPACT_PCT_OVERRIDE=70 claude --model claude-opus-5-5"


def test_el_agente_del_hub_no_admite_dos_modos_de_permiso():
    """Antes salía `--permission-mode dontAsk --permission-mode bypassPermissions`."""
    with pytest.raises(ValueError):
        agentes.comando("haz", sin_preguntar=True, modo="dontAsk")


def test_restaurar_sigue_dejando_escrito_lo_mismo():
    """Es el texto que queda en la ventana sin Enter (decisión 164)."""
    assert restauracion.comando_claude(U, "reanudar") == f"claude --resume {U}"
    assert restauracion.comando_claude("x; rm", "reanudar") == "claude"
    assert restauracion.comando_claude(U, "nuevo") == "claude"
    assert restauracion.comando_claude(U, "nada") == ""


def test_ninguna_linea_lanzada_lleva_dos_env_ni_encadena_comandos():
    """Un solo comando simple: `sh -c` hace `exec` y `claude` queda como proceso
    raíz del panel, que es de lo que dependen `tui.detectar` y `ajustar`."""
    l = modelos.linea_claude("opus", permisos="dontAsk", prompt="a; b && c | d", compactar=True)
    final = tmux.con_entorno(l.comando, {"PATH": "/usr/bin", **l.entorno})
    partes = shlex.split(final)
    assert final.count("env ") == 1 and partes[0] == "env"
    assert partes[-1] == "a; b && c | d"          # el prompt entero es UN argumento
    assert not any(p in (";", "&&", "|", "&") for p in partes)


# Banderas de `claude` dentro de un literal de texto, o la bandera del modelo
# armada a mano. Leerlas (`x == "--model"`, `"--resume" in comando`,
# `.startswith(...)`) está bien: es mirar lo que corre, no lanzar nada.
_BANDERA = re.compile(r"""(["'])[^"'\n]*(--permission-mode|--resume\b|--effort|--model\b|--continue\b"""
                      r"""|--dangerously-skip-permissions|CLAUDE_AUTOCOMPACT_PCT_OVERRIDE=)|modelos\.bandera\(""")
_LEE = re.compile(r"""==|["']\s+in\s|\.startswith\(""")


def test_solo_modelos_arma_la_linea_de_claude():
    assert SRC.is_dir()
    fuera = []
    for archivo in SRC.rglob("*.py"):
        rel = str(archivo.relative_to(SRC))
        if rel in ("modelos.py", "secretario/motor.py"):   # el motor es `claude -p` (301, 328)
            continue
        for n, linea in enumerate(archivo.read_text(encoding="utf-8").splitlines(), 1):
            if linea.lstrip().startswith("#"):
                continue
            if _BANDERA.search(linea) and not _LEE.search(linea):
                fuera.append(f"{rel}:{n}: {linea.strip()}")
    assert not fuera, "banderas de `claude` armadas fuera de `modelos.linea_claude`:\n  " + "\n  ".join(fuera)
