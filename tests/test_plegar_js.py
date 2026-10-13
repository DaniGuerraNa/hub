"""El plegado del raíl, ejecutando el JavaScript de verdad (regla dura 11).

Comprobar que la página devuelve 200 no dice nada de un script que revienta al
arrancar: la página se sirve perfecta y el navegador muere en silencio. Aquí se
ejecuta y se mira qué hizo.
"""

from __future__ import annotations

import pytest

from arnes_js import ejecutar, script_estatico

GUION = script_estatico("plegar.js")


def test_arranca_sin_reventar(tmp_path):
    assert ejecutar(GUION, tmp_path)["errores"] == []


def test_al_pulsar_se_pliega_y_queda_guardado(tmp_path):
    """El efecto es doble: la caja se marca y la preferencia sobrevive al F5."""
    resultado = ejecutar(
        GUION, tmp_path,
        accion="""
          const caja = document.querySelectorAll('.proyecto[data-proyecto]')[0];
          caja.querySelector('.plegar').disparar('click');
          registro.guardado = localStorage.getItem('hub.trabajo.plegados');
        """,
    )

    assert resultado["errores"] == []
    assert [c for c in resultado["alternadas"] if c[0].endswith(":plegado")]
    assert "demo" in (resultado.get("guardado") or "")


def test_lo_plegado_vuelve_plegado_al_recargar(tmp_path):
    """Sin esto el plegado dura hasta la siguiente navegación, o sea nada: en
    esta vista se cambia de ventana a cada rato."""
    resultado = ejecutar(
        GUION, tmp_path,
        previo="localStorage.setItem('hub.trabajo.plegados', JSON.stringify(['demo']));",
    )

    assert resultado["errores"] == []
    plegadas = [c for c in resultado["alternadas"] if c[0].endswith(":plegado") and c[1]]
    assert plegadas, "el proyecto guardado tenía que nacer plegado"


def test_un_localStorage_que_falla_no_deja_el_rail_roto(tmp_path):
    """🔴 En modo privado `localStorage` puede lanzar. Se pierde la preferencia,
    nunca la lista de proyectos — que es lo único para lo que se entra aquí."""
    resultado = ejecutar(
        GUION, tmp_path,
        previo="localStorage.getItem = () => { throw new Error('denegado'); };",
    )

    assert resultado["errores"] == []
