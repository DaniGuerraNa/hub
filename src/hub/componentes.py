"""Navegante y Reuniones: dónde está lo que hace su trabajo y qué le falta.

Las dos pantallas son del hub, pero el trabajo lo hacen componentes aparte —el
laboratorio del navegador y el procesado de Reuniones—, que en el producto
viajan dentro del clon, en `componentes/` (decisión 293). Sin preparar, cada
pantalla enseña sus pasos en vez de un error: quien instala el hub ve qué es,
qué le falta y cómo se consigue, desde la propia pantalla.

🔴 **Preparar no instala nada por su cuenta.** Abre una ventana en la carpeta
del componente con un encargo para Claude escrito y SIN Enter —el tercer caso
de la regla dura 15, el mismo de los kits (decisión 287)—. La sesión que
arranca la lanza la persona, y es ella la que da permiso a cada orden. Lo que
pide `sudo` (Node, ffmpeg, Xvfb) se le dice, no se hace.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from . import config

NOMBRES = ("navegador-lab", "reuniones")
# Por el nombre de su pantalla, que es como lo llama quien lo usa.
ALIAS = {"navegante": "navegador-lab"}

# 🔴 Los componentes viven DENTRO del clon, y `actualizar.sh` se niega a
# avanzar con cambios sin commit (paso 1). Por eso se preparan con
# `uv sync --frozen` y `npm ci`, que no reescriben `uv.lock` ni
# `package-lock.json`: un `npm install` que tocara el lock bloquearía la
# siguiente actualización sin que nadie supiera por qué.

# La variable que cambia la carpeta de cada uno. Son las de siempre: quien ya
# los tenía en otro sitio no tiene que tocar nada.
VARIABLE = {"navegador-lab": "NAV_LAB", "reuniones": "REUNIONES_PROYECTO"}


def carpeta(nombre: str) -> Path:
    """La variable si está; si no, la copia del clon; si no, junto a los proyectos.

    El último caso es el de quien desarrolla el hub, que tiene los componentes
    como repos propios y no dentro del clon.
    """
    declarada = os.environ.get(VARIABLE[nombre])
    if declarada:
        return Path(declarada).expanduser()
    dentro = config.RAIZ_REPO / "componentes" / nombre
    if dentro.is_dir():
        return dentro
    return Path.home() / "projects" / nombre


def _hay_chrome() -> bool:
    if os.environ.get("NAV_CHROME") or any(
        shutil.which(c) for c in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser")
    ):
        return True
    cache = Path.home() / ".cache" / "ms-playwright"
    return cache.is_dir() and any(cache.glob("chromium-*"))


def _paso(id_: str, titulo: str, hecho: bool, como: str, opcional: bool = False) -> dict:
    return {"id": id_, "titulo": titulo, "hecho": hecho, "como": como, "opcional": opcional}


def pasos_navegante() -> list[dict]:
    """Lo que necesita el laboratorio, en el orden en que se consigue."""
    lab = carpeta("navegador-lab")
    return [
        _paso("componente", "El laboratorio está en el clon", (lab / "bin" / "nav").exists(),
              f"El hub lo busca en {lab}. Si lo tienes en otro sitio, arranca el hub con NAV_LAB."),
        _paso("entorno", "Su entorno de Python y Node está preparado",
              (lab / ".venv").is_dir() and (lab / "node_modules").is_dir(),
              "uv sync --frozen y npm ci en su carpeta. «Preparar con Claude» lo hace contigo."),
        _paso("chrome", "Hay un Chrome o Chromium que abrir", _hay_chrome(),
              "npx playwright install chromium en su carpeta, si no tienes Chrome instalado."),
        _paso("xvfb", "Pantalla virtual (Xvfb)", bool(shutil.which("Xvfb")),
              "sudo apt install xvfb. Sin ella el navegador va sin ventana, y algunos sitios lo bloquean.",
              opcional=True),
    ]


def pasos_reuniones_wsl() -> list[dict]:
    """La mitad de WSL de Reuniones: el procesado. La de Windows la cuenta
    `reuniones.preparacion()`, que sabe del agente."""
    proyecto = carpeta("reuniones")
    return [
        _paso("componente", "El procesado está en el clon", (proyecto / "pyproject.toml").exists(),
              f"El hub lo busca en {proyecto}. Si lo tienes en otro sitio, arranca el hub con REUNIONES_PROYECTO."),
        _paso("entorno", "Su entorno de Python está preparado", (proyecto / ".venv").is_dir(),
              "uv sync --frozen en su carpeta. «Preparar con Claude» lo hace contigo; descarga Whisper, que pesa."),
        _paso("ffmpeg", "ffmpeg, para comprimir las grabaciones", bool(shutil.which("ffmpeg")),
              "sudo apt install ffmpeg.", opcional=True),
        _paso("gpu", "GPU NVIDIA para transcribir rápido", bool(shutil.which("nvidia-smi")),
              "Sin ella se transcribe en la CPU, mucho más despacio.", opcional=True),
    ]


def listo(pasos: list[dict]) -> bool:
    return all(p["hecho"] for p in pasos if not p["opcional"])


ENCARGOS = {
    "navegador-lab": (
        "Prepara este laboratorio para la pantalla Navegante del hub, siguiendo README.md "
        "(«Arrancar de cero»), pero con uv sync --frozen y npm ci, que no reescriben los archivos "
        "de bloqueo; si no hay Chrome ni Chromium en el PATH, "
        "npx playwright install chromium. Pide permiso antes de cada orden. Si falta algo del "
        "sistema (Node y npm, Xvfb), dime el comando exacto y espera a que lo instale yo: no uses "
        "sudo. Al terminar comprueba con bin/nav estado y dime que vuelva a la pantalla Navegante."
    ),
    "reuniones": (
        "Prepara el procesado de la pantalla Reuniones del hub en esta carpeta, siguiendo "
        "README.md: uv sync --frozen, que no reescribe uv.lock. Comprueba si hay ffmpeg y una GPU NVIDIA (nvidia-smi). Pide permiso "
        "antes de cada orden. Si falta algo del sistema, dime el comando exacto y espera a que lo "
        "instale yo: no uses sudo. Al terminar dime que siga en la pantalla Reuniones, que "
        "guía la instalación del agente de Windows."
    ),
}


def preparar(nombre: str) -> dict:
    """La ventana en la carpeta del componente con el encargo escrito y sin Enter."""
    from . import agentes, slots, tmux

    nombre = ALIAS.get(nombre, nombre)
    if nombre not in ENCARGOS:
        raise ValueError(f"no hay ningún componente «{nombre}»: son navegante y reuniones")
    destino = carpeta(nombre)
    if not destino.is_dir():
        raise ValueError(f"no está en {destino}")
    pane_id = slots.abrir_en(str(destino), f"preparar-{nombre}", "hub",
                             agentes.comando(ENCARGOS[nombre]))
    indice = next((p["window_idx"] for p in tmux.listar_paneles() if p["pane_id"] == pane_id), None)
    return {"session": "hub", "ventana": indice}
