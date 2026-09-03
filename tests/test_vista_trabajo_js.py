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


# Lo que contesta el hub al latido. El slot del arnés es el 7, y viene con un
# estado y una nota DISTINTOS de los que la página pintó: si el script no hace
# nada con la respuesta, el efecto no aparece por ninguna parte.
PULSO = {"/api/trabajo/pulso": {"slots": {"7": "trabajando"},
                                "notas": {"7": "lo escribió otro"}}}


@pytest.fixture(scope="module")
def ejecucion(tmp_path_factory):
    return ejecutar(
        script_de("trabajo.html", CONTEXTO), tmp_path_factory.mktemp("js"), PULSO
    )


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


# ── el latido, ejecutado ──────────────────────────────────────────────────────
#
# La vista se pintaba entera en el servidor y se quedaba quieta. El punto de
# estado congelado es peor que no tenerlo: existe para enterarse de que un
# segundo slot paró, y sólo se enteraba quien recargara.

def test_pide_el_pulso_al_arrancar(ejecucion):
    """Y con las notas que tiene en pantalla, no con todas las del hub."""
    pulsos = [p for p in ejecucion["peticiones"] if p.startswith("/api/trabajo/pulso")]
    assert pulsos == ["/api/trabajo/pulso?notas=7"]


def test_deja_de_latir_con_la_pestana_de_fondo(ejecucion):
    """Una petición cada cinco segundos durante horas, para nadie."""
    assert "document:visibilitychange" in ejecucion["oyentes"]


def test_el_latido_arranca_despues_de_lo_que_usa():
    """🔴 Es el fallo que dejó el terminal en negro y creó este archivo.

    `latir()` toca `notas` y `puntos`, declarados con `const`. Programarlo antes
    aborta el script entero por la zona muerta temporal, y la página se sirve
    perfecta mientras el navegador muere en silencio.
    """
    guion = script_de("trabajo.html", CONTEXTO)
    assert guion.index("const notas =") < guion.index("setInterval(latir")
    assert guion.index("const puntos =") < guion.index("setInterval(latir")


def test_las_ventanas_del_mismo_slot_comparten_la_nota_al_instante():
    """Hay un `textarea` por ventana y todos son el mismo texto.

    Sin copiarlo, escribir en una y cambiar de pestaña enseñaba el texto viejo
    en la otra hasta recargar — que es el fallo del que sale todo esto. Y se
    hace al teclear, no en la vuelta siguiente: la pestaña se cambia en menos.
    """
    guion = script_de("trabajo.html", CONTEXTO)
    assert "hermanas" in guion
    assert "otra.value = nota.value" in guion


def test_el_latido_no_pisa_lo_que_se_esta_escribiendo():
    """Lo que hay en pantalla manda sobre lo que devuelve el servidor.

    Son dos guardas y hacen falta las dos: la nota con cambios sin confirmar, y
    el `textarea` que tiene el cursor dentro —reemplazar su `value` manda el
    cursor al final aunque el texto sea idéntico.
    """
    guion = script_de("trabajo.html", CONTEXTO)
    assert "sucias.has(String(slot))" in guion
    assert "document.activeElement" in guion
    # Y si siguió escribiendo mientras la petición volaba, sigue sucia.
    assert "nota.value === enviado" in guion


def test_el_punto_se_repinta_con_los_textos_del_servidor():
    """Una sola definición de las frases: el primer pintado lo hace Jinja y el
    latido lo rehace el navegador. Dos copias divergen a la primera corrección."""
    from pathlib import Path

    guion = script_de("trabajo.html", CONTEXTO)
    assert "const TITULOS_ESTADO = {" in guion
    assert "Trabajando ahora" in guion  # `tojson` escapa los acentos, no esto
    # Y la frase está escrita UNA vez en la plantilla: la del `{% set %}`.
    plantilla = (Path(__file__).parents[1] / "src/hub/templates/trabajo.html").read_text("utf-8")
    assert plantilla.count("Trabajando ahora") == 1


def test_el_punto_cambia_de_verdad_cuando_el_pulso_dice_otra_cosa(ejecucion):
    """No basta con que pida el pulso: tiene que repintar.

    El fallo silencioso de este cambio es que el HTML se sirva igual de bien, el
    latido corra, y ningún punto se entere nunca — un `dataset` mal escrito
    basta. Aquí se ejecuta y se mira lo que escribió en el DOM.
    """
    assert "trabajando" in ejecucion["clases"]


def test_la_nota_que_cambio_fuera_aparece_sin_recargar(ejecucion):
    """El asistente escribe notas por su cuenta, y la misma nota puede estar
    abierta en dos ventanas. Sin esto se veía la vieja hasta dar F5."""
    assert "lo escribió otro" in ejecucion["valores"]


# ── copiar al seleccionar ─────────────────────────────────────────────────────
#
# 🔴 Esto no existía. Copiar funcionaba en una ventana y en otra no, porque lo
# que copiaba era el navegador por su cuenta y su comportamiento por defecto
# depende de dónde acabe el foco. Una terminal donde copiar funciona A VECES es
# peor que una donde no funciona nunca: se pierde texto creyendo que se tiene.


def _con_seleccion(tmp_path_factory, texto, accion="nodo('marco').disparar('mouseup');",
                   extra=""):
    from arnes_js import ejecutar
    # `globalThis` y no `const`: el guion se inserta dentro de un `try`, y una
    # declaración de bloque no la ve el `Terminal` del arnés, definido fuera.
    guion = f"globalThis.SELECCION = {texto!r};\n{extra}\n" + script_de("trabajo.html", CONTEXTO)
    return ejecutar(guion, tmp_path_factory.mktemp("cp"), PULSO, accion)


def test_soltar_el_raton_copia_lo_seleccionado(tmp_path_factory):
    r = _con_seleccion(tmp_path_factory, "lo que arrastré")
    assert r["portapapeles"] == ["lo que arrastré"]


def test_sin_seleccion_no_se_toca_el_portapapeles(tmp_path_factory):
    """Un clic suelto no puede borrar lo que tuvieras copiado de antes."""
    r = _con_seleccion(tmp_path_factory, "")
    assert r["portapapeles"] == []


def test_si_el_portapapeles_se_niega_hay_plan_B(tmp_path_factory):
    """`navigator.clipboard` puede denegarse. Quedarse ahí sería copiar en
    silencio a ninguna parte, que es el fallo que esto viene a arreglar."""
    r = _con_seleccion(tmp_path_factory, "texto", extra="global.CLIPBOARD_FALLA = true;")
    assert r["portapapeles"] == ["(execCommand)"]


def test_se_copia_al_SOLTAR_y_no_en_cada_pixel_del_arrastre():
    """`onSelectionChange` se dispara en cada píxel: escribir en el portapapeles
    en todos no es gratis, y `writeText` exige un gesto del usuario — soltar el
    botón lo es, arrastrar puede no serlo."""
    guion = script_de("trabajo.html", CONTEXTO)
    assert "'mouseup', copiarSeleccion" in guion
    # Se busca la LLAMADA, no la palabra: el porqué está escrito en el comentario
    # de al lado y encontrarlo ahí no significa que se esté usando.
    assert "term.onSelectionChange(" not in guion


# ── copiar desde DENTRO del panel: OSC 52 ─────────────────────────────────────
#
# 🔴 Lo de arriba sólo cubre la selección que hace el NAVEGADOR, y en un panel
# donde corre Claude Code no hay ninguna: la aplicación pide los eventos de
# ratón —medido, `mouse_any_flag` a SÍ en las tres ventanas—, así que selecciona
# ella y copia con OSC 52. Es también lo que usa tmux con `set-clipboard on`.
#
# xterm.js no trae esa secuencia: la parsea y la descarta. El síntoma fue
# exactamente ese — la terminal decía «N caracteres copiados», porque el mensaje
# lo pinta la aplicación, y al portapapeles no llegaba nada.
#
# Comprobado en un PTY real antes de escribir el manejador: la secuencia
# atraviesa tmux entera y llega al terminal de fuera sin tocarse.


def _osc52(tmp_path_factory, carga):
    from arnes_js import ejecutar
    guion = "globalThis.SELECCION = '';\n" + script_de("trabajo.html", CONTEXTO)
    return ejecutar(
        guion, tmp_path_factory.mktemp("osc"), PULSO,
        f"TERM.parser._osc[52]({carga!r});",
    )


def test_lo_que_copia_la_aplicacion_del_panel_llega_al_portapapeles(tmp_path_factory):
    """`aG9sYSBtdW5kbw==` es «hola mundo» en base64, que es como viaja."""
    r = _osc52(tmp_path_factory, "c;aG9sYSBtdW5kbw==")
    assert r["portapapeles"] == ["hola mundo"]


def test_los_acentos_sobreviven_al_viaje(tmp_path_factory):
    """El base64 lleva UTF-8 dentro, así que `atob` a secas parte los acentos:
    da un byte por carácter y «ó» son dos. Sin `TextDecoder` se copiaría mojibake
    — y copiar mal es peor que no copiar, porque no se nota hasta después."""
    import base64
    carga = base64.b64encode("función · ñandú «cita»".encode()).decode()
    r = _osc52(tmp_path_factory, f"c;{carga}")
    assert r["portapapeles"] == ["función · ñandú «cita»"]


def test_NUNCA_se_contesta_a_quien_PREGUNTA_que_hay_copiado(tmp_path_factory):
    """🔴 `OSC 52 ... ?` pide leer el portapapeles, y la respuesta saldría por el
    PTY. Contestar dejaría que cualquier cosa que corra en un panel se lleve lo
    que el usuario tenga copiado —contraseñas incluidas— sin que se vea nada."""
    r = _osc52(tmp_path_factory, "c;?")
    assert r["portapapeles"] == []
    # Y no se escribe de vuelta por el socket, que es por donde saldría.
    assert r["errores"] == []


def test_un_base64_roto_no_tumba_la_terminal(tmp_path_factory):
    """Llega por el mismo canal que el texto de la pantalla: si un byte suelto
    puede reventar el manejador, cualquier salida rara deja la terminal muerta."""
    r = _osc52(tmp_path_factory, "c;no-es-base64-@@@")
    assert r["portapapeles"] == []
    assert r["errores"] == []


def test_el_manejador_se_registra_para_la_secuencia_52(tmp_path_factory):
    from arnes_js import ejecutar
    guion = "globalThis.SELECCION = '';\n" + script_de("trabajo.html", CONTEXTO)
    r = ejecutar(guion, tmp_path_factory.mktemp("osc"), PULSO)
    assert 52 in r["osc"]
