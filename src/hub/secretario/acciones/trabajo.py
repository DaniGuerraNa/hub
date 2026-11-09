"""Lo que el asistente hacía en el hub, ahora del secretario (C-0161, decisión 355).

Las mismas puertas que la pantalla y el CLI: la nota de un slot por
`slots.editar`, un lienzo por `lienzos.escribir`. Ni una forma propia ni una
copia de `asistente.escribir_nota`. Y la regla de siempre (16): escriben en el
hub, nunca en un proyecto.
"""

from __future__ import annotations

from ... import api, db, lienzos, slots
from ..piezas import Accion


class AnotarEnSlot(Accion):
    id = "anotar_en_slot"
    gesto = "anotar"
    nombre = "Anotar en un slot"
    resumen = "Añade una línea a la nota de un slot, sin tocar lo que ya tenía."
    descripcion = ("Añade texto AL FINAL de la nota de un slot del hub (nunca la reescribe). `slot` es su id "
                   "(míralo con `hub_slots`). `texto`, autocontenido: se leerá dentro de semanas.")
    parametros = {"type": "object", "properties": {"slot": {"type": "integer"}, "texto": {"type": "string"}},
                  "required": ["slot", "texto"]}
    riesgo = "reversible"
    nivel_inicial = "auto"
    saca_datos = True

    def ejecutar(self, con, params):
        texto = (params.get("texto") or "").strip()
        if not texto:
            raise ValueError("una nota vacía no se guarda")
        h = db.conectar()
        try:
            s = api.obtener_slot(h, int(params["slot"]))
            if not s:
                raise ValueError(f"no hay ningún slot {params['slot']}")
            previo = (s["nota"] or "").rstrip()
            slots.editar(h, s["id"], nota=f"{previo}\n\n{texto}" if previo else texto)
            h.commit()
            if texto not in (api.obtener_slot(h, s["id"])["nota"] or ""):
                raise RuntimeError("la nota no quedó guardada")
        finally:
            h.close()
        return f"anotado en el slot «{s['nombre']}» de {s['proyecto_id']}"


class PublicarLienzo(Accion):
    id = "publicar_lienzo"
    gesto = "mostrar"
    nombre = "Publicar un lienzo"
    resumen = "Deja en el hub un lienzo (decisiones, pasos, comparativa…) para verlo en vez de leerlo."
    descripcion = ("Publica un lienzo en un proyecto del hub: contenido visual que sustituye a un texto largo "
                   "(puntos a decidir, una secuencia, una comparativa, una arquitectura). `plantilla`: decisiones, "
                   "pasos, comparativa o arquitectura. Nunca pisa lo que él editó: si existe, sale al lado.")
    parametros = {"type": "object", "properties": {
        "proyecto": {"type": "string"}, "titulo": {"type": "string"}, "cuerpo": {"type": "string"},
        "plantilla": {"type": "string", "enum": ["decisiones", "pasos", "comparativa", "arquitectura"]}},
        "required": ["proyecto", "titulo", "cuerpo"]}
    riesgo = "reversible"
    nivel_inicial = "auto"
    saca_datos = True

    def ejecutar(self, con, params):
        h = db.conectar()
        try:
            if not api.obtener_proyecto(h, params["proyecto"]):
                raise ValueError(f"no hay ningún proyecto «{params['proyecto']}»")
        finally:
            h.close()
        l = lienzos.escribir(params["proyecto"], params["titulo"], params["cuerpo"],
                             plantilla=params.get("plantilla") or "decisiones", revisar=True)
        return f"lienzo «{l.id}» publicado en {params['proyecto']} (búscalo por su id en el panel de lienzos)"


ACCIONES = [AnotarEnSlot(), PublicarLienzo()]
