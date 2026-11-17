"""Las conversaciones con Claude Code que lleva el puente: cuáles hay y cuál está abierta.

El puente lleva **su propia lista** (`PUENTE_HOME/conversaciones.json`) y no
lee los archivos internos de Claude Code: cada conversación es un UUID que
genera el puente y que se le da a Claude Code al crearla (`--session-id`), con
el nombre de la persona y el modelo con que se abrió.

**Una sola viva a la vez**: dos Claudes abiertos podrían teclear en el mismo
Mac con un único control. Cambiar de conversación cierra la abierta —Claude
Code ya la tiene guardada— y abre la otra (ver `terminal.abrir`).

Los nombres pueden ser nombres de objetos del trabajo: no van a la bitácora ni
al diagnóstico. Este archivo es de la persona; no se reconstruye de ninguna
parte: si se borra, las conversaciones siguen en Claude Code (su `/resume` las
encuentra), pero el puente deja de listarlas.
"""

from __future__ import annotations

import json
import re
import threading
import time
import unicodedata
import uuid
from dataclasses import asdict, dataclass, fields

from . import config

UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
NOMBRE_MAX = 60
_cerrojo = threading.Lock()


@dataclass
class Conversacion:
    id: str
    nombre: str
    creada: float
    usada: float
    modelo: str  # el id exacto con que se abrió por última vez; "" = el de Claude Code
    espacio: str  # la carpeta donde nació: Claude Code guarda ahí sus conversaciones
    claude_code: str = ""  # la versión de Claude Code con que se abrió por última vez

    def publica(self) -> dict:
        d = asdict(self)
        d["modelo_texto"] = config.texto_modelo(self.modelo)
        d["otra_carpeta"] = self.espacio != str(config.espacio())
        return d


def validar_id(id_: str) -> str:
    """Un UUID en minúsculas y nada más: es lo único que llega a la línea de órdenes."""
    if not isinstance(id_, str) or not UUID.fullmatch(id_):
        raise ValueError("identificador de conversación inválido")
    return id_


def limpiar_nombre(nombre: str) -> str:
    """Sin caracteres de control ni saltos, espacios juntos, y no más de NOMBRE_MAX.

    Los de control y formato (escapes de terminal, marcas de dirección que
    dan la vuelta al texto) se quitan; tabuladores y saltos pasan a espacio.
    """
    texto = "".join(" " if c in "\t\n\r\x0b\x0c" else "" if unicodedata.category(c)[0] == "C" else c
                    for c in str(nombre or ""))
    texto = " ".join(texto.split())[:NOMBRE_MAX].strip()
    return texto or time.strftime("Conversación del %d-%m %H:%M")


# ── el archivo ──────────────────────────────────────────────────────────────
def _ruta():
    return config.hogar() / "conversaciones.json"


def _leer() -> dict:
    try:
        datos = json.loads(_ruta().read_text())
    except (OSError, json.JSONDecodeError):
        return {"actual": None, "conversaciones": []}
    campos = {f.name for f in fields(Conversacion)}
    lista = []
    for d in datos.get("conversaciones", []):
        if isinstance(d, dict) and UUID.fullmatch(str(d.get("id", ""))):
            lista.append(Conversacion(**{k: v for k, v in d.items() if k in campos}))
    actual = datos.get("actual")
    return {"actual": actual if any(c.id == actual for c in lista) else None, "conversaciones": lista}


def _escribir(datos: dict) -> None:
    ruta = _ruta()
    tmp = ruta.with_suffix(".tmp")
    tmp.write_text(json.dumps({"actual": datos["actual"],
                               "conversaciones": [asdict(c) for c in datos["conversaciones"]]},
                              ensure_ascii=False, indent=1))
    tmp.replace(ruta)


# ── consultas ───────────────────────────────────────────────────────────────
def todas() -> list[Conversacion]:
    return sorted(_leer()["conversaciones"], key=lambda c: c.usada, reverse=True)


def buscar(id_: str) -> Conversacion | None:
    return next((c for c in _leer()["conversaciones"] if c.id == id_), None)


def actual() -> Conversacion | None:
    datos = _leer()
    return next((c for c in datos["conversaciones"] if c.id == datos["actual"]), None)


# ── cambios ─────────────────────────────────────────────────────────────────
def nueva(nombre: str, modelo: str) -> Conversacion:
    ahora = time.time()
    c = Conversacion(id=str(uuid.uuid4()), nombre=limpiar_nombre(nombre), creada=ahora, usada=ahora,
                     modelo=config.validar_modelo(modelo), espacio=str(config.espacio()))
    with _cerrojo:
        datos = _leer()
        datos["conversaciones"].append(c)
        _escribir(datos)
    return c


def marcar_abierta(id_: str | None, modelo: str | None = None, claude_code: str | None = None) -> None:
    """La que corre ahora en la terminal (None: ninguna del registro)."""
    with _cerrojo:
        datos = _leer()
        datos["actual"] = id_
        for c in datos["conversaciones"]:
            if c.id == id_:
                c.usada = time.time()
                if modelo is not None:
                    c.modelo = modelo
                if claude_code is not None:
                    c.claude_code = claude_code
        _escribir(datos)


def tocar(id_: str | None) -> None:
    """Se acaba de usar (lo dicen los hooks de Claude Code con su `session_id`)."""
    if not id_ or not UUID.fullmatch(str(id_)):
        return
    with _cerrojo:
        datos = _leer()
        for c in datos["conversaciones"]:
            if c.id == id_:
                c.usada = time.time()
                _escribir(datos)
                return


def renombrar(id_: str, nombre: str) -> Conversacion:
    validar_id(id_)
    with _cerrojo:
        datos = _leer()
        c = next((c for c in datos["conversaciones"] if c.id == id_), None)
        if c is None:
            raise KeyError("no existe esa conversación")
        c.nombre = limpiar_nombre(nombre)
        _escribir(datos)
        return c


def quitar(id_: str) -> None:
    """Fuera de la lista del puente. En Claude Code sigue guardada: no se borra nada."""
    validar_id(id_)
    with _cerrojo:
        datos = _leer()
        datos["conversaciones"] = [c for c in datos["conversaciones"] if c.id != id_]
        if datos["actual"] == id_:
            datos["actual"] = None
        _escribir(datos)
