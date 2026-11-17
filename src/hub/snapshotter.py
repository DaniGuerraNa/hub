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
import threading
import time
from collections.abc import Callable

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
    if not paneles:
        # Sin servidor: no se escribe un snapshot vacío que pise al bueno.
        # Y sin paneles aunque haya PID, igual (C-0283): un servidor vivo
        # tiene al menos uno, y el PID y la lista son dos llamadas. Si muere
        # entre ellas —el corte exacto para el que existe esto— llegaba un PID
        # vivo con la lista vacía, se escribía la muestra vacía con el PID
        # viejo y el ciclo siguiente preservaba ésa en vez de la buena.
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
            # 🔴 Sólo si su agente está trabajando (decisión 393), no por tener
            # una ventana: con eso, una `bash` olvidada o un slot de encargos
            # sin mensajes desde hacía meses salía como trabajo de hoy y
            # encabezaba la lista (C-0297, regla dura 13). Lo que se hace en
            # una shell a mano no se ve desde aquí, y se acepta: es mejor una
            # fecha que se queda corta que una que miente.
            if slot_id and ocupados[p["pane_id"]]:
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
    # 🔴 Cada sincronización en su `try`, antes de muestrear (regla dura 2,
    # decisión 376): un `alias` repetido en `conexiones:` daba un error de
    # integridad en cada ciclo y, al ir en el mismo paso, no se tomaba ni una
    # muestra más mientras el latido seguía vivo. Lo derivado se queda como
    # estaba hasta que se arregle el registro; la muestra no espera.
    for clave, sincronizar in (
        ("el registro de proyectos", lambda: registry.sincronizar(con, proyectos)),
        ("las conexiones", lambda: conexiones.sincronizar(con, registry.cargar_conexiones())),
    ):
        try:
            sincronizar()
            _racha_lenta(clave, None)
        except Exception as exc:  # noqa: BLE001 — se dice una vez por racha y se sigue (regla 21)
            _racha_lenta(clave, f"no se pudo sincronizar {clave}: {type(exc).__name__}: {exc}")
    return capturar(con, Atribuidor(proyectos))


# Qué medición del ciclo lento está fallando y con qué mensaje (EJE-27). Una
# racha se dice al empezar y al terminar, no cada diez minutos: «docker no está
# instalado» salió 787 veces en seis días y tapaba lo que sí había que leer.
# Mismo criterio que `rele_base.pasos`, aquí aparte para no tocar los relés.
_RACHAS_LENTO: dict[str, str] = {}


def _racha_lenta(clave: str, mensaje: str | None) -> None:
    """Apunta al empezar una racha (o si cambia el mensaje) y al terminarla.

    Nunca lanza: decirlo mal no puede tumbar el bucle (regla dura 2).
    """
    try:
        if mensaje is None:
            if _RACHAS_LENTO.pop(clave, None) is not None:
                print(f"[snapshotter] {clave}: vuelve a medirse", flush=True)
        elif _RACHAS_LENTO.get(clave) != mensaje:
            _RACHAS_LENTO[clave] = mensaje
            print(f"[snapshotter] {mensaje} (se apunta una vez por racha)", flush=True)
    except Exception:  # noqa: BLE001 - el aviso no puede romper el ciclo
        pass


def _decir_paso(al_paso: Callable | None, clave: str, duro: float | None = None,
                fallo: str | None = None) -> None:
    """Avisa a quien sigue el ciclo lento de que un paso empieza (`duro` None)
    o de cuánto duró y, si lanzó, con qué. Nunca lanza: apuntarlo mal no puede
    dejar sin medir (regla dura 2), pero se dice (regla 21)."""
    if al_paso is None:
        return
    try:
        al_paso(clave, duro, fallo)
    except Exception as exc:  # noqa: BLE001
        _racha_lenta("el paso", f"no se pudo apuntar el paso del ciclo lento: {exc}")


def ciclo_lento(con: sqlite3.Connection, al_paso: Callable | None = None,
                sai: bool = True) -> dict:
    """Lo que consulta procesos externos: git y docker.

    Cada medición va en su propio `try`: que docker no esté levantado no puede
    dejar sin medir el respaldo de los repos, que es lo que de verdad importa.

    `al_paso(clave, duro, fallo)` se llama al empezar cada paso (`duro` None)
    y al acabarlo, con los segundos que tardó y, si lanzó, con qué (C-0309):
    desde que esto corre en su hilo, un paso colgado ya no para el latido, así
    que hay que poder decir cuál es; y como cada paso va en su `try`, una
    vuelta puede acabar con todos fallando, y eso también hay que poder
    decirlo. Lo que «se conserva» porque no se pudo preguntar (docker
    apagado, sin git) no es un fallo. El registro cuenta como paso aunque no
    mida nada: es un `stat` por ruta sobre el disco de Windows, lo que se
    cuelga.

    `sai=False` cuando esto corre a la vez que el latido: el SAI lo mide
    sólo él (decisión 249; el porqué, en `maquina.medir`).
    """
    _decir_paso(al_paso, "registro")
    empieza = time.monotonic()
    try:
        proyectos = registry.cargar()
    finally:
        _decir_paso(al_paso, "registro", time.monotonic() - empieza)
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
        ("maquina", lambda: maquina.escanear(con, sai=sai)),
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
        _decir_paso(al_paso, clave)
        empieza = time.monotonic()
        fallo = None
        try:
            resultado[clave] = funcion()
        except (servicios.NoRespondio, repos.RespaldoNoMedido,
                consumo.ConsumoNoMedido, maquina.MaquinaNoMedida) as exc:
            # Docker apagado es lo normal, no una avería: se conserva la última
            # lectura buena y no se ensucia el log con un error cada 10 minutos.
            # Con git ausente vale lo mismo, y aún más: un cero de respaldo que
            # en realidad significa «no he mirado» es la peor cifra del hub.
            resultado[clave] = None
            _racha_lenta(clave, f"{clave}: {exc}; se conserva lo anterior")
        except Exception as exc:
            fallo = f"{type(exc).__name__}: {exc}"
            _racha_lenta(clave, f"{clave} falló: {exc}")
        else:
            _racha_lenta(clave, None)
        _decir_paso(al_paso, clave, time.monotonic() - empieza, fallo)
    return resultado


class CicloLento:
    """El ciclo lento en su propio hilo, con su conexión y de uno en uno (C-0309).

    Dentro de la vuelta, cada diez minutos la muestra tardaba 69–75 s en vez
    de 20 (medido), y con ella los programados y el despertar del orquestador:
    justo lo que la regla dura 14 dice que no puede pasar. Aquí el latido sólo
    **pide** la vuelta lenta y sigue.

    - **Su conexión**, abierta dentro del hilo: la del latido lleva la
      transacción de la muestra y SQLite no deja compartirla entre hilos. Dos
      conexiones escribiendo no es nuevo —la web y los relés ya escriben la
      misma base desde otros procesos—, y en WAL el que llega segundo espera.
    - **De uno en uno, sin cola**: si el anterior sigue, `pedir` dice que no y
      no guarda nada. Encolar haría que tras media hora de disco colgado
      salieran tres escaneos seguidos justo al volver.
    - **Regla dura 2**: cada vuelta en su `try`; si aun así el hilo muere, el
      siguiente `pedir` levanta otro; y si no se puede levantar, `pedir` lanza
      y quien llama mide `dentro`, como antes de esto.
    - **Lo que le pasa se ve desde fuera**: `estado()` viaja en el latido y lo
      juzga `salud`. Un hilo colgado en un `stat` no para nada, así que sin
      eso sería un silencio.
    """

    def __init__(self, trabajo: Callable | None = None, conectar: Callable | None = None) -> None:
        # Por nombre y en el momento de llamar, no la función de ahora: quien
        # sustituye `ciclo_lento` o `db.conectar` después de crear esto (los
        # tests) tiene que ver su sustituto.
        # Sin el SAI: con esto, lo mide sólo el latido, corra la vuelta en
        # el hilo o `dentro`.
        self._trabajo = trabajo or (lambda con, al_paso: ciclo_lento(con, al_paso, sai=False))
        self._conectar = conectar or (lambda: db.conectar())
        self._cerrojo = threading.Lock()
        self._pedido = threading.Event()
        self._hilo: threading.Thread | None = None
        self._estado: dict = {
            # Desde cuándo existe: si nunca acabó una vuelta, «lleva sin
            # acabar» se cuenta desde aquí.
            "desde": ahora(),
            "corriendo": False,
            # True si la última vuelta corrió en el hilo del latido porque el
            # suyo no arrancó.
            "dentro": False,
            "empezo": None,
            # Sólo la que acabó BIEN: una vuelta que lanza no cuenta, o un
            # ciclo lento que falla siempre parecería sano.
            "acabo": None,
            "duro": None,
            "paso": None,
            "paso_desde": None,
            "pasos": {},
            "fallo": None,
            # Los pasos que lanzaron en la última vuelta acabada, con qué. La
            # vuelta «acaba bien» aunque fallen todos (cada uno va en su
            # `try`): sin esto, un ciclo lento que no mide nada parecería sano.
            "fallaron": {},
        }
        self._fallan_en_esta: dict[str, str] = {}

    def estado(self) -> dict:
        """Una copia, lista para escribirse como JSON en el latido."""
        with self._cerrojo:
            return {**self._estado, "pasos": dict(self._estado["pasos"]),
                    "fallaron": dict(self._estado["fallaron"])}

    def pedir(self) -> bool:
        """Pide una vuelta. False si la anterior sigue: ni se solapa ni se encola.

        Si el hilo no existe o murió, levanta otro; si no se puede levantar,
        lanza lo que lance `Thread.start`, y quien llama decide (la vuelta del
        snapshotter mide `dentro`)."""
        with self._cerrojo:
            vivo = self._hilo is not None and self._hilo.is_alive()
            if vivo and self._estado["corriendo"]:
                return False
            if not vivo:
                hilo = threading.Thread(target=self._bucle, name="ciclo-lento", daemon=True)
                hilo.start()
                self._hilo = hilo
            self._empezar(dentro=False)
            self._pedido.set()
            return True

    def dentro(self, con: sqlite3.Connection) -> None:
        """La vuelta en el hilo y con la conexión de quien llama: la salida si
        el hilo no arranca. Lleva la misma cuenta, y deja dicho que fue dentro
        para que Salud lo enseñe: así la muestra vuelve a esperar al ciclo
        lento, que es lo que esto existe para evitar."""
        with self._cerrojo:
            self._empezar(dentro=True)
        empieza = time.monotonic()
        fallo = None
        try:
            self._trabajo(con, self._al_paso)
        except Exception as exc:
            fallo = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            self._acabar(empieza, fallo)

    def _empezar(self, *, dentro: bool) -> None:
        # `fallaron` no se limpia aquí: mientras corre la vuelta nueva sigue
        # valiendo lo de la última acabada.
        self._fallan_en_esta = {}
        self._estado.update(corriendo=True, dentro=dentro, empezo=ahora(),
                            paso=None, paso_desde=None, pasos={}, fallo=None)

    def _acabar(self, empieza: float, fallo: str | None) -> None:
        with self._cerrojo:
            self._estado.update(corriendo=False, paso=None, paso_desde=None, fallo=fallo,
                                fallaron=dict(self._fallan_en_esta))
            if fallo is None:
                self._estado.update(acabo=ahora(), duro=round(time.monotonic() - empieza, 1))

    def _al_paso(self, clave: str, duro: float | None = None, fallo: str | None = None) -> None:
        with self._cerrojo:
            if duro is None:
                self._estado.update(paso=clave, paso_desde=ahora())
            else:
                self._estado["pasos"][clave] = round(duro, 1)
                self._estado.update(paso=None, paso_desde=None)
                if fallo:
                    self._fallan_en_esta[clave] = fallo

    def _bucle(self) -> None:
        con: sqlite3.Connection | None = None
        while True:
            self._pedido.wait()
            self._pedido.clear()
            empieza = time.monotonic()
            # Si sale algo que no es `Exception` el hilo muere, pero no con
            # `corriendo` puesto: el `finally` lo deja dicho y `pedir` levanta otro.
            fallo: str | None = "el hilo del ciclo lento murió a media vuelta"
            try:
                if con is None:
                    con = self._conectar()
                self._trabajo(con, self._al_paso)
                fallo = None
            except Exception as exc:  # noqa: BLE001 — el hilo no muere por una vuelta mala (regla dura 2)
                fallo = f"{type(exc).__name__}: {exc}"
                print(f"[snapshotter] ciclo lento fallido: {fallo}", flush=True)
                # Tras un fallo no se sabe cómo quedó la conexión (una
                # transacción a medias, la base que no abría): la siguiente
                # vuelta abre otra.
                if con is not None:
                    try:
                        con.close()
                    except Exception as exc_cierre:  # noqa: BLE001
                        print(f"[snapshotter] la conexión del ciclo lento no cerró: {exc_cierre}",
                              flush=True)
                    con = None
            finally:
                self._acabar(empieza, fallo)


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


def _pedir_lo_caro(lento: CicloLento | None) -> bool:
    """Toca medir lo caro: se le pide al hilo. Devuelve True si no hay hilo al
    que pedírselo y hay que medirlo dentro del latido, como antes de C-0309:
    más lento, pero el respaldo y la copia diaria de la base no se quedan sin
    hacer."""
    if lento is None:
        return True
    try:
        pedido = lento.pedir()
    except Exception as exc:  # noqa: BLE001 — sin hilo se mide dentro, y se dice
        _racha_lenta("el hilo del ciclo lento",
                     f"el hilo del ciclo lento no arranca ({exc}): se mide dentro del latido")
        return True
    _racha_lenta("el hilo del ciclo lento", None)
    # Que el anterior siga a los diez minutos es un disco colgado o un escaneo
    # eterno: no se lanza otro encima, y se dice una vez por racha.
    _racha_lenta("el ciclo lento", None if pedido else
                 "el ciclo lento anterior no ha acabado: no se lanza otro encima")
    return False


def vuelta(con: sqlite3.Connection, ciclos: int, lento: CicloLento | None = None) -> None:
    """Una vuelta del demonio, cada paso en su `try` (reglas duras 2 y 21,
    decisión 376): uno que falla siempre no puede dejar sin hacer los demás.

    El 7-nov una carpeta de OneDrive ilegible tumbó el muestreo durante
    minutos, y con él los programados y el despertar del orquestador, que
    venían detrás en el mismo `try`.

    Con `lento`, lo caro no se mide aquí: se le pide a su hilo y la vuelta
    sigue (C-0309). Sin él se mide dentro, como siempre.
    """
    # El latido va primero y aparte: es lo que dice «estoy vivo» aunque no
    # haya tmux que muestrear o el ciclo falle (decisión 289). Y el estado del
    # ciclo lento se lee antes y en su `try`: un dato de más no puede dejar al
    # hub sin latido.
    estado_lento = None
    if lento is not None:
        try:
            estado_lento = lento.estado()
        except Exception as exc:
            print(f"[snapshotter] estado del ciclo lento: {exc}", flush=True)
    try:
        if estado_lento is None:
            salud.latir()
        else:
            salud.latir(lento=estado_lento)
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
    sai_medido = False
    try:
        # Al arrancar se mide una vez: tras un reinicio de WSL, el panorama
        # no puede estar en blanco esperando diez minutos.
        if ciclos % CADA_CUANTOS_CICLOS_LO_CARO == 0 and _pedir_lo_caro(lento):
            if lento is None:
                ciclo_lento(con)
                sai_medido = True
            else:
                lento.dentro(con)
    except Exception as exc:
        print(f"[snapshotter] ciclo lento: {exc}", flush=True)
    try:
        # Aparte del ciclo lento y más a menudo: el SAI aguanta ~22 min
        # y enterarse del corte a los diez gastaría media reserva
        # esperando. Cuesta un `powershell`, así que cabe (regla 14).
        # Se queda en el latido, y SÓLO en él (decisión 249): el ciclo lento
        # de un `CicloLento` no lo mide, porque su lectura, guardada segundos
        # después, pisaba la más fresca de aquí. Sólo se salta sin hilo
        # (`lento=None`), donde el ciclo lento acaba de medirlo aquí mismo.
        if not sai_medido and ciclos % CADA_CUANTOS_CICLOS_EL_SAI == 0:
            maquina.escanear_ups(con)
    except Exception as exc:
        print(f"[snapshotter] sai: {exc}", flush=True)


def espera_hasta_la_siguiente(transcurrido: float) -> float:
    """Cuánto duerme el bucle tras una vuelta que tardó `transcurrido` segundos.

    A plazo fijo: dormir el intervalo entero después de cada vuelta daba un
    periodo de 20 s más lo que durase (22,9 s de media, medido), y «cada 30
    vueltas» ya no eran diez minutos. Al menos un segundo: una vuelta más
    larga que el intervalo no puede dejar el bucle girando sin pausa."""
    return max(1.0, config.INTERVALO_SEGUNDOS - transcurrido)


def main() -> None:  # pragma: no cover - bucle del demonio
    config.asegurar_home()
    con = db.abrir()
    # El hilo se levanta con el primer `pedir`, en la primera vuelta. Si no
    # arranca, esa vuelta y las siguientes miden dentro (`_pedir_lo_caro`).
    lento = CicloLento()
    ciclos = 0
    while True:
        empieza = time.monotonic()
        try:
            vuelta(con, ciclos, lento)
        except Exception as exc:  # el demonio nunca muere por un ciclo malo
            print(f"[snapshotter] ciclo fallido: {exc}", flush=True)
        ciclos += 1
        time.sleep(espera_hasta_la_siguiente(time.monotonic() - empieza))


if __name__ == "__main__":  # pragma: no cover
    main()
