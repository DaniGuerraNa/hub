"""La orden `puente-kvm`.

- `web`: el servicio (la web en 127.0.0.1 y la API que usan las herramientas de Claude).
- `mcp`: las herramientas de Claude Code (las arranca Claude Code, por `.mcp.json`).
- `comprobar`: qué falta en este equipo para que funcione, y cómo arreglarlo.
- `diagnostico`: un informe sin secretos ni contenido del trabajo, para mandar.
- `version`: la versión del código.
"""

from __future__ import annotations

import sys

USO = "uso: puente-kvm [web|mcp|comprobar [--sin-entrar]|diagnostico|version]"


def main() -> None:
    orden = sys.argv[1] if len(sys.argv) > 1 else "web"
    resto = sys.argv[2:]
    if orden == "web":
        import uvicorn

        from . import config
        from .app import crear_app

        # Sólo 127.0.0.1: el puente teclea en un Mac ajeno y no se abre a la red.
        uvicorn.run(crear_app(), host=config.HOST, port=config.PUERTO, log_level="warning")
    elif orden == "mcp":
        from .mcp_servidor import main as mcp

        mcp()
    elif orden == "comprobar":
        from .comprobar import comprobar

        sys.exit(comprobar(resto))
    elif orden == "diagnostico":
        from .comprobar import diagnostico

        sys.exit(diagnostico(resto))
    elif orden in ("version", "--version"):
        from . import config

        print(config.VERSION)
    else:
        sys.exit(USO)


if __name__ == "__main__":
    main()
