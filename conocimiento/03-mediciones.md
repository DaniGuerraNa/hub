# Qué mide el hub, y cómo se leen sus cifras

Todo lo que ves está **medido contra tu disco**, no estimado. Cuando algo no se
puede medir, el hub lo dice en vez de enseñar un cero.

**Las fechas van en tu hora y con cuánto hace.** Toda fecha de pantalla sale
en la hora de tu casa (la zona de la máquina, o `TZ` si la pones) y en una sola
forma: «13/11 14:41», con el año sólo si no es el actual, y «hace 3 h» al lado
o al pasar el puntero. Cuando una **medición** (la última muestra, la lectura
de Docker, el respaldo, la máquina, la copia de la base) lleva más de lo que el
hub promete entre lectura y lectura, su fecha sale en ámbar: lo de abajo no es
de ahora. La actividad de tus slots, proyectos e ideas nunca se pinta así: el
hub no te dice cuánto llevas sin tocar algo.

## Respaldo — commits que no están en ningún sitio

Por cada ruta que declaraste: rama, **commits que no alcanza ningún remoto**,
archivos sin commitear, fecha del último commit y worktrees extra.

Dos cosas que conviene saber para leerlo bien:

- **No cuenta «commits por detrás de tu rama»**, cuenta los que no alcanza
  *ningún* remoto. Si trabajas en una rama que no existe en `origin`, la otra
  forma de contarlo daría el historial entero.
- **Los worktrees del mismo repo salen marcados «espejo»** y no suman dos veces.
- **«Sin remoto» no es una alarma**: un repo local puede ser deliberado.
- **Una medición puede quedar incompleta.** Cada vuelta tiene un tiempo
  máximo, y un repo en un disco lento, o cuyo git falla, se queda con la cifra
  de la vuelta anterior. Entonces, junto a «Última medición», sale
  «incompleta: N de M repos medidos; el más viejo, del …», y la fila de cada
  repo que no se midió lleva «medido el …».

El hub no hace push ni te avisa. Mide y muestra.

### Los datos del propio hub

Debajo de las cifras, «Los datos del hub» dice cuándo se copió por última vez
la base del hub (`hub.db`). Ahí viven cosas que no están en ningún repo: tus
slots y sus notas, el canal, los mensajes programados y los encargos. El hub
la copia solo **una vez al día** en `~/.local/share/hub/respaldos/` (o donde
diga `HUB_RESPALDO`) y guarda las **14 últimas**. Si la última tiene más de dos
días, la fila sale en rojo: algo impide copiarla, y conviene mirarlo.

Si usas el secretario, debajo sale también **la copia de su memoria**, con la
misma regla de los dos días. Esa copia la hace el propio secretario mientras
está en marcha, en la misma carpeta; si sale vieja, mira que el secretario
corra. En Máquina → Salud del hub aparecen las dos.

Cada copia se **comprueba al hacerla** (`PRAGMA quick_check`): si no pasa, no
se guarda, la fila lo dice en rojo («no pasó la comprobación») con lo que
encontró, y se vuelve a intentar sola pasada una hora. Si pasa, debajo pone
«Comprobada al hacerla».

🔴 Esa carpeta está **en el mismo disco**. Para que tus notas sobrevivan a un
disco muerto, dale al hub una **segunda carpeta en otro disco**: la copia se
hace igual en local y después se lleva el archivo allí, con la misma regla de
las 14 últimas (también la de la memoria del secretario). Se enciende de una
de dos formas, sin reiniciar nada:

- escribe la ruta en una línea en `~/.local/share/hub/respaldo-extra.txt`:

  ```bash
  echo /ruta/en/otro/disco/respaldos > ~/.local/share/hub/respaldo-extra.txt
  ```

- o pon `HUB_RESPALDO_EXTRA` en el entorno de los servicios (manda sobre el
  archivo).

La carpeta tiene que **existir**: el hub no la crea, para no llenar el disco
de siempre si el otro no está montado. Si no existe o no se puede escribir, la
copia de siempre se hace igual y la fila lo dice («sin segunda copia») con el
motivo; cuando el disco vuelve, la copia de ese día llega sola. Con ella
funcionando, pone «También en otro disco» y cuántas hay allí. Tus datos para
los trámites (`mis-datos.yml`) no van ni a una carpeta ni a la otra.

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

- Se arranca, se para y se reinicia **de uno en uno, con confirmación**. No hay «parar todo»,
  y borrar no se expone: en un mismo Docker conviven contenedores de varios
  proyectos, y un `docker stop $(docker ps -q)` se los lleva por delante.
- Si Docker no contesta, no está instalado o no hay lectura nueva desde hace
  media hora, el hub enseña **la última lectura buena** con su fecha («corrían
  el 02/11 04:07», «visto el…») y dice por qué no es la de ahora. Un cero se
  leería como «no tienes contenedores». Mientras tanto no se ofrece arrancar,
  parar ni reiniciar (los botones salen apagados) y el menú no cuenta
  contenedores en marcha.

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
