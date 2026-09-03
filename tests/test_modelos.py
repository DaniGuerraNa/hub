"""Que nada que arranque el hub elija modelo por su cuenta.

El fallo que trajo esto: `agentes.comando()` construía `claude` a secas, así que
la ventana heredaba el `"model"` de `~/.claude/settings.json` —un ajuste del
usuario, para SUS ventanas—. Con `"model": "fable"` ahí, medido el 2026-09-03,
`claude -p` respondía `claude-fable-5-1`, y el agente que iba a sembrar la capa
base murió antes de empezar: «There's an issue with the selected model (fable)».

Dos formas de comprobarlo, y hacen falta las dos:
- **De comportamiento**: los comandos que el hub construye llevan `--model`.
- **De lint**: ningún archivo de `src/` arranca `claude` sin pasar por
  `modelos.bandera()`. Sin esto, el siguiente sitio que lance un agente vuelve a
  nacer sin modelo y nadie se entera hasta que falla en una ventana que nadie
  mira.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from hub import agentes, asistente, modelos

RAIZ = Path(__file__).resolve().parents[1]
SRC = RAIZ / "src" / "hub"

# Los alias son la trampa: `fable`, `sonnet` u `opus` resuelven a lo que toque
# ese día. El fallo lo dio un alias, y la decisión 91 ya lo había dicho.
ALIAS = {"fable", "sonnet", "opus", "haiku"}


def test_el_techo_es_sonnet() -> None:
    """Decisión suya: *«nada del hub debería usar más de sonnet»*."""
    assert modelos.AGENTE in modelos.PERMITIDOS
    assert modelos.ASISTENTE in modelos.PERMITIDOS
    prohibidos = {m for m in modelos.PERMITIDOS if "opus" in m or "fable" in m}
    assert not prohibidos, f"por encima del techo acordado: {prohibidos}"


def test_ningun_modelo_es_un_alias() -> None:
    for modelo in {modelos.AGENTE, modelos.ASISTENTE} | set(modelos.PERMITIDOS):
        assert modelo not in ALIAS, (
            f"«{modelo}» es un alias y resuelve a lo que toque ese día;"
            " va el id exacto (decisión 91)"
        )


def test_un_modelo_fuera_de_la_politica_no_arranca() -> None:
    """Da igual que llegue cableado o por parámetro: muere en el mismo sitio."""
    with pytest.raises(ValueError, match="fable"):
        modelos.bandera("claude-fable-5-1")


def test_el_agente_lanzado_por_el_hub_lleva_su_modelo() -> None:
    for sin_preguntar in (False, True):
        comando = agentes.comando("haz algo", sin_preguntar=sin_preguntar)
        assert f"--model {modelos.AGENTE}" in comando, comando
        # Y va antes del prompt, que es el argumento posicional: un `--model`
        # detrás del prompt sería una palabra más del prompt.
        assert comando.index("--model") < comando.index("haz algo")


def test_el_asistente_lleva_su_modelo() -> None:
    assert f"--model {modelos.ASISTENTE}" in asistente.comando_de_arranque(None)


def test_el_asistente_no_duplica_la_politica() -> None:
    """Un techo escrito en dos sitios se separa solo."""
    assert asistente.MODELO is modelos.ASISTENTE


def test_nadie_en_src_arranca_claude_sin_modelo() -> None:
    """El lint: `claude` como comando, en un literal, sin `--model` al lado."""
    # `claude` al principio de un literal de shell, o justo tras `env …`. No
    # busca la palabra suelta: `.claude/` y `pane_current_command == "claude"`
    # aparecen por todo el módulo y no arrancan nada.
    arranque = re.compile(r"""["'](?:env [^"']*)?claude(?: |["'])""")
    sospechosos: list[str] = []
    for archivo in sorted(SRC.rglob("*.py")):
        lineas = archivo.read_text(encoding="utf-8").splitlines()
        for n, linea in enumerate(lineas, 1):
            if not arranque.search(linea):
                continue
            if "--model" in linea or "modelos.bandera" in linea:
                continue
            # `panel["comando"] == "claude"` mira lo que ya corre; no arranca nada.
            if "==" in linea:
                continue
            # La excepción declarada, en el renglón o justo encima —que es donde
            # cae un comentario—. Es lo que la separa de un descuido: se ve con
            # un `grep -rn "modelo: hereda" src/`, y es una lista corta.
            if "modelo: hereda" in linea or "modelo: hereda" in lineas[n - 2]:
                continue
            sospechosos.append(f"{archivo.relative_to(RAIZ)}:{n}: {linea.strip()}")
    assert not sospechosos, (
        "Esto arranca `claude` sin decir con qué modelo, así que hereda el"
        " `\"model\"` de ~/.claude/settings.json:\n  "
        + "\n  ".join(sospechosos)
        + "\n\nUsa `modelos.bandera(modelos.AGENTE)`. Si de verdad tiene que"
        " heredarlo —una ventana de trabajo suya, no un agente del hub—, dilo"
        " en el mismo renglón con un comentario y añádelo aquí."
    )
