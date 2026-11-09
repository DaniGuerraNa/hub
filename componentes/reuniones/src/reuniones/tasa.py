"""La frecuencia real de la pista de la reunión, antes de transcribir.

proctap pide 48 kHz a Windows y etiqueta así lo que entrega, pero la captura
por proceso llega a la frecuencia de la salida de audio: con unos audífonos a
96 kHz (2-nov) la pista decía 48 kHz y traía el doble de muestras. Leída a 48
kHz era ruido, Whisper no sacó ni una palabra y el resumen salió vacío.

El reloj no miente: la grabación duró `fin - inicio` (meta.json). Si la pista
dice durar otra cosa, su frecuencia es la declarada por esa proporción,
redondeada a una estándar, y se corrige la cabecera del WAV. Los 44 bytes
originales se guardan al lado: no se pierde nada y se puede deshacer.
"""
import struct
import wave
from pathlib import Path

from . import carpeta

ESTANDAR = (16000, 22050, 24000, 32000, 44100, 48000, 88200, 96000, 176400, 192000)
#: Margen para dar por buena la duración (el relleno de silencio la mueve un poco).
TOLERANCIA = 0.05


def corregir(c: Path, pista: str = "reunion") -> dict | None:
    """Corrige la cabecera si la duración no cuadra. Devuelve qué hizo, o None."""
    wav = c / f"{pista}.wav"
    meta = carpeta.leer(c / "meta.json") or {}
    if not wav.exists() or not meta.get("inicio") or not meta.get("fin"):
        return None
    real = float(meta["fin"]) - float(meta["inicio"])
    with wave.open(str(wav), "rb") as w:
        declarada, n = w.getframerate(), w.getnframes()
    if real <= 0 or n == 0:
        return None
    proporcion = (n / declarada) / real
    if abs(proporcion - 1) <= TOLERANCIA:
        return None
    nueva = min(ESTANDAR, key=lambda t: abs(t - declarada * proporcion))
    if abs(nueva / (declarada * proporcion) - 1) > TOLERANCIA:
        return {"pista": pista, "corregida": False, "motivo": f"dura {n / declarada:.0f} s y la grabación {real:.0f} s,"
                " y ninguna frecuencia estándar lo explica"}
    with open(wav, "r+b") as f:
        cabecera = f.read(44)
        if cabecera[:4] != b"RIFF" or cabecera[12:16] != b"fmt ":
            return {"pista": pista, "corregida": False, "motivo": "cabecera WAV no estándar"}
        (c / f"{pista}.wav.cabecera-original").write_bytes(cabecera)
        canales, bits = struct.unpack("<H", cabecera[22:24])[0], struct.unpack("<H", cabecera[34:36])[0]
        f.seek(24)
        f.write(struct.pack("<II", nueva, nueva * canales * bits // 8))
    hecho = {"pista": pista, "corregida": True, "de": declarada, "a": nueva}
    carpeta.escribir(c / "meta.json", {**meta, "tasa_corregida": hecho})
    return hecho
