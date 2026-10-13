"""Comandos preparados: plantillas con huecos que se escriben en una ventana nueva.

Nació de una frase suya sobre el viaje: *«para lanzar comandos con presets…
son sólo `git clone`, sólo es agregar el nombre del repo al final, y un comando
por ambiente»*. Desde el móvil, escribir a mano una orden larga con una URL
dentro es justo lo que no se puede hacer; elegirla de una lista y rellenar un
hueco, sí.

🔴 **Aquí no vive ningún secreto, ni siquiera de paso** (regla dura 5). Una
plantilla es texto que se guarda en `comandos.yml` y que cualquiera que abra el
hub puede leer, así que lo que lleva credenciales **no es la plantilla: es un
script suyo**, fuera del repo y con permisos 600, al que la plantilla sólo
apunta. El hub queda igual que con el token de Telegram — sabe dónde está, no
qué es.

🔴 **Y no se ejecuta nada.** Lo que hace el hub es abrir una ventana de tmux en
la carpeta y **dejar el comando escrito, sin Enter** — el tercer caso de la
regla dura 15, el mismo que usa «Restaurar» (decisión 164). Esa media pulsación
que falta es el gate humano del principio 6, y es lo que permite que el
navegador de archivos siga sin ejecutar nada (decisión 203) y por tanto sin
vivir detrás del interruptor de la terminal.

Los huecos se escriben `{repo}` y se rellenan con `shlex.quote`: una plantilla
es texto del usuario, y interpolarlo en crudo sería ejecución arbitraria en
cuanto un nombre de repo llevara un `;` (regla dura 10).
"""

from __future__ import annotations

import os
import re
import shlex
from pathlib import Path

import yaml

from . import config

ARCHIVO = "comandos.yml"

# Un hueco es `{nombre}` con letras, números y guiones. Sin llaves anidadas ni
# expresiones: esto es una plantilla, no un lenguaje.
HUECO = re.compile(r"\{([a-zA-Z][a-zA-Z0-9_-]*)\}")


class ComandoInvalido(ValueError):
    """Lo que impide escribir una orden a medias en un panel."""


def archivo() -> Path:
    """Dónde viven. Función y no constante, por lo mismo que en `acceso`: el
    archivo puede aparecer después de que el proceso arranque."""
    declarado = os.environ.get("HUB_COMANDOS_YML")
    return Path(declarado) if declarado else config.HUB_HOME / ARCHIVO


def leer() -> list[dict]:
    """Los comandos declarados. Sin archivo, ninguno — no es un error."""
    ruta = archivo()
    if not ruta.exists():
        return []
    datos = yaml.safe_load(ruta.read_text(encoding="utf-8")) or {}
    comandos = datos.get("comandos") or []
    return [c for c in comandos if isinstance(c, dict) and c.get("id") and c.get("plantilla")]


def por_id(id_comando: str) -> dict | None:
    return next((c for c in leer() if c["id"] == id_comando), None)


def huecos(plantilla: str) -> list[str]:
    """Qué hay que rellenar, en el orden en que aparece. Sin repetidos."""
    vistos: list[str] = []
    for nombre in HUECO.findall(plantilla):
        if nombre not in vistos:
            vistos.append(nombre)
    return vistos


def expandir(plantilla: str, valores: dict[str, str]) -> str:
    """La orden lista para escribirla, con cada valor escapado.

    🔴 Falta un hueco y no se escribe nada: una orden a medias pegada en un
    panel es peor que ninguna — se queda ahí, a la vista, esperando un Enter que
    la ejecutaría mal. Es el mismo criterio de «Restaurar» (decisión 164).
    """
    faltan = [h for h in huecos(plantilla) if not (valores.get(h) or "").strip()]
    if faltan:
        raise ComandoInvalido("falta " + ", ".join(f"«{h}»" for h in faltan))

    def sustituir(coincidencia: re.Match) -> str:
        return shlex.quote(valores[coincidencia.group(1)].strip())

    return HUECO.sub(sustituir, plantilla)
