"""La orden `puente-kvm`.

- `web`: el servicio (la web en 127.0.0.1 y la API que usan las herramientas de Claude).
- `mcp`: las herramientas de Claude Code (las arranca Claude Code, por `.mcp.json`).
- `comprobar`: qué falta en este equipo para que funcione, y cómo arreglarlo.
- `diagnostico`: un informe sin secretos ni contenido del trabajo, para mandar.
- `ocupado`: sale con 3 (y dice por qué) si el puente en marcha no se debe reiniciar ahora.
- `mediciones resumir <zip>`: lo que dice un paquete de mediciones de uso (C-0483), legible.
- `version`: la versión del código.
"""

from __future__ import annotations

import sys

USO = ("uso: puente-kvm [web|mcp|comprobar [--sin-entrar]|diagnostico|ocupado|version"
       "|mediciones resumir <zip>]")


def main() -> None:
    orden = sys.argv[1] if len(sys.argv) > 1 else "web"
    resto = sys.argv[2:]
    if orden == "web":
        import uvicorn

        from . import config
        from .app import crear_app

        # Sólo 127.0.0.1: el puente teclea en un Mac ajeno y no se abre a la red.
        # Al pararlo, 5 s como mucho esperando a las peticiones abiertas: el
        # directo no termina mientras una pestaña lo mira, y el 17-nov un stop
        # tardó 93 s, hasta que systemd lo mató. Con el botón «Reiniciar el
        # puente», eso son 93 s con la página esperando.
        uvicorn.run(crear_app(), host=config.HOST, port=config.PUERTO, log_level="warning",
                    timeout_graceful_shutdown=5)
    elif orden == "mcp":
        from .mcp_servidor import main as mcp

        mcp()
    elif orden == "comprobar":
        from .comprobar import comprobar

        sys.exit(comprobar(resto))
    elif orden == "diagnostico":
        from .comprobar import diagnostico

        sys.exit(diagnostico(resto))
    elif orden == "ocupado":
        from .comprobar import orden_ocupado

        sys.exit(orden_ocupado())
    elif orden == "mediciones":
        if len(resto) != 2 or resto[0] != "resumir":
            sys.exit("uso: puente-kvm mediciones resumir <zip>")
        import zipfile
        from pathlib import Path

        from .mediciones import resumir

        try:
            print(resumir(Path(resto[1])), end="")
        except (OSError, ValueError, zipfile.BadZipFile) as e:  # un .zip que no está o no es un .zip: se dice, sin traza
            sys.exit(f"no puedo leer {resto[1]}: {e}")
    elif orden in ("version", "--version"):
        from . import config

        print(config.VERSION)
    else:
        sys.exit(USO)


if __name__ == "__main__":
    main()
