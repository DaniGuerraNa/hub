# Las demás pantallas y piezas

Lo que no cabe en los otros documentos: entrar desde fuera, Telegram, las
pestañas del panel derecho de Trabajo y unas cuantas pantallas más pequeñas.
Cada sección dice qué es, dónde está, qué tienes que configurar y qué no hace.

## Acceso — usar el hub desde el móvil u otro aparato

**Dónde:** [Acceso](/acceso).

🔴 **El puerto del hub da una shell**: `/terminal` es una terminal de verdad. Por
eso el hub escucha sólo en `127.0.0.1`, y la respuesta a «¿abro el puerto a la
red?» o «¿lo pongo en `0.0.0.0`?» es **no**, siempre. Nunca se expone a
internet.

Para entrar desde otro aparato el camino es otro, y tiene tres cerraduras:

1. **Una red privada** entre tus aparatos (tipo Tailscale) que haga de puente
   hasta `127.0.0.1` de esta máquina — con Tailscale, `tailscale serve`.
2. **Nombres exactos.** El nombre de la máquina en esa red se declara en
   `~/.local/share/hub/acceso.yml`:

   ```yaml
   hosts:
     - esta-maquina.tu-red.ts.net
   ```

   Un comodín (`*`) se rechaza. Por un nombre que no esté en la lista no se
   entra.
3. **Aparatos dados de alta.** Entrando por un nombre de fuera, cada aparato
   necesita alta: en Acceso, «Generar el QR», y se escanea con el aparato —o
   se abre en él el enlace que sale debajo— en los 10 minutos siguientes. El
   primero, si aún no puedes entrar desde ningún otro, se da de alta desde una
   terminal de la máquina (por SSH si no tiene pantalla):
   `uv run python -m hub.acceso alta "Móvil"` en la carpeta del hub. Con el hub
   en una máquina sin monitor, mira `14-maquina-aparte.md`. En la
   misma pantalla se ven los aparatos y se quitan: quitar uno surte efecto en
   la petición siguiente.

**La terminal, además**, sólo se abre desde fuera con el interruptor «terminal
remota» de Acceso. Viene apagado y **se apaga solo cada vez que el hub
reinicia**. Desde esta máquina la terminal funciona siempre.

**Qué no hace:** no abre ningún puerto ni configura la red privada; eso lo
montas tú. Y no defiende de un aparato que ya esté dentro de tu red privada
y se haga pasar por local: la defensa ahí es aprobar a mano qué aparatos
entran en esa red.

## Canal — preguntas por Telegram

**Dónde:** [Canal](/canal). Opcional.

Sirve para que una sesión de Claude **le pregunte algo a una persona** que no
está delante —tú desde el móvil, o alguien que sabe la respuesta— y siga con lo
que le contesten. Las preguntas salen con `hub preguntar` y se ven en la
pestaña **Consultas** de Trabajo.

🔴 **No es un canal para mandar instrucciones.** Nadie de fuera puede abrir una
conversación ni pedirle trabajo a una sesión: sólo contestar lo que se le
pregunta. Las acciones que se pueden conceder son una lista cerrada
(`recibir-preguntas`, `responder`, `leer-estado`), por proyecto y por persona.

**Qué configurar:**

1. Crea un bot de Telegram y guarda su token en un archivo tuyo con permisos
   propios. **El token no va en el hub**: en `~/.local/share/hub/canal.yml`
   sólo va el puntero:

   ```yaml
   token_ref: ~/.secretos/telegram.env#TELEGRAM_BOT_TOKEN
   ```

2. El servicio `hub-canal` se instala **parado**. Arráncalo cuando el archivo
   esté listo: `systemctl --user enable --now hub-canal`.
3. Cada persona escribe al bot y aparece en Canal como pendiente. Ahí le das
   permisos por proyecto, y marcas quién eres tú (el dueño).

**Avisos.** Con el canal en marcha, al dueño le llegan avisos cortos de una
lista cerrada: una sesión parada preguntando, una sesión quieta, el hub sin
latido y, en la salud del equipo, temperatura, disco y corte de luz. El aviso
dice que pasa algo, **nunca el contenido**: eso se lee en el hub.

**Pánico.** Si no puedes entrar al hub, escribir `panico` al bot (sólo el
dueño) reinicia `hub-web` y `hub-snapshotter`. Es lo único que se puede
ordenar por Telegram. No sirve si la máquina entera está caída.

## Encargos — negocios contados por audio

**Dónde:** [Encargos](/encargos). Opcional, con su propio bot.

Una persona cuenta por Telegram (por audio) qué necesita su negocio; un agente
la entrevista, va rellenando la ficha del encargo y sale una primera maqueta
para que la mire. Cada encargo tiene su ficha en `/encargos/<id>`, con lo que
se sabe y la conversación. «Implementar» pasa una maqueta aprobada a sistema.

**Qué configurar:** un segundo bot, distinto del canal. Su puntero va en
`~/.local/share/hub/encargos.yml` (`token_ref`, y `transcripcion` para los
audios; ver [`09`](09-orquestador-e-intercambio.md)), el servicio
`hub-encargos` también se instala parado, y en Encargos das de alta a quién
puede mandarlos. Publicar maquetas en un servidor necesita además los scripts
`scripts/desplegar-*.sh`.

## El panel derecho de Trabajo

En [Trabajo](/trabajo), a la derecha, cuatro pestañas. Todas siguen a la
ventana que estás mirando.

- **Nota** — la del slot. Ver [`02`](02-trabajo-y-slots.md).
- **Lienzos** — contenido visual que una sesión de Claude publica en vez de
  soltar texto en la terminal: una lista de decisiones, una arquitectura, unos
  pasos o una comparativa. Se publican con `hub lienzo nuevo` (o
  `POST /api/lienzo`) y se guardan en `~/.local/share/hub/lienzos/<proyecto>/`.
  En una lista de decisiones marcas tú cada punto, y la sesión lo lee de vuelta.
  Si editas uno, nadie lo pisa sin que lo pidas. «Archivo» enseña los
  archivados.
- **Consultas** — las preguntas que tus sesiones mandaron por el canal, con su
  respuesta. Filtros: todas, pendientes y contestadas.
- **Programados** — un mensaje que se escribe en la ventana de ese slot a la
  hora que digas, para que Claude lo lea. Sólo se entrega si en ese momento
  ahí sigue corriendo un agente (Claude Code o Codex). **Se intenta una sola
  vez**, y si pasan 30 minutos de la hora pedida (por ejemplo, la máquina
  estaba apagada) ya no se manda: se marca caducado con su motivo. Sólo
  funciona en ventanas que tienen slot.

## Archivos y comandos preparados

**Dónde:** [Archivos](/archivos).

Navegas por las carpetas de tus proyectos: nombres y rutas, sin abrir ni
tocar nada. «Abrir terminal aquí» abre una ventana de tmux en esa carpeta.

Si declaras **comandos preparados**, puedes elegir uno y dejarlo escrito en esa
ventana **sin Enter**: lo lanzas tú. Útil desde el móvil, donde escribir una
orden larga no es práctico. Van en `~/.local/share/hub/comandos.yml`:

```yaml
comandos:
  - id: clonar
    nombre: Clonar un repo
    plantilla: git clone git@github.com:mi-org/{repo}.git
```

Lo que va entre llaves es un hueco que rellenas al usarlo (se escapa antes de
escribirlo). 🔴 Nada de credenciales en una plantilla: si un comando necesita
una, la plantilla llama a un script tuyo que la lee.

## Tablero — ideas para después

Para no perder una mejora que se te ocurre mientras se trabaja en otra cosa.
Escribes la idea en una línea (con detalle y proyecto si quieres) y pulsas
**Apuntar**; también vale decírselo al secretario («anota en el tablero
que…») o, en una terminal, `uv run python -m hub.ideas apuntar "…"`.

El detalle se puede **dictar**: «Dictar» graba, pulsas otra vez y el texto
aparece en el campo para que lo revises; la transcripción se hace en tu
máquina. Para fotos, capturas y archivos: **Adjuntar**, pegar con Ctrl+V o
soltarlos encima del cuadro (hasta 10 por idea). Las imágenes se ven en
miniatura; lo demás se descarga. También se añaden después, con «Adjuntar» en
la idea que espera. Los adjuntos se guardan en la carpeta del Intercambio
(`intercambio/_tablero/`), así que también aparecen allí, y **no entran en la
copia diaria** de la base.

Las ideas esperan de la más antigua a la más nueva. Cuando te pongas con una
(tú o Claude en una sesión), se marca como tomada diciendo dónde sigue —su
tarea, su issue, su ficha—: `uv run python -m hub.ideas tomar <número>
"<dónde sigue>"`, y `uv run python -m hub.ideas lista` enseña las que esperan.
Nada avisa ni la toma solo. Si una ya no tiene sentido, **Descartar**
pide el motivo y la deja a la vista.

**Trabajarla** se la encarga al orquestador. La trabaja una sesión fija
llamada «Tablero», en una **copia de trabajo** del proyecto (un `git
worktree` en `<carpeta del proyecto>-tablero`), así que no toca tu carpeta
ni tus sesiones. Esa sesión la toma, la **aterriza** (mide lo que hay, fija
el objetivo y propone un plan) y, si el cambio es mediano o grande, te
pregunta antes de construir. Lo hecho se queda en la rama de la copia hasta
que tú lo integres. La primera vez que trabajas una idea de un proyecto con
git, el botón dice **Crear la copia y trabajarla**: te explica qué se crea
(la copia junto a su carpeta, en una rama «tablero») y, si aceptas, la crea y
la encarga. Tu carpeta y tus ramas no se tocan. Un proyecto **sin git** no
tiene copia: su idea se trabaja en su propia carpeta, y sólo mientras tú no
tengas ahí una sesión de Claude Code abierta (si la tienes, el orquestador te
pregunta; una terminal normal no cuenta).
También se le puede
pedir al secretario («trabaja la idea 3»): te deja la solicitud y, al
aprobarla, vale como tu sí.

## Talleres — ver trabajar a tus sesiones

**Dónde:** [Talleres](/talleres), en el grupo Agentes del menú.

Cada ventana donde corre Claude Code o Codex se ve como un **taller**: una casa
de muñecas de dos plantas con su herrería, su alquimia, su biblioteca con la
mesa de mapas, su estudio y su rincón junto a la chimenea.

- **La rana del yunque es la sesión.** Martilla si está trabajando; si está
  quieta, se duerme y el taller baja la luz; si espera tu permiso, levanta
  «¿Me das permiso?» y el taller se marca. De Codex no se sabe leer el estado:
  su rana se queda quieta, sin dormir.
- **Sus subagentes** entran por la puerta y van a la estación de su oficio:
  quien investiga, a la alquimia; quien diseña la arquitectura, a la mesa de
  mapas; quien explora o resume, a la biblioteca; quien diseña, al caballete;
  quien planifica, a la chimenea; quien revisa o ayuda, a la entrada. Si en
  una estación no caben, sale «+N» y el siguiente entra cuando sale uno. Al
  terminar, le llevan el resultado a la sesión y se van.
- Debajo de cada taller está la lista de quién hay y qué hace; arriba, cuántos
  talleres, cuántos trabajan, cuántos esperan tu sí y cuántas ranas.
- Toca la cabecera de un taller para verlo en grande.

Se pone al día sola cada 10 segundos mientras la miras, con lo que mide el hub
(el muestreo de tus ventanas, cada 20 s). Si el muestreo no corre, lo dice en
vez de enseñar como de ahora algo viejo.

**Qué no hace:** no escribe en ninguna ventana ni manda avisos: sólo mira. Que
una sesión espera tu permiso lo sabe sólo si los avisos de Telegram están
encendidos y la ventana tiene slot; si no, se ve como quieta.

## Máquina

**Dónde:** [Máquina](/maquina).

Disco, memoria, GPU y, si hay un SAI por USB, si se fue la luz. Se mide cada
diez minutos y la pantalla dice cuándo. Está pensada para **WSL en Windows**:
pregunta a Windows con `powershell` y a la GPU con `nvidia-smi`. En Linux sin
Windows saldrá casi vacía, y lo que no puede medir lo dice en vez de enseñar un
cero.

## Consumo

**Dónde:** [Consumo](/consumo).

Tokens por proyecto y por día, leídos del registro de Claude Code. 🔴 Son
**los últimos días que quedan**, no el histórico: Claude Code borra su registro
a los 30 días, y la pantalla dice de qué fecha a qué fecha cuenta. No convierte
a dinero.

## Buscar y moverse con el teclado

| | |
|---|---|
| `Ctrl+K` o `/` | Buscar en todo lo indexado, desde cualquier pantalla |
| `g` y una letra | Ir a una pantalla: `p`anorama, `t`rabajo, `i`nventario, `r`espaldo, `s`ervicios, `c`onexiones, conte`x`to |
| `?` | Todos los atajos |
| `Esc` | Cerrar lo que esté abierto |
