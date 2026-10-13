#!/usr/bin/env bash
# Copia diaria de la base de cada encargo implementado. La instala el despliegue
# en /etc/cron.daily del servidor (decisión 244): sin respaldo no hay sistema.
set -euo pipefail
RAIZ=/opt/encargos
FECHA=$(date +%Y%m%d)
for base in "$RAIZ"/datos/*/app.db; do
  [ -f "$base" ] || continue
  id=$(basename "$(dirname "$base")")
  mkdir -p "$RAIZ/respaldos/$id"
  cp "$base" "$RAIZ/respaldos/$id/app-$FECHA.db"
  ls -1t "$RAIZ/respaldos/$id"/app-*.db | tail -n +15 | xargs -r rm --
done
