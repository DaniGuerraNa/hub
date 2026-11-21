"""Qué sabe hacer Claude aquí, qué puede tocar y qué está haciendo ahora.

Todo se lee de los archivos que de verdad usa Claude Code —las skills de
`.claude/skills/`, los permisos de `.claude/settings.json` y
`.claude/preguntar.json`, las herramientas del servidor MCP—, no de una lista
aparte: una lista aparte se queda vieja y entonces la pantalla miente sobre lo
que Claude puede hacer.

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
# Las reglas «ask», aparte: `terminal.ajustes_de_sesion` las suma sólo en el
# modo normal, porque en el modo sin permisos una «ask» seguiría preguntando.
PREGUNTAR = PROYECTO / ".claude" / "preguntar.json"

# Lo que exige algo de la persona en el puente, además del permiso de Claude Code.
NECESITA_CONTROL = {"teclear", "atajo", "ir_a_linea", "clic", "rueda", "recorrer_pantalla", "leer_documento",
                    "escribir_cambio", "despertar_mac"}
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


def reglas() -> dict[str, list[str]]:
    """Los permisos de Claude en el puente, de los dos archivos: lo único que los
    lee, para que la pantalla y la sesión no puedan decir cosas distintas."""
    base = json.loads(AJUSTES_CLAUDE.read_text()).get("permissions", {})
    preguntar = json.loads(PREGUNTAR.read_text()).get("permissions", {})
    return {"allow": list(base.get("allow", [])), "ask": [*base.get("ask", []), *preguntar.get("ask", [])],
            "deny": list(base.get("deny", []))}


def permisos() -> dict:
    try:
        datos = reglas()
    except (OSError, json.JSONDecodeError) as e:
        return {"error": f"no se pudieron leer los permisos de .claude/: {e}", "allow": [], "ask": [], "deny": []}
    return {clave: [{"regla": r, "texto": _humano(r)} for r in datos[clave]] for clave in ("allow", "ask", "deny")}


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
# Lo único de la actividad que sobrevive a reiniciar el puente (C-0470).
ESTADOS_GUARDADOS = ("trabajando", "esperando")


class Actividad:
    def __init__(self, ruta: Path | None = None):
        self.eventos: deque[dict] = deque(maxlen=60)
        self.estado = "sin noticias"
        self.skill: str | None = None
        self.herramienta: str | None = None
        self.t = 0.0
        # Dónde se dejan el estado y su hora (C-0470): la conversación de Claude
        # vive en tmux y sobrevive al reinicio del puente, y el puente nuevo, sin
        # esto, no sabría si Claude está a medias. Sólo eso: la skill y la
        # herramienta llevan rutas y nombres del trabajo. None: en memoria y ya.
        self.ruta = ruta

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
        self._guardar()
        return self.publico()

    def recien_abierta(self) -> None:
        """Claude Code acaba de abrirse (lo abrió el puente): espera su primer
        mensaje. El que se cerró para abrirlo no manda su `Stop`, y sin esto la
        placa se quedaba en «trabajando»."""
        self.estado, self.skill, self.herramienta = "esperando", None, None
        self.t = time.time()
        self._guardar()

    def recuperar(self) -> bool:
        """Lo que dejó guardado el puente de antes de reiniciarlo, si se entiende.
        Quien llama sabe si la conversación sigue viva: si no, es de otra."""
        if self.ruta is None:
            return False
        try:
            datos = json.loads(self.ruta.read_text())
            estado, t = datos["estado"], float(datos["t"])
        except (OSError, ValueError, KeyError, TypeError):
            return False
        if estado not in ESTADOS_GUARDADOS:
            return False
        self.estado, self.t = estado, t
        return True

    def _guardar(self) -> None:
        if self.ruta is None:
            return
        # Por un temporal: el puente que arranca puede leerlo a la vez.
        tmp = self.ruta.with_suffix(".tmp")
        try:
            tmp.write_text(json.dumps({"estado": self.estado, "t": self.t}))
            tmp.replace(self.ruta)
        except OSError as e:  # no es motivo para perder el hook: se dice y se sigue
            print(f"[actividad] no pude guardar el estado de Claude en {self.ruta}: {e}", flush=True)

    def publico(self) -> dict:
        return {"estado": self.estado, "skill": self.skill, "herramienta": self.herramienta, "t": self.t}
