# Cuando algo no funciona

Antes de nada:

```bash
bash scripts/doctor.sh
systemctl --user status hub-web hub-snapshotter hub-canal hub-encargos
journalctl --user -u hub-web -n 40 --no-pager
```

## La página no carga

El servicio puede no estar corriendo, o el puerto estar ocupado por otra cosa.

```bash
systemctl --user restart hub-web
ss -ltn | grep 8787
```

Si el puerto está ocupado por otro programa, instala en otro:
`HUB_PORT=8788 bash scripts/instalar.sh`.

## Cambié el código y no se aplica

**Las plantillas se recargan solas; el Python no.**

```bash
systemctl --user restart hub-web
```

## Cambié algo del navegador y sigo viendo lo viejo

No debería pasar: los estáticos se sirven con `Cache-Control: no-cache`. Si aun
así ocurre, recarga con `Ctrl+Shift+R`.

## Guardé o borré algo y la página no se recargó

Es lo normal: en la mayoría de pantallas, guardar, borrar o crear cambia sólo
la lista que toca y te deja donde estabas. El aviso sale flotando arriba: si
salió bien («Guardado») se va solo; si el hub dice que algo falló, se queda
hasta que lo cierras con la ×. Si ni siquiera llegó a contestar —sin conexión,
o un error del servidor—, sale un diálogo que lo dice. Si alguna vez la lista
parece vieja, recarga la pestaña: lo que ves sale siempre de lo que el hub
tiene guardado.

## No aparece ningún proyecto

Comprueba que tu registro existe y que es YAML válido:

```bash
cat ~/.local/share/hub/projects.yml
uv run python -c "import yaml,pathlib; yaml.safe_load(pathlib.Path.home().joinpath('.local/share/hub/projects.yml').read_text()); print('YAML válido')"
```

El error más común es indentar mal un proyecto y dejarlo fuera de la lista
`proyectos:`.

## Una pantalla tarda y no sé por qué

Cada respuesta que el hub llega a atender (no las que rechaza en la puerta) dice en qué se le fue el tiempo, en la cabecera
`Server-Timing`: en el navegador, DevTools → Red → la petición → «Timing».
Desde la terminal:

```bash
curl -s -D - -o /dev/null localhost:8787/archivos | grep -i server-timing
```

Sale el total y las funciones más lentas, en milisegundos (sólo sus nombres:
nunca rutas ni datos). Si una petición pasa de un segundo, la misma lista va
al final de su línea en `journalctl --user -u hub-web`.

Lo que cuesta leer y casi nunca cambia —el resumen de cada sesión de Claude
Code, los `kit.yml`— se recuerda mientras el archivo no cambie, así que la
segunda visita es mucho más rápida que la primera. Cómo se resuelve cada ruta
de tu registro se recuerda un minuto: si cambias a dónde apunta un enlace que
declaraste como ruta, Archivos tarda hasta un minuto en verlo.

## La pantalla de servicios está vacía

O no tienes Docker, o no está corriendo. Si tienes Docker Desktop en Windows,
tiene que estar abierto. Pulsa **Medir ahora** después.

Si Docker no contesta, el hub enseña la última lectura buena y lo dice — no la
borra.

## Dice que tengo commits sin respaldo y creo que no

Compruébalo:

```bash
git -C <ruta> log --oneline HEAD --not --remotes | wc -l
```

Cuenta los commits que **no alcanza ningún remoto**, no los que van por detrás de
tu rama. Si tu rama local no existe en `origin`, todos sus commits cuentan — y es
correcto: no están en ninguna otra parte.

## La terminal se ve rara o pierde caracteres

Prueba a cambiar el tamaño de letra con `A−`/`A+`: fuerza un remedido. Si
persiste, recarga la pestaña.

## El asistente no responde

```bash
tmux ls | grep asistente
```

Desde el chat, la rueda → **Si algo falla → Terminal** abre su sesión cruda
para ver qué está pasando.
Comprueba también que `claude` está en el PATH y con sesión iniciada.

## Empezar de cero sin perder el registro

Casi todo lo que hay en la base de datos se reconstruye escaneando: proyectos,
repos, mediciones, sesiones de tmux. **Pero no todo.** Hay cosas que creas tú
desde el hub y que hoy sólo viven en la base:

- los **slots** y sus **notas**,
- las ventanas ocultas o descartadas,
- las personas, permisos e historial del **canal**,
- los **mensajes programados**,
- los **encargos** y sus conversaciones.

Por eso, si algo va mal, **aparta** la base en vez de borrarla: así se puede
volver atrás.

```bash
systemctl --user stop hub-web hub-snapshotter hub-canal hub-encargos
mkdir -p ~/.local/share/hub/apartada
mv ~/.local/share/hub/hub.db* ~/.local/share/hub/apartada/
systemctl --user start hub-web hub-snapshotter
```

Si usas el canal o los encargos, arráncalos también (`hub-canal`,
`hub-encargos`): los dos escriben en la base, por eso se paran antes de
apartarla. Si no los activaste nunca, el `stop` sobre ellos no hace nada.

Para volver a la de antes, el mismo `stop`, mueve de vuelta los archivos de
`apartada/` y `start`. Si la base de antes también estaba mal, en
`~/.local/share/hub/respaldos/` hay una copia por día de las dos últimas
semanas (`hub-AAAAMMDD.db`): copia la que quieras como `hub.db`, con los
servicios parados. `projects.yml`, el intercambio, las tareas del orquestador
y sus permisos viven en archivos aparte y no se tocan.

## Contárselo a quien mantiene el hub

Si algo falla y no lo arregla nada de lo de arriba, o echas algo en falta,
**Contar un fallo o una idea** (desde Actualizaciones; con la interfaz nueva,
también en Ajustes; dirección `/incidencia`):

1. Eliges **Un fallo** o **Una idea o mejora**, pones un título y lo cuentas:
   qué hacías, qué esperabas y qué pasó.
2. Debajo están los **datos del equipo** que se añaden: la versión del hub (y
   si falta terminar de actualizar), el commit y si tienes cambios propios en
   el clon (sólo sí o no), el sistema, Python, tmux, Claude Code, la
   interfaz, el navegador, las herramientas opcionales encendidas y cómo está
   cada comprobación de Máquina (sólo su nombre y si está bien). **Nunca**
   rutas, tu usuario, el nombre del equipo, los nombres de Acceso ni
   direcciones. Si no quieres mandarlos, quita «Añadir los datos del equipo».
3. En **Así sale** ves el texto entero tal cual saldrá.
4. **Abrir en GitHub** te lleva al formulario de incidencias del repositorio
   de donde instalaste el hub, ya relleno; allí lo repasas y lo envías con tu
   cuenta. **Lo que envías a GitHub es público**: no pongas contraseñas ni
   nombres de tus proyectos o de otras personas.

El hub no envía nada por su cuenta: es un enlace que abres tú. Si tu hub no
salió de GitHub (o su carpeta no tiene apuntado de dónde salió, `git remote
get-url origin`), no hay a dónde abrirlo: **Copiar el texto** y mándaselo a
quien te lo instaló. Si lo que escribiste es muy largo para ir en el enlace,
la pantalla lo dice: al pulsar «Abrir en GitHub» se copia, y allí lo pegas en
su campo. «Copiar» necesita https o estar en la propia máquina; si el
navegador no deja, el texto queda seleccionado para copiarlo con Ctrl+C.

## Desinstalar

```bash
bash scripts/desinstalar.sh           # servicios fuera, datos intactos
bash scripts/desinstalar.sh --datos   # además borra la carpeta de datos del servicio instalado (te dice antes todo lo que se va)
```

Si preparaste el Puente KVM, antes quita su servicio, que no es del hub y
`desinstalar.sh` no toca: `bash scripts/servicio.sh quitar` en
`componentes/puente-kvm`. Su carpeta de trabajo, con lo leído del Mac, se
queda (`15-puente-kvm.md`).
