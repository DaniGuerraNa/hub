#!/usr/bin/env bash
# Sube el chat web de encargos al servidor y lo pone bajo chat.<dominio>.
#
#   HUB_CADDY=caddy bash scripts/desplegar-chat.sh <alias-ssh> <ruta#CLAVE> [--va]
#
# 🔴 El token del hub se pasa con el MISMO puntero que `chat_web.token_ref` en
# encargos.yml (`ruta#CLAVE`) y lo lee `telegram.leer_token`, como el hub:
# con un `grep` propio, otra clave subía un token vacío (C-0141). El token
# viaja como archivo con permisos 600 y entra al contenedor por `--env-file`:
# nunca en la línea de comandos, nunca en `docker inspect` a la vista de otro
# usuario. Igual que los encargos implementados: un contenedor por nombre
# exacto, red `web`, volumen para la base y los medios, Caddy delante.
set -euo pipefail
ALIAS=${1:-}; TOKEN_REF=${2:-}; MODO=${3:-}
CADDY=${HUB_CADDY:-}
# Sin valor por omisión, por lo mismo que Caddy: el dominio es de quien
# instala. Con uno cableado, otra persona publicaba bajo el del autor.
DOMINIO=${HUB_DOMINIO_ENCARGOS:-}
if [ -z "$DOMINIO" ]; then
  printf '  ✗ falta HUB_DOMINIO_ENCARGOS: el dominio bajo el que cuelga cada encargo\n' >&2
  printf '    p.ej.: HUB_DOMINIO_ENCARGOS=tudominio.com bash %s ...\n' "$0" >&2
  exit 2
fi
RAIZ=/opt/encargos/chat
HOST="chat.$DOMINIO"
AQUI=$(cd "$(dirname "$0")" && pwd)

rojo() { printf '  ✗ %s\n' "$1" >&2; }
bien() { printf '  ✓ %s\n' "$1"; }

if [ -z "$ALIAS" ]; then
  rojo "falta el alias de ssh del servidor (el primer argumento)"; exit 1
fi
if [ -z "$TOKEN_REF" ]; then
  rojo "falta el puntero al token: ruta#CLAVE, el mismo de chat_web.token_ref"; exit 1
fi
# El token se lee aquí, antes de tocar el servidor, y lo lee el hub por el
# puntero (en la línea de órdenes va el puntero, nunca el valor). Un
# `[ -f "${TOKEN_REF%%#*}" ]` propio no expandía `~`, y la forma documentada es
# `~/.secretos/…#CLAVE`: se paraba con un puntero que `leer_token` lee bien
# (C-0186). Ahora el diagnóstico es el suyo. Si no se puede leer, no se sube nada.
if ! TOKEN_ENV=$(uv run --project "$AQUI/.." --quiet python -c '
import sys
from hub.telegram import SinToken, leer_token
try:
    print("CHAT_TOKEN=" + leer_token(sys.argv[1]))
except SinToken as exc:
    sys.exit(f"  ✗ {exc}")
' "$TOKEN_REF"); then
  rojo "no se pudo leer el token de «$TOKEN_REF»"; exit 1
fi
if ! ssh -o BatchMode=yes -o ConnectTimeout=10 "$ALIAS" true 2>/dev/null; then
  rojo "no se puede entrar en «$ALIAS» sin contraseña ni agente"; exit 1
fi
bien "se entra en $ALIAS"

BLOQUE=$(cat <<BLOQUE
# Generado por el hub: el chat web de encargos. No editar a mano.
$HOST {
	reverse_proxy hub-chat:8000
	encode gzip
}
BLOQUE
)
if [ "$MODO" != "--va" ]; then
  printf '  ENSAYO — no se ha tocado nada. Se subiría %s a %s:%s,\n  se construiría la imagen hub-chat y se levantaría el contenedor hub-chat con este bloque:\n\n' "$AQUI/chat-web" "$ALIAS" "$RAIZ/app"
  printf '%s\n' "$BLOQUE" | sed 's/^/    /'
  exit 0
fi
if [ -z "$CADDY" ]; then rojo "falta HUB_CADDY: el nombre exacto del contenedor de Caddy"; exit 1; fi

ssh -o BatchMode=yes "$ALIAS" "mkdir -p $RAIZ/app $RAIZ/datos /opt/encargos/sites && chmod 700 $RAIZ"
rsync -az --delete --exclude datos-local --exclude __pycache__ -e "ssh -o BatchMode=yes" "$AQUI/chat-web/" "$ALIAS:$RAIZ/app/"
bien "código subido"
# El token, como archivo de entorno: CHAT_TOKEN=<valor>, leído arriba. Viaja
# por la entrada de ssh.
printf '%s\n' "$TOKEN_ENV" | ssh -o BatchMode=yes "$ALIAS" "umask 077 && cat > $RAIZ/token.env"
bien "token colocado (600)"
if ! ssh -o BatchMode=yes "$ALIAS" "docker build -q -t hub-chat $RAIZ/app" >/dev/null 2>&1; then
  rojo "no se pudo construir la imagen hub-chat"; exit 1
fi
bien "imagen hub-chat construida"
ssh -o BatchMode=yes "$ALIAS" "docker rm -f hub-chat >/dev/null 2>&1 || true"
ssh -o BatchMode=yes "$ALIAS" "docker run -d --name hub-chat --restart unless-stopped --network web \
  --memory 256m --cpus 0.5 --env-file $RAIZ/token.env -v $RAIZ/datos:/datos -e DATOS=/datos hub-chat" >/dev/null
bien "contenedor hub-chat levantado"
printf '%s\n' "$BLOQUE" | ssh -o BatchMode=yes "$ALIAS" "cat > /opt/encargos/sites/chat.caddy"
if ! ssh -o BatchMode=yes "$ALIAS" "docker exec $CADDY caddy reload --config /etc/caddy/Caddyfile" >/dev/null 2>&1; then
  rojo "Caddy no aceptó la configuración"; exit 1
fi
bien "Caddy recargado"
printf '  esperando a que responda'
for _ in $(seq 1 20); do
  codigo=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "https://$HOST/salud" || true)
  if [ "$codigo" = "200" ]; then printf '\n'; bien "https://$HOST responde"; exit 0; fi
  printf '.'; sleep 3
done
printf '\n'; rojo "https://$HOST no contesta todavía (${codigo:-sin respuesta})"; exit 1
