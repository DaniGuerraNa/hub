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

Para entrar desde otro aparato el camino es otro, y tiene tres cerraduras.
Las dos primeras las monta la propia pantalla Acceso con botones, sin
escribir comandos ni editar archivos:

1. **Una red privada** entre tus aparatos (tipo Tailscale) que haga de puente
   hasta `127.0.0.1` de esta máquina — con Tailscale, `tailscale serve` hacia
   `http://127.0.0.1:8787`. En Acceso, **«Preparar con Claude»** abre una
   ventana con el encargo escrito: lo lanzas tú con Enter y Claude te pide
   permiso para cada paso. El hub no lo hace solo: la primera vez Tailscale
   puede pedir que actives serve en su consola, y eso sólo lo puedes hacer tú.
2. **Nombres exactos.** El nombre de la máquina en esa red va en `hosts` de
   `~/.local/share/hub/acceso.yml`. Acceso lo pregunta a Tailscale y lo
   guarda con **«Usar este nombre»** (o lo escribes en su campo, si no lo
   ve). Un comodín (`*`) se rechaza, y por un nombre que no esté en la lista
   no se entra. Una IP, un `https://` o un `:puerto` en la lista no sirven
   para entrar: la pantalla los señala y no los usa para el QR.

   **Mientras no haya ese nombre, Acceso no genera ningún QR**: uno a
   `127.0.0.1` es válido y no lo abre ningún móvil. En su lugar dice qué
   falta. Y si `acceso.yml` está mal escrito, dice qué le pasa, cómo quedará y
   lo reescribe con **«Arreglarlo»**, guardando el anterior al lado
   (`acceso.yml.roto-<fecha>-<hora>`).

   🔴 **La solución nunca es poner la IP de Tailscale con el puerto del hub,
   ni escuchar en `0.0.0.0`, ni abrir el puerto**: el hub no escucha ahí, y
   no debe.
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

**Qué no hace:** no abre ningún puerto ni configura la red privada por su
cuenta; eso lo montas tú, con «Preparar con Claude» si quieres. Y no defiende de un aparato que ya esté dentro de tu red privada
y se haga pasar por local: la defensa ahí es aprobar a mano qué aparatos
entran en esa red.

### Acceso, paso a paso: preparar la red privada (Preparar con Claude)

Se hace una vez, en la PC del hub, en [Acceso](/acceso). Mientras falte,
«Dar de alta un aparato» no enseña el formulario del QR sino **«Para entrar
desde el móvil u otro aparato faltan dos cosas»**, con dos pasos:

1. **«La red privada lleva al hub».** Pulsa **«Preparar con Claude»**. Se abre
   la pantalla Trabajo con una ventana nueva donde ya está escrito el encargo
   para Claude: pulsa **Enter** para lanzarlo. Claude mira si Tailscale está
   instalado y con la sesión iniciada, publica el hub en la red privada
   (`tailscale serve` hacia `http://127.0.0.1:8787`) y guarda el nombre de la
   máquina. Te pide permiso para cada orden. Si Tailscale pide activar
   «serve» o https en su consola, Claude te da el enlace y espera: eso sólo
   lo puedes hacer tú, con tu cuenta. Al acabar, vuelve a Acceso: el paso sale
   «hecho».
   - Si dice **«No veo Tailscale en esta máquina»**: instala Tailscale en ella
     (en Windows, el de Windows), inicia sesión con tu cuenta y vuelve a abrir
     Acceso. Claude, con el mismo botón, te guía.
   - Si dice **«No pude mirarlo»**: Tailscale no contestó a tiempo. Ábrelo (o
     espera a que conecte) y recarga la página.
2. **«El nombre de esta máquina en la red privada».** Si Tailscale lo da, sale
   escrito (algo como `esta-maquina.tu-red.ts.net`) con el botón **«Usar este
   nombre»**: púlsalo. Si no lo ve, hay un campo: escribe ahí el nombre exacto
   que te da la app de Tailscale y pulsa **«Guardar»**. Vale en el acto, sin
   reiniciar nada.

### Acceso, paso a paso: dar de alta un aparato con el QR

En la PC del hub, en [Acceso](/acceso) → «Dar de alta un aparato»: escribe
un nombre para reconocerlo («Móvil») y pulsa **«Generar el QR»**. Sale un QR
y, debajo, su enlace, que empieza por `https://` y el nombre de la red
privada. Con el aparato **conectado a Tailscale**, escanéalo con su cámara (o
abre en él ese enlace) antes de 10 minutos: entra al hub y queda dado de
alta. Sirve una sola vez. Los aparatos dados de alta salen debajo, y
**«Quitar»** deja fuera a uno en la petición siguiente.

### Acceso, paso a paso: «no me funciona el QR»

- **No sale ningún QR, sale «faltan dos cosas»:** falta el nombre de la red
  privada; sigue «preparar la red privada» (arriba). Es a propósito: un QR a
  `127.0.0.1` no lo abre ningún móvil.
- **El QR abre pero no carga:** el aparato no está conectado a Tailscale (abre
  la app en él y conéctalo), o la red privada no lleva al hub. Si Acceso dice
  «Tailscale no tiene guardado publicar el hub en la red privada», pulsa ahí
  «Preparar con Claude».
- **«Este código ya no vale»:** pasaron los 10 minutos o ya se usó. Genera
  otro.
- **«El hub no acepta el nombre…»:** el nombre por el que entra el aparato no
  está guardado. En la PC del hub, Acceso → «Usar este nombre».
- **«Este dispositivo no está dado de alta»:** genera un QR en la PC del hub y
  escanéalo con ese aparato.
- **Sale un aviso de que el archivo de acceso está mal escrito:** mira el
  siguiente apartado.

🔴 Lo que **nunca** arregla esto, aunque lo parezca: poner la IP de Tailscale
con el puerto del hub (`http://100.x.x.x:8787`), hacer que el hub escuche en
`0.0.0.0` o abrir el puerto o el cortafuegos. El hub escucha sólo en esta
máquina a propósito, porque su terminal da una shell. Tampoco hay ningún
enlace que escribir a mano: el bueno lo da el QR.

### Acceso, paso a paso: el archivo de acceso está mal escrito

Si `acceso.yml` dice algo que no se puede obedecer (un nombre suelto en vez
de una lista, un comodín, un `https://` o un puerto dentro, o un archivo que
no se lee), Acceso lo dice arriba en un aviso: qué le pasa, la lista de lo
que cambiará y con qué nombres quedará. Pulsa **«Arreglarlo»** en la PC del
hub. El archivo de antes se guarda al lado (`acceso.yml.roto-<fecha>-<hora>`). Si el
aviso dice que **los aparatos tendrán que volver a darse de alta**, es que el
archivo no se podía leer: después del arreglo, vuelve a dar de alta cada uno
con su QR. Mientras está mal escrito, al hub se entra desde la propia PC, no
desde fuera. Si dice «el archivo cambió mientras lo mirabas», recarga y
vuelve a pulsar.

Una IP en la lista no rompe nada, pero no sirve para el QR: Acceso la
señala. El nombre bueno lo pone «Usar este nombre».

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
3. Cada persona escribe al bot y aparece en Canal como pendiente, con su
   formulario ya abierto: le pones un alias, la activas y marcas quién eres tú
   (el dueño, el que recibe los avisos). Después cada persona se lee en una
   línea y su formulario espera tras **Editar**. Los permisos se dan por
   proyecto, en su plegado: ahí salen sólo los proyectos donde ya tiene algo
   (pulsar una acción la quita o la pone) y, para otro, **Dar acceso a otro
   proyecto**: eliges el proyecto y pulsas la acción.

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
  Si editas uno, nadie lo pisa sin que lo pidas; y si la sesión publica una
  versión nueva mientras lo tienes abierto, tu marca tampoco la pisa: el panel
  te enseña la de ahora y lo vuelves a marcar. «Archivo» enseña los
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

**El secretario también los usa.** Pídele «clóname estos repos en
interno/repos» y te los deja escritos sin Enter en una ventana (todos en una
sola línea, separados por ` ; `), con el enlace para abrirla. Si quieres que
los corra él, marca ese comando así:

```yaml
  - id: clonar
    nombre: Clonar un repo
    plantilla: bash ~/.secretos/clonar.sh {repo} {ruta}
    ejecutable: true      # sólo tú lo escribes: el hub nunca toca este archivo
    crea: "{repo}"        # la carpeta que crea, relativa a donde se corre
```

Entonces te pide permiso en **Pendientes**, donde ves cada orden tal cual
antes de aprobarla (si apruebas pasados 15 minutos, no la corre). Va de uno
en uno, salta los que ya tienen su carpeta sin entrar en ellos, da por bueno
sólo lo que quedó como repo de git, y te deja en el chat cuáles salieron,
cuáles ya estaban y cuáles fallaron con su error. Hasta 30 de una vez, cada
uno con 5 minutos como mucho, y nunca en un proyecto con guardrail `never`.
Corre sin terminal: si tu script pide una contraseña, falla en vez de
quedarse esperando.

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
  «¿Me das permiso?» y el taller se marca. Si está quieta pero tiene
  subagentes en marcha, está **delegando**: no se duerme y cuenta entre las
  que trabajan. De Codex no se sabe leer el estado: su rana se queda quieta,
  sin dormir.
- Si dos talleres se llaman igual, su título lleva la ventana («· ventana 2»).
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

Arriba va **Salud del hub**: lo que pide algo sale abierto, con su arreglo al
lado; lo que está bien queda plegado en una sola línea («Todo en pie · N
comprobaciones», o «Lo demás en pie» si algo falla). Ábrela para ver el detalle.

En **Encendido y apagones**, «Tras el último arranque» dice cuánto tardaron WSL
y los servicios del hub en arrancar después de que encendiera Windows: si tras
un apagón el hub no vuelve solo, ahí se ve dónde se quedó. Sale sólo cuando
las horas son de la misma lectura y cuadran.

**Diagnóstico de la PC**, más abajo, es para justo después de un pantallazo o
con la red rara: «Diagnosticar ahora» lee en Windows los pantallazos (con su
código), los volcados y los apagados recientes, y mide la latencia a la puerta
de enlace y a dos servidores de referencia. Sólo lectura, pide confirmación,
tarda unos segundos y no se guarda: al recargar, se va. Va uno a la vez: si
ya hay uno en marcha, lo dice y no lanza otro. Es lo mismo que te contesta el
secretario si se lo preguntas.

## Consumo

**Dónde:** [Consumo](/consumo).

Tokens por proyecto y por día, leídos del registro de Claude Code. 🔴 Son
**los últimos días que quedan**, no el histórico: Claude Code borra su registro
a los 30 días, y la pantalla dice de qué fecha a qué fecha cuenta. No convierte
a dinero: hace falta una tabla de precios que cambia sola y que no se puede
verificar contra nada, y una cifra que no se puede defender no se enseña.

El porqué de Consumo, Canal, Conexiones y Servicios está plegado bajo una línea
de la cabecera («¿Por qué así?»): se lee una vez y luego no empuja el contenido.

## Interfaz nueva (vista previa)

Al final de la **Guía**, «Probar la interfaz nueva» cambia el marco del hub en
**ese aparato**: la navegación en nueve secciones (en la PC se pliegan con la
flecha de arriba), una barra abajo en el teléfono y sus propios colores (Pizarra
o Brasa, ahí mismo). Las pantallas por dentro son las de siempre y los demás
aparatos no cambian. «Volver a la de siempre», en el mismo sitio, la apaga.

Viene apagada porque aún se está puliendo: si la pruebas y algo no se ve bien o
echas algo en falta, cuéntaselo a quien te instaló el hub o abre una incidencia
en el repositorio de donde lo instalaste (desde la Guía, el enlace te lleva a
«Contar un fallo o una idea», `06-problemas.md`).

## Buscar y moverse con el teclado

| | |
|---|---|
| `Ctrl+K` o `/` | Buscar en todo lo indexado, desde cualquier pantalla |
| `g` y una letra | Ir a una pantalla: `p`anorama, `t`rabajo, `i`nventario, `r`espaldo, `s`ervicios, `c`onexiones, conte`x`to |
| `?` | Todos los atajos |
| `Esc` | Cerrar lo que esté abierto |

Si la búsqueda no encuentra nada, lo dice («Nada con …»), y si el secretario es
quien te habla en todas las pantallas, ofrece preguntárselo a él.

Un slot se encuentra también por las palabras de su nota, pero en la lista sale
con su proyecto y su ruta: la nota no se enseña, porque a veces lleva pegado
algo que no debería verse en una lista que se abre con un atajo.
