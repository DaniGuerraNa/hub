"""SQLite en modo WAL.

Es el ÍNDICE, no la fuente de verdad (decisión 2). La verdad son los archivos de
cada proyecto y git. Si esto se corrompe, se reconstruye escaneando — por eso no
hay que temerle a un cambio de esquema.

WAL aguanta apagones y deja leer mientras el snapshotter escribe.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from . import config

ESQUEMA = """
CREATE TABLE IF NOT EXISTS proyecto (
    id            TEXT PRIMARY KEY,
    nombre        TEXT NOT NULL,
    dominio       TEXT NOT NULL DEFAULT 'personal',
    tipo          TEXT NOT NULL DEFAULT 'proyecto',  -- proyecto | kit
    asiento       TEXT,
    estado_ref    TEXT,
    base_version  TEXT,
    guardrail     TEXT NOT NULL DEFAULT 'ask',
    status        TEXT NOT NULL DEFAULT 'activo',
    nota          TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS proyecto_ruta (
    proyecto_id TEXT NOT NULL REFERENCES proyecto(id) ON DELETE CASCADE,
    ruta        TEXT NOT NULL,
    tipo        TEXT NOT NULL DEFAULT 'repo',
    PRIMARY KEY (proyecto_id, ruta)
);

CREATE TABLE IF NOT EXISTS slot (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    proyecto_id      TEXT NOT NULL REFERENCES proyecto(id) ON DELETE CASCADE,
    nombre           TEXT NOT NULL,
    ruta             TEXT,
    nota             TEXT NOT NULL DEFAULT '',
    comando          TEXT,
    autostart_claude INTEGER NOT NULL DEFAULT 0,
    status           TEXT NOT NULL DEFAULT 'activo',
    creado_en        TEXT NOT NULL,
    ultima_actividad TEXT
);
CREATE INDEX IF NOT EXISTS idx_slot_proyecto ON slot(proyecto_id, status);

CREATE TABLE IF NOT EXISTS snapshot (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    tomado_en   TEXT NOT NULL,
    server_pid  INTEGER,
    preservado  INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_snapshot_ts ON snapshot(tomado_en DESC);

CREATE TABLE IF NOT EXISTS panel (
    snapshot_id INTEGER NOT NULL REFERENCES snapshot(id) ON DELETE CASCADE,
    pane_id     TEXT NOT NULL,
    session     TEXT NOT NULL,
    window_idx  INTEGER NOT NULL,
    pane_idx    INTEGER NOT NULL,
    cwd         TEXT NOT NULL,
    titulo      TEXT NOT NULL DEFAULT '',
    comando     TEXT NOT NULL DEFAULT '',
    etiqueta    TEXT NOT NULL DEFAULT '',
    proyecto_id TEXT,
    slot_id     INTEGER
);
CREATE INDEX IF NOT EXISTS idx_panel_snapshot ON panel(snapshot_id);

-- Binding explícito panel -> slot. Efímero por naturaleza: el pane_id de tmux
-- sólo es estable mientras viva el servidor, por eso se guarda con su epoch.
CREATE TABLE IF NOT EXISTS binding (
    pane_id    TEXT NOT NULL,
    server_pid INTEGER NOT NULL,
    slot_id    INTEGER NOT NULL REFERENCES slot(id) ON DELETE CASCADE,
    visto_en   TEXT NOT NULL,
    PRIMARY KEY (pane_id, server_pid)
);

-- ── Catálogo ───────────────────────────────────────────────────────────────
-- Todo derivado del filesystem: se borra y se rehace en cada escaneo.

CREATE TABLE IF NOT EXISTS capacidad (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    proyecto_id TEXT NOT NULL,
    tipo        TEXT NOT NULL,   -- agente | skill | metodo | script
    nombre      TEXT NOT NULL,
    ruta        TEXT NOT NULL,
    descripcion TEXT NOT NULL DEFAULT '',
    modelo      TEXT,
    status      TEXT NOT NULL DEFAULT 'activo',  -- activo | incompleto | deprecated
    origen      TEXT NOT NULL DEFAULT 'convencion',
    modificado  TEXT,            -- cuándo se editó
    usado       TEXT,            -- cuándo se usó de verdad (transcripts)
    -- Un método es un documento que se lee, no algo invocable por nombre:
    -- medirlo con la misma vara lo marcaría como olvidado siempre.
    medible     INTEGER NOT NULL DEFAULT 1,
    riesgos     TEXT
);
CREATE INDEX IF NOT EXISTS idx_capacidad_proyecto ON capacidad(proyecto_id, tipo);

CREATE TABLE IF NOT EXISTS dependencia (
    kit_id        TEXT NOT NULL,
    consumidor_id TEXT NOT NULL,
    origen        TEXT NOT NULL,
    destino       TEXT NOT NULL,
    estado        TEXT NOT NULL,  -- igual | difiere | divergencia-declarada | falta | sin-origen
    PRIMARY KEY (kit_id, consumidor_id, destino)
);

CREATE TABLE IF NOT EXISTS divergencia (
    kit_id        TEXT NOT NULL,
    consumidor_id TEXT NOT NULL,
    archivo       TEXT NOT NULL,
    razon         TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (kit_id, consumidor_id, archivo)
);

-- Paneles que el usuario descartó explícitamente de la bandeja de entrada.
CREATE TABLE IF NOT EXISTS descartado (
    pane_id    TEXT NOT NULL,
    server_pid INTEGER NOT NULL,
    PRIMARY KEY (pane_id, server_pid)
);

-- ── Respaldo de repos ──────────────────────────────────────────────────────
-- El hub nació de descubrir 473 commits sin respaldo. Derivado de git:
-- se borra y se rehace en cada escaneo.

CREATE TABLE IF NOT EXISTS repo (
    proyecto_id   TEXT NOT NULL,
    ruta          TEXT NOT NULL,
    rama          TEXT NOT NULL DEFAULT '',
    sin_push      INTEGER,          -- NULL = no hay contra qué comparar
    regimen       TEXT NOT NULL DEFAULT '',  -- con-upstream | sin-upstream | sin-remoto
    detras        INTEGER,
    sucios        INTEGER NOT NULL DEFAULT 0,
    ultimo_commit TEXT,
    worktrees     INTEGER NOT NULL DEFAULT 0,
    -- Worktrees del mismo repo comparten commits: sin esto, `~/dev/app`
    -- y `~/dev/app-int` sumarían 500 donde sólo hay 250.
    repo_comun    TEXT,
    head          TEXT,
    medido_en     TEXT NOT NULL,
    PRIMARY KEY (ruta)
);

-- ── Servicios Docker ───────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS servicio (
    contenedor       TEXT PRIMARY KEY,
    proyecto_id      TEXT,
    imagen           TEXT NOT NULL DEFAULT '',
    estado           TEXT NOT NULL DEFAULT '',
    detalle          TEXT NOT NULL DEFAULT '',
    creado           TEXT NOT NULL DEFAULT '',
    ultima_vez_visto TEXT,
    medido_en        TEXT NOT NULL
);

-- ── Conexiones ─────────────────────────────────────────────────────────────
-- 🔴 Sólo datos de conexión y punteros. Nunca el secreto (decisión 28).
CREATE TABLE IF NOT EXISTS conexion (
    alias              TEXT PRIMARY KEY,
    host               TEXT,
    usuario            TEXT,
    proposito          TEXT NOT NULL DEFAULT '',
    referencia_secreto TEXT,
    puntero_ok         INTEGER,     -- NULL = no se puede comprobar (p. ej. una URL)
    nota               TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS conexion_proyecto (
    alias       TEXT NOT NULL,
    proyecto_id TEXT NOT NULL,
    PRIMARY KEY (alias, proyecto_id)
);
"""

# FTS5 no está en todos los builds de SQLite. Si falta, la búsqueda cae a LIKE
# (ver `busqueda.py`): degradar es preferible a que el hub no arranque.
ESQUEMA_FTS = """
CREATE VIRTUAL TABLE IF NOT EXISTS indice USING fts5(
    clase, ref, titulo, cuerpo, proyecto_id UNINDEXED, tokenize='unicode61'
);
"""


class BaseIlegible(RuntimeError):
    """El índice no se puede abrir ni leer, y hay que decir qué hacer.

    La cabecera de este módulo dice que si esto se corrompe «se reconstruye
    escaneando». Era verdad como principio y mentira como experiencia: no había
    nada que lo detectara ni nada que lo dijera. Una `hub.db` corrupta —o un
    `HUB_HOME` sin permiso de escritura, o un disco lleno— tumbaba las siete
    pantallas a `Internal Server Error` desnudo, y quien lo veía no tenía forma
    de saber que la cura era renombrar un archivo.

    🔴 No se repara sola, y es deliberado: casi todo aquí se reconstruye
    escaneando, pero **las notas y los slots no viven en ningún otro sitio**
    (por eso `desinstalar.sh` no borra `HUB_HOME` sin que lo pidas). Borrar
    automáticamente convertiría una avería recuperable en una pérdida.
    """


def _porque_no_abre(ruta: Path, exc: Exception) -> str:
    """El diagnóstico y el remedio, en la misma frase.

    🔴 El remedio que se propone es DESTRUCTIVO —renombrar la base se lleva las
    notas y los slots—, así que decir «corrupto» cuando no lo está es peor que
    no decir nada. La primera versión de esta función mandaba a la basura una
    base perfectamente sana en cuanto estaba bloqueada por otro proceso, que en
    este hub es lo más normal del mundo: el snapshotter escribe cada 20 s.
    """
    detalle = str(exc)
    if "locked" in detalle or "busy" in detalle:
        return (
            "La base está ocupada por otro proceso y no se pudo leer a tiempo.\n\n"
            "NO está corrupta y no hay que tocar nada: recarga en unos segundos. "
            "Si se repite, mira si hay más de un snapshotter corriendo:\n\n"
            "    systemctl --user status hub-snapshotter\n\n"
            f"Detalle: {detalle}"
        )
    if "readonly" in detalle or "unable to open" in detalle or "permission" in detalle:
        return (
            f"No se puede escribir en {ruta}. Comprueba permisos y espacio libre "
            f"en el disco.\n\nDetalle: {detalle}"
        )
    return (
        f"El índice {ruta} está corrupto.\n\n"
        f"Se reconstruye escaneando, así que puedes renombrarlo y volver a "
        f"arrancar:\n\n    mv {ruta} {ruta}.roto\n\n"
        f"🔴 Con él se van tus notas y tus slots, que son lo único del hub que "
        f"no está en ningún otro sitio. Renómbralo, no lo borres.\n\n"
        f"Detalle: {detalle}"
    )


def conectar(ruta: Path | None = None) -> sqlite3.Connection:
    ruta = ruta or config.DB_PATH
    try:
        ruta.parent.mkdir(parents=True, exist_ok=True)
        con = sqlite3.connect(ruta, timeout=10.0, isolation_level=None)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA synchronous=NORMAL")
        con.execute("PRAGMA foreign_keys=ON")
        return con
    except (sqlite3.Error, OSError) as exc:
        raise BaseIlegible(_porque_no_abre(ruta, exc)) from exc


# Columnas añadidas después de que la base ya existía. `CREATE TABLE IF NOT
# EXISTS` no las agrega a una tabla vieja, así que se aseguran una a una.
_COLUMNAS_NUEVAS = [
    ("capacidad", "medible", "INTEGER NOT NULL DEFAULT 1"),
    ("proyecto", "tipo", "TEXT NOT NULL DEFAULT 'proyecto'"),
    ("repo", "repo_comun", "TEXT"),
    ("repo", "head", "TEXT"),
    # Cuándo se escaneó el catálogo. Sin esto, `/inventario` enseñaba una
    # foto de hace una semana igual que una recién medida: la pantalla no
    # tenía forma de decir cuál de las dos estaba viendo.
    ("capacidad", "medido_en", "TEXT"),
]


def hay_fts(con: sqlite3.Connection) -> bool:
    return con.execute("SELECT 1 FROM pragma_module_list WHERE name='fts5'").fetchone() is not None


def _asegurar_columna(con: sqlite3.Connection, tabla: str, columna: str, tipo: str) -> None:
    existentes = {f["name"] for f in con.execute(f"PRAGMA table_info({tabla})")}
    if existentes and columna not in existentes:
        con.execute(f"ALTER TABLE {tabla} ADD COLUMN {columna} {tipo}")


def inicializar(con: sqlite3.Connection) -> None:
    con.executescript(ESQUEMA)
    for tabla, columna, tipo in _COLUMNAS_NUEVAS:
        _asegurar_columna(con, tabla, columna, tipo)
    try:
        con.executescript(ESQUEMA_FTS)
    except sqlite3.OperationalError:
        pass  # sin FTS5 la búsqueda usa LIKE; no es motivo para no arrancar


def abrir() -> sqlite3.Connection:
    con = conectar()
    try:
        inicializar(con)
    except sqlite3.DatabaseError as exc:
        # Una base medio corrupta ABRE sin quejarse y revienta en la primera
        # consulta. Aquí se paga una comprobación barata a cambio de que el
        # fallo salga con nombre y remedio en vez de en la vista de turno.
        con.close()
        raise BaseIlegible(_porque_no_abre(config.DB_PATH, exc)) from exc
    return con
