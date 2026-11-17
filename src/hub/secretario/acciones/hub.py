"""Acciones sobre el hub (definición 7.1).

🔴 **El secretario no escribe en los proyectos** (regla dura 16). Lo que toca
un proyecto se lo encarga al orquestador, que trabaja a través de las sesiones
de cada proyecto con su alcance concedido en `/orquestador` (decisiones
254-256 y 279): el secretario pide, no hace.

Detener y reanudar una tarea, y descartar una idea (C-0422), entran por la
puerta que ya usaba la web y preguntan siempre: el riesgo no está en la puerta
sino en que el modelo la abra solo.
"""

from __future__ import annotations

from ... import db, ideas, orquestador
from .. import asuntos, memoria
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
                   "pendiente con fecha: es para el tablero (/tablero). Si la idea nace de algo que no supiste hacer y "
                   "apuntaste con `no_se_hacer`, pasa en `hueco` ese mismo texto: así Confianza ve que ya está "
                   "apuntado como mejora. Sólo con el sí del dueño: nunca la apuntes por tu cuenta.")
    parametros = {"type": "object", "properties": {
        "texto": {"type": "string"}, "detalle": {"type": "string"}, "proyecto": {"type": "string"},
        "hueco": {"type": "string"}},
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
            # El hueco lo redactó el modelo: se limpia de llaves y se acota como
            # en `no_se_hacer`, y tiene que coincidir con lo que allí se apuntó.
            from ..herramientas import HUECO_MAXIMO
            hueco = memoria.ocultar_secretos(" ".join(str(params.get("hueco") or "").split()))[:HUECO_MAXIMO]
            iid = ideas.apuntar(h, params["texto"], params.get("detalle") or "", params.get("proyecto"),
                                origen="secretario", hueco=hueco)
            h.commit()
            if not ideas.ver(h, iid):
                raise RuntimeError("la idea no quedó apuntada")
        finally:
            h.close()
        return f"idea {iid} apuntada en el tablero (/tablero)"


#: Lo que contesta una acción que pregunta siempre si alguien la ejecuta sin
#: pasar por su solicitud (C-0422): no llegan a `auto`, y si llegaran, tampoco.
SOLO_CON_SU_SI = "esto sólo se hace con el sí del dueño a esta solicitud"

RAZON_MAXIMA = 300    # una frase: la redacta el modelo y queda en el tablero


class DescartarIdea(Accion):
    id = "descartar_idea"
    gesto = "idea"
    nombre = "Descartar una idea del tablero"
    resumen = ("Descarta una idea del tablero por su número, con su razón. No tiene vuelta atrás: una idea "
               "descartada no vuelve a la bandeja, así que siempre te pregunta.")
    descripcion = ("Cuando el dueño dice «descarta la idea N» (o «la #N del tablero ya no»). `idea` es su número "
                   "en /tablero: lo da él, no lo adivines. `razon`: por qué se descarta, en una frase con sus "
                   "palabras; queda escrita en el tablero. Sólo las que aún esperan. No tiene vuelta atrás y "
                   "siempre pide su permiso: dile que se lo pediste, no que ya está.")
    # `razon` y no `motivo`: ése se lo queda la herramienta para la bitácora.
    parametros = {"type": "object", "properties": {"idea": {"type": "integer"}, "razon": {"type": "string"}},
                  "required": ["idea", "razon"]}
    # `ideas._mover` sólo sale de «nueva» y no hay puerta para recuperarla.
    riesgo = "irreversible"
    nivel_inicial = "ask"
    solo_con_el_dueno = True
    # Sólo `ejecutar_aprobadas` sabe que la aprobó (como `cambiar_en_pc`).
    quiere_aprobacion = True
    # La razón va a `hub.db`, con sus copias (382).
    saca_datos = True

    @staticmethod
    def _leer(params) -> tuple[int, str]:
        try:
            # `bool` es un `int` para Python: «true» no es la idea 1.
            if isinstance(params.get("idea"), bool):
                raise ValueError
            numero = int(params.get("idea"))
        except (TypeError, ValueError):
            raise ValueError("`idea` es su número en el tablero") from None
        # La redacta el modelo: sin llaves y acotada, como el hueco de `apuntar_idea`.
        razon = memoria.ocultar_secretos(" ".join(str(params.get("razon") or "").split()))[:RAZON_MAXIMA]
        if not razon:
            raise ValueError("descartar una idea lleva su razón")
        return numero, razon

    @staticmethod
    def _la_que_espera(h, numero: int) -> dict:
        idea = ideas.ver(h, numero)
        if not idea:
            raise ValueError(f"no hay ninguna idea {numero}")
        if idea["estado"] != "nueva":
            raise ValueError(f"la idea {numero} ya está {idea['estado']}")
        return idea

    def comprobar(self, params):
        numero, _ = self._leer(params)
        h = db.abrir()
        try:
            idea = self._la_que_espera(h, numero)
        finally:
            h.close()
        # Sólo su número: esto se guarda y sale en el aviso, y el texto de una
        # idea puede nombrar a un cliente (regla dura 22). Lo enseña `detalle`.
        return f"idea {numero}"

    def detalle(self, con, params):
        try:
            numero, _ = self._leer(params)
        except ValueError:
            return []
        h = db.conectar()
        try:
            idea = ideas.ver(h, numero)
        finally:
            h.close()
        if not idea:
            return [("idea", "ya no existe")]
        return [("idea", idea["texto"]), ("estado ahora", idea["estado"])]

    def ejecutar(self, con, params, aprobada: bool = False):
        if not aprobada:
            raise RuntimeError(SOLO_CON_SU_SI)
        numero, razon = self._leer(params)
        h = db.abrir()
        try:
            # La misma puerta que el tablero y la terminal (decisión 342).
            ideas.descartar(h, numero, razon)
            h.commit()
            idea = ideas.ver(h, numero)
            if not idea or idea["estado"] != "descartada":
                raise RuntimeError("la idea no quedó descartada")
        finally:
            h.close()
        return f"idea {numero} descartada («{_corta(idea['texto'])}»): {razon}"


def _corta(texto: str, n: int = 80) -> str:
    texto = " ".join(str(texto or "").split())
    return texto if len(texto) <= n else texto[: n - 1].rstrip() + "…"


def _tarea(params) -> tuple[str, dict]:
    """La tarea que nombra `params`, tal como está ahora. Lanza si el id no
    tiene forma de id (`orquestador.dir_de`: viene del modelo) o no existe."""
    tarea_id = str(params.get("tarea") or "").strip()
    tarea = orquestador.cargar(tarea_id)
    if tarea is None:
        raise ValueError(f"no hay ninguna tarea «{tarea_id}»: mira `hub_orquestador`")
    return tarea_id, tarea


def _estado(tarea: dict) -> str:
    return orquestador.ETIQUETA.get(tarea.get("estado"), tarea.get("estado") or "?")


def _dicha(tarea_id: str, tarea: dict) -> str:
    """Lo que se guarda con la solicitud y sale en el aviso: su id y cómo
    estaba al pedirlo. 🔴 Sin su pedido: «en <cliente> dame logos» ya lleva
    el nombre de un cliente, y el timbre del orquestador tampoco lo saca
    (regla dura 22). El pedido lo enseña `_detalle_de_tarea`, al decidir."""
    return f"tarea {tarea_id}, {_estado(tarea)} al pedirlo"


def _detalle_de_tarea(params) -> list[tuple[str, str]]:
    """El pedido entero y cómo está AHORA, leídos al pintar la solicitud."""
    try:
        _, tarea = _tarea(params)
    except ValueError:
        return [("tarea", "ya no existe")]
    return [("pedido", " ".join(str(tarea.get("pedido") or "").split())), ("estado ahora", _estado(tarea))]


class DetenerTarea(Accion):
    id = "detener_tarea"
    gesto = "delegar"
    nombre = "Detener una tarea del orquestador"
    resumen = ("Para una tarea del orquestador y a las sesiones que trabajan para ella, como el botón "
               "«Detener». Pregunta siempre.")
    descripcion = ("Detiene una tarea del orquestador cuando el dueño lo pide («para esa tarea», «detén lo "
                   "que le encargaste»). `tarea` es su id (`hub_orquestador`). Es el mismo botón «Detener» de "
                   "/orquestador: interrumpe a las sesiones que estén trabajando para ella, o la quita de la "
                   "cola. Se puede reanudar después. Siempre pide su permiso: dile que se lo pediste.")
    parametros = {"type": "object", "properties": {"tarea": {"type": "string"}}, "required": ["tarea"]}
    riesgo = "reversible"
    nivel_inicial = "ask"
    # La puerta manda Escape a sesiones que trabajan (reglas duras 15 y 7):
    # que eso pase lo decide él cada vez, nunca el modelo solo.
    siempre_pregunta = True
    solo_con_el_dueno = True
    quiere_aprobacion = True

    def comprobar(self, params):
        tarea_id, tarea = _tarea(params)
        if tarea["estado"] in orquestador.CERRADAS:
            raise ValueError(f"la tarea {tarea_id} ya estaba {tarea['estado']}")
        return _dicha(tarea_id, tarea)

    def detalle(self, con, params):
        return _detalle_de_tarea(params)

    def ejecutar(self, con, params, aprobada: bool = False):
        if not aprobada:
            raise RuntimeError(SOLO_CON_SU_SI)
        tarea_id, _ = _tarea(params)
        # La puerta de la web, entera: cierra la tarea, interrumpe a quien
        # trabaja con una tecla de la lista cerrada y toca el timbre.
        r = orquestador.detener(tarea_id, motivo="detenida por el secretario, con el sí del dueño")
        if not r.get("ok"):
            raise RuntimeError(f"no se detuvo: {r.get('motivo') or 'no se sabe por qué'}")
        ahora = orquestador.cargar(tarea_id)
        if not ahora or ahora["estado"] != orquestador.DETENIDA:
            raise RuntimeError("la tarea no quedó detenida")
        n = len(r.get("interrumpidas") or ())
        paradas = f"; interrumpí {n} {'sesión' if n == 1 else 'sesiones'} que trabajaba{'' if n == 1 else 'n'} para ella" if n else ""
        return f"tarea {tarea_id} detenida{paradas} (se reanuda en /orquestador o pidiéndomelo)"


class ReanudarTarea(Accion):
    id = "reanudar_tarea"
    gesto = "delegar"
    nombre = "Reanudar una tarea del orquestador"
    resumen = ("Vuelve a poner en marcha una tarea detenida, desde donde estaba, como el botón «Reanudar». "
               "Pregunta siempre, y no le añade ninguna nota tuya: eso sólo lo escribes tú.")
    descripcion = ("Reanuda una tarea del orquestador que está detenida, cuando el dueño lo pide. `tarea` es su "
                   "id (`hub_orquestador`). Sigue desde donde estaba; si hay otra en curso, vuelve a la cola. "
                   "No lleva nota: si el dueño quiere decirle algo al reanudarla, lo escribe él en "
                   "/orquestador. Siempre pide su permiso.")
    # 🔴 Sin `nota`: la puerta la entrega como «Lo que te dice el dueño», y
    # aquí la escribiría el modelo (351).
    parametros = {"type": "object", "properties": {"tarea": {"type": "string"}}, "required": ["tarea"]}
    riesgo = "reversible"
    nivel_inicial = "ask"
    # Pone a trabajar sesiones de sus proyectos (reglas duras 15 y 7). El
    # alcance por proyecto lo sigue pidiendo el orquestador, como siempre.
    siempre_pregunta = True
    solo_con_el_dueno = True
    quiere_aprobacion = True

    def comprobar(self, params):
        tarea_id, tarea = _tarea(params)
        if tarea["estado"] != orquestador.DETENIDA:
            raise ValueError(f"la tarea {tarea_id} no está detenida: está "
                             f"{orquestador.ETIQUETA.get(tarea['estado'], tarea['estado'])}")
        return _dicha(tarea_id, tarea)

    def detalle(self, con, params):
        return _detalle_de_tarea(params)

    def ejecutar(self, con, params, aprobada: bool = False):
        if not aprobada:
            raise RuntimeError(SOLO_CON_SU_SI)
        tarea_id, _ = _tarea(params)
        # Sólo el id: lo demás que traiga `params` no llega a la puerta.
        r = orquestador.reanudar(tarea_id)
        ahora = orquestador.cargar(tarea_id)
        if not ahora or ahora["estado"] in orquestador.CERRADAS:
            raise RuntimeError("la tarea no quedó reanudada")
        if r.get("en_cola"):
            return f"tarea {tarea_id} reanudada: vuelve a la cola y sigue cuando acabe la que está en curso"
        return f"tarea {tarea_id} reanudada: el orquestador sigue en su próximo latido (se ve en /orquestador)"


ACCIONES = [EncargarAlOrquestador(), TrabajarIdea(), ApuntarIdea(), DescartarIdea(), DetenerTarea(),
            ReanudarTarea()]
