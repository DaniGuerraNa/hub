"""Un JetKVM falso que habla el protocolo del firmware 0.5.11, con el Mac simulado detrás.

Sirve para probar `jetkvm.JetKVM` de punta a punta —login, señalización por
WebSocket, ICE por goteo (con candidatos ANTES de la respuesta, como el
aparato), canales de datos, saludo HID binario, vídeo H.264 de verdad— sin
el aparato. No prueba el aparato: prueba que el cliente hace lo que dice el
código del firmware. Lo que el firmware haga distinto de lo leído sólo se
verá con el aparato delante.
"""

from __future__ import annotations

import asyncio
import base64
import fractions
import json
import math
import struct
import time
import uuid

import av
from aiohttp import web
from aiortc import MediaStreamTrack, RTCPeerConnection, RTCRtpSender, RTCSessionDescription, VideoStreamTrack

from puente_kvm.simulador import Simulador


class PantallaFalsa(VideoStreamTrack):
    def __init__(self, sim: Simulador, falso: "JetKVMFalso | None" = None):
        super().__init__()
        self.sim = sim
        self.falso = falso

    async def recv(self):
        # Con el Mac en reposo (o la pantalla apagada) no hay HDMI y no sale vídeo.
        while self.falso is not None and (self.falso.usb == "suspended" or not self.falso.video):
            await asyncio.sleep(0.05)
        pts, base = await self.next_timestamp()
        trama = av.VideoFrame.from_image(await self.sim.captura())
        trama.pts, trama.time_base = pts, base
        return trama


class SonidoFalso(MediaStreamTrack):
    """Un tono, como manda el aparato lo que suena en el Mac: 20 ms por paquete. En
    una pausa no manda nada y su reloj no avanza (así hasta 0.5.11)."""

    kind = "audio"

    def __init__(self, pausas: dict[int, float]):
        super().__init__()
        self.pausas = dict(pausas)  # paquete → segundos callado antes de mandarlo
        self.n = 0
        self.base: float | None = None

    async def recv(self):
        if self.base is None:
            self.base = time.monotonic()
        if self.n in self.pausas:
            pausa = self.pausas.pop(self.n)
            await asyncio.sleep(pausa)
            self.base += pausa
        await asyncio.sleep(max(0.0, self.base + self.n * 0.02 - time.monotonic()))
        datos = struct.pack("<320h", *(round(8000 * math.sin(2 * math.pi * 440 * (self.n * 320 + i) / 16000))
                                       for i in range(320)))
        trama = av.AudioFrame(format="s16", layout="mono", samples=320)
        trama.planes[0].update(datos)
        trama.sample_rate = 16000
        trama.pts, trama.time_base = self.n * 320, fractions.Fraction(1, 16000)
        self.n += 1
        return trama


class JetKVMFalso:
    def __init__(self, sim: Simulador, clave: str = "secreta", version: str = "0.5.11-falso"):
        self.sim = sim
        self.clave = clave
        self.version = version
        self.token = ""
        self.pcs: list[RTCPeerConnection] = []
        self.mensajes_hid: list[bytes] = []
        self.rpc: list[dict] = []
        self.runner: web.AppRunner | None = None
        self.puerto = 0
        # El audio, como el firmware 0.5.9-0.5.11: apagado de fábrica, sólo con el
        # dispositivo de audio USB, y sólo en las conexiones que empiezan encendido.
        self.audio = False
        self.audio_usb = True
        self.sabe_audio = True  # False: un firmware anterior a 0.5.9
        self.pausas: dict[int, float] = {}
        # El jiggler como viene (apagado, «Estándar») y el USB hacia el Mac (su usb.go).
        self.jiggler = False
        self.jiggler_config = {"inactivity_limit_seconds": 60, "jitter_percentage": 25, "schedule_cron_tab": "0 * * * * *"}
        self.rechazar_horario = False  # como un cron que su gocron no entiende
        self.usb = "configured"  # «suspended» con el Mac dormido, «not attached» sin el cable
        self.video = True  # False: el Mac despierto pero sin imagen (la pantalla aún apagada)
        self.despertares = 0

    def _dentro(self, req: web.Request) -> bool:
        return bool(self.token) and req.cookies.get("authToken") == self.token

    async def status(self, req):
        return web.json_response({"isSetup": True, "sku": "falso"})

    async def device(self, req):
        if not self._dentro(req):
            return web.json_response({"error": "Unauthorized"}, status=401)
        return web.json_response({"authMode": "password", "deviceId": "falso", "loopbackOnly": False})

    async def login(self, req):
        datos = await req.json()
        if datos.get("password") != self.clave:
            return web.json_response({"error": "Invalid password"}, status=401)
        self.token = str(uuid.uuid4())  # uno solo: echa al anterior, como el aparato
        r = web.json_response({"message": "Login successful"})
        r.set_cookie("authToken", self.token, httponly=True, path="/")
        return r

    async def senalizacion(self, req):
        if not self._dentro(req):
            return web.json_response({"error": "Unauthorized"}, status=401)
        ws = web.WebSocketResponse()
        await ws.prepare(req)
        await ws.send_str(json.dumps({"type": "device-metadata", "data": {"deviceVersion": self.version}}))
        async for m in ws:
            if m.data == "ping":
                await ws.send_str("pong")
                continue
            msg = json.loads(m.data)
            if msg.get("type") == "offer":
                await self._contestar(ws, json.loads(base64.b64decode(msg["data"]["sd"])))
        return ws

    async def _contestar(self, ws, oferta: dict):
        pc = RTCPeerConnection()
        self.pcs.append(pc)

        @pc.on("datachannel")
        def canal(c):
            @c.on("message")
            def mensaje(m):
                if c.label.startswith("hidrpc"):
                    asyncio.ensure_future(self._hid(c, m))
                elif c.label == "rpc":
                    asyncio.ensure_future(self._rpc(c, m))

        await pc.setRemoteDescription(RTCSessionDescription(oferta["sdp"], oferta["type"]))
        pc.addTrack(PantallaFalsa(self.sim, self))
        if self.audio and "G722/8000" in oferta["sdp"].upper():
            pc.addTrack(SonidoFalso(self.pausas))
        for t in pc.getTransceivers():
            if t.kind == "video":
                t.setCodecPreferences([c for c in RTCRtpSender.getCapabilities("video").codecs
                                       if c.mimeType == "video/H264"])
            elif t.kind == "audio":
                t.setCodecPreferences([c for c in RTCRtpSender.getCapabilities("audio").codecs
                                       if c.mimeType == "audio/G722"])
        await pc.setLocalDescription(await pc.createAnswer())
        sdp = pc.localDescription.sdp
        candidatos = [l[2:] for l in sdp.splitlines() if l.startswith("a=candidate:")]
        sin = "\r\n".join(l for l in sdp.splitlines() if not l.startswith("a=candidate:")) + "\r\n"
        mid = next((l.split(":", 1)[1] for l in sdp.splitlines() if l.startswith("a=mid:")), "0")

        def ice(c):
            return json.dumps({"type": "new-ice-candidate",
                               "data": {"candidate": c, "sdpMid": mid, "sdpMLineIndex": 0}})

        # Como el aparato: algún candidato llega ANTES que la respuesta, el resto después.
        if candidatos:
            await ws.send_str(ice(candidatos[0]))
        await ws.send_str(json.dumps({"type": "answer", "data": base64.b64encode(
            json.dumps({"type": "answer", "sdp": sin}).encode()).decode()}))
        for c in candidatos[1:]:
            await ws.send_str(ice(c))

    async def _hid(self, canal, m):
        if not isinstance(m, bytes):
            return  # el aparato rechaza texto en los canales HID
        self.mensajes_hid.append(m)
        if m[0] == 0x01:
            canal.send(bytes([0x01, 0x01]))
        elif m[0] == 0x02:
            await self.sim.informe_teclado(m[1], [k for k in m[2:8] if k])
        elif m[0] == 0x03:
            x, y, b = struct.unpack(">iiB", m[1:10])
            await self.sim.raton(round(x * 1920 / 32767), round(y * 1080 / 32767), b)

    async def _rpc(self, canal, m):
        j = json.loads(m)
        self.rpc.append(j)
        resultado = None
        if j["method"] == "getVideoState":
            resultado = {"ready": True, "streaming": 1, "width": 1920, "height": 1080, "fps": 30}
        elif j["method"] == "wheelReport":
            await self.sim.rueda(-int(j["params"]["wheelY"]))  # en el aparato, positivo sube
        elif j["method"] in ("getAudioConfig", "setAudioConfig") and not self.sabe_audio:
            canal.send(json.dumps({"jsonrpc": "2.0", "id": j["id"],
                                   "error": {"code": -32601, "message": "Method not found"}}))
            return
        elif j["method"] == "getAudioConfig":
            resultado = {"enabled": self.audio}
        elif j["method"] == "getJigglerState":
            resultado = self.jiggler
        elif j["method"] == "setJigglerState":
            self.jiggler = bool(j["params"]["enabled"])
        elif j["method"] == "getJigglerConfig":
            resultado = self.jiggler_config
        elif j["method"] == "setJigglerConfig":
            # Como `rpcSetJigglerConfig`: lo toma en memoria antes de programarlo, y si
            # falla se queda con el malo y sin jiggler hasta reiniciar.
            self.jiggler_config = j["params"]["jigglerConfig"]
            if self.rechazar_horario:
                canal.send(json.dumps({"jsonrpc": "2.0", "id": j["id"],
                                       "error": {"code": -32603, "message": "error scheduling jiggler crontab"}}))
                return
        elif j["method"] == "getTimezones":
            resultado = ["UTC", "America/Mexico_City", "Europe/Madrid"]
        elif j["method"] == "getUSBState":
            resultado = self.usb
        elif j["method"] == "wakeHost":
            # Sin el USB conectado contesta bien sin hacer nada (`rpcWakeHost`).
            if self.usb not in ("not attached", "unknown", ""):
                self.despertares += 1
                self.usb = "configured"
        elif j["method"] == "setAudioConfig":
            # Sin el audio USB lo deja apagado, sin error (`rpcSetAudioConfig`).
            self.audio = bool(j["params"]["params"]["enabled"]) and self.audio_usb
        canal.send(json.dumps({"jsonrpc": "2.0", "id": j["id"],
                               **({"result": resultado} if resultado is not None else {})}))

    async def arrancar(self) -> str:
        app = web.Application()
        app.router.add_get("/device/status", self.status)
        app.router.add_get("/device", self.device)
        app.router.add_post("/auth/login-local", self.login)
        app.router.add_get("/webrtc/signaling/client", self.senalizacion)
        self.runner = web.AppRunner(app)
        await self.runner.setup()
        sitio = web.TCPSite(self.runner, "127.0.0.1", 0)
        await sitio.start()
        self.puerto = sitio._server.sockets[0].getsockname()[1]
        return f"http://127.0.0.1:{self.puerto}"

    async def parar(self):
        for pc in self.pcs:
            await pc.close()
        if self.runner:
            await self.runner.cleanup()
