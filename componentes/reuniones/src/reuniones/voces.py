"""Quién habla en la pista de la reunión: Persona 1, Persona 2… y sus nombres.

Tu voz ya se sabe —es la pista del micro—; la de la aplicación las mezcla a
todas. Aquí se separan con pyannote, en la GPU y sin que el audio salga de la
máquina (regla 1). Los nombres los pone el dueño en el hub y se guardan al lado,
en `nombres.json`: «Persona 2» → «Ana».

🔴 **pyannote trae telemetría encendida de fábrica**: manda métricas de uso a
`otel.pyannote.ai`. Se apaga A LA FUERZA antes de importarlo, y no con
`setdefault`: la regla 1 no deja que una variable de entorno olvidada la
vuelva a encender. Y el modelo se busca primero sin red (`HF_HUB_OFFLINE`):
internet sólo hace falta la primera vez, para descargarlo con el token de
Hugging Face que el dueño guarda con `hf auth login` (nunca en este repo).

Si no se puede separar —sin token, sin modelo, sin GPU—, la reunión se procesa
igual con «Reunión» y se dice por qué: las voces son una mejora, no un requisito.
"""
import os
from pathlib import Path

from . import carpeta

MODELO = os.environ.get("REUNIONES_DIARIZADOR", "pyannote/speaker-diarization-community-1")
_TUBERIA = None


class SinSeparar(RuntimeError):
    """No se pudieron separar las voces; el motivo va en el mensaje."""


def _tuberia():
    global _TUBERIA
    if _TUBERIA is not None:
        return _TUBERIA
    os.environ["PYANNOTE_METRICS_ENABLED"] = "false"
    import torch
    from huggingface_hub.errors import LocalEntryNotFoundError
    from pyannote.audio import Pipeline

    def cargar():
        return Pipeline.from_pretrained(MODELO)

    previo = os.environ.get("HF_HUB_OFFLINE")
    os.environ["HF_HUB_OFFLINE"] = "1"
    try:
        tuberia = cargar()
    except (LocalEntryNotFoundError, OSError, ValueError):
        # No está descargado: la única vez que hace falta red.
        if previo is None:
            os.environ.pop("HF_HUB_OFFLINE", None)
        else:
            os.environ["HF_HUB_OFFLINE"] = previo
        try:
            tuberia = cargar()
        except Exception as e:  # noqa: BLE001 — se dice por qué, no se tumba el procesado
            raise SinSeparar(
                f"no se pudo descargar {MODELO}: hace falta aceptar sus condiciones en "
                f"huggingface.co/{MODELO} y `hf auth login` ({e.__class__.__name__})") from e
    if tuberia is None:
        raise SinSeparar(f"{MODELO} no se cargó: ¿aceptaste sus condiciones en Hugging Face?")
    if torch.cuda.is_available():
        tuberia.to(torch.device("cuda"))
    _TUBERIA = tuberia
    return tuberia


def _onda(audio: Path):
    """El audio en memoria, mono y a 16 kHz, decodificado con `av` (lee WAV y Opus).

    Se le da a pyannote ya decodificado para no depender de qué códecs traiga
    su lector: la pista puede estar comprimida (comprimir.py).
    """
    import av
    import numpy as np
    import torch

    trozos = []
    with av.open(str(audio)) as f:
        remuestreo = av.AudioResampler(format="flt", layout="mono", rate=16000)
        for marco in f.decode(audio=0):
            for m in remuestreo.resample(marco):
                trozos.append(m.to_ndarray().reshape(-1))
        for m in remuestreo.resample(None):
            trozos.append(m.to_ndarray().reshape(-1))
    if not trozos:
        raise SinSeparar("la pista de la reunión está vacía")
    onda = np.concatenate(trozos).astype("float32")
    return {"waveform": torch.from_numpy(onda).unsqueeze(0), "sample_rate": 16000}


def turnos(audio: Path) -> list[dict]:
    """Quién habla y cuándo: `[{ini, fin, voz}]`, con la etiqueta cruda del modelo."""
    salida = _tuberia()(_onda(audio))
    # pyannote 4 devuelve un objeto con `.speaker_diarization`; el 3, la anotación.
    anotacion = getattr(salida, "exclusive_speaker_diarization", None) \
        or getattr(salida, "speaker_diarization", None) or salida
    return [{"ini": round(t.start, 2), "fin": round(t.end, 2), "voz": voz}
            for t, _, voz in anotacion.itertracks(yield_label=True)]


def asignar(segs: list[dict], turnos_: list[dict]) -> list[dict]:
    """Pone a cada intervención de «Reunión» la voz que más tiempo habla en ella.

    Se numeran por orden de aparición —la primera que habla es la Persona 1—,
    que es como se recuerda una reunión. Lo tuyo («Yo») no se toca: ya se sabe
    de quién es. Una intervención sin ninguna voz encima se queda en «Reunión».
    """
    orden: dict[str, str] = {}
    for t in sorted(turnos_, key=lambda t: t["ini"]):
        orden.setdefault(t["voz"], f"Persona {len(orden) + 1}")
    salida = []
    for s in segs:
        if s.get("quien") == "Yo":
            salida.append(s)
            continue
        solape: dict[str, float] = {}
        for t in turnos_:
            comun = min(s["fin"], t["fin"]) - max(s["ini"], t["ini"])
            if comun > 0:
                solape[t["voz"]] = solape.get(t["voz"], 0) + comun
        quien = orden[max(solape, key=solape.get)] if solape else "Reunión"
        salida.append({**s, "quien": quien})
    return salida


def separar(c: Path) -> list[dict]:
    """Separa las voces de una reunión ya transcrita y reescribe su transcripción."""
    from .comprimir import audio

    pista = audio(c, "reunion")
    if not pista:
        raise SinSeparar("no hay pista de la reunión")
    segs = carpeta.leer(c / "transcripcion.json") or []
    nuevos = asignar([{**s, "quien": "Yo" if s.get("quien") == "Yo" else "Reunión"} for s in segs],
                     turnos(pista))
    carpeta.escribir(c / "transcripcion.json", nuevos)
    return nuevos


# ─────────────────────────────── los nombres ────────────────────────────────


def nombres(c: Path) -> dict[str, str]:
    """`{"Persona 1": "Ana"}`, o vacío. Lo que no tiene nombre se queda como está."""
    datos = carpeta.leer(c / "nombres.json") or {}
    return {str(k): str(v).strip() for k, v in datos.items()
            if str(k).startswith("Persona ") and str(v).strip()}


def poner_nombres(c: Path, cambios: dict[str, str]) -> dict[str, str]:
    """Guarda los nombres. Uno vacío quita el que hubiera."""
    actuales = nombres(c)
    for clave, valor in cambios.items():
        clave, valor = str(clave), " ".join(str(valor).split())[:60]
        if not clave.startswith("Persona "):
            continue
        if valor:
            actuales[clave] = valor
        else:
            actuales.pop(clave, None)
    carpeta.escribir(c / "nombres.json", actuales)
    return actuales


def con_nombres(segs: list[dict], tabla: dict[str, str]) -> list[dict]:
    return [{**s, "quien": tabla.get(s.get("quien", ""), s.get("quien", ""))} for s in segs]
