"""Las herramientas opcionales del hub: una lista cerrada, apagadas de fábrica (decisión 438).

Una herramienta opcional es algo que viaja con el hub pero que usará una sola
de las personas que lo instalan: hoy, el Puente KVM, que sólo sirve a quien
tiene un JetKVM. Apagada no sale en ningún menú y las pantallas se pintan como
si no existiera; se enciende y se apaga en Ajustes → Guía, con un formulario
normal.

Por instalación y no por aparato, al revés que la interfaz nueva (413): lo que
decide es si en esta máquina hay con qué usarla, no desde qué navegador se
mira.

🔴 **Un dato que sólo vive aquí** (regla dura 1): `HUB_HOME/opcionales.json`
no se reconstruye escaneando, y la copia diaria no lo lleva. Perderlo sólo
las deja apagadas, que es como vienen. Al leerlo, ausente, ilegible o con una
clave que no está en `OPCIONALES` vale lo mismo: apagada. Al escribirlo, uno
ilegible no se pisa (`Ilegible`).

Módulo hoja: sólo sabe qué hay y qué está encendido. Lo que cada herramienta
hace es de su propio módulo (`puente.py`).
"""

from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass
from pathlib import Path

from . import config, recordar


@dataclass(frozen=True)
class Opcional:
    """Una herramienta opcional: cómo se llama, dónde está su pantalla, su
    icono (de `_ui.html`) y qué es, dicho en llano para la Guía."""

    nombre: str
    ruta: str
    icono: str
    que_es: str
    quien: str


#: La lista cerrada. Lo que no esté aquí no se guarda ni se obedece: una
#: herramienta nueva es su entrada aquí, su pantalla y una decisión escrita.
OPCIONALES: dict[str, Opcional] = {
    "puente-kvm": Opcional(
        nombre="Puente KVM",
        ruta="/puente",
        icono="teclado",
        que_es="Deja que Claude lea y escriba en un Mac de otra persona a través de un JetKVM, "
               "sin instalar nada en ese Mac. Es un programa aparte: el hub sólo dice cómo está "
               "y te lleva a él.",
        quien="Sólo tiene sentido si tienes un JetKVM.",
    ),
}

_cerrojo = threading.Lock()


def archivo() -> Path:
    return config.HUB_HOME / "opcionales.json"


def _leer(ruta: Path) -> frozenset[str]:
    """Lo encendido según el archivo; cualquier cosa rara, nada encendido."""
    try:
        datos = json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return frozenset()
    lista = datos.get("encendidas") if isinstance(datos, dict) else None
    if not isinstance(lista, list):
        return frozenset()
    return frozenset(c for c in lista if isinstance(c, str) and c in OPCIONALES)


def encendidas() -> frozenset[str]:
    """Las herramientas encendidas en esta instalación.

    Lo pregunta el raíl en cada pantalla: se recuerda mientras el archivo no
    cambie (`recordar.por_archivo`), y un `frozenset` no hace falta copiarlo.
    """
    return recordar.por_archivo(archivo(), _leer)


def encendida(clave: str) -> bool:
    return clave in encendidas()


class Ilegible(Exception):
    """`opcionales.json` existe y no se entiende: no se escribe encima."""


def _leer_para_escribir(ruta: Path) -> dict:
    """Lo que hay en el archivo, entero, para escribir encima de ello.

    Al revés que `_leer`, aquí lo raro no vale «apagado»: un archivo que
    existe y no se entiende lo pudo dejar otra versión o una mano, y
    reescribirlo borraría lo que dijera. Se dice y no se toca."""
    try:
        texto = ruta.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {"encendidas": []}
    except OSError as exc:
        raise Ilegible(f"no se puede leer {ruta}: {exc}") from exc
    try:
        datos = json.loads(texto)
    except ValueError as exc:
        raise Ilegible(f"{ruta} no es un JSON que se entienda; arréglalo o bórralo") from exc
    lista = datos.get("encendidas", []) if isinstance(datos, dict) else None
    if not isinstance(lista, list) or not all(isinstance(c, str) for c in lista):
        raise Ilegible(f"{ruta} no tiene la forma de siempre; arréglalo o bórralo")
    return datos


def poner(clave: str, encendida: bool) -> frozenset[str]:
    """Enciende o apaga una herramienta de la lista y devuelve lo encendido.

    Una clave fuera de `OPCIONALES` lanza `ValueError`, y un archivo que
    existe y no se entiende, `Ilegible`: en los dos casos no se escribe nada.
    Lo que el archivo diga y esta versión no conozca —otra herramienta, otra
    clave— se conserva tal cual. Se escribe aparte, se lleva al disco y se
    renombra: un corte a mitad deja el archivo de antes, nunca uno a medias.
    """
    if clave not in OPCIONALES:
        raise ValueError(f"no hay ninguna herramienta opcional «{clave}»")
    with _cerrojo:
        ruta = archivo()
        # En fresco y no por `encendidas`: lo que se escribe parte del disco.
        datos = _leer_para_escribir(ruta)
        lista = [c for c in datos.get("encendidas", []) if c != clave]
        if encendida:
            lista.append(clave)
        ruta.parent.mkdir(parents=True, exist_ok=True)
        aparte = ruta.with_name(ruta.name + ".tmp")
        with aparte.open("w", encoding="utf-8") as f:
            f.write(json.dumps({**datos, "encendidas": sorted(set(lista))}, ensure_ascii=False) + "\n")
            f.flush()
            os.fsync(f.fileno())
        aparte.replace(ruta)
    return frozenset(c for c in lista if c in OPCIONALES)
