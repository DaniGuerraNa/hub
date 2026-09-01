"""Ejecuta de verdad el JavaScript de la vista de trabajo.

Existe por un fallo real: `let ws` estaba declarado después de la función que lo
lee durante el arranque, así que la zona muerta temporal abortaba el script
entero y el terminal se quedaba en negro. Comprobar el HTTP 200 no lo detectó —
la página se servía perfecta y el navegador moría al ejecutarla.
"""

from __future__ import annotations

import pytest

from arnes_js import ejecutar, script_de

CONTEXTO = {
    "session": "work",
    "ventana": 1,
    "slot": {"id": 7, "nombre": "back", "ruta": "/tmp/demo", "nota": "pendiente", "abierto": True},
    "slot_id": 7,
    "proyectos": [
        {"id": "demo", "nombre": "Demo", "paneles_abiertos": 2,
         "slots": [{"id": 7, "nombre": "back", "ruta": "/tmp/demo"}]}
    ],
    "sesiones": [{"session": "work", "paneles": 3, "etiquetas": []}],
    "paneles": [],
    "ancho_completo": True,
    "seccion": "trabajo",
    "titulo": "back",
}


@pytest.fixture(scope="module")
def ejecucion(tmp_path_factory):
    return ejecutar(script_de("trabajo.html", CONTEXTO), tmp_path_factory.mktemp("js"))


def test_el_script_arranca_sin_reventar(ejecucion):
    assert ejecucion["errores"] == []


def test_abre_el_websocket_a_la_sesion_y_ventana_correctas(ejecucion):
    """Si el arranque falla, esta lista queda vacía y el terminal se ve en negro."""
    assert ejecucion["sockets"] == ["ws://localhost/ws/terminal/work?ventana=1"]


def test_pide_las_ventanas_de_la_sesion_al_arrancar(ejecucion):
    assert "/api/sesion/work/ventanas" in ejecucion["peticiones"]


def test_registra_el_atajo_de_teclado_para_saltar_de_ventana(ejecucion):
    assert "window:keydown" in ejecucion["oyentes"]


def test_vigila_el_hueco_del_terminal_en_vez_de_confiar_en_acordarse(ejecucion):
    """El tamaño útil depende del preset, del rail, de la nota, del arrastre y de
    cuántas líneas ocupe la cabecera. Acordarse de reajustar en cada una es la
    clase de olvido que deja filas invisibles debajo del borde."""
    assert "marco" in ejecucion["observados"]


def test_el_ajuste_del_tamano_se_aplaza_a_un_frame_posterior():
    """xterm recalcula el alto de celda de forma asíncrona al cambiar la fuente.

    Medir en la misma vuelta usaba las métricas viejas: al pasar a «cómodo»
    pedía más filas de las que caben y las últimas quedaban fuera de la vista.
    """
    guion = script_de("trabajo.html", CONTEXTO)
    # `encajar()` es quien llama a `fit()`, y tiene que invocarse desde dentro
    # del frame aplazado — no en la misma vuelta que el cambio de fuente.
    dentro = guion.index("encajar();")
    raf = guion.index("requestAnimationFrame")
    assert raf < dentro, "el ajuste va dentro del frame aplazado, no antes"


def test_el_panel_derecho_sigue_a_la_pestana():
    """🔴 Sin esto, cambiar de pestaña dejaba la nota del slot con el que se
    entró: escribías en el trabajo equivocado y nada en la pantalla lo decía.
    Cambiar de ventana no recarga la página, así que el JS tiene que moverlo."""
    guion = script_de("trabajo.html", CONTEXTO)
    assert "mostrarPanelDe" in guion
    # Se llama tanto al cambiar de pestaña como al resolver la ventana inicial.
    assert guion.count("mostrarPanelDe(") >= 3


def test_la_url_sigue_a_la_pestana():
    """Para que recargar, o volver de un formulario, caiga en la ventana que se
    está mirando y no en la que se abrió al principio."""
    guion = script_de("trabajo.html", CONTEXTO)
    assert "history.replaceState" in guion
    assert "searchParams.set('ventana'" in guion


def test_cada_nota_guarda_en_su_propio_slot():
    """Hay una nota por ventana en el DOM a la vez. Un solo `data-slot` global
    haría que todas guardaran en el mismo sitio."""
    guion = script_de("trabajo.html", CONTEXTO)
    assert "querySelectorAll('.nota-texto')" in guion
    assert "nota.dataset.slot" in guion


def test_las_pestanas_no_se_reescriben_al_cambiar_de_ventana():
    """🔴 Reescribir el HTML entero en cada pintado ROMPÍA el doble clic.

    El primer clic repintaba, el segundo caía sobre un nodo recién creado y el
    navegador emitía el `dblclick` en la barra, no en la pestaña. El manejador
    busca `[data-ir]` desde el target, así que salía sin hacer nada: renombrar
    no fallaba, no llegaba a empezar. El sondeo de cada 5 s podía provocarlo
    igual, sin tocar nada.
    """
    guion = script_de("trabajo.html", CONTEXTO)
    assert "firmaPintada" in guion, "hace falta comparar antes de reescribir"
    # La clase activa se actualiza sobre los nodos vivos, no reescribiéndolos.
    assert "classList.toggle('activa'" in guion


def test_el_doble_clic_tiene_red_de_seguridad_por_posicion():
    """Si el repintado se cuela igualmente entre los dos clics, el puntero sí
    sabe sobre qué pestaña estaba."""
    guion = script_de("trabajo.html", CONTEXTO)
    assert "elementFromPoint" in guion


def test_la_vista_enseña_el_desfase_de_columnas():
    """No se puede arreglar lo que no se ve. Tres intentos de diagnóstico se
    fueron en esto: tmux creía tener más columnas que el navegador y las letras
    del final de cada línea desaparecían sin ningún síntoma."""
    guion = script_de("trabajo.html", CONTEXTO)
    assert "medirDesfase" in guion
    # Se avisa en color de alerta sólo cuando de verdad hay desfase.
    assert "'frio' : 'tenue'" in guion or "desfase ? 'frio'" in guion


def test_el_ancho_del_terminal_se_mide_no_se_estima():
    """🔴 Cuatro intentos se fueron en esto.

    `fit()` pide más columnas de las que caben: calcula con
    `getComputedStyle(padre).width`, que con `box-sizing:border-box` incluye el
    padding, y resta el de `.xterm`, no el del marco. La última columna queda
    fuera del área visible y `overflow:hidden` se la come — se pierden letras al
    final de la línea y sólo reaparecen al redimensionar.

    Compensarlo con padding no bastó dos veces seguidas: la holgura quedaba por
    debajo del ancho de una celda y un redondeo volvía a comerse un carácter.
    Así que se mide el desbordamiento real y se quitan columnas hasta que quepa.
    """
    guion = script_de("trabajo.html", CONTEXTO)
    assert "function encajar()" in guion
    assert "vp.clientWidth - holgura" in guion, (
        "encajar al píxel exacto dejaba 1px de margen y `offsetWidth` es entero: "
        "se exige media celda libre")
    assert "guardia" in guion, "un layout raro no puede colgar la página"
