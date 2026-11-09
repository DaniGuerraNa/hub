"""Avisar al teléfono del dueño: una capacidad con proveedores en cadena (decisiones 306 y 310).

Recordatorios, permisos pendientes, disparadores y la acción «avisar» llaman a
`mandar` y no saben por dónde sale. El orden se elige en `secretario.yml`
(`avisos: [webpush, telegram]`, que es el de por omisión): sale por el primero
que esté listo y no falle. Web Push es el canal propio —la app del teléfono—
y Telegram queda de respaldo.

Respaldo no es «caer en otro en silencio» (decisión 306): la cadena la elige
el dueño, el canal por el que salió queda en la bitácora, y un nombre que no
existe sigue siendo un error.
"""

from __future__ import annotations

from dataclasses import dataclass

from .. import piezas
from ..piezas import Proveedor

POR_OMISION = ["webpush", "telegram"]


@dataclass
class Aviso:
    texto: str
    #: La pantalla del hub que lo explica; tocar el aviso lleva ahí.
    enlace: str = "/secretario"
    #: Si es una solicitud de permiso, su id: el canal puede ofrecer
    #: Aprobar/Rechazar sin abrir la app.
    solicitud: int | None = None
    #: Falso para lo que no tiene vuelta atrás: eso se decide con la app
    #: abierta, viendo el detalle, nunca desde la pantalla bloqueada.
    decidir_desde_aviso: bool = False
    titulo: str = "Secretario"


class SinCanal(RuntimeError):
    """Ningún canal de la cadena pudo mandarlo. Lleva el porqué de cada uno."""


class Canal(Proveedor):
    """El contrato de un canal hacia el teléfono del dueño."""

    def mandar(self, aviso: Aviso) -> None:
        """Deja el aviso en camino, o lanza diciendo por qué no."""
        raise NotImplementedError


def cadena() -> list[Canal]:
    elegido = piezas.ajuste("avisos") or POR_OMISION
    if isinstance(elegido, str):
        elegido = [elegido]
    todos = piezas.proveedores("avisos")
    faltan = [c for c in elegido if c not in todos]
    if faltan:
        raise LookupError(f"avisos: no hay canal «{', '.join(faltan)}» (hay: {', '.join(sorted(todos))})")
    return [todos[c] for c in elegido]  # type: ignore[misc]


def actual() -> Canal:
    """El primero de la cadena que está listo (o el primero, si ninguno)."""
    canales = cadena()
    return next((c for c in canales if not c.disponible()), canales[0])


def mandar(texto: str, **kw) -> str:
    """Lo manda por el primer canal que pueda. Devuelve cuál fue."""
    aviso = Aviso(texto=texto, **kw)
    porque = []
    for c in cadena():
        falta = c.disponible()
        if falta:
            porque.append(f"{c.nombre}: {falta}")
            continue
        try:
            c.mandar(aviso)
            return c.id
        except Exception as exc:  # noqa: BLE001 — un canal roto deja paso al siguiente
            porque.append(f"{c.nombre}: {exc}")
    raise SinCanal("; ".join(porque) or "no hay canales")


def intentar(con, texto: str, que: str, *, reintenta: bool = False, **kw) -> str | None:
    """`mandar`, y que se sepa si no salió. Devuelve el canal, o None.

    Una sola política para los avisos que no pueden parar a quien los manda
    (C-0063): antes cada sitio tenía la suya y tres se tragaban el fallo con un
    `pass`, sin dejar nada en la bitácora. Lo que no sale se apunta con
    `ok=False` y queda en `avisos_error`, que es lo que la pantalla enseña
    arriba (como los recordatorios). Con `reintenta`, quien llama lo volverá a
    intentar en la vuelta siguiente: se apunta una vez por motivo, no cada 30 s.
    """
    from .. import memoria

    try:
        canal = mandar(texto, **kw)
    except (SinCanal, LookupError) as exc:
        repetido = memoria.leer(con, "avisos_error") == str(exc)
        memoria.poner(con, "avisos_error", str(exc))
        if not (reintenta and repetido):
            memoria.apuntar(con, que, params={"titulo": kw.get("titulo", "")},
                            resultado=f"no salió: {exc}", ok=False)
        return None
    memoria.poner(con, "avisos_error", None)
    return canal

