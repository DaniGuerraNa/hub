#!/usr/bin/env python3
"""¿Hay una reunión en esta captura? Leído en esta máquina (decisión 337).

Las capturas de una reunión no salen de la PC (regla 1 de Reuniones): en
lugar de enseñársela a un modelo, se lee su texto con un OCR local
(rapidocr, ONNX) y se buscan los controles de la llamada. Una reunión de
Teams, Zoom o Meet siempre pinta un botón para irse («Salir», «Leave»,
«Colgar»…) junto a los de cámara, micro o compartir; al colgar desaparecen.

Como `transcribir-whisper.py`, es un adaptador: se ejecuta con el intérprete
que tenga `rapidocr_onnxruntime`. Imprime una línea JSON:
`{"reunion": true|false, "marcas": [...]}`.
"""

from __future__ import annotations

import json
import sys
import unicodedata

IRSE = ("salir", "leave", "colgar", "hang up", "abandonar", "end call", "finalizar")
CONTROLES = ("camara", "camera", "microfono", "mic", "silenciar", "mute", "compartir", "share", "chat",
             "personas", "people", "participantes", "participants", "reaccionar", "react")


def _plano(t: str) -> str:
    t = unicodedata.normalize("NFKD", t.lower())
    return "".join(c for c in t if not unicodedata.combining(c)).strip()


def decidir(textos: list[str]) -> dict:
    planos = [_plano(t) for t in textos]
    irse = [t for t in planos if any(t == m or t.startswith(m) for m in IRSE)]
    controles = [t for t in planos if any(t == m or t.startswith(m) for m in CONTROLES)]
    return {"reunion": bool(irse) and bool(controles), "marcas": (irse + controles)[:8]}


def main() -> int:
    from rapidocr_onnxruntime import RapidOCR
    resultado, _ = RapidOCR()(sys.argv[1])
    print(json.dumps(decidir([r[1] for r in resultado or []]), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
