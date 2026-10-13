"""Que una regla de móvil no quede anulada por otra escrita después.

🔴 Ha mordido **cuatro veces** y siempre igual de callada, porque el síntoma
nunca es un error: la pantalla se pinta, se ve entera y sana, y lo que falla es
invisible.

    decisión 202  `.por-ventana.viendo` vs `[hidden]` — el panel decía «esta
                  ventana no tiene slot» teniéndolo, y tres arneses daban verde
    decisión 207  `body.completo` (0,1,1) le ganaba a `body` (0,0,1) dentro del
                  `@media`: 332 px cortados en el móvil y la pestaña «Nota»
                  inalcanzable, con la página aparentemente perfecta
    decisión 208  `#ir-a { display:none }` escrito DESPUÉS del `@media`, misma
                  especificidad, ganaba la última: el `select` de móvil no
                  aparecía tampoco en el móvil

El patrón común: **dos reglas para lo mismo, y la que manda no es la que
parece**. Este lint cubre el caso que se puede comprobar sin implementar el
modelo de cascada entero — el mismo selector, la misma propiedad, una dentro del
`@media` y otra fuera y después.
"""

from __future__ import annotations

import re
from pathlib import Path

PLANTILLAS = Path(__file__).resolve().parents[1] / "src" / "hub" / "templates"

# Las que deciden si algo se ve y cuánto ocupa. Un color repetido no hace daño.
PROPIEDADES = ("display", "overflow", "height", "width", "max-height", "position")


def _bloques_media(css: str) -> list[tuple[int, int]]:
    """Los `@media`, con sus llaves emparejadas de verdad.

    Con una expresión regular hasta el primer `}` se corta en la primera regla
    de dentro, y entonces el lint mira el sitio equivocado.
    """
    bloques = []
    for m in re.finditer(r"@media[^{]*\{", css):
        i, nivel = m.end(), 1
        while i < len(css) and nivel:
            nivel += (css[i] == "{") - (css[i] == "}")
            i += 1
        bloques.append((m.start(), i))
    return bloques


def _reglas(css: str, desde: int = 0) -> list[tuple[str, str, int]]:
    """(selector, cuerpo, posición) de cada regla simple."""
    return [(m.group(1).strip(), m.group(2), desde + m.start())
            for m in re.finditer(r"([^{}@]+)\{([^{}]*)\}", css)]


def _propiedades(cuerpo: str) -> set[str]:
    return {p for p in PROPIEDADES
            if re.search(rf"(^|[;{{\s]){re.escape(p)}\s*:", cuerpo)}


def _analizar(css: str) -> list[str]:
    """Las reglas de `@media` que una regla posterior deja sin efecto.

    Se escanea el CSS **original una sola vez**: el patrón de regla simple no
    casa con `@media …{` porque lleva `@`, así que las de dentro salen con su
    posición verdadera y no hay que recomponer nada. La primera versión sí
    recomponía, y se equivocaba tanto que no detectaba ni el caso que la motivó
    — de ahí el segundo test de este archivo.
    """
    medias = _bloques_media(css)

    def dentro_de(pos: int) -> tuple[int, int] | None:
        return next(((i, f) for i, f in medias if i <= pos < f), None)

    reglas = _reglas(css)
    quejas = []
    for sel, cuerpo, pos in reglas:
        bloque = dentro_de(pos)
        if bloque is None:
            continue
        props = _propiedades(cuerpo)
        if not props:
            continue
        for sel2, cuerpo2, pos2 in reglas:
            if dentro_de(pos2) is not None or sel2.strip() != sel.strip():
                continue
            chocan = props & _propiedades(cuerpo2)
            # Después del @media ENTERO: una regla anterior sí queda pisada por
            # la de dentro, que es lo correcto y no hay nada que avisar.
            # Y mayor-o-IGUAL: el escaneo empieza la regla de fuera justo en la
            # llave que cierra el @media, así que un "mayor" a secas se dejaba
            # fuera el caso exacto — el lint no veía ni el fallo que lo motivó.
            if chocan and pos2 >= bloque[1]:
                quejas.append(
                    f"«{sel.strip()}» fija {sorted(chocan)} dentro de un @media y "
                    f"la misma regla vuelve a fijarlo DESPUÉS: gana la de fuera, "
                    f"así que en el móvil no se aplica nunca."
                )
    return quejas


def test_ninguna_regla_de_movil_queda_anulada_por_una_posterior():
    problemas = {}
    for plantilla in sorted(PLANTILLAS.glob("*.html")):
        css = " ".join(re.findall(r"<style>(.*?)</style>", plantilla.read_text(), re.S))
        if not css:
            continue
        if quejas := _analizar(css):
            problemas[plantilla.name] = quejas
    assert not problemas, (
        "Reglas de móvil anuladas por la cascada (decisiones 202, 207, 208):\n  "
        + "\n  ".join(f"{a}: {q}" for a, qs in problemas.items() for q in qs)
        + "\n\nMueve la regla de escritorio ANTES del @media, o hazla más específica."
    )


def test_el_lint_detecta_el_caso_que_lo_motivó():
    """🔴 Un lint que nunca ha estado en rojo no se sabe si mira algo.

    Este es el CSS exacto que dejó el `select` de móvil invisible el 16-sep.
    """
    malo = """
      @media (max-width: 720px) { #ir-a { display:block; width:100%; } }
      #ir-a { display:none; }
    """
    assert _analizar(malo), "el lint no vio el fallo que lo motivó"
    bueno = """
      #ir-a { display:none; }
      @media (max-width: 720px) { #ir-a { display:block; width:100%; } }
    """
    assert not _analizar(bueno), "el lint se queja del orden correcto"
