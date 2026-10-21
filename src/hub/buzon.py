"""La cola de un encargo: lo que llega mientras el agente no puede recibirlo.

🔴 **El agente NO es quien recibe, y ésa es toda la pieza.** El relé escucha
siempre y aparca aquí lo que llega; el agente lo recoge cuando su panel está
apto. Si el relé escribiera directo en el panel, un audio que llegara en mitad
de un compact —dos o tres minutos— entraría en una TUI que no está lista, y la
regla dura 17 ya dice que escribir no es haber enviado.

Aparcar primero es lo que cumple la promesa que se le hizo: *«que los mensajes
durante ese tiempo no se pierdan»*. Un mensaje aparcado no depende de que nada
esté listo — se guarda al recibirlo y se entrega cuando se pueda, aunque eso sea
diez minutos después o tras reiniciar el agente entero.

🔴 **Y vuelven en LOTE, no de uno en uno.** Cada entrega al panel es un turno de
Claude, y un turno relee el contexto entero: medido en este hub, 148k tokens por
llamada. Cuatro audios sueltos son cuatro despertares; en lote es uno. Es la
misma razón por la que existen los lotes del canal de consulta, y aquí pesa más
porque quien manda audios manda tres seguidos.

Lo que este módulo **no** hace: no habla con Telegram y no transcribe. Recibe
texto ya resuelto y decide cuándo y cómo entra al panel, que es lo que se puede
probar entero sin red.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone

from . import api, encargos, entrega

# Cuánto puede llevar un mensaje aparcado sin que se le diga nada a quien lo
# mandó. Por debajo no se dice nada a propósito: un bot que se narra cada treinta
# segundos acaba silenciado, y el indicador «escribiendo…» ya cubre las esperas
# cortas. Por encima, el silencio se lee como «no me hace caso».
ESPERA_ANTES_DE_AVISAR = 45

AVISO_DE_ESPERA = (
    "Dame un par de minutos, estoy ordenando lo que me contaste. "
    "No hace falta que repitas nada: lo tengo todo."
)

# Cuánto se sostiene el «escribiendo…» sobre algo sin contestar. Pasado esto,
# o el agente no va a contestar (dijo «ok gracias» y no hacía falta) o algo se
# rompió, y en los dos casos seguir tecleando en falso es peor que parar.
TOPE_ESCRIBIENDO = 300

# Un audio aparcado que todavía no tiene texto. No está «en cola» porque
# entregarlo así sería entregar una ruta a un archivo que el agente no abre.
SIN_TRANSCRIBIR = "sin-transcribir"

# Los botones que van bajo cada pregunta al dueño (decisión 237). Lo que llevan
# dentro son las mismas palabras que valdrían escritas: pulsar es responder.
BOTONES_PLAN = [("✅ Aprobar", "aprobado"), ("✖ Descartar", "no")]
BOTONES_RONDA = [("🔁 Otra ronda", "otra ronda"), ("Dejarlo así", "no")]
# 🔴 Decisión 245: si la maqueta está lista lo dice ELLA, no él. A ella le van
# estos dos con la URL; a él le llega «¿la implementamos?» sólo cuando ella
# pulsó «así la quiero», y entonces él aprueba con estos otros dos.
BOTONES_MAQUETA = [("✅ Así la quiero", "maqueta-lista"), ("🔁 Quiero cambiar algo", "maqueta-cambiar")]
BOTONES_IMPLEMENTAR = [("🚀 Implementar", "implementar"), ("Todavía no", "no")]


def ahora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _momento(valor: str | None) -> datetime:
    fecha = datetime.fromisoformat(valor or ahora())
    return fecha if fecha.tzinfo else fecha.replace(tzinfo=timezone.utc)


# --------------------------------------------------------------------------- #
# Aparcar
# --------------------------------------------------------------------------- #


def aparcar(con: sqlite3.Connection, encargo_id: str, user_id: int, texto: str,
            clase: str = "texto", adjunto: str = "",
            message_id: int | None = None) -> int:
    """Guarda lo que llegó. Es lo PRIMERO que se hace con un mensaje.

    Antes de mirar si el panel está, antes de transcribir, antes de contestar:
    si esto no es lo primero, hay un camino por el que un mensaje se pierde, y
    ése es el único fallo que esta función existe para impedir.

    🔴 Un audio entra como `sin-transcribir` y no como `en-cola`. Aparcar el
    archivo es lo que garantiza que no se pierda; pero entregarlo al agente
    antes de tener el texto le daría una ruta a un `.ogg` que no puede abrir, y
    el audio quedaría entregado y sin leer — perdido de la peor manera, porque
    la cola diría que salió bien.
    """
    if clase == "audio" and not (texto or "").strip():
        estado = SIN_TRANSCRIBIR
    else:
        estado = "en-cola"
    cursor = con.execute(
        """INSERT INTO encargo_mensaje
             (encargo_id, direccion, user_id, clase, texto, adjunto,
              message_id, estado, recibido_en)
           VALUES (?, 'entra', ?, ?, ?, ?, ?, ?, ?)""",
        (encargo_id, int(user_id), clase, texto or "", adjunto or "",
         message_id, estado, ahora()),
    )
    return int(cursor.lastrowid or 0)


def sin_transcribir(con: sqlite3.Connection) -> list[dict]:
    """Los audios que esperan texto, de todos los encargos y en orden de llegada."""
    return [dict(f) for f in con.execute(
        """SELECT * FROM encargo_mensaje
           WHERE direccion = 'entra' AND estado = ? ORDER BY id""",
        (SIN_TRANSCRIBIR,),
    )]


def anotar_transcripcion(con: sqlite3.Connection, mensaje_id: int,
                         texto: str) -> None:
    """El audio ya tiene texto y pasa a la cola normal, con los demás."""
    con.execute(
        """UPDATE encargo_mensaje
           SET texto = ?, estado = 'en-cola', detalle = '' WHERE id = ?""",
        (texto.strip(), int(mensaje_id)),
    )


def rendirse_con_el_audio(con: sqlite3.Connection, mensaje_id: int,
                          motivo: str) -> None:
    """No se pudo transcribir, y aun así se entrega. Nunca en silencio.

    🔴 El audio pasa a la cola con el hueco DECLARADO, no se descarta. Quien lo
    mandó contó algo y no tiene forma de saber que se perdió; el agente, con la
    nota delante, puede pedirle que lo repita. Tirarlo callando convertiría un
    fallo de whisper en un requisito que nunca existió.

    El archivo se conserva: si el transcriptor se arregla mañana, el audio sigue
    ahí para volver a pasarlo.
    """
    con.execute(
        """UPDATE encargo_mensaje
           SET texto = ?, estado = 'en-cola', detalle = ? WHERE id = ?""",
        (f"(no se pudo transcribir este audio: {motivo})", motivo, int(mensaje_id)),
    )


def encolar_salida(con: sqlite3.Connection, encargo_id: str, texto: str,
                   clase: str = "texto", adjunto: str = "",
                   user_id: int | None = None,
                   botones: list[tuple[str, str]] | None = None) -> int:
    """Lo que el agente quiere decirle a la persona. Lo manda el relé, no él.

    🔴 Mismo reparto que el tutorial del canal de consulta, y por el mismo
    motivo: **quien escribe esto no tiene el token** (regla dura 22). El agente
    corre en un panel de tmux y encola; el relé, que es el único proceso que lee
    el token, es quien habla con Telegram.
    """
    cursor = con.execute(
        """INSERT INTO encargo_mensaje
             (encargo_id, direccion, user_id, clase, texto, adjunto,
              estado, recibido_en, botones)
           VALUES (?, 'sale', ?, ?, ?, ?, 'en-cola', ?, ?)""",
        (encargo_id, user_id, clase, texto or "", adjunto or "", ahora(),
         json.dumps(botones) if botones else ""),
    )
    return int(cursor.lastrowid or 0)


def anunciar_publicacion(con: sqlite3.Connection, encargo_id: str, url: str,
                         clave: str | None = None) -> None:
    """La URL a los DOS: a quien lo encargó y a quien aprobó.

    🔴 Que le llegue a ella es la decisión 283, y es la que salva el diseño: quien
    puede decir «así no es» es la persona que describió el negocio. Sin esto, el
    circuito se cerraría entre el hub y quien paga, y nadie sabría si lo
    construido encaja. Vive aquí y no en la CLI porque lo llaman dos caminos
    —`encargo publicado` a mano y el relé al desplegar solo— y dos textos para
    la misma noticia acabarían diciendo cosas distintas.
    """
    fila = encargos.ver(con, encargo_id)
    if fila and fila["etapa"] == "sistema":
        # 🔴 La contraseña va aquí y sólo aquí (regla dura 5): no se guarda en
        # ningún sitio, así que este mensaje es la única vez que existe.
        usuario = encargo_id
        acceso = (f"Entras con usuario «{usuario}» y contraseña «{clave}». Guárdala: "
                  "no la tenemos apuntada en ningún sitio; si se pierde, se genera otra."
                  if clave else f"Entras con tu usuario «{usuario}» y tu contraseña de siempre.")
        texto = (f"Ya está tu sistema de verdad: {url}\n\n{acceso}\n\n"
                 "Lo que apuntes ahí se queda guardado. Empieza vacío: los datos "
                 "de ejemplo eran de la maqueta.")
        encolar_salida(con, encargo_id, texto)
        if quien := encargos.dueno(con):
            encolar_salida(con, encargo_id,
                           f"«{encargo_id}» implementado y publicado en {url}. "
                           + (f"Acceso: usuario «{usuario}», contraseña «{clave}» (no se guarda). "
                              if clave else "")
                           + "A ella le ha llegado también.",
                           user_id=int(quien["user_id"]))
        return
    if fila and int(fila["ronda"] or 1) > 1:
        # A partir de la segunda ronda ya no es «un primer borrador»: es lo que
        # pidió. Decirle otra vez que es un borrador se lee como que no se
        # enteraron de que ya lo vio (visto en el recorrido del 19-sep).
        texto = (f"Ya está lo que pediste: {url}\n\n"
                 "Ábrelo y dime si quedó como querías, o qué más cambiarías.")
    else:
        texto = (f"Ya puedes verlo: {url}\n\n"
                 "Es una maqueta de tu sistema: recórrela entera, usa cada pantalla "
                 "unos días como si fuera de verdad, y cuéntame qué cambiarías. "
                 "Todavía es un primer borrador, así que decir «esto no es así» "
                 "ayuda más que decir que está bien.")
    # La decisión de que ya está es suya (245): los botones van con la URL.
    texto += ("\n\nCuando ya esté como la quieres, pulsa «Así la quiero» y la "
              "convertimos en tu sistema de verdad, con tus datos guardados.")
    encolar_salida(con, encargo_id, texto, botones=BOTONES_MAQUETA)
    if quien := encargos.dueno(con):
        encolar_salida(con, encargo_id,
                       f"«{encargo_id}» publicado en {url}. "
                       "El enlace le ha llegado también a ella.",
                       user_id=int(quien["user_id"]))


def en_cola(con: sqlite3.Connection, encargo_id: str,
            direccion: str = "entra") -> list[dict]:
    return [dict(f) for f in con.execute(
        """SELECT * FROM encargo_mensaje
           WHERE encargo_id = ? AND direccion = ? AND estado = 'en-cola'
           ORDER BY id""",
        (encargo_id, direccion),
    )]


def salientes(con: sqlite3.Connection) -> list[dict]:
    """Todo lo que el agente dejó dicho, de todos los encargos, en orden."""
    return [dict(f) for f in con.execute(
        """SELECT * FROM encargo_mensaje
           WHERE direccion = 'sale' AND estado = 'en-cola'
           ORDER BY id""",
    )]


def conversacion(con: sqlite3.Connection, encargo_id: str,
                 limite: int = 200) -> list[dict]:
    """Las dos direcciones juntas y en orden, que es como se lee un chat."""
    filas = con.execute(
        """SELECT * FROM encargo_mensaje WHERE encargo_id = ?
           ORDER BY id DESC LIMIT ?""",
        (encargo_id, int(limite)),
    )
    return list(reversed([dict(f) for f in filas]))


def sin_resolver(con: sqlite3.Connection, encargo_id: str) -> list[dict]:
    """Todo lo que llegó y todavía no está en el panel del agente.

    🔴 Incluye los audios **sin transcribir**, y ésa es la diferencia con
    `en_cola`. Medido aquí: un audio de tres minutos tarda 19 s en transcribirse,
    y durante esos 19 s no estaba «en cola» —así que no se le mandaba el
    «escribiendo…»— pero la persona sí estaba esperando. El silencio no
    distingue en qué paso interno se atascó su mensaje.
    """
    return [dict(f) for f in con.execute(
        """SELECT * FROM encargo_mensaje
           WHERE encargo_id = ? AND direccion = 'entra'
             AND estado IN ('en-cola', ?)
           ORDER BY id""",
        (encargo_id, SIN_TRANSCRIBIR),
    )]


def sin_contestar(con: sqlite3.Connection, encargo_id: str) -> list[dict]:
    """Lo que dijo desde la última vez que el agente le contestó.

    🔴 Es la medida de la espera que ELLA siente, y no es `sin_resolver`
    (decisión 235). Un mensaje sale de la cola en dos segundos —entra al panel
    y ya está «entregado»— y desde ahí el agente piensa un minuto: durante ese
    minuto no había cola, así que no había «escribiendo…» ni aviso, y la
    segunda persona real mandó un «Hola?» en ese hueco exacto. Lo que a ella
    le importa no es en qué paso está su mensaje: es que nadie le ha
    contestado todavía.

    Cuentan sólo las contestaciones **a ella**: lo que sale hacia el dueño (el
    plan, las confirmaciones) no responde a nada suyo.
    """
    fila = encargos.ver(con, encargo_id)
    if not fila:
        return []
    ultima = con.execute(
        """SELECT MAX(id) AS id FROM encargo_mensaje
           WHERE encargo_id = ? AND direccion = 'sale' AND estado = 'enviado'
             AND (user_id IS NULL OR user_id = ?)""",
        (encargo_id, int(fila["user_id"])),
    ).fetchone()["id"] or 0
    return [dict(f) for f in con.execute(
        """SELECT * FROM encargo_mensaje
           WHERE encargo_id = ? AND direccion = 'entra' AND id > ?
             AND estado != 'descartado'
           ORDER BY id""",
        (encargo_id, ultima),
    )]


def esperando(con: sqlite3.Connection) -> list[str]:
    """Qué encargos tienen algo sin entregar. Es lo que mira el bucle."""
    return [f["encargo_id"] for f in con.execute(
        """SELECT DISTINCT encargo_id FROM encargo_mensaje
           WHERE direccion = 'entra' AND estado = 'en-cola'
           ORDER BY encargo_id""",
    )]


# --------------------------------------------------------------------------- #
# El marco
# --------------------------------------------------------------------------- #


def marcar(quien: str, mensajes: list[dict]) -> str:
    """Envuelve lo que llegó antes de que entre al contexto del agente.

    🔴 El marco no es decoración (regla dura 22): dice de quién es el texto y
    cuánta confianza merece. Lo escribió otra persona en un móvil, no es una
    instrucción del dueño del hub y no deroga nada de lo pactado con el agente.

    🔴 Y un audio se marca **como transcripción**, no como algo que dijo. Lo que
    hay ahí es lo que whisper oyó, y confundir las dos cosas hace que un error de
    transcripción se lea como un requisito raro del negocio en vez de como lo
    que es. La diferencia importa cuando el negocio se describe hablando.
    """
    lineas = [
        f"Mensajes de «{quien}» por el canal de encargos ({len(mensajes)}):",
        "",
    ]
    for m in mensajes:
        etiqueta = {
            "audio": "— audio, transcrito aquí (puede tener errores de oído):",
            "eleccion": "— eligió:",
        }.get(m.get("clase", "texto"), "— escribió:")
        lineas += [etiqueta, f"«{(m.get('texto') or '').strip()}»", ""]
    return "\n".join(lineas).strip()


# --------------------------------------------------------------------------- #
# Drenar
# --------------------------------------------------------------------------- #


def nombre_de_lote(encargo_id: str) -> str:
    return f"{encargo_id}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}"


def _anotar_motivo(con: sqlite3.Connection, ids: list[int], motivo: str) -> None:
    """Por qué siguen en cola, sin dejar rastro en el registro.

    Se escribe **encima** y no como una línea más: el bucle pasa cada pocos
    segundos y un apunte por vuelta convertiría el registro en ruido justo
    mientras pasa lo único que hay que poder leer ahí.
    """
    con.executemany(
        "UPDATE encargo_mensaje SET detalle = ? WHERE id = ?",
        [(motivo, i) for i in ids],
    )


def drenar(con: sqlite3.Connection, encargo_id: str) -> dict:
    """Entrega al panel del agente todo lo aparcado, de una vez.

    Devuelve qué pasó, para poder registrarlo y probarlo:

    - `entregado`: entró en el panel y se vio salir.
    - `nada`: no había nada que entregar.
    - `sin-panel`: el encargo no tiene agente abierto ahora mismo.
    - `no-apto`: hay panel pero ahí no se puede escribir — está trabajando, o
      compactando, o quien lo mira se salió a una shell. **Se reintenta.**
    - `sin-confirmar`: 🔴 el texto YA está en el panel y no se pudo confirmar
      que saliera. **No se reintenta**: repetirlo sería repetir una instrucción.
    """
    mensajes = en_cola(con, encargo_id)
    if not mensajes:
        return {"resultado": "nada", "cuantos": 0}

    ids = [m["id"] for m in mensajes]
    fila = encargos.ver(con, encargo_id)
    if not fila or not fila["slot_id"]:
        motivo = "el encargo todavía no tiene un agente abierto"
        _anotar_motivo(con, ids, motivo)
        return {"resultado": "sin-panel", "cuantos": len(ids), "motivo": motivo}

    panel = api.panel_de_slot(con, int(fila["slot_id"]))
    if not panel:
        motivo = "el slot del agente no está abierto en tmux"
        _anotar_motivo(con, ids, motivo)
        return {"resultado": "sin-panel", "cuantos": len(ids), "motivo": motivo}

    quien = encargos.nombre_visible(
        encargos.ver_persona(con, int(fila["user_id"]))
    )
    texto = marcar(quien, mensajes)
    lote = nombre_de_lote(encargo_id)

    try:
        entrega.entregar(panel["pane_id"], texto)
    except entrega.EscritoSinConfirmar as exc:
        # 🔴 ANTES que `PanelNoApto`, del que hereda. El orden de los `except`
        # es la lógica: al revés, un texto ya escrito volvería a la cola y
        # entraría dos veces en el contexto del agente.
        con.executemany(
            """UPDATE encargo_mensaje
               SET estado = 'sin-confirmar', lote = ?, movido_en = ?, detalle = ?
               WHERE id = ?""",
            [(lote, ahora(), str(exc), i) for i in ids],
        )
        encargos.registrar(
            con, "falla", f"escrito en el panel sin poder confirmar: {exc}",
            encargo_id=encargo_id,
        )
        return {"resultado": "sin-confirmar", "cuantos": len(ids), "motivo": str(exc)}
    except entrega.PanelNoApto as exc:
        _anotar_motivo(con, ids, str(exc))
        return {"resultado": "no-apto", "cuantos": len(ids), "motivo": str(exc)}

    con.executemany(
        """UPDATE encargo_mensaje
           SET estado = 'entregado', lote = ?, movido_en = ?, detalle = ''
           WHERE id = ?""",
        [(lote, ahora(), i) for i in ids],
    )
    encargos.registrar(
        con, "sale", f"{len(ids)} mensaje(s) entregados al agente en un lote",
        encargo_id=encargo_id,
    )
    return {"resultado": "entregado", "cuantos": len(ids), "lote": lote}


def drenar_todos(con: sqlite3.Connection) -> dict[str, dict]:
    return {e: drenar(con, e) for e in esperando(con)}


# --------------------------------------------------------------------------- #
# Que no parezca que nadie escucha
# --------------------------------------------------------------------------- #


def toca_avisar_de_la_espera(con: sqlite3.Connection, encargo_id: str,
                             momento: str | None = None) -> bool:
    """Si hay que decirle que espere: lleva rato aparcado y no se le ha dicho.

    🔴 Una sola vez por espera. El aviso vale porque es raro; repetido cada
    minuto enseña a ignorar al bot, que es exactamente lo que no puede pasar con
    el único canal por el que esta persona va a contar su negocio.
    """
    mensajes = sin_contestar(con, encargo_id)
    if not mensajes:
        return False
    fila = encargos.ver(con, encargo_id)
    if not fila or fila["avisado_espera"]:
        return False
    primero = _momento(mensajes[0]["recibido_en"])
    return _momento(momento) - primero >= timedelta(seconds=ESPERA_ANTES_DE_AVISAR)


def espera_viva(con: sqlite3.Connection, encargo_id: str,
                momento: str | None = None) -> list[dict]:
    """Lo sin contestar que todavía merece el «escribiendo…»: lo reciente.

    Con tope, porque un «ok gracias» al que el agente no contesta —y no tenía
    por qué— dejaría al bot tecleando en falso para siempre.
    """
    return [m for m in sin_contestar(con, encargo_id)
            if _momento(momento) - _momento(m["recibido_en"]) <= timedelta(seconds=TOPE_ESCRIBIENDO)]


def anotar_aviso_de_espera(con: sqlite3.Connection, encargo_id: str) -> None:
    encargos.tocar(con, encargo_id, avisado_espera=ahora())



def cerrar_espera(con: sqlite3.Connection, encargo_id: str) -> None:
    """La espera acaba cuando el agente le contesta: la contestación ES el
    «ya estoy», así que no se narra nada más (decisión 235)."""
    encargos.tocar(con, encargo_id, avisado_espera=None)
