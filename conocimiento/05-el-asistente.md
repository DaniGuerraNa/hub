# El asistente

La pestaña de abajo a la derecha. Un chat que te sigue por todas las pantallas y
responde sobre **tus** proyectos.

Detrás no hay ningún motor de chat: hay una ventana de tmux con `claude` dentro,
y el hub pinta su transcript. Por eso no hay historial que guardar ni sesión que
reanudar, y por eso **Compactar** y **Limpiar** son de verdad `/compact` y
`/clear`.

## Instalarlo

Es opcional. Si no lo instalas, la pestaña ni se pinta.

```bash
bash scripts/sembrar-asistente.sh
```

El script lo declara solo en tu registro; en menos de un minuto sale el chat.

## Para qué sirve

Para preguntar por el sistema **sin gastar el contexto de la sesión en la que
estés trabajando**. El caso típico: dejaste un proyecto trabajando solo durante
horas y al día siguiente quieres saber qué se hizo sin leerlo entero.

Puede decirte qué sesiones hubo y de qué iban, resumir una, apuntar notas en tus
slots y darte el panorama de respaldo y servicios.

## Lo que no hace

**Sobre tus proyectos es sólo lectura.** No escribe en ellos y no ejecuta nada
ahí. Dentro del hub sí escribe —notas y slots— y **borrar no se le expone**.

No es sólo una instrucción: su `.claude/settings.json` **deniega** `Edit`,
`Write`, `NotebookEdit`, `rm`, `mv`, `git commit`, `git push`, `git checkout`,
`docker`, `systemctl` y `curl`.

## Cómo leer la pestaña

- El **porcentaje** es su contexto ocupado. Se pone naranja al 70 %.
- La **luz** dice si está vivo o pensando.
- La **rueda** de la pestaña guarda **Compactar** y **Limpiar** (su contexto) y,
  bajo «Si algo falla», **Terminal**, que abre su sesión cruda por si hace falta
  ver lo que hay debajo.

Si Claude Code le pide permiso para algo, el cuadro aparece **en el chat** con
dos botones. Sin eso la conversación se quedaría muda sin decir por qué.

## Guardrails

Cada proyecto lleva en el registro un `guardrail`: `auto`, `ask` o `never`.
Lo que hace hoy cada valor, medido en el código:

| | |
|---|---|
| `never` | El hub **no lanza agentes** en ese proyecto: ni los botones que abren `claude` ni el orquestador. Aunque se lo pidas desde la interfaz |
| `ask` | Lo que el hub haría **solo** en ese proyecto te pide confirmación antes. Hoy eso es el orquestador: la primera vez que una tarea quiere tocar el proyecto (abrir una sesión, mandarle trabajo, cambiarle el modelo o compactarla), espera a que lo confirmes en [Orquestador](/orquestador). Se confirma una vez por tarea y proyecto |
| `auto` | No pregunta: el orquestador trabaja ahí con el nivel que le diste |

Lo que lanzas tú con un botón no pide una segunda confirmación: pulsarlo ya es
tu sí.

`never` significa nunca: primero se cambia el guardrail en el registro.

El guardrail **no es el permiso del asistente**. El asistente es de sólo
lectura sobre tus proyectos sea cual sea su guardrail (ver arriba).

## Para aprender el hub

Si acabas de instalarlo, el asistente es la forma más rápida de aprenderlo:

- **Sabe en qué pantalla estás.** Pregúntale «¿qué es esto?» y te lo explica
  sin que tengas que decir dónde estás.
- **Te lleva.** Cuando habla de una pantalla pone el enlace, y en el chat se
  pulsa.
- **Hace contigo lo básico:** registrar un proyecto que ya tienes, crear uno
  nuevo, crear un slot o apuntar una nota. Te pregunta lo que necesita, te
  propone hacerlo y lo hace cuando le dices que sí.
- Con el chat vacío te propone por dónde empezar.

La pantalla **[Guía](/guia)** tiene los primeros pasos. Cada uno se marca solo
cuando el hub ve que está hecho, y su botón **Guíame** le hace al asistente la
pregunta de ese paso.
