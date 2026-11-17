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
hace falta: al empezar a grabar (`transcribir.calentar`, C-0292) o con la
primera frase (`transcribir.dictado`). La frase que llega mientras carga le
espera unos segundos; si no, sigue por el camino de siempre. El socket se
abre ya caliente: antes pasa un segundo de silencio por el modelo.

Va en la **GPU** si puede (decisión 330): ctranslate2 abre libcublas y
libcudnn con `dlopen` y en un venv no las encuentra sin `LD_LIBRARY_PATH`, así
que se precargan desde los paquetes `nvidia-*` del propio venv —el mismo
arreglo que Reuniones—. Si no están o la GPU falla, CPU como siempre.

Además de audios, entiende dos órdenes por la misma línea JSON (C-0312):
`{"orden": "estado"}` contesta qué tiene cargado (modelo, tipo de cálculo,
dispositivo, pid y lo que tardó en estar listo) y `{"orden": "apagar"}`
contesta y sale, soltando la memoria de la GPU en el acto. Las usa el banco
de dictado para medir una configuración tras otra, un modelo a la vez.

Como el otro script, es un adaptador: se ejecuta con el intérprete que tenga
`faster_whisper`, no se importa desde el hub. Nada de aquí sale de la máquina.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import time
from pathlib import Path


#: Los idiomas que se aceptan por petición: los de la conversación.
IDIOMAS = ("es", "en")

def _segundos(valor):
    return round(valor, 2) if isinstance(valor, (int, float)) else None


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


#: El tipo de cálculo de siempre en cada sitio, si no se pide otro.
TIPO_GPU = "float16"
TIPO_CPU = "int8"


def _modelo(nombre: str, dispositivo: str, tipo: str | None = None):
    """El modelo, dónde quedó y con qué tipo de cálculo.

    `tipo` es el que se pide (C-0312); si la GPU cae con `auto`, la CPU se
    carga con el suyo de siempre, porque el pedido era para la GPU (`float16`
    en la CPU ni siquiera carga). Se devuelve el que quedó, que es lo que se
    mide."""
    from faster_whisper import WhisperModel
    if dispositivo in ("auto", "cuda"):
        try:
            _cargar_cuda()
            elegido = tipo or TIPO_GPU
            return WhisperModel(nombre, device="cuda", compute_type=elegido), "cuda", elegido
        except Exception as exc:  # noqa: BLE001 — sin GPU, la CPU de siempre
            if dispositivo == "cuda":
                raise
            print(f"sin GPU ({str(exc)[:200]}): voy por CPU", file=sys.stderr, flush=True)
    elegido = (tipo if dispositivo == "cpu" else None) or TIPO_CPU
    return WhisperModel(nombre, device="cpu", compute_type=elegido), "cpu", elegido


def _calentar(modelo, idioma: str) -> None:
    """Un segundo de silencio por el modelo antes de abrir el socket (C-0292).

    La primera llamada en la GPU inicializa cuBLAS y cuDNN, y la pagaba la
    primera frase dictada. Así, que exista el socket quiere decir «cargado y
    caliente». Sin VAD, porque con silencio no dejaría pasar nada al modelo;
    con un haz y sin reintentos, porque sólo se trata de que corra una vez.
    Si falla, se sigue: es un adelanto, no una condición."""
    import io
    import wave

    sonido = io.BytesIO()
    with wave.open(sonido, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\0\0" * 16000)
    sonido.seek(0)
    try:
        trozos, _ = modelo.transcribe(sonido, language=idioma, vad_filter=False, beam_size=1, temperature=0.0)
        for _ in trozos:   # perezoso: sin leerlo, no corre
            pass
    except Exception as exc:  # noqa: BLE001 — sin calentar se transcribe igual
        print(f"no se pudo calentar el modelo ({str(exc)[:200]}): sigo", file=sys.stderr, flush=True)


def main() -> int:
    partes = argparse.ArgumentParser(description=__doc__)
    partes.add_argument("socket")
    partes.add_argument("--modelo", default="small")
    partes.add_argument("--idioma", default="es")
    partes.add_argument("--ocioso", type=int, default=900)
    partes.add_argument("--dispositivo", choices=("auto", "cuda", "cpu"), default="auto")
    partes.add_argument("--tipo", default=None, help="compute_type de ctranslate2 (float16, int8_float16, int8…)")
    args = partes.parse_args()

    try:
        import faster_whisper  # noqa: F401
    except ImportError:
        print("este intérprete no tiene faster-whisper", file=sys.stderr)
        return 2

    ruta = Path(args.socket)
    carpeta = ruta.parent.resolve()
    t_carga = time.perf_counter()
    modelo, dispositivo, tipo = _modelo(args.modelo, args.dispositivo, args.tipo)
    print(f"whisper {args.modelo} ({tipo}) cargado en {dispositivo}", file=sys.stderr, flush=True)
    _calentar(modelo, args.idioma)
    # Lo que tardó en estar listo, cargar y calentar: lo que se paga en frío.
    s_carga = _segundos(time.perf_counter() - t_carga)

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
                    orden = pedido.get("orden")
                    if orden == "apagar":
                        # Se contesta antes de salir: quien lo pide sabe así
                        # que es un servidor que entiende la orden y no hace
                        # falta mandarle una señal. Al salir se borra el socket.
                        con.sendall((json.dumps({"ok": True}) + "\n").encode())
                        print("apagado a petición", file=sys.stderr, flush=True)
                        return 0
                    if orden == "estado":
                        respuesta = {"modelo": args.modelo, "tipo": tipo, "dispositivo": dispositivo,
                                     "pid": os.getpid(), "s_carga": s_carga}
                        con.sendall((json.dumps(respuesta) + "\n").encode())
                        continue
                    if orden is not None:
                        raise ValueError(f"orden desconocida: {str(orden)[:40]}")
                    idioma = pedido.get("idioma") if pedido.get("idioma") in IDIOMAS else args.idioma
                    audio = Path(str(pedido.get("ruta") or "")).resolve()
                    if audio.parent != carpeta or not audio.is_file():
                        respuesta = {"error": "sólo transcribo audios de la carpeta de voz del hub"}
                    else:
                        t0 = time.perf_counter()
                        trozos, info = modelo.transcribe(str(audio), language=idioma, vad_filter=True)
                        texto = " ".join(t.text.strip() for t in trozos).strip()
                        # Lo que se midió, nunca el texto (C-0246). El generador de
                        # `transcribe` es perezoso: el tiempo cuenta tras leerlo entero.
                        respuesta = {"texto": texto, "medidas": {
                            "ms_whisper": round((time.perf_counter() - t0) * 1000),
                            "modelo": args.modelo, "tipo": tipo, "dispositivo": dispositivo,
                            "s_audio": _segundos(getattr(info, "duration", None)),
                            "s_voz": _segundos(getattr(info, "duration_after_vad", None))}}
                except Exception as exc:  # noqa: BLE001 — una petición mala no tumba el servidor
                    respuesta = {"error": str(exc)[:300]}
                    # Al registro del servidor (stderr): el mensaje de la excepción, no lo dictado.
                    print(f"error en una petición: {respuesta['error']}", file=sys.stderr, flush=True)
                try:
                    con.sendall((json.dumps(respuesta, ensure_ascii=False) + "\n").encode())
                except OSError:
                    pass
    finally:
        servidor.close()
        ruta.unlink(missing_ok=True)


if __name__ == "__main__":
    sys.exit(main())
