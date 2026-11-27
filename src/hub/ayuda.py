"""Cómo se usa el hub, leído de su conocimiento (C-0504).

`conocimiento/` es lo que viaja al producto para explicar cada pantalla
(`producto/conocimiento/` en el repo de desarrollo, `conocimiento/` en el clon:
`publicacion`). Hasta aquí nada del hub lo leía: el secretario contestaba
«¿cómo se entra desde el móvil?» de memoria, y a quien preguntó le inventó
enlaces y le propuso escuchar en 0.0.0.0. Ésta es la única puerta para leerlo.

Sin parámetro de ruta, a propósito: quien llama sólo da palabras, y lo que
sale son secciones (`## …`) de los `.md` de esa carpeta, recortadas aquí y no
en cada llamador. Nunca lanza: sin carpeta, nada.
"""

from __future__ import annotations

import re
from pathlib import Path

from . import config

#: Lo que se devuelve de cada sección, en caracteres: un paso a paso entero
#: cabe; un documento entero, no.
TOPE_SECCION = 4000

_PALABRA = re.compile(r"\w+", re.UNICODE)


def carpeta() -> Path:
    """Dónde está el conocimiento: el del clon del producto o, en el repo de
    desarrollo, el que se publica."""
    clon = config.RAIZ_REPO / "conocimiento"
    return clon if clon.is_dir() else config.RAIZ_REPO / "producto" / "conocimiento"


def _secciones_de(archivo: Path) -> list[tuple[str, str]]:
    try:
        texto = archivo.read_text(encoding="utf-8")
    except OSError:
        return []
    trozos = re.split(r"(?m)^(?=#{2,3} )", texto)
    return [(t.splitlines()[0].lstrip("# ").strip(), t.strip()) for t in trozos
            if t.startswith("##") and t.strip()]


def _sin_tildes(texto: str) -> str:
    return texto.casefold().translate(str.maketrans("áéíóúüñ", "aeiouun"))


def secciones(texto: str, n: int = 2) -> list[dict]:
    """Las `n` secciones que mejor casan con `texto`: `{titulo, archivo, texto}`.

    Cuenta cuántas palabras de `texto` (de tres letras o más) salen en cada
    sección, y el título pesa el triple. Sin ninguna coincidencia, nada."""
    palabras = {p for p in _PALABRA.findall(_sin_tildes(texto or "")) if len(p) >= 3}
    if not palabras:
        return []
    raiz = carpeta()
    try:
        archivos = sorted(a for a in raiz.glob("*.md") if a.name != "INDICE.md")
    except OSError:
        return []
    puntuadas = []
    for archivo in archivos:
        for titulo, cuerpo in _secciones_de(archivo):
            en_titulo = set(_PALABRA.findall(_sin_tildes(titulo)))
            en_cuerpo = set(_PALABRA.findall(_sin_tildes(cuerpo)))
            puntos = sum(3 if p in en_titulo else 1 for p in palabras if p in en_cuerpo or p in en_titulo)
            if puntos:
                puntuadas.append((puntos, archivo.name, titulo, cuerpo))
    # Las de más puntos; a igualdad, la sección más corta, que es la más concreta.
    puntuadas.sort(key=lambda x: (-x[0], len(x[3])))
    salida = []
    for _, nombre, titulo, cuerpo in puntuadas[:max(1, n)]:
        recortado = cuerpo if len(cuerpo) <= TOPE_SECCION else cuerpo[:TOPE_SECCION].rsplit("\n", 1)[0] + "\n…"
        salida.append({"titulo": titulo, "archivo": nombre, "texto": recortado})
    return salida
