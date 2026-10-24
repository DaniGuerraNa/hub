# Hub

Un índice de tus proyectos, tus sesiones de trabajo y lo que has construido.
Corre en tu máquina y escucha sólo en `127.0.0.1`. No manda nada fuera salvo lo
que actives tú: el canal de Telegram, los encargos y publicar maquetas en un
servidor son opcionales y vienen apagados.

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
bash scripts/actualizar.sh
```

Baja la versión, regenera los servicios, pone al día el asistente, aplica los
pasos propios de cada versión, reinicia lo que estaba en marcha y te enseña qué
cambió ([`CHANGELOG.md`](CHANGELOG.md)). Tus datos viven en
`~/.local/share/hub/`, fuera del repo, y no se tocan. Si algo se ve raro
después, recarga con **Ctrl+Shift+R**.

El hub te avisa arriba, en todas las pantallas, cuando hay una versión nueva
publicada; nunca se actualiza solo. Y si hiciste sólo `git pull`, te avisa de
que falta terminar.

🔴 **Si lo instalaste antes de la 0.2.0**, esta vez: `git pull && bash
scripts/actualizar.sh --sin-bajar`.

### Las ramas

| Rama | Qué hay |
|---|---|
| `main` | **La que quieres.** Es lo que se ha usado, no sólo lo que compila |
| `qa` | En pruebas, camino de `main` |
| `dev` | Todo lo que se va haciendo. Se rompe |

`git clone` te deja en `main` sin que hagas nada. Cada versión que llega a
`main` lleva su etiqueta (`v0.2.0`) y su entrada en `CHANGELOG.md`.

## Las pantallas

En el menú, **Panorama** y **Trabajo** van arriba; el resto, en cinco grupos
que se despliegan: **Agentes**, **Proyectos**, **Vigilar**, **Comunicación** y
**Ajustes**.

| | |
|---|---|
| **Panorama** | Qué pide atención hoy: commits sin respaldo, sesiones perdidas tras un corte, proyectos parados |
| **Trabajo** | Donde vas a pasar el día: slots a la izquierda, una **terminal de verdad** en medio y, a la derecha, la nota del slot, sus lienzos, sus consultas y sus mensajes programados |
| **Inventario** | Todo lo que has construido, quién lo usa y qué lleva meses sin tocarse |
| **Respaldo** | Cuánto trabajo tuyo no está en ningún otro sitio |
| **Servicios** | De quién es cada contenedor de Docker, **antes** de parar ninguno |
| **Conexiones** | Dónde despliega cada cosa y **dónde vive** su credencial — nunca la credencial |
| **Contexto** | Todo el estado en un texto, listo para pegar al principio de una sesión de Claude |
| **Archivos** | Qué hay y dónde, por proyecto. Sólo nombres y rutas: el hub no abre archivos |
| **Intercambio** | La carpeta por la que pasan archivos entre el teléfono y tus sesiones |
| **Máquina** | Cómo está el equipo cuando no hay nadie delante: disco, memoria, GPU y, si hay un SAI por USB, si se fue la luz |
| **Consumo** | Cuántos tokens ha costado cada proyecto en los últimos días, leído del registro de Claude Code (que borra lo de más de 30 días) |
| **Orquestador** | Le das una tarea y él se la pide a la sesión de cada proyecto, paso a paso. Ver [`conocimiento/09`](conocimiento/09-orquestador-e-intercambio.md) antes de darle permisos |
| **Navegante** | Un navegador de verdad que maneja Claude, con un guardián que pausa lo que modifica hasta que lo permites. Se le enseña un flujo haciéndolo una vez |
| **Reuniones** | Graba la reunión de otro monitor (pantalla, audio de la aplicación y tu micro) y la procesa en tu máquina: transcripción, resumen y tareas. Necesita un agente pequeño en Windows |
| **Canal** y **Encargos** | Preguntar y recibir encargos por Telegram. Opcionales: sus servicios se instalan parados |
| **Acceso** | Usar el hub desde el móvil u otro aparato: por qué nombres se entra, qué aparatos pueden, y si la terminal está abierta desde fuera. Ver [`conocimiento/10`](conocimiento/10-mas-pantallas.md) |
| **Actualizaciones** | Qué versión tienes, si hay otra publicada y ponerla con un botón |
| **Guía** | Por dónde empezar: los primeros pasos, que se marcan solos al hacerlos, y qué hay en cada pantalla. Con «Guíame», el asistente te acompaña |

Y una más que no sale en el raíl porque depende de dónde estés: **la del
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

Casi todo el hub sólo mide y muestra. Estas acciones son la excepción y conviene
saber cuáles son, porque abren una ventana de tmux con `claude` dentro de una
carpeta:

| Botón | Dónde | Sobre qué |
|---|---|---|
| **Proyecto nuevo** | Panorama | Una carpeta **vacía** que crea el hub |
| **Kit nuevo** | Inventario → Kits | Una carpeta **vacía**, desde la plantilla |
| **Crear capa base** | Pantalla del proyecto | Un repo tuyo que ya existe |
| **Lanzar mantenedor** | Inventario, sobre un kit | El repo de ese kit |
| **Una tarea** al orquestador | Orquestador | Las sesiones de los proyectos a los que le diste alcance en Orquestador → Permisos |
| **Entrevistar** e **Implementar** | La ficha de un encargo | La carpeta de ese encargo, dentro de los datos del hub |

Aparte, **Archivos → «Abrir terminal aquí»** y **Restaurar** abren ventanas y
dejan un comando escrito, pero **sin pulsar Enter**: lo lanzas tú.

Los dos primeros pueden ser botones justamente porque la carpeta está vacía: no
hay nada de nadie que sobrescribir. Aplicar un kit a un proyecto que **ya
existe** no tiene botón por eso mismo, y se pide a Claude Code. Registrar uno
que ya existe se le pide al asistente: mira la carpeta, te pregunta lo que
necesita y sólo da el alta en el registro, sin escribir nada dentro.

Ninguna escribe por su cuenta: el hub prepara el encargo y lo ejecuta un agente
en su ventana, que tú ves. Y `guardrail: never` en el registro de un proyecto
bloquea las que actúan sobre él, aunque las pidas desde la interfaz. Con
`guardrail: ask`, el orquestador te pide confirmación antes de tocar ese
proyecto en cada tarea.

## Cómo funciona, en tres frases

**Tú declaras tus proyectos en un archivo de texto** —
`~/.local/share/hub/projects.yml` — y todo lo demás sale de ahí. La base de datos
es sobre todo un índice que se reconstruye escaneando, pero tus slots, sus
notas, el canal, los programados y los encargos **sólo viven en ella**: no la
borres; si da problemas, apártala (ver `conocimiento/06`).

**El hub no toca tus proyectos.** Los lee, los mide y te dice lo que ve. Cuando
algo hay que escribir dentro de uno, lo propone y lo escribe Claude contigo
mirando.

**No hay nada automático.** No archiva, no expira y no hace push por ti. Mide y
muestra; la acción es tuya. La única excepción son unos pocos avisos por
Telegram (una sesión que te espera, el hub sin latido, la salud del equipo), y
sólo si activas el canal.

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

WSL o Linux con `git`, `tmux`, [`uv`](https://astral.sh/uv) y
[Claude Code](https://claude.com/claude-code). Python 3.12 no hace falta
tenerlo: uv lo descarga solo. `systemd --user` es lo normal para que arranque
solo, pero sin él también funciona (`--sin-servicios`). Opcionalmente `docker`
y `rg`. Navegante y Reuniones traen su propio componente y se preparan
desde su pantalla ([`conocimiento/12`](conocimiento/12-navegante-y-reuniones.md)).
El diagnóstico te lo dice todo:

```bash
bash scripts/doctor.sh
```

## Dónde están tus cosas

| | |
|---|---|
| `~/.local/share/hub/projects.yml` | **Tu registro.** El único archivo que editas a mano |
| `~/.local/share/hub/hub.db` | El índice, y también tus slots, notas, canal, programados y encargos: no lo borres (ver `conocimiento/06`) |
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

> 🔴 **La terminal del hub da acceso de shell.** Por eso el hub escucha sólo en
> `127.0.0.1`: no lo pongas en `0.0.0.0` ni lo expongas a internet. Para usarlo
> desde otro aparato está la pantalla **Acceso** —red privada, nombres exactos,
> aparatos dados de alta con un QR y la terminal tras su propio interruptor,
> apagado de fábrica y en cada reinicio—. Ver
> [`conocimiento/10`](conocimiento/10-mas-pantallas.md).
