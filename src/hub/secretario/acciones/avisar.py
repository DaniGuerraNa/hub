"""Mandarle algo al teléfono del dueño (definición 5.1).

Por el canal que el dueño eligió (`avisos`, decisión 306): la acción no sabe
si sale por Telegram o por otro sitio.

Riesgo `reversible` y no `sale-de-la-maquina` a propósito: el destinatario es
el propio dueño, y el contenido puede viajar porque él lo decidió así para el
secretario (decisión 298). `sale-de-la-maquina` queda para lo que llega a
otras personas, que es lo que no tiene vuelta atrás.
"""

from __future__ import annotations

from .. import avisos
from ..piezas import Accion


class Avisar(Accion):
    id = "avisar"
    gesto = "avisar"
    nombre = "Avisarte al teléfono"
    resumen = "Te manda un aviso corto al teléfono."
    descripcion = "Manda un aviso corto al teléfono del dueño."
    parametros = {"type": "object", "properties": {"texto": {"type": "string"}}, "required": ["texto"]}
    riesgo = "reversible"
    nivel_inicial = "auto"
    # El aviso sale de la máquina por el canal de avisos: un dato suyo en el
    # texto pide su sí antes (382, revisión cruzada del 7-nov).
    saca_datos = True

    def ejecutar(self, con, params):
        return f"aviso enviado por {avisos.mandar(params['texto'])}"


class ResumenDelDia(Accion):
    """Armado por script, sin modelo (decisión 308): agenda, vencidos, lo de hoy,
    lo que espera su sí y lo anotado desde ayer.

    Con `noche`, es el parte de la mañana (decisión 360): además lo que pasó, lo
    que falló y lo que espera de él en las últimas 24 h. Con `en_chat`, el texto
    entero va al chat del secretario y al teléfono sólo su primera línea, que
    lleva ahí: un parte largo no se lee en una notificación. Los dos los pone el
    dueño en su disparador; sin ellos, todo sigue como antes."""

    id = "resumen_del_dia"
    gesto = "avisar"
    nombre = "Mandarte el resumen del día"
    resumen = ("Agenda, lo que vence hoy, lo vencido y lo que espera tu sí, al teléfono. Con «noche», también lo "
               "que pasó y lo que falló en 24 h; con «en_chat», entero al chat y al teléfono sólo su primera línea.")
    descripcion = ("Manda al dueño el resumen del día (agenda, compromisos de hoy y vencidos, permisos pendientes, "
                   "notas nuevas): al teléfono, o con `en_chat` entero a este chat y al teléfono sólo la primera "
                   "línea. Con `noche`, es el parte: además lo que pasó, lo que falló y lo que le espera de las "
                   "últimas 24 h. Lo arma un script: úsalo tal cual, no lo reescribas.")
    parametros = {"type": "object", "properties": {
        "noche": {"type": "boolean", "description": "Añade lo que pasó, lo que falló y lo que te espera de las "
                                                    "últimas 24 h (el parte de la mañana)."},
        "en_chat": {"type": "boolean", "description": "El texto entero al chat; al teléfono, sólo la primera línea."},
    }}
    riesgo = "reversible"
    nivel_inicial = "auto"

    def ejecutar(self, con, params):
        from .. import conversacion, resumen
        texto = resumen.del_dia(con, noche=_si(params.get("noche")))
        if not _si(params.get("en_chat")):
            canal = avisos.mandar(texto, titulo="Tu día", enlace="/secretario?p=pendientes")
            return f"resumen enviado por {canal}:\n{texto}"
        turno = conversacion.decir(con, None, texto)
        # Ya está en el chat: si el aviso no sale, se apunta y no se reintenta
        # (C-0063); el parte no se pierde por eso. La primera línea del parte
        # es su titular; la del resumen de siempre sería «Agenda:», que sola no dice nada.
        corto = texto.split("\n", 1)[0] if _si(params.get("noche")) else "Tu resumen del día está en el chat."
        canal = avisos.intentar(con, corto, "resumen_del_dia", titulo="Tu día", enlace="/secretario")
        return (f"parte en el chat (turno {turno}); aviso "
                + (f"enviado por {canal}" if canal else "no salió") + f":\n{texto}")


def _si(valor) -> bool:
    """Lo que el dueño escribió en su disparador: `true`, o un «sí» a mano."""
    if isinstance(valor, str):
        return valor.strip().lower() in ("true", "sí", "si", "yes", "1")
    return bool(valor)


ACCIONES = [Avisar(), ResumenDelDia()]
