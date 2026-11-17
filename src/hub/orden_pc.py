"""Una orden de PowerShell en el Windows del dueño (C-0240, decisión 404).

Lo que no cubren los guiones fijos de `hub.diagnostico` —«¿qué modelo son mis
monitores?», «¿qué tengo conectado por USB?»— el secretario lo pregunta con
una orden suya. Dos caminos, y el que elige no es el modelo sino el código:

- **`leer`**: sólo si la orden **mira el estado del sistema**. Lo decide
  `veredicto` sobre lo que dice el analizador del propio PowerShell
  (`Parser::ParseInput`), no sobre lo que el modelo diga de ella: cmdlets por
  nombre exacto (`CMDLETS_LECTURA`), clases de WMI de una lista, argumentos
  escritos tal cual (una ruta o una clase calculada se saltaría las
  comprobaciones), sin métodos, sin `>`, sin `$env:`, sin red
  (`-ComputerName`, rutas UNC), sin contenido de archivos (eso es
  `secretario.archivos`, decisión 336). Y corre en un PowerShell recortado:
  con los módulos cargados y **todo lo demás oculto** (lo que hace JEA), en
  `ConstrainedLanguage` y con el PATH vacío. El guion vuelve a comprobar, en
  el mismo proceso que la ejecuta, que cada comando está en la lista: medido
  el 10-nov, el recorte no impide llamar a un programa por su ruta
  (`C:\\…\\cmd.exe` corría), y esa segunda comprobación sí.
- **`cambiar`**: cualquier otra orden, en un PowerShell normal que arranca en
  la carpeta temporal de Windows. Sólo la llama `cambiar_en_pc` con el sí del
  dueño a esa orden exacta: ésa es la garantía.

Lo que no se acepta ni con su sí (`veredicto(...).nunca`): las carpetas de sus
proyectos (regla dura 16) o una que las contenga —con las rutas resueltas como
las vería Windows: relativas, `..`, `~`, comodines—, abrir puertos o el
cortafuegos (8), docker (12), volver a WSL —donde están el hub, sus bases y
las llaves—, cambiar de carpeta a mitad de orden, elevar a administrador y lo
codificado o calculado: el sí sólo vale si puede leer lo que va a correr.
**Es una red, no una garantía** (regla dura 22): una orden puede llegar a una
carpeta sin nombrarla. La garantía es que nada cambia sin su sí.

Los programas de lectura (`NATIVOS_LECTURA`) no pasan por PowerShell: si la
orden es sólo uno de ellos con unos argumentos fijos, se lanza tal cual, con
sus argumentos sueltos (regla dura 10), como `diagnostico` lanza `ping.exe`.
"""

from __future__ import annotations

import argparse
import base64
import json
import ntpath
import re
import subprocess
import sys
import time
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from . import diagnostico, maquina

#: El tope de una orden, lanzar PowerShell incluido. Por debajo del de
#: `diagnostico` y lejos de `motor.SIN_NOTICIAS_S`: el secretario espera
#: callado mientras tanto, y `ejecutar_aprobadas` corre en su bucle.
TOPE_S = 40
#: Lo que vuelve al modelo como mucho. El MCP corta en 60 000.
SALIDA_MAX = 12_000
#: Lo más larga que puede ser una orden: la tiene que leer entera antes de aprobarla.
ORDEN_MAX = 4000

#: Lo que se puede mirar, por nombre exacto, con el módulo que lo trae. Sólo
#: estado del sistema: aparatos, controladores, discos, red, servicios,
#: procesos, eventos y el registro. 🔴 No por familias (`Get-*`): `Get-Content`,
#: `Get-Clipboard` o `Get-Credential` también empiezan por `Get`. Y sin
#: `Select-String`: con una ruta por posición lee un archivo.
CMDLETS_LECTURA = {
    "ForEach-Object": "Microsoft.PowerShell.Core", "Where-Object": "Microsoft.PowerShell.Core",
    "Select-Object": "Microsoft.PowerShell.Utility", "Sort-Object": "Microsoft.PowerShell.Utility",
    "Group-Object": "Microsoft.PowerShell.Utility", "Measure-Object": "Microsoft.PowerShell.Utility",
    "Format-Table": "Microsoft.PowerShell.Utility", "Format-List": "Microsoft.PowerShell.Utility",
    "Format-Wide": "Microsoft.PowerShell.Utility", "Out-String": "Microsoft.PowerShell.Utility",
    "ConvertTo-Json": "Microsoft.PowerShell.Utility", "ConvertTo-Csv": "Microsoft.PowerShell.Utility",
    "Get-Date": "Microsoft.PowerShell.Utility", "Get-Culture": "Microsoft.PowerShell.Utility",
    "Get-Service": "Microsoft.PowerShell.Management", "Get-Process": "Microsoft.PowerShell.Management",
    "Get-ComputerInfo": "Microsoft.PowerShell.Management", "Get-HotFix": "Microsoft.PowerShell.Management",
    "Get-TimeZone": "Microsoft.PowerShell.Management", "Get-WmiObject": "Microsoft.PowerShell.Management",
    "Get-ItemProperty": "Microsoft.PowerShell.Management", "Get-ChildItem": "Microsoft.PowerShell.Management",
    "Get-WinEvent": "Microsoft.PowerShell.Diagnostics",
    "Get-CimInstance": "CimCmdlets",
    "Get-PnpDevice": "PnpDevice", "Get-PnpDeviceProperty": "PnpDevice",
    "Get-NetAdapter": "NetAdapter", "Get-NetAdapterStatistics": "NetAdapter",
    "Get-NetAdapterAdvancedProperty": "NetAdapter",
    "Get-NetIPAddress": "NetTCPIP", "Get-NetIPConfiguration": "NetTCPIP", "Get-NetRoute": "NetTCPIP",
    "Get-NetConnectionProfile": "NetConnection", "Get-DnsClientServerAddress": "DnsClient",
    "Get-Disk": "Storage", "Get-PhysicalDisk": "Storage", "Get-Volume": "Storage", "Get-Partition": "Storage",
    "Get-StorageReliabilityCounter": "Storage",
    "Get-ScheduledTask": "ScheduledTasks", "Get-ScheduledTaskInfo": "ScheduledTasks",
    "Get-Printer": "PrintManagement", "Get-AppxPackage": "Appx",
}
#: Los alias de siempre de esos mismos comandos: el modelo los escribe.
ALIAS_LECTURA = {
    "%": "ForEach-Object", "foreach": "ForEach-Object", "?": "Where-Object", "where": "Where-Object",
    "select": "Select-Object", "sort": "Sort-Object", "group": "Group-Object", "measure": "Measure-Object",
    "ft": "Format-Table", "fl": "Format-List", "fw": "Format-Wide",
    "gcim": "Get-CimInstance", "gwmi": "Get-WmiObject", "gps": "Get-Process", "ps": "Get-Process",
    "gsv": "Get-Service", "gp": "Get-ItemProperty", "gci": "Get-ChildItem", "ls": "Get-ChildItem",
    "dir": "Get-ChildItem",
}
_CANONICO = {**{c.lower(): c for c in CMDLETS_LECTURA}, **{a: c for a, c in ALIAS_LECTURA.items()}}

#: Los que sólo dan forma a lo ya leído: pueden llevar expresiones (una
#: propiedad calculada, `@{n=…;e={…}}`) porque lo que corre dentro lo miran las
#: demás reglas. Los otros, sólo valores escritos tal cual y bloques.
SOLO_FORMA = {"ForEach-Object", "Where-Object", "Select-Object", "Sort-Object", "Group-Object", "Measure-Object",
              "Format-Table", "Format-List", "Format-Wide", "Out-String", "ConvertTo-Json", "ConvertTo-Csv"}

#: Parámetros que llevan la orden a otra máquina o con otras credenciales, con
#: sus alias. En Windows no hay un espacio de red aparte: «sin red» sólo lo da esto.
PARAMETROS_FUERA = ("computername", "cn", "servername", "__server", "ipaddress", "pscomputername", "cimsession",
                    "session", "sessionoption", "credential", "connectionuri", "enableallprivileges", "asjob",
                    "throttlelimit")
#: Los que en un comando concreto leen archivos o llaman a métodos sin que se vea.
PARAMETROS_DE = {
    "ForEach-Object": ("membername", "argumentlist", "args"),
    "Get-WinEvent": ("path", "pspath"),
}
#: Lo que puede ir detrás de otro en una tubería al mirar, además de los de
#: `SOLO_FORMA`: el resto va el primero de la suya. 🔴 Lo que entra por la
#: tubería no pasa por ninguna regla —una cadena o un objeto con `Path` le da
#: la ruta a `Get-ChildItem`—, así que sólo se admite detrás de lo suyo.
SEGUROS_TRAS = {
    "Get-PnpDeviceProperty": {"Get-PnpDevice"}, "Get-NetAdapterStatistics": {"Get-NetAdapter"},
    "Get-NetAdapterAdvancedProperty": {"Get-NetAdapter"}, "Get-ScheduledTaskInfo": {"Get-ScheduledTask"},
    "Get-StorageReliabilityCounter": {"Get-PhysicalDisk", "Get-Disk"}, "Get-Partition": {"Get-Disk"},
    "Get-Volume": {"Get-Partition"},
}
#: Sólo el registro: con ruta de archivo, listarían o leerían el disco.
SOLO_REGISTRO = ("Get-ChildItem", "Get-ItemProperty")
_REGISTRO = ("hklm:", "hkcu:", "registry::", "microsoft.powershell.core\\registry::")

#: Las clases que se miran con `Get-CimInstance` y `Get-WmiObject`, por nombre
#: exacto. 🔴 No cualquiera: enumerar `Win32_Product` hace que Windows
#: Installer revise cada paquete, y `Win32_Process` (o su padre `CIM_Process`)
#: lleva la línea de órdenes de cada proceso, que puede llevar llaves (402).
CLASES_LECTURA = {
    "win32_videocontroller", "wmimonitorid", "wmimonitorbasicdisplayparams", "wmimonitorconnectionparams",
    "win32_desktopmonitor", "win32_pnpentity", "win32_pnpsigneddriver", "win32_usbhub", "win32_usbcontroller",
    "win32_keyboard", "win32_pointingdevice", "win32_sounddevice", "win32_diskdrive", "win32_diskpartition",
    "win32_logicaldisk", "win32_volume", "win32_cdromdrive", "win32_networkadapter",
    "win32_networkadapterconfiguration", "win32_bios", "win32_baseboard", "win32_processor",
    "win32_physicalmemory", "win32_computersystem", "win32_operatingsystem", "win32_battery",
    "win32_portablebattery", "win32_printer", "win32_fan", "win32_temperatureprobe",
    "msacpi_thermalzonetemperature", "win32_systemdriver", "win32_quickfixengineering", "win32_serialport",
    "win32_systemenclosure", "win32_cachememory", "msft_physicaldisk", "msft_disk", "msft_volume",
    "msft_partition", "msft_storagereliabilitycounter", "msft_netadapter", "msft_netipaddress",
}
ESPACIOS_LECTURA = {"root\\cimv2", "root\\wmi", "root\\microsoft\\windows\\storage", "root\\standardcimv2"}
#: Los parámetros que se admiten al mirar con WMI, y si llevan valor detrás.
_PARAMETROS_CIM = {"namespace": True, "classname": True, "class": True, "filter": True, "property": True,
                   "query": True, "shallow": False, "keyonly": False}
_CIM = ("Get-CimInstance", "Get-WmiObject")

#: Programas que sólo miran, y SÓLO con estos argumentos: con otros, varios
#: cambian algo (`ipconfig /release`, `nvidia-smi -pl`), se quedan en bucle
#: (`nvidia-smi -l`) o enseñan una llave (`netsh wlan show profile key=clear`).
#: Lo que empieza por «-» se compara tal cual (`-L` no es `-l`); lo demás,
#: sin mayúsculas, como lo lee Windows.
NATIVOS_LECTURA = {
    "ipconfig": [(), ("/all",)],
    "systeminfo": [()],
    "nvidia-smi": [(), ("-q",), ("-L",)],
    "driverquery": [(), ("/v",), ("/si",)],
    "getmac": [(), ("/v",)],
    "whoami": [()],
    "tasklist": [(), ("/svc",)],
    "pnputil": [("/enum-devices",), ("/enum-devices", "/connected"), ("/enum-devices", "/problem"),
                ("/enum-drivers",)],
    "powercfg": [("/a",), ("/l",), ("/getactivescheme",), ("/devicequery", "wake_armed")],
    "netsh": [("wlan", "show", "interfaces"), ("wlan", "show", "drivers"), ("interface", "show", "interface"),
              ("interface", "ipv4", "show", "config")],
}

_A_WSL = "volver a WSL llega al hub, a sus bases y a tus llaves"
_OTRA_CARPETA = "cambia de carpeta a mitad de la orden: escribe las rutas enteras, para que se vea adónde llega"
#: Comandos que no se aceptan nunca, ni con su sí: por su nombre y, si la
#: orden cambia algo, también como palabra de un argumento (`cmd /c wsl …`).
NUNCA_COMANDOS = {
    "docker": "docker se acciona de uno en uno, desde su pantalla del hub",
    "docker-compose": "docker se acciona de uno en uno, desde su pantalla del hub",
    "tailscale": "la red privada y lo que se publica en ella no se tocan desde aquí",
    "wsl": _A_WSL, "bash": _A_WSL,
    "powershell": "otra consola dentro esconde lo que corre", "pwsh": "otra consola dentro esconde lo que corre",
    "invoke-expression": "ejecuta un texto: lo que corre no es lo que aprobaste",
    "iex": "ejecuta un texto: lo que corre no es lo que aprobaste",
    "invoke-command": "ejecuta en otra sesión o máquina", "icm": "ejecuta en otra sesión o máquina",
    "new-pssession": "abre una sesión en otra máquina", "enter-pssession": "abre una sesión en otra máquina",
    "runas": "pide administrador", "new-netnat": "abre la red de la máquina a otras",
    "add-netnatstaticmapping": "abre un puerto de la máquina",
    "set-location": _OTRA_CARPETA, "cd": _OTRA_CARPETA, "sl": _OTRA_CARPETA, "chdir": _OTRA_CARPETA,
    "push-location": _OTRA_CARPETA, "pushd": _OTRA_CARPETA, "pop-location": _OTRA_CARPETA, "popd": _OTRA_CARPETA,
}
_NUNCA_PREFIJOS = (("ubuntu", _A_WSL), ("debian", _A_WSL), ("kali", _A_WSL), ("opensuse", _A_WSL))
#: Se buscan en lo escrito ya sin escapes (las cadenas como las lee
#: PowerShell) y en el texto tal cual.
_NUNCA_TEXTO = (
    ("wsl$", _A_WSL), ("wsl.localhost", _A_WSL),
    ("frombase64string", "lo codificado no se puede leer antes de aprobarlo"),
    ("-encodedcommand", "lo codificado no se puede leer antes de aprobarlo"),
    ("setcurrentdirectory", _OTRA_CARPETA),
    ("runas", "pide administrador"),
)
#: Sólo si cambia algo: mirar el estado de su servicio sí se puede.
_NUNCA_SI_CAMBIA = (("docker", NUNCA_COMANDOS["docker"]), ("tailscale", NUNCA_COMANDOS["tailscale"]),
                    ("portproxy", "abre un puerto de la máquina"),
                    ("firewall", "el cortafuegos no se toca desde aquí"))


class NoEsLectura(ValueError):
    """La orden no se puede correr sin preguntar. Lleva el veredicto."""

    def __init__(self, v: "Veredicto"):
        super().__init__(v.explicacion())
        self.veredicto = v


class Prohibida(ValueError):
    """La orden no se acepta ni con el sí del dueño."""


@dataclass
class Veredicto:
    lectura: bool
    nunca: str | None = None
    motivos: list[str] = field(default_factory=list)
    comandos: list[str] = field(default_factory=list)
    #: Si es un programa de lectura solo: su nombre y sus argumentos tal cual.
    nativo: tuple[str, tuple[str, ...]] | None = None

    def explicacion(self) -> str:
        if self.nunca:
            return f"no se puede: {self.nunca}"
        if self.lectura:
            return "sólo mira"
        return "no es sólo mirar: " + "; ".join(self.motivos)


@dataclass
class Resultado:
    codigo: int | None
    salida: str
    errores: list[str]
    recortada: bool
    segundos: float


# ─────────────────────────────── el guion ───────────────────────────────

# 🔴 Fijo: los datos —la orden, el modo, las listas— le llegan por la entrada
# estándar, en base64, y la orden dentro otra vez en base64. Nunca se
# interpolan en su texto, y no ocupan la línea de órdenes de Windows (32 767
# caracteres, que con `-EncodedCommand` una orden de unos 2 800 ya no cabía).
#
# Tres modos: `analizar` devuelve lo que ve el analizador; `leer` lo vuelve a
# mirar EN ESTE MISMO PROCESO, se niega si algo no está en `permitidos` y lo
# corre en el PowerShell recortado; `cambiar` lo corre en uno normal que
# arranca en la carpeta temporal: arrancar en la del usuario dejaba que una
# orden sin rutas llegara a todo lo que hay debajo, proyectos incluidos.
GUION = r"""
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$d = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String([Console]::In.ReadToEnd().Trim())) | ConvertFrom-Json
$orden = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String([string]$d.orden))
$tokens = $null; $fallos = $null
$ast = [System.Management.Automation.Language.Parser]::ParseInput($orden, [ref]$tokens, [ref]$fallos)
function Elemento($tipo, $texto, $pegado, $valores) {
  [pscustomobject]@{ tipo = $tipo; nombre = ''; texto = [string]$texto; pegado = $pegado; valores = @($valores) }
}
$comandos = @(foreach ($c in $ast.FindAll({ $args[0] -is [System.Management.Automation.Language.CommandAst] }, $true)) {
  $elementos = @(foreach ($e in @($c.CommandElements | Select-Object -Skip 1)) {
    if ($e -is [System.Management.Automation.Language.CommandParameterAst]) {
      $p = Elemento 'parametro' $e.Extent.Text ($null -ne $e.Argument) @()
      $p.nombre = $e.ParameterName
      $p
    } elseif ($e -is [System.Management.Automation.Language.ScriptBlockExpressionAst]) {
      Elemento 'bloque' '' $false @()
    } elseif ($e -is [System.Management.Automation.Language.StringConstantExpressionAst]) {
      Elemento 'constante' $e.Value $false @()
    } elseif ($e -is [System.Management.Automation.Language.ConstantExpressionAst]) {
      Elemento 'numero' $e.Value $false @()
    } elseif ($e -is [System.Management.Automation.Language.ArrayLiteralAst] -and
              -not @($e.Elements | Where-Object { $_ -isnot [System.Management.Automation.Language.ConstantExpressionAst] }).Count) {
      Elemento 'lista' $e.Extent.Text $false @($e.Elements | ForEach-Object { [string]$_.Value })
    } else {
      Elemento 'expresion' $e.Extent.Text $false @()
    }
  })
  $posicion = 0; $previo = ''
  if ($c.Parent -is [System.Management.Automation.Language.PipelineAst]) {
    $posicion = $c.Parent.PipelineElements.IndexOf($c)
    if ($posicion -gt 0) {
      $antes = $c.Parent.PipelineElements[$posicion - 1]
      if ($antes -is [System.Management.Automation.Language.CommandAst]) { $previo = [string]$antes.GetCommandName() }
    }
  }
  [pscustomobject]@{
    nombre = $c.GetCommandName()
    constante = ($c.CommandElements[0] -is [System.Management.Automation.Language.StringConstantExpressionAst])
    elementos = $elementos; posicion = $posicion; previo = $previo
  }
})
$metodos = @($ast.FindAll({ $args[0] -is [System.Management.Automation.Language.InvokeMemberExpressionAst] }, $true) | ForEach-Object { $_.Member.Extent.Text })
$redirecciones = @($ast.FindAll({ $args[0] -is [System.Management.Automation.Language.FileRedirectionAst] }, $true)).Count
$variables = @($ast.FindAll({ $args[0] -is [System.Management.Automation.Language.VariableExpressionAst] }, $true) | ForEach-Object {
  [pscustomobject]@{ nombre = $_.VariablePath.UserPath; unidad = [string]$_.VariablePath.DriveName; esparcida = $_.Splatted } })
$asignaciones = @($ast.FindAll({ $args[0] -is [System.Management.Automation.Language.AssignmentStatementAst] }, $true) | ForEach-Object {
  if ($_.Left -is [System.Management.Automation.Language.VariableExpressionAst] -and -not $_.Left.VariablePath.DriveName) { 'variable' } else { $_.Left.Extent.Text } })
$cadenas = @($ast.FindAll({ $args[0] -is [System.Management.Automation.Language.StringConstantExpressionAst] -or $args[0] -is [System.Management.Automation.Language.ExpandableStringExpressionAst] }, $true) | ForEach-Object { [string]$_.Value })
$hechos = [pscustomobject]@{
  errores = @($fallos | ForEach-Object { $_.Message })
  comandos = $comandos; metodos = $metodos; redirecciones = $redirecciones; variables = $variables
  asignaciones = $asignaciones; cadenas = $cadenas
  usos = $ast.UsingStatements.Count; requisitos = ($null -ne $ast.ScriptRequirements)
  base = [pscustomobject]@{ temp = [string]$env:TEMP; perfil = [string]$env:USERPROFILE; onedrive = [string]$env:OneDrive }
}
function Correr($rs) {
  $ps = [PowerShell]::Create(); $ps.Runspace = $rs
  [void]$ps.AddScript($orden).AddCommand('Out-String').AddParameter('Width', 160)
  $salida = ''; $err = @()
  try { $salida = (@($ps.Invoke()) -join '') } catch { $err += $_.Exception.Message }
  foreach ($x in $ps.Streams.Error) { $err += $x.ToString() }
  $recortada = $salida.Length -gt [int]$d.max
  if ($recortada) { $salida = $salida.Substring(0, [int]$d.max) }
  [pscustomobject]@{ salida = $salida; errores = $err; recortada = $recortada }
}
if ($d.modo -eq 'analizar') {
  [pscustomobject]@{ hechos = $hechos } | ConvertTo-Json -Depth 6 -Compress
} elseif ($d.modo -eq 'leer') {
  # El candado, en el mismo proceso que corre la orden.
  $permitidos = @($d.permitidos | ForEach-Object { $_.ToLowerInvariant() })
  $malos = @()
  if ($hechos.errores.Count) { $malos += 'no se entiende la orden' }
  $forma = @($d.solo_forma | ForEach-Object { $_.ToLowerInvariant() })
  foreach ($c in $comandos) {
    if (-not $c.constante -or -not $c.nombre -or $permitidos -notcontains $c.nombre.ToLowerInvariant()) { $malos += ('comando ' + [string]$c.nombre) }
    elseif ($c.posicion -gt 0 -and $forma -notcontains $c.nombre.ToLowerInvariant()) {
      $tras = @($d.tras.($c.nombre.ToLowerInvariant()))
      if (-not $c.previo -or $tras -notcontains $c.previo.ToLowerInvariant()) { $malos += ('recibe por la tubería ' + [string]$c.nombre) }
    }
  }
  if ($metodos.Count) { $malos += 'llama a métodos' }
  if ($redirecciones) { $malos += 'redirige a un archivo' }
  if (@($variables | Where-Object { $_.esparcida -or $_.unidad }).Count) { $malos += 'variables de entorno o esparcidas' }
  if ($malos.Count) {
    [pscustomobject]@{ cerradura = $malos } | ConvertTo-Json -Compress
  } else {
    $iss = [System.Management.Automation.Runspaces.InitialSessionState]::CreateDefault2()
    $iss.ImportPSModule([string[]]@($d.modulos))
    $iss.LanguageMode = 'ConstrainedLanguage'
    $rs = [System.Management.Automation.Runspaces.RunspaceFactory]::CreateRunspace($iss)
    $rs.Open()
    foreach ($c in $rs.SessionStateProxy.InvokeCommand.GetCommands('*', 'Alias,Function,Filter,Cmdlet', $true)) {
      if ($permitidos -notcontains $c.Name.ToLowerInvariant()) { $c.Visibility = 'Private' }
    }
    $rs.SessionStateProxy.Path.SetLocation('HKLM:\') | Out-Null
    $env:PATH = ''
    Correr $rs | ConvertTo-Json -Compress
  }
} elseif ($d.modo -eq 'cambiar') {
  $rs = [System.Management.Automation.Runspaces.RunspaceFactory]::CreateRunspace()
  $rs.Open()
  $rs.SessionStateProxy.Path.SetLocation($env:TEMP) | Out-Null
  Correr $rs | ConvertTo-Json -Compress
}
"""
#: El guion ya codificado para `-EncodedCommand`: es fijo, se calcula una vez.
_GUION_CODIFICADO = base64.b64encode(GUION.encode("utf-16-le")).decode()


def _entrada(datos: dict) -> bytes:
    """Lo que el guion lee por la entrada: el JSON de los datos, en base64."""
    return base64.b64encode(json.dumps(datos, ensure_ascii=False).encode("utf-8"))


def _lanzar_guion(datos: dict, fin: float) -> dict:
    ps = maquina.encontrar("powershell.exe")
    if not ps:
        raise diagnostico.SinWindows("No encuentro Windows debajo de esta máquina (falta powershell.exe).")
    # Desde una carpeta de Windows: desde una de WSL, PowerShell arranca en
    # una ruta UNC y los programas de consola se quejan (medido el 10-nov).
    proc = subprocess.Popen([ps, "-NoProfile", "-NonInteractive", "-EncodedCommand", _GUION_CODIFICADO],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            cwd=str(Path(ps).parent))
    rc, salida, error = diagnostico.esperar(proc, fin, entrada=_entrada(datos))
    if rc is None:
        raise TimeoutError(f"PowerShell no terminó en {TOPE_S} s")
    texto = diagnostico.texto_consola(salida)
    linea = next((x for x in reversed(texto.splitlines()) if x.strip().startswith("{")), "")
    try:
        return json.loads(linea)
    except ValueError:
        motivo = " ".join(diagnostico.texto_consola(error).split())[:300] or "salida vacía"
        raise RuntimeError(f"PowerShell no devolvió lo esperado (código {rc}): {motivo}") from None


def _datos(modo: str, comando: str) -> dict:
    return {"modo": modo, "orden": base64.b64encode(comando.encode("utf-8")).decode(), "max": SALIDA_MAX,
            "permitidos": sorted(set(CMDLETS_LECTURA) | set(ALIAS_LECTURA)),
            "modulos": sorted(set(CMDLETS_LECTURA.values())),
            "solo_forma": sorted(SOLO_FORMA | {a for a, c in ALIAS_LECTURA.items() if c in SOLO_FORMA}),
            "tras": {c.lower(): sorted(x.lower() for x in previos) for c, previos in SEGUROS_TRAS.items()}}


# ─────────────────────────────── el veredicto ───────────────────────────────


def _lista(x) -> list:
    if x is None:
        return []
    return x if isinstance(x, list) else [x]


def _nombre(n: str) -> str:
    """El nombre de un comando como se compara: sin carpeta, sin `.exe`, en minúsculas."""
    n = re.split(r"[\\/]", (n or "").strip())[-1].lower()
    return n[:-4] if n.endswith(".exe") else n


def _windows(ruta: str) -> str | None:
    """`/mnt/c/Users/x` → `c:\\users\\x`. Lo que no está en un disco de Windows,
    None: se llega sólo por `\\\\wsl$`, que ya se niega."""
    m = re.fullmatch(r"/mnt/([a-zA-Z])(/.*)?", ruta.rstrip("/"))
    if not m:
        return None
    return f"{m.group(1).lower()}:{(m.group(2) or '').replace('/', chr(92))}".lower()


class SinVetadas(RuntimeError):
    """No se sabe qué carpetas proteger: el registro, o un patrón suyo, no se lee."""


def rutas_vetadas() -> list[str]:
    """Las carpetas de los proyectos registrados, en su forma de Windows (16).

    `SinVetadas` si no se pueden saber todas. Devolver la lista vacía era
    fallar abierto (EJE-26): la red desaparecía justo cuando el registro
    fallaba, y con OneDrive en EIO un patrón ilegible dejaba sus repos sin veto.
    Por eso el registro se lee `estricto`."""
    from . import registry
    out = []
    try:
        for p in registry.cargar(estricto=True):
            for r in p.todas_las_rutas():
                w = _windows(str(r))
                if w:
                    out.append(w)
    except Exception as exc:  # noqa: BLE001 — cualquier fallo es «no sé», y «no sé» cierra
        raise SinVetadas(f"no puedo saber qué carpetas proteger ({str(exc)[:200] or type(exc).__name__})") from exc
    return sorted(set(out))


def _valores(hechos: dict) -> list[str]:
    """Todo lo escrito tal cual en la orden, ya sin escapes: cadenas,
    argumentos, listas y nombres de comandos."""
    out = [str(x) for x in _lista(hechos.get("cadenas"))]
    for c in _lista(hechos.get("comandos")):
        out.append(str(c.get("nombre") or ""))
        for e in _lista(c.get("elementos")):
            out.append(str(e.get("texto") or ""))
            out += [str(v) for v in _lista(e.get("valores"))]
    return [v for v in out if v.strip()]


def _como_ruta(valor: str, base: dict) -> str | None:
    """Un valor como la ruta de Windows a la que llegaría, resuelta contra la
    carpeta donde corre la orden (la temporal), con `~`, `$HOME`,
    `$env:USERPROFILE` y `$env:OneDrive` puestos, `..` resuelto y cortada en
    el primer comodín: `C:\\Users\\*\\x` abarca todo `C:\\Users`."""
    t = valor.strip().strip("'\"").replace("/", "\\").lower()
    perfil = str(base.get("perfil") or "").lower()
    onedrive = str(base.get("onedrive") or "").lower()
    temp = str(base.get("temp") or "").lower()
    for var, real in (("${env:userprofile}", perfil), ("$env:userprofile", perfil), ("$home", perfil),
                      ("${env:onedrive}", onedrive), ("$env:onedrive", onedrive)):
        if real:
            t = t.replace(var, real)
    if t.startswith("~") and perfil:
        t = perfil + t[1:]
    for pre in ("\\\\?\\unc\\", "\\\\.\\unc\\"):
        if t.startswith(pre):
            t = "\\\\" + t[len(pre):]
    for pre in ("\\\\?\\", "\\\\.\\"):
        if t.startswith(pre):
            t = t[len(pre):]
    t = re.sub(r"^(microsoft\.powershell\.core\\)?filesystem::", "", t)
    if t.startswith("\\\\"):
        return None                      # red: lo mira `_motivos_lectura`, y WSL `_NUNCA_TEXTO`
    if not re.match(r"[a-z]:", t):
        if not temp:
            return None
        t = (temp[:2] + t) if t.startswith("\\") else (temp.rstrip("\\") + "\\" + t)
    t = ntpath.normpath(t)
    partes = t.split("\\")
    corte = next((i for i, p in enumerate(partes) if re.search(r"[*?\[]", p)), None)
    if corte is not None:
        t = "\\".join(partes[:corte]) or partes[0]
    return t.rstrip("\\") or t


def _nunca(hechos: dict, comando: str, lectura: bool, vetadas: list[str]) -> str | None:
    comandos = _lista(hechos.get("comandos"))
    for c in comandos:
        if not c.get("constante") or not c.get("nombre"):
            return "el nombre de un comando se calcula al correr: no se puede leer qué corre"
        n = _nombre(c["nombre"])
        if n in NUNCA_COMANDOS:
            return NUNCA_COMANDOS[n]
        for pre, porque in _NUNCA_PREFIJOS:
            if n.startswith(pre):
                return porque
    valores = _valores(hechos)
    texto = " ".join([comando, *valores, *map(str, _lista(hechos.get("metodos")))]).lower().replace("/", "\\")
    for trozo, porque in _NUNCA_TEXTO:
        if trozo in texto:
            return porque
    if not lectura:
        for trozo, porque in _NUNCA_SI_CAMBIA:
            if trozo in texto:
                return porque
        # Un programa vetado pasado como argumento de otro (`cmd /c wsl …`).
        for v in valores:
            for palabra in re.split(r"[\s;|&,()\"']+", v):
                n = _nombre(palabra)
                if n in NUNCA_COMANDOS:
                    return NUNCA_COMANDOS[n]
                for pre, porque in _NUNCA_PREFIJOS:
                    if n.startswith(pre):
                        return porque
        # Las carpetas de sus proyectos, y las que las contienen, como las
        # vería Windows. Sólo si cambia algo: mirar no llega a los archivos, y
        # un `'C:'` en un filtro de discos no es tocar nada.
        base = hechos.get("base") or {}
        for v in valores:
            r = _como_ruta(v, base)
            if not r:
                continue
            for vet in vetadas:
                if r == vet or vet.startswith(r + "\\") or r.startswith(vet + "\\"):
                    return f"toca la carpeta de un proyecto tuyo, o una que la contiene ({vet}): ahí sólo escribe su sesión"
        from .secretario.archivos import CARPETAS_LLAVE
        for parte in re.split(r"[\\:]+", texto):
            if parte.strip() in CARPETAS_LLAVE:
                return f"toca una carpeta de llaves ({parte.strip()})"
    if _lista(hechos.get("errores")):
        return "no se entiende la orden: " + "; ".join(str(e) for e in _lista(hechos["errores"]))[:200]
    return None


def _candidatos(param: str, lista) -> list[str]:
    """`-Comp` es `-ComputerName`: PowerShell acepta cualquier prefijo único."""
    p = (param or "").lower()
    if not p:
        return []
    return [v for v in lista if v.startswith(p)]


def _motivos_cim(canon: str, elementos: list[dict]) -> list[str]:
    """Con WMI sólo se miran las clases de `CLASES_LECTURA`, en sus espacios, y
    sólo con los parámetros de `_PARAMETROS_CIM`."""
    motivos, clases, espacio, posicionales = [], [], "root\\cimv2", 0
    i = 0
    while i < len(elementos):
        e = elementos[i]
        if e.get("tipo") == "parametro":
            nombre = str(e.get("nombre") or "").lower()
            cand = [nombre] if nombre in _PARAMETROS_CIM else _candidatos(nombre, _PARAMETROS_CIM)
            if cand and all(c in ("class", "classname") for c in cand):
                cand = ["class"]
            if len(cand) != 1:
                motivos.append(f"{canon} con «{e.get('texto')}» no es de sólo mirar")
                i += 1
                continue
            if not _PARAMETROS_CIM[cand[0]]:
                i += 1
                continue
            valor = elementos[i + 1] if i + 1 < len(elementos) else {}
            i += 2
            if valor.get("tipo") not in ("constante", "lista"):
                motivos.append(f"{canon} {e.get('texto')} con un valor que no está escrito tal cual")
                continue
            texto = str(valor.get("texto") or "")
            if cand[0] == "namespace":
                espacio = texto.lower().replace("/", "\\")
            elif cand[0] in ("class", "classname"):
                clases.append(texto)
            elif cand[0] == "query":
                m = re.match(r"\s*select\s+.+?\s+from\s+(\w+)", texto, re.I | re.S)
                if m:
                    clases.append(m.group(1))
                else:
                    motivos.append(f"no entiendo la consulta de {canon}")
            continue
        if e.get("tipo") in ("constante", "lista") and posicionales == 0:
            clases.append(str(e.get("texto") or ""))
        elif e.get("tipo") in ("constante", "lista") and canon == "Get-WmiObject" and posicionales == 1:
            pass                                # su segundo posicional son las propiedades
        else:
            motivos.append(f"{canon} con «{e.get('texto')}» no es de sólo mirar")
        posicionales += 1
        i += 1
    if espacio not in ESPACIOS_LECTURA:
        motivos.append(f"el espacio de WMI «{espacio}» no está entre los de sólo mirar")
    if not clases:
        motivos.append(f"{canon} sin una clase de las de sólo mirar")
    for c in clases:
        if c.lower() not in CLASES_LECTURA:
            motivos.append(f"la clase «{c}» no está entre las de sólo mirar")
    return motivos


def _igual(args: tuple[str, ...], forma: tuple[str, ...]) -> bool:
    return len(args) == len(forma) and all(
        a == f if f.startswith("-") else a.lower() == f.lower() for a, f in zip(args, forma))


def _motivos_lectura(hechos: dict) -> tuple[list[str], tuple[str, tuple[str, ...]] | None]:
    motivos: list[str] = []
    comandos = _lista(hechos.get("comandos"))
    # Un programa de lectura, solo y con sus argumentos fijos.
    if len(comandos) == 1 and _nombre(comandos[0].get("nombre") or "") in NATIVOS_LECTURA:
        c = comandos[0]
        n = _nombre(c["nombre"])
        elementos = _lista(c.get("elementos"))
        args = tuple(str(e.get("texto") or "") for e in elementos)
        extra = (_lista(hechos.get("metodos")) or hechos.get("redirecciones") or _lista(hechos.get("variables"))
                 or _lista(hechos.get("asignaciones")))
        if not extra and all(e.get("tipo") in ("constante", "parametro") and not e.get("pegado") for e in elementos) \
                and any(_igual(args, f) for f in NATIVOS_LECTURA[n]):
            return [], (n, args)
        return [f"«{c['nombre']}» sólo se admite solo y con {_formas(n)}"], None
    for c in comandos:
        nombre = c.get("nombre") or ""
        if not c.get("constante") or not nombre:
            motivos.append(f"el nombre del comando no está escrito ({nombre or 'calculado'})")
            continue
        canon = _CANONICO.get(nombre.lower())
        if not canon:
            motivos.append(f"«{nombre}» no es de sólo mirar")
            continue
        elementos = _lista(c.get("elementos"))
        if int(c.get("posicion") or 0) > 0 and canon not in SOLO_FORMA:
            previo = _CANONICO.get(str(c.get("previo") or "").lower())
            if previo not in SEGUROS_TRAS.get(canon, ()):
                motivos.append(f"«{nombre}» recibiría por la tubería lo que tiene delante: al mirar, va el primero")
        for e in elementos:
            if e.get("tipo") == "parametro":
                if e.get("pegado"):
                    motivos.append(f"«{e.get('texto')}»: escribe el valor separado del parámetro")
                elif _candidatos(e.get("nombre"), PARAMETROS_FUERA):
                    motivos.append(f"«{e.get('texto')}» lleva la orden a otra máquina o con otras credenciales")
                elif _candidatos(e.get("nombre"), PARAMETROS_DE.get(canon, ())):
                    motivos.append(f"«{canon} {e.get('texto')}» lee archivos o llama a métodos")
            elif e.get("tipo") == "expresion" and canon not in SOLO_FORMA:
                motivos.append(f"«{e.get('texto')}» se calcula al correr: al mirar sólo valen valores escritos tal cual")
        if canon == "ForEach-Object" and any(e.get("tipo") in ("constante", "expresion", "lista", "numero")
                                             for e in elementos):
            motivos.append("ForEach-Object sólo con un bloque { … }: con un nombre llama a ese método")
        if canon in _CIM:
            motivos += _motivos_cim(canon, elementos)
        if canon in SOLO_REGISTRO:
            for e in elementos:
                for t in ([e.get("texto")] if e.get("tipo") == "constante" else
                          _lista(e.get("valores")) if e.get("tipo") == "lista" else []):
                    tl = str(t or "").lower()
                    if re.search(r"[:\\/~]", tl) and not tl.startswith(_REGISTRO):
                        motivos.append(f"{canon} sólo mira el registro (HKLM:\\ o HKCU:\\), no «{t}»")
    metodos = _lista(hechos.get("metodos"))
    if metodos:
        motivos.append("llama a " + ", ".join(f"«{m}»" for m in metodos[:5]))
    if hechos.get("redirecciones"):
        motivos.append("escribe en un archivo (>)")
    for v in _lista(hechos.get("variables")):
        if v.get("esparcida"):
            motivos.append(f"pasa parámetros escondidos (@{v.get('nombre')})")
        elif (v.get("unidad") or "").lower() == "env" or str(v.get("nombre") or "").lower().startswith("env:"):
            motivos.append("lee variables de entorno")
    for a in _lista(hechos.get("asignaciones")):
        if a != "variable":
            motivos.append(f"cambia «{a}»")
    if hechos.get("usos") or hechos.get("requisitos"):
        motivos.append("carga módulos (using / #requires)")
    for t in _lista(hechos.get("cadenas")):
        tl = str(t).lower()
        if tl.startswith(("\\\\", "//")):
            motivos.append(f"va a otra máquina por red («{t}»)")
        elif re.match(r"\s*env:", tl):
            motivos.append("lee variables de entorno")
        elif "win32_process" in tl or "commandline" in tl:
            motivos.append("lee la línea de órdenes de los procesos, que puede llevar llaves")
    return list(dict.fromkeys(motivos)), None


def _formas(n: str) -> str:
    return " o ".join("«" + " ".join((n, *f)) + "»" for f in NATIVOS_LECTURA[n])


def veredicto(hechos: dict, comando: str, vetadas: list[str] | None = None) -> Veredicto:
    """Qué es una orden, a partir de lo que vio el analizador. Puro: los tests
    lo prueban sin Windows."""
    motivos, nativo = _motivos_lectura(hechos)
    lectura = not motivos and not _lista(hechos.get("errores"))
    sin_vetadas = None
    if vetadas is None:
        # Sólo cambiar las necesita: mirar no llega a los archivos y sigue
        # aunque el registro no se lea.
        try:
            vetadas = [] if lectura else rutas_vetadas()
        except SinVetadas as exc:
            vetadas, sin_vetadas = [], str(exc)
    nunca = _nunca(hechos, comando, lectura, vetadas) or sin_vetadas
    nombres = [str(c.get("nombre") or "") for c in _lista(hechos.get("comandos"))]
    return Veredicto(lectura=lectura and not nunca, nunca=nunca, motivos=motivos, comandos=nombres, nativo=nativo)


# ─────────────────────────────── lo que se llama ───────────────────────────────


def _validar(comando: str) -> str:
    comando = (comando or "").replace("\r\n", "\n").strip()
    if not comando:
        raise ValueError("falta la orden")
    if len(comando) > ORDEN_MAX:
        raise ValueError("la orden es demasiado larga para leerla antes de aprobarla")
    # Lo que no se ve en la pantalla haría aprobar algo distinto de lo que corre.
    for ch in comando:
        cat = unicodedata.category(ch)
        if (cat == "Cc" and ch not in "\n\t") or cat in ("Cf", "Zl", "Zp") or (cat == "Zs" and ch != " "):
            raise ValueError("la orden lleva caracteres invisibles o de control: lo que verías no sería lo que corre")
    return comando


def analizar(comando: str, fin: float | None = None) -> dict:
    """Lo que ve el analizador de PowerShell en la orden. No la ejecuta."""
    fin = fin or time.monotonic() + TOPE_S
    return _lanzar_guion(_datos("analizar", _validar(comando)), fin).get("hechos") or {}


def clasificar(comando: str) -> Veredicto:
    """Sólo analiza: qué es y por qué. No ejecuta nada."""
    comando = _validar(comando)
    return veredicto(analizar(comando), comando)


def _nativo(nombre: str, args: tuple[str, ...], fin: float, t0: float) -> Resultado:
    exe = maquina.encontrar(f"{nombre}.exe")
    if not exe:
        raise FileNotFoundError(f"{nombre}.exe no está en este Windows")
    proc = subprocess.Popen([exe, *args], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            cwd=str(Path(exe).parent))
    rc, salida, error = diagnostico.esperar(proc, fin)
    texto = diagnostico.texto_consola(salida)
    errores = [x for x in [" ".join(diagnostico.texto_consola(error).split())[:500]] if x]
    if rc is None:
        errores.append(f"no terminó en {TOPE_S} s")
    return Resultado(rc, texto[:SALIDA_MAX], errores, len(texto) > SALIDA_MAX, round(time.monotonic() - t0, 1))


def _resultado(r: dict, t0: float) -> Resultado:
    return Resultado(0 if not _lista(r.get("errores")) else 1, str(r.get("salida") or "").replace("\r", ""),
                     [str(e) for e in _lista(r.get("errores"))], bool(r.get("recortada")),
                     round(time.monotonic() - t0, 1))


def leer(comando: str) -> Resultado:
    """Corre una orden que sólo mira. `NoEsLectura` si no lo es, sin correrla."""
    comando = _validar(comando)
    t0 = time.monotonic()
    fin = t0 + TOPE_S
    v = veredicto(analizar(comando, fin), comando)
    if not v.lectura:
        raise NoEsLectura(v)
    if v.nativo:
        return _nativo(*v.nativo, fin, t0)
    r = _lanzar_guion(_datos("leer", comando), fin)
    if r.get("cerradura"):
        # Python la dio por lectura y el guion no: se dice, no se arregla solo.
        raise NoEsLectura(Veredicto(False, motivos=[f"el candado la paró: {', '.join(_lista(r['cerradura']))}"]))
    return _resultado(r, t0)


def cambiar(comando: str) -> Resultado:
    """Corre una orden cualquiera. Sólo la llama `cambiar_en_pc`, con el sí del
    dueño a esta orden exacta. `Prohibida` si es de las que nunca."""
    comando = _validar(comando)
    t0 = time.monotonic()
    fin = t0 + TOPE_S
    v = veredicto(analizar(comando, fin), comando)
    if v.nunca:
        raise Prohibida(v.nunca)
    return _resultado(_lanzar_guion(_datos("cambiar", comando), fin), t0)


def legible(r: Resultado) -> str:
    partes = [r.salida.rstrip() or "(no escribió nada)"]
    if r.recortada:
        partes.append(f"[recortado a {SALIDA_MAX} caracteres]")
    if r.errores:
        partes.append("Errores: " + " | ".join(r.errores)[:1500])
    partes.append(f"({r.segundos} s)")
    return "\n".join(partes)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m hub.orden_pc",
                                 description="Clasificar o leer con una orden de PowerShell en el Windows de debajo.")
    ap.add_argument("modo", choices=("clasificar", "leer"))
    ap.add_argument("orden")
    a = ap.parse_args(argv)
    try:
        if a.modo == "clasificar":
            print(clasificar(a.orden).explicacion())
        else:
            print(legible(leer(a.orden)))
    except (NoEsLectura, Prohibida, ValueError, TimeoutError, RuntimeError, diagnostico.SinWindows) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
