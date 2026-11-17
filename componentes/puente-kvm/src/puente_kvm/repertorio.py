"""Qué sabe hacer Claude aquí, qué puede tocar y qué está haciendo ahora.

Todo se lee de los archivos que de verdad usa Claude Code —las skills de
`.claude/skills/`, los permisos de `.claude/settings.json`, las herramientas
del servidor MCP—, no de una lista aparte: una lista aparte se queda vieja y
entonces la pantalla miente sobre lo que Claude puede hacer.

La actividad llega de los *hooks* de Claude Code (ver `.claude/settings.json`):
cada mensaje, cada herramienta y cada final de turno. Se guarda **sólo el
resumen** —qué herramienta, qué skill, qué archivo—, nunca el contenido: lo
que Claude escribe o pega puede ser código del trabajo.
"""

from __future__ import annotations

import json
import re
import time
from collections import deque
from pathlib import Path

from markupsafe import Markup, escape

from . import config

PROYECTO = config.CODIGO
SKILLS = PROYECTO / ".claude" / "skills"
AJUSTES_CLAUDE = PROYECTO / ".claude" / "settings.json"

# Lo que exige algo de la persona en el puente, además del permiso de Claude Code.
NECESITA_CONTROL = {"teclear", "atajo", "ir_a_linea", "clic", "rueda", "leer_documento", "escribir_cambio"}
NECESITA_APROBACION = {"escribir_cambio"}


def _frontmatter(texto: str) -> dict:
    m = re.match(r"^---\n(.*?)\n---\n", texto, re.S)
    datos = {}
    if m:
        for linea in m.group(1).splitlines():
            if ":" in linea:
                k, v = linea.split(":", 1)
                datos[k.strip()] = v.strip()
    return datos


def _md(texto: str) -> Markup:
    """Lo poco de markdown que usan las skills (**negrita** y `código`), ya escapado."""
    seguro = str(escape(texto))
    seguro = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", seguro)
    seguro = re.sub(r"`([^`]+)`", r"<code>\1</code>", seguro)
    return Markup(seguro)


def skills() -> list[dict]:
    salida = []
    for archivo in sorted(SKILLS.glob("*/SKILL.md")):
        texto = archivo.read_text()
        meta = _frontmatter(texto)
        acceso = re.search(r"\*\*Acceso:\*\*(.*?)(?:\n\n|\Z)", texto, re.S)
        salida.append({
            "nombre": meta.get("name", archivo.parent.name),
            "descripcion": meta.get("description", ""),
            "acceso": _md(" ".join(acceso.group(1).split())) if acceso else "",
            "ruta": str(archivo.relative_to(PROYECTO)),
        })
    return salida


# Rutas que tienen nombre propio en la pantalla.
_SITIOS = {
    "~/.local/share/puente-kvm/": "los datos del puente (~/.local/share/puente-kvm: lecturas y cambios)",
    "~/.config/puente-kvm/": "~/.config/puente-kvm (la contraseña del JetKVM)",
}


def _sitio(patron: str) -> str:
    """El patrón de una regla, dicho como lo diría una persona.

    En las reglas de Claude Code, «/x» es relativo a la carpeta del proyecto
    (donde está `.claude/`), «~/x» a la carpeta personal y «//x» es absoluto.
    """
    base = patron.removesuffix("**")
    if base in _SITIOS:
        return _SITIOS[base]
    if base == "/":
        return "esta carpeta (el espacio de trabajo y lo que contiene)"
    if base.startswith("//"):
        return base[1:]
    return base.removeprefix("./").removeprefix("/") or "esta carpeta"


def _humano(regla: str) -> str:
    if regla.startswith("mcp__puente-kvm__"):
        return f"puente: {regla.removeprefix('mcp__puente-kvm__')}"
    m = re.match(r"(\w+)\((.*)\)$", regla)
    if not m:
        return {"Read": "leer cualquier archivo", "Glob": "buscar archivos", "Grep": "buscar en archivos",
                "WebFetch": "leer páginas web", "WebSearch": "buscar en la web"}.get(regla, regla)
    herramienta, patron = m.groups()
    # En Claude Code, Edit(ruta) cubre también crear archivos (Write(ruta) no se aplica).
    return {"Read": f"leer {_sitio(patron)}",
            "Edit": f"crear y editar archivos en {_sitio(patron)}",
            "Bash": f"ejecutar «{patron.rstrip(':*')}»"}.get(herramienta, regla)


def permisos() -> dict:
    try:
        datos = json.loads(AJUSTES_CLAUDE.read_text()).get("permissions", {})
    except (OSError, json.JSONDecodeError) as e:
        return {"error": f"no se pudo leer .claude/settings.json: {e}", "allow": [], "ask": [], "deny": []}
    return {clave: [{"regla": r, "texto": _humano(r)} for r in datos.get(clave, [])]
            for clave in ("allow", "ask", "deny")}


def _clase_permiso(nombre: str, p: dict) -> str:
    regla = f"mcp__puente-kvm__{nombre}"
    for clave in ("deny", "ask", "allow"):
        if any(r["regla"] == regla for r in p.get(clave, [])):
            return clave
    return "ask"  # sin regla, Claude Code pregunta


async def herramientas() -> list[dict]:
    from .mcp_servidor import mcp

    p = permisos()
    salida = []
    for t in await mcp.list_tools():
        salida.append({
            "nombre": t.name,
            # El primer párrafo entero: la primera línea a veces corta la frase.
            "descripcion": " ".join((t.description or "").strip().split("\n\n")[0].split()),
            "control": t.name in NECESITA_CONTROL,
            "aprobacion": t.name in NECESITA_APROBACION,
            "permiso": _clase_permiso(t.name, p),
        })
    return salida


def conocimiento() -> dict:
    trabajo = config.trabajo()

    def listar(patron: str) -> list[str]:
        return sorted(str(f.relative_to(trabajo.parent)) for f in trabajo.glob(patron)) if trabajo.exists() else []

    return {
        "reglas": "CLAUDE.md",
        "espacio": str(config.espacio()),
        "entorno": "trabajo/entorno.md" if (trabajo / "entorno.md").exists() else None,
        "copias": listar("*.sql"),
        "notas": listar("notas/*.md"),
        "propuestas": listar("propuestas/*"),
    }


# ── actividad ───────────────────────────────────────────────────────────────
class Actividad:
    def __init__(self):
        self.eventos: deque[dict] = deque(maxlen=60)
        self.estado = "sin noticias"
        self.skill: str | None = None
        self.herramienta: str | None = None
        self.t = 0.0

    def registrar(self, hook: dict) -> dict:
        evento = hook.get("hook_event_name", "")
        entrada = (hook.get("tool_input") or {}) if isinstance(hook.get("tool_input"), dict) else {}
        nombre = hook.get("tool_name", "")
        self.t = time.time()
        resumen = None
        if evento == "UserPromptSubmit":
            self.estado, self.skill, self.herramienta = "trabajando", None, None
            resumen = "empieza a trabajar en tu mensaje"
        elif evento == "Stop":
            self.estado, self.herramienta = "esperando", None
            resumen = "terminó: espera tu mensaje"
        elif evento == "PreToolUse":
            self.estado = "trabajando"
            if nombre == "Skill":
                self.skill = str(entrada.get("skill") or entrada.get("command") or "?").lstrip("/")
                resumen = f"usa la skill {self.skill}"
            elif nombre.startswith("mcp__puente-kvm__"):
                resumen = f"puente: {nombre.removeprefix('mcp__puente-kvm__')}"
            elif nombre in ("Read", "Edit", "Write", "MultiEdit", "NotebookEdit"):
                ruta = str(entrada.get("file_path") or "")
                try:
                    ruta = str(Path(ruta).relative_to(config.espacio()))
                except ValueError:
                    ruta = Path(ruta).name
                verbo = {"Read": "lee", "Write": "escribe"}.get(nombre, "edita")
                resumen = f"{verbo} {ruta}"
            elif nombre == "Bash":
                resumen = f"terminal: {entrada.get('description') or str(entrada.get('command', '')).split(' ')[0]}"
            elif nombre in ("Task", "Agent"):
                resumen = f"subagente: {entrada.get('description') or ''}".strip()
            else:
                resumen = nombre
            self.herramienta = resumen
        if resumen:
            self.eventos.append({"t": self.t, "evento": evento, "resumen": resumen[:160]})
        return self.publico()

    def publico(self) -> dict:
        return {"estado": self.estado, "skill": self.skill, "herramienta": self.herramienta, "t": self.t}
