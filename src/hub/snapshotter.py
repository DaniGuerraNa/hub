"""Muestreo continuo del estado de tmux.

Resuelve el dolor 1 sin LLM, sin tokens y sin inferencia cara.

Por qué muestreo y no captura "al cerrar": si WSL muere de golpe o se apaga la PC,
ningún hook alcanza a dispararse. Es la única parte del sistema donde un demonio
se justifica.
"""

from __future__ import annotations

import sqlite3
import time
from datetime import datetime, timezone

from . import (busqueda, conexiones, config, db, registry, repos, servicios,
               terminal, tmux)
from .registry import Atribuidor

# Cada cuántos ciclos de 20 s se mide lo caro (git y docker). ~10 minutos: los
# repos de /mnt/c van por 9p y no hay ninguna urgencia — un commit sin push no
# se vuelve más grave en cinco minutos, y meterlo en el latido rápido
# convertiría el componente que existe para no fallar en el que va lento.
CADA_CUANTOS_CICLOS_LO_CARO = 30


def ahora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _ultimo_snapshot(con: sqlite3.Connection) -> sqlite3.Row | None:
    return con.execute(
        "SELECT * FROM snapshot ORDER BY id DESC LIMIT 1"
    ).fetchone()


def detectar_corte(con: sqlite3.Connection, pid_actual: int | None) -> bool:
    """¿Murió el servidor de tmux desde el último snapshot?

    Se compara el PID del servidor: si cambió (o desapareció), lo que había antes
    se perdió. El último snapshot de ese epoch se marca `preservado` y ya nunca se
    poda — es justo el que hay que enseñar en la pantalla de recuperación.
    """
    ultimo = _ultimo_snapshot(con)
    if ultimo is None or ultimo["server_pid"] is None:
        return False
    if pid_actual == ultimo["server_pid"]:
        return False

    con.execute(
        """UPDATE snapshot SET preservado=1
           WHERE id = (SELECT MAX(id) FROM snapshot WHERE server_pid = ?)""",
        (ultimo["server_pid"],),
    )
    return True


def capturar(con: sqlite3.Connection, atribuidor: Atribuidor) -> int | None:
    """Toma una muestra. Devuelve el id del snapshot, o None si tmux no responde."""
    pid = tmux.servidor_pid()
    paneles = tmux.listar_paneles()
    if pid is None and not paneles:
        # Sin servidor: no se escribe un snapshot vacío que pise al bueno.
        detectar_corte(con, None)
        return None

    detectar_corte(con, pid)

    cur = con.execute(
        "INSERT INTO snapshot (tomado_en, server_pid) VALUES (?,?)", (ahora(), pid)
    )
    snapshot_id = cur.lastrowid

    bindings = {
        fila["pane_id"]: fila["slot_id"]
        for fila in con.execute(
            "SELECT pane_id, slot_id FROM binding WHERE server_pid=?", (pid,)
        )
    }

    for p in paneles:
        etiqueta = tmux.inferir_etiqueta(p["titulo"], p["cwd"], p["comando"])
        proyecto_id = atribuidor.atribuir(p["cwd"])
        slot_id = bindings.get(p["pane_id"])
        con.execute(
            """INSERT INTO panel (snapshot_id, pane_id, session, window_idx, pane_idx,
                                  cwd, titulo, comando, etiqueta, proyecto_id, slot_id)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (snapshot_id, p["pane_id"], p["session"], p["window_idx"], p["pane_idx"],
             p["cwd"], p["titulo"], p["comando"], etiqueta, proyecto_id, slot_id),
        )
        if slot_id:
            con.execute(
                "UPDATE slot SET ultima_actividad=? WHERE id=?", (ahora(), slot_id)
            )

    podar(con)
    return snapshot_id


def podar(con: sqlite3.Connection, retencion: int | None = None) -> int:
    """Ventana rodante. Los preservados no se podan nunca.

    Se guarda historial y no sólo el último porque si el corte llega mientras se
    reorganizaban paneles, la última muestra puede estar a medias.
    """
    retencion = retencion or config.RETENCION_SNAPSHOTS
    cur = con.execute(
        """DELETE FROM snapshot
           WHERE preservado = 0
             AND id NOT IN (
               SELECT id FROM snapshot WHERE preservado = 0
               ORDER BY id DESC LIMIT ?
             )""",
        (retencion,),
    )
    return cur.rowcount


def un_ciclo(con: sqlite3.Connection) -> int | None:
    # Los espejos de la terminal se limpian al cerrar la pestaña, pero si el
    # navegador muere sin avisar quedarían hasta la siguiente conexión. Aquí hay
    # un latido cada 20 s: es el sitio natural para barrerlos.
    try:
        terminal.limpiar_espejos_huerfanos()
    except Exception:
        pass

    proyectos = registry.cargar()
    registry.sincronizar(con, proyectos)
    conexiones.sincronizar(con, registry.cargar_conexiones())
    return capturar(con, Atribuidor(proyectos))


def ciclo_lento(con: sqlite3.Connection) -> dict:
    """Lo que consulta procesos externos: git y docker.

    Cada medición va en su propio `try`: que docker no esté levantado no puede
    dejar sin medir el respaldo de los repos, que es lo que de verdad importa.
    """
    proyectos = registry.cargar()
    resultado = {"repos": 0, "servicios": 0, "indice": 0}
    for clave, funcion in (
        ("repos", lambda: repos.escanear(con, proyectos)),
        ("servicios", lambda: servicios.escanear(con, proyectos)),
        ("indice", lambda: busqueda.reindexar(con)),
    ):
        try:
            resultado[clave] = funcion()
        except (servicios.NoRespondio, repos.RespaldoNoMedido) as exc:
            # Docker apagado es lo normal, no una avería: se conserva la última
            # lectura buena y no se ensucia el log con un error cada 10 minutos.
            # Con git ausente vale lo mismo, y aún más: un cero de respaldo que
            # en realidad significa «no he mirado» es la peor cifra del hub.
            resultado[clave] = None
            print(f"[snapshotter] {clave}: {exc}; se conserva lo anterior", flush=True)
        except Exception as exc:
            print(f"[snapshotter] {clave} falló: {exc}", flush=True)
    return resultado


def main() -> None:  # pragma: no cover - bucle del demonio
    config.asegurar_home()
    con = db.abrir()
    ciclos = 0
    while True:
        try:
            un_ciclo(con)
            # Al arrancar se mide una vez: tras un reinicio de WSL, el panorama
            # no puede estar en blanco esperando diez minutos.
            if ciclos % CADA_CUANTOS_CICLOS_LO_CARO == 0:
                ciclo_lento(con)
            ciclos += 1
        except Exception as exc:  # el demonio nunca muere por un ciclo malo
            print(f"[snapshotter] ciclo fallido: {exc}", flush=True)
        time.sleep(config.INTERVALO_SEGUNDOS)


if __name__ == "__main__":  # pragma: no cover
    main()
