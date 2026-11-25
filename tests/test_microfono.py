"""Un solo botón de dictar en todo el hub (C-0480).

Había cuatro maneras de dictar: el chat con su micrófono, y Trabajo, Tablero y
Orquestador escribiendo «Dictar» (Trabajo, dos veces). Ahora todos pasan por
`ui.microfono`, y el modelo del dictado (decisión 452) va a su lado sólo donde
lo dictado sube a `/api/voz`, que es el único camino que ese modelo gobierna.
"""

from __future__ import annotations

import re
from pathlib import Path

from hub import interfaz, web

PLANTILLAS = Path(__file__).resolve().parents[1] / "src" / "hub" / "templates"


def _pintar(fuente: str) -> str:
    entorno = web._PLANTILLAS[interfaz.CLASICA].env
    return entorno.from_string('{% import "_ui.html" as ui %}' + fuente).render()


def _llamadas(texto: str, nombre: str) -> list[str]:
    """Los argumentos de cada `ui.<nombre>(…)`, con los paréntesis emparejados."""
    salida = []
    for m in re.finditer(r"ui\." + nombre + r"\(", texto):
        i, nivel = m.end(), 1
        while nivel:
            nivel += (texto[i] == "(") - (texto[i] == ")")
            i += 1
        salida.append(texto[m.end():i - 1])
    return salida


def test_ninguna_plantilla_tiene_un_boton_que_diga_dictar():
    """El micrófono es el botón de dictar; la palabra queda en su nombre para
    el lector de pantalla y al pasar el ratón."""
    culpables = []
    for archivo in sorted(PLANTILLAS.rglob("*.html")):
        texto = re.sub(r"\{#.*?#\}", "", archivo.read_text(encoding="utf-8"), flags=re.S)
        for m in re.finditer(r"<button\b[^>]*>(.*?)</button>", texto, re.S):
            visible = re.sub(r"<[^>]+>|\{\{.*?\}\}", "", m.group(1)).strip()
            if re.search(r"\bDictar\b", visible):
                culpables.append(f"{archivo.relative_to(PLANTILLAS)}: {visible!r}")
    assert not culpables, culpables


def test_el_microfono_es_un_icono_con_su_nombre_y_sus_datos():
    html = _pintar("{{ ui.microfono(datos={'grabar': 'pedido', 'grabar-estado': 'estado'}) }}")
    boton = re.search(r"<button\b[^>]*>", html).group(0)
    assert 'aria-label="Dictar"' in boton and 'title="Dictar"' in boton
    assert 'data-grabar="pedido"' in boton and 'data-grabar-estado="estado"' in boton
    assert 'class="mic icono-solo sutil"' in boton
    assert html.count("<svg") == 2 and "data-mic-seg" in html
    assert re.sub(r"<[^>]+>", "", html).strip() == "", "el botón no lleva palabra visible"
    assert "data-modelo-dictado" not in html


def test_con_modelo_la_flecha_va_pegada_al_microfono():
    html = _pintar("{{ ui.microfono(datos={'dictar': ''}, modelo=true) }}")
    assert html.strip().startswith('<span class="mic-con-modelo">')
    assert 'data-md-forma="flecha"' in html and 'aria-label="Modelo del dictado"' in html


def test_dentro_de_un_menu_el_modelo_es_un_plegable_y_no_otro_menu():
    """Un `details.menu` dentro de otro se cierra al abrirse: `hub-ui.js` cierra
    los menús que no contienen lo pulsado."""
    html = _pintar("{{ ui.modelo_dictado('seccion') }}")
    details = re.search(r"<details\b[^>]*>", html).group(0)
    assert "data-modelo-dictado" in details and 'data-md-forma="seccion"' in details
    clases = re.search(r'class="([^"]*)"', details).group(1).split()
    assert "menu" not in clases and "plegable-menu" in clases


def test_el_modelo_solo_va_junto_a_un_microfono_que_sube_a_api_voz():
    """El modelo gobierna `/api/voz` y nada más (decisión 452). La terminal
    (`data-dictar`) sube por `HubGrabar.subir`, que va ahí por omisión; un
    `data-grabar` sube a `/orquestador/audio` salvo que diga `grabar-url`.
    El Orquestador transcribe por el camino de los encargos: un menú de modelo
    a su lado diría algo que allí no se aplica."""
    culpables, vistos = [], set()
    for archivo in sorted(PLANTILLAS.rglob("*.html")):
        if archivo.name == "_ui.html":      # su comentario lo nombra
            continue
        texto = archivo.read_text(encoding="utf-8")
        for args in _llamadas(texto, "microfono"):
            if "modelo=true" not in args:
                continue
            vistos.add(archivo.name)
            a_voz = "'dictar'" in args or re.search(r"'grabar-url'\s*:\s*'/api/voz'", args)
            if not a_voz:
                culpables.append(f"{archivo.name}: ui.microfono({' '.join(args.split())})")
    assert not culpables, culpables
    assert vistos == {"tablero.html", "trabajo.html"}, vistos


def test_el_modelo_suelto_solo_va_donde_hay_un_microfono_que_sube_a_api_voz():
    """Llamado a pelo, `ui.modelo_dictado` sólo está en el chat del secretario
    (su micrófono sube a `/api/voz`) y en el «⋯» de Trabajo, junto a la terminal."""
    con_modelo = {archivo.name for archivo in PLANTILLAS.rglob("*.html")
                  if archivo.name != "_ui.html" and _llamadas(archivo.read_text(encoding="utf-8"), "modelo_dictado")}
    assert "_chat_secretario.html" in con_modelo
    assert con_modelo <= {"_chat_secretario.html", "trabajo.html"}, con_modelo
    trabajo = (PLANTILLAS / "trabajo.html").read_text(encoding="utf-8")
    assert "data-dictar" in trabajo or "'dictar'" in trabajo


def test_el_orquestador_dicta_con_el_microfono_y_sin_modelo():
    texto = (PLANTILLAS / "orquestador.html").read_text(encoding="utf-8")
    llamadas = _llamadas(texto, "microfono")
    assert len(llamadas) == 3
    assert not [a for a in llamadas if "modelo" in a]
    assert "modelo_dictado" not in texto
