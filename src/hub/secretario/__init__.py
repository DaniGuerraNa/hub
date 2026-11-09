"""El secretario (`PLAN-SECRETARIO.md`, decisiones 298-305).

Un asistente del día a día del dueño: lee sus fuentes, guarda lo importante en
una memoria propia, contesta con el origen de lo que dice, recuerda lo que
quedó pendiente y hace cosas a través de un catálogo de acciones con nivel de
confianza.

Cómo está partido, y por qué así:

- `memoria`   — la base propia (`HUB_HOME/secretario/memoria.db`). Es lo que
  sabe; ninguna conversación vive lo bastante para necesitar compactar.
- `piezas`    — el contrato de fuentes y acciones. El núcleo sólo conoce el
  contrato: añadir una fuente o una acción es añadir un archivo.
- `fuentes/`, `acciones/` — las piezas concretas.
- `enrutador` — qué modelo atiende cada trabajo.
- `motor`     — cómo se llama al modelo: `claude -p` con la suscripción.
- `herramientas` y `mcp` — lo que el modelo puede usar, servido por MCP.
- `triaje`, `conversacion`, `recordatorios`, `disparadores` — los trabajos.
- `servicio`  — el bucle de `hub-secretario`.
"""
