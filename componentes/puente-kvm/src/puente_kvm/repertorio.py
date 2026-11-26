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
                    "escribir_cambio", "despertar_mac", "sondear_teclado", "probar_teclado"}
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
    "~/.local/share/puente-kvm/teclados/": "los teclados medidos del puente (sólo los cambia el puente, al verificarlos)",
    "~/.local/share/puente-kvm/ajustes.json": "los ajustes del puente (el teclado en uso y las teclas reservadas)",
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
# El `session_id` de un hook: un UUID, como los que da el puente a sus
# conversaciones (`conversaciones.UUID`). Otra cosa no se guarda.
_SESION = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


MAX_ABIERTOS = 20


def _sesion(valor) -> str | None:
    return valor if isinstance(valor, str) and _SESION.fullmatch(valor) else None


class Actividad:
    def __init__(self, ruta: Path | None = None):
        self.eventos: deque[dict] = deque(maxlen=60)
        self.estado = "sin noticias"
        self.skill: str | None = None
        self.herramienta: str | None = None
        self.t = 0.0
        # De qué conversación de Claude Code es el último hook, y cuál tiene un
        # turno abierto: su `UserPromptSubmit` llegó y su `Stop` todavía no
        # (C-0486). Con eso el puente sabe si Claude sigue con un encargo y le
        # deja el control entre una lectura y una escritura. Los hooks están en
        # el settings del proyecto y también los mandan las sesiones de
        # desarrollo: quien decide mira que sea la conversación abierta.
        # Por sesión (lo encontró el revisor): con una sola casilla, el mensaje de
        # una sesión de desarrollo pisaba el turno cortado de la conversación y
        # la red del Esc no saltaba. Sesión → hora de su último hook.
        self.sesion: str | None = None
        self.abiertos: dict[str, float] = {}
        # Dónde se dejan el estado y su hora (C-0470): la conversación de Claude
        # vive en tmux y sobrevive al reinicio del puente, y el puente nuevo, sin
        # esto, no sabría si Claude está a medias. Sólo eso (y de qué
        # conversación es, C-0486): la skill y la
        # herramienta llevan rutas y nombres del trabajo. None: en memoria y ya.
        self.ruta = ruta

    def registrar(self, hook: dict) -> dict:
        evento = hook.get("hook_event_name", "")
        entrada = (hook.get("tool_input") or {}) if isinstance(hook.get("tool_input"), dict) else {}
        nombre = hook.get("tool_name", "")
        self.t = time.time()
        self.sesion = _sesion(hook.get("session_id"))
        resumen = None
        if evento == "UserPromptSubmit":
            self.estado, self.skill, self.herramienta = "trabajando", None, None
            if self.sesion:
                self.abiertos[self.sesion] = self.t
                # Las de desarrollo que nunca mandan su `Stop` no crecen sin fin.
                for vieja in sorted(self.abiertos, key=self.abiertos.get)[:-MAX_ABIERTOS]:
                    del self.abiertos[vieja]
            resumen = "empieza a trabajar en tu mensaje"
        elif evento in ("Stop", "SessionEnd"):
            self.estado, self.herramienta = "esperando", None
            if self.sesion:
                self.abiertos.pop(self.sesion, None)
            resumen = "terminó: espera tu mensaje" if evento == "Stop" else "se cerró la conversación"
        elif evento == "PreToolUse":
            self.estado = "trabajando"
            if self.sesion in self.abiertos:
                self.abiertos[self.sesion] = self.t
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
        self.abiertos.clear()
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
        self.sesion = _sesion(datos.get("sesion"))
        abiertos = datos.get("abiertos")
        self.abiertos = {k: float(v) for k, v in abiertos.items()
                         if _sesion(k) and isinstance(v, (int, float))} if isinstance(abiertos, dict) else {}
        return True

    def _guardar(self) -> None:
        if self.ruta is None:
            return
        # Por un temporal: el puente que arranca puede leerlo a la vez.
        tmp = self.ruta.with_suffix(".tmp")
        try:
            # La conversación es un UUID, sin nada del trabajo.
            tmp.write_text(json.dumps({"estado": self.estado, "t": self.t, "sesion": self.sesion,
                                       "abiertos": self.abiertos}))
            tmp.replace(self.ruta)
        except OSError as e:  # no es motivo para perder el hook: se dice y se sigue
            print(f"[actividad] no pude guardar el estado de Claude en {self.ruta}: {e}", flush=True)

    def publico(self) -> dict:
        return {"estado": self.estado, "skill": self.skill, "herramienta": self.herramienta, "t": self.t}
