"""El chat web como otro bot de encargos (decisión 246).

La misma interfaz que `telegram.BotDeEncargos` —recibir, mandar texto, fotos y
botones, «escribiendo…», bajar audios— sobre el servidor de `scripts/chat-web`.
Igual que con Telegram, **la conexión la abre el hub**: aquí no hay ningún
puerto; el relé recoge y deja. Y el token del hub vive fuera, con un puntero
en `encargos.yml` (`chat_web: {url, token_ref}`), como el del bot.

`Bots` es lo que hace que el relé no tenga que saber cuántos canales hay: se le
da uno solo que reparte por el canal de cada persona.
"""

from __future__ import annotations

import json
import secrets
import sqlite3
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

from . import telegram


TIMEOUT = 15
PREFIJO_MEDIO = "web:"


class BotDeChat:
    """Habla con el servidor del chat. Cada método es una llamada, sin estado."""

    ADMITE = ["message", "callback_query"]

    def __init__(self, url: str, token: str) -> None:
        self.url = url.rstrip("/")
        self.token = token

    # ── transporte ──────────────────────────────────────────────────────────

    def _peticion(self, ruta: str, datos: dict | None = None, *, metodo: str = "POST",
                  archivo: tuple[str, str, bytes] | None = None) -> dict:
        cabeceras = {"Authorization": f"Bearer {self.token}"}
        cuerpo: bytes | None = None
        if archivo:
            limite = uuid.uuid4().hex
            partes = []
            for k, v in (datos or {}).items():
                partes.append(f"--{limite}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode("utf-8"))
            campo, nombre, bytes_ = archivo
            partes.append((f"--{limite}\r\nContent-Disposition: form-data; name=\"{campo}\"; "
                           f"filename=\"{nombre}\"\r\nContent-Type: application/octet-stream\r\n\r\n").encode("utf-8"))
            partes.append(bytes_ + b"\r\n")
            partes.append(f"--{limite}--\r\n".encode("utf-8"))
            cuerpo = b"".join(partes)
            cabeceras["Content-Type"] = f"multipart/form-data; boundary={limite}"
        elif datos is not None and metodo == "POST":
            cuerpo = urllib.parse.urlencode(datos).encode("utf-8")
            cabeceras["Content-Type"] = "application/x-www-form-urlencoded"
        elif datos:
            ruta += "?" + urllib.parse.urlencode(datos)
        peticion = urllib.request.Request(self.url + ruta, data=cuerpo, headers=cabeceras, method=metodo)
        try:
            with self._abrir(peticion) as r:
                crudo = r.read()
        except urllib.error.HTTPError as exc:
            raise telegram.TelegramCaido(f"el chat web contestó {exc.code} en {ruta}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise telegram.TelegramCaido(f"el chat web no responde: {exc}") from exc
        try:
            return json.loads(crudo.decode("utf-8")) if crudo else {}
        except ValueError as exc:
            raise telegram.TelegramCaido("el chat web devolvió algo que no es JSON") from exc

    def _abrir(self, peticion):  # separado para poder sustituirlo en las pruebas
        return urllib.request.urlopen(peticion, timeout=TIMEOUT)

    # ── lo que el relé le pide ──────────────────────────────────────────────

    def enviar(self, chat_id: int, texto: str) -> int | None:
        return self._peticion("/hub/mensajes", {"user_id": int(chat_id), "texto": texto}).get("message_id")

    def enviar_con_botones(self, chat_id: int, texto: str, botones: list) -> int | None:
        return self._peticion("/hub/mensajes", {
            "user_id": int(chat_id), "texto": texto,
            "botones": json.dumps([list(b) for b in botones], ensure_ascii=False)}).get("message_id")

    def enviar_foto(self, chat_id: int, ruta: Path, pie: str = "") -> int | None:
        return self._peticion("/hub/fotos", {"user_id": int(chat_id), "pie": pie},
                              archivo=("foto", Path(ruta).name, Path(ruta).read_bytes())).get("message_id")

    def pulsado(self, callback_id: str, texto: str = "") -> None:
        return None   # en la página el botón desaparece al pulsarlo; no hay «cargando…»

    def quitar_botones(self, chat_id: int, message_id: int) -> None:
        self._peticion("/hub/quitar_botones", {"user_id": int(chat_id), "message_id": int(message_id)})

    def escribiendo(self, chat_id: int) -> None:
        self._peticion("/hub/escribiendo", {"user_id": int(chat_id)})

    def descargar(self, file_id: str, destino: Path) -> Path:
        nombre = file_id[len(PREFIJO_MEDIO):] if file_id.startswith(PREFIJO_MEDIO) else file_id
        peticion = urllib.request.Request(f"{self.url}/hub/medios/{urllib.parse.quote(nombre)}",
                                          headers={"Authorization": f"Bearer {self.token}"})
        try:
            with self._abrir(peticion) as r:
                cuerpo = r.read()
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise telegram.TelegramCaido(f"no se pudo bajar el audio del chat web: {exc}") from exc
        destino = Path(destino)
        destino.parent.mkdir(parents=True, exist_ok=True)
        # Es webm/opus, no ogg: el transcriptor lo lee igual, pero el nombre
        # tiene que decir la verdad para que ffmpeg no adivine.
        destino = destino.with_suffix(".webm")
        destino.write_bytes(cuerpo)
        return destino

    def actualizaciones(self, offset: int | None = None) -> list[dict]:
        r = self._peticion("/hub/actualizaciones", {"desde": int(offset or 0)}, metodo="GET")
        return list(r.get("result") or [])

    # ── el alta de una persona, desde el hub ────────────────────────────────

    def crear_persona(self, usuario: str, nombre: str) -> tuple[int, str]:
        """Da de alta a alguien en el chat. Devuelve (user_id, contraseña).

        🔴 La contraseña se devuelve UNA vez y no se guarda en el hub (regla
        dura 5): al servidor va el hash, y a él se le enseña para que se la dé.
        """
        import bcrypt

        clave = secrets.token_urlsafe(8)
        hash_ = bcrypt.hashpw(clave.encode("utf-8"), bcrypt.gensalt()).decode("ascii")
        r = self._peticion("/hub/personas", {"usuario": usuario, "nombre": nombre, "hash": hash_})
        return int(r["user_id"]), clave

    def renombrar(self, user_id: int, nombre: str) -> None:
        """El nombre que ve al entrar («Hola, …»); el usuario no cambia."""
        self._peticion(f"/hub/personas/{int(user_id)}/nombre", {"nombre": nombre})

    def nueva_clave(self, user_id: int) -> str:
        import bcrypt

        clave = secrets.token_urlsafe(8)
        hash_ = bcrypt.hashpw(clave.encode("utf-8"), bcrypt.gensalt()).decode("ascii")
        self._peticion(f"/hub/personas/{int(user_id)}/clave", {"hash": hash_})
        return clave


def configurado(ajustes: dict) -> dict | None:
    bloque = ajustes.get("chat_web") or {}
    if not isinstance(bloque, dict) or not str(bloque.get("url") or "").strip():
        return None
    return bloque


def bot(ajustes: dict) -> BotDeChat | None:
    bloque = configurado(ajustes)
    if not bloque:
        return None
    return BotDeChat(str(bloque["url"]), telegram.leer_token(str(bloque.get("token_ref") or "")))


class Bots:
    """Un bot que reparte por el canal de cada persona (decisión 246).

    El relé sigue viendo un solo bot. Las salidas van al canal de la persona
    —que se lee de la base en el momento, no se cachea—; las entradas se
    recogen de todos, cada uno con su propio cursor; y un audio se baja del
    canal que lo tenga, que se sabe por el prefijo de su id.
    """

    def __init__(self, con: sqlite3.Connection, por_canal: dict[str, object]) -> None:
        self.con = con
        self.por_canal = por_canal
        self.cursores: dict[str, int | None] = {c: None for c in por_canal}
        self.caidos: dict[str, str] = {}

    def _de(self, chat_id: int):
        fila = self.con.execute("SELECT canal FROM encargo_persona WHERE user_id = ?",
                                (int(chat_id),)).fetchone()
        canal = (fila["canal"] if fila else None) or "telegram"
        if canal not in self.por_canal:
            raise telegram.TelegramCaido(f"la persona {chat_id} es de «{canal}» y ese canal no está configurado")
        return self.por_canal[canal]

    def enviar(self, chat_id, texto):
        return self._de(chat_id).enviar(chat_id, texto)

    def enviar_con_botones(self, chat_id, texto, botones):
        return self._de(chat_id).enviar_con_botones(chat_id, texto, botones)

    def enviar_foto(self, chat_id, ruta, pie=""):
        return self._de(chat_id).enviar_foto(chat_id, ruta, pie)

    def escribiendo(self, chat_id):
        return self._de(chat_id).escribiendo(chat_id)

    def quitar_botones(self, chat_id, message_id):
        return self._de(chat_id).quitar_botones(chat_id, message_id)

    def pulsado(self, callback_id, texto=""):
        canal = "web" if str(callback_id).startswith("web") else "telegram"
        b = self.por_canal.get(canal)
        return b.pulsado(callback_id, texto) if b else None

    def descargar(self, file_id, destino):
        canal = "web" if str(file_id).startswith(PREFIJO_MEDIO) else "telegram"
        b = self.por_canal.get(canal)
        if not b:
            raise telegram.TelegramCaido(f"no hay canal «{canal}» para bajar {file_id}")
        return b.descargar(file_id, destino)

    def actualizaciones(self, offset: int | None = None) -> list[dict]:
        """Las de todos. El `offset` que el relé devuelve es el de Telegram; el
        del chat web se lleva aquí, y los updates del chat salen marcados para
        no confundir sus ids con los de Telegram."""
        salida: list[dict] = []
        for canal, b in self.por_canal.items():
            if canal == "telegram":
                salida += b.actualizaciones(offset)
                continue
            try:
                nuevas = b.actualizaciones(self.cursores.get(canal))
            except telegram.TelegramCaido as exc:
                # 🔴 Que el chat esté caído no puede parar Telegram: se apunta
                # una vez por racha y se sigue con los demás canales.
                if self.caidos.get(canal) != str(exc):
                    self.caidos[canal] = str(exc)
                    from . import encargos

                    encargos.registrar(self.con, "falla", f"el canal «{canal}» no responde: {exc}")
                continue
            self.caidos.pop(canal, None)
            for u in nuevas:
                self.cursores[canal] = max(int(u.get("update_id", 0)) + 1, self.cursores.get(canal) or 0)
                u = dict(u)
                u["update_id"] = offset or 0   # que no mueva el offset de Telegram
                u["canal"] = canal
                salida.append(u)
        return salida
