"""El relé, con la Bot API simulada y sin tocar la red.

Lo que se prueba aquí es lo que sólo se ve cuando las piezas están juntas: que
un mensaje de un desconocido no consiga nada, que una respuesta sin *reply* no
se adivine, y que el 409 —el peor fallo posible de este canal— no se trague.

🔴 Ninguna prueba de aquí sale a internet. `BotFalso` es todo el contrato que
`rele` usa de `telegram.Bot`; si ese contrato cambia, estos tests dejan de
proteger nada aunque sigan verdes, así que el cliente real tiene los suyos en
`test_telegram.py`.
"""

from __future__ import annotations

import pytest

from hub import canal, entrega, rele, telegram


class BotFalso:
    """Guarda lo que se le manda y devuelve lo que se le programe."""

    def __init__(self, updates=None, falla=None):
        self.enviados: list[tuple[int, str]] = []
        self._updates = list(updates or [])
        self._falla = falla
        self.siguiente_id = 5000

    def enviar(self, chat_id, texto):
        if self._falla:
            raise self._falla
        self.enviados.append((chat_id, texto))
        self.siguiente_id += 1
        return self.siguiente_id

    def actualizaciones(self, offset=None):
        pendientes = [
            u for u in self._updates
            if offset is None or u.get("update_id", 0) >= offset
        ]
        return pendientes


def _update(user_id=777, texto="sí, ya lo lleva", responde_a=None, update_id=1,
            username="ana_t", nombre="Ana"):
    mensaje = {
        "message_id": 900 + update_id,
        "text": texto,
        "from": {"id": user_id, "username": username, "first_name": nombre},
    }
    if responde_a:
        mensaje["reply_to_message"] = {"message_id": responde_a}
    return {"update_id": update_id, "message": mensaje}


@pytest.fixture
def escena(con):
    con.execute("INSERT INTO proyecto (id, nombre) VALUES ('contab','Contabilidad')")
    canal.anotar_contacto(con, 777, "ana_t", "Ana")
    canal.editar_usuario(con, 777, alias="ana", estado="activo")
    for a in canal.ACCIONES:
        canal.conceder(con, 777, "contab", a)
    return con


@pytest.fixture
def panel_ok(monkeypatch):
    """Un panel donde sí corre Claude Code. Registra lo que se le escribe."""
    escrito: list[str] = []
    monkeypatch.setattr(entrega, "panel_apto", lambda pane_id: (True, ""))
    monkeypatch.setattr(entrega, "entregar", lambda pane_id, texto: escrito.append(texto))
    return escrito


# ── lo que entra ──────────────────────────────────────────────────────────────


def test_un_desconocido_queda_apuntado_y_no_consigue_nada(con):
    """Aparece en el hub para poder aprobarlo, y eso es TODO lo que consigue."""
    assert rele.procesar_mensaje(con, telegram.partes_del_mensaje(_update(user_id=42))) == "sin-alta"

    usuario = canal.ver_usuario(con, 42)
    assert usuario["estado"] == "pendiente"
    assert canal.permisos_de(con, 42) == []


def test_una_respuesta_sin_reply_no_se_adivina(escena):
    """🔴 Con varias preguntas abiertas, elegir «la última» escribe la respuesta
    de una cosa en el hilo de otra, y eso no deja rastro de haberse equivocado."""
    canal.marcar_enviada(escena, canal.crear_pregunta(escena, "contab", "¿A?", user_id=777), 5001)
    canal.marcar_enviada(escena, canal.crear_pregunta(escena, "contab", "¿B?", user_id=777), 5002)

    assert rele.procesar_mensaje(escena, telegram.partes_del_mensaje(_update())) == "sin-reply"
    assert all(p["estado"] == "enviada" for p in canal.preguntas(escena))
    assert any("sin reply" in r["detalle"] for r in canal.registro(escena))


def test_un_reply_a_algo_que_no_es_una_pregunta_del_hub(escena):
    assert rele.procesar_mensaje(
        escena, telegram.partes_del_mensaje(_update(responde_a=1234))
    ) == "sin-pregunta"


def test_el_recorrido_completo_deja_la_respuesta_en_el_panel(escena, panel_ok):
    pid = canal.crear_pregunta(
        escena, "contab", "¿lleva IVA?", user_id=777, pane_id="%7"
    )
    canal.marcar_enviada(escena, pid, 5001)

    resultado = rele.procesar_mensaje(
        escena, telegram.partes_del_mensaje(_update(responde_a=5001))
    )

    assert resultado == "respondida"
    assert canal.ver_pregunta(escena, pid)["estado"] == "entregada"
    assert len(panel_ok) == 1


def test_lo_que_llega_al_panel_va_enmarcado(escena, panel_ok):
    """🔴 El marco es información sobre la confianza del texto.

    Lo escribió una persona en un móvil: no es una instrucción del dueño y no
    deroga el pacto. En crudo sería indistinguible de algo que dijo él.
    """
    pid = canal.crear_pregunta(escena, "contab", "¿lleva IVA?", user_id=777, pane_id="%7")
    canal.marcar_enviada(escena, pid, 5001)
    rele.procesar_mensaje(escena, telegram.partes_del_mensaje(_update(responde_a=5001)))

    entregado = panel_ok[0]
    assert "Respuesta de «ana»" in entregado
    assert f"la pregunta #{pid}" in entregado
    assert entregado.strip() != "sí, ya lo lleva"      # nunca en crudo


def test_si_el_panel_ya_no_tiene_claude_la_respuesta_espera(escena, monkeypatch):
    """El caso que justifica toda la verificación: se salió a una shell."""
    monkeypatch.setattr(
        entrega, "entregar",
        lambda *a: (_ for _ in ()).throw(entrega.PanelNoApto("en ese panel ya no corre Claude Code")),
    )
    pid = canal.crear_pregunta(escena, "contab", "¿lleva IVA?", user_id=777, pane_id="%7")
    canal.marcar_enviada(escena, pid, 5001)

    rele.procesar_mensaje(escena, telegram.partes_del_mensaje(_update(responde_a=5001)))

    pregunta = canal.ver_pregunta(escena, pid)
    assert pregunta["estado"] == "respondida"          # no consumida
    assert "ya no corre Claude" in pregunta["detalle"]


def test_lo_escrito_sin_confirmar_NO_se_vuelve_a_escribir(escena, monkeypatch):
    """🔴 Es lo que casi duplica un mensaje al estrenar el canal.

    La respuesta llegó al panel, `despachar` no supo confirmarlo —no sabía leer
    esa forma de caja— y el relé la dejó en `respondida`, o sea en la cola de
    reentrega. En cuanto el panel volviera a estar quieto se habría pegado otra
    vez, y otra: la confirmación fallaba SIEMPRE en ese panel, así que el ciclo
    no se agotaba solo. En Claude Code eso no es un mensaje repetido, es una
    instrucción repetida.
    """
    escrituras = []

    def escribe_y_no_confirma(pane_id, texto):
        escrituras.append(texto)
        raise entrega.EscritoSinConfirmar("se escribió pero no se pudo confirmar que saliera")

    monkeypatch.setattr(entrega, "entregar", escribe_y_no_confirma)
    pid = canal.crear_pregunta(escena, "contab", "¿lleva IVA?", user_id=777, pane_id="%7")
    canal.marcar_enviada(escena, pid, 5001)
    rele.procesar_mensaje(escena, telegram.partes_del_mensaje(_update(responde_a=5001)))

    assert len(escrituras) == 1
    pregunta = canal.ver_pregunta(escena, pid)
    assert pregunta["estado"] == "sin-confirmar"   # ni entregada ni en cola
    assert "no se pudo confirmar" in pregunta["detalle"]

    # Y la vuelta siguiente del relé no la toca: no vuelve a escribir.
    assert rele.reintentar_entregas(escena) == 0
    assert len(escrituras) == 1


def test_el_registro_dice_que_no_se_reintenta(escena, monkeypatch):
    """Quien lea el registro tiene que poder distinguir «no llegó» de «llegó y
    no lo sé»: son dos cosas que se arreglan de forma distinta."""
    monkeypatch.setattr(
        entrega, "entregar",
        lambda *a: (_ for _ in ()).throw(entrega.EscritoSinConfirmar("no se pudo confirmar")),
    )
    pid = canal.crear_pregunta(escena, "contab", "¿?", user_id=777, pane_id="%7")
    canal.marcar_enviada(escena, pid, 5001)
    rele.procesar_mensaje(escena, telegram.partes_del_mensaje(_update(responde_a=5001)))

    assert any("NO se reintenta" in r["detalle"] for r in canal.registro(escena))


def test_lo_que_no_se_pudo_entregar_se_reintenta(escena, panel_ok):
    """Cuando el panel vuelve, la respuesta que esperaba entra sola."""
    pid = canal.crear_pregunta(escena, "contab", "¿lleva IVA?", user_id=777, pane_id="%7")
    canal.anotar_respuesta(escena, pid, 777, "sí")
    canal.marcar_fallo_de_entrega(escena, pid, "estaba trabajando")

    assert rele.reintentar_entregas(escena) == 1
    assert canal.ver_pregunta(escena, pid)["estado"] == "entregada"


# ── lo que sale ───────────────────────────────────────────────────────────────


def test_las_preguntas_del_dueno_no_viajan(escena):
    """A él sólo se le avisa: el contenido se queda en la máquina."""
    canal.crear_pregunta(escena, "contab", "¿migramos a decimal?")       # para él
    canal.crear_pregunta(escena, "contab", "¿lleva IVA?", user_id=777)   # para ella

    bot = BotFalso()
    assert rele.enviar_pendientes(escena, bot) == 1
    assert [t for _, t in bot.enviados] == ["¿lleva IVA?"]


def test_al_dueno_se_le_avisa_SIN_el_contenido(escena):
    """🔴 El punto donde es más fácil arruinar la propiedad que sostiene el
    diseño: meter aquí el texto «para verlo sin entrar» saca de la máquina justo
    lo que se decidió que no saliera, y funcionando mejor."""
    canal.marcar_dueno(escena, 777)
    pid = canal.crear_pregunta(escena, "contab", "¿migramos a decimal? es delicado")

    bot = BotFalso()
    rele.enviar_pendientes(escena, bot)

    assert len(bot.enviados) == 1
    destinatario, aviso = bot.enviados[0]
    assert destinatario == 777
    assert "decimal" not in aviso and "delicado" not in aviso
    assert "contab" in aviso            # sí se dice de qué proyecto
    assert canal.ver_pregunta(escena, pid)["estado"] == "enviada"


def test_el_aviso_al_dueno_no_se_repite_en_cada_vuelta(escena):
    """Un aviso cada 27 segundos se silencia el mismo día, y entonces el canal
    sigue encendido y ya no existe."""
    canal.marcar_dueno(escena, 777)
    canal.crear_pregunta(escena, "contab", "¿migramos?")

    bot = BotFalso()
    rele.enviar_pendientes(escena, bot)
    rele.enviar_pendientes(escena, bot)
    rele.enviar_pendientes(escena, bot)

    assert len(bot.enviados) == 1


def test_sin_nadie_marcado_como_dueno_se_DICE(escena):
    """Callarlo deja la pregunta esperando un aviso que no existe — que es lo
    que pasó con la primera pregunta real del canal, horas en `pendiente`."""
    canal.crear_pregunta(escena, "contab", "¿migramos?")

    bot = BotFalso()
    rele.enviar_pendientes(escena, bot)

    assert bot.enviados == []
    assert any("nadie está marcado como dueño" in r["detalle"] for r in canal.registro(escena))


def test_solo_hay_un_dueno_a_la_vez(escena):
    """Dos serían dos personas recibiendo avisos de lo que se decidió que no
    saliera de aquí."""
    canal.anotar_contacto(escena, 888, "otro", "Otro")
    canal.marcar_dueno(escena, 777)
    canal.marcar_dueno(escena, 888)

    assert canal.dueno(escena)["user_id"] == 888
    assert sum(1 for u in canal.usuarios(escena) if u["es_dueno"]) == 1


def test_sin_message_id_no_se_da_por_enviada(escena):
    """Sin él no hay forma de casar la respuesta: quedaría esperando algo que
    nunca podría llegarle."""
    class SinId(BotFalso):
        def enviar(self, chat_id, texto):
            return None

    pid = canal.crear_pregunta(escena, "contab", "¿lleva IVA?", user_id=777)
    assert rele.enviar_pendientes(escena, SinId()) == 0
    assert canal.ver_pregunta(escena, pid)["estado"] == "pendiente"


def test_si_telegram_no_responde_la_pregunta_sigue_pendiente(escena):
    pid = canal.crear_pregunta(escena, "contab", "¿lleva IVA?", user_id=777)
    bot = BotFalso(falla=telegram.TelegramCaido("timeout"))

    assert rele.enviar_pendientes(escena, bot) == 0
    assert canal.ver_pregunta(escena, pid)["estado"] == "pendiente"
    assert any("no salió" in r["detalle"] for r in canal.registro(escena))


def test_el_vencimiento_solo_compara_lo_que_traia_plazo(escena):
    pid = canal.crear_pregunta(
        escena, "contab", "urge", user_id=777, vence_en="2026-01-01T00:00:00+00:00"
    )
    canal.marcar_enviada(escena, pid, 5001)
    assert rele.revisar_vencimientos(escena, "2026-06-01T00:00:00+00:00") == 1
    assert canal.ver_pregunta(escena, pid)["estado"] == "vencida"


# ── el bucle ──────────────────────────────────────────────────────────────────


def test_el_offset_avanza_aunque_el_mensaje_se_descarte(escena):
    """🔴 Si sólo avanzara al procesar bien, un mensaje intratable se devolvería
    en cada vuelta para siempre y el canal se quedaría atascado en él."""
    bot = BotFalso(updates=[_update(user_id=42, update_id=7)])   # desconocido
    assert rele.una_vuelta(escena, bot, None) == 8


def test_el_409_no_se_traga(escena):
    """El peor fallo posible: dos pollers robándose mensajes de forma
    intermitente, que reintentando en silencio se ve como «Telegram va lento»."""
    class DosVeces(BotFalso):
        def actualizaciones(self, offset=None):
            raise telegram.DosPollers("terminated by other getUpdates request")

    with pytest.raises(telegram.DosPollers):
        rele.una_vuelta(escena, DosVeces(), None)


def test_sin_canal_yml_no_es_un_error(tmp_path, monkeypatch):
    """Lo normal es no tener canal: no puede reventar la web al preguntarle."""
    monkeypatch.setenv("HUB_CANAL_YML", str(tmp_path / "no-existe.yml"))
    assert rele.ajustes() == {}
    assert rele.estado()["configurado"] is False


# ── el lote: varias preguntas que vuelven en un solo turno ────────────────────
#
# Cada respuesta que entra en el panel es un turno de Claude, y un turno relee el
# contexto entero. Medido con la herramienta del kit orquestador sobre sesiones
# reales: 148k tokens de relectura por llamada, el 69% del EQ de la sesión más
# cara. Cinco respuestas sueltas son cinco despertares y cinco cambios de
# tarea; en lote son uno.


def _lote_de_tres(con, pane_id="%7", vence=None):
    ids = []
    for texto in ("¿A?", "¿B?", "¿C?"):
        pid = canal.crear_pregunta(
            con, "contab", texto, user_id=777, pane_id=pane_id,
            vence_en=vence, lote="revision",
        )
        canal.marcar_enviada(con, pid, 5000 + len(ids) + 1)
        ids.append(pid)
    return ids


def test_una_respuesta_del_lote_no_vuelve_sola(escena, panel_ok):
    """Es todo el propósito: contestar la primera no despierta a Claude."""
    _lote_de_tres(escena)
    rele.procesar_mensaje(escena, telegram.partes_del_mensaje(_update(responde_a=5001)))

    assert panel_ok == []                       # no se escribió nada
    assert canal.lotes_listos(escena) == []     # y el lote no está listo


def test_el_lote_completo_vuelve_en_UN_SOLO_mensaje(escena, panel_ok):
    ids = _lote_de_tres(escena)
    for i, msg in enumerate((5001, 5002, 5003)):
        rele.procesar_mensaje(
            escena,
            telegram.partes_del_mensaje(_update(responde_a=msg, texto=f"r{i}", update_id=i + 1)),
        )
    assert rele.entregar_lotes(escena) == 1

    assert len(panel_ok) == 1                   # un turno, no tres
    entregado = panel_ok[0]
    assert "Respuestas de «ana»" in entregado   # el marco sigue puesto
    for i in range(3):
        assert f"r{i}" in entregado
    assert all(canal.ver_pregunta(escena, i)["estado"] == "entregada" for i in ids)


def test_al_vencer_vuelve_lo_que_haya_y_DICE_lo_que_falta(escena, panel_ok):
    """🔴 El caso pedido: 4 respondidas de 5.

    Y lo que falta se nombra: un lote incompleto que sólo enseñe lo que llegó
    deja a Claude creyendo que tiene las tres respuestas cuando tiene una, y no
    hay forma de notarlo desde dentro.
    """
    _lote_de_tres(escena, vence="2020-01-01T00:00:00+00:00")
    rele.procesar_mensaje(escena, telegram.partes_del_mensaje(_update(responde_a=5001)))

    assert canal.lotes_listos(escena) == ["revision"]
    assert rele.entregar_lotes(escena) == 1
    entregado = panel_ok[0]
    assert "Sin respuesta al vencer el plazo" in entregado
    assert "¿B?" in entregado and "¿C?" in entregado


def test_sin_vencer_y_sin_estar_completo_el_lote_espera(escena, panel_ok):
    """Sin plazo cumplido no se entrega a medias: eso es lo que lo hace
    determinista y no «a ver si la sesión está despierta»."""
    _lote_de_tres(escena, vence="2099-01-01T00:00:00+00:00")
    rele.procesar_mensaje(escena, telegram.partes_del_mensaje(_update(responde_a=5001)))

    assert canal.lotes_listos(escena) == []
    assert rele.entregar_lotes(escena) == 0
    assert panel_ok == []


def test_un_lote_entregado_no_se_entrega_otra_vez(escena, panel_ok):
    """🔴 El mismo modo de fallo que casi duplica una respuesta suelta, pero
    multiplicado: si una del lote se quedara sin mover de estado, el lote
    volvería a salir como listo en la vuelta siguiente."""
    _lote_de_tres(escena, vence="2020-01-01T00:00:00+00:00")
    rele.procesar_mensaje(escena, telegram.partes_del_mensaje(_update(responde_a=5001)))

    assert rele.entregar_lotes(escena) == 1
    assert rele.entregar_lotes(escena) == 0
    assert len(panel_ok) == 1


def test_el_reintento_suelto_no_toca_las_del_lote(escena, panel_ok):
    """Dos caminos hacia el mismo panel entregarían el lote de una en una, que
    es exactamente lo que el lote existe para evitar."""
    _lote_de_tres(escena)
    rele.procesar_mensaje(escena, telegram.partes_del_mensaje(_update(responde_a=5001)))

    assert rele.reintentar_entregas(escena) == 0
    assert panel_ok == []


def test_una_pregunta_suelta_sigue_volviendo_al_instante(escena, panel_ok):
    """El lote es opcional: sin él, todo se comporta como antes."""
    pid = canal.crear_pregunta(escena, "contab", "¿lleva IVA?", user_id=777, pane_id="%7")
    canal.marcar_enviada(escena, pid, 5001)
    rele.procesar_mensaje(escena, telegram.partes_del_mensaje(_update(responde_a=5001)))

    assert len(panel_ok) == 1
    assert canal.ver_pregunta(escena, pid)["estado"] == "entregada"


def test_la_respuesta_que_llega_tarde_no_se_pierde_y_se_anuncia(escena, panel_ok):
    """🔴 El agujero que abrió cerrar la reentrega del lote.

    El lote se cierra por vencimiento con una de tres. Media hora después llega
    la segunda: su lote ya no está listo —bien, no debe entregarse dos veces—
    pero `reintentar_entregas` la saltaba por tener lote, así que se quedaba en
    `respondida` para siempre. Alguien se molestó en escribirla.

    Vuelve sola y diciendo que llega tarde, porque puede contradecir una
    decisión que ya se tomó sin ella.
    """
    _lote_de_tres(escena, vence="2020-01-01T00:00:00+00:00")
    rele.procesar_mensaje(escena, telegram.partes_del_mensaje(_update(responde_a=5001)))
    assert rele.entregar_lotes(escena) == 1

    rele.procesar_mensaje(
        escena,
        telegram.partes_del_mensaje(_update(responde_a=5002, texto="tarde", update_id=2)),
    )
    assert rele.reintentar_entregas(escena) == 1

    assert len(panel_ok) == 2
    assert "llega TARDE" in panel_ok[1] and "tarde" in panel_ok[1]
    # Y el lote no se ha vuelto a entregar entero.
    assert rele.entregar_lotes(escena) == 0


def test_una_tardia_no_arrastra_al_lote_entero_otra_vez(escena, panel_ok):
    """Sin la guarda de «ya entregado», la tardía volvería a dar el lote por
    listo —las otras siguen sin contestar y el plazo pasó— y se entregaría
    entero por segunda vez."""
    _lote_de_tres(escena, vence="2020-01-01T00:00:00+00:00")
    rele.procesar_mensaje(escena, telegram.partes_del_mensaje(_update(responde_a=5001)))
    rele.entregar_lotes(escena)
    rele.procesar_mensaje(
        escena,
        telegram.partes_del_mensaje(_update(responde_a=5002, texto="tarde", update_id=2)),
    )

    assert canal.lotes_listos(escena) == []


# ── el tutorial ───────────────────────────────────────────────────────────────
#
# Lo manda el propio bot, en la conversación donde se va a contestar: quien usa
# esto lo usa desde el móvil, así que el sitio donde se aprende tiene que ser el
# sitio donde se responde.


def test_el_tutorial_solo_se_le_manda_a_quien_ya_esta_aprobado(escena):
    """🔴 Si se pudiera mandar a un `pendiente`, el hub tendría una forma de
    escribirle a cualquiera que le haya escrito al bot alguna vez. El alta
    invertida existe justamente para que aparecer en la lista no dé derecho a
    nada."""
    canal.anotar_contacto(escena, 999, "curioso", "Curioso")   # se queda pendiente

    with pytest.raises(canal.CanalInvalido, match="activo"):
        canal.pedir_tutorial(escena, 999)

    bot = BotFalso()
    assert rele.enviar_tutoriales(escena, bot) == 0
    assert bot.enviados == []


def test_el_tutorial_sale_entero_y_lleva_el_nombre_de_quien_pregunta(escena):
    canal.marcar_dueno(escena, 777)
    canal.pedir_tutorial(escena, 777)

    bot = BotFalso()
    assert rele.enviar_tutoriales(escena, bot) == 1

    assert len(bot.enviados) == len(canal.TUTORIAL)
    todo = "\n".join(t for _, t in bot.enviados)
    assert "ana" in todo                      # el alias del dueño, no un hueco
    assert "{dueno}" not in todo              # y la plantilla, resuelta
    assert "RESPONDER" in todo or "reply" in todo


def test_el_tutorial_no_se_repite_solo(escena):
    """Tres mensajes en cada vuelta del relé sería la forma más rápida de que
    alguien silencie el bot el primer día."""
    canal.pedir_tutorial(escena, 777)
    bot = BotFalso()
    rele.enviar_tutoriales(escena, bot)
    rele.enviar_tutoriales(escena, bot)

    assert len(bot.enviados) == len(canal.TUTORIAL)
    assert canal.ver_usuario(escena, 777)["tutorial"] not in ("", "pedido")


def test_contestar_al_ensayo_se_reconoce_y_no_se_confunde_con_una_respuesta(escena):
    """El último mensaje pide practicar el `reply`. Sin esta rama, ese ensayo
    caería en «reply a un mensaje que no es una pregunta del hub» y quien
    acaba de aprender recibiría silencio."""
    canal.pedir_tutorial(escena, 777)
    bot = BotFalso()
    rele.enviar_tutoriales(escena, bot)
    ultimo = canal.ver_usuario(escena, 777)["tutorial_msg"]

    resultado = rele.procesar_mensaje(
        escena, telegram.partes_del_mensaje(_update(responde_a=ultimo, texto="listo"))
    )

    assert resultado == "ensayo"
    assert any("ensayo del tutorial" in r["detalle"] for r in canal.registro(escena))


def test_el_ensayo_recibe_confirmacion(escena):
    """Un ensayo que no confirma nada no enseña que haya salido bien."""
    canal.pedir_tutorial(escena, 777)
    bot = BotFalso()
    rele.enviar_tutoriales(escena, bot)
    ultimo = canal.ver_usuario(escena, 777)["tutorial_msg"]

    bot._updates = [_update(responde_a=ultimo, texto="listo", update_id=7)]
    rele.una_vuelta(escena, bot, None)

    assert bot.enviados[-1][1] == canal.RESPUESTA_AL_ENSAYO


def test_una_respuesta_de_verdad_sigue_funcionando_tras_el_tutorial(escena, panel_ok):
    """La rama nueva se mete ANTES de buscar la pregunta: no puede tragarse los
    replies que sí son respuestas."""
    canal.pedir_tutorial(escena, 777)
    rele.enviar_tutoriales(escena, BotFalso())

    pid = canal.crear_pregunta(escena, "contab", "¿lleva IVA?", user_id=777, pane_id="%7")
    canal.marcar_enviada(escena, pid, 5001)
    assert rele.procesar_mensaje(
        escena, telegram.partes_del_mensaje(_update(responde_a=5001))
    ) == "respondida"
    assert len(panel_ok) == 1
