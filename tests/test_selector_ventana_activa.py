"""El bloque de la ventana activa se busca por `.viendo`, nunca por `[hidden]`.

🔴 Un lint, y existe porque el mismo fallo se coló TRES veces sin que nada lo
dijera.

`trabajo.html` pinta cada `.por-ventana` con el atributo `hidden` y revela la
activa poniéndole la clase `viendo`. **El atributo no se quita nunca**: la regla
`.por-ventana.viendo { display:flex }` gana al `[hidden]` del navegador por
especificidad, así que la pantalla se ve bien y el atributo sigue puesto. Por
eso `.por-ventana:not([hidden])` no casa con ningún bloque, jamás.

Lo que costó: en `lienzos.js` y en `consultas.js` había un respaldo detrás, así
que el selector fallaba **en silencio** y el panel enseñaba el proyecto del slot
con el que entraste en vez del de la pestaña que miras — que es exactamente el
arreglo que sus propios comentarios decían estar haciendo. En `programados.js`
no había respaldo y el síntoma salió a la cara: «esta ventana no pertenece a
ningún slot» sobre una ventana que sí tenía, con la pestaña «Nota» funcionando
al lado.

Y los tres arneses de JS contestaban al selector equivocado, así que los tests
daban verde sobre el fallo. Un arnés que responde a lo que le pregunten no
prueba nada: repite la suposición de quien escribió el script.
"""

from __future__ import annotations

import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
FUENTES = [
    *(RAIZ / "src" / "hub" / "static").glob("*.js"),
    *(RAIZ / "src" / "hub" / "templates").glob("*.html"),
    *(RAIZ / "tests").glob("test_*_js.py"),
]

# Cualquier forma de preguntar por `.por-ventana` filtrando por el atributo.
_MALO = re.compile(r"\.por-ventana[^'\"`\n]*\[hidden\]")


def test_nadie_busca_la_ventana_activa_por_el_atributo_hidden():
    culpables = []
    for archivo in sorted(FUENTES):
        for n, linea in enumerate(archivo.read_text(encoding="utf-8").splitlines(), 1):
            # Los comentarios que EXPLICAN el fallo lo nombran a propósito.
            if linea.lstrip().startswith(("*", "/*", "//", "#")):
                continue
            if _MALO.search(linea):
                culpables.append(f"{archivo.relative_to(RAIZ)}:{n}: {linea.strip()}")

    assert not culpables, (
        "`.por-ventana` conserva el atributo `hidden` SIEMPRE; la activa se marca\n"
        "con la clase `viendo`. Filtrar por `[hidden]` no casa con ninguna:\n  "
        + "\n  ".join(culpables)
        + "\n\nUsa `.por-ventana.viendo`."
    )


def test_la_plantilla_sigue_revelando_por_clase_y_no_por_atributo():
    """La otra mitad: si algún día la plantilla quitara el `hidden` al mostrar,
    este lint pasaría a estar prohibiendo lo correcto. Que se entere aquí."""
    guion = (RAIZ / "src" / "hub" / "templates" / "trabajo.html").read_text(encoding="utf-8")
    assert "b.classList.toggle('viendo', suyo)" in guion
    assert ".por-ventana.viendo { display:flex; }" in guion
