#!/usr/bin/env bash
# Deja el lector de WhatsApp en Windows (decisión 331). Se corre desde WSL.
#
#   bash instalar.sh extension    # copia + registra el anfitrión para Chrome
#   bash instalar.sh escritorio   # copia + abre el puerto de depuración SÓLO a WhatsApp.Root.exe
#   bash instalar.sh quitar       # borra las dos entradas del registro (los archivos se quedan)
#
# Los archivos van al disco D si existe (`HUB_WA_WINDOWS` manda), porque es
# donde se instala lo de esta máquina. Nada de esto toca la cuenta de
# WhatsApp: vincular la app o WhatsApp Web lo hace la persona, con el QR.
set -euo pipefail

AQUI="$(cd "$(dirname "$0")" && pwd)"
COMPONENTE="$(dirname "$AQUI")"
HUB_HOME="${HUB_HOME:-$HOME/.local/share/hub}"
if [[ -n "${HUB_WA_WINDOWS:-}" ]]; then DESTINO="$HUB_WA_WINDOWS"
elif [[ -d /mnt/d ]]; then DESTINO=/mnt/d/hub/whatsapp-lector
else DESTINO="$(wslpath "$(cmd.exe /c 'echo %LOCALAPPDATA%' 2>/dev/null | tr -d '\r')")/hub/whatsapp-lector"
fi
PS=/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe
NOMBRE=com.hub.whatsapp_lector
PUERTO="${HUB_WA_CDP:-9333}"

ps() { (cd /mnt/c && "$PS" -NoProfile -NonInteractive -Command "$1"); }

copiar() {
    mkdir -p "$DESTINO/extension" "$HUB_HOME/secretario/whatsapp"
    cp "$AQUI"/{pagina.js,escritor.js,anfitrion.js,escritorio.js} "$COMPONENTE/formato.js" "$DESTINO/"
    cp "$AQUI"/extension/* "$AQUI/pagina.js" "$DESTINO/extension/"
    local datos; datos="$(wslpath -w "$HUB_HOME/secretario/whatsapp")"
    printf '{"destino": %s}\n' "$(printf '%s' "$datos" | python3 -c 'import json,sys; print(json.dumps(sys.stdin.read()))')" > "$DESTINO/config.json"
    echo "Copiado en $(wslpath -w "$DESTINO")"
}

extension() {
    copiar
    local win id node
    win="$(wslpath -w "$DESTINO")"
    id="$(cat "$AQUI/extension/ID")"
    node="$(ps '(Get-Command node -ErrorAction SilentlyContinue).Source' | tr -d '\r')"
    [[ -n "$node" ]] || { echo "Falta Node en Windows (https://nodejs.org, 22 o más)"; exit 1; }
    printf '@echo off\r\n"%s" "%%~dp0anfitrion.js"\r\n' "$node" > "$DESTINO/anfitrion.bat"
    python3 - "$DESTINO/nativo.json" "$win\\anfitrion.bat" "$id" <<'PY'
import json, sys
json.dump({"name": "com.hub.whatsapp_lector", "description": "Lector de WhatsApp para el hub",
           "path": sys.argv[2], "type": "stdio", "allowed_origins": [f"chrome-extension://{sys.argv[3]}/"]},
          open(sys.argv[1], "w"), indent=1)
PY
    ps "New-Item -Force -Path 'HKCU:\\Software\\Google\\Chrome\\NativeMessagingHosts\\$NOMBRE' -Value '$win\\nativo.json' | Out-Null"
    cat <<FIN

Listo. Falta lo tuyo, en Chrome:
  1. chrome://extensions → activa «Modo de desarrollador».
  2. «Cargar descomprimida» → elige $win\\extension
     (su id tiene que ser $id).
  3. Abre https://web.whatsapp.com y, si no está vinculado, escanea el QR.
FIN
}

escritorio() {
    copiar
    ps "New-Item -Force -Path 'HKCU:\\Software\\Policies\\Microsoft\\Edge\\WebView2\\AdditionalBrowserArguments' | Out-Null; Set-ItemProperty -Path 'HKCU:\\Software\\Policies\\Microsoft\\Edge\\WebView2\\AdditionalBrowserArguments' -Name 'WhatsApp.Root.exe' -Value '--remote-debugging-port=$PUERTO'"
    local win node; win="$(wslpath -w "$DESTINO")"
    node="$(ps '(Get-Command node -ErrorAction SilentlyContinue).Source' | tr -d '\r')"
    [[ -n "$node" ]] || { echo "Falta Node en Windows (https://nodejs.org, 22 o más)"; exit 1; }
    printf '@echo off\r\n"%s" "%%~dp0escritorio.js"\r\n' "$node" > "$DESTINO/escritorio.cmd"
    cat <<FIN

Listo. Falta lo tuyo:
  1. Cierra la app de WhatsApp del todo (también del área de notificaciones) y ábrela:
     el puerto sólo se abre al arrancar.
  2. Si no está vinculada, vincúlala con el QR.
  3. Arranca el lector: doble clic en $win\\escritorio.cmd (o déjamelo a mí).
FIN
}

quitar() {
    ps "Remove-Item -ErrorAction SilentlyContinue -Path 'HKCU:\\Software\\Google\\Chrome\\NativeMessagingHosts\\$NOMBRE'; Remove-ItemProperty -ErrorAction SilentlyContinue -Path 'HKCU:\\Software\\Policies\\Microsoft\\Edge\\WebView2\\AdditionalBrowserArguments' -Name 'WhatsApp.Root.exe'"
    echo "Quitadas las entradas del registro. Los archivos siguen en $DESTINO."
}

case "${1:-}" in
    extension) extension ;;
    escritorio) escritorio ;;
    quitar) quitar ;;
    *) sed -n '2,8p' "$0"; exit 2 ;;
esac
