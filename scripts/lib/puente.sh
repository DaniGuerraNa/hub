# shellcheck shell=bash
# El Puente KVM al actualizar el hub (C-0459, decisión 442).
#
# Su servicio no es del hub (decisión 438), pero corre el código de este clon:
# sin reiniciarlo, sus pantallas, que se leen del disco, salían nuevas y lo que
# hacían seguía siendo lo de antes (18-nov). Se reinicia por su propia puerta,
# `servicio.sh reiniciar --si-libre`, y sólo si su unidad corre desde
# `componentes/puente-kvm` de ESTE clon (ruta física: con un enlace de por
# medio, comparar a secas no reiniciaría nunca y no lo diría). Nada de aquí
# impide apuntar la versión: el puente no es el hub.
#
#   reiniciar_puente <si|no>    si la herramienta está encendida en Ajustes
reiniciar_puente() {
  local dir="$RAIZ/componentes/puente-kvm" encendido="${1:-no}" fisico unidad_dir salida rc
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
    salida=$(bash "$dir/scripts/servicio.sh" reiniciar --si-libre 2>&1) || rc=$?
    case "$rc" in
      0)
        printf '  ✓ puente-kvm reiniciado: en su terminal, Conversaciones → Reabrir (o una conversación nueva),\n'
        printf '    para que Claude tenga también las herramientas nuevas\n' ;;
      3)
        printf '  ⚠ puente-kvm no se reinicia ahora (%s): cuando acabe,\n' "$salida"
        printf '    systemctl --user restart puente-kvm\n' ;;
      *)
        printf '  ⚠ puente-kvm no se pudo reiniciar: %s\n' "$salida"
        printf '    reinícialo tú cuando no esté trabajando: systemctl --user restart puente-kvm\n' ;;
    esac
  elif [ "$encendido" = "si" ]; then
    printf '  ⚠ El Puente KVM no tiene servicio: si lo tienes en marcha, ciérralo y vuelve a lanzar\n'
    printf '    scripts/arrancar.sh en componentes/puente-kvm, con la misma PUENTE_TRABAJO delante\n'
  fi
}
