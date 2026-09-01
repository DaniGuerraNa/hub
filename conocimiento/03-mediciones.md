# Qué mide el hub, y cómo se leen sus cifras

Todo lo que ves está **medido contra tu disco**, no estimado. Cuando algo no se
puede medir, el hub lo dice en vez de enseñar un cero.

## Respaldo — commits que no están en ningún sitio

Por cada ruta que declaraste: rama, **commits que no alcanza ningún remoto**,
archivos sin commitear, fecha del último commit y worktrees extra.

Dos cosas que conviene saber para leerlo bien:

- **No cuenta «commits por detrás de tu rama»**, cuenta los que no alcanza
  *ningún* remoto. Si trabajas en una rama que no existe en `origin`, la otra
  forma de contarlo daría el historial entero.
- **Los worktrees del mismo repo salen marcados «espejo»** y no suman dos veces.
- **«Sin remoto» no es una alarma**: un repo local puede ser deliberado.

El hub no hace push ni te avisa. Mide y muestra.

## Inventario — lo que has construido

Escanea por convención: `.claude/agents/*.md`, `.claude/skills/*/SKILL.md`,
scripts, y el contenido de los kits. Si un proyecto tiene un `registry.yaml`,
también lo lee para sacar status declarado y contratos.

**Reescanear** repuebla desde el disco (instantáneo). **Reescanear y medir uso**
además recorre los transcripts de Claude Code (~8 s) para saber cuándo se usó
cada cosa **de verdad**, no cuándo la editaste.

Dos etiquetas que no son lo mismo:

| | |
|---|---|
| **sin uso detectado** | Se buscó y no aparece. Puede que se te haya olvidado que existe |
| **uso no medible** | No se puede buscar: un método es un documento que se lee, no algo que se invoque por nombre |

Medirlo todo con la misma vara marcaría los documentos como olvidados siempre, y
eso envenenaría justo la señal que hace útil esta pantalla.

## Servicios — de quién es cada contenedor

Se atribuyen por el prefijo que declaraste. Lo que no declara nadie sale como
**sin dueño**.

- Se arranca y se para **de uno en uno, con confirmación**. No hay «parar todo»,
  y borrar no se expone: en un mismo Docker conviven contenedores de varios
  proyectos, y un `docker stop $(docker ps -q)` se los lleva por delante.
- Si Docker no contesta, el hub enseña **la última lectura buena** y dice que no
  pudo preguntar. Un cero se leería como «no tienes contenedores».

## Conexiones — el puntero, no el secreto

De cada conexión se comprueba una sola cosa: **si su `referencia_secreto`
existe**. Nunca se abre.

| | |
|---|---|
| `puntero ok` | El archivo existe |
| `no existe` | Apunta a algo que no está |
| `no comprobable` | Es una referencia externa (un gestor de secretos) |
| `sin puntero` | No se declaró dónde vive la credencial |

## Contexto — todo en un texto

`/contexto` reúne lo medido y lo que cada proyecto declaró vigente, listo para
pegar al principio de una sesión de Claude. **No lo genera un modelo**: no cuesta
tokens y no puede inventarse nada.

Sólo lista lo que exige acción, y dice explícitamente lo que falta — por ejemplo,
que un proyecto no tiene un bloque de estado legible. En crudo:
`/api/contexto?formato=md`.

## Si una cifra te sorprende

Compruébala. Para el respaldo:

```bash
git -C <ruta> log --oneline HEAD --not --remotes | wc -l
```

Si no coincide con lo que dice el hub, es un fallo del hub y merece mirarse.
