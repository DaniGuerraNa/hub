"""El relé de encargos: recibir sin perder nada y no conceder nada por escribir.

🔴 Casi todo lo de aquí prueba lo que **no** pasa. Este canal es el primero del
hub que puede provocar trabajo —una aprobación autoriza gasto y un despliegue
público—, así que lo que hay que fijar no es que funcione: es que un mensaje de
alguien de fuera no consiga por su cuenta nada de lo que no se le dio.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from pathlib import Path

import pytest

from hub import buzon, encargos, rele_encargos, telegram, transcribir


def t(**delta) -> str:
    return (datetime.now(timezone.utc) + timedelta(**delta)).isoformat(timespec="seconds")


class BotFalso:
    """Un bot que apunta lo que se le pidió en vez de mandarlo.

    Guarda las llamadas por separado —textos, fotos, «escribiendo…»— porque lo
    que se comprueba muchas veces es que algo NO se mandó, y una lista única
    obligaría a distinguirlo mirando el contenido.
    """

    def __init__(self, updates=None, cae=False):
        self.textos: list[tuple[int, str]] = []
        self.fotos: list[tuple[int, str, str]] = []
        self.escrituras: list[int] = []
        self.bajados: list[str] = []
        self._updates = list(updates or [])
        self.cae = cae
        self.siguiente_id = 500

    def enviar(self, chat_id, texto):
        if self.cae:
            raise telegram.TelegramCaido("la red no va")
        self.textos.append((int(chat_id), texto))
        self.siguiente_id += 1
        return self.siguiente_id

    def enviar_foto(self, chat_id, ruta, pie=""):
        if self.cae:
            raise telegram.TelegramCaido("la red no va")
        self.fotos.append((int(chat_id), str(ruta), pie))
        self.siguiente_id += 1
        return self.siguiente_id

    def enviar_con_botones(self, chat_id, texto, botones):
        self.con_botones = getattr(self, "con_botones", [])
        self.con_botones.append((int(chat_id), texto, list(botones)))
        return self.enviar(chat_id, texto)

    def pulsado(self, callback_id, texto=""):
        self.pulsados = getattr(self, "pulsados", []) + [callback_id]

    def quitar_botones(self, chat_id, message_id):
        self.sin_botones = getattr(self, "sin_botones", []) + [(int(chat_id), int(message_id))]

    def escribiendo(self, chat_id):
        self.escrituras.append(int(chat_id))

    def descargar(self, file_id, destino):
        if self.cae:
            raise telegram.TelegramCaido("la red no va")
        self.bajados.append(file_id)
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_bytes(b"ogg falso")
        return destino

    def actualizaciones(self, offset=None):
        pendientes, self._updates = self._updates, []
        return pendientes


def update(user_id=77, texto="hola", **extra):
    mensaje = {"message_id": extra.pop("message_id", 9), "from": {
        "id": user_id, "username": "quien", "first_name": "Quien"}}
    if texto:
        mensaje["text"] = texto
    if "voz" in extra:
        mensaje["voice"] = {"file_id": extra.pop("voz"), "duration": extra.pop("segundos", 12)}
    if "responde_a" in extra:
        mensaje["reply_to_message"] = {"message_id": extra.pop("responde_a")}
    return {"update_id": extra.pop("update_id", 1), "message": mensaje}


@pytest.fixture
def sin_construir(monkeypatch):
    """Apaga el arranque automático del constructor.

    🔴 Lo apagan los tests que prueban OTRA cosa, no porque estorbe: construir
    abre una ventana de tmux de verdad, y un test que la abre de propina deja
    sesiones sueltas y prueba dos cosas a la vez. Lo automático tiene sus
    propios tests, y ahí se sustituye el constructor entero.
    """
    monkeypatch.setattr(rele_encargos, "ajustes",
                        lambda: {"construir_al_aprobar": False})


@pytest.fixture
def escena(con):
    """Una persona de alta con su encargo abierto, y el dueño marcado."""
    encargos.anotar_persona(con, 77, "quien", "Quien")
    encargos.editar_persona(con, 77, estado="activo", alias="Rosa")
    encargos.anotar_persona(con, 1, "eldueno", "El Dueño")
    encargos.marcar_dueno(con, 1)
    encargos.crear(con, "encargo-1", 77)
    return "encargo-1"


# ── Escribir al bot no concede nada ─────────────────────────────────────────


def test_un_desconocido_queda_apuntado_y_no_consigue_nada(con):
    """🔴 Aparecer es lo único que pasa, y es lo que permite darle de alta."""
    assert rele_encargos.procesar_mensaje(con, _msg(user_id=99)) == "sin-alta"

    assert encargos.ver_persona(con, 99)["estado"] == "pendiente"
    assert encargos.listar(con) == []


def test_a_quien_no_tiene_alta_se_le_contesta_UNA_vez_en_su_vida(con):
    """Una línea para que no mire un silencio; no una por cada cosa que escriba."""
    bot = BotFalso()
    rele_encargos.procesar_mensaje(con, _msg(user_id=99))

    rele_encargos.saludar_a_los_que_no_pueden(con, bot)
    rele_encargos.saludar_a_los_que_no_pueden(con, bot)

    assert len(bot.textos) == 1
    assert "dadas de alta" in bot.textos[0][1]


def test_el_saludo_no_dice_nada_de_dentro(con):
    bot = BotFalso()
    rele_encargos.procesar_mensaje(con, _msg(user_id=99))
    rele_encargos.saludar_a_los_que_no_pueden(con, bot)

    assert "encargo" not in bot.textos[0][1].lower()


def test_estar_de_alta_sin_encargo_abierto_tampoco_crea_uno(con):
    """Abrir un encargo es un acto suyo: un mensaje no puede provocarlo."""
    encargos.anotar_persona(con, 77, "quien", "Quien")
    encargos.editar_persona(con, 77, estado="activo")

    assert rele_encargos.procesar_mensaje(con, _msg()) == "sin-encargo"
    assert encargos.listar(con) == []


# ── Lo que llega se aparca ──────────────────────────────────────────────────


def test_un_texto_se_aparca_en_el_encargo_de_quien_escribe(con, escena):
    assert rele_encargos.procesar_mensaje(con, _msg(texto="abro a las siete")) == "aparcado"

    assert [m["texto"] for m in buzon.en_cola(con, escena)] == ["abro a las siete"]


def test_un_audio_se_aparca_sin_tocar_la_red(con, escena):
    """🔴 `procesar_mensaje` no baja nada: se guarda el `file_id` y lo baja otro paso.

    Es lo que permite probar sin internet quién puede escribir y dónde cae lo
    que manda, que es donde están casi todos los fallos que importan.
    """
    assert rele_encargos.procesar_mensaje(con, _msg(texto="", voz="AUDIO1")) == "audio"

    guardado = buzon.sin_transcribir(con)
    assert len(guardado) == 1
    assert guardado[0]["adjunto"] == "telegram:AUDIO1"
    assert buzon.en_cola(con, escena) == []      # todavía no tiene texto


def test_un_audio_sin_transcribir_no_se_le_entrega_al_agente(con, escena):
    """Entregarle la ruta de un `.ogg` sería entregarlo y que no lo lea nadie."""
    rele_encargos.procesar_mensaje(con, _msg(texto="", voz="AUDIO1"))

    assert buzon.drenar(con, escena)["resultado"] == "nada"


def test_bajar_un_audio_deja_el_archivo_y_quita_la_marca_de_telegram(con, escena):
    bot = BotFalso()
    rele_encargos.procesar_mensaje(con, _msg(texto="", voz="AUDIO1"))

    assert rele_encargos.bajar_audios(con, bot) == 1
    guardado = buzon.sin_transcribir(con)[0]
    assert not guardado["adjunto"].startswith("telegram:")
    from pathlib import Path
    assert Path(guardado["adjunto"]).is_file()


def test_si_la_red_falla_al_bajar_el_audio_no_se_descarta(con, escena):
    """Telegram guarda el archivo: la vuelta siguiente vuelve a intentarlo."""
    rele_encargos.procesar_mensaje(con, _msg(texto="", voz="AUDIO1"))

    assert rele_encargos.bajar_audios(con, BotFalso(cae=True)) == 0
    guardado = buzon.sin_transcribir(con)[0]
    assert guardado["adjunto"] == "telegram:AUDIO1"
    assert "no se pudo bajar" in guardado["detalle"]


# ── Los tres finales de una transcripción ───────────────────────────────────


def _con_audio_en_disco(con, escena, bot=None):
    rele_encargos.procesar_mensaje(con, _msg(texto="", voz="AUDIO1"))
    rele_encargos.bajar_audios(con, bot or BotFalso())
    return buzon.sin_transcribir(con)[0]


def test_lo_transcrito_entra_en_la_cola_con_los_demas(con, escena, monkeypatch):
    _con_audio_en_disco(con, escena)
    monkeypatch.setattr(transcribir, "transcribir", lambda ruta, aj: "fío a los vecinos")

    assert rele_encargos.transcribir_pendientes(con, {}) == 1
    assert [m["texto"] for m in buzon.en_cola(con, escena)] == ["fío a los vecinos"]


def test_un_audio_del_que_no_se_entiende_nada_se_entrega_diciendolo(con, escena, monkeypatch):
    """🔴 Whisper sin texto es información, no una avería: se le puede pedir que repita."""
    _con_audio_en_disco(con, escena)
    monkeypatch.setattr(transcribir, "transcribir", _levanta(transcribir.NoSeEntendio("nada")))

    rele_encargos.transcribir_pendientes(con, {})

    cola = buzon.en_cola(con, escena)
    assert len(cola) == 1 and "no se pudo transcribir" in cola[0]["texto"]


def test_sin_transcriptor_se_insiste_un_rato_antes_de_rendirse(con, escena, monkeypatch):
    """Un modelo que se está descargando tarda; rendirse a la primera lo perdería."""
    _con_audio_en_disco(con, escena)
    monkeypatch.setattr(transcribir, "transcribir",
                        _levanta(transcribir.SinTranscriptor("falta el modelo")))

    rele_encargos.transcribir_pendientes(con, {})

    assert len(buzon.sin_transcribir(con)) == 1
    assert "modelo" in buzon.sin_transcribir(con)[0]["detalle"]


def test_pasado_el_plazo_el_audio_se_entrega_con_el_hueco_declarado(con, escena, monkeypatch):
    """🔴 Dejar a alguien esperando en silencio es peor que decirle que no se le oyó."""
    _con_audio_en_disco(con, escena)
    con.execute("UPDATE encargo_mensaje SET recibido_en = ?", (t(hours=-1),))
    monkeypatch.setattr(transcribir, "transcribir",
                        _levanta(transcribir.SinTranscriptor("falta el modelo")))

    rele_encargos.transcribir_pendientes(con, {})

    assert buzon.sin_transcribir(con) == []
    assert "no se pudo transcribir" in buzon.en_cola(con, escena)[0]["texto"]


def test_el_audio_se_conserva_aunque_no_se_pudiera_transcribir(con, escena, monkeypatch):
    """Si el transcriptor se arregla mañana, el archivo sigue ahí."""
    mensaje = _con_audio_en_disco(con, escena)
    con.execute("UPDATE encargo_mensaje SET recibido_en = ?", (t(hours=-1),))
    monkeypatch.setattr(transcribir, "transcribir",
                        _levanta(transcribir.SinTranscriptor("falta el modelo")))
    rele_encargos.transcribir_pendientes(con, {})

    from pathlib import Path
    assert Path(mensaje["adjunto"]).is_file()


# ── Aprobar un plan: la acción más privilegiada del sistema ─────────────────


def _con_plan(con, escena):
    buzon.encolar_salida(con, escena, "el plan", clase="plan", user_id=1)
    bot = BotFalso()
    rele_encargos.mandar_salientes(con, bot)
    return encargos.ver(con, escena)["plan_msg"], bot


def test_el_plan_se_recuerda_por_su_message_id(con, escena):
    """Sin esto la aprobación no tendría a qué atarse (decisión 281)."""
    plan_msg, bot = _con_plan(con, escena)

    assert plan_msg == bot.siguiente_id
    assert bot.textos[0][0] == 1          # al dueño, no a quien encargó


def test_aprobar_es_responder_a_ESE_mensaje(con, escena, sin_construir):
    plan_msg, _ = _con_plan(con, escena)

    r = rele_encargos.procesar_mensaje(
        con, _msg(user_id=1, texto="aprobado", responde_a=plan_msg))

    assert r == "aprobado"
    assert encargos.ver(con, escena)["estado"] == "aprobado"


def test_un_si_suelto_en_otra_conversacion_no_aprueba_nada(con, escena):
    """🔴 El fallo que esto evita: un «sí» escrito a otra cosa lanza una construcción."""
    _con_plan(con, escena)

    rele_encargos.procesar_mensaje(con, _msg(user_id=1, texto="aprobado"))

    assert encargos.ver(con, escena)["estado"] == "recogiendo"


def test_quien_no_es_el_dueno_no_aprueba_aunque_responda_al_plan(con, escena):
    plan_msg, _ = _con_plan(con, escena)

    rele_encargos.procesar_mensaje(
        con, _msg(user_id=77, texto="aprobado", responde_a=plan_msg))

    assert encargos.ver(con, escena)["estado"] == "recogiendo"


def test_un_comentario_sobre_el_plan_no_es_ni_un_si_ni_un_no(con, escena):
    """Tratarlo como rechazo perdería la corrección; como sí, construiría otra cosa."""
    plan_msg, _ = _con_plan(con, escena)

    r = rele_encargos.procesar_mensaje(
        con, _msg(user_id=1, texto="quítale los descuentos", responde_a=plan_msg))

    assert r == "comentario"
    assert encargos.ver(con, escena)["estado"] == "recogiendo"
    assert buzon.en_cola(con, escena)[0]["texto"] == "quítale los descuentos"


def test_descartar_tambien_va_atado_al_plan(con, escena):
    plan_msg, _ = _con_plan(con, escena)

    rele_encargos.procesar_mensaje(
        con, _msg(user_id=1, texto="no", responde_a=plan_msg))

    assert encargos.ver(con, escena)["estado"] == "descartado"


# ── Lo que sale ─────────────────────────────────────────────────────────────


def test_un_fallo_de_red_no_da_por_enviado_lo_que_no_salio(con, escena):
    buzon.encolar_salida(con, escena, "¿cómo es un día normal?")

    assert rele_encargos.mandar_salientes(con, BotFalso(cae=True)) == 0
    assert len(buzon.salientes(con)) == 1


def test_lo_enviado_sale_de_la_cola_y_no_se_manda_dos_veces(con, escena):
    bot = BotFalso()
    buzon.encolar_salida(con, escena, "¿cómo es un día normal?")

    rele_encargos.mandar_salientes(con, bot)
    rele_encargos.mandar_salientes(con, bot)

    assert len(bot.textos) == 1


def test_una_muestra_de_estilo_va_como_foto(con, escena, tmp_path):
    """Las imágenes son el mecanismo: quien no sabe describir, elige viendo."""
    muestra = tmp_path / "claro.png"
    muestra.write_bytes(b"png")
    buzon.encolar_salida(con, escena, "¿cuál se parece más?", clase="muestras",
                         adjunto=str(muestra))
    bot = BotFalso()

    rele_encargos.mandar_salientes(con, bot)

    assert len(bot.fotos) == 1 and bot.fotos[0][2] == "¿cuál se parece más?"


def test_lo_del_agente_va_a_quien_encargo_y_no_al_dueno(con, escena):
    bot = BotFalso()
    buzon.encolar_salida(con, escena, "¿cómo es un día normal?")

    rele_encargos.mandar_salientes(con, bot)

    assert bot.textos[0][0] == 77


# ── Que no parezca que nadie escucha ────────────────────────────────────────


def test_mientras_haya_algo_sin_entregar_se_marca_escribiendo(con, escena):
    """Cubre las esperas cortas sin dejar rastro en la conversación."""
    bot = BotFalso()
    buzon.aparcar(con, escena, 77, "hola")

    rele_encargos.atender_esperas(con, bot)

    assert bot.escrituras == [77] and bot.textos == []


def test_pasado_el_umbral_se_avisa_una_sola_vez(con, escena):
    bot = BotFalso()
    buzon.aparcar(con, escena, 77, "hola")
    con.execute("UPDATE encargo_mensaje SET recibido_en = ?", (t(minutes=-5),))

    rele_encargos.atender_esperas(con, bot)
    rele_encargos.atender_esperas(con, bot)

    assert len(bot.textos) == 1 and "par de minutos" in bot.textos[0][1]


def test_mientras_el_agente_piensa_se_sigue_marcando_escribiendo(con, escena):
    """🔴 Decisión 235: entregado no es contestado. Es el hueco del «Hola?»."""
    bot = BotFalso()
    buzon.aparcar(con, escena, 77, "el último, se ve bonito")
    con.execute("UPDATE encargo_mensaje SET estado = 'entregado'")

    rele_encargos.atender_esperas(con, bot)

    assert bot.escrituras == [77]


def test_cuando_el_agente_contesta_la_espera_se_cierra_sin_narrarla(con, escena):
    """La contestación ya es el «ya estoy»: no se añade nada."""
    bot = BotFalso()
    buzon.aparcar(con, escena, 77, "hola")
    con.execute("UPDATE encargo_mensaje SET recibido_en = ?, estado = 'entregado'", (t(minutes=-5),))
    rele_encargos.atender_esperas(con, bot)
    assert len(bot.textos) == 1 and "par de minutos" in bot.textos[0][1]

    buzon.encolar_salida(con, escena, "Perfecto, verde y natural entonces")
    rele_encargos.mandar_salientes(con, bot)
    rele_encargos.atender_esperas(con, bot)

    assert [t_ for _, t_ in bot.textos] == [buzon.AVISO_DE_ESPERA, "Perfecto, verde y natural entonces"]
    assert encargos.ver(con, escena)["avisado_espera"] is None
    assert bot.escrituras == [77], "contestada, ya no se teclea en falso"


def test_sin_espera_no_se_narra_nada(con, escena):
    """Un bot que se narra cada treinta segundos acaba silenciado."""
    bot = BotFalso()
    buzon.aparcar(con, escena, 77, "hola")
    con.execute("UPDATE encargo_mensaje SET estado = 'entregado'")

    rele_encargos.atender_esperas(con, bot)

    assert bot.textos == []


# ── El bucle ────────────────────────────────────────────────────────────────


def test_el_offset_avanza_aunque_el_mensaje_se_descarte(con, escena):
    """Si no, un mensaje que no se puede tratar atasca el canal para siempre."""
    bot = BotFalso(updates=[update(user_id=99, update_id=41)])

    assert rele_encargos.una_vuelta(con, bot, None, {}) == 42


def test_una_vuelta_entera_aparca_lo_que_llega(con, escena):
    bot = BotFalso(updates=[update(texto="abro a las siete", update_id=7)])

    rele_encargos.una_vuelta(con, bot, None, {})

    assert [m["texto"] for m in buzon.en_cola(con, escena)] == ["abro a las siete"]


def _msg(user_id=77, texto="hola", **extra):
    return telegram.partes_con_voz(update(user_id=user_id, texto=texto, **extra))


def _levanta(error):
    def _falla(*_args, **_kwargs):
        raise error
    return _falla


def test_mientras_se_transcribe_un_audio_tambien_se_marca_escribiendo(con, escena):
    """🔴 Medido: un audio de tres minutos tarda 19 s en transcribirse.

    Durante esos 19 s el mensaje no está «en cola» —le falta el texto— pero
    quien lo mandó sí está esperando, y el silencio no distingue en qué paso
    interno se atascó.
    """
    bot = BotFalso()
    rele_encargos.procesar_mensaje(con, _msg(texto="", voz="AUDIO1"))

    rele_encargos.atender_esperas(con, bot)

    assert bot.escrituras == [77]


def test_un_audio_atascado_tambien_acaba_avisando_de_la_espera(con, escena):
    """Si el transcriptor está roto, la espera es real y hay que decirlo."""
    bot = BotFalso()
    rele_encargos.procesar_mensaje(con, _msg(texto="", voz="AUDIO1"))
    con.execute("UPDATE encargo_mensaje SET recibido_en = ?", (t(minutes=-5),))

    rele_encargos.atender_esperas(con, bot)

    assert bot.textos and "par de minutos" in bot.textos[0][1]


# ── Lo que pasa justo después de un «aprobado» ──────────────────────────────


def test_aprobar_pone_a_construir_sin_pedir_un_segundo_permiso(con, escena, monkeypatch):
    """🔴 El gate va antes de gastar, no antes de publicar (decisión 223).

    Pedir un segundo clic convertiría una decisión en dos permisos, que es como
    se acaba aprobando sin mirar.
    """
    from hub import constructor

    abiertos = []
    monkeypatch.setattr(constructor, "abrir_agente",
                        lambda c, e: abiertos.append(e) or {"slot_id": 1})
    plan_msg, _ = _con_plan(con, escena)

    rele_encargos.procesar_mensaje(
        con, _msg(user_id=1, texto="aprobado", responde_a=plan_msg))

    assert abiertos == [escena]


def test_no_se_ponen_dos_constructores_a_la_vez(con, escena, monkeypatch):
    """Compiten por la misma cuota, y cuando algo falla no se sabe cuál fue."""
    from hub import constructor

    monkeypatch.setattr(constructor, "abrir_agente", _levanta(AssertionError("no")))
    encargos.crear(con, "encargo-9", 77)
    encargos.tocar(con, "encargo-9", estado="construyendo")

    assert rele_encargos.empezar_a_construir(con, escena) == "hay-otro"


def test_se_puede_apagar_sin_tocar_codigo(con, escena, monkeypatch):
    from hub import constructor

    monkeypatch.setattr(constructor, "abrir_agente", _levanta(AssertionError("no")))
    monkeypatch.setattr(rele_encargos, "ajustes",
                        lambda: {"construir_al_aprobar": False})

    assert rele_encargos.empezar_a_construir(con, escena) == "apagado"


def test_si_no_se_puede_construir_el_canal_no_se_queda_mudo(con, escena, monkeypatch):
    """🔴 Esto corre dentro del bucle del relé: que no haya tmux no puede
    dejar sin canal a todo el mundo (regla dura 2)."""
    from hub import constructor

    monkeypatch.setattr(constructor, "abrir_agente",
                        _levanta(RuntimeError("tmux no responde")))

    assert rele_encargos.empezar_a_construir(con, escena) == "no-se-pudo"
    assert any("constructor" in r["detalle"] for r in encargos.registro(con))


# ── Publicar lo construido: sin segundo permiso (decisión 228), con tres frenos ───────


def _construido(con, encargo_id="encargo-1", nombre="fiados-del-barrio"):
    """Un encargo que el constructor dio por hecho, con portada y nombre real."""
    if nombre:
        encargos.renombrar(con, encargo_id, nombre)
        encargo_id = nombre
    encargos.tocar(con, encargo_id, estado="construido")
    portada = encargos.carpeta(encargo_id) / "sitio" / "index.html"
    portada.parent.mkdir(parents=True, exist_ok=True)
    portada.write_text("<h1>Los fiados</h1>", encoding="utf-8")
    con.commit()
    return encargo_id


@pytest.fixture
def despliegue(monkeypatch, tmp_path):
    """Un script de despliegue falso que apunta cómo lo llamaron y obedece a un
    archivo para fallar. Lo que se prueba aquí es el relé, no el script: el
    script tiene sus propios tests contra sus propias barreras."""
    rastro = tmp_path / "llamadas"
    falla = tmp_path / "falla"
    script = tmp_path / "desplegar.sh"
    script.write_text(
        "#!/usr/bin/env bash\n"
        f"printf '%s\\n' \"$* caddy=$HUB_CADDY dominio=$HUB_DOMINIO_ENCARGOS\" >> {rastro}\n"
        f"if [ -f {falla} ]; then echo 'el Caddy de ese servidor todavía no lee' >&2; exit 1; fi\n",
        encoding="utf-8")
    monkeypatch.setattr(rele_encargos, "SCRIPT_DESPLIEGUE", script)
    class Falso:
        ajustes = {"despliegue": {"servidor": "vps-prueba", "caddy": "caddy",
                                  "dominio": "ejemplo.com"}}

        def llamadas(self):
            return rastro.read_text(encoding="utf-8").splitlines() if rastro.exists() else []

        def que_falle(self):
            falla.write_text("sí")
    return Falso()


def test_lo_construido_se_publica_solo_y_la_url_llega_a_los_dos(con, escena, despliegue):
    """🔴 «El gate va antes de gastar, no antes de publicar» (decisión 228)."""
    encargo_id = _construido(con)

    assert rele_encargos.desplegar_construidos(con, despliegue.ajustes) == 1

    fila = encargos.ver(con, encargo_id)
    assert fila["estado"] == "publicado"
    assert fila["url"] == "https://fiados-del-barrio.ejemplo.com"
    [llamada] = despliegue.llamadas()
    assert llamada.startswith("fiados-del-barrio ") and llamada.endswith(
        "vps-prueba --va caddy=caddy dominio=ejemplo.com")
    destinos = {m["user_id"] for m in buzon.salientes(con)}
    assert destinos == {None, 1}, "a ella (sin user_id) y al dueño"
    assert any("Ya puedes verlo: https://fiados-del-barrio.ejemplo.com" in m["texto"]
               for m in buzon.salientes(con))


def test_si_la_ficha_sabe_el_nombre_se_le_pone_antes_de_publicar(con, escena, despliegue):
    """«Peluches de Ana» → peluches-de-ana.ejemplo.com, sin que nadie lo teclee."""
    _construido(con, nombre="")
    ficha = encargos.cargar_ficha(con, "encargo-1")
    ficha.responde("nombre", "Peluches de Ana")
    encargos.guardar_ficha(con, ficha)
    con.commit()

    assert rele_encargos.desplegar_construidos(con, despliegue.ajustes) == 1

    assert encargos.ver(con, "encargo-1") is None
    fila = encargos.ver(con, "peluches-de-ana")
    assert fila["estado"] == "publicado"
    assert fila["url"] == "https://peluches-de-ana.ejemplo.com"
    assert despliegue.llamadas()[0].startswith("peluches-de-ana ")


def test_sin_nombre_se_publica_con_el_provisional(con, escena, despliegue):
    """Decisión 232: un enlace feo que funciona vale más que un encargo parado."""
    _construido(con, nombre="")

    assert rele_encargos.desplegar_construidos(con, despliegue.ajustes) == 1
    assert encargos.ver(con, "encargo-1")["url"] == "https://encargo-1.ejemplo.com"


def test_el_nombre_sugerido_no_inventa_ni_pisa(con, escena):
    from hub.encargos import Ficha, nombre_sugerido

    def con_nombre(texto):
        f = Ficha("x"); f.responde("nombre", texto); return f

    assert nombre_sugerido(con, con_nombre("  Lo dé Rosa!  ")) == "lo-de-rosa"
    assert nombre_sugerido(con, con_nombre("Ana")) == "ana"
    assert nombre_sugerido(con, Ficha("x")) is None, "sin nombre no hay sugerencia"
    assert nombre_sugerido(con, con_nombre("¿?")) is None, "nada usable no se convierte en algo"
    assert nombre_sugerido(con, con_nombre("encargo-7")) is None, "no se disfraza de provisional"
    encargos.crear(con, "ana", 77)
    assert nombre_sugerido(con, con_nombre("Ana")) == "ana-2"


def test_si_el_despliegue_falla_se_espera_y_al_dueno_se_le_dice_una_vez(con, escena, despliegue):
    """Un DNS que no resuelve no mejora en cinco segundos, y cada intento es un rsync."""
    encargo_id = _construido(con)
    despliegue.que_falle()

    for _ in range(3):
        assert rele_encargos.desplegar_construidos(con, despliegue.ajustes) == 0

    assert len(despliegue.llamadas()) == 1, "tras el fallo se espera el plazo"
    assert encargos.ver(con, encargo_id)["estado"] == "construido"
    avisos = [m for m in buzon.salientes(con) if m["user_id"] == 1]
    assert len(avisos) == 1 and "no se pudo publicar" in avisos[0]["texto"]
    falla = [r for r in encargos.registro(con, encargo_id=encargo_id) if r["direccion"] == "falla"]
    assert "todavía no lee" in falla[0]["cuerpo"], "el motivo del script queda en el registro"


def test_pasado_el_plazo_se_vuelve_a_intentar(con, escena, despliegue, monkeypatch):
    encargo_id = _construido(con)
    despliegue.que_falle()
    rele_encargos.desplegar_construidos(con, despliegue.ajustes)
    monkeypatch.setattr(rele_encargos, "PLAZO_TRAS_FALLO", timedelta(seconds=0))

    rele_encargos.desplegar_construidos(con, despliegue.ajustes)

    assert len(despliegue.llamadas()) == 2
    assert encargos.ver(con, encargo_id)["estado"] == "construido"


def test_sin_configurar_donde_no_se_publica_nada(con, escena, despliegue):
    """Sin `despliegue:` en encargos.yml se queda en «construido» para hacerlo a mano."""
    _construido(con)
    for ajustes in ({}, {"despliegue": {"automatico": False, **despliegue.ajustes["despliegue"]}},
                    {"despliegue": {"servidor": "vps-prueba"}}):
        assert rele_encargos.desplegar_construidos(con, ajustes) == 0
    assert despliegue.llamadas() == []


def test_una_vuelta_entera_publica_lo_construido(con, escena, despliegue, monkeypatch):
    monkeypatch.setattr(rele_encargos, "ajustes", lambda: despliegue.ajustes)
    encargo_id = _construido(con)
    bot = BotFalso()

    rele_encargos.una_vuelta(con, bot, None, despliegue.ajustes)

    assert encargos.ver(con, encargo_id)["estado"] == "publicado"
    assert any("Ya puedes verlo" in t for _, t in bot.textos)


# ── Cada acción del dueño recibe una confirmación (decisión 231) ────────────


def _al_dueno(con):
    return [m["texto"] for m in buzon.salientes(con) if m["user_id"] == 1]


def test_aprobar_se_confirma_diciendo_que_el_constructor_ya_trabaja(con, escena, monkeypatch):
    from hub import constructor

    monkeypatch.setattr(constructor, "abrir_agente", lambda c, e: {"slot_id": 1})
    plan_msg, _ = _con_plan(con, escena)

    rele_encargos.procesar_mensaje(con, _msg(user_id=1, texto="aprobado", responde_a=plan_msg))

    (texto,) = _al_dueno(con)
    assert "aprobado" in texto and "constructor ya está trabajando" in texto


def test_si_el_constructor_no_arranca_la_confirmacion_lo_dice(con, escena, monkeypatch):
    """Lo que pasó de verdad: el constructor murió y el dueño se quedó sin saberlo."""
    from hub import constructor

    monkeypatch.setattr(constructor, "abrir_agente", _levanta(RuntimeError("murió al arrancar")))
    plan_msg, _ = _con_plan(con, escena)

    rele_encargos.procesar_mensaje(con, _msg(user_id=1, texto="aprobado", responde_a=plan_msg))

    (texto,) = _al_dueno(con)
    assert "no pude arrancar el constructor" in texto
    assert encargos.ver(con, escena)["estado"] == "aprobado"


def test_a_ella_se_le_dice_que_se_esta_construyendo_o_que_se_queda_en_pausa(con, escena, monkeypatch):
    """Decisión 233: quien espera es ella, y el silencio se lee como un fallo."""
    from hub import constructor

    monkeypatch.setattr(constructor, "abrir_agente", lambda c, e: {"slot_id": 1})
    plan_msg, _ = _con_plan(con, escena)
    rele_encargos.procesar_mensaje(con, _msg(user_id=1, texto="aprobado", responde_a=plan_msg))
    a_ella = [m["texto"] for m in buzon.salientes(con) if m["user_id"] is None]
    assert any("se está construyendo" in t for t in a_ella)

    encargos.tocar(con, escena, estado="propuesta")
    rele_encargos.procesar_mensaje(con, _msg(user_id=1, texto="no", responde_a=plan_msg))
    a_ella = [m["texto"] for m in buzon.salientes(con) if m["user_id"] is None]
    assert any("se queda en pausa" in t for t in a_ella)


def test_descartar_y_comentar_tambien_se_confirman(con, escena):
    plan_msg, _ = _con_plan(con, escena)
    rele_encargos.procesar_mensaje(con, _msg(user_id=1, texto="quítale esto", responde_a=plan_msg))
    rele_encargos.procesar_mensaje(con, _msg(user_id=1, texto="no", responde_a=plan_msg))

    comentario, descarte = _al_dueno(con)
    assert "responde «aprobado» a ese mismo mensaje" in comentario
    assert "descartado" in descarte


def test_un_aprobado_suelto_del_dueno_no_aprueba_pero_se_le_explica(con, escena):
    """🔴 n14 no cambia: sigue sin aprobar. Lo que cambia es que se entera."""
    _con_plan(con, escena)
    encargos.tocar(con, escena, estado="propuesta")

    r = rele_encargos.procesar_mensaje(con, _msg(user_id=1, texto="aprobado"))

    assert r == "sin-encargo"
    assert encargos.ver(con, escena)["estado"] == "propuesta"
    (texto,) = _al_dueno(con)
    assert "RESPONDER al mensaje del plan" in texto


def test_un_mensaje_cualquiera_del_dueno_sin_encargo_no_provoca_nada(con, escena):
    _con_plan(con, escena)
    rele_encargos.procesar_mensaje(con, _msg(user_id=1, texto="hola qué tal"))
    assert _al_dueno(con) == []


def test_lo_aprobado_que_esperaba_turno_arranca_cuando_hay_hueco(con, escena, monkeypatch):
    """«Empieza solo en cuanto aquel acabe» tiene que ser verdad."""
    from hub import constructor

    abiertos = []
    monkeypatch.setattr(constructor, "abrir_agente", lambda c, e: abiertos.append(e) or {})
    encargos.crear(con, "encargo-9", 77)
    encargos.tocar(con, "encargo-9", estado="construyendo")
    encargos.tocar(con, escena, estado="aprobado")

    assert rele_encargos.construir_lo_aprobado(con, {}) is None      # hay otro
    encargos.tocar(con, "encargo-9", estado="construido")
    assert rele_encargos.construir_lo_aprobado(con, {}) == "construyendo"
    assert abiertos == [escena]


def test_tras_un_fallo_al_abrir_el_constructor_se_espera_antes_de_reintentar(con, escena, monkeypatch):
    from hub import constructor

    intentos = []
    monkeypatch.setattr(constructor, "abrir_agente",
                        lambda c, e: intentos.append(e) or (_ for _ in ()).throw(RuntimeError("no")))
    encargos.tocar(con, escena, estado="aprobado")

    rele_encargos.construir_lo_aprobado(con, {})
    rele_encargos.construir_lo_aprobado(con, {})
    assert len(intentos) == 1
    monkeypatch.setattr(rele_encargos, "PLAZO_TRAS_FALLO", timedelta(seconds=0))
    rele_encargos.construir_lo_aprobado(con, {})
    assert len(intentos) == 2


# ── Lo que dice tras ver lo publicado: otra ronda, y la decide él (234) ─────


def _publicado(con, escena):
    encargos.tocar(con, escena, estado="publicado", url="https://encargo-1.ejemplo.com")
    con.commit()


def test_lo_que_dice_tras_ver_su_pagina_se_aparca_y_a_el_se_le_pregunta_una_vez(con, escena):
    _publicado(con, escena)

    assert rele_encargos.procesar_mensaje(con, _msg(texto="¿se puede añadir un carrusel?")) == "cambios"
    rele_encargos.mandar_salientes(con, BotFalso())          # fija plan_msg
    assert rele_encargos.procesar_mensaje(con, _msg(texto="con tres fotos")) == "cambios"

    assert [m["texto"] for m in buzon.en_cola(con, escena)] == [
        "¿se puede añadir un carrusel?", "con tres fotos"]
    assert encargos.ver(con, escena)["estado"] == "publicado", "no se reabre solo"
    preguntas = [r for r in encargos.registro(con, encargo_id=escena)
                 if r["detalle"] == "mensaje del agente (plan)"]
    assert len(preguntas) == 1, "a él se le pregunta una vez, no una por mensaje"


def test_otra_ronda_reabre_la_entrevista_con_lo_que_pidio_esperando(con, escena, monkeypatch):
    from hub import entrevistador

    abiertos, cerrados = [], []
    monkeypatch.setattr(entrevistador, "abrir_agente", lambda c, e: abiertos.append(e) or {"slot_id": 1})
    monkeypatch.setattr(entrevistador, "cerrar_agentes", lambda c, e: cerrados.append(e) or [])
    _publicado(con, escena)
    rele_encargos.procesar_mensaje(con, _msg(texto="¿se puede añadir un carrusel?"))
    rele_encargos.mandar_salientes(con, BotFalso())
    plan_msg = encargos.ver(con, escena)["plan_msg"]

    r = rele_encargos.procesar_mensaje(con, _msg(user_id=1, texto="otra ronda", responde_a=plan_msg))

    assert r == "otra-ronda" and abiertos == [escena] and cerrados == [escena]
    fila = encargos.ver(con, escena)
    assert fila["estado"] == "recogiendo" and fila["ronda"] == 2
    assert fila["url"] == "https://encargo-1.ejemplo.com", "se vuelve a publicar en la misma"
    assert [m["texto"] for m in buzon.en_cola(con, escena)] == ["¿se puede añadir un carrusel?"]
    assert any("Vale, le entramos" in m["texto"] for m in buzon.salientes(con))


def test_un_no_deja_lo_publicado_como_esta(con, escena):
    _publicado(con, escena)
    rele_encargos.procesar_mensaje(con, _msg(texto="¿y un carrusel?"))
    rele_encargos.mandar_salientes(con, BotFalso())
    plan_msg = encargos.ver(con, escena)["plan_msg"]

    assert rele_encargos.procesar_mensaje(con, _msg(user_id=1, texto="no", responde_a=plan_msg)) == "sin-ronda"
    fila = encargos.ver(con, escena)
    assert fila["estado"] == "publicado" and fila["plan_msg"] is None
    assert any("se queda como está" in m["texto"] for m in buzon.salientes(con))


def test_a_quien_ya_tiene_su_pagina_no_se_le_pide_paciencia(con, escena):
    _publicado(con, escena)
    rele_encargos.procesar_mensaje(con, _msg(texto="¿y un carrusel?"))
    con.execute("UPDATE encargo_mensaje SET recibido_en = ?", (t(minutes=-5),))
    bot = BotFalso()

    rele_encargos.atender_esperas(con, bot)

    assert bot.escrituras == [] and all(buzon.AVISO_DE_ESPERA != t_ for _, t_ in bot.textos)


def test_al_publicar_se_cierran_los_agentes_antes_de_renombrar(con, escena, despliegue, monkeypatch):
    from hub import entrevistador

    cerrados = []
    monkeypatch.setattr(entrevistador, "cerrar_agentes", lambda c, e: cerrados.append(e) or [])
    _construido(con, nombre="")
    ficha = encargos.cargar_ficha(con, "encargo-1"); ficha.responde("nombre", "La Tienda")
    encargos.guardar_ficha(con, ficha); con.commit()

    rele_encargos.desplegar_construidos(con, despliegue.ajustes)

    # Se cerró con el id VIEJO: o sea, antes de renombrar y de mover la carpeta.
    assert cerrados == ["encargo-1"]
    assert encargos.ver(con, "la-tienda")["estado"] == "publicado"


def test_al_publicar_se_olvida_el_plan_msg_para_que_lo_que_diga_despues_te_pregunte(con, escena, despliegue):
    """Lo que pasó con la primera persona real: su «no vi ni una pizca de rosa»
    se aparcó en silencio porque el `plan_msg` de la ronda 1 seguía puesto."""
    encargo_id = _construido(con)
    encargos.tocar(con, encargo_id, plan_msg=25)
    con.commit()
    rele_encargos.desplegar_construidos(con, despliegue.ajustes)
    assert encargos.ver(con, encargo_id)["plan_msg"] is None

    rele_encargos.procesar_mensaje(con, _msg(texto="no vi ni una pizca de rosa"))

    assert any(m["clase"] == "plan" and m["user_id"] == 1 for m in buzon.salientes(con))
    assert any("Anotado" in m["texto"] for m in buzon.salientes(con) if m["user_id"] is None)


# ── Botones bajo las preguntas (decisión 237) ───────────────────────────────


def _pulsa(user_id, dato, message_id, update_id=5):
    return {"update_id": update_id, "callback_query": {
        "id": "cb-1", "data": dato,
        "from": {"id": user_id, "username": "eldueno", "first_name": "El Dueño"},
        "message": {"message_id": message_id, "chat": {"id": user_id}}}}


def test_la_pregunta_de_otra_ronda_lleva_botones(con, escena):
    _publicado(con, escena)
    rele_encargos.procesar_mensaje(con, _msg(texto="¿y un carrusel?"))
    bot = BotFalso()
    rele_encargos.mandar_salientes(con, bot)
    ((chat, _, botones),) = bot.con_botones
    # A él no se le ofrece «Implementar» aquí: eso lo decide ella (245).
    assert chat == 1 and [d for _, d in botones] == ["otra ronda", "no"]


def test_pulsar_aprobar_aprueba_como_si_hubiera_respondido_y_retira_los_botones(con, escena, monkeypatch):
    from hub import constructor

    monkeypatch.setattr(constructor, "abrir_agente", lambda c, e: {"slot_id": 1})
    encargos.tocar(con, escena, estado="propuesta")
    plan_msg, bot = _con_plan(con, escena)

    rele_encargos.una_vuelta(con, BotFalso([_pulsa(1, "aprobado", plan_msg)]), None, {})

    assert encargos.ver(con, escena)["estado"] == "aprobado"


def test_al_pulsar_se_cierra_la_pulsacion_y_se_quitan_los_botones(con, escena, monkeypatch):
    from hub import constructor

    monkeypatch.setattr(constructor, "abrir_agente", lambda c, e: {"slot_id": 1})
    encargos.tocar(con, escena, estado="propuesta")
    plan_msg, _ = _con_plan(con, escena)
    bot = BotFalso([_pulsa(1, "aprobado", plan_msg)])

    rele_encargos.una_vuelta(con, bot, None, {})

    assert bot.pulsados == ["cb-1"] and bot.sin_botones == [(1, plan_msg)]


def test_pulsar_dos_veces_no_aprueba_dos_veces_ni_abre_otro_constructor(con, escena, monkeypatch):
    """🔴 Antes, un segundo «aprobado» devolvía el encargo a «aprobado» desde
    «construyendo» y el relé abría OTRO constructor."""
    from hub import constructor

    abiertos = []
    monkeypatch.setattr(constructor, "abrir_agente", lambda c, e: abiertos.append(e) or {"slot_id": 1})
    encargos.tocar(con, escena, estado="propuesta")
    plan_msg, _ = _con_plan(con, escena)
    rele_encargos.procesar_mensaje(con, _msg(user_id=1, texto="aprobado", responde_a=plan_msg))
    encargos.tocar(con, escena, estado="construyendo")

    r = rele_encargos.procesar_mensaje(con, _msg(user_id=1, texto="aprobado", responde_a=plan_msg))

    assert r == "ya-resuelto" and abiertos == [escena]
    assert encargos.ver(con, escena)["estado"] == "construyendo"
    assert any("ya está en «construyendo»" in m["texto"] for m in buzon.salientes(con))


def test_quien_no_es_el_dueno_no_aprueba_ni_pulsando(con, escena):
    encargos.tocar(con, escena, estado="propuesta")
    plan_msg, _ = _con_plan(con, escena)

    rele_encargos.una_vuelta(con, BotFalso([_pulsa(77, "aprobado", plan_msg)]), None, {})

    assert encargos.ver(con, escena)["estado"] == "propuesta"


# ── Implementar: de la maqueta al sistema (decisión 244) ─────────────────────


def test_la_url_de_la_maqueta_le_lleva_a_ella_los_botones_de_asi_la_quiero(con, escena, despliegue):
    """Decisión 245: que la maqueta está lista lo dice quien la usa."""
    _construido(con)
    rele_encargos.desplegar_construidos(con, despliegue.ajustes)
    bot = BotFalso()
    rele_encargos.mandar_salientes(con, bot)
    ((chat, _, botones),) = bot.con_botones
    assert chat == 77 and [d for _, d in botones] == ["maqueta-lista", "maqueta-cambiar"]


def test_asi_la_quiero_le_pregunta_a_el_si_implementa_y_el_aprueba(con, escena, monkeypatch):
    from hub import implementador

    abiertos = []
    monkeypatch.setattr(implementador, "abrir_agente",
                        lambda c, e: abiertos.append(e) or {"pane_id": "%1"})
    _publicado(con, escena)

    assert rele_encargos.procesar_mensaje(
        con, telegram.boton_pulsado(_pulsa(77, "maqueta-lista", 900))) == "maqueta-lista"
    bot = BotFalso()
    rele_encargos.mandar_salientes(con, bot)
    ((chat, texto, botones),) = bot.con_botones
    assert chat == 1 and "convertimos" in texto
    assert [d for _, d in botones] == ["implementar", "no"]
    assert encargos.ver(con, escena)["etapa"] == "maqueta", "todavía no: él no ha dicho nada"
    plan_msg = encargos.ver(con, escena)["plan_msg"]

    assert rele_encargos.procesar_mensaje(
        con, telegram.boton_pulsado(_pulsa(1, "implementar", plan_msg))) == "implementando"
    assert encargos.ver(con, escena)["etapa"] == "sistema" and abiertos == [escena]


def test_quiero_cambiar_algo_solo_le_pide_que_cuente(con, escena):
    _publicado(con, escena)
    assert rele_encargos.procesar_mensaje(
        con, telegram.boton_pulsado(_pulsa(77, "maqueta-cambiar", 900))) == "maqueta-cambiar"
    bot = BotFalso()
    rele_encargos.mandar_salientes(con, bot)
    assert not getattr(bot, "con_botones", []) and [c for c, _ in bot.textos] == [77]


def test_un_audio_tras_publicar_se_le_pregunta_a_el_con_el_texto_y_no_con_un_audio(con, escena, monkeypatch, tmp_path):
    """Pasó de verdad el 19-sep: a él le llegó «(un audio)» y no había con qué
    decidir. La pregunta sale cuando el audio ya es texto."""
    _publicado(con, escena)
    assert rele_encargos.procesar_mensaje(con, _msg(texto="", voz="v1")) == "cambios"
    bot = BotFalso()
    rele_encargos.mandar_salientes(con, bot)
    assert not getattr(bot, "con_botones", []), "sin texto no hay pregunta"
    assert [c for c, _ in bot.textos] == [77]

    # El relé bajó el audio: ahora está en disco y se transcribe.
    audio = tmp_path / "v1.ogg"; audio.write_bytes(b"ogg")
    con.execute("UPDATE encargo_mensaje SET adjunto = ? WHERE clase = 'audio'", (str(audio),))
    monkeypatch.setattr(transcribir, "transcribir", lambda ruta, ajustes: "hay que ajustar el selector")
    rele_encargos.transcribir_pendientes(con, {})
    rele_encargos.mandar_salientes(con, bot)
    ((chat, texto, botones),) = bot.con_botones
    assert chat == 1 and "hay que ajustar el selector" in texto and "(un audio)" not in texto
    assert [d for _, d in botones] == ["otra ronda", "no"]


def test_sobre_un_sistema_la_url_no_lleva_botones_de_maqueta(con, escena, despliegue):
    _construido(con)
    encargos.tocar(con, "fiados-del-barrio", etapa="sistema"); con.commit()
    rele_encargos.desplegar_construidos(con, despliegue.ajustes)
    bot = BotFalso()
    rele_encargos.mandar_salientes(con, bot)
    assert not getattr(bot, "con_botones", [])


def test_un_plan_aprobado_sobre_un_sistema_lo_hace_el_implementador(con, escena, monkeypatch):
    from hub import constructor, implementador

    quien = []
    monkeypatch.setattr(implementador, "abrir_agente", lambda c, e: quien.append("implementador") or {})
    monkeypatch.setattr(constructor, "abrir_agente", lambda c, e: quien.append("constructor") or {})
    encargos.tocar(con, escena, etapa="sistema", estado="aprobado"); con.commit()

    assert rele_encargos.empezar_a_construir(con, escena) == "implementando"
    assert quien == ["implementador"]


def test_al_publicar_un_sistema_va_la_app_y_la_contrasena_sale_una_sola_vez(con, escena, despliegue):
    from hub import implementador

    encargo_id = _construido(con)
    app_ = encargos.carpeta(encargo_id) / "app"
    (app_ / "static").mkdir(parents=True)
    (app_ / "main.py").write_text("app = None", encoding="utf-8")
    encargos.tocar(con, encargo_id, etapa="sistema"); con.commit()

    assert rele_encargos.desplegar_construidos(con, despliegue.ajustes) == 1

    (llamada,) = despliegue.llamadas()
    assert str(app_) in llamada and "/sitio" not in llamada
    assert implementador.tiene_acceso(encargo_id)
    bot = BotFalso()
    rele_encargos.mandar_salientes(con, bot)
    a_ella = [t for chat, t in bot.textos if chat == 77]
    assert any("contraseña «" in t and f"usuario «{encargo_id}»" in t for t in a_ella)
    # Regla dura 5: la contraseña no queda en la base ni en la carpeta.
    clave = next(t for t in a_ella if "contraseña «" in t).split("contraseña «")[1].split("»")[0]
    assert clave not in (encargos.carpeta(encargo_id) / implementador.ACCESO).read_text()
    assert not con.execute("SELECT 1 FROM encargo WHERE nota LIKE ?", (f"%{clave}%",)).fetchone()

    # Segundo despliegue (una ronda): mismo acceso, sin contraseña nueva.
    encargos.tocar(con, encargo_id, estado="construido"); con.commit()
    bot2 = BotFalso()
    rele_encargos.desplegar_construidos(con, despliegue.ajustes)
    rele_encargos.mandar_salientes(con, bot2)
    assert any("de siempre" in t for chat, t in bot2.textos if chat == 77)


def test_abrir_otra_ronda_no_pide_paciencia_antes_del_vale_le_entramos(con, escena, monkeypatch):
    """Visto en el ensayo del 19-sep: él tardó en pulsar «otra ronda», y en la
    misma vuelta le salió a ella «dame un par de minutos» antes del «vale, le
    entramos». El acuse ya es esa línea."""
    from hub import entrevistador

    monkeypatch.setattr(entrevistador, "abrir_otra_ronda", lambda c, e: {"ronda": 2})
    _publicado(con, escena)
    rele_encargos.procesar_mensaje(con, _msg(texto="¿y la semana entera?"))
    rele_encargos.mandar_salientes(con, BotFalso())
    plan_msg = encargos.ver(con, escena)["plan_msg"]
    con.execute("UPDATE encargo_mensaje SET recibido_en = ?", (t(minutes=-3),)); con.commit()

    rele_encargos.procesar_mensaje(con, telegram.boton_pulsado(_pulsa(1, "otra ronda", plan_msg)))
    bot = BotFalso()
    rele_encargos.mandar_salientes(con, bot)
    rele_encargos.atender_esperas(con, bot)

    a_ella = [t_ for chat, t_ in bot.textos if chat == 77]
    assert any("le entramos" in t_ for t_ in a_ella)
    assert not any(t_ == buzon.AVISO_DE_ESPERA for t_ in a_ella)


def test_si_es_de_confianza_lo_que_dice_tras_ver_su_pagina_abre_la_ronda_sola(con, escena, monkeypatch):
    """La decisión de cuándo hay otra versión es de quien usa la maqueta (236+245):
    a él sólo se le cuenta."""
    from hub import entrevistador

    abiertas = []
    monkeypatch.setattr(entrevistador, "abrir_otra_ronda",
                        lambda c, e: abiertas.append(e) or {"ronda": 2})
    encargos.editar_persona(con, 77, de_confianza=1)
    _publicado(con, escena)

    assert rele_encargos.procesar_mensaje(con, _msg(texto="que el total salga en grande")) == "cambios"
    bot = BotFalso()
    rele_encargos.mandar_salientes(con, bot)

    assert abiertas == [escena]
    assert not getattr(bot, "con_botones", []), "a él no se le pregunta"
    a_el = [t_ for c, t_ in bot.textos if c == 1]
    assert any("se abrió sola" in t_ and "salga en grande" in t_ for t_ in a_el)
    assert any("le entramos" in t_ for c, t_ in bot.textos if c == 77)


def test_se_apunta_donde_quedo_el_audio_y_no_donde_se_pidio(con, escena):
    """El chat web guarda webm con su extensión de verdad; apuntar el .ogg pedido
    dejó el primer audio real de la web como «no existe» para el transcriptor."""
    class BotWebm(BotFalso):
        def descargar(self, file_id, destino):
            destino = Path(destino).with_suffix(".webm")
            destino.parent.mkdir(parents=True, exist_ok=True)
            destino.write_bytes(b"opus")
            return destino

    rele_encargos.procesar_mensaje(con, _msg(texto="", voz="web:a.webm"))
    assert rele_encargos.bajar_audios(con, BotWebm()) == 1
    fila = con.execute("SELECT adjunto FROM encargo_mensaje WHERE clase = 'audio'").fetchone()
    assert fila["adjunto"].endswith(".webm") and Path(fila["adjunto"]).is_file()
