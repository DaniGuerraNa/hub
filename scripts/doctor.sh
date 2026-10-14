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
# `$USER` no siempre existe (docker exec, algunos sudo y lanzadores), y con
# `set -u` reventaba justo al comprobar el linger. Visto instalando en limpio.
YO=${USER:-$(id -un)}

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

# Python 3.12+, pero el que importa es el que usa `uv`, no el del sistema: el
# hub corre siempre con `uv run`, y uv descarga su propio Python si hace falta.
# 🔴 Mirar `python3` bloqueaba Ubuntu 22.04 (trae 3.10) en un callejón sin
# salida: el consejo era `uv python install 3.12`, que no cambia `python3`, así
# que el diagnóstico seguía diciendo «falta» después de hacerle caso (visto
# instalando en limpio el 14-oct).
if tiene uv; then
  py=$(uv python find '>=3.12' 2>/dev/null || true)
  if [ -n "$py" ]; then
    linea "$ok" "python" "$("$py" -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null) (el que usa uv)"
  else
    linea "$ojo" "python" "no hay 3.12 todavía: uv lo descarga solo al instalar"
  fi
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
  # Que systemd responda AHORA no dice que vaya a seguir: sin linger se apaga
  # entero al cerrar la última sesión de login (decisión 155).
  if [ "$(loginctl show-user "$YO" -p Linger --value 2>/dev/null)" = "yes" ]; then
    linea "$ok" "linger" "activo: el hub sobrevive a cerrar la terminal"
  else
    avisos=$((avisos + 1))
    linea "$ojo" "linger" "apagado: el hub morirá al cerrar la última sesión de login"
    printf '        → arréglalo con: loginctl enable-linger %s\n' "$YO"
  fi
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
# Con `ss` o `lsof` se lista; sin ellos, bash intenta conectar. Afirmar que está
# libre sin haberlo mirado sería peor que no decirlo.
if tiene ss; then ocupado=$(ss -ltn 2>/dev/null | grep -c ":$puerto ")
elif tiene lsof; then ocupado=$(lsof -iTCP:"$puerto" -sTCP:LISTEN -t 2>/dev/null | wc -l)
# Sin ninguno de los dos, bash sabe intentar la conexión él solo.
elif (exec 3<>"/dev/tcp/127.0.0.1/$puerto") 2>/dev/null; then ocupado=1
else ocupado=0
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
