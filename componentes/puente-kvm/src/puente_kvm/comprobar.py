"""`puente-kvm comprobar` y `puente-kvm diagnostico`: qué falta, y un informe para mandar.

`comprobar` dice en claro qué falta para que el puente funcione en este
equipo y cómo arreglarlo, de lo más básico (uv, tmux, Claude Code) al aparato
(si responde y con qué firmware). Sale con 1 si falta algo imprescindible.

`diagnostico` escribe un informe para mandárselo a quien mantiene el puente
cuando algo falla. **No lleva secretos ni contenido del trabajo**: ni la
contraseña (sólo si está puesta), ni lo tecleado, ni nombres de objetos o de
cambios, ni rutas de la carpeta personal (salen como `~`). Lleva versiones,
firmware, estados, tiempos y los últimos errores de la bitácora con lo que
iba entre comillas tapado.
"""

from __future__ import annotations

import asyncio
import json
import os
import platform
import re
import shutil
import socket
import stat
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from . import config

BIEN, OJO, FALTA = "bien", "ojo", "falta"
MARCA = {BIEN: "✔", OJO: "!", FALTA: "✘"}

from .jetkvm import FIRMWARE_CONTRASTADO  # noqa: E402  (uno solo: el del cliente)


@dataclass
class Punto:
    estado: str
    que: str
    detalle: str
    arreglo: str = ""

    def linea(self) -> str:
        s = f"{MARCA[self.estado]} {self.que}: {self.detalle}"
        return s + (f"\n    → {self.arreglo}" if self.arreglo else "")


def _orden(*args: str, timeout: float = 10) -> str | None:
    """La primera línea de lo que dice una orden, o None si no se puede ejecutar."""
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None
    salida = (r.stdout or r.stderr).strip()
    return salida.splitlines()[0] if r.returncode == 0 and salida else None


def _ruta_usuario() -> str:
    from .terminal import _path_de_usuario

    return _path_de_usuario()


def _programas() -> list[Punto]:
    puntos = []
    v = sys.version_info
    puntos.append(Punto(BIEN if v >= (3, 12) else FALTA, "Python", f"{v.major}.{v.minor}.{v.micro}",
                        "" if v >= (3, 12) else "hace falta 3.12 o más: `uv python install 3.12`"))
    ruta = _ruta_usuario()
    for nombre, version, arreglo, imprescindible in (
        ("uv", ["--version"], "instálalo: https://docs.astral.sh/uv/ (`curl -LsSf https://astral.sh/uv/install.sh | sh`)", True),
        ("tmux", ["-V"], "`sudo apt install tmux` (en macOS, `brew install tmux`)", True),
        ("curl", ["--version"], "`sudo apt install curl`: lo usan los hooks para contar al puente qué hace Claude", False),
    ):
        donde = shutil.which(nombre, path=ruta)
        if not donde:
            puntos.append(Punto(FALTA if imprescindible else OJO, nombre, "no está en el PATH", arreglo))
            continue
        version_corta = (_orden(donde, *version) or "responde").split(" (")[0]
        puntos.append(Punto(BIEN, nombre, f"{version_corta} ({_casa(donde)})"))
    from . import simulador
    from .terminal import terminal_se_puede_abrir

    se_puede, como = terminal_se_puede_abrir()
    puntos.append(Punto(BIEN, "terminal web", como) if se_puede else
                  Punto(FALTA, "terminal web", "este Python no abre la terminal en una sesión propia y no está `setsid`",
                        "`sudo apt install util-linux`"))
    if simulador.FUENTE_MONO:
        puntos.append(Punto(BIEN, "fuentes del simulador", _casa(simulador.FUENTE_MONO)))
    else:
        puntos.append(Punto(OJO, "fuentes del simulador", "falta la monoespaciada: el Mac simulado se verá con otra",
                            simulador.ARREGLO_FUENTES))
    if hay_systemd():
        puntos.append(Punto(BIEN, "systemd de usuario", f"disponible: `{orden_arrancar()}`"))
    else:
        puntos.append(Punto(OJO, "systemd de usuario", "no está (WSL sin systemd, macOS…)",
                            f"arranca el puente a mano con `{orden_arrancar()}` (ver INSTALAR.md)"))
    return puntos


def hay_systemd() -> bool:
    return bool(shutil.which("systemctl")) and _orden("systemctl", "--user", "show-environment") is not None


def otro_repositorio(ruta: Path) -> Path | None:
    """El repositorio git que contiene a `ruta` desde fuera (no el suyo propio), si lo hay.

    El código copiado en `<otro-repo>/componentes/puente-kvm` está dentro de
    otro repositorio: lo que se deje ahí (lo leído del Mac) acaba en su clon.
    """
    arriba = _orden("git", "-C", str(Path(ruta).resolve().parent), "rev-parse", "--show-toplevel")
    return Path(arriba) if arriba else None


def orden_arrancar() -> str:
    """La orden que hay que sugerir en ESTE equipo: con systemd o sin él, y con el
    espacio de trabajo fuera si el código vive dentro de otro repositorio."""
    orden = "bash scripts/servicio.sh instalar" if hay_systemd() else "bash scripts/arrancar.sh"
    if not os.environ.get("PUENTE_TRABAJO") and otro_repositorio(config.CODIGO):
        orden = f'PUENTE_TRABAJO="$HOME/puente-trabajo" {orden}'
    return orden


def punto_modelo(modelo: str, version_claude: str | None) -> Punto:
    """Fable 5.2 pide Claude Code 2.1.322 o posterior (medido): si no, se dice qué elegir."""
    texto = config.texto_modelo(modelo) if modelo else "el de tu Claude Code"
    m = re.search(r"(\d+)\.(\d+)\.(\d+)", version_claude or "")
    if modelo == "claude-fable-5-2" and m and tuple(map(int, m.groups())) < config.CLAUDE_CODE_PARA_FABLE:
        minima = ".".join(map(str, config.CLAUDE_CODE_PARA_FABLE))
        return Punto(OJO, "modelo de Claude", f"Fable 5.2 necesita Claude Code {minima} o posterior, y aquí hay "
                     f"{m.group(0)}", "actualiza Claude Code (`claude update`) o elige Opus 5.5 en "
                     "Ajustes → Modelo de Claude")
    return Punto(BIEN, "modelo de Claude", f"{texto} (Ajustes → Modelo de Claude)")


# Carpetas donde suele haber un `claude` además de las del PATH del puente.
SISTEMA = ("/usr/local/bin", "/usr/bin", "/bin", "/snap/bin")


def todos_los_claude() -> list[tuple[str, str | None]]:
    """Cada `claude` distinto del equipo (por su destino real), con su versión."""
    from . import terminal

    vistos: dict[str, tuple[str, str | None]] = {}
    for carpeta in dict.fromkeys([*_ruta_usuario().split(":"), *SISTEMA]):
        r = Path(carpeta) / "claude" if carpeta else None
        if r and r.is_file() and os.access(r, os.X_OK):
            vistos.setdefault(str(r.resolve()), (str(r), terminal.version_de(str(r))))
    return list(vistos.values())


def _claude(estado: dict | None, modelo: str) -> list[Punto]:
    """El `claude` que abre el puente —el del servicio en marcha, con SU PATH, o el que
    resolvería la terminal desde aquí—, no el primero del PATH de esta shell."""
    from . import terminal

    if estado and estado.get("claude_code"):
        cc, origen = estado["claude_code"], "el que abre el puente en marcha"
    else:
        cc, origen = terminal.claude_code(), "el que abriría el puente desde esta shell"
    if not cc.get("ruta"):
        return [Punto(FALTA, "claude", "el puente no encuentra Claude Code en sus carpetas",
                      "instala Claude Code y entra con tu cuenta: https://docs.claude.com/claude-code")]
    puntos = [Punto(BIEN, "claude", f"{cc.get('version') or 'versión desconocida'} ({_casa(cc['ruta'])}), {origen}")]
    todos = todos_los_claude()
    if len({v for _, v in todos}) > 1:
        lista = "; ".join(f"{_casa(r)} {v or '?'}" for r, v in todos)
        puntos.append(Punto(OJO, "varios Claude Code", f"hay {len(todos)} con versiones distintas ({lista}); "
                            f"el puente usa {_casa(cc['ruta'])}",
                            "quita o actualiza los que no uses, para que no gane uno viejo si cambia el PATH"))
    puntos.append(punto_modelo(modelo, cc.get("version")))
    return puntos


def _casa(ruta: str | Path) -> str:
    """Una ruta con la carpeta personal como `~`: el nombre de usuario no viaja."""
    s, casa = str(ruta), str(Path.home())
    return "~" + s[len(casa):] if casa != "/" and (s == casa or s.startswith(casa + "/")) else s


def _leer_entorno(ruta: Path) -> dict[str, str]:
    datos = {}
    for linea in ruta.read_text().splitlines():
        m = re.match(r"\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)=(.*)$", linea)
        if m:
            datos[m.group(1)] = m.group(2).strip().strip("'\"")
    return datos


def _clave(ajustes: dict) -> list[Punto]:
    """El archivo de la contraseña: si existe, sus permisos, y si la variable tiene valor. Nunca el valor."""
    nombre = ajustes["dispositivo"].get("clave_env") or "JETKVM_CLAVE"
    ruta = config.entorno()
    puntos = []
    en_archivo = False
    if not ruta.exists():
        puntos.append(Punto(OJO if ajustes["dispositivo"]["tipo"] == "simulador" else FALTA,
                            "archivo de la contraseña", f"{_casa(ruta)} no existe",
                            f"créalo con permisos 600 y pon dentro `{nombre}=…` (lo escribe la persona, "
                            "no Claude): `install -D -m 600 /dev/null " + _casa(ruta) + "`"))
    else:
        modo = stat.S_IMODE(ruta.stat().st_mode)
        if modo & 0o077:
            puntos.append(Punto(FALTA, "archivo de la contraseña", f"{_casa(ruta)} tiene permisos {modo:o}: "
                                "otros usuarios del equipo pueden leerlo", f"`chmod 600 {_casa(ruta)}`"))
        else:
            puntos.append(Punto(BIEN, "archivo de la contraseña", f"{_casa(ruta)} (permisos {modo:o})"))
        try:
            en_archivo = bool(_leer_entorno(ruta).get(nombre))
        except OSError as e:
            puntos.append(Punto(FALTA, "archivo de la contraseña", f"no se puede leer: {e.strerror}"))
    en_proceso = bool(os.environ.get(nombre))
    puesta = en_archivo or en_proceso
    if ajustes["dispositivo"]["tipo"] == "jetkvm":
        puntos.append(Punto(BIEN if puesta else FALTA, "contraseña del JetKVM",
                            f"{nombre} tiene valor" if puesta else f"{nombre} está vacía",
                            "" if puesta else f"añade `{nombre}=…` a {_casa(ruta)} y reinicia el puente "
                            "(si el JetKVM no tiene contraseña, déjala vacía y no pasa nada)"))
    return puntos


def _preguntar_al_puente(timeout: float = 2) -> dict | None:
    """El estado del puente si está en marcha en su puerto; None si ahí no hay nadie."""
    import httpx

    try:
        r = httpx.get(f"http://127.0.0.1:{config.PUERTO}/api/estado", timeout=timeout,
                      headers={"Host": f"127.0.0.1:{config.PUERTO}"})
        return r.json() if r.status_code == 200 and "control" in r.text else {"ajeno": r.status_code}
    except Exception:
        pass
    with socket.socket() as s:
        s.settimeout(0.5)
        return {"ajeno": "ocupado"} if s.connect_ex(("127.0.0.1", config.PUERTO)) == 0 else None


def _servicio(estado: dict | None) -> list[Punto]:
    if estado is None:
        return [Punto(OJO, "el puente", f"no está en marcha en 127.0.0.1:{config.PUERTO} (el puerto está libre)",
                      f"arráncalo, desde la carpeta del código: `{orden_arrancar()}`")]
    if "ajeno" in estado:
        return [Punto(FALTA, "puerto", f"127.0.0.1:{config.PUERTO} lo ocupa otro programa",
                      f"ciérralo (`ss -ltnp | grep {config.PUERTO}`) o usa otro puerto con PUENTE_PUERTO")]
    puntos = [Punto(BIEN, "el puente", f"en marcha en http://127.0.0.1:{config.PUERTO} (versión {estado.get('version')})")]
    if estado.get("version") != config.VERSION:
        puntos.append(Punto(OJO, "versión", f"corre la {estado.get('version')} y el código es la {config.VERSION}",
                            "reinicia el puente para usar el código nuevo"))
    return puntos


async def _sondear_jetkvm(url: str, clave: str, entrar: bool) -> tuple[list[Punto], str]:
    """Pregunta al JetKVM sin abrir sesión de vídeo: si responde, y su firmware.

    `/device/status` es público. El firmware llega en el primer mensaje de la
    señalización, antes de ofrecer nada; como no se manda oferta, no se le quita
    la sesión a nadie. Pero ENTRAR con la contraseña cierra la web del JetKVM
    si estaba abierta en un navegador (guarda un solo token).
    """
    import aiohttp

    url = url.rstrip("/")
    url = url if url.startswith(("http://", "https://")) else "http://" + url
    puntos = []
    timeout = aiohttp.ClientTimeout(total=8)
    async with aiohttp.ClientSession(cookie_jar=aiohttp.CookieJar(unsafe=True), timeout=timeout) as http:
        try:
            async with http.get(f"{url}/device/status") as r:
                datos = await r.json(content_type=None) if r.status == 200 else {}
                puntos.append(Punto(BIEN if r.status == 200 else OJO, "JetKVM", f"responde en {url} ({r.status})"
                                    + (", sin configurar todavía" if datos.get("isSetup") is False else "")))
        except Exception as e:
            puntos.append(Punto(FALTA, "JetKVM", f"no responde en {url}: {type(e).__name__}",
                                "¿está encendido y en la misma red? Prueba su dirección en un navegador "
                                "y ponla en Ajustes (http://, sin barra final)"))
            return puntos, ""
        if not entrar:
            return puntos, ""
        async with http.get(f"{url}/device") as r:
            pide = r.status == 401
        if pide:
            if not clave:
                puntos.append(Punto(FALTA, "JetKVM", "pide contraseña y no está puesta"))
                return puntos, ""
            async with http.post(f"{url}/auth/login-local", json={"password": clave}) as r:
                if r.status != 200:
                    puntos.append(Punto(FALTA, "JetKVM", f"rechaza la contraseña ({r.status})",
                                        "revisa el valor en el archivo de la contraseña"))
                    return puntos, ""
        ws_url = url.replace("http", "ws", 1) + "/webrtc/signaling/client"
        try:
            async with http.ws_connect(ws_url) as ws:
                m = await asyncio.wait_for(ws.receive(), 5)
                firmware = (json.loads(m.data).get("data") or {}).get("deviceVersion", "")
        except Exception as e:
            puntos.append(Punto(FALTA, "JetKVM", f"la señalización no abre: {type(e).__name__}: {e}"))
            return puntos, ""
    puntos.append(punto_firmware(firmware))
    return puntos, firmware


def punto_firmware(firmware: str) -> Punto:
    if not firmware:
        return Punto(OJO, "firmware", "el JetKVM no dijo su versión")
    if firmware in FIRMWARE_CONTRASTADO:
        return Punto(BIEN, "firmware", f"{firmware} (contrastado con su código)")
    return Punto(OJO, "firmware", f"{firmware}: fuera de lo contrastado ({', '.join(FIRMWARE_CONTRASTADO)})",
                 "puede funcionar; si algo falla, compáralo con docs/protocolo-jetkvm.md")


def _aparato(ajustes: dict, estado: dict | None, entrar: bool) -> list[Punto]:
    d = ajustes["dispositivo"]
    if d["tipo"] == "simulador":
        return [Punto(BIEN, "aparato", "el Mac simulado (para el JetKVM: Ajustes → Tipo «JetKVM»)")]
    if estado and "control" in estado:
        disp = estado.get("dispositivo") or {}
        if disp.get("conectado"):
            return [Punto(BIEN, "JetKVM", f"conectado a {disp.get('url')}, vídeo {disp.get('resolucion')}"),
                    punto_firmware(disp.get("firmware", ""))]
        motivo = estado.get("error_conexion") or disp.get("motivo") or "sin conexión"
        return [Punto(FALTA, "JetKVM", f"el puente no conecta: {motivo}",
                      "mira el aviso del panel; «Reconectar el aparato» en Ajustes lo reintenta")]
    clave = os.environ.get(d.get("clave_env") or "JETKVM_CLAVE", "")
    if not clave and config.entorno().exists():
        clave = _leer_entorno(config.entorno()).get(d.get("clave_env") or "JETKVM_CLAVE", "")
    puntos, _ = asyncio.run(_sondear_jetkvm(d["url"], clave, entrar))
    if not entrar:
        puntos.append(Punto(OJO, "firmware", "sin mirar (--sin-entrar)"))
    return puntos


def _espacio(estado: dict | None = None) -> list[Punto]:
    puntos = []
    try:
        hogar = config.hogar()
        prueba = hogar / ".escribible"
        prueba.write_text("")
        prueba.unlink()
        puntos.append(Punto(BIEN, "datos del puente", _casa(hogar)))
    except OSError as e:
        puntos.append(Punto(FALTA, "datos del puente", f"no se puede escribir en PUENTE_HOME: {e.strerror}"))
    # El que cuenta es el del servicio (su unidad puede llevar otro PUENTE_TRABAJO
    # que esta shell); sólo si no está en marcha, el de esta shell.
    if estado and estado.get("espacio"):
        esp, origen = Path(estado["espacio"]), "el del puente en marcha"
    else:
        esp, origen = config.espacio(), "el de esta shell: el puente no está en marcha"
    medido = (esp / "trabajo" / "entorno.md").exists()
    contenedor = otro_repositorio(esp)
    if contenedor:
        puntos.append(Punto(OJO, "espacio de trabajo de Claude", f"{_casa(esp)} ({origen}) está dentro de otro "
                            f"repositorio git ({_casa(contenedor)}): lo leído del Mac quedaría en su clon, y Claude "
                            "cargaría su CLAUDE.md", 'ponlo fuera: `PUENTE_TRABAJO="$HOME/puente-trabajo"` al '
                            f"instalar (`{orden_arrancar()}`)"))
    else:
        puntos.append(Punto(BIEN, "espacio de trabajo de Claude", f"{_casa(esp)} ({origen})"
                            + (", con trabajo/entorno.md" if medido else "")))
    if not medido:
        puntos.append(Punto(OJO, "entorno del Mac", "sin medir (no hay trabajo/entorno.md)",
                            "sigue docs/pruebas-con-el-aparato.md con el aparato delante"))
    try:
        servidor = json.loads((config.CODIGO / ".mcp.json").read_text())["mcpServers"]["puente-kvm"]
        orden = shutil.which(servidor["command"], path=_ruta_usuario())
        puntos.append(Punto(BIEN if orden else FALTA, "herramientas de Claude (.mcp.json)",
                            f"{servidor['command']} " + ("encontrado" if orden else "no está en el PATH")))
    except (OSError, KeyError, json.JSONDecodeError) as e:
        puntos.append(Punto(FALTA, "herramientas de Claude (.mcp.json)", f"no se puede leer: {e}"))
    return puntos


def puntos(entrar: bool = True) -> list[Punto]:
    ajustes = config.leer_ajustes()
    todos = _programas()
    estado = _preguntar_al_puente()
    en_marcha = estado if estado and "control" in estado else None
    todos += _claude(en_marcha, ajustes.get("claude", {}).get("modelo", config.MODELO_POR_OMISION))
    todos += _clave(ajustes)
    todos += _servicio(estado)
    todos += _aparato(ajustes, estado, entrar)
    todos += _espacio(en_marcha)
    return todos


def comprobar(args: list[str]) -> int:
    entrar = "--sin-entrar" not in args
    if entrar:
        print("(Si el puente no está en marcha y el aparato es un JetKVM, se entra en él para leer su firmware:\n"
              " eso cierra su web si la tienes abierta en un navegador. Para no entrar: --sin-entrar.)\n")
    lista = puntos(entrar)
    for p in lista:
        print(p.linea())
    faltan = [p for p in lista if p.estado == FALTA]
    print("\n" + (f"Faltan {len(faltan)} cosas: arréglalas en ese orden y vuelve a comprobar."
                  if faltan else "Nada imprescindible falta."))
    return 1 if faltan else 0


# ── diagnóstico ─────────────────────────────────────────────────────────────
# Tipos de la bitácora que no llevan contenido del trabajo en sí mismos.
_TIPOS_DIAGNOSTICO = {"error", "aviso", "conexion", "corte", "control", "comprobacion", "ajustes", "terminal"}
_ID = re.compile(r"\b[a-z0-9]+(?:-[a-z0-9]+)*-[0-9a-f]{6}\b")


def tapar(texto: str) -> str:
    """Lo que va entre comillas o es un identificador con nombre, fuera."""
    texto = re.sub(r"«[^»]*»", "«…»", texto)
    texto = re.sub(r"'[^']*'", "'…'", texto)
    texto = re.sub(r'"[^"]*"', '"…"', texto)
    texto = _ID.sub("<id>", texto)
    return _casa_en_texto(texto)


def _casa_en_texto(texto: str) -> str:
    casa = str(Path.home())
    return texto.replace(casa, "~") if casa != "/" else texto


def _bitacora(cuantas: int = 40) -> tuple[dict[str, int], list[str], list[str]]:
    ruta = config.hogar() / "bitacora.jsonl"
    if not ruta.exists():
        return {}, [], []
    entradas = []
    for linea in ruta.read_text().splitlines()[-5000:]:
        try:
            entradas.append(json.loads(linea))
        except json.JSONDecodeError:
            continue
    por_tipo: dict[str, int] = {}
    for e in entradas:
        por_tipo[e.get("tipo", "?")] = por_tipo.get(e.get("tipo", "?"), 0) + 1
    hora = lambda e: time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(e.get("t", 0)))  # noqa: E731
    ultimas = [f"{hora(e)} {e.get('quien', '?')} · {e.get('tipo')} · {tapar(str(e.get('detalle', '')))}"
               for e in entradas if e.get("tipo") in _TIPOS_DIAGNOSTICO][-cuantas:]
    # Cuánto tardó cada captura: del «empiezo» a «N páginas» de la misma lectura.
    inicio: dict[str, float] = {}
    tiempos = []
    for e in entradas:
        if e.get("tipo") != "lectura" or not e.get("lectura"):
            continue
        if str(e.get("detalle", "")).startswith("empiezo"):
            inicio[e["lectura"]] = e["t"]
        elif e["lectura"] in inicio:
            m = re.search(r"(\d+) páginas", str(e.get("detalle", "")))
            if m:
                dur = e["t"] - inicio.pop(e["lectura"])
                tiempos.append(f"{m.group(1)} páginas en {dur:.1f} s ({dur / max(1, int(m.group(1))):.2f} s/página)")
    return por_tipo, ultimas, tiempos[-10:]


def _paquetes() -> str:
    from importlib.metadata import PackageNotFoundError, version

    salida = []
    for p in ("aiortc", "av", "aiohttp", "fastapi", "mcp", "pillow"):
        try:
            salida.append(f"{p} {version(p)}")
        except PackageNotFoundError:
            salida.append(f"{p} ?")
    return ", ".join(salida)


def _sistema() -> str:
    s = f"{platform.system()} {platform.release()} ({platform.machine()})"
    try:
        if "microsoft" in Path("/proc/version").read_text().lower():
            s += ", WSL"
    except OSError:
        pass
    return s


def informe() -> str:
    from . import cambios, conversaciones, lecturas

    ajustes = config.leer_ajustes()
    commit = _orden("git", "-C", str(config.CODIGO), "rev-parse", "--short", "HEAD") or "?"
    cambiado = _orden("git", "-C", str(config.CODIGO), "status", "--porcelain")
    lineas = [
        "# Diagnóstico del puente KVM",
        "",
        "Sin secretos ni contenido del trabajo: ni la contraseña, ni lo tecleado, ni nombres de",
        "objetos o de cambios. Lo que iba entre comillas en la bitácora sale como «…».",
        "",
        f"- Fecha: {time.strftime('%Y-%m-%d %H:%M:%S %z')}",
        f"- Puente: {config.VERSION} (commit {commit}{', con cambios locales' if cambiado else ''})",
        f"- Sistema: {_sistema()}; Python {platform.python_version()}",
        f"- Paquetes: {_paquetes()}",
        "",
        "## Comprobación",
        "",
    ]
    lineas += [tapar(p.linea()) for p in puntos(entrar=False)]
    d = ajustes["dispositivo"]
    p = ajustes["perfil"]
    lineas += [
        "",
        "## Ajustes",
        "",
        f"- Aparato: {d['tipo']}" + (f", {d['url']}" if d["tipo"] == "jetkvm" else ""),
        f"- Variable de la contraseña: {d.get('clave_env')}",
        f"- Perfil: {p.get('nombre')}; inicio {p.get('inicio_documento')}, fin {p.get('fin_documento')}, "
        f"página {p.get('pagina_abajo')}, ir a línea {p.get('ir_a_linea')}, fin de línea {p.get('fin_de_linea')}",
        f"- Región del editor: {p.get('region_editor')}; ratón aparcado en {p.get('aparcar_raton')}; "
        f"pausa entre teclas {p.get('retardo_tecla_ms')} ms; distribución {p.get('distribucion')}",
    ]
    estado = _preguntar_al_puente()
    if estado and "control" in estado:
        disp = estado.get("dispositivo") or {}
        lineas += [
            "",
            "## El puente en marcha",
            "",
            f"- Versión: {estado.get('version')}",
            f"- Control: {estado['control'].get('modo')} ({tapar(str(estado['control'].get('motivo', '')))})",
            f"- Tarea: {'sí' if estado.get('tarea') else 'ninguna'}",
            f"- Aparato: {disp.get('tipo')}, conectado={disp.get('conectado')}, resolución={disp.get('resolucion')}, "
            f"firmware={disp.get('firmware', '—')}, último fotograma hace {disp.get('ultimo_fotograma_s', '—')} s",
            f"- Motivo: {tapar(str(disp.get('motivo') or '—'))}",
            f"- Error de conexión: {tapar(estado.get('error_conexion') or '—')}",
        ]
    ls = lecturas.todas()
    cs = cambios.todos()
    estados_l: dict[str, int] = {}
    for l in ls:
        clave = "verificada" if l.verificada else l.estado
        estados_l[clave] = estados_l.get(clave, 0) + 1
    estados_c: dict[str, int] = {}
    for c in cs:
        estados_c[c.estado] = estados_c.get(c.estado, 0) + 1
    inestables = sum(sum(pg.inestable for pg in l.paginas) for l in ls)
    por_tipo, ultimas, tiempos = _bitacora()
    lineas += [
        "",
        "## Lecturas y cambios (sólo cuántos)",
        "",
        f"- Lecturas: {len(ls)} {estados_l or ''}; páginas capturadas moviéndose: {inestables}",
        f"- Páginas por lectura: {[len(l.paginas) for l in ls[:10]]}",
        f"- Cambios: {len(cs)} {estados_c or ''}",
        # Sus nombres pueden ser del trabajo: sólo cuántas.
        f"- Conversaciones con Claude: {len(conversaciones.todas())}",
        f"- Capturas: {'; '.join(tiempos) or '—'}",
        "",
        "## Bitácora",
        "",
        f"- Entradas por tipo: {por_tipo or '—'}",
        "",
        "Últimas (errores, avisos, conexión, control, comprobaciones):",
        "",
        *[f"    {u}" for u in ultimas],
        "",
    ]
    return "\n".join(lineas)


def diagnostico(args: list[str]) -> int:
    texto = informe()
    destino = config.hogar() / f"diagnostico-{time.strftime('%Y%m%d-%H%M%S')}.md"
    destino.write_text(texto)
    print(texto)
    print(f"\nGuardado en {_casa(destino)}: mándaselo a quien mantiene el puente.")
    return 0
