"""Capa de lectura única.

UI, asistente y el futuro MCP consumen esto y nada más (decisión 25). Si la UI
empieza a leer archivos o SQL por su cuenta, cada función nueva multiplica los
caminos y el MCP del VPS se vuelve un rework completo.

Convención de `snapshot.preservado`:
    0 = muestra normal, entra en la ventana rodante
    1 = último antes de un corte detectado, pendiente de revisar
    2 = ya revisado por el usuario (se conserva, deja de anunciarse)
"""

from __future__ import annotations

import contextlib
import re
import sqlite3
from collections import Counter
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import base
from . import config
from . import copia_base
from . import navegacion as _navegacion
from . import navegador
from . import opcionales as _opcionales
from . import procesos
from . import restauracion as _restauracion
from . import registry
from . import servicios as _servicios
from . import reloj
from . import repos as _repos
from . import tiempos
from . import tmux
from . import transcripts
from . import version as _version
from .models import Proyecto, Ruta


def _fila_a_dict(fila: sqlite3.Row) -> dict[str, Any]:
    return {k: fila[k] for k in fila.keys()}


def ruta_corta(ruta: str | None) -> str:
    """Una ruta reconocible como ruta, en el ancho de una barra lateral.

    Existe por un fallo de lectura real: la barra mostraba sólo el último
    segmento, así que el slot «respaldo pendiente» de `/home/usuario/dev/tienda`
    se subtitulaba `tienda` —idéntico al nombre de su proyecto— y se leía como si
    hubiera dos proyectos Tienda. Con `~/dev/tienda` y `…/trabajo/plataforma` la
    ambigüedad desaparece: se ve que es una ruta.

    Se conservan DOS segmentos y no uno porque el último rara vez distingue: en
    un inventario real, tres carpetas distintas terminaban en hojas parecidas y
    sin el padre no se sabía cuál era cuál.
    """
    if not ruta:
        return ""
    limpia = ruta.rstrip("/")
    # El home real de quien corre el hub, no uno cableado: esto se ejecuta en
    # máquinas ajenas.
    for prefijo in (str(Path.home()), "/root"):
        if limpia == prefijo or limpia.startswith(prefijo + "/"):
            return "~" + limpia[len(prefijo):]
    partes = [p for p in limpia.split("/") if p]
    if len(partes) <= 2:
        return limpia
    return "…/" + "/".join(partes[-2:])


def _a_modelo(datos: dict) -> Proyecto:
    """Reconstruye el modelo desde el índice.

    Los módulos que leen el filesystem (`base`, `catalogo`) hablan `Proyecto`,
    no filas de SQL. Convertir aquí mantiene la costura única: la UI sigue
    llamando sólo a `api`.
    """
    return Proyecto(
        id=datos["id"],
        nombre=datos["nombre"],
        dominio=datos.get("dominio", "personal"),
        tipo=datos.get("tipo", "proyecto"),
        asiento=datos.get("asiento"),
        rutas=[Ruta(ruta=r["ruta"], tipo=r["tipo"]) for r in datos.get("rutas", [])],
        estado_ref=datos.get("estado_ref"),
        base_version=datos.get("base_version"),
        guardrail=datos.get("guardrail", "ask"),
        status=datos.get("status", "activo"),
        nota=datos.get("nota", ""),
    )


def listar_proyectos(con: sqlite3.Connection, dominio: str | None = None,
                     incluir_archivados: bool = False) -> list[dict]:
    """El registro, sin los archivados salvo que se pidan: la guía cuenta como
    el raíl, con ellos (C-0056)."""
    sql = "SELECT * FROM proyecto WHERE " + ("1" if incluir_archivados else "status != 'archivado'")
    args: tuple = ()
    if dominio:
        sql += " AND dominio = ?"
        args = (dominio,)
    sql += " ORDER BY nombre COLLATE NOCASE"
    return [_fila_a_dict(f) for f in con.execute(sql, args)]


def obtener_proyecto(con: sqlite3.Connection, proyecto_id: str) -> dict | None:
    fila = con.execute("SELECT * FROM proyecto WHERE id=?", (proyecto_id,)).fetchone()
    if not fila:
        return None
    datos = _fila_a_dict(fila)
    datos["rutas"] = [
        _fila_a_dict(f)
        for f in con.execute(
            "SELECT ruta, tipo FROM proyecto_ruta WHERE proyecto_id=? ORDER BY tipo, ruta",
            (proyecto_id,),
        )
    ]
    return datos


def snapshot_actual(con: sqlite3.Connection) -> dict | None:
    """La última muestra, y sólo si es del servidor de tmux que sigue vivo.

    🔴 Se mira el último snapshot a secas y se descarta si está preservado; no
    es lo mismo que pedir `WHERE preservado = 0`. Al morir el servidor,
    `detectar_corte` marca sólo la ÚLTIMA muestra de ese epoch, y la penúltima
    —mismo servidor muerto, mismos paneles— pasaba a ser la «actual» sin que
    nadie la pisara, porque sin servidor no se escribe un snapshot vacío
    (regla dura 4). Tras reiniciar WSL, el hub enseñaba como abiertas
    terminales que ya no existían, con su «Abrir» llevando a una sesión muerta.

    Sin muestra viva no hay nada abierto, que es la verdad. Lo que se perdió lo
    enseña `recuperacion_pendiente`, que es la que lee los preservados.
    """
    fila = con.execute("SELECT * FROM snapshot ORDER BY id DESC LIMIT 1").fetchone()
    if fila is None or fila["preservado"]:
        return None
    return _fila_a_dict(fila)


def paneles_de(con: sqlite3.Connection, snapshot_id: int) -> list[dict]:
    return [
        _fila_a_dict(f)
        for f in con.execute(
            """SELECT p.*, s.nombre AS slot_nombre, pr.nombre AS proyecto_nombre
               FROM panel p
               LEFT JOIN slot s ON s.id = p.slot_id
               LEFT JOIN proyecto pr ON pr.id = p.proyecto_id
               WHERE p.snapshot_id = ?
               ORDER BY p.session, p.window_idx, p.pane_idx""",
            (snapshot_id,),
        )
    ]


@tiempos.medido
def paneles_abiertos(con: sqlite3.Connection) -> list[dict]:
    actual = snapshot_actual(con)
    return paneles_de(con, actual["id"]) if actual else []


def panel_por_id(con: sqlite3.Connection, pane_id: str) -> dict | None:
    """El panel del último muestreo, por su id de tmux.

    Existe para que una acción sobre un panel no tenga que recibir la sesión y
    el índice de ventana por el formulario: el HTML puede llevar minutos abierto
    y esos dos datos cambian solos cuando se mueve una ventana. El `pane_id` no.
    """
    return next((p for p in paneles_abiertos(con) if p["pane_id"] == pane_id), None)


def recuperacion_pendiente(con: sqlite3.Connection) -> dict | None:
    """Lo que se perdió en el último corte, si aún no se ha revisado.

    No dice "se perdieron 23 paneles" — eso son IDs sin significado. Devuelve los
    slots y las rutas, que es lo que permite retomar.

    Un corte sin nada abierto no se anuncia: el snapshotter preserva la última
    muestra de cada servidor que muere, tuviera paneles o no, y reiniciar con
    la terminal cerrada dejaba un «se perdió una sesión · 0 paneles» que no
    había perdido nada. Un aviso sin nada que hacer se aprende a ignorar.
    """
    fila = con.execute(
        """SELECT * FROM snapshot s
           WHERE s.preservado = 1
             AND EXISTS (SELECT 1 FROM panel p WHERE p.snapshot_id = s.id)
           ORDER BY s.id DESC LIMIT 1"""
    ).fetchone()
    if not fila:
        return None
    datos = _fila_a_dict(fila)
    datos["paneles"] = paneles_de(con, fila["id"])
    datos["proyectos"] = sorted(
        {p["proyecto_nombre"] for p in datos["paneles"] if p["proyecto_nombre"]}
    )
    datos.update(_como_esta_el_corte(datos["paneles"], paneles_abiertos(con), datos["tomado_en"]))
    return datos


# Un corte de hace más de esto se enseña plegado (C-0296): lo de hoy no puede
# quedar a cinco pantallas por un aviso de hace días.
CORTE_RECIENTE_SEGUNDOS = 24 * 3600


def _como_esta_el_corte(antes: list[dict], ahora: list[dict], tomado_en: str | None) -> dict:
    """Lo que quedó del corte en el tmux de ahora, por ventana (C-0296).

    🔴 tmux-resurrect/continuum devuelve las ventanas solo, con su sesión y su
    índice; lo que no devuelve es el agente que corría dentro (decisión 261:
    vuelven como `bash`). El aviso seguía diciendo «se perdió» cinco días
    después y empujaba a abrirlas otra vez. Aquí sólo se mide; la muestra
    preservada no se toca (regla dura 4) y nada se archiva ni se oculta solo
    (principio 9): con todo devuelto, o pasado un día, se pliega.
    """
    from . import tui

    def por_ventana(paneles: list[dict]) -> dict[tuple, bool]:
        ventanas: dict[tuple, bool] = {}
        for p in paneles:
            clave = (p["session"], p["window_idx"])
            con_agente = tui.reconocer(p.get("comando") or "", p.get("titulo") or "") is not None
            ventanas[clave] = ventanas.get(clave, False) or con_agente
        return ventanas

    previas, actuales = por_ventana(antes), por_ventana(ahora)
    devueltas = [k for k in previas if k in actuales]
    sin_su_agente = sum(1 for k, agente in previas.items() if agente and not actuales.get(k))
    todo_devuelto = len(devueltas) == len(previas) and not sin_su_agente
    reciente = _segundos_desde(tomado_en) < CORTE_RECIENTE_SEGUNDOS
    return {
        "ventanas": len(previas),
        "devueltas": len(devueltas),
        "sin_su_agente": sin_su_agente,
        "todo_devuelto": todo_devuelto,
        "reciente": reciente,
        "abierta": reciente and not todo_devuelto,
        "tomado_en": tomado_en,
    }


def marcar_recuperacion_revisada(con: sqlite3.Connection, snapshot_id: int) -> None:
    con.execute("UPDATE snapshot SET preservado = 2 WHERE id = ?", (snapshot_id,))


@tiempos.medido
def slots_de(
    con: sqlite3.Connection, proyecto_id: str, incluir_archivados: bool = False
) -> list[dict]:
    sql = "SELECT * FROM slot WHERE proyecto_id = ?"
    if not incluir_archivados:
        sql += " AND status = 'activo'"
    # ultima_actividad es dato, no gestión: columna ordenable, sin avisos (decisión 14).
    sql += " ORDER BY (ultima_actividad IS NULL), ultima_actividad DESC, nombre"
    filas = [_fila_a_dict(f) for f in con.execute(sql, (proyecto_id,))]
    for f in filas:
        f["ruta_corta"] = ruta_corta(f.get("ruta"))
    return filas


def estado_de_panel(panel: dict | None) -> str:
    """Qué está pasando en el panel de un slot, para el punto de la barra.

    Nace de una pregunta concreta: *"si tengo un segundo slot en ejecución y ese
    termina o se pausa para hacerme preguntas, quiero enterarme"*. La respuesta
    ya estaba en la base de datos —`panel.titulo` se guarda con el glifo crudo
    que escribe Claude Code— y no se estaba usando para nada.

    Cuatro estados, y los cuatro significan algo distinto para quien mira:

        trabajando  el spinner gira: no hace falta ir
        detenido    Claude está quieto. **Es el que pide atención**: acabó, o
                    está esperando una respuesta tuya. Desde el título no se
                    puede saber cuál de las dos.
        otro        una shell, o algo que no reporta estado: nada que medir
        cerrado     el slot no tiene panel abierto en el último muestreo

    El dato es tan fresco como el snapshot, o sea hasta `INTERVALO_SEGUNDOS` de
    retraso. Es deliberado: leer tmux en vivo daría 3 segundos, pero el caso de
    uso es enterarse de que algo paró, no cronometrarlo.

    «Trabajando» también si el muestreo lo vio en la pantalla (`panel.ocupado`,
    decisión 393): con una herramienta larga el título se queda en reposo.
    """
    if panel is None:
        return "cerrado"
    titulo = panel.get("titulo") or ""
    if panel.get("ocupado") or tmux.es_spinner(titulo):
        return "trabajando"
    if tmux.tiene_glifo_estado(titulo):
        return "detenido"
    return "otro"


def slots_activos(con: sqlite3.Connection) -> list[dict]:
    """Todos los slots activos, con el nombre de su proyecto.

    Existe para poder ofrecer «mover esta ventana a un trabajo de OTRO
    proyecto». La ruta no siempre dice de qué va el trabajo: se puede estar en
    una carpeta cualquiera hablando del hub, y hasta ahora la barra sólo
    ofrecía slots del proyecto que salía del `cwd`, así que ese caso no tenía
    salida ninguna.
    """
    filas = [
        _fila_a_dict(f)
        for f in con.execute(
            """SELECT s.*, p.nombre AS proyecto_nombre
                 FROM slot s JOIN proyecto p ON p.id = s.proyecto_id
                WHERE s.status = 'activo'
                ORDER BY p.nombre, s.nombre"""
        )
    ]
    for f in filas:
        f["ruta_corta"] = ruta_corta(f.get("ruta"))
    return filas


def notas_de_slots(con: sqlite3.Connection) -> list[dict]:
    """Los slots con nota, sean del estado que sean, y su última actividad.

    La lee el secretario como fuente (`secretario/fuentes/hub.py`): antes la
    consultaba con su propio SQL, el camino paralelo que esta costura existe
    para evitar."""
    return [dict(f) for f in con.execute(
        "SELECT s.id, s.nombre, s.nota, s.proyecto_id, COALESCE(s.ultima_actividad, s.creado_en) AS fecha"
        "  FROM slot s WHERE s.nota != '' ORDER BY s.id")]


def obtener_slot(con: sqlite3.Connection, slot_id: int) -> dict | None:
    fila = con.execute("SELECT * FROM slot WHERE id=?", (slot_id,)).fetchone()
    return _fila_a_dict(fila) if fila else None


def panel_de_slot(con: sqlite3.Connection, slot_id: int) -> dict | None:
    """Dónde está viviendo ahora mismo un slot, si es que está abierto.

    Es el puente entre el índice y la terminal: da la sesión y la ventana a las
    que hay que atacarse para ver ese trabajo.
    """
    actual = snapshot_actual(con)
    if not actual:
        return None
    fila = con.execute(
        """SELECT * FROM panel
           WHERE snapshot_id = ? AND slot_id = ?
           ORDER BY window_idx, pane_idx LIMIT 1""",
        (actual["id"], slot_id),
    ).fetchone()
    return _fila_a_dict(fila) if fila else None


def paneles_de_slot(con: sqlite3.Connection, slot_id: int) -> list[dict]:
    """Todas las ventanas de un slot en el último muestreo, en su orden.

    `panel_de_slot` da sólo la primera, que basta para «dónde vive el slot»
    pero no para escribirle a su agente: un slot puede tener un `claude` y
    ocho `bash` restaurados, o dos agentes (C-0225)."""
    actual = snapshot_actual(con)
    if not actual:
        return []
    return [_fila_a_dict(f) for f in con.execute(
        """SELECT * FROM panel WHERE snapshot_id = ? AND slot_id = ?
           ORDER BY window_idx, pane_idx""", (actual["id"], slot_id))]


def contexto_trabajo(
    con: sqlite3.Connection,
    slot_id: int | None = None,
    session: str | None = None,
    ventana: int | None = None,
) -> dict:
    """Todo lo que necesita la vista de trabajo, en una sola llamada.

    Con `slot_id` el destino se resuelve solo. Con `session`+`ventana` se entra
    directo a un panel suelto, que es el caso de la bandeja de entrada: todavía
    no es un slot pero quieres verlo ya.
    """
    # Una sola muestra para los paneles y su servidor: de dos lecturas, un
    # reinicio de tmux entre ellas casaba `%N` de un servidor con el otro (396).
    actual = snapshot_actual(con)
    paneles = paneles_de(con, actual["id"]) if actual else []
    por_proyecto: dict[str, int] = {}
    for panel in paneles:
        if panel["proyecto_id"]:
            por_proyecto[panel["proyecto_id"]] = por_proyecto.get(panel["proyecto_id"], 0) + 1

    # El panel de cada slot, para poder decir qué está haciendo. Se toma el
    # primero igual que `panel_de_slot`: si un slot tuviera dos, dos puntos
    # distintos junto al mismo nombre no se sabrían leer.
    panel_por_slot: dict[int, dict] = {}
    for panel in paneles:
        if panel["slot_id"] and panel["slot_id"] not in panel_por_slot:
            panel_por_slot[panel["slot_id"]] = panel

    # Las ventanas de cada slot, colgadas de él en el raíl: proyecto → slot →
    # ventanas, «como carpetas, una dentro de otra» (decisión 291). Una por
    # ventana de tmux, no por panel: una ventana partida en dos es una sola.
    ventanas_por_slot: dict[int, list[dict]] = {}
    vistas: set[tuple[str, int]] = set()
    panes = _paneles_por_ventana(paneles)
    for panel in paneles:
        clave = (panel["session"], panel["window_idx"])
        if not panel["slot_id"] or clave in vistas:
            continue
        vistas.add(clave)
        ventanas_por_slot.setdefault(panel["slot_id"], []).append({
            "session": panel["session"], "ventana": panel["window_idx"],
            "pane_id": panel["pane_id"], "panes": panes[clave],
            "etiqueta": panel.get("etiqueta") or f"{panel['session']}:{panel['window_idx']}",
            "estado": estado_de_panel(panel),
        })

    proyectos = listar_proyectos(con)
    for p in proyectos:
        p["slots"] = slots_de(con, p["id"])
        for s in p["slots"]:
            s["estado"] = estado_de_panel(panel_por_slot.get(s["id"]))
            s["ventanas"] = ventanas_por_slot.get(s["id"], [])
        p["paneles_abiertos"] = por_proyecto.get(p["id"], 0)
        # Un proyecto entra en la barra si hay algo suyo que mirar. Se calcula
        # aquí y no en la plantilla porque «slots O paneles» en Jinja obliga a
        # un `namespace` con bucle, y el rótulo de la sección necesita saber de
        # antemano si va a quedar vacía.
        p["en_uso"] = bool(p["slots"] or p["paneles_abiertos"])

    # Entrar por `?session=` es el atajo de la bandeja: ver ya un panel que
    # todavía no es slot. Pero si ESA ventana sí tiene slot, hay que resolverlo
    # —si no, la nota no aparece y el único camino para escribirla es dar el
    # rodeo por el proyecto, que es justo lo que el atajo evitaba.
    if not slot_id and session:
        slot_id = _slot_de_ventana(paneles, session, ventana)

    slot = obtener_slot(con, slot_id) if slot_id else None
    if slot:
        # 🔴 La ventana pedida manda si es de ese slot (C-0242). El slot sólo
        # dice cuál enseñar cuando no se pidió ninguna: antes se cambiaba
        # siempre por su primera, y en un slot con ventanas en dos sesiones
        # pulsar cualquiera de la otra devolvía a la primera.
        pedida = session is not None and ventana is not None and any(
            p["slot_id"] == slot["id"] and p["session"] == session and p["window_idx"] == ventana
            for p in paneles)
        panel = None if pedida else panel_de_slot(con, slot["id"])
        if panel:
            session = panel["session"]
            ventana = panel["window_idx"]
        elif not pedida:
            ventana = None
        slot["abierto"] = pedida or panel is not None

    return {
        "proyectos": proyectos,
        "slot": slot,
        "session": session,
        "ventana": ventana,
        "paneles": paneles,
        # El estado de CADA ventana de la sesión, no sólo de la que se abrió.
        # Cambiar de pestaña no recarga la página, así que si el panel derecho
        # se calculara sólo para la ventana inicial, seguirías viendo —y
        # editando— la nota de otro trabajo sin que nada lo dijera.
        "ventanas_estado": _estado_por_ventana(con, paneles, session),
        # La ventana concreta que se está mirando, para el primer pintado.
        "vinculable": _estado_de_ventana(con, paneles, session, ventana),
        # El servidor de tmux del muestreo con el que se pinta: viaja con cada
        # «Cerrar», porque los `%N` se reutilizan al reiniciarlo (396). El del
        # muestreo y no el de ahora: lo que se ve es de ése.
        "servidor": actual["server_pid"] if actual else None,
    }


@tiempos.medido
def rail(con: sqlite3.Connection) -> dict:
    """Lo que necesita el raíl global, que sale en TODAS las pantallas.

    Sólo vistas y sus cifras. Los proyectos salieron de aquí (decisión 253):
    en el móvil llenaban el menú, y los commits en riesgo siguen a la vista en el
    contador de Respaldo.

    Se piden pocos datos y baratos a propósito. Esto corre en cada petición,
    incluida `/trabajo`, donde una consulta lenta se nota al abrir el terminal.
    """
    sin_push: dict[str, int] = {}
    for r in _repos.deduplicar([_fila_a_dict(f) for f in con.execute("SELECT * FROM repo")]):
        if r.get("sin_push"):
            sin_push[r["proyecto_id"]] = sin_push.get(r["proyecto_id"], 0) + int(r["sin_push"])

    paneles = paneles_abiertos(con)

    corriendo, medido_svc = con.execute(
        "SELECT COUNT(CASE WHEN estado = 'running' THEN 1 END), MAX(medido_en) FROM servicio"
    ).fetchone()
    # Sobre una lectura que no es de ahora no se cuenta: «Servicios 1» con
    # Docker ausente desde hace días es una cifra que no se puede defender
    # (regla dura 13, C-0293).
    if not _vigencia_servicios(medido_svc)[0]:
        corriendo = None
    # ¿Hay algún proyecto declarado con `tipo: asistente`? Sin él no hay chat que
    # abrir, y pintar su pestaña sería ofrecer algo que sólo puede fallar: el
    # error aparecía al pulsarla, que es el peor momento para enterarse.
    hay_asistente = bool(
        con.execute("SELECT 1 FROM proyecto WHERE tipo = 'asistente' LIMIT 1").fetchone()
    )
    # Un hub recién instalado no tiene nada que enseñar. Es dato del raíl porque
    # la guía de arranque sale en la portada y depende de lo mismo que él.
    # 🔴 Sólo los que tienen carpeta: el registro recién instalado trae dos de
    # ejemplo con rutas inventadas, y contándolos la guía de arranque no salía
    # NUNCA en una instalación nueva — justo donde existe (sala limpia, 16-oct).
    total_proyectos = sum(
        1 for (asiento,) in con.execute(
            "SELECT asiento FROM proyecto WHERE tipo NOT IN ('asistente', 'kit')")
        if asiento and _carpeta_existe(asiento))
    # Barato: tres archivos pequeños. Va en el raíl porque «falta terminar de
    # actualizar» tiene que verse en cualquier pantalla (decisión 286).
    try:
        version = _version.estado()
    except Exception:  # noqa: BLE001 — un pyproject raro no tumba todas las pantallas
        version = None
    # Que el muestreo no corre se dice en todas las pantallas: sin él, un
    # apagón no tiene vuelta, y enterarse después es tarde (decisión 289).
    # Barato: un archivo.
    try:
        from . import salud as _salud
        muestreo = _salud.muestreo()
    except Exception:  # noqa: BLE001
        muestreo = None
    from . import navegante as _nav
    secretario_nombre = nombre_secretario()
    # Quién te habla en todas las pantallas (C-0160): el secretario si lo
    # pusiste en Ajustes → Personaje (C-0239; antes, `en_todo_el_hub: true` en
    # `secretario.yml`) y está montado; si no, el asistente. Nunca los dos.
    voz, ingles, personaje = ("asistente" if hay_asistente else None), False, None
    if secretario_en_todo_el_hub():
        from .secretario import memoria as _mem, personaje as _pj
        voz, ingles = "secretario", bool(_mem.leer_sin_abrir("modo_ingles"))
        # Quién es (C-0188): lo elegido en su galería, en cualquier aparato.
        personaje = _mem.leer_sin_abrir(_pj.CLAVE)
    # Lo que espera y lo que delegó, para que el personaje salga ya bien
    # pintado (C-0166), y sólo donde se pinta; la misma consulta da la cifra
    # de pendientes. Sin él, la cuenta de siempre.
    espera = secretario_espera(con) if voz == "secretario" else None
    datos = {
        "navegante_pendientes": _nav.pendientes() if _nav.instalado() else 0,
        "secretario_pendientes": espera["solicitudes"] if espera else secretario_pendientes(),
        "secretario_espera": espera,
        # Las del chat vacío del panel (UI-33), de la misma espera.
        "secretario_ideas": secretario_ideas(espera) if espera else [],
        "version": version,
        "muestreo": muestreo,
        "sin_respaldo": sum(sin_push.values()),
        "servicios": corriendo,
        "paneles": len(paneles),
        "hay_asistente": hay_asistente,
        "voz": voz,
        "secretario_ingles": ingles,
        "personaje": personaje_vista(personaje),
        "secretario_nombre": secretario_nombre,
        "total_proyectos": total_proyectos,
        # Las herramientas opcionales encendidas (438): un archivo pequeño y
        # recordado. Sólo dice qué entradas salen; al puente no se le
        # pregunta nada desde aquí.
        "opcionales": sorted(_opcionales.encendidas()),
    }
    # Las mismas cifras, repartidas en las nueve secciones de la interfaz nueva
    # (C-0169). Sale de lo de arriba, sin leer nada más: el raíl de siempre no
    # lo mira, y el nuevo no enseña ninguna señal que éste no dé.
    datos["secciones"] = _navegacion.con_cifras(datos)
    return datos


def ocultos(con: sqlite3.Connection) -> list[dict]:
    """Lo que se ha sacado de la bandeja a mano, para contarlo y devolverlo.

    Se lee siempre, aunque la ventana ya no exista: una sesión de node que hoy
    está apagada sigue oculta mañana, y si no se listara aquí no habría forma de
    destaparla — sólo se podría desde una ventana que no está abierta.
    """
    return [
        _fila_a_dict(f)
        for f in con.execute(
            "SELECT session, window_idx, creado_en FROM oculto"
            " ORDER BY session, IFNULL(window_idx, -1)"
        )
    ]


def _oculta(reglas: set, session: str, ventana: int | None) -> bool:
    """¿Tapa alguna regla a esta ventana? La de la sesión entera vale para todas."""
    return (session, None) in reglas or (session, ventana) in reglas


def _ventanas_atadas(paneles: list[dict]) -> set[tuple[str, int]]:
    """Las ventanas con algún panel atado a un slot: ésas salen bajo su slot y
    en ninguna bandeja.

    🔴 La regla de «suelta» es UNA para las dos pantallas (C-0425): la portada
    contaba paneles sin slot y «Sin organizar» ventanas sin ninguno, así que
    una ventana partida con un panel atado salía bajo su slot en /trabajo y,
    por su otro panel, en la bandeja de la portada. Es la queja del 10-sep
    («veo una en sin organizar que también está en trabajo») por otra puerta."""
    return {(p["session"], p["window_idx"]) for p in paneles if p["slot_id"]}


def _paneles_por_ventana(paneles: list[dict]) -> dict[tuple[str, int], list[str]]:
    """Todos los `pane_id` de cada ventana. Una fila del raíl o de la bandeja
    es una ventana, y sigue viva mientras le quede alguno: con sólo el primero,
    una ventana partida que perdiera ése se daría por muerta estando viva
    (C-0234)."""
    panes: dict[tuple[str, int], list[str]] = {}
    for p in paneles:
        panes.setdefault((p["session"], p["window_idx"]), []).append(p["pane_id"])
    return panes


def bandeja_de_ventanas(
    con: sqlite3.Connection, sesiones: list[dict], paneles: list[dict]
) -> tuple[list[dict], list[dict]]:
    """Las ventanas sin slot, **una fila por ventana**, y las que están ocultas.

    Sustituye a la lista por sesión de la barra. El defecto que arregla lo vio
    él: *«veo una ventana que me aparece sin vincular en organizar pero que sí
    me aparece en trabajo»*. Con la unidad puesta en la sesión, `Personal` salía
    arriba bajo su slot «Hub - Dev» —dos de sus tres ventanas están ahí— y
    abajo en «Sin organizar» por la tercera. La misma cosa en dos sitios
    diciendo lo contrario, y al pulsar abajo se abría la ventana ACTIVA, que era
    una de las ya vinculadas.

    Con una fila por ventana no hay ambigüedad posible: lo que sale abajo es
    exactamente lo que no tiene slot, y pulsarlo lleva a esa ventana y no a otra.

    🔴 Una ventana cuenta como suelta cuando NINGUNO de sus paneles tiene slot.
    Con «alguno» —el criterio anterior— una ventana partida en dos, con un panel
    vinculado, volvería a salir en los dos sitios a la vez: es el mismo defecto
    por otra puerta.
    """
    reglas = {(f["session"], f["window_idx"]) for f in ocultos(con)}

    # Panel representante de cada ventana y si alguno de ellos tiene slot.
    panes = _paneles_por_ventana(paneles)
    primero: dict[tuple[str, int], dict] = {}
    for p in paneles:
        primero.setdefault((p["session"], p["window_idx"]), p)
    con_slot = _ventanas_atadas(paneles)

    visibles, tapadas = [], []
    for s in sesiones:
        nombre = s["session"]
        suyas = sorted(v for (ses, v) in primero if ses == nombre)
        # Si es la única ventana de su sesión, cerrarla se lleva la sesión
        # entera: tmux la mata al morir su última ventana. Lo tiene que saber
        # quien pinte el botón, o el aviso diría menos de lo que va a pasar.
        unica = len(suyas) == 1

        # Una sesión que el snapshotter aún no ha visto no tiene ventanas
        # conocidas. Tratarla como organizada la escondería sin haberla mirado,
        # así que entra con una fila propia y sin número de ventana.
        if not suyas:
            fila = {
                "session": nombre, "ventana": None, "etiqueta": nombre,
                "pane_id": None, "cwd": "", "ruta_corta": "",
                "proyecto_nombre": None, "desconocida": True, "ultima": False,
            }
            (tapadas if _oculta(reglas, nombre, None) else visibles).append(fila)
            continue

        for v in suyas:
            if (nombre, v) in con_slot:
                continue          # ya sale arriba, bajo su slot
            p = primero[(nombre, v)]
            fila = {
                "session": nombre, "ventana": v,
                "etiqueta": p["etiqueta"] or f"{nombre}:{v}",
                "pane_id": p["pane_id"], "panes": panes[(nombre, v)], "cwd": p["cwd"],
                "ruta_corta": ruta_corta(p["cwd"]),
                "proyecto_nombre": p["proyecto_nombre"], "desconocida": False,
                "ultima": unica,
            }
            (tapadas if _oculta(reglas, nombre, v) else visibles).append(fila)

    return visibles, tapadas


# Lo que tarda tmux-resurrect en devolver las ventanas al arrancar, con
# holgura: una ventana con actividad dentro de este margen nació con el
# servidor. Lo que se toque después ya no cuenta como «sin usar» (C-0352).
MARGEN_DEL_ARRANQUE = 120


def shells_quietas(con: sqlite3.Connection, paneles: list[dict]) -> dict:
    """Las ventanas que son sólo una shell y no han tenido actividad desde que
    arrancó tmux (más `MARGEN_DEL_ARRANQUE`), para ofrecer cerrarlas (C-0352).

    Tras una restauración vuelven como `bash` las ventanas de todo lo que había
    —doce sin slot en el hallazgo, más las de los slots—, y con ~20 sitios el
    ruido tapa lo que sí está vivo. Aquí sólo se señalan: cerrarlas es un
    botón suyo, marcándolas una a una y con confirmación (regla dura 3), por
    `tmux.cerrar_ventana_de` (396). Una ventana cuenta si tmux no le ha visto
    salida desde el arranque y TODOS sus paneles son, ahora mismo, una shell
    en reposo: tmux dice que corre una shell (en el instante, no en la
    muestra) y `procesos.shell_en_reposo` que es una a secas y sin nada
    debajo —con `bash x.sh` o un comando compuesto tmux dice `bash` igual—.
    La misma llamada sirve para volver a mirar al cerrar (revisión cruzada).
    La cifra se queda corta antes que inflarse (regla 13). `paneles`, los de
    la muestra, dan qué ventanas se enseñan y cómo se llaman. Lo oculto a mano
    no sale, como en la bandeja. Los slots no se tocan: cerrar una ventana no
    archiva nada.
    """
    arranque, en_vivo = tmux.actividad_de_ventanas()
    if arranque is None:
        return {"ventanas": [], "arranque": ""}
    reglas = {(f["session"], f["window_idx"]) for f in ocultos(con)}
    por_ventana: dict[tuple[str, int], list[dict]] = {}
    for p in paneles:
        por_ventana.setdefault((p["session"], p["window_idx"]), []).append(p)
    quietas = []
    for (session, indice), suyos in por_ventana.items():
        viva = en_vivo.get((session, indice))
        if (viva is None or viva["actividad"] > arranque + MARGEN_DEL_ARRANQUE
                or _oculta(reglas, session, indice) or not viva["paneles"]
                or not all(x["comando"] in tmux.SHELLS and procesos.shell_en_reposo(x["pid"], tmux.SHELLS)
                           for x in viva["paneles"])):
            continue
        p = suyos[0]
        slot = next((x for x in suyos if x["slot_id"]), None)
        quietas.append({
            "session": session, "ventana": indice, "pane_id": p["pane_id"],
            "etiqueta": p["etiqueta"] or f"{session}:{indice}",
            "ruta_corta": ruta_corta(p["cwd"]),
            "slot_nombre": slot["slot_nombre"] if slot else None,
        })
    quietas.sort(key=lambda v: (v["session"], v["ventana"]))
    momento = datetime.fromtimestamp(arranque, timezone.utc).isoformat()
    return {"ventanas": quietas, "arranque": _hora_local(momento)}


def ventanas_de_sesion(
    con: sqlite3.Connection, session: str, slot_id: int | None = None
) -> list[dict]:
    """Las ventanas vivas de una sesión, diciendo **de quién es cada una**.

    🔴 Esto existe porque la franja de pestañas se pintaba llamando a
    `tmux.listar_ventanas` **directamente desde la ruta**, sin pasar por aquí. Y
    tmux no sabe nada de slots, así que las pestañas no podían saberlo: las tres
    ventanas de `Personal` se pintaban idénticas bajo el rótulo «Hub - Dev»
    cuando sólo dos son de ese slot. La tercera salía además abajo, en «Sin
    organizar», y ésa es la contradicción que él lleva reportando desde hace
    semanas: la misma ventana en dos sitios diciendo cosas distintas.

    Los arreglos anteriores —la bandeja por ventanas (179), el slot sin ventana
    (180)— no la tocaron porque los tres iban por la costura de lectura y ésta
    era un camino paralelo. Es literalmente el defecto que `CLAUDE.md` describe
    al exigir una sola costura: «si una plantilla o una ruta consulta por su
    cuenta, es un defecto».

    `pertenece` tiene CUATRO valores, y el cuarto es el que evita cambiar una
    mentira por otra:

    - `este`   — es del slot que se está mirando.
    - `otro`   — es de otro slot, y se dice de cuál.
    - `ninguno`— no tiene slot: es lo mismo que sale en «Sin organizar».
    - `nueva`  — 🔴 el snapshotter todavía no la ha visto. NO es «sin slot»:
      una ventana recién creada tarda hasta un ciclo en aparecer, y marcarla
      como huérfana durante 20 s sería inventarse un dato que no se tiene.
    """
    tmux.validar_sesion(session)
    # El último muestreo, que es lo que sabe de slots. Puede ir hasta un ciclo
    # por detrás de tmux, y de ahí el estado `nueva`.
    muestreadas: dict[int, int | None] = {}
    for p in paneles_abiertos(con):
        if p["session"] != session:
            continue
        # Basta con que UN panel de la ventana tenga slot, igual que en la
        # bandeja: una ventana partida en dos con un panel vinculado es de ese
        # slot, no media.
        if p["window_idx"] not in muestreadas or p["slot_id"]:
            muestreadas[p["window_idx"]] = p["slot_id"]

    nombres = {s["id"]: s for s in (
        _fila_a_dict(f) for f in con.execute(
            """SELECT s.id, s.nombre, p.nombre AS proyecto_nombre
               FROM slot s LEFT JOIN proyecto p ON p.id = s.proyecto_id"""))}

    # 🔴 Transitorio (C-0479): el nombre del slot que el hub les ponía con `-n`
    # a las ventanas abiertas antes de ese cambio no es del dueño. Lo mismo
    # pasa el snapshotter, para que la pestaña y el árbol digan lo mismo.
    dados = {indice: {nombres[suyo]["nombre"]}
             for indice, suyo in muestreadas.items() if suyo in nombres}
    ventanas = tmux.listar_ventanas(session, dados)
    if not ventanas:
        return []

    for v in ventanas:
        indice = v["indice"]
        if indice not in muestreadas:
            v["pertenece"], v["slot"] = "nueva", None
            continue
        suyo = muestreadas[indice]
        v["slot"] = nombres.get(suyo) if suyo else None
        if not suyo:
            v["pertenece"] = "ninguno"
        elif slot_id and suyo == slot_id:
            v["pertenece"] = "este"
        elif slot_id:
            v["pertenece"] = "otro"
        else:
            # Sin slot en la cabecera no hay nada que contradecir: se entró por
            # `?session=`, así que la pestaña no tiene que justificarse.
            v["pertenece"] = "este"
    return ventanas


def _estado_por_ventana(
    con: sqlite3.Connection, paneles: list[dict], session: str | None
) -> list[dict]:
    if not session:
        return []
    indices = sorted({p["window_idx"] for p in paneles if p["session"] == session})
    estados = [_estado_de_ventana(con, paneles, session, i) for i in indices]
    return [e for e in estados if e]


def _estado_de_ventana(
    con: sqlite3.Connection,
    paneles: list[dict],
    session: str | None,
    ventana: int | None,
) -> dict | None:
    """Qué slot tiene una ventana y a cuáles podría atarse.

    Se devuelve **siempre**, tenga slot o no: sin slot hace falta para poder
    crearlo, y con slot hace falta para poder moverla o separarla. Que no
    hubiera nada que ofrecer una vez vinculada convertía el primer acierto en
    definitivo.
    """
    if not session or ventana is None:
        return None

    panel = next(
        (p for p in paneles if p["session"] == session and p["window_idx"] == ventana),
        None,
    )
    if not panel:
        return None

    slot = obtener_slot(con, panel["slot_id"]) if panel["slot_id"] else None
    # Sin proyecto no se puede crear el slot: un slot cuelga de un proyecto, y
    # adivinar cuál sería inventarse la atribución. La UI lo dice y explica que
    # se arregla registrando la ruta en projects.yml.
    hermanos = slots_de(con, panel["proyecto_id"]) if panel["proyecto_id"] else []

    # Los slots de los DEMÁS proyectos, para poder atar esta ventana a un
    # trabajo que no es el de su carpeta. Se excluye el suyo por lo mismo que
    # `otros_slots`: "mover" no puede ofrecer quedarse donde está.
    ajenos = [
        s
        for s in slots_activos(con)
        if s["proyecto_id"] != panel["proyecto_id"]
        and (not slot or s["id"] != slot["id"])
    ]

    return {
        "ventana": ventana,
        "pane_id": panel["pane_id"],
        "etiqueta": panel["etiqueta"],
        "cwd": panel["cwd"],
        # 🔴 Dos proyectos distintos y los dos hacen falta. `proyecto_id` es un
        # hecho de la RUTA y no se toca: es lo que decide si se puede crear un
        # slot aquí. `proyecto_efectivo` es de qué TRABAJO es esta ventana, que
        # es una decisión suya al vincularla, y es lo que tienen que mirar la
        # nota y los lienzos. Colapsarlos hacía que una ventana vinculada a un
        # slot de otro proyecto enseñara los lienzos del proyecto de su carpeta.
        "proyecto_id": panel["proyecto_id"],
        "proyecto_nombre": panel["proyecto_nombre"],
        "proyecto_efectivo": slot["proyecto_id"] if slot else panel["proyecto_id"],
        "slot": slot,
        "slots": hermanos,
        # Los demás slots del proyecto: a dónde se puede mover. Sin quitar el
        # suyo, "mover" ofrecería quedarse donde está.
        "otros_slots": [s for s in hermanos if not slot or s["id"] != slot["id"]],
        "slots_ajenos": ajenos,
    }


def _slot_de_ventana(
    paneles: list[dict], session: str, ventana: int | None
) -> int | None:
    """El slot de una ventana concreta, o el de la sesión si no se dice cuál.

    Sin `ventana` se acepta el slot de cualquier panel de esa sesión, pero sólo
    si **hay uno solo**: una sesión de tmux puede tener tres ventanas de tres
    trabajos distintos, y elegir la primera escribiría la nota en el sitio
    equivocado sin avisar. Ante la duda, ninguno.
    """
    candidatos = [
        p for p in paneles
        if p["session"] == session and p["slot_id"]
        and (ventana is None or p["window_idx"] == ventana)
    ]
    if ventana is not None:
        return candidatos[0]["slot_id"] if candidatos else None
    unicos = {p["slot_id"] for p in candidatos}
    return next(iter(unicos)) if len(unicos) == 1 else None


def guardar_nota(con: sqlite3.Connection, slot_id: int, nota: str) -> None:
    con.execute("UPDATE slot SET nota = ? WHERE id = ?", (nota, slot_id))


def pulso_trabajo(
    con: sqlite3.Connection, slots_nota: Sequence[int] = ()
) -> dict:
    """Lo que cambia mientras la vista de trabajo sigue abierta, sin recargarla.

    La vista se pinta entera en el servidor y luego se queda quieta durante
    horas. Eso dejaba dos cosas mintiendo en pantalla:

    - **el punto de estado**, congelado en el que tenía al abrir la página, que
      es exactamente lo contrario de para lo que existe: sirve para enterarse
      de que un segundo slot paró, y sólo se enteraba quien recargara;
    - **la nota**, cuando el mismo slot tiene dos ventanas —hay un `textarea`
      por ventana, así que escribir en una dejaba a la otra con el texto viejo—
      o cuando la escribe el asistente por su cuenta.

    Devuelve las dos cosas juntas a propósito: es un solo latido y una sola
    petición. Los estados van de TODOS los slots activos porque el raíl los
    enseña todos; las notas sólo de los que se piden, que son los del panel
    derecho —una o dos— y son lo único que pesa.

    No incluye slots nuevos ni ventanas nuevas: eso cambia la forma de la
    página, no su contenido, y repintar el raíl entero cada 5 s por si acaso
    rompería el clic en curso igual que rompía el doble clic en las pestañas.
    Sí trae los paneles del muestreo y su servidor (`paneles`, `servidor`),
    para que la página **quite** las filas de las ventanas que ya no tienen
    ninguno —las que murieron por dentro, con un `exit`— y nunca añade
    (C-0234, decisión 398).
    """
    # Una sola lectura del muestreo: los paneles y su servidor tienen que ser
    # de la misma, o un reinicio de tmux entre dos casaría `%N` de uno con el
    # otro (396).
    actual = snapshot_actual(con)
    paneles = paneles_de(con, actual["id"]) if actual else []
    panel_por_slot: dict[int, dict] = {}
    for panel in paneles:
        if panel["slot_id"] and panel["slot_id"] not in panel_por_slot:
            panel_por_slot[panel["slot_id"]] = panel

    estados = {
        f["id"]: estado_de_panel(panel_por_slot.get(f["id"]))
        for f in con.execute("SELECT id FROM slot WHERE status = 'activo'")
    }

    notas: dict[int, str] = {}
    for slot_id in dict.fromkeys(slots_nota):
        fila = con.execute("SELECT nota FROM slot WHERE id=?", (slot_id,)).fetchone()
        if fila is not None:
            notas[slot_id] = fila["nota"] or ""

    # Sin muestra viva, `None` y no `[]`: una lista vacía haría que la página
    # soltara todas sus filas (C-0234). `ventanas` son los sitios
    # (`sesión:índice`) que siguen ocupados: una ventana partida después de
    # pintar la página tiene paneles que su fila no conoce, y sin esto se
    # soltaría estando viva (revisor).
    return {"slots": estados, "notas": notas,
            "paneles": [p["pane_id"] for p in paneles] if actual else None,
            "ventanas": sorted({f"{p['session']}:{p['window_idx']}" for p in paneles}) if actual else None,
            "servidor": actual["server_pid"] if actual else None}


@tiempos.medido
def bandeja(con: sqlite3.Connection) -> list[dict]:
    """Los paneles de las ventanas sin slot, no descartados.

    Elimina la disciplina en el momento de abrir un panel: no hay que etiquetar
    nada al arrancar y aun así nada se pierde (decisión 15).

    Suelta es lo mismo que en «Sin organizar» (`_ventanas_atadas`, C-0425): el
    panel de una ventana partida cuyo otro panel ya tiene slot no es de la
    bandeja, aunque él no lo tenga.
    """
    actual = snapshot_actual(con)
    if not actual:
        return []
    descartados = {
        f["pane_id"]
        for f in con.execute(
            "SELECT pane_id FROM descartado WHERE server_pid = ?", (actual["server_pid"],)
        )
    }
    # 🔴 Lo oculto se respeta AQUÍ también. Antes «ocultar» sólo valía para la
    # barra de /trabajo, así que lo mismo salía escondido en una pantalla y a la
    # vista en la otra — que es el defecto que este cambio venía a quitar, no a
    # mover de sitio.
    reglas = {(f["session"], f["window_idx"]) for f in ocultos(con)}
    paneles = paneles_de(con, actual["id"])
    atadas = _ventanas_atadas(paneles)
    return [
        p
        for p in paneles
        if (p["session"], p["window_idx"]) not in atadas
        and p["pane_id"] not in descartados
        and not _oculta(reglas, p["session"], p["window_idx"])
    ]


@tiempos.medido
def inventario(
    con: sqlite3.Connection,
    tipo: str | None = None,
    proyecto_id: str | None = None,
    archivadas: bool = False,
) -> dict:
    """Qué capacidades existen, quién las usa y cuándo se usaron por última vez.

    Tres decisiones sobre el filtrado, las tres por el mismo motivo — un filtro
    que no filtra es peor que no tenerlo, porque se confía en él:

    - **Lo archivado no sale por defecto.** Antes salía, y encima *primero*: el
      orden pone arriba lo que no se ha usado nunca, y nada archivado se usa. Al
      filtrar por «skill» lo primero de la lista eran las skills de proyectos
      retirados, que es justo lo que nadie está buscando. Se siguen contando y
      se pueden pedir con `archivadas=True`; lo que no hacen es colarse.
    - **Las cifras de los chips ignoran el filtro de tipo.** Si no, al pulsar
      «skill» los demás chips pasaban a 0 y «Todo» mostraba el número de skills:
      la barra de filtros dejaba de decir qué hay y pasaba a describirse a sí
      misma. Sí respetan el de proyecto, que es el contexto elegido.
    - El orden mete lo archivado al final incluso cuando se pide, por lo mismo.
    """
    base = """SELECT c.*, p.nombre AS proyecto_nombre, p.status AS proyecto_status
              FROM capacidad c LEFT JOIN proyecto p ON p.id = c.proyecto_id"""
    # Lo que lleva más tiempo sin usarse arriba: es lo que se olvida. Y lo
    # archivado abajo del todo, que no está olvidado sino retirado.
    orden = (""" ORDER BY (p.status = 'archivado'), (c.usado IS NOT NULL),
                          c.usado, c.tipo, c.nombre COLLATE NOCASE""")

    def consultar(con_tipo: bool) -> list[dict]:
        donde, args = [], []
        if con_tipo and tipo:
            donde.append("c.tipo = ?")
            args.append(tipo)
        if proyecto_id:
            donde.append("c.proyecto_id = ?")
            args.append(proyecto_id)
        if not archivadas:
            donde.append("(p.status IS NULL OR p.status != 'archivado')")
        sql = base + (" WHERE " + " AND ".join(donde) if donde else "") + orden
        return [_fila_a_dict(f) for f in con.execute(sql, tuple(args))]

    capacidades = consultar(con_tipo=True)
    universo = consultar(con_tipo=False) if tipo else capacidades

    por_tipo: dict[str, int] = {}
    for c in universo:
        por_tipo[c["tipo"]] = por_tipo.get(c["tipo"], 0) + 1

    # Cuántas quedan fuera por estar archivadas, para poder decirlo en voz alta:
    # una lista que esconde cosas en silencio se lee como una lista completa.
    ocultas = 0
    if not archivadas:
        cond, args2 = ["p.status = 'archivado'"], []
        if proyecto_id:
            cond.append("c.proyecto_id = ?")
            args2.append(proyecto_id)
        ocultas = con.execute(
            "SELECT COUNT(*) FROM capacidad c LEFT JOIN proyecto p ON p.id = c.proyecto_id"
            " WHERE " + " AND ".join(cond),
            tuple(args2),
        ).fetchone()[0]

    return {
        "capacidades": capacidades,
        "por_tipo": por_tipo,
        "total": len(universo),
        "mostradas": len(capacidades),
        "ocultas_archivadas": ocultas,
        "viendo_archivadas": archivadas,
        # Sólo cuenta como olvidada lo que es medible Y sigue vivo: un método es
        # un documento que se lee, y algo archivado a propósito no está olvidado.
        "sin_uso": sum(
            1 for c in capacidades
            if c["medible"] and not c["usado"] and c["proyecto_status"] != "archivado"
        ),
        # Sobre el universo y no sobre lo listado: si se contara lo listado, la
        # cifra diría 0 en cuanto el filtro las esconde — que es precisamente
        # cuando hace falta saber que existen.
        "archivadas": ocultas + sum(
            1 for c in universo if c["proyecto_status"] == "archivado"
        ),
        # 🔴 Cuándo se escaneó. Sin esto, una foto de hace una semana y una
        # recién medida se veían idénticas: la pantalla enseñaba cifras sin
        # decir de cuándo eran, y «0 sin uso» significa cosas muy distintas si
        # el escaneo es de hoy o de antes de escribir media docena de skills.
        "medido_en": max(
            (c["medido_en"] for c in universo if c.get("medido_en")), default=None
        ),
        "no_medibles": sum(1 for c in capacidades if not c["medible"]),
        "incompletas": sum(1 for c in capacidades if c["status"] == "incompleto"),
        "tipos": sorted(por_tipo),
        "proyectos": listar_proyectos(con),
    }


def kits_de(kits_: list[dict], proyecto_id: str) -> list[dict]:
    """Los kits que le tocan a un proyecto: el suyo si ÉL es un kit, y los que consume.

    🔴 El filtro de `/inventario` comparaba el id del KIT con el del proyecto
    elegido (`k["id"] == proyecto`), así que sólo casaba cuando el proyecto ERA
    un kit. Para cualquier consumidor —o sea, para el caso normal— la lista
    salía **vacía**: se veían sus skills y cero kits, aunque la base tuviera sus
    tres kits declarados y dieciséis archivos propagados. No faltaba el dato:
    estaba mal escrita la pregunta, y por eso el hueco no se veía como un error
    sino como un proyecto que no usa kits.

    Y un consumidor se lleva su tarjeta con **sólo su fila**, no con la de todos
    los consumidores del kit: al filtrar por un proyecto la pregunta es «qué usa
    éste», no «quién más usa esto». El kit mirándose a sí mismo sí los conserva a
    todos, porque ahí la pregunta es justo la otra.
    """
    salida = []
    for k in kits_:
        if k["id"] == proyecto_id:
            salida.append(k)
            continue
        suyos = [c for c in k["consumidores"] if c["id"] == proyecto_id]
        if suyos:
            salida.append({**k, "consumidores": suyos})
    return salida


def catalogo_kits() -> list[dict]:
    """Qué kits se pueden aplicar, con lo que aporta cada uno.

    El asistente lo necesita para entender «aplícale lienzos y telegram»: sin
    esto no sabía que eran kits (21-oct).
    """
    from . import kits as _kits
    try:
        proyectos = registry.cargar()
    except Exception:  # noqa: BLE001 — sin registro, ningún kit está en desarrollo
        proyectos = []
    # Lo que tiene esta máquina de cada uno va junto: es lo que pinta el
    # catálogo de Inventario → Kits, con sus botones de instalar y aplicar.
    return [
        {"id": k, "nombre": v.get("nombre", k), "version": str(v.get("version", "")),
         "descripcion": v.get("descripcion", ""), "obligatorio": bool(v.get("obligatorio")),
         **_kits.estado_en_catalogo(k, v, proyectos)}
        for k, v in sorted(_kits.catalogo().items())
    ]


@tiempos.medido
def kits(con: sqlite3.Connection) -> list[dict]:
    """Kits con sus consumidores y el estado real de cada archivo propagado."""
    from . import kits as _kits

    salida = []
    # Todos los kits, no sólo los que ya declararon consumidores: un kit sin
    # `consumidores/` es información — dice que nadie ha declarado quién lo usa.
    for fila in con.execute(
        "SELECT id FROM proyecto WHERE tipo = 'kit' ORDER BY nombre COLLATE NOCASE"
    ):
        kit_id = fila["id"]
        proyecto = obtener_proyecto(con, kit_id)
        consumidores = []
        for c in con.execute(
            "SELECT DISTINCT consumidor_id FROM dependencia WHERE kit_id=? ORDER BY consumidor_id",
            (kit_id,),
        ):
            cid = c["consumidor_id"]
            enlaces = [
                _fila_a_dict(f)
                for f in con.execute(
                    """SELECT * FROM dependencia WHERE kit_id=? AND consumidor_id=?
                       ORDER BY estado, destino""",
                    (kit_id, cid),
                )
            ]
            divergencias = [
                _fila_a_dict(f)
                for f in con.execute(
                    "SELECT * FROM divergencia WHERE kit_id=? AND consumidor_id=? ORDER BY archivo",
                    (kit_id, cid),
                )
            ]
            cuenta: dict[str, int] = {}
            for e in enlaces:
                cuenta[e["estado"]] = cuenta.get(e["estado"], 0) + 1
            destino = obtener_proyecto(con, cid)
            consumidores.append(
                {
                    "id": cid,
                    "nombre": (destino or {}).get("nombre", cid),
                    "enlaces": enlaces,
                    "divergencias": divergencias,
                    "cuenta": cuenta,
                    # Deriva = lo que difiere sin estar declarado como decisión.
                    "deriva": cuenta.get("difiere", 0) + cuenta.get("falta", 0),
                    "prompt_mantenedor": _kits.prompt_mantenedor(
                        (proyecto or {}).get("nombre", kit_id),
                        (destino or {}).get("nombre", cid),
                        cuenta.get("difiere", 0) + cuenta.get("falta", 0),
                        len(divergencias),
                        # Lo que el kit avisa a quien lo mantiene. Estaba
                        # declarado en su `kit.yml` y no llegaba a ninguna
                        # salida.
                        _mantenimiento_de(proyecto),
                    ),
                }
            )
        salida.append(
            {
                "id": kit_id,
                "nombre": (proyecto or {}).get("nombre", kit_id),
                "status": (proyecto or {}).get("status", "activo"),
                "consumidores": consumidores,
                "deriva_total": sum(c["deriva"] for c in consumidores),
                "capacidades": con.execute(
                    "SELECT COUNT(*) c FROM capacidad WHERE proyecto_id = ?", (kit_id,)
                ).fetchone()["c"],
                **_manifiesto_de(proyecto),
            }
        )
    return salida


def _mantenimiento_de(proyecto: dict | None) -> dict:
    """El bloque `mantenimiento:` del kit, si lo declara."""
    raiz = (proyecto or {}).get("asiento")
    if not raiz or not (Path(raiz) / "kit.yml").is_file():
        return {}
    from . import kits as _kits

    try:
        return _kits.leer_manifiesto(Path(raiz)).mantenimiento or {}
    except _kits.KitInvalido:
        return {}


def _manifiesto_de(proyecto: dict | None) -> dict:
    """Lo que un kit declara de sí mismo, si trae `kit.yml`.

    Los kits sin manifiesto siguen apareciendo igual: se soportan los dos
    formatos mientras haya kits sin migrar (`catalogo.dependencias_de_kit`).
    """
    vacio = {"version": None, "expone": [], "consume": [], "sin_proveedor": []}
    raiz = (proyecto or {}).get("asiento")
    if not raiz or not (Path(raiz) / "kit.yml").is_file():
        return vacio
    from . import kits as _kits

    try:
        kit = _kits.leer_manifiesto(Path(raiz))
    except _kits.KitInvalido:
        return vacio

    # Lo que este kit pide y nadie instalado provee. Se dice en voz alta: una
    # capacidad ausente y callada es un instrumento en verde que nadie ha visto
    # funcionar.
    disponibles = set()
    for otro_id, versiones in _kits.instalados().items():
        try:
            otro = _kits.leer_manifiesto(_kits.ruta_de(otro_id, versiones[-1]))
        except _kits.KitInvalido:
            continue
        disponibles.update(otro.capacidades_expuestas)
    disponibles.update(kit.capacidades_expuestas)

    return {
        "version": kit.version,
        "expone": kit.capacidades_expuestas,
        "consume": [c["id"] for c in kit.consume],
        "sin_proveedor": [
            {"id": c["id"], "opcional": bool(c.get("opcional"))}
            for c in kit.consume
            if c["id"] not in disponibles
        ],
    }


# ───────────────────────── respaldo de repos ─────────────────────────


@tiempos.medido
def repos_de(con: sqlite3.Connection, proyecto_id: str | None = None) -> list[dict]:
    sql = """SELECT r.*, p.nombre AS proyecto_nombre
             FROM repo r LEFT JOIN proyecto p ON p.id = r.proyecto_id"""
    args: tuple = ()
    if proyecto_id:
        sql += " WHERE r.proyecto_id = ?"
        args = (proyecto_id,)
    # Lo que más commits tiene sin respaldo, arriba: es lo que se puede perder.
    sql += " ORDER BY (r.sin_push IS NULL), r.sin_push DESC, r.ruta"
    return [_fila_a_dict(f) for f in con.execute(sql, args)]


def _copia_memoria() -> dict | None:
    from .secretario import memoria
    if not memoria.existe():
        return None
    return copia_base.estado(prefijo=copia_base.PREFIJO_SECRETARIO)


def respaldo(con: sqlite3.Connection, proyecto_id: str | None = None) -> dict:
    """Cuánto trabajo hay hoy sin respaldar.

    Es la cifra que el hub existe para que nunca vuelva a ser una sorpresa: el
    2026-08-27 eran 473 commits repartidos en dos worktrees que se habían dado
    por muertos.

    Con `proyecto_id`, TODO se recalcula sobre ese proyecto —también las cifras
    de cabecera—. Filtrar la lista y dejar los totales globales daría una
    pantalla que se contradice consigo misma: «9 commits sin respaldo» encima de
    una lista donde no hay ninguno.
    """
    repos = repos_de(con, proyecto_id)
    # Se listan todos los worktrees, pero la CIFRA se calcula sobre repos
    # únicos: `~/dev/app` y `~/dev/app-int` son el mismo trabajo.
    unicos = _repos.deduplicar(repos)
    # Marcar los espejos deja la lista honesta: se ven los cuatro worktrees,
    # pero se entiende por qué la suma no son cuatro números.
    rutas_unicas = {r["ruta"] for r in unicos}
    # La vuelta más reciente que midió algo. Cada escaneo sella TODAS sus filas
    # con la misma hora, así que una fila con otra es de una vuelta anterior
    # —no dio tiempo, git falló en ese repo, la ruta dejó de ser un repo— y su
    # cifra es de entonces. Enseñar sólo la hora más nueva daba por medido
    # ahora lo que no (C-0295, reglas 13 y 19). Global y no del filtro: con un
    # proyecto elegido, «la última vuelta» sigue siendo la misma.
    ultima_vuelta = con.execute("SELECT MAX(medido_en) FROM repo").fetchone()[0]
    for r in repos:
        r["cuenta_en_total"] = r["ruta"] in rutas_unicas
        r["de_otra_vuelta"] = r["medido_en"] != ultima_vuelta
    mas_viejo = min((r["medido_en"] for r in repos), default=None)
    en_riesgo = [r for r in repos if (r["sin_push"] or 0) > 0]
    return {
        "repos": repos,
        "en_riesgo": en_riesgo,
        "commits_sin_respaldo": sum(
            r["sin_push"] or 0 for r in unicos if (r["sin_push"] or 0) > 0
        ),
        # Sobre repos únicos, igual que la cifra de commits. Contar las filas de
        # `en_riesgo` daba «538 commits en 5 repos» cuando son 3: las dos mitades
        # de la misma frase se medían con denominadores distintos.
        "repos_en_riesgo": sum(1 for r in unicos if (r["sin_push"] or 0) > 0),
        "sucios": sum(1 for r in repos if r["sucios"]),
        "sin_remoto": sum(1 for r in repos if r["regimen"] == "sin-remoto"),
        "worktrees": sum(r["worktrees"] for r in repos),
        "medido_en": max((r["medido_en"] for r in repos), default=None),
        "ultima_vuelta": ultima_vuelta,
        # Cuántos de los de esta vista no se midieron en esa vuelta, y de
        # cuándo es el más viejo: «incompleta: 95 de 138; el más viejo, del…».
        "de_otra_vuelta": sum(1 for r in repos if r["de_otra_vuelta"]),
        "mas_viejo": mas_viejo,
        # Sin git no hay medición posible, y un «0 commits sin respaldo» que en
        # realidad significa «no he mirado» es la peor cifra que este hub puede
        # enseñar. La pantalla lo dice en vez de dar el cero por bueno.
        "hay_git": _repos.hay_git(),
        # La otra mitad del respaldo: los datos del propio hub, que no están en
        # ningún repo (decisión 277).
        "copia_base": copia_base.estado(),
        # Y la memoria del secretario, que tampoco se reconstruye (decisión
        # 299) y cuya copia no vigilaba nadie (C-0282). Sin secretario, nada.
        "copia_memoria": _copia_memoria(),
        # Para el selector: los proyectos que TIENEN repos, no todos. Ofrecer
        # veinte opciones de las que quince dan una lista vacía no es un filtro,
        # es una trampa.
        "proyectos": [
            p for p in listar_proyectos(con)
            if p["id"] in {r["proyecto_id"] for r in repos_de(con)}
        ],
    }


# ───────────────────────────── consumo de tokens ──────────────────────────────


# Los cuatro recuentos, en el orden en que se enseñan y con lo que significan.
# El rótulo importa tanto como la cifra: «tokens» a secas junta cosas que no
# cuestan lo mismo ni quieren decir lo mismo.
TIPOS_DE_TOKEN = (
    ("salida", "salida", "Lo que Claude escribió: respuestas, código y llamadas a herramientas."),
    ("escritura", "caché escrita", "Contexto nuevo que hubo que guardar. Sube al abrir archivos grandes."),
    ("lectura", "caché leída", "Contexto releído en cada turno. Es casi todo el volumen, y el más barato."),
    ("entrada", "entrada", "Lo que se manda sin cachear. Aquí es residual."),
)


# Cómo se agrupa el consumo además de por proyecto. La clave es el campo del
# proyecto; el rótulo es lo que se lee en la pantalla.
#
# 🔴 Son categorías del HUB, no del registro de Claude Code: salen de
# `projects.yml`, así que cambiar el dominio de un proyecto reordena la vista sin
# volver a medir nada. El modelo es la excepción y viene del registro, porque un
# token de Opus y uno de Haiku no son la misma cosa y eso no lo sabe el hub.
CATEGORIAS = (
    ("dominio", "Dominio", "En qué se está yendo: lo laboral o lo personal."),
    ("tipo", "Tipo", "Proyectos, kits y el asistente."),
    ("status", "Estado", "🔴 Lo pausado y lo archivado que sigue consumiendo."),
    ("modelo", "Modelo", "Del registro, no del hub: no todos pesan igual."),
)

# La gráfica, en coordenadas de su `viewBox`. Se calcula en Python y no en la
# plantilla ni en JavaScript: es aritmética, se puede probar, y así la pantalla
# no depende de que un script arranque (regla dura 11 esquivada por no tener
# script que probar).
_ANCHO, _ALTO, _HUECO = 620.0, 150.0, 2.0

# Cuántas series se dibujan con tono propio. Más de seis y la rampa deja de
# distinguirse; lo que sobra se junta en «otros», que no tiene rango.
SERIES_CON_TONO = 6


def consumo(con: sqlite3.Connection, proyecto_id: str | None = None) -> dict:
    """Cuánto se ha gastado, por proyecto y por categoría.

    🔴 Devuelve la **ventana** además de las cifras, y no es decoración: los
    transcripts se podan a los 30 días, así que esto es «lo último que queda en
    el registro» y jamás un histórico. Una pantalla que enseñe el número sin las
    fechas está invitando a leerlo como total (regla dura 13).

    Con `proyecto_id` se recorta todo a ese proyecto **menos `parte`**, que sigue
    siendo su tajada del total global: en la ficha de un proyecto la pregunta es
    «cuánto de lo mío es esto», y un 100 % no contesta nada.

    `razonado` va aparte de la suma a propósito: está DENTRO de `salida`, así que
    sumarlo lo contaría dos veces.
    """
    todas = [_fila_a_dict(f) for f in con.execute("SELECT * FROM consumo")]
    filas = [f for f in todas if f["proyecto_id"] == proyecto_id] if proyecto_id else todas

    proyectos = {p["id"]: p for p in listar_proyectos(con)}
    campos = [c for c, _, _ in TIPOS_DE_TOKEN]

    def vacio(clave, etiqueta):
        return {"proyecto_id": clave, "nombre": etiqueta, "peticiones": 0,
                "razonado": 0, "razonadas": 0, "modelos": {}, "rutas": {},
                **{c: 0 for c in campos}}

    por_proyecto: dict = {}
    por_dia: dict = {}
    por_categoria: dict = {c: {} for c, _, _ in CATEGORIAS}
    dia_proyecto: dict = {}
    for f in filas:
        clave = f["proyecto_id"]
        # Sin proyecto NO se descarta ni se reparte: se enseña aparte. Es lo que
        # dice «esta carpeta no está dada de alta en el hub», que es información
        # y no un hueco — 5 261 peticiones vivían en rutas sin registrar.
        #
        # 🔴 Tres casos, no dos. Un `proyecto_id` que ya no está declarado no es
        # «sin proyecto»: se sabe de quién era, y decirlo es la diferencia entre
        # «no la has dado de alta» y «esto lo gastó algo que borraste».
        if not clave:
            etiqueta = "Sin proyecto"
        elif clave in proyectos:
            etiqueta = proyectos[clave]["nombre"]
        else:
            etiqueta = f"{clave} — ya no está en projects.yml"
        entrada = por_proyecto.setdefault(clave, vacio(clave, etiqueta))
        entrada["peticiones"] += f["peticiones"]
        entrada["razonado"] += f["razonado"]
        entrada["razonadas"] += f["razonadas"]
        for c in campos:
            entrada[c] += f[c]
        entrada["modelos"][f["modelo"]] = entrada["modelos"].get(f["modelo"], 0) + f["peticiones"]
        suma = sum(f[c] for c in campos)
        entrada["rutas"][f["ruta"]] = entrada["rutas"].get(f["ruta"], 0) + suma
        por_dia[f["dia"]] = por_dia.get(f["dia"], 0) + suma
        dia_proyecto[(f["dia"], clave)] = dia_proyecto.get((f["dia"], clave), 0) + suma

        # Las categorías, sobre el mismo recorrido.
        ficha = proyectos.get(clave)
        for campo, _, _ in CATEGORIAS:
            if campo == "modelo":
                valor = f["modelo"]
            elif ficha:
                valor = ficha.get(campo) or "—"
            else:
                # Un proyecto sin ficha no tiene dominio ni tipo ni estado, y
                # meterlo en «personal» por omisión falsearía justo la cifra que
                # se está mirando: sale con nombre propio.
                valor = "sin proyecto"
            por_categoria[campo][valor] = por_categoria[campo].get(valor, 0) + suma

    for e in por_proyecto.values():
        e["total"] = sum(e[c] for c in campos)
        e["modelos"] = sorted(e["modelos"].items(), key=lambda kv: -kv[1])
        e["rutas"] = sorted(e["rutas"].items(), key=lambda kv: -kv[1])

    lista = sorted(por_proyecto.values(), key=lambda e: -e["total"])
    total = sum(e["total"] for e in lista)
    # Sobre el total GLOBAL, no sobre el filtrado: es lo que deja decir «este
    # proyecto es el 1,3 % de todo» en su propia ficha.
    global_ = sum(sum(f[c] for c in campos) for f in todas)
    for e in lista:
        e["parte"] = (100 * e["total"] / global_) if global_ else 0

    dias = sorted(por_dia.items())
    return {
        "proyectos": lista,
        "totales": {c: sum(e[c] for e in lista) for c in campos}
                   | {"total": total, "total_global": global_,
                      "parte": (100 * total / global_) if global_ else 0,
                      "peticiones": sum(e["peticiones"] for e in lista),
                      "razonado": sum(e["razonado"] for e in lista),
                      "razonadas": sum(e["razonadas"] for e in lista)},
        "tipos": TIPOS_DE_TOKEN,
        "categorias": _categorias(por_categoria, total),
        "grafica": _grafica(dias, dia_proyecto, lista),
        "por_dia": [{"dia": d, "total": v} for d, v in dias],
        "modelos": sorted(por_categoria["modelo"].items(), key=lambda kv: -kv[1]),
        # La ventana sale del propio registro, no de un ajuste: si Claude Code
        # cambia su poda, esto lo dice solo.
        "desde": min((f["desde"] for f in filas if f["desde"]), default=None),
        "hasta": max((f["hasta"] for f in filas if f["hasta"]), default=None),
        # El primer y el último día de las columnas, para el rótulo «Del… al…»:
        # las columnas son días UTC (`consumo` agrupa por `marca[:10]`), y con
        # `desde`/`hasta` en hora de la casa el rótulo y la gráfica discrepaban
        # un día en los bordes (regla 19, tras la revisión de C-0396).
        "primer_dia": dias[0][0] if dias else None,
        "ultimo_dia": dias[-1][0] if dias else None,
        "medido_en": max((f["medido_en"] for f in todas), default=None),
        "hay_registro": bool(todas),
        "hay_datos": bool(filas),
        "carpeta": str(transcripts.raiz()),
        # El selector se arma sobre TODAS las filas, no sobre las filtradas: con
        # las filtradas, elegir un proyecto dejaba un desplegable de una sola
        # opción y sin forma de volver a otro.
        "proyectos_del_filtro": [
            p for p in listar_proyectos(con)
            if p["id"] in {f["proyecto_id"] for f in todas}
        ],
    }


def _categorias(por_categoria: dict, total: int) -> list[dict]:
    """Cada agrupación con sus tajadas, ya ordenadas y con su parte."""
    fuera = []
    for campo, etiqueta, que_es in CATEGORIAS:
        valores = sorted(por_categoria[campo].items(), key=lambda kv: -kv[1])
        fuera.append({
            "campo": campo, "etiqueta": etiqueta, "que_es": que_es,
            "tajadas": [
                {"valor": v, "total": n, "parte": (100 * n / total) if total else 0,
                 # El tono va por RANGO, no por identidad: la mayor se lleva el
                 # más saturado. Ver el porqué en los tokens `--serie-*`.
                 "tono": min(i + 1, SERIES_CON_TONO)}
                for i, (v, n) in enumerate(valores)
            ],
        })
    return fuera


def _grafica(dias: list, dia_proyecto: dict, lista: list[dict]) -> dict:
    """Barras apiladas por día, en coordenadas del `viewBox`.

    Se calcula aquí y no en la plantilla porque es aritmética con casos de
    borde —un día sin datos, un solo día, el tope a cero— y en Jinja eso no se
    puede probar. Tampoco en JavaScript: una gráfica que sólo existe si arranca
    un script es una pantalla que se puede quedar en blanco sin decirlo.
    """
    if not dias:
        return {"columnas": [], "series": [], "ancho": _ANCHO, "alto": _ALTO,
                "tope": 0, "dias": 0}

    # Las seis mayores llevan tono propio; el resto se junta en «otros», que no
    # tiene rango porque no es una serie: es un resto.
    con_tono = {e["proyecto_id"]: i + 1
                for i, e in enumerate(lista[:SERIES_CON_TONO])}
    series = [{"nombre": e["nombre"], "tono": i + 1, "total": e["total"]}
              for i, e in enumerate(lista[:SERIES_CON_TONO])]
    resto = sum(e["total"] for e in lista[SERIES_CON_TONO:])
    if resto:
        series.append({"nombre": f"otros ({len(lista) - SERIES_CON_TONO})",
                       "tono": 0, "total": resto})

    tope = max(v for _, v in dias)
    ancho_col = _ANCHO / len(dias)
    columnas = []
    for i, (dia, total_dia) in enumerate(dias):
        x = i * ancho_col
        alto_total = (_ALTO * total_dia / tope) if tope else 0
        trozos, y = [], _ALTO - alto_total
        # 🔴 El orden es de arriba abajo, porque se dibuja desde el techo de la
        # columna. La serie mayor —tono 1— va la ÚLTIMA para quedar apoyada en
        # la base: sobre una línea recta su altura se compara entre días de un
        # vistazo, y flotando sobre las pequeñas no. «Otros» va arriba del todo,
        # que es donde estorba menos porque no es una serie sino un resto.
        reparto = sorted(
            ((con_tono.get(pid, 0), n) for (d, pid), n in dia_proyecto.items() if d == dia),
            key=lambda par: (par[0] != 0, -par[0]),
        )
        for tono, n in reparto:
            alto = (_ALTO * n / tope) if tope else 0
            trozos.append({"tono": tono, "y": round(y, 2), "alto": round(alto, 2)})
            y += alto
        columnas.append({
            "dia": dia, "total": total_dia,
            "x": round(x, 2), "ancho": round(max(ancho_col - _HUECO, 0.5), 2),
            "trozos": trozos,
        })
    return {"columnas": columnas, "series": series, "ancho": _ANCHO,
            "alto": _ALTO, "tope": tope, "dias": len(dias)}


# ───────────────────────── servicios y conexiones ─────────────────────────


# Cuánto vale la tabla de contenedores como «lo que hay ahora». El ciclo lento
# la relee cada 10 minutos; tres vueltas sin lectura nueva es que Docker no
# contesta o el muestreo no corre, y lo guardado pasa a ser lo que se vio
# entonces, no lo que hay (C-0293, regla dura 13).
SERVICIOS_VIGENTES_SEGUNDOS = 30 * 60


def _vigencia_servicios(medido_en: str | None) -> tuple[bool, str]:
    """Si la última lectura de Docker se puede dar por la de ahora, y si no, por qué.

    🔴 Existe porque sin Docker la tabla se conserva —un cero diría «no tienes
    contenedores» cuando no se pudo preguntar— y la pantalla la enseñaba como
    viva: «corriendo» y los botones de parar sobre una lectura de nueve días.
    La regla 12 va de no parar el contenedor equivocado; ofrecerlo sobre algo
    que puede no ser ya así es el mismo accidente por otro camino.
    """
    if not _servicios.disponible():
        return False, "Docker no está instalado en este entorno"
    if medido_en and _segundos_desde(medido_en) > SERVICIOS_VIGENTES_SEGUNDOS:
        return False, f"Docker no ha contestado desde el {_hora_local(medido_en)}"
    return True, ""


def servicios(con: sqlite3.Connection, proyecto_id: str | None = None) -> dict:
    sql = """SELECT s.*, p.nombre AS proyecto_nombre
             FROM servicio s LEFT JOIN proyecto p ON p.id = s.proyecto_id"""
    args: tuple = ()
    if proyecto_id:
        sql += " WHERE s.proyecto_id = ?"
        args = (proyecto_id,)
    # Vivos primero, y dentro de cada grupo por proyecto: así se ve de un
    # vistazo de quién es lo que está corriendo antes de parar nada.
    sql += " ORDER BY (s.estado != 'running'), p.nombre COLLATE NOCASE, s.contenedor"
    filas = [_fila_a_dict(f) for f in con.execute(sql, args)]
    medido_en = max((f["medido_en"] for f in filas), default=None)
    vigente, motivo = _vigencia_servicios(medido_en)
    return {
        "contenedores": filas,
        "total": len(filas),
        # Los que corrían EN LA LECTURA: con `vigente` falso es lo que se vio
        # el `visto`, y así lo tiene que decir quien lo pinte.
        "vivos": sum(1 for f in filas if f["estado"] == "running"),
        # Un contenedor sin dueño es la clase de cosa que lleva meses parada y
        # nadie sabe si se puede borrar. En el inventario que originó esto había
        # uno detenido desde hacía cuatro meses y sin dueño conocido.
        "sin_atribuir": [f for f in filas if not f["proyecto_id"]],
        "medido_en": medido_en,
        "visto": _hora_local(medido_en),
        "hay_docker": _servicios.disponible(),
        "vigente": vigente,
        "motivo": motivo,
        # Igual que en respaldo: sólo los proyectos que tienen contenedores.
        "proyectos": [
            p for p in listar_proyectos(con)
            if p["id"] in {
                r["proyecto_id"] for r in con.execute("SELECT proyecto_id FROM servicio")
            }
        ],
    }


@tiempos.medido
def tablero(con: sqlite3.Connection, recientes: int = 15) -> dict:
    """La bandeja de ideas (decisión 342): las nuevas, en el orden en que se
    tomarán, y lo último tomado o descartado con dónde sigue."""
    from . import ideas
    hechas = sorted(ideas.listar(con, "tomada", limite=recientes) + ideas.listar(con, "descartada", limite=recientes),
                    key=lambda i: i["movida"] or "", reverse=True)[:recientes]
    nuevas = ideas.listar(con, "nueva")
    from . import orquestador
    for i in nuevas + hechas:
        i["adjuntos"] = ideas.adjuntos(i["id"])
    # Encargada al orquestador y aún sin tomar: la ficha la crea la sesión
    # del Tablero, y hasta entonces se ve con qué tarea va (C-0151).
    por_idea = orquestador.tareas_por_idea()
    donde: dict[str, Any] = {}
    for i in nuevas:
        tarea = por_idea.get(i["id"])
        i["tarea"] = {"id": tarea["id"], "estado": tarea["estado"]} if tarea else None
        # Dónde se trabajaría, para que el botón diga lo que va a pasar: un
        # proyecto con git y sin copia pide crearla (D1 de C-0151).
        p = i["proyecto"] or "hub"
        if p not in donde:
            try:
                donde[p] = orquestador.donde_trabajar(con, p)
            except orquestador.FaltaCopia as exc:
                donde[p] = {"falta_copia": exc.copia.name}
            except ValueError as exc:
                donde[p] = {"error": str(exc)}
        i["donde"] = donde[p]
    return {"nuevas": nuevas, "recientes": hechas, "max_adjuntos": ideas.MAX_ADJUNTOS,
            "proyectos": sorted(p.id for p in registry.cargar())}


def llaves() -> dict:
    """Las llaves de esta máquina: dónde viven y si están marcadas en
    Bitwarden. Nunca el valor: `llavero.inventario` sólo hace `stat` (C-0143)."""
    from . import llavero

    filas = llavero.inventario()
    casa = str(Path.home())
    for f in filas:
        f["donde"] = f["puntero"].replace(casa, "~", 1)
        f["presente"] = f["estado"] not in ("no existe", "sin configurar")
    presentes = [f for f in filas if f["presente"] and not f["sesion"]]
    return {"filas": filas, "sin_subir": sum(1 for f in presentes if not f["bitwarden"]),
            "presentes": len(presentes)}


@tiempos.medido
def conexiones(con: sqlite3.Connection) -> list[dict]:
    salida = []
    for f in con.execute("SELECT * FROM conexion ORDER BY alias"):
        datos = _fila_a_dict(f)
        datos["proyectos"] = [
            r["proyecto_id"]
            for r in con.execute(
                "SELECT proyecto_id FROM conexion_proyecto WHERE alias=? ORDER BY proyecto_id",
                (f["alias"],),
            )
        ]
        salida.append(datos)
    return salida


def conexiones_concedidas(con: sqlite3.Connection, ruta: str) -> dict:
    """Las conexiones concedidas al proyecto que contiene `ruta`.

    La concesión es la lista `proyectos:` de la conexión en `projects.yml`
    (decisión 197). Quitar un proyecto de ahí retira el puntero sin tocar el
    servidor; añadirlo tampoco da acceso —el acceso lo da la llave—, así que
    esto reparte DIRECCIONES de dónde vive una credencial, nunca la credencial.

    🔴 El proyecto se deduce de dónde se pregunta y no se acepta por nombre. Si
    se aceptara, la lista dejaría de conceder nada: sería una etiqueta, y
    cualquier sesión podría pedir la conexión de otro proyecto sabiendo su id.

    Lo que esto NO es: una frontera contra un proceso hostil de la máquina. La
    ruta la manda quien llama y podría mentir. Contra eso no defiende nada que
    escuche en `127.0.0.1` —el endpoint de terminal da una shell entera (regla
    dura 8)—; lo que evita es el error honesto de una sesión que pide el
    servidor equivocado porque conoce su nombre.
    """
    proyecto_id = registry.atribuidor(con).atribuir(ruta) if ruta else None
    if not proyecto_id:
        return {"proyecto_id": None, "conexiones": []}
    return {
        "proyecto_id": proyecto_id,
        "conexiones": [c for c in conexiones(con) if proyecto_id in c["proyectos"]],
    }


def plan_de_restauracion(con: sqlite3.Connection, muestra_id: int | None = None) -> dict:
    """Qué haría el botón de restaurar, ANTES de pulsarlo.

    🔴 Se enseña el plan en vez de ejecutarlo a ciegas porque la elección de
    muestra no se puede automatizar: el 16-sep quedaron dos marcadas «antes de un
    corte» con los mismos slots y el mismo número de paneles, y sólo una era el
    escritorio de trabajo. Enseñarlas convierte una elección equivocada en algo
    que se ve, en vez de en trece ventanas abiertas donde no tocaba.
    """
    if not con.execute(
        "SELECT 1 FROM slot WHERE status='activo' AND restaurar=1 LIMIT 1"
    ).fetchone():
        return {"candidatos": [], "muestra": None, "ventanas": []}
    candidatos = _restauracion.candidatos_de_restauracion(con)
    elegida = muestra_id or (candidatos[0]["id"] if candidatos else None)
    muestra = next((c for c in candidatos if c["id"] == elegida), None)
    return {
        "candidatos": candidatos,
        "muestra": muestra,
        "ventanas": _restauracion.plan_de_restauracion(con, muestra_id=elegida),
        # Con una muestra de hace días el plan se enseña plegado (C-0296).
        "reciente": not muestra or _segundos_desde(muestra["tomado_en"]) < CORTE_RECIENTE_SEGUNDOS,
    }


# ───────────────────────── navegador de archivos ─────────────────────────


@tiempos.medido
def confin(con: sqlite3.Connection) -> list[Path]:
    """Las raíces que el navegador puede servir: exactamente las que el hub indexa.

    Sale de `proyecto_ruta` y no de `projects.yml` a pelo porque es la misma
    tabla de la que come `registry.atribuidor`. Dos listas de raíces distintas darían un
    navegador que enseña una carpeta y un hub que dice que no es de nadie, y la
    discrepancia sólo se vería el día que importe.
    """
    return navegador.raices(
        f["ruta"] for f in con.execute("SELECT ruta FROM proyecto_ruta")
    )


@tiempos.medido
def _repos_medidos(con: sqlite3.Connection) -> dict[str, dict]:
    """Lo que ya se sabe de cada repo, por ruta resuelta.

    El navegador no ejecuta `git`: sería lento sobre `/mnt/c` y además caro en el
    sitio equivocado (regla 14). Lo que enseña es lo que el escaneo ya midió, así
    que puede estar viejo — y por eso la pantalla dice cuándo se midió en vez de
    dar la rama como si fuera de ahora mismo.

    La ruta de cada repo es declarada: se resuelve recordada un minuto
    (`navegador.declarada`, C-0310), como las raíces.
    """
    medidos = {}
    for f in con.execute(
        "SELECT ruta, rama, sucios, sin_push, medido_en FROM repo"
    ):
        medidos[str(navegador.declarada(f["ruta"]))] = {
            "rama": f["rama"] or "",
            "sucios": f["sucios"],
            "sin_push": f["sin_push"],
            "medido_en": f["medido_en"],
        }
    return medidos


@tiempos.medido
def explorar(con: sqlite3.Connection, ruta: str = "") -> dict:
    """Qué hay en esa carpeta, o los sitios por los que empezar si no se da ninguna.

    Las dos respuestas tienen la MISMA forma —`entradas` con su nombre y su
    ruta—, para que la pantalla tenga un solo pintor. Un caso especial para la
    portada es una segunda plantilla que se olvida de arreglar.

    🔴 Ni contenido ni acciones: ver `navegador.py`. Esta función es la costura
    de lectura (`CLAUDE.md`, primera regla) y no hay otra.
    """
    permitidas = confin(con)
    por_ruta = registry.atribuidor(con)
    medidos = _repos_medidos(con)
    nombres = {
        f["id"]: f["nombre"] for f in con.execute("SELECT id, nombre FROM proyecto")
    }

    def _adornar(entrada: dict) -> dict:
        proyecto_id = por_ruta.atribuir(entrada["ruta"])
        entrada["proyecto_id"] = proyecto_id
        entrada["proyecto"] = nombres.get(proyecto_id or "", "")
        entrada.update(medidos.get(entrada["ruta"], {}))
        return entrada

    if not ruta:
        raices = sorted(navegador.minimas(permitidas), key=lambda r: str(r).lower())
        return {
            "ruta": "",
            "migas": [],
            "arriba": None,
            "entradas": [
                _adornar({
                    "nombre": r.name or str(r),
                    "ruta": str(r),
                    "carpeta": True,
                    "repo": (r / ".git").exists(),
                    "tamano": None,
                    "fuera": False,
                })
                for r in raices
            ],
            "ocultos": 0,
            "truncado": 0,
            "proyecto_id": None,
        }

    datos = navegador.listar(ruta, permitidas)
    datos["entradas"] = [_adornar(e) for e in datos["entradas"]]
    datos["proyecto_id"] = por_ruta.atribuir(datos["ruta"])
    datos["proyecto"] = nombres.get(datos["proyecto_id"] or "", "")
    datos["ruta_corta"] = ruta_corta(datos["ruta"])
    return datos


# ───────────────────────── mensajes programados ─────────────────────────


def programados(con: sqlite3.Connection, slot_id: int | None = None) -> list[dict]:
    """Los mensajes programados, con el nombre de su slot.

    🔴 La consulta vive aquí y no en `programados.py` para no invertir la
    dirección de las dependencias: los módulos de acción —`slots`, `canal`,
    `programados`— importan `api`, y `api` no importa a ninguno. Delegar habría
    cerrado un ciclo de imports que hoy funciona por el orden en que se cargan
    los módulos, que es la clase de cosa que se rompe seis meses después.

    El nombre del slot se añade porque la lista se enseña también fuera del
    slot, y un `slot_id` a secas no le dice nada a nadie.
    """
    sql = """SELECT m.*, s.nombre AS slot_nombre
             FROM mensaje_programado m LEFT JOIN slot s ON s.id = m.slot_id"""
    args: tuple = ()
    if slot_id is not None:
        sql += " WHERE m.slot_id = ?"
        args = (slot_id,)
    # Los pendientes arriba: son los únicos sobre los que se puede hacer algo.
    # Los cerrados siguen saliendo —saber que uno CADUCÓ sin entregarse es justo
    # lo que hay que ver—, y esconderlos dejaría la pantalla idéntica tanto si
    # salió como si no.
    sql += " ORDER BY (m.estado != 'pendiente'), m.cuando DESC"
    return [_fila_a_dict(f) for f in con.execute(sql, args)]


# ───────────────────────── estado y capa base ─────────────────────────


def estado_de(con: sqlite3.Connection, proyecto_id: str) -> dict:
    """El documento vigente de un proyecto, resuelto y resumido, y cada campo
    también entero: de un solo proyecto, la ficha lo despliega (C-0353)."""
    datos = obtener_proyecto(con, proyecto_id)
    return base.estado_de(_a_modelo(datos), enteros=True) if datos else {}


def capa_base(con: sqlite3.Connection, proyecto_id: str) -> dict:
    datos = obtener_proyecto(con, proyecto_id)
    if not datos:
        return {}
    proyecto = _a_modelo(datos)
    capa = base.capa_de(proyecto)
    capa["prompt_sembrar"] = base.prompt_sembrar(proyecto)
    return capa


# ───────────────────────── contexto completo ─────────────────────────


@tiempos.medido
def contexto(con: sqlite3.Connection) -> dict:
    """Todo el estado del hub en una sola llamada.

    Es la costura del asistente: **lee** esto en vez de levantar una
    sesión de Claude Code por proyecto para preguntar cómo va. También es lo que
    consumirá el MCP del VPS (decisión 25).

    A propósito no genera nada con un LLM: reúne lo que ya está medido y lo que
    cada proyecto ya declaró. El digest generado sigue pendiente porque exige
    revisar los cinco documentos con el usuario, uno por uno.
    """
    proyectos = []
    for p in listar_proyectos(con):
        datos = obtener_proyecto(con, p["id"]) or p
        proyectos.append({
            "id": p["id"],
            "nombre": p["nombre"],
            "dominio": p["dominio"],
            "status": p["status"],
            "guardrail": p["guardrail"],
            "nota": p["nota"],
            "asiento": p["asiento"],
            "estado": base.estado_de(_a_modelo(datos)),
            "capa_base": base.capa_de(_a_modelo(datos))["presente"],
            "slots": slots_de(con, p["id"]),
            "repos": repos_de(con, p["id"]),
            "servicios": servicios(con, p["id"])["contenedores"],
        })

    inv = inventario(con)
    return {
        "proyectos": proyectos,
        "respaldo": respaldo(con),
        "servicios": servicios(con),
        "conexiones": conexiones(con),
        "bandeja": bandeja(con),
        "paneles": paneles_abiertos(con),
        "capacidades": {
            "total": inv["total"],
            "sin_uso": inv["sin_uso"],
            "no_medibles": inv["no_medibles"],
            "por_tipo": inv["por_tipo"],
        },
        "kits": [
            {"id": k["id"], "nombre": k["nombre"], "deriva": k["deriva_total"],
             "consumidores": [c["nombre"] for c in k["consumidores"]]}
            for k in kits(con)
        ],
    }


def contexto_markdown(con: sqlite3.Connection) -> str:
    """El mismo contexto, escrito para pegarlo al principio de una sesión.

    Existe porque es lo que el usuario hace de verdad: abrir `claude` y contarle dónde
    está. Que el hub lo escriba por él es el atajo más corto entre lo que ya
    mide y el trabajo real.
    """
    c = contexto(con)
    lineas = ["# Estado del sistema", ""]

    r = c["respaldo"]
    if r["commits_sin_respaldo"]:
        lineas.append(
            f"🔴 **{r['commits_sin_respaldo']} commits sin respaldo** en "
            f"{r['repos_en_riesgo']} repo(s)."
        )
    else:
        lineas.append("Todo lo commiteado está respaldado en algún remoto.")
    # Con una lectura que no es de ahora se dice de cuándo es (C-0293).
    svc = c["servicios"]
    if svc["vigente"]:
        contenedores = f"{svc['vivos']}/{svc['total']} contenedores corriendo"
    elif svc["total"]:
        contenedores = (f"{svc['vivos']}/{svc['total']} contenedores corrían el "
                        f"{svc['visto']} ({svc['motivo']})")
    else:
        contenedores = svc["motivo"]
    lineas += [
        f"{contenedores} · "
        f"{len(c['paneles'])} paneles abiertos · {len(c['bandeja'])} sin clasificar · "
        f"{c['capacidades']['total']} capacidades ({c['capacidades']['sin_uso']} sin uso detectado)",
        "",
    ]

    for p in c["proyectos"]:
        lineas.append(f"## {p['nombre']}  ·  `{p['id']}`")
        cabecera = [p["dominio"], p["status"], f"guardrail `{p['guardrail']}`"]
        if not p["capa_base"]:
            cabecera.append("sin capa base")
        lineas += [" · ".join(cabecera), ""]

        campos = p["estado"]["campos"]
        for clave, titulo in (
            ("estado", "Estado"),
            ("proxima_accion", "Próxima acción"),
            ("bloqueado_por", "Bloqueado por"),
        ):
            if campos.get(clave):
                lineas += [f"**{titulo}:** {campos[clave]}", ""]
        if not campos:
            declarado = p["estado"]["declarado"]
            lineas += [
                f"*Sin bloque de estado legible en `{declarado}`.*" if declarado
                else "*No declara qué documento suyo está vigente.*",
                "",
            ]

        # Sólo lo que exige acción: una lista de todo lo sano es ruido que hace
        # que se deje de leer justo lo que sí importa.
        for repo in _repos.deduplicar(p["repos"]):
            avisos = []
            if repo["sin_push"]:
                avisos.append(f"{repo['sin_push']} commits sin push")
            if repo["sucios"]:
                avisos.append(f"{repo['sucios']} archivos sin commitear")
            if avisos:
                # La rama ya viene entre paréntesis cuando el HEAD está suelto:
                # `((detached))` se lee como un error de plantilla.
                rama = repo["rama"].strip("()")
                lineas.append(f"- `{repo['ruta']}` [{rama}]: {', '.join(avisos)}")

        vivos = [s["contenedor"] for s in p["servicios"] if s["estado"] == "running"]
        if vivos:
            lineas.append(f"- Contenedores arriba: {', '.join(vivos)}")
        if p["slots"]:
            lineas.append(f"- Slots: {', '.join(s['nombre'] for s in p['slots'])}")
        lineas.append("")

    sin_dueno = [s["contenedor"] for s in c["servicios"]["sin_atribuir"]]
    if sin_dueno:
        lineas += ["## Sin atribuir", "", f"Contenedores sin proyecto: {', '.join(sin_dueno)}", ""]

    # Los kits estaban en el JSON y se caían del markdown, que es lo único que
    # ve el asistente. Su guía le decía «qué kits hay: `hub estado`», corría el
    # comando, no encontraba nada, y tenía que inventar o rendirse. El dato ya
    # estaba medido: sólo faltaba enseñarlo.
    if c.get("kits"):
        lineas += ["## Kits", ""]
        for k in c["kits"]:
            consumidores = ", ".join(k.get("consumidores") or []) or "sin consumidores"
            deriva = k.get("deriva") or 0
            estado = f"{deriva} archivo(s) por revisar" if deriva else "al día"
            lineas.append(f"- **{k['nombre']}** (`{k['id']}`) — {estado} · {consumidores}")
        lineas.append("")

    return "\n".join(lineas).strip() + "\n"


@tiempos.medido
def resumen(con: sqlite3.Connection, muestra_id: int | None = None) -> dict:
    """Lo que necesita la pantalla principal, en una sola llamada.

    `muestra_id` sólo lo usa el panel de restaurar, para poder mirar el plan de
    otra muestra sin salir del panorama.
    """
    actual = snapshot_actual(con)
    paneles = paneles_de(con, actual["id"]) if actual else []
    por_proyecto: dict[str, int] = {}
    primera_sesion: dict[str, dict] = {}
    for p in paneles:
        if p["proyecto_id"]:
            por_proyecto[p["proyecto_id"]] = por_proyecto.get(p["proyecto_id"], 0) + 1
            primera_sesion.setdefault(p["proyecto_id"], p)

    repos_por_proyecto: dict[str, list[dict]] = {}
    for r in repos_de(con):
        repos_por_proyecto.setdefault(r["proyecto_id"], []).append(r)

    slots_con_ventana = {p["slot_id"] for p in paneles if p["slot_id"]}
    restauracion = plan_de_restauracion(con, muestra_id)
    les_falta = {v.get("slot_id") for v in restauracion["ventanas"]}

    proyectos = listar_proyectos(con)
    for p in proyectos:
        p["paneles_abiertos"] = por_proyecto.get(p["id"], 0)
        p["slots"] = slots_de(con, p["id"])
        # Para poder saltar del panorama al terminal de un proyecto en un clic.
        entrada = primera_sesion.get(p["id"])
        p["session_abierta"] = entrada["session"] if entrada else None
        p["ventana_abierta"] = entrada["window_idx"] if entrada else None
        p["repos"] = repos_por_proyecto.get(p["id"], [])
        p["sin_push"] = sum(
            r["sin_push"] or 0 for r in _repos.deduplicar(p["repos"])
        )
        # El estado sale del documento que el propio proyecto declaró vigente:
        # el hub no escribe un resumen nuevo, apunta al que ya existe (decisión 5).
        p["estado"] = base.estado_de(_a_modelo(obtener_proyecto(con, p["id"]) or {}))

    return {
        "proyectos": proyectos,
        "snapshot": actual,
        "paneles_totales": len(paneles),
        "sin_atribuir": sum(1 for p in paneles if not p["proyecto_id"]),
        "bandeja": bandeja(con),
        # Lo oculto viaja al lado de la bandeja, no en vez de ella: la portada
        # tiene que poder decir cuántas esconde y dejar destaparlas.
        "ocultas": ocultos(con),
        "recuperacion": recuperacion_pendiente(con),
        "respaldo": respaldo(con),
        "servicios": servicios(con),
        # Los slots marcados a mano para volver tras un apagón Y que hoy no
        # tienen ninguna ventana: los que ya la tienen no se ofrecen, porque
        # tras un reinicio tmux-continuum las devuelve solo y el botón, siempre
        # a la vista, duplicaba ventanas y se aprendía a ignorar (C-0299).
        # Van por aquí y no leyendo SQL desde la plantilla porque la costura de
        # lectura es única (principio 8) y el MCP se montará encima.
        # También los que tienen alguna pero les falta otra (dos ventanas en
        # la muestra y volvió una): el plan la pide, y sin esto el bloque no
        # salía y esa ventana se quedaba sin camino (decisión 206).
        "para_restaurar": [
            {"id": f["id"], "nombre": f["nombre"], "proyecto_id": f["proyecto_id"]}
            for f in con.execute(
                "SELECT id, nombre, proyecto_id FROM slot "
                "WHERE status='activo' AND restaurar=1 ORDER BY proyecto_id, id"
            )
            if f["id"] not in slots_con_ventana or f["id"] in les_falta
        ],
        "restauracion": restauracion,
    }


# ───────────────────────────── sesiones de Claude ─────────────────────────────

# Tope de `/api/sesiones`: cada una de más es un transcript que leer entero la
# primera vez.
SESIONES_MAX = 200


@tiempos.medido
def sesiones(proyecto: str | None = None, desde: str | None = None, limite: int = 30) -> list[dict]:
    """Índice de las sesiones de Claude Code, de la más reciente a la más vieja.

    La ruta lo leía de `transcripts` por su cuenta, fuera de la costura de
    lectura (C-0310). La ficha de cada una sale recordada mientras su
    archivo no cambie (`transcripts.resumir_sesion`), así que pedir lo mismo
    dos veces ya no relee los transcripts."""
    return transcripts.listar_sesiones(
        registry.cargar(), proyecto or None, desde or None, min(limite, SESIONES_MAX))


def sesion(session_id: str, desde: str = "", hasta: str = "", crudo: bool = False) -> dict | None:
    """El contenido de una sesión: el esqueleto, o el tramo pedido con `crudo`
    o `desde`/`hasta`. `None` si el id no es de ninguna. La ruta lo leía de
    `transcripts` por su cuenta (C-0382)."""
    ruta = transcripts.ruta_de_sesion(session_id)
    if not ruta:
        return None
    if crudo or desde or hasta:
        return transcripts.zoom(ruta, desde or None, hasta or None)
    return transcripts.esqueleto(ruta)


def buscar(con: sqlite3.Connection, q: str, limite: int = 20) -> Any:
    """La paleta de comandos: destino y no sólo coincidencia, hasta 50 (C-0101)."""
    from . import busqueda
    return busqueda.buscar(con, q, max(1, min(limite, 50)))


def pregunta(con: sqlite3.Connection, pregunta_id: int) -> dict | None:
    """Una pregunta del canal de consulta, o `None` (C-0101)."""
    from . import canal as _canal
    return _canal.ver_pregunta(con, pregunta_id)


def preguntas(con: sqlite3.Connection, proyecto: str = "", estado: str = "",
              slot: int | None = None) -> list[dict]:
    """Las preguntas del canal, filtradas como las pide la CLI (C-0101)."""
    from . import canal as _canal
    return _canal.preguntas(con, proyecto or None, estado or None, slot)


def comandos_preparados() -> list[dict]:
    """Las plantillas de comando (decisión 251), cada una con los huecos que
    pide: lo que /archivos ofrece al abrir una terminal en una carpeta. La
    ruta las leía por su cuenta (C-0101)."""
    from . import comandos
    return [{**c, "huecos": comandos.huecos(c["plantilla"])} for c in comandos.leer()]


def sesiones_tmux() -> list[dict]:
    """Las sesiones de tmux de verdad, sin las espejo que abre el hub: las que
    /trabajo puede enseñar. La ruta se lo preguntaba a `terminal` (C-0101)."""
    from . import terminal
    return terminal.sesiones_disponibles()


def ventana_activa(session: str) -> int | None:
    """Qué ventana de esa sesión está en primer plano, según tmux: entrar por
    `?session=` sin ventana es lo normal desde la bandeja (C-0101)."""
    try:
        return next(v["indice"] for v in tmux.listar_ventanas(session) if v["activa"])
    except (StopIteration, tmux.DestinoInvalido):
        return None


def proyectos_declarados() -> int:
    """Cuántos proyectos DECLARA `projects.yml`, que no es lo mismo que cuántos
    hay indexados: con el índice vacío y el registro no, decir «no hay
    proyectos en projects.yml» manda a arreglar el único archivo que estaba
    bien. 0 si no se puede leer: la portada se pinta igual."""
    try:
        return len(registry.cargar())
    except Exception:  # noqa: BLE001 — la portada se pinta igual
        return 0


# ─────────────────────────────── lienzos ────────────────────────────────────
#
# El cuerpo lo interpreta el panel (`static/lienzos.js`, C-0387); aquí sólo la
# ficha de cada uno. Lo leían las rutas por su cuenta (C-0382).


def ficha_lienzo(lienzo, con_cuerpo: bool = False) -> dict[str, Any]:
    """Lo que sale de un lienzo por la API: lo mismo al listar, leer o guardar."""
    from . import lienzos as _lienzos

    ficha = {
        "id": lienzo.id,
        "titulo": lienzo.titulo,
        "plantilla": lienzo.plantilla,
        "proyecto_id": lienzo.proyecto_id,
        "slot": lienzo.slot,
        "publicado_en": lienzo.publicado_en,
        "archivado_en": lienzo.archivado_en,
        # Lo que decide si Claude puede republicar encima. Va en la ficha para
        # que el panel lo pueda enseñar sin una segunda llamada.
        "tuyo": lienzo.editado_por_el_usuario(),
    }
    if con_cuerpo:
        ficha["cuerpo"] = lienzo.cuerpo
        # Lo que el panel devuelve al guardar, para no pisar lo publicado
        # después de leerlo (C-0383).
        ficha["version"] = _lienzos.version(lienzo)
    return ficha


def lienzos(proyecto: str = "", q: str = "", archivados: bool = False) -> list[dict[str, Any]]:
    """Los del proyecto, o los que casen con `q` en todos los proyectos.

    Buscar sale del proyecto a propósito —el panel enseña lo que tienes
    delante y buscar sirve justamente para lo que no— y **sí encuentra los
    archivados**: archivar los quita de la lista, no de la memoria. Sin
    proyecto ni consulta, nada. Un proyecto que no vale levanta `ValueError`.
    """
    from . import lienzos as _lienzos

    hallados = (_lienzos.buscar(q) if q
                else (_lienzos.listar(proyecto, archivados=archivados) if proyecto else []))
    return [ficha_lienzo(l) for l in hallados]


def lienzo(proyecto_id: str, lienzo_id: str) -> dict[str, Any] | None:
    """Un lienzo con su cuerpo y su `version`, o `None` si no existe."""
    from . import lienzos as _lienzos

    encontrado = _lienzos.leer(proyecto_id, lienzo_id)
    return ficha_lienzo(encontrado, con_cuerpo=True) if encontrado else None


# ─────────────────────────────── el orquestador ─────────────────────────────


def orquestador(con: sqlite3.Connection, tarea_id: str = "", proyecto: str = "") -> dict[str, Any]:
    """Lo que pinta /orquestador: la bandeja, la tarea que se mira y la lista.

    Todo sale de disco —las carpetas de las tareas y el YAML de permisos—; aquí
    no se decide nada, se reúne. `proyecto` filtra la lista: con semanas de
    tareas encima, lo que se busca es «qué ha pasado en tal proyecto», no todo.
    """
    from . import orquestador as orq

    tareas = orq.listar()
    for t in tareas:
        t["creada_local"] = _hora_local(t.get("creada"))
        # Las tareas de antes de los puntos no tienen `pasos`: se cuentan del
        # plan, que es de donde salen igual.
        if not t.get("pasos"):
            t["pasos"] = orq.contar_pasos(orq.plan(t["id"]))
        t["puntos"] = orq.puntos(t)
        t["etiqueta"] = orq.ETIQUETA.get(t["estado"], t["estado"])
    viva = next((t for t in tareas if t["estado"] in orq.VIVAS), None)
    elegida = None
    if tarea_id:
        elegida = next((t for t in tareas if t["id"] == tarea_id), None)
    elegida = elegida or viva

    detalle = None
    if elegida:
        detalle = {
            **elegida,
            "plan": orq.plan(elegida["id"]),
            "bitacora": [{**b, "hora": _hora_local(b.get("cuando"))}
                         for b in reversed(orq.bitacora(elegida["id"]))][:80],
            "esperando": [e for e in elegida["esperas"] if e["estado"] == "esperando"],
            "confirmar": orq.pendientes_de_confirmar(elegida),
            "viva": elegida["estado"] in orq.VIVAS,
            # Lo que dejó abierto, sólo de una cerrada (C-0351).
            "restos": restos_de_tarea(con, elegida) if elegida["estado"] in orq.CERRADAS else None,
        }

    cuenta: dict[str, int] = {}
    for t in tareas:
        for p in t.get("proyectos") or []:
            cuenta[p] = cuenta.get(p, 0) + 1
    nombres = {p["id"]: p["nombre"] for p in listar_proyectos(con)}
    lista = [t for t in reversed(tareas)
             if t["estado"] not in orq.VIVAS
             and (not proyecto or proyecto in (t.get("proyectos") or []))]
    return {
        "viva": viva,
        # Lo que el orquestador no puede hacer sin el dueño (decisión 279).
        "confirmar": orq.pendientes_de_confirmar(viva) if viva else [],
        "detalle": detalle,
        "cola": [t for t in tareas if t["estado"] == orq.EN_COLA],
        "lista": lista[:30],
        "mas": max(0, len(lista) - 30),
        "filtro": proyecto,
        "por_proyecto": sorted(
            ({"id": p, "nombre": nombres.get(p, p), "tareas": n} for p, n in cuenta.items()),
            key=lambda x: -x["tareas"]),
        "con_alcance": sum(1 for n in orq.leer_permisos().values() if n != "nada"),
        "etiquetas": orq.ETIQUETA,
    }


def restos_de_tarea(con: sqlite3.Connection, tarea: dict[str, Any]) -> dict[str, Any]:
    """Lo que una tarea del orquestador dejó abierto: los slots que abrió
    (`abiertas`) y siguen activos o con ventanas, y esas ventanas (C-0351).

    Cada tarea dejaba su slot y su ventana para siempre —cuatro slots «orq-…»
    y la sesión `orq-hub` con ventanas `bash` en el hallazgo—, entre las
    sesiones perdidas de la portada y en Trabajo. Aquí sólo se cuentan, para
    ENSEÑARLO en la tarea y ofrecer recogerlo con un botón suyo: el
    orquestador no cierra ni archiva nada solo (regla dura 3), y esto no toca
    `orquestador.py`. Las ventanas y su servidor salen de la misma muestra,
    porque se cierran por (pane_id, servidor) (396). La sesión fija del
    tablero no cuenta: se reutiliza en la tarea siguiente y no es de ésta.

    🔴 Lo que usa la tarea EN CURSO no es resto de nadie (revisión cruzada):
    `abrir_sesion` hace que la siguiente reutilice la sesión que ya hay en el
    proyecto, así que el slot `orq-…` de una cerrada suele ser el panel donde
    trabaja la viva. Un slot con una ventana que la viva espera o abrió, o que
    ella abrió, sale `en_uso`: se enseña, pero no se ofrece ni cuenta."""
    from . import orquestador as orq

    actual = snapshot_actual(con)
    paneles = paneles_de(con, actual["id"]) if actual else []
    fija = tarea.get("sesion_fija") or {}
    viva = orq.viva()
    usados_panes: set[str] = set()
    usados_slots: set[int] = set()
    if viva and viva["id"] != tarea.get("id"):
        usados_panes = {e.get("pane_id") for e in viva.get("esperas") or [] if e.get("estado") == "esperando"}
        usados_panes |= {a.get("pane_id") for a in viva.get("abiertas") or []}
        usados_slots = {a.get("slot_id") for a in viva.get("abiertas") or []}
    panes_por_ventana = _paneles_por_ventana(paneles)
    restos: list[dict[str, Any]] = []
    vistos: set[int] = set()
    for abierta in tarea.get("abiertas") or []:
        slot_id = abierta.get("slot_id")
        if not isinstance(slot_id, int) or slot_id in vistos:
            continue
        vistos.add(slot_id)
        if fija and abierta.get("proyecto") == fija.get("proyecto") and abierta.get("nombre") == fija.get("nombre"):
            continue
        slot = obtener_slot(con, slot_id)
        if not slot:
            continue
        ventanas: dict[tuple[str, int], dict] = {}
        for p in paneles:
            if p["slot_id"] == slot_id:
                ventanas.setdefault((p["session"], p["window_idx"]), p)
        activo = slot["status"] == "activo"
        if not activo and not ventanas:
            continue
        en_uso = slot_id in usados_slots or any(
            usados_panes.intersection(panes_por_ventana[clave]) for clave in ventanas)
        restos.append({
            "id": slot_id, "nombre": slot["nombre"], "proyecto": slot["proyecto_id"], "activo": activo,
            "en_uso": en_uso,
            "ventanas": [{"session": s, "ventana": i, "pane_id": p["pane_id"],
                          "etiqueta": p["etiqueta"] or f"{s}:{i}"}
                         for (s, i), p in sorted(ventanas.items())],
        })
    libres = [r for r in restos if not r["en_uso"]]
    return {
        "slots": restos,
        # Lo que el botón recoge: sin lo que usa la tarea en curso.
        "ventanas": sum(len(r["ventanas"]) for r in libres),
        "activos": sum(1 for r in libres if r["activo"]),
        "servidor": actual["server_pid"] if actual else None,
    }


def orquestador_permisos(con: sqlite3.Connection) -> dict[str, Any]:
    """La pantalla de permisos, aparte: se toca una vez y se revisa de tarde en tarde."""
    from . import orquestador as orq

    permisos = orq.leer_permisos()
    proyectos = [
        {"id": p["id"], "nombre": p["nombre"], "guardrail": p["guardrail"],
         "nivel": "nada" if p["guardrail"] == "never" else permisos.get(p["id"], "nada")}
        for p in listar_proyectos(con) if p.get("tipo") == "proyecto"
    ]
    return {
        "proyectos": sorted(proyectos, key=lambda p: (p["nivel"] == "nada", p["nombre"].lower())),
        "niveles": orq.NIVELES,
        "descripcion": orq.DESCRIPCION,
        "siempre_del_dueno": orq.SIEMPRE_DEL_DUENO,
    }


def _hora_local(iso: str | None) -> str:
    """«22/09 14:41» en la hora de la casa. En UTC, leído en el móvil, engaña.

    La zona es la de `reloj.zona`, la misma con que el secretario recuerda: con
    la de la máquina por su cuenta, una hora podía salir distinta en dos
    pantallas (C-0051).

    Es la pieza `local` de `reloj.cuando` (con el año si no es el de ahora), y
    queda para las frases —«Docker no ha contestado desde el …»— y lo que una
    plantilla mete en un atributo. Una fecha suelta en pantalla va con
    `ui.cuando`, que además dice cuánto hace (C-0396).
    """
    c = reloj.cuando(iso)
    return c["local"] if c else (iso or "")


def _intercambio_por_proyecto(con: sqlite3.Connection, archivos: list[dict]) -> list[dict]:
    """Proyecto → slot → archivos, lo más nuevo primero en cada nivel (decisión 288).

    La carpeta es `proyecto/<id>-<slot>/archivo`. Lo que no cuelga de un
    proyecto registrado —subido sin elegir, o una carpeta que dejó una
    sesión— va a «Sin proyecto», y lo de un proyecto sin slot, a «Sin slot».
    """
    from . import intercambio as _intercambio

    proyectos = {f["id"]: f["nombre"] for f in con.execute("SELECT id, nombre FROM proyecto")}
    slots = {f["id"]: f["nombre"] for f in con.execute("SELECT id, nombre FROM slot")}
    arbol: dict[str, dict[str, list[dict]]] = {}
    titulos: dict[str, str] = {}
    for a in archivos:   # ya vienen ordenados, lo más nuevo primero
        tramos = a.get("tramos") or []
        proyecto = tramos[0] if tramos and tramos[0] in proyectos else ""
        seccion = "Sin slot"
        if proyecto and len(tramos) > 1:
            m = re.match(r"^(\d+)(?:-|$)", tramos[1])
            seccion = (slots.get(int(m.group(1))) if m else None) or tramos[1]
        titulos[proyecto] = proyectos.get(proyecto, "Sin proyecto")
        arbol.setdefault(proyecto, {}).setdefault(seccion, []).append(a)
    grupos = []
    for proyecto, secciones in arbol.items():
        miembros = [a for lista in secciones.values() for a in lista]
        grupos.append({
            "titulo": titulos[proyecto],
            "proyecto_id": proyecto,
            "archivos": miembros,
            "secciones": [{"titulo": t, "archivos": l, "cuantos": len(l)}
                          for t, l in secciones.items()],
            "tandas": [],
            "cuantos": len(miembros),
            "tamano": _intercambio.tamano(sum(a["bytes"] for a in miembros)),
            "ultimo": max(a["mtime"] for a in miembros),
        })
    return sorted(grupos, key=lambda g: g["ultimo"], reverse=True)


def destinos_intercambio(con: sqlite3.Connection) -> list[dict]:
    """Dónde se puede dejar lo que se sube: cada proyecto, y cada slot suyo."""
    destinos = []
    for p in con.execute("SELECT id, nombre FROM proyecto WHERE status != 'archivado' "
                         "AND tipo = 'proyecto' ORDER BY nombre"):
        destinos.append({"valor": p["id"], "etiqueta": p["nombre"]})
        for sl in con.execute("SELECT id, nombre FROM slot WHERE proyecto_id = ? "
                              "AND status = 'activo' ORDER BY nombre", (p["id"],)):
            destinos.append({"valor": f"{p['id']}:{sl['id']}",
                             "etiqueta": f"{p['nombre']} · {sl['nombre']}"})
    return destinos


def intercambio(con: sqlite3.Connection, por: str = "proyecto", q: str = "") -> dict[str, Any]:
    """La carpeta de intercambio, agrupada para que se sepa qué es cada cosa.

    `q` filtra por nombre (también la subcarpeta): es lo que se usa cuando uno
    ya sabe qué busca y no quiere abrir grupos.
    """
    from . import ideas as _ideas
    from . import intercambio as _intercambio

    por = por if por in _intercambio.AGRUPACIONES else "proyecto"
    archivos = _intercambio.listar()
    total = len(archivos)
    q = (q or "").strip()
    if q:
        archivos = [a for a in archivos if q.lower() in a["nombre"].lower()]
    # «Nuevo» es la última tanda que llegó, no «la última hora»: en una hora
    # una sesión puede dejar dos tandas, y lo que se quiere ver es la última.
    ahora = datetime.now().timestamp()
    ultima = _intercambio.tandas(archivos)[0] if archivos else []
    recien = {a["nombre"] for a in ultima
              if ahora - a["mtime"] < _intercambio.NUEVO_SEGUNDOS}
    for a in archivos:
        a["cuando_local"] = _hora_local(a["cuando"])
        a["nuevo"] = a["nombre"] in recien
        a["caduca_local"] = (reloj.a_local(datetime.fromtimestamp(a["caduca"], timezone.utc).isoformat(), "%d/%m")
                             if a.get("caduca") else None)
        # 🔴 Con miniatura sólo lo que `/intercambio/ver` sirve en línea: la
        # misma lista, `ideas.TIPOS_IMAGEN`, y no el grupo «Imágenes», que mete
        # svg y heic. Un SVG en línea en el mismo origen que la terminal es un
        # XSS (343). Y hasta `MINIATURA_HASTA`, que la miniatura es el archivo.
        a["imagen"] = (Path(a["archivo"]).suffix.lower() in _ideas.TIPOS_IMAGEN
                       and a["bytes"] <= _intercambio.MINIATURA_HASTA)
    grupos = (_intercambio_por_proyecto(con, archivos) if por == "proyecto"
              else _intercambio.agrupar(archivos, por))
    for g in grupos:
        for t in g["tandas"]:
            desde = datetime.fromtimestamp(t["desde"])
            hasta = datetime.fromtimestamp(t["hasta"])
            t["etiqueta"] = desde.strftime("%d/%m %H:%M") + (
                "" if hasta.strftime("%H:%M") == desde.strftime("%H:%M")
                else "–" + hasta.strftime("%H:%M"))
    return {
        "grupos": grupos,
        "por": por,
        "agrupaciones": _intercambio.AGRUPACIONES,
        "q": q,
        "total": total,
        "encontrados": len(archivos),
    }


def salud(con: sqlite3.Connection) -> list[dict]:
    """Las comprobaciones de `/maquina` (decisión 289)."""
    from . import maquina as _maquina
    from . import salud as _salud
    return _salud.revisar(slots_activos(con), _maquina.ultimas(con))


def maquina(con: sqlite3.Connection) -> dict[str, Any]:
    """Lo que pinta /maquina: cómo está el equipo cuando no hay nadie delante.

    Lee lo que midió el ciclo lento y **no vuelve a medir**: la pantalla se
    abre para mirar, y lanzar `nvidia-smi` y un `powershell` en cada visita
    metería un segundo de espera en algo que se consulta desde el móvil (regla
    dura 14). Por eso va la hora de la lectura (`medido_en`).
    """
    from . import avisos, canal, rele
    from . import maquina as _maquina

    medidas = _maquina.ultimas(con)
    ajustes = rele.ajustes()
    limites = avisos.limites_maquina(ajustes)
    dueno = canal.dueno(con)
    revisiones = salud(con)
    return {
        "medidas": medidas,
        "tarjetas": _tarjetas_de_maquina(medidas, limites),
        "arranque": _ultimo_arranque(medidas),
        "medido_en": max((m["medido_en"] for m in medidas.values()), default=""),
        "limites": limites,
        "armadas": bool(dueno) and avisos.activos(ajustes),
        "dueno_nombre": canal.nombre_visible(dueno) if dueno else "",
        "salud": revisiones,
        # Lo que pide algo, abierto; lo que está bien, plegado en una línea
        # (C-0378): diez «bien» seguidos empujaban debajo lo que fallaba.
        "salud_atencion": [r for r in revisiones if r["estado"] != "ok"],
        "salud_en_pie": [r for r in revisiones if r["estado"] == "ok"],
        # Lo llena sólo «Diagnosticar ahora» (`diagnosticar_pc`): abrir la
        # pantalla no lanza nada en Windows (regla dura 14).
        "diagnostico": None,
        "diagnostico_en_marcha": False,   # lo pone la ruta si ya corre uno (C-0209)
    }


def _tarjetas_de_maquina(medidas: dict, limites: dict) -> list[dict]:
    """Las cifras de arriba, en el orden en que se miran con prisa.

    El orden no es decorativo: primero lo que puede matar la máquina estando
    sola —calor y disco—, y después lo que sólo dice cómo va. `urge` se calcula
    con el MISMO límite con el que avisa el relé: dos números distintos para la
    misma cosa es cómo se aprende a no creerse ninguno.
    """
    from . import maquina as _maquina

    def numero(clave: str) -> float | None:
        medida = medidas.get(clave) or {}
        return medida.get("valor")

    filas = []
    temperatura = numero("gpu.temperatura")
    if temperatura is not None:
        filas.append({
            "nombre": "GPU", "valor": f"{temperatura:.0f}", "unidad": "°C",
            "icono": "aviso" if temperatura >= limites["temperatura"] else "punto",
            "urge": temperatura >= limites["temperatura"],
            "pie": (medidas.get("gpu.nombre") or {}).get("texto", ""),
        })
    for clave, nombre in (
        ("disco.windows", "Disco de Windows"), ("disco.wsl", "Disco de WSL"),
    ):
        libre, uso = numero(f"{clave}.libre"), numero(f"{clave}.uso")
        if libre is None:
            continue
        filas.append({
            "nombre": nombre, "valor": f"{libre:.0f}", "unidad": "GB libres",
            "icono": "pilas",
            "urge": libre <= limites["disco"],
            "pie": f"{uso:.0f} % ocupado" if uso is not None else "",
        })
    # El SAI va justo después del calor y el disco: es el único dato que avisa
    # de algo que está pasando AHORA en la casa, no de cómo va el equipo.
    estado_ups = numero("ups.estado")
    if estado_ups is not None:
        sobre_bateria = estado_ups == _maquina.SOBRE_BATERIA
        minutos, carga_ups = numero("ups.minutos"), numero("ups.carga")
        filas.append({
            "nombre": "SAI",
            "valor": "sin luz" if sobre_bateria else "con luz",
            "unidad": "",
            "urge": sobre_bateria,
            "icono": "aviso" if sobre_bateria else "escudo",
            "pie": " · ".join(
                p for p in (
                    f"{carga_ups:.0f} % de batería" if carga_ups is not None else "",
                    f"~{minutos:.0f} min de margen" if minutos is not None else "",
                    (medidas.get("ups.nombre") or {}).get("texto", ""),
                ) if p
            ),
        })

    memoria, carga, uso_gpu = numero("memoria.libre"), numero("carga"), numero("gpu.uso")
    if memoria is not None:
        filas.append({"nombre": "Memoria de WSL", "valor": f"{memoria:.1f}".replace(".", ","),
                      "unidad": "GB libres", "urge": False, "pie": "",
                      "icono": "rejilla"})
    if carga is not None:
        filas.append({"nombre": "Carga", "valor": f"{carga:.2f}".replace(".", ","), "unidad": "",
                      "urge": False, "pie": "media del último minuto",
                      "icono": "lineas"})
    if uso_gpu is not None:
        filas.append({"nombre": "Uso de GPU", "valor": f"{uso_gpu:.0f}", "unidad": "%",
                      "urge": False, "pie": "", "icono": "lineas"})
    return filas


def _duracion(segundos: int) -> str:
    if segundos < 120:
        return f"{segundos} s"
    if segundos < 7200:
        return f"{segundos // 60} min"
    return f"{segundos // 3600} h {segundos % 3600 // 60} min"


def _ultimo_arranque(medidas: dict) -> dict | None:
    """Cuánto tardaron WSL y los servicios del hub tras encender Windows la
    última vez (C-0381): la evidencia de C-0014 que dejan los apagones reales.

    🔴 Sólo se cruza lo de una misma vuelta del ciclo lento (`medido_en`): si
    PowerShell falló en la última, `windows.arranque` es de un encendido
    anterior y la resta mentiría. Y nada si no cuadra —Linux antes que
    Windows—: una cifra que no se puede defender no se enseña (regla 13).
    Qué significa la espera no se dice: si alguien inició sesión entre medias
    aún no se mide."""
    def leida(clave: str) -> tuple[datetime, str] | None:
        """El instante guardado y la vuelta en que se leyó; None si no hay."""
        m = medidas.get(clave) or {}
        if not m.get("texto"):
            return None          # `reloj.instante` sin valor es «ahora»
        try:
            return reloj.instante(m["texto"]), m.get("medido_en") or ""
        except ValueError:
            return None

    windows, wsl, hub = leida("windows.arranque"), leida("encendido.wsl"), leida("encendido.hub")
    if not windows or not wsl or windows[1] != wsl[1] or wsl[0] < windows[0]:
        return None
    wsl_s = int((wsl[0] - windows[0]).total_seconds())
    hub_s = (int((hub[0] - windows[0]).total_seconds())
             if hub and hub[1] == wsl[1] and hub[0] >= wsl[0] else None)
    return {"wsl_s": wsl_s, "wsl": _duracion(wsl_s),
            "hub_s": hub_s, "hub": _duracion(hub_s) if hub_s is not None else ""}


def diagnosticar_pc() -> dict[str, Any]:
    """«Diagnosticar ahora» en Máquina (C-0209): Windows y su red, por la misma
    puerta que la CLI y el secretario (`hub.diagnostico`, decisión 386), con sus
    guiones fijos de sólo lectura y su tope de tiempo.

    🔴 A petición y nunca al abrir la pantalla (regla dura 14): son segundos de
    PowerShell y `ping.exe`. No se guarda, como en la 386: lo que se enseña es
    de este momento y lleva su hora. Los dos van a la vez, cada uno en su
    `try`: que la red falle no puede dejar sin ver los pantallazos.
    """
    from concurrent.futures import ThreadPoolExecutor

    from . import diagnostico as _d

    def uno(medir):
        try:
            return medir(), None
        except _d.SinWindows as exc:
            return None, ("sin_windows", str(exc))
        except Exception as exc:  # noqa: BLE001 — se dice en la tarjeta (regla dura 21)
            print(f"[maquina] el diagnóstico ({medir.__name__}) falló: {exc}", flush=True)
            return None, ("error", f"{type(exc).__name__}: {exc}")

    with ThreadPoolExecutor(max_workers=2) as hilos:
        de_windows, de_red = hilos.submit(uno, _d.windows), hilos.submit(uno, _d.red)
        (win, fallo_win), (red, fallo_red) = de_windows.result(), de_red.result()
    fallos = [f for f in (fallo_win, fallo_red) if f]
    win, red = win or {}, red or {}
    equipo = win.get("equipo") or {}
    bios = equipo.get("bios") or {}
    placa = " ".join(x for x in ((equipo.get("placa") or {}).get("fabricante"),
                                 (equipo.get("placa") or {}).get("modelo")) if x)
    latencias = []
    for x in red.get("latencias") or []:
        if not x.get("recibidos"):
            perdida = "sin respuesta" + (f" ({x['nota']})" if x.get("nota") else "")
        elif x.get("perdidos_pct") is None:
            # Cortado en el tope: los que faltan no llegaron a salir (regla 13).
            perdida = f"pérdida sin medir ({x.get('nota') or 'no terminó'})"
        else:
            perdida = f"{x['perdidos_pct']} % perdidos"
        latencias.append({**x, "perdida": perdida})
    return {
        "hecho_en": reloj.ahora(),
        "sin_windows": next((texto for clase, texto in fallos if clase == "sin_windows"), ""),
        "errores": [texto for clase, texto in fallos if clase == "error"],
        "fallos": [*(win.get("fallos") or []), *(red.get("fallos") or [])],
        "windows": bool(win), "red": bool(red),
        "dias": win.get("dias"),
        "pantallazos": list(win.get("pantallazos") or []),
        "volcados": [{**v, "mb": round((v.get("bytes") or 0) / 1024**2)}
                     for v in win.get("volcados") or []],
        "sin_permiso": win.get("sin_permiso") or [],
        "equipo": " · ".join(p for p in (
            equipo.get("cpu") or "",
            f"placa {placa}" if placa else "",
            f"BIOS {bios.get('version')} del {bios.get('fecha')}" if bios.get("version") else "",
        ) if p),
        "adaptadores": red.get("adaptadores") or [],
        "latencias": latencias,
        "segundos": max(win.get("segundos") or 0, red.get("segundos") or 0),
    }


# Cuántas entradas del registro del canal por página. 40 es lo que cabe sin
# scroll infinito y sin obligar a paginar por todo: el registro crece y no se
# poda nunca, porque es la auditoría de lo que sale de la máquina.
CANAL_POR_PAGINA = 40


def canal(con: sqlite3.Connection, *, direccion: str | None = None, quien: int | None = None,
          proyecto: str | None = None, pagina: int = 1, situacion: str | None = None,
          proyecto_preguntas: str | None = None) -> dict[str, Any]:
    """Lo que pinta /canal: la matriz de permisos, las preguntas y el registro
    de todo lo que entra y sale, con sus filtros (decisión 23: por la URL).

    🔴 Aquí NO se manda nada (regla dura 22): preguntar es de `hub preguntar`
    y del relé, y esto sólo lee. Los avisos los cuenta `avisos.panorama`, que
    hoy abre también la memoria del secretario (C-0061).
    """
    from . import avisos, rele
    from . import canal as _canal

    pagina = max(1, int(pagina or 1))
    filtros = {"direccion": direccion or None, "user_id": quien, "proyecto_id": proyecto or None}
    total = _canal.cuenta_registro(con, **filtros)
    vistas = _canal.preguntas(con, proyecto_preguntas or None, situacion=situacion or None)
    proyectos = listar_proyectos(con)
    usuarios = _canal.usuarios(con)
    # Por persona, los proyectos donde tiene algo y los demás, que la pantalla
    # ofrece en un selector (HER-11, C-0372): eran todos por tres acciones,
    # 105 casillas con 35 proyectos para 8 permisos reales en 2.
    for u in usuarios:
        con_algo = {p["proyecto_id"] for p in u["permisos"]}
        u["proyectos_con"] = [p for p in proyectos if p["id"] in con_algo]
        u["proyectos_sin"] = [p for p in proyectos if p["id"] not in con_algo]
    return {
        "usuarios": usuarios,
        "proyectos": proyectos,
        "acciones": _canal.ACCIONES,
        "preguntas": vistas[:30],
        # Las dos cifras: sin la de arriba, un filtro que deja 30 y el tope
        # que deja 30 se ven exactamente igual.
        "preg_mostradas": len(vistas[:30]),
        "preg_total": len(vistas),
        "preg_todas": _canal.cuenta_preguntas(con),
        "situaciones": tuple(_canal.SITUACIONES),
        # Los paneles a los que se puede empujar a mano una respuesta que nació
        # sin destino. Salen del último muestreo y no de preguntarle a tmux uno
        # por uno: la comprobación de verdad la hace `entrega` en el instante
        # de escribir (regla dura 15), y consultar veinte paneles para pintar
        # un desplegable haría lenta una pantalla que se abre para leer.
        "paneles": [p for p in paneles_abiertos(con) if p.get("slot_id")],
        "registro": _canal.registro(con, CANAL_POR_PAGINA, desde=(pagina - 1) * CANAL_POR_PAGINA,
                                    **filtros),
        "reg_total": total,
        "reg_pag": pagina,
        "reg_paginas": max(1, -(-total // CANAL_POR_PAGINA)),
        "direcciones": ("sale", "entra", "falla"),
        "canal_estado": rele.estado(),
        "avisos": avisos.panorama(con, rele.ajustes(), _canal.dueno(con)),
    }


# Cuántas líneas del registro de encargos se enseñan de una vez. Es un TOPE y
# no una página: `encargos.registro` no acepta desplazamiento, al revés que el
# del canal de consulta, así que aquí no se puede paginar sin tocar el dominio.
ENCARGOS_EN_REGISTRO = 60


def encargos(con: sqlite3.Connection, filtro: str = "") -> dict[str, Any]:
    """Lo que pinta /encargos: quién puede mandarlos, los encargos y lo que ha
    pasado por su bot (decisión 221). `filtro` deja el registro en un encargo.

    🔴 Aquí NO se manda nada (regla dura 22): el token lo lee `hub-encargos`.
    """
    from . import buzon, rele_encargos
    from . import encargos as _encargos

    gente = _encargos.personas(con)
    por_persona = {p["user_id"]: p for p in gente}
    return {
        "personas": gente,
        # Sólo a alguien activo se le puede abrir un encargo, así que el
        # desplegable de crear no puede ofrecer a los demás: una opción que
        # siempre falla es una trampa, no un filtro.
        "activas": [p for p in gente if p["estado"] == "activo"],
        # La cuenta de sin entregar va aquí y no en la plantilla porque es lo
        # único de la fila que pide una acción: un encargo con mensajes en cola
        # y sin agente abierto es exactamente el caso que el buzón existe para
        # que no se pierda. Una consulta por encargo: son pocos.
        "encargos": [{**f, "quien": _encargos.nombre_visible(por_persona.get(f["user_id"])),
                      "sin_entregar": len(buzon.en_cola(con, f["id"]))}
                     for f in _encargos.listar(con)],
        "propuesto": _encargos.siguiente_provisional(con),
        "canal_estado": rele_encargos.estado(),
        "registro": _encargos.registro(con, ENCARGOS_EN_REGISTRO, filtro),
    }


def encargo(con: sqlite3.Connection, encargo_id: str) -> dict[str, Any] | None:
    """La ficha de un encargo y la conversación entera de la que salió, o
    `None` si no existe.

    Las dos cosas juntas a propósito: la ficha es el estado y la conversación
    no (el porqué está en `encargos.py`), pero cuando algo de la ficha extraña,
    lo primero que se quiere ver es qué dijo ella exactamente.

    🔴 `conversacion` y `dicho` son texto de un tercero, tal como llegó. Para
    pintarlo, la plantilla lo escapa; quien lo lleve a un panel lo enmarca antes
    (`buzon.marcar`, regla dura 22): no es una instrucción del dueño.
    """
    from . import buzon, rele_encargos
    from . import encargos as _encargos

    fila = _encargos.ver(con, encargo_id)
    if not fila:
        return None
    ficha = _encargos.cargar_ficha(con, encargo_id)
    siguiente = ficha.siguiente()
    return {
        "enc": fila,
        "quien": _encargos.nombre_visible(_encargos.ver_persona(con, fila["user_id"])),
        # La ficha se aplana aquí y no en la plantilla: así la vista pinta y
        # no razona, y lo que se enseña se puede afirmar sin renderizar nada.
        "fases": [
            {
                "id": f.id, "titulo": f.titulo, "pregunta": f.pregunta,
                "campo": f.campo, "minimo": f.minimo, "se_elige": f.se_elige,
                "valor": ficha.campos.get(f.campo, ""),
                "contestada": ficha.contestada(f.id),
                "agotada": ficha.agotada(f.id),
                "veces": ficha.preguntado.get(f.id, 0),
                "tope": _encargos.TOPE_POR_FASE,
            }
            for f in _encargos.FASES
        ],
        "huecos": ficha.huecos(),
        "suficiente": ficha.suficiente(),
        "siguiente": siguiente.titulo if siguiente else "",
        # Los mismos estados que rechaza `entrevistador.abrir_agente`: publicado
        # o descartado no queda entrevista que seguir, y la ficha no ofrece un
        # botón que sólo llevaría a ese error (C-0384). Que no se separen lo
        # comprueba `test_encargos_web.py` con el entrevistador de verdad.
        "entrevista_abierta": fila["estado"] not in ("publicado", "descartado"),
        "dicho": ficha.dicho,
        "conversacion": buzon.conversacion(con, encargo_id),
        "sin_entregar": len(buzon.en_cola(con, encargo_id)),
        "registro": _encargos.registro(con, ENCARGOS_EN_REGISTRO, encargo_id),
        "canal_estado": rele_encargos.estado(),
    }


def guia(con: sqlite3.Connection) -> dict[str, Any]:
    """Los primeros pasos —medidos— y el mapa de pantallas (decisión 271)."""
    from . import guia as _guia, orquestador

    try:
        niveles = orquestador.leer_permisos()
    except ValueError:
        niveles = {}
    # Donde el secretario es la voz, el asistente está retirado: los pasos
    # hablan de él y «Guíame» le pregunta a él (C-0355).
    secretario = nombre_secretario() if secretario_en_todo_el_hub() else None
    pasos = _guia.pasos(listar_proyectos(con, incluir_archivados=True), slots_activos(con), repos_de(con),
                        paneles_abiertos(con), niveles, _carpeta_existe, secretario)
    obligatorios = [p for p in pasos if not p["opcional"]]
    return {
        "pasos": pasos,
        "hechos": sum(1 for p in obligatorios if p["hecho"]),
        "total": len(obligatorios),
        "mapa": _guia.mapa(_opcionales.encendidas()),
        "opcionales": opcionales(),
    }


def opcionales() -> list[dict[str, Any]]:
    """Las herramientas opcionales y si están encendidas en esta instalación,
    para el bloque de la Guía donde se encienden (decisión 438)."""
    encendidas = _opcionales.encendidas()
    return [{"clave": clave, "nombre": o.nombre, "ruta": o.ruta, "icono": o.icono,
             "que_es": o.que_es, "quien": o.quien, "encendida": clave in encendidas}
            for clave, o in _opcionales.OPCIONALES.items()]


def actualizacion() -> dict[str, Any]:
    """La actualización en marcha o la última (decisión 296): lo que la
    pantalla vuelve a preguntar cada dos segundos mientras dura, también al
    volver del reinicio. Sólo lee sus archivos; lo que pregunta al repo va
    aparte, en `actualizaciones`."""
    from . import actualizacion as _actualizacion
    return _actualizacion.estado()


def actualizaciones() -> dict[str, Any]:
    """Lo que pinta /actualizaciones: tu versión, la actualización y lo que la
    pararía (C-0100). Mirar si hay una publicada nueva no va aquí: sale a la
    red, y cuándo se mira lo decide quien abre la pantalla."""
    from . import actualizacion as _actualizacion
    return {
        # `vers` y no `v`: base.html hace `{% set v = rail.version %}` y lo pisaría.
        "vers": _version.para_la_guia(),
        "a": actualizacion(),
        "cambios": _actualizacion.cambios_locales(),
    }


def incidencia(con: sqlite3.Connection, *, interfaz: str, navegador: str | None,
               de: str | None = None) -> dict[str, Any]:
    """Lo que pinta /incidencia (C-0468, decisión 445): los tipos con su
    plantilla, los campos, el tope de la URL, a dónde se abre y el texto de
    los datos del equipo, ya hecho para que la persona lo vea antes de salir.

    `destino` es None si el `origin` no es de GitHub: entonces sólo se copia.
    De la salud pasan sólo `clave` y `estado`; del agente de Reuniones, su
    versión si late. `interfaz` y `navegador` son de la petición (la cookie y
    el User-Agent), así que los pasa la ruta. Nada de aquí sale de la
    máquina: lo arma el navegador y lo manda la persona."""
    from . import actualizacion as _actualizacion
    from . import incidencias as _incidencias
    from . import reuniones as _reuniones
    latido = _reuniones.agente()
    datos = _incidencias.datos_del_equipo(
        version=_version.estado(), commit=_version.commit(),
        con_cambios=bool(_actualizacion.cambios_locales()),
        salud=[{"clave": r.get("clave"), "estado": r.get("estado")} for r in salud(con)],
        encendidas=_opcionales.encendidas(), interfaz=interfaz, navegador=navegador,
        agente_reuniones=latido.get("agente") if latido.get("vivo") else None, de=de)
    origen = _incidencias.origen(de)
    return {
        "tipos": [{"clave": clave, "plantilla": plantilla, **_incidencias.ROTULOS[clave]}
                  for clave, plantilla in _incidencias.TIPOS.items()],
        "campos": list(_incidencias.CAMPOS),
        "limite": _incidencias.LIMITE_URL,
        "limite_titulo": _incidencias.LIMITE_TITULO,
        "destino": _incidencias.destino(_version.repo_github()),
        "equipo": _incidencias.como_texto(datos),
        "de": {"clave": origen, "nombre": _incidencias.ORIGENES[origen]} if origen else None,
    }


def acceso(codigo: str | None = None, de_casa: bool = False, al_momento: bool = False) -> dict[str, Any]:
    """Lo que pinta /acceso: por qué nombres se entra, qué aparatos están dados
    de alta y si la terminal remota está encendida (decisiones 158-163).

    `codigo` es un alta recién creada: si sigue esperando, sale en `pendiente`.
    El enlace del QR no va aquí: el nombre por el que va a entrar el aparato
    depende de por dónde se está mirando la pantalla, y eso es de la petición.
    Un `acceso.yml` mal escrito no tumba la pantalla: se enseñan los nombres
    locales, qué está mal y cómo quedaría arreglado (`acceso.revisar`, C-0504).

    `de_casa` añade `red`: el nombre de esta máquina en la red privada y si
    `tailscale serve` lleva al hub. Al momento (`maquina.red_privada`) sólo
    mientras falte algo o haya un alta esperando —tras «Preparar con Claude»
    la medida del ciclo lento llega con minutos de retraso—; si no, de esa
    medida. `al_momento` la pide siempre al momento: el secretario contesta
    por lo que hay ahora, no por lo de hace un rato. Desde fuera no se mira:
    eso sólo se arregla en casa."""
    from . import acceso as _acceso
    from . import maquina as _maquina

    revision = _acceso.revisar()
    error = revision["error"]
    # Con la raíz del archivo rota tampoco se leen aparatos ni altas: la
    # pantalla daba un 500 justo donde se explica el arreglo (C-0504).
    try:
        pendientes, aparatos = _acceso.pendientes(), _acceso.dispositivos()
    except _acceso.AccesoInvalido as exc:
        pendientes, aparatos, error = [], [], error or str(exc)
    pendiente = next((p for p in pendientes if p["codigo"] == codigo), None) \
        if codigo else None
    red = None
    if de_casa:
        if not revision["utilizables"] or pendiente or al_momento:
            red = _maquina.red_privada()
        else:
            red = _red_medida()
    return {
        "hosts": revision["hosts"], "locales": _acceso.HOSTS_LOCALES,
        "utilizables": revision["utilizables"], "avisos": revision["avisos"],
        "arreglo": revision["arreglo"], "huella": revision["huella"],
        # Sin la huella del testigo: no la pinta nadie, y lo que sale de `api`
        # lo pueden leer el asistente y el MCP.
        "dispositivos": [{k: v for k, v in d.items() if k != "hash"}
                         for d in aparatos],
        "terminal_remota": _acceso.terminal_remota(),
        "pendiente": pendiente,
        "minutos": _acceso.MINUTOS_DE_ALTA,
        "archivo": str(_acceso.archivo()), "error": error,
        "red": red,
    }


def _red_medida() -> dict | None:
    """Si `tailscale serve` llevaba al hub en la última vuelta lenta, o None
    si no se midió. Sin el nombre ni el puerto: eso sólo se mira al momento."""
    from . import db
    from . import maquina as _maquina

    try:
        con = db.conectar()
        try:
            serve = _maquina.ultimas(con).get("desatendido.serve")
        finally:
            con.close()
    except (sqlite3.Error, OSError, db.BaseIlegible):
        return None
    if not serve or serve.get("valor") is None:
        return None
    return {"hay": True, "conectado": None, "nombre": "", "puerto": None, "error": "",
            "lleva_al_hub": bool(serve["valor"])}


def _carpeta_existe(ruta: str) -> bool:
    try:
        return Path(ruta).expanduser().is_dir()
    except OSError:
        return False


# ──────────────────── el navegante (el navegador de Claude) ──────────────────


def navegante() -> dict[str, Any]:
    """Lo que pinta /navegante: preguntas del guardián, guardianes vivos,
    sus últimas decisiones y los últimos flujos corridos."""
    import time
    from . import navegante as nav
    def hora(t):
        return time.strftime("%d-%m %H:%M:%S", time.localtime(float(t))) if t else ""
    preguntas = [{**p, "hora": hora(p.get("creada"))} for p in nav.preguntas()]
    r = nav.resumen() or {}
    conf = r.get("config") or {}
    from . import componentes
    pasos = componentes.pasos_navegante()
    return {
        "instalado": nav.instalado(),
        "pasos": pasos,
        "listo": componentes.listo(pasos),
        "lab": str(nav.lab()),
        "lab_disponible": nav.disponible(),
        "carpeta": str(nav.carpeta()),
        "estado": r.get("estado"),
        "flujos": r.get("flujos", []),
        "mapa": r.get("mapa") or {"pantallas": [], "salen": {}, "sin_pantalla": []},
        "politicas": r.get("politicas", []),
        "accesos": conf.get("accesos", []),
        "colecciones": [c["nombre"] for c in conf.get("colecciones", [])],
        "preguntas": preguntas,
        "pendientes": [p for p in preguntas if p.get("estado") == "pendiente"],
        "registro": [{**e, "hora": hora(e.get("t"))} for e in nav.registro()],
        "corridas": nav.corridas(),
    }


def componentes() -> dict[str, Any]:
    """Qué les falta a Navegante, Reuniones, el Puente KVM y el estudio para
    funcionar (decisiones 293, 438 y 463). Lo lee el asistente para guiar, con los mismos
    pasos que pintan las pantallas. Del puente, sin preguntarle si contesta:
    eso sólo al pintar /puente."""
    from . import componentes as _c
    from . import reuniones as _r
    pasos = _c.pasos_navegante()
    del_puente = _c.pasos_puente()
    # El estudio, sólo encendido (461) y sin preguntarle si contesta, como el
    # puente: eso es de su pantalla.
    del_estudio: dict[str, Any] = {"encendida": False, "pantalla": _c.PANTALLA["estudio"]}
    if _opcionales.encendida("estudio"):
        pasos_e = _c.pasos_estudio()
        del_estudio.update(encendida=True, pasos=pasos_e, listo=_c.listo(pasos_e))
    return {
        "navegante": {"carpeta": str(_c.carpeta("navegador-lab")), "pasos": pasos,
                      "listo": _c.listo(pasos), "pantalla": _c.PANTALLA["navegador-lab"]},
        "reuniones": {**_r.preparacion(), "pantalla": _c.PANTALLA["reuniones"]},
        "puente": {"carpeta": str(_c.carpeta("puente-kvm")), "pasos": del_puente,
                   "listo": _c.listo(del_puente), "pantalla": _c.PANTALLA["puente-kvm"],
                   "encendida": _opcionales.encendida("puente-kvm")},
        "estudio": del_estudio,
    }


# ───────────────────────────── el Puente KVM ─────────────────────────────


def puente(local: bool) -> dict[str, Any]:
    """Lo que pinta /puente (decisión 438): si está encendido, cómo está el
    puente y qué le falta.

    Es el único sitio donde se le pregunta al puente (`puente.estado`, un GET
    a loopback con un plazo absoluto de 0,8 s): ni el raíl ni el muestreo lo
    hacen. Apagado no se le pregunta nada. Los pasos preguntan además a
    systemd por su servicio (`salud.estado_servicio`: hasta tres llamadas a
    `systemctl` con 5 s de tope cada una), así que pintar esto puede tardar
    bastante más que el sondeo si systemd no contesta.

    `direccion` sólo va si `local` —se entró desde la PC donde corre—: desde
    otro aparato no se ofrece abrirlo, porque su web no pasa por la puerta de
    /acceso (regla dura 8). Y desde otro aparato, por qué no llega al JetKVM
    se dice sin el detalle (`puente.para_fuera`)."""
    from . import componentes as _c
    from . import puente as _p
    if not _opcionales.encendida("puente-kvm"):
        return {"encendida": False}
    estado = _p.estado()
    if not local:
        estado = _p.para_fuera(estado)
    pasos = _c.pasos_puente(estado)
    datos: dict[str, Any] = {
        "encendida": True, "local": local, "estado": estado,
        "aparato": _p.APARATOS.get(estado["aparato"] or ""),
        "control": _p.CONTROLES.get(estado["control"] or ""),
        "pasos": pasos, "listo": _c.listo(pasos),
    }
    if local:
        datos["direccion"] = _p.direccion()
    return datos


# ───────────────────────────── el estudio ─────────────────────────────


def estudio(local: bool) -> dict[str, Any]:
    """Lo que pinta /estudio (decisión 461): si está encendido, si contesta,
    sus proyectos y cómo se abre o se instala.

    Es el único sitio donde se le pregunta al estudio (`estudio.estado`, dos
    GET a loopback con un plazo absoluto de 0,8 s entre los dos): ni el raíl
    ni el muestreo lo hacen. Apagado no se le pregunta nada.

    Las direcciones —la del estudio y la de cada proyecto— sólo van si
    `local`: su web no pasa por la puerta de /acceso (regla dura 8), y desde
    otro aparato no se ofrece abrirla. Sin contestar van además sus pasos
    (`componentes.pasos_estudio`), que preguntan a systemd si lo hay: hasta 5 s
    más si no contesta."""
    from . import estudio as _e
    if not _opcionales.encendida("estudio"):
        return {"encendida": False}
    estado = _e.estado()
    datos: dict[str, Any] = {"encendida": True, "local": local, "estado": estado,
                             "proyectos": [dict(p) for p in estado["proyectos"] or []]}
    if local:
        datos.update(direccion=_e.direccion(), puerto=_e.puerto(), variable_puerto=_e.VARIABLE_PUERTO)
        for p in datos["proyectos"]:
            p["direccion"] = _e.direccion_de(p["id"])
    if estado["vivo"]:
        nueva = _e.version_nueva(estado.get("version"))
        if nueva:
            datos.update(actualizar={"corre": estado.get("version"), "publicada": nueva},
                         se_puede_preparar=True)
    if not estado["vivo"]:
        # Lo que falta, en pasos y sin un comando para la persona: lo hace la
        # sesión de «Preparar con Claude» (C-0503). Sin rutas, así que sirve
        # también desde fuera; el botón sólo se ofrece desde la PC donde corre.
        from . import componentes as _c
        pasos = _c.pasos_estudio(estado)
        datos.update(pasos=pasos, listo=_c.listo(pasos),
                     se_puede_preparar=_e.kit() is not None or _e.en_catalogo())
    return datos


def navegante_corrida(flujo: str, cuando: str) -> dict[str, Any]:
    from . import navegante as nav
    return nav.corrida(flujo, cuando)


# ───────────────────────────────── reuniones ─────────────────────────────────


def reuniones() -> dict[str, Any]:
    from . import reuniones as r
    a = r.agente()
    o = r.orden()
    lista = r.lista()
    pendientes = [x for x in lista if x["terminada"] and not x["comprimida"] and x["estado"] != "procesando"]
    return {"agente": a, "orden": o, "lista": lista, "raices": [str(x) for x in r.raices()],
            "sin_comprimir": {"n": len(pendientes), "bytes": sum(x["tamano"] for x in pendientes),
                              "comprimiendo": any(x["comprimiendo"] for x in lista)},
            "miniaturas": [m["n"] for m in a.get("monitores") or [] if r.miniatura(m["n"])],
            "grabando": a.get("grabando") if o.get("grabar") else None,
            "preparacion": r.preparacion(),
            "version_agente": r.version_agente(a),
            "sigue_ventana": r.sigue_ventana(a),
            "conexion": {"hay_llave": r.hay_llave(), "rechazo": r.rechazo_reciente(),
                         "carpeta_agente": str(r.carpeta_agente()),
                         "carpeta_existe": r.carpeta_agente().is_dir()}}


def reunion(id_: str) -> dict[str, Any]:
    from . import reuniones as r
    from . import base as _b  # noqa: F401
    d = r.detalle(id_)
    # Las voces que hay (Persona 1, 2…), en orden, con el nombre que tengan.
    vistas = sorted({s["quien"] for s in d["transcripcion"]
                     if str(s.get("quien", "")).startswith("Persona ")},
                    key=lambda q: int(q.split()[-1]) if q.split()[-1].isdigit() else 0)
    d["voces"] = [{"clave": q, "nombre": d["nombres"].get(q, "")} for q in vistas]
    d["sin_separar"] = bool(d["transcripcion"]) and not vistas and any(
        s.get("quien") == "Reunión" for s in d["transcripcion"])
    d["transcripcion"] = [{**s, "nombre": d["nombres"].get(s.get("quien"), s.get("quien"))}
                          for s in d["transcripcion"]]
    hh = lambda s: f"{int(s) // 3600:02d}:{int(s) % 3600 // 60:02d}:{int(s) % 60:02d}"
    # La transcripción con las fotos intercaladas en su segundo, igual que el .md.
    eventos = [(s["ini"], 1, {**s, "hora": hh(s["ini"])}) for s in d["transcripcion"]] + \
              [(f, 0, {"foto": f, "hora": hh(f)}) for f in d["fotos"]]
    d["linea"] = [e[2] for e in sorted(eventos, key=lambda e: (e[0], e[1]))]
    d["compromisos"] = compromisos_de_reunion(id_)
    return d


def compromisos_de_reunion(id_: str) -> list[dict]:
    """Los compromisos abiertos que el secretario sacó de esta reunión (C-0380),
    para cerrarlos de una vez. Vacío si no hay memoria del secretario: una
    pantalla que sólo mira no la crea."""
    from .secretario import memoria as _mem
    from .secretario.fuentes.hub import FuenteHub, clave_reunion

    try:
        con = _memoria_secretario()
    except sqlite3.Error:
        return []
    if con is None:
        return []
    try:
        evento = _mem.id_evento(con, FuenteHub.id, clave_reunion(id_))
        if evento is None:
            return []
        lista = _mem.compromisos(con, "abierto", evento=evento)
    finally:
        con.close()
    return lista


def conversaciones(con: sqlite3.Connection, slot_id: int) -> list[dict]:
    """Las conversaciones de Claude de un slot, para retomarlas (decisión 290)."""
    from . import conversaciones as conv
    return conv.de_slot(con, slot_id)


# ───────────────────────────── el secretario ─────────────────────────────


def _memoria_secretario():
    """La base del secretario en sólo lectura, si existe y está al día
    (`memoria.abrir_lectura`, C-0099). `None` en un hub que no lo usa: una
    pantalla que sólo mira no crea ni migra la base, que es del servicio."""
    from .secretario import memoria as _mem
    return _mem.abrir_lectura()


# Si la última vez no se pudo abrir: el sondeo del chat va cada pocos
# segundos, y el registro lo dice al empezar la racha, no en cada vuelta.
_MEMORIA_SIN_LEER = {"racha": False}


def _memoria_para_pintar():
    """`_memoria_secretario` para lo que pinta /secretario y sondea el chat de
    todas las pantallas: una memoria bloqueada más de lo que espera
    `abrir_lectura` o ilegible se pinta como sin base —vacía y parada— en vez
    de un 500, y se dice en el registro una vez por racha (regla dura 21)."""
    import sys

    try:
        con = _memoria_secretario()
    except sqlite3.Error as exc:
        if not _MEMORIA_SIN_LEER["racha"]:
            print(f"web: no pude leer la memoria del secretario ({exc}); se pinta vacía hasta que se pueda",
                  file=sys.stderr, flush=True)
        _MEMORIA_SIN_LEER["racha"] = True
        return None
    _MEMORIA_SIN_LEER["racha"] = False
    return con


def secretario_pendientes() -> int:
    """Para el raíl: lo que espera el sí del dueño. Barato, una consulta.
    Donde el personaje se pinta, la cifra sale de `secretario_espera` (C-0166)."""
    try:
        m = _memoria_secretario()
    except sqlite3.Error:
        return 0
    if m is None:
        return 0
    try:
        return m.execute("SELECT COUNT(*) FROM solicitud WHERE estado = 'pendiente'").fetchone()[0]
    finally:
        m.close()


def _valor_legible(valor: Any) -> str:
    """El valor de un parámetro como lo lee el dueño: «sí» o «no» en vez de
    `True`, y una lista con cada elemento entre comillas en vez de `['a', 'b']`
    (C-0231): unidos con comas a secas, «b, c.pdf» parecía dos archivos y no
    se sabía cuántos eran (revisor)."""
    if isinstance(valor, bool):
        return "sí" if valor else "no"
    if valor is None:
        return "—"
    if isinstance(valor, (list, tuple)):
        return " · ".join(f"«{v}»" for v in valor) if valor else "(ninguno)"
    return str(valor)


#: Las notas que se pintan: las más recientes, o las primeras que dicen lo buscado.
NOTAS_VISTAS = 80
NOTAS_HALLADAS = 300


def secretario_solicitudes(con: sqlite3.Connection, pendientes: bool = False) -> list[dict[str, Any]]:
    """Lo que el secretario pidió permiso para hacer, como lo lee el dueño.

    La única lectura de `solicitud` para pintar (C-0421): la usan Pendientes,
    «Te espera» y la tarjeta «Pide tu permiso» del chat, que antes no existía
    porque rótulos, datos y orden se armaban dentro de `secretario()`.

    `pendientes=True`: sólo las que esperan su sí. Si no, las 30 últimas y,
    además, toda la que espera: una pendiente más vieja contaba en el globo y
    no se pintaba (revisión cruzada del 7-nov). Las más nuevas primero.

    Cada una lleva `params` tal cual (es lo que se ejecuta) y, para pintar:
    `nombre` (el de Confianza), `datos` (`[rótulo, valor]`, enteros: lo que se
    aprueba se lee completo, 395), `orden` (la de su PC, aparte y literal),
    `estado_rotulo`, `creada_local` (para la tarjeta del chat, que la pinta
    en JS: «Lo pidió el …»), y de su acción `riesgo_rotulo` y
    `con_techo`. En las pendientes, `datos` lleva además lo que la acción
    enseña sin guardarlo (`Accion.detalle`: la nota que pide olvidar). 🔴 El motivo y los valores los escribe el modelo: quien los
    pinte los escapa."""
    import json as _json

    from .secretario import piezas as _p

    acciones = _p.acciones()
    donde = ("estado = 'pendiente'" if pendientes else
             "estado = 'pendiente' OR id IN (SELECT id FROM solicitud ORDER BY id DESC LIMIT 30)")
    out = []
    for s in con.execute(f"SELECT * FROM solicitud WHERE {donde} ORDER BY id DESC"):
        d = dict(s)
        try:
            d["params"] = _json.loads(d["params"] or "{}")
        except ValueError:
            d["params"] = {}
        if not isinstance(d["params"], dict):
            d["params"] = {}
        # Una que se cortó a mitad se lee «no sé si se hizo» (C-0315).
        d["estado_rotulo"] = _p.ROTULOS_ESTADO.get(d["estado"], d["estado"])
        # La tarjeta del chat la pinta en JS, sin `ui.cuando`: ya formateada,
        # en la hora de la casa (C-0395, tras la revisión: se perdió al
        # unificar las fechas y la tarjeta dejó de decir cuándo se pidió).
        d["creada_local"] = _hora_local(d["creada"])
        # Lo que se pinta: con rótulo y sin `True` de Python (C-0231). `params`
        # sigue tal cual, que es lo que se ejecuta.
        d["datos"] = [[_p.rotulo_parametro(k), _valor_legible(v)] for k, v in d["params"].items()
                      if k != "comando"]
        # Una orden para su PC (C-0240) se lee entera y tal cual, aparte:
        # es lo que se va a correr si dice que sí.
        d["orden"] = d["params"].get("comando") if isinstance(d["params"].get("comando"), str) else None
        # El nombre, aquí y no en la plantilla, y por la regla de todos
        # (`piezas.nombre_de_accion`, C-0395).
        a = acciones.get(d["accion"])
        d["nombre"] = _p.nombre_de_accion(d["accion"], acciones)
        d["riesgo_rotulo"] = _p.ROTULOS_RIESGO.get(a.riesgo, a.riesgo.replace("-", " ")) if a else ""
        d["con_techo"] = bool(a and _p.con_techo(a))
        if a and d["estado"] == "pendiente":
            # Lo que hay que ver para decidir y no se guarda con la solicitud
            # (`Accion.detalle`, C-0418): leído ahora, sólo mientras espera.
            try:
                d["datos"] += [[str(k), str(v)] for k, v in a.detalle(con, d["params"])]
            except Exception as exc:  # noqa: BLE001 — una acción rota no deja Pendientes sin pintar; se dice
                d["datos"].append(["detalle", f"no se pudo leer ({exc})"])
        out.append(d)
    return out


@tiempos.medido
def secretario(pestana: str = "conversacion", notas_q: str = "", notas_tema: str = "",
               notas_sin_salir: bool = False) -> dict[str, Any]:
    """Lo que pinta /secretario (`PLAN-SECRETARIO.md`, decisiones 298-305).

    `notas_q`: buscar en todas las notas, no sólo en las que se pintan
    (SEC-35: el filtro del navegador sólo veía las 80 últimas).
    `notas_tema` (uno de `memoria.TEMAS`) y `notas_sin_salir` (las que no se
    le han servido al modelo desde que se cuenta) filtran también sobre
    todas, y se suman a la búsqueda (C-0424)."""
    import json as _json

    from .secretario import conversacion as _conv, disparadores as _disp, memoria as _mem, piezas as _p
    from .secretario import personaje as _pj
    from .secretario.avisos import webpush as _webpush
    from .reloj import a_local

    # Sin base, una vacía en RAM: la misma vista, parado y sin nada, y sin
    # crearle la base al servicio (C-0099).
    con = _memoria_para_pintar() or _mem.vacia()
    try:
        vivo, latido = _latido_secretario(con)
        h = _conv.hilo_abierto(con)
        turnos = _conv.turnos(con, h["id"]) if h else []
        ajustes = _p.ajustes_fuentes()
        estados = _mem.estados_fuentes(con)
        fuentes = []
        # Las conversaciones que ya se han leído, para elegirlas tocando en vez
        # de teclear su nombre. De la memoria y no de `Fuente.conversaciones()`:
        # ésa abre la cuenta (Telegram), y la web no ve llaves (decisión 298).
        vistas: dict[str, list[str]] = {}
        for c in _mem.conversaciones(con):
            if c["conversacion"]:
                vistas.setdefault(c["fuente"], []).append(c["conversacion"])
        for fid, f in _p.fuentes().items():
            e = estados.get(fid) or {}
            a = ajustes.get(fid) or {}
            fuentes.append({"id": fid, "nombre": f.nombre, "descripcion": f.descripcion,
                            "activa": bool(a.get("activa")), "falta": f.disponible(),
                            "incluir": ", ".join(a.get("incluir") or []),
                            "excluir": ", ".join(a.get("excluir") or []),
                            "leida": e.get("leida"), "error": e.get("error"), "eventos": e.get("eventos", 0),
                            "vistas": vistas.get(fid, [])[:40]})
        compromisos = _mem.compromisos(con, "abierto")
        for c in compromisos:
            c["vence_local"] = a_local(c.get("vence"))
            c["recordar_local"] = a_local(c.get("recordar_en"))
        solicitudes = secretario_solicitudes(con)
        catalogo = _p.acciones()
        acciones = [{"id": a.id, "nombre": _p.nombre_de_accion(a.id, catalogo), "resumen": a.resumen or a.descripcion,
                     "descripcion": a.descripcion, "riesgo": a.riesgo, "nivel": _p.nivel(a),
                     "solo_con_el_dueno": a.solo_con_el_dueno,
                     "riesgo_rotulo": _p.ROTULOS_RIESGO.get(a.riesgo, a.riesgo.replace("-", " ")),
                     # Lo que no puede estar en `auto`, y si es porque el acto es
                     # suyo y no por lo que rompe (C-0422): Confianza lo dice.
                     "con_techo": _p.con_techo(a), "siempre_pregunta": bool(a.siempre_pregunta),
                     # Al modelo no se le ofrece; aquí sigue, con dónde se
                     # configura, para que el dueño sepa que existe (C-0389).
                     "sin_configurar": "" if _p.se_ofrece(a) else (a.como_configurar or "Falta configurarla."),
                     "aprobadas": con.execute("SELECT COUNT(*) FROM bitacora WHERE accion = ? AND nivel = 'aprobada'"
                                              " AND ok = 1", (a.id,)).fetchone()[0],
                     # La sugerencia de `auto` va con éstas, no con el total (303, SEC-45).
                     "aprobadas_seguidas": _mem.aprobadas_seguidas(con, a.id)}
                    for a in catalogo.values()]
        nombres_acciones = {a["id"]: a["nombre"] for a in acciones}
        bitacora = _mem.bitacora(con, 60)
        for b in bitacora:
            # Con el nombre que tiene en Confianza (C-0231, C-0395). Lo que
            # apunta el servicio sin ser una acción (un disparador, el triaje),
            # al menos sin guiones bajos.
            b["nombre"] = _p.nombre_de_accion(b["accion"], catalogo)
        huecos = secretario_huecos(con)
        huecos_sueltos = secretario_huecos_sin_clasificar(con)
        notas_q = " ".join((notas_q or "").split())[:200]
        notas_total = con.execute("SELECT COUNT(*) FROM nota").fetchone()[0]
        # El filtro por tema ofrece la lista (C-0424); un tema de fuera no
        # filtra: las notas de antes llevan el suyo libre, y para eso está
        # buscar, que también mira el tema.
        notas_tema = notas_tema if notas_tema in _mem.TEMAS else ""
        # «Sin salir» sólo desde que se cuenta: sin esa fecha no hay «desde» que
        # decir, y «nunca salió» no se puede defender (regla dura 13).
        uso_desde = _mem.leer(con, _mem.USO_DESDE)
        notas_sin_salir = bool(notas_sin_salir and uso_desde)
        filtrando = bool(notas_tema or notas_sin_salir)
        # Lo que pasa la búsqueda y «sin salir», aún sin el tema: de ahí sale
        # cuántas trae cada tema en el desplegable, para que la cifra sea lo
        # que se verá al elegirlo y no el total del tema.
        sin_el_tema = _mem.buscar_notas(con, notas_q) if notas_q else None
        if notas_sin_salir:
            no_salieron = _mem.notas(con, None, sin_leer=True)
            ids = {n["id"] for n in no_salieron}
            sin_el_tema = no_salieron if sin_el_tema is None else [n for n in sin_el_tema if n["id"] in ids]
        por_tema = _mem.cuantas_por_tema(con) if sin_el_tema is None else Counter(n["tema"] for n in sin_el_tema)
        if notas_tema:
            halladas = [n for n in (_mem.notas(con, None, tema=notas_tema) if sin_el_tema is None else sin_el_tema)
                        if n["tema"] == notas_tema]
        else:
            halladas = sin_el_tema
        notas = halladas[:NOTAS_HALLADAS] if halladas is not None else _mem.notas(con, NOTAS_VISTAS)
        hilos = [dict(x) for x in con.execute(
            "SELECT id, titulo, resumen, cerrado FROM hilo WHERE cerrado IS NOT NULL ORDER BY id DESC LIMIT 15")]
        # Lo vencido o de hoy, aparte y con los mismos campos que se pintan
        # (UI-33, C-0369): en «Próximos» se leía como lo que viene. Lo que
        # viene: lo que tiene fecha, lo más cercano primero.
        ids_vencidos = {c["id"] for c in _mem.vencidos_o_de_hoy(con)}
        vencidos = [c for c in compromisos if c["id"] in ids_vencidos]
        proximos = sorted((c for c in compromisos
                           if (c.get("recordar_en") or c.get("vence")) and c["id"] not in ids_vencidos),
                          key=lambda c: c.get("recordar_en") or c.get("vence"))[:6]
        espera = secretario_espera(None, con)
        aparatos = _mem.suscripciones(con)
        for a in aparatos:
            a["huella"] = _mem.huella_de(a["endpoint"])
        return {
            "pestana": pestana,
            "seccion": pestana if pestana in ("conversacion", "pendientes", "memoria") else "ajustes",
            "proximos": proximos,
            "vencidos": vencidos,
            # Los abiertos que no han vencido: en Pendientes, lo vencido va en
            # su bloque y no se repite en la lista (C-0373).
            "no_vencidos": [c for c in compromisos if c["id"] not in ids_vencidos],
            "push": {"publica": _webpush.publica(), "aparatos": aparatos, "canal_actual": _canal_actual()},
            "avisos_error": _mem.leer(con, "avisos_error"),
            "vivo": vivo, "latido": latido,
            # Sólo si no late: preguntarle a systemd en cada pintado sobra.
            "servicio": None if vivo else _servicio_secretario(),
            "hilo": dict(h) if h else None, "turnos": turnos,
            "hilos": hilos,
            "fuentes": fuentes,
            "compromisos": compromisos,
            "solicitudes": solicitudes,
            "pendientes": sum(1 for s in solicitudes if s["estado"] == "pendiente"),
            "acciones": acciones,
            "nombres_acciones": nombres_acciones,
            "bitacora": bitacora,
            "huecos": huecos,
            "huecos_sueltos": huecos_sueltos,
            "notas": notas, "notas_q": notas_q, "notas_total": notas_total,
            "notas_halladas": len(halladas) if halladas is not None else None,
            "notas_tema": notas_tema, "notas_sin_salir": notas_sin_salir, "notas_filtrando": filtrando,
            "notas_uso_desde": uso_desde,
            "temas": [{"tema": t, "notas": por_tema.get(t, 0)} for t in _mem.TEMAS],
            "investigaciones": secretario_investigaciones(con),
            "disparadores": _disp.texto_crudo(),
            "disparadores_lista": _disp.lista(),
            "uso": _mem.uso(con),
            **_mem.cuentas_triaje(con),
            "triaje": _mem.leer(con, "triaje"),
            "ingles": _conv.ingles(con),
            # El de la cabecera y el marcado en la galería (C-0188): de la
            # memoria abierta, también cuando el raíl no lo lee.
            "personaje": personaje_vista(_mem.leer(con, _pj.CLAVE)),
            "nombre": nombre_secretario(con),
            # Para el personaje de la cabecera cuando el raíl no lo trae (sin
            # `en_todo_el_hub`): sin las sesiones, que llegan con el sondeo.
            "espera": espera,
            "ideas": secretario_ideas(espera),
        }
    finally:
        con.close()


def secretario_huecos(con) -> list[dict[str, Any]]:
    """Lo que el dueño pidió y el secretario no supo hacer (C-0247), de la
    bitácora (acción `hueco`). Agrupado por `ideas.clave_hueco`, sin agrupar
    por sentido: eso sería inventar. Los más repetidos primero, y a igualdad
    el más reciente. Su recorrido como mejora, de `secretario.huecos.mejoras`
    (C-0252), el mismo cruce que usa el ciclo del secretario."""
    import json as _json

    from . import ideas as _ideas
    from .secretario import huecos as _huecos

    grupos: dict[str, dict[str, Any]] = {}
    for b in con.execute("SELECT cuando, params FROM bitacora WHERE accion = 'hueco' ORDER BY id"):
        try:
            que = str(_json.loads(b["params"] or "{}").get("que") or "")
        except ValueError:
            continue
        clave = _ideas.clave_hueco(que)
        if not clave:
            continue
        g = grupos.setdefault(clave, {"que": " ".join(que.split()), "veces": 0, "ultimo": ""})
        g["veces"] += 1
        g["ultimo"] = max(g["ultimo"], b["cuando"])
    mejoras = _huecos.mejoras()
    for clave, g in grupos.items():
        g["mejora"] = mejoras.get(clave)
    return sorted(grupos.values(), key=lambda g: (g["veces"], g["ultimo"]), reverse=True)


#: Cuántas investigaciones enseña Memoria (SEC-20): las demás siguen en sus
#: notas (tema «investigación») y en la bitácora.
INVESTIGACIONES_VISTAS = 20


def secretario_investigaciones(con, n: int = INVESTIGACIONES_VISTAS) -> list[dict[str, Any]]:
    """Las últimas investigaciones, una por investigación y la más reciente
    primero (SEC-20): pregunta, modelo, cuándo, cómo acabó, cuánto tardó y a
    cuánto equivale, y el enlace a su nota si la dejó.

    De la bitácora y no de `llamada`: ahí no hay con qué saber de qué
    investigación es cada llamada, y emparejarlas por la hora sería una cifra
    que no se puede defender (regla 13). Lo que no se apuntó —el modelo y el
    gasto de las de antes de esto— sale vacío, y lo que se cortó sin dar su
    cuenta, «no se sabe» (SEC-23). Cómo acabó lo dice `investigar.desenlace`."""
    import json as _json
    from urllib.parse import quote

    from . import modelos as _modelos
    from .secretario import investigar as _inv

    out: list[dict[str, Any]] = []
    for b in con.execute("SELECT cuando, params, resultado FROM bitacora WHERE accion = 'investigar'"
                         " ORDER BY id DESC"):
        try:
            p = _json.loads(b["params"] or "{}")
        except ValueError:
            continue
        estado = _inv.desenlace(p, b["resultado"]) if isinstance(p, dict) else None
        if estado is None:
            continue
        ident = str(p.get("id") or "")
        out.append({
            "pregunta": " ".join(str(p.get("pregunta") or "").split()),
            "modelo": _modelos.legible(p["modelo"]) if p.get("modelo") else "",
            "cuando": b["cuando"],
            "estado": _inv.ESTADOS[estado],
            "tiempo": _inv.legible_tiempo(p.get("segundos")) if "segundos" in p else "",
            "gasto": _gasto_investigacion(p),
            # Por su `ref.`, que va en la primera línea de su nota (SEC-19).
            "enlace": f"/secretario?p=memoria&q={quote(f'ref. {ident}')}" if estado == "hecha" and ident else "",
        })
        if len(out) >= n:
            break
    return out


def _gasto_investigacion(p: dict) -> str:
    """Lo gastado como se lee en la lista: «equivale a…» (324), «lo gastado
    no se sabe» si se cortó sin dar su cuenta, o nada si no se apuntó."""
    from .secretario import investigar as _inv

    if "coste" not in p:
        return ""
    if p["coste"] is None:
        return "lo gastado no se sabe"
    return f"equivale a {_inv.legible_coste(p['coste'], p.get('coste_falta') or 0)}"


def secretario_huecos_sin_clasificar(con) -> dict[str, Any]:
    """Las respuestas que sonaban a «no puedo» sin que el secretario apuntara
    qué le faltaba (C-0324): las deja la red de `conversacion.contestar`, con
    el turno y sin texto. Sólo cuántas y cuándo la última: qué pidió no se
    sabe, y agruparlas con las demás sería inventarlo."""
    from .secretario import memoria as _mem

    f = con.execute("SELECT COUNT(*) AS veces, MAX(cuando) AS ultimo FROM bitacora WHERE accion = 'hueco'"
                    " AND resultado = ?", (_mem.HUECO_SIN_CLASIFICAR,)).fetchone()
    return {"veces": f["veces"] or 0, "ultimo": f["ultimo"]}


def secretario_datos() -> dict[str, Any]:
    """Lo que pinta Ajustes → Mis datos (decisión 382): cada campo de
    `misdatos.CAMPOS`, con su valor, si está propuesto o confirmado, de dónde
    salió y la propuesta que espera al lado de uno confirmado. Sólo lee: sin
    ficha no crea ni la carpeta del secretario. Una ficha rota se dice."""
    from .secretario import misdatos as _md

    try:
        ficha, error = _md.leer(), None
    except _md.FichaIlegible as exc:
        ficha, error = {}, str(exc)
    filas = []
    for campo, nombre in _md.CAMPOS.items():
        d = ficha.get(campo) or {}
        p = d.get("propuesta") or {}
        filas.append({"campo": campo, "nombre": nombre, "valor": d.get("valor", ""), "estado": d.get("estado", ""),
                      "fuente": d.get("fuente", ""), "cuando": d.get("cuando") or "",
                      "propuesta": {"valor": p["valor"], "fuente": p.get("fuente", "")} if p else None})
    return {"filas": filas, "error": error, "archivo": str(_md.ruta()),
            "confirmados": sum(f["estado"] == "confirmado" for f in filas),
            "propuestos": sum(f["estado"] == "propuesto" or bool(f["propuesta"]) for f in filas)}


def _servicio_secretario() -> str:
    """Por qué no late, para decir lo que toca (decisión 400): `parado` (se
    ofrece encenderlo), `en-marcha` (corre pero no late: arrancando o
    colgado), `falla` (se cae y systemd lo reintenta: encenderlo no arregla
    nada) o `sin-systemd` (sólo a mano)."""
    from . import salud
    e = salud.estado_servicio("hub-secretario")
    if e is None:
        return "sin-systemd"
    if e["activo"] == "active":
        return "en-marcha"
    # `Restart=always`: uno que revienta al arrancar pasa la espera entre
    # intentos en `activating`, no en `failed`.
    if e["activo"] == "activating":
        return "falla"
    return "parado"


def _latido_secretario(con: sqlite3.Connection) -> tuple[bool, str | None]:
    """Si `hub-secretario` está en marcha —latió hace menos de dos minutos;
    su ciclo es de 30 s— y su último latido tal cual (UTC)."""
    from .secretario import memoria as _mem
    latido = _mem.leer(con, "latido")
    return bool(latido) and _segundos_desde(latido) < 120, latido


def secretario_monitor(hub: sqlite3.Connection | None = None) -> dict[str, Any]:
    """Lo que pinta /secretario/monitor (C-0202, decisión 389): el secretario
    para una pantalla dedicada.

    Lo mismo que la conversación de /secretario —el hilo abierto, el modo
    inglés, quién es, lo que espera— y el escenario: los puestos y en cuál se
    pone con cada estado y gesto (`personaje.escenario`), que el JS sólo
    aplica. Sin las fuentes, la bitácora ni las notas: aquí no se pintan.
    Pintarla sin secretario no le crea la base: el chat sale vacío y él,
    quieto (C-0099: tampoco el sondeo de los turnos ni /secretario)."""
    from .secretario import conversacion as _conv, memoria as _mem, personaje as _pj

    vista = {"puestos": [{"id": k, "nombre": n, "que": q, "accesorio": a} for k, (n, q, a) in _pj.PUESTOS.items()],
             "escenario": _pj.escenario(), "vivo": False, "latido": None, "turnos": [], "ingles": False,
             "personaje": personaje_vista(), "espera": None, "nombre": nombre_secretario()}
    try:
        con = _memoria_secretario()
    except sqlite3.Error:
        con = None
    if con is None:
        return vista
    try:
        vivo, latido = _latido_secretario(con)
        h = _conv.hilo_abierto(con)
        vista.update(vivo=vivo, latido=latido, turnos=_conv.turnos(con, h["id"]) if h else [],
                     ingles=_conv.ingles(con), personaje=personaje_vista(_mem.leer(con, _pj.CLAVE)),
                     nombre=nombre_secretario(con),
                     espera=secretario_espera(hub, con))
        vista["ideas"] = secretario_ideas(vista["espera"])
    finally:
        con.close()
    return vista


# Lo último leído de su memoria, por base (C-0239). Sólo vale si la lectura
# siguiente falla: quien lo puso con el botón no tiene nada en el yml, y un
# `database is locked` le devolvería al asistente.
_EN_TODO_LEIDO: dict[str, bool] = {}


def secretario_en_todo_el_hub() -> bool:
    """Si el secretario es la voz del hub y el asistente está retirado (C-0160, C-0164).

    Lo decide «En todas las pantallas», en Ajustes → Personaje, guardado en su
    memoria (C-0239, decisión 403). `en_todo_el_hub` de `secretario.yml` sólo
    vale si nunca se pulsó: quien lo tenía puesto así no nota nada. Sólo si su
    memoria existe. Nunca lanza: sin secretario, la respuesta es no."""
    try:
        from .secretario import conversacion as _conv, memoria as _mem
        if not _mem.existe():
            return False
        ruta = str(_mem.ruta())
        try:
            elegido = _mem.leer_sin_abrir(_conv.CLAVE_EN_TODO)
        except sqlite3.Error:
            # 🔴 Un fallo al leer no es un «no»: con `False` volvería el
            # asistente (web._asistente_retirado). Vale lo último leído en este
            # proceso; si no hay, el yml.
            elegido = _EN_TODO_LEIDO.get(ruta)
        else:
            if elegido is not None:
                _EN_TODO_LEIDO[ruta] = bool(elegido)
        if elegido is None:
            elegido = _conv.ajustes().get("en_todo_el_hub")
        return bool(elegido)
    except Exception:  # noqa: BLE001
        return False


def secretario_late(con: sqlite3.Connection) -> bool:
    """Si `hub-secretario` está en marcha ahora. Lo pide «Ponerlo en todas las
    pantallas» (C-0239): con el asistente retirado y él parado, abajo no
    contestaría nadie."""
    return _latido_secretario(con)[0]


def _canal_actual() -> str:
    """Por dónde saldría un aviso ahora mismo, dicho para el dueño."""
    from .secretario import avisos as _avisos
    try:
        canales = _avisos.cadena()
    except LookupError as exc:
        return str(exc)
    for c in canales:
        if not c.disponible():
            return c.nombre
    return "ninguno (no hay canal listo)"


def secretario_turnos(desde: int = 0, hub: sqlite3.Connection | None = None) -> dict[str, Any]:
    """Lo nuevo del hilo abierto, para la pantalla que espera la respuesta.

    Trae también `espera` (`secretario_espera`): es el mismo sondeo el que
    mueve al personaje, sin otro que abrir (C-0166). `hub` es la conexión de
    `hub.db`, para saber qué sesión trabaja lo que delegó. Y `vivo`, si
    `hub-secretario` late: sin él lo escrito espera en la base y el chat de
    cualquier pantalla tiene que poder decirlo (C-0302); es leer su latido,
    sin preguntar a systemd. Y `permisos`: las solicitudes que esperan su sí
    (`secretario_solicitudes`), para decidirlas sin salir del chat (C-0421).
    Y `ingles`, si el modo inglés está puesto ahora (C-0422). Sin base, vacío
    y parado (C-0099)."""
    from .secretario import conversacion as _conv, memoria as _mem

    con = _memoria_para_pintar()
    if con is None:
        # La misma forma que con base: el chat no tiene que distinguirlo.
        return {"hilo": None, "turnos": [], "espera": None, "vivo": False, "permisos": [], "ingles": False}
    try:
        espera = secretario_espera(hub, con)
        vivo = _latido_secretario(con)[0]
        # Lo que espera su sí, para la tarjeta del chat (C-0421). Sólo si hay
        # algo: este sondeo va cada 1,5 s mientras contesta.
        permisos = secretario_solicitudes(con, pendientes=True) if espera and espera["solicitudes"] else []
        # El modo inglés, como está ahora: lo puede cambiar él desde otro
        # aparato o el secretario por su acción (`modo_ingles`, C-0422), y el
        # botón «English» de esta pantalla decía lo de cuando se cargó.
        comun = {"espera": espera, "vivo": vivo, "permisos": permisos, "ingles": _conv.ingles(con)}
        h = _conv.hilo_abierto(con)
        if not h:
            return {"hilo": None, "turnos": [], **comun}
        return {"hilo": h["id"], "turnos": _conv.turnos(con, h["id"], desde), **comun}
    finally:
        con.close()


#: Lo anterior se pide por páginas: al cargar, una; con «Ver lo anterior»,
#: otra cada vez. 50 como mucho por petición, que es lo que pide quien busca
#: una conversación de la lista (C-0393).
ANTERIORES_POR_PAGINA = 30
ANTERIORES_TOPE = 50


def secretario_anteriores(antes_de: int = 0, n: int = ANTERIORES_POR_PAGINA) -> dict[str, Any]:
    """Lo ya hablado con el secretario, para releerlo en el chat (C-0393).

    Los `n` turnos de cualquier hilo que van justo antes de `antes_de` (el
    globo más viejo que ya está pintado; `<= 0` es «lo último»), de más viejo
    a más nuevo y con la misma forma que el sondeo (`conversacion.turnos`).
    `hilos` dice de cada hilo que sale cuándo se abrió, su título y si ya se
    cerró y resumió: el chat lo pone en el separador. `hay_mas`, si queda algo
    más atrás. Sólo lectura (`_memoria_para_pintar`): sin base, ilegible o de
    una versión anterior, vacío. 🔴 Nada de esto entra en la sesión del
    modelo, que sigue naciendo limpia en cada hilo (299)."""
    from .secretario import conversacion as _conv

    vacio: dict[str, Any] = {"turnos": [], "hilos": {}, "hay_mas": False}
    n = max(1, min(int(n), ANTERIORES_TOPE))
    con = _memoria_para_pintar()
    if con is None:
        return vacio
    try:
        # Uno de más para saber si queda algo atrás sin otra consulta.
        turnos = _conv.turnos(con, None, antes_de=antes_de if antes_de > 0 else None, n=n + 1)
        hay_mas = len(turnos) > n
        turnos = turnos[1:] if hay_mas else turnos
        ids = sorted({t["hilo"] for t in turnos})
        hilos = {}
        if ids:
            marcas = ",".join("?" * len(ids))
            for h in con.execute(f"SELECT id, titulo, abierto, cerrado, resumen FROM hilo WHERE id IN ({marcas})", ids):
                # Como toda fecha de pantalla (`reloj.cuando`, C-0396): la
                # pinta el JS en el separador, así que va ya formateada.
                hilos[str(h["id"])] = {"titulo": h["titulo"], "abierto_local": _hora_local(h["abierto"]),
                                       "cerrado": h["cerrado"] is not None, "resumido": bool(h["resumen"])}
        return {"turnos": turnos, "hilos": hilos, "hay_mas": hay_mas}
    finally:
        con.close()


def _segundos_desde(iso: str | None) -> float:
    from datetime import datetime as _dt, timezone as _tz
    try:
        return (_dt.now(_tz.utc) - _dt.fromisoformat(str(iso))).total_seconds()
    except (TypeError, ValueError):
        return float("inf")


def secretario_espera(hub: sqlite3.Connection | None = None,
                      mem: sqlite3.Connection | None = None) -> dict[str, Any] | None:
    """Lo que el secretario espera o tiene delegado y sigue vivo (C-0166, decisión 358).

    - `solicitudes`: las acciones que esperan el sí del dueño.
    - `resumenes`: los resúmenes de sesión en cola o leyéndose ahora, y
      `resumiendo` (0 o 1) el que se está leyendo.
    - `investigaciones`: lo que investiga en la web, en cola o ahora (385), e
      `investigando` (0 o 1) la que se está haciendo: comparten hilo con los
      resúmenes, así que una en cola puede estar esperando a uno.
    - `encargos`: sus tareas del orquestador (`origen == "secretario"`) en
      cola o vivas, con la sesión que trabaja cada una y los subagentes vivos
      de esa sesión, ya con su rol (`personaje.rol_de`).

    Es lo único que el personaje pinta como acompañantes: el secretario no
    tiene subagentes (301), y uno inventado sería una cifra indefendible
    (regla 13). Las sesiones de /trabajo no son suyas: tienen su punto en el
    raíl. `mem` es la memoria ya abierta (si no, se abre y se cierra aquí);
    sin `hub` no se miran sesiones. `None` si no hay secretario. Nunca lanza:
    lo pinta el raíl de todas las pantallas."""
    from .secretario import asuntos as _as, investigar as _inv, memoria as _mem, motor as _motor, sesiones as _ses

    propia = mem is None
    try:
        if propia:
            mem = _memoria_secretario()
        if mem is None:
            return None
        solicitudes = mem.execute("SELECT COUNT(*) FROM solicitud WHERE estado = 'pendiente'").fetchone()[0]
        en_cola = len(_mem.leer(mem, _ses.CLAVE) or [])
        en_curso = _mem.leer(mem, _ses.EN_CURSO)
        resumiendo = int(isinstance(en_curso, dict)
                         and _segundos_desde(en_curso.get("desde")) < _motor.TOPE_SEGUNDOS)
        investigaciones = len(_mem.leer(mem, _inv.CLAVE) or [])
        investigando = _mem.leer(mem, _inv.EN_CURSO)
        # Con su tope, no el de un turno (SEC-23): pasados 10 min seguía viva.
        investigando = int(isinstance(investigando, dict)
                           and _segundos_desde(investigando.get("desde")) < _inv.TOPE_S)
        asuntos = _cuenta_de_asuntos(_mem.leer(mem, _as.CLAVE_ESTADO))
    except sqlite3.Error:
        return None
    finally:
        if propia and mem is not None:
            mem.close()
    try:
        encargos = _encargos_del_secretario(hub)
    except Exception:  # noqa: BLE001 — una tarea ilegible no deja la pantalla sin raíl
        encargos = []
    # `resumiendo`, el que se lee ahora: los de la cola esperan, no trabajan (revisor).
    return {"solicitudes": int(solicitudes), "resumenes": en_cola + resumiendo, "resumiendo": resumiendo,
            "encargos": encargos, "investigaciones": investigaciones + investigando, "investigando": investigando,
            "asuntos": asuntos}


#: Las ideas del chat vacío de siempre: de reserva, cuando nada espera (UI-33).
IDEAS_CHAT = ("¿Qué tengo pendiente del trabajo?", "¿Qué se decidió en la última reunión?",
              "Recuérdame mañana a las 10 revisar los PR")


def _ideas_del_chat(*, solicitudes: int, nuevas: int, encargos: int) -> list[str]:
    """Por dónde empezar con el chat vacío (UI-33, C-0369): primero lo que hay
    hoy; las de siempre, de reserva. Tres, como antes. Pulsar una se la manda
    tal cual, así que van dichas como las diría el dueño. Lo vencido no: el
    dueño lo quiere sólo en Pendientes y en el parte (C-0373), y este chat sale
    en el panel de todas las pantallas."""
    ideas = []
    if solicitudes:
        ideas.append("¿Qué espera mi permiso?")
    if nuevas:
        ideas.append("¿Qué me espera que no haya visto?")
    if encargos:
        ideas.append("¿Cómo va lo que le encargaste al orquestador?")
    return (ideas + [i for i in IDEAS_CHAT if i not in ideas])[:3]


def secretario_ideas(espera: dict[str, Any] | None) -> list[str]:
    """Las ideas del chat vacío de lo que trae `secretario_espera`. Aparte y no
    dentro de ella: viaja en el `data-espera` de cada pantalla y en el sondeo
    de cada 6 s, y el personaje no las usa."""
    e = espera or {}
    return _ideas_del_chat(solicitudes=int(e.get("solicitudes") or 0),
                           nuevas=int((e.get("asuntos") or {}).get("nuevas") or 0),
                           encargos=len(e.get("encargos") or []))


def _cuenta_de_asuntos(cuenta: Any) -> dict[str, int]:
    """`{nuevas, total}` de la instantánea que deja `asuntos.recalcular`. La
    pantalla la sondea cada 6 s, así que no relee fuentes (380): sin
    instantánea todavía, cero, y el globo no sale."""
    if not isinstance(cuenta, dict):
        return {"nuevas": 0, "total": 0}
    try:
        return {"nuevas": max(0, int(cuenta.get("nuevas") or 0)), "total": max(0, int(cuenta.get("total") or 0))}
    except (TypeError, ValueError):
        return {"nuevas": 0, "total": 0}


# ─────────────────────── «Te espera»: los asuntos en pantalla ───────────────────────

#: Lo que se puede hacer con cada asunto desde su botón (decisión 381). Lo que
#: no está aquí se contesta por la puerta de su dueño, que la plantilla enlaza:
#: el permiso, en su solicitud; el orquestador, en `/orquestador/*`.
COMO_ASUNTO = ("anotar", "delegar", "preparar", "callar", "hecho", "reabrir", "contestar")

_TESTIGO = re.compile(r"[0-9a-f]{12}")


def secretario_asuntos(hub: sqlite3.Connection | None = None) -> dict[str, Any]:
    """El bloque «Te espera» de Pendientes (C-0201, decisiones 379-381).

    Lee por `asuntos.reunir`, en vivo de cada dueño, y a cada asunto le pone
    lo que se le ofrece (`como`): anotar, delegar o prepararlo, callarlo,
    contestarlo. Lo callado va aparte (`callados`), para reabrirlo; lo
    resuelto no sale. `fallos`, las fuentes que no se pudieron leer, dichas.
    `grupos`, los mismos `asuntos` como los pinta la pantalla
    (`_grupos_de_asuntos`, C-0368).

    Sin secretario, vacío y sin crear su carpeta (`_memoria_secretario`). Sin
    carpeta de tareas no se lee el orquestador: `orquestador.listar` la
    crearía, y una pantalla que sólo mira no deja carpetas."""
    from .secretario import asuntos as _as

    vacio: dict[str, Any] = {"asuntos": [], "grupos": [], "fichas": [], "callados": [], "fallos": [], "nuevas": 0}
    try:
        mem = _memoria_secretario()
    except sqlite3.Error as exc:
        return {**vacio, "fallos": [f"No pude abrir la memoria del secretario: {exc}"]}
    if mem is None:
        return vacio
    clases = tuple(c for c in _as.CLASES
                   if c != "orquestador" or (config.HUB_HOME / "orquestador" / "tareas").is_dir())
    try:
        r = _as.reunir(mem, hub=hub, clases=clases, todos=True)
    finally:
        mem.close()
    vivos = [a for a in r.asuntos if a.estado not in _as.APARTADAS]
    # Primero lo que pide un gesto suyo aquí mismo, y las fichas aparte y
    # plegadas: medido el 7-nov con su hub real, 51 fichas sin botones
    # empujaban fuera de la vista los bloqueos que sí se delegan.
    vivos.sort(key=_orden_asunto)
    vistas = [_vista_asunto(hub, a) for a in vivos if a.clase != "ficha"]
    return {"asuntos": vistas, "grupos": _grupos_de_asuntos(vistas),
            "fichas": [_vista_asunto(hub, a) for a in vivos if a.clase == "ficha"],
            "callados": [_vista_asunto(hub, a) for a in r.asuntos if a.estado == "callada"],
            # Con la regla del globo (`recalcular`: sin `SIN_GLOBO`): «Te espera: 4»
            # tiene que encontrar sus cuatro en la cabecera del bloque (C-0367).
            "fallos": r.fallos,
            "nuevas": sum(a.estado == "nueva" and a.clase not in _as.SIN_GLOBO for a in vivos)}


#: En qué orden salen en «Te espera»: primero lo que sólo él contesta
#: (`asuntos.SOLO_EL`), luego lo que le dice un proyecto y al final lo que se
#: pliega. Medido el 13-nov, lo del canal quedaba debajo de 24 filas de
#: bloqueos y vencidos (C-0368).
_ORDEN_ASUNTOS = ("relevo", "permiso", "navegante", "orquestador", "dato", "sesion", "canal", "proyecto",
                  "bloqueo", "vence", "ficha")


def _orden_asunto(a) -> int:
    clase = a["clase"] if isinstance(a, dict) else a.clase
    return _ORDEN_ASUNTOS.index(clase) if clase in _ORDEN_ASUNTOS else len(_ORDEN_ASUNTOS)


def _grupos_de_asuntos(vistas: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """«Te espera» como se pinta (C-0368): los bloqueos, uno por proyecto con
    su cuenta; lo que vence, un solo grupo con un solo enlace a «Compromisos
    abiertos»; lo demás, llano y abierto, como siempre. Pura, sin E/S.

    Qué se pliega no es otra lista: lo que ni sólo él contesta ni nace aquí
    (`CLASES - SOLO_EL - PROPIAS`). Un grupo de una fila no se pliega, y uno con
    algo nuevo llega abierto: llegar por el globo enseña lo nuevo y el primer
    gesto lo marca visto, igual que antes. Agrupar y contar no es gestión;
    ordenar por antigüedad o decir cuánto lleva, sí (regla dura 3): dentro de
    cada grupo el orden es el de su fuente."""
    from .secretario import asuntos as _as

    plegables = set(_as.CLASES) - _as.SOLO_EL - set(_as.PROPIAS)
    grupos: dict[str, dict[str, Any]] = {}
    for v in sorted(vistas, key=_orden_asunto):
        clase = v["clase"]
        clave = f"g:bloqueo:{v.get('proyecto') or v.get('origen') or ''}" if clase == "bloqueo" else f"g:{clase}"
        grupos.setdefault(clave, {"clave": clave, "clase": clase, "asuntos": []})["asuntos"].append(v)
    for g in grupos.values():
        filas, clase = g["asuntos"], g["clase"]
        n = len(filas)
        nuevas = sum(a.get("estado") == "nueva" for a in filas)
        plegado = clase in plegables and n > 1
        if clase == "bloqueo":
            nombre = filas[0].get("nombre") or filas[0].get("proyecto") or filas[0].get("origen") or ""
            titulo = f"{nombre} · {n} {'bloqueo' if n == 1 else 'bloqueos'}"
            enlace = filas[0].get("enlace") or ""
        elif clase == "vence":
            titulo = (f"{n} {'compromiso vencido' if n == 1 else 'compromisos vencidos'} o de hoy")
            enlace = "#compromisos"
        else:
            titulo, enlace = _as.ROTULOS.get(clase, clase), ""
        g.update(titulo=titulo, n=n, nuevas=nuevas, plegado=plegado, abierto=not plegado or nuevas > 0,
                 enlace=enlace)
    return list(grupos.values())


def secretario_asunto(hub: sqlite3.Connection | None, clave: str) -> dict[str, Any] | None:
    """Un asunto con lo que se le ofrece, como lo pinta «Te espera», si existe
    ahora (callado o no). Lo pide la web antes de actuar: el botón que llega
    tiene que ser uno que la pantalla ofrece hoy, no el de hace una hora.
    `ValueError` si la clave no es la de un asunto; `RuntimeError` si su
    fuente no se pudo leer."""
    from .secretario import asuntos as _as

    mem = _memoria_secretario()
    if mem is None:
        return None
    try:
        a = _as.buscar(mem, clave)
    finally:
        mem.close()
    return _vista_asunto(hub, a) if a is not None else None


def _vista_asunto(hub: sqlite3.Connection | None, a) -> dict[str, Any]:
    """Lo que la plantilla necesita de un asunto, y lo que se le ofrece.

    - permiso: la `solicitud` que pinta su macro de siempre;
    - orquestador: la `tarea`, y el `testigo` de su pregunta o el `conf_id`
      de su confirmación, para contestar por `/orquestador/*` sin aplicar la
      respuesta a otra pregunta que llegó después;
    - bloqueo: anotar, delegar o prepararlo (`asuntos.como_delegar`) y callar;
    - proyecto: contestar (le vuelve al proyecto), darlo por hecho y callar;
    - relevo: darlo por hecho (quien lo pidió no lee respuestas).

    `principal`, cuál de `como` encabeza la fila (C-0368): lo decide esto y no
    la plantilla, como qué se ofrece. Lo demás de `como` va a su menú.

    Un bloqueo se anota **o** se delega, una vez: el asunto guarda una sola
    marca y una sola `ref`, y anotar después de delegar borraba la tarea de la
    `ref` y volvía a ofrecer delegarlo —dos tareas para el mismo punto
    (revisor)—. La `ref` sobrevive a callar y reabrir (`marcar` sólo la pisa
    con otra), así que también tras reabrir se sabe qué se decidió."""
    from dataclasses import asdict

    from .secretario import asuntos as _as

    d = asdict(a)
    d.update(como=[], principal="", motivo="", solicitud=0, tarea="", testigo="", conf_id=0, proyecto="",
             que=a.texto, decidido="", rotulo=_as.ROTULOS.get(a.clase, a.clase))
    if a.estado == "callada":
        d["como"], d["principal"] = ["reabrir"], "reabrir"
        return d
    if a.clase == "permiso":
        d["solicitud"] = int(a.clave.split(":", 1)[1])
    elif a.clase == "orquestador":
        d["tarea"] = a.origen
        resto = a.clave[len(f"orquestador:{a.origen}:"):]
        if a.tipo == "confirmacion":
            d["conf_id"] = int(resto.rsplit(":", 1)[1])
        elif _TESTIGO.fullmatch(resto):
            # Las preguntas de antes del testigo no lo llevan: sin él, se
            # contesta la que haya, como desde /orquestador.
            d["testigo"] = resto
    elif a.clase == "bloqueo":
        # La misma regla que el modelo (`asuntos.como_delegar`, 381): con dos,
        # uno delegaba lo que el otro no.
        dl = _as.como_delegar(a, hub=hub)
        decidido = a.estado in _as.DECIDIDAS or bool(a.ref)
        d.update(proyecto=dl.proyecto, nombre=dl.nombre, punto=dl.punto, que=f"{dl.nombre}: {dl.punto}",
                 motivo="" if decidido else dl.motivo,
                 como=[c for c in ("anotar", dl.como, "callar") if c and not (decidido and c == "anotar")])
        if decidido:
            d["decidido"] = ("delegado" if a.estado == "delegada" or a.ref.startswith("t-")
                             or a.ref == _as.DELEGANDO else "anotado")
        # Lo que `como_delegar` ofrece; si no ofrece nada, anotarlo.
        d["principal"] = next((c for c in (dl.como, "anotar") if c and c in d["como"]), "")
    elif a.clase == "proyecto":
        d["como"], d["principal"] = ["contestar", "hecho", "callar"], "contestar"
    elif a.clase == "relevo":
        # Quien pidió el relevo no lee respuestas: lo que se hace es en la PC,
        # y «Hecho» es lo que hay que decir (388).
        d["como"], d["principal"] = ["hecho"], "hecho"
    return d


def _encargos_del_secretario(hub: sqlite3.Connection | None) -> list[dict[str, Any]]:
    from . import orquestador as _orq

    # Sin carpeta de tareas no se crea una por mirar: `listar` la haría.
    if not (config.HUB_HOME / "orquestador" / "tareas").is_dir():
        return []
    out = []
    for t in _orq.listar():
        if t.get("origen") != "secretario" or t.get("estado") not in (*_orq.VIVAS, _orq.EN_COLA):
            continue
        out.append({"id": t["id"], "estado": t["estado"], "pedido": " ".join(str(t.get("pedido") or "").split())[:90],
                    "sesiones": _sesiones_del_encargo(hub, t) if hub is not None else []})
    return out


def _sesiones_del_encargo(hub: sqlite3.Connection, tarea: dict[str, Any]) -> list[dict[str, Any]]:
    """Las sesiones a las que la tarea mandó trabajo y aún espera, con sus
    subagentes vivos. Del último muestreo (qué conversación corre en cada
    panel) y de los transcripts: nunca tmux en vivo desde la pantalla."""
    paneles = {p["pane_id"]: p for p in paneles_abiertos(hub)}
    out, vistos = [], set()
    for e in tarea.get("esperas") or []:
        panel = paneles.get(e.get("pane_id"))
        if e.get("estado") != "esperando" or not panel or e["pane_id"] in vistos:
            continue
        vistos.add(e["pane_id"])
        out.append({"proyecto": e.get("proyecto") or panel.get("proyecto_id") or "",
                    "nombre": panel.get("slot_nombre") or panel.get("etiqueta") or e.get("proyecto") or "",
                    "subagentes": _subagentes_de(panel)})
    return out


def _subagentes_de(panel: dict[str, Any]) -> list[dict[str, Any]]:
    """Los subagentes vivos de la conversación que corre en un panel, con su
    rol (358). Del último muestreo (qué conversación) y de los transcripts:
    nunca tmux en vivo desde la pantalla. Lo usan los acompañantes del
    secretario y los talleres (C-0220)."""
    from .secretario import personaje as _pj

    sesion = panel.get("claude_sesion") or ""
    if not sesion:
        return []
    ruta = (transcripts.ruta_de_sesion(sesion, [transcripts.directorio_de(panel.get("cwd") or "")])
            or transcripts.ruta_de_sesion(sesion))
    if not ruta:
        return []
    return [{"id": s["id"], "rol": _pj.rol_de(s["tipo"]), "tipo": s["tipo"], "inicial": _pj.inicial(s["tipo"]),
             "que": s["que"]} for s in transcripts.subagentes_vivos(ruta)]


#: Cómo se ordenan los talleres: lo que te espera, primero (C-0220).
_ORDEN_TALLER = {"espera": 0, "trabajando": 1, "delegando": 1, "quieta": 2, "neutro": 3}


def talleres(con: sqlite3.Connection) -> dict[str, Any]:
    """Cada sesión con agente del último muestreo es un taller (C-0220, 391).

    Sólo lectura y sólo de lo guardado: qué agente corre lo dice
    `tui.reconocer` sobre el comando y el título del panel (una shell con el
    glifo heredado no es un taller, 261), y su estado, `estado_de_panel`
    —trabajando, por el título o por la pantalla (393), o detenido, que aquí
    es «quieta»— más `avisos.preguntando` cuando el relé midió un cuadro de
    permisos («espera»). Codex no pinta estado en el título: trabajando lo
    dice su pantalla y, si no, va «neutro», porque no se distingue parado de
    esperando (regla 13).

    Cada taller lleva `clave` (`pane_id` + conversación: tmux recicla los
    ids) y sus subagentes con su estación (`talleres.estacion_de`).
    `tomado_en` es la hora de la muestra: la página no pinta como de ahora
    una muestra vieja. `escena` es la tabla del dibujo (`talleres.escena`)."""
    from . import avisos as _avisos, talleres as _talleres, tui

    actual = snapshot_actual(con)
    escena = _talleres.escena()
    if not actual:
        return {"talleres": [], "tomado_en": None, "escena": escena}
    try:
        piden = _avisos.preguntando(con)
    except sqlite3.Error:
        piden = set()
    out = []
    for p in paneles_de(con, actual["id"]):
        agente = tui.reconocer(p.get("comando") or "", p.get("titulo") or "")
        if agente is None:
            continue
        estado = {"trabajando": "trabajando", "detenido": "quieta"}.get(estado_de_panel(p), "neutro")
        if estado == "quieta" and p["pane_id"] in piden:
            estado = "espera"
        subagentes = [{**s, "estacion": _talleres.estacion_de(s["rol"])} for s in _subagentes_de(p)]
        # Quieta en el yunque, pero con subagentes vivos: está delegando, y
        # eso es trabajar. Con siete en marcha la pantalla decía «0
        # trabajando» y «quieta» (C-0298). `tui.ocupado` no cambia (393): es
        # otra señal que se suma; si además pide permiso, manda la espera.
        if estado in ("quieta", "neutro") and subagentes:
            estado = "delegando"
        out.append({
            "clave": f"{p['pane_id']}:{p.get('claude_sesion') or ''}",
            "agente": agente.nombre,
            "proyecto": p.get("proyecto_nombre") or p.get("proyecto_id") or "",
            "nombre": p.get("slot_nombre") or p.get("etiqueta") or f"{p['session']}:{p['window_idx']}",
            "ventana": f"ventana {p['window_idx']}",
            "estado": estado,
            "subagentes": subagentes,
        })
    # Dos talleres que se titulan igual no se distinguen: llevan su ventana.
    repetidos = Counter((t["proyecto"], t["nombre"]) for t in out)
    for t in out:
        if repetidos[(t["proyecto"], t["nombre"])] > 1:
            t["nombre"] = f"{t['nombre']} · {t['ventana']}"
    out.sort(key=lambda x: (_ORDEN_TALLER[x["estado"]], x["proyecto"], x["nombre"]))
    return {"talleres": out, "tomado_en": actual["tomado_en"], "escena": escena}


def personaje_catalogo() -> dict[str, Any]:
    """Todo lo que el personaje sabe enseñar, para su galería (C-0166), y
    entre quiénes se elige (C-0188). Cuál está elegido lo trae `secretario()`."""
    from .secretario import personaje as _pj
    return {"estados": [{"id": k, "nombre": n, "cuando": c} for k, (n, c) in _pj.ESTADOS.items()],
            "gestos": [{"id": k, "nombre": n} for k, n in _pj.GESTOS.items()],
            "roles": [{"id": k, "nombre": n, "que": q} for k, (n, q) in _pj.ROLES.items()],
            "personajes": [personaje_vista(k) for k in _pj.PERSONAJES]}


def nombre_secretario(con: sqlite3.Connection | None = None) -> str:
    """Cómo se llama el secretario (C-0226): lo puesto en Ajustes → Personaje,
    o «Secretario». Con su memoria abierta, de ahí; sin ella —el raíl, el
    manifiesto—, en sólo lectura y sin crearla (C-0099): una instalación sin
    secretario todavía no tiene memoria, y eso es «Secretario», no un error."""
    from .secretario import memoria as _mem, personaje as _pj
    if con is not None:
        return _pj.nombre_de(_mem.leer(con, _pj.CLAVE_NOMBRE))
    try:
        return _pj.nombre_de(_mem.leer_sin_abrir(_pj.CLAVE_NOMBRE))
    except sqlite3.Error:
        return _pj.NOMBRE_POR_OMISION


def personaje_vista(valor: Any = None) -> dict[str, str]:
    """Lo que la plantilla necesita de un personaje: su id (lo que no está en
    el catálogo es el de por omisión), su nombre, su familia y su hoja."""
    from .secretario import personaje as _pj
    pid = _pj.elegido(valor)
    nombre, familia = _pj.PERSONAJES[pid]
    return {"id": pid, "nombre": nombre, "familia": familia, "hoja": _pj.hoja(pid)}


def voz_estado(gpu: bool = False, solo_eleccion: bool = False, solo_descarga: bool = False) -> dict:
    """El modelo del dictado (C-0313): cuál eligió, cuáles hay descargados,
    qué tiene cargado el servidor, la descarga en curso o la última (C-0505)
    y, con `gpu`, la memoria de la GPU medida al momento. Lo lee el menú
    junto a cada micrófono al abrirse; cerrado, sólo lo elegido
    (`solo_eleccion`), que no lanza nada. Mientras baja un modelo, el menú
    abierto pregunta `solo_descarga`, que sólo lee dos archivos."""
    from . import transcribir
    if solo_eleccion:
        return transcribir.eleccion_dictado()
    if solo_descarga:
        return {"descarga": transcribir.descarga()}
    return transcribir.estado_dictado(gpu=gpu)


def banco_dictado(aparato: str | None = None) -> dict:
    """Lo que enseña `/voz/banco` (C-0312): las frases, qué está grabado en
    cada aparato, la frase por la que seguir y las últimas medidas. Sólo lee
    `HUB_HOME/voz/banco/`; grabar va por `banco_dictado.guardar`."""
    from . import banco_dictado as _banco
    aparato = aparato if aparato in _banco.APARATOS else _banco.APARATOS[0]
    hechas = _banco.grabadas()
    frases = [{"id": f["id"], "categoria": f["categoria"], "texto": f["texto"],
               "grabada": {a: (a, f["id"]) in hechas for a in _banco.APARATOS}} for f in _banco.frases()]
    progreso = {a: _banco.progreso(a) for a in _banco.APARATOS}
    actual = progreso[aparato]
    frase = next((f for f in frases if f["id"] == actual["siguiente"]), frases[0] if frases else None)
    return {"aparato": aparato, "hechas": actual["hechas"], "total": actual["total"], "frase": frase,
            "aparatos": [{"id": a, "nombre": _banco.NOMBRES_APARATO[a], **progreso[a]} for a in _banco.APARATOS],
            "frases": frases, "categorias": dict(_banco.CATEGORIAS), "congelada": _banco.congelada(),
            "resultados": _banco.resultados(5)}
