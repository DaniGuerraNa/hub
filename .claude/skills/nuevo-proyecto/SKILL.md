---
name: nuevo-proyecto
description: Crea un proyecto nuevo con la capa base y los kits que elija. Úsala cuando pidan «crea un proyecto», «arranca un proyecto nuevo» o «empieza algo nuevo con el hub».
---

# Crear un proyecto nuevo

El reparto, y conviene tenerlo claro antes de empezar:

| Quién | Qué pone |
|---|---|
| **El hub** | La **identidad**: el alta en el registro y la capa base |
| **Los kits** | La **forma de trabajar**: método, roles, skills, herramientas |

El hub no impone una metodología. Si el usuario quiere una, viene de un kit.

## Pasos

### 1. Pregunta lo mínimo, y sólo una vez

- **Nombre y para qué es.** Con eso sale el `id` (minúsculas, guiones, sin
  acentos). El `id` no cambiará nunca; el nombre sí.
- **Dónde va la carpeta.**
- **Personal o laboral.** Determina el `dominio` y, con él, el `guardrail`: en
  lo laboral, `never` por defecto.

No preguntes por el stack ni por la estructura: eso lo decide el proyecto cuando
tenga algo que decidir, y adelantarlo produce carpetas vacías que nadie llena.

### 2. Crea la carpeta y su git

```bash
mkdir -p <ruta> && cd <ruta> && git init -b main
```

Con git desde el minuto uno: el hub mide commits sin respaldo, y un proyecto sin
git es invisible para esa medición — que es la razón por la que el hub existe.

### 3. Aplica la capa base

```bash
bash scripts/kit.sh ruta base       # dónde está la semilla
```

Copia sus tres archivos a `.claude/hub/` del proyecto nuevo y **rellena los
marcadores** (`@ID@`, `@NOMBRE@`, `@ESTADO_REF@`, `@FECHA@`).

`estado_ref` apunta al documento que llevará el estado. En un proyecto nuevo
todavía no existe: créalo **vacío pero con su forma** —qué estado tiene, qué hacer
al volver, qué está bloqueado— y apúntalo. Es el único documento que el hub
espera de todos.

### 4. Ofrece kits

```bash
bash scripts/kit.sh listar
```

No apliques ninguno por tu cuenta: un kit trae archivos, reglas y a veces
agentes, y meterlos sin pedirlo es decidir por otro cómo va a trabajar.

**Cómo ofrecerlos depende de si hay alguien delante**, y esto no es un matiz:

- **Con alguien en la conversación**: enseña qué hay, con qué aporta cada uno, y
  deja elegir. Para cada elegido, la skill `aplicar-kit`.
- 🔴 **Si te lanzó el hub** —ventana abierta desde el chat del asistente—:
  **NO preguntes.** Nadie está mirando esa ventana, así que la pregunta no
  espera a nadie: deja el trabajo colgado y desde fuera se ve como «está
  trabajando», porque el hub sólo distingue `trabajando` de `detenido`. Pon la
  lista en tu resumen final y termina. La decisión se toma después, en la
  conversación donde sí hay alguien.

Se sabe cuál es el caso por cómo empezó: si lo primero que viste fue un encargo
ya escrito con la carpeta creada y el alta hecha, te lanzó el hub.

### 5. Da de alta en el registro

Añade el bloque a `~/.local/share/hub/projects.yml`. Mismo formato que en
`anexar-proyecto`.

### 6. Comprueba

```bash
bash scripts/kit.sh estado <id>
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8787/
```

Y dile qué tiene: la ruta, qué kits lleva, dónde está su documento de estado y
que el hub ya lo vigila.

## Qué NO hacer

- **No montes una estructura de carpetas «estándar»** (`src/`, `tests/`, `docs/`)
  si no sabes aún qué se va a construir. Carpetas vacías no son un andamio: son
  ruido que hay que ir borrando.
- **No copies la configuración de otro proyecto** «porque funcionó allí». Eso es
  exactamente cómo una plantilla se convierte en la copia de un proyecto ajeno,
  con sus rutas y su stack dentro.
- **No apliques kits sin preguntar.**
