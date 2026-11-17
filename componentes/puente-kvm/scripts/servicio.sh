#!/usr/bin/env bash
# El servicio de usuario del puente (systemd). La unidad se genera aquí, con la
# carpeta real de este clon y el uv que se encuentre: el repositorio no lleva
# ninguna ruta fija y no se reescribe al instalar. Funciona igual desde
# ~/projects/puente-kvm que desde <otro-repo>/componentes/puente-kvm.
#
#   bash scripts/servicio.sh unidad      # enseña la unidad que instalaría, sin tocar nada
#   bash scripts/servicio.sh instalar    # la escribe en ~/.config/systemd/user y arranca el puente
#   bash scripts/servicio.sh reiniciar | estado | registro | quitar
#
# Sin systemd (WSL sin systemd, macOS): bash scripts/arrancar.sh
set -euo pipefail
codigo="$(cd "$(dirname "$0")/.." && pwd -P)"
nombre="${PUENTE_SERVICIO:-puente-kvm}"
unidad="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user/$nombre.service"
entorno="${PUENTE_ENTORNO:-$HOME/.config/puente-kvm/entorno}"

generar() {
  local uv
  uv="$(command -v uv || true)"
  if [ -z "$uv" ]; then
    echo "No encuentro uv en el PATH: instálalo (https://docs.astral.sh/uv/) y repite." >&2
    exit 1
  fi
  cat <<UNIDAD
# Generada por scripts/servicio.sh desde $codigo: no la edites, vuelve a instalar.
[Unit]
Description=Puente KVM (Claude Code y un Mac por JetKVM)

[Service]
WorkingDirectory=$codigo
# La contraseña del JetKVM no va aquí: va en este archivo, fuera del repositorio y con permisos 600.
EnvironmentFile=-$entorno
# El PATH de quien instaló: bajo systemd no está ~/.local/bin, y sin él no se
# encuentran claude ni uv al abrir la terminal de Claude.
Environment="PATH=$PATH"
UNIDAD
  for v in PUENTE_PUERTO PUENTE_HOME PUENTE_TRABAJO PUENTE_ENTORNO; do
    if [ -n "${!v:-}" ]; then echo "Environment=\"$v=${!v}\""; fi
  done
  cat <<UNIDAD
ExecStart=$uv run --frozen puente-kvm web
Restart=on-failure
# Al pararlo (stop, restart) sale con 143 por SIGTERM: es un final normal, no un fallo.
SuccessExitStatus=143

[Install]
WantedBy=default.target
UNIDAD
}

case "${1:-}" in
  unidad) generar ;;
  instalar)
    contenido="$(generar)"
    mkdir -p "$(dirname "$unidad")" "$(dirname "$entorno")"
    printf '%s\n' "$contenido" > "$unidad.tmp" && mv "$unidad.tmp" "$unidad"
    [ -f "$entorno" ] || install -m 600 /dev/null "$entorno"
    systemctl --user daemon-reload
    systemctl --user enable --now "$nombre"
    echo "Puente en http://127.0.0.1:${PUENTE_PUERTO:-8794} (unidad: $unidad)"
    ;;
  reiniciar)
    systemctl --user restart "$nombre"
    # La conversación de Claude vive en tmux, fuera del servicio, a propósito: sigue
    # abierta, y con ella su servidor MCP con el código de antes.
    echo "Si has actualizado el puente: en su terminal, Conversaciones → Reabrir, para que Claude cargue el código nuevo."
    ;;
  estado) systemctl --user status "$nombre" --no-pager ;;
  registro) journalctl --user -u "$nombre" -n 100 --no-pager ;;
  quitar)
    systemctl --user disable --now "$nombre" || true
    rm -f "$unidad"
    systemctl --user daemon-reload
    systemctl --user reset-failed "$nombre" 2>/dev/null || true
    # La conversación de Claude abierta (nace fuera del servicio y le sobreviviría):
    # sólo la del puente, por su nombre exacto, en el servidor de tmux del usuario.
    # Claude Code ya la tiene guardada.
    sesion="${PUENTE_SESION_CLAUDE:-puente-claude}"
    tmux_orden=(tmux)
    if [ -n "${PUENTE_TMUX_SOCKET:-}" ]; then tmux_orden=(tmux -L "$PUENTE_TMUX_SOCKET"); fi
    if "${tmux_orden[@]}" has-session -t "=$sesion" 2>/dev/null; then
      "${tmux_orden[@]}" kill-session -t "=$sesion" || true
    fi
    echo "Quitado. La carpeta de trabajo, con lo leído del Mac, y los datos del puente se quedan: bórralos tú si quieres."
    ;;
  *) echo "uso: $0 unidad|instalar|reiniciar|estado|registro|quitar"; exit 1 ;;
esac
