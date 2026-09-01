#!/usr/bin/env bash
# Statusline del asistente: vuelca su ocupación de contexto donde el hub la lee.
#
# Claude Code pasa por stdin al comando de statusline un JSON con
# `context_window.used_percentage` — el mismo número que enseña /context. Es el
# dato exacto, y es el que el usuario pidió ver siempre: "es muy importante mostrar el
# tamaño de la ventana de contexto del asistente para saber cuándo mandar un
# compact o clear".
#
# El hub tiene un respaldo calculado del transcript, pero sólo da tokens, no
# porcentaje: no conoce el tamaño de la ventana. Esto es la vía buena.
#
# ── Por qué encadena en vez de sustituir ───────────────────────────────────
# Es normal tener ya un statusLine en el `settings.json` global —uno que registre
# la cuota, que pinte un HUD, o los dos encadenados—. Un statusLine de proyecto
# lo SUSTITUYE, no se suma: si esto no reenviara el payload, trabajar en el
# asistente dejaría de alimentar al tuyo y no lo avisaría nadie. Se entrega
# intacto.
#
# Requisito duro, igual que su envoltorio: NUNCA puede romper la statusline.
# Cualquier fallo del volcado se traga en silencio y el payload sigue su camino.

set -uo pipefail   # -e queda FUERA a propósito

DESTINO="${HUB_CONTEXTO_FICHERO:-$HOME/.local/share/hub/asistente-contexto.json}"
# Si ya tenías una statusline propia, declárala aquí y el payload sigue hacia ella
# intacto. Vacío = el HUD no encadena con nada.
SIGUIENTE="${HUB_STATUSLINE_SIGUIENTE:-}"

# El sufijo centinela evita que $() se coma los saltos de línea finales.
CARGA="$(cat 2>/dev/null; printf 'X')"
CARGA="${CARGA%X}"

# Escritura atómica: el hub puede estar leyendo justo ahora, y medio JSON se
# lee como "no sé cuánto contexto queda" en vez de como un número a medias.
{
  mkdir -p "$(dirname "$DESTINO")" 2>/dev/null \
    && printf '%s' "$CARGA" > "$DESTINO.tmp" 2>/dev/null \
    && mv -f "$DESTINO.tmp" "$DESTINO" 2>/dev/null
} || true

if [ -x "$SIGUIENTE" ]; then
  printf '%s' "$CARGA" | "$SIGUIENTE"
else
  # Sin el envoltorio del usuario no hay HUD que pintar, pero la statusline tiene
  # que decir algo: el silencio se lee como "se rompió".
  printf 'asistente'
fi
