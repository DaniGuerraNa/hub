"""El espacio de trabajo de Claude cuando no es la carpeta del código.

Con `PUENTE_TRABAJO` apuntando fuera del código, la sesión de Claude corre
allí y necesita lo mismo que tendría en la carpeta del código: sus reglas
(`CLAUDE.md`), sus skills y permisos (`.claude/`), las herramientas del
puente (`.mcp.json`) y `trabajo/`. Todo menos `.mcp.json` son **enlaces** al
código: una actualización del puente llega sola, y nada se copia dos veces.

`.mcp.json` se escribe aquí con la ruta real del código, porque el del
repositorio arranca el servidor en la carpeta desde la que se abre Claude, y
ésta no es la del código. Está fuera del repositorio, así que llevar una ruta
absoluta no viaja a ninguna parte.

Y es un **repositorio git que no guarda nada** (`.git/info/exclude` = `*`).
Medido con Claude Code 2.1.322: en una carpeta que no es un repositorio no
aplica los ajustes del proyecto —las herramientas del puente se quedaban
«pendientes de aprobar» con `enabledMcpjsonServers` puesto—, y entonces
tampoco cabe dar por hecho que aplique sus permisos. Con `git init` sí los
aplica. Que no guarde nada es para que lo traído del Mac no pueda acabar en
un commit por descuido.

Lo que ya exista y no sea un enlace nuestro no se toca: es de quien lo puso.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from . import config

# Lo que se enlaza, relativo a la carpeta del código.
ENLACES = ("CLAUDE.md", ".claude/skills", ".claude/settings.json", "docs", "conocimiento")


def mcp_para(codigo: Path) -> dict:
    return {"mcpServers": {"puente-kvm": {
        "command": "uv",
        "args": ["run", "--directory", str(codigo), "--frozen", "puente-kvm", "mcp"],
    }}}


def preparar(destino: Path | None = None) -> list[str]:
    """Deja el espacio listo y devuelve lo que no pudo dejar como debía."""
    destino = destino or config.espacio()
    codigo = config.CODIGO
    (destino / "trabajo").mkdir(parents=True, exist_ok=True)
    if destino.resolve() == codigo:
        return []
    avisos = []
    (destino / ".claude").mkdir(exist_ok=True)
    for nombre in ENLACES:
        enlace, origen = destino / nombre, codigo / nombre
        if enlace.is_symlink():
            if enlace.resolve() == origen.resolve():
                continue
            enlace.unlink()  # un enlace nuestro a un código que se movió
        elif enlace.exists():
            avisos.append(f"{enlace} ya existe y no es un enlace al puente: lo dejo como está")
            continue
        enlace.symlink_to(origen)
    mcp = destino / ".mcp.json"
    deseado = json.dumps(mcp_para(codigo), indent=2, ensure_ascii=False) + "\n"
    if not mcp.exists() or mcp.read_text() != deseado:
        try:
            actual = json.loads(mcp.read_text()) if mcp.exists() else None
        except (OSError, json.JSONDecodeError):
            actual = None
        if actual is None or set(actual.get("mcpServers", {})) <= {"puente-kvm"}:
            tmp = mcp.with_suffix(".tmp")
            tmp.write_text(deseado)
            os.replace(tmp, mcp)
        else:
            avisos.append(f"{mcp} tiene otros servidores: no lo reescribo; añade «puente-kvm» a mano")
    avisos += _repositorio_vacio(destino)
    return avisos


def _repositorio_vacio(destino: Path) -> list[str]:
    if (destino / ".git").exists():
        return []
    try:
        dentro = subprocess.run(["git", "-C", str(destino), "rev-parse", "--is-inside-work-tree"],
                                capture_output=True, text=True, timeout=10)
        if dentro.returncode == 0:
            # Ya está dentro de otro repositorio: no es nuestro, no se toca, pero se dice.
            return [f"{destino} está dentro de otro repositorio git: lo que se traiga del Mac a "
                    "trabajo/ podría acabar en sus commits. Mejor un PUENTE_TRABAJO fuera de cualquier repositorio"]
        subprocess.run(["git", "init", "-q", str(destino)], capture_output=True, text=True, timeout=10, check=True)
    except (OSError, subprocess.SubprocessError) as e:
        return [f"no pude hacer de {destino} un repositorio git ({e}): Claude Code puede no aplicar ahí "
                "los permisos del puente"]
    excluir = destino / ".git" / "info" / "exclude"
    excluir.parent.mkdir(parents=True, exist_ok=True)
    excluir.write_text("# Espacio de trabajo del puente: lo traído del Mac no se guarda nunca en git.\n*\n")
    return []
