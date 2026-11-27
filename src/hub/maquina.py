"""La salud de la máquina que se queda sola.

Sale de una necesidad con fecha: *«un módulo con valores de la pc, temperatura
entre otras y poder configurar alertas o cosas así por si acaso aumenta la
temperatura de más, porque estará sola la pc como 1 mes»*. Estando a 2 000 km,
lo que mata a un equipo encendido sin nadie delante es corto y conocido: el
disco que se llena, el calor, y un apagón del que nadie se entera.

🔴 **Sólo se mide lo que existe sin una sesión de Windows abierta.** Es la
condición que manda aquí, porque el plan del viaje es justo que el equipo
arranque **sin que nadie inicie sesión**: una cifra que existe únicamente
mientras hay alguien dentro sería la que más veces faltaría el mes que importa.
Por eso entra `nvidia-smi` —un ejecutable del driver— y no entra la temperatura
de CPU, que en Windows pide un driver en el núcleo y una aplicación de
escritorio que arranca al iniciar sesión. No se enseña un hueco vacío ni un
número inventado: sencillamente no está, y la pantalla dice por qué.

🔴 **Una medida que no se pudo tomar NO se escribe.** Se conserva la anterior
con su fecha, que es lo que hace `repos` con el respaldo y por el mismo motivo:
un cero que en realidad significa «no he mirado» es la peor cifra posible, y
aquí además dispararía una alarma falsa a un teléfono que está de viaje.

Lo caro va en el ciclo lento (regla dura 14): esto lanza `nvidia-smi` y un
`powershell`, así que se mide cada diez minutos y la pantalla dice **cuándo** se
midió en lugar de dar el dato como si fuera de ahora mismo.
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from . import config
from .reloj import ahora


class MaquinaNoMedida(Exception):
    """No se pudo medir nada de nada. Como con docker: se conserva lo anterior."""


# Cuánto se espera a un proceso de fuera. `powershell.exe` tarda ~0,4 s y
# `nvidia-smi` ~0,3 s medidos aquí; diez segundos es margen de sobra para una
# máquina cargada y poco para un ciclo que se repite.
ESPERA = 10

# Las rutas que se miran. La primera es el disco virtual de WSL —donde vive el
# hub y su base— y la segunda el disco de Windows, que es el que se llena solo.
DISCOS = (("disco.wsl", "/"), ("disco.windows", "/mnt/c"))


@dataclass(frozen=True)
class Medida:
    """Una magnitud con su unidad. `valor` a None = es texto, no un número."""

    clave: str
    valor: float | None = None
    texto: str = ""
    unidad: str = ""


# 🔴 Dónde están, por si el PATH no los trae. Es la decisión 81 otra vez y en
# otro sitio: `hub-snapshotter` corre bajo systemd, cuyo PATH **no incluye los
# caminos de interoperabilidad de Windows**, así que `nvidia-smi.exe` y
# `powershell.exe` no existen ahí aunque una shell interactiva los encuentre sin
# esfuerzo. Se vio en la primera medición dentro del servicio: discos y memoria
# al día y la GPU, el SAI y Windows congelados diez minutos atrás, sin un solo
# error a la vista. Probar a mano no lo detecta nunca.
RESPALDOS = {
    "nvidia-smi.exe": "/mnt/c/Windows/System32/nvidia-smi.exe",
    "powershell.exe": "/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe",
    # Los del diagnóstico de la red (`diagnostico.red`, decisión 386), que el
    # secretario lanza desde su servicio.
    "tracert.exe": "/mnt/c/Windows/System32/tracert.exe",
    "ping.exe": "/mnt/c/Windows/System32/ping.exe",
    # El de Linux, para quien pregunta si hay GPU desde WSL (Reuniones,
    # C-0119): WSL lo pone en su carpeta de librerías, no en /usr/bin.
    "nvidia-smi": "/usr/lib/wsl/lib/nvidia-smi",
    # El de la red privada, que va en Windows y no en WSL (decisión 159).
    "tailscale.exe": "/mnt/c/Program Files/Tailscale/tailscale.exe",
}


def _programa(nombre: str) -> str:
    """El ejecutable, con su ruta absoluta si el PATH no lo trae."""
    return shutil.which(nombre) or RESPALDOS.get(nombre, nombre)


def encontrar(nombre: str, *, de_usuario: bool = False) -> str | None:
    """Dónde está un programa aunque el PATH del servicio no lo traiga, o None.

    La puerta para preguntar «¿hay X?» desde un servicio de systemd: con
    `shutil.which` a secas la respuesta depende de quién arrancó el proceso.
    `de_usuario` mira además donde instala la persona lo suyo (`~/.local/bin`
    y compañía, `tmux.path_de_usuario`, decisión 81): `claude` vive ahí, y
    bajo systemd «no está» sería falso (C-0468)."""
    if de_usuario:
        from . import tmux
        propio = shutil.which(nombre, path=tmux.path_de_usuario())
        if propio:
            return propio
    ruta = _programa(nombre)
    try:
        return ruta if shutil.which(ruta) or Path(ruta).is_file() else None
    except OSError as exc:
        # El disco de Windows visto desde WSL puede dar EIO (medido el 7-nov:
        # todo `/mnt/c` cayó y `is_file` lanzaba). Para quien pregunta «¿hay
        # X?», un programa que no se puede leer no está; se dice una vez (21).
        _decir_que_falta(NoHay(f"no se puede leer {ruta} ({exc.strerror or exc})"))
        return None


class NoHay(FileNotFoundError):
    """El programa no existe en esta máquina: no es un fallo, es que no aplica."""


# Lo que ya se dijo que falta. Sin esto, en un Linux sin Windows debajo el SAI
# escribía «no existe powershell.exe» en el registro CADA MINUTO (visto
# instalando en limpio el 13-oct). Se dice una vez, no se calla (regla dura 21).
_FALTAS_DICHAS: set[str] = set()


def _decir_que_falta(exc: NoHay) -> None:
    if str(exc) not in _FALTAS_DICHAS:
        _FALTAS_DICHAS.add(str(exc))
        print(f"[maquina] {exc} — no se medirá lo que depende de él", flush=True)


def _salida(comando: list[str]) -> str:
    programa = _programa(comando[0])
    if not shutil.which(programa) and not Path(programa).exists():
        raise NoHay(f"no hay {comando[0]} en esta máquina")
    return subprocess.run(
        [programa, *comando[1:]],
        capture_output=True, text=True, timeout=ESPERA, check=True,
    ).stdout.strip()


def _gpu() -> list[Medida]:
    """Temperatura, uso y memoria de la GPU, del propio driver.

    Es además el mejor termómetro de la caja que hay sin sensores de placa: si
    la habitación se calienta, esto sube.
    """
    crudo = _salida([
        "nvidia-smi.exe",
        "--query-gpu=name,temperature.gpu,utilization.gpu,memory.used,memory.total",
        "--format=csv,noheader,nounits",
    ])
    nombre, temp, uso, usada, total = [c.strip() for c in crudo.split(",")]
    return [
        Medida("gpu.nombre", texto=nombre),
        Medida("gpu.temperatura", float(temp), unidad="°C"),
        Medida("gpu.uso", float(uso), unidad="%"),
        Medida("gpu.memoria", float(usada) / float(total) * 100, unidad="%"),
    ]


def gpu_memoria() -> tuple[int, int] | None:
    """Memoria de la GPU en uso y total, en MB, medida al momento (C-0313), o
    None si no hay GPU NVIDIA o el driver no contesta. Cuesta ~0,3 s: sólo bajo
    demanda (el menú del modelo del dictado), nunca en un sondeo."""
    try:
        crudo = _salida(["nvidia-smi.exe", "--query-gpu=memory.used,memory.total",
                         "--format=csv,noheader,nounits"])
        usada, total = [int(float(c.strip())) for c in crudo.splitlines()[0].split(",")]
    except (NoHay, OSError, ValueError, IndexError, subprocess.SubprocessError):
        return None
    return usada, total


def _discos() -> list[Medida]:
    medidas: list[Medida] = []
    for clave, ruta in DISCOS:
        if not os.path.isdir(ruta):
            continue
        uso = shutil.disk_usage(ruta)
        medidas.append(Medida(f"{clave}.libre", uso.free / 1024**3, unidad="GB"))
        medidas.append(Medida(f"{clave}.uso", uso.used / uso.total * 100, unidad="%"))
    return medidas


def _memoria_y_carga() -> list[Medida]:
    """De la VM de WSL, que es donde corre el hub.

    No de Windows: lo que deja al hub sin memoria es lo que pase **dentro** de
    la VM, y mezclar las dos cifras en una pantalla es pedir que alguien lea la
    que no era.
    """
    campos = {}
    with open("/proc/meminfo", encoding="utf-8") as f:
        for linea in f:
            clave, _, resto = linea.partition(":")
            campos[clave] = float(resto.strip().split()[0]) / 1024**2  # kB → GB
    disponible = campos.get("MemAvailable", 0.0)
    total = campos.get("MemTotal", 0.0) or 1.0
    return [
        Medida("memoria.libre", disponible, unidad="GB"),
        Medida("memoria.uso", (1 - disponible / total) * 100, unidad="%"),
        Medida("carga", os.getloadavg()[0]),
    ]


# Un solo `powershell` para las tres cosas de Windows: arrancarlo cuesta más
# que cualquiera de las consultas, y son la misma pregunta —«¿qué le ha pasado
# a este equipo?»— hecha en tres sitios del registro de eventos.
#
# 1074 es un apagado que alguien o algo pidió (una actualización, por ejemplo);
# 41 y 6008 son los que no se pidieron: corte de luz o cuelgue. Distinguirlos
# importa, porque «se reinició solo» y «se fue la luz» piden cosas distintas.
_PS_WINDOWS = """
$ErrorActionPreference = 'Stop'
$os = Get-CimInstance Win32_OperatingSystem
Write-Output ("arranque=" + $os.LastBootUpTime.ToUniversalTime().ToString('s') + 'Z')
foreach ($par in @(@('apagon', @(41, 6008)), @('reinicio', @(1074)))) {
  try {
    $e = Get-WinEvent -FilterHashtable @{LogName='System'; Id=$par[1]} -MaxEvents 1
    Write-Output ($par[0] + "=" + $e.TimeCreated.ToUniversalTime().ToString('s') + 'Z')
  } catch { }
}
"""


def _windows() -> list[Medida]:
    """Desde cuándo lleva encendido, y el último apagón que no se pidió."""
    crudo = _salida(["powershell.exe", "-NoProfile", "-Command", _PS_WINDOWS])
    medidas: list[Medida] = []
    for linea in crudo.replace("\r", "").splitlines():
        clave, _, valor = linea.partition("=")
        if clave in ("arranque", "apagon", "reinicio") and valor:
            medidas.append(Medida(f"windows.{clave}", texto=valor))
    return medidas


# El SAI se ve porque está conectado por USB: Windows lo trata como una batería
# más. Es la única forma que tiene esta casa de enterarse de que se fue la luz
# **mientras todavía hay luz**, y por eso vale más que cualquier otra medida de
# aquí: da minutos de margen en vez de un silencio a posteriori.
#
# 🔴 `BatteryStatus` es un código, y su tabla es famosa por confusa. Aquí se
# guarda **el número crudo** y la lectura se hace contra `SOBRE_BATERIA`, que se
# midió desquitando la corriente de verdad. Interpretar de más un código que no
# se ha visto cambiar es exactamente la cifra que no se puede defender.
# 🔴 **Medido el 2026-09-21 quitando la corriente de verdad**, no leído de una
# tabla: con el SAI enchufado `BatteryStatus` vale 2; a los segundos de tirar
# del enchufe pasa a 1 y la carga cae de 100 a 83 %; al devolver la corriente
# vuelve a 2 y a 100 % en la siguiente lectura. Esa caída rápida de la carga es
# además la razón de que la alarma mire el ESTADO y no el porcentaje: un umbral
# sobre la carga saltaría en cada parpadeo de luz.
SOBRE_BATERIA = 1
CON_CORRIENTE = 2

_PS_UPS = """
$ErrorActionPreference = 'Stop'
$b = Get-CimInstance Win32_Battery | Select-Object -First 1
if ($b) {
  Write-Output ("nombre=" + $b.Name)
  Write-Output ("estado=" + $b.BatteryStatus)
  Write-Output ("carga=" + $b.EstimatedChargeRemaining)
  if ($b.EstimatedRunTime -and $b.EstimatedRunTime -lt 71582788) {
    Write-Output ("minutos=" + $b.EstimatedRunTime)
  }
}
"""


def _ups() -> list[Medida]:
    """El SAI, si está conectado por USB. Sin él, esto no devuelve nada.

    `EstimatedRunTime` vale 71582788 —el «desconocido» de WMI— cuando no hay
    estimación; dejarlo pasar pintaría «quedan 136 años de batería».
    """
    crudo = _salida(["powershell.exe", "-NoProfile", "-Command", _PS_UPS])
    medidas: list[Medida] = []
    for linea in crudo.replace("\r", "").splitlines():
        clave, _, valor = linea.partition("=")
        if not valor:
            continue
        if clave == "nombre":
            medidas.append(Medida("ups.nombre", texto=valor))
        elif clave == "estado":
            medidas.append(Medida("ups.estado", float(valor)))
        elif clave == "carga":
            medidas.append(Medida("ups.carga", float(valor), unidad="%"))
        elif clave == "minutos":
            medidas.append(Medida("ups.minutos", float(valor), unidad="min"))
    return medidas


# ── Lo que hace falta para que vuelva sola (C-0214) ─────────────────────────
#
# Con el hub en una máquina sin monitor, un apagón sólo tiene vuelta si cuatro
# cosas de fuera del hub están puestas, y ninguna avisa si falta: se descubre el
# día que no se puede entrar. Se midieron en la PC del dueño el 9-nov, que pasó
# por las cuatro (decisiones 172 y 205, y la corrección del 23-sep: Tailscale
# se quedó en `NeedsLogin` cinco horas tras un apagón real por no tener
# `--unattended`). Aquí sólo se mide; lo juzga `salud`.


def _tailscale() -> list[Medida]:
    """Si la red privada lleva al hub y si conecta sin sesión de Windows.

    El de Windows primero: es el que va con el hub en WSL (decisión 159). En un
    Linux sin Windows debajo el suyo corre como servicio del sistema y no tiene
    la pega de la sesión, así que ahí sólo se mira `serve`.
    """
    windows = encontrar("tailscale.exe")
    programa = "tailscale.exe" if windows else "tailscale"
    if not windows and not encontrar("tailscale"):
        raise NoHay("no hay tailscale en esta máquina")
    medidas: list[Medida] = []
    if windows:
        # `ForceDaemon` es lo que deja `tailscale set --unattended=true`. De
        # `prefs` no se guarda nada más: lleva la cuenta con la que se entró, y
        # por eso el error se dice sin la salida. En su propio `try`: que esto
        # falle no puede dejar sin mirar `serve` (regla dura 14).
        try:
            prefs = json.loads(_salida([programa, "debug", "prefs"]))
            medidas.append(Medida("desatendido.tailscale", 1.0 if prefs.get("ForceDaemon") else 0.0))
        except (subprocess.SubprocessError, ValueError) as exc:
            print(f"[maquina] tailscale debug prefs no midió: {type(exc).__name__}", flush=True)
    estado = json.loads(_salida([programa, "serve", "status", "--json"]) or "{}")
    sitio = sitio_del_hub(estado)
    medidas.append(Medida("desatendido.serve", 1.0 if sitio else 0.0, texto=sitio))
    return medidas


def sitio_del_hub(estado: dict) -> str:
    """El nombre por el que `tailscale serve` publica el hub, o "" si no lo hace.

    Sólo la configuración de arriba, que es la que se guarda (`serve --bg`): la
    de `Foreground` es un `serve` dejado en una terminal y muere con ella, así
    que tras un apagón no está.
    """
    return _sitio_con_puerto(estado).rsplit(":", 1)[0]


def _sitio_con_puerto(estado: dict) -> str:
    """Como `sitio_del_hub`, con el puerto («nombre:443»), o ""."""
    for sitio, web in (estado.get("Web") or {}).items():
        for manejador in ((web or {}).get("Handlers") or {}).values():
            proxy = (manejador or {}).get("Proxy") or ""
            destino = urlsplit(proxy if "://" in proxy else f"http://{proxy}")
            try:
                puerto = destino.port
            except ValueError:
                continue
            if destino.hostname in ("127.0.0.1", "localhost") and puerto == config.WEB_PORT:
                return sitio
    return ""


#: Lo que se espera a Tailscale al pintar /acceso: la medida del ciclo lento
#: puede esperar `ESPERA`, una pantalla no.
ESPERA_RED = 3


def _programa_tailscale() -> str | None:
    """El Tailscale que manda en esta máquina: el de Windows, si lo hay."""
    return encontrar("tailscale.exe") or encontrar("tailscale")


def red_privada(tope: float = ESPERA_RED) -> dict:
    """El nombre de esta máquina en la red privada y si `tailscale serve` ya
    lleva al hub, mirado al momento (C-0504). Nunca lanza.

    `hay`: si hay Tailscale; `conectado`: si dice estar en marcha (`Running`);
    `nombre`: `Self.DNSName` sin el punto final; `lleva_al_hub`: si serve
    publica `127.0.0.1:WEB_PORT`; `puerto`: en qué puerto lo publica (443 lo
    normal). Lo que no se pudo mirar va a `None`, no a «no» (regla dura 13):
    `error` dice por qué. El de Windows primero, como `_tailscale`."""
    salida = {"hay": False, "conectado": None, "nombre": "", "lleva_al_hub": None,
              "puerto": None, "error": ""}
    programa = _programa_tailscale()
    if not programa:
        salida["error"] = "no hay Tailscale en esta máquina"
        return salida
    salida["hay"] = True
    import time
    limite = time.monotonic() + tope

    def pedir(*argumentos) -> dict:
        # El tope es para las dos preguntas juntas: es lo que espera la pantalla.
        queda = limite - time.monotonic()
        if queda <= 0:
            raise subprocess.TimeoutExpired(programa, tope)
        texto = subprocess.run([programa, *argumentos], capture_output=True, text=True,
                               timeout=queda).stdout
        datos = json.loads(texto or "{}")
        return datos if isinstance(datos, dict) else {}

    try:
        estado = pedir("status", "--json")
        salida["conectado"] = estado.get("BackendState") == "Running"
        salida["nombre"] = str((estado.get("Self") or {}).get("DNSName") or "").strip().rstrip(".").lower()
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        salida["error"] = f"Tailscale no contestó ({type(exc).__name__})"
        return salida
    # En su propio `try`: sin serve se sabe igual el nombre (regla dura 14).
    try:
        sitio = _sitio_con_puerto(pedir("serve", "status", "--json"))
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        salida["error"] = f"no se pudo mirar tailscale serve ({type(exc).__name__})"
        return salida
    salida["lleva_al_hub"] = bool(sitio)
    if sitio:
        nombre, _, puerto = sitio.rpartition(":")
        salida["puerto"] = int(puerto) if puerto.isdigit() else 443
        salida["nombre"] = salida["nombre"] or nombre.lower()
    return salida


# Un solo `powershell` para las dos cosas de Windows, como en `_PS_WINDOWS`.
#
# La tarea se busca por lo que HACE y no por su nombre, que cada cual pone el
# suyo: que arranque al encender, sin sesión (S4U, o con contraseña guardada) y
# que lance WSL, sea directamente o desde el `.cmd` que ejecuta, que es como lo
# hace la del dueño (`mantener-wsl-arriba.cmd`, por la VM que WSL apagaba a los
# 16 s). La ruta del script no puede cruzar otra `X:\`: con el programa escrito
# con su ruta y el script sin comillas (`C:\…\cmd.exe /c C:\…\a.cmd`, lo que
# deja «Examinar» del Programador de tareas) se quedaba con las dos juntas, el
# `.cmd` no se leía y la tarea salía como que no está. Las formas, en
# `test_maquina`. `powercfg` sale en el idioma de Windows; sus dos últimos
# números son siempre «con corriente» y «con batería», en ese orden.
_PS_ARRANQUE = r"""
$ErrorActionPreference = 'Stop'
$q = (powercfg /query SCHEME_CURRENT SUB_SLEEP STANDBYIDLE) | Out-String
$h = [regex]::Matches($q, '0x[0-9a-fA-F]+')
if ($h.Count -ge 2) { Write-Output ("suspender=" + [Convert]::ToInt64($h[$h.Count - 2].Value, 16)) }
$tarea = ''
foreach ($t in Get-ScheduledTask) {
  if ($t.State -eq 'Disabled') { continue }
  if (-not ($t.Triggers | Where-Object { $_.CimClass.CimClassName -eq 'MSFT_TaskBootTrigger' })) { continue }
  if (@('S4U', 'Password') -notcontains [string]$t.Principal.LogonType) { continue }
  foreach ($a in $t.Actions) {
    $texto = "$($a.Execute) $($a.Arguments) "
    foreach ($m in [regex]::Matches($texto, '[A-Za-z]:\\(?:(?![A-Za-z]:\\)[^"])+?\.(cmd|bat|ps1)')) {
      if (Test-Path -LiteralPath $m.Value) { $texto += (Get-Content -LiteralPath $m.Value -Raw) }
    }
    if ($texto -match 'wsl(\.exe)?\s') { $tarea = $t.TaskName }
  }
}
Write-Output ("tarea=" + $tarea)
"""


def _arranque() -> list[Medida]:
    """Si Windows levanta WSL al encender sin nadie, y si se suspende solo."""
    crudo = _salida(["powershell.exe", "-NoProfile", "-Command", _PS_ARRANQUE])
    medidas: list[Medida] = []
    for linea in crudo.replace("\r", "").splitlines():
        clave, _, valor = linea.partition("=")
        if clave == "tarea":
            medidas.append(Medida("desatendido.tarea", 1.0 if valor else 0.0, texto=valor))
        elif clave == "suspender" and valor:
            medidas.append(Medida("desatendido.suspender", float(valor), unidad="s"))
    return medidas


# ── El último arranque (C-0381, C-0014) ───────────────────────────────────────
# Si el hub vuelve solo tras un apagón se planteaba como un ensayo que montar,
# y los apagones y pantallazos reales ya dejan la evidencia: faltaba apuntarla
# para cruzarla con `windows.arranque`. Dos instantes que systemd anota al
# arrancar, en la hora de pared:
#   - `UserspaceTimestamp` del sistema: cuando arrancó Linux en WSL.
#   - `FinishTimestamp` del usuario: cuando su gestor —con linger, al arrancar—
#     terminó de lanzar sus servicios, que son los del hub.
# 🔴 No `btime` de `/proc/stat`: medido el 13-nov, salía cinco horas más tarde
# que el arranque de verdad (16:51 en `journalctl --list-boots`), porque el
# reloj de arranque de WSL no cuenta la VM en pausa. Ni el `ActiveEnterTimestamp`
# de `hub-web`: cambia en cada reinicio del servicio y deja de ser el del
# arranque. Los dos de aquí cuadraron el 13-nov con el arranque del 6-nov:
# Windows 22:50:24Z, Linux 22:51:13Z (lo mismo que `journalctl`), servicios
# 22:51:49Z (regla dura 19).
_INSTANTES = (
    ("encendido.wsl", ["systemctl", "show", "-p", "UserspaceTimestamp", "--value", "--timestamp=unix"]),
    ("encendido.hub", ["systemctl", "--user", "show", "-p", "FinishTimestamp", "--value", "--timestamp=unix"]),
)


def _hay_systemd() -> bool:
    """Lo que mira `sd_booted()`: sin systemd de PID 1 no hay a quién preguntar."""
    return os.path.isdir("/run/systemd/system")


def _de_unix(crudo: str) -> str:
    """`@1794005473` → `2026-11-06T22:51:13Z`, el formato de `windows.arranque`.
    Vacío si no es eso: un instante que no se entiende no se guarda (regla 13)."""
    crudo = crudo.strip()
    if not (crudo.startswith("@") and crudo[1:].isdigit() and int(crudo[1:]) > 0):
        return ""
    return datetime.fromtimestamp(int(crudo[1:]), timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _encendido() -> list[Medida]:
    """Cuándo arrancaron Linux en WSL y los servicios del hub, la última vez."""
    if not _hay_systemd():
        raise NoHay("no hay systemd: no se sabe cuándo arrancó el hub")
    medidas: list[Medida] = []
    for clave, comando in _INSTANTES:
        # Cada uno en su `try` (regla dura 14). Un systemd viejo sin
        # `--timestamp=unix` lo diría cada diez minutos: se dice una vez (21).
        try:
            iso = _de_unix(_salida(comando))
        except subprocess.CalledProcessError as exc:
            _decir_que_falta(NoHay(f"systemctl no dio {clave}: {(exc.stderr or '').strip()[:120]}"))
            continue
        if iso:
            medidas.append(Medida(clave, texto=iso))
    return medidas


def medir(sai: bool = True) -> list[Medida]:
    """Todo lo que se puede leer, cada cosa en su propio `try`.

    🔴 Que no haya GPU no puede dejar sin medir el disco, que es lo que de
    verdad se llena. Es la regla dura 14 aplicada dentro de la propia medición,
    no sólo alrededor de ella.

    `sai=False` deja fuera el SAI, para quien mide a la vez que el latido (el
    ciclo lento en su hilo, C-0309). Esto lee el SAI a mitad y se guarda al
    final, segundos después y con la fecha del guardado: una lectura que el
    latido hiciera entre medias quedaba pisada por la vieja hasta un minuto,
    y un corte de luz justo ahí se veía como «volvió» y «se fue».
    """
    medidas: list[Medida] = []
    fallos = 0
    fuentes = (_gpu, _discos, _memoria_y_carga, _windows, _ups, _tailscale, _arranque, _encendido)
    for fuente in fuentes if sai else tuple(f for f in fuentes if f is not _ups):
        try:
            medidas.extend(fuente())
        except NoHay as exc:
            _decir_que_falta(exc)
        except Exception as exc:
            fallos += 1
            # 🔴 En voz alta (regla dura 21). Callarlo es lo que dejó al
            # servicio midiendo la mitad sin que se notara: la pantalla seguía
            # enseñando cifras, sólo que de hacía diez minutos.
            print(f"[maquina] {fuente.__name__} no midió: {exc}", flush=True)
    if not medidas and fallos:
        raise MaquinaNoMedida("ninguna medida se pudo tomar")
    return medidas


def escanear_ups(con: sqlite3.Connection) -> int:
    """Sólo el SAI, para poder mirarlo más a menudo que lo demás.

    🔴 La cadencia es la mitad del valor de este aviso. El ciclo lento pasa cada
    diez minutos y el SAI aguanta ~22: enterarse del corte a los diez habría
    gastado casi la mitad del margen en esperar. Medir sólo esto cuesta un
    `powershell` —0,4 s— así que cabe cada minuto sin volver lento el latido,
    que es lo que la regla dura 14 protege.
    """
    try:
        medidas = _ups()
    except NoHay as exc:
        _decir_que_falta(exc)
        return 0
    return _guardar(con, medidas)


def escanear(con: sqlite3.Connection, sai: bool = True) -> int:
    """Guarda la última lectura de cada magnitud. Devuelve cuántas se tomaron.

    Sólo la última: esto no es un histórico. Volver a medir lo reconstruye
    entero (regla dura 1), y guardar la serie convertiría al hub en un sistema
    de monitorización, que es precisamente lo que el principio 9 dice que no es.

    `sai=False`: todo menos el SAI, que entonces sólo lo guarda
    `escanear_ups` (ver `medir`).
    """
    return _guardar(con, medir() if sai else medir(sai=False))


def _guardar(con: sqlite3.Connection, medidas: list[Medida]) -> int:
    momento = ahora()
    for m in medidas:
        con.execute(
            """INSERT INTO maquina (clave, valor, texto, unidad, medido_en)
               VALUES (?,?,?,?,?)
               ON CONFLICT(clave) DO UPDATE SET
                 valor=excluded.valor, texto=excluded.texto,
                 unidad=excluded.unidad, medido_en=excluded.medido_en""",
            (m.clave, m.valor, m.texto, m.unidad, momento),
        )
    return len(medidas)


def ultimas(con: sqlite3.Connection) -> dict[str, dict]:
    """Lo último medido, por clave, con su fecha. Vacío si nunca se midió."""
    return {
        f["clave"]: dict(f)
        for f in con.execute("SELECT * FROM maquina ORDER BY clave")
    }


def valor(con: sqlite3.Connection, clave: str) -> float | None:
    fila = con.execute("SELECT valor FROM maquina WHERE clave=?", (clave,)).fetchone()
    return fila["valor"] if fila and fila["valor"] is not None else None
