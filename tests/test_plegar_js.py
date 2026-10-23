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


def test_al_entrar_todo_esta_plegado(tmp_path):
    """22-oct: al entrar (o con F5) sólo queda abierto el proyecto que se mira;
    antes había que cerrarlos a mano en cada carga."""
    resultado = ejecutar(GUION, tmp_path)
    assert resultado["errores"] == []
    plegadas = [c for c in resultado["alternadas"] if c[0].endswith(":plegado")]
    assert plegadas and all(v for _, v in plegadas)


def test_el_proyecto_que_se_mira_queda_abierto(tmp_path):
    resultado = ejecutar(
        GUION, tmp_path,
        previo="""
          const [mirado] = document.querySelectorAll('.proyecto[data-proyecto]');
          mirado.classList.add('mirando');
          globalThis.MIRADO = mirado;
        """,
        accion="registro.mirado = MIRADO.classList.contains('plegado');",
    )
    assert resultado["errores"] == []
    assert resultado["mirado"] is False


def test_desplegar_a_mano_no_se_recuerda(tmp_path):
    """Vale hasta la siguiente carga: recordarlo es lo que dejaba la lista
    larga en cada F5."""
    resultado = ejecutar(
        GUION, tmp_path,
        accion="""
          const caja = document.querySelectorAll('.proyecto[data-proyecto]')[0];
          caja.querySelector('.plegar').disparar('click');
          registro.abierto = !caja.classList.contains('plegado');
          registro.guardado = localStorage.getItem('hub.trabajo.plegados');
        """,
    )
    assert resultado["errores"] == []
    assert resultado["abierto"] is True
    assert resultado["guardado"] is None


def test_un_localStorage_que_falla_no_deja_el_rail_roto(tmp_path):
    """🔴 En modo privado `localStorage` puede lanzar. Se pierde la preferencia,
    nunca la lista de proyectos — que es lo único para lo que se entra aquí."""
    resultado = ejecutar(
        GUION, tmp_path,
        previo="localStorage.getItem = () => { throw new Error('denegado'); };",
    )

    assert resultado["errores"] == []
