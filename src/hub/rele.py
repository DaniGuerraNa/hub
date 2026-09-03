"""El relé: el único proceso que habla con Telegram.

Uno solo, y no uno por proyecto, porque **un bot admite un único consumidor de
updates**: la cola es única y el `offset` la confirma para todos. Con dos
pollers, Telegram corta uno con un 409 y entre medias se roban mensajes.

Repartir a varios proyectos no le exige ser listo, y no lo es a propósito: cada
pregunta que sale guarda su `message_id`, la respuesta llega con
`reply_to_message` apuntando a él, y casar es una consulta. **El relé no
interpreta el contenido de nada.** Es lo que le permite servir a diez proyectos
sin convertirse en el sitio donde todo se rompe.

Corre como servicio propio (`hub-canal.service`), separado de `hub-web`: es el
único que lee el token, y el que expone el puerto no debe verlo.
"""

from __future__ import annotations

import sqlite3
import time
from typing import Any

import yaml

from . import canal, config, db, entrega, telegram

# Entre vueltas. El long polling ya espera dentro de `getUpdates`, así que esto
# sólo evita un bucle cerrado cuando la API contesta al instante o falla.
PAUSA = 2

# Tras un fallo de red. No es reintento inmediato: si Telegram no está, insistir
# cada dos segundos no lo trae antes y llena el registro de ruido.
PAUSA_TRAS_FALLO = 30


def ajustes() -> dict:
    """Lee `canal.yml`. Un canal sin configurar no es un error: es lo normal."""
    ruta = config.canal_yml()
    if not ruta.is_file():
        return {}
    try:
        return yaml.safe_load(ruta.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        # No se traga: un YAML roto aquí deja el canal mudo, y callarlo haría
        # que el síntoma fuera «no llegan mensajes» sin ninguna pista.
        raise ValueError(f"{ruta} no es YAML válido: {exc}") from exc


def token_configurado() -> str:
    return str(ajustes().get("token_ref") or "").strip()


def bot() -> telegram.Bot:
    return telegram.Bot(telegram.leer_token(token_configurado()))


def estado() -> dict[str, Any]:
    """Qué le pasa al canal, para poder enseñarlo sin arrancar nada.

    Se comprueba **si el puntero lleva a un token**, no si Telegram responde:
    esto lo llama la web en cada carga y una llamada de red ahí la haría lenta
    de forma intermitente.
    """
    referencia = token_configurado()
    if not referencia:
        return {"configurado": False, "detalle": "no hay `token_ref` en canal.yml"}
    try:
        telegram.leer_token(referencia)
    except telegram.SinToken as exc:
        return {"configurado": False, "referencia": referencia, "detalle": str(exc)}
    return {"configurado": True, "referencia": referencia, "detalle": "el puntero lleva a un token"}


# --------------------------------------------------------------------------- #
# Lo que entra
# --------------------------------------------------------------------------- #


def procesar_mensaje(con: sqlite3.Connection, msg: dict) -> str:
    """Un mensaje entrante. Devuelve qué se hizo, para registrarlo y probarlo.

    🔴 El orden de las comprobaciones no es casual: primero se anota QUIÉN
    escribió —sin darle nada— y sólo después se mira si podía. Así una persona
    desconocida aparece en el hub para poder aprobarla, que es el único camino de
    alta que existe, y a la vez no consigue ningún efecto por haber escrito.
    """
    usuario = canal.anotar_contacto(
        con, msg["user_id"], msg.get("username", ""), msg.get("nombre", "")
    )

    if usuario["estado"] != "activo":
        canal.registrar(
            con, "falla", "mensaje de alguien sin alta", user_id=msg["user_id"],
            cuerpo=msg["texto"],
        )
        return "sin-alta"

    responde_a = msg.get("responde_a")
    if not responde_a:
        # 🔴 No se adivina. Con varias preguntas abiertas, elegir "la última"
        # escribe la respuesta de una cosa en el hilo de otra, y eso no deja
        # rastro de haberse equivocado.
        canal.registrar(
            con, "falla", "respuesta sin reply: no se sabe a qué contesta",
            user_id=msg["user_id"], cuerpo=msg["texto"],
        )
        return "sin-reply"

    # ¿Está practicando el `reply` con el último mensaje del tutorial? Es lo
    # único que se le pide hacer para aprender, y tiene que responder algo: un
    # ensayo que no confirma nada no enseña que haya salido bien.
    if canal.por_mensaje_de_tutorial(con, int(responde_a)):
        canal.registrar(
            con, "entra", "ensayo del tutorial: contestó con reply",
            user_id=msg["user_id"], cuerpo=msg["texto"],
        )
        return "ensayo"

    pregunta = canal.por_message_id(con, int(responde_a))
    if not pregunta:
        canal.registrar(
            con, "falla", "reply a un mensaje que no es una pregunta del hub",
            user_id=msg["user_id"], cuerpo=msg["texto"],
        )
        return "sin-pregunta"

    try:
        canal.anotar_respuesta(con, pregunta["id"], msg["user_id"], msg["texto"])
    except canal.SinPermiso:
        return "denegada"      # `exigir` y `anotar_respuesta` ya dejaron rastro
    except canal.CanalInvalido:
        return "invalida"

    # Una del lote no vuelve sola: espera a las demás. Lo que la libera está en
    # `canal.lotes_listos` y lo mira el bucle, no esta función — así una
    # respuesta que llega tarde no se cuela por un camino distinto.
    if not pregunta["lote"]:
        entregar_respuesta(con, pregunta["id"])
    return "respondida"


def entregar_respuesta(con: sqlite3.Connection, pregunta_id: int) -> bool:
    """Lleva la respuesta al panel donde está trabajando Claude.

    La verificación de que ahí sigue corriendo Claude Code la hace `entrega`, en
    el instante de escribir. Si falla, la respuesta **no se pierde**: se queda en
    `respondida` con el motivo, sale como pendiente de entregar y se reintenta en
    la siguiente vuelta.
    """
    pregunta = canal.ver_pregunta(con, pregunta_id)
    if not pregunta or not pregunta["pane_id"] or not pregunta["respuesta"]:
        return False

    quien = canal.nombre_visible(canal.ver_usuario(con, pregunta["user_id"] or 0))
    # Una tardía se anuncia como tardía: llega cuando su lote ya se dio por
    # cerrado, y puede contradecir una decisión que ya se tomó sin ella.
    referencia = f"la pregunta #{pregunta['id']}"
    if pregunta["lote"]:
        referencia += f" (llega TARDE: su lote «{pregunta['lote']}» ya se entregó sin ella)"
    texto = entrega.marcar(quien, referencia, pregunta["respuesta"])

    try:
        entrega.entregar(pregunta["pane_id"], texto)
    except entrega.EscritoSinConfirmar as exc:
        # 🔴 ANTES que `PanelNoApto`, del que hereda — misma trampa que el
        # `HTTPError` sobre `URLError` del CLI. Aquí el texto YA está escrito:
        # reintentarlo lo duplicaría, y en un panel de Claude Code eso es una
        # instrucción repetida. Sale de la cola y se enseña para que lo mire un
        # humano, que es el único que puede ver si salió.
        canal.marcar_escrita_sin_confirmar(con, pregunta_id, str(exc))
        return False
    except entrega.PanelNoApto as exc:
        # Aquí no se tocó el panel, así que reintentar es seguro: se queda en
        # `respondida` y vuelve a intentarse cuando el panel esté.
        canal.marcar_fallo_de_entrega(con, pregunta_id, str(exc))
        return False

    canal.marcar_entregada(con, pregunta_id)
    canal.registrar(
        con, "sale", "respuesta entregada al panel",
        proyecto_id=pregunta["proyecto_id"], pregunta_id=pregunta_id,
    )
    return True


def entregar_lote(con: sqlite3.Connection, lote: str) -> bool:
    """Las respuestas de un lote, en un solo mensaje y por tanto en un solo turno.

    🔴 El estado se mueve para TODAS las del lote a la vez, incluidas las que
    nadie contestó. Si una se quedara en `respondida` o `enviada`, el lote
    volvería a salir como listo en la vuelta siguiente y se entregaría otra vez
    — el mismo modo de fallo que casi duplica una respuesta suelta, sólo que
    multiplicado por cinco.
    """
    preguntas_ = canal.preguntas_del_lote(con, lote)
    if not preguntas_:
        return False

    contestadas = [p for p in preguntas_ if p["estado"] == "respondida"]
    if not contestadas:
        return False

    pane_id = next((p["pane_id"] for p in preguntas_ if p["pane_id"]), None)
    if not pane_id:
        return False

    quien = canal.nombre_visible(canal.ver_usuario(con, contestadas[0]["user_id"] or 0))
    texto = entrega.marcar_lote(
        quien,
        [(f"la pregunta #{p['id']}: {p['texto']}", p["respuesta"]) for p in contestadas],
        [f"#{p['id']}: {p['texto']}" for p in preguntas_ if p["estado"] != "respondida"],
    )

    try:
        entrega.entregar(pane_id, texto)
    except entrega.EscritoSinConfirmar as exc:
        for p in preguntas_:
            canal.marcar_escrita_sin_confirmar(con, p["id"], str(exc))
        return False
    except entrega.PanelNoApto as exc:
        canal.marcar_fallo_de_entrega(con, contestadas[0]["id"], str(exc))
        return False

    for p in preguntas_:
        canal.marcar_entregada(con, p["id"])
    canal.registrar(
        con, "sale",
        f"lote «{lote}» entregado al panel: {len(contestadas)} de {len(preguntas_)}",
        proyecto_id=preguntas_[0]["proyecto_id"], pregunta_id=contestadas[0]["id"],
    )
    return True


# --------------------------------------------------------------------------- #
# Lo que sale
# --------------------------------------------------------------------------- #


def enviar_tutoriales(con: sqlite3.Connection, bot_: telegram.Bot) -> int:
    """Manda el tutorial a quien lo tenga encolado. Devuelve a cuántos.

    El `message_id` que se guarda es el del ÚLTIMO mensaje, que es el que pide
    practicar el *reply*: contestarlo es el único ensayo posible sin gastar una
    pregunta de verdad.

    Si se cae a mitad, la persona se queda con parte del tutorial y sin la
    marca, así que en la vuelta siguiente lo recibe entero otra vez. Repetirlo
    es molesto; dejarlo a medias sin saber cuál falta, peor.
    """
    quien_avisa = dueno(con)
    nombre_dueno = canal.nombre_visible(quien_avisa) if quien_avisa else "tu contacto"

    enviados = 0
    for usuario in canal.esperan_tutorial(con):
        ultimo = None
        try:
            for texto in canal.TUTORIAL:
                ultimo = bot_.enviar(
                    int(usuario["user_id"]), texto.format(dueno=nombre_dueno)
                )
        except telegram.TelegramCaido as exc:
            canal.registrar(
                con, "falla", f"no salió el tutorial: {exc}", user_id=usuario["user_id"]
            )
            continue
        canal.marcar_tutorial_enviado(con, usuario["user_id"], ultimo)
        canal.registrar(
            con, "sale", "tutorial enviado", user_id=usuario["user_id"]
        )
        enviados += 1
    return enviados


def dueno(con: sqlite3.Connection) -> dict | None:
    return canal.dueno(con)


def avisar_al_dueno(con: sqlite3.Connection, bot_: telegram.Bot, pregunta: dict) -> bool:
    """«Hay una pregunta para ti.» Y nada más: el contenido NO viaja.

    🔴 Este es el punto donde es más fácil arruinar la propiedad que sostiene
    todo el diseño. Meter aquí el texto —«para que se vea desde el móvil sin
    entrar»— saca de la máquina justo lo que se decidió que no saliera, y lo
    haría de la forma más difícil de notar: funcionando mejor.

    Si no hay nadie marcado como dueño no se manda nada y se dice. Callarlo
    dejaría la pregunta esperando un aviso que no existe, que es exactamente lo
    que pasó con la primera pregunta real del canal.
    """
    quien = canal.dueno(con)
    if not quien:
        canal.registrar(
            con, "falla",
            "hay una pregunta para el dueño y nadie está marcado como dueño en /canal",
            proyecto_id=pregunta["proyecto_id"], pregunta_id=pregunta["id"],
        )
        return False

    aviso = (
        f"Tienes una pregunta pendiente del proyecto «{pregunta['proyecto_id']}».\n"
        "El contenido no viaja por aquí: léela en el hub, en /canal."
    )
    try:
        message_id = bot_.enviar(int(quien["user_id"]), aviso)
    except telegram.TelegramCaido as exc:
        canal.registrar(
            con, "falla", f"no salió el aviso al dueño: {exc}",
            proyecto_id=pregunta["proyecto_id"], pregunta_id=pregunta["id"],
        )
        return False

    # Se marca enviada aunque lo que salió fuera el aviso: si no, cada vuelta
    # del relé mandaría otro, y un aviso cada 27 segundos se silencia el mismo
    # día. El `message_id` es el del aviso, así que responderle por Telegram
    # también funciona — pero es su decisión, no la vía que se le propone.
    canal.marcar_enviada(con, pregunta["id"], int(message_id) if message_id else None)
    canal.registrar(
        con, "sale", "avisado el dueño (sin contenido)",
        user_id=quien["user_id"], proyecto_id=pregunta["proyecto_id"],
        pregunta_id=pregunta["id"],
    )
    return True


def enviar_pendientes(con: sqlite3.Connection, bot_: telegram.Bot) -> int:
    """Manda las preguntas que todavía no salieron. Devuelve cuántas.

    Las que son para el dueño del hub (`user_id` nulo) **no se mandan por aquí**:
    a él sólo se le avisa y lee el contenido en el hub. Es petición suya y es lo
    que mantiene dentro de la máquina todo lo que puede quedarse dentro.
    """
    enviadas = 0
    for pregunta in canal.preguntas(con, estado="pendiente"):
        if pregunta["user_id"] is None:
            avisar_al_dueno(con, bot_, pregunta)
            continue
        try:
            message_id = bot_.enviar(int(pregunta["user_id"]), pregunta["texto"])
        except telegram.TelegramCaido as exc:
            canal.registrar(
                con, "falla", f"no salió: {exc}",
                user_id=pregunta["user_id"], proyecto_id=pregunta["proyecto_id"],
                pregunta_id=pregunta["id"],
            )
            continue
        if message_id is None:
            # Sin `message_id` no hay forma de casar la respuesta. Darla por
            # enviada la dejaría esperando algo que nunca podría llegarle.
            canal.registrar(
                con, "falla", "Telegram no devolvió message_id: no se podría casar",
                pregunta_id=pregunta["id"],
            )
            continue
        canal.marcar_enviada(con, pregunta["id"], int(message_id))
        canal.registrar(
            con, "sale", "pregunta enviada", user_id=pregunta["user_id"],
            proyecto_id=pregunta["proyecto_id"], pregunta_id=pregunta["id"],
            cuerpo=pregunta["texto"],
        )
        enviadas += 1
    return enviadas


def revisar_vencimientos(con: sqlite3.Connection, momento: str | None = None) -> int:
    """Marca las que se pasaron de plazo. Quién escala y cuándo lo dice el pacto.

    🔴 El hub **no decide** aquí: sólo compara `vence_en`, que llegó de fuera con
    la pregunta. Un temporizador con reglas propias chocaría con el principio 9,
    que es lo que ha mantenido el hub habitable; una contingencia acordada por
    escrito antes de ausentarse es otra cosa.

    Lo hace el relé porque ya es un bucle vivo: no hace falta ningún reloj nuevo.
    """
    n = 0
    for pregunta in canal.vencidas(con, momento):
        canal.marcar_vencida(con, pregunta["id"])
        n += 1
    return n


def reintentar_entregas(con: sqlite3.Connection) -> int:
    """Respuestas que llegaron pero no se pudieron escribir en su panel.

    Las de un lote **no entran aquí**: su momento lo decide `entregar_lotes`, y
    dejarlas pasar por los dos caminos las entregaría sueltas — que es justo lo
    que el lote existe para evitar.
    """
    n = 0
    for pregunta in canal.preguntas(con, estado="respondida"):
        # Una del lote espera a las suyas... salvo que el lote ya se entregara
        # sin ella, por vencimiento. Entonces llega tarde y vuelve sola: alguien
        # se molestó en contestarla, y descartarla en silencio sería peor que
        # entregarla a destiempo.
        if pregunta["lote"] and not canal.lote_entregado(con, pregunta["lote"]):
            continue
        if pregunta["pane_id"] and entregar_respuesta(con, pregunta["id"]):
            n += 1
    return n


def entregar_lotes(con: sqlite3.Connection, momento: str | None = None) -> int:
    """Los lotes que ya pueden volver: todos contestados, o vencido el plazo."""
    n = 0
    for lote in canal.lotes_listos(con, momento):
        if entregar_lote(con, lote):
            n += 1
    return n


# --------------------------------------------------------------------------- #
# El bucle
# --------------------------------------------------------------------------- #


def una_vuelta(con: sqlite3.Connection, bot_: telegram.Bot, offset: int | None) -> int | None:
    """Una iteración completa. Devuelve el offset siguiente.

    Separada del bucle para poder probarla entera sin dormir ni tocar la red.
    """
    enviar_tutoriales(con, bot_)
    enviar_pendientes(con, bot_)
    reintentar_entregas(con)
    # Antes de `revisar_vencimientos`: una pregunta vencida de un lote es lo que
    # LIBERA al lote —se entrega lo que haya diciendo cuál falta—, y marcarla
    # `vencida` primero la sacaría del lote sin que nadie hubiera entregado nada.
    entregar_lotes(con)
    revisar_vencimientos(con)

    for update in bot_.actualizaciones(offset):
        # El offset avanza SIEMPRE, incluso si el mensaje se descarta: si sólo
        # avanzara al procesar bien, un mensaje que no se puede tratar se
        # devolvería en cada vuelta para siempre y el canal se quedaría atascado
        # en él sin recibir nada más.
        offset = int(update.get("update_id", 0)) + 1
        msg = telegram.partes_del_mensaje(update)
        if msg:
            if procesar_mensaje(con, msg) == "ensayo":
                # Se contesta desde aquí y no desde `procesar_mensaje`: esa
                # función es la única sin red, y es lo que permite probar el
                # dominio entero sin tocar internet.
                try:
                    bot_.enviar(int(msg["user_id"]), canal.RESPUESTA_AL_ENSAYO)
                except telegram.TelegramCaido:
                    pass   # el ensayo salió bien igual; sólo se queda sin el «✅»
        con.commit()
    con.commit()
    return offset


def correr() -> None:  # pragma: no cover - es el bucle del servicio
    """El proceso. Aísla cada fallo para que el relé no muera por una vuelta mala.

    Mismo criterio que el snapshotter (regla dura 2): un canal que se cae solo es
    peor que uno lento, porque su ausencia no se nota hasta que alguien esperaba
    una respuesta.
    """
    con = db.conectar(config.DB_PATH)
    db.inicializar(con)
    offset: int | None = None
    bot_: telegram.Bot | None = None

    while True:
        try:
            if bot_ is None:
                bot_ = bot()
            offset = una_vuelta(con, bot_, offset)
            time.sleep(PAUSA)
        except telegram.DosPollers as exc:
            # 🔴 Nunca en silencio. Reintentar callando hace que esto se vea como
            # «Telegram va lento» mientras dos procesos se roban los mensajes de
            # forma intermitente, y es el peor fallo posible de este canal.
            canal.registrar(con, "falla", f"409, hay otro poller con el mismo token: {exc}")
            con.commit()
            time.sleep(PAUSA_TRAS_FALLO)
        except telegram.SinToken as exc:
            canal.registrar(con, "falla", f"sin token utilizable: {exc}")
            con.commit()
            bot_ = None
            time.sleep(PAUSA_TRAS_FALLO)
        except telegram.TelegramCaido as exc:
            canal.registrar(con, "falla", f"telegram no responde: {exc}")
            con.commit()
            time.sleep(PAUSA_TRAS_FALLO)
        except Exception as exc:  # noqa: BLE001 - el bucle no puede morir
            canal.registrar(con, "falla", f"vuelta fallida: {exc!r}")
            con.commit()
            time.sleep(PAUSA_TRAS_FALLO)


if __name__ == "__main__":  # pragma: no cover
    correr()
