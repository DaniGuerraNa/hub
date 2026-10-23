@echo off
rem Arranca el agente de reuniones sin ventana. El hub al que llama:
rem El hub de siempre (8787). Hasta el 22-oct apuntaba al 8788, la rama de pruebas.
set REUNIONES_HUB=http://127.0.0.1:8787
cd /d "%~dp0"
tasklist /FI "WINDOWTITLE eq reuniones-agente" 2>nul | find /i "pythonw" >nul && exit /b
start "reuniones-agente" .venv\Scripts\pythonw.exe agente.py
