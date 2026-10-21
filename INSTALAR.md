# Instalar el hub

El hub es un índice de proyectos, sesiones de trabajo y capacidades. Corre en tu
máquina y escucha sólo en `127.0.0.1`. Por sí solo no manda nada a ninguna
parte; lo único que sale de la máquina son las piezas **opcionales** que tú
actives: el canal y los encargos por Telegram, y los despliegues de encargos a
un servidor tuyo por SSH.

## Lo que necesitas

**Imprescindible:** WSL o Linux, `git`, `tmux`, `curl`,
[`uv`](https://astral.sh/uv) y [Claude Code](https://claude.com/claude-code).
**Python no hace falta instalarlo**: el proyecto fija la 3.12 (`.python-version`)
y `uv` la descarga; el `python3` de tu sistema da igual.

**Opcional:** `systemd --user` (sin él, los servicios se arrancan a mano; ver
abajo), `docker` (sin él, la pantalla de servicios queda vacía) y `rg` (sin él,
la medición de uso cae a `grep` y tarda más).

Probado en WSL. En Linux debería funcionar igual; en macOS no, porque no hay
`systemd --user` y los servicios habría que arrancarlos de otra forma.

## Opción A — que lo instale Claude

```bash
git clone <url-del-repo> hub
cd hub
```

Abre Claude Code **en esa carpeta** y dile:

> instala este repo

El repositorio trae la skill `instalar-hub`, que le dice exactamente qué
comprobar, qué pedirte antes de tocar tu sistema y cómo verificar que quedó
funcionando. **No instalará nada sin preguntarte primero.**

## Opción B — a mano

```bash
bash scripts/doctor.sh      # qué falta, y qué implica que falte
bash scripts/instalar.sh    # instala, arranca y comprueba
```

El diagnóstico no instala nada: sólo mira. El instalador es idempotente —puedes
correrlo las veces que quieras— y **nunca pisa tu registro** si ya existe.

Cuando termine, el hub está en <http://127.0.0.1:8787>.

**Sin `systemd --user`** —un contenedor, un Linux sin systemd de usuario, WSL
antes de activarlo— el instalador omite los servicios y te lo dice. No es un
error: el hub se arranca a mano, los dos procesos a la vez, con

```bash
bash scripts/arrancar.sh            # web + snapshotter, en segundo plano
bash scripts/arrancar.sh --parar
```

Sólo la web no basta: el snapshotter es quien relee `projects.yml` y muestrea
tmux, y sin él el hub parece instalado sin estarlo.

## Qué te ha dejado

| | |
|---|---|
| `~/.local/share/hub/projects.yml` | **Tu registro.** Aquí declaras tus proyectos. Es un archivo de texto a propósito: si algo se rompe, se arregla con un editor |
| `~/.local/share/hub/hub.db` | El índice, y también tus slots, notas, canal, programados y encargos. No lo borres: si algo falla, apártalo (ver `conocimiento/06-problemas.md`) |
| `~/.config/systemd/user/hub-*.service` | Cuatro servicios, generados con las rutas de tu clon: `hub-web` y `hub-snapshotter` arrancados; `hub-canal` y `hub-encargos` instalados **parados** |

Los dos parados son los relés de Telegram (el canal de consulta con sus avisos,
y los encargos). Sin su archivo de ajustes no tienen token, y por eso no se
arrancan. Cuando los configures (`canal.yml`, `encargos.yml`; cómo, en
`conocimiento/10-mas-pantallas.md`):

```bash
systemctl --user enable --now hub-canal       # y/o hub-encargos
```

Tus datos **no viven dentro del repo**: así puedes actualizar el hub con un
`git pull` sin que choque con lo tuyo.

## El primer proyecto

La portada trae una guía mientras el registro esté vacío. A partir de ahí hay
tres caminos, según lo que tengas:

- **Empezar algo nuevo** → botón **«Proyecto nuevo»** en la portada. Crea la
  carpeta vacía, la da de alta y lanza un agente que la monta contigo delante.
- **Tienes repos que no puedes tocar** —de otro equipo, o sin estructura común—
  → el mismo botón, poniendo esos repos en «Repos que ya existen». La carpeta
  que creas queda como **asiento** desde el que orquestas: ahí va la capa base,
  los kits y el estado. Los repos declarados se miden y no se tocan, porque el
  permiso del agente se acota al asiento.
- **Registrar algo que ya existe** → abre Claude Code en la carpeta del hub y
  dile **«anexa mi proyecto»**. La skill `anexar-proyecto` lo registra y detecta
  cuál de tus documentos lleva el estado, sin crear uno nuevo. No es un botón
  porque escribe dentro de un repo que ya es tuyo.
- **A mano** → `~/.local/share/hub/projects.yml` trae un ejemplo comentado.

Para fabricar una capacidad reutilizable, el botón **«Kit nuevo»** está en
`/inventario` → Kits.

## El asistente

Un chat que te sigue por todas las pantallas y responde sobre tus proyectos. Por
debajo es `claude` corriendo en una ventana de tmux; el hub pinta su transcript.
Es de **consulta**: lee tus proyectos y no escribe en ellos.

```bash
bash scripts/sembrar-asistente.sh
```

El script lo declara solo en el registro. Si no lo quieres, no lo siembres: sin
ese proyecto la pestaña no se pinta. Después, empieza por la Guía (`/guia`):
sus botones «Guíame» se lo preguntan al asistente.

## Comprobar y desinstalar

```bash
systemctl --user status hub-web hub-snapshotter hub-canal hub-encargos   # cómo van
journalctl --user -u hub-web -f                   # qué está haciendo
bash scripts/desinstalar.sh                       # servicios fuera, datos intactos
bash scripts/desinstalar.sh --datos               # además borra ~/.local/share/hub
```

## Instalar en otro sitio o en otro puerto

Los datos y el puerto salen de variables de entorno:

```bash
HUB_HOME=/tmp/hub-pruebas HUB_PORT=8788 bash scripts/instalar.sh --sin-servicios
```

🔴 **`--sin-servicios` no es opcional si ya tienes el hub instalado.** Los cuatro
units de systemd se llaman siempre igual (`hub-web`, `hub-snapshotter`,
`hub-canal`, `hub-encargos`), así que una
segunda instalación **reescribe los de la primera** y te deja el hub de verdad
sirviendo desde la carpeta de pruebas. Cambiar `HUB_HOME` y `HUB_PORT` no
evita eso: aísla los datos, no los servicios.

Con ese flag se hace todo menos systemd, y el instalador te imprime la orden
para arrancarlo a mano: `bash scripts/arrancar.sh` con tus `HUB_HOME` y
`HUB_PORT`, que levanta **los dos procesos**, web y snapshotter. Es también la
forma de usar el hub en una máquina sin `systemd --user` (macOS, algunos
contenedores).

### Todas las variables de entorno

Ninguna hace falta para usar el hub: todas tienen un valor por defecto que
funciona. Están aquí porque la que no se documenta no existe.

| Variable | Por defecto | Para qué |
|---|---|---|
| `HUB_HOME` | `~/.local/share/hub` | Dónde viven tus datos: el registro, el índice y los kits |
| `HUB_PORT` | `8787` | Puerto de la web. Se lee **al instalar** y queda escrito en los cuatro units (en el `ExecStart` de `hub-web` y como `Environment=HUB_PORT` en todos), así que el pánico de `hub-canal` comprueba el puerto bueno. Cambiarlo después es reinstalar |
| `HUB_HOST` | `127.0.0.1` | 🔴 **No lo cambies.** Es lo que mantiene el hub fuera de la red — ver más abajo |
| `HUB_PROJECTS_YML` | `$HUB_HOME/projects.yml` | El registro, si lo quieres en otro sitio |
| `HUB_KITS` | `$HUB_HOME/kits` | Dónde se instalan los kits |
| `HUB_INTERVALO` | `20` | Cada cuántos segundos muestrea el snapshotter |
| `HUB_RETENCION` | `50` | Cuántas muestras se guardan antes de podar |
| `HUB_TMUX_SOCKET` | *(ninguno)* | Servidor de tmux aparte (`tmux -L`). Los tests lo usan para no tocar tus sesiones |
| `HUB_CONTEXTO_FICHERO` | `$HUB_HOME/asistente-contexto.json` | Dónde escribe el statusline del asistente su porcentaje de contexto. La leen el hub y el script, y el hub se la pasa al asistente al arrancarlo, así que los dos miran el mismo archivo |
| `HUB_RESPALDO` | `$HUB_HOME/respaldos` | Dónde deja el snapshotter la copia diaria de `hub.db` (se guardan las 14 últimas). Apúntala a otro disco si quieres que sobreviva a éste |
| `HUB_BUSCAR_VERSIONES` | `1` | Con `0`, el hub no mira si hay versión nueva publicada (un `git ls-remote` al día como mucho) |
| `HUB_BIN` | `~/.local/bin` | Dónde enlaza `sembrar-asistente.sh` el comando `hub` |
| `HUB_STATUSLINE_SIGUIENTE` | *(ninguno)* | Ver abajo |
| `HUB_COMANDO_CLAUDE` | `claude` | Lo que «Restaurar» deja escrito (sin Enter) en las ventanas que tenían Claude Code. Va en el entorno de `hub-web` |
| `HUB_ACCESO_YML` | `$HUB_HOME/acceso.yml` | La puerta de acceso remoto: nombres admitidos y aparatos dados de alta |
| `HUB_CANAL_YML` | `$HUB_HOME/canal.yml` | Ajustes del canal de consulta: el **puntero** al token del bot, nunca el token |
| `HUB_ENCARGOS_YML` | `$HUB_HOME/encargos.yml` | Lo mismo para el bot de encargos, que es otro bot con otro token |
| `HUB_COMANDOS_YML` | `$HUB_HOME/comandos.yml` | Los comandos preparados de Archivos. Sin archivo, ninguno |
| `HUB_TRANSCRIPTS` | `~/.claude/projects` | Dónde busca los transcripts de Claude Code la pantalla de Consumo |
| `HUB_CADDY`, `HUB_DOMINIO_ENCARGOS` | *(ninguno)* | Sólo para `scripts/desplegar-encargo.sh` y `desplegar-chat.sh`: el Caddy del servidor y el dominio bajo el que se publica cada encargo. El relé los pasa desde `encargos.yml` |

🔴 **`HUB_STATUSLINE_SIGUIENTE`, si ya tienes una statusline.** Sembrar el
asistente le pone la suya, y en Claude Code una statusline de proyecto
**sustituye** a la global, no se suma. Si la tuya registra cuota o pinta un HUD,
dejaría de hacerlo mientras trabajas en el asistente, y sin decir nada. Pon ahí
el comando de la tuya y el hub le pasa el payload intacto:

```json
{ "env": { "HUB_STATUSLINE_SIGUIENTE": "/ruta/a/tu-statusline.sh" } }
```

### Actualizar

Un solo comando, en la carpeta del hub:

```bash
bash scripts/actualizar.sh
```

Baja la versión (sólo si avanza en línea recta: si tu clon tiene commits
propios, para y lo dice), resuelve dependencias, aplica los pasos propios de
cada versión que cruces (`scripts/migraciones/`), regenera los servicios con
**tu** puerto y **tu** carpeta de datos, reinicia los que estaban en marcha,
pone al día el asistente y comprueba que el hub contesta. Al final te enseña lo
que cambió, sacado de [`CHANGELOG.md`](CHANGELOG.md). Si algo falla, para ahí y
la versión no se da por instalada: volver a correrlo retoma.

`git pull` y reiniciar **no basta**: deja el código nuevo corriendo con los
servicios y el asistente de antes. El hub lo detecta —compara la versión del
código con la que `actualizar.sh` apuntó al terminar, en
`$HUB_HOME/version.json`— y lo dice arriba en todas las pantallas.

🔴 **Si lo instalaste antes de la 0.2.0** no tienes todavía `actualizar.sh`:

```bash
git pull && bash scripts/actualizar.sh --sin-bajar
```

**Cómo te enteras de que hay versión nueva:** el hub mira una vez al día las
etiquetas del repo publicado (`git ls-remote`, no baja nada) y, si hay una más
nueva que la tuya, lo dice arriba en todas las pantallas, con un enlace a sus
novedades. **Nunca se actualiza solo.** Es la única consulta a internet que
hace por su cuenta; se apaga con `HUB_BUSCAR_VERSIONES=0`.

Y si **mueves la carpeta del clon**, vuelve a correr `bash scripts/instalar.sh`:
la ruta va escrita dentro de los units, y sin regenerarlos apuntan a donde ya no
estás.

## 🔴 La terminal da acceso de shell

`/terminal` te ata a una sesión de tmux real. Por eso el hub escucha **sólo en
`127.0.0.1`**, y **no se abre el puerto a la red**, ni siquiera «un momento
para probar».

Para usarlo desde el móvil o desde otra PC está `/acceso`, que no abre ningún
puerto: se entra por una **red privada** (Tailscale, con `tailscale serve`
apuntando a la dirección local), sólo por los nombres exactos que declares en
`acceso.yml`, y sólo desde **aparatos dados de alta con un QR**. El primero se da
de alta desde una terminal de la propia máquina:

```bash
uv run python -m hub.acceso alta "Mi móvil"     # imprime el QR
```

La terminal pide además el interruptor **«terminal remota»** de `/acceso`, que
está apagado de fábrica y se vuelve a apagar cada vez que `hub-web` reinicia.

Lo que esa puerta **no** cubre: un aparato que ya esté aprobado en tu red
privada y falsee la cabecera `Host: localhost` pasa como si fuera de casa. Ahí
te defiende la aprobación manual de aparatos de la red privada (en Tailscale,
el *tailnet lock*), no el hub.

Dos cosas que conviene saber, porque no se deducen de lo anterior:

- **`HUB_HOST` es la palanca que quita esa protección.** `HUB_HOST=0.0.0.0` deja
  el hub —y la terminal— accesible desde toda tu red. No lo pongas: para entrar
  de fuera está `/acceso`.
- **Un navegador puede alcanzar `127.0.0.1`.** Que el hub sea local te protege de
  la red, no de una página web abierta en tu propio navegador. Mientras el hub
  esté levantado, trátalo como lo que es: una consola con tu shell dentro.

## Los scripts

Los que usas: `doctor.sh`, `instalar.sh`, `arrancar.sh`, `desinstalar.sh` y
`sembrar-asistente.sh` (arriba), `kit.sh` (kits, ver `FLUJOS.md`),
`alta-conexion.sh` y `guardar-secreto.sh` (conexiones sin pegar el secreto).
El resto es para piezas opcionales o para mantener el hub:

| Script | Para qué |
|---|---|
| `desplegar-encargo.sh`, `desplegar-chat.sh`, `encargo-app.Dockerfile`, `chat-web/` | Publicar un encargo, o su chat web, en un servidor propio con Caddy |
| `respaldo-encargos.sh` | Copia diaria de la base de cada encargo; el despliegue la instala en el cron del **servidor**, no aquí |
| `ensayo-encargos/` | Ensayar los encargos sin Telegram: `alta.py` hace lo del dueño y `hablar.py` habla como la persona, sobre un `HUB_HOME` de ensayo |
| `transcribir-whisper.py` | Transcriptor local con faster-whisper. No se importa: se apunta desde `transcripcion.comando` en `encargos.yml` |
| `sala-limpia/` | Probar la instalación de cero en un contenedor (`conocimiento/08-sala-limpia.md`) |
| `tmux-arranque.service` | Ejemplo de unit que levanta un servidor de tmux al arrancar, para el acceso remoto en frío. El instalador **no** lo instala |
| `generar-iconos.py` | Regenera los iconos de la web |
