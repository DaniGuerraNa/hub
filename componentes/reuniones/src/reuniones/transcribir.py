"""Transcripción local con faster-whisper en la GPU. El audio no sale de la máquina.

Dos pistas y no una mezcla: la de la aplicación es «la reunión» y la del micro
eres tú. Así quién dijo qué no se adivina (no hace falta diarización para lo
que más importa: separar tus compromisos de los de los demás).
"""
import os
from difflib import SequenceMatcher
from pathlib import Path

_MODELO = None


def _cargar_cuda():
    """ctranslate2 abre libcublas/libcudnn con dlopen y no las encuentra en el
    venv sin LD_LIBRARY_PATH (mismo arreglo que voice-assistant). Hay que
    ponerlo ANTES de cargar el modelo y en el proceso: por eso se precarga."""
    import ctypes
    try:
        import nvidia.cublas.lib as cb
        import nvidia.cudnn.lib as cd
    except ImportError:
        return
    for d in (cb.__path__[0], cd.__path__[0]):
        for nombre in sorted(os.listdir(d)):
            if nombre.endswith(".so") or ".so." in nombre:
                try:
                    ctypes.CDLL(os.path.join(d, nombre), mode=ctypes.RTLD_GLOBAL)
                except OSError:
                    pass


def modelo():
    global _MODELO
    if _MODELO is None:
        from faster_whisper import WhisperModel
        nombre = os.environ.get("REUNIONES_WHISPER", "large-v3")
        try:
            _cargar_cuda()
            _MODELO = WhisperModel(nombre, device="cuda", compute_type="float16")
        except Exception:
            _MODELO = WhisperModel(nombre, device="cpu", compute_type="int8")
    return _MODELO


def soltar_modelo() -> None:
    """Libera la GPU: Whisper large-v3 y pyannote no tienen por qué convivir."""
    global _MODELO
    _MODELO = None
    import gc
    gc.collect()


def pista(wav: Path, idioma: str | None = "es") -> list[dict]:
    if not wav.exists() or wav.stat().st_size < 4096:
        return []
    segs, _info = modelo().transcribe(str(wav), language=idioma, vad_filter=True,
                                      beam_size=5, condition_on_previous_text=False)
    return [{"ini": round(s.start, 2), "fin": round(s.end, 2), "texto": s.text.strip()}
            for s in segs if s.text.strip()]


def fusionar(reunion: list[dict], micro: list[dict]) -> list[dict]:
    """Las dos pistas en una línea de tiempo, con quién habla.

    Si el micro recoge lo que suena por los altavoces (sin cascos), tu pista
    repite a los demás: un segmento del micro que se solapa con uno de la
    reunión y dice casi lo mismo es eco, y se quita."""
    out = [{**s, "quien": "Reunión"} for s in reunion]
    for m in micro:
        eco = any(r["ini"] - 2 <= m["ini"] <= r["fin"] + 2 and
                  SequenceMatcher(None, r["texto"].lower(), m["texto"].lower()).ratio() > 0.7
                  for r in reunion)
        if not eco:
            out.append({**m, "quien": "Yo"})
    return sorted(out, key=lambda s: s["ini"])
