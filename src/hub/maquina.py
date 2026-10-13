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

import os
import shutil
import sqlite3
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


def ahora() -> str:
    # Repetido y no importado de `snapshotter`: el ciclo lento vive allí y
    # llamar aquí, así que importarlo al revés cerraría el círculo.
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


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
}


def _programa(nombre: str) -> str:
    """El ejecutable, con su ruta absoluta si el PATH no lo trae."""
    return shutil.which(nombre) or RESPALDOS.get(nombre, nombre)


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


def medir() -> list[Medida]:
    """Todo lo que se puede leer, cada cosa en su propio `try`.

    🔴 Que no haya GPU no puede dejar sin medir el disco, que es lo que de
    verdad se llena. Es la regla dura 14 aplicada dentro de la propia medición,
    no sólo alrededor de ella.
    """
    medidas: list[Medida] = []
    fallos = 0
    for fuente in (_gpu, _discos, _memoria_y_carga, _windows, _ups):
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


def escanear(con: sqlite3.Connection) -> int:
    """Guarda la última lectura de cada magnitud. Devuelve cuántas se tomaron.

    Sólo la última: esto no es un histórico. Volver a medir lo reconstruye
    entero (regla dura 1), y guardar la serie convertiría al hub en un sistema
    de monitorización, que es precisamente lo que el principio 9 dice que no es.
    """
    return _guardar(con, medir())


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
