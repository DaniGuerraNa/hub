---
name: calibrar-teclado
description: Mide en el propio Mac, en un texto plano, la fuente de entrada que el puente no tiene (la latinoamericana, por ejemplo) y la verifica con una consulta de huellas en el programa donde la persona escribe sus consultas, antes de usarla. Úsala cuando lo tecleado salga cambiado (`<` como `|`, `{` como `^`, `#` como otro) aunque Ajustes → Teclado diga la del Mac, o cuando el Mac use una fuente que no está en esa lista.
---

# Calibrar el teclado del Mac

**En dos partes, y ninguna pide un programa concreto (C-0482):**

- **Parte 1, medir:** en un **texto plano** nuevo y vacío (TextEdit). Ahí se
  pulsa cada tecla y se lee lo que sale. Da un borrador **sin verificar**.
- **Parte 2, comprobar para consultas:** en el programa donde la persona
  **escribe sus consultas**, el que sea (no des por hecho DBeaver: pregúntaselo).
  Se teclea con el borrador una consulta que calcula huellas; la **ejecuta la
  persona**, tú nunca. Comprueba la distribución y, de paso, que ese programa
  no cambia lo tecleado.

**Acceso:** necesitas el control para teclear el sondeo y la consulta de prueba
(`sondear_teclado`, `probar_teclado`). La medida la **activa la persona** en
Ajustes («Usar»), no tú.

Herramientas, en una sola búsqueda:
`select:mcp__puente-kvm__estado,mcp__puente-kvm__ver_pantalla,mcp__puente-kvm__atajo,mcp__puente-kvm__sondear_teclado,mcp__puente-kvm__leer_documento,mcp__puente-kvm__ver_pagina,mcp__puente-kvm__transcribir_pagina,mcp__puente-kvm__estado_lectura,mcp__puente-kvm__resolver_linea,mcp__puente-kvm__medir_teclado,mcp__puente-kvm__probar_teclado,mcp__puente-kvm__recorrer_pantalla,mcp__puente-kvm__comprobar_teclado`.

Por qué así: el puente teclea códigos de tecla y el Mac los convierte con su
fuente de entrada. De la latinoamericana de Apple no hay copia fiable, y
escribirla de memoria es adivinar justo `< > { } [ ] # | \ ~ @`. Aquí no se
adivina: se pulsa cada tecla, se lee lo que sale y **sólo vale lo que confirma
una huella de la base** (regla 5). No se toca la configuración del Mac.

**Por qué no basta con el texto plano**, por si la persona lo pregunta: el
puente no abre archivos del Mac, sólo ve su pantalla. Y a la vista se
confunden `´` `'` `’`, `^` `ˆ`, `~` `˜`: justo la comilla que rompe un SQL. La
huella la calcula el propio Mac con lo que de verdad llegó, y sale en
hexadecimal, que no se confunde al leerlo.

**«Latinoamericano ISO», ANSI o ISO**, por si la persona lo pregunta: son dos
cosas. «Latinoamericano» es la fuente de entrada del Mac (la que se mide aquí).
ISO es la forma de SU teclado físico (con `< >` junto a Mayús), y no cuenta:
para el Mac, el JetKVM es otro teclado USB, y macOS guarda el tipo (ANSI, ISO)
de cada teclado por separado. Si al conectarlo el Mac pregunta qué teclado es,
vale cualquier respuesta: según cuál, dos teclas cambian de sitio (la de junto
al 1 y la de junto a Mayús), y la medida pulsa las dos y apunta lo que salga.
La condición es **no cambiar después el tipo del teclado del JetKVM**; si se
cambia, se vuelve a medir. (Lo de «elige ANSI» de la documentación vale sólo para las distribuciones de
serie, «U.S.» y «Español - ISO», que no se miden.)

Antes de empezar, dile a la persona qué vas a hacer y qué necesitarás de ella:
el control, abrir un TextEdit vacío, después una pestaña vacía donde escribe
sus consultas, ejecutar una consulta de sólo lectura cuando se lo pidas, y
pulsar «Usar» al final. Pregúntale ya **en qué programa escribe sus consultas
y con qué base** (SQL Server o PostgreSQL; con otra, la parte 2 todavía no se
puede hacer: díselo).

# Parte 1 — medir, en un texto plano

## 1. El texto plano

Pídele que abra **TextEdit** con un documento nuevo y lo deje así:

- **Formato → Convertir en texto normal** (⇧⌘T), si no lo es ya: letra
  monoespaciada, que deja contar los espacios.
- **Edición → Sustituciones**: apagadas **Comillas inteligentes**, **Guiones
  inteligentes** y **Sustitución de texto**; y en **Edición → Ortografía y
  gramática**, apagada **Corregir ortografía automáticamente**. Y en
  **Ajustes del Sistema → Teclado → Fuentes de entrada → Editar**, apagado
  **Poner mayúsculas automáticamente** (si no, tras `x. x` o `x? x` la `x`
  siguiente sale `X`). Los nombres pueden variar un poco con la versión de
  macOS.
- La ventana grande, sin nada encima, y el **Bloq Mayús quitado**.

Otro editor de texto plano vale si cumple lo mismo; Notas no (no es texto
plano). Que te dé el control. `ver_pantalla()`: el foco tiene que estar en ese
documento, vacío. Si no, no sigas. Apunta la **zona del texto** en píxeles
reales (x, y, ancho, alto): sólo el área donde se escribe, sin la barra de
menús ni el título de la ventana.

## 2. Sondear

`sondear_teclado()`. Teclea una línea por cada tecla que escribe y cada capa
(sin nada, Mayús, Opción, Mayús+Opción), en este orden, **cada una con su
número delante** (`001` … `192`). Detrás del número, `x`, la tecla, un espacio
y `x`:

- `007 xg x`, `012 x< x`: una tecla **normal** (su carácter y el espacio);
- `040 x´x`: una tecla **muerta** (se come el espacio y deja su acento);
- `125 x x`: una tecla que **no escribe** nada (o reservada).

Al acabar, `ver_pantalla()`: si se abrió algo (un diálogo, un panel, un menú)
o el documento no tiene sólo las líneas del sondeo, díselo a la persona antes
de seguir, y que lo cierre ella.

## 3. Leer

`leer_documento("sondeo del teclado", x, y, ancho, alto)` **con la zona del
texto** (sin ella leería la región del editor de Ajustes, que es la de otro
programa), y transcríbela entera como dice `leer-documento` (`ver_pagina` y
`transcribir_pagina`). Aquí no hay columna gris: **el número de cada renglón es
el que lleva escrito delante**, y el contenido es la línea entera, número
incluido: `7|007 xg x`. Cuidado con los que a la vista se confunden: `^`/`ˆ`,
`~`/`˜`, `´`/`'`/`’`, `º`/`°` y los guiones; transcribe el que veas, la huella
lo resuelve. Y con los espacios: `x´x` (muerta) no es `x´ x` (normal).
`estado_lectura` tiene que decir que está completa, sin huecos ni conflictos
(`resolver_linea` si los hay). Si sólo salió una página, Av Pág no avanza en
ese programa: díselo a la persona.

## 4. Medir

`medir_teclado(lectura, nombre)` con el nombre que le dé la persona
(«Latinoamericano»). Rechaza, y dice por qué:

- un sondeo con líneas de menos o un número fuera de su sitio (una línea
  saltada o repetida al transcribir): corrígela con `resolver_linea`;
- uno hecho con el Bloq Mayús puesto, o con las comillas inteligentes
  encendidas: que la persona lo arregle, **cierre ese documento sin guardar y
  abra uno nuevo** (no lo borres tú: el foco puede estar en otra ventana; pídeselo
  y termina tu turno, que es cuando el Mac vuelve a ella), y vuelve al paso 1;
- uno en el que la fila de números no da cifras (la francesa del Mac): ese
  teclado no se puede medir así; díselo.

El borrador queda **sin verificar**: todavía no se puede usar. El TextEdit ya
no hace falta: que lo cierre **sin guardar**.

# Parte 2 — comprobar, en el programa de sus consultas

## 5. Probar

Pídele una **pestaña nueva y vacía** en el programa donde escribe sus
consultas, conectada a su base, con el **autocompletado** y el **cierre
automático de paréntesis y comillas apagados** si ese programa los tiene.
Revisa también **Ajustes → «Teclas que el puente nunca pulsa al teclear»**: de
fábrica lleva `alt+x` (en DBeaver, Opción+X ejecuta el script). Si escribe en
**VS Code**, propónle añadir `alt+z, shift+alt+a, shift+alt+f, shift+alt+i`
(ajuste de línea, comentario, formato y varios cursores en VS Code para Mac);
de otro programa no inventes: pregúntale si conoce atajos con Opción. Ojo: si
una reservada es la única tecla que da un carácter del ASCII, la medida no
podrá quedar verificada; díselo si pasa.

Con la pestaña vacía y el control, `probar_teclado(medida)` (con
`motor="PostgreSQL"` si la base es PostgreSQL). Teclea con el borrador una
consulta `SELECT … FROM (VALUES …)` que no lee ninguna tabla ni cambia nada:
calcula, por cada fila de 8–10 caracteres, su largo y su huella.

Si su editor cierra solo paréntesis y comillas y no se puede apagar, la
consulta se puede teclear en un texto plano y que la persona la copie y la
pegue en su programa. Eso comprueba el teclado, **pero no el programa**: dile
que en él el puente seguirá tecleando mal los paréntesis y las comillas.

## 6. La persona la ejecuta

Al acabar de teclearla, dile a la persona que la ejecute ella, como ejecuta
siempre en su programa, y **termina tu turno**: es entonces cuando el control
vuelve a ella (lo conservas mientras sigas trabajando). **No la ejecutes tú.** Si el cliente pide valores para parámetros o da un
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

(La de la parte 2, en el programa de sus consultas.)

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

Pídele que cierre la pestaña de la consulta **sin guardar** (y el TextEdit, si sigue abierto). Termina con un resumen: qué se
midió, cuántos caracteres quedaron verificados, qué no, y que con la medida en
uso la línea de prueba de `primera-conexion` (paso 4) debe salir idéntica.
