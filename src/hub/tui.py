"""Qué agente de terminal corre en un panel, y cómo se le lee el cuadro de entrada.

Existe porque la condición de la **regla dura 15** nunca fue «que sea Claude
Code»: es *que el hub sepa qué hay dentro del panel*, para no estar escribiendo
en una shell cuyo estado desconoce (regla 6). Claude Code era lo único que el
hub sabía reconocer, así que la regla se escribió con su nombre. Reconocer
también a Codex no afloja la condición — la cumple sobre otro programa.

🔴 La asimetría que gobierna este módulo: **`pane_current_command` sirve para
afirmar, nunca para negar.**

- Afirmar: si tmux dice que el proceso en primer plano es `codex`, ahí hay un
  Codex. Una shell en su prompt jamás reporta eso; lo lee tmux del tty y no lo
  pinta la aplicación, así que es una señal más fuerte que el glifo del título.
- Negar: no vale. Quien arranca un agente por un envoltorio o un alias hace que
  el comando diga `node` o `sh` con el agente vivo — está documentado en
  `tmux.tiene_glifo_estado` y es justo por lo que aquella comprobación mira el
  título. Por eso Claude Code se sigue reconociendo **también** por su glifo: el
  comando sólo suma casos, nunca quita ninguno.

Lo que este módulo **no** hace es adivinar. De Codex se sabe lo que se ha medido
en un panel real: su comando y la marca de su cuadro de entrada. No se declaran
marcas de sus diálogos de permiso porque no se han visto ninguna, y escribir
unas inventadas sería peor que no tenerlas: parecería que se comprueban.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import asistente, tmux


@dataclass(frozen=True)
class Agente:
    """Un agente de terminal que el hub sabe reconocer y al que sabe escribir."""

    id: str
    nombre: str
    comando: str
    prompt: str
    # Lo que la TUI pinta en el cuadro cuando está vacío. Sin esto, el marcador
    # de posición se leería como «hay texto escrito» y `despachar` daría por
    # bueno un envío que nunca salió.
    marcador: str = ""
    # Cómo se lee que está pensando. En Claude Code lo dice el spinner del
    # título; en Codex, una línea de la pantalla. Vacío significa que el hub no
    # sabe leerlo en ese agente — y no pasa nada: esta comprobación existe para
    # no duplicar SU cola, no por seguridad, porque el texto va al cuadro de
    # entrada y no a una shell.
    marca_ocupado: str = ""


# El suyo no es una marca de pantalla sino el spinner del título; se resuelve
# en `ocupado()` y por eso el campo queda vacío aquí.
CLAUDE = Agente("claude", "Claude Code", "claude", asistente.MARCA_LISTO)

# Todo medido en un panel real el 2026-09-12, ninguno supuesto:
#     pane_current_command  codex
#     cuadro vacío          «› Ask Codex to do anything»
#     trabajando            «• Working (18s • esc to interrupt)»
CODEX = Agente("codex", "Codex", "codex", "›",
               marcador="Ask Codex to do anything",
               marca_ocupado="esc to interrupt")

CONOCIDOS = (CLAUDE, CODEX)


# 🔴 Una shell en primer plano NIEGA, diga lo que diga el título (decisión 261).
#
# La asimetría de arriba —el comando afirma, nunca niega— tiene una excepción, y
# se pagó cara. Tras un reinicio, tmux-resurrect devuelve cada panel con su
# TÍTULO y su CONTENIDO de antes: un `bash` recién nacido lleva «✳ Estatus de
# Project R» y el cuadro `❯` de la sesión de Claude que hubo ahí. El glifo
# afirmaba Claude, `listo` veía el `❯`, y el orquestador pegó su mensaje en
# bash con Enter: cada línea se ejecutó como un comando. No rompió nada porque
# ninguna línea era una orden válida; fue suerte. Medido al día siguiente: once
# paneles `bash` con glifo ✳ heredado.
#
# Lo que el glifo cubre —Claude arrancado por un envoltorio— se ve como `node` o
# como `claude` (el envoltorio de la casa hace `exec`), nunca como una shell: una
# shell en primer plano es, por definición, un prompt esperando comandos.
SHELLS = frozenset({"bash", "sh", "zsh", "fish", "dash", "ksh", "tcsh", "csh"})


def detectar(pane_id: str) -> Agente | None:
    """Qué agente corre AHORA en ese panel. `None` si no se puede afirmar.

    🔴 Se llama en el instante de escribir, nunca antes. Es la comprobación
    entera de la regla 15: entre abrir un panel y escribirle pueden pasar horas,
    y en ese rato el usuario puede haber salido del agente a una shell.
    """
    comando = tmux.comando_de_panel(pane_id)
    if comando in SHELLS:
        return None
    for agente in CONOCIDOS:
        if comando == agente.comando:
            return agente

    # Y el glifo, que cubre a Claude Code arrancado por un envoltorio. Va
    # DESPUÉS: cuando las dos señales están, manda la fuerte.
    titulo = tmux.titulo_panel(pane_id)
    if titulo and tmux.tiene_glifo_estado(titulo):
        return CLAUDE
    return None


def cuadro(agente: Agente, pane_id: str) -> str:
    """Lo que hay escrito en el cuadro de entrada ahora mismo.

    Es lo que permite cumplir la regla dura 17 —escribir no es haber enviado—:
    se espera a VER el texto dentro y después se comprueba que se fue.
    """
    if agente is CLAUDE:
        # El de Claude Code se ancla en los bordes de su caja y tiene su propia
        # historia de falsos negativos medidos; no se reimplementa aquí.
        return asistente._cuadro(pane_id)

    lineas = tmux.capturar_panel(pane_id).splitlines()
    for linea in reversed(lineas):
        limpia = linea.strip()
        if not limpia.startswith(agente.prompt):
            continue
        contenido = limpia[len(agente.prompt):].strip()
        return "" if contenido == agente.marcador else contenido
    return ""


def listo(agente: Agente, pane_id: str) -> bool:
    """Si el cuadro de entrada está pintado y acepta texto."""
    if agente is CLAUDE:
        return asistente.listo(pane_id)
    return agente.prompt in tmux.capturar_panel(pane_id)


def ocupado(agente: Agente, pane_id: str) -> bool:
    """Si está pensando. `False` cuando el hub no sabe leerlo en ese agente.

    Devolver `False` ante la duda es seguro aquí y no lo sería en otras: esta
    comprobación no protege el panel —el texto va al cuadro de entrada, no a una
    shell—, sino que evita duplicar la cola que el propio agente ya tiene.
    """
    if agente is CLAUDE:
        return bool(asistente.ocupado(pane_id))
    if not agente.marca_ocupado:
        return False
    return agente.marca_ocupado in tmux.capturar_panel(pane_id)
