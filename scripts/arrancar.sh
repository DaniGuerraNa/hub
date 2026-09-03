#!/usr/bin/env bash
# Arranca el hub a mano: la web Y el snapshotter, en segundo plano.
#
#   bash scripts/arrancar.sh          # arranca los dos
#   bash scripts/arrancar.sh --parar  # los para
#
# Es lo que hace systemd cuando está; sin él (un contenedor, un Linux sin
# systemd de usuario, WSL antes de activarlo) esto lo sustituye. 🔴 Los DOS:
# la primera instalación en limpio (3-sep) arrancó sólo la web, y como el
# snapshotter es quien relee `projects.yml`, el hub no vio el primer proyecto
# hasta reiniciarlo. Arrancar no es funcionar.
set -euo pipefail
RAIZ=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
HUB_HOME=${HUB_HOME:-$HOME/.local/share/hub}
HUB_HOST=${HUB_HOST:-127.0.0.1}
HUB_PORT=${HUB_PORT:-8787}
LOGS="$HUB_HOME/logs"
mkdir -p "$LOGS"

parar() {
  for p in web snapshotter; do
    if [ -f "$LOGS/$p.pid" ] && kill -0 "$(cat "$LOGS/$p.pid")" 2>/dev/null; then
      kill "$(cat "$LOGS/$p.pid")" && printf '  ✓ %s parado\n' "$p"
    fi
    rm -f "$LOGS/$p.pid"
  done
}

if [ "${1:-}" = "--parar" ]; then parar; exit 0; fi

parar >/dev/null 2>&1 || true
cd "$RAIZ"
HUB_HOME="$HUB_HOME" nohup uv run uvicorn hub.web:app --host "$HUB_HOST" --port "$HUB_PORT" \
  > "$LOGS/web.log" 2>&1 & echo $! > "$LOGS/web.pid"
HUB_HOME="$HUB_HOME" nohup uv run python -m hub.snapshotter \
  > "$LOGS/snapshotter.log" 2>&1 & echo $! > "$LOGS/snapshotter.pid"

# Arrancar no es funcionar: se espera a que la web conteste de verdad.
url="http://$HUB_HOST:$HUB_PORT"
for _ in $(seq 1 30); do
  codigo=$(curl -s -o /dev/null -w '%{http_code}' "$url/" || true)
  [ "$codigo" = "200" ] && break
  sleep 0.5
done
if [ "${codigo:-}" != "200" ]; then
  printf '  ✗ la web no contesta en %s: mira %s\n' "$url" "$LOGS/web.log" >&2
  exit 1
fi
printf '  ✓ web         %s   (pid %s)\n' "$url" "$(cat "$LOGS/web.pid")"
printf '  ✓ snapshotter cada 20 s          (pid %s)\n' "$(cat "$LOGS/snapshotter.pid")"
printf '  registros en %s · para parar: bash scripts/arrancar.sh --parar\n' "$LOGS"
