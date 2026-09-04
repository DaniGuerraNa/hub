---
name: mantener-kit
description: Mantiene un kit — mide su deriva en los consumidores, propaga cambios y publica versiones. Úsala cuando pidan «mantén el kit X», «sincroniza el kit», «propaga este cambio» o «publica una versión del kit».
---

# Mantener un kit

**Este procedimiento vive una vez, en el hub, y sirve para todos los kits.** Las
particularidades de cada uno están en su `mantenimiento:` — léelo antes de
empezar. Si cada kit llevara su propio agente mantenedor, cambiar el método
obligaría a actualizar N agentes que dicen casi lo mismo, que es justo el
problema que los kits vinieron a resolver.

## Empieza por verificar, nunca por aplicar

```bash
bash scripts/kit.sh estado          # todos los proyectos que declaran kits
bash scripts/kit.sh arbol           # quién provee qué, y qué se pide sin proveedor
```

Y si el kit declara un `verificar:` en su manifiesto, córrelo también.

## Cómo se lee lo que sale

| | Qué significa |
|---|---|
| `igual` | Al día. No se toca |
| `difiere` | 🔴 **Puede ser un defecto o una decisión.** Hay que averiguar cuál |
| `falta` | El consumidor no tiene ese archivo |
| `al-dia` | Una copia salida de esta misma versión. No se compara por contenido |
| `origen-cambiado` | Una copia de una versión anterior. Se avisa; no se propaga |
| `sin-origen` | 🔴 El kit ya no trae ese archivo pero sigue declarado |
| huérfano | Lo puso una versión anterior y la actual ya no. **No lo borres** |

> **Una divergencia sin declarar es un defecto. Una divergencia declarada es una
> decisión.**

Ante un `difiere`, la pregunta no es «¿lo propago?» sino **«¿por qué difiere?»**.
Mira el diff y pregunta a quien mantiene ese proyecto. Si el cambio local era
deliberado, se **declara con su motivo**; si no, se propaga.

## Propagar un cambio

1. Cámbialo **en el kit**, nunca en el consumidor.
2. Sube la versión: `minor` si añade o corrige, `major` si rompe.
3. Escribe el `CHANGELOG` con **qué cambió, cuándo y quién lo decidió**. Lo
   tercero es lo que permite reevaluarlo después.
4. `git tag vX.Y`. **Un tag publicado no se mueve**: si hay que corregirlo, se
   publica el siguiente. Reescribir un tag hace que toda la deriva medida contra
   él pase a mentir sin avisar.
5. Aplica a cada consumidor con la skill `aplicar-kit`, **uno por uno**. Nunca
   en lote: cada proyecto puede tener sus divergencias declaradas.

## Lo que la comparación de archivos NO ve

Hay divergencias de **método**, no de fichero. Un kit puede estar byte a byte
idéntico en dos proyectos y significar cosas distintas en cada uno — por ejemplo,
una regla de revisión cruzada que en un proyecto se cumple con dos proveedores y
en otro se sustituye por «modelo distinto, contexto limpio». Los archivos salen
`igual` y la regla está debilitada.

Eso no lo detecta ninguna herramienta. Cuando lo veas, **escríbelo en el kit**,
donde se lea.

## Antes de dar el mantenimiento por hecho

- ¿La deriva vuelve a estar limpia, o quedan divergencias **declaradas con su
  motivo**?
- ¿El `CHANGELOG` dice quién decidió?
- ¿Se ha visto el instrumento fallar? Rompe un archivo propagado, comprueba que
  sale `difiere`, restaura, comprueba que vuelve.
- Si la versión la va a instalar **otra persona**: pásala por la sala limpia
  (`scripts/sala-limpia/sala.sh`, procedimiento en
  `producto/conocimiento/08-sala-limpia.md`) y anota turnos y preguntas en el
  `README` del kit. Lo que aquí funciona con tu `~/.claude` y tu tmux abierto
  no es lo que va a ver quien lo reciba.
