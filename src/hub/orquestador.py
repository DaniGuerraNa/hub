"""El orquestador: un agente transversal que le pide trabajo a las sesiones.

Lo pidió así: *«un agente que sea transversal, que pueda moverse a N proyectos;
no que él lo haga directamente, sino que gestione los proyectos»*. Recibe una
tarea, la parte en pasos, **le manda cada paso a la sesión de Claude Code del
proyecto que toca**, espera, lee lo que contestó y decide el siguiente. El plan
y lo que decidió el dueño están en `PLAN-ORQUESTADOR.md`; las decisiones, en
`ARQUITECTURA.md` desde la 254.

🔴 **El hub sigue sin escribir dentro de los proyectos, y el orquestador
tampoco.** Su `settings.json` le niega Edit y Write, y lo único que ejecuta es
`./orq`. Quien cambia algo en un proyecto es la sesión de ese proyecto, con sus
kits y sus guardrails. Lo que cambia es la decisión 69: un agente del hub ya no
sólo lee los proyectos, también **le pide trabajo a sus sesiones** (254).

🔴 **La memoria vive en disco, no en su contexto** (255). Una tarea es una
carpeta con `tarea.json`, `plan.md` y `bitacora.jsonl`. El orquestador se
despierta, lee su tarea, da un paso, lo apunta y termina el turno; así una
tarea de horas no le llena el contexto y sobrevive a un reinicio o a un
apagón. SQLite no guarda nada de esto (regla dura 1): no hay nada que
reconstruir porque nunca estuvo sólo ahí.

🔴 **Los permisos los comprueba este módulo, no su prompt** (256). El alcance
—a qué proyectos llega— es una cerradura: `./orq` se niega. El nivel de
decisión es un **pacto**: va escrito en cada mensaje a la sesión y lo cumplen
dos modelos. Con las sesiones en skip permissions no hay nada debajo que frene,
y decir otra cosa sería prometer más de lo que se cumple.
"""

from __future__ import annotations

import contextlib
import fcntl
import json
import re
import shlex
import shutil
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

import yaml

from . import asistente, config, entrega, modelos, tmux, tui

# 🔴 Sin el prefijo `hub-`: es el de las sesiones espejo de la terminal
# (`tmux.PREFIJO_ESPEJO`), y `listar_paneles` las excluye. Con ese nombre,
# `localizar()` no encontraba nunca al orquestador vivo, lo daba por caído y la
# bomba abría otro en cada latido: el primer ensayo real acabó con dos
# orquestadores trabajando la misma tarea.
SESION = "orq-hub"
VENTANA = "orquestador"

# ─────────────────────────────── permisos ───────────────────────────────────

NIVELES = ("nada", "bajo", "medio", "alto")

# Ambiguos a propósito y dicho por él: *«es el alcance que podemos tener por
# ahora, no contamos con el tiempo para definir una matriz de permisos por
# proyecto»*. Por eso se describen por TIPO de acción, que es lo que un modelo
# puede aplicar, y no con un «alto/medio» que cada uno leería a su manera.
DESCRIPCION = {
    "nada": "el orquestador no llega a este proyecto",
    "bajo": "haz sólo lo que se pide al pie de la letra; ante cualquier "
            "bifurcación, para y dilo en tu resumen",
    "medio": "decide tú lo técnico y reversible (tests, entornos de prueba, "
             "ramas, builds); lo irreversible, lo que sale hacia fuera y las "
             "decisiones de producto, no: dilo en tu resumen",
    "alto": "decide tú todo lo que haga falta para terminarlo, salvo la lista "
            "de «nunca sin el dueño»",
}

# Lo que ningún nivel desbloquea. La lista es suya, tal cual la aprobó.
SIEMPRE_DEL_DUENO = (
    "desplegar a producción",
    "hacer push a main",
    "borrar datos",
    "cualquier cosa que llegue a un cliente o a un tercero",
    "gastar dinero",
)


def permisos_yml() -> Path:
    """Aparte de `projects.yml` y fuera de la carpeta del orquestador.

    Fuera de su carpeta porque es lo único que él no debe poder tocar: si el
    archivo que dice hasta dónde llega viviera donde trabaja, un día se
    concedería a sí mismo un nivel. No puede escribir en ningún sitio —Edit y
    Write denegados—, pero la distancia es la segunda cerradura.
    """
    return config.HUB_HOME / "orquestador-permisos.yml"


def leer_permisos() -> dict[str, str]:
    ruta = permisos_yml()
    if not ruta.is_file():
        return {}
    try:
        datos = yaml.safe_load(ruta.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        # En voz alta (regla 21), y sin conceder nada: un archivo roto no puede
        # leerse como «todos a nada» en silencio ni, peor, como otra cosa.
        raise ValueError(f"{ruta} no es YAML válido: {exc}") from exc
    proyectos = datos.get("proyectos") or {}
    return {
        str(pid): str((valor or {}).get("nivel") if isinstance(valor, dict) else valor)
        for pid, valor in proyectos.items()
        if str((valor or {}).get("nivel") if isinstance(valor, dict) else valor) in NIVELES
    }


def fijar_nivel(proyecto_id: str, nivel: str) -> None:
    """Sólo lo llama la web. Ninguna orden de `./orq` escribe aquí."""
    if nivel not in NIVELES:
        raise ValueError(f"nivel desconocido: {nivel}. Son: {', '.join(NIVELES)}")
    actuales = leer_permisos()
    if nivel == "nada":
        actuales.pop(proyecto_id, None)
    else:
        actuales[proyecto_id] = nivel
    ruta = permisos_yml()
    ruta.parent.mkdir(parents=True, exist_ok=True)
    cuerpo = (
        "# Hasta dónde llega el orquestador en cada proyecto. Lo edita la pantalla\n"
        "# /orquestador; un proyecto que no está aquí es «nada».\n"
        + yaml.safe_dump({"proyectos": {p: {"nivel": n} for p, n in sorted(actuales.items())}},
                         allow_unicode=True, sort_keys=False)
    )
    tmp = ruta.with_suffix(".yml.tmp")
    tmp.write_text(cuerpo, encoding="utf-8")
    tmp.replace(ruta)


def nivel_de(con: sqlite3.Connection, proyecto_id: str) -> str:
    """El nivel que rige de verdad. `never` en `projects.yml` gana siempre.

    Regla dura 7: el guardrail `never` significa nunca, aunque la petición venga
    del dueño en la UI. Aquí la petición viene de un agente, así que con más razón.
    """
    fila = con.execute(
        "SELECT guardrail FROM proyecto WHERE id = ?", (proyecto_id,)
    ).fetchone()
    if not fila:
        return "nada"
    if fila["guardrail"] == "never":
        return "nada"
    return leer_permisos().get(proyecto_id, "nada")


class SinPermiso(PermissionError):
    """El orquestador no llega a ese proyecto. Lleva el motivo."""


def exigir(con: sqlite3.Connection, proyecto_id: str) -> str:
    nivel = nivel_de(con, proyecto_id)
    if nivel == "nada":
        raise SinPermiso(
            f"no tienes alcance sobre «{proyecto_id}». Sólo el dueño lo concede, en "
            "el hub → Orquestador → Permisos. No lo intentes por otro camino: "
            "pregúntale con `./orq preguntar` si hace falta."
        )
    return nivel


# ─────────────────────────────── las tareas ─────────────────────────────────

EN_COLA = "en-cola"
ACTIVA = "activa"
ESPERANDO_SESION = "esperando-sesion"
ESPERANDO_DUENO = "esperando-dueno"
TERMINADA = "terminada"
DETENIDA = "detenida"

VIVAS = (ACTIVA, ESPERANDO_SESION, ESPERANDO_DUENO)
CERRADAS = (TERMINADA, DETENIDA)

ETIQUETA = {
    EN_COLA: "en cola",
    ACTIVA: "trabajando",
    ESPERANDO_SESION: "esperando a una sesión",
    ESPERANDO_DUENO: "esperando tu respuesta",
    TERMINADA: "terminada",
    DETENIDA: "detenida",
}

_ID_TAREA = re.compile(r"^t-\d{6}-\d{6}(-\d+)?$")


def carpeta() -> Path:
    ruta = config.HUB_HOME / "orquestador"
    ruta.mkdir(parents=True, exist_ok=True)
    return ruta


def _tareas() -> Path:
    ruta = carpeta() / "tareas"
    ruta.mkdir(parents=True, exist_ok=True)
    return ruta


def ahora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _momento(valor: str | None) -> datetime:
    fecha = datetime.fromisoformat(valor or ahora())
    return fecha if fecha.tzinfo else fecha.replace(tzinfo=timezone.utc)


def _segundos_desde(valor: str | None) -> float:
    return (datetime.now(timezone.utc) - _momento(valor)).total_seconds()


@contextlib.contextmanager
def _candado() -> Iterator[None]:
    """Un candado para todas las tareas, y es a propósito uno solo.

    Escriben tres procesos —el CLI del orquestador, el snapshotter que lo
    despierta y la web desde la que el dueño contesta o detiene— y lo hacen pocas
    veces por minuto. Un candado por tarea no compraría nada y abriría la
    carrera de activar dos a la vez.
    """
    ruta = carpeta() / ".candado"
    with ruta.open("a") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def _estado_de(tarea: dict[str, Any]) -> str:
    """El estado de una tarea viva, deducido de lo que tiene pendiente.

    Deducido y no asignado a mano en cada sitio: en el primer ensayo real el
    orquestador preguntó y, sin esperar, mandó trabajo a una sesión; `mandar`
    pisó «esperando tu respuesta» con «esperando a una sesión» y la respuesta
    del dueño se rechazaba por estar en el estado equivocado. Una pregunta
    abierta manda sobre todo lo demás, porque es lo único que pide a una persona.
    """
    if tarea.get("pregunta"):
        return ESPERANDO_DUENO
    if tarea.get("despertar"):
        return ACTIVA
    if any(e["estado"] == "esperando" for e in tarea.get("esperas", [])):
        return ESPERANDO_SESION
    return ACTIVA


def dir_de(tarea_id: str) -> Path:
    if not _ID_TAREA.match(tarea_id or ""):
        # Viene de una URL o de un argumento del agente: sin validar, `../` sale
        # de la carpeta de tareas.
        raise ValueError(f"id de tarea no válido: {tarea_id!r}")
    return _tareas() / tarea_id


def _leer(tarea_id: str) -> dict[str, Any] | None:
    try:
        return json.loads((dir_de(tarea_id) / "tarea.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _escribir(tarea: dict[str, Any]) -> None:
    destino = dir_de(tarea["id"]) / "tarea.json"
    tmp = destino.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(tarea, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(destino)   # atómico: un apagón nunca deja media tarea


def cargar(tarea_id: str) -> dict[str, Any] | None:
    return _leer(tarea_id)


@contextlib.contextmanager
def editar(tarea_id: str) -> Iterator[dict[str, Any]]:
    with _candado():
        tarea = _leer(tarea_id)
        if tarea is None:
            raise ValueError(f"no hay ninguna tarea «{tarea_id}»")
        yield tarea
        _escribir(tarea)


def anotar(tarea_id: str, tipo: str, texto: str, **extra: Any) -> None:
    """Una línea en la bitácora. Sólo se añade: lo que pasó, pasó.

    Es lo que el dueño mira para saber qué se pidió a quién en su nombre, así que
    no se reescribe nunca, ni siquiera para corregir.
    """
    linea = {"cuando": ahora(), "tipo": tipo, "texto": texto, **extra}
    with (dir_de(tarea_id) / "bitacora.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(linea, ensure_ascii=False) + "\n")


def bitacora(tarea_id: str) -> list[dict[str, Any]]:
    ruta = dir_de(tarea_id) / "bitacora.jsonl"
    if not ruta.is_file():
        return []
    lineas = []
    for crudo in ruta.read_text(encoding="utf-8").splitlines():
        with contextlib.suppress(ValueError):
            lineas.append(json.loads(crudo))
    return lineas


def plan(tarea_id: str) -> str:
    ruta = dir_de(tarea_id) / "plan.md"
    return ruta.read_text(encoding="utf-8") if ruta.is_file() else ""


def guardar_plan(tarea_id: str, texto: str) -> None:
    (dir_de(tarea_id) / "plan.md").write_text(texto.strip() + "\n", encoding="utf-8")


def crear(pedido: str, origen: str = "texto") -> str:
    """Una tarea nueva, al final de la cola. No arranca nada: eso lo hace la bomba."""
    pedido = (pedido or "").strip()
    if not pedido:
        raise ValueError("una tarea vacía no se encola")
    with _candado():
        base = "t-" + datetime.now().strftime("%y%m%d-%H%M%S")
        tarea_id, n = base, 1
        while (_tareas() / tarea_id).exists():
            n += 1
            tarea_id = f"{base}-{n}"
        (_tareas() / tarea_id).mkdir()
        _escribir({
            "id": tarea_id,
            "pedido": pedido,
            "origen": origen,
            "estado": EN_COLA,
            "creada": ahora(),
            # Para ordenar la cola. `creada` va al segundo, y dos tareas
            # dictadas seguidas empataban: salía primero cualquiera de las dos.
            "orden": time.time_ns(),
            "empezada": None,
            "cerrada": None,
            "resumen": "",
            "proyectos": [],
            "esperas": [],
            "abiertas": [],
            "pregunta": None,
            "despertar": [],
            "avance": "",
        })
    anotar(tarea_id, "pedido", pedido, origen=origen)
    return tarea_id


def listar() -> list[dict[str, Any]]:
    tareas = []
    for d in _tareas().iterdir():
        if d.is_dir() and _ID_TAREA.match(d.name):
            t = _leer(d.name)
            if t:
                tareas.append(t)
    return sorted(tareas, key=lambda t: (t["creada"], t.get("orden", 0)))


def viva() -> dict[str, Any] | None:
    """La tarea en curso. Hay una como mucho: la cola es la decisión del dueño."""
    return next((t for t in listar() if t["estado"] in VIVAS), None)


def en_cola() -> list[dict[str, Any]]:
    return [t for t in listar() if t["estado"] == EN_COLA]


def detener(tarea_id: str, motivo: str = "detenida por el dueño") -> dict[str, Any]:
    """Para la tarea y a quien estuviera trabajando para ella. Siempre funciona.

    Interrumpe con Escape —de la lista cerrada de teclas— al orquestador y a las
    sesiones que esperaba **si están trabajando**. A una sesión quieta no se le
    manda nada: un Escape en un cuadro vacío no hace daño, pero tampoco hay
    nada que parar, y lo que no hace falta no se teclea.

    Una tarea en cola se quita de la cola con esto mismo.
    """
    interrumpidas: list[str] = []
    with editar(tarea_id) as tarea:
        if tarea["estado"] in CERRADAS:
            return {"ok": False, "motivo": f"ya estaba {tarea['estado']}"}
        estaba = tarea["estado"]
        tarea["estado"] = DETENIDA
        tarea["cerrada"] = ahora()
        tarea["despertar"] = []
        tarea["pregunta"] = None
        # Todas las sesiones a las que esta tarea mandó algo, no sólo las que
        # aún esperaba: en el ensayo, una espera se había dado por acabada
        # mientras la sesión seguía trabajando y Detener no la tocó. Sólo se
        # interrumpe la que esté trabajando AHORA (`_interrumpir`).
        paneles = list(dict.fromkeys(
            e["pane_id"] for e in tarea["esperas"] if e["estado"] != "perdida"))
        for e in tarea["esperas"]:
            if e["estado"] == "esperando":
                e["estado"] = "cancelada"
    if estaba in VIVAS:
        orq = localizar()
        for pane_id in [*paneles, *([orq] if orq else [])]:
            if _interrumpir(pane_id):
                interrumpidas.append(pane_id)
    anotar(tarea_id, "detenida", motivo, interrumpidas=interrumpidas)
    timbre(f"Tarea {tarea_id} detenida.")
    return {"ok": True, "interrumpidas": interrumpidas}


def _interrumpir(pane_id: str) -> bool:
    try:
        agente = tui.detectar(pane_id)
        if agente is not tui.CLAUDE or not tui.ocupado(agente, pane_id):
            return False
        tmux.tecla_en_panel(pane_id, "Escape")
        return True
    except (tmux.DestinoInvalido, tmux.TmuxNoDisponible, RuntimeError) as exc:
        print(f"[orquestador] no se pudo interrumpir {pane_id}: {exc}", flush=True)
        return False


def responder(tarea_id: str, texto: str, origen: str = "texto") -> None:
    """El dueño contesta la pregunta abierta. Despierta al orquestador con ella."""
    texto = (texto or "").strip()
    if not texto:
        raise ValueError("una respuesta vacía no se manda")
    with editar(tarea_id) as tarea:
        if tarea["estado"] not in VIVAS or not tarea.get("pregunta"):
            raise ValueError("esa tarea no está esperando ninguna respuesta tuya")
        pregunta = tarea["pregunta"]["texto"]
        tarea["pregunta"] = None
        tarea["despertar"].append(
            f"El dueño contestó a tu pregunta «{_corto(pregunta, 160)}»:\n«{texto}»"
        )
        tarea["estado"] = _estado_de(tarea)
    anotar(tarea_id, "respuesta", texto, origen=origen)


# ─────────────────────── lo que hacen sus manos (./orq) ─────────────────────


class TareaCerrada(RuntimeError):
    """La tarea ya no admite nada. Es lo que hace real el botón Detener."""


def exigir_viva() -> dict[str, Any]:
    tarea = viva()
    if not tarea:
        ultima = next(reversed(listar()), None)
        if ultima and ultima["estado"] == DETENIDA:
            raise TareaCerrada(
                f"la tarea {ultima['id']} fue DETENIDA por el dueño. No hagas nada "
                "más: ni mandes, ni abras, ni preguntes. Termina tu turno."
            )
        raise TareaCerrada("no hay ninguna tarea en curso. Termina tu turno.")
    return tarea


def sesiones(con: sqlite3.Connection, proyecto_id: str) -> list[dict[str, Any]]:
    """Las sesiones con un agente vivo en ese proyecto, comprobadas contra tmux.

    El proyecto de cada panel sale del último muestreo; que siga habiendo un
    agente dentro, de tmux en este instante. Las que abrió esta misma tarea se
    suman aunque el muestreo aún no las haya visto: va hasta 20 s por detrás, y
    una sesión recién abierta es justo la que se quiere usar.
    """
    from . import api

    candidatos: dict[str, dict[str, Any]] = {}
    pestanas: dict[str, dict[int, str]] = {}
    for p in api.paneles_abiertos(con):
        if p.get("proyecto_id") == proyecto_id:
            if p["session"] not in pestanas:
                pestanas[p["session"]] = _pestanas_de(con, p["session"])
            candidatos[p["pane_id"]] = {
                "pane_id": p["pane_id"],
                "nombre": _nombre_visible(p.get("slot_nombre") or "",
                                          pestanas[p["session"]].get(p["window_idx"])
                                          or p.get("etiqueta") or ""),
                "cwd": p.get("cwd") or ""}
    tarea = viva()
    for a in (tarea or {}).get("abiertas", []):
        if a["proyecto"] == proyecto_id:
            candidatos.setdefault(a["pane_id"], {"pane_id": a["pane_id"],
                                                 "nombre": a.get("nombre", ""), "cwd": ""})
    vivas = []
    for c in candidatos.values():
        agente, _ = entrega.quien_hay(c["pane_id"])
        if agente is None:
            continue
        c["agente"] = agente.nombre
        c["trabajando"] = tui.ocupado(agente, c["pane_id"])
        vivas.append(c)
    return vivas


def _pestanas_de(con: sqlite3.Connection, session: str) -> dict[int, str]:
    """La etiqueta de cada pestaña de /trabajo en esa sesión, por índice de ventana.

    🔴 Sólo con el slot, las tres sesiones del hub salían como «Hub - Dev» y ni
    el dueño ni el orquestador podían decir a cuál mandar: un slot tiene varias
    ventanas, y lo que las distingue es lo que se lee en la pestaña —el nombre
    que él le puso a mano o, si no, el título que pinta Claude—. Se toma de la
    misma costura que la franja de pestañas para que los dos digan lo mismo.
    """
    from . import api

    try:
        return {v["indice"]: v["etiqueta"] for v in api.ventanas_de_sesion(con, session)
                if v.get("etiqueta")}
    except tmux.DestinoInvalido:
        return {}


def _nombre_visible(slot: str, pestana: str) -> str:
    if slot and pestana and pestana != slot:
        return f"{slot} › {pestana}"
    return slot or pestana


def abrir_sesion(con: sqlite3.Connection, proyecto_id: str, nombre: str = "") -> dict[str, Any]:
    """Abre una sesión de Claude Code en el proyecto. Sólo si no hay ninguna.

    Si ya hay una, se usa ésa; si hay varias, se le pregunta al dueño cuál: es lo
    que él decidió, y abrir otra más al lado de la suya sería trabajar a sus
    espaldas en el mismo árbol.

    🔴 Corre en `bypassPermissions`, que es como trabaja él (*«siempre trabajo
    con el skip permissions»*) y lo único que funciona sin nadie delante: una
    sesión que pregunta un permiso a las tres de la mañana se queda parada
    hasta que él vuelva. Lo que no debe pasar nunca va como `deny` en el
    `settings.json` del proyecto, que es la cerradura que sí existe.
    """
    from . import agentes, api, entrevistador, slots

    tarea = exigir_viva()
    exigir(con, proyecto_id)
    ya = sesiones(con, proyecto_id)
    if ya:
        raise ValueError(
            f"«{proyecto_id}» ya tiene {len(ya)} sesión(es) abierta(s): "
            + ", ".join(s["pane_id"] for s in ya)
            + (". Usa ésa." if len(ya) == 1 else
               ". Hay varias: pregúntale al dueño a cuál mandar con `./orq preguntar`.")
        )
    proyecto = api.obtener_proyecto(con, proyecto_id)
    if not proyecto or not proyecto.get("asiento"):
        raise ValueError(f"«{proyecto_id}» no tiene asiento donde abrir una sesión")

    nombre = (nombre or "").strip() or f"orq-{tarea['id'][2:]}"
    agentes._confiar(Path(proyecto["asiento"]))
    comando = (f"claude {modelos.bandera(modelos.SESION_ORQUESTADA)} "
               "--permission-mode bypassPermissions")
    slot_id = slots.crear(con, proyecto_id, nombre, ruta=proyecto["asiento"],
                          nota=f"Abierta por el orquestador para la tarea {tarea['id']}.",
                          comando=comando)
    con.commit()
    pane_id = slots.abrir(con, slot_id, conservar_al_morir=True)
    con.commit()
    if not pane_id:
        raise RuntimeError(f"no se pudo abrir la ventana en «{proyecto_id}»")
    entrevistador.comprobar_arranque(pane_id)
    listo = _esperar(lambda: tui.listo(tui.CLAUDE, pane_id), 30)
    with editar(tarea["id"]) as t:
        t["abiertas"].append({"proyecto": proyecto_id, "pane_id": pane_id,
                              "nombre": nombre, "slot_id": slot_id, "cuando": ahora()})
        if proyecto_id not in t["proyectos"]:
            t["proyectos"].append(proyecto_id)
    anotar(tarea["id"], "abierta", f"sesión nueva en {proyecto_id}",
           proyecto=proyecto_id, pane_id=pane_id)
    if not listo:
        _esperar_libre(tarea["id"], proyecto_id, pane_id, "todavía arrancando")
    return {"pane_id": pane_id, "slot_id": slot_id, "listo": listo}


def _esperar(condicion, segundos: float, paso: float = 0.5) -> bool:
    fin = time.monotonic() + segundos
    while time.monotonic() < fin:
        with contextlib.suppress(Exception):
            if condicion():
                return True
        time.sleep(paso)
    return False


def marca(tarea_id: str, n: int) -> str:
    """La etiqueta que va en la primera línea de cada mensaje a una sesión.

    Sirve para dos cosas: que la sesión y quien lea el transcript sepan de dónde
    viene, y que `respuesta` encuentre en el transcript **este** mensaje y no
    otro — es la única forma fiable de casar un panel con su sesión de Claude.
    """
    return f"[orq {tarea_id} #{n}]"


def enmarcar(tarea_id: str, n: int, nivel: str, texto: str) -> str:
    """El mensaje tal como llega a la sesión. El pacto va dentro, cada vez.

    Cada vez y no una: la sesión puede haber compactado, o ser una que el dueño
    abrió ayer para otra cosa. Lo que no está en el mensaje no se puede suponer.
    """
    nunca = "; ".join(SIEMPRE_DEL_DUENO)
    return (
        f"{marca(tarea_id, n)} Mensaje del orquestador del hub, por encargo del dueño.\n"
        f"Nivel de decisión que el dueño te da en este proyecto: {nivel} — {DESCRIPCION[nivel]}.\n"
        f"Nunca sin el dueño, sea cual sea el nivel: {nunca}. Si algo de eso hace "
        "falta, no lo hagas: dilo en tu resumen.\n"
        "Si lo que se pide choca con una decisión registrada del proyecto, no lo "
        "hagas: dilo en tu resumen.\n\n"
        f"{texto.strip()}\n\n"
        "Al terminar, cierra tu respuesta con este bloque:\n"
        "RESUMEN\n- hecho: …\n- no hecho: …\n- necesita al dueño: …"
    )


def mandar(con: sqlite3.Connection, proyecto_id: str, pane_id: str, texto: str) -> dict[str, Any]:
    """Le manda una instrucción a la sesión de un proyecto. La pieza delicada.

    Tres comprobaciones, y todas en el instante de escribir:

    1. **Alcance**: el nivel del proyecto no es «nada» (cerradura, 256).
    2. **Que el panel sea de ese proyecto**: si no, un pane_id equivocado le
       mandaría el trabajo de un proyecto a otro.
    3. **Que ahí siga corriendo un agente libre** (`entrega.entregar`, regla
       dura 15): si el dueño salió a una shell, no se escribe nada.

    Si la sesión está trabajando no se encola en su cola: se apunta una espera
    «hasta que quede libre» y el hub despierta al orquestador cuando lo esté.
    """
    tarea = exigir_viva()
    nivel = exigir(con, proyecto_id)
    texto = (texto or "").strip()
    if not texto:
        raise ValueError("un mensaje vacío no se manda")
    tmux.validar_panel(pane_id)
    suyas = {s["pane_id"] for s in sesiones(con, proyecto_id)}
    if pane_id not in suyas:
        raise ValueError(
            f"{pane_id} no es una sesión viva de «{proyecto_id}». Mira `./orq sesiones {proyecto_id}`."
        )

    apto, motivo = entrega.panel_apto(pane_id)
    if not apto:
        # Hay un agente pero ahora no acepta —trabaja, arranca, pide permiso—:
        # se espera a que quede libre y el hub lo despierta. Antes sólo se
        # esperaba si «trabajaba»; una sesión que ARRANCABA daba error, él
        # anotaba «se lo pido cuando acepte» y nadie lo despertaba nunca.
        agente, _ = entrega.quien_hay(pane_id)
        if agente is not None:
            _esperar_libre(tarea["id"], proyecto_id, pane_id, motivo)
            # 🔴 Un menú en pantalla no se arregla esperando: alguien tiene que
            # contestarlo. Visto instalando en limpio (13-oct): la tarea se quedó
            # esperando con la razón bien escrita en su bitácora y al dueño no le
            # llegó nada. El hub avisa él mismo, sin fiarlo al modelo; sólo el
            # id de la tarea, como todo timbre (regla dura 22).
            menu = asistente.menu_abierto(tmux.capturar_panel(pane_id))
            if menu:
                timbre(f"Una sesión de la tarea {tarea['id']} espera que contestes "
                       "algo en su pantalla.")
            return {"enviado": False, "motivo": motivo, "espera": "libre",
                    "necesita_al_dueno": menu}
        raise ValueError(f"no se puede escribir en {pane_id}: {motivo}")

    with editar(tarea["id"]) as t:
        n = len(t["esperas"]) + 1
    cuerpo = enmarcar(tarea["id"], n, nivel, texto)
    try:
        entrega.entregar(pane_id, cuerpo)
        confirmado = True
    except entrega.EscritoSinConfirmar:
        # El texto YA está en el panel: no se reintenta (duplicaría la orden).
        # Se sigue como si hubiera salido y se dice en la bitácora.
        confirmado = False
    except entrega.PanelNoApto as exc:
        raise ValueError(f"no se puede escribir en {pane_id}: {exc}") from exc

    with editar(tarea["id"]) as t:
        espera = _nueva_espera(t, proyecto_id, pane_id, tipo="respuesta", n=n)
        t["estado"] = _estado_de(t)
        if proyecto_id not in t["proyectos"]:
            t["proyectos"].append(proyecto_id)
    anotar(tarea["id"], "mandado", texto, proyecto=proyecto_id, pane_id=pane_id,
           n=n, nivel=nivel, confirmado=confirmado)
    return {"enviado": True, "confirmado": confirmado, "espera": espera["id"]}


def _esperar_libre(tarea_id: str, proyecto_id: str, pane_id: str, motivo: str) -> None:
    with editar(tarea_id) as t:
        if not any(e["pane_id"] == pane_id and e["tipo"] == "libre" and e["estado"] == "esperando"
                   for e in t["esperas"]):
            _nueva_espera(t, proyecto_id, pane_id, tipo="libre")
        t["estado"] = _estado_de(t)
    anotar(tarea_id, "espera", f"{proyecto_id}: {motivo}; espero a que quede libre",
           proyecto=proyecto_id, pane_id=pane_id)


def _nueva_espera(tarea: dict, proyecto_id: str, pane_id: str, tipo: str,
                  n: int | None = None) -> dict[str, Any]:
    espera = {
        "id": n or len(tarea["esperas"]) + 1,
        "tipo": tipo,
        "proyecto": proyecto_id,
        "pane_id": pane_id,
        "enviado": ahora(),
        "visto_trabajando": False,
        "avisado_tope": False,
        "estado": "esperando",
    }
    tarea["esperas"].append(espera)
    return espera


def respuesta(pane_id: str, n: int | None = None) -> dict[str, Any]:
    """Lo que contestó una sesión al último mensaje que se le mandó.

    Se lee del transcript de Claude Code buscando la marca del mensaje: es la
    única forma de casar un panel con su sesión sin suponer —en una misma
    carpeta puede haber tres sesiones—. Si la marca no aparece se cae a la
    pantalla del panel y **se dice**, porque lo que se lee de ahí es parcial.
    """
    from . import transcripts

    tarea = exigir_viva()
    enviadas = [e for e in tarea["esperas"]
                if e["pane_id"] == pane_id and e["tipo"] == "respuesta"]
    if n is not None:
        enviadas = [e for e in enviadas if e["id"] == n]
    if not enviadas:
        raise ValueError(f"no le has mandado nada a {pane_id} en esta tarea")
    espera = enviadas[-1]
    buscada = marca(tarea["id"], espera["id"])

    cwd = next((p["cwd"] for p in tmux.listar_paneles() if p["pane_id"] == pane_id), "")
    directorios = [transcripts.TRANSCRIPTS / transcripts.slug_de(cwd)] if cwd else []
    desde = _momento(espera["enviado"]).timestamp() - 120
    candidatos = sorted(
        (j for d in directorios if d.is_dir() for j in transcripts.jsonl_de(d)
         if transcripts.mtime(j) >= desde),
        key=transcripts.mtime, reverse=True,
    )
    for ruta in candidatos:
        mensajes = transcripts.esqueleto(ruta)["mensajes"]
        inicio = next((i for i, m in enumerate(mensajes)
                       if m.get("rol") == "user" and buscada in (m.get("texto") or "")), None)
        if inicio is None:
            continue
        textos = [m["texto"] for m in mensajes[inicio + 1:]
                  if m.get("rol") == "assistant" and (m.get("texto") or "").strip()]
        cuerpo = "\n\n".join(textos).strip()
        return {"origen": "transcript", "texto": _recortar(cuerpo),
                "terminada": espera["estado"] == "terminada"}

    pantalla = tmux.capturar_panel(pane_id, unir_lineas=True, con_historia=True)
    return {"origen": "pantalla",
            "texto": _recortar("\n".join(pantalla.splitlines()[-150:])),
            "terminada": espera["estado"] == "terminada"}


LIMITE_RESPUESTA = 12_000


def _recortar(texto: str) -> str:
    """Lo último, que es donde va el RESUMEN que se le pidió a la sesión."""
    if len(texto) <= LIMITE_RESPUESTA:
        return texto
    return "[… recortado: sólo lo último …]\n" + texto[-LIMITE_RESPUESTA:]


def preguntar(texto: str) -> None:
    """A la bandeja del dueño. La tarea queda esperando hasta que conteste."""
    texto = (texto or "").strip()
    if not texto:
        raise ValueError("una pregunta vacía no se hace")
    tarea = exigir_viva()
    with editar(tarea["id"]) as t:
        t["pregunta"] = {"texto": texto, "hecha": ahora()}
        t["estado"] = _estado_de(t)
    anotar(tarea["id"], "pregunta", texto)
    timbre(f"El orquestador tiene una pregunta para ti (tarea {tarea['id']}).")


def avance(texto: str) -> None:
    tarea = exigir_viva()
    with editar(tarea["id"]) as t:
        t["avance"] = (texto or "").strip()
    anotar(tarea["id"], "avance", texto)


_PASO = re.compile(r"^\s*(\d+)[.)]\s+\S", re.MULTILINE)


def contar_pasos(plan_texto: str) -> int:
    """Cuántos pasos numerados tiene un plan («1. …», «2) …»). 0 si no los numera.

    Se cuentan los números distintos y no las líneas: un paso con sub-apartados
    «1.» dentro de un bloque no debería contar doble.
    """
    return len({int(n) for n in _PASO.findall(plan_texto or "")})


def fijar_plan(texto: str) -> None:
    tarea = exigir_viva()
    if not (texto or "").strip():
        raise ValueError("un plan vacío no se guarda")
    guardar_plan(tarea["id"], texto)
    with editar(tarea["id"]) as t:
        t["pasos"] = contar_pasos(texto)
        t["paso"] = min(int(t.get("paso") or 0), t["pasos"]) or (1 if t["pasos"] else 0)
    anotar(tarea["id"], "plan", f"plan guardado ({contar_pasos(texto)} pasos)")


def marcar_paso(n: int) -> None:
    """En qué paso del plan va. Los de antes quedan hechos.

    Es lo que pintan los puntos de la pantalla: sin esto, desde el teléfono
    sólo se ve «trabajando», que no dice si va por el principio o casi acaba.
    """
    tarea = exigir_viva()
    total = int(tarea.get("pasos") or 0)
    if not total:
        raise ValueError("tu plan no tiene pasos numerados («1. …»): guárdalo así con `./orq plan`")
    if not 1 <= n <= total:
        raise ValueError(f"el plan tiene {total} pasos: el paso va de 1 a {total}")
    with editar(tarea["id"]) as t:
        t["paso"] = n
    anotar(tarea["id"], "paso", f"paso {n} de {total}")


def puntos(tarea: dict[str, Any]) -> list[str]:
    """Un estado por paso del plan, para pintarlos: hecho · ahora · falta.

    `ahora` pasa a `pregunta` si la tarea está esperando al dueño —es lo que
    necesita verse de un vistazo— y los que faltaban de una tarea detenida se
    quedan en `parado`. Una tarea terminada tiene todos hechos: si acabó antes
    de lo planeado, lo que dice es el resumen, no los puntos.
    """
    total = int(tarea.get("pasos") or 0)
    if not total:
        return []
    if tarea["estado"] == TERMINADA:
        return ["hecho"] * total
    actual = int(tarea.get("paso") or 1)
    if tarea["estado"] == DETENIDA:
        return ["hecho" if i < actual else "parado" for i in range(1, total + 1)]
    ahora_ = "pregunta" if tarea["estado"] == ESPERANDO_DUENO else "ahora"
    if tarea["estado"] == EN_COLA:
        ahora_ = "falta"
    return ["hecho" if i < actual else ahora_ if i == actual else "falta"
            for i in range(1, total + 1)]


def terminar(resumen: str) -> None:
    """Cierra la tarea. Lo que quede esperando se cancela, y se le avisa."""
    resumen = (resumen or "").strip()
    if not resumen:
        raise ValueError("cierra con un resumen: es lo que el dueño va a leer")
    tarea = exigir_viva()
    with editar(tarea["id"]) as t:
        t["estado"] = TERMINADA
        t["cerrada"] = ahora()
        t["resumen"] = resumen
        t["despertar"] = []
        for e in t["esperas"]:
            if e["estado"] == "esperando":
                e["estado"] = "cancelada"
    anotar(tarea["id"], "terminada", resumen)
    timbre(f"Tarea {tarea['id']} terminada.")


# ───────────────────────── el timbre (Telegram) ─────────────────────────────


def timbre(texto: str) -> None:
    """Deja un aviso para que lo mande el relé. Sólo el aviso: el contenido, en el hub.

    Un archivo por aviso y no una tabla: el relé lo manda y lo borra, sin
    pisarse con quien escribe. 🔴 Regla dura 22: sale el id de la tarea y qué
    pasó, **ni siquiera su pedido** —«en <cliente> dame logos» ya lleva el
    nombre de un cliente—. Lo demás se lee en el hub.
    """
    d = carpeta() / "timbres"
    d.mkdir(exist_ok=True)
    nombre = f"{time.time_ns()}.json"
    (d / nombre).write_text(json.dumps({"texto": texto, "cuando": ahora()},
                                       ensure_ascii=False), encoding="utf-8")


def timbres_pendientes() -> list[Path]:
    d = carpeta() / "timbres"
    return sorted(d.glob("*.json")) if d.is_dir() else []


def _corto(texto: str, n: int = 90) -> str:
    limpio = " ".join((texto or "").split())
    return limpio if len(limpio) <= n else limpio[: n - 1] + "…"


# ───────────────────────── el panel del orquestador ─────────────────────────


def localizar() -> str | None:
    """Su panel, escaneando tmux. Nada guardado que pueda apuntar a otro."""
    for panel in tmux.listar_paneles():
        if panel["session"] == SESION and panel["comando"] == "claude":
            return panel["pane_id"]
    return None


def preparar() -> Path:
    """Su carpeta: el contrato, sus permisos y sus manos. Se reescribe cada vez.

    Cada vez para que un cambio del contrato llegue a la siguiente tarea sin
    pasos a mano. Es la carpeta del hub, no de un proyecto: aquí escribir es
    legítimo.
    """
    from . import agentes

    d = carpeta()
    (d / "CLAUDE.md").write_text(CONTRATO.format(
        niveles="\n".join(f"- **{n}**: {DESCRIPCION[n]}" for n in NIVELES[1:]),
        nunca="\n".join(f"- {x}" for x in SIEMPRE_DEL_DUENO),
    ), encoding="utf-8")
    manos = d / "orq"
    manos.write_text(ENVOLTORIO.format(
        hub_home=shlex.quote(str(config.HUB_HOME)),
        uv=shlex.quote(shutil.which("uv", path=tmux.path_de_usuario()) or "uv"), raiz=shlex.quote(str(config.RAIZ_REPO)),
    ), encoding="utf-8")
    manos.chmod(0o755)

    conf = d / ".claude"
    conf.mkdir(exist_ok=True)
    casa = str(Path.home()).lstrip("/")
    (conf / "settings.json").write_text(json.dumps({
        "permissions": {
            "allow": [
                "Read", "Glob", "Grep",
                "Bash(./orq:*)", f"Bash({manos}:*)",
                "Bash(git log:*)", "Bash(git status:*)", "Bash(git diff:*)",
                "Bash(ls:*)",
            ],
            # Denegado y no «sin permitir»: en `dontAsk` lo no permitido también
            # se rechaza, pero decirlo aquí deja escrito el trato (decisión 78).
            "deny": [
                "Edit", "Write", "NotebookEdit",
                f"Read(//{casa}/.secretos/**)", f"Read(//{casa}/.ssh/**)",
                "Bash(rm:*)", "Bash(git push:*)", "Bash(git commit:*)",
                "Bash(docker:*)", "Bash(systemctl:*)", "Bash(curl:*)",
            ],
        }
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    agentes._confiar(d)
    return d


def comando_de_arranque(primer_mensaje: str) -> str:
    """`claude` en `dontAsk`: lo que no está permitido se rechaza, no se pregunta.

    🔴 Es el modo que hace posible dejarlo solo. En `manual`, cualquier cosa
    fuera de su lista abriría un cuadro de permisos que nadie va a contestar y
    la tarea se quedaría parada horas sin que nada lo dijera. En `dontAsk` el
    rechazo es inmediato y el agente sigue con lo que sí puede hacer.
    """
    return (f"env PATH={shlex.quote(tmux.path_de_usuario())} "
            f"claude {modelos.bandera(modelos.ORQUESTADOR)} "
            f"--permission-mode dontAsk {shlex.quote(primer_mensaje)}")


def abrir_panel(primer_mensaje: str) -> str:
    """Un orquestador nuevo, con el primer mensaje como argumento de `claude`.

    Como argumento y no pegado después: en arranque en frío la TUI se traga lo
    que llega antes de pintar el cuadro (regla dura 17). Así no hay carrera.
    """
    d = preparar()
    comando = comando_de_arranque(primer_mensaje)
    entorno = {"PATH": tmux.path_de_usuario()}
    if tmux.existe_sesion(SESION):
        tmux.nueva_ventana(SESION, str(d), VENTANA, comando, entorno)
    else:
        tmux.nueva_sesion(SESION, str(d), VENTANA, comando, entorno)
    if not _esperar(lambda: localizar() is not None, 15):
        raise RuntimeError("se abrió la ventana del orquestador pero `claude` no llegó a arrancar")
    return localizar() or ""


def cerrar_panel() -> None:
    """Al empezar una tarea nueva, el orquestador de la anterior se va entero.

    Contexto limpio por tarea: lo que importa de la anterior está en su carpeta,
    y arrastrarlo sólo gasta y confunde.
    """
    pane_id = localizar()
    if pane_id:
        tmux.matar_panel(pane_id)


# ────────────────────────────── la bomba ────────────────────────────────────

# Cuánto sin verla trabajar hace falta para dar una respuesta por acabada. Una
# instrucción corta puede empezar y acabar entre dos latidos (20 s), así que no
# verla trabajar no significa que no lo hiciera; pero justo después de mandar
# el spinner aún no ha arrancado.
QUIETA_TRAS = 45

# Pasado esto sin que acabe, se le avisa una vez. No se cancela nada: una
# compilación larga o una batería de tests son trabajo legítimo.
TOPE_MINUTOS = 90


def bombear(con: sqlite3.Connection) -> dict[str, Any]:
    """Un latido. Lo llama el snapshotter cada 20 s, en su propio `try`.

    Activa la siguiente de la cola si no hay ninguna, mira las sesiones a las
    que se mandó algo y, si hay algo que contarle, despierta al orquestador.
    """
    with _candado():
        tarea = viva()
        if not tarea:
            siguiente = next(iter(en_cola()), None)
            if not siguiente:
                return {}
            tarea = siguiente
            tarea["estado"] = ACTIVA
            tarea["empezada"] = ahora()
            tarea["despertar"] = [PRIMER_MENSAJE.format(tarea=tarea["id"])]
            tarea["nueva"] = True
            _escribir(tarea)
        else:
            _revisar_esperas(tarea)
            _vigilar_quieta(tarea)
            _escribir(tarea)
    if tarea.pop("nueva", False):
        anotar(tarea["id"], "empezada", "el orquestador empieza")
        with editar(tarea["id"]) as t:
            t.pop("nueva", None)
    return _despertar(tarea["id"])


def _revisar_esperas(tarea: dict[str, Any]) -> None:
    for e in tarea["esperas"]:
        if e["estado"] != "esperando":
            continue
        agente, motivo = entrega.quien_hay(e["pane_id"])
        quien = f"la sesión de {e['proyecto']} ({e['pane_id']})"
        if agente is None:
            e["estado"] = "perdida"
            tarea["despertar"].append(f"{quien} ya no está: {motivo}. Decide cómo seguir.")
            continue
        trabajando = tui.ocupado(agente, e["pane_id"])
        if trabajando:
            e["visto_trabajando"] = True
        elif agente is tui.CLAUDE and _pide_permiso(e["pane_id"]):
            if not e.get("avisado_permiso"):
                e["avisado_permiso"] = True
                tarea["despertar"].append(
                    f"{quien} está parada pidiendo un permiso que tú no puedes dar. "
                    "Pregúntale al dueño con `./orq preguntar` y di que lo apruebe en el hub.")
            continue
        edad = _segundos_desde(e["enviado"])
        if e["tipo"] == "libre":
            # «Libre» es «se le puede escribir»: arrancando o con un permiso
            # abierto no trabaja, pero tampoco acepta.
            if entrega.panel_apto(e["pane_id"])[0]:
                e["estado"] = "terminada"
                tarea["despertar"].append(f"{quien} ya está libre: puedes mandarle.")
            elif edad >= TOPE_MINUTOS * 60 and not e["avisado_tope"]:
                e["avisado_tope"] = True
                tarea["despertar"].append(
                    f"{quien} lleva más de {TOPE_MINUTOS} min sin quedar libre. "
                    "Decide si esperas o le preguntas al dueño.")
            continue
        if not trabajando and (e["visto_trabajando"] or edad >= QUIETA_TRAS):
            e["estado"] = "terminada"
            tarea["despertar"].append(
                f"{quien} terminó lo que le mandaste (#{e['id']}). "
                f"Léelo con `./orq respuesta {e['pane_id']}`.")
        elif edad >= TOPE_MINUTOS * 60 and not e["avisado_tope"]:
            e["avisado_tope"] = True
            tarea["despertar"].append(
                f"{quien} lleva más de {TOPE_MINUTOS} min con lo tuyo (#{e['id']}). "
                "Sigue trabajando; decide si esperas o le preguntas al dueño.")
    tarea["estado"] = _estado_de(tarea)


# Cuánto puede estar una tarea viva sin nada pendiente y con el orquestador
# parado antes de que el hub lo despierte. Existe por el bloqueo del 23-sep: él
# terminó su turno creyendo que alguien lo despertaría, y no había nada que lo
# hiciera. Ningún descuido suyo debería poder dejar una tarea muerta en silencio.
MINUTOS_SIN_NADA = 10


def _vigilar_quieta(tarea: dict[str, Any]) -> None:
    if tarea["estado"] != ACTIVA or tarea["despertar"] or tarea.get("pregunta"):
        return
    if any(e["estado"] == "esperando" for e in tarea["esperas"]):
        return
    ultima = (bitacora(tarea["id"]) or [{}])[-1].get("cuando")
    if not ultima or _segundos_desde(ultima) < MINUTOS_SIN_NADA * 60:
        return
    if tarea.get("vigia") == ultima:
        return   # ya se le dijo por este mismo silencio
    pane_id = localizar()
    if pane_id and tui.ocupado(tui.CLAUDE, pane_id):
        return
    tarea["vigia"] = ultima
    tarea["despertar"].append(
        f"Llevas {MINUTOS_SIN_NADA} minutos parado y no estás esperando nada que el hub "
        "sepa (ni una sesión, ni una respuesta del dueño). Nadie te va a despertar "
        "si no. Mira `./orq tarea` y sigue: manda, pregunta o termina.")


def _pide_permiso(pane_id: str) -> bool:
    from . import asistente
    return asistente.esperando_confirmacion(pane_id)


def _despertar(tarea_id: str) -> dict[str, Any]:
    """Le entrega al orquestador lo acumulado, todo en un mensaje.

    En uno: cada entrega es un turno y un turno relee el contexto entero, lo
    mismo que los lotes del canal.

    La sugerencia gris que Claude Code pinta en el cuadro —en el ensayo le
    proponía a él mismo «a, créalo como saludo.txt», la respuesta a su propia
    pregunta— **no la acepta un Enter**: medido el 2026-09-22, un Enter con sólo
    la sugerencia (`ESC[2m`, tenue) no envió nada. Así que ni el Enter «por si
    acaso» de `despachar` puede hacer que se conteste solo. Si está trabajando se deja para el siguiente
    latido; si no hay panel —primera vez, o un reinicio se lo llevó— se abre
    uno con el mensaje como argumento, que retoma desde la carpeta.
    """
    tarea = cargar(tarea_id)
    if not tarea or not tarea["despertar"] or tarea["estado"] in CERRADAS:
        return {}
    texto = "\n\n".join(tarea["despertar"])
    pane_id = localizar()
    if tarea["despertar"][0].startswith(PRIMER_MENSAJE.split("{")[0]):
        # Tarea nueva: orquestador nuevo, contexto limpio.
        cerrar_panel()
        pane_id = None
    if not pane_id:
        if not texto.startswith(PRIMER_MENSAJE.split("{")[0]):
            texto = RETOMAR.format(tarea=tarea_id) + "\n\n" + texto
        try:
            abrir_panel(texto)
        except (RuntimeError, tmux.TmuxNoDisponible) as exc:
            return _fallo_de_arranque(tarea_id, str(exc))
        entregado = True
    else:
        apto, motivo = entrega.panel_apto(pane_id)
        if not apto:
            return {"pendiente": motivo}
        try:
            entrega.entregar(pane_id, texto)
            entregado = True
        except entrega.EscritoSinConfirmar:
            entregado = True    # ya está escrito: repetirlo duplicaría el turno
        except entrega.PanelNoApto as exc:
            return {"pendiente": str(exc)}
    if entregado:
        with editar(tarea_id) as t:
            t["despertar"] = []
            if t["estado"] in VIVAS:
                t["estado"] = _estado_de(t)
    return {"despertado": tarea_id}


# Cuántas veces seguidas puede fallar el arranque antes de rendirse. Sin tope,
# un `claude` que muere al arrancar —un modelo que no existe, una versión que no
# acepta el modo— abriría una ventana nueva cada 20 s para siempre.
INTENTOS_DE_ARRANQUE = 3


def _fallo_de_arranque(tarea_id: str, motivo: str) -> dict[str, Any]:
    print(f"[orquestador] no arrancó para {tarea_id}: {motivo}", flush=True)
    with editar(tarea_id) as t:
        t["fallos_arranque"] = int(t.get("fallos_arranque") or 0) + 1
        agotado = t["fallos_arranque"] >= INTENTOS_DE_ARRANQUE
    anotar(tarea_id, "fallo", f"el orquestador no arrancó: {motivo}")
    if agotado:
        detener(tarea_id, f"el orquestador no arrancó {INTENTOS_DE_ARRANQUE} veces: {motivo}")
    return {"fallo": motivo}


# ─────────────────────────────── los textos ─────────────────────────────────

PRIMER_MENSAJE = (
    "Tarea nueva: {tarea}. Lee tu CLAUDE.md entero si no lo has hecho, y "
    "empieza con `./orq tarea`."
)

RETOMAR = (
    "Retomas la tarea {tarea} (tu ventana anterior se cerró; todo lo que pasó "
    "está en la bitácora). Empieza con `./orq tarea`."
)

ENVOLTORIO = """\
#!/usr/bin/env bash
# Las manos del orquestador. Lo genera `orquestador.preparar`; no se edita.
set -euo pipefail
export HUB_HOME={hub_home}
exec {uv} run --project {raiz} python -m hub.orquestador_cli "$@"
"""

CONTRATO = """\
# El orquestador del hub

Eres el orquestador del hub y trabajas para su dueño. Recibes una tarea y la llevas a cabo **pidiéndole
el trabajo a las sesiones de Claude Code de sus proyectos**, como lo haría él:
tú no programas, no editas y no despliegas. Coordinas.

## Tus manos son `./orq`, y nada más

    ./orq tarea                   la tarea: qué pidió, plan, bitácora, permisos
    ./orq proyectos               a qué proyectos llegas y con qué nivel
    ./orq sesiones <proyecto>     las sesiones de Claude abiertas ahí
    ./orq abrir <proyecto>        abre una sesión (sólo si no hay ninguna)
    ./orq mandar <proyecto> <pane> <<'FIN'
    …la instrucción…
    FIN                           le manda trabajo a esa sesión
    ./orq respuesta <pane>        lo que contestó desde tu último mensaje
    ./orq plan <<'FIN' … FIN      guarda tu plan, con pasos numerados
    ./orq paso <n>                en qué paso vas (los de antes quedan hechos)
    ./orq avance "<texto>"        una línea de cómo va, para el dueño
    ./orq preguntar "<texto>"     a la bandeja del dueño; la tarea espera
    ./orq terminar "<resumen>"    cierra la tarea

También puedes **leer** (Read, Glob, Grep, `git log/status/diff`, `ls`) para
entender un proyecto antes de pedir nada. No puedes escribir en ningún sitio, y
es a propósito: el trabajo lo hace la sesión del proyecto, con sus reglas.

## Cómo trabajas

1. `./orq tarea`. Lee lo que pidió y los permisos.
2. Antes de pedir nada, **lee lo que el proyecto tiene definido**: su
   `CLAUDE.md`, su arquitectura, su estado y sus pendientes. El dueño documenta
   todo al principio; tú trabajas sobre eso, no a tu aire.
3. Escribe el plan con `./orq plan`: **pasos numerados** («1. …», «2. …»),
   qué proyecto, y cuáles tocan algo de la lista de «nunca sin el dueño».
   Al empezar cada paso, `./orq paso <n>`: el dueño ve en el teléfono un punto
   por paso, y sin esto no sabe si vas por el principio o casi acabas.
4. Para cada paso: `./orq sesiones <p>`. Si no hay ninguna, `./orq abrir <p>`.
   Si hay una, ésa. **Si hay varias, pregúntale al dueño a cuál.**
5. `./orq mandar`, y **termina tu turno**. No esperes ni consultes en bucle:
   el hub te despierta con un mensaje cuando la sesión termina, cuando queda
   libre o cuando el dueño contesta.
6. Al despertar: `./orq respuesta <pane>`, decide el siguiente paso, apunta
   `./orq avance`, y sigue.
7. Al acabar: `./orq terminar` con un resumen que se entienda sin haber visto
   nada: qué se hizo, dónde está el resultado, qué queda y qué necesita al dueño.

## Lo que mandas a una sesión

Una instrucción autocontenida: la sesión no ve esta conversación. El hub le
añade él solo de dónde viene, el nivel de decisión y que cierre con un bloque
RESUMEN. Pide una cosa por mensaje cuando el orden importe.

Si hay que entregarle un archivo al dueño (un APK, un informe), pídele a la sesión
que lo **copie a la carpeta de Intercambio del hub**:
`{{HUB_HOME}}/intercambio/` —la ruta la da `./orq tarea`— y díselo en el
resumen. Nunca por Telegram ni por ningún otro sitio.

## Los niveles

Cada proyecto tiene uno, y lo pone el dueño:

{niveles}

## 🔴 Nunca sin el dueño, sea cual sea el nivel

{nunca}

Si un paso lo necesita, no lo mandes: `./orq preguntar`.

## 🔴 Cuándo te paras y preguntas

- La orden **choca con una decisión registrada** del proyecto o del hub
  (`ARQUITECTURA.md`, `CLAUDE.md`, un ADR). Ejemplo real: «que los agentes
  tomen el modelo más nuevo» choca con «id exacto, nunca el alias». No lo
  ejecutes: explícale el choque y deja que decida.
- Hay varias sesiones y no sabes a cuál.
- La sesión dice «necesita al dueño» en su resumen.
- Algo falla dos veces igual.

Pregunta una cosa concreta, con opciones si puedes: el dueño lo lee en el teléfono.

## Lo que no haces

- No intentas conseguir permisos por otro camino. Si `./orq` te dice que no
  llegas a un proyecto, es que no llegas.
- No inventas resultados. Si una sesión no confirmó algo, no lo des por hecho.
- Si `./orq` te dice que la tarea fue detenida, no haces nada más.
"""


# ──────────────────────────────── el audio ──────────────────────────────────

# 25 MB: varios minutos de voz en webm. Más que eso no es una instrucción.
LIMITE_AUDIO = 25 * 1024 * 1024
_EXTENSIONES = {"webm", "ogg", "m4a", "mp4", "wav", "mp3"}


def transcribir_audio(datos: bytes, nombre: str) -> str:
    """El texto de un audio grabado en la web. En casa, con el transcriptor de encargos.

    🔴 En casa y no en un servicio de fuera, por lo mismo que los encargos
    (decisión n4): es su voz hablando de sus proyectos. El texto vuelve al
    formulario y **no se manda solo**: una transcripción equivocada en una orden
    que se ejecuta sin nadie delante es exactamente el error que no se ve hasta
    que ya pasó. Lo lee él y pulsa.

    El audio se guarda junto a las tareas y no se poda solo (principio 9).
    """
    from . import transcribir

    if not datos:
        raise ValueError("el audio llegó vacío")
    if len(datos) > LIMITE_AUDIO:
        raise ValueError("el audio es demasiado largo para una instrucción")
    extension = (nombre.rsplit(".", 1)[-1] if "." in nombre else "webm").lower()
    if extension not in _EXTENSIONES:
        extension = "webm"
    d = carpeta() / "audios"
    d.mkdir(exist_ok=True)
    ruta = d / f"{datetime.now().strftime('%y%m%d-%H%M%S')}-{time.time_ns() % 10**6}.{extension}"
    ruta.write_bytes(datos)
    ajustes = {}
    if config.encargos_yml().is_file():
        ajustes = yaml.safe_load(config.encargos_yml().read_text(encoding="utf-8")) or {}
    return transcribir.transcribir(ruta, ajustes)
