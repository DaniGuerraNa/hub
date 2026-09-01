"""Mutaciones sobre slots y bandeja de entrada.

El hub informa, no gestiona (principio 9): archivar y borrar son siempre acciones
manuales. No hay expiración, ni avisos, ni nada automático.
"""

from __future__ import annotations

import sqlite3

from . import api, tmux
from .snapshotter import ahora


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
    permitidos = {"nombre", "ruta", "nota", "comando", "autostart_claude", "proyecto_id"}
    cambios = {k: v for k, v in campos.items() if k in permitidos and v is not None}
    if not cambios:
        return
    if "autostart_claude" in cambios:
        cambios["autostart_claude"] = int(bool(cambios["autostart_claude"]))
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
    """Ata un panel de la bandeja a un slot, dentro del epoch actual del servidor."""
    actual = api.snapshot_actual(con)
    if not actual:
        return
    con.execute(
        """INSERT INTO binding (pane_id, server_pid, slot_id, visto_en)
           VALUES (?,?,?,?)
           ON CONFLICT(pane_id, server_pid) DO UPDATE SET
             slot_id=excluded.slot_id, visto_en=excluded.visto_en""",
        (pane_id, actual["server_pid"], slot_id, ahora()),
    )
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


def abrir(con: sqlite3.Connection, slot_id: int, session: str | None = None) -> str | None:
    """Lanza el slot en tmux. La UI lanza terminales, no las hospeda (decisión 16)."""
    slot = api.obtener_slot(con, slot_id)
    if not slot or not slot["ruta"]:
        return None
    comando = slot["comando"]
    if not comando and slot["autostart_claude"]:
        comando = "claude"
    pane_id = tmux.abrir_ventana(slot["ruta"], slot["nombre"], comando, session)
    if pane_id:
        vincular(con, pane_id, slot_id)
        try:
            tmux.escribir_titulo(pane_id, slot["nombre"])
        except Exception:
            pass  # el título es cosmético; no debe tumbar la apertura
    return pane_id


def comando_manual(con: sqlite3.Connection, slot_id: int) -> str | None:
    slot = api.obtener_slot(con, slot_id)
    if not slot or not slot["ruta"]:
        return None
    comando = slot["comando"] or ("claude" if slot["autostart_claude"] else None)
    return tmux.comando_de_apertura(slot["ruta"], slot["nombre"], comando)
