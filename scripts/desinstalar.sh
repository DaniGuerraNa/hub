#!/usr/bin/env bash
# Quita los servicios del hub. NO borra tus datos salvo que lo pidas.
#
#   bash scripts/desinstalar.sh           servicios fuera, datos intactos
#   bash scripts/desinstalar.sh --datos   además borra HUB_HOME
#
# Los datos no se van por defecto porque en HUB_HOME viven las notas de los
# slots, que son lo único del hub que no está en ningún otro sitio: no se
# reconstruyen escaneando, a diferencia del resto de la base.
set -euo pipefail

HUB_HOME=${HUB_HOME:-$HOME/.local/share/hub}
UNIDADES=${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user

systemctl --user disable --now hub-web hub-snapshotter >/dev/null 2>&1 || true
rm -f "$UNIDADES/hub-web.service" "$UNIDADES/hub-snapshotter.service"
systemctl --user daemon-reload
printf '  ✓ servicios detenidos y eliminados\n'

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
