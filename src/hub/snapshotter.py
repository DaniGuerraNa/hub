"""Muestreo continuo del estado de tmux.

Resuelve el dolor 1 sin LLM, sin tokens y sin inferencia cara.

Por qué muestreo y no captura "al cerrar": si WSL muere de golpe o se apaga la PC,
ningún hook alcanza a dispararse. Es la única parte del sistema donde un demonio
se justifica.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time

from . import version as _version
from . import (busqueda, conexiones, config, consumo, copia_base, db, intercambio, maquina, modelos, orquestador,
               programados, registry, repos, salud, servicios, terminal, tmux, transcribir, tui)
from .registry import Atribuidor
from .reloj import ahora

# Cada cuántos ciclos de 20 s se mide lo caro (git y docker). ~10 minutos: los
# repos de /mnt/c van por 9p y no hay ninguna urgencia — un commit sin push no
# se vuelve más grave en cinco minutos, y meterlo en el latido rápido
# convertiría el componente que existe para no fallar en el que va lento.
CADA_CUANTOS_CICLOS_LO_CARO = 30

# El SAI va aparte y más rápido —un ciclo por minuto— porque su aviso sólo sirve
# si llega mientras queda batería. Ver la decisión 249.
CADA_CUANTOS_CICLOS_EL_SAI = 3


def _ultimo_snapshot(con: sqlite3.Connection) -> sqlite3.Row | None:
    return con.execute(
        "SELECT * FROM snapshot ORDER BY id DESC LIMIT 1"
    ).fetchone()


def detectar_corte(con: sqlite3.Connection, pid_actual: int | None) -> bool:
    """¿Murió el servidor de tmux desde el último snapshot?

    Se compara el PID del servidor: si cambió (o desapareció), lo que había antes
    se perdió. El último snapshot de ese epoch se marca `preservado` y ya nunca se
    poda — es justo el que hay que enseñar en la pantalla de recuperación.

    Sólo se marca una vez: con tmux apagado esto corre en cada ciclo, y volver
    a ponerle `1` deshacía el «revisada» (`2`) — el «Ya lo revisé» y el cerrar
    la última ventana a propósito volvían a avisar a los 20 s (C-0227).
    """
    ultimo = _ultimo_snapshot(con)
    if ultimo is None or ultimo["server_pid"] is None:
        return False
    if pid_actual == ultimo["server_pid"]:
        return False

    con.execute(
        """UPDATE snapshot SET preservado=1
           WHERE id = (SELECT MAX(id) FROM snapshot WHERE server_pid = ?) AND preservado = 0""",
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




def claude_por_panel() -> dict[str, str]:
    """`{pane_id: id de la conversación}` de los Claude Code vivos en tmux.

    Claude Code escribe `~/.claude/sessions/<pid>.json` con su `sessionId` y
    el panel de tmux donde corre (`"tmux": "sesion:@2.%7"`), y lo borra al
    salir. Es lo que deja que «Restaurar» reanude la conversación exacta
    (decisión 289) en vez de abrir una nueva.

    🔴 Sólo de procesos vivos: un archivo que sobrevivió a un corte apunta a
    un `%7` del servidor de tmux ANTERIOR, y el `%7` de hoy es otra ventana.

    Un Claude que enseña un trabajo en segundo plano (`parkedJobId`) no es
    quien trabaja: es el del trabajo (`kind: bg`, su `jobId`), que no tiene
    panel. El panel se apunta a ése, que es lo que se ve dentro y donde viven
    sus subagentes; sin él, Talleres no los veía (C-0228).
    """
    salida: dict[str, str] = {}
    try:
        archivos = list(orquestador._sesiones_de_claude().glob("*.json"))
    except OSError:
        return salida
    aparcados: dict[str, str] = {}
    trabajos: dict[str, str] = {}
    for ruta in archivos:
        try:
            info = json.loads(ruta.read_text(encoding="utf-8"))
            pid = int(info.get("pid") or 0)
            os.kill(pid, 0)
        except (OSError, ValueError, TypeError, ProcessLookupError, PermissionError):
            continue
        sesion = str(info.get("sessionId") or "")
        if pid <= 0 or not modelos.es_sesion(sesion):
            continue
        if info.get("jobId"):
            trabajos[str(info["jobId"])] = sesion
        panel = str(info.get("tmux") or "").rsplit(".", 1)[-1]
        if panel.startswith("%"):
            salida[panel] = sesion
            if info.get("parkedJobId"):
                aparcados[panel] = str(info["parkedJobId"])
    for panel, trabajo in aparcados.items():
        salida[panel] = trabajos.get(trabajo, salida[panel])
    return salida


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

    # 🔴 Todo lo que mira tmux o el disco, antes de escribir; y la muestra
    # entera en una sola transacción. En cuanto la fila `snapshot` existe es
    # la «actual», y con las filas `panel` escritas una a una quien leyera en
    # ese hueco veía 0, 1, 2… paneles: el relé olvidaba los episodios de todos
    # (revisor), y el raíl de Trabajo soltaba ventanas vivas (C-0234, revisor:
    # reproducido con dos conexiones, el latido llegó a leer `[]`).
    ocupados = {p["pane_id"]: _ocupado(p) for p in paneles}
    try:
        conversaciones = claude_por_panel()
    except Exception as exc:  # el muestreo no muere por esto (regla dura 2)
        print(f"[snapshotter] sesiones de Claude: {exc}", flush=True)
        conversaciones = {}
    bindings = {
        fila["pane_id"]: fila["slot_id"]
        for fila in con.execute(
            "SELECT pane_id, slot_id FROM binding WHERE server_pid=?", (pid,)
        )
    }
    filas = [
        (p, tmux.inferir_etiqueta(p["titulo"], p["cwd"], p["comando"]),
         atribuidor.atribuir(p["cwd"]), bindings.get(p["pane_id"]))
        for p in paneles
    ]

    with db.transaccion(con):
        cur = con.execute(
            "INSERT INTO snapshot (tomado_en, server_pid) VALUES (?,?)", (ahora(), pid)
        )
        snapshot_id = cur.lastrowid
        for p, etiqueta, proyecto_id, slot_id in filas:
            con.execute(
                """INSERT INTO panel (snapshot_id, pane_id, session, window_idx, pane_idx,
                                      cwd, titulo, comando, etiqueta, proyecto_id, slot_id,
                                      claude_sesion, ocupado)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (snapshot_id, p["pane_id"], p["session"], p["window_idx"], p["pane_idx"],
                 p["cwd"], p["titulo"], p["comando"], etiqueta, proyecto_id, slot_id,
                 conversaciones.get(p["pane_id"]), ocupados[p["pane_id"]]),
            )
            if slot_id:
                con.execute(
                    "UPDATE slot SET ultima_actividad=? WHERE id=?", (ahora(), slot_id)
                )

    podar(con)
    return snapshot_id


def _ocupado(panel: dict) -> int:
    """Si el agente del panel está trabajando ahora (decisión 393).

    🔴 El título solo no basta: con una herramienta larga Claude Code lo deja
    en ✳ —reposo— mientras la pantalla dice «✢ Embellishing… (7m 6s …)»
    (medido el 22-sep y otra vez el 9-nov), y talleres, la barra de Trabajo y
    los avisos daban por quieta una sesión que trabajaba. `tui.ocupado` mira
    las dos cosas, y también la línea de Codex. Sólo donde `reconocer` afirma
    un agente: un `bash` restaurado con la pantalla de Claude casaría (261).
    Leer cuesta una o dos llamadas a tmux por panel con agente (~7 ms cada
    uno, medido): cabe en el latido. Un panel que no se deja leer queda en 0,
    dicho en voz alta (reglas 2 y 21)."""
    agente = tui.reconocer(panel["comando"], panel["titulo"])
    if agente is None:
        return 0
    if tmux.es_spinner(panel["titulo"]):
        return 1   # el título de la lista ya lo dice: ni se vuelve a pedir
    try:
        return int(bool(tui.ocupado(agente, panel["pane_id"])))
    except Exception as exc:
        print(f"[snapshotter] no se pudo leer si {panel['pane_id']} trabaja: {exc}", flush=True)
        return 0


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
    except Exception as exc:  # noqa: BLE001 — el ciclo no muere, pero lo dice (regla 21)
        print(f"[snapshotter] el barrido de espejos falló: {exc}", flush=True)

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
        # ¿Hay versión publicada más nueva? Un `git ls-remote` a la hora como
        # mucho (decisiones 286 y 296); el resto de ciclos es leer un archivo.
        ("version", lambda: (_version.buscar_remota() or {}).get("ultima")),
        # Lo soltado o pegado en la terminal caduca a los diez días (decisión
        # 288). Cuántos se fueron, no cuáles: el nombre es de un proyecto.
        ("intercambio", lambda: len(intercambio.podar_de_paso())),
        # El audio de un dictado que falló, a los diez días (decisión 362).
        ("dictados", lambda: transcribir.podar_dictados()),
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


def vuelta(con: sqlite3.Connection, ciclos: int) -> None:
    """Una vuelta del demonio, cada paso en su `try` (reglas duras 2 y 21,
    decisión 376): uno que falla siempre no puede dejar sin hacer los demás.

    El 7-nov una carpeta de OneDrive ilegible tumbó el muestreo durante
    minutos, y con él los programados y el despertar del orquestador, que
    venían detrás en el mismo `try`.
    """
    # El latido va primero y aparte: es lo que dice «estoy vivo» aunque no
    # haya tmux que muestrear o el ciclo falle (decisión 289).
    try:
        salud.latir()
    except Exception as exc:
        print(f"[snapshotter] latido: {exc}", flush=True)
    try:
        un_ciclo(con)
    except Exception as exc:
        print(f"[snapshotter] muestreo fallido: {exc}", flush=True)
    try:
        recuento = ciclo_mensajes(con)
        if recuento:
            print(f"[snapshotter] programados: {recuento}", flush=True)
    except Exception as exc:
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
    try:
        # Al arrancar se mide una vez: tras un reinicio de WSL, el panorama
        # no puede estar en blanco esperando diez minutos.
        if ciclos % CADA_CUANTOS_CICLOS_LO_CARO == 0:
            ciclo_lento(con)
        elif ciclos % CADA_CUANTOS_CICLOS_EL_SAI == 0:
            # Aparte del ciclo lento y más a menudo: el SAI aguanta ~22 min
            # y enterarse del corte a los diez gastaría media reserva
            # esperando. Cuesta un `powershell`, así que cabe (regla 14).
            # `elif` para no medirlo dos veces en el mismo ciclo.
            maquina.escanear_ups(con)
    except Exception as exc:
        print(f"[snapshotter] ciclo lento o sai: {exc}", flush=True)


def main() -> None:  # pragma: no cover - bucle del demonio
    config.asegurar_home()
    con = db.abrir()
    ciclos = 0
    while True:
        try:
            vuelta(con, ciclos)
        except Exception as exc:  # el demonio nunca muere por un ciclo malo
            print(f"[snapshotter] ciclo fallido: {exc}", flush=True)
        ciclos += 1
        time.sleep(config.INTERVALO_SEGUNDOS)


if __name__ == "__main__":  # pragma: no cover
    main()
