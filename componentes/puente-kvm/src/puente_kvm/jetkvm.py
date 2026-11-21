"""El JetKVM de verdad: WebRTC como su propia web, sin navegador de por medio.

Sacado del código del firmware (ver `docs/protocolo-jetkvm.md`) y contrastado
con 0.5.9, 0.5.10 (la última estable) y 0.5.11 (la rama de desarrollo): en lo
que usa este cliente, las tres son iguales. **No probado aún contra un
aparato.** Lo que hace, en orden:

1. Entra con la contraseña (`POST /auth/login-local` → cookie `authToken`).
   🔴 El JetKVM guarda **un solo** token: entrar aquí echa a cualquier
   navegador que tuviera su web abierta, y al revés. La cookie no se guarda en
   disco (es una llave); se entra en cada conexión.
2. Abre la señalización por WebSocket (`/webrtc/signaling/client`), ofrece
   vídeo sólo de recepción y los canales de datos, y recibe la respuesta y los
   candidatos ICE (que pueden llegar antes que la respuesta).
3. Teclado y ratón por el canal binario `hidrpc` (tras el saludo `01 01`);
   la rueda, por JSON-RPC (`wheelReport`), que es lo único que el binario
   ignora.
4. El vídeo llega en H.264 y se decodifica continuamente; `captura()` devuelve
   el último fotograma. No hay ninguna URL de captura en el aparato.
5. El sonido del Mac (para grabar una reunión) llega en G722 si el audio del
   aparato está encendido; sale de la tarjeta de sonido USB que el JetKVM le
   presenta al Mac, no del HDMI (`docs/protocolo-jetkvm.md`).

Una sesión a la vez: si alguien abre la web del JetKVM, el aparato nos echa
(`otherSessionConnected`) y aquí se dice, no se reconecta solo.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import struct
import time

import aiohttp
from PIL import Image

from .dispositivo import AparatoNoDisponible, Dispositivo

# Las versiones del firmware cuyo código se leyó y en las que casa todo lo que
# usa este cliente (inicio de sesión, señalización, canales, HID-RPC, rueda).
# Otra puede funcionar, pero nadie la ha leído: se dice al conectar.
FIRMWARE_CONTRASTADO = ("0.5.9", "0.5.10", "0.5.11")


def aviso_firmware(version: str) -> str:
    if not version:
        return "el JetKVM no dijo su versión de firmware: no se sabe si es una de las contrastadas"
    if version in FIRMWARE_CONTRASTADO:
        return ""
    return (f"firmware {version}: fuera de lo contrastado ({', '.join(FIRMWARE_CONTRASTADO)}). Puede "
            "funcionar; si algo se comporta raro, compáralo con docs/protocolo-jetkvm.md")


class JetKVM(Dispositivo):
    tipo = "jetkvm"

    def __init__(self, url: str, clave: str = ""):
        self.url = url.rstrip("/")
        if not self.url.startswith(("http://", "https://")):
            self.url = "http://" + self.url
        self._clave = clave
        self._http: aiohttp.ClientSession | None = None
        self._ws = None
        self._pc = None
        self._rpc = None
        self._hid = None
        self._hid_suelto = None
        self._tareas: list[asyncio.Task] = []
        self._pendientes: dict[int, asyncio.Future] = {}
        self._n = 0
        self._trama = None
        self._trama_t = 0.0
        self._sin_video = False
        self._pista_audio = None
        self._botones = 0
        self.ancho, self.alto = 1920, 1080
        self.version = ""
        self.conectado = False
        self.motivo = "sin conectar"

    # ── conexión ────────────────────────────────────────────────────────────
    async def conectar(self) -> None:
        from aiortc import RTCConfiguration, RTCPeerConnection, RTCSessionDescription

        await self.cerrar()
        self._http = aiohttp.ClientSession(cookie_jar=aiohttp.CookieJar(unsafe=True),
                                           timeout=aiohttp.ClientTimeout(total=15))
        # Cada respuesta se cierra al salir del `async with`: una sin cerrar
        # retiene su conexión hasta que el recolector pase por ella.
        async with self._http.get(f"{self.url}/device") as r:
            estado = r.status
        if estado == 401:
            if not self._clave:
                raise AparatoNoDisponible("el JetKVM pide contraseña y la variable de la clave está vacía")
            async with self._http.post(f"{self.url}/auth/login-local", json={"password": self._clave}) as r:
                if r.status != 200:
                    raise AparatoNoDisponible(f"el JetKVM rechaza la contraseña ({r.status})")
        elif estado != 200:
            raise AparatoNoDisponible(f"el JetKVM responde {estado} en /device")

        ws_url = self.url.replace("http", "ws", 1) + "/webrtc/signaling/client"
        self._ws = await self._http.ws_connect(ws_url, heartbeat=20)
        meta = json.loads((await asyncio.wait_for(self._ws.receive(), 10)).data)
        self.version = str((meta.get("data") or {}).get("deviceVersion", ""))

        # Sin servidores STUN: con los de por omisión aiortc se queda esperando en una red sin internet.
        pc = self._pc = RTCPeerConnection(RTCConfiguration(iceServers=[]))
        from aiortc import RTCRtpReceiver

        video = pc.addTransceiver("video", direction="recvonly")
        # Sólo H.264: es lo que manda el aparato, y así un JetKVM falso tampoco puede elegir otro.
        video.setCodecPreferences([c for c in RTCRtpReceiver.getCapabilities("video").codecs
                                   if c.mimeType in ("video/H264", "video/rtx")])
        # El sonido, para grabar una reunión (C-0461). Sólo G722: 16 kHz, lo que
        # pide la transcripción (su PCMU es de 8). Ofrecerlo no le cuesta nada al
        # aparato con su audio apagado, que es como viene: contesta con la línea
        # inactiva y no captura (`attachAudioTrack`, firmware 0.5.9-0.5.11).
        sonido = pc.addTransceiver("audio", direction="recvonly")
        sonido.setCodecPreferences([c for c in RTCRtpReceiver.getCapabilities("audio").codecs
                                    if c.mimeType == "audio/G722"])
        self._rpc = pc.createDataChannel("rpc")
        self._hid = pc.createDataChannel("hidrpc")
        self._hid_suelto = pc.createDataChannel("hidrpc-unreliable-ordered", ordered=True, maxRetransmits=0)
        pista: asyncio.Future = asyncio.get_running_loop().create_future()

        @pc.on("track")
        def _pista(t):
            if t.kind == "video" and not pista.done():
                pista.set_result(t)
            elif t.kind == "audio":  # sólo si el aparato la añadió: con su audio apagado no llega
                self._pista_audio = t
                self._tareas.append(asyncio.create_task(self._recibir_audio(t)))

        @pc.on("connectionstatechange")
        async def _estado():
            if pc.connectionState in ("failed", "closed"):
                self.conectado, self._sin_video = False, False
                self.motivo = f"conexión {pc.connectionState}"

        @self._rpc.on("message")
        def _rpc_mensaje(m):
            try:
                j = json.loads(m)
            except Exception:
                return
            if "id" in j and j["id"] in self._pendientes:
                self._pendientes.pop(j["id"]).set_result(j)
            elif j.get("method") == "otherSessionConnected":
                self.conectado, self._sin_video = False, False
                self.motivo = "otra sesión abrió el JetKVM (¿su web en un navegador?): el puente quedó fuera"
            elif j.get("method") == "videoInputState":
                self._leer_video(j.get("params") or {})

        saludo: asyncio.Future = asyncio.get_running_loop().create_future()

        @self._hid.on("message")
        def _hid_mensaje(m):
            if isinstance(m, bytes) and m[:1] == b"\x01" and not saludo.done():
                saludo.set_result(m[1:2])

        await pc.setLocalDescription(await pc.createOffer())
        ld = pc.localDescription
        sd = base64.b64encode(json.dumps({"type": ld.type, "sdp": ld.sdp}).encode()).decode()
        await self._ws.send_str(json.dumps({"type": "offer", "data": {"sd": sd}}))

        respondido = asyncio.Event()
        tempranos: list[dict] = []

        async def candidato(c: dict) -> None:
            from aiortc.sdp import candidate_from_sdp

            if not c or not c.get("candidate"):
                return
            cand = candidate_from_sdp(c["candidate"].split(":", 1)[1])
            cand.sdpMid, cand.sdpMLineIndex = c.get("sdpMid"), c.get("sdpMLineIndex")
            await pc.addIceCandidate(cand)

        async def bombear():
            async for m in self._ws:
                if m.type != aiohttp.WSMsgType.TEXT or m.data == "pong":
                    continue
                msg = json.loads(m.data)
                if msg.get("type") == "answer":
                    a = json.loads(base64.b64decode(msg["data"]))
                    await pc.setRemoteDescription(RTCSessionDescription(a["sdp"], a["type"]))
                    respondido.set()
                    for c in tempranos:
                        await candidato(c)
                elif msg.get("type") == "new-ice-candidate":
                    if respondido.is_set():
                        await candidato(msg["data"])
                    else:
                        tempranos.append(msg["data"])
                elif "error" in msg:
                    self.motivo = f"señalización: {msg['error']}"
            self.motivo = "la señalización se cerró"

        self._tareas.append(asyncio.create_task(bombear()))
        await asyncio.wait_for(respondido.wait(), 15)
        await self._esperar_abiertos(15)

        for _ in range(10):  # el aparato contesta al saludo cuando está listo; la web reintenta cada segundo
            self._hid.send(bytes([0x01, 0x01]))
            with contextlib.suppress(asyncio.TimeoutError):
                await asyncio.wait_for(asyncio.shield(saludo), 1.0)
                break
        if not saludo.done():
            raise AparatoNoDisponible("el JetKVM no contesta al saludo HID (¿firmware anterior a 0.4.7?)")

        with contextlib.suppress(Exception):
            self._leer_video((await self._llamar("getVideoState")).get("result") or {})
        # Antes del vídeo: con el Mac dormido no llega imagen y la conexión se da
        # por fallida, pero el jiggler y despertarlo sólo necesitan este canal.
        with contextlib.suppress(Exception):
            await self.leer_jiggler()

        track = await asyncio.wait_for(pista, 10)
        self._tareas.append(asyncio.create_task(self._recibir_video(track)))
        fin = time.monotonic() + 5
        while self._trama is None and time.monotonic() < fin:
            await asyncio.sleep(0.1)
        if self._trama is None:
            self._sin_video = True
            raise AparatoNoDisponible("conectado, pero no llega vídeo (¿el Mac está dormido, apagado o sin HDMI?)")
        self.conectado, self.motivo = True, ""

    async def _esperar_abiertos(self, tope: float) -> None:
        fin = time.monotonic() + tope
        while time.monotonic() < fin:
            if all(c.readyState == "open" for c in (self._rpc, self._hid, self._hid_suelto)):
                return
            await asyncio.sleep(0.05)
        raise AparatoNoDisponible("los canales de datos no se abren")

    def _leer_video(self, v: dict) -> None:
        if v.get("width") and v.get("height"):
            self.ancho, self.alto = int(v["width"]), int(v["height"])

    async def _recibir_video(self, track) -> None:
        while True:
            try:
                trama = await track.recv()
            except Exception as e:  # la pista terminó: se dice en el estado
                self.conectado, self.motivo = False, f"el vídeo se cortó ({type(e).__name__})"
                return
            self._trama, self._trama_t = trama, time.time()
            self.ancho, self.alto = trama.width, trama.height
            if self._sin_video:  # estaba dormido al conectar y ya despertó: lo demás estaba listo
                self._sin_video = False
                self.conectado, self.motivo = True, ""

    async def _recibir_audio(self, track) -> None:
        # Se lee siempre, grabe alguien o no: lo que no se lee se acumula en la
        # cola de aiortc. En silencio el aparato no manda nada y esto espera.
        while True:
            try:
                trama = await track.recv()
            except Exception:
                if self._pista_audio is track:
                    self._pista_audio = None
                return
            oido = self.oido
            if oido is not None:
                oido(bytes(trama.planes[0])[: trama.samples * 2], time.time())

    async def _llamar(self, metodo: str, **params) -> dict:
        self._n += 1
        f = asyncio.get_running_loop().create_future()
        self._pendientes[self._n] = f
        self._rpc.send(json.dumps({"jsonrpc": "2.0", "method": metodo, "params": params, "id": self._n}))
        # Las llamadas JSON-RPC se atienden en paralelo en el aparato: se espera cada una.
        return await asyncio.wait_for(f, 5)

    async def cerrar(self) -> None:
        for t in self._tareas:
            t.cancel()
        self._tareas = []
        for cerrar in (lambda: self._pc and self._pc.close(), lambda: self._ws and self._ws.close(),
                       lambda: self._http and self._http.close()):
            with contextlib.suppress(Exception):
                r = cerrar()
                if asyncio.iscoroutine(r):
                    await r
        self._pc = self._ws = self._http = None
        self._trama = None
        self._pista_audio = None
        self.jiggler = None  # se vuelve a leer al conectar: lo de antes puede no ser de este aparato
        self._sin_video = False
        self.conectado = False

    # ── Dispositivo ─────────────────────────────────────────────────────────
    def _listo(self) -> None:
        if not self.conectado or self._hid is None or self._hid.readyState != "open":
            raise AparatoNoDisponible(f"sin conexión con el JetKVM: {self.motivo}")

    async def captura(self) -> Image.Image:
        if self._trama is None:
            raise AparatoNoDisponible(f"sin vídeo del JetKVM: {self.motivo}")
        return self._trama.to_image().convert("RGB")

    async def miniatura(self, ancho: int) -> Image.Image:
        # Reducida desde el vídeo, en otro hilo: 2 ms frente a ~37 de convertir
        # la imagen entera y reducirla después (medido a 1920×1080 → 1280). Con
        # el trabajo en el bucle, el directo dejaba sin atender el ratón y el
        # teclado de la persona («va muy lento», primera prueba con el aparato).
        trama = self._trama
        if trama is None:
            raise AparatoNoDisponible(f"sin vídeo del JetKVM: {self.motivo}")
        if trama.width <= ancho:
            return await asyncio.to_thread(lambda: trama.to_image().convert("RGB"))
        alto = max(2, round(trama.height * ancho / trama.width) // 2 * 2)
        return await asyncio.to_thread(lambda: trama.reformat(width=ancho, height=alto, format="rgb24").to_image())

    async def informe_teclado(self, modificadores: int, teclas: list[int]) -> None:
        self._listo()
        k = (list(teclas) + [0] * 6)[:6]
        # Informe completo (0x02): no se suelta solo, a diferencia de 0x05, que el
        # aparato suelta a los 100 ms; aquí cada pulsación ya manda su informe vacío.
        self._hid.send(bytes([0x02, modificadores & 0xFF, *k]))

    async def raton(self, x: int, y: int, botones: int = 0) -> None:
        self._listo()
        # La misma cuenta que la web del aparato (useMouse.ts): píxel / ancho * 32767.
        hx = max(0, min(32767, round(x * 32767 / max(1, self.ancho))))
        hy = max(0, min(32767, round(y * 32767 / max(1, self.alto))))
        datos = struct.pack(">BiiB", 0x03, hx, hy, botones & 0x1F)
        # Como la web: los cambios de botón por el canal fiable; el movimiento puede perderse.
        canal = self._hid if botones != self._botones else self._hid_suelto
        canal.send(datos)
        self._botones = botones

    async def rueda(self, pasos: int) -> None:
        self._listo()
        paso = -1 if pasos > 0 else 1  # en el aparato, positivo sube
        for _ in range(abs(pasos)):
            await self._llamar("wheelReport", wheelY=paso, wheelX=0)

    async def girar(self, pasos: int) -> None:
        self._listo()
        # Un informe de hasta ±127 y sin esperar respuesta, como su web: esperar
        # cada paso (lo que hace `rueda`, que Claude necesita medido) dejaba la
        # rueda de la persona lentísima (20-nov). La respuesta se ignora.
        self._n += 1
        self._rpc.send(json.dumps({"jsonrpc": "2.0", "method": "wheelReport", "id": self._n,
                                   "params": {"wheelY": -max(-127, min(pasos, 127)), "wheelX": 0}}))

    # ── sonido ──────────────────────────────────────────────────────────────
    @property
    def da_sonido(self) -> bool:
        return self._pista_audio is not None

    async def encender_sonido(self) -> bool:
        self._listo()
        r = await self._llamar("getAudioConfig")
        if "error" in r:  # método desconocido: el audio llegó en 0.5.9
            raise AparatoNoDisponible("este JetKVM no da sonido: su firmware tiene que ser 0.5.9 o posterior "
                                      "(se actualiza desde su web, en Ajustes)")
        if not (r.get("result") or {}).get("enabled"):
            # Con el «params» anidado, como su web. Queda guardado en el aparato.
            await self._llamar("setAudioConfig", params={"enabled": True})
            r = await self._llamar("getAudioConfig")
            if not (r.get("result") or {}).get("enabled"):
                # Sin el dispositivo de audio USB, el aparato lo deja apagado sin dar error.
                raise AparatoNoDisponible("el JetKVM no enciende el sonido: en su web, Ajustes → Hardware, "
                                          "«Activar audio USB» (el Mac verá ese dispositivo nuevo)")
        # Encenderlo no lo añade a esta conexión: lo añade el aparato al empezar una.
        return self._pista_audio is None

    async def apagar_sonido(self) -> None:
        if self._rpc is None or self._rpc.readyState != "open":
            return
        await self._llamar("setAudioConfig", params={"enabled": False})
        # Apagado, deja de capturar para esta conexión y no vuelve sin reconectar.
        self._pista_audio = None

    # ── el jiggler y despertar el Mac (C-0463): sólo el canal rpc ───────────
    def _rpc_listo(self) -> None:
        if self._rpc is None or self._rpc.readyState != "open":
            raise AparatoNoDisponible(f"sin conexión con el JetKVM: {self.motivo or 'no conectado'}")

    async def _resultado(self, metodo: str, **params):
        r = await self._llamar(metodo, **params)
        if "error" in r:
            e = r["error"]
            raise AparatoNoDisponible(f"el JetKVM no hizo «{metodo}»: "
                                      + str((e.get("data") or e.get("message")) if isinstance(e, dict) else e))
        return r.get("result")

    async def leer_jiggler(self) -> dict:
        self._rpc_listo()
        self.jiggler = {"encendido": bool(await self._resultado("getJigglerState")),
                        "config": await self._resultado("getJigglerConfig") or {}}
        return self.jiggler

    async def poner_jiggler(self, encendido: bool, config: dict | None = None) -> dict:
        self._rpc_listo()
        try:
            if config is not None:
                antes = await self._resultado("getJigglerConfig")
                r = await self._llamar("setJigglerConfig", jigglerConfig=config)
                if "error" in r:
                    # El aparato ya lo tomó en memoria y paró el jiggler: se repone el de antes.
                    e = r["error"]
                    motivo = "el JetKVM no aceptó el horario: " + str(
                        (e.get("data") or e.get("message")) if isinstance(e, dict) else e)
                    repuesto = await self._llamar("setJigglerConfig", jigglerConfig=antes)
                    if "error" in repuesto:
                        motivo += "; y no pude reponer el de antes: se queda sin jiggler hasta reiniciarlo"
                    raise ValueError(motivo)
            await self._resultado("setJigglerState", enabled=bool(encendido))
        finally:
            # Lo que enseña la pantalla, lo que tenga de verdad, también si algo falló.
            with contextlib.suppress(Exception):
                await self.leer_jiggler()
        return self.jiggler

    async def zonas(self) -> list[str]:
        self._rpc_listo()
        return list(await self._resultado("getTimezones") or [])

    async def despertar(self, tope: float = 8.0) -> dict:
        self._rpc_listo()
        antes = await self._usb()
        # Sin el USB conectado, `wakeHost` contesta bien sin hacer nada (su usb.go,
        # `IsUSBStateAttached`: ni «not attached» ni «unknown»).
        if antes in ("not attached", "unknown", ""):
            raise AparatoNoDisponible("el JetKVM no está conectado al Mac por USB: no le llega la señal de despertar")
        t0 = time.time()
        # Despierto y con imagen: mandar la señal no cambiaría nada, y decir
        # «despertó» sería mentir.
        if antes != "suspended" and self._trama_t > t0 - 2:
            return {"antes": antes, "despues": antes, "imagen": True, "ya_despierto": True}
        await self._resultado("wakeHost")
        despues, fin = antes, time.monotonic() + tope
        while time.monotonic() < fin:
            await asyncio.sleep(0.5)
            despues = await self._usb()
            if self._trama_t > t0 + 0.2 and despues != "suspended":
                return {"antes": antes, "despues": despues, "imagen": True}
        return {"antes": antes, "despues": despues, "imagen": self._trama_t > t0 + 0.2}

    async def _usb(self) -> str | None:
        """El estado del USB del aparato hacia el Mac: «suspended» mientras duerme."""
        r = await self._llamar("getUSBState")
        return r.get("result") if "error" not in r else None

    def estado(self) -> dict:
        edad = time.time() - self._trama_t if self._trama_t else None
        e = {"tipo": self.tipo, "conectado": self.conectado, "motivo": self.motivo,
             "resolucion": f"{self.ancho}×{self.alto}" if self._trama is not None else None,
             "ancho": self.ancho, "alto": self.alto,
             "firmware": self.version, "url": self.url,
             "firmware_contrastado": self.version in FIRMWARE_CONTRASTADO,
             "ultimo_fotograma_s": round(edad, 1) if edad is not None else None,
             "sonido": self.da_sonido, "jiggler": self.jiggler}
        if self.version or self.conectado:
            aviso = aviso_firmware(self.version)
            if aviso:
                e["aviso"] = aviso
        return e
