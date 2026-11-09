"""Crear y registrar proyectos y slots (definición 7.1, decisión 307).

Son las **mismas funciones** que usan el botón de la pantalla, el CLI del
asistente y el orquestador: `agentes.crear_proyecto`, `agentes.anexar_proyecto`
y `slots.crear`. El secretario no tiene una forma propia de crear un proyecto;
si mañana cambia cómo se crea uno, cambia para todos a la vez.

Crear un proyecto no choca con la regla dura 16: la carpeta no existe todavía,
así que no es de nadie, y quien la rellena es el agente que lanza el hub,
acotado a ella (`agentes._acotar_permisos`).
"""

from __future__ import annotations

from ... import agentes, api, db, slots
from ..piezas import Accion


def _con_hub():
    return db.conectar()


class CrearProyecto(Accion):
    id = "crear_proyecto"
    gesto = "hacer"
    nombre = "Crear un proyecto"
    resumen = "Crea la carpeta, la registra en el hub y abre un agente que la prepara."
    descripcion = ("Crea un proyecto NUEVO en una carpeta vacía: el hub la crea, la registra y lanza un agente "
                   "que la rellena. `id` en minúsculas y guiones (no cambia nunca), `ruta` absoluta, `dominio` "
                   "personal o laboral. Pregúntale al dueño lo que no te haya dicho; no inventes la ruta.")
    parametros = {"type": "object", "properties": {
        "id": {"type": "string"}, "nombre": {"type": "string"}, "ruta": {"type": "string"},
        "dominio": {"type": "string", "enum": ["personal", "laboral"]}},
        "required": ["id", "nombre", "ruta"]}
    riesgo = "reversible"
    nivel_inicial = "ask"

    def ejecutar(self, con, params):
        h = _con_hub()
        try:
            hecho = agentes.crear_proyecto(h, params["id"], params["nombre"], params["ruta"],
                                           params.get("dominio") or "personal")
            if not api.obtener_proyecto(h, hecho.get("id") or params["id"]):
                raise RuntimeError("el proyecto no quedó registrado")
        finally:
            h.close()
        return f"proyecto {params['id']} creado en {params['ruta']}; el agente lo está preparando (se ve en /trabajo)"


class AnexarProyecto(Accion):
    id = "anexar_proyecto"
    gesto = "hacer"
    nombre = "Registrar un proyecto que ya existe"
    resumen = "Lo da de alta en el hub sin tocar nada dentro."
    descripcion = ("Registra en el hub una carpeta que YA tiene un proyecto, sin tocarla. `ruta` absoluta. "
                   "`estado_ref` es el documento de estado dentro de la carpeta, sólo si existe.")
    parametros = {"type": "object", "properties": {
        "id": {"type": "string"}, "nombre": {"type": "string"}, "ruta": {"type": "string"},
        "dominio": {"type": "string", "enum": ["personal", "laboral"]}, "estado_ref": {"type": "string"}},
        "required": ["id", "nombre", "ruta"]}
    riesgo = "reversible"
    nivel_inicial = "ask"

    def ejecutar(self, con, params):
        h = _con_hub()
        try:
            agentes.anexar_proyecto(h, params["id"], params["nombre"], params["ruta"],
                                    params.get("dominio") or "personal", estado_ref=params.get("estado_ref") or "")
            if not api.obtener_proyecto(h, params["id"]):
                raise RuntimeError("el proyecto no quedó registrado")
        finally:
            h.close()
        return f"proyecto {params['id']} registrado ({params['ruta']})"


class CrearSlot(Accion):
    id = "crear_slot"
    gesto = "hacer"
    nombre = "Crear un slot"
    resumen = "Abre un hueco de trabajo con nombre y nota dentro de un proyecto."
    descripcion = ("Crea un slot (un frente de trabajo con nombre y nota) en un proyecto que ya existe. "
                   "`proyecto` es su id; `nota` dice de qué va, autocontenida.")
    parametros = {"type": "object", "properties": {
        "proyecto": {"type": "string"}, "nombre": {"type": "string"}, "nota": {"type": "string"}},
        "required": ["proyecto", "nombre"]}
    riesgo = "reversible"
    nivel_inicial = "ask"

    def ejecutar(self, con, params):
        h = _con_hub()
        try:
            p = api.obtener_proyecto(h, params["proyecto"])
            if not p:
                raise ValueError(f"no hay ningún proyecto «{params['proyecto']}»")
            nombre = (params.get("nombre") or "").strip()
            if not nombre:
                raise ValueError("un slot necesita nombre")
            sid = slots.crear(h, params["proyecto"], nombre, nota=params.get("nota") or "")
            if not api.obtener_slot(h, sid):
                raise RuntimeError("el slot no quedó guardado")
        finally:
            h.close()
        return f"slot «{nombre}» creado en {params['proyecto']} (/proyecto/{params['proyecto']})"


ACCIONES = [CrearProyecto(), AnexarProyecto(), CrearSlot()]
