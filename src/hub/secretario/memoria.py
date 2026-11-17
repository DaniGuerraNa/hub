"""La memoria del secretario: lo que sabe, fuera de cualquier conversación.

🔴 **Base propia, no `hub.db`** (decisión 299). Crece mucho más rápido —cada
mensaje de cada fuente— y es mucho más sensible: dentro van chats enteros. Se
respalda igual que `hub.db` pero aparte (`copia_base` la incluye), y casi todo
lo que guarda **sólo vive aquí** (regla dura 1): los eventos se podrían volver a
leer de algunas fuentes, pero las notas, los compromisos y lo que el dueño
corrigió no se reconstruyen de ningún sitio. Por eso esta base no se borra nunca
para «probar que se rehace».

Búsqueda con FTS5, que viene con SQLite y no añade dependencias. La búsqueda
semántica (vectores) espera a que FTS se quede corto con preguntas reales:
medir antes de complicar.
"""

from __future__ import annotations

import functools
import hashlib
import json
import re
import sqlite3
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from .. import config
from ..db import TOPE_DEL_WAL, transaccion
from ..reloj import ahora

ESQUEMA = """
-- Lo que llegó de cada fuente, tal cual. `id_externo` evita duplicar al releer.
CREATE TABLE IF NOT EXISTS evento (
    id            INTEGER PRIMARY KEY,
    fuente        TEXT NOT NULL,
    id_externo    TEXT NOT NULL,
    conversacion  TEXT NOT NULL DEFAULT '',
    autor         TEXT NOT NULL DEFAULT '',
    fecha         TEXT NOT NULL,
    texto         TEXT NOT NULL DEFAULT '',
    adjuntos      TEXT NOT NULL DEFAULT '[]',
    enlace        TEXT NOT NULL DEFAULT '',
    recibido      TEXT NOT NULL,
    -- 0 por leer, 1 leído por el triaje, 2 apartado tras tres fallos,
    -- 3 descartado por el filtro sin llamar al modelo (decisión 308),
    -- 4 apartado sin leer porque el dueño pidió empezar limpio desde una fecha.
    triado        INTEGER NOT NULL DEFAULT 0,
    -- A quién va (decisión 332): privado, etiqueta, nombre, otros o vacío.
    para_mi       TEXT NOT NULL DEFAULT '',
    UNIQUE (fuente, id_externo)
);
CREATE INDEX IF NOT EXISTS evento_sin_triar ON evento (triado, id);
CREATE INDEX IF NOT EXISTS evento_fecha ON evento (fecha);

CREATE VIRTUAL TABLE IF NOT EXISTS evento_fts USING fts5(
    texto, autor, conversacion, content='evento', content_rowid='id',
    tokenize='unicode61 remove_diacritics 2'
);
CREATE TRIGGER IF NOT EXISTS evento_ai AFTER INSERT ON evento BEGIN
    INSERT INTO evento_fts(rowid, texto, autor, conversacion)
    VALUES (new.id, new.texto, new.autor, new.conversacion);
END;
CREATE TRIGGER IF NOT EXISTS evento_ad AFTER DELETE ON evento BEGIN
    INSERT INTO evento_fts(evento_fts, rowid, texto, autor, conversacion)
    VALUES ('delete', old.id, old.texto, old.autor, old.conversacion);
END;

-- 🔴 Sólo vive aquí. Lo que el triaje o una conversación sacó en limpio.
CREATE TABLE IF NOT EXISTS nota (
    id        INTEGER PRIMARY KEY,
    texto     TEXT NOT NULL,
    tema      TEXT NOT NULL DEFAULT '',
    evento    INTEGER REFERENCES evento(id) ON DELETE SET NULL,
    origen    TEXT NOT NULL DEFAULT '',
    creada    TEXT NOT NULL,
    editada   TEXT
);
CREATE VIRTUAL TABLE IF NOT EXISTS nota_fts USING fts5(
    texto, tema, origen, content='nota', content_rowid='id',
    tokenize='unicode61 remove_diacritics 2'
);
CREATE TRIGGER IF NOT EXISTS nota_ai AFTER INSERT ON nota BEGIN
    INSERT INTO nota_fts(rowid, texto, tema, origen) VALUES (new.id, new.texto, new.tema, new.origen);
END;
CREATE TRIGGER IF NOT EXISTS nota_ad AFTER DELETE ON nota BEGIN
    INSERT INTO nota_fts(nota_fts, rowid, texto, tema, origen)
    VALUES ('delete', old.id, old.texto, old.tema, old.origen);
END;
CREATE TRIGGER IF NOT EXISTS nota_au AFTER UPDATE ON nota BEGIN
    INSERT INTO nota_fts(nota_fts, rowid, texto, tema, origen)
    VALUES ('delete', old.id, old.texto, old.tema, old.origen);
    INSERT INTO nota_fts(rowid, texto, tema, origen) VALUES (new.id, new.texto, new.tema, new.origen);
END;

-- 🔴 Sólo vive aquí y no se reconstruye: cuántas veces se le sirvió cada nota
-- al modelo y cuándo la última (`apuntar_lectura`, C-0424). Perderla pierde la
-- cuenta, no las notas. Aparte de `nota` a propósito: una columna allí haría
-- saltar `nota_au` —y reescribir el índice de texto— en cada búsqueda. Desde
-- cuándo se cuenta va en `estado` (`USO_DESDE`); borrar la nota se lleva su fila.
CREATE TABLE IF NOT EXISTS nota_uso (
    nota    INTEGER PRIMARY KEY REFERENCES nota(id) ON DELETE CASCADE,
    veces   INTEGER NOT NULL DEFAULT 0,
    ultima  TEXT NOT NULL
);

-- 🔴 Sólo vive aquí. «Voy a hacer X» (quien = 'yo') o «te pido X» (quien = otro).
CREATE TABLE IF NOT EXISTS compromiso (
    id           INTEGER PRIMARY KEY,
    quien        TEXT NOT NULL DEFAULT 'yo',
    para_quien   TEXT NOT NULL DEFAULT '',
    que          TEXT NOT NULL,
    vence        TEXT,
    recordar_en  TEXT,
    recordado    TEXT,
    estado       TEXT NOT NULL DEFAULT 'abierto',
    evento       INTEGER REFERENCES evento(id) ON DELETE SET NULL,
    origen       TEXT NOT NULL DEFAULT '',
    calendario   TEXT,
    creado       TEXT NOT NULL,
    cerrado      TEXT
);
CREATE INDEX IF NOT EXISTS compromiso_abierto ON compromiso (estado, recordar_en);

-- 🔴 Sólo vive aquí. La misma persona en varias fuentes.
CREATE TABLE IF NOT EXISTS persona (
    id      INTEGER PRIMARY KEY,
    nombre  TEXT NOT NULL UNIQUE,
    alias   TEXT NOT NULL DEFAULT '[]',
    nota    TEXT NOT NULL DEFAULT ''
);

-- Cada conversación con el dueño. `sesion` es la de `claude -p` mientras el
-- hilo está abierto; al cerrarse queda el resumen y la sesión ya no se usa.
CREATE TABLE IF NOT EXISTS hilo (
    id        INTEGER PRIMARY KEY,
    abierto   TEXT NOT NULL,
    ultimo    TEXT NOT NULL,
    cerrado   TEXT,
    sesion    TEXT,
    resumen   TEXT NOT NULL DEFAULT '',
    titulo    TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS turno (
    id        INTEGER PRIMARY KEY,
    hilo      INTEGER NOT NULL REFERENCES hilo(id) ON DELETE CASCADE,
    rol       TEXT NOT NULL,
    texto     TEXT NOT NULL DEFAULT '',
    tarjetas  TEXT NOT NULL DEFAULT '[]',
    estado    TEXT NOT NULL DEFAULT 'listo',
    modelo    TEXT NOT NULL DEFAULT '',
    pantalla  TEXT NOT NULL DEFAULT '',
    creado    TEXT NOT NULL,
    segundos  REAL
);
CREATE INDEX IF NOT EXISTS turno_pendiente ON turno (estado, id);

-- Lo que una acción en `ask` espera del dueño (8.2).
CREATE TABLE IF NOT EXISTS solicitud (
    id         INTEGER PRIMARY KEY,
    accion     TEXT NOT NULL,
    params     TEXT NOT NULL DEFAULT '{}',
    motivo     TEXT NOT NULL DEFAULT '',
    estado     TEXT NOT NULL DEFAULT 'pendiente',
    hilo       INTEGER,
    creada     TEXT NOT NULL,
    resuelta   TEXT,
    resultado  TEXT NOT NULL DEFAULT ''
);

-- 🔴 Sólo vive aquí. Todo lo que hizo, con qué nivel y por qué (8.4).
CREATE TABLE IF NOT EXISTS bitacora (
    id        INTEGER PRIMARY KEY,
    cuando    TEXT NOT NULL,
    accion    TEXT NOT NULL,
    nivel     TEXT NOT NULL DEFAULT '',
    params    TEXT NOT NULL DEFAULT '{}',
    motivo    TEXT NOT NULL DEFAULT '',
    resultado TEXT NOT NULL DEFAULT '',
    ok        INTEGER NOT NULL DEFAULT 1
);

-- Hasta dónde se leyó cada fuente y si falló.
CREATE TABLE IF NOT EXISTS fuente_estado (
    fuente     TEXT PRIMARY KEY,
    cursor     TEXT NOT NULL DEFAULT '',
    leida      TEXT,
    error      TEXT,
    eventos    INTEGER NOT NULL DEFAULT 0
);

-- Los aparatos que reciben avisos por Web Push (decisión 311). Los da de alta
-- el navegador desde /secretario; no son secretos: sin la clave VAPID, que
-- vive fuera (`~/.secretos/secretario-webpush/`), nadie puede usarlos. Sólo
-- viven aquí, pero se rehacen con volver a pulsar «Activar avisos». Los que el
-- dueño quitó de la lista se recuerdan aparte, en `estado` (`QUITADOS`, C-0232).
CREATE TABLE IF NOT EXISTS suscripcion (
    id         INTEGER PRIMARY KEY,
    endpoint   TEXT NOT NULL UNIQUE,
    p256dh     TEXT NOT NULL,
    auth       TEXT NOT NULL,
    aparato    TEXT NOT NULL DEFAULT '',
    -- Desde dónde se suscribió (`https://….ts.net`, `http://127.0.0.1:8787`):
    -- el aviso lleva ahí al tocarlo.
    origen     TEXT NOT NULL DEFAULT '',
    creada     TEXT NOT NULL,
    ultimo_ok  TEXT,
    fallos     INTEGER NOT NULL DEFAULT 0,
    error      TEXT
);

-- Cada llamada al modelo: para qué, cuánto tardó y cuánto habría costado por
-- API (`total_cost_usd` de `claude -p`; con la suscripción no se cobra, pero
-- es la medida comparable). Sin ella la cuota del triaje no se puede medir.
-- No se reconstruye, pero sólo es medición: perderla no pierde nada del dueño.
CREATE TABLE IF NOT EXISTS llamada (
    id        INTEGER PRIMARY KEY,
    fecha     TEXT NOT NULL,
    trabajo   TEXT NOT NULL DEFAULT '',
    modelo    TEXT NOT NULL DEFAULT '',
    segundos  REAL NOT NULL DEFAULT 0,
    coste     REAL NOT NULL DEFAULT 0,
    entrada   INTEGER NOT NULL DEFAULT 0,
    salida    INTEGER NOT NULL DEFAULT 0,
    ok        INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS llamada_fecha ON llamada (fecha);

-- Lo que el servicio cuenta de sí mismo: su latido y el del triaje.
CREATE TABLE IF NOT EXISTS estado (
    clave  TEXT PRIMARY KEY,
    valor  TEXT NOT NULL
);

-- Lo que espera del dueño (decisiones 379 y 380). 🔴 Sólo vive aquí lo que
-- nace aquí —un relevo, lo que dice un proyecto, un dato por confirmar— y lo
-- que el dueño hizo con cada asunto (visto, anotado, delegado, callado); lo
-- demás se lee en vivo de su dueño y no se copia. No se reconstruye.
CREATE TABLE IF NOT EXISTS asunto (
    id         INTEGER PRIMARY KEY,
    clave      TEXT NOT NULL UNIQUE,
    clase      TEXT NOT NULL,
    origen     TEXT NOT NULL DEFAULT '',
    texto      TEXT NOT NULL DEFAULT '',
    detalle    TEXT NOT NULL DEFAULT '',
    enlace     TEXT NOT NULL DEFAULT '',
    opciones   TEXT NOT NULL DEFAULT '[]',
    propio     INTEGER NOT NULL DEFAULT 0,
    estado     TEXT NOT NULL DEFAULT 'nueva',
    ref        TEXT NOT NULL DEFAULT '',
    respuesta  TEXT NOT NULL DEFAULT '',
    creada     TEXT NOT NULL,
    cambiada   TEXT
);
"""


def carpeta(crear: bool = True) -> Path:
    """Donde vive lo del secretario. La crea quien va a escribir en ella; quien
    sólo mira pasa `crear=False`: una pantalla de `hub-web` no deja la carpeta
    de un secretario que nadie ha encendido (C-0099)."""
    d = config.HUB_HOME / "secretario"
    if crear:
        d.mkdir(parents=True, exist_ok=True)
    return d


def ruta() -> Path:
    """Dónde está la base, sin crear nada: lo crea `conectar`."""
    return carpeta(crear=False) / "memoria.db"


def conectar(r: Path | str | None = None) -> sqlite3.Connection:
    """La memoria para escribir: la crea si no existe y la migra en el sitio.
    La abren `hub-secretario` y las rutas POST de la web; lo que sólo mira
    usa `abrir_lectura` (C-0099)."""
    if r is None:
        carpeta()
    con = sqlite3.connect(r or ruta(), timeout=10.0, isolation_level=None)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=NORMAL")
    con.execute("PRAGMA foreign_keys=ON")
    # El mismo tope que `hub.db` (C-0281): sin él, el `-wal` no encoge nunca.
    con.execute(f"PRAGMA journal_size_limit={TOPE_DEL_WAL}")
    con.executescript(ESQUEMA)
    # Columnas que llegaron después de crearse la base (regla dura 1: la
    # memoria no se rehace, se migra en el sitio).
    columnas = {f["name"] for f in con.execute("PRAGMA table_info(evento)")}
    if "para_mi" not in columnas:
        con.execute("ALTER TABLE evento ADD COLUMN para_mi TEXT NOT NULL DEFAULT ''")
    # Lo que llegó hablando en el modo voz: se le pide contestar corto (C-0155).
    if "voz" not in {f["name"] for f in con.execute("PRAGMA table_info(turno)")}:
        con.execute("ALTER TABLE turno ADD COLUMN voz INTEGER NOT NULL DEFAULT 0")
    # Dicho con el modo inglés puesto: práctica, sin acciones propias (C-0159).
    if "ingles" not in {f["name"] for f in con.execute("PRAGMA table_info(turno)")}:
        con.execute("ALTER TABLE turno ADD COLUMN ingles INTEGER NOT NULL DEFAULT 0")
    # La ventana de /trabajo que miraba al escribir («sesión:índice», C-0162):
    # lo único que `pantalla_actual` puede leer. El contenido no se guarda.
    if "enfoque" not in {f["name"] for f in con.execute("PRAGMA table_info(turno)")}:
        con.execute("ALTER TABLE turno ADD COLUMN enfoque TEXT NOT NULL DEFAULT ''")
    # Qué está haciendo mientras contesta (C-0166, decisión 358): JSON con el
    # estado, el gesto y el rótulo, nunca lo que la herramienta recibió. Dura
    # lo que el turno: se vacía al cerrarlo, así que no es memoria de nada.
    if "actividad" not in {f["name"] for f in con.execute("PRAGMA table_info(turno)")}:
        con.execute("ALTER TABLE turno ADD COLUMN actividad TEXT NOT NULL DEFAULT ''")
    # Lo que el dueño adjuntó al escribir (decisión 383): rutas relativas al
    # intercambio, bajo `_secretario/`. El archivo no se copia aquí.
    if "adjuntos" not in {f["name"] for f in con.execute("PRAGMA table_info(turno)")}:
        con.execute("ALTER TABLE turno ADD COLUMN adjuntos TEXT NOT NULL DEFAULT '[]'")
    # A qué globo del chat contesta (C-0243, decisión 406): un puntero, no una
    # copia. Sin `REFERENCES`: si el citado ya no está, la cita se queda vacía.
    if "responde_a" not in {f["name"] for f in con.execute("PRAGMA table_info(turno)")}:
        con.execute("ALTER TABLE turno ADD COLUMN responde_a INTEGER")
    return con


def existe() -> bool:
    return ruta().is_file()


# Tablas y columnas tal cual están en el archivo: lo que `abrir_lectura`
# compara con lo que hoy deja `conectar`.
_COLUMNAS = ("SELECT m.name, c.name FROM sqlite_master AS m, pragma_table_info(m.name) AS c"
             " WHERE m.type = 'table'")


@functools.cache
def _esquema_de_hoy() -> frozenset[tuple[str, str]]:
    """Lo que una base al día tiene: el `ESQUEMA` y sus migraciones, aplicados
    a una vacía en RAM. Sacado de `conectar` mismo, para que una columna nueva
    no haya que apuntarla en dos sitios."""
    c = conectar(":memory:")
    try:
        return frozenset((f[0], f[1]) for f in c.execute(_COLUMNAS))
    finally:
        c.close()


def abrir_lectura() -> sqlite3.Connection | None:
    """La memoria para quien sólo la mira (`hub-web`, C-0099): en sólo lectura,
    sin crear la carpeta ni la base y sin migrarla. Crearla y ponerla al día es
    de quien escribe: el servicio y las rutas POST, por `conectar`.

    `None` si no hay base, y también si es de una versión anterior (le falta
    una tabla o una columna que `conectar` añade): leída a medias, una consulta
    nueva fallaría en una pantalla cualquiera, y migrarla desde aquí es justo
    lo que esto evita. Se lee como vacía hasta que la abra quien escribe, que
    al arrancar el servicio es enseguida. Puede lanzar `sqlite3.Error` (una
    base ilegible o bloqueada): quien llama decide qué significa."""
    r = ruta()
    if not r.is_file():
        return None
    con = sqlite3.connect(f"{r.absolute().as_uri()}?mode=ro", uri=True, timeout=5)
    con.row_factory = sqlite3.Row
    try:
        al_dia = _esquema_de_hoy() <= {(f[0], f[1]) for f in con.execute(_COLUMNAS)}
    except BaseException:
        con.close()
        raise
    if not al_dia:
        con.close()
        return None
    return con


def vacia() -> sqlite3.Connection:
    """Una memoria vacía en RAM con el esquema de hoy: lo que lee una pantalla
    cuando `abrir_lectura` no da base (C-0099). Tiene la misma forma que la de
    verdad, así que se pinta por el mismo camino, y no deja archivos."""
    return conectar(":memory:")


# ───────────────────────────── aparatos con avisos ─────────────────────────────


def suscribir(con: sqlite3.Connection, endpoint: str, p256dh: str, auth: str, aparato: str = "",
              origen: str = "") -> int:
    if not endpoint.startswith("https://") or not p256dh or not auth:
        raise ValueError("suscripción incompleta")
    con.execute("INSERT INTO suscripcion (endpoint, p256dh, auth, aparato, origen, creada) VALUES (?,?,?,?,?,?)"
                " ON CONFLICT(endpoint) DO UPDATE SET p256dh = excluded.p256dh, auth = excluded.auth,"
                " aparato = excluded.aparato, origen = excluded.origen, fallos = 0, error = NULL",
                (endpoint, p256dh, auth, aparato[:120], origen[:200], ahora()))
    return con.execute("SELECT id FROM suscripcion WHERE endpoint = ?", (endpoint,)).fetchone()[0]


def anotar_entrega(con: sqlite3.Connection, sid: int, ok: bool, error: str | None = None) -> None:
    """Cómo fue el último envío push a un aparato."""
    if ok:
        con.execute("UPDATE suscripcion SET ultimo_ok = ?, fallos = 0, error = NULL WHERE id = ?", (ahora(), sid))
    else:
        con.execute("UPDATE suscripcion SET fallos = fallos + 1, error = ? WHERE id = ?", ((error or "")[:300], sid))


def desuscribir(con: sqlite3.Connection, endpoint: str | None = None, sid: int | None = None) -> None:
    if sid is not None:
        con.execute("DELETE FROM suscripcion WHERE id = ?", (sid,))
    else:
        con.execute("DELETE FROM suscripcion WHERE endpoint = ?", (endpoint,))


def suscripciones(con: sqlite3.Connection) -> list[dict]:
    return [dict(r) for r in con.execute("SELECT * FROM suscripcion ORDER BY id")]


# 🔴 Quitar un aparato de la lista tiene que ser definitivo (C-0232). Desde la
# PC no se le puede quitar la suscripción a su navegador, y ese aparato vuelve a
# darse de alta cada vez que abre la app —a propósito: en iOS desaparecen
# solas—, así que «Quitar» duraba hasta la próxima vez que lo abría. Se recuerda
# en `estado` y no con una marca en `suscripcion`: quien manda avisos lee
# `suscripciones` tal cual y no puede olvidarse de un filtro. Se guarda la
# huella, no la dirección: de un aparato quitado sólo hace falta reconocerlo.
QUITADOS = "push_quitados"
# Se guardan las más nuevas: la huella de un aparato que ya no existe no vuelve
# a llegar, y sin tope la lista sólo crecería.
MAX_QUITADOS = 100
# `activar` es el botón «Activar avisos aquí», la única que vuelve a apuntar un
# aparato quitado; `abrir`, el alta de siempre al abrir la app; `renovar`, la
# del service worker cuando el navegador cambia la suscripción por su cuenta.
MOTIVOS_ALTA = ("abrir", "activar", "renovar")


def _huella(endpoint: str) -> str:
    return hashlib.sha256(endpoint.encode()).hexdigest()


def _quitado(con: sqlite3.Connection, endpoint: str) -> bool:
    return bool(endpoint) and _huella(endpoint) in (leer(con, QUITADOS) or [])


def _recordar_quitado(con: sqlite3.Connection, endpoint: str) -> None:
    huella = _huella(endpoint)
    lista = [h for h in (leer(con, QUITADOS) or []) if h != huella] + [huella]
    poner(con, QUITADOS, lista[-MAX_QUITADOS:])


def huella_de(endpoint: str) -> str:
    """Cómo se reconoce un aparato sin repetir su dirección (la lista de
    quitados, y el «Quitar» de la pantalla)."""
    return _huella(endpoint)


def quitar_aparato(con: sqlite3.Connection, sid: int, huella: str = "") -> bool:
    """«Quitar» en la lista de aparatos: deja de recibir avisos aunque vuelva a
    abrir la app, hasta que en ese aparato se pulse «Activar avisos aquí».
    False si no estaba.

    Con `huella`, sólo si la fila sigue siendo ese aparato: SQLite reutiliza
    el `id` de la última fila borrada, y el «Quitar» de una lista vieja podía
    caer en otro aparato que se acabara de dar de alta (revisor, C-0232)."""
    with transaccion(con):
        fila = con.execute("SELECT endpoint FROM suscripcion WHERE id = ?", (sid,)).fetchone()
        if not fila or (huella and _huella(fila["endpoint"]) != huella):
            return False
        con.execute("DELETE FROM suscripcion WHERE id = ?", (sid,))
        _recordar_quitado(con, fila["endpoint"])
    return True


def dar_de_alta(con: sqlite3.Connection, endpoint: str, p256dh: str, auth: str, aparato: str = "",
                origen: str = "", *, motivo: str = "abrir", anterior: str = "") -> int | None:
    """El alta que pide el navegador; None si no lo apunta porque se quitó de
    la lista (C-0232).

    Con `renovar` y `anterior` (la dirección vieja), el aparato conserva su
    nombre y su fila vieja desaparece: si no, salía «renovada» hasta que se
    volvía a abrir la app y no se sabía cuál era. La renovación de un quitado
    tampoco vuelve, y la dirección nueva queda quitada con él: si no, volvería
    la próxima vez que abriera la app."""
    if motivo not in MOTIVOS_ALTA:
        raise ValueError(f"motivo de alta desconocido: {motivo!r}")
    if not endpoint.startswith("https://") or not p256dh or not auth:
        raise ValueError("suscripción incompleta")
    anterior = anterior if motivo == "renovar" and anterior != endpoint else ""
    with transaccion(con):
        if motivo == "activar":
            quitados = leer(con, QUITADOS) or []
            if _huella(endpoint) in quitados:
                poner(con, QUITADOS, [h for h in quitados if h != _huella(endpoint)])
        elif _quitado(con, endpoint):
            return None
        elif _quitado(con, anterior):
            _recordar_quitado(con, endpoint)
            return None
        if anterior:
            viejo = con.execute("SELECT aparato FROM suscripcion WHERE endpoint = ?", (anterior,)).fetchone()
            if viejo:
                aparato = viejo["aparato"] or aparato
                con.execute("DELETE FROM suscripcion WHERE endpoint = ?", (anterior,))
        return suscribir(con, endpoint, p256dh, auth, aparato, origen)


# ───────────────────────────── eventos ─────────────────────────────


# 🔴 Lo que tiene pinta de llave se tapa ANTES de guardar (regla dura 5). Salió
# en la primera lectura real (2026-10-24): la nota de un slot llevaba una clave
# de API pegada, y sin esto acababa en la memoria y en el prompt del triaje.
# Es una red, no una garantía (regla dura 22): atrapa los formatos conocidos y
# las asignaciones evidentes, no un secreto escrito en prosa.
_SECRETOS = [
    re.compile(r"\b(?:sk|pk|rk)[-_](?:ant-|live_|test_|proj-)?[A-Za-z0-9_-]{16,}"),
    re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}|\bgithub_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bxox[abposr]-[A-Za-z0-9-]{10,}"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{30,}"),
    re.compile(r"\b\d{8,10}:[A-Za-z0-9_-]{30,}\b"),                     # token de bot de Telegram
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.S),
    re.compile(r"(?i)\b(?:bearer)\s+[A-Za-z0-9._~+/-]{20,}=*"),
    # La comilla (escapada o no) entre la clave y los dos puntos es la forma
    # JSON: `{"password": "…"}` pasaba entero, y así sale lo que devuelve una
    # herramienta dentro de una línea de stream-json (C-0185). Y la clave puede
    # llevar algo delante con `_` (`access_token`, `client_secret`,
    # `DB_PASSWORD`): `\b` no lo dejaba. `input_tokens` no casa: tras la clave
    # sólo valen comilla, espacio, `:` o `=`. Un valor entre comillas se tapa
    # hasta la comilla (con espacios dentro, si los tiene) y no hasta el fin
    # de la línea compacta; si no cuadra, se tapa de más, nunca de menos.
    # Lo ya tapado no se vuelve a tapar: lo que dice un proyecto pasa tres veces
    # (al dejarlo, al recogerlo y en el asunto, 387) y cada una dejaba otro
    # « oculto]» colgando.
    re.compile(r"(?i)(?<![A-Za-z0-9])(password|passwd|contrase(?:ñ|n)a|token|secret|api[_-]?key)"
               r"(\\?[\"']?\s*[:=]\s*)(?!\\?[\"']?\[secreto oculto\])"
               r"(?:\\?[\"'][^\"'\\\n]{6,}\\?[\"']?|\S{6,})"),
]


def ocultar_secretos(texto: str) -> str:
    """Tapa lo que tiene pinta de llave. Pasa por aquí todo lo que se guarda
    venga de donde venga: lo que entra de las fuentes (`guardar_evento`) y lo
    que escribe el secretario —sus notas y compromisos (`anotar`,
    `comprometer`, también los que apunta el modelo) y sus turnos
    (`conversacion.contestar` y `decir`), C-0434—. Es una red de patrones,
    no una garantía (regla dura 22): un secreto escrito en prosa pasa."""
    for patron in _SECRETOS:
        if patron.groups >= 2:
            texto = patron.sub(lambda m: f"{m.group(1)}{m.group(2)}[secreto oculto]", texto)
        else:
            texto = patron.sub("[secreto oculto]", texto)
    return texto


def guardar_evento(con: sqlite3.Connection, ev) -> int | None:
    """Mete un evento en el buzón. Devuelve su id, o None si ya estaba."""
    ev.texto = ocultar_secretos(ev.texto or "")
    cur = con.execute(
        "INSERT OR IGNORE INTO evento (fuente, id_externo, conversacion, autor, fecha, texto, adjuntos,"
        " enlace, recibido, para_mi) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (ev.fuente, ev.id_externo, ev.conversacion, ev.autor, ev.fecha, ev.texto,
         json.dumps(ev.adjuntos, ensure_ascii=False), ev.enlace, ahora(), getattr(ev, "para_mi", "") or ""))
    return cur.lastrowid if cur.rowcount else None


#: Lo que dice `evento.triado` (ver el esquema). Con nombre para que nadie
#: escriba ni cuente un número suelto (C-0064).
POR_LEER, LEIDO, APARTADO, FILTRADO, LIMPIO = 0, 1, 2, 3, 4
_TRIADOS = {POR_LEER, LEIDO, APARTADO, FILTRADO, LIMPIO}


def sin_triar(con: sqlite3.Connection, n: int = 40) -> list[sqlite3.Row]:
    return con.execute("SELECT * FROM evento WHERE triado = ? ORDER BY id LIMIT ?", (POR_LEER, n)).fetchall()


def marcar_triados(con: sqlite3.Connection, ids: list[int], estado: int = LEIDO) -> None:
    if estado not in _TRIADOS:
        raise ValueError(f"estado de triaje desconocido: {estado}")
    con.executemany("UPDATE evento SET triado = ? WHERE id = ?", [(estado, i) for i in ids])


def cuentas_triaje(con: sqlite3.Connection) -> dict[str, int]:
    """Cuántos eventos hay, cuántos esperan al triaje, cuántos filtró el filtro
    y cuántas vueltas del triaje no llamaron al modelo gracias a él (C-0006)."""
    f = con.execute("SELECT COUNT(*) AS eventos, SUM(triado = ?) AS sin_triar, SUM(triado = ?) AS filtrados"
                    " FROM evento", (POR_LEER, FILTRADO)).fetchone()
    return {"eventos": f["eventos"] or 0, "sin_triar": f["sin_triar"] or 0, "filtrados": f["filtrados"] or 0,
            "sin_llamada": int(leer(con, "triaje_sin_llamada", 0) or 0)}


# ───────────────────────────── búsqueda ─────────────────────────────

_PALABRA = re.compile(r"[\wáéíóúñü]+", re.IGNORECASE)
# Palabras que no ayudan a encontrar nada y, con AND, hacen que no salga nada.
_VACIAS = frozenset(
    "a al algo alguna alguno con de del el en es esa ese eso esta este esto ha hay la las le lo los me mi "
    "mis no o para pero por que qué se sobre su sus te tengo tu un una y ya dijeron dijo".split())


def _consulta_fts(texto: str, modo: str) -> str | None:
    """Texto libre → consulta FTS5 segura. Cada término va entre comillas: un
    `-` o un `:` sueltos son sintaxis de FTS y reventarían la consulta."""
    terminos = [t for t in _PALABRA.findall(texto or "") if t.lower() not in _VACIAS and len(t) > 1]
    if not terminos:
        return None
    return f" {modo} ".join(f'"{t}"*' for t in terminos[:12])


#: Las notas que van delante en `buscar`: lo ya sacado en limpio, sin que
#: tape los mensajes cuando casan muchas.
NOTAS_DELANTE = 4


def buscar(con: sqlite3.Connection, texto: str, *, fuente: str | None = None, desde: str | None = None,
           hasta: str | None = None, n: int = 12) -> list[dict]:
    """Notas y mensajes que casan con `texto`, con su origen: primero las
    notas (hasta `NOTAS_DELANTE`) y luego los mensajes, cada grupo por su
    puntuación y, a igualdad, lo más reciente primero.

    No se mezclan: bm25 de `evento_fts` y el de `nota_fts` no se comparan,
    cada índice tiene sus propias estadísticas, y una nota quedaba detrás de
    veinte mensajes que casaban mejor por casualidad (SEC2-20). Sin notas que
    casen, todo el hueco es para los mensajes.

    Primero exige todos los términos; si no sale nada, se conforma con alguno.
    Lo segundo trae ruido, pero «no encontré nada» cuando sí había es peor: el
    dueño deja de preguntar.

    `desde` y `hasta` (UTC) recortan los mensajes por su fecha y las notas por
    cuándo se anotaron (C-0322): sin lo segundo, «¿qué anotamos desde el
    lunes?» traía notas de cualquier día.
    """
    for modo in ("AND", "OR"):
        q = _consulta_fts(texto, modo)
        if not q:
            break
        filtros, params = "", [q]
        de_notas, params_notas = "", [q]
        if fuente:
            filtros += " AND e.fuente = ?"
            params.append(fuente)
        if desde:
            filtros += " AND e.fecha >= ?"
            params.append(desde)
            de_notas += " AND n.creada >= ?"
            params_notas.append(desde)
        if hasta:
            filtros += " AND e.fecha <= ?"
            params.append(hasta)
            de_notas += " AND n.creada <= ?"
            params_notas.append(hasta)
        notas = [] if fuente else con.execute(
            "SELECT n.id, n.texto, n.tema, n.origen, n.creada, bm25(nota_fts) AS r"
            " FROM nota_fts JOIN nota n ON n.id = nota_fts.rowid WHERE nota_fts MATCH ?"
            f"{de_notas} ORDER BY r, n.creada DESC LIMIT ?", (*params_notas, min(NOTAS_DELANTE, n))).fetchall()
        filas = con.execute(
            "SELECT e.id, e.fuente, e.conversacion, e.autor, e.fecha, e.texto, e.enlace, bm25(evento_fts) AS r"
            " FROM evento_fts JOIN evento e ON e.id = evento_fts.rowid"
            f" WHERE evento_fts MATCH ? {filtros} ORDER BY r, e.fecha DESC LIMIT ?",
            (*params, n - len(notas))).fetchall()
        salida = ([{"tipo": "nota", "id": f["id"], "texto": f["texto"], "tema": f["tema"],
                    "origen": f["origen"], "fecha": f["creada"]} for f in notas]
                  + [{"tipo": "mensaje", "id": f["id"], "fuente": f["fuente"], "conversacion": f["conversacion"],
                      "autor": f["autor"], "fecha": f["fecha"], "texto": f["texto"][:1500],
                      "enlace": f["enlace"]} for f in filas])
        if salida:
            return salida
    return []


def _filtros_recientes(con: sqlite3.Connection, *, fuente: str | None = None, conversacion: str | None = None,
                       desde: str | None = None, hasta: str | None = None, autor: str | None = None,
                       solo_para_mi: bool = False) -> tuple[list[str], list]:
    """Los filtros de `recientes`, armados una vez para la página y para su
    cuenta (C-0392): dos `WHERE` copiados acabarían contando otra cosa.
    `desde`/`hasta` en UTC, como `fecha`; `autor`, por `autores_llamados`."""
    filtros, params = [], []
    if solo_para_mi:
        filtros.append("para_mi IN ('privado', 'etiqueta', 'nombre')")
    if fuente:
        filtros.append("fuente = ?")
        params.append(fuente)
    if conversacion:
        filtros.append("conversacion LIKE ?")
        params.append(f"%{conversacion}%")
    if desde:
        filtros.append("fecha >= ?")
        params.append(desde)
    if hasta:
        filtros.append("fecha <= ?")
        params.append(hasta)
    if autor:
        quienes = autores_llamados(con, autor)
        filtros.append(f"autor IN ({','.join('?' * len(quienes))})" if quienes else "0")
        params.extend(quienes)
    return filtros, params


def recientes(con: sqlite3.Connection, *, fuente: str | None = None, conversacion: str | None = None,
              desde: str | None = None, n: int = 40, solo_para_mi: bool = False, hasta: str | None = None,
              autor: str | None = None, antes_de: int | None = None) -> list[dict]:
    """Lo último que llegó, sin buscar: «¿qué se dijo hoy en el grupo?», y con
    `solo_para_mi`, «¿qué me pidieron a mí?» (decisión 332). Lo más nuevo
    primero, en el orden `(fecha, id)`.

    `antes_de`: el id del último que ya se leyó; da los que van después de él
    en ese orden (C-0392). Por la pareja y no por el id solo: un chat
    exportado entra con ids nuevos y fechas viejas, y a igual fecha el orden
    no estaba definido, así que una página podía repetir o saltarse uno. Un
    id que no existe es un `ValueError`. Sigue siendo una lista: el total lo
    da `contar_recientes` (la usa también el triaje)."""
    filtros, params = _filtros_recientes(con, fuente=fuente, conversacion=conversacion, desde=desde, hasta=hasta,
                                         autor=autor, solo_para_mi=solo_para_mi)
    if antes_de is not None:
        cursor = con.execute("SELECT fecha FROM evento WHERE id = ?", (int(antes_de),)).fetchone()
        if cursor is None:
            raise ValueError(f"no hay ningún mensaje con id {antes_de}")
        filtros.append("(fecha < ? OR (fecha = ? AND id < ?))")
        params.extend([cursor["fecha"], cursor["fecha"], int(antes_de)])
    donde = ("WHERE " + " AND ".join(filtros)) if filtros else ""
    filas = con.execute(f"SELECT id, fuente, conversacion, autor, fecha, texto, enlace, para_mi FROM evento {donde}"
                        " ORDER BY fecha DESC, id DESC LIMIT ?", (*params, n)).fetchall()
    return [dict(f) | {"texto": f["texto"][:1500]} for f in filas]


def contar_recientes(con: sqlite3.Connection, *, fuente: str | None = None, conversacion: str | None = None,
                     desde: str | None = None, hasta: str | None = None, autor: str | None = None,
                     solo_para_mi: bool = False) -> int:
    """Cuántos cumplen los filtros de `recientes`, sin página ni cursor: lo
    que hace falta para decir «hay 266, leí los 100 últimos» (C-0392)."""
    filtros, params = _filtros_recientes(con, fuente=fuente, conversacion=conversacion, desde=desde, hasta=hasta,
                                         autor=autor, solo_para_mi=solo_para_mi)
    donde = ("WHERE " + " AND ".join(filtros)) if filtros else ""
    return con.execute(f"SELECT COUNT(*) FROM evento {donde}", params).fetchone()[0]


def conversaciones(con: sqlite3.Connection) -> list[dict]:
    return [dict(f) for f in con.execute(
        "SELECT fuente, conversacion, COUNT(*) AS mensajes, MAX(fecha) AS ultimo FROM evento"
        " GROUP BY fuente, conversacion ORDER BY ultimo DESC")]


def nombra(texto: str, nombre: str) -> bool:
    """Si `texto` lleva `nombre` como palabra entera, sin mayúsculas ni
    tildes: «Ana» no casa con «Anabel» (como `piezas.para_mi`)."""
    n = _sin_tildes(" ".join((nombre or "").split()))
    return bool(n) and re.search(rf"(?<!\w){re.escape(n)}(?!\w)", _sin_tildes(texto or "")) is not None


def autores_llamados(con: sqlite3.Connection, nombre: str) -> list[str]:
    """Los autores de mensajes que se llaman `nombre` (`nombra`: palabra
    entera, sin mayúsculas ni tildes), sin el dueño («Yo»). Una sola regla
    para `persona` y para `recientes` por autor (C-0392): un `LIKE` aparte
    haría que «Ana» casara con «Anabel» en uno y no en el otro."""
    return sorted({f["autor"] for f in con.execute("SELECT DISTINCT autor FROM evento WHERE autor != 'Yo'")
                   if nombra(f["autor"], nombre)})


def sobre_persona(con: sqlite3.Connection, nombre: str, *, n: int = 10) -> dict:
    """Lo que hay de alguien, calculado al vuelo (C-0411): la tabla `persona`
    sigue vacía (C-0029), y esto no la necesita ni cambia el esquema.

    Los chats donde firma mensajes, su último mensaje, el último del dueño
    (autor «Yo») en su chat privado —en un grupo no se sabe a quién hablaba—,
    los compromisos abiertos que hace él o son para él, y las notas que lo
    nombran. Las fechas, en UTC como todo lo de aquí."""
    autores = autores_llamados(con, nombre)
    chats, ultimo, tuyo = [], None, None
    if autores:
        marcas = ",".join("?" * len(autores))
        chats = [dict(f) for f in con.execute(
            f"SELECT fuente, conversacion, COUNT(*) AS mensajes, MAX(fecha) AS ultimo FROM evento"
            f" WHERE autor IN ({marcas}) GROUP BY fuente, conversacion ORDER BY ultimo DESC LIMIT ?", (*autores, n))]
        f = con.execute(f"SELECT id, fuente, conversacion, autor, fecha, texto FROM evento WHERE autor IN ({marcas})"
                        " ORDER BY fecha DESC LIMIT 1", autores).fetchone()
        ultimo = dict(f) if f else None
        privados = con.execute(f"SELECT DISTINCT fuente, conversacion FROM evento WHERE autor IN ({marcas})"
                               " AND para_mi = 'privado'", autores).fetchall()
        for p in privados:
            f = con.execute("SELECT id, fuente, conversacion, fecha, texto FROM evento WHERE autor = 'Yo'"
                            " AND fuente = ? AND conversacion = ? ORDER BY fecha DESC LIMIT 1",
                            (p["fuente"], p["conversacion"])).fetchone()
            if f and (tuyo is None or f["fecha"] > tuyo["fecha"]):
                tuyo = dict(f)
    suyos = [c for c in compromisos(con, "abierto")
             if nombra(c["quien"], nombre) or nombra(c["para_quien"], nombre)]
    q = " ".join(_PALABRA.findall(nombre or ""))
    notas = [dict(f) for f in con.execute(
        "SELECT n.id, n.texto, n.tema, n.creada FROM nota_fts JOIN nota n ON n.id = nota_fts.rowid"
        " WHERE nota_fts MATCH ? ORDER BY n.creada DESC LIMIT ?", (f'"{q}"', n))] if q else []
    return {"autores": autores, "chats": chats, "su_ultimo": ultimo, "del_dueno": tuyo,
            "compromisos": suyos[:n], "notas": notas}


# ───────────────────────────── notas ─────────────────────────────


def anotar(con: sqlite3.Connection, texto: str, *, tema: str = "", evento: int | None = None,
           origen: str = "") -> int:
    """Una nota, con lo que parece una llave tapado (`ocultar_secretos`, C-0434:
    una red, no una garantía)."""
    return con.execute("INSERT INTO nota (texto, tema, evento, origen, creada) VALUES (?,?,?,?,?)",
                       (ocultar_secretos(texto.strip()), ocultar_secretos(tema.strip()), evento, origen,
                        ahora())).lastrowid


#: Los temas que pueden llevar las notas que el secretario saca solo: el
#: triaje y el cierre de un hilo eligen de aquí o lo dejan vacío (C-0424).
#: Con tema libre salían 88 temas para 127 notas, y un tema que no agrupa no
#: sirve para filtrar; el detalle va en el texto. El dueño, y el secretario
#: cuando él se lo dicta (`anotar`, corregir una nota), siguen con tema libre.
#: Cambiar la lista no migra nada: las notas ya guardadas se quedan como están.
TEMAS = ("persona", "proyecto", "preferencia", "decisión", "dato", "investigación", "inglés")

#: En `estado`: desde cuándo se cuenta qué notas se le sirven al modelo. De
#: antes no se sabe, y decir «nunca salió» sería una cifra que no se puede
#: defender (regla dura 13).
USO_DESDE = "uso_notas_desde"


def tema_automatico(tema) -> str:
    """El tema de una nota que el secretario saca solo: uno de `TEMAS`, o
    ninguno. El esquema del triaje y el del cierre ya se lo piden al modelo;
    esto es por si no lo cumple, que un tema inventado vuelve a partir lo que
    la lista junta. Lo que pone el dueño no pasa por aquí."""
    t = " ".join(str(tema or "").split()).lower()
    return t if t in TEMAS else ""


def notas(con: sqlite3.Connection, n: int | None = 100, *, tema: str | None = None,
          sin_leer: bool = False) -> list[dict]:
    """Las notas, la más nueva primero; `n=None`, todas.

    `tema`: sólo las de ese tema, exacto. `sin_leer`: sólo las que no se le
    han servido al modelo desde que se cuenta (`apuntar_lectura`; desde
    cuándo, `USO_DESDE`): sin una búsqueda contada, lo son todas."""
    filtros, params = [], []
    if tema is not None:
        filtros.append("tema = ?")
        params.append(tema)
    if sin_leer:
        filtros.append("id NOT IN (SELECT nota FROM nota_uso)")
    donde = ("WHERE " + " AND ".join(filtros)) if filtros else ""
    limite = "" if n is None else " LIMIT ?"
    return [dict(f) for f in con.execute(f"SELECT * FROM nota {donde} ORDER BY id DESC{limite}",
                                         (*params, *(() if n is None else (n,))))]


def cuantas_por_tema(con: sqlite3.Connection) -> dict[str, int]:
    """Cuántas notas lleva cada tema, exacto (las de tema libre también)."""
    return dict(con.execute("SELECT tema, COUNT(*) FROM nota GROUP BY tema").fetchall())


def apuntar_lectura(con: sqlite3.Connection, ids, *, desde_ahora: bool = False) -> None:
    """Que estas notas se le acaban de servir al modelo (C-0424): suma una vez
    a cada una y guarda cuándo. La primera vez, apunta también desde cuándo se
    cuenta (`USO_DESDE`), aunque la búsqueda no trajera ninguna nota.

    La llaman quienes le dan la nota al modelo —las herramientas `buscar` y
    `persona`—, cada una en su `try`: si falla, la herramienta contesta igual
    y lo dice. **`buscar` no escribe**: es una lectura que cualquiera puede
    llamar, y que el dueño abra Memoria no es que el secretario la use.

    La fecha y la cuenta, juntas o ninguna: una fecha sin su cuenta diría «no
    salió» de lo que sí salió. Por lo mismo, `desde_ahora` la adelanta a este
    momento: lo pide quien sabe que una lectura anterior no se pudo apuntar, y
    desde la fecha de antes «no salió» ya no se podría defender (regla dura
    13). Una nota que ya no está (borrada entre que se buscó y se apunta) no
    deja fila. Escribe en `nota_uso` y en `estado`, nunca en `nota`: su índice
    de texto no se toca."""
    unicos = sorted({int(i) for i in ids})
    momento = ahora()

    def escribir() -> None:
        con.execute("INSERT INTO estado (clave, valor) VALUES (?, ?) ON CONFLICT(clave) DO "
                    + ("UPDATE SET valor = excluded.valor" if desde_ahora else "NOTHING"),
                    (USO_DESDE, json.dumps(momento)))
        if unicos:
            # Por el SELECT y no por VALUES: así una nota que ya no está no
            # deja fila (ni rompe la clave ajena). Su `WHERE` hace falta para
            # que SQLite no lea el `ON` de `ON CONFLICT` como el de un JOIN.
            con.execute(f"INSERT INTO nota_uso (nota, veces, ultima) SELECT id, 1, ? FROM nota"
                        f" WHERE id IN ({','.join('?' * len(unicos))})"
                        " ON CONFLICT(nota) DO UPDATE SET veces = nota_uso.veces + 1, ultima = excluded.ultima",
                        (momento, *unicos))

    if con.in_transaction:
        escribir()
        return
    with transaccion(con):
        escribir()


def buscar_notas(con: sqlite3.Connection, texto: str) -> list[dict]:
    """Todas las notas que dicen `texto` en su texto, su tema o su origen, la
    más reciente primero (SEC-35: la pantalla carga las últimas y una vieja
    equivocada no se podía ni encontrar). Un trozo de palabra cuenta, sin
    mayúsculas ni tildes que la separen, como el filtro del navegador: por eso
    no va por `nota_fts`, que sólo casa palabras enteras."""
    q = _sin_tildes(texto.strip())
    if not q:
        return []
    return [dict(f) for f in con.execute("SELECT * FROM nota ORDER BY id DESC")
            if q in _sin_tildes(f"{f['texto']} {f['tema']} {f['origen']}")]


def _sin_tildes(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texto.casefold()) if unicodedata.category(c) != "Mn")


def editar_nota(con: sqlite3.Connection, id_: int, texto: str, tema: str | None = None) -> None:
    if tema is None:
        con.execute("UPDATE nota SET texto = ?, editada = ? WHERE id = ?", (texto.strip(), ahora(), id_))
    else:
        con.execute("UPDATE nota SET texto = ?, tema = ?, editada = ? WHERE id = ?",
                    (texto.strip(), tema.strip(), ahora(), id_))


def borrar_nota(con: sqlite3.Connection, id_: int) -> None:
    con.execute("DELETE FROM nota WHERE id = ?", (id_,))


#: Lo que queda en la bitácora y en una solicitud donde estaba el texto de una
#: nota olvidada: la fila sigue diciendo qué se hizo y cuándo, no el contenido.
OLVIDADO = "[olvidado]"

#: Las acciones cuyo parámetro `texto` ES el texto de una nota.
_DE_NOTAS = ("anotar", "editar_nota")
_ANTES_DECIA = re.compile(r"antes decía: «(.*?)»(?:; su tema era «.*»)?\Z", re.S)
#: Por debajo de esto una versión no se busca suelta dentro de un resultado:
#: una nota que dijera «ok» se llevaría por delante medio «nota 5 guardada».
_MINIMO_SUELTO = 12


def olvidar_nota(con: sqlite3.Connection, id_: int) -> int:
    """Borra una nota y tapa lo que la bitácora y las solicitudes guardaban de
    ella (C-0418). Devuelve cuántas filas tapó.

    `borrar_nota` quita la fila y nada más: el texto seguía en la bitácora
    —en los parámetros de anotarla y de cada corrección, en el «antes decía»
    y en el motivo que redactó el modelo— y, si pasó por un permiso, en su
    solicitud. Olvidar que deja eso escrito no es olvidar.

    Qué filas son de la nota, y sólo éstas:

    - `anotar` cuyo resultado es «nota N guardada», y su solicitud si la hubo;
    - `editar_nota` cuyo parámetro `id` es N, y sus solicitudes (también la
      que aún espera: aprobada después, dirá que la nota no existe);
    - la fila que pidió permiso para anotarla, que no lleva N: se llega por
      el número de su solicitud («solicitud S»);
    - y la de `anotar` o `editar_nota` que no lleva N (un intento que no se
      permitió): sólo si su `texto` es **exactamente** el de la nota o el de
      una versión suya de las que estas mismas filas guardan. Nunca por
      parecido, y nunca en otra acción: un compromiso con las mismas
      palabras no es la nota.

    El número de una nota puede volver a usarse al borrar la última: las
    filas de una nota anterior con ese número también se tapan, y está bien,
    porque esa nota ya no existe.

    En cada una, todo texto de sus parámetros y su motivo pasan a ser
    `OLVIDADO`, y el «antes decía» del resultado también. Se conservan la
    fila, la fecha, la acción, el nivel y el número. 🔴 Es la única escritura
    que cambia la bitácora después de apuntada, y con el borrado va en una
    sola transacción: las dos cosas o ninguna.

    Lo que **no** toca, porque no se puede saber con certeza qué es de la
    nota: los turnos del chat, los resúmenes de conversaciones, el mensaje
    del que salió (`evento`) y las copias diarias ya hechas."""
    if con.in_transaction:
        return _olvidar_nota(con, int(id_))
    with transaccion(con):
        return _olvidar_nota(con, int(id_))


def _olvidar_nota(con: sqlite3.Connection, nid: int) -> int:
    def parametros(fila) -> dict:
        try:
            p = json.loads(fila["params"] or "{}")
        except ValueError:
            return {}
        return p if isinstance(p, dict) else {}

    def de_la_nota(fila, p: dict) -> bool:
        if fila["accion"] == "anotar":
            return (fila["resultado"] or "") == f"nota {nid} guardada"
        return not isinstance(p.get("id"), bool) and str(p.get("id")) == str(nid)

    def tapada(fila, p: dict) -> tuple[str, str, str | None]:
        limpio = {k: v if v is None or isinstance(v, (bool, int, float)) else OLVIDADO for k, v in p.items()}
        resultado = fila["resultado"]
        if resultado:
            resultado = _ANTES_DECIA.sub(f"antes decía: «{OLVIDADO}»", resultado)
            # Por si el resultado la citara de otra forma que el «antes decía».
            for v in versiones:
                if len(v) >= _MINIMO_SUELTO:
                    resultado = resultado.replace(v, OLVIDADO)
        return json.dumps(limpio, ensure_ascii=False), OLVIDADO if fila["motivo"] else fila["motivo"], resultado

    def version(fila, p: dict) -> None:
        if isinstance(p.get("texto"), str) and p["texto"].strip():
            versiones.add(p["texto"])
        antes = _ANTES_DECIA.search(fila["resultado"] or "")
        if antes and antes.group(1).strip():
            versiones.add(antes.group(1))

    nota = con.execute("SELECT texto FROM nota WHERE id = ?", (nid,)).fetchone()
    versiones: set[str] = {nota["texto"]} if nota and nota["texto"].strip() else set()
    marcas = ", ".join("?" for _ in _DE_NOTAS)

    solicitudes = [(s, parametros(s)) for s in con.execute(
        f"SELECT id, accion, params, motivo, resultado FROM solicitud WHERE accion IN ({marcas})", _DE_NOTAS)]
    solicitudes = [(s, p) for s, p in solicitudes if de_la_nota(s, p)]
    suyas = {s["id"] for s, _ in solicitudes}

    seguras, dudosas = [], []
    for b in con.execute(f"SELECT id, accion, params, motivo, resultado FROM bitacora WHERE accion IN ({marcas})",
                         _DE_NOTAS).fetchall():
        p = parametros(b)
        pidio = re.fullmatch(r"solicitud (\d+)", b["resultado"] or "")
        (seguras if de_la_nota(b, p) or (pidio and int(pidio.group(1)) in suyas) else dudosas).append((b, p))
    for fila, p in (*solicitudes, *seguras):
        version(fila, p)
    # Las que no dicen de qué nota son: sólo por el texto exacto.
    seguras += [(b, p) for b, p in dudosas if isinstance(p.get("texto"), str) and p["texto"] in versiones]

    for s, p in solicitudes:
        con.execute("UPDATE solicitud SET params = ?, motivo = ?, resultado = ? WHERE id = ?", (*tapada(s, p), s["id"]))
    for b, p in seguras:
        con.execute("UPDATE bitacora SET params = ?, motivo = ?, resultado = ? WHERE id = ?", (*tapada(b, p), b["id"]))
    con.execute("DELETE FROM nota WHERE id = ?", (nid,))
    return len(solicitudes) + len(seguras)


# ───────────────────────────── compromisos ─────────────────────────────


def comprometer(con: sqlite3.Connection, que: str, *, quien: str = "yo", para_quien: str = "",
                vence: str | None = None, recordar_en: str | None = None, evento: int | None = None,
                origen: str = "") -> int:
    """Un compromiso nuevo, salvo que ya haya uno abierto igual (el triaje ve el
    mismo «mañana te lo mando» en dos mensajes seguidos).

    Si ya había uno igual y llegan fechas, **las fechas nuevas mandan**: «el de
    los PRs, recuérdamelo el lunes» sobre uno que vencía el martes pasado se
    quedaba con la fecha vieja, y el modelo, viéndolo vencido, lo descartó
    (medido el 2026-10-24). Lo último que dijo el dueño es lo que vale.

    Un plazo que llega sin aviso no se vuelve aviso: el triaje no lo da a lo
    que le pide otro (C-0410) ni a un plazo ya pasado, y `reprogramar` hacía
    del plazo la hora del aviso.

    Lo que parece una llave se tapa antes de compararlo y de guardarlo
    (`ocultar_secretos`, C-0434: una red, no una garantía)."""
    que = ocultar_secretos(que)
    igual = con.execute("SELECT id FROM compromiso WHERE estado = 'abierto' AND lower(que) = lower(?)"
                        " AND quien = ?", (que.strip(), quien or "yo")).fetchone()
    if igual:
        if recordar_en:
            reprogramar(con, igual["id"], vence=vence, recordar_en=recordar_en)
        elif vence:
            con.execute("UPDATE compromiso SET vence = ? WHERE id = ?", (vence, igual["id"]))
        return igual["id"]
    return con.execute(
        "INSERT INTO compromiso (quien, para_quien, que, vence, recordar_en, evento, origen, creado)"
        " VALUES (?,?,?,?,?,?,?,?)",
        (quien or "yo", para_quien, que.strip(), vence, recordar_en, evento, origen, ahora())).lastrowid


def reprogramar(con: sqlite3.Connection, id_: int, *, vence: str | None = None,
                recordar_en: str | None = None) -> None:
    """Fechas nuevas para un compromiso; el aviso vuelve a quedar pendiente."""
    if vence:
        con.execute("UPDATE compromiso SET vence = ? WHERE id = ?", (vence, id_))
    if recordar_en or vence:
        con.execute("UPDATE compromiso SET recordar_en = ?, recordado = NULL, estado = 'abierto' WHERE id = ?",
                    (recordar_en or vence, id_))


def editar_compromiso(con: sqlite3.Connection, id_: int, *, que: str, vence: str | None,
                      recordar_en: str | None) -> None:
    """Lo que el dueño corrige a mano: el texto y las dos fechas (UTC ISO o
    None para quitarla). Si cambia el aviso, vuelve a quedar pendiente."""
    que = (que or "").strip()
    if not que:
        raise ValueError("el compromiso necesita texto")
    f = con.execute("SELECT recordar_en FROM compromiso WHERE id = ?", (id_,)).fetchone()
    if not f:
        raise ValueError("ese compromiso ya no existe")
    con.execute("UPDATE compromiso SET que = ?, vence = ?, recordar_en = ? WHERE id = ?",
                (que, vence, recordar_en, id_))
    if recordar_en != f["recordar_en"]:
        con.execute("UPDATE compromiso SET recordado = NULL WHERE id = ?", (id_,))


def compromisos(con: sqlite3.Connection, estado: str | None = "abierto", n: int = 200, *,
                quien: str | None = None, vence_antes: str | None = None,
                evento: int | None = None) -> list[dict]:
    """Los abiertos, el que vence antes primero; los cerrados, el último que
    se cerró primero («¿qué hice esta semana?» no empieza por lo de octubre).

    `quien`: «yo» (lo que dijo que haría) u «otros» (lo que le pidieron);
    `vence_antes` (UTC): sólo los que tienen plazo hasta ese instante;
    `evento`: sólo los que salieron de ese evento (una reunión, C-0380)."""
    filtros, params = [], []
    if estado:
        filtros.append("estado = ?")
        params.append(estado)
    if evento is not None:
        filtros.append("evento = ?")
        params.append(int(evento))
    if quien == "yo":
        filtros.append("lower(quien) = 'yo'")
    elif quien == "otros":
        filtros.append("lower(quien) != 'yo'")
    elif quien:
        raise ValueError("`quien` es «yo» u «otros»")
    if vence_antes:
        filtros.append("vence IS NOT NULL AND vence <= ?")
        params.append(vence_antes)
    donde = ("WHERE " + " AND ".join(filtros)) if filtros else ""
    orden = ("vence IS NULL, vence, id" if estado == "abierto" else "cerrado DESC, id DESC" if estado
             else "id DESC")
    return [dict(f) for f in con.execute(f"SELECT * FROM compromiso {donde} ORDER BY {orden} LIMIT ?", (*params, n))]


def vencidos(con: sqlite3.Connection, momento: str | None = None) -> list[dict]:
    """Los abiertos cuya fecha de vencer es anterior a `momento` (UTC ISO; por
    omisión, ahora), el que antes venció primero. De quien sea: la pantalla
    los enseña todos, como «Compromisos abiertos». Una sola regla para la
    pantalla y el parte (C-0369, C-0373)."""
    return [dict(f) for f in con.execute(
        "SELECT * FROM compromiso WHERE estado = 'abierto' AND vence IS NOT NULL AND vence < ?"
        " ORDER BY vence, id", (momento or ahora(),))]


def vencidos_o_de_hoy(con: sqlite3.Connection) -> list[dict]:
    """Los vencidos y los que vencen hoy, en la hora de la casa: lo que
    enseñan «Vencidos o de hoy» y su lote de Pendientes. Hasta el final del día
    y no hasta ahora: un compromiso de hoy sin hora se guarda a las 9
    (`tiempo.a_utc`), y con el corte en «ahora» a las 10 ya salía vencido."""
    from . import tiempo

    return vencidos(con, tiempo.limite_utc(tiempo.ahora_local().date().isoformat(), fin=True))


def cerrar_compromiso(con: sqlite3.Connection, id_: int, estado: str = "hecho", *,
                      solo_abierto: bool = False) -> None:
    """`solo_abierto`: no toca uno ya cerrado. Lo pide el aviso de un
    recordatorio, que puede ser de antes de cerrarlo: un «Hecho» viejo pasaba
    un descartado a hecho y le cambiaba la hora de cierre (C-0407)."""
    if estado not in ("hecho", "descartado", "abierto"):
        raise ValueError("estado no válido")
    # Uno que no existe se dice: «Hecho» desde un aviso viejo contestaba que sí (C-0407).
    if not con.execute("UPDATE compromiso SET estado = ?, cerrado = ? WHERE id = ?"
                       + (" AND estado = 'abierto'" if solo_abierto else ""),
                       (estado, None if estado == "abierto" else ahora(), id_)).rowcount:
        existe = con.execute("SELECT 1 FROM compromiso WHERE id = ?", (id_,)).fetchone()
        raise ValueError("ese compromiso ya está cerrado" if existe else "ese compromiso ya no existe")


def aplazar_aviso(con: sqlite3.Connection, id_: int, minutos: int) -> str:
    """«En 1 h» desde el aviso de un recordatorio (C-0407): sólo la hora del
    aviso, por la misma puerta que «Editar» en Pendientes; el texto y el plazo
    no se tocan. Uno ya cerrado no se vuelve a avisar. Devuelve la hora nueva (UTC)."""
    f = con.execute("SELECT que, vence, estado FROM compromiso WHERE id = ?", (id_,)).fetchone()
    if not f:
        raise ValueError("ese compromiso ya no existe")
    if f["estado"] != "abierto":
        raise ValueError("ese compromiso ya está cerrado")
    nuevo = (datetime.fromisoformat(ahora()) + timedelta(minutes=minutos)).isoformat(timespec="seconds")
    editar_compromiso(con, id_, que=f["que"], vence=f["vence"], recordar_en=nuevo)
    return nuevo


def id_evento(con: sqlite3.Connection, fuente: str, id_externo: str) -> int | None:
    """El evento que una fuente guardó con ese id suyo (`reunion:<id>`), o None."""
    f = con.execute("SELECT id FROM evento WHERE fuente = ? AND id_externo = ?", (fuente, id_externo)).fetchone()
    return f["id"] if f else None


def cerrar_compromisos(con: sqlite3.Connection, ids, estado: str, *, evento: int) -> int:
    """Cierra de una vez los compromisos de `ids` que sigan abiertos y hayan
    salido de `evento` (los de una reunión vieja, C-0380). Devuelve cuántos.

    🔴 Por ids y no «todos los del evento»: se cierran los que el dueño vio y
    confirmó (regla dura 3); uno que llegara entre medias no entra. Y del
    evento: un id de otra reunión colado en el formulario no se toca. Todos
    o ninguno, que un corte a medias dejaría la reunión partida en dos."""
    if estado not in ("hecho", "descartado"):
        raise ValueError("se cierran como «hecho» o «descartado»")
    abiertos = {c["id"] for c in compromisos(con, "abierto", n=10_000, evento=evento)}
    cerrar = sorted({int(i) for i in ids} & abiertos)
    with transaccion(con):
        for i in cerrar:
            cerrar_compromiso(con, i, estado)
    return len(cerrar)


def por_recordar(con: sqlite3.Connection, momento: str | None = None) -> list[dict]:
    """Los compromisos abiertos cuyo recordatorio ya toca y no se ha mandado."""
    return [dict(f) for f in con.execute(
        "SELECT * FROM compromiso WHERE estado = 'abierto' AND recordar_en IS NOT NULL"
        " AND recordado IS NULL AND recordar_en <= ? ORDER BY recordar_en", (momento or ahora(),))]


def marcar_recordado(con: sqlite3.Connection, id_: int) -> None:
    con.execute("UPDATE compromiso SET recordado = ? WHERE id = ?", (ahora(), id_))


# ───────────────────────────── bitácora y estado ─────────────────────────────


#: El `resultado` de un `hueco` que no apuntó el modelo con `no_se_hacer` sino
#: la red de `conversacion.contestar` (C-0324): se sabe en qué turno dijo que
#: no podía, no qué le faltaba. Lo cuenta aparte `api.secretario_huecos_sin_clasificar`.
HUECO_SIN_CLASIFICAR = "sin clasificar"


def apuntar(con: sqlite3.Connection, accion: str, *, nivel: str = "", params: dict | None = None,
            motivo: str = "", resultado: str = "", ok: bool = True) -> None:
    con.execute("INSERT INTO bitacora (cuando, accion, nivel, params, motivo, resultado, ok)"
                " VALUES (?,?,?,?,?,?,?)",
                (ahora(), accion, nivel, json.dumps(params or {}, ensure_ascii=False), motivo,
                 resultado[:2000], int(ok)))


def aprobadas_seguidas(con: sqlite3.Connection, accion: str) -> int:
    """Las veces que el dueño aprobó `accion` y salió bien desde su último
    rechazo o fallo. Es lo que pide la 303 para sugerir `auto` («cinco
    aprobaciones sin fallo»): contar todas sugería subir algo que acababa de
    rechazar (SEC-45)."""
    return con.execute(
        "SELECT COUNT(*) FROM bitacora WHERE accion = ? AND nivel = 'aprobada' AND ok = 1 AND id > COALESCE("
        "(SELECT MAX(id) FROM bitacora WHERE accion = ? AND (nivel = 'rechazada' OR (nivel = 'aprobada' AND ok = 0)))"
        ", 0)", (accion, accion)).fetchone()[0]


def bitacora(con: sqlite3.Connection, n: int = 100, desde: str | None = None) -> list[dict]:
    """Lo último que hizo, lo más nuevo primero. `desde`: ISO en UTC, como `cuando`."""
    if desde:
        return [dict(f) for f in con.execute("SELECT * FROM bitacora WHERE cuando >= ? ORDER BY id DESC LIMIT ?",
                                             (desde, n))]
    return [dict(f) for f in con.execute("SELECT * FROM bitacora ORDER BY id DESC LIMIT ?", (n,))]


def poner(con: sqlite3.Connection, clave: str, valor) -> None:
    con.execute("INSERT INTO estado (clave, valor) VALUES (?, ?) ON CONFLICT(clave) DO UPDATE SET"
                " valor = excluded.valor", (clave, json.dumps(valor, ensure_ascii=False)))


def quitar(con: sqlite3.Connection, clave: str) -> None:
    con.execute("DELETE FROM estado WHERE clave = ?", (clave,))


def anotar_fuente(con: sqlite3.Connection, fuente: str, cursor: str, *, error: str | None,
                  sumar: int = 0) -> None:
    """Por dónde va una fuente, cuándo se leyó y si falló."""
    con.execute(
        "INSERT INTO fuente_estado (fuente, cursor, leida, error, eventos) VALUES (?,?,?,?,?)"
        " ON CONFLICT(fuente) DO UPDATE SET cursor = excluded.cursor, leida = excluded.leida,"
        " error = excluded.error, eventos = fuente_estado.eventos + ?",
        (fuente, cursor, ahora(), error, sumar, sumar))


def estado_fuente(con: sqlite3.Connection, fuente: str) -> sqlite3.Row | None:
    return con.execute("SELECT * FROM fuente_estado WHERE fuente = ?", (fuente,)).fetchone()


def estados_fuentes(con: sqlite3.Connection) -> dict[str, dict]:
    return {f["fuente"]: dict(f) for f in con.execute("SELECT * FROM fuente_estado")}


def leer(con: sqlite3.Connection, clave: str, defecto=None):
    f = con.execute("SELECT valor FROM estado WHERE clave = ?", (clave,)).fetchone()
    return json.loads(f["valor"]) if f else defecto


def leer_sin_abrir(clave: str, defecto=None):
    """`leer` para quien no es `hub-secretario` (los avisos de `hub-web`): en
    sólo lectura, sin crear la base ni migrarla. Si no se puede leer, lanza
    `sqlite3.Error` y quien llama decide qué significa."""
    c = sqlite3.connect(f"file:{ruta()}?mode=ro", uri=True, timeout=5)
    try:
        f = c.execute("SELECT valor FROM estado WHERE clave = ?", (clave,)).fetchone()
    finally:
        c.close()
    return json.loads(f[0]) if f else defecto


def resolver_solicitud(con: sqlite3.Connection, sid: int, estado: str, resultado: str | None = None,
                       solo_pendiente: bool = False, de: str | None = None,
                       params: Any = None) -> sqlite3.Row | None:
    """Cambia el estado de una solicitud y la devuelve; None si no se tocó.

    La única que cambia el estado de una `solicitud` después de crearla
    (C-0050): la pantalla la aprueba o rechaza y el servicio la cierra, y cada
    uno tenía su UPDATE. (`olvidar_nota` le tapa el texto, no el estado.)

    `de`: el estado en el que tiene que estar; si no lo está, no se toca y
    devuelve None. Es como se **reclama** (C-0315): de dos que piden
    `"ejecutando", de="aprobada"` sólo uno recibe la fila, y sólo ése la
    ejecuta. `solo_pendiente=True` es `de="pendiente"`. Sin `de`, por id: así
    cierra quien la ejecutó, esté como esté.

    Los estados, que no tienen otra lista (el campo es texto libre):
    `pendiente` (espera su sí) → `aprobada` | `rechazada`; `aprobada` →
    `ejecutando` (reclamada: se está haciendo, o murió a mitad) → `hecha` |
    `fallo` | `caducada`; y `ejecutando` → `cortada` sólo lo que el servicio
    encontró a medias al arrancar (`servicio.recoger_cortadas`): no se sabe
    si se hizo, y es final.

    🔴 El reclamo (`ejecutando`) se asegura en disco antes de volver. La
    base va con `synchronous=NORMAL`, que en WAL puede perder el último
    commit en un corte de luz: si el perdido es éste, la solicitud vuelve a
    «aprobada» con la acción ya hecha y se repetiría. Sólo para esta
    escritura se pone FULL, y se deja como estaba. Dentro de una transacción
    ya abierta no se puede cambiar, y no se intenta.

    `params`: los que se quedan guardados, en la misma escritura y con la
    misma condición. Se pasan tapados al cerrarla (hecha, fallo, caducada,
    rechazada, cortada: C-0431): en claro sólo hacen falta mientras puede
    ejecutarse, y resuelta sigue en esta base y en sus catorce copias."""
    de = "pendiente" if solo_pendiente and de is None else de
    cond, extra = (" AND estado = ?", (de,)) if de is not None else ("", ())
    cambia, valores = "estado = ?, resuelta = ?", [estado, ahora()]
    if resultado is not None:
        cambia, valores = cambia + ", resultado = ?", [*valores, resultado[:2000]]
    if params is not None:
        cambia, valores = cambia + ", params = ?", [*valores, json.dumps(params, ensure_ascii=False)]
    antes = None
    if estado == "ejecutando" and not con.in_transaction:
        antes = int(con.execute("PRAGMA synchronous").fetchone()[0])
        con.execute("PRAGMA synchronous=FULL")
    try:
        cur = con.execute(f"UPDATE solicitud SET {cambia} WHERE id = ?{cond}", (*valores, sid, *extra))
    finally:
        if antes is not None:
            con.execute(f"PRAGMA synchronous={antes}")
    if not cur.rowcount:
        return None
    return con.execute("SELECT * FROM solicitud WHERE id = ?", (sid,)).fetchone()


def apuntar_llamada(trabajo: str, modelo: str, segundos: float, coste: float = 0.0,
                    entrada: int = 0, salida: int = 0, ok: bool = True) -> None:
    """Deja constancia de una llamada al modelo. Nunca rompe la llamada: si la
    base no se puede escribir, se pierde la medida y nada más."""
    try:
        con = conectar()
    except (OSError, sqlite3.Error):
        return
    try:
        con.execute("INSERT INTO llamada (fecha, trabajo, modelo, segundos, coste, entrada, salida, ok)"
                    " VALUES (?,?,?,?,?,?,?,?)",
                    (ahora(), trabajo, modelo, round(segundos, 2), coste, entrada, salida, 1 if ok else 0))
    except sqlite3.Error:
        pass
    finally:
        con.close()


def uso(con: sqlite3.Connection, dias: int = 7) -> list[dict]:
    """Por trabajo, en los últimos `dias`: llamadas, fallos, segundos de media y
    coste equivalente por API."""
    desde = (datetime.now(timezone.utc) - timedelta(days=dias)).isoformat(timespec="seconds")
    return [dict(f) for f in con.execute(
        "SELECT trabajo, COUNT(*) AS llamadas, SUM(1 - ok) AS fallos, ROUND(AVG(segundos), 1) AS segundos,"
        " ROUND(SUM(coste), 4) AS coste, SUM(entrada) AS entrada, SUM(salida) AS salida"
        " FROM llamada WHERE fecha >= ? GROUP BY trabajo ORDER BY llamadas DESC", (desde,))]


# ───────────────────────────── colas de trabajo aparte ─────────────────────────────


def encolar(con: sqlite3.Connection, clave: str, item: dict, *, igual=None) -> bool:
    """Pone `item` al final de la cola `clave` (en `estado`). False si ya había uno igual.

    La cola de lo que se hace aparte, en el hilo de los resúmenes: un resumen
    de sesión (C-0163), una investigación (385). La tocan dos procesos —el MCP
    encarga, el servicio atiende—, cada uno con su conexión: leer y escribir
    van en la misma transacción, o un encargo se perdería entre las dos.
    `igual(item)` dice qué lo hace el mismo encargo (`lambda x: x["sesion"]`);
    sin él, que sea idéntico."""
    clave_de = igual or (lambda x: x)
    with transaccion(con):
        cola = leer(con, clave) or []
        if any(clave_de(x) == clave_de(item) for x in cola):
            return False
        poner(con, clave, cola + [item])
    return True


def sacar(con: sqlite3.Connection, clave: str, *, en_curso: str | None = None,
          como: Callable[[dict], Any] | None = None) -> dict | None:
    """Saca el primero de la cola `clave`, o None si está vacía; en una
    transacción, así que dos que sacan a la vez nunca se llevan el mismo.

    Con `en_curso`, en la misma transacción deja en esa clave `como(item)`
    (o el item): entre sacarlo y marcarlo no hay un instante en que quien lo
    busca para cancelarlo no lo encuentre ni en la cola ni en curso (C-0241)."""
    with transaccion(con):
        cola = leer(con, clave) or []
        if not cola:
            return None
        poner(con, clave, cola[1:])
        if en_curso:
            poner(con, en_curso, como(cola[0]) if como else cola[0])
    return cola[0]


def devolver(con: sqlite3.Connection, clave: str, en_curso: str, *, rehacer: Callable[[Any], dict | None] | None = None,
             igual=None) -> tuple[Any, dict | None]:
    """Lo que quedó marcado en `en_curso` vuelve a la CABEZA de la cola `clave`
    y la marca se borra, en una transacción (C-0308): es lo que `sacar` dejó a
    medias en un servicio que murió, y ya esperó su turno una vez.

    Devuelve `(lo que había en la marca, lo que quedó en la cola)`; `(None,
    None)` si no había nada. `rehacer(lo que había)` da el item que vuelve —la
    marca no tiene por qué ser el item—, o None si no debe volver: la marca se
    borra igual. Con `igual`, si ya espera uno igual no se duplica y se queda
    el que estaba, en su sitio.

    🔴 Sólo la llama quien sabe que nadie está haciendo lo marcado: el
    servicio al arrancar, en el mismo hilo que después atiende la cola. A
    mitad de una investigación viva la pondría a correr dos veces."""
    clave_de = igual or (lambda x: x)
    with transaccion(con):
        habia = leer(con, en_curso)
        if habia is None:
            return None, None
        item = rehacer(habia) if rehacer else habia
        if item is not None:
            cola = leer(con, clave) or []
            ya = next((x for x in cola if clave_de(x) == clave_de(item)), None)
            if ya is not None:
                item = ya
            else:
                poner(con, clave, [item] + cola)
        quitar(con, en_curso)
    return habia, item


def retirar(con: sqlite3.Connection, clave: str, quitar: Callable[[dict], bool]) -> list[dict]:
    """Quita de la cola `clave` los que cumplen `quitar(item)` y los devuelve,
    en una transacción como `encolar` y `sacar` (C-0241: cancelar lo que aún
    espera)."""
    with transaccion(con):
        cola = leer(con, clave) or []
        fuera = [x for x in cola if quitar(x)]
        if fuera:
            poner(con, clave, [x for x in cola if not quitar(x)])
    return fuera
