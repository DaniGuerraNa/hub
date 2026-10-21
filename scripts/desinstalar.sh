#!/usr/bin/env bash
# Quita los servicios del hub. NO borra tus datos salvo que lo pidas.
#
#   bash scripts/desinstalar.sh           servicios fuera, datos intactos
#   bash scripts/desinstalar.sh --datos   además borra HUB_HOME
#
# Los datos no se van por defecto porque en HUB_HOME viven cosas que no están
# en ningún otro sitio y no se reconstruyen escaneando: los slots y sus notas,
# el canal, los programados y los encargos (ver conocimiento/06-problemas.md).
set -euo pipefail

HUB_HOME=${HUB_HOME:-$HOME/.local/share/hub}
UNIDADES=${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user

# Los cuatro, y los dos relés no estaban: `instalar.sh` los escribe y esto los
# dejaba atrás, así que desinstalar y volver a instalar arrastraba una unidad
# vieja apuntando a la ruta anterior. Salió al añadir `hub-encargos`.
SERVICIOS="hub-web hub-snapshotter hub-canal hub-encargos"
# shellcheck disable=SC2086
systemctl --user disable --now $SERVICIOS >/dev/null 2>&1 || true
for servicio in $SERVICIOS; do rm -f "$UNIDADES/$servicio.service"; done
systemctl --user daemon-reload
printf '  ✓ servicios detenidos y eliminados\n'

# El enlace de `hub` que puso `sembrar-asistente.sh` (decisión 278), sólo si es
# el suyo: un `hub` que apunte a otro sitio no lo creó el hub y no se toca.
ENLACE=${HUB_BIN:-$HOME/.local/bin}/hub
if [ -L "$ENLACE" ]; then
  ASISTENTE=$(dirname "$(dirname "$(readlink "$ENLACE")")")
  if head -1 "$ASISTENTE/CLAUDE.md" 2>/dev/null | grep -q '^# CLAUDE.md — el asistente'; then
    rm -f "$ENLACE"
    printf '  ✓ comando hub quitado de %s\n' "$ENLACE"
  fi
fi

if [ "${1:-}" = "--datos" ]; then
  printf '\n  Esto borra %s, con tus notas de slots dentro.\n' "$HUB_HOME"
  read -r -p '  Escribe «borrar» para confirmar: ' respuesta
  if [ "$respuesta" = "borrar" ]; then
    rm -rf "$HUB_HOME"
    printf '  ✓ %s borrado\n' "$HUB_HOME"
  else
    printf '  · no se ha borrado nada\n'
  fi
else
  printf '  · tus datos siguen en %s (usa --datos para borrarlos)\n' "$HUB_HOME"
fi
