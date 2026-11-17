"""Lo versionado no nombra a nadie: ni rutas de la carpeta personal de nadie, ni correos.

El puente viaja a otros equipos y dentro de otros repositorios. Una ruta
`/home/<alguien>/…` en `.mcp.json` dejaba a Claude sin herramientas en
cualquier otro equipo; un correo en `pyproject.toml` nombraba a quien lo
escribió. Se mira lo que git conoce, incluido lo que aún no tiene commit.
"""

import re
import subprocess

from puente_kvm import config

# Rutas absolutas de carpetas personales, en Linux, WSL y macOS.
RUTA_PERSONAL = re.compile(r"/home/[a-z_][a-z0-9_-]*/|/mnt/[a-z]/Users/|/Users/[A-Za-z][^/\s]*/")
CORREO = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)*\.[a-z]{2,}\b")
# Lo vendorizado y el lock son de terceros.
AJENOS = {"uv.lock", "src/puente_kvm/static/xterm.js", "src/puente_kvm/static/xterm.css",
          "src/puente_kvm/static/addon-fit.js"}


def versionados() -> list[str]:
    r = subprocess.run(["git", "-C", str(config.CODIGO), "ls-files", "--cached", "--others", "--exclude-standard"],
                       capture_output=True, text=True, check=True)
    return [f for f in r.stdout.splitlines() if f not in AJENOS and (config.CODIGO / f).is_file()]


def test_ningun_archivo_versionado_lleva_rutas_personales_ni_correos():
    hallazgos = []
    for f in versionados():
        try:
            texto = (config.CODIGO / f).read_text()
        except UnicodeDecodeError:
            continue
        for n, linea in enumerate(texto.splitlines(), 1):
            if RUTA_PERSONAL.search(linea) or CORREO.search(linea):
                hallazgos.append(f"{f}:{n}: {linea.strip()[:100]}")
    assert not hallazgos, "\n".join(hallazgos)


def test_pyproject_no_lleva_autores():
    assert "authors" not in (config.CODIGO / "pyproject.toml").read_text()
