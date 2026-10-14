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
# `$USER` no siempre existe (docker exec, algunos sudo y lanzadores), y con
# `set -u` reventaba justo al comprobar el linger. Visto instalando en limpio.
YO=${USER:-$(id -un)}

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
# Sin systemd de usuario no hay servicios que instalar: se cae al arranque a
# mano en vez de fallar. Es lo que le pasa a un contenedor, a un Linux sin
# systemd de usuario, y a WSL antes de activarlo.
if [ "$CON_SERVICIOS" -eq 1 ] && ! systemctl --user show-environment >/dev/null 2>&1; then
  CON_SERVICIOS=0
  bien "systemd --user no responde: se omiten los servicios"
fi
if [ "$CON_SERVICIOS" -eq 0 ]; then
  bien "omitidos (sin systemd de usuario, o --sin-servicios)"
  # Los DOS procesos, no sólo la web: sin el snapshotter el hub no relee
  # projects.yml ni muestrea tmux, y parece instalado sin estarlo.
  printf '    Arráncalo a mano (web + snapshotter) cuando quieras:\n'
  printf '      cd %s && HUB_HOME=%s HUB_PORT=%s bash scripts/arrancar.sh\n' \
         "$RAIZ" "$HUB_HOME" "$HUB_PORT"
  printf '\nListo. Datos en %s\n' "$HUB_HOME"
  exit 0
fi

# Las rutas se resuelven AHORA y se escriben dentro del unit. Cablearlas en el
# repo era lo que impedía instalar el hub en cualquier carpeta que no fuera
# ~/projects/hub, y no se veía hasta que fallaba en otra máquina.
UV=$(command -v uv)
mkdir -p "$UNIDADES"
for servicio in hub-web hub-snapshotter hub-canal hub-encargos; do
  sed -e "s|@RAIZ@|$RAIZ|g" \
      -e "s|@HUB_HOME@|$HUB_HOME|g" \
      -e "s|@UV@|$UV|g" \
      -e "s|@PATH@|$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin|g" \
      -e "s|@HOST@|$HUB_HOST|g" \
      -e "s|@PUERTO@|$HUB_PORT|g" \
      "$RAIZ/scripts/$servicio.service.plantilla" > "$UNIDADES/$servicio.service"
  bien "$UNIDADES/$servicio.service"
done

# 🔴 Sin linger, `systemd --user` entero se apaga al cerrar la última sesión de
# login y vuelve con la siguiente (decisión 155). Medido el 2026-09-04 tras
# reiniciar la PC: el gestor se recicló TRES veces en tres minutos y se llevó
# `hub-web` cada vez — el síntoma que se ve es «el hub me deja entrar y se muere
# a los pocos segundos», que no parece un problema de sesión de login.
if [ "$(loginctl show-user "$YO" -p Linger --value 2>/dev/null)" = "yes" ]; then
  # Se mira antes de pedirlo: activarlo puede denegarse a un usuario normal
  # aunque ya esté puesto, y entonces se avisaba de un fallo que no existía.
  bien "linger ya activo: el hub sigue vivo aunque cierres la terminal"
elif loginctl enable-linger "$YO" >/dev/null 2>&1; then
  bien "linger activado: el hub sigue vivo aunque cierres la terminal"
else
  # No es fatal: con una sesión abierta el hub funciona. Se dice en voz alta
  # porque el fallo que provoca aparece horas después y en otro sitio.
  printf '    ⚠ no se pudo activar el linger: el hub morirá al cerrar la última sesión\n'
  printf '      arréglalo con: loginctl enable-linger %s\n' "$YO"
fi

systemctl --user daemon-reload
# 🔴 El puerto se mira con el hub de antes ya parado (si es una reinstalación),
# para no confundirlo con «otro programa». Sin esto, con el puerto ocupado
# `hub-web` moría al arrancar —Errno 98— y el instalador decía «Listo»: lo que
# contestaba en la comprobación era el otro programa (visto el 14-oct).
systemctl --user stop hub-web >/dev/null 2>&1 || true
if (exec 3<>"/dev/tcp/$HUB_HOST/$HUB_PORT") 2>/dev/null; then
  mal "el puerto $HUB_PORT ya lo usa otro programa: el hub no podría arrancar"
  printf '    usa otro:  HUB_PORT=8788 bash scripts/instalar.sh
' >&2
  exit 1
fi
systemctl --user enable hub-web hub-snapshotter >/dev/null 2>&1
# `restart` y no `enable --now`: `--now` no toca un servicio que ya corre, así
# que reinstalar tras un `git pull` dejaba en marcha el código viejo.
systemctl --user restart hub-web hub-snapshotter
bien "arrancados y habilitados para el próximo inicio"
# 🔴 `hub-canal` se instala pero NO se arranca. Sin `canal.yml` no tiene token, y
# un servicio que sólo sabe escribir fallos en el registro cada 30 segundos es
# ruido que enseña a ignorar el registro — justo el sitio donde luego hay que
# mirar. Se habilita cuando se configure: `systemctl --user enable --now hub-canal`.
bien "hub-canal instalado y PARADO: arráncalo cuando configures canal.yml"
# Y lo mismo, por lo mismo, con el relé de encargos: sin `encargos.yml` no tiene
# token y sólo sabría apuntar fallos.
bien "hub-encargos instalado y PARADO: arráncalo cuando configures encargos.yml"

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

# Que conteste 200 no basta: tiene que ser EL HUB quien contesta. Con el
# puerto ocupado por otro servidor, la portada daba 200 y el resto 404.
if ! curl -s "$url/" | grep -q 'apple-mobile-web-app-title" content="Hub"'; then
  mal "en $url contesta algo, pero no es el hub"
  printf '    journalctl --user -u hub-web -n 40 --no-pager
' >&2
  exit 1
fi
fallos=0
for r in / /trabajo /inventario /respaldo /servicios /conexiones /contexto /orquestador /intercambio; do
  c=$(curl -s -o /dev/null -w '%{http_code}' "$url$r" || true)
  [ "$c" = "200" ] || { mal "$r → $c"; fallos=1; }
done
if [ "$fallos" -ne 0 ]; then
  printf '    alguna pantalla falla: journalctl --user -u hub-web -n 40 --no-pager
' >&2
  exit 1
fi
bien "las pantallas responden"

cat <<FIN

Listo. El hub está en $url

  Datos     $HUB_HOME
  Registro  $HUB_HOME/projects.yml   ← declara aquí tus proyectos
  Servicios systemctl --user status hub-web hub-snapshotter

Lo siguiente: abre Claude Code en esta carpeta y di «anexa mi proyecto», o edita
el registro a mano. La pantalla de inicio te guía si aún no tienes ninguno.

El asistente (el chat de abajo a la derecha) es opcional y va aparte:
  bash scripts/sembrar-asistente.sh     y declara el bloque que imprime.
FIN
