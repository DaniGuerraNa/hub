#!/usr/bin/env bash
# Pone al día una instalación del hub. Un solo comando, en la carpeta del clon:
#
#   bash scripts/actualizar.sh
#
# Lo que hace, en orden, y por qué cada paso (decisión 286):
#   1. comprueba que el clon puede avanzar sin perder nada tuyo
#   2. baja la versión publicada (sólo si avanza en línea recta)
#   3. resuelve dependencias y pasa el doctor
#   4. copia las bases tal como están y aplica los pasos propios de cada
#      versión que cruces (scripts/migraciones)
#   5. regenera los servicios —con TU puerto y TUS datos— y reinicia los que
#      estaban en marcha (también el Puente KVM, si es de este clon y está libre)
#   6. pone al día los archivos del asistente, si lo tienes
#   7. comprueba que el hub contesta y que lo reiniciado funciona, apunta la
#      versión y te dice qué cambió
#
# `git pull` y reiniciar —lo que se documentaba antes de la 0.2.0— hace el 2 y
# medio 5: deja el código nuevo corriendo con los servicios y el asistente de
# la versión anterior. El hub lo detecta y lo dice en todas las pantallas.
#
#   --sin-bajar    no hace `git pull`: para quien ya bajó el código a mano, o
#                  desarrolla el hub en este clon
#
# Tus datos (`HUB_HOME`) no se tocan salvo lo que diga una migración. Antes de
# los pasos de versión se copian `hub.db` y la memoria del secretario
# (`antes-hub-<fecha>.db`, `antes-secretario-<fecha>.db`, C-0448), además de
# la copia diaria (decisión 277). Si algo falla, para ahí y lo dice: la
# versión no se apunta como instalada hasta el final, así que volver a correrlo
# retoma. Desde el paso 4, además, dice cómo volver a como estaba; no vuelve
# solo (INSTALAR.md, «Volver a la versión anterior»).
#
#   HUB_ESPERA_SENAL    segundos que se espera a que el muestreo y el
#                       secretario den señales tras reiniciarlos (60)
set -euo pipefail

RAIZ=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
UNIDADES=${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user
BAJAR=1
for arg in "$@"; do
  case "$arg" in
    --sin-bajar) BAJAR=0 ;;
    *) printf 'opción desconocida: %s\n' "$arg" >&2; exit 2 ;;
  esac
done

paso() { printf '\n\033[1m%s\033[0m\n' "$*"; }
bien() { printf '  ✓ %s\n' "$*"; }
ojo()  { printf '  ⚠ %s\n' "$*"; }
mal()  { printf '  ✗ %s\n' "$*" >&2; }
version() { (cd "$RAIZ" && HUB_HOME="$HUB_HOME" uv run --quiet python -m hub.version "$@"); }
ESPERA_SENAL=${HUB_ESPERA_SENAL:-60}

# Lo que hace falta para decir cómo volver si algo falla desde el paso 4
# (C-0448): el commit en el que estaba el clon antes de bajar y dónde quedaron
# las copias de antes.
DESDE=""
COPIAS=""
VOLVER=0

# La versión que declara el código de un commit (la de `[project]`).
version_de() {
  git -C "$RAIZ" show "$1:pyproject.toml" 2>/dev/null \
    | sed -n '/^\[project\]/,/^\[/s/^version *= *"\([^"]*\)".*/\1/p' | head -1 || true
}

# 🔴 Cómo volver, impreso y nada más. No se restaura nada solo ni se imprime
# un `cp` encima de una base: restaurar pisa lo escrito desde la copia, y eso
# lo decide quien lo lee (INSTALAR.md, «Volver a la versión anterior»).
#
# «Como estaba» es la versión apuntada como instalada, que al fallar no
# cambia. El commit de antes de bajar lo es si su código declara esa versión;
# si no —un reintento que bajó otro arreglo después de fallar—, es el de un
# intento que tampoco se instaló, y volver ahí repetiría sus pasos de
# versión: entonces manda la etiqueta de la versión apuntada.
como_volver() {
  local cabeza a="" t=""
  cabeza=$(git -C "$RAIZ" rev-parse HEAD 2>/dev/null || true)
  if [ -n "$DESDE" ] && [ "$DESDE" != "$cabeza" ] \
     && { [ -z "${antes:-}" ] || [ "$(version_de "$DESDE")" = "$antes" ]; }; then
    a=$DESDE
  elif [ -n "${antes:-}" ] && t=$(git -C "$RAIZ" rev-parse -q --verify "refs/tags/v$antes^{commit}" 2>/dev/null) \
       && [ "$t" != "$cabeza" ]; then
    a=v$antes
  fi
  {
    printf '\n\033[1mPara volver a como estaba\033[0m\n'
    if [ -n "$a" ]; then
      printf '  git checkout %s\n  bash scripts/actualizar.sh --sin-bajar\n' "$a"
    elif [ -n "${antes:-}" ] && [ "${t:-}" = "$cabeza" ]; then
      printf '  El código ya es el de la versión que tenías (la %s): no hay otra a la que\n' "$antes"
      printf '  volver. Arregla lo que diga arriba y vuelve a correr: bash scripts/actualizar.sh --sin-bajar\n'
    else
      printf '  No encuentro el commit de la versión que tenías%s: no tiene etiqueta en\n' "${antes:+ (la $antes)}"
      printf '  este clon. Búscalo con «git reflog» y después:\n'
      printf '    git checkout <ese commit>\n    bash scripts/actualizar.sh --sin-bajar\n'
    fi
    if [ -n "$COPIAS" ]; then
      printf 'Tus bases de antes de este intento:\n'
      while IFS= read -r copia; do printf '  %s\n' "$copia"; done <<< "$COPIAS"
      printf 'Sólo hacen falta si el hub de antes no arranca:\n'
    else
      printf 'Si el hub de antes no arranca:\n'
    fi
    printf '  INSTALAR.md, «Volver a la versión anterior».\n'
    if [ -n "${rama:-}" ] && [ "$rama" != "HEAD" ]; then
      printf 'Para intentarlo otra vez más adelante: git switch %s && bash scripts/actualizar.sh\n' "$rama"
    fi
  } >&2
}
trap 'rc=$?; if [ "$rc" -ne 0 ] && [ "$VOLVER" -eq 1 ]; then como_volver; fi; exit $rc' EXIT

# shellcheck source=lib/unidades.sh
. "$RAIZ/scripts/lib/unidades.sh"
# shellcheck source=lib/puente.sh
. "$RAIZ/scripts/lib/puente.sh"

# Con servicios, lo instalado manda: el puerto y la carpeta de datos se leen de
# los units, no se suponen. Sin ellos, de las variables de siempre.
CON_SERVICIOS=0
if systemctl --user show-environment >/dev/null 2>&1 && leer_unidad_instalada; then
  CON_SERVICIOS=1
else
  HUB_HOME=${HUB_HOME:-$HOME/.local/share/hub}
  HUB_HOST=${HUB_HOST:-127.0.0.1}
  HUB_PORT=${HUB_PORT:-8787}
fi
export HUB_HOME
# Un unit con otro `--host` no se conserva: se para aquí y se dice (C-0112).
# shellcheck source=lib/loopback.sh
. "$RAIZ/scripts/lib/loopback.sh"
exigir_loopback "$HUB_HOST"

paso "1/7 · El clon"
cd "$RAIZ"
if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
  mal "hay cambios sin guardar en archivos del hub:"
  git status --short --untracked-files=no >&2
  # Quien llega aquí casi nunca sabe git, y «guárdalos» sin decir cómo lo
  # deja en manos de un stash que luego no sabe reaplicar. Lo habitual es un
  # parche de urgencia que la versión nueva ya trae: se mira, se guarda copia
  # y se descarta. La rama queda para lo que de verdad sea suyo.
  rama_actual=$(git rev-parse --abbrev-ref HEAD)
  dia=$(date +%Y%m%d)
  cat >&2 <<EOF
    actualizar encima los mezclaría con los nuevos. Casi siempre son arreglos
    de urgencia que la versión nueva ya trae. Mira para qué eran (git diff),
    guarda una copia y descártalos:

      git diff > ~/cambios-hub-$dia.patch
      git restore .
      bash scripts/actualizar.sh

    Si son algo tuyo que quieres conservar, guárdalos en una rama:

      git switch -c mis-cambios-$dia
      git commit -am "Mis cambios antes de actualizar"
      git switch $rama_actual
      bash scripts/actualizar.sh
EOF
  exit 1
fi
rama=$(git rev-parse --abbrev-ref HEAD)
bien "rama $rama, sin cambios locales"
[ "$rama" = "main" ] || printf '    · no es main: se actualiza lo que haya en «%s»\n' "$rama"

paso "2/7 · Bajar la versión"
if [ "$BAJAR" -eq 1 ]; then
  # Dónde estaba el clon: es adonde se vuelve si algo falla (C-0448). Vale
  # también sin etiqueta, para quien sigue una rama.
  DESDE=$(git rev-parse HEAD)
  antes_guion=$(sha256sum "$RAIZ/scripts/actualizar.sh" | cut -d' ' -f1)
  if ! git pull --ff-only --tags; then
    mal "no avanza en línea recta: tu clon tiene commits que el publicado no"
    printf '    mira «git log origin/%s..HEAD»; no se mezcla nada automáticamente\n' "$rama" >&2
    exit 1
  fi
  # 🔴 Si lo que bajó trae otro actualizar.sh, sigue el nuevo: el que está
  # corriendo es el de la versión anterior y no conoce sus pasos. Le pasa de
  # dónde venía, que él ya no puede saber.
  if [ "$(sha256sum "$RAIZ/scripts/actualizar.sh" | cut -d' ' -f1)" != "$antes_guion" ]; then
    bien "el actualizador también cambió: sigue el de la versión nueva"
    export HUB_ACTUALIZA_DESDE=$DESDE
    exec bash "$RAIZ/scripts/actualizar.sh" --sin-bajar
  fi
  bien "código al día"
else
  # Lo que deja aquí el guion de la versión anterior al relanzarse: un commit,
  # y sólo eso (lo que no es un hash se ignora).
  if [[ "${HUB_ACTUALIZA_DESDE:-}" =~ ^[0-9a-f]{7,64}$ ]]; then
    DESDE=$(git rev-parse -q --verify "$HUB_ACTUALIZA_DESDE^{commit}" || true)
  fi
  bien "omitido (--sin-bajar)"
fi

paso "3/7 · Dependencias y entorno"
uv sync --quiet
bien "entorno de Python listo"
if ! bash "$RAIZ/scripts/doctor.sh" >/dev/null 2>&1; then
  bash "$RAIZ/scripts/doctor.sh" || true
  mal "al entorno le falta algo imprescindible; no sigo"
  exit 1
fi
bien "doctor sin faltas"

nueva=$(version codigo)
antes=$(version instalada)
if [ -z "$antes" ]; then
  bien "instalación anterior al protocolo de versiones: se pone al día hasta la $nueva"
else
  bien "de la $antes a la $nueva"
fi

paso "4/7 · Copia de las bases y pasos de versión"
# Desde aquí se toca algo, y un fallo dice cómo volver (C-0448).
VOLVER=1
# Las bases tal como están, antes de que los pasos de versión o el código
# nuevo al arrancar les cambien el esquema: con la API de copia de SQLite y en
# sólo lectura (`copia_base.antes_de_actualizar`), nunca con `cp`, que en
# modo WAL da una copia a medias. Sin copia no se sigue.
if ! COPIAS=$(cd "$RAIZ" && HUB_HOME="$HUB_HOME" uv run --quiet python -m hub.copia_base antes); then
  mal "no se pudieron copiar las bases antes de tocarlas: no se ha tocado ninguna y la versión NO se apunta"
  exit 1
fi
if [ -z "$COPIAS" ]; then
  bien "todavía no hay bases que copiar"
else
  while IFS= read -r copia; do bien "copia de antes: $copia"; done <<< "$COPIAS"
fi
pasos=$(version migraciones "$antes" "$nueva" "$RAIZ/scripts/migraciones")
if [ -z "$pasos" ]; then
  bien "ninguno que aplicar"
else
  while IFS= read -r guion; do
    printf '  → %s\n' "$(basename "$guion" .sh)"
    if ! RAIZ="$RAIZ" HUB_HOME="$HUB_HOME" bash "$guion"; then
      mal "falló el paso de la $(basename "$guion" .sh); la versión NO se apunta"
      printf '    arregla lo que diga arriba y vuelve a correr: bash scripts/actualizar.sh --sin-bajar\n' >&2
      exit 1
    fi
  done <<< "$pasos"
fi

paso "5/7 · Servicios"
if [ "$CON_SERVICIOS" -eq 1 ]; then
  generar_unidades
  systemctl --user daemon-reload
  # Sólo los que estaban en marcha: actualizar no enciende el canal ni los
  # encargos de quien no los configuró, ni apaga los de quien sí.
  reiniciados=""
  for servicio in $SERVICIOS_HUB; do
    if systemctl --user is-active --quiet "$servicio"; then
      if ! systemctl --user restart "$servicio"; then
        mal "$servicio no se pudo reiniciar; la versión NO se apunta"
        printf '    journalctl --user -u %s -n 40 --no-pager\n' "$servicio" >&2
        exit 1
      fi
      reiniciados="$reiniciados $servicio"
      bien "$servicio reiniciado"
    fi
  done
  # Desde cuándo una señal es ya del proceso nuevo: un segundo después de que
  # vuelva el último `restart`, que no vuelve hasta que el viejo ha salido. El
  # latido va al segundo, y uno del viejo en este mismo segundo se daría por
  # bueno (C-0448).
  reinicio=$(date -u -d '+1 second' '+%Y-%m-%dT%H:%M:%S+00:00')
else
  bien "sin servicios de systemd: reinicia tú el hub (bash scripts/arrancar.sh --parar y otra vez)"
fi
# El Puente KVM, si viaja en este clon (C-0459): por su propia puerta, nunca a
# mitad de una tarea, y lo que falle ahí es un aviso.
puente_encendido=no
if [ -d "$RAIZ/componentes/puente-kvm" ] && (cd "$RAIZ" && HUB_HOME="$HUB_HOME" uv run --quiet python -c \
     'import sys; from hub import opcionales; sys.exit(0 if opcionales.encendida("puente-kvm") else 1)') 2>/dev/null; then
  puente_encendido=si
fi
reiniciar_puente "$puente_encendido"

paso "6/7 · Asistente"
asiento=$(uv run --quiet python -c "
from hub import registry
print(next((p.asiento for p in registry.cargar() if p.tipo == 'asistente' and p.asiento), ''))
" 2>/dev/null || true)
if [ -n "$asiento" ] && [ -d "$asiento" ]; then
  bash "$RAIZ/scripts/sembrar-asistente.sh" --refrescar "$asiento"
else
  bien "no hay asistente declarado: nada que poner al día"
fi

paso "7/7 · Comprobación"
if [ "$CON_SERVICIOS" -eq 1 ]; then
  url="http://$HUB_HOST:$HUB_PORT"
  codigo=""
  for _ in $(seq 1 40); do
    codigo=$(curl -s -o /dev/null -w '%{http_code}' "$url/guia" || true)
    [ "$codigo" = "200" ] && break
    sleep 0.5
  done
  fallaron=""
  if [ "$codigo" != "200" ]; then
    mal "el hub no contesta en $url (código ${codigo:-sin respuesta})"
    fallaron="hub-web"
  else
    bien "el hub contesta en $url"
  fi
  # Contestar la web no dice que el resto funcione: arrancado no es funcionar
  # (decisión 151). Cada servicio reiniciado tiene que seguir en marcha, y el
  # muestreo, latir (C-0448). La web ya se miró contestando.
  for servicio in $reiniciados; do
    [ "$servicio" = "hub-web" ] && continue
    senal=$(cd "$RAIZ" && HUB_HOME="$HUB_HOME" uv run --quiet python -m hub.salud senal "$servicio" \
              --desde "$reinicio" --espera "$ESPERA_SENAL") || senal="error"
    case "$senal" in
      ok) bien "$servicio da señales de vida" ;;
      sin-medir) bien "$servicio en marcha (no tiene señal propia: sólo se mira que siga en marcha)" ;;
      sin-senal)
        # El primer latido del secretario puede tardar un minuto: avisa, no
        # tumba la actualización. Sin muestreo, en cambio, no se guarda qué
        # ventanas había y tras un apagón no vuelve nada.
        if [ "$servicio" = "hub-secretario" ]; then
          ojo "hub-secretario está en marcha pero aún no late (el primer latido puede tardar un minuto): míralo en Máquina dentro de un rato"
        else
          mal "$servicio está en marcha pero no ha latido en $ESPERA_SENAL s"
          fallaron="$fallaron $servicio"
        fi ;;
      caido)
        mal "$servicio no quedó en marcha"
        fallaron="$fallaron $servicio" ;;
      *)
        mal "no se pudo comprobar $servicio"
        fallaron="$fallaron $servicio" ;;
    esac
  done
  if [ -n "$fallaron" ]; then
    mal "la versión NO se apunta. Lo que dicen al fallar:"
    for servicio in $fallaron; do
      printf '    journalctl --user -u %s -n 40 --no-pager\n' "$servicio" >&2
    done
    exit 1
  fi
fi
version registrar "$nueva"
# Instalada: lo que falle de aquí en adelante (enseñar las novedades) no es
# motivo para volver a ninguna parte.
VOLVER=0
bien "instalada la $nueva"

novedades=$(version novedades "$antes" "$nueva" "$RAIZ/CHANGELOG.md")
if [ -n "$novedades" ]; then
  printf '\n\033[1mQué cambió\033[0m\n\n%s\n' "$novedades"
fi
printf '\nListo. Si alguna pantalla se ve rara, recarga con Ctrl+Shift+R.\n'
