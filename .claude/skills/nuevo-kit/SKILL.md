---
name: nuevo-kit
description: Crea un kit nuevo desde cero, en el hub. Úsala cuando pidan «crea un kit», «quiero un kit para X» o «haz un kit de Y».
---

# Crear un kit

**Los kits nacen aquí, en el hub**, no se extraen de un proyecto que ya los
tenía. Esa diferencia importa: la extracción produce «plantillas» que en realidad
son copias del proyecto de origen, con sus rutas y su stack dentro, y el segundo
consumidor tiene que reescribirlas enteras.

**Cuándo hace falta un kit lo decide el usuario.** Tu trabajo no es filtrar, es
preguntar en voz alta lo que ayuda a decidir en ese momento.

## 1. Pregunta cuatro cosas

1. **¿Qué capacidad aporta?** En una frase que empiece por un verbo. Si hace
   falta la palabra «y» para describirla, probablemente son dos kits.
2. **¿Quién más lo va a usar?** Si sólo un proyecto, quizá sea de ese proyecto.
   No bloquees por esto: dilo y sigue.
3. **¿Su contenido va a cambiar con el tiempo?** Si no cambia nunca y lo llevan
   todos, puede ser de la capa base.
4. **¿Necesita algo de otro kit?** Eso se declara como capacidad consumida, no
   como dependencia de un nombre propio.

## 2. Crea el repo — FUERA del repositorio de kits

```bash
HUB=$(pwd)                          # el repo del hub, para volver
ID=<id-en-minusculas>               # minúsculas, números y guiones
DESTINO=~/projects/$ID              # su repo propio, donde tú trabajas
mkdir -p "$DESTINO"
cp -r "$HUB"/semillas/kit/. "$DESTINO/"
git -C "$DESTINO" init -b main
```

🔴 **El kit NO se escribe dentro de `~/.local/share/hub/kits/<id>/<versión>/`.**
Esa carpeta es el repositorio local de instalación, con la versión **en la
ruta** — el equivalente de `~/.m2`. Escribir ahí tiene tres consecuencias, y las
tres son malas:

- `kit.sh instalar` ve la carpeta, se cortocircuita y responde `✓ instalado` sin
  haber clonado ni resuelto ningún tag. Te da un éxito que no ocurrió.
- La versión de la carpeta y la del `kit.yml` se separan en cuanto subes una:
  quedas con `.../0.1/` conteniendo un manifiesto que dice `0.2`, y
  `resolver('0.2')` devuelve `None`.
- Y sobre todo: **cambias el contenido que hay detrás de una versión ya
  publicada.** Es exactamente lo que este diseño prohíbe —«si un tag se
  reescribiera, todo lo que midió deriva contra él pasaría a mentir sin
  avisar»—, y lo estarías haciendo siguiendo el procedimiento.

Trabajas en tu repo, publicas un tag, y **entonces** el hub lo instala.

Fíjate en que los comandos siguientes se ejecutan **desde el repo del hub**
(`cd "$HUB"`), no desde el del kit: `scripts/kit.sh` es una ruta relativa a él.

Pon lo tuyo donde la semilla trae ejemplos:

- **`id` y `nombre`** vienen con valores de ejemplo (`mi-kit`, `Mi kit`) y no con
  marcadores, para que la plantilla **verifique en verde recién copiada** y se
  pueda probar antes de entenderla. El `id` acaba siendo el nombre de su
  carpeta: minúsculas, números y guiones.
- **Los marcadores que sí quedan** —`@DESCRIPCION@`, `@FECHA@`,
  `@NOTAS_DE_MANTENIMIENTO@`— están en campos de texto libre. Sustitúyelos.

**Deja `expone`, `consume` y `aplica` vacíos** hasta que haya contenido real: un
manifiesto que promete archivos que no existen es peor que uno corto.

Comprueba que sigue parseando antes de seguir — desde el repo del hub:

```bash
bash scripts/kit.sh verificar "$DESTINO"
```

## 3. Escribe el contenido

Y mientras lo escribes, vigila lo único que de verdad estropea un kit:

> **Una plantilla que nombra el proyecto que la originó no es una plantilla, es
> una copia.**

Si aparece una ruta concreta, un stack, o «como hicimos en X», sácalo a
`parametros:` o quítalo. Ya pasó: un agente `revisor` que citaba el concepto y el
reparto de proveedores de un proyecto específico no le sirvió al siguiente.

Elige el modo de cada archivo por lo que es, no por costumbre:

- **apuntador** — se lee y nadie lo edita. El consumidor no tiene el archivo.
- **materializado** — Claude Code lo busca en una ruta fija (skills, agentes).
- **copia** — es semilla y se personaliza.

## 4. Valida el manifiesto

```bash
bash scripts/kit.sh verificar "$DESTINO"
```

Te dirá si el contrato está bien formado y si declara archivos que no existen.

## 5. 🔴 Consíguele el primer consumidor, y mídelo

**Un kit sin un consumidor medido no está terminado.** Aplícalo a un proyecto
real con la skill `aplicar-kit`, y haz el control negativo:

```bash
bash scripts/kit.sh estado <proyecto>     # al día
# cambia una línea de un archivo propagado
bash scripts/kit.sh estado <proyecto>     # tiene que decir «difiere»
# restaura
bash scripts/kit.sh estado <proyecto>     # y volver a decir «al día»
```

Escribe el resultado **literal** en el `README` del kit, no un resumen. Un verde
que nadie ha visto en rojo no es evidencia.

Si el kit consume algo **opcional**, demuéstralo también funcionando **sin** el
proveedor. Mientras eso no se haya visto, «opcional» es una afirmación.

Y si lo va a instalar alguien que no eres tú, **la sala limpia** antes de
publicar: `bash scripts/sala-limpia/sala.sh kit <ruta>` instala el kit con un
Claude sin contexto en un contenedor vacío y enseña cuántas preguntas hace y
qué deja. El procedimiento está en `producto/conocimiento/08-sala-limpia.md`.

## 6. Publica y da de alta

```bash
git -C "$DESTINO" add -A
git -C "$DESTINO" commit -m "Kit $ID 0.1"
git -C "$DESTINO" tag v0.1
```

Un tag publicado **no se mueve**: si hay que corregir, se publica `0.2`.

Después, decláralo en el catálogo del usuario —`$HUB_HOME/kits.yml`, que por
defecto es `~/.local/share/hub/kits.yml`— con esta forma:

```yaml
kits:
  - id: mi-kit
    nombre: Mi kit
    version: "0.1"                       # entre comillas: sin ellas, 1.10 → 1.1
    origen: /home/tu-usuario/projects/mi-kit   # o la URL, cuando lo publiques
    descripcion: Para qué sirve, en una línea.
```

Y **da de alta el kit como proyecto** en tu `projects.yml`, con `tipo: kit`:

```yaml
  - id: mi-kit
    nombre: Mi kit
    dominio: personal
    tipo: kit
    asiento: /home/tu-usuario/projects/mi-kit
    status: activo
```

Sin esto el kit es invisible para todo el lado web —no sale en el inventario, no
tiene deriva, no genera prompt de mantenimiento— y, sobre todo, no funciona
`resolver_en_desarrollo`, que es lo que te deja **editarlo y medir el efecto en
el mismo minuto** sin publicar un tag por cada cambio.

Ahora sí, desde el repo del hub:

```bash
cd "$HUB"
bash scripts/kit.sh listar        # tiene que salir
bash scripts/kit.sh instalar $ID 0.1
```

## Qué NO hacer

- **No publiques un kit sin consumidor medido.** Es lo que convierte esto en un
  método y no en una carpeta de buenas intenciones.
- **No le pongas un agente mantenedor propio.** El procedimiento vive una vez, en
  el hub; las particularidades van en `mantenimiento:` del manifiesto.
- **No metas secretos.** Punteros a dónde vive la credencial, nunca la credencial.
