#!/usr/bin/env bash
# Sube un encargo ya construido al servidor y lo pone bajo su subdominio.
#
#   bash scripts/desplegar-encargo.sh <id> <carpeta> [alias-ssh]   # ensayo
#   bash scripts/desplegar-encargo.sh <id> <carpeta> [alias] --va   # de verdad
#
# 🔴 **La casa construye; la casa NO sirve** (decisión 282, regla dura 8). Esto
# empuja archivos a un servidor por SSH. Tu máquina no abre ningún puerto más.
#
# 🔴 **Un encargo se despliega ESTÁTICO, y no es una limitación: es la decisión.**
# Un MVP de encargo es de una sola persona, sin uso simultáneo, y existe para que
# alguien lo mire y reaccione — no para que su negocio dependa de él (decisión
# n9). Estático lo hace verdad por construcción en vez de por promesa: no hay
# base de datos que respaldar, ni proceso que se caiga un sábado, ni secreto que
# guardar. El día que uno de estos deje de ser una muestra, se replantea con
# nombre y con otro servidor, que es lo acordado.
#
# 🔴 **Esto NO edita el Caddyfile de nadie.** Deja un archivo suyo en
# `/opt/encargos/sites/` y nada más. Que ese directorio se lea o no depende de
# una línea `import` en el Caddyfile principal, y ese archivo es de otro
# proyecto: lo sobrescribe su propio despliegue, así que un cambio hecho aquí
# desaparecería solo y sin aviso. Si falta la línea, esto se para y lo dice.
set -euo pipefail

ID=${1:-}
CARPETA=${2:-}
ALIAS=${3:-vps-test}
MODO=${4:-}

# El contenedor de Caddy, por NOMBRE EXACTO y SIN valor por omisión.
#
# 🔴 Las dos mitades importan. Por nombre exacto porque adivinar cuál es —«el que
# publica el 80»— es la clase de patrón que la regla dura 12 prohíbe, y aquí
# recargaría el proxy que sirve las betas de otros proyectos. Y sin omisión
# porque el nombre depende de la máquina: cablear el de una la convierte en la
# suposición de todas, y el fallo aparecería recargando el Caddy equivocado.
CADDY=${HUB_CADDY:-}
RAIZ_REMOTA=/opt/encargos
DOMINIO=${HUB_DOMINIO_ENCARGOS:-}

rojo() { printf '  ✗ %s\n' "$1" >&2; }
bien() { printf '  ✓ %s\n' "$1"; }

if [ -z "$ID" ] || [ -z "$CARPETA" ]; then
  sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'
  exit 1
fi

# Sin valor por omisión, por lo mismo que Caddy: el dominio es de quien
# instala. Con uno cableado, otra persona publicaba bajo el del autor.
if [ -z "$DOMINIO" ]; then
  printf '  ✗ falta HUB_DOMINIO_ENCARGOS: el dominio bajo el que cuelga cada encargo\n' >&2
  printf '    p.ej.: HUB_DOMINIO_ENCARGOS=tudominio.com bash %s ...\n' "$0" >&2
  exit 2
fi

# El id es el subdominio: se valida con la misma regla que en `encargos.py`, y
# aquí hace falta igual porque esto puede llamarse a mano.
if ! printf '%s' "$ID" | grep -Eq '^[a-z0-9][a-z0-9-]{1,38}[a-z0-9]$'; then
  rojo "«$ID» no sirve como subdominio: minúsculas, números y guiones"
  exit 1
fi
# Un id provisional (`encargo-3`) se despliega igual (decisión 232): el nombre
# del negocio se pone solo si la ficha lo sabe, y si no, un enlace feo que
# funciona vale más que un encargo parado esperando un nombre.

if [ ! -d "$CARPETA" ]; then
  rojo "no existe la carpeta «$CARPETA»"
  exit 1
fi
# Dos modos, y lo decide lo que hay en la carpeta: `main.py` es una app
# (decisión 244: un contenedor propio detrás de Caddy, con acceso); `index.html`
# es la maqueta estática de siempre.
APP=0
if [ -f "$CARPETA/main.py" ]; then
  APP=1
  HASH_ACCESO=$(cat "$CARPETA/../acceso.bcrypt" 2>/dev/null | tr -d '[:space:]' || true)
  if [ -z "$HASH_ACCESO" ]; then
    rojo "falta $CARPETA/../acceso.bcrypt: una app no se publica sin acceso"
    exit 1
  fi
  if [ ! -d "$CARPETA/static" ]; then
    rojo "«$CARPETA» no tiene static/: la app sirve las pantallas de la maqueta desde ahí"
    exit 1
  fi
elif [ ! -f "$CARPETA/index.html" ]; then
  # Sin esto, el despliegue «funciona» y la URL devuelve un listado de archivos
  # o un 404: quien lo abre cree que se rompió el servidor, no que falta la
  # página.
  rojo "«$CARPETA» no tiene index.html: no habría nada que abrir"
  exit 1
fi
AQUI=$(cd "$(dirname "$0")" && pwd)

HOST="$ID.$DOMINIO"
ENSAYO=1
[ "$MODO" = "--va" ] && ENSAYO=0
DESTINO_REMOTO=$RAIZ_REMOTA/$ID
[ "$APP" = 1 ] && DESTINO_REMOTO=$RAIZ_REMOTA/apps/$ID

printf '\n  encargo   %s\n  desde     %s\n  hacia     %s:%s\n  url       https://%s\n\n' \
       "$ID" "$CARPETA" "$ALIAS" "$DESTINO_REMOTO" "$HOST"

# ── Que se pueda entrar, antes de tocar nada ────────────────────────────────
# Con `BatchMode`: así se comprueba lo mismo que hará un servicio, y no lo que
# consigue una shell interactiva con un agente cargado.
if ! ssh -o BatchMode=yes -o ConnectTimeout=10 "$ALIAS" true 2>/dev/null; then
  rojo "no se puede entrar en «$ALIAS» sin contraseña ni agente"
  printf '    Dalo de alta con: bash scripts/alta-conexion.sh <alias> <host> <usuario>\n'
  exit 1
fi
bien "se entra en $ALIAS"

# ── La línea que no es nuestra ──────────────────────────────────────────────
if ! ssh -o BatchMode=yes "$ALIAS" \
     "grep -rqs 'import $RAIZ_REMOTA/sites' /etc/caddy/Caddyfile /opt/*/Caddyfile 2>/dev/null"; then
  rojo "el Caddy de ese servidor todavía no lee $RAIZ_REMOTA/sites"
  cat <<AYUDA

    Falta UNA línea, y tiene que ponerla quien sea dueño de ese Caddyfile —no
    este script— porque ese archivo se regenera en cada despliegue suyo y un
    cambio hecho aquí desaparecería sin avisar:

        import $RAIZ_REMOTA/sites/*.caddy

    Con ella, cada encargo deja su propio archivo ahí y nunca se toca la
    configuración de nada más.
AYUDA
  exit 1
fi
bien "Caddy lee $RAIZ_REMOTA/sites"

# Se comprueba aquí y no arriba: en un ensayo no hace falta, y pedirlo antes de
# saber siquiera si la carpeta tiene un index sería frenar por lo accesorio.
if [ -z "$CADDY" ] && [ "$ENSAYO" = 0 ]; then
  rojo "falta HUB_CADDY: el nombre exacto del contenedor de Caddy en ese servidor"
  printf '    Míralo con: ssh %s docker ps --format "{{.Names}}\t{{.Ports}}"\n' "$ALIAS"
  printf '    y luego:    HUB_CADDY=<nombre> bash %s ... --va\n' "$0"
  exit 1
fi

if [ "$APP" = 1 ]; then
  # 🔴 El acceso lo pone Caddy delante, con el hash: la app no sabe de
  # contraseñas y el hub no guarda ninguna (regla dura 5). El usuario es el id.
  BLOQUE=$(cat <<BLOQUE
# Generado por el hub para el encargo «$ID». No editar a mano.
# Sistema implementado: un contenedor propio, con su base en un volumen.
$HOST {
	basic_auth {
		$ID $HASH_ACCESO
	}
	reverse_proxy encargo-$ID:8000
	encode gzip
}
BLOQUE
)
else
  BLOQUE=$(cat <<BLOQUE
# Generado por el hub para el encargo «$ID». No editar a mano.
# Estático a propósito: un MVP de encargo es para mirar, no para depender.
$HOST {
	root * $RAIZ_REMOTA/$ID
	file_server
	encode gzip
}
BLOQUE
)
fi

if [ "$ENSAYO" = 1 ]; then
  printf '  ENSAYO — no se ha tocado nada. Esto es lo que se subiría:\n\n'
  rsync -avzn --delete --exclude datos-local --exclude datos-prueba --exclude __pycache__ \
        -e "ssh -o BatchMode=yes" "$CARPETA/" "$ALIAS:$DESTINO_REMOTO/" | sed 's/^/    /'
  [ "$APP" = 1 ] && printf '\n  Y se construiría la imagen encargo-%s y se levantaría el contenedor encargo-%s\n' "$ID" "$ID"
  printf '\n  Y este bloque en %s/sites/%s.caddy:\n\n' "$RAIZ_REMOTA" "$ID"
  printf '%s\n' "$BLOQUE" | sed 's/^/    /'
  printf '\n  Añade --va cuando lo hayas mirado.\n\n'
  exit 0
fi

ssh -o BatchMode=yes "$ALIAS" "mkdir -p $DESTINO_REMOTO $RAIZ_REMOTA/sites"
rsync -az --delete --exclude datos-local --exclude datos-prueba --exclude __pycache__ \
      -e "ssh -o BatchMode=yes" "$CARPETA/" "$ALIAS:$DESTINO_REMOTO/"
bien "archivos subidos"

if [ "$APP" = 1 ]; then
  # La imagen la define la casa (encargo-app.Dockerfile), no la carpeta: lo que
  # corre en el servidor no lo decide un agente guiado por texto ajeno.
  scp -q -o BatchMode=yes "$AQUI/encargo-app.Dockerfile" "$ALIAS:$DESTINO_REMOTO/Dockerfile"
  scp -q -o BatchMode=yes "$AQUI/respaldo-encargos.sh" "$ALIAS:/etc/cron.daily/respaldo-encargos"
  ssh -o BatchMode=yes "$ALIAS" "chmod +x /etc/cron.daily/respaldo-encargos && mkdir -p $RAIZ_REMOTA/datos/$ID"
  bien "respaldo diario instalado"
  if ! ssh -o BatchMode=yes "$ALIAS" "docker build -q -t encargo-$ID $DESTINO_REMOTO" >/dev/null 2>&1; then
    rojo "no se pudo construir la imagen encargo-$ID"
    printf '    Míralo con: ssh %s docker build -t encargo-%s %s\n' "$ALIAS" "$ID" "$DESTINO_REMOTO"
    exit 1
  fi
  bien "imagen encargo-$ID construida"
  # 🔴 Un contenedor, por su nombre EXACTO (regla dura 12): se para el de este
  # encargo y se levanta el nuevo sobre el mismo volumen. Nada más se toca.
  ssh -o BatchMode=yes "$ALIAS" "docker rm -f encargo-$ID >/dev/null 2>&1 || true"
  if ! ssh -o BatchMode=yes "$ALIAS" "docker run -d --name encargo-$ID --restart unless-stopped \
        --network web --memory 256m --cpus 0.5 \
        -v $RAIZ_REMOTA/datos/$ID:/datos -e DATOS=/datos encargo-$ID" >/dev/null 2>&1; then
    rojo "no se pudo levantar el contenedor encargo-$ID"
    exit 1
  fi
  bien "contenedor encargo-$ID levantado"
  printf '  esperando a que la app conteste dentro del contenedor'
  viva=0
  for _ in $(seq 1 20); do
    if ssh -o BatchMode=yes "$ALIAS" "docker exec encargo-$ID python -c \"import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/salud', timeout=3).status==200 else 1)\"" >/dev/null 2>&1; then
      viva=1; break
    fi
    printf '.'; sleep 2
  done
  printf '\n'
  if [ "$viva" = 0 ]; then
    rojo "la app no contesta en /salud dentro del contenedor"
    printf '    Míralo con: ssh %s docker logs --tail 40 encargo-%s\n' "$ALIAS" "$ID"
    exit 1
  fi
  bien "la app responde dentro del contenedor"
fi

printf '%s\n' "$BLOQUE" | ssh -o BatchMode=yes "$ALIAS" \
  "cat > $RAIZ_REMOTA/sites/$ID.caddy"
bien "bloque de Caddy escrito"

# Recargar y no reiniciar: reiniciar cortaría las conexiones de todo lo demás
# que vive detrás del mismo Caddy, y ahí hay betas de otros proyectos.
if ! ssh -o BatchMode=yes "$ALIAS" \
     "docker exec $CADDY caddy reload --config /etc/caddy/Caddyfile" >/dev/null 2>&1; then
  rojo "Caddy no aceptó la configuración: se deja el archivo y NO se recarga"
  printf '    Míralo con: ssh %s docker logs --tail 40 %s\n' "$ALIAS" "$CADDY"
  exit 1
fi
bien "Caddy recargado"

# 🔴 Desplegar no es funcionar. Un `rsync` que devuelve 0 y un `reload` que no
# se queja pueden convivir con una URL que da 502 — es la misma trampa que dar
# por enviado un mensaje que sigue en pantalla (regla dura 17).
printf '  esperando a que responda'
for _ in $(seq 1 20); do
  codigo=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "https://$HOST" || true)
  # Una app contesta 401 sin credenciales: eso ES que Caddy la sirve y pide
  # el acceso; que la app viva ya se comprobó desde dentro del contenedor.
  if [ "$codigo" = "200" ] || { [ "$APP" = 1 ] && [ "$codigo" = "401" ]; }; then
    printf '\n'
    bien "https://$HOST responde 200"
    exit 0
  fi
  printf '.'
  sleep 3
done
printf '\n'
rojo "https://$HOST no contesta todavía (último código: ${codigo:-sin respuesta})"
printf '    Si el subdominio es nuevo, Caddy puede estar sacando el certificado.\n'
printf '    Compruébalo otra vez en un minuto antes de tocar nada.\n'
exit 1
