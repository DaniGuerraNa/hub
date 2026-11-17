"""La copia diaria de `hub.db` (decisión 277).

La regla dura 1 dice que la base es un índice, y para lo derivado lo es. Pero
hay datos que sólo viven ahí —los slots y sus notas, el canal, los programados,
los encargos; la lista entera está en `db.BaseIlegible`—, y un dato que sólo
vive en un sitio no está respaldado. Volcarlos a archivos para que la regla
vuelva a ser verdad era mucho trabajo para poco; copiar la base cada día, no.

🔴 **Con la API de copia de SQLite, nunca con `cp`.** La base va en WAL: lo
último escrito puede estar todavía en `hub.db-wal`, y copiar sólo el archivo
principal mientras el snapshotter escribe da una copia a medias que abre bien
y le faltan cosas — el peor tipo de respaldo, porque nadie lo descubre hasta
que lo necesita.

**Y comprobada, y también en otro disco** (C-0417). Antes de darla por buena,
`PRAGMA quick_check` sobre la copia: una base con una página rota se copia
sin quejarse, y la copia hereda el defecto. Hecha y comprobada en local, el
archivo se **copia** a una segunda carpeta opcional (`HUB_RESPALDO_EXTRA`, o
la primera línea de `HUB_HOME/respaldo-extra.txt`): las copias de siempre
viven en el mismo disco que la base y no sobreviven a ese disco. La base nunca
se escribe allí directamente: un disco de Windows visto desde WSL (drvfs/9p)
no garantiza los cerrojos de SQLite.

**Y una más, antes de actualizar** (C-0448): `actualizar.sh` copia las dos
bases justo antes de los pasos de versión y del reinicio, que es cuando el
código nuevo cambia el esquema al abrirlas. La diaria puede tener 23 horas.
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import shutil
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

from . import config

PREFIJO = "hub-"
# La de la memoria del secretario (decisión 299). La hace `hub-secretario`
# con este prefijo; aquí, para que `/respaldo` y Máquina la vigilen (C-0282).
PREFIJO_SECRETARIO = "secretario-"
CONSERVAR = 14
# Las de antes de actualizar (C-0448), con su propio prefijo: ni su poda toca
# las diarias ni `/respaldo` las cuenta como la copia de cada día. Tres: lo
# que hace falta para volver de un intento fallido, no un archivo histórico.
PREFIJO_ANTES = "antes-hub-"
PREFIJO_ANTES_SECRETARIO = "antes-secretario-"
CONSERVAR_ANTES = 3
# Más que esto sin copia nueva es que algo no va: el snapshotter la intenta
# cada diez minutos, así que dos días sin ninguna no es mala suerte.
VIEJA_A_LOS = timedelta(days=2)
#: Cada cuánto se vuelve a intentar una copia que no pasó la comprobación.
REINTENTO = timedelta(hours=1)
#: La segunda carpeta, escrita en una línea dentro de `HUB_HOME` (C-0417). Un
#: archivo y no sólo la variable: se lee en cada copia, así que se enciende
#: sin tocar los servicios de systemd ni reiniciar nada.
ARCHIVO_EXTRA = "respaldo-extra.txt"


class CopiaDefectuosa(RuntimeError):
    """La copia no pasó `PRAGMA quick_check`: no se guarda y se dice."""


def carpeta() -> Path:
    """Dónde van las copias. Se resuelve en cada llamada: los tests la mueven."""
    declarada = os.environ.get("HUB_RESPALDO")
    return Path(declarada) if declarada else config.HUB_HOME / "respaldos"


def carpeta_extra() -> Path | None:
    """La segunda carpeta, en otro disco, o None si no hay ninguna (C-0417).

    Manda `HUB_RESPALDO_EXTRA`; sin ella, la primera línea con algo de
    `HUB_HOME/respaldo-extra.txt` (las que empiezan por `#` no cuentan). Se
    resuelve en cada llamada, como `carpeta`. Un archivo que existe y no se
    puede leer lanza `OSError`: quien llama lo dice, no lo da por apagado.
    """
    declarada = os.environ.get("HUB_RESPALDO_EXTRA", "").strip()
    if not declarada:
        try:
            texto = (config.HUB_HOME / ARCHIVO_EXTRA).read_text(encoding="utf-8")
        except FileNotFoundError:
            return None
        declarada = next((linea.strip() for linea in texto.splitlines()
                          if linea.strip() and not linea.strip().startswith("#")), "")
    return Path(declarada).expanduser() if declarada else None


def _nuestra(prefijo: str, cola: str = "") -> re.Pattern:
    """El nombre de una copia nuestra, y nada más: `<prefijo>` + la fecha en
    ocho cifras + `.db` (+ `cola`). La segunda carpeta es del dueño y puede
    tener un `hub-notas.db` suyo; con `hub-*.db` la poda se lo llevaba, y el
    más «nuevo» por orden era el suyo (revisión cruzada de C-0417)."""
    return re.compile(re.escape(prefijo) + r"\d{8}\.db" + re.escape(cola))


def copias(donde: Path, prefijo: str = PREFIJO) -> list[Path]:
    """Las copias de esa carpeta, de la más vieja a la más nueva. Pública
    porque `db` busca en ellas la última buena cuando la base no abre. Sólo
    las que son nuestras sin duda (`_nuestra`): lo demás ni se cuenta ni se poda."""
    if not donde.is_dir():
        return []
    patron = _nuestra(prefijo)
    return sorted(p for p in donde.glob(f"{prefijo}*.db") if patron.fullmatch(p.name))


def hacer(con: sqlite3.Connection, ahora: datetime | None = None,
          conservar: int = CONSERVAR, prefijo: str = PREFIJO) -> Path | None:
    """Una copia por día; si la de hoy ya existe, no la rehace y devuelve None.

    `prefijo` es para la otra base que sólo vive en un sitio: la memoria del
    secretario (`secretario-<fecha>.db`, decisión 299), con su propia cuenta de
    catorce.

    Se escribe primero a `.tmp` y se renombra: un corte a mitad de la copia
    deja un `.tmp` suelto, nunca un `hub-<fecha>.db` que parece bueno. Y sólo
    se renombra si pasa `PRAGMA quick_check` (C-0417); si no, se borra, se
    apunta para `/respaldo` y lanza `CopiaDefectuosa`: el ciclo siguiente lo
    vuelve a intentar.

    Después, la de hoy se lleva a la segunda carpeta si la hay y aún no está
    allí, también cuando la local ya existía: un disco que no estaba montado
    a la hora de la copia la recibe al volver.
    """
    ahora = ahora or datetime.now()
    donde = carpeta()
    destino = donde / f"{prefijo}{ahora:%Y%m%d}.db"
    if destino.exists():
        _llevar_a_otro_disco(destino, prefijo, conservar)
        return None
    _no_tan_seguido(destino.name, prefijo)
    donde.mkdir(parents=True, exist_ok=True)
    temporal = destino.with_suffix(".db.tmp")
    # Lo que dejó un intento anterior que no pasó la comprobación o se cortó.
    temporal.unlink(missing_ok=True)
    copia = sqlite3.connect(temporal)
    try:
        con.backup(copia)
        # La copia hereda el modo WAL de la base, y abrirla para mirarla le
        # creaba sus `-wal` y `-shm` (C-0280): deja de ser un solo archivo.
        # Una copia no la escribe nadie; con DELETE se queda en uno.
        copia.execute("PRAGMA journal_mode=DELETE")
    finally:
        copia.close()
    resultado = comprobar(temporal)
    _anotar(prefijo, comprobacion={"copia": destino.name, "cuando": _ahora(), "resultado": resultado})
    if resultado != "ok":
        temporal.unlink(missing_ok=True)
        raise CopiaDefectuosa(f"la copia {destino.name} no pasó la comprobación: {resultado}")
    temporal.replace(destino)
    for sobra in copias(donde, prefijo)[:-conservar]:
        sobra.unlink(missing_ok=True)
    _sin_huerfanos(donde, prefijo)
    _llevar_a_otro_disco(destino, prefijo, conservar)
    return destino


def antes_de_actualizar(ahora: datetime | None = None) -> list[Path]:
    """Copia `hub.db` y la memoria del secretario antes de que `actualizar.sh`
    toque nada (C-0448): `antes-hub-<fecha>.db` y `antes-secretario-<fecha>.db`,
    comprobadas como las diarias y las tres últimas de cada una.

    🔴 **En sólo lectura**, nunca con `db.conectar` ni `memoria.conectar`: ésas
    ponen el esquema al día al abrir, y la copia «de antes» ya no lo sería. Los
    servicios siguen en marcha con el código viejo y escribiendo; la API de
    copia de SQLite lee lo confirmado, también lo que sigue en el `-wal`.

    Si la de hoy ya existe no se rehace (`hacer`): en un reintento el código
    nuevo ya pudo tocar la base, y la buena es la del primer intento. Devuelve
    dónde está cada una, hecha ahora o antes; una base que no existe no se
    copia ni se crea. Lanza si una copia no se puede hacer: quien actualiza
    para ahí, sin haber tocado nada. `mis-datos.yml` no se copia (382).
    """
    from .secretario import memoria   # aquí: memoria importa `db`, y `db` a este módulo

    ahora = ahora or datetime.now()
    hechas = []
    for prefijo, base in ((PREFIJO_ANTES, config.DB_PATH),
                          (PREFIJO_ANTES_SECRETARIO, memoria.ruta())):
        if not base.is_file():
            continue
        con = sqlite3.connect(f"{base.resolve().as_uri()}?mode=ro", uri=True, timeout=10)
        try:
            hacer(con, ahora, conservar=CONSERVAR_ANTES, prefijo=prefijo)
        finally:
            con.close()
        hechas.append(carpeta() / f"{prefijo}{ahora:%Y%m%d}.db")
    return hechas


def main(argv: list[str]) -> int:
    """`python -m hub.copia_base antes`: lo corre `actualizar.sh` antes de los
    pasos de versión. Dice una ruta por línea; si no pudo, el porqué y sale con 1."""
    if argv != ["antes"]:
        print("uso: python -m hub.copia_base antes", file=sys.stderr)
        return 2
    try:
        # Lo que se dice por el camino (la segunda carpeta que no está, una
        # anotación que no se escribe) va a stderr: la salida son las rutas,
        # y el guion la lee entera.
        with contextlib.redirect_stdout(sys.stderr):
            hechas = antes_de_actualizar()
    except (sqlite3.Error, OSError, CopiaDefectuosa) as exc:
        print(f"no se pudo copiar: {exc}", file=sys.stderr)
        return 1
    for ruta in hechas:
        print(ruta)
    return 0


def _no_tan_seguido(nombre: str, prefijo: str) -> None:
    """Una base con un defecto lo tiene en cada intento: rehacer la copia
    entera en cada vuelta del secretario no arregla nada y gasta disco. Si
    la de hoy no pasó hace menos de `REINTENTO`, se vuelve a decir lo mismo
    sin copiar (el ciclo lento lo apunta una vez por racha)."""
    previa = _leer_anotacion(prefijo).get("comprobacion")
    if not isinstance(previa, dict) or previa.get("copia") != nombre or previa.get("resultado") == "ok":
        return
    try:
        hace = datetime.now() - datetime.fromisoformat(str(previa.get("cuando")))
    except ValueError:
        return
    if timedelta(0) <= hace < REINTENTO:
        raise CopiaDefectuosa(f"la copia {nombre} no pasó la comprobación: {previa.get('resultado')}")


def comprobar(ruta: Path) -> str:
    """`ok`, o lo que `PRAGMA quick_check` encontró (resumido). De sólo
    lectura: mirar la copia no la toca. Una que ni abre también es defecto."""
    try:
        mirada = sqlite3.connect(f"{ruta.resolve().as_uri()}?mode=ro", uri=True)
        try:
            filas = [str(f[0]) for f in mirada.execute("PRAGMA quick_check")]
        finally:
            mirada.close()
    except sqlite3.Error as exc:
        return f"no se pudo leer: {exc}"[:300]
    if filas == ["ok"]:
        return "ok"
    return " ".join(" · ".join(filas).split())[:300] or "sin respuesta"


def _llevar_a_otro_disco(copia: Path, prefijo: str, conservar: int) -> None:
    """La copia de hoy, a la segunda carpeta (C-0417). Nunca lanza: la copia
    local ya está hecha y no puede fallar por esto (regla dura 2). Lo que
    falle se apunta para `/respaldo` y sale en el journal (regla dura 21),
    una vez por cada cambio y no en cada ciclo.

    Se copia el ARCHIVO, ya cerrado y comprobado, a un `.tmp` y se renombra;
    no se abre allí con SQLite. La carpeta no se crea sola: con el disco sin
    montar, crearla llenaría en silencio el disco de siempre.
    """
    donde = copia.parent
    try:
        extra = carpeta_extra()
    except OSError as exc:
        _anotar_extra(prefijo, {"carpeta": str(config.HUB_HOME / ARCHIVO_EXTRA),
                                "error": f"no se pudo leer {ARCHIVO_EXTRA}: {exc}"})
        return
    if extra is None:
        _anotar_extra(prefijo, None)
        return
    final = extra / copia.name
    temporal = final.with_name(final.name + ".tmp")
    try:
        if not extra.is_dir():
            raise OSError("no existe (no se crea sola, por si el disco no está montado: créala tú)")
        if extra.resolve() == donde.resolve():
            raise OSError("es la misma carpeta de las copias de siempre")
        # Ya está: unos `stat` y nada más. La vuelta del secretario pasa por
        # aquí cada 30 s, y en un disco de Windows cada búsqueda en la carpeta
        # cruza a Windows (y despierta el disco): la poda, sólo al copiar.
        if not (final.is_file() and final.stat().st_size == copia.stat().st_size):
            shutil.copyfile(copia, temporal)
            if temporal.stat().st_size != copia.stat().st_size:
                raise OSError("la copia quedó a medias")
            os.replace(temporal, final)
            for sobra in copias(extra, prefijo)[:-conservar]:
                sobra.unlink(missing_ok=True)
            _sin_huerfanos(extra, prefijo)
    except OSError as exc:
        try:
            temporal.unlink(missing_ok=True)
        except OSError:
            pass
        _anotar_extra(prefijo, {"carpeta": str(extra), "error": str(exc)[:300]})
        return
    _anotar_extra(prefijo, {"carpeta": str(extra), "error": None})


def _ahora() -> str:
    return datetime.now().isoformat(timespec="minutes")


def _anotacion(prefijo: str) -> Path:
    """Lo último que pasó con las copias de `prefijo`: la comprobación y la
    segunda carpeta (`copia-hub.json`, `copia-secretario.json`). En `HUB_HOME`
    y no junto a las copias, que siguen siendo sólo copias; en un archivo y no
    en una tabla, sin tocar el esquema de ninguna base. Lo escriben dos
    procesos (`hub-web` y `hub-secretario`), cada uno el suyo."""
    return config.HUB_HOME / f"copia-{prefijo.rstrip('-')}.json"


def _leer_anotacion(prefijo: str) -> dict:
    try:
        datos = json.loads(_anotacion(prefijo).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return datos if isinstance(datos, dict) else {}


def _anotar(prefijo: str, **cambios) -> None:
    """Entera o nada (temporal y `replace`). Si no se puede escribir, se dice
    en el journal: no es motivo para perder la copia."""
    datos = _leer_anotacion(prefijo)
    datos.update(cambios)
    ruta = _anotacion(prefijo)
    try:
        ruta.parent.mkdir(parents=True, exist_ok=True)
        temporal = ruta.with_name(ruta.name + ".tmp")
        temporal.write_text(json.dumps(datos, ensure_ascii=False), encoding="utf-8")
        temporal.replace(ruta)
    except OSError as exc:
        print(f"[copia {prefijo.rstrip('-')}] no se pudo apuntar cómo fue la copia: {exc}", flush=True)


def _anotar_extra(prefijo: str, extra: dict | None) -> None:
    """Sólo si cambió: esto se mira en cada ciclo, y un disco ausente no
    puede llenar el journal con la misma línea cada diez minutos."""
    antes = _leer_anotacion(prefijo).get("extra")
    if antes is not None and extra is not None and \
            (antes.get("carpeta"), antes.get("error")) == (extra["carpeta"], extra["error"]):
        return
    if antes is None and extra is None:
        return
    if extra is not None:
        extra = {**extra, "cuando": _ahora()}
        if extra["error"]:
            print(f"[copia {prefijo.rstrip('-')}] la segunda carpeta {extra['carpeta']}: {extra['error']}. "
                  "La copia de siempre sí se hizo.", flush=True)
    _anotar(prefijo, extra=extra)


def _sin_huerfanos(donde: Path, prefijo: str) -> None:
    """Los `-wal`, `-shm` y `-journal` de copias que ya no están (C-0280).

    La poda sólo borraba los `.db`, y quedaban los hermanos que crea abrir una
    copia: 30 el 11-nov. Los de una copia que sigue no se tocan: puede tenerla
    abierta alguien que la está mirando.
    """
    for cola in ("-wal", "-shm", "-journal"):
        patron = _nuestra(prefijo, cola)
        for suelto in donde.glob(f"{prefijo}*.db{cola}"):
            if patron.fullmatch(suelto.name) and not suelto.with_name(suelto.name[: -len(cola)]).exists():
                suelto.unlink(missing_ok=True)


def estado(ahora: datetime | None = None, prefijo: str = PREFIJO) -> dict:
    """Lo que enseña `/respaldo`: dónde, cuántas, y si la última es vieja.

    `prefijo` como en `hacer`: con `secretario-`, la copia de la memoria del
    secretario, que la hace `hub-secretario` y no vigilaba nadie (C-0282).

    Y desde C-0417: `comprobada` (True si la última pasó `quick_check` al
    hacerla, False si el último intento no, None si no consta: una copia de
    antes de esto no se da por comprobada), `defecto` (lo que encontró) y
    `extra`, la segunda carpeta: None si no hay, o dónde, cuántas copias y el
    error si el último intento de llevarla allí falló.
    """
    ahora = ahora or datetime.now()
    donde = carpeta()
    hechas = copias(donde, prefijo)
    anotado = _leer_anotacion(prefijo)
    ultima = hechas[-1] if hechas else None
    comprobada, defecto = _comprobacion(anotado.get("comprobacion"), ultima)
    base = {"carpeta": str(donde), "conservar": CONSERVAR, "comprobada": comprobada,
            "defecto": defecto, "extra": _estado_extra(anotado.get("extra"), prefijo)}
    if ultima is None:
        return {**base, "copias": 0, "ultima": None, "tamano": None, "vieja": True}
    cuando = datetime.fromtimestamp(ultima.stat().st_mtime)
    return {
        **base,
        "copias": len(hechas),
        "ultima": cuando.isoformat(timespec="minutes"),
        "tamano": ultima.stat().st_size,
        "vieja": ahora - cuando > VIEJA_A_LOS,
    }


def _comprobacion(anotada, ultima: Path | None) -> tuple[bool | None, str | None]:
    """Lo apuntado vale para la última copia, o es un intento fallido más nuevo
    que ella (ése no dejó copia). Lo demás es de otra copia: no consta."""
    if not isinstance(anotada, dict):
        return None, None
    if anotada.get("resultado") != "ok":
        if ultima is None or str(anotada.get("copia", "")) > ultima.name:
            return False, str(anotada.get("resultado") or "")
        return None, None
    if ultima is not None and anotada.get("copia") == ultima.name:
        return True, None
    return None, None


def _estado_extra(anotada, prefijo: str) -> dict | None:
    try:
        extra = carpeta_extra()
    except OSError as exc:
        return {"carpeta": str(config.HUB_HOME / ARCHIVO_EXTRA), "copias": 0, "ultima": None,
                "error": f"no se pudo leer {ARCHIVO_EXTRA}: {exc}"}
    if extra is None:
        return None
    error = None
    if isinstance(anotada, dict) and anotada.get("carpeta") == str(extra):
        error = anotada.get("error")
    try:
        alli = copias(extra, prefijo)
    except OSError as exc:
        alli, error = [], error or str(exc)
    return {"carpeta": str(extra), "copias": len(alli),
            "ultima": alli[-1].name if alli else None, "error": error}


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
