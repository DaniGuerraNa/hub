"""Las preguntas del orquestador que le tocan al secretario (decisión 348, C-0151).

El dueño sólo habla con el secretario. Cuando el orquestador pregunta algo
operativo —a qué sesión mandar, qué hacer tras un fallo, una duda que no
cambia lo que se entrega—, el reparto (`orquestador.para_quien`, por código)
se lo pasa a él en vez de al dueño. Aquí se decide, con una llamada al modelo
**sin herramientas**, entre contestarla o elevarla.

🔴 Lo que contesta es su criterio, nunca el sí del dueño: no confirma
proyectos (`orquestador.confirmar`), no cambia niveles (`fijar_nivel`) y no
contesta preguntas del dueño (`responder` lo rechaza). Lo vigila
`tests/test_consultas.py`. Si duda, eleva: una pregunta de más al dueño cuesta
un aviso; una decisión suya tomada por otro no se ve hasta que hace daño.

Al elevar, el aviso lleva el resumen que redacta el secretario, sin código ni
rutas, y lleva a `/orquestador` (D2). Si el modelo no contesta, se eleva igual.
"""

from __future__ import annotations

import importlib
import re
import sqlite3

from .. import orquestador
from . import avisos, enrutador, memoria, motor

ESQUEMA = {
    "type": "object",
    "properties": {
        "decision": {"type": "string", "enum": ["contestar", "elevar"]},
        "respuesta": {"type": "string"},
        "resumen": {"type": "string"},
    },
    "required": ["decision"],
}

SISTEMA = """\
Eres el secretario del dueño. El orquestador del hub —un agente que coordina
el trabajo en las sesiones de sus proyectos— te hace una pregunta OPERATIVA
para no molestar al dueño. Decides entre:

- "contestar": si se resuelve con sentido común y con lo que ves (la tarea, su
  plan, la bitácora). Respuesta corta y concreta, una sola decisión.
- "elevar": si hace falta el criterio del dueño, si toca algo de la lista de
  «nunca sin el dueño» ({nunca}), una decisión de producto, dinero, terceros,
  o si no estás seguro. En "resumen" escribe para el dueño, en dos o tres
  frases, qué se pregunta y por qué le hace falta a él: sin código, sin rutas
  de archivos, sin nombres de clientes.

Lo que contestes NO es el sí del dueño. Ante la duda, elevar.
"""

#: Lo que no viaja en un aviso (D2): bloques de código, rutas y comandos.
_FUERA = re.compile(r"`[^`]*`|(?<!\w)(?:~|\.{0,2})/[\w.\-/]+")


def _nombres_propios() -> tuple[str, ...]:
    """Los nombres que el repo público tampoco lleva (`publicacion.BLOQUEANTES`:
    el dueño, sus clientes), si están.

    🔴 `publicacion` no viaja con el producto —lleva justo esos nombres—, así
    que no se importa arriba: en una instalación nueva el secretario no
    arrancaba (C-0221). Allí no hay lista y la red es sólo la instrucción al
    modelo. Por `importlib` y no con `import`: así lo ve quien lea esto, y
    `test_producto_limpio` caza cualquier `import` de un módulo que no viaja."""
    try:
        return importlib.import_module("hub.publicacion").BLOQUEANTES
    except ModuleNotFoundError as exc:
        if exc.name != "hub.publicacion":
            raise
        return ()


def _limpio(texto: str, n: int = 400) -> str:
    """Sin código, sin rutas y sin los nombres propios que se conozcan
    (`_nombres_propios`). 🔴 Es una red, no una garantía (regla 22): un cliente
    que no esté en esa lista sólo lo frena la instrucción al modelo, y el aviso
    puede salir por Telegram."""
    t = _FUERA.sub("…", texto or "")
    for patron in _nombres_propios():
        t = re.sub(patron, "…", t, flags=re.IGNORECASE)
    t = " ".join(t.split())
    return t if len(t) <= n else t[: n - 1] + "…"


def _contexto(tarea: dict) -> str:
    ultimas = orquestador.bitacora(tarea["id"])[-12:]
    lineas = "\n".join(f"- {b.get('tipo')}: {(b.get('texto') or '')[:400]}" for b in ultimas)
    return (f"TAREA {tarea['id']}\nPedido: {tarea.get('pedido', '')[:1500]}\n\n"
            f"Plan:\n{orquestador.plan(tarea['id'])[:2000] or '(sin plan)'}\n\n"
            f"Últimas líneas de la bitácora:\n{lineas or '(nada)'}\n\n"
            f"PREGUNTA (motivo «{tarea['pregunta'].get('motivo')}»):\n{tarea['pregunta']['texto']}")


def _avisar(con: sqlite3.Connection, tarea_id: str, resumen: str) -> None:
    texto = _limpio(resumen) or f"El orquestador tiene una pregunta para ti (tarea {tarea_id})."
    canal = avisos.intentar(con, texto, "consulta elevada", titulo="El orquestador pregunta",
                            enlace=f"/orquestador?tarea={tarea_id}")
    if canal is None:
        # `intentar` ya dejó el fallo a la vista. Además, por el timbre: una
        # pregunta elevada que no llega es una tarea parada sin que nadie lo sepa.
        orquestador.timbre(f"El orquestador tiene una pregunta para ti (tarea {tarea_id}).")
        canal = "timbre"
    memoria.apuntar(con, "consulta elevada", nivel="auto", params={"tarea": tarea_id},
                    resultado=f"aviso por {canal}")


def atender(con: sqlite3.Connection) -> int:
    """Una vuelta: contesta o eleva cada pregunta pendiente. Devuelve cuántas."""
    n = 0
    for pendiente in orquestador.consultas_pendientes():
        tarea = orquestador.tomar_consulta(pendiente["id"])
        if not tarea:
            continue
        n += 1
        try:
            r = motor.llamar(_contexto(tarea), modelo=enrutador.modelo("consultas"),
                             esfuerzo=enrutador.esfuerzo("consultas"), herramientas=False, esquema=ESQUEMA,
                             sistema=SISTEMA.format(nunca="; ".join(orquestador.SIEMPRE_DEL_DUENO)),
                             nueva=True, persistir=False, trabajo="consultas")
            salida = r.estructurada or {}
        except Exception as exc:  # noqa: BLE001 — sin respuesta se eleva, no se queda «atendiendo»
            salida = {"decision": "elevar", "resumen": "", "fallo": f"{type(exc).__name__}: {exc}"}
        testigo = tarea["pregunta"].get("id")
        respuesta = (salida.get("respuesta") or "").strip()
        if salida.get("decision") == "contestar" and respuesta:
            try:
                orquestador.responder(tarea["id"], respuesta, origen="secretario", de="secretario",
                                      testigo=testigo)
            except ValueError:
                continue   # el dueño contestó entretanto, o la tarea se cerró
            memoria.apuntar(con, "consulta contestada", nivel="auto", params={"tarea": tarea["id"]},
                            motivo=tarea["pregunta"]["texto"][:300], resultado=respuesta)
            continue
        resumen = (salida.get("resumen") or "").strip()
        if orquestador.elevar(tarea["id"], _limpio(resumen), por="secretario", testigo=testigo):
            _avisar(con, tarea["id"], resumen)
    return n
