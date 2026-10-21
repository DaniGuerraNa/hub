# Cambios

Qué trae cada versión del hub, empezando por la más nueva. Cada una dice tres
cosas: **qué hay nuevo**, **qué cambia en lo que ya usabas** y **qué tienes que
hacer tú** —casi siempre nada más que actualizar—.

Para actualizar, en la carpeta del hub:

```bash
bash scripts/actualizar.sh
```

Al terminar te enseña esta misma lista, sólo con las versiones que acabas de
cruzar.

## 0.2.0 — 2026-10-20

La primera versión con número. Desde aquí, cada versión se publica con su
etiqueta (`v0.2.0`), su entrada en este archivo y, si hace falta, sus pasos
propios, y se actualiza con un solo comando.

### Qué tienes que hacer

🔴 **Si instalaste el hub antes de esta versión**, actualiza esta vez así:

```bash
git pull && bash scripts/actualizar.sh --sin-bajar
```

`git pull` y reiniciar —lo que decía la documentación hasta ahora— **no basta
esta vez**: los servicios se generan distinto y el asistente trae instrucciones
nuevas. Si ya hiciste sólo el `git pull`, el hub te lo dice en todas las
pantallas hasta que corras `actualizar.sh`. Tus datos no se tocan.

Después de actualizar:

- **Revisa los guardrails de tus proyectos** (ver «Qué cambia»): si el
  orquestador trabaja en proyectos con `guardrail: ask`, ahora te pedirá
  confirmación la primera vez que toque cada uno en cada tarea.
- **Pulsa «Limpiar» en el chat del asistente** (rueda de ajustes) para que lea
  sus instrucciones nuevas.

### Nuevo

- **Versiones y aviso de versión nueva.** El hub sabe qué versión tiene, mira
  una vez al día si hay otra publicada y lo dice arriba en todas las pantallas.
  Nunca se actualiza solo. `/guia` tiene una sección «Versión». Se apaga con
  `HUB_BUSCAR_VERSIONES=0` (es la única consulta a internet que hace el hub por
  su cuenta).
- **`scripts/actualizar.sh`**: baja la versión, regenera los servicios con tu
  puerto y tus datos, pone al día el asistente, aplica los pasos de cada
  versión, reinicia lo que estaba en marcha y te dice qué cambió.
- **Copia diaria de la base.** `hub.db` guarda datos que no existen en ningún
  otro sitio —tus slots y sus notas, el canal, los mensajes programados, los
  encargos—, así que ahora se copia sola una vez al día, guardando las 14
  últimas, en `~/.local/share/hub/respaldos/` (o `HUB_RESPALDO`). `/respaldo`
  dice cuándo fue la última y avisa si tiene más de dos días. Esa carpeta está
  en el mismo disco: cópiala a otro sitio si quieres sobrevivir a un disco
  muerto.
- **El comando `hub` en `~/.local/bin`**, también fuera del chat del asistente.
  Lo crea `sembrar-asistente.sh` (y `actualizar.sh` si ya tenías asistente). Si
  ya tenías un `hub` ahí, no se pisa.
- **El orquestador pide confirmación** en los proyectos con `guardrail: ask`:
  una tarjeta en `/orquestador` con «Confirmar» o «No, sin ese proyecto».
- **Documentación**: `conocimiento/10-mas-pantallas.md` (Acceso, Canal,
  Encargos, Lienzos, Programados, Archivos, Máquina, Consumo y atajos), y el
  resto puesto al día con lo que el hub hace hoy.

### Qué cambia en lo que ya usabas

- 🔴 **`guardrail: ask` ahora significa algo.** Antes `auto` y `ask` se
  comportaban igual. Ahora, en un proyecto `ask`, el orquestador no abre
  sesiones, no manda trabajo, no ajusta ni compacta sin que confirmes —una vez
  por tarea y proyecto—. Si quieres que trabaje sin preguntar en un proyecto,
  ponlo en `auto`. `never` sigue igual.
- **`hub.db` no se borra nunca.** La documentación decía que se reconstruía
  escaneando; no es verdad para tus slots y notas. Si la base no abre, se
  aparta y se restaura desde la copia diaria (`conocimiento/06-problemas.md`).
- **Seguridad, dicha como es.** La terminal y el resto del hub siguen
  escuchando sólo en `127.0.0.1`. Para entrar desde el móvil está `/acceso`
  (red privada, aparatos dados de alta por QR y un interruptor aparte para la
  terminal). La documentación ya no dice que lo único que protege es el bind.
- **Los textos de la pantalla ya no citan números de reglas** internas.
- **Los servicios llevan `HUB_PORT`**: si instalaste el hub en otro puerto, el
  aviso de «el hub no contesta» y el pánico del canal miran ya el correcto.
- **`HUB_CONTEXTO_FICHERO`** se respeta también en el lado del hub (antes sólo
  lo leía la línea de estado del asistente).
- **El kit `lienzos`** está en el catálogo público (0.2): su skill dice dónde
  están de verdad las plantillas.

## 0.1.0 — hasta el 2026-10-17

Todo lo publicado antes de que el hub tuviera número de versión. No tiene
etiqueta: quien lo instaló entonces pasa a la 0.2.0 con el comando de arriba.
