"""Reuniones: el hub da la orden de grabar y enseña lo procesado.

Cuatro piezas, cada una donde puede hacer su trabajo:

- **El agente de Windows** (`~/projects/reuniones/agente`) graba: es el único
  que ve el escritorio y el audio de las aplicaciones. No escucha en ningún
  puerto: llama aquí cada segundo (`/api/reuniones/latido`) contando qué ve
  (monitores, micros, apps con audio) y recibe la orden vigente.
- **El hub** guarda esa orden y lo último que contó el agente, en archivos de
  su carpeta de datos —nada de esto está en `projects.yml` ni hace falta
  reconstruirlo (regla dura 1: no va a la base)—.
- **El procesado** (`reuniones procesar`, en WSL) transcribe en la GPU y
  resume. El hub lo lanza cuando el agente dice que terminó una grabación.
- **El Puente KVM** graba una reunión del Mac por el JetKVM, con su botón y en
  su carpeta (`<id>-kvm`, decisión 443). El hub no le pregunta (438): el ciclo
  lento del muestreo mira esa carpeta y lanza el procesado de lo terminado
  (`procesar_pendientes`).

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
import time
from pathlib import Path

from . import config

# `AAAAMMDD-HHMMSS`, y `-kvm` detrás si la grabó el Puente KVM (decisión 443):
# el sufijo evita choques con el agente de Windows en el mismo segundo y dice
# en qué carpeta vive (`carpeta_de`). Va detrás para no cambiar el orden por fecha.
ID = re.compile(r"^\d{8}-\d{6}(?:-kvm)?$")
SUFIJO_PUENTE = "-kvm"
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


def raiz_puente() -> Path:
    """Donde deja el Puente KVM las reuniones del Mac (decisión 443). No se
    crea: la carpeta es del puente y el hub sólo la lee.

    Misma convención que `puente.puerto()`: la variable del puente si está,
    y si no, su sitio de siempre. Sin importar `hub.puente`, que fuera de
    `api.py` nadie lo hace (`tests/test_puertas.py`): esto no le pregunta
    nada al puente, mira una carpeta."""
    return Path(os.environ.get("PUENTE_HOME") or Path.home() / ".local/share/puente-kvm") / "reuniones"


def raices() -> list[Path]:
    """Las carpetas donde hay reuniones: la del agente siempre; la del puente,
    sólo con la herramienta encendida y si existe. Apagada, sus reuniones no
    asoman en ningún sitio (438)."""
    from . import opcionales
    out = [raiz()]
    if opcionales.encendida("puente-kvm") and raiz_puente().is_dir():
        out.append(raiz_puente())
    return out


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
        componentes.paso("carpeta", "Dónde va el agente en Windows",
                          bool(carpeta_windows()) or destino.is_dir(),
                          "Una carpeta de Windows para el agente; las grabaciones irán a la de al lado."),
        componentes.paso("agente", "El agente está en esa carpeta", (destino / "agente.py").exists(),
                          "«Copiar el agente» lo deja ahí, con el puerto de este hub."),
        componentes.paso("instalado", "El agente está instalado en Windows", llamo,
                          "Doble clic en instalar.cmd dentro de esa carpeta. Necesita uv para Windows."),
        componentes.paso("llave", "Tiene su llave", hay_llave(), "«Generar la llave», aquí abajo."),
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
    if datos.get("abiertas"):
        _confirmar_abiertas(datos["abiertas"])
    datos = {k: datos.get(k) for k in ("agente", "equipo", "grabando", "monitores", "microfonos", "apps")}
    previo = _leer(carpeta() / "latido.json") or {}
    for k in ("monitores", "microfonos", "apps"):       # el inventario no llega en cada latido
        if datos.get(k) is None:
            datos[k] = previo.get(k)
    datos["t"] = time.time()
    _escribir(carpeta() / "latido.json", datos)
    g = datos.get("grabando") if isinstance(datos.get("grabando"), dict) else {}
    if g.get("monitor_origen") == "ventana" and isinstance(g.get("monitor"), int):
        _recordar_monitor(g["monitor"])
    return {"orden": orden(), "miniaturas": _consumir("pedir-miniaturas"), "abrir": _por_abrir()}


# ── abrir una pantalla del hub en la PC (decisión 313) ────────────────────────
# El agente ya llama cada segundo y vive en la sesión de Windows: él la abre en
# su navegador. (La 313 decía que WSL no podía lanzar programas de Windows; el
# 7-nov se midió que sí, y leer la PC va directo, decisión 386; lo que cambia
# algo en ella sigue por aquí.) Sólo
# rutas del propio hub —«/trabajo?slot=3»—, nunca una URL de fuera: el agente
# las pega a SU dirección del hub, así que aunque alguien escribiera aquí, no
# podría mandarlo a otra web.
RUTA_DEL_HUB = re.compile(r"^/(?!/)[\w\-./?=&%#:+~@!,;]*$")


def pedir_abrir(ruta: str) -> str:
    """Encola una pantalla para que el agente la abra. Devuelve su id."""
    if not RUTA_DEL_HUB.match(ruta or "") or "\\" in ruta:
        raise ValueError(f"sólo se abren pantallas del hub («/trabajo», «/reuniones/…»), no «{ruta}»")
    import uuid
    pedidos = _leer(carpeta() / "abrir.json") or []
    pid = uuid.uuid4().hex[:12]
    pedidos.append({"id": pid, "ruta": ruta, "t": time.time()})
    _escribir(carpeta() / "abrir.json", pedidos[-10:])
    return pid


def _por_abrir() -> list[dict]:
    """Lo pendiente, una vez: lo que lleva más de un minuto ya no es lo que se pidió."""
    f = carpeta() / "abrir.json"
    pedidos = _leer(f) or []
    if not pedidos:
        return []
    f.unlink(missing_ok=True)
    return [{"id": p["id"], "ruta": p["ruta"]} for p in pedidos if time.time() - p.get("t", 0) < 60]


def _confirmar_abiertas(ids) -> None:
    hechas = set(_leer(carpeta() / "abiertas.json") or [])
    hechas |= {str(i) for i in ids if isinstance(i, str)}
    _escribir(carpeta() / "abiertas.json", sorted(hechas)[-50:])


def abierta(pid: str) -> bool:
    return pid in set(_leer(carpeta() / "abiertas.json") or [])


def terminada(id_: str) -> None:
    if ID.match(id_ or ""):
        try:
            lanzar_procesado(id_)
        except ValueError as e:  # su carpeta no se ve desde aquí: queda el botón «Procesar», y el latido no cae
            with open(carpeta() / "procesado.log", "a") as log:
                log.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {id_}: no se lanza su procesado: {e}\n")


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


# ── si el agente de Windows está al día (C-0379) ──────────────────────────────
# Tras actualizar el hub no había forma de saber si tocaba «Copiar el agente».
# Hay tres versiones: la que dice el agente en cada latido (la que CORRE), la
# que trae el componente y la que quedó copiada en su carpeta de Windows. Se
# leen del texto de `agente.py`, sin importarlo: es código de Windows.
_VERSION = re.compile(r"""^VERSION\s*=\s*["']([^"'\n]{1,32})["']""", re.M)


def _version_en(archivo: Path) -> str | None:
    try:
        m = _VERSION.search(archivo.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return None
    return m.group(1) if m else None


def _tupla(version: str | None) -> tuple[int, ...] | None:
    try:
        return tuple(int(p) for p in str(version).split("."))
    except ValueError:
        return None


def version_agente(latido: dict | None = None) -> dict:
    """`estado`: «al-dia», «vieja» (hay una más nueva sin copiar), «copiada»
    (copiada, pero el que llama sigue con la de antes) o None.

    🔴 None cuando no se puede comparar (regla dura 13): un agente que no dice
    su versión, un componente que no se encuentra o un agente MÁS nuevo que el
    del hub —quien desarrolla el agente—, al que «Copiar» bajaría de versión."""
    corre = (latido if latido is not None else agente()).get("agente") or None
    hay = _version_en(proyecto() / "agente" / "agente.py")
    copiada = _version_en(carpeta_agente() / "agente.py")
    a, b = _tupla(corre), _tupla(hay)
    estado = None
    if a is not None and b is not None:
        if a == b:
            estado = "al-dia"
        elif a < b:
            estado = "copiada" if _tupla(copiada) == b else "vieja"
    return {"estado": estado, "corre": corre, "hay": hay, "copiada": copiada}


# Desde la 0.3.0 el agente graba el monitor donde está la ventana de la app
# (C-0456). La pantalla sólo lo ofrece y sólo lo afirma si el agente que corre
# lo sabe hacer: a uno anterior se le manda la orden y la ignora (regla dura 13).
AGENTE_SIGUE_VENTANA = (0, 3, 0)


def sigue_ventana(latido: dict | None = None) -> bool:
    corre = _tupla((latido if latido is not None else agente()).get("agente") or "")
    return corre is not None and corre >= AGENTE_SIGUE_VENTANA


def _recordar_monitor(n: int) -> None:
    """Dónde vio el agente la ventana de la llamada por última vez."""
    f = carpeta() / "monitor-visto.json"
    if (_leer(f) or {}).get("monitor") != n:
        _escribir(f, {"monitor": n, "t": time.time()})


def _reserva(monitores: set[str]) -> str:
    """El monitor que se graba si el agente no encuentra la ventana: donde la
    vio la última vez; si no, el de la orden anterior; si no, el 1.

    Lo decide `grabar` y no quien llama (C-0456): copiar la orden anterior en
    cada sitio es lo que dejó semanas grabando una pantalla sin la reunión."""
    for n in ((_leer(carpeta() / "monitor-visto.json") or {}).get("monitor"), orden().get("monitor")):
        if n is not None and str(n) in monitores:
            return str(n)
    return min(monitores, key=lambda x: int(x) if x.isdigit() else 99)


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


def grabar(monitor: str, app: str, micro: str, titulo: str = "", seguir_app: bool = False) -> dict:
    """La orden de grabar, validada contra lo que el agente dijo que ve: el
    formulario sólo puede elegir entre eso.

    Con `seguir_app` el agente graba el monitor donde esté la ventana de la
    app (C-0456); `monitor` puede ir vacío y entonces se pone la reserva, que
    es lo que graba si no la encuentra."""
    a = agente()
    if not a["vivo"]:
        raise ValueError("el agente de Windows no está conectado")
    if orden().get("grabar"):
        raise ValueError("ya se está grabando")
    mons = {str(m["n"]) for m in a.get("monitores") or []}
    apps = {x["nombre"]: x for x in a.get("apps") or []}
    mics = {str(m["n"]) for m in a.get("microfonos") or []}
    if seguir_app and not app:
        raise ValueError("para grabar donde esté la ventana, elige la aplicación de la llamada")
    if seguir_app and monitor not in mons and mons:
        monitor = _reserva(mons)
    if monitor not in mons:
        raise ValueError("elige un monitor")
    if app and app not in apps:
        raise ValueError("esa aplicación ya no tiene audio abierto; refresca la lista")
    if micro and micro not in mics:
        raise ValueError("ese micrófono no existe")
    o = {"grabar": True, "id": time.strftime("%Y%m%d-%H%M%S"), "monitor": int(monitor),
         "app": app or None, "pid": apps[app]["pid"] if app else None, "micro": micro or None,
         "titulo": titulo.strip()[:120], "seguir_app": bool(seguir_app), "desde": time.time()}
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


def _lanzar(*args: str, raiz: Path, ids: tuple[str, ...] = (), estado: str | None = None) -> None:
    """Una orden de `reuniones`, en segundo plano y con su salida al log.

    `raiz` es la carpeta de las reuniones de esa orden (`REUNIONES_RAIZ`): la
    del agente o la del puente, según el id (decisión 443). Obligatoria, para
    que nadie lance una del puente contra la carpeta del agente.

    Fuera del cgroup de quien lo lanza (decisión 344) —`hub-web`, o
    `hub-snapshotter` las del puente—: al reiniciar la web, el resumen de una
    reunión murió a medias (C-0148). Y se apunta qué se lanzó y su huella,
    para que un «procesando» cuyo proceso ya no existe no se quede así para
    siempre (`_cortado`). El pid es el de `uv`, no el de Python: mueren juntos.
    `estado` es el archivo de estado que escribe la orden: `voces` y `nombres`
    pasan por `procesar` y escriben su «procesando» (revisor de C-0148).
    """
    from . import procesos, tmux
    with open(carpeta() / "procesado.log", "a") as log:
        proceso = procesos.desasir(["uv", "run", "--quiet", "--project", str(proyecto()), "reuniones", *args],
                                   cwd=proyecto(), salida=log,
                                   env={**os.environ, "PATH": tmux.path_de_usuario(), "REUNIONES_RAIZ": str(raiz)})
    huella = procesos.huella(proceso.pid)
    if huella:
        for id_ in ids:
            _escribir(_lanzados(crear=True) / f"{id_}-{estado or args[0]}.json", {**huella, "desde": time.time()})


# Lo lanzado por el hub, en su carpeta y no en la de la grabación: ésa la
# escribe el proyecto reuniones, y el hub no escribe en lo de otro (regla 16).
def _lanzados(crear: bool = False) -> Path:
    d = carpeta() / "lanzados"
    if crear:
        d.mkdir(exist_ok=True)
    return d


# Cuánto puede tardar `uv run` en arrancar y que `reuniones procesar` escriba
# su «procesando». Un inicio más tardío que esto no es de este lanzamiento:
# lo empezó otro (a mano, en una terminal) y no se da por cortado.
_ARRANQUE_S = 300


def _cortado(id_: str, orden: str, desde: float | None, tope: float | None = _ARRANQUE_S) -> bool:
    """Si lo que el hub lanzó para esta reunión ya no corre.

    Sin registro no se sabe —lo lanzó otro— y se deja como esté. `desde` es
    cuándo empezó lo que dice estar en marcha: el registro tiene que ser de
    ese mismo arranque, y no puede ser anterior a él. `tope=None` quita el
    límite por arriba: una compresión de varias marca cada reunión al llegar
    a ella, quizá mucho después de lanzarse.
    """
    from . import procesos
    h = _leer(_lanzados() / f"{id_}-{orden}.json")
    if not h or desde is None:
        return False
    inicio = h.get("desde", 0)
    if desde < inicio - 5 or (tope is not None and desde > inicio + tope):
        return False
    return not procesos.vivo(h)


#: Lo que no deja comprimir: el proyecto reuniones lee «procesando» en ambos.
SIN_TERMINAR = ("procesando", "se cortó")


def _estado_procesado(id_: str, p: dict) -> str | None:
    if p.get("estado") == "procesando" and _cortado(id_, "procesar", p.get("inicio")):
        return "se cortó"
    return p.get("estado")


def procesando() -> list[str]:
    """Las reuniones que se están procesando ahora: las que tienen un modelo
    de Whisper cargado en la GPU (C-0312). El banco de dictado no mide con
    otro a la vez, ni `procesar_pendientes` lanza otra. Un «procesando» cuyo
    proceso ya murió no cuenta («se cortó»); uno que lanzó otro a mano sí,
    porque de ése no se sabe. De todas las carpetas: la GPU es una."""
    return [d.name for d in sorted(_todas(), key=lambda x: x.name)
            if _estado_procesado(d.name, _leer(d / "procesado.json") or {}) == "procesando"]


def _en_su_raiz(r: Path) -> list[Path]:
    """Las carpetas de reunión de una raíz. Cada id vive donde dice su sufijo
    (`carpeta_de`): una `-kvm` en la del agente, o al revés, no se enseña,
    porque luego no se podría abrir."""
    if not r.is_dir():
        return []
    del_puente = r == raiz_puente()
    return [x for x in r.iterdir() if ID.match(x.name) and x.name.endswith(SUFIJO_PUENTE) == del_puente]


def _todas() -> list[Path]:
    return [d for r in raices() for d in _en_su_raiz(r)]


def _procesar_en_marcha() -> bool:
    """Un `procesar` (o `voces`, `nombres`, que pasan por él) que el hub lanzó
    y sigue vivo, aunque aún no haya escrito su «procesando»: `uv run` tarda
    en arrancar, y en ese hueco `procesando()` no lo ve."""
    from . import procesos
    return any(procesos.vivo(_leer(f)) for f in _lanzados().glob("*-procesar.json"))


def procesar_pendientes() -> str | None:
    """Lanza el procesado de UNA reunión del Puente KVM terminada y sin
    procesar —la más antigua— y devuelve su id; si no, None (decisión 443).

    Lo llama el ciclo lento del muestreo: el hub no le pregunta al puente
    (438), mira su carpeta. Las del agente de Windows no pasan por aquí: ésas
    las lanza su latido al terminar (`terminada`). `fin` en `meta.json` es lo
    último que escribe el puente; sin él, se está grabando y no se toca. Una
    por vuelta y nunca con otro procesado en marcha: Whisper en la GPU, de uno
    en uno. Lo lanzado una vez no se relanza solo (su `lanzados/<id>-procesar.json`):
    si falló, lo dice su página y se reintenta con el botón.

    Barato a propósito (regla dura 14): listar una carpeta local y leer
    `meta.json`; lo de las demás reuniones, que está en el disco de Windows,
    sólo se mira si hay candidata."""
    r = raiz_puente()
    if r not in raices():
        return None
    for d in sorted(_en_su_raiz(r), key=lambda x: x.name):
        if not _espera_procesado(d):
            continue
        if procesando() or _procesar_en_marcha():
            return None
        lanzar_procesado(d.name)
        return d.name
    return None


def _espera_procesado(d: Path) -> bool:
    """Una del puente terminada que nadie ha procesado ni lanzado: la que
    `procesar_pendientes` lanzará sola en una de sus vueltas."""
    return (d.name.endswith(SUFIJO_PUENTE) and not (d / "procesado.json").exists()
            and not (_lanzados() / f"{d.name}-procesar.json").exists()
            and bool((_leer(d / "meta.json") or {}).get("fin")))


def _comprimiendo(d: Path) -> bool:
    marca = d / "comprimiendo"
    if not marca.exists():
        return False
    try:
        desde = marca.stat().st_mtime
    except OSError:
        return False
    return not _cortado(d.name, "comprimir", desde, tope=None)


def _libre(id_: str) -> Path:
    """La carpeta de la reunión, si no tiene un procesado a medias."""
    d = carpeta_de(id_)
    estado = _estado_procesado(id_, _leer(d / "procesado.json") or {})
    if estado == "procesando":
        raise ValueError("se está procesando: espera a que termine")
    if estado == "se cortó":
        raise ValueError("el procesado se cortó a medias: reinténtalo primero")
    return d


def lanzar_procesado(id_: str) -> None:
    d = carpeta_de(id_)
    _lanzar("procesar", id_, raiz=d.parent, ids=(id_,))


def lanzar_voces(id_: str) -> None:
    """Separar las voces de una ya procesada, y rehacer su resumen con ellas."""
    d = _libre(id_)
    _lanzar("voces", id_, "--resumen", raiz=d.parent, ids=(id_,), estado="procesar")


# Lo que se acepta como nombre: corto y de una línea. Va como argumento a un
# proceso (lista, sin shell) y acaba en un .md que lee Claude.
_NOMBRE = re.compile(r"^[\w .'’-]{0,60}$")


def lanzar_nombres(id_: str, nombres: dict[str, str], resumen: bool) -> None:
    """Pone nombre a las voces. Lo guarda `reuniones nombres`, que es quien
    conoce su carpeta: el hub no escribe en lo de otro proyecto."""
    d = _libre(id_)
    pares = []
    for clave, valor in nombres.items():
        valor = " ".join(str(valor).split())
        if not re.match(r"^Persona \d{1,3}$", clave) or not _NOMBRE.match(valor):
            raise ValueError(f"nombre no válido para {clave}: usa letras, espacios o guiones")
        pares.append(f"{clave}={valor}")
    _lanzar("nombres", id_, *pares, *(["--resumen"] if resumen else []), raiz=d.parent, ids=(id_,),
            estado="procesar")


#: Lo que ocupa cada subcarpeta de una reunión terminada (`fotos/`), con la
#: fecha de la carpeta cuando se midió: `{ruta: (st_mtime_ns, bytes)}`.
_SUBCARPETAS: dict[str, tuple[int, int]] = {}


def _tamano(d: Path, terminada: bool = False) -> int:
    """Lo que ocupa la carpeta de una reunión, en bytes (C-0276).

    `/reuniones` tardaba 6,6–7,9 s y casi todo era esto: `rglob` + `is_file` +
    `stat` por archivo sobre el disco de Windows (9p), 6,8 s para 19
    grabaciones y ~1 000 archivos, en cada carga y cada 5 s mientras se graba.
    `os.scandir` no pide dos veces cada archivo (0,94 s medido sobre lo mismo).

    Y las fotos de una reunión terminada no cambian —el agente deja de
    escribirlas al parar—: su subcarpeta se recuerda por su fecha, que cambia
    si se añade o se quita una. Lo de arriba (el audio, que se comprime, y los
    `.json` del procesado) se mide siempre. Mientras se graba, todo entero.
    """
    return _sumar(str(d), recordar=terminada)


def _sumar(ruta: str, recordar: bool = False) -> int:
    total = 0
    try:
        with os.scandir(ruta) as it:
            entradas = list(it)
    except OSError:
        return 0
    for e in entradas:
        # Un archivo que desaparece entre listar y medir (se está comprimiendo)
        # no puede tumbar la pantalla: lo que ya no está no ocupa.
        try:
            if e.is_dir(follow_symlinks=False):
                total += _subcarpeta(e) if recordar else _sumar(e.path)
            elif e.is_file():
                total += e.stat().st_size
        except OSError:
            continue
    return total


def _subcarpeta(e: os.DirEntry) -> int:
    fecha = e.stat(follow_symlinks=False).st_mtime_ns
    visto = _SUBCARPETAS.get(e.path)
    if visto and visto[0] == fecha:
        return visto[1]
    total = _sumar(e.path)
    _SUBCARPETAS[e.path] = (fecha, total)
    return total


def _comprimida(d: Path) -> bool:
    return not any((d / f"{p}.wav").exists() for p in ("reunion", "micro"))


def lanzar_compresion(ids: list[str]) -> None:
    """Comprimir el audio (WAV → Opus) es borrar el original: sólo cuando el
    dueño lo pide, nunca solo. Lo hace `reuniones comprimir`, que comprueba la
    duración antes de borrar nada."""
    carpetas = {}
    for i in ids:
        try:
            carpetas[i] = carpeta_de(i)
        except ValueError:
            continue
    # Una cortada tampoco: su procesado.json sigue diciendo «procesando», y
    # `reuniones comprimir` se negaría. Primero se reintenta.
    if any(_estado_procesado(i, _leer(d / "procesado.json") or {}) in SIN_TERMINAR for i, d in carpetas.items()):
        raise ValueError("se está procesando: comprime cuando termine")
    if not carpetas:
        raise ValueError("nada que comprimir")
    # Una orden por carpeta: `reuniones comprimir` las busca en su
    # `REUNIONES_RAIZ`, y las del puente viven en otra (decisión 443).
    por_raiz: dict[Path, list[str]] = {}
    for i, d in carpetas.items():
        por_raiz.setdefault(d.parent, []).append(i)
    for r, grupo in por_raiz.items():
        _lanzar("comprimir", *grupo, raiz=r, ids=tuple(grupo))


def sin_comprimir() -> list[str]:
    """Las terminadas que aún tienen WAV y no se están comprimiendo."""
    return [x["id"] for x in lista(500) if x["terminada"] and not x["comprimida"] and not x["comprimiendo"]
            and x["estado"] not in SIN_TERMINAR]


def carpeta_de(id_: str) -> Path:
    """La carpeta de una reunión: la única forma de ir de un id a sus archivos.

    El id dice de quién es (decisión 443): `-kvm`, del Puente KVM, y sólo con
    la herramienta encendida —apagada, sus reuniones no existen para el hub
    (438)—; el resto, del agente de Windows."""
    if not ID.match(id_ or ""):
        raise ValueError("reunión no válida")
    if id_.endswith(SUFIJO_PUENTE):
        from . import opcionales
        if not opcionales.encendida("puente-kvm"):
            raise ValueError("esa reunión no existe")
        d = raiz_puente() / id_
    else:
        d = raiz() / id_
    if not d.is_dir():
        raise ValueError("esa reunión no existe")
    return d


def lista(n: int = 50) -> list[dict]:
    """Las de todas las carpetas juntas, de la más nueva a la más vieja: el id
    empieza por la fecha, y el sufijo del puente va detrás."""
    out = []
    for d in sorted(_todas(), key=lambda x: x.name, reverse=True)[:n]:
        meta = _leer(d / "meta.json") or {}
        p = _leer(d / "procesado.json") or {}
        res = _leer(d / "resumen.json") or {}
        dur = int(meta["fin"] - meta["inicio"]) if meta.get("fin") is not None and meta.get("inicio") is not None else None
        out.append({"id": d.name, "titulo": res.get("titulo") or meta.get("titulo") or "",
                    "app": (meta.get("proceso") or {}).get("nombre"), "duracion": dur,
                    "estado": _estado_procesado(d.name, p) or ("grabando" if not meta.get("fin") else "sin procesar"),
                    "tareas": len(res.get("tareas") or []), "terminada": bool(meta.get("fin")),
                    "tamano": _tamano(d, terminada=bool(meta.get("fin"))), "comprimida": _comprimida(d),
                    "comprimiendo": _comprimiendo(d),
                    "error_compresion": (_leer(d / "comprimido.json") or {}).get("error")})
    return out


def detalle(id_: str) -> dict:
    d = carpeta_de(id_)
    procesado = _leer(d / "procesado.json") or {}
    if procesado:
        procesado = {**procesado, "estado": _estado_procesado(id_, procesado)}
    meta = _leer(d / "meta.json") or {}
    return {"id": id_, "carpeta": str(d), "guia_voces": f"{proyecto()}/README.md",
            "meta": meta, "procesado": procesado, "se_procesa_sola": _espera_procesado(d),
            "tamano": _tamano(d, terminada=bool(meta.get("fin"))), "comprimida": _comprimida(d),
            "comprimiendo": _comprimiendo(d),
            "compresion": _leer(d / "comprimido.json"),
            "resumen": _leer(d / "resumen.json"), "transcripcion": _leer(d / "transcripcion.json") or [],
            "nombres": _leer(d / "nombres.json") or {},
            "fotos": sorted(int(f.stem) for f in (d / "fotos").glob("*.jpg") if f.stem.isdigit())
            if (d / "fotos").is_dir() else []}


def foto(id_: str, segundo: int) -> Path:
    p = carpeta_de(id_) / "fotos" / f"{int(segundo):06d}.jpg"
    if not p.is_file():
        raise ValueError("esa foto no existe")
    return p
