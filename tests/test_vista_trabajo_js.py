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
    assert any(u.startswith("/api/sesion/work/ventanas") for u in ejecucion["peticiones"])


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


# ── cerrar la última ventana de una sesión ────────────────────────────────────

def test_la_equis_sale_tambien_con_una_sola_ventana():
    """🔴 Se escondía con `ventanas.length > 1`, o sea justo en las sesiones de
    una ventana — la forma de casi todo lo que se acumula en la bandeja. Desde
    el hub no había ningún camino para cerrarlas."""
    guion = script_de("trabajo.html", CONTEXTO)
    assert "ventanas.length > 1 ?" not in guion
    assert 'data-cerrar="${v.indice}"' in guion


def test_al_cerrar_la_ultima_se_avisa_de_que_muere_la_sesion():
    """tmux mata la sesión al morir su última ventana: decir sólo «la ventana»
    prometería menos de lo que va a pasar."""
    guion = script_de("trabajo.html", CONTEXTO)
    assert "const ultima = ventanas.length === 1;" in guion
    assert "Cerrar la sesión" in guion


def test_tras_cerrar_la_ultima_no_se_queda_mirando_una_sesion_muerta():
    """Recargar pestañas de algo que ya no existe deja el terminal colgado."""
    guion = script_de("trabajo.html", CONTEXTO)
    assert "if (ultima) { location.href = '/trabajo'; return; }" in guion


# ── Las pestañas dicen de quién es cada ventana ──────────────────────────────
#
# 🔴 Esto es lo que él llevaba semanas reportando: «veo una en sin organizar que
# también está en trabajo». La sesión `Personal` tiene tres ventanas, dos del
# slot «Hub - Dev» y una suelta; las tres se pintaban IDÉNTICAS bajo ese rótulo,
# y la suelta salía además abajo en la bandeja. La misma ventana en dos sitios
# diciendo cosas contrarias.
#
# Los arreglos anteriores no la tocaron porque la franja se pintaba llamando a
# `tmux.listar_ventanas` desde la ruta, saltándose `api.py` — y tmux no sabe de
# slots. Se prueba ejecutando el script (regla dura 11), no leyendo el fuente:
# la primera versión de este arreglo declaraba una función `marcaDe` que YA
# existía cien líneas más abajo, y la colisión tumbaba el script entero. La
# página se servía con 200, la franja salía vacía y el terminal en negro.

VENTANAS_MEZCLADAS = [
    {"indice": 0, "etiqueta": "Del slot", "activa": True, "paneles": 1,
     "pertenece": "este", "slot": {"id": 7, "nombre": "back"}},
    {"indice": 1, "etiqueta": "Suelta", "activa": False, "paneles": 1,
     "pertenece": "ninguno", "slot": None},
    {"indice": 2, "etiqueta": "De otro", "activa": False, "paneles": 1,
     "pertenece": "otro", "slot": {"id": 9, "nombre": "Facturas - Main"}},
    {"indice": 3, "etiqueta": "Recién creada", "activa": False, "paneles": 1,
     "pertenece": "nueva", "slot": None},
]


def _franja(tmp_path_factory, ventanas=None):
    from arnes_js import ejecutar
    respuestas = {**PULSO, "/ventanas": ventanas if ventanas is not None
                  else VENTANAS_MEZCLADAS}
    return ejecutar(
        script_de("trabajo.html", CONTEXTO), tmp_path_factory.mktemp("franja"),
        respuestas, "registro.valores.push(nodo('ventanas').innerHTML);")


def test_una_ventana_sin_slot_lo_dice_en_su_pestana(tmp_path_factory):
    """El caso exacto que él reporta. Sin esto, la única forma de enterarse era
    pulsar la pestaña y leer el panel derecho."""
    html = "".join(_franja(tmp_path_factory)["valores"])
    assert "sin slot" in html, "la pestaña suelta no se distingue de las del slot"
    assert "huerfana" in html


def test_las_ventanas_de_otro_slot_de_la_misma_sesion_no_salen(tmp_path_factory):
    """🔴 Decisión 263: cuatro slots en una sesión y cada uno enseñaba las
    ventanas de los otros tres — *«tengo ventanas repetidas»*. Cada una ya
    sale en su slot; aquí sobran."""
    html = "".join(_franja(tmp_path_factory)["valores"])
    assert "De otro" not in html
    assert "Del slot" in html and "Suelta" in html and "Recién creada" in html


def test_si_se_esta_mirando_una_de_otro_slot_su_pestana_sigue_y_dice_de_cual(tmp_path_factory):
    """Esconder la que ocupa el terminal sería mentir sobre qué se ve."""
    from arnes_js import ejecutar
    r = ejecutar(
        script_de("trabajo.html", {**CONTEXTO, "ventana": 2}),
        tmp_path_factory.mktemp("franja"),
        {**PULSO, "/ventanas": VENTANAS_MEZCLADAS},
        "registro.valores.push(nodo('ventanas').innerHTML);")
    html = "".join(r["valores"])
    assert "De otro" in html and "Facturas - Main" in html and "ajena" in html


def test_la_lista_de_ventanas_se_pide_con_el_slot(tmp_path_factory):
    """Sin `?slot=` el hub no sabe cuál es «éste» y da todas por suyas: por eso
    las de los otros slots salían idénticas, sin marca, como repetidas."""
    r = _franja(tmp_path_factory)
    pedidas = [u for u in r["peticiones"] if u.endswith("/ventanas?slot=7")]
    assert pedidas, r["peticiones"]


def test_una_ventana_recien_creada_NO_se_marca_como_huerfana(tmp_path_factory):
    """🔴 El snapshotter puede ir hasta un ciclo por detrás de tmux. Marcar «sin
    slot» una ventana que aún no se ha muestreado sería cambiar una mentira por
    otra, y encima durante los 20 s en que uno acaba de crearla y está mirando."""
    html = "".join(_franja(tmp_path_factory)["valores"])
    (trozo,) = [p for p in html.split('class="pestana') if "Recién creada" in p]
    assert "sin slot" not in trozo


def test_las_ventanas_del_slot_no_llevan_marca(tmp_path_factory):
    """Marcarlas todas sería ruido: la marca sólo significa algo si es la
    excepción."""
    html = "".join(_franja(tmp_path_factory, [VENTANAS_MEZCLADAS[0]])["valores"])
    assert "marca" not in html
    assert "huerfana" not in html and "ajena" not in html


def test_la_franja_le_pregunta_al_hub_y_no_a_tmux(tmp_path_factory):
    """La causa raíz: se pedía la lista a `tmux.listar_ventanas` desde la ruta,
    sin pasar por `api.py`. Con el slot en la URL, el hub puede contestar de
    quién es cada ventana; sin él, seguiría sin poder."""
    r = _franja(tmp_path_factory)
    pedidas = [u for u in r["peticiones"] if "/ventanas" in u]
    assert pedidas, "la franja no pidió las ventanas"
    assert any("slot=" in u for u in pedidas), \
        "no se le dice al hub qué slot anuncia la cabecera"


# ── El botón de ventana nueva ───────────────────────────────────────────────

CLIC_NUEVA = "nodo('ventanas').disparar('click', { target: { id: 'nueva-ventana' } })"


def test_si_el_hub_no_puede_abrir_la_ventana_se_dice_en_pantalla(tmp_path):
    """🔴 El botón ignoraba la respuesta: cuando el hub contestaba que no podía
    —la sesión ya no existe— no pasaba nada y nada lo explicaba. Un botón mudo
    se lee como «está roto», y así se reportó."""
    r = ejecutar(
        script_de("trabajo.html", CONTEXTO), tmp_path,
        {"POST /api/sesion/work/ventanas":
            {"ok": False, "error": "la sesión «work» ya no existe en tmux"}},
        accion=CLIC_NUEVA,
    )

    assert r["errores"] == []
    assert [a["titulo"] for a in r["avisos"]] == ["No se pudo abrir la ventana"]
    assert "ya no existe en tmux" in r["avisos"][0]["mensaje"]


def test_cuando_sale_bien_no_se_avisa_de_nada(tmp_path):
    """El aviso tiene que costar algo: uno que salta siempre se aprende a cerrar
    sin leerlo, y entonces el día que dice algo tampoco se lee."""
    r = ejecutar(
        script_de("trabajo.html", CONTEXTO), tmp_path,
        {"POST /api/sesion/work/ventanas": {"ok": True}},
        accion=CLIC_NUEVA,
    )

    assert r["errores"] == [] and r["avisos"] == []


def test_la_ventana_nueva_se_pide_en_la_ruta_del_slot(tmp_path):
    """Y no donde caiga: el slot dice dónde se trabaja, y esa ruta va en el
    cuerpo. Comprobar sólo la URL no distinguiría pedirla bien de pedirla vacía,
    que es exactamente el caso que acaba abriendo una shell en el hub."""
    r = ejecutar(
        script_de("trabajo.html", CONTEXTO), tmp_path,
        {"POST /api/sesion/work/ventanas": {"ok": True}}, accion=CLIC_NUEVA,
    )

    creaciones = [e for e in r["enviados"] if e["url"].endswith("/ventanas")]
    assert [e["cuerpo"] for e in creaciones] == [{"ruta": "/tmp/demo"}]


# ───────────── por qué no conectó la terminal (decisión 207) ─────────────


def _al_cerrarse_el_socket(respuesta, tmp_path):
    """Dispara el `onclose` del WebSocket y devuelve lo que quedó en pantalla.

    🔴 El arnés contesta lo que contestaría el hub, no lo que le convenga al
    script: `/api/acceso/terminal` con los mismos dos campos que devuelve de
    verdad. Es la lección de la decisión 202 — un arnés complaciente da verde
    sobre el fallo.
    """
    return ejecutar(
        script_de("trabajo.html", CONTEXTO), tmp_path,
        {**PULSO, "/api/acceso/terminal": respuesta},
        # Sin `await`: la acción se inyecta en un contexto síncrono. El arnés
        # vuelca el registro a los ~40 ms, así que leer a los 10 deja de sobra
        # para que se resuelva el `fetch`, que es una microtarea.
        accion="""
          __sockets[0].onclose();
          setTimeout(() => {
            const e = nodo('estado');
            registro.valores.push(['estado', e.innerHTML || e.textContent]);
          }, 10);
        """,
    )


def _anotados(salida, clave):
    """Lo que el guion anotó bajo esa clave.

    `registro.valores` lo comparten varios scripts y no todas sus entradas son
    pares: las hay que son cadenas sueltas, y un `v[0]` a ciegas revienta con
    `IndexError` sobre una cadena vacía.
    """
    return [v[1] for v in salida["valores"]
            if isinstance(v, list) and len(v) == 2 and v[0] == clave]


def _texto_del_estado(salida):
    return _anotados(salida, "estado")[-1]


def test_desde_fuera_y_con_el_interruptor_apagado_lo_dice_y_dice_dónde(tmp_path):
    """🔴 La mentira que se midió en su móvil el 16-sep.

    El WebSocket se rechaza con 403 **antes del `accept()`**, que es lo que pide
    la decisión 163 — pero del apretón de manos fallido al navegador sólo le
    llega un cierre 1006, así que la pantalla decía «desconectado» ante algo
    cerrado a propósito. Estando de viaje eso son horas buscando un fallo que no
    existe.
    """
    texto = _texto_del_estado(
        _al_cerrarse_el_socket({"de_casa": False, "remota_abierta": False}, tmp_path))
    assert "cerrada" in texto
    assert "/acceso" in texto


def test_en_casa_un_corte_sigue_siendo_un_corte(tmp_path):
    """No se puede arreglar la mentira mintiendo al revés."""
    texto = _texto_del_estado(
        _al_cerrarse_el_socket({"de_casa": True, "remota_abierta": False}, tmp_path))
    assert "desconectado" in texto
    assert "cerrada" not in texto


def test_con_el_interruptor_abierto_un_corte_es_un_corte(tmp_path):
    texto = _texto_del_estado(
        _al_cerrarse_el_socket({"de_casa": False, "remota_abierta": True}, tmp_path))
    assert "desconectado" in texto


def test_se_sigue_reintentando_aunque_esté_cerrada(tmp_path):
    """Si él abre el interruptor, la terminal tiene que engancharse sola.

    Por eso la pregunta va DESPUÉS de programar el reintento y no en su lugar.
    """
    salida = _al_cerrarse_el_socket({"de_casa": False, "remota_abierta": False}, tmp_path)
    # El primer reintento va a 1 s (500 · 2¹) y el arnés vuelca a los ~40 ms, así
    # que lo que se comprueba es que quedó PROGRAMADO, no que ya ocurrió.
    assert 1000 in salida["temporizadores"], salida["temporizadores"]


# ───────────── el selector de móvil (decisión 208) ─────────────


def test_el_selector_de_movil_navega_al_slot_elegido(tmp_path):
    """En el móvil el raíl se cambia por un `select`; si no navega, no sirve."""
    r = ejecutar(
        script_de("trabajo.html", CONTEXTO), tmp_path, PULSO,
        accion="""
          const s = nodo('ir-a');
          s.value = '/trabajo?slot=9';
          s.disparar('change');
          registro.valores.push(['href', location.href]);
        """,
    )
    assert _anotados(r, "href") == ["/trabajo?slot=9"]


def test_un_valor_vacío_no_lleva_a_ninguna_parte(tmp_path):
    """Un `optgroup` sin opciones o un navegador raro no deben mandarte a `/`."""
    r = ejecutar(
        script_de("trabajo.html", CONTEXTO), tmp_path, PULSO,
        accion="""
          const s = nodo('ir-a');
          s.value = '';
          s.disparar('change');
          registro.valores.push(['href', location.href]);
        """,
    )
    assert _anotados(r, "href") == [""]


# ───────────── el terminal a solas (decisión 210) ─────────────


def _pulsar_pantalla(tmp_path, veces=1):
    return ejecutar(
        script_de("trabajo.html", CONTEXTO), tmp_path, PULSO,
        accion=f"""
          for (let i = 0; i < {veces}; i++) nodo('pantalla-completa').disparar('click');
          registro.valores.push(['a-solas',
            String(document.body.classList.contains('terminal-sola'))]);
          registro.valores.push(['pulsado',
            nodo('pantalla-completa').atributos
              ? String(nodo('pantalla-completa').atributos['aria-pressed']) : '?']);
        """,
    )


def test_el_boton_le_da_la_pantalla_al_terminal(tmp_path):
    r = _pulsar_pantalla(tmp_path)
    assert _anotados(r, "a-solas") == ["true"]
    assert r["errores"] == []


def test_pulsarlo_otra_vez_devuelve_el_rail(tmp_path):
    assert _anotados(_pulsar_pantalla(tmp_path, veces=2), "a-solas") == ["false"]


def test_la_pantalla_completa_se_le_pide_al_terminal_y_no_al_documento(tmp_path):
    """🔴 Al documento es «la página entera»; al marco es «terminal completa».

    Son cosas distintas y él pidió la segunda: con el documento, el terminal
    seguía siendo una región con su barra, sus pestañas y la nota alrededor.

    Se pide, no se exige — si el navegador la niega (iOS no la da para un
    elemento cualquiera), la capa de CSS ya ha hecho su parte y no se avisa de
    nada, porque no hay nada que el usuario pueda hacer.
    """
    r = _pulsar_pantalla(tmp_path)
    assert r["pantalla"] == ["entrar:lienzo-terminal"], (
        "la pantalla completa no se le pidió al envoltorio del terminal. Al "
        "propio elemento a pantalla completa el navegador le fija el tamaño con "
        "`!important` y no se le puede cambiar: medido en su móvil, seguía en 806"
    )


def test_reajusta_el_terminal_al_cambiar_de_tamaño(tmp_path):
    """Cambiar el alto sin decírselo a xterm y a tmux deja dos tamaños distintos.

    Es el fallo de las decisiones 90 y 93, y su síntoma son letras que no están.
    `reajustar()` avisa al servidor con las filas y columnas nuevas.
    """
    base = ejecutar(script_de("trabajo.html", CONTEXTO), tmp_path, PULSO)
    r = _pulsar_pantalla(tmp_path)
    assert r["errores"] == []
    assert len(r["encajes"]) > len(base["encajes"]), (
        "pulsar el botón no provocó ningún `fit()`: xterm y tmux se quedarían "
        "creyendo tamaños distintos"
    )


# ───────────── el teclado del móvil (decisión 211) ─────────────


def _con_teclado(tmp_path, alto):
    """Abre el teclado a ese alto visible y devuelve lo que hizo la página."""
    return ejecutar(
        script_de("trabajo.html", CONTEXTO), tmp_path, PULSO,
        accion=f"""
          visualViewport.abrirTeclado({alto});
          registro.valores.push(['teclado',
            String(document.body.classList.contains('teclado-abierto'))]);
        """,
    )


def test_al_salir_el_teclado_el_terminal_se_queda_con_lo_visible(tmp_path):
    """🔴 El teclado no encoge la página: la tapa.

    Sin esto, `100dvh` sigue valiendo la pantalla entera y el cursor queda
    debajo del teclado — que es exactamente lo que se veía en su móvil.
    """
    r = _con_teclado(tmp_path, 340)
    assert _anotados(r, "teclado") == ["true"]
    assert ["html:--alto-util", "340px"] in r["variables"]


def test_al_guardar_el_teclado_vuelve_todo(tmp_path):
    r = ejecutar(
        script_de("trabajo.html", CONTEXTO), tmp_path, PULSO,
        accion="""
          visualViewport.abrirTeclado(340);
          visualViewport.abrirTeclado(844);
          registro.valores.push(['teclado',
            String(document.body.classList.contains('teclado-abierto'))]);
        """,
    )
    assert _anotados(r, "teclado") == ["false"]


def test_la_barra_de_direcciones_no_cuenta_como_teclado(tmp_path):
    """También encoge el viewport visual, y mucho menos.

    Sin el umbral, desplazarse por la página escondería el raíl a cada momento.
    """
    assert _anotados(_con_teclado(tmp_path, 800), "teclado") == ["false"]


def test_reajusta_xterm_al_abrirse_el_teclado(tmp_path):
    """Cambiar el alto sin reajustar deja el prompt fuera de la pantalla igual."""
    base = ejecutar(script_de("trabajo.html", CONTEXTO), tmp_path, PULSO)
    r = _con_teclado(tmp_path, 340)
    assert len(r["encajes"]) > len(base["encajes"])
    assert r["errores"] == []


def test_en_pantalla_completa_el_teclado_encoge_el_propio_marco(tmp_path):
    """🔴 El caso que falló: en modo normal funcionaba y en pantalla completa no.

    El navegador saca el elemento a pantalla completa del flujo y lo pinta con
    `position:fixed; inset:0`, pegado a los cuatro bordes de la PANTALLA. Las
    reglas de `body.teclado-abierto` no le llegan y el teclado le pasa por
    encima, así que hay que fijarle el alto a mano — y soltarle el `bottom`, o
    con `inset:0` el `height` no decide nada.
    """
    r = ejecutar(
        script_de("trabajo.html", CONTEXTO), tmp_path, PULSO,
        accion="""
          document.fullscreenElement = nodo('lienzo-terminal');
          visualViewport.abrirTeclado(340);
        """,
    )
    assert ["marco:height", "340px"] in r["variables"]
    assert ["marco:bottom", "auto"] in r["variables"]
    # 🔴 Y el `top`: Chrome no sólo encoge el viewport visual, lo DESPLAZA.
    # Medido en su teléfono: 257 px. Sin compensarlo, el marco se queda anclado
    # arriba del todo y media terminal cae fuera de pantalla.
    assert any(v[0] == "marco:top" for v in r["variables"]), (
        "no se compensó el desplazamiento del viewport visual"
    )


def test_fuera_de_pantalla_completa_el_marco_se_queda_sin_alto_a_mano(tmp_path):
    """Si no, al salir se quedaría clavado al alto que tenía con el teclado."""
    r = ejecutar(
        script_de("trabajo.html", CONTEXTO), tmp_path, PULSO,
        accion="""
          document.fullscreenElement = nodo('lienzo-terminal');
          visualViewport.abrirTeclado(340);
          document.fullscreenElement = null;
          visualViewport.abrirTeclado(844);
        """,
    )
    assert ["marco:height", None] in r["variables"]
    assert ["marco:bottom", None] in r["variables"]
    assert ["marco:top", None] in r["variables"]


# ── la ventana que ya no está ────────────────────────────────────────────────
#
# 🔴 El fallo, de punta a punta: él tenía dos ventanas en `personal-test`, se
# puso en la 1, y la 1 se cerró. `irA()` escribe el índice en la URL, así que
# recargar volvía a pedir la ventana 1 — que ya no existe— y `mostrarPanelDe(1)`
# no casaba con ningún bloque. Sin bloque marcado, el panel derecho no sabe de
# qué slot es esta ventana, y el de programados se quedaba sin poder programar:
# «no se ve qué ventana estás mirando», para siempre y aunque recargara.
#
# Medido en Chrome a 390 px contra el hub de verdad, con y sin el arreglo.

VENTANA_MUERTA = {**CONTEXTO, "ventana": 1}
SOLO_LA_CERO = {"/api/sesion/work/ventanas": [
    {"indice": 0, "nombre": "Codex", "activa": True, "paneles": 1,
     "etiqueta": "Codex", "pertenece": "este", "ancho": 157,
     "slot": {"id": 7, "nombre": "Codex", "proyecto_nombre": "personal-test"}},
]}


def _alternadas(salida, clase):
    return [v for v in salida["alternadas"]
            if isinstance(v, list) and len(v) == 2 and v[0].endswith(":" + clase)]


def test_si_la_ventana_pedida_ya_no_existe_se_cae_a_la_activa(tmp_path):
    """Pedir una ventana muerta no puede dejar la pantalla sin saber dónde está.

    El bloque que se marca tiene que ser el de la ventana 0 —la única que queda—
    y no ninguno: «ninguno» es lo que dejaba el panel derecho mudo.
    """
    salida = ejecutar(
        script_de("trabajo.html", VENTANA_MUERTA), tmp_path, {**PULSO, **SOLO_LA_CERO}
    )
    assert not salida["errores"], salida["errores"]
    encendidas = [v[0] for v in _alternadas(salida, "viendo") if v[1]]
    assert encendidas == ["a:viendo"], salida["alternadas"]


def test_una_ventana_viva_se_respeta(tmp_path):
    """La otra mitad: si la pedida existe, no se toca. Sin esto, el arreglo
    mandaría siempre a la ventana activa de tmux y cambiar de pestaña en el hub
    dejaría de funcionar."""
    dos = {"/api/sesion/work/ventanas": [
        {**SOLO_LA_CERO["/api/sesion/work/ventanas"][0]},
        {"indice": 1, "nombre": "otra", "activa": False, "paneles": 1,
         "etiqueta": "otra", "pertenece": "otro", "ancho": 157, "slot": None},
    ]}
    salida = ejecutar(script_de("trabajo.html", VENTANA_MUERTA), tmp_path, {**PULSO, **dos})
    assert not salida["errores"], salida["errores"]
    encendidas = [v[0] for v in _alternadas(salida, "viendo") if v[1]]
    assert encendidas == ["b:viendo"], salida["alternadas"]


def test_sin_ventanas_se_dice_por_que_no_hay_pestanas(tmp_path):
    """Regla dura 21: las dos salidas mudas de `cargarVentanas` se saltaban la
    línea que marca la ventana, y el síntoma salía tres capas más allá."""
    salida = ejecutar(
        script_de("trabajo.html", CONTEXTO), tmp_path,
        {**PULSO, "/api/sesion/work/ventanas": []},
        "registro.valores.push(['tira', document.getElementById('ventanas').innerHTML]);",
    )
    assert not salida["errores"], salida["errores"]
    (tira,) = [v[1] for v in salida["valores"]
               if isinstance(v, list) and len(v) == 2 and v[0] == "tira"]
    # 🔴 El motivo EXACTO, no un «Sin pestañas» cualquiera. Sin la guarda, el
    # código revienta un par de líneas más abajo y el `catch` acaba pintando
    # «Sin pestañas: no se pudieron pedir…» — o sea que un test que sólo mirara
    # el rótulo pasaría con el arreglo deshecho. Pasó al sabotearlo.
    assert "no tiene ventanas en el último muestreo" in tira, tira[:200]


# ── teclas del móvil e imágenes sobre la terminal (21-oct) ────────────────────


def _con_socket_abierto(tmp_path_factory, accion, respuestas=None):
    return ejecutar(script_de("trabajo.html", CONTEXTO), tmp_path_factory.mktemp("js"),
                    {**PULSO, **(respuestas or {})},
                    accion="__sockets[0].readyState = 1;\n" + accion)


def test_la_barra_del_movil_manda_las_secuencias_de_un_teclado(tmp_path_factory):
    r = _con_socket_abierto(tmp_path_factory, """
      for (const t of ['esc', 'ctrl-c', 'shift-tab', 'arriba'])
        nodo('teclas').querySelectorAll('[data-tecla]')
          .find(b => b.dataset.tecla === t).disparar('click');
    """)
    assert r["errores"] == []
    assert r["tecleado"][-4:] == ["\x1b", "\x03", "\x1b[Z", "\x1b[A"]


def test_una_imagen_soltada_sube_y_su_ruta_se_pega_sin_enter(tmp_path_factory):
    r = _con_socket_abierto(tmp_path_factory, """
      const f = new File([new Uint8Array([137, 80])], 'captura.png', { type: 'image/png' });
      for (const fn of DOC_OYENTES.drop) fn({ preventDefault(){}, stopPropagation(){},
        dataTransfer: { files: [f], types: ['Files'] } });
    """, {"POST /api/terminal/adjuntar": {"ok": True, "ruta": "/casa/intercambio/captura.png"}})
    assert r["errores"] == []
    assert "/api/terminal/adjuntar" in r["peticiones"]
    assert r["pegados"] == ["/casa/intercambio/captura.png "]


def test_pegar_una_imagen_la_adjunta_y_un_texto_lo_deja_a_xterm(tmp_path_factory):
    r = _con_socket_abierto(tmp_path_factory, """
      let detenido = 0;
      const ev = (files) => ({ clipboardData: { files },
        preventDefault(){ detenido++; }, stopPropagation(){} });
      nodo('lienzo-terminal').disparar('paste', ev([]));
      nodo('lienzo-terminal').disparar('paste',
        ev([new File([new Uint8Array([1])], 'image.png', { type: 'image/png' })]));
      globalThis.DETENIDO = detenido;
    """, {"POST /api/terminal/adjuntar": {"ok": True, "ruta": "/casa con espacio/pegado.png"}})
    assert r["errores"] == []
    assert r["peticiones"].count("/api/terminal/adjuntar") == 1
    assert r["pegados"] == ['"/casa con espacio/pegado.png" ']


def test_una_imagen_arrastrada_desde_otra_web_pega_su_url(tmp_path_factory):
    """Sin archivo: trae `text/uri-list`. Se pega la URL, sin subir nada."""
    r = _con_socket_abierto(tmp_path_factory, """
      let detenido = 0;
      const dt = { files: [], types: ['text/uri-list', 'text/html'],
                   getData: (t) => t === 'text/uri-list' ? '# c\\r\\nhttps://x.example/a.png' : '' };
      for (const fn of DOC_OYENTES.dragover) fn({ dataTransfer: dt, preventDefault(){ detenido++; } });
      for (const fn of DOC_OYENTES.drop) fn({ dataTransfer: dt, preventDefault(){}, stopPropagation(){} });
      globalThis.DETENIDO = detenido;
    """)
    assert r["errores"] == []
    assert r["pegados"] == ["https://x.example/a.png "]
    assert "/api/terminal/adjuntar" not in r["peticiones"]


def test_un_clic_en_la_cabecera_marca_que_el_slot_vuelva_tras_un_apagon(tmp_path_factory):
    """Decisión 289: marcarlo se hace donde se trabaja, no en un formulario aparte."""
    r = ejecutar(script_de("trabajo.html", CONTEXTO), tmp_path_factory.mktemp("js"),
                 {**PULSO, "POST /api/slot/7/restaurar": {"ok": True, "restaurar": True}},
                 accion="nodo('vuelve').disparar('click');")
    assert r["errores"] == []
    assert {"url": "/api/slot/7/restaurar", "metodo": "POST",
            "cuerpo": {"restaurar": True}} in r["enviados"]
    assert ["vuelve:on", True] in r["alternadas"]


def test_el_panel_derecho_se_pliega_desde_el_propio_panel_y_se_despliega_desde_el_borde(
        tmp_path_factory):
    """22-oct: el «Nota» de la cabecera ya lo plegaba, pero no se intuía."""
    r = ejecutar(script_de("trabajo.html", CONTEXTO), tmp_path_factory.mktemp("js"), PULSO,
                 accion="nodo('plegar-lado').disparar('click');"
                        "nodo('desplegar-lado').disparar('click');")
    assert r["errores"] == []
    plegados = [v for k, v in r["alternadas"] if k.endswith(":sin-nota")]
    assert plegados[-2:] == [True, False]


def test_el_boton_de_plegar_no_cuenta_como_pestana():
    """Las hojas se eligen con `[data-hoja]`: si el «»» contara, al pulsarlo
    escondería todas y el panel se quedaría en blanco."""
    from pathlib import Path
    estaticos = Path(__file__).resolve().parents[1] / "src" / "hub" / "static"
    for archivo in ("lienzos.js", "consultas.js", "programados.js"):
        texto = (estaticos / archivo).read_text()
        assert "'.pest-lado button[data-hoja]'" in texto, archivo
