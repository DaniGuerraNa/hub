---
name: aplicar-kit
description: Aplica un kit a un proyecto, o lo actualiza a una versión nueva. Úsala cuando pidan «aplica el kit X», «instala X en este proyecto», «actualiza el kit» o «sincroniza el kit».
---

# Aplicar un kit a un proyecto

Un kit es una capa que aporta una capacidad. Aplicarlo escribe archivos **dentro
del repo de alguien**, así que el orden importa: **primero se mide, después se
enseña, y sólo entonces se escribe lo aprobado.**

## 🔴 Antes de nada: mide

```bash
bash scripts/kit.sh estado <proyecto>
```

Nunca apliques a ciegas. Lo que ya está al día no se toca, y lo que difiere puede
ser un cambio deliberado de esa persona.

## Los tres modos, y por qué se tratan distinto

| Modo | Qué haces | Por qué |
|---|---|---|
| `apuntador` | **NO copies el archivo.** Referencia el del kit desde el `CLAUDE.md` del proyecto | El contenido vive en un solo sitio. Copiarlo es cómo una regla acaba diciendo cosas distintas en tres ficheros |
| `materializado` | Copia el archivo con cabecera *«del kit X vN — no editar aquí»* | Claude Code busca skills y agentes en rutas fijas: si no está físicamente, no existe |
| `copia` | Copia y **personaliza** con los parámetros | Es semilla. Divergir es lo correcto, no un defecto |

Para los `apuntador`, el `CLAUDE.md` del proyecto lleva **un solo bloque** que
los lista:

```markdown
<!-- kits — generado, no editar a mano -->
Este proyecto usa: orquestacion v1.2 · notificar-telegram v1.0
El contenido de cada uno vive en su kit; resuelve la ruta desde el repo del hub
con `bash scripts/kit.sh ruta <id>`.
Si algo de este archivo contradice a un kit, manda el kit.
```

Un único punto de composición: así dos kits no se pelean por el mismo destino.

## Pasos

### 1. Consigue el kit

```bash
bash scripts/kit.sh listar
bash scripts/kit.sh instalar <id> [version]
bash scripts/kit.sh ruta <id> [version]
```

### 2. Enseña el plan y espera

Di, archivo por archivo, qué va a pasar: crear, actualizar, dejar como está. Y
**enseña también lo que no vas a tocar** — quien aprueba necesita ver el alcance
completo, no sólo la parte que cambia.

Tres cosas se dicen siempre, aunque no las pregunten:

- **Lo que difiere**: puede ser un cambio deliberado suyo. Pregunta antes de
  pisarlo. *Una divergencia sin declarar es un defecto; declarada, es una
  decisión* — y declararla es escribir el motivo, no callarse.
- **Los huérfanos**: archivos que puso una versión anterior y la nueva ya no
  pone. **No los borres.** Dilos y que decida.
- **Los binarios que faltan**: si el kit necesita algo que no está en el PATH,
  esa parte no va a funcionar y hay que decirlo ahora, no después.

### 3. Aplica sólo lo aprobado

Respeta el modo de cada archivo. Si algo no encaja —un destino que ya existe con
contenido distinto, un parámetro que no sabes rellenar— **para y pregunta**. Un
kit aplicado a medias es peor que uno no aplicado: parece que está.

### 4. Deja rastro

Actualiza `.claude/hub/kits.yml` del proyecto:

```yaml
kits:
  - id: <kit>
    version: "1.2"
    aplicado: <fecha de hoy>
    parametros: {stack: python}     # si tenía `copia` con parámetros
    destinos:
      - docs/equipo/metodo.md
      - .claude/skills/sesion-autonoma/SKILL.md
```

**`destinos` no es opcional.** Es lo único que permite saber qué sobra cuando el
kit suba de versión o se quite. Sin esa lista, lo que ya no respalda nadie se
queda dentro del repo para siempre.

### 5. Verifica, y verifica que sabe fallar

```bash
bash scripts/kit.sh estado <proyecto>
```

Tiene que salir al día. Y si es la primera vez que aplicas **ese** kit a **ese**
proyecto, haz el control negativo: cambia una línea de un archivo propagado,
vuelve a medir y comprueba que sale `difiere`; restáuralo y comprueba que vuelve
a `igual`.

Un verde que nadie ha visto en rojo no es evidencia de nada.

## Actualizar a una versión nueva

Igual, con dos avisos más:

- Si cambia el **`major`**, el kit dice que rompe. Lee su `CHANGELOG` antes.
- Los archivos en modo `copia` **no se pisan**: salieron para personalizarse. El
  hub avisa de que su origen cambió; rehacerlos es decisión del proyecto.
