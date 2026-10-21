# Genera los units de systemd del hub con las rutas REALES de este clon.
# Lo usan `instalar.sh` y `actualizar.sh`: dos copias del mismo bucle acabarían
# generando units distintos, y el que se nota es el de quien actualiza.
#
# Espera definidas: RAIZ, HUB_HOME, HUB_HOST, HUB_PORT, UNIDADES.

SERVICIOS_HUB="hub-web hub-snapshotter hub-canal hub-encargos"

generar_unidades() {
  local uv servicio destino
  uv=$(command -v uv)
  mkdir -p "$UNIDADES"
  for servicio in $SERVICIOS_HUB; do
    destino="$UNIDADES/$servicio.service"
    sed -e "s|@RAIZ@|$RAIZ|g" \
        -e "s|@HUB_HOME@|$HUB_HOME|g" \
        -e "s|@UV@|$uv|g" \
        -e "s|@PATH@|$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin|g" \
        -e "s|@HOST@|$HUB_HOST|g" \
        -e "s|@PUERTO@|$HUB_PORT|g" \
        "$RAIZ/scripts/$servicio.service.plantilla" > "$destino.nuevo"
    # 🔴 Un unit retocado a mano no se pierde en silencio: si cambia, el de
    # antes queda al lado. Regenerar es lo correcto —lleva lo de la versión
    # nueva—, pero lo que alguien escribió ahí es trabajo suyo.
    if [ -f "$destino" ] && ! cmp -s "$destino" "$destino.nuevo"; then
      cp "$destino" "$destino.antes"
    fi
    mv "$destino.nuevo" "$destino"
    printf '  ✓ %s\n' "$destino"
  done
}

# Lo que ya hay instalado manda: actualizar no cambia de puerto ni de datos a
# nadie. Se lee del unit de la web, que es donde instalar.sh lo escribió.
leer_unidad_instalada() {
  local web="$UNIDADES/hub-web.service"
  [ -f "$web" ] || return 1
  HUB_HOME=$(sed -n 's/^Environment=HUB_HOME=//p' "$web" | head -1)
  HUB_HOST=$(sed -n 's/.*--host \([^ ]*\).*/\1/p' "$web" | head -1)
  HUB_PORT=$(sed -n 's/.*--port \([0-9]*\).*/\1/p' "$web" | head -1)
  [ -n "$HUB_HOME" ] && [ -n "$HUB_HOST" ] && [ -n "$HUB_PORT" ]
}
