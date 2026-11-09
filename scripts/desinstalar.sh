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

RAIZ=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
UNIDADES=${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user
# shellcheck source=lib/unidades.sh
. "$RAIZ/scripts/lib/unidades.sh"

# 🔴 Los datos están donde dice el servicio instalado, no donde diga el entorno
# de esta shell: con el `HUB_HOME` supuesto, `--datos` borraba una carpeta que
# no era y dejaba la de verdad (C-0114). Se lee ANTES de quitar los units.
HUB_HOME_ENTORNO=${HUB_HOME:-}
# Las copias diarias pueden ir fuera de HUB_HOME (`HUB_RESPALDO`): ésas no se
# borran con la carpeta, y el aviso tiene que decirlo (C-0186). Manda lo que
# diga un unit instalado, como con HUB_HOME (C-0114), y si no, el entorno;
# leído también antes de quitarlos. Un drop-in (`.service.d/`) no se lee: ahí
# sale la frase general.
RESPALDO=$( { sed -n 's/^Environment=HUB_RESPALDO=//p' "$UNIDADES"/hub-*.service 2>/dev/null || true; } | head -1)
RESPALDO=${RESPALDO:-${HUB_RESPALDO:-}}
if leer_unidad_instalada; then
  DE_DONDE="el del servicio instalado"
else
  HUB_HOME=${HUB_HOME_ENTORNO:-$HOME/.local/share/hub}
  DE_DONDE="no hay servicio instalado: el de HUB_HOME o el de por omisión"
fi

# La lista es la de `lib/unidades.sh`, la que instala (C-0115). Tenía su copia
# aquí y ya había divergido: los dos relés no estaban, así que desinstalar y
# volver a instalar arrastraba una unidad vieja apuntando a la ruta anterior.
# shellcheck disable=SC2086
systemctl --user disable --now $SERVICIOS_HUB >/dev/null 2>&1 || true
for servicio in $SERVICIOS_HUB; do rm -f "$UNIDADES/$servicio.service"; done
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
  if [ -z "$HUB_HOME" ] || [ "$HUB_HOME" = "/" ] || [ "$HUB_HOME" = "$HOME" ] || [ ! -d "$HUB_HOME" ]; then
    printf '  · «%s» no es una carpeta de datos del hub: no se borra nada\n' "$HUB_HOME"
    exit 0
  fi
  # Todo lo que se va, dicho antes de pedir el sí: el aviso nombraba sólo
  # «tus notas de slots», y con la carpeta se van también las copias de cada
  # día y la memoria del secretario (C-0114).
  printf '\n  Esto borra %s (%s), con todo lo que hay dentro:\n' "$HUB_HOME" "$DE_DONDE"
  for entrada in "$HUB_HOME"/*; do
    [ -e "$entrada" ] || continue
    nombre=$(basename "$entrada")
    case "$nombre" in
      hub.db-*) continue ;;
      hub.db) que="tus slots y sus notas, el canal, los programados, los encargos y las ideas del tablero" ;;
      respaldos) que="las copias de cada día de hub.db y de la memoria del secretario" ;;
      secretario) que="la memoria del secretario y sus ajustes" ;;
      projects.yml) que="tu registro de proyectos" ;;
      intercambio) que="lo que subiste o pegaste" ;;
      *) que="" ;;
    esac
    printf '    - %s%s\n' "$nombre" "${que:+ — $que}"
  done
  case "$RESPALDO" in
    "") printf '  Si tus copias diarias van a otra carpeta (HUB_RESPALDO), ésa no se toca.\n' ;;
    "$HUB_HOME"|"$HUB_HOME"/*) ;;
    *) printf '  Las copias diarias de %s (HUB_RESPALDO) están fuera y no se tocan: bórralas a mano si quieres.\n' "$RESPALDO" ;;
  esac
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
