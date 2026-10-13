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


def _ahora() -> str:
    return datetime.now(timezone.utc).isoformat()


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

def hosts() -> tuple[str, ...]:
    """Los nombres por los que se acepta entrar, locales incluidos.

    🔴 **Un comodín no se acepta, y no se ignora en silencio.** El comentario de
    `web.py` documenta por qué esta lista existe: sin validar el `Host`, los
    nombres de sesión de tmux se enumeran por DNS-rebinding. Un `*` reabriría
    justo el agujero que la lista cerró, así que se levanta y se dice — dejar
    entrar con un aviso en el registro es lo mismo que dejar entrar.
    """
    declarados = _leer().get("hosts") or []
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
            raise AccesoInvalido(
                f"«{texto}» lleva un comodín, y aquí no se admiten (decisión 162): "
                "sin validar el `Host` los nombres de sesión se enumeran por "
                "DNS-rebinding. Escribe el nombre exacto de la máquina en la red "
                "privada."
            )
        fuera.append(texto)
    return (*HOSTS_LOCALES, *fuera)


def es_host_local(host: str | None) -> bool:
    """¿El nombre por el que se ha entrado es uno de casa?

    Se parte por `:` para quitar el puerto. Un `Host` ausente cuenta como local:
    lo mandan `curl` y el CLI del asistente, que no son navegadores.
    """
    if not host:
        return True
    nombre = host.rsplit(":", 1)[0].strip("[]").lower() if ":" in host else host.lower()
    return nombre in HOSTS_LOCALES


def host_permitido(host: str | None) -> bool:
    if not host:
        return True
    nombre = host.rsplit(":", 1)[0].strip("[]").lower() if ":" in host else host.lower()
    return nombre in hosts()


def origen_permitido(origen: str | None) -> bool:
    """Sin `Origin` se pasa; con un `Origin` ajeno, no.

    Ausente significa que no lo mandó un navegador: `curl`, el `bin/hub` del
    asistente o un script. Lo que se cierra es el caso en que un navegador dice
    de dónde viene y no es de aquí.

    🔴 Se compara el HOSTNAME y no la URL entera con su puerto. La primera
    versión montaba la lista con `config.WEB_PORT` y rechazaba al origen
    legítimo en cuanto uvicorn arrancaba en otro puerto sin exportar `HUB_PORT`.
    """
    if origen is None:
        return True
    partes = urlsplit(origen)
    return partes.scheme in ("http", "https") and (partes.hostname or "") in hosts()


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
            "alta": _ahora(),
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
    for d in dispositivos():
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

    if args.orden == "quitar":
        print("Quitado." if revocar(args.id) else "No hay ningún aparato con ese id.")
        return 0

    # `alta`. El nombre por el que el aparato va a abrir el hub no se puede
    # adivinar desde aquí: `127.0.0.1` haría un QR que sólo funciona en la
    # máquina que ya está dentro, que es justo el aparato que no hace falta dar
    # de alta.
    remotos = [h for h in hosts() if h not in HOSTS_LOCALES]
    destino = args.host or (remotos[0] if remotos else None)
    if not destino:
        print(
            f"No sé por qué nombre va a entrar ese aparato.\n\n"
            f"Añade el nombre de esta máquina en la red privada a la lista `hosts`\n"
            f"de {archivo()}, o pásalo con --host.\n"
        )
        return 1

    codigo = alta_pendiente(args.nombre)
    enlace = f"https://{destino}/acceso/alta/{codigo}"
    print(f"\n  {args.nombre} — escanéalo en los próximos {MINUTOS_DE_ALTA} minutos.\n")
    print(qr_terminal(enlace))
    print(f"  {enlace}\n")
    print("  Sirve una sola vez. Si caduca, vuelve a lanzar esto.\n")
    return 0


if __name__ == "__main__":  # pragma: no cover - punto de entrada
    raise SystemExit(_cli())
