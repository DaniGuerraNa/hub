"""Adaptador de tmux.

Modelo espejo: tmux sigue siendo la fuente de verdad de qué está abierto. El hub
observa y lanza. La terminal embebida (decisión 34) se engancha a tmux con
`attach`; no le quita a tmux el papel de quien hospeda los procesos.
"""

from __future__ import annotations

import os
import re
import shlex
import socket
import subprocess
from pathlib import Path

from . import procesos

# session | window | pane | pane_id | cwd | título | comando | activo
_FORMATO = (
    "#{session_name}\t#{window_index}\t#{pane_index}\t#{pane_id}\t"
    "#{pane_current_path}\t#{pane_title}\t#{pane_current_command}\t#{pane_active}"
)

# Claude Code antepone un glifo de estado al título ("⠂ Continuar con los
# pendientes", "✳ Debugar lambda"). Se limpia sin tocar acentos ni signos de
# apertura del español.
_GLIFO_INICIAL = re.compile(r"^[^\w¿¡«\"'(\[]+", re.UNICODE)

# Ese glifo no es decoración: es la ÚNICA señal de actividad que da Claude Code
# sin leer la pantalla entera, y llega gratis porque `list-panes` ya la trae.
# Mientras piensa gira un spinner del bloque braille (⠂ ⠐ …); cuando no, pone
# otra cosa (✳). Medido en esta máquina: 240 títulos con ✳ contra 60 braille.
#
# 🔴 El glifo NO distingue "terminó" de "te está esperando con una pregunta":
# los dos son ✳. Para eso haría falta leer el contenido del panel.
_BRAILLE = (0x2800, 0x28FF)

# Shells: un panel con una de estas no está corriendo un asistente, así que su
# título no dice nada de actividad.
SHELLS = {"bash", "zsh", "sh", "fish"}


# Prefijo de las sesiones espejo que crea el hub para la terminal embebida.
# Son sesiones AGRUPADAS: comparten las mismas ventanas que la original, así que
# si no se excluyen, `list-panes -a` cuenta cada panel dos veces.
PREFIJO_ESPEJO = "hub-"


# Todo destino que venga de la URL pasa por aquí antes de tocar la línea de
# comandos de tmux. Un nombre de sesión sin validar es inyección.
NOMBRE_VALIDO = re.compile(r"^[\w.\-]+$")

# Un id de panel de tmux es siempre `%<número>`. Es la clave con la que se
# valida el único panel donde se permite escribir (regla dura 15).
PANEL_VALIDO = re.compile(r"^%\d+$")


class TmuxNoDisponible(RuntimeError):
    pass


class DestinoInvalido(ValueError):
    pass


def validar_sesion(session: str) -> str:
    """El nombre, si cabe en `NOMBRE_VALIDO`; si no, `DestinoInvalido`. Lo que
    llega de una URL acaba en la línea de órdenes de tmux (regla dura 9)."""
    if not isinstance(session, str) or not NOMBRE_VALIDO.match(session):
        raise DestinoInvalido(session)
    return session


def validar_panel(pane_id: str) -> str:
    """El id, si es `%N`; si no, `DestinoInvalido` (regla dura 9). Un id de
    panel no es un nombre: con `%` sólo se apunta a un panel, nunca a una sesión."""
    if not isinstance(pane_id, str) or not PANEL_VALIDO.match(pane_id):
        raise DestinoInvalido(pane_id)
    return pane_id


def orden_base() -> list[str]:
    """`tmux`, o `tmux -L <socket>` si se pidió un servidor aparte.

    🔴 `HUB_HOME` aísla el disco pero **no aísla tmux**: hasta que existió esto,
    correr los tests en una máquina con trabajo abierto creaba y mataba sesiones
    en el servidor de tmux real del usuario. Pasó durante la auditoría —una
    prueba dejó una sesión suelta que hubo que borrar a mano—, y un proyecto que
    se publica no puede pedirle a nadie que ejecute sus tests a ciegas.

    `-L` levanta un servidor de tmux distinto, con su propio socket: lo que pasa
    ahí dentro no toca ni ve las sesiones de nadie.

    Se lee en cada llamada y no al importar, para que un test pueda ponerlo sin
    recargar el módulo.
    """
    # `aparte` y no `socket`: este módulo importa el módulo `socket` y una
    # variable con ese nombre lo sombrearía dentro de la función.
    aparte = os.environ.get("HUB_TMUX_SOCKET")
    # 🔴 `-f /dev/null`: el servidor aparte NO lee el `~/.tmux.conf` de quien
    # ejecuta. Con tmux-continuum ahí, cada servidor nuevo restauraba las
    # sesiones reales del usuario —también el de pruebas—, así que un test
    # encontraba una sesión `encargos` que no había creado y no la limpiaba:
    # sus ventanas se acumulaban de una ejecución a otra hasta tumbarlo (264).
    return ["tmux", "-L", aparte, "-f", "/dev/null"] if aparte else ["tmux"]


# Órdenes que pueden CREAR el servidor de tmux. No importan por lo que hacen,
# sino por de quién queda colgando el servidor que arrancan.
_PUEDEN_CREAR_SERVIDOR = {"new-session", "new"}

# El cgroup propio lo da `procesos` (decisión 344, que generaliza ésta). Aquí
# sólo se envuelve lo que puede crear el servidor, con `run` y no con `Popen`:
# tmux vuelve en el acto y su salida hace falta.
_PREFIJO_DESASIR = procesos.PREFIJO_SCOPE


def _hay_donde_desasir() -> bool:
    return procesos.puede_desasir()


def _correr(args: list[str], entrada: str | None = None) -> str:
    orden = [*orden_base(), *args]

    # 🔴 El servidor de tmux hereda el cgroup de quien lo arranca (decisión 153).
    # `hub-web` corre bajo systemd, y systemd mata el cgroup entero al parar o
    # reiniciar una unidad: si el servidor nace ahí dentro, una caída de la web
    # se lleva por delante TODAS las sesiones de trabajo. Pasó el 2026-09-04 —
    # tres abortos de `hub-web` en 81 segundos, tres servidores de tmux muertos.
    # Envolver sólo lo que puede crear el servidor basta: si ya existe, ninguna
    # otra orden lo re-parenta.
    desasida = args and args[0] in _PUEDEN_CREAR_SERVIDOR and _hay_donde_desasir()
    if desasida:
        orden = [*_PREFIJO_DESASIR, *orden]

    try:
        salida = subprocess.run(
            orden, input=entrada, capture_output=True, text=True,
            timeout=10, check=False,
        )
    except FileNotFoundError as exc:  # tmux no instalado
        raise TmuxNoDisponible("tmux no está en el PATH") from exc

    # Si el que falló fue `systemd-run`, se repite a pelo. No puede duplicar una
    # sesión: cuando no consigue montar el scope, ni siquiera llega a ejecutar
    # la orden. Y quedarse sin terminal por no poder aislar un cgroup sería
    # cambiar un riesgo por una avería.
    if desasida and salida.returncode != 0:
        try:
            salida = subprocess.run(
                [*orden_base(), *args], input=entrada, capture_output=True,
                text=True, timeout=10, check=False,
            )
        except FileNotFoundError as exc:
            raise TmuxNoDisponible("tmux no está en el PATH") from exc
    if salida.returncode != 0:
        err = salida.stderr.strip()
        # 🔴 «error connecting to …» es lo que dice tmux cuando el SOCKET no
        # existe, que es el estado normal de quien acaba de instalar el hub y
        # todavía no ha abierto ninguna sesión. Faltaba en esta lista, así que
        # se convertía en `RuntimeError` y tumbaba `/trabajo` —la pantalla
        # principal— a 500 desnudo.
        #
        # No se detectó nunca porque en la máquina de quien lo escribió siempre
        # hay tmux corriendo: apareció al clonar el producto en limpio y
        # arrancarlo, que es exactamente lo que hará quien lo reciba. Quitar
        # tmux del PATH tampoco lo destapaba —eso da `FileNotFoundError`, que
        # sí estaba cubierto—: hay que tenerlo instalado y sin servidor.
        sin_servidor = (
            "no server running" in err
            or "failed to connect" in err
            or "error connecting" in err
            or "no such file or directory" in err.lower()
        )
        if sin_servidor:
            raise TmuxNoDisponible(err)
        raise RuntimeError(f"tmux {' '.join(args)} falló: {err}")
    return salida.stdout


def servidor_pid() -> int | None:
    """Identifica el 'epoch' del servidor de tmux.

    Si cambia entre dos snapshots, hubo un reinicio: es como se detecta que se
    perdió una sesión de trabajo sin depender de ningún hook.
    """
    try:
        return int(_correr(["display-message", "-p", "#{pid}"]).strip())
    except (TmuxNoDisponible, ValueError):
        return None


def _titulo_por_defecto() -> set[str]:
    """tmux pone el hostname como título cuando nadie lo setea."""
    host = socket.gethostname()
    return {host.lower(), host.split(".")[0].lower()}


def limpiar_titulo(titulo: str) -> str:
    return _GLIFO_INICIAL.sub("", titulo).strip()


def tiene_glifo_estado(titulo: str) -> bool:
    """Si el título lo está escribiendo algo que reporta estado, o sea Claude.

    Se pregunta por el glifo y no por `pane_current_command` porque el comando
    no es de fiar en los dos sentidos: hay quien arranca el asistente por un
    envoltorio (`node`, un alias) y hay paneles con `vim` o `python` que no
    reportan nada. Sin esto, un panel con vim se pintaba «detenido» y mandaba a
    mirar un sitio donde no había pasado nada.
    """
    return bool(titulo) and limpiar_titulo(titulo) != titulo


def es_spinner(titulo: str) -> bool:
    """Si el título viene con el spinner de Claude Code, o sea: está pensando.

    Toma el título entero y no el carácter suelto a propósito: quien la llama
    tiene un `pane_title`, y hacerle recortar el primer carácter es una forma
    fácil de equivocarse con un título vacío.
    """
    if not titulo:
        return False
    return _BRAILLE[0] <= ord(titulo[0]) <= _BRAILLE[1]


def inferir_etiqueta(titulo: str, cwd: str, comando: str) -> str:
    """Etiqueta legible del panel.

    Claude Code ya escribe en `pane_title` una descripción viva de lo que hace la
    sesión, así que cuando existe es mejor que cualquier cosa que podamos inferir.
    Para shells sueltas se compone con carpeta + comando + rama de git.
    """
    limpio = limpiar_titulo(titulo)
    if limpio and limpio.lower() not in _titulo_por_defecto():
        return limpio

    carpeta = Path(cwd).name or cwd
    partes = [carpeta]
    if comando and comando not in SHELLS:
        partes.append(comando)
    rama = rama_git(cwd)
    if rama:
        partes.append(rama)
    return " · ".join(partes)


def rama_git(cwd: str) -> str | None:
    try:
        salida = subprocess.run(
            ["git", "-C", cwd, "branch", "--show-current"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (FileNotFoundError, subprocess.SubprocessError):
        return None
    rama = salida.stdout.strip()
    return rama or None


def listar_paneles(incluir_espejos: bool = False) -> list[dict]:
    """Todos los paneles del servidor, sin importar quién los abrió.

    Las sesiones espejo del hub se excluyen por defecto: comparten ventanas con
    la sesión original y duplicarían cada panel.
    """
    try:
        crudo = _correr(["list-panes", "-a", "-F", _FORMATO])
    except TmuxNoDisponible:
        return []

    paneles = []
    for linea in crudo.splitlines():
        campos = linea.split("\t")
        if len(campos) < 8:
            continue
        session, window, pane, pane_id, cwd, titulo, comando, activo = campos[:8]
        if not incluir_espejos and session.startswith(PREFIJO_ESPEJO):
            continue
        paneles.append(
            {
                "session": session,
                "window_idx": int(window) if window.isdigit() else 0,
                "pane_idx": int(pane) if pane.isdigit() else 0,
                "pane_id": pane_id,
                "cwd": cwd,
                "titulo": titulo,
                "comando": comando,
                "activo": activo == "1",
            }
        )
    return paneles


_FORMATO_VENTANA = (
    "#{window_index}\t#{window_name}\t#{window_active}\t#{window_panes}\t"
    "#{pane_current_command}\t#{pane_title}\t#{pane_current_path}\t"
    # `automatic-rename` distingue un nombre puesto a mano de uno que inventa
    # tmux: renombrar una ventana lo apaga solo. Verificado contra tmux.
    "#{automatic-rename}\t"
    # El ancho real de la ventana. La vista lo compara con el suyo: si no
    # coinciden se pierden caracteres al final de cada línea, y sin este dato
    # no hay forma de verlo.
    "#{window_width}\t"
    # El panel activo y el servidor: con ellos se cierra la ventana (396), y
    # salen de la misma llamada que el índice. Al final, para no mover los de
    # antes.
    "#{pane_id}\t#{pid}"
)


def listar_ventanas(session: str) -> list[dict]:
    """Ventanas de una sesión, con la etiqueta de su panel activo."""
    validar_sesion(session)
    try:
        crudo = _correr(["list-windows", "-t", f"={session}", "-F", _FORMATO_VENTANA])
    except (TmuxNoDisponible, RuntimeError):
        return []

    ventanas = []
    for linea in crudo.splitlines():
        campos = linea.split("\t")
        if len(campos) < 7:
            continue
        indice, nombre, activa, paneles, comando, titulo, cwd = campos[:7]
        # Sin el campo (tmux viejo) se asume automático, que es el caso común.
        automatico = campos[7] != "0" if len(campos) > 7 else True
        ventanas.append(
            {
                "indice": int(indice) if indice.isdigit() else 0,
                "nombre": nombre,
                "activa": activa == "1",
                "paneles": int(paneles) if paneles.isdigit() else 1,
                "comando": comando,
                # Un nombre puesto a mano MANDA sobre el título de Claude Code.
                # Antes no: renombrar guardaba bien el nombre en tmux y la
                # pestaña seguía pintando `pane_title`, que Claude Code
                # reescribe cada pocos segundos. El renombrado funcionaba y
                # parecía roto, que es la peor combinación.
                "etiqueta": nombre if not automatico
                else inferir_etiqueta(titulo, cwd, comando),
                "renombrada": not automatico,
                "ancho": int(campos[8]) if len(campos) > 8 and campos[8].isdigit() else None,
                "cwd": cwd,
                "pane_id": campos[9] if len(campos) > 9 else "",
                "servidor": int(campos[10]) if len(campos) > 10 and campos[10].isdigit() else None,
            }
        )
    return ventanas


# Directorios de usuario que systemd NO pone en el PATH y que sí están en el de
# una shell de login. Se añaden a mano a todo lo que el hub lanza.
_BIN_DE_USUARIO = ("~/.local/bin", "~/.npm-global/bin", "~/bin")


def path_de_usuario(extra: str | None = None) -> str:
    """El PATH que debe ver lo que el hub lanza, con `extra` delante si se pasa.

    🔴 Salió de un fallo real y silencioso. `hub-web` corre bajo **systemd de
    usuario**, cuyo PATH es `/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:
    /sbin:/bin` — sin `~/.local/bin`. Todo lo que el hub abría en tmux heredaba
    ese PATH mutilado, así que el asistente no encontraba su propio comando
    `hub` y contestaba, muy convencido: *«hub no está en el PATH de esta sesión;
    prueba abrir el chat desde la interfaz del hub»* — que es exactamente de
    donde venía.

    No se ve probando a mano porque una shell interactiva sí tiene el PATH bueno:
    el mismo comando funciona escrito por el usuario y falla lanzado por el hub.
    """
    partes = [extra] if extra else []
    partes += [str(Path(d).expanduser()) for d in _BIN_DE_USUARIO]
    actual = os.environ.get("PATH", "")
    vistos: list[str] = []
    for parte in [*partes, *actual.split(os.pathsep)]:
        if parte and parte not in vistos:
            vistos.append(parte)
    return os.pathsep.join(vistos)


def con_entorno(comando: str, entorno: dict[str, str] | None) -> str:
    """`comando` con su entorno DENTRO, por `env`.

    🔴 `-e PATH=…` de tmux no llega al proceso: medido el 2-nov con tmux
    3.4 (C-0041), una ventana pedida con el PATH de `hub-web` y
    `-e PATH=<el del usuario>` arrancó `/usr/bin/claude` 2.1.112 en vez del
    `claude` 2.1.280 del dueño. Es el fallo de la decisión 231, que se había
    arreglado en `abrir_ventana` y seguía vivo en las otras tres primitivas.
    Por eso el entorno va aquí, en un solo sitio, para todas.

    Medido otra vez el 6-nov (C-0058, `test_tmux_entorno.py`): tmux pone el
    PATH del CLIENTE que da la orden, con comando y sin él; otra variable por
    `-e` sí llega. Sin comando no se manda nada: la shell de login lee su
    perfil, y su PATH sale igual con `-e PATH` que sin él. Las primitivas ya no
    llevan `-e`, y su `entorno` sólo sirve con comando.
    """
    if not entorno:
        return comando
    asignaciones = " ".join(shlex.quote(f"{k}={v}") for k, v in entorno.items())
    return f"env {asignaciones} {comando}"


def literal(texto: str) -> str:
    """Un nombre o una ruta tal cual, sin que tmux lo lea como formato (C-0078).

    `-c` y `-n` de `new-window`/`new-session`/`respawn-pane`, `rename-window` y
    `select-pane -T` expanden formatos, y `#(orden)` en un formato **ejecuta**
    la orden. Medido con tmux 3.4 en un servidor aparte (3-nov): una ruta
    `#(touch x)` en `-c` crea `x`; en `-n` el nombre se queda vacío (se
    evalúa) y en una de dos mediciones también lo creó. `##` es el `#` literal
    en los cinco. El
    `-e` no expande y no se escapa. Lo que pase por aquí puede venir de una
    carpeta clonada, del nombre de un slot o de un cwd restaurado (reglas 9-10).
    """
    return texto.replace("#", "##")


def nueva_ventana(
    session: str,
    ruta: str | None = None,
    nombre: str | None = None,
    comando: str | None = None,
    entorno: dict[str, str] | None = None,
) -> int | None:
    """Crea una ventana y devuelve su índice, para poder navegar hasta ella.

    Sin `ruta` se abre donde está la ventana actual de esa sesión, que es lo que
    significa «una ventana más aquí». 🔴 Sin el `-c`, tmux hereda el cwd de quien
    creó la SESIÓN: para todo lo que abre el hub eso es `hub-web`, que corre bajo
    systemd desde el directorio del hub. El botón daba una shell en el código del
    hub en vez de en el proyecto, y no había nada en la pantalla que lo explicara.
    """
    validar_sesion(session)
    args = ["new-window", "-P", "-F", "#{window_index}", *al_final(session)]
    # `-c` admite un formato de tmux, resuelto contra el destino: es el idioma
    # de tmux para «aquí mismo» y evita una consulta extra.
    args += ["-c", literal(ruta) if ruta else "#{pane_current_path}"]
    if nombre:
        args += ["-n", literal(nombre)]
    if comando:
        args.append(con_entorno(comando, entorno))
    salida = _correr(args).strip()
    return int(salida) if salida.isdigit() else None


def existe_sesion(session: str) -> bool:
    validar_sesion(session)
    try:
        _correr(["has-session", "-t", f"={session}"])
        return True
    except (RuntimeError, TmuxNoDisponible):
        return False


def nueva_sesion(
    session: str,
    ruta: str | None = None,
    nombre_ventana: str | None = None,
    comando: str | None = None,
    entorno: dict[str, str] | None = None,
    conservar: bool = False,
) -> None:
    """Crea la sesión desasida.

    El comando va aquí y no en un `send-keys` posterior a propósito: `new-session`
    lo arranca **como** el proceso de la ventana, sin pasar por una shell cuyo
    prompt habría que adivinar. Es la diferencia entre lanzar un proceso y
    teclear en una terminal ajena (decisión 22).
    """
    validar_sesion(session)
    args = ["new-session", "-d", "-s", session]
    if ruta:
        args += ["-c", literal(ruta)]
    if nombre_ventana:
        args += ["-n", literal(nombre_ventana)]
    if comando:
        args.append(con_entorno(comando, entorno))
    # Ver `abrir_ventana`: aquí importa aún más, porque una sesión cuyo único
    # comando muere desaparece ENTERA, y con ella cualquier forma de mirar.
    if conservar:
        args += [";", "set-option", "-p", "-t", f"={session}:", "remain-on-exit", "on"]
    _correr(args)


def panel_de_sesion(session: str) -> str:
    """El panel activo de una sesión: lo que `new-session -d` no devuelve.

    🔴 **`list-panes`, no `display-message`.** `display-message -p -t "=sesión"
    "#{pane_id}"` devuelve una línea VACÍA: con un destino de sesión no hay panel
    con el que resolver el formato, y da igual que haya un cliente atacado —se
    midió con y sin—. Es prima hermana de la decisión 21: otro comando de tmux
    que acepta el prefijo `=` y luego no hace lo que parece.

    El síntoma no era un error, y por eso duró: `slots.abrir()` sólo entra aquí
    cuando **no hay servidor de tmux**, o sea en una instalación recién hecha
    (decisión 151). La ventana se abría bien, así que parecía funcionar; lo que
    no pasaba era el `vincular()` de después, y el slot se quedaba sin su
    ventana. Justo el caso que la decisión 151 existía para arreglar, y justo el
    que no se ve en una máquina donde siempre hay tmux abierto.
    """
    validar_sesion(session)
    paneles = _correr(["list-panes", "-t", f"={session}", "-F", "#{pane_id}"]).split()
    return paneles[0] if paneles else ""


def renombrar_ventana(session: str, indice: int, nombre: str) -> None:
    validar_sesion(session)
    _correr(["rename-window", "-t", f"={session}:{int(indice)}", literal(nombre)])


class ServidorDistinto(RuntimeError):
    """El panel salió del muestreo de un servidor de tmux que ya no es el de
    ahora: su `%N` puede ser hoy otra ventana."""


def cerrar_ventana_de(pane_id: str, servidor: int | str | None) -> bool:
    """Mata la ventana que contiene `pane_id` y todo lo que corra dentro.
    Acción destructiva (decisión 396).

    Por el panel y no por `sesión:índice`: tmux reasigna los índices libres,
    y el segundo clic sobre una fila vieja mataba otra ventana. Con `%N`, si
    el panel ya no existe tmux falla en vez de elegir otra: devuelve False
    («ya estaba cerrada»). `servidor` es el `server_pid` del muestreo con el
    que se pintó lo que se pulsó; los `%N` se reutilizan al reiniciar tmux, y
    si no coincide no se cierra nada (`ServidorDistinto`)."""
    validar_panel(pane_id)
    try:
        esperado = int(servidor) if servidor is not None else None
    except (TypeError, ValueError):
        esperado = None
    actual = servidor_pid()
    if actual is None:
        return False  # sin servidor no queda ninguna ventana abierta
    if esperado != actual:
        raise ServidorDistinto("tmux se reinició desde que se pintó esta página")
    try:
        _correr(["kill-window", "-t", pane_id])
    except RuntimeError as exc:
        if "can't find pane" in str(exc):
            return False
        raise
    return True


def seleccionar_ventana(destino: str, indice: int) -> None:
    """Cambia la ventana activa de `destino`.

    Se usa contra la sesión ESPEJO, nunca contra la real: así moverte por la UI
    no arrastra de ventana a quien esté atacado en la terminal nativa.
    """
    validar_sesion(destino)
    _correr(["select-window", "-t", f"={destino}:{int(indice)}"])


# ── Las sesiones espejo de la terminal embebida (las usa `terminal`) ─────────


def listar_sesiones() -> list[tuple[str, int, int]]:
    """(nombre, clientes atacados, epoch de creación) de cada sesión."""
    crudo = _correr(["list-sessions", "-F", "#{session_name}\t#{session_attached}\t#{session_created}"])
    sesiones = []
    for linea in crudo.splitlines():
        partes = linea.split("\t")
        if len(partes) < 3:
            continue
        try:
            sesiones.append((partes[0], int(partes[1] or 0), int(partes[2] or 0)))
        except ValueError:
            continue
    return sesiones


def agrupar_sesion(origen: str, nombre: str) -> None:
    """Crea `nombre` en el grupo de `origen`: mismas ventanas, tamaño propio.

    🔴 tmux NO falla si `origen` no existe: lee `-t` como el nombre de un
    grupo y lo crea, con una shell vacía en el cwd de quien llama. Quien llama
    comprueba antes que exista (`terminal.crear_espejo`)."""
    validar_sesion(origen)
    validar_sesion(nombre)
    _correr(["new-session", "-d", "-t", origen, "-s", nombre])


def ajustar_ventana_a_quien_mira(session: str, indice: int) -> None:
    """`aggressive-resize` en esa ventana, y sin `-g`: con `-g` la opción queda
    puesta en todo el servidor, también en las sesiones del dueño."""
    validar_sesion(session)
    _correr(["set-window-option", "-t", f"={session}:{int(indice)}", "aggressive-resize", "on"])


def clientes_y_grupo() -> list[tuple[str, str]]:
    """(sesión del cliente, grupo de esa sesión) de cada cliente atacado."""
    crudo = _correr(["list-clients", "-F", "#{client_session}\t#{session_group}"])
    return [(p[0], p[1]) for p in (l.split("\t") for l in crudo.splitlines()) if len(p) >= 2]


def grupo_de_sesion(session: str) -> str:
    """El grupo de la sesión, o "" si no está agrupada.

    🔴 **`=sesión:`, con los dos puntos.** Con `-t =sesión` a secas
    `display-message` devuelve una línea VACÍA para `#{session_group}` —medido
    en tmux 3.4, con y sin cliente atacado—, prima de lo de `panel_de_sesion`.
    Vacía, `terminal._hay_otro_espectador` contestaba siempre «nadie» y la
    ventana se encogía con la terminal del dueño mirándola (C-0087)."""
    validar_sesion(session)
    return _correr(["display-message", "-p", "-t", f"={session}:", "#{session_group}"]).strip()


def activar_raton(session: str) -> None:
    """La rueda entra en el copy-mode. `mouse` es opción de sesión: sólo ésa.

    Sin `=`: `set-option` es el único que NO acepta ese prefijo («no such
    session: =hub-…»), y callado el síntoma era «el scroll no va» (regla dura
    21). El nombre ya pasó por `validar_sesion`."""
    validar_sesion(session)
    _correr(["set-option", "-t", session, "mouse", "on"])


def matar_sesion(session: str) -> None:
    """Mata la sesión entera. Acción destructiva: hoy sólo la usan los espejos."""
    validar_sesion(session)
    _correr(["kill-session", "-t", f"={session}"])


def escribir_titulo(pane_id: str, titulo: str) -> None:
    """Escribe la etiqueta de vuelta a tmux para que aparezca en la status bar."""
    validar_panel(pane_id)
    _correr(["select-pane", "-t", pane_id, "-T", literal(titulo)])


def al_final(session: str) -> list[str]:
    """Dónde va una ventana nueva: detrás de la última de su sesión.

    🔴 Sin esto tmux le da el número libre más bajo, y tras cerrar una la
    siguiente se colaba en ese hueco, a media lista: no se veía cuál era la
    última que se abrió (21-oct). Y no se renumera al cerrar, a propósito: la
    terminal se reconecta y los enlaces apuntan por número de ventana, y
    renumerar los haría caer en otra sin que nada lo dijera.
    """
    validar_sesion(session)
    return ["-a", "-t", f"={session}:{{end}}"]


def abrir_ventana(ruta: str, nombre: str, comando: str | None = None,
                  session: str | None = None,
                  conservar: bool = False,
                  entorno: dict[str, str] | None = None) -> str:
    """Abre una ventana nueva en la ruta del slot.

    La UI LANZA terminales, no las hospeda: sin PTY, sin rendering, sin resize.
    """
    args = ["new-window", "-P", "-F", "#{pane_id}", "-c", literal(ruta), "-n", literal(nombre)]
    # 🔴 Sin `-e PATH=`: se probó y NO llega al proceso —la ventana nueva sale
    # con el PATH del CLIENTE que la pide, que desde systemd es el del servicio
    # y encuentra otro `claude` (decisión 231)—. El PATH va DENTRO del comando
    # con `env`, que es lo que la regla dura 18 ya prescribía para el primer
    # panel de una sesión; ver `slots.abrir`.
    if session:
        args += al_final(session)
    if comando:
        args.append(con_entorno(comando, entorno))
    # 🔴 `remain-on-exit` en la MISMA orden que crea la ventana, no en otra
    # después: un comando que muere al instante cerraría la ventana entre las
    # dos y se llevaría el motivo (decisión 231). `new-window` deja la ventana
    # nueva como actual de su sesión, y `-t =sesion:` es esa ventana.
    if conservar and session:
        args += [";", "set-option", "-p", "-t", f"={session}:", "remain-on-exit", "on"]
    return _correr(args).strip()


def panel_enfocado(excluir: set[str] | None = None) -> str | None:
    """El panel donde el usuario estuvo escribiendo más recientemente.

    **`pane_active` no sirve para esto**, y la primera versión de este diseño lo
    daba por bueno: medido contra su tmux, `#{pane_active}` vale 1 en el panel
    activo de **cada** ventana —diez paneles abiertos, diez «activos»—. Con eso,
    una nota sin destino explícito caía en cualquiera.

    Lo que sí distingue es `client_activity`: el epoch de la última vez que se
    usó cada cliente atacado. Con sus tres pantallas daba 1787937361 (hace 9 min),
    1787937266 y 1787872737 (hace 18 h), que separa perfectamente dónde está de
    dónde estuvo ayer.

    Del cliente más reciente se toma su sesión, y de ella el panel activo de su
    ventana activa. Si ese cliente está en una sesión espejo del hub, el pane_id
    que sale es el **real**: las espejo comparten ventanas con la original, así
    que el id es el mismo y la atribución funciona igual.
    """
    excluir = excluir or set()
    try:
        crudo = _correr(["list-clients", "-F", "#{client_activity}\t#{client_session}"])
    except (TmuxNoDisponible, RuntimeError):
        return None

    candidatos = []
    for linea in crudo.splitlines():
        campos = linea.split("\t")
        if len(campos) < 2 or not campos[0].strip().isdigit():
            continue
        sesion = campos[1].strip()
        if not sesion or sesion in excluir or not NOMBRE_VALIDO.match(sesion):
            continue
        candidatos.append((int(campos[0]), sesion))

    # Del más reciente al más antiguo, y se prueba hasta que uno resuelva: la
    # lista de clientes puede traer sesiones que ya no existen.
    for _, sesion in sorted(candidatos, reverse=True):
        panel = _panel_activo_de(sesion)
        if panel:
            return panel
    return None


def _panel_activo_de(session: str) -> str | None:
    """El panel activo de la ventana activa de una sesión.

    Con `list-panes` y un filtro, y **no** con `display-message -t =<sesión>`:
    ese devuelve una línea vacía para `#{pane_id}` —comprobado—, así que la
    resolución fallaba en silencio y ninguna nota encontraba nunca su slot.
    """
    try:
        salida = _correr([
            "list-panes", "-t", f"={session}", "-s", "-F", "#{pane_id}",
            "-f", "#{&&:#{window_active},#{pane_active}}",
        ])
    except (TmuxNoDisponible, RuntimeError):
        return None
    primero = salida.strip().splitlines()
    return primero[0].strip() if primero else None


def titulo_panel(pane_id: str) -> str | None:
    """El `pane_title` crudo, con su glifo de estado. None si el panel murió.

    🔴 **Se pide el `pane_id` junto al título y se comprueba que coincide**, y
    no es puntillismo: `display-message -t %999` sobre un panel que ya no existe
    **sale con código 0 y devuelve una cadena vacía**. Medido el 18-sep, no
    supuesto. Sin esta comprobación esta función nunca devolvía `None`, así que
    la rama «el panel ya no existe» de `entrega.quien_hay` era **código muerto**:
    un panel cerrado se rechazaba igual —porque `tui.detectar` tampoco encuentra
    a nadie— pero con el motivo equivocado, y quien leyera el registro buscaría
    un agente que se salió a una shell donde lo que había era una ventana
    cerrada. Dos averías distintas contadas como la misma.
    """
    validar_panel(pane_id)
    try:
        salida = _correr(
            ["display-message", "-p", "-t", pane_id, "#{pane_id}\t#{pane_title}"]
        )
    except (TmuxNoDisponible, RuntimeError):
        return None
    visto, _, titulo = salida.partition("\t")
    return titulo.strip() if visto.strip() == pane_id else None


def comando_de_panel(pane_id: str) -> str:
    """El proceso en primer plano del panel. Cadena vacía si no se puede leer.

    Es la señal FUERTE sobre qué hay dentro: lo reporta tmux del tty, no lo
    pinta la aplicación. Sirve para afirmar («aquí corre `codex`»), nunca para
    negar: quien arranca un agente por un envoltorio o un alias hace que esto
    diga `node` o `sh` con el agente perfectamente vivo — ver `tiene_glifo_estado`.
    """
    validar_panel(pane_id)
    try:
        return _correr(
            ["display-message", "-p", "-t", pane_id, "#{pane_current_command}"]
        ).strip()
    except (TmuxNoDisponible, RuntimeError):
        return ""


def panel_muerto(pane_id: str) -> bool:
    """Si el proceso del panel ya terminó (y la ventana sigue por `remain-on-exit`)."""
    validar_panel(pane_id)
    return _correr(["display-message", "-p", "-t", pane_id, "#{pane_dead}"]).strip() == "1"


def conservar_al_morir(pane_id: str, conservar: bool) -> None:
    """`remain-on-exit` sobre UN panel: que morir deje el error a la vista.

    Sin esto, un comando que falla al arrancar cierra la ventana y se lleva el
    motivo: el hub lo daba por abierto y nadie veía el «option … is invalid»
    (decisión 231). Se enciende sólo mientras se comprueba el arranque y se
    apaga después, para que salir de un agente a mano siga cerrando la ventana.
    """
    validar_panel(pane_id)
    _correr(["set-option", "-p", "-t", pane_id, "remain-on-exit", "on" if conservar else "off"])


def matar_panel(pane_id: str) -> None:
    """Mata un panel y lo que corre dentro. Acción destructiva: sólo sobre
    paneles que abrió el hub (el de un entrevistador, el de una tarea), nunca
    sobre una ventana de trabajo del dueño."""
    validar_panel(pane_id)
    _correr(["kill-pane", "-t", pane_id])


def pid_del_panel(pane_id: str) -> int | None:
    """El proceso raíz del panel: el que tmux arrancó, no lo que corre encima."""
    validar_panel(pane_id)
    salida = _correr(["display-message", "-p", "-t", pane_id, "#{pane_pid}"]).strip()
    return int(salida) if salida.isdigit() else None


def relanzar_panel(pane_id: str, ruta: str, comando: str,
                   entorno: dict[str, str] | None = None) -> None:
    """Mata lo que corre en el panel y arranca `comando` en el MISMO panel.

    El mismo y no uno nuevo porque el id del panel es lo que casa al slot, a
    las esperas del orquestador y a la pestaña de /trabajo: con `respawn-pane`
    ninguno se entera de que debajo cambió el proceso (decisión 268).
    """
    validar_panel(pane_id)
    args = ["respawn-pane", "-k", "-t", pane_id, "-c", literal(ruta)]
    args.append(con_entorno(comando, entorno))
    _correr(args)


def capturar_panel(pane_id: str, unir_lineas: bool = False,
                   con_historia: bool = False) -> str:
    """Lo que se ve en el panel ahora mismo. Cadena vacía si no se puede leer.

    `unir_lineas` pide `-J`, que junta las líneas que el terminal partió por
    ancho. Hace falta para **buscar** un texto: un comando de 37 caracteres en
    un panel de 30 sale cortado en dos y no casa con la cadena que se escribió.
    """
    validar_panel(pane_id)
    try:
        # `con_historia` pide también el scrollback (`-S -`). Hace falta para
        # leer lo que escribió un proceso que murió: el rótulo «Pane is dead»
        # que pinta tmux desplaza su salida fuera de la pantalla visible
        # (medido: sin `-S` la captura traía sólo el rótulo).
        return _correr(["capture-pane", "-p", *(["-J"] if unir_lineas else []),
                        *(["-S", "-"] if con_historia else []),
                        "-t", pane_id])
    except (TmuxNoDisponible, RuntimeError):
        return ""


# Nombre del búfer de tmux que usa el hub. Fijo y propio: `load-buffer` sin `-b`
# apila en la pila global y pisaría lo que el usuario tenga copiado a mano.
BUFER = "hub-asistente"


def pegar_en_panel(pane_id: str, texto: str, enter: bool = True) -> None:
    """Escribe un texto en un panel como si se hubiera pegado, y lo despacha.

    🔴 Sólo se llama sobre el panel del asistente, y quien llama debe haberlo
    validado por id (regla dura 15). Aquí no se comprueba de quién es el panel:
    esta capa es el adaptador de tmux y no conoce esa política.

    **`send-keys` con el texto no sirve**, y no es una preferencia de estilo:
    Claude Code despacha con Enter, así que un mensaje de tres líneas se enviaría
    como tres mensajes sueltos y el tercero contestaría al primero. `load-buffer`
    + `paste-buffer` entrega el bloque entero; el Enter va después y aparte, ya
    con el mensaje completo en el prompt.

    🔴 **`-p` no es opcional.** Se comprobó contra el asistente real: sin él, un
    `paste-buffer` normal manda los saltos de línea como pulsaciones de Enter y
    el mensaje se parte igual que con `send-keys` —«Preséntate en una frase» y
    «y di qué no puedes hacer» llegaron como dos mensajes, y el segundo contestó
    fuera de contexto—. `-p` envuelve el texto en *bracketed paste*, que es como
    la TUI distingue un pegado de alguien tecleando.

    El texto viaja por **stdin**, no en la línea de comandos: es texto libre del
    usuario y puede tener cualquier cosa dentro, incluidas comillas.
    """
    validar_panel(pane_id)
    _correr(["load-buffer", "-b", BUFER, "-"], entrada=texto)
    # `-d` borra el búfer tras pegarlo: no deja el mensaje colgando en la pila.
    _correr(["paste-buffer", "-b", BUFER, "-p", "-t", pane_id, "-d"])
    if enter:
        enter_en_panel(pane_id)


def enter_en_panel(pane_id: str) -> None:
    """Sólo la tecla Enter, sin texto. Despacha lo que ya esté escrito."""
    tecla_en_panel(pane_id, "Enter")


# Las únicas teclas que el hub puede pulsar. Es una lista cerrada a propósito:
# `send-keys` acepta cualquier cosa, incluido texto entero, y ahí es donde vive
# el peligro que describe la decisión 22. Con esto, lo peor que puede llegar a
# un panel por esta puerta es un dígito o un Escape.
TECLAS_PERMITIDAS = frozenset({"Enter", "Escape", *(str(d) for d in range(10))})


def tecla_en_panel(pane_id: str, tecla: str) -> None:
    """Pulsa UNA tecla de la lista cerrada en un panel.

    Existe aparte de `pegar_en_panel` porque **el pegado no sirve para un menú**:
    se comprobó contra el cuadro de permisos de Claude Code, y un `1` entregado
    por `paste-buffer -p` no selecciona nada —el *bracketed paste* está pensado
    para campos de texto, y un menú espera una pulsación—. Con `send-keys` el
    dígito sí elige la opción.
    """
    validar_panel(pane_id)
    if tecla not in TECLAS_PERMITIDAS:
        raise DestinoInvalido(f"tecla no permitida: {tecla!r}")
    _correr(["send-keys", "-t", pane_id, tecla])


def comando_de_apertura(ruta: str, nombre: str, comando: str | None) -> str:
    """El equivalente en texto, para poder copiarlo si se prefiere hacerlo a mano."""
    base = f"tmux new-window -c {shlex.quote(literal(ruta))} -n {shlex.quote(literal(nombre))}"
    return f"{base} {shlex.quote(comando)}" if comando else base
