"""Ejecuta el JavaScript del chat del asistente.

Vive en `base.html`, así que si revienta al arrancar se lleva por delante TODAS
las pantallas sin ningún síntoma visible: la página se sirve perfecta y el
navegador muere en silencio (regla dura 11).
"""

from __future__ import annotations

import pytest

from arnes_js import ejecutar, script_estatico


@pytest.fixture(scope="module")
def guion():
    return script_estatico("asistente.js")


@pytest.fixture(scope="module")
def ejecucion(guion, tmp_path_factory):
    return ejecutar(guion, tmp_path_factory.mktemp("js"))


def test_el_script_arranca_sin_reventar(ejecucion):
    assert ejecucion["errores"] == []


def test_plegado_no_sondea_nada(ejecucion):
    """Es una barra en las siete pantallas. Un sondeo de fondo permanente sería
    coste puro por algo que nadie está mirando."""
    assert ejecucion["peticiones"] == []


def test_registra_los_gestos_que_lo_hacen_usable(ejecucion):
    # Sin el clic la pestaña no abre; sin el keydown, Enter no envía.
    assert ejecucion["oyentes"].count("click") >= 3
    assert "keydown" in ejecucion["oyentes"]


def test_el_sondeo_pide_solo_lo_nuevo(guion):
    """Sin el `desde`, cada segundo y medio se relee la conversación entera —y
    el transcript de una sesión larga son megabytes."""
    assert "desde=" in guion


def test_compactar_y_limpiar_piden_confirmacion(guion):
    """Ninguno de los dos es reversible: `/clear` deja el transcript huérfano y
    `/compact` no se deshace."""
    assert guion.count("HubUI.confirmar") == 2


def test_el_compactado_va_en_dos_tiempos_y_no_ensena_el_prompt(guion):
    # El usuario: "que el propio chat genere un prompt que se adjuntará con el compact
    # […] ese prompt generado no hace falta que me lo muestre".
    assert "'preparar'" in guion and "'ejecutar'" in guion
    assert "instrucciones" not in guion.split("// ── Compactar")[1].split("btLimpiar")[0] \
        or "no se enseñan" in guion


def test_el_indicador_de_contexto_no_inventa_un_porcentaje(guion):
    """Regla dura 13. Sin saber el tamaño de la ventana sólo se pueden enseñar
    tokens; un porcentaje sobre una ventana supuesta sería una cifra indefendible
    justo en el dato que él usa para decidir cuándo compactar."""
    assert "porcentaje != null" in guion and "c.tokens" in guion


def test_el_texto_del_usuario_se_escapa_antes_de_pintarlo(guion):
    """El transcript trae texto libre suyo y del modelo, con `<` y `&` a mansalva.
    Interpolarlo crudo en innerHTML rompe el hilo al primer fragmento de HTML."""
    assert "escapar(m.texto)" in guion


def test_lo_escrito_no_se_pierde_si_el_envio_falla(guion):
    """Perder un mensaje largo porque el asistente estaba ocupado sería la peor
    manera de fallar aquí."""
    assert guion.count("caja.value = texto") == 2


def test_no_existe_ninguna_llamada_de_borrado(guion):
    """Regla dura 16: el asistente escribe notas y crea slots. Borrar es del usuario."""
    assert "method: 'DELETE'" not in guion and "/borrar" not in guion


def test_el_cuadro_de_permisos_se_pinta_con_dos_botones(guion):
    """Desde la web no se puede pulsar «Yes», así que sin traerlo al chat la
    conversación se queda muda: ni pensando, ni respondiendo."""
    assert "pintarConfirmacion" in guion
    assert "data-r=\"si\"" in guion and "data-r=\"no\"" in guion


def test_no_se_ofrece_el_no_volver_a_preguntar(guion):
    """La opción 2 de Claude Code amplía sus permisos para siempre. Eso se
    decide editando su settings.json, no pulsando un botón en un chat."""
    import re

    # Las únicas respuestas que el chat puede mandar son las de sus dos botones.
    assert sorted(set(re.findall(r'data-r="(\w+)"', guion))) == ["no", "si"]
    assert "respuesta: b.dataset.r" in guion  # y no un valor cableado aparte


def test_lo_que_pide_se_escapa_antes_de_pintarlo(guion):
    """El comando que pide permiso es texto arbitrario del modelo, con `<`, `&`
    y comillas a mansalva. Interpolarlo crudo rompe el hilo entero."""
    assert "escapar(c.peticion.join" in guion
