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

Después declara en tu registro el bloque `tipo: asistente` que el script imprime.

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
`Write`, `rm`, `mv`, `git commit`, `git push`, `git checkout`, `docker` y
`systemctl`.

## Cómo leer la pestaña

- El **porcentaje** es su contexto ocupado. Se pone naranja al 70 %.
- La **luz** dice si está vivo o pensando.
- **Terminal** abre su sesión cruda, por si hace falta ver lo que hay debajo.

Si Claude Code le pide permiso para algo, el cuadro aparece **en el chat** con
dos botones. Sin eso la conversación se quedaría muda sin decir por qué.

## Guardrails

Cada proyecto declara en el registro cuánto permiso tiene el asistente:

| | |
|---|---|
| `auto` | Puede ejecutar |
| `ask` | Pregunta antes |
| `never` | **Nunca**, aunque se lo pidas desde la interfaz |

`never` significa nunca: primero se cambia el guardrail en el registro.
