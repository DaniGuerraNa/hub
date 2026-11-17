"""Lo que el asistente escribe se pinta con enlaces del hub, y con nada más.

El chat era texto plano y el asistente no podía llevarte a ningún sitio: daba
la ruta y había que copiarla (decisión 271). Ahora un `[Abrir Trabajo](/trabajo)`
se pulsa. 🔴 Pero sólo si apunta al hub: el texto lo escribe un modelo que ha
leído transcripts y archivos ajenos, y un `javascript:` o un enlace fuera es
justo lo que no puede llegar al innerHTML.

Se ejecuta el archivo de verdad en node (regla dura 11).
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

GUION = Path(__file__).resolve().parents[1] / "src" / "hub" / "static" / "formato-chat.js"

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="hace falta node")


def formatear(*textos: str) -> list[str]:
    programa = (GUION.read_text(encoding="utf-8")
                + f"\nconsole.log(JSON.stringify({json.dumps(list(textos))}.map(formatearMensaje)));")
    salida = subprocess.run(["node", "-e", programa], capture_output=True, text=True,
                            timeout=20, check=True).stdout
    return json.loads(salida)


def test_un_enlace_del_hub_se_puede_pulsar():
    [html] = formatear("Ve a [Trabajo](/trabajo?slot=3#nota) y crea el slot.")

    assert html == 'Ve a <a class="ir" href="/trabajo?slot=3&amp;#nota">Trabajo</a> y crea el slot.' \
        or html == 'Ve a <a class="ir" href="/trabajo?slot=3#nota">Trabajo</a> y crea el slot.'


def test_un_enlace_fuera_del_hub_se_queda_en_texto():
    html = formatear("[pulsa](javascript:alert(1))", "[otro](https://malo.example)",
                     "[doble](//malo.example/x)", '[comillas](/x"onmouseover="y)')

    assert all("<a" not in h for h in html), html


def test_el_html_del_transcript_nunca_llega_crudo():
    [html] = formatear('<img src=x onerror="alert(1)"> & **negrita**')

    assert "<img" not in html and "&lt;img" in html and "&amp;" in html
    assert "<strong>negrita</strong>" in html


def test_lo_que_va_entre_comillas_de_codigo_no_se_interpreta():
    [html] = formatear("usa `[esto](/trabajo) **no**` tal cual")

    assert html == "usa <code>[esto](/trabajo) **no**</code> tal cual"


# ── bloques de código y títulos (C-0306) ─────────────────────────────────────

def formatear_con(opciones: dict, *textos: str) -> list[str]:
    programa = (GUION.read_text(encoding="utf-8")
                + f"\nconsole.log(JSON.stringify({json.dumps(list(textos))}"
                  f".map(t => formatearMensaje(t, {json.dumps(opciones)}))));")
    salida = subprocess.run(["node", "-e", programa], capture_output=True, text=True,
                            timeout=20, check=True).stdout
    return json.loads(salida)


def test_un_bloque_de_codigo_sale_aparte_escapado_y_sin_interpretar():
    """Con tres comillas invertidas quedaba literal y en letra normal: una
    orden o una ruta no se distinguía ni se copiaba cómodamente."""
    [html] = formatear("Haz esto:\n```bash\nls -la **no** [x](/trabajo)\n<script>alert(1)</script>\n```\nY ya.")

    assert html == ('Haz esto:<div class="bloque-codigo"><pre><code>ls -la **no** [x](/trabajo)\n'
                    '&lt;script&gt;alert(1)&lt;/script&gt;</code></pre></div>Y ya.')


def test_el_bloque_que_aun_se_esta_escribiendo_ya_sale_como_codigo():
    """La respuesta llega por trozos (C-0155): sin cerrar todavía, ya es código."""
    [html] = formatear("Prueba:\n```\nuv run pytest")

    assert html == 'Prueba:<div class="bloque-codigo"><pre><code>uv run pytest</code></pre></div>'


def test_en_el_chat_del_secretario_el_bloque_lleva_copiar():
    [html] = formatear_con({"copiar": True}, "```\nuv run pytest\n```")

    assert html == ('<div class="bloque-codigo"><button type="button" class="copiar-codigo" data-copiar-codigo>'
                    'Copiar</button><pre><code>uv run pytest</code></pre></div>')


def test_un_titulo_sale_en_negrita_sin_sus_almohadillas():
    [html] = formatear("## Lo que tienes hoy\nDos reuniones, el issue #123 y\n# Otra cosa")

    assert html == ('<strong class="titulo">Lo que tienes hoy</strong>\nDos reuniones, el issue #123 y\n'
                    '<strong class="titulo">Otra cosa</strong>')


def test_dentro_de_un_bloque_de_codigo_una_almohadilla_es_codigo():
    [html] = formatear("```\n# un comentario\n```")

    assert "<strong" not in html and "# un comentario" in html


def test_tres_comillas_en_una_linea_son_codigo_en_linea():
    [html] = formatear("usa ```git status``` y ya")

    assert html == "usa <code>git status</code> y ya"
