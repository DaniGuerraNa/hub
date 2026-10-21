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
| «hazme un diagrama», «ponlo en el hub» | `lienzos` |

## Las tres reglas del hub

1. **El hub indexa; nunca mueve ni copia contenido de otros proyectos.** Si algo
   necesita escribir dentro de un proyecto ajeno, lo hace un agente corriendo
   ahí, con el usuario mirando — no el servidor.
2. **Nunca se almacena un secreto.** Sólo datos de conexión y un puntero a dónde
   vive la credencial. El hub comprueba si el puntero existe; jamás lo abre.
3. **Nada automático.** No archiva, no expira y no hace push. Mide y muestra;
   la acción es del usuario. La única excepción son unos pocos avisos por
   Telegram de una lista cerrada, y sólo si el usuario activa el canal.

## Si te piden cambiar el código

- **Los tests se corren antes de cerrar nada:** `uv run pytest`.
- **El registro del usuario es `~/.local/share/hub/projects.yml`**, fuera del
  repo. No lo edites para «probar»: son sus datos.
- **La base de datos es sobre todo un índice**: lo que se mide se reconstruye
  escaneando. Pero los slots, sus notas, el canal, los programados y los
  encargos **sólo viven ahí**. 🔴 Nunca la borres «para empezar limpio»; si
  hace falta, se aparta (`conocimiento/06-problemas.md`). Y no metas en ella
  nada nuevo que no se pueda reconstruir sin dejarlo dicho.
- **Sin dependencias nuevas en el navegador.** Nada de CDN ni de bundler: Jinja,
  formularios normales y JavaScript en `static/`.
- **Español** en nombres, comentarios, tests y en la interfaz.

### Las reglas de seguridad del código

El código las cita por número («regla dura N», «decisión N»); esos números
vienen del repositorio de desarrollo, que no se publica. Lo que dicen:

- **No se escribe en un panel de tmux cuyo contenido no se conoce.** Pegar en
  una shell ejecuta comandos reales. La excepción es acotada: sólo donde el hub
  comprueba, en el instante de escribir, que dentro corre un agente (Claude
  Code o Codex), o en una ventana que acaba de crear y sin pulsar Enter. Texto
  por `load-buffer` + `paste-buffer -p`; teclas sueltas sólo de una lista
  cerrada.
- **Todo destino de tmux se valida contra `NOMBRE_VALIDO`** antes de llegar a la
  línea de comandos. Un nombre que venga de la URL sin validar es inyección.
- **Todo lo que se pasa a una shell va con `shlex.quote`.** Un prompt o una
  plantilla son texto libre.
- **El token de Telegram sólo lo leen los servicios del canal** (`hub-canal`,
  `hub-encargos`), nunca `hub-web`, que es el que expone el puerto.
- **`api.py` es la única costura de lectura.** Una plantilla o una ruta que
  consulta SQL o lee archivos por su cuenta es un defecto.
- **El JavaScript se prueba ejecutándolo**, no sólo pidiendo la página: un 200
  no detecta un script que revienta al arrancar.

## Lo que no debes hacer

- **No expongas el puerto a la red.** La terminal del hub da acceso de shell,
  así que escucha sólo en `127.0.0.1`: nunca `0.0.0.0` ni internet, ni «un
  momento para probar». Para entrar desde otro aparato existe la pantalla
  Acceso (red privada, nombres exactos, aparatos dados de alta y la terminal
  tras su interruptor); ver `conocimiento/10-mas-pantallas.md`. No la debilites:
  nada de comodines en los nombres, nada de saltarse el alta.
- **No pares contenedores en lote.** Docker se acciona de uno en uno y por nombre
  exacto: en el Docker de alguien conviven contenedores de varios proyectos.
- **No inventes cifras.** Si una medición no se puede defender, no se muestra.
