"""Que el dedo pueda recorrer el historial de la terminal.

🔴 Dos invariantes que no se ven leyendo el código y que se midieron el
2026-09-16 en Chrome, con el modo de ratón activo de verdad:

1. **`touch-action: none`** en la terminal. `.xterm-viewport` lleva
   `overflow-y: scroll`, así que sin esto el NAVEGADOR reclama el arrastre como
   scroll nativo, xterm devuelve el viewport al fondo y el `preventDefault` del
   manejador llega tarde — el gesto ya no es suyo. Síntoma medido: nada se
   mueve, y nada falla por ninguna parte.

2. **El evento va a `.xterm`**, no a `#marco`. Medido: `.xterm`,
   `.xterm-viewport` y `.xterm-screen` producen los tres `ESC[<64;1;1M`;
   `#marco` no produce nada, porque el manejador de xterm vive DENTRO y un
   evento no burbujea hacia abajo. La primera versión apuntaba a un hermano y
   por eso «no puedo scrollear aún».

No se prueba ejecutándolo porque el gesto táctil necesita un navegador de
verdad, y esto tiene que correr en cualquier máquina (el repo se publica). Lo
que se protege es que nadie deshaga las dos cosas sin enterarse.
"""

from __future__ import annotations

import re
from pathlib import Path

TRABAJO = Path(__file__).resolve().parents[1] / "src" / "hub" / "templates" / "trabajo.html"


def _fuente() -> str:
    return TRABAJO.read_text(encoding="utf-8")


def test_la_terminal_no_le_cede_el_gesto_al_navegador():
    css = " ".join(re.findall(r"<style>(.*?)</style>", _fuente(), re.S))
    regla = re.search(r"([^{}]*\.xterm-viewport[^{}]*)\{([^{}]*touch-action\s*:\s*none[^{}]*)\}", css)
    assert regla, (
        "falta `touch-action: none` sobre `.xterm-viewport`: el navegador se "
        "quedará el arrastre como scroll nativo y el dedo dejará de servir"
    )


def test_la_rueda_sintetica_va_a_la_raiz_de_xterm_y_no_al_contenedor():
    guion = _fuente()
    destino = re.search(r"const destino = document\.querySelector\('([^']+)'\)", guion)
    assert destino, "ya no se elige a dónde mandar la rueda"
    assert destino.group(1) == ".xterm", (
        f"la rueda se manda a «{destino.group(1)}». Medido: sólo `.xterm`, "
        "`.xterm-viewport` y `.xterm-screen` la reciben; `#marco` es el padre y "
        "un evento no burbujea hacia abajo"
    )


def test_el_arrastre_se_frena_desde_el_primer_movimiento():
    """Frenar sólo al completar una muesca llega tarde: el gesto ya es del navegador."""
    guion = _fuente()
    cuerpo = guion[guion.index("marcoTerm.addEventListener('touchmove'"):]
    cuerpo = cuerpo[:cuerpo.index("}, { passive: false });")]
    freno = cuerpo.index("e.preventDefault()")
    umbral = cuerpo.index("< PASO_RUEDA")
    assert freno < umbral, (
        "`preventDefault()` se llama DESPUÉS de comprobar el umbral: los "
        "primeros píxeles del arrastre se los queda el navegador y ya no lo suelta"
    )


def test_el_manejador_no_es_pasivo():
    """Un oyente pasivo no puede frenar nada, y el navegador lo sabe de antemano."""
    guion = _fuente()
    ini = guion.index("marcoTerm.addEventListener('touchmove'")
    cuerpo = guion[ini:guion.index("marcoTerm.addEventListener('touchend'", ini)]
    assert "{ passive: false }" in cuerpo, (
        "el `touchmove` es pasivo: el navegador ni siquiera le dejará frenar el gesto"
    )


def test_con_dos_dedos_no_se_toca_el_gesto():
    """El pellizco es del navegador; robárselo sería peor que no tener scroll."""
    assert "e.touches.length !== 1" in _fuente()
