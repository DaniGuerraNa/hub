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
git pull && bash scripts/actualizar.sh --sin-bajar
```

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
