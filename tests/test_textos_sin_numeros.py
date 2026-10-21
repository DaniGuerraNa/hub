"""Lo que lee quien usa el hub no cita reglas ni decisiones por número.

`ARQUITECTURA.md` y el `CLAUDE.md` de desarrollo no se publican: en el repo
público, «(decisión 162)» en un mensaje de error es un número que nadie puede
buscar. Los comentarios sí los citan —ahí los lee quien tiene el documento—.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
NUMERO = re.compile(r"(decisi[oó]n(es)?|regla( dura)?|principio)\s+\d+", re.I)


def _sin_comentarios(texto: str) -> str:
    for patron in (r"\{#.*?#\}", r"<!--.*?-->", r"/\*.*?\*/"):
        texto = re.sub(patron, lambda m: "\n" * m.group(0).count("\n"), texto, flags=re.S)
    return "\n".join(re.sub(r"(^|\s)//.*", "", linea) for linea in texto.split("\n"))


def test_las_plantillas_y_el_javascript_no_ensenan_numeros_de_reglas():
    archivos = [*(RAIZ / "src/hub/templates").glob("*.html"),
                *(RAIZ / "src/hub/static").glob("*.js")]
    encontrados = [
        f"{p.name}:{n}" for p in archivos
        for n, linea in enumerate(_sin_comentarios(p.read_text(encoding="utf-8")).split("\n"), 1)
        if NUMERO.search(linea)
    ]
    assert encontrados == []


def test_los_mensajes_del_codigo_no_ensenan_numeros_de_reglas():
    """Cadenas que no son docstrings: mensajes de error, avisos, rótulos.
    `db.py` se salta porque sus cadenas son SQL con comentarios."""
    encontrados = []
    for p in (RAIZ / "src/hub").glob("*.py"):
        if p.name == "db.py":
            continue
        arbol = ast.parse(p.read_text(encoding="utf-8"))
        docstrings = {
            id(n.body[0].value) for n in ast.walk(arbol)
            if isinstance(n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            and n.body and isinstance(n.body[0], ast.Expr)
            and isinstance(n.body[0].value, ast.Constant)
        }
        encontrados += [
            f"{p.name}:{n.lineno}" for n in ast.walk(arbol)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)
            and id(n) not in docstrings and NUMERO.search(n.value)
        ]
    assert encontrados == []
