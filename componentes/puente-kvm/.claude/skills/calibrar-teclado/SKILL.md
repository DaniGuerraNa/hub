---
name: calibrar-teclado
description: Mide en el propio Mac la fuente de entrada que el puente no tiene (la latinoamericana, por ejemplo) y la verifica con huellas de la base antes de usarla. Úsala cuando lo tecleado salga cambiado (`<` como `|`, `{` como `^`, `#` como otro) aunque Ajustes → Teclado diga la del Mac, o cuando el Mac use una fuente que no está en esa lista.
---

# Calibrar el teclado del Mac

**Acceso:** necesitas el control para teclear el sondeo y la consulta de prueba
(`sondear_teclado`, `probar_teclado`), siempre en una **pestaña de script nueva y
vacía**. La consulta la **ejecuta la persona**: tú nunca. Y la medida la **activa
la persona** en Ajustes («Usar»), no tú.

Herramientas, en una sola búsqueda:
`select:mcp__puente-kvm__estado,mcp__puente-kvm__ver_pantalla,mcp__puente-kvm__atajo,mcp__puente-kvm__sondear_teclado,mcp__puente-kvm__leer_documento,mcp__puente-kvm__ver_pagina,mcp__puente-kvm__transcribir_pagina,mcp__puente-kvm__estado_lectura,mcp__puente-kvm__resolver_linea,mcp__puente-kvm__medir_teclado,mcp__puente-kvm__probar_teclado,mcp__puente-kvm__recorrer_pantalla,mcp__puente-kvm__comprobar_teclado`.

Por qué así: el puente teclea códigos de tecla y el Mac los convierte con su
fuente de entrada. De la latinoamericana de Apple no hay copia fiable, y
escribirla de memoria es adivinar justo `< > { } [ ] # | \ ~ @`. Aquí no se
adivina: se pulsa cada tecla, se lee lo que sale y **sólo vale lo que confirma
una huella de la base** (regla 5). No se toca la configuración del Mac.

Antes de empezar, dile a la persona qué vas a hacer y qué necesitarás de ella:
el control, abrir una pestaña de script, ejecutar una consulta de sólo lectura
cuando se lo pidas, y pulsar «Usar» al final.

## 1. La pestaña

Pídele que abra una **pestaña de script nueva y vacía** (en DBeaver, ⌘] o
«Editor SQL → Nuevo script»), conectada a una base cualquiera, con el
autocompletado, el cierre de paréntesis y comillas, la sangría automática y
«convertir mayúsculas de palabras clave» **apagados** (`primera-conexion`, paso
3), y el **Bloq Mayús quitado**. Que te dé el control. `ver_pantalla()`: el foco
tiene que estar en esa pestaña, vacía. Si no, no sigas.

## 2. Sondear

`sondear_teclado()`. Teclea una línea por cada tecla que escribe y cada capa
(sin nada, Mayús, Opción, Mayús+Opción), en este orden, sin números. Cada línea
es `x`, la tecla, un espacio y `x`:

- `xa x`, `x< x`: una tecla **normal** (su carácter y el espacio);
- `x´x`: una tecla **muerta** (se come el espacio y deja su acento);
- `x x`: una tecla que **no escribe** nada (o reservada, como Opción+X).

Opción+X no se pulsa, pero **Mayús+Opción+X sí**, y no se ha comprobado qué
hace en DBeaver. Al acabar, `ver_pantalla()`: si se abrió algo (un diálogo, un
panel, un menú) o el editor no tiene sólo las líneas del sondeo, díselo a la
persona antes de seguir, y que lo cierre ella.

## 3. Leer

`leer_documento("sondeo del teclado")` y transcríbela entera como dice
`leer-documento` (`ver_pagina` y `transcribir_pagina`, «número|contenido»).
Cuidado con los que a la vista se confunden: `^`/`ˆ`, `~`/`˜`, `´`/`'`/`’`,
`º`/`°` y los guiones; transcribe el que veas, la huella lo resuelve. Y con los
espacios: `x´x` (muerta) no es `x´ x` (normal). `estado_lectura` tiene que
decir que está completa, sin huecos ni conflictos (`resolver_linea` si los hay).

## 4. Medir

`medir_teclado(lectura, nombre)` con el nombre que le dé la persona
(«Latinoamericano»). Rechaza un sondeo con líneas de menos o hecho con el Bloq
Mayús puesto: entonces borra la pestaña y vuelve al paso 2 (ver «Borrar la
pestaña», abajo). Si se queja de una línea concreta, mírala en su página y corrígela con
`resolver_linea`. El borrador queda **sin verificar**: todavía no se puede usar.

## 5. Probar

Con la pestaña otra vez vacía (ver «Borrar la pestaña») y el control, `probar_teclado(medida)` (con
`motor="PostgreSQL"` si la base es PostgreSQL). Teclea con el borrador una
consulta `SELECT … FROM (VALUES …)` que no lee ninguna tabla ni cambia nada:
calcula, por cada fila de 8–10 caracteres, su largo y su huella.

## 6. La persona la ejecuta

Al acabar de teclearla, el control vuelve solo a la persona: dile que la
ejecute ella (⌘Intro o «Ejecutar sentencia»). **No la ejecutes tú.** Si el cliente pide valores para parámetros o da un
error de sintaxis, que cancele: mira la consulta en pantalla (`ver_pantalla`),
busca el carácter que salió distinto, corrige su línea del sondeo con
`resolver_linea` y vuelve a medir.

## 7. Comprobar

Lee la rejilla de resultados (`ver_pantalla` de su zona, o `recorrer_pantalla`
si no cabe) y pásala a `comprobar_teclado(medida, huellas)`, una fila por
línea: `1001 9 3F2A0C…` (número, largo y huella). Dice qué filas coinciden y
qué corrigió. Si falta algo del ASCII, borra la consulta (ver «Borrar la pestaña») y vuelve al paso 5: la
ronda siguiente sólo lleva lo que falta, y lo que falló va solo en su fila.
Dos o tres rondas bastan; si un carácter sigue sin teclas, mira su línea del
sondeo.

Si dice «¿Bloq Mayús?», no apuntó nada de esa ronda: que la persona lo quite,
borra la consulta y vuelve al paso 5.

### Borrar la pestaña

Antes de borrar, `ver_pantalla()`: el foco tiene que estar en el **editor**, no
en la rejilla de resultados ni en otra ventana (tras ejecutar, suele quedarse en
la rejilla). Si no, un clic en el editor o pídeselo a la persona. Sólo entonces
`atajo("cmd+a")` y `atajo("backspace")`, y `ver_pantalla()` para ver que quedó
vacía.

## 8. Usarla

Cuando `comprobar_teclado` diga **verificada**, dile a la persona que vaya a
**Ajustes → Teclado** y pulse **«Usar»** en «Medida: <nombre> (fecha)». No la
actives tú: es su decisión. Desde entonces, el puente sólo teclea lo
verificado con esa medida; un carácter sin verificar no se teclea.

## 9. Cerrar

Pídele que cierre la pestaña **sin guardar**. Termina con un resumen: qué se
midió, cuántos caracteres quedaron verificados, qué no, y que con la medida en
uso la línea de prueba de `primera-conexion` (paso 4) debe salir idéntica.
