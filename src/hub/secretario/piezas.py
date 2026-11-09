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
#: `auto` (decisión 303).
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
    "slot": "slot", "tema": "tema", "texto": "texto", "titulo": "título", "valor": "valor", "vence": "vence",
    "ventana": "ventana",
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


def ajuste(clave: str):
    """Un valor de `secretario.yml`, o None."""
    try:
        return (yaml.safe_load((memoria.carpeta() / "secretario.yml").read_text(encoding="utf-8")) or {}).get(clave)
    except (OSError, yaml.YAMLError, AttributeError):
        return None


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


# ───────────────────────────── ajustes de fuentes ─────────────────────────────


def _fuentes_yml() -> Path:
    return memoria.carpeta() / "fuentes.yml"


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
    _fuentes_yml().write_text(yaml.safe_dump(datos, allow_unicode=True, sort_keys=True), encoding="utf-8")


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
        from .conversacion import ajustes as ajustes_secretario
        alias = [ajustes_secretario().get("dueno") or ""]
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


def _permisos_yml() -> Path:
    return memoria.carpeta() / "permisos.yml"


def niveles() -> dict[str, str]:
    try:
        datos = yaml.safe_load(_permisos_yml().read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        datos = {}
    return {k: v for k, v in datos.items() if v in NIVELES}


def nivel(accion: Accion) -> str:
    """El nivel que manda ahora: el del dueño, o el inicial de la acción. Con
    techo para lo que no tiene vuelta atrás."""
    n = niveles().get(accion.id, accion.nivel_inicial)
    if n == "auto" and accion.riesgo in CON_TECHO:
        return "ask"
    return n


def poner_nivel(accion_id: str, nuevo: str) -> None:
    if nuevo not in NIVELES:
        raise ValueError("nivel no válido")
    if accion_id not in acciones():
        raise ValueError("esa acción no existe")
    datos = niveles()
    datos[accion_id] = nuevo
    _permisos_yml().write_text(yaml.safe_dump(datos, sort_keys=True), encoding="utf-8")
