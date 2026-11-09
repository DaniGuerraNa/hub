# El BOM de este archivo es a propósito: sin él, PowerShell 5 lo lee como ANSI y los acentos salen rotos.
<#
  Levanta WSL al encender Windows, sin que nadie inicie sesión, y lo mantiene
  encendido: con él arrancan los servicios del hub. Es para el hub en una
  máquina sin monitor (INSTALAR.md, «El hub en una máquina aparte»).

  Se ejecuta UNA vez, en PowerShell abierto como administrador, con la cuenta
  de Windows que usa WSL:

      powershell -ExecutionPolicy Bypass -File arrancar-sin-sesion.ps1
      powershell -ExecutionPolicy Bypass -File arrancar-sin-sesion.ps1 -Distro Ubuntu-24.04

  El nombre de la distro lo da `wsl -l -v`. Volver a ejecutarlo reemplaza la
  tarea; quitarla: Unregister-ScheduledTask -TaskName "Hub - levantar WSL al arrancar"

  Por qué así (medido con apagones de verdad en la máquina donde nació el hub):
  - S4U: la tarea corre al encender con tu usuario y SIN guardar tu contraseña.
  - `sleep infinity` y no `true`: WSL apaga la distro unos 16 s después de
    quedarse sin ninguna sesión abierta por wsl.exe. Con `true` el hub subía
    entero y a los 16 s WSL lo apagaba.
  - El bucle: si la VM cae (un `wsl --shutdown`, una actualización) vuelve sola.
    4 s de espera y no más: con 10, el relevo llegaba casi al límite de esos 16.
  - Sin límite de tiempo: el de fábrica de una tarea son 72 h, y al tercer día
    Windows la pararía y WSL se apagaría con ella.

  Lo que esto NO hace, y la máquina necesita para volver sola:
  - encenderse al volver la luz: es la BIOS («Restore on AC power loss» o
    «AC BACK» → Power On / Always On);
  - que Tailscale conecte sin sesión: tailscale set --unattended=true
  Lo que falte lo dice el hub en Máquina → Salud.
#>
param(
  [string]$Distro = "Ubuntu",
  [string]$Nombre = "Hub - levantar WSL al arrancar"
)
$ErrorActionPreference = 'Stop'

wsl.exe -d $Distro -e true
if ($LASTEXITCODE -ne 0) {
  throw "No hay una distro «$Distro» en WSL. Mira el nombre con: wsl -l -v"
}

$usuario = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$bucle = "while (`$true) { wsl.exe -d $Distro -e sleep infinity; Start-Sleep -Seconds 4 }"
$accion = New-ScheduledTaskAction -Execute "powershell.exe" `
  -Argument "-NoProfile -WindowStyle Hidden -Command `"$bucle`""
$disparo = New-ScheduledTaskTrigger -AtStartup
$quien = New-ScheduledTaskPrincipal -UserId $usuario -LogonType S4U -RunLevel Limited
$ajustes = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) `
  -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable

Register-ScheduledTask -TaskName $Nombre -Action $accion -Trigger $disparo `
  -Principal $quien -Settings $ajustes -Force | Out-Null
Start-ScheduledTask -TaskName $Nombre

Write-Output "Listo: «$Nombre» levantará WSL ($Distro) al encender, como $usuario, sin iniciar sesión."
Write-Output "Pruébalo apagando y encendiendo sin entrar en Windows: el hub debe contestar desde otro aparato."
