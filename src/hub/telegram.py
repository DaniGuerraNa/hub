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

import http.client
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
        # 🔴 `IncompleteRead` —una respuesta que llega corta— NO hereda de
        # `OSError`, así que sin nombrarla aquí se escapaba sin envolver y quien
        # llama, que atrapa `TelegramCaido` para reintentar, se llevaba un error
        # de otro tipo. Un corte de red a media lectura es de lo más normal en
        # una conexión doméstica: es reintentable, y tiene que llegar dicho así.
        except (TimeoutError, OSError, http.client.HTTPException) as exc:
            raise TelegramCaido(str(exc)) from exc

    # Qué actualizaciones se piden. El canal de consulta sólo mensajes; el de
    # encargos, además, las pulsaciones de sus botones.
    ADMITE = ["message"]

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
        datos: dict = {"timeout": ESPERA_LARGA, "allowed_updates": json.dumps(self.ADMITE)}
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


class BotDeEncargos(Bot):
    """Lo que el canal de encargos necesita y el de consulta no debe tener.

    🔴 **Es una clase aparte y no cuatro métodos más en `Bot`.** La cabecera de
    `Bot` dice por qué: cada método es una capacidad más que alguien de fuera
    podría acabar teniendo, y el canal de consulta existe para que sólo haya dos
    —preguntar y recibir—. Aquí hacen falta cuatro cosas más, pero las hacen
    falta **a otro bot, con otro token y en otro servicio** (decisión 221).
    Heredar y no ampliar es lo que mantiene esa frase siendo verdad.

    Las cuatro, con su motivo:

    - **Fotos.** Son el mecanismo, no un adorno: quien no sabe describir un
      estilo sí sabe elegir uno viéndolo (decisión 285).
    - **«escribiendo…»**, que es lo que evita que un silencio de veinte segundos
      se lea como que el bot no hace caso.
    - **Descargar un audio**, porque es la materia prima de todo esto.
    - **Responder a un mensaje concreto**, que es como él aprueba un plan: sobre
      ese plan y no sobre un «sí» suelto (decisión 281).
    """

    def _multiparte(self, metodo: str, campos: dict, archivo: tuple[str, str, bytes],
                    timeout: int = 60) -> dict:
        """`multipart/form-data` a mano: subir un archivo no cabe en urlencode."""
        limite = "----hub" + f"{id(archivo):x}"
        partes: list[bytes] = []
        for clave, valor in campos.items():
            partes.append(
                f"--{limite}\r\nContent-Disposition: form-data; name=\"{clave}\"\r\n\r\n"
                f"{valor}\r\n".encode()
            )
        nombre, fichero, datos = archivo
        partes.append(
            f"--{limite}\r\nContent-Disposition: form-data; name=\"{nombre}\"; "
            f"filename=\"{fichero}\"\r\nContent-Type: application/octet-stream\r\n\r\n"
            .encode() + datos + b"\r\n"
        )
        partes.append(f"--{limite}--\r\n".encode())

        peticion = urllib.request.Request(
            f"{self._api}/bot{self._token}/{metodo}", data=b"".join(partes),
            headers={"Content-Type": f"multipart/form-data; boundary={limite}"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(peticion, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise TelegramCaido(f"HTTP {exc.code} en {metodo}") from exc
        except urllib.error.URLError as exc:
            raise TelegramCaido(str(exc.reason)) from exc
        except (TimeoutError, OSError, http.client.HTTPException) as exc:
            raise TelegramCaido(str(exc)) from exc

    def enviar_foto(self, chat_id: int, ruta: Path, pie: str = "") -> int | None:
        """Manda una imagen del catálogo de estilos. Nunca algo de la persona.

        Lo que sale por aquí son capturas genéricas preparadas de antemano
        (`estilos.py`), y por eso mandarlas no saca nada de la máquina — que es
        lo que la regla dura 22 vigila. Si algún día esto mandara una captura de
        lo construido para alguien, esa frase deja de ser cierta.
        """
        ruta = Path(ruta)
        if not ruta.is_file():
            raise TelegramCaido(f"no existe la imagen «{ruta}»")
        campos = {"chat_id": str(chat_id)}
        if pie:
            campos["caption"] = pie
        r = self._multiparte(
            "sendPhoto", campos, ("photo", ruta.name, ruta.read_bytes())
        )
        if not r.get("ok"):
            raise TelegramCaido(str(r.get("description") or "sendPhoto falló"))
        return (r.get("result") or {}).get("message_id")

    ADMITE = ["message", "callback_query"]

    def enviar_con_botones(self, chat_id: int, texto: str,
                           botones: list[tuple[str, str]]) -> int | None:
        """Un mensaje con botones debajo (decisión 237): «Aprobar», «Otra ronda»…

        Pulsar uno llega como `callback_query` atado a ESTE mensaje, así que el
        gate de la 281 —aprobar es responder a ese mensaje— se cumple igual, sólo
        que con un dedo en vez de escribiendo «aprobado».
        """
        teclado = {"inline_keyboard": [[{"text": t, "callback_data": d} for t, d in botones]]}
        r = self._llamar("sendMessage", {
            "chat_id": chat_id, "text": texto, "reply_markup": json.dumps(teclado),
        })
        if not r.get("ok"):
            raise TelegramCaido(str(r.get("description") or "sendMessage falló"))
        return (r.get("result") or {}).get("message_id")

    def pulsado(self, callback_id: str, texto: str = "") -> None:
        """Cierra el «cargando…» del botón. Cosmético: si falla, no pasa nada."""
        try:
            self._llamar("answerCallbackQuery", {"callback_query_id": callback_id, "text": texto})
        except TelegramCaido:
            pass

    def quitar_botones(self, chat_id: int, message_id: int) -> None:
        """Retira los botones de un mensaje ya decidido. Cosmético también."""
        try:
            self._llamar("editMessageReplyMarkup", {
                "chat_id": chat_id, "message_id": message_id,
                "reply_markup": json.dumps({"inline_keyboard": []}),
            })
        except TelegramCaido:
            pass

    def responder(self, chat_id: int, texto: str, a_mensaje: int) -> int | None:
        """Un mensaje colgado de otro, para que se vea a qué contesta."""
        r = self._llamar("sendMessage", {
            "chat_id": chat_id, "text": texto, "reply_to_message_id": a_mensaje,
        })
        if not r.get("ok"):
            raise TelegramCaido(str(r.get("description") or "sendMessage falló"))
        return (r.get("result") or {}).get("message_id")

    def escribiendo(self, chat_id: int) -> None:
        """El «escribiendo…» de Telegram. Dura unos 5 s, así que se repite.

        🔴 Es lo que cubre las esperas cortas **sin mandar un mensaje**. Un bot
        que escribe «sigo aquí» cada treinta segundos se silencia el mismo día;
        el indicador dice lo mismo y no deja rastro en la conversación.

        Si falla, no es nada: es un adorno de cortesía y perderlo no pierde
        información. Por eso se traga el fallo aquí y no arriba — lo contrario
        haría que un parpadeo de red frenara la vuelta entera del relé.
        """
        try:
            self._llamar("sendChatAction", {"chat_id": chat_id, "action": "typing"})
        except TelegramCaido:
            pass

    def descargar(self, file_id: str, destino: Path) -> Path:
        """Trae un audio a disco. Es la materia prima de todo el encargo.

        Se baja **en casa** a propósito (decisión 221): es la voz de alguien
        describiendo su negocio, y transcribirla fuera sacaría de la máquina
        justo lo que la regla dura 22 protege.
        """
        r = self._llamar("getFile", {"file_id": file_id})
        if not r.get("ok"):
            raise TelegramCaido(str(r.get("description") or "getFile falló"))
        camino = (r.get("result") or {}).get("file_path")
        if not camino:
            raise TelegramCaido("getFile no devolvió file_path")

        url = f"{self._api}/file/bot{self._token}/{camino}"
        destino = Path(destino)
        destino.parent.mkdir(parents=True, exist_ok=True)
        try:
            with urllib.request.urlopen(url, timeout=TIMEOUT) as r_:
                datos = r_.read()
        # 🔴 `http.client.HTTPException` va aquí porque `IncompleteRead` —el
        # corte a media lectura, que es EL caso que el temporal de abajo dice
        # cubrir— no hereda de `OSError` y se escapaba sin envolver. El relé
        # atrapa `TelegramCaido` para aparcar el audio y reintentarlo; sin esto
        # se llevaba otra excepción y el audio no se aparcaba con su razón.
        except (urllib.error.URLError, TimeoutError, OSError,
                http.client.HTTPException) as exc:
            raise TelegramCaido(f"no se pudo bajar el audio: {exc}") from exc

        # Con un temporal: un archivo a medias parece un audio válido y whisper
        # transcribiría medio negocio sin que nada dijera que faltaba la otra
        # mitad.
        parcial = destino.with_suffix(destino.suffix + ".parcial")
        try:
            parcial.write_bytes(datos)
            parcial.replace(destino)
        except OSError as exc:
            parcial.unlink(missing_ok=True)
            raise TelegramCaido(f"no se pudo guardar el audio: {exc}") from exc
        return destino


def boton_pulsado(update: dict) -> dict | None:
    """Una pulsación de botón, con la forma de un mensaje que responde a otro.

    Es la misma forma que devuelve `partes_con_voz` a propósito: `texto` es lo
    que el botón lleva dentro («aprobado», «otra ronda») y `responde_a` es el
    mensaje bajo el que estaba, así que `procesar_mensaje` no distingue —ni
    tiene por qué— entre pulsar y escribir (decisión 237).
    """
    cq = update.get("callback_query") or {}
    de = cq.get("from") or {}
    mensaje = cq.get("message") or {}
    if not de.get("id") or not mensaje.get("message_id") or not cq.get("data"):
        return None
    return {
        "update_id": update.get("update_id"),
        "message_id": None,
        "user_id": int(de["id"]),
        "username": de.get("username") or "",
        "nombre": " ".join(x for x in (de.get("first_name"), de.get("last_name")) if x),
        "texto": str(cq["data"]),
        "voz": "",
        "segundos": 0,
        "responde_a": int(mensaje["message_id"]),
        "boton": True,
        "callback_id": str(cq.get("id") or ""),
        "chat_id": int((mensaje.get("chat") or {}).get("id") or de["id"]),
    }


def partes_con_voz(update: dict) -> dict | None:
    """Como `partes_del_mensaje`, pero admitiendo notas de voz.

    🔴 Función aparte y no un parámetro, para que el canal de consulta siga
    ignorando los audios exactamente igual que antes. Allí un `texto` vacío con
    un `voz` al lado se colaría por caminos que esperan texto, y eso convertiría
    una nota de voz mandada por error en un registro raro imposible de explicar.
    """
    mensaje = update.get("message") or {}
    de = mensaje.get("from") or {}
    if not de.get("id"):
        return None

    voz = mensaje.get("voice") or mensaje.get("audio") or {}
    texto = mensaje.get("text") or mensaje.get("caption") or ""
    if not texto and not voz.get("file_id"):
        return None

    return {
        "update_id": update.get("update_id"),
        "message_id": mensaje.get("message_id"),
        "user_id": int(de["id"]),
        "username": de.get("username") or "",
        "nombre": " ".join(x for x in (de.get("first_name"), de.get("last_name")) if x),
        "texto": texto,
        "voz": voz.get("file_id") or "",
        "segundos": int(voz.get("duration") or 0),
        "responde_a": (mensaje.get("reply_to_message") or {}).get("message_id"),
    }
