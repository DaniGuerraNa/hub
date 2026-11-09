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
"""

from __future__ import annotations

import json
import math
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .. import config, tmux
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


class TopeAgotado(MotorCaido):
    """Llegó a su `tope_usd` antes de acabar. `coste`: lo que llevaba gastado."""

    def __init__(self, mensaje: str, coste: float = 0.0):
        super().__init__(mensaje)
        self.coste = coste


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
        raise MotorCaido(f"claude: {d.get('result') or d.get('terminal_reason') or 'error'}"[:400])
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
        self.p = subprocess.Popen(linea, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self._err,
                                  text=True, cwd=_trabajo(), env=entorno)
        threading.Thread(target=self._leer, daemon=True, name="motor-abierto").start()

    def _leer(self) -> None:
        for l in self.p.stdout:
            self.lineas.put(l)
        self.lineas.put(None)

    def vivo(self) -> bool:
        return self.p.poll() is None

    def turno(self, prompt: str | list[dict], tope: float, al_trozo: Callable[[str], None] | None = None,
              al_evento: Callable[[dict], None] | None = None) -> dict | None:
        """El evento `result` del turno, o None si el proceso murió antes.

        `prompt` es el texto o, con imágenes, la lista de bloques del mensaje
        (`_bloques`): van en el mismo proceso que el resto del hilo (383).

        Con `al_trozo`, el texto acumulado según llega (`--include-partial-messages`),
        como mucho cada `CADA_TROZO_S` salvo al cerrar una frase, y siempre una
        última vez entero. Se llama desde este hilo, el del turno: quien lo
        recibe escribe en su conexión de sqlite, que no se comparte entre hilos.
        `al_evento`, lo mismo con lo que va haciendo (`_Actividad`)."""
        texto, avisado = "", 0.0
        actividad = _Actividad(al_evento) if al_evento is not None else None
        recientes: deque = deque(maxlen=LINEAS_GUARDADAS)
        self.usado = t0 = time.monotonic()
        try:
            self.p.stdin.write(json.dumps({"type": "user", "message": {"role": "user", "content": prompt}},
                                          ensure_ascii=False) + "\n")
            self.p.stdin.flush()
        except OSError:
            return None
        fin = time.monotonic() + tope
        while True:
            queda = fin - time.monotonic()
            try:
                l = self.lineas.get(timeout=max(0.1, min(queda, SIN_NOTICIAS_S)))
            except queue.Empty:
                self.p.kill()
                if queda > SIN_NOTICIAS_S:
                    # Colgado: se repite por el camino de siempre (devuelve None).
                    self._volcar(f"{SIN_NOTICIAS_S} s sin decir nada: se mata y el turno se repite", recientes)
                    return None
                self._volcar(f"llegó al tope de {int(tope)} s", recientes)
                raise MotorCaido(f"el modelo no contestó en {int(tope)} s") from None
            if l is None:
                return None
            recientes.append((time.monotonic() - t0, l))
            try:
                d = json.loads(l)
            except ValueError:
                continue
            if actividad is not None:
                actividad.linea(d)
            if d.get("type") == "stream_event" and al_trozo is not None:
                ev = d.get("event") or {}
                if ev.get("type") == "message_start" and texto and not texto.endswith("\n"):
                    texto += "\n\n"   # otro mensaje tras una herramienta
                trozo = ((ev.get("delta") or {}).get("text") or "") if ev.get("type") == "content_block_delta" else ""
                if trozo:
                    texto += trozo
                    ahora = time.monotonic()
                    if ahora - avisado >= CADA_TROZO_S or trozo.rstrip()[-1:] in ".?!…:":
                        avisado = ahora
                        al_trozo(texto)
            if d.get("type") == "result":
                self.usado = time.monotonic()
                if d.get("is_error"):
                    motivo = memoria.ocultar_secretos(str(d.get("result") or ""))[:200]
                    self._volcar(f"dio error a los {time.monotonic() - t0:.0f} s ({d.get('terminal_reason') or '?'}:"
                                 f" {motivo})", recientes)
                if al_trozo is not None and texto:
                    al_trozo(texto)
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

    def cerrar(self) -> None:
        try:
            self.p.stdin.close()
        except OSError:
            pass
        try:
            self.p.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.p.kill()
            self.p.wait()
        self._err.close()


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
               nativas=(), tope_usd=None):
        entorno = {**os.environ, **CORTES_DE_RED, "PATH": tmux.path_de_usuario(), **entorno_extra}
        kw = dict(modelo=modelo, sistema=sistema, sesion=sesion, nueva=nueva, herramientas=herramientas,
                  esquema=esquema, esfuerzo=esfuerzo, entorno_extra=entorno_extra, persistir=persistir,
                  nativas=_nativas(nativas), tope_usd=_tope(tope_usd))
        if abierta and sesion and not esquema:
            # Sólo el proceso abierto da trozos; por los demás caminos llega entera.
            # Con imágenes también (decisión 383): saltárselo arrancaba otro
            # proceso con la misma sesión mientras éste seguía vivo, y nunca
            # puede haber dos escribiéndola (328). Se arman antes de tocar el
            # proceso: una imagen que no se puede mandar no lo tumba.
            contenido = _bloques(imagenes, prompt) if imagenes else prompt
            t0 = time.monotonic()
            r = self._en_abierto(contenido, entorno, kw, al_trozo, al_evento)
            if r is not None:
                return r
            perdidos = time.monotonic() - t0
            # Murió, calló o dio error de la API a mitad: la sesión ya existe y
            # se retoma. Si era su primer turno puede que no llegara a
            # guardarse, y entonces se crea.
            # Retomarla con el mismo mensaje hacía que el modelo lo leyera dos
            # veces y repitiera lo ya hecho —una tarjeta, una nota, un aviso—
            # (C-0185): va con el aviso del corte, y con el mensaje por si no
            # llegó a guardarse. Lo escrito del intento tirado ya no vale.
            if al_evento is not None:
                _Actividad(al_evento)._avisar({"tipo": "reintento"})   # adorno: no tumba el turno
            try:
                r = self.llamar(RETOMAR + prompt, **{**kw, "nueva": False}, abierta=False, imagenes=imagenes,
                                al_evento=al_evento)
            except MotorCaido:
                if not kw["nueva"]:
                    raise
                r = self.llamar(prompt, **kw, abierta=False, imagenes=imagenes, al_evento=al_evento)
            r.perdidos += perdidos
            return r
        if sesion:
            self.soltar(sesion)      # nunca dos procesos escribiendo la misma sesión
        if imagenes:
            return self._con_imagenes(prompt, imagenes, entorno, kw)
        linea, sesion = self._linea(entorno, **kw)
        if al_evento is not None and not esquema:
            return self._suelta(linea, prompt, entorno, sesion, kw["modelo"], al_evento)
        linea += ["--output-format", "json"]
        t0 = time.monotonic()
        try:
            r = subprocess.run(linea, input=prompt, capture_output=True, text=True, timeout=TOPE_SEGUNDOS,
                               cwd=_trabajo(), env=entorno)
        except subprocess.TimeoutExpired as exc:
            raise MotorCaido(f"el modelo no contestó en {TOPE_SEGUNDOS} s") from exc
        except OSError as exc:
            raise MotorCaido(f"no se pudo arrancar claude: {exc}") from exc
        try:
            d = json.loads(r.stdout)
        except ValueError as exc:
            raise MotorCaido(f"`claude -p` salió con {r.returncode}: {(r.stderr or r.stdout)[-400:]}") from exc
        return _respuesta(d, sesion, time.monotonic() - t0, modelo)

    def _suelta(self, linea, prompt, entorno, sesion, modelo, al_evento) -> Respuesta:
        """Una llamada de un solo uso que va contando lo que hace (C-0166).

        La del modelo mayor tras escalar, sobre todo: sin esto, el personaje se
        quedaba «pensando» mientras buscaba. `stream-json` en vez de `json`
        (pide `--verbose`), leído línea a línea y sin mensajes parciales: cada
        herramienta se avisa al llegar su mensaje entero."""
        linea = linea + ["--output-format", "stream-json", "--verbose"]
        actividad = _Actividad(al_evento)
        t0 = time.monotonic()
        with tempfile.TemporaryFile("w+", encoding="utf-8") as err:
            try:
                p = subprocess.Popen(linea, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=err,
                                     text=True, cwd=_trabajo(), env=entorno)
            except OSError as exc:
                raise MotorCaido(f"no se pudo arrancar claude: {exc}") from exc
            reloj = threading.Timer(TOPE_SEGUNDOS, p.kill)
            reloj.start()
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
                    actividad.linea(d)
                    if d.get("type") == "result":
                        resultado = d
                p.wait()
            finally:
                reloj.cancel()
            if resultado is None:
                if time.monotonic() - t0 >= TOPE_SEGUNDOS:
                    raise MotorCaido(f"el modelo no contestó en {TOPE_SEGUNDOS} s")
                err.seek(0)
                raise MotorCaido(f"`claude -p` salió con {p.returncode}: {err.read()[-400:]}")
        return _respuesta(resultado, sesion, time.monotonic() - t0, modelo)

    def _con_imagenes(self, prompt, imagenes, entorno, kw) -> Respuesta:
        """Una llamada suelta con imágenes: `-p` sólo admite texto por stdin,
        así que va como un mensaje de stream-json con sus bloques (decisión 335).
        Quien llama ya soltó el proceso abierto de esa sesión (328)."""
        bloques = _bloques(imagenes, prompt)
        linea, sesion = self._linea(entorno, **kw)
        linea += ["--input-format", "stream-json", "--output-format", "stream-json", "--verbose"]
        entrada = json.dumps({"type": "user", "message": {"role": "user", "content": bloques}}) + "\n"
        t0 = time.monotonic()
        try:
            r = subprocess.run(linea, input=entrada, capture_output=True, text=True, timeout=TOPE_SEGUNDOS,
                               cwd=_trabajo(), env=entorno)
        except subprocess.TimeoutExpired as exc:
            raise MotorCaido(f"el modelo no contestó en {TOPE_SEGUNDOS} s") from exc
        except OSError as exc:
            raise MotorCaido(f"no se pudo arrancar claude: {exc}") from exc
        for l in reversed(r.stdout.splitlines()):
            try:
                d = json.loads(l)
            except ValueError:
                continue
            if d.get("type") == "result":
                return _respuesta(d, sesion, time.monotonic() - t0, kw["modelo"])
        raise MotorCaido(f"`claude -p` salió con {r.returncode}: {(r.stderr or r.stdout)[-400:]}")

    def _en_abierto(self, prompt, entorno, kw, al_trozo=None, al_evento=None) -> Respuesta | None:
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
                    raise MotorCaido(f"no se pudo arrancar claude: {exc}") from exc
        t0 = time.monotonic()
        try:
            d = a.turno(prompt, TOPE_SEGUNDOS, al_trozo, al_evento)
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
        raise MotorCaido(f"`motor: {eleccion}` en secretario.yml no existe; los que hay: {', '.join(MOTORES)}")
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
           nativas: tuple[str, ...] = (), tope_usd: float | None = None) -> Respuesta:
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
    ellas: callarlas daría una investigación sin web o sin tope."""
    nativas, tope_usd = _nativas(nativas), _tope(tope_usd)
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
                            **({"tope_usd": tope_usd} if tope_usd is not None else {}))
    except MotorCaido as exc:
        # Lo gastado hasta el tope también se gastó (regla 13).
        memoria.apuntar_llamada(trabajo, modelo, time.monotonic() - t0, getattr(exc, "coste", 0.0), ok=False)
        raise
    if r.perdidos:
        memoria.apuntar_llamada(trabajo, modelo, r.perdidos, ok=False)
    memoria.apuntar_llamada(trabajo, modelo, r.segundos, r.coste, r.entrada, r.salida)
    return r


def soltar(sesion: str | None = None) -> None:
    for m in MOTORES.values():
        m.soltar(sesion)


def podar() -> None:
    for m in MOTORES.values():
        m.podar()
