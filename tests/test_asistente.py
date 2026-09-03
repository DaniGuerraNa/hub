"""El asistente.

🔴 Este archivo cubre la única excepción del hub a la decisión 22 —escribir en
un panel de tmux—. Los tests de `_autorizar` no son de cortesía: si esa
validación se rompe, el hub pega texto y un Enter en un panel de trabajo del usuario
cuyo estado se desconoce, y eso ejecuta comandos reales.
"""

from __future__ import annotations

import json

import pytest

from hub import asistente, tmux
from hub.models import Proyecto


@pytest.fixture
def proyectos(tmp_path):
    asiento = tmp_path / "asistente"
    asiento.mkdir()
    return [
        Proyecto(id="facturador", nombre="Facturador", asiento="/tmp/facturador"),
        Proyecto(id="asistente", nombre="Asistente", tipo="asistente", asiento=str(asiento)),
    ]


@pytest.fixture
def tmux_falso(monkeypatch):
    """Un tmux de mentira que registra lo que se le manda."""

    estado = {
        "paneles": [
            {"session": "asistente", "pane_id": "%9", "comando": "claude",
             "window_idx": 0, "pane_idx": 0, "cwd": "/tmp", "titulo": "✳ listo",
             "activo": True},
            {"session": "Facturador", "pane_id": "%1", "comando": "claude",
             "window_idx": 0, "pane_idx": 0, "cwd": "/tmp", "titulo": "✳ trabajo",
             "activo": True},
        ],
        "titulos": {"%9": "✳ listo", "%1": "✳ trabajo"},
        "pegado": [],
        "sesiones": {"asistente"},
        # Lo que hay escrito en el cuadro de entrada de cada panel. Pegar lo
        # llena y Enter lo vacía, como en la terminal de verdad.
        "cuadro": {"%9": "", "%1": ""},
        "arrancando": set(),
    }

    monkeypatch.setattr(tmux, "listar_paneles",
                        lambda incluir_espejos=False: estado["paneles"])
    monkeypatch.setattr(tmux, "titulo_panel", lambda p: estado["titulos"].get(p))
    monkeypatch.setattr(tmux, "existe_sesion", lambda s: s in estado["sesiones"])

    def pegar(pane_id, texto, enter=True):
        tmux.validar_panel(pane_id)
        estado["pegado"].append((pane_id, texto, enter))
        estado["cuadro"][pane_id] = texto

    def capturar(pane_id):
        if pane_id in estado["arrancando"]:
            return ""   # sin cuadro todavía: la TUI aún no acepta texto
        return _pantalla(estado["cuadro"].get(pane_id, ""))

    monkeypatch.setattr(tmux, "pegar_en_panel", pegar)
    monkeypatch.setattr(tmux, "capturar_panel", capturar)
    monkeypatch.setattr(tmux, "enter_en_panel",
                        lambda p: estado["cuadro"].update({p: ""}))
    monkeypatch.setattr(asistente.time, "sleep", lambda s: None)
    return estado


def _pantalla(dentro: str) -> str:
    """Una captura de panel con la forma real: cuadro entre dos reglas."""
    regla = "─" * 40
    return f"conversación\n{regla}\n❯ {dentro}\n{regla}\n  [Sonnet 4.6] │ asistente"


def _pantalla_de_trabajo(dentro: str) -> str:
    """La OTRA forma real: la caja sólo dibuja su borde de abajo.

    🔴 Medida el 2026-09-02 en un panel de trabajo vivo, a la vez que la de
    arriba en el del asistente:

        panel del asistente   reglas=[41, 43]   prompt=[42]
        panel de trabajo      reglas=[36]       prompt=[35]

    Faltaba en los tests, y por eso `_cuadro` pudo quedarse ciego en un panel
    real sin que nada avisara: el único que se había medido era el del asistente.
    """
    regla = "─" * 40
    return (
        f"❯ {dentro}\n{regla}\n"
        "  [Opus 5] │ personal │ rama\n"
        "  Context ██░░░░░░░░ 23% │ Usage ░░░░░░░░░░ 1%\n"
        "  ⏵⏵ bypass permissions on (shift+tab to cycle)"
    )


# --------------------------------------------------------------------------- #
# 🔴 Regla dura 15 — dónde se permite escribir
# --------------------------------------------------------------------------- #


def test_escribir_en_un_panel_que_no_es_el_del_asistente_se_rechaza(tmux_falso):
    # %1 es un panel de trabajo real del usuario, con `claude` dentro y todo. Que se
    # parezca al del asistente es justo por lo que hace falta comparar por id.
    with pytest.raises(asistente.DestinoNoAutorizado):
        asistente.enviar("hola", pane_id="%1")
    assert tmux_falso["pegado"] == []


def test_sin_asistente_abierto_no_se_escribe_en_ningun_sitio(tmux_falso):
    tmux_falso["paneles"] = [p for p in tmux_falso["paneles"] if p["session"] != "asistente"]
    with pytest.raises(asistente.AsistenteNoDisponible):
        asistente.enviar("hola")
    with pytest.raises(asistente.AsistenteNoDisponible):
        asistente.enviar_comando("clear")
    assert tmux_falso["pegado"] == []


def test_un_pane_id_con_forma_invalida_no_llega_a_tmux(tmux_falso):
    for veneno in ["%9; rm -rf /", "asistente:0", "$(id)", "%", ""]:
        with pytest.raises((asistente.DestinoNoAutorizado, tmux.DestinoInvalido)):
            asistente.enviar("hola", pane_id=veneno)
    assert tmux_falso["pegado"] == []


def test_solo_se_admiten_los_comandos_de_la_lista_cerrada(tmux_falso):
    # `/` abre en Claude Code un menú con todo lo que sabe hacer. Un comando
    # llegado por HTTP no debería poder elegir de esa lista entera.
    for prohibido in ["exit", "quit", "model", "bashes", ""]:
        with pytest.raises(ValueError):
            asistente.enviar_comando(prohibido)
    assert tmux_falso["pegado"] == []


# --------------------------------------------------------------------------- #
# Envío
# --------------------------------------------------------------------------- #


def test_un_mensaje_multilinea_llega_entero_y_como_un_solo_mensaje(tmux_falso):
    # Es la razón de `load-buffer`+`paste-buffer`: Claude Code despacha con
    # Enter, así que un `send-keys` con este texto lo partiría en tres mensajes
    # y el tercero contestaría al primero.
    texto = "revisa la sesión de ayer\n\ny escribe una nota con lo que salió"
    resultado = asistente.enviar(texto)
    assert resultado["enviado"] is True and resultado["despachado"] is True

    assert len(tmux_falso["pegado"]) == 1
    pane_id, enviado, enter = tmux_falso["pegado"][0]
    # El Enter NO va con el pegado: se pulsa después, cuando se ha visto que el
    # texto entró de verdad en el cuadro.
    assert (pane_id, enviado, enter) == ("%9", texto, False)


def test_se_espera_a_ver_el_texto_en_el_cuadro_antes_de_pulsar_enter(
    tmux_falso, monkeypatch
):
    """🔴 El segundo fallo medido, y el más traicionero: comprobar «¿sigue el
    texto en el cuadro?» justo después de pegar da que **no**, porque la TUI
    todavía no ha repintado. El envío se daba por bueno con el mensaje intacto
    en pantalla, y el chat decía `enviado: true` sobre algo que nunca salió."""
    # La TUI tarda dos vueltas en repintar el texto pegado.
    guion = [_pantalla(""), _pantalla(""), _pantalla("hola"), _pantalla("")]
    enters = []
    monkeypatch.setattr(tmux, "capturar_panel",
                        lambda p: guion.pop(0) if guion else _pantalla(""))
    monkeypatch.setattr(tmux, "enter_en_panel", lambda p: enters.append(p))
    monkeypatch.setattr(asistente.time, "sleep", lambda s: None)

    assert asistente.enviar("hola")["despachado"] is True
    # Ni un solo Enter mientras el cuadro se veía vacío.
    assert enters == ["%9"]


def test_si_la_terminal_se_traga_el_enter_se_reintenta_solo_el_enter(tmux_falso,
                                                                     monkeypatch):
    """🔴 El primer fallo medido: en el arranque en frío el pegado entra pero el
    Enter se pierde. El mensaje se queda escrito en el cuadro y la API contesta
    que se envió; nadie se entera de que nunca salió.

    Se reintenta **sólo la tecla**: volver a pegar mandaría el mensaje dos veces,
    que es peor que no mandarlo."""
    enters = []
    monkeypatch.setattr(tmux, "capturar_panel", lambda p: _pantalla("hola pendiente"))
    monkeypatch.setattr(tmux, "enter_en_panel", lambda p: enters.append(p))
    monkeypatch.setattr(asistente.time, "sleep", lambda s: None)

    resultado = asistente.enviar("hola pendiente")

    assert resultado["despachado"] is False   # se dice en voz alta que no salió
    assert enters == ["%9"] * 8               # se insiste con la tecla, no con el texto
    assert len(tmux_falso["pegado"]) == 1     # el texto se pegó UNA sola vez


def test_si_no_se_reconoce_el_cuadro_no_se_miente_diciendo_que_se_envio(
    tmux_falso, monkeypatch
):
    """`_cuadro` lee la pantalla, así que un rediseño de la TUI puede dejarlo
    ciego. Ahí toca decir «no lo pude confirmar», no dar el envío por bueno."""
    # Hay chevron —la TUI está viva— pero no se distinguen las reglas del cuadro.
    monkeypatch.setattr(tmux, "capturar_panel", lambda p: "❯ una pantalla irreconocible")
    monkeypatch.setattr(tmux, "enter_en_panel", lambda p: None)
    monkeypatch.setattr(asistente.time, "sleep", lambda s: None)

    assert asistente.enviar("hola")["despachado"] is False


def test_con_el_asistente_pensando_no_se_solapa_el_mensaje(tmux_falso):
    tmux_falso["titulos"]["%9"] = "⠸ Revisando la sesión"
    resultado = asistente.enviar("otra cosa")
    assert resultado == {"enviado": False, "motivo": "ocupado", "pane_id": "%9"}
    assert tmux_falso["pegado"] == []


def test_un_mensaje_vacio_no_se_envia(tmux_falso):
    with pytest.raises(ValueError):
        asistente.enviar("   \n  ")


def test_el_comando_se_manda_con_su_barra_y_su_argumento(tmux_falso):
    asistente.enviar_comando("compact", "conserva las decisiones")
    assert tmux_falso["pegado"][0][1] == "/compact conserva las decisiones"
    asistente.enviar_comando("clear")
    assert tmux_falso["pegado"][1][1] == "/clear"


# --------------------------------------------------------------------------- #
# Ocupado
# --------------------------------------------------------------------------- #


def test_el_spinner_braille_significa_ocupado_y_el_asterisco_libre(tmux_falso):
    # Verificado muestreando tmux a 0,4 s: los paneles ociosos se quedan quietos
    # en `✳` y el que trabaja cicla por el braille.
    for glifo in ["⠂", "⠐", "⠸", "⠿"]:
        tmux_falso["titulos"]["%9"] = f"{glifo} Trabajando"
        assert asistente.ocupado("%9") is True
    tmux_falso["titulos"]["%9"] = "✳ Listo para lo que sea"
    assert asistente.ocupado("%9") is False


def test_sin_panel_el_estado_es_none_y_no_false(tmux_falso):
    # False autoriza a enviar; None dice que no hay panel del que leer.
    # Colapsarlos haría que el chat escribiera contra un panel muerto.
    tmux_falso["paneles"] = []
    assert asistente.ocupado() is None


def test_un_titulo_sin_glifo_no_se_lee_como_ocupado(tmux_falso):
    tmux_falso["titulos"]["%9"] = "asistente"
    assert asistente.ocupado("%9") is False


# --------------------------------------------------------------------------- #
# Arranque
# --------------------------------------------------------------------------- #


def test_sin_sesion_se_crea_con_claude_como_proceso_de_la_ventana(
    proyectos, tmux_falso, monkeypatch
):
    tmux_falso["paneles"] = []
    tmux_falso["sesiones"] = set()
    creadas = []

    def nueva_sesion(session, ruta=None, nombre_ventana=None, comando=None, entorno=None):
        creadas.append((session, ruta, nombre_ventana, comando))
        tmux_falso["paneles"] = [
            {"session": "asistente", "pane_id": "%42", "comando": "claude",
             "window_idx": 0, "pane_idx": 0, "cwd": ruta, "titulo": "✳",
             "activo": True}
        ]
        tmux_falso["cuadro"]["%42"] = ""

    monkeypatch.setattr(tmux, "nueva_sesion", nueva_sesion)
    resultado = asistente.asegurar_sesion(proyectos)

    assert resultado == {"pane_id": "%42", "session": "asistente",
                         "creada": True, "listo": True}
    # El comando va DENTRO de `new-session`: nunca se teclea en una shell.
    assert creadas[0][3].endswith("claude --model claude-sonnet-5")
    assert creadas[0][2] == "asistente"


def test_el_asistente_arranca_con_su_bin_en_el_path(proyectos):
    """🔴 `tmux new-session -e PATH=…` NO basta, y se comprobó: deja bien la
    variable de la sesión pero el primer panel arranca con el entorno de quien
    lanzó el comando —`hub-web`, bajo systemd, con el venv del hub por delante—.
    El asistente no encontraba su propio comando `hub` y contestaba, muy seguro,
    que «no está en el PATH de esta sesión»."""
    proyecto = asistente.proyecto_asistente(proyectos)
    comando = asistente.comando_de_arranque(proyecto)

    assert comando.startswith("env PATH=")
    assert f"{proyecto.asiento}/bin" in comando
    # `env` se sustituye por `claude`, así que `localizar()` lo sigue viendo.
    assert comando.endswith("claude --model claude-sonnet-5")


def test_no_se_envia_mientras_la_terminal_arranca(tmux_falso):
    """La trampa que se pagó aquí: medido contra tmux, el proceso figura como
    `claude` a los 0,5 s pero el cuadro de entrada no aparece hasta los 2,0 s.
    Lo que se pegue en esa ventana se lo traga la terminal **sin dejar rastro**:
    el mensaje no existe, no falla, no se reintenta. Se pierde y ya."""
    tmux_falso["arrancando"].add("%9")   # aún no hay cuadro de entrada
    assert asistente.enviar("hola") == {
        "enviado": False, "motivo": "arrancando", "pane_id": "%9",
    }
    assert tmux_falso["pegado"] == []


def test_con_la_sesion_ya_abierta_no_se_lanza_un_segundo_claude(proyectos, tmux_falso):
    resultado = asistente.asegurar_sesion(proyectos)
    assert resultado == {"pane_id": "%9", "session": "asistente", "creada": False}


def test_sin_proyecto_de_tipo_asistente_se_dice_en_voz_alta(tmux_falso):
    tmux_falso["paneles"] = []
    solo_normales = [Proyecto(id="c", nombre="C", asiento="/tmp/c")]
    with pytest.raises(asistente.AsistenteNoDisponible, match="tipo: asistente"):
        asistente.asegurar_sesion(solo_normales)


def test_el_asistente_se_declara_por_tipo_y_no_por_una_ruta_cableada(proyectos):
    assert asistente.proyecto_asistente(proyectos).id == "asistente"


# --------------------------------------------------------------------------- #
# Mensajes internos
# --------------------------------------------------------------------------- #


def _msj(rol, texto, uuid="x"):
    return {"uuid": uuid, "rol": rol, "ts": None, "texto": texto, "herramientas": []}


def test_el_mensaje_interno_y_su_respuesta_no_se_pintan_en_el_chat():
    # El usuario: "ese prompt generado no hace falta que me lo muestre porque es para
    # uso interno".
    mensajes = [
        _msj("user", "revisa la sesión de ayer", "1"),
        _msj("assistant", "Lo miro.", "2"),
        _msj("user", asistente.PETICION_DE_COMPACTADO, "3"),
        _msj("assistant", "Conserva las decisiones y tira los tool results.", "4"),
        _msj("user", "gracias", "5"),
    ]
    assert [m["uuid"] for m in asistente.ocultar_internos(mensajes)] == ["1", "2", "5"]


def test_un_interno_sin_respuesta_todavia_tampoco_deja_hueco_visible():
    mensajes = [
        _msj("user", "hola", "1"),
        _msj("user", asistente.PETICION_DE_COMPACTADO, "2"),
    ]
    assert [m["uuid"] for m in asistente.ocultar_internos(mensajes)] == ["1"]


def test_el_rastro_de_un_comando_de_barra_no_se_pinta_en_el_chat():
    """🔴 Pasó de verdad al pulsar «Limpiar»: el `/clear` funcionó —la sesión era
    nueva— y aun así el chat enseñaba estos dos bloques de XML, así que parecía
    que había fallado. Los escribe Claude Code en el transcript con rol `user`.

    Se copian tal cual salieron del transcript real, con su sangrado incluido.
    """
    mensajes = [
        _msj("user",
             "<local-command-caveat>Caveat: The messages below were generated by "
             "the user while running local commands.</local-command-caveat>", "1"),
        _msj("user",
             "<command-name>/clear</command-name>\n"
             "            <command-message>clear</command-message>\n"
             "            <command-args></command-args>", "2"),
    ]
    assert asistente.ocultar_internos(mensajes) == []


def test_el_rastro_de_un_comando_no_se_lleva_por_delante_lo_que_viene_despues():
    """El control negativo, y es el que de verdad importa. A un mensaje interno le
    sigue una respuesta que tampoco debe verse; a un `/clear` no le contesta
    nadie. Si se tratasen igual, limpiar se comería el primer mensaje real de la
    conversación siguiente — y eso ya no sería un fallo cosmético."""
    mensajes = [
        _msj("user", "<command-name>/clear</command-name>", "1"),
        _msj("assistant", "Hola, ¿en qué te ayudo?", "2"),
        _msj("user", "qué se hizo ayer", "3"),
    ]
    assert [m["uuid"] for m in asistente.ocultar_internos(mensajes)] == ["2", "3"]


def test_un_mensaje_que_solo_menciona_una_etiqueta_no_se_oculta():
    """Se ancla al principio del texto a propósito: preguntar por `<command-name>`
    es una conversación legítima, y desaparecer del chat lo que alguien acaba de
    escribir sí sería pérdida visible."""
    mensajes = [
        _msj("user", "¿qué significa <command-name> en el transcript?", "1"),
    ]
    assert [m["uuid"] for m in asistente.ocultar_internos(mensajes)] == ["1"]


def test_se_extrae_la_respuesta_al_interno_para_pasarsela_a_compact():
    mensajes = [
        _msj("user", asistente.PETICION_DE_COMPACTADO, "1"),
        _msj("assistant", "  Conserva el diseño acordado.  ", "2"),
    ]
    assert asistente.extraer_instrucciones(mensajes) == "Conserva el diseño acordado."


def test_sin_interno_no_hay_instrucciones_que_extraer():
    assert asistente.extraer_instrucciones([_msj("user", "hola", "1")]) is None


# --------------------------------------------------------------------------- #
# Ocupación de contexto
# --------------------------------------------------------------------------- #


def test_la_via_exacta_es_el_json_del_statusline(tmp_path, monkeypatch):
    archivo = tmp_path / "asistente-contexto.json"
    archivo.write_text(json.dumps({
        "model": {"id": "claude-sonnet-5"},
        "context_window": {
            "context_window_size": 200000,
            "used_percentage": 43.7,
            "current_usage": {"input_tokens": 2, "cache_read_input_tokens": 87000,
                              "cache_creation_input_tokens": 400, "output_tokens": 900},
        },
    }), encoding="utf-8")
    monkeypatch.setattr(asistente, "ARCHIVO_CONTEXTO", archivo)

    ctx = asistente.contexto()
    assert ctx["porcentaje"] == 43.7
    assert ctx["tokens"] == 87402
    assert ctx["ventana"] == 200000
    assert ctx["origen"] == "statusline"


def test_un_statusline_viejo_se_ignora_y_se_cae_al_transcript(tmp_path, monkeypatch):
    # El dato del statusline sobrevive a la sesión que lo escribió: enseñarlo
    # sería mostrar la ocupación de una conversación que ya no existe.
    import os

    archivo = tmp_path / "asistente-contexto.json"
    archivo.write_text('{"context_window": {"used_percentage": 99.0}}', encoding="utf-8")
    os.utime(archivo, (0, 0))
    monkeypatch.setattr(asistente, "ARCHIVO_CONTEXTO", archivo)

    transcript = tmp_path / "aaaaaaaa-1111-2222-3333-444444444444.jsonl"
    transcript.write_text(json.dumps({
        "type": "assistant", "uuid": "a1", "timestamp": "2026-08-28T10:00:00Z",
        "message": {"model": "claude-sonnet-5", "content": [],
                    "usage": {"input_tokens": 2, "cache_read_input_tokens": 151350,
                              "cache_creation_input_tokens": 686}},
    }), encoding="utf-8")

    ctx = asistente.contexto(transcript)
    assert ctx["origen"] == "transcript"
    assert ctx["tokens"] == 152038
    # El porcentaje se recalcula sobre la ventana del modelo, no se hereda el
    # 99 % del archivo viejo: ese era de una conversación que ya no existe.
    # El archivo viejo no traía modelo, así que su tamaño no se puede aplicar y
    # se cae a la tabla. El 99 % que guardaba NO se hereda: era de otra sesión.
    assert ctx["ventana"] == 1_000_000 and ctx["porcentaje"] == 15.2


def test_sin_ninguna_de_las_dos_vias_el_contexto_es_none(tmp_path, monkeypatch):
    monkeypatch.setattr(asistente, "ARCHIVO_CONTEXTO", tmp_path / "no-existe.json")
    assert asistente.contexto(None) is None


# --------------------------------------------------------------------------- #
# El cuadro de permisos
# --------------------------------------------------------------------------- #


def test_se_detecta_que_claude_esta_pidiendo_permiso(tmux_falso, monkeypatch):
    """Salió probando de verdad: el asistente pidió `hub estado`, Claude Code
    abrió su cuadro de confirmación y el chat se quedó callado —ni ocupado ni
    respondiendo—, porque desde la web no hay forma de pulsar «Yes». Sin
    detectarlo, el síntoma es «el asistente no responde» y nada explica por qué.
    """
    monkeypatch.setattr(tmux, "capturar_panel", lambda p: (
        "● Running 2 bash commands…\n Bash command\n   hub estado\n"
        " This command requires approval\n Do you want to proceed?\n ❯ 1. Yes\n"
    ))
    assert asistente.esperando_confirmacion("%9") is True


def test_una_pantalla_normal_no_se_lee_como_peticion_de_permiso(tmux_falso):
    # Falla hacia False a propósito: una falsa alarma es peor que no avisar.
    assert asistente.esperando_confirmacion("%9") is False


def test_sin_panel_no_se_inventa_que_pide_permiso(tmux_falso):
    tmux_falso["paneles"] = []
    assert asistente.esperando_confirmacion() is False


def test_responder_el_permiso_manda_una_tecla_al_panel_del_asistente(tmux_falso,
                                                                     monkeypatch):
    teclas = []
    monkeypatch.setattr(tmux, "capturar_panel", lambda p: (
        "─" * 40 + "\n Bash command\n\n   hub estado\n   Estado del hub\n\n"
        " Do you want to proceed?\n ❯ 1. Yes\n   2. Yes, and don't ask again\n   3. No\n"
    ))
    monkeypatch.setattr(tmux, "tecla_en_panel", lambda p, t: teclas.append((p, t)))

    assert asistente.responder_confirmacion("si")["ok"] is True
    assert asistente.responder_confirmacion("no")["ok"] is True
    assert teclas == [("%9", "1"), ("%9", "3")]
    # Nunca se pega texto para contestar un menú, y nunca se manda Enter detrás.
    assert tmux_falso["pegado"] == []


def test_no_se_ofrece_el_no_volver_a_preguntar(tmux_falso):
    """La opción 2 de Claude Code amplía sus permisos para siempre. Eso se
    decide editando su `settings.json` a conciencia, no con un botón en un chat."""
    assert set(asistente.RESPUESTAS) == {"si", "no"}
    with pytest.raises(ValueError):
        asistente.responder_confirmacion("siempre")


def test_sin_cuadro_abierto_no_se_teclea_un_digito_suelto(tmux_falso, monkeypatch):
    """Sin menú, ese «1» se escribiría en el prompt y acabaría enviado como un
    mensaje de un solo carácter."""
    teclas = []
    monkeypatch.setattr(tmux, "tecla_en_panel", lambda p, t: teclas.append((p, t)))
    resultado = asistente.responder_confirmacion("si")
    assert resultado["ok"] is False and resultado["motivo"] == "sin-confirmacion-pendiente"
    assert teclas == []


def test_se_extrae_que_permiso_esta_pidiendo(tmux_falso, monkeypatch):
    monkeypatch.setattr(tmux, "capturar_panel", lambda p: (
        "conversación previa\n" + "─" * 40 + "\n Bash command\n\n"
        "   which hub || ls ~/projects/hub/bin/hub\n   Locate hub binary\n\n"
        " Do you want to proceed?\n ❯ 1. Yes\n   3. No\n"
    ))
    c = asistente.confirmacion_pendiente("%9")
    assert c["peticion"] == [
        "Bash command", "which hub || ls ~/projects/hub/bin/hub", "Locate hub binary",
    ]
    assert sorted(c["respuestas"]) == ["no", "si"]


def test_la_via_del_transcript_tambien_da_porcentaje(tmp_path, monkeypatch):
    """El tamaño de la ventana NO caduca aunque el dato sí: es del modelo, no de
    la sesión. Reaprovecharlo deja que la vía de respaldo dé el porcentaje, que
    es lo que se mira para decidir cuándo compactar."""
    import os

    archivo = tmp_path / "asistente-contexto.json"
    archivo.write_text(json.dumps({
        "model": {"id": "claude-sonnet-5"},
        "context_window": {"context_window_size": 1000000, "used_percentage": 99},
    }), encoding="utf-8")
    os.utime(archivo, (0, 0))   # viejo: el porcentaje de dentro ya no vale
    monkeypatch.setattr(asistente, "ARCHIVO_CONTEXTO", archivo)

    transcript = tmp_path / "aaaaaaaa-1111-2222-3333-444444444444.jsonl"
    transcript.write_text(json.dumps({
        "type": "assistant", "uuid": "a1", "timestamp": "2026-08-28T10:00:00Z",
        "message": {"model": "claude-sonnet-5", "content": [],
                    "usage": {"input_tokens": 33, "cache_read_input_tokens": 37000,
                              "cache_creation_input_tokens": 0}},
    }), encoding="utf-8")

    ctx = asistente.contexto(transcript)
    assert ctx["origen"] == "transcript"
    assert ctx["tokens"] == 37033
    assert ctx["ventana"] == 1000000
    assert ctx["porcentaje"] == 3.7


def test_el_tamano_medido_gana_a_la_tabla_cableada(tmp_path, monkeypatch):
    """Una tabla cableada envejece: sale un modelo nuevo, o cambia su ventana, y
    aquí no se entera nadie. Lo que reportó el statusline de ESTA máquina es un
    dato real y manda."""
    archivo = tmp_path / "asistente-contexto.json"
    archivo.write_text(json.dumps({
        "model": {"id": "claude-sonnet-5"},
        "context_window": {"context_window_size": 2000000},   # distinto de la tabla
    }), encoding="utf-8")
    monkeypatch.setattr(asistente, "ARCHIVO_CONTEXTO", archivo)

    assert asistente.tamano_de_ventana("claude-sonnet-5") == 2_000_000


def test_sin_statusline_la_tabla_permite_dar_porcentaje_desde_el_primer_mensaje(
    tmp_path, monkeypatch
):
    """Antes de que el statusline escriba nada no había con qué calcular el
    porcentaje, y el indicador salía en tokens justo al abrir el chat."""
    monkeypatch.setattr(asistente, "ARCHIVO_CONTEXTO", tmp_path / "no-existe.json")

    transcript = tmp_path / "bbbbbbbb-1111-2222-3333-444444444444.jsonl"
    transcript.write_text(json.dumps({
        "type": "assistant", "uuid": "a1", "timestamp": "2026-08-28T10:00:00Z",
        "message": {"model": "claude-sonnet-5", "content": [],
                    "usage": {"input_tokens": 50000}},
    }), encoding="utf-8")

    ctx = asistente.contexto(transcript)
    assert ctx["ventana"] == 1_000_000 and ctx["porcentaje"] == 5.0


def test_no_confundir_las_ventanas_de_dos_modelos(tmp_path, monkeypatch):
    """🔴 Sonnet 4.6 son 200.000 y Sonnet 5 un millón. Aplicar el tamaño del otro
    daría un porcentaje cinco veces equivocado — peor que no dar ninguno justo en
    el número que se usa para decidir si compactar (regla dura 13)."""
    archivo = tmp_path / "asistente-contexto.json"
    archivo.write_text(json.dumps({
        "model": {"id": "claude-sonnet-5"},
        "context_window": {"context_window_size": 1000000},
    }), encoding="utf-8")
    monkeypatch.setattr(asistente, "ARCHIVO_CONTEXTO", archivo)

    # El statusline dice un millón, pero es de OTRO modelo: manda la tabla.
    assert asistente.tamano_de_ventana("claude-sonnet-4-6") == 200_000
    # Y un modelo que nadie conoce no recibe un tamaño inventado.
    assert asistente.tamano_de_ventana("claude-de-pasado-manana") is None
    assert asistente.tamano_de_ventana(None) is None


# ── las dos formas de caja que existen de verdad ──────────────────────────────


def test_el_cuadro_se_lee_en_las_dos_formas_de_caja(monkeypatch):
    """🔴 El fallo que destapó estrenar el canal.

    `_cuadro` buscaba el texto «entre las dos últimas reglas». En un panel que
    sólo dibuja el borde de abajo eso daba `len(reglas) < 2` y devolvía vacío
    **siempre**, así que `despachar` no podía confirmar nada ahí: falso negativo
    garantizado, no intermitente. El relé lo tomaba por «no entregada» y la
    dejaba en cola de reentrega — que habría pegado el texto otra vez.
    """
    for forma, pantalla in (("asistente", _pantalla), ("trabajo", _pantalla_de_trabajo)):
        monkeypatch.setattr(tmux, "capturar_panel", lambda p, s=pantalla: s("hola pendiente"))
        assert asistente._cuadro("%9") == "hola pendiente", f"ciego en la forma «{forma}»"


def test_un_chevron_del_historial_no_se_confunde_con_el_cuadro(monkeypatch):
    """Los mensajes ya enviados también salen con `❯`. El cuadro es el que tiene
    el borde de la caja debajo, y anclar ahí es lo que los distingue sin tener
    que contar líneas desde el final."""
    regla = "─" * 40
    monkeypatch.setattr(
        tmux, "capturar_panel",
        lambda p: f"❯ lo que mandé hace un rato\n  respuesta\n❯ {''}\n{regla}\n  [Opus 5]",
    )
    assert asistente._cuadro("%9") == ""


def test_un_pegado_multilinea_se_confirma_aunque_la_TUI_lo_colapse(monkeypatch):
    """🔴 Medido el 2026-09-02, y era un falso negativo en CADA entrega real.

        cuadro='[Pasted text #1 +6 lines]'    ← lo que la TUI enseña
        busca ='Respuestas de «Prueba» por…'   ← lo que se buscaba

    Claude Code colapsa un pegado de varias líneas en ese marcador, así que
    buscar el texto literal no podía funcionar nunca — y toda respuesta del
    canal es multilínea, porque el marco añade líneas. Lo que se comprueba es
    que el cuadro se VACÍE, que es lo que de verdad significa «salió».
    """
    guion = [_pantalla("[Pasted text #1 +6 lines]"), _pantalla("")]
    enters = []
    monkeypatch.setattr(tmux, "capturar_panel",
                        lambda p: guion.pop(0) if guion else _pantalla(""))
    monkeypatch.setattr(tmux, "enter_en_panel", lambda p: enters.append(p))
    monkeypatch.setattr(asistente.time, "sleep", lambda s: None)

    texto = "Respuestas de «Prueba» por el canal:\n\n— la #90:\n«una»\n\n— la #91:\n«dos»"
    assert asistente.despachar("%9", texto) is True
    assert enters == ["%9"]


def test_si_el_cuadro_no_se_vacia_NUNCA_no_se_da_por_enviado(monkeypatch):
    """El marcador de pegado sigue ahí tras insistir: el Enter se lo tragó la
    TUI. Es el fallo original, y con el criterio nuevo se sigue detectando."""
    enters = []
    monkeypatch.setattr(tmux, "capturar_panel",
                        lambda p: _pantalla("[Pasted text #1 +6 lines]"))
    monkeypatch.setattr(tmux, "enter_en_panel", lambda p: enters.append(p))
    monkeypatch.setattr(asistente.time, "sleep", lambda s: None)

    assert asistente.despachar("%9", "lo que sea\nmultilínea") is False
    assert enters == ["%9"] * 8     # se insiste con la tecla, no con el texto
