# Instalar el hub

El hub es un índice de proyectos, sesiones de trabajo y capacidades. Corre en tu
máquina, escucha sólo en `127.0.0.1` y no manda nada a ninguna parte.

## Lo que necesitas

**Imprescindible:** WSL o Linux con `systemd --user`, `git`, `tmux`, `python`
3.12+, [`uv`](https://astral.sh/uv) y [Claude Code](https://claude.com/claude-code).

**Opcional:** `docker` (sin él, la pantalla de servicios queda vacía) y `rg`
(sin él, la medición de uso cae a `grep` y tarda más).

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
| `~/.local/share/hub/hub.db` | El índice. Se reconstruye escaneando; no guardes nada aquí que no esté en otro sitio |
| `~/.config/systemd/user/hub-*.service` | Los dos servicios, generados con las rutas de tu clon |

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

Luego declara en el registro el bloque `tipo: asistente` que el script imprime.
Si no lo quieres, no hagas nada: sin ese proyecto la pestaña no se pinta.

## Comprobar y desinstalar

```bash
systemctl --user status hub-web hub-snapshotter   # cómo van
journalctl --user -u hub-web -f                   # qué está haciendo
bash scripts/desinstalar.sh                       # servicios fuera, datos intactos
bash scripts/desinstalar.sh --datos               # además borra ~/.local/share/hub
```

## Instalar en otro sitio o en otro puerto

Los datos y el puerto salen de variables de entorno:

```bash
HUB_HOME=/tmp/hub-pruebas HUB_PORT=8788 bash scripts/instalar.sh --sin-servicios
```

🔴 **`--sin-servicios` no es opcional si ya tienes el hub instalado.** Los dos
units de systemd se llaman siempre `hub-web` y `hub-snapshotter`, así que una
segunda instalación **reescribe los de la primera** y te deja el hub de verdad
sirviendo desde la carpeta de pruebas. Cambiar `HUB_HOME` y `HUB_PORT` no
evita eso: aísla los datos, no los servicios.

Con ese flag se hace todo menos systemd, y el instalador te imprime la orden
para arrancarlo a mano. Es también la forma de usar el hub en una máquina sin
`systemd --user` (macOS, algunos contenedores).

⚠️ Arrancado así **sólo corre la web**, y quien lee `projects.yml` es el
snapshotter: el hub no verá tus proyectos hasta que lo arranques también.

```bash
cd <tu-clon> && HUB_HOME=... uv run python -m hub.snapshotter
```

### Todas las variables de entorno

Ninguna hace falta para usar el hub: todas tienen un valor por defecto que
funciona. Están aquí porque la que no se documenta no existe.

| Variable | Por defecto | Para qué |
|---|---|---|
| `HUB_HOME` | `~/.local/share/hub` | Dónde viven tus datos: el registro, el índice y los kits |
| `HUB_PORT` | `8787` | Puerto de la web |
| `HUB_HOST` | `127.0.0.1` | 🔴 **No lo cambies.** Es lo que mantiene el hub fuera de la red — ver más abajo |
| `HUB_PROJECTS_YML` | `$HUB_HOME/projects.yml` | El registro, si lo quieres en otro sitio |
| `HUB_KITS` | `$HUB_HOME/kits` | Dónde se instalan los kits |
| `HUB_INTERVALO` | `20` | Cada cuántos segundos muestrea el snapshotter |
| `HUB_RETENCION` | `50` | Cuántas muestras se guardan antes de podar |
| `HUB_TMUX_SOCKET` | *(ninguno)* | Servidor de tmux aparte (`tmux -L`). Los tests lo usan para no tocar tus sesiones |
| `HUB_CONTEXTO_FICHERO` | `$HUB_HOME/asistente-contexto.json` | Dónde escribe el statusline del asistente |
| `HUB_STATUSLINE_SIGUIENTE` | *(ninguno)* | Ver abajo |

🔴 **`HUB_STATUSLINE_SIGUIENTE`, si ya tienes una statusline.** Sembrar el
asistente le pone la suya, y en Claude Code una statusline de proyecto
**sustituye** a la global, no se suma. Si la tuya registra cuota o pinta un HUD,
dejaría de hacerlo mientras trabajas en el asistente, y sin decir nada. Pon ahí
el comando de la tuya y el hub le pasa el payload intacto:

```json
{ "env": { "HUB_STATUSLINE_SIGUIENTE": "/ruta/a/tu-statusline.sh" } }
```

### Actualizar

`git pull` no basta: el código en marcha sigue siendo el viejo.

```bash
git pull && systemctl --user restart hub-web hub-snapshotter
```

Y si **mueves la carpeta del clon**, vuelve a correr `bash scripts/instalar.sh`:
la ruta va escrita dentro de los units, y sin regenerarlos apuntan a donde ya no
estás.

## 🔴 La terminal da acceso de shell

`/terminal` te ata a una sesión de tmux real. Hoy **lo único que la protege es
que el hub escucha en `127.0.0.1`**. No expongas el puerto a la red sin ponerle
antes autenticación, ni siquiera «un momento para probar».

Dos cosas que conviene saber, porque no se deducen de lo anterior:

- **`HUB_HOST` es la palanca que quita esa protección.** `HUB_HOST=0.0.0.0` deja
  el hub —y la terminal— accesible desde toda tu red. No lo pongas.
- **Un navegador puede alcanzar `127.0.0.1`.** Que el hub sea local te protege de
  la red, no de una página web abierta en tu propio navegador. Mientras el hub
  esté levantado, trátalo como lo que es: una consola con tu shell dentro.
