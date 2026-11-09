"""Acciones sobre su propia memoria: anotar, comprometer, cerrar, callar un asunto.

Van en `auto`: escriben sólo en la base del secretario, se ven en su pantalla y
se corrigen o se borran desde ahí (3.2). Preguntar cada vez que quiere apuntar
algo haría inútil que tome notas solo (3.1).
"""

from __future__ import annotations

from .. import asuntos, memoria
from ..piezas import Accion
from ..tiempo import a_local, a_utc


class Anotar(Accion):
    id = "anotar"
    gesto = "anotar"
    nombre = "Anotar"
    resumen = "Guarda una nota en su memoria. Se ven y se corrigen en Memoria."
    descripcion = ("Guarda una nota en la memoria: un dato, un acuerdo o algo que el dueño pidió recordar. "
                   "Indica el tema y, si viene de un mensaje, de dónde salió.")
    parametros = {"type": "object", "properties": {
        "texto": {"type": "string"}, "tema": {"type": "string"}, "origen": {"type": "string"}},
        "required": ["texto"]}
    riesgo = "reversible"
    nivel_inicial = "auto"

    def ejecutar(self, con, params):
        i = memoria.anotar(con, params["texto"], tema=params.get("tema", ""), origen=params.get("origen", ""))
        return f"nota {i} guardada"


class Comprometer(Accion):
    id = "comprometer"
    gesto = "compromisos"
    nombre = "Apuntar un compromiso"
    resumen = "Apunta algo que vas a hacer (o que te pidieron) y, si le das hora, te lo recuerda."
    descripcion = ("Apunta un compromiso: algo que el dueño va a hacer (quien='yo') o que alguien le pidió. "
                   "`vence` y `recordar_en` en hora local, 'AAAA-MM-DDTHH:MM'. Si hay `recordar_en`, el "
                   "secretario le avisará al teléfono a esa hora. Si es un asunto suyo que pidió anotar "
                   "(«anótalo en mis pendientes»), pasa su `clave` en `asunto`: queda como anotado.")
    parametros = {"type": "object", "properties": {
        "que": {"type": "string"}, "quien": {"type": "string"}, "para_quien": {"type": "string"},
        "vence": {"type": "string"}, "recordar_en": {"type": "string"}, "origen": {"type": "string"},
        "asunto": {"type": "string"}},
        "required": ["que"]}
    riesgo = "reversible"
    nivel_inicial = "auto"

    def ejecutar(self, con, params):
        asunto = (params.get("asunto") or "").strip()
        vence, recordar_en = a_utc(params.get("vence")), a_utc(params.get("recordar_en") or params.get("vence"))
        if asunto:
            # «Anótalo» (381), por la misma regla que su botón: ni lo que sólo
            # él contesta (un permiso perdía lo nuevo sin contestarse), ni lo
            # callado, ni lo ya anotado o delegado.
            i = asuntos.anotar(con, asunto, params["que"], quien=params.get("quien") or "yo",
                               para_quien=params.get("para_quien", ""), vence=vence, recordar_en=recordar_en)
        else:
            i = memoria.comprometer(con, params["que"], quien=params.get("quien") or "yo",
                                    para_quien=params.get("para_quien", ""), vence=vence, recordar_en=recordar_en,
                                    origen=params.get("origen", ""))
        fila = con.execute("SELECT recordar_en FROM compromiso WHERE id = ?", (i,)).fetchone()
        aviso = f", con aviso el {a_local(fila['recordar_en'])} (hora local)" if fila and fila["recordar_en"] else ""
        if asunto:
            aviso += "; el asunto queda anotado"
        return f"compromiso {i} apuntado{aviso}"


class CerrarCompromiso(Accion):
    id = "cerrar_compromiso"
    gesto = "compromisos"
    nombre = "Cerrar un compromiso"
    resumen = "Marca un compromiso como hecho o descartado."
    descripcion = "Marca un compromiso como hecho o descartado (estado: 'hecho' | 'descartado')."
    parametros = {"type": "object", "properties": {
        "id": {"type": "integer"}, "estado": {"type": "string", "enum": ["hecho", "descartado"]}},
        "required": ["id"]}
    riesgo = "reversible"
    nivel_inicial = "auto"

    def ejecutar(self, con, params):
        memoria.cerrar_compromiso(con, int(params["id"]), params.get("estado") or "hecho")
        return f"compromiso {params['id']} {params.get('estado') or 'hecho'}"


class Reprogramar(Accion):
    id = "reprogramar_compromiso"
    gesto = "compromisos"
    nombre = "Cambiar la fecha de un compromiso"
    resumen = "Mueve el plazo o la hora del aviso de un compromiso que ya existe."
    descripcion = ("Cambia la fecha de un compromiso que ya existe (por su id) y vuelve a dejar pendiente su "
                   "aviso. `vence` y `recordar_en` en hora local, 'AAAA-MM-DDTHH:MM'.")
    parametros = {"type": "object", "properties": {
        "id": {"type": "integer"}, "vence": {"type": "string"}, "recordar_en": {"type": "string"}},
        "required": ["id"]}
    riesgo = "reversible"
    nivel_inicial = "auto"

    def ejecutar(self, con, params):
        if not (params.get("vence") or params.get("recordar_en")):
            raise ValueError("falta la fecha nueva")
        memoria.reprogramar(con, int(params["id"]), vence=a_utc(params.get("vence")),
                            recordar_en=a_utc(params.get("recordar_en")))
        f = con.execute("SELECT recordar_en FROM compromiso WHERE id = ?", (int(params["id"]),)).fetchone()
        if not f:
            raise ValueError("ese compromiso no existe")
        return f"compromiso {params['id']}: aviso el {a_local(f['recordar_en'])} (hora local)"


class CallarAsunto(Accion):
    id = "callar_asunto"
    gesto = "compromisos"
    nombre = "Dejar de sugerir un asunto"
    resumen = ("«No me lo vuelvas a sugerir»: un bloqueo, un compromiso o lo que dijo un proyecto no vuelve "
               "a salir. Lo que sólo tú contestas (permisos, preguntas) no se calla.")
    descripcion = ("Calla un asunto (su `clave`, de la lectura `asuntos`) cuando el dueño dice que no se lo "
                   "vuelvas a sugerir. Es para siempre: no vuelve aunque siga ahí. Sólo él lo reabre. Los que "
                   "llevan `solo_el` (permisos, preguntas, fichas, relevos) no se callan: se contestan.")
    parametros = {"type": "object", "properties": {"clave": {"type": "string"}}, "required": ["clave"]}
    # Reversible por él y sólo por él: lo reabre él (379).
    riesgo = "reversible"
    nivel_inicial = "auto"

    def ejecutar(self, con, params):
        clave = (params.get("clave") or "").strip()
        # Sólo uno que existe ahora: va en `auto` y la clave la escribe el modelo.
        if asuntos.buscar(con, clave) is None:
            raise ValueError(f"no hay ningún asunto «{clave}»: mira la lectura `asuntos`")
        if asuntos.marcar(con, clave, "callada") != "callada":
            raise ValueError(f"el asunto {clave} no quedó callado")
        return f"asunto {clave} callado: no se lo vuelvo a sugerir"


ACCIONES = [Anotar(), Comprometer(), CerrarCompromiso(), Reprogramar(), CallarAsunto()]
