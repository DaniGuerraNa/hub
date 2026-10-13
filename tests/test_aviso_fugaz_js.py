"""El aviso de después de una acción se va solo, ejecutando el JS (regla dura 11)."""

from __future__ import annotations

from arnes_js import ejecutar, script_estatico

GUION = script_estatico("aviso-fugaz.js")


def test_lo_que_salio_bien_se_va_solo_a_los_cinco_segundos(tmp_path):
    r = ejecutar(GUION, tmp_path, previo="""
      const aviso = nodo('aviso');
      aviso.classList.add('fugaz');
      document.querySelector = () => aviso;
    """)

    assert r["errores"] == []
    assert 5000 in r["temporizadores"]


def test_un_fallo_se_queda_hasta_que_se_cierra(tmp_path):
    """Regla dura 21: lo que falla se dice, y no se desvanece solo."""
    r = ejecutar(GUION, tmp_path, previo="""
      const aviso = nodo('aviso');
      document.querySelector = () => aviso;
    """, accion="""
      nodo('aviso').querySelector('[data-cerrar-aviso]').disparar('click');
      registro.cerrado = nodo('aviso').classList.contains('ido');
    """)

    assert 5000 not in r["temporizadores"]
    assert r["cerrado"] is True


def test_recargar_no_lo_vuelve_a_pintar(tmp_path):
    r = ejecutar(GUION, tmp_path, previo="""
      location.href = 'http://localhost/orquestador?tarea=t-1&aviso=Encolada&fugaz=1#tarea';
      global.history = { replaceState(a, b, url) { registro.url = url; } };
    """)

    assert r["url"] == "/orquestador?tarea=t-1#tarea"
