"""La puerta del hub: por qué nombres se entra, qué dispositivos pueden, y si la
terminal remota está abierta.

Hasta hoy el hub no tenía puerta y **era correcto que no la tuviera**: escuchaba
sólo en `127.0.0.1`, y el argumento de `web.py` decía que un token no defendería
de nada «porque quien puede ejecutar `curl` en esta máquina ya puede ejecutar
`bash`». Ese argumento deja de valer en cuanto un móvil entra en la red privada:
**el móvil no es la máquina** (decisión 160).

Tres piezas, que van juntas porque empiezan a importar en el mismo instante:

- **`hosts()`** — por qué nombres se acepta entrar. Exactos, jamás un comodín
  (decisión 162).
- **Dispositivos** — cada uno con su nombre, su alta y su último uso. Se dan de
  alta escaneando un QR y se revocan borrando una fila (decisión 161).
- **`terminal_remota`** — interruptor apagado de fábrica que además se apaga
  solo al reiniciar `hub-web` (decisión 163).

🔴 **Dónde vive cada cosa, y por qué no en la base.** La regla dura 1 dice que
todo lo que viva sólo en SQLite tiene que poder reconstruirse escaneando, y un
dispositivo dado de alta no se reconstruye de ningún sitio. Así que la lista vive
en `~/.local/share/hub/acceso.yml`, al lado de `canal.yml` y por el mismo motivo.
El interruptor de la terminal es el caso contrario: **no se persiste a propósito**
—apagarse al reiniciar es la mitad de la decisión 163— así que vive en memoria y
en ningún sitio más.
"""

from __future__ import annotations

import contextlib
import ipaddress
import fcntl
import hashlib
import os
import secrets
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit

import yaml

from . import config
from .reloj import ahora

# Los nombres de casa. Siempre valen y no se pueden quitar: si un `acceso.yml`
# mal escrito dejara al hub sin `localhost`, la forma de arreglarlo sería…
# entrar al hub.
HOSTS_LOCALES = ("127.0.0.1", "localhost", "::1")

# La cookie que dice «este navegador es un dispositivo dado de alta».
COOKIE = "hub_dispositivo"

# Cuánto vive un código de alta sin usarse. Diez minutos es el tiempo de sacar
# el móvil y apuntarle a la pantalla; un código que dura una hora es un código
# que se queda escrito en una captura.
MINUTOS_DE_ALTA = 10

# Cuánto dura la cookie en el navegador. Un año: la caducidad no es la defensa
# —lo es la revocación, que actúa en la petición siguiente— y una caducidad
# corta sólo consigue que haya que volver a dar de alta el móvil en mitad de un
# viaje, que es exactamente cuando no se puede.
DIAS_DE_COOKIE = 365

# Cada cuánto se anota, como mucho, que un aparato sigue entrando. La vista de
# trabajo late cada 5 s: sin esto, un móvil abierto en un bolsillo reescribe el
# archivo que decide quién entra doce veces por minuto durante horas. Un minuto
# de resolución sobra para lo que ese dato sirve —reconocer el aparato que
# sobra al mirar la lista— y recorta a la doceava parte el rato que el archivo
# pasa abriéndose y cerrándose.
SEGUNDOS_ENTRE_MARCAS = 60


class AccesoInvalido(ValueError):
    """El archivo de acceso dice algo que no se puede obedecer."""


# ── El archivo ───────────────────────────────────────────────────────────────

def archivo() -> Path:
    """Dónde vive la puerta. Función y no constante: el instalador lo crea
    después de que el proceso arranque, y una constante evaluada al importar se
    quedaría con la respuesta vieja — el mismo motivo que `config.canal_yml`."""
    declarado = os.environ.get("HUB_ACCESO_YML")
    return Path(declarado) if declarado else config.HUB_HOME / "acceso.yml"


def _leer() -> dict:
    ruta = archivo()
    if not ruta.is_file():
        return {}
    try:
        datos = yaml.safe_load(ruta.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise AccesoInvalido(f"`{ruta}` no es YAML válido: {exc}") from exc
    if not isinstance(datos, dict):
        raise AccesoInvalido(f"`{ruta}` tiene que ser un mapa, no {type(datos).__name__}.")
    # Lo que no es una lista se iteraba y daba un `TypeError`, que ningún
    # `except AccesoInvalido` recoge: con `hosts: 5` la puerta daba 500 en cada
    # petición, también desde casa (C-0504). `hosts` lo mira `hosts()`.
    for clave in ("dispositivos", "pendientes"):
        if datos.get(clave) is not None and not isinstance(datos[clave], list):
            raise AccesoInvalido(f"`{clave}` tiene que ser una lista, y en `{ruta}` no lo es.")
    return datos


def _escribir(datos: dict) -> None:
    """Se escribe entero y de una vez.

    🔴 A un archivo temporal y luego `replace`: es el archivo que decide quién
    entra, y un corte de luz a mitad de escritura lo dejaría truncado. Un
    `acceso.yml` a medias no es «un dispositivo menos», es un `AccesoInvalido`
    en cada petición.

    🔴 **El temporal lleva el pid y el hilo en el nombre** (decisión 184). Con un
    nombre fijo, dos escritores lo abrían y lo truncaban a la vez: uno renombraba
    el archivo mezclado y al otro le explotaba el `os.replace` con
    `FileNotFoundError`. Medido —15 de 15 altas fallidas— y con las dos formas de
    romperse: o un 500 al canjear el QR, o un YAML a medias que deja al hub sin
    la lista de nombres y sin la de aparatos, o sea sin acceso remoto ninguno.
    """
    ruta = archivo()
    ruta.parent.mkdir(parents=True, exist_ok=True)
    temporal = ruta.with_name(f"{ruta.name}.{os.getpid()}.{threading.get_ident()}.nuevo")
    try:
        temporal.write_text(
            yaml.safe_dump(datos, allow_unicode=True, sort_keys=False), encoding="utf-8"
        )
        os.replace(temporal, ruta)
    except BaseException:
        # Un temporal huérfano no rompe nada, pero se acumula y confunde a quien
        # mire la carpeta buscando por qué no entra su móvil.
        with contextlib.suppress(OSError):
            temporal.unlink()
        raise


# ── Un solo escritor cada vez ────────────────────────────────────────────────
#
# 🔴 Todo lo que lee-modifica-escribe este archivo pasa por `_actualizar`, y la
# razón es una medición, no una precaución (decisión 184). Sin esto:
#
#   - dar de alta el portátil mientras el móvil está usando el hub falla
#     **15 de 15 veces**, porque el `marcar_uso` del móvil había leído la lista
#     antes y la reescribe sin el aparato nuevo;
#   - revocar un aparato **mientras lo está usando** se deshace solo, que es
#     exactamente lo que el §8.8 del plan pide comprobar que NO pasa;
#   - y con varias peticiones a la vez la lista de aparatos se queda **vacía**,
#     sin una sola excepción por ningún lado.
#
# Los dos cerrojos hacen falta y no se solapan: el de hilos protege de las
# peticiones simultáneas de `hub-web` —los endpoints síncronos de FastAPI corren
# en un pool—, y el `flock` protege del CLI, que es otro proceso y es justo el
# que se usa para dar de alta el primer aparato.
_ESCRITURA = threading.Lock()


@contextlib.contextmanager
def _en_exclusiva():
    ruta = archivo()
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with _ESCRITURA, open(ruta.with_name(f"{ruta.name}.lock"), "w") as cerrojo:
        fcntl.flock(cerrojo, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(cerrojo, fcntl.LOCK_UN)


def _actualizar(cambio):
    """Lee, aplica `cambio` y escribe, con el archivo cerrado de punta a punta.

    `cambio(datos)` devuelve `(escribir, resultado)`. El `escribir` existe para
    que decidir si hace falta escribir ocurra **dentro** del cerrojo: la marca de
    uso se salta la escritura casi siempre, y mirar el reloj fuera sería otra
    carrera más pequeña haciendo el mismo daño.
    """
    with _en_exclusiva():
        datos = _leer()
        escribir, resultado = cambio(datos)
        if escribir:
            _escribir(datos)
        return resultado


# ── Por qué nombres se entra ─────────────────────────────────────────────────

def hosts(tolerante: bool = False) -> tuple[str, ...]:
    """Los nombres por los que se acepta entrar, locales incluidos.

    `tolerante`: con el archivo mal escrito valen sólo los de casa, en vez de
    lanzar. Es lo que necesitan la puerta, la salud y la pantalla: un archivo
    roto no puede dejar al hub inalcanzable desde casa (C-0504). Lo que lo
    explica y lo arregla es `revisar`.

    🔴 **Un comodín no se acepta, y no se ignora en silencio.** El comentario de
    `web.py` documenta por qué esta lista existe: sin validar el `Host`, los
    nombres de sesión de tmux se enumeran por DNS-rebinding. Un `*` reabriría
    justo el agujero que la lista cerró, así que se levanta y se dice — dejar
    entrar con un aviso en el registro es lo mismo que dejar entrar.
    """
    if tolerante:
        try:
            return hosts()
        except AccesoInvalido:
            return HOSTS_LOCALES
    declarados = _leer().get("hosts") or []
    if not isinstance(declarados, (str, list, tuple, dict)):
        raise AccesoInvalido(f"`hosts` tiene que ser una lista de nombres, y es «{declarados}».")
    if isinstance(declarados, str):
        # Igual que las `rutas` de un proyecto: Python iteraría la CADENA letra a
        # letra y la lista quedaría llena de nombres de un carácter.
        raise AccesoInvalido(
            "`hosts` es una lista, aunque sólo haya un nombre:\n\n"
            f"    hosts:\n      - {declarados}"
        )
    fuera = []
    for nombre in declarados:
        texto = str(nombre).strip().lower()
        if not texto:
            continue
        if "*" in texto or "?" in texto:
            # Decisión 162. El número no va en el mensaje: quien lo lee no tiene
            # ARQUITECTURA.md, que no se publica.
            raise AccesoInvalido(
                f"«{texto}» lleva un comodín, y aquí no se admiten: "
                "sin validar el `Host` los nombres de sesión se enumeran por "
                "DNS-rebinding. Escribe el nombre exacto de la máquina en la red "
                "privada."
            )
        fuera.append(texto)
    return (*HOSTS_LOCALES, *fuera)


# ── Lo que dice el archivo, y su arreglo (C-0504) ────────────────────────────
#
# Quien instala el hub no tiene por qué editar YAML ni escribir comandos: la
# pantalla dice qué está mal, propone cómo queda y lo reescribe con un botón.
# Una entrada que nunca puede casar con un `Host` —con esquema, ruta o
# puerto— o que no sirve para un QR por https —una IP— se SEÑALA y no se usa,
# en vez de lanzar: lanzar apagaría también los nombres buenos del archivo, y
# quien estuviera de viaje se quedaría fuera tras actualizar.

def _es_ip(texto: str) -> bool:
    try:
        ipaddress.ip_address(texto.strip("[]"))
    except ValueError:
        return False
    return True


def _por_que_no_sirve(nombre: str) -> str:
    """Por qué una entrada de `hosts` no sirve para entrar desde fuera, o «»."""
    if _es_ip(nombre):
        return ("es una dirección IP: desde fuera se entra por el nombre de la máquina "
                "en la red privada, que es el que lleva el certificado de https. "
                "No se usa para el QR.")
    if "://" in nombre or "/" in nombre:
        return ("lleva el esquema o una ruta, y el hub compara sólo el nombre: así no "
                "deja entrar a nadie.")
    if ":" in nombre:
        return "lleva el puerto, y el hub compara sólo el nombre: así no deja entrar a nadie."
    return ""


def _limpiar_nombre(crudo) -> str:
    """El nombre que quería decir una entrada: sin esquema, ruta ni puerto."""
    texto = str(crudo or "").strip().lower()
    if "://" in texto:
        texto = texto.split("://", 1)[1]
    texto = texto.split("/", 1)[0]
    if not _es_ip(texto):
        texto = texto.rsplit(":", 1)[0] if ":" in texto else texto
    return texto.strip().rstrip(".")


def _validar_nombre(nombre: str) -> str:
    """Un nombre de la red privada que se puede guardar, o `AccesoInvalido`."""
    texto = str(nombre or "").strip().lower().rstrip(".")
    if not texto:
        raise AccesoInvalido("falta el nombre de la máquina en la red privada")
    if "*" in texto or "?" in texto:
        raise AccesoInvalido("un nombre con comodín no se admite: tiene que ser el exacto")
    if texto in HOSTS_LOCALES:
        raise AccesoInvalido(f"«{texto}» es de casa: ése vale siempre y no hace falta guardarlo")
    motivo = _por_que_no_sirve(texto)
    if motivo:
        raise AccesoInvalido(f"«{texto}» {motivo}")
    if not all(c.isalnum() or c in "-." for c in texto) or texto.startswith(("-", ".")):
        raise AccesoInvalido(f"«{texto}» no parece un nombre de máquina (letras, números, «-» y «.»)")
    return texto


def utilizables(nombres: tuple[str, ...]) -> list[str]:
    """Los nombres de fuera que sirven para armar un QR."""
    return [h for h in nombres if h not in HOSTS_LOCALES and not _por_que_no_sirve(h)]


def destino_de_alta(host: str | None, de_casa: bool, puerto: int | None = None) -> str | None:
    """Por qué nombre va a entrar el aparato que se da de alta, o None si no hay
    ninguno y entonces no se pinta QR (C-0504).

    Desde casa, el primer nombre utilizable de la red privada (decisión 185),
    con `puerto` si `tailscale serve` publica el hub en uno que no es el 443:
    el nombre de la petición sería `127.0.0.1`, un QR válido que ningún móvil
    abre. Desde un aparato que ya entró, el nombre por el que entró. Lo usan
    la pantalla y el CLI del alta."""
    if not de_casa:
        return (host or "").strip() or None
    remotos = utilizables(hosts(tolerante=True))
    if not remotos:
        return None
    return f"{remotos[0]}:{puerto}" if puerto and puerto != 443 else remotos[0]


def _texto_crudo() -> str | None:
    ruta = archivo()
    try:
        return ruta.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None


def _huella_de(texto: str | None) -> str:
    return hashlib.sha256((texto or "").encode("utf-8")).hexdigest()[:16]


def _propuesta(texto: str | None) -> dict | None:
    """Cómo quedaría bien escrito el archivo cuyo texto es `texto`, o None si
    ya lo está. `datos` es lo que se escribiría; `cambios`, qué se hace, en
    frases; `pierde_aparatos`, si los dados de alta tendrán que volver a
    darse de alta (sólo cuando el archivo no se puede leer)."""
    if texto is None:
        return None
    cambios: list[str] = []
    pierde = False
    try:
        crudo = yaml.safe_load(texto)
    except yaml.YAMLError:
        crudo, pierde = None, True
        cambios.append("No se puede leer (no es YAML): se empieza uno nuevo, sin nombres de fuera.")
    if crudo is None and not pierde:
        crudo = {}
    if isinstance(crudo, list):
        cambios.append("Empezaba por una lista: sus nombres pasan a «hosts».")
        crudo = {"hosts": crudo}
    elif isinstance(crudo, str) and not pierde:
        cambios.append("Era sólo un texto: pasa a ser un nombre de «hosts».")
        crudo = {"hosts": [crudo]}
    elif not isinstance(crudo, dict):
        if not pierde:
            cambios.append("No era un mapa: se empieza uno nuevo, sin nombres de fuera.")
        crudo = {}
    datos = dict(crudo)
    declarados = datos.get("hosts")
    if declarados is None:
        declarados = []
    elif isinstance(declarados, str):
        cambios.append("«hosts» era un texto suelto: pasa a ser una lista.")
        declarados = [declarados]
    elif isinstance(declarados, dict):
        cambios.append("«hosts» era un mapa: sus nombres pasan a ser una lista.")
        declarados = list(declarados)
    elif not isinstance(declarados, list):
        cambios.append("«hosts» no era una lista: se vacía.")
        declarados = []
    nuevos: list[str] = []
    for entrada in declarados:
        original = str(entrada or "").strip().lower()
        if not original:
            continue
        if "*" in original or "?" in original:
            cambios.append(f"«{original}» lleva un comodín, que no se admite: se quita.")
            continue
        limpio = _limpiar_nombre(original)
        if limpio != original:
            cambios.append(f"«{original}» pasa a «{limpio}»: el hub compara sólo el nombre.")
        if not limpio or limpio in HOSTS_LOCALES:
            if limpio in HOSTS_LOCALES:
                cambios.append(f"«{limpio}» es de casa y vale siempre: se quita de la lista.")
            continue
        if limpio not in nuevos:
            nuevos.append(limpio)
    datos["hosts"] = nuevos
    for clave in ("dispositivos", "pendientes"):
        if datos.get(clave) is not None and not isinstance(datos[clave], list):
            cambios.append(f"«{clave}» no era una lista: se vacía.")
            pierde = pierde or clave == "dispositivos"
            datos[clave] = []
    if not cambios:
        return None
    return {"datos": datos, "cambios": cambios, "pierde_aparatos": pierde, "hosts": nuevos}


def revisar() -> dict:
    """Lo que dice `acceso.yml`, para la pantalla: los nombres que valen, los
    que no sirven y por qué, el error si no se puede obedecer y su arreglo.

    Nunca lanza. `huella` identifica el texto que se revisó: `arreglar` sólo
    escribe si el archivo sigue siendo ése."""
    texto = _texto_crudo()
    error = None
    try:
        nombres = hosts()
        dispositivos()
    except AccesoInvalido as exc:
        nombres, error = HOSTS_LOCALES, str(exc)
    avisos = [{"nombre": h, "motivo": m} for h in nombres
              if h not in HOSTS_LOCALES and (m := _por_que_no_sirve(h))]
    propuesta = _propuesta(texto)
    return {
        "hosts": nombres, "utilizables": utilizables(nombres), "avisos": avisos,
        "error": error, "huella": _huella_de(texto),
        "arreglo": None if propuesta is None else {
            "cambios": propuesta["cambios"], "hosts": propuesta["hosts"],
            "pierde_aparatos": propuesta["pierde_aparatos"]},
    }


def arreglar(huella: str) -> Path:
    """Reescribe bien el archivo y devuelve dónde quedó el anterior.

    🔴 Sólo si sigue siendo el que se enseñó (`huella`): entre mirar el arreglo
    y pulsarlo otro pudo cambiarlo, y reescribir encima perdería lo suyo.
    Con el cerrojo de siempre pero sin `_actualizar`, que lee con `_leer` y
    lanzaría justo con el archivo que se quiere arreglar. El anterior se
    guarda entero (`acceso.yml.roto-<fecha>-<hora>`, 600): lleva los aparatos."""
    with _en_exclusiva():
        texto = _texto_crudo()
        if not secrets.compare_digest(_huella_de(texto), str(huella or "")):
            raise AccesoInvalido("el archivo de acceso cambió mientras lo mirabas: "
                                 "vuelve a mirar el arreglo antes de aplicarlo")
        propuesta = _propuesta(texto)
        if propuesta is None:
            raise AccesoInvalido("el archivo de acceso ya está bien escrito: no hay nada que arreglar")
        ruta = archivo()
        copia = ruta.with_name(f"{ruta.name}.roto-{datetime.now().strftime('%Y%m%d-%H%M%S')}")
        try:
            fd = os.open(copia, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError as exc:
            raise AccesoInvalido("se acaba de arreglar hace un instante: recarga y mira cómo quedó") from exc
        with os.fdopen(fd, "w", encoding="utf-8") as salida:
            salida.write(texto or "")
        _escribir(propuesta["datos"])
    return copia


def poner_nombre(nombre: str) -> str:
    """Guarda en `hosts` el nombre de esta máquina en la red privada y lo
    devuelve como quedó (C-0504). Exacto: sin comodín, esquema, puerto ni IP
    (`AccesoInvalido` si no). Conserva los aparatos y las altas, y un `hosts`
    escrito como texto suelto pasa a ser lista. Con el archivo ilegible lanza:
    primero se arregla (`arreglar`)."""
    limpio = _validar_nombre(nombre)

    def cambio(datos: dict):
        actuales = datos.get("hosts")
        lista = [actuales] if isinstance(actuales, str) else list(actuales or []) \
            if isinstance(actuales, (list, dict)) else []
        if any("*" in str(h) or "?" in str(h) for h in lista):
            # Guardarlo diría «listo» con un archivo que la puerta sigue sin
            # obedecer: primero se arregla.
            raise AccesoInvalido("el archivo de acceso tiene un nombre con comodín: arréglalo antes "
                                 "(«Arreglarlo» en Acceso, o `python -m hub.acceso arreglar`)")
        if limpio in (str(h).strip().lower() for h in lista):
            if lista == actuales:
                return False, limpio
        else:
            lista.append(limpio)
        datos["hosts"] = lista
        return True, limpio

    return _actualizar(cambio)


def partes_de_host(host: str | None) -> tuple[str, str | None]:
    """El nombre de una cabecera `Host` —sin corchetes y en minúscula— y lo que
    lleva detrás como puerto, en texto y sin validar (`None` si no lleva).

    El único sitio que la parte (C-0118): la puerta del `Host` y la comparación
    del `Origin` la leen igual (C-0187; antes el `Origin` la partía con
    `urlsplit` por su cuenta). Una dirección IPv6 va entre corchetes y lleva `:`
    dentro: partir por el último `:` a secas convertía `[::1]` en «:», un
    nombre de casa que no contaba como de casa.
    """
    host = (host or "").strip().lower()
    if host.startswith("["):
        nombre, _, resto = host[1:].partition("]")
        if not resto:
            return nombre, None
        # Tras el corchete sólo cabe `:<puerto>`; lo demás se devuelve tal cual
        # para que quien valide el puerto lo rechace.
        return nombre, resto[1:] if resto.startswith(":") else resto
    if ":" in host:
        nombre, _, puerto = host.rpartition(":")
        return nombre, puerto
    return host, None


def nombre_de_host(host: str | None) -> str:
    """El nombre de una cabecera `Host`, sin puerto, sin corchetes y en minúscula
    (`partes_de_host`)."""
    return partes_de_host(host)[0]


def es_host_local(host: str | None) -> bool:
    """¿El nombre por el que se ha entrado es uno de casa?

    Un `Host` ausente cuenta como local: lo mandan `curl` y el CLI del
    asistente, que no son navegadores.
    """
    return host_permitido(host, HOSTS_LOCALES)


def es_cliente_local(ip: str | None, admitidos: tuple[str, ...] = ()) -> bool:
    """¿La conexión viene de esta máquina? Loopback de IPv4 o IPv6 (también
    `::ffff:127.0.0.1`). Sin dirección, no: aquí no se presume a favor."""
    if not ip:
        return False
    if ip in admitidos:
        return True
    try:
        direccion = ipaddress.ip_address(ip)
    except ValueError:
        return False
    if getattr(direccion, "ipv4_mapped", None):
        direccion = direccion.ipv4_mapped
    return direccion.is_loopback


def host_permitido(host: str | None, permitidos: tuple[str, ...] | None = None) -> bool:
    """Si el nombre por el que se entró está en la lista (`hosts()` si no se da
    otra). La puerta de `web` la llama con la suya, que suma la del arnés de
    pruebas. Un `Host` ausente pasa: no lo manda un navegador (ver
    `es_host_local`); el WebSocket de la terminal lo trata aparte."""
    if not host:
        return True
    return nombre_de_host(host) in (hosts() if permitidos is None else permitidos)


_PUERTO_DE = {"http": 80, "https": 443}


def _puerto(esquema: str, puerto: int | None) -> int | None:
    return puerto if puerto is not None else _PUERTO_DE.get(esquema)


def origen_permitido(origen: str | None, host: str | None = None,
                     nombres: tuple[str, ...] | None = None) -> bool:
    """Sin `Origin` se pasa; con un `Origin` ajeno, no.

    Ausente significa que no lo mandó un navegador: `curl`, el `bin/hub` del
    asistente o un script. Lo que se cierra es el caso en que un navegador dice
    de dónde viene y no es de aquí.

    🔴 El puerto no se compara contra `config.WEB_PORT`: la primera versión lo
    hacía y rechazaba al origen legítimo en cuanto uvicorn arrancaba en otro
    puerto sin exportar `HUB_PORT`. **Se compara contra el `Host` de la propia
    petición** (C-0153): para un nombre de casa, el `Origin` tiene que llevar
    el mismo puerto al que el navegador se conectó. Sin eso, cualquier página
    servida en `http://127.0.0.1:<otro puerto>` —la app de un encargo, el
    servidor de desarrollo de cualquier proyecto— pasaba por «de aquí» y abría
    la terminal, donde desde casa no se pide nada más. Los nombres de la red
    privada siguen comparándose sólo por nombre: llegan por `tailscale serve`,
    que no escucha en otros puertos de ese nombre.

    `nombres` sustituye a `hosts()`: quien ya sabe que el archivo está roto
    pasa los de casa (C-0504).
    """
    if origen is None:
        return True
    partes = urlsplit(origen)
    nombre = partes.hostname or ""
    if partes.scheme not in ("http", "https") or nombre not in (hosts() if nombres is None else nombres):
        return False
    if nombre not in HOSTS_LOCALES or host is None:
        return True
    try:
        puerto_origen = _puerto(partes.scheme, partes.port)
    except ValueError:
        return False
    nombre_host, puerto_texto = partes_de_host(host)
    if not puerto_texto:
        puerto_host = _PUERTO_DE[partes.scheme]
    elif puerto_texto.isascii() and puerto_texto.isdigit() and int(puerto_texto) <= 65535:
        puerto_host = int(puerto_texto)
    else:
        # Un puerto que no es un puerto: se cierra, como cerraba `urlsplit`.
        return False
    # Una página de casa sólo habla con el hub por casa: la misma página de
    # 127.0.0.1:5000 pidiendo al nombre de la red privada tampoco es el hub.
    return nombre_host in HOSTS_LOCALES and puerto_origen == puerto_host


# ── Que la red privada lleve al hub, con Claude (C-0504) ────────────────────
#
# 🔴 El hub no ejecuta `tailscale serve` por su cuenta: la primera vez puede
# pedir activar serve o https en la consola de Tailscale, con un enlace que
# sólo abre una persona, y que el proceso que da una shell cambie lo que la
# máquina deja ver a la red es superficie nueva. Lo hace la persona, con una
# ventana que deja escrito el encargo SIN Enter (tercer caso de la regla dura
# 15, decisión 164), y Claude le pide permiso a cada orden.

def encargo_red() -> str:
    puerto = config.WEB_PORT
    return (
        "Prepara esta máquina para entrar al hub desde otros aparatos, por la red privada de "
        "Tailscale. Desde WSL, Tailscale es el de Windows (tailscale.exe); si no, tailscale. "
        "1) Mira si está instalado y conectado (tailscale status). Si no lo está o no ha "
        "iniciado sesión, dime qué hacer y espera a que lo haga yo. "
        f"2) Publica el hub en la red privada con tailscale serve --bg http://127.0.0.1:{puerto} "
        "y compruébalo con tailscale serve status. Si pide activar serve o https en la consola "
        "de Tailscale, dame el enlace y espera a que lo haga yo. "
        "3) Guarda el nombre de esta máquina en la red privada (el DNSName de tailscale status "
        "--json, sin el punto final) con uv run python -m hub.acceso nombre <ese nombre>; si "
        "dice que el archivo de acceso está mal escrito, antes uv run python -m hub.acceso "
        "arreglar. No edites acceso.yml a mano ni ningún archivo de esta carpeta. "
        "🔴 Nunca tailscale funnel, nunca escuchar en 0.0.0.0, abrir el puerto ni tocar el "
        f"cortafuegos, y nunca un enlace con la IP de Tailscale al {puerto}: el hub escucha sólo "
        "en 127.0.0.1 a propósito, porque su terminal da una shell. Pide permiso antes de cada "
        "orden. Al terminar dime que vuelva a la pantalla Acceso del hub y pulse «Generar el QR»."
    )


def preparar_red() -> dict:
    """La ventana en la carpeta del hub con `encargo_red()` escrito y sin Enter."""
    from . import agentes, slots, tmux

    pane_id = slots.abrir_en(str(config.RAIZ_REPO), "preparar-acceso", "hub",
                             agentes.comando(encargo_red()))
    indice = next((p["window_idx"] for p in tmux.listar_paneles() if p["pane_id"] == pane_id), None)
    return {"session": "hub", "ventana": indice}


# ── Dispositivos ─────────────────────────────────────────────────────────────
#
# 🔴 El archivo guarda el HASH del testigo, nunca el testigo. La decisión 161
# hablaba de «una cookie firmada», y firmar exigiría una clave que hay que
# guardar en algún sitio —un secreto más, contra el espíritu de la regla dura
# 5— y además **no sería revocable**: una firma válida lo es para siempre, y el
# §8 del plan pide que revocar surta efecto *en la petición siguiente*. Un
# testigo aleatorio de 256 bits con su hash en disco cumple las dos cosas y no
# guarda ningún secreto: quien lea `acceso.yml` no puede entrar con lo que hay
# dentro.

def _hash(testigo: str) -> str:
    return hashlib.sha256(testigo.encode("utf-8")).hexdigest()


def _dispositivos_de(datos: dict) -> list[dict]:
    """La lista tal y como está en unos datos ya leídos.

    Existe para que quien escribe use **la misma lectura** que va a reescribir:
    volver a leer el archivo a mitad de un cambio es cómo se pierde el aparato
    que otro acababa de dar de alta.
    """
    lista = datos.get("dispositivos") or []
    return [d for d in lista if isinstance(d, dict) and d.get("hash")]


def dispositivos() -> list[dict]:
    return _dispositivos_de(_leer())


def alta_pendiente(nombre: str) -> str:
    """Crea un código de un solo uso y devuelve el código.

    El código no es el testigo: es un vale para canjearlo. Vive en el archivo con
    su caducidad porque el alta la empieza una pantalla y la termina otro
    dispositivo — si viviera en memoria, reiniciar `hub-web` entre las dos
    mitades dejaría el QR de la pantalla apuntando a nada.
    """
    codigo = secrets.token_urlsafe(16)

    def cambio(datos: dict):
        vivos = [p for p in (datos.get("pendientes") or []) if not _caducado(p)]
        vivos.append({
            "codigo": codigo,
            "nombre": nombre.strip() or "Sin nombre",
            "caduca": (datetime.now(timezone.utc)
                       + timedelta(minutes=MINUTOS_DE_ALTA)).isoformat(),
        })
        datos["pendientes"] = vivos
        return True, codigo

    return _actualizar(cambio)


def _caducado(pendiente: dict) -> bool:
    try:
        return datetime.fromisoformat(str(pendiente.get("caduca"))) < datetime.now(timezone.utc)
    except (TypeError, ValueError):
        return True  # sin fecha legible se descarta: un vale sin caducidad no caduca nunca


def pendientes() -> list[dict]:
    return [p for p in (_leer().get("pendientes") or []) if not _caducado(p)]


def canjear(codigo: str) -> str | None:
    """Convierte un código en un dispositivo y devuelve su testigo, una sola vez.

    Devuelve `None` si el código no existe, ya se usó o caducó. Los tres casos se
    responden igual a propósito: distinguirlos le diría a quien prueba códigos
    cuáles existieron.
    """
    def cambio(datos: dict):
        vivos = [p for p in (datos.get("pendientes") or []) if not _caducado(p)]
        elegido = next((p for p in vivos
                        if secrets.compare_digest(str(p.get("codigo", "")), codigo)), None)
        if not elegido:
            return False, None

        testigo = secrets.token_urlsafe(32)
        lista = _dispositivos_de(datos)
        lista.append({
            "id": secrets.token_hex(8),
            "nombre": elegido["nombre"],
            "hash": _hash(testigo),
            "alta": ahora(),
            "ultimo_uso": None,
        })
        datos["dispositivos"] = lista
        datos["pendientes"] = [p for p in vivos if p is not elegido]
        return True, testigo

    return _actualizar(cambio)


def reconocer(testigo: str | None) -> dict | None:
    """El dispositivo al que pertenece este testigo, o `None`.

    Se lee el archivo en CADA petición y no se cachea: revocar tiene que surtir
    efecto en la petición siguiente, no en la próxima caducidad ni cuando expire
    una caché. El archivo son unos KB y está en la caché del sistema.
    """
    if not testigo:
        return None
    buscado = _hash(testigo)
    try:
        lista = dispositivos()
    except AccesoInvalido:
        # Con el archivo roto no se sabe quién está dado de alta: se cierra.
        return None
    for d in lista:
        if secrets.compare_digest(str(d.get("hash", "")), buscado):
            return d
    return None


def marcar_uso(dispositivo_id: str) -> None:
    """Deja constancia de cuándo se usó, para poder reconocer el que sobra.

    Se traga sus errores: es información, no permiso. Que falle una escritura no
    puede tumbar una petición que ya está autorizada.

    Sólo escribe si la última marca tiene más de `SEGUNDOS_ENTRE_MARCAS`. Se
    decide dentro del cerrojo a propósito: es una lectura y una escritura del
    mismo archivo, o sea la misma carrera que todo lo demás de aquí, y saltársela
    fuera sería dejar abierta una versión pequeña del agujero grande.
    """
    def cambio(datos: dict):
        ahora = datetime.now(timezone.utc)
        for d in _dispositivos_de(datos):
            if d.get("id") != dispositivo_id:
                continue
            try:
                ultimo = datetime.fromisoformat(str(d.get("ultimo_uso")))
            except (TypeError, ValueError):
                ultimo = None
            if ultimo and (ahora - ultimo).total_seconds() < SEGUNDOS_ENTRE_MARCAS:
                return False, None
            d["ultimo_uso"] = ahora.isoformat()
            return True, None
        return False, None

    try:
        _actualizar(cambio)
    except (OSError, AccesoInvalido):
        pass


def revocar(dispositivo_id: str) -> bool:
    def cambio(datos: dict):
        lista = _dispositivos_de(datos)
        quedan = [d for d in lista if d.get("id") != dispositivo_id]
        if len(quedan) == len(lista):
            return False, False
        datos["dispositivos"] = quedan
        return True, True

    return _actualizar(cambio)


# ── El interruptor de la terminal ────────────────────────────────────────────
#
# 🔴 En memoria y en ningún sitio más. Que se apague al reiniciar `hub-web` no
# es comodidad al revés: convierte «abrir la terminal remota» en una decisión
# consciente cada vez, en lugar de una puerta que lleva meses abierta porque un
# día se abrió (decisión 163). Persistirlo sería derogar la mitad de la decisión.
_terminal_remota = False
_cerrojo = threading.Lock()


def terminal_remota() -> bool:
    return _terminal_remota


def abrir_terminal_remota(abierta: bool) -> bool:
    global _terminal_remota
    with _cerrojo:
        _terminal_remota = bool(abierta)
    return _terminal_remota


# ── El QR ────────────────────────────────────────────────────────────────────

def qr_svg(texto: str, escala: int = 6) -> str:
    """El QR del alta, como SVG en línea.

    En línea y no un archivo: la UI no debe depender de nada externo y así el
    QR no es una petición más que puede fallar justo cuando hace falta.

    🔴 **Negro literal, y es la excepción a «nunca colores literales».** La
    primera versión pasaba `currentColor` para heredar el tono del tema: segno
    lo rechaza —no es un color web ni un hexadecimal— y la pantalla daba un 500.
    Pero aunque lo aceptara estaría mal: un QR tiene que ser oscuro sobre claro
    para que lo lea una cámara, y con el tema oscuro habría salido un código
    ilegible sin ningún error. Por eso la tarjeta que lo envuelve también es
    blanca a propósito.
    """
    import segno

    return segno.make(texto, error="m").svg_inline(scale=escala, dark="#000")


def qr_terminal(texto: str) -> str:
    """El mismo QR en caracteres, para escanearlo desde una terminal.

    Es cómo se da de alta el PRIMER dispositivo: desde `tmux`, sin navegador y
    sin haber entrado todavía a ningún sitio.
    """
    import io

    import segno

    salida = io.StringIO()
    segno.make(texto, error="m").terminal(out=salida, compact=True)
    return salida.getvalue()


# ── El primer aparato se da de alta desde aquí ───────────────────────────────

def _cli(argv: list[str] | None = None) -> int:
    """`python -m hub.acceso alta "Móvil"` — el alta del PRIMER dispositivo.

    🔴 Existe porque hay un huevo y una gallina: para dar de alta un aparato
    desde la web hay que poder entrar a la web, y desde fuera de casa no se
    puede entrar sin un aparato dado de alta. Esto lo rompe por el único sitio
    donde se puede romper sin abrir un agujero: **una shell en la máquina**.
    Quien la tiene ya puede ejecutar `bash`, así que no se le está concediendo
    nada que no tuviera — es exactamente el argumento que `web.py` lleva
    documentado desde el principio, usado donde sí vale.

    Imprime el QR en caracteres para poder escanearlo desde `tmux`, sin
    navegador y sin haber entrado todavía a ningún sitio.
    """
    import argparse

    partes = argparse.ArgumentParser(prog="python -m hub.acceso",
                                     description="La puerta del hub.")
    orden = partes.add_subparsers(dest="orden", required=True)
    alta = orden.add_parser("alta", help="da de alta un aparato y enseña su QR")
    alta.add_argument("nombre", help="para reconocerlo después: «Móvil», «Portátil del viaje»")
    alta.add_argument("--host", help="por qué nombre lo va a abrir el aparato "
                                     "(por defecto, el primero de la red privada)")
    orden.add_parser("listar", help="qué aparatos pueden entrar")
    poner = orden.add_parser("nombre", help="guarda el nombre de esta máquina en la red privada")
    poner.add_argument("nombre", help="el exacto, p. ej. maquina.tu-red.ts.net")
    orden.add_parser("arreglar", help="reescribe bien un acceso.yml mal escrito (guarda el anterior)")
    quitar = orden.add_parser("quitar", help="revoca un aparato por su id")
    quitar.add_argument("id")
    args = partes.parse_args(argv)

    if args.orden == "listar":
        lista = dispositivos()
        if not lista:
            print("Ningún aparato dado de alta.")
            return 0
        for d in lista:
            print(f"  {d.get('id')}  {d.get('nombre')}"
                  f"   alta {str(d.get('alta'))[:10]}"
                  f"   {'visto ' + str(d.get('ultimo_uso'))[:16] if d.get('ultimo_uso') else 'sin usar'}")
        return 0

    # `nombre` y `arreglar` existen para que Claude, desde «Preparar con
    # Claude», escriba el archivo por la misma puerta que los botones, con su
    # cerrojo, y no a mano (C-0504).
    if args.orden == "nombre":
        try:
            print(f"Guardado: {poner_nombre(args.nombre)}. Ya se puede generar el QR en Acceso.")
        except AccesoInvalido as exc:
            print(f"No se guardó: {exc}")
            return 1
        return 0

    if args.orden == "arreglar":
        estado = revisar()
        if not estado["arreglo"]:
            print("El archivo de acceso ya está bien escrito.")
            return 0
        for linea in estado["arreglo"]["cambios"]:
            print(f"  - {linea}")
        try:
            copia = arreglar(estado["huella"])
        except AccesoInvalido as exc:
            print(f"No se arregló: {exc}")
            return 1
        print(f"Arreglado. El anterior quedó en {copia}.")
        return 0

    if args.orden == "quitar":
        print("Quitado." if revocar(args.id) else "No hay ningún aparato con ese id.")
        return 0

    # `alta`. El nombre por el que el aparato va a abrir el hub no se puede
    # adivinar desde aquí: `127.0.0.1` haría un QR que sólo funciona en la
    # máquina que ya está dentro, que es justo el aparato que no hace falta dar
    # de alta.
    destino = args.host or destino_de_alta(None, de_casa=True)
    if not destino:
        print(
            "No sé por qué nombre va a entrar ese aparato.\n\n"
            "En la pantalla Acceso del hub, «Usar este nombre» guarda el de esta máquina\n"
            "en la red privada; desde aquí, `python -m hub.acceso nombre <el nombre>`,\n"
            "o pásalo con --host.\n"
        )
        return 1

    codigo = alta_pendiente(args.nombre)
    enlace = f"https://{destino}/acceso/alta/{codigo}"
    # El enlace, además del QR: el aparato a dar de alta puede ser la propia PC
    # desde la que se llega por SSH a una máquina sin monitor (C-0214).
    print(f"\n  {args.nombre} — escanéalo, o abre el enlace de abajo en ese aparato, "
          f"en los próximos {MINUTOS_DE_ALTA} minutos.\n")
    print(qr_terminal(enlace))
    print(f"  {enlace}\n")
    print("  Sirve una sola vez. Si caduca, vuelve a lanzar esto.\n")
    return 0


if __name__ == "__main__":  # pragma: no cover - punto de entrada
    raise SystemExit(_cli())
