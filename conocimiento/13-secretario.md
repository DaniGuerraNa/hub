# El secretario

Un asistente de tu día a día dentro del hub. Hace cinco cosas:

- **lee** tus fuentes: tus reuniones grabadas, las notas de tus slots y, si los
  conectas, tu Telegram, tu correo (IMAP), los chats de WhatsApp que exportes y
  tu calendario (Google o iCal);
- **te contesta** lo que le preguntes sobre eso, y dice de dónde lo sacó (qué chat,
  quién y cuándo);
- **apunta solo** las notas y los compromisos que salen de lo que lee;
- **te recuerda** lo que quedaste en hacer, en el teléfono;
- **hace** las acciones que tiene: apuntar, poner algo en tu calendario, crear
  un proyecto o un slot, o encargarle trabajo al orquestador, y te pregunta
  antes si así lo decides.

Está en [Secretario](/secretario), arriba en el menú.

## Encenderlo

Viene **apagado**: cada respuesta usa tu suscripción de Claude, y eso lo decides
tú. Mientras está apagado, su pantalla lo dice arriba y ofrece **Encenderlo**:
te lo recuerda antes, lo enciende y lo deja encendido también cuando reinicies
el equipo. No lo da por encendido hasta que da señales; la primera vez puede
tardar un minuto. Lo que le escribas mientras tanto espera a que arranque.

Si lo prefieres en la terminal, es lo mismo:

```bash
systemctl --user enable --now hub-secretario
```

Si se cae nada más arrancar, la pantalla lo dice y te da el comando para ver
por qué.

Sin systemd de usuario (un contenedor, WSL sin systemd), `scripts/arrancar.sh`
arranca la web y el muestreo pero no a él: lánzalo en una terminal aparte, en
la carpeta del hub, con `uv run python -m hub.secretario`.

Si quieres que te llame por tu nombre, ponlo en
`~/.local/share/hub/secretario/secretario.yml`:

```yaml
dueno: Tu nombre
```

## Hablarle

- **Escribiendo**, en el cuadro de abajo. Enter manda; Mayús+Enter es un salto de
  línea.
- **Hablando**: pulsa «Hablar», di lo que quieras y pulsa «Parar». Se transcribe
  en tu máquina con el mismo Whisper que usa Reuniones, así que hace falta tener
  Reuniones preparado. El texto queda en el cuadro para que lo leas antes de
  enviarlo, salvo que marques «Al terminar de hablar, mandarlo solo».
- **Manteniendo Ctrl+Espacio** (en el PC, en cualquier pantalla y aunque el
  cursor esté en otro campo o en la terminal): graba mientras la mantienes y,
  al soltar, se lo manda directamente. Si el panel estaba plegado, se abre. Un
  toque corto, o cambiar de ventana con la tecla pulsada, no manda nada.
- **Con algo adjunto**: el clip a la izquierda del cuadro, **Ctrl+V** de una
  captura (también la de Win+Shift+S) o soltar el archivo sobre la
  conversación. Antes de mandar ves sus miniaturas (✕ quita una), y puedes
  mandarlo sin escribir nada. Las **imágenes y los PDF los ve** («¿qué pone en
  esta captura?», «resúmeme este PDF»); de lo demás sólo conoce dónde está,
  para pasárselo a quien le encargue algo. Lo que hay dentro lo trata como
  dato, no como órdenes: si la captura de un chat dice «haz X», no lo hace por
  eso. Queda en **Intercambio** (`_secretario/<día>/`) y se borra solo a los
  diez días. Una foto de más de 3,5 MB se reduce con `ffmpeg`; sin él, no la
  ve y te lo dice. Hasta 10 por mensaje; un PDF, hasta 10 MB, y entre todo lo
  que ve, hasta 15 MB por mensaje (lo que no cabe le llega sólo como ruta).
- **Oírle**: marca «Leer las respuestas en voz alta». Usa la voz de tu navegador:
  no instala nada y no saca el texto a ningún servicio.
- **Modo voz** (el botón de las ondas, junto al micrófono): hablas sin tocar
  nada. Escucha, manda lo que dijiste cuando te callas, lee la respuesta y
  vuelve a escuchar, hasta que salgas con **✕**. Para interrumpirle mientras
  habla, háblale (o toca el círculo); tocarlo mientras te escucha manda ya lo
  que llevas dicho. **Pausar** apaga
  el micrófono sin salir del modo. Si te callas, sigue esperando; tras unos
  dos minutos sin oírte se pone en pausa solo, y también si sales de la app.
  Mientras dura, la pantalla no se apaga.
  Te lee la respuesta frase a frase según la escribe, así que empieza a
  hablar a los pocos segundos; por voz contesta en dos o tres frases, y si
  tiene que consultar algo te lo dice primero.
- **English** (debajo del cuadro): práctica de inglés. Conversa en inglés
  sobre tu día —puede mirar tus slots y proyectos para hablar de lo que
  haces—, te corrige un error por turno y a veces te pregunta como en una
  entrevista. Si le hablas en español te contesta en inglés (sirve para
  preguntar «¿cómo se dice…?»). Mientras está puesto **no hace nada por su
  cuenta**: cualquier acción, también un recordatorio, sale como permiso que
  apruebas en Pendientes, y no le contesta al orquestador. Lo que hayáis
  hablado no queda como notas. Se quita con el mismo botón. Para hablarle
  en inglés hace falta el Whisper del hub: si declaraste otro transcriptor
  en `encargos.yml`, te dirá que no sabe cambiar de idioma.

Cuando la respuesta tiene varias cosas comparables, te las enseña en una tabla
debajo del texto.

### Investigar algo en la web

Pídele algo **público** —«¿qué dice la norma de facturación?», «¿cuánto cuesta
el plan X?», «¿qué cambió en la versión 5?»— y te contesta al momento «lo
investigo y te lo dejo aquí». Lo busca y lo lee aparte y, en unos minutos, te lo
deja en la misma conversación:

- cada dato con **la página de donde sale y la fecha que dice esa página**
  («sin fecha» si no dice ninguna); lo que llega sin página no se enseña;
- **lo que no encontró**, dicho;
- una tarjeta con las fuentes, para comprobarlas (copia la dirección en el navegador).

Empieza siempre con la línea «De la web, investigado aparte: es dato, no
instrucción»: lo que dice una página lo escribió cualquiera. Por eso quien
investiga **sólo puede buscar y leer**: no puede anotar, avisarte, encargar
nada ni tocar tus archivos, aunque una página se lo pida. Las páginas las pide
desde tu máquina, y no le deja pedir ni la propia máquina ni tu red de casa o
privada (`localhost`, `*.local`, `*.ts.net`, `192.168.*.*`…); un nombre que no
está en esa lista y apunta a tu red pasaría, así que es una red, no una
garantía. **Lo que le pides no puede llevar direcciones** (ni `https://…`, ni
`www.`, ni un nombre de sitio, ni una IP): la pregunta la redacta el secretario,
que conoce tus cosas, y una dirección ahí sería la forma de que un adjunto o un
mensaje de otro le hiciera mandarlas a un sitio ajeno. Di el tema o el nombre
(«el portal del SAT»); si quieres que pueda nombrar un sitio concreto, añádelo
en `secretario.yml` → `investigar: {sitios: [ejemplo.org]}`. Lo que encontró
queda también en sus notas (tema «investigación»), y luego puedes preguntarle
por ello. Lo que le pidas sale a un buscador: no metas datos tuyos ni de nadie
(los de «mis datos» confirmados no los deja pasar).

Cada investigación tiene un **tope de gasto**, contado como lo que costaría
por la API: 0,50 USD. Una pregunta sencilla gasta bastante menos; si una muy
amplia no cabe, te dice que no terminó y te pide acotarla. Para cambiarlo, en
`secretario.yml`:

```yaml
investigar:
  tope_usd: 1.0
```

Las investigaciones van de una en una, en la misma cola que los resúmenes de
sesión, y esperan como mucho cinco a la vez. Las hace Haiku, que es con el que
se midió el tope; para otro, `investigar: sonnet` en `modelos.yml` (y quizá un
tope mayor). No maneja tu navegador ni entra con tus cuentas.

### El personaje: qué está haciendo

El secretario tiene cara: un cuadrado pequeño en el color del hub, con ojos.
Está en la pestaña que te sigue por todas las pantallas (abajo a la derecha) y
en la cabecera de su pantalla, y enseña lo que **de verdad** está haciendo,
con una línea debajo que lo dice:

- **Te escucha** (ondas que laten con tu voz), **transcribe**, **piensa** (mira
  arriba y le suben tres cuadraditos), **escribe** y **te habla** (abre la
  boca con cada palabra).
- **Trabajando**, lleva en la mano lo que usa —lupa para buscar, hoja para
  leer, sobre para tus mensajes, calendario, carpeta, campana, mando de la
  tele…— y la línea lo dice con sus palabras: «Buscando «Ana» en tus
  mensajes», «Leyendo notas.md». Si pasa el turno a un modelo mayor, se pone
  gafas.
- **Levanta la mano** con un «?» ámbar cuando una acción espera tu sí; un ✓
  verde cuando acaba de contestar y un «!» rojo si algo falló (se van solos).
- **Quién trabaja para él** aparece a su lado: la tarea que le encargó al
  orquestador, la sesión de tu proyecto que la está haciendo y los subagentes
  de esa sesión, cada uno con la ropa de su rol (arquitecto con casco, revisor
  con gafas, diseñador con boina, explorador con sombrero…), un resumen de
  sesión que esté leyendo aparte y lo que esté investigando en la web (con la
  ropa del investigador; las que esperan, en cola). Caben tres y un «+N».
  Nunca pinta a nadie que no exista: el secretario no tiene ayudantes propios.

**Le pasa encargos a tus sesiones abiertas.** Si tienes Claude Code abierto en
un slot y le dices «pásale esto a mi terminal de trabajo», te pide permiso con
el texto exacto y se lo escribe a esa sesión, con una primera línea que dice que
viene de él por encargo tuyo; así lo hace con su contexto y tú sigues en ella.
Luego le puedes preguntar qué contestó. Siempre pregunta antes (aunque en
Confianza lo pongas en automático), sólo escribe si la sesión está quieta, y si
el slot tiene dos ventanas con agente te pregunta a cuál. Un proyecto con
guardrail `never` no se toca. Con Claude Code, además, no escribe si tiene un
permiso o un menú abiertos, y puede leerte lo que contestó; de Codex todavía no
sabe leer ni lo uno ni lo otro.

**Puedes ponerle nombre.** En **Ajustes → Personaje**, arriba del todo,
«Cómo se llama»: el que escribas sale en el menú, en su pantalla y en la app
instalada, y él sabe que es el suyo desde la siguiente conversación. Vacío
vuelve a «Secretario». (En el teléfono, una app ya instalada puede quedarse con
el nombre viejo bajo el icono hasta que la reinstales.)

**Puedes elegir quién es.** En **Ajustes → Personaje**, arriba, están el
cubo de siempre y varios dibujados (ranitas, hongos y los dos juntos): pulsa
«Usar este» y lo verás en la pestaña, en la cabecera y en todos tus aparatos.
Los dibujados tienen su propia pose para escuchar, pensar, buscar, anotar,
hablar, esperar tu sí, celebrar y dormir (si a alguno le falta una, se queda
en su dibujo base); lo que tiene en la mano en cada
momento sale en una insignia redonda a su lado, y los globos («?», ✓, «!»)
son los mismos que los del cubo.

Cada estado se ve al menos medio segundo, para que no parpadee. Si tu sistema
tiene «reducir movimiento», se queda quieto en la pose de cada estado. Para
verlo todo a la vez sin provocarlo: **Ajustes → Personaje**, con una
conversación de ejemplo que se reproduce con un botón.

### Modo monitor: para tenerlo en otra pantalla

Si tienes una pantalla libre, pulsa **Modo monitor** arriba a la derecha de
su pantalla (en el PC; o abre `/secretario/monitor`). Ocupa la pantalla entera,
sin el menú del hub: a un lado un escenario con sus puestos y al otro la
conversación de siempre, para escribirle o hablarle desde ahí.

El personaje va **al puesto de lo que está haciendo**, con el rótulo encima:

- **Mensajes** cuando lee o busca en lo que te escribieron o en tus reuniones,
  o te manda un aviso;
- **Agenda** para tu calendario y la hora;
- **Te espera** cuando algo necesita tu sí o repasa tus compromisos;
- **Proyectos** para tus carpetas, archivos e ideas;
- **Máquina** para el hub, la máquina, tu pantalla, grabar o la tele;
- **Navegador** cuando te abre algo en la PC o te prepara algo que ver;
- **Orquestador** cuando le encarga trabajo, y ahí espera mientras lo
  delegado sigue en marcha, con quien trabaja para él al lado;
- **Su mesa** para escucharte, pensar, escribirte y descansar.

Al volver a su mesa trae en la mano el objeto del puesto del que viene. Si
algo te espera sin que lo hayas visto, en vez de su mesa espera junto a
**Te espera**, con la cifra al lado del nombre (pulsándolo vas a Pendientes).

No se mueve por moverse: sólo cuando cambia de puesto. Con «reducir
movimiento» en el sistema cambia de sitio sin andar, y con la pestaña
escondida no hace nada hasta que vuelves. **Salir del modo monitor**, arriba,
te devuelve a su pantalla.

**Desde el teléfono:** entra por [Acceso](/acceso), abre Secretario y añádelo a
la pantalla de inicio. El icono abre directamente el secretario, como una app:
secciones abajo y el cuadro de escribir siempre a la vista. En la PC, la
conversación tiene al lado lo que espera tu permiso y lo próximo.

Tiene cuatro secciones: **Conversación**, **Pendientes**, **Memoria** y
**Ajustes** (dentro: Avisos, Fuentes, Confianza, Disparadores y Personaje).

### Por qué no se llena nunca

Cada conversación es un **hilo**. Lo que sabe no vive en la conversación, sino en
su memoria, y la consulta cuando hace falta. Tras media hora sin hablar, el hilo
se cierra solo: se guarda un resumen y las notas que salieron, y la siguiente
conversación empieza limpia. No hay que compactar ni limpiar nada a mano.
«Conversación nueva» lo cierra en el momento.

### Qué modelo contesta

Depende del trabajo:

| Trabajo | Modelo |
|---|---|
| Leer lo que llega y sacar notas y compromisos | Haiku |
| Hablar contigo | Sonnet |
| Planificar algo de varios pasos o decidir con consecuencias | Opus (lo pide el propio Sonnet) |
| Investigar algo en la web (`investigar`) | Haiku |

Bajo cada respuesta ves qué modelo la dio y cuánto tardó. Para cambiar la tabla:
`~/.local/share/hub/secretario/modelos.yml`, por ejemplo con `conversacion: haiku`.

## Fuentes

En **Ajustes → Fuentes** enciendes cada fuente y eliges qué conversaciones lee:
«Sólo estas» o «Menos éstas», por nombre y separadas por comas. Todas las fuentes
son de **sólo lectura**: el secretario no contesta a nadie en tu nombre.

**El hub** viene encendida. Lee tus reuniones grabadas que ya tienen resumen y las
notas de tus slots.

**Telegram** se lee con **tu cuenta**, no con un bot: un bot no ve tus grupos.
Para conectarla:

1. En <https://my.telegram.org>, entra en «API development tools» y crea una
   aplicación. Te da un `api_id` y un `api_hash`.
2. En la carpeta del hub, corre esto. Te pide los dos datos, tu teléfono y el
   código que Telegram te manda:

   ```bash
   uv run python -m hub.secretario telegram-entrar
   ```

3. Enciéndela en la pestaña Fuentes.

La primera vez trae los últimos 14 días; después, sólo lo nuevo. Lo que es
sólo una cortesía («ok», «jaja», un sticker) se guarda y se puede buscar, pero
no se le pasa al modelo: no gasta tu suscripción. Los canales de
noticias no se leen salvo que los pongas en «Sólo estas». Los audios se
transcriben en tu máquina.

🔴 **La sesión de Telegram es una llave de tu cuenta entera.** Vive en
`~/.secretos/secretario-telegram/`, con permisos solo para ti. Sólo la abre el
servicio `hub-secretario`, nunca la web.

**Correo** se lee por IMAP: Gmail, Outlook o el de tu dominio. Para conectarlo:

```bash
uv run python -m hub.secretario correo-entrar
```

Pide el servidor (`imap.gmail.com` por omisión), tu correo y una **contraseña
de aplicación** (en Gmail: Cuenta de Google → Seguridad → Contraseñas de
aplicaciones; hace falta tener la verificación en dos pasos). Prueba a entrar
antes de guardar nada, y la guarda en `~/.secretos/secretario-correo/` con
permisos sólo para ti. Luego enciéndela en Ajustes → Fuentes.

- **No marca nada como leído:** abre los buzones en modo de sólo lectura.
- Lee la bandeja de entrada; otros buzones, con `buzones: [INBOX, "[Gmail]/Enviados"]`
  en `fuentes.yml`.
- Los boletines y avisos automáticos no se leen salvo que su remitente esté en
  «Sólo estas». En el correo, «Sólo estas» y «Menos éstas» valen por
  fragmento: `github.com` o `Ana` bastan.
- De una respuesta se queda lo nuevo, sin el hilo citado debajo.

**En los grupos, qué es para ti.** Cada mensaje sabe si va para ti: un chat
contigo, uno donde te etiquetan o responden a un mensaje tuyo (Telegram), o uno
que te nombra. En un grupo, lo que no va dirigido a ti no se apunta como
pendiente tuyo aunque pida algo «al team». Cómo te llaman se pone en los
ajustes de la fuente, en `fuentes.yml`: `alias: [Ana, Anita, anaperez]` (tu
usuario también vale). Sin `alias`, se usa el `dueno` de `secretario.yml`. Un
disparador de mensaje puede saltar **«Sólo si es para mí»**.

Lo que se anuncia **a todo el grupo** y te afecta igual te llega al teléfono
(«📣 En el grupo»): una reunión que se mueve, se cancela o se convoca, una
caída, un plazo para todos. Y si un mensaje cambia la hora de un pendiente tuyo
—«la planning se movió a las 4:30»—, lo mueve y te avisa («🔁 Pendiente
movido»). Sólo con mensajes de las últimas horas, y nunca lo cierra ni lo borra. En WhatsApp las
etiquetas llegan como un número, así que allí sólo se sabe si te nombran.

**WhatsApp (exportado a mano)** es la forma sin riesgo para tu cuenta: no se
conecta nada a WhatsApp. En el teléfono, en un chat: ⋮ → Más → **Exportar chat**
→ «Sin archivos», y deja el `.txt` (o el `.zip`) en
`HUB_HOME/secretario/whatsapp-exportado/`. Lo lee en unos minutos. No es en
vivo: lee lo que exportes; exportar otra vez el mismo chat sólo añade lo nuevo.
Tus mensajes salen como «Yo» si tu nombre en el chat coincide con el `dueno` de
`secretario.yml` (o pon `yo: [Tu nombre]` en los ajustes de la fuente).

**WhatsApp (provisional)** se lee de una de tres formas, y las tres dejan los
mensajes en el mismo archivo que el secretario lee. El hub no habla con WhatsApp.

- **La extensión de Chrome** lee dentro del WhatsApp Web que ya tienes abierto.
  No abre ninguna sesión nueva; sólo lee mientras la pestaña esté abierta.
- **La app de escritorio de Windows**: un pequeño programa lee dentro de la
  app de WhatsApp mientras está abierta. Para eso la app arranca con un puerto
  de depuración en `127.0.0.1`. 🔴 Mientras ese puerto esté abierto, cualquier
  programa de tu PC puede manejar la app.
- **El colector** abre WhatsApp Web en un navegador sin ventana, con su propia
  sesión vinculada (abajo).

Las dos primeras se instalan desde WSL con
`bash componentes/whatsapp-web/lector/instalar.sh extension` (o `escritorio`),
que dice lo que falta hacer a mano; `instalar.sh quitar` deshace lo que puso en
el registro. Si usas las dos a la vez, `uv run python -m hub.secretario
whatsapp comparar` dice cuántos mensajes vio cada una, cuántos sólo ella y con
cuánto retraso.

Lo que sigue sobre el riesgo vale para las tres: ninguna es oficial.

🔴 **Antes de encenderla, el riesgo.** WhatsApp no permite programas no
oficiales y **puede bloquear tu número**, temporal o definitivamente, **aunque
sólo se lea**: hay casos documentados de cuentas avisadas que no enviaban nada.
Es poco probable, pero si pasa pierdes el número. Por eso:

- **Pruébala primero con un número secundario** un par de semanas.
- Exporta antes los chats que te importen (WhatsApp → chat → Exportar): es lo
  único que sobrevive a un bloqueo.
- Vincula **una vez** y déjala vinculada; vincular y desvincular a menudo es
  peor.

Para conectarla (hace falta Node 22 o más y un Chromium; usa el de Playwright
si lo tienes, o el que digas en `HUB_WHATSAPP_CHROME`):

1. Instala el colector, una vez:

   ```bash
   cd componentes/whatsapp-web && PUPPETEER_SKIP_DOWNLOAD=1 npm ci
   ```

2. Vincúlalo. Pinta un QR en la terminal: en el teléfono, WhatsApp →
   Dispositivos vinculados → Vincular un dispositivo.

   ```bash
   uv run python -m hub.secretario whatsapp entrar
   ```

3. Déjalo escuchando, por ejemplo en una ventana de tmux (no viene como
   servicio: es provisional):

   ```bash
   uv run python -m hub.secretario whatsapp escuchar
   ```

4. Enciéndela en Ajustes → Fuentes. Ahí mismo dice si el colector está parado
   y desde cuándo.

- **No marca nada como leído ni te pone «en línea»:** no abre ningún chat y
  se anuncia «no disponible», así que tu teléfono sigue avisándote.
- Lee lo que llega y lo que escribes tú (para los compromisos). Al arrancar
  recoge lo que entró mientras estaba parado (los últimos 20 por chat;
  `HUB_WHATSAPP_AL_ARRANCAR=0` lo apaga).
- Fotos, audios y documentos no se descargan: queda «[imagen]», «[nota de voz
  sin transcribir]»… con su pie si lo tiene.
- Los estados no se leen; los canales, sólo si los pones en «Sólo estas».
- Si desvinculas el aparato desde el teléfono, el colector lo dice y se para.
- `uv run python -m hub.secretario whatsapp comprobar` abre WhatsApp Web hasta
  que pide el QR y se cierra sin vincular nada: sirve para saber si sigue
  funcionando tras una actualización de WhatsApp.

🔴 **La sesión es una llave de tu cuenta entera.** Vive en
`~/.secretos/secretario-whatsapp/` (o en `HUB_SECRETARIO_WHATSAPP`), con
permisos sólo para ti. Para cortar el acceso, desvincula ese aparato en
Dispositivos vinculados del teléfono (aparece como un navegador).

**Teams** todavía no tiene fuente.

## Pendientes, memoria y confianza

- **Pendientes**: arriba, **Te espera** (lo explica el apartado de abajo), que
  incluye lo que espera tu permiso (Aprobar o Rechazar); después, tus
  compromisos abiertos (Hecho o Descartar; descartar pregunta antes, porque
  no se puede deshacer). Al aprobar, el secretario lo hace en unos segundos y
  te lo cuenta en la conversación.
- **Memoria**: las notas que ha sacado. Se corrigen y se borran ahí (borrar
  pregunta antes: una nota borrada no se recupera). Al final, plegadas, tus
  **conversaciones anteriores** con su resumen: en la PC también salen al lado
  de la conversación, y en el teléfono y la tablet sólo aquí.
- **Ajustes → Confianza**: lo que sabe hacer y cuándo te pregunta. Hay tres niveles:
  - **auto**: lo hace sin preguntar;
  - **ask**: te pide permiso en el teléfono;
  - **never**: no lo hace.

  Debajo de cada acción dice si sólo mira, si tiene vuelta atrás, si no la
  tiene o si sale de tu máquina. Lo que no tiene vuelta atrás pregunta siempre. Cuando has aprobado algo varias
  veces, te sugiere pasarlo a auto, pero no lo cambia solo. Abajo está la
  **bitácora**: todo lo que hizo, con qué nivel y por qué.

**En tu PC:** puede abrirte una pantalla del hub en el navegador («ábreme en la
PC la reunión del martes») y la ventana de trabajo de un slot. Lo primero lo
hace el agente de Reuniones, así que tiene que estar conectado y en la versión
0.2.0 o posterior (Reuniones → «Copiar el agente» y reiniciarlo).

**Sabe consultar** tu respaldo (lo que no está subido), tus contenedores de
docker, la salud de la máquina y tus slots.

**Revisa tu PC con Windows y tu red, sólo leyendo.** Cuéntale «me salió
pantalla azul», «se reinició sola», «la PC va lenta» o «tengo lag en el juego»
y lo mira él, sin pedirte permiso porque no cambia nada:

- **Windows** (últimos 14 días): los pantallazos con su código (p. ej.
  `0x00000133 DPC_WATCHDOG_VIOLATION`) y su hora, los apagados que nadie pidió,
  si se pudo guardar el volcado, los volcados que hay (nombre, tamaño y fecha;
  no los abre) y tu BIOS, placa y procesador. Listar `C:\Windows\Minidump`
  pide ser administrador de Windows: si no puede, te lo dice.
- **La red**: tus adaptadores y a qué velocidad van, por dónde sales a
  internet, tu DNS, y la latencia y la pérdida a tu router, a 1.1.1.1, a
  8.8.8.8 y a lo que le pidas. Si le dices el programa («el juego»), mira sus
  conexiones y la latencia a lo que usa; y puede hacer un traceroute.

Tarda menos de un minuto. Lo mismo, desde la terminal:
`uv run python -m hub.diagnostico windows` y
`uv run python -m hub.diagnostico red --proceso <programa> --trazar 1.1.1.1`
(con `--json`, todo el detalle). Sólo funciona con el hub instalado en WSL.

**Lo que no sabe hacer, no lo improvisa:** no tiene terminal ni acceso a tus
archivos. Crear un proyecto o un slot lo hace igual que el botón de la
pantalla: la misma función, con el agente acotado a la carpeta nueva. Cambiar
algo en un proyecto que ya existe se lo encarga al
[orquestador](09-orquestador-e-intercambio.md).

**Sabe qué te espera.** Pregúntale «¿qué tengo pendiente?» o «¿qué me
espera?»: junta lo que sólo se mueve si haces algo —lo que espera tu permiso,
lo que te preguntan el orquestador, tus sesiones o el canal, lo que tus
proyectos dicen que los bloquea (el apartado «Bloqueado por» de su documento
de estado), lo que te preguntan o te avisan tus proyectos (ver «Lo que te
dicen tus proyectos») y tus compromisos que vencen hoy—. Lo lee cada vez de donde vive,
así que lo que resuelves allí desaparece de aquí. Sobre cada cosa puedes decirle
«anótalo en mis pendientes» (queda como compromiso) o, de un bloqueo o un
compromiso, «no me lo vuelvas a sugerir» (no vuelve a salir). Lo que sólo tú
contestas —un permiso, una pregunta— no se calla: se contesta donde dice.
**Nada de esto te llega al teléfono**: espera aquí hasta que lo abres. En la
terminal: `uv run python -m hub.secretario asuntos`, y para volver a ver uno
que callaste, `uv run python -m hub.secretario asuntos reabrir CLAVE` (la
clave sale en la lista con `--todos`).

**Te espera, en la pantalla.** Cuando hay algo que no has visto, encima de la
conversación (en /secretario y en el panel de las demás pantallas) sale un
globo: «Te espera: 2», con lo que aún no has visto. Pulsándolo vas a **Te
espera**, arriba de Pendientes, donde cada cosa dice de qué es (una pregunta
del orquestador, lo que bloquea un proyecto, lo que te dice un proyecto…) y
lleva sus botones:

- un **permiso**: Aprobar o Rechazar, como siempre;
- una **pregunta del orquestador**: la contestas ahí mismo, o confirmas que
  entre en un proyecto; si entretanto te ha hecho otra pregunta, tu respuesta
  no se le aplica a la nueva;
- lo que **bloquea a un proyecto**: **Anótalo** (pasa a tus compromisos), **Te
  lo delego** (se lo encarga al orquestador; el botón ya es tu sí para entrar
  en ese proyecto, no te lo vuelve a pedir) o **No me lo sugieras más**;
- lo que te dice **un proyecto**: lo contestas (o eliges una de sus
  respuestas) y tu respuesta le vuelve al proyecto (ver «Lo que te dicen tus
  proyectos»), lo das por **Hecho** o pulsas **No me lo sugieras más**;
- un **relevo**: lo haces en la PC y lo das por **Hecho** (quien lo pidió no
  lee respuestas, así que no se contesta escribiendo);
- lo que **vence** te lleva a tus compromisos, y una pregunta de una sesión o
  del canal, a su pantalla.

**Lo que no se delega, se prepara.** Si el asunto habla de firmar, contratos,
trámites, pagar o publicar en tu nombre, o si el orquestador aún no tiene
permisos en ese proyecto (Orquestador → Permisos), en vez de «Te lo delego»
sale **Prepáramelo**: se lo encarga igual, pero con la orden de dejarlo listo
sin hacerlo y de preguntarte antes. Un proyecto con guardrail `never` sólo se
anota o se calla: el hub no le encarga nada. Lo que ya anotaste o delegaste no se vuelve
a delegar, ni con el botón ni pidiéndoselo en el chat: las dos cosas siguen la
misma regla, y dos clics seguidos dan una sola tarea. Lo que vence ya es un
compromiso tuyo y no se delega.

Lo que tienes delante deja de contar como nuevo cuando llegas por el globo o
tocas la página; una pantalla que se abre sola sin nadie delante no lo da por
visto, y lo que sigue plegado (las fichas) tampoco hasta que lo abres. Las
fichas no cuentan en el globo. Lo callado se recupera en **Reabrir lo callado**, al final del bloque.

**Lo que sólo tú puedes hacer en la PC te espera en la PC** (el relevo): un
captcha, verificar tu identidad o iniciar sesión con tu cuenta. Queda en tus
asuntos y, si el agente de Reuniones está conectado, te abre esa lista en el
navegador de la PC, una vez por cada cosa (si esa vez no estaba conectado, se
abre la próxima que se pida, mientras no la hayas visto). **Nunca va al teléfono**: desde ahí
no podrías resolverlo. Si no quieres que se abra solo, `relevo_en_pc: false` en
`secretario.yml` (sigue esperando en tus asuntos). Lo pide quien está con el
navegador en tu máquina:
`uv run python -m hub.secretario relevo --origen navegador "Resuelve el captcha del banco"`.
Las preguntas del orquestador con motivo `relevo` hacen lo mismo y no miran ese
ajuste.

**Tus datos para los trámites (Ajustes → Mis datos).** Tu nombre legal, tu
identificador fiscal, tu identificación, tus domicilios (fiscal y de envíos),
tu correo y tu teléfono de contacto y tu régimen fiscal: lo que te pide un
trámite digital en cada proyecto. Se dan **una vez** y sirven para todos.

- Lo que encuentra en tus archivos o le dices en el chat queda **propuesto**:
  no lo usa hasta que lo confirmas tú con el botón **Confirmar** en esa
  pestaña. Un «sí» en el chat no lo confirma. Te lo recuerda en tus asuntos
  («Confirma tu domicilio fiscal en Mis datos»), sin enseñar el valor.
- Lo que escribes tú ahí queda confirmado. **Corregir** lo cambia y
  **Olvidar** lo borra.
- Si ya lo diste para un proyecto, en el siguiente no te lo vuelve a
  preguntar. Si encuentra otro valor, te lo propone al lado del que tienes, y
  sigue usando el tuyo hasta que elijas («Usar el nuevo» o «Dejar el de antes»).
- **Antes de mandar uno a otro sitio te pide permiso**, aunque esa acción
  esté en *auto*: un encargo al orquestador, un lienzo, la nota de un slot, una
  idea del tablero. La
  solicitud dice qué dato lleva. **Nunca lo lleva a una búsqueda en la web**:
  si se lo pides así, te pide preguntarlo sin el dato.
- Lo que te compromete legalmente o con dinero —firmar, pagar, darte de
  alta— lo prepara con tus datos y lo haces tú.

Viven en `HUB_HOME/secretario/mis-datos.yml`, que sólo puede leer tu usuario,
**fuera de su memoria y de sus copias diarias**: «Olvidar» lo quita de la
ficha y de ella no queda copia (por eso tampoco se recupera de ningún
respaldo). Lo que no borra: lo que le dijiste en el chat y lo que ya salió en
algo que aprobaste, que sigue en su historial. En su bitácora lo apunta
tapado. No guardes ahí contraseñas ni llaves: las rechaza.

**Las preguntas del orquestador pasan por él.** Lo operativo lo contesta solo
(lo ves en la bitácora de `/orquestador`); lo tuyo te lo trae. Puedes
contestar en la pantalla del orquestador o **aquí mismo, en el chat**:
pregúntale qué te pregunta el orquestador y contéstale; tu mensaje le llega
al orquestador tal cual lo escribiste, no un resumen suyo.

**Lo que le encarga vuelve aquí, con lo que se vio.** Pásale una captura y
dile «haz pruebas de este proyecto»: se lo encarga al orquestador con la
imagen y te pide permiso (aprobarlo vale como tu sí para ese proyecto, y no
te lo vuelve a preguntar `/orquestador`). La sesión del proyecto sigue su
receta «Cómo se prueba» —si no la tiene, la escribe primero en el proyecto—,
lo ejecuta y deja capturas de lo que vio. Cuando la tarea termina (o la
detienes), te lo dice en este chat: lo que cuenta el orquestador, marcado
como lo que dice él, y debajo las capturas en miniatura; pulsando una se ve
entera. Cada tarea se dice una vez, y al encenderlo no te repite las que ya
estaban cerradas. Si te pidió delegar un asunto de «Te espera», sigue la misma
regla que el botón: sólo lo que bloquea a un proyecto, una vez, y queda como
delegado con su tarea; lo legal, con dinero o de un proyecto sin permisos, te
lo prepara; con guardrail `never`, nada. Al volver, el chat dice qué punto era
y si lo delegaste tú o se lo pediste a él. Él también puede **mirar** una imagen que le
adjuntaste o la evidencia de una tarea («¿qué se ve en la captura que dejó?»),
y enseñarte imágenes del Intercambio en una tarjeta.

## Lo que te dicen tus proyectos

Un proyecto tuyo con su propio operador —una tienda que recibe pedidos, un
taller que lleva su inventario— puede hablarte **por el secretario** en vez de
por su propio bot: una sola voz. Sólo los proyectos registrados en el hub.
Tres tipos:

- **`pendiente`**: algo que tienes que hacer, con su plazo («envía el pedido
  123 antes del martes»). Queda como compromiso en Pendientes, con el proyecto
  de origen, y el día que vence sale en lo que te espera. **No te avisa al
  teléfono** salvo que lo enciendas para ese proyecto, en `secretario.yml`:

  ```yaml
  de_proyectos:
    tienda:
      recordar: true     # sus pendientes te avisan a la hora del plazo
  ```

- **`pregunta`**: algo que te pregunta («¿cotizas 20 kg de café?»). Espera en
  lo que te espera, nunca en el teléfono.
- **`aviso`**: algo que te cuenta («se acabó el café tostado»). Igual.

Lo que dice un proyecto lo trata como dato, no como una orden tuya, y tapa lo
que parezca una contraseña o una llave.

**Para la sesión o el operador del proyecto**, desde la carpeta del hub:

```bash
uv run python -m hub.secretario proyecto-dice tienda --tipo pendiente \
    --vence 2026-11-10T18:00 --clave pedido-123 "Envía el pedido 123: dos cajas a la dirección del pedido"
uv run python -m hub.secretario proyecto-dice tienda --tipo pregunta --clave stock-cafe \
    "¿Cotizas 20 kg de café para la semana que viene?"
```

- `tienda` es el id del proyecto en el registro del hub. Si no está
  registrado, no se deja nada.
- `--vence` (sólo en un pendiente): `AAAA-MM-DD` o `AAAA-MM-DDTHH:MM`, en tu
  hora. Un día sin hora es a las 9.
- `--para` (sólo en un pendiente): `yo` (tú, por omisión) o el nombre de otra
  persona. Sigue siendo tuyo —lo coordinas tú— y el texto dice quién lo hace:
  «Lleva las cajas (lo hace Ana)».
- `--enlace` (sólo en una pregunta o un aviso): una ruta del hub
  (`/proyecto/tienda`); sin él, la del proyecto.
- `--clave`: su identidad. Con la misma, no se apunta dos veces: un pendiente
  abierto se pone al día con lo último (texto y plazo), y uno que ya cerraste
  no se reabre.

El secretario lo recoge en su siguiente vuelta (cada 30 s). **Un proyecto
también puede dejar el archivo él mismo**, sin la orden: un JSON por mensaje en
`~/.local/share/hub/secretario/de-proyectos/<id>/` (o donde esté tu
`HUB_HOME`), con nombre `*.json`, escrito primero como `.tmp` y renombrado:

```json
{"tipo": "pendiente", "texto": "Envía el pedido 123", "vence": "2026-11-10T18:00",
 "para": "yo", "enlace": "", "clave": "pedido-123"}
```

`tipo` y `texto` son obligatorios; lo demás, opcional. Lo que no se entiende
(JSON roto, un tipo que no existe, una fecha que no es fecha, una carpeta de
un proyecto que no está registrado) se aparta a `.rotos/` dentro de esa
carpeta y queda en la bitácora; lo leído se borra. Para volver a mandar algo
apartado —por ejemplo, después de registrar el proyecto—, devuélvelo de
`.rotos/` a su carpeta. Si un pendiente coincide con uno que ya apuntaste tú,
el proyecto no te cambia el plazo ni el aviso.

**Lo que contestas le vuelve al proyecto.** Cuando contestas una pregunta suya
en «Te espera», tu respuesta queda en
`HUB_HOME/secretario/de-proyectos/<id>/respuestas/<clave>.json` (o
`asunto-<n>.json` si la pregunta no traía `--clave`), y el proyecto la lee con:

```bash
uv run python -m hub.secretario proyecto-respuestas tienda           # las lee
uv run python -m hub.secretario proyecto-respuestas tienda --borrar  # las lee y las quita
```

Sale un JSON por línea: `clave`, `asunto`, `pregunta`, `respuesta` y
`cuando`. Contestar otra vez la misma pregunta pisa la respuesta de antes. Si
en tu respuesta va uno de tus datos (Mis datos), le llega tapado («[tu
identificador fiscal]»): si de verdad lo necesita, dáselo tú. Si no se pudo
dejar el archivo, el asunto sigue esperando y la pantalla te dice por qué.

## Avisos en el teléfono

Los avisos —recordatorios, permisos que te pide, lo que manden tus
disparadores— salen **por la app** si la tienes activada, y si no, por el
Telegram del [Canal](/canal).

Para instalarla como app: en [Secretario → Ajustes → Avisos](/secretario?p=avisos),
**Instalar Secretario**. Donde el navegador lo permite (Chrome en Android y en la
PC) abre su diálogo de instalar; donde no, el mismo botón te dice dónde está en el
menú (en iPhone, Compartir → Añadir a pantalla de inicio).

Para activarlos: en el aparato, abre [Secretario → Ajustes → Avisos](/secretario?p=avisos)
y pulsa **Activar avisos aquí**. El navegador pide permiso una vez. «Mandar uno
de prueba» comprueba que llegan.

- **iPhone:** primero añádela a la pantalla de inicio y ábrela desde el icono;
  Safari sólo da avisos a la app instalada (iOS 16.4 o posterior). Tocar un
  permiso abre la app para decidir.
- **Android y PC:** el aviso de un permiso trae **Aprobar** y **Rechazar**. Lo
  que no tiene vuelta atrás llega sin botones: se decide con la app abierta.
- **Fuera de casa**, entrando por el nombre de Tailscale. En la PC funciona
  también en `127.0.0.1`.
- El aviso va cifrado hasta tu aparato: el servicio de avisos del navegador
  (Google o Apple) lo lleva, pero no puede leerlo.

**Aparatos con avisos**, debajo, es la lista de los que los reciben, con su
nombre. Para dejar de recibirlos hay dos formas, y las dos son definitivas:

- **Desactivar aquí**, en el propio aparato: le quita los avisos a su navegador.
- **Quitar**, en la lista, desde cualquier otro: útil si ya no tienes el aparato
  a mano. No vuelve a la lista aunque abra la app; su pantalla de Avisos dice
  «Quitaste este aparato de la lista» y sólo vuelve si pulsas **Activar avisos
  aquí** en él.

Cada vez que abres la app, el aparato se vuelve a apuntar solo si ya tenía los
avisos activados (en iPhone se pierden a veces sin avisar). Si el navegador
cambia la suscripción por su cuenta, el aparato conserva su nombre; sólo si el
hub no la reconoce sale como «renovada» hasta que vuelves a abrir la app.

Si los recordatorios no pueden salir por ningún lado, Pendientes lo dice
arriba y se reintentan solos.

## Recordatorios

Un compromiso con hora de aviso te llega al teléfono (ver arriba). Hay dos
formas de crearlos:

- se lo pides: «recuérdame el lunes a las 10 revisar los PR»;
- lo dijiste tú en un chat con un plazo: «lo mando el viernes».

**Cuándo avisa** de lo que sale de tus chats y reuniones: con la antelación
que pide lo que hay que hacer. Unos minutos antes si es ir a una reunión, una
hora si es contestar algo, varias horas si hay que preparar un entregable. Si
el plazo es sólo un día, esa mañana a las 9. Si la antelación ya pasó cuando lo
lee, avisa en ese momento. Un plazo que ya pasó no avisa, y un compromiso sin
plazo tampoco. Lo que le pides tú («recuérdame a las 10») avisa a esa hora exacta.

El orden de los canales se cambia en `secretario.yml`
(`avisos: [webpush, telegram]` es el de por omisión). El calendario, igual:
`agenda: google`. Cambiar uno no cambia nada más del secretario.

## Calendario

**Sólo para que vea tu agenda** (lo más rápido, dos minutos): en Google Calendar
(web) → ⚙ Configuración → tu calendario → «Integrar el calendario» → **Dirección
secreta en formato iCal**. Cópiala y corre:

```bash
uv run python -m hub.secretario ical-entrar
```

Con eso ya tiene tu agenda, el resumen del día y los avisos antes de cada
evento. La dirección es una llave de tu calendario: si se filtra, en esa misma
pantalla se «restablece». No puede crear eventos.

**Para que también ponga cosas en tu calendario**, conecta Google:

1. En Google Cloud, crea un cliente OAuth de tipo **Escritorio** con la API de
   Google Calendar activada. Descarga su JSON como
   `~/.secretos/secretario-google/cliente.json`.
2. En la carpeta del hub, corre esto. Abre la página de Google para que aceptes:

   ```bash
   uv run python -m hub.secretario google-entrar
   ```

3. En Google Cloud → «Pantalla de consentimiento de OAuth», pulsa **Publicar
   app** («En producción»). En modo «Prueba» el permiso caduca a los 7 días y
   habría que volver a entrar cada semana. No hace falta que Google la
   verifique: al entrar sale un aviso que se pasa con «Avanzado».

«Poner en tu calendario» empieza en **ask**: te pregunta antes de crear cada
evento hasta que tú cambies el nivel. Con los dos conectados manda Google;
`agenda: ical` en `secretario.yml` elige la dirección iCal.

## La tele

Si tienes una tele con **Roku** (las TCL, Hisense o Philips «Roku TV», o un
Roku enchufado), el secretario puede encenderla, apagarla, cambiarla de entrada
y abrir una app: «enciende la tele y pon la PC», «abre YouTube en la tele»,
«¿está encendida?». Habla con ella por la red de casa (ECP, lo mismo que usa la
app de Roku del móvil): las órdenes **salen** de la PC hacia la tele, y el hub
no abre nada a la red.

**En la tele, una vez:**

1. **Ajustes → Sistema → Ajustes avanzados → Control por apps móviles** →
   **Habilitado**. Con «Limitado» la tele rechaza las teclas (el secretario lo
   dice: «rechazó la orden (403)»). «Permisivo» no hace falta y no conviene.
2. **Ajustes → Sistema → Energía → Fast TV Start** → activado. Sin esto, la
   tele apagada desaparece de la red y no se puede encender desde la PC. Gasta
   algo más en reposo.
3. **La IP**, en **Ajustes → Red → Acerca de** (algo como `192.168.1.50`).

**En el router**, reserva esa IP para la tele (suele llamarse «Reserva DHCP»,
«IP fija» o «Asignación estática», y se elige el aparato por su nombre o su
MAC). Si no, el día que el router le dé otra, el secretario dirá que la tele
no contesta.

**En el hub**, añade a `secretario.yml` (en la carpeta `secretario` de tu
`HUB_HOME`):

```yaml
tele:
  ip: 192.168.1.50
  entradas:          # nombres tuyos para las entradas (opcional)
    pc: InputHDMI2
    consola: InputHDMI1
```

Sin `entradas` valen `hdmi1`…`hdmi4`, `antena` y `av`. Sólo se acepta una IP
de tu red de casa. Para probar que llega, desde la PC:
`curl http://192.168.1.50:8060/query/device-info` (con tu IP) tiene que
devolver un XML con `power-mode`. Si el hub corre en WSL y no llega, prueba
desde Windows: en el modo de red NAT de WSL puede no verse la red de casa.

**Niveles:** «Mirar cómo está la tele» va en **auto** (sólo mira). Encender,
apagar, cambiar de entrada y abrir una app empiezan en **ask**: te pide permiso
cada vez hasta que lo subas en Confianza. Cada una comprueba que pasó: si
manda «encender» y la tele sigue en espera, te lo dice en vez de darlo por
hecho. La tele nunca se enciende sola para avisarte de algo.

Lo que no hace: escribir texto en la tele ni mandarle contenido. Para ver el
hub en la tele, pon la PC (o lo que tengas en esa entrada) con la pantalla
abierta y pídele «pon la PC en la tele».

## Tus archivos

El secretario lee los archivos de los proyectos que registraste en el hub —sólo
leer: nunca escribe—. «¿Qué planeé para la migración?», «lee el plan de
actividades del trace de streaming», «¿qué fue lo último que toqué en el
workspace?». Puedes dictarle la ruta tal cual, también la de Windows
(`C:\Users\…`). Fuera de los proyectos registrados no lee nada, y nunca abre
lo que parece una llave: `.env`, `*.pem`, carpetas `secrets/`, `.ssh`…

Para que sepa **dónde** buscar, cuéntale cómo organizas tu trabajo en
`secretario.yml`:

```yaml
contexto: |
  Mi trabajo vive en el proyecto «trabajo». Lo que investigo de cada tema
  está en notas/<tema>/, con un plan.md.
```

## Grabar sola cada llamada

En Ajustes → Disparadores: «Al entrar a una reunión» → «Hacer una acción» →
«Grabar una reunión», y en Confianza pon esa acción en **auto** (si la dejas en
ask, te pide permiso en el teléfono cada vez). Graba con el monitor, la app y
el micro de tu última grabación, empieza tras unos 30 s de llamada —un sonido
suelto de Teams no cuenta— y **para sola** cuando la reunión ya no está en tu
pantalla: con la llamada callada, mira cada 30 s la última captura del monitor
que se graba y sólo para si dos veces seguidas no ve una reunión, así que para
entre 1 y 1,5 minutos después de colgar. Una pausa larga con la reunión en
pantalla no la corta. Te avisa al empezar y al parar. Lo que grabas a mano
no lo para nunca.

## Corregir un compromiso

En **Pendientes**, cada compromiso tiene **Editar**: cambias el texto, cuándo
vence y cuándo te avisa. Si cambias la hora del aviso, vuelve a quedar
pendiente aunque ya te hubiera avisado. **Hecho** y **Descartar** lo cierran;
descartar te pregunta antes, porque no se puede deshacer.

## Disparadores

En **Ajustes → Disparadores** creas «cuando pase X, haz Y» con un formulario:

- **Cuándo salta**: a una hora (con sus días), al entrar a una reunión, unos
  minutos antes de cada evento de tu agenda, o al llegar un mensaje (de una
  fuente, en una conversación, o que diga ciertas palabras).
- **Qué hace**: preguntarle algo con tus palabras y mandarte la respuesta,
  sólo avisarte, o una acción de la lista (con su nivel de confianza).

Arriba ves los que tienes, cada uno en una frase, con **Quitar**. Lo que no cabe
en el formulario se escribe a mano en «Escribirlos a mano (avanzado)», en este
formato:

```yaml
- nombre: me nombran en el grupo del trabajo
  cuando: {fuente: telegram, conversacion: Trabajo, menciona: [mi nombre, urgente]}
  haz: avisar

- nombre: resumen de la mañana
  cuando: {horario: "08:30", dias: L-V}
  haz: resumen_del_dia

- nombre: parte de la mañana
  cuando: {horario: "07:30", dias: L-V}
  haz: resumen_del_dia
  noche: true
  en_chat: true

- nombre: antes de cada reunión
  cuando: {antes_de_evento: 15}

- nombre: entrando a una reunión
  cuando: {estado: en_reunion}
  pide: Estoy entrando a una reunión. ¿Qué tengo pendiente del trabajo?
```

- `haz` usa una acción, con su nivel de confianza.
- `pide` le hace la pregunta al secretario y te manda la respuesta al teléfono.
- `haz: resumen_del_dia` te manda el resumen del día (agenda, lo de hoy, lo
  vencido, lo que espera tu sí y lo anotado desde ayer). Lo arma un script:
  no gasta tu suscripción.
- Con `noche: true` es el **parte de la mañana**: además, lo de las últimas
  24 horas, en este orden: lo que espera de ti (permisos, preguntas del
  orquestador, sesiones que te preguntan algo), tu día, lo que pasó (tareas
  del orquestador, sesiones de Claude, lo que hizo el secretario, lo que
  anotó) y lo que falló (acciones con error, avisos que no salen, fuentes
  que fallan, servicios caídos). Lo que no tiene nada no aparece; si no hay
  nada en ninguna, es una sola línea. Tapa las claves que reconoce (como
  todo lo que guarda el secretario); es una red, no una garantía.
- Con `en_chat: true` el texto entero queda en el chat del secretario y al
  teléfono sólo te llega la primera línea («Te esperan 2 permisos y 3 fichas
  · 1 fallo»): tocándola lo abres. Si no le contestas, esa conversación espera
  abierta hasta 12 horas; si le contestas, ya sabe lo que te dijo. Sin
  `en_chat`, el parte entero va al teléfono por tu canal de avisos.
- `antes_de_evento: 15` te avisa 15 minutos antes de cada evento de tu agenda,
  con los pendientes y lo último que se dijo sobre ese tema.
- «En reunión» es que Reuniones está grabando **o** que Teams o Zoom tienen el
  audio abierto (lo cuenta el agente de Reuniones). Otras apps de llamadas, en
  `secretario.yml`: `apps_de_llamada: [ms-teams.exe, Discord.exe]`.
- Uno de horario no salta si han pasado más de dos horas: con la máquina apagada
  a las 8, el resumen de la mañana no te llega a las 4 de la tarde.

## Si algo no va

- **«El secretario no está en marcha»:** mira el servicio con
  `systemctl --user status hub-secretario` y su registro con
  `journalctl --user -u hub-secretario -n 50`.
- **Contesta «No pude contestar…»:** casi siempre es `claude` sin sesión iniciada
  o sin cuota. Prueba en la terminal: `uv run python -m hub.secretario preguntar hola`.
- **Una fuente dice «no lee»:** la pestaña Fuentes dice qué falta.
- **Ver cómo va todo de un vistazo:** `uv run python -m hub.secretario estado`.
