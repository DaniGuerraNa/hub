# Puente KVM

Claude Code, en esta máquina, lee y escribe en un **Mac donde no se puede
instalar nada**, a través de un **JetKVM**: ve la pantalla del Mac (la salida
HDMI) y teclea como un teclado USB. Pensado para un caso concreto: traer un
procedimiento almacenado largo (unas 2.000 líneas) desde el cliente de base de
datos del Mac, trabajar sobre él aquí y devolver los cambios, **sin copiar a mano**.

```
Esta máquina                                            Mac (no se instala nada)
┌─────────────────────────────┐                        ┌──────────┐ HDMI ┌──────────────┐
│ Claude Code ── MCP ──┐      │    red local           │ JetKVM   │◄─────┤ cliente de BD│
│                      ▼      │    WebRTC              │          │      │ (modo        │
│  servicio puente-kvm ───────┼───────────────────────►│          ├─────►│  captura)    │
│  web 127.0.0.1:8794 ◄─ tú   │                        └──────────┘ USB  └──────────────┘
└─────────────────────────────┘
```

## Cómo se usa

Todo se hace en **una sola pantalla: http://127.0.0.1:8794**.

```
┌ Puente KVM · aparato · quién tiene el Mac · [Parar] ───────────────────────┐
│ ┌ el puente ─────────────────────────┐ ┃ ┌ Claude Code ──────────────────┐ │
│ │ pantalla del Mac en directo,        │ ┃ │ aquí le hablas: «lee esta     │ │
│ │ control, lecturas, cambios,         │ ┃ │ función y dime qué hace»,     │ │
│ │ aprobaciones, ajustes               │ ┃ │ «revísala, tarda mucho»…      │ │
│ └─────────────────────────────────────┘ ┃ └───────────────────────────────┘ │
└──────────────────────────────────────── ↔ arrastra para repartir ─────────┘
```

1. **A la derecha está Claude Code**, ya abierto en esta carpeta y con las
   herramientas del puente. La conversación vive en tmux (`puente-claude`):
   recargar la página o reiniciar el servicio no la corta. La primera vez,
   Claude pregunta si confías en la carpeta: contéstale tú.
   - **Sólo carga lo del puente**: sus skills, sus permisos y su servidor, no
     tus conectores, skills, agentes ni plugins personales (gasta bastante
     menos en cada llamada, y lo que lee del Mac no tiene otro camino para
     salir). De tus ajustes de Claude Code se lleva el modelo, el esfuerzo, la
     interfaz, la barra de estado, los avisos al teléfono, lo que tengas
     prohibido y lo que te pregunta. **No sale en el control remoto de
     Claude** aunque lo tengas encendido: es otra forma de manejar una sesión
     que ve el Mac de otro. **Una excepción:** si tus ajustes de Claude Code
     dicen cómo autenticarse (`apiKeyHelper`, `env` u otra), el puente los
     carga enteros para poder arrancar y sólo deja fuera tus servidores MCP y
     lo sincronizado de claude.ai (skills y plugins).
   - **Si Claude Code se cierra**, la terminal se queda en una shell: para
     volver, el menú de la conversación → **Reabrir** (retoma la misma). Un
     `claude` escrito ahí también abre con lo del puente, en el mismo modo.
   - **El modelo** va explícito, por su nombre exacto: por omisión **Fable 5.2**
     (`claude-fable-5-2`, pide Claude Code 2.1.322 o posterior). Se cambia en
     **Ajustes → Modelo de Claude** (Opus 5.5, Sonnet 5, o el que tenga tu Claude
     Code) y vale para la siguiente conversación que se abra. La barra de la
     terminal dice con qué modelo y qué versión de Claude Code corre la abierta.
   - **Conversaciones:** el nombre de la abierta, en la barra, abre la lista:
     nueva (con nombre), cambiar a otra, reabrir, renombrar y quitar de la lista
     (quitar no borra nada de Claude Code). Hay **una sola abierta a la vez**:
     cambiar cierra la abierta (Claude Code la guarda) y el control del Mac
     vuelve a ti; con una lectura o escritura en marcha no se cambia. La lista
     la lleva el puente en `PUENTE_HOME/conversaciones.json`.
2. **A la izquierda, el puente.** Deja el SP abierto en el cliente del Mac y
   pulsa **«Dar el control a Claude»**; mientras, no toques el Mac. **Parar**
   (arriba) corta en el acto. Al terminar cada lectura o escritura, el control
   vuelve solo a ti.
   - **Para usar el Mac tú, sin la web del JetKVM** (que admite una sola
     sesión y desconectaría el puente): **«Usar el Mac desde aquí»**, bajo la
     imagen. Desde ahí, tu teclado y tu ratón van al Mac; un clic fuera de la
     imagen o «Dejar de usar» lo suelta. Con el JetKVM, la imagen es **su vídeo
     tal cual**, como en su web: el puente no lo recomprime y el navegador lo
     pinta a los fotogramas que mande el aparato. Con el Mac simulado, o si el
     navegador no sabe decodificarlo, va por imágenes (unas 11 por segundo
     usándolo, 2 mirando). Por qué: si es cosa del puente (otra versión de
     aiortc, un fallo al pasar el vídeo), la bitácora y `diagnostico`, en
     «Directo»; si es del navegador (sin WebCodecs, un códec que no sabe), su
     consola (F12). Si el aparato se desconecta, vuelven las imágenes, que
     dicen por qué, y el vídeo vuelve solo con él. **Ctrl = ⌘** (marcado de fábrica)
     cambia Ctrl y ⌘ de sitio, porque Windows se queda la tecla ⌘; ⌘Tab y
     ⌘Espacio tienen botón, y «Pegar texto» teclea lo del portapapeles con el
     **teclado del Mac** que eliges a su lado («U.S.», «Español - ISO» o uno medido): si no
     es el que tiene el Mac, los acentos salen cambiados. Sólo funciona
     mientras Claude no tiene el control. Lo que teclees no se guarda en ningún
     sitio.
   - **«Despertar el Mac»**, bajo la imagen: lo saca del reposo, como
     «Intentar despertar» de la web del JetKVM, y dice si volvió la imagen.
     El puente sabe al momento si el Mac está en reposo (se lo dice el JetKVM
     por el USB): la placa de arriba dice «Mac en reposo» y el panel lo avisa,
     y el aviso se va solo en cuanto vuelve la imagen. **«Reconectar»**, a su
     lado, vuelve a conectar con el JetKVM (cierra su web si alguien la tiene
     abierta, y el control vuelve a ti); con una reunión grabándose no deja.
     **«Jiggler»** lo enciende y lo apaga: el JetKVM mueve un poco el ratón
     cuando nadie lo toca, para que el Mac no se bloquee ni te ponga
     «ausente» (lo mueve 1 a 3 píxeles). El botón lo enciende con «Frecuente,
     cada 30 s» (el JetKVM trae «Estándar»); Claude puede ponerle horario («de 9
     a 18 entre semana», con tu zona horaria) si se lo pides. Lo hace el
     aparato, así que **sigue aunque cierres el puente**.
   - Si en el Mac **la rueda va al revés** (el «desplazamiento natural»),
     Ajustes → «Invertir la rueda del ratón».
   - **«⤢ Pantalla grande»**, arriba de la imagen: el Mac ocupa toda la ventana
     del navegador (no el monitor), sin la terminal. Con **− / +** se acerca
     hasta el tamaño real y más (el % es del tamaño real del Mac), y con barras
     o arrastrando te mueves por ella; «Ajustar» vuelve a encajarla. Se puede
     usar el Mac igual. **Esc** o «Salir» vuelve (usando el Mac, Esc va al Mac).
   - **«● Estoy en reunión»**, arriba de la imagen: graba lo que suena en el
     Mac y su pantalla cuando cambia, hasta que pulses **«■ Salí de la
     reunión»**. Tu voz no se graba (entra al Mac por su micrófono y no pasa
     por el JetKVM). Al pararla, Reuniones del hub la transcribe y la resume
     sola. Lo pulsas tú: Claude no tiene herramienta para empezarla ni
     pararla, y sus permisos le niegan leer esa carpeta (una barrera contra
     descuidos, como con la contraseña, no contra quien la salte). En
     el Mac, una vez: Ajustes del Sistema → Sonido → Salida → el dispositivo
     USB del JetKVM (no «JetKVM v1», que es la pantalla); para oírla a la vez,
     un «dispositivo de salida múltiple» en Configuración de Audio MIDI (viene
     con macOS). Hace falta el firmware 0.5.9 o posterior; el puente enciende
     el audio del JetKVM al empezar cada reunión (la imagen se corta unos
     segundos) y lo apaga al terminar.
3. Pídele lo que necesites en la terminal. Lee el documento página a página;
   en la página de la lectura ves **cada captura junto a su transcripción** y la
   comprobación con la **huella** de la base.
4. Si necesita más (las tablas, sus índices, el plan), ábrelo tú en el cliente
   y dile «ya está en pantalla», o deja que escriba la consulta de solo lectura
   y **ejecútala tú**.
5. Cuando proponga un cambio, aparece un aviso abajo a la derecha: **Revisar**
   abre el diff. Nada se escribe hasta que lo apruebas, y nada se guarda en la
   base hasta que lo guardas tú en el Mac. Tras guardar, la huella confirma que
   quedó exactamente lo acordado.

## Preparar el Mac (una vez)

En el cliente de base de datos, un **«modo captura»**:

| Ajuste | Por qué |
|---|---|
| Números de línea visibles | Cada línea leída se ancla a su número |
| Fuente Menlo 16–18 pt, sin ligaduras | Distingue 0/O y 1/l/I |
| Tema claro, sin colorear la sintaxis (o casi) | El color resta contraste |
| **Plegado de código desactivado** | Un bloque plegado esconde líneas |
| Ajuste de línea desactivado; ventana maximizada | Una línea partida no se puede reconstruir sin ambigüedad |
| **Autocompletado, cierre de paréntesis/comillas y sangría automática desactivados** | Si no, al teclear un Enter se acepta una sugerencia o se añade sangría, y lo escrito queda distinto |
| Salida HDMI a 1920×1080; si es portátil, **duplicada** | Si no, el JetKVM ve un monitor vacío |

En macOS, la fuente de entrada activa mientras Claude teclea tiene que ser la
que dice Ajustes → Teclado del puente: **«U.S.»** o **«Español - ISO»** (con el
teclado del JetKVM como ANSI). Si no coinciden, `{ } [ ] | \ ~ @` salen
distintos. Si el Mac usa otra (la latinoamericana, por ejemplo), pídele a
Claude que **calibre el teclado** (skill `calibrar-teclado`), en dos partes:
pulsa cada tecla en un TextEdit vacío y lee lo que sale; después teclea una
consulta de prueba en el programa donde escribes tus consultas (el que sea), tú
la ejecutas y con sus huellas se verifica. Al final pulsas «Usar» en Ajustes. La medida
queda en los datos del puente, no en el repositorio. En Ajustes también están
las **teclas que el puente nunca pulsa** al teclear: de fábrica, Opción+X, que
en DBeaver para Mac ejecuta el script.

Después, en **Ajustes** del puente, marca la región del editor arrastrando
sobre la captura y comprueba los atajos de tu cliente (por omisión, los de
DBeaver: Cmd+L para ir a una línea).

## Arrancar y conectar

Los pasos completos, para seguirlos con Claude Code, están en **`INSTALAR.md`**.
En corto:

```bash
uv sync --frozen
uv run --frozen puente-kvm comprobar --sin-entrar   # qué falta y cómo arreglarlo, sin entrar en el JetKVM
bash scripts/servicio.sh instalar          # servicio de usuario (genera la unidad con la ruta de este clon)
bash scripts/arrancar.sh                   # o, sin systemd, en primer plano
```

Siempre `--frozen`: sin él, uv puede reescribir `uv.lock`, y dentro de otro
repositorio eso es un archivo versionado modificado. `comprobar` sin
`--sin-entrar` entra en el JetKVM para leer su firmware y le cierra su web a
quien la tenga abierta. La web del puente escucha sólo en `127.0.0.1` y **no se
publica ni se reenvía**: dentro hay una terminal con Claude Code.

Por omisión arranca con un **Mac simulado** (un cliente de BD con un SP de
2.017 líneas) para probarlo todo sin el aparato. Para el JetKVM:

1. Pon la contraseña en `~/.config/puente-kvm/entorno` (permisos 600),
   **nunca en los ajustes**: `JETKVM_CLAVE=…`. La pone la persona, no Claude.
2. En **Ajustes**: tipo «JetKVM» y su dirección (`http://192.168.x.x`).
3. Ojo: el JetKVM admite **una sola sesión**. Si abres su web en un navegador,
   el puente queda fuera (y al revés). La pantalla lo dice.

**Al actualizar**, si el puente sigue con el código de antes, su pantalla lo
avisa arriba con dos botones: «Reiniciar el puente» y, después, «Reabrir la
conversación de Claude» (sin systemd, el aviso dice el comando). Lo cuenta
`INSTALAR.md`, «Actualizar».

La primera vez con el aparato: **`docs/pruebas-con-el-aparato.md`**. Si algo
falla, `uv run --frozen puente-kvm diagnostico` deja un informe sin secretos
ni contenido del trabajo para mandar. Desde un espacio de trabajo fuera del
código (`PUENTE_TRABAJO`), las órdenes van con
`uv run --directory "${PUENTE_CODIGO:-.}" --frozen puente-kvm …`.

## Probar

```bash
uv run --frozen pytest
```

Prueba el recorrido completo contra el Mac simulado (leer, verificar, aprobar,
escribir, verificar), las puertas (sin control no se toca nada; Claude no puede
aprobar ni darse el control; Parar corta a mitad; cambiar de aparato devuelve
el control; antes de escribir se comprueba que el documento sigue siendo el
leído) y el cliente del JetKVM contra un JetKVM falso que habla su protocolo
por WebRTC de verdad.

## Medido hasta ahora (con el Mac simulado)

- **Leer por visión funciona en limpio:** las 2.017 líneas del SP de muestra,
  capturadas en 57 páginas y transcritas por Claude (6 subagentes en paralelo,
  sólo mirando las capturas), salieron **exactas a la primera**: la huella
  coincidió byte a byte (SHA-256 sobre UTF-16-LE con CRLF, como SQL Server), sin
  conflictos ni huecos. Ojo: eran capturas sin pérdida del simulador. Con el
  vídeo H.264 del aparato y la fuente real del Mac hay que volver a medirlo.
- **Escribir funciona:** un cambio de 4 tramos (insertar, reemplazar, añadir al
  final) aprobado y escrito desde el navegador dejó el editor exactamente con el
  texto acordado, y la huella tras guardar coincidió.
- **El cliente del JetKVM** conecta, recibe vídeo H.264, teclea, hace clic y
  usa la rueda contra un JetKVM falso que habla el protocolo del firmware.
  Diferencia entre la pantalla y el fotograma H.264 decodificado: 0,8 % en el
  peor cuadro de 64×32 px, por debajo del umbral del 3 %.
- **La comprobación antes de escribir** (recorrer el documento hasta el tramo
  más bajo y comparar cada página con la lectura) cuesta unos 0,21 s por página
  con el simulador: 0,2 s para un tramo en la primera página, 6,0 s en la
  línea 1.000 y 12,3 s en la última de 2.017 (13-nov).
- **Reiniciar con el botón** (con systemd, en una unidad de prueba): la página
  vuelve a los 0,7 s sin nadie mirando el directo, y a los 5,7 s con otra
  pestaña mirándolo por imágenes, porque el directo de imágenes no termina
  mientras se mira y el puente lo corta a los 5 s al parar (el de vídeo, con el
  JetKVM, se cierra en el acto al parar); sin ese tope, esperaba al `TimeoutStopSec` de
  systemd (90 s por omisión: el stop de 93 s del 17-nov). Recorrido en un
  navegador de verdad, de pulsar a la página recargada con el código nuevo:
  1,2 s (20-nov).

- **El directo** (C-0469), contra el JetKVM falso y con el mismo arnés antes y
  después (`uv run --frozen python -m tests.medir_directo`): de 10,7 a 30
  fotogramas pintados por segundo usando el Mac (de 2 a 30 mirando), el
  puntero de 204 a 83 ms de p50 y de 270 a 97 de p95, y la CPU del puente de
  30 % a 15 % (22-nov). Es la cifra del falso en este equipo, no la del aparato.

## Lo que aún no se ha medido con el aparato

El cliente del JetKVM sigue el código de su firmware, contrastado con 0.5.9,
0.5.10 (la última estable) y 0.5.11 (`docs/protocolo-jetkvm.md`), pero no se ha
conectado a uno real. En la primera prueba hay que medir:

1. Que conecta y llega el vídeo (H.264), y a qué resolución.
2. Cuántas líneas por captura se leen sin errores con tu cliente y tu fuente.
3. Si «Av Pág» avanza exactamente una página en tu cliente y si «Ir a la línea»
   deja el cursor en la columna 1.
4. Si la huella de la base coincide con lo que enseña el editor (algunos
   clientes añaden `CREATE OR ALTER` al abrir).
5. La pausa entre teclas a partir de la cual no se pierde ningún carácter.
6. El ruido del vídeo: el umbral para «la pantalla no cambió» está calibrado
   con H.264 local, no con el del aparato.
7. Si el diálogo de «Ir a la línea» del cliente se ve en pantalla lo bastante
   grande (4 cuadros de 64×32) para que el puente lo dé por abierto.
8. Cuánto tarda la comprobación antes de escribir, por página.
9. Lo fluido que va el directo con su vídeo de verdad (`/panel?medir=1`,
   paso 12 de `docs/pruebas-con-el-aparato.md`).
