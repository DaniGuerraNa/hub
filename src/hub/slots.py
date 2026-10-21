"""Mutaciones sobre slots y bandeja de entrada.

El hub informa, no gestiona (principio 9): archivar y borrar son siempre acciones
manuales. No hay expiración, ni avisos, ni nada automático.
"""

from __future__ import annotations

import re
import shlex
import sqlite3
import time
from pathlib import Path

from . import api, restauracion, tmux
from .snapshotter import ahora

# Lo que tmux no admite en un nombre de sesión, igual que en `agentes`.
_NO_VALIDO = re.compile(r"[^\w.\-]+")


def crear(
    con: sqlite3.Connection,
    proyecto_id: str,
    nombre: str,
    ruta: str | None = None,
    nota: str = "",
    comando: str | None = None,
    autostart_claude: bool = False,
) -> int:
    cur = con.execute(
        """INSERT INTO slot (proyecto_id, nombre, ruta, nota, comando,
                             autostart_claude, status, creado_en)
           VALUES (?,?,?,?,?,?,'activo',?)""",
        (proyecto_id, nombre, ruta, nota, comando, int(autostart_claude), ahora()),
    )
    return int(cur.lastrowid)


def editar(con: sqlite3.Connection, slot_id: int, **campos) -> None:
    permitidos = {"nombre", "ruta", "nota", "comando", "autostart_claude",
                  "proyecto_id", "restaurar"}
    cambios = {k: v for k, v in campos.items() if k in permitidos and v is not None}
    if not cambios:
        return
    for bandera in ("autostart_claude", "restaurar"):
        if bandera in cambios:
            cambios[bandera] = int(bool(cambios[bandera]))
    asignaciones = ", ".join(f"{k}=?" for k in cambios)
    con.execute(
        f"UPDATE slot SET {asignaciones} WHERE id=?", (*cambios.values(), slot_id)
    )


def archivar(con: sqlite3.Connection, slot_id: int) -> None:
    con.execute("UPDATE slot SET status='archivado' WHERE id=?", (slot_id,))


def desarchivar(con: sqlite3.Connection, slot_id: int) -> None:
    con.execute("UPDATE slot SET status='activo' WHERE id=?", (slot_id,))


def borrar(con: sqlite3.Connection, slot_id: int) -> None:
    con.execute("DELETE FROM slot WHERE id=?", (slot_id,))


def vincular(con: sqlite3.Connection, pane_id: str, slot_id: int) -> None:
    """Ata un panel a un slot, dentro del epoch actual del servidor de tmux.

    🔴 **El epoch se le pregunta a tmux, no al último snapshot.** Antes salía
    por un `return` mudo cuando no había snapshot, y eso es una instalación
    recién arrancada: tmux abierto hace un instante, el snapshotter todavía sin
    su primera vuelta. En ese hueco la ventana se abría, el binding no se
    escribía **y nadie lo decía** (regla dura 21), así que el panel no recibía
    su `slot_id` nunca — el snapshot siguiente lee `binding`, y si está vacío no
    hay de dónde sacarlo. El síntoma quedaba tres capas más allá: un slot
    abierto y vivo al que el hub no sabe entregarle nada, para siempre.

    La fila del snapshot vigente se sigue actualizando si lo hay, porque es lo
    que hace que la vista de trabajo lo enseñe atado **sin esperar 20 s**.
    """
    actual = api.snapshot_actual(con)
    pid = tmux.servidor_pid()
    if pid is None:
        # Sin tmux alcanzable se usa el último epoch conocido. No es adivinar:
        # es exactamente lo que se hacía antes, y sigue siendo lo correcto
        # cuando quien vincula es la UI sobre paneles que salen de un muestreo.
        pid = actual["server_pid"] if actual else None
    if pid is None:
        return
    con.execute(
        """INSERT INTO binding (pane_id, server_pid, slot_id, visto_en)
           VALUES (?,?,?,?)
           ON CONFLICT(pane_id, server_pid) DO UPDATE SET
             slot_id=excluded.slot_id, visto_en=excluded.visto_en""",
        (pane_id, pid, slot_id, ahora()),
    )
    if actual and actual["server_pid"] == pid:
        con.execute(
            "UPDATE panel SET slot_id=? WHERE snapshot_id=? AND pane_id=?",
            (slot_id, actual["id"], pane_id),
        )


def desvincular(con: sqlite3.Connection, pane_id: str) -> None:
    """Suelta un panel de su slot y lo devuelve a la bandeja.

    La nota **no se toca**: vive en el slot, y el slot sigue existiendo con ella.
    Esto sólo deshace el «esta ventana es aquel trabajo», que es lo que se hace
    por error. Sin esta acción, vincular era irreversible: el único arreglo era
    moverlo a otro slot, y si no había otro, ninguno.
    """
    actual = api.snapshot_actual(con)
    if not actual:
        return
    con.execute(
        "DELETE FROM binding WHERE pane_id=? AND server_pid=?",
        (pane_id, actual["server_pid"]),
    )
    con.execute(
        "UPDATE panel SET slot_id=NULL WHERE snapshot_id=? AND pane_id=?",
        (actual["id"], pane_id),
    )


def promover(con: sqlite3.Connection, pane_id: str, nombre: str) -> int | None:
    """Convierte un panel de la bandeja en un slot nuevo del proyecto que lo contiene."""
    actual = api.snapshot_actual(con)
    if not actual:
        return None
    fila = con.execute(
        "SELECT * FROM panel WHERE snapshot_id=? AND pane_id=?", (actual["id"], pane_id)
    ).fetchone()
    if not fila or not fila["proyecto_id"]:
        return None
    slot_id = crear(
        con, fila["proyecto_id"], nombre or fila["etiqueta"], ruta=fila["cwd"]
    )
    # `vincular` reasigna aunque el panel ya tuviera slot, así que esto vale
    # también para SEPARAR una ventana de un slot compartido: se le da uno
    # propio y el anterior conserva su nota y sus otras ventanas.
    vincular(con, pane_id, slot_id)
    return slot_id


def descartar(con: sqlite3.Connection, pane_id: str) -> None:
    actual = api.snapshot_actual(con)
    if not actual:
        return
    con.execute(
        "INSERT OR IGNORE INTO descartado (pane_id, server_pid) VALUES (?,?)",
        (pane_id, actual["server_pid"]),
    )


def abrir(con: sqlite3.Connection, slot_id: int, session: str | None = None,
          conservar_al_morir: bool = False) -> str | None:
    """Lanza el slot en tmux. Lanzar es abrir la ventana; mirarla y escribir en ella
    es cosa de la terminal embebida (decisión 34, que revocó la 16).

    🔴 **Crea la sesión si no hay ninguna.** Hasta el 3-sep esto era un
    `new-window` a secas, que exige un servidor de tmux corriendo. En una máquina
    recién instalada —tmux está, nadie lo ha abierto— tmux contestaba «error
    connecting», el manejador se lo tragaba y el botón «Lanzar» no hacía nada:
    la primera persona que instaló el hub creó un slot y no consiguió abrir una
    terminal. Aquí nunca pasó porque aquí siempre hay tmux abierto.

    Y la ruta cae al asiento del proyecto cuando el slot no tiene la suya: «creé
    el slot sobre el proyecto» es exactamente eso.
    """
    slot = api.obtener_slot(con, slot_id)
    if not slot:
        return None
    ruta = slot["ruta"]
    if not ruta:
        proyecto = api.obtener_proyecto(con, slot["proyecto_id"])
        ruta = (proyecto or {}).get("asiento")
    if not ruta:
        raise ValueError(
            f"«{slot['nombre']}» no tiene ruta y su proyecto no tiene asiento: "
            "no hay dónde abrir la ventana."
        )
    comando = slot["comando"]
    if not comando and slot["autostart_claude"]:
        # Un slot es TU ventana de trabajo, no un agente del hub: la abres, la
        # miras y eliges tú con qué modelo trabajar, desde
        # `~/.claude/settings.json` o con `/model`. Si un slot concreto quiere
        # otro, se le pone en `slot["comando"]`. La política de `modelos.py`
        # cubre lo que el hub lanza por su cuenta, que es lo que nadie mira.
        comando = "claude"  # modelo: hereda — a propósito, ver arriba

    if comando:
        # 🔴 El PATH del usuario DENTRO del comando (regla dura 18, decisión
        # 231). Ni el `-e` de `new-session` alcanza al primer panel ni el de
        # `new-window` al proceso: medido, la ventana sale con el PATH del
        # cliente que la pidió, y desde un servicio de systemd ese PATH
        # encuentra `/usr/bin/claude` —otra versión— en vez del suyo. `env`
        # hace `exec`, así que `pane_current_command` sigue diciendo `claude`.
        comando = f"env PATH={shlex.quote(tmux.path_de_usuario())} {comando}"
    if not session or not tmux.existe_sesion(session):
        session = sesion_para(con, slot["proyecto_id"])
    if tmux.existe_sesion(session):
        pane_id = tmux.abrir_ventana(ruta, slot["nombre"], comando, session,
                                     conservar=conservar_al_morir)
    else:
        # El PATH de usuario, o `claude` no está: `hub-web` corre bajo systemd
        # y su PATH no trae `~/.local/bin` (decisión 81).
        tmux.nueva_sesion(session, ruta, slot["nombre"], comando,
                          entorno={"PATH": tmux.path_de_usuario()},
                          conservar=conservar_al_morir)
        pane_id = tmux.panel_de_sesion(session)
    if pane_id:
        vincular(con, pane_id, slot_id)
        try:
            tmux.escribir_titulo(pane_id, slot["nombre"])
        except Exception:
            pass  # el título es cosmético; no debe tumbar la apertura
    return pane_id


def abrir_en(ruta: str, nombre: str, session: str, texto: str = "") -> str:
    """Una ventana de tmux en esa carpeta, con el comando escrito y SIN Enter.

    Es el tercer caso de la regla dura 15 y el mismo de «Restaurar» (decisión
    164): **crear la ventana y escribir en ella son la misma operación**, así
    que la shell acaba de nacer y no hay hueco temporal que verificar. Sin Enter
    jamás: eso es lo que lo hace inofensivo — deja la orden a la vista para que
    la lance una persona, que es el gate humano del principio 6.

    Y por eso el navegador de archivos puede ofrecerlo sin dejar de cumplir la
    decisión 203: abrir una ventana no es ejecutar nada.
    """
    if tmux.existe_sesion(session):
        pane_id = tmux.abrir_ventana(ruta, nombre, None, session)
    else:
        # El PATH de usuario: `hub-web` corre bajo systemd (decisión 81).
        tmux.nueva_sesion(session, ruta, nombre, None,
                          entorno={"PATH": tmux.path_de_usuario()})
        pane_id = tmux.panel_de_sesion(session)
    if not pane_id:
        raise ValueError("tmux no devolvió el panel de la ventana nueva")

    try:
        tmux.escribir_titulo(pane_id, nombre)
    except Exception:
        pass  # el título es cosmético; no debe tumbar la apertura

    if texto:
        # 🔴 Si la escritura llega tarde, se dice: una ventana con el comando a
        # medias es peor que una ventana vacía (regla dura 15).
        tmux.pegar_en_panel(pane_id, texto, enter=False)
        _esperar_a_verlo(pane_id, texto)
    return pane_id


def sesion_para(con: sqlite3.Connection, proyecto_id: str) -> str:
    """Dónde abrir la ventana: donde ya vive ese proyecto, si es que vive.

    El mismo criterio que usan los agentes (`agentes.sesion_para`); vive aquí
    también porque `agentes` no puede importar `slots` sin cerrar un ciclo.
    """
    for panel in api.paneles_abiertos(con):
        if panel["proyecto_id"] == proyecto_id:
            return panel["session"]
    return _NO_VALIDO.sub("-", proyecto_id) or "hub-slots"


def comando_manual(con: sqlite3.Connection, slot_id: int) -> str | None:
    slot = api.obtener_slot(con, slot_id)
    if not slot or not slot["ruta"]:
        return None
    # modelo: hereda — el mismo comando que `abrir()`, para copiar y pegar.
    comando = slot["comando"] or ("claude" if slot["autostart_claude"] else None)
    return tmux.comando_de_apertura(slot["ruta"], slot["nombre"], comando)


# ── Restaurar tras un apagón ─────────────────────────────────────────────────

# Lo que se deja escrito en la ventana: `restauracion.COMANDO_SUGERIDO`, que es
# `claude` salvo que `HUB_COMANDO_CLAUDE` diga otra cosa (decisiones 165 y 266).
#
# modelo: hereda — y aquí con más motivo que en `abrir()`. Esto no arranca nada:
# deja el texto en el prompt para que lo lance una persona, que puede editarlo
# antes de pulsar Enter. Fijar un modelo sería decidir por él en su propia
# ventana de trabajo; la política de `modelos.py` cubre lo que el hub lanza por
# su cuenta, que es lo que nadie mira.
# modelo: hereda
# Se reexportan para no romper a quien ya los importaba de aquí.
COMANDO_SUGERIDO = restauracion.COMANDO_SUGERIDO
marcados_para_restaurar = restauracion.marcados_para_restaurar
plan_de_restauracion = restauracion.plan_de_restauracion
candidatos_de_restauracion = restauracion.candidatos_de_restauracion
normalizar_ruta = restauracion.normalizar_ruta

def restaurar(con: sqlite3.Connection, muestra_id: int | None = None) -> dict:
    """Deja el escritorio como estaba: una ventana por cada una que había abierta.

    Es la vuelta después de un apagón. Sigue siendo deliberadamente poca cosa:
    no relanza sesiones de Claude, no toca docker, no arranca nada. Lo que hace
    es devolver **las ventanas**, cada una en su ruta, con el comando escrito y
    sin lanzar.

    🔴 **Lo que cambió el 2026-09-16, y por qué** (decisión 206). Antes abría UNA
    ventana por slot marcado, que era lo pedido en la decisión 165 —*«con que me
    deje la terminal en la ruta que corresponde es suficiente»*—. Al usarlo tras
    un corte real resultó ser menos de lo que hacía falta: *«debería restaurar
    todo lo que ya estaba abierto, toda terminal que ya estaba dentro de un
    slot»*. Medido en la muestra de aquel corte: **19 paneles en 10 sesiones**, y
    los ocho slots habrían devuelto ocho ventanas. `Trabajo` tenía cuatro.

    El dato ya estaba guardado; lo que faltaba era usarlo. Y usarlo obligó a dos
    cosas que no se veían desde fuera: normalizar las rutas de montajes rancios
    —**10 de las 19 ya no existían**— y contar por ventana y no por panel.

    🔴 **Sin Enter, jamás.** Es el tercer caso de la regla dura 15 y su condición
    se cumple igual que antes: crear la ventana y escribir en ella son la MISMA
    operación, así que la shell acaba de nacer y no hay hueco que verificar.
    Escribir sin despachar es lo que lo vuelve inofensivo — deja el comando a la
    vista para que lo lance una persona, el gate humano del principio 6. Y si la
    escritura falla, **no se reintenta**: una ventana con el comando a medias es
    peor que una vacía, y se dice cuál (regla 21).

    Que sea barato no lo hace automático: sigue siendo un botón (regla dura 3).
    """
    abiertos, fallos = [], []
    for paso in plan_de_restauracion(con, muestra_id=muestra_id):
        if not paso["ruta"]:
            fallos.append(f"«{paso['nombre']}»: {paso['aviso']}")
            continue

        session = sesion_para(con, paso["proyecto_id"])
        try:
            if tmux.existe_sesion(session):
                pane_id = tmux.abrir_ventana(paso["ruta"], paso["nombre"], None, session)
            else:
                tmux.nueva_sesion(session, paso["ruta"], paso["nombre"], None,
                                  entorno={"PATH": tmux.path_de_usuario()})
                pane_id = tmux.panel_de_sesion(session)
        except Exception as exc:  # noqa: BLE001 — una ventana rota no cancela las demás
            fallos.append(f"«{paso['nombre']}»: {exc}")
            continue

        if not pane_id:
            fallos.append(f"«{paso['nombre']}»: tmux no devolvió el panel")
            continue

        vincular(con, pane_id, paso["slot_id"])
        try:
            tmux.escribir_titulo(pane_id, paso["nombre"])
        except Exception:
            pass  # el título es cosmético; no debe tumbar la restauración

        abierto = {"slot_id": paso["slot_id"], "nombre": paso["nombre"],
                   "pane_id": pane_id, "ruta": paso["ruta"],
                   "comando": paso["comando"], "aviso": paso["aviso"]}
        if paso["aviso"]:
            # La ventana se abrió, pero no donde se pedía. Sale como abierta y
            # con su porqué: callarlo dejaría a alguien en una ruta que no es la
            # suya creyendo que sí (regla 13).
            fallos.append(f"«{paso['nombre']}»: {paso['aviso']}")

        if not paso["comando"]:
            # Nada que escribir —el proceso de antes no está en la lista blanca—
            # y eso no es un fallo: la ventana en su ruta ya es la mitad buena.
            abiertos.append(abierto)
            continue

        try:
            tmux.pegar_en_panel(pane_id, paso["comando"], enter=False)
            _esperar_a_verlo(pane_id, paso["comando"])
        except Exception as exc:  # noqa: BLE001
            fallos.append(f"«{paso['nombre']}»: la ventana se abrió pero no se "
                          f"pudo dejar el comando escrito ({exc})")
            continue
        abiertos.append(abierto)

    return {"abiertos": abiertos, "fallos": fallos}


# Cuánto se espera a ver el comando en la pantalla. La shell acaba de nacer y
# puede no haber pintado el prompt todavía; medido, aparece de inmediato, pero
# «de inmediato» en una máquina que acaba de arrancar tras un apagón —que es el
# único momento en que esto se usa— no significa lo mismo.
SEGUNDOS_PARA_VERLO = 3.0


def _esperar_a_verlo(pane_id: str, texto: str) -> None:
    """🔴 Regla dura 17, aplicada a una escritura que NO se despacha.

    La regla nació de un `enviado: true` sobre un mensaje que seguía en
    pantalla. Aquí el fallo simétrico es peor y más callado: dar por escrito un
    comando que nunca llegó al panel, y decirlo en la pantalla del panorama
    justo cuando se vuelve de un apagón. Comprobar es una captura, así que no
    hay motivo para suponerlo.

    Se mira con `-J` porque el terminal parte por ancho: un comando de 37
    caracteres en un panel estrecho sale en dos líneas y no casaría.
    """
    limite = time.monotonic() + SEGUNDOS_PARA_VERLO
    while time.monotonic() < limite:
        if texto in tmux.capturar_panel(pane_id, unir_lineas=True):
            return
        time.sleep(0.1)
    raise RuntimeError(
        f"se pegó pero no llegó a verse en el panel tras {SEGUNDOS_PARA_VERLO:g}s"
    )


# ── Ocultar de la bandeja ────────────────────────────────────────────────────
#
# Lo que pidió: *«hay cosas que son servers de node o cosas así que no las
# necesito tener tan a la vista»*. No es descartar ni cerrar: la ventana sigue
# corriendo y sigue siendo suya. Deja de estorbar en la lista, y nada más.
#
# 🔴 Por nombre y no por `pane_id`. Ver el comentario de la tabla en `db.py`: un
# `pane_id` muere con el servidor de tmux y se recicla, así que ocultar por panel
# se deshace solo al reiniciar y puede acabar escondiendo otra ventana.


def ocultar(con: sqlite3.Connection, session: str, window_idx: int | None = None) -> None:
    """Saca de la bandeja una ventana, o la sesión entera con `window_idx=None`."""
    con.execute(
        "INSERT OR IGNORE INTO oculto (session, window_idx, creado_en) VALUES (?,?,?)",
        (session, window_idx, ahora()),
    )


def mostrar(con: sqlite3.Connection, session: str, window_idx: int | None = None) -> None:
    """Deshace un `ocultar`.

    Ocultar la sesión entera y ocultar una de sus ventanas son dos filas
    distintas: mostrar la ventana no destapa la sesión, ni al revés. Es lo que
    permite decir «esta sesión no, salvo esta ventana» sin que una acción borre
    en silencio la otra.
    """
    con.execute(
        "DELETE FROM oculto WHERE session=? AND IFNULL(window_idx,-1)=IFNULL(?,-1)",
        (session, window_idx),
    )
