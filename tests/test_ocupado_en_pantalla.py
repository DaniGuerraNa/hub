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


# Medido el 9-nov (C-0222) con Claude Code 2.1.280: una sesión con nombre lo
# pinta en el borde de arriba del cuadro, y con lista de tareas ésta va entre
# la línea de estado y el cuadro. Con las dos cosas, se daba por parada.
CON_NOMBRE_Y_TAREAS = "\n".join([
    "",
    "· Preparando la versión… (53m 38s · ↓ 151.2k tokens)",
    "  ⎿ \xa0✔ C-0214: hub en máquina aparte (4 piezas)",
    "     ◼ Preparar la versión 0.5.0",
    "     ◼ C-0222: talleres y punto de estado",
    "     … +2 pending",
    "",
    "─" * 100 + " Hub remoto con control desde múltiples dispositivos ─",
    "❯\xa0",
    REGLA,
    "  [Opus 5.5] │ hub git:(main)",
])

# Un cuadro de permiso abierto: el `❯` más cercano es un mensaje del
# historial, y encima el turno anterior citaba una línea de estado. No hay
# cuadro de entrada, así que no se lee nada (revisor de C-0222).
PERMISO_TRAS_CITAR_UNA_LINEA_DE_ESTADO = "\n".join([
    "● El panel decía «· Brewing… (1m 3s)» cuando lo miré.",
    "✻ Worked for 4s · done 1:40 PM",
    "❯ Crea el archivo nota.txt con el texto hola.",
    "● Write(nota.txt)",
    REGLA,
    " Create file",
    " Do you want to create nota.txt?",
    " ❯ 1. Yes",
    "   3. No",
])

ACABADO_CON_NOMBRE = CON_NOMBRE_Y_TAREAS.replace(
    "· Preparando la versión… (53m 38s · ↓ 151.2k tokens)", "✻ Brewed for 10m 39s · done 1:42 PM")


@pytest.mark.parametrize("pantalla, esperado", [
    (TRABAJANDO, True),
    (CON_NOMBRE_Y_TAREAS, True),
    (ACABADO_CON_NOMBRE, False),
    (PERMISO_TRAS_CITAR_UNA_LINEA_DE_ESTADO, False),
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
