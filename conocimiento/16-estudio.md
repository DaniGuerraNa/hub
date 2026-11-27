# Estudio

Para quien ayuda a alguien que **no programa** a hacer su propia aplicación.
El estudio es una web aparte, del kit `estudio`, donde esa persona habla con
Claude Code y revisa lo que va saliendo: maquetas que se pueden pulsar,
capturas en teléfono y escritorio, y lo que le toca decidir en cada vuelta.

Es un programa aparte: su servicio (la unidad de usuario `estudio`) no es del
hub, y el hub no lo instala, no lo arranca ni lo reinicia. El hub sólo enseña
cómo está y te lleva a él.

🔴 **Su web no se publica ni se reenvía**, tampoco con `tailscale serve`:
dentro hay un Claude Code. Escucha sólo en `127.0.0.1` y así se queda.

## Viene apagado

Es una herramienta opcional. Apagada, no sale en ningún menú ni en ninguna
búsqueda, y el hub se ve como si no existiera. Se enciende en **Ajustes →
Guía**, «Herramientas opcionales», y vale para todos los aparatos de esta
instalación. Encendida, sale en el menú (Agentes; en la interfaz nueva,
Herramientas) y su pantalla es [`/estudio`](/estudio).

## La pantalla

- **Cómo está:** si contesta y con qué versión. Para volver a mirar, «Volver
  a mirar».
- **Sus proyectos:** el nombre de cada uno, en qué momento está, cuántas cosas
  **te espera** (lo que la persona tiene que elegir, aprobar o comentar) y si
  **Claude está trabajando** en él.
- **«Abrir el estudio»** y **«Abrir»** en cada proyecto, en una pestaña aparte
  y **sólo desde la PC donde corre**. Desde el teléfono u otro aparato ves
  cómo está y sus proyectos, sin los botones ni las direcciones.
- **Si no contesta**, por qué (nada escuchando, no contestó a tiempo…) y sus
  pasos para instalarlo y arrancarlo, con «Preparar con Claude».

Contestar, aprobar y comentar se hace **en el estudio**, no desde el hub. El
hub no le manda nada: le pregunta cómo está y qué proyectos tiene, y de lo que
contesta sólo enseña eso. Ni rutas ni lo que se habla con Claude.

## Instalarlo y arrancarlo

No hay que escribir ningún comando. Con el estudio sin contestar, `/estudio`
enseña tres pasos, cada uno hecho o por hacer:

1. **El kit «estudio» está en esta máquina.** Viene del catálogo de kits
   (Inventario → Kits).
2. **Hay systemd de usuario, para que arranque solo.** Es opcional: sin él,
   el estudio corre en una ventana propia y, al reiniciar la máquina, hay que
   volver a arrancarlo.
3. **Contesta en esta máquina.**

Lo que falte lo hace **«Preparar con Claude»**, desde la PC donde corre: abre
una ventana en Trabajo con Claude y el encargo escrito —traer el kit del
catálogo, leer su instalador, instalarlo como servicio de usuario (o sin
servicio, si no hay systemd), arrancarlo y comprobar que contesta— y la
lanzas tú con Enter. Esa sesión te pide permiso para cada orden; si falta algo
del sistema (Python 3.10 o más, git, Claude Code), te dice qué es y espera a
que lo instales tú. Si ya estaba instalado y no contesta, la misma ventana lo
arranca y te dice por qué no contestaba. Al terminar, «Volver a mirar».

El hub no ejecuta el instalador ni toca el servicio por su cuenta: lo hace esa
sesión, contigo delante.

**Que te guíe el secretario.** «Guíame», junto a «Preparar con Claude», le
pregunta al secretario, que te lleva un paso cada vez con lo mismo que dice
aquí (la Guía de esta pantalla): pulsar el botón, dar Enter en la ventana que
se abre, contestar lo que Claude te pregunte y, al final, «Volver a mirar»
hasta ver «En marcha» y «Abrir el estudio».

**Otro puerto.** El hub lo busca en el 8795, o en el que diga `ESTUDIO_PUERTO`
en su entorno; «Preparar con Claude» lo instala en ese mismo.

## Si algo no va

- **«No hay nada escuchando en su puerto»:** no está en marcha, o escucha en
  otro puerto. «Preparar con Claude» lo arranca y mira por qué.
- **«No contestó a tiempo»:** está arrancando o atascado. Vuelve a mirar en
  unos segundos; si sigue, «Preparar con Claude».
- **«No se pudo saber qué proyectos tiene»:** el estudio contesta pero su
  lista no; el motivo va al lado.
- **No ves «Abrir»:** estás mirando desde otro aparato. Se abre en la PC donde
  corre.

## Al desinstalar el hub

`desinstalar.sh` no para ni quita la unidad `estudio`: es de su kit, y
quitarla lo dice el README del kit. Hazlo **antes** si vas a usar `--datos`:
el kit vive en la carpeta de kits del hub, dentro de sus datos, y con ella se
iría también lo que la unidad arranca.
