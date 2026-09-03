---
name: anexar-proyecto
description: Registra en el hub un proyecto que ya existe. Úsala cuando pidan «anexa mi proyecto», «registra este repo en el hub», «añade X al hub» o quieran que el hub empiece a vigilar algo que ya tienen.
---

# Anexar un proyecto que ya existe

El hub indexa; no reorganiza. Anexar un proyecto es **declarar lo que ya hay**,
no imponerle una estructura.

## 🔴 La regla que ordena todo esto

**No crees un documento de estado nuevo.** Casi todos los proyectos ya tienen uno
—`ESTADO.md`, un checkpoint, un `contexto-tecnico.md`, un `registry.yaml`—, y
añadir otro produce exactamente el problema que el hub existe para resolver:
sobran documentos y falta saber cuál está vigente.

Tu trabajo es **encontrar cuál lo está** y apuntar a él.

## Pasos

### 1. Mira qué hay antes de escribir nada

```bash
ls -la <ruta-del-proyecto>
git -C <ruta-del-proyecto> log --oneline -5 2>/dev/null
```

Busca, en este orden, cuál es su documento de estado vigente:

1. Uno que se llame `ESTADO`, `PUNTO-DE-RETOMA`, `CHECKPOINT`, `HANDOFF` o
   parecido, **con fecha reciente**.
2. Un `docs/` con checkpoints: coge el **más nuevo**, y compruébalo mirando su
   contenido, no sólo su nombre.
3. Un `README` que de verdad diga en qué punto está el trabajo.
4. Nada de lo anterior. Entonces `estado_ref` se queda **vacío** y se dice: no
   tener puntero es información, y es mejor que inventarse uno.

Si dudas entre dos, **pregunta**. Elegir mal aquí hace que el hub enseñe como
«estado actual» algo de hace tres meses, y eso es peor que no enseñar nada.

### 2. Localiza sus repos y sus contenedores

El asiento —desde dónde se trabaja— **no siempre es donde vive el código**. Un
proyecto puede orquestarse desde una carpeta y tener sus repos en otra. Pregunta
si hay más rutas: **lo que no se declara, no se mide**, y un repo sin medir es un
repo que se puede dar por respaldado sin estarlo.

Si usa Docker, apunta el **prefijo** de sus contenedores (`mi-proyecto-`), no los
nombres exactos.

### 3. Declara en el registro

Edita `~/.local/share/hub/projects.yml` (o el que resuelva
`python -m hub.kits_cli` si hay `HUB_HOME` propio) y añade el bloque. El archivo
trae los campos comentados.

- El `id` es la identidad y **no cambia nunca**: los slots y las notas cuelgan
  de él. El `nombre` es sólo la etiqueta, y ése sí se cambia cuando quieras.
- `guardrail: ask` salvo que el usuario diga otra cosa. Para trabajo laboral o
  para algo delicado, `never`.
- **Si es un workspace que contiene repos** —una carpeta de trabajo con
  `{ambiente}/repos/{repo}` dentro, cada uno con su git— no le hagas `git init`
  ni le crees un documento de estado. Declara los repos con un patrón y deja
  `estado_ref` vacío:

  ```yaml
  rutas:
    - patron: "*/repos/*"
  ```

  El hub lo resuelve al leer contra el disco y mide cada repo que encaje y tenga
  `.git`. Un patrón sin coincidencias no es un error: el workspace acaba de
  instalarse.

No hace falta reiniciar nada: el siguiente ciclo lo recoge.

### 4. Ofrece la capa base

```bash
bash scripts/kit.sh estado <id>
```

Si el proyecto no tiene `.claude/hub/`, propón sembrar el kit `base`: son tres
archivos —`project.yml`, `capabilities.yml` y `kits.yml`— que le dan identidad
propia, para que el proyecto se describa a sí mismo aunque el registro se pierda.

**Pregunta antes de escribir dentro de su repo.** Es su proyecto; el hub sólo
propone.

#### 🔴 Si NO puede modificar el repo

Pasa más de lo que parece: repos de otro equipo, con revisión obligatoria, o
simplemente que no le toca reorganizar. **Si te lo dice, no insistas ni busques
la forma de colar los tres archivos** — hay una salida pensada para esto, y es la
que tienes que ofrecerle.

Se llama **asiento de orquestación**: una carpeta **nueva y aparte**, que pasa a
ser el `asiento` del proyecto, y el repo intocable se declara en `rutas`.

```yaml
  - id: plataforma
    nombre: Plataforma
    asiento: ~/proyectos/plataforma-main     # NUEVA, vacía, la creas tú
    rutas:
      - ruta: /ruta/al/repo-que-no-se-toca   # se mide, no se toca
      - ruta: /ruta/a/otro-repo-suyo
```

Con eso:

- La capa base, los kits y el documento de estado van **en el asiento**. El hub
  siembra ahí porque `prompt_sembrar` usa el `asiento`.
- Los repos declarados se siguen midiendo enteros —ramas, commits sin respaldar,
  worktrees, cambios sin commitear— sin que nadie escriba una línea en ellos.
- Si el proyecto YA estaba anexado apuntando al repo, esto es **mover una línea**
  en `projects.yml`: el repo baja de `asiento` a `rutas`, y arriba va la carpeta
  nueva. El `id` no se toca — los slots y las notas cuelgan de él.

Dos cosas que comprobar antes de darlo por hecho:

1. **La carpeta del asiento tiene que existir** y, si el código vive en ella,
   conviene que tenga `git init`: el hub mide commits sin respaldo, y una carpeta
   sin git es invisible para esa medición. Si el asiento es un workspace que
   **contiene** repos, no: ahí lo que se mide son los repos, por `patron:`.
2. **Lo que declares en `rutas` tiene que existir de verdad.** Lo que se declara
   se mide, y medir una carpeta que no está no da error: da un cero, y un cero en
   «commits sin respaldo» se lee como «todo a salvo».

Para un proyecto que empieza de cero, esto mismo está en la portada: **«Proyecto
nuevo»**, con los repos en «Repos que ya existen». Ahí el hub además acota el
permiso del agente al asiento, así que los repos declarados quedan fuera de lo
que puede escribir.

### 5. Comprueba que el hub lo ve

```bash
curl -s "http://127.0.0.1:8787/api/contexto?formato=md" | head -30
```

Enseña qué ha detectado —repos, commits sin respaldo, contenedores, estado— y
**contrasta la cifra con la realidad**. Si dice «250 commits sin respaldo»,
verifica con `git -C <ruta> log --oneline HEAD --not --remotes | wc -l` antes de
dársela por buena. Una cifra que no se puede defender no se muestra.

## Qué NO hacer

- **No muevas ni reorganices nada** dentro del proyecto. El hub apunta.
- **No inventes un `estado_ref`** que no existe: déjalo vacío y dilo.
- **No declares rutas que no existan** para «dejarlo preparado». Lo que se
  declara se mide, y medir sobre algo inexistente produce cifras falsas.
