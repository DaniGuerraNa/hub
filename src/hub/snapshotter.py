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

from . import version as _version
from . import (busqueda, conexiones, config, consumo, copia_base, db, maquina, orquestador, programados,
               registry, repos, servicios, terminal, tmux)
from .registry import Atribuidor

# Cada cuántos ciclos de 20 s se mide lo caro (git y docker). ~10 minutos: los
# repos de /mnt/c van por 9p y no hay ninguna urgencia — un commit sin push no
# se vuelve más grave en cinco minutos, y meterlo en el latido rápido
# convertiría el componente que existe para no fallar en el que va lento.
CADA_CUANTOS_CICLOS_LO_CARO = 30

# El SAI va aparte y más rápido —un ciclo por minuto— porque su aviso sólo sirve
# si llega mientras queda batería. Ver la decisión 249.
CADA_CUANTOS_CICLOS_EL_SAI = 3


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


def reconciliar_bindings(
    con: sqlite3.Connection, pid: int, paneles: list[dict]
) -> int:
    """Devuelve los slots a sus ventanas después de un corte (decisión 154).

    `binding` está atado al PID del servidor de tmux, porque un `pane_id` se
    reutiliza entre servidores y heredarlo a ciegas ataría un slot a una ventana
    ajena. Pero eso, tal cual, hacía que **cada** reinicio de tmux dejara todos
    los slots vacíos y todas las terminales en la bandeja — que es exactamente
    lo que pasó el 2026-09-04, y lo que se ve desde fuera es «está todo hecho
    un caos», no «se reinició tmux».

    Emparejar por (sesión, ventana, panel) es lo correcto porque es justo lo que
    `tmux-resurrect` reconstruye igual: mismo nombre de sesión, mismo índice de
    ventana, mismo layout. El `pane_id` es lo único que cambia.

    Esto **sólo restaura** vínculos que puso una persona: nunca borra uno, nunca
    crea un slot y nunca archiva nada (principio 9). Y hace falta precisamente
    porque el vínculo «esta ventana es aquel trabajo» es la única cosa del hub
    que NO se puede reconstruir escaneando: no está en `projects.yml` ni en
    tmux, sólo en la cabeza de quien lo ató.
    """
    anterior = con.execute(
        """SELECT id FROM snapshot
           WHERE server_pid IS NOT NULL AND server_pid <> ?
           ORDER BY id DESC LIMIT 1""",
        (pid,),
    ).fetchone()
    if anterior is None:
        return 0

    # Sólo slots vivos: revivir uno archivado sería gestión automática, y eso
    # aquí no se hace.
    previos = {
        (f["session"], f["window_idx"], f["pane_idx"]): f["slot_id"]
        for f in con.execute(
            """SELECT p.session, p.window_idx, p.pane_idx, p.slot_id
               FROM panel p JOIN slot s ON s.id = p.slot_id
               WHERE p.snapshot_id = ? AND s.status = 'activo'""",
            (anterior["id"],),
        )
    }
    if not previos:
        return 0

    devueltos = 0
    for p in paneles:
        slot_id = previos.get((p["session"], p["window_idx"], p["pane_idx"]))
        if slot_id is None:
            continue
        # DO NOTHING y no UPDATE: si ya hay un binding para este epoch, lo puso
        # alguien a mano y manda sobre lo que había antes del corte.
        cur = con.execute(
            """INSERT INTO binding (pane_id, server_pid, slot_id, visto_en)
               VALUES (?,?,?,?)
               ON CONFLICT(pane_id, server_pid) DO NOTHING""",
            (p["pane_id"], pid, slot_id, ahora()),
        )
        devueltos += cur.rowcount
    return devueltos


def capturar(con: sqlite3.Connection, atribuidor: Atribuidor) -> int | None:
    """Toma una muestra. Devuelve el id del snapshot, o None si tmux no responde."""
    pid = tmux.servidor_pid()
    paneles = tmux.listar_paneles()
    if pid is None and not paneles:
        # Sin servidor: no se escribe un snapshot vacío que pise al bueno.
        detectar_corte(con, None)
        return None

    if detectar_corte(con, pid) and pid is not None:
        # En voz alta: que un corte devuelva 0 ventanas a su sitio es un dato,
        # y callarlo dejaría el mismo síntoma mudo de la vez que costó encontrar.
        devueltos = reconciliar_bindings(con, pid, paneles)
        print(
            f"[snapshotter] corte de tmux: {devueltos} ventana(s) devueltas a su slot",
            flush=True,
        )

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
        # Leer 1,5 GB de transcripts son ~5 s: caro para el latido de 20 s y
        # barato para el ciclo lento (regla dura 14). Y en su propio `try`, como
        # los demás: que no haya registro de Claude Code no puede dejar sin medir
        # el respaldo, que es lo que de verdad importa.
        ("consumo", lambda: consumo.escanear(con, proyectos)),
        # La salud del equipo: `nvidia-smi` y un `powershell`, ~1 s. Caro para
        # el latido de 20 s y barato aquí. Importa sobre todo cuando no hay
        # nadie delante, que es cuando nadie oye el ventilador.
        ("maquina", lambda: maquina.escanear(con)),
        # La copia diaria de la base (decisión 277): una por día, así que
        # aquí casi siempre es mirar que la de hoy existe y seguir.
        ("copia_base", lambda: copia_base.hacer(con)),
        # ¿Hay versión publicada más nueva? Un `git ls-remote` al día como
        # mucho (decisión 286); el resto de ciclos es leer un archivo.
        ("version", lambda: (_version.buscar_remota() or {}).get("ultima")),
    ):
        try:
            resultado[clave] = funcion()
        except (servicios.NoRespondio, repos.RespaldoNoMedido,
                consumo.ConsumoNoMedido, maquina.MaquinaNoMedida) as exc:
            # Docker apagado es lo normal, no una avería: se conserva la última
            # lectura buena y no se ensucia el log con un error cada 10 minutos.
            # Con git ausente vale lo mismo, y aún más: un cero de respaldo que
            # en realidad significa «no he mirado» es la peor cifra del hub.
            resultado[clave] = None
            print(f"[snapshotter] {clave}: {exc}; se conserva lo anterior", flush=True)
        except Exception as exc:
            print(f"[snapshotter] {clave} falló: {exc}", flush=True)
    return resultado


def ciclo_mensajes(con: sqlite3.Connection) -> dict:
    """Los mensajes programados que ya tocan.

    🔴 Vive aquí, y no en el relé, porque **el relé no late si no hay Telegram**:
    sin token, `correr()` ni siquiera llega a `una_vuelta` —duerme 30 s y
    reintenta—, así que un mensaje programado no saldría nunca en una máquina con
    el canal sin configurar, que es lo normal. El snapshotter es lo único que
    late pase lo que pase (regla dura 2), y por eso es lo único sobre lo que se
    puede prometer una hora.

    Va DESPUÉS de `un_ciclo` y no antes: el panel de un slot se resuelve contra
    el último snapshot, y entregar antes de muestrear resolvería la ventana con
    la foto anterior — la de hace 20 s, que es justo cuando el slot puede acabar
    de abrirse.

    Y en su propio `try` arriba: una entrega que falle no puede dejar sin
    muestrear. El muestreo es lo que existe para funcionar el día que todo lo
    demás falla; esto es una comodidad encima.
    """
    return programados.entregar_pendientes(con)


def main() -> None:  # pragma: no cover - bucle del demonio
    config.asegurar_home()
    con = db.abrir()
    ciclos = 0
    while True:
        try:
            un_ciclo(con)
            try:
                recuento = ciclo_mensajes(con)
                if recuento:
                    print(f"[snapshotter] programados: {recuento}", flush=True)
            except Exception as exc:
                # En voz alta y sin tumbar el muestreo (reglas duras 2 y 21).
                print(f"[snapshotter] programados falló: {exc}", flush=True)
            try:
                # Aquí y no en hub-web por lo mismo que los programados: esto es
                # lo único que late pase lo que pase. Despierta al orquestador
                # cuando una sesión termina lo que le mandó (decisión 255).
                hecho = orquestador.bombear(con)
                if hecho:
                    print(f"[snapshotter] orquestador: {hecho}", flush=True)
            except Exception as exc:
                print(f"[snapshotter] orquestador falló: {exc}", flush=True)
            # Al arrancar se mide una vez: tras un reinicio de WSL, el panorama
            # no puede estar en blanco esperando diez minutos.
            if ciclos % CADA_CUANTOS_CICLOS_LO_CARO == 0:
                ciclo_lento(con)
            elif ciclos % CADA_CUANTOS_CICLOS_EL_SAI == 0:
                # Aparte del ciclo lento y más a menudo: el SAI aguanta ~22 min
                # y enterarse del corte a los diez gastaría media reserva
                # esperando. Cuesta un `powershell`, así que cabe (regla 14).
                # `elif` para no medirlo dos veces en el mismo ciclo.
                try:
                    maquina.escanear_ups(con)
                except Exception as exc:
                    print(f"[snapshotter] sai: {exc}", flush=True)
            ciclos += 1
        except Exception as exc:  # el demonio nunca muere por un ciclo malo
            print(f"[snapshotter] ciclo fallido: {exc}", flush=True)
        time.sleep(config.INTERVALO_SEGUNDOS)


if __name__ == "__main__":  # pragma: no cover
    main()
