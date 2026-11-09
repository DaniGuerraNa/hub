"""Qué modelo atiende cada trabajo (definición 0.4, decisión 301).

Lo pidió el dueño expresamente: *«no todo debe pasar por el mismo modelo,
depende la complejidad»*. Dos decisiones distintas, y sólo una cuesta algo:

1. **Por tipo de trabajo, con una tabla fija.** Clasificar un mensaje o
   resumir un hilo es mecánico y pasa cientos de veces al día: Haiku. Hablar
   con el dueño, Sonnet. Decidirlo no gasta nada.
2. **Dentro de la conversación, el modelo se escala a sí mismo** con la
   herramienta `pedir_modelo_mayor`: un turno que pide planificar o decidir con
   consecuencias pasa a Opus. Un clasificador delante de cada turno costaría
   una llamada más —~3,5 s medidos— en todos los turnos, también en los que no
   lo necesitan.

La tabla se puede cambiar en `HUB_HOME/secretario/modelos.yml` (p.ej.
`conversacion: haiku` para probar si basta con escalar), siempre dentro de
`modelos.PERMITIDOS`. Cada turno guarda qué modelo contestó y si escaló: es lo
que permite medir antes de afinar.
"""

from __future__ import annotations

import yaml

from .. import modelos
from . import memoria

POR_OMISION = {
    "triaje": "haiku",
    "cierre": "haiku",
    "conversacion": "sonnet",
    "consultas": "sonnet",
    "mayor": "opus",
    # Medido con haiku (385): una pregunta sencilla, 0,08-0,13 USD. Con otro
    # modelo, el tope de 0,50 no está medido.
    "investigar": "haiku",
}
#: El esfuerzo de pensar: poco para lo mecánico, lo normal para hablar.
ESFUERZO = {"triaje": "low", "cierre": "low", "conversacion": "medium", "consultas": "medium",
            "mayor": "high", "investigar": "medium"}


def tabla() -> dict[str, str]:
    try:
        propia = yaml.safe_load((memoria.carpeta() / "modelos.yml").read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        propia = {}
    return POR_OMISION | {k: v for k, v in propia.items() if k in POR_OMISION and isinstance(v, str)}


def modelo(trabajo: str) -> str:
    """El id exacto (decisión 91), comprobado contra el techo."""
    return modelos.resolver(tabla().get(trabajo) or POR_OMISION[trabajo])


def esfuerzo(trabajo: str) -> str:
    return ESFUERZO.get(trabajo, "medium")
