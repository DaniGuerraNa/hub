---
name: consultar-catalogo
description: Trae del cliente de BD del Mac información de solo lectura — columnas e índices de una tabla, dependencias, tamaños, el plan estimado o la huella de un objeto — escribiendo la consulta en una pestaña nueva para que la persona la ejecute, y leyendo el resultado. Úsala cuando otra tarea necesite datos del catálogo o la huella.
---

# Consultar el catálogo (solo lectura)

**Acceso:** necesitas el control para abrir una pestaña y teclear (te pedirá
permiso en la terminal para `teclear`/`atajo`: es lo esperado). **La consulta la
ejecuta la persona**, siempre. Sólo consultas de lectura: `SELECT` sobre el
catálogo, procedimientos de sistema que sólo leen (`sp_helpindex`,
`sp_spaceused`) y `SHOWPLAN`. Nada de `INSERT/UPDATE/DELETE/MERGE`, DDL ni
ejecutar procedimientos de la aplicación.

## Cómo

1. `ver_pantalla()`: localiza el cliente. Atajos en `trabajo/entorno.md`
   (por omisión DBeaver en Mac: **Cmd+]** abre un script SQL nuevo).
2. Pestaña nueva, y `teclear` la consulta. **No pulses ejecutar.**
3. Dile a la persona: «He dejado esta consulta en una pestaña nueva: <qué trae>.
   Revísala y ejecútala tú (Cmd+Enter)». Espera a que te diga que ya está.
4. Lee el resultado:
   - **Pocas filas:** `ver_pantalla(x, y, ancho, alto)` con la zona de la
     rejilla, que llega a tamaño real (la pantalla entera llega reducida).
   - **Más filas de las que caben, pero cortas:** `recorrer_pantalla` sobre la
     zona de la rejilla, desde la primera fila: la baja con la rueda y te da
     todas las páginas en una sola llamada, con lo que se repite entre una y
     otra.
   - **Muchas filas o texto largo** (un plan, una definición): llévalo a un
     editor y léelo con la skill `leer-documento`. Con el control: clic en la
     rejilla, Cmd+A, Cmd+C, pestaña nueva (Cmd+]), Cmd+V. El portapapeles es el
     del propio Mac: nada sale de él.
5. Cierra lo que abriste si la persona quiere, sin guardar.

## Consultas — SQL Server

```sql
-- Columnas de una tabla
SELECT c.name, t.name AS tipo, c.max_length, c.precision, c.scale, c.is_nullable
FROM sys.columns c JOIN sys.types t ON t.user_type_id = c.user_type_id
WHERE c.object_id = OBJECT_ID('dbo.Tabla') ORDER BY c.column_id;

-- Índices (columnas clave e incluidas)
EXEC sp_helpindex 'dbo.Tabla';

-- Filas y tamaño
EXEC sp_spaceused 'dbo.Tabla';

-- Qué usa un procedimiento
SELECT DISTINCT referenced_schema_name, referenced_entity_name
FROM sys.dm_sql_referenced_entities('dbo.Procedimiento', 'OBJECT');

-- Huella exacta de un objeto (para leer-documento)
SELECT CONVERT(varchar(64), HASHBYTES('SHA2_256', OBJECT_DEFINITION(OBJECT_ID('dbo.Objeto'))), 2) AS huella;

-- Plan estimado en texto: NO ejecuta la sentencia
SET SHOWPLAN_TEXT ON;
GO
-- la sentencia o el EXEC a analizar
GO
SET SHOWPLAN_TEXT OFF;
```

`GO` como separador depende del cliente: si no lo acepta, ejecutar el
`SET SHOWPLAN_TEXT ON` solo, luego la sentencia, luego el `OFF`. Apúntalo en
`trabajo/entorno.md` cuando lo sepas.

## PostgreSQL / MySQL

- Columnas: `information_schema.columns` filtrando por tabla.
- Índices: `pg_indexes` (PostgreSQL) / `SHOW INDEX FROM tabla` (MySQL).
- Plan: `EXPLAIN …` sin `ANALYZE` (sin `ANALYZE` no ejecuta).
- Huella: `md5(pg_get_functiondef('esq.fn'::regproc))` /
  `SHA2(ROUTINE_DEFINITION, 256)` de `information_schema.ROUTINES`.
