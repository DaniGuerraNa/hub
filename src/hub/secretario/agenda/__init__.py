"""La agenda del dueño: una capacidad con un proveedor (decisión 306).

Quien la usa —herramientas, acciones, disparadores— llama a estas funciones y
no sabe qué calendario hay detrás. Hoy hay dos: `google` (lee y crea) e
`ical`, la dirección secreta del calendario, que sólo lee (decisión 327). Otro
calendario es otro archivo aquí con `PROVEEDOR = …` y `agenda: <id>` en
`secretario.yml`.
"""

from __future__ import annotations

from datetime import datetime

from ..piezas import Proveedor, proveedor


class Calendario(Proveedor):
    """El contrato de un calendario. Las horas que recibe y da son locales."""

    #: Si `crear` puede salir bien. La dirección iCal sólo lee (327): con
    #: ella, poner algo en el calendario sólo podría fallar (C-0391).
    crea: bool = True

    def eventos(self, desde: datetime, hasta: datetime, n: int = 50) -> list[dict]:
        """[{id, titulo, inicio, fin, lugar, enlace}] entre dos instantes."""
        raise NotImplementedError

    def crear(self, titulo: str, inicio: str, fin: str | None = None, descripcion: str = "",
              minutos_aviso: int = 30) -> dict:
        """Crea y devuelve lo que el calendario dice que creó: {id, titulo, inicio, enlace}.

        🔴 Comprobado contra la respuesta del calendario (regla dura 17).
        """
        raise NotImplementedError

    def entrar(self) -> None:
        """Conectar la cuenta, interactivo, desde la terminal."""
        raise NotImplementedError


def actual() -> Calendario:
    """El de `agenda:` en `secretario.yml`. Sin elegir: Google si está conectado,
    y si no, la dirección iCal si la hay (decisión 327); si no hay ninguno,
    Google, que es el que dice qué falta para conectarlo."""
    from ..piezas import ajuste, proveedores
    if ajuste("agenda"):
        return proveedor("agenda", "google")  # type: ignore[return-value]
    todos = proveedores("agenda")
    for id_ in ("google", "ical"):
        p = todos.get(id_)
        if p is not None and p.disponible() is None:
            return p  # type: ignore[return-value]
    return proveedor("agenda", "google")  # type: ignore[return-value]


def disponible() -> str | None:
    p = actual()
    falta = p.disponible()
    return f"{p.nombre}: {falta}" if falta else None


def conectada(para_crear: bool = False) -> bool:
    """Si hay un calendario que leer ahora; con `para_crear`, uno en el que
    además se pueda crear (C-0391). Lo preguntan el prompt y la lista de
    herramientas (C-0408), que no pueden caerse por un `agenda:` que no
    existe en `secretario.yml`: eso cuenta como que no."""
    try:
        return disponible() is None and (not para_crear or actual().crea)
    except Exception:  # noqa: BLE001 — el porqué lo dice `disponible` a quien la use
        return False


def eventos(desde: datetime, hasta: datetime, n: int = 50) -> list[dict]:
    return actual().eventos(desde, hasta, n)


def crear(titulo: str, inicio: str, fin: str | None = None, descripcion: str = "",
          minutos_aviso: int = 30) -> dict:
    return actual().crear(titulo, inicio, fin, descripcion, minutos_aviso)
