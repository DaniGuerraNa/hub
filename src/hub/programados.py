"""Mensajes programados: un texto que entra en el panel de un slot a una hora.

🔴 **Lee `entrega.py` antes de tocar esto.** Escribir en un panel de tmux está
prohibido por la regla dura 6, y la 15 abre una excepción **acotada** cuya
condición es que el hub sepa qué corre dentro — comprobado **en el instante de
escribir**, no antes.

Un mensaje programado es el caso extremo de esa regla, y por eso se construye
encima de `entrega.entregar` y nunca al lado: por definición se entrega cuando
**no hay nadie mirando**, horas después de escribirlo. Todo lo que se supiera
del panel al programarlo está caducado para cuando llega la hora. De ahí las dos
decisiones que gobiernan este módulo:

- **No se guarda el `pane_id`.** Se guarda el slot, y el panel se resuelve al
  entregar. Un `pane_id` de hace ocho horas puede ser hoy la shell de otra cosa.
- **`entrega.entregar` comprueba y escribe sin hueco entre medias.** Aquí no se
  replica esa comprobación ni se adelanta: se llama y se respeta su veredicto.

Lo que este módulo añade por su cuenta es **cuándo dejar de intentarlo**, que es
la parte que no existía. Un mensaje que no se pudo entregar a su hora no se
arrastra para siempre: tiene un plazo, y al pasarlo se declara caducado con su
motivo. Entregar «buenos días, empieza por los tests» a las cuatro de la tarde
es peor que no entregarlo, porque quien lo lee no tiene forma de saber que llega
tarde.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

from . import api, entrega

# 🔴 **Un intento y sólo uno.** Decisión suya, del 2026-09-12: *«prefiero que no
# se mande a que se manden 90 mensajes de reintentos»*.
#
# El caso que temía —entregado y la validación falla— ya no se reintentaba
# (`EscritoSinConfirmar` sale de la cola para siempre), y lo que sí se
# reintentaba era sólo aquello donde **no se había tocado el panel**. Pero su
# conclusión se sostiene igual: en el sitio más peligroso del proyecto, un
# intento único es lo que se puede razonar entero de una vez, y el precio —un
# mensaje que no sale porque justo a esa hora el agente estaba pensando— es
# recuperable. Noventa mensajes inyectados no.
#
# Y el intento se registra ANTES de tocar el panel (`_ESTADO_INTENTANDO`), no
# después: si el proceso muriera entre escribir y guardar, un `pendiente`
# superviviente volvería a entrar en la cola y **eso** sí sería un duplicado.
_ESTADO_INTENTANDO = "entregando"

# Cuánto se admite de retraso sobre la hora pedida. Pasado, ni se intenta: el
# mensaje ya no es el mensaje que se escribió. Es lo que cubre el caso de la
# máquina apagada — arrancar a las once y soltar el «buenos días» de las nueve.
PLAZO_MINUTOS = 30

# 🔴 No se antepone NADA al texto. Se probó con una línea diciendo cuándo se
# escribió y él la quitó: «espero solo el texto limpio». Tiene razón y el motivo
# es del dominio, no de estilo — lo que va al cuadro de un agente es una
# instrucción, y una línea de metadatos delante es contexto que él no escribió y
# que el agente tiene que interpretar.
#
# Es distinto del marco de `entrega.marcar`, que sí envuelve: aquello viene de
# otra persona por Telegram y **tiene** que distinguirse de una instrucción suya
# (regla dura 22). Esto lo escribió él; marcarlo sería mentir en la otra
# dirección.


class SlotDesconocido(ValueError):
    """No se programa contra un slot que no existe: no habría dónde entregarlo."""


def ahora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _momento(valor: str | None) -> datetime:
    """Un ISO a `datetime` con zona. Sin zona se asume UTC, como toda la base."""
    fecha = datetime.fromisoformat(valor or ahora())
    return fecha if fecha.tzinfo else fecha.replace(tzinfo=timezone.utc)


def _legible(iso: str) -> str:
    """Para el texto que ve Claude. En UTC y dicho, no en una hora local muda."""
    try:
        return _momento(iso).strftime("%d/%m a las %H:%M UTC")
    except ValueError:
        return iso


def normalizar(cuando: str) -> str:
    """La hora que llega de fuera, en UTC y con formato de la base.

    🔴 Se exige zona horaria explícita. El navegador la pone (manda un ISO con
    `Z`) y el CLI también puede; aceptar una hora desnuda obligaría al servidor a
    elegir una zona por su cuenta, y en esta máquina —CST, UTC−6— elegir mal no
    es un detalle de formato: son seis horas de diferencia entre lo que alguien
    quiso decir y lo que el hub haría.
    """
    texto = (cuando or "").strip()
    if not texto:
        raise ValueError("hace falta una hora")
    try:
        fecha = datetime.fromisoformat(texto.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"«{cuando}» no es una fecha que se pueda leer") from exc
    if fecha.tzinfo is None:
        raise ValueError(
            f"«{cuando}» no dice en qué zona horaria es. Manda la hora con zona "
            "(por ejemplo terminada en Z si es UTC): el hub no la adivina."
        )
    return fecha.astimezone(timezone.utc).isoformat(timespec="seconds")


def crear(con: sqlite3.Connection, slot_id: int, texto: str, cuando: str) -> int:
    """Programa un mensaje. Devuelve su id.

    No se comprueba que el slot esté abierto **a propósito**: programar algo para
    dentro de ocho horas sobre una ventana que ahora mismo está cerrada es un uso
    normal, y exigir que esté abierta convertiría «prográmalo para mañana» en un
    error. Lo que sí se exige es que el slot exista, porque un mensaje sin
    destino no se puede entregar nunca y fallar al final es fallar tarde.
    """
    limpio = (texto or "").strip()
    if not limpio:
        raise ValueError("un mensaje vacío no se programa")
    if not api.obtener_slot(con, slot_id):
        raise SlotDesconocido(f"no hay ningún slot {slot_id}")

    cur = con.execute(
        """INSERT INTO mensaje_programado (slot_id, texto, cuando, creado_en)
           VALUES (?,?,?,?)""",
        (slot_id, limpio, normalizar(cuando), ahora()),
    )
    return int(cur.lastrowid)


def cancelar(con: sqlite3.Connection, mensaje_id: int) -> bool:
    """Sólo se cancela lo que aún no ha pasado por el panel.

    Un `entregado` o un `sin-confirmar` ya tuvo efecto: marcarlos «cancelado»
    reescribiría la historia y dejaría la pantalla diciendo que no pasó algo que
    sí pasó.
    """
    cur = con.execute(
        "UPDATE mensaje_programado SET estado='cancelado' WHERE id=? AND estado='pendiente'",
        (mensaje_id,),
    )
    return cur.rowcount > 0


def pendientes(con: sqlite3.Connection, momento: str | None = None) -> list[dict]:
    """Los que ya tocan: pendientes cuya hora llegó."""
    return [
        {k: f[k] for k in f.keys()}
        for f in con.execute(
            """SELECT * FROM mensaje_programado
               WHERE estado='pendiente' AND cuando <= ?
               ORDER BY cuando""",
            (momento or ahora(),),
        )
    ]


def _cerrar(con: sqlite3.Connection, mensaje_id: int, estado: str, motivo: str,
            momento: str) -> None:
    con.execute(
        """UPDATE mensaje_programado
           SET estado=?, motivo=?, intentado_en=?,
               entregado_en = CASE WHEN ?='entregado' THEN ? ELSE entregado_en END
           WHERE id=?""",
        (estado, motivo, momento, estado, momento, mensaje_id),
    )


def entregar_uno(con: sqlite3.Connection, mensaje: dict, momento: str | None = None) -> str:
    """Intenta entregar uno, **una vez**. Devuelve el estado en que queda.

    Cuatro desenlaces, todos definitivos:

    - **`entregado`**: salió y se vio salir (`entrega` lo confirma, regla 17).
    - **`caducado`**: pasó el plazo. No se toca el panel siquiera.
    - **`no-entregado`**: el panel no estaba apto —no corre ningún agente, no hay
      ventana abierta, estaba trabajando—. **No se escribió nada**, así que
      reintentar sería seguro; no se hace porque él prefiere que no salga a que
      salga noventa veces. Queda con su motivo para reprogramarlo a mano.
    - **`sin-confirmar`**: 🔴 el texto YA está en el panel y no se pudo confirmar
      que saliera. Aquí reintentar nunca fue una opción: en un agente, un
      duplicado no es un mensaje repetido sino una instrucción repetida.
    """
    momento = momento or ahora()

    if _momento(momento) - _momento(mensaje["cuando"]) > timedelta(minutes=PLAZO_MINUTOS):
        _cerrar(con, mensaje["id"], "caducado",
                f"pasó el plazo de {PLAZO_MINUTOS} min; no se intentó entregarlo",
                momento)
        return "caducado"

    # 🔴 Sale de la cola ANTES de tocar nada. A partir de esta línea, pase lo que
    # pase —una excepción, un `kill -9` a mitad—, este mensaje no se vuelve a
    # intentar. Es lo único que convierte «un intento» en una garantía y no en
    # una intención.
    con.execute(
        "UPDATE mensaje_programado SET estado=?, intentado_en=? WHERE id=?",
        (_ESTADO_INTENTANDO, momento, mensaje["id"]),
    )

    panel = api.panel_de_slot(con, mensaje["slot_id"])
    if not panel:
        _cerrar(con, mensaje["id"], "no-entregado",
                "el slot no tenía ninguna ventana abierta a esa hora", momento)
        return "no-entregado"

    try:
        entrega.entregar(panel["pane_id"], mensaje["texto"])
    except entrega.EscritoSinConfirmar as exc:
        # 🔴 ANTES que `PanelNoApto`, del que hereda. El orden de los `except` ES
        # la lógica: al revés, esto se registraría como «no se escribió nada»
        # sobre un panel donde el texto ya está puesto.
        _cerrar(con, mensaje["id"], "sin-confirmar", str(exc), momento)
        return "sin-confirmar"
    except entrega.PanelNoApto as exc:
        _cerrar(con, mensaje["id"], "no-entregado", str(exc), momento)
        return "no-entregado"

    _cerrar(con, mensaje["id"], "entregado", "", momento)
    return "entregado"


def entregar_pendientes(con: sqlite3.Connection, momento: str | None = None) -> dict:
    """El tic. Lo llama el snapshotter, que es lo único que late siempre.

    Devuelve el recuento por estado, que es lo que se registra: un tic que no
    dice qué hizo no se puede depurar desde fuera.
    """
    momento = momento or ahora()
    recuento: dict[str, int] = {}
    for mensaje in pendientes(con, momento):
        estado = entregar_uno(con, mensaje, momento)
        recuento[estado] = recuento.get(estado, 0) + 1
    return recuento
