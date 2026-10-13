"""Saber si Claude Code está trabajando, cuando el título no lo dice.

Medido el 2026-09-22 con Claude Code 2.1.280: el título se quedó en `✳`
(reposo) los cien segundos que una sesión estuvo ejecutando un comando, y el
orquestador daba por acabada la orden a los 45 s. La pantalla sí lo decía.
Estas capturas son de aquel panel, recortadas.
"""

from __future__ import annotations

import pytest

from hub import asistente

REGLA = "─" * 60

TRABAJANDO = f"""\
● Voy a ejecutarlo.
  ⎿  $ python3 -c 'import time; time.sleep(100)' (1m 12s)
✻ Boondoggling… (1m 15s · ↓ 136 tokens)
  ⎿  Tip: Use /permissions to pre-approve and pre-deny bash, edit, and MCP tools

{REGLA}
❯ 
{REGLA}
  [Opus 5.5] │ ensayo │ ⏱️  9m
"""

ACABADO = f"""\
● Listo: 4 líneas.
✻ Worked for 5s · done 2:56 PM

{REGLA}
❯ 
{REGLA}
  [Opus 5.5] │ ensayo │ ⏱️  9m
"""

# El «…(3s» está en el historial, no justo encima del cuadro: no es de ahora.
EN_EL_HISTORIAL = f"""\
✻ Pondering… (3s · ↓ 10 tokens)
● Una respuesta larga.
● Otra más.
● Y otra.
● Y la última.
● Hecho.
✻ Cogitated for 10s · done 3:01 PM

{REGLA}
❯ 
{REGLA}
"""


@pytest.mark.parametrize("pantalla, esperado", [
    (TRABAJANDO, True),
    (ACABADO, False),
    (EN_EL_HISTORIAL, False),
    ("sin cuadro de entrada", False),
])
def test_la_linea_de_estado_dice_si_trabaja(pantalla, esperado, monkeypatch):
    monkeypatch.setattr(asistente.tmux, "capturar_panel", lambda pane_id: pantalla)

    assert asistente.trabajando_en_pantalla("%1") is esperado


def test_con_el_titulo_en_reposo_la_pantalla_manda(monkeypatch):
    """La señal nueva sólo suma casos de «trabajando», nunca los quita."""
    monkeypatch.setattr(asistente.tmux, "titulo_panel", lambda pane_id: "✳ README")
    monkeypatch.setattr(asistente.tmux, "capturar_panel", lambda pane_id: TRABAJANDO)

    assert asistente.ocupado("%1") is True
