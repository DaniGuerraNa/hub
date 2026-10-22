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
  el nombre `orq-…`). Si tiene varias, te pregunta a cuál mandarlo.
- **Detener** interrumpe la tarea y lo que estuvieran haciendo sus sesiones.
  **Reanudar** la vuelve a poner en marcha desde donde estaba, con su plan y su
  bitácora; puedes añadirle una nota (escrita o dictada) con lo que viste
  mientras estaba parada. Si hay otra en curso, vuelve a la cola.
- Necesita el muestreo en marcha (`hub-snapshotter`): es quien lo despierta
  cuando una sesión termina. Sin él, la tarea se queda encolada.

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
principal, borra datos, gasta dinero ni manda nada a un tercero: eso lo para y
te lo pregunta. Y un proyecto con `guardrail: never` en `projects.yml` queda
fuera aunque intentes darle nivel.

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

## El intercambio (`/intercambio`)

La carpeta por la que pasan archivos entre el teléfono y las sesiones, sin que
el hub escriba nunca dentro de tus proyectos:

Es una carpeta **de paso**: lo que quieras conservar, guárdalo en tu proyecto.

- **Del teléfono a una sesión:** súbelo aquí eligiendo su proyecto o slot y, en
  «Más», pulsa *Escribir la ruta ahí*. La ruta aparece en el cuadro de Claude
  **sin Enter**, para que añadas qué quieres que haga con él.
- **De la terminal:** lo que arrastras o pegas sobre la terminal de `/trabajo`
  cae aquí solo, en la carpeta del proyecto y el slot de esa ventana.
- **De una sesión a ti:** pídele a la sesión que lo copie en la carpeta de su
  proyecto (`intercambio/<proyecto>/`) y bájalo desde aquí.

Se agrupa como el resto del hub: **por proyecto y, dentro, por slot**, lo más
nuevo primero. También se puede ver por **fecha**, **tipo**, **tema** (el
principio del nombre) o todo en fila con **Recientes**. Lo último que llegó
lleva la marca *nuevo*.

Hasta 64 MB por archivo. **Lo arrastrado o pegado en la terminal se borra solo a
los 10 días**, y cada archivo dice el día. Lo que subes desde aquí o deja una
sesión no caduca: se borra a mano.
