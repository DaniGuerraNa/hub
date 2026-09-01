"""La capa base de cada proyecto y el puntero a su estado vigente.

Dos cosas que van juntas porque contestan la misma pregunta: *¿qué está pasando
hoy en este proyecto y dónde lo leo?*

**El estado NO es un archivo nuevo** (decisión 5). Los proyectos viejos no
migran: `projects.yml` apunta a donde el estado ya vive y con el formato que ya
usan. Aquí sólo se resuelve ese puntero y se extrae el mínimo exigible —
`estado`, `próxima acción`, `bloqueado_por` (decisión 6)— para que la UI y el
futuro asistente no tengan que interpretar cinco formatos distintos.

El diagnóstico que originó el hub es literal: *sobran documentos y falta un puntero a cuál
está vigente*. Este módulo es ese puntero.

**El hub no escribe dentro de otros proyectos.** Si falta la capa base, no se
siembra: se genera un prompt para que lo haga el agente de mantenimiento del kit
(decisión 9), que es quien tiene permiso para tocar ese repo.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

import yaml

from .models import Proyecto

VERSION_BASE = "1.0"

# Los tres campos del mínimo exigible, con los sinónimos que el usuario ya escribe.
# No se inventan: se extrajeron de sus checkpoints del 2026-08-21.
_CAMPOS = {
    "estado": (
        "estado", "estado actual", "situacion", "resumen", "donde estamos",
        # Un proyecto puede estar escrito en inglés —un kit publicado, por
        # ejemplo— y su estado sigue siendo su estado. Sin estos alias, el hub
        # decía «sin bloque legible» sobre un documento que lo tenía.
        "status", "current status", "state",
    ),
    "proxima_accion": (
        "proxima accion", "proximas acciones", "siguiente paso", "siguientes pasos",
        "que hacer al volver", "al volver", "que sigue", "por hacer", "pendientes",
        "next", "next step", "next steps", "todo", "what to do next",
    ),
    "bloqueado_por": (
        "bloqueado por", "bloqueos", "bloqueado", "espera decision",
        "que espera decision", "lo que espera decision", "decisiones pendientes",
        "blocked", "blocked by", "blockers", "waiting on",
    ),
}

_ENCABEZADO = re.compile(r"^(#{1,6})\s+(.*?)\s*#*$")
_FRONTMATTER = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.S)


def _plano(texto: str) -> str:
    """Sin acentos, sin puntuación, sin numeración y en minúsculas.

    «Próxima acción», «PROXIMA ACCION» y «## 0. Estado en una línea» tienen que
    caer en la misma casilla. La numeración importa: los checkpoints reales del
    usuario van numerados (`## 0. Estado…`, `## 1. Qué hacer al volver…`), y sin
    quitarla el extractor no reconocía ninguno de sus documentos.
    """
    sin_acentos = "".join(
        c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn"
    )
    limpio = re.sub(r"[^a-z0-9 ]+", " ", sin_acentos.lower())
    # Numeración de sección al principio: «0.», «2.1», «3)».
    limpio = re.sub(r"^\s*\d+(\s+\d+)*\s+", " ", limpio)
    return " ".join(limpio.split())


def _encaje(titulo: str) -> tuple[str, int] | None:
    """El campo al que pertenece un encabezado y **cómo de específico** es.

    La especificidad es la longitud del alias que encajó, y hace falta para
    resolver un caso real: `# Resumen y checkpoint — proyecto` encaja por
    «resumen» y se llevaba el preámbulo entero como si fuera el estado, dejando
    fuera el `## Estado en una línea` que venía después. Ganaba el primero que
    aparecía; ahora gana el más específico.
    """
    plano = _plano(titulo)
    mejor: tuple[int, str] | None = None
    for campo, alias in _CAMPOS.items():
        for a in alias:
            if plano == a or plano.startswith(a + " "):
                if mejor is None or len(a) > mejor[0]:
                    mejor = (len(a), campo)
    return (mejor[1], mejor[0]) if mejor else None


def _casilla(titulo: str) -> str | None:
    """A qué campo del mínimo pertenece un encabezado, si es que pertenece a alguno.

    El alias tiene que estar **al principio** del título. Buscarlo en cualquier
    posición parecía más tolerante y era peor: «5.1 El mínimo de estado» —una
    sección de diseño de este mismo repo— se colaba como si fuera el estado del
    proyecto. Un estado falso es peor que ninguno, porque se actúa sobre él.

    Los títulos con adorno se cubren con alias explícitos («lo que espera
    decisión»), no aflojando la regla. Gana el alias más largo que encaje.
    """
    plano = _plano(titulo)
    mejor: tuple[int, str] | None = None
    for campo, alias in _CAMPOS.items():
        for a in alias:
            if plano == a or plano.startswith(a + " "):
                if mejor is None or len(a) > mejor[0]:
                    mejor = (len(a), campo)
    return mejor[1] if mejor else None


def extraer_minimo(texto: str) -> dict:
    """Saca `estado` / `proxima_accion` / `bloqueado_por` de un markdown cualquiera.

    Precedencia: el frontmatter YAML gana sobre los encabezados. Un proyecto que
    ya declaró el bloque estructurado no debe verse pisado por una sección de
    prosa que se llame parecido.
    """
    encontrado: dict[str, str] = {}
    # Cómo de específico era el título que llenó cada campo. El frontmatter va
    # con la fuerza más alta posible: es una declaración explícita y ninguna
    # sección de prosa debe pisarla.
    fuerza: dict[str, int] = {}

    def guardar(campo: str, valor: str, peso: int) -> None:
        if not valor:
            return
        if campo not in encontrado or peso > fuerza.get(campo, 0):
            encontrado[campo] = valor
            fuerza[campo] = peso

    m = _FRONTMATTER.match(texto)
    if m:
        try:
            datos = yaml.safe_load(m.group(1))
        except yaml.YAMLError:
            datos = None
        if isinstance(datos, dict):
            for clave, valor in datos.items():
                campo = _casilla(str(clave))
                if campo and valor:
                    guardar(campo, _resumir(valor), 10_000)
        texto = texto[m.end():]

    actual: str | None = None
    peso_actual = 0
    nivel = 0
    primer_h1 = True
    acumulado: list[str] = []
    for linea in texto.splitlines():
        cabecera = _ENCABEZADO.match(linea)
        if cabecera:
            profundidad, titulo = len(cabecera.group(1)), cabecera.group(2)
            # El primer `#` de un documento es su TÍTULO, no una sección suya, y
            # sólo debe ganar si ninguna sección encaja. Sin esto,
            # `# Resumen y checkpoint — proyecto` encajaba por «resumen» y se
            # llevaba el preámbulo como estado, tapando el `## Estado en una
            # línea` que venía justo debajo. Ocurre en un documento real.
            titulo_del_documento = profundidad == 1 and primer_h1
            if profundidad == 1:
                primer_h1 = False
            # Una subsección no cierra la sección que la contiene: su título es
            # parte del contenido. Sin esto, «2. LO QUE ESPERA DECISIÓN» se
            # perdía entera porque todo su cuerpo colgaba de 2.1, 2.2 y 2.3.
            if actual and profundidad > nivel and _encaje(titulo) is None:
                acumulado.append(titulo)
                continue
            if actual:
                guardar(actual, _resumir("\n".join(acumulado)), peso_actual)
            encaje = _encaje(titulo)
            if encaje:
                campo, largo = encaje
                actual = campo
                peso_actual = largo if titulo_del_documento else largo + 100
            else:
                actual, peso_actual = None, 0
            nivel, acumulado = profundidad, []
            continue
        if actual:
            acumulado.append(linea)
    if actual:
        guardar(actual, _resumir("\n".join(acumulado)), peso_actual)

    return {k: v for k, v in encontrado.items() if v}


def _resumir(valor) -> str:
    """Las primeras líneas con contenido, sin la tipografía del markdown.

    Aquí no se renderiza markdown: se muestra como texto en una tarjeta, así que
    dejar `> **Todo está commiteado**` a la vista sólo añade ruido. Se quitan las
    marcas ligeras y se descartan las tablas, que sin renderizar son ilegibles.
    """
    if isinstance(valor, (list, tuple)):
        valor = "\n".join(f"- {v}" for v in valor)

    utiles = []
    for linea in str(valor).splitlines():
        limpia = _sin_marcas(linea)
        if not limpia or set(limpia) <= set("-=_*|"):
            continue
        if limpia.startswith("|"):  # fila de tabla: ilegible sin renderizar
            continue
        utiles.append(limpia)
    return "\n".join(utiles[:6])[:600].strip()


_MARCAS = re.compile(r"\*\*|__|`|~~")


def _sin_marcas(linea: str) -> str:
    sin_cita = re.sub(r"^\s*>\s?", "", linea.rstrip())
    return _MARCAS.sub("", sin_cita).strip()


def resolver_estado_ref(proyecto: Proyecto) -> Path | None:
    """Dónde vive de verdad el archivo al que apunta `estado_ref`.

    Se prueba contra todas las rutas del proyecto, no sólo el asiento: hay
    proyectos que se orquestan desde `/mnt/c` mientras su código vive en `~/dev`,
    y su doc de estado podría estar en cualquiera de los dos.
    """
    if not proyecto.estado_ref:
        return None
    candidato = Path(proyecto.estado_ref).expanduser()
    if candidato.is_absolute():
        return candidato if candidato.is_file() else None
    for base in proyecto.todas_las_rutas():
        ruta = Path(base) / proyecto.estado_ref
        if ruta.is_file():
            return ruta
    return None


def estado_de(proyecto: Proyecto) -> dict:
    """Qué está pasando en un proyecto, según el documento que él mismo declaró.

    Devuelve siempre un dict: la ausencia del puntero es información —significa
    que ese proyecto todavía no dice cuál de sus documentos está vigente.
    """
    ruta = resolver_estado_ref(proyecto)
    if not ruta:
        return {
            "ruta": None,
            "declarado": proyecto.estado_ref,
            "existe": False,
            "campos": {},
            "modificado": None,
        }
    try:
        texto = ruta.read_text(encoding="utf-8", errors="replace")[:60_000]
    except OSError:
        texto = ""
    try:
        modificado = datetime.fromtimestamp(
            ruta.stat().st_mtime, timezone.utc
        ).isoformat(timespec="seconds")
    except OSError:
        modificado = None

    return {
        "ruta": str(ruta),
        "declarado": proyecto.estado_ref,
        "existe": True,
        "campos": extraer_minimo(texto),
        "modificado": modificado,
    }


# ───────────────────────── la capa base ─────────────────────────


def capa_de(proyecto: Proyecto) -> dict:
    """Qué tiene el proyecto en `.claude/hub/`.

    Vive ahí porque todos los proyectos tienen `.claude/` garantizado, los
    agentes lo encuentran por convención y no ensucia la raíz (decisión 3).
    """
    for base in proyecto.todas_las_rutas():
        carpeta = Path(base) / ".claude" / "hub"
        if not carpeta.is_dir():
            continue
        project_yml = carpeta / "project.yml"
        datos = {}
        if project_yml.is_file():
            try:
                datos = yaml.safe_load(project_yml.read_text(encoding="utf-8")) or {}
            except (OSError, yaml.YAMLError):
                datos = {}
        return {
            "presente": True,
            "carpeta": str(carpeta),
            "version": str(datos.get("base_version") or proyecto.base_version or "?"),
            "tiene_project": project_yml.is_file(),
            "tiene_capabilities": (carpeta / "capabilities.yml").is_file(),
            "al_dia": str(datos.get("base_version") or "") == VERSION_BASE,
        }
    return {
        "presente": False,
        "carpeta": None,
        "version": None,
        "tiene_project": False,
        "tiene_capabilities": False,
        "al_dia": False,
    }


def prompt_sembrar(proyecto: Proyecto) -> str:
    """Propuesta editable para que un agente cree la capa base.

    El hub no la escribe él: escribir dentro de otro proyecto es exactamente lo
    que `CLAUDE.md` prohíbe. Propone; el agente que corre dentro de ese repo
    decide y ejecuta.
    """
    destino = proyecto.asiento or (proyecto.rutas[0].ruta if proyecto.rutas else "")
    return (
        f"Crea la capa base del hub en `{destino}/.claude/hub/`.\n\n"
        f"1. `project.yml` con: `id: {proyecto.id}`, `nombre: {proyecto.nombre}`, "
        f"`base_version: \"{VERSION_BASE}\"`, y `estado_ref:` apuntando al documento "
        f"que HOY está vigente en este proyecto"
        + (f" (hoy declara `{proyecto.estado_ref}`)" if proyecto.estado_ref else "")
        + ".\n"
        "2. `capabilities.yml` declarando los agentes, skills y scripts propios.\n\n"
        "Antes de escribir: revisa qué documento de estado está realmente vigente — "
        "puede no ser el que dice el registro. Y **no crees un documento de estado "
        "nuevo**: la capa base apunta a donde el estado ya vive, no lo duplica.\n\n"
        "El mínimo exigible del documento apuntado es un bloque corto con `estado`, "
        "`próxima acción` y `bloqueado_por`. Si ya existe algo equivalente con otro "
        "nombre, dímelo en vez de añadir otro."
    )
