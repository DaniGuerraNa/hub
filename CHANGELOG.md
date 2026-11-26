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

## Sin publicar

## 0.16.0 — 2026-11-26

El Puente KVM escribe en la misma ventana en la que leyó, sin mover la región
del editor en cada trabajo, y tiene un apartado de permisos para elegir qué
hace Claude sin preguntarte.

### Qué tienes que hacer

- Actualiza. Si usas el Puente KVM, en su pantalla, «Reabrir la conversación
  de Claude» para que lea sus instrucciones nuevas.

### Nuevo

- **Puente KVM: «Permisos de Claude», en Ajustes.** Eliges qué casillas salen
  ya marcadas al dar el control (hoy, las correcciones pequeñas sin
  aprobación). En el diálogo se ven siempre y las puedes quitar para ese
  encargo, y **«Trabajo delicado: pregúntame todo»** las desmarca todas.
  Ejecutar nada en el Mac, guardar o escribir un documento nuevo sin tu
  aprobación no entran nunca.

### Qué cambia en lo que ya usabas

- **Puente KVM: el cambio se escribe en la zona que se leyó.** Antes, una
  lectura hecha en otra ventana no se podía escribir y había que mover la
  región del editor en Ajustes. Ahora cada lectura recuerda su zona, y la
  pantalla la recuadra mientras trabaja. Lo escrito fuera de la región de
  Ajustes siempre espera tu aprobación: los atajos son los del programa que
  calibraste.

## 0.15.0 — 2026-11-25

El Puente KVM puede escribir correcciones pequeñas sin una aprobación por
cada una, y guarda mediciones de uso (sin nada de lo que escribes ni lees)
que puedes mandar a quien te ayuda con él.

### Qué tienes que hacer

- Actualiza. Si usas el Puente KVM, en su pantalla, «Reabrir la conversación
  de Claude» para que lea sus instrucciones nuevas.

### Nuevo

- **Puente KVM: correcciones pequeñas sin pedirte aprobación.** Al pulsar «Dar
  el control a Claude», el diálogo trae una casilla (desmarcada siempre):
  durante ese encargo, lo que quepa en **20 líneas y 1 500 caracteres en
  total** se escribe sin tu clic. Un documento nuevo, o un cambio que quite
  más de la mitad del documento, sigue esperando tu aprobación. La pantalla dice cuánto lleva, cada cambio así
  lleva la placa «aprobado por tu permiso», y al volver el control te dice
  cuántas correcciones escribió sin pedirte. Guardar sigue siendo tuyo.
- **Puente KVM: «Mediciones de uso», en Ajustes.** Guarda cuánto tarda cada
  cosa, cuántas veces pasa y si salió bien o mal: nunca lo que escribes, lo que
  se lee, nombres de documentos ni la pantalla. Se queda en tu máquina (30
  días). «Preparar para enviar» te da un .zip que puedes abrir y mirar antes de
  mandarlo por donde quieras; «Borrar mediciones» lo vacía.

### Qué cambia en lo que ya usabas

- **Puente KVM: una escritura larga ya no se corta a los 30 minutos.** Claude
  Code corta cualquier herramienta que pase 30 minutos sin contestar, y
  escribir un documento de casi 2 000 líneas tarda más. Ahora la herramienta
  contesta «sigue en marcha» a los 10 minutos, el puente acaba la escritura
  solo y el control vuelve a ti al terminar. Si se te cortó una, el documento
  quedó a medias y sin guardar: vuelve al archivo guardado y pide repetirla.
- **Puente KVM: las mediciones vienen encendidas.** Si no las quieres, apágalas
  en Ajustes → «Mediciones de uso»; nada sale de tu máquina sin que tú lo
  mandes.

## 0.14.1 — 2026-11-25

### Qué tienes que hacer

- Actualiza. Si usas el Puente KVM, en su pantalla, «Reabrir la conversación
  de Claude».

### Qué cambia en lo que ya usabas

- **Puente KVM: terminar el turno ya no corta una escritura en marcha.** Con
  la 0.14.0, si Claude lanzaba una escritura larga, te avisaba del progreso y
  terminaba su turno, el puente le quitaba el control y el tecleo se cortaba a
  mitad del documento. Ahora el control vuelve a ti **cuando acaba la
  escritura** (o la lectura). Parar, «Retomar el Mac» y «Usar el Mac desde
  aquí» la siguen cortando en el acto. Si se te cortó una, el documento quedó
  a medias y sin guardar: vuelve al archivo guardado (Archivo → Revertir) y
  pídele a Claude que la repita.

## 0.14.0 — 2026-11-25

El Puente KVM deja que Claude termine un encargo entero sin perder el control,
espera a que el vídeo del JetKVM se ponga al día antes de leer, y «Usar el Mac
desde aquí» le quita el control a Claude.

### Qué tienes que hacer

- Actualiza. Si usas el Puente KVM, en su pantalla, «Reabrir la conversación
  de Claude» para que lea sus instrucciones nuevas.

### Nuevo

- **Puente KVM, Ajustes → «Retraso del vídeo (ms)»**, junto a «Pausa entre
  teclas» (3000 de fábrica). El vídeo del JetKVM llega 1-2 s tarde; tras cada
  tecla, el puente espera hasta ese tiempo a **ver** el cambio. Si una lectura
  avisa de que tardó cerca del tope, súbelo.

### Qué cambia en lo que ya usabas

- **Puente KVM: el control dura todo el encargo.** Antes volvía a ti al
  terminar cada lectura o escritura, y un encargo de dos párrafos se quedaba en
  el primero. Ahora vuelve cuando Claude termina su turno o te pregunta algo,
  y también con Parar, «Retomar el Mac», a los 10 minutos sin actividad o al
  cerrarse Claude Code. Si lo interrumpes con Esc, vuelve con tu mensaje
  siguiente. La pantalla dice «Claude sigue con el control hasta que termine
  el encargo»: no toques el Mac hasta que vuelva.
- **Puente KVM: «Usar el Mac desde aquí» le quita el control a Claude**, sin
  pulsar antes «Retomar el Mac». Lo que Claude estuviera haciendo se corta en
  su siguiente tecla.
- **Puente KVM: leer ya no da la primera página vieja.** Antes, con el vídeo
  retrasado, la primera página podía salir de antes de subir al principio
  (faltaban las primeras líneas) y una lectura podía cortarse antes del final.
  Leer tarda unos 3 s más al terminar.
- **Puente KVM: la calibración del teclado explica «Latinoamericano ISO»**: el
  tipo de teclado que el Mac le asigne al JetKVM da igual mientras no cambie
  después de calibrar.

## 0.13.0 — 2026-11-25

La calibración del teclado del Puente KVM ya no pide DBeaver ni ningún
programa concreto: se mide en un TextEdit y se comprueba en el programa donde
escribes tus consultas.

### Qué tienes que hacer

- Actualiza. Si usas el Puente KVM, en su pantalla, «Reabrir la conversación
  de Claude» para que lea sus instrucciones nuevas.

### Qué cambia en lo que ya usabas

- **Puente KVM: calibrar el teclado va en dos partes.** Primero, en un
  **TextEdit vacío** (texto normal, comillas inteligentes y corrección
  automática apagadas), su Claude pulsa cada tecla, una línea numerada por
  tecla, y lee lo que sale. Después, en el programa donde **escribes tus
  consultas** —el que uses, con SQL Server o PostgreSQL—, teclea una consulta
  que no lee ninguna tabla, la ejecutas tú y con sus huellas se verifica. Si el
  TextEdit tenía las comillas inteligentes encendidas o tu teclado no da
  cifras en la fila de números, te lo dice en vez de medir mal. Al final
  sigues pulsando «Usar» en Ajustes → Teclado.

## 0.12.0 — 2026-11-25

El Puente KVM teclea bien en un Mac con cualquier teclado: si el Mac usa uno
que el puente no trae (el latinoamericano, por ejemplo), su Claude lo mide en
el propio Mac y lo comprueba antes de usarlo. El dictado entiende mejor tu
voz y tus palabras, y la barra de la terminal en el teléfono cabe en una línea.

### Qué tienes que hacer

- **Actualiza** con el botón de **Actualizaciones** (o con
  `bash scripts/actualizar.sh` en la carpeta del hub).
- **Si usas el Puente KVM**, la actualización lo reinicia si está libre; si
  estaba ocupado, su pantalla te lo ofrece con «Reiniciar el puente». Después,
  «Reabrir la conversación de Claude», para que su Claude tenga las
  herramientas nuevas.
- **Si en el Mac `< > { } [ ]` salen cambiados**, pídele a su Claude que
  calibre el teclado (skill `calibrar-teclado`): teclea en una pestaña de
  script vacía, te pide que ejecutes una consulta que sólo calcula huellas, y
  al final pulsas **«Usar»** en Ajustes → Teclado del Mac.

### Nuevo

- **Puente KVM: calibrar el teclado del Mac.** Hasta ahora sólo sabía teclear
  para «U.S.» y «Español - ISO»; con otra fuente de entrada, los símbolos
  salían cambiados. Ahora su Claude pulsa cada tecla del Mac en una pestaña
  vacía, lee lo que sale y arma la tabla, y una consulta que ejecutas tú
  confirma con huellas, fila a fila, que cada carácter sale exacto. Sólo una
  medida comprobada se puede elegir, y la eliges tú.

- **Eliges qué Whisper transcribe tu dictado**, en la flechita pegada al
  micrófono de la terminal y del Tablero (en el teléfono, en el «⋯» de la
  barra de la terminal, «Modelo del dictado») y en el chat del secretario:
  «Ligero» (el de siempre), «Preciso» (large-v3-turbo en la GPU: medido con una voz real, la
  mitad de errores por unas centésimas de segundo más) o «Apagado» (suelta la
  memoria de la GPU; el dictado sigue, más lento, por la CPU). Sólo se
  ofrecen los modelos ya descargados, y nada cambia tu elección.
- **El dictado conoce tus palabras**: se le da a Whisper una lista de
  términos (Claude, commit, worktree, Tailscale, SQLite… y los nombres de tus
  proyectos), y escribe bien los nombres propios y técnicos que antes
  confundía. La lista es tuya: `python -m hub.banco_dictado glosario
  --sembrar` la deja en `voz/glosario.txt` para que la edites. Sólo se usa
  con tu dictado, no con audios de otras personas.

### Qué cambia en lo que ya usabas

- **Dictar es un micrófono en todo el hub.** En Trabajo, Tablero y
  Orquestador el botón «Dictar» pasa a ser el icono del micrófono, como en el
  chat; mientras graba enseña un cuadrado de parar y los segundos. Igual en
  la interfaz de siempre y en la nueva.
- **Trabajo: la barra de encima de la terminal cabe en una línea**, también
  en la interfaz de siempre. En el teléfono quedan el selector (que ahora es
  el nombre de lo que ves y ya no ocupa una fila aparte), el micrófono y un
  «⋯»; la terminal gana alto y empieza más arriba. En el PC quedan fuera la
  letra, «Nota», el micrófono con su modelo y el «⋯». Dentro del «⋯»: la
  letra y la nota (en el teléfono), «Conversaciones anteriores», «Reabrir al
  encender» (lo que era «↻ Persistente», ahora un interruptor; un slot
  persistente lleva un icono de encendido junto a su nombre), «Pantalla
  completa», el reparto y «Ajustar a tmux». Las columnas ya no son un número
  suelto en la barra: si tmux tiene más de las que se ven, sale un aviso
  sobre la terminal con su botón «Ajustar». Ese aviso y los mensajes de la terminal
  (conectando, grabando, dictado escrito…) flotan sobre su esquina de arriba
  en vez de ocupar una fila, y se quitan tocándolos.
- **El selector de Trabajo en el teléfono ya navega desde un slot sin
  ventana.** Antes, en esa pantalla, elegir otro sitio no hacía nada.
- **Trabajo en el teléfono: cada ventana se llama igual que en el escritorio.**
  Las pestañas de un slot salían con el nombre del slot o de la sesión en
  vez de lo que hace cada una; ahora dicen lo mismo que el árbol: el nombre
  que tú le pusiste o, si no, el título de la conversación. Y lo que
  renombras se ve también en el árbol, no sólo en la pestaña. El selector
  de arriba elige ventanas («slot › ventana»), deja los slots sin ventana
  juntos al final y tiene un solo «+ Slot nuevo…» en lugar de uno por
  proyecto.
- **Puente KVM: sabe al momento si el Mac está en reposo.** El JetKVM se lo
  dice por el USB: la placa de arriba pone «Mac en reposo» y el panel lo
  avisa con «Despertar el Mac». El aviso de conexión ya no se queda en
  pantalla hasta recargar: se va solo en cuanto vuelve la imagen. Y
  **«Reconectar»** está siempre en el panel, junto a «Despertar el Mac» (antes
  sólo en Ajustes o cuando fallaba); con una reunión grabándose no reconecta,
  para no cortar su sonido.
- **Puente KVM: Opción+X no se pulsa nunca al teclear.** En DBeaver para Mac
  es «Ejecutar script», y el puente la usaba para escribir `≈` y `∑`. Ni su
  Claude ni tu «Pegar texto» la pulsan; un texto que la necesite no se
  teclea y te dice qué carácter. Puedes añadir más teclas en Ajustes →
  «Teclas que el puente nunca pulsa al teclear».
- **Puente KVM: un cambio aprobado se comprueba entero antes de la primera
  tecla** con el teclado del Mac: si un carácter no se puede escribir, no se
  escribe nada en vez de quedarse a medias.

## 0.11.0 — 2026-11-22

Más personajes para el secretario: cuatro gatos y cuatro amigos nuevos (un
ajolote, una capibara, un búho y una nutria), con sus poses.

### Qué tienes que hacer

- **Actualiza** con el botón de **Actualizaciones** (o con
  `bash scripts/actualizar.sh` en la carpeta del hub).
- Si quieres uno de los nuevos, elígelo en la pantalla del secretario,
  **Ajustes → Personaje**, con «Usar este».

### Nuevo

- **Gatos y otros amigos para el secretario.** En Ajustes → Personaje, dos
  grupos nuevos: «Gatos» (el gatito naranja con cascabel, el negro de moño,
  el siamés con audífonos y el que se asoma desde su caja) y «Otros amigos»
  (el ajolote con su libretita, la capibara con su mandarina, el búho de
  lentes y la nutria con su piedrita). Cada uno con sus poses para escuchar,
  pensar, buscar, anotar, hablar, esperar tu sí, celebrar y dormir.

### Qué cambia en lo que ya usabas

Nada: el personaje que tenías elegido sigue igual.

## 0.10.0 — 2026-11-22

Usar el Mac desde el Puente KVM va como en la web del JetKVM: la pantalla es
su vídeo tal cual y el puntero responde antes. Su Claude gasta menos al leer
y al revisar lo que escribe, y el secretario avisa de un compromiso media
hora antes también cuando se lo apuntas tú.

### Qué tienes que hacer

- **Actualiza** con el botón de **Actualizaciones** (o con
  `bash scripts/actualizar.sh` en la carpeta del hub).

- **Si usas el Puente KVM**, la actualización lo reinicia si está libre; si
  estaba ocupado, su pantalla te lo ofrece con «Reiniciar el puente». Después,
  «Reabrir la conversación de Claude» (el mismo aviso o el menú de la
  conversación), para que Claude use la forma nueva de leer. Recarga su
  pantalla (Ctrl+Shift+R) para ver el vídeo nuevo.

### Nuevo

- **Puente KVM: usar el Mac desde la pantalla del puente va como en la web
  del JetKVM.** La imagen es ahora el vídeo del aparato tal cual, a los
  fotogramas que mande (antes, unas 12 imágenes por segundo recomprimidas en
  tu PC), y el puntero responde antes; el puente, además, gasta menos CPU.
  Con el Mac simulado, o en un navegador que no sabe decodificar el vídeo,
  sigue por imágenes como antes. `/panel?medir=1` enseña cuántos fotogramas
  se pintan y el retraso del puntero.

### Qué cambia en lo que ya usabas

- **Puente KVM, el puntero** llega siempre a donde paras el ratón (antes
  podía quedarse corto si lo movías rápido), y reiniciar el puente con el
  vídeo abierto ya no espera unos segundos a que se cierre.
- **Puente KVM, menos gasto de Claude al leer y al revisar:** al transcribir
  un documento, Claude guarda una página y mira la siguiente en el mismo
  paso; al recorrer una hoja o una web larga, a partir de la segunda página
  sólo recibe lo nuevo; y al revisar un cambio ya escrito, sólo la franja que
  cambió (entera si no cambió nada, si se movió la vista o si la pide). Lo
  que ves en la pantalla del puente y lo que se teclea en el Mac no cambian.
  Para que Claude lo use, reabre su conversación después de actualizar.
- **Puente KVM, «Nueva conversación»:** si no se puede preparar la orden de
  Claude, lo dice y deja la conversación que tenías abierta, sin apuntar una
  nueva vacía en la lista.

- **Secretario, recordatorios:** un compromiso que le apuntas o le mueves con
  plazo pero sin decir cuándo avisarte te avisa **media hora antes** del plazo
  (si es sólo un día, esa mañana a las 9), como ya hacía con lo que sale de tus
  chats; antes te avisaba justo a la hora del plazo. Al moverlo, el aviso
  conserva la antelación que tenía, y un plazo que ya pasó no te suena de golpe.

## 0.9.0 — 2026-11-20

El Puente KVM despierta el Mac y lleva el jiggler con un botón, pega con los
acentos del teclado español y, al actualizar, se reinicia con botones en vez de
comandos; su Claude ya sólo carga lo del puente y gasta menos. Y desde el hub
se puede contar un fallo o una idea a quien lo mantiene.

### Qué tienes que hacer

- **Actualiza** con el botón de **Actualizaciones** (o con
  `bash scripts/actualizar.sh` en la carpeta del hub).

- **Si usas el Puente KVM**, la actualización lo reinicia si está libre. Si
  estaba ocupado, Actualizaciones lo dice: abre su pantalla y, **esta vez**,
  reinícialo con el comando que enseña su aviso (el puente de antes de esta
  versión aún no tiene el botón); desde la siguiente ya es un botón.
  **Después de reiniciarlo**, reabre la conversación de Claude (el aviso de
  arriba → «Reabrir la conversación de Claude», o el menú de la conversación
  → «Reabrir»), para que Claude tenga las herramientas nuevas. Reábrela
  después de reiniciar el puente, no antes: si no, se abre como hasta ahora,
  con tus conectores y skills personales.

- **Si el Mac está en español de España**, en la pantalla del puente elige
  «Español - ISO» junto a «Pegar texto»: con el teclado equivocado, los
  acentos salen como símbolos raros.

### Nuevo

- **Grabar una reunión del Mac con un botón (Puente KVM).** «Estoy en reunión»
  en la pantalla del puente graba lo que suena en el Mac y su pantalla (tu voz
  no: el JetKVM no tiene micrófono), y al pararla aparece en Reuniones y se
  procesa sola en unos minutos. Hace falta el firmware 0.5.9 o posterior del
  JetKVM y elegir en el Mac su salida USB (Sonido → Salida); los pasos, en la
  ayuda del Puente KVM.
- **Despertar el Mac y el jiggler (Puente KVM).** Bajo la imagen del Mac,
  «Despertar el Mac» lo saca del reposo (como «Intentar despertar» de la web
  del JetKVM) y dice si volvió la imagen; «Jiggler» lo enciende y lo apaga con
  «Frecuente, cada 30 s», para que el Mac no se bloquee ni te ponga «ausente».
  Claude puede ponerle horario («de 9 a 18 entre semana», con tu zona horaria)
  si se lo pides, y despertar el Mac si le das el control. El jiggler lo hace
  el JetKVM: sigue aunque cierres el puente.
- **Contar un fallo o una idea desde el hub.** En Actualizaciones (y en
  Ajustes, con la interfaz nueva) está «Contar un fallo o una idea»: eliges si
  es un fallo o una idea, lo cuentas y ves entero lo que va a salir, con la
  versión del hub y lo justo del equipo (sin rutas, usuario ni nombres; los
  puedes quitar). «Abrir en GitHub» te lleva al formulario de incidencias del
  repositorio de donde instalaste el hub, ya relleno, y lo envías tú con tu
  cuenta; el hub no manda nada por su cuenta. Lo que se envía a GitHub es
  público. Sin GitHub detrás, «Copiar el texto» y lo mandas por donde quieras.
  Desde la pantalla del Puente KVM, «Avisar de un fallo del puente».
- **Cuatro pingüinos nuevos para el secretario.** En su pantalla, Ajustes →
  Personaje, un grupo nuevo «Pingüinos»: el pingüinito con bufanda, el de la
  taza caliente, el de pajarita y el que va en su trocito de hielo. Como los
  demás dibujados, con su pose para escuchar, pensar, buscar, anotar, hablar,
  esperar tu sí, celebrar y dormir.

### Qué cambia en lo que ya usabas

- **Puente KVM, usando el Mac desde su pantalla:** un clic en la imagen del Mac
  se lleva el teclado aunque estuvieras escribiendo en la terminal de Claude
  (antes seguía yendo a Claude hasta pulsar «Pantalla grande»); y la rueda del
  ratón mueve como en la web del JetKVM (con un touchpad iba lentísima).
- **Puente KVM, pegar texto en el Mac:** se elige el teclado del Mac junto a
  «Pegar texto» («U.S.» o «Español - ISO»), y tras pegar algo con acentos te
  dice con cuál se tecleó: si no es el del Mac, los acentos salían como
  símbolos raros. Con «U.S.» ya se pegan las comillas “ ”, las rayas — y el
  resto de lo que se copia de una respuesta de Claude (antes no se pegaba
  nada). Si tu Mac está en español de España, elige «Español - ISO».
- **Puente KVM, terminal de Claude:** lo que seleccionas con el ratón se copia
  al portapapeles de la PC (y de ahí, «Pegar texto» lo lleva al Mac). Ctrl+C
  justo después de seleccionar ya no interrumpe a Claude; para eso, Esc.
- **Puente KVM, tras actualizar: botones en vez de comandos.** Si la
  actualización no pudo reiniciar el puente (estaba ocupado), Actualizaciones
  lo dice con un enlace al Puente KVM, y en su pantalla el aviso de arriba
  trae dos pasos: «Reiniciar el puente» y «Reabrir la conversación de Claude».
  Si está ocupado, el botón dice por qué y no lo corta; ni el botón ni la
  actualización lo reinician mientras tienes abierto «Usar el Mac desde aquí»
  en su pantalla, aunque no estés moviendo nada. Si Claude está trabajando
  (o, recién reiniciado el puente, no se sabe si lo estaba), reabrir o abrir
  otra conversación te pregunta antes de cortarlo. Sin systemd, el aviso sigue
  diciendo el comando. La primera vez, si el puente sigue con el programa de
  antes de esta versión, el aviso también dice el comando: reinícialo así esa
  vez y desde la siguiente ya son botones.
- **Puente KVM, la terminal de Claude sólo carga lo del puente.** Ya no carga
  tus conectores, skills, agentes ni plugins personales: gasta menos en cada
  llamada (cuanto más tengas puesto en tu Claude Code, más se nota) y lo que
  lee del Mac no tiene otro camino para salir. De tus ajustes de Claude Code
  se sigue llevando el modelo, el esfuerzo, la interfaz, la barra de estado,
  los avisos al teléfono, lo que tengas prohibido y lo que te pregunta. La
  terminal del puente ya no sale en el control remoto de Claude, aunque lo
  tengas encendido: es otra forma de manejar una sesión que ve el Mac de otro.
  **Una excepción:** si tus ajustes de Claude Code dicen cómo autenticarse
  (`apiKeyHelper`, `env` u otra forma), el puente los carga para poder
  arrancar y sólo deja fuera tus servidores MCP y lo que sincronizas de
  claude.ai (skills y plugins). Con «Sin pedir permisos», Claude ya tiene las
  skills del puente (antes arrancaba sin ellas). Si Claude Code se cierra,
  vuelve con el menú de la conversación → «Reabrir»; un `claude` escrito en
  la terminal también abre con lo del puente. Vale desde la siguiente
  conversación que abras o reabras.

## 0.8.0 — 2026-11-20

El Puente KVM con la pantalla del Mac en grande y Claude recorriendo una hoja
en una sola llamada; Reuniones graba el monitor de la llamada; y el
secretario ya no se rinde con la configuración de un programa.

### Qué tienes que hacer

- **Actualiza** con el botón de **Actualizaciones** (o con
  `bash scripts/actualizar.sh` en la carpeta del hub).

- **Si usas Reuniones, actualiza el agente de Windows** («Copiar el agente»
  en la pantalla Reuniones, y luego `instalar.cmd`). Hasta entonces graba como
  antes.

- **Si usas el Puente KVM**, después de actualizar abre su pantalla y, en la
  terminal de Claude, el menú de la conversación → **Reabrir**, para que Claude
  tenga las herramientas nuevas. Si lo arrancas sin systemd, reinícialo tú
  (`scripts/arrancar.sh`, con tu `PUENTE_TRABAJO` delante); con systemd ya lo
  hace la actualización.

### Nuevo

- **Puente KVM: «⤢ Pantalla grande».** Arriba de la imagen del Mac: la
  pantalla ocupa toda la ventana del navegador (no el monitor), sin la
  terminal, y se pide a su resolución real para que la letra pequeña se lea.
  Con − / + se acerca hasta el tamaño real y más; con las barras o arrastrando
  te mueves por ella. Se puede usar el Mac igual que en la vista de siempre.
  Esc o «Salir» vuelve.

- **Puente KVM: recorrer una hoja o una web en una sola llamada.** Claude
  tiene `recorrer_pantalla`: baja la zona que le digas con la rueda hasta el
  final y la recibe página a página, con cuánto se repite entre una y otra.
  Antes lo hacía a golpes de rueda y captura (unas 40 llamadas para una hoja).
  Y `ver_pantalla` puede devolver sólo una zona a tamaño real, que se lee
  mejor y gasta menos. Como la rueda, te pide permiso salvo con «Sin pedir
  permisos».

### Qué cambia en lo que ya usabas

- **Actualizar reinicia el Puente KVM** si su servicio es el de este hub,
  salvo que esté en medio de una lectura o una escritura o con el control
  dado a Claude: entonces no lo corta y te dice la orden para hacerlo después.
  Antes había que reiniciarlo a mano, y hasta entonces sus pantallas salían
  nuevas pero hacían lo de antes. Ahora, si corre un código que ya no es el
  del disco, también lo dice en su pantalla.

- **Reuniones graba la pantalla donde está la llamada.** Antes repetía el
  monitor de la grabación anterior (y el formulario marcaba el último de la
  lista), así que al mover la ventana de la reunión a otro monitor se grababa
  la pantalla equivocada sin que nada lo dijera. Ahora el agente busca la
  ventana de la aplicación, la sigue si la mueves y, si no la encuentra, lo
  avisa mientras graba y en la página de la reunión. Las grabaciones que
  empieza el secretario hacen lo mismo.

- **El secretario ya no dice que no puede con la configuración de un programa
  o juego de tu PC** (dónde la guarda, pasarla a otra cuenta). Averigua dónde
  está y te propone la orden exacta, con una copia de seguridad antes; la
  corre sólo si la apruebas. Empieza una conversación nueva para que lo lea.

## 0.7.1 — 2026-11-17

Un parche del Puente KVM: usar el Mac desde su pantalla va más fluido.

### Qué tienes que hacer

- **Actualiza** con el botón de **Actualizaciones** (o con
  `bash scripts/actualizar.sh` en la carpeta del hub).
- **Si usas el Puente KVM, reinícialo** (`systemctl --user restart
  puente-kvm`, desde cualquier carpeta; o vuelve a lanzar
  `scripts/arrancar.sh` en su carpeta con la misma `PUENTE_TRABAJO` delante).
  Sin reiniciarlo, sus pantallas se ven nuevas pero lo que hacen sigue siendo
  lo de antes.

### Qué cambia en lo que ya usabas

- **Puente KVM: el ratón y el teclado ya no esperan a la imagen.** Preparar
  cada imagen del directo dejaba al puente sin atender lo que hacías durante
  unos 40 ms, varias veces por segundo; ahora se prepara aparte y desde el
  vídeo, y mientras usas el Mac la imagen se refresca unas 12 veces por
  segundo.

## 0.7.0 — 2026-11-17

La interfaz nueva, apagada, para quien quiera probarla y dar su opinión; y en
el Puente KVM, usar el Mac desde su pantalla, la rueda invertible y «Sin
pedir permisos» sin preguntas antes de cada clic.

### Qué tienes que hacer

- **Actualiza** con el botón de **Actualizaciones** (o con
  `bash scripts/actualizar.sh` en la carpeta del hub).
- **Si usas el Puente KVM, reinícialo** (`systemctl --user restart
  puente-kvm`, o vuelve a lanzar `scripts/arrancar.sh` en su carpeta con la
  misma `PUENTE_TRABAJO` delante) y abre una conversación nueva.
- Para probar la interfaz nueva: al final de la **Guía**, «Probar la
  interfaz nueva». Si no quieres, no tienes que hacer nada.

### Nuevo

- **La interfaz nueva, para quien quiera probarla.** Viene apagada: al final
  de la **Guía**, «Probar la interfaz nueva» la enciende sólo en ese aparato
  (navegación en nueve secciones, barra abajo en el teléfono y sus colores) y
  «Volver a la de siempre» la apaga. Las pantallas por dentro son las mismas.
  Es una vista previa: lo que no se vea bien o eches en falta, cuéntalo.
  Todo, en `conocimiento/10-mas-pantallas.md`.
- **Puente KVM: usar el Mac desde la pantalla del puente.** «Usar el Mac
  desde aquí», bajo la imagen: tu teclado y tu ratón van al Mac sin abrir la
  web del JetKVM (que admite una sola sesión y desconectaba el puente). Ctrl
  hace de ⌘ (se quita con su casilla), ⌘Tab y ⌘Espacio tienen botón y
  «Pegar texto» teclea lo del portapapeles. Sólo mientras Claude no tiene el
  control, y lo que teclees no se guarda en ningún sitio.
- **Puente KVM: invertir la rueda.** En Ajustes, para cuando el Mac tiene el
  «desplazamiento natural» y la rueda va al revés; vale para Claude y para ti.

### Qué cambia en lo que ya usabas

- **Puente KVM: «Sin pedir permisos» ya no pregunta antes de cada clic o
  tecla.** Las reglas «pregúntame» del puente ganaban a ese modo; ahora, con
  la casilla marcada, no se aplican. Lo que sigue frenando a Claude es el
  control: sólo toca el Mac cuando se lo das. Vale para las conversaciones
  que se abran después de reiniciar el puente.

## 0.6.1 — 2026-11-17

Un parche del Puente KVM tras su primera prueba con un JetKVM de verdad.

### Qué tienes que hacer

- **Actualiza** con el botón de **Actualizaciones** (o con
  `bash scripts/actualizar.sh` en la carpeta del hub).
- **Si usas el Puente KVM, reinícialo** (`systemctl --user restart
  puente-kvm`, o vuelve a lanzar `scripts/arrancar.sh` en su carpeta con la
  misma `PUENTE_TRABAJO` delante). Si no lo usas, no tienes que hacer nada más.

### Nuevo

- **Puente KVM: teclado «Español - ISO» de macOS.** En Ajustes → Teclado del
  puente se elige la fuente de entrada que tiene el Mac mientras Claude
  teclea: «U.S.» o «Español - ISO». La española sale de la distribución de
  Apple y supone que el Mac tomó el teclado del JetKVM como **ANSI**. La
  latinoamericana aún no está.
- **Puente KVM: «Sin pedir permisos».** En Ajustes → Claude Code, una casilla
  (apagada de fábrica) para que Claude Code use sus herramientas en tu
  equipo sin preguntarte cada vez. Tocar el Mac sigue necesitando que le
  des el control en la pantalla del puente.

### Qué cambia en lo que ya usabas

- **Puente KVM: la rueda del ratón gira donde se le dice.** Antes giraba
  donde estuviera el puntero, que el puente deja aparcado en una esquina, y
  no movía nada.

## 0.6.0 — 2026-11-17

Herramientas opcionales (la primera, el Puente KVM para quien tiene un
JetKVM), un secretario que apunta lo que no sabe hacer y lo convierte en
mejoras, e investigaciones que llegan digeridas.

### Qué tienes que hacer

- **Actualiza** con el botón de **Actualizaciones** (o con
  `bash scripts/actualizar.sh` en la carpeta del hub).
- **Reinicia el secretario antes que la web, o a la vez** (lo hace
  `actualizar.sh`). Su memoria gana una tabla y, hasta que el servicio
  arranque con el código nuevo, la pantalla del secretario se ve vacía. Si
  lo tienes parado, se ve vacía hasta que lo enciendas.
- **Para que el secretario trate lo dictado como dictado, empieza una
  conversación nueva**: las que ya estaban abiertas leyeron sus instrucciones
  al empezar.
- **Para usar Fable 5.2, actualiza Claude Code** (`npm install -g
  @anthropic-ai/claude-code@latest`): hasta la 2.1.280 no lo reconoce.
- **Abre una vez la app del secretario en el teléfono** tras actualizar: así
  carga la versión nueva de sus avisos, con «Hecho» y «En 1 h» en los
  recordatorios.
- Si usas el secretario, reinicia `hub-secretario` para que lea las
  instrucciones nuevas (lo hace `actualizar.sh`).
- **Si preparas el Puente KVM**: su servicio no es del hub. Tras cada
  actualización del hub, reinícialo tú (`systemctl --user restart
  puente-kvm`, o vuelve a lanzar `scripts/arrancar.sh` en su carpeta con la
  misma `PUENTE_TRABAJO` delante), y antes de desinstalar el hub quítalo
  (`bash scripts/servicio.sh quitar` en `componentes/puente-kvm`):
  `desinstalar.sh` no lo toca.

### Nuevo

- **Herramientas opcionales, apagadas de fábrica**, en Ajustes → Guía
  («Herramientas opcionales»). Vienen con el hub, pero sólo le sirven a quien
  tiene con qué usarlas; apagadas no salen en ningún menú ni en ninguna
  búsqueda, y el hub se ve como siempre. La primera es el **Puente KVM**,
  para quien tiene un JetKVM: Claude lee y escribe en un Mac donde no se
  puede instalar nada. Viene en `componentes/puente-kvm` del clon, con su
  propio servicio, y se prepara una vez desde su pantalla («Preparar con
  Claude»). Encendido, sale en el menú (Agentes) y su pantalla dice si el
  puente está en marcha, si llega al aparato y quién tiene el teclado.
  «Abrir el puente» lo abre en una pestaña aparte, y sólo desde la PC donde
  corre. **Aún no se ha probado con un JetKVM de verdad**, sólo con el Mac
  simulado que trae. Si usas el asistente, `hub componentes` y `hub preparar
  puente` también lo conocen («Limpiar» su chat para que lea sus
  instrucciones nuevas). Todo, en `conocimiento/15-puente-kvm.md`. Si no
  tienes un JetKVM, no tienes que hacer nada.
- **«Te espera» enseña las peticiones que el navegador de Claude tiene en
  pausa** esperando tu permiso: la acción y el sitio, nunca la dirección
  entera, con un botón que lleva a Navegante, donde se contesta. No se
  pueden callar ni aprobar desde ahí, y si el guardián no está en marcha la
  fila lo avisa.
- **En Secretario → Memoria, «Filtrar» junto a la búsqueda.** Por tema
  (persona, proyecto, preferencia, decisión, dato, investigación, inglés) y
  por «Sin salir en ninguna búsqueda desde el …»: las notas que el
  secretario no ha usado al buscar desde que se cuenta. Nada se borra solo.
- **`/maquetas/` enseña prototipos HTML, sólo para mirarlos.** Los de la
  carpeta `maquetas/` del repo (u otra con `HUB_MAQUETAS`), también desde el
  teléfono por el acceso remoto. Cada página va aislada del hub: sus `.css` y
  `.js` se incrustan, y lo que cargue de un CDN o como imagen suelta no se
  ve. Sin la carpeta, la ruta responde 404.
- **El secretario conoce las skills de tus proyectos.** Puede consultar las
  skills, agentes y métodos que cada proyecto tiene escritos (lo que enseña
  Inventario) y leer cómo se hace un proceso antes de explicártelo, en vez
  de inventarlo. Depende de que el inventario esté escaneado.
- **De «no sé hacerlo» a una mejora.** Cuando le pides algo que aún no sabe,
  te pregunta si lo apunta como mejora en el tablero y, si quieres, la manda
  trabajar; nunca lo hace sin que se lo digas. Confianza enseña en qué punto
  va cada una.
- **El secretario apunta lo que no sabe hacer.** Cuando te dice que aún no
  puede con algo, lo deja anotado, y Confianza enseña «Lo que le pediste y no
  supo», agrupado y con su recuento: así se sabe qué le falta sin que tengas
  que acordarte de pedirlo.
- **Cada dictado deja medido lo que tardó.** Una línea en el registro del hub
  con el tiempo total y el de Whisper, por qué camino fue, el modelo, si usó
  GPU o CPU y cuánto duraba el audio; nunca lo que dijiste. El servidor de
  voz guarda su arranque y sus errores en `voz/servidor.log` (las últimas
  200 líneas).
- **El recorrido de pantallas avisa de más cosas** (`python -m hub.recorrido`),
  sin darlas por rotas: botones y enlaces de menos de 24 px, campos con letra
  de menos de 16 px en el móvil, pantallas sin título principal o sin `main`,
  respuestas de más de 500 ms y más de un botón de acción principal a la vez.
- **El secretario mira tu PC con PowerShell.** Pídele «revisa qué modelo son
  mis monitores» o «¿qué tengo conectado por USB?» y lo mira él, sin
  preguntarte, si la orden sólo mira (aparatos, controladores, discos, red,
  servicios, el registro). Lo comprueba el propio PowerShell antes de
  correrla y la corre recortada a esos comandos; no lee tus archivos.
  **Si hace falta cambiar algo, te pide tu sí con la orden exacta**, que ves
  entera en Pendientes: nada cambia sin él, y si tardas más de 15 minutos no
  la corre. Además, se niega a pedirte lo que toque tus proyectos, puertos,
  docker o WSL; eso es una red para lo evidente, no una garantía. Nunca lo
  usa desde un disparador. Sólo en Windows, con el hub en WSL.
- **Elige con qué modelo investiga el secretario, y páralo si te arrepientes.**
  «Investígalo con opus» o «consúltalo con Fable 5.2» lo hace con ése; si no
  dices ninguno, lo elige él según lo difícil que sea (Haiku para un dato,
  Sonnet para comparar fuentes, Opus para analizar). Fable sólo si lo nombras
  tú en tu mensaje: es el que más gasta. «Contéstame con fable» le pasa la
  respuesta a ése. Y «para la investigación» (o «páusala») la detiene a mitad
  y quita las que esperaban; para retomarla, pídela otra vez.
- **Responde a un mensaje concreto del secretario, como en WhatsApp Web.**
  Doble clic en el hueco al lado de un globo (o su ↩, que en el teléfono se
  ve siempre): encima del cuadro sale «Respondiendo a…»; × o Escape lo quita.
  Tu mensaje lleva la cita arriba y pulsarla te lleva al original. Le llega
  lo citado aunque esa conversación ya se haya cerrado, y lo trata como dato,
  no como una orden.

- **Pregúntale al secretario por un día concreto.** «¿Qué hice ayer?» le
  deja ver las sesiones de trabajo de ese día, y al buscar en tus mensajes
  «hoy» y «desde las 3» son tu hora local, igual que las horas que te cita.
- **Busca en todas tus notas.** En la pestaña Memoria del secretario, pulsa
  Intro en «Filtrar notas» para buscar en todas, no sólo en las 80 más
  recientes.
- **Respaldo y Máquina vigilan también la copia de la memoria del
  secretario**, si lo usas: dicen cuándo fue la última y avisan en pantalla
  si lleva más de dos días sin hacerse.

- **Una dirección que no existe abre una página del hub**, con el menú y el
  buscador, en vez de un error en inglés; y un proyecto que ya no existe lo
  dice al volver al panorama.
- **Cada respuesta dice en qué se le fue el tiempo**, en la cabecera
  `Server-Timing` (DevTools → Red → Timing), y la línea del registro de una
  petición lenta también. Sirve para saber por qué tarda una pantalla.

- **Banco de dictado** (`/voz/banco`, también desde la guía). Lees en voz alta
  unas frases en la PC y en el teléfono; se guardan sólo en tu máquina, y
  `uv run python -m hub.banco_dictado medir --modelos small,large-v3-turbo`
  te dice qué modelo de Whisper te entiende mejor: error por palabras, por
  categoría y por aparato. Las grabaciones no caducan ni van en la copia
  diaria. Con tu propio vocabulario: `python -m hub.banco_dictado sembrar
  --de mis-frases.yml`, antes de grabar.

- En Ajustes → Confianza, bajo «Lo que le pediste y no supo», ahora se
  cuentan también las veces que contestó que no podía sin apuntar qué le
  faltaba.
- **El secretario sabe más del hub y de cada persona.** Ideas del tablero,
  fichas, consumo, versión y dónde está cada pantalla; «¿cuándo hablé
  con…?»; y busca primero en lo que ya anotó. Sin calendario conectado ya no
  intenta leerlo.
- Máquina: «Diagnosticar ahora» enseña pantallazos, volcados y latencia de
  Windows, en sólo lectura y a petición.
- Reuniones: la pantalla dice si el agente de Windows está al día y, si no,
  ofrece copiarlo; en una reunión, sus compromisos abiertos se cierran de
  una vez («Darlos por hechos» o «Descartarlos»).
- Lo que el secretario te pide aprobar sale como tarjeta encima del cuadro
  del chat, con el texto entero: apruebas o rechazas sin ir a Pendientes.
- Puedes pedirle al secretario que detenga o reanude una tarea, arranque o
  pare un contenedor, archive un slot, descarte una idea o ponga el modo
  inglés. Salvo el modo inglés, pregunta siempre y no se aprueba desde la
  notificación.
- Por el chat puedes corregir una nota o el texto de un compromiso, y
  pedirle que olvide una nota; olvidar pide siempre tu permiso.
- El aviso de un recordatorio trae «Hecho» y «En 1 h» (Android y PC), y
  puedes preguntarle en qué está cualquier sesión de Claude Code de un slot.
- Si usas fichas de cambios, cuando la mejora que nació de algo que el
  secretario no sabía hacer está hecha y su herramienta ya está cargada, te
  lo dice una vez en el chat (nunca al teléfono).
- Trabajo reúne las shells sin usar desde que arrancó tmux y cierra las que
  marques, con confirmación. En el orquestador, una tarea terminada o
  detenida enseña lo que dejó abierto y ofrece cerrarlo y archivarlo.

- Puedes pedir más sobre una investigación («profundiza en el punto 3»): la
  siguiente sabe lo que ya se encontró y no lo repite. Cada investigación
  dice cuánto tardó y a cuánto equivale, y Memoria → Investigaciones lista
  las últimas con modelo, estado y gasto; lo que gastó una cortada sale como
  «no se sabe».
- La copia diaria se comprueba al hacerla y puede llevarse también a una
  segunda carpeta en otro disco (`HUB_RESPALDO_EXTRA` o `respaldo-extra.txt`
  dentro de la carpeta del hub); `/respaldo` dice si llegó.
- En Secretario → Ajustes → Voz eliges, en cada aparato, qué voz te lee
  (también en el modo inglés) y a qué velocidad, con «Probar».

- `scripts/medir_claude.py` comprueba, tras actualizar Claude Code, que el
  hub sigue leyéndolo bien (sin gastar cuota; `--con-modelo` para lo que sí
  gasta).

- El chat del secretario enseña las conversaciones anteriores encima de la
  de ahora, con un separador cada una; «Ver lo anterior» trae más, y cada
  conversación de la lista se abre en el chat.
- Al rechazar lo que pide el secretario puedes decirle por qué, desde el
  chat o desde Pendientes; te contesta a eso, y el chat nombra la acción por
  su nombre.

### Qué cambia en lo que ya usabas

- **Las investigaciones del secretario llegan digeridas.** Sin cabecera ni
  tu pregunta repetida: primero la respuesta, luego de 3 a 6 puntos redactados que citan
  sus fuentes por número (`[1][3]`) y, si cabe, «Lo que deduzco», rotulado
  como no dato. Las direcciones ya no van en el texto: están en la tarjeta
  «Fuentes», numeradas igual y como enlace corto (el dominio; pulsarlo abre
  la página en otra pestaña). Un punto que no cita ninguna fuente válida, o
  con una cifra que no está en las fuentes que cita, no se enseña y se
  cuenta. Si el investigador no devuelve esos puntos, sale como antes. Las
  notas que ya tenías no cambian, y las nuevas se siguen pudiendo ampliar
  («profundiza en el punto 3»).
- **Actualizar copia tus bases antes de tocarlas** (`respaldos/antes-
  hub-<fecha>.db` y `antes-secretario-<fecha>.db`, las tres últimas) y ya no
  da la versión por instalada sólo porque la web conteste: si el muestreo no
  late en un minuto, o un servicio que reinició no sigue en marcha, falla y
  te dice cómo volver a la de antes (`INSTALAR.md`, «Volver a la versión
  anterior»). Si el secretario aún no late, sólo avisa. Nada se restaura
  solo. La comprobación final puede tardar hasta un minuto más.
- **Las notas que el secretario saca solo llevan un tema de una lista corta,
  o ninguno**; las que apuntas tú, el que digas. Al cerrar una conversación
  también apunta tus preferencias. Las notas que ya tenías no cambian.
- **Lo que se pega en una sesión va sin caracteres de control.** Un mensaje
  de fuera (Encargos, el canal de consulta) que los trajera podía cerrar el
  pegado antes de tiempo y llegar al agente como teclas sueltas; ahora se
  quitan antes de pegar, y si se quitó alguno el registro lo dice.
- **Si el hub no contestaba y dictabas y luego escribías, «Reintentar» manda
  las dos cosas** (antes se perdía lo grabado), y los fallos del dictado
  salen en rojo. Un fallo antes de llamar al modelo ya no deja la respuesta
  «pensando» hasta reiniciar.
- **Sin registro de proyectos, el secretario no cambia nada en tu PC**: antes
  sólo se negaba si el registro estaba roto, no si faltaba.
- **El chat del secretario se abre mostrando la última respuesta entera**,
  aunque haya algo en «Te espera», y sigue al final al abrir el teclado del
  móvil. El panel ya no enseña un instante las sugerencias de «chat vacío»
  al cambiar de pantalla.
- **Si un mensaje al secretario no sale, lo dice en rojo bajo el cuadro, con
  «Reintentar»**, y lo escrito no se pierde; en el modo voz se pausa y lo dice
  en voz alta.
- **Si le escribes con su servicio parado, el chat lo dice a los pocos
  segundos** («lo contestará al volver»), con un enlace a su pantalla, en vez
  de quedarse «pensando».
- **Cuando no puede contestar, dice qué pasó y qué hacer en lenguaje llano**;
  el detalle técnico queda en `journalctl --user -u hub-secretario`.
- **El código de sus respuestas sale en un bloque aparte, con «Copiar»**, y
  los títulos sin almohadillas.
- **Modo voz: «déjame mirarlo» suena mientras busca**, no al terminar. Puedes
  contestar en cuanto calla o seguir hablando tras interrumpirle: lo dicho ya
  no se pierde. Una tos o un ruido no lo pausan: dice «¿Perdón?» y sigue; y
  si se pausa por un fallo, lo dice en voz alta. Ya no se queda «hablando» si
  el navegador no avisa del final de una frase.
- **Dictado: si se corta la red, se reintenta solo**; si no sale, aparece
  «Reintentar» y lo grabado no se pierde. El panel dice cuándo pasa tu voz a
  texto y enseña lo que entendió, y si el micrófono falla dice por qué (sin
  permiso, no hay micrófono, ocupado por otra aplicación).
- **El primer dictado tras un rato es más rápido**: el Whisper empieza a
  cargar al pulsar grabar. Y lo dictado sin revisar le llega al secretario
  como dictado: si algo clave no cuadra, pregunta antes de actuar.
- **«Reabrir tus slots persistentes» ya no ofrece lo que está abierto**: sólo
  sale para los slots que se quedaron sin ninguna ventana, y cuenta sólo las
  que faltan.
- **El aviso de una sesión perdida dice cuántas ventanas volvieron** y cuántas
  sin su agente; si el corte es de hace más de un día, sale plegado en una
  línea.
- **Servicios no ofrece arrancar ni parar sobre una lectura vieja.** Si Docker
  no contesta, no está instalado o no hay lectura de la última media hora,
  enseña la última con su fecha y el menú deja de contar contenedores.
- **Actualizaciones dice cuándo un clon no tiene remoto**, explica en español
  por qué falló la consulta y avisa si lleva más de dos horas sin mirar.
- **Respaldo avisa cuando la última medición no llegó a todos los repos**:
  cuántos se midieron y qué filas tienen una cifra anterior.
- **La última actividad de un slot es la última vez que su agente trabajó**;
  tener una ventana abierta ya no la actualiza.
- **Talleres cuenta como trabajando la sesión que delega en subagentes**, y
  dos talleres con el mismo nombre se distinguen por su ventana.
- **Archivos y la lista de sesiones cargan mucho más rápido** desde la segunda
  visita: lo que no cambió en el disco no se vuelve a leer. Si cambias a
  dónde apunta un enlace que declaraste como ruta, Archivos tarda hasta un
  minuto en verlo.
- **Reiniciar o actualizar el hub ya no deja «Failed» en el registro de sus
  servicios**, y el secretario termina de contestarte antes de reiniciarse
  (hasta 45 segundos). Los servicios arrancan con el Python del entorno, sin
  `uv run`. No tienes que hacer nada: `actualizar.sh` regenera los servicios.
- **Los recordatorios ya no esperan a que el secretario termine de leer tus
  mensajes**, ni el corte de la grabación de una reunión. Y lo que le
  apruebas se hace casi al momento.
- **El secretario sabe qué día y hora es en cada mensaje**: «mañana» o «el
  jueves» se entienden sin una consulta de más.
- **Si le pides cambiar algo en un proyecto, te ofrece encargarlo** en vez de
  decir que no puede.
- **Cuando pasa una pregunta al modelo mayor, la respuesta se va viendo**
  mientras se escribe.
- **Si se reinicia a mitad de una respuesta, al retomarla no repite lo que ya
  había hecho.** Y un mensaje escrito justo cuando la conversación se estaba
  cerrando ya no desaparece del chat.
- **El secretario sólo investiga cuando se lo pides tú en una conversación**:
  ni un disparador ni el modo inglés pueden encargar una investigación. Si
  una investigación falla al devolver sus resultados, te lo dice en vez de
  responder que no encontró nada.
- **Si no puede leer tu registro de proyectos, no te pide cambiar nada en tu
  PC** hasta que pueda; mirar sigue funcionando.
- **El resumen de una sesión de trabajo llega marcado como dato y con las
  llaves tapadas**, y un disparador ya no puede mandarte «…» al teléfono.
- **La sugerencia de pasar una acción a «auto» sólo aparece tras cinco
  aprobaciones seguidas**, sin un «no» ni un fallo entre medias.
- **Las pantallas viajan comprimidas**: se cargan bastante más rápido desde
  el teléfono. Reuniones abre en menos de un segundo donde tardaba siete.
- **Las pestañas del hub que no estás mirando dejan de preguntar al
  servidor**; al volver se ponen al día enseguida.
- **Menos escritura en disco**: el muestreo ya no reescribe el registro cada
  20 segundos si nada cambió, y las copias diarias quedan en un solo archivo.
- **Las notas de los slots ya no enseñan contraseñas ni llaves.** El
  secretario las ve tapadas y el buscador (Ctrl+K) las muestra como
  `[secreto oculto]`, aunque sigue encontrando la nota por sus palabras. Es
  un filtro por patrones, no una garantía: guarda las llaves en el llavero y
  deja en la nota sólo el puntero.
- **El registro del servicio web ya no apunta cada acceso correcto.** Sólo
  las respuestas con error y las peticiones de más de un segundo, con su ruta
  y su tiempo: el historial de `journalctl` pasa de unos seis días a semanas.
  Surte efecto al ejecutar `scripts/actualizar.sh`, que regenera el servicio.
  Los avisos repetidos del ciclo lento («docker no está instalado») se dicen
  una vez por racha, no cada diez minutos.
- **Una investigación ya no va siempre con Haiku**: si no nombras modelo, el
  secretario puede elegir Sonnet u Opus para una pregunta que pide comparar o
  analizar, y entonces tarda algo más y gasta más (como mucho 1 USD con Sonnet
  y 1,50 con Opus, frente a 0,50 con Haiku). Si prefieres que no, nómbrale
  «con haiku».
- **El tope de gasto de una investigación va por modelo**: el de siempre con
  Haiku, y más alto con los que gastan más. Si pusiste `investigar: tope_usd`
  en `secretario.yml`, ese número vale para todos; para uno solo,
  `tope_usd: {fable: 8}`.
- **En Trabajo, pulsar una ventana de un slot abre ésa.** Si el slot tenía
  ventanas en más de una sesión de tmux (por ejemplo, tras restaurar),
  pulsar cualquiera de la otra sesión te devolvía siempre a la primera, y no
  había forma de llegar a las demás para usarlas o cerrarlas.

- **En un disparador `pide`, el secretario ya sólo te avisa por su cuenta.**
  Cualquier otra cosa te pide permiso aunque esté en auto; la solicitud dice
  que nació en un disparador y se aprueba abriendo la app, no desde la
  notificación. Lo que pones en `haz` no cambia.
- **Lo que se escribe en un grupo y no va para ti se lee junto** (diez
  mensajes o cinco minutos) en vez de mensaje a mensaje: gasta menos. Un
  aviso «En el grupo» puede tardar hasta unos cinco minutos; lo que es para
  ti y tus disparadores no esperan.
- Mientras el secretario escribe una respuesta larga, la pantalla ya no dice
  que no está en marcha.
- Al preguntarle por un periodo («¿qué anotamos desde el lunes?»), el
  secretario ya no trae notas de otros días, y dice en tu hora cuándo fue el
  último mensaje de un chat, cuándo se encargó una tarea y desde cuándo
  espera un asunto.
- Si una investigación falla, te lo dice en llano y con qué hacer. Si el
  modelo elegido no devuelve los datos con su fuente, la repite una vez con
  el modelo de siempre y te lo dice (son dos intentos, cada uno con su
  tope).
- Dictar en la terminal (/trabajo) ahora dice por qué no puede usar el
  micrófono (sin permiso, sin micrófono u ocupado por otra aplicación),
  reintenta una vez la subida si se corta la red y empieza a cargar el
  modelo de voz al pulsar «Dictar», como ya hacían el secretario y el
  tablero.
- Si tienes `HUB_TRANSCRIPTS` puesta, ahora la siguen también las
  conversaciones de cada slot, el contexto, el orquestador, el asistente y
  Talleres; antes sólo Consumo e Inventario.
- Si el secretario se reinicia mientras investiga o resume una sesión, lo
  repite solo (como mucho dos veces) y te lo dice en el chat.
- Si Claude no está disponible, el secretario ya no aparta mensajes ni
  cierra conversaciones sin resumen: espera y reintenta solo. Antes de
  apartar hace una llamada mínima de prueba.
- Una acción que apruebas se hace una sola vez: si el secretario se reinicia
  a mitad no la repite; te dice que no sabe si se hizo y queda como «no sé
  si se hizo».
- Los mensajes programados y el orquestador ya no esperan hasta un minuto
  cada diez mientras se miden repos y consumo; Máquina → Salud gana la fila
  «Mediciones lentas». El muestreo ya no relee todo el registro de Claude
  Code en cada medición. No tienes que hacer nada.
- Lo que contesta un disparador `pide` queda entero en su chat y al teléfono
  llega la primera línea (`en_chat: false` lo deja como antes).
- En el teléfono los campos ya no amplían la página al tocarlos, botones y
  plegables son más fáciles de pulsar, el menú abre plegado y la paleta no
  parte los títulos; en todas partes los campos llevan el mismo estilo, las
  casillas dejan la versalita, los ejemplos se ven apagados y hay «Saltar al
  contenido» para el teclado.
- «Te espera» agrupa los bloqueos de cada proyecto y lo que vence en una
  línea plegada con su cuenta; lo que sólo contestas tú sale arriba, y en
  cada fila la acción propuesta va destacada y el resto en su menú (⋯). La
  cabecera dice cuántas cosas son nuevas.
- En Memoria las notas se leen y se corrigen con «Editar»; «Borrar» pasa a
  su menú, en rojo. En Canal cada persona se lee en una línea, con su
  formulario tras «Editar», y los permisos enseñan sólo los proyectos donde
  tiene algo.
- Junto a la conversación, lo vencido sale aparte («Vencidos»), con «Hecho»
  y «Mover». Pendientes junta los compromisos vencidos en «Vencidos sin
  cerrar» para cerrarlos o descartarlos de varios en varios; el parte dice
  dónde están.
- Confianza y la ficha de proyecto dicen «Lo hace solo», «Te pregunta» y
  «Nunca» (en la configuración sigue auto/ask/never).
- Máquina: «Salud del hub» enseña arriba sólo lo que pide algo; lo que está
  bien queda plegado en «Todo en pie», y cada estado lleva su glifo. «Tras
  el último arranque» dice cuánto tardaron WSL y el hub en volver tras
  encender.
- El secretario ya no te recuerda en el teléfono lo que te pide otra persona
  en un chat o una reunión: queda en Pendientes con su plazo, o como nota si
  no trae plazo (pídele «recuérdamelo» si lo quieres).
- El estado de un proyecto ya no se corta a media palabra: «Leer entero» lo
  despliega en su ficha. La búsqueda (Ctrl+K) dice cuando no encuentra nada
  y enseña cada slot con su proyecto y su ruta en vez de su nota. La Guía y
  Acceso hablan del secretario cuando es él quien te habla.
- La bandeja de la portada ya no cuenta una ventana partida que tiene un
  panel en un slot: sale sólo bajo su slot. Un slot abierto por el
  secretario, el orquestador o Encargos sale ya bajo su slot en Trabajo, sin
  pasar 20 s por «Sin organizar».
- En Trabajo, «Ocultar» y «Cerrar» de las ventanas sin organizar están en su
  menú ⋯, y el nombre ya no se parte. En el teléfono, el selector de Trabajo
  marca lo que estás viendo, y los slots con ventana van primero.
- Un doble clic en «Dictar» o en el micrófono del secretario, o salir del
  modo voz mientras se abre, ya no deja el micrófono grabando.
- Intercambio: «Elegir archivos» en castellano y varios a la vez; miniaturas
  de las imágenes; un solo selector de sesión y las acciones de cada archivo
  en su menú ⋯.
- Lienzos: un valor escrito en bloque se publica en una línea (o se rechaza
  diciendo la línea), y sus saltos se ven; marcar una decisión ya no pisa
  una versión publicada mientras lo tenías abierto.
- Encargos: un encargo descartado o publicado ya no ofrece «Abrir el
  entrevistador». Archivos: en el teléfono el filtro va debajo de la
  explicación. Inventario: CHANGELOG, PLAN, PENDIENTES y ESTADO de un kit
  dejan de contarse como «método» tras reescanear.

- La nota que guarda una investigación ya no se corta a 4000 caracteres, y
  una investigación puede tardar hasta 20 minutos (antes se cortaba a los
  10).
- Mis datos: «Confirmar» sólo confirma el valor que tenías delante; si
  cambió mientras lo mirabas, no confirma y te lo dice.
- Los avisos con emoji, texto no latino o un título largo ya llegan por la
  app (antes caían a Telegram), y un aparato con la suscripción rota ya no
  deja sin avisos a los demás.
- Mirar el hub sin usar el secretario ya no le crea su carpeta ni su base, y
  la web ya no la migra (lo hace el servicio). Lo que el secretario guarda
  —notas, compromisos y respuestas— lleva tapado lo que parece una llave.
- El secretario sólo te lee con voces de tu aparato. Las de red (las
  «Google…» de Chrome, las «Online» de Edge) mandan el texto fuera y sólo
  suenan si las eliges tú en Ajustes → Voz.
- «Leer las respuestas en voz alta» empieza a leer según escribe, y las
  respuestas habladas son más cortas y sin rutas, códigos ni símbolos. En el
  modo voz, si tarda en empezar con lo tuyo, te dice «un momento».
- Con el modo inglés puesto, una línea encima del cuadro lo recuerda, con
  «Quitar». El globo dice «Te espera: N nuevas»; en el teléfono, los botones
  pequeños del chat se tocan mejor.
- Un repo recién clonado bajo un `patron` tarda hasta un minuto en aparecer;
  si su carpeta no se deja leer un rato, sus repos conservan su última cifra
  de respaldo en vez de desaparecer.

- Las fechas salen en tu hora y con cuánto hace («13/11 14:41 (hace 3 h)»);
  una medición atrasada sale en ámbar. Las cifras llevan coma decimal en
  todas las pantallas («64,0 MB», «25,0 %»).
- La explicación de Canal, Conexiones, Servicios, Consumo y Navegante va
  plegada bajo «¿Por qué así?». En el teléfono no salen teclas y «Buscar» es
  una lupa.
- «Refrescar» sólo sale en Panorama, Trabajo y Talleres; en Servicios,
  «Reescanear» pasa a «Medir ahora», arriba. El cian marca sólo la acción
  principal; «Aprobar» o «Guardar» de cada fila van en tono de aceptar;
  «Encolar» pasa a cian.
- La terminal toma fondo, cursor y selección de los colores de la interfaz.

- El secretario dice cuántos mensajes hay cuando no los lee todos, y lo
  largo le llega recortado pero entero, no partido.

- El secretario ya no intenta lo que aún no está configurado (la tele sin su
  IP, poner cosas en el calendario sin Google): en Ajustes → Confianza sale
  «sin configurar», con dónde se configura.

- Sin systemd, `bash scripts/arrancar.sh --parar` seguido de arrancar otra
  vez (lo que pide `actualizar.sh` en esas instalaciones) ya no deja el hub
  apagado diciendo que el puerto lo usa otro programa: parar espera a que la
  web suelte el puerto.

## 0.5.2 — 2026-11-10

El secretario se pone en todas las pantallas con un botón, revisa tus
programas y quien trabaja para él lleva tu personaje.

### Qué tienes que hacer

- **Actualiza** con el botón de **Actualizaciones** (o con
  `bash scripts/actualizar.sh` en la carpeta del hub).
- Si usas el secretario y abajo a la derecha sigues viendo al asistente: en
  su pantalla, **Ajustes → Personaje → Ponerlo en todas las pantallas**.
- Si los ayudantes del secretario siguen saliendo como el cubo azul con otro
  personaje elegido, recarga la página con **Ctrl+Shift+R**.

### Nuevo

- **El secretario mira tus programas.** Pregúntale qué versión tienes de un
  programa («¿qué tengo de AMD?»), la del controlador de tu tarjeta gráfica,
  o si un proceso está escribiendo sin parar: te dice lo instalado con su
  versión, cada gráfica con su controlador y lo que escribe cada proceso,
  medido unos segundos. Sólo leyendo, como el resto de lo que revisa en tu
  PC. Desde la terminal: `uv run python -m hub.diagnostico programas`.

### Qué cambia en lo que ya usabas

- **El secretario en todas las pantallas, con un botón.** Si lo usas pero en
  la pestaña de abajo seguías viendo al asistente: en su pantalla, Ajustes →
  Personaje → **Ponerlo en todas las pantallas** (sale con él encendido).
  «Quitarlo de abajo» devuelve al asistente. Ya no hace falta editar
  `secretario.yml`; si lo tenías puesto ahí, sigue igual.
- **Quien trabaja para el secretario lleva tu personaje.** Si elegiste uno
  dibujado, lo que investiga en la web, la sesión que hace su encargo y sus
  subagentes salen a su lado como ese mismo personaje en pequeño, con una
  insignia de lo que hace (la lupa si investiga…). Antes salía el cubo azul
  de siempre junto a tu personaje. Con el cubo, todo sigue igual.

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
