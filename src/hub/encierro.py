"""Ejecutar lo que escribe un agente sin que vea la máquina (decisión 350, C-0145).

🔴 **Lo que escribe un agente guiado por terceros corre encerrado, o no corre.**
`./encargo servir` arrancaba la app del implementador con todo el entorno, el
HOME entero y la red del host: podía leer `~/.ssh` o `~/.secretos` y hablarle
al hub en 127.0.0.1:8787, que da una shell.

Aquí no hay docker (sin integración con WSL), ni bwrap, ni podman, y no se
instala nada. Lo que sí hay son user namespaces sin privilegios (`unshare -U`).
Con ellos:

- **Raíz por lista blanca**, montada en un tmpfs y con `pivot_root`: sólo
  `/usr`, `/bin`, `/lib*`, `/sbin` y `/etc` en sólo lectura, y lo que se pida
  (`leer` en sólo lectura, `escribir` con `nosuid,nodev,noexec`). Tapar con
  tmpfs lo peligroso (lista negra) no sirve: dentro del namespace se es root
  sobre los montajes y un `umount` lo destapa; además en WSL se escapaban
  `/run/WSL` y el binfmt de `/init`, que ejecuta en Windows.
- **Su propio namespace de procesos**: sin él, `/proc/<pid>/root` de cualquier
  proceso del dueño lleva al sistema de archivos de fuera.
- **Sin red**: un namespace de red propio con `lo` apagado. La app escucha en un
  socket Unix que **abre fuera quien lanza** y se le pasa como descriptor
  (`uvicorn --fd`): el archivo del socket no está dentro, así que la app no
  puede cambiarlo por un enlace al de tmux o al bus de systemd.
- **Sin capacidades** tras montar (`setpriv --no-new-privs --bounding-set=-all`)
  y con un entorno mínimo, no el de quien lanza.

Se lanza por `procesos.desasir` (344). `unshare --kill-child` hace que, al
morir él, muera todo lo de dentro; ignora SIGTERM, así que se para con SIGKILL
(`parar`), y sólo si `procesos.vivo` confirma que es el mismo proceso.

Si la máquina no puede encerrar, `lanzar` se niega con el porqué
(`NoDisponible`); nunca cae a correr sin aislar. `tests/test_puertas.py`
vigila que `unshare` no aparezca fuera de aquí.
"""

from __future__ import annotations

import http.client
import os
import signal
import socket
import stat
import subprocess
from pathlib import Path

from . import procesos

UNSHARE = ["unshare", "-Urmnpf", "--kill-child", "--propagation", "private"]

# Lo que se ve dentro. Sólo lectura, y nada de /home, /run, /mnt, /var ni /tmp.
SISTEMA = ("/usr", "/bin", "/lib", "/lib64", "/lib32", "/libx32", "/sbin", "/etc")

# Recibe la raíz vacía, la lista de `leer` y la de `escribir` (separadas por
# «:»), y después la orden. Va en `sh` porque se ejecuta antes de tener nada:
# ni Python ni el venv están montados todavía.
GUION = r"""
set -euf
R="$1"; shift
if [ "$ENC_LO" = 1 ]; then ip link set lo up; fi
mount -t tmpfs -o size=64m,mode=755 tmpfs "$R"
for d in $ENC_SISTEMA; do
  [ -e "$d" ] || continue
  if [ -L "$d" ]; then ln -s "$(readlink "$d")" "$R$d"
  else mkdir -p "$R$d"; mount --rbind "$d" "$R$d"; fi
done
# `--rbind` porque en un user namespace no se puede montar sin los submontajes
# (están bloqueados), y el `ro` no baja solo: se pone a cada uno.
for m in $(awk -v r="$R" 'index($5, r "/") == 1 {print $5}' /proc/self/mountinfo); do
  mount -o remount,bind,ro "$m"
done
mkdir -p "$R/dev/shm" "$R/proc" "$R/tmp"
for n in null zero random urandom; do touch "$R/dev/$n"; mount --bind "/dev/$n" "$R/dev/$n"; done
mount -t proc proc "$R/proc"
mount -t tmpfs -o size=64m,nosuid,nodev,noexec tmpfs "$R/tmp"
mount -t tmpfs -o size=256m,nosuid,nodev,noexec tmpfs "$R/dev/shm"
IFS=:
for P in $ENC_LEER; do
  mkdir -p "$R$P"; mount --bind "$P" "$R$P"; mount -o remount,bind,ro,nosuid,nodev "$R$P"
done
for P in $ENC_ESCRIBIR; do
  mkdir -p "$R$P"; mount --bind "$P" "$R$P"; mount -o remount,bind,nosuid,nodev,noexec "$R$P"
done
unset IFS
cd "$R"; mkdir .viejo; pivot_root . .viejo; umount -l /.viejo; rmdir /.viejo
mount -o remount,bind,ro /
cd "$ENC_CWD"
exec setpriv --no-new-privs --bounding-set=-all --inh-caps=-all env -i $ENC_ENTORNO "$@"
"""


class NoDisponible(RuntimeError):
    """Esta máquina no puede encerrar: no se lanza nada."""


_puede: bool | None = None


def disponible() -> bool:
    """Si se pueden crear los namespaces. Se prueba ejecutando, una vez."""
    global _puede
    if _puede is None:
        try:
            r = subprocess.run([*UNSHARE, "true"], capture_output=True, timeout=10, check=False)
            _puede = r.returncode == 0
        except (OSError, subprocess.SubprocessError):
            _puede = False
    return _puede


def _sin_enlaces(ruta: Path) -> Path:
    """La ruta tal cual, si ningún tramo es un enlace. `mount --bind` sigue los
    enlaces, y lo que se monta lo prepara a veces el propio agente."""
    ruta = Path(ruta).absolute()
    if any(c in str(ruta) for c in ":*?[") or ruta.resolve() != ruta:
        raise ValueError(f"«{ruta}» pasa por un enlace o lleva «:»: no se monta")
    if not ruta.is_dir():
        raise ValueError(f"«{ruta}» no es una carpeta")
    return ruta


def lanzar(orden: list[str], *, raiz: Path, leer: list[Path], escribir: list[Path] = (),
           cwd: Path, entorno: dict[str, str], descriptores: tuple[int, ...] = (),
           salida=None, loopback: bool = False) -> subprocess.Popen:
    """Lanza `orden` encerrada. `raiz` es una carpeta vacía de quien llama que
    sirve de punto de montaje; `descriptores`, los que hereda (el socket).
    `loopback` levanta `lo` dentro de su red propia: sigue sin salida, pero
    deja que el navegador de `mirar` hable con su puente (`fotografiar`)."""
    if not disponible():
        raise NoDisponible("esta máquina no permite user namespaces (`unshare -U`): "
                           "lo que escribe el agente no se ejecuta sin aislar")
    leer = [_sin_enlaces(p) for p in leer]
    escribir = [_sin_enlaces(p) for p in escribir]
    raiz = _sin_enlaces(raiz)
    for clave, valor in entorno.items():
        if not clave.isidentifier() or any(c.isspace() for c in valor):
            raise ValueError(f"variable «{clave}»: sin espacios (va a `env` palabra a palabra)")
    # El entorno de quien lanza llega a `systemd-run` (necesita el bus) y al
    # guion de montaje, que es nuestro; la orden encerrada arranca con `env -i`.
    env = {
        **os.environ,
        "ENC_SISTEMA": " ".join(SISTEMA),
        "ENC_LO": "1" if loopback else "0",
        "ENC_LEER": ":".join(map(str, leer)),
        "ENC_ESCRIBIR": ":".join(map(str, escribir)),
        "ENC_CWD": str(Path(cwd).absolute()),
        "ENC_ENTORNO": " ".join(f"{k}={v}" for k, v in
                                {"PATH": "/usr/bin:/bin", "HOME": "/tmp", **entorno}.items()),
    }
    return procesos.desasir([*UNSHARE, "sh", "-c", GUION, "encierro", str(raiz), *orden],
                            env=env, salida=salida, heredar=descriptores)


def parar(huella: dict | None) -> bool:
    """Para lo lanzado si sigue siendo ese proceso. `unshare` ignora SIGTERM;
    con SIGKILL, `--kill-child` se lleva todo lo de dentro."""
    if not procesos.vivo(huella):
        return False
    os.kill(int(huella["pid"]), signal.SIGKILL)
    return True


# ── Hablarle a lo encerrado, por su socket ──────────────────────────────────

def escuchar(ruta: Path) -> socket.socket:
    """El socket Unix donde escuchará lo encerrado. Lo abre quien lanza, en una
    carpeta suya: dentro sólo llega el descriptor."""
    ruta = Path(ruta)
    if len(os.fsencode(ruta)) > 107:
        raise ValueError(f"«{ruta}» es demasiado larga para un socket Unix (108 bytes como mucho)")
    try:
        if stat.S_ISSOCK(ruta.lstat().st_mode):
            ruta.unlink()
    except FileNotFoundError:
        pass
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.bind(str(ruta))
    os.chmod(ruta, 0o600)
    s.listen(64)
    return s


def _conectar(ruta: Path, timeout: float) -> socket.socket:
    ruta = Path(ruta)
    if not stat.S_ISSOCK(ruta.lstat().st_mode):
        raise ConnectionError(f"«{ruta}» no es un socket")
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(timeout)
    s.connect(str(ruta))
    return s


class _PorSocket(http.client.HTTPConnection):
    def __init__(self, ruta: Path, timeout: float):
        super().__init__("app", timeout=timeout)
        self._ruta = ruta

    def connect(self):
        self.sock = _conectar(self._ruta, self.timeout)


def peticion(ruta: Path, metodo: str, camino: str, cuerpo: bytes | None = None,
             timeout: float = 15) -> tuple[int, bytes]:
    """Una petición HTTP a lo encerrado. Sin puerto: no hay nada que apuntar a otro sitio."""
    c = _PorSocket(Path(ruta), timeout)
    try:
        c.request(metodo, camino, body=cuerpo, headers={"Content-Type": "application/json"})
        r = c.getresponse()
        return r.status, r.read()
    finally:
        c.close()


# El puente de dentro: el navegador encerrado sólo sabe de URLs, la app sólo de
# su socket. Corre con el python del sistema (sólo librería estándar).
_PUENTE = r"""
import socket, sys, threading
puerto, ruta = int(sys.argv[1]), sys.argv[2]
s = socket.socket(); s.bind(("127.0.0.1", puerto)); s.listen(16)
def tramo(c):
    o = socket.socket(socket.AF_UNIX); o.connect(ruta)
    def copiar(a, b):
        try:
            while d := a.recv(65536): b.sendall(d)
        except OSError: pass
        finally:
            try: b.shutdown(socket.SHUT_WR)
            except OSError: pass
    threading.Thread(target=copiar, args=(o, c), daemon=True).start(); copiar(c, o)
while True:
    c, _ = s.accept(); threading.Thread(target=tramo, args=(c,), daemon=True).start()
"""

_FOTO = ('python3 -c "$1" 8000 "$2" & sleep 0.5; '
         '"$3" --headless --disable-gpu --no-sandbox --window-size="$5" --virtual-time-budget="$6" '
         '--screenshot="$4" "http://127.0.0.1:8000$7"')


def fotografiar(enchufe: Path, camino: str, destino: Path, *, ancho: int, alto: int,
                espera_ms: int = 2500) -> Path:
    """La foto de una página de lo encerrado, con el navegador **también
    encerrado** (C-0145): sin red —el JavaScript de la página no sale a
    internet ni llega a otros servicios de 127.0.0.1— y sin el HOME si el
    navegador se rompe. Dentro, un puente lleva el puerto 8000 de su red
    propia al socket de la app.

    Sólo con un Chromium de Linux: el de Windows no se puede encerrar.
    """
    import shutil
    import tempfile

    from . import mirar

    chrome = mirar.cual_linux()
    if not chrome:
        raise mirar.SinNavegador("hace falta un Chromium de Linux (p.ej. el de Playwright): "
                                 "el de Windows no se puede aislar, y la página la escribió un agente")
    if not camino.startswith("/") or any(c.isspace() for c in camino):
        raise ValueError("la ruta empieza por «/» y no lleva espacios")
    destino = Path(destino)
    raiz = Path(tempfile.mkdtemp(prefix="hub-foto-"))
    try:
        registro = raiz.parent / f"{raiz.name}.log"
        with registro.open("w") as salida:
            p = lanzar(["/bin/sh", "-c", _FOTO, "foto", _PUENTE, str(enchufe), chrome, str(destino),
                        f"{int(ancho)},{int(alto)}", str(int(espera_ms)), camino],
                       raiz=raiz, leer=[Path(chrome).parent, Path(enchufe).parent], escribir=[destino.parent],
                       cwd=Path("/"), entorno={}, salida=salida, loopback=True)
            try:
                p.wait(120)
            except subprocess.TimeoutExpired:
                parar(procesos.huella(p.pid))
        cola = registro.read_text(errors="replace").splitlines()[-5:]
        registro.unlink(missing_ok=True)
    finally:
        shutil.rmtree(raiz, ignore_errors=True)
    if not destino.is_file():
        raise mirar.SinNavegador("el navegador no produjo la captura: " + " · ".join(cola))
    return destino
