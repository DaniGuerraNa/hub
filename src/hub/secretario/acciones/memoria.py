"""Acciones sobre su propia memoria: anotar, comprometer, cerrar, callar un asunto,
corregir una nota o el texto de un compromiso, olvidar una nota, y poner o
quitar el modo inglés.

Van en `auto`: escriben sólo en la base del secretario, se ven en su pantalla y
se corrigen o se borran desde ahí (3.2). Preguntar cada vez que quiere apuntar
algo haría inútil que tome notas solo (3.1). La excepción es olvidar una nota
(C-0418): borrar es acto del dueño, y pregunta siempre.
"""

from __future__ import annotations

from .. import asuntos, conversacion, memoria, misdatos
from ..piezas import Accion
from ..tiempo import a_local, a_utc, tiene_hora


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
                   "secretario le avisará al teléfono a esa hora; si sólo hay `vence`, 30 min antes (un día sin "
                   "hora, esa mañana a las 9), y si ya pasó, sin aviso. Si es un asunto suyo que pidió anotar "
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
        vence = a_utc(params.get("vence"))
        # Sin hora de aviso, la del triaje (C-0066): el plazo como aviso llegaba tarde.
        recordar_en = (a_utc(params.get("recordar_en"))
                       or memoria.cuando_avisar(vence, con_hora=tiene_hora(params.get("vence"))))
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
                   "aviso. `vence` y `recordar_en` en hora local, 'AAAA-MM-DDTHH:MM'. Si sólo cambia `vence`, el "
                   "aviso se mueve con él, a la misma antelación (30 min si no tenía).")
    parametros = {"type": "object", "properties": {
        "id": {"type": "integer"}, "vence": {"type": "string"}, "recordar_en": {"type": "string"}},
        "required": ["id"]}
    riesgo = "reversible"
    nivel_inicial = "auto"

    def ejecutar(self, con, params):
        if not (params.get("vence") or params.get("recordar_en")):
            raise ValueError("falta la fecha nueva")
        memoria.reprogramar(con, int(params["id"]), vence=a_utc(params.get("vence")),
                            recordar_en=a_utc(params.get("recordar_en")), con_hora=tiene_hora(params.get("vence")))
        f = con.execute("SELECT recordar_en FROM compromiso WHERE id = ?", (int(params["id"]),)).fetchone()
        if not f:
            raise ValueError("ese compromiso no existe")
        if not f["recordar_en"]:
            return f"compromiso {params['id']}: sin aviso, el plazo ya pasó"
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


def _numero(params, de_que: str) -> int:
    """El `id` que manda el modelo, o un error que le dice de dónde sacarlo."""
    valor = params.get("id")
    try:
        # `bool` es un `int` para Python: «true» no es la nota 1.
        if isinstance(valor, bool):
            raise ValueError
        return int(valor)
    except (TypeError, ValueError):
        raise ValueError(f"`id` es el número de {de_que}") from None


def _nota(con, params):
    nid = _numero(params, "la nota (sale en `buscar`, o al anotarla)")
    fila = con.execute("SELECT * FROM nota WHERE id = ?", (nid,)).fetchone()
    if fila is None:
        raise ValueError(f"no hay ninguna nota {nid}: búscala con `buscar`")
    return fila


#: Lo que cabe de lo de antes: la bitácora guarda 2 000 caracteres del resultado.
MAX_DE_ANTES = 1500


def _de_antes(texto: str) -> tuple[str, str]:
    """Lo que decía, para la bitácora —es con lo que se deshace una
    corrección—, y el aviso de si ya no se puede deshacer entera.

    Va sin sus datos ni lo que parece una llave (382, regla dura 5): la
    bitácora no puede ser donde sobrevive lo que se quiso quitar. Y acotado.
    Cualquiera de las dos cosas hace que lo guardado no sea lo que había: se
    dice, para que «tiene vuelta atrás» no prometa de más."""
    original = str(texto or "").strip()
    guardado = misdatos.tapar(original)
    que = ["tapado"] if guardado != original else []
    if len(guardado) > MAX_DE_ANTES:
        guardado = guardado[: MAX_DE_ANTES - 1].rstrip() + "…"
        que.append("recortado")
    aviso = f" (lo anterior quedó {' y '.join(que)} en la bitácora: no se recupera entero)" if que else ""
    return guardado, aviso


class EditarNota(Accion):
    id = "editar_nota"
    gesto = "anotar"
    nombre = "Corregir una nota"
    resumen = ("Cambia el texto (y, si se lo dices, el tema) de una nota de su memoria. Lo que decía antes y "
               "su tema quedan en la bitácora, por si hay que volver; si era muy larga o llevaba una llave, "
               "queda recortado o tapado y te lo dice.")
    descripcion = ("Corrige una nota que ya existe cuando el dueño dice que está mal («eso que anotaste no es "
                   "el martes, es el jueves»). `id`: el de la nota (sale en `buscar`, con `tipo: nota`, o al "
                   "anotarla). `texto`: la nota entera ya corregida, no sólo el trozo que cambia. `tema` sólo "
                   "si también cambia. Para quitarla del todo no la dejes vacía: usa `olvidar_nota`.")
    parametros = {"type": "object", "properties": {
        "id": {"type": "integer"}, "texto": {"type": "string"}, "tema": {"type": "string"}},
        "required": ["id", "texto"]}
    riesgo = "reversible"
    nivel_inicial = "auto"
    # Sólo con él delante (404): que un mensaje de otro, dentro de un `pide`,
    # no le reescriba lo que tiene apuntado.
    solo_con_el_dueno = True

    def ejecutar(self, con, params):
        fila = _nota(con, params)
        texto = str(params.get("texto") or "").strip()
        if not texto:
            raise ValueError("una nota no se queda vacía: para quitarla, usa `olvidar_nota`")
        tema = params.get("tema")
        # La misma puerta que la pantalla Memoria.
        memoria.editar_nota(con, fila["id"], texto, str(tema) if isinstance(tema, str) and tema.strip() else None)
        ahora = con.execute("SELECT texto FROM nota WHERE id = ?", (fila["id"],)).fetchone()
        if ahora is None or ahora["texto"] != texto:
            raise RuntimeError("la nota no quedó corregida")
        antes, aviso = _de_antes(fila["texto"])
        # El tema también: corregir puede cambiarlo, y sin él no hay vuelta.
        tema_de_antes = f"; su tema era «{str(fila['tema'])[:200]}»" if fila["tema"] else ""
        return f"nota {fila['id']} corregida{aviso}; antes decía: «{antes}»{tema_de_antes}"


class EditarCompromiso(Accion):
    id = "editar_compromiso"
    gesto = "compromisos"
    nombre = "Cambiar el texto de un compromiso"
    resumen = ("Corrige lo que dice un compromiso abierto, sin moverle el plazo ni el aviso. Lo que decía "
               "antes queda en la bitácora.")
    descripcion = ("Cambia el texto de un compromiso abierto (por su id, de `compromisos`) cuando el dueño lo "
                   "corrige («cámbialo a \"llamar al taller\"»). `que`: el texto entero ya corregido. No toca "
                   "las fechas: para eso, `reprogramar_compromiso`.")
    parametros = {"type": "object", "properties": {"id": {"type": "integer"}, "que": {"type": "string"}},
                  "required": ["id", "que"]}
    riesgo = "reversible"
    nivel_inicial = "auto"
    solo_con_el_dueno = True

    def ejecutar(self, con, params):
        cid = _numero(params, "el compromiso (sale en `compromisos`)")
        fila = con.execute("SELECT * FROM compromiso WHERE id = ?", (cid,)).fetchone()
        if fila is None:
            raise ValueError(f"no hay ningún compromiso {cid}: míralos con `compromisos`")
        if fila["estado"] != "abierto":
            raise ValueError(f"el compromiso {cid} ya está {fila['estado']}: sólo se corrigen los abiertos")
        que = str(params.get("que") or "").strip()
        # La misma puerta que «Editar» en Pendientes, con sus fechas tal cual:
        # así el aviso no vuelve a quedar pendiente ni cambia de hora.
        memoria.editar_compromiso(con, cid, que=que, vence=fila["vence"], recordar_en=fila["recordar_en"])
        ahora = con.execute("SELECT que FROM compromiso WHERE id = ?", (cid,)).fetchone()
        if ahora is None or ahora["que"] != que:
            raise RuntimeError("el compromiso no quedó corregido")
        antes, aviso = _de_antes(fila["que"])
        dicho = f"compromiso {cid} corregido{aviso}; antes decía: «{antes}»"
        if str(fila["origen"] or "").startswith("proyecto:"):
            # Mientras siga abierto, lo último que diga el proyecto manda
            # (`de_proyectos`): que no se sorprenda si vuelve a cambiar.
            dicho += ". Lo dejó un proyecto: si el proyecto lo vuelve a escribir, valdrá lo suyo"
        return dicho


class OlvidarNota(Accion):
    id = "olvidar_nota"
    gesto = "anotar"
    nombre = "Olvidar una nota"
    resumen = ("Borra una nota de su memoria cuando tú se lo pides, y tapa lo que la bitácora guardaba de "
               "ella. Pregunta siempre, enseñándote cuál: una nota olvidada no se recupera. Lo que hablasteis "
               "de ella en el chat sigue ahí.")
    descripcion = ("Borra una nota cuando el dueño dice que la olvide («olvida lo del taller»). `id`: el de la "
                   "nota (sale en `buscar`, con `tipo: nota`). Si no sabes cuál es, búscala y pregúntale; "
                   "nunca borres por tu cuenta ni para ordenar. Siempre pide su permiso: dile que se lo "
                   "pediste, no que ya la olvidaste. Sólo lleva el `id`: él ve la nota entera al decidir. "
                   "Para corregirla, `editar_nota`.")
    parametros = {"type": "object", "properties": {"id": {"type": "integer"}}, "required": ["id"]}
    # Una nota borrada no vuelve, y a diferencia de `editar_nota` aquí su
    # texto no se guarda en la bitácora: olvidar es olvidar. Y lo que ya
    # guardaba de ella —de anotarla y de corregirla— se tapa al hacerlo.
    riesgo = "irreversible"
    nivel_inicial = "ask"
    # Decidido por el dueño (C-0418): borrar es acto suyo, cada vez.
    siempre_pregunta = True
    solo_con_el_dueno = True
    # Sólo `ejecutar_aprobadas` sabe que la aprobó (como `cambiar_en_pc`).
    quiere_aprobacion = True
    # 🔴 Ni motivo ni texto del modelo: lo copiaría de la nota y quedaría en
    # la solicitud, en la bitácora y en el aviso después de «olvidarla».
    sin_texto_del_modelo = True

    def comprobar(self, params):
        # `comprobar` no recibe la conexión: se abre una para leer y se cierra.
        c = memoria.conectar()
        try:
            fila = _nota(c, params)
        finally:
            c.close()
        # 🔴 Sólo cuál y de cuándo, sin su texto: esto se guarda con la
        # solicitud y en la bitácora, y sale en el aviso. Si llevara el texto,
        # «olvídala» lo dejaría escrito en tres sitios. El texto lo enseña
        # `detalle`, mientras espera y sin guardarlo.
        return f"nota {fila['id']}, anotada el {a_local(fila['creada'])}"

    def detalle(self, con, params):
        try:
            fila = _nota(con, params)
        except ValueError:
            return [("nota", "ya no existe")]
        return [("nota", fila["texto"]), *([("tema", fila["tema"])] if fila["tema"] else [])]

    def ejecutar(self, con, params, aprobada: bool = False):
        if not aprobada:
            raise RuntimeError("esto sólo se hace con el sí del dueño a esta solicitud")
        fila = _nota(con, params)
        # No `borrar_nota`, que sólo quita la fila: `olvidar_nota` tapa además,
        # en la misma transacción, lo que la bitácora y las solicitudes
        # guardaban de ella (al anotarla, al corregirla, el «antes decía»).
        memoria.olvidar_nota(con, fila["id"])
        if con.execute("SELECT 1 FROM nota WHERE id = ?", (fila["id"],)).fetchone():
            raise RuntimeError("la nota no quedó borrada")
        return f"nota {fila['id']} olvidada"


class ModoIngles(Accion):
    id = "modo_ingles"
    gesto = "hacer"
    nombre = "Poner o quitar el modo inglés"
    resumen = ("Pone o quita la práctica de inglés, como el botón «English» del chat. Con el modo puesto, "
               "quitarlo te pide permiso: en la práctica no hace nada solo.")
    descripcion = ("Pone (`activo`: true) o quita (`activo`: false) el modo inglés cuando el dueño lo pide "
                   "(«pon el modo inglés», «let's switch back to Spanish»). Es el mismo interruptor que su botón "
                   "«English»: se queda puesto hasta que lo quite. Con el modo puesto, quitarlo sale como "
                   "permiso suyo; díselo y no lo des por quitado.")
    parametros = {"type": "object", "properties": {"activo": {"type": "boolean"}}, "required": ["activo"]}
    riesgo = "reversible"
    nivel_inicial = "auto"
    # Sólo con él delante (C-0422): es lo que impide que un `pide`, con el
    # mensaje de un tercero, quite el freno de la práctica (354).
    solo_con_el_dueno = True

    def ejecutar(self, con, params):
        activo = params.get("activo")
        if not isinstance(activo, bool):
            raise ValueError("di `activo`: true para ponerlo o false para quitarlo")
        # La misma puerta que el botón (`/api/secretario/ingles`).
        conversacion.poner_ingles(con, activo)
        if conversacion.ingles(con) is not activo:
            raise RuntimeError("el modo inglés no quedó como se pidió")
        return ("modo inglés puesto: se queda hasta que lo quite, y mientras dura no hago nada sin su permiso"
                if activo else "modo inglés quitado")


ACCIONES = [Anotar(), Comprometer(), CerrarCompromiso(), Reprogramar(), CallarAsunto(), EditarNota(),
            EditarCompromiso(), OlvidarNota(), ModoIngles()]
