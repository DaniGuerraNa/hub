"""Pasar a texto un audio, en casa.

🔴 **En casa y no en un servicio de fuera** (decisión 221). Lo que hay en estos
archivos es la voz de alguien —la madre de quien usa el hub, para el primer
encargo— describiendo su negocio: mandarla a transcribir a un tercero saca de la
máquina justo lo que la regla dura 22 protege, y lo haría en el formato más
íntimo que tiene este sistema.

🔴 **Y el hub no depende de whisper.** El transcriptor es un comando externo que
se declara en `encargos.yml`, por dos motivos que apuntan al mismo sitio:

- Este repo se publica y se instala en máquinas ajenas. Meter `faster-whisper`
  en las dependencias haría que quien sólo quiere el índice de proyectos se
  bajara doscientos megas de modelos que no va a usar.
- El modelo que va bien depende de la máquina. Medido aquí: `small` tarda 4,7 s
  en 105 s de audio y `base` 1,6 s. Elegir por él sería inventar su hardware.

Si no está configurado no se adivina nada y **el audio no se pierde**: se queda
aparcado con la razón escrita, que es lo que permite arreglarlo y volver a
intentarlo en vez de descubrir un hueco tres días después.
"""

from __future__ import annotations

import shlex
import subprocess
from pathlib import Path

# Un audio largo transcribe lento, y el relé no puede quedarse colgado en él: es
# el mismo proceso que atiende a todo el mundo. Medido con `small`, 105 s de
# audio son 4,7 s; este tope cubre un audio de diez minutos con margen de sobra.
TOPE_SEGUNDOS = 300


class SinTranscriptor(RuntimeError):
    """No hay comando configurado. Lleva dentro la línea que hay que escribir."""


class NoSeEntendio(RuntimeError):
    """Se ejecutó y no salió texto. No es lo mismo que no haber podido."""


def por_omision() -> list[str] | None:
    """El Whisper que ya trae Reuniones, si está preparado (decisión 295).

    No es depender de él: es no pedirle a nadie que instale dos veces lo mismo.
    El procesado de Reuniones lleva `faster-whisper` en su entorno, y quien lo
    preparó ya tiene un transcriptor que funciona en su máquina. Lo declarado
    en `encargos.yml` manda sobre esto.
    """
    from . import componentes, config

    python = componentes.carpeta("reuniones") / ".venv" / "bin" / "python"
    guion = config.RAIZ_REPO / "scripts" / "transcribir-whisper.py"
    if python.is_file() and guion.is_file():
        return [str(python), str(guion), "{audio}"]
    return None


def comando(ajustes: dict | None = None) -> list[str]:
    """Qué se ejecuta para transcribir, con `{audio}` donde va el archivo.

    Se admite una cadena o una lista. La lista es lo correcto —una cadena con un
    espacio en una ruta se parte por donde no es— pero la cadena es lo que uno
    escribe la primera vez, así que se acepta y se parte con `shlex`.
    """
    trozo = (ajustes or {}).get("transcripcion") or {}
    crudo = trozo.get("comando") or por_omision()
    if not crudo:
        raise SinTranscriptor(
            "no hay transcriptor. Lo más fácil: prepara Reuniones (su pantalla "
            "lo hace contigo), que trae Whisper, y el hub lo usa solo. O "
            "declara uno en `encargos.yml`:\n\n"
            "    transcripcion:\n"
            "      comando: [\"/ruta/a/python\", \"scripts/transcribir-whisper.py\", \"{audio}\"]"
        )
    partes = shlex.split(crudo) if isinstance(crudo, str) else [str(x) for x in crudo]
    if not any("{audio}" in p for p in partes):
        raise SinTranscriptor(
            "el comando de transcripción no dice dónde va el archivo: "
            "falta «{audio}» en alguno de sus argumentos"
        )
    return partes


def transcribir(ruta: Path, ajustes: dict | None = None) -> str:
    """El texto del audio. Levanta en vez de devolver vacío, y la diferencia importa.

    «No se pudo transcribir» y «se transcribió y no dijo nada» llevan a cosas
    distintas: lo primero se arregla y se reintenta, lo segundo se le pregunta a
    la persona. Devolver `""` en los dos casos los haría indistinguibles justo
    donde hay que distinguirlos.
    """
    ruta = Path(ruta)
    if not ruta.is_file():
        raise SinTranscriptor(f"no existe el audio «{ruta}»")

    linea = [p.replace("{audio}", str(ruta)) for p in comando(ajustes)]
    try:
        salida = subprocess.run(
            linea, capture_output=True, text=True, timeout=TOPE_SEGUNDOS, check=False,
        )
    except FileNotFoundError as exc:
        raise SinTranscriptor(f"no se pudo ejecutar «{linea[0]}»: {exc}") from exc
    except subprocess.TimeoutExpired as exc:
        raise SinTranscriptor(
            f"la transcripción pasó de {TOPE_SEGUNDOS} s y se cortó"
        ) from exc

    if salida.returncode != 0:
        # El stderr entero, no un resumen: lo que falla aquí suele ser un modelo
        # que no está descargado o un ffmpeg que falta, y esos mensajes traen el
        # remedio dentro.
        raise SinTranscriptor(
            f"el transcriptor salió con código {salida.returncode}: "
            f"{(salida.stderr or '').strip()[:500]}"
        )

    texto = (salida.stdout or "").strip()
    if not texto:
        raise NoSeEntendio("el transcriptor no devolvió texto")
    return texto


# Varios minutos de voz en webm. Más que eso no es un mensaje que se dicta.
LIMITE_AUDIO = 25 * 1024 * 1024
_EXTENSIONES = {"webm", "ogg", "m4a", "mp4", "wav", "mp3"}


def dictado(datos: bytes, nombre: str) -> str:
    """El texto de lo que se dictó en la web, para la terminal.

    El audio se escribe en `HUB_HOME/voz/` para poder transcribirlo y se borra
    en cuanto sale bien: es la voz de alguien explicando su trabajo, y ya está
    en texto. Si falla se queda, con lo que se puede reintentar o mirar qué
    pasó. Nada sale de la máquina (decisión 221).
    """
    import time

    import yaml

    from . import config

    if not datos:
        raise ValueError("el audio llegó vacío")
    if len(datos) > LIMITE_AUDIO:
        raise ValueError("el audio es demasiado largo para dictar")
    extension = (nombre.rsplit(".", 1)[-1] if "." in nombre else "webm").lower()
    if extension not in _EXTENSIONES:
        extension = "webm"
    carpeta = config.HUB_HOME / "voz"
    carpeta.mkdir(parents=True, exist_ok=True)
    ruta = carpeta / f"{time.strftime('%y%m%d-%H%M%S')}-{time.time_ns() % 10**6}.{extension}"
    ruta.write_bytes(datos)
    ajustes = {}
    if config.encargos_yml().is_file():
        ajustes = yaml.safe_load(config.encargos_yml().read_text(encoding="utf-8")) or {}
    texto = transcribir(ruta, ajustes)
    ruta.unlink(missing_ok=True)
    return texto

