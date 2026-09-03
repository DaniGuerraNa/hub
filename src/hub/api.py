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

import sqlite3
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from . import base
from . import repos as _repos
from . import tmux
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


def listar_proyectos(con: sqlite3.Connection, dominio: str | None = None) -> list[dict]:
    sql = "SELECT * FROM proyecto WHERE status != 'archivado'"
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
    fila = con.execute(
        "SELECT * FROM snapshot WHERE preservado = 0 ORDER BY id DESC LIMIT 1"
    ).fetchone()
    return _fila_a_dict(fila) if fila else None


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
    """
    fila = con.execute(
        "SELECT * FROM snapshot WHERE preservado = 1 ORDER BY id DESC LIMIT 1"
    ).fetchone()
    if not fila:
        return None
    datos = _fila_a_dict(fila)
    datos["paneles"] = paneles_de(con, fila["id"])
    datos["proyectos"] = sorted(
        {p["proyecto_nombre"] for p in datos["paneles"] if p["proyecto_nombre"]}
    )
    return datos


def marcar_recuperacion_revisada(con: sqlite3.Connection, snapshot_id: int) -> None:
    con.execute("UPDATE snapshot SET preservado = 2 WHERE id = ?", (snapshot_id,))


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
    """
    if panel is None:
        return "cerrado"
    titulo = panel.get("titulo") or ""
    if tmux.es_spinner(titulo):
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
    paneles = paneles_abiertos(con)
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

    proyectos = listar_proyectos(con)
    for p in proyectos:
        p["slots"] = slots_de(con, p["id"])
        for s in p["slots"]:
            s["estado"] = estado_de_panel(panel_por_slot.get(s["id"]))
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
        panel = panel_de_slot(con, slot["id"])
        if panel:
            session = panel["session"]
            ventana = panel["window_idx"]
        else:
            ventana = None
        slot["abierto"] = panel is not None

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
    }


def rail(con: sqlite3.Connection) -> dict:
    """Lo que necesita el raíl global, que sale en TODAS las pantallas.

    Los proyectos van con su estado y sus commits en riesgo porque el raíl deja
    de ser sólo navegación: es la respuesta a «¿hay algo parado o sin respaldar?»
    sin entrar en ninguna pantalla.

    Se piden pocos datos y baratos a propósito. Esto corre en cada petición,
    incluida `/trabajo`, donde una consulta lenta se nota al abrir el terminal.
    """
    sin_push: dict[str, int] = {}
    for r in _repos.deduplicar([_fila_a_dict(f) for f in con.execute("SELECT * FROM repo")]):
        if r.get("sin_push"):
            sin_push[r["proyecto_id"]] = sin_push.get(r["proyecto_id"], 0) + int(r["sin_push"])

    abiertos: dict[str, int] = {}
    paneles = paneles_abiertos(con)
    for panel in paneles:
        if panel["proyecto_id"]:
            abiertos[panel["proyecto_id"]] = abiertos.get(panel["proyecto_id"], 0) + 1

    # El raíl lista lo que está PASANDO, no el catálogo entero. Con los once
    # proyectos registrados dejaba de ser navegación y pasaba a ser otra lista
    # que recorrer — y la mitad no tenían nada abierto. Entra un proyecto si
    # tiene paneles abiertos, commits en riesgo, o es el que estás mirando.
    # Para el resto están el panorama y la paleta (Ctrl+K).
    proyectos = []
    ocultos = 0
    for p in listar_proyectos(con):
        activo = abiertos.get(p["id"], 0)
        riesgo = sin_push.get(p["id"], 0)
        if not activo and not riesgo:
            ocultos += 1
            continue
        proyectos.append({
            "id": p["id"], "nombre": p["nombre"], "status": p["status"],
            "sin_push": riesgo, "paneles": activo,
        })
    # Lo que pide atención, arriba.
    proyectos.sort(key=lambda x: (-x["sin_push"], -x["paneles"], x["nombre"].lower()))

    corriendo = con.execute(
        "SELECT COUNT(*) FROM servicio WHERE estado = 'running'"
    ).fetchone()[0]
    # ¿Hay algún proyecto declarado con `tipo: asistente`? Sin él no hay chat que
    # abrir, y pintar su pestaña sería ofrecer algo que sólo puede fallar: el
    # error aparecía al pulsarla, que es el peor momento para enterarse.
    hay_asistente = bool(
        con.execute("SELECT 1 FROM proyecto WHERE tipo = 'asistente' LIMIT 1").fetchone()
    )
    # Un hub recién instalado no tiene nada que enseñar. Es dato del raíl porque
    # la guía de arranque sale en la portada y depende de lo mismo que él.
    total_proyectos = con.execute(
        "SELECT COUNT(*) FROM proyecto WHERE tipo != 'asistente'"
    ).fetchone()[0]
    return {
        "proyectos": proyectos,
        # Se dice cuántos no salen: una lista que esconde en silencio se lee
        # como la lista completa.
        "ocultos": ocultos,
        "sin_respaldo": sum(sin_push.values()),
        "servicios": corriendo,
        "paneles": len(paneles),
        "hay_asistente": hay_asistente,
        "total_proyectos": total_proyectos,
    }


def clasificar_sesiones(
    sesiones: list[dict], paneles: list[dict], session_actual: str | None = None
) -> tuple[list[dict], list[dict]]:
    """Separa las sesiones de tmux en pendientes de organizar y ya organizadas.

    La lista de la barra es una **bandeja**: enseña lo que todavía no está
    atado a un slot. Sin esto, una sesión ya vinculada seguía apareciendo junto
    a su propio slot y se leía como un duplicado.

    El criterio es por VENTANA, no por sesión, y eso importa: `work` tiene la
    ventana 0 en un slot y la 1 suelta. Ocultar la sesión entera al vincular la
    primera ventana dejaría a la 1 sin ningún camino para llegar a ella.
    Pendiente = le queda al menos una ventana sin slot.

    La sesión que se está mirando nunca se oculta: verla desaparecer de la barra
    en el momento de vincularla es desorientador, y además es la única entrada
    a sus otras ventanas.
    """
    sueltas: dict[str, int] = {}
    todas: dict[str, set] = {}
    for p in paneles:
        todas.setdefault(p["session"], set()).add(p["window_idx"])
        if not p["slot_id"]:
            sueltas.setdefault(p["session"], set()).add(p["window_idx"])

    pendientes, organizadas = [], []
    for s in sesiones:
        nombre = s["session"]
        sin_slot = len(sueltas.get(nombre, set()))
        anotada = {
            **s,
            "ventanas": len(todas.get(nombre, set())),
            "sin_slot": sin_slot,
        }
        # Una sesión que el snapshotter aún no ha visto no tiene paneles
        # conocidos: tratarla como organizada la escondería sin haberla mirado.
        desconocida = nombre not in todas
        if sin_slot or desconocida or nombre == session_actual:
            pendientes.append(anotada)
        else:
            organizadas.append(anotada)
    return pendientes, organizadas


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
    """
    paneles = paneles_abiertos(con)
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

    return {"slots": estados, "notas": notas}


def bandeja(con: sqlite3.Connection) -> list[dict]:
    """Paneles abiertos sin slot y no descartados.

    Elimina la disciplina en el momento de abrir un panel: no hay que etiquetar
    nada al arrancar y aun así nada se pierde (decisión 15).
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
    return [
        p
        for p in paneles_de(con, actual["id"])
        if p["slot_id"] is None and p["pane_id"] not in descartados
    ]


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


def prompt_mantenedor(
    kit_nombre: str, consumidor: str, deriva: int, divergencias: int,
    mantenimiento: dict | None = None,
) -> str:
    """Propuesta editable, no una orden.

    Lleva la medición dentro para que el agente no tenga que redescubrirla, y
    empieza por verificar en vez de por aplicar: el sistema propone, el usuario
    decide.

    🔴 Tres cosas que estaban mal y se arreglan juntas porque son la misma:
    este texto era fijo y no leía nada del manifiesto.

    - Mandaba usar «el agente mantenedor de X», que está **abolido** —el
      procedimiento vive una vez, en la skill `mantener-kit`, no repetido en un
      agente por kit—. Ahora nombra la skill.
    - Remitía a «su ficha de `consumidores/`», el formato anterior a `kit.yml`
      que `aplica:` sustituyó.
    - E ignoraba `mantenimiento.notas` y `mantenimiento.verificar`, que el kit
      declara justo para esto: se parseaban y no los leía nadie.
    """
    estado = (
        f"El hub midió {deriva} archivo(s) con deriva real"
        if deriva
        else "El hub no detectó deriva (todos los archivos mapeados coinciden)"
    )
    partes = [
        f"Sigue la skill `mantener-kit` para revisar el consumidor «{consumidor}» "
        f"del kit {kit_nombre}.",
        "",
        f"{estado} y {divergencias} divergencia(s) declarada(s) por el propio "
        "consumidor en su `.claude/hub/kits.yml`.",
    ]

    mantenimiento = mantenimiento or {}
    if notas := str(mantenimiento.get("notas") or "").strip():
        partes += ["", "Lo que este kit avisa a quien lo mantiene:", "", notas]
    if gancho := str(mantenimiento.get("verificar") or "").strip():
        partes += ["", f"Y trae su propia comprobación: ejecuta `{gancho}` "
                       "desde la raíz del kit."]

    partes += [
        "",
        "Antes de tocar nada: verifica la medición por tu cuenta y contrasta las "
        "divergencias declaradas contra la realidad — pueden estar obsoletas. "
        "Repórtame qué encontraste y qué propones antes de aplicar cambios.",
    ]
    return "\n".join(partes)


def kits(con: sqlite3.Connection) -> list[dict]:
    """Kits con sus consumidores y el estado real de cada archivo propagado."""
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
                    "prompt_mantenedor": prompt_mantenedor(
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
    for r in repos:
        r["cuenta_en_total"] = r["ruta"] in rutas_unicas
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
        # Sin git no hay medición posible, y un «0 commits sin respaldo» que en
        # realidad significa «no he mirado» es la peor cifra que este hub puede
        # enseñar. La pantalla lo dice en vez de dar el cero por bueno.
        "hay_git": _repos._hay_git(),
        # Para el selector: los proyectos que TIENEN repos, no todos. Ofrecer
        # veinte opciones de las que quince dan una lista vacía no es un filtro,
        # es una trampa.
        "proyectos": [
            p for p in listar_proyectos(con)
            if p["id"] in {r["proyecto_id"] for r in repos_de(con)}
        ],
    }


# ───────────────────────── servicios y conexiones ─────────────────────────


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
    return {
        "contenedores": filas,
        "total": len(filas),
        "vivos": sum(1 for f in filas if f["estado"] == "running"),
        # Un contenedor sin dueño es la clase de cosa que lleva meses parada y
        # nadie sabe si se puede borrar. En el inventario que originó esto había
        # uno detenido desde hacía cuatro meses y sin dueño conocido.
        "sin_atribuir": [f for f in filas if not f["proyecto_id"]],
        "medido_en": max((f["medido_en"] for f in filas), default=None),
        # Igual que en respaldo: sólo los proyectos que tienen contenedores.
        "proyectos": [
            p for p in listar_proyectos(con)
            if p["id"] in {
                r["proyecto_id"] for r in con.execute("SELECT proyecto_id FROM servicio")
            }
        ],
    }


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


# ───────────────────────── estado y capa base ─────────────────────────


def estado_de(con: sqlite3.Connection, proyecto_id: str) -> dict:
    """El documento vigente de un proyecto, resuelto y resumido."""
    datos = obtener_proyecto(con, proyecto_id)
    return base.estado_de(_a_modelo(datos)) if datos else {}


def capa_base(con: sqlite3.Connection, proyecto_id: str) -> dict:
    datos = obtener_proyecto(con, proyecto_id)
    if not datos:
        return {}
    proyecto = _a_modelo(datos)
    capa = base.capa_de(proyecto)
    capa["prompt_sembrar"] = base.prompt_sembrar(proyecto)
    return capa


# ───────────────────────── contexto completo ─────────────────────────


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
    lineas += [
        f"{c['servicios']['vivos']}/{c['servicios']['total']} contenedores corriendo · "
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


def resumen(con: sqlite3.Connection) -> dict:
    """Lo que necesita la pantalla principal, en una sola llamada."""
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
        "recuperacion": recuperacion_pendiente(con),
        "respaldo": respaldo(con),
        "servicios": servicios(con),
    }
