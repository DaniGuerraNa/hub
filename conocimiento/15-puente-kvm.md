# Puente KVM

Para quien tiene un **JetKVM**: deja que Claude Code, en esta máquina, lea y
escriba en un **Mac donde no se puede instalar nada**. El JetKVM ve la salida
HDMI del Mac y teclea en él como un teclado USB; el puente es el programa que
lo maneja, con su propia web y su propia terminal de Claude.

Viene con el hub, en `componentes/puente-kvm` del clon, pero es un programa
aparte: su servicio (`puente-kvm`) no es del hub, y el hub no lo arranca ni lo
reinicia. El hub sólo enseña cómo está y te lleva a él.

🔴 **Aún no se ha probado con un JetKVM de verdad.** Todo lo medido es con el
Mac simulado que trae el puente. Qué está medido, qué no y cómo probarlo con
el aparato delante: `componentes/puente-kvm/docs/pruebas-con-el-aparato.md`.

🔴 **Su web no se publica ni se reenvía**, tampoco con `tailscale serve`:
dentro hay una terminal con Claude Code que teclea en otra máquina. Escucha
sólo en `127.0.0.1` y así se queda.

## Viene apagado

Es una herramienta opcional. Apagada, no sale en ningún menú ni en ninguna
búsqueda, y el hub se ve como si no existiera. Se enciende en **Ajustes →
Guía**, «Herramientas opcionales», y vale para todos los aparatos de esta
instalación. Encendida, sale en el menú (Agentes) y su pantalla es
[`/puente`](/puente).

## La pantalla

- **Cómo está:** si el puente está en marcha, con qué aparato (el JetKVM o el
  Mac simulado), si llega a él y quién tiene el teclado del Mac (la persona,
  Claude porque la persona se lo dio, o nadie tras «Parar»). Para volver a
  mirar, «Volver a mirar».
- **«Abrir el puente»**, en una pestaña aparte y **sólo desde la PC donde
  corre**. Su web escucha sólo en esa máquina y no pasa por la puerta del hub
  (Acceso): desde el teléfono u otro aparato ves cómo está y nada más, ni el
  botón ni la dirección.
- **Lo que le falta**, mientras falte algo, con «Preparar con Claude».

Dar el control a Claude, pararlo y aprobar un cambio se hace **en la pantalla
del puente**, no desde el hub. El hub no le manda nada: sólo le pregunta cómo
está, y de lo que contesta no enseña lo que se ha leído del Mac.

La terminal de Claude del puente vive en una sesión de tmux, `puente-claude`,
y por eso sale en **Trabajo** como cualquier otra. En **Talleres** no sale:
el puente lanza Claude desde una `bash`, y Talleres sólo enseña las sesiones
donde ve un agente. **No la
hagas slot**: teclea en otra máquina, y lo que el hub ofrece para un slot
(escribirle, retomarlo, encargarle trabajo) no es para ella.

Esa terminal **sólo carga lo del puente** (sus skills, sus permisos y su
servidor MCP), no tus conectores, skills, agentes ni plugins de Claude Code,
y no sale en su control remoto; de tus ajustes se lleva el modelo, el
esfuerzo, la interfaz, la barra de estado, los avisos al teléfono y lo que
tengas prohibido o te pregunta. Si tus ajustes dicen cómo autenticarse
(`apiKeyHelper`, `env`…), los carga para poder arrancar.

## Prepararlo

«Preparar con Claude» abre en `/trabajo` una ventana en su carpeta con `claude`
y el encargo **escrito y sin lanzar**: pulsa Enter ahí. Esa sesión sigue el
`INSTALAR.md` del puente y pide permiso antes de cada orden. A mano, en
`componentes/puente-kvm` (siempre con `uv run --frozen`, y sin `git pull` ahí:
el puente se actualiza con el hub):

| Paso | Cómo |
|---|---|
| Su entorno | `uv sync --frozen` (no reescribe `uv.lock`: `componentes/` está dentro del clon) |
| Qué le falta | `uv run --frozen puente-kvm comprobar --sin-entrar` |
| Con systemd | `PUENTE_TRABAJO="$HOME/puente-trabajo" bash scripts/servicio.sh unidad` enseña la unidad; `PUENTE_TRABAJO="$HOME/puente-trabajo" bash scripts/servicio.sh instalar` la instala y lo arranca. La variable, delante de las dos: sin ella, la unidad que ves no es la que se instala |
| Sin systemd | `PUENTE_TRABAJO="$HOME/puente-trabajo" bash scripts/arrancar.sh`, en su propia ventana (Ctrl+C lo para) |
| Comprobar | `uv run --frozen puente-kvm comprobar --sin-entrar`, y la pantalla `/puente` |

`comprobar` **sin** `--sin-entrar` entra en el JetKVM con la contraseña, y
eso le cierra su web si la tienes abierta en un navegador: úsalo así sólo
cuando quieras probar el aparato.

**`PUENTE_TRABAJO`, fuera del clon del hub.** Es la carpeta donde trabaja la
sesión de Claude del puente y donde queda lo que se trae del Mac. Dentro del
clon, Claude Code cargaría también el `CLAUDE.md` del hub y lo leído del Mac
acabaría en una carpeta que se vuelve a clonar. El puente prepara esa carpeta
solo. Con systemd, la variable queda dentro de la unidad al instalar; sin
systemd, hay que ponerla cada vez que se lanza.

**La contraseña del JetKVM la pones tú**, nunca Claude: una línea
`JETKVM_CLAVE=…` en `~/.config/puente-kvm/entorno`, con permisos 600. No va en
ningún archivo del clon ni en los ajustes del puente, y Claude no la toca: sus
permisos le niegan leerlo y editarlo. La dirección del aparato se elige en
**Ajustes**, en la web del puente.

## Despertar el Mac, el jiggler y pegar texto

En la pantalla del puente, bajo la imagen del Mac:

- **«Despertar el Mac»** lo saca del reposo, como «Intentar despertar» de la
  web del JetKVM (una tecla normal no lo despierta), y dice si volvió la
  imagen. Si el puente conectó con el Mac dormido (sin imagen), al despertarlo
  la conexión vuelve sola. Un Mac apagado no se enciende así. Claude también
  puede despertarlo (`despertar_mac`), pero sólo con el control.
- **«Jiggler»** lo enciende y lo apaga: el JetKVM mueve el ratón 1 a 3 píxeles
  cuando nadie lo toca, para que el Mac no se bloquee ni te ponga «ausente».
  El botón pone «Frecuente, cada 30 s»; Claude puede ponerle horario si se lo
  pides («de 9 a 18 entre semana»: un cron con segundos y tu zona horaria) y
  te pide permiso antes. Queda guardado en el aparato: **sigue aunque cierres
  el puente**, y el botón dice cuál corre.
- **«Teclado del Mac»**, junto a «Pegar texto» mientras usas el Mac: «Pegar
  texto» (y Claude al teclear) escribe tecla a tecla, y el Mac convierte cada
  tecla según su fuente de entrada. Si no es la misma, los acentos salen como
  símbolos raros (con «U.S.» en un Mac español, «á» sale «€a»). Un Mac en
  español de España suele tener «Español - ISO»; la latinoamericana aún no está.

## Grabar una reunión del Mac

Encima de la pantalla del Mac, en la web del puente, hay un botón: **«Estoy en
reunión»** empieza a grabar lo que suena en el Mac y su pantalla, y **«Salí de
la reunión»** lo para. Lo pulsas tú: ni Claude, ni el secretario, ni el hub lo
empiezan, porque graba a otras personas.

- **Tu voz no se graba.** El JetKVM no tiene micrófono: graba lo que el Mac
  manda a su salida de sonido, o sea a los demás. Lo que dices entra al Mac
  por su micro y no pasa por el JetKVM.
- **En el Mac, elige la salida del JetKVM:** Ajustes del Sistema → Sonido →
  Salida → el dispositivo USB del JetKVM. **No «JetKVM v1»**: ésa es la del
  HDMI, y por ahí no llega nada. Si no llega sonido, el puente lo avisa;
  en silencio no se distingue de una salida mal elegida.
- **Para oír y grabar a la vez:** «Configuración de Audio MIDI» (viene con
  macOS) → «+» → «Crear dispositivo de salida múltiple», con el JetKVM y tus
  auriculares, y elígelo como salida. Con él no van las teclas de volumen.
  Aún no se ha comprobado en un Mac.
- **Firmware del JetKVM 0.5.9 o posterior.** Su audio viene apagado: al
  empezar cada reunión el puente lo enciende y reconecta (la imagen se corta
  unos segundos y, si Claude tenía el control, vuelve a ti), y al pararla lo
  apaga. Con una tarea de Claude a medias no empieza: espera a que acabe.
- **Se procesa sola en Reuniones.** Al pararla, Reuniones la encuentra en unos
  minutos (sale como «Mac (JetKVM)») y la transcribe y resume como las demás;
  si no quieres esperar, «Procesar» en su página. Hace falta el procesado de
  Reuniones preparado (su parte de WSL); el agente de Windows no. Lo grabado
  se queda en los datos del puente (`PUENTE_HOME/reuniones`), y la
  transcripción va a Claude para el resumen, como la de cualquier reunión.

## Al actualizar y al desinstalar el hub

- **Al actualizar el hub, el puente se reinicia solo** si tiene su servicio
  de systemd y no está ocupado (una lectura, una escritura, el control dado
  a Claude, una reunión grabando o tú con «Usar el Mac desde aquí» abierto en
  su pantalla, aunque no estés moviendo nada). Si lo está, la actualización no
  lo corta, y Actualizaciones te dice cómo quedó con un enlace a esta pantalla.
- **Lo que falte, con botones, en la pantalla del puente.** Mientras siga con
  el código de antes, arriba sale un aviso con dos pasos:
  1. **«Reiniciar el puente»**: la imagen del Mac y la terminal se cortan
     unos segundos y la página vuelve sola. Si está ocupado, te dice por qué
     y no lo corta: vuelve a pulsarlo cuando acabe.
  2. **«Reabrir la conversación de Claude»**, para que Claude tenga las
     herramientas nuevas (la conversación sigue: Claude Code la retoma). Si
     Claude está trabajando, o recién reiniciado el puente no se sabe si lo
     estaba, te pregunta antes; igual al abrir otra conversación o una nueva.
  **Sin systemd** no hay botón de reiniciar: el aviso dice el comando. Vuelve
  a lanzar `scripts/arrancar.sh` **con la misma `PUENTE_TRABAJO` delante**
  (sin ella, Claude volvería a trabajar dentro del clon); el paso 2 sí tiene
  botón.
- **Desinstalar el hub no quita su servicio.** Antes, en
  `componentes/puente-kvm`: `bash scripts/servicio.sh quitar`. Se quedan sus
  datos (`~/.local/share/puente-kvm`, con las reuniones grabadas), la contraseña y la carpeta de trabajo
  (`~/puente-trabajo`, con lo leído del Mac): bórralos a mano si quieres.

## Si algo no va

- **«Caído · no hay nada escuchando en su puerto»:** no está arrancado, o el
  puente y el hub miran puertos distintos (si cambiaste `PUENTE_PUERTO`, tiene
  que valer lo mismo para los dos). Con systemd, `journalctl --user -u
  puente-kvm` dice por qué no arranca.
- **«Contesta, pero con un error (HTTP …)»:** en ese puerto contesta algo que
  no es el puente. Mira qué lo ocupa, o mueve el puente a otro con
  `PUENTE_PUERTO` (para los dos).
- **No llega al aparato:** en la PC, `/puente` dice por qué (desde fuera sólo
  que no está conectado). `uv run --frozen puente-kvm diagnostico` deja un
  informe sin secretos ni contenido del trabajo, para mandarlo; no entra en
  el JetKVM.
- **Avisar a quien mantiene el puente:** en `/puente` del hub, «Avisar de un
  fallo del puente» abre «Contar un fallo o una idea» ya marcado como del
  puente, con la versión del hub y lo justo del equipo. El diagnóstico del
  puente se copia en la pantalla del puente, Ajustes → «Copiar diagnóstico»
  (sin la contraseña, lo tecleado ni las direcciones de tu red); si lo pegas,
  léelo antes: lo que se envía a GitHub es público
  ([`06-problemas.md`](06-problemas.md), «Contárselo a quien mantiene el hub»).

## Variables

Ninguna hace falta.

| Variable | Por omisión | Para qué |
|---|---|---|
| `PUENTE_KVM` | `componentes/puente-kvm` del clon | Dónde lo busca el hub |
| `PUENTE_PUERTO` | `8794` | Su puerto; el mismo para el puente y para el hub |
| `PUENTE_TRABAJO` | la carpeta del código | Dónde trabaja Claude; ponla fuera del clon |
| `PUENTE_HOME` | `~/.local/share/puente-kvm` | Sus lecturas, cambios, bitácora y reuniones grabadas; si la cambias, la misma para el puente y para el hub, que lee ahí las reuniones |
