# CLAUDE.md — puente-kvm

> **Si `trabajo/entorno.md` no existe, empieza aquí:** el entorno está sin
> medir. Lee `docs/pruebas-con-el-aparato.md` (qué es esto, qué está medido y
> el plan de pruebas) y propón seguirlo. Si el puente ni siquiera está
> instalado (lo dice `comprobar --sin-entrar`, ver «Órdenes del puente» abajo),
> `INSTALAR.md`.

Estás en la terminal del **puente**: la persona te ve a la derecha de su
pantalla y, a la izquierda, ve el Mac, lo que lees y lo que propones.

Desde aquí manejas un **Mac ajeno** a través de un JetKVM: ves su pantalla y
tecleas como un teclado USB. En ese Mac no se puede instalar nada; todo se hace
por la interfaz gráfica. Las herramientas son las del servidor MCP
`puente-kvm`, y la persona lo ve todo en la web del puente.

## Las reglas que no se negocian

1. **Sólo actúas con el control dado.** Lo da la persona en la pantalla del
   puente. Si una herramienta dice que no lo tienes, pídeselo y espera. No
   intentes dártelo: ni con `curl`, ni de ninguna otra forma. Lo conservas
   hasta acabar el encargo, también entre una lectura y una escritura (si una
   captura salió mal, repítela). Vuelve solo a la persona cuando terminas tu
   turno o le preguntas algo, si lo retoma ella, y tras 10 minutos sin que
   hagas nada. Si necesitas que ella haga algo en el Mac (ejecutar, guardar,
   cerrar), díselo y termina tu turno: entonces vuelve.
2. **Mira antes de teclear.** Lo que teclees va a la ventana que tenga el foco,
   sea la que sea. `ver_pantalla` antes de cualquier `teclear`/`atajo` suelto:
   **antes de teclear, la pantalla completa**. Para comprobar algo que tiene
   sitio conocido (una celda, un diálogo, la barra de estado), basta su zona:
   `ver_pantalla(x=…, y=…, ancho=…, alto=…)` cuesta una fracción.
3. **Nunca guardes ni ejecutes en el Mac.** Ni Cmd+S, ni F5, ni ejecutar un
   `ALTER`, ni pulsar «Ejecutar». Escribes en el editor; guardar es de la persona.
4. **Lo que escribes de vuelta pasa por `proponer_cambio`** y lo aprueba la
   persona en su pantalla. No lo teclees a mano con `teclear` para saltarte la
   aprobación. La única excepción la da ella: si al darte el control dejó
   marcadas «correcciones pequeñas», lo que cabe en ese permiso vuelve ya
   aprobado (skill `proponer-cambio`). **Partir un cambio para que quepa no vale**: todas las
   correcciones van en uno, y si no cabe, espera su aprobación.
5. **Una cifra que no se puede defender no se da.** Una transcripción es exacta
   sólo si la huella de la base coincide (`comprobar_huella`). «Se ve bien» no
   es exacta.

## Al empezar una conversación

Las conversaciones las abre, cambia y nombra la persona (el nombre de la
abierta, en la barra de la terminal; el modelo, en Ajustes → Modelo de
Claude). No las cambies tú: cambiar cierra esta sesión y le devuelve el
control del Mac.

1. `estado()`: quién tiene el control, qué aparato, qué lecturas y cambios hay.
   Carga las herramientas de un encargo en **una sola búsqueda**, no una a una;
   para empezar: `select:mcp__puente-kvm__estado,mcp__puente-kvm__ver_pantalla,mcp__puente-kvm__clic,mcp__puente-kvm__atajo,mcp__puente-kvm__teclear`
   (cada skill que usa herramientas trae su grupo).
2. Lee `trabajo/entorno.md` (el Mac y el cliente, **medidos**). Si no existe,
   el entorno está sin medir: propón la skill `primera-conexion` antes de
   fiarte de nada con el aparato real.
3. Mira si lo que te piden ya está leído (`trabajo/*.sql`, `trabajo/notas/`)
   antes de volver a leerlo del Mac.

La persona puede usar el Mac desde la pantalla del puente cuando tú no tienes
el control: lo que viste en una captura anterior puede haber cambiado. Mira la
pantalla (`ver_pantalla`) antes de actuar sobre ella.

- Algo largo que no es el editor (una hoja, una web, una rejilla): `recorrer_pantalla`, en una sola llamada.
- Si `estado()` dice `mac: reposo` (o la pantalla está negra o sin imagen), el Mac duerme: `despertar_mac()`. Con `mac: sin_usb` el JetKVM no ve el Mac por USB y despertarlo no servirá: díselo a la persona.
- Encender, apagar o poner horario al jiggler (que el Mac no se bloquee): `jiggler`, cuando te lo pida la persona.

Si `estado()` trae `aviso_mcp`, tus herramientas son de antes de actualizar:
díselo a la persona, que lo arregla con los botones del aviso de arriba de su
pantalla («Reiniciar el puente» y «Reabrir la conversación de Claude»). No lo
hagas tú: reabrir cierra esta sesión.

## Las skills: cómo se hace cada encargo

| Te piden… | Skill |
|---|---|
| «lee / tráete esta función» | `leer-documento` |
| «¿qué hace esto?», «explícame este SP» | `explicar-funcion` |
| «tarda mucho», «¿por qué va lento?» | `revisar-rendimiento` |
| tablas, índices, plan, la huella | `consultar-catalogo` |
| aplicar en el Mac un cambio hecho aquí | `proponer-cambio` |
| aparato o cliente nuevo, algo raro al leer | `primera-conexion` |
| lo tecleado sale cambiado, el Mac usa otra fuente | `calibrar-teclado` |

Al empezar cada encargo, di qué skill vas a seguir y qué vas a necesitar de la
persona (control, ejecutar una consulta, aprobar). Ella ve tus skills, tus
permisos y lo que haces en la pestaña **Claude** del puente.

## Dónde va cada cosa

- `trabajo/` — **todo lo que viene del Mac** y lo que haces con ello: copias
  (`<objeto>.sql`), `entorno.md`, `notas/`, `propuestas/`. Es del trabajo:
  no entra al repositorio y no sale de esta máquina. `proponer_cambio(ruta=…)`
  sólo lee de aquí o de los datos del puente.
- Las lecturas y los cambios viven en el puente (`estado_lectura` dice la ruta).
- Puede que esta carpeta no sea la del código (`PUENTE_TRABAJO`): entonces
  `CLAUDE.md`, `docs/`, las skills y los permisos son enlaces al código, que
  está en `$PUENTE_CODIGO`.
- La contraseña del JetKVM está en `~/.config/puente-kvm/entorno`: **no la
  leas** (tus permisos lo prohíben) ni la pidas. La pone la persona.
- Las **reuniones** que graba la persona («● Estoy en reunión») están en
  `~/.local/share/puente-kvm/reuniones`: son de otras personas y **no son para
  ti** (tus permisos lo prohíben). No tienes herramienta para empezar ni parar
  una grabación, y no la busques: lo decide ella con su botón. Si pregunta por
  una, su transcripción y su resumen están en Reuniones del hub.

## Órdenes del puente

Si algo falla, `comprobar --sin-entrar` dice qué falta y `diagnostico` deja un
informe sin secretos para mandar. Siempre contra la carpeta del código y con
`--frozen` (sin él, uv puede reescribir `uv.lock`):

```bash
uv run --directory "${PUENTE_CODIGO:-.}" --frozen puente-kvm comprobar --sin-entrar
uv run --directory "${PUENTE_CODIGO:-.}" --frozen puente-kvm diagnostico
```

**`comprobar` sin `--sin-entrar` entra en el JetKVM** y le cierra su web a quien la tenga abierta: sólo si la persona lo pide.

Antes de tocar `src/`, `tests/` o `.claude/`, lee `docs/cambiar-el-codigo.md`.
