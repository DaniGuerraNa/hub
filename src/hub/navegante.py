"""El navegante —el navegador que maneja Claude—, visto desde el hub: qué pide permiso y qué ha hecho.

El laboratorio (`navegador-lab`) es otro proyecto: tiene su guardián, que pausa
las peticiones que modifican y deja una pregunta por archivo en su carpeta de
datos. El hub **contesta** esas preguntas —lo único que el dueño tiene que poder
hacer desde el teléfono, escribiendo la respuesta en la carpeta de aprobaciones
del laboratorio— y además **maneja** el laboratorio desde la pantalla (decisión
274): encender, vista en vivo, guardián, grabar, componer y correr flujos, pero
siempre por `nav` y con una lista cerrada de órdenes (`hacer`). Aprobar no está
en esa lista: el permiso lo da el dueño en el hub, nunca la sesión que lo pide
(decisión 256).

Lo que se pinta sale de `nav resumen --json`, salvo las preguntas, el registro,
las corridas y sus capturas, que se leen de los archivos de datos: así se ven
aunque el guardián esté caído —las preguntas viejas salen como caducadas— y el
hub no depende de que otro proceso responda para pintar.
"""
import json
import os
import re
import time
from pathlib import Path

ID_VALIDO = re.compile(r"^[\w-]{1,64}$")


def carpeta() -> Path:
    return Path(os.environ.get("NAV_DATOS") or Path.home() / ".local/share/navegador-lab")


def instalado() -> bool:
    return carpeta().is_dir()


def _leer(ruta: Path) -> dict | None:
    try:
        return json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def preguntas(limite: int = 30) -> list[dict]:
    d = carpeta() / "aprobaciones"
    if not d.is_dir():
        return []
    out = [x for x in (_leer(r) for r in sorted(d.glob("*.json"), reverse=True)[:200]) if x]
    out.sort(key=lambda x: (x.get("estado") != "pendiente", -float(x.get("creada") or 0)))
    return out[:limite]


def pendientes() -> int:
    d = carpeta() / "aprobaciones"
    if not d.is_dir():
        return 0
    return sum(1 for r in d.glob("*.json") if (_leer(r) or {}).get("estado") == "pendiente")


def registro(n: int = 40) -> list[dict]:
    """Las últimas decisiones que importan: lo bloqueado, lo preguntado y lo
    permitido que no era una lectura simple. Leído desde el final, sin cargar el
    archivo entero, que crece con cada sesión."""
    f = carpeta() / "registro.jsonl"
    if not f.exists():
        return []
    with f.open("rb") as h:
        h.seek(0, 2)
        tam = h.tell()
        h.seek(max(0, tam - 200_000))
        lineas = h.read().decode("utf-8", "replace").splitlines()[-n:]
    out = []
    for l in reversed(lineas):
        try:
            out.append(json.loads(l))
        except ValueError:
            continue
    return out


def responder(pid: str, aprobar: bool) -> dict:
    """La respuesta del dueño. Sólo sobre una pregunta pendiente y por id validado:
    el id llega de un formulario y acaba en una ruta."""
    if not ID_VALIDO.match(pid or ""):
        raise ValueError("id no válido")
    ruta = carpeta() / "aprobaciones" / f"{pid}.json"
    d = _leer(ruta)
    if d is None:
        raise ValueError("esa pregunta no existe")
    if d.get("estado") != "pendiente":
        raise ValueError(f"ya está {d.get('estado')}")
    d["estado"] = "aprobada" if aprobar else "denegada"
    d["respondida"] = time.time()
    d["desde"] = "hub"
    tmp = ruta.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    tmp.replace(ruta)
    return d


# ───────────────────── manejar el laboratorio, por su `nav` ─────────────────────
#
# El hub no sabe encender un navegador ni grabar: se lo pide a `nav`, el mismo
# comando que usan el dueño y Claude en la terminal. Así lo que hace un botón es
# exactamente lo que haría el comando, y si el laboratorio cambia por dentro el
# hub no se entera. Y es una lista CERRADA: el formulario elige qué orden, nunca
# escribe la línea de comandos (regla dura 10).

NOMBRE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
CLAVE = re.compile(r"^\w{1,40}$")


def lab() -> Path:
    from . import componentes
    return componentes.carpeta("navegador-lab")


def disponible() -> bool:
    return (lab() / "bin" / "nav").exists()


def _nav(*args: str, timeout: float = 30) -> tuple[bool, str]:
    import subprocess
    from . import tmux
    try:
        r = subprocess.run([str(lab() / "bin" / "nav"), *args], capture_output=True, text=True,
                           timeout=timeout, env={**os.environ, "PATH": tmux.path_de_usuario()})
    except subprocess.TimeoutExpired:
        return False, f"`nav {args[0]}` no respondió en {int(timeout)} s"
    except OSError as exc:
        return False, f"no se pudo ejecutar nav: {exc}"
    salida = (r.stdout + ("\n" + r.stderr if r.returncode else "")).strip()
    return r.returncode == 0, salida


def _json(*args: str):
    ok, salida = _nav(*args, "--json", timeout=15)
    if not ok:
        return None
    try:
        return json.loads(salida.splitlines()[-1])
    except (ValueError, IndexError):
        return None


def resumen() -> dict | None:
    """Estado, flujos, políticas y configuración del laboratorio, en una llamada."""
    return _json("resumen") if disponible() else None


def flujos() -> list[dict]:
    return (resumen() or {}).get("flujos", [])


def politicas() -> list[dict]:
    return (resumen() or {}).get("politicas", [])


def colecciones() -> list[str]:
    return [c["nombre"] for c in ((resumen() or {}).get("config") or {}).get("colecciones", [])]


def parametros(texto: str) -> list[str]:
    """`clave=valor` por línea → ['clave=valor', …], validando la clave. El
    valor es libre (una consulta de Logs Insights lleva de todo) y viaja como un
    argumento, nunca por una shell."""
    out = []
    for linea in (texto or "").splitlines():
        if not linea.strip():
            continue
        k, sep, v = linea.partition("=")
        k = k.strip()
        if not sep or not CLAVE.match(k):
            raise ValueError(f"parámetro mal escrito: «{linea.strip()[:40]}» (va clave=valor)")
        out.append(f"{k}={v.strip()}")
    return out


def hacer(que: str, f: dict) -> tuple[bool, str]:
    """Una orden del formulario → un `nav`. Lo que no esté aquí no se hace."""
    if not disponible():
        return False, f"no encuentro el laboratorio en {lab()}"
    if que == "encender":
        return _nav("navegador", timeout=20)
    if que == "cerrar":
        return _nav("cerrar", timeout=20)
    if que == "panel":
        return _nav("panel", timeout=40)
    if que == "ir":
        url = str(f.get("url") or "").strip()
        if not re.match(r"^https?://[^\s]{1,2000}$", url):
            raise ValueError("la dirección tiene que empezar por http:// o https://")
        return _nav("ir", url, timeout=40)
    if que == "guardian":
        pol = str(f.get("politica") or "")
        if pol not in {p["archivo"] for p in politicas()}:
            raise ValueError("esa política no existe")
        return _nav("guardian", "--politica", pol, "--fondo", timeout=20)
    if que == "parar-guardian":
        return _nav("parar-guardian", timeout=15)
    if que == "grabar":
        return _nav("grabar", "empezar", timeout=60)
    if que == "parar-grabacion":
        nombre = str(f.get("nombre") or "").strip()
        if not NOMBRE.match(nombre):
            raise ValueError("el nombre va en minúsculas, números y guiones (p. ej. errores-pedidos)")
        args = ["grabar", "parar", nombre, "--json"]
        for k in ("desde", "hasta"):
            v = str(f.get(k) or "").strip()
            if v:
                if not NOMBRE.match(v):
                    raise ValueError("una pantalla se nombra en minúsculas y guiones (apigw-lista)")
                args += [f"--{k}", v]
        col = str(f.get("coleccion") or "")
        if col:
            if col not in colecciones():
                raise ValueError("esa colección no existe")
            args += ["--coleccion", col]
        if f.get("descripcion"):
            args += ["--descripcion", str(f["descripcion"])[:300]]
        for p in parametros(str(f.get("parametros") or "")):
            args += ["-p", p]
        return _nav(*args, timeout=60)
    if que == "correr":
        nombre = str(f.get("flujo") or "")
        if nombre not in {f_["coleccion"] + "/" + f_["nombre"] for f_ in flujos()}:
            raise ValueError("ese flujo no existe")
        args = ["flujo", nombre, "--fondo"]
        for k, v in f.items():
            if k.startswith("p_") and CLAVE.match(k[2:]) and str(v).strip():
                args += ["-p", f"{k[2:]}={str(v).strip()}"]
        return _nav(*args, timeout=20)
    if que == "componer":
        nombre = str(f.get("nombre") or "").strip()
        if not NOMBRE.match(nombre):
            raise ValueError("el nombre va en minúsculas, números y guiones")
        existentes = {x["coleccion"] + "/" + x["nombre"] for x in flujos()}
        piezas = [str(f.get(f"pieza_{i}") or "") for i in range(1, 9)]
        piezas = [p for p in piezas if p]
        if len(piezas) < 2:
            raise ValueError("elige al menos dos fragmentos, en orden")
        if any(p not in existentes for p in piezas):
            raise ValueError("algún fragmento no existe")
        args = ["componer", nombre, *piezas, "--json"]
        col = str(f.get("coleccion") or "")
        if col:
            if col not in colecciones():
                raise ValueError("esa colección no existe")
            args += ["--coleccion", col]
        if f.get("descripcion"):
            args += ["--descripcion", str(f["descripcion"])[:300]]
        return _nav(*args, timeout=30)
    if que == "pantallas":
        nombre = str(f.get("flujo") or "")
        if nombre not in {x["coleccion"] + "/" + x["nombre"] for x in flujos()}:
            raise ValueError("ese flujo no existe")
        desde, hasta = (str(f.get(k) or "").strip() for k in ("desde", "hasta"))
        for v in (desde, hasta):
            if v and not NOMBRE.match(v):
                raise ValueError("una pantalla se nombra en minúsculas y guiones (apigw-lista)")
        if not desde:
            raise ValueError("falta la pantalla donde empieza")
        return _nav("pantallas", nombre, desde, *([hasta] if hasta else []), timeout=20)
    if que == "acceso":
        nombre_ = str(f.get("nombre") or "").strip()[:40]
        url = str(f.get("url") or "").strip()
        if not nombre_ or not re.match(r"^https?://[^\s]{1,2000}$", url):
            raise ValueError("pon un nombre y una dirección que empiece por http(s)://")
        return _nav("acceso", nombre_, url, timeout=20)
    if que == "quitar-acceso":
        return _nav("acceso", str(f.get("nombre") or "")[:40], "--quitar", timeout=20)
    raise ValueError(f"orden desconocida: {que}")


# ─────────────────────────────── las corridas ───────────────────────────────


def corridas(n: int = 15) -> list[dict]:
    d = carpeta() / "salidas"
    if not d.is_dir():
        return []
    todas = sorted((c for f in d.iterdir() if f.is_dir() for c in f.iterdir() if c.is_dir()),
                   key=lambda c: c.name, reverse=True)[:n]
    out = []
    for c in todas:
        if (c / "resultado.json").exists():
            estado_ = "bien"
        elif (c / "fallo.json").exists():
            estado_ = "fallo"
        elif (c / "en-curso.json").exists() and Path(f"/proc/{(_leer(c / 'en-curso.json') or {}).get('pid')}").exists():
            estado_ = "en-curso"
        else:
            estado_ = "cortada"
        out.append({"flujo": c.parent.name, "cuando": c.name, "estado": estado_})
    return out


def _carpeta_corrida(flujo: str, cuando: str) -> Path:
    if not NOMBRE.match(flujo) or not re.match(r"^\d{8}-\d{6}$", cuando):
        raise ValueError("corrida no válida")
    c = carpeta() / "salidas" / flujo / cuando
    if not c.is_dir():
        raise ValueError("esa corrida no existe")
    return c


def corrida(flujo: str, cuando: str) -> dict:
    c = _carpeta_corrida(flujo, cuando)
    r = _leer(c / "resultado.json")
    fallo = _leer(c / "fallo.json")
    return {"flujo": flujo, "cuando": cuando, "resultado": r, "fallo": fallo,
            "imagenes": sorted(p.name for p in c.glob("*.png"))}


def imagen(flujo: str, cuando: str, nombre: str) -> Path:
    c = _carpeta_corrida(flujo, cuando)
    if not re.match(r"^[\w.-]{1,80}\.png$", nombre):
        raise ValueError("imagen no válida")
    p = c / nombre
    if not p.is_file():
        raise ValueError("esa imagen no existe")
    return p
