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

import re
import shlex
import subprocess
from pathlib import Path

# Un audio largo transcribe lento, y el relé no puede quedarse colgado en él: es
# el mismo proceso que atiende a todo el mundo. Medido con `small`, 105 s de
# audio son 4,7 s; este tope cubre un audio de diez minutos con margen de sobra.
TOPE_SEGUNDOS = 300

# El código con que NUESTRO guion dice «lo oí y no había nada»: lo fija
# `scripts/transcribir-whisper.py`. Leído como fallo, un dictado de silencio
# enseñaba «salió con código 3» y un audio mudo de un encargo se reintentaba
# hasta rendirse por plazo (C-0150). Sólo vale para ese guion (C-0186): otro
# programa declarado en `encargos.yml` no ha firmado ese contrato, y un 3 suyo
# es un fallo como cualquier otro código.
CODIGO_NADA = 3


def _guion() -> Path:
    """El transcriptor del hub. Una ruta y no tres: la usan el de por omisión,
    el servidor rápido y el contrato del código 3."""
    from . import config

    return config.RAIZ_REPO / "scripts" / "transcribir-whisper.py"


def _habla_nuestro_contrato(partes: list[str]) -> bool:
    """Si lo que se ejecuta es nuestro guion, con los argumentos que sean.

    Por el nombre del archivo y no por la ruta entera: la forma documentada
    lo declara relativo (`scripts/transcribir-whisper.py`), y una copia del
    guion en otra carpeta sigue hablando su contrato. Más estricto es lo que
    hace falta para el servidor (`_python_del_servidor`), que lo SUSTITUYE.
    """
    return any(Path(p).name == _guion().name for p in partes)


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
    from . import componentes

    python = componentes.carpeta("reuniones") / ".venv" / "bin" / "python"
    guion = _guion()
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

    partes = comando(ajustes)
    linea = [p.replace("{audio}", str(ruta)) for p in partes]
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

    if salida.returncode == CODIGO_NADA and _habla_nuestro_contrato(partes):
        raise NoSeEntendio("no se entendió nada en el audio")
    if salida.returncode != 0:
        # El stderr entero, no un resumen: lo que falla aquí suele ser un modelo
        # que no está descargado o un ffmpeg que falta, y esos mensajes traen el
        # remedio dentro.
        raise SinTranscriptor(
            f"el transcriptor salió con código {salida.returncode}: "
            f"{(salida.stderr or '').strip()[:500]}"
        )

    return _validar(salida.stdout or "")


def _validar(texto: str) -> str:
    texto = texto.strip()
    if not texto:
        raise NoSeEntendio("el transcriptor no devolvió texto")
    if alucinacion(texto):
        raise NoSeEntendio(f"no se oyó a nadie hablar (Whisper inventó «{texto[:60]}»)")
    return texto


# ── Whisper cargado (decisión 325) ──────────────────────────────────────────
# Sólo para el transcriptor por omisión, el de Reuniones: uno declarado en
# `encargos.yml` es del dueño y se respeta tal cual.

#: Lo que se espera a que el servidor conteste una frase dictada.
ESPERA_SERVIDOR_S = 60
#: Tras arrancarlo, cuánto se tarda en volver a intentarlo si no aparece.
REARRANQUE_S = 30


def _python_del_servidor(ajustes: dict) -> str | None:
    """Con qué intérprete puede servir el Whisper cargado, o None si no puede.

    Lo declarado en `encargos.yml` manda (325): el servidor sólo lo sustituye
    si lo declarado es NUESTRO guion, sin más argumentos que el audio, porque
    entonces hace lo mismo —modelo e idioma por omisión— y sólo cambia cuánto
    tarda (2,6 s frente a ~1 s, medido el 5-nov, C-0155). Con otro guion u
    otro `--modelo`, lo declarado y por su camino.
    """
    if not (ajustes.get("transcripcion") or {}).get("comando"):
        return ""   # nada declarado: el de por omisión
    try:
        partes = comando(ajustes)
    except SinTranscriptor:
        return None
    guion = _guion()
    if len(partes) == 3 and partes[2] == "{audio}" and Path(partes[1]).resolve() == guion.resolve():
        return partes[0]
    return None


def _servidor(ruta: Path, python: str = "", idioma: str = "es") -> str | None:
    """El texto por el servidor con Whisper cargado, o None si no está (y
    entonces se arranca para la próxima: esta frase va por el camino de siempre)."""
    import json
    import socket
    import time

    carpeta = ruta.parent
    enchufe = carpeta / "whisper.sock"
    # Un socket de Unix no admite rutas de más de ~104 bytes: con un HUB_HOME
    # muy hondo el servidor no podría escuchar, y se sigue por el camino de siempre.
    if len(str(enchufe.resolve()).encode()) > 100:
        return None
    if enchufe.exists():
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as c:
                c.settimeout(ESPERA_SERVIDOR_S)
                c.connect(str(enchufe))
                # El español va como siempre, la ruta sola: un servidor de antes
                # de C-0159 que siga cargado lo entiende.
                pedido = str(ruta.resolve()) if idioma == "es" else json.dumps({"ruta": str(ruta.resolve()),
                                                                               "idioma": idioma})
                c.sendall((pedido + "\n").encode())
                linea = c.makefile("r", encoding="utf-8").readline()
            respuesta = json.loads(linea)
        except (OSError, ValueError):
            enchufe.unlink(missing_ok=True)   # un socket huérfano de un servidor muerto
            respuesta = None
        if respuesta and "texto" in respuesta:
            return respuesta["texto"]
        if respuesta and idioma != "es":
            return None   # un servidor viejo que no sabe de idiomas: por el camino de siempre
    marca = carpeta / "whisper.arrancando"
    try:
        reciente = time.time() - marca.stat().st_mtime < REARRANQUE_S
    except OSError:
        reciente = False
    if not reciente and not enchufe.exists():
        if python:
            _arrancar_servidor(enchufe, python)
        else:
            _arrancar_servidor(enchufe)
        marca.touch()
    return None


def _arrancar_servidor(enchufe: Path, python: str = "") -> None:
    from . import config, procesos

    linea = [python] if python else por_omision()
    if not linea:
        return
    guion = config.RAIZ_REPO / "scripts" / "transcribir-servidor.py"
    # Lo arrancan servicios (secretario, encargos, el orquestador): fuera de su
    # cgroup, o el modelo cargado moriría con el primer reinicio (decisión 344).
    try:
        procesos.desasir([linea[0], str(guion), str(enchufe)])
    except OSError as exc:
        # En voz alta (C-0124): sin servidor cada dictado carga el modelo de
        # cero y sigue funcionando, sólo que más lento y sin decir por qué.
        print(f"[transcribir] no arrancó el servidor de Whisper ({linea[0]}): {exc}", flush=True)


# 🔴 Lo que Whisper «oye» en el silencio o el ruido: frases de los subtítulos
# con que se entrenó. Medido el 2026-10-24: un tono sin voz salió como
# «Subtítulos por la comunidad de Amara.org» y, con la conversación continua
# del secretario, se mandó como mensaje del dueño. Sólo se descarta si el
# texto ENTERO es una de éstas: dentro de una frase real no se toca.
_ALUCINACIONES = (
    "subtitulos por la comunidad de amara org", "subtitulos realizados por la comunidad de amara org",
    "subtitulado por la comunidad de amara org", "subtitles by the amara org community",
    "gracias por ver", "gracias por ver el video", "gracias por vernos", "muchas gracias por ver el video",
    "suscribete", "suscribete al canal", "no olvides suscribirte", "thank you for watching",
    "thanks for watching", "musica", "aplausos", "silencio", "risas",
)


def alucinacion(texto: str) -> bool:
    import unicodedata
    t = unicodedata.normalize("NFKD", texto.lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = " ".join(re.sub(r"[^\w\s]", " ", t).split())
    return not t or t in _ALUCINACIONES


# Varios minutos de voz en webm. Más que eso no es un mensaje que se dicta.
LIMITE_AUDIO = 25 * 1024 * 1024
_EXTENSIONES = {"webm", "ogg", "m4a", "mp4", "wav", "mp3"}


IDIOMAS = ("es", "en")


def dictado(datos: bytes, nombre: str, idioma: str = "es") -> str:
    """El texto de lo que se dictó en la web, para la terminal.

    El audio se escribe en `HUB_HOME/voz/` para poder transcribirlo y se borra
    en cuanto sale bien: es la voz de alguien explicando su trabajo, y ya está
    en texto. Si falla se queda diez días (`podar_dictados`, decisión 362), con
    lo que se puede reintentar o mirar qué pasó. Nada sale de la máquina
    (decisión 221).
    """
    import time

    import yaml

    from . import config

    if not datos:
        raise ValueError("el audio llegó vacío")
    if idioma not in IDIOMAS:
        raise ValueError(f"idioma no admitido: {idioma}")
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
    python = _python_del_servidor(ajustes)
    if python is None and idioma != "es":
        # Otro transcriptor declarado no sabe de idiomas: transcribiría en el
        # suyo sin decirlo, y en el modo inglés eso es texto inventado.
        ruta.unlink(missing_ok=True)
        raise ValueError("el transcriptor declarado en encargos.yml no sabe cambiar de idioma; "
                         "para el inglés, usa el del hub (scripts/transcribir-whisper.py)")
    rapido = None if python is None else _servidor(ruta, python, idioma)
    if rapido is None and idioma != "es":
        ajustes = {**ajustes, "transcripcion": {"comando": comando(ajustes) + ["--idioma", idioma]}}
    texto = _validar(rapido) if rapido is not None else transcribir(ruta, ajustes)
    ruta.unlink(missing_ok=True)
    return texto



#: Lo que se queda un audio de dictado que falló. Basta para mirar qué pasó o
#: reintentarlo a mano; después es la voz de alguien guardada sin que nadie lo
#: pidiera (decisión 362, como lo pegado en la terminal en la 288).
DICTADO_CADUCA_DIAS = 10


def podar_dictados(ahora: float | None = None) -> int:
    """Borra los audios de `HUB_HOME/voz/` de más de diez días. Devuelve cuántos.

    Va en el ciclo lento. Sólo audio, por su extensión: en la misma carpeta
    viven el socket y la marca del Whisper cargado, que no son de nadie.
    """
    import time

    from . import config

    carpeta = config.HUB_HOME / "voz"
    if not carpeta.is_dir():
        return 0
    limite = (time.time() if ahora is None else ahora) - DICTADO_CADUCA_DIAS * 86400
    borrados = 0
    for archivo in carpeta.iterdir():
        if archivo.suffix.lstrip(".").lower() not in _EXTENSIONES or not archivo.is_file():
            continue
        try:
            if archivo.stat().st_mtime < limite:
                archivo.unlink()
                borrados += 1
        except FileNotFoundError:
            pass   # lo borró a la vez un dictado que acabó bien
    return borrados
