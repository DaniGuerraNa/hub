#!/usr/bin/env bash
# Diagnostica el entorno. NO instala nada.
#
# Bash puro y sin dependencias a propósito: esto tiene que poder correr antes de
# que exista el entorno de Python, que es justo cuando hace falta saber qué falta.
#
# Cada ausencia se reporta CON SU CONSECUENCIA. «Falta docker» no le dice nada a
# quien acaba de clonar; «sin docker, la pantalla de servicios queda vacía» sí.
#
#   0  todo lo imprescindible está
#   1  falta algo imprescindible
set -uo pipefail

falta=0
avisos=0

if [ -t 1 ]; then
  ok=$'\033[32m  ok \033[0m'; mal=$'\033[31mFALTA\033[0m'; ojo=$'\033[33m ojo \033[0m'
else
  ok="  ok "; mal="FALTA"; ojo=" ojo "
fi

titulo() { printf '\n%s\n' "$1"; }
linea()  { printf '  [%s] %-16s %s\n' "$1" "$2" "$3"; }

# `command -v` vale para binarios del sistema. Ojo: también resuelve alias y
# funciones de shell, y por eso el hub usa `shutil.which` para `rg` — ahí `rg`
# era un alias y la medición de uso se saltaba en silencio.
tiene() { command -v "$1" >/dev/null 2>&1; }

imprescindible() {   # nombre, consecuencia, cómo instalarlo
  if tiene "$1"; then linea "$ok" "$1" "$(command -v "$1")"
  else linea "$mal" "$1" "$2"; printf '        → %s\n' "$3"; falta=1
  fi
}

opcional() {         # nombre, consecuencia de no tenerlo
  if tiene "$1"; then linea "$ok" "$1" "$(command -v "$1")"
  else linea "$ojo" "$1" "$2"; avisos=$((avisos + 1))
  fi
}

printf 'Hub — diagnóstico del entorno\n'

titulo 'Imprescindibles'
imprescindible git    "sin git no hay respaldo que medir ni kits que instalar" \
                      "sudo apt install git"
imprescindible tmux   "el hub vive sobre tmux: sin él no hay sesiones ni terminal" \
                      "sudo apt install tmux"
imprescindible uv     "es lo que corre el hub y resuelve sus dependencias" \
                      "curl -LsSf https://astral.sh/uv/install.sh | sh"
imprescindible claude "sin Claude Code no hay asistente, ni medición de uso, ni agentes" \
                      "https://claude.com/claude-code"

# Python: no basta con que exista, tiene que ser 3.12 o más.
if tiene python3; then
  version=$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null || echo "?")
  mayor=${version%%.*}; menor=${version##*.}
  if [ "${mayor:-0}" -gt 3 ] || { [ "${mayor:-0}" -eq 3 ] && [ "${menor:-0}" -ge 12 ]; }; then
    linea "$ok" "python3" "$version"
  else
    linea "$mal" "python3" "hace falta 3.12 o superior; tienes $version"
    printf '        → uv se encarga: `uv python install 3.12`\n'
    falta=1
  fi
else
  linea "$mal" "python3" "no está"
  printf '        → sudo apt install python3\n'
  falta=1
fi

# systemd de usuario: es lo que arranca los dos servicios solos al abrir sesión.
# 🔴 NO es imprescindible. Lo era, y con eso `--sin-servicios` no servía para
# el único caso en que hace falta: sin systemd el doctor fallaba, el instalador
# no seguía, y en un contenedor o un Linux sin systemd de usuario la única
# salida que se ofrecía era «edita /etc/wsl.conf y reinicia Windows» — que la
# primera instalación en limpio (3-sep) siguió al pie de la letra dentro de un
# Ubuntu que no era WSL.
if systemctl --user show-environment >/dev/null 2>&1; then
  linea "$ok" "systemd --user" "activo: los servicios arrancan solos"
else
  avisos=$((avisos + 1)); linea "$ojo" "systemd --user" "no responde: el hub no arrancará solo, pero se puede arrancar a mano"
  if grep -qi microsoft /proc/version 2>/dev/null && [ ! -f /.dockerenv ]; then
    printf '        → en WSL: añade `[boot]\\nsystemd=true` a /etc/wsl.conf y `wsl --shutdown` desde Windows\n'
  fi
  printf '        → o instala sin servicios: `bash scripts/instalar.sh --sin-servicios` y luego `bash scripts/arrancar.sh`\n'
fi

titulo 'Opcionales — el hub funciona sin ellos, con menos'
opcional docker "sin docker, /servicios queda vacía: no hay contenedores que atribuir"
opcional rg     "sin ripgrep la medición de uso cae a grep, bastante más lenta"

titulo 'Entorno'
if grep -qi microsoft /proc/version 2>/dev/null; then
  linea "$ok" "plataforma" "WSL"
elif [ "$(uname -s)" = "Linux" ]; then
  linea "$ok" "plataforma" "Linux"
else
  linea "$ojo" "plataforma" "$(uname -s): probado en WSL y Linux, aquí no"
  avisos=$((avisos + 1))
fi

case ":$PATH:" in
  *":$HOME/.local/bin:"*) linea "$ok" "PATH" "~/.local/bin está" ;;
  *) linea "$ojo" "PATH" "~/.local/bin no está: uv y claude pueden no encontrarse"
     printf '        → añade `export PATH="$HOME/.local/bin:$PATH"` a ~/.bashrc\n'
     avisos=$((avisos + 1)) ;;
esac

puerto=${HUB_PORT:-8787}
# Sin `ss` ni `lsof` no se puede afirmar nada, y afirmar que está libre sin
# haberlo mirado es peor que no decirlo.
if tiene ss; then ocupado=$(ss -ltn 2>/dev/null | grep -c ":$puerto ")
elif tiene lsof; then ocupado=$(lsof -iTCP:"$puerto" -sTCP:LISTEN -t 2>/dev/null | wc -l)
else ocupado=""
fi
if [ -z "$ocupado" ]; then
  linea "$ojo" "puerto $puerto" "no se pudo comprobar (falta ss y lsof)"
elif [ "$ocupado" -gt 0 ]; then
  linea "$ojo" "puerto $puerto" "ya hay algo escuchando; si no es el hub, usa HUB_PORT"
  avisos=$((avisos + 1))
else
  linea "$ok" "puerto $puerto" "libre"
fi

printf '\n'
if [ "$falta" -ne 0 ]; then
  printf 'Falta algo imprescindible. Instálalo y vuelve a pasar el diagnóstico.\n'
  exit 1
fi
printf 'Todo lo imprescindible está'
[ "$avisos" -gt 0 ] && printf ' (%d aviso(s) arriba)' "$avisos"
printf '.\nSiguiente: bash scripts/instalar.sh\n'
exit 0
