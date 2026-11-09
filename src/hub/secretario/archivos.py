"""Los archivos de sus proyectos, en sólo lectura (decisión 336).

El secretario sabía de sus mensajes y reuniones pero no de su trabajo: le
dictaban una ruta del workspace y contestaba que no podía leer archivos. Aquí
puede **listar, buscar y leer** dentro de los proyectos registrados en el hub
(`projects.yml`, su `asiento`), y en ningún otro sitio:

- La ruta se resuelve y tiene que quedar dentro del asiento: ni `..` ni un
  enlace simbólico sacan de ahí.
- Nunca abre lo que suele ser una llave (`.env`, `.pem`, `id_rsa`…): regla dura
  5. Y lo que lee pasa por `memoria.ocultar_secretos` antes de llegar al modelo.
- No escribe nada: el hub apunta y el proyecto decide (regla 16, decisión 69).

Lo leído va al modelo con la suscripción del dueño, como el resto de lo suyo
(decisión 302): es él quien lo pide, en su conversación.
"""

from __future__ import annotations

import fnmatch
import os
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from . import memoria

#: Lo que nunca se abre, por nombre de archivo.
LLAVES = (".env", ".env.*", "*.pem", "*.key", "*.p12", "*.pfx", "id_rsa*", "id_ed25519*", "*.keystore",
          ".npmrc", ".pypirc", ".pgpass", ".netrc", "credentials", "credentials.json", "*.kdbx",
          "*credential*", "*secret*", "*password*", "*keystore*", "*truststore*", "application-prod.y*ml")
#: Carpetas que no se abren nunca, estén donde estén.
CARPETAS_LLAVE = {"secrets", "secretos", ".secretos", ".ssh", ".aws", ".gnupg"}
#: Carpetas que no se recorren al buscar o al pedir lo reciente: pesan y no son suyas.
SALTAR = {".git", "node_modules", ".venv", "venv", "__pycache__", ".next", "dist", "build", ".gradle",
          ".idea", "Pods", ".terraform", "target", ".cache"}
MAX_LEER = 60_000
MAX_ARCHIVO = 5_000_000
TOPE_BUSCAR_S = 25


class FueraDeAlcance(ValueError):
    """La ruta no está dentro de un proyecto registrado, o es una llave."""


def raices() -> dict[str, Path]:
    from .. import registry
    out = {}
    for p in registry.cargar():
        if p.asiento and Path(p.asiento).is_dir():
            out[p.id] = Path(p.asiento)
    return out


def proyectos() -> list[dict]:
    from .. import registry
    return [{"id": p.id, "nombre": p.nombre, "dominio": p.dominio, "ruta": p.asiento, "nota": (p.nota or "")[:300]}
            for p in registry.cargar() if p.asiento]


def es_llave(nombre: str) -> bool:
    return any(fnmatch.fnmatch(nombre.lower(), patron) for patron in LLAVES)


def resolver(proyecto: str, ruta: str = "") -> tuple[Path, Path]:
    """(raíz, ruta) dentro del proyecto. Acepta la ruta relativa o la absoluta
    que él dicte, en Linux o con letra de Windows."""
    rs = raices()
    if proyecto not in rs:
        raise FueraDeAlcance(f"no hay un proyecto «{proyecto}» con carpeta; los que hay: {', '.join(sorted(rs))}")
    raiz = rs[proyecto].resolve()
    ruta = (ruta or "").strip().strip('"')
    m = re.match(r"^([a-zA-Z]):[\\/](.*)$", ruta)
    if m:
        ruta = f"/mnt/{m.group(1).lower()}/" + m.group(2).replace("\\", "/")
    destino = (Path(ruta) if ruta.startswith("/") else raiz / ruta).resolve()
    # En un disco de Windows (/mnt/c…) «Proyectos» y «proyectos» son la
    # misma carpeta: se compara sin mayúsculas y se rehace desde la raíz.
    windows = str(raiz).startswith("/mnt/")
    partes_r, partes_d = raiz.parts, destino.parts
    dentro = len(partes_d) >= len(partes_r) and all(
        (a.lower() == b.lower()) if windows else (a == b) for a, b in zip(partes_r, partes_d))
    if not dentro:
        raise FueraDeAlcance(f"{ruta} está fuera del proyecto {proyecto}")
    destino = raiz.joinpath(*partes_d[len(partes_r):])
    if any(parte.lower() in CARPETAS_LLAVE for parte in partes_d[len(partes_r):]):
        raise FueraDeAlcance("esa carpeta guarda llaves: no se abre")
    if destino.is_file() and es_llave(destino.name):
        raise FueraDeAlcance(f"{destino.name} parece una llave: no se abre")
    return raiz, destino


def _info(p: Path, raiz: Path) -> dict:
    try:
        st = p.stat()
    except OSError:
        return {"ruta": str(p.relative_to(raiz)), "tipo": "?"}
    return {"ruta": str(p.relative_to(raiz)) or ".", "tipo": "carpeta" if p.is_dir() else "archivo",
            "bytes": st.st_size if p.is_file() else None,
            "modificado": datetime.fromtimestamp(st.st_mtime, timezone.utc).isoformat(timespec="minutes")}


def listar(proyecto: str, ruta: str = "", n: int = 200) -> dict:
    raiz, d = resolver(proyecto, ruta)
    if not d.is_dir():
        raise FueraDeAlcance(f"{ruta} no es una carpeta")
    hijos = sorted(d.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
    hijos = [h for h in hijos if h.name not in SALTAR and h.name.lower() not in CARPETAS_LLAVE
             and not (h.is_file() and es_llave(h.name))]
    return {"proyecto": proyecto, "carpeta": str(d.relative_to(raiz)) or ".", "total": len(hijos),
            "entradas": [_info(h, raiz) for h in hijos[:n]]}


def _recorrer(d: Path, profundidad: int, carpetas: bool = False):
    try:
        hijos = list(os.scandir(d))
    except OSError:
        return
    for h in hijos:
        if h.name in SALTAR or h.name.startswith(".git") or h.name.lower() in CARPETAS_LLAVE:
            continue
        if h.is_dir(follow_symlinks=False):
            if carpetas:
                yield h
            if profundidad > 0:
                yield from _recorrer(Path(h.path), profundidad - 1, carpetas)
        elif not es_llave(h.name):
            yield h


def recientes(proyecto: str, ruta: str = "", n: int = 30, profundidad: int = 5) -> dict:
    """Lo último que tocó: los archivos modificados más recientemente."""
    raiz, d = resolver(proyecto, ruta)
    vistos = []
    for h in _recorrer(d, profundidad):
        try:
            vistos.append((h.stat().st_mtime, Path(h.path)))
        except OSError:
            continue
        if len(vistos) > 50_000:
            break
    vistos.sort(reverse=True)
    return {"proyecto": proyecto, "carpeta": str(d.relative_to(raiz)) or ".",
            "archivos": [_info(p, raiz) for _, p in vistos[:n]]}


def leer(proyecto: str, ruta: str, desde: int = 1, max_chars: int = MAX_LEER) -> dict:
    raiz, f = resolver(proyecto, ruta)
    if not f.is_file():
        raise FueraDeAlcance(f"{ruta} no es un archivo")
    if f.stat().st_size > MAX_ARCHIVO:
        raise FueraDeAlcance(f"{ruta} pesa {f.stat().st_size // 1_000_000} MB: demasiado para leerlo entero")
    crudo = f.read_bytes()
    if b"\x00" in crudo[:8000]:
        raise FueraDeAlcance(f"{ruta} es binario")
    lineas = crudo.decode("utf-8", errors="replace").splitlines()
    desde = max(1, int(desde or 1))
    texto = "\n".join(lineas[desde - 1:])
    cortado = len(texto) > max_chars
    return {"proyecto": proyecto, "ruta": str(f.relative_to(raiz)), "lineas": len(lineas), "desde": desde,
            "texto": memoria.ocultar_secretos(texto[:max_chars]),
            "cortado": f"sigue: pide desde la línea {desde + texto[:max_chars].count(chr(10)) + 1}" if cortado else ""}


TEXTO = {".md", ".txt", ".yaml", ".yml", ".json", ".js", ".ts", ".tsx", ".jsx", ".py", ".java", ".kt", ".swift",
         ".sql", ".sh", ".xml", ".csv", ".html", ".css", ".go", ".rb", ".php", ".cs", ".gradle", ".properties",
         ".toml", ".ini", ".cfg", ".tf", ".dart", ".vue", ".log", ""}


def _buscar_dentro(d: Path, raiz: Path, t: str, lineas: list, n: int) -> None:
    """Sin ripgrep: recorre con tope de tiempo y de tamaño. Lento sobre /mnt/c."""
    import time
    fin = time.monotonic() + TOPE_BUSCAR_S
    for h in _recorrer(d, 8):
        if time.monotonic() > fin:
            lineas.append({"ruta": "", "linea": 0, "texto": f"(se cortó a los {TOPE_BUSCAR_S} s: acota la carpeta)"})
            return
        if Path(h.name).suffix.lower() not in TEXTO:
            continue
        try:
            if h.stat().st_size > 1_000_000:
                continue
            with open(h.path, encoding="utf-8", errors="ignore") as f:
                halladas = 0
                for i, linea in enumerate(f, 1):
                    if t in linea.lower():
                        lineas.append({"ruta": str(Path(h.path).relative_to(raiz)), "linea": i,
                                       "texto": memoria.ocultar_secretos(linea.strip()[:300])})
                        halladas += 1
                        if halladas >= 3:
                            break
        except OSError:
            continue
        if len(lineas) >= n:
            return


def buscar(proyecto: str, texto: str, ruta: str = "", n: int = 40) -> dict:
    """Archivos cuyo nombre o contenido tiene `texto` (sin distinguir mayúsculas)."""
    raiz, d = resolver(proyecto, ruta)
    texto = (texto or "").strip()
    if not texto:
        raise FueraDeAlcance("dime qué buscar")
    nombres, lineas = [], []
    rg = shutil.which("rg")
    if rg:
        excluir = [a for s in SALTAR | CARPETAS_LLAVE for a in ("-g", f"!{s}")] + [a for llave in LLAVES for a in ("-g", f"!{llave}")]
        try:
            r = subprocess.run([rg, "-i", "-n", "-F", "--max-count", "3", "--max-filesize", "1M", *excluir,
                                "--", texto, str(d)], capture_output=True, text=True, timeout=TOPE_BUSCAR_S)
            for l in r.stdout.splitlines()[: n * 3]:
                ruta_, _, resto = l.partition(":")
                num, _, linea = resto.partition(":")
                lineas.append({"ruta": str(Path(ruta_).relative_to(raiz)), "linea": int(num) if num.isdigit() else 0,
                               "texto": memoria.ocultar_secretos(linea.strip()[:300])})
        except subprocess.TimeoutExpired:
            lineas.append({"ruta": "", "linea": 0, "texto": f"(la búsqueda pasó de {TOPE_BUSCAR_S} s: acota la carpeta)"})
    t = texto.lower()
    if not rg:
        _buscar_dentro(d, raiz, t, lineas, n)
    for h in _recorrer(d, 8, carpetas=True):
        if t in h.name.lower():
            nombres.append(_info(Path(h.path), raiz))
            if len(nombres) >= n:
                break
    return {"proyecto": proyecto, "carpeta": str(d.relative_to(raiz)) or ".", "por_nombre": nombres,
            "por_contenido": lineas[:n]}
