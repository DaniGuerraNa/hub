"""Comprimir el audio de una reunión, cuando el dueño lo pide.

El WAV es lo que el agente puede escribir sin perder nada mientras graba
(~1 GB/h entre las dos pistas). Ya transcrita, la voz se oye igual en Opus
a 24 kbps mono (~10 MB/h por pista): unas 15 veces menos.

A demanda y no al terminar de procesar: es borrar el original, y eso lo
decide el dueño (principio del hub: nada automático que no se pueda deshacer).
Por eso también se comprueba antes de borrar: el .opus tiene que existir y
durar lo mismo que el WAV, o el WAV se queda.
"""
import subprocess
import time
from pathlib import Path

from . import carpeta

PISTAS = ("reunion", "micro")
KBPS = 24


def audio(c: Path, pista: str) -> Path | None:
    """La pista que haya: el WAV original o, si ya se comprimió, el .opus."""
    for ext in ("wav", "opus"):
        p = c / f"{pista}.{ext}"
        if p.exists():
            return p
    return None


def duracion(p: Path) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(p)],
                       capture_output=True, text=True, timeout=60)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return -1.0


def tamano(c: Path) -> int:
    return sum(f.stat().st_size for f in c.rglob("*") if f.is_file())


def comprimida(c: Path) -> bool:
    return not any((c / f"{p}.wav").exists() for p in PISTAS)


def comprimir(c: Path) -> dict:
    meta = carpeta.leer(c / "meta.json") or {}
    if not meta.get("fin"):
        raise RuntimeError("todavía se está grabando (o se cortó sin cerrar): no se comprime")
    # Medido: comprimir mientras se transcribe borra el WAV que Whisper está
    # leyendo, y el procesado falla. Primero se termina de procesar.
    if (carpeta.leer(c / "procesado.json") or {}).get("estado") == "procesando":
        raise RuntimeError("se está procesando: comprime cuando termine")
    antes = tamano(c)
    hechas = []
    for p in PISTAS:
        wav = c / f"{p}.wav"
        if not wav.exists():
            continue
        if wav.stat().st_size < 4096:          # pista vacía: no hay nada que guardar
            wav.unlink()
            continue
        opus = c / f"{p}.opus"
        tmp = c / f"{p}.opus.tmp"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(wav), "-ac", "1", "-c:a", "libopus",
                        "-b:a", f"{KBPS}k", "-application", "voip", "-f", "ogg", str(tmp)],
                       check=True, timeout=3600)
        dw, do = duracion(wav), duracion(tmp)
        if do < 0 or abs(dw - do) > 1.0:
            tmp.unlink(missing_ok=True)
            raise RuntimeError(f"{p}: el comprimido dura {do:.1f} s y el original {dw:.1f} s; no se borra nada")
        tmp.replace(opus)
        wav.unlink()
        hechas.append(p)
    r = {"fecha": time.time(), "antes": antes, "despues": tamano(c), "pistas": hechas, "kbps": KBPS}
    carpeta.escribir(c / "comprimido.json", r)
    return r
