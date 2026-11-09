"""El correo del dueño por IMAP (definición 1.1), en sólo lectura.

IMAP y no la API de Gmail: sirve para cualquier cuenta (Gmail con una
contraseña de aplicación, Outlook, la de un dominio propio) con la biblioteca
estándar, y el contrato de fuente no cambia si mañana se añade otra.

🔴 **Sólo lectura de verdad, no por buena voluntad:**

- los buzones se abren con `EXAMINE` (`readonly=True`): el servidor no deja
  cambiar nada en esa sesión;
- se pide `BODY.PEEK[]`, no `BODY[]`: leer un correo no lo marca como leído.
  Que el secretario lo lea no puede hacer que el dueño lo pierda en su bandeja.

🔴 **La contraseña es una llave de la cuenta** (regla dura 5). Vive en
`~/.secretos/secretario-correo/cuenta.env` (permisos 600), sólo la abre
`hub-secretario`, y `fuentes.yml` guarda a lo sumo dónde está. Para Gmail es
una *contraseña de aplicación*, no la de la cuenta: se revoca sola sin tocar
lo demás.

Lo masivo (boletines, avisos automáticos: `List-Unsubscribe`, `Precedence:
bulk`, `Auto-Submitted`) no se lee salvo que su remitente esté en «Sólo
estas»: es la mayor parte del correo y casi nunca tiene nada del dueño.
"""

from __future__ import annotations

import email
import imaplib
import json
import os
import re
from datetime import datetime, timedelta, timezone
from email.header import decode_header, make_header
from email.policy import default as POLITICA
from email.utils import getaddresses, parseaddr, parsedate_to_datetime
from html import unescape
from pathlib import Path

from ... import llavero
from ..piezas import Evento, Fuente, ajustes_fuentes

DIAS_AL_EMPEZAR = 14
POR_LECTURA = 200
TOPE_CUERPO = 8000


def carpeta(ajustes: dict | None = None) -> Path:
    a = ajustes if ajustes is not None else ajustes_fuentes().get("correo", {})
    por_omision = os.environ.get("HUB_SECRETARIO_CORREO", "~/.secretos/secretario-correo")
    return Path(str(a.get("credenciales") or por_omision)).expanduser()


#: Para el inventario del llavero (C-0143): dónde vive, nunca el valor.
LLAVES = (llavero.Llave("secretario-correo", "la cuenta de correo que lee el secretario", lambda: str(carpeta())),)


def cuenta(ajustes: dict | None = None) -> dict | None:
    """`cuenta.env`: IMAP_SERVIDOR, IMAP_USUARIO, IMAP_CLAVE y, opcionales,
    IMAP_PUERTO (993) e IMAP_SEGURIDAD (`ssl`, `starttls`; `ninguna` sólo en 127.0.0.1)."""
    try:
        lineas = (carpeta(ajustes) / "cuenta.env").read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    v = {k.strip(): x.strip() for k, x in (l.split("=", 1) for l in lineas if "=" in l and not l.lstrip().startswith("#"))}
    if not all(v.get(k) for k in ("IMAP_SERVIDOR", "IMAP_USUARIO", "IMAP_CLAVE")):
        return None
    return v


def conectar(c: dict) -> imaplib.IMAP4:
    seguridad = c.get("IMAP_SEGURIDAD", "ssl").lower()
    servidor = c["IMAP_SERVIDOR"]
    if seguridad == "ninguna":
        # Sin cifrar sólo contra la propia máquina (pruebas): la contraseña
        # viajaría en claro por la red.
        if servidor not in ("127.0.0.1", "localhost"):
            raise RuntimeError("IMAP sin cifrar sólo se admite contra 127.0.0.1")
        m = imaplib.IMAP4(servidor, int(c.get("IMAP_PUERTO") or 143))
    elif seguridad == "starttls":
        m = imaplib.IMAP4(servidor, int(c.get("IMAP_PUERTO") or 143))
        m.starttls()
    else:
        m = imaplib.IMAP4_SSL(servidor, int(c.get("IMAP_PUERTO") or 993), timeout=30)
    m.login(c["IMAP_USUARIO"], c["IMAP_CLAVE"])
    return m


# ───────────────────────────── leer un correo ─────────────────────────────


def _texto_cabecera(v) -> str:
    try:
        return str(make_header(decode_header(str(v or ""))))
    except Exception:  # noqa: BLE001 — una cabecera mal codificada no tumba la lectura
        return str(v or "")


def _de_html(html: str) -> str:
    html = re.sub(r"(?is)<(script|style|head).*?</\1>", " ", html)
    html = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</li>|</tr>", "\n", html)
    texto = unescape(re.sub(r"<[^>]+>", " ", html))
    return re.sub(r"[ \t\xa0]+", " ", re.sub(r"\n\s*\n+", "\n\n", texto)).strip()


def _sin_citas(texto: str) -> str:
    """Lo que escribió esta persona, sin el hilo citado debajo: eso ya llegó antes."""
    corte = re.search(r"(?im)^(?:>.*\n?){2,}|^(?:El|On) .{0,200}(?:escribió|wrote):\s*$|^-{2,} ?(?:Original Message|Mensaje original)",
                      texto)
    return texto[:corte.start()].rstrip() if corte and corte.start() > 0 else texto


def cuerpo(m: email.message.EmailMessage) -> tuple[str, list[str]]:
    """El texto del correo (el plano si hay; si no, el HTML limpio) y los nombres de los adjuntos."""
    plano, html, adjuntos = None, None, []
    for parte in m.walk():
        if parte.is_multipart():
            continue
        disp = parte.get_content_disposition()
        nombre = parte.get_filename()
        if disp == "attachment" or (nombre and disp != "inline"):
            adjuntos.append(_texto_cabecera(nombre or "adjunto"))
            continue
        tipo = parte.get_content_type()
        try:
            contenido = parte.get_content()
        except Exception:  # noqa: BLE001 — un charset raro: se salta esa parte, no el correo
            continue
        if tipo == "text/plain" and plano is None:
            plano = contenido
        elif tipo == "text/html" and html is None:
            html = contenido
    texto = plano if plano and plano.strip() else _de_html(html or "")
    return _sin_citas(texto.strip())[:TOPE_CUERPO], adjuntos


def es_masivo(m: email.message.Message) -> bool:
    prec = str(m.get("Precedence", "")).lower()
    auto = str(m.get("Auto-Submitted", "no")).lower()
    return bool(m.get("List-Unsubscribe") or m.get("List-Id")) or prec in ("bulk", "list", "junk") or auto != "no"


def evento(crudo: bytes, uid: str, buzon: str, propias: set[str]) -> tuple[Evento, bool]:
    """Un correo como evento del secretario, y si es masivo."""
    m = email.message_from_bytes(crudo, policy=POLITICA)
    nombre, direccion = parseaddr(str(m.get("From", "")))
    nombre = _texto_cabecera(nombre) or direccion
    asunto = _texto_cabecera(m.get("Subject", "")) or "(sin asunto)"
    try:
        fecha = parsedate_to_datetime(str(m.get("Date"))).astimezone(timezone.utc)
    except (TypeError, ValueError, IndexError):
        fecha = datetime.now(timezone.utc)
    texto, adjuntos = cuerpo(m)
    para = ", ".join(_texto_cabecera(n) or d for n, d in getaddresses([str(m.get("To", ""))]))[:200]
    mio = direccion.lower() in propias
    cabeza = f"Asunto: {asunto}\n" + (f"Para: {para}\n" if para else "") + (
        f"Adjuntos: {', '.join(adjuntos)}\n" if adjuntos else "")
    ev = Evento(fuente="correo", id_externo=str(m.get("Message-ID") or f"{buzon}:{uid}").strip(),
                fecha=fecha.isoformat(timespec="seconds"), texto=cabeza + "\n" + texto,
                conversacion=f"{nombre} <{direccion}>" if not mio else f"Enviados: {para}",
                autor="Yo" if mio else nombre, adjuntos=adjuntos)
    return ev, es_masivo(m)


# ───────────────────────────── la fuente ─────────────────────────────


class FuenteCorreo(Fuente):
    id = "correo"
    nombre = "Correo"
    descripcion = "Tu correo por IMAP (Gmail, Outlook o el tuyo), en sólo lectura: no marca nada como leído."
    intervalo = 300

    def disponible(self) -> str | None:
        # Sólo si existe, sin leerlo: esto lo pinta también `hub-web`, que no
        # debe abrir las llaves de las fuentes (decisión 298; C-0183). Si está
        # a medias, lo dice `leer`, que corre en `hub-secretario`.
        if not (carpeta() / "cuenta.env").is_file():
            return (f"falta {carpeta() / 'cuenta.env'} con IMAP_SERVIDOR, IMAP_USUARIO e IMAP_CLAVE; "
                    "lo crea: uv run python -m hub.secretario correo-entrar")
        return None

    def leer(self, cursor: str, ajustes: dict) -> tuple[list[Evento], str]:
        c = cuenta(ajustes)
        if not c:
            raise RuntimeError(self.disponible() or
                               f"{carpeta(ajustes) / 'cuenta.env'} está a medias: necesita IMAP_SERVIDOR, "
                               "IMAP_USUARIO e IMAP_CLAVE (correo-entrar lo rehace)")
        estado = json.loads(cursor) if cursor else {}
        buzones = ajustes.get("buzones") or ["INBOX"]
        propias = {c["IMAP_USUARIO"].lower(), *[x.lower() for x in ajustes.get("direcciones_propias") or []]}
        # Por fragmento y no por nombre exacto: «github.com» o «Ana» bastan.
        incluir = [x.lower() for x in ajustes.get("incluir") or []]
        excluir = [x.lower() for x in ajustes.get("excluir") or []]
        eventos: list[Evento] = []
        m = conectar(c)
        try:
            for buzon in buzones:
                tipo, datos = m.select(_entre_comillas(buzon), readonly=True)
                if tipo != "OK":
                    raise RuntimeError(f"no se pudo abrir el buzón «{buzon}»: {datos}")
                validez = (m.response("UIDVALIDITY")[1] or [b""])[0]
                validez = validez.decode() if isinstance(validez, bytes) else str(validez)
                previo = estado.get(buzon) or {}
                # El cursor sólo vale si el servidor no renumeró el buzón (UIDVALIDITY).
                base = int(previo.get("uid") or 0) if previo.get("validez") == validez else 0
                if base:
                    criterio = f"UID {base + 1}:*"
                else:
                    # Primera vez, o el servidor renumeró el buzón: los últimos días.
                    desde = (datetime.now(timezone.utc) - timedelta(days=DIAS_AL_EMPEZAR)).strftime("%d-%b-%Y")
                    criterio = f"SINCE {desde}"
                tipo, datos = m.uid("SEARCH", None, criterio)
                # `UID n:*` devuelve siempre el último aunque sea anterior a n.
                uids = [u for u in (datos[0] or b"").split() if int(u) > base]
                ultimo = base
                for uid in uids[-POR_LECTURA:]:
                    tipo, partes = m.uid("FETCH", uid, "(BODY.PEEK[])")
                    crudo = next((p[1] for p in partes if isinstance(p, tuple)), None)
                    ultimo = max(ultimo, int(uid))
                    if not crudo:
                        continue
                    ev, masivo = evento(crudo, uid.decode(), buzon, propias)
                    remitente = ev.conversacion.lower()
                    pedido = any(x in remitente for x in incluir)
                    if (incluir and not pedido) or (masivo and not pedido) or any(x in remitente for x in excluir):
                        continue
                    eventos.append(ev)
                estado[buzon] = {"validez": validez, "uid": ultimo}
        finally:
            try:
                m.logout()
            except Exception:  # noqa: BLE001
                pass
        return eventos, json.dumps(estado)


def _entre_comillas(buzon: str) -> str:
    return buzon if buzon.upper() == "INBOX" else '"' + buzon.replace('"', '\\"') + '"'


def entrar() -> None:  # pragma: no cover - interactivo
    """Pide los datos, prueba a entrar y sólo entonces los guarda."""
    import getpass
    print("Para Gmail: servidor imap.gmail.com y una contraseña de aplicación\n"
          "(Cuenta de Google → Seguridad → Contraseñas de aplicaciones; hace falta la verificación en dos pasos).\n")
    servidor = input("Servidor IMAP [imap.gmail.com]: ").strip() or "imap.gmail.com"
    usuario = input("Usuario (tu correo): ").strip()
    clave = getpass.getpass("Contraseña de aplicación: ").replace(" ", "")
    c = {"IMAP_SERVIDOR": servidor, "IMAP_USUARIO": usuario, "IMAP_CLAVE": clave}
    m = conectar(c)
    tipo, buzones = m.list()
    m.logout()
    d = carpeta({})
    d.mkdir(parents=True, exist_ok=True)
    os.chmod(d, 0o700)
    ruta = d / "cuenta.env"
    ruta.write_text("".join(f"{k}={v}\n" for k, v in c.items()), encoding="utf-8")
    os.chmod(ruta, 0o600)
    print(f"Conectado ({len(buzones or [])} buzones). Guardado en {ruta}. Enciéndela en Ajustes → Fuentes.")


FUENTE = FuenteCorreo()
