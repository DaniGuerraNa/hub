---
name: leer-documento
description: Trae un documento largo (un procedimiento, una función, una vista, un script) del editor del Mac a esta máquina, exacto y verificado con la huella de la base. Úsala cuando pidan «lee esta función», «tráete el SP», o cuando otra skill necesite el texto de algo que está en el Mac.
---

# Leer un documento del Mac

**Acceso:** necesitas el control del Mac sólo para capturar (`leer_documento`).
Transcribir, ensamblar y verificar no tocan el Mac.

Herramientas, en una sola búsqueda:
`select:mcp__puente-kvm__estado,mcp__puente-kvm__ver_pantalla,mcp__puente-kvm__leer_documento,mcp__puente-kvm__ver_pagina,mcp__puente-kvm__estado_lectura,mcp__puente-kvm__resolver_linea,mcp__puente-kvm__comprobar_huella`.

## 0. Antes

1. `estado()`. Si ya hay una lectura **verificada** de ese objeto y nadie lo ha
   cambiado desde entonces, úsala: no lo vuelvas a leer.
2. `ver_pantalla()` y confirma con la persona que lo que está al frente es el
   documento que quiere, en el editor (no en una rejilla de resultados).
3. Si no tienes el control, pídeselo: «Dame el control en el puente (botón azul)
   y no toques el Mac hasta que te avise». Espera a que lo dé.

## 1. Capturar

`leer_documento(nombre)` con el nombre del objeto (`usp_ConciliarMovimientos`).
Va al principio, baja con Av Pág y guarda cada página. Al terminar **sigues
con el control**: si la lectura salió mal (páginas a medio pintar, un diálogo
encima), repítela; si el encargo sigue con una escritura, también es tuyo.
Vuelve a la persona cuando terminas tu turno.
No hace falta dejar la vista arriba ni comprobar la pantalla antes: tras cada
tecla el puente espera a **ver** el cambio (el vídeo del aparato llega 1–2 s
tarde), no a la primera pantalla quieta. Si el resultado dice que la pantalla
tardó **cerca del tope**, díselo a la persona: que suba **Retraso del vídeo**
en Ajustes; y si la última página no llega al final del documento, vuelve a
leerlo después.

**Dónde se lee.** Sin zona, cada página es la región del editor de Ajustes.
Para cualquier otra ventana (el texto plano del sondeo del teclado, o el editor
que la persona tenga abierto en otro sitio), pásale su zona en píxeles reales
del Mac: `leer_documento(nombre, x, y, ancho, alto)`, sólo el texto, sin barras
ni otras ventanas. Elegirla no pide permiso: leer no es escribir. **Dile a la
persona qué zona usas** («leo la ventana de la derecha, x…, y…»); la página de
la lectura y el panel la enseñan, y la lectura la guarda (`zona`): un cambio
sobre ella se escribe en esa misma zona. Notas y el navegador no tienen números
de línea: ahí se puede leer (o recorrer la pantalla), pero no sirve para
proponer un cambio después.

## 2. Transcribir — en paralelo

Reparte las páginas entre subagentes, **8–10 páginas por agente**, todos a la
vez. A cada uno dale estas instrucciones. Con las de antes (ver y transcribir cada
página por separado) salieron 2.017 líneas exactas a la primera; éstas transcriben
una página y miran la siguiente en la misma respuesta. Medidas las dos el 22-nov
con Sonnet 5 sobre el mismo documento: ninguna dio la huella, y éstas no leen
peor:

> Transcribe con tu vista, sin ningún otro recurso, las páginas N–M de la
> lectura L. Carga las dos herramientas en una sola búsqueda:
> `select:mcp__puente-kvm__ver_pagina,mcp__puente-kvm__transcribir_pagina`.
> Empieza con `ver_pagina(L, N)`. Después, en cada respuesta, dos llamadas
> a la vez: `transcribir_pagina(L, n, texto)` de la página que acabas de ver
> y `ver_pagina(L, n+1)` de la siguiente (en la última, sólo transcribir).
> Formato: una línea por renglón del
> editor, `número|contenido`, incluidas las vacías (`57|`). El número es el de
> la columna gris. El contenido EXACTO: sangría contada por la rejilla
> monoespaciada, mayúsculas, comillas, acentos, espacios entre columnas
> alineadas. Cuidado con 0/O, 1/l/I, ;/:, y con contar los guiones de los
> comentarios por posición. La barrita al principio de una línea es el
> cursor; la flecha negra, el ratón: no son texto. No inventes: si algo
> sale cortado por el borde, dilo. Devuelve sólo las líneas de las que dudes.

## 3. Ensamblar y verificar

1. `estado_lectura(L)`: si hay **conflictos** (dos páginas leen distinto la
   misma línea), mira las dos capturas (`ver_pagina`) y `resolver_linea`. Si hay **huecos**,
   vuelve a transcribir esa página.
2. **La huella.** Pídesela a la persona (la consulta está en la página de la
   lectura, en el puente), o usa la skill `consultar-catalogo` para escribirla
   tú en una pestaña nueva y que ella la ejecute. `comprobar_huella(L, huella)`.
3. **Sin huella que coincida, la copia no es exacta.** Dilo así, con las líneas
   dudosas. No la des por buena porque «se ve bien».

## 4. Dejarla lista

Copia el archivo ensamblado (`estado_lectura` → `archivo`) a
`trabajo/<objeto>.sql`. Ése es el que se lee y se edita; el de la lectura no se
toca. Apunta en `trabajo/entorno.md` (sección «Leído») el objeto, la lectura,
las líneas y si quedó verificado.

Termina diciendo: cuántas líneas, si es exacta (y con qué variante de huella),
y dónde está la copia.
