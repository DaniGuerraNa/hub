"""Qué versión del hub corre aquí, cuál se terminó de instalar y si hay otra.

Tres números distintos, y confundirlos es el fallo que esto existe para evitar
(decisión 286):

- **la del código** — `pyproject.toml` de este clon. Cambia con un `git pull`.
- **la instalada** — la que `instalar.sh` o `actualizar.sh` dejaron escrita en
  `HUB_HOME/version.json` al TERMINAR. Si es menor que la del código, alguien
  hizo `git pull` y reinició (lo que decía la documentación hasta la 0.2.0)
  sin completar los pasos de la versión: servicios regenerados, asistente
  refrescado, migraciones. El hub lo dice en todas las pantallas.
- **la publicada** — la etiqueta `vX.Y.Z` más alta del remoto. Se mira una vez
  al día desde el ciclo lento con `git ls-remote`, que no descarga nada.

🔴 **Nada se actualiza solo** (principio 9). Saber que hay una versión nueva
es información; aplicarla es una acción de la persona, con `actualizar.sh`.

🔴 Mirar el remoto es una consulta a internet, la única que hace el hub por su
cuenta. Se apaga con `HUB_BUSCAR_VERSIONES=0`, y el resultado vive en un
archivo de `HUB_HOME`, no en la base: es un dato que se rehace mirando.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tomllib
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import config

PATRON = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
ETIQUETA = re.compile(r"refs/tags/v(\d+\.\d+\.\d+)$")
# La versión que se da por instalada cuando no hay `version.json`: todo lo
# anterior al protocolo. Con ella, las migraciones desde la 0.2.0 se aplican.
ANTES_DEL_PROTOCOLO = "0.1.0"
CADA = timedelta(hours=24)


def clave(version: str) -> tuple[int, int, int]:
    """`"0.10.0"` > `"0.9.3"`: se compara por números, nunca como texto."""
    m = PATRON.match(version.strip())
    if not m:
        raise ValueError(f"versión no válida: {version!r} (se espera X.Y.Z)")
    return tuple(int(x) for x in m.groups())  # type: ignore[return-value]


def del_codigo(raiz: Path | None = None) -> str:
    with open((raiz or config.RAIZ_REPO) / "pyproject.toml", "rb") as f:
        return tomllib.load(f)["project"]["version"]


def _archivo_instalada() -> Path:
    return config.HUB_HOME / "version.json"


def _archivo_remota() -> Path:
    return config.HUB_HOME / "version-remota.json"


def instalada() -> str | None:
    """La versión que terminó de instalarse, o `None` si nunca se apuntó."""
    try:
        return json.loads(_archivo_instalada().read_text())["version"]
    except (OSError, ValueError, KeyError):
        return None


def registrar(version: str) -> None:
    """La apunta `actualizar.sh` (e `instalar.sh`) al terminar, y sólo entonces."""
    clave(version)
    destino = _archivo_instalada()
    destino.parent.mkdir(parents=True, exist_ok=True)
    tmp = destino.with_suffix(".tmp")
    tmp.write_text(json.dumps({
        "version": version,
        "en": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }) + "\n")
    tmp.replace(destino)


def etiquetas(salida_ls_remote: str) -> list[str]:
    """Las versiones de una salida de `git ls-remote --tags`, de menor a mayor.

    Ignora lo que no sea `vX.Y.Z` y las referencias `^{}` de etiquetas anotadas.
    """
    vistas = {m.group(1) for linea in salida_ls_remote.splitlines()
              if (m := ETIQUETA.search(linea.split("\t")[-1].strip()))}
    return sorted(vistas, key=clave)


def buscar_remota(raiz: Path | None = None, *, ahora: datetime | None = None,
                  forzar: bool = False) -> dict | None:
    """Mira la etiqueta más alta del remoto, como mucho una vez al día.

    Devuelve lo apuntado, o `None` si está apagado o no hay remoto. Un fallo de
    red no borra la lectura anterior: se apunta el error junto a ella.
    """
    if os.environ.get("HUB_BUSCAR_VERSIONES", "1") == "0":
        return None
    ahora = ahora or datetime.now(timezone.utc)
    previa = remota()
    if previa and not forzar:
        try:
            if ahora - datetime.fromisoformat(previa["mirado_en"]) < CADA:
                return previa
        except (KeyError, ValueError):
            pass
    raiz = raiz or config.RAIZ_REPO
    # Un clon sin `origin` (el de desarrollo, una copia suelta) no tiene de
    # dónde mirar: no es un fallo que enseñar, es que no aplica.
    sin_remoto = subprocess.run(["git", "-C", str(raiz), "remote", "get-url", "origin"],
                                capture_output=True, text=True, timeout=5).returncode != 0
    if sin_remoto:
        return None
    datos = dict(previa or {})
    datos["mirado_en"] = ahora.isoformat(timespec="seconds")
    try:
        r = subprocess.run(
            ["git", "-C", str(raiz), "ls-remote", "--tags", "origin"],
            capture_output=True, text=True, timeout=20,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
        )
        if r.returncode != 0:
            raise RuntimeError((r.stderr or "git ls-remote falló").strip().splitlines()[-1])
        vistas = etiquetas(r.stdout)
        datos["ultima"] = vistas[-1] if vistas else None
        datos.pop("error", None)
    except Exception as exc:  # noqa: BLE001 — sin red no es una avería del hub
        datos["error"] = str(exc)[:200]
    destino = _archivo_remota()
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(json.dumps(datos) + "\n")
    return datos


def remota() -> dict | None:
    try:
        return json.loads(_archivo_remota().read_text())
    except (OSError, ValueError):
        return None


def estado(raiz: Path | None = None) -> dict:
    """Lo que necesita la UI: barato, se pinta en cada pantalla."""
    codigo = del_codigo(raiz)
    hecha = instalada()
    leida = remota() or {}
    ultima = leida.get("ultima")
    falta_terminar = clave(hecha or ANTES_DEL_PROTOCOLO) < clave(codigo)
    return {
        "codigo": codigo,
        "instalada": hecha,
        "falta_terminar": falta_terminar,
        "publicada": ultima,
        "hay_nueva": bool(ultima) and clave(ultima) > clave(codigo),
        "mirado_en": leida.get("mirado_en"),
        "error": leida.get("error"),
        "buscar": os.environ.get("HUB_BUSCAR_VERSIONES", "1") != "0",
    }


def migraciones(desde: str | None, hasta: str, carpeta: Path) -> list[Path]:
    """Los pasos de cada versión cruzada, en orden: `(desde, hasta]`.

    Un paso es `scripts/migraciones/X.Y.Z.sh`. Sin `desde` (instalación anterior
    al protocolo) se parte de la 0.1.0.
    """
    inicio, fin = clave(desde or ANTES_DEL_PROTOCOLO), clave(hasta)
    pasos = []
    for p in carpeta.glob("*.sh"):
        try:
            v = clave(p.stem)
        except ValueError:
            continue
        if inicio < v <= fin:
            pasos.append((v, p))
    return [p for _, p in sorted(pasos)]


def novedades(changelog: str, desde: str | None, hasta: str) -> str:
    """Las secciones `## X.Y.Z` del CHANGELOG entre dos versiones: `(desde, hasta]`."""
    inicio, fin = clave(desde or ANTES_DEL_PROTOCOLO), clave(hasta)
    fuera, dentro = [], False
    for linea in changelog.splitlines():
        m = re.match(r"^## \[?(\d+\.\d+\.\d+)\]?", linea)
        if m:
            dentro = inicio < clave(m.group(1)) <= fin
        elif linea.startswith("# "):
            dentro = False
        if dentro:
            fuera.append(linea)
    return "\n".join(fuera).strip()


def url_novedades(raiz: Path | None = None) -> str | None:
    """El CHANGELOG de la rama `main` publicada, si el remoto es de GitHub.

    Para enseñar qué trae una versión que aún no está en este clon. Con otro
    alojamiento no se adivina la URL: mejor ningún enlace que uno roto.
    """
    try:
        r = subprocess.run(["git", "-C", str(raiz or config.RAIZ_REPO), "remote", "get-url", "origin"],
                           capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    m = re.match(r"^(?:https://github\.com/|git@github\.com:)([\w.-]+/[\w.-]+?)(?:\.git)?$",
                 r.stdout.strip())
    return f"https://github.com/{m.group(1)}/blob/main/CHANGELOG.md" if m else None


def para_la_guia(raiz: Path | None = None) -> dict:
    """La sección «Versión» de `/guia`: los tres números y lo que trae la tuya."""
    raiz = raiz or config.RAIZ_REPO
    datos = estado(raiz)
    try:
        texto = (raiz / "CHANGELOG.md").read_text()
        anteriores = [v for v in re.findall(r"^## \[?(\d+\.\d+\.\d+)", texto, re.M)
                      if clave(v) < clave(datos["codigo"])]
        previa = max(anteriores, key=clave) if anteriores else None
        datos["novedades"] = novedades(texto, previa, datos["codigo"])
    except OSError:
        datos["novedades"] = ""
    datos["url_novedades"] = url_novedades(raiz) if datos["hay_nueva"] else None
    return datos


def main(argv: list[str]) -> int:
    """Lo que usan los scripts: `python -m hub.version <orden>`."""
    orden = argv[0] if argv else "estado"
    if orden == "codigo":
        print(del_codigo())
    elif orden == "instalada":
        print(instalada() or "")
    elif orden == "registrar":
        registrar(argv[1] if len(argv) > 1 else del_codigo())
    elif orden == "migraciones":
        desde = argv[1] or None
        for p in migraciones(desde, argv[2], Path(argv[3])):
            print(p)
    elif orden == "novedades":
        desde = argv[1] or None
        print(novedades(Path(argv[3]).read_text(), desde, argv[2]))
    elif orden == "buscar":
        print(json.dumps(buscar_remota(forzar=True)))
    elif orden == "estado":
        print(json.dumps(estado(), indent=2))
    else:
        print(f"orden desconocida: {orden}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
