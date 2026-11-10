# Cambios

Qué trae cada versión del hub, empezando por la más nueva. Cada una dice tres
cosas: **qué hay nuevo**, **qué cambia en lo que ya usabas** y **qué tienes que
hacer tú** —casi siempre nada más que actualizar—.

Para actualizar, en la carpeta del hub:

```bash
bash scripts/actualizar.sh
```

Al terminar te enseña esta misma lista, sólo con las versiones que acabas de
cruzar.

## 0.5.1 — 2026-11-09

El secretario se enciende desde su pantalla, sin terminal.

### Qué tienes que hacer

- **Actualiza** con el botón de **Actualizaciones** (o con
  `bash scripts/actualizar.sh` en la carpeta del hub). Nada más.

### Qué cambia en lo que ya usabas

- **El secretario se enciende con un botón.** Si está apagado, su pantalla
  dice «Está apagado» y ofrece **Encenderlo**: te recuerda que cada respuesta
  usa tu suscripción de Claude, lo enciende y lo deja encendido también al
  reiniciar el equipo, y no lo da por encendido hasta que da señales. Si se
  cae al arrancar, lo dice con el comando para ver por qué; sin systemd, te da
  el comando para arrancarlo a mano. Ya no hace falta la terminal.

## 0.5.0 — 2026-11-09

Llega el secretario: lee tus reuniones, tus mensajes y tu agenda, te contesta
diciendo de dónde lo sacó, te recuerda lo que quedaste en hacer y puede
acompañarte en todas las pantallas. Además, el Tablero para apuntar ideas, los
Talleres para ver trabajar a tus sesiones, y muchos arreglos para que el hub
no deje de latir, los bots no pierdan mensajes y guardar no recargue la página.

### Qué tienes que hacer

- **Actualiza** con el botón de **Actualizaciones** (o con
  `bash scripts/actualizar.sh` en la carpeta del hub). Las dependencias nuevas
  las instala él.
- **Si quieres el secretario, enciéndelo.** Viene apagado porque cada
  respuesta usa tu suscripción de Claude: la actualización deja su servicio
  instalado y parado. Para encenderlo:
  `systemctl --user enable --now hub-secretario`. Cómo conectarle Telegram, el
  correo, el calendario y lo demás está en `conocimiento/13-secretario.md`.
- **Si tu hub escuchaba en otra dirección que `127.0.0.1`** (por ejemplo
  `0.0.0.0`, para entrar desde la red de casa): desde esta versión la web no
  arranca así, y la actualización se para y lo dice. Vuelve a instalar con
  `HUB_HOST=127.0.0.1 bash scripts/instalar.sh` (con tu `HUB_PORT` y tu
  `HUB_HOME` si los cambiaste), termina con
  `bash scripts/actualizar.sh --sin-bajar` y entra desde otros aparatos por
  **Acceso**. Si lo dejaste como venía, no te afecta.
- **Si despliegas encargos o el chat web en tu servidor:**
  `desplegar-encargo.sh` y `desplegar-chat.sh` piden ahora siempre el alias de
  ssh del servidor, y `desplegar-chat.sh` recibe el token con el mismo puntero
  que pusiste en `chat_web.token_ref` (`ruta#CLAVE`, también
  `~/.secretos/…#CLAVE`), no con la ruta del archivo.
- Esta vez **no hace falta «Limpiar»** el chat del asistente: sus
  instrucciones no cambian. Si alguna pantalla se ve rara, recarga con
  Ctrl+Shift+R.

### Nuevo

- **El secretario** (Secretario, arriba en el menú). Lee tus reuniones
  grabadas y las notas de tus slots y, si los conectas, tu Telegram, tu correo
  (por IMAP, sin marcar nada como leído), los chats de WhatsApp que exportes a
  mano y tu calendario (Google Calendar, o su dirección iCal si sólo quieres
  que lo vea). Contesta lo que le preguntes y dice de dónde lo sacó. Apunta los
  compromisos que salen de lo que lee —cada conversación entera y en orden, así
  que un plan entre los dos queda como tuyo una sola vez y con su plazo; si se
  equivoca, se corrige con «Editar»— y te los recuerda en el teléfono. Se le
  habla escribiendo o con la voz, puede leerte las respuestas en voz alta y,
  con el **modo voz** (el botón de las ondas), conversas sin tocar nada hasta
  que sales. Los avisos automáticos («cada día a las 9, mándame el resumen») se
  crean con un formulario. También crea proyectos y slots, preguntándote antes.
  Usa la zona horaria del sistema, también sin `/etc/timezone` (Fedora,
  Arch…). Todo, en `conocimiento/13-secretario.md`.
- **El secretario en tu teléfono, como una app.** En Secretario → Ajustes →
  Avisos, **Instalar**: funciona como una app con **avisos propios** (Aprobar y
  Rechazar desde la notificación en Android y en la PC), y tocar un aviso te
  lleva a lo que avisa, también con la app ya abierta. Si no los activas, salen
  por el Telegram del Canal, encabezados con lo que son («⏰ Recordatorio»,
  «📣 En el grupo»…); para eso tienes que estar marcado como dueño en Canal,
  y si no pueden salir, el secretario dice «no salió» en vez de darlo por
  enviado. Si lo tienes encendido y lleva cinco minutos sin dar señales, te
  avisa por ese mismo Telegram: sus recordatorios no te llegarían. Quitar un
  aparato de «Aparatos con avisos» es definitivo: no vuelve aunque abra la app,
  hasta que pulses «Activar avisos aquí» en él.
- **El secretario en todas las pantallas**, en el sitio del asistente: pon
  `en_todo_el_hub: true` en `secretario.yml`. Sabe desde qué pantalla le
  hablas y, en Trabajo, qué ventana miras; si le preguntas por lo que tienes
  en pantalla («¿qué es este error?») mira esa ventana —sólo esa, en ese
  momento y sin guardarla— y bajo su respuesta verás «Miré tu pantalla». Hace
  lo que hacía el asistente: anota en la nota de un slot sin borrar lo que
  había, publica lienzos sin pisar lo que corregiste, te dice qué kits hay y
  qué haría aplicarlos, lista las sesiones de trabajo de un proyecto y **te
  resume una sesión larga** («¿qué se hizo ayer en el hub?»). Con ese ajuste
  el asistente queda retirado (no se arranca ni se le escribe); quitándolo,
  vuelve. En la PC, **mantén Ctrl+Espacio** para hablarle aunque estés
  escribiendo en otro sitio: al soltar se lo manda; un toque corto no manda
  nada.
- **«¿Qué tengo pendiente?»** El secretario junta lo que espera de ti:
  permisos, preguntas del orquestador, de tus sesiones y del canal, lo que tus
  proyectos declaran que los bloquea (`bloqueado_por` en su documento de
  estado) y tus compromisos que vencen hoy. Está en **Te espera**, arriba de
  Pendientes, y un globo encima de su conversación te avisa de lo nuevo; nada
  de esto llega al teléfono. Cada cosa trae sus botones: aprobar un permiso,
  contestar o confirmar al orquestador sin salir de ahí y, de lo que bloquea a
  un proyecto, **Anótalo** (pasa a tus compromisos), **Te lo delego** (se lo
  encarga al orquestador, y el botón ya es tu sí para entrar en ese proyecto)
  o **No me lo sugieras más**. Lo legal, lo que mueve dinero y lo de un proyecto donde el
  orquestador aún no tiene permisos no se delega: sale **Prepáramelo**, que lo
  deja listo sin hacerlo. Un proyecto con guardrail `never` sólo se anota. Lo
  callado se recupera en «Reabrir lo callado». Pedírselo en el chat sigue la
  misma regla: lo ya anotado o delegado no se repite, lo callado no vuelve y
  lo que vence no se delega. En la terminal:
  `uv run python -m hub.secretario asuntos` (y `asuntos reabrir CLAVE`).
- **Tus proyectos te hablan por el secretario.** Un proyecto con su propio
  operador (una tienda que recibe pedidos, por ejemplo) ya no necesita su
  propio bot: con `uv run python -m hub.secretario proyecto-dice <id> --tipo
  pendiente --vence 2026-11-10 "Envía el pedido 123"` le deja un pendiente con
  plazo, que queda en tus compromisos; con `--tipo pregunta` o `--tipo aviso`,
  algo que espera en «Te espera». Lo que le contestas ahí le vuelve, y lo lee
  con `proyecto-respuestas <id>` (con `--borrar`, lo quita al leerlo); si
  lleva uno de tus datos, le llega tapado. Sus pendientes no te avisan al
  teléfono salvo que lo enciendas para ese proyecto
  (`de_proyectos: {<id>: {recordar: true}}` en `secretario.yml`).
- **El relevo: lo que sólo puedes hacer tú en la PC te espera en la PC.** Un
  captcha, una verificación de identidad o iniciar sesión con tu cuenta: si
  una tarea del orquestador se topa con eso, o alguien lo deja con
  `uv run python -m hub.secretario relevo --origen navegador "Resuelve el
  captcha"`, queda en tus asuntos y, si el agente de Reuniones está conectado,
  te los abre en la PC una vez. Nunca suena en el teléfono, y se da por
  **Hecho** en vez de contestarse. Para que no se abra solo,
  `relevo_en_pc: false` en `secretario.yml` (no frena los del orquestador).
- **Encárgale pruebas con una captura, y te vuelve con lo que se vio.** Pásale
  al secretario una imagen y dile «haz pruebas de este proyecto»: se lo
  encarga al orquestador con la imagen (te pide permiso, y ese sí vale para el
  proyecto) y, al terminar, te cuenta en el chat lo que dice el orquestador con
  las capturas debajo. El orquestador acepta archivos del Intercambio en un
  encargo (lo que digan dentro cuenta como dato, no como una orden tuya); al
  probar, la sesión sigue la receta «Cómo se prueba» del proyecto —si no la
  tiene, la escribe primero— y sus capturas quedan en la tarea como evidencia.
- **Adjunta imágenes y archivos al secretario**: el clip junto al cuadro,
  Ctrl+V de una captura o soltar el archivo encima. Las imágenes y los PDF los
  ve él («¿qué pone en esta captura?»); de lo demás conoce la ruta, para
  pasárselo a quien le encargue algo. Quedan en Intercambio y se borran solas a
  los diez días. Una foto de más de 3,5 MB se reduce con `ffmpeg`; sin él, no
  la ve y te lo dice.
- **El secretario investiga en la web lo público** («¿qué dice la norma de
  facturación?»): lo busca y lo lee aparte y, en unos minutos, te deja cada
  dato con su página y su fecha, lo que no encontró y las fuentes. Quien
  investiga sólo puede buscar y leer, con un tope de gasto por investigación
  (0,50 USD equivalentes de la API; se cambia con
  `investigar: {tope_usd: 1.0}` en `secretario.yml`). Lo que le pides no
  puede llevar direcciones: di el tema y él busca; un sitio concreto se
  permite con `investigar: {sitios: [ejemplo.org]}`.
- **Tus datos para los trámites, una sola vez** (Secretario → Ajustes → **Mis
  datos**): nombre legal, identificador fiscal, identificación, domicilios,
  contacto y régimen fiscal. Lo que el secretario encuentra queda *propuesto*
  hasta que pulsas **Confirmar**; lo que escribes tú ya queda confirmado. Lo
  que mande uno de tus datos a otro sitio (un encargo, un lienzo, la nota de
  un slot, una idea, un aviso al teléfono) te pide permiso antes, aunque esa
  acción esté en *auto*, y nunca va a una búsqueda en la web. Viven en un
  archivo que sólo lee tu usuario y no entran en las copias diarias:
  **Olvidar** lo quita sin dejar copia. Lo que te compromete legalmente o con
  dinero lo prepara y lo haces tú.
- **El secretario tiene cara.** Un personaje pequeño en la pestaña que te
  sigue por las pantallas y en su cabecera: te escucha, piensa, lleva en la
  mano lo que está usando («Mirando tu agenda»…), te habla, levanta la mano
  cuando algo espera tu sí, y a su lado aparecen quienes trabajan para él (la
  tarea del orquestador, la sesión que la hace y sus subagentes con la ropa de
  su rol). Sólo enseña lo que de verdad pasa. En **Ajustes → Personaje** eliges
  entre doce —el cubo de siempre y once dibujados, ranitas y hongos— y lo ves
  en cada estado. En el modo voz, el círculo sigue tu voz, gira al pensar y
  late al hablar; en el chat, tres puntos mientras piensa. Con «reducir
  movimiento» se queda quieto en cada pose.
- **El secretario le pasa un encargo a la sesión que ya tienes abierta.** «Díselo
  a mi terminal de trabajo»: le escribe a la sesión de Claude Code (o Codex) de
  ese slot, con una primera línea que dice que es suyo por encargo tuyo, para
  que lo haga con su contexto y sigas tú en ella. Te pide permiso cada vez con
  el texto exacto, nunca lo hace solo, y si la sesión está trabajando no
  escribe y te dice por qué. Con Claude Code, además, no escribe si tiene un
  permiso o un menú abiertos, y después te cuenta lo que contestó; de Codex
  eso todavía no lo sabe leer.
- **Ponle nombre a tu secretario.** En Secretario → Ajustes → Personaje, arriba,
  «Cómo se llama»: sale en el menú, en su pantalla y en la app instalada, y él
  sabe que es el suyo desde la siguiente conversación. Vacío vuelve a
  «Secretario».
- **Modo monitor del secretario**, para una pantalla aparte (en Secretario,
  arriba a la derecha): a pantalla entera, un escenario con sus puestos
  —agenda, mensajes, lo que te espera, proyectos, orquestador, máquina,
  navegador— y la conversación al lado. El personaje va al puesto de lo que
  está haciendo y vuelve a su mesa con lo que fue a buscar.
- **Modo inglés** (el botón *English*, debajo del cuadro), para practicar:
  conversa en inglés sobre tu día, te corrige un error por vez con un «Tip» y
  a veces te hace una pregunta de entrevista, también por voz. Mientras está
  puesto no hace nada por su cuenta: lo que haría te llega como permiso en
  Pendientes. Lo hablado ahí no se guarda como notas.
- **La voz, más rápida.** En el modo voz empieza a leerte la respuesta en
  cuanto tiene la primera frase, contesta más corto y, si va a consultar
  algo, te lo dice antes («déjame mirarlo»). Mientras habláis deja `claude`
  abierto (se cierra a los diez minutos sin uso), así que cada turno contesta
  un segundo antes. El dictado usa la tarjeta gráfica si la hay (NVIDIA, con
  `nvidia-cublas-cu12` y `nvidia-cudnn-cu12` en el entorno de Whisper): una
  frase en medio segundo. Sin GPU, como antes.
- **Grabar sola al entrar a una llamada**: con un disparador «al entrar a una
  reunión» → «Grabar una reunión» (y esa acción en `auto`), empieza a grabar
  con los ajustes de la última vez a los ~30 s de llamada y para entre 1 y 1,5
  minutos después de colgar, cuando ya no ve la reunión en tu pantalla (las
  pausas no la cortan). Graba también las apps de llamada que añadas en
  `apps_de_llamada` (`secretario.yml`). Lo que grabas a mano no lo toca.
- **En los grupos, el secretario distingue lo que es para ti**: si te
  etiquetan, te responden o te nombran (cómo te llaman, con `alias:` en los
  ajustes de la fuente). Lo que piden a otros ya no te sale como pendiente, y
  un disparador puede saltar «sólo si es para mí». Lo que se anuncia a todo el
  grupo y te afecta —una reunión que se mueve o se cancela, una caída, un
  plazo para todos— te llega, y si mueve la hora de un pendiente tuyo, lo
  cambia y te lo dice.
- **El parte de la mañana**: el resumen del día puede contarte también las
  últimas 24 horas —primero lo que espera de ti, luego lo que pasó y al final
  lo que falló— entero en el chat del secretario, con sólo la primera línea al
  teléfono. Con un disparador de horario con `haz: resumen_del_dia`,
  `noche: true` y `en_chat: true` (ejemplo en la guía del secretario). Si no
  le contestas, esa conversación espera abierta hasta 12 horas y, al cerrarse,
  no gasta una llamada al modelo.
- **El secretario lee los archivos de tus proyectos registrados**, en sólo
  lectura: busca, lista lo último que tocaste y lee. Nunca abre llaves
  (`.env`, carpetas `secrets/`…). Cuéntale cómo organizas tu trabajo con
  `contexto:` en `secretario.yml`.
- **El secretario revisa tu PC con Windows y tu red, sólo leyendo.** Cuéntale
  un pantallazo, un apagado raro, que la PC va lenta o que tienes lag, y mira
  los pantallazos con su código y su hora, los volcados (sin abrirlos), la
  BIOS, la velocidad de tus adaptadores, la latencia y la pérdida, las
  conexiones de un programa y un traceroute. No cambia nada. Desde la
  terminal: `uv run python -m hub.diagnostico windows` o
  `… red --proceso <programa> --trazar 1.1.1.1`. Sólo con el hub en WSL.
- **El secretario maneja una tele Roku** por la red de casa: «enciende la tele
  y pon la PC», «abre YouTube en la tele», «¿está encendida?»; al principio te
  pide permiso cada vez. Necesita la IP de la tele en `secretario.yml` y dos
  ajustes en la tele (guía del secretario, «La tele»).
- **WhatsApp en vivo, provisional y apagado.** Se lee dentro del WhatsApp Web
  que ya usas (con una extensión de Chrome o en la app de escritorio de
  Windows) o con un colector aparte sin ventana. Sólo lee: no marca leído ni
  te pone «en línea», y lo leído se guarda sólo para tu usuario. 🔴 WhatsApp
  puede bloquear el número por usar un programa no oficial, aunque sólo lea:
  pruébalo con un número secundario. La forma sin riesgo es exportar los chats
  a mano. Las dos, en la guía del secretario (Fuentes).
- **Tablero** (en el menú, debajo de Secretario). Suelta ahí una mejora o una
  idea en una línea cuando se te ocurra, también desde el teléfono o
  diciéndoselo al secretario («anota en el tablero que…»), y espera a que se
  tome. Con **Dictar** la dices en voz y se transcribe en tu máquina; con
  **Adjuntar**, pegando una captura o soltando archivos, lleva fotos y
  archivos (se guardan con lo del Intercambio y, como él, no entran en la
  copia diaria). Lo descartado se queda a la vista con su motivo.
  **Trabajarla** se la encarga al orquestador, que la trabaja en una sesión
  fija «Tablero» dentro de una copia de trabajo del proyecto: la primera vez el
  botón ofrece **Crear la copia y trabajarla** (un `git worktree` junto a su
  carpeta, en una rama «tablero»; la tuya no se toca). Te enseña el plan si es
  un cambio mediano o grande, y lo hecho queda en su rama hasta que lo
  integres. Un proyecto sin git se trabaja en su carpeta, sólo si no tienes
  una sesión abierta ahí. También: «trabaja la idea 3» al secretario, que te
  pide permiso antes.
- **Los talleres** (Talleres, en Agentes). Cada sesión con Claude Code o Codex
  se ve como un taller en una casa de muñecas: la rana del yunque es la sesión
  (martilla si trabaja, se duerme si está quieta y pide permiso si espera tu
  sí), y los subagentes que lanza entran por la puerta y se ponen en la
  estación de su oficio; al terminar le llevan el resultado y se van. Sólo
  mira: no escribe en ningún panel ni manda avisos. Se pone al día sola cada
  10 s mientras la miras.
- **El hub en una máquina aparte, sin monitor.** Si lo tienes en una segunda
  máquina y lo usas desde tu PC, hay guía nueva
  (`conocimiento/14-maquina-aparte.md`): el primer aparato se da de alta por
  SSH abriendo el enlace en tu PC, sin escanear nada, y SSH queda como salida
  de emergencia. **Máquina → Salud** dice, en cuanto declaras un nombre en
  `acceso.yml`, si esa máquina volverá sola tras un apagón: si Tailscale
  conecta sin iniciar sesión en Windows, si hay una tarea que levante WSL al
  encender (la crea `scripts/arrancar-sin-sesion.ps1`), si Windows se
  suspende y si `tailscale serve` lleva al hub. Conectar Google Calendar
  desde otra PC también funciona: pegas en la terminal la dirección a la que
  vuelve el navegador.
- **Tus llaves, a la vista y a Bitwarden** (Conexiones → *Llaves de esta
  máquina*). Cada llave que usa el hub —los tokens de los bots, las del
  secretario, tus claves ssh y lo que haya suelto en `~/.secretos`— con dónde
  vive y si ya la tienes en Bitwarden. Nunca se enseña ni se abre el valor.
  Para subir las que faltan, con `bw` y tu caja abierta:
  `export BW_SESSION=$(bw unlock --raw)` y
  `uv run python -m hub.llavero subir` (van a una carpeta «hub», una nota por
  archivo). Si ya la subiste a mano, pulsa «Ya está en Bitwarden».
- **Crear un slot desde Trabajo en el móvil.** El selector de arriba trae
  «+ Slot nuevo» al final de cada proyecto y «+ Slot en otro proyecto»: el
  mismo diálogo que en el escritorio.
- **Comprobar todas las pantallas en un navegador de verdad.**
  `uv run --group navegador python -m hub.recorrido` abre cada pantalla a
  ancho de móvil y de PC y dice cuál falla: un error en la página, algo que no
  carga o algo que se sale de lado. Sólo mira. Necesita un Chromium de Linux
  (`uv run --group navegador playwright install chromium` lo baja).

### Qué cambia en lo que ya usabas

- **Refrescar te deja en la pantalla en la que estabas** (antes llevaba a
  Panorama).
- **El aviso de que una sesión te está preguntando salta también cuando espera
  que apruebes crear o editar un archivo**; antes sólo se reconocía el cuadro de
  los comandos.
- **«Ya lo revisé» en Panorama, añadir una conexión y «Encolar» en el
  Orquestador ya no recargan la página.** Como el resto de acciones, te dejan
  donde estabas y cambian sólo lo que tocan: el aviso de la sesión perdida se
  va, la conexión nueva aparece en la lista y la tarea encolada sale arriba y
  en la cola, con el formulario vacío para la siguiente. Si añadir una
  conexión falla (un alias repetido), la página se recarga para decirte por
  qué, también si vuelve a fallar igual.
- **Cerrar una ventana se ve al momento.** Antes seguía en la lista hasta el
  siguiente muestreo (20 s), y se pulsaba otra vez sin saber si había cerrado;
  ese segundo clic podía además cerrar otra ventana que hubiera tomado su número.
  Ahora se cierra por la ventana concreta, la lista se rehace antes de volver y,
  si ya estaba cerrada, lo dice. Cerrar la última ya no avisa de «una sesión
  perdida».
- **Una ventana que se cierra por dentro (con `exit`) sale sola de la lista de
  Trabajo** en unos segundos, sin recargar la página.
- **El hub sólo escucha en esta máquina, y ahora lo comprueba.** Con un
  `--host` distinto de `127.0.0.1` (o `localhost`) la web ya no arranca y
  `actualizar.sh` se para (arriba, qué hacer).
- **Seguridad: otra página de tu propia máquina ya no puede abrir la terminal
  del hub.** Antes bastaba con que estuviera servida en `127.0.0.1` o
  `localhost` en cualquier puerto (el servidor de desarrollo de otro proyecto,
  por ejemplo); ahora tiene que venir del mismo puerto que el hub.
- **Seguridad: lo que llega como nombre ya no puede colarse como opción.** Un
  contenedor que empiece por guion no llega a `docker`, el origen de un kit no
  se lee como opción de `git`, y `alta-conexion.sh` rechaza un host, usuario o
  puerto con saltos de línea o caracteres raros antes de tocar `~/.ssh/config`.
- **Seguridad: la app que construye el implementador de un encargo se prueba
  aislada.** `./encargo servir` la arranca sin acceso a tu carpeta personal,
  sin red y sin ver los demás procesos (con los «user namespaces» de Linux,
  sin instalar nada); si tu máquina no los permite, se niega en vez de
  arrancarla sin aislar. El implementador ya no tiene `curl` ni recibe una
  URL: prueba la API de su app con `./encargo api GET /api/…` y la mira con
  `./encargo mirar /ruta`.
- **Guardar, borrar o crear ya no recarga la página.** En el Tablero, la ficha
  de un proyecto, Canal, Encargos, Orquestador y sus permisos, Intercambio,
  Servicios, Conexiones, Navegante, Reuniones y la Portada, la acción cambia
  sólo la lista que toca: sigues donde estabas, lo desplegado sigue abierto y
  el aviso («Guardado») flota arriba sin empujar la página. Navegante y
  Reuniones se actualizan solos sin parpadear, y dejan de preguntar cuando no
  hay nada en marcha; tras arrancar o parar un contenedor, la cifra de
  Servicios del menú se pone al día. Al cargar, el texto ya no salta cuando
  llega la letra, y en Trabajo los proyectos del lado salen ya plegados. Sin
  JavaScript todo funciona como antes, también renombrar.
- **Reiniciar el hub ya no corta lo que estaba haciendo.** El procesado de una
  reunión, la compresión del audio, una actualización y el servidor de dictado
  siguen aunque se reinicie el servicio que los lanzó; antes, un reinicio a
  mitad de un resumen dejaba la reunión en «procesando» para siempre. Si aun
  así algo se corta (un apagón), la reunión dice «se cortó» y tiene
  **Reintentar**.
- **Una carpeta de un proyecto que no se deja leer** (OneDrive a medio
  sincronizar, un disco que no responde) ya no deja al hub sin latir: ese
  proyecto se queda sin esas rutas mientras tanto y el registro del servicio
  lo dice. Antes se caía el muestreo entero, con los mensajes programados y el
  orquestador detrás, y llegaba el aviso de «hub callado».
- **Los bots de Canal y Encargos ya no repiten ni pierden mensajes si algo
  falla a medias.** Un mensaje que no se pudo tratar se reintenta sin duplicar
  lo anterior, y uno que falla siempre se salta a los tres intentos y queda
  apuntado en el registro. Si `hub-encargos` se reinicia justo después de
  recibir un mensaje, ya no se trata dos veces (ni otro «Anotado…», ni el
  entrevistador lee dos veces): en el registro queda como «repetido». Y un
  paso que falla en cada vuelta ya no deja sordo a un bot. Las pantallas Canal
  y Encargos dicen si el token sirve según lo comprobó el propio servicio del
  bot: si acabas de cambiarlo, verás «todavía no ha leído el token» hasta que
  reinicies ese servicio.
- **`encargo deshacer` cuenta sólo lo que de verdad retiró**: si el bot ya
  había mandado alguno, lo dice. Lo que retiras mientras sale un lote ya no se
  manda igual, y si llega en el instante justo, la conversación del encargo
  dice «le llegó igual».
- **Dar de alta por el chat web ya no pierde el encargo** si el entrevistador
  no se puede abrir: queda de alta, con su encargo, y se abre luego con el
  botón, como en el alta de siempre.
- **`desplegar-encargo.sh` y `desplegar-chat.sh`** ya no traen un servidor por
  omisión, y `desplegar-chat.sh` lee el token por su puntero como el hub (antes
  buscaba siempre la clave `CHAT_WEB_TOKEN` y, con otra, subía un token vacío).
  El aviso de «construido y sin desplegar» trae la orden completa, con la
  carpeta de la app si es una.
- **El orquestador ya no te pregunta lo operativo, si tienes el secretario
  encendido: se lo pregunta a él.** A qué sesión mandar, qué hacer tras un
  fallo, una duda que no cambia lo que se entrega: lo resuelve el secretario,
  y en Orquestador ves qué contestó. A ti te llega lo que es tuyo —el plan de
  un cambio mediano o grande, la lista de «nunca sin el dueño», un choque con
  algo decidido, lo de producto— o lo que el secretario te pasa con su
  resumen; y si en 10 minutos no lo ha resuelto, o no está encendido, te llega
  igual. Lo que contesta el secretario nunca cuenta como tu sí, y las tuyas
  puedes contestarlas en su chat.
- **Firmar o aceptar términos, trámites y contratos y publicar en tu nombre**
  entran en la lista de «nunca sin el dueño» del orquestador: te las pregunta
  a ti, y una pregunta que las nombre te llega aunque la marque como
  operativa.
- **Los agentes que abre el hub arrancan con tu `claude`.** Crear un proyecto o
  un kit, sembrar la capa base o lanzar un agente desde la web abrían la
  ventana con el PATH del servicio, y con dos `claude` instalados podía
  arrancar el otro. Ahora arranca el mismo que usas en tu terminal.
- **Anexar un proyecto acepta todo lo del registro.** `/api/proyecto/anexar`
  (y las skills `anexar-proyecto`, `nuevo-proyecto` y `nuevo-kit`) aceptan
  `rutas`, `patrones`, `contenedores` y `tipo`: ya no hace falta editar
  `projects.yml` a mano para declarar repos fuera del asiento o un workspace.
- **Dictar un silencio dice «no se entendió nada en el audio»**, en vez de «el
  transcriptor salió con código 3», y un audio mudo que llega a un encargo
  queda en el momento como «no se entendió nada» en vez de reintentarse hasta
  rendirse. Eso vale para el transcriptor que trae el hub: si declaraste el
  tuyo en `encargos.yml`, «no se oyó nada» es que no escriba texto, y
  cualquier código de error sigue siendo un fallo. El audio de un dictado que
  falló se borra solo a los diez días (antes se quedaba para siempre). Y el
  dictado usa el Whisper que se queda cargado también si declaraste en
  `encargos.yml` el transcriptor del hub.
- **Reuniones ve la GPU en WSL.** Decía «sin GPU NVIDIA» aunque la hubiera,
  porque el servicio no encontraba `nvidia-smi` donde lo pone WSL.
- **La terminal del hub ya no encoge una ventana que tienes abierta en otra
  terminal** (encoger recorta para siempre lo ya escrito). Si con las dos
  abiertas ves cortado el final de las líneas en el navegador, baja el tamaño
  de la letra: eso no borra nada.
- **Si la base del hub se rompe, la pantalla propone primero la copia de cada
  día**, con su nombre y las órdenes para ponerla, y dice todo lo que se
  perdería sin ella (no sólo las notas y los slots).
- **`desinstalar.sh --datos` borra la carpeta de datos que usa tu hub**, la
  que dice su servicio, y no la que suponga la terminal desde la que lo
  lanzas. Antes de pedirte «borrar» enumera lo que se va —copias de cada día y
  memoria del secretario incluidas— y avisa de que las copias que guardes
  fuera (`HUB_RESPALDO`) no se borran.
- **Máquina → Salud, sin systemd de usuario** (un contenedor, WSL sin
  systemd), dice eso en vez de dar la web y el muestreo por parados.
- **«Comprobar ahora» en Actualizaciones, sin git**, dice que no pudo mirar y
  por qué, en vez de dar un error 500.
- **Si el registro no se puede leer, la página nombra el archivo que lee tu
  hub**, también con `HUB_HOME` o `HUB_PROJECTS_YML` movidos (antes decía
  siempre `~/.local/share/hub/projects.yml`). Lo mismo el aviso de
  `sembrar-asistente.sh` cuando no puede declararse solo.
- **El «último uso» de Inventario mira donde dice `HUB_TRANSCRIPTS`**, como ya
  hacía Consumo; antes miraba siempre en `~/.claude/projects`.
- **Navegante ya no da por hecho el paso «Hay un Chrome»** con una descarga de
  Chromium a medias en la caché de Playwright: busca el navegador como el
  resto del hub.
- **La portada ya no se sale de lado en el móvil** cuando el aviso de «se
  perdió una sesión de trabajo» lleva una ventana cuyo título es una ruta
  larga sin espacios.
- **Mover un slot a un proyecto que no existe** ya no enseña «el índice del
  hub no se puede leer»: vuelve a la ficha diciendo que ese proyecto no
  existe, y el slot se queda como estaba.
- **Si archivar un lienzo falla, el aviso dice qué pasó.** Salía un diálogo en
  blanco, sólo con «Entendido».
- **La API contesta 400, no 500, si el cuerpo no es un objeto JSON** (`[]`,
  un texto suelto o algo que no es JSON), con `{"ok": false, "error": …}`.
- **`/api/docs` y `/redoc` ya no existen.** Cargaban Swagger y Redoc de
  internet, y el hub no carga nada de fuera. La lista entera de la API sigue
  en `/openapi.json` (`curl -s localhost:8787/openapi.json | jq '.paths | keys'`).
- **Una sesión que corre una herramienta larga ya no sale como parada.** Claude
  Code deja el título en reposo mientras trabaja con una orden larga, y el
  punto de estado de Trabajo y los avisos de «sesión quieta» lo daban por
  parado. Ahora el muestreo mira también su pantalla.
- **El asistente ya no recibe `/clear` ni `/compact` con un permiso o un menú
  abiertos**: antes se pegaban sin mirar y caían dentro del diálogo.
- **Los errores de tmux en la terminal y en el panel se dicen**, en vez de
  tragarse o dar un error 500 (renombrar con tmux parado, por ejemplo).
- **Seguridad: volver tras un formulario sólo lleva a pantallas del hub.** Un
  destino de fuera (`https://…`, `//…`) se ignora.
- **Canal y Encargos explican un `user_id` que no es un número**, en vez de
  enseñar «invalid literal for int()».

## 0.4.0 — 2026-10-23

Más fácil de usar: actualizar con un botón, dictarle a Claude Code, el menú
agrupado y los kits con su catálogo y sus botones.

### Qué tienes que hacer

- **Actualiza esta vez como siempre**, con `bash scripts/actualizar.sh` en la
  carpeta del hub. Desde esta versión, las siguientes se hacen con el botón de
  **Actualizaciones**.
- **Pulsa «Limpiar» en el chat del asistente**, para que sepa de la pantalla
  Actualizaciones, del dictado y del catálogo de kits.
- **Recarga con Ctrl+Shift+R** la primera vez: el menú y la terminal cambian.

### Nuevo

- **El catálogo de kits, con botones.** En Inventario → Kits, arriba, cada kit
  publicado dice si lo tienes y en qué versión. **Instalar** lo trae a tu
  máquina y **Aplicar a…** lo pone en el proyecto que elijas, en una ventana
  donde ves los cambios antes de hacerlos. Sin terminal.
- **Actualizar con un botón.** Nueva pantalla **Actualizaciones** (en el
  menú, Ajustes): qué versión tienes, si hay otra y «Actualizar ahora». Te
  enseña lo que va pasando y vuelve sola cuando el hub se reinicia. Ya no
  hace falta copiar ningún comando.
- **Dictar en la terminal.** El botón «Dictar» graba lo que dices, lo
  transcribe en tu máquina y lo deja escrito en la terminal sin enviarlo,
  para explicarle algo largo a Claude Code sin teclearlo. Si preparaste
  Reuniones, usa su Whisper; si no, te dice cómo tener un transcriptor.
- **El menú, agrupado.** Panorama y Trabajo arriba; el resto en cinco grupos
  que se despliegan (Agentes, Proyectos, Vigilar, Comunicación y Ajustes). Un
  grupo cerrado enseña sus avisos urgentes.
- **Tres kits más en el catálogo:** *Orquestación* (el método para trabajar
  de forma semiautónoma con Claude Code: roles, delegación y techo de
  consumo), *Consulta por Telegram* (que una sesión pueda preguntarle a otra
  persona cuando tú no estás) e *Inmersión en inglés* (un kit de máquina para
  practicar inglés mientras programas).

### Qué cambia en lo que ya usabas

- **Las versiones nuevas se miran cada hora**, y otra vez al entrar en
  Actualizaciones. Antes, una vez al día: una versión recién publicada podía
  tardar un día en aparecer.
- **La versión ya no está en la Guía**: tiene su pantalla, Actualizaciones.
- **En Trabajo, los avisos de arriba miden lo que su texto.** Con dos avisos a
  la vez se estiraban hasta ocupar media pantalla.

## 0.3.1 — 2026-10-23

Corrección de errores y mejoras de uso: lo que pasaba al reiniciar WSL, crear
y retomar desde Trabajo sin salir de ahí, y dos pantallas nuevas que se
preparan solas paso a paso.

### Qué tienes que hacer

- **Actualiza** con `bash scripts/actualizar.sh` en la carpeta del hub.
- **Pulsa «Limpiar» en el chat del asistente** después de actualizar: sabe
  ayudarte a preparar Navegante y Reuniones, y eso viene en sus instrucciones
  nuevas.
- Si quieres **Navegante** o **Reuniones**, entra en su pantalla: te dice qué
  falta y cómo conseguirlo. Si no, no hace falta nada.

### Nuevo

- **Navegante.** Un navegador de verdad que maneja Claude, con un guardián
  que pausa todo lo que modifica hasta que lo permites. Se le enseña un flujo
  haciéndolo una vez y lo repite.
- **Reuniones.** Graba la reunión que tienes en otro monitor (pantalla, audio
  sólo de la aplicación y tu micro) y la procesa en tu máquina: transcripción,
  resumen, tareas y decisiones. Necesita un agente pequeño en Windows; la
  pantalla lo copia a la carpeta que elijas y lo instalas con un doble clic.
- Las dos vienen con el hub (en `componentes/`) y, mientras no están
  preparadas, su pantalla enseña los pasos que faltan, medidos en tu máquina.
  **«Preparar con Claude»** abre una ventana con el encargo escrito y sin
  lanzar; **«Guíame»** se lo pregunta al asistente. Desde el chat:
  `hub componentes` y `hub preparar <navegante|reuniones>`. Todo en
  `conocimiento/12-navegante-y-reuniones.md`.
- **Crear desde Trabajo.** En la lista de la izquierda hay «+ Proyecto» y, al
  final de cada proyecto, «+ Slot nuevo». Crear un slot desde ahí le abre su
  terminal con Claude y te lleva a ella. Si aún no tienes proyectos, la lista
  te explica qué son y te ofrece crear el primero.
- **Conversaciones anteriores de un slot.** En la cabecera del slot,
  «Conversaciones» lista las que tuviste con Claude en esa carpeta, con su
  título y cuándo fueron. «Retomar» abre una ventana con esa conversación tal
  como la dejaste: cerrar la consola ya no es perder el hilo. Un slot sin
  ninguna ventana abierta te las ofrece directamente.
- **Las ventanas, dentro de su slot.** La lista de la izquierda de Trabajo es
  ahora un árbol: proyecto → slot → ventanas. Pulsa una para verla, doble clic
  para renombrarla, × para cerrarla y «+ Ventana» para abrir otra en ese slot.
  En el escritorio sustituye a las pestañas de encima de la terminal, que
  siguen apareciendo con el raíl plegado, a pantalla completa y en el móvil.
- **Chats anteriores del asistente**, a la vista bajo su chat. «Limpiar» ya no
  pierde nada: la conversación de antes queda ahí y puedes volver a ella.

Claude Code guarda cada conversación 30 días; las más viejas las borra él.

### Qué cambia en lo que ya usabas

- **Tras reiniciar WSL, las terminales que ya no existen dejan de salir como
  abiertas.** Antes el slot seguía en verde y su «Abrir» llevaba a una sesión
  muerta. Lo que se perdió sigue en el aviso de la portada, para reabrirlo.
- **Ya no sale «se perdió una sesión · 0 paneles»** al reiniciar sin nada
  abierto: no se había perdido nada.
- **Una terminal cuya sesión ya no existe lo dice y deja de reintentar**
  («esa sesión ya no existe · ábrela desde su slot»), en vez de repetir el
  mismo error cada diez segundos. Si lo que falla es tmux un momento, sigue
  reintentando sola como antes.
- **«Vuelve tras un apagón» ahora se llama «Persistente».** Es lo mismo: un
  slot persistente se reabre cuando vuelves a encender el equipo, por apagón o
  porque apagaste tú. Lo que ya tenías marcado sigue marcado. En la portada, el
  aviso se llama «Reabrir tus slots persistentes».
- **Una ventana abierta con el «+» de las pestañas queda en su slot.** Antes
  se abría en la carpeta del slot pero salía suelta, en «Sin organizar».
- **Al entrar en Trabajo, todos los proyectos salen plegados** salvo el del
  slot que estás mirando.
- **Si tienes cambios propios en el código del hub, `actualizar.sh` te dice
  qué hacer con ellos** en vez de sólo pararse: guardar una copia y
  descartarlos (lo habitual, si eran arreglos de urgencia) o guardarlos en una
  rama. La receta, y cómo encontrar la carpeta del hub en WSL, están en
  `conocimiento/11-versiones.md`.
- **Los tests ya no dependen del nombre de tu máquina.** Uno sólo pasaba en un
  equipo llamado `DESKTOP`.

## 0.3.0 — 2026-10-22

Arreglos de lo que reportaron quienes lo usan, y lo que hace falta para que un
apagón tenga vuelta.

### Qué tienes que hacer

- **Actualiza** con `bash scripts/actualizar.sh` en la carpeta del hub.
- **Pulsa «Limpiar» en el chat del asistente** después de actualizar, para que
  lea sus instrucciones nuevas.
- **Marca los slots que quieras recuperar tras un apagón** (Trabajo → «↻ No
  vuelve tras un apagón»). Máquina → «Salud del hub» te dice si no hay
  ninguno.

### Nuevo

- **El asistente prepara la aplicación de kits.** Pídele «aplícale los kits
  lienzos y telegram a mi-proyecto»: deja en `/trabajo` una ventana en la
  carpeta del proyecto con el encargo escrito. No se lanza solo: pulsas Enter
  allí y esa sesión te enseña lo que va a cambiar antes de hacerlo.
- **Imágenes en la terminal web.** Arrastra una imagen sobre la terminal o
  pégala del portapapeles (Ctrl+V): se guarda en la carpeta de intercambio del
  hub y su ruta queda escrita en la terminal, lista para que Claude Code la
  lea. No se envía sola.
- **El intercambio va por proyecto y slot.** Lo que subes eliges de qué
  proyecto o slot es, lo que pegas en la terminal va solo al de esa ventana, y
  la pantalla lo agrupa así, lo más nuevo primero. Lo pegado o arrastrado en
  la terminal **se borra solo a los 10 días** (cada archivo dice el día); lo
  demás se queda hasta que lo borres.
- **Restaurar reanuda tu conversación.** Tras un apagón, las ventanas que
  tenían Claude Code vuelven con `claude --resume <id>` escrito (sin Enter):
  la conversación exacta que tenían. Se cambia con `HUB_RESTAURAR_CLAUDE`
  (`reanudar`, `nuevo` o `nada`).
- **Marcar qué vuelve tras un apagón, con un clic.** En Trabajo, en la
  cabecera del slot: «↻ Vuelve tras un apagón». Los marcados llevan ↻ en la
  lista.
- **Salud del hub**, en Máquina: si el muestreo late, si hay slots que
  vuelven, si los servicios arrancan solos, el *linger* y la copia de la base,
  cada uno con su arreglo. Si el muestreo se para, lo dicen todas las
  pantallas.
- **Teclas especiales en el móvil.** Debajo de la terminal, en pantallas
  táctiles: Esc, Ctrl+C, Tab, ⇧Tab, flechas, Enter y «Imagen» para adjuntar
  una foto del teléfono.

### Qué cambia en lo que ya usabas

- **Las respuestas en varias líneas se ven limpias en el chat del asistente.**
  Salían con unas etiquetas `<pasted_content>` y la línea de la pantalla
  delante. Y el asistente sabe ya que ese bloque lo escribiste tú.
- **«Lanzar» un slot abre una sola ventana.** La página tardaba hasta 20
  segundos en verlo abierto y seguía enseñando el botón; cada pulsación abría
  otra. Ahora lo ve al momento, y el botón se apaga («Abriendo…») al pulsarlo.
- **Las ventanas que abre el hub van al final de la lista.** Antes una nueva
  tomaba el número de la última que cerraste y quedaba a media lista. Los
  números ya no se reutilizan, así que pueden quedar huecos (1, 2, 5…): es a
  propósito, para que un enlace o una terminal que se reconecta no acabe en
  otra ventana.
- **El panel de la derecha de Trabajo se pliega del todo** desde el propio
  panel («»», junto a las pestañas) y se vuelve a abrir desde la pestaña
  «‹ Nota» del borde. El botón «Nota» de la cabecera sigue haciendo lo mismo.
- **La carpeta de intercambio**: lo que ya tenías ahí sale en «Sin proyecto»;
  no se mueve ni caduca nada de lo anterior.
- **Un clon sin remoto no enseña un error en «Versión»**: simplemente no busca
  versiones nuevas.

## 0.2.0 — 2026-10-20

La primera versión con número. Desde aquí, cada versión se publica con su
etiqueta (`v0.2.0`), su entrada en este archivo y, si hace falta, sus pasos
propios, y se actualiza con un solo comando.

### Qué tienes que hacer

🔴 **Si instalaste el hub antes de esta versión**, actualiza esta vez así:

```bash
git status --short --untracked-files=no     # tiene que salir vacío
git pull --ff-only && bash scripts/actualizar.sh --sin-bajar
```

Si `git status` enseña archivos, tienes cambios propios en el código del hub:
qué hacer con ellos está en `conocimiento/11-versiones.md` («Tengo
cambios míos en el clon»). Vale igual si llegas directamente a una versión
posterior.

`git pull` y reiniciar —lo que decía la documentación hasta ahora— **no basta
esta vez**: los servicios se generan distinto y el asistente trae instrucciones
nuevas. Si ya hiciste sólo el `git pull`, el hub te lo dice en todas las
pantallas hasta que corras `actualizar.sh`. Tus datos no se tocan.

Después de actualizar:

- **Revisa los guardrails de tus proyectos** (ver «Qué cambia»): si el
  orquestador trabaja en proyectos con `guardrail: ask`, ahora te pedirá
  confirmación la primera vez que toque cada uno en cada tarea.
- **Pulsa «Limpiar» en el chat del asistente** (rueda de ajustes) para que lea
  sus instrucciones nuevas.

### Nuevo

- **Versiones y aviso de versión nueva.** El hub sabe qué versión tiene, mira
  una vez al día si hay otra publicada y lo dice arriba en todas las pantallas.
  Nunca se actualiza solo. `/guia` tiene una sección «Versión». Se apaga con
  `HUB_BUSCAR_VERSIONES=0` (es la única consulta a internet que hace el hub por
  su cuenta).
- **`scripts/actualizar.sh`**: baja la versión, regenera los servicios con tu
  puerto y tus datos, pone al día el asistente, aplica los pasos de cada
  versión, reinicia lo que estaba en marcha y te dice qué cambió.
- **Copia diaria de la base.** `hub.db` guarda datos que no existen en ningún
  otro sitio —tus slots y sus notas, el canal, los mensajes programados, los
  encargos—, así que ahora se copia sola una vez al día, guardando las 14
  últimas, en `~/.local/share/hub/respaldos/` (o `HUB_RESPALDO`). `/respaldo`
  dice cuándo fue la última y avisa si tiene más de dos días. Esa carpeta está
  en el mismo disco: cópiala a otro sitio si quieres sobrevivir a un disco
  muerto.
- **El comando `hub` en `~/.local/bin`**, también fuera del chat del asistente.
  Lo crea `sembrar-asistente.sh` (y `actualizar.sh` si ya tenías asistente). Si
  ya tenías un `hub` ahí, no se pisa.
- **El orquestador pide confirmación** en los proyectos con `guardrail: ask`:
  una tarjeta en `/orquestador` con «Confirmar» o «No, sin ese proyecto».
- **Documentación**: `conocimiento/10-mas-pantallas.md` (Acceso, Canal,
  Encargos, Lienzos, Programados, Archivos, Máquina, Consumo y atajos), y el
  resto puesto al día con lo que el hub hace hoy.

### Qué cambia en lo que ya usabas

- 🔴 **`guardrail: ask` ahora significa algo.** Antes `auto` y `ask` se
  comportaban igual. Ahora, en un proyecto `ask`, el orquestador no abre
  sesiones, no manda trabajo, no ajusta ni compacta sin que confirmes —una vez
  por tarea y proyecto—. Si quieres que trabaje sin preguntar en un proyecto,
  ponlo en `auto`. `never` sigue igual.
- **`hub.db` no se borra nunca.** La documentación decía que se reconstruía
  escaneando; no es verdad para tus slots y notas. Si la base no abre, se
  aparta y se restaura desde la copia diaria (`conocimiento/06-problemas.md`).
- **Seguridad, dicha como es.** La terminal y el resto del hub siguen
  escuchando sólo en `127.0.0.1`. Para entrar desde el móvil está `/acceso`
  (red privada, aparatos dados de alta por QR y un interruptor aparte para la
  terminal). La documentación ya no dice que lo único que protege es el bind.
- **Los textos de la pantalla ya no citan números de reglas** internas.
- **Los servicios llevan `HUB_PORT`**: si instalaste el hub en otro puerto, el
  aviso de «el hub no contesta» y el pánico del canal miran ya el correcto.
- **`HUB_CONTEXTO_FICHERO`** se respeta también en el lado del hub (antes sólo
  lo leía la línea de estado del asistente).
- **El kit `lienzos`** está en el catálogo público (0.2): su skill dice dónde
  están de verdad las plantillas.

## 0.1.0 — hasta el 2026-10-17

Todo lo publicado antes de que el hub tuviera número de versión. No tiene
etiqueta: quien lo instaló entonces pasa a la 0.2.0 con el comando de arriba.
