# La pantalla de trabajo, los slots y la terminal

`/trabajo` es donde vas a pasar el día: **slots a la izquierda, terminal en
medio, nota a la derecha**.

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

## La pantalla del proyecto: donde se administran los slots

`/proyecto/<id>` — se llega pinchando cualquier proyecto. Es la **octava
pantalla**, no sale en el raíl porque depende de cuál estés mirando, y es donde
está todo lo que se puede hacer con un slot.

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

## Recuperación tras un corte

Un demonio fotografía el estado de tmux cada 20 segundos. Si el servidor de tmux
muere —se cerró WSL, se apagó la PC—, el hub **conserva la última muestra buena**
y te la enseña en la portada: qué paneles tenías, en qué carpetas y con qué
slots.

Es lo que te deja retomar sin reconstruirlo de memoria.

> 🔴 La terminal da acceso de shell a quien alcance el puerto. Escucha sólo en
> `127.0.0.1`. No la expongas sin autenticación.
