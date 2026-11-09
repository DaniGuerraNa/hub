"""Proveedor de agenda: Google Calendar sin librerías de Google (definición 4.2, decisión 304).

Con `urllib` y nada más: el cliente oficial arrastra decenas de paquetes para
dos llamadas (listar y crear eventos) y un intercambio de tokens.

Entrar es el flujo OAuth de «aplicación instalada» con redirección a
`127.0.0.1` y PKCE: el dueño crea un cliente de tipo *Escritorio* en Google
Cloud, deja su `cliente.json` en la carpeta de credenciales y corre
`uv run python -m hub.secretario google-entrar`. Con el hub en otra máquina,
la dirección de vuelta se pega en esa misma terminal (C-0214).

🔴 **El `refresh_token` es una llave de su calendario** (regla dura 5): vive en
`~/.secretos/secretario-google/` con permisos 600, fuera de `HUB_HOME`, y sólo
lo lee `hub-secretario`.
"""

from __future__ import annotations

import base64
import hashlib
import http.server
import json
import os
import secrets
import select
import socketserver
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from typing import TextIO

from ..tiempo import zona
from ... import llavero
from . import Calendario

ALCANCE = "https://www.googleapis.com/auth/calendar.events"
API = "https://www.googleapis.com/calendar/v3"
TOKEN_URL = "https://oauth2.googleapis.com/token"


def carpeta() -> Path:
    return Path(os.environ.get("HUB_SECRETARIO_GOOGLE", "~/.secretos/secretario-google")).expanduser()


#: Para el inventario del llavero (C-0143): dónde vive, nunca el valor.
LLAVES = (llavero.Llave("secretario-google", "el acceso a tu Google (agenda)", lambda: str(carpeta())),)


class SinGoogle(RuntimeError):
    """No está conectado. Lleva dentro qué falta, dicho para el dueño."""



def _cliente() -> dict:
    try:
        datos = json.loads((carpeta() / "cliente.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SinGoogle(f"falta {carpeta() / 'cliente.json'} (cliente OAuth de tipo Escritorio)") from exc
    return datos.get("installed") or datos.get("web") or datos


def disponible() -> str | None:
    if not (carpeta() / "cliente.json").is_file():
        return f"falta {carpeta() / 'cliente.json'}: crea un cliente OAuth «Escritorio» en Google Cloud"
    if not (carpeta() / "token.json").is_file():
        return "falta entrar: uv run python -m hub.secretario google-entrar"
    return None


def _post(url: str, datos: dict) -> dict:
    cuerpo = urllib.parse.urlencode(datos).encode()
    with urllib.request.urlopen(urllib.request.Request(url, data=cuerpo), timeout=20) as r:
        return json.loads(r.read())


def _token() -> str:
    """Un token de acceso válido, renovándolo con el `refresh_token` si caducó."""
    if disponible():
        raise SinGoogle(disponible())
    ruta = carpeta() / "token.json"
    tok = json.loads(ruta.read_text(encoding="utf-8"))
    if tok.get("access_token") and tok.get("caduca", 0) > time.time() + 60:
        return tok["access_token"]
    c = _cliente()
    try:
        nuevo = _post(TOKEN_URL, {"client_id": c["client_id"], "client_secret": c.get("client_secret", ""),
                                  "refresh_token": tok["refresh_token"], "grant_type": "refresh_token"})
    except urllib.error.HTTPError as exc:
        raise SinGoogle(f"Google no renovó el acceso ({exc.code}): vuelve a entrar (google-entrar)") from exc
    tok["access_token"] = nuevo["access_token"]
    tok["caduca"] = time.time() + int(nuevo.get("expires_in", 3600))
    ruta.write_text(json.dumps(tok), encoding="utf-8")
    os.chmod(ruta, 0o600)
    return tok["access_token"]


def _api(metodo: str, camino: str, cuerpo: dict | None = None, consulta: dict | None = None) -> dict:
    url = API + camino + ("?" + urllib.parse.urlencode(consulta) if consulta else "")
    datos = json.dumps(cuerpo).encode() if cuerpo is not None else None
    req = urllib.request.Request(url, data=datos, method=metodo,
                                 headers={"Authorization": f"Bearer {_token()}",
                                          "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"Google Calendar respondió {exc.code}: {exc.read()[:300]!r}") from exc


def eventos(desde: datetime, hasta: datetime, n: int = 50) -> list[dict]:
    d = _api("GET", "/calendars/primary/events", consulta={
        "timeMin": desde.isoformat(), "timeMax": hasta.isoformat(), "singleEvents": "true",
        "orderBy": "startTime", "maxResults": n})
    out = []
    for e in d.get("items", []):
        ini, fin = e.get("start", {}), e.get("end", {})
        out.append({"id": e.get("id"), "titulo": e.get("summary", ""),
                    "inicio": ini.get("dateTime") or ini.get("date"), "fin": fin.get("dateTime") or fin.get("date"),
                    "lugar": e.get("location", ""), "enlace": e.get("htmlLink", "")})
    return out


def crear(titulo: str, inicio: str, fin: str | None = None, descripcion: str = "",
          minutos_aviso: int = 30) -> dict:
    """Un evento en el calendario principal, y lo que Google dice que creó.

    `inicio` es `AAAA-MM-DD` (todo el día) o `AAAA-MM-DDTHH:MM` en hora local.
    Se devuelve lo que contestó Google —su id y su enlace—: eso es comprobar
    que existe (regla dura 17), no suponerlo porque no hubo error.
    """
    z = zona()
    if len(inicio) == 10:
        dia = datetime.fromisoformat(inicio).date()
        cuerpo = {"start": {"date": dia.isoformat()}, "end": {"date": (dia + timedelta(days=1)).isoformat()}}
    else:
        a = datetime.fromisoformat(inicio)
        b = datetime.fromisoformat(fin) if fin else a + timedelta(minutes=30)
        cuerpo = {"start": {"dateTime": a.replace(tzinfo=None).isoformat(), "timeZone": z},
                  "end": {"dateTime": b.replace(tzinfo=None).isoformat(), "timeZone": z}}
    cuerpo |= {"summary": titulo, "description": descripcion,
               "reminders": {"useDefault": False, "overrides": [{"method": "popup", "minutes": minutos_aviso}]}}
    e = _api("POST", "/calendars/primary/events", cuerpo)
    if not e.get("id"):
        raise RuntimeError("Google no devolvió el evento creado")
    return {"id": e["id"], "enlace": e.get("htmlLink", ""), "titulo": titulo, "inicio": inicio}



class _Vuelta(http.server.BaseHTTPRequestHandler):
    """La página a la que Google devuelve al navegador tras aceptar."""

    def do_GET(self):  # noqa: N802
        self.server.recibido.update(_de_la_direccion(self.path))
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write("Listo, ya puedes cerrar esta pestaña.".encode())

    def log_message(self, *a):
        pass


def _de_la_direccion(texto: str) -> dict[str, str]:
    """Los parámetros de la vuelta, de la dirección entera o sólo de su `?…`."""
    texto = texto.strip()
    consulta = urllib.parse.urlparse(texto).query or texto.lstrip("/?")
    return {k: v[0] for k, v in urllib.parse.parse_qs(consulta).items()}


def _esperar_vuelta(srv: socketserver.TCPServer, entrada: TextIO | None) -> dict[str, str]:
    """Lo primero que llegue: el navegador a `127.0.0.1`, o la dirección pegada.

    🔴 Con el hub en una máquina sin monitor (C-0214) el navegador está en otra
    PC, y su `127.0.0.1` no es esta máquina: tras aceptar, Google lo manda a una
    página que no carga. La dirección de esa página lleva el código, así que se
    copia y se pega aquí. El `state` y el PKCE son los mismos por los dos
    caminos: pegar no se salta ninguna comprobación.
    """
    srv.recibido = {}
    # Sin descriptor 0 (lanzado sin terminal), `sys.stdin` es None: sólo el navegador.
    fuentes: list = [srv] + ([entrada.fileno()] if entrada is not None else [])
    while "code" not in srv.recibido and "error" not in srv.recibido:
        listos, _, _ = select.select(fuentes, [], [])
        if srv in listos:
            srv.handle_request()
            continue
        # Del descriptor y no con `readline`: varias líneas pegadas de golpe se
        # quedarían en el búfer del archivo, donde `select` no las ve.
        trozo = os.read(fuentes[1], 65536)
        if not trozo:              # entrada cerrada o `/dev/null`: sólo el navegador
            fuentes.pop()
            continue
        for linea in trozo.decode("utf-8", "replace").splitlines():
            srv.recibido.update(_de_la_direccion(linea))
    return srv.recibido


def entrar() -> None:  # pragma: no cover - interactivo: espera al navegador del dueño
    """OAuth de aplicación instalada, con redirección a 127.0.0.1 y PKCE."""
    c = _cliente()
    carpeta().mkdir(parents=True, exist_ok=True)
    os.chmod(carpeta(), 0o700)
    verificador = secrets.token_urlsafe(64)
    reto = base64.urlsafe_b64encode(hashlib.sha256(verificador.encode()).digest()).rstrip(b"=").decode()
    estado = secrets.token_urlsafe(16)

    with socketserver.TCPServer(("127.0.0.1", 0), _Vuelta) as srv:
        puerto = srv.server_address[1]
        redir = f"http://127.0.0.1:{puerto}/"
        url = "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode({
            "client_id": c["client_id"], "redirect_uri": redir, "response_type": "code", "scope": ALCANCE,
            "access_type": "offline", "prompt": "consent", "state": estado,
            "code_challenge": reto, "code_challenge_method": "S256"})
        print("Abre esto en el navegador y acepta:\n\n" + url + "\n")
        print("Si el navegador está en otra máquina, al aceptar acabarás en una página que no "
              f"carga ({redir}…): copia la dirección entera de la barra, pégala aquí y pulsa "
              "Enter.\n", flush=True)
        recibido = _esperar_vuelta(srv, sys.stdin)
    if recibido.get("state") != estado or "code" not in recibido:
        raise SystemExit(f"no se pudo entrar: {recibido.get('error', 'respuesta inesperada')}")
    tok = _post(TOKEN_URL, {"client_id": c["client_id"], "client_secret": c.get("client_secret", ""),
                            "code": recibido["code"], "code_verifier": verificador,
                            "redirect_uri": redir, "grant_type": "authorization_code"})
    ruta = carpeta() / "token.json"
    ruta.write_text(json.dumps({"refresh_token": tok["refresh_token"], "access_token": tok["access_token"],
                                "caduca": time.time() + int(tok.get("expires_in", 3600))}), encoding="utf-8")
    os.chmod(ruta, 0o600)
    print(f"Conectado. El acceso está en {ruta}.")


class CalendarioGoogle(Calendario):
    id = "google"
    nombre = "Google Calendar"

    def disponible(self):
        return disponible()

    def eventos(self, desde, hasta, n=50):
        return eventos(desde, hasta, n)

    def crear(self, titulo, inicio, fin=None, descripcion="", minutos_aviso=30):
        return crear(titulo, inicio, fin, descripcion, minutos_aviso)

    def entrar(self):  # pragma: no cover - interactivo
        entrar()


PROVEEDOR = CalendarioGoogle()
