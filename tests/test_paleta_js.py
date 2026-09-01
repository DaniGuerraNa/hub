"""Ejecuta el JavaScript de la paleta de comandos.

Vive en `base.html`, así que si revienta al arrancar se lleva por delante el
atajo en TODAS las pantallas, sin ningún síntoma visible (regla dura 11).
"""

from __future__ import annotations

import pytest

from arnes_js import ejecutar, script_estatico


@pytest.fixture(scope="module")
def ejecucion(tmp_path_factory):
    return ejecutar(script_estatico("paleta.js"), tmp_path_factory.mktemp("js"))


def test_el_script_arranca_sin_reventar(ejecucion):
    assert ejecucion["errores"] == []


def test_registra_el_atajo_global_de_teclado(ejecucion):
    """Sin este oyente, Ctrl+K no hace nada y la paleta queda inalcanzable."""
    assert "window:keydown" in ejecucion["oyentes"]


def test_no_pide_nada_al_arrancar(ejecucion):
    """La paleta sólo consulta cuando se escribe: no cuesta nada estar ahí."""
    assert ejecucion["peticiones"] == []


def test_cubre_todas_las_secciones_de_la_navegacion():
    """Un atajo `g` que no llegue a una sección es peor que no tenerlo: se
    aprende el gesto y falla justo donde hace falta."""
    guion = script_estatico("paleta.js")
    for destino in ("/trabajo", "/inventario", "/respaldo", "/servicios",
                    "/conexiones", "/contexto"):
        assert f"'{destino}'" in guion


def test_no_roba_teclas_mientras_escribes(ejecucion):
    """En el terminal embebido, robar una tecla arruina el comando que ibas a
    lanzar — la peor forma posible de fallar aquí."""
    guion = script_estatico("paleta.js")
    assert ".xterm" in guion and "isContentEditable" in guion
