# Hub

Un índice de tus proyectos, tus sesiones de trabajo y lo que has construido.
Corre en tu máquina, escucha sólo en `127.0.0.1` y no manda nada a ninguna parte.

Existe para dos cosas:

- **No perder el rastro** cuando se cierra WSL o se apaga la PC. Un demonio va
  fotografiando tus sesiones de tmux, así que al volver sabes exactamente qué
  tenías abierto y en qué estabas.
- **No olvidar lo que ya construiste.** Agentes, skills, scripts y kits que
  hiciste, funcionan, y dejas de usar porque se te olvida que existen.

Y de paso mide lo que nadie mide: **cuántos commits tuyos no están en ningún
remoto**. Nació de descubrir 473 que se habían dado por perdidos.

## Empezar

```bash
git clone <url> hub
cd hub
```

Abre Claude Code en esa carpeta y dile **«instala este repo»**. Comprobará qué
te falta, te lo dirá con su consecuencia, y no instalará nada sin preguntarte.

A mano: `bash scripts/doctor.sh` y luego `bash scripts/instalar.sh`. El detalle
está en [`INSTALAR.md`](INSTALAR.md).

Cuando termine, el hub está en <http://127.0.0.1:8787> y la portada te guía
hasta declarar tu primer proyecto.

### Actualizar

```bash
git pull && systemctl --user restart hub-web hub-snapshotter
```

El `pull` solo no basta: el código en marcha sigue siendo el viejo. Tus datos
viven en `~/.local/share/hub/`, fuera del repo, así que actualizar no puede
pisarte nada. Si algo se ve raro después, recarga con **Ctrl+Shift+R**: parte de
la interfaz son `.js` que el navegador cachea.

### Las ramas

| Rama | Qué hay |
|---|---|
| `main` | **La que quieres.** Es lo que se ha usado, no sólo lo que compila |
| `qa` | En pruebas, camino de `main` |
| `dev` | Todo lo que se va haciendo. Se rompe |

`git clone` te deja en `main` sin que hagas nada.

## Las pantallas

| | |
|---|---|
| **Inicio** | Qué pide atención hoy: commits sin respaldo, sesiones perdidas tras un corte, proyectos parados |
| **Trabajo** | Donde vas a pasar el día: slots a la izquierda, una **terminal de verdad** en medio, y la nota del slot a la derecha |
| **Inventario** | Todo lo que has construido, quién lo usa y qué lleva meses sin tocarse |
| **Respaldo** | Cuánto trabajo tuyo no está en ningún otro sitio |
| **Servicios** | De quién es cada contenedor de Docker, **antes** de parar ninguno |
| **Conexiones** | Dónde despliega cada cosa y **dónde vive** su credencial — nunca la credencial |
| **Contexto** | Todo el estado en un texto, listo para pegar al principio de una sesión de Claude |

Y una octava que no sale en el raíl porque depende de dónde estés: **la del
proyecto** (`/proyecto/<id>`, pinchando cualquiera), donde se crean, editan,
mueven, archivan y borran sus slots.

### Atajos

| | |
|---|---|
| `Ctrl+K` o `/` | Buscar desde cualquier sitio |
| `g` y una letra | Ir a una pantalla: `p`anorama, `t`rabajo, `i`nventario, `r`espaldo, `s`ervicios, `c`onexiones, conte`x`to |
| `?` | La ayuda con todos los atajos |
| `Alt+0..9` | Cambiar de ventana, en la terminal |
| `Esc` | Cerrar lo que esté abierto |

Más un **asistente** opcional en la esquina: un chat que responde sobre tus
proyectos leyendo lo que el hub ya midió.

### Los botones que lanzan un agente

Casi todo el hub sólo mide y muestra. Cuatro acciones son la excepción y conviene
saber cuáles son, porque abren una ventana de tmux con `claude` dentro de una
carpeta tuya:

| Botón | Dónde | Sobre qué |
|---|---|---|
| **Proyecto nuevo** | Portada | Una carpeta **vacía** que crea el hub |
| **Kit nuevo** | Inventario → Kits | Una carpeta **vacía**, desde la plantilla |
| **Crear capa base** | Pantalla del proyecto | Un repo tuyo que ya existe |
| **Lanzar mantenedor** | Inventario, sobre un kit | El repo de ese kit |

Los dos primeros pueden ser botones justamente porque la carpeta está vacía: no
hay nada de nadie que sobrescribir. Registrar un proyecto que **ya existe** o
aplicarle un kit no tienen botón por eso mismo, y se piden a Claude Code.

Ninguna escribe por su cuenta: el hub prepara el encargo y lo ejecuta un agente
en su ventana, que tú ves. Y `guardrail: never` en el registro de un proyecto
las bloquea todas, aunque las pidas desde la interfaz.

## Cómo funciona, en tres frases

**Tú declaras tus proyectos en un archivo de texto** —
`~/.local/share/hub/projects.yml` — y todo lo demás sale de ahí. La base de datos
sólo es un índice: se puede borrar y se reconstruye escaneando.

**El hub no toca tus proyectos.** Los lee, los mide y te dice lo que ve. Cuando
algo hay que escribir dentro de uno, lo propone y lo escribe Claude contigo
mirando.

**No hay nada automático.** No archiva, no expira, no avisa y no hace push por
ti. Mide y muestra; la acción es tuya.

## Kits — darle capacidades a un proyecto

Un kit es una capa que aporta una funcionalidad a un proyecto al aplicarse: un
método de trabajo, unas skills, unas herramientas. El hub los resuelve por su
`id` y los instala como un gestor de dependencias.

```bash
bash scripts/kit.sh listar
bash scripts/kit.sh instalar <id>
```

Y desde Claude Code, en el proyecto: **«aplica el kit X aquí»**.

Lo que puedes hacer con ellos —crear uno, aplicarlo, mantenerlo— está en
[`FLUJOS.md`](FLUJOS.md).

## Qué necesitas

WSL o Linux con `systemd --user`, `git`, `tmux`, `python` 3.12+,
[`uv`](https://astral.sh/uv) y [Claude Code](https://claude.com/claude-code).
Opcionalmente `docker` y `rg`. El diagnóstico te lo dice todo:

```bash
bash scripts/doctor.sh
```

## Dónde están tus cosas

| | |
|---|---|
| `~/.local/share/hub/projects.yml` | **Tu registro.** El único archivo que editas a mano |
| `~/.local/share/hub/hub.db` | El índice. Se reconstruye solo |
| `~/.local/share/hub/kits/` | Los kits instalados, por `id` y versión |

Nada de eso vive dentro del repo, así que puedes actualizar el hub con un
`git pull` sin que choque con lo tuyo.

## Documentación

- [`INSTALAR.md`](INSTALAR.md) — instalar, comprobar, desinstalar
- [`FLUJOS.md`](FLUJOS.md) — crear proyectos, anexarlos, aplicar y crear kits
- [`conocimiento/`](conocimiento/INDICE.md) — cómo se usa cada parte, con los
  formatos de los archivos que vas a editar

## Licencia

MIT — ver [`LICENSE`](LICENSE). Úsalo, cámbialo y redistribúyelo; sólo conserva
el aviso de copyright.

> 🔴 **La terminal del hub da acceso de shell**, y hoy sólo la protege el bind a
> `127.0.0.1`. No expongas el puerto a la red sin ponerle antes autenticación.
