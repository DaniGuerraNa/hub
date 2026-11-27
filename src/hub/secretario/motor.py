"""Cómo se llama al modelo, detrás de una sola costura (decisiones 301 y 328).

Todo el secretario llama a `motor.llamar(...)` y no sabe con qué se contesta.
Quién contesta lo dice `motor:` en `secretario.yml`; por omisión, y hoy el
único, `suscripcion`.

**`suscripcion`**: `claude -p` con la suscripción del dueño (P1, 2026-10-23).
Es la forma de usarla sin una terminal delante: sin raspar una TUI —lo frágil
del asistente y del orquestador—, con salida JSON, con sesiones que se retoman
y con las herramientas por MCP.

🔴 **Sin nada de lo que trae el `claude` interactivo del dueño:**

- `--tools ""`: ni Bash, ni Read, ni Edit. El secretario no tiene shell; lo
  que puede hacer es el catálogo (7.3), y lo que no está ahí no lo improvisa.
- `--setting-sources ""` y `--strict-mcp-config`: ni sus hooks, ni sus
  permisos, ni sus otros servidores MCP.
- `--permission-mode dontAsk`: lo no permitido se deniega y sigue, en vez de
  quedarse esperando un «sí» que nadie va a dar (medido en encargos, 240).
- Se corre en una carpeta vacía propia: ningún `CLAUDE.md` se cuela.

`--bare` sería lo natural y **no sirve**: no lee el llavero, y sin él no hay
suscripción (medido el 2026-10-24: `terminal_reason: api_error`).

**Buscar y leer en la web, sólo en un trabajo aparte** (`nativas`, decisión
385): `nativas=("WebSearch", "WebFetch")` cambia `--tools ""` por esas dos y
las permite con `--allowedTools` (con `dontAsk` y sin permitirlas, se
deniegan: medido el 7-nov). Nada fuera de `NATIVAS_PERMITIDAS`, y nunca junto
al MCP del secretario: lo leído en una página no puede accionar nada.
`WebFetch` pide desde esta máquina: se le niega la propia y la red privada por
nombre (`NO_LEER`), que es una red y no una garantía. Con
`tope_usd` va `--max-budget-usd`; se mira entre turno y turno del modelo, así
que el último lo puede pasar (medido: tope 0,01, gastó 0,018-0,028), y entonces
lanza `TopeAgotado`. La conversación no lleva nunca `nativas` (390).

**La conversación deja el proceso abierto** (`abierta=True`, decisión 328):
arrancar `claude` y su servidor MCP en cada turno se paga cada vez. Medido el
2-nov con sonnet y el MCP del secretario: 3,2-3,5 s por turno arrancando, y
2,2-3,0 s con el proceso ya abierto (`--input-format stream-json`). Es un
segundo por turno, no más; en el modo voz se nota. El proceso es de un hilo:
se cierra al cerrarse el hilo, a los `ABIERTO_MAX_S` sin usarse, o si cambia el
modelo; si muere a mitad, ese turno se repite por el camino de siempre.

**Pasar a la API** es escribir otro `Motor` y ponerlo en `MOTORES`; nadie más
cambia. Lo que tendría que hacer, porque `claude -p` lo hace hoy por él:
llevar el bucle de herramientas (las mismas de `herramientas.todas()`, que son
las que sirve el MCP, pasándoles el turno como lo hace `mcp.py`), guardar el
historial de cada `sesion` para poder retomarla, y respetar `esquema`
(salida estructurada) y `persistir`. La llave, como todas, fuera de la base
(regla dura 5).

**Un motor caído no es un pedido malo** (C-0307). Lo que falla por el motor
y no por lo que se le pidió lanza `MotorNoDisponible` (con su `causa`), y quien
reintenta solo —el triaje con un lote, el cierre con un hilo— no lo cuenta
contra el pedido: espera (`pausar`, `en_pausa`, `reanudar`; el retroceso es
`RETROCESO_S`) y deja una línea por racha en la bitácora. Sólo se clasifica lo
medido; lo demás llega como `MotorCaido` corriente, y por eso antes de rendirse
con un pedido se sondea si el motor contesta (`responde`, `rendirse`). La
conversación no se pausa: él está delante y se intenta siempre.
"""

from __future__ import annotations

import json
import math
import os
import queue
import shutil
import signal
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import uuid
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from .. import config, tmux
from ..reloj import a_local
from . import memoria

TOPE_SEGUNDOS = 600
#: Un proceso abierto sin turnos se cierra: cada uno ocupa memoria (claude y su MCP).
ABIERTO_MAX_S = 600
#: Cada cuánto, como mucho, se pasa el texto a medio escribir (C-0155): más a
#: menudo sólo escribiría más en la memoria sin que se oiga antes.
CADA_TROZO_S = 0.25
#: Sin una sola línea del proceso abierto en este tiempo, se da por colgado y
#: el turno se repite por el camino de siempre. Medido el 5-nov: una llamada se
#: quedó 2 min 8 s muda tras una herramienta (C-0170: los «6 min» que se dijeron
#: eran la edad del proceso), y con el tope de 10 min los mensajes que llegaban
#: detrás esperaban todos; matarla y repetirla contestó en 6,7 s.
#: Con trozos llega algo cada pocos segundos mientras escribe; lo que más calla
#: es una herramienta lenta (buscar en una carpeta grande).
SIN_NOTICIAS_S = 120
#: El vigilante de red del propio `claude` (C-0170). Lo del 5-nov fue una
#: llamada a la API que no llegó a completarse, y el CLI espera por omisión
#: 180-300 s sin un byte antes de cortarla y reintentar: más que
#: `SIN_NOTICIAS_S`, así que lo matábamos antes de que actuara. Con 45 s corta
#: y reintenta él, dentro del mismo proceso y sin repetir el turno: el
#: reintento que el 5-nov habría contestado llega a los 45 s y no a los 120.
#: Medido con una API falsa (2.1.280): intentos a los 0, 45 y 90 s, sin una
#: línea entre medias, y un `result` con `terminal_reason: api_error` a los
#: 135 s; si la red sigue caída, `SIN_NOTICIAS_S` lo mata antes y el turno se
#: repite igual. Una respuesta sana no calla 45 s: mientras piensa, la API
#: manda `ping`. El primer byte tarda más con un contexto enorme, y por eso no
#: se baja de aquí.
CORTES_DE_RED = {"CLAUDE_BYTE_STREAM_IDLE_TIMEOUT_MS": "45000", "CLAUDE_STREAM_FIRST_BYTE_TIMEOUT_MS": "45000"}
#: Lo último que dijo un turno que hubo que matar, al journal: el 5-nov hizo
#: falta el transcript para saber dónde se había parado (C-0170).
LINEAS_GUARDADAS = 30
#: Las herramientas del secretario llegan por su MCP con este prefijo; quien
#: escucha `al_evento` recibe el nombre del catálogo, sin él.
PREFIJO_MCP = "mcp__secretario__"
#: Las únicas herramientas propias de `claude` que se dejan pedir (decisión
#: 385): buscar y leer lo público. Ni Bash, ni Read, ni Edit: el secretario no
#: tiene shell, y lo que puede hacer es su catálogo (7.3).
NATIVAS_PERMITIDAS = ("WebSearch", "WebFetch")
#: Adónde no va `WebFetch` (385): esta máquina, la red de casa y la privada.
#: Medido el 7-nov: pide desde aquí —llegó a un servidor en 127.0.0.1, también
#: por `127.0.0.1.nip.io`— y `--disallowedTools "WebFetch(domain:…)"` lo
#: corta, también con `*.` delante; con `*` detrás (`192.168.*`) no, con un
#: `*` por octeto sí, según su comparador. Es una red, no una garantía: un
#: nombre que no está aquí y apunta a una IP privada pasa. Lo acota que pide
#: siempre por https (un servicio sólo http no contesta) y que la pregunta no
#: puede llevar direcciones (`investigar._DIRECCION`).
NO_LEER = ("localhost", "*.localhost", "127.0.0.1", "0.0.0.0", "[::1]", "*.local", "*.lan", "*.internal",
           "*.home.arpa", "*.ts.net", "*.nip.io", "*.sslip.io", "localtest.me", "*.localtest.me",
           "lvh.me", "*.lvh.me", "*.traefik.me", "169.254.169.254",
           # Un `*` por octeto: así sí casa el comparador de Claude Code 2.1.280
           # (leído en su binario en la revisión cruzada del 7-nov; sin medir
           # contra `claude`). La red de casa, la privada y la del tailnet.
           "127.*.*.*", "10.*.*.*", "192.168.*.*", "169.254.*.*",
           *(f"172.{n}.*.*" for n in range(16, 32)), *(f"100.{n}.*.*" for n in range(64, 128)))
#: Lo que pesa, como mucho, una imagen que va al modelo (decisión 383). La API
#: admite 5 MB por imagen ya en base64, que engorda un tercio: 3,5 MB deja
#: margen. Una más grande se reduce con ffmpeg; sin ffmpeg, se dice. Claude
#: Code 2.1.280 ya reduce lo que recibe (medido el 7-nov con un PNG de 20 MB):
#: esto es la guarda para cuando no, y no pasa decenas de MB por la tubería.
TOPE_IMAGEN = 3_500_000
#: El lado largo al reducir: más no lo ve el modelo, que reduce solo lo que
#: pasa de 1568 px.
LADO_REDUCIDO = 1568
#: Un PDF no se reduce, y la sesión lo vuelve a mandar en cada turno del hilo:
#: uno mayor va sólo por su ruta. Prudencia, no medida: la API corta una
#: petición de más de 32 MB.
TOPE_PDF = 10_000_000
#: Lo que va al modelo en un mismo mensaje, sumado: diez imágenes en el tope
#: serían 47 MB en base64. Lo que no cabe va sólo por su ruta. Prudencia, no
#: medida: Claude Code 2.1.280 aguantó 34 MB en dos turnos porque reduce él.
TOPE_MENSAJE = 15_000_000
#: El demuxer de ffmpeg se fija por la extensión: adivinarlo por el contenido
#: dejaría que una lista HLS con forma de `.png` le hiciera leer otro archivo.
_DEMUXER = {".gif": "gif"}


class MotorCaido(RuntimeError):
    """El modelo no contestó o contestó con error."""


#: Por qué el motor no está disponible (C-0307). 🔴 Hoy sólo se dan las dos
#: medidas: `no_arranca` (el `OSError` al lanzar `claude`) y `api` (un `result`
#: con `terminal_reason: api_error`, C-0170: también es lo que da la red
#: cortada). `sin_sesion`, `cuota` y `red` están para cuando se mida su
#: `result`, que no se ha visto nunca: mientras, llegan como `api` o como un
#: `MotorCaido` corriente, y las cubre la sonda (`responde`). No se adivinan.
CAUSAS = ("no_arranca", "sin_sesion", "cuota", "red", "api")


class MotorNoDisponible(MotorCaido):
    """El motor no está, y no es por lo que se le pidió (C-0307): `claude` no
    arranca, la API da error agotados sus reintentos, o el `motor:` de
    `secretario.yml` no existe. Quien reintenta solo no lo cuenta contra el
    pedido (`rendirse`).

    `causa`: una de `CAUSAS`, o None si el mensaje ya dice en llano qué
    arreglar. `hasta`: la hora a la que vuelve, si la CLI la diera (la cuota);
    hoy nadie la rellena.

    🔴 No lo es el tope de tiempo (`el modelo no contestó en…`): un pedido que
    siempre lo agota tiene que poder apartarse, o dejaría sordo a quien lo
    reintenta (decisión 376). Tampoco `TopeAgotado`, `Cancelada`, una imagen
    que no entra ni una salida sin JSON: son del pedido."""

    def __init__(self, mensaje: str, causa: str | None = "api", hasta: str | None = None):
        super().__init__(mensaje)
        self.causa, self.hasta = causa, hasta


class TopeAgotado(MotorCaido):
    """Llegó a su `tope_usd` antes de acabar. `coste`: lo que llevaba gastado."""

    def __init__(self, mensaje: str, coste: float = 0.0):
        super().__init__(mensaje)
        self.coste = coste


class Cancelada(MotorCaido):
    """Se paró a mitad porque `parar()` lo pidió (C-0241). Lo gastado hasta
    ahí no se sabe: el proceso muere sin dar su `result`, o lo da sin gasto
    (el «interrupt» del proceso abierto, C-0506).

    `sigue`: en el proceso abierto, si siguió vivo tras parar (C-0506). Sólo
    entonces se sabe que su sesión existe para retomarla."""

    sigue = False


#: Cada cuánto se pregunta a `parar` si hay que cortar (C-0241). Un segundo
#: basta para quien acaba de pedir «para»; más a menudo sólo leería más.
CADA_PARAR_S = 1.0
#: En el proceso abierto (C-0506), lo más que se espera a que acabe la
#: herramienta que está en vuelo antes de pedir que pare: cortada, su
#: servidor puede acabarla igual —una nota, una solicitud— y el modelo
#: creería que no la hizo. Pasado esto, se corta aunque no haya acabado.
ESPERA_HERRAMIENTA_S = 30.0
#: Lo más que se espera, pedido el «interrupt», a que el turno se cierre con
#: su `result`. Medido el 27-nov (2.1.322): 10 ms escribiendo y 10 ms con
#: una herramienta en vuelo. Si no llega, se mata el grupo del proceso.
ESPERA_INTERRUMPIR_S = 10.0
#: Cómo cierra el CLI un turno interrumpido (medido el 27-nov, 2.1.322):
#: `is_error` con `subtype: error_during_execution` y una de éstas.
CORTADO_POR_INTERRUMPIR = ("aborted_streaming", "aborted_tools")


def _pide(parar: Callable[[], bool]) -> bool:
    """Si `parar` dice que sí; una lectura que falla no corta (C-0241)."""
    try:
        return bool(parar())
    except Exception:  # noqa: BLE001 — cancelar es una petición, no una garantía
        return False


def _matar_grupo(p: subprocess.Popen) -> None:
    """Mata el grupo de `p` (nace con `process_group=0`), y si no es su
    grupo o ya no existe, al menos a él. Por su id, nunca por un patrón."""
    try:
        os.killpg(p.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        # Ya acabó (y su grupo con él), o no es su propio grupo: al menos él.
        try:
            p.kill()
        except ProcessLookupError:
            pass


class _Vigia:
    """Mata el proceso al pasar `tope_s` (sin él, `TOPE_SEGUNDOS`), o antes si
    `parar()` lo pide.

    Las dos razones para cortar una llamada en un solo sitio (C-0241): antes
    cada camino tenía la suya (`timeout=` en dos `subprocess.run` y un
    `Timer` en `_suelta`). `parar` se llama desde este hilo, no desde el de
    quien llamó: si lee una base, con su propia conexión. Si falla, no corta:
    cancelar es una petición, no una garantía, y quien lo pidió lo comprueba.

    🔴 Mata el GRUPO del proceso (nace con `process_group=0`): matar sólo a
    `claude` dejaba a su servidor MCP —que hereda las tuberías— con ellas
    abiertas, y quien lee esperaba a que acabara él (revisión de C-0241,
    medido con un nieto: 12 s en vez de 1). El grupo es el de ese `claude` y
    nada más: se mata por su id, no por un patrón. Un grupo propio no es una
    sesión nueva ni saca del cgroup: al parar el servicio muere con él, que es
    lo contrario de `procesos.desasir` (344)."""

    #: El de esta llamada (SEC-23); sin él, `TOPE_SEGUNDOS`.
    tope_s: float | None = None

    def __init__(self, p: subprocess.Popen, parar: Callable[[], bool] | None = None,
                 tope_s: float | None = None):
        self.p, self.parar, self.motivo, self.tope_s = p, parar, "", tope_s
        self._fin = threading.Event()
        self._t0 = time.monotonic()
        threading.Thread(target=self._mirar, daemon=True).start()

    @property
    def tope(self) -> float:
        # Se lee al mirar y no al importar: quien cambia `TOPE_SEGUNDOS` (un test) lo ve.
        return TOPE_SEGUNDOS if self.tope_s is None else self.tope_s

    def _mirar(self) -> None:
        while not self._fin.wait(CADA_PARAR_S if self.parar else self.tope):
            if time.monotonic() - self._t0 >= self.tope:
                self.motivo = "tope"
            elif self.parar is not None:
                try:
                    if self.parar():
                        self.motivo = "parar"
                except Exception:  # noqa: BLE001 — una lectura que falla no corta la llamada
                    pass
            if self.motivo:
                self.matar()
                return

    def matar(self) -> None:
        _matar_grupo(self.p)

    def cerrar(self) -> None:
        self._fin.set()

    def comprobar(self) -> None:
        """Lanza lo que corresponda si fue el vigía quien la cortó. Uno que
        acabó solo justo cuando el vigía decidía cortarlo no cuenta: su
        respuesta está entera (un `kill` a un proceso ya muerto no hace nada,
        y su código no es el de una señal)."""
        if not self.motivo or self.p.returncode is None or self.p.returncode >= 0:
            return
        if self.motivo == "parar":
            raise Cancelada("se canceló a mitad")
        if self.motivo == "tope":
            raise MotorCaido(f"el modelo no contestó en {self.tope:g} s")


def _correr(linea: list[str], entrada: str, entorno: dict, parar: Callable[[], bool] | None = None,
            tope_s: float | None = None) -> subprocess.CompletedProcess:
    """`subprocess.run` con su vigía: lo que acaba, entero; lo que corta el
    vigía, con su excepción."""
    try:
        p = subprocess.Popen(linea, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             text=True, cwd=_trabajo(), env=entorno, process_group=0)
    except OSError as exc:
        raise MotorNoDisponible(f"no se pudo arrancar claude: {exc}", "no_arranca") from exc
    vigia = _Vigia(p, parar, tope_s)
    try:
        salida, err = p.communicate(entrada)
    except BaseException:
        # Como `subprocess.run`: lo que se interrumpe no se queda vivo y sin vigía.
        vigia.matar()
        raise
    finally:
        vigia.cerrar()
    vigia.comprobar()
    return subprocess.CompletedProcess(linea, p.returncode, salida, err)


def _nativas(nativas) -> tuple[str, ...]:
    """Las nativas pedidas, comprobadas: una que no está en la lista no se
    ignora, se niega (decisión 385). Un texto suelto también, que iterado
    serían letras."""
    if isinstance(nativas, str):
        raise ValueError("`nativas` es una tupla de nombres, no un texto")
    nativas = tuple(dict.fromkeys(nativas or ()))
    fuera = [n for n in nativas if n not in NATIVAS_PERMITIDAS]
    if fuera:
        raise ValueError(f"herramientas de claude no permitidas: {fuera}; sólo {list(NATIVAS_PERMITIDAS)} (385)")
    return nativas


def _tope_s(tope_s) -> float | None:
    """El tope de tiempo de una llamada (SEC-23), comprobado como `_tope`."""
    if tope_s is None:
        return None
    tope = float(tope_s)
    if not math.isfinite(tope) or tope <= 0:
        raise ValueError(f"tope_s tiene que ser un número de segundos positivo, no {tope_s!r}")
    return tope


def _tope(tope_usd) -> float | None:
    if tope_usd is None:
        return None
    tope = float(tope_usd)
    if not math.isfinite(tope) or tope <= 0:
        raise ValueError(f"tope_usd tiene que ser un importe positivo, no {tope_usd!r}")
    return tope


#: Lo que lleva delante un turno que se repite tras un corte (C-0185).
RETOMAR = ("(Tu respuesta a este mensaje se cortó a mitad. Si ya hiciste algo con tus herramientas —una "
           "tarjeta, una nota, un compromiso, un aviso, un encargo—, ya está hecho: no lo repitas. "
           "Termina de contestar. El mensaje era:)\n\n")


@dataclass
class Respuesta:
    texto: str
    sesion: str
    estructurada: dict | None
    segundos: float
    coste: float
    modelo: str
    entrada: int = 0
    salida: int = 0
    #: Segundos de un intento que hubo que tirar antes de esta respuesta (el
    #: proceso abierto se murió, calló o dio error de la API, C-0170). Se
    #: apuntan como una llamada fallida aparte: sin eso, el tiempo se perdía.
    perdidos: float = 0.0


class Motor:
    """El contrato. `llamar` contesta o lanza `MotorCaido`; lo demás es opcional.

    `al_trozo(texto)` también es opcional, y nadie depende de él: quien sabe
    dar la respuesta por trozos lo llama con el texto ACUMULADO de lo que va
    escribiendo (todos sus mensajes del turno, no sólo el último); quien no,
    lo ignora y la respuesta llega entera en `Respuesta`, como siempre. Cambiar
    de motor no cambia nada para quien consume (C-0155).

    `al_evento(evento)`, igual de opcional (C-0166, decisión 358): qué está
    haciendo el modelo mientras contesta, para enseñarlo. Uno de
    `{"tipo": "pensando"}`, `{"tipo": "herramienta", "nombre", "args"}` (el
    nombre del catálogo, sin prefijo; puede llegar dos veces, al empezar con
    `args` vacío y con los argumentos enteros), `{"tipo": "fin_herramienta"}`
    y `{"tipo": "reintento"}`: lo escrito hasta ahí se tira y la respuesta
    vuelve a empezar (C-0185). Quien no reintenta nunca lo manda, y quien
    escucha no puede depender de él.
    Es adorno: un fallo de quien escucha no tumba el turno."""

    id = ""
    nombre = ""

    def disponible(self) -> str | None:
        return None

    def llamar(self, prompt: str, *, modelo: str, sistema: str | None, sesion: str | None, nueva: bool,
               herramientas: bool, esquema: dict | None, esfuerzo: str | None, entorno_extra: dict,
               persistir: bool, abierta: bool, imagenes: list | None = None,
               al_trozo: Callable[[str], None] | None = None,
               al_evento: Callable[[dict], None] | None = None,
               nativas: tuple[str, ...] = (), tope_usd: float | None = None) -> Respuesta:
        raise NotImplementedError

    def soltar(self, sesion: str | None = None) -> None:
        """Cierra lo que tenga abierto de esa sesión (o de todas)."""

    def podar(self) -> None:
        """Cierra lo abierto que lleve demasiado sin usarse."""


# ───────────────────────────── la suscripción ─────────────────────────────


def _trabajo() -> Path:
    d = memoria.carpeta() / "trabajo"
    d.mkdir(exist_ok=True)
    return d


def _claude(entorno: dict) -> str:
    # Sólo el binario: el `--model` lo pone `llamar`, siempre, y del enrutador.
    return shutil.which("claude", path=entorno["PATH"]) or "claude"  # el --model va en _linea()


def mcp_config(entorno: dict[str, str]) -> str:
    """El servidor de herramientas, con el mismo intérprete que corre el secretario.

    En línea y con su `env` explícito: el hilo que se contesta viaja así hasta
    las herramientas, y no se depende de si `claude` pasa o no su entorno a los
    servidores. El turno no: en un proceso abierto cambia y el entorno no, así
    que va en la memoria (`turno_en_curso:<hilo>`).
    """
    return json.dumps({"mcpServers": {"secretario": {
        "command": sys.executable, "args": ["-m", "hub.secretario.mcp"], "env": entorno}}})


class _Actividad:
    """Las líneas de stream-json de un turno, dichas como eventos (C-0166).

    Con `--include-partial-messages` llegan los bloques según empiezan
    (`content_block_start`) y los argumentos de una herramienta a trozos
    (`input_json_delta`) hasta su `content_block_stop`; sin él (el camino de
    un solo uso), sólo los mensajes enteros. Se atienden los dos, y una
    herramienta ya avisada con sus argumentos no se repite por su mensaje
    entero. El fin de una herramienta es el `user` que trae su resultado."""

    def __init__(self, al_evento: Callable[[dict], None]):
        self.al_evento = al_evento
        self.bloques: dict = {}
        self.avisadas: set = set()
        self.parciales = False

    def _avisar(self, evento: dict) -> None:
        try:
            self.al_evento(evento)
        except Exception:  # noqa: BLE001 — el personaje es adorno: no tumba el turno
            pass

    def _herramienta(self, bloque_id, nombre, args) -> None:
        if bloque_id:
            self.avisadas.add(bloque_id)
        nombre = str(nombre or "")
        nombre = nombre[len(PREFIJO_MCP):] if nombre.startswith(PREFIJO_MCP) else nombre
        self._avisar({"tipo": "herramienta", "nombre": nombre, "args": args if isinstance(args, dict) else {}})

    def linea(self, d: dict) -> None:
        tipo = d.get("type")
        if tipo == "stream_event":
            self.parciales = True
            ev = d.get("event") or {}
            clase, indice = ev.get("type"), ev.get("index")
            if clase == "content_block_start":
                b = ev.get("content_block") or {}
                if b.get("type") == "thinking":
                    self._avisar({"tipo": "pensando"})
                elif b.get("type") == "tool_use":
                    self.bloques[indice] = {"id": b.get("id"), "nombre": b.get("name"), "json": ""}
                    self._herramienta(None, b.get("name"), {})
            elif clase == "content_block_delta":
                delta = ev.get("delta") or {}
                if delta.get("type") == "input_json_delta" and indice in self.bloques:
                    self.bloques[indice]["json"] += delta.get("partial_json") or ""
            elif clase == "content_block_stop" and indice in self.bloques:
                # Medido el 6-nov (2.1.280): el mensaje entero con los
                # argumentos llega ANTES que este stop; si ya se avisó, sobra.
                b = self.bloques.pop(indice)
                if b["id"] in self.avisadas:
                    return
                try:
                    args = json.loads(b["json"] or "{}")
                except ValueError:
                    args = {}
                self._herramienta(b["id"], b["nombre"], args)
        elif tipo == "assistant":
            for b in (d.get("message") or {}).get("content") or []:
                if not isinstance(b, dict):
                    continue
                if b.get("type") == "tool_use" and b.get("id") not in self.avisadas:
                    self._herramienta(b.get("id"), b.get("name"), b.get("input"))
                elif b.get("type") == "thinking" and not self.parciales:
                    self._avisar({"tipo": "pensando"})
        elif tipo == "user":
            contenido = (d.get("message") or {}).get("content")
            if isinstance(contenido, list) and any(isinstance(b, dict) and b.get("type") == "tool_result"
                                                   for b in contenido):
                self._avisar({"tipo": "fin_herramienta"})


class _Trozos:
    """El texto que va escribiendo, sacado de las líneas `stream_event` que
    da `--include-partial-messages` (C-0155).

    Llama a `al_trozo` con el texto ACUMULADO de todos los mensajes del turno,
    como mucho cada `CADA_TROZO_S` salvo al cerrar una frase, y `fin()` una
    última vez entero. Lo usan el proceso abierto y la llamada de un solo uso
    (C-0274): dos copias de esto acabarían dando trozos distintos."""

    def __init__(self, al_trozo: Callable[[str], None]):
        self.al_trozo, self.texto, self._avisado = al_trozo, "", 0.0

    def linea(self, d: dict) -> None:
        if d.get("type") != "stream_event":
            return
        ev = d.get("event") or {}
        if ev.get("type") == "message_start" and self.texto and not self.texto.endswith("\n"):
            self.texto += "\n\n"   # otro mensaje tras una herramienta
        trozo = ((ev.get("delta") or {}).get("text") or "") if ev.get("type") == "content_block_delta" else ""
        if trozo:
            self.texto += trozo
            ahora = time.monotonic()
            if ahora - self._avisado >= CADA_TROZO_S or trozo.rstrip()[-1:] in ".?!…:":
                self._avisado = ahora
                self.al_trozo(self.texto)

    def fin(self) -> None:
        if self.texto:
            self.al_trozo(self.texto)


def _mb(peso: int) -> str:
    return f"{peso / 1_000_000:.1f}".replace(".", ",")


def para_el_modelo(ruta: Path) -> tuple[int, str]:
    """Si un archivo puede ir en `imagenes` y cuánto pesará en el mensaje (383).

    `(peso, "")` si va: una imagen raster —ya reducida, si hace falta— o un
    PDF que cabe; el PDF va como bloque `document` (medido el 7-nov con haiku
    en el proceso abierto: leyó la frase de un PDF de una página).
    `(0, "")` si no es de lo que ve el modelo, y `(0, motivo)` si lo es pero
    no puede ir: quien llama lo dice en vez de tumbar el turno entero."""
    from .. import maquina
    from ..ideas import TIPOS_IMAGEN
    sufijo = ruta.suffix.lower()
    try:
        peso = ruta.stat().st_size
    except OSError:
        return 0, ""
    if sufijo in TIPOS_IMAGEN:
        if peso <= TOPE_IMAGEN:
            return peso, ""
        if maquina.encontrar("ffmpeg"):
            return TOPE_IMAGEN, ""
        return 0, f"pesa {_mb(peso)} MB y no hay ffmpeg para reducirla"
    if sufijo == ".pdf":
        return (peso, "") if peso <= TOPE_PDF else (0, f"pasa de {TOPE_PDF // 1_000_000} MB")
    return 0, ""


def _bloques(imagenes: list, prompt: str) -> list[dict]:
    """El mensaje con su texto delante y sus imágenes (y PDF) detrás, como lo
    lee `--input-format stream-json` (decisiones 335 y 383)."""
    import base64
    # El texto va delante: lleva el aviso de que lo adjunto es dato (322), y
    # el modelo tiene que leerlo antes que una captura que diga lo contrario
    # (revisión cruzada del 7-nov).
    bloques = [{"type": "text", "text": prompt}] if prompt else []
    for ruta in map(Path, imagenes):
        if ruta.suffix.lower() == ".pdf":
            bloques.append({"type": "document", "source": {"type": "base64", "media_type": "application/pdf",
                                                           "data": base64.b64encode(_pdf(ruta)).decode()}})
            continue
        try:
            datos, tipo = imagen(ruta)
        except MotorCaido as exc:
            # Una imagen que ffmpeg no puede reducir no tumba el turno entero:
            # el resto del mensaje sigue y el modelo se lo dice (383).
            bloques.append({"type": "text", "text": f"(No ves «{ruta.name}»: {exc}. Díselo.)"})
            continue
        bloques.append({"type": "image", "source": {"type": "base64", "media_type": tipo,
                                                    "data": base64.b64encode(datos).decode()}})
    return bloques


def _pdf(ruta: Path) -> bytes:
    try:
        datos = ruta.read_bytes()
    except OSError as exc:
        raise MotorCaido(f"no pude leer el PDF «{ruta.name}»: {exc}") from exc
    if len(datos) > TOPE_PDF:
        raise MotorCaido(f"el PDF «{ruta.name}» pasa de {TOPE_PDF // 1_000_000} MB: no se le puede mandar al modelo")
    return datos


def imagen(ruta: Path) -> tuple[bytes, str]:
    """Los bytes de una imagen y su tipo, ya en el tamaño que admite el modelo.
    Pública: la usa también `herramientas.ver_imagen` (384), con la misma
    guarda de tamaño que lo adjunto."""
    from ..ideas import TIPOS_IMAGEN   # los raster que se ven en línea: los mismos que admite la API
    try:
        datos = ruta.read_bytes()
    except OSError as exc:
        raise MotorCaido(f"no pude leer la imagen «{ruta.name}»: {exc}") from exc
    if len(datos) <= TOPE_IMAGEN:
        return datos, TIPOS_IMAGEN.get(ruta.suffix.lower(), "image/jpeg")
    return _reducida(ruta, len(datos)), "image/jpeg"


def _reducida(ruta: Path, peso: int) -> bytes:
    """La imagen en JPEG con su lado largo en `LADO_REDUCIDO`, por ffmpeg.

    Sin ffmpeg no se manda recortada ni a ciegas: se dice, y el turno lo
    enseña como error (383). La original no se toca: es lo que él adjuntó."""
    from .. import maquina
    mb = _mb(peso)
    ffmpeg = maquina.encontrar("ffmpeg")
    if not ffmpeg:
        raise MotorCaido(f"la imagen «{ruta.name}» pesa {mb} MB, más de lo que admite el modelo, y no encuentro "
                         "ffmpeg para reducirla")
    escala = (f"scale=w='min({LADO_REDUCIDO},iw)':h='min({LADO_REDUCIDO},ih)'"
              ":force_original_aspect_ratio=decrease:force_divisible_by=2")
    with tempfile.TemporaryDirectory(dir=_trabajo()) as carpeta:
        salida = Path(carpeta) / "reducida.jpg"
        try:
            r = subprocess.run([ffmpeg, "-nostdin", "-loglevel", "error", "-y", "-protocol_whitelist", "file",
                                "-f", _DEMUXER.get(ruta.suffix.lower(), "image2"), "-i", str(ruta), "-vf", escala,
                                "-frames:v", "1", "-q:v", "3", str(salida)],
                               capture_output=True, text=True, timeout=60)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise MotorCaido(f"no pude reducir la imagen «{ruta.name}» ({mb} MB): {exc}") from exc
        if r.returncode != 0 or not salida.is_file():
            raise MotorCaido(f"no pude reducir la imagen «{ruta.name}» ({mb} MB): ffmpeg dijo "
                             f"{(r.stderr or '').strip()[-200:] or r.returncode}")
        datos = salida.read_bytes()
    if len(datos) > TOPE_IMAGEN:
        raise MotorCaido(f"la imagen «{ruta.name}» sigue pesando demasiado aun reducida")
    return datos


def _respuesta(d: dict, sesion: str, segundos: float, modelo: str) -> Respuesta:
    if d.get("is_error"):
        # Medido el 7-nov (2.1.280): `subtype: error_max_budget_usd`,
        # `terminal_reason: budget_exhausted` y sin `result`.
        if d.get("subtype") == "error_max_budget_usd" or d.get("terminal_reason") == "budget_exhausted":
            coste = float(d.get("total_cost_usd") or 0)
            raise TopeAgotado(f"llegó al tope de gasto (llevaba {coste:.2f} USD equivalentes)", coste)
        texto = f"claude: {d.get('result') or d.get('terminal_reason') or 'error'}"[:400]
        if d.get("terminal_reason") == "api_error":
            # Medido (C-0170): es lo que queda cuando el CLI agota sus
            # reintentos contra la API. Del motor, no del pedido (C-0307).
            raise MotorNoDisponible(texto, "api")
        raise MotorCaido(texto)
    gasto = d.get("usage") or {}
    return Respuesta(texto=(d.get("result") or "").strip(), sesion=d.get("session_id") or sesion,
                     estructurada=d.get("structured_output"), segundos=segundos,
                     coste=float(d.get("total_cost_usd") or 0), modelo=modelo,
                     entrada=int(gasto.get("input_tokens") or 0) + int(gasto.get("cache_read_input_tokens") or 0)
                     + int(gasto.get("cache_creation_input_tokens") or 0),
                     salida=int(gasto.get("output_tokens") or 0))


class _Abierto:
    """Un `claude -p` en stream-json esperando el siguiente turno de su hilo."""

    def __init__(self, linea: list[str], entorno: dict, clave: tuple):
        self.clave = clave
        self.usado = time.monotonic()
        self.lineas: queue.Queue = queue.Queue()
        self._err = open(_trabajo() / "abierto.err", "a", encoding="utf-8")  # noqa: SIM115 — vive con el proceso
        # Su propio grupo, como `_Vigia` (C-0241): si hay que matarlo, matar
        # sólo a `claude` dejaba vivo a su servidor MCP (C-0506).
        self.p = subprocess.Popen(linea, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self._err,
                                  text=True, cwd=_trabajo(), env=entorno, process_group=0)
        threading.Thread(target=self._leer, daemon=True, name="motor-abierto").start()

    def _leer(self) -> None:
        for l in self.p.stdout:
            self.lineas.put(l)
        self.lineas.put(None)

    def vivo(self) -> bool:
        return self.p.poll() is None

    def turno(self, prompt: str | list[dict], tope: float, al_trozo: Callable[[str], None] | None = None,
              al_evento: Callable[[dict], None] | None = None,
              parar: Callable[[], bool] | None = None) -> dict | None:
        """El evento `result` del turno, o None si el proceso murió antes.

        `prompt` es el texto o, con imágenes, la lista de bloques del mensaje
        (`_bloques`): van en el mismo proceso que el resto del hilo (383).

        Con `al_trozo`, el texto acumulado según llega (`--include-partial-messages`),
        como mucho cada `CADA_TROZO_S` salvo al cerrar una frase, y siempre una
        última vez entero. Se llama desde este hilo, el del turno: quien lo
        recibe escribe en su conexión de sqlite, que no se comparte entre hilos.
        `al_evento`, lo mismo con lo que va haciendo (`_Actividad`).

        `parar` (C-0506): se le pregunta cada `CADA_PARAR_S`, desde este hilo.
        Si dice que sí, el turno se corta **entre herramientas**: la que está
        en vuelo acaba antes (hasta `ESPERA_HERRAMIENTA_S`), y entonces se le
        pide al CLI que pare (`_Corte`). El proceso sigue vivo para el turno
        siguiente (328). Lo cortado lanza `Cancelada`, nunca devuelve None:
        None hace que `llamar` repita el turno por `--resume`."""
        trozos = _Trozos(al_trozo) if al_trozo is not None else None
        actividad = _Actividad(al_evento) if al_evento is not None else None
        corte = _Corte(parar) if parar is not None else None
        recientes: deque = deque(maxlen=LINEAS_GUARDADAS)
        self.usado = t0 = time.monotonic()
        try:
            self.p.stdin.write(json.dumps({"type": "user", "message": {"role": "user", "content": prompt}},
                                          ensure_ascii=False) + "\n")
            self.p.stdin.flush()
        except OSError:
            return None
        fin = time.monotonic() + tope
        oido = time.monotonic()        # cuándo dijo algo por última vez

        def cortado(motivo: str | None = None) -> Cancelada:
            # Lo ya escrito se da entero: el último trozo puede no haber salido.
            if motivo:
                self._volcar(motivo, recientes)
            if trozos is not None:
                trozos.fin()
            exc = Cancelada("se detuvo a petición del dueño")
            # Si el proceso sigue vivo, la sesión sigue ahí para el turno siguiente.
            exc.sigue = self.vivo()
            return exc

        while True:
            if corte is not None:
                if corte.mirar() == "pedir" and not self._interrumpir(corte.id):
                    corte.que = "matar"
                if corte.que == "matar":
                    self._matar()
                    raise cortado("se pidió parar y no cerró el turno: se mata")
            ahora = time.monotonic()
            espera = min(fin - ahora, SIN_NOTICIAS_S - (ahora - oido))
            if corte is not None:
                espera = min(espera, CADA_PARAR_S)
            try:
                l = self.lineas.get(timeout=max(0.1, espera))
            except queue.Empty:
                ahora = time.monotonic()
                if ahora < fin and ahora - oido < SIN_NOTICIAS_S:
                    continue           # sólo tocaba preguntar a `parar`
                self._matar()
                if corte is not None and corte.pedido is not None:
                    raise cortado() from None
                if ahora < fin:
                    # Colgado: se repite por el camino de siempre (devuelve None).
                    self._volcar(f"{SIN_NOTICIAS_S} s sin decir nada: se mata y el turno se repite", recientes)
                    return None
                self._volcar(f"llegó al tope de {int(tope)} s", recientes)
                raise MotorCaido(f"el modelo no contestó en {int(tope)} s") from None
            if l is None:
                if corte is not None and corte.pedido is not None:
                    raise cortado()
                return None
            oido = time.monotonic()
            recientes.append((oido - t0, l))
            try:
                d = json.loads(l)
            except ValueError:
                continue
            if actividad is not None:
                actividad.linea(d)
            if trozos is not None:
                trozos.linea(d)
            if corte is not None:
                corte.linea(d)
            if d.get("type") == "result" and corte is not None and corte.pedido is not None:
                # El motivo medido o, si otra versión lo llama de otra forma,
                # el `subtype` de un turno interrumpido: con la petición hecha,
                # nunca debe acabar en «No pude contestar».
                if d.get("is_error") and (d.get("terminal_reason") in CORTADO_POR_INTERRUMPIR
                                          or d.get("subtype") == "error_during_execution"):
                    self.usado = time.monotonic()
                    raise cortado()
                # Acabó solo antes de que el CLI atendiera la petición: gana
                # lo terminado. Se espera a su respuesta, para que nada de esta
                # petición quede por leer al empezar el turno siguiente.
                self._esperar_respuesta(corte)
            if d.get("type") == "result":
                self.usado = time.monotonic()
                if d.get("is_error"):
                    motivo = memoria.ocultar_secretos(str(d.get("result") or ""))[:200]
                    self._volcar(f"dio error a los {time.monotonic() - t0:.0f} s ({d.get('terminal_reason') or '?'}:"
                                 f" {motivo})", recientes)
                if trozos is not None:
                    trozos.fin()
                return d

    def _volcar(self, motivo: str, recientes: deque) -> None:
        """Lo último que dijo el turno, a stderr: bajo systemd es el journal.

        Cada línea con su clase delante (lo que se busca es dónde se paró) y
        recortada y sin llaves (`memoria.ocultar_secretos`). De lo que devolvió
        una herramienta (las líneas `user`), sólo la clase y el tamaño
        (C-0185): puede traer una pantalla entera, un `.env` leído o un correo,
        y el filtro de llaves es una red, no una garantía (regla dura 22)."""
        print(f"motor: proceso abierto {self.p.pid}: {motivo}. Sus últimas {len(recientes)} líneas del turno:",
              file=sys.stderr)
        for t, l in recientes:
            try:
                d = json.loads(l)
                clase = f"{d.get('type')}/{d.get('subtype') or (d.get('event') or {}).get('type') or ''}"
                if d.get("type") == "user":
                    contenido = (d.get("message") or {}).get("content")
                    resultado = isinstance(contenido, list) and any(
                        isinstance(b, dict) and b.get("type") == "tool_result" for b in contenido)
                    print(f"  +{t:6.1f}s user/{'tool_result' if resultado else ''} ({len(l)} caracteres)",
                          file=sys.stderr)
                    continue
            except (ValueError, AttributeError):
                clase = "?"
            print(f"  +{t:6.1f}s {clase} {memoria.ocultar_secretos(l.strip())[:240]}", file=sys.stderr)
        sys.stderr.flush()

    def _interrumpir(self, ident: str) -> bool:
        """Le pide al CLI que corte el turno en curso (C-0506): el
        `control_request` «interrupt» del stream-json. False si no se pudo escribir."""
        try:
            self.p.stdin.write(json.dumps({"type": "control_request", "request_id": ident,
                                           "request": {"subtype": "interrupt"}}) + "\n")
            self.p.stdin.flush()
        except OSError:
            return False
        return True

    def _esperar_respuesta(self, corte: _Corte) -> None:
        """Lo que queda de una petición de parar que llegó tarde: su
        `control_response`, si aún no salió, con un tope corto."""
        fin = time.monotonic() + 2.0
        while not corte.respondido and time.monotonic() < fin:
            try:
                l = self.lineas.get(timeout=max(0.05, fin - time.monotonic()))
            except queue.Empty:
                return
            if l is None:
                self.lineas.put(None)      # que el turno siguiente vea que murió
                return
            try:
                corte.linea(json.loads(l))
            except ValueError:
                pass

    def _matar(self) -> None:
        _matar_grupo(self.p)
        try:
            self.p.wait(timeout=5)     # que `vivo()` lo vea muerto enseguida
        except subprocess.TimeoutExpired:
            pass

    def cerrar(self) -> None:
        try:
            self.p.stdin.close()
        except OSError:
            pass
        try:
            self.p.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self._matar()
            self.p.wait()
        self._err.close()


class _Corte:
    """Cuándo pedir que pare un turno del proceso abierto (C-0506).

    Lleva las herramientas en vuelo: las del mensaje entero del modelo
    (`assistant` con `tool_use`, que es cuando el CLI la ejecuta) hasta su
    `tool_result`. `mirar()` dice qué toca: nada, «pedir» (una vez) o «matar»
    (pedido y sin cerrar el turno en `ESPERA_INTERRUMPIR_S`). Una lectura de
    `parar` que falla no corta: cancelar es una petición, no una garantía."""

    def __init__(self, parar: Callable[[], bool]):
        self.parar = parar
        self.id = f"parar-{uuid.uuid4().hex[:12]}"
        self.en_vuelo: set = set()
        self.quiere: float | None = None     # cuándo dijo `parar` que sí
        self.pedido: float | None = None     # cuándo se mandó el «interrupt»
        self.respondido = False
        self.que = ""
        self._mirado = float("-inf")

    def linea(self, d: dict) -> None:
        tipo = d.get("type")
        contenido = (d.get("message") or {}).get("content")
        if tipo == "assistant" and isinstance(contenido, list):
            self.en_vuelo |= {b.get("id") for b in contenido if isinstance(b, dict) and b.get("type") == "tool_use"}
        elif tipo == "user" and isinstance(contenido, list):
            self.en_vuelo -= {b.get("tool_use_id") for b in contenido
                              if isinstance(b, dict) and b.get("type") == "tool_result"}
        elif tipo == "control_response" and (d.get("response") or {}).get("request_id") == self.id:
            self.respondido = True

    def mirar(self) -> str:
        ahora = time.monotonic()
        if self.pedido is not None:
            if ahora - self.pedido >= ESPERA_INTERRUMPIR_S:
                self.que = "matar"
            return ""
        if self.quiere is None and ahora - self._mirado >= CADA_PARAR_S:
            self._mirado = ahora
            try:
                if self.parar():
                    self.quiere = ahora
            except Exception:  # noqa: BLE001 — una lectura que falla no corta el turno
                pass
        if self.quiere is not None and (not self.en_vuelo or ahora - self.quiere >= ESPERA_HERRAMIENTA_S):
            self.pedido = ahora
            return "pedir"
        return ""


class Suscripcion(Motor):
    id = "suscripcion"
    nombre = "Suscripción de Claude (claude -p)"

    def __init__(self):
        self._abiertos: dict[str, _Abierto] = {}
        self._cerrojo = threading.Lock()

    def disponible(self) -> str | None:
        if not shutil.which("claude", path=tmux.path_de_usuario()):  # sólo busca, no arranca (--model en _linea)
            return "no encuentro `claude` en el PATH de usuario"
        return None

    def _linea(self, entorno, *, modelo, sistema, sesion, nueva, herramientas, esquema, esfuerzo,
               entorno_extra, persistir, nativas=(), tope_usd=None) -> tuple[list[str], str]:
        nativas, tope_usd = _nativas(nativas), _tope(tope_usd)
        if nativas and herramientas:
            raise ValueError("con `nativas` no van las herramientas del secretario: lo leído en la web no "
                             "puede accionar nada (385)")
        # Sin nativas queda `--tools ""`: la conversación no busca ni lee en la web (390).
        linea = [_claude(entorno), "-p", "--model", modelo, "--tools", ",".join(nativas), "--setting-sources", "",
                 "--strict-mcp-config", "--permission-mode", "dontAsk"]
        if esfuerzo:
            linea += ["--effort", esfuerzo]
        if not persistir:
            linea += ["--no-session-persistence"]
        if herramientas:
            para_mcp = {"HUB_HOME": str(config.HUB_HOME), "PATH": entorno["PATH"], **entorno_extra}
            linea += ["--mcp-config", mcp_config(para_mcp), "--allowedTools", "mcp__secretario"]
        if nativas:
            # Con `dontAsk`, lo que no está permitido se deniega (medido el 7-nov).
            linea += ["--allowedTools", ",".join(nativas)]
            if "WebFetch" in nativas:
                linea += ["--disallowedTools", ",".join(f"WebFetch(domain:{d})" for d in NO_LEER)]
        if tope_usd is not None:
            linea += ["--max-budget-usd", f"{tope_usd:g}"]
        if esquema:
            linea += ["--json-schema", json.dumps(esquema)]
        if sesion and not nueva:
            linea += ["--resume", sesion]
        else:
            sesion = sesion or str(uuid.uuid4())
            linea += ["--session-id", sesion]
            if sistema:
                linea += ["--system-prompt", sistema]
        return linea, sesion

    def llamar(self, prompt, *, modelo, sistema, sesion, nueva, herramientas, esquema, esfuerzo,
               entorno_extra, persistir, abierta, imagenes=None, al_trozo=None, al_evento=None,
               nativas=(), tope_usd=None, parar=None, tope_s=None):
        entorno = {**os.environ, **CORTES_DE_RED, "PATH": tmux.path_de_usuario(), **entorno_extra}
        kw = dict(modelo=modelo, sistema=sistema, sesion=sesion, nueva=nueva, herramientas=herramientas,
                  esquema=esquema, esfuerzo=esfuerzo, entorno_extra=entorno_extra, persistir=persistir,
                  nativas=_nativas(nativas), tope_usd=_tope(tope_usd))
        if abierta and sesion and not esquema:
            # El proceso abierto da trozos; de los demás caminos, sólo la llamada
            # suelta sin imágenes ni esquema (`_suelta`, C-0274): por el resto llega entera.
            # Con imágenes también (decisión 383): saltárselo arrancaba otro
            # proceso con la misma sesión mientras éste seguía vivo, y nunca
            # puede haber dos escribiéndola (328). Se arman antes de tocar el
            # proceso: una imagen que no se puede mandar no lo tumba.
            contenido = _bloques(imagenes, prompt) if imagenes else prompt
            t0 = time.monotonic()
            r = self._en_abierto(contenido, entorno, kw, al_trozo, al_evento, tope_s, parar)
            if r is not None:
                return r
            perdidos = time.monotonic() - t0
            # Pedido parar mientras moría (C-0506): no se repite lo que él paró.
            if parar is not None and _pide(parar):
                raise Cancelada("se detuvo a petición del dueño")
            # Murió, calló o dio error de la API a mitad: la sesión ya existe y
            # se retoma. Si era su primer turno puede que no llegara a
            # guardarse, y entonces se crea.
            # Retomarla con el mismo mensaje hacía que el modelo lo leyera dos
            # veces y repitiera lo ya hecho —una tarjeta, una nota, un aviso—
            # (C-0185): va con el aviso del corte, y con el mensaje por si no
            # llegó a guardarse. Lo escrito del intento tirado ya no vale.
            if al_evento is not None:
                _Actividad(al_evento)._avisar({"tipo": "reintento"})   # adorno: no tumba el turno
            # Una vez: el turno que ya cortó un reinicio del servicio lo trae
            # puesto de `conversacion` (C-0269), y dos seguidos le confundían (C-0314).
            retomar = prompt if prompt.startswith(RETOMAR) else RETOMAR + prompt
            # Con `al_trozo`, el reintento también se ve escribir: la llamada
            # suelta ya sabe darlo (C-0274), y sin él llegaba entero de golpe.
            try:
                r = self.llamar(retomar, **{**kw, "nueva": False}, abierta=False, imagenes=imagenes,
                                al_evento=al_evento, al_trozo=al_trozo, tope_s=tope_s, parar=parar)
            except Cancelada:
                raise
            except MotorCaido:
                if not kw["nueva"]:
                    raise
                r = self.llamar(prompt, **kw, abierta=False, imagenes=imagenes, al_evento=al_evento,
                                al_trozo=al_trozo, tope_s=tope_s, parar=parar)
            r.perdidos += perdidos
            return r
        if sesion:
            self.soltar(sesion)      # nunca dos procesos escribiendo la misma sesión
        if imagenes:
            return self._con_imagenes(prompt, imagenes, entorno, kw, parar, tope_s)
        linea, sesion = self._linea(entorno, **kw)
        if (al_evento is not None or al_trozo is not None) and not esquema:
            return self._suelta(linea, prompt, entorno, sesion, kw["modelo"], al_evento, parar, al_trozo, tope_s)
        linea += ["--output-format", "json"]
        t0 = time.monotonic()
        r = _correr(linea, prompt, entorno, parar, tope_s)
        try:
            d = json.loads(r.stdout)
        except ValueError as exc:
            raise MotorCaido(f"`claude -p` salió con {r.returncode}: {(r.stderr or r.stdout)[-400:]}") from exc
        return _respuesta(d, sesion, time.monotonic() - t0, modelo)

    def _suelta(self, linea, prompt, entorno, sesion, modelo, al_evento=None, parar=None, al_trozo=None,
                tope_s=None) -> Respuesta:
        """Una llamada de un solo uso que va contando lo que hace (C-0166).

        La del modelo mayor tras escalar, sobre todo: sin esto, el personaje se
        quedaba «pensando» mientras buscaba. `stream-json` en vez de `json`
        (pide `--verbose`), leído línea a línea. Sin `al_trozo` va sin mensajes
        parciales y cada herramienta se avisa al llegar su mensaje entero; con
        él, con `--include-partial-messages`, y la respuesta se va viendo como
        en el proceso abierto (C-0274: el mayor escribía minuto y medio sin que
        se viera una palabra). `al_trozo` se llama desde este hilo, el de
        quien llamó."""
        linea = linea + ["--output-format", "stream-json", "--verbose"]
        if al_trozo is not None:
            linea.append("--include-partial-messages")
        actividad = _Actividad(al_evento) if al_evento is not None else None
        trozos = _Trozos(al_trozo) if al_trozo is not None else None
        t0 = time.monotonic()
        with tempfile.TemporaryFile("w+", encoding="utf-8") as err:
            try:
                p = subprocess.Popen(linea, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=err,
                                     text=True, cwd=_trabajo(), env=entorno, process_group=0)
            except OSError as exc:
                raise MotorNoDisponible(f"no se pudo arrancar claude: {exc}", "no_arranca") from exc
            vigia = _Vigia(p, parar, tope_s)
            resultado = None
            try:
                try:
                    p.stdin.write(prompt)
                    p.stdin.close()
                except OSError:
                    pass
                for l in p.stdout:
                    try:
                        d = json.loads(l)
                    except ValueError:
                        continue
                    if actividad is not None:
                        actividad.linea(d)
                    if trozos is not None:
                        trozos.linea(d)
                    if d.get("type") == "result":
                        resultado = d
                        if trozos is not None:
                            trozos.fin()
                p.wait()
            except BaseException:
                vigia.matar()
                raise
            finally:
                vigia.cerrar()
            if resultado is None:
                vigia.comprobar()
                err.seek(0)
                raise MotorCaido(f"`claude -p` salió con {p.returncode}: {err.read()[-400:]}")
        return _respuesta(resultado, sesion, time.monotonic() - t0, modelo)

    def _con_imagenes(self, prompt, imagenes, entorno, kw, parar=None, tope_s=None) -> Respuesta:
        """Una llamada suelta con imágenes: `-p` sólo admite texto por stdin,
        así que va como un mensaje de stream-json con sus bloques (decisión 335).
        Quien llama ya soltó el proceso abierto de esa sesión (328)."""
        bloques = _bloques(imagenes, prompt)
        linea, sesion = self._linea(entorno, **kw)
        linea += ["--input-format", "stream-json", "--output-format", "stream-json", "--verbose"]
        entrada = json.dumps({"type": "user", "message": {"role": "user", "content": bloques}}) + "\n"
        t0 = time.monotonic()
        r = _correr(linea, entrada, entorno, parar, tope_s)
        for l in reversed(r.stdout.splitlines()):
            try:
                d = json.loads(l)
            except ValueError:
                continue
            if d.get("type") == "result":
                return _respuesta(d, sesion, time.monotonic() - t0, kw["modelo"])
        raise MotorCaido(f"`claude -p` salió con {r.returncode}: {(r.stderr or r.stdout)[-400:]}")

    def _en_abierto(self, prompt, entorno, kw, al_trozo=None, al_evento=None, tope_s=None,
                    parar=None) -> Respuesta | None:
        sesion = kw["sesion"]
        # Con otras nativas u otro tope es otro proceso: la línea no es la misma (385).
        clave = (kw["modelo"], kw["esfuerzo"], kw["herramientas"], kw["nativas"], kw["tope_usd"],
                 json.dumps(kw["entorno_extra"], sort_keys=True))
        with self._cerrojo:
            a = self._abiertos.get(sesion)
            if a is not None and (a.clave != clave or not a.vivo()):
                self._abiertos.pop(sesion).cerrar()
                a = None
                kw = {**kw, "nueva": False}
            if a is None:
                linea, _ = self._linea(entorno, **kw)
                linea += ["--input-format", "stream-json", "--output-format", "stream-json", "--verbose",
                          "--include-partial-messages"]
                try:
                    a = self._abiertos[sesion] = _Abierto(linea, entorno, clave)
                except OSError as exc:
                    raise MotorNoDisponible(f"no se pudo arrancar claude: {exc}", "no_arranca") from exc
        t0 = time.monotonic()
        try:
            d = a.turno(prompt, TOPE_SEGUNDOS if tope_s is None else tope_s, al_trozo, al_evento, parar)
        except Cancelada:
            # Parado por el «interrupt», el proceso sigue vivo y es del hilo
            # entero (328); si hubo que matarlo, se suelta (C-0506).
            if not a.vivo():
                self.soltar(sesion)
            raise
        except MotorCaido:
            self.soltar(sesion)
            raise
        # Un error de la API, agotados ya los reintentos del CLI (C-0170), se
        # trata como si el proceso hubiera muerto: un intento más por
        # `--resume`, con conexión nueva, en vez de dar el turno por perdido.
        if d is None or (d.get("is_error") and d.get("terminal_reason") == "api_error"):
            self.soltar(sesion)
            return None
        return _respuesta(d, sesion, time.monotonic() - t0, kw["modelo"])

    def soltar(self, sesion=None):
        with self._cerrojo:
            for s in [sesion] if sesion else list(self._abiertos):
                a = self._abiertos.pop(s, None) if s else None
                if a is not None:
                    a.cerrar()

    def podar(self):
        viejos = [s for s, a in list(self._abiertos.items())
                  if time.monotonic() - a.usado > ABIERTO_MAX_S or not a.vivo()]
        for s in viejos:
            self.soltar(s)


MOTORES: dict[str, Motor] = {"suscripcion": Suscripcion()}


def actual() -> Motor:
    from .conversacion import ajustes
    eleccion = str(ajustes().get("motor") or "suscripcion")
    if eleccion not in MOTORES:
        # Sin causa: el mensaje ya dice qué arreglar, y así llega al chat.
        raise MotorNoDisponible(f"`motor: {eleccion}` en secretario.yml no existe; los que hay: "
                                f"{', '.join(MOTORES)}", None)
    return MOTORES[eleccion]


def _admite(m: Motor, nombre: str) -> bool:
    import inspect
    parametros = inspect.signature(m.llamar).parameters.values()
    return any(p.name == nombre or p.kind is p.VAR_KEYWORD for p in parametros)


def llamar(prompt: str, *, modelo: str, sistema: str | None = None, sesion: str | None = None,
           nueva: bool = False, herramientas: bool = True, esquema: dict | None = None,
           esfuerzo: str | None = None, entorno_extra: dict | None = None,
           persistir: bool = True, abierta: bool = False, imagenes: list | None = None,
           trabajo: str = "", al_trozo: Callable[[str], None] | None = None,
           al_evento: Callable[[dict], None] | None = None,
           nativas: tuple[str, ...] = (), tope_usd: float | None = None,
           parar: Callable[[], bool] | None = None, tope_s: float | None = None) -> Respuesta:
    """Una llamada. `sesion` + `nueva` la crea con ese id; `sesion` solo la retoma.

    `persistir=False` para lo que no se retoma nunca (triaje, cierres): cada
    lote dejaría su transcript en `~/.claude/projects/`, cientos al día.
    `abierta=True` deja el proceso esperando el siguiente turno de esa sesión.
    `al_trozo`: el texto a medio escribir, si el motor sabe darlo (ver `Motor`).
    `al_evento`: qué va haciendo (pensar, cada herramienta), si sabe darlo.
    `imagenes`: rutas que van como bloques del mensaje (`para_el_modelo`: imagen
    raster o PDF); con `abierta`, en el mismo proceso que el resto del hilo (383).
    `nativas`: buscar y leer en la web, sólo de `NATIVAS_PERMITIDAS` y con
    `herramientas=False` (385); `tope_usd`: lo más que puede gastar. Las dos
    lanzan `ValueError` si no valen, y `MotorCaido` si el motor no sabe de
    ellas: callarlas daría una investigación sin web o sin tope.
    `parar`: se le pregunta cada `CADA_PARAR_S`, desde otro hilo, si cortar;
    si dice que sí, se mata el proceso y lanza `Cancelada` (C-0241). Es
    opcional como `al_evento` —un motor que no sabe de él lo ignora—, porque
    no es una garantía: quien pidió parar comprueba que paró. Con `abierta`
    también (C-0506): ahí no se mata el proceso, que es de todos los turnos
    del hilo (328), sino que se le pide al CLI que corte el turno, entre
    herramientas (`_Abierto.turno`); sólo si no lo cierra se mata su grupo.
    `tope_s`: cuánto puede tardar, si no `TOPE_SEGUNDOS` (SEC-23). Es de cada
    trabajo: lo que va aparte del turno —una investigación— puede tardar más
    que una respuesta en el chat sin que nadie espere delante. Opcional como
    `parar`: un motor que no sabe de él corta en su tope, y eso es margen, no
    una guarda que se pierda."""
    nativas, tope_usd, tope_s = _nativas(nativas), _tope(tope_usd), _tope_s(tope_s)
    if nativas and herramientas:
        raise ValueError("con `nativas` no van las herramientas del secretario: lo leído en la web no puede "
                         "accionar nada (385); pasa herramientas=False")
    t0 = time.monotonic()
    m = actual()
    # Un motor que no conoce `al_trozo` no lo recibe: contesta entero y nadie
    # se entera de la diferencia (ver `Motor`).
    if al_trozo is not None and not _admite(m, "al_trozo"):
        al_trozo = None
    if al_evento is not None and not _admite(m, "al_evento"):
        al_evento = None
    if parar is not None and not _admite(m, "parar"):
        parar = None
    if tope_s is not None and not _admite(m, "tope_s"):
        tope_s = None
    for nombre, valor in (("nativas", nativas), ("tope_usd", tope_usd)):
        if valor and not _admite(m, nombre):
            raise MotorCaido(f"el motor «{m.id}» no sabe de `{nombre}`")
    try:
        r = m.llamar(prompt, modelo=modelo, sistema=sistema, sesion=sesion, nueva=nueva,
                            herramientas=herramientas, esquema=esquema, esfuerzo=esfuerzo,
                            entorno_extra=dict(entorno_extra or {}), persistir=persistir, abierta=abierta,
                            **({"imagenes": imagenes} if imagenes else {}),
                            **({"al_trozo": al_trozo} if al_trozo else {}),
                            **({"al_evento": al_evento} if al_evento else {}),
                            **({"nativas": nativas} if nativas else {}),
                            **({"tope_usd": tope_usd} if tope_usd is not None else {}),
                            **({"parar": parar} if parar is not None else {}),
                            **({"tope_s": tope_s} if tope_s is not None else {}))
    except MotorCaido as exc:
        # Lo gastado hasta el tope también se gastó (regla 13).
        memoria.apuntar_llamada(trabajo, modelo, time.monotonic() - t0, getattr(exc, "coste", 0.0), ok=False)
        raise
    if r.perdidos:
        memoria.apuntar_llamada(trabajo, modelo, r.perdidos, ok=False)
    memoria.apuntar_llamada(trabajo, modelo, r.segundos, r.coste, r.entrada, r.salida)
    return r


# ───────────────────────── cuando el motor no está (C-0307) ─────────────────────────

#: La racha en curso, en `estado`: `{desde, causa, fallos, proximo, apuntada}`.
#: Una sola para todo lo que reintenta solo (el triaje y el cierre de hilos):
#: lo que supo uno le vale al otro. Se rehace sola: borrarla sólo adelanta un intento.
CLAVE_PAUSA = "motor_no_disponible"
#: Lo que se espera tras cada fallo seguido antes de volver a intentarlo. El
#: ciclo es de 30 s: sin esto, una caída de horas era una llamada fallida (y
#: su línea en la bitácora) cada vuelta.
RETROCESO_S = (30, 60, 120, 300, 600, 900)
#: Una línea por racha en la bitácora; otra si la última tiene más que esto. El
#: parte de la mañana saca «Falló» de las últimas 24 h: con una sola, al
#: segundo día de caída no diría nada.
REAPUNTAR_S = 20 * 3600
#: Cuántos fallos seguidos de un pedido (un lote, un hilo) hacen rendirse con él.
FALLOS_PARA_RENDIRSE = 3
#: 🔴 La red contra quedarse sordo (regla dura 2, decisión 376): cada tantos
#: fallos seguidos «del motor» se sondea, y si el motor contesta, lo que falla
#: es el pedido y ese fallo cuenta contra él. Sin esto, un pedido que la API
#: rechazase siempre (`api_error`) se reintentaría sin fin y nada de lo que
#: espera detrás se atendería. Al llegar al retroceso mayor: en una caída de
#: verdad es una sonda —que falla sin gastar— cada hora y media.
COMPROBAR_CADA = len(RETROCESO_S)
#: Lo más que se espera a la sonda. Decir «no contesta» de más sólo hace
#: esperar; decir «contesta» de más aparta mensajes buenos.
SONDA_TOPE_S = 60
#: Cómo empieza la línea de la racha en la bitácora, y con qué acción se apunta
#: que el motor volvió: el parte de la mañana las casa para no decir sólo «Falló».
NO_DISPONIBLE = "El modelo no está disponible"
ACCION_VUELTA = "motor"
#: La causa, como se apunta en la bitácora (la lee el dueño en el parte).
QUE_PASA = {
    "no_arranca": "Claude Code no arranca en esta máquina",
    "sin_sesion": "Claude Code no tiene la sesión iniciada",
    "cuota": "se acabó el uso de Claude por ahora",
    "red": "no hay conexión con Claude",
    "api": "Claude no contesta o contesta con un error (si dura, abre `claude` en una terminal: ahí se ve si "
           "falta iniciar sesión o se acabó el uso)",
}


def _iso(d: datetime) -> str:
    return d.isoformat(timespec="seconds")


def _racha(con: sqlite3.Connection) -> dict | None:
    e = memoria.leer(con, CLAVE_PAUSA)
    return e if isinstance(e, dict) else None


def en_pausa(con: sqlite3.Connection, ahora: datetime | None = None) -> dict | None:
    """La racha, si todavía no toca volver a intentarlo; None si se puede llamar.

    Se mira justo antes de `llamar`, y sólo quien reintenta solo: lo que no
    necesita al modelo (descartar lo trivial, cerrar un hilo vacío) sigue.
    🔴 Una pausa que no se entiende, o con más espera que la mayor posible
    (el reloj saltó), no pausa: lo que decide saltarse un paso del ciclo no
    puede saltárselo para siempre (regla dura 2)."""
    e = _racha(con)
    if e is None:
        return None
    ahora = ahora or datetime.now(timezone.utc)
    try:
        falta = (datetime.fromisoformat(str(e.get("proximo"))) - ahora).total_seconds()
    except (TypeError, ValueError):
        return None
    return e if 0 < falta <= RETROCESO_S[-1] else None


def pausar(con: sqlite3.Connection, exc: BaseException, trabajo: str, ahora: datetime | None = None) -> dict:
    """Apunta un fallo más de la racha y pone la hora del intento siguiente.
    Devuelve la racha. `trabajo`, quién lo pedía: es la acción con que se
    apunta, una vez por racha (y otra pasadas `REAPUNTAR_S`).

    Sin aviso al teléfono: no es una clase de `avisos.CLASES` (regla dura 3).
    Cada fallo se dice en el registro del servicio (regla 21), sin el texto
    del error: puede llevar salida de `claude` (regla 22)."""
    ahora = ahora or datetime.now(timezone.utc)
    e = _racha(con) or {}
    try:
        fallos = max(0, int(e.get("fallos") or 0)) + 1
    except (TypeError, ValueError):
        fallos = 1
    espera = RETROCESO_S[min(fallos, len(RETROCESO_S)) - 1]
    # Uno sin clasificar que la sonda no desmintió: no se sabe más que eso.
    causa = exc.causa if isinstance(exc, MotorNoDisponible) else "api"
    apuntada = e.get("apuntada")
    try:
        toca = not apuntada or (ahora - datetime.fromisoformat(str(apuntada))).total_seconds() > REAPUNTAR_S
    except (TypeError, ValueError):
        toca = True
    if toca:
        que = QUE_PASA.get(causa) or memoria.ocultar_secretos(str(exc))[:200]
        memoria.apuntar(con, trabajo, ok=False,
                        resultado=f"{NO_DISPONIBLE}: {que}. Lo reintento solo, cada vez más espaciado "
                                  f"(hasta cada {RETROCESO_S[-1] // 60} min); mientras, no aparto mensajes ni "
                                  "cierro conversaciones sin resumen.")
        apuntada = _iso(ahora)
    estado = {"desde": e.get("desde") or _iso(ahora), "causa": causa or "", "fallos": fallos,
              "proximo": _iso(ahora + timedelta(seconds=espera)), "apuntada": apuntada}
    memoria.poner(con, CLAVE_PAUSA, estado)
    print(f"motor: no disponible ({causa or 'configuración'}) al pedirle «{trabajo}»; van {fallos} seguidos y "
          f"se reintenta en {espera} s", file=sys.stderr, flush=True)
    return estado


def reanudar(con: sqlite3.Connection) -> bool:
    """El motor contestó: se acaba la racha. Devuelve si había una. Queda
    dicho en la bitácora, una vez por racha: sin ello el parte de la mañana
    sólo diría que falló, no que ya volvió."""
    e = memoria.leer(con, CLAVE_PAUSA)
    if e is None:
        return False
    memoria.quitar(con, CLAVE_PAUSA)
    if not isinstance(e, dict):
        return False                    # algo que no se entendía: fuera, sin más
    if e.get("apuntada"):
        desde = a_local(str(e.get("desde") or ""), "%H:%M") or "hace un rato"
        memoria.apuntar(con, ACCION_VUELTA, nivel="auto",
                        resultado=f"El modelo vuelve a contestar: no estaba disponible desde las {desde} "
                                  f"({e.get('fallos')} fallos seguidos). Sigo con lo que esperaba.")
    print(f"motor: vuelve a contestar; no estaba disponible desde {e.get('desde')} ({e.get('fallos')} fallos "
          "seguidos)", file=sys.stderr, flush=True)
    return True


def responde(modelo: str | None = None) -> bool:
    """La sonda: ¿contesta el motor a una llamada mínima? Sin herramientas,
    sin persistir, y con `modelo` (el del trabajo que falla: el uso puede
    agotarse para un modelo y no para otro); sin él, el del triaje.

    🔴 Gasta una llamada de verdad, pequeña: sólo se usa antes de rendirse
    con un pedido (`rendirse`), nunca en cada vuelta. Lo que falle, sea lo que
    sea, es «no contesta»: lo dudoso espera, no se aparta."""
    from . import enrutador
    t0 = time.monotonic()
    try:
        llamar("Contesta sólo con la palabra: ok", modelo=modelo or enrutador.modelo("triaje"),
               sistema="Eres una sonda de disponibilidad. Contesta sólo «ok».", herramientas=False, nueva=True,
               persistir=False, trabajo="sonda", parar=lambda: time.monotonic() - t0 > SONDA_TOPE_S)
    except MotorCaido:
        return False
    except Exception:  # noqa: BLE001 — una sonda rota no puede decir «contesta»
        traceback.print_exc()
        return False
    return True


def _cuenta(con: sqlite3.Connection, clave: str) -> int:
    try:
        return max(0, int(memoria.leer(con, clave, 0) or 0))
    except (TypeError, ValueError):
        return 0


def acierto(con: sqlite3.Connection, clave: str) -> None:
    """El pedido de `clave` salió: se acaba la racha, si la había, y se
    olvida su cuenta de fallos «del motor» (la otra, la suya, es de quien llama)."""
    reanudar(con)
    memoria.quitar(con, f"{clave}:motor")


def rendirse(con: sqlite3.Connection, exc: MotorCaido, trabajo: str, clave: str, *, modelo: str | None = None,
             params: dict | None = None) -> bool:
    """Qué hacer cuando el modelo falla a quien reintenta solo un pedido (el
    triaje con un lote, el cierre con un hilo). True si hay que rendirse con
    ese pedido —apartarlo, cerrar sin resumen—; False si se reintenta en otra
    vuelta. `clave` es donde ese pedido lleva su cuenta de fallos (en
    `estado`); ponerla a cero al rendirse es de quien llama, y al acertar
    llama a `acierto`.

    - Lo que es del motor (`MotorNoDisponible`) no cuenta: se pausa.
    - Lo demás cuenta, y antes de llegar a `FALLOS_PARA_RENDIRSE` se sondea:
      si el motor no contesta, no era el pedido; se pausa y **su cuenta
      vuelve a cero**. Sin eso, lo fallado durante una caída sin clasificar
      (el uso agotado, la sesión sin iniciar) se quedaba sumado, y el primer
      fallo pasajero con el motor ya de vuelta apartaba un lote bueno.
    - Con una racha en curso se sondea en cada fallo, sin contar hasta tres:
      cada intento es ya uno por cada espera, no tres.
    - 🔴 Y al revés, cada `COMPROBAR_CADA` fallos «del motor» **de este
      pedido** (`clave:motor`; la racha es de todos y la borra el acierto de
      otro trabajo): si la sonda contesta, el malo es el pedido y ese fallo
      cuenta (regla dura 2).

    🔴 Riesgo conocido, sin arreglo: un pedido de verdad malo con una sonda
    que diga «no contesta» en falso no sale nunca de aquí, y lo que espera
    detrás no se atiende. Rendirse sin creer a la sonda reabriría la pérdida
    de mensajes en las caídas largas, que es peor; queda dicho en la bitácora
    (una línea por racha, y otra cada `REAPUNTAR_S`) y en el parte."""
    del_motor = f"{clave}:motor"
    if isinstance(exc, MotorNoDisponible):
        pausar(con, exc, trabajo)
        seguidos = _cuenta(con, del_motor) + 1
        memoria.poner(con, del_motor, seguidos)
        if seguidos % COMPROBAR_CADA or not responde(modelo):
            return False
        memoria.poner(con, del_motor, 0)
        reanudar(con)
    elif _racha(con) is not None or _cuenta(con, clave) + 1 >= FALLOS_PARA_RENDIRSE:
        if not responde(modelo):
            memoria.poner(con, clave, 0)
            pausar(con, exc, trabajo)
            return False
        reanudar(con)
    # Aquí, o el motor contesta, o es de los primeros fallos y aún no hace
    # falta saberlo: el fallo cuenta contra el pedido.
    intentos = _cuenta(con, clave) + 1
    memoria.poner(con, clave, intentos)
    memoria.apuntar(con, trabajo, params=params, resultado=str(exc), ok=False)
    if intentos < FALLOS_PARA_RENDIRSE:
        return False
    memoria.quitar(con, del_motor)
    return True


def soltar(sesion: str | None = None) -> None:
    for m in MOTORES.values():
        m.soltar(sesion)


def podar() -> None:
    for m in MOTORES.values():
        m.podar()
