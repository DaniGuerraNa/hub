# shellcheck shell=bash
# El Puente KVM al actualizar el hub (C-0459, decisión 442; C-0470, decisión 446).
#
# Su servicio no es del hub (decisión 438), pero corre el código de este clon:
# sin reiniciarlo, sus pantallas, que se leen del disco, salían nuevas y lo que
# hacían seguía siendo lo de antes (18-nov). Se reinicia por su propia puerta,
# `servicio.sh reiniciar --si-libre`, y sólo si su unidad corre desde
# `componentes/puente-kvm` de ESTE clon (ruta física: con un enlace de por
# medio, comparar a secas no reiniciaría nunca y no lo diría). Nada de aquí
# impide apuntar la versión: el puente no es el hub.
#
# Cómo quedó se apunta en `HUB_HOME/actualizacion/puente.json` para que
# Actualizaciones lo cuente (446). Ni ahí ni en el registro va el motivo de
# «ocupado»: lleva nombres del trabajo (la tarea en curso), y el registro se ve
# también desde el teléfono (438). Lo que no se pudo hacer aquí se hace con el
# botón «Reiniciar el puente» de su propia pantalla, no con un comando. Si falló
# por otra cosa, sí va la última línea de su salida: es de `systemctl` o la de
# «no pude preguntarle al puente» (rc 4), sin nombres del trabajo, y sin ella
# no se sabría qué mirar.
#
#   reiniciar_puente <si|no>    si la herramienta está encendida en Ajustes
reiniciar_puente() {
  local dir="$RAIZ/componentes/puente-kvm" encendido="${1:-no}" fisico unidad_dir rc salida
  [ -d "$dir" ] || return 0
  fisico=$(cd "$dir" && pwd -P)
  if systemctl --user cat puente-kvm >/dev/null 2>&1; then
    unidad_dir=$(systemctl --user show -p WorkingDirectory --value puente-kvm 2>/dev/null || true)
    if [ -n "$unidad_dir" ] && [ -d "$unidad_dir" ]; then
      unidad_dir=$(cd "$unidad_dir" && pwd -P)
    fi
    # El de otro clon (o el repositorio del puente) no es nuestro; parado se queda parado.
    [ "$unidad_dir" = "$fisico" ] || return 0
    systemctl --user is-active --quiet puente-kvm || return 0
    rc=0
    # Su salida no se enseña entera: con rc 3 es el motivo (ver arriba).
    salida=$(bash "$dir/scripts/servicio.sh" reiniciar --si-libre 2>&1) || rc=$?
    case "$rc" in
      0)
        _apuntar_puente reiniciado
        printf '  ✓ puente-kvm reiniciado: en su pantalla, «Reabrir la conversación de Claude»,\n'
        printf '    para que Claude tenga también las herramientas nuevas\n' ;;
      3)
        _apuntar_puente ocupado
        printf '  ⚠ puente-kvm no se reinicia ahora: estaba ocupado. Cuando acabe, ábrelo y\n'
        printf '    pulsa «Reiniciar el puente»\n' ;;
      *)
        _apuntar_puente no_pudo
        salida=$(printf '%s\n' "$salida" | sed '/^[[:space:]]*$/d' | tail -n 1)
        printf '  ⚠ puente-kvm no se pudo reiniciar%s\n' "${salida:+: $salida}"
        printf '    Ábrelo: si su pantalla dice que sigue con el código de antes, pulsa\n'
        printf '    «Reiniciar el puente»; si no abre, mira el registro de su servicio\n' ;;
    esac
  elif [ "$encendido" = "si" ]; then
    _apuntar_puente sin_servicio
    printf '  ⚠ El Puente KVM no tiene servicio: si lo tienes en marcha, ciérralo y vuelve a lanzar\n'
    printf '    scripts/arrancar.sh en componentes/puente-kvm, con la misma PUENTE_TRABAJO delante\n'
  fi
}

# Escribe {"puente": <cómo quedó>, "t": <epoch>} por un temporal y `mv`: la
# pantalla puede leerlo a la vez. Sin HUB_HOME, o si no se puede escribir, no
# se apunta y ya: no es motivo para tumbar la actualización.
_apuntar_puente() {
  local carpeta tmp
  [ -n "${HUB_HOME:-}" ] || return 0
  carpeta="$HUB_HOME/actualizacion"
  mkdir -p "$carpeta" 2>/dev/null || return 0
  tmp="$carpeta/.puente.json.$$"
  if printf '{"puente": "%s", "t": %d}\n' "$1" "$(date +%s)" > "$tmp" 2>/dev/null; then
    mv -f "$tmp" "$carpeta/puente.json" 2>/dev/null || rm -f "$tmp" 2>/dev/null || true
  else
    rm -f "$tmp" 2>/dev/null || true
  fi
  return 0
}
