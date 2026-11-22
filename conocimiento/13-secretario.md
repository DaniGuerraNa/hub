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

### Que te hable él en todas las pantallas

Encendido, en su pantalla, **Ajustes → Personaje → En todas las pantallas →
Ponerlo**: desde entonces la pestaña de abajo a la derecha de las demás
pantallas es él, en el sitio del asistente, y sabe desde qué pantalla le hablas
(y, en Trabajo, qué ventana miras). El asistente queda retirado; **Quitarlo de
abajo** lo devuelve. Sólo se ofrece encendido: apagado, abajo no te contestaría
nadie. Si lo tenías puesto con `en_todo_el_hub: true` en `secretario.yml`, sigue
igual hasta que pulses uno de los dos botones.

Si quieres que te llame por tu nombre, ponlo en
`~/.local/share/hub/secretario/secretario.yml`:

```yaml
dueno: Tu nombre
```

## Hablarle

- **Escribiendo**, en el cuadro de abajo. Enter manda; Mayús+Enter es un salto de
  línea. Si un mensaje no sale (el hub no contesta), te lo dice en rojo debajo
  del cuadro, lo escrito se queda en él y **Reintentar** lo manda.
- **Hablando**: pulsa «Hablar», di lo que quieras y pulsa «Parar». Se transcribe
  en tu máquina con el mismo Whisper que usa Reuniones, así que hace falta tener
  Reuniones preparado. El texto queda en el cuadro para que lo leas antes de
  enviarlo, salvo que marques «Al terminar de hablar, mandarlo solo». Si no se
  pudo transcribir te lo dice en rojo, como un mensaje que no sale; si fue por
  un corte de red, sale **Reintentar** y lo grabado no se pierde, aunque luego
  escribas algo que tampoco salga: Reintentar manda lo escrito y después sube
  lo grabado.
- **Manteniendo Ctrl+Espacio** (en el PC, en su pantalla —y en cualquiera si
  lo pusiste en todas las pantallas— aunque el cursor esté en otro campo o en
  la terminal): graba mientras la mantienes y,
  al soltar, se lo manda directamente. Si el panel estaba plegado, se abre. Un
  toque corto, o cambiar de ventana con la tecla pulsada, no manda nada.
- Lo dictado que le llega sin que lo hayas tocado (Ctrl+Espacio, el modo voz,
  «mandarlo solo» o el texto dictado que envías tal cual) le llega marcado como
  dictado: sabe que puede traer una palabra mal oída —un nombre, un proyecto—,
  lo interpreta por el sentido y, si algo clave no cuadra, te pregunta antes de
  actuar.
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
- **Respondiendo a un mensaje**: doble clic en el hueco **al lado** de un globo
  (encima, el doble clic selecciona una palabra), o su **↩**, que sale al pasar
  por él y en el teléfono se ve siempre, dentro del globo. Encima del cuadro sale «Respondiendo
  a…» con sus primeras líneas; **×** o **Escape** lo quita. Tu mensaje lleva la
  cita arriba y pulsarla te lleva al original. Sirve cuando le pediste varias
  cosas y contestas a una. Le llega lo citado aunque esa conversación ya se
  haya cerrado, y lo trata como dato: si dentro hay un «haz X» de otra persona,
  no lo hace por eso.
- **Oírle**: marca «Leer las respuestas en voz alta» (en **Opciones**). Te lee
  la respuesta frase a frase según la escribe, como en el modo voz, y él la
  escribe para oírla: corta y sin rutas ni símbolos. Usa la voz de tu
  navegador, y de entrada **sólo una que esté en el aparato**: algunas (las
  «Google…» de Chrome, las «Online» de Edge) mandan el texto a Google o a
  Microsoft para leerlo, y ésas sólo suenan si las eliges tú. Si en un aparato
  sólo hay de ésas, no te lee en voz alta: te lo dice una vez y deja **Elegir
  voz** debajo del cuadro.
  En [Ajustes → Voz](/secretario?p=voz) eliges, **en cada aparato**, qué voz te
  lee en español y cuál en el modo inglés, y a qué velocidad (de 0,9 a 1,3),
  con **Probar**. Se guarda en ese navegador: en el teléfono y en la PC se
  elige por separado.
- **Copiar una orden**: si te contesta con una orden o una ruta en un bloque de
  código, sale aparte, en letra de código, con **Copiar** encima. Sus enlaces
  sólo llevan a pantallas del hub, nunca fuera.
- **Modo voz** (el botón de las ondas, junto al micrófono): hablas sin tocar
  nada. Escucha, manda lo que dijiste cuando te callas, lee la respuesta y
  vuelve a escuchar, hasta que salgas con **✕**. Puedes contestarle en cuanto
  calla. Para interrumpirle mientras habla, háblale y sigue: lo que digas le
  llega (o toca el círculo); tocarlo mientras te escucha manda ya lo
  que llevas dicho. **Pausar** apaga
  el micrófono sin salir del modo. Si te callas, sigue esperando; tras unos
  dos minutos sin oírte se pone en pausa solo, y también si sales de la app.
  Si oye un ruido sin palabras (una tos, una puerta) te dice «¿Perdón?» y
  sigue escuchando; si algo falla de verdad, se pausa y te lo dice en voz alta.
  Si lo que dijiste no llega al hub (un corte de red), lo reintenta solo; si
  tampoco, sale **Reintentar** debajo del cuadro y lo grabado no se pierde.
  Si lo que entendió no se puede mandar, se pausa, te lo dice en voz alta y
  **Reintentar** lo manda tal cual.
  Mientras lo pasa a texto el panel lo dice, y mientras piensa enseña lo que
  entendió («Entendí: «…»»): si oyó mal, interrúmpele antes de que actúe.
  Si a los tres segundos aún no ha empezado con lo tuyo (está acabando otra
  cosa), te dice «un momento» y el panel, por qué.
  Mientras dura, la pantalla no se apaga.
  Te lee la respuesta frase a frase según la escribe, así que empieza a
  hablar a los pocos segundos; por voz contesta en tres frases como mucho,
  escritas para oírlas (sin rutas, códigos ni símbolos, las horas como se
  dicen), te ofrece contarte el resto, y si tiene que consultar algo te lo
  dice primero.
- **English** (debajo del cuadro): práctica de inglés. Conversa en inglés
  sobre tu día —puede mirar tus slots y proyectos para hablar de lo que
  haces—, te corrige un error por turno y a veces te pregunta como en una
  entrevista. Si le hablas en español te contesta en inglés (sirve para
  preguntar «¿cómo se dice…?»). Mientras está puesto **no hace nada por su
  cuenta**: cualquier acción, también un recordatorio, sale como permiso que
  apruebas en Pendientes, y no le contesta al orquestador. Lo que hayáis
  hablado no queda como notas. Mientras está puesto lo dice encima del
  cuadro («Practicando inglés · no hace nada sin tu permiso», con **Quitar**)
  y el cuadro pide «Write to him». Se quita con el mismo botón. También puedes
  pedírselo («pon el modo inglés»): lo pone él y el botón se enciende solo; para
  quitarlo de palabra te pide permiso, porque en la práctica no hace nada solo.
  Para hablarle
  en inglés hace falta el Whisper del hub: si declaraste otro transcriptor
  en `encargos.yml`, te dirá que no sabe cambiar de idioma.

Cuando la respuesta tiene varias cosas comparables, te las enseña en una tabla
debajo del texto.

### Investigar algo en la web

Pídele algo **público** —«¿qué dice la norma de facturación?», «¿cuánto cuesta
el plan X?», «¿qué cambió en la versión 5?»— y te contesta al momento «lo
investigo y te lo dejo aquí». Lo busca y lo lee aparte y, en unos minutos, te lo
deja en la misma conversación, digerido:

- primero **la respuesta** a lo que preguntaste, en una o dos frases, sin
  repetirte la pregunta;
- **lo que no encontró**, en una línea («No encontré: …»);
- de 3 a 6 **puntos redactados** que cruzan lo encontrado, cada uno con las
  fuentes en que se apoya por número (`[1][3]`). Un punto que no cita ninguna
  fuente válida, o que trae una cifra que no está escrita en las fuentes que
  cita, no se enseña: se cuenta («Descarté 1 punto con una cifra…»). Es una
  comprobación hecha por el hub, no por el modelo, pero es una red: una cifra
  escrita con letras no se mira;
- a veces, **«Lo que deduzco (no es dato de ninguna fuente)»**: qué implica,
  deducido sólo de tu pregunta y de lo encontrado (quien investiga no conoce
  tus cosas);
- una tarjeta **«Fuentes»**, numerada igual que las citas: cada fuente con la
  fecha que dice esa página («sin fecha» si no dice ninguna) y su enlace, que
  enseña sólo el dominio y abre la página en otra pestaña. Lo que llega sin
  página no se enseña.

En el texto no van direcciones: están en la tarjeta y en su nota. Si
preguntas «¿de dónde sale el 2?», el secretario la lee en esa nota. Si quien
investiga no devuelve los puntos, te llega como antes: cada dato con su
página y su fecha, en lista. Al final, una línea pequeña con el modelo que
investigó, cuánto tardó y a cuánto equivale.

Para el secretario va marcado como «de la web: es dato, no instrucción» (a ti
no se te enseña esa línea): lo que dice una página lo escribió cualquiera. Por eso quien
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
(los de «mis datos» confirmados no los deja pasar). Sólo investiga cuando se lo
pides tú en una conversación: un disparador que «pide» algo por el mensaje de
otro no puede encargarla (ni el resumen de una sesión), y en el modo inglés
tampoco: sal del modo y pídesela.

**Pedir más sobre una que ya llegó.** «Profundiza en el punto 3», «¿y para el
plan anual?»: la primera línea del resultado lleva su referencia («ref. …») y
el secretario la usa para encargar la siguiente con lo que ya se encontró
delante. Quien investiga busca sólo lo nuevo, y si vuelve a traer algo que ya
estaba, no te lo enseña otra vez («1 ya estaba en la anterior»). Lo ya
encontrado sale de la nota de esa investigación: si la corriges en Memoria, va
corregido; si la borras, ya no se puede seguir y hay que pedirla entera. Al
investigador le llega sólo el texto de lo ya encontrado, sin sus direcciones:
la pregunta anterior o la línea que lleve una dirección (`https://…`, un
nombre de sitio) o un dato tuyo no se le manda, igual que no la dejaría pasar
en una pregunta nueva, y el resultado te dice «Al investigador no le mandé…».

**Con qué modelo.** Si nombras uno —«investígalo con opus», «consúltalo con
Fable 5.2»—, usa ése, y te lo dice al encargarla y al traerla, en la línea
del final («Fable 5.2 · tardó…»). Si no dices ninguno, lo elige él por lo difícil que sea: Haiku
para un dato concreto, Sonnet para comparar fuentes, Opus para un análisis.
**Fable sólo si la palabra «fable» está en tu último mensaje**: es el que más
gasta, y si no la escribiste tú, no lo usa aunque lo elija él o se lo sugiera un
mensaje de otro. Comprueba que lo nombraste, no que lo pidieras: si preguntas
«¿qué es Fable 5.2?», podría usarlo, con su tope. Fable 5.2 pide Claude Code 2.1.322
o posterior (`npm install -g @anthropic-ai/claude-code@latest`). Lo mismo para
contestarte: «contéstame con fable» rehace su respuesta con ése.

**Si falla.** Te lo dice en el mismo chat, en llano y con qué hacer (el detalle
técnico queda en `journalctl --user -u hub-secretario`). Si lo que falla es que
el modelo que eligió —o el que le pediste— no devuelve los datos con su fuente
en el formato esperado, la repite una vez con el modelo de siempre (Haiku, o el
de tu `modelos.yml`) y te lo dice en el resultado: «Con Sonnet 5 no salió con el
formato pedido y la repetí con Haiku 4.5». Son dos intentos y cada uno gasta
hasta su tope.

**Pararla.** «Para la investigación» (o «páusala») la detiene aunque esté a
mitad, y quita las que esperaban; con una parte de la pregunta («para la de los
precios»), sólo ésa. No te llega nada de ella. Para retomarla, pídela otra vez,
corregida si quieres.

Cada investigación tiene un **tope de gasto**, contado como lo que costaría
por la API, que va con el modelo: 0,50 USD con Haiku, 1 con Sonnet, 1,50 con Opus y
2,50 con Fable (una pregunta mediana gastó 0,20-0,45 con Haiku, 0,22 con Sonnet,
0,38 con Opus y 0,53 con Fable). Una pregunta sencilla gasta menos; si
una muy amplia no cabe, te dice que no terminó y te pide acotarla. Para
cambiarlo, en `secretario.yml` (un número vale para todos; por modelo, uno a
uno):

```yaml
investigar:
  tope_usd: {haiku: 0.8, fable: 8}
```

Cada resultado acaba diciendo **cuánto tardó y a cuánto equivale** («Tardó 1
min 28 s; equivale a 0,53 USD de la API»): con tu suscripción no se cobra, pero
sirve para ver lo que gasta cada modelo. Si la repitió porque el primer intento
no salió, dice «al menos», porque ese intento no dio su cuenta.

En **Memoria → Investigaciones** están las 20 últimas: qué preguntaste, con qué
modelo, cuándo, cómo acabó (hecha, sin nada con fuente, no cupo en su tope,
falló, cancelada), cuánto tardó y a cuánto equivale, y «Ver su nota» para
volver a lo que encontró. Las de antes de esta versión salen sin modelo ni
gasto: no se apuntaban.

Las investigaciones van de una en una, en la misma cola que los resúmenes de
sesión, y esperan como mucho cinco a la vez. Cada una puede tardar hasta 20
minutos (más que una respuesta del chat: ahí nadie espera delante); si no ha
acabado, se corta y te lo dice. Lo que gastó una que se cortó así, o que
paraste, no se sabe: el proceso se corta sin dar su cuenta. No maneja tu
navegador ni entra con tus cuentas.

**Si el servicio se reinicia a mitad** (una actualización, un corte), la
investigación o el resumen que estaba haciendo no se pierde: al arrancar te lo
dice en el mismo chat («se cortó al reiniciarme; la repito») y la vuelve a
hacer desde el principio, antes que las que esperaban. Repetirla gasta otra
vez, así que lo hace como mucho dos veces: si se corta una tercera, te lo dice
y ya no la repite. La que tú paraste no vuelve, y tampoco una que se quedó a
medias hace más de un día: ésa se retira sin más.

### El personaje: qué está haciendo

El secretario tiene cara: un cuadrado pequeño en el color del hub, con ojos.
Está en la cabecera de su pantalla y, si lo pusiste en todas las pantallas, en
la pestaña de abajo a la derecha, y enseña lo que **de verdad** está haciendo,
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
  Si elegiste un personaje dibujado, cada uno es ese mismo personaje en
  pequeño, con una insignia de lo que hace en vez de ropa: la lupa si
  investiga, la carpeta si busca en el código, el ✓ si revisa…

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

**Te dice en qué está cualquier sesión.** «¿Cómo va lo de la tienda?» o «¿en
qué está la sesión de Trabajo?»: lee el registro de la conversación de Claude
Code de ese slot (no la pantalla) y te cuenta su último mensaje y lo último que
hizo (qué archivos tocó, qué comandos lanzó), con las llaves tapadas. Sólo
lo tiene en tu chat (nunca cuando contesta a otra cosa por su cuenta) y está
hecho para cuando le preguntas por una sesión; de Codex todavía no sabe leerlo.

**Puedes ponerle nombre.** En **Ajustes → Personaje**, arriba del todo,
«Cómo se llama»: el que escribas sale en el menú, en su pantalla y en la app
instalada, y él sabe que es el suyo desde la siguiente conversación. Vacío
vuelve a «Secretario». (En el teléfono, una app ya instalada puede quedarse con
el nombre viejo bajo el icono hasta que la reinstales.)

**Puedes elegir quién es.** En **Ajustes → Personaje**, arriba, están el
cubo de siempre y varios dibujados (ranitas, hongos, los dos juntos y
pingüinos): pulsa
«Usar este» y lo verás en la cabecera, en la pestaña de abajo si lo pusiste en
todas las pantallas y en todos tus aparatos.
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
conversación tiene al lado lo que espera tu permiso, lo **vencido o de hoy**
(aparte, con **Hecho** y **Mover** para cambiarle la fecha) y lo próximo. Con
la conversación vacía, las ideas para empezar salen de lo que te espera (un
permiso, algo nuevo, lo que le encargaste al orquestador) y, si no hay nada,
las de siempre.

Tiene cuatro secciones: **Conversación**, **Pendientes**, **Memoria** y
**Ajustes** (dentro: Avisos, Fuentes, Confianza, Disparadores, Personaje, Voz y Mis datos).

### Por qué no se llena nunca

Cada conversación es un **hilo**. Lo que sabe no vive en la conversación, sino en
su memoria, y la consulta cuando hace falta. Tras media hora sin hablar, el hilo
se cierra solo: se guarda un resumen y las notas que salieron, y la siguiente
conversación empieza limpia. No hay que compactar ni limpiar nada a mano.
«Conversación nueva» lo cierra en el momento.

Lo ya hablado **se sigue viendo**: al abrir el chat, encima de la conversación
de ahora salen las anteriores, cada una con su separador («Conversación del…,
resumida»), y **Ver lo anterior**, arriba del todo, trae más mientras quede algo
atrás. Se pueden releer y responder a un globo de entonces (↩), pero el
secretario no las tiene delante: el separador de la de ahora lo dice («lo de
arriba lo recuerda sólo por su resumen»). Si citas algo de entonces, le llega
lo citado. Una imagen adjunta de hace más de diez días ya no está: deja su
nombre.

### Qué modelo contesta

Depende del trabajo:

| Trabajo | Modelo |
|---|---|
| Leer lo que llega y sacar notas y compromisos | Haiku |
| Hablar contigo | Sonnet |
| Planificar algo de varios pasos o decidir con consecuencias | Opus (lo pide el propio Sonnet) |
| Investigar algo en la web (`investigar`) | Haiku, o el que elija según lo difícil que sea |

Si le nombras un modelo («con opus», «con fable»), manda el tuyo, para esa
investigación o esa respuesta. Fable no lo usa nunca si no lo nombras tú.
Bajo cada respuesta ves qué modelo la dio y cuánto tardó. Para cambiar la tabla:
`~/.local/share/hub/secretario/modelos.yml`, por ejemplo con `conversacion: haiku`
(ahí no entra Fable: sólo cuando lo pides).

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

Lo de un grupo que no va para ti no se lee mensaje a mensaje: espera a que se
junten diez o a que el más viejo lleve cinco minutos, y entonces se lee todo de
una vez (gasta menos de tu suscripción). Por eso un aviso «📣 En el grupo» puede
tardar hasta unos cinco minutos. Un chat contigo, una etiqueta o tu nombre no
esperan, y tus disparadores tampoco.

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

- **Aprobar sin salir del chat**: cuando el secretario te pide permiso, sale una
  tarjeta **Pide tu permiso** justo encima del cuadro de escribir, en su
  pantalla y en el panel de las demás. Dice qué quiere hacer, por qué y, entero,
  el texto exacto o la orden que va a usar, y cuándo lo pidió: léelo antes de
  decidir. Tiene tres botones: **Aprobar**, **Rechazar** y **Rechazar y decir
  por qué**, que abre un campo en la misma tarjeta: escribes qué estaba mal y
  pulsas **Rechazar** (o **Cancelar**). Él dice «No lo hago: rechazaste…» con el
  nombre de la acción y lo que pedía, y tu motivo le llega como un mensaje tuyo
  que responde a eso, así que te contesta (lo vuelve a proponer bien o te
  pregunta). El motivo no se guarda en la solicitud: vive en la conversación.
  Si se cae la red, lo escrito sigue en la tarjeta; si otro aparato ya la había
  decidido, también, hasta que pulses **Quitar**.
  Si hay varias, salen todas, la más antigua arriba; las que nacieron sin ti
  delante lo dicen al principio. Lo mismo sigue en Pendientes, donde
  **Rechazar diciendo por qué** se despliega bajo cada una: decidir en un
  sitio la quita del otro.
- **Pendientes**: arriba, **Te espera** (lo explica el apartado de abajo), que
  incluye lo que espera tu permiso (Aprobar o Rechazar); después, tus
  compromisos abiertos (Hecho o Descartar; descartar pregunta antes, porque
  no se puede deshacer). Lo que ya venció o vence hoy va arriba de ellos, en
  **Vencidos o de hoy**: marcas los que quieras y los das por **Hecho** o los
  **Descartas** de una vez (los botones salen al marcar uno), y cada uno se puede **Mover** a otra fecha. Nada
  se cierra solo; el parte de la mañana te dice cuántos hay y dónde están. Al
  aprobar, el secretario lo hace en unos segundos y te lo cuenta en la
  conversación. Lo hace una sola vez: si el secretario se
  reinicia justo a mitad, no la repite; te dice en el chat que no sabe si llegó
  a hacerse, para que lo mires tú y se la vuelvas a pedir si hace falta, y en
  «Solicitudes resueltas» queda como «no sé si se hizo».
- **Memoria**: las notas que ha sacado. Cada una se lee tal cual; **Editar**
  abre su texto para corregirlo y **Borrar** está en su menú (⋯), en rojo, y
  pregunta antes: una nota borrada no se recupera. También se lo puedes decir
  en la conversación: «eso que anotaste está mal, es el jueves» corrige la nota
  al momento, y lo que decía antes (y su tema) queda en la bitácora; si era muy
  larga o llevaba algo con forma de contraseña, ahí queda recortado o tapado, y
  te lo dice. «Cámbialo a "llamar al taller"» cambia el texto de un compromiso
  abierto sin moverle el plazo ni el aviso. Y «olvida esa nota» te pide permiso
  siempre, enseñándote la nota entera, porque borrar es cosa tuya. Al olvidarla
  se borra la nota y, a la vez, se tapa con «[olvidado]» lo que la bitácora y
  las solicitudes guardaban de ella: el texto con que se anotó, cada
  corrección y su «antes decía», y el motivo que se apuntó entonces. La
  bitácora sigue diciendo que se anotó, se corrigió y se olvidó, y cuándo; no
  qué decía. El aviso y la solicitud de olvidarla tampoco llevan su texto.
  **Lo que sí sigue**, y conviene saberlo: lo que hablasteis de ella en la
  conversación (también lo que él te contestó citándola) y los resúmenes de
  esas conversaciones; el mensaje del que salió, si salió de uno, que sigue
  entre lo leído; y las copias diarias de su memoria hechas antes (se guardan
  las catorce últimas). **Borrar** desde esta pantalla quita la nota, pero no
  tapa la bitácora: para eso, pídeselo a él. Se ven las 80 más
  recientes: escribir en «Filtrar notas» filtra ésas al momento, y con Intro
  busca en todas (sin distinguir mayúsculas ni tildes). El botón **Filtrar**,
  al lado, acota también sobre todas, y se suma a lo que hayas buscado:
  - **Tema**: las notas que saca él solo (de lo que lee y al cerrar una
    conversación) llevan uno de una lista corta —persona, proyecto,
    preferencia, decisión, dato, investigación, inglés— o ninguno, y el
    detalle va en el texto. Las que apuntas tú, o le dictas, llevan el tema que
    digas. Las notas de antes conservan el suyo: para encontrarlas, busca la
    palabra, que la búsqueda también mira el tema.
  - **Sin salir en ninguna búsqueda desde el …**: las que no le han salido
    cuando busca en su memoria o le preguntas por alguien. Cuenta desde su
    primera búsqueda con esta versión, y la fecha lo dice; de antes no se sabe.
    Que tú abras Memoria no cuenta. No borra nada: sirve para decidir qué
    olvidar, y olvidar sigue siendo cosa tuya.

  Lo puesto se ve encima de las notas, y cada uno se quita con su ×.
  Cuando cierra una conversación también apunta lo que **prefieres** si lo
  dejas caer («prefiere…», «no le gusta…»), con tema «preferencia»: sólo lo
  que dijiste tú. Al final, plegadas, tus
  **conversaciones anteriores** con su resumen: en la PC también salen al lado
  de la conversación, y en el teléfono y la tablet sólo aquí.
- **Ajustes → Confianza**: lo que sabe hacer y cuándo te pregunta. Hay tres niveles:
  - **Lo hace solo** (*auto*): sin preguntar;
  - **Te pregunta** (*ask*): te pide permiso en el teléfono;
  - **Nunca** (*never*): no lo hace.

  En pantalla salen con su nombre; entre paréntesis, el valor que se guarda
  y que verás en los archivos de configuración (el guardrail de un proyecto
  usa los mismos tres).

  Debajo de cada acción dice si sólo mira, si tiene vuelta atrás, si no la
  tiene o si sale de tu máquina. Lo que no tiene vuelta atrás pregunta siempre, y también lo que
  dice **Pregunta siempre**: cosas que tienen vuelta atrás pero son tuyas de decidir cada vez
  (archivar un slot, parar un contenedor, detener una tarea). En ésas, «Lo hace solo» no se puede elegir. Cuando has aprobado algo cinco
  veces seguidas sin que fallara (un «no» o un fallo vuelven a empezar la cuenta), te sugiere pasarlo a «Lo hace solo»,
  pero no lo cambia solo. Lo que sabe hacer pero aún no está configurado
  sale marcado **sin configurar**, con dónde se configura: mientras tanto el
  secretario ni lo intenta (no se le ofrece), y en cuanto lo configuras lo
  tiene en la siguiente conversación. Su nivel se puede elegir igual. Abajo está la
  **bitácora**: todo lo que hizo, con qué nivel y por qué.
  Encima de la bitácora, **Lo que le pediste y no supo**: lo que él mismo apunta
  cuando no tiene con qué hacer algo, agrupado y con cuántas veces. Si contestó
  que no podía y no apuntó qué le faltaba, sale contado aparte («Dijo que no
  podía, sin apuntar qué le faltaba»): es una señal, no una lista exacta —un
  «no puedo eso, pero sí esto» también cuenta—, y lo que dijo está en esa
  conversación.
  Cuando te dice que no sabe hacer algo, te pregunta si lo apunta como mejora
  en el tablero, y sólo lo apunta si le dices que sí; al lado del hueco, aquí,
  ves en qué va. Si usas fichas de cambios (`parte_fichas`) y la ficha que lo
  resolvió está hecha y dice qué herramienta suya lo resuelve (`resuelve:`),
  te lo dice **una vez, en el chat** («Ya sé hacer algo que me pediste y no
  sabía…»), y sólo cuando esa herramienta ya está cargada en el secretario que
  tienes en marcha. No te llega al teléfono.

**En tu PC:** puede abrirte una pantalla del hub en el navegador («ábreme en la
PC la reunión del martes») y la ventana de trabajo de un slot. Lo primero lo
hace el agente de Reuniones, así que tiene que estar conectado y en la versión
0.2.0 o posterior (Reuniones → «Copiar el agente» y reiniciarlo).

**Sabe consultar** tu respaldo (lo que no está subido), tus contenedores de
docker, la salud de la máquina y tus slots.

**Revisa tu PC con Windows, tu red y tus programas, sólo leyendo.** Cuéntale
«me salió pantalla azul», «se reinició sola», «la PC va lenta», «tengo lag en
el juego» o pregúntale qué versión tienes de algo, y lo mira él, sin pedirte
permiso porque no cambia nada:

- **Windows** (últimos 14 días): los pantallazos con su código (p. ej.
  `0x00000133 DPC_WATCHDOG_VIOLATION`) y su hora, los apagados que nadie pidió,
  si se pudo guardar el volcado, los volcados que hay (nombre, tamaño y fecha;
  no los abre) y tu BIOS, placa y procesador. Listar `C:\Windows\Minidump`
  pide ser administrador de Windows: si no puede, te lo dice.
- **La red**: tus adaptadores y a qué velocidad van, por dónde sales a
  internet, tu DNS, y la latencia y la pérdida a tu router, a 1.1.1.1, a
  8.8.8.8 y a lo que le pidas. Si le dices el programa («el juego»), mira sus
  conexiones y la latencia a lo que usa; y puede hacer un traceroute.
- **Tus programas**: tu Windows y su versión, cada tarjeta gráfica con la
  versión de su controlador, y los programas instalados que le nombres («¿qué
  versión de Chrome tengo?», «¿qué tengo de AMD?»), con su versión y cuándo
  se instalaron. La versión del programa de la gráfica (Adrenalin, por
  ejemplo, sale como «AMD Software») no es la del controlador, y te las da
  separadas. Y lo que escriben los procesos, medido unos segundos: los que
  más escriben ahora o, si le dices uno («¿ese proceso está escribiendo sin
  parar?»), lo que lleva escrito desde que arrancó y lo de ahora. Es toda la
  entrada y salida del proceso, no sólo el disco: un techo.

Tarda menos de un minuto. Lo mismo, desde la terminal:
`uv run python -m hub.diagnostico windows`,
`uv run python -m hub.diagnostico red --proceso <programa> --trazar 1.1.1.1` y
`uv run python -m hub.diagnostico programas --buscar <nombre> --proceso <proceso>`
(con `--json`, todo el detalle). Sólo funciona con el hub instalado en WSL.

**Mira lo demás de tu PC con una orden de PowerShell.** Lo que no cubre lo de
arriba —«¿qué modelo son mis monitores?», «¿qué tengo conectado por USB?», «¿mi
disco está sano?»— lo mira él con una orden de PowerShell, **sin preguntarte,
sólo si la orden únicamente mira**: aparatos, controladores, discos, red,
servicios, procesos, eventos y el registro. No se fía de lo que él diga de su
orden: la comprueba el propio PowerShell antes de correrla, y la corre en un
PowerShell recortado que sólo tiene esos comandos. No lee el contenido de tus
archivos (eso va por la carpeta que le diste), ni el portapapeles, ni
contraseñas, ni variables de entorno, ni la línea de órdenes de tus procesos.
Lo que sí mira (el registro, los eventos de Windows) puede llevar algo
privado: lo que parece una llave se tapa antes de pasárselo, pero es un
filtro, no una garantía.

**Si hace falta cambiar algo, te lo pide con la orden exacta.** En Pendientes
ves la orden entera, tal cual se va a correr, y por qué no es sólo mirar.
**Nada cambia sin tu sí**: ésa es la garantía. Si pasan más de 15 minutos
desde que te lo pidió, aunque la apruebes no la corre (la PC ya puede estar
distinta). Desde la notificación no se aprueba: hay que verla. Además, se
niega a pedirte lo que toque las carpetas de tus proyectos (o una que las
contenga), abra puertos, el cortafuegos o tailscale, accione docker, salte a
WSL (donde están el hub y sus bases), pida administrador o vaya codificado. Si
no puede leer tu registro de proyectos (o una carpeta de las que declara),
no sabe cuáles proteger y no te pide cambiar nada hasta que se pueda; mirar
sí sigue. Es una red para lo evidente, no una garantía: una orden puede llegar a una
carpeta sin nombrarla, y por eso lo que importa es que la leas antes de
aprobarla. Mirar y cambiar, sólo cuando le hablas tú: nunca desde un
disparador. Si algo que está leyendo (un mensaje, un correo) le pidiera correr
algo, para cambiar seguiría necesitando tu sí. Sólo en Windows, con el hub
instalado en WSL.
Desde la terminal, para ver qué haría con una orden:
`uv run python -m hub.orden_pc clasificar "<orden>"`.

**Lo que no sabe hacer, no lo improvisa:** no tiene una terminal de Linux ni
acceso a tus archivos fuera de lo que le diste. Crear un proyecto o un slot lo hace igual que el botón de la
pantalla: la misma función, con el agente acotado a la carpeta nueva. Cambiar
algo en un proyecto que ya existe se lo encarga al
[orquestador](09-orquestador-e-intercambio.md).

**Sabe del hub.** Pregúntale cuántas ideas esperan en el tablero, qué fichas
de cambios hay abiertas (si las usas: `parte_fichas` en `secretario.yml`; si
no, te dice que no hay), cuánto llevas gastado en Claude Code (siempre con las
fechas que cubre: el registro se poda a los 30 días), qué versión del hub
tienes y si hay otra, o dónde está algo («¿dónde veo el respaldo?»): te da la
pantalla y, con el agente de Windows conectado, te la abre en la PC.

**Hace por ti cosas del hub que antes eran sólo botones**, siempre que se
lo pidas tú en la conversación (nunca desde un disparador):

- **Descartar una idea del tablero** («descarta la idea 12, ya lo hace la
  interfaz nueva»): con su número y la razón, que queda escrita en el tablero.
  No tiene vuelta atrás.
- **Archivar o desarchivar un slot** («archiva el slot del login»). Borrar un
  slot no lo hace: eso es sólo tu botón. Y no te lo propone él porque lleve
  tiempo sin tocarse.
- **Detener o reanudar una tarea del orquestador** («para esa tarea»,
  «reanúdala»). Detener interrumpe a las sesiones que trabajan para ella, como
  el botón. Al reanudar no le añade ninguna nota: si quieres decirle algo al
  orquestador, lo escribes tú en su pantalla.
- **Arrancar, parar o reiniciar un contenedor** («para el contenedor
  tienda-db»): uno cada vez y por su nombre exacto, de los que salen en
  Servicios. No borra contenedores ni toca los de un proyecto con guardrail
  never. Después mira cómo quedó y te lo dice.

Todas **preguntan siempre**: no se pueden poner en auto, y su aviso al
teléfono no trae Aprobar y Rechazar. Se deciden viendo el detalle —qué slot y
de qué proyecto, de quién es el contenedor, qué pedía la tarea, y cómo está
cada cosa en ese momento—, y eso sólo sale en la tarjeta **Pide tu permiso**
del chat y en Pendientes: el aviso lleva el número o el nombre de lo que es,
nunca el pedido de la tarea ni el nombre del proyecto.

**Sabe de cada persona.** «¿Cuándo hablé con Ana?» o «¿qué le debo a Ana?»:
junta en qué chats escribe, su último mensaje, el tuyo en su chat privado, los
compromisos abiertos con ella o para ella y las notas que la nombran. Busca el
nombre como palabra entera («Ana» no es «Anabel») y tal como sale en sus
mensajes: si en un chat la tienes guardada con otro nombre, pregúntale por ése.

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
globo: «Te espera: 2 nuevas», con lo que aún no has visto. Pulsándolo vas a **Te
espera**, arriba de Pendientes: su cabecera dice cuántas cosas hay y cuántas
son nuevas (las mismas del globo), y cada una nueva lleva la marca «nuevo». Ahí cada cosa dice de qué es (una pregunta
del orquestador, lo que bloquea un proyecto, lo que te dice un proyecto…) y
lleva sus botones. Arriba y abierto, lo que sólo contestas tú; debajo, los
bloqueos de cada proyecto en una línea plegada («La tienda · 2 bloqueos») y
lo que vence en otra («3 compromisos vencidos o de hoy»). Un grupo con algo
nuevo llega abierto. En cada fila, la acción que se te propone va destacada y
las demás, en su menú (⋯):

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
- lo que **el navegante tiene en pausa** (una petición del navegador que
  modifica algo y espera tu permiso): sale con la acción y el sitio, sin la
  dirección entera, y **Ver y contestar** te lleva a Navegante, donde se ve
  todo y se da el permiso; aquí no se aprueba ni se calla, y si el guardián
  no está en marcha la fila lo dice;
- lo que **vence** te lleva a tus compromisos (un solo enlace para todo el
  grupo), y una pregunta de una sesión o del canal, a su pantalla.

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
visto, y lo que sigue plegado (las fichas, un grupo cerrado) tampoco hasta que lo abres. Las
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
- **Confirmar** y **Usar el nuevo** confirman el valor que tenías delante. Si
  mientras mirabas la pestaña llegó otro, no confirman nada y te dicen «cambió
  mientras lo mirabas»: revisa el que hay ahora y vuelve a pulsar.
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
tapado, también el que te propone y no llega a guardarse, y también si lo
escribe en el motivo. No guardes ahí contraseñas ni llaves: las rechaza.

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
  El de un recordatorio trae **Hecho** (lo cierra, como su botón en
  Pendientes) y **En 1 h** (te lo vuelve a recordar dentro de una hora; la
  hora se cambia en Pendientes con Editar). Sin conexión con el hub, el botón
  abre la app.
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

Lo que **te pide otro** en un chat o una reunión con plazo («para el viernes
necesito la propuesta») queda en Pendientes con ese plazo, pero no te suena en
el teléfono. Si quieres que te lo recuerde, pídeselo: «recuérdame lo de Ana el
jueves a las 10». Lo que le apuntas tú en su chat con un plazo («apunta que
Ana me pidió la propuesta para el viernes») sí avisa: cuenta como pedírselo.
Lo que te piden **sin plazo** («¿me pasas el link?») no llega a Pendientes:
queda como nota en Memoria («Luis le pidió: …»).

**Cuándo avisa** de lo que sale de tus chats y reuniones: con la antelación
que pide lo que hay que hacer. Unos minutos antes si es ir a una reunión, una
hora si es contestar algo, varias horas si hay que preparar un entregable. Si
el plazo es sólo un día, esa mañana a las 9. Si la antelación ya pasó cuando lo
lee, avisa en ese momento. Un plazo que ya pasó no avisa, y un compromiso sin
plazo tampoco. Lo que le pides tú («recuérdame a las 10») avisa a esa hora exacta.
Si le das un plazo sin decir cuándo avisarte («apunta que lo mando el viernes a
las 12»), media hora antes; si es sólo un día, esa mañana a las 9. Y si le
mueves el plazo, el aviso se mueve con él, con la misma antelación.

**Aún no repite recordatorios.** Si le pides uno «cada lunes», te dice que no
sabe repetirlo y apunta sólo el primero.

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

Sin ninguna de las dos, el secretario no cuenta con tu agenda: ni la nombra ni
intenta leerla. Desde la siguiente conversación después de conectarla, sí.

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
evento hasta que tú cambies el nivel. Sin Google conectado (con sólo la
dirección iCal, o sin calendario) ni lo intenta: en Confianza sale **sin
configurar**. Con los dos conectados manda Google;
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

Mientras falte la IP, el secretario no cuenta con la tele: ni lo intenta, y en
Confianza sus cinco acciones salen **sin configurar**. En la siguiente
conversación después de ponerla, ya las tiene.

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
- `pide` le hace la pregunta al secretario. La respuesta queda entera en su
  chat, con el nombre del disparador delante, y al teléfono te llega su primera
  línea (tocándola lo abres); si le contestas («¿y lo segundo?»), sabe lo que
  te dijo. En el chat va debajo de una línea que dice que salió de un
  disparador y que es dato, como una investigación: si cita algo de otra
  persona («ignora lo anterior…»), no lo toma como una orden tuya. Con
  `en_chat: false`, sólo al teléfono y entera. Contesta corto
  (lo esencial en la primera línea), sin preguntarte nada, y sabe cuándo salta:
  «ayer» es el día de antes del disparo.
  Como ahí no estás tú delante, lo único que hace solo es avisarte: cualquier otra
  cosa que quiera hacer (anotar, callar un asunto, apuntar un pendiente…) te pide
  permiso aunque esté en auto, la solicitud dice «Nació en un disparador, sin ti
  delante» y se aprueba abriendo la app, no desde la notificación. Lo que pones
  en `haz` no cambia: eso lo escribiste tú.
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

- **«El secretario no está en marcha»:** lo dice su pantalla arriba y, si le
  escribes con él parado, también el chat de cualquier pantalla («lo contestará
  al volver»: lo que le dijiste no se pierde, espera a que arranque; en el modo
  voz, se pausa y te lo dice). **Ver qué le pasa** lleva a su pantalla, que
  dice por qué y, si encenderlo lo arregla, ofrece **Encenderlo**. A mano: mira
  el servicio con `systemctl --user status hub-secretario` y su registro con
  `journalctl --user -u hub-secretario -n 50`.
- **Contesta «No pude contestar…»:** te dice qué pasó y qué hacer: que Claude
  Code no arranca, que tardaba demasiado y lo cortó, que Claude contestó con un
  error, que su memoria estaba ocupada… Casi siempre es `claude` sin sesión
  iniciada o sin cuota: abre `claude` en una terminal y lo verás, o prueba
  `uv run python -m hub.secretario preguntar hola`. El detalle técnico de cada
  fallo está en `journalctl --user -u hub-secretario`.
- **Claude no está disponible un rato** (se acabó el uso, no hay sesión
  iniciada, no hay conexión): lo que va leyendo de tus fuentes **no se pierde
  ni se aparta**. Espera sin clasificar y el secretario lo reintenta solo, cada
  vez más espaciado (de medio minuto a un cuarto de hora); cuando Claude
  vuelve, saca los pendientes y avisos de todo lo que entró mientras. Las
  conversaciones quietas tampoco se cierran sin resumen. Queda una línea en
  su bitácora («El modelo no está disponible…»), otra cuando vuelve («El
  modelo vuelve a contestar…»), y el parte de la mañana lo dice en «Falló»:
  si ya volvió, dice que ya volvió. Sólo se aparta un grupo de mensajes —siguen pudiéndose
  buscar, pero no dan pendientes— cuando falla tres veces **y** Claude sí
  contesta a una pregunta de prueba: entonces el problema son esos mensajes.
  Esa pregunta de prueba es una llamada mínima al modelo.
- **Una fuente dice «no lee»:** la pestaña Fuentes dice qué falta.
- **Ver cómo va todo de un vistazo:** `uv run python -m hub.secretario estado`.
