# Kits

Un **kit** es una capa que aporta una funcionalidad a un proyecto al aplicarse:
un método de trabajo, unas skills, unas herramientas. Como una librería, pero de
contenido en vez de código.

Un proyecto es la **capa base** (obligatoria) más 0..N kits.

## Dos clases de kit

| | Qué hace | Ejemplo |
|---|---|---|
| **De proyecto** | Propaga archivos a cada proyecto que lo use | Un método de trabajo con sus skills y sus plantillas |
| **De máquina** | Instala algo una vez y no toca ningún proyecto | Un toolkit que pone comandos en `~/.local/bin` |

Los de máquina traen su propio instalador. El hub te dice que existe y te imprime
el comando — **nunca lo ejecuta por su cuenta**: es un script de un repositorio
ajeno corriendo en tu máquina.

`bash scripts/kit.sh verificar <id>` te dice de cuál se trata.

## Usarlos

```bash
bash scripts/kit.sh listar              # qué hay en el catálogo, y qué tienes
bash scripts/kit.sh instalar <id>       # lo trae a tu máquina
bash scripts/kit.sh estado [proyecto]   # qué está al día y qué ha cambiado
bash scripts/kit.sh arbol               # quién provee qué, y qué falta
bash scripts/kit.sh ruta <id>           # dónde está instalado
```

Para aplicarlo a un proyecto, abre Claude Code ahí y di **«aplica el kit X»**
(skill `aplicar-kit`). El hub calcula qué haría falta y te lo enseña **antes** de
escribir nada.

## Dónde se instalan

`~/.local/share/hub/kits/<id>/<version>/`, con la versión en la ruta. **Todas las
versiones conviven**, así que un proyecto puede quedarse en la 1.2 mientras otro
pasa a la 2.0.

Instalar una versión es clonar el repo del kit en su tag. Un tag publicado no se
mueve: si hay que corregir algo, se publica el siguiente.

## Tu propio catálogo

El repo trae un `kits.yml` con los kits públicos. Los tuyos van en
`~/.local/share/hub/kits.yml`, con el mismo formato; los dos se fusionan y gana
el tuyo.

```yaml
kits:
  - id: mi-kit
    nombre: Mi kit
    version: "1.0"
    origen: https://github.com/yo/mi-kit.git    # o una ruta local
```

## Los tres modos

Cada archivo de un kit llega al proyecto de una de estas tres formas, y se
comprueba de forma distinta:

| Modo | Qué pasa en tu proyecto | Cómo se comprueba |
|---|---|---|
| `apuntador` | **No tienes el archivo.** Tu `CLAUDE.md` referencia el del kit | Por contenido |
| `materializado` | Se copia de verdad, con cabecera «del kit X vN — no editar aquí». Es lo que se usa para skills y agentes, que Claude Code busca en rutas fijas | Por contenido |
| `copia` | Se copia **para que la personalices**. Divergir es lo correcto | Por procedencia: se avisa si el kit sube de versión, y ya |

## Qué te dice `estado`

| | |
|---|---|
| `al día` | Nada que hacer |
| `N archivos por revisar` | Falta alguno, o alguno difiere del kit |
| `sobra de una versión anterior` | Un archivo que puso una versión vieja. **El hub no lo borra**: te lo dice |
| `⚠️ necesita X` | El kit usa un binario que no tienes en el PATH |

Si un archivo **difiere**, la pregunta no es «¿lo propago?» sino **«¿por qué
difiere?»**. Puede ser un cambio tuyo deliberado — y entonces se declara, no se
pisa.

## Excepciones: lo que no heredas, y por qué

Un proyecto puede no querer un archivo del kit, o quererlo distinto. Eso se
declara en su `.claude/hub/kits.yml`, **con el motivo escrito**:

```yaml
kits:
  - id: orquestacion
    version: "1.0"
    excepciones:
      tools/mutar.sh: >
        Sólo sabe de GDScript. En un proyecto sin stack decidido, copiarlo
        documenta un instrumento que no existe.
```

Lo declarado **no cuenta como deriva** y el hub no te pedirá tocarlo. El motivo
viaja hasta el plan de aplicación, para que quien lo lea sepa por qué no debe.

> **Una divergencia sin declarar es un defecto. Una divergencia declarada es una
> decisión.**

## El kit que estás escribiendo

Si un kit está declarado en tu registro con `tipo: kit`, el hub lo resuelve desde
su carpeta sin que tengas que publicar nada. Editas y mides en el mismo minuto.

En las salidas aparece como **«en desarrollo, desde el registro»**, para que no
lo confundas con una versión publicada.

## Capacidades

Un kit declara qué **capacidades** ofrece y cuáles necesita, con nombres del tipo
`notificar#enviar-mensaje`. La dependencia es de la capacidad, no del kit: si
mañana la provee otro, quien la consume no se entera.

Lo que nadie provee se dice en voz alta, en el inventario y en `kit.sh arbol`:

- **opcional sin proveedor** → esa parte del kit no existe hoy
- **obligatoria sin proveedor** → el kit no puede funcionar

## Hacer uno

Desde la interfaz: **`/inventario` → Kits → «Kit nuevo»**. Pide el nombre, el
identificador y en qué carpeta va, y con eso el hub crea el repo desde la
plantilla —con el `id` y el `nombre` ya puestos dentro—, lo da de alta y abre una
ventana con un agente que te pregunta las cuatro cosas que definen el kit y lo
diseña contigo.

También vale abrir Claude Code en el hub y decir **«quiero un kit para X»**
(skill `nuevo-kit`): es el mismo procedimiento, porque el botón invoca esa misma
skill en vez de llevar su propia copia.

🔴 **La carpeta tiene que estar vacía, y no es capricho.** Un kit nace desde la
plantilla; extraerlo de un proyecto que ya lo tenía produce una copia de ese
proyecto, con sus rutas y su stack dentro, y el segundo que lo use tendrá que
reescribirlo entero. Y **no va dentro de la carpeta de kits instalados**: ahí la
versión forma parte de la ruta, y `kit.sh instalar` vería la carpeta, se
cortocircuitaría y respondería `✓ instalado` sin haber clonado nada.

Las dos reglas que aprenderás igual, pero mejor antes:

> **Una plantilla que nombra el proyecto que la originó no es una plantilla, es
> una copia.** Si dentro hay una ruta concreta o un stack concreto, el siguiente
> que la use tendrá que reescribirla entera.

> **Un kit no está terminado hasta verlo acertar y verlo fallar.** Aplícalo,
> rompe un archivo a propósito, comprueba que la deriva lo marca, restaura y
> comprueba que vuelve.

## Fuera del hub

El contenido de un kit **funciona sin el hub**: sus documentos se leen y sus
scripts corren a mano. Lo que el hub aporta es aplicarlo, resolverlo por `id`,
medirlo y mantenerlo.
