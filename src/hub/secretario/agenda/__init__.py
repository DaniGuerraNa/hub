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


def eventos(desde: datetime, hasta: datetime, n: int = 50) -> list[dict]:
    return actual().eventos(desde, hasta, n)


def crear(titulo: str, inicio: str, fin: str | None = None, descripcion: str = "",
          minutos_aviso: int = 30) -> dict:
    return actual().crear(titulo, inicio, fin, descripcion, minutos_aviso)
