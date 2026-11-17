#!/usr/bin/env bash
# Arranca el puente en primer plano, sin systemd (WSL sin systemd, macOS).
# Ctrl+C lo para. Déjalo en su propia terminal (o en una ventana de tmux).
#
#   bash scripts/arrancar.sh
#
# Carga la contraseña del JetKVM del mismo archivo que usaría el servicio
# (~/.config/puente-kvm/entorno, o PUENTE_ENTORNO), y nada más.
set -euo pipefail
codigo="$(cd "$(dirname "$0")/.." && pwd -P)"
entorno="${PUENTE_ENTORNO:-$HOME/.config/puente-kvm/entorno}"
if [ -f "$entorno" ]; then
  if [ -n "$(find "$entorno" -perm /077 2>/dev/null)" ]; then
    echo "Ojo: $entorno lo pueden leer otros usuarios. Arréglalo con: chmod 600 $entorno" >&2
  fi
  # Se lee como lo lee systemd (CLAVE=valor, comillas envolventes fuera), NO
  # con `source`: una contraseña con $ o ` se expandiría o se ejecutaría.
  while IFS= read -r linea || [ -n "$linea" ]; do
    case "$linea" in '' | '#'*) continue ;; esac
    clave="${linea%%=*}"
    valor="${linea#*=}"
    [[ "$clave" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || continue
    if [[ "$valor" =~ ^\"(.*)\"$ ]] || [[ "$valor" =~ ^\'(.*)\'$ ]]; then valor="${BASH_REMATCH[1]}"; fi
    export "$clave=$valor"
  done < "$entorno"
fi
cd "$codigo"
echo "Puente en http://127.0.0.1:${PUENTE_PUERTO:-8794} (Ctrl+C para pararlo)"
exec uv run --frozen puente-kvm web
