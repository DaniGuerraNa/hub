#!/usr/bin/env bash
# Crea el proyecto del asistente a partir de la semilla.
#
#   bash scripts/sembrar-asistente.sh [destino]      (por defecto ~/projects/asistente)
#
# El asistente es un proyecto más: `claude` corriendo en una ventana de tmux. Lo
# único distinto es que el hub pinta su transcript como chat. Vive FUERA del repo
# del hub a propósito: dentro, sus transcripts y su `.claude/` ensuciarían al
# proyecto que los indexa.
#
# No pisa nada: si el destino ya existe, para.
set -euo pipefail

RAIZ=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
DESTINO=${1:-$HOME/projects/asistente}
SEMILLA="$RAIZ/semillas/asistente"

if [ -e "$DESTINO" ]; then
  printf '  ✗ %s ya existe. Si quieres rehacerlo, muévelo antes.\n' "$DESTINO" >&2
  exit 1
fi

mkdir -p "$DESTINO"
cp -r "$SEMILLA/." "$DESTINO/"
chmod +x "$DESTINO/bin/hub" "$DESTINO/bin/contexto-statusline.sh"

# Las rutas reales, resueltas ahora: `settings.json` de Claude Code no expande
# `~` ni variables en el comando de la statusline.
sed -i "s|@ASIENTO@|$DESTINO|g" "$DESTINO/.claude/settings.json"

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
CONOCIMIENTO="$RAIZ"
[ -d "$RAIZ/producto/conocimiento" ] && CONOCIMIENTO="$RAIZ/producto"

sed -i -e "s|@HUB@/conocimiento|$CONOCIMIENTO/conocimiento|g" \
       -e "s|@HUB@|$RAIZ|g" "$DESTINO/CLAUDE.md"

printf '  ✓ asistente sembrado en %s\n' "$DESTINO"

# 🔴 Este heredoc NO va entrecomillado porque necesita expandir $DESTINO — y por
# eso mismo no puede llevar backticks dentro: bash las ejecutaría. Pasó, y se vio
# en la primera instalación: «line 32: tipo:: command not found», con la frase
# saliendo mutilada. Se usan comillas «» para citar, que no ejecutan nada.
cat <<FIN

Falta declararlo en tu registro (~/.local/share/hub/projects.yml). Añade:

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
