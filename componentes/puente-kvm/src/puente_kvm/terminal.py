"""La terminal de Claude Code dentro del puente: una sesión de tmux y un PTY por pestaña.

Claude corre en una sesión de tmux (`puente-claude`) abierta en el espacio de
trabajo (la carpeta del código, o `PUENTE_TRABAJO`; ver `espacio.py`), así que
**la conversación no depende de la pestaña**: cerrar, recargar o reiniciar el
servicio no la corta; la siguiente conexión se vuelve a enganchar. Cada
pestaña es un `tmux attach` en su propio PTY.

Lo aprendido en otra terminal web, aplicado aquí desde el principio:
- **La sesión se crea fuera del cgroup del servicio** (`systemd-run --scope`).
  Si este servicio arrancara el servidor de tmux, reiniciarlo mataría todas
  las sesiones de tmux de la máquina, no sólo la de Claude.
- **Lo que se lanza lleva su entorno en la propia orden** (`env …`): si el
  servidor de tmux ya existía, el panel nuevo hereda el entorno de ESE
  servidor, no el de quien lo pide. Así llegan el PATH del usuario (bajo
  systemd no está `~/.local/bin`), el puerto y las carpetas del puente.
- **La contraseña del JetKVM no entra**: el servicio la tiene en su entorno
  para conectar, y la sesión de Claude lo heredaría entero; con ella dentro,
  bastaría un `echo` para leerla. Se quita con `env -u`, también por si el
  servidor de tmux la tuviera de antes.
- **El PTY es no bloqueante y `os.write` puede escribir a medias**: lo que no
  cabe se encola. Sin eso, un pegado largo llega cortado por varios sitios.
- **Un fallo de tmux se dice**, no se traga: un `except: pass` aquí se ve luego
  como «la rueda no va».

🔴 Esto es una shell. El servicio escucha sólo en 127.0.0.1 y el WebSocket exige
el `Origin` y el `Host` de esta misma web (ver `app.py`).
"""

from __future__ import annotations

import asyncio
import fcntl
import os
import re
import select
import shlex
import shutil
import signal
import struct
import subprocess
import termios
import time
from pathlib import Path

from . import config, conversaciones, espacio

SESION = os.environ.get("PUENTE_SESION_CLAUDE", "puente-claude")
_ENTORNO_SERVICIO = ("INVOCATION_ID", "JOURNAL_STREAM", "NOTIFY_SOCKET", "MANAGERPID",
                     "WATCHDOG_PID", "WATCHDOG_USEC")


def tmux() -> list[str]:
    """La orden base de tmux; con PUENTE_TMUX_SOCKET, un servidor aparte (las pruebas).

    Se busca con el mismo PATH que `claude` (el de la persona delante): un tmux
    de otra versión que el del servidor que ya corre no se puede enganchar a él.
    """
    socket = os.environ.get("PUENTE_TMUX_SOCKET")
    base = shutil.which("tmux", path=_path_de_usuario()) or "tmux"
    return [base, "-L", socket] if socket else [base]


def _path_de_usuario() -> str:
    # 🔴 Las carpetas de la persona van DELANTE de las del sistema. Medido: con
    # ellas al final, bajo systemd ganaba un `/usr/bin/claude` viejo, instalado
    # una vez para todo el equipo y nunca actualizado, sobre el Claude Code que
    # la persona sí mantiene al día en su carpeta; la terminal abría una versión
    # de hace meses, sin los modelos nuevos, y nada lo decía.
    casa = Path.home()
    propias = [str(casa / ".local/bin"), str(casa / ".npm-global/bin"), str(casa / ".claude/local")]
    actual = [p for p in os.environ.get("PATH", "").split(":") if p]
    return ":".join(dict.fromkeys([*propias, *actual, "/usr/local/bin", "/usr/bin", "/bin"]))


def _sin_claves(entorno: dict[str, str]) -> dict[str, str]:
    quitar = config.variables_de_clave() | set(_ENTORNO_SERVICIO)
    return {k: v for k, v in entorno.items() if k not in quitar}


def _con_entorno(orden: list[str]) -> list[str]:
    """`env -u CLAVE … VAR=valor … orden`: lo que la sesión de Claude ve, decidido aquí."""
    variables = {
        "PATH": _path_de_usuario(),
        "PUENTE_CODIGO": str(config.CODIGO),
        "PUENTE_TRABAJO": str(config.espacio()),
        "PUENTE_PUERTO": str(config.PUERTO),
        "PUENTE_HOME": str(config.hogar()),
    }
    quitar = [a for nombre in sorted(config.variables_de_clave()) for a in ("-u", nombre)]
    return ["env", *quitar, *[f"{k}={v}" for k, v in variables.items()], *orden]


AVISO_MODELO = ("Claude Code no arrancó o terminó con un error. Si es por el modelo, "
                "cámbialo en Ajustes → Modelo de Claude y abre una conversación.")


# ── el Claude Code que se usa de verdad ─────────────────────────────────────
def resolver_claude() -> str | None:
    """El `claude` que abrirá el puente: el mismo PATH que la sesión (la persona delante)."""
    return shutil.which("claude", path=_path_de_usuario())


_versiones: dict[tuple[str, int], str | None] = {}


def version_de(ruta: str | None) -> str | None:
    """`X.Y.Z` de `claude --version`; se pregunta una vez por binario (ruta y fecha)."""
    if not ruta:
        return None
    try:
        clave = (ruta, os.stat(ruta).st_mtime_ns)
    except OSError:
        return None
    if clave not in _versiones:
        try:
            r = subprocess.run([ruta, "--version"], capture_output=True, text=True, timeout=20)
            m = re.search(r"\d+\.\d+\.\d+", r.stdout or "")
            _versiones[clave] = m.group(0) if m else None
        except (OSError, subprocess.SubprocessError):
            _versiones[clave] = None
    return _versiones[clave]


def claude_code() -> dict:
    ruta = resolver_claude()
    return {"ruta": ruta, "version": version_de(ruta)}


class ClaudeCodeViejo(RuntimeError):
    """El modelo elegido pide un Claude Code más nuevo que el que se abriría."""


def comprobar_claude(modelo: str) -> dict:
    """Antes de cerrar nada: ¿el `claude` que se abriría puede con este modelo?

    No se arranca a ciegas: con Fable 5.2 y un Claude Code anterior a 2.1.322,
    la terminal se abría con otro modelo (uno viejo) y nada lo decía.
    """
    cc = claude_code()
    if os.environ.get("PUENTE_TERMINAL_ORDEN"):
        return cc
    if not cc["ruta"]:
        raise ClaudeCodeViejo("No encuentro Claude Code (claude) en las carpetas del puente: instálalo y "
                              "comprueba con «puente-kvm comprobar --sin-entrar» cuál vería el puente")
    minima = config.CLAUDE_CODE_PARA_FABLE
    if modelo == "claude-fable-5-2" and cc["version"] and tuple(map(int, cc["version"].split("."))) < minima:
        texto = ".".join(map(str, minima))
        raise ClaudeCodeViejo(
            f"El Claude Code que abriría el puente ({cc['ruta']}, versión {cc['version']}) es anterior a "
            f"{texto} y no tiene Fable 5.2. Actualízalo (claude update, o el que tengas delante en el PATH) "
            "o elige otro modelo en Ajustes → Modelo de Claude. La conversación abierta sigue como estaba.")
    return cc


def orden_claude(conv: conversaciones.Conversacion | None = None, retomar: bool = False) -> str:
    """Lo que corre dentro: Claude Code con su conversación y su modelo y, si se
    cierra, una shell para relanzarlo.

    Retomar es `--resume U … || --session-id U …`, medido con la 2.1.322: si en
    la conversación nunca se escribió, Claude Code no la guardó y `--resume` sale
    con 1 al momento («No conversation found»), así que arranca de nuevo con el
    mismo id; si sí se escribió y algo falla después, `--session-id` de un id ya
    usado también sale con 1 («already in use») y no pisa nada.
    """
    a_medida = os.environ.get("PUENTE_TERMINAL_ORDEN")
    if a_medida:
        return a_medida
    ruta = _path_de_usuario()
    claude = shlex.quote(shutil.which("claude", path=ruta) or "claude")
    # El modo de permisos va explícito: sin él, Claude hereda el que tenga la
    # persona por omisión, y si fuera automático las reglas de «pregúntame» de
    # .claude/settings.json no preguntarían (medido con Claude Code en otra terminal web).
    base = f"{claude} --permission-mode default"
    if conv is None:
        lanzar = base
    else:
        conversaciones.validar_id(conv.id)  # lo único que llega a la orden sin comillas
        modelo = config.validar_modelo(conv.modelo)
        base += f" --model {shlex.quote(modelo)}" if modelo else ""
        nombre = shlex.quote(conversaciones.limpiar_nombre(conv.nombre))
        nueva = f"{base} --session-id {conv.id} -n {nombre}"
        lanzar = f"{base} --resume {conv.id} -n {nombre} || {nueva}" if retomar else nueva
    aviso = shlex.quote(AVISO_MODELO)
    cerrado = shlex.quote("Claude Code se cerró. Escribe claude para volver a abrirlo.")
    # `bash -l` acaba de leer /etc/profile, que en Ubuntu reescribe el PATH: se
    # vuelve a poner el del puente, para que el `uv` de .mcp.json, el `curl` de
    # los hooks y el `claude` que se escriba a mano sean los mismos que elige el
    # puente. Y la shell de después, sin -l, para que no lo vuelva a reescribir.
    return (f"export PATH={shlex.quote(ruta)} ; {lanzar} ; rc=$? ; echo ; "
            f"if [ $rc -ne 0 ] ; then echo {aviso} ; fi ; echo {cerrado} ; exec bash")


def _puede_desasir() -> bool:
    if os.environ.get("PUENTE_TMUX_SOCKET") or not shutil.which("systemd-run"):
        return False
    try:
        r = subprocess.run(["systemd-run", "--user", "--scope", "--quiet", "--collect", "true"],
                           capture_output=True, timeout=10, check=False)
        return r.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def existe() -> bool:
    r = subprocess.run([*tmux(), "has-session", "-t", f"={SESION}"], capture_output=True, timeout=10)
    return r.returncode == 0


def modelo_elegido() -> str:
    """El de Ajustes → Modelo de Claude: se aplica a la siguiente conversación que se abra."""
    try:
        return config.validar_modelo(config.leer_ajustes()["claude"]["modelo"])
    except (KeyError, ValueError):
        return config.MODELO_POR_OMISION


def asegurar_sesion() -> None:
    """Que haya una conversación abierta: la que estaba (retomada) o una nueva."""
    if existe():
        return
    modelo = modelo_elegido()
    cc = comprobar_claude(modelo)
    conv = conversaciones.actual()
    retomar = conv is not None
    if conv is None:
        conv = conversaciones.nueva("", modelo)
    conv.modelo = modelo
    _crear(conv, retomar, cc)


def cerrar() -> None:
    """Cierra la conversación abierta. Claude Code ya la tiene guardada (si se escribió en ella)."""
    if existe():
        subprocess.run([*tmux(), "kill-session", "-t", f"={SESION}"], capture_output=True, timeout=10)


def abrir(conv: conversaciones.Conversacion, retomar: bool) -> None:
    """Cierra la que hubiera y abre ésta: una sola viva a la vez.

    Lo que puede impedir abrirla se mira ANTES de cerrar la abierta: si no, un
    Claude Code viejo dejaría a la persona sin ninguna.
    """
    modelo = modelo_elegido()
    cc = comprobar_claude(modelo)
    cerrar()
    conv.modelo = modelo
    _crear(conv, retomar, cc)


def _crear(conv: conversaciones.Conversacion, retomar: bool, cc: dict) -> None:
    for aviso in espacio.preparar():
        print(f"[terminal] {aviso}", flush=True)
    entorno = _sin_claves(dict(os.environ))
    entorno["PATH"] = _path_de_usuario()
    orden = [*tmux(), "new-session", "-d", "-s", SESION, "-x", "160", "-y", "48", "-c", str(config.espacio()),
             *_con_entorno(["bash", "-lc", orden_claude(conv, retomar)])]
    if _puede_desasir():
        orden = ["systemd-run", "--user", "--scope", "--quiet", "--collect", *orden]
    r = subprocess.run(orden, capture_output=True, text=True, timeout=20, env=entorno)
    if r.returncode != 0 or not existe():
        raise RuntimeError(f"no se pudo abrir la sesión de Claude en tmux: {r.stderr.strip() or r.returncode}")
    # Sin barra de estado: la del puente ya dice todo, y así no se come una fila.
    for opcion in (["mouse", "on"], ["window-size", "latest"], ["status", "off"]):
        # Sin `=` delante del nombre: set-option no lo acepta (a diferencia de
        # has-session y attach), y el fallo se tragaba en silencio.
        r = subprocess.run([*tmux(), "set-option", "-t", SESION, *opcion], capture_output=True, text=True,
                           timeout=10)
        if r.returncode != 0:
            print(f"[terminal] tmux no aceptó {' '.join(opcion)}: {r.stderr.strip()}", flush=True)
    conversaciones.marcar_abierta(conv.id, conv.modelo, cc.get("version") or "")


def reiniciar(nombre: str = "") -> conversaciones.Conversacion:
    """Una conversación nueva (la abierta se cierra, y queda en la lista para retomarla)."""
    comprobar_claude(modelo_elegido())  # antes de apuntarla en la lista
    conv = conversaciones.nueva(nombre, modelo_elegido())
    abrir(conv, retomar=False)
    return conv


def _tamano(fd: int, filas: int, columnas: int) -> None:
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", filas, columnas, 0, 0))


def lanzar_con_terminal(orden: list[str], entorno: dict, ruta: str) -> int:
    """Lanza ``orden`` en una sesión propia con el PTY ``ruta`` como terminal de
    control, sin ``fork`` (ver ``Adjunto``), y devuelve su PID.

    🔴 El Python que descarga uv no trae ``setsid`` en ``posix_spawn``
    (``NotImplementedError``; medido en Ubuntu 22.04, y en cualquier equipo
    donde uv no use el Python del sistema). Ahí se pasa por ``setsid --ctty``
    de util-linux: el hijo no lidera su grupo, así que ``setsid`` no se bifurca
    y el PID sigue siendo el del proceso que queda."""
    acciones = [(os.POSIX_SPAWN_OPEN, 0, ruta, os.O_RDWR, 0),
                (os.POSIX_SPAWN_DUP2, 0, 1), (os.POSIX_SPAWN_DUP2, 0, 2)]
    programa = shutil.which(orden[0], path=entorno.get("PATH")) or orden[0]
    try:
        return os.posix_spawn(programa, [programa, *orden[1:]], entorno, setsid=True, file_actions=acciones)
    except NotImplementedError:
        pass
    envoltorio = shutil.which("setsid", path=entorno.get("PATH"))
    if not envoltorio:
        raise RuntimeError("este Python no sabe abrir la terminal en una sesión propia y no está "
                           "`setsid` (util-linux): `sudo apt install util-linux`")
    return os.posix_spawn(envoltorio, [envoltorio, "--ctty", programa, *orden[1:]], entorno,
                          file_actions=acciones)


def terminal_se_puede_abrir() -> tuple[bool, str]:
    """Para ``comprobar``: si la terminal web podrá abrirse en este equipo, y cómo."""
    try:
        pid = os.posix_spawn("/bin/true", ["/bin/true"], dict(os.environ), setsid=True)
        os.waitpid(pid, 0)
        return True, "sesión propia con posix_spawn"
    except NotImplementedError:
        pass
    except OSError:
        pass
    if shutil.which("setsid"):
        return True, "sesión propia con `setsid --ctty` (este Python no trae setsid en posix_spawn)"
    return False, ""


class Adjunto:
    """Un `tmux attach` vivo en su PTY, con escritura que no pierde bytes."""

    def __init__(self, filas: int = 40, columnas: int = 120):
        # 🔴 `posix_spawn`, no `pty.fork()`: con el JetKVM conectado este proceso
        # tiene hilos (vídeo, WebRTC), y un fork así puede dejar al hijo colgado
        # en un cerrojo que otro hilo tenía tomado. Medido: la suite se colgaba al
        # abrir la terminal después de la prueba del JetKVM. El hijo abre el
        # esclavo DESPUÉS de `setsid`, y así ese PTY pasa a ser su terminal de
        # control: sin eso tmux no recibiría SIGWINCH al cambiar el tamaño.
        self.fd, esclavo = os.openpty()
        _tamano(self.fd, filas, columnas)
        ruta = os.ttyname(esclavo)
        orden = [*tmux(), "attach", "-t", f"={SESION}"]
        entorno = _sin_claves(dict(os.environ))
        entorno["TERM"] = "xterm-256color"
        try:
            self.pid = lanzar_con_terminal(orden, entorno, ruta)
        finally:
            os.close(esclavo)
        os.set_blocking(self.fd, False)
        self._pendiente = bytearray()
        self._esperando = False
        # 🔴 Lo tecleado antes de que tmux ponga su terminal en crudo se pierde:
        # al hacerlo descarta lo pendiente. Con `setsid --ctty` (el Python de uv,
        # 22.04) tmux tarda un exec más y el primer «echo» desaparecía.
        self._listo = False
        self._tope_listo = time.monotonic() + 3
        self._reintento = False

    def leer(self) -> bytes:
        try:
            return os.read(self.fd, 65536)
        except BlockingIOError:
            return b""
        except OSError:
            raise EOFError from None

    def escribir(self, datos: bytes) -> None:
        self._pendiente += datos
        self._vaciar()

    def _en_crudo(self) -> bool:
        try:
            return not termios.tcgetattr(self.fd)[3] & termios.ICANON
        except (OSError, termios.error):
            return True

    def _esperar_a_tmux(self) -> bool:
        """Si ya se puede escribir; si no, deja programado otro intento."""
        if self._listo or self._en_crudo() or time.monotonic() > self._tope_listo:
            self._listo = True
            return True
        try:
            bucle = asyncio.get_running_loop()
        except RuntimeError:
            while not (self._en_crudo() or time.monotonic() > self._tope_listo):
                select.select([], [], [], 0.02)
            self._listo = True
            return True
        if not self._reintento:
            self._reintento = True

            def otra_vez() -> None:
                self._reintento = False
                self._vaciar()

            bucle.call_later(0.02, otra_vez)
        return False

    def _vaciar(self) -> None:
        if self._pendiente and not self._esperar_a_tmux():
            return
        while self._pendiente:
            try:
                n = os.write(self.fd, self._pendiente)
            except BlockingIOError:
                n = 0
            except OSError:
                self._pendiente.clear()
                break
            if n:
                del self._pendiente[:n]
                continue
            try:
                bucle = asyncio.get_running_loop()
            except RuntimeError:
                if not select.select([], [self.fd], [], 2.0)[1]:
                    break
                continue
            if not self._esperando:
                bucle.add_writer(self.fd, self._vaciar)
                self._esperando = True
            return
        if self._esperando:
            self._esperando = False
            try:
                asyncio.get_running_loop().remove_writer(self.fd)
            except (RuntimeError, OSError, ValueError):
                pass

    def redimensionar(self, filas: int, columnas: int) -> None:
        try:
            _tamano(self.fd, max(5, min(filas, 300)), max(20, min(columnas, 500)))
        except OSError:
            pass

    def cerrar(self) -> None:
        self._pendiente.clear()  # un reintento que llegue tarde no escribe en un fd cerrado
        try:
            asyncio.get_running_loop().remove_reader(self.fd)
        except (RuntimeError, OSError, ValueError):
            pass
        if self._esperando:
            try:
                asyncio.get_running_loop().remove_writer(self.fd)
            except (RuntimeError, OSError, ValueError):
                pass
        try:
            os.close(self.fd)
        except OSError:
            pass
        try:
            os.kill(self.pid, signal.SIGHUP)  # sólo el cliente: la sesión de Claude sigue
        except OSError:
            return
        for _ in range(20):
            try:
                if os.waitpid(self.pid, os.WNOHANG)[0]:
                    return
            except ChildProcessError:
                return
            select.select([], [], [], 0.05)
        try:
            os.kill(self.pid, signal.SIGKILL)
            os.waitpid(self.pid, 0)
        except (OSError, ChildProcessError):
            pass
