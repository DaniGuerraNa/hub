# Conocimiento del hub

Documentación de uso. Cada pieza contesta un tipo de pregunta; abre sólo la que
haga falta.

| Documento | Contesta |
|---|---|
| [`01-el-registro.md`](01-el-registro.md) | Cómo declaro mis proyectos, mis repos, mis contenedores y mis conexiones |
| [`02-trabajo-y-slots.md`](02-trabajo-y-slots.md) | Qué son los slots, la bandeja y las notas, y cómo uso la terminal |
| [`03-mediciones.md`](03-mediciones.md) | Qué mide el hub exactamente y cómo se leen sus cifras |
| [`04-kits.md`](04-kits.md) | Qué es un kit, cómo se aplica, cómo se hace uno |
| [`05-el-asistente.md`](05-el-asistente.md) | Qué es el chat, qué puede y qué no, y cómo te guía si empiezas |
| [`06-problemas.md`](06-problemas.md) | Algo no funciona |
| [`07-la-api.md`](07-la-api.md) | Leer lo que el hub mide desde un script |
| [`08-sala-limpia.md`](08-sala-limpia.md) | Probar una instalación del hub o de un kit como la vería otra persona, y auditar un kit |
| [`09-orquestador-e-intercambio.md`](09-orquestador-e-intercambio.md) | Mandar trabajo a las sesiones sin estar delante, sus permisos, y pasar archivos desde el teléfono |
| [`10-mas-pantallas.md`](10-mas-pantallas.md) | Entrar desde el móvil (Acceso), Telegram (Canal, avisos, pánico y Encargos), las pestañas Lienzos, Consultas y Programados de Trabajo, Archivos y comandos preparados, Máquina, Consumo y los atajos |
| [`11-versiones.md`](11-versiones.md) | Qué versión tengo, cómo me entero de que hay otra, cómo actualizo y qué significa «falta terminar de actualizar» |

🔴 **Si la pregunta es «¿puedo abrir el puerto a la red?», la respuesta es no**, y
no hace falta abrir ningún documento para decirlo: la pantalla `/terminal` da
acceso de shell, así que el hub escucha sólo en `127.0.0.1` y nunca se pone en
`0.0.0.0` ni se expone a internet. Es la pregunta donde improvisar hace daño.

Pero si la pregunta es **«¿puedo usarlo desde el móvil?»**, la respuesta es sí,
por otro camino: [Acceso](/acceso) — una red privada, nombres exactos, cada
aparato dado de alta con un QR y la terminal tras su propio interruptor. Está en
[`10-mas-pantallas.md`](10-mas-pantallas.md).

**Por dónde empiezo / dónde está cada pantalla:** no hay un documento aparte:
lo da la pantalla [`/guia`](/guia) (o `GET /api/guia`), medido contra el
estado real. El asistente lo lee con `hub guia`. El comando `hub` existe en tu
terminal desde que se siembra el asistente (queda en `~/.local/bin/hub`).

## Si eres Claude y te preguntan por el hub

Lee **este índice primero** y abre sólo el documento que toque. Si la respuesta
no está en ninguno, dilo — es mejor que deducirla.

Lo que **no** vas a encontrar aquí es por qué el hub está diseñado así: eso vive
en el repositorio de quien lo mantiene. Si la pregunta es «¿por qué no hace X?»,
la respuesta honesta es que no lo sabes.
