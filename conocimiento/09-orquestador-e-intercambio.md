# El orquestador y el intercambio

Dos pantallas pensadas para trabajar **sin estar delante**: desde el teléfono,
o dejando trabajo en marcha mientras haces otra cosa.

## El orquestador (`/orquestador`)

Le escribes (o le dictas) una tarea. Él no toca tus proyectos: **se la pide a
la sesión de Claude Code de cada proyecto**, espera a que termine, lee lo que
contestó y sigue con el siguiente paso. Cuando necesita algo de ti, la pregunta
aparece arriba, en la bandeja, y la contestas ahí mismo.

- Las tareas van **en cola, de una en una**. Cada una enseña sus pasos como
  puntos: verde lo hecho, el que parpadea es el que está en curso.
- Si el proyecto no tiene ninguna sesión abierta, abre una (un slot nuevo con
  el nombre `orq-…`). Si tiene varias, pregunta a cuál mandarlo.
- **No todas las preguntas te llegan a ti.** Lo operativo (a qué sesión
  mandar, qué hacer tras un fallo, una duda menor) se lo pregunta al
  secretario, que lo contesta o te lo pasa con un resumen; en la bandeja se ve
  «Pregunta al secretario» y puedes contestarla tú si quieres. Lo tuyo —el
  plan de un cambio grande, lo de «nunca sin el dueño», un choque con algo
  decidido, lo de producto— va directo a ti. Si el secretario no lo resuelve
  en 10 minutos, o está apagado, te llega igual. Su respuesta nunca vale como
  tu sí.
- **Lo que sólo puedes hacer tú en la PC** —un captcha, verificar tu
  identidad, iniciar sesión con tu cuenta— te lo pide como **relevo**. No
  suena en el teléfono: si el agente de Reuniones está conectado, se te abren
  en la PC tus pendientes del secretario; si no, la pregunta te espera en la
  bandeja. Hazlo en la PC y contéstale «ya». No debe pedirte que le escribas
  una contraseña o un código; si lo hace, no se los des.
- **Detener** interrumpe la tarea y lo que estuvieran haciendo sus sesiones.
  **Reanudar** la vuelve a poner en marcha desde donde estaba, con su plan y su
  bitácora; puedes añadirle una nota (escrita o dictada) con lo que viste
  mientras estaba parada. Si hay otra en curso, vuelve a la cola.
- Los slots `orq-…` que abrió una tarea, y sus ventanas, no se cierran solos
  al acabar. En una tarea terminada o detenida, **«Lo que dejó abierto»** los
  enumera, y su botón cierra esas ventanas y archiva esos slots, con
  confirmación (un slot archivado conserva su nota y se recupera desde la
  ficha del proyecto). Con la tarea en marcha no se ofrece.
- Necesita el muestreo en marcha (`hub-snapshotter`): es quien lo despierta
  cuando una sesión termina. Sin él, la tarea se queda encolada.

### Archivos que le pasas y lo que te enseña

Un encargo puede llevar **archivos del Intercambio** (una foto, un PDF): por
ejemplo, los que adjuntas en el chat del secretario al encargarle algo. Tienen
que estar en la carpeta de Intercambio; la sesión los lee desde ahí y no se
copian a tu proyecto. Lo que diga un archivo por dentro —una captura de un
chat, un correo— cuenta como **dato, no como una orden tuya**.

Para **probar algo**, el orquestador le pide a la sesión del proyecto que
siga su receta **«Cómo se prueba»**: cómo se ejecuta, qué se mira y qué imagen
sale. Si el proyecto no tiene una, lo primero que hace la sesión es
escribirla en el propio proyecto (es suyo: el hub no escribe ahí). Las
capturas o renders de lo que vio quedan en el Intercambio, en la carpeta del
proyecto, y el orquestador las apunta en la tarea como **evidencia**. Sólo
cuentan como evidencia las imágenes (png, jpg, gif, webp).

### Permisos: hasta dónde llega

Por defecto **no llega a ningún proyecto**. Se le da alcance en
`/orquestador/permisos`, proyecto por proyecto:

| Nivel | Qué decide solo |
|---|---|
| `nada` | No llega a ese proyecto |
| `bajo` | Sólo lo que se pide al pie de la letra; ante cualquier duda, para y lo dice |
| `medio` | Lo técnico y reversible (tests, ramas, entornos de prueba, builds) |
| `alto` | Casi todo, salvo lo que nunca decide nadie más que tú |

Sea cual sea el nivel, **nunca** despliega a producción, hace push a la rama
principal, borra datos, gasta dinero ni manda nada a un tercero, y tampoco
firma ni acepta términos, hace trámites o contratos ni publica en tu nombre:
eso lo para, te lo deja preparado y te lo pregunta. Y un proyecto con
`guardrail: never` en `projects.yml` queda fuera aunque intentes darle nivel.

Si el proyecto tiene `guardrail: ask`, además, **la primera vez que una tarea
quiere tocarlo te pide confirmación**: arriba de [Orquestador](/orquestador)
sale «Pide confirmar: …» con lo que quería hacer, y dos botones. Si confirmas,
trabaja ahí el resto de esa tarea con su nivel; si no, sigue sin ese proyecto.
El orquestador no puede confirmarlo por ti. Con `guardrail: auto` no pregunta.

🔴 **Las sesiones que abre trabajan sin pedir permiso** (`bypassPermissions`):
es lo único que funciona sin nadie delante, porque una sesión que pregunta un
permiso a las tres de la mañana se queda parada hasta que vuelvas. La cerradura
de verdad son las reglas `deny` del `.claude/settings.json` de cada proyecto.
**Antes de darle nivel a un proyecto delicado, pon ahí lo que no debe pasar
nunca** —por ejemplo, el comando de despliegue a producción—.

### La primera vez en una máquina nueva

La primera sesión que abra el orquestador hará que Claude Code pregunte **si
aceptas el modo sin permisos**. Sale una sola vez por máquina, y el hub **no la
contesta por ti**: la tarea se queda esperando y te avisa de qué hay que
aceptar. Contéstalo en la terminal de esa sesión (en Trabajo, la ventana
`orq-…`) y la tarea sigue sola.

Si prefieres quitártelo de en medio antes de la primera tarea, abre una terminal
y ejecuta una vez `claude --dangerously-skip-permissions`, acepta y sal con
`/exit`.

### Modelo, esfuerzo y contexto

El orquestador y las sesiones que abre usan **Opus** con esfuerzo alto, porque
coordinar trabajo de varios pasos es justo donde un modelo menor se equivoca.
**Él puede cambiarlo por sesión** —subir a `xhigh` para un análisis difícil,
bajar a Sonnet para algo mecánico— y te lo cuenta en el avance; si no tiene
claro que compense, te lo pregunta (te llega el aviso al teléfono). Cambiar el
modelo **no cambia tus ajustes**: relanza esa sesión con su misma
conversación.

Las sesiones que abre **compactan solas al 70 %** del contexto, en vez de
esperar al borde. Las que abriste tú no: si una va muy llena, él la compacta
entre dos encargos.

Una tarea pequeña son unos pocos minutos de Opus; una grande, bastante más.
Mira `/consumo`.

### Dictar

El botón del micrófono graba, transcribe **en tu máquina** y pega el texto en
el campo para que lo revises: no manda nada solo. El navegador sólo deja usar
el micrófono por HTTPS o en `localhost`.

🔴 **Recién instalado no transcribe**: el hub no trae ningún modelo de voz, a
propósito, porque el que va bien depende de la máquina. Hasta que configures
uno, el botón te dice exactamente qué poner. Se declara en
`~/.local/share/hub/encargos.yml`:

```yaml
transcripcion:
  comando: ["/ruta/a/python", "scripts/transcribir-whisper.py", "{audio}"]
```

`scripts/transcribir-whisper.py` usa `faster-whisper`, que hay que instalar en
ese Python. Sin transcriptor, la tarea se escribe a mano y todo lo demás
funciona igual.

Con el guion del hub, el dictado del secretario, del tablero y de la terminal
deja el modelo cargado un rato (se apaga solo tras 15 minutos sin uso) y lo
empieza a cargar en cuanto pulsas grabar: el primer dictado tras un rato no
espera a cargarlo de cero mientras hablas.

Puedes declarar otro programa: recibe el audio donde pongas `{audio}` y escribe
el texto en su salida. Si no escribe nada, el hub entiende que en el audio no
se oyó a nadie; cualquier código de salida distinto de cero es un fallo, y un
audio de un encargo se reintenta un rato antes de entregarse con el hueco
dicho. El código 3 como «no se oyó nada» es sólo del guion del hub.

### Medir el dictado con tu voz (`/voz/banco`)

Qué modelo de Whisper te entiende mejor sólo se sabe midiéndolo con tu voz.
La pantalla **Banco de dictado** (`/voz/banco`, también en la guía) te enseña
una frase cada vez:

1. Elige el aparato, PC o teléfono (sale solo según el ancho de la pantalla).
   Conviene grabar en los dos: el micrófono cambia mucho el resultado.
2. Pulsa **Grabar**, lee la frase en voz alta como hablas siempre y pulsa
   **Parar**. Se guarda en tu máquina con lo que tenías que decir; **no
   transcribe nada** y no necesita la GPU.
3. **Siguiente** pasa a la que falta; **Repetir** la vuelve a grabar. Son unos
   diez minutos por aparato.

Graba con los mismos ajustes de micrófono que el chat del secretario, y apunta
lo que el micrófono aplicó de verdad.

Las frases salen de una plantilla genérica con los nombres de tus proyectos y
de tu secretario. Puedes poner las tuyas antes de grabar:

```bash
uv run python -m hub.banco_dictado frases > mis-frases.yml   # la de ahora, para editarla
uv run python -m hub.banco_dictado sembrar --de mis-frases.yml
```

La lista se congela con la primera grabación; para cambiarla, vacía antes el
banco (sección «Vaciar», en cada aparato).

Para medir, en una terminal en la carpeta del hub:

```bash
uv run python -m hub.banco_dictado medir --modelos small,large-v3-turbo
uv run python -m hub.banco_dictado resultados
```

Carga cada modelo en su propio servidor de Whisper, le pasa todas las
grabaciones y lo apaga. Antes apaga el del dictado, y no empieza si Reuniones
está procesando: un modelo a la vez. Da el error por palabras (WER, con y sin
tildes), por letras (CER), cuántos términos propios acertó, el tiempo por
frase y lo que tardó en cargar, por categoría (cortas, técnicas, cifras…) y
por aparato; la última medida sale también en la sección «Medir» de la
pantalla. `--tipos float16,int8_float16` prueba tipos de cálculo y
`--dispositivo cpu` fuerza la CPU.

Las grabaciones viven en `~/.local/share/hub/voz/banco/`, sólo para tu
usuario; no caducan ni van en la copia diaria de la base. Nada sale de tu
máquina.

## El intercambio (`/intercambio`)

La carpeta por la que pasan archivos entre el teléfono y las sesiones, sin que
el hub escriba nunca dentro de tus proyectos:

Es una carpeta **de paso**: lo que quieras conservar, guárdalo en tu proyecto.

- **Del teléfono a una sesión:** pulsa *Elegir archivos* (puedes elegir
  varios), su proyecto o slot y *Subir*. Elige la sesión en *Sesión a la que
  pasar rutas* y, en el menú ⋯ del archivo, pulsa *Escribir la ruta en la
  sesión elegida*. La ruta aparece en el cuadro de Claude **sin Enter**, para
  que añadas qué quieres que haga con él. La sesión elegida se queda para el
  siguiente archivo.
- **De la terminal:** lo que arrastras o pegas sobre la terminal de `/trabajo`
  cae aquí solo, en la carpeta del proyecto y el slot de esa ventana.
- **De una sesión a ti:** pídele a la sesión que lo copie en la carpeta de su
  proyecto (`intercambio/<proyecto>/`) y bájalo desde aquí.

Se agrupa como el resto del hub: **por proyecto y, dentro, por slot**, lo más
nuevo primero. También se puede ver por **fecha**, **tipo**, **tema** (el
principio del nombre) o todo en fila con **Recientes**. Lo último que llegó
lleva la marca *nuevo*.

Las imágenes (png, jpg, gif, webp) de hasta 1 MB se ven en miniatura; tócala
para verla entera. Borrar está en el mismo menú ⋯ y pregunta antes.

Hasta 64 MB por archivo. **Lo arrastrado o pegado en la terminal se borra solo a
los 10 días**, y cada archivo dice el día. Lo que subes desde aquí o deja una
sesión no caduca: se borra a mano.
