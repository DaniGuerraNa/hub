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
#: Lo que espera una frase a que acabe de cargar el servidor que ya arranca,
#: antes de irse por el camino frío (C-0292). El frío carga OTRO modelo en la
#: CPU (2,4-3,3 s, decisión 325) mientras el primero se carga: dos cargas a la
#: vez. La carga en la GPU no está medida; 8 s es el tope del informe.
ESPERA_ARRANQUE_S = 8


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


#: Lo que se espera a que el servidor conteste una orden (estado, apagar).
ESPERA_ORDEN_S = 3


def cabe_el_socket(enchufe: Path) -> bool:
    """Un socket de Unix no admite rutas de más de ~104 bytes: con un HUB_HOME
    muy hondo el servidor no podría escuchar."""
    return len(str(Path(enchufe).resolve()).encode()) <= 100


def pedir(enchufe: Path, pedido: dict | str, espera: float = ESPERA_SERVIDOR_S, *,
          quien: dict | None = None) -> dict | None:
    """Una petición al servidor de Whisper cargado y su respuesta (C-0312).

    El único cliente de su socket: el dictado, `estado_servidor`,
    `apagar_servidor` y el banco de dictado pasan por aquí. `pedido` es un
    diccionario (va en una línea JSON) o la ruta del audio sola, que es lo que
    entiende un servidor de antes de C-0159. Devuelve la respuesta, o None si
    no hay nadie escuchando o no contestó a tiempo.

    `quien`, si se pasa, recibe al conectar el pid y el uid de quien escucha
    (`SO_PEERCRED`, lo da el núcleo y no el servidor) y su huella: para
    apagarlo hay que saber quién es antes de que se vaya."""
    import json
    import socket
    import struct

    from . import procesos

    linea = pedido if isinstance(pedido, str) else json.dumps(pedido, ensure_ascii=False)
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as c:
            c.settimeout(espera)
            c.connect(str(enchufe))
            if quien is not None:
                pid, uid, _ = struct.unpack("3i", c.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED,
                                                               struct.calcsize("3i")))
                quien.update({"pid": pid, "uid": uid, "huella": procesos.huella(pid)})
            c.sendall((linea + "\n").encode())
            respuesta = json.loads(c.makefile("r", encoding="utf-8").readline())
    except (OSError, ValueError):
        return None
    return respuesta if isinstance(respuesta, dict) else None


def interprete_del_servidor() -> str | None:
    """Con qué intérprete se arranca el servidor de Whisper (C-0312): «» es
    el de por omisión (el de Reuniones), una ruta es el de lo declarado en
    `encargos.yml` si es nuestro guion tal cual, y None si lo declarado es
    otro programa: entonces no hay servidor, porque lo declarado manda (325)."""
    return _python_del_servidor(_ajustes())


def _servidor(ruta: Path, python: str = "", idioma: str = "es", medidas: dict | None = None) -> str | None:
    """El texto por el servidor con Whisper cargado, o None si no está (y
    entonces se arranca para la próxima: esta frase va por el camino de siempre).

    `medidas`, si se pasa, recibe lo que el servidor midió de esa frase
    (C-0246): tiempos y duraciones, nunca el texto."""
    carpeta = ruta.parent
    enchufe = carpeta / "whisper.sock"
    # Con un HUB_HOME muy hondo el servidor no podría escuchar, y se sigue por
    # el camino de siempre.
    if not cabe_el_socket(enchufe):
        return None
    if not enchufe.exists():
        _esperar_al_que_carga(carpeta, enchufe)
    if enchufe.exists():
        # El español va como siempre, la ruta sola: un servidor de antes de
        # C-0159 que siga cargado lo entiende.
        pedido = str(ruta.resolve()) if idioma == "es" else {"ruta": str(ruta.resolve()), "idioma": idioma}
        respuesta = pedir(enchufe, pedido)
        if respuesta is None:
            enchufe.unlink(missing_ok=True)   # un socket huérfano de un servidor muerto
        if respuesta and "texto" in respuesta:
            if medidas is not None and isinstance(respuesta.get("medidas"), dict):
                medidas.update(respuesta["medidas"])
            return respuesta["texto"]
        if respuesta and idioma != "es":
            return None   # un servidor viejo que no sabe de idiomas: por el camino de siempre
    _arrancar_si_toca(enchufe, python)
    return None


def _marca(enchufe: Path) -> Path:
    """Donde deja su huella el servidor de `enchufe` (`whisper.arrancando`
    para el del dictado, C-0292)."""
    return Path(enchufe).with_suffix(".arrancando")


def _huella_de(marca: Path) -> dict | None:
    import json

    try:
        huella = json.loads(marca.read_text(encoding="utf-8") or "null")
    except (OSError, ValueError):
        return None
    return huella if isinstance(huella, dict) else None


def _escribir_marca(marca: Path, huella: dict | None) -> None:
    """La marca, sólo para el dueño (600) aunque ya existiera de antes."""
    import json
    import os

    fd = os.open(marca, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(json.dumps(huella))
    os.chmod(marca, 0o600)


def _escucha(enchufe: Path) -> bool:
    """Si alguien escucha en el socket. Que exista el archivo no lo dice: tras
    un `kill -9` o un reinicio queda el archivo y nadie detrás (C-0312)."""
    import socket

    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as c:
            c.settimeout(0.5)
            c.connect(str(enchufe))
        return True
    except OSError:
        return False


def _arrancar_si_toca(enchufe: Path, python: str = "") -> bool:
    """Arranca el servidor si no está ni se arrancó hace poco. Devuelve si lo arrancó.

    La marca `whisper.arrancando` lleva la huella del proceso que carga
    (C-0292): quien llega mientras tanto le espera sólo si sigue vivo. Pasado
    `REARRANQUE_S` tampoco se relanza mientras esa huella siga viva: es el que
    está sirviendo. Un socket que existe y no escucha es un huérfano: se quita
    y se arranca otro. Que dos lleguen a la vez lo resuelve el cerrojo de
    `arrancar_servidor`."""
    import time

    from . import procesos

    marca = _marca(enchufe)
    try:
        reciente = time.time() - marca.stat().st_mtime < REARRANQUE_S
    except OSError:
        reciente = False
    # La huella viva antes que el socket: entre `bind` y `listen` el socket
    # existe y aún no acepta, y no es un huérfano.
    if reciente or procesos.vivo(_huella_de(marca)):
        return False
    if enchufe.exists():
        if _escucha(enchufe):
            return False
        enchufe.unlink(missing_ok=True)
    huella = _arrancar_servidor(enchufe, python) if python else _arrancar_servidor(enchufe)
    if not marca.exists():
        # No se lanzó nada (no hay con qué): que no se reintente en cada frase.
        _escribir_marca(marca, None)
    return huella is not None


def _esperar_al_que_carga(carpeta: Path, enchufe: Path) -> None:
    """Si hay un servidor cargando (lo arrancó `calentar` al empezar a grabar,
    o la frase de antes), espera a su socket hasta `ESPERA_ARRANQUE_S`, y sólo
    mientras el proceso siga vivo (C-0292): uno que no arranca —sin
    faster-whisper— no puede costar la espera entera en cada frase."""
    import json
    import time

    from . import procesos

    marca = carpeta / "whisper.arrancando"
    try:
        if time.time() - marca.stat().st_mtime >= REARRANQUE_S:
            return
        huella = json.loads(marca.read_text(encoding="utf-8") or "null")
    except (OSError, ValueError):
        return
    if not isinstance(huella, dict):
        return
    limite = time.monotonic() + ESPERA_ARRANQUE_S
    while time.monotonic() < limite and procesos.vivo(huella):
        if enchufe.exists():
            # El socket existe desde `bind` y acepta desde `listen`, justo
            # después: un `connect` en ese hueco fallaría y se tomaría por huérfano.
            time.sleep(0.05)
            return
        time.sleep(0.1)


def calentar() -> str:
    """Que el Whisper cargado esté listo para la frase que se empieza a dictar (C-0292).

    Lo llama `POST /api/voz/calentar` al empezar a grabar: la frase dura uno o
    dos segundos como poco, y la carga queda casi tapada. Uno de cada cuatro
    dictados llegaba con el servidor ya apagado (se apaga a los 15 min) y se
    pagaba entero en la CPU, cargando el modelo. Devuelve en qué quedó:
    «listo», «arrancando» o «no» (lo declarado no es nuestro guion, o no hay
    transcriptor: nada que calentar).
    """
    from . import config

    python = interprete_del_servidor()
    if python is None or (not python and not por_omision()):
        return "no"
    carpeta = config.HUB_HOME / "voz"
    carpeta.mkdir(parents=True, exist_ok=True)
    enchufe = carpeta / "whisper.sock"
    if not cabe_el_socket(enchufe):
        return "no"
    if enchufe.exists() and _escucha(enchufe):
        return "listo"
    _arrancar_si_toca(enchufe, python)
    return "arrancando"


def _arrancar_servidor(enchufe: Path, python: str = "") -> dict | None:
    """El servidor del dictado, con el modelo y el tipo de siempre."""
    return arrancar_servidor(enchufe, python=python)


#: Lo que se acepta como modelo o tipo de cálculo: un nombre (`large-v3-turbo`,
#: `int8_float16`) o la carpeta de un modelo; nunca algo que empiece por «-» y
#: el guion leyera como otra opción.
_VALOR_SERVIDOR = re.compile(r"^[\w.][\w./-]{0,79}$")
DISPOSITIVOS = ("auto", "cuda", "cpu")


def arrancar_servidor(enchufe: Path, *, python: str = "", modelo: str = "small", tipo: str | None = None,
                      dispositivo: str = "auto", ocioso: int = 900) -> dict | None:
    """Lanza el servidor de Whisper en `enchufe` y devuelve la huella del
    proceso, o None si no se lanzó (C-0312).

    `python` vacío es el de por omisión (el de Reuniones). Sólo lo que no es
    lo de siempre va en la línea: el servidor del dictado se lanza igual que
    antes. Vuelve en el acto: el socket aparece cuando el modelo está cargado
    y caliente. El servidor sólo transcribe audios de la carpeta de su socket.
    """
    from . import config, procesos

    if not _VALOR_SERVIDOR.match(str(modelo)):
        raise ValueError(f"modelo no válido: {modelo!r}")
    if tipo is not None and not _VALOR_SERVIDOR.match(str(tipo)):
        raise ValueError(f"tipo de cálculo no válido: {tipo!r}")
    if dispositivo not in DISPOSITIVOS:
        raise ValueError(f"dispositivo no válido: {dispositivo!r} (uno de {', '.join(DISPOSITIVOS)})")
    linea = [python] if python else por_omision()
    if not linea:
        return None
    guion = config.RAIZ_REPO / "scripts" / "transcribir-servidor.py"
    orden = [linea[0], str(guion), str(enchufe)]
    if modelo != "small":
        orden += ["--modelo", modelo]
    if tipo:
        orden += ["--tipo", tipo]
    if dispositivo != "auto":
        orden += ["--dispositivo", dispositivo]
    if int(ocioso) != 900:
        orden += ["--ocioso", str(int(ocioso))]
    # Lo arrancan servicios (secretario, encargos, el orquestador): fuera de su
    # cgroup, o el modelo cargado moriría con el primer reinicio (decisión 344).
    # Con su registro (C-0246): sin él, «cargado en cuda/cpu» y sus errores iban
    # a ninguna parte y no se sabía si la GPU había caído a CPU.
    #
    # 🔴 En exclusiva, y con la marca escrita ANTES de lanzar (C-0312): dos
    # llamadas a la vez arrancaban dos servidores; el segundo hacía
    # `unlink`+`bind` y el primero, al salir, borraba el socket del vivo. Bajo
    # el cerrojo se mira si ya hay uno —escuchando, o cargando con su huella
    # viva— y entonces no se lanza otro.
    marca = _marca(enchufe)
    with _cerrojo(enchufe):
        if _escucha(enchufe) or procesos.vivo(_huella_de(marca)):
            return None
        _escribir_marca(marca, None)
        registro = None
        try:
            registro = _abrir_registro_servidor(enchufe.parent)
            lanzado = procesos.desasir(orden, salida=registro)
            pid = getattr(lanzado, "pid", None)
            huella = procesos.huella(pid) if pid else None
        except OSError as exc:
            # En voz alta (C-0124): sin servidor cada dictado carga el modelo de
            # cero y sigue funcionando, sólo que más lento y sin decir por qué.
            print(f"[transcribir] no arrancó el servidor de Whisper ({linea[0]}): {exc}", flush=True)
            return None
        finally:
            if registro is not None:
                registro.close()   # el hijo ya heredó su copia
        # Su huella junto al socket: mientras carga aún no hay socket, y por
        # ella lo encuentran quien le espera y `apagar_servidor`.
        if huella:
            _escribir_marca(marca, huella)
    return huella


def _cerrojo(enchufe: Path):
    """Un cerrojo por socket (`flock` sobre `<socket>.cerrojo`, 600): vale
    entre procesos y entre hilos, porque cada llamada abre el suyo."""
    import contextlib
    import fcntl
    import os

    @contextlib.contextmanager
    def tomado():
        fd = os.open(Path(enchufe).with_suffix(".cerrojo"), os.O_WRONLY | os.O_CREAT, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)
    return tomado()


def estado_servidor(enchufe: Path) -> dict | None:
    """Qué tiene cargado el servidor de `enchufe`: `{modelo, tipo, dispositivo,
    pid, s_carga}`, o None si no hay servidor, está ocupado o es uno de antes
    de C-0312 que no entiende la orden."""
    enchufe = Path(enchufe)
    if not enchufe.exists():
        return None
    respuesta = pedir(enchufe, {"orden": "estado"}, ESPERA_ORDEN_S)
    if not respuesta or "error" in respuesta or "modelo" not in respuesta:
        return None
    return respuesta


def _es_el_guion(pid: int) -> bool:
    """Si lo que corre con ese pid es nuestro servidor de Whisper. Se mira
    antes de mandar una señal: la huella dice que es el mismo proceso que
    escuchaba, esto que ese proceso es el que se quiere parar."""
    try:
        partes = Path(f"/proc/{int(pid)}/cmdline").read_bytes().split(b"\0")
    except OSError:
        return False
    return any(Path(p.decode(errors="replace")).name == "transcribir-servidor.py" for p in partes)


def _esperar_que_muera(huella: dict | None, segundos: float) -> bool:
    import time

    from . import procesos

    limite = time.monotonic() + segundos
    while procesos.vivo(huella):
        if time.monotonic() >= limite:
            return False
        time.sleep(0.05)
    return True


def apagar_servidor(enchufe: Path, espera: float = ESPERA_SERVIDOR_S) -> bool:
    """Apaga el servidor de Whisper de `enchufe` y suelta su memoria (C-0312).

    Devuelve True si había uno y ya no está, False si no había ninguno, y
    lanza `RuntimeError` si no se pudo (dicho, regla 21). Primero se le pide
    con la orden `apagar`, que espera en su cola hasta `espera` (lo que tarda
    una frase: atiende de una en una, y no se corta lo que alguien dicta); si
    no contesta o es uno de antes que no la entiende, SIGTERM al pid que dio
    su socket (`SO_PEERCRED`), comprobado con su huella y con que sea nuestro
    guion: 🔴 por pid y nunca por patrón. Uno que aún carga no tiene socket:
    se le encuentra por la huella de su marca (`whisper.arrancando`, C-0292).
    """
    import os
    import signal

    from . import procesos

    enchufe = Path(enchufe)
    marca = _marca(enchufe)
    quien: dict = {}
    respuesta = pedir(enchufe, {"orden": "apagar"}, espera, quien=quien) if enchufe.exists() else None
    huella = quien.get("huella") if quien.get("uid") == os.getuid() else None
    if huella is None and not quien:
        huella = _huella_de(marca)
    habia = bool(respuesta) or procesos.vivo(huella)
    if respuesta and respuesta.get("ok"):
        apagado = _esperar_que_muera(huella, ESPERA_ORDEN_S) if huella else True
    else:
        apagado = not procesos.vivo(huella)
    if not apagado:
        if not _es_el_guion(huella["pid"]):
            raise RuntimeError(f"lo que escucha en {enchufe.name} (pid {huella['pid']}) no es el servidor "
                               "de Whisper: no se le manda ninguna señal")
        try:
            os.kill(huella["pid"], signal.SIGTERM)
        except ProcessLookupError:
            pass
        except PermissionError as exc:
            raise RuntimeError(f"sin permiso para parar el servidor de Whisper (pid {huella['pid']}): {exc}") from exc
        if not _esperar_que_muera(huella, ESPERA_ORDEN_S):
            raise RuntimeError(f"el servidor de Whisper (pid {huella['pid']}) no se apagó con SIGTERM")
    # Muerto por una señal no borra su socket, y su marca ya no espera a nadie.
    enchufe.unlink(missing_ok=True)
    marca.unlink(missing_ok=True)
    return habia


#: Las últimas líneas que se guardan del registro del servidor de Whisper.
LINEAS_REGISTRO_SERVIDOR = 200


def _abrir_registro_servidor(carpeta: Path):
    """`voz/servidor.log` abierto para añadir, acotado a las últimas líneas.

    Se acota al arrancar —el servidor es de vida corta, se apaga solo por
    ocioso— y así no crece sin fin. Lo que escribe el servidor es su arranque
    y sus errores, nunca lo dictado.
    """
    import os

    ruta = carpeta / "servidor.log"
    try:
        lineas = ruta.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        lineas = []
    if len(lineas) > LINEAS_REGISTRO_SERVIDOR:
        ruta.write_text("\n".join(lineas[-LINEAS_REGISTRO_SERVIDOR:]) + "\n", encoding="utf-8")
    # Sólo para el dueño (600), también uno que viniera de antes.
    os.close(os.open(ruta, os.O_WRONLY | os.O_CREAT, 0o600))
    os.chmod(ruta, 0o600)
    return open(ruta, "a", encoding="utf-8")


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
#: Los formatos que se aceptan; lo demás se guarda como `webm`. Los usa
#: también el banco de dictado (C-0312).
EXTENSIONES = {"webm", "ogg", "m4a", "mp4", "wav", "mp3"}


IDIOMAS = ("es", "en")


def _ajustes() -> dict:
    """Lo declarado en `encargos.yml`: el dictado y `calentar` miran lo mismo."""
    from . import config

    if config.encargos_yml().is_file():
        return config.leer_yaml(config.encargos_yml().read_text(encoding="utf-8")) or {}
    return {}


def dictado(datos: bytes, nombre: str, idioma: str = "es", medidas: dict | None = None) -> str:
    """El texto de lo que se dictó en la web, para la terminal.

    El audio se escribe en `HUB_HOME/voz/` para poder transcribirlo y se borra
    en cuanto sale bien: es la voz de alguien explicando su trabajo, y ya está
    en texto. Si falla se queda diez días (`podar_dictados`, decisión 362), con
    lo que se puede reintentar o mirar qué pasó. Nada sale de la máquina
    (decisión 221).

    `medidas`, si se pasa, se rellena con `camino`, `ms_whisper` y lo que se
    sepa de modelo, dispositivo y duraciones (C-0246), también cuando falla.
    Nunca lleva el texto.
    """
    import time

    from . import config

    if not datos:
        raise ValueError("el audio llegó vacío")
    if idioma not in IDIOMAS:
        raise ValueError(f"idioma no admitido: {idioma}")
    if len(datos) > LIMITE_AUDIO:
        raise ValueError("el audio es demasiado largo para dictar")
    extension = (nombre.rsplit(".", 1)[-1] if "." in nombre else "webm").lower()
    if extension not in EXTENSIONES:
        extension = "webm"
    carpeta = config.HUB_HOME / "voz"
    carpeta.mkdir(parents=True, exist_ok=True)
    ruta = carpeta / f"{time.strftime('%y%m%d-%H%M%S')}-{time.time_ns() % 10**6}.{extension}"
    ruta.write_bytes(datos)
    ajustes = _ajustes()
    python = _python_del_servidor(ajustes)
    if python is None and idioma != "es":
        # Otro transcriptor declarado no sabe de idiomas: transcribiría en el
        # suyo sin decirlo, y en el modo inglés eso es texto inventado.
        ruta.unlink(missing_ok=True)
        raise ValueError("el transcriptor declarado en encargos.yml no sabe cambiar de idioma; "
                         "para el inglés, usa el del hub (scripts/transcribir-whisper.py)")
    medidas = {} if medidas is None else medidas
    t0 = time.perf_counter()
    rapido = None if python is None else _servidor(ruta, python, idioma, medidas)
    if rapido is not None:
        medidas["camino"] = "servidor"
        medidas.setdefault("ms_whisper", round((time.perf_counter() - t0) * 1000))
    else:
        # «declarado»: el comando es del dueño y se respeta; «frio»: nuestro
        # guion, cargando el modelo de cero en cada frase.
        medidas["camino"] = "declarado" if python is None else "frio"
    if rapido is None and idioma != "es":
        ajustes = {**ajustes, "transcripcion": {"comando": comando(ajustes) + ["--idioma", idioma]}}
    if rapido is not None:
        texto = _validar(rapido)
    else:
        t1 = time.perf_counter()
        try:
            texto = transcribir(ruta, ajustes)
        finally:
            medidas["ms_whisper"] = round((time.perf_counter() - t1) * 1000)
        if python is not None:
            medidas.setdefault("dispositivo", "cpu")   # lo que usa nuestro guion
    ruta.unlink(missing_ok=True)
    return texto



#: Quién pidió el dictado: lo manda el cliente y se valida contra esta lista.
ORIGENES = ("secretario", "terminal", "tablero")


def origen_valido(origen: str | None) -> str:
    return origen if origen in ORIGENES else "desconocido"


def linea_de_medidas(medidas: dict) -> str:
    """Una línea `clave=valor` para el journal, sin texto dictado (regla 22).

    Sólo pasa una lista cerrada de claves: lo que no esté aquí no sale, así que
    un campo nuevo con texto no llega al journal por descuido. Del texto vale
    el número de caracteres y nada más.
    """
    claves = ("resultado", "origen", "camino", "modelo", "dispositivo", "ms_total",
              "ms_whisper", "s_audio", "s_voz", "caracteres")
    partes = [f"{k}={medidas.get(k, '-')}" for k in claves]
    return "[voz] " + " ".join(p.replace("\n", " ") for p in partes)


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
        if archivo.suffix.lstrip(".").lower() not in EXTENSIONES or not archivo.is_file():
            continue
        try:
            if archivo.stat().st_mtime < limite:
                archivo.unlink()
                borrados += 1
        except FileNotFoundError:
            pass   # lo borró a la vez un dictado que acabó bien
    return borrados
