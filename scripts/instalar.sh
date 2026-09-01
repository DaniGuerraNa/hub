#!/usr/bin/env bash
# Instala el hub en esta máquina. Idempotente: correrlo dos veces deja lo mismo.
#
# Lo que hace, y nada más:
#   1. comprueba el entorno (doctor.sh)
#   2. resuelve las dependencias de Python (uv sync)
#   3. crea HUB_HOME y siembra el registro SI NO EXISTE — nunca pisa el tuyo
#   4. genera los dos servicios de systemd con las rutas REALES de este clon
#   5. los arranca y verifica que el hub contesta
#
# No instala nada del sistema: si falta algo, lo dice y para. Instalar paquetes
# en la máquina de alguien es una acción con consecuencias, y se decide fuera.
#
#   --sin-servicios   hace todo menos systemd. Para probar una instalación en
#                     paralelo sin pisar la que ya tienes —los units se llaman
#                     igual y se sobreescribirían— y para máquinas sin
#                     `systemd --user`, donde el hub se arranca a mano.
set -euo pipefail

RAIZ=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
HUB_HOME=${HUB_HOME:-$HOME/.local/share/hub}
HUB_HOST=${HUB_HOST:-127.0.0.1}
HUB_PORT=${HUB_PORT:-8787}
UNIDADES=${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user
CON_SERVICIOS=1
[ "${1:-}" = "--sin-servicios" ] && CON_SERVICIOS=0

paso() { printf '\n\033[1m%s\033[0m\n' "$*"; }
bien() { printf '  ✓ %s\n' "$*"; }
mal()  { printf '  ✗ %s\n' "$*" >&2; }

paso "1/5 · Entorno"
if ! bash "$RAIZ/scripts/doctor.sh"; then
  mal "falta algo imprescindible; no sigo"
  exit 1
fi

paso "2/5 · Dependencias"
(cd "$RAIZ" && uv sync --quiet)
bien "entorno de Python listo"

paso "3/5 · Datos"
mkdir -p "$HUB_HOME"
bien "$HUB_HOME"
if [ -f "$HUB_HOME/projects.yml" ]; then
  bien "projects.yml ya existe — no se toca"
else
  cp "$RAIZ/projects.ejemplo.yml" "$HUB_HOME/projects.yml"
  bien "projects.yml sembrado desde el ejemplo — edítalo para declarar lo tuyo"
fi

paso "4/5 · Servicios"
if [ "$CON_SERVICIOS" -eq 0 ]; then
  bien "omitidos (--sin-servicios)"
  printf '    Arráncalo a mano cuando quieras:\n'
  printf '      cd %s && HUB_HOME=%s uv run uvicorn hub.web:app --host %s --port %s\n' \
         "$RAIZ" "$HUB_HOME" "$HUB_HOST" "$HUB_PORT"
  printf '\nListo. Datos en %s\n' "$HUB_HOME"
  exit 0
fi

# Las rutas se resuelven AHORA y se escriben dentro del unit. Cablearlas en el
# repo era lo que impedía instalar el hub en cualquier carpeta que no fuera
# ~/projects/hub, y no se veía hasta que fallaba en otra máquina.
UV=$(command -v uv)
mkdir -p "$UNIDADES"
for servicio in hub-web hub-snapshotter; do
  sed -e "s|@RAIZ@|$RAIZ|g" \
      -e "s|@HUB_HOME@|$HUB_HOME|g" \
      -e "s|@UV@|$UV|g" \
      -e "s|@PATH@|$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin|g" \
      -e "s|@HOST@|$HUB_HOST|g" \
      -e "s|@PUERTO@|$HUB_PORT|g" \
      "$RAIZ/scripts/$servicio.service.plantilla" > "$UNIDADES/$servicio.service"
  bien "$UNIDADES/$servicio.service"
done

systemctl --user daemon-reload
systemctl --user enable --now hub-web hub-snapshotter >/dev/null 2>&1
bien "arrancados y habilitados para el próximo inicio"

paso "5/5 · Comprobación"
# Arrancar no es funcionar: se espera a que conteste de verdad. Dar por bueno un
# `systemctl start` que devuelve 0 es la misma trampa que dar por enviado un
# mensaje que sigue en pantalla.
url="http://$HUB_HOST:$HUB_PORT"
for _ in $(seq 1 20); do
  codigo=$(curl -s -o /dev/null -w '%{http_code}' "$url/" || true)
  [ "$codigo" = "200" ] && break
  sleep 0.5
done
if [ "${codigo:-}" != "200" ]; then
  mal "el hub no contesta en $url (código ${codigo:-sin respuesta})"
  printf '    journalctl --user -u hub-web -n 40 --no-pager\n' >&2
  exit 1
fi

fallos=0
for r in / /trabajo /inventario /respaldo /servicios /conexiones /contexto; do
  c=$(curl -s -o /dev/null -w '%{http_code}' "$url$r" || true)
  [ "$c" = "200" ] || { mal "$r → $c"; fallos=1; }
done
[ "$fallos" -eq 0 ] && bien "las pantallas responden"

cat <<FIN

Listo. El hub está en $url

  Datos     $HUB_HOME
  Registro  $HUB_HOME/projects.yml   ← declara aquí tus proyectos
  Servicios systemctl --user status hub-web hub-snapshotter

Lo siguiente: abre Claude Code en esta carpeta y di «anexa mi proyecto», o edita
el registro a mano. La pantalla de inicio te guía si aún no tienes ninguno.
FIN
