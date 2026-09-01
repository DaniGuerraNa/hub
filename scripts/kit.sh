#!/usr/bin/env bash
# El gestor de kits, sin necesidad de que el hub esté corriendo.
#
#   bash scripts/kit.sh listar
#   bash scripts/kit.sh instalar <id> [version]
#   bash scripts/kit.sh ruta <id> [version]     ← lo que resuelve un apuntador
#   bash scripts/kit.sh estado [proyecto]
#   bash scripts/kit.sh arbol                   ← quién provee qué, y qué falta
#   bash scripts/kit.sh verificar <ruta|id>
set -euo pipefail
RAIZ=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$RAIZ"
exec uv run python -m hub.kits_cli "$@"
