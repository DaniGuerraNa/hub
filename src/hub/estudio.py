"""El estudio visto desde el hub: si contesta, sus proyectos y dónde se abre (decisión 461).

El estudio es un programa aparte —el kit `estudio`, con su unidad de usuario
`estudio` y su web sólo en 127.0.0.1— donde una persona que no programa habla
con Claude Code y revisa su aplicación. Como con el Puente KVM (438), el hub
**sólo apunta**: le hace dos preguntas GET a loopback por el cliente común
(`consulta_local`), con un plazo absoluto para las dos juntas, y enseña los
enlaces para abrirlo en una pestaña aparte.

🔴 Lo que esto no hace, y no debe hacer nunca:

- **Un POST al estudio.** Contestar, aprobar y comentar son de la persona,
  en la pantalla del estudio: el hub no tiene botón para nada de eso.
- **Hacer de proxy** de su web ni embeberla: la puerta de `/acceso` no la
  cubre (regla dura 8), y dentro habla con Claude Code. Se abre en la PC
  donde corre y en ningún otro sitio. La dirección es literal.
- **Dejar pasar lo que no está en su lista.** De la salud, `vivo` y la
  versión; de cada proyecto, sólo las claves de `CLAVES_PROYECTO`, con el
  nombre recortado y sin caracteres de control, y un id que cabe en una
  dirección. Ni rutas ni texto de la conversación, aunque los trajera.
"""

from __future__ import annotations

import os
import re
import time
from pathlib import Path
from typing import Any

from . import consulta_local, kits

PUERTO_POR_OMISION = 8795
#: Dónde se cambia el puerto, si el estudio escucha en otro.
VARIABLE_PUERTO = "ESTUDIO_PUERTO"
#: Cuánto se espera como mucho a que conteste, las dos preguntas juntas.
ESPERA_S = 0.8
#: Lo más que se lee de cada respuesta. La salud son dos claves; los
#: proyectos, unos pocos renglones.
TOPE_SALUD = 4 * 1024
TOPE_PROYECTOS = 128 * 1024

#: Lo único que sale de aquí.
CLAVES = ("vivo", "motivo", "version", "proyectos", "motivo_proyectos")
CLAVES_PROYECTO = ("id", "nombre", "momento", "esperando", "trabajando")

#: Cuántos proyectos se enseñan como mucho: más no es una lista que se lea.
MAX_PROYECTOS = 50
NOMBRE_MAX = 80
MOMENTO_MAX = 60
#: El id va dentro de una dirección (`/p/<id>/`): sólo lo que no hay que escapar.
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}")
_VERSION = re.compile(r"[0-9][0-9A-Za-z.+-]{0,31}")

#: El id del kit en el catálogo de kits, para decir dónde está su instalador.
KIT = "estudio"


def puerto() -> int:
    """`ESTUDIO_PUERTO` si es un puerto; si no, el de siempre."""
    try:
        n = int(os.environ.get(VARIABLE_PUERTO) or PUERTO_POR_OMISION)
    except ValueError:
        return PUERTO_POR_OMISION
    return n if 0 < n < 65536 else PUERTO_POR_OMISION


def direccion() -> str:
    """Dónde se abre el estudio, en la PC donde corre."""
    return f"http://{consulta_local.ANFITRION}:{puerto()}"


def direccion_de(id_: str) -> str | None:
    """Dónde se abre un proyecto del estudio; None si el id no es de los que
    caben en una dirección."""
    return f"{direccion()}/p/{id_}/" if _ID.fullmatch(id_ or "") else None


def _proyecto(p: object) -> dict[str, Any] | None:
    """Un proyecto, con sólo `CLAVES_PROYECTO`; None si no tiene un id usable."""
    if not isinstance(p, dict):
        return None
    id_ = p.get("id")
    if not isinstance(id_, str) or not _ID.fullmatch(id_):
        return None
    esperando = p.get("esperando")
    if isinstance(esperando, bool) or not isinstance(esperando, int) or esperando < 0:
        esperando = None
    trabajando = p.get("trabajando")
    return {
        "id": id_,
        "nombre": consulta_local.recortar(p.get("nombre"), NOMBRE_MAX) or id_,
        "momento": consulta_local.recortar(p.get("momento"), MOMENTO_MAX),
        "esperando": min(esperando, 999) if esperando is not None else None,
        "trabajando": trabajando if isinstance(trabajando, bool) else None,
    }


def estado(espera: float = ESPERA_S) -> dict[str, Any]:
    """Cómo está el estudio: `vivo`, `motivo` y `version` de su salud, y
    `proyectos` (None si no se pudieron saber, con `motivo_proyectos`).
    Nunca lanza, y las dos preguntas juntas no tardan más que `espera`."""
    limite = time.monotonic() + espera
    salida: dict[str, Any] = {"vivo": False, "motivo": None, "proyectos": None, "motivo_proyectos": None}
    try:
        salud = consulta_local.pedir_json(puerto(), "/api/salud", espera, TOPE_SALUD)
    except consulta_local.NoContesta as exc:
        return {**salida, "motivo": exc.motivo}
    if not isinstance(salud, dict) or salud.get("vivo") is not True:
        return {**salida, "motivo": "contesta algo que no es su estado"}
    salida["vivo"] = True
    version = salud.get("version")
    if isinstance(version, str) and _VERSION.fullmatch(version):
        salida["version"] = version
    try:
        lista = consulta_local.pedir_json(puerto(), "/api/proyectos", limite - time.monotonic(),
                                          TOPE_PROYECTOS, que="su lista de proyectos")
    except consulta_local.NoContesta as exc:
        return {**salida, "motivo_proyectos": exc.motivo}
    if not isinstance(lista, list):
        return {**salida, "motivo_proyectos": "contesta algo que no es su lista de proyectos"}
    proyectos = [p for p in map(_proyecto, lista) if p is not None]
    salida["proyectos"] = proyectos[:MAX_PROYECTOS]
    return salida


def en_catalogo() -> bool:
    """Si el catálogo de kits sabe de dónde traer el del estudio (C-0503)."""
    return KIT in kits.catalogo()


def version_publicada() -> str | None:
    """La versión del kit que da el catálogo, o None si no está en él."""
    version = (kits.catalogo().get(KIT) or {}).get("version")
    return str(version) if version else None


def version_nueva(corre: str | None) -> str | None:
    """La del catálogo si es más nueva que la que corre; si no, None. Quien
    ya lo tenía instalado no recibía los arreglos del kit (27-nov)."""
    publicada = version_publicada()
    if not corre or not publicada:
        return None
    try:
        return publicada if kits.es_mas_nueva(publicada, corre) else None
    except ValueError:
        return None


def kit() -> Path | None:
    """Dónde está instalado el kit del estudio, la versión más alta; None si
    no está. Lo mismo que da `bash scripts/kit.sh ruta estudio`."""
    return kits.resolver(KIT)
