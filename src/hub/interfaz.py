"""Qué interfaz ve cada aparato: la de siempre o la nueva, en vista previa (C-0169).

La interfaz nueva entra detrás de un interruptor **por aparato y apagado de
fábrica**: una cookie con una lista cerrada de valores. Sin ella —o con un
valor que no se conoce— se sirve la de siempre, sin un byte de diferencia.
Así se puede probar en el teléfono sin tocar el PC, y volver atrás es borrar
una cookie, no deshacer un despliegue.

No es un ajuste de `secretario.yml` ni de la base: la interfaz no es de
ningún módulo, y lo que elige un aparato no tiene por qué valer para otro.

🔴 **Módulo hoja, con fecha de salida.** Cuando el dueño dé por buena la
interfaz nueva pantalla a pantalla, la de siempre se retira y con ella este
módulo, el entorno doble de `web.py`, `POST /interfaz` y el bloque del pie de
la guía. Nada más debería importar de aquí. El catálogo de colores (`COLORES`,
`POST /interfaz/colores`) no se retira con ella: pasa a ser de la interfaz que
quede.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

COOKIE = "hub_interfaz"
CLASICA = "clasica"
NUEVA = "nueva"
#: Lista cerrada: lo que no esté aquí no se guarda ni se obedece.
INTERFACES = (CLASICA, NUEVA)

#: Lo que dura la elección en un aparato. Larga a propósito: quien la enciende
#: no quiere que se le apague sola al mes; se apaga con su botón.
DIAS_DE_COOKIE = 365


@dataclass(frozen=True)
class Juego:
    """Un juego de colores de la interfaz nueva.

    Los colores viven en su bloque `[data-colores="<clave>"]` de
    `templates/nueva/base.html`, no aquí. `lienzo` es lo único que hace falta
    fuera del CSS: el `theme-color`, que el navegador lee antes que la hoja.
    """

    nombre: str
    lienzo: str


COOKIE_COLORES = "hub_colores"
#: El catálogo, cerrado (C-0169, fase 1b). Un juego nuevo es su bloque de
#: tokens y su entrada aquí: nunca reglas propias. Todos oscuros (decisión 39).
#: Se llama «colores» porque «estilo» ya es el catálogo de `estilos.py` (285),
#: «paleta» la de órdenes y «tema» el de las notas.
COLORES: dict[str, Juego] = {
    "pizarra": Juego("Pizarra", "#11161d"),
    "brasa": Juego("Brasa", "#141318"),
}
#: Con el que se pinta quien no ha elegido: el que eligió el dueño.
DE_FABRICA = "pizarra"

_PLANTILLAS = Path(__file__).parent / "templates"


def carpeta(interfaz: str) -> Path:
    """Dónde viven las plantillas que una interfaz pone por delante de las de siempre."""
    return _PLANTILLAS / interfaz


def disponible() -> bool:
    """¿Están las plantillas de la interfaz nueva en esta instalación?

    Mientras sea una vista previa puede no viajar con lo que se publica: donde
    no está, el interruptor no se ofrece y la cookie no se obedece, en vez de
    dar un 500 al buscar una plantilla que no hay.
    """
    return (carpeta(NUEVA) / "base.html").is_file()


def valida(valor: object) -> bool:
    return isinstance(valor, str) and valor in INTERFACES


def elegida(cookies: Mapping[str, str] | None) -> str:
    """La interfaz de este aparato. Ausente, desconocida o no instalada → la de siempre."""
    valor = (cookies or {}).get(COOKIE)
    return NUEVA if valor == NUEVA and disponible() else CLASICA


def colores_validos(valor: object) -> bool:
    return isinstance(valor, str) and valor in COLORES


def colores_elegidos(cookies: Mapping[str, str] | None) -> str:
    """El juego de colores de este aparato. Ausente o desconocido → el de fábrica.

    Sólo lo mira la interfaz nueva: con la de siempre la cookie no pinta nada.
    """
    valor = (cookies or {}).get(COOKIE_COLORES)
    return valor if colores_validos(valor) else DE_FABRICA
