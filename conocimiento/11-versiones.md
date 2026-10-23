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

Tus datos (`~/.local/share/hub/`) no se borran ni se editan. Lo único que
cambia ahí es lo que la versión necesita: se apunta la versión instalada
(`version.json`), y la base recibe las tablas o columnas nuevas, sin perder
lo que tenía. Del asistente se refrescan sus archivos, y cada uno que cambia
queda al lado con `.antes-<fecha>`.

Si algo falla, para ahí y lo dice, y la versión no se da por instalada.
Arregla lo que diga y vuelve a correrlo: retoma desde el principio sin
problema. Si ya bajaste el código a mano, usa `--sin-bajar`.

## Dónde está «la carpeta del hub»

Es el clon desde el que corren los servicios, y no tiene por qué ser la
carpeta en la que estés. En Windows el hub vive **dentro de WSL**: el comando
se corre en la terminal de Ubuntu, no en PowerShell ni en una copia del repo
en el disco de Windows. Para saber cuál es:

```bash
systemctl --user show hub-web -p WorkingDirectory
```

Sin servicios, es la carpeta desde la que lanzas `bash scripts/arrancar.sh`.

## Tengo cambios míos en el clon

Si tocaste el código del hub —o se lo pediste a una sesión de Claude—,
`actualizar.sh` (y `git pull`) paran antes de pisarlo y lo dicen.

**Lo habitual es que sean arreglos de urgencia**: algo no funcionaba y se
parcheó ahí mismo. La versión nueva casi siempre los trae resueltos, así que
lo que conviene es mirar para qué eran, guardar una copia y descartarlos:

```bash
git diff                                 # para qué eran
git diff > ~/cambios-hub-$(date +%Y%m%d).patch   # la copia, por si acaso
git restore .                            # descarta sólo cambios del código del hub
bash scripts/actualizar.sh
```

`git restore .` sólo deshace cambios en archivos del repo del hub. Tus datos
(`~/.local/share/hub/`: el registro, la base, los respaldos) y tus proyectos
están fuera y no se tocan.

Si después de actualizar vuelve a fallar lo que parcheaste, **cuéntalo** con
esa copia: es la forma de que el arreglo llegue a la versión publicada.

Si en cambio son algo tuyo que quieres conservar, guárdalos en una rama:

```bash
git switch -c mis-cambios-$(date +%Y%m%d)
git commit -am "Mis cambios antes de actualizar"
git switch main
bash scripts/actualizar.sh
```

El hub queda **sin** ellos; siguen en esa rama. `git stash` también sirve,
pero reaplicarlo encima de la versión nueva suele dar conflictos, y un stash
olvidado no se ve en ningún sitio.

## «Falta terminar de actualizar»

Ese aviso rojo arriba significa que el código de tu carpeta es más nuevo que lo
que se instaló del todo. Normalmente es porque hiciste `git pull` y reiniciaste,
sin `actualizar.sh`. El hub funciona, pero le faltan pasos: los servicios o el
asistente pueden ser los de la versión anterior. Se arregla con
`bash scripts/actualizar.sh --sin-bajar`.

**Si instalaste el hub antes de la 0.2.0**, es lo que verás la primera vez: esa
versión es la primera con número, y antes no existía `actualizar.sh`. Esa vez,
en la carpeta del hub:

```bash
git status --short --untracked-files=no     # si sale algo, mira «Tengo cambios míos en el clon»
git pull --ff-only && bash scripts/actualizar.sh --sin-bajar
```

Da igual a qué versión llegues: el comando es el mismo, y al final te enseña
lo que cambió en todas las que cruzaste.

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
