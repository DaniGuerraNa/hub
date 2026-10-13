#!/usr/bin/env python3
"""Transcribe un audio con faster-whisper y lo escribe en la salida estándar.

Adaptador, no dependencia: el hub no importa nada de aquí, lo ejecuta. Se apunta
con `transcripcion.comando` en `encargos.yml` usando el intérprete que tenga
`faster_whisper` instalado, que no tiene por qué ser el del hub.

    transcripcion:
      comando: ["/ruta/al/python", "scripts/transcribir-whisper.py", "{audio}"]

Modelo por omisión `small`. Medido en esta máquina sobre audio con voz de
principio a fin —que es el caso que importa, no un archivo con silencios—:

    180 s de grabación  →  19,3 s con `small`  ·  10,3 s con `base`
    cargar el modelo     →  1,3 s de esos

O sea que un audio de tres minutos está transcrito en veinte segundos, dentro de
lo que tapa el indicador «escribiendo…» de Telegram. `base` va al doble pero se
come nombres propios, que en una tienda de barrio son la mitad de lo que importa.

🔴 Un número anterior decía «22× tiempo real» y salía de un archivo con mucho
silencio: con `vad_filter` los huecos no se transcriben, así que el ritmo depende
de cuánta voz haya dentro. El de arriba es el malo, que es el que hay que poder
defender.

🔴 Nada de esto sale de la máquina. Si algún día este script llama a una API,
deja de ser cierta la decisión n4 y hay que decirlo en voz alta.
"""

from __future__ import annotations

import argparse
import sys


def main() -> int:
    partes = argparse.ArgumentParser(description=__doc__)
    partes.add_argument("audio")
    partes.add_argument("--modelo", default="small")
    partes.add_argument("--idioma", default="es")
    args = partes.parse_args()

    try:
        from faster_whisper import WhisperModel
    except ImportError:
        print(
            "este intérprete no tiene faster-whisper. Instálalo en uno que lo "
            "tenga y apunta ahí `transcripcion.comando` en encargos.yml",
            file=sys.stderr,
        )
        return 2

    modelo = WhisperModel(args.modelo, device="cpu", compute_type="int8")
    trozos, _ = modelo.transcribe(args.audio, language=args.idioma, vad_filter=True)
    texto = " ".join(t.text.strip() for t in trozos).strip()
    if not texto:
        return 3      # se entendió nada; el hub lo distingue de no haber podido
    print(texto)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
