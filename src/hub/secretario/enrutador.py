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

3. **Y si el dueño nombra uno, manda él** (decisión 405, 11-nov: *«debería de
   poder él decidir qué modelo si yo se lo pido»*). Lo que admite elegir
   (`investigar`, `pedir_modelo_mayor`) pasa `pedido`; sin él, la tabla. Uno
   de `modelos.A_PETICION` (Fable) sólo con `a_peticion`, que da el código
   cuando él lo nombró en su mensaje, nunca el modelo de la conversación.
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
        propia = yaml.safe_load((memoria.carpeta(crear=False) / "modelos.yml").read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        propia = {}
    return POR_OMISION | {k: v for k, v in propia.items() if k in POR_OMISION and isinstance(v, str)}


def modelo(trabajo: str, pedido: str | None = None, *, a_peticion: bool = False) -> str:
    """El id exacto (decisión 91), comprobado contra el techo. `pedido` (alias
    o id): el que se eligió para este trabajo en vez del de la tabla (405).
    Lanza `ValueError` si no vale."""
    if pedido and str(pedido).strip():
        return modelos.resolver(str(pedido), a_peticion=a_peticion)
    return modelos.resolver(tabla().get(trabajo) or POR_OMISION[trabajo])


def esfuerzo(trabajo: str) -> str:
    return ESFUERZO.get(trabajo, "medium")


def por_que_no(pedido) -> str:
    """Por qué `pedido` no vale (lo que `modelo` rechazó), dicho para el modelo
    de la conversación: que lo sepa en el mismo turno y se lo diga a él."""
    pedido = str(pedido or "").strip()
    if modelos.ALIAS.get(pedido.lower(), pedido) in modelos.A_PETICION:
        return (f"«{pedido}» sólo si el dueño lo nombra en su mensaje (gasta su uso más rápido que Opus). Usa "
                f"otro, o dile que si lo quiere con ése te lo pida nombrándolo («con {pedido.lower()}»): un «sí» "
                "suelto no lo nombra.")
    return f"no conozco el modelo «{pedido}»: elige uno de {', '.join(modelos.PARA_QUE)}"
