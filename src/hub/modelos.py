"""Qué modelo usa cada cosa que el hub arranca.

Está en un módulo propio porque es una **política**, no un detalle de cada
sitio: lo que el hub lanza no elige modelo por su cuenta, y quien quiera saber
con qué corre su máquina mira aquí, no cinco archivos.

🔴 **Nada que arranque el hub pasa de Sonnet.** Sembrar la capa base, aplicar un
kit o crear un proyecto es trabajo mecánico —copiar archivos declarados, escribir
un `kits.yml`, medir deriva—, y decisión suya: *«nada del hub debería usar más de
sonnet, las operaciones no son complejas»*. Un modelo más caro ahí no hace el
trabajo mejor; sólo lo hace más caro y más lento.

🔴 **Y nunca se hereda el modelo del entorno.** `claude` sin `--model` toma el
`"model"` de `~/.claude/settings.json`, que es un ajuste del USUARIO para SUS
ventanas. Medido el 2026-09-03: con `"model": "fable"` ahí, cada ventana que
abría el hub nacía en `claude-fable-5-1` sin que nada lo dijera, y una de ellas
murió antes de empezar con «*There's an issue with the selected model (fable)*».
Un agente que el hub lanza y nadie mira no puede depender de un ajuste que
cambia por fuera.

Va el **id exacto** y no el alias (decisión 91): el alias `sonnet` resolvió unas
veces a Sonnet 4.6 y otras a Sonnet 5 en la misma tarde, y son ventanas de 200k y
de 1M. El fallo de arriba lo dio precisamente un alias.
"""

from __future__ import annotations

import shlex

#: El que usan los agentes que lanza el hub (crear proyecto, aplicar kit, …).
AGENTE = "claude-sonnet-5"

#: El asistente. Mismo techo, decisión propia (74): *«por ahora dejemos sonnet
#: para el asistente, y vemos qué tal se comporta»*.
ASISTENTE = "claude-sonnet-5"

#: Lo que el hub puede arrancar. Es un TECHO, no un catálogo: que un modelo no
#: esté aquí no significa que no exista, significa que el hub no lo lanza.
#: Añadir uno por encima de Sonnet es una decisión suya, no un descuido.
PERMITIDOS = frozenset(
    {
        "claude-sonnet-5",
        "claude-sonnet-4-6",
        "claude-haiku-4-5",
    }
)


def bandera(modelo: str) -> str:
    """`--model <id>`, listo para pegar en una línea de comandos.

    Se comprueba contra `PERMITIDOS` aquí y no en quien llama: un modelo que se
    cuele por un parámetro tiene que morir en el mismo sitio que uno cableado.
    """
    if modelo not in PERMITIDOS:
        raise ValueError(
            f"el hub no arranca «{modelo}»: fuera de la política de modelos. "
            f"Permitidos: {', '.join(sorted(PERMITIDOS))}"
        )
    return f"--model {shlex.quote(modelo)}"
