"""Que nadie vuelva a pisar los componentes compartidos con un selector suelto.

`.placa` y `.insignia` son `<span>`. Cualquier regla de la forma `X span { … }`
los alcanza con más especificidad (0,1,1) que su propia clase (0,1,0) y les
cambia por debajo el `display`, el color o el tamaño de letra.

Pasó de verdad el 2026-08-29: `.cifra span { display:block; color:var(--texto-3) }`
convertía la placa en un bloque —con lo que `place-items:center` dejaba de
aplicar y el icono se pegaba a la esquina superior izquierda— y además le
imponía el gris encima de su tinte, así que el escudo de «commits sin respaldo»
salía apagado dentro de un cuadro rojo. No se ve leyendo el CSS; se vio
midiendo. Este test lo caza sin navegador.

La regla que impone: escribe `X > span:not(.placa)`, nunca `X span`. Acotar al
hijo directo y excluir el componente cuesta once caracteres y hace explícito a
quién apunta la regla.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

PLANTILLAS = Path(__file__).resolve().parents[1] / "src" / "hub" / "templates"

# Un selector de span descendiente: algo, un espacio, `span`, y a continuación
# el inicio del bloque o una coma. Lo que lleva `>` o `:not(` queda fuera.
SPAN_SUELTO = re.compile(r"^[^@{}\n]*[^>\s][ ]span\s*(?:,|\{)", re.MULTILINE)


@pytest.mark.parametrize("archivo", sorted(PLANTILLAS.glob("*.html")), ids=lambda p: p.name)
def test_sin_selectores_que_pisen_las_placas(archivo: Path) -> None:
    css = "\n".join(re.findall(r"<style>(.*?)</style>", archivo.read_text(), re.S))
    # Sin comentarios: ahí se escribe *sobre* los selectores, y el lint se
    # denunciaba a sí mismo al leer la nota que explica esta misma regla.
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    culpables = [m.group(0).strip() for m in SPAN_SUELTO.finditer(css)]
    assert not culpables, (
        f"{archivo.name}: selector de span descendiente sin acotar: {culpables}. "
        "`.placa` y `.insignia` son spans y quedan dentro del alcance. "
        "Usa `> span:not(.placa)`."
    )
