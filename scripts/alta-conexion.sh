#!/usr/bin/env bash
# Deja un servidor listo para que el hub pueda entrar, y sin contraseñas.
#
#   bash scripts/alta-conexion.sh vps-ejemplo 203.0.113.10 root 22
#                                 alias        host           usuario puerto
#
# Hace las cuatro cosas que antes había que acertar a mano:
#   1. una clave SÓLO para ese servidor
#   2. la instala allá  ← aquí, y sólo aquí, te pide la contraseña
#   3. escribe su bloque en ~/.ssh/config
#   4. comprueba que entra de verdad
#
# 🔴 La contraseña no se pasa por argumento, ni se guarda, ni la ve este script:
# la pide `ssh-copy-id` directamente. Un secreto en la línea de comandos queda
# en el historial y en `ps`. Y es de un solo uso: después se entra con la clave.
#
# 🔴 Y por eso la clave va SIN passphrase. El despliegue corre sin nadie
# delante, así que una passphrase sólo lo rompería a las tres de la mañana. Lo
# que la protege son sus permisos (600) y que abre ese servidor y ninguno más.
set -euo pipefail

alias_="${1:-}"; host="${2:-}"; usuario="${3:-}"; puerto="${4:-22}"
if [[ -z "$alias_" || -z "$host" || -z "$usuario" ]]; then
  echo "uso: bash scripts/alta-conexion.sh <alias> <host> <usuario> [puerto]" >&2
  echo "     p.ej. vps-ejemplo 203.0.113.10 root 22" >&2
  exit 2
fi
if [[ ! "$alias_" =~ ^[a-z0-9][a-z0-9._-]*$ ]]; then
  echo "«$alias_» no sirve como alias: minúsculas, números, punto y guion" >&2
  exit 2
fi

config="$HOME/.ssh/config"
clave="$HOME/.ssh/$alias_"
mkdir -p "$HOME/.ssh"; chmod 700 "$HOME/.ssh"

# ── 1 · la clave ─────────────────────────────────────────────────────────────
if [[ -f "$clave" ]]; then
  echo "· ya había una clave en $clave; se reutiliza"
else
  ssh-keygen -t ed25519 -f "$clave" -N "" -C "hub -> $alias_" >/dev/null
  echo "· clave nueva en $clave"
fi
chmod 600 "$clave"

# ── 2 · el bloque en ~/.ssh/config ───────────────────────────────────────────
# Antes de tocar nada: un alias repetido hace que ssh use el PRIMERO y el
# segundo no se aplique nunca — un fallo mudo que se diagnostica fatal.
if [[ -f "$config" ]] && grep -qiE "^[[:space:]]*Host[[:space:]]+$alias_[[:space:]]*$" "$config"; then
  echo "· «$alias_» ya está en ~/.ssh/config; no se duplica (revísalo si cambió algo)"
else
  touch "$config"; chmod 600 "$config"
  # La línea en blanco delante evita pegar el bloque al `Host` anterior, que es
  # como un bloque acaba heredando opciones del de arriba.
  {
    printf '\nHost %s\n' "$alias_"
    printf '    HostName %s\n' "$host"
    printf '    Port %s\n' "$puerto"
    printf '    User %s\n' "$usuario"
    printf '    IdentityFile %s\n' "$clave"
    printf '    IdentitiesOnly yes\n'
  } >> "$config"
  echo "· bloque «$alias_» añadido a ~/.ssh/config"
fi

# ── 3 · instalarla allá ──────────────────────────────────────────────────────
if ssh -o BatchMode=yes -o ConnectTimeout=8 "$alias_" true 2>/dev/null; then
  echo "· la clave ya estaba puesta allá: no hace falta la contraseña"
else
  echo
  echo "Ahora te va a pedir la contraseña del servidor. Es la ÚLTIMA vez:"
  echo "la teclea ssh directamente, y este script no la ve ni la guarda."
  echo
  ssh-copy-id -i "$clave.pub" "$alias_"
fi

# ── 4 · comprobar de verdad ──────────────────────────────────────────────────
# 🔴 No basta con que `ssh-copy-id` no haya fallado: lo que importa es entrar
# SIN contraseña, y eso sólo lo dice intentarlo con `BatchMode`.
if ssh -o BatchMode=yes -o ConnectTimeout=10 "$alias_" true 2>/dev/null; then
  echo "· comprobado: se entra con la clave, sin contraseña"
else
  echo "✗ no se pudo entrar con la clave. El servidor puede tener la" >&2
  echo "  autenticación por clave apagada, o el usuario no es ése." >&2
  exit 1
fi

echo
echo "Listo. Da de alta la conexión en el hub, en /conexiones:"
echo "  Alias                    $alias_"
echo "  Host                     $host"
echo "  Usuario                  $usuario"
echo "  Referencia del secreto   ~/.ssh/config#$alias_"
