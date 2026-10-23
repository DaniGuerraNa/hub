@echo off
rem Instala el agente de reuniones para tu usuario de Windows: prepara su
rem entorno, lo deja arrancando al iniciar sesion y lo lanza. Se puede repetir.
rem Sin acentos a proposito: la consola de Windows no siempre los pinta bien.
cd /d "%~dp0"
rem Recien instalado, uv puede no estar aun en el PATH de esta ventana (el
rem Explorador no siempre se entera): se busca tambien donde lo deja su instalador.
where uv >nul 2>nul
if errorlevel 1 if exist "%USERPROFILE%\.local\bin\uv.exe" set "PATH=%USERPROFILE%\.local\bin;%PATH%"
where uv >nul 2>nul
if errorlevel 1 (
  echo Falta uv para Windows. Instalalo en PowerShell con:
  echo   powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
  echo y vuelve a abrir este archivo.
  pause
  exit /b 1
)
uv sync
if errorlevel 1 (
  echo No se pudo preparar el entorno. Mira el error de arriba.
  pause
  exit /b 1
)
set "INICIO=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
> "%INICIO%\reuniones-agente.vbs" echo CreateObject("WScript.Shell").Run "cmd /c ""%~dp0iniciar.cmd""", 0, False
call "%~dp0iniciar.cmd"
echo.
echo Listo: el agente esta en marcha y arrancara solo al iniciar sesion.
echo Vuelve a la pantalla Reuniones del hub: en unos segundos dira "agente conectado".
pause
