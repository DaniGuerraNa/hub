"""El contrato de las piezas: fuentes, acciones y proveedores (definición 0.1 y 0.2, decisiones 300 y 306).

El núcleo sólo conoce esto. Una fuente o una acción nueva es **un archivo** en
`fuentes/` o `acciones/` que deja en el módulo `FUENTE` o `ACCIONES`; se
descubren solas. Quitarla es borrar el archivo. Nada más del secretario cambia.

🔴 **Las fuentes son de sólo lectura por construcción** (1.4 y alcance A): el
contrato no tiene ningún método para escribir. Contestar en nombre del dueño,
si algún día llega, será una acción —con su riesgo `sale-de-la-maquina` y su
nivel—, nunca un método de la fuente.

**Proveedores** (decisión 306). Lo que el secretario usa de **uno en uno**
—la agenda, el canal para avisar al teléfono— es una *capacidad*: un paquete
con un contrato y una fachada (`agenda.eventos`, `avisos.mandar`) y, dentro,
un archivo por proveedor (`agenda/google.py`, `avisos/telegram.py`). Quien
llama sólo conoce la fachada: cambiar Google por otro calendario, o Telegram
por Web Push, es añadir un archivo y elegirlo en `secretario.yml`, sin tocar
ni el prompt, ni las herramientas, ni las acciones. Las fuentes son lo mismo
en plural: se leen todas las encendidas, y la fachada es la memoria.
"""

from __future__ import annotations

import re

import importlib
import pkgutil
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from . import memoria


@dataclass
class Evento:
    """Lo mismo venga de donde venga: un mensaje, un correo, una reunión."""

    fuente: str
    id_externo: str
    fecha: str
    texto: str
    conversacion: str = ""
    autor: str = ""
    adjuntos: list = field(default_factory=list)
    #: Dónde se ve el original, si la fuente lo sabe (una URL del hub, un enlace).
    enlace: str = ""
    #: Si le hablan a él (decisión 332): `privado` (chat con él), `etiqueta`
    #: (lo etiquetan o le responden), `nombre` (lo nombran), `otros` (en un
    #: grupo, y no es para él) o vacío si la fuente no lo sabe.
    para_mi: str = ""


class Fuente:
    """De dónde lee el secretario (definición 1.x)."""

    id: str = ""
    nombre: str = ""
    descripcion: str = ""
    #: Cada cuántos segundos se lee. Lo caro, más espaciado (regla dura 14).
    intervalo: int = 300

    def disponible(self) -> str | None:
        """None si se puede leer; si no, la razón, dicha para el dueño."""
        return None

    def conversaciones(self) -> list[str]:
        """Las conversaciones que hay, para que el dueño elija cuáles se leen (1.2)."""
        return []

    def leer(self, cursor: str, ajustes: dict) -> tuple[list[Evento], str]:
        """Lo nuevo desde `cursor`. Devuelve los eventos y el cursor siguiente."""
        raise NotImplementedError


#: Lo que una acción puede romper. Manda sobre el nivel: lo `irreversible` y
#: lo que `sale-de-la-maquina` pregunta siempre, aunque el dueño lo ponga en
#: `auto` (decisión 303). Quien pregunte «¿ésta tiene techo?» lo hace con
#: `con_techo(accion)`, no mirando esta lista: también lo tiene la que declara
#: `siempre_pregunta` (C-0422).
RIESGOS = ("lectura", "reversible", "irreversible", "sale-de-la-maquina")
CON_TECHO = ("irreversible", "sale-de-la-maquina")
#: Cómo lo lee el dueño en Confianza (C-0231): salía «riesgo: reversible».
#: Con las palabras del párrafo que encabeza esa lista, que es el que explica
#: que lo que no tiene vuelta atrás pregunta siempre.
ROTULOS_RIESGO = {
    "lectura": "Sólo mira",
    "reversible": "Tiene vuelta atrás",
    "irreversible": "No tiene vuelta atrás",
    "sale-de-la-maquina": "Sale de tu máquina",
}
#: Cómo lee el dueño el estado de una solicitud cuando la palabra de dentro no
#: lo dice (C-0315). `cortada` es la del hub para lo que murió a medias; para
#: él es una duda, y eso es lo que tiene que leer. Los demás se enseñan tal cual.
ROTULOS_ESTADO = {"cortada": "no sé si se hizo"}
#: Los niveles no llevan rótulo a propósito: `auto`, `ask` y `never` son las
#: palabras de los guardrails de los proyectos, y el dueño ya las conoce así.
NIVELES = ("never", "ask", "auto")

#: Cómo se dice cada parámetro cuando una acción pide permiso (C-0231): salían
#: las claves del esquema («minutos_aviso: 30»). Son los de las acciones de
#: hoy; uno que no esté sale con `_` cambiado por espacio (`rotulo_parametro`),
#: así que añadir una acción sigue siendo sólo añadir su archivo.
ROTULOS_PARAMETROS = {
    "app": "app", "archivos": "archivos", "asunto": "asunto", "campo": "dato", "clave": "asunto",
    "cuerpo": "contenido", "descripcion": "descripción", "detalle": "detalle", "dominio": "dominio",
    "en_chat": "en el chat", "entrada": "entrada", "estado": "estado", "estado_ref": "documento de estado",
    "fin": "termina", "fuente": "de dónde", "id": "identificador", "idea": "idea", "inicio": "empieza",
    "minutos_aviso": "aviso, minutos antes", "noche": "con las últimas 24 h", "nombre": "nombre", "nota": "nota",
    "origen": "de dónde sale", "para_quien": "para quién", "pedido": "pedido", "plantilla": "plantilla",
    "proyecto": "proyecto", "que": "qué", "quien": "quién", "recordar_en": "aviso", "ruta": "ruta",
    "slot": "slot", "comando": "orden", "tema": "tema", "texto": "texto", "titulo": "título", "valor": "valor", "vence": "vence",
    "ventana": "ventana",
    # Los de las acciones que entran por una puerta del hub (C-0422).
    "activo": "activo", "contenedor": "contenedor", "razon": "por qué", "tarea": "tarea",
    # Los de los comandos preparados (C-0507).
    "preparado": "comando preparado", "valores": "valores", "hueco": "hueco", "fijos": "otros huecos",
}


def rotulo_parametro(nombre: str) -> str:
    """El rótulo de un parámetro, o su nombre con espacios si no tiene."""
    return ROTULOS_PARAMETROS.get(nombre) or str(nombre).replace("_", " ")


class Accion:
    """Algo que el secretario hace (definición 7.x)."""

    id: str = ""
    #: Lo que lee el modelo para decidir usarla.
    descripcion: str = ""
    #: Lo que lee el dueño en Confianza: dicho para él, no para el modelo.
    nombre: str = ""
    resumen: str = ""
    #: Esquema JSON de los parámetros: es lo que lee el modelo.
    parametros: dict = {"type": "object", "properties": {}}
    riesgo: str = "reversible"
    nivel_inicial: str = "ask"
    #: Lo que lleva en la mano el personaje mientras la hace (C-0166): uno de
    #: `personaje.GESTOS`. Su rótulo es `nombre`.
    gesto: str = "hacer"
    #: Si lo que hace lleva sus parámetros a otro sitio (un encargo, un
    #: lienzo, la nota de un slot, una idea). Con un dato suyo dentro (`misdatos`), pide
    #: permiso aunque esté en `auto` (decisión 382): el dato es suyo y él
    #: decide adónde va. Lo comprueba `herramientas.usar_accion`, no el prompt.
    saca_datos: bool = False
    #: Sólo cuando el dueño le habla en una conversación (C-0240, decisión 404):
    #: nunca desde un disparador, ni con `haz` ni con `pide`, que pueden llevar
    #: el texto de un tercero. Lo comprueban `herramientas.usar_accion` (sin
    #: hilo, no), `herramientas.todas` (sin `SECRETARIO_HILO` no se sirve) y
    #: `disparadores` (no se guarda en `haz`).
    solo_con_el_dueno: bool = False
    #: Los segundos que vale su sí: aprobada más tarde, `ejecutar_aprobadas` no
    #: la hace. Un sí horas después actuaría sobre otro estado de la máquina.
    caduca_s: int | None = None
    #: Nunca pasa a `auto` aunque tenga vuelta atrás (C-0422): el acto es del
    #: dueño —archivar un slot (regla dura 3), parar un contenedor (12),
    #: detener una tarea (15)— y lo hace su toque sobre esa solicitud, cada
    #: vez. No es un riesgo: llamarlo «irreversible» para que pregunte sería
    #: mentirle en Confianza. Su aviso sale sin Aprobar/Rechazar: se decide
    #: viendo el detalle de la solicitud —cuál es, de quién y cómo está
    #: ahora (`detalle`)—, que la notificación no enseña
    #: (`herramientas.usar_accion`).
    siempre_pregunta: bool = False
    #: Nada de lo que redacta el modelo queda escrito al pedirla (C-0418): no
    #: se le ofrece `motivo` y, si lo manda, se descarta; y de sus parámetros
    #: sólo pasan los declarados que sean un número o un sí/no. Es para la
    #: que borra algo que no debe sobrevivir en la solicitud, en la bitácora
    #: ni en el aviso (`olvidar_nota`): que no lo copie ahí era una frase de
    #: su descripción, y eso es prompt, no código. Lo que se guarda como
    #: motivo es sólo lo que devuelve `comprobar`. Lo hace `herramientas`.
    sin_texto_del_modelo: bool = False
    #: Los parámetros que SON un dato suyo de `misdatos` aunque aún no esté en
    #: la ficha: el que trae `proponer_dato`, se guarde o no (C-0431). La
    #: bitácora los tapa siempre, y también donde salgan en el motivo: tapar
    #: por la ficha no llega a lo que no se guardó.
    campos_propios: tuple[str, ...] = ()
    #: Si se le ofrece ahora al modelo: el mismo concepto y la misma forma
    #: que `herramientas.Herramienta.disponible` (C-0408, C-0389) —una función
    #: sin argumentos, con `staticmethod`, o None si no depende de nada—. La
    #: que no está configurada sólo puede fallar: servirla cuesta su esquema
    #: en cada turno y un intento con un error técnico. Confianza la sigue
    #: enseñando, «sin configurar» y con `como_configurar`, para que el dueño
    #: sepa que existe. Lo mira `se_ofrece`, nunca cada uno por su cuenta.
    disponible: Callable[[], bool] | None = None
    #: Dónde se configura, dicho para el dueño: lo lee en Confianza mientras
    #: `disponible` diga que no.
    como_configurar: str = ""

    def datos_propios(self, params) -> list[str]:
        """Los valores de `campos_propios` que trae `params`, para `misdatos.tapar(…, ademas=…)`."""
        if not isinstance(params, dict):
            return []
        return [str(params[k]) for k in self.campos_propios if str(params.get(k) or "").strip()]

    def comprobar(self, params: dict) -> str:
        """Antes de pedir permiso o de hacerla: lanza si no se puede ni pedir,
        y lo que devuelve se añade al motivo que lee el dueño."""
        return ""

    def detalle(self, con: sqlite3.Connection, params: dict) -> list[tuple[str, str]]:
        """Lo que su solicitud enseña mientras espera, además de sus parámetros:
        pares `(rótulo, valor)` leídos en ese instante, de la memoria (`con`)
        o de donde viva lo que toca.

        Es para lo que el dueño tiene que ver antes de decir que sí y **no
        debe quedar escrito** en la solicitud ni en la bitácora, ni salir en
        el aviso: el texto de la nota que pide olvidar (C-0418), el pedido de
        una tarea o el proyecto de un contenedor, que pueden nombrar a un
        cliente (regla dura 22), y cómo está ahora, que escrito al pedirlo
        sería viejo al aprobarlo (C-0422). Lo que devuelve `comprobar` sí se
        guarda, con el motivo; esto no. Sólo lee, y barato: se pinta en cada
        sondeo del chat (regla dura 14)."""
        return []

    def ejecutar(self, con: sqlite3.Connection, params: dict) -> str:
        """La hace y devuelve qué pasó, para el modelo y para la bitácora.

        🔴 Comprobando que salió (regla dura 17): un «hecho» sobre algo que no
        se hizo es la peor forma de fallar. Si no se puede comprobar, lanza.
        """
        raise NotImplementedError


class Proveedor:
    """Quien da una capacidad (decisión 306). Cada capacidad lo amplía con sus métodos."""

    id: str = ""
    nombre: str = ""

    def disponible(self) -> str | None:
        """None si se puede usar; si no, qué falta, dicho para el dueño."""
        return None


def proveedores(capacidad: str) -> dict[str, Proveedor]:
    """Los proveedores de `hub.secretario.<capacidad>`, por id."""
    out = {}
    for mod in _modulos(f"hub.secretario.{capacidad}"):
        p = getattr(mod, "PROVEEDOR", None)
        if isinstance(p, Proveedor):
            out[p.id] = p
    return out


def ajustes() -> dict:
    """`secretario.yml` entero, o `{}`. Es la única lectora (C-0495): había dos,
    y una dejaba pasar una lista o un texto suelto que luego reventaba en
    `.get`. Lo que no es un diccionario no es un ajuste: vale lo mismo que
    no tenerlo."""
    try:
        datos = yaml.safe_load((memoria.carpeta(crear=False) / "secretario.yml").read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return {}
    if datos is not None and not isinstance(datos, dict):
        # Se dice: si no, el secretario vuelve a lo de fábrica y nadie sabe por qué.
        print(f"[secretario] secretario.yml no tiene la forma «clave: valor» ({type(datos).__name__}): no lo leo",
              flush=True)
        return {}
    return datos or {}


def ajuste(clave: str):
    """Un valor de `secretario.yml`, o None."""
    return ajustes().get(clave)


def carpeta_de_fichas() -> Path | None:
    """Dónde están las fichas de cambios, si `secretario.yml` lo dice
    (`parte_fichas`). Son del flujo con que se desarrolla el hub y quien
    instala el producto no las tiene: entonces, None.

    No comprueba que exista, porque cada uno hace algo distinto si no: el
    parte y «Te espera» lo dicen como fallo, la lectura `fichas` se lo cuenta
    al modelo y Confianza se queda en el estado de la idea."""
    valor = ajuste("parte_fichas")
    return Path(str(valor)).expanduser() if valor else None


def proveedor(capacidad: str, por_omision: str) -> Proveedor:
    """El elegido en `secretario.yml` (`agenda: google`), o el de por omisión.

    Uno que no existe no cae en otro en silencio: se dice, porque avisar por
    un canal que el dueño no eligió es peor que no avisar.
    """
    elegido = ajuste(capacidad)
    todos = proveedores(capacidad)
    clave = elegido or por_omision
    if clave not in todos:
        raise LookupError(f"{capacidad}: no hay proveedor «{clave}» (hay: {', '.join(sorted(todos)) or 'ninguno'})")
    return todos[clave]


def _modulos(paquete: str) -> list:
    base = importlib.import_module(paquete)
    out = []
    for m in pkgutil.iter_modules(base.__path__):
        if m.name.startswith("_"):
            continue
        out.append(importlib.import_module(f"{paquete}.{m.name}"))
    return out


def fuentes() -> dict[str, Fuente]:
    out = {}
    for mod in _modulos("hub.secretario.fuentes"):
        f = getattr(mod, "FUENTE", None)
        if isinstance(f, Fuente):
            out[f.id] = f
    return out


def acciones() -> dict[str, Accion]:
    out = {}
    for mod in _modulos("hub.secretario.acciones"):
        for a in getattr(mod, "ACCIONES", ()):
            if isinstance(a, Accion):
                out[a.id] = a
    return out


def se_ofrece(cosa) -> bool:
    """Si una herramienta o una acción se le ofrece ahora al modelo: lo dice
    su `disponible` (C-0408, C-0389). Sólo para ésas: el `disponible` de una
    fuente o de un proveedor devuelve qué falta, no un sí.

    Uno que revienta cuenta como que no: la lista que se sirve no se cae por
    una configuración rota, y quien la use igual dice qué falta."""
    disponible = getattr(cosa, "disponible", None)
    if disponible is None:
        return True
    try:
        return bool(disponible())
    except Exception:  # noqa: BLE001 — el porqué lo dice la pieza al usarla
        return False


def nombre_de_accion(accion_id: str, catalogo: dict[str, Accion] | None = None) -> str:
    """Cómo se llama una acción para el dueño: el nombre que tiene en
    Confianza. Una que ya no existe —o lo que apunta el servicio sin ser una
    acción, un disparador o el triaje—, su id sin guiones bajos.

    Una sola regla para Pendientes, la tarjeta del chat, la bitácora y el
    «No lo hago…» (C-0395): el chat lo decía con el id, `escribir_en_sesion`.
    `catalogo`: el de `acciones()`, si quien llama ya lo tiene; para no
    recorrer los módulos en cada fila."""
    a = (acciones() if catalogo is None else catalogo).get(accion_id)
    return (a.nombre or a.id) if a else str(accion_id).replace("_", " ")


def params_tapados(accion_id: str, params):
    """Los parámetros de `accion_id` como pueden quedarse guardados: con sus
    datos tapados (`misdatos.tapar`), también los suyos que no están en la
    ficha (`Accion.campos_propios`). Para la bitácora y para la solicitud ya
    resuelta (C-0431): la de la pantalla y la del servicio, la misma."""
    from . import misdatos
    accion = acciones().get(accion_id)
    return misdatos.tapar(params, accion.datos_propios(params) if accion else [])


def solicitud_tapada(con: sqlite3.Connection, sid: int):
    """Los parámetros de la solicitud `sid`, tapados, para cerrarla con ellos
    (`memoria.resolver_solicitud(…, params=…)`). None si no existe."""
    import json
    fila = con.execute("SELECT accion, params FROM solicitud WHERE id = ?", (sid,)).fetchone()
    if fila is None:
        return None
    try:
        params = json.loads(fila["params"] or "{}")
    except ValueError:
        params = {}
    return params_tapados(fila["accion"], params)


# ───────────────────────────── ajustes de fuentes ─────────────────────────────


def _fuentes_yml(crear: bool = False) -> Path:
    return memoria.carpeta(crear=crear) / "fuentes.yml"


def ajustes_fuentes() -> dict:
    """`fuentes.yml`: cuáles están encendidas y qué conversaciones leen (1.2).

    Por omisión sólo está encendida la del propio hub: leer una cuenta de
    Telegram o un correo es algo que el dueño enciende, no algo que pasa.
    """
    try:
        datos = yaml.safe_load(_fuentes_yml().read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        datos = {}
    datos.setdefault("hub", {}).setdefault("activa", True)
    return datos


def guardar_ajustes_fuentes(datos: dict) -> None:
    _fuentes_yml(crear=True).write_text(yaml.safe_dump(datos, allow_unicode=True, sort_keys=True), encoding="utf-8")


def _sin_tildes(texto: str) -> str:
    import unicodedata
    t = unicodedata.normalize("NFKD", texto.lower())
    return "".join(c for c in t if not unicodedata.combining(c))


def alias_del_dueno(ajustes: dict) -> list[str]:
    """Cómo lo llaman: `alias:` en los ajustes de la fuente o, si no, el `dueno`
    de `secretario.yml`."""
    alias = ajustes.get("alias")
    if isinstance(alias, str):
        alias = [alias]
    if not alias:
        alias = [ajuste("dueno") or ""]
    return [str(a).strip() for a in alias if str(a or "").strip()]


def para_mi(texto: str, alias: list[str], *, grupo: bool, etiqueta: bool = False) -> str:
    """A quién va un mensaje (decisión 332). En un chat privado, a él. En un
    grupo, sólo si lo etiquetan o le responden (lo sabe la fuente) o si lo
    nombran por palabra entera —«Ana» no casa con «Anabel»—. Un alias puede
    ser su usuario («MiUsuario»): así casa la etiqueta escrita en el texto."""
    if not grupo:
        return "privado"
    if etiqueta:
        return "etiqueta"
    t = _sin_tildes(texto or "")
    for a in alias:
        if re.search(rf"(?<!\w){re.escape(_sin_tildes(a))}(?!\w)", t):
            return "nombre"
    return "otros"


def conversacion_admitida(ajustes: dict, conversacion: str) -> bool:
    """`incluir` (si hay lista) manda; `excluir` quita. Sin listas, todas."""
    nombre = (conversacion or "").strip().lower()
    incluir = [c.strip().lower() for c in ajustes.get("incluir") or []]
    excluir = [c.strip().lower() for c in ajustes.get("excluir") or []]
    if nombre in excluir:
        return False
    return not incluir or nombre in incluir


# ───────────────────────────── niveles de confianza ─────────────────────────────


def _permisos_yml(crear: bool = False) -> Path:
    return memoria.carpeta(crear=crear) / "permisos.yml"


def niveles() -> dict[str, str]:
    try:
        datos = yaml.safe_load(_permisos_yml().read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        datos = {}
    return {k: v for k, v in datos.items() if v in NIVELES}


def con_techo(accion: Accion) -> bool:
    """Si la acción no puede estar en `auto`: por lo que puede romper
    (`CON_TECHO`, 303) o porque el acto es del dueño (`siempre_pregunta`).
    La única pregunta que hacen `nivel`, Confianza y el aviso al teléfono."""
    return accion.riesgo in CON_TECHO or bool(accion.siempre_pregunta)


def nivel(accion: Accion) -> str:
    """El nivel que manda ahora: el del dueño, o el inicial de la acción. Con
    techo para lo que no tiene vuelta atrás y para lo que pregunta siempre."""
    n = niveles().get(accion.id, accion.nivel_inicial)
    if n == "auto" and con_techo(accion):
        return "ask"
    return n


def poner_nivel(accion_id: str, nuevo: str) -> None:
    if nuevo not in NIVELES:
        raise ValueError("nivel no válido")
    if accion_id not in acciones():
        raise ValueError("esa acción no existe")
    datos = niveles()
    datos[accion_id] = nuevo
    _permisos_yml(crear=True).write_text(yaml.safe_dump(datos, sort_keys=True), encoding="utf-8")
