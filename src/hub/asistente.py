"""El asistente.

Es **un proyecto más** con `claude --model sonnet` corriendo en una ventana de
tmux. Lo único distinto es cómo se ve: el hub renderiza su transcript como chat
en vez de como terminal.

Para qué existe, en palabras de quien lo pidió: *«en la ventana del proyecto en el
que estoy tengo 50 % de contexto, estoy con el prompt grande; para no ensuciarlo
mejor uso el asistente, que es general»*. Es una herramienta de **consulta**: el
trabajo pesado ocurre en el proyecto, las preguntas sobre el sistema ocurren aquí.

Por qué tmux y no `claude -p --resume`, que es lo que decía el diseño original y
**queda revocado** (decisión 68): así salen gratis tres cosas que había que
construir. El historial ya existe —es el transcript JSONL, que se lee y se pinta,
sin almacenar ni un mensaje—. Compactar y limpiar ya existen: son `/compact` y
`/clear`. Y la sesión está viva de verdad, sin gestionar session-ids.

🔴 **Aquí vive la única excepción a la decisión 22.** Escribir en un panel de
tmux está prohibido porque su estado se desconoce y unas teclas sueltas ejecutan
comandos reales. Este panel es distinto: lo crea el hub, sabe que dentro corre
`claude` y nada más, y cada escritura se valida contra su id (regla dura 15). La
excepción es **acotada a este panel**; nunca se extiende a uno de trabajo.
"""

from __future__ import annotations

import json
import shlex
import time
from pathlib import Path
from typing import Any

from . import config, tmux
from .models import Proyecto

# La sesión y la ventana del asistente tienen nombre fijo. Es lo que permite
# localizarlo escaneando tmux en vez de guardar su pane_id en la base: los ids
# no sobreviven a un reinicio del servidor, y la regla dura 1 exige que todo lo
# que viva en SQLite se pueda reconstruir escaneando.
SESION = "asistente"
VENTANA = "asistente"

# Sonnet por decisión suya: *"por ahora dejemos sonnet para el asistente, y vemos
# qué tal se comporta"* (decisión 74). El hub sólo filtra; el trabajo de resumir
# 14 MB de transcript llega ya reducido a ~100 KB.
#
# Va el id EXACTO y no el alias `sonnet` (decisión 91): el alias resolvió unas
# veces a Sonnet 4.6 y otras a Sonnet 5 en la misma tarde, y sus ventanas son de
# 200k y 1M. Con el alias, el porcentaje de contexto cambiaba de escala sin que
# nada lo dijera.
MODELO = "claude-sonnet-5"

# Tamaño de la ventana de contexto por modelo, para poder dar un porcentaje
# desde el primer mensaje, antes de que el statusline haya escrito nada.
#
# 🔴 Es el ÚLTIMO recurso, no la fuente: una tabla cableada envejece —salió un
# modelo nuevo y aquí no está—, así que lo medido siempre gana. El orden es
# statusline fresco → tamaño del último statusline del mismo modelo → esta
# tabla. Y si el modelo no está, no se inventa un porcentaje (regla dura 13).
#
# Verificado contra el statusline de una máquina real el 2026-08-28:
# `claude-sonnet-5` reportó `context_window_size: 1000000`.
VENTANA_POR_MODELO = {
    "claude-sonnet-5": 1_000_000,
    "claude-opus-5": 1_000_000,
    "claude-fable-5": 1_000_000,
    "claude-sonnet-4-6": 200_000,
    "claude-haiku-4-5": 200_000,
}

# Los mensajes que el hub se manda a sí mismo —hoy sólo el que pide las
# instrucciones de compactado— llevan este prefijo y no se pintan en el chat.
PREFIJO_INTERNO = "[hub:interno]"

# Estado del panel según el glifo del `pane_title`. Verificado muestreando tmux
# a 0,4 s: los paneles ociosos se quedan quietos en `✳` y el que trabaja cicla
# por el spinner braille (⠂⠐⠠…), que es todo el bloque U+2800–U+28FF.
GLIFO_LIBRE = "✳"

# Dónde deja el statusline del proyecto asistente su JSON de contexto.
ARCHIVO_CONTEXTO = config.HUB_HOME / "asistente-contexto.json"

# Pasado este tiempo el dato del statusline es de una sesión que ya no está
# viva. Mejor calcularlo del transcript que enseñar un número de ayer.
FRESCURA_CONTEXTO = 120


class AsistenteNoDisponible(RuntimeError):
    """No hay sesión del asistente y no se ha podido crear."""


class DestinoNoAutorizado(PermissionError):
    """🔴 Se intentó escribir en un panel que no es el del asistente (regla dura 15)."""


# --------------------------------------------------------------------------- #
# Dónde vive
# --------------------------------------------------------------------------- #


def proyecto_asistente(proyectos: list[Proyecto]) -> Proyecto | None:
    """El proyecto declarado con `tipo: asistente` en `projects.yml`.

    Se busca por tipo y no por una ruta cableada para que mover el directorio
    sea editar una línea de YAML y no tocar código (decisión 75).
    """
    for p in proyectos:
        if p.tipo == "asistente":
            return p
    return None


def localizar() -> str | None:
    """El pane_id del asistente, escaneando tmux. None si no está abierto.

    Escanear en vez de recordar es lo que hace que sobreviva a un reinicio del
    servidor de tmux, a un `kill-session` y a un reinicio del hub, sin guardar
    estado que pudiera quedar apuntando a un panel ajeno —que es exactamente el
    accidente que la regla dura 15 existe para impedir.
    """
    for panel in tmux.listar_paneles(incluir_espejos=True):
        if panel["session"] == SESION and panel["comando"] == "claude":
            return panel["pane_id"]
    return None


def asegurar_sesion(proyectos: list[Proyecto]) -> dict[str, Any]:
    """Devuelve el panel del asistente, creándolo si hace falta."""
    pane_id = localizar()
    if pane_id:
        return {"pane_id": pane_id, "session": SESION, "creada": False}

    proyecto = proyecto_asistente(proyectos)
    if not proyecto or not proyecto.asiento:
        raise AsistenteNoDisponible(
            "no hay ningún proyecto con `tipo: asistente` y asiento en projects.yml"
        )
    if not Path(proyecto.asiento).is_dir():
        raise AsistenteNoDisponible(f"el asiento del asistente no existe: {proyecto.asiento}")

    try:
        if not tmux.existe_sesion(SESION):
            # El comando va en el propio `new-session`, no en un `send-keys`
            # después: así `claude` ES el proceso de la ventana y nunca se teclea
            # nada en una shell (decisión 22).
            tmux.nueva_sesion(SESION, proyecto.asiento, VENTANA,
                              comando_de_arranque(proyecto), _entorno(proyecto))
        else:
            tmux.nueva_ventana(SESION, proyecto.asiento, VENTANA,
                               comando_de_arranque(proyecto), _entorno(proyecto))
    except (tmux.TmuxNoDisponible, RuntimeError) as exc:
        raise AsistenteNoDisponible(str(exc)) from exc

    pane_id = _esperar_panel()
    if not pane_id:
        raise AsistenteNoDisponible("la ventana se creó pero `claude` no llegó a arrancar")
    return {"pane_id": pane_id, "session": SESION, "creada": True,
            "listo": _esperar_listo(pane_id)}


def _entorno(proyecto: Proyecto) -> dict[str, str]:
    """El `bin/` del asistente por delante, para que `hub` esté siempre a mano.

    Sin esto, el comando que el asistente necesita **no existe para él**: lo
    lanza `hub-web`, que corre bajo systemd y no tiene `~/.local/bin` en el
    PATH. Ver `tmux.path_de_usuario`.
    """
    return {"PATH": tmux.path_de_usuario(str(Path(proyecto.asiento) / "bin"))}


def comando_de_arranque(proyecto: Proyecto | None = None) -> str:
    """`claude` con el PATH correcto delante.

    El PATH va **en el comando** y no sólo en el `-e` de tmux porque se comprobó
    que no basta: `tmux new-session -e PATH=…` deja bien la variable de la
    sesión —`show-environment` la enseña— pero el **primer panel** arranca con
    el entorno de quien lanzó el comando, que aquí es `hub-web` bajo systemd.
    Resultado: el asistente veía el venv del hub y no encontraba `hub`.

    `env` se sustituye a sí mismo por `claude`, así que `pane_current_command`
    sigue diciendo `claude` y `localizar()` no se entera de nada.
    """
    base = f"claude --model {shlex.quote(MODELO)}"
    if not proyecto or not proyecto.asiento:
        return base
    ruta = tmux.path_de_usuario(str(Path(proyecto.asiento) / "bin"))
    return f"env PATH={shlex.quote(ruta)} {base}"


# El chevron del cuadro de entrada de Claude Code. Es la señal de que la TUI ya
# acepta texto — y NO vale mirar `pane_current_command`, que es la trampa que
# se pagó aquí: medido, el proceso figura como `claude` a los 0,5 s pero el
# cuadro no aparece hasta los 2,0 s. Lo que se pegue en esos 1,5 s se lo traga
# la terminal sin dejar rastro: el mensaje simplemente no existe.
MARCA_LISTO = "❯"

# El cuadro de entrada va delimitado por dos reglas horizontales de guiones de
# caja, cada una del ancho del panel.
_GUION_CAJA = "─"
_ANCHO_MINIMO_REGLA = 10


def listo(pane_id: str) -> bool:
    """Si el cuadro de entrada de Claude Code ya está pintado y acepta texto."""
    return MARCA_LISTO in tmux.capturar_panel(pane_id)


# Marcas del diálogo de permisos de Claude Code. Salió probando de verdad: el
# asistente pidió `hub estado`, Claude Code abrió su cuadro de confirmación y el
# chat se quedó callado —ni ocupado ni contestando— porque desde la web no hay
# forma de pulsar «Yes». Sin detectarlo, el síntoma es que el asistente «no
# responde» y nada en la pantalla dice por qué.
_MARCAS_CONFIRMACION = (
    "Do you want to proceed?",
    "This command requires approval",
    "¿Quieres continuar?",
)


_LINEA_PREGUNTA = "Do you want to proceed?"
_OPCION = "opcion"

# Las dos únicas respuestas que el hub ofrece. El «2. Yes, and don't ask again»
# se deja fuera **a propósito**: amplía los permisos del asistente de forma
# permanente, y eso se decide editando su `.claude/settings.json` a conciencia,
# no pulsando un botón en un chat.
RESPUESTAS = {"si": "1", "no": "3"}


def confirmacion_pendiente(pane_id: str | None = None) -> dict[str, Any] | None:
    """Qué permiso está pidiendo Claude Code, si es que pide alguno.

    Salió probando de verdad: el asistente lanzó `hub estado` y, **en paralelo**,
    un `which hub || ls …` para asegurarse de que el binario existía. Lo primero
    estaba preautorizado; lo segundo abrió el cuadro de permisos. Desde la web no
    hay forma de pulsar «Yes», así que la conversación se quedó colgada: ni
    ocupada, ni respondiendo, sin nada en pantalla que dijera por qué.

    Ampliar la lista de permitidos hasta cubrir cualquier cosa que un modelo
    pueda intentar es imposible, y abrirlos del todo sería saltarse el trato.
    Así que se enseña la petición y **decide el usuario**, que es exactamente para lo
    que el cuadro existe.

    Se lee de la pantalla, así que un cambio de la TUI lo deja ciego. Falla hacia
    None a propósito: una falsa alarma sería peor que no avisar.
    """
    pane_id = pane_id or localizar()
    if not pane_id:
        return None

    pantalla = tmux.capturar_panel(pane_id)
    if not any(marca in pantalla for marca in _MARCAS_CONFIRMACION):
        return None

    lineas = pantalla.splitlines()
    corte = next((i for i, l in enumerate(lineas) if _LINEA_PREGUNTA in l), len(lineas))
    # Lo que pide va entre la última regla anterior a la pregunta y la pregunta.
    inicio = max((i for i, l in enumerate(lineas[:corte]) if _es_regla(l)), default=-1)
    peticion = [l.strip() for l in lineas[inicio + 1:corte] if l.strip()]

    return {"pane_id": pane_id, "peticion": peticion, "respuestas": sorted(RESPUESTAS)}


def esperando_confirmacion(pane_id: str | None = None) -> bool:
    pane_id = pane_id or localizar()
    if not pane_id:
        return False
    return any(m in tmux.capturar_panel(pane_id) for m in _MARCAS_CONFIRMACION)


def responder_confirmacion(respuesta: str, pane_id: str | None = None) -> dict[str, Any]:
    """Contesta el cuadro de permisos con «sí, esta vez» o «no».

    🔴 Pasa por `_autorizar` como cualquier otra escritura (regla dura 15): es
    una tecla en un panel de tmux, y el hecho de que sea un solo carácter no la
    hace menos peligrosa en un panel equivocado.
    """
    tecla = RESPUESTAS.get(respuesta)
    if not tecla:
        raise ValueError(f"respuesta no permitida: {respuesta}. Son: {sorted(RESPUESTAS)}")

    destino = _autorizar(pane_id)
    if not esperando_confirmacion(destino):
        # Sin cuadro abierto, ese «1» se escribiría en el prompt como un mensaje.
        return {"ok": False, "motivo": "sin-confirmacion-pendiente", "pane_id": destino}

    # Va como TECLA, no como pegado: se comprobó contra el cuadro real y un `1`
    # entregado por `paste-buffer -p` no selecciona nada —el bracketed paste es
    # para campos de texto y un menú espera una pulsación—. El dígito elige y
    # confirma de una vez; un Enter detrás despacharía además lo que hubiera
    # escrito debajo.
    tmux.tecla_en_panel(destino, tecla)
    return {"ok": True, "respuesta": respuesta, "pane_id": destino}


def _es_regla(linea: str) -> bool:
    limpia = linea.strip()
    return len(limpia) >= _ANCHO_MINIMO_REGLA and set(limpia) == {_GUION_CAJA}


def _cuadro(pane_id: str) -> str:
    """Lo que hay escrito en el cuadro de entrada ahora mismo.

    Sirve para comprobar si un mensaje se despachó de verdad: si sigue ahí, no
    salió. Es una lectura de la pantalla y por tanto frágil ante un rediseño de
    la TUI, pero falla de forma **explícita** —devuelve vacío, y `_despachar`
    trata «no veo el cuadro» como «no lo puedo confirmar», no como «se envió».

    Se busca **línea a línea**, no partiendo la pantalla por una cadena de
    guiones: la primera versión partía por `"─" * 10` y la regla real mide el
    ancho del panel —120 caracteres—, así que el `split` devolvía trozos vacíos
    entre medias y el cuadro salía siempre vacío. Efecto: todos los envíos se
    daban por despachados, incluido el que se quedó escrito en la pantalla.
    """
    lineas = tmux.capturar_panel(pane_id).splitlines()
    reglas = [i for i, l in enumerate(lineas) if _es_regla(l)]
    if len(reglas) < 2:
        return ""
    contenido = "\n".join(lineas[reglas[-2] + 1:reglas[-1]])
    return contenido.replace(MARCA_LISTO, "").strip()


def _despachar(pane_id: str, texto: str, intentos: int = 8, espera: float = 0.35) -> bool:
    """Pulsa Enter hasta que el mensaje sale del cuadro de entrada.

    🔴 Existe por dos fallos medidos, no por precaución.

    El primero: en el **arranque en frío** la TUI se traga el Enter. El texto se
    queda escrito en el cuadro, la API contesta `enviado: true` y nadie se entera
    de que nunca se envió. Ya caliente no vuelve a pasar —se probó con esperas de
    0 s a 0,3 s y las cuatro despacharon—, así que no sirve una espera fija.

    El segundo, al arreglar el primero: comprobar «¿sigue el texto en el cuadro?»
    **justo después de pegar** da que no, porque la TUI todavía no ha repintado.
    El envío se daba por bueno con el mensaje intacto en pantalla. Por eso el
    orden aquí es: esperar a **ver** el texto dentro, y sólo entonces despachar.

    Se reintenta sólo la tecla, nunca el texto: pegar dos veces mandaría el
    mensaje duplicado, que es peor que no mandarlo.
    """
    primera = (texto.strip().splitlines() or [""])[0][:40]

    entro = False
    for _ in range(intentos):
        if primera and primera in _cuadro(pane_id):
            entro = True
            break
        time.sleep(espera)

    if not entro:
        # No se ve el texto: o la TUI cambió de aspecto y `_cuadro` ya no la
        # entiende, o el pegado no llegó. Se pulsa Enter una vez por si acaso y
        # se dice que no se pudo confirmar, en vez de mentir con un `true`.
        tmux.enter_en_panel(pane_id)
        return False

    for _ in range(intentos):
        tmux.enter_en_panel(pane_id)
        time.sleep(espera)
        if primera not in _cuadro(pane_id):
            return True
    return False


def _esperar_panel(intentos: int = 20, espera: float = 0.25) -> str | None:
    """`claude` tarda un momento en aparecer como `pane_current_command`.

    Sin esta espera, `asegurar_sesion` devolvería None justo después de crear la
    ventana y la UI diría «no disponible» sobre un asistente que arrancó bien.
    """
    for _ in range(intentos):
        pane_id = localizar()
        if pane_id:
            return pane_id
        time.sleep(espera)
    return None


def _esperar_listo(pane_id: str, intentos: int = 40, espera: float = 0.25) -> bool:
    """Hasta 10 s a que la TUI acepte entrada. Medido: tarda ~2 s."""
    for _ in range(intentos):
        if listo(pane_id):
            return True
        time.sleep(espera)
    return False


# --------------------------------------------------------------------------- #
# Estado
# --------------------------------------------------------------------------- #


def ocupado(pane_id: str | None = None) -> bool | None:
    """Si el asistente está pensando. None si no se puede saber.

    None y False no son lo mismo: False autoriza a enviar, None dice que no hay
    panel del que leer. Colapsarlos haría que el chat enviara a un panel muerto.
    """
    pane_id = pane_id or localizar()
    if not pane_id:
        return None
    titulo = tmux.titulo_panel(pane_id)
    if titulo is None:
        return None
    return _es_spinner(titulo[:1])


def _es_spinner(glifo: str) -> bool:
    """El bloque braille de Unicode, que es donde vive el spinner de Claude Code."""
    return bool(glifo) and 0x2800 <= ord(glifo) <= 0x28FF


def contexto(ruta_transcript: Path | None = None) -> dict[str, Any] | None:
    """Cuánto ocupa la ventana de contexto del asistente.

    El usuario lo pidió explícitamente: *"es muy importante mostrar el tamaño de la
    ventana de contexto del asistente para saber cuándo mandar un compact o
    clear"*. Sin esto, compactar es adivinar.

    **Vía A, la exacta:** el JSON que Claude Code pasa al comando de statusline
    trae `context_window.used_percentage`, que es el mismo número que enseña
    `/context`. El proyecto asistente lo vuelca a un archivo y aquí se lee.

    **Vía B, el respaldo:** se calcula del último `usage` del transcript. No
    necesita configurar nada, pero no conoce el tamaño de la ventana, así que da
    tokens y no porcentaje. Se usa cuando A falta o está vieja.
    """
    exacto = _contexto_del_statusline()
    if exacto:
        return exacto

    if ruta_transcript is None:
        return None

    from . import transcripts

    calculado = transcripts.ultima_ocupacion(ruta_transcript)
    if not calculado:
        return None

    # El tamaño de la ventana **no caduca aunque el dato sí**: es una propiedad
    # del modelo, no de la sesión. Así que se reaprovecha el último que dejó el
    # statusline —sin exigirle frescura— y la vía B también puede dar un
    # porcentaje, que es lo que se mira para decidir cuándo compactar.
    #
    # Se exige que el modelo coincida: Sonnet 4.6 tiene 200.000 y Sonnet 5
    # 1.000.000, así que aplicar el tamaño del otro daría un porcentaje cinco
    # veces equivocado — peor que no dar ninguno (regla dura 13).
    ventana = tamano_de_ventana(calculado.get("modelo"))
    calculado["ventana"] = ventana
    calculado["porcentaje"] = (
        round(calculado["tokens"] / ventana * 100, 1) if ventana else None
    )
    return calculado


def tamano_de_ventana(modelo: str | None) -> int | None:
    """Cuántos tokens caben, para poder dar el dato en porcentaje.

    Dos fuentes, y **lo medido gana**: primero lo que reportó el statusline para
    ese mismo modelo —dato real de esta máquina, y sigue valiendo aunque el
    archivo esté viejo, porque el tamaño es propiedad del modelo y no de la
    sesión—; y sólo si no lo hay, la tabla cableada.

    Se exige que el modelo coincida: Sonnet 4.6 son 200k y Sonnet 5 un millón,
    así que aplicar el tamaño del otro daría un porcentaje cinco veces
    equivocado. Si no se reconoce el modelo, no se inventa (regla dura 13).
    """
    if not modelo:
        return None
    medido, modelo_medido = _ventana_del_statusline()
    if medido and modelo_medido == modelo:
        return medido
    return VENTANA_POR_MODELO.get(modelo)


def _ventana_del_statusline() -> tuple[int | None, str | None]:
    """Tamaño de ventana y modelo del último statusline, sin mirar su edad."""
    try:
        datos = json.loads(ARCHIVO_CONTEXTO.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None, None
    ventana = ((datos or {}).get("context_window") or {}).get("context_window_size")
    modelo = ((datos or {}).get("model") or {}).get("id")
    return (int(ventana) if ventana else None), modelo


def _contexto_del_statusline() -> dict[str, Any] | None:
    try:
        edad = time.time() - ARCHIVO_CONTEXTO.stat().st_mtime
        if edad > FRESCURA_CONTEXTO:
            return None
        datos = json.loads(ARCHIVO_CONTEXTO.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None

    ventana = (datos or {}).get("context_window") or {}
    uso = ventana.get("current_usage") or {}
    porcentaje = ventana.get("used_percentage")
    tokens = sum(
        int(uso.get(c) or 0)
        for c in ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")
    )
    if porcentaje is None and not tokens:
        return None

    return {
        "tokens": tokens or None,
        "porcentaje": round(float(porcentaje), 1) if porcentaje is not None else None,
        "ventana": ventana.get("context_window_size"),
        "modelo": (datos.get("model") or {}).get("id"),
        "origen": "statusline",
    }


# --------------------------------------------------------------------------- #
# Escritura — el único sitio del hub donde se escribe en un panel
# --------------------------------------------------------------------------- #


def _autorizar(pane_id: str | None) -> str:
    """🔴 Regla dura 15. El portero de la excepción a la decisión 22.

    Todo camino que escriba en tmux pasa por aquí. Un pane_id que no sea
    **exactamente** el del asistente vivo se rechaza, aunque venga de la UI: un
    panel de trabajo del usuario tiene estado desconocido, y pegarle texto seguido
    de un Enter ejecuta lo que sea que haya en su prompt.
    """
    real = localizar()
    if not real:
        raise AsistenteNoDisponible("el asistente no está abierto")
    if pane_id is not None and pane_id != real:
        raise DestinoNoAutorizado(
            f"{pane_id} no es el panel del asistente ({real}): el hub sólo escribe ahí"
        )
    return real


def enviar(texto: str, pane_id: str | None = None) -> dict[str, Any]:
    """Manda un mensaje al asistente. Multilínea llega como UN solo mensaje."""
    if not texto.strip():
        raise ValueError("un mensaje vacío no se envía")

    destino = _autorizar(pane_id)
    if not listo(destino):
        # Arrancando. Pegar aquí es perder el mensaje sin dejar rastro.
        return {"enviado": False, "motivo": "arrancando", "pane_id": destino}
    if ocupado(destino):
        # No se encola en una cola propia: Claude Code ya tiene la suya y
        # duplicarla haría que el hub creyera saber un orden que no controla.
        # Se dice que está ocupado y la UI decide.
        return {"enviado": False, "motivo": "ocupado", "pane_id": destino}

    # El Enter no va con el pegado: se pulsa después, cuando se ha visto que el
    # texto entró de verdad en el cuadro.
    tmux.pegar_en_panel(destino, texto, enter=False)
    despachado = _despachar(destino, texto)
    return {"enviado": True, "pane_id": destino, "interno": es_interno(texto),
            "despachado": despachado}


def enviar_comando(cmd: str, argumento: str = "", pane_id: str | None = None) -> dict[str, Any]:
    """Un comando de barra (`/compact`, `/clear`) con su argumento opcional.

    La lista es cerrada a propósito. `/` abre en Claude Code un menú con todo lo
    que sepa hacer —incluido salirse—, y un comando llegado por HTTP no debería
    poder elegir de esa lista entera.
    """
    if cmd not in COMANDOS_PERMITIDOS:
        raise ValueError(f"comando no permitido: {cmd}")
    linea = f"/{cmd} {argumento}".strip() if argumento else f"/{cmd}"
    destino = _autorizar(pane_id)
    tmux.pegar_en_panel(destino, linea, enter=False)
    return {"enviado": True, "comando": cmd, "pane_id": destino,
            "despachado": _despachar(destino, linea)}


COMANDOS_PERMITIDOS = frozenset({"compact", "clear"})


# --------------------------------------------------------------------------- #
# Mensajes internos
# --------------------------------------------------------------------------- #

# Lo que el hub le pide al asistente antes de compactar. Es el proceso que el usuario
# describió: *"que al darle compact, el propio chat genere un prompt que se
# adjuntará con el compact"*. Ni esta petición ni su respuesta se pintan.
PETICION_DE_COMPACTADO = (
    f"{PREFIJO_INTERNO} Vas a compactar tu propia conversación. Escribe SÓLO las "
    "instrucciones de compactado: qué conservar textualmente, qué se puede "
    "resumir y qué se puede tirar. Sin preámbulo y sin explicar qué vas a hacer; "
    "tu respuesta se pasa tal cual como argumento de /compact."
)


def es_interno(texto: str) -> bool:
    return texto.lstrip().startswith(PREFIJO_INTERNO)


def ocultar_internos(mensajes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Quita del chat los mensajes que el hub se manda a sí mismo y sus respuestas.

    Se marca por prefijo en el texto y no por una clave guardada porque el uuid
    lo asigna Claude Code, no el hub: no hay nada limpio que correlacionar. Es
    frágil a propósito, y su peor fallo es **cosmético** —aparece un mensaje que
    debía estar oculto—, nunca pérdida de datos. Si llega a molestar, la
    alternativa es una tabla que correlacione por texto y timestamp.
    """
    visibles: list[dict[str, Any]] = []
    saltar_respuesta = False
    for mensaje in mensajes:
        if mensaje.get("rol") == "user":
            if es_interno(mensaje.get("texto") or ""):
                saltar_respuesta = True
                continue
            saltar_respuesta = False
        elif saltar_respuesta:
            saltar_respuesta = False
            continue
        visibles.append(mensaje)
    return visibles


def extraer_instrucciones(mensajes: list[dict[str, Any]]) -> str | None:
    """La respuesta del asistente a la petición de compactado, si ya llegó."""
    for i, mensaje in enumerate(mensajes):
        if mensaje.get("rol") == "user" and es_interno(mensaje.get("texto") or ""):
            for siguiente in mensajes[i + 1:]:
                if siguiente.get("rol") == "assistant" and (siguiente.get("texto") or "").strip():
                    return siguiente["texto"].strip()
    return None


# --------------------------------------------------------------------------- #
# Escritura acotada — sólo dentro del hub
# --------------------------------------------------------------------------- #
#
# La escritura del asistente se separa por DESTINO, no por permiso (decisión 69):
#
#     tus proyectos → sólo lectura. Nunca escribe, nunca ejecuta.
#     el hub        → escribe: notas y slots.
#     borrar        → nunca. Sigue siendo tuyo (principio 9).
#
# Es lo que permite decir «sólo lectura» sin que el asistente sea inútil, y
# encaja con el principio 1: el hub no toca proyectos ajenos. Aquí no hay ninguna
# función de borrado, y añadir una no es «una más»: es cambiar el trato.


def escribir_nota(con, texto: str, slot_id: int | None = None) -> dict[str, Any]:
    """Deja una nota en un slot. Sin `slot_id`, resuelve por el panel enfocado.

    El usuario: *«si no especifico, que detecte la ruta y la ventana sobre la que estoy
    al momento de escribir»*.

    Cuando el panel enfocado no tiene slot, esto **no falla**: devuelve la
    sugerencia de crearlo con los datos ya resueltos, para que el asistente
    ofrezca crearlo en vez de contestar un error. Crear el slot sigue siendo una
    acción aparte y consciente — nombrar slots es lo único del sistema que no
    puede construirse solo.

    La respuesta dice **siempre en qué slot se escribió**. El panel enfocado es
    la mejor señal disponible, pero es una inferencia: si acierta el 95 % de las
    veces y no se dice cuál, el 5 % restante es una nota perdida en otro sitio.
    """
    from . import api

    texto = (texto or "").strip()
    if not texto:
        raise ValueError("una nota vacía no se guarda")

    if slot_id is None:
        resuelto = _slot_del_panel_enfocado(con)
        if not resuelto["slot_id"]:
            return {"ok": False, "motivo": "sin-slot", **resuelto}
        slot_id = resuelto["slot_id"]

    slot = api.obtener_slot(con, slot_id)
    if not slot:
        return {"ok": False, "motivo": "slot-desconocido", "slot_id": slot_id}

    previo = slot["nota"] or ""
    api.guardar_nota(con, slot_id, f"{previo}\n\n{texto}".strip() if previo else texto)
    con.commit()
    return {
        "ok": True,
        "slot_id": slot_id,
        "slot": slot["nombre"],
        "proyecto_id": slot["proyecto_id"],
        "anexada": bool(previo),
    }


def _slot_del_panel_enfocado(con) -> dict[str, Any]:
    """Dónde está trabajando el usuario ahora, traducido a slot si lo tiene."""
    from . import api

    # La sesión del asistente se excluye: una nota sobre en qué se está
    # trabajando no puede caer sobre el propio asistente.
    pane_id = tmux.panel_enfocado(excluir={SESION})
    if not pane_id:
        return {"slot_id": None, "pane_id": None, "sugerencia": None}

    for panel in api.paneles_abiertos(con):
        if panel["pane_id"] != pane_id:
            continue
        if panel["slot_id"]:
            return {"slot_id": panel["slot_id"], "pane_id": pane_id, "sugerencia": None}
        return {
            "slot_id": None,
            "pane_id": pane_id,
            "sugerencia": {
                "crear_slot": {
                    "proyecto_id": panel["proyecto_id"],
                    "nombre": panel["etiqueta"] or Path(panel["cwd"]).name,
                    "ruta": panel["cwd"],
                }
            },
        }
    return {"slot_id": None, "pane_id": pane_id, "sugerencia": None}


def crear_slot(con, proyecto_id: str, nombre: str, ruta: str | None = None) -> dict[str, Any]:
    """Crea un slot en el hub. Es lo único que el asistente crea, y no borra nada."""
    from . import api, slots

    nombre = (nombre or "").strip()
    if not nombre:
        raise ValueError("un slot sin nombre no sirve: el nombre ES la línea de trabajo")
    if not api.obtener_proyecto(con, proyecto_id):
        raise ValueError(f"proyecto desconocido: {proyecto_id}")

    slot_id = slots.crear(con, proyecto_id, nombre, ruta)
    con.commit()
    return {"ok": True, "slot_id": slot_id, "nombre": nombre, "proyecto_id": proyecto_id}


# --------------------------------------------------------------------------- #
# El transcript vivo
# --------------------------------------------------------------------------- #


def transcript_vivo(proyectos: list[Proyecto]) -> Path | None:
    """El JSONL de la sesión del asistente que se está escribiendo ahora.

    El más reciente por mtime: `/clear` abre un archivo nuevo y deja el viejo
    huérfano, así que el criterio tiene que ser cuál se está escribiendo, no cuál
    existe.
    """
    from . import transcripts

    proyecto = proyecto_asistente(proyectos)
    if not proyecto:
        return None

    candidatos: list[Path] = []
    for directorio in transcripts.directorios_de(proyecto):
        candidatos.extend(transcripts.jsonl_de(directorio))
    if not candidatos:
        return None
    return max(candidatos, key=transcripts.mtime)


def conversacion(
    proyectos: list[Proyecto], desde_uuid: str | None = None
) -> dict[str, Any]:
    """Lo que el chat necesita para pintarse: mensajes, si está ocupado y contexto."""
    from . import transcripts

    ruta = transcript_vivo(proyectos)
    pane_id = localizar()

    mensajes: list[dict[str, Any]] = []
    sesion_id = None
    if ruta:
        crudo = transcripts.esqueleto(ruta, desde_uuid=desde_uuid)
        mensajes = ocultar_internos(crudo["mensajes"])
        sesion_id = crudo["id"]

    return {
        "abierto": bool(pane_id),
        "pane_id": pane_id,
        "session": SESION if pane_id else None,
        "sesion_id": sesion_id,
        "ocupado": ocupado(pane_id),
        # Sin esto, un cuadro de permisos deja al chat callado sin decir por qué.
        "confirmacion": confirmacion_pendiente(pane_id) if pane_id else None,
        "contexto": contexto(ruta),
        "mensajes": mensajes,
    }
