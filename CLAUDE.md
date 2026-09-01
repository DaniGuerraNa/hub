# CLAUDE.md — el hub

Este repositorio es el **hub**: un índice de proyectos, sesiones de trabajo y
capacidades, que corre en la máquina del usuario. `README.md` explica qué hace.

## Si te piden instalarlo

Usa la skill **`instalar-hub`**. Trae el procedimiento entero: qué comprobar, qué
pedir permiso antes de tocar, y cómo verificar que quedó funcionando.

🔴 **No instales nada del sistema sin permiso explícito, una cosa cada vez.**
Estás en la máquina de alguien.

## Si te piden usarlo

| Piden… | Skill |
|---|---|
| «anexa mi proyecto», «registra este repo» | `anexar-proyecto` |
| «crea un proyecto» | `nuevo-proyecto` |
| «aplica el kit X» | `aplicar-kit` |
| «quiero un kit para X» | `nuevo-kit` |
| «mantén el kit X» | `mantener-kit` |
| «¿cómo hago X en el hub?» | `sobre-el-hub` |

## Las tres reglas del hub

1. **El hub indexa; nunca mueve ni copia contenido de otros proyectos.** Si algo
   necesita escribir dentro de un proyecto ajeno, lo hace un agente corriendo
   ahí, con el usuario mirando — no el servidor.
2. **Nunca se almacena un secreto.** Sólo datos de conexión y un puntero a dónde
   vive la credencial. El hub comprueba si el puntero existe; jamás lo abre.
3. **Nada automático.** No archiva, no expira, no avisa y no hace push. Mide y
   muestra; la acción es del usuario.

## Si te piden cambiar el código

- **Los tests se corren antes de cerrar nada:** `uv run pytest`.
- **El registro del usuario es `~/.local/share/hub/projects.yml`**, fuera del
  repo. No lo edites para «probar»: son sus datos.
- **La base de datos es un índice**, no la fuente de verdad. Todo lo que viva
  sólo ahí tiene que poder reconstruirse escaneando.
- **Sin dependencias nuevas en el navegador.** Nada de CDN ni de bundler: Jinja,
  formularios normales y JavaScript en `static/`.
- **Español** en nombres, comentarios, tests y en la interfaz.

## Lo que no debes hacer

- **No expongas el puerto a la red.** La terminal del hub da acceso de shell y
  hoy sólo la protege el bind a `127.0.0.1`. Ni «un momento para probar».
- **No pares contenedores en lote.** Docker se acciona de uno en uno y por nombre
  exacto: en el Docker de alguien conviven contenedores de varios proyectos.
- **No inventes cifras.** Si una medición no se puede defender, no se muestra.
