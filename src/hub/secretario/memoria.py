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

import hashlib
import json
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .. import config
from ..db import transaccion
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


def carpeta() -> Path:
    d = config.HUB_HOME / "secretario"
    d.mkdir(parents=True, exist_ok=True)
    return d


def ruta() -> Path:
    return carpeta() / "memoria.db"


def conectar(r: Path | None = None) -> sqlite3.Connection:
    con = sqlite3.connect(r or ruta(), timeout=10.0, isolation_level=None)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=NORMAL")
    con.execute("PRAGMA foreign_keys=ON")
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
    return con


def existe() -> bool:
    return ruta().is_file()


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


def buscar(con: sqlite3.Connection, texto: str, *, fuente: str | None = None, desde: str | None = None,
           hasta: str | None = None, n: int = 12) -> list[dict]:
    """Eventos y notas que casan con `texto`, los mejores primero, con su origen.

    Primero exige todos los términos; si no sale nada, se conforma con alguno.
    Lo segundo trae ruido, pero «no encontré nada» cuando sí había es peor: el
    dueño deja de preguntar.
    """
    salida: list[dict] = []
    for modo in ("AND", "OR"):
        q = _consulta_fts(texto, modo)
        if not q:
            break
        filtros, params = "", [q]
        if fuente:
            filtros += " AND e.fuente = ?"
            params.append(fuente)
        if desde:
            filtros += " AND e.fecha >= ?"
            params.append(desde)
        if hasta:
            filtros += " AND e.fecha <= ?"
            params.append(hasta)
        filas = con.execute(
            "SELECT e.id, e.fuente, e.conversacion, e.autor, e.fecha, e.texto, e.enlace, bm25(evento_fts) AS r"
            " FROM evento_fts JOIN evento e ON e.id = evento_fts.rowid"
            f" WHERE evento_fts MATCH ? {filtros} ORDER BY r LIMIT ?", (*params, n)).fetchall()
        notas = [] if fuente else con.execute(
            "SELECT n.id, n.texto, n.tema, n.origen, n.creada, bm25(nota_fts) AS r"
            " FROM nota_fts JOIN nota n ON n.id = nota_fts.rowid WHERE nota_fts MATCH ?"
            " ORDER BY r LIMIT ?", (q, n)).fetchall()
        salida = ([{"tipo": "nota", "id": f["id"], "texto": f["texto"], "tema": f["tema"],
                    "origen": f["origen"], "fecha": f["creada"], "r": f["r"]} for f in notas]
                  + [{"tipo": "mensaje", "id": f["id"], "fuente": f["fuente"], "conversacion": f["conversacion"],
                      "autor": f["autor"], "fecha": f["fecha"], "texto": f["texto"][:1500],
                      "enlace": f["enlace"], "r": f["r"]} for f in filas])
        if salida:
            break
    salida.sort(key=lambda x: x["r"])
    for x in salida:
        x.pop("r", None)
    return salida[:n]


def recientes(con: sqlite3.Connection, *, fuente: str | None = None, conversacion: str | None = None,
              desde: str | None = None, n: int = 40, solo_para_mi: bool = False) -> list[dict]:
    """Lo último que llegó, sin buscar: «¿qué se dijo hoy en el grupo?», y con
    `solo_para_mi`, «¿qué me pidieron a mí?» (decisión 332)."""
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
    donde = ("WHERE " + " AND ".join(filtros)) if filtros else ""
    filas = con.execute(f"SELECT id, fuente, conversacion, autor, fecha, texto, enlace, para_mi FROM evento {donde}"
                        " ORDER BY fecha DESC LIMIT ?", (*params, n)).fetchall()
    return [dict(f) | {"texto": f["texto"][:1500]} for f in filas]


def conversaciones(con: sqlite3.Connection) -> list[dict]:
    return [dict(f) for f in con.execute(
        "SELECT fuente, conversacion, COUNT(*) AS mensajes, MAX(fecha) AS ultimo FROM evento"
        " GROUP BY fuente, conversacion ORDER BY ultimo DESC")]


# ───────────────────────────── notas ─────────────────────────────


def anotar(con: sqlite3.Connection, texto: str, *, tema: str = "", evento: int | None = None,
           origen: str = "") -> int:
    return con.execute("INSERT INTO nota (texto, tema, evento, origen, creada) VALUES (?,?,?,?,?)",
                       (texto.strip(), tema.strip(), evento, origen, ahora())).lastrowid


def notas(con: sqlite3.Connection, n: int = 100) -> list[dict]:
    return [dict(f) for f in con.execute("SELECT * FROM nota ORDER BY id DESC LIMIT ?", (n,))]


def editar_nota(con: sqlite3.Connection, id_: int, texto: str, tema: str | None = None) -> None:
    if tema is None:
        con.execute("UPDATE nota SET texto = ?, editada = ? WHERE id = ?", (texto.strip(), ahora(), id_))
    else:
        con.execute("UPDATE nota SET texto = ?, tema = ?, editada = ? WHERE id = ?",
                    (texto.strip(), tema.strip(), ahora(), id_))


def borrar_nota(con: sqlite3.Connection, id_: int) -> None:
    con.execute("DELETE FROM nota WHERE id = ?", (id_,))


# ───────────────────────────── compromisos ─────────────────────────────


def comprometer(con: sqlite3.Connection, que: str, *, quien: str = "yo", para_quien: str = "",
                vence: str | None = None, recordar_en: str | None = None, evento: int | None = None,
                origen: str = "") -> int:
    """Un compromiso nuevo, salvo que ya haya uno abierto igual (el triaje ve el
    mismo «mañana te lo mando» en dos mensajes seguidos).

    Si ya había uno igual y llegan fechas, **las fechas nuevas mandan**: «el de
    los PRs, recuérdamelo el lunes» sobre uno que vencía el martes pasado se
    quedaba con la fecha vieja, y el modelo, viéndolo vencido, lo descartó
    (medido el 2026-10-24). Lo último que dijo el dueño es lo que vale."""
    igual = con.execute("SELECT id FROM compromiso WHERE estado = 'abierto' AND lower(que) = lower(?)"
                        " AND quien = ?", (que.strip(), quien or "yo")).fetchone()
    if igual:
        if vence or recordar_en:
            reprogramar(con, igual["id"], vence=vence, recordar_en=recordar_en)
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


def compromisos(con: sqlite3.Connection, estado: str | None = "abierto", n: int = 200) -> list[dict]:
    if estado:
        filas = con.execute("SELECT * FROM compromiso WHERE estado = ? ORDER BY vence IS NULL, vence, id"
                            " LIMIT ?", (estado, n))
    else:
        filas = con.execute("SELECT * FROM compromiso ORDER BY id DESC LIMIT ?", (n,))
    return [dict(f) for f in filas]


def cerrar_compromiso(con: sqlite3.Connection, id_: int, estado: str = "hecho") -> None:
    if estado not in ("hecho", "descartado", "abierto"):
        raise ValueError("estado no válido")
    con.execute("UPDATE compromiso SET estado = ?, cerrado = ? WHERE id = ?",
                (estado, None if estado == "abierto" else ahora(), id_))


def por_recordar(con: sqlite3.Connection, momento: str | None = None) -> list[dict]:
    """Los compromisos abiertos cuyo recordatorio ya toca y no se ha mandado."""
    return [dict(f) for f in con.execute(
        "SELECT * FROM compromiso WHERE estado = 'abierto' AND recordar_en IS NOT NULL"
        " AND recordado IS NULL AND recordar_en <= ? ORDER BY recordar_en", (momento or ahora(),))]


def marcar_recordado(con: sqlite3.Connection, id_: int) -> None:
    con.execute("UPDATE compromiso SET recordado = ? WHERE id = ?", (ahora(), id_))


# ───────────────────────────── bitácora y estado ─────────────────────────────


def apuntar(con: sqlite3.Connection, accion: str, *, nivel: str = "", params: dict | None = None,
            motivo: str = "", resultado: str = "", ok: bool = True) -> None:
    con.execute("INSERT INTO bitacora (cuando, accion, nivel, params, motivo, resultado, ok)"
                " VALUES (?,?,?,?,?,?,?)",
                (ahora(), accion, nivel, json.dumps(params or {}, ensure_ascii=False), motivo,
                 resultado[:2000], int(ok)))


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
                       solo_pendiente: bool = False) -> sqlite3.Row | None:
    """Cambia el estado de una solicitud y la devuelve; None si no se tocó.

    La única que escribe `solicitud` después de crearla (C-0050): la pantalla
    la aprueba o rechaza y el servicio la cierra, y cada uno tenía su UPDATE."""
    cond = " AND estado = 'pendiente'" if solo_pendiente else ""
    if resultado is None:
        cur = con.execute(f"UPDATE solicitud SET estado = ?, resuelta = ? WHERE id = ?{cond}", (estado, ahora(), sid))
    else:
        cur = con.execute(f"UPDATE solicitud SET estado = ?, resuelta = ?, resultado = ? WHERE id = ?{cond}",
                          (estado, ahora(), resultado[:2000], sid))
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


def sacar(con: sqlite3.Connection, clave: str) -> dict | None:
    """Saca el primero de la cola `clave`, o None si está vacía; en una
    transacción, así que dos que sacan a la vez nunca se llevan el mismo."""
    with transaccion(con):
        cola = leer(con, clave) or []
        if not cola:
            return None
        poner(con, clave, cola[1:])
    return cola[0]
