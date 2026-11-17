---
name: revisar-rendimiento
description: Revisa por qué un procedimiento o consulta del Mac tarda mucho y propone cómo mejorarlo, con evidencia (definiciones de tablas, índices, plan) traída del cliente de BD. Úsala con «revisa esta función, dicen que tarda», «¿por qué va lento?», «optimiza este SP».
---

# Revisar el rendimiento

**Acceso:** leer el texto (control para capturar); traer evidencia con
`consultar-catalogo` (control para escribir la consulta; **ejecutarla es de la
persona**); cambiar el SP sólo con `proponer-cambio` (aprobación de la persona).
**Nunca** ejecutes nada en la base, ni crees índices: los propones como script.

## 1. El texto

Lectura verificada del objeto (skill `leer-documento`) y su explicación si no la
hay (`explicar-funcion`, o al menos el recorrido por bloques).

## 2. Sospechas, desde el código

Repasa el texto buscando lo que suele costar caro, y anota cada sospecha con su
línea y por qué:

- Bucles fila a fila: cursores, `WHILE` con consultas dentro.
- Funciones sobre columnas en `WHERE`/`JOIN` (`dbo.fn(x) = …`, `CONVERT`,
  `ISNULL(col, …)`, `LIKE '%…'`): impiden usar índices.
- Conversiones implícitas (parámetro `NVARCHAR` contra columna `VARCHAR`).
- Funciones escalares definidas por el usuario dentro de consultas grandes.
- `SELECT *`, `DISTINCT` u `ORDER BY` innecesarios; `OR` en joins.
- Tablas temporales grandes sin índice, o variables de tabla con muchas filas.
- El mismo cálculo o la misma consulta repetidos por bloque.
- Transacciones largas, `NOLOCK` que esconden otros problemas, *parameter
  sniffing* (rangos de fechas muy variables según el parámetro).

## 3. Evidencia, desde la base

Pide sólo lo que hace falta para confirmar o descartar las sospechas, y dile a
la persona **qué vas a traer y por qué**:

- Columnas e índices de las tablas que más pesan.
- Tamaño (filas) de esas tablas.
- El plan estimado en texto de la parte sospechosa.
- Si la persona puede, estadísticas reales (`SET STATISTICS IO, TIME ON`) de una
  ejecución que ELLA decida hacer, en un entorno donde se pueda.

Cómo traerla: skill `consultar-catalogo`. No adivines índices que no has visto.

## 4. Diagnóstico y propuesta

1. Ordena las causas de más a menos impacto, cada una con su evidencia
   (línea del SP + dato del catálogo/plan). Lo que no esté probado, dilo como
   hipótesis.
2. Para cada una, la propuesta: el cambio en el SP, o un índice (como script
   `CREATE INDEX …` en `trabajo/propuestas/`, **para que lo revise y lo cree
   quien deba**), y el riesgo del cambio.
3. Si hay cambios en el SP: edita `trabajo/<objeto>.sql` y sigue la skill
   `proponer-cambio`.
4. Deja el diagnóstico en `trabajo/notas/<objeto>-rendimiento.md`.
