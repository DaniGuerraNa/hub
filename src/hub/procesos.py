"""Lanzar algo que siga corriendo cuando el servicio que lo lanzó se reinicia.

🔴 **El cgroup, no la sesión** (decisión 344, que generaliza la 153). Los
servicios del hub corren bajo systemd con `KillMode=control-group`: al parar o
reiniciar uno, systemd mata todo lo que cuelga de su cgroup. `start_new_session`
cambia la sesión del proceso, no su cgroup, así que un hijo lanzado así muere
igual. Pasó el 2026-11-03: reiniciar `hub-web` mató a medias el resumen de una
reunión y se quedó en «procesando» para siempre (C-0148).

`desasir` lo lanza dentro de un *scope* propio (`systemd-run --scope`), que hace
`exec` del comando: el pid que devuelve es el del comando, y se conservan el
directorio, el entorno y la salida que se le den. Sin systemd se lanza como
antes: quedarse sin el proceso por no poder aislarlo cambiaría un riesgo por
una avería.

`huella` y `vivo` sirven a quien guarda el pid para saber después si lo que
lanzó sigue en marcha, sin confundirlo con otro proceso que herede el número.

Es la única puerta: `tests/test_puertas.py` vigila que `systemd-run` y
`start_new_session` no aparezcan fuera de aquí.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

# Un cgroup propio y transitorio. `--collect` lo recoge solo cuando ya no queda
# nada dentro.
PREFIJO_SCOPE = ["systemd-run", "--user", "--scope", "--quiet", "--collect"]

# Lo que systemd le pone al proceso del servicio y no debe heredar lo lanzado:
# con `NOTIFY_SOCKET`, un hijo podría hablarle a systemd en nombre de `hub-web`.
_DEL_SERVICIO = ("INVOCATION_ID", "JOURNAL_STREAM", "NOTIFY_SOCKET", "MANAGERPID", "WATCHDOG_PID",
                 "WATCHDOG_USEC")

# Se prueba una vez por proceso: preguntar en cada llamada costaría un
# subproceso de más en el camino más caliente del hub (tmux).
_puede: bool | None = None


def puede_desasir() -> bool:
    """Si esta máquina puede darle a un proceso un cgroup propio.

    Se comprueba ejecutando de verdad, no mirando si el binario existe: en un
    contenedor `systemd-run` está instalado y falla igual por no haber bus.
    """
    global _puede
    if _puede is None:
        _puede = False
        if shutil.which("systemd-run") and os.environ.get("DBUS_SESSION_BUS_ADDRESS"):
            try:
                sonda = subprocess.run([*PREFIJO_SCOPE, "true"], capture_output=True, timeout=10, check=False)
                _puede = sonda.returncode == 0
            except (OSError, subprocess.SubprocessError):
                _puede = False
    return _puede


def _abrir(orden: list[str], cwd, env, salida, heredar=()) -> subprocess.Popen:
    return subprocess.Popen(orden, cwd=cwd, env=env, start_new_session=True, stdin=subprocess.DEVNULL,
                            pass_fds=tuple(heredar),
                            stdout=salida if salida is not None else subprocess.DEVNULL,
                            stderr=subprocess.STDOUT if salida is not None else subprocess.DEVNULL)


def desasir(orden: list[str], *, cwd: str | Path | None = None, env: dict | None = None,
            salida=None, heredar: tuple[int, ...] = ()) -> subprocess.Popen:
    """Lanza `orden` fuera del cgroup de quien llama y vuelve en el acto.

    `salida` es un archivo abierto donde van stdout y stderr juntos; sin ella,
    a ninguna parte. La sonda de `puede_desasir` ya probó que el scope se
    monta; si aun así `systemd-run` fallara, el proceso devuelto termina en el
    acto con código distinto de 0, y quien necesite saberlo lo mira con
    `poll()` (como `actualizacion.lanzar`). `heredar` son los descriptores
    que se le pasan abiertos (el socket de lo encerrado, `encierro`). No se reintenta a pelo: con
    `--scope` no se distingue el código de systemd-run del de la orden, y
    repetir una orden que sí corrió sería ejecutarla dos veces.
    """
    entorno = {k: v for k, v in (os.environ if env is None else env).items() if k not in _DEL_SERVICIO}
    return _abrir([*PREFIJO_SCOPE, *orden] if puede_desasir() else orden, cwd, entorno, salida, heredar)


def huella(pid: int) -> dict | None:
    """El pid y su instante de arranque (campo 22 de /proc/pid/stat).

    El arranque distingue a este proceso de otro que reciba el mismo número
    cuando el primero ya murió.
    """
    campos = _stat(pid)
    return {"pid": int(pid), "arranque": campos[19]} if campos else None


def vivo(h: dict | None) -> bool:
    """Si el proceso de la huella sigue en marcha.

    Un zombi cuenta como muerto: un `Popen` que nadie espera sigue en /proc
    con su mismo arranque hasta que Python lo recoge.
    """
    if not h or not h.get("pid"):
        return False
    campos = _stat(h["pid"])
    return bool(campos) and campos[19] == h.get("arranque") and campos[0] not in ("Z", "X")


# Lo que puede llevar una shell interactiva en su línea de órdenes y seguir
# siendo sólo eso. Con cualquier otra cosa —un guion, `-c "…"`— está
# ejecutando algo, aunque tmux la llame `bash`.
_OPCIONES_DE_SHELL = frozenset({"-l", "-i", "-il", "-li", "--login", "--norc", "--noprofile",
                                "--noediting", "--posix"})


def shell_en_reposo(pid: int, shells: frozenset[str] | set[str]) -> bool:
    """Si `pid` es una shell interactiva sin nada en marcha (C-0352, revisión
    cruzada).

    `pane_current_command` dice `bash` con `bash x.sh` o con un comando
    compuesto, y con eso las «shells sin usar» se inflaban (regla 13). Dos
    señales de /proc, baratas y sin `pgrep`: su línea de órdenes es la de una
    shell a secas (su nombre, con el `-` de login, y opciones de
    `_OPCIONES_DE_SHELL`) y no tiene ningún hijo (`/proc/pid/task/*/children`:
    ni en primer plano ni en segundo, ni un trabajo parado). Lo que no se puede
    leer cuenta como no en reposo: mejor quedarse corto que cerrar algo vivo.
    """
    try:
        argv = [a.decode(errors="replace")
                for a in Path(f"/proc/{int(pid)}/cmdline").read_bytes().split(b"\0") if a]
        hilos = list(Path(f"/proc/{int(pid)}/task").iterdir())
        if any((h / "children").read_text().strip() for h in hilos):
            return False
    except (OSError, ValueError):
        return False
    if not argv or not hilos:
        return False
    return (Path(argv[0]).name.lstrip("-") in shells
            and all(a in _OPCIONES_DE_SHELL for a in argv[1:]))


def _stat(pid: int) -> list[str] | None:
    """Los campos de /proc/pid/stat a partir del estado (campo 3).

    El nombre (campo 2) va entre paréntesis y puede llevar espacios, así que se
    corta por el último «)».
    """
    try:
        texto = Path(f"/proc/{int(pid)}/stat").read_text()
    except (OSError, ValueError):
        return None
    return texto.rsplit(")", 1)[1].split()
