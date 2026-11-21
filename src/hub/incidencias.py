"""Contar un fallo o una idea a quien mantiene el hub (C-0468, decisión 445).

Quien instalaba el hub no tenía por dónde avisar: lo hacía por fuera, y lo
que llegaba venía sin versión ni datos del equipo, así que lo primero era
preguntarlos. `/incidencia` arma el texto **en el navegador** y abre el
formulario de incidencias del repositorio de donde se instaló
(`issues/new?template=…`), si es de GitHub; si no, sólo se copia.

🔴 **El hub no envía nada.** No hay POST ni petición a GitHub ni a nadie: es un
enlace que abre la persona, y lo manda ella con su cuenta después de verlo.

🔴 **Los datos del equipo salen de una lista blanca** (`datos_del_equipo`):
cada fila se nombra aquí, y su valor tiene que tener la forma esperada o no
sale. Nunca rutas, usuario, nombre del equipo, nombres de acceso ni de la red
privada, IPs ni la URL del remoto (puede llevar un token). Lo que se manda a
GitHub es público.

🔴 **Las plantillas viven en `.github/ISSUE_TEMPLATE/`** y se rellenan por el
`id` de sus campos (`CAMPOS`). Ni sus nombres (`TIPOS`) ni esos `id` se
renombran: un hub viejo sigue enlazando a ellos. En la URL no van `labels=`
ni `assignees=` (GitHub da 404 a quien no tiene permiso en el repositorio) ni
`body=` (con una plantilla de formulario no rellena nada): las etiquetas van
dentro de cada plantilla. Lo vigila `tests/test_incidencias.py`.

Este módulo no lee la base ni le pregunta al Puente KVM: lo que no mide él
(versión, salud, lo encendido) llega de `api.incidencia`.
"""

from __future__ import annotations

import os
import platform
import re
import subprocess
import tempfile
from collections.abc import Iterable

from . import interfaz as interfaz_
from . import maquina, tmux

#: Tipo → su plantilla en `.github/ISSUE_TEMPLATE/`. No se renombran (445).
TIPOS: dict[str, str] = {"fallo": "fallo.yml", "mejora": "mejora.yml"}
#: Los `id` de los campos de las dos plantillas, en el orden del formulario.
CAMPOS: tuple[str, ...] = ("que_paso", "equipo")
#: Lo que se deja medir a una URL antes de dejar el texto fuera de ella. Los
#: navegadores aguantan más, pero GitHub corta antes; con margen.
LIMITE_URL = 6000
#: Un título de incidencia en GitHub admite 256; éste deja margen.
LIMITE_TITULO = 200

#: Cómo se nombra cada tipo en la pantalla, y la etiqueta de su campo
#: `que_paso`: la misma que en su plantilla de GitHub (lo comprueba su test),
#: para que la vista previa diga lo mismo que el formulario que se abre.
ROTULOS: dict[str, dict[str, str]] = {
    "fallo": {"nombre": "Un fallo", "campo": "Qué pasó",
              "ejemplo": "p. ej. Al pulsar «Lanzar» en un slot no se abre su ventana; ayer sí se abría."},
    "mejora": {"nombre": "Una idea o mejora", "campo": "Qué te gustaría",
               "ejemplo": "p. ej. Poder ordenar los slots por la fecha de su nota."},
}

#: De dónde se puede llegar a la pantalla (`?de=`). Lista cerrada: otro valor
#: no se pinta ni sale en el texto.
ORIGENES: dict[str, str] = {"puente-kvm": "Puente KVM"}

#: Lo que se espera a `claude --version`. Es opcional: sin contestar, la fila
#: lo dice y la pantalla no espera más.
ESPERA_CLAUDE = 3

_VERSION = re.compile(r"\d+\.\d+\.\d+")
_COMMIT = re.compile(r"[0-9a-f]{7,40}")
_REPO = re.compile(r"[\w.-]+/[\w.-]+")
_CORTO = re.compile(r"[\w.+-]{1,32}")
_CLAVE_SALUD = re.compile(r"[a-z][a-z0-9:_-]{0,40}")
_ESTADOS = ("mal", "aviso", "ok")
_INTERFACES = {interfaz_.CLASICA: "la de siempre", interfaz_.NUEVA: "la nueva (vista previa)"}
_NO_IMPRIMIBLE = re.compile(r"[\x00-\x1f\x7f]+")


def origen(de: str | None) -> str | None:
    """La clave de `ORIGENES` si `de` es una; si no, None."""
    return de if de in ORIGENES else None


def titulo(texto: str | None) -> str:
    """El título que llega por la dirección, en una línea y con su tope."""
    return _limpio(texto, LIMITE_TITULO)


def destino(repo: str | None) -> str | None:
    """`https://github.com/<repo>/issues/new`, o None sin repositorio de GitHub.

    `repo` es `dueño/repo` (`version.repo_github`), nunca una URL: así no hay
    forma de que un token del remoto acabe en el enlace."""
    return f"https://github.com/{repo}/issues/new" if repo and _REPO.fullmatch(repo) else None


def _tmux(v: str | None) -> str:
    return "no está" if v is None else v or "no se pudo leer"


def _limpio(texto: str | None, tope: int) -> str:
    return " ".join(_NO_IMPRIMIBLE.sub(" ", texto or "").split())[:tope]


def _version(v: dict) -> str:
    codigo = v.get("codigo") if _VERSION.fullmatch(str(v.get("codigo") or "")) else None
    instalada = v.get("instalada") if _VERSION.fullmatch(str(v.get("instalada") or "")) else None
    if not codigo:
        return "no se pudo leer"
    texto = codigo
    if v.get("falta_terminar"):
        texto += (f" (instalada del todo: {instalada}; falta terminar de actualizar)" if instalada
                  else " (falta terminar de actualizar)")
    return texto


def _commit(hash_: str | None, con_cambios: bool) -> str:
    if not (hash_ and _COMMIT.fullmatch(hash_)):
        return "no se pudo leer"
    # Sólo sí o no: las líneas de `git status` llevan nombres de archivo, y
    # en un clon con cambios propios pueden ser de lo suyo.
    return f"{hash_}, {'con' if con_cambios else 'sin'} cambios locales"


def _sistema() -> str:
    """El sistema por su nombre de distribución, el núcleo y si es WSL. Nunca
    `platform.node()` ni `uname().nodename`: son el nombre del equipo."""
    partes = []
    try:
        partes.append(_limpio(platform.freedesktop_os_release().get("PRETTY_NAME"), 60))
    except OSError:
        mac = platform.mac_ver()[0]
        if mac:
            partes.append(f"macOS {_limpio(mac, 20)}")
    partes.append(_limpio(f"{platform.system()} {platform.release()}", 80))
    nucleo = platform.release().lower()
    if "microsoft" in nucleo:
        partes.append("WSL 2" if "wsl2" in nucleo else "WSL")
    return " · ".join(p for p in partes if p) or "no se pudo leer"


def _claude_code() -> str:
    """`claude --version`, con su tope. Se busca por `maquina.encontrar` con
    el PATH de usuario (decisión 81): bajo systemd el de `hub-web` no trae
    `~/.local/bin`, y «no se encontró» sería falso (regla dura 13)."""
    camino = tmux.path_de_usuario()
    ruta = maquina.encontrar("claude", de_usuario=True)
    if not ruta:
        return "no se encontró"
    # La salida a un archivo y no a una tubería: si `claude` deja un hijo
    # colgado con la tubería abierta, `run` esperaría a ese hijo y el tope no
    # serviría de nada.
    with tempfile.TemporaryFile(mode="w+") as salida:
        try:
            subprocess.run([ruta, "--version"], stdin=subprocess.DEVNULL, stdout=salida,
                           stderr=subprocess.DEVNULL, timeout=ESPERA_CLAUDE,
                           env={**os.environ, "PATH": camino}, check=False)
        except subprocess.TimeoutExpired:
            return f"no contestó en {ESPERA_CLAUDE} s"
        except (OSError, subprocess.SubprocessError):
            return "no se pudo ejecutar"
        salida.seek(0)
        m = re.match(r"(\d+\.\d+\.\d+)", salida.read(200).strip())
    return m.group(1) if m else "no dijo su versión"


def _salud(revisiones: Iterable[dict]) -> str:
    """Sólo `clave` y `estado` de cada comprobación (decisión 289): el
    `detalle` y el `arreglo` son texto libre, y el de seguir vivo sin terminal
    lleva el usuario (`loginctl enable-linger <usuario>`)."""
    validas = [(str(r.get("clave")), r.get("estado")) for r in revisiones
               if _CLAVE_SALUD.fullmatch(str(r.get("clave") or "")) and r.get("estado") in _ESTADOS]
    if not validas:
        return "sin medir"
    validas.sort(key=lambda r: _ESTADOS.index(r[1]))
    fuera = [f"{clave} {estado}" for clave, estado in validas if estado != "ok"]
    bien = sum(1 for _, estado in validas if estado == "ok")
    if not fuera:
        return f"todo ok ({bien})"
    return " · ".join(fuera + ([f"{bien} más ok"] if bien else []))


def datos_del_equipo(*, version: dict, commit: str | None, con_cambios: bool, salud: list[dict],
                     encendidas: frozenset[str], interfaz: str, navegador: str | None,
                     agente_reuniones: str | None, de: str | None) -> list[tuple[str, str]]:
    """Lo justo del equipo para quien mantiene el hub, fila a fila.

    🔴 **Lista blanca** (decisión 445): cada fila se nombra aquí y lleva sólo
    lo que su forma admite; lo que no casa no sale. Lo que no se mide aquí
    llega ya leído de `api.incidencia`; aquí se miden el sistema, Python, tmux
    (por el adaptador) y Claude Code (con tope). Nunca rutas, usuario, nombre
    del equipo, nombres de acceso o de la red privada, IPs, la URL del remoto
    ni los textos de la salud. No la versión de los componentes: el puente
    dice siempre la misma y no distinguiría nada (regla dura 13)."""
    filas: list[tuple[str, str]] = []
    if origen(de):
        filas.append(("Desde", ORIGENES[de]))
    filas += [
        ("Versión del hub", _version(version)),
        ("Commit", _commit(commit, con_cambios)),
        ("Sistema", _sistema()),
        ("Python", platform.python_version()),
        ("tmux", _tmux(tmux.version())),
        ("Claude Code", _claude_code()),
    ]
    if interfaz in _INTERFACES:
        filas.append(("Interfaz", _INTERFACES[interfaz]))
    if navegador:
        filas.append(("Navegador", _limpio(navegador, 160)))
    lo_encendido = sorted(e for e in encendidas if _CORTO.fullmatch(e))
    filas.append(("Herramientas opcionales", ", ".join(lo_encendido) or "ninguna encendida"))
    filas.append(("Salud del hub", _salud(salud)))
    if agente_reuniones and _CORTO.fullmatch(agente_reuniones):
        filas.append(("Agente de Reuniones", agente_reuniones))
    return filas


def como_texto(datos: list[tuple[str, str]]) -> str:
    """Las filas como van en el campo `equipo`: una por línea."""
    return "\n".join(f"{nombre}: {valor}" for nombre, valor in datos)
