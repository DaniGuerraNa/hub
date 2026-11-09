"""Dónde vive cada llave del hub, y si ya está en Bitwarden (decisión 346, C-0143).

🔴 **El hub no guarda llaves, y esto tampoco** (regla dura 5, decisión 28).
Bitwarden es el único llavero; aquí sólo se sabe **dónde** vive cada llave en
esta máquina y si el dueño la marcó como subida. El inventario hace `stat`,
nunca `open`: ni el valor ni su longitud pasan por aquí.

Las llaves las declara cada módulo que las usa (`LLAVES`, con su propio
puntero), y este módulo las reúne: quien sabe dónde vive el token del canal es
`rele`, no un cuarto sitio que lo adivine. Lo que hay en `~/.secretos` y nadie
declara se enseña como «suelta», sin suponer qué es. Las claves ssh se
enseñan por su par `.pub`.

Subir a Bitwarden lo hace **el dueño en su terminal**, con su caja abierta
(`BW_SESSION`): `uv run python -m hub.llavero subir`. El valor va del disco a
`bw` por la entrada estándar (nunca en argumentos: `ps` los ve), y la salida
de `bw` —que devuelve el elemento descifrado— no se imprime. Exige una
terminal de verdad: Claude no tiene TTY y no puede lanzarla (lo pidió así el
dueño: Claude encola, él confirma).

**La cola**: lo que Claude quiere que acabe en Bitwarden (una llave nueva, o
el puntero a una que ya existe) lo deja en `~/.secretos/llavero-cola/`, con
permisos 600 como el resto de esa carpeta. `subir` la vacía. Las sesiones (la
de Telegram del dueño, la de WhatsApp) no se suben: dan la cuenta entera y se
vuelven a vincular.

    uv run python -m hub.llavero lista
    uv run python -m hub.llavero marcar <nombre> [elemento]
    uv run python -m hub.llavero encolar <nombre> --para "…" (--ruta R | valor por la entrada estándar)
    uv run python -m hub.llavero subir [nombre…]          # sólo el dueño, en su terminal
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import stat
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import yaml

from . import config

#: Las carpetas de llaves de esta máquina. El orquestador las tiene vedadas.
CARPETAS = ("~/.secretos", "~/.ssh")
CARPETA_BW = "hub"
#: Más que esto no es una llave: es un archivo que no se sube por error.
TOPE = 64 * 1024
_NOMBRE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,60}$")
#: Lo que no se sube nunca: sesiones que dan la cuenta entera.
_SESIONES = ("*.session", "*.session-journal")


@dataclass(frozen=True)
class Llave:
    """Una llave declarada por el módulo que la usa.

    `puntero` devuelve dónde vive hoy (`ruta`, o `ruta#CLAVE` dentro de un
    `.env`), o None si no está configurada. `sesion` marca lo que no se sube.
    """
    nombre: str
    para: str
    puntero: Callable[[], str | None]
    sesion: bool = False


def carpetas() -> list[Path]:
    return [Path(c).expanduser() for c in CARPETAS]


def _cola() -> Path:
    return Path(CARPETAS[0]).expanduser() / "llavero-cola"


def _marcas_yml() -> Path:
    return config.HUB_HOME / "llavero.yml"


# ── qué hay ──────────────────────────────────────────────────────────────────

def declaradas() -> list[Llave]:
    """Las de cada módulo. Se importan aquí, no arriba: ellos importan esto."""
    from . import chatweb, rele, rele_encargos
    from .secretario.agenda import google, ical
    from .secretario.avisos import webpush
    from .secretario.fuentes import correo, telegram as tg_secretario, whatsapp

    salida: list[Llave] = []
    for modulo in (rele, rele_encargos, chatweb, webpush, google, ical, correo, tg_secretario, whatsapp):
        salida += list(getattr(modulo, "LLAVES", ()))
    return salida


def _ruta(puntero: str) -> Path:
    return Path(puntero.split("#", 1)[0]).expanduser()


def _estado_archivo(ruta: Path) -> str:
    try:
        st = ruta.stat()
    except OSError:
        return "no existe"
    if stat.S_ISDIR(st.st_mode):
        return "carpeta"
    if st.st_mode & 0o077:
        return "⚠ la pueden leer otros usuarios"
    return "en disco"


def _marcas() -> dict:
    try:
        datos = yaml.safe_load(_marcas_yml().read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return {}
    return datos if isinstance(datos, dict) else {}


def inventario() -> list[dict]:
    """Cada llave con dónde vive y si está marcada en Bitwarden. Sólo `stat`.

    Etiqueta honesta (regla 13): «marcada en Bitwarden» es lo que el dueño o
    `subir` apuntaron, no una comprobación contra su caja, que el hub no abre.
    """
    marcas = _marcas()
    filas, reclamadas = [], set()
    for llave in declaradas():
        try:
            puntero = llave.puntero()
        except Exception:  # noqa: BLE001 - un ajuste roto no tumba el inventario
            puntero = None
        if puntero:
            reclamadas.add(_ruta(puntero))
        filas.append(_fila(llave.nombre, llave.para, puntero, llave.sesion, marcas))
    secretos = carpetas()[0]
    if secretos.is_dir():
        for p in sorted(secretos.iterdir()):
            if p in reclamadas or p == _cola():
                continue
            filas.append(_fila(f"suelta:{p.name}", "nadie la declara: no se supone qué es", str(p), False, marcas))
    ssh = carpetas()[1]
    if ssh.is_dir():
        for pub in sorted(ssh.glob("*.pub")):
            privada = pub.with_suffix("")
            if privada.exists():
                filas.append(_fila(f"ssh:{privada.name}", "clave ssh", str(privada), False, marcas))
    # 🔴 De la cola se lee el `.para`, nunca el `.json`: ése lleva el valor, y
    # esto lo llama `hub-web`.
    for p in sorted(_cola().glob("*.json")) if _cola().is_dir() else []:
        try:
            para = p.with_suffix(".para").read_text(encoding="utf-8").strip()
        except OSError:
            para = ""
        filas.append({**_fila(f"cola:{p.stem}", para, str(p), False, marcas), "en_cola": True})
    return filas


def _fila(nombre: str, para: str, puntero: str | None, sesion: bool, marcas: dict) -> dict:
    marca = marcas.get(nombre) or {}
    return {
        "nombre": nombre, "para": para, "puntero": puntero or "",
        "clave": puntero.split("#", 1)[1] if puntero and "#" in puntero else "",
        "estado": _estado_archivo(_ruta(puntero)) if puntero else "sin configurar",
        "sesion": sesion,
        "bitwarden": marca.get("elemento", ""),
        "marcada": marca.get("cuando", ""),
    }


# ── marcar (la única escritura del hub) ──────────────────────────────────────

def marcar(nombre: str, elemento: str = "") -> None:
    """Apunta que esa llave está en Bitwarden. Sin el valor, sólo el nombre."""
    from .reloj import ahora

    if not any(f["nombre"] == nombre for f in inventario()):
        raise ValueError(f"no hay ninguna llave «{nombre}»")
    marcas = _marcas()
    marcas[nombre] = {"elemento": elemento or f"bw://{CARPETA_BW}/{nombre}", "cuando": ahora()}
    _guardar_marcas(marcas)


def desmarcar(nombre: str) -> None:
    marcas = _marcas()
    if marcas.pop(nombre, None) is not None:
        _guardar_marcas(marcas)


def _guardar_marcas(marcas: dict) -> None:
    _marcas_yml().parent.mkdir(parents=True, exist_ok=True)
    tmp = _marcas_yml().with_suffix(".tmp")
    tmp.write_text(yaml.safe_dump(marcas, allow_unicode=True, sort_keys=True), encoding="utf-8")
    tmp.replace(_marcas_yml())


# ── la cola: Claude encola, el dueño sube ────────────────────────────────────

def _leer_cola(p: Path) -> dict:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def encolar(nombre: str, para: str, *, ruta: str = "", valor: str = "") -> Path:
    """Deja una llave para que el dueño la suba. O un puntero (`ruta`) a una que
    ya está en disco, o el valor de una nueva, que se escribe 600 en la cola —un
    secreto en disco como los demás de `~/.secretos`— y se borra al subirla."""
    if not _NOMBRE.match(nombre or ""):
        raise ValueError("nombre de llave no válido: minúsculas, números, punto, guion")
    if bool(ruta) == bool(valor):
        raise ValueError("o la ruta de una llave que ya existe, o el valor de una nueva")
    if ruta:
        r = _ruta(ruta).resolve()
        if not r.exists():
            raise ValueError(f"no existe {ruta}")
        # Sólo lo que ya es una llave: una ruta cualquiera (un proyecto, `~`)
        # acabaría entera en Bitwarden al subir (revisor de C-0143).
        if not any(r == c.resolve() or c.resolve() in r.parents for c in carpetas()):
            raise ValueError(f"sólo se encolan llaves de {', '.join(CARPETAS)}")
        for f in inventario():
            if f["puntero"] and not f.get("en_cola") and _ruta(f["puntero"]).resolve() == r:
                raise ValueError(f"ya está en el inventario como «{f['nombre']}»: `subir` la sube sola")
    if valor and len(valor.encode()) > TOPE:
        raise ValueError("eso no es una llave")
    secretos = carpetas()[0]
    secretos.mkdir(mode=0o700, exist_ok=True)
    d = _cola()
    d.mkdir(mode=0o700, exist_ok=True)
    os.chmod(d, 0o700)
    destino = d / f"{nombre}.json"
    for ruta_, contenido in ((destino.with_suffix(".para"), para.strip()),
                             (destino, json.dumps({"nombre": nombre, "ruta": ruta, "valor": valor}))):
        fd = os.open(ruta_, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        # O_TRUNC sobre uno que ya existía conserva sus permisos: se fuerzan.
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(contenido)
    return destino


# ── subir: sólo el dueño, en su terminal ─────────────────────────────────────

class NoDesdeAqui(RuntimeError):
    """`subir` sin terminal o sin la caja abierta."""


def _bw(args: list[str], entrada: str = "") -> str:
    """`bw` con la sesión del dueño. La salida no se imprime nunca: trae el
    elemento descifrado. Se devuelve para sacar el id, y nada más."""
    r = subprocess.run(["bw", *args], input=entrada, capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        # El error de bw no lleva el valor (lo lee por la entrada estándar).
        raise RuntimeError(f"bw {args[0]} falló: {(r.stderr or '').strip()[:200]}")
    return r.stdout


def _codificar(objeto: dict) -> str:
    """Lo que hace `bw encode`: el JSON en base64, sin pasar por otro proceso."""
    return base64.b64encode(json.dumps(objeto).encode("utf-8")).decode("ascii")


def _carpeta_bw() -> str:
    for f in json.loads(_bw(["list", "folders", "--search", CARPETA_BW]) or "[]"):
        if f.get("name") == CARPETA_BW:
            return f["id"]
    return json.loads(_bw(["create", "folder"], _codificar({"name": CARPETA_BW})))["id"]


def _ya_en_bw(carpeta: str) -> set[str]:
    # Trae notas descifradas: sólo se guardan los nombres.
    return {i.get("name") for i in json.loads(_bw(["list", "items", "--folderid", carpeta]) or "[]")}


def _archivos_de(puntero: str) -> list[tuple[str, Path]]:
    """Qué archivos sube una llave: el suyo, o los de su carpeta que no sean
    sesiones ni demasiado grandes para ser una llave."""
    import fnmatch

    ruta = _ruta(puntero)
    if ruta.is_file():
        return [("", ruta)] if ruta.stat().st_size <= TOPE else []
    if not ruta.is_dir():
        return []
    salida = []
    for p in sorted(ruta.rglob("*")):
        if (p.is_file() and p.stat().st_size <= TOPE
                and not any(fnmatch.fnmatch(p.name, s) for s in _SESIONES)):
            salida.append(("/" + str(p.relative_to(ruta)), p))
    return salida


def _preguntar() -> bool:
    return input("¿Subir? Escribe «sí»: ").strip().lower() in ("sí", "si")


def subir(nombres: list[str] | None = None, salida=print, confirmar: Callable[[], bool] = _preguntar) -> int:
    """Sube a la carpeta «hub» de Bitwarden lo que falta. Devuelve cuántas.

    Cada archivo es una nota segura con nombre `hub/<llave>[/<archivo>]`; lo
    que ya hay con ese nombre no se pisa.
    """
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        raise NoDesdeAqui("esto se corre en tu terminal, no desde un agente ni un servicio")
    if not os.environ.get("BW_SESSION"):
        raise NoDesdeAqui("abre la caja: export BW_SESSION=$(bw unlock --raw)")
    carpeta = _carpeta_bw()
    ya = _ya_en_bw(carpeta)
    filas = inventario()
    plan = []   # (fila, cola, nombre, [(titulo, ruta, valor)])
    for fila in filas:
        if nombres and fila["nombre"] not in nombres:
            continue
        cola = Path(fila["puntero"]) if fila.get("en_cola") else None
        if not cola and (fila["sesion"] or not fila["puntero"] or fila["bitwarden"]):
            continue
        datos = _leer_cola(cola) if cola else {}
        nombre = datos.get("nombre") or fila["nombre"]
        if datos.get("valor"):
            piezas = [("", None, datos["valor"])]
        else:
            piezas = [(sufijo, ruta, None) for sufijo, ruta in _archivos_de(datos.get("ruta") or fila["puntero"])]
        piezas = [(f"{CARPETA_BW}/{nombre}{s}", r, v) for s, r, v in piezas]
        if piezas:
            plan.append((fila, cola, nombre, piezas))
    if not plan:
        salida("nada que subir")
        return 0
    # Claude encola, el dueño confirma (C-0143): lo que va a salir se ve antes.
    salida("Va a subir a la carpeta «hub» de tu Bitwarden:")
    for fila, _, _, piezas in plan:
        for titulo, ruta, _ in piezas:
            salida(f"  {titulo}" + ("  (ya está, no se pisa)" if titulo in ya else "")
                   + (f"  ← {ruta}" if ruta else "  (de la cola)"))
    if not confirmar():
        salida("no se subió nada")
        return 0
    hechas = 0
    for fila, cola, nombre, piezas in plan:
        try:
            for titulo, ruta, valor in piezas:
                if titulo in ya:
                    continue
                # Estricto: un binario «arreglado» con reemplazos quedaría
                # marcado como respaldado y no se podría recuperar (regla 13).
                texto = valor if valor is not None else ruta.read_bytes().decode("utf-8")
                _bw(["create", "item"], _codificar({
                    "type": 2, "secureNote": {"type": 0}, "folderId": carpeta, "name": titulo,
                    "notes": texto, "fields": [{"name": "para", "value": fila["para"], "type": 0}],
                }))
                salida(f"✓ {titulo}")
        except UnicodeDecodeError:
            salida(f"✗ {fila['nombre']}: tiene un archivo que no es texto; súbelo a mano como adjunto")
            continue
        elemento = f"bw://{CARPETA_BW}/{nombre}"
        if cola:
            cola.unlink(missing_ok=True)
            cola.with_suffix(".para").unlink(missing_ok=True)
        else:
            marcar(fila["nombre"], elemento)
        hechas += 1
    return hechas


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - fino sobre lo de arriba
    p = argparse.ArgumentParser(prog="hub.llavero", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="orden", required=True)
    sub.add_parser("lista")
    m = sub.add_parser("marcar")
    m.add_argument("nombre")
    m.add_argument("elemento", nargs="?", default="")
    e = sub.add_parser("encolar")
    e.add_argument("nombre")
    e.add_argument("--para", required=True)
    e.add_argument("--ruta", default="")
    s = sub.add_parser("subir")
    s.add_argument("nombres", nargs="*")
    args = p.parse_args(argv)
    try:
        if args.orden == "lista":
            for f in inventario():
                bw = f"Bitwarden: {f['bitwarden']}" if f["bitwarden"] else (
                    "sesión: no se sube" if f["sesion"] else "⚠ sólo en esta máquina")
                print(f"{f['nombre']:<28} {f['estado']:<22} {bw}\n{'':<29}{f['para']} · {f['puntero'] or '—'}")
        elif args.orden == "marcar":
            marcar(args.nombre, args.elemento)
            print(f"{args.nombre} marcada en Bitwarden")
        elif args.orden == "encolar":
            valor = "" if args.ruta else sys.stdin.read().strip()
            print(f"en la cola: {encolar(args.nombre, args.para, ruta=args.ruta, valor=valor)}")
        else:
            print(f"{subir(args.nombres)} llave(s) subida(s)")
        return 0
    except (ValueError, NoDesdeAqui, RuntimeError) as exc:
        print(exc, file=sys.stderr)
        return 2


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
