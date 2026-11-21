---
name: primera-conexion
description: Pone a punto el puente con un Mac y un cliente de BD nuevos — mide conexión, región del editor, líneas legibles, Av Pág, Ir a la línea, huella y velocidad de tecleo, y lo apunta en trabajo/entorno.md. Úsala la primera vez con el JetKVM real, al cambiar de cliente o de fuente, o cuando una lectura falle de forma rara.
---

# Primera conexión: medir antes de fiarse

**Acceso:** varias pruebas necesitan el control y teclean en una **pestaña de
script nueva y vacía**, nunca en un objeto real. Avisa de cada paso.

Herramientas, en una sola búsqueda:
`select:mcp__puente-kvm__estado,mcp__puente-kvm__ver_pantalla,mcp__puente-kvm__teclear,mcp__puente-kvm__atajo,mcp__puente-kvm__leer_documento,mcp__puente-kvm__ver_pagina,mcp__puente-kvm__transcribir_pagina,mcp__puente-kvm__comprobar_huella`.

Nada de esto se razona: se mide en la pantalla real y se apunta. Copia
`conocimiento/entorno.plantilla.md` a `trabajo/entorno.md` si no existe, y ve
rellenándolo.

1. **Conexión.** `estado()`: aparato `jetkvm`, conectado, resolución, firmware.
   Si no conecta, el motivo está en `dispositivo.motivo` (contraseña, otra
   sesión abierta en su web, sin HDMI).
2. **Pantalla.** `ver_pantalla()`: ¿se ve el Mac entero y nítido? Si es un
   portátil, ¿la pantalla está duplicada? Pide a la persona que marque la región
   del editor en Ajustes (con la columna de números, sin la barra de estado).
3. **Modo captura.** Con la persona: números de línea, Menlo 16–18, tema claro
   sin colores, sin plegado ni ajuste de línea, y **autocompletado, cierre de
   paréntesis y sangría automática apagados**. Fuente de entrada: la que dice Ajustes → Teclado («U.S.» o «Español - ISO»).
4. **Tecleo.** En una pestaña nueva: `teclear` una línea con todo lo difícil —
   ``ABC xyz 0O1lI {}[]()<> |\\~`^ ;:'" á é í ó ú ñ Ñ ü ¿? ¡! €``— y
   compárala en pantalla carácter a carácter. Si falta o sobra algo, sube
   `retardo_tecla_ms` en Ajustes y repite. Apunta el valor que funcionó.
5. **Atajos.** Teclea 60 líneas numeradas de prueba en esa pestaña y comprueba:
   Cmd+↑ / Cmd+↓, **Av Pág** (¿avanza una página exacta o deja líneas de
   solape?), **Ir a la línea** (¿qué atajo, y deja el cursor en la columna 1?),
   **fin de línea**. Corrige los atajos en Ajustes si no son los de DBeaver.
6. **Lectura.** `leer_documento` de esa pestaña de prueba y transcríbela: debe
   salir idéntica a lo tecleado. Apunta cuántas líneas caben por página.
7. **Huella.** En un objeto real pequeño: compara la huella de la base con la
   de su lectura (`comprobar_huella`). Si no coincide nunca, mira si el editor
   enseña una cabecera distinta de la que guarda la base (`CREATE` frente a
   `CREATE OR ALTER`) y apúntalo.
8. Cierra la pestaña de pruebas **sin guardar**.

Termina con un resumen de lo medido y lo que quedó pendiente.
