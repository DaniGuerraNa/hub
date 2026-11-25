# Cambiar el código del puente

Para quien toca `src/`, `tests/` o `.claude/` (Claude incluido). Está aquí y no
en `CLAUDE.md` porque `CLAUDE.md` va entero en cada llamada de la sesión del
puente, y casi ninguna cambia el código.

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

## Los permisos de la sesión de Claude

- `.claude/settings.json`: lo que se permite y lo que se niega, los hooks y el
  servidor. **Sin reglas «ask»**: lo cargan los dos modos, y en «Sin pedir
  permisos» una «ask» seguiría preguntando antes de cada clic.
- `.claude/preguntar.json`: las reglas «ask». `terminal.ajustes_de_sesion` las
  suma por `--settings` sólo en el modo normal. Una herramienta nueva del
  servidor MCP lleva su regla en uno de los dos (lo comprueba una prueba).
- La sesión no carga los ajustes de usuario de Claude Code de quien la abre
  (`--setting-sources project,local --strict-mcp-config`): de ellos sólo se
  lleva la lista cerrada `terminal.DE_LA_PERSONA` y sus «deny» (y, en el modo
  normal, sus «ask»), y lleva siempre `terminal.SIEMPRE` (sin control remoto
  ni lo sincronizado de claude.ai). Si una función necesita algo más de ahí,
  se añade a esa lista a propósito, no se abre la fuente entera.
- Lo que lanza Claude Code va con esas mismas banderas también en la shell que
  queda al cerrarse (`terminal._shell_de_despues`): un `claude` sin ellas
  cargaría lo personal y ninguna «ask».
- Los «deny» que protegen los datos del puente (`ajustes.json`, que guarda el
  teclado en uso y las teclas reservadas; `teclados/**`, las medidas; las
  reuniones) van con la ruta por omisión, `~/.local/share/puente-kvm`. Claude
  Code no lee variables en sus reglas: con otro `PUENTE_HOME`, **no cubren
  nada**, y hay que añadir a mano las mismas reglas con esa ruta.

## Límites conocidos

- **Las huellas de la calibración del teclado (C-0481) y las de
  `comprobar_huella` se fían de Claude.** Puede leer `ronda.filas` de la medida
  (los datos del puente se leen sin preguntar) y calcular las huellas con Bash
  en vez de leerlas de la rejilla: la verificación probaría la tabla contra sí
  misma. Es el mismo modelo de confianza que la huella de una lectura, y no se
  cambia: la barrera es que la persona ejecuta la consulta y ve el resultado.
