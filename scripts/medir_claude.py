"""Re-mide contra la CLI `claude` instalada lo que el hub supone de ella (C-0327).

Cada versión de Claude Code puede cambiar el terreno que el hub lee —el glifo
del título, los diálogos, los eventos de stream-json, los códigos de salida—, y
nada avisa: un fallo raro del orquestador o del secretario tras actualizar
parece un bug del hub. Esto lo convierte en una tabla de pasa / falla / no
medido, con la versión delante.

🔴 **No reimplementa nada.** Cada medición llama a la puerta del hub
(`tui.detectar`, `entrega.panel_apto`, `motor.llamar`…) contra la CLI de
verdad: una marca o una expresión copiada aquí mediría la copia.

Tres niveles (`MEDICIONES`, lista cerrada; una suposición nueva sobre la CLI
entra con su medición aquí):

- **local** — sin red: `--version`, `--help` y la TUI en su pantalla de alta.
- **api-falsa** — contra una API falsa en `127.0.0.1`, puerto efímero y llave
  de relleno: casi todo se mide así, sin credenciales y sin cuota.
- **modelo** — sólo con `--con-modelo`: lo único que usa la sesión de quien lo
  corre, y sólo por `motor.llamar` sin persistir. Gasta.

🔴 **Aislamiento.** `HOME` y `HUB_HOME` temporales, un servidor de tmux propio
(`HUB_TMUX_SOCKET=hub-medir-<pid>`) y el entorno limpio de todo `CLAUDE*`,
`ANTHROPIC*` y `TMUX*` de quien lo corre. Las credenciales no se copian ni se
enlazan nunca (regla dura 5). Además el proxy apunta a la API falsa: lo que
la CLI intentara sacar a internet llega ahí, se rechaza y se apunta. Sólo
escribe en paneles por `entrega.entregar` y no contesta menús ni permisos:
mide que el hub los ve y mata su sesión. Una medición negativa lleva su
control positivo: si el control no pasa, es «no medido», nunca «pasa»
(regla dura 19).

Uso:
    uv run python scripts/medir_claude.py [--con-modelo] [--a-peticion ID] [--lentas]
        [--solo ID,…] [--claude RUTA] [--json]
Salida: 0 nada falla · 1 algo falla · 2 no se pudo medir (sin claude o sin tmux).
"""

from __future__ import annotations

import argparse
import ast
import contextlib
import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import uuid
import zlib
from dataclasses import asdict, dataclass, field
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable

RAIZ = Path(__file__).resolve().parents[1]
FUENTES = RAIZ / "src" / "hub"

# 🔴 Nada del hub se importa aquí arriba: `config` lee `HUB_HOME` al
# importarse, y tiene que leer el temporal del banco, no el de quien lo corre.


class Falla(Exception):
    """Lo medido contradice lo que el hub supone."""


class NoMedido(Exception):
    """No se pudo medir, o el control positivo no pasó: no se sabe."""


class SinClaude(RuntimeError):
    """No hay `claude` que medir."""


PASA, FALLA, NO_MEDIDO = "pasa", "falla", "no medido"
LOCAL, API_FALSA, MODELO, SIN_MEDIR = "local", "api-falsa", "modelo", "sin medir"


@dataclass(frozen=True)
class Medicion:
    id: str
    que: str
    #: «módulo.símbolo» del hub que depende de esto.
    supone: str
    nivel: str
    #: Lanza `Falla` o `NoMedido`; si vuelve, pasa. Lo que devuelva es el detalle.
    medir: Callable[["Banco"], str | None]
    lenta: bool = False


@dataclass
class Resultado:
    id: str
    que: str
    supone: str
    nivel: str
    estado: str
    detalle: str = ""


# ─────────────────────────────── la API falsa ───────────────────────────────

#: La marca que lleva cada mensaje de una medición. La API falsa contesta según
#: ella, y sólo ella dice qué petición es de qué medición.
_MARCA = re.compile(r"MEDIR-[A-Z0-9]+-[0-9a-f]{8}")


def nueva_marca(id_: str) -> str:
    return f"MEDIR-{id_}-{uuid.uuid4().hex[:8]}"


@dataclass
class Plan:
    """Lo que contesta la API falsa a una petición."""

    texto: str = ""
    herramienta: tuple[str, dict] | None = None
    #: El `usage` que declara. Por omisión, cifras reconocibles en el transcript.
    uso: dict = field(default_factory=lambda: {"input_tokens": 1234, "output_tokens": 56,
                                               "cache_creation_input_tokens": 0,
                                               "cache_read_input_tokens": 0})
    #: Si está, deja la respuesta a medias hasta que se ponga.
    retener: threading.Event | None = None
    #: Segundos sin mandar un solo byte (la API que calla, F15).
    callar: float = 0.0


@dataclass
class Peticion:
    ruta: str
    modelo: str
    stream: bool
    marca: str
    #: Trae resultados de herramienta: es la vuelta de un turno, no un turno nuevo.
    seguimiento: bool
    resultados: list[str]
    mensajes: int
    request_id: str
    t: float
    #: El `User-Agent`: dice qué versión de la CLI hizo la petición.
    agente: str = ""


class ApiFalsa:
    """Una API de mensajes de mentira, sólo en `127.0.0.1` y en un puerto efímero.

    Contesta en SSE como la de verdad. Lo que dice lo fija la medición con
    `preparar(marca, primero, despues)`: `primero` al turno que trae la marca,
    `despues` a la vuelta con el resultado de una herramienta. Hace también de
    proxy que no deja salir: un `CONNECT` se rechaza y se apunta en `salidas`.
    """

    HOST = "127.0.0.1"

    def __init__(self):
        self.peticiones: list[Peticion] = []
        self.salidas: list[str] = []
        self.otras: list[str] = []
        self._planes: dict[str, tuple[Plan | None, Plan | None]] = {}
        self._cerrojo = threading.Lock()
        self._cerrando = threading.Event()
        api = self

        class Manejador(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):
                pass

            def do_CONNECT(self):
                api.salidas.append(self.path)
                self._json(403, {"error": "la medición no sale a internet"})

            def do_GET(self):
                api.otras.append(f"GET {self.path}")
                self._json(404, {"type": "error", "error": {"type": "not_found_error", "message": "falsa"}})

            def do_POST(self):
                largo = int(self.headers.get("Content-Length") or 0)
                try:
                    cuerpo = json.loads(self.rfile.read(largo) or b"{}")
                except ValueError:
                    cuerpo = {}
                if "count_tokens" in self.path:
                    return self._json(200, {"input_tokens": 1234})
                if not self.path.startswith("/v1/messages"):
                    api.otras.append(f"POST {self.path}")
                    return self._json(404, {"type": "error", "error": {"type": "not_found_error",
                                                                      "message": "falsa"}})
                api._contestar(self, cuerpo)

            def _json(self, codigo, datos, cabeceras=None):
                b = json.dumps(datos).encode()
                self.send_response(codigo)
                self.send_header("Content-Type", "application/json")
                for k, v in (cabeceras or {}).items():
                    self.send_header(k, v)
                self.send_header("Content-Length", str(len(b)))
                self.end_headers()
                self.wfile.write(b)

        class Servidor(ThreadingHTTPServer):
            daemon_threads = True

            def handle_error(self, request, client_address):
                pass   # una conexión que la CLI corta a medias no es noticia

        self.srv = Servidor((self.HOST, 0), Manejador)
        self._hilo = threading.Thread(target=self.srv.serve_forever, daemon=True, name="api-falsa")
        self._hilo.start()

    @property
    def puerto(self) -> int:
        return self.srv.server_address[1]

    @property
    def url(self) -> str:
        return f"http://{self.HOST}:{self.puerto}"

    def preparar(self, marca: str, primero: Plan | None = None, despues: Plan | None = None) -> None:
        self._planes[marca] = (primero, despues)

    def con_marca(self, marca: str, *, seguimiento: bool | None = None) -> list[Peticion]:
        with self._cerrojo:
            return [p for p in self.peticiones if p.marca == marca
                    and (seguimiento is None or p.seguimiento == seguimiento)]

    def cerrar(self) -> None:
        self._cerrando.set()
        self.srv.shutdown()
        self.srv.server_close()

    # ── la respuesta ──

    @staticmethod
    def _textos(contenido) -> list[str]:
        if isinstance(contenido, str):
            return [contenido]
        textos = []
        for b in contenido or []:
            if not isinstance(b, dict):
                continue
            if b.get("type") == "text":
                textos.append(str(b.get("text") or ""))
            elif b.get("type") == "tool_result":
                textos += ApiFalsa._textos(b.get("content"))
        return textos

    def _contestar(self, h: BaseHTTPRequestHandler, cuerpo: dict) -> None:
        mensajes = cuerpo.get("messages") or []
        marca = ""
        # Del último mensaje del usuario hacia atrás: en una conversación de
        # varios turnos, las marcas de los anteriores siguen ahí delante.
        for m in reversed(mensajes):
            if m.get("role") != "user":
                continue
            # Y la última del mensaje: al retomar (`--resume`) tras un turno que
            # no contestó, la CLI junta los dos prompts en el mismo mensaje.
            halladas = _MARCA.findall("\n".join(self._textos(m.get("content"))))
            if halladas:
                marca = halladas[-1]
                break
        ultimo = mensajes[-1].get("content") if mensajes else ""
        resultados = ["\n".join(self._textos(b.get("content")))[:2000]
                      for b in (ultimo if isinstance(ultimo, list) else [])
                      if isinstance(b, dict) and b.get("type") == "tool_result"]
        seguimiento = bool(resultados)
        primero, despues = self._planes.get(marca, (None, None))
        plan = (despues if seguimiento else primero) or Plan(
            texto=f"Hecho tras la herramienta. {marca}" if seguimiento else f"Respuesta falsa. {marca}")
        request_id = "req_medir" + uuid.uuid4().hex[:16]
        with self._cerrojo:
            self.peticiones.append(Peticion(h.path, str(cuerpo.get("model") or ""), bool(cuerpo.get("stream")),
                                            marca, seguimiento, resultados, len(mensajes), request_id,
                                            time.monotonic(), h.headers.get("User-Agent") or ""))
        if plan.callar:
            # Las cabeceras y después nada, como la API falsa de C-0170: los
            # vigilantes de `CORTES_DE_RED` cuentan desde ahí. Sin cabeceras no
            # actúan (medido el 13-nov con 2.1.322: 4,5 min esperando).
            h.send_response(200)
            h.send_header("Content-Type", "text/event-stream")
            h.send_header("request-id", request_id)
            h.end_headers()
            h.wfile.flush()
            self._cerrando.wait(plan.callar)
            h.close_connection = True
            return
        modelo = str(cuerpo.get("model") or "falso")
        bloques: list[dict] = []
        if plan.texto:
            bloques.append({"type": "text", "text": plan.texto})
        if plan.herramienta:
            nombre, entrada = plan.herramienta
            bloques.append({"type": "tool_use", "id": "toolu_medir" + uuid.uuid4().hex[:12], "name": nombre,
                            "input": entrada})
        parada = "tool_use" if plan.herramienta else "end_turn"
        mid = "msg_medir" + uuid.uuid4().hex[:16]
        if not cuerpo.get("stream"):
            h._json(200, {"id": mid, "type": "message", "role": "assistant", "model": modelo, "content": bloques,
                          "stop_reason": parada, "stop_sequence": None, "usage": plan.uso},
                    {"request-id": request_id})
            return
        h.send_response(200)
        h.send_header("Content-Type", "text/event-stream")
        h.send_header("Cache-Control", "no-cache")
        h.send_header("request-id", request_id)
        h.send_header("Connection", "close")
        h.end_headers()
        h.close_connection = True

        def ev(tipo: str, datos: dict) -> None:
            h.wfile.write(f"event: {tipo}\ndata: {json.dumps(datos)}\n\n".encode())
            h.wfile.flush()

        try:
            ev("message_start", {"type": "message_start", "message": {
                "id": mid, "type": "message", "role": "assistant", "model": modelo, "content": [],
                "stop_reason": None, "stop_sequence": None,
                "usage": {**plan.uso, "output_tokens": 1}}})
            for i, b in enumerate(bloques):
                if b["type"] == "text":
                    ev("content_block_start", {"type": "content_block_start", "index": i,
                                               "content_block": {"type": "text", "text": ""}})
                    # En dos trozos: `al_trozo` tiene que acumularlos (F2).
                    mitad = len(b["text"]) // 2
                    for trozo in (b["text"][:mitad], b["text"][mitad:]):
                        ev("content_block_delta", {"type": "content_block_delta", "index": i,
                                                   "delta": {"type": "text_delta", "text": trozo}})
                        if plan.retener is not None and trozo:
                            # A medias, con `ping` como la de verdad mientras piensa.
                            while not plan.retener.wait(2) and not self._cerrando.is_set():
                                ev("ping", {"type": "ping"})
                            plan.retener = None
                else:
                    ev("content_block_start", {"type": "content_block_start", "index": i,
                                               "content_block": {**b, "input": {}}})
                    ev("content_block_delta", {"type": "content_block_delta", "index": i,
                                               "delta": {"type": "input_json_delta",
                                                         "partial_json": json.dumps(b["input"])}})
                ev("content_block_stop", {"type": "content_block_stop", "index": i})
            ev("message_delta", {"type": "message_delta", "delta": {"stop_reason": parada, "stop_sequence": None},
                                 "usage": {"output_tokens": plan.uso.get("output_tokens", 1)}})
            ev("message_stop", {"type": "message_stop"})
        except OSError:
            pass


class Escucha:
    """Un puerto en `127.0.0.1` que sólo cuenta quién llega (F6).

    No habla TLS ni HTTP: para saber si `WebFetch` salió hacia esta máquina
    basta con que la conexión llegue, y así no hace falta ningún certificado.
    """

    def __init__(self):
        self.llegadas = 0
        self._s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._s.bind(("127.0.0.1", 0))
        self._s.listen(8)
        self._s.settimeout(0.5)
        self._fin = threading.Event()
        threading.Thread(target=self._aceptar, daemon=True, name="escucha").start()

    @property
    def puerto(self) -> int:
        return self._s.getsockname()[1]

    def _aceptar(self) -> None:
        while not self._fin.is_set():
            try:
                c, _ = self._s.accept()
            except (TimeoutError, OSError):
                continue
            self.llegadas += 1
            c.close()

    def cerrar(self) -> None:
        self._fin.set()
        self._s.close()


# ─────────────────────────────────── el banco ───────────────────────────────

#: El modelo de las mediciones: el más barato de los del hub, por su alias.
def _modelo_barato() -> str:
    from hub import modelos
    return modelos.ALIAS["haiku"]


# Lo que se quita del entorno de quien corre esto antes de lanzar nada: su
# sesión de Claude (si lo corre desde una), sus llaves y su tmux.
_PREFIJOS_FUERA = ("CLAUDE", "ANTHROPIC", "TMUX")
_FUERA = {"HUB_TRANSCRIPTS", "HTTPS_PROXY", "HTTP_PROXY", "ALL_PROXY", "NO_PROXY",
          "https_proxy", "http_proxy", "all_proxy", "no_proxy"}


def resolver_claude(ruta: str | None = None) -> Path:
    """La CLI a medir, con su ruta absoluta y sin enlaces."""
    if ruta:
        p = Path(ruta).expanduser()
        if not (p.is_file() and os.access(p, os.X_OK)):
            raise SinClaude(f"«{ruta}» no es un ejecutable")
        return p.resolve()
    hallada = shutil.which("claude")
    if not hallada:
        raise SinClaude("no encuentro `claude` en el PATH")
    return Path(hallada).resolve()


class Banco:
    """Donde se mide: HOME y HUB_HOME temporales, tmux propio, API falsa.

    Cambia `os.environ` de este proceso —`config`, `motor`, `agentes` y
    `transcripts` leen de ahí— y `cerrar()` lo deja como estaba. Un solo
    `claude` vivo a la vez.
    """

    def __init__(self, claude: str | Path | None = None, *, con_modelo: bool = False):
        self.claude = resolver_claude(str(claude) if claude else None)
        if not shutil.which("tmux"):
            raise SinClaude("no encuentro `tmux`")
        self.con_modelo = con_modelo
        self.llave = "sk-ant-api03-relleno-para-medir-" + "0" * 40
        self._antes = dict(os.environ)
        self.tmp = Path(tempfile.mkdtemp(prefix="hub-medir-"))
        self.home = self.tmp / "home"
        self.hub_home = self.tmp / "hub-home"
        self.bin = self.tmp / "bin"
        for d in (self.home, self.hub_home, self.bin):
            d.mkdir()
        # El de la ruta pedida, con el nombre que buscan `motor` y la línea de
        # tmux. Un enlace al ejecutable, nada de la carpeta de quien lo corre.
        (self.bin / "claude").symlink_to(self.claude)
        self.socket = f"hub-medir-{os.getpid()}"
        self.api = ApiFalsa()
        self.version = ""
        self.a_peticion: tuple[str, ...] = ()
        self.cwd_turno: Path | None = None
        self._turno: tuple[str, str] | None = None
        self._panel: tuple[str, str, tuple] | None = None   # (sesion, pane, clave)
        self._n = 0
        self._config_antes: dict = {}
        self._aislar()

    # ── el entorno ──

    def _aislar(self) -> None:
        node = shutil.which("node")
        resto = [d for d in self._antes.get("PATH", "").split(os.pathsep) if d]
        ruta = [str(self.bin), *([str(Path(node).parent)] if node else []), *resto]
        for k in list(os.environ):
            if k.startswith(_PREFIJOS_FUERA) or k in _FUERA or k.startswith("XDG_"):
                del os.environ[k]
        os.environ.update({
            "HOME": str(self.home),
            "HUB_HOME": str(self.hub_home),
            "HUB_TMUX_SOCKET": self.socket,
            "PATH": os.pathsep.join(dict.fromkeys(ruta)),
            "ANTHROPIC_BASE_URL": self.api.url,
            "ANTHROPIC_API_KEY": self.llave,
            "DISABLE_AUTOUPDATER": "1",
            "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
            # Lo que intente salir por su cuenta pasa por la API falsa, que lo
            # rechaza y lo apunta; lo de `127.0.0.1` va directo.
            "HTTPS_PROXY": self.api.url,
            "HTTP_PROXY": self.api.url,
            "NO_PROXY": "127.0.0.1,localhost",
            "XDG_CONFIG_HOME": str(self.home / ".config"),
            "XDG_CACHE_HOME": str(self.home / ".cache"),
            "XDG_DATA_HOME": str(self.home / ".local" / "share"),
            "XDG_STATE_HOME": str(self.home / ".local" / "state"),
        })
        from hub import config, tmux
        self._config_antes = {k: getattr(config, k) for k in ("HUB_HOME", "DB_PATH", "HUB_KITS")}
        config.HUB_HOME, config.DB_PATH, config.HUB_KITS = (self.hub_home, self.hub_home / "hub.db",
                                                            self.hub_home / "kits")
        if tmux.orden_base()[:3] != ["tmux", "-L", self.socket]:
            self.cerrar()
            raise RuntimeError(f"tmux no va a su servidor aparte ({tmux.orden_base()}): no se mide")
        self.comprobar()

    def comprobar(self) -> None:
        """Antes de cada lanzamiento: HOME temporal, API en 127.0.0.1, tmux propio."""
        home = Path(os.environ.get("HOME", "")).resolve()
        if self.tmp.resolve() not in home.parents:
            raise RuntimeError(f"HOME no es el temporal ({home}): no se lanza")
        if not os.environ.get("ANTHROPIC_BASE_URL", "").startswith(f"http://{ApiFalsa.HOST}:"):
            raise RuntimeError("ANTHROPIC_BASE_URL no apunta a 127.0.0.1: no se lanza")
        if os.environ.get("HUB_TMUX_SOCKET") != self.socket:
            raise RuntimeError("HUB_TMUX_SOCKET no es el del banco: no se lanza")
        if (home / ".claude" / ".credentials.json").exists():
            raise RuntimeError("hay credenciales en el HOME temporal: no se lanza")

    @contextlib.contextmanager
    def con_la_sesion_de_quien_lo_corre(self):
        """Sólo `--con-modelo`: su HOME (su sesión de Claude) para `motor.llamar`.

        Nada más: `HUB_HOME` sigue siendo el temporal, la API la de verdad, y
        ninguna TUI corre nunca así.
        """
        if not self.con_modelo:
            raise RuntimeError("el nivel con modelo va con --con-modelo")
        guardado = dict(os.environ)
        for k in ("ANTHROPIC_BASE_URL", "ANTHROPIC_API_KEY", "HTTPS_PROXY", "HTTP_PROXY", "NO_PROXY"):
            os.environ.pop(k, None)
        os.environ["HOME"] = self._antes.get("HOME", "")
        if self._antes.get("CLAUDE_CONFIG_DIR"):
            os.environ["CLAUDE_CONFIG_DIR"] = self._antes["CLAUDE_CONFIG_DIR"]
        try:
            yield
        finally:
            os.environ.clear()
            os.environ.update(guardado)

    def llamar(self, prompt: str, **kw):
        """`motor.llamar` contra la API falsa, comprobado antes de lanzar."""
        from hub.secretario import motor
        self.comprobar()
        kw.setdefault("modelo", _modelo_barato())
        kw.setdefault("herramientas", False)
        kw.setdefault("persistir", False)
        return motor.llamar(prompt, trabajo="medir", **kw)

    # ── los paneles ──

    def _sembrar(self) -> None:
        """Lo que la CLI escribe en `~/.claude.json` al pasar el alta.

        Visto el 13-nov con 2.1.322 en un HOME temporal, pasando el alta a
        mano una vez: tras elegir tema y aceptar la llave, `hasCompletedOnboarding`,
        `lastOnboardingVersion` y la llave aprobada por sus 20 últimos
        caracteres. Nada más ni copiado de ningún sitio. Si una versión pide
        otra cosa, la TUI no arranca y F8 lo dice.
        """
        conf = self.home / ".claude.json"
        try:
            datos = json.loads(conf.read_text(encoding="utf-8")) if conf.exists() else {}
        except (OSError, ValueError):
            datos = {}
        datos.update(hasCompletedOnboarding=True, lastOnboardingVersion=self.version or "0.0.0",
                     customApiKeyResponses={"approved": [self.llave[-20:]], "rejected": []})
        conf.write_text(json.dumps(datos), encoding="utf-8")

    def panel(self, *, confiada: bool = True, alta: bool = False) -> str:
        """Un `claude` en su panel, lanzado como lo lanza el hub.

        `alta`: en un HOME nuevo sin sembrar, o sea en la pantalla de alta de
        quien nunca la pasó. Con la llave de relleno: sin ninguna, lo primero
        que hace la TUI es comprobar que llega a api.anthropic.com (medido el
        13-nov: con el proxy cortado sale con «Unable to connect»), y la
        medición no sale a internet. Si no es `alta`, en el HOME sembrado y
        con la carpeta confiada por `agentes.confiar` (o sin confiar).
        """
        from hub import agentes, asistente, modelos, tmux
        clave = (confiada, alta)
        if self._panel and self._panel[2] == clave:
            return self._panel[1]
        self.cerrar_panel()
        self.comprobar()
        self._n += 1
        cwd = self.tmp / f"trabajo-{self._n}"
        cwd.mkdir()
        entorno: dict[str, str] = {}
        if alta:
            home = self.tmp / f"home-alta-{self._n}"
            home.mkdir()
            entorno = {"HOME": str(home)}
        else:
            self._sembrar()
            if confiada:
                agentes.confiar(cwd)
        linea = modelos.linea_claude(_modelo_barato())
        sesion = f"medir-{self._n}"
        tmux.nueva_sesion(sesion, ruta=str(cwd), comando=linea.comando, entorno={**linea.entorno, **entorno},
                          conservar=True)
        pane = tmux.panel_de_sesion(sesion)
        self._panel = (sesion, pane, clave)
        self.cwd_turno = cwd
        # Que lo que corre en el panel sea la CLI medida y no otra del PATH
        # del servidor de tmux: si no, se mediría otra versión sin decirlo.
        pid = esperar(lambda: tmux.pid_del_panel(pane), 5)
        try:
            exe = Path(f"/proc/{pid}/exe").resolve() if pid else None
        except OSError:
            exe = None
        if exe is not None and exe.exists() and exe != self.claude:
            raise NoMedido(f"el panel corre {exe}, no la CLI medida")
        # Hasta que pinta algo: el cuadro, un menú o la pantalla de alta.
        if not esperar(lambda: asistente.listo(pane) or asistente.menu_abierto(tmux.capturar_panel(pane)), 25):
            if alta:
                return pane
            pantalla = _ultimas(tmux.capturar_panel(pane))
            raise NoMedido(f"la TUI no arrancó sin el alta en un HOME sembrado (pide sesión iniciada): {pantalla}")
        return pane

    def cerrar_panel(self) -> None:
        from hub import tmux
        if not self._panel:
            return
        sesion, pane, _ = self._panel
        self._panel = None
        self._turno = None
        try:
            pid = tmux.pid_del_panel(pane)
        except Exception:  # noqa: BLE001 — sin pid, se mata la sesión igual
            pid = None
        try:
            tmux.matar_sesion(sesion)
        except Exception as exc:  # noqa: BLE001 — se dice, no se calla (regla dura 21)
            print(f"medir_claude: no pude matar la sesión {sesion}: {exc}", file=sys.stderr)
        # Por su pid y sólo el suyo, si sobrevivió al cierre del panel.
        if pid and not esperar(lambda: not _vivo(pid), 5):
            with contextlib.suppress(ProcessLookupError, PermissionError):
                os.kill(pid, signal.SIGKILL)

    def cerrar(self) -> None:
        with contextlib.suppress(Exception):
            from hub.secretario import motor
            motor.soltar()
        with contextlib.suppress(Exception):
            self.cerrar_panel()
        if self._config_antes:
            from hub import config
            for k, v in self._config_antes.items():
                setattr(config, k, v)
        os.environ.clear()
        os.environ.update(self._antes)
        with contextlib.suppress(Exception):
            self.api.cerrar()
        # tmux deja el archivo de su socket aunque el servidor se vaya.
        zocalo = Path(self._antes.get("TMUX_TMPDIR") or "/tmp") / f"tmux-{os.getuid()}" / self.socket
        zocalo.unlink(missing_ok=True)
        shutil.rmtree(self.tmp, ignore_errors=True)


def _vivo(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    # Un zombi también responde a la señal 0: muerto a efectos de esto.
    try:
        return Path(f"/proc/{pid}/stat").read_text().split(")")[-1].split()[0] != "Z"
    except OSError:
        return False


def esperar(cond: Callable[[], object], segundos: float, cada: float = 0.25):
    """Hasta que `cond()` dé algo verdadero; lo devuelve, o None al agotarse."""
    fin = time.monotonic() + segundos
    while True:
        try:
            r = cond()
        except Exception:  # noqa: BLE001 — una lectura que falla es «todavía no»
            r = None
        if r:
            return r
        if time.monotonic() >= fin:
            return None
        time.sleep(cada)


def _ultimas(pantalla: str, n: int = 3) -> str:
    lineas = [l.strip() for l in pantalla.splitlines() if l.strip()]
    return " / ".join(lineas[-n:])[:300] or "(pantalla vacía)"


# ───────────────────────────── las mediciones ───────────────────────────────


def version(claude: str) -> str:
    """`X.Y.Z` de `claude --version`, o "" si no lo dice."""
    try:
        r = subprocess.run([str(claude), "--version"], capture_output=True, text=True, timeout=60,
                           stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    m = re.search(r"\b(\d+\.\d+\.\d+)\b", r.stdout or "")
    return m.group(1) if m else ""


def _l1(b: Banco) -> str:
    v = version(str(b.bin / "claude"))
    if not v:
        raise Falla("`claude --version` no da X.Y.Z")
    return v


def banderas_del_hub() -> set[str]:
    """Las banderas de `claude` que escribe el hub: las de `motor.py` y `modelos.py`.

    Leídas de su código, no copiadas aquí: una bandera nueva en el motor entra
    sola en la medición. Los docstrings no cuentan (ahí se nombran también las
    que no sirven, como `--bare`).
    """
    banderas: set[str] = set()
    for archivo in (FUENTES / "secretario" / "motor.py", FUENTES / "modelos.py"):
        arbol = ast.parse(archivo.read_text(encoding="utf-8"))
        docstrings = {id(n.body[0].value) for n in ast.walk(arbol)
                      if isinstance(n, (ast.Module, ast.FunctionDef, ast.ClassDef, ast.AsyncFunctionDef))
                      and n.body and isinstance(n.body[0], ast.Expr)
                      and isinstance(n.body[0].value, ast.Constant)}
        for n in ast.walk(arbol):
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docstrings:
                banderas |= set(re.findall(r"(?<![\w-])--[a-zA-Z][\w-]*", n.value))
    return banderas


def _l2(b: Banco) -> str:
    r = subprocess.run([str(b.bin / "claude"), "--help"], capture_output=True, text=True, timeout=60,
                       stdin=subprocess.DEVNULL)
    ayuda = (r.stdout or "") + (r.stderr or "")
    if r.returncode != 0 or "--" not in ayuda:
        raise Falla(f"`claude --help` salió con {r.returncode}")
    banderas = sorted(banderas_del_hub())
    faltan = [x for x in banderas if not re.search(rf"(?<![\w-]){re.escape(x)}(?![\w-])", ayuda)]
    # Una que falte en la ayuda es aviso, no fallo: hay banderas que funcionan
    # sin salir ahí, y lo que importa de cada una lo miden las de la API falsa.
    if faltan:
        return f"{len(banderas) - len(faltan)} de {len(banderas)} en la ayuda; no salen: {', '.join(faltan)}"
    return f"las {len(banderas)} salen en la ayuda"


def _l3(b: Banco) -> str:
    from hub import tmux, tui
    # En el HOME sembrado: arrancar ahí no pide nada a nadie (la pantalla de
    # alta sí, ver L4), así que esto sigue siendo local.
    pane = b.panel(confiada=True)
    comando = esperar(lambda: tmux.comando_de_panel(pane) == "claude" and "claude", 10)
    agente = tui.detectar(pane)
    if not comando:
        raise Falla(f"el panel dice «{tmux.comando_de_panel(pane)}», no «claude»")
    if agente is not tui.CLAUDE:
        raise Falla(f"`tui.detectar` da {agente}")
    return "pane_current_command=claude"


def _l4(b: Banco) -> str:
    from hub import entrega, tmux, tui
    pane = b.panel(alta=True)
    esperar(lambda: tmux.capturar_panel(pane).strip(), 15)
    time.sleep(1.5)   # que termine de pintar
    if tmux.panel_muerto(pane):
        pantalla = _ultimas(tmux.capturar_panel(pane), 12)
        b.cerrar_panel()
        if "Unable to connect" in pantalla:
            # Medido el 13-nov con 2.1.322: antes del selector de tema
            # comprueba que llega a api.anthropic.com, y aquí no sale nada.
            raise NoMedido("la pantalla de alta comprueba antes que llega a api.anthropic.com, y la medición "
                           "no sale a internet")
        raise NoMedido(f"la TUI se cerró en el alta: {pantalla}")
    if tui.detectar(pane) is not tui.CLAUDE:
        raise NoMedido("el panel no es un Claude que el hub reconozca: la negativa no diría nada")
    apto, motivo = entrega.panel_apto(pane)
    pantalla = _ultimas(tmux.capturar_panel(pane), 4)
    b.cerrar_panel()
    if apto:
        raise Falla(f"en la pantalla de alta `panel_apto` da apto: pegaría ahí. Pantalla: {pantalla}")
    return motivo


def _f1(b: Banco) -> str:
    from hub import modelos
    marca = nueva_marca("F1")
    r = b.llamar(marca)
    if marca not in r.texto:
        raise Falla(f"`result` no trae la respuesta de la API falsa: {r.texto[:120]!r}")
    if not modelos.es_sesion(r.sesion):
        raise Falla(f"`session_id` no es un id de conversación: {r.sesion!r}")
    if not r.coste > 0:
        raise Falla("`total_cost_usd` no llegó o vale 0")
    if (r.entrada, r.salida) != (1234, 56):
        raise Falla(f"el `usage` no casa con el de la API falsa: entrada {r.entrada}, salida {r.salida}")
    # Que la llamada del motor la hiciera la CLI medida y no otra del PATH de
    # usuario (`motor._claude`): lo dice su `User-Agent`.
    agentes = {p.agente for p in b.api.con_marca(marca)}
    if b.version and not any(b.version in a for a in agentes):
        raise NoMedido(f"el motor lanzó otra CLI: {sorted(agentes)}")
    return f"coste {r.coste:.6f}, sesión {r.sesion[:8]}…"


def _f2(b: Banco) -> str:
    marca = nueva_marca("F2")
    b.api.preparar(marca, primero=Plan(texto="Miro. ", herramienta=("mcp__secretario__buscar", {"texto": "x"})),
                   despues=Plan(texto=f"Primera parte. Segunda parte {marca}."))
    trozos: list[str] = []
    eventos: list[dict] = []
    r = b.llamar(marca, al_trozo=trozos.append, al_evento=eventos.append)
    tipos = [e.get("tipo") for e in eventos]
    if not trozos:
        raise Falla("`al_trozo` no recibió nada: no llegan `stream_event` / `content_block_delta`")
    if f"Segunda parte {marca}." not in trozos[-1] or "Miro." not in trozos[-1]:
        raise Falla(f"`al_trozo` no acumula los dos mensajes (`message_start`): {trozos[-1]!r}")
    if not any(e.get("tipo") == "herramienta" and e.get("nombre") == "buscar" for e in eventos):
        raise Falla(f"`al_evento` no vio la herramienta (`content_block_start` de tool_use): {tipos}")
    if "fin_herramienta" not in tipos:
        raise Falla(f"`al_evento` no vio el `tool_result`: {tipos}")
    if marca not in r.texto:
        raise Falla(f"la respuesta final no es la de la API falsa: {r.texto[:120]!r}")
    return f"{len(trozos)} trozos; eventos {sorted(set(tipos))}"


def _f3(b: Banco) -> str:
    from hub.secretario import motor
    sesion = str(uuid.uuid4())
    m1, m2 = nueva_marca("F3"), nueva_marca("F3")
    r1 = b.llamar(m1, sesion=sesion, nueva=True, abierta=True, persistir=True)
    abierto = motor.MOTORES["suscripcion"]._abiertos.get(sesion)
    if abierto is None:
        raise NoMedido("el motor no dejó el proceso abierto tras el primer turno")
    pid = abierto.p.pid
    r2 = b.llamar(m2, sesion=sesion, abierta=True, persistir=True)
    despues = motor.MOTORES["suscripcion"]._abiertos.get(sesion)
    motor.soltar(sesion)
    if m1 not in r1.texto or m2 not in r2.texto:
        raise Falla("algún turno no trae la respuesta de la API falsa")
    if despues is None or despues.p.pid != pid or r2.perdidos:
        raise Falla("el segundo turno no fue en el mismo proceso")
    segunda = b.api.con_marca(m2)
    if not any(p.mensajes >= 3 for p in segunda):
        raise Falla("el segundo turno no llevó el primero en su conversación")
    return f"pid {pid} en los dos turnos"


def _f4(b: Banco) -> str:
    from hub.secretario import motor
    marca = nueva_marca("F4")
    # Un turno caro que pide otra vuelta: el tope se mira entre turno y turno.
    caro = {"input_tokens": 1234, "output_tokens": 4_000_000, "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0}
    b.api.preparar(marca, primero=Plan(texto="Sigo.", herramienta=("mcp__secretario__buscar", {"texto": "x"}),
                                       uso=caro))
    try:
        r = b.llamar(marca, tope_usd=0.01)
    except motor.TopeAgotado as exc:
        if not exc.coste > 0.01:
            raise Falla(f"`TopeAgotado` sin el coste gastado ({exc.coste})") from None
        return f"TopeAgotado con {exc.coste:.2f} USD"
    except motor.MotorCaido as exc:
        raise Falla(f"no da `error_max_budget_usd`: {exc}") from None
    raise Falla(f"pasó del tope sin cortar: contestó «{r.texto[:80]}» con {r.coste:.2f} USD")


def _ruta_motor(b: Banco, **kw) -> tuple[list[str], dict]:
    """La línea que arma el motor y el entorno con que la lanza: para los
    controles, que cambian una sola cosa de ella."""
    from hub import tmux
    from hub.secretario import motor
    entorno = {**os.environ, **motor.CORTES_DE_RED, "PATH": tmux.path_de_usuario()}
    base = dict(modelo=_modelo_barato(), sistema=None, sesion=None, nueva=True, herramientas=False, esquema=None,
                esfuerzo=None, entorno_extra={}, persistir=False, nativas=(), tope_usd=None)
    linea, _ = motor.Suscripcion()._linea(entorno, **{**base, **kw})
    return linea, entorno


def _control(b: Banco, linea: list[str], entorno: dict, prompt: str) -> dict:
    from hub.secretario import motor
    b.comprobar()
    r = motor._correr(linea + ["--output-format", "json"], prompt, entorno)
    try:
        return json.loads(r.stdout)
    except ValueError:
        raise NoMedido(f"el control no dio JSON (salió con {r.returncode}): {(r.stderr or r.stdout)[-200:]}") from None


def _f5(b: Banco) -> str:
    def plan(archivo: Path) -> tuple[Plan, Plan]:
        return Plan(herramienta=("Bash", {"command": f"touch {archivo}", "description": "medir"})), Plan(texto="ok")
    sin, con = b.tmp / "f5-sin-herramientas", b.tmp / "f5-control"
    # El control: la misma línea del motor con Bash permitido. Si ahí no corre,
    # que no corra con `--tools ""` no diría nada.
    m_control = nueva_marca("F5")
    b.api.preparar(m_control, *plan(con))
    linea, entorno = _ruta_motor(b)
    i = linea.index("--tools")
    linea[i + 1] = "Bash"
    _control(b, linea + ["--allowedTools", "Bash"], entorno, m_control)
    if not con.exists():
        raise NoMedido("el control no corrió el Bash que pidió la API falsa: no se puede medir el corte")
    marca = nueva_marca("F5")
    b.api.preparar(marca, *plan(sin))
    b.llamar(marca)
    if sin.exists():
        raise Falla("con `--tools \"\"` se ejecutó el Bash que pidió la API")
    vuelta = b.api.con_marca(marca, seguimiento=True)
    return f"no se ejecutó; la CLI contestó «{(vuelta[0].resultados[0] if vuelta else '')[:80]}»"


def _f6(b: Banco) -> str:
    """El control es la misma línea sin `--disallowedTools`.

    Que sin la lista *llegue* a 127.0.0.1 no se puede ver aquí: antes de leer,
    `WebFetch` pregunta a claude.ai si el dominio es seguro, y esa pregunta la
    corta el proxy (medido el 13-nov con 2.1.322: «Unable to verify if domain
    127.0.0.1 is safe to fetch»). Lo que sí se ve es lo que se mide: sin la
    lista el permiso lo deja pasar —se para después, en esa pregunta— y con
    ella lo niega el permiso, sin preguntar a nadie ni conectar.
    """
    escucha = Escucha()
    try:
        def plan(ruta: str) -> tuple[Plan, Plan]:
            return (Plan(herramienta=("WebFetch", {"url": f"https://127.0.0.1:{escucha.puerto}/{ruta}",
                                                   "prompt": "Resume la página."})), Plan(texto="ok"))

        def vuelta(marca: str) -> str:
            v = b.api.con_marca(marca, seguimiento=True)
            return v[0].resultados[0] if v and v[0].resultados else ""

        negado = re.compile(r"denied", re.I)
        m_control = nueva_marca("F6")
        b.api.preparar(m_control, *plan("control"))
        linea, entorno = _ruta_motor(b, nativas=("WebFetch",))
        i = linea.index("--disallowedTools")
        del linea[i:i + 2]
        _control(b, linea, entorno, m_control)
        control = vuelta(m_control)
        esperar(lambda: escucha.llegadas, 2)
        if not control or (negado.search(control) and not escucha.llegadas):
            raise NoMedido(f"sin `NO_LEER` el WebFetch también se niega o no vuelve: «{control[:120]}»")
        antes = escucha.llegadas
        marca = nueva_marca("F6")
        b.api.preparar(marca, *plan("medida"))
        b.llamar(marca, nativas=("WebFetch",))
        time.sleep(1)
        medida = vuelta(marca)
        if escucha.llegadas > antes:
            raise Falla("con `NO_LEER` el WebFetch llegó igual a 127.0.0.1")
        if not negado.search(medida):
            raise Falla(f"con `NO_LEER` el permiso no lo negó: «{medida[:120]}»")
        sin = "llegó" if escucha.llegadas else "pasa el permiso (no llega: la pregunta a claude.ai no sale de aquí)"
        return f"«{medida.splitlines()[0][:60]}»; sin la lista {sin}"
    finally:
        escucha.cerrar()


def _f7(b: Banco) -> str:
    from hub import modelos
    from hub.secretario import motor
    rechazados = []
    for modelo in sorted(modelos.PERMITIDOS | modelos.A_PETICION):
        marca = nueva_marca("F7")
        try:
            b.llamar(marca, modelo=modelo)
        except motor.MotorCaido as exc:
            rechazados.append(f"{modelo} ({str(exc)[:80]})")
            continue
        if not any(p.modelo == modelo for p in b.api.con_marca(marca)):
            rechazados.append(f"{modelo} (no llegó con ese id)")
    if rechazados:
        raise Falla("la CLI no los manda a la API: " + "; ".join(rechazados))
    return f"{len(modelos.PERMITIDOS | modelos.A_PETICION)} ids llegan"


def _f8(b: Banco) -> str:
    from hub import asistente, entrega, tmux, tui
    pane = b.panel(confiada=True)
    pantalla = tmux.capturar_panel(pane)
    if asistente.menu_abierto(pantalla):
        raise Falla(f"con la carpeta confiada sale un diálogo: {_ultimas(pantalla)}")
    if not asistente.listo(pane):
        raise Falla("`asistente.listo` no lo ve listo")
    if tui.cuadro(tui.CLAUDE, pane):
        raise Falla(f"el cuadro no está vacío: {tui.cuadro(tui.CLAUDE, pane)!r}")
    apto, motivo = entrega.panel_apto(pane)
    if not apto:
        raise Falla(f"`panel_apto` no lo da por apto: {motivo}")
    titulo = tmux.titulo_panel(pane) or ""
    return "listo, sin diálogo, cuadro vacío" + ("" if tmux.tiene_glifo_estado(titulo)
                                                 else "; el título no lleva glifo hasta el primer turno")


def turno(b: Banco, marca: str, retener: threading.Event | None = None) -> str:
    """Un mensaje de varias líneas por `entrega.entregar` al panel confiado."""
    from hub import entrega
    pane = b.panel(confiada=True)
    if retener is not None:
        b.api.preparar(marca, primero=Plan(texto=f"Pienso despacio y contesto. {marca}", retener=retener))
    entrega.entregar(pane, f"{marca}\nsegunda línea del mensaje\ntercera línea del mensaje")
    return pane


def _respondido(b: Banco, pane: str, marca: str) -> bool:
    from hub import tmux, tui
    return (bool(b.api.con_marca(marca)) and f"Respuesta falsa. {marca}" in tmux.capturar_panel(pane, unir_lineas=True)
            and not tui.ocupado(tui.CLAUDE, pane))


def _turno_hecho(b: Banco) -> tuple[str, str]:
    """El panel confiado con al menos un turno acabado (para F13 y F14)."""
    if b._turno and b._panel and b._panel[1] == b._turno[0]:
        return b._turno
    from hub import entrega
    marca = nueva_marca("T")
    try:
        pane = turno(b, marca)
    except entrega.PanelNoApto as exc:
        raise NoMedido(f"no se pudo completar un turno: {exc}") from None
    if not esperar(lambda: _respondido(b, pane, marca), 30):
        raise NoMedido("el turno no acabó en 30 s")
    b._turno = (pane, marca)
    return b._turno


def _f10(b: Banco) -> str:
    from hub import entrega, tmux
    marca = nueva_marca("F10")
    try:
        pane = turno(b, marca)
    except entrega.EscritoSinConfirmar as exc:
        raise Falla(f"`entregar` lanzó EscritoSinConfirmar: {exc}") from None
    except entrega.PanelNoApto as exc:
        raise NoMedido(f"el panel no estaba apto: {exc}") from None
    if not esperar(lambda: _respondido(b, pane, marca), 30):
        raise Falla("la respuesta no llegó a la pantalla en 30 s")
    time.sleep(2)
    n = len(b.api.con_marca(marca))
    if n != 1:
        raise Falla(f"la API falsa recibió {n} peticiones de un solo mensaje (regla dura 17)")
    b._turno = (pane, marca)
    titulo = tmux.titulo_panel(pane) or ""
    if not tmux.tiene_glifo_estado(titulo) or tmux.es_spinner(titulo):
        raise Falla(f"tras el turno el título no lleva el glifo de reposo: {titulo!r}")
    return f"una petición; título en reposo «{titulo[:20]}»"


def _f11(b: Banco) -> str:
    from hub import entrega, tui
    pane = b.panel(confiada=True)
    if tui.ocupado(tui.CLAUDE, pane) or not entrega.panel_apto(pane)[0]:
        raise NoMedido("antes de retener la respuesta, el panel ya no estaba libre")
    soltar = threading.Event()
    marca = nueva_marca("F11")
    try:
        turno(b, marca, retener=soltar)
        if not esperar(lambda: b.api.con_marca(marca), 15):
            raise NoMedido("el mensaje no llegó a la API falsa")
        ocupado = esperar(lambda: tui.ocupado(tui.CLAUDE, pane), 15)
        apto, motivo = entrega.panel_apto(pane)
    finally:
        soltar.set()
    if not ocupado:
        raise Falla("con la respuesta retenida `tui.ocupado` no lo ve trabajando")
    if apto or "trabajando" not in motivo:
        raise Falla(f"con la respuesta retenida `panel_apto` dice {apto, motivo}")
    if not esperar(lambda: not tui.ocupado(tui.CLAUDE, pane) and entrega.panel_apto(pane)[0], 30):
        raise Falla("al soltar la respuesta no vuelve a estar libre")
    return f"ocupado mientras retenida («{motivo}»); libre al soltarla"


def _f12(b: Banco) -> str:
    from hub import asistente, entrega, tmux
    pane = b.panel(confiada=True)
    if not entrega.panel_apto(pane)[0]:
        raise NoMedido("el panel no estaba apto antes del permiso: la negativa no diría nada")
    archivo = b.tmp / "f12-no-se-aprueba"
    marca = nueva_marca("F12")
    b.api.preparar(marca, primero=Plan(herramienta=("Bash", {"command": f"touch {archivo}",
                                                             "description": "medir"})))
    entrega.entregar(pane, marca)
    viendo = esperar(lambda: asistente.esperando_confirmacion(pane), 20)
    apto, motivo = entrega.panel_apto(pane)
    pantalla = _ultimas(tmux.capturar_panel(pane), 5)
    # No se contesta: el panel queda con su diálogo y se mata.
    b.cerrar_panel()
    if archivo.exists():
        raise Falla("el Bash se ejecutó sin que nadie lo aprobara")
    if not viendo:
        raise Falla(f"`esperando_confirmacion` no ve el permiso del Bash: {pantalla}")
    if apto:
        raise Falla("con el permiso abierto `panel_apto` da apto")
    # Niega, que es lo que importa. Por qué rama lo dice se apunta: el cuadro
    # de permisos lleva «Esc to cancel», que es marca de menú, así que niega
    # antes de llegar a la de permisos.
    return f"niega: «{motivo}»"



def _f9(b: Banco) -> str:
    from hub import asistente, entrega, tmux
    pane = b.panel(confiada=False)
    if not esperar(lambda: asistente.menu_abierto(tmux.capturar_panel(pane)), 10):
        b.cerrar_panel()
        raise Falla("con la carpeta sin confiar no sale el diálogo de confianza")
    apto, motivo = entrega.panel_apto(pane)
    b.cerrar_panel()
    if apto:
        raise Falla("con el diálogo de confianza abierto `panel_apto` da apto")
    if "confías en la carpeta" not in motivo:
        raise Falla(f"niega, pero no nombra el menú: {motivo}")
    return motivo


def _f13(b: Banco) -> str:
    from hub import transcripts
    from hub.orquestador import ficha
    pane, marca = _turno_hecho(b)
    sesion = ficha(pane).get("session_id")
    directorio = transcripts.directorio_de(str(b.cwd_turno))
    ruta = transcripts.ruta_de_sesion(sesion or "", [directorio])
    if ruta is None:
        hay = sorted(p.name for p in transcripts.raiz().glob("*")) if transcripts.raiz().is_dir() else []
        raise Falla(f"no está en `{directorio.name}` (slug_de); en la raíz hay {hay}")
    emitidos = {p.request_id for p in b.api.peticiones}
    asistentes = [d for d in transcripts.leer_lineas(ruta) if d.get("type") == "assistant"]
    if not asistentes:
        raise Falla("el transcript no tiene líneas `type: assistant`")
    if not any(d.get("requestId") in emitidos for d in asistentes):
        raise Falla("ninguna línea `assistant` lleva el `requestId` que dio la API")
    ocupacion = transcripts.ultima_ocupacion(ruta)
    if not ocupacion or ocupacion.get("tokens") != 1234:
        raise Falla(f"`message.usage` no se lee como lo dio la API: {ocupacion}")
    return "assistant con requestId y usage (1234 de entrada)"


def _f14(b: Banco) -> str:
    from hub import orquestador, tmux
    pane, _ = _turno_hecho(b)
    pid = tmux.pid_del_panel(pane)
    if not (orquestador._sesiones_de_claude() / f"{pid}.json").is_file():
        raise Falla(f"no hay `sessions/{pid}.json` del proceso del panel")
    estado = esperar(lambda: orquestador.estado_claude(pane) == "idle" and "idle", 10)
    if not estado:
        raise Falla(f"tras el turno `estado_claude` da {orquestador.estado_claude(pane)!r}, no «idle»")
    return f"sessions/{pid}.json: idle"


#: Lo más que se espera a que la CLI se rinda con la API callada. Con 2.1.280
#: fueron 135 s (C-0170); el doble deja margen sin colgar la medición.
TOPE_F15_S = 300


def _f15(b: Banco) -> str:
    from hub.secretario import motor
    sesion = str(uuid.uuid4())
    marca = nueva_marca("F15")
    b.api.preparar(marca, primero=Plan(callar=TOPE_F15_S + 30))
    t0 = time.monotonic()

    def intentos() -> list[int]:
        return [round(p.t - t0) for p in b.api.con_marca(marca)]

    try:
        b.llamar(marca, sesion=sesion, nueva=True, persistir=True,
                 parar=lambda: time.monotonic() - t0 > TOPE_F15_S)
    except motor.Cancelada:
        raise Falla(f"en {TOPE_F15_S} s no dio `api_error`; peticiones a los {intentos()} s") from None
    except motor.MotorNoDisponible as exc:
        if exc.causa != "api":
            raise Falla(f"cayó, pero no como `api_error`: {exc}") from None
    except motor.MotorCaido as exc:
        raise Falla(f"cayó sin `terminal_reason: api_error`: {exc}") from None
    else:
        raise Falla("contestó con la API callada")
    tardo = time.monotonic() - t0
    vistos = intentos()
    huecos = [y - x for x, y in zip(vistos, vistos[1:])]
    if len(vistos) < 2 or min(huecos) < 40:
        raise Falla(f"no reintenta a los 45 s: peticiones a los {vistos} s")
    otra = nueva_marca("F15")
    r = b.llamar(otra, sesion=sesion, persistir=True)
    if otra not in r.texto:
        raise Falla("`--resume` tras el corte no contestó")
    return f"api_error a los {tardo:.0f} s; peticiones a los {vistos} s; --resume contesta"


# Nivel con modelo: gasta. Sólo con --con-modelo, y M2 con los A_PETICION sólo
# si se nombran (decisión 405).

def _m1(b: Banco) -> str:
    with b.con_la_sesion_de_quien_lo_corre():
        r = _motor_real("Contesta sólo: vale.")
    if not r.coste > 0:
        raise Falla("contestó con coste 0")
    return f"{r.texto[:40]!r}, {r.coste:.4f} USD"


def _motor_real(prompt: str, **kw):
    from hub.secretario import motor
    kw.setdefault("modelo", _modelo_barato())
    kw.setdefault("herramientas", False)
    return motor.llamar(prompt, persistir=False, trabajo="medir", **kw)


def _m2(b: Banco) -> str:
    from hub import modelos
    from hub.secretario import motor
    ids = sorted(modelos.PERMITIDOS) + sorted(set(b.a_peticion) & modelos.A_PETICION)
    malos = []
    with b.con_la_sesion_de_quien_lo_corre():
        for modelo in ids:
            try:
                _motor_real("Contesta sólo: vale.", modelo=modelo)
            except motor.MotorCaido as exc:
                malos.append(f"{modelo}: {str(exc)[:80]}")
    if malos:
        raise Falla("; ".join(malos))
    return ", ".join(ids)


def _m3(b: Banco) -> str:
    esquema = {"type": "object", "properties": {"color": {"type": "string"}}, "required": ["color"]}
    with b.con_la_sesion_de_quien_lo_corre():
        r = _motor_real("¿De qué color es el cielo despejado? Una palabra.", esquema=esquema)
    if not isinstance(r.estructurada, dict) or "color" not in r.estructurada:
        raise Falla(f"`--json-schema` no dio `Respuesta.estructurada`: {r.estructurada!r}")
    return json.dumps(r.estructurada, ensure_ascii=False)[:60]


def _png_rojo() -> bytes:
    """Un PNG de 16×16 rojo, hecho aquí: sin depender de ningún archivo."""
    def trozo(tipo: bytes, datos: bytes) -> bytes:
        return (len(datos).to_bytes(4, "big") + tipo + datos
                + (zlib.crc32(tipo + datos) & 0xFFFFFFFF).to_bytes(4, "big"))
    filas = b"".join(b"\x00" + b"\xff\x00\x00" * 16 for _ in range(16))
    return (b"\x89PNG\r\n\x1a\n" + trozo(b"IHDR", (16).to_bytes(4, "big") * 2 + b"\x08\x02\x00\x00\x00")
            + trozo(b"IDAT", zlib.compress(filas)) + trozo(b"IEND", b""))


def _m4(b: Banco) -> str:
    imagen = b.tmp / "rojo.png"
    imagen.write_bytes(_png_rojo())
    with b.con_la_sesion_de_quien_lo_corre():
        r = _motor_real("¿De qué color es esta imagen? Una palabra en español.", imagenes=[str(imagen)])
    if "roj" not in r.texto.lower():
        raise Falla(f"no vio la imagen: {r.texto[:80]!r}")
    return r.texto[:40]


def _m5(b: Banco) -> str:
    eventos: list[dict] = []
    with b.con_la_sesion_de_quien_lo_corre():
        _motor_real("Usa tu herramienta `ahora` y dime qué día es.", herramientas=True,
                    al_evento=eventos.append)
    if not any(e.get("tipo") == "herramienta" and e.get("nombre") == "ahora" for e in eventos):
        raise Falla(f"no se vio la llamada a `mcp__secretario__ahora`: {eventos[:4]}")
    return "llamó a mcp__secretario__ahora"


def _sin_medir(motivo: str) -> Callable[[Banco], str]:
    def medir(b: Banco) -> str:
        raise NoMedido(motivo)
    return medir


MEDICIONES: tuple[Medicion, ...] = (
    Medicion("L1", "`claude --version` da X.Y.Z", "medir_claude.version", LOCAL, _l1),
    Medicion("L2", "`--help` nombra las banderas que pasa el hub", "motor._linea, modelos.linea_claude", LOCAL, _l2),
    Medicion("L3", "lanzado por `tmux.nueva_sesion`, el panel dice `claude`", "tui.detectar", LOCAL, _l3),
    Medicion("L4", "en la pantalla de alta `panel_apto` niega", "entrega.panel_apto", LOCAL, _l4),
    Medicion("F1", "llamada suelta: result, session_id, total_cost_usd", "motor.llamar", API_FALSA, _f1),
    Medicion("F2", "stream-json con parciales, por al_trozo y al_evento", "motor._Trozos, motor._Actividad",
             API_FALSA, _f2),
    Medicion("F3", "proceso abierto: dos turnos en el mismo proceso", "motor._Abierto", API_FALSA, _f3),
    Medicion("F4", "--max-budget-usd da error_max_budget_usd", "motor.TopeAgotado", API_FALSA, _f4),
    Medicion("F5", "--tools \"\" no ejecuta el Bash que pide la API", "motor.Suscripcion._linea", API_FALSA, _f5),
    Medicion("F6", "NO_LEER corta un WebFetch a 127.0.0.1", "motor.NO_LEER", API_FALSA, _f6),
    Medicion("F7", "cada id de PERMITIDOS y A_PETICION llega a la API", "modelos.PERMITIDOS, modelos.A_PETICION",
             API_FALSA, _f7),
    Medicion("F8", "carpeta confiada: sin diálogo, listo, cuadro vacío", "agentes.confiar, asistente.listo",
             API_FALSA, _f8),
    Medicion("F10", "entregar varias líneas: una sola petición", "entrega.entregar", API_FALSA, _f10),
    Medicion("F11", "respuesta retenida: ocupado y «trabajando»", "tui.ocupado, entrega.panel_apto", API_FALSA, _f11),
    Medicion("F13", "transcript en projects/<slug_de(cwd)> con requestId y usage", "transcripts.slug_de",
             API_FALSA, _f13),
    Medicion("F14", "sessions/<pid>.json con su estado", "orquestador.estado_claude", API_FALSA, _f14),
    Medicion("F12", "tool_use de Bash: permiso visto, panel no apto", "asistente.esperando_confirmacion",
             API_FALSA, _f12),
    Medicion("F9", "carpeta sin confiar: panel_apto niega y nombra el menú", "entrega.panel_apto",
             API_FALSA, _f9),
    Medicion("F15", "API callada: reintenta a los 45 s, api_error, --resume", "motor.CORTES_DE_RED",
             API_FALSA, _f15, lenta=True),
    Medicion("M1", "una llamada real contesta con coste", "motor.llamar", MODELO, _m1),
    Medicion("M2", "cada id de PERMITIDOS contesta (A_PETICION si se nombra)", "modelos.PERMITIDOS", MODELO, _m2),
    Medicion("M3", "--json-schema da Respuesta.estructurada", "motor.Respuesta", MODELO, _m3),
    Medicion("M4", "una imagen como bloque", "motor._bloques", MODELO, _m4),
    Medicion("M5", "conversación con el MCP: se ve mcp__secretario", "motor.mcp_config", MODELO, _m5),
    Medicion("N1", "CLAUDE_AUTOCOMPACT_PCT_OVERRIDE", "modelos.entorno_de_sesion", SIN_MEDIR,
             _sin_medir("pide llenar una ventana de contexto de verdad")),
    Medicion("N2", "--resume en respawn-pane", "orquestador.ajustar", SIN_MEDIR,
             _sin_medir("pide una sesión con conversación y relanzar su panel; sin medición propia")),
    Medicion("N3", "Codex", "tui.CODEX", SIN_MEDIR, _sin_medir("este guion sólo mide Claude Code")),
)


def _clave_de_orden(id_: str) -> tuple[int, int]:
    return ("LFMN".index(id_[0]) if id_[0] in "LFMN" else 9, int(re.sub(r"\D", "", id_) or 0))


class Resultados(list):
    """Los resultados, con la versión medida (la cabecera de la tabla)."""

    version = ""
    salidas: list[str] = []


def correr(ids=None, *, con_modelo: bool = False, a_peticion=(), lentas: bool = False,
           claude=None) -> Resultados:
    """Las mediciones pedidas, cada una en su `try`, en un banco que se cierra
    siempre. Lanza `SinClaude` si no hay qué medir."""
    from hub import modelos
    fuera = set(a_peticion) - modelos.A_PETICION
    if fuera:
        raise ValueError(f"no son de A_PETICION: {sorted(fuera)}")
    pedidas = [m for m in MEDICIONES if ids is None or m.id in ids]
    banco = Banco(claude, con_modelo=con_modelo)
    banco.a_peticion = tuple(a_peticion)
    resultados = Resultados()
    try:
        banco.version = version(str(banco.bin / "claude"))
        for m in pedidas:
            r = Resultado(m.id, m.que, m.supone, m.nivel, PASA)
            if m.nivel == MODELO and not con_modelo:
                if ids is None:
                    continue
                r.estado, r.detalle = NO_MEDIDO, "va con --con-modelo"
            elif m.lenta and not lentas:
                if ids is None:
                    continue
                r.estado, r.detalle = NO_MEDIDO, "va con --lentas"
            else:
                try:
                    r.detalle = m.medir(banco) or ""
                except Falla as exc:
                    r.estado, r.detalle = FALLA, str(exc)
                except NoMedido as exc:
                    r.estado, r.detalle = NO_MEDIDO, str(exc)
                except Exception as exc:  # noqa: BLE001 — una medición que revienta no tumba las demás
                    # Falla y no «no medido»: un cambio de la CLI que rompe la
                    # lectura tiene que dar un código distinto de 0.
                    r.estado, r.detalle = FALLA, f"la medición reventó: {type(exc).__name__}: {exc}"
            resultados.append(r)
        resultados.sort(key=lambda r: _clave_de_orden(r.id))
    finally:
        banco.cerrar()
    resultados.version = banco.version
    # No es una medición: es lo que la CLI quiso sacar de la máquina y cortó
    # el proxy. Se dice, sin contarlo como «pasa» ni como «falla».
    resultados.salidas = sorted(set(banco.api.salidas))
    return resultados


def tabla(resultados: list[Resultado], version: str) -> str:
    cuenta = {e: sum(r.estado == e for r in resultados) for e in (PASA, FALLA, NO_MEDIDO)}
    lineas = [f"Claude Code {version or '(versión desconocida)'} — medido el {date.today().isoformat()}",
              f"{cuenta[PASA]} pasan · {cuenta[FALLA]} fallan · {cuenta[NO_MEDIDO]} sin medir", ""]
    ancho = max((len(r.que) for r in resultados), default=10)
    for r in resultados:
        lineas.append(f"{r.id:<4} {r.nivel:<9} {r.estado:<9} {r.que:<{ancho}}  {r.detalle}")
    salidas = getattr(resultados, "salidas", [])
    lineas += ["", "Intentó salir de la máquina (cortado en el proxy): " + (", ".join(salidas) or "nada")]
    return "\n".join(lineas)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Re-mide contra la CLI `claude` lo que el hub supone de ella (C-0327).")
    p.add_argument("--con-modelo", action="store_true", help="también el nivel que llama al modelo de verdad (gasta)")
    p.add_argument("--a-peticion", action="append", default=[], metavar="ID",
                   help="un modelo de A_PETICION que M2 sí llama (sólo con --con-modelo)")
    p.add_argument("--lentas", action="store_true", help="también F15 (la API callada): minutos")
    p.add_argument("--solo", default="", help="sólo estas, separadas por comas (L1,F3,…)")
    p.add_argument("--claude", default=None, help="la CLI a medir; por omisión, la del PATH")
    p.add_argument("--json", action="store_true", help="la tabla en JSON")
    a = p.parse_args(argv)
    if a.a_peticion and not a.con_modelo:
        print("--a-peticion va con --con-modelo")
        return 2
    ids = {x.strip().upper() for x in a.solo.split(",") if x.strip()} or None
    desconocidos = (ids or set()) - {m.id for m in MEDICIONES}
    if desconocidos:
        print(f"no existen: {', '.join(sorted(desconocidos))}")
        return 2
    try:
        resultados = correr(ids, con_modelo=a.con_modelo, a_peticion=a.a_peticion, lentas=a.lentas,
                            claude=a.claude)
    except SinClaude as exc:
        print(f"no se pudo medir: {exc}")
        return 2
    except ValueError as exc:
        print(f"no se pudo medir: {exc}")
        return 2
    v = resultados.version
    if a.json:
        print(json.dumps({"version": v, "resultados": [asdict(r) for r in resultados],
                          "salidas": resultados.salidas}, ensure_ascii=False, indent=2))
    else:
        print(tabla(resultados, v))
    return 1 if any(r.estado == FALLA for r in resultados) else 0


if __name__ == "__main__":
    sys.exit(main())
