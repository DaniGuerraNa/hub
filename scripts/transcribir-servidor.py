#!/usr/bin/env python3
"""Whisper cargado y esperando, para el dictado y el modo voz (decisión 325).

`transcribir-whisper.py` arranca un intérprete y carga el modelo en cada frase.
Medido el 1-nov con 6 s de voz: 2,4-3,3 s por frase así, y 1,1 s con el modelo
ya cargado. En una conversación por voz esa diferencia se oye en cada turno.

Escucha en un **socket de Unix** dentro de `HUB_HOME/voz/` (permisos 600), nunca
en un puerto: es un servicio de esta máquina para este usuario (regla dura 8).
Una petición es una línea con la ruta del audio; la respuesta, una línea JSON
(`{"texto": …}` o `{"error": …}`). Sólo acepta audios de esa misma carpeta.

Se apaga solo tras `--ocioso` segundos sin peticiones: un modelo en memoria
todo el día por un dictado al mediodía no compensa. Lo arranca el hub cuando
hace falta (`transcribir.dictado`), y mientras tanto el dictado sigue por el
camino de siempre.

Va en la **GPU** si puede (decisión 330): ctranslate2 abre libcublas y
libcudnn con `dlopen` y en un venv no las encuentra sin `LD_LIBRARY_PATH`, así
que se precargan desde los paquetes `nvidia-*` del propio venv —el mismo
arreglo que Reuniones—. Si no están o la GPU falla, CPU como siempre.

Como el otro script, es un adaptador: se ejecuta con el intérprete que tenga
`faster_whisper`, no se importa desde el hub. Nada de aquí sale de la máquina.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import sys
from pathlib import Path


#: Los idiomas que se aceptan por petición: los de la conversación.
IDIOMAS = ("es", "en")

def _cargar_cuda() -> None:
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


def _modelo(nombre: str, dispositivo: str):
    from faster_whisper import WhisperModel
    if dispositivo in ("auto", "cuda"):
        try:
            _cargar_cuda()
            return WhisperModel(nombre, device="cuda", compute_type="float16"), "cuda"
        except Exception as exc:  # noqa: BLE001 — sin GPU, la CPU de siempre
            if dispositivo == "cuda":
                raise
            print(f"sin GPU ({str(exc)[:200]}): voy por CPU", file=sys.stderr, flush=True)
    return WhisperModel(nombre, device="cpu", compute_type="int8"), "cpu"


def main() -> int:
    partes = argparse.ArgumentParser(description=__doc__)
    partes.add_argument("socket")
    partes.add_argument("--modelo", default="small")
    partes.add_argument("--idioma", default="es")
    partes.add_argument("--ocioso", type=int, default=900)
    partes.add_argument("--dispositivo", choices=("auto", "cuda", "cpu"), default="auto")
    args = partes.parse_args()

    try:
        import faster_whisper  # noqa: F401
    except ImportError:
        print("este intérprete no tiene faster-whisper", file=sys.stderr)
        return 2

    ruta = Path(args.socket)
    carpeta = ruta.parent.resolve()
    modelo, dispositivo = _modelo(args.modelo, args.dispositivo)
    print(f"whisper {args.modelo} cargado en {dispositivo}", file=sys.stderr, flush=True)

    ruta.unlink(missing_ok=True)
    viejo = os.umask(0o177)
    servidor = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        servidor.bind(str(ruta))
    finally:
        os.umask(viejo)
    servidor.listen(4)
    servidor.settimeout(args.ocioso)
    try:
        while True:
            try:
                con, _ = servidor.accept()
            except socket.timeout:
                return 0
            with con:
                con.settimeout(30)
                try:
                    # La ruta sola, o `{"ruta", "idioma"}` (C-0159, el modo inglés).
                    linea = con.makefile("r", encoding="utf-8").readline().strip()
                    pedido = json.loads(linea) if linea.startswith("{") else {"ruta": linea}
                    idioma = pedido.get("idioma") if pedido.get("idioma") in IDIOMAS else args.idioma
                    audio = Path(str(pedido.get("ruta") or "")).resolve()
                    if audio.parent != carpeta or not audio.is_file():
                        respuesta = {"error": "sólo transcribo audios de la carpeta de voz del hub"}
                    else:
                        trozos, _ = modelo.transcribe(str(audio), language=idioma, vad_filter=True)
                        respuesta = {"texto": " ".join(t.text.strip() for t in trozos).strip()}
                except Exception as exc:  # noqa: BLE001 — una petición mala no tumba el servidor
                    respuesta = {"error": str(exc)[:300]}
                try:
                    con.sendall((json.dumps(respuesta, ensure_ascii=False) + "\n").encode())
                except OSError:
                    pass
    finally:
        servidor.close()
        ruta.unlink(missing_ok=True)


if __name__ == "__main__":
    sys.exit(main())
