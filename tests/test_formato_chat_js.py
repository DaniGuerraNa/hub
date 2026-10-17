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
