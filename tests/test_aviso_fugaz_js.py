"""El aviso de después de una acción se va solo, ejecutando el JS (regla dura 11)."""

from __future__ import annotations

from pathlib import Path

from arnes_js import ejecutar, script_estatico

GUION = script_estatico("aviso-fugaz.js")
BASE = Path(__file__).resolve().parents[1] / "src" / "hub" / "templates" / "base.html"

# El aviso que pinta la página: `querySelectorAll` porque puede llegar más de
# uno a lo largo de la vida de la página (C-0167: sin recargar).
CON_AVISO = """
  const aviso = nodo('aviso');
  document.querySelectorAll = (sel) => sel === '[data-aviso-fugaz]' ? [aviso] : [];
"""


def test_lo_que_salio_bien_se_va_solo_a_los_cinco_segundos(tmp_path):
    r = ejecutar(GUION, tmp_path, previo=CON_AVISO + """
      aviso.classList.add('fugaz');
    """)

    assert r["errores"] == []
    assert 5000 in r["temporizadores"]


def test_un_fallo_se_queda_hasta_que_se_cierra(tmp_path):
    """Regla dura 21: lo que falla se dice, y no se desvanece solo."""
    r = ejecutar(GUION, tmp_path, previo=CON_AVISO, accion="""
      nodo('aviso').querySelector('[data-cerrar-aviso]').disparar('click');
      registro.cerrado = nodo('aviso').classList.contains('ido');
    """)

    assert 5000 not in r["temporizadores"]
    assert r["cerrado"] is True


def test_recargar_no_lo_vuelve_a_pintar(tmp_path):
    r = ejecutar(GUION, tmp_path, previo=CON_AVISO + """
      location.href = 'http://localhost/orquestador?tarea=t-1&aviso=Encolada&fugaz=1#tarea';
      global.history = { replaceState(a, b, url) { registro.url = url; } };
    """)

    assert r["url"] == "/orquestador?tarea=t-1#tarea"


def test_el_que_llega_sin_recargar_tambien_se_va_solo(tmp_path):
    """C-0167: `sin-recarga.js` pinta el aviso de la acción sin cargar la
    página, y avisa con `hub:repintado`. Sin repasar ahí, ese aviso se quedaba
    para siempre."""
    r = ejecutar(GUION, tmp_path, previo="""
      document.querySelectorAll = () => [];
    """, accion="""
      const nuevo = nodo('nuevo-aviso');
      nuevo.classList.add('fugaz');
      document.querySelectorAll = (sel) => sel === '[data-aviso-fugaz]' ? [nuevo] : [];
      DOC_OYENTES['hub:repintado'].forEach((f) => f({}));
    """)

    assert r["errores"] == []
    assert "document:hub:repintado" in r["oyentes"]
    assert 5000 in r["temporizadores"]


def test_el_aviso_de_una_accion_flota_y_no_empuja_la_pagina():
    """Entraba en el flujo encima del contenido y se iba a los cinco segundos:
    dos saltos por acción. Flota fijo, y sin sombra (el sistema no las usa)."""
    css = BASE.read_text(encoding="utf-8")
    i = css.index(".aviso-accion[data-aviso-fugaz] {")
    regla = css[i:css.index("}", i)]
    assert "position:fixed" in regla
    assert "shadow" not in regla
