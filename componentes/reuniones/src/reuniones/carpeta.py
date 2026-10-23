"""Cómo es la carpeta de una reunión. Es el contrato entre el agente de Windows
(que la llena mientras graba) y el procesado (que la lee al acabar).

    <raiz>/<id>/
      meta.json          lo escribe el agente: inicio, fin, monitor, proceso, micro
      reunion.wav        audio SÓLO de la aplicación (Teams…), por proceso
      micro.wav          tu micrófono, aparte
                         (reunion.opus / micro.opus si se comprimió: comprimir.py)
      fotos/<s>.jpg      fotogramas que cambiaron; <s> = segundos desde el inicio
      ── lo que deja el procesado ──
      transcripcion.json / .md
      resumen.json / .md
      procesado.json     estado por etapas y errores
      nombres.json       {"Persona 1": "Ana"}: el nombre de cada voz, si se pusieron (voces.py)
      ── lo que deja comprimir (a demanda) ──
      comprimiendo       marca vacía mientras se comprime (el hub no ofrece otra vez el botón)
      comprimido.json    antes/después en bytes y fecha, o {error}: si hay error, el WAV sigue ahí

`id` = AAAAMMDD-HHMMSS: ordena por fecha sin leer nada.
"""
import json
import os
import re
from pathlib import Path

ID = re.compile(r"^\d{8}-\d{6}$")


def raiz() -> Path:
    return Path(os.environ.get("REUNIONES_RAIZ") or "/mnt/d/reuniones/grabaciones")


def de(id_: str) -> Path:
    if not ID.match(id_ or ""):
        raise ValueError("id de reunión no válido")
    return raiz() / id_


def leer(ruta: Path) -> dict | None:
    try:
        return json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def escribir(ruta: Path, datos) -> None:
    tmp = ruta.with_suffix(ruta.suffix + ".tmp")
    tmp.write_text(json.dumps(datos, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(ruta)


def hhmmss(s: float) -> str:
    s = int(s)
    return f"{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}"
