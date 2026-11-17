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


class ArchivarSlot(Accion):
    id = "archivar_slot"
    gesto = "carpeta"
    nombre = "Archivar o desarchivar un slot"
    resumen = ("Archiva un slot, o lo devuelve a los activos, cuando tú se lo pides. Pregunta siempre: archivar "
               "es cosa tuya. Borrar no lo hace: eso es sólo tu botón.")
    descripcion = ("Archiva (`que`: archivar) o devuelve a los activos (`que`: desarchivar) un slot del hub. "
                   "`slot` es su id (míralo con `hub_slots`). Sólo si él lo pide con sus palabras («archiva el "
                   "slot del login»): nunca lo propongas tú, ni porque lleve tiempo sin tocarse, ni por "
                   "inactividad, ni para ordenar. Siempre pide su permiso, y borrar un slot no existe aquí.")
    parametros = {"type": "object", "properties": {
        "slot": {"type": "integer"}, "que": {"type": "string", "enum": ["archivar", "desarchivar"]}},
        "required": ["slot", "que"]}
    riesgo = "reversible"
    nivel_inicial = "ask"
    # Regla dura 3: archivar es una acción humana, siempre. Lo hace su toque
    # sobre esta solicitud, cada vez; nunca una regla ni el modelo solo.
    siempre_pregunta = True
    solo_con_el_dueno = True
    # Sólo `ejecutar_aprobadas` sabe que la aprobó (como `cambiar_en_pc`).
    quiere_aprobacion = True

    #: Lo que se pide → el estado en que tiene que quedar.
    _QUEDA = {"archivar": "archivado", "desarchivar": "activo"}

    def _leer(self, h, params) -> tuple[dict, str]:
        que = str(params.get("que") or "")
        if que not in self._QUEDA:
            raise ValueError("`que` es archivar o desarchivar; borrar un slot sólo lo hace el dueño con su botón")
        try:
            if isinstance(params.get("slot"), bool):
                raise ValueError
            numero = int(params.get("slot"))
        except (TypeError, ValueError):
            raise ValueError("`slot` es su id (míralo con `hub_slots`)") from None
        s = api.obtener_slot(h, numero)
        if not s:
            raise ValueError(f"no hay ningún slot {numero}")
        if que == "archivar" and s["status"] == "archivado":
            raise ValueError(f"el slot «{s['nombre']}» ya está archivado")
        if que == "desarchivar" and s["status"] != "archivado":
            raise ValueError(f"el slot «{s['nombre']}» no está archivado")
        return s, que

    def comprobar(self, params):
        h = db.conectar()
        try:
            s, _ = self._leer(h, params)
        finally:
            h.close()
        # Sólo su id: esto se guarda y sale en el aviso, y el nombre del slot
        # y el del proyecto pueden ser los de un cliente (regla dura 22).
        return f"slot {s['id']}"

    def detalle(self, con, params):
        """Cuál es, de qué proyecto y cómo está ahora, leído al pintar la solicitud."""
        try:
            numero = int(params.get("slot"))
        except (TypeError, ValueError):
            return []
        h = db.conectar()
        try:
            s = api.obtener_slot(h, numero)
        finally:
            h.close()
        if not s:
            return [("slot", "ya no existe")]
        return [("slot", f"«{s['nombre']}», de «{s['proyecto_id']}»"), ("estado ahora", s["status"])]

    def ejecutar(self, con, params, aprobada: bool = False):
        if not aprobada:
            raise RuntimeError("esto sólo se hace con el sí del dueño a esta solicitud")
        h = db.conectar()
        try:
            s, que = self._leer(h, params)
            queda = self._QUEDA[que]
            # Las mismas puertas que su botón (`/slot/{id}/estado`).
            if que == "archivar":
                slots.archivar(h, s["id"])
            else:
                slots.desarchivar(h, s["id"])
            h.commit()
            ahora = api.obtener_slot(h, s["id"])
            if not ahora or ahora["status"] != queda:
                raise RuntimeError(f"el slot no quedó {queda}")
        finally:
            h.close()
        return f"slot «{s['nombre']}» de «{s['proyecto_id']}» {'archivado' if que == 'archivar' else 'de vuelta en los activos'}"


ACCIONES = [AnotarEnSlot(), PublicarLienzo(), ArchivarSlot()]
