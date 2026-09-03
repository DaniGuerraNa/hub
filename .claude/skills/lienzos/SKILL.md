---
name: lienzos
description: "Publica un lienzo (diagrama, lista de decisiones, pasos o comparativa) para que se vea en la web del hub en vez de soltarlo como texto. Úsala cuando vayas a entregar algo denso, por ejemplo una arquitectura con varios servicios, un informe con muchos puntos que él tiene que decidir, una secuencia de pasos o una comparación entre opciones. También cuando él diga «hazme un diagrama», «enséñamelo» o «ponlo en el hub»."
---

<!-- Del kit `lienzos` v0.1 — no editar aquí; el original está en el kit. -->
# Publicar un lienzo

Un lienzo es contenido que se **ve** en el hub en vez de leerse en la terminal.
Claude Code no puede pintar imágenes en su TUI; el hub sí, porque es un
navegador.

## 🔴 La regla que decide si merece la pena

**Un lienzo SUSTITUYE texto. No lo acompaña.**

Si después de publicarlo tienes que repetir el contenido en la terminal, el
lienzo sobra: le has dado una cosa más que mirar a alguien que ya estaba
saturado, que es exactamente el daño que esto existe para evitar.

Publicar bien:

> ● Son 8 puntos y cada uno pide una decisión tuya, así que te lo dejo como
>   lienzo en vez de soltarlo aquí de corrido.
>   ✓ `revision-facturacion` — márcalos y avísame.

Publicar mal:

> ● Aquí van los 8 puntos: 1) el contador… 2) el IVA… *(y los ocho enteros)*
>   Además te lo he dejado como lienzo.

## Cuándo sí

- **Un informe con muchos puntos que él tiene que decidir.** Es el caso que más
  atención le ahorra: plegados, decide de uno en uno en vez de sostener treinta
  en la cabeza a la vez.
- **Una arquitectura** con más de tres piezas y flujo entre ellas.
- **Una secuencia** cuyo orden es la respuesta (orden de ejecución, un pipeline).
- **Una comparación** entre opciones con varios criterios.

## Cuándo NO

- **Tres viñetas.** Se leen mejor en prosa, y en la terminal ya las tiene.
- **Una sola cosa**, por muy importante que sea. Un lienzo de un nodo es ruido.
- **Para adornar.** Si el texto ya se entiende, el lienzo resta.
- **Cuando él está esperando una respuesta corta.** Publicar es un rodeo:
  contesta y, si acaso, ofrece el lienzo después.

🔴 Un asistente que contesta todo con diagramas es peor que uno que no dibuja
ninguno. Ante la duda, **no publiques**: es más fácil añadir un lienzo que
quitarle la costumbre.

## Cómo se publica

```bash
hub lienzo nuevo --proyecto <id> --titulo "Lo que es" \
                 --plantilla decisiones --slot <slot> --cuerpo -
```

El cuerpo va por la entrada estándar (`--cuerpo -`) porque son varias líneas:
meterlas en un argumento obliga a escapar comillas y saltos, y ahí se rompe.

El comando devuelve el `id`. **Díselo siempre** — es lo que él escribe en el
buscador del panel para encontrarlo.

## Las plantillas

Están en `.claude/hub/lienzos/`. **Lee sólo la que vayas a usar**: cargarlas
todas gasta contexto en formatos que no vas a escribir.

| Plantilla | Para qué |
|---|---|
| `decisiones` | Puntos con su justificación y una decisión suya |
| `arquitectura` | Piezas y el flujo entre ellas |
| `pasos` | Una secuencia donde el orden es lo que importa |
| `comparativa` | Opciones contra criterios |

```bash
cat .claude/hub/lienzos/decisiones.md      # el formato y un ejemplo
```

## 🔴 Si ya existe y él lo ha editado

El comando fallará diciendo:

> `«x» ya existe y lo editaste tú. Usa --revisar para publicarlo al lado, o
> --forzar para pisarlo.`

**No uses `--forzar` por tu cuenta.** Ese archivo tiene trabajo suyo dentro —
puede haber estado veinte minutos corrigiéndolo—, y pisarlo no deja rastro: el
panel enseñará un lienzo perfectamente válido y él no se enterará de que perdió
lo suyo.

Lo que se hace:

1. **Léelo primero**: `hub lienzo ver <proyecto> <id>`. A lo mejor lo que
   corrigió ya responde a lo que ibas a cambiar.
2. Si sigue haciendo falta uno nuevo, `--revisar`: se publica al lado.
3. `--forzar` sólo si **él** lo pide.

## Cuando él lo corrija

El hub **no te avisa**, y es a propósito: nada automático (principio 9). Él te
dirá «ya lo edité, léelo». Entonces:

```bash
hub lienzo ver <proyecto> <id>
```

Y si estás trabajando sobre un lienzo que publicaste hace rato, **reléelo antes
de seguir**: puede haber cambiado sin que nadie te lo dijera.

Lo que él corrige es lo que quiere. No lo deshagas en la siguiente publicación:
si su cambio choca con lo que ibas a proponer, **dilo** en vez de sobrescribirlo.

## Qué NO hacer

- **No publiques el mismo lienzo dos veces** por si acaso. Se acumulan en su
  proyecto y borrarlos es trabajo suyo: el hub no poda nada solo.
- **No inventes el `id`**: sale del título, y lo devuelve el comando.
- **No metas cifras que no hayas medido.** Un lienzo se lee de un vistazo y por
  eso se cree más que un párrafo; una cifra inventada ahí hace más daño.
- **No uses un lienzo para esconder que no sabes algo.** Un diagrama vago parece
  más sólido que una frase honesta, y no lo es.
