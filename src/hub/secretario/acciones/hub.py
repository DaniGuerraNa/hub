"""Acciones sobre el hub (definición 7.1).

🔴 **El secretario no escribe en los proyectos** (regla dura 16). Lo que toca
un proyecto se lo encarga al orquestador, que trabaja a través de las sesiones
de cada proyecto con su alcance concedido en `/orquestador` (decisiones
254-256 y 279): el secretario pide, no hace.
"""

from __future__ import annotations

from ... import db, ideas, orquestador
from .. import asuntos
from ..piezas import Accion


class EncargarAlOrquestador(Accion):
    id = "encargar_al_orquestador"
    gesto = "delegar"
    nombre = "Encargar al orquestador"
    resumen = ("Le pasa una tarea al orquestador, que la hace en las sesiones de tus proyectos; lo que vea al "
               "probarlo vuelve a este chat con sus imágenes.")
    descripcion = ("Encola una tarea para el orquestador del hub, que la hace a través de las sesiones de los "
                   "proyectos: cambiar algo en uno, desplegar, probarlo, trabajo de varios pasos. Para crear un "
                   "proyecto o un slot usa sus acciones, no esto. `pedido` es la tarea completa y autocontenida, "
                   "como se la diría el dueño. `proyecto` (su id, de `proyectos`) si es de uno: si el dueño lo "
                   "aprueba, vale como su sí para ese proyecto. `archivos`: las rutas de lo que te adjuntó en este "
                   "hilo, tal como te llegaron, si la tarea los necesita. `asunto`: la clave de un bloqueo suyo "
                   "(lectura `asuntos`) si te pidió que se lo delegues; el proyecto sale del asunto y queda como "
                   "delegado. Sólo se delegan bloqueos, una vez; si es legal, de dinero o el orquestador no llega "
                   "a ese proyecto, sólo se prepara, y con guardrail never no se encarga nada. Para «haz pruebas de "
                   "este proyecto» (con una captura o sin ella), encárgaselo con `proyecto` y los adjuntos: la sesión "
                   "del proyecto sigue su receta «Cómo se prueba» (si no la tiene, la escribe primero), lo ejecuta y "
                   "devuelve imágenes de lo que vio, que llegan a este chat cuando termina. Dile que se lo "
                   "encargaste, no que ya está probado.")
    parametros = {"type": "object", "properties": {
        "pedido": {"type": "string"}, "proyecto": {"type": "string"},
        "archivos": {"type": "array", "items": {"type": "string"}}, "asunto": {"type": "string"}},
        "required": ["pedido"]}
    riesgo = "reversible"
    nivel_inicial = "ask"
    # Su aprobación vale como el sí del proyecto (regla 7, 279), como en
    # `trabajar_idea`: sólo `ejecutar_aprobadas` lo sabe, nunca `params`.
    quiere_aprobacion = True
    saca_datos = True

    def ejecutar(self, con, params, aprobada: bool = False):
        pedido = str(params.get("pedido") or "").strip()
        proyecto = str(params.get("proyecto") or "").strip()
        asunto = str(params.get("asunto") or "").strip()
        archivos = params.get("archivos") or ()
        if asunto:
            return _delegar_asunto(con, asunto, pedido, proyecto, archivos, aprobada)
        if proyecto:
            _alcance(proyecto)
            pedido = f"En «{proyecto}»: {pedido}"
        # `crear` valida los archivos (dentro del intercambio, o no encola nada).
        tarea = orquestador.crear(pedido, origen="secretario", archivos=archivos,
                                  confirmados=(proyecto,) if proyecto and aprobada else ())
        encolada = orquestador.cargar(tarea)
        if not encolada:
            raise RuntimeError("la tarea no quedó en la cola")
        dicho = f"tarea {tarea} en la cola del orquestador (se sigue en /orquestador)"
        if encolada.get("archivos"):
            dicho += f", con {len(encolada['archivos'])} archivos"
        return dicho + ". Cuando termine, lo que cuente y lo que vio vuelven a este chat."


def _delegar_asunto(con, asunto: str, pedido: str, proyecto: str, archivos, aprobada: bool) -> str:
    """Un asunto suyo, por la misma regla que su botón (`asuntos.delegar`, 381):
    sólo un bloqueo, ni lo ya decidido ni lo callado, nada sobre un `never`, y
    lo legal o donde el orquestador no llega, sólo preparado. El proyecto es
    el del asunto: uno distinto en `proyecto` es un error, no otro alcance."""
    a = asuntos.buscar(con, asunto)
    if a is None:
        raise ValueError(f"no hay ningún asunto «{asunto}»: mira la lectura `asuntos`")
    if proyecto and proyecto != a.origen:
        raise ValueError(f"el asunto {asunto} es de «{a.origen}», no de «{proyecto}»")
    tarea, como = asuntos.delegar(con, asunto, pedido_extra=pedido, archivos=archivos, confirmado=aprobada,
                                  por="secretario")
    hecho = "pedido que se lo preparen (no se delega del todo)" if como == "preparar" else "delegado"
    return (f"asunto {asunto} {hecho}: tarea {tarea} en la cola del orquestador (se sigue en /orquestador). "
            "Cuando termine, lo que cuente y lo que vio vuelven a este chat.")


def _alcance(proyecto: str) -> None:
    """Sin alcance sobre el proyecto la tarea no saldría: se dice antes de encolarla,
    y cómo se da (256). Un guardrail `never` es «nada» (regla dura 7)."""
    h = db.abrir()
    try:
        orquestador.exigir(h, proyecto)
    except orquestador.SinPermiso:
        raise PermissionError(f"el orquestador no tiene alcance sobre «{proyecto}» (o no está registrado): "
                              "se lo da el dueño en /orquestador → Permisos") from None
    finally:
        h.close()


class TrabajarIdea(Accion):
    id = "trabajar_idea"
    gesto = "delegar"
    nombre = "Trabajar una idea del tablero"
    resumen = "Encarga al orquestador una idea del tablero por su número, en la sesión fija «Tablero»."
    descripcion = ("Cuando el dueño dice «trabaja la idea N» (o «atiende la #N del tablero»). `idea` es su número "
                   "en /tablero. La trabaja la sesión «Tablero» del proyecto en su copia de trabajo: la aterriza y, "
                   "si es mediana o grande, le vuelve el plan antes de construir. No uses encargar_al_orquestador "
                   "para una idea del tablero.")
    parametros = {"type": "object", "properties": {"idea": {"type": "integer"}}, "required": ["idea"]}
    riesgo = "reversible"
    # «ask» (D5 del dueño): una frase mal entendida no pone a trabajar una
    # sesión. Su aprobación vale como el sí del proyecto (regla 7, 279).
    nivel_inicial = "ask"
    quiere_aprobacion = True

    def ejecutar(self, con, params, aprobada: bool = False):
        h = db.abrir()
        try:
            tarea = orquestador.encargar_idea(h, int(params["idea"]), confirmado_por_dueno=aprobada,
                                              origen="secretario")
        finally:
            h.close()
        return f"idea {params['idea']} encargada: tarea {tarea} (se sigue en /orquestador)"


class ApuntarIdea(Accion):
    id = "apuntar_idea"
    gesto = "idea"
    nombre = "Apuntar una idea en el tablero"
    resumen = "Deja una mejora o una función nueva en el tablero del hub, para tomarla después."
    descripcion = ("Apunta en el tablero del hub una idea, mejora o función nueva que se le ocurre al dueño, para "
                   "que se trabaje después sin interrumpir lo de ahora. `texto` en una línea, con sus palabras; "
                   "`detalle` opcional; `proyecto` (su id) sólo si lo dice. No es una nota de memoria ni un "
                   "pendiente con fecha: es para el tablero (/tablero).")
    parametros = {"type": "object", "properties": {
        "texto": {"type": "string"}, "detalle": {"type": "string"}, "proyecto": {"type": "string"}},
        "required": ["texto"]}
    riesgo = "reversible"
    nivel_inicial = "auto"
    # Lo apuntado va a `hub.db` (con sus copias) y, trabajado, a un proyecto (382).
    saca_datos = True

    def ejecutar(self, con, params):
        # La misma puerta que la pantalla y la terminal (decisión 342): el
        # secretario no tiene su propia forma de guardar una idea.
        h = db.abrir()
        try:
            iid = ideas.apuntar(h, params["texto"], params.get("detalle") or "", params.get("proyecto"),
                                origen="secretario")
            h.commit()
            if not ideas.ver(h, iid):
                raise RuntimeError("la idea no quedó apuntada")
        finally:
            h.close()
        return f"idea {iid} apuntada en el tablero (/tablero)"


ACCIONES = [EncargarAlOrquestador(), TrabajarIdea(), ApuntarIdea()]
