"""Canal de consulta: preguntarle a otra persona cuando el dueño no está.

Que Claude, en vez de archivar una duda hasta el checkpoint, se la mande a
alguien que sí puede resolverla y siga trabajando con la respuesta. El diseño
entero, con sus porqués, en `PLAN-TELEGRAM.md`.

🔴 **Esto NO es un canal por el que un tercero manda instrucciones.** Es un canal
por el que Claude hace una pregunta y recibe una respuesta. Toda la diferencia de
superficie de ataque está ahí, y este módulo está construido sobre lo segundo:
no existe ninguna función para que alguien de fuera abra una conversación.

Aquí vive el dominio —quién puede qué, y el ciclo de una pregunta— y nada de
red. Hablar con Telegram es de `telegram.py`; el bucle, de `rele.py`. Partido así
porque lo de aquí se puede probar entero sin tocar internet, y es la parte donde
un fallo se convierte en un permiso que no debía existir.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from . import api
from .snapshotter import ahora

# Las tres acciones de la V1. Es una lista CERRADA a propósito: si conceder algo
# nuevo fuera cuestión de escribir otra cadena en la tabla, el día que alguien
# añadiera `enviar-prompt` nadie se enteraría de que acaba de abrir la puerta que
# este diseño existe para no abrir.
ACCIONES = ("recibir-preguntas", "responder", "leer-estado")

ESTADOS_USUARIO = ("pendiente", "activo", "bloqueado")


class CanalInvalido(ValueError):
    """Se pidió algo que el contrato no admite. Se dice qué, no «error»."""


class SinPermiso(PermissionError):
    """Denegado. Lleva dentro qué faltaba, para poder registrarlo tal cual."""


# --------------------------------------------------------------------------- #
# Registro
# --------------------------------------------------------------------------- #


def registrar(
    con: sqlite3.Connection,
    direccion: str,
    detalle: str,
    *,
    user_id: int | None = None,
    proyecto_id: str | None = None,
    pregunta_id: int | None = None,
    cuerpo: str = "",
) -> None:
    """Deja constancia. Se llama SIEMPRE, también —sobre todo— cuando se deniega.

    Un canal hacia fuera sin registro es un canal del que no se puede decir
    después qué salió, y lo que sale de aquí sale de la máquina.
    """
    con.execute(
        """INSERT INTO canal_registro
             (momento, direccion, user_id, proyecto_id, pregunta_id, detalle, cuerpo)
           VALUES (?,?,?,?,?,?,?)""",
        (ahora(), direccion, user_id, proyecto_id, pregunta_id, detalle, cuerpo),
    )


def registro(
    con: sqlite3.Connection,
    limite: int = 100,
    direccion: str | None = None,
    user_id: int | None = None,
    proyecto_id: str | None = None,
    desde: int = 0,
) -> list[dict]:
    """Lo que ha pasado por el canal, del último al primero.

    Con filtros porque este registro **crece y no se poda**: es la auditoría de
    lo que sale de la máquina, así que borrarlo sería quitarse la única prueba
    de qué se envió. Y un registro que sólo se puede mirar entero deja de
    mirarse en cuanto tiene mil líneas.

    `desde` es el desplazamiento para paginar. Se pide `limite + 1` en la
    llamada de arriba para saber si hay más sin contar la tabla entera.
    """
    sql = "SELECT * FROM canal_registro WHERE 1=1"
    args: list[Any] = []
    if direccion:
        sql += " AND direccion=?"
        args.append(direccion)
    if user_id is not None:
        sql += " AND user_id=?"
        args.append(int(user_id))
    if proyecto_id:
        sql += " AND proyecto_id=?"
        args.append(proyecto_id)
    sql += " ORDER BY id DESC LIMIT ? OFFSET ?"
    args += [int(limite), int(desde)]
    return [dict(f) for f in con.execute(sql, args)]


def cuenta_registro(
    con: sqlite3.Connection,
    direccion: str | None = None,
    user_id: int | None = None,
    proyecto_id: str | None = None,
) -> int:
    """Cuántas entradas casan con el filtro. Es lo que permite decir «de 340»
    en vez de dejar al usuario adivinando cuánto le queda por delante."""
    sql = "SELECT COUNT(*) AS n FROM canal_registro WHERE 1=1"
    args: list[Any] = []
    if direccion:
        sql += " AND direccion=?"
        args.append(direccion)
    if user_id is not None:
        sql += " AND user_id=?"
        args.append(int(user_id))
    if proyecto_id:
        sql += " AND proyecto_id=?"
        args.append(proyecto_id)
    return int(con.execute(sql, args).fetchone()["n"])


# --------------------------------------------------------------------------- #
# Usuarios
# --------------------------------------------------------------------------- #


def ver_usuario(con: sqlite3.Connection, user_id: int) -> dict | None:
    fila = con.execute(
        "SELECT * FROM canal_usuario WHERE user_id=?", (int(user_id),)
    ).fetchone()
    return dict(fila) if fila else None


def anotar_contacto(
    con: sqlite3.Connection, user_id: int, username: str = "", nombre: str = ""
) -> dict:
    """Alguien escribió al bot. Se apunta, y NO se le da nada.

    Es el único camino de entrada que existe, porque la Bot API no deja escribir
    a un teléfono: el bot sólo puede contestar a quien le habló primero. De ahí
    que el alta esté invertida respecto a lo que uno esperaría — no eliges a
    quién añadir, apruebas a quien apareció.

    Se refrescan `username` y `nombre` en cada contacto porque son lo único que
    permite reconocer a la persona al aprobarla, y su dueño los cambia cuando
    quiere. El `alias`, el `estado` y los permisos NO se tocan aquí: son del
    dueño del hub y un mensaje entrante no puede moverlos.
    """
    user_id = int(user_id)
    previo = ver_usuario(con, user_id)
    if previo:
        con.execute(
            "UPDATE canal_usuario SET username=?, nombre=?, visto_en=? WHERE user_id=?",
            (username, nombre, ahora(), user_id),
        )
        return ver_usuario(con, user_id)  # type: ignore[return-value]

    con.execute(
        """INSERT INTO canal_usuario (user_id, username, nombre, estado, visto_en)
           VALUES (?,?,?,'pendiente',?)""",
        (user_id, username, nombre, ahora()),
    )
    registrar(con, "entra", "contacto nuevo, sin permisos", user_id=user_id)
    return ver_usuario(con, user_id)  # type: ignore[return-value]


def usuarios(con: sqlite3.Connection) -> list[dict]:
    filas = [
        dict(f)
        for f in con.execute(
            "SELECT * FROM canal_usuario ORDER BY estado, alias, user_id"
        )
    ]
    for f in filas:
        f["permisos"] = permisos_de(con, f["user_id"])
    return filas


def editar_usuario(
    con: sqlite3.Connection,
    user_id: int,
    alias: str | None = None,
    estado: str | None = None,
    nota: str | None = None,
) -> None:
    if estado is not None and estado not in ESTADOS_USUARIO:
        raise CanalInvalido(
            f"«{estado}» no es un estado. Son: {', '.join(ESTADOS_USUARIO)}."
        )
    cambios = {
        k: v
        for k, v in (("alias", alias), ("estado", estado), ("nota", nota))
        if v is not None
    }
    if not cambios:
        return
    asignaciones = ", ".join(f"{k}=?" for k in cambios)
    con.execute(
        f"UPDATE canal_usuario SET {asignaciones} WHERE user_id=?",
        (*cambios.values(), int(user_id)),
    )
    registrar(
        con, "sale", f"el dueño cambió {', '.join(cambios)}", user_id=int(user_id)
    )


# --------------------------------------------------------------------------- #
# El tutorial
# --------------------------------------------------------------------------- #
#
# Lo escribe el bot, no un documento aparte: quien va a usar esto lo va a usar
# desde el móvil y desde esta misma conversación, así que el sitio donde se
# aprende tiene que ser el sitio donde se responde.
#
# 🔴 Va en el HUB y no en el kit. El kit aporta el criterio de cuándo preguntar;
# esto explica el TRANSPORTE —cómo llega y cómo se contesta— y el transporte es
# del hub. Si mañana el canal fuera Slack, el criterio seguiría valiendo y esto
# habría que reescribirlo entero.
#
# Son tres mensajes cortos y no uno largo: en un móvil un muro de texto se
# arrastra hasta el final sin leerse. El último pide practicar, porque un
# tutorial que no se practica no se recuerda.

TUTORIAL = [
    (
        "Hola 👋 Soy el bot de consulta de {dueno}.\n\n"
        "Cuando su asistente de programación tenga una duda que tú puedas "
        "resolver y él no esté disponible, te la mandaré por aquí. Tú contestas "
        "y sigue trabajando con tu respuesta.\n\n"
        "No hace falta que abras nada ni que sepas de código: las preguntas "
        "llegan enteras, con todo lo que hace falta para contestarlas."
    ),
    (
        "Dos cosas que conviene que sepas:\n\n"
        "• **No puedes darle órdenes.** Este canal sólo sirve para contestar a "
        "lo que se te pregunta; no hay forma de mandarle tareas ni de ver en qué "
        "está trabajando. Es a propósito.\n\n"
        "• **Contesta cuando puedas.** Si tardas o no contestas, no se rompe "
        "nada: la pregunta caduca y sigue sin ti. No hay guardias ni urgencias."
    ),
    (
        "Lo único que hay que hacer bien: **contesta con RESPONDER (reply)** "
        "sobre el mensaje de la pregunta.\n\n"
        "En Telegram: mantén pulsado el mensaje → Responder. En el ordenador: "
        "pasa el ratón por encima → Responder.\n\n"
        "Es importante porque puede haber varias preguntas abiertas a la vez, y "
        "así sé a cuál contestas. Un mensaje suelto, sin *responder*, se "
        "descarta — prefiero perderlo a apuntarlo en la pregunta equivocada.\n\n"
        "👉 **Practica ahora: contesta a ESTE mensaje con un «listo».**"
    ),
]

RESPUESTA_AL_ENSAYO = (
    "✅ Perfecto, así es. Eso es todo lo que hay que saber.\n\n"
    "A partir de ahora, cuando llegue una pregunta de verdad, contéstala igual."
)


def pedir_tutorial(con: sqlite3.Connection, user_id: int) -> None:
    """Encola el tutorial. Lo manda el relé, que es quien tiene el token.

    🔴 Sólo a quien ya está **activo**. Si se pudiera mandar a un `pendiente`,
    el hub tendría una forma de escribirle a cualquiera que le haya escrito al
    bot alguna vez — y el alta invertida existe justamente para que aparecer en
    la lista no dé derecho a nada.
    """
    usuario = ver_usuario(con, user_id)
    if not usuario:
        raise CanalInvalido(f"no hay ningún usuario {user_id}")
    if usuario["estado"] != "activo":
        raise CanalInvalido(
            "el tutorial sólo se le manda a alguien activo; apruébalo primero"
        )
    con.execute(
        "UPDATE canal_usuario SET tutorial='pedido' WHERE user_id=?", (int(user_id),)
    )
    registrar(con, "sale", "tutorial encolado", user_id=int(user_id))


def marcar_tutorial_enviado(
    con: sqlite3.Connection, user_id: int, message_id: int | None
) -> None:
    con.execute(
        "UPDATE canal_usuario SET tutorial=?, tutorial_msg=? WHERE user_id=?",
        (ahora(), message_id, int(user_id)),
    )


def esperan_tutorial(con: sqlite3.Connection) -> list[dict]:
    return [
        dict(f)
        for f in con.execute(
            "SELECT * FROM canal_usuario WHERE tutorial='pedido' AND estado='activo'"
        )
    ]


def por_mensaje_de_tutorial(con: sqlite3.Connection, message_id: int) -> dict | None:
    """Quién está contestando al ensayo del tutorial, si es que alguien lo hace."""
    fila = con.execute(
        "SELECT * FROM canal_usuario WHERE tutorial_msg=?", (int(message_id),)
    ).fetchone()
    return dict(fila) if fila else None


def dueno(con: sqlite3.Connection) -> dict | None:
    """A quién se le avisa de las preguntas que son para el dueño del hub.

    Es un usuario más del canal —tiene que haber escrito al bot, como todos— y
    lo marca él mismo en `/canal`. No sale de `canal.yml` porque esto no es
    configuración del transporte: es una persona concreta del alta.

    🔴 Al dueño no le viaja el contenido de nada, ni siquiera siendo el dueño.
    Sólo se le avisa de que hay una pregunta y la lee dentro. Es petición
    literal suya, y es lo que mantiene en la máquina todo lo que puede quedarse.
    """
    fila = con.execute(
        "SELECT * FROM canal_usuario WHERE es_dueno=1 ORDER BY user_id LIMIT 1"
    ).fetchone()
    return dict(fila) if fila else None


def marcar_dueno(con: sqlite3.Connection, user_id: int | None) -> None:
    """Uno solo, o ninguno. Dos dueños serían dos personas recibiendo avisos de
    lo que se decidió que no saliera de aquí."""
    con.execute("UPDATE canal_usuario SET es_dueno=0")
    if user_id is None:
        registrar(con, "sale", "ya no hay nadie marcado como dueño")
        return
    if not ver_usuario(con, user_id):
        raise CanalInvalido(f"no hay ningún usuario {user_id}: nadie ha escrito al bot")
    con.execute("UPDATE canal_usuario SET es_dueno=1 WHERE user_id=?", (int(user_id),))
    registrar(con, "sale", "marcado como dueño: recibirá los avisos", user_id=int(user_id))


def nombre_visible(usuario: dict | None) -> str:
    """Cómo se le llama en la interfaz y en el marco de la respuesta.

    El alias manda porque es lo único que no cambia su dueño. Si no lo hay se
    cae al `@username` y por último al id, que es feo pero nunca miente.
    """
    if not usuario:
        return "?"
    return (
        usuario.get("alias")
        or (f"@{usuario['username']}" if usuario.get("username") else "")
        or str(usuario.get("user_id", "?"))
    )


# --------------------------------------------------------------------------- #
# Permisos
# --------------------------------------------------------------------------- #


def permisos_de(con: sqlite3.Connection, user_id: int) -> list[dict]:
    return [
        dict(f)
        for f in con.execute(
            """SELECT p.*, pr.nombre AS proyecto_nombre
                 FROM canal_permiso p
                 LEFT JOIN proyecto pr ON pr.id = p.proyecto_id
                WHERE p.user_id=? ORDER BY pr.nombre, p.accion""",
            (int(user_id),),
        )
    ]


def conceder(con: sqlite3.Connection, user_id: int, proyecto_id: str, accion: str) -> None:
    if accion not in ACCIONES:
        raise CanalInvalido(
            f"«{accion}» no es una acción del canal. Son: {', '.join(ACCIONES)}."
        )
    if not api.obtener_proyecto(con, proyecto_id):
        raise CanalInvalido(f"no existe el proyecto «{proyecto_id}»")
    if not ver_usuario(con, user_id):
        raise CanalInvalido(f"no hay ningún usuario {user_id}: nadie ha escrito al bot")
    con.execute(
        """INSERT OR IGNORE INTO canal_permiso (user_id, proyecto_id, accion, dado_en)
           VALUES (?,?,?,?)""",
        (int(user_id), proyecto_id, accion, ahora()),
    )
    registrar(
        con, "sale", f"concedido {accion}", user_id=int(user_id), proyecto_id=proyecto_id
    )


def revocar(con: sqlite3.Connection, user_id: int, proyecto_id: str, accion: str) -> None:
    con.execute(
        "DELETE FROM canal_permiso WHERE user_id=? AND proyecto_id=? AND accion=?",
        (int(user_id), proyecto_id, accion),
    )
    registrar(
        con, "sale", f"revocado {accion}", user_id=int(user_id), proyecto_id=proyecto_id
    )


def puede(con: sqlite3.Connection, user_id: int, proyecto_id: str, accion: str) -> bool:
    """La única pregunta de autorización que existe. Sin fila, no.

    🔴 No hay comodines, no hay permiso global y no hay herencia entre proyectos.
    Cualquier atajo que se añada aquí —«si tiene X en algún proyecto, entonces…»—
    convierte una concesión concreta en una general sin que nadie lo decida.

    Y el estado del usuario manda sobre sus permisos: bloquear a alguien tiene
    que bastar, sin ir a borrarle las filas una por una.
    """
    usuario = ver_usuario(con, user_id)
    if not usuario or usuario["estado"] != "activo":
        return False
    return (
        con.execute(
            "SELECT 1 FROM canal_permiso WHERE user_id=? AND proyecto_id=? AND accion=?",
            (int(user_id), proyecto_id, accion),
        ).fetchone()
        is not None
    )


def exigir(con: sqlite3.Connection, user_id: int, proyecto_id: str, accion: str) -> None:
    """`puede`, pero denegando en voz alta y dejando rastro."""
    if not puede(con, user_id, proyecto_id, accion):
        registrar(
            con,
            "falla",
            f"denegado {accion}",
            user_id=int(user_id),
            proyecto_id=proyecto_id,
        )
        raise SinPermiso(f"{user_id} no tiene «{accion}» sobre «{proyecto_id}»")


def por_alias(con: sqlite3.Connection, quien: str) -> dict | None:
    """Encuentra a alguien por su alias, su @username o su id.

    Existe para que quien pregunta escriba `--a ana` y no un número de quince
    cifras: un identificador que hay que copiar de algún sitio se acaba copiando
    mal, y aquí equivocarse significa mandarle la pregunta a otra persona.
    """
    aguja = (quien or "").strip().lstrip("@").lower()
    if not aguja:
        return None
    for u in usuarios(con):
        candidatos = {
            str(u["user_id"]),
            (u["alias"] or "").lower(),
            (u["username"] or "").lower(),
        }
        if aguja in candidatos - {""}:
            return u
    return None


def destinatarios(con: sqlite3.Connection, proyecto_id: str) -> list[dict]:
    """A quién se le puede preguntar sobre este proyecto, hoy."""
    return [
        u
        for u in usuarios(con)
        if puede(con, u["user_id"], proyecto_id, "recibir-preguntas")
    ]


# --------------------------------------------------------------------------- #
# El ciclo de una pregunta
# --------------------------------------------------------------------------- #


def crear_pregunta(
    con: sqlite3.Connection,
    proyecto_id: str,
    texto: str,
    user_id: int | None = None,
    slot_id: int | None = None,
    pane_id: str | None = None,
    vence_en: str | None = None,
    lote: str | None = None,
) -> int:
    """Registra una pregunta. Todavía no la manda: eso es del relé.

    `user_id` a `None` significa **es para el dueño**, y ese caso se comporta
    distinto a propósito: a él sólo se le avisa de que hay una pregunta, el
    contenido no viaja y la lee en el hub. Es petición suya, y es lo que mantiene
    dentro de la máquina todo lo que puede quedarse dentro.
    """
    if not texto.strip():
        raise CanalInvalido("una pregunta vacía no se manda")
    if not api.obtener_proyecto(con, proyecto_id):
        raise CanalInvalido(f"no existe el proyecto «{proyecto_id}»")
    if user_id is not None:
        exigir(con, user_id, proyecto_id, "recibir-preguntas")

    cur = con.execute(
        """INSERT INTO canal_pregunta
             (proyecto_id, slot_id, pane_id, user_id, texto, estado, creada_en,
              vence_en, lote)
           VALUES (?,?,?,?,?, 'pendiente', ?, ?, ?)""",
        (proyecto_id, slot_id, pane_id, user_id, texto.strip(), ahora(), vence_en, lote),
    )
    pid = int(cur.lastrowid)
    registrar(
        con,
        "sale",
        "pregunta creada",
        user_id=user_id,
        proyecto_id=proyecto_id,
        pregunta_id=pid,
        cuerpo=texto.strip(),
    )
    return pid


def ver_pregunta(con: sqlite3.Connection, pregunta_id: int) -> dict | None:
    fila = con.execute(
        "SELECT * FROM canal_pregunta WHERE id=?", (int(pregunta_id),)
    ).fetchone()
    return dict(fila) if fila else None


# Las tres formas en que se busca una pregunta, y ninguna es un estado suelto.
#
# 🔴 «Contestada» es TENER respuesta, no estar en un estado concreto: los
# estados describen el TRANSPORTE —`entregada` dice que llegó al panel,
# `sin-confirmar` que se escribió sin poder confirmarlo—, así que filtrar por
# ellos dejaría fuera respuestas que existen. Y `sin-confirmar` es justo la que
# hay que poder revisar. Es la misma regla que ya sigue el panel de /trabajo.
SITUACIONES = {
    "pendientes": "respuesta = '' AND estado NOT IN ('vencida', 'archivada')",
    "contestadas": "respuesta <> ''",
    "atascadas": "estado IN ('sin-confirmar', 'vencida') OR detalle <> ''",
}


def preguntas(
    con: sqlite3.Connection,
    proyecto_id: str | None = None,
    estado: str | None = None,
    slot_id: int | None = None,
    situacion: str | None = None,
) -> list[dict]:
    sql = "SELECT * FROM canal_pregunta WHERE 1=1"
    args: list[Any] = []
    if proyecto_id:
        sql += " AND proyecto_id=?"
        args.append(proyecto_id)
    if estado:
        sql += " AND estado=?"
        args.append(estado)
    if slot_id is not None:
        sql += " AND slot_id=?"
        args.append(int(slot_id))
    # Del diccionario y nunca del parámetro: lo que llega es texto de una URL, y
    # concatenarlo sería dejar escribir SQL desde la barra de direcciones.
    if situacion in SITUACIONES:
        sql += f" AND ({SITUACIONES[situacion]})"
    filas = [dict(f) for f in con.execute(sql + " ORDER BY id DESC", args)]
    for f in filas:
        f["quien"] = nombre_visible(ver_usuario(con, f["user_id"])) if f["user_id"] else ""
    return filas


def cuenta_preguntas(con: sqlite3.Connection) -> int:
    """Cuántas hay en total, sin filtrar. Es contra esto contra lo que se sabe
    si un filtro está escondiendo algo."""
    return con.execute("SELECT COUNT(*) FROM canal_pregunta").fetchone()[0]


def marcar_enviada(con: sqlite3.Connection, pregunta_id: int, message_id: int | None) -> None:
    con.execute(
        "UPDATE canal_pregunta SET estado='enviada', enviada_en=?, message_id=? WHERE id=?",
        (ahora(), message_id, int(pregunta_id)),
    )


def por_message_id(con: sqlite3.Connection, message_id: int) -> dict | None:
    """La pregunta a la que contesta un *reply*. Sin esto no se casa nada.

    Es lo que permite que el relé sea central sin ser listo: no interpreta el
    contenido, sólo mira a qué mensaje responde. Y por eso una respuesta **sin**
    reply no se adivina — ver `anotar_respuesta`.
    """
    fila = con.execute(
        "SELECT * FROM canal_pregunta WHERE message_id=?", (int(message_id),)
    ).fetchone()
    return dict(fila) if fila else None


def anotar_respuesta(
    con: sqlite3.Connection, pregunta_id: int, user_id: int, texto: str
) -> dict:
    """Guarda lo que contestaron, tras comprobar que podían contestarlo.

    🔴 Dos comprobaciones y las dos importan: que tenga `responder` **sobre ese
    proyecto**, y que sea la persona a quien se le preguntó. Sin la segunda,
    alguien con permiso en el proyecto podría contestar preguntas dirigidas a
    otro, y el marco de la respuesta diría un nombre que no es el que decidió.
    """
    pregunta = ver_pregunta(con, pregunta_id)
    if not pregunta:
        raise CanalInvalido(f"no hay ninguna pregunta {pregunta_id}")

    exigir(con, user_id, pregunta["proyecto_id"], "responder")

    if pregunta["user_id"] is not None and int(pregunta["user_id"]) != int(user_id):
        registrar(
            con,
            "falla",
            "contestó alguien a quien no se le preguntó",
            user_id=int(user_id),
            proyecto_id=pregunta["proyecto_id"],
            pregunta_id=pregunta_id,
        )
        raise SinPermiso(f"la pregunta {pregunta_id} no era para {user_id}")

    if not texto.strip():
        raise CanalInvalido("una respuesta vacía no se anota")

    con.execute(
        """UPDATE canal_pregunta
              SET estado='respondida', respuesta=?, respondida_en=? WHERE id=?""",
        (texto.strip(), ahora(), int(pregunta_id)),
    )
    registrar(
        con,
        "entra",
        "respuesta",
        user_id=int(user_id),
        proyecto_id=pregunta["proyecto_id"],
        pregunta_id=int(pregunta_id),
        cuerpo=texto.strip(),
    )
    return ver_pregunta(con, pregunta_id)  # type: ignore[return-value]


def marcar_entregada(con: sqlite3.Connection, pregunta_id: int) -> None:
    con.execute(
        "UPDATE canal_pregunta SET estado='entregada', entregada_en=? WHERE id=?",
        (ahora(), int(pregunta_id)),
    )


def marcar_escrita_sin_confirmar(
    con: sqlite3.Connection, pregunta_id: int, motivo: str
) -> None:
    """El texto se escribió en el panel y no se pudo confirmar que saliera.

    🔴 Estado propio, y sale de la cola de reintentos a propósito: volver a
    escribir duplicaría una instrucción que probablemente ya llegó. Tampoco se
    marca `entregada`, que sería afirmar lo que no se sabe.

    Es el único estado que pide mirar: la respuesta está en el panel de alguien,
    quizá enviada y quizá esperando un Enter, y sólo un humano puede verlo. Por
    eso se enseña en `/canal` como aviso y no como éxito.
    """
    con.execute(
        "UPDATE canal_pregunta SET estado='sin-confirmar', detalle=?, entregada_en=? WHERE id=?",
        (motivo, ahora(), int(pregunta_id)),
    )
    pregunta = ver_pregunta(con, pregunta_id)
    registrar(
        con,
        "falla",
        f"escrita en el panel sin confirmar, NO se reintenta: {motivo}",
        proyecto_id=(pregunta or {}).get("proyecto_id"),
        pregunta_id=int(pregunta_id),
    )


def marcar_fallo_de_entrega(con: sqlite3.Connection, pregunta_id: int, motivo: str) -> None:
    """No se pudo escribir en el panel. La respuesta NO se pierde: se queda aquí.

    Pasa cuando el slot ya no tiene un Claude dentro, que es exactamente el caso
    para el que existe la verificación. Se deja en `respondida` a propósito: así
    sigue saliendo como pendiente de entregar y se puede reintentar cuando el
    panel vuelva, en vez de darla por consumida.
    """
    con.execute(
        "UPDATE canal_pregunta SET detalle=? WHERE id=?", (motivo, int(pregunta_id))
    )
    pregunta = ver_pregunta(con, pregunta_id)
    registrar(
        con,
        "falla",
        f"no se pudo entregar: {motivo}",
        proyecto_id=(pregunta or {}).get("proyecto_id"),
        pregunta_id=int(pregunta_id),
    )


def nombre_de_lote(proyecto_id: str) -> str:
    """Un nombre legible para un lote sin nombre. Se ve en el registro y en la
    pantalla, así que lleva el proyecto y el momento y no un identificador que
    no le diga nada a nadie."""
    marca = ahora().replace("-", "").replace(":", "").replace("+00:00", "")
    return f"{proyecto_id}-{marca}"


def preguntas_del_lote(con: sqlite3.Connection, lote: str) -> list[dict]:
    return [
        dict(f)
        for f in con.execute(
            "SELECT * FROM canal_pregunta WHERE lote=? ORDER BY id", (lote,)
        )
    ]


def lote_entregado(con: sqlite3.Connection, lote: str) -> bool:
    """Si el lote ya volvió al panel. Basta con que una lo haya hecho: se
    entrega entero de una vez."""
    return any(
        p["estado"] in ("entregada", "sin-confirmar")
        for p in preguntas_del_lote(con, lote)
    )


def lotes_listos(con: sqlite3.Connection, momento: str | None = None) -> list[str]:
    """Lotes cuyas respuestas ya pueden volver, juntas y en un solo turno.

    Un lote está listo cuando pasa **una de dos cosas**, y las dos son
    deterministas a propósito: o están todas contestadas, o venció el plazo. No
    se mira si la sesión está despierta ni cuánto lleva esperando nadie.

        todas contestadas   se entrega el lote entero
        venció el plazo     se entrega lo que haya, diciendo cuáles faltan

    El segundo caso es el del ejemplo de 4 respondidas de 5: sin él, una pregunta
    que nadie contesta retiene indefinidamente a las otras cuatro, y el trabajo
    se queda parado esperando lo que no va a llegar.

    Sólo se consideran lotes con algo que entregar: uno donde todavía no ha
    contestado nadie y aún no ha vencido no está listo, está esperando.
    """
    ahora_ = momento or ahora()
    listos: list[str] = []
    for fila in con.execute(
        "SELECT DISTINCT lote FROM canal_pregunta WHERE lote IS NOT NULL AND lote != ''"
    ):
        lote = fila["lote"]
        preguntas_ = preguntas_del_lote(con, lote)
        # 🔴 Ya entregado: el lote no se entrega dos veces. Sin esta guarda, una
        # respuesta que llegue DESPUÉS de un lote cerrado por vencimiento lo
        # volvería a dar por listo —las demás siguen sin contestar y el plazo ya
        # pasó— y se entregaría otra vez. Esa tardía vuelve sola, por
        # `reintentar_entregas`, y no arrastra al resto.
        if lote_entregado(con, lote):
            continue
        contestadas = [p for p in preguntas_ if p["estado"] == "respondida"]
        if not contestadas:
            continue
        vencido = any(
            p["vence_en"] and p["vence_en"] <= ahora_
            for p in preguntas_
            if p["estado"] != "respondida"
        )
        if len(contestadas) == len(preguntas_) or vencido:
            listos.append(lote)
    return listos


def vencidas(con: sqlite3.Connection, momento: str | None = None) -> list[dict]:
    """Preguntas enviadas cuyo plazo pasó sin respuesta.

    El plazo lo fija el pacto de la sesión, **no el hub** — y la diferencia no es
    semántica: un temporizador que decide por su cuenta choca con el principio 9,
    mientras que una contingencia acordada por escrito antes de ausentarse es el
    pacto ejecutándose. Por eso `vence_en` llega de fuera y aquí sólo se compara.
    """
    ahora_ = momento or ahora()
    return [
        dict(f)
        for f in con.execute(
            """SELECT * FROM canal_pregunta
                WHERE estado='enviada' AND vence_en IS NOT NULL AND vence_en <= ?
                ORDER BY vence_en""",
            (ahora_,),
        )
    ]


def marcar_vencida(con: sqlite3.Connection, pregunta_id: int) -> None:
    con.execute(
        "UPDATE canal_pregunta SET estado='vencida' WHERE id=?", (int(pregunta_id),)
    )
    registrar(con, "falla", "venció sin respuesta", pregunta_id=int(pregunta_id))


def archivar(con: sqlite3.Connection, pregunta_id: int) -> None:
    """Nadie contestó. Se archiva y el trabajo sigue: es el final acordado.

    No es un fallo del canal — es el comportamiento que ya había antes de que
    existiera, cuando las dudas esperaban al checkpoint.
    """
    con.execute(
        "UPDATE canal_pregunta SET estado='archivada' WHERE id=?", (int(pregunta_id),)
    )
    registrar(con, "sale", "archivada sin respuesta", pregunta_id=int(pregunta_id))
