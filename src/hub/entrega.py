"""Escribir en el panel de un slot. La pieza delicada de todo el canal.

🔴 **Lee esto antes de tocar nada de aquí.**

La **regla dura 6** prohíbe inyectar teclas en un panel de tmux: su estado es
desconocido y pegar texto seguido de un Enter ejecuta lo que sea que haya en el
prompt. La **regla dura 15** abre una excepción **acotada** para el panel del
asistente, y la abre por un motivo concreto, no por comodidad: *ese panel lo crea
el hub y sabe que dentro corre `claude` y nada más*.

Ese motivo no es exclusivo del asistente. El hub también abre los slots
(`slots.abrir`, `autostart_claude`). Lo que faltaba para poder escribir ahí era
poder **comprobar la condición**, y desde el 2026-09-02 se puede: el glifo que
Claude Code pone en `pane_title` dice si sigue habiendo un Claude dentro
(`tmux.tiene_glifo_estado`) o si el usuario se salió a una shell.

Así que esto **no deroga la regla 15: cumple su condición en otro panel**. Y la
diferencia entre las dos cosas es entera:

🔴 **La comprobación va en el INSTANTE de escribir, nunca al abrir el slot.**
Entre abrir un slot y entregarle una respuesta pueden pasar horas, y en ese rato
el usuario puede haber salido de `claude`. Un permiso comprobado antes es un
permiso que ya no significa nada. Si falla, **no se escribe**: se registra y se
avisa, y la respuesta se queda guardada para reintentarla.
"""

from __future__ import annotations

from . import asistente, tmux


class PanelNoApto(RuntimeError):
    """Ahí no hay un Claude al que escribir. Lleva el motivo, para registrarlo.

    **No se tocó el panel.** Es lo que la distingue de `EscritoSinConfirmar`, y
    es lo que hace que reintentar sea seguro.
    """


class EscritoSinConfirmar(PanelNoApto):
    """El texto YA está en el panel; lo que no se pudo es confirmar que salió.

    🔴 Esto **no se reintenta escribiendo**. Reintentar repetiría un paso que ya
    tuvo efecto, y en un panel de Claude Code un duplicado no es un mensaje
    repetido: es una instrucción repetida, que puede hacer trabajo de más. Lo
    dice ya `asistente.despachar` para el Enter —*«se reintenta sólo la tecla,
    nunca el texto»*— y esto lleva la misma doctrina una capa más arriba, que es
    donde faltaba.

    Hereda de `PanelNoApto` para no romper a quien ya lo captura, así que **hay
    que atraparla ANTES**. Es la misma trampa del `HTTPError` que hereda de
    `URLError` y que ya mordió en el CLI: el orden de los `except` es la lógica.
    """


def panel_apto(pane_id: str) -> tuple[bool, str]:
    """Si en `pane_id` sigue corriendo un Claude Code que acepta entrada.

    Devuelve el motivo además del veredicto: quien deniega tiene que poder decir
    por qué, porque el usuario que se quedó sin su respuesta merece saberlo y
    porque «no se pudo entregar» a secas no se puede depurar.
    """
    try:
        titulo = tmux.titulo_panel(pane_id)
    except tmux.DestinoInvalido:
        return False, "el identificador de panel no es válido"
    except tmux.TmuxNoDisponible:
        return False, "tmux no responde"

    if titulo is None:
        return False, "el panel ya no existe"
    if not tmux.tiene_glifo_estado(titulo):
        # Ni braille ni ✳: ahí no hay una TUI de Claude Code reportando estado.
        # Es el caso real que esto existe para atrapar — el usuario salió de
        # `claude` y el panel es su shell.
        return False, "en ese panel ya no corre Claude Code"
    if not asistente.listo(pane_id):
        return False, "Claude Code está arrancando y todavía no acepta entrada"
    if asistente.ocupado(pane_id):
        # No se encola: Claude Code ya tiene su propia cola y duplicarla haría
        # que el hub creyera saber un orden que no controla. Se dice y se
        # reintenta en la siguiente vuelta del relé.
        return False, "está trabajando ahora mismo"
    return True, ""


def marcar(quien: str, referencia: str, texto: str) -> str:
    """Envuelve lo que dijo una persona de fuera antes de que entre al contexto.

    🔴 El marco NO es decoración: es información sobre la confianza del texto.
    Lo de dentro lo escribió alguien en un móvil — no es una instrucción del
    dueño del hub y no deroga el pacto de la sesión. Pegarlo en crudo lo volvería
    indistinguible de algo que dijo él, que es justo la confusión que un canal
    hacia fuera no se puede permitir.

    No neutraliza que un texto se lea como instrucción. Lo hace **visible** en el
    transcript, y con el registro, auditable.
    """
    limpio = texto.strip()
    return (
        f"Respuesta de «{quien}» por el canal de consulta, a {referencia}:\n"
        f"«{limpio}»"
    )


def marcar_lote(quien: str, respuestas: list[tuple[str, str]], sin_responder: list[str]) -> str:
    """El mismo marco, para las respuestas de un lote que vuelven juntas.

    Van en un solo mensaje porque cada entrega es un turno de Claude, y un turno
    relee el contexto entero: cinco respuestas sueltas son cinco despertares.

    Lo que **no** se calla es lo que falta. Un lote entregado por vencimiento
    llega incompleto, y decir sólo lo que llegó dejaría a Claude creyendo que
    tiene las cinco respuestas cuando tiene cuatro — que es peor que no entregar
    nada, porque no hay forma de notarlo desde dentro.
    """
    lineas = [
        f"Respuestas de «{quien}» por el canal de consulta ({len(respuestas)}):",
        "",
    ]
    for referencia, texto in respuestas:
        lineas += [f"— {referencia}:", f"«{texto.strip()}»", ""]
    if sin_responder:
        lineas += [
            "Sin respuesta al vencer el plazo, decide tú qué hacer con ellas:",
            *(f"— {r}" for r in sin_responder),
        ]
    return "\n".join(lineas).strip()


def entregar(pane_id: str, texto: str) -> None:
    """Escribe en el panel. Los dos fallos posibles NO son el mismo fallo.

    - `PanelNoApto`: no se tocó nada, y reintentar es seguro.
    - `EscritoSinConfirmar`: el texto ya está ahí. Reintentar lo duplicaría.

    Se comprueba primero y se escribe después, en ese orden y sin hueco entre
    medias: cualquier reorganización que pegue antes de verificar convierte esto
    en «el hub escribe en una shell», que es lo que la regla 6 prohíbe.
    """
    apto, motivo = panel_apto(pane_id)
    if not apto:
        raise PanelNoApto(motivo)

    # El Enter no va con el pegado. `despachar` espera a VER el texto en el
    # cuadro y sólo entonces pulsa (regla dura 17): escribir no es haber
    # enviado, y un «entregado» sobre un mensaje que sigue en pantalla es la
    # peor forma de fallar aquí porque nadie se entera.
    tmux.pegar_en_panel(pane_id, texto, enter=False)
    if not asistente.despachar(pane_id, texto):
        raise EscritoSinConfirmar("se escribió pero no se pudo confirmar que saliera")
