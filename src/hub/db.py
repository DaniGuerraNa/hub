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
    restaurar        INTEGER NOT NULL DEFAULT 0,
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

-- Ventanas que no quiere tener delante: servidores de node, logs, una shell
-- suelta. No se borra nada ni se toca tmux — sólo dejan de ocupar sitio en la
-- bandeja.
--
-- 🔴 Se identifica por NOMBRE, no por `pane_id`, y ésa es toda la diferencia con
-- `descartado`. Un `pane_id` muere con el servidor de tmux y además se RECICLA:
-- al reiniciar, `%0` es otra ventana cualquiera. Un descarte por panel se
-- deshace solo cada vez que se reinicia tmux —justo lo que no sirve para un
-- servidor de node que está siempre— y, peor, podría esconder una ventana
-- distinta que heredó el identificador.
--
-- `window_idx` NULL significa la sesión entera. Ocultar UNA ventana va por
-- índice, y el índice sí se mueve si se reordenan o se cierra una anterior: es
-- el precio de poder ocultar una sola, y por eso lo que se oculta se enseña
-- siempre contado y se puede volver a mostrar de un clic.
CREATE TABLE IF NOT EXISTS oculto (
    session    TEXT NOT NULL,
    window_idx INTEGER,
    creado_en  TEXT NOT NULL
);
-- NULL no es igual a NULL en un PRIMARY KEY, así que «la sesión entera» podría
-- guardarse dos veces. El índice sobre `IFNULL` es lo que hace que `INSERT OR
-- IGNORE` de verdad ignore el duplicado.
CREATE UNIQUE INDEX IF NOT EXISTS idx_oculto ON oculto(session, IFNULL(window_idx, -1));

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

-- ── Consumo de tokens ──────────────────────────────────────────────────────
-- Leído del registro de Claude Code (`~/.claude/projects/*.jsonl`), no medido
-- por el hub: se borra y se rehace en cada escaneo, como `repo`.
--
-- La clave es (ruta, día, modelo) y no el proyecto: el proyecto se recalcula al
-- escanear, así que dar de alta uno nuevo reclasifica su historia sola. Y el
-- modelo va en la clave porque un token de Opus y uno de Haiku no son la misma
-- cosa; sumarlos sin poder separarlos después sería tirar la única parte del
-- dato que dice cuánto pesa.
CREATE TABLE IF NOT EXISTS consumo (
    proyecto_id TEXT,             -- NULL = ese cwd no cae en ningún proyecto
    ruta        TEXT NOT NULL,
    dia         TEXT NOT NULL,
    modelo      TEXT NOT NULL,
    peticiones  INTEGER NOT NULL DEFAULT 0,
    entrada     INTEGER NOT NULL DEFAULT 0,
    escritura   INTEGER NOT NULL DEFAULT 0,   -- caché escrita
    lectura     INTEGER NOT NULL DEFAULT 0,   -- caché leída
    salida      INTEGER NOT NULL DEFAULT 0,
    -- Está DENTRO de `salida`, no al lado. Sumarlo al total lo contaría dos veces.
    razonado    INTEGER NOT NULL DEFAULT 0,
    -- Cuántas de esas peticiones razonaron. Sin esto, «4,5 M de razonamiento
    -- sobre 64,7 M de salida» se lee como «razona poco en cada turno», y lo que
    -- pasa de verdad es que sólo el 13 % de las peticiones razonó.
    razonadas   INTEGER NOT NULL DEFAULT 0,
    desde       TEXT NOT NULL DEFAULT '',
    hasta       TEXT NOT NULL DEFAULT '',
    medido_en   TEXT NOT NULL,
    PRIMARY KEY (ruta, dia, modelo)
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

-- ── Canal de consulta ───────────────────────────────────────────────────────
--
-- Que Claude pueda preguntarle a otra persona cuando el stakeholder no está.
-- El diseño entero y sus porqués, en PLAN-TELEGRAM.md.
--
-- 🔴 Aquí no hay ningún secreto. El token del bot vive fuera, en un archivo con
-- permisos propios, y de él sólo se guarda un puntero (regla dura 5).

CREATE TABLE IF NOT EXISTS canal_usuario (
    -- El `id` de Telegram y NO el @username: el username lo cambia su dueño
    -- cuando quiere y el id no se puede cambiar. Colgar los permisos del
    -- username los perdería —o peor, se los daría a otro— sin que nadie lo note.
    user_id   INTEGER PRIMARY KEY,
    alias     TEXT NOT NULL DEFAULT '',   -- el nombre que le pone el dueño del hub
    username  TEXT NOT NULL DEFAULT '',   -- informativo, para reconocerlo al darlo de alta
    nombre    TEXT NOT NULL DEFAULT '',   -- ídem, el que trae Telegram
    -- pendiente = escribió al bot y no tiene NADA. Es el estado inicial y el
    -- único que se alcanza solo: dar de alta es siempre un acto del dueño.
    estado    TEXT NOT NULL DEFAULT 'pendiente',  -- pendiente | activo | bloqueado
    visto_en  TEXT NOT NULL,
    nota      TEXT NOT NULL DEFAULT '',
    -- Quién recibe los AVISOS de las preguntas que son para el dueño del hub.
    -- A él no le viaja el contenido: sólo «hay una pregunta», y la lee dentro.
    es_dueno  INTEGER NOT NULL DEFAULT 0,
    -- El tutorial que el propio bot le manda para explicarle cómo se contesta.
    -- '' = nunca · 'pedido' = encolado, lo manda el relé · ISO = cuándo se mandó.
    --
    -- Lo ENCOLA la web y lo MANDA el relé, y no es ceremonia: hub-web no tiene
    -- el token del bot a propósito (es el que expone el puerto, regla dura 8),
    -- así que no puede escribir a nadie ni queriendo.
    tutorial      TEXT NOT NULL DEFAULT '',
    -- El mensaje del tutorial al que se le pide practicar el `reply`. Contestarlo
    -- es el único ensayo posible sin gastarle una pregunta de verdad.
    tutorial_msg  INTEGER
);

-- Denegar por defecto: sin fila, no hay permiso. No existe el comodín ni el
-- permiso global, y es deliberado — con uno, añadir un proyecto se lo regalaría
-- a quien ya tuviera acceso sin que nadie lo decidiera.
CREATE TABLE IF NOT EXISTS canal_permiso (
    user_id     INTEGER NOT NULL REFERENCES canal_usuario(user_id) ON DELETE CASCADE,
    proyecto_id TEXT NOT NULL REFERENCES proyecto(id) ON DELETE CASCADE,
    accion      TEXT NOT NULL,   -- recibir-preguntas | responder | leer-estado
    dado_en     TEXT NOT NULL,
    PRIMARY KEY (user_id, proyecto_id, accion)
);

CREATE TABLE IF NOT EXISTS canal_pregunta (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    proyecto_id TEXT NOT NULL REFERENCES proyecto(id) ON DELETE CASCADE,
    slot_id     INTEGER,          -- a qué panel vuelve la respuesta
    pane_id     TEXT,             -- el que había al preguntar; se revalida al entregar
    user_id     INTEGER,          -- NULL = es para el dueño: sólo se le avisa
    texto       TEXT NOT NULL,
    -- El id del mensaje en Telegram. Es la clave con la que se casa la
    -- respuesta: llega como `reply_to_message` y no hay que adivinar nada.
    message_id  INTEGER,
    estado      TEXT NOT NULL DEFAULT 'pendiente',
                -- pendiente | enviada | respondida | entregada | sin-confirmar
                -- | vencida | archivada
    -- Preguntas que viajan juntas y VUELVEN juntas. NULL = suelta.
    lote        TEXT,
    creada_en   TEXT NOT NULL,
    enviada_en  TEXT,
    vence_en    TEXT,             -- lo fija el pacto, no el hub
    respuesta   TEXT NOT NULL DEFAULT '',
    respondida_en TEXT,
    entregada_en  TEXT,
    detalle     TEXT NOT NULL DEFAULT ''   -- por qué no se pudo entregar, si pasó
);
CREATE INDEX IF NOT EXISTS idx_pregunta_estado ON canal_pregunta(estado, vence_en);
CREATE INDEX IF NOT EXISTS idx_pregunta_msg ON canal_pregunta(message_id);

-- Todo lo que entra y sale, íntegro. Es la monitorización que se pidió, y es lo
-- que permite auditar después qué se envió exactamente — que importa porque lo
-- que sale de aquí sale de la máquina.
CREATE TABLE IF NOT EXISTS canal_registro (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    momento     TEXT NOT NULL,
    direccion   TEXT NOT NULL,   -- sale | entra | falla
    user_id     INTEGER,
    proyecto_id TEXT,
    pregunta_id INTEGER,
    detalle     TEXT NOT NULL DEFAULT '',
    cuerpo      TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_registro_momento ON canal_registro(momento DESC);

-- ── Mensajes programados ────────────────────────────────────────────────────
--
-- Un texto que se escribe en el panel de un slot a una hora. Lo escribe el
-- dueño del hub y va a su propia terminal, así que NO lleva el marco de
-- `entrega.marcar`, que existe para lo que entra de fuera (regla dura 22).
--
-- 🔴 `cuando` va en UTC, como todo lo demás de esta base. La hora local la pone
-- y la lee el navegador: el servidor no adivina zonas. Con CST (UTC−6) una
-- confusión aquí no es un detalle, son seis horas.
--
-- No hay `pane_id`: el panel se resuelve EN EL INSTANTE de entregar, desde el
-- slot. Guardarlo al programar sería fijar un permiso que caduca — entre
-- programar y entregar pueden pasar horas y el slot puede vivir ya en otra
-- ventana (regla dura 15).
CREATE TABLE IF NOT EXISTS mensaje_programado (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    slot_id     INTEGER NOT NULL REFERENCES slot(id) ON DELETE CASCADE,
    texto       TEXT NOT NULL,
    cuando      TEXT NOT NULL,            -- UTC, ISO 8601
    estado      TEXT NOT NULL DEFAULT 'pendiente',
                -- pendiente | entregando | entregado | no-entregado
                -- | caducado | sin-confirmar | cancelado
                --
                -- 🔴 «entregando» se escribe ANTES de tocar el panel, y por
                -- eso es lo que garantiza UN SOLO intento: un mensaje que se
                -- quede ahí es uno cuyo proceso murió a mitad, y no se
                -- reintenta — se enseña para que lo mire una persona.
    creado_en   TEXT NOT NULL,
    intentado_en TEXT,                    -- último intento, haya salido o no
    entregado_en TEXT,
    motivo      TEXT NOT NULL DEFAULT ''  -- por qué no se pudo, si no se pudo
);
CREATE INDEX IF NOT EXISTS idx_programado_cuando
    ON mensaje_programado(estado, cuando);

-- ── Lo que el relé ya vio, para no avisar dos veces ─────────────────────────
--
-- Una fila por panel de slot —y una, `hub`, por el latido—. NO es estado: es
-- una caché de lo último que se vio, reconstruible mirando tmux (regla dura 1).
-- Perderla cuesta silencio, no avisos repetidos: `avisos.py` no avisa nunca del
-- primer vistazo, sólo de una parada que vio producirse.
--
-- `desde` es la edad del episodio y sólo se mueve cuando el estado cambia; es
-- lo único contra lo que tiene sentido comparar un umbral. `avisado` se limpia
-- en cada cambio, y eso es lo que hace que cada episodio avise UNA vez.
CREATE TABLE IF NOT EXISTS aviso (
    clave   TEXT PRIMARY KEY,   -- el `pane_id`, o «hub» para el latido
    estado  TEXT NOT NULL,
    previo  TEXT,               -- de dónde viene el episodio; NULL si es el primero
    desde   TEXT NOT NULL,      -- UTC, cuándo empezó este episodio
    avisado TEXT                -- UTC, cuándo salió su aviso; NULL si no salió
);

-- ── La salud de la máquina, medida en el ciclo lento ───────────────────────
--
-- Una fila por magnitud y sólo la ÚLTIMA: no es un histórico. Volver a medir la
-- reconstruye entera (regla dura 1), y guardar la serie convertiría al hub en un
-- sistema de monitorización, que es lo que el principio 9 dice que no es.
--
-- `valor` a NULL con `texto` lleno es una fecha o un nombre —cuándo arrancó
-- Windows, qué GPU hay—; las dos formas conviven porque la pantalla y las
-- alarmas leen de la misma tabla y no de dos.
CREATE TABLE IF NOT EXISTS maquina (
    clave     TEXT PRIMARY KEY,
    valor     REAL,
    texto     TEXT NOT NULL DEFAULT '',
    unidad    TEXT NOT NULL DEFAULT '',
    medido_en TEXT NOT NULL
);

-- ── Encargos: un MVP descrito por audio ─────────────────────────────────────
--
-- Otra persona cuenta su negocio por Telegram y de ahí sale algo desplegado que
-- puede mirar. El planteamiento y sus 24 decisiones están en dos lienzos del
-- proyecto `hub`; lo que hay que saber para leer estas tablas es esto:
--
-- 🔴 **Canal aparte del de consulta** (decisión n1). Bot propio, servicio propio
-- (`hub-encargos`), registro de personas propio y permisos propios. No se toca
-- nada de `canal_*`: lo que un encargo necesita es provocar trabajo, y ése es
-- justo el poder que el canal de consulta se negó a tener. Mezclarlos habría
-- abierto esa puerta para todos.
--
-- 🔴 **La base es el índice; la ficha es un archivo** (regla dura 1). Lo que la
-- persona contó vive en `HUB_HOME/encargos/<id>/ficha.json`, que escribe el
-- agente entrevistador. Aquí está el estado, la cola y el rastro — lo que hace
-- falta para saber qué falta por entregar, no la entrevista.

CREATE TABLE IF NOT EXISTS encargo (
    -- El slug es también la carpeta y el subdominio: un solo nombre para las
    -- tres cosas, porque tres nombres para lo mismo es cómo se despliega un
    -- encargo encima de otro.
    id             TEXT PRIMARY KEY,
    titulo         TEXT NOT NULL DEFAULT '',
    user_id        INTEGER NOT NULL,   -- de quién es el negocio
    estado         TEXT NOT NULL DEFAULT 'recogiendo',
                   -- recogiendo | propuesta | aprobado | construyendo
                   -- | publicado | descartado
    ronda          INTEGER NOT NULL DEFAULT 1,
    -- Dónde vive el entrevistador. NO se guarda su `pane_id`: se resuelve en el
    -- instante de entregar, como en `mensaje_programado` y por lo mismo — entre
    -- que llega un audio y se entrega puede haber pasado un compact entero.
    slot_id        INTEGER,
    url            TEXT,
    -- El mensaje del plan que se le mandó al dueño. Se aprueba RESPONDIÉNDOLO
    -- (decisión n14): un «sí» suelto en otra conversación no puede lanzar una
    -- construcción, que es la acción más privilegiada del sistema.
    plan_msg       INTEGER,
    -- Cuándo se le dijo a la persona que esperase. Se pone cuando el agente
    -- lleva rato sin poder recibir y sirve para dos cosas: no repetir el aviso,
    -- y saber que hay que decirle «ya estoy» al reanudar.
    avisado_espera TEXT,
    creado_en      TEXT NOT NULL,
    actualizado_en TEXT NOT NULL,
    nota           TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_encargo_estado ON encargo(estado);

-- Quién puede hablar con el bot de encargos. Mismo modelo que `canal_usuario` y
-- por el mismo motivo: la Bot API no deja escribir a un teléfono que no habló
-- primero, así que el alta se invierte —aparece quien escribió y el dueño lo
-- aprueba— y escribirle al bot no concede absolutamente nada.
CREATE TABLE IF NOT EXISTS encargo_persona (
    user_id  INTEGER PRIMARY KEY,
    username TEXT NOT NULL DEFAULT '',
    nombre   TEXT NOT NULL DEFAULT '',
    alias    TEXT NOT NULL DEFAULT '',
    estado   TEXT NOT NULL DEFAULT 'pendiente',  -- pendiente | activo | bloqueado
    es_dueno INTEGER NOT NULL DEFAULT 0,
    visto_en TEXT NOT NULL,
    nota     TEXT NOT NULL DEFAULT '',
    -- De confianza: sus planes se construyen sin esperar la aprobación del
    -- dueño (decisión 236). Lo marca él, en el hub, por persona.
    de_confianza INTEGER NOT NULL DEFAULT 0
);

-- 🔴 **La cola, que es la pieza que hace que esto no pierda nada.**
--
-- El agente NO es quien recibe. El relé escucha siempre y aparca aquí lo que
-- llega; el agente lo recoge cuando su panel está apto. Escribir directo en el
-- panel haría que un audio llegado en mitad de un compact entrara en una TUI que
-- no está lista, y la regla dura 17 dice que escribir no es haber enviado.
--
-- Las dos direcciones viven en la misma tabla a propósito: lo que se enseña a
-- una persona que pregunta «¿qué le dije al bot?» es la conversación entera, y
-- partirla en dos tablas obliga a recomponerla en cada consulta.
CREATE TABLE IF NOT EXISTS encargo_mensaje (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    -- `ON UPDATE CASCADE` porque el id de un encargo SÍ cambia: nace
    -- provisional y se renombra en cuanto se sabe cómo se llama el negocio.
    -- Sin esto, renombrar fallaría con una violación de clave ajena justo
    -- cuando el encargo ya tiene toda la conversación colgando.
    encargo_id  TEXT NOT NULL
                REFERENCES encargo(id) ON DELETE CASCADE ON UPDATE CASCADE,
    direccion   TEXT NOT NULL,                  -- entra | sale
    user_id     INTEGER,
    clase       TEXT NOT NULL DEFAULT 'texto',  -- texto | audio | muestras
    texto       TEXT NOT NULL DEFAULT '',
    -- Ruta local: el audio recibido, o el PNG que hay que mandar. Nunca el
    -- contenido, que en un audio de tres minutos no tiene por qué caber aquí.
    adjunto     TEXT NOT NULL DEFAULT '',
    -- Botones bajo el mensaje, como JSON [[texto, dato], …] (decisión 237).
    botones     TEXT NOT NULL DEFAULT '',
    message_id  INTEGER,
    estado      TEXT NOT NULL DEFAULT 'en-cola',
                -- entra: en-cola | entregado | sin-confirmar | descartado
                -- sale:  en-cola | enviado | fallido
    lote        TEXT,           -- con qué otros mensajes entró al panel de una vez
    recibido_en TEXT NOT NULL,
    movido_en   TEXT,
    detalle     TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_encargo_mensaje
    ON encargo_mensaje(encargo_id, direccion, estado, id);

-- Todo lo que entra y sale, como en el canal de consulta y por lo mismo: lo que
-- sale de aquí sale de la máquina, y hay que poder auditar después qué salió.
CREATE TABLE IF NOT EXISTS encargo_registro (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    momento     TEXT NOT NULL,
    direccion   TEXT NOT NULL,   -- sale | entra | falla
    user_id     INTEGER,
    encargo_id  TEXT,
    detalle     TEXT NOT NULL DEFAULT '',
    cuerpo      TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_encargo_registro ON encargo_registro(momento DESC);
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
    ("encargo_persona", "de_confianza", "INTEGER NOT NULL DEFAULT 0"),
    ("encargo_mensaje", "botones", "TEXT NOT NULL DEFAULT ''"),
    # En qué etapa está el encargo: «maqueta» (estático, para pasear y
    # corregir barato) o «sistema» (con base de datos y acceso, decisión 244).
    ("encargo", "etapa", "TEXT NOT NULL DEFAULT 'maqueta'"),
    # Por dónde habla la persona: telegram, o el chat web para quien no lo
    # tiene (decisión 246). Lo que sale va por su canal.
    ("encargo_persona", "canal", "TEXT NOT NULL DEFAULT 'telegram'"),
    ("proyecto", "tipo", "TEXT NOT NULL DEFAULT 'proyecto'"),
    ("repo", "repo_comun", "TEXT"),
    ("repo", "head", "TEXT"),
    # Cuándo se escaneó el catálogo. Sin esto, `/inventario` enseñaba una
    # foto de hace una semana igual que una recién medida: la pantalla no
    # tenía forma de decir cuál de las dos estaba viendo.
    ("capacidad", "medido_en", "TEXT"),
    # El lote al que pertenece una pregunta. NULL es una pregunta suelta, que
    # se entrega en cuanto se contesta — el comportamiento de siempre.
    #
    # Existe porque cada respuesta que entra en un panel es un turno de Claude,
    # y un turno relee el contexto entero: medido sobre sesiones reales, 148k
    # tokens por llamada y el 69% del coste de la más cara. Cinco respuestas
    # sueltas son cinco despertares; en lote son uno.
    ("canal_pregunta", "lote", "TEXT"),
    ("consumo", "razonadas", "INTEGER NOT NULL DEFAULT 0"),
    ("canal_usuario", "es_dueno", "INTEGER NOT NULL DEFAULT 0"),
    ("canal_usuario", "tutorial", "TEXT NOT NULL DEFAULT ''"),
    ("canal_usuario", "tutorial_msg", "INTEGER"),
    # Qué slots quiere volver a tener delante tras un apagón. Marca humana y por
    # slot: nada automático sobre los slots (regla dura 3, principio 9).
    ("slot", "restaurar", "INTEGER NOT NULL DEFAULT 0"),
    # De dónde viene el episodio. Se guarda y no se deduce: en la vuelta
    # siguiente el estado ya no cambia, así que deducirlo perdía el origen.
    ("aviso", "previo", "TEXT"),
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
