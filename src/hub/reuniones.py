"""Reuniones: el hub da la orden de grabar y enseña lo procesado.

Tres piezas, cada una donde puede hacer su trabajo:

- **El agente de Windows** (`~/projects/reuniones/agente`) graba: es el único
  que ve el escritorio y el audio de las aplicaciones. No escucha en ningún
  puerto: llama aquí cada segundo (`/api/reuniones/latido`) contando qué ve
  (monitores, micros, apps con audio) y recibe la orden vigente.
- **El hub** guarda esa orden y lo último que contó el agente, en archivos de
  su carpeta de datos —nada de esto está en `projects.yml` ni hace falta
  reconstruirlo (regla dura 1: no va a la base)—.
- **El procesado** (`reuniones procesar`, en WSL) transcribe en la GPU y
  resume. El hub lo lanza cuando el agente dice que terminó una grabación.

🔴 Lo grabado es contenido laboral y de terceros. Nada de aquí sale de la
máquina salvo el texto de la transcripción, que va a Claude para el resumen.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import subprocess
import time
from pathlib import Path

from . import config

ID = re.compile(r"^\d{8}-\d{6}$")
VIVO_S = 6


def carpeta() -> Path:
    d = config.HUB_HOME / "reuniones"
    d.mkdir(parents=True, exist_ok=True)
    return d


def proyecto() -> Path:
    from . import componentes
    return componentes.carpeta("reuniones")


# ───────────────────────────── dónde está el agente ─────────────────────────────
#
# El agente guarda las grabaciones junto a su carpeta (`<base>\\agente` →
# `<base>\\grabaciones`), así que basta un dato: dónde lo pusiste en Windows.
# Lo da la persona en la pantalla y se guarda en la carpeta de datos del hub.
# Sin él, `D:\\reuniones`, que es donde vivía antes de poder elegirse: así una
# instalación de entonces sigue funcionando sin tocar nada.

POR_OMISION_WINDOWS = r"D:\reuniones\agente"
SUGERIDA_WINDOWS = r"C:\reuniones\agente"
# Sin `/`: Windows la acepta como separador, y `C:\\a/..\\b` colaría un `..`
# que el troceo por `\\` no vería.
_WINDOWS = re.compile(r"^([A-Za-z]):\\([^:*?\"<>|\r\n/]*)$")


def _ajustes() -> Path:
    return carpeta() / "ajustes.json"


def carpeta_windows() -> str | None:
    """La carpeta del agente que dio la persona, tal como la escribió."""
    return (_leer(_ajustes()) or {}).get("agente_windows")


def a_wsl(ruta: str) -> Path:
    """`C:\\reuniones\\agente` → `/mnt/c/reuniones/agente`.

    🔴 Llega de un formulario y acaba siendo donde el hub escribe, así que se
    valida entera: una unidad y una ruta absoluta, sin `..` ni caracteres que
    Windows no admite."""
    m = _WINDOWS.match((ruta or "").strip())
    if not m:
        raise ValueError("escribe una ruta de Windows completa, como C:\\reuniones\\agente")
    partes = [p for p in m.group(2).split("\\") if p]
    if not partes or any(p in (".", "..") for p in partes):
        raise ValueError("la ruta no puede ser la raíz de la unidad ni llevar «..»")
    return Path("/mnt", m.group(1).lower(), *partes)


def guardar_carpeta_windows(ruta: str) -> Path:
    destino = a_wsl(ruta)
    _escribir(_ajustes(), {**(_leer(_ajustes()) or {}), "agente_windows": ruta.strip().rstrip("\\")})
    return destino


def carpeta_agente() -> Path:
    """Donde está el agente de Windows, visto desde WSL."""
    if os.environ.get("REUNIONES_AGENTE"):
        return Path(os.environ["REUNIONES_AGENTE"])
    if os.environ.get("REUNIONES_RAIZ"):
        return Path(os.environ["REUNIONES_RAIZ"]).parent / "agente"
    return a_wsl(carpeta_windows() or POR_OMISION_WINDOWS)


def raiz() -> Path:
    """Donde están las grabaciones: junto al agente, salvo que se diga otra cosa."""
    return Path(os.environ.get("REUNIONES_RAIZ") or carpeta_agente().parent / "grabaciones")


# Lo que el agente necesita en Windows. El `token` no está: lo escribe
# «Generar la llave», y copiar otra vez el agente no puede borrar la que hay.
ARCHIVOS_AGENTE = ("agente.py", "pyproject.toml", "uv.lock", "iniciar.cmd", "instalar.cmd")


def copiar_agente() -> dict:
    """Deja el agente en la carpeta que dio la persona, listo para `instalar.cmd`.

    Lo pide ella con un botón y escribe sólo ahí, en la carpeta que eligió para
    él. `iniciar.cmd` sale con el puerto de ESTE hub: el de la copia dice 8787,
    y un hub en otro puerto no recibiría ningún latido. Los `.cmd` van con
    saltos de Windows, que es donde se ejecutan."""
    origen = proyecto() / "agente"
    if not (origen / "agente.py").exists():
        raise ValueError(f"no encuentro el agente en {origen}")
    destino = carpeta_agente()
    if not destino.parent.parent.is_dir():
        raise ValueError(f"no se ve {destino.parent.parent} desde aquí: ¿es una unidad de Windows montada en WSL?")
    destino.mkdir(parents=True, exist_ok=True)
    for nombre in ARCHIVOS_AGENTE:
        datos = (origen / nombre).read_bytes()
        if nombre.endswith(".cmd"):
            texto = datos.decode("utf-8").replace("\r\n", "\n")
            if nombre == "iniciar.cmd":
                texto = re.sub(r"set REUNIONES_HUB=\S+", f"set REUNIONES_HUB=http://127.0.0.1:{config.WEB_PORT}", texto)
            datos = texto.replace("\n", "\r\n").encode("utf-8")
        (destino / nombre).write_bytes(datos)
    return {"carpeta": str(destino), "windows": carpeta_windows() or POR_OMISION_WINDOWS,
            "archivos": list(ARCHIVOS_AGENTE)}


def preparacion() -> dict:
    """Los pasos para tener Reuniones funcionando, de WSL a Windows."""
    from . import componentes
    destino = carpeta_agente()
    # Que haya llamado ALGUNA vez, no que esté vivo ahora: con Windows apagado
    # el agente no late, y eso no es que falte instalarlo. Lo dice su tarjeta.
    # Un agente que llama con una llave que no vale también está instalado: lo
    # que le falta es la llave, y eso es otro paso.
    llamo = agente()["hace"] is not None or rechazo_reciente() is not None
    pasos = componentes.pasos_reuniones_wsl() + [
        componentes._paso("carpeta", "Dónde va el agente en Windows",
                          bool(carpeta_windows()) or destino.is_dir(),
                          "Una carpeta de Windows para el agente; las grabaciones irán a la de al lado."),
        componentes._paso("agente", "El agente está en esa carpeta", (destino / "agente.py").exists(),
                          "«Copiar el agente» lo deja ahí, con el puerto de este hub."),
        componentes._paso("instalado", "El agente está instalado en Windows", llamo,
                          "Doble clic en instalar.cmd dentro de esa carpeta. Necesita uv para Windows."),
        componentes._paso("llave", "Tiene su llave", hay_llave(), "«Generar la llave», aquí abajo."),
    ]
    return {"pasos": pasos, "listo": componentes.listo(pasos),
            "windows": carpeta_windows() or (POR_OMISION_WINDOWS if destino.is_dir() else SUGERIDA_WINDOWS),
            "carpeta": str(destino)}


# ───────────────────────────── la llave ─────────────────────────────
#
# 🔴 Sólo el agente habla por `/api/reuniones/*`, y lo demuestra con una llave
# (decisión 280). La puerta de dispositivos decide por el `Host`, y un aparato
# de la red privada que forje `Host: localhost` la pasa: con estos endpoints
# podría ordenar procesar (lo que manda la transcripción a Claude) o colar
# miniaturas. La llave se exige venga de donde venga, también desde casa.
#
# Aquí se guarda el HASH, nunca la llave —igual que los testigos de `acceso`—:
# quien lea la carpeta de datos del hub no puede hacerse pasar por el agente, y
# la base no la ve (regla dura 5). La llave en claro vive sólo junto al agente.

CABECERA = "X-Reuniones-Token"


def _hash_llave() -> Path:
    return carpeta() / "agente.llave.sha256"


def hay_llave() -> bool:
    return _hash_llave().is_file()


def llave_valida(valor: str | None) -> bool:
    if not valor:
        return False
    try:
        guardado = _hash_llave().read_text(encoding="utf-8").strip()
    except OSError:
        return False
    return hmac.compare_digest(hashlib.sha256(valor.strip().encode()).hexdigest(), guardado)


def llave_rechazada() -> None:
    """El agente llamó con una llave que no vale: la pantalla lo cuenta en vez
    de decir sólo «desconectado», que manda a buscar el fallo en otro sitio."""
    _escribir(carpeta() / "rechazo.json", {"t": time.time()})


def rechazo_reciente() -> float | None:
    r = _leer(carpeta() / "rechazo.json") or {}
    hace = time.time() - float(r.get("t") or 0)
    return round(hace) if r and hace < 60 else None


def conectar_agente() -> dict:
    """Saca una llave nueva —la anterior deja de valer— y la deja donde la lee
    el agente, si su carpeta se ve desde aquí.

    Escribir en la carpeta del agente es una excepción a «el hub no escribe en
    proyectos ajenos», acotada a un archivo (`token`) de una instalación, no de
    un repo, y es lo que permite configurarlo desde la pantalla sin copiar nada
    a mano (decisión 280). Si la carpeta no está, la llave se enseña una vez y
    se copia a mano: no se guarda en claro en ningún sitio del hub."""
    llave = secrets.token_urlsafe(32)
    destino = carpeta_agente()
    escrito = None
    if destino.is_dir():
        f = destino / "token"
        f.write_text(llave + "\n", encoding="utf-8")
        try:
            f.chmod(0o600)
        except OSError:
            pass                                    # en /mnt/d los permisos son de Windows
        escrito = str(f)
    h = _hash_llave()
    tmp = h.with_suffix(".tmp")
    tmp.write_text(hashlib.sha256(llave.encode()).hexdigest() + "\n", encoding="utf-8")
    tmp.chmod(0o600)
    tmp.replace(h)
    (carpeta() / "rechazo.json").unlink(missing_ok=True)
    return {"llave": llave, "escrita_en": escrito, "carpeta": str(destino)}


def _leer(ruta: Path):
    try:
        return json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _escribir(ruta: Path, datos) -> None:
    tmp = ruta.with_suffix(".tmp")
    tmp.write_text(json.dumps(datos, ensure_ascii=False), encoding="utf-8")
    tmp.replace(ruta)


# ───────────────────────────── el agente ─────────────────────────────


def orden() -> dict:
    return _leer(carpeta() / "orden.json") or {"grabar": False}


def latido(datos: dict) -> dict:
    """Lo que manda el agente cada segundo. Devuelve la orden vigente.

    Cuando el agente avisa de que terminó una grabación, se lanza su procesado:
    es el único momento en que se sabe que los archivos están cerrados."""
    if datos.get("terminada"):
        terminada(str(datos["terminada"]))
    datos = {k: datos.get(k) for k in ("agente", "equipo", "grabando", "monitores", "microfonos", "apps")}
    previo = _leer(carpeta() / "latido.json") or {}
    for k in ("monitores", "microfonos", "apps"):       # el inventario no llega en cada latido
        if datos.get(k) is None:
            datos[k] = previo.get(k)
    datos["t"] = time.time()
    _escribir(carpeta() / "latido.json", datos)
    return {"orden": orden(), "miniaturas": _consumir("pedir-miniaturas")}


def terminada(id_: str) -> None:
    if ID.match(id_ or ""):
        lanzar_procesado(id_)


def _consumir(nombre: str) -> bool:
    f = carpeta() / nombre
    if f.exists():
        f.unlink(missing_ok=True)
        return True
    return False


def agente() -> dict:
    l = _leer(carpeta() / "latido.json") or {}
    l["vivo"] = bool(l.get("t")) and time.time() - l["t"] < VIVO_S
    l["hace"] = int(time.time() - l["t"]) if l.get("t") else None
    return l


def pedir_miniaturas() -> None:
    (carpeta() / "pedir-miniaturas").touch()


def guardar_miniatura(n: int, cuerpo: bytes) -> None:
    if not 1 <= n <= 9 or len(cuerpo) > 1_000_000 or not cuerpo.startswith(b"\xff\xd8"):
        raise ValueError("miniatura no válida")
    d = carpeta() / "miniaturas"
    d.mkdir(exist_ok=True)
    (d / f"{n}.jpg").write_bytes(cuerpo)


def miniatura(n: int) -> Path | None:
    p = carpeta() / "miniaturas" / f"{n}.jpg"
    return p if 1 <= n <= 9 and p.exists() else None


def grabar(monitor: str, app: str, micro: str, titulo: str = "") -> dict:
    """La orden de grabar, validada contra lo que el agente dijo que ve: el
    formulario sólo puede elegir entre eso."""
    a = agente()
    if not a["vivo"]:
        raise ValueError("el agente de Windows no está conectado")
    if orden().get("grabar"):
        raise ValueError("ya se está grabando")
    mons = {str(m["n"]) for m in a.get("monitores") or []}
    apps = {x["nombre"]: x for x in a.get("apps") or []}
    mics = {str(m["n"]) for m in a.get("microfonos") or []}
    if monitor not in mons:
        raise ValueError("elige un monitor")
    if app and app not in apps:
        raise ValueError("esa aplicación ya no tiene audio abierto; refresca la lista")
    if micro and micro not in mics:
        raise ValueError("ese micrófono no existe")
    o = {"grabar": True, "id": time.strftime("%Y%m%d-%H%M%S"), "monitor": int(monitor),
         "app": app or None, "pid": apps[app]["pid"] if app else None, "micro": micro or None,
         "titulo": titulo.strip()[:120], "desde": time.time()}
    _escribir(carpeta() / "orden.json", o)
    return o


def parar() -> dict:
    o = orden()
    if not o.get("grabar"):
        raise ValueError("no se estaba grabando")
    o = {**o, "grabar": False, "hasta": time.time()}
    _escribir(carpeta() / "orden.json", o)
    return o


# ───────────────────────────── lo grabado ─────────────────────────────


def _lanzar(*args: str) -> None:
    """Una orden de `reuniones`, en segundo plano y con su salida al log."""
    from . import tmux
    log = open(carpeta() / "procesado.log", "a")
    subprocess.Popen(["uv", "run", "--quiet", "--project", str(proyecto()), "reuniones", *args],
                     cwd=proyecto(), stdout=log, stderr=log, start_new_session=True,
                     env={**os.environ, "PATH": tmux.path_de_usuario(), "REUNIONES_RAIZ": str(raiz())})


def _libre(id_: str) -> None:
    if (_leer(_dir(id_) / "procesado.json") or {}).get("estado") == "procesando":
        raise ValueError("se está procesando: espera a que termine")


def lanzar_procesado(id_: str) -> None:
    if not ID.match(id_):
        raise ValueError("id no válido")
    _lanzar("procesar", id_)


def lanzar_voces(id_: str) -> None:
    """Separar las voces de una ya procesada, y rehacer su resumen con ellas."""
    _libre(id_)
    _lanzar("voces", id_, "--resumen")


# Lo que se acepta como nombre: corto y de una línea. Va como argumento a un
# proceso (lista, sin shell) y acaba en un .md que lee Claude.
_NOMBRE = re.compile(r"^[\w .'’-]{0,60}$")


def lanzar_nombres(id_: str, nombres: dict[str, str], resumen: bool) -> None:
    """Pone nombre a las voces. Lo guarda `reuniones nombres`, que es quien
    conoce su carpeta: el hub no escribe en lo de otro proyecto."""
    _libre(id_)
    pares = []
    for clave, valor in nombres.items():
        valor = " ".join(str(valor).split())
        if not re.match(r"^Persona \d{1,3}$", clave) or not _NOMBRE.match(valor):
            raise ValueError(f"nombre no válido para {clave}: usa letras, espacios o guiones")
        pares.append(f"{clave}={valor}")
    _lanzar("nombres", id_, *pares, *(["--resumen"] if resumen else []))


def _tamano(d: Path) -> int:
    return sum(f.stat().st_size for f in d.rglob("*") if f.is_file())


def _comprimida(d: Path) -> bool:
    return not any((d / f"{p}.wav").exists() for p in ("reunion", "micro"))


def lanzar_compresion(ids: list[str]) -> None:
    """Comprimir el audio (WAV → Opus) es borrar el original: sólo cuando el
    dueño lo pide, nunca solo. Lo hace `reuniones comprimir`, que comprueba la
    duración antes de borrar nada."""
    ids = [i for i in ids if ID.match(i)]
    if any((_leer(raiz() / i / "procesado.json") or {}).get("estado") == "procesando" for i in ids):
        raise ValueError("se está procesando: comprime cuando termine")
    if not ids:
        raise ValueError("nada que comprimir")
    from . import tmux
    log = open(carpeta() / "procesado.log", "a")
    subprocess.Popen(["uv", "run", "--quiet", "--project", str(proyecto()), "reuniones", "comprimir", *ids],
                     cwd=proyecto(), stdout=log, stderr=log, start_new_session=True,
                     env={**os.environ, "PATH": tmux.path_de_usuario(), "REUNIONES_RAIZ": str(raiz())})


def sin_comprimir() -> list[str]:
    """Las terminadas que aún tienen WAV y no se están comprimiendo."""
    return [x["id"] for x in lista(500) if x["terminada"] and not x["comprimida"] and not x["comprimiendo"]
            and x["estado"] != "procesando"]


def _dir(id_: str) -> Path:
    if not ID.match(id_ or ""):
        raise ValueError("reunión no válida")
    d = raiz() / id_
    if not d.is_dir():
        raise ValueError("esa reunión no existe")
    return d


def lista(n: int = 50) -> list[dict]:
    r = raiz()
    if not r.is_dir():
        return []
    out = []
    for d in sorted((x for x in r.iterdir() if ID.match(x.name)), key=lambda x: x.name, reverse=True)[:n]:
        meta = _leer(d / "meta.json") or {}
        p = _leer(d / "procesado.json") or {}
        res = _leer(d / "resumen.json") or {}
        dur = int(meta["fin"] - meta["inicio"]) if meta.get("fin") is not None and meta.get("inicio") is not None else None
        out.append({"id": d.name, "titulo": res.get("titulo") or meta.get("titulo") or "",
                    "app": (meta.get("proceso") or {}).get("nombre"), "duracion": dur,
                    "estado": p.get("estado") or ("grabando" if not meta.get("fin") else "sin procesar"),
                    "tareas": len(res.get("tareas") or []), "terminada": bool(meta.get("fin")),
                    "tamano": _tamano(d), "comprimida": _comprimida(d),
                    "comprimiendo": (d / "comprimiendo").exists(),
                    "error_compresion": (_leer(d / "comprimido.json") or {}).get("error")})
    return out


def detalle(id_: str) -> dict:
    d = _dir(id_)
    return {"id": id_, "carpeta": str(d), "guia_voces": f"{proyecto()}/README.md",
            "meta": _leer(d / "meta.json") or {}, "procesado": _leer(d / "procesado.json") or {},
            "tamano": _tamano(d), "comprimida": _comprimida(d), "comprimiendo": (d / "comprimiendo").exists(),
            "compresion": _leer(d / "comprimido.json"),
            "resumen": _leer(d / "resumen.json"), "transcripcion": _leer(d / "transcripcion.json") or [],
            "nombres": _leer(d / "nombres.json") or {},
            "fotos": sorted(int(f.stem) for f in (d / "fotos").glob("*.jpg") if f.stem.isdigit())
            if (d / "fotos").is_dir() else []}


def foto(id_: str, segundo: int) -> Path:
    p = _dir(id_) / "fotos" / f"{int(segundo):06d}.jpg"
    if not p.is_file():
        raise ValueError("esa foto no existe")
    return p
