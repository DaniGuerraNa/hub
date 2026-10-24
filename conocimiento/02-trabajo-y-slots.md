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
clic para renombrarla, **×** para cerrarla y **«+ Ventana»** para abrir otra en
la carpeta del slot. Las ventanas que no son de ningún slot están al final, en
«Sin organizar». En el escritorio el árbol sustituye a las pestañas de encima
de la terminal; con el raíl plegado, a pantalla completa o en el móvil vuelven
las pestañas.

### Crear un proyecto o un slot

En la lista de la izquierda de Trabajo: **«+ Proyecto»** arriba, y **«+ Slot
nuevo»** al final de cada proyecto. El slot nuevo se abre solo con Claude dentro
y te lleva a su terminal. Los proyectos sin nada abierto no salen en la lista;
para ellos está **«+ Slot en otro proyecto»**, al final.

### Retomar una conversación

Cerrar la terminal no borra la conversación: Claude Code la guarda entera. En la
cabecera del slot, **«Conversaciones»** lista las de su carpeta, la última
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
- El nombre que pongas **manda** sobre el que Claude Code va reescribiendo. Para
  volver al automático:
  `tmux set-window-option -t <sesión>:<n> automatic-rename on`
- Cerrar la pestaña del navegador sólo te desata: los procesos siguen vivos,
  igual que un `detach`.
- Si se cae la conexión, se reengancha sola.
- **Dictar:** el botón «Dictar» (arriba, y en el móvil en la barra de teclas)
  graba lo que dices, lo transcribe **en tu máquina** y lo deja escrito en la
  terminal, sin enviarlo: lo lees y pulsas Enter. Sirve para explicarle algo
  largo a Claude Code sin teclearlo. El `/voice` de Claude Code no sirve aquí:
  usa el micrófono de la máquina donde corre `claude`, no el de tu navegador.
  Necesita un transcriptor: si preparaste Reuniones, usa el suyo (Whisper);
  si no, la terminal te dice cómo tenerlo.

**No encoge tu terminal nativa.** Cada pestaña usa su propia sesión agrupada
(`hub-<sesión>-<id>`), porque tmux dimensiona una sesión al cliente más pequeño.
Se limpian solas al cerrar.

> ⚠️ Por eso mismo: **no te conectes a una sesión con un ancho distinto desde
> fuera** si te importa su scrollback — tmux lo trunca de forma irreversible.

### Tamaño y presets

Se recuerdan entre sesiones.

| | Letra | Rail | Nota |
|---|---|---|---|
| Cómodo | 14 | sí | sí |
| Denso | 12 | sí | sí |
| Foco | 13 | no | no |

Además `A−`/`A+` (9–22) y los bordes entre paneles se arrastran.

## Slots persistentes: recuperar el trabajo al reiniciar

Un demonio fotografía el estado de tmux cada 20 segundos. Si el servidor de tmux
muere —cerraste WSL, apagaste o reiniciaste el equipo, se fue la luz—, el hub **conserva la última muestra buena**
y te la enseña en la portada: qué paneles tenías, en qué carpetas y con qué
slots.

Es lo que te deja retomar sin reconstruirlo de memoria.

### Marcar un slot como persistente

Un slot **persistente** se reabre cuando vuelves a encender el equipo: la
portada te ofrece **«Reabrir tus slots persistentes»** con un botón **«Abrir N
ventanas»**. Los slots nacen no persistentes; márcalo en los que quieras
conservar: en **Trabajo**, en la cabecera del slot, pulsa **«↻ No persistente»**
y pasa a **«↻ Persistente»**. En la lista de la izquierda, los persistentes
llevan un **↻** junto al nombre. (También está la casilla al editar el slot, en
la pantalla del proyecto.)

Reabrir abre cada ventana **en su carpeta** y, en las que tenían Claude Code,
deja escrito **`claude --resume <id>`**: la conversación exacta que tenía esa
ventana. Pulsas Enter y sigues donde estabas. Si no se sabe cuál era, o la
carpeta ya no existe, deja `claude` a secas. Nunca pulsa Enter ni relanza nada
por su cuenta.

Para cambiar qué se deja escrito, pon `HUB_RESTAURAR_CLAUDE` en el entorno de
`hub-web`: `reanudar` (por omisión), `nuevo` (un `claude` nuevo) o `nada` (sólo
la carpeta). Si trabajas con otro comando (por ejemplo `claude --model …`),
ponlo en `HUB_COMANDO_CLAUDE` (ver `INSTALAR.md`).

### Salud del hub

Para que el hub pueda reabrir tu trabajo, el muestreo (`hub-snapshotter`) tiene que estar
corriendo **antes**: es quien apunta qué ventanas tenías. En **Máquina →
Salud del hub** ves, con su arreglo, si:

- el muestreo late;
- hay tmux abierto;
- tienes algún slot persistente;
- los servicios del hub están en marcha y arrancan solos;
- el hub sigue vivo al cerrar todas las terminales (*linger*);
- la copia diaria de la base está al día.

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
