#!/usr/bin/env bash
# La sala limpia: instala el hub o un kit como lo haría alguien que acaba de
# clonar, en un contenedor sin nada, con un Claude sin contexto.
#
#   bash scripts/sala-limpia/sala.sh construir                 # la imagen, una vez
#   bash scripts/sala-limpia/sala.sh arrancar [url-del-hub]    # contenedor nuevo + clon del hub
#   bash scripts/sala-limpia/sala.sh hub                       # «instala este repo»
#   bash scripts/sala-limpia/sala.sh kit <ruta-local> ["petición"]   # copia el kit y pide instalarlo
#   bash scripts/sala-limpia/sala.sh pedir <etiqueta> "<petición>" [carpeta]
#   bash scripts/sala-limpia/sala.sh ver <etiqueta>            # el transcript
#   bash scripts/sala-limpia/sala.sh dentro "<comando>"        # comprobar desde dentro (curl, tmux ls…)
#   bash scripts/sala-limpia/sala.sh borrar                    # tira el contenedor
#
# 🔴 Dos cosas que no son negociables:
#   1. Las credenciales de Claude se COPIAN al contenedor desde ~/.claude/
#      (el OAuth de quien corre esto). Viven sólo en ese contenedor, en esta
#      máquina, y se van con `borrar`. No se publica ni se comparte una imagen
#      con ellas dentro: por eso van en `arrancar`, nunca en el Dockerfile.
#   2. El hub dentro escucha en 127.0.0.1 (regla dura 8): no se mapean puertos.
#      Se comprueba con `dentro "curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8787/"`.
#
# El procedimiento entero y cómo leer los resultados: conocimiento/08-sala-limpia.md
set -euo pipefail
AQUI=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
IMAGEN=${SALA_IMAGEN:-hub-sala-limpia}
NOMBRE=${SALA_CONTENEDOR:-hub-sala}
HUB_URL_DEFECTO="https://github.com/DaniGuerraNa/hub.git"

persona() { docker exec -u persona "$NOMBRE" bash -lc "$*"; }

case "${1:-}" in
  construir)
    docker build -t "$IMAGEN" "$AQUI"
    docker run --rm "$IMAGEN" bash -lc 'claude --version; uv --version; tmux -V; git --version; whoami'
    ;;
  arrancar)
    docker rm -f "$NOMBRE" >/dev/null 2>&1 || true
    docker run -d --name "$NOMBRE" "$IMAGEN" sleep infinity >/dev/null
    [ -f "$HOME/.claude/.credentials.json" ] || { echo "no hay ~/.claude/.credentials.json: inicia sesión en claude primero" >&2; exit 1; }
    docker cp "$HOME/.claude/.credentials.json" "$NOMBRE:/tmp/cred.json"
    docker cp "$AQUI/persona.sh" "$NOMBRE:/tmp/persona.sh"
    docker exec -u root "$NOMBRE" bash -c 'chown persona:persona /tmp/cred.json /tmp/persona.sh'
    persona 'mkdir -p ~/.claude ~/salas && mv /tmp/cred.json ~/.claude/.credentials.json && chmod 600 ~/.claude/.credentials.json && mv /tmp/persona.sh ~/persona.sh && chmod +x ~/persona.sh'
    persona "git clone -q '${2:-$HUB_URL_DEFECTO}' ~/hub && echo \"hub clonado: \$(git -C ~/hub log --oneline -1)\""
    persona 'claude -p --model sonnet "di sólo: hola" | tail -1'
    ;;
  hub)
    persona '~/persona.sh ~/hub instalar-hub "instala este repo"'
    echo; echo "── comprobación ──"
    persona 'curl -s -o /dev/null -w "hub en 8787: %{http_code}\n" http://127.0.0.1:8787/ || true; pgrep -af "hub.web|hub.snapshotter" | grep -v pgrep || echo "(ningún proceso del hub corriendo)"'
    ;;
  kit)
    [ -n "${2:-}" ] || { echo "falta la ruta local del kit" >&2; exit 1; }
    ruta=$(cd "$2" && pwd); id=$(basename "$ruta")
    docker cp "$ruta" "$NOMBRE:/tmp/$id"
    docker exec -u root "$NOMBRE" bash -c "chown -R persona:persona /tmp/$id"
    persona "rm -rf ~/$id && mv /tmp/$id ~/$id && rm -rf ~/$id/.git"
    peticion=${3:-"instala el kit que está en ~/$id en una carpeta nueva ~/workspace; mi nombre es Persona y mi rol Backend Java"}
    persona "~/persona.sh ~/hub kit-$id \"$peticion\""
    echo; echo "── comprobación ──"
    persona 'find ~/workspace -maxdepth 3 -type f 2>/dev/null | sort || echo "(no hay ~/workspace)"'
    ;;
  pedir)
    [ -n "${3:-}" ] || { echo "uso: pedir <etiqueta> \"<petición>\" [carpeta]" >&2; exit 1; }
    persona "~/persona.sh ${4:-~/hub} $2 \"$3\""
    ;;
  ver)
    persona "cat ~/salas/${2:-instalar-hub}.log"
    ;;
  dentro)
    persona "${2:-bash}"
    ;;
  borrar)
    docker rm -f "$NOMBRE" >/dev/null && echo "contenedor $NOMBRE eliminado (la imagen $IMAGEN se queda)"
    ;;
  *)
    sed -n '2,20p' "$0"; exit 1 ;;
esac
