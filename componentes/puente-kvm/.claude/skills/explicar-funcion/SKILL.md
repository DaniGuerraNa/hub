---
name: explicar-funcion
description: Explica qué hace un procedimiento, función o vista del Mac — propósito, parámetros, flujo por bloques con sus líneas, qué tablas lee y escribe, efectos y riesgos. Úsala con «dime qué hace esta función», «explícame este SP», «¿qué toca esto?».
---

# Explicar qué hace

**Acceso:** sólo lectura. Si el texto no está aún aquí, la skill
`leer-documento` necesita el control para capturarlo; explicar no toca el Mac.

1. **Ten el texto exacto.** Si no hay una lectura verificada del objeto, usa
   `leer-documento`. Si la persona tiene prisa y acepta una lectura sin
   verificar, dilo en la respuesta: «basado en una copia no verificada».
2. **Lee la copia de `trabajo/`** entera (con Read, no desde las capturas).
3. **Explica en este orden**, citando líneas (`L120–L158`):
   - **Para qué sirve**, en dos o tres frases, como se lo dirías a alguien de negocio.
   - **Parámetros**: cada uno, su tipo, su valor por omisión y qué cambia.
   - **El recorrido**: los bloques en orden, qué hace cada uno y por qué parece
     estar ahí. Si se repite un patrón (p. ej. un bloque por tipo de documento),
     explícalo una vez y lista las variantes.
   - **Qué toca**: tablas y vistas que **lee**, las que **escribe**
     (INSERT/UPDATE/DELETE/MERGE), tablas temporales, otros procedimientos y
     funciones a los que llama.
   - **Efectos y riesgos**: transacciones, manejo de errores, lo que pasa si
     falla a mitad, bloqueos (`NOLOCK`, transacciones largas), y lo que te
     parezca raro o inconsistente (comentarios que no casan con el código, etc.).
4. **Guárdalo** en `trabajo/notas/<objeto>.md` para no tener que releerlo la
   próxima vez, con la fecha y la lectura de la que sale.

No propongas cambios aquí salvo que te los pidan: para eso están
`revisar-rendimiento` y `proponer-cambio`.
