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

Lo que irá en la próxima versión. Al publicarla, este título pasa a ser su
número.

<!-- 🔴 SIN CONFIRMAR: en el navegador del dueño aún no pega (ESTADO §1).
     No publicar esta línea hasta verlo funcionar allí. -->
- **Ctrl+V pega en la terminal web**, texto e imágenes (también la captura de
  Win+Shift+S). Antes la terminal se quedaba la tecla como `^V` y no pegaba
  nada: la 0.3.0 lo anunciaba y no funcionaba. Ctrl+Shift+V y Mayús+Insert
  hacen lo mismo.

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
