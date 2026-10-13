#!/usr/bin/env bash
# Guarda un secreto donde el hub espera encontrarlo, con sus permisos.
#
#   bash scripts/guardar-secreto.sh ~/.secretos/telegram-encargos.env TELEGRAM_ENCARGOS_TOKEN
#
# El valor se teclea o se pega cuando lo pida: NO se pasa como argumento.
#
# 🔴 Ésa es la razón de que este script exista y no sea un `echo` a mano. Un
# secreto en la línea de comandos queda en el historial del shell y lo ve
# cualquiera que mire `ps` mientras corre — dos sitios donde nadie lo va a
# borrar. Por stdin no pasa por ninguno de los dos.
#
# El hub no guarda secretos (decisión 28): guarda un PUNTERO `ruta#CLAVE`, que
# es lo que este script imprime al terminar para que lo pegues donde toque.
set -euo pipefail

ruta="${1:-}"; clave="${2:-}"
if [[ -z "$ruta" || -z "$clave" ]]; then
  echo "uso: bash scripts/guardar-secreto.sh <ruta-del-archivo> <NOMBRE_DE_LA_CLAVE>" >&2
  echo "     p.ej. ~/.secretos/telegram-encargos.env TELEGRAM_ENCARGOS_TOKEN" >&2
  echo >&2
  echo "     🔴 El VALOR del secreto NO se pasa aquí: se pide después y no se" >&2
  echo "        ve al escribirlo. En la línea de comandos quedaría en el" >&2
  echo "        historial y lo vería cualquiera que mire \`ps\`." >&2
  exit 2
fi
# 🔴 Se aceptan en cualquier orden, y no es comodidad: son dos argumentos que
# se distinguen a simple vista —una ruta lleva `/` o `.`, una clave son
# mayúsculas— así que exigir el orden sólo sirve para que alguien lo falle. Pasó
# a la primera, y el mensaje que salía hablaba de «nombre de clave» enseñando
# una ruta, que es la peor forma de decir «los pusiste al revés».
es_clave() { [[ "$1" =~ ^[A-Z][A-Z0-9_]*$ ]]; }
if es_clave "$ruta" && ! es_clave "$clave"; then
  ruta_vieja="$ruta"; ruta="$clave"; clave="$ruta_vieja"
  echo "· los argumentos venían al revés; van la ruta primero y la clave después" >&2
fi
# 🔴 El error que de verdad se comete: pasar el VALOR del secreto como
# argumento. Es lo natural —«guardar el token» suena a darle el token— y es
# justo lo que este script existe para evitar, así que cuando pasa hay que
# decirlo por su nombre y no con un «no sirve como nombre de clave».
parece_secreto() {
  [[ "$1" =~ ^[0-9]{6,}:[A-Za-z0-9_-]{30,}$ ]] && return 0   # token de Telegram
  [[ ${#1} -ge 20 && "$1" =~ [a-z] && "$1" =~ [A-Z] && "$1" != */* ]]
}
if ! es_clave "$clave" && parece_secreto "$clave"; then
  echo "Eso parece el VALOR del secreto, y aquí no va." >&2
  echo >&2
  echo "Este script pide sólo DÓNDE guardarlo y CÓMO se llama la variable;" >&2
  echo "el valor te lo pide después y no se ve al escribirlo. Por eso existe:" >&2
  echo "un secreto en la línea de comandos queda en el historial y en \`ps\`." >&2
  echo >&2
  echo "  bash scripts/guardar-secreto.sh ~/.secretos/telegram-encargos.env TELEGRAM_ENCARGOS_TOKEN" >&2
  echo >&2
  echo "🔴 Si eso era el token de verdad, bórralo del historial:" >&2
  echo "     history -d \$((HISTCMD-1))   # o edita ~/.bash_history" >&2
  echo "   y pídele uno nuevo a BotFather con /revoke: el viejo ya circuló." >&2
  exit 2
fi
if ! es_clave "$clave"; then
  echo "«$clave» no sirve como nombre de clave: mayúsculas, números y _" >&2
  # Si es un identificador válido en minúsculas, casi seguro que sólo es eso y
  # se dice cómo quedaría. Proponerlo evita el viaje de ida y vuelta.
  if [[ "$clave" =~ ^[A-Za-z][A-Za-z0-9_]*$ ]]; then
    echo "     ¿querías «$(printf '%s' "$clave" | tr '[:lower:]' '[:upper:]')»?" >&2
  fi
  echo "uso: bash scripts/guardar-secreto.sh <ruta-del-archivo> <NOMBRE_DE_LA_CLAVE>" >&2
  echo "     el VALOR no va aquí: se pide después, sin eco" >&2
  exit 2
fi

ruta="${ruta/#\~/$HOME}"
carpeta="$(dirname "$ruta")"
mkdir -p "$carpeta"
chmod 700 "$carpeta" 2>/dev/null || true

# Se lee sin eco: pegar un token y verlo quedar escrito en la pantalla es la
# otra forma de que acabe donde no debe —una captura, alguien mirando—.
printf 'Pega el valor de %s (no se verá al escribir) y pulsa Enter:\n> ' "$clave" >&2
read -rs valor
printf '\n' >&2
[[ -n "$valor" ]] || { echo "no se escribió nada; no se ha tocado el archivo" >&2; exit 1; }

# 🔴 Si el archivo ya existe se CONSERVA lo demás y sólo se sustituye esa clave.
# Pisarlo entero borraría otros secretos que vivan ahí, y esa pérdida no deja
# rastro: el archivo sigue siendo válido y el fallo aparece días después.
tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT
chmod 600 "$tmp"
if [[ -f "$ruta" ]]; then
  grep -v -E "^(export )?[[:space:]]*${clave}[[:space:]]*=" "$ruta" > "$tmp" || true
  echo "  (el archivo ya existía: se conserva lo demás y se reemplaza «$clave»)" >&2
fi
printf '%s=%s\n' "$clave" "$valor" >> "$tmp"
mv "$tmp" "$ruta"
trap - EXIT
# Redundante hoy —`mktemp` ya crea a 600 y `mv` conserva el modo—, y se queda:
# el día que alguien cambie la escritura por un `>` directo, esta línea es lo
# único que impedirá que el token quede legible para todo el sistema.
chmod 600 "$ruta"

# 🔴 Un aviso al guardar, no al usarlo. Pasó: se pegó un token cortado, el
# archivo quedó perfectamente válido y el fallo sólo apareció al preguntarle a
# Telegram — a una capa de distancia y horas después. Aquí no se puede saber si
# un secreto es correcto, pero sí que tiene una pinta rara, y decirlo cuesta
# nada. No se rechaza: hay secretos legítimamente cortos.
if [[ ${#valor} -lt 16 ]]; then
  echo "⚠ Ojo: sólo ${#valor} caracteres. Si se cortó al pegar, vuelve a" >&2
  echo "  ejecutarlo — se reemplaza sin dejar rastro del anterior." >&2
fi
if [[ "$clave" == *TOKEN* && "$valor" != *:* && ${#valor} -lt 40 ]]; then
  echo "⚠ No tiene forma de token de Telegram (123456789:AA…, ~46 caracteres)." >&2
fi
echo "Guardado en $ruta (permisos $(stat -c '%a' "$ruta"), sólo tú)."
echo
echo "El puntero para el hub — esto sí se puede pegar donde haga falta:"
echo "  ${ruta/#$HOME/\~}#$clave"
