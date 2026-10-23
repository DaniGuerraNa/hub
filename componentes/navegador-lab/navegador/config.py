"""Dónde vive cada cosa, y la configuración que es del dueño.

Dos sitios para flujos y políticas, a propósito:

- **El repo** (`flujos/`, `politicas/`): ejemplos y lo de la consola falsa. Se
  publica si algún día esto es un kit.
- **Los datos** (`~/.local/share/navegador-lab/`): lo del TRABAJO. Fuera de
  git, porque un flujo laboral lleva nombres de cuentas, grupos de logs y APIs
  de un cliente. Es la colección por defecto al grabar.

`config.yml` en los datos lo puede cambiar el dueño (o el hub, por él): accesos
directos y colecciones extra.
"""
import os
from pathlib import Path

import yaml

RAIZ = Path(__file__).resolve().parents[1]
DATOS = Path(os.environ.get("NAV_DATOS") or Path.home() / ".local/share/navegador-lab")
CDP = os.environ.get("NAV_CDP", "http://127.0.0.1:9222")

POR_DEFECTO = {
    "colecciones": [
        {"nombre": "trabajo", "ruta": str(DATOS / "flujos")},
        {"nombre": "lab", "ruta": str(RAIZ / "flujos")},
    ],
    "politicas": [str(DATOS / "politicas"), str(RAIZ / "politicas")],
    "accesos": [
        {"nombre": "Consola falsa", "url": "http://127.0.0.1:8790/console/home"},
    ],
}


def cargar() -> dict:
    f = DATOS / "config.yml"
    c = dict(POR_DEFECTO)
    if f.exists():
        c.update(yaml.safe_load(f.read_text()) or {})
    for col in c["colecciones"]:
        col["ruta"] = str(Path(os.path.expanduser(col["ruta"])))
    c["politicas"] = [str(Path(os.path.expanduser(p))) for p in c["politicas"]]
    if os.environ.get("NAV_FLUJOS"):
        c["colecciones"] = [{"nombre": "flujos", "ruta": os.environ["NAV_FLUJOS"]}] + c["colecciones"]
    return c


def guardar(c: dict) -> None:
    DATOS.mkdir(parents=True, exist_ok=True)
    (DATOS / "config.yml").write_text(yaml.safe_dump(c, allow_unicode=True, sort_keys=False))


def flujos() -> list[dict]:
    out, vistos = [], set()
    for col in cargar()["colecciones"]:
        d = Path(col["ruta"])
        for f in sorted(d.glob("*.yml")) if d.is_dir() else []:
            if f.name.endswith(".nuevo.yml"):
                continue
            try:
                y = yaml.safe_load(f.read_text()) or {}
            except yaml.YAMLError as e:
                out.append({"nombre": f.stem, "coleccion": col["nombre"], "ruta": str(f), "error": str(e)[:200]})
                continue
            clave = (col["nombre"], f.stem)
            if clave in vistos:
                continue
            vistos.add(clave)
            usa = [p["usar"]["flujo"] if isinstance(p.get("usar"), dict) else p["usar"]
                   for p in (y.get("pasos") or []) if isinstance(p, dict) and "usar" in p]
            out.append({"nombre": f.stem, "coleccion": col["nombre"], "ruta": str(f),
                        "descripcion": y.get("descripcion", ""), "modo": y.get("modo", "lectura"),
                        "parametros": y.get("parametros") or {}, "pasos": len(y.get("pasos") or []),
                        "pantallas": y.get("pantallas") or {}, "usa": usa})
    return out


def buscar_flujo(nombre: str) -> Path:
    """`nombre`, `coleccion/nombre` o una ruta a un .yml."""
    if nombre.endswith(".yml"):
        return Path(nombre)
    col, _, n = nombre.rpartition("/")
    for f in flujos():
        if f["nombre"] == n and (not col or f["coleccion"] == col):
            return Path(f["ruta"])
    raise SystemExit(f"No hay ningún flujo «{nombre}». Mira: nav flujos")


def politicas() -> list[dict]:
    out = []
    for d in map(Path, cargar()["politicas"]):
        for f in sorted(d.glob("*.yml")) if d.is_dir() else []:
            try:
                y = yaml.safe_load(f.read_text()) or {}
            except yaml.YAMLError:
                continue
            out.append({"nombre": y.get("nombre", f.stem), "archivo": f.stem, "ruta": str(f),
                        "modo": y.get("modo", "lectura"), "origenes": y.get("origenes", []),
                        "avisar": y.get("avisar", "")})
    return out


def buscar_politica(nombre: str) -> Path:
    if nombre.endswith(".yml") or "/" in nombre:
        return Path(nombre)
    for p in politicas():
        if nombre in (p["nombre"], p["archivo"]):
            return Path(p["ruta"])
    raise SystemExit(f"No hay ninguna política «{nombre}». Mira: nav politicas")


def mapa() -> dict:
    """Pantallas como nodos y fragmentos como caminos entre ellas.

    Una pantalla con n flujos que sólo en algunos lleva a otra se ve aquí: de
    cada pantalla salen sus fragmentos, y cada uno dice adónde llega (o que se
    queda en la misma, si sólo lee)."""
    pantallas, caminos, sueltos = set(), [], []
    for f in flujos():
        p = f.get("pantallas") or {}
        if not p.get("desde"):
            sueltos.append(f["coleccion"] + "/" + f["nombre"])
            continue
        hasta = p.get("hasta") or p["desde"]
        pantallas.update([p["desde"], hasta])
        caminos.append({"desde": p["desde"], "hasta": hasta, "flujo": f["coleccion"] + "/" + f["nombre"],
                        "descripcion": f.get("descripcion", "")})
    por = {}
    for c in caminos:
        por.setdefault(c["desde"], []).append(c)
    return {"pantallas": sorted(pantallas), "caminos": caminos,
            "salen": {k: por.get(k, []) for k in sorted(pantallas)}, "sin_pantalla": sueltos}
