# La pantalla de trabajo, los slots y la terminal

`/trabajo` es donde vas a pasar el día: **slots a la izquierda, terminal en
medio y, a la derecha, un panel con cuatro pestañas**: Nota, Lienzos, Consultas
y Programados. La nota se explica aquí; las otras tres, en
[`10-mas-pantallas.md`](10-mas-pantallas.md).

## Qué es un slot

Una línea de trabajo con nombre dentro de un proyecto — «respaldo pendiente»,
«refactor del carrito», «bug del login». **La ruta es un atributo suyo, no su
identidad**, así que una nota larga sobrevive a que se caiga tmux o se reinicie
la máquina.

La relación es: `proyecto → N slots → 1 nota por slot, y N ventanas por slot`.

- **La nota vive en el slot, no en la ventana.** Varias ventanas del mismo slot
  comparten su nota.
- El panel de la derecha **sigue a la pestaña**: enseña la nota del slot de la
  ventana que estás mirando, no la del slot con el que entraste.
- Se guarda sola mientras escribes.

### El árbol de la izquierda

Proyecto → slot → ventanas, una dentro de otra. Bajo cada slot están sus
ventanas abiertas, cada una con su punto de estado: pulsa una para verla, doble
clic para renombrarla, la **cruz** para cerrarla y **«+ Ventana»** para abrir otra en
la carpeta del slot. Las ventanas que no son de ningún slot están al final, en
«Sin organizar»; su **⋯** tiene «Ocultar» (deja de salir en la lista y sigue
corriendo) y «Cerrar» (con confirmación). En el escritorio el árbol sustituye
a las pestañas de encima de la terminal; con el raíl plegado, a pantalla
completa o en el móvil vuelven las pestañas. En el móvil, el selector de arriba
—que es también el nombre de lo que estás viendo, en la barra de encima de la
terminal— hace de árbol: una opción por ventana, «slot › ventana», agrupadas por
proyecto; luego «Sin organizar» y, al final, los slots sin ventana abierta.
Marca la ventana que estás viendo; si no está en la lista (una ventana oculta,
por ejemplo), lo dice con «Viendo: …». Cada ventana se llama igual en el árbol,
en las pestañas y en el selector: el nombre que le pusiste o, si no, el título
de la conversación.

Después de reiniciar el equipo, tmux puede devolver como `bash` las ventanas
de todo lo que tenías abierto. Debajo de la lista, **«N shells sin usar desde
el arranque»** las reúne: shells a secas, sin nada en marcha dentro (ni un
guion, ni algo en segundo plano), que no han tenido actividad desde que
arrancó tmux. Ante la duda, una ventana no sale: la lista puede quedarse
corta, nunca contar de más. Ninguna va marcada; marcas las que quieras
quitar, **«Cerrar las marcadas»** te pide confirmación, y si en alguna has
lanzado algo mientras tanto, no se cierra. Los slots no se tocan.

### Crear un proyecto o un slot

En la lista de la izquierda de Trabajo: **«+ Proyecto»** arriba, y **«+ Slot
nuevo»** al final de cada proyecto. El slot nuevo se abre solo con Claude dentro
y te lleva a su terminal. Los proyectos sin nada abierto no salen en la lista;
para ellos está **«+ Slot en otro proyecto»**, al final. En el móvil la lista
es el selector de arriba, y ahí hay una sola **«+ Slot nuevo…»**, al final: el
proyecto se elige en el diálogo.

### Retomar una conversación

Cerrar la terminal no borra la conversación: Claude Code la guarda entera. En la
barra del slot, el **«⋯»** → **«Conversaciones anteriores»** lista las de su carpeta, la última
arriba, con su título (o lo primero que pediste) y cuándo fueron.
**«Retomar»** abre una ventana nueva del slot con esa conversación, tal como la
dejaste. La que ya está abierta en una ventana dice «abierta ahora» y te lleva a
ella en vez de abrirla dos veces. Un slot sin ventanas te las ofrece en el
centro de la pantalla.

El asistente tiene lo mismo bajo su chat: **«Chats anteriores»**. «Limpiar»
empieza una conversación nueva y la anterior queda ahí.

Claude Code borra las conversaciones de más de 30 días.

## La pantalla del proyecto: donde se administran los slots

`/proyecto/<id>` — se llega pinchando cualquier proyecto. No sale en el raíl
porque depende de cuál estés mirando, y es donde está todo lo que se puede
hacer con un slot.

**Crear uno a mano**, sin esperar a promoverlo desde la bandeja: «Slot nuevo».
Además del nombre y la ruta, dos campos que conviene conocer:

| Campo | Qué hace |
|---|---|
| `comando` | 🔴 Se **ejecuta** en la ventana al pulsar «Lanzar». Es texto libre: lo que escribas ahí se corre tal cual |
| `autostart_claude` | Si está marcado, la ventana arranca con `claude` |

**Lanzar** abre una ventana de tmux nueva en la ruta del slot, con ese comando
si lo hay. **Editar** cambia todo lo anterior, y su desplegable *mover a* pasa el
slot a otro proyecto conservando su nota.

Los slots se ordenan por su **última actividad**: la última vez que el
muestreo vio trabajando a su agente (Claude Code o Codex). Tener una ventana
abierta no cuenta, y lo que hagas a mano en una shell tampoco se ve desde ahí.

**Archivar** lo quita de la lista y lo conserva entero. **Borrar** lo elimina —y
🔴 **se lleva su nota**, que es lo único del hub que no se reconstruye
escaneando—. Por eso pide confirmación y por eso existe archivar: si sólo
quieres quitarlo de en medio, archívalo.

## La bandeja de entrada

No hay que etiquetar nada al abrir un panel. Trabajas como siempre, y los paneles
que el hub no sabe a qué slot pertenecen caen a la **bandeja**. Cuando quieras,
los promueves a slot, los vinculas a uno existente o los descartas.

Una sesión sale de la bandeja sólo cuando **todas** sus ventanas tienen slot.

Nada de esto caduca ni se archiva solo. Archivar y borrar son acciones tuyas.

## La terminal

Es una terminal de verdad, dentro del navegador, conectada a tus sesiones de
tmux.

- Pulsa un slot y te lleva a **su sesión y su ventana exacta**.
- Las pestañas de arriba son las ventanas: clic para cambiar, `Alt+0..9` para
  saltar, `+` para crear una en la ruta del slot, doble clic para renombrar, `×`
  para cerrar (con confirmación).
- El nombre que pongas **manda** sobre el que Claude Code va reescribiendo, y
  se ve también en el árbol. El que pone el hub al abrir una ventana (el del
  slot) no: ahí manda el título de la conversación. Para volver al automático:
  `tmux set-window-option -t <sesión>:<n> automatic-rename on`
- Cerrar la pestaña del navegador sólo te desata: los procesos siguen vivos,
  igual que un `detach`.
- Si se cae la conexión, se reengancha sola.
- **La barra de encima de la terminal** cabe en una línea. En el PC: el
  nombre del slot y su ruta, la letra (`A−`/`A+`), **«Nota»**, el micrófono
  con su flechita y el **«⋯»**. En el teléfono: el selector (el nombre), el
  micrófono y el «⋯»; la letra y la nota van dentro del «⋯». En el «⋯»
  están también «Conversaciones anteriores», «Reabrir al encender»,
  «Pantalla completa», el reparto (Cómodo, Denso, Foco) y «Ajustar a tmux»,
  con las columnas al pie. Cuando tmux tiene más columnas de las que caben
  (se perderían letras al final de cada línea), sale un aviso sobre la
  terminal, «Caben N de M columnas», con su botón **«Ajustar»**. Los
  mensajes de la conexión y del dictado también flotan sobre la terminal;
  tócalos para quitarlos.
- **Dictar:** el **micrófono** (arriba, y en el móvil también en la barra de
  teclas) graba lo que dices, lo transcribe **en tu máquina** y lo deja escrito en la
  terminal, sin enviarlo: lo lees y pulsas Enter. Sirve para explicarle algo
  largo a Claude Code sin teclearlo. El `/voice` de Claude Code no sirve aquí:
  usa el micrófono de la máquina donde corre `claude`, no el de tu navegador.
  Mientras graba enseña un cuadrado de parar y los segundos; púlsalo otra
  vez para terminar. Es el mismo botón en todo el hub (Tablero, Orquestador,
  chat del secretario).
  Pegada a él, la **flechita** elige qué Whisper lo transcribe (en el
  teléfono, en el «⋯», «Modelo del dictado»): «Ligero» (small,
  el de siempre), «Preciso» (turbo, en la GPU: la mitad de errores, sobre todo
  con nombres y términos técnicos) o «Apagado» (suelta la memoria de la GPU
  y cada frase se transcribe en la CPU, unos segundos más lenta). Dice qué hay
  cargado y cuánta memoria de la GPU está en uso. Lo eliges tú y nada lo
  cambia solo; sólo se eligen los modelos ya descargados (el que falta se
  baja desde el mismo menú: «Dictado: descargar un modelo», abajo). El mismo menú está
  junto al micrófono del Tablero y en el chat del secretario, junto a
  «Opciones». En el Orquestador no: lo que le dictas se transcribe por otro
  camino.

  El dictado conoce tus palabras: a Whisper se le da una lista de términos
  técnicos y los nombres de tus proyectos, y así escribe «worktree» o
  «Tailscale» en vez de algo que suena parecido. Para cambiarla,
  `python -m hub.banco_dictado glosario --sembrar` la deja en
  `voz/glosario.txt` (un término por línea); el mismo comando sin
  `--sembrar` enseña la que se está usando. Sólo se usa al dictar en español.
  Necesita un transcriptor: si preparaste Reuniones, usa el suyo (Whisper);
  si no, la terminal te dice cómo tenerlo. Si no puede usar el micrófono te
  dice por qué (sin permiso, sin micrófono u ocupado por otra aplicación), y
  si la subida falla por un corte de red la reintenta una vez sola.

**No encoge tu terminal nativa.** Cada pestaña usa su propia sesión agrupada
(`hub-<sesión>-<id>`), porque tmux dimensiona una sesión al cliente más pequeño.
Se limpian solas al cerrar.

> ⚠️ Por eso mismo: **no te conectes a una sesión con un ancho distinto desde
> fuera** si te importa su scrollback — tmux lo trunca de forma irreversible.

### Dictado: descargar un modelo

**Dónde:** el menú del modelo del dictado, la flechita pegada al micrófono
(Trabajo y Tablero), «Dictado: …» en el chat del secretario, junto a
«Opciones», o en el teléfono el «⋯» → «Modelo del dictado».

Un modelo que no está en tu máquina sale en el menú como «… — sin descargar», con un
botón **«↓ Descargar (≈1,6 GB)»** debajo (el ligero pesa ≈0,5 GB). Púlsalo: baja
en segundo plano y el menú dice «Descargando…»; puedes cerrarlo y seguir, no
se corta aunque cierres la página. Al acabar queda elegible y lo eliges tú:
nada se elige solo. Va de uno en uno. Si falla (sin red, sin espacio), el menú
dice por qué y el botón vuelve; pulsarlo otra vez sigue donde iba. Turbo sólo
va en una GPU NVIDIA: sin ella no se ofrece bajarlo, porque no se podría usar.
Si el menú dice que no pudo comprobar qué modelos hay, no ofrece nada: vuelve
a abrirlo en un momento.

### Tamaño y presets

Se recuerdan entre sesiones.

| | Letra | Rail | Nota |
|---|---|---|---|
| Cómodo | 14 | sí | sí |
| Denso | 12 | sí | sí |
| Foco | 13 | no | no |

Están en el «⋯» de la barra. Además `A−`/`A+` (9–22) y los bordes entre
paneles se arrastran.

## Slots persistentes: recuperar el trabajo al reiniciar

Un demonio fotografía el estado de tmux cada 20 segundos. Si el servidor de tmux
muere —cerraste WSL, apagaste o reiniciaste el equipo, se fue la luz—, el hub **conserva la última muestra buena**
y te la enseña en la portada: qué paneles tenías, en qué carpetas y con qué
slots.

Es lo que te deja retomar sin reconstruirlo de memoria.

El aviso compara aquella muestra con lo que hay ahora: dice cuántas ventanas
devolvió tmux (si usas tmux-resurrect o tmux-continuum) y cuántas volvieron sin
su agente. Si el corte es de hace más de un día, o tmux lo devolvió todo con su
agente, sale **plegado en una línea**; se abre con un clic, y sólo desaparece
cuando pulsas «Ya lo revisé».

### Marcar un slot como persistente

Un slot **persistente** se reabre cuando vuelves a encender el equipo: la
portada te ofrece **«Reabrir tus slots persistentes»** con un botón **«Abrir N
ventanas»**. Los slots nacen no persistentes; márcalo en los que quieras
conservar: en **Trabajo**, en el **«⋯»** de la barra del slot, enciende
**«Reabrir al encender»**. Un persistente lleva un icono de encendido junto a
su nombre, en la barra y en la lista de la izquierda. (También está la casilla al editar el slot, en
la pantalla del proyecto.)

Reabrir abre cada ventana **en su carpeta** y, en las que tenían Claude Code,
deja escrito **`claude --resume <id>`**: la conversación exacta que tenía esa
ventana. Pulsas Enter y sigues donde estabas. Si no se sabe cuál era, o la
carpeta ya no existe, deja `claude` a secas. Nunca pulsa Enter ni relanza nada
por su cuenta.

Lo que ya está abierto no se vuelve a abrir: si tmux devolvió las ventanas
solo al arrancar (tmux-resurrect o tmux-continuum), el aviso sólo sale para
los slots persistentes que se han quedado sin ninguna ventana, y el botón
cuenta sólo las que faltan.

Para cambiar qué se deja escrito, pon `HUB_RESTAURAR_CLAUDE` en el entorno de
`hub-web`: `reanudar` (por omisión), `nuevo` (un `claude` nuevo) o `nada` (sólo
la carpeta). Si trabajas con otro comando (por ejemplo `claude --model …`),
ponlo en `HUB_COMANDO_CLAUDE` (ver `INSTALAR.md`).

### Salud del hub

Para que el hub pueda reabrir tu trabajo, el muestreo (`hub-snapshotter`) tiene que estar
corriendo **antes**: es quien apunta qué ventanas tenías. En **Máquina →
Salud del hub** ves, con su arreglo, si:

- el muestreo late;
- las mediciones lentas (respaldo de los repos, contenedores, consumo, salud
  del equipo) siguen dando vueltas: se miden aparte, cada diez minutos, sin
  parar el muestreo, y aquí sale un aviso si llevan media hora sin terminar
  una, diez minutos atascadas en un paso o si alguna no se pudo tomar en la
  última vuelta, que es cuando esas cifras se quedan viejas (al despertar el
  equipo de una suspensión sale un rato y se va solo);
- hay tmux abierto;
- tienes algún slot persistente;
- los servicios del hub están en marcha y arrancan solos;
- el hub sigue vivo al cerrar todas las terminales (*linger*);
- la copia diaria de la base está al día (y la de la memoria del secretario, si lo usas).

Si el muestreo se para, **todas las pantallas lo dicen** con un aviso rojo.

**Imágenes y teclas especiales.** Arrastra una imagen sobre la terminal o
pégala con Ctrl+V: se guarda en la carpeta de intercambio del hub, en la de
ese proyecto y slot, y su ruta queda escrita en la terminal, sin enviar, para
que Claude Code la lea. Es de paso: se borra sola a los 10 días. En el
móvil, debajo de la terminal hay una barra con Esc, Ctrl+C, Tab, ⇧Tab, las
flechas, Enter e «Imagen», para adjuntar una foto del teléfono.

> 🔴 **La terminal da acceso de shell a quien alcance el puerto.** Por eso el hub
> escucha sólo en `127.0.0.1` y nunca se pone en `0.0.0.0` ni se expone a
> internet. Para usarlo desde el móvil u otro aparato está [Acceso](/acceso): se
> entra por una red privada (tipo Tailscale) con nombres exactos, cada aparato
> se da de alta con un QR, y la terminal además sólo se abre desde fuera con el
> interruptor «terminal remota», apagado de fábrica y otra vez en cada
> reinicio. Detalle en [`10-mas-pantallas.md`](10-mas-pantallas.md).
