"""El servicio: la web para la persona y la API para Claude (vía MCP).

Es el único proceso que habla con el aparato —el JetKVM admite una sesión de
vídeo a la vez— y por eso el MCP no se conecta al aparato: llama a esta API.
Una sola costura: todo lo que hace Claude y todo lo que ve la persona pasa
por aquí.

Escucha **sólo en 127.0.0.1**. Hay dos clases de petición:
- las de **la persona** (dar el control, aprobar, ajustes): exigen `Origin`
  de esta misma web, o sea, un clic en el navegador. El MCP no manda `Origin`
  y por eso no puede darse el control ni aprobarse un cambio a sí mismo. Es una
  barrera contra accidentes, no contra quien quiera saltarla a propósito.
- las de **Claude** (teclear, leer, proponer, escribir lo aprobado): aceptan
  peticiones sin `Origin`; si traen uno, tiene que ser el de esta web, para
  que otra pestaña del navegador no pueda teclear en el Mac.
"""

from __future__ import annotations

import asyncio
import contextlib
import io
import json
import os
import re
import struct
import subprocess
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import (FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, Response,
                               StreamingResponse)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from PIL import Image, ImageDraw, ImageFont
from starlette.background import BackgroundTask

from . import (cambios, comprobar, config, conversaciones, hid, huellas, jiggler, lecturas, mediciones, reinicio,
               repertorio, reunion, teclados, terminal)
from .control import TOPE_CARACTERES, TOPE_LINEAS, Bitacora, Control, Permiso, SinControl
from .dispositivo import AparatoNoDisponible, Dispositivo
from .motor import RETARDO_VIDEO_MAX_MS, Motor, Ocupado, PantallaInesperada

AQUI = Path(__file__).parent
plantillas = Jinja2Templates(directory=AQUI / "plantillas")
# Lo que la página dice de un cambio aprobado por un permiso que ya acabó: espera
# a la persona, aunque en disco siga «aprobado» hasta que alguien lo toque (un
# GET no cambia el estado).
plantillas.env.globals["permiso_acabado"] = cambios.permiso_acabado

# Lo único que se abre en el marco de la izquierda: las páginas de esta web,
# por su forma exacta. Un filtro por prefijo deja pasar `/\sitio.com`, que el
# navegador entiende como `//sitio.com`, otra web.
PAGINAS_DEL_MARCO = re.compile(r"/(panel|claude|ajustes)|/(lecturas|cambios)/[a-z0-9-]{1,64}")


def explicar_error(e: Exception, dispositivo: Dispositivo) -> str:
    """El error de conexión dicho de forma que se sepa qué hacer, con el detalle técnico al final."""
    tecnico = f"{type(e).__name__}: {e}"
    if isinstance(e, AparatoNoDisponible):
        return str(e)
    url = getattr(dispositivo, "url", "")
    if isinstance(e, (OSError, asyncio.TimeoutError)) or "Connector" in type(e).__name__:
        return (f"el JetKVM no responde en {url}: ¿está encendido, en la misma red, y es ésa su dirección "
                f"en Ajustes? ({tecnico})")
    return tecnico


_avisos_sin_video: dict[str, bytes] = {}


def imagen_sin_video(motivo: str) -> bytes:
    """Lo que enseña el directo cuando no hay vídeo: un fotograma que lo dice.

    Sin él, la imagen en directo se queda cargando para siempre (la página
    nunca acaba de cargar) y la persona no ve más que un recuadro negro.
    """
    if motivo not in _avisos_sin_video:
        from .simulador import FUENTE_UI

        img = Image.new("RGB", (1280, 720), "#131a23")
        d = ImageDraw.Draw(img)
        grande = ImageFont.truetype(FUENTE_UI, 34) if FUENTE_UI else ImageFont.load_default(34)
        normal = ImageFont.truetype(FUENTE_UI, 22) if FUENTE_UI else ImageFont.load_default(22)
        d.text((60, 280), "Sin imagen del aparato", font=grande, fill="#e3e9f2")
        lineas, linea = [], ""
        for palabra in motivo.split():
            if len(linea) + len(palabra) > 90:
                lineas.append(linea)
                linea = ""
            linea += palabra + " "
        lineas.append(linea)
        for i, l in enumerate(lineas[:4]):
            d.text((60, 340 + i * 32), l.strip(), font=normal, fill="#b6c2d4")
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=80)
        if len(_avisos_sin_video) > 20:  # los motivos cambian poco; esto sólo pone un tope
            _avisos_sin_video.clear()
        _avisos_sin_video[motivo] = buf.getvalue()
    return _avisos_sin_video[motivo]


def motivo_conexion(e: Exception) -> str:
    """Por qué no conectó, en la lista de las mediciones (`mediciones.MOTIVOS_CONEXION`).

    Por los textos de `jetkvm.py`, que son de este código: el mensaje entero
    puede llevar la dirección del aparato, y a las mediciones no va."""
    texto = str(e).lower()
    if isinstance(e, AparatoNoDisponible):
        for trozo, motivo in (("contraseña", "contrasena"), ("reposo", "reposo"), ("no llega vídeo", "sin_video"),
                              ("sin vídeo", "sin_video"), ("saludo", "saludo"), ("canales", "canales"),
                              ("otra sesión", "otra_sesion")):
            if trozo in texto:
                return motivo
        return "otro"
    if isinstance(e, (OSError, asyncio.TimeoutError)) or "Connector" in type(e).__name__:
        return "no_responde"
    return "otro"


def crear_dispositivo(ajustes: dict) -> Dispositivo:
    d = ajustes["dispositivo"]
    if d["tipo"] == "jetkvm":
        from .jetkvm import JetKVM

        return JetKVM(d["url"], os.environ.get(d.get("clave_env") or "JETKVM_CLAVE", ""))
    from .simulador import Simulador

    # El Mac simulado tiene su propia fuente de entrada, como el de verdad (C-0481):
    # arranca con la del ajuste si es de serie, y después no la sigue. Si la
    # siguiera, un puente que teclea con otra no se podría probar nunca.
    inicial = ajustes.get("perfil", {}).get("distribucion", "mac-us")
    return Simulador(fuente=inicial if inicial in hid.DE_SERIE else "mac-us")


# El directo: 2 imágenes por segundo mirando, ~12 mientras la persona usa el Mac.
INTERVALO_DIRECTO = 0.5
INTERVALO_MANDO = 0.08
# Lo que se puede pedir de ancho a una imagen para mirar. Por arriba lo acota
# el propio aparato (no da más que su resolución); por abajo, que un 0 o un
# negativo no lleguen a reducir la imagen a nada.
ANCHO_MIN, ANCHO_MAX = 160, 7680
# Un recorrido: páginas como mucho y pasos de rueda por bajada.
RECORRIDO_PAGINAS, RECORRIDO_PASOS = 20, 60
# Lo que la persona puede pulsar con un botón y no con su teclado (Windows se
# queda la tecla ⌘ y algunas combinaciones).
COMBINACIONES_MANDO = ("cmd+tab", "cmd+space")
# Códigos de tecla HID que acepta el mando: de la «a» al Ctrl/Mayús/⌥/⌘ derechos.
TECLA_MIN, TECLA_MAX = 0x04, 0xE7
# Tras pedir el reinicio, cuánto se contesta «ya se está reiniciando» a otro
# clic. Si systemd no lo aceptó, nada: se puede volver a pulsar en el acto. Y
# pasado esto, tampoco: la página dice a los 15 s que no se reinició.
REINICIO_EN_CURSO = 15.0


class Puente:
    def __init__(self, dispositivo: Dispositivo | None = None):
        self.ajustes = config.leer_ajustes()
        self.dispositivo = dispositivo or crear_dispositivo(self.ajustes)
        self.control = Control()
        self.control.al_caducar = self._al_caducar
        self.bitacora = Bitacora()
        self.dispositivo.avisar = self.aviso_del_aparato
        self.motor = Motor(self.dispositivo, self.control, self.bitacora, self.ajustes["perfil"])
        self.motor.al_soltar = self._tras_tarea
        self.devolver_pendiente: str | None = None
        self.devolver_pendiente_por: str | None = None  # su `por` de las mediciones (C-0483)
        self.error_conexion = ""
        # Mientras conecta (al arrancar, «Reconectar», una reunión que reconecta),
        # el aparato dice «sin conectar» sin que nada haya fallado: el panel lo
        # dice como «conectando», no como un fallo (C-0477).
        self.conectando = False
        self.tareas: set[asyncio.Task] = set()
        self.actividad = repertorio.Actividad(config.hogar() / "actividad.json")
        # Tras reiniciar el puente, la conversación de Claude sigue viva en tmux:
        # lo último que contaron sus hooks, para que cambiarla pregunte si Claude
        # estaba a medias (C-0470). Sin conversación viva, lo guardado es de otra.
        with contextlib.suppress(OSError, subprocess.SubprocessError):
            if self.actividad.ruta.exists() and terminal.existe():
                self.actividad.recuperar()
        # Hasta cuándo la persona está usando el Mac desde la pantalla: mientras,
        # el directo va más fluido, y el puente no se reinicia (`comprobar.ocupado`).
        self.mando_hasta = 0.0
        # Cuántas pestañas tienen abierto el mando: al cerrarse la última, el Mac
        # ya no está en uso, aunque no hayan pasado los segundos de `mando_hasta`.
        self.mandos = 0
        # Hasta cuándo un reinicio pedido está en curso (`REINICIO_EN_CURSO`).
        self.reinicio_hasta = 0.0
        self._mirando_reinicio = False
        self.ultima_imagen: tuple[bytes, float, int] = (b"", 0.0, 0)
        # Las páginas del último recorrido (`/api/recorrer`), sólo en memoria: son
        # contenido del trabajo, y el siguiente las sustituye. Con su id, para que
        # quien las baja no mezcle las de otro que llegó en medio.
        self.recorrido: tuple[str, list[bytes]] = ("", [])
        self.grabadora = reunion.Grabadora(self.dispositivo)
        # Para las mediciones (C-0483): los turnos abiertos de Claude por sesión,
        # con sus cuentas, y cuándo acabó la última herramienta y llegó el último
        # mensaje (`time.monotonic()`), para el hueco entre herramientas.
        self.turnos: dict[str, dict] = {}
        self.fin_herramienta = 0.0
        self.ultimo_mensaje = 0.0
        self.version_claude_code: str | None = None

    async def conectar(self, por: str = "arranque") -> None:
        self.conectando = True
        inicio, motivo = time.monotonic(), "ninguno"
        try:
            await self.dispositivo.conectar()
            await self.tras_conectar()
        except Exception as e:  # se enseña en la pantalla, no se traga
            self.error_conexion = explicar_error(e, self.dispositivo)
            self.bitacora.apuntar("error", f"no conecta: {self.error_conexion}", quien="puente")
            motivo = motivo_conexion(e)
        finally:
            self.conectando = False
        mediciones.apuntar("conexion", evento="fallo" if self.error_conexion else "conectado", por=por,
                           ms=round((time.monotonic() - inicio) * 1000), motivo=motivo, aparato=self._aparato())

    def _aparato(self) -> str | None:
        tipo = getattr(self.dispositivo, "tipo", None)
        return tipo if tipo in mediciones.APARATOS else None

    def medir_contexto(self, evento: str) -> None:
        """Con qué se trabaja, en una línea: aparato, versiones, resolución y los
        retardos del perfil. Sin la dirección del aparato ni el nombre del perfil."""
        try:
            disp = self.dispositivo.estado()
        except Exception:
            disp = {}
        perfil, claude = self.ajustes.get("perfil", {}), self.ajustes.get("claude", {})
        distribucion = perfil.get("distribucion", "mac-us")
        modelo = claude.get("modelo") or "el_suyo"

        def version(v) -> str | None:
            return v if isinstance(v, str) and mediciones._VERSION.fullmatch(v) else None

        def numero(v) -> int | None:
            return v if isinstance(v, int) and not isinstance(v, bool) else None
        mediciones.apuntar(
            "contexto", evento=evento, aparato=self._aparato(), version=version(config.VERSION),
            firmware=version(disp.get("firmware")),
            firmware_contrastado=disp["firmware_contrastado"] if isinstance(disp.get("firmware_contrastado"),
                                                                            bool) else None,
            claude_code=version(self.version_claude_code), ancho=numero(disp.get("ancho")),
            alto=numero(disp.get("alto")), retardo_tecla_ms=numero(perfil.get("retardo_tecla_ms")),
            retardo_video_ms=numero(perfil.get("retardo_video_ms")),
            invertir_rueda=perfil.get("invertir_rueda") is True,
            distribucion=distribucion if distribucion in hid.DE_SERIE else "medida",
            modelo=modelo if modelo in mediciones.MODELOS else "otro",
            saltar_permisos=claude.get("saltar_permisos") is True)

    async def tras_conectar(self) -> None:
        """Lo de después de conectar. También cuando la conexión vuelve sola: con el
        Mac dormido al conectar no llega vídeo, y al despertar llega (C-0463)."""
        self.error_conexion = ""
        e = self.dispositivo.estado()
        self.medir_contexto("conexion")
        self.bitacora.apuntar("conexion", f"conectado a {self.dispositivo.tipo}"
                              + (f", firmware {e['firmware']}" if e.get("firmware") else ""), quien="puente")
        if e.get("aviso"):
            self.bitacora.apuntar("aviso", e["aviso"], quien="puente")
        if self.dispositivo.da_sonido and self.grabadora.actual is None and not self.grabadora.empezando:
            # Encendido de una reunión que no se cerró bien: se queda guardado
            # en el aparato, y sin esto capturaría en cada conexión.
            with contextlib.suppress(Exception):
                await self.dispositivo.apagar_sonido()

    def aviso_del_aparato(self, texto: str) -> None:
        self.bitacora.apuntar("aviso", texto, quien="puente")

    def devolver_control(self, motivo: str, por: str = "otro") -> None:
        """La única puerta por la que el puente le devuelve el Mac a la persona, con
        su línea en la bitácora. Sólo con el control dado a Claude: nunca se lo da,
        y un PARADO sigue parado.

        `por` es el motivo en la lista de las mediciones (`mediciones.POR_CONTROL`):
        el texto de `motivo` es para la persona, y a las mediciones no va."""
        self.olvidar_pendiente()
        # Que caduque antes, si toca: lo apunta `_al_caducar`, y aquí ya no
        # quedaría nada que devolver (sin esto salían dos «devuelto»).
        self.control.estado()
        if self.control.modo == "claude":
            # Lo que lo tuvo de verdad, medido ahora: con C-0488 puede ser el final
            # de una tarea larga, no el hook que pidió devolverlo.
            con_claude = (time.time() - self.control.desde) * 1000
            # Antes de retomar: después, el permiso ya no es el vigente.
            resumen = self.resumen_correcciones(self.control.permiso_vigente())
            self.control.retomar(motivo)
            self.bitacora.apuntar("control", motivo, quien="puente")
            if resumen:
                self.bitacora.apuntar(**resumen)
            mediciones.apuntar("control", evento="devuelto", por=por if por in mediciones.POR_CONTROL else "otro",
                               ms_con_claude=round(con_claude))

    def _al_caducar(self, ms_con_claude: float, permiso: Permiso | None) -> None:
        """El control volvió solo tras `INACTIVIDAD_S` (lo llama `Control`, ya
        suelto): lo mismo que apunta `devolver_control`, con el permiso que valía
        hasta entonces, que ya no es el vigente."""
        self.olvidar_pendiente()
        resumen = self.resumen_correcciones(permiso)
        if resumen:
            self.bitacora.apuntar(**resumen)
        mediciones.apuntar("control", evento="devuelto", por="caducidad", ms_con_claude=round(ms_con_claude))

    def olvidar_pendiente(self) -> None:
        """La devolución que esperaba a que acabara la tarea (C-0488) ya no vale:
        el control cambió de manos. Lo llama todo lo que lo quita o lo da
        (devolver, Retomar, Parar, «Usar el Mac», caducar y dar): un control
        dado después no puede perderse al acabar una tarea de antes."""
        self.devolver_pendiente = self.devolver_pendiente_por = None

    def resumen_correcciones(self, permiso: Permiso | None) -> dict | None:
        """La línea de bitácora «Claude escribió N correcciones sin pedirte», si
        `permiso` escribió algo (C-0489). Se le pasa el permiso, cogido ANTES de
        quitar el control (después ya no es el vigente): lo que la persona va a
        guardar incluye lo que nadie le enseñó antes."""
        if permiso is None:
            return None
        escritos = []
        for id_ in permiso.escritos:
            with contextlib.suppress(Exception):
                c = cambios.cargar(id_)
                # Uno que falló a medias también dejó texto en el editor.
                if c.estado in ("escrito", "verificado") or any(t.estado == "escrito" for t in c.tramos):
                    escritos.append(c.id)
        if not escritos:
            return None
        n = len(escritos)
        return {"tipo": "correcciones", "quien": "puente", "cambios": escritos,
                "detalle": f"Claude escribió {n} {'corrección' if n == 1 else 'correcciones'} sin pedirte: "
                           f"revísal{'a' if n == 1 else 'as'} antes de guardar ({', '.join(escritos)})"}

    def aprobar_cambio(self, c: cambios.Cambio, permiso: Permiso | None = None) -> None:
        """Aprobar con su línea en la bitácora, por los dos caminos: el clic de la
        persona y su permiso de correcciones pequeñas (C-0489). Es también el único
        sitio que mide la aprobación (C-0483): cuánto tardó en decidirse (una
        duración, no una hora), quién la dio y cuánto mueve; conteos, nunca texto."""
        cambios.aprobar(c, permiso)
        lineas, caracteres = cambios.medida(c)
        mediciones.apuntar("cambio", evento="aprobado", tramos=len(c.tramos),
                           ms=round(max(0.0, time.time() - c.creado) * 1000), por=c.aprobado_por,
                           lineas=lineas, caracteres=caracteres)
        if permiso is None:
            self.bitacora.apuntar("aprobacion", f"{c.descripcion}: aprobado", quien="persona", cambio=c.id)
            return
        self.bitacora.apuntar(
            "aprobacion", f"{c.descripcion}: aprobado por tu permiso de correcciones pequeñas "
            f"({lineas} {'línea' if lineas == 1 else 'líneas'}, {caracteres} caracteres)"
            + (", sobre una lectura sin verificar" if c.sin_verificar else ""),
            quien="puente", cambio=c.id)

    def devolver_al_acabar(self, motivo: str, por: str = "otro") -> None:
        """Como `devolver_control`, pero sin cortar la tarea en marcha (C-0488).

        Escribir un documento largo es una sola tarea de casi una hora, y Claude
        puede terminar su turno mientras tanto (avisa del progreso y se para).
        Quitarle el control entonces cortaba el tecleo a mitad del documento:
        antes de C-0486 el control duraba hasta acabar la tarea, y eso se
        conserva. Lo que corta en el acto sigue siendo de la persona: Parar,
        Retomar y «Usar el Mac desde aquí».

        `por` se guarda con el motivo: la medición `control` dice lo que de verdad
        lo devolvió (el fin de turno), no el final de la tarea que lo hizo efectivo."""
        if self.motor.tarea and self.control.modo == "claude":
            if self.devolver_pendiente is None:
                self.bitacora.apuntar("control", f"{motivo.split(':')[0]}; el Mac vuelve a ti cuando acabe "
                                      f"«{self.motor.tarea}»", quien="puente")
            self.devolver_pendiente, self.devolver_pendiente_por = motivo, por
        else:
            self.devolver_control(motivo, por=por)

    def _tras_tarea(self) -> None:
        if self.devolver_pendiente:
            self.devolver_control(self.devolver_pendiente, por=self.devolver_pendiente_por or "otro")

    # ── cuándo vuelve el Mac: al acabar el encargo, no cada tarea (C-0486) ──
    def turno_en_curso(self) -> bool:
        """Claude está con un encargo de la conversación abierta: llegó su
        `UserPromptSubmit` y aún no su `Stop`. Sin conversación del registro, o
        con hooks de otra sesión, no se sabe, y «no sé» no cuenta como sí."""
        conv = conversaciones.actual()
        return conv is not None and conv.id in self.actividad.abiertos

    def conversacion_reabierta(self, motivo: str) -> None:
        """Claude Code se abrió de nuevo (o se cambió de conversación): el que se
        cerró no manda su `Stop`, y un control dado para su encargo no vale
        para el siguiente (lo encontró el revisor de C-0486)."""
        self.devolver_control(motivo, por="conversacion")
        self.actividad.recien_abierta()
        for sesion in list(self.turnos):
            self.cerrar_turno(sesion, "reabierta")

    def al_acabar_tarea(self, motivo: str) -> None:
        """Acabó una lectura, una escritura o la consulta de prueba del teclado.

        Si el puente sabe qué turno corre, el control sigue con Claude: un
        encargo de dos párrafos se quedaba en el primero porque escribir lo
        devolvía, y una captura mala ya no se podía repetir (C-0486). Lo
        devuelve el `Stop` de ese turno (`fin_de_turno`), Parar, «Usar el Mac
        desde aquí» o los 10 min sin hacer nada. Si no lo sabe (sin hooks, una
        conversación sin registro), vuelve como siempre, tras cada tarea."""
        try:
            sigue = self.turno_en_curso()
        except Exception:  # un registro ilegible no puede dejar el control dado
            sigue = False
        if not sigue:
            self.devolver_control(motivo, por="respaldo_tarea")
        elif self.control.modo == "claude":
            hecho = motivo.split(":")[0]
            self.bitacora.apuntar("control", f"{hecho}; Claude sigue con el control hasta que termine el encargo",
                                  quien="puente")

    def fin_de_turno(self, hook: dict) -> None:
        """Lo que dicen los hooks de Claude Code sobre el control. Se llama ANTES de
        `actividad.registrar`: la red del Esc mira el turno anterior.

        Sólo cuentan los de la conversación abierta: el settings del proyecto
        también lo cargan las sesiones de desarrollo. 🔴 Sólo devuelve
        (`devolver_control`): nunca da el control ni saca de PARADO.
        """
        evento = hook.get("hook_event_name")
        herramienta = str(hook.get("tool_name") or "") if evento == "PreToolUse" else ""
        pregunta = herramienta == "AskUserQuestion"
        del_mac = herramienta.removeprefix("mcp__puente-kvm__") in repertorio.NECESITA_CONTROL \
            and herramienta.startswith("mcp__puente-kvm__")
        if evento not in ("Stop", "SessionEnd", "UserPromptSubmit") and not pregunta and not del_mac:
            return  # cada herramienta manda su hook: sin leer el registro para nada
        if self.control.modo != "claude":
            return
        try:
            conv = conversaciones.actual()
        except Exception:
            conv = None
        if conv is None:
            return  # no se sabe cuál es la del puente: cada tarea devuelve, como antes
        if hook.get("session_id") != conv.id:
            # Otra sesión de Claude con el MCP del puente (una de desarrollo) iba a
            # tocar el Mac con el control dado para el encargo de la conversación:
            # con el control por turno, ese rato ya no es una tarea, es un turno.
            if del_mac:
                self.devolver_al_acabar("otra sesión de Claude iba a tocar el Mac: el control vuelve a ti",
                                        por="otra_sesion")
            return
        if evento in ("Stop", "SessionEnd"):
            self.devolver_al_acabar("Claude terminó: el Mac vuelve a ti para revisar y guardar", por="fin_turno")
        elif pregunta:
            self.devolver_al_acabar("Claude te pregunta algo: el Mac vuelve a ti", por="pregunta")
        elif evento == "UserPromptSubmit" and conv.id in self.actividad.abiertos \
                and self.control.desde < self.actividad.abiertos[conv.id]:
            # Un Esc corta el turno sin `Stop`: el mensaje siguiente lo delata. Si
            # la persona dio el control después del corte, lo dio para esto.
            self.devolver_al_acabar("el encargo anterior se cortó sin terminar: el Mac vuelve a ti", por="esc")

    # ── las mediciones de Claude (C-0483): turnos y herramientas ──
    def medir_turno(self, hook: dict) -> None:
        """Cuenta el turno con los hooks que ya llegan (sin PostToolUse: trae la
        imagen y para a Claude). Sólo cuántas herramientas y de qué clase, nunca
        qué llevaban. Un `UserPromptSubmit` con el turno abierto es un Esc."""
        sesion = repertorio._sesion(hook.get("session_id"))
        if sesion is None:
            return
        evento, ahora = hook.get("hook_event_name"), time.monotonic()
        if evento == "UserPromptSubmit":
            self.ultimo_mensaje = ahora
            if sesion in self.turnos:
                self.cerrar_turno(sesion, "cortado")
            self.turnos[sesion] = {"t0": ahora, "herramientas": 0, "lecturas": 0, "propuestas": 0, "cambios": 0,
                                   "otras": 0, "preguntas": 0}
            for vieja in sorted(self.turnos, key=lambda k: self.turnos[k]["t0"])[:-repertorio.MAX_ABIERTOS]:
                del self.turnos[vieja]
        elif evento == "PreToolUse" and sesion in self.turnos:
            cuenta, nombre = self.turnos[sesion], str(hook.get("tool_name") or "")
            if nombre.startswith("mcp__puente-kvm__"):
                cuenta["herramientas"] += 1
                clave = {"leer_documento": "lecturas", "proponer_cambio": "propuestas",
                         "escribir_cambio": "cambios"}.get(nombre.removeprefix("mcp__puente-kvm__"))
                if clave:
                    cuenta[clave] += 1
            elif nombre == "AskUserQuestion":
                cuenta["preguntas"] += 1
            else:
                cuenta["otras"] += 1
        elif evento in ("Stop", "SessionEnd") and sesion in self.turnos:
            self.cerrar_turno(sesion, "stop" if evento == "Stop" else "sesion_cerrada")

    def cerrar_turno(self, sesion: str, fin: str) -> None:
        cuenta = self.turnos.pop(sesion, None)
        if cuenta is None:
            return
        try:
            conv = conversaciones.actual()
        except Exception:
            conv = None
        t0 = cuenta.pop("t0")
        mediciones.apuntar("turno", ms=round((time.monotonic() - t0) * 1000), fin=fin,
                           conversacion=conv is not None and conv.id == sesion, **cuenta)

    def medir_herramienta(self, datos: dict) -> None:
        """Lo que mandó el MCP de una herramienta, con el hueco desde la anterior.

        El hueco es lo que piensa Claude entre dos herramientas del mismo turno;
        la primera tras un mensaje lleva, en su lugar, cuánto tardó desde él."""
        if not isinstance(datos, dict) or set(datos) - {"nombre", "ms", "ok", "error", "imagenes", "kb"}:
            raise mediciones.NoValida("una herramienta sólo manda nombre, ms, ok, error, imagenes y kb")
        mediciones.validar("herramienta", datos)
        ahora = time.monotonic()
        inicio = ahora - (datos.get("ms") or 0) / 1000
        hueco = desde_mensaje = None
        if self.fin_herramienta and self.fin_herramienta >= self.ultimo_mensaje:
            hueco = round(max(0.0, inicio - self.fin_herramienta) * 1000)
        elif self.ultimo_mensaje:
            desde_mensaje = round(max(0.0, inicio - self.ultimo_mensaje) * 1000)
        self.fin_herramienta = max(self.fin_herramienta, ahora)
        mediciones.apuntar("herramienta", **datos, hueco_ms=hueco, desde_mensaje_ms=desde_mensaje)

    def en_segundo_plano(self, coro) -> None:
        t = asyncio.create_task(coro)
        self.tareas.add(t)
        t.add_done_callback(self.tareas.discard)

    def mirar_reinicio(self) -> None:
        """Vuelve a preguntarle a systemd si es el de su unidad, en un hilo y una
        vez a la vez: el estado se contesta desde el bucle cada segundo, y
        `systemctl show` puede tardar (C-0470)."""
        if self._mirando_reinicio:
            return
        try:
            asyncio.get_running_loop()
        except RuntimeError:  # fuera del bucle: lo mirará el siguiente estado
            return
        self._mirando_reinicio = True

        async def mirar() -> None:
            try:
                await asyncio.to_thread(reinicio.como)
            finally:
                self._mirando_reinicio = False
        self.en_segundo_plano(mirar())


def _modo_video(p: Puente) -> str:
    try:
        return p.dispositivo.video
    except Exception:
        return "mjpeg"


def crear_app(dispositivo: Dispositivo | None = None, hosts: set[str] | None = None) -> FastAPI:
    admitidos = hosts if hosts is not None else config.HOSTS

    @contextlib.asynccontextmanager
    async def vida(app: FastAPI):
        app.state.puente = Puente(dispositivo)
        p = app.state.puente
        # Una vez, fuera del bucle: si es el de su unidad de systemd, ya no cambia.
        await asyncio.to_thread(reinicio.como)
        for id_ in reunion.cerrar_cortadas():
            app.state.puente.bitacora.apuntar("reunion", f"cerrada la reunión {id_}, que se cortó a medias",
                                              quien="puente")
        # Las mediciones (C-0483): los días de más de un mes fuera, y con qué se
        # arranca. La versión de Claude Code, en otro hilo: la pregunta a `claude`.
        await asyncio.to_thread(mediciones.podar)
        with contextlib.suppress(Exception):
            p.version_claude_code = (await asyncio.to_thread(terminal.claude_code)).get("version")
        p.medir_contexto("arranque")
        await app.state.puente.conectar()

        def del_video() -> dict:
            modo = _modo_video(p)
            return {"modo": modo if modo in ("h264", "mjpeg") else None,
                    "conectado": bool(p.dispositivo.estado().get("conectado"))}
        volcado = asyncio.create_task(mediciones.volcar_siempre(mediciones.SUMAS, del_video))
        yield
        volcado.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await volcado
        with contextlib.suppress(Exception):  # lo del último minuto, que no se pierda al parar
            mediciones.SUMAS.volcar(del_video())
        if app.state.puente.grabadora.actual is not None:
            with contextlib.suppress(Exception):
                await app.state.puente.grabadora.parar(cortada="el puente se paró mientras grababa")
        with contextlib.suppress(Exception):
            await app.state.puente.dispositivo.cerrar()

    app = FastAPI(title="Puente KVM", lifespan=vida)
    app.mount("/static", StaticFiles(directory=AQUI / "static"), name="static")

    @app.middleware("http")
    async def solo_por_su_nombre(req: Request, siguiente):
        if req.headers.get("host", "") not in admitidos:
            return JSONResponse({"detail": "nombre de host no admitido"}, status_code=403)
        r = await siguiente(req)
        # Sólo esta web puede enmarcar sus páginas (el espacio de trabajo enmarca
        # el panel). Enmarcadas en otra web, un clic robado sobre «Dar el
        # control» o «Aprobar» se saltaría la única puerta que no es de Claude.
        r.headers["Content-Security-Policy"] = "frame-ancestors 'self'"
        r.headers["X-Frame-Options"] = "SAMEORIGIN"
        return r

    def puente(req: Request) -> Puente:
        return req.app.state.puente

    def mismo_origen(req: Request) -> bool:
        origen = req.headers.get("origin")
        if not origen:
            return False
        anfitrion = req.headers.get("host", "")
        return origen in (f"http://{anfitrion}", f"https://{anfitrion}")

    def ws_de_esta_web(ws: WebSocket) -> bool:
        """Las puertas de los tres WebSocket (el mando, la terminal y la pantalla): el
        nombre y el origen de ESTA web, o nada. Un WebSocket no pasa por el
        middleware de arriba, y el navegador sí deja abrir uno a otra web."""
        anfitrion = ws.headers.get("host", "")
        origen = ws.headers.get("origin", "")
        return anfitrion in admitidos and origen in (f"http://{anfitrion}", f"https://{anfitrion}")

    def imagen_de_esta_web(req: Request) -> None:
        """La pantalla del Mac, por GET: la piden la propia página (un `<img>`, sin
        `Origin` y con `Sec-Fetch-Site: same-origin`) y las herramientas de Claude
        (sin cabeceras de navegador). Otra web que la incruste no la recibe: no
        podría leerla, pero el puente se la seguiría haciendo."""
        if req.headers.get("origin") and not mismo_origen(req):
            raise HTTPException(403, "origen no admitido")
        if req.headers.get("sec-fetch-site", "same-origin") not in ("same-origin", "none"):
            raise HTTPException(403, "origen no admitido")

    def de_la_persona(req: Request) -> None:
        if not mismo_origen(req):
            raise HTTPException(403, "esto lo hace la persona desde la pantalla del puente")

    def de_claude(req: Request) -> None:
        if req.headers.get("origin") and not mismo_origen(req):
            raise HTTPException(403, "origen no admitido")

    async def cuerpo(req: Request) -> dict:
        try:
            return await req.json()
        except Exception:
            return {}

    def fallo(e: Exception) -> HTTPException:
        if isinstance(e, SinControl):
            return HTTPException(423, str(e))
        if isinstance(e, (Ocupado, PantallaInesperada, terminal.ClaudeCodeViejo)):
            return HTTPException(409, str(e))
        if isinstance(e, hid.TextoIntraducible):
            return HTTPException(422, str(e))
        if isinstance(e, AparatoNoDisponible):
            return HTTPException(503, str(e))
        if isinstance(e, (ValueError, FileNotFoundError, KeyError)):
            return HTTPException(400, str(e))
        return HTTPException(500, f"{type(e).__name__}: {e}")

    # ── páginas ─────────────────────────────────────────────────────────────
    def pagina(req: Request, plantilla: str, **ctx) -> HTMLResponse:
        p = puente(req)
        return plantillas.TemplateResponse(req, plantilla, {"estado": estado(p),
                                                            "permiso_vigente": p.control.permiso_vigente(), **ctx})

    @app.get("/", response_class=HTMLResponse)
    async def espacio(req: Request, ver: str = "/panel"):
        ver = ver if PAGINAS_DEL_MARCO.fullmatch(ver) else "/panel"
        return pagina(req, "espacio.html", titulo="Puente KVM", ver=ver)

    @app.get("/panel", response_class=HTMLResponse)
    async def inicio(req: Request):
        return pagina(req, "panel.html", titulo="Panel",
                      lecturas=[lecturas.resumen(l) for l in lecturas.todas()[:20]],
                      cambios=[c for c in cambios.todos()[:20]],
                      teclados_disponibles=teclados.disponibles(),
                      # Los del permiso de correcciones (C-0489), para la casilla de «Dar el control».
                      tope_lineas=TOPE_LINEAS, tope_caracteres=TOPE_CARACTERES)

    @app.get("/lecturas/{id_}", response_class=HTMLResponse)
    async def ver_lectura(req: Request, id_: str):
        try:
            l = lecturas.cargar(id_)
        except Exception as e:
            raise HTTPException(404, "no existe esa lectura") from e
        ens = lecturas.ensamblar(l)
        return pagina(req, "lectura.html", titulo=l.nombre, l=l, r=lecturas.resumen(l), ens=ens,
                      textos={p.n: l.transcripcion(p.n) for p in l.paginas},
                      consultas=huellas.CONSULTAS,
                      cambios=[c for c in cambios.todos() if c.lectura == l.id])

    @app.get("/cambios/{id_}", response_class=HTMLResponse)
    async def ver_cambio(req: Request, id_: str):
        try:
            c = cambios.cargar(id_)
        except Exception as e:
            raise HTTPException(404, "no existe ese cambio") from e
        return pagina(req, "cambio.html", titulo=c.descripcion, c=c)

    @app.get("/claude", response_class=HTMLResponse)
    async def ver_claude(req: Request):
        return pagina(req, "claude.html", titulo="Claude", skills=repertorio.skills(),
                      permisos=repertorio.permisos(), herramientas=await repertorio.herramientas(),
                      conocimiento=repertorio.conocimiento(),
                      actividad=list(puente(req).actividad.eventos)[::-1],
                      lecturas=[lecturas.resumen(l) for l in lecturas.todas()[:10]])

    @app.get("/ajustes", response_class=HTMLResponse)
    async def ver_ajustes(req: Request):
        p = puente(req)
        clave_env = p.ajustes["dispositivo"].get("clave_env") or "JETKVM_CLAVE"
        return pagina(req, "ajustes.html", titulo="Ajustes", ajustes=p.ajustes,
                      clave_puesta=bool(os.environ.get(clave_env)),
                      teclados_disponibles=teclados.disponibles(), medidas=teclados.medidas(),
                      modelos=config.MODELOS, mediciones=mediciones.estado())

    # ── estado y pantalla ───────────────────────────────────────────────────
    def estado(p: Puente) -> dict:
        try:
            disp = p.dispositivo.estado()
        except Exception as e:
            disp = {"tipo": p.dispositivo.tipo, "conectado": False, "error": str(e)}
        if p.error_conexion and disp.get("conectado"):
            p.error_conexion = ""  # antes de lanzarlo: que el sondeo siguiente no lo lance otra vez
            mediciones.apuntar("conexion", evento="vuelta", por="sola", aparato=p._aparato())
            p.en_segundo_plano(p.tras_conectar())
        conv = conversaciones.actual()
        como, mirar = reinicio.sabido()
        if mirar:
            p.mirar_reinicio()
        return {"version": config.VERSION, "control": p.control.estado(), "dispositivo": disp,
                # El disco ya no es lo que corre: se actualizó sin reiniciar el puente.
                "codigo_viejo": config.CODIGO_EN_MARCHA.viejo(),
                # Con qué se reinicia (decisión 446 del hub): «boton» si es el de su
                # unidad de systemd; «a_mano», el comando de siempre. Y desde cuándo
                # corre, para que la pantalla sepa que ya contesta el nuevo.
                "reinicio": "boton" if como == "systemd" else "a_mano",
                "arrancado": reinicio.ARRANQUE,
                # Con «Usar el Mac» abierto, aunque no se mueva nada: leyendo lo que
                # hay, la persona también lo está usando.
                "mando": p.mandos > 0 or time.time() < p.mando_hasta,
                # Cómo llega la pantalla al navegador (C-0469): el vídeo del aparato
                # tal cual («h264») o imágenes («mjpeg»: el simulador, o sin vídeo directo).
                "video": _modo_video(p),
                "claude": p.actividad.publico(), "error_conexion": p.error_conexion, "tarea": p.motor.tarea,
                "conectando": p.conectando,
                "reunion": p.grabadora.estado(),
                "jiggler_texto": jiggler.describir(disp.get("jiggler")),
                "progreso": p.motor.progreso, "perfil": p.ajustes["perfil"], "t": time.time(),
                # Dónde trabaja Claude y con qué conversación: rutas y el nombre que le puso la persona.
                "espacio": str(config.espacio()), "codigo": str(config.CODIGO),
                "conversacion": {"nombre": conv.nombre, "modelo": conv.modelo, "claude_code": conv.claude_code,
                                 "modelo_texto": config.texto_modelo(conv.modelo),
                                 # Su servidor MCP es de otro código que el del disco: hay que reabrirla.
                                 "herramientas_viejas": conv.herramientas_viejas()} if conv else None,
                # Sin registro: ¿hay una de antes abierta, o aún no se ha abierto ninguna?
                "conversacion_anterior": False if conv else terminal.existe(),
                # El `claude` que abriría el puente con SU PATH (no el de una shell).
                "claude_code": terminal.claude_code()}

    @app.get("/api/estado")
    async def api_estado(req: Request):
        p = puente(req)
        return {**estado(p),
                "lecturas": [lecturas.resumen(l) for l in lecturas.todas()[:10]],
                "cambios": [{"id": c.id, "descripcion": c.descripcion, "estado": c.estado,
                             "tramos": len(c.tramos)} for c in cambios.todos()[:10]]}

    @app.get("/api/bitacora")
    async def api_bitacora(req: Request, desde: int = 0):
        return puente(req).bitacora.ultimas(desde)

    def _codificar(img: Image.Image, ancho: int) -> bytes:
        if ancho and img.width > ancho:
            img = img.resize((ancho, round(img.height * ancho / img.width)), Image.BILINEAR)
        buf = io.BytesIO()
        img.convert("RGB").save(buf, "JPEG", quality=75)
        return buf.getvalue()

    async def jpeg(p: Puente, region: str, ancho: int) -> bytes:
        """Para mirar, no para leer (las lecturas van por la captura entera).

        🔴 Nada de esto corre en el bucle: reducir y comprimir 1080p ahí lo
        paraba ~40 ms por imagen, y a 8 por segundo el ratón y el teclado de la
        persona esperaban en cola. Y una imagen recién hecha se reparte entre
        quienes miran a la vez (la pestaña del puente, la de Ajustes…). Con dos
        que miran a anchos distintos, la imagen se rehace para cada uno."""
        ancho = max(ANCHO_MIN, min(int(ancho), ANCHO_MAX))
        if region == "editor":
            img = p.motor.recortar(await p.motor.captura())
            return await asyncio.to_thread(_codificar, img, ancho)
        ahora = time.monotonic()
        hecha, cuando, de_ancho = p.ultima_imagen
        if hecha and de_ancho == ancho and ahora - cuando < INTERVALO_MANDO / 2:
            return hecha
        img = await p.dispositivo.miniatura(ancho)
        datos = await asyncio.to_thread(_codificar, img, ancho)
        p.ultima_imagen = (datos, time.monotonic(), ancho)
        mediciones.SUMAS.sumar("imagenes")
        return datos

    @app.get("/api/pantalla.jpg")
    async def api_pantalla(req: Request, region: str = "completa", ancho: int = 1280):
        imagen_de_esta_web(req)
        try:
            return Response(await jpeg(puente(req), region, ancho), media_type="image/jpeg",
                            headers={"Cache-Control": "no-store"})
        except Exception as e:
            raise fallo(e) from e

    @app.get("/api/pantalla.png")
    async def api_pantalla_png(req: Request, region: str = "completa"):
        imagen_de_esta_web(req)
        p = puente(req)
        try:
            img = await p.motor.captura()
        except Exception as e:
            raise fallo(e) from e
        if region == "editor":
            img = p.motor.recortar(img)
        buf = io.BytesIO()
        img.save(buf, "PNG")
        return Response(buf.getvalue(), media_type="image/png", headers={"Cache-Control": "no-store"})

    @app.get("/api/pantalla.mjpg")
    async def api_directo(req: Request, ancho: int = 1280):
        """En la tarjeta del panel, 1280 px; en «Pantalla grande», hasta el ancho real
        del Mac: reducida y estirada después, la letra pequeña no se lee."""
        imagen_de_esta_web(req)
        p = puente(req)

        async def fotogramas():
            while not await req.is_disconnected():
                try:
                    datos = await jpeg(p, "completa", ancho)
                except Exception as e:  # sin vídeo, un fotograma que dice por qué
                    datos = imagen_sin_video(str(e) or type(e).__name__)
                yield (b"--fotograma\r\nContent-Type: image/jpeg\r\nContent-Length: "
                       + str(len(datos)).encode() + b"\r\n\r\n" + datos + b"\r\n")
                await asyncio.sleep(INTERVALO_MANDO if time.time() < p.mando_hasta else INTERVALO_DIRECTO)

        return StreamingResponse(fotogramas(), media_type="multipart/x-mixed-replace; boundary=fotograma")

    # ── control (la persona) ────────────────────────────────────────────────
    @app.post("/api/control")
    async def api_control(req: Request):
        de_la_persona(req)
        p = puente(req)
        datos = await cuerpo(req)
        accion = datos.get("accion")
        # Sólo un verdadero de verdad: «false» o «no» como texto no dan el permiso.
        correcciones = accion == "dar" and datos.get("correcciones") is True
        tenia, desde = p.control.estado()["modo"], p.control.desde
        if accion not in ("dar", "retomar", "parar"):
            raise HTTPException(400, "acción desconocida")
        resumen = p.resumen_correcciones(p.control.permiso_vigente()) if accion in ("retomar", "parar") else None
        # Un control dado ahora es para lo que viene, y uno quitado ya no se
        # devuelve: la devolución que esperaba a la tarea anterior (C-0488) sobra.
        p.olvidar_pendiente()
        if accion == "dar":
            p.control.dar(correcciones=correcciones)
        elif accion == "retomar":
            p.control.retomar()
        else:
            p.control.parar()
        p.bitacora.apuntar("control", {"dar": "la persona da el control a Claude"
                                       + (f", con correcciones pequeñas sin pedirle aprobación (hasta "
                                          f"{TOPE_LINEAS} líneas y {TOPE_CARACTERES} caracteres)"
                                          if correcciones else ""),
                                       "retomar": "la persona retoma el Mac",
                                       "parar": "PARAR"}[accion], quien="persona")
        if resumen:
            p.bitacora.apuntar(**resumen)
        if accion == "dar":
            # Si trajo el permiso de correcciones: sólo el sí o no, nunca el tope gastado.
            mediciones.apuntar("control", evento="dado", correcciones=correcciones)
        elif tenia == "claude":
            mediciones.apuntar("control", evento="devuelto", por=accion, ms_con_claude=round((time.time() - desde) * 1000))
        with contextlib.suppress(Exception):
            await p.dispositivo.informe_teclado(0, [])
        return p.control.estado()

    # ── acciones sueltas (Claude) ───────────────────────────────────────────
    @app.post("/api/teclear")
    async def api_teclear(req: Request):
        de_claude(req)
        p, datos = puente(req), await cuerpo(req)
        try:
            async with p.motor.ocupar("teclear"):
                n = await p.motor.teclear(str(datos.get("texto", "")))
            return {"pulsaciones": n}
        except Exception as e:
            raise fallo(e) from e

    @app.post("/api/atajo")
    async def api_atajo(req: Request):
        de_claude(req)
        p, datos = puente(req), await cuerpo(req)
        try:
            veces = max(1, min(int(datos.get("veces", 1)), 200))
            async with p.motor.ocupar(f"atajo {datos.get('atajo')}"):
                await p.motor.atajo(str(datos.get("atajo", "")), veces=veces)
            return {"ok": True}
        except Exception as e:
            raise fallo(e) from e

    @app.post("/api/ir_a_linea")
    async def api_ir_a_linea(req: Request):
        de_claude(req)
        p, datos = puente(req), await cuerpo(req)
        try:
            async with p.motor.ocupar("ir a línea"):
                await p.motor.ir_a_linea(int(datos["linea"]))
            return {"ok": True}
        except Exception as e:
            raise fallo(e) from e

    # ── el teclado del Mac: medirlo (Claude) ────────────────────────────────
    # Activar una medida no está aquí: lo hace la persona en Ajustes
    # (`/api/ajustes`), como elegir cualquier otra distribución.
    @app.get("/api/teclado")
    async def api_teclado(req: Request):
        p = puente(req)
        return {"activa": p.ajustes["perfil"].get("distribucion", "mac-us"),
                "reservadas": p.ajustes["perfil"].get("reservadas", []),
                "disponibles": teclados.disponibles(), "medidas": teclados.medidas()}

    @app.post("/api/teclado/sondear")
    async def api_teclado_sondear(req: Request):
        de_claude(req)
        p = puente(req)
        try:
            async with p.motor.ocupar("sondear el teclado"):
                p.control.comprobar()  # antes de apuntar nada: sin control, no se teclea
                p.bitacora.apuntar("teclado", f"sondeo del teclado: {teclados.LINEAS_SONDEO} líneas")
                n = await p.motor.pulsar(teclados.sondeo(p.motor.reservadas()))
            mediciones.apuntar("calibracion", evento="sondeo", lineas=teclados.LINEAS_SONDEO, ok=True)
            return {"pulsaciones": n, "lineas": teclados.LINEAS_SONDEO}
        except Exception as e:
            raise fallo(e) from e

    @app.post("/api/teclado/medir")
    async def api_teclado_medir(req: Request):
        de_claude(req)
        p, datos = puente(req), await cuerpo(req)
        try:
            if datos.get("lectura"):
                ens = lecturas.ensamblar(lecturas.cargar(str(datos["lectura"])))
                if not ens.completo:
                    raise ValueError("la lectura del sondeo no está entera (páginas sin transcribir, huecos o "
                                     "conflictos): termínala antes de medir")
                lineas = ens.lineas
            else:
                lineas = str(datos.get("texto", ""))
            b = teclados.guardar(teclados.construir(lineas, str(datos.get("nombre", ""))))
        except FileNotFoundError as e:
            raise HTTPException(404, "no existe esa lectura") from e
        except Exception as e:
            raise fallo(e) from e
        p.bitacora.apuntar("teclado", f"medida {b['id']} ({b['nombre']}), sin verificar")
        r = teclados.resumen(b)
        mediciones.apuntar("calibracion", evento="medida", lineas=len(lineas) if isinstance(lineas, list) else
                           len(lineas.splitlines()), caracteres=r["caracteres"], verificados=r["verificados"],
                           faltan=len(r["faltan_ascii"]), elegible=r["elegible"], ok=True)
        return r

    @app.post("/api/teclado/probar")
    async def api_teclado_probar(req: Request):
        de_claude(req)
        p, datos = puente(req), await cuerpo(req)
        try:
            b = teclados.cargar(str(datos.get("medida", "")))
            texto, ronda = teclados.consulta(b, str(datos.get("motor") or "SQL Server"), p.motor.reservadas())
            async with p.motor.ocupar("probar el teclado medido"):
                p.control.comprobar()  # antes de apuntar nada: sin control, no se teclea
                p.bitacora.apuntar("teclado", f"consulta de prueba de {b['id']}, ronda {ronda['n']}: "
                                   f"{len(ronda['filas'])} filas")
                try:
                    n = await p.motor.teclear(texto, apuntar=False,
                                              distribucion=teclados.distribucion_del_borrador(b))
                finally:
                    # Lo siguiente es de la persona, haya salido entera o no: ejecutarla, o
                    # borrar lo que quedó a medias. Claude nunca ejecuta: se lo pide y
                    # acaba su turno, y su `Stop` le devuelve el Mac (C-0486).
                    p.al_acabar_tarea("terminó de teclear la consulta de prueba del teclado: el Mac vuelve a "
                                      "ti para ejecutarla")
                # Sólo ahora: unas huellas de una consulta que no se tecleó entera no valen.
                teclados.empezar_ronda(b, ronda)
                teclados.guardar(b)
            mediciones.apuntar("calibracion", evento="prueba", ronda=ronda["n"], filas=len(ronda["filas"]),
                               caracteres=len(ronda["pasos"]), ok=True)
            return {"pulsaciones": n, "ronda": ronda["n"], "filas": len(ronda["filas"]),
                    "caracteres": len(ronda["pasos"])}
        except Exception as e:
            raise fallo(e) from e

    @app.post("/api/teclado/comprobar")
    async def api_teclado_comprobar(req: Request):
        de_claude(req)
        p, datos = puente(req), await cuerpo(req)
        try:
            b = teclados.cargar(str(datos.get("medida", "")))
            r = teclados.comprobar(b, datos.get("huellas") or "")
            teclados.guardar(b)
        except Exception as e:
            raise fallo(e) from e
        p.bitacora.apuntar("teclado", f"{b['id']}: {r['verificados']} caracteres verificados ({r['estado']})")
        filas = r.get("filas") or []
        mediciones.apuntar("calibracion", evento="comprobacion", filas=len(filas), verificados=r["verificados"],
                           no_cuadran=sum(1 for f in filas if f.get("estado") == "no coincide"),
                           faltan=len(r["faltan_ascii"]), elegible=r["elegible"], ok=True)
        return r

    @app.post("/api/clic")
    async def api_clic(req: Request):
        de_claude(req)
        p, datos = puente(req), await cuerpo(req)
        try:
            async with p.motor.ocupar("clic"):
                await p.motor.clic(int(datos["x"]), int(datos["y"]), datos.get("boton", "izquierdo"),
                                   bool(datos.get("doble")))
            return {"ok": True}
        except Exception as e:
            raise fallo(e) from e

    @app.post("/api/rueda")
    async def api_rueda(req: Request):
        de_claude(req)
        p, datos = puente(req), await cuerpo(req)
        try:
            async with p.motor.ocupar("rueda"):
                x, y = datos.get("x"), datos.get("y")
                await p.motor.rueda(int(datos.get("pasos", 1)),
                                    None if x is None else int(x), None if y is None else int(y))
            return {"ok": True}
        except Exception as e:
            raise fallo(e) from e

    def _zona(p: Puente, datos: dict) -> tuple[int, int, int, int]:
        try:
            x, y, w, h = (int(datos[k]) for k in ("x", "y", "ancho", "alto"))
        except (KeyError, TypeError, ValueError) as e:
            raise ValueError("la zona va en píxeles reales del Mac: x, y, ancho y alto") from e
        ancho = getattr(p.dispositivo, "ancho", 1920) or 1920
        alto = getattr(p.dispositivo, "alto", 1080) or 1080
        if w < 50 or h < 50:
            raise ValueError("la zona es demasiado pequeña (50×50 como poco)")
        if x < 0 or y < 0 or x + w > ancho or y + h > alto:
            raise ValueError(f"la zona se sale de la pantalla, que mide {ancho}×{alto}")
        return x, y, w, h

    @app.post("/api/recorrer")
    async def api_recorrer(req: Request):
        de_claude(req)
        p, datos = puente(req), await cuerpo(req)
        try:
            zona = _zona(p, datos)
            pasos = max(1, min(int(datos.get("pasos", 5)), RECORRIDO_PASOS))
            tope = max(1, min(int(datos.get("max_paginas", 10)), RECORRIDO_PAGINAS))
            async with p.motor.ocupar("recorrer la pantalla"):
                r = await p.motor.recorrer(zona, pasos=pasos, tope=tope)
        except Exception as e:
            raise fallo(e) from e

        def png(img: Image.Image) -> bytes:
            buf = io.BytesIO()
            img.save(buf, "PNG")
            return buf.getvalue()
        ident = uuid.uuid4().hex[:12]
        p.recorrido = (ident, [await asyncio.to_thread(png, img) for img in r.paginas])
        return {"id": ident, "paginas": len(r.paginas), "subio": r.subio, "final": r.final, "pasos": r.pasos}

    @app.get("/api/recorridos/{ident}/{n}.png")
    async def api_recorrido(req: Request, ident: str, n: int):
        actual, paginas = puente(req).recorrido
        if ident != actual:
            raise HTTPException(404, "ese recorrido ya no está: lo sustituyó otro más nuevo")
        if not 1 <= n <= len(paginas):
            raise HTTPException(404, f"el recorrido tiene {len(paginas)} páginas")
        return Response(paginas[n - 1], media_type="image/png", headers={"Cache-Control": "no-store"})

    # ── lecturas ────────────────────────────────────────────────────────────
    @app.post("/api/lecturas")
    async def api_nueva_lectura(req: Request):
        de_claude(req)
        p, datos = puente(req), await cuerpo(req)
        nombre = str(datos.get("nombre") or "documento").strip()[:80]
        try:
            # Sin zona, la región del editor del perfil. Con ella, otra ventana
            # (el texto plano donde se sondea el teclado, C-0482): las cuatro o
            # ninguna, para no leer media pantalla sin querer.
            dadas = [k for k in ("x", "y", "ancho", "alto") if k in datos]
            zona = _zona(p, datos) if dadas else None
            p.control.comprobar()
        except Exception as e:
            raise fallo(e) from e
        if p.motor.tarea:
            raise HTTPException(409, f"ya estoy con: {p.motor.tarea}")
        l = lecturas.nueva(nombre)

        async def correr():
            inicio = time.monotonic()
            try:
                async with p.motor.ocupar(f"leer «{nombre}»"):
                    await lecturas.capturar(p.motor, l, zona=zona)
                # Si el encargo sigue (otra lectura si la captura salió mal, una
                # escritura), el control sigue con Claude hasta su `Stop` (C-0486).
                p.al_acabar_tarea("terminó de capturar: el Mac vuelve a ti")
            except Ocupado as e:
                l.estado, l.error = "error", str(e)
                l.guardar()
            # Cuántas páginas y cómo acabó: ni el nombre ni la zona.
            mediciones.apuntar("lectura", evento="captura", ms=round((time.monotonic() - inicio) * 1000),
                               paginas=len(l.paginas), inestables=sum(pg.inestable for pg in l.paginas),
                               estado=l.estado if l.estado in ("capturada", "cortada", "error") else None,
                               con_zona=zona is not None)

        p.en_segundo_plano(correr())
        await asyncio.sleep(0.05)
        return {"id": l.id, "url": f"/lecturas/{l.id}"}

    @app.get("/api/lecturas/{id_}")
    async def api_lectura(id_: str):
        try:
            l = lecturas.cargar(id_)
        except Exception as e:
            raise HTTPException(404, "no existe esa lectura") from e
        return {**lecturas.resumen(l),
                "paginas_detalle": [{"n": pg.n, "transcrita": pg.transcrita, "quien": pg.quien,
                                     "primera": pg.primera, "ultima": pg.ultima,
                                     "png": str(l.png(pg.n))} for pg in l.paginas]}

    @app.get("/api/lecturas/{id_}/paginas/{n}.png")
    async def api_pagina_png(id_: str, n: int):
        try:
            ruta = lecturas.cargar(id_).png(n)
        except Exception as e:
            raise HTTPException(404, "no existe") from e
        if not ruta.exists():
            raise HTTPException(404, "no existe esa página")
        return FileResponse(ruta, media_type="image/png")

    @app.get("/api/lecturas/{id_}/texto", response_class=PlainTextResponse)
    async def api_lectura_texto(id_: str):
        try:
            l = lecturas.cargar(id_)
        except Exception as e:
            raise HTTPException(404, "no existe esa lectura") from e
        return lecturas.texto_ensamblado(l)

    @app.post("/api/lecturas/{id_}/paginas/{n}")
    async def api_transcribir(req: Request, id_: str, n: int):
        datos = await cuerpo(req)
        quien = "persona" if mismo_origen(req) else "claude"
        de_claude(req)
        try:
            l = lecturas.cargar(id_)
            pg = lecturas.transcribir(l, n, str(datos.get("texto", "")), quien)
            ens = lecturas.ensamblar(l)
            p = puente(req)
            p.bitacora.apuntar("transcripcion", f"«{l.nombre}» página {n} ({pg.primera}–{pg.ultima})",
                               quien=quien, lectura=l.id)
            conflictos = [c for c in ens.conflictos if pg.primera <= c["linea"] <= pg.ultima]
            mediciones.apuntar("lectura", evento="transcripcion", quien=quien, errores=len(pg.errores),
                               conflictos=len(conflictos))
            return {"pagina": n, "primera": pg.primera, "ultima": pg.ultima, "errores": pg.errores,
                    "conflictos": conflictos}
        except Exception as e:
            raise fallo(e) from e

    @app.post("/api/lecturas/{id_}/resolver")
    async def api_resolver(req: Request, id_: str):
        de_claude(req)
        datos = await cuerpo(req)
        try:
            l = lecturas.cargar(id_)
            lecturas.resolver(l, int(datos["linea"]), str(datos["texto"]))
            puente(req).bitacora.apuntar(
                "resolucion", f"«{l.nombre}» línea {datos['linea']}",
                quien="persona" if mismo_origen(req) else "claude", lectura=l.id)
            return lecturas.resumen(l)
        except Exception as e:
            raise fallo(e) from e

    @app.post("/api/lecturas/{id_}/huella")
    async def api_huella_lectura(req: Request, id_: str):
        de_claude(req)
        datos = await cuerpo(req)
        try:
            l = lecturas.cargar(id_)
            r = lecturas.comprobar_huella(l, str(datos.get("referencia", "")))
            puente(req).bitacora.apuntar(
                "huella", f"«{l.nombre}»: {'EXACTA' if r['verificada'] else 'no coincide'}",
                quien="persona" if mismo_origen(req) else "claude", lectura=l.id)
            mediciones.apuntar("lectura", evento="huella", ok=bool(r["verificada"]), completo=bool(r["completo"]),
                               quien="persona" if mismo_origen(req) else "claude")
            return r
        except Exception as e:
            raise fallo(e) from e

    # ── cambios ─────────────────────────────────────────────────────────────
    @app.post("/api/cambios")
    async def api_proponer(req: Request):
        de_claude(req)
        datos = await cuerpo(req)
        try:
            l = lecturas.cargar(str(datos["lectura"]))
            m = puente(req).motor
            c = cambios.proponer(l, str(datos["texto"]), str(datos.get("descripcion") or "cambio"),
                                 m.distribucion(), m.reservadas())
            p = puente(req)
            p.bitacora.apuntar(
                "propuesta", f"{c.descripcion}: {len(c.tramos)} {'tramo' if len(c.tramos) == 1 else 'tramos'}"
                + (" (sobre una lectura sin verificar)" if c.sin_verificar else ""), cambio=c.id)
            lineas, caracteres = cambios.medida(c)
            # Antes de aprobarla por el permiso: la propuesta va antes que su aprobación.
            mediciones.apuntar("cambio", evento="propuesta", tramos=len(c.tramos), ok=True, fallo="ninguno",
                               sin_verificar=bool(c.sin_verificar), lineas=lineas, caracteres=caracteres)
            permiso = p.control.permiso_vigente()
            motivo = cambios.cabe(c, permiso) if permiso else None
            if permiso and motivo is None:
                p.aprobar_cambio(c, permiso)
                aviso = ("Aprobado por su permiso de correcciones pequeñas: escríbelo (escribir_cambio) y "
                         "avísale de qué corregiste.")
            elif permiso:
                aviso = (f"No cabe en su permiso de correcciones pequeñas ({motivo}): espera a que la "
                         "persona lo apruebe en la pantalla del puente. No lo partas para que quepa.")
            else:
                aviso = "Espera a que la persona lo apruebe en la pantalla del puente."
            if c.sin_verificar:
                aviso = ("La lectura de la que parte está sin verificar con la huella de la base: los "
                         "tramos se calcularon contra lo transcrito, que puede tener errores. Díselo a "
                         "la persona" + (" al avisarle. " if c.estado == "aprobado" else " antes de que apruebe. ")
                         + aviso)
            return {"id": c.id, "url": f"/cambios/{c.id}", "tramos": len(c.tramos),
                    "estado": c.estado, "lectura_verificada": not c.sin_verificar, "aviso": aviso,
                    "aprobado_por": c.aprobado_por if c.estado == "aprobado" else None,
                    "lineas": lineas, "caracteres": caracteres, "cabe": motivo}
        except Exception as e:
            mediciones.apuntar("cambio", evento="propuesta", ok=False,
                               fallo="intraducible" if isinstance(e, hid.TextoIntraducible) else "otro")
            raise fallo(e) from e

    @app.get("/api/cambios/{id_}")
    async def api_cambio(id_: str):
        try:
            c = cambios.cargar(id_)
        except Exception as e:
            raise HTTPException(404, "no existe ese cambio") from e
        return {"id": c.id, "descripcion": c.descripcion, "estado": c.estado, "error": c.error,
                "lectura": c.lectura, "huella_esperada": c.huella_esperada,
                "lectura_verificada": not c.sin_verificar,
                "tramos": [{"i": t.i, "desde": t.desde, "hasta": t.hasta, "estado": t.estado,
                            "antes": t.antes, "nuevas": t.nuevas, "captura_inestable": t.captura_inestable,
                            "franja": t.franja,
                            "png": str(c.png(t.i)) if c.png(t.i).exists() else None}
                           for t in c.tramos]}

    @app.get("/api/cambios/{id_}/tramos/{i}.png")
    async def api_tramo_png(id_: str, i: int):
        try:
            ruta = cambios.cargar(id_).png(i)
        except Exception as e:
            raise HTTPException(404, "no existe ese cambio") from e
        if not ruta.exists():
            raise HTTPException(404, "sin captura")
        return FileResponse(ruta, media_type="image/png")

    @app.post("/api/cambios/{id_}/aprobar")
    async def api_aprobar(req: Request, id_: str):
        de_la_persona(req)
        try:
            c = cambios.cargar(id_)
            puente(req).aprobar_cambio(c)  # mide él: aquí sería contarlo dos veces
            return {"estado": c.estado}
        except Exception as e:
            raise fallo(e) from e

    @app.post("/api/cambios/{id_}/rechazar")
    async def api_rechazar(req: Request, id_: str):
        de_la_persona(req)
        try:
            c = cambios.cargar(id_)
            cambios.rechazar(c)
            puente(req).bitacora.apuntar("aprobacion", f"{c.descripcion}: rechazado", quien="persona",
                                         cambio=c.id)
            mediciones.apuntar("cambio", evento="rechazado", tramos=len(c.tramos),
                               ms=round(max(0.0, time.time() - c.creado) * 1000))
            return {"estado": c.estado}
        except Exception as e:
            raise fallo(e) from e

    @app.post("/api/cambios/{id_}/escribir")
    async def api_escribir(req: Request, id_: str):
        de_claude(req)
        p = puente(req)
        quien = "persona" if mismo_origen(req) else "claude"
        try:
            c = cambios.cargar(id_)
            # Primero si se puede escribir (400) y luego el control (423), como siempre.
            cambios.escribible(c, p.control.permiso_vigente())
            p.control.comprobar()
            if p.motor.tarea:
                raise Ocupado(f"ya estoy con: {p.motor.tarea}")
        except Exception as e:
            raise fallo(e) from e

        async def correr():
            try:
                async with p.motor.ocupar(f"escribir «{c.descripcion}»"):
                    # El permiso de ahora, no el de la petición: se vuelve a mirar al empezar.
                    await cambios.escribir(p.motor, c, quien, p.control.permiso_vigente())
                # Revisar y guardar es de la persona, pero al acabar el encargo: con
                # dos párrafos, el segundo también es de Claude (C-0486).
                p.al_acabar_tarea("terminó de escribir: el Mac vuelve a ti para revisar y guardar")
            except Ocupado as e:
                c.estado, c.error = "fallido", str(e)
                c.guardar()
            except ValueError as e:  # `escribible`: la concesión acabó entre la petición y ahora
                p.bitacora.apuntar("error", f"{c.descripcion}: {e}", quien="puente", cambio=c.id)

        p.en_segundo_plano(correr())
        await asyncio.sleep(0.05)
        return {"id": c.id, "estado": "escribiendo"}

    @app.post("/api/cambios/{id_}/huella")
    async def api_huella_cambio(req: Request, id_: str):
        de_claude(req)
        datos = await cuerpo(req)
        try:
            c = cambios.cargar(id_)
            r = cambios.comprobar_huella(c, str(datos.get("referencia", "")))
            puente(req).bitacora.apuntar(
                "huella", f"{c.descripcion}: {'coincide' if r['verificado'] else 'NO coincide'}",
                quien="persona" if mismo_origen(req) else "claude", cambio=c.id)
            mediciones.apuntar("cambio", evento="huella", ok=bool(r["verificado"]),
                               quien="persona" if mismo_origen(req) else "claude")
            return r
        except Exception as e:
            raise fallo(e) from e

    # ── ajustes y simulador (la persona) ────────────────────────────────────
    @app.post("/api/ajustes")
    async def api_ajustes(req: Request):
        de_la_persona(req)
        p, datos = puente(req), await cuerpo(req)
        # Un «false» como texto no es apagarlas: con `is not False` las dejaría
        # encendidas sin decir nada. Lo que no es verdadero o falso, ni se mira.
        med = datos.get("mediciones", {})
        if not isinstance(med, dict) or ("activas" in med and not isinstance(med["activas"], bool)):
            raise HTTPException(400, "«mediciones.activas» va como verdadero o falso (true o false), no como texto")
        # El interruptor de las mediciones, solo, no cambia nada de lo que se hace
        # en el Mac: se puede apagar con una tarea en marcha.
        solo_mediciones = bool(datos) and set(datos) <= {"mediciones"}
        # Antes de tocar nada: con una tarea en marcha, unos ajustes nuevos
        # cambiarían los atajos o el aparato a mitad de escribir.
        if p.motor.tarea and not solo_mediciones:
            raise HTTPException(409, f"hay una tarea en marcha ({p.motor.tarea}): espera a que acabe o pulsa Parar")
        if (p.grabadora.actual is not None
                and {**p.ajustes["dispositivo"], **datos.get("dispositivo", {})} != p.ajustes["dispositivo"]):
            raise HTTPException(409, "se está grabando una reunión: pulsa «Salí de la reunión» antes de cambiar el aparato")
        try:
            nuevos = config.leer_ajustes()
            for seccion in ("dispositivo", "perfil", "claude", "mediciones"):
                nuevos[seccion].update(datos.get(seccion, {}))
            # Sólo esa clave, y verdadero o falso: lo de más no se guarda.
            nuevos["mediciones"] = {"activas": nuevos["mediciones"].get("activas", True) is not False}
            config.validar_modelo(nuevos["claude"]["modelo"])
            nuevos["claude"]["saltar_permisos"] = nuevos["claude"].get("saltar_permisos") is True
            if nuevos["perfil"].get("distribucion", "mac-us") not in {d["id"] for d in teclados.disponibles()}:
                raise ValueError("distribución de teclado desconocida, o una medida sin verificar")
            reservadas = nuevos["perfil"].get("reservadas", [])
            if not isinstance(reservadas, list) or len(reservadas) > 20:
                raise ValueError("las teclas reservadas van en una lista, como «alt+x»")
            # Escritas como las escribe el puente («option+x» → «alt+x»), sin repetir.
            nuevos["perfil"]["reservadas"] = list(dict.fromkeys(str(hid.combinacion(str(r))) for r in reservadas))
            for clave in ("inicio_documento", "fin_documento", "pagina_abajo", "ir_a_linea", "fin_de_linea"):
                hid.combinacion(nuevos["perfil"][clave])
            r = [int(v) for v in nuevos["perfil"]["region_editor"]]
            if len(r) != 4 or r[2] < 50 or r[3] < 50:
                raise ValueError("la región del editor tiene que ser x, y, ancho, alto")
            nuevos["perfil"]["region_editor"] = r
            nuevos["perfil"]["aparcar_raton"] = [int(v) for v in nuevos["perfil"]["aparcar_raton"]]
            nuevos["perfil"]["retardo_tecla_ms"] = max(2, min(int(nuevos["perfil"]["retardo_tecla_ms"]), 200))
            # En el perfil y no en el aparato: cambiarlo en «dispositivo» lo reconectaría (C-0485).
            nuevos["perfil"]["retardo_video_ms"] = max(0, min(int(nuevos["perfil"].get(
                "retardo_video_ms", config.PERFIL_POR_OMISION["retardo_video_ms"])), RETARDO_VIDEO_MAX_MS))
            nuevos["perfil"]["invertir_rueda"] = nuevos["perfil"].get("invertir_rueda") is True
            config.guardar_ajustes(nuevos)
        except Exception as e:
            raise fallo(e) from e
        cambia_aparato = nuevos["dispositivo"] != p.ajustes["dispositivo"]
        p.ajustes = nuevos
        p.motor.perfil = nuevos["perfil"]
        if cambia_aparato:
            p.devolver_control("cambió el aparato: el control vuelve a la persona", por="aparato")
            with contextlib.suppress(Exception):
                await p.dispositivo.cerrar()
            p.dispositivo = crear_dispositivo(nuevos)
            p.dispositivo.avisar = p.aviso_del_aparato
            p.motor.dispositivo = p.dispositivo
            p.grabadora.dispositivo = p.dispositivo
            await p.conectar(por="ajustes")
        if solo_mediciones:
            p.bitacora.apuntar("ajustes", "mediciones de uso " + ("encendidas" if nuevos["mediciones"]["activas"]
                                                                 else "apagadas"), quien="persona")
        else:
            p.bitacora.apuntar("ajustes", "ajustes guardados" + (" y aparato cambiado" if cambia_aparato else ""),
                               quien="persona")
        return {"ok": True, "error_conexion": p.error_conexion, "mediciones": mediciones.estado()}

    @app.get("/api/diagnostico")
    async def api_diagnostico():
        # En otro hilo: el informe le pregunta su estado a este mismo puente por HTTP.
        return {"texto": await asyncio.to_thread(comprobar.informe, True)}

    @app.post("/api/reconectar")
    async def api_reconectar(req: Request):
        de_la_persona(req)
        p = puente(req)
        if p.motor.tarea:
            raise HTTPException(409, f"hay una tarea en marcha ({p.motor.tarea}): espera a que acabe o pulsa Parar")
        # Con «Reconectar» siempre en el panel (C-0477), un clic suelto no puede
        # cortar el sonido de una reunión que se graba: su audio va en esta conexión.
        if p.grabadora.actual is not None or p.grabadora.empezando:
            raise HTTPException(409, "se está grabando una reunión: reconectar cortaría su sonido. "
                                     "Termínala y vuelve a pulsar «Reconectar»")
        # Tras reconectar, lo que hay al otro lado puede no ser lo que era.
        p.devolver_control("se reconectó el aparato: el control vuelve a la persona", por="aparato")
        with contextlib.suppress(Exception):
            await p.dispositivo.cerrar()
        await p.conectar(por="reconectar")
        return {"error_conexion": p.error_conexion}

    # ── reiniciar el puente (C-0470, decisión 446 del hub): sólo la persona, con su botón ──
    @app.post("/api/reiniciar")
    async def api_reiniciar(req: Request):
        """El botón del aviso de código viejo. No corta nada a medias: lo mismo que
        mira `servicio.sh reiniciar --si-libre`. Sólo con systemd: sin él, el
        puente no puede volver a arrancarse igual que arrancó."""
        de_la_persona(req)
        p = puente(req)
        if time.monotonic() < p.reinicio_hasta:
            raise HTTPException(409, "Ya se está reiniciando: la página vuelve sola en unos segundos.")
        motivo = comprobar.ocupado(estado(p))
        if motivo:
            raise HTTPException(409, f"No lo reinicio ahora: {motivo}. Cuando acabe, vuelve a pulsar «Reiniciar "
                                     "el puente».")
        if await asyncio.to_thread(reinicio.como) != "systemd":
            raise HTTPException(409, "Este puente no corre como su servicio de systemd, así que no puede "
                                     "reiniciarse solo: ciérralo y vuelve a lanzar scripts/arrancar.sh.")
        p.reinicio_hasta = time.monotonic() + REINICIO_EN_CURSO
        p.bitacora.apuntar("reinicio", "la persona reinicia el puente", quien="persona")

        def pedir() -> None:
            if not reinicio.pedir():
                p.reinicio_hasta = 0.0  # systemd no lo aceptó: que se pueda volver a pulsar
        # Después de contestar: el reinicio para este proceso, y la respuesta tiene que llegar antes.
        return JSONResponse({"arrancado": reinicio.ARRANQUE}, background=BackgroundTask(pedir))

    # ── el jiggler y despertar el Mac (C-0463): la persona y Claude, por la misma ruta ──
    # El origen dice quién: con el de esta web es la persona; sin él, el MCP.
    @app.post("/api/jiggler")
    async def api_jiggler(req: Request):
        de_claude(req)
        p, datos = puente(req), await cuerpo(req)
        try:
            encendido = datos.get("encendido")
            if not isinstance(encendido, bool):
                raise ValueError("falta «encendido»: true o false")  # nunca «alternar»: dos pestañas lo deshacen
            config_ = None
            if encendido:
                horario = str(datos.get("horario") or "").strip()
                zona = str(datos.get("zona") or "").strip()
                inactividad = datos.get("inactividad_s")
                # La zona contra las del aparato: una que no tenga, la cambia por UTC sin decirlo.
                if zona and zona != "UTC" and zona not in await p.dispositivo.zonas():
                    raise ValueError(f"el JetKVM no conoce la zona «{zona}»: va como «America/Mexico_City»")
                actual = (await p.dispositivo.leer_jiggler()).get("config")
                config_ = jiggler.config_nueva(actual, horario, zona,
                                               None if inactividad in (None, "") else int(inactividad))
            elif datos.get("horario") or datos.get("zona"):
                raise ValueError("para apagarlo no hace falta horario")
            leido = await p.dispositivo.poner_jiggler(encendido, config_)
        except Exception as e:
            raise fallo(e) from e
        texto = jiggler.describir(leido)
        p.bitacora.apuntar("jiggler", f"jiggler: {texto}", quien="persona" if mismo_origen(req) else "claude")
        return {"ok": True, "jiggler": leido, "texto": texto}

    @app.post("/api/despertar")
    async def api_despertar(req: Request):
        de_claude(req)
        p = puente(req)
        persona = mismo_origen(req)
        try:
            if not persona:
                p.control.comprobar()  # despertar es actuar sobre el Mac: Claude, sólo con el control
            if p.motor.tarea:
                raise Ocupado(f"hay una tarea en marcha ({p.motor.tarea}): espera o pulsa Parar")
            # Sin `motor.ocupar`: la espera dura segundos, y con el cerrojo el mando
            # echaría a la persona del Mac al primer movimiento del ratón.
            r = await p.dispositivo.despertar()
        except Exception as e:
            raise fallo(e) from e
        if r.get("ya_despierto"):
            texto = "El Mac ya estaba despierto."
        elif r.get("imagen"):
            texto = "El Mac despertó: ya hay imagen."
        elif r.get("antes") == "suspended" and r.get("despues") not in ("suspended", None):
            texto = "El Mac despertó, pero aún no llega su imagen: puede tardar unos segundos."
        else:
            texto = ("Mandé la señal de despertar, pero el Mac no respondió. "
                     "Si está apagado (no en reposo), desde aquí no se enciende.")
        p.bitacora.apuntar("despertar", texto, quien="persona" if persona else "claude")
        return {"ok": True, "despierto": bool(r.get("imagen")), "texto": texto, **r}

    # ── una reunión (C-0461): sólo la persona, con su botón; ni Claude ni el hub ──
    @app.post("/api/reunion/empezar")
    async def api_reunion_empezar(req: Request):
        de_la_persona(req)
        p, datos = puente(req), await cuerpo(req)
        if p.motor.tarea:
            # Empezar puede reconectar el aparato, y eso cortaría lo que hace Claude.
            raise HTTPException(409, f"Claude está con una tarea ({p.motor.tarea}): espera a que acabe o pulsa "
                                     "Parar, y vuelve a pulsar «Estoy en reunión»")

        async def reconectar():
            # Como «Reconectar»: con lo que haya al otro lado recién conectado, el
            # control vuelve a la persona; y dentro de `ocupar`, Claude no empieza
            # nada mientras tanto (y si tenía algo suelto en marcha, no se corta).
            async with p.motor.ocupar("conectar el sonido de la reunión"):
                p.devolver_control("empieza una reunión: el puente reconecta el aparato y el control vuelve a la persona",
                                   por="reunion")
                await p.conectar(por="reunion")
            if p.error_conexion:
                raise AparatoNoDisponible(p.error_conexion)

        try:
            g = await p.grabadora.empezar(str(datos.get("titulo") or ""), reconectar)
        except Exception as e:
            raise fallo(e) from e
        p.bitacora.apuntar("reunion", f"empieza a grabar una reunión ({g.id})", quien="persona")
        return p.grabadora.estado()

    @app.post("/api/reunion/parar")
    async def api_reunion_parar(req: Request):
        de_la_persona(req)
        p = puente(req)
        try:
            r = await p.grabadora.parar()
        except Exception as e:
            raise fallo(e) from e
        p.bitacora.apuntar("reunion", f"termina la reunión {r['id']}: {r['segundos'] // 60} min, {r['fotos']} "
                           "fotos" + ("" if r["con_sonido"] else ", sin que llegara sonido"), quien="persona")
        return r

    @app.post("/api/simulador/guardar")
    async def api_sim_guardar(req: Request):
        """Lo que en el Mac haría la persona: guardar (ejecutar el ALTER)."""
        de_la_persona(req)
        p = puente(req)
        if p.dispositivo.tipo != "simulador":
            raise HTTPException(400, "sólo en el simulador")
        p.dispositivo.editor.guardar()  # type: ignore[attr-defined]
        p.bitacora.apuntar("simulador", "la persona guarda en la base (Cmd+S)", quien="persona")
        return p.dispositivo.estado()

    # ── qué sabe y qué hace Claude ──────────────────────────────────────────
    @app.post("/api/claude/actividad")
    async def api_actividad(req: Request):
        # La mandan los hooks de Claude Code (sin Origin). Sólo se guarda el resumen.
        de_claude(req)
        datos = await cuerpo(req)
        p = puente(req)
        if datos.get("hook_event_name") == "UserPromptSubmit":
            # Su `session_id` es el de la conversación del puente: se usó ahora.
            conversaciones.tocar(datos.get("session_id"))
        p.fin_de_turno(datos)  # antes de registrar: necesita el turno anterior
        try:
            p.medir_turno(datos)
        except Exception as e:  # medir no le quita el hook a lo que decide el control
            print(f"[mediciones] el turno no se pudo contar: {type(e).__name__}", flush=True)
        return p.actividad.registrar(datos)

    # ── las mediciones de uso (C-0483) ──────────────────────────────────────
    @app.get("/api/mediciones")
    async def api_mediciones():
        return mediciones.estado()

    @app.post("/api/mediciones/herramienta")
    async def api_medir_herramienta(req: Request):
        # La manda el MCP tras cada herramienta (sin Origin), como los hooks.
        de_claude(req)
        try:
            puente(req).medir_herramienta(await cuerpo(req))
        except mediciones.NoValida as e:
            raise HTTPException(400, str(e)) from e
        return {"ok": True}

    @app.post("/api/mediciones/preparar")
    async def api_preparar_mediciones(req: Request):
        """El .zip para mandar. Sólo la persona: lo descarga ella, lo mira y lo manda."""
        de_la_persona(req)
        datos = await asyncio.to_thread(mediciones.empaquetar)
        nombre = f"mediciones-puente-{time.strftime('%Y-%m-%d')}.zip"
        return Response(datos, media_type="application/zip",
                        headers={"Content-Disposition": f'attachment; filename="{nombre}"',
                                 "Cache-Control": "no-store"})

    @app.post("/api/mediciones/borrar")
    async def api_borrar_mediciones(req: Request):
        de_la_persona(req)
        n = await asyncio.to_thread(mediciones.borrar)
        puente(req).bitacora.apuntar("ajustes", f"mediciones de uso borradas ({n} días)", quien="persona")
        return {"borrados": n, **mediciones.estado()}

    @app.get("/api/claude/actividad")
    async def api_ver_actividad(req: Request):
        a = puente(req).actividad
        return {**a.publico(), "eventos": list(a.eventos)[::-1]}

    @app.get("/api/claude/repertorio")
    async def api_repertorio():
        return {"skills": repertorio.skills(), "permisos": repertorio.permisos(),
                "herramientas": await repertorio.herramientas(), "conocimiento": repertorio.conocimiento()}

    # ── las conversaciones con Claude Code (la persona) ─────────────────────
    def estado_conversaciones() -> dict:
        actual = conversaciones.actual()
        # La que dejó una versión anterior del puente: viva en tmux, sin registro.
        anterior = actual is None and terminal.existe()
        return {"actual": actual.publica() if actual else None, "anterior": anterior,
                "lista": [c.publica() for c in conversaciones.todas()],
                "modelo_siguiente": config.texto_modelo(terminal.modelo_elegido()),
                "espacio": str(config.espacio())}

    async def cambiar(req: Request, abrir, aunque_trabaje: bool = False) -> None:
        """Cerrar la abierta y abrir otra: nunca con una tarea en marcha sobre el Mac,
        y el control vuelve a la persona (la otra conversación no sabe qué se le dio).

        Con Claude trabajando (lo dicen sus hooks), cerrarla lo corta a medias:
        409 salvo que la persona lo confirme (`aunque_trabaje`). No es una puerta
        cerrada como la tarea: si Claude Code se cerró sin su último hook, el
        estado se queda en «trabajando» y no habría forma de cambiar. Vale para
        cualquier cambio: reabrir, otra de la lista o una nueva.

        Recién reiniciado el puente sin nada guardado de los hooks («sin
        noticias») y con la conversación viva, no se sabe: se pregunta igual
        (C-0470). «No sé» no es «está libre»."""
        p = puente(req)
        if p.motor.tarea:
            raise HTTPException(409, f"hay una tarea en marcha ({p.motor.tarea}): espera a que acabe o pulsa "
                                     "Parar antes de cambiar de conversación")
        if not aunque_trabaje:
            # La cabecera dice a la pantalla que puede preguntar y repetir.
            if p.actividad.estado == "trabajando":
                raise HTTPException(409, "Claude está trabajando: si cierras la conversación ahora, lo cortas a "
                                         "medias.", headers={"X-Puente-Motivo": "trabajando"})
            if p.actividad.estado == "sin noticias" and await asyncio.to_thread(terminal.existe):
                raise HTTPException(409, "No sé si Claude está a medias: el puente se acaba de reiniciar y aún no "
                                         "ha sabido nada de él. Si estaba trabajando, cerrar la conversación lo "
                                         "corta.", headers={"X-Puente-Motivo": "trabajando"})
        p.devolver_control("se cambió de conversación con Claude: el control vuelve a la persona", por="conversacion")
        try:
            await asyncio.to_thread(abrir)
        except Exception as e:
            raise fallo(e) from e
        # Recién abierta, Claude espera: el que se cerró no manda su `Stop`.
        p.conversacion_reabierta("se cambió de conversación con Claude: el control vuelve a la persona")

    @app.get("/api/conversaciones")
    async def api_conversaciones():
        return await asyncio.to_thread(estado_conversaciones)

    @app.post("/api/conversaciones")
    async def api_nueva_conversacion(req: Request):
        de_la_persona(req)
        datos = await cuerpo(req)
        nombre = str(datos.get("nombre") or "")
        hecha: dict = {}

        def abrir():
            hecha["c"] = terminal.reiniciar(nombre)
        await cambiar(req, abrir, aunque_trabaje=datos.get("aunque_trabaje") is True)
        # Los nombres pueden ser del trabajo: a la bitácora, sin él.
        puente(req).bitacora.apuntar("terminal", "conversación nueva con Claude", quien="persona")
        return conversaciones.buscar(hecha["c"].id).publica()

    def de_la_lista(id_: str) -> conversaciones.Conversacion:
        try:
            conversaciones.validar_id(id_)
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
        c = conversaciones.buscar(id_)
        if c is None:
            raise HTTPException(404, "no existe esa conversación en la lista del puente")
        return c

    @app.post("/api/conversaciones/{id_}/abrir")
    async def api_abrir_conversacion(req: Request, id_: str):
        de_la_persona(req)
        c = de_la_lista(id_)
        await cambiar(req, lambda: terminal.abrir(c, retomar=True),
                      aunque_trabaje=(await cuerpo(req)).get("aunque_trabaje") is True)
        puente(req).bitacora.apuntar("terminal", "se retomó otra conversación con Claude", quien="persona")
        return conversaciones.buscar(id_).publica()

    @app.post("/api/conversaciones/{id_}/renombrar")
    async def api_renombrar_conversacion(req: Request, id_: str):
        de_la_persona(req)
        de_la_lista(id_)
        return conversaciones.renombrar(id_, str((await cuerpo(req)).get("nombre") or "")).publica()

    @app.post("/api/conversaciones/{id_}/quitar")
    async def api_quitar_conversacion(req: Request, id_: str):
        de_la_persona(req)
        c = de_la_lista(id_)
        actual = conversaciones.actual()
        if actual and actual.id == c.id:
            raise HTTPException(409, "es la conversación abierta: cambia a otra antes de quitarla de la lista")
        conversaciones.quitar(c.id)
        return {"ok": True, "aviso": "Quitada de la lista del puente. En Claude Code sigue guardada: no se ha "
                                     "borrado nada (su /resume la encuentra)."}

    # ── la terminal de Claude Code ──────────────────────────────────────────
    @app.post("/api/terminal/reiniciar")
    async def api_terminal_reiniciar(req: Request):
        """La de antes de las conversaciones: una nueva, con su nombre por omisión."""
        de_la_persona(req)
        await cambiar(req, terminal.reiniciar, aunque_trabaje=(await cuerpo(req)).get("aunque_trabaje") is True)
        puente(req).bitacora.apuntar("terminal", "conversación nueva con Claude", quien="persona")
        return {"ok": True}

    @app.websocket("/ws/mando")
    async def ws_mando(ws: WebSocket):
        """La persona usa el Mac desde la pantalla del puente: su ratón y su teclado.

        Mismas puertas que la terminal (nombre y origen de esta web). Abrirlo es
        retomar el Mac (C-0484): sólo lo abre un clic de la persona en «Usar el
        Mac desde aquí», y quien pulsa eso quiere usarlo ya, no buscar antes
        «Retomar». Lo que Claude tuviera en marcha se corta en su siguiente
        tecla (`Control.comprobar`); hasta entonces lo de la persona espera
        (dos manos en el mismo teclado escriben basura): lo de la persona no
        llega al Mac y se le avisa una vez. Si Claude recibe el
        control con esto abierto, no llega nada. 🔴 Lo tecleado no se guarda en
        ningún sitio (puede ser una contraseña del Mac): la bitácora sólo dice
        cuánto rato se usó.
        """
        if not ws_de_esta_web(ws):
            await ws.close(code=4403)
            return
        await ws.accept()
        p: Puente = ws.app.state.puente
        p.mandos += 1
        teclas: list[int] = []
        estado = {"mods": 0, "botones": 0, "x": 0, "y": 0, "desde": 0.0, "esperando": False}
        # Para las mediciones: cuántas, nunca cuáles (C-0483).
        cuenta = {"teclas": 0, "clics": 0, "pegados": 0, "ruedas": 0, "combinaciones": 0, "rechazadas": 0}
        abierto = time.monotonic()
        p.control.estado()  # que caduque antes, si toca: no se retoma lo que ya volvió
        retomo = p.control.modo == "claude"
        if p.control.modo == "claude":
            con_claude = (time.time() - p.control.desde) * 1000
            resumen = p.resumen_correcciones(p.control.permiso_vigente())
            p.olvidar_pendiente()
            p.control.retomar("retomado al usar el Mac desde aquí")
            p.bitacora.apuntar("control", "la persona retoma el Mac al usarlo desde aquí", quien="persona")
            if resumen:
                p.bitacora.apuntar(**resumen)
            mediciones.apuntar("control", evento="devuelto", por="usar_mac", ms_con_claude=round(con_claude))
            with contextlib.suppress(Exception):
                await p.dispositivo.informe_teclado(0, [])  # una tecla de Claude a medias, arriba
            await ws.send_json({"aviso": "Le quitaste el control a Claude: el Mac es tuyo."
                                + (" Lo que estaba haciendo se corta ya." if p.motor.tarea else "")})

        async def soltar() -> None:
            if not (teclas or estado["mods"] or estado["botones"]):
                return
            teclas.clear()
            estado["mods"] = 0
            with contextlib.suppress(Exception):
                await p.dispositivo.informe_teclado(0, [])
            if estado["botones"]:
                estado["botones"] = 0
                with contextlib.suppress(Exception):
                    await p.dispositivo.raton(estado["x"], estado["y"], 0)

        async def pulsar(pulsacion: hid.Pulsacion) -> None:
            retardo = p.ajustes["perfil"].get("retardo_tecla_ms", 12) / 1000
            await p.dispositivo.informe_teclado(pulsacion.modificadores, [pulsacion.tecla])
            await asyncio.sleep(retardo)
            await p.dispositivo.informe_teclado(0, [])
            await asyncio.sleep(retardo)

        try:
            while True:
                m = await ws.receive()
                if m["type"] == "websocket.disconnect":
                    break
                try:
                    orden = json.loads(m.get("text") or "{}")
                    tipo = orden.get("t")
                except (ValueError, AttributeError):
                    continue
                p.control.estado()  # que caduque el control de Claude si toca
                if p.control.modo == "claude":
                    cuenta["rechazadas"] += 1
                    await soltar()
                    await ws.send_json({"no": "Le diste el control a Claude: lo que hagas aquí no llega al Mac."})
                    continue
                if p.motor.tarea:
                    # Sin cerrar: la tarea se corta en su siguiente tecla, o acaba.
                    cuenta["rechazadas"] += 1
                    await soltar()
                    if not estado["esperando"]:
                        estado["esperando"] = True
                        await ws.send_json({"espera": f"Espera un momento: termina «{p.motor.tarea}». "
                                            "Lo que hagas mientras tanto no llega al Mac."})
                    continue
                estado["esperando"] = False
                if not estado["desde"]:
                    estado["desde"] = time.time()
                p.mando_hasta = time.time() + 3
                try:
                    if tipo == "raton":
                        ancho = getattr(p.dispositivo, "ancho", 1920) or 1920
                        alto = getattr(p.dispositivo, "alto", 1080) or 1080
                        estado["x"] = max(0, min(int(orden["x"]), ancho - 1))
                        estado["y"] = max(0, min(int(orden["y"]), alto - 1))
                        botones = int(orden.get("b", 0)) & 0x07
                        if botones & ~estado["botones"]:
                            cuenta["clics"] += 1  # un botón que baja; moverse no cuenta
                        estado["botones"] = botones
                        await p.dispositivo.raton(estado["x"], estado["y"], estado["botones"])
                    elif tipo == "rueda":
                        pasos = max(-127, min(int(orden["pasos"]), 127))  # lo que cabe en un informe
                        if pasos:
                            cuenta["ruedas"] += 1
                            invertir = p.ajustes["perfil"].get("invertir_rueda")
                            await p.dispositivo.girar(-pasos if invertir else pasos)
                    elif tipo == "tecla":
                        codigo = int(orden["codigo"])
                        if not TECLA_MIN <= codigo <= TECLA_MAX:
                            continue
                        abajo = bool(orden.get("abajo"))
                        if codigo >= 0xE0:  # Ctrl, Mayús, ⌥ y ⌘: bits, no teclas
                            bit = 1 << (codigo - 0xE0)
                            estado["mods"] = estado["mods"] | bit if abajo else estado["mods"] & ~bit
                        elif abajo and codigo not in teclas:
                            cuenta["teclas"] += 1
                            teclas.append(codigo)
                            del teclas[:-6]  # el informe lleva como mucho seis
                        elif not abajo and codigo in teclas:
                            teclas.remove(codigo)
                        await p.dispositivo.informe_teclado(estado["mods"], list(teclas))
                    elif tipo == "soltar":
                        await soltar()
                    elif tipo == "combinacion" and orden.get("atajo") in COMBINACIONES_MANDO:
                        cuenta["combinaciones"] += 1
                        await soltar()
                        await pulsar(hid.combinacion(orden["atajo"]))
                    elif tipo == "pegar":
                        texto = str(orden.get("texto", ""))[:5000]
                        await soltar()
                        id_teclado = p.ajustes["perfil"].get("distribucion", "mac-us")
                        try:
                            # Con las reservadas del perfil: pegar un «≈» no puede ejecutar el script.
                            pulsaciones = hid.secuencia(texto, teclados.resolver(id_teclado), p.motor.reservadas())
                        except hid.TextoIntraducible:
                            raise
                        except ValueError as e:  # una medida que ya no se lee: se dice, no se calla
                            await ws.send_json({"no": f"No pegué nada: {e}"})
                            continue
                        cuenta["pegados"] += 1
                        for pulsacion in pulsaciones:
                            await pulsar(pulsacion)
                        # Con qué teclado se tecleó, el de verdad: otra pestaña pudo cambiarlo.
                        await ws.send_json({"hecho": "pegar", "teclado": teclados.nombre_corto(id_teclado)})
                except hid.TextoIntraducible as e:
                    await ws.send_json({"no": f"No pegué nada: {e}"})
                except (KeyError, TypeError, ValueError):
                    continue
                except AparatoNoDisponible as e:
                    await ws.send_json({"no": str(e)})
        except WebSocketDisconnect:
            pass
        finally:
            p.mandos -= 1
            if not p.mandos:
                p.mando_hasta = 0.0  # nadie lo tiene abierto: el Mac ya no está en uso
            await soltar()
            if estado["desde"]:
                minutos = max(1, round((time.time() - estado["desde"]) / 60))
                p.bitacora.apuntar("mando", f"la persona usó el Mac desde la pantalla (~{minutos} min)",
                                   quien="persona")
            mediciones.apuntar("mando", s=round(time.monotonic() - abierto, 1), retomo=retomo, **cuenta)

    @app.websocket("/ws/pantalla")
    async def ws_pantalla(ws: WebSocket):
        """La pantalla del Mac como el vídeo H.264 del aparato, sin recomprimirlo, para
        pintarlo con WebCodecs (C-0469, decisión 449 del hub).

        Primero un texto `{"codec": "avc1.PPCCLL", "ancho", "alto"}` (otra vez si
        cambia el SPS); después, una trama por mensaje binario: byte 0 las marcas
        (bit 0, clave), 8 bytes de marca de tiempo a 90 kHz (big-endian) y la trama
        en Annex B. `{"no": "…"}` si no hay vídeo directo: la página vuelve a las
        imágenes, y con `"otra_vez": true` (cambió el aparato) lo vuelve a pedir
        después. Mirar no es usar el Mac: no cuenta en `comprobar.ocupado`.
        """
        if not ws_de_esta_web(ws):
            await ws.close(code=4403)
            return
        await ws.accept()
        p: Puente = ws.app.state.puente
        aparato = p.dispositivo
        suscripcion = aparato.video_codificado()
        if suscripcion is None:
            with contextlib.suppress(Exception):
                await ws.send_json({"no": "este aparato no da el vídeo directo: la pantalla va por imágenes"})
                await ws.close()
            return

        async def oir() -> None:
            # Lo único que llega es el cierre: así se sabe en el acto, también al
            # parar el puente, y nadie se queda esperando a la siguiente trama.
            while (await ws.receive())["type"] != "websocket.disconnect":
                pass

        oido = asyncio.create_task(oir())
        enviado = None
        try:
            while True:
                siguiente = asyncio.ensure_future(suscripcion.siguiente())
                hecho, _ = await asyncio.wait({siguiente, oido}, timeout=2, return_when=asyncio.FIRST_COMPLETED)
                if oido in hecho:
                    siguiente.cancel()
                    break
                if siguiente not in hecho:
                    siguiente.cancel()
                    if p.dispositivo is not aparato:
                        # No es que no se pueda: la página vuelve a pedirlo, ya al nuevo.
                        await ws.send_json({"no": "cambió el aparato", "otra_vez": True})
                        break
                    continue
                trama = siguiente.result()
                if trama is None:
                    await ws.send_json({"no": suscripcion.motivo or "se acabó el vídeo directo"})
                    break
                if trama.sps != enviado:
                    await ws.send_json({"codec": trama.codec, "ancho": getattr(aparato, "ancho", 0),
                                        "alto": getattr(aparato, "alto", 0)})
                    enviado = trama.sps
                await ws.send_bytes(bytes([1 if trama.clave else 0]) + struct.pack(">Q", trama.marca) + trama.datos)
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            suscripcion.cerrar()
            oido.cancel()
            # Recogida: tras el cierre, `receive` lanza, y una tarea con su excepción
            # sin recoger acaba en el registro como «never retrieved».
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await oido
            with contextlib.suppress(Exception):
                await ws.close()

    @app.websocket("/ws/terminal")
    async def ws_terminal(ws: WebSocket):
        # 🔴 Una shell: el nombre y el origen de ESTA web, o nada.
        if not ws_de_esta_web(ws):
            await ws.close(code=4403)
            return
        await ws.accept()
        try:
            if await asyncio.to_thread(terminal.asegurar_sesion):
                # La abrió ahora el puente: Claude acaba de arrancar y espera su primer mensaje.
                ws.app.state.puente.conversacion_reabierta("Claude Code se volvió a abrir: el control vuelve a ti")
        except Exception as e:
            await ws.send_text(f"\r\n[no se pudo abrir Claude Code: {e}]\r\n")
            await ws.close()
            return
        adjunto = terminal.Adjunto()
        bucle = asyncio.get_running_loop()
        salida: asyncio.Queue[bytes | None] = asyncio.Queue()

        def hay_datos():
            try:
                datos = adjunto.leer()
            except EOFError:
                bucle.remove_reader(adjunto.fd)
                salida.put_nowait(None)
                return
            if datos:
                salida.put_nowait(datos)

        bucle.add_reader(adjunto.fd, hay_datos)

        async def enviar():
            while True:
                datos = await salida.get()
                if datos is None:
                    await ws.close()
                    return
                await ws.send_bytes(datos)

        envio = asyncio.create_task(enviar())
        try:
            while True:
                m = await ws.receive()
                if m["type"] == "websocket.disconnect":
                    break
                if m.get("bytes"):
                    adjunto.escribir(m["bytes"])
                elif m.get("text"):
                    try:
                        orden = json.loads(m["text"])
                        adjunto.redimensionar(int(orden["filas"]), int(orden["columnas"]))
                    except (ValueError, KeyError, TypeError):
                        adjunto.escribir(m["text"].encode())
        except WebSocketDisconnect:
            pass
        finally:
            envio.cancel()
            adjunto.cerrar()

    return app
