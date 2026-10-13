"""El chat web de encargos: la misma conversación que por Telegram, en una página.

🔴 Corre en el SERVIDOR, no en la casa (regla dura 8: la casa no sirve). Es un
buzón con dos puertas:

- La de la persona: entra con usuario y contraseña, ve su conversación, escribe,
  graba un audio, pulsa un botón. Todo por sesión (cookie).
- La del hub: con un token, recoge lo que entró (como `getUpdates`), deja lo
  que sale, sube fotos, marca «escribiendo…». La conexión la abre el hub, igual
  que con Telegram: aquí no se llama a nadie.

Los ids de mensaje son enteros por lo mismo que en Telegram: el relé aprueba
«respondiendo a ESE mensaje», y los botones llevan el id del mensaje bajo el
que estaban. Las contraseñas se guardan como hash bcrypt y las genera el hub.
"""

from __future__ import annotations

import os
import secrets
import sqlite3
import time
from pathlib import Path

import bcrypt
from fastapi import Cookie, Depends, FastAPI, File, Form, Header, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

AQUI = Path(__file__).resolve().parent
DATOS = Path(os.environ.get("DATOS", str(AQUI / "datos-local")))
DATOS.mkdir(parents=True, exist_ok=True)
MEDIOS = DATOS / "medios"
MEDIOS.mkdir(exist_ok=True)
BASE = DATOS / "chat.db"
TOKEN = os.environ.get("CHAT_TOKEN", "")
# Los ids de persona nacen aquí y no chocan con los de Telegram, que son
# menores: el relé los trata como user_id igual que a los otros.
PRIMER_USER_ID = 900_000_000
ESCRIBIENDO_SEGUNDOS = 6

ESQUEMA = """
CREATE TABLE IF NOT EXISTS persona (
    user_id INTEGER PRIMARY KEY,
    usuario TEXT NOT NULL UNIQUE,
    nombre  TEXT NOT NULL DEFAULT '',
    hash    TEXT NOT NULL,
    creado  REAL NOT NULL,
    escribiendo_hasta REAL NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS sesion (
    token   TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL,
    creado  REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS mensaje (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id   INTEGER NOT NULL,
    direccion TEXT NOT NULL,           -- entra (ella) | sale (hub)
    texto     TEXT NOT NULL DEFAULT '',
    medio     TEXT NOT NULL DEFAULT '', -- archivo en MEDIOS
    tipo      TEXT NOT NULL DEFAULT 'texto', -- texto | audio | foto
    botones   TEXT NOT NULL DEFAULT '', -- JSON [[etiqueta, dato], ...]
    creado    REAL NOT NULL
);
-- Lo que el hub todavía no recogió: mensajes de ella y botones pulsados.
CREATE TABLE IF NOT EXISTS evento (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL,
    clase      TEXT NOT NULL,           -- mensaje | boton
    mensaje_id INTEGER,                 -- el mensaje de ella, o el de los botones
    dato       TEXT NOT NULL DEFAULT '',
    creado     REAL NOT NULL
);
"""


def con() -> sqlite3.Connection:
    c = sqlite3.connect(BASE)
    c.row_factory = sqlite3.Row
    return c


with con() as _c:
    _c.executescript(ESQUEMA)
    # Lo que el hub ya confirmó haber visto (pidiendo desde un id mayor): un
    # relé que se reinicia pide «desde 0» y sólo debe recibir lo pendiente,
    # como pasa con el offset de Telegram.
    try:
        _c.execute("ALTER TABLE evento ADD COLUMN visto INTEGER NOT NULL DEFAULT 0")
    except sqlite3.OperationalError:
        pass

app = FastAPI(title="chat de encargos")


# ── Quién habla ──────────────────────────────────────────────────────────────


def hub(authorization: str = Header(default="")) -> None:
    if not TOKEN or authorization != f"Bearer {TOKEN}":
        raise HTTPException(401, "token")


def persona(sesion: str = Cookie(default="")) -> dict:
    if not sesion:
        raise HTTPException(401, "sin sesión")
    with con() as c:
        fila = c.execute(
            "SELECT p.* FROM sesion s JOIN persona p ON p.user_id = s.user_id WHERE s.token = ?",
            (sesion,)).fetchone()
    if not fila:
        raise HTTPException(401, "sesión caducada")
    return dict(fila)


# ── La puerta de la persona ──────────────────────────────────────────────────


@app.get("/", response_class=HTMLResponse)
def portada() -> str:
    return (AQUI / "static" / "index.html").read_text(encoding="utf-8")


@app.get("/salud")
def salud() -> dict:
    return {"ok": True}


@app.post("/entrar")
def entrar(request: Request, response: Response, usuario: str = Form(...), clave: str = Form(...)) -> dict:
    with con() as c:
        fila = c.execute("SELECT * FROM persona WHERE usuario = ?", (usuario.strip().lower(),)).fetchone()
        if not fila or not bcrypt.checkpw(clave.encode("utf-8"), fila["hash"].encode("ascii")):
            # Un fallo se responde igual haya o no usuario: no se enumera.
            time.sleep(0.4)
            raise HTTPException(401, "usuario o contraseña incorrectos")
        token = secrets.token_urlsafe(32)
        c.execute("INSERT INTO sesion (token, user_id, creado) VALUES (?, ?, ?)",
                  (token, fila["user_id"], time.time()))
    # `secure` sólo cuando de verdad va por HTTPS (detrás de Caddy lo va; en
    # las pruebas y en local no): si no, la cookie no vuelve y nadie entra.
    response.set_cookie("sesion", token, httponly=True, samesite="lax",
                        secure=(request.url.scheme == "https"), max_age=60 * 60 * 24 * 30)
    return {"ok": True, "nombre": fila["nombre"]}


@app.post("/salir")
def salir(response: Response, sesion: str = Cookie(default="")) -> dict:
    with con() as c:
        c.execute("DELETE FROM sesion WHERE token = ?", (sesion,))
    response.delete_cookie("sesion")
    return {"ok": True}


@app.get("/api/yo")
def yo(p: dict = Depends(persona)) -> dict:
    return {"user_id": p["user_id"], "nombre": p["nombre"], "usuario": p["usuario"]}


@app.get("/api/mensajes")
def mensajes(desde: int = 0, p: dict = Depends(persona)) -> dict:
    with con() as c:
        filas = c.execute(
            "SELECT id, direccion, texto, medio, tipo, botones, creado FROM mensaje "
            "WHERE user_id = ? AND id > ? ORDER BY id", (p["user_id"], desde)).fetchall()
        hasta = c.execute("SELECT escribiendo_hasta FROM persona WHERE user_id = ?",
                          (p["user_id"],)).fetchone()[0]
    return {"mensajes": [dict(f) for f in filas], "escribiendo": time.time() < hasta}


@app.post("/api/mensajes")
async def escribe(p: dict = Depends(persona), texto: str = Form(default=""),
                  audio: UploadFile | None = File(default=None)) -> dict:
    texto = (texto or "").strip()
    medio, tipo = "", "texto"
    if audio is not None:
        cuerpo = await audio.read()
        if not cuerpo:
            raise HTTPException(400, "audio vacío")
        if len(cuerpo) > 25 * 1024 * 1024:
            raise HTTPException(413, "audio demasiado grande")
        nombre = f"{p['user_id']}-{int(time.time() * 1000)}.webm"
        (MEDIOS / nombre).write_bytes(cuerpo)
        medio, tipo = nombre, "audio"
    elif not texto:
        raise HTTPException(400, "nada que mandar")
    with con() as c:
        cur = c.execute(
            "INSERT INTO mensaje (user_id, direccion, texto, medio, tipo, creado) VALUES (?, 'entra', ?, ?, ?, ?)",
            (p["user_id"], texto, medio, tipo, time.time()))
        mid = cur.lastrowid
        c.execute("INSERT INTO evento (user_id, clase, mensaje_id, dato, creado) VALUES (?, 'mensaje', ?, '', ?)",
                  (p["user_id"], mid, time.time()))
    return {"id": mid}


@app.post("/api/botones")
def pulsa(p: dict = Depends(persona), mensaje_id: int = Form(...), dato: str = Form(...)) -> dict:
    with con() as c:
        fila = c.execute("SELECT botones FROM mensaje WHERE id = ? AND user_id = ? AND direccion = 'sale'",
                         (mensaje_id, p["user_id"])).fetchone()
        if not fila or not fila["botones"]:
            raise HTTPException(404, "ese mensaje no tiene botones")
        c.execute("INSERT INTO evento (user_id, clase, mensaje_id, dato, creado) VALUES (?, 'boton', ?, ?, ?)",
                  (p["user_id"], mensaje_id, dato, time.time()))
    return {"ok": True}


@app.get("/medios/{nombre}")
def medio(nombre: str, p: dict = Depends(persona)) -> FileResponse:
    ruta = _medio_de(nombre, p["user_id"])
    return FileResponse(ruta)


def _medio_de(nombre: str, user_id: int | None) -> Path:
    if "/" in nombre or nombre.startswith(".") or not (MEDIOS / nombre).is_file():
        raise HTTPException(404, "no existe")
    if user_id is not None and not nombre.startswith(f"{user_id}-"):
        raise HTTPException(404, "no existe")
    return MEDIOS / nombre


# ── La puerta del hub ────────────────────────────────────────────────────────


@app.post("/hub/personas", dependencies=[Depends(hub)])
def alta(usuario: str = Form(...), nombre: str = Form(default=""), hash: str = Form(...)) -> dict:
    usuario = usuario.strip().lower()
    if not usuario.replace("-", "").replace("_", "").isalnum():
        raise HTTPException(400, "usuario: letras, números, guiones")
    with con() as c:
        if c.execute("SELECT 1 FROM persona WHERE usuario = ?", (usuario,)).fetchone():
            raise HTTPException(409, "ese usuario ya existe")
        siguiente = (c.execute("SELECT MAX(user_id) FROM persona").fetchone()[0] or PRIMER_USER_ID - 1) + 1
        c.execute("INSERT INTO persona (user_id, usuario, nombre, hash, creado) VALUES (?, ?, ?, ?, ?)",
                  (siguiente, usuario, nombre.strip(), hash, time.time()))
    return {"user_id": siguiente, "usuario": usuario}


@app.post("/hub/personas/{user_id}/nombre", dependencies=[Depends(hub)])
def renombrar(user_id: int, nombre: str = Form(...)) -> dict:
    with con() as c:
        if not c.execute("UPDATE persona SET nombre = ? WHERE user_id = ?", (nombre.strip(), user_id)).rowcount:
            raise HTTPException(404, "no existe")
    return {"ok": True}


@app.post("/hub/personas/{user_id}/clave", dependencies=[Depends(hub)])
def nueva_clave(user_id: int, hash: str = Form(...)) -> dict:
    with con() as c:
        if not c.execute("UPDATE persona SET hash = ? WHERE user_id = ?", (hash, user_id)).rowcount:
            raise HTTPException(404, "no existe")
        c.execute("DELETE FROM sesion WHERE user_id = ?", (user_id,))
    return {"ok": True}


@app.get("/hub/actualizaciones", dependencies=[Depends(hub)])
def actualizaciones(desde: int = 0) -> dict:
    """Lo que entró a partir de `desde` (INCLUSIVE, como el offset de Telegram).

    🔴 Inclusive y no exclusivo: el relé guarda «último visto + 1» y pide desde
    ahí. Con `>` se saltaba justo el evento siguiente —el primer audio real por
    la web se quedó en el servidor sin que el hub lo viera nunca—.
    """
    with con() as c:
        # Pedir desde N confirma todo lo anterior a N, como el offset de Telegram.
        if desde:
            c.execute("UPDATE evento SET visto = 1 WHERE id < ?", (desde,))
        eventos = c.execute("SELECT * FROM evento WHERE id >= ? AND visto = 0 ORDER BY id LIMIT 100",
                            (desde,)).fetchall()
        salida = []
        for e in eventos:
            p = c.execute("SELECT usuario, nombre FROM persona WHERE user_id = ?", (e["user_id"],)).fetchone()
            de = {"id": e["user_id"], "username": p["usuario"] if p else "", "first_name": p["nombre"] if p else ""}
            if e["clase"] == "boton":
                salida.append({"update_id": e["id"], "callback_query": {
                    "id": f"web{e['id']}", "from": de, "data": e["dato"],
                    "message": {"message_id": e["mensaje_id"], "chat": {"id": e["user_id"]}}}})
                continue
            m = c.execute("SELECT * FROM mensaje WHERE id = ?", (e["mensaje_id"],)).fetchone()
            if not m:
                continue
            mensaje = {"message_id": m["id"], "from": de, "chat": {"id": e["user_id"]}}
            if m["tipo"] == "audio":
                mensaje["voice"] = {"file_id": f"web:{m['medio']}", "duration": 0}
            else:
                mensaje["text"] = m["texto"]
            salida.append({"update_id": e["id"], "message": mensaje})
    return {"result": salida}


@app.post("/hub/mensajes", dependencies=[Depends(hub)])
def manda(user_id: int = Form(...), texto: str = Form(...), botones: str = Form(default="")) -> dict:
    with con() as c:
        if not c.execute("SELECT 1 FROM persona WHERE user_id = ?", (user_id,)).fetchone():
            raise HTTPException(404, "no existe esa persona")
        cur = c.execute(
            "INSERT INTO mensaje (user_id, direccion, texto, tipo, botones, creado) VALUES (?, 'sale', ?, 'texto', ?, ?)",
            (user_id, texto, botones, time.time()))
        c.execute("UPDATE persona SET escribiendo_hasta = 0 WHERE user_id = ?", (user_id,))
    return {"message_id": cur.lastrowid}


@app.post("/hub/fotos", dependencies=[Depends(hub)])
async def manda_foto(user_id: int = Form(...), pie: str = Form(default=""), foto: UploadFile = File(...)) -> dict:
    cuerpo = await foto.read()
    nombre = f"hub-{user_id}-{int(time.time() * 1000)}-{secrets.token_hex(3)}.png"
    (MEDIOS / nombre).write_bytes(cuerpo)
    with con() as c:
        cur = c.execute(
            "INSERT INTO mensaje (user_id, direccion, texto, medio, tipo, creado) VALUES (?, 'sale', ?, ?, 'foto', ?)",
            (user_id, pie, nombre, time.time()))
    return {"message_id": cur.lastrowid}


@app.post("/hub/escribiendo", dependencies=[Depends(hub)])
def escribiendo(user_id: int = Form(...)) -> dict:
    with con() as c:
        c.execute("UPDATE persona SET escribiendo_hasta = ? WHERE user_id = ?",
                  (time.time() + ESCRIBIENDO_SEGUNDOS, user_id))
    return {"ok": True}


@app.post("/hub/quitar_botones", dependencies=[Depends(hub)])
def quitar_botones(user_id: int = Form(...), message_id: int = Form(...)) -> dict:
    with con() as c:
        c.execute("UPDATE mensaje SET botones = '' WHERE id = ? AND user_id = ?", (message_id, user_id))
    return {"ok": True}


@app.get("/hub/medios/{nombre}", dependencies=[Depends(hub)])
def medio_hub(nombre: str) -> FileResponse:
    return FileResponse(_medio_de(nombre, None))


@app.get("/medios-hub/{nombre}")
def foto_para_ella(nombre: str, p: dict = Depends(persona)) -> FileResponse:
    """Las fotos que mandó el hub a ESTA persona."""
    if not nombre.startswith(f"hub-{p['user_id']}-"):
        raise HTTPException(404, "no existe")
    return FileResponse(_medio_de(nombre, None))
