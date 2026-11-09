"""El relé de encargos: el único proceso que habla con el bot de encargos.

Servicio propio (`hub-encargos.service`) y bot propio, separados del canal de
consulta (decisión 221). No es orden: **son dos tokens y no deben verse el uno
al otro**, y un fallo en lo nuevo no puede llevarse por delante el canal que ya
se usa a diario. `hub-web`, que expone el puerto y con él una shell (regla dura
8), no ve ninguno de los dos.

🔴 **Este proceso recibe; no contesta.** Lo que llega se aparca en `buzon.py` y
se entrega al agente cuando su panel está apto; lo que el agente quiere decir lo
encola él y se manda desde aquí. Las dos direcciones pasan por la cola a
propósito: es lo que hace que un audio llegado en mitad de un compact no se
pierda y que quien escribe la respuesta no necesite el token.

Y, como en el canal de consulta, **el relé no interpreta el contenido de nada**.
Lo único que lee es de quién viene, si podía escribir y a qué mensaje responde.
Lo demás es trabajo del agente, que es quien puede equivocarse sin romper el
canal para todos.
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from . import buzon, config, db, encargos, llavero, rele_base, telegram, transcribir
from .reloj import instante

# Cuánto se insiste con un audio que no se puede transcribir antes de entregarlo
# con el hueco declarado. Diez minutos cubren un modelo que se está descargando;
# más allá, lo que hay es una avería, y dejar a la persona esperando en silencio
# mientras se arregla es peor que decirle que no se le oyó.
PLAZO_TRANSCRIPCION = timedelta(minutes=10)

# El prefijo que marca un audio que está en Telegram y todavía no en disco. Se
# guarda así —y no el `file_id` a secas— para que `adjunto` signifique siempre lo
# mismo: dónde está el archivo. Un campo que a veces es una ruta y a veces un
# identificador remoto es el que acaba borrando lo que no era.
EN_TELEGRAM = "telegram:"

SALUDO_SIN_ALTA = (
    "Hola. Este bot sólo atiende a personas dadas de alta, así que todavía no "
    "puedo ayudarte. Ya avisé a quien lo administra; si te esperaba, en un "
    "momento seguimos."
)

# Qué se admite como aprobación de un plan. Corta y cerrada a propósito
# (decisión 281): es la acción más privilegiada del sistema —autoriza gasto y un
# despliegue público— y lo que la dispara tiene que ser inequívoco. Todo lo demás
# que llegue por ese hilo se trata como un comentario, no como un sí.
APRUEBAN = {"aprobado", "apruebo", "aprobar", "adelante", "dale", "ok", "vale"}
DESCARTAN = {"no", "descartar", "descartado", "cancelar", "cancelado"}
# Sobre algo ya publicado, «aprobado» y estas significan lo mismo: otra ronda.
IMPLEMENTAN = frozenset({"implementar", "implementalo", "impleméntalo", "sistema"})
RETOMAN = {"otra ronda", "ronda", "retomar", "seguimos", "sí", "si"}
# Resultados de `procesar_mensaje` que cierran una pregunta con botones.
DECIDIDOS = {"aprobado", "descartado", "otra-ronda", "sin-ronda", "ya-resuelto"}
# Con esto se apunta el fallo al abrir el constructor y con esto se busca para
# no reintentar antes de `PLAZO_TRAS_FALLO`: dos cadenas en dos sitios harían
# que, cambiada una, se reintentara en cada vuelta.
MARCA_SIN_CONSTRUCTOR = "no se pudo abrir el constructor"
# Estados en los que un plan ya no admite decisión: volver a «aprobar» no es
# aprobar, es un toque de más.
YA_DECIDIDOS = ("aprobado", "construyendo", "implementando", "construido", "descartado")


def ajustes() -> dict:
    """Lee `encargos.yml`. Sin configurar no es un error: es lo normal al llegar."""
    return config.leer_ajustes(config.encargos_yml())


def token_configurado() -> str:
    return str(ajustes().get("token_ref") or "").strip()


#: Para el inventario del llavero (C-0143): dónde vive, nunca el valor.
LLAVES = (llavero.Llave("telegram-encargos", "el bot de encargos (hub-encargos)", token_configurado),)


def bot(con: sqlite3.Connection | None = None):
    """El bot de Telegram, o —si el chat web está configurado— uno que reparte
    entre los dos por el canal de cada persona (decisión 246)."""
    from . import chatweb

    referencia = token_configurado()
    try:
        token = telegram.leer_token(referencia)
    except telegram.SinToken as exc:
        rele_base.anotar_token("encargos", referencia, str(exc))
        raise
    rele_base.anotar_token("encargos", referencia, None)
    de_telegram = telegram.BotDeEncargos(token)
    chat = chatweb.bot(ajustes())
    if chat is None or con is None:
        return de_telegram
    return chatweb.Bots(con, {"telegram": de_telegram, "web": chat})


def estado() -> dict[str, Any]:
    """Qué le pasa al canal, sin tocar la red: lo llama la web en cada carga."""
    referencia = token_configurado()
    if not referencia:
        return {"configurado": False, "detalle": "no hay `token_ref` en encargos.yml"}
    # 🔴 Sin abrir el token: `hub-web` no lo toca (C-0144). Lo dice el relé.
    token = rele_base.estado_token("encargos", referencia, "hub-encargos")
    if not token["configurado"]:
        return token
    detalle = token["detalle"]
    try:
        transcribir.comando(ajustes())
    except transcribir.SinTranscriptor as exc:
        # No impide arrancar: el texto sigue funcionando y los audios se aparcan.
        # Pero se dice, porque el síntoma sin esto sería «no contesta a los
        # audios» y eso no lleva a ningún sitio.
        return {"configurado": True, "referencia": referencia,
                "detalle": detalle, "transcriptor": str(exc)}
    return {"configurado": True, "referencia": referencia, "detalle": detalle}


def carpeta_audios(encargo_id: str) -> Path:
    return encargos.carpeta(encargo_id) / "audios"


# --------------------------------------------------------------------------- #
# Lo que entra
# --------------------------------------------------------------------------- #


def procesar_mensaje(con: sqlite3.Connection, msg: dict) -> str:
    """Un mensaje entrante. Devuelve qué se hizo, para registrarlo y probarlo.

    🔴 **No toca la red**, igual que su equivalente del canal de consulta: el
    audio se aparca con su `file_id` y lo baja otro paso. Es lo que permite
    probar el comportamiento entero —quién puede, dónde cae, qué se aparca— sin
    internet, que es donde viven casi todos los fallos que importan.

    🔴 Y el orden de las comprobaciones tampoco es casual: primero se anota
    QUIÉN escribió —sin darle nada— y sólo después se mira si podía. Así una
    persona desconocida aparece en el hub para poder darle de alta, y a la vez
    no consigue ningún efecto por haber escrito.
    """
    persona = encargos.anotar_persona(
        con, msg["user_id"], msg.get("username", ""), msg.get("nombre", "")
    )

    # 🔴 Lo que el canal vuelve a dar tras un reinicio del relé (C-0186): ni se
    # aparca ni se contesta otra vez. Antes de todo lo demás, porque cada rama
    # de abajo deja algo —una línea, un «Anotado…»— que la segunda vez sobra.
    if buzon.ya_recibido(con, msg["user_id"], msg.get("message_id")):
        encargos.registrar(
            con, "entra", f"repetido: el canal volvió a dar el mensaje #{msg['message_id']}, "
            "que ya estaba recibido", user_id=msg["user_id"], cuerpo=msg.get("texto", ""),
        )
        return "repetido"

    if persona["estado"] != "activo":
        encargos.registrar(
            con, "falla", encargos.marca_sin_alta(msg.get("message_id")),
            user_id=msg["user_id"], cuerpo=msg.get("texto", ""),
        )
        return "sin-alta"

    # ¿Está contestando al plan que se le mandó? Sólo el dueño, y sólo sobre el
    # mensaje que enseña ese plan (decisión 281).
    responde_a = msg.get("responde_a")
    if persona["es_dueno"] and responde_a:
        encargo = encargos.por_plan_msg(con, int(responde_a))
        if encargo:
            return _resolver_plan(con, encargo, msg)

    if msg.get("boton") and not persona["es_dueno"]:
        return _boton_de_ella(con, persona, msg)

    encargo = encargos.abierto_de(con, msg["user_id"])
    if not encargo and (publicado := encargos.publicado_de(con, msg["user_id"])):
        return _cambios_sobre_lo_publicado(con, publicado, msg)
    if not encargo:
        encargos.registrar(
            con, "falla", "escribió alguien sin ningún encargo abierto",
            user_id=msg["user_id"], cuerpo=msg.get("texto", ""),
        )
        # El dueño que escribe «aprobado» SUELTO, con un plan esperando: no
        # aprueba nada —y eso no cambia (decisión 281)— pero se le dice, porque la
        # primera vez lo hizo y se quedó veinte minutos creyendo que sí.
        if persona["es_dueno"] and _palabra(msg) in APRUEBAN | DESCARTAN:
            for pendiente in encargos.listar(con, "propuesta"):
                buzon.encolar_salida(
                    con, pendiente["id"],
                    f"Eso no ha aprobado ni descartado nada: para «{pendiente['id']}» "
                    "hay que RESPONDER al mensaje del plan (mantén pulsado → "
                    "Responder). Así un «ok» en otra conversación no pone a construir.",
                    user_id=int(msg["user_id"]))
                break
        return "sin-encargo"

    if msg.get("voz"):
        buzon.aparcar(
            con, encargo["id"], msg["user_id"], msg.get("texto", ""),
            clase="audio", adjunto=EN_TELEGRAM + msg["voz"],
            message_id=msg.get("message_id"),
        )
        encargos.registrar(
            con, "entra", f"audio de {msg.get('segundos', 0)} s",
            user_id=msg["user_id"], encargo_id=encargo["id"],
        )
        return "audio"

    buzon.aparcar(
        con, encargo["id"], msg["user_id"], msg["texto"],
        message_id=msg.get("message_id"),
    )
    encargos.registrar(
        con, "entra", "mensaje de texto", user_id=msg["user_id"],
        encargo_id=encargo["id"], cuerpo=msg["texto"],
    )
    return "aparcado"


def _resolver_plan(con: sqlite3.Connection, encargo: dict, msg: dict) -> str:
    """Su respuesta al plan. Aprobar autoriza gasto, así que se lee estricto.

    Lo que no está en la lista **no es un no**: es un comentario, y se aparca
    para que lo lea el agente. Tratar «mejor quítale los descuentos» como un
    rechazo perdería una corrección; tratarlo como un sí construiría lo que no
    pidió.
    """
    if encargo["estado"] == "publicado":
        return _resolver_otra_ronda(con, encargo, msg)
    dicho = _palabra(msg)
    dueno = int(msg["user_id"])
    if encargo["estado"] in YA_DECIDIDOS and dicho in APRUEBAN | DESCARTAN:
        # 🔴 Un segundo «aprobado» sobre algo ya aprobado —o construyéndose—
        # volvía a ponerlo en «aprobado» y abría OTRO constructor. Con botones
        # es un toque de más; se contesta y no se toca nada (237).
        buzon.encolar_salida(
            con, encargo["id"],
            f"«{encargo['id']}» ya está en «{encargo['estado']}»: no hay nada que "
            "volver a decidir.", user_id=dueno)
        return "ya-resuelto"
    if dicho in APRUEBAN:
        encargos.tocar(con, encargo["id"], estado="aprobado")
        encargos.registrar(
            con, "entra", "plan APROBADO por el dueño", user_id=msg["user_id"],
            encargo_id=encargo["id"], cuerpo=msg.get("texto", ""),
        )
        encargo_id = encargo["id"]

        def construir() -> None:
            # Abre un constructor en tmux: fuera de la transacción (C-0152).
            resultado = empezar_a_construir(con, encargo_id)
            # 🔴 Cada acción suya recibe una confirmación (decisión 231). Aprobó, y
            # durante veinte minutos no supo si había servido: la primera vez lo
            # escribió suelto y no pasó nada; la segunda arrancó un constructor
            # que murió al instante, y tampoco. Un canal que calla tras un permiso
            # se lee como que no funcionó, y entonces se repite el permiso.
            buzon.encolar_salida(con, encargo_id, CONFIRMACION[resultado].format(
                encargo=encargo_id), user_id=dueno)
            # Y a ella, que es quien está esperando (decisión 233).
            buzon.encolar_salida(
                con, encargo_id,
                "Ya está aprobado y se está construyendo. Te aviso en cuanto esté "
                "listo para que lo veas.")

        rele_base.efecto(construir)
        return "aprobado"
    if dicho in DESCARTAN:
        encargos.tocar(con, encargo["id"], estado="descartado")
        encargos.registrar(
            con, "entra", "plan descartado por el dueño", user_id=msg["user_id"],
            encargo_id=encargo["id"], cuerpo=msg.get("texto", ""),
        )
        buzon.encolar_salida(
            con, encargo["id"],
            f"«{encargo['id']}» descartado. No se construye nada.", user_id=dueno)
        buzon.encolar_salida(
            con, encargo["id"],
            "Por ahora esto se queda en pausa. Si se retoma, te escribo yo.")
        return "descartado"

    buzon.aparcar(
        con, encargo["id"], msg["user_id"], msg.get("texto", ""),
        message_id=msg.get("message_id"),
    )
    encargos.registrar(
        con, "entra", "comentario del dueño sobre el plan (no es una aprobación)",
        user_id=msg["user_id"], encargo_id=encargo["id"], cuerpo=msg.get("texto", ""),
    )
    buzon.encolar_salida(
        con, encargo["id"],
        "Anotado; se lo paso al entrevistador. Si quieres aprobar el plan tal "
        "cual, responde «aprobado» a ese mismo mensaje.", user_id=dueno)
    return "comentario"


def _cambios_sobre_lo_publicado(con: sqlite3.Connection, encargo: dict, msg: dict) -> str:
    """Ella vio su página y dice algo. Es el principio de otra ronda, que la
    decide él (decisión 234): se aparca lo que dijo —lo leerá el entrevistador
    de la ronda—, se le acusa recibo a ella y a él se le pregunta UNA vez.

    Una vez y no una por mensaje: si manda cinco cosas seguidas, él recibe una
    pregunta con la primera y las demás se acumulan en la cola.

    🔴 Un audio se aparca y se le pregunta a él **cuando esté transcrito**
    (decisión 245): la primera vez le llegó «(un audio)» y no había forma de
    decidir nada con eso. La pregunta la lanza `transcribir_pendientes`.
    """
    encargo_id = encargo["id"]
    if msg.get("voz"):
        buzon.aparcar(con, encargo_id, msg["user_id"], msg.get("texto", ""),
                      clase="audio", adjunto=EN_TELEGRAM + msg["voz"],
                      message_id=msg.get("message_id"))
        encargos.registrar(con, "entra", "audio tras ver lo publicado",
                           user_id=msg["user_id"], encargo_id=encargo_id)
        if not encargo["plan_msg"]:
            buzon.encolar_salida(
                con, encargo_id,
                "Anotado, le entramos. Te escribo en un momento."
                if encargos.de_confianza(con, int(msg["user_id"]))
                else "Anotado. Se lo paso a quien decide si le entramos, y te aviso.")
        return "cambios"
    buzon.aparcar(con, encargo_id, msg["user_id"], msg.get("texto", ""),
                  message_id=msg.get("message_id"))
    encargos.registrar(con, "entra", "dice algo tras ver lo publicado",
                       user_id=msg["user_id"], encargo_id=encargo_id,
                       cuerpo=msg.get("texto", ""))
    if encargo["plan_msg"]:
        return "cambios"
    if encargos.de_confianza(con, int(msg["user_id"])):
        buzon.encolar_salida(con, encargo_id, "Anotado, le entramos. Te escribo en un momento.")
    else:
        buzon.encolar_salida(
            con, encargo_id,
            "Anotado. Se lo paso a quien decide si le entramos, y te aviso.")
    _preguntar_por_la_ronda(con, encargo, int(msg["user_id"]), msg.get("texto") or "")
    return "cambios"


def _preguntar_por_la_ronda(con: sqlite3.Connection, encargo: dict,
                            user_id: int, resumen: str) -> bool:
    """A él, una vez: «¿otra ronda?». Con lo que ella dijo, no con «un audio».

    🔴 Si la persona es de confianza (decisión 236), la ronda se abre sola y a
    él sólo se le cuenta: la decisión de cuándo hay otra versión es de quien
    usa la maqueta, y el gate de gastar ya lo levantó él al marcarla así.
    """
    if encargos.de_confianza(con, user_id):
        return _abrir_ronda_sola(con, encargo, user_id, resumen)
    quien = encargos.dueno(con)
    if not quien:
        encargos.registrar(con, "falla", "pide cambios y nadie está marcado como dueño",
                           encargo_id=encargo["id"])
        return False
    persona = encargos.ver_persona(con, user_id) or {}
    buzon.encolar_salida(
        con, encargo["id"],
        f"{encargos.nombre_visible(persona)} vio «{encargo['id']}» ({encargo['url']}) y dice:\n"
        f"«{(resumen or '(un audio)').strip()[:600]}»\n\n"
        "Pulsa «Otra ronda» para retomarlo —se abre el entrevistador con lo que "
        "pidió— o «Dejarlo así». Si quieres decirle algo al entrevistador, "
        "contesta a ESTE mensaje.",
        clase="plan", user_id=int(quien["user_id"]), botones=buzon.BOTONES_RONDA)
    return True


def _abrir_ronda_sola(con: sqlite3.Connection, encargo: dict, user_id: int, resumen: str) -> bool:
    from . import entrevistador

    encargo_id = encargo["id"]

    def abrir() -> bool:
        # Mata y abre agentes: fuera de la transacción del mensaje (C-0152).
        # Si el relé muere entre guardar y esto, esta ronda no se recupera
        # sola (decisión 352): se acepta, y el dueño lo ve en /encargos.
        try:
            hecho = entrevistador.abrir_otra_ronda(con, encargo_id)
        except Exception as exc:  # noqa: BLE001 - el relé no puede morir por esto
            encargos.registrar(con, "falla", f"no se pudo abrir otra ronda sola: {exc!r}",
                               encargo_id=encargo_id)
            return False
        buzon.anotar_aviso_de_espera(con, encargo_id)
        persona = encargos.ver_persona(con, user_id) or {}
        if quien := encargos.dueno(con):
            buzon.encolar_salida(
                con, encargo_id,
                f"{encargos.nombre_visible(persona)} vio «{encargo_id}» y dice:\n"
                f"«{(resumen or '').strip()[:600]}»\n\n"
                f"Es de confianza, así que la ronda {hecho['ronda']} se abrió sola. Te aviso "
                "cuando esté.", user_id=int(quien["user_id"]))
        return True

    hecho = rele_base.efecto(abrir)
    return True if hecho is None else hecho


def _boton_de_ella(con: sqlite3.Connection, persona: dict, msg: dict) -> str:
    """Los botones que van con la URL de su maqueta (decisión 245).

    «Así la quiero» es la única forma de que a él le llegue «¿la
    implementamos?»: la decisión de que está lista es de quien la usa, y la de
    gastar en implementarla sigue siendo de quien aprueba.
    """
    dato = msg.get("texto", "")
    encargo = encargos.publicado_de(con, msg["user_id"])
    if not encargo:
        return "boton-sin-encargo"
    encargo_id = encargo["id"]
    if dato == "maqueta-cambiar":
        buzon.encolar_salida(
            con, encargo_id,
            "Va. Cuéntame qué cambiarías, con calma y con tus palabras: lo que me "
            "digas se lo paso a quien le entra.")
        return "maqueta-cambiar"
    if dato != "maqueta-lista":
        return "boton-desconocido"
    if encargo["etapa"] != "maqueta":
        buzon.encolar_salida(con, encargo_id, "Ya es tu sistema de verdad: lo que apuntes ahí se queda.")
        return "ya-es-sistema"
    if encargo["plan_msg"]:
        buzon.encolar_salida(con, encargo_id, "Ya se lo pasé; en cuanto decida, te aviso.")
        return "ya-preguntado"
    quien = encargos.dueno(con)
    if not quien:
        encargos.registrar(con, "falla", "dice que la maqueta está y nadie es dueño",
                           encargo_id=encargo_id)
        return "sin-dueno"
    encargos.registrar(con, "entra", "dice que la maqueta ya está como la quiere",
                       user_id=msg["user_id"], encargo_id=encargo_id)
    buzon.encolar_salida(
        con, encargo_id,
        "Se lo paso a quien decide. Cuando esté hecho de verdad te aviso con la "
        "dirección y tu acceso.")
    buzon.encolar_salida(
        con, encargo_id,
        f"{encargos.nombre_visible(persona)} dice que la maqueta «{encargo_id}» "
        f"({encargo['url']}) ya está como la quiere. ¿La convertimos en el sistema "
        "de verdad, con base de datos y acceso? Pulsa «Implementar» o «Todavía no». "
        "Si quieres decirle algo, contesta a ESTE mensaje.",
        clase="plan", user_id=int(quien["user_id"]), botones=buzon.BOTONES_IMPLEMENTAR)
    return "maqueta-lista"


def _resolver_otra_ronda(con: sqlite3.Connection, encargo: dict, msg: dict) -> str:
    """Su respuesta a «¿otra ronda?». Mismo rigor que el plan: atada al mensaje."""
    from . import entrevistador

    dicho = _palabra(msg)
    dueno = int(msg["user_id"])
    encargo_id = encargo["id"]
    if dicho in IMPLEMENTAN:
        # 🔴 Decisión 244: la maqueta ya está como quiere; ahora el sistema.
        from . import implementador

        def implementar() -> str:
            # Mata paneles y abre el implementador: fuera de la transacción (C-0152).
            try:
                implementador.empezar(con, encargo_id)
            except Exception as exc:  # noqa: BLE001 - el relé no puede morir por esto
                encargos.registrar(con, "falla", f"no se pudo empezar a implementar: {exc!r}",
                                   encargo_id=encargo_id)
                buzon.encolar_salida(con, encargo_id,
                                     f"No pude empezar a implementar «{encargo_id}»: {exc}",
                                     user_id=dueno)
                return "no-se-pudo"
            buzon.encolar_salida(con, encargo_id,
                                 f"«{encargo_id}» pasa a sistema: el implementador ya está "
                                 "trabajando sobre la maqueta. Cuando esté, se publica en la "
                                 "misma dirección y os llega el acceso a los dos.", user_id=dueno)
            buzon.encolar_salida(con, encargo_id,
                                 "Tu maqueta ya está como la quieres, así que ahora la "
                                 "convertimos en el sistema de verdad: lo que apuntes se "
                                 "queda guardado y entras con tu contraseña. Te aviso cuando "
                                 "esté, con la dirección y tu acceso.")
            return "implementando"

        return rele_base.efecto(implementar) or "implementando"
    if dicho in APRUEBAN | RETOMAN:
        def ronda() -> str:
            # Mata y abre agentes: fuera de la transacción (C-0152).
            try:
                hecho = entrevistador.abrir_otra_ronda(con, encargo_id)
            except Exception as exc:  # noqa: BLE001 - el relé no puede morir por esto
                encargos.registrar(con, "falla", f"no se pudo abrir otra ronda: {exc!r}",
                                   encargo_id=encargo_id)
                buzon.encolar_salida(con, encargo_id,
                                     f"No pude abrir otra ronda de «{encargo_id}». El motivo "
                                     "está en el registro de /encargos.", user_id=dueno)
                return "no-se-pudo"
            buzon.encolar_salida(con, encargo_id,
                                 f"Ronda {hecho['ronda']} de «{encargo_id}» abierta: el "
                                 "entrevistador ya tiene lo que pidió.", user_id=dueno)
            buzon.encolar_salida(con, encargo_id,
                                 "Vale, le entramos. Te escribo en un momento con alguna pregunta.")
            # Lo que dijo llevaba aparcado desde que él tardó en pulsar: sin esto, la
            # misma vuelta le pedía paciencia ANTES del «vale, le entramos». Esta
            # línea ya es el acuse; la de espera empieza a contar desde aquí.
            buzon.anotar_aviso_de_espera(con, encargo_id)
            return "otra-ronda"

        return rele_base.efecto(ronda) or "otra-ronda"
    if dicho in DESCARTAN:
        encargos.tocar(con, encargo_id, plan_msg=None)
        encargos.registrar(con, "entra", "sin otra ronda por ahora", user_id=dueno,
                           encargo_id=encargo_id)
        buzon.encolar_salida(con, encargo_id, f"«{encargo_id}» se queda como está.", user_id=dueno)
        buzon.encolar_salida(con, encargo_id,
                             "Por ahora se queda como está. Si se retoma, te escribo yo.")
        return "sin-ronda"
    buzon.aparcar(con, encargo_id, msg["user_id"], msg.get("texto", ""),
                  message_id=msg.get("message_id"))
    buzon.encolar_salida(con, encargo_id,
                         "Anotado. Para retomarlo responde «otra ronda» a ese mismo mensaje.",
                         user_id=dueno)
    return "comentario"


def _palabra(msg: dict) -> str:
    return (msg.get("texto") or "").strip().lower().strip(".!¡ ")


# Lo que se le dice al dueño según cómo acabó su «aprobado». Una por resultado
# de `empezar_a_construir`, para que ninguno se quede sin frase.
CONFIRMACION = {
    "construyendo": ("«{encargo}» aprobado. El constructor ya está trabajando; "
                     "te aviso cuando esté hecho y se publique."),
    "hay-otro": ("«{encargo}» aprobado. Hay otro encargo construyéndose ahora; "
                 "éste empieza solo en cuanto aquel acabe."),
    "apagado": ("«{encargo}» aprobado. El constructor no arranca solo (así está "
                "configurado): ábrelo desde /encargos cuando quieras."),
    "no-se-pudo": ("«{encargo}» aprobado, pero no pude arrancar el constructor. "
                   "El motivo está en el registro de /encargos; lo vuelvo a "
                   "intentar solo."),
}


def construir_lo_aprobado(con: sqlite3.Connection, ajustes_: dict | None = None) -> str | None:
    """Lo aprobado que se quedó esperando turno arranca cuando hay hueco.

    Sin esto, un «aprobado» que llegara mientras otro encargo se construye —o
    justo cuando tmux no pudo abrir la ventana— se quedaba en «aprobado» para
    siempre, con una confirmación que decía «empieza solo» y no era verdad.
    Uno por vuelta, el más antiguo, y sólo si nadie está construyendo.
    """
    if not (ajustes() if ajustes_ is None else ajustes_).get("construir_al_aprobar", True):
        return None
    if encargos.listar(con, "construyendo") or encargos.listar(con, "implementando"):
        return None
    aprobados = sorted(encargos.listar(con, "aprobado"), key=lambda e: e["actualizado_en"])
    if not aprobados:
        return None
    # Tras un fallo se espera el mismo plazo que el despliegue: reintentar cada
    # cinco segundos contra un tmux que no está no lo trae antes.
    encargo_id = aprobados[0]["id"]
    if encargos.ya_registrado(con, encargo_id, MARCA_SIN_CONSTRUCTOR,
                              desde=datetime.now(timezone.utc) - PLAZO_TRAS_FALLO):
        return None
    return empezar_a_construir(con, encargo_id)


def empezar_a_construir(con: sqlite3.Connection, encargo_id: str) -> str:
    """Lo que pasa justo después de un «aprobado». Devuelve qué se hizo.

    🔴 Empieza **solo**, y es su diseño, no una comodidad mía: *«el gate va antes
    de gastar, no antes de publicar»* (decisión 228). La aprobación que acaba de
    llegar es el permiso, y pedir un segundo clic en el hub lo convertiría en
    dos permisos para la misma decisión — que es cómo se acaba aprobando sin
    mirar.

    Tres frenos, y cada uno tapa una forma distinta de que esto salga caro:

    - **Uno a la vez.** Dos constructores compiten por la misma cuota y por la
      misma pantalla, y cuando algo falla no se sabe cuál lo hizo.
    - **Se puede apagar** con `construir_al_aprobar: false` en `encargos.yml`,
      sin tocar código. Aprobar seguirá funcionando; sólo habrá que abrir el
      constructor a mano desde el hub.
    - **Un fallo aquí no se propaga.** Esto corre dentro del bucle del relé
      (regla dura 2): que no haya tmux no puede dejar el canal mudo. El encargo
      se queda en «aprobado» y se abre a mano, que es exactamente donde estaría
      si el interruptor estuviera apagado.
    """
    from . import constructor

    if not (ajustes().get("construir_al_aprobar", True)):
        encargos.registrar(
            con, "sale", "aprobado; no se construye solo (así está configurado)",
            encargo_id=encargo_id)
        return "apagado"

    if encargos.listar(con, "construyendo") or encargos.listar(con, "implementando"):
        encargos.registrar(
            con, "falla",
            "aprobado, pero ya hay otro encargo construyéndose: espera su turno",
            encargo_id=encargo_id)
        return "hay-otro"

    # Un plan aprobado sobre un sistema lo hace el implementador, no el
    # constructor: la maqueta ya no es lo que se publica (decisión 244).
    fila = encargos.ver(con, encargo_id)
    if fila and fila["etapa"] == "sistema":
        from . import implementador

        try:
            implementador.abrir_agente(con, encargo_id)
        except Exception as exc:  # noqa: BLE001 - el relé no puede morir por esto
            encargos.registrar(
                con, "falla", f"no se pudo abrir el implementador: {exc!r}",
                encargo_id=encargo_id)
            return "no-se-pudo"
        return "implementando"

    try:
        constructor.abrir_agente(con, encargo_id)
    except Exception as exc:  # noqa: BLE001 - el relé no puede morir por esto
        encargos.registrar(
            con, "falla", f"{MARCA_SIN_CONSTRUCTOR}: {exc!r}",
            encargo_id=encargo_id)
        return "no-se-pudo"
    return "construyendo"


# ── Publicar lo construido ───────────────────────────────────────────────────

SCRIPT_DESPLIEGUE = Path(__file__).resolve().parents[2] / "scripts" / "desplegar-encargo.sh"
# Cuánto se le da al script entero: rsync de un sitio estático más el minuto
# que espera a ver la URL responder. Pasado esto, algo no es un despliegue.
TOPE_DESPLIEGUE = 240
# Tras un fallo no se reintenta en cada vuelta: Caddy sacando un certificado o
# el DNS propagándose no mejoran en cinco segundos, y cada intento es un rsync.
PLAZO_TRAS_FALLO = timedelta(minutes=10)
MARCA_FALLO = "no se pudo desplegar"


def despliegue_configurado(ajustes_: dict | None = None) -> dict | None:
    """Dónde se publica, o `None` si no está dicho o está apagado.

    Tres datos y los tres son de la máquina, no del código: el alias de ssh, el
    nombre exacto del contenedor de Caddy y el dominio. Ninguno tiene valor por
    omisión aquí por lo mismo que no lo tiene en el script: cablear el de una
    máquina es convertirlo en la suposición de todas.
    """
    bloque = (ajustes() if ajustes_ is None else ajustes_).get("despliegue") or {}
    if not isinstance(bloque, dict) or not bloque.get("automatico", True):
        return None
    if not all(str(bloque.get(k) or "").strip() for k in ("servidor", "caddy", "dominio")):
        return None
    return {k: str(bloque[k]).strip() for k in ("servidor", "caddy", "dominio")}


def desplegar_construidos(con: sqlite3.Connection,
                          ajustes_: dict | None = None) -> int:
    """Publica lo que el constructor dio por hecho. Devuelve cuántos salieron.

    🔴 Sin pedir otro permiso, y es su decisión, no una comodidad: *«el gate va
    antes de gastar, no antes de publicar»* (decisión 228). El «aprobado» autorizó el
    plan entero, y la URL llega detrás «sin preguntar otra vez». La primera
    versión de esto ponía a una persona entre «construido» y «publicado» por
    prudencia mía, y era contradecir una decisión cerrada (228).

    Lo que sí frena, y por qué:

    - **El nombre no bloquea** (decisión 232). Si la ficha sabe cómo se llama
      el negocio, aquí se le pone ese nombre —`peluches-de-ana`— justo
      antes de subirlo, cuando el constructor ya terminó y mover la carpeta
      no pisa a nadie. Si no lo sabe, sale con el provisional: él prefirió un
      enlace feo que funciona a un encargo parado esperando un nombre.
    - **Tras un fallo se espera** `PLAZO_TRAS_FALLO` antes de reintentar, y al
      dueño se le cuenta sólo la primera vez: el fallo típico es un DNS que aún
      no resuelve, y eso no lo arregla insistir cada cinco segundos.
    - **El script decide, no esto.** Todo lo que el despliegue se niega a hacer
      —sin `index.html`, Caddy que no lee la carpeta, URL que no contesta— lo
      dice él y aquí sólo se apunta. Un fallo no mata la vuelta (regla dura 2).
    """
    from . import entrevistador

    destino = despliegue_configurado(ajustes_)
    if not destino:
        return 0

    publicados = 0
    for fila in encargos.listar(con, "construido"):
        encargo_id = fila["id"]
        # 🔴 Antes de renombrar: renombrar mueve la carpeta, y un agente abierto
        # dentro se queda apuntando a un id que ya no existe (decisión 234).
        # Los dos terminaron su ronda; la siguiente abre uno nuevo.
        entrevistador.cerrar_agentes(con, encargo_id)
        if encargos.ES_PROVISIONAL.match(encargo_id):
            ficha = encargos.cargar_ficha(con, encargo_id)
            if nombre := encargos.nombre_sugerido(con, ficha):
                encargos.renombrar(con, encargo_id, nombre)
                encargos.registrar(con, "sale", f"nombrado «{nombre}» a partir de la ficha",
                                   encargo_id=nombre)
                encargo_id = nombre
        if encargos.ya_registrado(con, encargo_id, MARCA_FALLO,
                                  desde=datetime.now(timezone.utc) - PLAZO_TRAS_FALLO):
            continue

        fila = encargos.ver(con, encargo_id)
        es_sistema = fila["etapa"] == "sistema"
        clave = None
        if es_sistema:
            from . import implementador

            # La contraseña nace en el primer despliegue del sistema y se manda
            # UNA vez con la URL; en disco y en el servidor sólo queda el hash.
            if not implementador.tiene_acceso(encargo_id):
                clave = implementador.generar_acceso(encargo_id)
        que = encargos.carpeta(encargo_id) / ("app" if es_sistema else "sitio")
        entorno = {**os.environ, "HUB_CADDY": destino["caddy"],
                   "HUB_DOMINIO_ENCARGOS": destino["dominio"]}
        try:
            r = subprocess.run(
                ["bash", str(SCRIPT_DESPLIEGUE), encargo_id, str(que),
                 destino["servidor"], "--va"],
                capture_output=True, text=True, timeout=TOPE_DESPLIEGUE, env=entorno,
            )
            salida, codigo = (r.stdout + r.stderr), r.returncode
        except (OSError, subprocess.TimeoutExpired) as exc:
            salida, codigo = repr(exc), -1

        if codigo != 0:
            primera_vez = not encargos.ya_registrado(con, encargo_id, MARCA_FALLO)
            encargos.registrar(
                con, "falla", f"{MARCA_FALLO} (código {codigo})",
                encargo_id=encargo_id, cuerpo=salida[-2000:])
            if primera_vez and (quien := encargos.dueno(con)):
                buzon.encolar_salida(
                    con, encargo_id,
                    f"«{encargo_id}» está construido pero no se pudo publicar. "
                    "El motivo está en el registro de /encargos; lo reintento "
                    "cada diez minutos.",
                    user_id=int(quien["user_id"]))
            continue

        url = f"https://{encargo_id}.{destino['dominio']}"
        # 🔴 `plan_msg` a cero al publicar: es la llave de «¿ya te pregunté?»
        # para lo que diga después (234), y con el del plan de la ronda puesto,
        # el primer mensaje de la primera persona real tras ver su página se
        # aparcó en silencio: ni acuse a ella ni pregunta a él.
        encargos.tocar(con, encargo_id, estado="publicado", url=url, plan_msg=None)
        encargos.registrar(con, "sale", f"publicado en {url}", encargo_id=encargo_id)
        buzon.anunciar_publicacion(con, encargo_id, url, clave=clave)
        publicados += 1
    return publicados


def bajar_audios(con: sqlite3.Connection, bot_: telegram.BotDeEncargos) -> int:
    """Trae a disco los audios aparcados. Devuelve cuántos.

    Un fallo aquí **no descarta nada**: el mensaje se queda esperando con su
    `file_id`. Telegram guarda los archivos, así que la vuelta siguiente vuelve a
    intentarlo, y el motivo queda escrito para saber por qué no llega.
    """
    bajados = 0
    for mensaje in buzon.sin_transcribir(con):
        adjunto = mensaje["adjunto"] or ""
        if not adjunto.startswith(EN_TELEGRAM):
            continue
        destino = (carpeta_audios(mensaje["encargo_id"])
                   / f"{mensaje['id']:06d}.ogg")
        try:
            guardado = bot_.descargar(adjunto[len(EN_TELEGRAM):], destino)
        except telegram.TelegramCaido as exc:
            buzon.anotar_detalle(con, mensaje["id"], f"no se pudo bajar el audio: {exc}")
            continue
        # Lo que se apunta es donde QUEDÓ, que no siempre es donde se pidió: el
        # chat web guarda webm y corrige la extensión (246). Apuntar el .ogg
        # pedido dejó un audio real «inexistente» para el transcriptor.
        buzon.apuntar_adjunto(con, mensaje["id"], str(guardado or destino))
        bajados += 1
    return bajados


def transcribir_pendientes(con: sqlite3.Connection,
                           ajustes_: dict | None = None) -> int:
    """Pasa a texto lo que ya está en disco. Devuelve cuántos audios se resolvieron.

    Los tres finales son distintos y se distinguen a propósito:

    - **texto**: sigue su camino con los demás mensajes.
    - **no se entendió**: se entrega diciéndolo, para que el agente pueda pedir
      que lo repita. Whisper devolviendo nada es información, no un fallo.
    - **no se pudo**: se insiste un rato —un modelo que se descarga tarda— y
      pasado el plazo se entrega con el hueco declarado. Nunca se descarta: el
      archivo se queda por si el transcriptor se arregla mañana.
    """
    ajustes_ = ajustes_ if ajustes_ is not None else ajustes()
    resueltos = 0
    for mensaje in buzon.sin_transcribir(con):
        adjunto = mensaje["adjunto"] or ""
        if not adjunto or adjunto.startswith(EN_TELEGRAM):
            continue
        try:
            texto = transcribir.transcribir(Path(adjunto), ajustes_)
        except transcribir.NoSeEntendio:
            buzon.rendirse_con_el_audio(
                con, mensaje["id"], "no se entendió nada en la grabación")
            encargos.registrar(
                con, "falla", "audio sin nada que transcribir",
                encargo_id=mensaje["encargo_id"])
            _preguntar_si_era_tras_publicar(con, mensaje, "(un audio que no se entendió)")
            resueltos += 1
            continue
        except transcribir.SinTranscriptor as exc:
            buzon.anotar_detalle(con, mensaje["id"], str(exc))
            if instante(mensaje["recibido_en"]) + PLAZO_TRANSCRIPCION < instante(None):
                buzon.rendirse_con_el_audio(con, mensaje["id"], str(exc))
                encargos.registrar(
                    con, "falla", f"audio entregado sin transcribir: {exc}",
                    encargo_id=mensaje["encargo_id"])
                resueltos += 1
            continue
        buzon.anotar_transcripcion(con, mensaje["id"], texto)
        encargos.registrar(
            con, "entra", "audio transcrito", encargo_id=mensaje["encargo_id"],
            cuerpo=texto)
        _preguntar_si_era_tras_publicar(con, mensaje, texto)
        resueltos += 1
    return resueltos


def _preguntar_si_era_tras_publicar(con: sqlite3.Connection, mensaje: dict, texto: str) -> None:
    """Un audio de después de publicar: ahora que tiene texto, a él (245)."""
    encargo = encargos.ver(con, mensaje["encargo_id"])
    if encargo and encargo["estado"] == "publicado" and not encargo["plan_msg"]:
        _preguntar_por_la_ronda(con, encargo, int(mensaje["user_id"]), texto)


# --------------------------------------------------------------------------- #
# Lo que sale
# --------------------------------------------------------------------------- #


def mandar_salientes(con: sqlite3.Connection, bot_: telegram.BotDeEncargos) -> int:
    """Manda lo que el agente dejó encolado. Devuelve cuántos salieron.

    🔴 Un fallo de red **no marca nada**: en este canal la red se cae decenas de
    veces por semana y el mensaje sigue siendo cierto en la vuelta siguiente. Lo
    que sí sale de la cola es lo que Telegram rechaza por su contenido, porque
    eso no mejora reintentándolo.
    """
    salidos = 0
    for mensaje in buzon.salientes(con):
        # La cola se leyó de golpe y se manda de uno en uno: lo que `encargo
        # deshacer` retiró entre medias ya no sale (C-0186).
        if not buzon.sigue_en_cola(con, mensaje["id"]):
            continue
        encargo = encargos.ver(con, mensaje["encargo_id"])
        if not encargo:
            continue
        destino = mensaje["user_id"] or encargo["user_id"]
        try:
            if mensaje["clase"] == "muestras" and mensaje["adjunto"]:
                message_id = bot_.enviar_foto(
                    int(destino), Path(mensaje["adjunto"]), buzon.para_enviar(mensaje["texto"]))
            elif mensaje.get("botones"):
                message_id = bot_.enviar_con_botones(
                    int(destino), buzon.para_enviar(mensaje["texto"]),
                    [tuple(b) for b in json.loads(mensaje["botones"])])
            else:
                message_id = bot_.enviar(int(destino), buzon.para_enviar(mensaje["texto"]))
        except telegram.TelegramCaido as exc:
            # Al registro, sólo cuando cambia el motivo (C-0186): una imagen
            # que ya no está no se arregla sola, y una línea por vuelta, cada
            # pocos segundos, tapaba el resto del registro.
            motivo = f"no salió: {exc}"
            if mensaje.get("detalle") != motivo:
                buzon.anotar_detalle(con, mensaje["id"], motivo)
                encargos.registrar(
                    con, "falla", f"no salió un mensaje: {exc}",
                    user_id=destino, encargo_id=mensaje["encargo_id"])
            continue

        if not mensaje["user_id"]:
            # Le contestaron: si se le había pedido paciencia, la espera acaba
            # aquí y sin narrarla — la contestación ya lo dice (235).
            buzon.cerrar_espera(con, mensaje["encargo_id"])
        if not buzon.marcar_enviado(con, mensaje["id"], message_id):
            # Se retiró mientras se mandaba: ya había salido y no se finge
            # (C-0186). Un plan así no se ata a su mensaje: aprobar autoriza
            # gasto (281), y quien lo encoló dijo que no lo quería.
            encargos.registrar(
                con, "sale", f"mensaje del agente ({mensaje['clase']}): {buzon.SALIO_AUNQUE_RETIRADO}",
                user_id=destino, encargo_id=mensaje["encargo_id"],
                cuerpo=buzon.tapado(mensaje["texto"]))
            salidos += 1
            continue
        # 🔴 El plan se recuerda por su `message_id`: aprobarlo es responder a
        # ESE mensaje (decisión 281). Sin esto, la aprobación no tendría a qué
        # atarse y un «sí» escrito en cualquier otro momento la dispararía.
        if mensaje["clase"] == "plan" and message_id:
            encargos.tocar(con, mensaje["encargo_id"], plan_msg=int(message_id))
        encargos.registrar(
            con, "sale", f"mensaje del agente ({mensaje['clase']})",
            user_id=destino, encargo_id=mensaje["encargo_id"],
            cuerpo=buzon.tapado(mensaje["texto"]))
        salidos += 1
    return salidos


def atender_esperas(con: sqlite3.Connection, bot_: telegram.BotDeEncargos) -> int:
    """Que un silencio largo no se lea como que nadie escucha. Sin pasarse.

    Tres niveles, y el orden es el diseño:

    - Mientras haya algo sin entregar, el indicador «escribiendo…». No deja
      rastro en la conversación y cubre las esperas cortas, que son casi todas.
    - Pasado el umbral, **una** línea. Una, no una cada minuto: un bot que se
      narra acaba silenciado, y entonces el aviso que importe tampoco se leerá.
    - Cuando la cola se vacía y se había avisado, otra diciendo que ya está.
      La manda el relé porque es quien SABE que el lote entró; el agente puede
      tardar otro tanto en contestar, y ese hueco es justo el que hay que tapar.
    """
    avisos = 0
    for encargo in encargos.listar(con):
        identificador = encargo["id"]
        if encargo["estado"] in ("publicado", "descartado"):
            # Lo que aparcó tras ver su página lo lee la ronda siguiente, si él
            # la abre: pedirle paciencia mientras tanto sería mentirle.
            continue
        # 🔴 «Sin contestar» y no «en cola» (decisión 235): la cola se vacía en
        # dos segundos y el agente piensa un minuto; lo que ella siente es
        # que nadie le ha contestado, esté su mensaje donde esté.
        pendientes = buzon.espera_viva(con, identificador)

        if pendientes:
            bot_.escribiendo(int(encargo["user_id"]))
            if buzon.toca_avisar_de_la_espera(con, identificador):
                try:
                    bot_.enviar(int(encargo["user_id"]), buzon.AVISO_DE_ESPERA)
                except telegram.TelegramCaido as exc:
                    encargos.registrar(
                        con, "falla", f"no salió el aviso de espera: {exc}",
                        encargo_id=identificador)
                    continue
                buzon.anotar_aviso_de_espera(con, identificador)
                encargos.registrar(
                    con, "sale", "avisado de que va a tardar",
                    user_id=encargo["user_id"], encargo_id=identificador)
                avisos += 1
            continue

    return avisos


def saludar_a_los_que_no_pueden(con: sqlite3.Connection,
                                bot_: telegram.BotDeEncargos) -> int:
    """Una línea a quien escribió sin alta, y sólo una en su vida.

    🔴 No concede nada y no dice nada de dentro: sólo evita que la persona a la
    que él invitó se quede mirando un silencio. Y se manda **una vez**, no una
    por mensaje: quien no debería estar aquí no consigue que el bot le conteste
    a todo lo que escriba.
    """
    salidos = 0
    for persona in encargos.personas(con):
        if persona["estado"] != "pendiente" or encargos.ya_saludado(con, persona["user_id"]):
            continue
        try:
            bot_.enviar(int(persona["user_id"]), SALUDO_SIN_ALTA)
        except telegram.TelegramCaido:
            continue
        encargos.registrar(
            con, "sale", encargos.MARCA_SALUDO, user_id=persona["user_id"])
        salidos += 1
    return salidos


# --------------------------------------------------------------------------- #
# El bucle
# --------------------------------------------------------------------------- #


#: Cuántas veces ha fallado cada update, entre vuelta y vuelta (`rele_base`).
FALLOS: dict = {}
#: Qué paso de la vuelta está fallando y con qué, para apuntarlo una vez (`rele_base.pasos`).
FALLANDO: dict = {}


def una_vuelta(con: sqlite3.Connection, bot_: telegram.BotDeEncargos,
               offset: int | None, ajustes_: dict | None = None) -> int | None:
    """Una iteración completa. Separada del bucle para probarla sin dormir.

    El orden es el que hace que la conversación se lea bien: primero se resuelve
    lo que ya llegó —bajar, transcribir, entregar—, después sale lo que el
    agente tenga que decir, y sólo al final se mira si hay que disculparse por
    la espera. Al revés, se le pediría paciencia por algo que ya se contestó.

    Cada paso en su `try` (`rele_base.pasos`, C-0186): uno que falla siempre
    no puede impedir que se pida lo nuevo, que va el último.
    """
    rele_base.pasos("encargos", [
        ("bajar_audios", lambda: bajar_audios(con, bot_)),
        ("transcribir_pendientes", lambda: transcribir_pendientes(con, ajustes_)),
        ("drenar", lambda: buzon.drenar_todos(con)),
        # Antes de mandar lo saliente, para que el «se publica solo en un
        # momento» y la URL no vayan en vueltas distintas cuando el despliegue
        # es rápido.
        ("desplegar_construidos", lambda: desplegar_construidos(con, ajustes_)),
        ("construir_lo_aprobado", lambda: construir_lo_aprobado(con, ajustes_)),
        ("mandar_salientes", lambda: mandar_salientes(con, bot_)),
        ("atender_esperas", lambda: atender_esperas(con, bot_)),
        ("saludar", lambda: saludar_a_los_que_no_pueden(con, bot_)),
    ], registrar=lambda texto: encargos.registrar(con, "falla", texto), fallando=FALLANDO)

    # El offset (o el cursor del chat web) avanza mensaje a mensaje (345). Lo que llega del chat web viene marcado con
    # `canal` y no mueve el offset de Telegram (decisión 246).
    def tratar(update: dict) -> tuple[dict, str, list] | None:
        msg = telegram.boton_pulsado(update) or telegram.partes_con_voz(update)
        if not msg:
            return None
        # Atómico: lo que se guarda de un mensaje, o todo o nada; abrir o
        # matar agentes queda para `despues` (C-0152).
        with rele_base.diferidos() as efectos, db.transaccion(con):
            resultado = procesar_mensaje(con, msg)
        return msg, resultado, efectos

    def despues(_update: dict, hecho: tuple[dict, str, list]) -> None:
        msg, resultado, efectos = hecho
        # Antes que los botones: si el efecto falla («no-se-pudo»), los botones
        # se quedan y él puede volver a pulsar.
        try:
            final = rele_base.ejecutar(efectos)
        finally:
            # El «cargando…» del botón se cierra aunque el efecto falle.
            if msg.get("boton"):
                bot_.pulsado(msg["callback_id"], "Recibido")
        if isinstance(final, str):
            resultado = final
        if msg.get("boton"):
            # Si decidió algo, retirar los botones: un «Aprobar» que sigue
            # ahí invita a pulsarlo dos veces (237). Ya guardado: si la red
            # falla, no se repite.
            if resultado in DECIDIDOS or resultado == "maqueta-lista":
                bot_.quitar_botones(msg["chat_id"], msg["responde_a"])

    return rele_base.recorrer(con, bot_.actualizaciones(offset), offset, tratar, despues=despues,
                              confirmar=getattr(bot_, "confirmar", None),
                              registrar=lambda texto: encargos.registrar(con, "falla", texto), fallos=FALLOS)


def correr() -> None:
    """El proceso: el bucle común de los relés (`rele_base.correr`, regla dura 2)."""
    con = db.conectar(config.DB_PATH)
    db.inicializar(con)

    def apuntar(texto: str) -> None:
        encargos.registrar(con, "falla", texto)
        con.commit()

    rele_base.correr("encargos", lambda: bot(con), lambda bot_, offset: una_vuelta(con, bot_, offset),
                     apuntar, dormir=time.sleep)


if __name__ == "__main__":  # pragma: no cover
    correr()
