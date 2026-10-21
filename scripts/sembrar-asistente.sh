#!/usr/bin/env bash
# Crea el proyecto del asistente a partir de la semilla.
#
#   bash scripts/sembrar-asistente.sh [destino]      (por defecto ~/projects/asistente)
#   bash scripts/sembrar-asistente.sh --refrescar <destino>
#
# El asistente es un proyecto más: `claude` corriendo en una ventana de tmux. Lo
# único distinto es que el hub pinta su transcript como chat. Vive FUERA del repo
# del hub a propósito: dentro, sus transcripts y su `.claude/` ensuciarían al
# proyecto que los indexa.
#
# Sembrar no pisa nada: si el destino ya existe, para. `--refrescar` es lo que
# usa `actualizar.sh` (decisión 286): pone al día los archivos que vienen de la
# semilla y deja al lado, con `.antes-<fecha>`, el que había si era distinto.
# Lo demás de esa carpeta —su historia, lo que la persona añadiera— no se toca.
set -euo pipefail

RAIZ=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
SEMILLA="$RAIZ/semillas/asistente"
REFRESCAR=0
if [ "${1:-}" = "--refrescar" ]; then
  REFRESCAR=1
  shift
  [ -n "${1:-}" ] || { printf '  ✗ --refrescar necesita la carpeta del asistente\n' >&2; exit 2; }
fi
DESTINO=${1:-$HOME/projects/asistente}

# La semilla con las rutas de ESTA máquina ya resueltas, en la carpeta que se
# le diga. Sembrar y refrescar la generan igual: dos caminos que la escribieran
# cada uno a su manera acabarían en dos asistentes distintos.
renderizar() {
  local donde=$1
  cp -r "$SEMILLA/." "$donde/"
  chmod +x "$donde/bin/hub" "$donde/bin/contexto-statusline.sh"

  # Las rutas reales, resueltas ahora: `settings.json` de Claude Code no expande
  # `~` ni variables en el comando de la statusline.
  sed -i "s|@ASIENTO@|$DESTINO|g" "$donde/.claude/settings.json"

  # 🔴 Y la del hub en su CLAUDE.md. Sin esto el asistente tenía una instrucción
  # imposible: se le mandaba leer `conocimiento/INDICE.md` sin decirle dónde
  # estaba, y a la vez se le prohibía explorar el disco para encontrarlo. El
  # resultado medido: de diez preguntas normales sobre el hub sólo podía
  # contestar dos con fuente; el resto se las inventaba — incluida «¿puedo abrir
  # el puerto a la red?», que es la única donde inventar hace daño de verdad.
  #
  # El conocimiento está en dos sitios según desde dónde se siembre: en el repo
  # publicado cuelga de la raíz, y en el de desarrollo vive en `producto/` porque
  # es material que se escribe PARA el producto. Se resuelve aquí en vez de
  # suponerlo, o el asistente de quien desarrolla el hub apunta a una carpeta que
  # no existe — que es justo el defecto que esto viene a cerrar.
  local conocimiento="$RAIZ"
  [ -d "$RAIZ/producto/conocimiento" ] && conocimiento="$RAIZ/producto"
  sed -i -e "s|@HUB@/conocimiento|$conocimiento/conocimiento|g" \
         -e "s|@HUB@|$RAIZ|g" "$donde/CLAUDE.md"
}

if [ "$REFRESCAR" -eq 1 ]; then
  [ -d "$DESTINO" ] || { printf '  ✗ %s no existe: no hay asistente que refrescar\n' "$DESTINO" >&2; exit 1; }
  tmp=$(mktemp -d)
  trap 'rm -rf "$tmp"' EXIT
  renderizar "$tmp"
  fecha=$(date +%Y%m%d)
  cambios=0
  while IFS= read -r relativa; do
    nuevo="$tmp/$relativa"
    actual="$DESTINO/$relativa"
    if [ -f "$actual" ] && cmp -s "$nuevo" "$actual"; then
      continue
    fi
    mkdir -p "$(dirname "$actual")"
    [ -f "$actual" ] && cp -p "$actual" "$actual.antes-$fecha"
    cp -p "$nuevo" "$actual"
    printf '  ✓ %s\n' "$relativa"
    cambios=$((cambios + 1))
  done < <(cd "$tmp" && find . -type f | sed 's|^\./||' | sort)
  if [ "$cambios" -eq 0 ]; then
    printf '  · el asistente ya estaba al día\n'
  else
    printf '  · %s archivo(s) al día; lo anterior queda al lado con .antes-%s\n' "$cambios" "$fecha"
    printf '  · el chat lee sus instrucciones nuevas cuando se limpia (botón «Limpiar» de la rueda)\n'
  fi
fi

if [ "$REFRESCAR" -eq 0 ]; then
if [ -e "$DESTINO" ]; then
  printf '  ✗ %s ya existe. Si quieres rehacerlo, muévelo antes.\n' "$DESTINO" >&2
  exit 1
fi

mkdir -p "$DESTINO"
renderizar "$DESTINO"

printf '  ✓ asistente sembrado en %s\n' "$DESTINO"
fi

# El comando `hub` también fuera del chat (decisión 278). Las skills del repo
# —`lienzos`, `sobre-el-hub`— lo usan desde cualquier sesión de Claude Code, y
# hasta ahora sólo existía en el PATH del asistente: en una máquina nueva esas
# skills fallaban. 🔴 Lo que ya haya en esa ruta no se pisa: puede ser de otra
# instalación, o algo que la persona puso a propósito.
BIN=${HUB_BIN:-$HOME/.local/bin}
ENLACE="$BIN/hub"
if [ -L "$ENLACE" ] && [ "$(readlink "$ENLACE")" = "$DESTINO/bin/hub" ]; then
  printf '  · %s ya apuntaba aquí\n' "$ENLACE"
elif [ -e "$ENLACE" ] || [ -L "$ENLACE" ]; then
  printf '  · %s ya existe (%s): no se toca. El del asistente está en %s\n' \
    "$ENLACE" "$(readlink "$ENLACE" 2>/dev/null || echo 'no es un enlace')" "$DESTINO/bin/hub"
else
  mkdir -p "$BIN"
  ln -s "$DESTINO/bin/hub" "$ENLACE"
  printf '  ✓ comando hub en %s\n' "$ENLACE"
  case ":$PATH:" in
    *":$BIN:"*) ;;
    *) printf '  · %s no está en tu PATH: añádelo para usar `hub` fuera del chat\n' "$BIN" ;;
  esac
fi

[ "$REFRESCAR" -eq 1 ] && exit 0

# 🔴 Se declara solo, con el escritor del registro del hub. Antes se imprimía
# el bloque y un «Añade:», y pegarlo al final del archivo —lo natural— lo dejaba
# debajo de `conexiones: []` y el registro entero dejaba de leerse: el hub se
# quedaba sin ningún proyecto. Pasó en la sala limpia del 16-oct.
# `añadir_proyecto` lo inserta dentro de `proyectos:` y no pisa nada: si ya hay
# un asistente declarado, no hace nada y lo dice.
if (cd "$RAIZ" && uv run --quiet python - "$DESTINO" <<'PY'
import sys
from hub import registry
destino = sys.argv[1]
if any(p.tipo == "asistente" for p in registry.cargar()):
    print("  · ya había un asistente en tu registro: no se toca")
else:
    registry.añadir_proyecto({"id": "asistente", "nombre": "Asistente", "dominio": "personal",
                              "tipo": "asistente", "asiento": destino,
                              "estado_ref": "CLAUDE.md", "guardrail": "ask", "status": "activo"})
    print("  ✓ declarado en tu registro")
PY
); then
  cat <<FIN

Listo. En menos de un minuto aparece el chat abajo a la derecha de cada
pantalla. Empieza por la Guía (/guia): sus botones «Guíame» se lo preguntan.
FIN
  exit 0
fi

printf '  ✗ no se pudo declarar solo. Hazlo a mano, abajo.\n' >&2

# 🔴 Este heredoc NO va entrecomillado porque necesita expandir $DESTINO — y por
# eso mismo no puede llevar backticks dentro: bash las ejecutaría. Pasó, y se vio
# en la primera instalación: «line 32: tipo:: command not found», con la frase
# saliendo mutilada. Se usan comillas «» para citar, que no ejecutan nada.
cat <<FIN

Falta declararlo en tu registro (~/.local/share/hub/projects.yml). Añade, DENTRO
de la lista «proyectos:» (no al final del archivo):

  - id: asistente
    nombre: Asistente
    dominio: personal
    tipo: asistente
    asiento: $DESTINO
    estado_ref: CLAUDE.md
    guardrail: ask
    status: activo

«tipo: asistente» es lo que hace que el hub sepa cuál es sin cablear ninguna ruta
en el código. Mientras no haya ningún proyecto de ese tipo, la pestaña del chat
ni siquiera se pinta.
FIN
