---
title: Lienzos — contenido visual generado por Claude Code y trabajado en la web
estado: INVESTIGACIÓN
fecha: 2026-09-01
maquetas: maquetas/i-situaciones.html (las tres situaciones, la A funciona) ·
  maquetas/j-editor.html (editor arrastrable, funciona) · maquetas/k-panel.html (el panel) ·
  maquetas/h-lienzo-vivo.html (el motor) · maquetas/g-lienzos.html (las opciones)
---

> Si esto y `ARQUITECTURA.md` se contradicen, **manda `ARQUITECTURA.md`**. Aquí no
> hay ninguna decisión tomada: hay lo que se ha medido y una recomendación.

## Qué es esto en realidad

No es «poner diagramas en el hub». Con su contexto, el objetivo es otro y
conviene escribirlo porque decide todo lo demás:

> «cuando trabajo algunos temas que son muy extensos en cantidad de información
> la verdad es que a veces tiendo a saturarme o directamente perder la atención
> después de leer informes de 20, 30 puntos con explicación, justificación y que
> requieren mi decisión […] eso llevarlo todo en mi mente cansa, no es que no
> pueda pero consume atención y hace que me queme más rápido»

**El objetivo es preservar atención, no ilustrar.** Y de ahí sale el criterio
que ordena el resto: 🔴 **un lienzo que se añade al texto ha fracasado; sólo
sirve el que lo sustituye.** Si después de ver el diagrama hay que leer los 30
puntos igual, se ha añadido una cosa más que mirar a alguien que ya está
saturado — que es exactamente el daño que se quería evitar.

Hay además una pérdida concreta que se está intentando recuperar: en Claude web
esto existía, y se perdió al pasarse a Claude Code al 100 % —porque un
coordinador separado del equipo no funciona en un proyecto grande—. La capacidad
se dio por perdida. La interfaz web del hub es lo que la vuelve posible.

---

## 1. El bucle es el producto, no el dibujo

La frase que lo define:

> «él me hace la propuesta del flujo, los servicios con flechas y demás, **y yo
> lo modifico ahí mismo y él puede leer los cambios**»

Eso no es un visor. Es un **documento compartido con dos autores**, y cambia el
diseño entero:

```
Claude propone  →  lo ves en el hub  →  lo corriges tú  →  él relee
      ▲                                                        │
      └────────────────────────────────────────────────────────┘
```

Y tiene una consecuencia que decide el formato: **lo que se corrige tiene que
ser diffable.** Un SVG no lo es —Claude no sabe qué cambiaste comparando dos
dibujos—. Unos datos sí: cambiar `q1 -> l2` por `q1 -> l3` es una línea, y esa
línea se lee.

Por eso, de los tres tipos posibles, el que sostiene el bucle es **`vista`**:
Claude emite datos, el hub dibuja. Mermaid vale para mirar y no para el bucle;
un SVG, ni para una cosa ni para la otra.

---

## 2. Lo que se probó: el motor existe y funciona

**`maquetas/h-lienzo-vivo.html` no es una maqueta: funciona.** Se edita el panel
izquierdo y el diagrama se redibuja. Motor entero: ~150 líneas de JS, **cero
dependencias**. Layout por niveles topológicos — nadie coloca ninguna caja.

Los tres ejemplos son los suyos: la arquitectura AWS (API GW, 3 lambdas, 2 SQS,
2 bases), el orden de ejecución de SQL, y un árbol de decisión.

Y sirvió para lo que sirve construir en vez de razonar: **destapó dos defectos
que leyendo el código no se ven** (regla dura 20).

1. **La tabla de idempotencia salía a la izquierda del API Gateway.** Su única
   entrada era una flecha de lectura (`~>`), y ésas no cuentan para la
   profundidad —si contaran, una caché arrastraría a su lector al fondo y el
   flujo principal dejaría de leerse en línea recta—. Con nivel 0, se dibujaba
   antes que todo. Arreglado con una segunda pasada que la coloca **junto** a
   quien la consulta, no detrás.
2. **El orden de SQL —8 pasos en cadena— salía ilegible.** Ocho columnas
   escaladas para caber en 940 px dejan las etiquetas en nada. Se resolvió con
   orientación automática: una cadena larga y estrecha se dibuja **en vertical**,
   que además es como se lee una lista de pasos. Acierta sola en los tres casos,
   y es la orientación correcta para el panel estrecho de `/trabajo`.

*(Yo había concluido aquí que no hacía falta arrastrar cajas. **Descartado por
él el 2026-09-01**: sí quiere arrastrar y editar texto in-situ. Era una
preferencia mía, no un límite técnico, y la §2b la resuelve.)*

---

## 2b. El editor arrastrable — qué librería, y por qué el sandbox lo permite

Dos cosas que él planteó y que resultaron ser correctas:

**«¿el iframe no soporta JS?» — sí lo soporta.** Ya estaba demostrado en la
propia prueba de seguridad sin que yo lo señalara: la línea
`iframe-ws-construido` sólo pudo llegar al servidor porque el script del lienzo
**se ejecutó**. El sandbox no bloquea JavaScript: bloquea el acceso al DOM del
padre y al WebSocket. Ahí dentro cabe una librería entera.

**«no se trata de reinventar la rueda» — tampoco.** Medido hoy, descargando los
`dist` reales:

| Librería | Peso | Licencia | ¿Sin build? |
|---|---|---|---|
| **Drawflow 0.0.60** | **45 KB + 2 KB CSS** · 8,6 gz | MIT | **sí, vanilla** |
| jsPlumb Community | 211 KB | MIT | sí |
| Cytoscape.js | 365 KB | MIT | sí |
| LiteGraph.js | 480 KB | MIT | sí |
| React Flow / tldraw / Excalidraw | — | varias | **no: React + build** |
| draw.io `embed=1` | — | — | **no: sólo contra `embed.diagrams.net`** |

**Recomendación: Drawflow.** Es **seis veces más ligero que el xterm.js** que ya
lleváis vendorizado, es vanilla sin dependencias —así que no rompe «sin build de
frontend»—, y sus nodos **son HTML**, que es lo que permite vestirlos con vuestros
tokens sin pelearse con la librería. Trae arrastre, conexiones tirando de un
puerto a otro, zoom, pan, reroute y borrado. La edición de texto in-situ no la
trae, pero se monta con `contenteditable` sobre el HTML del nodo en ~15 líneas
(hay que congelar `editor_mode` mientras se escribe, o cada clic dentro del texto
arrastra la caja).

Se descartan React Flow, tldraw y Excalidraw pese a ser mejores editores: los
tres exigen React y un bundler. Y draw.io en modo `embed` **sólo funciona contra
`embed.diagrams.net`**, o sea mandar tu arquitectura fuera — contra la primera
línea del README.

**`maquetas/j-editor.html` lo tiene montado y funciona**: arrastras, conectas,
renombras con doble clic, y a la derecha se ve en vivo el archivo que Claude
relee.

### El contrato que hace que esto no rompa nada

🔴 **La librería es sólo el editor; la verdad sigue siendo el archivo legible.**
El hub traduce en los dos sentidos. Eso significa que se puede cambiar de
librería —o quitarla— sin invalidar un solo lienzo guardado, y que el archivo
sigue siendo diffable, que es lo que sostiene el bucle.

🔴 **Las posiciones sólo se guardan si las mueves.** Mientras no toques nada, el
archivo no lleva coordenadas y el layout lo calcula el hub — así una pieza que
Claude añada después se coloca sola. En cuanto arrastras una caja, esa caja queda
**fijada** y no se recoloca. Sin esta regla pasa una de dos cosas malas: o el
layout automático te deshace la colocación cada vez que él añade algo, o deja de
colocar nada y toda pieza nueva nace amontonada en el origen.

### Y la pieza de la que dependía todo: sacar los datos del sandbox

Si el editor vive en un origen opaco, tiene que poder devolver lo editado. Se
probó (`prueba_postmessage.py`), y funcionan las dos direcciones:

```
hub → editor  (cargar el diagrama):  ✓ FUNCIONA
editor → hub  (devolver lo editado): ✓ FUNCIONA
y el WebSocket de la terminal:       llegó, y origen_permitido() lo rechazó
```

🔴 Con un detalle de seguridad que hay que fijar por escrito: **`ev.origin` vale
`"null"`** desde un sandbox opaco, así que **no se puede validar por origen**. Se
valida por **fuente**: `ev.source === marco.contentWindow`. Quien escriba ese
`addEventListener('message')` sin la comprobación deja al hub aceptando mensajes
de cualquier pestaña que le hable.

---

## 3. Las plantillas — con la cifra que corrige tu premisa

Pediste plantillas para no partir de cero y **para no engordar el contexto**. Lo
primero es acertado; lo segundo hay que matizarlo, y prefiero decírtelo:

| El mismo diagrama, emitido como… | Coste | |
|---|---|---|
| SVG a mano *(lo único que puede hoy)* | 1.936 car | 1,00× |
| Mermaid con estilos | 664 car | 0,34× |
| **Vista contra plantilla** | **540 car** | **0,28×** |
| Prosa *(lo de hoy)* | 466 car | 0,24× |

**El ahorro contra Mermaid es sólo del 19 %.** Y la prosa sigue siendo lo más
barato de todo: si el objetivo fuera ahorrar contexto, la respuesta sería no
dibujar nada. El ahorro grande —72 %— es contra el SVG a mano, que es lo único
que Claude puede producir hoy sin nada montado, y que además **sale mal**: hay
que colocar cada caja y las flechas no esquivan nada.

Así que las plantillas se justifican, pero por otras tres razones:

- **No dibujar.** Claude describe; el layout, los colores y las formas los pone
  el hub. Es el 72 %.
- **Consistencia.** Sin plantilla, cada diagrama sale con los estilos que al
  modelo le parezcan ese día. Con ella, todos se leen igual y usan tus tokens.
- **El bucle.** Una plantilla define un esquema, y un esquema es lo que hace que
  tu corrección sea válida y que él sepa qué cambió.

🔴 Y un aviso sobre el contexto que sí es real, aunque va por otro lado: **si la
skill documenta las diez plantillas, eso sí ocupa, y ocupa en cada sesión.** La
skill debe decir que existen y cómo listarlas (`hub lienzo plantillas`); el
esquema de cada una se pide cuando se va a usar. Una plantilla que hay que
explicar entera para usarla está mal diseñada.

---

## 4. El catálogo — y cuál construir primero

Contra tus casos reales, por orden de valor:

| Plantilla | Para qué | De dónde sale |
|---|---|---|
| **`decisiones`** | Los 20-30 puntos con justificación **y tu decisión**, plegados, y los vas marcando | Tu primer dolor citado |
| **`pasos`** | Orden de ejecución, secuencias, procedimientos | Tu caso de estudio (SQL) |
| **`arquitectura`** | Servicios y flujo entre ellos | Tu caso de AWS |
| **`comparativa`** | Opciones × criterios, para elegir | El informe que acabas de leer |

🔴 **Empezaría por `decisiones`, y no por el diagrama.** Es lo que citaste
primero —«informes de 20, 30 puntos […] que requieren mi decisión»— y es donde
más atención se pierde: hoy tienes que sostener 30 puntos en la cabeza *a la vez
que* decides sobre ellos. Una vista donde cada punto está plegado con su
justificación y tú marcas sí / no / luego convierte eso en 30 decisiones de una
en una. Y es **la más barata de las cuatro**: no necesita motor de layout, es una
lista.

Además es la que mejor cierra el bucle: lo que tú marcas es exactamente lo que
él necesita leer. No hace falta interpretar un dibujo, se lee `decision: si`.

`arquitectura` y `pasos` ya están construidas y funcionando en el prototipo.
`decisiones` es la que falta, y es la que yo haría primero.

---

## 5. ¿Kit? Sí — pero sólo la mitad

Preguntaste si meterlo como kit, y el razonamiento era el bueno: «por más que la
web esté preparada, si Claude Code no sabe que lo puede hacer no va a generar los
archivos». La respuesta es **sí, y la separación es la siguiente**:

| | Dónde vive | Por qué |
|---|---|---|
| `hub lienzo`, el render, el panel | **El hub** | Es infraestructura: sin ella no hay dónde pintar. Va en el producto, para todos |
| La skill (**cuándo** usar un lienzo), las plantillas | **Un kit `lienzos`** | Es criterio y contenido: evoluciona, se versiona, y no todos los proyectos quieren las mismas plantillas |

Que las plantillas viajen en el kit es lo que hace que tu nota funcione:
**cada escenario nuevo que salga es una plantilla nueva**, se añade al kit, y
`mantener-kit` la propaga a los proyectos que lo tengan. Un proyecto de AWS
acaba con plantillas de AWS; el de estudio, con las suyas. Sin kit, las
plantillas serían una carpeta que sólo crece y que nadie versiona.

Y hay una consecuencia buena: **el kit es el sitio donde va el criterio de
cuándo NO hacer un lienzo**, que es la mitad que más falta va a hacer. Un
asistente que contesta todo con diagramas es peor que uno que no dibuja ninguno,
y es la forma más probable de que esto salga mal.

---

## 6. Dónde vive el archivo — por PROYECTO

**CORREGIDO (2026-09-01).** Yo había propuesto colgarlos del **slot**, tomando al
pie de la letra su «es de la conversación, o más concretamente del slot». Él
preguntó si no debería ser por proyecto, y tenía razón: mi versión tenía un fallo
que se ve mirando el esquema.

```
~/.local/share/hub/lienzos/<proyecto_id>/<slug>.md
```

Tres razones, y la primera es la que lo decide:

1. 🔴 **`slot.id` es `INTEGER PRIMARY KEY AUTOINCREMENT`** (`db.py`): un número
   que asigna SQLite. El `proyecto.id` es TEXT y viene de `projects.yml`, y la
   skill `anexar-proyecto` dice de él que es *«la identidad y **no cambia
   nunca**»*. Colgar archivos permanentes de un autoincremental de la base es
   atarlos a algo que la propia regla dura 1 permite regenerar — y quedarían
   huérfanos en carpetas con ids de slots que ya no existen.
2. **Los slots se archivan y se borran** (`slots.borrar`), y son la unidad de
   trabajo, no la de conocimiento. El diagrama de arquitectura de un proyecto
   sigue valiendo cuando el slot de diseño se cerró hace tres meses; perderlo al
   archivar el slot sería exactamente el olvido que el hub existe para evitar.
3. **Un proyecto tiene varios slots.** El mismo diagrama hace falta en «diseño» y
   en «implementación», y con carpeta por slot habría que duplicarlo — copia, que
   es el modo de fallo que prohíbe la decisión 17.

El slot no se pierde: va como **campo del frontmatter** (`slot: diseño`), por
nombre y no por id. Sirve para que el panel enseñe primero los de donde estás, sin
que la carpeta imponga nada. Si el índice se reconstruye y los ids cambian, el
lienzo sigue sabiendo de qué proyecto es y en qué slot nació.

Y «quién lo borra» sigue teniendo respuesta sin violar el principio 9: **los
borras tú**, con `hub lienzo borrar` o quitando el archivo. Ni expiración ni
archivado automático, que es lo que prohíbe la regla dura 3.

### Por qué en `HUB_HOME` y no dentro del repo del proyecto

Esta parte no cambia, y son tres razones ya comprobadas: el caso de los repos que
tu compañero **no puede modificar** dejaría de funcionar el primer día; un
`git clean` se los lleva; y te ensucia el `git status` con archivos que no son
del proyecto.

Tiene una consecuencia que conviene decir en voz alta: **así los lienzos no se
versionan ni viajan con el repo.** Para el 95 % está bien —son material de
trabajo, no documentación—, pero el día que un diagrama merezca ser documentación
de verdad, la salida es explícita y tuya: `hub lienzo exportar <id> --a docs/`.
Fuera de la V1, pero conviene que el formato no lo impida — y no lo impide,
porque es markdown con frontmatter.

**Un detalle comprobado que hay que resolver:** hoy al agente **no se le pasa
`HUB_HOME`** — `asistente._entorno()` sólo le pone el `bin/` del asiento en el
PATH. Por eso el canal debe ser un comando, `hub lienzo`, y no una ruta: Claude
no tiene que saber dónde vive `HUB_HOME` ni componer rutas. Y de paso resuelve la
lectura, porque `HUB_HOME` está fuera del `cwd` de la sesión y leer ahí le pediría
permiso cada vez.

---

## 6b. Cómo sabe la web que hay algo que mostrar

**DECIDIDO (2026-09-01), y es su propuesta:** una carpeta, y la web lista lo que
hay dentro. Claude dice «está en `flujo-pedidos`», y tú abres el panel y ves el
más reciente o buscas el que te dijo.

Encaja con la **regla dura 1** mejor de lo que parece: *la carpeta es la fuente
de verdad y la web sólo escanea.* No hay base de datos, ni índice que mantener,
ni migración cuando cambie el formato. Borras un archivo y desaparece del panel;
copias uno y aparece. El título tampoco hay que guardarlo en ninguna parte: va en
el frontmatter del propio archivo, como ya hacen las skills y los kits
(`catalogo.py`). Y el sondeo es un `iterdir()` sobre un directorio con pocos
archivos — más barato que cualquiera de las mediciones que el hub ya hace cada
20 s.

**`maquetas/k-panel.html`** lo enseña en su sitio, con la terminal al lado.

### 🔴 Lo que esa propuesta deja abierto: Claude te pisa la edición

«Claude dice: gráfica `ejemplo-c`». ¿Y si **ya existe** un `ejemplo-c` que
acabas de editar durante veinte minutos? Con una carpeta y un nombre, escribir es
sobrescribir, **y el trabajo perdido es el tuyo**.

No es hipotético, es el caso normal: le pides un ajuste, él regenera el lienzo, y
se lleva por delante lo que habías movido. Y **no te enteras**, porque el panel
enseñará un diagrama perfectamente válido.

```
❯ hub lienzo nuevo --titulo "ejemplo-c"
  ✗ ya existe y lo editaste tú hace 20 min.
    Usa --revisar para verlo, o --forzar.

❯ hub lienzo nuevo --titulo "ejemplo-c" --revisar
  ✓ ejemplo-c-2      ← al lado, sin pisar
```

**La regla: un lienzo que tú has tocado no se sobrescribe sin decirlo.** El hub ya
sabe quién escribió el último —el `mtime` frente a la marca de publicación—, así
que no hay que llevar la cuenta de nada. Es la misma idea del instalador, que
*«nunca pisa tu registro si ya existe»*.

### Dónde se busca, y cómo se nombra

El panel enseña **los del slot en el que estás**, que es donde está el que buscas
casi siempre. Para «el que mencionó Claude hace tres días», **la búsqueda global
que ya existe** (`Ctrl+K`, `busqueda.py`): se le añade un tipo más y los
encuentra por título en todos los slots. **Cero pantallas nuevas** — que es lo
que hace que esto no sea la octava pantalla que había descartado en §3.

El `id` es el slug del título y es lo que devuelve el comando, así que Claude
siempre puede decírtelo y tú escribirlo tal cual en el buscador. Si el título se
repite, sufijo numérico; **el `id` no cambia nunca**, como el de los proyectos.

---

## 7. 🔴 El límite duro: cómo se entera Claude de tu corrección

Aquí hay un choque con vuestras propias reglas y hay que decirlo antes de
diseñar nada encima.

Lo natural sería un botón «avisar a Claude» que le pegue el aviso en su panel de
tmux. **Eso está prohibido por la regla dura 6**, y la excepción de la regla 15
es sólo para el panel del asistente, validado por id, porque el hub sabe que
dentro corre `claude` y nada más. Un panel de trabajo tuyo tiene estado
desconocido: si estás en un `vim` o en un menú, pegar texto ejecuta cosas.

**DECIDIDO (2026-09-01): el lienzo sólo registra, y el aviso lo das tú.**

> «no espero que sea automático, por ejemplo en el supuesto del diagrama yo lo
> edito desde la interfaz y hasta que ya termine le digo a Claude que lo lea de
> nuevo»

Es la opción que respeta el principio 9 y la regla dura 6 a la vez, y además es
la más barata de construir: el hub **no escribe en ningún panel, no notifica y no
vigila**. Guarda el archivo y ya. Claude lo relee cuando tú se lo dices, con
`hub lienzo ver <id>`.

Queda descartado, por tanto: que el hub pegue avisos en tu panel de tmux (rompe
la regla 6), y cualquier disparo automático al detectar un cambio. Ni siquiera
hace falta que el hub marque el lienzo como «modificado»: si tú avisas, la marca
no aporta nada.

Lo único que sí conviene es que `hub lienzo ver` acepte `--diff` y diga qué
cambió desde que Claude lo publicó. No para avisar — para que cuando lo relea no
tenga que compararlo entero.

---

## 8. La seguridad ya está resuelta, y se midió

Se montó el ataque con Chrome de verdad (`prueba_sandbox.py`): un
`<iframe sandbox="allow-scripts">` con un lienzo que va a por
`ws://…/ws/terminal/`, que es acceso de shell (regla dura 8).

```
/ws/terminal?quien=padre    Origin: 'http://127.0.0.1:8799'  → permitido   (control positivo ✓)
iframe-ws-construido        Origin: 'null'    el script del lienzo SÍ corre
iframe-BLOQUEADO-al-leer-al-padre  SecurityError   no alcanza el DOM del hub
/ws/terminal?quien=iframe   Origin: 'null'    → origen_permitido() = False  ✓ RECHAZADO
```

**El hub ya tenía escrita la defensa y no lo sabía.** Un iframe sin
`allow-same-origin` es origen opaco, manda `Origin: null`, y `origen_permitido()`
lo rechaza porque el esquema viene vacío — la misma función escrita contra las
páginas de internet.

Tres consecuencias: la defensa **no es el sandbox solo**, es el sandbox *más*
`origen_permitido` —quien «arregle» esa función para aceptar `null` abre el
agujero entero, y eso merece un test con nombre de frase—; 🔴
**`allow-same-origin` no puede aparecer nunca** en el iframe de un lienzo; y
Mermaid deja de ser un problema de seguridad, aunque siga pesando 3,4 MB
(12,3× el xterm.js).

Con `tipo: vista` nada de esto hace falta: el modelo no aporta marcado, el hub
dibuja. El sandbox sólo hace falta el día que entre `mermaid` o `html`.

---

## 9. Por dónde empezaría

**1 · `hub lienzo` y la plantilla `decisiones`.** El comando, el directorio por
slot, y la vista que ataca tu primer dolor. No necesita motor de layout.

**2 · El panel en `/trabajo`,** pestaña junto a la nota, que no roba el foco:
aparece con un punto y la abres tú. Reutiliza el tirador y el ancho recordado
que ya existen.

**3 · El kit `lienzos`** —skill + plantillas— **a la vez que el 2, no después.**
Hasta que exista, el panel es una pantalla vacía: se midieron tus 132
transcripts —**319 MB, 1.013 bloques de código, cero lienzos**— y el 92 % de los
bloques que Claude escribe hoy van sin etiqueta de lenguaje.

**4 · `arquitectura` y `pasos`,** portando el motor del prototipo. Ya funcionan.

**5 · El editor arrastrable** (Drawflow en iframe sandbox, con `postMessage`
validado por fuente) y el cierre del bucle.

**6 · `md`, y `mermaid`/`html` en el mismo iframe** — sólo si al usarlo aparece
la falta.

## Lo que no haría

- **Que el hub pegue avisos en tu panel de trabajo.** Ver §7.
- **Traer React para el editor** (React Flow, tldraw, Excalidraw). Rompe «sin
  build de frontend», que es una de vuestras convenciones más antiguas.
- **draw.io en modo embed.** Sólo funciona contra `embed.diagrams.net`.
- **Guardar el formato nativo de la librería** como archivo del lienzo. Ata los
  lienzos a Drawflow para siempre y deja de ser diffable. Ver §2b.
- **Empezar por el diagrama de arquitectura.** Es el caso más vistoso y el que
  tú mismo dijiste que no es el primero.
- **Escribir los lienzos dentro de los repos.**
- **Mandar el lienzo fuera para que lo dibujen.** El hub «no manda nada a ninguna
  parte», y un diagrama de tu arquitectura es justo lo que no quieres subir.
- **Documentar todas las plantillas en la skill.** Ver §3.

---

---

## 10. Las situaciones, para aprobar

**`maquetas/i-situaciones.html`** las enseña enteras, con el ciclo completo: lo
que Claude escribe en su terminal, lo que ves en el hub, lo que corriges y lo que
él relee. **La primera funciona**: se marcan las decisiones y el archivo que
Claude leería cambia debajo.

- **A · El informe de 30 puntos** → `decisiones`. La que yo construiría primero.
- **B · La arquitectura que corriges** → `arquitectura`, con el ciclo entero y
  el diff de dos líneas.
- **C · Estudiando** → `pasos`. Sin bucle, y a propósito: **no todo lienzo se
  corrige**, y una plantilla que obliga a contestar algo no sirve para estudiar.

Lo que hay que aprobar o cambiar ahí es el **contrato del comando**
—`hub lienzo nuevo --plantilla X --titulo "…"` · `ver <id>` · `ver <id> --diff` ·
`plantillas` · `listar`— y las **cuatro plantillas**.

Un detalle de A que conviene mirar con atención porque es el que decide si esto
cumple su objetivo: en el paso 1, Claude **no repite los 8 puntos en la
terminal**. Si los repitiera, el lienzo sería una cosa más que mirar, y entonces
no sirve — es el criterio de §0 aplicado.
