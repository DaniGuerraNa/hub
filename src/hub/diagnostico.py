"""Diagnosticar la PC con Windows y su red, en sólo lectura (decisión 386, C-0194).

Nace de dos noches del dueño: dos pantallazos seguidos (5 y 6-nov) y un juego
con el ping por las nubes. Se lo pidió al secretario, que contestó «no tengo
permisos»; desde WSL se diagnosticó en minutos y **sólo leyendo**, con
`powershell.exe`, `tracert.exe` y `ping.exe`. Esto es esa lectura, fija, para
que la pueda hacer él sin tener que venir al hub.

No va en `maquina.py` a propósito: aquello mide solo en el ciclo lento y
guarda la última medida; esto se pide, tarda unos segundos y no se guarda.
Los programas sí se buscan por la puerta de allí (`maquina.encontrar`), porque
el PATH de un servicio de systemd no trae los de Windows (decisión 81).

🔴 **Sólo lectura, y se comprueba.** Los guiones de PowerShell son fijos y
`tests/test_diagnostico.py` los lee: sólo pueden usar los verbos de
`VERBOS_DE_LECTURA`, y lo que está en posición de orden tiene que ser uno de
esos cmdlets o una palabra del lenguaje. Lo que entra de fuera se valida contra
un patrón **antes** de lanzar nada: en un guion sólo entra el nombre de un
proceso, entre comillas simples y con un patrón que no admite comillas; los
destinos no entran en ninguno, van como argumento suelto a `tracert.exe` y
`ping.exe`, sin shell. Lo que cambie algo en la PC no va por aquí: o
por el agente de Reuniones, o no va (386).

🔴 **Todo cabe en `TOPE_S`**, por debajo de los 60 s: el secretario lo llama
como herramienta, y `motor.SIN_NOTICIAS_S` mata la que se calla demasiado. Por
eso las latencias van con `ping.exe` **en paralelo** y no con
`Test-Connection`, que es secuencial y espera ~4,5 s por cada eco perdido
(medido el 7-nov: 9 s por dos ecos a una IP muerta, 4,3 s por cinco a una
viva); un solo destino caído se habría comido el tope.
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import re
import subprocess
import sys
import time
from collections.abc import Sequence
from datetime import datetime

from . import maquina
from .reloj import a_local


def _reloj() -> float:
    """El reloj de los plazos; aparte para que un test pueda adelantarlo."""
    return time.monotonic()


class SinWindows(RuntimeError):
    """No hay Windows debajo: el hub no corre en WSL o no encuentra sus programas."""


#: El tope de todo un diagnóstico, en segundos. Por debajo de 60, y lejos de
#: `motor.SIN_NOTICIAS_S`, que es lo que mata una herramienta callada.
TOPE_S = 50
#: Lo que se espera a PowerShell, dentro del tope. Medido el 7-nov: 1,9 s el
#: guion de Windows y 1,9 s el de la red.
ESPERA_PS = 25
DIAS_POR_OMISION = 14
DIAS_MAX = 60
#: Destinos de referencia, siempre, además de la puerta de enlace: si éstos van
#: bien y el del juego no, el problema no está en casa (lo del 6-nov).
REFERENCIAS = ("1.1.1.1", "8.8.8.8")
DESTINOS_MAX = 6
PINGS = 5
ESPERA_PING_MS = 1000
SALTOS = 15
ESPERA_SALTO_MS = 500
#: De cuántas conexiones de un proceso se mide la latencia.
REMOTAS_MAX = 3
#: Lo que se guarda del texto de un evento: viene en el idioma del sistema y
#: el dato es el código, no la prosa.
TEXTO = 300

#: Los únicos verbos que pueden aparecer en un guion (lo comprueba un test).
VERBOS_DE_LECTURA = ("Get", "Test", "Select", "ConvertTo", "Where", "ForEach", "Measure")

_PROCESO = re.compile(r"[A-Za-z0-9 ._-]{1,64}")
# Un nombre de host: etiquetas de letras, cifras y guiones, nunca empezando por
# guion. 🔴 Eso último no es estética: `ping.exe -t` haría ping para siempre, y
# cualquier destino que empiece por «-» se leería como una opción.
_HOST = re.compile(r"(?=.{1,253}$)[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
                   r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*\.?")
_CODIGO = re.compile(r"0x[0-9A-Fa-f]{8}")

#: Los pantallazos más comunes, con el nombre que les da Microsoft. Sólo los
#: que se sabe seguro: uno que no esté aquí se enseña con su código y nada más.
NOMBRES_BUGCHECK = {
    0x0A: "IRQL_NOT_LESS_OR_EQUAL",
    0x1A: "MEMORY_MANAGEMENT",
    0x1E: "KMODE_EXCEPTION_NOT_HANDLED",
    0x3B: "SYSTEM_SERVICE_EXCEPTION",
    0x50: "PAGE_FAULT_IN_NONPAGED_AREA",
    0x7E: "SYSTEM_THREAD_EXCEPTION_NOT_HANDLED",
    0x9F: "DRIVER_POWER_STATE_FAILURE",
    0xD1: "DRIVER_IRQL_NOT_LESS_OR_EQUAL",
    0xEF: "CRITICAL_PROCESS_DIED",
    0x101: "CLOCK_WATCHDOG_TIMEOUT",
    0x116: "VIDEO_TDR_FAILURE",
    0x124: "WHEA_UNCORRECTABLE_ERROR",
    0x133: "DPC_WATCHDOG_VIOLATION",
    0x139: "KERNEL_SECURITY_CHECK_FAILURE",
    0x154: "UNEXPECTED_STORE_EXCEPTION",
}

# Qué es cada evento, dicho para el dueño. 41 y 6008 son los apagados que nadie
# pidió (cuelgue o luz), 1074 el que sí se pidió; 161 explica por qué a veces
# no hay volcado; 6005/6006, cada arranque y cada apagado limpio.
_QUE = {
    41: "se reinició sin apagarse bien",
    161: "no pudo guardar el volcado",
    1074: "apagado o reinicio pedido",
    6005: "arranque",
    6006: "apagado limpio",
    6008: "el apagado anterior fue inesperado",
}

# ─────────────────────────────── los guiones ───────────────────────────────
#
# Sin comillas dobles: viajan por la línea de órdenes de Windows, que las
# interpreta. Lo de fuera entra sólo por `__DIAS__` (un entero) y
# `__PROCESO__` (validado), siempre entre comillas simples.

_PS_WINDOWS = r"""
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$desde = (Get-Date).AddDays(-__DIAS__)
$fallos = @()
$sinPermiso = @()
$eventos = @()
foreach ($filtro in @(
    @{LogName='System'; Id=41,1001,6008,161; StartTime=$desde},
    @{LogName='System'; Id=1074,6005,6006; StartTime=$desde},
    @{LogName='System'; ProviderName='Microsoft-Windows-WHEA-Logger'; StartTime=$desde})) {
  try {
    $eventos += @(Get-WinEvent -FilterHashtable $filtro -MaxEvents 40 | ForEach-Object {
      $m = [string]$_.Message
      $b = $null
      if ($_.Id -eq 41 -and $_.Properties.Count -gt 0) { $b = [int64]$_.Properties[0].Value }
      [ordered]@{id=$_.Id; fuente=$_.ProviderName; hora=$_.TimeCreated.ToUniversalTime().ToString('s') + 'Z';
                 bugcheck=$b; texto=$m.Substring(0, [Math]::Min(1000, $m.Length))}
    })
  } catch {
    if ($_.FullyQualifiedErrorId -notlike 'NoMatchingEventsFound*') { $fallos += ('eventos: ' + $_.Exception.Message) }
  }
}
$volcados = @()
foreach ($ruta in @('C:\Windows\Minidump', 'C:\Windows\MEMORY.DMP')) {
  try {
    $volcados += @(Get-ChildItem -LiteralPath $ruta -Force | Where-Object { -not $_.PSIsContainer } |
      Select-Object -First 60 | ForEach-Object {
        [ordered]@{nombre=$_.FullName; bytes=$_.Length; fecha=$_.LastWriteTime.ToUniversalTime().ToString('s') + 'Z'}
      })
  } catch {
    if ($_.CategoryInfo.Category -eq 'PermissionDenied' -or $_.Exception -is [System.UnauthorizedAccessException]) {
      $sinPermiso += $ruta
    } elseif ($_.CategoryInfo.Category -ne 'ObjectNotFound') { $fallos += ($ruta + ': ' + $_.Exception.Message) }
  }
}
$equipo = [ordered]@{}
try {
  $bios = Get-CimInstance Win32_BIOS
  $placa = Get-CimInstance Win32_BaseBoard
  $cpu = Get-CimInstance Win32_Processor | Select-Object -First 1
  $so = Get-CimInstance Win32_OperatingSystem
  $equipo = [ordered]@{
    bios=[ordered]@{fabricante=$bios.Manufacturer; version=$bios.SMBIOSBIOSVersion; fecha=$bios.ReleaseDate.ToString('yyyy-MM-dd')};
    placa=[ordered]@{fabricante=$placa.Manufacturer; modelo=$placa.Product};
    cpu=([string]$cpu.Name).Trim();
    windows=[ordered]@{nombre=$so.Caption; version=$so.Version; arranque=$so.LastBootUpTime.ToUniversalTime().ToString('s') + 'Z'}
  }
} catch { $fallos += ('equipo: ' + $_.Exception.Message) }
[ordered]@{eventos=$eventos; volcados=$volcados; sin_permiso=$sinPermiso; equipo=$equipo; fallos=$fallos} |
  ConvertTo-Json -Compress -Depth 5
"""

_PS_RED = r"""
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$fallos = @()
$adaptadores = @()
$rutas = @()
$dns = @()
try {
  $adaptadores = @(Get-NetAdapter | Where-Object { $_.Status -eq 'Up' } | ForEach-Object {
    [ordered]@{nombre=$_.Name; descripcion=$_.InterfaceDescription; velocidad=$_.LinkSpeed; medio=$_.MediaType}
  })
} catch { $fallos += ('adaptadores: ' + $_.Exception.Message) }
try {
  $rutas = @(Get-NetRoute -DestinationPrefix '0.0.0.0/0' | ForEach-Object {
    [ordered]@{siguiente=$_.NextHop; interfaz=$_.InterfaceAlias; metrica=[int]$_.RouteMetric + [int]$_.InterfaceMetric}
  })
} catch { $fallos += ('ruta: ' + $_.Exception.Message) }
try {
  $dns = @(Get-DnsClientServerAddress -AddressFamily IPv4 | Where-Object { $_.ServerAddresses.Count -gt 0 } |
    ForEach-Object { [ordered]@{interfaz=$_.InterfaceAlias; servidores=@($_.ServerAddresses)} })
} catch { $fallos += ('dns: ' + $_.Exception.Message) }
$proceso = $null
$buscado = '__PROCESO__'
if ($buscado) {
  $proceso = [ordered]@{buscado=$buscado; procesos=@(); tcp=@(); udp=@()}
  try {
    $ps = @(Get-Process | Where-Object { $_.ProcessName -like ('*' + $buscado + '*') } | Select-Object -First 20)
    $proceso.procesos = @($ps | ForEach-Object { [ordered]@{nombre=$_.ProcessName; pid=$_.Id} })
    $ids = @($ps | ForEach-Object { [uint32]$_.Id })
    if ($ids.Count -gt 0) {
      $proceso.tcp = @(Get-NetTCPConnection -OwningProcess $ids -State Established -ErrorAction SilentlyContinue |
        Select-Object -First 60 | ForEach-Object {
          [ordered]@{remota=$_.RemoteAddress; puerto=$_.RemotePort; local=$_.LocalPort; pid=$_.OwningProcess}
        })
      $proceso.udp = @(Get-NetUDPEndpoint -OwningProcess $ids -ErrorAction SilentlyContinue |
        Select-Object -First 60 | ForEach-Object { [ordered]@{local=$_.LocalAddress; puerto=$_.LocalPort; pid=$_.OwningProcess} })
    }
  } catch { $fallos += ('proceso: ' + $_.Exception.Message) }
}
[ordered]@{adaptadores=$adaptadores; rutas=$rutas; dns=$dns; proceso=$proceso; fallos=$fallos} |
  ConvertTo-Json -Compress -Depth 5
"""

#: Los guiones, para que el test los lea todos.
GUIONES = (_PS_WINDOWS, _PS_RED)


# ─────────────────────────────── validar ───────────────────────────────


def validar_destino(destino: str) -> str:
    """Una IP literal o un nombre de host; lo demás, `ValueError` antes de lanzar nada."""
    d = str(destino or "").strip()
    # 🔴 Sin «%»: `ipaddress` acepta una IPv6 con zona («fe80::1%lo que sea») y
    # detrás del «%» cabe cualquier texto, espacios incluidos.
    if "%" not in d:
        try:
            return str(ipaddress.ip_address(d))
        except ValueError:
            pass
    if not _HOST.fullmatch(d):
        raise ValueError(f"destino no válido: {d[:60]!r} (una IP o un nombre de host)")
    return d


def validar_proceso(proceso: str) -> str:
    """El nombre de un proceso, sin «.exe»; con comillas o comodines no pasa."""
    p = str(proceso or "").strip()
    if p.lower().endswith(".exe"):
        p = p[:-4]
    if not _PROCESO.fullmatch(p):
        raise ValueError(f"proceso no válido: {p[:60]!r} (letras, cifras, espacio, punto, guion; hasta 64)")
    return p


# ─────────────────────────────── lanzar ───────────────────────────────


def _programa(nombre: str) -> str:
    ruta = maquina.encontrar(nombre)
    if not ruta:
        raise SinWindows(f"No encuentro Windows debajo de esta máquina (falta {nombre}): este diagnóstico "
                         "sólo funciona con el hub instalado en WSL.")
    return ruta


def _lanzar(args: list[str]) -> subprocess.Popen:
    """Un programa con sus argumentos sueltos: nunca por una shell (regla dura 10)."""
    return subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def _esperar(proc, fin: float) -> tuple[int | None, bytes, bytes]:
    """Lo que dijo, esperando como mucho hasta `fin`. Si no acabó, se mata y
    devuelve `None` como código: el diagnóstico sigue con lo demás."""
    try:
        salida, error = proc.communicate(timeout=max(0.05, fin - _reloj()))
        return proc.returncode, salida or b"", error or b""
    except subprocess.TimeoutExpired:
        proc.kill()
        # Lo que ya escribió (media traza) está en la tubería y matar la
        # cierra, así que leerlo es inmediato. Se acota igual, contra el mismo
        # plazo más un segundo: uno que no suelte no alarga el tope por cada
        # proceso.
        try:
            salida, error = proc.communicate(timeout=max(0.05, fin + 1 - _reloj()))
        except subprocess.TimeoutExpired:
            salida, error = b"", b""
        return None, salida or b"", error or b""


def _texto(crudo: bytes) -> str:
    """`ping.exe` y `tracert.exe` escriben en la página de códigos de la
    consola (850 en español), PowerShell en UTF-8 porque se le pide. Se lee lo
    que venga; lo que importa son números e IP, que son ASCII en las dos."""
    try:
        t = crudo.decode("utf-8")
    except UnicodeDecodeError:
        t = crudo.decode("cp850", "replace")
    # Windows mete marcas de dirección (U+200E) dentro de las fechas.
    return t.replace("\r", "").replace("\u200e", "").replace("\u200f", "")


def _powershell(guion: str, fin: float) -> tuple[dict, list[str]]:
    ps = _programa("powershell.exe")
    try:
        proc = _lanzar([ps, "-NoProfile", "-NonInteractive", "-Command", guion])
    except OSError as exc:
        # El archivo está pero no arranca: la interoperabilidad de WSL con
        # Windows está apagada (así se midió para la 313). Es «no hay Windows»
        # a efectos de esto, y se dice igual de claro.
        raise SinWindows(f"No puedo lanzar programas de Windows desde aquí ({exc}): ¿está apagada la "
                         "interoperabilidad de WSL con Windows?") from exc
    rc, salida, error = _esperar(proc, fin)
    if rc is None:
        return {}, [f"PowerShell no terminó en {ESPERA_PS} s"]
    texto = _texto(salida)
    linea = next((x for x in reversed(texto.splitlines()) if x.strip().startswith("{")), "")
    try:
        return json.loads(linea), []
    except ValueError:
        motivo = " ".join(_texto(error).split())[:200] or "salida vacía"
        return {}, [f"PowerShell no devolvió lo esperado (código {rc}): {motivo}"]


def _lista(x) -> list:
    if x is None:
        return []
    return x if isinstance(x, list) else [x]


# ─────────────────────────────── Windows ───────────────────────────────


def _codigo(n: int) -> str:
    return f"0x{n:08X}"


def _nombre_bugcheck(codigo: str) -> str:
    try:
        return NOMBRES_BUGCHECK.get(int(codigo, 16), "")
    except ValueError:
        return ""


#: La hora de la caída dentro del texto del 6008, en español o en inglés
#: («…del sistema a las 04:13:25 p. m. del 06/11/2026…», «…at 4:13:25 PM on…»).
_CAIDA = re.compile(r"(?i)(?:a las|at)\s+(\d{1,2}:\d{2}(?::\d{2})?(?:\s*[ap]\.?\s?m\.?)?(?:\s+(?:del?|on)\s+[\d/.-]+)?)")


def leer_windows(crudo: dict, dias: int = DIAS_POR_OMISION) -> dict:
    """De lo que devolvió el guion, lo que sirve: los pantallazos con su código
    y su hora, los eventos recortados, los volcados y el equipo.

    La hora de un pantallazo es la del evento 1001, que Windows escribe al
    **volver a arrancar**, y no la de la caída: si se quedó colgado en la
    pantalla azul (sin volcado, el 161), puede ser media hora después —el
    5 y el 6-nov fueron 23 y 37 min, revisión cruzada del 7-nov—. La hora
    de la caída la dice el 6008 en su texto, en el idioma de Windows: se
    enseña tal cual (`cayo`), sin interpretarla (regla 13). Ni se abre
    ningún volcado ni hace falta."""
    eventos = []
    for e in _lista(crudo.get("eventos")):
        if not isinstance(e, dict):
            continue
        texto = " ".join(str(e.get("texto") or "").split())
        ident, fuente = int(e.get("id") or 0), str(e.get("fuente") or "")
        m = _CODIGO.search(texto)
        codigo = "0x" + m.group(0)[2:].upper() if m else ""
        # El 41 trae el código en sus propiedades, no en el texto, y a veces
        # es el único que lo tiene (cuando no se escribió el 1001).
        if ident == 41 and e.get("bugcheck"):
            codigo = _codigo(int(e["bugcheck"]))
        if "WHEA" in fuente:
            que = "error de hardware (WHEA)"
        elif ident == 1001 and "SystemErrorReporting" in fuente:
            que = "pantallazo"
        else:
            que = _QUE.get(ident, f"evento {ident}")
        eventos.append({"id": ident, "que": que, "hora": str(e.get("hora") or ""), "fuente": fuente,
                        "codigo": codigo, "nombre": _nombre_bugcheck(codigo) if codigo else "",
                        "texto": texto[:TEXTO]})
    eventos.sort(key=lambda x: x["hora"], reverse=True)

    pantallazos = [{"hora": e["hora"], "codigo": e["codigo"], "nombre": e["nombre"]}
                   for e in eventos if e["que"] == "pantallazo" and e["codigo"]]
    # Un 41 con código y sin su 1001 al lado también fue un pantallazo: el
    # 1001 falta cuando el volcado no se pudo guardar (el 161).
    for e in eventos:
        if e["id"] == 41 and e["codigo"] and not any(
                p["codigo"] == e["codigo"] and abs(_segundos(p["hora"]) - _segundos(e["hora"])) < 900
                for p in pantallazos):
            pantallazos.append({"hora": e["hora"], "codigo": e["codigo"], "nombre": e["nombre"]})
    pantallazos.sort(key=lambda x: x["hora"], reverse=True)
    for p in pantallazos:
        p["cayo"] = next((m.group(1).strip() for e in eventos if e["id"] == 6008
                          and abs(_segundos(e["hora"]) - _segundos(p["hora"])) < 900
                          for m in [_CAIDA.search(e["texto"])] if m), "")

    volcados = sorted(({"nombre": str(v.get("nombre") or ""), "bytes": int(v.get("bytes") or 0),
                        "fecha": str(v.get("fecha") or "")} for v in _lista(crudo.get("volcados"))
                       if isinstance(v, dict)), key=lambda v: v["fecha"], reverse=True)
    return {"que": "windows", "dias": dias, "equipo": crudo.get("equipo") or {}, "pantallazos": pantallazos,
            "eventos": eventos, "volcados": volcados[:10], "sin_permiso": _lista(crudo.get("sin_permiso")),
            "fallos": [str(f)[:300] for f in _lista(crudo.get("fallos"))]}


def _segundos(iso: str) -> float:
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def windows(dias: int = DIAS_POR_OMISION) -> dict:
    """Pantallazos, apagados, volcados (sin abrirlos) y el equipo, de los
    últimos `dias`. Sólo lectura. `SinWindows` si no hay Windows debajo."""
    dias = int(dias)
    if not 1 <= dias <= DIAS_MAX:
        raise ValueError(f"días entre 1 y {DIAS_MAX}")
    t0 = _reloj()
    crudo, fallos = _powershell(_PS_WINDOWS.replace("__DIAS__", str(dias)), min(t0 + ESPERA_PS, t0 + TOPE_S))
    d = leer_windows(crudo, dias)
    d["fallos"] = fallos + d["fallos"]
    d["segundos"] = round(_reloj() - t0, 1)
    return d


# ─────────────────────────────── red ───────────────────────────────

# Un eco de `ping.exe`, en cualquier idioma: una línea sin sangría con un
# tiempo pegado a «=» o «<»: «tiempo=41ms TTL=54», «time<1ms TTL=64», en
# español «tiempo<1m TTL=64» (así, sin la «s») y, en IPv6, sin TTL:
# «Respuesta desde ::1: tiempo<1m» (medido el 7-nov). «Host de destino
# inaccesible» empieza igual y no trae tiempo; el resumen va con sangría y con
# espacio tras el «=» («Mínimo = 0ms»).
_ECO = re.compile(r"([=<])(\d+)\s?ms?(?=\s|$)", re.I)
# Un salto de `tracert.exe`: el número, tres medidas («<1 ms», «12 ms» o «*»)
# y lo que quede, donde está la IP si contestó. Sin palabras: vale en
# cualquier idioma.
_SALTO = re.compile(r"^\s*(\d{1,2})\s+((?:(?:<?\d+\s*ms|\*)\s+){3})(.*)$")
_MEDIDA = re.compile(r"(<?)(\d+)\s*ms|\*")
_IP = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b|\b[0-9a-fA-F]{0,4}(?::[0-9a-fA-F]{0,4}){2,7}\b")


def leer_ping(salida: str, enviados: int = PINGS) -> dict:
    """Ecos, pérdida y tiempos. «<1» cuenta como 0, como el propio resumen de
    `ping.exe` («Mínimo = 0ms»)."""
    tiempos = []
    for linea in salida.splitlines():
        m = _ECO.search(linea) if linea[:1].strip() else None
        if m:
            tiempos.append(0 if m.group(1) == "<" else int(m.group(2)))
    tiempos = tiempos[:enviados]
    d = {"enviados": enviados, "recibidos": len(tiempos),
         "perdidos_pct": round(100 * (enviados - len(tiempos)) / enviados) if enviados else 0}
    if tiempos:
        d.update(min=min(tiempos), media=round(sum(tiempos) / len(tiempos)), max=max(tiempos))
    else:
        # Si ping llegó a correr (hay resumen con sangría), la primera línea es
        # «Haciendo ping a…» y el motivo es la siguiente; si no, el error es
        # todo lo que dijo.
        lineas = [x.rstrip() for x in salida.splitlines() if x.strip()]
        de_raiz = [x.strip() for x in lineas if x[:1].strip()]
        if len(de_raiz) > 1 and len(de_raiz) < len(lineas):
            d["nota"] = de_raiz[1][:160]
        else:
            d["nota"] = " ".join(de_raiz)[:160]
    return d


def leer_tracert(salida: str) -> list[dict]:
    """Los saltos: número, las tres medidas en ms (None = «*», sin respuesta) y la IP."""
    saltos = []
    for linea in salida.splitlines():
        m = _SALTO.match(linea)
        if not m:
            continue
        medidas = [None if x.group(0) == "*" else (0 if x.group(1) else int(x.group(2)))
                   for x in _MEDIDA.finditer(m.group(2))]
        ip = _IP.search(m.group(3))
        saltos.append({"salto": int(m.group(1)), "ms": medidas, "ip": ip.group(0) if ip else None})
    return saltos


def _puerta(rutas: list) -> str | None:
    """La puerta de enlace de la ruta por omisión que gana (la de menor métrica).

    Viene de Windows, no de fuera, pero va a `ping.exe` igual que un destino
    pedido: pasa por el mismo patrón."""
    buenas = [r for r in rutas if isinstance(r, dict) and r.get("siguiente") not in (None, "", "0.0.0.0")]
    buenas.sort(key=lambda r: int(r.get("metrica") or 0))
    for r in buenas:
        try:
            return validar_destino(str(r["siguiente"]))
        except ValueError:
            continue
    return None


def _remotas(proceso: dict | None) -> list[str]:
    """Las direcciones públicas a las que habla el proceso por TCP, sin repetir."""
    vistas: list[str] = []
    for c in _lista((proceso or {}).get("tcp")):
        try:
            ip = ipaddress.ip_address(str(c.get("remota")))
        except ValueError:
            continue
        if ip.version == 6 and ip.ipv4_mapped:
            ip = ip.ipv4_mapped
        if ip.is_global and str(ip) not in vistas:
            vistas.append(str(ip))
    return vistas[:REMOTAS_MAX]


def red(destinos: Sequence[str] = (), proceso: str | None = None, trazar: str | None = None) -> dict:
    """Adaptadores y su velocidad, la ruta, el DNS, la latencia y la pérdida a
    la puerta de enlace, a `REFERENCIAS` y a `destinos`; con `proceso`, sus
    conexiones y la latencia a lo que usa; con `trazar`, el traceroute.

    Los argumentos se validan antes de lanzar nada (`ValueError`). La traza y
    los pings corren en paralelo con PowerShell para caber en `TOPE_S`."""
    if isinstance(destinos, str):
        destinos = [destinos]
    destinos = [validar_destino(d) for d in destinos if str(d or "").strip()]
    if len(destinos) > DESTINOS_MAX:
        raise ValueError(f"como mucho {DESTINOS_MAX} destinos")
    buscado = validar_proceso(proceso) if proceso else ""
    trazar = validar_destino(trazar) if trazar else None
    _programa("powershell.exe")

    t0 = _reloj()
    fin = t0 + TOPE_S
    fallos: list[str] = []
    traza_proc = None
    if trazar:
        tracert = maquina.encontrar("tracert.exe")
        if tracert:
            try:
                traza_proc = _lanzar([tracert, "-d", "-h", str(SALTOS), "-w", str(ESPERA_SALTO_MS), trazar])
            except OSError as exc:
                fallos.append(f"no pude lanzar tracert.exe: {exc}")
        else:
            fallos.append("no encuentro tracert.exe: sin traza")

    try:
        crudo, f = _powershell(_PS_RED.replace("__PROCESO__", buscado), min(t0 + ESPERA_PS, fin))
    except BaseException:
        if traza_proc is not None:
            traza_proc.kill()
        raise
    fallos += f + [str(x)[:300] for x in _lista(crudo.get("fallos"))]
    rutas = _lista(crudo.get("rutas"))
    puerta = _puerta(rutas)
    proc = crudo.get("proceso") if buscado else None

    objetivos: list[tuple[str, str]] = []
    for destino, papel in ([(puerta, "puerta de enlace")] if puerta else []) + \
            [(r, "referencia") for r in REFERENCIAS] + [(d, "pedido") for d in destinos] + \
            [(r, f"lo usa {buscado}") for r in _remotas(proc)]:
        if destino not in (x[0] for x in objetivos):
            objetivos.append((destino, papel))
    latencias = []
    ping = maquina.encontrar("ping.exe")
    if not ping:
        fallos.append("no encuentro ping.exe: sin latencias")
    else:
        lanzados = []
        for d, papel in objetivos:
            try:
                lanzados.append((d, papel, _lanzar([ping, "-n", str(PINGS), "-w", str(ESPERA_PING_MS), d])))
            except OSError as exc:
                fallos.append(f"no pude lanzar ping.exe a {d}: {exc}")
        for d, papel, p in lanzados:
            rc, salida, _ = _esperar(p, fin)
            r = leer_ping(_texto(salida))
            if rc is None:
                # Cortado en el tope: los que faltan no se perdieron, no
                # llegaron a salir. Esa pérdida no se puede defender (regla
                # dura 13), así que no se da.
                r["perdidos_pct"] = None
                r["nota"] = "no terminó a tiempo"
            latencias.append({"destino": d, "papel": papel} | r)

    traza = None
    if traza_proc is not None:
        rc, salida, _ = _esperar(traza_proc, fin)
        traza = {"destino": trazar, "saltos": leer_tracert(_texto(salida)), "completa": rc is not None}
        if rc is None:
            fallos.append(f"la traza a {trazar} no terminó en {TOPE_S} s: va lo que dio")

    return {"que": "red", "adaptadores": _lista(crudo.get("adaptadores")), "rutas": rutas, "puerta": puerta,
            "dns": _lista(crudo.get("dns")), "latencias": latencias, "proceso": proc, "traza": traza,
            "fallos": fallos, "segundos": round(_reloj() - t0, 1)}


# ─────────────────────────────── legible ───────────────────────────────

_SOLO_LECTURA = "Sólo lectura: no se cambió nada en la PC."


def _hora(iso: str) -> str:
    return a_local(iso) if iso else "?"


def _ms(x) -> str:
    """Una medida para leer: «*» sin respuesta, y el 0 de «<1 ms» otra vez
    como «<1», que «0 ms» no lo midió nadie (regla dura 13)."""
    return "*" if x is None else "<1" if x == 0 else f"{x}"


def _n(n: int, una: str, varias: str) -> str:
    return f"{n} {una if n == 1 else varias}"


def legible(d: dict) -> str:
    """El diagnóstico dicho en pocas líneas: lo que imprime la CLI y lo que
    recibe el secretario (sin volcar el JSON entero)."""
    return _legible_red(d) if d.get("que") == "red" else _legible_windows(d)


def _legible_windows(d: dict) -> str:
    out = [f"Windows, últimos {d.get('dias')} días ({d.get('segundos', '?')} s). {_SOLO_LECTURA}"]
    eq = d.get("equipo") or {}
    if eq:
        b, pl, w = eq.get("bios") or {}, eq.get("placa") or {}, eq.get("windows") or {}
        out.append(f"Equipo: {eq.get('cpu') or '?'} · placa {pl.get('fabricante') or '?'} {pl.get('modelo') or ''}"
                   f" · BIOS {b.get('version') or '?'} del {b.get('fecha') or '?'} ({b.get('fabricante') or '?'})")
        out.append(f"Windows: {w.get('nombre') or '?'} {w.get('version') or ''} · encendido desde "
                   f"{_hora(w.get('arranque') or '')}")
    p = d.get("pantallazos") or []
    out.append(f"Pantallazos: {len(p)}" if p else "Pantallazos: ninguno en estos días.")
    out += [f"  {_hora(x['hora'])}  {x['codigo']} {x['nombre']}".rstrip()
            + (f" — se cayó a las {x['cayo']} (según el 6008)" if x.get("cayo") else "") for x in p]
    if p:
        out.append("  (La primera hora es la de cuando volvió a arrancar, no la de la caída.)")
    ev = d.get("eventos") or []
    if ev:
        out.append(f"Eventos de apagado y arranque ({len(ev)}, el más nuevo primero):")
        for e in ev[:25]:
            cod = f" {e['codigo']}" if e.get("codigo") else ""
            out.append(f"  {_hora(e['hora'])}  {e['que']} ({e['id']}){cod} — {e['texto']}")
        if len(ev) > 25:
            out.append(f"  … y {len(ev) - 25} más")
    v = d.get("volcados") or []
    if v:
        out.append("Volcados (sin abrir):")
        out += [f"  {x['nombre']}  {x['bytes'] / 1024**2:.0f} MB  {_hora(x['fecha'])}" for x in v]
    for r in d.get("sin_permiso") or []:
        out.append(f"Sin permiso para listar {r}: hace falta ser administrador de Windows.")
    out += [f"No se pudo: {f}" for f in d.get("fallos") or []]
    return "\n".join(out)


def _legible_red(d: dict) -> str:
    out = [f"Red de la PC ({d.get('segundos', '?')} s). {_SOLO_LECTURA}"]
    ad = d.get("adaptadores") or []
    if ad:
        out.append("Adaptadores activos:")
        out += [f"  {a.get('nombre')} — {a.get('descripcion')}, {a.get('velocidad')}" for a in ad]
    rutas = [r for r in d.get("rutas") or [] if isinstance(r, dict)]
    if rutas:
        out.append("Salida a internet: " + "; ".join(
            f"{r.get('siguiente')} por {r.get('interfaz')} (métrica {r.get('metrica')})"
            for r in sorted(rutas, key=lambda r: int(r.get("metrica") or 0))))
    for x in d.get("dns") or []:
        out.append(f"DNS de {x.get('interfaz')}: {', '.join(_lista(x.get('servidores')))}")
    lat = d.get("latencias") or []
    if lat:
        out.append(f"Latencia ({PINGS} pings a cada uno):")
        for x in lat:
            if x.get("recibidos"):
                perdida = (f"{x['perdidos_pct']} % perdidos" if x.get("perdidos_pct") is not None
                           else f"pérdida sin medir ({x.get('nota') or 'no terminó'})")
                out.append(f"  {x['destino']} ({x['papel']}): mín {_ms(x['min'])} · media {_ms(x['media'])}"
                           f" · máx {_ms(x['max'])} ms · {perdida}")
            else:
                nota = f" — {x['nota']}" if x.get("nota") else ""
                out.append(f"  {x['destino']} ({x['papel']}): sin respuesta{nota}")
    pr = d.get("proceso")
    if pr:
        procs = _lista(pr.get("procesos"))
        if not procs:
            out.append(f"Proceso «{pr.get('buscado')}»: no hay ninguno corriendo con ese nombre.")
        else:
            nombres = sorted({str(x.get("nombre")) for x in procs})
            tcp, udp = _lista(pr.get("tcp")), _lista(pr.get("udp"))
            out.append(f"Proceso «{pr.get('buscado')}» ({', '.join(nombres)[:120]}; {len(procs)} en marcha): "
                       f"{_n(len(tcp), 'conexión TCP establecida', 'conexiones TCP establecidas')}, "
                       f"{_n(len(udp), 'puerto UDP abierto', 'puertos UDP abiertos')}.")
            out += [f"  TCP → {c.get('remota')}:{c.get('puerto')}" for c in tcp[:10]]
            if len(tcp) > 10:
                out.append(f"  … y {len(tcp) - 10} más")
            if udp:
                out.append("  De UDP Windows sólo da el puerto local: el servidor de un juego por UDP no se ve aquí.")
    tr = d.get("traza")
    if tr:
        out.append(f"Traza a {tr['destino']}" + ("" if tr.get("completa") else " (incompleta)") + ":")
        out += [f"  {s['salto']:>2}  {' '.join(_ms(m) for m in s['ms'])} ms  {s['ip'] or 'sin respuesta'}"
                for s in tr.get("saltos") or []]
    out += [f"No se pudo: {f}" for f in d.get("fallos") or []]
    return "\n".join(out)


# ─────────────────────────────── CLI ───────────────────────────────


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m hub.diagnostico",
                                 description="Diagnóstico de la PC con Windows y de su red, en sólo lectura.")
    sub = ap.add_subparsers(dest="que", required=True)
    w = sub.add_parser("windows", help="pantallazos, apagados, volcados y el equipo")
    w.add_argument("--dias", type=int, default=DIAS_POR_OMISION)
    r = sub.add_parser("red", help="adaptadores, ruta, DNS, latencias, un proceso y una traza")
    r.add_argument("--destino", action="append", default=[], help="IP o nombre; se puede repetir")
    r.add_argument("--proceso", help="nombre (o parte) de un proceso de Windows")
    r.add_argument("--trazar", help="IP o nombre al que hacer tracert")
    for p in (w, r):
        p.add_argument("--json", action="store_true", help="el resultado entero, en JSON")
    a = ap.parse_args(argv)
    try:
        d = windows(a.dias) if a.que == "windows" else red(a.destino, proceso=a.proceso, trazar=a.trazar)
    except (SinWindows, ValueError) as exc:
        print(exc, file=sys.stderr)
        return 2
    print(json.dumps(d, ensure_ascii=False, indent=2) if a.json else legible(d))
    return 0


if __name__ == "__main__":
    sys.exit(main())
