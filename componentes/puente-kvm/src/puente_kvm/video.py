"""El vídeo del aparato tal como llega, en H.264 sin decodificar, para el navegador (C-0469).

La web del JetKVM pinta su vídeo directo, a 30 o más fotogramas por segundo;
el directo de imágenes JPEG del puente (`/api/pantalla.mjpg`) llega a unos 11
usándolo, porque cada una se reduce y se recomprime aquí. Esto deja pasar las
tramas H.264 que manda el aparato, sin tocarlas, a quien las pinte con
WebCodecs (`/ws/pantalla`). Y sin quitárselas al decodificador del puente: las
capturas de Claude, las comprobaciones, las reuniones y despertar el Mac siguen
con los fotogramas decodificados de siempre.

Por qué así y no de otra forma (decisión 449 del hub):

- **No una segunda conexión WebRTC con el navegador**: aioice reúne candidatos
  en todas las interfaces (la red local, Tailscale) sin forma de filtrarlos, y
  en WSL2 con NAT el reenvío de localhost sólo pasa TCP.
- **No `MediaRelay`**: reenvía fotogramas ya decodificados, y habría que volver
  a comprimirlos aquí.
- **No el navegador directo al JetKVM**: admite una sola sesión y echaría al
  puente.

Lo que cuesta: aiortc no da las tramas antes de decodificarlas, así que se
envuelve el `put` de la cola privada de su receptor (`enganchar`). Por eso
aiortc va fijada (`pyproject.toml`), una prueba falla si esa cola desaparece,
y con otra versión el directo vuelve a las imágenes y lo dice.
"""

from __future__ import annotations

import asyncio
import queue
from collections.abc import Callable
from dataclasses import dataclass

# La versión de aiortc cuya cola privada se leyó (`rtcrtpreceiver.py`, 1.16.0).
AIORTC_FIJADA = "1.16."
# Cuántas tramas espera cada suscriptor como mucho: a 30 por segundo, medio
# segundo. Más atrás que eso, lo que se pintara ya sería viejo: se descarta
# lo que tiene y espera a la siguiente clave (el aparato manda una cada ~0,5 s).
TOPE = 15

SPS, PPS, IDR = 7, 8, 5
INICIO = b"\x00\x00\x00\x01"


def unidades(datos: bytes) -> list[bytes]:
    """Las unidades NAL de una trama Annex B, sin sus códigos de inicio."""
    trozos, i = [], datos.find(b"\x00\x00\x01")
    while i != -1:
        j = datos.find(b"\x00\x00\x01", i + 3)
        fin = len(datos) if j == -1 else (j - 1 if datos[j - 1] == 0 else j)
        if fin > i + 3:
            trozos.append(datos[i + 3:fin])
        i = j
    return trozos


def codec_de_sps(sps: bytes) -> str:
    """El códec para WebCodecs, «avc1.PPCCLL»: perfil, restricciones y nivel del SPS."""
    return f"avc1.{sps[1]:02x}{sps[2]:02x}{sps[3]:02x}"


@dataclass(frozen=True)
class Trama:
    datos: bytes   # Annex B, como llegó (la primera de cada suscriptor, con SPS y PPS delante)
    marca: int     # reloj de 90 kHz del RTP, desde el principio de la conexión
    clave: bool    # un IDR: desde aquí se puede decodificar sin lo de antes
    sps: bytes     # el SPS en curso: si cambia, el navegador reconfigura su decodificador

    @property
    def codec(self) -> str:
        return codec_de_sps(self.sps)


class Suscripcion:
    """Lo que recibe quien pinta el vídeo: tramas en orden, empezando por una clave.

    Nunca hace esperar al que las reparte: si quien las pinta no da abasto y se
    llena su cola, se tira lo que tenía y espera a la siguiente clave. Una
    trama suelta perdida dejaría la imagen rota hasta entonces, igual."""

    def __init__(self, derivacion: Derivacion, tope: int = TOPE):
        self._derivacion = derivacion
        self._cola: asyncio.Queue[Trama | None] = asyncio.Queue(tope)
        self.esperando_clave = True
        self.descartes = 0
        self.motivo = ""

    def _dar(self, trama: Trama, parametros: bytes) -> None:
        """`parametros`: el SPS y el PPS guardados, si esta clave no los trae."""
        if self.esperando_clave and not trama.clave:
            return
        if self._cola.full():
            self._vaciar()
            self.descartes += 1
            self.esperando_clave = True
            if not trama.clave:
                return
        if self.esperando_clave and parametros:  # que se pueda decodificar desde aquí sin lo de antes
            trama = Trama(parametros + trama.datos, trama.marca, True, trama.sps)
        self._cola.put_nowait(trama)
        self.esperando_clave = False

    def _vaciar(self) -> None:
        while not self._cola.empty():
            self._cola.get_nowait()

    def _terminar(self, motivo: str) -> None:
        self.motivo = motivo
        self._vaciar()
        self._cola.put_nowait(None)

    async def siguiente(self) -> Trama | None:
        """La siguiente trama; None si el vídeo directo se acabó (`motivo` dice por qué)."""
        return await self._cola.get()

    def cerrar(self) -> None:
        self._derivacion.quitar(self)


class Derivacion:
    """Reparte las tramas codificadas entre quienes las pintan.

    Recuerda el último SPS y PPS: el aparato los manda con cada clave, pero si
    algún día sólo los mandara al empezar, quien llega tarde no podría
    decodificar nada (decisión 449)."""

    def __init__(self) -> None:
        self._suscripciones: set[Suscripcion] = set()
        self._sps = self._pps = b""
        self.apagada = ""  # por qué no hay vídeo directo; vacío si lo hay

    @property
    def parametros(self) -> bytes:
        return INICIO + self._sps + INICIO + self._pps if self._sps and self._pps else b""

    def alimentar(self, datos: bytes, marca: int) -> None:
        """Una trama recién llegada del aparato. 🔴 Corre dentro de aiortc, antes de
        decodificarla: no puede lanzar ni esperar (lo envuelve `enganchar`)."""
        tipos = set()
        for nal in unidades(datos):
            tipo = nal[0] & 0x1F
            tipos.add(tipo)
            if tipo == SPS and len(nal) >= 4:
                self._sps = nal
            elif tipo == PPS:
                self._pps = nal
        if not self._sps or not self._suscripciones:
            return
        clave = IDR in tipos
        trama = Trama(datos, marca, clave, self._sps)
        parametros = self.parametros if clave and not {SPS, PPS} <= tipos else b""
        for s in list(self._suscripciones):
            s._dar(trama, parametros)

    def nueva_conexion(self) -> None:
        """El aparato volvió a conectar: lo de la conexión de antes ya no sirve para
        decodificar lo nuevo. Quien mira espera a la primera clave de ésta."""
        self._sps = self._pps = b""
        for s in self._suscripciones:
            s._vaciar()
            s.esperando_clave = True

    def suscribir(self, tope: int = TOPE) -> Suscripcion | None:
        if self.apagada:
            return None
        s = Suscripcion(self, tope)
        self._suscripciones.add(s)
        return s

    def quitar(self, s: Suscripcion) -> None:
        self._suscripciones.discard(s)

    def apagar(self, motivo: str) -> None:
        self.apagada = motivo
        for s in list(self._suscripciones):
            s._terminar(motivo)
        self._suscripciones.clear()


def enganchar(receptor, alimentar: Callable[[bytes, int], None], fallo: Callable[[str], None]) -> bool:
    """Deriva las tramas H.264 del receptor de vídeo de aiortc antes de su decodificador.

    Se envuelve el `put` de su cola, no se sustituye la cola: el hilo
    decodificador ya tiene la referencia a ésa. 🔴 Lo envuelto nunca bloquea ni
    lanza, y siempre llama al `put` de aiortc: si derivar falla, se apaga, lo
    dice `fallo` y el decodificador sigue como si nada. False si no se pudo
    enganchar (otra versión de aiortc): entonces el directo va por imágenes."""
    import aiortc

    if not aiortc.__version__.startswith(AIORTC_FIJADA):
        fallo(f"aiortc {aiortc.__version__} no es la fijada ({AIORTC_FIJADA}x): el directo va por imágenes")
        return False
    cola = getattr(receptor, "_RTCRtpReceiver__decoder_queue", None)
    if not isinstance(cola, queue.Queue):
        fallo("aiortc ya no tiene la cola de su decodificador donde se leyó: el directo va por imágenes")
        return False
    original = cola.put
    vivo = [True]

    def put(item, *args, **kwargs):
        if vivo[0] and item is not None:
            try:
                codec, trama = item
                if codec.mimeType.lower() == "video/h264":
                    alimentar(bytes(trama.data), int(trama.timestamp))
            except Exception as e:
                vivo[0] = False
                try:
                    fallo(f"el vídeo directo falló ({type(e).__name__}: {e}): el directo va por imágenes")
                except Exception:
                    pass
        return original(item, *args, **kwargs)

    cola.put = put
    return True
