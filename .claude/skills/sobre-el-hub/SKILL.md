---
name: sobre-el-hub
description: Responde dudas sobre cómo funciona o cómo se usa el hub. Úsala cuando pregunten «¿cómo hago X en el hub?», «¿qué significa esta cifra?», «¿qué es un slot/kit/guardrail?» o cualquier duda sobre su comportamiento.
---

# Responder dudas sobre el hub

## Cómo

1. **Lee `conocimiento/INDICE.md`** — dice qué documento contesta qué.
2. **Abre sólo el que toque.** Cargarlos todos gasta contexto para nada.
3. Si la pregunta es sobre una cifra concreta del usuario, **míralo en su
   instalación** en vez de explicar cómo se calcula en abstracto:

```bash
curl -s "http://127.0.0.1:8787/api/contexto?formato=md"
bash scripts/kit.sh estado
```

## Qué no inventar

- **El porqué de una decisión de diseño.** El producto trae documentación de uso,
  no el razonamiento detrás. Si preguntan «¿por qué no hace X?», la respuesta
  honesta es que no lo sabes — y es mejor que una explicación plausible.
- **Cifras.** Si el hub dice 250 commits sin respaldo, son 250. Si no lo has
  mirado, no lo digas.
- **Comportamiento que no hayas comprobado.** Ante la duda, corre el comando.

## Al contestar

En español, breve, y con el comando exacto cuando lo haya. Si la respuesta está
en un documento, **dile cuál**: así la próxima vez no necesita preguntarte.
