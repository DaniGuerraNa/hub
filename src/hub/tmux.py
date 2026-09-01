"""Adaptador de tmux.

Modelo espejo: tmux sigue siendo la fuente de verdad de qué está abierto. El hub
observa y lanza; no hospeda terminales (decisión 16).
"""

from __future__ import annotations

import os
import re
import shlex
import socket
import subprocess
from pathlib import Path

# session | window | pane | pane_id | cwd | título | comando | activo
_FORMATO = (
    "#{session_name}\t#{window_index}\t#{pane_index}\t#{pane_id}\t"
    "#{pane_current_path}\t#{pane_title}\t#{pane_current_command}\t#{pane_active}"
)

# Claude Code antepone un glifo de estado al título ("⠂ Continuar con los
# pendientes", "✳ Debugar lambda"). Se limpia sin tocar acentos ni signos de
# apertura del español.
_GLIFO_INICIAL = re.compile(r"^[^\w¿¡«\"'(\[]+", re.UNICODE)

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
    if not isinstance(session, str) or not NOMBRE_VALIDO.match(session):
        raise DestinoInvalido(session)
    return session


def validar_panel(pane_id: str) -> str:
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
    return ["tmux", "-L", aparte] if aparte else ["tmux"]


def _correr(args: list[str], entrada: str | None = None) -> str:
    try:
        salida = subprocess.run(
            [*orden_base(), *args], input=entrada, capture_output=True, text=True,
            timeout=10, check=False,
        )
    except FileNotFoundError as exc:  # tmux no instalado
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
    if comando and comando not in {"bash", "zsh", "sh", "fish"}:
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
    "#{window_width}"
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


def nueva_ventana(
    session: str,
    ruta: str | None = None,
    nombre: str | None = None,
    comando: str | None = None,
    entorno: dict[str, str] | None = None,
) -> int | None:
    """Crea una ventana y devuelve su índice, para poder navegar hasta ella."""
    validar_sesion(session)
    args = ["new-window", "-P", "-F", "#{window_index}", "-t", f"={session}:"]
    for clave, valor in (entorno or {}).items():
        args += ["-e", f"{clave}={valor}"]
    if ruta:
        args += ["-c", ruta]
    if nombre:
        args += ["-n", nombre]
    if comando:
        args.append(comando)
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
) -> None:
    """Crea la sesión desasida.

    El comando va aquí y no en un `send-keys` posterior a propósito: `new-session`
    lo arranca **como** el proceso de la ventana, sin pasar por una shell cuyo
    prompt habría que adivinar. Es la diferencia entre lanzar un proceso y
    teclear en una terminal ajena (decisión 22).
    """
    validar_sesion(session)
    args = ["new-session", "-d", "-s", session]
    for clave, valor in (entorno or {}).items():
        args += ["-e", f"{clave}={valor}"]
    if ruta:
        args += ["-c", ruta]
    if nombre_ventana:
        args += ["-n", nombre_ventana]
    if comando:
        args.append(comando)
    _correr(args)


def renombrar_ventana(session: str, indice: int, nombre: str) -> None:
    validar_sesion(session)
    _correr(["rename-window", "-t", f"={session}:{int(indice)}", nombre])


def cerrar_ventana(session: str, indice: int) -> None:
    """Mata la ventana y todo lo que corra dentro. Acción destructiva."""
    validar_sesion(session)
    _correr(["kill-window", "-t", f"={session}:{int(indice)}"])


def seleccionar_ventana(destino: str, indice: int) -> None:
    """Cambia la ventana activa de `destino`.

    Se usa contra la sesión ESPEJO, nunca contra la real: así moverte por la UI
    no arrastra de ventana a quien esté atacado en la terminal nativa.
    """
    validar_sesion(destino)
    _correr(["select-window", "-t", f"={destino}:{int(indice)}"])


def escribir_titulo(pane_id: str, titulo: str) -> None:
    """Escribe la etiqueta de vuelta a tmux para que aparezca en la status bar."""
    _correr(["select-pane", "-t", pane_id, "-T", titulo])


def abrir_ventana(ruta: str, nombre: str, comando: str | None = None,
                  session: str | None = None) -> str:
    """Abre una ventana nueva en la ruta del slot.

    La UI LANZA terminales, no las hospeda: sin PTY, sin rendering, sin resize.
    """
    args = ["new-window", "-P", "-F", "#{pane_id}", "-c", ruta, "-n", nombre]
    if session:
        args += ["-t", session]
    if comando:
        args.append(comando)
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
    """El `pane_title` crudo, con su glifo de estado. None si el panel murió."""
    validar_panel(pane_id)
    try:
        return _correr(["display-message", "-p", "-t", pane_id, "#{pane_title}"]).strip()
    except (TmuxNoDisponible, RuntimeError):
        return None


def capturar_panel(pane_id: str) -> str:
    """Lo que se ve en el panel ahora mismo. Cadena vacía si no se puede leer."""
    validar_panel(pane_id)
    try:
        return _correr(["capture-pane", "-p", "-t", pane_id])
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
    base = f"tmux new-window -c {shlex.quote(ruta)} -n {shlex.quote(nombre)}"
    return f"{base} {shlex.quote(comando)}" if comando else base
