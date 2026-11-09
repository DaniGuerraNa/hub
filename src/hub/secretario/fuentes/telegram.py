"""Telegram con la cuenta del dueño (definición 1.1), en sólo lectura.

🔴 **Cuenta de usuario, no un bot** (decisión 301). Un bot sólo ve lo que le
mandan o los grupos donde lo meten y le quitan el modo privado; para «¿qué
dijeron en el grupo del trabajo?» hace falta leer como el dueño. Telegram lo
permite oficialmente (MTProto, con un `api_id` propio de my.telegram.org), y
Telethon es la librería de referencia.

🔴 **La sesión es una llave de la cuenta entera** (regla dura 5). Quien tenga
el archivo `.session` puede leer y escribir como el dueño. Por eso:

- vive fuera de `HUB_HOME`, en `~/.secretos/` por omisión, y `fuentes.yml`
  sólo guarda dónde está (`credenciales:`);
- sólo la abre `hub-secretario`, nunca `hub-web` (decisión 298);
- esta fuente no llama a ningún método que escriba: lee diálogos y mensajes.

Entrar la primera vez es interactivo —Telegram manda un código al teléfono—:
`uv run python -m hub.secretario telegram-entrar`.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ... import llavero
from ..piezas import Evento, Fuente, ajustes_fuentes, alias_del_dueno, conversacion_admitida, para_mi

POR_OMISION = Path(os.environ.get("HUB_SECRETARIO_TELEGRAM", "~/.secretos/secretario-telegram")).expanduser()
# La primera vez se trae lo de estos días, no la historia entera: lo viejo se
# puede pedir después, y traerlo todo de golpe tarda y lo frena Telegram.
DIAS_AL_EMPEZAR = 14
POR_CONVERSACION = 400


def credenciales(ajustes: dict | None = None) -> Path:
    """La carpeta con `api.env` (TG_API_ID, TG_API_HASH) y la sesión."""
    a = ajustes if ajustes is not None else ajustes_fuentes().get("telegram", {})
    return Path(str(a.get("credenciales") or POR_OMISION)).expanduser()


#: Para el inventario del llavero (C-0143). Se sube `api.env`; la sesión
#: (`*.session`) no: da tu cuenta entera y se vuelve a abrir con el código.
LLAVES = (llavero.Llave("secretario-telegram", "la API de tu Telegram (api.env) y su sesión",
                        lambda: str(credenciales())),)


def _api(carpeta: Path) -> tuple[int, str] | None:
    try:
        lineas = (carpeta / "api.env").read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    valores = dict(l.split("=", 1) for l in lineas if "=" in l and not l.lstrip().startswith("#"))
    try:
        return int(valores["TG_API_ID"].strip()), valores["TG_API_HASH"].strip()
    except (KeyError, ValueError):
        return None


def _cliente(carpeta: Path):
    from telethon.sync import TelegramClient

    api = _api(carpeta)
    if not api:
        raise RuntimeError(f"faltan TG_API_ID y TG_API_HASH en {carpeta / 'api.env'}")
    return TelegramClient(str(carpeta / "sesion"), api[0], api[1])


def _nombre(entidad) -> str:
    if entidad is None:
        return ""
    if getattr(entidad, "title", None):
        return entidad.title
    partes = [getattr(entidad, "first_name", None) or "", getattr(entidad, "last_name", None) or ""]
    return " ".join(p for p in partes if p).strip() or (getattr(entidad, "username", None) or "")


class FuenteTelegram(Fuente):
    id = "telegram"
    nombre = "Telegram"
    descripcion = "Tus chats y grupos de Telegram, leídos con tu cuenta (sólo lectura)."
    intervalo = 120

    def disponible(self) -> str | None:
        try:
            import telethon  # noqa: F401
        except ImportError:
            return "falta la librería telethon (uv sync)"
        # Sólo si existen, sin leerlos: esto lo pinta también `hub-web`, que no
        # debe abrir las llaves de las fuentes (decisión 298).
        carpeta = credenciales()
        if not (carpeta / "api.env").is_file():
            return (f"falta {carpeta / 'api.env'} con TG_API_ID y TG_API_HASH (de my.telegram.org); "
                    "luego: uv run python -m hub.secretario telegram-entrar")
        if not (carpeta / "sesion.session").is_file():
            return "falta entrar con tu cuenta: uv run python -m hub.secretario telegram-entrar"
        return None

    def conversaciones(self) -> list[str]:
        # `connect` y no `with`: `with` llama a `start()`, que si la sesión no
        # vale se queda preguntando el teléfono por la entrada estándar.
        c = _cliente(credenciales())
        c.connect()
        try:
            if not c.is_user_authorized():
                raise RuntimeError("la sesión de Telegram ya no vale: vuelve a entrar (telegram-entrar)")
            return [d.name for d in c.iter_dialogs(limit=200) if d.name]
        finally:
            c.disconnect()

    def leer(self, cursor: str, ajustes: dict) -> tuple[list[Evento], str]:
        ultimos: dict[str, int] = json.loads(cursor) if cursor else {}
        eventos: list[Evento] = []
        desde = datetime.now(timezone.utc) - timedelta(days=DIAS_AL_EMPEZAR)
        alias = alias_del_dueno(ajustes)
        c = _cliente(credenciales(ajustes))
        c.connect()
        try:
            if not c.is_user_authorized():
                raise RuntimeError("la sesión de Telegram ya no vale: vuelve a entrar (telegram-entrar)")
            for d in c.iter_dialogs(limit=200):
                if not d.name or not conversacion_admitida(ajustes, d.name):
                    continue
                # Los canales de difusión (noticias, avisos de terceros) no son
                # conversaciones suyas: sólo si los pide por nombre en `incluir`.
                if d.is_channel and not d.is_group and d.name.lower() not in \
                        [c.lower() for c in ajustes.get("incluir") or []]:
                    continue
                clave = str(d.id)
                # Sin nada nuevo desde la última vez no se pregunta: cada chat es
                # una petición, y Telegram frena (FloodWait) a quien pide de más.
                if clave in ultimos and d.message and d.message.id <= ultimos[clave]:
                    continue
                # Lo nuevo: si hay cursor, desde ahí; si no, de los últimos días.
                if clave in ultimos:
                    mensajes = c.iter_messages(d.entity, min_id=ultimos[clave], reverse=True,
                                               limit=POR_CONVERSACION)
                elif d.date and d.date < desde:
                    ultimos[clave] = d.message.id if d.message else 0
                    continue
                else:
                    mensajes = c.iter_messages(d.entity, offset_date=desde, reverse=True,
                                               limit=POR_CONVERSACION)
                for m in mensajes:
                    ultimos[clave] = max(ultimos.get(clave, 0), m.id)
                    texto = m.message or ""
                    if m.voice or m.audio:
                        texto = (texto + "\n" if texto else "") + self._audio(c, m)
                    elif m.media and not texto:
                        texto = "[adjunto]"
                    if not texto.strip():
                        continue
                    autor = "Yo" if m.out else _nombre(m.sender)
                    eventos.append(Evento(
                        fuente=self.id, id_externo=f"{d.id}:{m.id}", fecha=m.date.isoformat(),
                        texto=texto, conversacion=d.name, autor=autor,
                        enlace=f"https://t.me/c/{str(d.id).removeprefix('-100')}/{m.id}" if d.is_channel or d.is_group else "",
                        # `mentioned` lo pone Telegram: lo etiquetan o responden a un mensaje suyo.
                        para_mi="" if m.out else para_mi(texto, alias, grupo=bool(d.is_group or d.is_channel),
                                                         etiqueta=bool(getattr(m, "mentioned", False)))))
        finally:
            c.disconnect()
        return eventos, json.dumps(ultimos)

    def _audio(self, c, m) -> str:
        """El audio en texto, en casa (decisión 221). Si no hay transcriptor,
        se dice: «[audio]» a secas haría creer que no había nada."""
        from ... import transcribir

        with tempfile.TemporaryDirectory() as d:
            try:
                ruta = c.download_media(m, file=os.path.join(d, "audio"))
                return "[audio] " + transcribir.transcribir(Path(ruta))
            except (transcribir.SinTranscriptor, transcribir.NoSeEntendio, OSError) as exc:
                return f"[audio sin transcribir: {str(exc)[:120]}]"


def telefono(crudo: str) -> str:
    """El teléfono como lo quiere Telegram: `+` y sólo dígitos. Sin lada se
    supone México, y el «1» de los celulares mexicanos antiguos (`+521…`)
    se quita: Telegram lo rechaza como número inválido (2-nov)."""
    digitos = "".join(ch for ch in crudo if ch.isdigit())
    if not crudo.strip().startswith("+") and len(digitos) == 10:
        digitos = "52" + digitos
    if digitos.startswith("521") and len(digitos) == 13:
        digitos = "52" + digitos[3:]
    return "+" + digitos


def entrar() -> None:  # pragma: no cover - es interactivo por naturaleza
    """La primera vez: pide `api_id`, `api_hash`, el teléfono y el código."""
    carpeta = credenciales()
    carpeta.mkdir(parents=True, exist_ok=True)
    os.chmod(carpeta, 0o700)
    if not _api(carpeta):
        print("Crea una aplicación en https://my.telegram.org → API development tools.")
        api_id = input("api_id: ").strip()
        api_hash = input("api_hash: ").strip()
        (carpeta / "api.env").write_text(f"TG_API_ID={api_id}\nTG_API_HASH={api_hash}\n", encoding="utf-8")
        os.chmod(carpeta / "api.env", 0o600)
    from telethon.errors import PhoneNumberInvalidError

    c = _cliente(carpeta)
    tel = telefono(input("Tu teléfono (con lada, p. ej. +52 55 1234 5678): "))
    try:
        c.start(phone=tel)  # pregunta el código (llega a la app de Telegram) y la contraseña si hay
    except PhoneNumberInvalidError:
        raise SystemExit(f"Telegram dice que {tel} no es válido. Escríbelo con lada y sin el 1 de "
                         "celular: +52 y los 10 dígitos.") from None
    with c:
        yo = c.get_me()
        print(f"Dentro como {_nombre(yo)}. La sesión está en {carpeta / 'sesion.session'}.")
    os.chmod(carpeta / "sesion.session", 0o600)


FUENTE = FuenteTelegram()
