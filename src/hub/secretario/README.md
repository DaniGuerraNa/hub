# Mapa del secretario

Qué pieza hace qué, y por dónde pasa cada cosa. 🔴 **Una pieza nueva no se da
por terminada sin su línea aquí** (decisión 309): con la IA, escribir el código
es lo barato, y lo que pesa con los años es mantener un sistema que nadie
recuerda cómo está armado.

El porqué de cada decisión está en `ARQUITECTURA.md` §11 (298-323); el uso, en
`producto/conocimiento/13-secretario.md`.

## La regla de las piezas

**El secretario sólo conoce contratos, nunca a quien los cumple** (decisiones
300 y 306). Siempre es el mismo camino:

```
secretario ──► herramienta / fachada ──► contrato ──► implementación concreta
 (modelo)       (buscar, agenda,          (Fuente,      (fuentes/telegram.py,
                 avisos.mandar)            Calendario,    agenda/google.py,
                                           Canal)         avisos/telegram.py)
```

Cambiar la implementación —Telegram por otra forma de leerlo, Google por otro
calendario, Telegram por Web Push para avisar— es añadir o cambiar **un
archivo** al final de la cadena. El prompt, las herramientas, las acciones y
los tests de los demás no se tocan. Si un cambio así obliga a tocar algo de
más arriba, el contrato está mal y se arregla el contrato.

Hay tres formas, según cuántas se usan a la vez:

| Forma | Cuántas | Contrato | Se elige en | Fachada |
|---|---|---|---|---|
| **Fuente** | todas las encendidas | `piezas.Fuente`: `disponible`, `conversaciones`, `leer` | pestaña Fuentes (`fuentes.yml`) | la memoria: `buscar`, `recientes`, `mensaje` |
| **Capacidad** | una (o una cadena, en avisos) | `agenda.Calendario`, `avisos.Canal` (base `piezas.Proveedor`) | `secretario.yml` (`agenda: google`, `avisos: [webpush, telegram]`) | `agenda.eventos/crear`, `avisos.mandar` |
| **Acción** | todas, cada una con su nivel | `piezas.Accion`: `riesgo`, `nivel_inicial`, `ejecutar` | pestaña Confianza (`permisos.yml`) | `herramientas.usar_accion` (mira el nivel) |

Todas se descubren solas: un archivo en `fuentes/`, `acciones/` o en la
carpeta de la capacidad, con `FUENTE`, `ACCIONES` o `PROVEEDOR` dentro.

## Los archivos

| Archivo | Qué hace | LLM |
|---|---|---|
| `servicio.py` | El bucle de `hub-secretario`: un hilo contesta, otro hace el ciclo de 30 s | — |
| `memoria.py` | La base propia (`memoria.db`): eventos con FTS, notas, compromisos, hilos, turnos, solicitudes, bitácora; y la cola de lo que se hace aparte (`encolar`, `sacar`) | — |
| `piezas.py` | Los contratos, el descubrimiento y los niveles de confianza | — |
| `tiempo.py` | La zona de la máquina; todo se guarda en UTC | — |
| `fuentes/hub.py` | Lee reuniones con resumen y notas de slots | — |
| `fuentes/telegram.py` | Lee la cuenta de Telegram del dueño (Telethon) | — |
| `fuentes/correo.py` | Lee el correo por IMAP en sólo lectura (`EXAMINE`, `BODY.PEEK`); sin boletines | — |
| `fuentes/whatsapp_exportado.py` | Los chats que el dueño exporta a mano («Exportar chat»): sin cliente conectado, sin riesgo para la cuenta; Android e iPhone, es/en (decisión 326) | — |
| `fuentes/whatsapp.py` | **Provisional** (decisión 323): lee el JSONL que vuelca el colector de WhatsApp Web (`componentes/whatsapp-web/`); cursor por byte e inodo; `disponible` mira su latido | — |
| `resumen.py` | El resumen del día armado por script: agenda, hoy, vencidos, permisos, notas; su «Te espera» sale de `asuntos` | — |
| `asuntos.py` | Lo que espera del dueño (379, 380): lee en vivo de cada dueño —solicitudes, orquestador, avisos, canal, fichas, `bloqueado_por` de cada proyecto, compromisos que vencen— y guarda en la tabla `asunto` sólo lo propio (relevo, proyecto, dato) y sus marcas. Nunca avisa al teléfono; `recalcular` deja la cuenta en `estado['asuntos']` cada vuelta. `pedir_relevo` (388): lo que sólo él hace en la PC, un asunto `relevo` que se le abre en la PC por el agente de Reuniones (`relevo_en_pc`, encendido por omisión), una vez abierta por asunto. **Anotar y delegar tienen una sola regla** (381): `como_delegar`, `anotar` y `delegar` las dicen el botón de «Te espera» y el modelo (`comprometer` y `encargar_al_orquestador` con `asunto`): sólo bloqueos, ni lo ya decidido ni lo callado, nada sobre un `never`, lo legal o sin alcance sólo preparado, y la marca antes de crear la tarea. `responder` sólo contesta lo de un proyecto, y le vuelve por `de_proyectos.devolver` | — |
| `de_proyectos.py` | Lo que un proyecto registrado le dice al dueño (387): `dejar` lo pone en la cola `HUB_HOME/secretario/de-proyectos/<proyecto>/` (lo usa `proyecto-dice`) y `recoger`, en el ciclo, lo lleva a su sitio: un `pendiente`, a compromiso suyo (al teléfono sólo con `de_proyectos.<id>.recordar`; `marca` lo señala como dato donde los compromisos entran solos al modelo); `pregunta` y `aviso`, a asunto `proyecto`. Lo roto, a `.rotos/`. La vuelta: `devolver` deja lo que contestó el dueño en `<proyecto>/respuestas/<clave>.json` (atómico, tapado) y `respuestas` lo lee (lo usa `proyecto-respuestas`) | — |
| `misdatos.py` | Sus datos para los trámites («mis datos», 382): campos cerrados en `mis-datos.yml` (600, fuera de `memoria.db`), de propuesto a confirmado sólo por su botón; `aparece_en` dice si lo que sale lleva uno, y entonces la acción pide permiso | — |
| `agenda/` | Capacidad agenda; `google.py` (urllib + OAuth, lee y crea) e `ical.py` (dirección secreta iCal, sólo lee; decisión 327) | — |
| `avisos/` | Capacidad avisos, en cadena (`webpush` y, de respaldo, `telegram`) | — |
| `avisos/webpush.py` | Web Push a la app: claves VAPID, aparatos, envío y 404/410 | — |
| `avisos/telegram.py` | Deja timbres que manda `hub-canal` | — |
| `cifrado_push.py` | RFC 8291 (cifrado) y RFC 8292 (VAPID), probado contra el apéndice A | — |
| `acciones/memoria.py` | Anotar, comprometer (con `asunto`, lo deja anotado), cerrar y reprogramar compromisos, y callar un asunto | — |
| `acciones/datos.py` | Proponer un dato suyo para «mis datos»: queda propuesto y es un asunto `dato:<campo>` hasta que él lo confirme | — |
| `acciones/agenda.py` | Poner algo en el calendario (por la fachada `agenda`) | — |
| `acciones/avisar.py` | Avisar al teléfono (por la fachada `avisos`) | — |
| `acciones/proyectos.py` | Crear proyecto, registrar uno existente, crear slot: **las mismas funciones del hub** (`agentes`, `slots`) | — |
| `acciones/hub.py` | Encargar trabajo de varios pasos al orquestador, con `proyecto` (su aprobación es el sí de la 279), los adjuntos del hilo y el `asunto` que delega (381, 384) | — |
| `acciones/pc.py` | Abrir una pantalla del hub en la PC (por el agente de Reuniones), la ventana de un slot, y grabar o parar una reunión con los ajustes de la última vez | — |
| `acciones/tele.py` | La tele: encender, apagar, entrada por nombre, abrir una app y mirar su estado; config en `secretario.yml` → `tele:` | — |
| `roku.py` | Cliente ECP de Roku (HTTP saliente al 8060 de la tele, urllib, lista cerrada de teclas) | — |
| `archivos.py` | Leer, listar y buscar en los proyectos registrados del hub (sólo lectura, sin llaves) | sí (lo leído) |
| `herramientas.py` | Lo que el modelo puede usar: lecturas y `accion_*`; aquí se mira el nivel. La tarjeta `imagenes` (sólo raster del intercambio) y `ver_imagen`, que le enseña al modelo lo adjunto o la evidencia de una tarea (384). `diagnosticar_pc` lee Windows y la red por `hub.diagnostico`, en sólo lectura y resumido (decisión 386) | — |
| `personaje.py` | El vocabulario cerrado de su personaje: gestos, roles, estados, quién es y su pose (358, 377), y los puestos del modo monitor con el de cada estado y gesto (389) | — |
| `mcp.py` | Expone `herramientas` por MCP (stdio, JSON-RPC a mano); una `Imagen` va como `content` de tipo `image` (384) | — |
| `triaje.py` | Filtro por script → Haiku saca notas y compromisos de lo nuevo | **sí** (lo que pasa el filtro) |
| `conversacion.py` | Hilos, turnos y cierre con resumen; los adjuntos del chat (`guardar_adjunto`, decisión 383) | **sí** |
| `enrutador.py` | Qué modelo y esfuerzo para cada trabajo: una tabla, no un modelo | — |
| `motor.py` | La costura del modelo (`Motor`; `motor:` en `secretario.yml`). Hoy `suscripcion`: `claude -p`, con el proceso de la conversación abierto entre turnos. Imágenes y PDF como bloques en ese mismo proceso (383). Con `nativas`, sólo `WebSearch` y `WebFetch` y nunca con su MCP; con `tope_usd`, `--max-budget-usd` (385) | — |
| `sesiones.py` | Resumir una sesión de trabajo larga: lo encarga la conversación y lo hace el hilo aparte del servicio (C-0163) | **sí** (la sesión) |
| `investigar.py` | Investigar lo público en la web (385): lo encarga la conversación (`investigar`) y lo hace el hilo aparte, con sólo buscar y leer, sin su MCP y con tope; vuelve al chat enmarcado, con fuente y fecha por dato, tarjeta de fuentes y nota | **sí** (lo leído en la web) |
| `delegados.py` | Lo que delegó vuelve a su chat (384): en cada vuelta, las tareas suyas del orquestador ya cerradas, una vez por cierre, con el resumen enmarcado como dato y sus evidencias en una tarjeta `imagenes`; al estrenarlo, lo ya cerrado se apunta sin decirse (`estado['delegados_contados']`). Si era un asunto delegado (`asuntos.delegado_en`), la cabecera dice qué punto era y quién lo delegó; todo va tapado (`misdatos.tapar`) | — |
| `recordatorios.py` | Manda lo que toca a su hora | — |
| `disparadores.py` | «Cuando pase X, haz Y»: por mensaje, horario o estado | sólo `pide` |
| `__main__.py` | CLI: `servicio`, `vuelta`, `preguntar`, `estado`, `asuntos [--todos]`, `asuntos reabrir CLAVE`, `proyecto-dice` y `proyecto-respuestas` (387), `relevo` (388), `telegram-entrar`, `correo-entrar`, `google-entrar`, `whatsapp entrar\|escuchar\|comprobar` | — |

Fuera de esta carpeta: `componentes/whatsapp-web/` (el colector de WhatsApp en Node, proceso aparte: el único que abre esa sesión), `diagnostico.py` (el diagnóstico de la PC con Windows y su red, que lee `diagnosticar_pc`), `api.py` (`secretario_*`, lo que lee la pantalla),
`web.py` (rutas `/secretario…` y `/api/secretario/…`), `templates/secretario.html`
(la app en tres tamaños, decisión 312), `static/secretario.js` (conversación,
voz, activar avisos, teclado del iPhone), `static/secretario-sw.js` (el service
worker: sólo avisos, sin `fetch`) y el modo monitor: `templates/secretario_monitor.html`
y `static/escenario-secretario.js` con su `.css` (`/secretario/monitor`, decisión 389).

## LLM o script (decisión 308)

**El modelo sólo interpreta lenguaje libre o redacta para el dueño.** Todo lo
que tiene una respuesta determinista es script: leer, deduplicar, buscar,
fechas, recordatorios, disparadores por mención u horario, elegir el modelo,
ejecutar lo aprobado. Antes de añadir una llamada al modelo, la pregunta es
si un script lo resuelve igual; si sí, va por script.

## El recorrido de un mensaje

1. **Ciclo** (`servicio.leer_fuentes`): cada fuente encendida cuyo intervalo
   pasó devuelve eventos → `memoria.guardar_evento` (tapa lo que parece una
   llave, deduplica por `fuente + id_externo`).
2. **Disparadores por evento** sobre lo que acaba de entrar.
3. **Triaje**: el filtro descarta cortesías (`triado = 3`); el resto va en
   lotes de 30 a Haiku, que devuelve notas y compromisos.
4. **Recordatorios**: los compromisos con `recordar_en` vencido salen por
   `avisos.mandar`.
5. **Conversación**: el dueño escribe en `/secretario` → `hub-web` deja el
   turno en la base → el hilo de conversación lo ve en ≤1 s, llama a Sonnet
   con las herramientas por MCP, guarda la respuesta → la pantalla la recoge.
   Lo adjunto sube antes (`/api/secretario/adjuntar` → intercambio, de paso)
   y el turno lleva sus rutas: imágenes y PDF van al modelo como bloques; de
   lo demás, la ruta, marcada como dato (decisión 383).
6. **Acción en `ask`**: queda una solicitud y un aviso → el dueño aprueba en
   la web o desde el aviso (`/api/secretario/solicitud/{id}`, lo llama el
   service worker) → el ciclo la ejecuta (este servicio tiene las llaves;
   `hub-web` no).

## Dónde vive cada dato

| Qué | Dónde | Se reconstruye |
|---|---|---|
| Memoria, notas, compromisos, bitácora | `HUB_HOME/secretario/memoria.db` (copia diaria `secretario-*`) | **no** |
| Fuentes, niveles, disparadores, ajustes | `HUB_HOME/secretario/{fuentes,permisos,secretario,modelos}.yml`, `disparadores.yml` | no (son del dueño) |
| Aparatos con avisos | tabla `suscripcion` de `memoria.db` | sí: «Activar avisos aquí» otra vez |
| Lo que dejan los proyectos, por recoger | `HUB_HOME/secretario/de-proyectos/<proyecto>/*.json` (lo roto, en `.rotos/`; lo leído se borra) | no; ya recogido, está en `memoria.db` |
| Sus datos para los trámites (mis datos) | `HUB_HOME/secretario/mis-datos.yml` (600) | **no**; tampoco va en la copia diaria, a propósito: olvidar la quita sin dejar copia de la ficha (382). Lo dicho en el chat y lo ya aprobado quedan en la memoria |
| Lo adjunto en el chat | `HUB_HOME/intercambio/_secretario/<día>/` (de paso: se borra a los 10 días; la ruta, en `turno.adjuntos`) | no; tampoco va en la copia diaria |
| Llaves de Telegram, correo, Google y Web Push | `~/.secretos/secretario-{telegram,correo,google,webpush}/` | no; sólo las abre `hub-secretario` |
| Lo que vuelca el colector de WhatsApp | `HUB_HOME/secretario/whatsapp/{mensajes.jsonl,chats.json,estado.json}` | no (lo leído ya está en `memoria.db`) |
| Sesión de WhatsApp | `~/.secretos/secretario-whatsapp/` (`HUB_SECRETARIO_WHATSAPP`) | no; sólo la abre el colector, ni `hub-secretario` ni `hub-web` |
