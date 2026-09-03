"""Cliente de la Bot API. Lo único de este canal que toca la red.

Aislado en su propio módulo para que el dominio (`canal.py`) se pueda probar
entero sin internet, y para que el sitio donde se lee el token sea **uno solo** y
se pueda mirar de un vistazo.

🔴 **El token no se guarda en la base ni en el código** (regla dura 5). Vive en un
archivo con permisos propios y el hub sólo conoce un puntero, igual que las
conexiones a VPS. Y hay un matiz que no conviene perder: hasta ahora el hub
*nunca* leía un puntero —de `conexiones.py` sólo comprueba que exista—. Aquí sí
se lee, y por eso el relé corre como un servicio **aparte** de `hub-web`: el
proceso que expone el puerto (y con él una shell, regla dura 8) nunca ve el
token.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://api.telegram.org"

# Cuánto aguanta abierta una llamada a getUpdates. El long polling es lo que
# hace que esto no sea un bucle de sondeo: la conexión se queda esperando y
# Telegram contesta cuando hay algo.
ESPERA_LARGA = 25
TIMEOUT = ESPERA_LARGA + 10


class TelegramCaido(RuntimeError):
    """No se pudo hablar con la API. Reintentable."""


class DosPollers(RuntimeError):
    """🔴 409: hay otro proceso haciendo getUpdates con este mismo token.

    Un bot admite **un solo consumidor**: la cola de updates es única y el
    `offset` la confirma para todos. Con dos, se roban los mensajes de forma
    intermitente.

    Es el peor modo de fallo que puede tener este canal, porque reintentando en
    silencio se ve como «Telegram va lento» y se pierden respuestas sin que nadie
    sepa por qué. Por eso es una excepción propia: para que quien la reciba la
    enseñe en vez de tragársela.
    """


class SinToken(RuntimeError):
    """El puntero no lleva a ningún token. Se dice dónde se buscó."""


def leer_token(referencia: str) -> str:
    """Saca el token del sitio al que apunta `ruta#CLAVE`.

    Mismo formato que `conexiones.referencia_secreto`, a propósito: un formato
    para punteros a secretos y no dos.

    Sin ancla se admite un archivo que sea el token a secas, porque es lo que
    hace uno la primera vez y fallar ahí no enseña nada.
    """
    if not referencia or not referencia.strip():
        raise SinToken("no hay ninguna referencia al token configurada")

    ruta_txt, _, clave = referencia.partition("#")
    ruta = Path(ruta_txt.strip()).expanduser()
    if not ruta.is_file():
        raise SinToken(f"el puntero apunta a «{ruta}», que no existe")

    contenido = ruta.read_text(encoding="utf-8")
    if not clave:
        token = contenido.strip()
        if not token:
            raise SinToken(f"«{ruta}» está vacío")
        return token

    for linea in contenido.splitlines():
        linea = linea.strip()
        if not linea or linea.startswith("#"):
            continue
        # Formato `.env`: se admite `export CLAVE=valor` porque es como acaban
        # escritos estos archivos y rechazarlo sólo daría un fallo confuso.
        if linea.startswith("export "):
            linea = linea[len("export "):].strip()
        nombre, sep, valor = linea.partition("=")
        if sep and nombre.strip() == clave.strip():
            token = valor.strip().strip('"').strip("'")
            # 🔴 `CLAVE=` a secas es el estado NORMAL antes de pegar el token:
            # el archivo se deja preparado y se rellena después. Devolverlo
            # vacío hacía que el diagnóstico dijera «el puntero lleva a un
            # token» y que el fallo apareciera mucho más tarde, como un 401 de
            # Telegram — a tres capas del sitio donde está el problema.
            if not token:
                raise SinToken(f"«{ruta}» tiene «{clave}» pero está vacía")
            return token

    raise SinToken(f"«{ruta}» no tiene ninguna clave «{clave}»")


class Bot:
    """Lo mínimo de la Bot API: mandar un mensaje y recoger lo que llega.

    Deliberadamente pequeño. Cada método que se añada aquí es una capacidad más
    que alguien de fuera podría acabar teniendo, y este canal existe para que
    sólo haya dos: preguntar y recibir la respuesta.
    """

    def __init__(self, token: str, api: str = API):
        if not token:
            raise SinToken("token vacío")
        self._token = token
        self._api = api.rstrip("/")

    def _llamar(self, metodo: str, datos: dict, timeout: int = 20) -> dict:
        url = f"{self._api}/bot{self._token}/{metodo}"
        cuerpo = urllib.parse.urlencode(datos).encode()
        peticion = urllib.request.Request(url, data=cuerpo, method="POST")
        try:
            with urllib.request.urlopen(peticion, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            # 🔴 `HTTPError` hereda de `URLError`, así que si se atrapa la
            # segunda primero, un 409 se ve como «la red no va» y el fallo que
            # más importa distinguir se pierde. Va antes, y a propósito.
            detalle = ""
            try:
                detalle = json.loads(exc.read().decode("utf-8")).get("description", "")
            except Exception:
                detalle = str(exc)
            if exc.code == 409:
                raise DosPollers(detalle or "otro proceso está haciendo getUpdates") from exc
            raise TelegramCaido(f"HTTP {exc.code}: {detalle}") from exc
        except urllib.error.URLError as exc:
            raise TelegramCaido(str(exc.reason)) from exc
        except (TimeoutError, OSError) as exc:
            raise TelegramCaido(str(exc)) from exc

    def enviar(self, chat_id: int, texto: str) -> int | None:
        """Manda un mensaje y devuelve su `message_id`.

        Ese id es lo que casa la respuesta con su pregunta: llega de vuelta en
        `reply_to_message` y evita tener que adivinar a qué contesta nadie. Si
        no viene, se devuelve None y quien llama decide — dar por enviada una
        pregunta cuyo id no se conoce la deja sin forma de recibir respuesta.
        """
        r = self._llamar("sendMessage", {"chat_id": chat_id, "text": texto})
        if not r.get("ok"):
            raise TelegramCaido(str(r.get("description") or "sendMessage falló"))
        return (r.get("result") or {}).get("message_id")

    def actualizaciones(self, offset: int | None = None) -> list[dict]:
        """Long polling. No abre ningún puerto: la conexión la abre el hub.

        Es la decisión que permite que este canal exista sin tocar la regla dura
        8. Un webhook exigiría una URL pública con HTTPS y eso es exponer la
        máquina; `getUpdates` es saliente.
        """
        datos: dict = {"timeout": ESPERA_LARGA, "allowed_updates": json.dumps(["message"])}
        if offset is not None:
            datos["offset"] = offset
        r = self._llamar("getUpdates", datos, timeout=TIMEOUT)
        if not r.get("ok"):
            raise TelegramCaido(str(r.get("description") or "getUpdates falló"))
        return list(r.get("result") or [])


def partes_del_mensaje(update: dict) -> dict | None:
    """Lo que interesa de un update, o None si no es un mensaje de texto.

    Se normaliza aquí para que el relé no tenga que conocer la forma de la API,
    y para que `responde_a` quede explícito: es la pieza sobre la que descansa
    todo el casado, y enterrada en un `.get().get()` se vuelve fácil de romper.
    """
    mensaje = update.get("message") or {}
    texto = mensaje.get("text")
    de = mensaje.get("from") or {}
    if not texto or not de.get("id"):
        return None
    return {
        "update_id": update.get("update_id"),
        "user_id": int(de["id"]),
        "username": de.get("username") or "",
        "nombre": " ".join(x for x in (de.get("first_name"), de.get("last_name")) if x),
        "texto": texto,
        "responde_a": (mensaje.get("reply_to_message") or {}).get("message_id"),
    }
