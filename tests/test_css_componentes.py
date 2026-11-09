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


# ── los tokens del sistema visual (C-0110) ────────────────────────────────────
#
# CLAUDE.md: «usa los tokens y sus radios, nunca valores literales». Un radio
# de 9, 10 o 16 px escrito a mano es uno de `--r-boton`, `--r-input`/`--r-nav`
# o `--r-tarjeta` que no se enterará si el token cambia: la interfaz se
# descose sin que nadie toque esa línea. Lo que no es de ningún token (7, 11,
# 12 px, la píldora) no se mira aquí.

ESTATICOS = PLANTILLAS.parent / "static"
VENDORIZADOS = {"xterm.css"}   # no son nuestros: se copian tal cual
RADIO = re.compile(r"radius\s*:\s*([^;}\"]*)")
VALOR_DE_TOKEN = re.compile(r"(?<![\d.])(9|10|16)px")


def _sin_comentarios(texto: str) -> str:
    return re.sub(r"\{#.*?#\}|/\*.*?\*/", "", texto, flags=re.S)


@pytest.mark.parametrize(
    "archivo",
    sorted([*PLANTILLAS.glob("*.html"),
            *(c for c in ESTATICOS.glob("*.css") if c.name not in VENDORIZADOS)]),
    ids=lambda p: p.name)
def test_un_radio_que_ya_es_token_se_escribe_con_su_token(archivo: Path) -> None:
    texto = _sin_comentarios(archivo.read_text(encoding="utf-8"))
    culpables = [m.group(0).strip() for m in RADIO.finditer(texto) if VALOR_DE_TOKEN.search(m.group(1))]
    assert not culpables, (
        f"{archivo.name}: radio literal con el valor de un token: {culpables}. "
        "9px es `--r-boton`, 10px `--r-input` (o `--r-nav` en la navegación), 16px `--r-tarjeta`.")


def test_en_base_los_colores_salen_de_root() -> None:
    """Fuera de `:root`, `base.html` no escribe colores: los toma de sus
    tokens. La única excepción es la sombra de lo que flota (`.menu-pop`,
    `.combo-pop`), que CLAUDE.md declara a propósito. El hover de `.cta` y el
    velo de los diálogos eran literales (C-0110)."""
    html = (PLANTILLAS / "base.html").read_text(encoding="utf-8")
    css = _sin_comentarios("\n".join(re.findall(r"<style[^>]*>(.*?)</style>", html, re.S)))
    raiz = re.search(r":root\s*\{.*?\n\}", css, re.S)
    assert raiz, "base.html sin bloque :root"
    fuera = css.replace(raiz.group(0), "")
    culpables = [
        decl.strip() for decl in re.split(r"[;{}]", fuera)
        if re.search(r"#[0-9a-fA-F]{3,8}\b|rgba?\(", decl) and not decl.strip().startswith("box-shadow")
    ]
    assert not culpables, f"colores literales fuera de :root: {culpables}"
