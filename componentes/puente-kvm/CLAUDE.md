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
`puente-kvm` (`.mcp.json`), y la persona lo ve todo en
**http://127.0.0.1:8794** (u otro puerto si `PUENTE_PUERTO` lo dice).

## Las reglas que no se negocian

1. **Sólo actúas con el control dado.** Lo da la persona en la pantalla del
   puente. Si una herramienta dice que no lo tienes, pídeselo y espera. No
   intentes dártelo: ni con `curl`, ni de ninguna otra forma. El control
   vuelve solo a la persona al terminar una lectura o una escritura, y tras 10
   minutos sin que hagas nada.
2. **Mira antes de teclear.** Lo que teclees va a la ventana que tenga el foco,
   sea la que sea. `ver_pantalla` antes de cualquier `teclear`/`atajo` suelto.
3. **Nunca guardes ni ejecutes en el Mac.** Ni Cmd+S, ni F5, ni ejecutar un
   `ALTER`, ni pulsar «Ejecutar». Escribes en el editor; guardar es de la persona.
4. **Lo que escribes de vuelta pasa por `proponer_cambio`** y lo aprueba la
   persona en su pantalla. No lo teclees a mano con `teclear` para saltarte la
   aprobación.
5. **Una cifra que no se puede defender no se da.** Una transcripción es exacta
   sólo si la huella de la base coincide (`comprobar_huella`). «Se ve bien» no
   es exacta.

## Al empezar una conversación

Las conversaciones las abre, cambia y nombra la persona (el nombre de la
abierta, en la barra de la terminal; el modelo, en Ajustes → Modelo de
Claude). No las cambies tú: cambiar cierra esta sesión y le devuelve el
control del Mac.

1. `estado()`: quién tiene el control, qué aparato, qué lecturas y cambios hay.
2. Lee `trabajo/entorno.md` (el Mac y el cliente, **medidos**). Si no existe,
   el entorno está sin medir: propón la skill `primera-conexion` antes de
   fiarte de nada con el aparato real.
3. Mira si lo que te piden ya está leído (`trabajo/*.sql`, `trabajo/notas/`)
   antes de volver a leerlo del Mac.

La persona puede usar el Mac desde la pantalla del puente cuando tú no tienes
el control: lo que viste en una captura anterior puede haber cambiado. Mira la
pantalla (`ver_pantalla`) antes de actuar sobre ella. La rueda: positivo baja
el contenido; si el Mac la tiene invertida, el puente lo corrige solo (Ajustes).

Para mirar sólo una parte, `ver_pantalla(x, y, ancho, alto)`: llega a tamaño
real y se lee mejor que la pantalla entera reducida. Para recorrer de arriba
abajo algo que no es el editor (una hoja, una web, una rejilla larga),
`recorrer_pantalla`, en **una sola llamada**: no lo hagas a golpes de `rueda`
y `ver_pantalla`. Si `estado()` trae `aviso_mcp`, tus herramientas son de
antes de actualizar: díselo a la persona.

## Las skills: cómo se hace cada encargo

| Te piden… | Skill |
|---|---|
| «lee / tráete esta función» | `leer-documento` |
| «¿qué hace esto?», «explícame este SP» | `explicar-funcion` |
| «tarda mucho», «¿por qué va lento?» | `revisar-rendimiento` |
| tablas, índices, plan, la huella | `consultar-catalogo` |
| aplicar en el Mac un cambio hecho aquí | `proponer-cambio` |
| aparato o cliente nuevo, algo raro al leer | `primera-conexion` |

Al empezar cada encargo, di qué skill vas a seguir y qué vas a necesitar de la
persona (control, ejecutar una consulta, aprobar). Ella lo ve también en el
puente: la pestaña **Claude** enseña tus skills, tus permisos y lo que estás
haciendo (lo cuentan tus hooks).

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
- Si algo falla: `comprobar --sin-entrar` dice qué falta, y `diagnostico`
  deja un informe sin secretos para mandar (ver abajo cómo lanzarlas).

## Órdenes del puente

Esta carpeta puede no ser la del código, y entonces `uv run puente-kvm …` a
secas falla («Failed to spawn»). Lánzalas siempre contra la carpeta del código,
que tu sesión tiene en `PUENTE_CODIGO`, y siempre con `--frozen` (sin él, uv
puede reescribir `uv.lock`, un archivo versionado):

```bash
uv run --directory "${PUENTE_CODIGO:-.}" --frozen puente-kvm comprobar --sin-entrar
uv run --directory "${PUENTE_CODIGO:-.}" --frozen puente-kvm diagnostico
```

**`comprobar` sin `--sin-entrar` entra en el JetKVM** (si el puente no está en
marcha) y le cierra su web a quien la tenga abierta en un navegador. Para saber
si el puente está bien, `--sin-entrar`; sin él, sólo si la persona lo pide.

## Para cambiar el código del puente

- `uv run --directory "${PUENTE_CODIGO:-.}" --frozen pytest` en verde antes de
  cerrar nada, mirando el código de salida.
  El flujo completo se prueba contra el Mac simulado (`simulador.py`) y el
  cliente del JetKVM contra un JetKVM falso por WebRTC real
  (`tests/jetkvm_falso.py`). Las pruebas usan su propia carpeta de datos, su
  propio archivo de contraseña y un puerto libre: nunca los de verdad.
- Lo que se ve se comprueba en un navegador (Playwright), no se razona.
- El protocolo del JetKVM, sacado de su firmware, está en
  `docs/protocolo-jetkvm.md`. Lo que no se ha visto con el aparato delante
  está marcado como no verificado: no lo des por bueno. Si el cliente no
  conecta, la última sección de ese documento dice cómo buscarlo.
- Lo versionado no nombra a nadie: ni nombres, ni correos, ni rutas de la
  carpeta personal de nadie.
- Español en el código, comentarios que explican el porqué.
