# Flujos — qué hacer y con qué

Siete procedimientos, todos como **skills de Claude Code** en `.claude/skills/`.
Abres Claude Code en la carpeta del hub y lo pides con tus palabras.

| Quiero… | Skill | Se pide diciendo |
|---|---|---|
| Poner el hub a funcionar | `instalar-hub` | «instala este repo» |
| Que el hub vigile algo que ya tengo | `anexar-proyecto` | «anexa mi proyecto» |
| Empezar algo nuevo | `nuevo-proyecto` | «crea un proyecto» |
| Darle una capacidad a un proyecto | `aplicar-kit` | «aplica el kit X aquí» |
| Fabricar una capacidad reutilizable | `nuevo-kit` | «quiero un kit para X» |
| Cuidar un kit que ya usa gente | `mantener-kit` | «mantén el kit X» |
| Entender qué es y qué hace el hub | `sobre-el-hub` | «explícame el hub» |

## Por qué son skills y no botones

Anexar, crear y aplicar **escriben archivos dentro del repo de un proyecto**, y
el hub tiene prohibido hacer eso: *el hub indexa; nunca mueve ni copia contenido
de otros proyectos*. No es una limitación que haya que rodear — es lo que hace
que estas operaciones sean revisables.

El reparto es siempre el mismo:

> **El hub calcula y propone. Un agente, corriendo en ese repo y contigo mirando,
> escribe.**

## Crear un proyecto sin salir del chat

`nuevo-proyecto` es la única que además se puede pedir al asistente, y **sin
romper el reparto de arriba**: el asistente no escribe nada.

```
hub nuevo-proyecto --id mi-app --nombre "Mi App" --ruta /ruta/absoluta/mi-app
```

Lo que pasa cuando lo pides:

| Quién | Qué hace |
|---|---|
| **El hub** | Crea la carpeta **vacía** con `git init`, la acota con permisos, da el alta en su registro y marca esa carpeta como de confianza en tu `~/.claude.json` |
| **Un agente** | La rellena, en una ventana que ves en `/trabajo`, **dentro de esa carpeta y sólo dentro** |

🔴 **Ese apunte en `~/.claude.json` es el único efecto fuera del hub y del
proyecto nuevo**, así que conviene saberlo: Claude Code descarta la lista entera
de permisos concedidos en un workspace que no está marcado como de confianza, de
modo que sin esa línea el agente arrancaría sin poder escribir ni en su propia
carpeta. Se añade una entrada por proyecto creado, y sólo para la carpeta que
acaba de crearse; nada de lo que ya tenías se toca.

Funciona porque un proyecto nuevo empieza en blanco: ahí no hay nada que
sobrescribir. Pero eso **se comprueba, no se supone** — si la ruta apunta a una
carpeta con contenido, el hub lo rechaza y te manda a `anexar-proyecto`, que
registra lo que ya existe sin tocarlo. Equivocarse de ruta dictándola por chat es
fácil, y es justo el caso en que un permiso amplio haría daño.

El agente arranca con lo justo: escribir en su carpeta, leer el procedimiento y
las semillas del hub, y consultar el catálogo de kits. **Lo que se salga de ahí
te lo pregunta a ti**, en su ventana. Que pregunte no es un fallo: es la última
señal de que algo se sale del guion.

Aplicar kits **no** se hace así. Ahí el asistente te da el plan y el prompt, y la
escritura la sigues haciendo con Claude Code — un kit toca muchos archivos de un
repo con historia, y ese es el momento en que quieres ver los diffs.

## El orden habitual

```
instalar-hub  →  anexar-proyecto  →  aplicar-kit
                 nuevo-proyecto   ↗
```

Y cuando algo se repite en dos proyectos y quieres que deje de estar duplicado:
`nuevo-kit`, y luego `mantener-kit` cada vez que cambie.

## Las tres ideas que hay detrás

**Capas.** Un proyecto es la capa base obligatoria más 0..N kits. Un kit es «una
librería que aporta funcionalidades al aplicarse sobre un proyecto».

**Capacidades, no nombres propios.** Un kit no depende de «telegram»: depende de
`notificar#enviar-mensaje`. El día que lo provea Slack, quien lo consume no se
entera. Lo que nadie provee **se dice en voz alta**.

**Se apunta lo que se lee, se materializa lo que otro programa busca en una ruta
fija, se copia lo que se edita.** Es la regla que decide, para cada archivo de un
kit, qué pasa con él en el consumidor.

## La línea de comandos

Las skills se apoyan en esto, y funciona **sin el hub levantado**:

```bash
bash scripts/kit.sh listar               # qué kits hay, y cuáles tienes
bash scripts/kit.sh instalar <id> [v]    # clona el tag de esa versión
bash scripts/kit.sh ruta <id> [v]        # dónde está — lo que resuelve un apuntador
bash scripts/kit.sh estado [proyecto]    # qué está al día y qué ha derivado
bash scripts/kit.sh arbol                # quién provee qué, y qué falta
bash scripts/kit.sh verificar <ruta|id>  # ¿el manifiesto es válido?
```
