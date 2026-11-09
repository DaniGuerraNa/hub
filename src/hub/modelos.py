"""Qué modelo usa cada cosa que el hub arranca.

Está en un módulo propio porque es una **política**, no un detalle de cada
sitio: lo que el hub lanza no elige modelo por su cuenta, y quien quiera saber
con qué corre su máquina mira aquí, no cinco archivos.

🔴 **Nada que arranque el hub pasa de Sonnet, salvo el orquestador** (257). Sembrar la capa base, aplicar un
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

import re
import shlex
from dataclasses import dataclass, field

#: El que usan los agentes que lanza el hub (crear proyecto, aplicar kit, …).
AGENTE = "claude-sonnet-5"

# 🔴 La excepción, y con su fecha (decisión 257). El techo de Sonnet se puso
# cuando lo que el hub arrancaba era mecánico; el orquestador no lo es —parte
# una tarea en pasos, decide y le pide trabajo a las sesiones—, y las sesiones
# que abre hacen trabajo real de proyecto. Lo dijo él el 2026-09-22: *«esto sí
# necesita opus, no puede usar sonnet; esa regla era porque el alcance del hub
# en ese momento no era tan grande»*. Sigue siendo id exacto (decisión 91).
ORQUESTADOR = "claude-opus-5-5"
SESION_ORQUESTADA = "claude-opus-5-5"

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
        "claude-opus-5-5",
    }
)


# Lo que el orquestador puede elegir para una sesión, y con qué esfuerzo. Lo
# decide él (decisión 268): *«dale la facultad de cambiar el modelo y el effort
# cuando lo vea necesario»*. El techo sigue siendo `PERMITIDOS`.
ESFUERZOS = ("low", "medium", "high", "xhigh", "max")
ESFUERZO_SESION_ORQUESTADA = "high"

#: Los alias que acepta `./orq`, para que el orquestador no tenga que saberse
#: el id. Se traducen aquí al id exacto (decisión 91): el alias nunca llega a
#: `claude`.
ALIAS = {"opus": "claude-opus-5-5", "sonnet": "claude-sonnet-5", "haiku": "claude-haiku-4-5"}

# 🔴 A qué porcentaje de la ventana compacta solo lo que arranca el orquestador
# (decisión 267). Por omisión Claude Code espera casi al borde: la sesión de
# la sesión de un proyecto llegó al 96 % sin compactar tras siete horas, y el
# dueño la paró: *«a partir de un umbral de 70 el contexto ya es demasiado y
# puede dar errores»*. Medido el 2026-10-16 en 2.1.280: con la variable a 4 el
# auto-compact saltó al 5-6 %.
COMPACTAR_AL = 70


def entorno_de_sesion() -> dict[str, str]:
    """Las variables con las que nace cada `claude` que arranca el orquestador."""
    return {"CLAUDE_AUTOCOMPACT_PCT_OVERRIDE": str(COMPACTAR_AL)}


def resolver(modelo: str) -> str:
    """Alias o id → id exacto, comprobado contra el techo."""
    modelo = ALIAS.get((modelo or "").strip().lower(), (modelo or "").strip())
    bandera(modelo)
    return modelo


def bandera_esfuerzo(esfuerzo: str) -> str:
    if esfuerzo not in ESFUERZOS:
        raise ValueError(f"esfuerzo «{esfuerzo}» no válido. Válidos: {', '.join(ESFUERZOS)}")
    return f"--effort {esfuerzo}"


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


# ── La línea de `claude` (decisión 340) ─────────────────────────────────────
#
# Ocho sitios la armaban cada uno a su manera: tres metían su propio
# `env PATH=` además del de tmux, tres convertían el umbral de compactar en
# texto a mano, sólo uno validaba el `--resume` y uno podía sacar dos
# `--permission-mode`. Ahora la arma esto y nadie más
# (`test_solo_modelos_arma_la_linea_de_claude`).
#
# 🔴 **El PATH no es de la línea**: es de las primitivas de tmux
# (`tmux.con_entorno`, decisiones 81 y 339). Si la línea lo pusiera también,
# saldría dos veces, que es justo lo que se quitó.

#: Sin `--model`: sólo las ventanas del DUEÑO (sus slots y restaurar), que
#: eligen modelo él desde sus ajustes (decisión 149). Lo que el hub lanza solo
#: lleva siempre un id de `PERMITIDOS`.
HEREDA = None

#: Lo que acepta `--permission-mode`. `manual` lo rechaza la 2.1.112 (231):
#: está sólo porque `ajustar` repite el modo que midió en un proceso que ya
#: lo aceptó; ningún arranque nuevo del hub lo usa.
MODOS_PERMISO = ("default", "manual", "acceptEdits", "auto", "dontAsk", "plan", "bypassPermissions")

# El id que llega a una terminal es un UUID comprobado, no texto de la base.
_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


def es_sesion(sesion: str | None) -> bool:
    """Si es el id de una conversación de Claude Code. La única comprobación:
    la usan reanudar, la lista de conversaciones, el muestreo y los
    transcripts, que lo usan como nombre de archivo (C-0092)."""
    return bool(sesion) and bool(_UUID.match(sesion))


@dataclass(frozen=True)
class LineaClaude:
    """El comando y su entorno, por separado.

    Al lanzar, quien llama suma `entorno` al PATH y se lo da a la primitiva de
    tmux, que lo pone en un único `env`. Lo que se GUARDA en un slot (267) es
    `completa()`, para que una restauración lo vuelva a poner."""
    comando: str
    entorno: dict[str, str] = field(default_factory=dict)

    def completa(self) -> str:
        from . import tmux
        return tmux.con_entorno(self.comando, self.entorno)


def linea_claude(modelo: str | None, *, esfuerzo: str = "", permisos: str = "", reanudar: str = "",
                 prompt: str = "", compactar: bool = False, programa: str = "claude") -> LineaClaude:
    """La única forma de armar el `claude` que el hub lanza en tmux.

    `modelo` no tiene valor por omisión a propósito: heredar se escribe a la
    vista (`HEREDA`). El orden es fijo —programa, `--model`, `--effort`,
    `--permission-mode`, `--resume` y el prompt el último—, y la línea es
    siempre UN comando simple: `sh -c` hace `exec` del último, y así `claude`
    queda como proceso raíz del panel, que es de lo que dependen
    `tui.detectar` y `orquestador.ajustar` (200, 261, 268).

    `programa` sólo vale con `HEREDA`: es `HUB_COMANDO_CLAUDE` (266), una
    configuración de quien instala, nunca algo que llegue de una petición.
    """
    if programa != "claude" and modelo is not HEREDA:
        raise ValueError("un programa propio sólo para ventanas que heredan el modelo (266)")
    partes = [programa]
    if modelo is not HEREDA:
        partes.append(bandera(resolver(modelo)))
    if esfuerzo:
        partes.append(bandera_esfuerzo(esfuerzo))
    if permisos:
        if permisos not in MODOS_PERMISO:
            raise ValueError(f"modo de permisos «{permisos}» no válido. Válidos: {', '.join(MODOS_PERMISO)}")
        partes.append(f"--permission-mode {permisos}")
    if reanudar:
        if not es_sesion(reanudar):
            raise ValueError(f"«{reanudar}» no es un id de conversación")
        partes.append(f"--resume {reanudar}")
    if prompt:
        partes.append(shlex.quote(prompt))
    return LineaClaude(" ".join(partes), entorno_de_sesion() if compactar else {})


_BANDERAS_LEIDAS = {"--model": "modelo", "--effort": "esfuerzo", "--permission-mode": "permisos"}


def leer_linea(argv: list[str]) -> dict[str, str | None]:
    """La vuelta de `linea_claude`: modelo, esfuerzo y permisos de un `claude`
    ya lanzado (su `/proc/<pid>/cmdline`). Vive aquí, junto a quien la escribe,
    para que un cambio de formato rompa el test de ida y vuelta y no a
    `orquestador.ficha` en silencio (C-0093).

    Lee también lo que escribe una persona y el hub no: `--model=…` y
    `--dangerously-skip-permissions`. Lo que no está queda en None: medido, no
    supuesto (regla dura 13)."""
    datos: dict[str, str | None] = dict.fromkeys(_BANDERAS_LEIDAS.values())
    for i, arg in enumerate(argv):
        bandera_, igual, valor = arg.partition("=")
        if bandera_ in _BANDERAS_LEIDAS:
            if igual:
                datos[_BANDERAS_LEIDAS[bandera_]] = valor
            elif i + 1 < len(argv):
                datos[_BANDERAS_LEIDAS[bandera_]] = argv[i + 1]
    if "--dangerously-skip-permissions" in argv:
        datos["permisos"] = "bypassPermissions"
    return datos
