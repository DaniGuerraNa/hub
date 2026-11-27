# Estudio

Para quien ayuda a alguien que **no programa** a hacer su propia aplicación.
El estudio es una web aparte, del kit `estudio`, donde esa persona habla con
Claude Code y revisa lo que va saliendo: maquetas que se pueden pulsar,
capturas en teléfono y escritorio, y lo que le toca decidir en cada vuelta.

Es un programa aparte: su servicio (la unidad de usuario `estudio`) no es del
hub, y el hub no lo instala, no lo arranca ni lo reinicia. El hub sólo enseña
cómo está y te lleva a él.

El kit `estudio` **todavía no está en el catálogo público**: mientras no lo
esté, esta herramienta sólo sirve en un equipo donde ya se instaló.

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
- **Si no contesta**, por qué (nada escuchando, no contestó a tiempo…) y cómo
  se instala y se arranca.

Contestar, aprobar y comentar se hace **en el estudio**, no desde el hub. El
hub no le manda nada: le pregunta cómo está y qué proyectos tiene, y de lo que
contesta sólo enseña eso. Ni rutas ni lo que se habla con Claude.

## Instalarlo y arrancarlo

En la carpeta del hub, `bash scripts/kit.sh ruta estudio` dice dónde está el
kit; si contesta «estudio no está instalado», no lo tienes todavía. Con el kit
en su sitio, una vez:

```bash
bash "$(bash scripts/kit.sh ruta estudio)/install.sh"
```

Deja la unidad de usuario `estudio`, que arranca sola con la sesión. Lo que
dice el README del kit manda sobre esto.

Si estaba instalado y no contesta:

```bash
systemctl --user start estudio          # arrancarlo
journalctl --user -u estudio            # por qué no arranca
```

**Otro puerto.** El hub lo busca en el 8795. Si el estudio escucha en otro,
pon ese número en `ESTUDIO_PUERTO`, en el entorno del hub.

## Si algo no va

- **«No hay nada escuchando en su puerto»:** el servicio no está en marcha,
  o escucha en otro puerto. Arráncalo, o mira `ESTUDIO_PUERTO`.
- **«No contestó a tiempo»:** está arrancando o atascado. Vuelve a mirar en
  unos segundos; si sigue, su registro (`journalctl --user -u estudio`).
- **«No se pudo saber qué proyectos tiene»:** el estudio contesta pero su
  lista no; el motivo va al lado.
- **No ves «Abrir»:** estás mirando desde otro aparato. Se abre en la PC donde
  corre.

## Al desinstalar el hub

`desinstalar.sh` no para ni quita la unidad `estudio`: es de su kit, y
quitarla lo dice el README del kit. Hazlo **antes** si vas a usar `--datos`:
el kit vive en la carpeta de kits del hub, dentro de sus datos, y con ella se
iría también lo que la unidad arranca.
