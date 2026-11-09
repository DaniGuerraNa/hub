# shellcheck shell=bash
# El hub sólo escucha en esta máquina (regla dura 8, C-0112).
#
# Lo comprueban los tres guiones que deciden el `--host` —instalar.sh lo
# escribe en el unit, actualizar.sh lo conserva, arrancar.sh lo lanza a
# mano—, y otra vez la web al arrancar (`config.exigir_loopback`). Con
# `0.0.0.0` la terminal quedaría abierta a la red local. Para entrar desde
# otro aparato está /acceso, por la red privada, que llega por loopback.
exigir_loopback() {
  case "$1" in
    localhost | 127.* | ::1 | "[::1]") return 0 ;;
  esac
  printf '  ✗ HUB_HOST=%s: el hub sólo escucha en esta máquina (127.0.0.1).\n' "$1" >&2
  printf '    Para entrar desde otro aparato, mira /acceso en el hub.\n' >&2
  exit 1
}
