"""Grabar una reunión del Mac: lo que suena en él y su pantalla cuando cambia (C-0461).

La persona pulsa «Estoy en reunión» y «Salí de la reunión» en la pantalla del
puente, y nada más la empieza ni la para: ni Claude (no está en el MCP) ni el
hub (no hace POST al puente, decisión 438). Grabar a otras personas lo decide
ella. Lo grabado lo transcribe y lo resume Reuniones del hub, que lo encuentra
en su sitio sin que el puente le avise (decisión 443 del hub).

La carpeta sigue el contrato de Reuniones (`reuniones/carpeta.py`), con el
puente como segundo escritor:

    <PUENTE_HOME>/reuniones/<AAAAMMDD-HHMMSS>-kvm/
      meta.json        inicio, fin, origen, proceso.nombre, titulo; `fin` va lo
                       último y es la señal de que lo demás está cerrado
      reunion.wav      lo que sonó en el Mac, 16 kHz mono de 16 bits
      fotos/%06d.jpg   la pantalla cuando cambió; el número, segundos desde el inicio

No hay `micro.wav`: la voz de la persona entra al Mac por su micrófono y no
pasa por el JetKVM, que sólo recibe lo que el Mac reproduce.

🔴 Es contenido de otras personas: no sale de la máquina, el MCP no lo lee y la
sesión de Claude del puente tiene negada esta carpeta (`.claude/settings.json`).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import struct
import threading
import time
from pathlib import Path

from PIL import Image, ImageChops, ImageStat

from . import config
from .dispositivo import AparatoNoDisponible, Dispositivo

TASA = 16000  # la del G722 que manda el JetKVM
CABECERA = 44
# Un hueco más largo que esto es silencio en el Mac: el JetKVM no manda nada
# mientras no suena y su reloj no avanza, así que el silencio se pone por la
# hora de llegada. Por debajo es el vaivén de la red, y rellenarlo metería cortes.
HUECO_S = 0.25
# Los del agente de Windows de Reuniones: misma huella, mismo umbral, misma foto.
UMBRAL_CAMBIO = 4.0  # media de |diferencia| en 0-255, a 96×54 en grises
ANCHO_FOTO, CALIDAD_FOTO = 1600, 72
FOTO_CADA_S = 1.0
ORIGEN, APP = "jetkvm", "Mac (JetKVM)"


def raiz() -> Path:
    return config.hogar() / "reuniones"


def _cabecera(muestras: int) -> bytes:
    datos = muestras * 2
    return (b"RIFF" + struct.pack("<I", 36 + datos) + b"WAVE"
            + b"fmt " + struct.pack("<IHHIIHH", 16, 1, 1, TASA, TASA * 2, 2, 16)
            + b"data" + struct.pack("<I", datos))


def arreglar_cabecera(wav: Path) -> int:
    """La cabecera de un WAV que no se cerró (dice 0 muestras), con lo que hay
    de verdad detrás. Devuelve las muestras."""
    muestras = max(0, wav.stat().st_size - CABECERA) // 2
    with open(wav, "r+b") as f:
        f.write(_cabecera(muestras))
    return muestras


def _leer(ruta: Path) -> dict | None:
    try:
        return json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _escribir(ruta: Path, datos: dict) -> None:
    tmp = ruta.with_suffix(".tmp")
    tmp.write_text(json.dumps(datos, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(ruta)


class Grabacion:
    """Una reunión mientras se graba: su carpeta, su WAV abierto y su última foto."""

    def __init__(self, titulo: str = "", ahora: float | None = None):
        t = int(ahora if ahora is not None else time.time())
        raiz().mkdir(parents=True, exist_ok=True)
        while True:  # dos en el mismo segundo (parar y volver a empezar): la segunda, al siguiente
            self.id = time.strftime("%Y%m%d-%H%M%S", time.localtime(t)) + "-kvm"
            self.dir = raiz() / self.id
            try:
                self.dir.mkdir()
                break
            except FileExistsError:
                t += 1
        (self.dir / "fotos").mkdir()
        self.inicio = float(t)
        self.titulo = titulo.strip()[:120]
        self.muestras = 0
        self.fotos = 0
        self.ultimo_sonido: float | None = None
        self.error = ""
        self._huella: Image.Image | None = None
        # Las fotos se guardan en otro hilo: cancelar su tarea no para el hilo, y
        # una foto escrita tras `fin` o contada de menos rompería el contrato.
        self._cerrojo = threading.Lock()
        self._cerrada = False
        self._escribir_meta()
        self._wav = open(self.dir / "reunion.wav", "wb")
        self._wav.write(_cabecera(0))

    def _escribir_meta(self, **mas) -> None:
        _escribir(self.dir / "meta.json", {"id": self.id, "inicio": self.inicio, "origen": ORIGEN,
                                           "proceso": {"nombre": APP}, "titulo": self.titulo, **mas})

    def _silencio(self, muestras: int) -> None:
        if muestras <= 0:
            return
        # Alargar el archivo deja ceros sin escribirlos: media hora callada son
        # 57 MB, y escribirlos de golpe en el bucle pararía el vídeo y el ratón.
        self._wav.flush()
        fin = self._wav.tell() + muestras * 2
        self._wav.truncate(fin)
        self._wav.seek(fin, os.SEEK_SET)
        self.muestras += muestras

    def oir(self, pcm: bytes, t: float) -> None:
        """Un trozo de lo que suena (PCM de 16 bits a 16 kHz) y cuándo llegó."""
        if self._wav is None:
            return
        n = len(pcm) // 2
        try:
            hueco = round((t - self.inicio) * TASA) - n - self.muestras
            if hueco > HUECO_S * TASA:
                self._silencio(hueco)
            self._wav.write(pcm[: n * 2])
        except OSError as e:  # el disco lleno no puede pasar callado: lo dice la pantalla
            self.error = f"no se pudo guardar el sonido: {e}"
            return
        self.muestras += n
        self.ultimo_sonido = t

    def mirar(self, img: Image.Image, t: float) -> bool:
        """La pantalla en `t`: se guarda si cambió respecto de la última guardada."""
        huella = img.convert("L").resize((96, 54))
        if (self._huella is not None
                and ImageStat.Stat(ImageChops.difference(huella, self._huella)).mean[0] <= UMBRAL_CAMBIO):
            return False
        if img.width > ANCHO_FOTO:
            img = img.resize((ANCHO_FOTO, round(img.height * ANCHO_FOTO / img.width)))
        with self._cerrojo:
            if self._cerrada:
                return False
            self._huella = huella
            img.convert("RGB").save(self.dir / "fotos" / f"{max(0, int(t - self.inicio)):06d}.jpg",
                                    "JPEG", quality=CALIDAD_FOTO)
            self.fotos += 1
        return True

    def terminar(self, fin: float | None = None, cortada: str = "") -> dict:
        """Cierra el WAV y escribe `fin`, lo último. Devuelve el resumen."""
        fin = fin if fin is not None else time.time()
        with self._cerrojo:  # la foto que se esté guardando acaba antes; después, ninguna
            self._cerrada = True
        # Hasta el final con silencio: las fotos y lo dicho se alinean por segundos.
        self._silencio(round((fin - self.inicio) * TASA) - self.muestras)
        self._wav.seek(0)
        self._wav.write(_cabecera(self.muestras))
        self._wav.close()
        self._wav = None
        mas = {"fin": fin, "fotos": self.fotos,
               "con_sonido": self.ultimo_sonido is not None}
        if cortada:
            mas["cortada"] = cortada
        self._escribir_meta(**mas)
        return {"id": self.id, "segundos": int(fin - self.inicio), "fotos": self.fotos,
                "con_sonido": self.ultimo_sonido is not None, "cortada": cortada}


def cerrar_cortadas() -> list[str]:
    """Las que quedaron sin `fin` porque el puente se paró a medias: se cierran
    como están. Sin esto, Reuniones no las procesaría nunca."""
    cerradas = []
    if not raiz().is_dir():
        return cerradas
    for d in sorted(raiz().glob("*-kvm")):
        meta = _leer(d / "meta.json") or {}
        if not d.is_dir() or meta.get("fin"):
            continue
        try:
            inicio = float(meta.get("inicio") or time.mktime(time.strptime(d.name[:15], "%Y%m%d-%H%M%S")))
        except ValueError:
            continue
        wav = d / "reunion.wav"
        if wav.exists():
            arreglar_cabecera(wav)
        # Lo último que se escribió es lo más cerca que se sabe de cuándo se cortó.
        fin = max([inicio] + [f.stat().st_mtime for f in d.rglob("*") if f.is_file()])
        fotos = len(list((d / "fotos").glob("*.jpg"))) if (d / "fotos").is_dir() else 0
        _escribir(d / "meta.json", {"id": d.name, "origen": ORIGEN, "proceso": {"nombre": APP}, "titulo": "",
                                    **meta, "inicio": inicio, "fin": fin, "fotos": fotos,
                                    "cortada": "el puente se paró mientras grababa"})
        cerradas.append(d.name)
    return cerradas


class Grabadora:
    """La reunión en curso, si la hay: une el sonido y la pantalla del aparato con su carpeta."""

    def __init__(self, dispositivo: Dispositivo):
        self.dispositivo = dispositivo
        self.actual: Grabacion | None = None
        self.ultima: dict | None = None
        # Desde el clic hasta que graba pasan segundos (reconectar): otra pestaña
        # o el teléfono no pueden empezar otra en medio y dejar una huérfana.
        self.empezando = False
        self._fotos: asyncio.Task | None = None

    async def empezar(self, titulo: str, reconectar) -> Grabacion:
        """`reconectar` se llama si el aparato sólo da el sonido en una conexión nueva."""
        if self.actual is not None or self.empezando:
            raise ValueError("ya se está grabando una reunión")
        self.empezando = True
        try:
            d = self.dispositivo
            try:
                if await d.encender_sonido():
                    await reconectar()
                    d = self.dispositivo
                if not d.da_sonido:
                    raise AparatoNoDisponible("el aparato no manda el sonido del Mac"
                                              + (f": {d.estado().get('motivo')}" if d.estado().get("motivo") else ""))
            except BaseException:
                # Encendido se queda guardado en el aparato, y capturaría en cada conexión.
                with contextlib.suppress(Exception):
                    await d.apagar_sonido()
                raise
            g = Grabacion(titulo)
            self.actual = g
            d.oido = g.oir
            self._fotos = asyncio.create_task(self._mirar(g))
            return g
        finally:
            self.empezando = False

    async def _mirar(self, g: Grabacion) -> None:
        while True:
            t0 = time.time()
            try:
                img = await self.dispositivo.captura()
                await asyncio.to_thread(g.mirar, img, t0)
            except asyncio.CancelledError:
                raise
            except Exception:  # sin vídeo un momento (una reconexión): la vuelta siguiente
                pass
            await asyncio.sleep(max(0.05, FOTO_CADA_S - (time.time() - t0)))

    async def parar(self, cortada: str = "") -> dict:
        g = self.actual
        if g is None:
            raise ValueError("no se está grabando ninguna reunión")
        self.actual = None
        self.dispositivo.oido = None
        if self._fotos is not None:
            self._fotos.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._fotos
            self._fotos = None
        self.ultima = await asyncio.to_thread(g.terminar, None, cortada)
        # Apagado en el aparato: queda guardado en él, y encendido capturaría en cada conexión.
        with contextlib.suppress(Exception):
            await self.dispositivo.apagar_sonido()
        return self.ultima

    def estado(self) -> dict:
        g = self.actual
        if g is None:
            return {"grabando": False, "ultima": self.ultima}
        ahora = time.time()
        return {"grabando": True, "id": g.id, "desde": g.inicio, "segundos": int(ahora - g.inicio),
                "fotos": g.fotos, "con_sonido": g.ultimo_sonido is not None,
                "sin_sonido_s": int(ahora - (g.ultimo_sonido or g.inicio)), "error": g.error}
