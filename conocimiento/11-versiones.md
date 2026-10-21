# Versiones y actualizar

## Qué versión tengo

En [`/guia`](/guia#version), sección **Versión**. Ahí salen tres cosas:

- **la tuya**: la del código de tu carpeta del hub;
- **si la actualización está terminada**: `actualizar.sh` la apunta al acabar;
- **la última publicada**: el hub la mira una vez al día.

## Cómo me entero de que hay una nueva

Arriba, en todas las pantallas, sale «Hay una versión nueva del hub» con un
enlace a sus novedades. El hub lo sabe porque una vez al día pregunta al repo
publicado qué etiquetas tiene (`git ls-remote`, no baja nada). Es la única
consulta a internet que hace por su cuenta; si no la quieres, arranca el hub
con `HUB_BUSCAR_VERSIONES=0`.

🔴 **El hub nunca se actualiza solo.** Avisar es información; actualizar lo
decides tú.

## Cómo actualizo

En la carpeta del hub:

```bash
bash scripts/actualizar.sh
```

Hace todo lo que una versión necesita:

- baja el código, y sólo si avanza en línea recta;
- aplica los pasos propios de esa versión;
- regenera los servicios con tu puerto y tus datos;
- reinicia lo que estaba en marcha;
- pone al día el asistente;
- comprueba que el hub contesta;
- al final te enseña qué cambió.

Tus datos (`~/.local/share/hub/`) no se tocan.

Si algo falla, para ahí y lo dice, y la versión no se da por instalada.
Arregla lo que diga y vuelve a correrlo: retoma desde el principio sin
problema. Si ya bajaste el código a mano, usa `--sin-bajar`.

## «Falta terminar de actualizar»

Ese aviso rojo arriba significa que el código de tu carpeta es más nuevo que lo
que se instaló del todo. Normalmente es porque hiciste `git pull` y reiniciaste,
sin `actualizar.sh`. El hub funciona, pero le faltan pasos: los servicios o el
asistente pueden ser los de la versión anterior. Se arregla con
`bash scripts/actualizar.sh --sin-bajar`.

**Si instalaste el hub antes de la 0.2.0**, es lo que verás la primera vez: esa
versión es la primera con número, y antes no existía `actualizar.sh`.

## Qué cambió en cada versión

En [`CHANGELOG.md`](../CHANGELOG.md), en la carpeta del hub. Cada versión dice qué
tienes que hacer tú, qué hay nuevo y qué cambia en lo que ya usabas. Lo que
cambia de comportamiento va ahí siempre: si algo empezó a funcionar distinto
después de actualizar, ahí está el porqué.

## Si después de actualizar algo va mal

- **Una pantalla rara:** recarga con **Ctrl+Shift+R**. Parte de la interfaz son
  archivos que el navegador guarda.
- **El chat del asistente sigue con las instrucciones de antes:** pulsa
  «Limpiar» en su rueda. Lo anterior de sus archivos queda al lado, con
  `.antes-<fecha>`.
- **Un servicio que tú habías retocado a mano:** el de antes queda al lado, con
  `.antes`, en `~/.config/systemd/user/`.
- **La base:** hay una copia por día en `~/.local/share/hub/respaldos/`. Cómo
  restaurarla está en [`06-problemas.md`](06-problemas.md).
