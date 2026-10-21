#!/usr/bin/env bash
# Pone al día una instalación del hub. Un solo comando, en la carpeta del clon:
#
#   bash scripts/actualizar.sh
#
# Lo que hace, en orden, y por qué cada paso (decisión 286):
#   1. comprueba que el clon puede avanzar sin perder nada tuyo
#   2. baja la versión publicada (sólo si avanza en línea recta)
#   3. resuelve dependencias y pasa el doctor
#   4. aplica los pasos propios de cada versión que cruces (scripts/migraciones)
#   5. regenera los servicios —con TU puerto y TUS datos— y reinicia los que
#      estaban en marcha
#   6. pone al día los archivos del asistente, si lo tienes
#   7. comprueba que el hub contesta, apunta la versión y te dice qué cambió
#
# `git pull` y reiniciar —lo que se documentaba antes de la 0.2.0— hace el 2 y
# medio 5: deja el código nuevo corriendo con los servicios y el asistente de
# la versión anterior. El hub lo detecta y lo dice en todas las pantallas.
#
#   --sin-bajar    no hace `git pull`: para quien ya bajó el código a mano, o
#                  desarrolla el hub en este clon
#
# Tus datos (`HUB_HOME`) no se tocan salvo lo que diga una migración, y la base
# tiene su copia diaria (decisión 277). Si algo falla, para ahí y lo dice: la
# versión no se apunta como instalada hasta el final, así que volver a correrlo
# retoma.
set -euo pipefail

RAIZ=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
UNIDADES=${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user
BAJAR=1
for arg in "$@"; do
  case "$arg" in
    --sin-bajar) BAJAR=0 ;;
    *) printf 'opción desconocida: %s\n' "$arg" >&2; exit 2 ;;
  esac
done

paso() { printf '\n\033[1m%s\033[0m\n' "$*"; }
bien() { printf '  ✓ %s\n' "$*"; }
mal()  { printf '  ✗ %s\n' "$*" >&2; }
version() { (cd "$RAIZ" && HUB_HOME="$HUB_HOME" uv run --quiet python -m hub.version "$@"); }

# shellcheck source=lib/unidades.sh
. "$RAIZ/scripts/lib/unidades.sh"

# Con servicios, lo instalado manda: el puerto y la carpeta de datos se leen de
# los units, no se suponen. Sin ellos, de las variables de siempre.
CON_SERVICIOS=0
if systemctl --user show-environment >/dev/null 2>&1 && leer_unidad_instalada; then
  CON_SERVICIOS=1
else
  HUB_HOME=${HUB_HOME:-$HOME/.local/share/hub}
  HUB_HOST=${HUB_HOST:-127.0.0.1}
  HUB_PORT=${HUB_PORT:-8787}
fi
export HUB_HOME

paso "1/7 · El clon"
cd "$RAIZ"
if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
  mal "hay cambios sin guardar en archivos del hub:"
  git status --short --untracked-files=no >&2
  printf '    guárdalos o descártalos antes; actualizar encima los mezclaría con los nuevos\n' >&2
  exit 1
fi
rama=$(git rev-parse --abbrev-ref HEAD)
bien "rama $rama, sin cambios locales"
[ "$rama" = "main" ] || printf '    · no es main: se actualiza lo que haya en «%s»\n' "$rama"

paso "2/7 · Bajar la versión"
if [ "$BAJAR" -eq 1 ]; then
  antes_guion=$(sha256sum "$RAIZ/scripts/actualizar.sh" | cut -d' ' -f1)
  if ! git pull --ff-only --tags; then
    mal "no avanza en línea recta: tu clon tiene commits que el publicado no"
    printf '    mira «git log origin/%s..HEAD»; no se mezcla nada automáticamente\n' "$rama" >&2
    exit 1
  fi
  # 🔴 Si lo que bajó trae otro actualizar.sh, sigue el nuevo: el que está
  # corriendo es el de la versión anterior y no conoce sus pasos.
  if [ "$(sha256sum "$RAIZ/scripts/actualizar.sh" | cut -d' ' -f1)" != "$antes_guion" ]; then
    bien "el actualizador también cambió: sigue el de la versión nueva"
    exec bash "$RAIZ/scripts/actualizar.sh" --sin-bajar
  fi
  bien "código al día"
else
  bien "omitido (--sin-bajar)"
fi

paso "3/7 · Dependencias y entorno"
uv sync --quiet
bien "entorno de Python listo"
if ! bash "$RAIZ/scripts/doctor.sh" >/dev/null 2>&1; then
  bash "$RAIZ/scripts/doctor.sh" || true
  mal "al entorno le falta algo imprescindible; no sigo"
  exit 1
fi
bien "doctor sin faltas"

nueva=$(version codigo)
antes=$(version instalada)
if [ -z "$antes" ]; then
  bien "instalación anterior al protocolo de versiones: se pone al día hasta la $nueva"
else
  bien "de la $antes a la $nueva"
fi

paso "4/7 · Pasos de versión"
pasos=$(version migraciones "$antes" "$nueva" "$RAIZ/scripts/migraciones")
if [ -z "$pasos" ]; then
  bien "ninguno que aplicar"
else
  while IFS= read -r guion; do
    printf '  → %s\n' "$(basename "$guion" .sh)"
    if ! RAIZ="$RAIZ" HUB_HOME="$HUB_HOME" bash "$guion"; then
      mal "falló el paso de la $(basename "$guion" .sh); la versión NO se apunta"
      printf '    arregla lo que diga arriba y vuelve a correr: bash scripts/actualizar.sh --sin-bajar\n' >&2
      exit 1
    fi
  done <<< "$pasos"
fi

paso "5/7 · Servicios"
if [ "$CON_SERVICIOS" -eq 1 ]; then
  generar_unidades
  systemctl --user daemon-reload
  # Sólo los que estaban en marcha: actualizar no enciende el canal ni los
  # encargos de quien no los configuró, ni apaga los de quien sí.
  for servicio in $SERVICIOS_HUB; do
    if systemctl --user is-active --quiet "$servicio"; then
      systemctl --user restart "$servicio"
      bien "$servicio reiniciado"
    fi
  done
else
  bien "sin servicios de systemd: reinicia tú el hub (bash scripts/arrancar.sh --parar y otra vez)"
fi

paso "6/7 · Asistente"
asiento=$(uv run --quiet python -c "
from hub import registry
print(next((p.asiento for p in registry.cargar() if p.tipo == 'asistente' and p.asiento), ''))
" 2>/dev/null || true)
if [ -n "$asiento" ] && [ -d "$asiento" ]; then
  bash "$RAIZ/scripts/sembrar-asistente.sh" --refrescar "$asiento"
else
  bien "no hay asistente declarado: nada que poner al día"
fi

paso "7/7 · Comprobación"
if [ "$CON_SERVICIOS" -eq 1 ]; then
  url="http://$HUB_HOST:$HUB_PORT"
  codigo=""
  for _ in $(seq 1 40); do
    codigo=$(curl -s -o /dev/null -w '%{http_code}' "$url/guia" || true)
    [ "$codigo" = "200" ] && break
    sleep 0.5
  done
  if [ "$codigo" != "200" ]; then
    mal "el hub no contesta en $url (código ${codigo:-sin respuesta}); la versión NO se apunta"
    printf '    journalctl --user -u hub-web -n 40 --no-pager\n' >&2
    exit 1
  fi
  bien "el hub contesta en $url"
fi
version registrar "$nueva"
bien "instalada la $nueva"

novedades=$(version novedades "$antes" "$nueva" "$RAIZ/CHANGELOG.md")
if [ -n "$novedades" ]; then
  printf '\n\033[1mQué cambió\033[0m\n\n%s\n' "$novedades"
fi
printf '\nListo. Si alguna pantalla se ve rara, recarga con Ctrl+Shift+R.\n'
