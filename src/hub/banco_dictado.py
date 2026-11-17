"""El banco de dictado: frases leídas por quien usa el hub, para medir Whisper con su voz (C-0312).

Sin esto, cambiar de modelo, de glosario o de parámetros era a ciegas: las
cifras de velocidad salían de frases sintetizadas, y cuánto acierta con su
voz no se había medido nunca (regla dura 13). Un glosario puede además
empeorar las frases que no lo llevan sin que nadie lo note.

- **Grabar.** `/voz/banco` le enseña una frase, él la lee y se guarda el
  audio con lo que tenía que decir (`guardar`), por aparato (PC o teléfono),
  con el grabador de siempre (`HubGrabar`). Grabar no transcribe: no necesita
  Whisper ni GPU.
- **Medir.** `medir` arranca un servidor de Whisper privado por
  configuración (`transcribir.arrancar_servidor`, en su propio scope, 344),
  le pide cada audio (`transcribir.pedir`) y lo apaga; el WER lo calcula
  aquí. Así se mide con los mismos parámetros de decodificación que el
  dictado, sin un tercer sitio que los repita. Un modelo a la vez: antes
  apaga el del dictado y no empieza si Reuniones está procesando.

🔴 **Nada sale de la máquina** (decisión 221).

🔴 **Es dato que no se rehace** (regla dura 1): su voz leyendo, con la
referencia. Vive en `HUB_HOME/voz/banco/` (carpeta 700, archivos 600,
escritura atómica), no caduca —`transcribir.podar_dictados` no entra en
subcarpetas: lo guardado a propósito se borra con su botón, matiza la 362— y
la copia diaria (`copia_base`) no lo lleva.

🔴 **La lista y lo que se publica.** En el repo sólo va `PLANTILLA`,
genérica, con los huecos `{proyecto}` y `{secretario}`, que se rellenan con
el registro y el nombre del secretario. La lista con el vocabulario de quien
lo usa entra por `sembrar --de` y sólo vive en `HUB_HOME`. Se congela con la
primera grabación: cambiar una frase después pide volver a grabarla.

    uv run python -m hub.banco_dictado frases                 # la lista, en YAML
    uv run python -m hub.banco_dictado sembrar --de mis-frases.yml
    uv run python -m hub.banco_dictado estado
    uv run python -m hub.banco_dictado medir --modelos small,large-v3-turbo [--tipos float16,int8_float16]
    uv run python -m hub.banco_dictado resultados
"""

from __future__ import annotations

import contextlib
import fcntl
import json
import math
import os
import re
import tempfile
import threading
import time
import unicodedata
from pathlib import Path

from . import config

APARATOS = ("pc", "telefono")
NOMBRES_APARATO = {"pc": "PC", "telefono": "Teléfono"}
#: Cómo se nombra cada categoría de la plantilla en la pantalla; una que
#: traiga la lista sembrada y no esté aquí se enseña tal cual.
CATEGORIAS = {"corta": "Corta", "tecnica": "Técnica", "hub": "Del hub", "cifras": "Cifras", "larga": "Larga"}

#: Las frases que trae el hub, genéricas. `{proyecto}` se rellena con los
#: proyectos del registro (uno distinto en cada frase, por orden) y
#: `{secretario}` con el nombre del secretario. Mezclan lo que se dicta de
#: verdad: respuestas cortas (donde más falla «no se oyó nada»), vocabulario
#: técnico con anglicismos, las piezas del hub, cifras dichas y frases largas
#: habladas, dos de más de 30 s, que cruzan la ventana de Whisper.
PLANTILLA: tuple[dict, ...] = (
    {"id": "c01", "categoria": "corta", "texto": "Sí, adelante.", "terminos": []},
    {"id": "c02", "categoria": "corta", "texto": "No, todavía no.", "terminos": []},
    {"id": "c03", "categoria": "corta", "texto": "Para.", "terminos": []},
    {"id": "c04", "categoria": "corta", "texto": "La primera.", "terminos": []},
    {"id": "c05", "categoria": "corta", "texto": "Repítelo, por favor.", "terminos": []},
    {"id": "c06", "categoria": "corta", "texto": "Déjalo así.", "terminos": []},
    {"id": "c07", "categoria": "corta", "texto": "¿Y ahora qué?", "terminos": []},
    {"id": "c08", "categoria": "corta", "texto": "Guárdalo para después.", "terminos": []},
    {"id": "t01", "categoria": "tecnica", "texto": "Lanza los tests con pytest y enséñame sólo los que fallan.",
     "terminos": ["tests", "pytest"]},
    {"id": "t02", "categoria": "tecnica", "texto": "Haz un commit con lo que hay y luego un push a la rama de desarrollo.",
     "terminos": ["commit", "push"]},
    {"id": "t03", "categoria": "tecnica", "texto": "Abre un pull request y pide una revisión antes del merge.",
     "terminos": ["pull request", "merge"]},
    {"id": "t04", "categoria": "tecnica", "texto": "Mira el log del contenedor de Docker, creo que se reinicia solo.",
     "terminos": ["log", "Docker"]},
    {"id": "t05", "categoria": "tecnica", "texto": "El deploy falló en el paso del build; revisa las variables de entorno.",
     "terminos": ["deploy", "build"]},
    {"id": "t06", "categoria": "tecnica", "texto": "Cambia el endpoint para que devuelva JSON y un cuatrocientos cuatro.",
     "terminos": ["endpoint", "JSON"]},
    {"id": "t07", "categoria": "tecnica", "texto": "Crea una rama nueva desde main y haz el rebase cuando termines.",
     "terminos": ["main", "rebase"]},
    {"id": "t08", "categoria": "tecnica", "texto": "Añade un índice a esa tabla, la consulta en SQL tarda demasiado.",
     "terminos": ["SQL"]},
    {"id": "t09", "categoria": "tecnica", "texto": "Instala la dependencia con uv y actualiza el lockfile.",
     "terminos": ["uv", "lockfile"]},
    {"id": "t10", "categoria": "tecnica", "texto": "Lee el stack trace y dime en qué línea se rompe.",
     "terminos": ["stack trace"]},
    {"id": "t11", "categoria": "tecnica", "texto": "Abre una sesión de tmux y deja corriendo el servidor.",
     "terminos": ["tmux"]},
    {"id": "t12", "categoria": "tecnica", "texto": "Pon un breakpoint en esa función y depúrala paso a paso.",
     "terminos": ["breakpoint"]},
    {"id": "h01", "categoria": "hub", "texto": "{secretario}, recuérdame mañana revisar {proyecto}.",
     "terminos": ["{secretario}", "{proyecto}"]},
    {"id": "h02", "categoria": "hub", "texto": "Pregúntale a {secretario} qué quedó pendiente en {proyecto}.",
     "terminos": ["{secretario}", "{proyecto}"]},
    {"id": "h03", "categoria": "hub", "texto": "Abre un slot nuevo en {proyecto} para el arreglo del formulario.",
     "terminos": ["slot", "{proyecto}"]},
    {"id": "h04", "categoria": "hub", "texto": "Encárgale al orquestador que corra las pruebas de {proyecto}.",
     "terminos": ["orquestador", "{proyecto}"]},
    {"id": "h05", "categoria": "hub", "texto": "Apunta en el tablero una idea para {proyecto}.",
     "terminos": ["tablero", "{proyecto}"]},
    {"id": "h06", "categoria": "hub", "texto": "Publica un lienzo con el diagrama de {proyecto}.",
     "terminos": ["lienzo", "{proyecto}"]},
    {"id": "h07", "categoria": "hub", "texto": "Revisa el respaldo, creo que hay commits sin subir en {proyecto}.",
     "terminos": ["respaldo", "commits", "{proyecto}"]},
    {"id": "h08", "categoria": "hub", "texto": "Dile a {secretario} que me lea el resumen de la reunión.",
     "terminos": ["{secretario}"]},
    {"id": "h09", "categoria": "hub", "texto": "Cambia el guardrail de {proyecto} para que pregunte antes de tocar nada.",
     "terminos": ["guardrail", "{proyecto}"]},
    {"id": "h10", "categoria": "hub", "texto": "Que Whisper use la GPU para el dictado de la terminal.",
     "terminos": ["Whisper", "GPU"]},
    {"id": "n01", "categoria": "cifras", "texto": "Avísame el martes a las diez y cuarto de la mañana.", "terminos": []},
    {"id": "n02", "categoria": "cifras", "texto": "Son tres mil cuatrocientos veinte registros en total.", "terminos": []},
    {"id": "n03", "categoria": "cifras", "texto": "Sube el límite al ochenta y cinco por ciento.", "terminos": []},
    {"id": "n04", "categoria": "cifras", "texto": "La reunión es el quince de enero a las cinco de la tarde.", "terminos": []},
    {"id": "n05", "categoria": "cifras", "texto": "Usa el puerto ocho mil ochenta con la versión dos punto uno.",
     "terminos": []},
    {"id": "l01", "categoria": "larga", "texto": "Bueno, a ver, lo que quiero es que revises cómo quedó lo de ayer, "
     "porque me parece que hay una parte que no terminamos y no recuerdo bien cuál era.", "terminos": []},
    {"id": "l02", "categoria": "larga", "texto": "Antes de cambiar nada, mira primero cómo está organizado el código, "
     "hazme un resumen corto de lo que encontraste y después me propones dos o tres caminos para seguir.",
     "terminos": []},
    {"id": "l03", "categoria": "larga", "texto": "Oye, la pantalla nueva está bien, pero en el teléfono los botones "
     "quedan muy pegados y a veces toco el que no es; sepáralos un poco y que el principal se vea más.",
     "terminos": []},
    {"id": "l04", "categoria": "larga", "texto": "Te cuento lo que pasó: esta mañana intenté entrar desde el teléfono "
     "y la página tardó muchísimo en cargar, luego me pidió otra vez que diera de alta el aparato y, cuando por fin "
     "entré, la terminal no respondía. Quiero que revises los registros de esa hora, que me digas qué falló primero "
     "y que me propongas cómo evitar que vuelva a pasar, sin cambiar todavía nada.", "terminos": []},
    {"id": "l05", "categoria": "larga", "texto": "Para la semana que viene necesito tres cosas: que el resumen del día "
     "me llegue más temprano, que los recordatorios de las reuniones salgan con media hora de margen y que, si algo se "
     "rompe mientras duermo, me lo dejes anotado para leerlo con calma en la mañana, en lugar de mandarme un aviso a "
     "cada rato.", "terminos": []},
)

#: Lo que se acepta de una lista sembrada. El id va en el nombre del audio.
_ID = re.compile(r"^[a-z0-9][a-z0-9_]{0,15}$")
_CATEGORIA = re.compile(r"^[a-z][a-z_]{0,19}$")
MAX_TEXTO = 800
MAX_FRASES = 200

#: Lo que se guarda de `track.getSettings()`: cómo sonó, nunca el
#: identificador del aparato (`deviceId`, `groupId`).
CLAVES_MICRO = ("echoCancellation", "noiseSuppression", "autoGainControl", "voiceIsolation", "sampleRate",
                "sampleSize", "channelCount", "latency", "restricciones")

#: Las categorías que no entran en el total y se informan aparte: las cifras
#: dichas («ocho mil ochenta») Whisper las puede escribir en dígitos, y sin un
#: normalizador de números contarían como fallos lo que no lo es.
APARTE = ("cifras",)

#: Lo que espera `medir` a que un servidor cargue su modelo, y a cada frase.
ESPERA_CARGA_S = 600
ESPERA_FRASE_S = 120
#: Un servidor de `medir` que se quedara huérfano (la orden cortada con
#: Ctrl+C) se apaga solo al rato, no a los 15 min del dictado.
OCIOSO_S = 120


class Ocupado(RuntimeError):
    """Otro modelo de Whisper está cargado (Reuniones procesando): no se mide."""


# ───────────────────────────── dónde vive ─────────────────────────────


def carpeta(crear: bool = False) -> Path:
    d = config.HUB_HOME / "voz" / "banco"
    if crear:
        d.mkdir(parents=True, exist_ok=True)
        os.chmod(d, 0o700)
    return d


def _escribir(ruta: Path, contenido: bytes) -> None:
    """Entero o nada, y sólo para el dueño desde el primer byte: `mkstemp`
    crea el temporal con 0600 y `os.replace` lo pone en su sitio."""
    fd, tmp = tempfile.mkstemp(dir=ruta.parent, prefix=f".{ruta.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(contenido)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, ruta)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


#: Dos escritores posibles —las peticiones a la vez de la web y la línea de
#: comandos—: el de hilos para lo primero, `flock` para lo segundo. Sin los
#: dos, uno reescribiría `grabaciones.jsonl` con lo que leyó antes.
_ESCRITURA = threading.Lock()


@contextlib.contextmanager
def _en_exclusiva():
    d = carpeta(crear=True)
    with _ESCRITURA, os.fdopen(os.open(d / "banco.lock", os.O_WRONLY | os.O_CREAT, 0o600), "w") as cerrojo:
        fcntl.flock(cerrojo, fcntl.LOCK_EX)
        try:
            yield d
        finally:
            fcntl.flock(cerrojo, fcntl.LOCK_UN)


# ───────────────────────────── la lista ─────────────────────────────


def _nombres_de_proyectos() -> list[str]:
    """Los proyectos activos con carpeta: los de ejemplo del registro recién
    instalado tienen rutas inventadas y no son de nadie."""
    from . import registry
    try:
        proyectos = registry.cargar()
    except (registry.YamlInvalido, OSError):
        proyectos = []
    return [p.nombre for p in proyectos
            if p.tipo == "proyecto" and p.status == "activo" and p.asiento
            and Path(p.asiento).expanduser().is_dir()] or ["el proyecto"]


def _rellenar(texto: str, proyecto: str, secretario: str) -> str:
    return texto.replace("{proyecto}", proyecto).replace("{secretario}", secretario)


def _de_la_plantilla() -> dict:
    """La plantilla con sus huecos rellenos: cada frase con `{proyecto}`
    lleva el siguiente proyecto del registro, por orden y dando la vuelta."""
    from . import api
    proyectos = _nombres_de_proyectos()
    secretario = api.nombre_secretario()
    frases, i = [], 0
    for f in PLANTILLA:
        proyecto = proyectos[i % len(proyectos)]
        i += "{proyecto}" in f["texto"]
        frases.append({"id": f["id"], "categoria": f["categoria"],
                       "texto": _rellenar(f["texto"], proyecto, secretario),
                       "terminos": [_rellenar(t, proyecto, secretario) for t in f["terminos"]]})
    return {"version": 1, "frases": frases}


def _lista() -> dict:
    """La lista congelada en `frases.yml`, o la de la plantilla si aún no hay."""
    ruta = carpeta() / "frases.yml"
    if ruta.is_file():
        return config.leer_yaml(ruta.read_text(encoding="utf-8")) or {"version": 1, "frases": []}
    return _de_la_plantilla()


def frases() -> list[dict]:
    """Las frases que se leen: `{id, categoria, texto, terminos}`."""
    return list(_lista().get("frases") or [])


def congelada() -> bool:
    return (carpeta() / "frases.yml").is_file()


def _validar_lista(lista) -> dict:
    crudas = lista.get("frases") if isinstance(lista, dict) else lista
    if not isinstance(crudas, list) or not crudas:
        raise ValueError("la lista no trae frases: hace falta `frases:` con al menos una")
    if len(crudas) > MAX_FRASES:
        raise ValueError(f"demasiadas frases: {len(crudas)} (como mucho {MAX_FRASES})")
    vistas, limpias = set(), []
    for n, f in enumerate(crudas, 1):
        if not isinstance(f, dict):
            raise ValueError(f"la frase nº{n} no es un bloque con id, categoria y texto")
        fid, cat = str(f.get("id") or ""), str(f.get("categoria") or "")
        texto = str(f.get("texto") or "").strip()
        if not _ID.match(fid):
            raise ValueError(f"frase nº{n}: id «{fid}» no vale (minúsculas, cifras y _; hasta 16)")
        if fid in vistas:
            raise ValueError(f"frase nº{n}: el id «{fid}» está repetido")
        if not _CATEGORIA.match(cat):
            raise ValueError(f"frase {fid}: categoría «{cat}» no vale (minúsculas y _)")
        if not texto or "\n" in texto or len(texto) > MAX_TEXTO:
            raise ValueError(f"frase {fid}: el texto tiene que ser una línea, de 1 a {MAX_TEXTO} caracteres")
        terminos = f.get("terminos") or []
        if not isinstance(terminos, list) or any(not str(t).strip() or len(str(t)) > 60 for t in terminos):
            raise ValueError(f"frase {fid}: `terminos` es una lista de palabras cortas")
        vistas.add(fid)
        limpias.append({"id": fid, "categoria": cat, "texto": texto, "terminos": [str(t).strip() for t in terminos]})
    version = lista.get("version") if isinstance(lista, dict) else None
    return {"version": int(version) if isinstance(version, int) else 1, "frases": limpias}


def _guardar_lista(d: Path, lista: dict) -> None:
    import yaml
    texto = ("# Las frases del banco de dictado (C-0312). Cambiar una ya grabada pide volver a\n"
             "# grabarla: se cambia con `python -m hub.banco_dictado sembrar --de` y el banco vacío.\n"
             + yaml.safe_dump(lista, allow_unicode=True, sort_keys=False, width=1000))
    _escribir(d / "frases.yml", texto.encode("utf-8"))


def sembrar(lista) -> int:
    """Pone la lista de frases (la de quien lo usa, con su vocabulario).
    Se niega si ya hay grabaciones: cambiarla debajo de ellas haría que la
    referencia no fuera lo que se leyó. Devuelve cuántas frases quedaron."""
    limpia = _validar_lista(lista)
    with _en_exclusiva() as d:
        hay = len(_grabaciones())
        if hay:
            raise ValueError(f"ya hay {hay} grabaciones: para cambiar la lista, vacía antes el banco "
                             "(«Vaciar» en /voz/banco, en cada aparato)")
        _guardar_lista(d, limpia)
    return len(limpia["frases"])


# ───────────────────────────── grabar ─────────────────────────────


def _grabaciones() -> list[dict]:
    ruta = carpeta() / "grabaciones.jsonl"
    if not ruta.is_file():
        return []
    salida = []
    for linea in ruta.read_text(encoding="utf-8").splitlines():
        with contextlib.suppress(ValueError):
            g = json.loads(linea)
            if isinstance(g, dict) and g.get("aparato") in APARATOS:
                salida.append(g)
    return salida


def _escribir_grabaciones(d: Path, lista: list[dict]) -> None:
    _escribir(d / "grabaciones.jsonl",
              "".join(json.dumps(g, ensure_ascii=False) + "\n" for g in lista).encode("utf-8"))


def _audio(d: Path, g: dict) -> Path | None:
    """El audio de una grabación, sólo si su nombre es un nombre de archivo y
    no una ruta: `grabaciones.jsonl` se puede editar a mano, y borrar o leer
    lo que diga no puede salir de la carpeta del banco."""
    archivo = g.get("archivo")
    if not isinstance(archivo, str) or Path(archivo).name != archivo or archivo.startswith("."):
        return None
    return d / archivo


def grabadas() -> set[tuple[str, str]]:
    """Qué (aparato, frase) tienen su audio guardado."""
    d = carpeta()
    return {(g["aparato"], g["frase"]) for g in _grabaciones()
            if (ruta := _audio(d, g)) is not None and ruta.is_file()}


def _aparato(aparato: str) -> str:
    if aparato not in APARATOS:
        raise ValueError(f"aparato no válido: «{aparato}» (uno de {', '.join(APARATOS)})")
    return aparato


def _valor_de_micro(v) -> bool:
    """Lo que manda el navegador es texto suyo: un número infinito o de cuatro
    mil cifras no es un ajuste de micrófono (ninguno pasa del millón)."""
    if isinstance(v, bool):
        return True
    if isinstance(v, int):
        return abs(v) <= 1_000_000
    if isinstance(v, float):
        return math.isfinite(v) and abs(v) <= 1_000_000
    return isinstance(v, str) and len(v) <= 40


def _micro(crudo) -> dict:
    if not isinstance(crudo, dict):
        return {}
    return {k: v for k, v in crudo.items() if k in CLAVES_MICRO and _valor_de_micro(v)}


def guardar(aparato: str, frase_id: str, datos: bytes, nombre: str, micro: dict | None = None,
            esperado: str | None = None) -> dict:
    """Guarda una toma: el audio y, en `grabaciones.jsonl`, su referencia.

    Volver a grabar una frase la sustituye. `micro` es lo que dio el
    micrófono (`track.getSettings()`): sin él no se sabría con qué se grabó
    cada toma. `esperado` es la frase que enseñaba la pantalla: si ya no es
    la de la lista, no se guarda una referencia que no se leyó. Devuelve el
    progreso del aparato. No transcribe nada.
    """
    from . import reloj, transcribir

    _aparato(aparato)
    # Aunque esté en la lista: `frases.yml` se puede editar a mano, y el id
    # va en el nombre del archivo.
    if not _ID.match(str(frase_id or "")):
        raise ValueError(f"id de frase «{frase_id}» no vale (minúsculas, cifras y _; hasta 16)")
    if not datos:
        raise ValueError("el audio llegó vacío")
    if len(datos) > transcribir.LIMITE_AUDIO:
        raise ValueError("el audio es demasiado largo para una frase")
    extension = (nombre.rsplit(".", 1)[-1] if "." in (nombre or "") else "webm").lower()
    if extension not in transcribir.EXTENSIONES:
        extension = "webm"
    with _en_exclusiva() as d:
        lista = _lista()
        frase = next((f for f in lista.get("frases") or [] if f.get("id") == frase_id), None)
        if frase is None:
            raise ValueError(f"la frase «{frase_id}» no está en la lista")
        if esperado is not None and esperado.strip() != frase["texto"]:
            raise ValueError("la frase cambió desde que se abrió la página: recárgala")
        if not congelada():
            _guardar_lista(d, lista)
        archivo = f"{aparato}-{frase_id}.{extension}"
        _escribir(d / archivo, datos)
        for viejo in d.glob(f"{aparato}-{frase_id}.*"):
            if viejo.name != archivo and viejo.suffix.lstrip(".") in transcribir.EXTENSIONES:
                viejo.unlink(missing_ok=True)
        resto = [g for g in _grabaciones() if (g.get("aparato"), g.get("frase")) != (aparato, frase_id)]
        resto.append({"frase": frase_id, "aparato": aparato, "archivo": archivo, "referencia": frase["texto"],
                      "categoria": frase["categoria"], "terminos": frase.get("terminos") or [],
                      "fecha": reloj.ahora(), "bytes": len(datos), "micro": _micro(micro)})
        _escribir_grabaciones(d, resto)
    return progreso(aparato)


def progreso(aparato: str) -> dict:
    """`{aparato, hechas, total, siguiente}`: cuántas tiene grabadas y la
    primera que le falta (None si ya están todas)."""
    _aparato(aparato)
    ids = [f["id"] for f in frases()]
    hechas = {f for a, f in grabadas() if a == aparato}
    faltan = [i for i in ids if i not in hechas]
    return {"aparato": aparato, "hechas": len(ids) - len(faltan), "total": len(ids),
            "siguiente": faltan[0] if faltan else None}


def borrar(aparato: str, frase_id: str) -> bool:
    """Quita una toma. Devuelve si había algo que quitar."""
    _aparato(aparato)
    with _en_exclusiva() as d:
        todas = _grabaciones()
        quedan = [g for g in todas if (g.get("aparato"), g.get("frase")) != (aparato, frase_id)]
        for g in todas:
            if g not in quedan and (ruta := _audio(d, g)) is not None:
                ruta.unlink(missing_ok=True)
        if len(quedan) != len(todas):
            _escribir_grabaciones(d, quedan)
        return len(quedan) != len(todas)


def vaciar(aparato: str | None = None) -> int:
    """Quita las tomas de un aparato, o de los dos. La lista y los
    resultados se quedan. Devuelve cuántas quitó."""
    if aparato is not None:
        _aparato(aparato)
    with _en_exclusiva() as d:
        todas = _grabaciones()
        quitar = [g for g in todas if aparato is None or g.get("aparato") == aparato]
        for g in quitar:
            if (ruta := _audio(d, g)) is not None:
                ruta.unlink(missing_ok=True)
        _escribir_grabaciones(d, [g for g in todas if g not in quitar])
        return len(quitar)


# ───────────────────────────── contar errores ─────────────────────────────


def normalizar(texto: str, tildes: bool = True) -> str:
    """Minúsculas, sin puntuación y con los espacios de uno en uno. Sin
    `tildes`, también sin acentos (la «ñ» queda «n»). Las cifras no se pasan
    a palabras: las frases con números se miden en su categoría, aparte."""
    t = unicodedata.normalize("NFC", str(texto or "")).lower()
    if not tildes:
        t = "".join(c for c in unicodedata.normalize("NFD", t) if not unicodedata.combining(c))
    return " ".join(re.sub(r"[^\w\s]|_", " ", t).split())


def _distancia(ref: list, hip: list) -> tuple[int, int, int]:
    """Levenshtein con lo que cuesta cada cosa: (sustituciones, borrados,
    inserciones). Propio y sin dependencias: son cuarenta frases."""
    previa = [(j, 0, 0, j) for j in range(len(hip) + 1)]   # (coste, s, b, i)
    for a in range(1, len(ref) + 1):
        fila = [(a, 0, a, 0)]
        for j in range(1, len(hip) + 1):
            if ref[a - 1] == hip[j - 1]:
                fila.append(previa[j - 1])
                continue
            s, b, i = previa[j - 1], previa[j], fila[j - 1]
            fila.append(min((s[0] + 1, s[1] + 1, s[2], s[3]), (b[0] + 1, b[1], b[2] + 1, b[3]),
                            (i[0] + 1, i[1], i[2], i[3] + 1)))
        previa = fila
    _, s, b, i = previa[-1]
    return s, b, i


def _tasa(ref: list, hip: list, clave: str) -> dict:
    s, b, i = _distancia(ref, hip)
    n = len(ref)
    tasa = round((s + b + i) / n, 4) if n else (0.0 if not hip else 1.0)
    return {clave: tasa, "s": s, "b": b, "i": i, "n": n}


def wer(referencia: str, hipotesis: str, tildes: bool = True) -> dict:
    """La tasa de error por palabras: `{wer, s, b, i, n}` (sustituciones,
    borrados, inserciones y palabras de la referencia), tras `normalizar`."""
    return _tasa(normalizar(referencia, tildes).split(), normalizar(hipotesis, tildes).split(), "wer")


def cer(referencia: str, hipotesis: str, tildes: bool = True) -> dict:
    """Lo mismo por letras: `{cer, s, b, i, n}`."""
    return _tasa(list(normalizar(referencia, tildes)), list(normalizar(hipotesis, tildes)), "cer")


def _contiene(texto: str, termino: str) -> bool:
    # Un término que se queda en nada al normalizar («++») no se acierta solo.
    buscado = normalizar(termino, False)
    return bool(buscado) and f" {buscado} " in f" {normalizar(texto, False)} "


# ───────────────────────────── medir ─────────────────────────────


def _config(c: dict) -> dict:
    if not isinstance(c, dict) or not c.get("modelo"):
        raise ValueError(f"una configuración necesita al menos `modelo`: {c!r}")
    limpia = {"modelo": str(c["modelo"]), "dispositivo": str(c.get("dispositivo") or "auto")}
    if c.get("tipo"):
        limpia["tipo"] = str(c["tipo"])
    return {**c, **limpia}


def _esperar_socket(enchufe: Path, huella: dict | None, segundos: float) -> bool:
    from . import procesos, transcribir
    limite = time.monotonic() + segundos
    while time.monotonic() < limite:
        if enchufe.exists() and transcribir.estado_servidor(enchufe):
            return True
        if huella and not procesos.vivo(huella):
            return False
        time.sleep(0.2)
    return False


def _cola_del_registro(d: Path, lineas: int = 3) -> str:
    try:
        return " | ".join((d / "servidor.log").read_text(encoding="utf-8", errors="replace").splitlines()[-lineas:])
    except OSError:
        return "sin registro"


def _rss_pico_mb(pid) -> float | None:
    """La memoria (RSS) que llegó a ocupar el servidor, de /proc. La de la
    GPU no se mide aquí."""
    try:
        for linea in Path(f"/proc/{int(pid)}/status").read_text().splitlines():
            if linea.startswith("VmHWM:"):
                return round(int(linea.split()[1]) / 1024, 1)
    except (OSError, ValueError, TypeError):
        pass
    return None


def _puntuar(g: dict, respuesta: dict | None) -> dict:
    from . import transcribir
    fila = {"frase": g["frase"], "aparato": g["aparato"], "categoria": g.get("categoria", ""),
            "referencia": g["referencia"]}
    if not respuesta or "texto" not in respuesta:
        # Sin respuesta no hay nada que puntuar: contarla como WER 1,0 haría
        # pasar un servidor caído por un modelo que no entiende (regla 13).
        fila["error"] = (respuesta or {}).get("error") or "el servidor no contestó"
        return fila
    texto = str(respuesta.get("texto") or "")
    # Lo que el dictado tira por ser silencio o un subtítulo inventado
    # (`transcribir.alucinacion`) cuenta como no oído: es lo que le llega.
    nada = transcribir.alucinacion(texto)
    dicho = "" if nada else texto
    terminos = list(g.get("terminos") or [])
    acertados = [t for t in terminos if _contiene(dicho, t)]
    medidas = (respuesta or {}).get("medidas") or {}
    fila.update({"hipotesis": texto, "nada": nada, "wer": wer(g["referencia"], dicho),
                 "wer_sin_tildes": wer(g["referencia"], dicho, tildes=False), "cer": cer(g["referencia"], dicho),
                 "terminos": {"total": len(terminos), "acertados": len(acertados),
                              "fallados": [t for t in terminos if t not in acertados]},
                 "ms_whisper": medidas.get("ms_whisper"), "s_audio": medidas.get("s_audio")})
    return fila


def _percentil(valores: list, p: float):
    """El de rango más cercano: el menor que deja por debajo o igual la
    fracción `p` (el p50 de [1, 2] es 1)."""
    if not valores:
        return None
    orden = sorted(valores)
    return orden[min(len(orden) - 1, max(0, math.ceil(p * len(orden)) - 1))]


def _resumir(filas: list[dict]) -> dict:
    """Las tasas del conjunto: errores sumados entre palabras sumadas (no la
    media de las tasas, que daría a «Para.» el peso de una frase larga). Las
    que el servidor no contestó no entran: se cuentan en `errores`."""
    oidas = [f for f in filas if not f.get("error")]

    def tasa(clave: str):
        n = sum(f[clave]["n"] for f in oidas)
        e = sum(f[clave]["s"] + f[clave]["b"] + f[clave]["i"] for f in oidas)
        return round(e / n, 4) if n else None
    total_t = sum(f["terminos"]["total"] for f in oidas)
    ms = [f["ms_whisper"] for f in oidas if isinstance(f.get("ms_whisper"), (int, float))]
    return {"frases": len(oidas), "wer": tasa("wer"), "wer_sin_tildes": tasa("wer_sin_tildes"),
            "cer": tasa("cer"),
            "terminos": round(sum(f["terminos"]["acertados"] for f in oidas) / total_t, 4) if total_t else None,
            "nada": sum(1 for f in oidas if f["nada"]), "errores": len(filas) - len(oidas),
            "ms_p50": _percentil(ms, 0.5), "ms_p90": _percentil(ms, 0.9)}


def _informe(filas: list[dict]) -> dict:
    """El total (sin las categorías de `APARTE`), y por categoría y aparato."""
    return {"totales": _resumir([f for f in filas if f["categoria"] not in APARTE]),
            "por_categoria": {c: _resumir([f for f in filas if f["categoria"] == c])
                              for c in sorted({f["categoria"] for f in filas})},
            "por_aparato": {a: _resumir([f for f in filas if f["aparato"] == a])
                            for a in sorted({f["aparato"] for f in filas})}}


def _medir_una(cfg: dict, grabaciones: list[dict], enchufe: Path, python: str, al_avance) -> dict:
    from . import transcribir
    d = enchufe.parent
    al_avance({"fase": "cargando", "config": cfg})
    try:
        huella = transcribir.arrancar_servidor(enchufe, python=python, modelo=cfg["modelo"], tipo=cfg.get("tipo"),
                                               dispositivo=cfg["dispositivo"], ocioso=OCIOSO_S)
    except ValueError as exc:
        return {"config": cfg, "error": str(exc)}
    if huella is None:
        return {"config": cfg, "error": "no se pudo lanzar el servidor de Whisper: " + _cola_del_registro(d)}
    try:
        if not _esperar_socket(enchufe, huella, ESPERA_CARGA_S):
            return {"config": cfg, "error": "el servidor no llegó a cargar el modelo: " + _cola_del_registro(d)}
        estado = transcribir.estado_servidor(enchufe) or {}
        filas = []
        for n, g in enumerate(grabaciones, 1):
            respuesta = transcribir.pedir(enchufe, {"ruta": str(_audio(d, g).resolve()), "idioma": "es"},
                                          ESPERA_FRASE_S)
            filas.append(_puntuar(g, respuesta))
            al_avance({"fase": "frase", "config": cfg, "hechas": n, "total": len(grabaciones)})
        rss = _rss_pico_mb(estado.get("pid"))
        # Si alguien dictó mientras tanto, hubo dos modelos a la vez y la cifra
        # puede no ser la de éste: no se impide, se apunta.
        dictado = (config.HUB_HOME / "voz" / "whisper.sock").exists()
    finally:
        try:
            transcribir.apagar_servidor(enchufe)
        except RuntimeError as exc:   # dicho, no tragado (regla 21)
            print(f"[banco] {exc}", flush=True)
    return {"config": cfg, "servidor": estado, "rss_pico_mb": rss, "dictado_cargado": dictado,
            **_informe(filas), "frases": filas}


def medir(configs: list[dict], al_avance=None, *, aparatos: tuple[str, ...] | None = None) -> dict:
    """Mide cada configuración (`{modelo, tipo, dispositivo, …}`, abierta)
    contra lo grabado, y lo deja en `resultados/<fecha>.json`.

    Cada una con su servidor de Whisper, de uno en uno, por la misma puerta
    que el dictado (`transcribir.arrancar_servidor`, `pedir`,
    `apagar_servidor`) y con el socket privado `voz/banco/medir.sock`: el
    servidor sólo lee audios de la carpeta de su socket, que es ésta. Antes
    apaga el del dictado, y no empieza si Reuniones procesa (`Ocupado`): dos
    modelos a la vez no caben en la GPU, y la cifra de uno con el otro
    cargado no sería la suya. `al_avance` recibe lo que va pasando.
    """
    avisar = al_avance or (lambda _x: None)
    configs = [_config(c) for c in configs]
    if not configs:
        raise ValueError("nada que medir: di al menos un modelo")
    d = carpeta()
    lista = [g for g in _grabaciones() if (not aparatos or g["aparato"] in aparatos)
             and (ruta := _audio(d, g)) is not None and ruta.is_file()]
    if not lista:
        raise ValueError("el banco está vacío: graba antes las frases en /voz/banco")
    # Una medida a la vez: dos compartirían `medir.sock` y se mezclarían.
    fd = os.open(carpeta(crear=True) / "medir.lock", os.O_WRONLY | os.O_CREAT, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise Ocupado("ya hay otra medida en marcha: espera a que acabe") from None
        return _medir(configs, lista, avisar)
    finally:
        os.close(fd)


def _medir(configs: list[dict], lista: list[dict], avisar) -> dict:
    from . import reuniones, transcribir
    d = carpeta()
    ocupadas = reuniones.procesando()
    if ocupadas:
        raise Ocupado(f"Reuniones está procesando ({', '.join(ocupadas)}): un modelo a la vez, "
                      "espera a que termine")
    python = transcribir.interprete_del_servidor()
    if python is None:
        raise ValueError("el transcriptor declarado en encargos.yml no es el guion del hub: no hay servidor que medir")
    enchufe = d / "medir.sock"
    if not transcribir.cabe_el_socket(enchufe):
        raise ValueError(f"la ruta del socket es demasiado larga para un socket de Unix: {enchufe}")
    transcribir.apagar_servidor(config.HUB_HOME / "voz" / "whisper.sock")
    transcribir.apagar_servidor(enchufe)   # uno de una medida que se cortó
    fecha = time.strftime("%Y%m%d-%H%M%S")
    salida = carpeta(crear=True) / "resultados"
    salida.mkdir(exist_ok=True)
    os.chmod(salida, 0o700)
    resultado = {"fecha": fecha, "version": _lista().get("version"), "grabaciones": len(lista),
                 "terminada": False, "configs": []}
    # Se guarda tras cada configuración: un Ctrl+C en la segunda no pierde la
    # primera, y `terminada` dice si llegó al final.
    for c in configs:
        resultado["configs"].append(_medir_una(c, lista, enchufe, python, avisar))
        resultado["terminada"] = len(resultado["configs"]) == len(configs)
        _escribir(salida / f"{fecha}.json", json.dumps(resultado, ensure_ascii=False, indent=1).encode("utf-8"))
    return resultado


def resultados(n: int = 20) -> list[dict]:
    """Las últimas medidas, de la más nueva a la más vieja, sin las frases:
    `{fecha, version, grabaciones, configs: [{config, servidor, totales,
    por_categoria, error}]}`."""
    d = carpeta() / "resultados"
    if not d.is_dir():
        return []
    salida = []
    for archivo in sorted(d.glob("*.json"), reverse=True)[:n]:
        try:
            r = json.loads(archivo.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        fecha = str(r.get("fecha") or archivo.stem)
        # `20261112-030000` → `2026-11-12 03:00`: la hora de la máquina, como se guardó.
        legible = (f"{fecha[0:4]}-{fecha[4:6]}-{fecha[6:8]} {fecha[9:11]}:{fecha[11:13]}"
                   if re.match(r"^\d{8}-\d{6}$", fecha) else fecha)
        salida.append({"fecha": fecha, "cuando": legible, "version": r.get("version"),
                       "grabaciones": r.get("grabaciones"), "terminada": r.get("terminada", True),
                       "configs": [{k: c.get(k) for k in ("config", "servidor", "totales", "por_categoria",
                                                          "por_aparato", "dictado_cargado", "error")}
                                   for c in r.get("configs") or []]})
    return salida


# ───────────────────────────── línea de comandos ─────────────────────────────


def _pct(x) -> str:
    return "—" if x is None else f"{x * 100:.1f} %"


def _tabla(r: dict) -> str:
    lineas = [f"{'configuración':<36} {'WER':>8} {'sin tildes':>11} {'CER':>8} {'términos':>9} "
              f"{'p50 ms':>7} {'p90 ms':>7} {'carga s':>8} {'sin resp.':>9}",
              f"(el total no lleva {', '.join(APARTE)}: va en su línea)"]
    for c in r["configs"]:
        cfg = c.get("config") or {}
        nombre = " ".join(str(cfg.get(k)) for k in ("modelo", "tipo", "dispositivo") if cfg.get(k))
        if c.get("error"):
            lineas.append(f"{nombre:<36} no se midió: {c['error']}")
            continue
        t, s = c.get("totales") or {}, c.get("servidor") or {}
        real = f"{nombre} → {s.get('tipo', '?')}/{s.get('dispositivo', '?')}"
        lineas.append(f"{real:<36} {_pct(t.get('wer')):>8} {_pct(t.get('wer_sin_tildes')):>11} "
                      f"{_pct(t.get('cer')):>8} {_pct(t.get('terminos')):>9} {t.get('ms_p50') or '—':>7} "
                      f"{t.get('ms_p90') or '—':>7} {s.get('s_carga') or '—':>8} {t.get('errores') or 0:>9}")
        if c.get("dictado_cargado"):
            lineas.append("    ⚠ el Whisper del dictado estaba cargado al acabar: hubo dos modelos a la vez")
        for cat, ct in sorted((c.get("por_categoria") or {}).items()):
            lineas.append(f"    {cat:<32} {_pct(ct.get('wer')):>8} {_pct(ct.get('wer_sin_tildes')):>11} "
                          f"{_pct(ct.get('cer')):>8}" + (f"   {ct['nada']} sin oír" if ct.get("nada") else ""))
    return "\n".join(lineas)


def main(argv: list[str] | None = None) -> int:
    import argparse

    import yaml

    partes = argparse.ArgumentParser(prog="python -m hub.banco_dictado", description=__doc__.split("\n\n")[0])
    ordenes = partes.add_subparsers(dest="orden", required=True)
    ordenes.add_parser("frases", help="la lista que se lee, en YAML (para copiarla y editarla)")
    s = ordenes.add_parser("sembrar", help="pone tu lista de frases (con el banco vacío)")
    s.add_argument("--de", required=True, help="un YAML con `version:` y `frases:`")
    ordenes.add_parser("estado", help="cuántas hay grabadas en cada aparato")
    m = ordenes.add_parser("medir", help="el WER de cada configuración de Whisper contra lo grabado")
    m.add_argument("--modelos", default="small", help="separados por comas: small,large-v3-turbo")
    m.add_argument("--tipos", default="", help="compute_type, separados por comas (vacío: el de siempre)")
    m.add_argument("--dispositivo", default="auto", choices=("auto", "cuda", "cpu"))
    m.add_argument("--aparato", choices=APARATOS, help="sólo lo grabado en uno")
    r = ordenes.add_parser("resultados", help="las medidas guardadas")
    r.add_argument("--json", action="store_true")
    args = partes.parse_args(argv)

    if args.orden == "frases":
        print(yaml.safe_dump(_lista(), allow_unicode=True, sort_keys=False, width=1000), end="")
        return 0
    if args.orden == "sembrar":
        try:
            n = sembrar(config.leer_yaml(Path(args.de).read_text(encoding="utf-8")))
        except (OSError, ValueError, yaml.YAMLError) as exc:
            print(f"no se sembró: {exc}")
            return 1
        print(f"{n} frases en {carpeta() / 'frases.yml'}")
        return 0
    if args.orden == "estado":
        for a in APARATOS:
            p = progreso(a)
            print(f"{NOMBRES_APARATO[a]}: {p['hechas']} de {p['total']}"
                  + (f" (sigue {p['siguiente']})" if p["siguiente"] else " (completo)"))
        print(f"Lista {'congelada' if congelada() else 'de la plantilla, sin congelar'}, en {carpeta()}")
        return 0
    if args.orden == "medir":
        tipos = [t.strip() for t in args.tipos.split(",") if t.strip()] or [None]
        configs = [{"modelo": mo.strip(), "tipo": t, "dispositivo": args.dispositivo}
                   for mo in args.modelos.split(",") if mo.strip() for t in tipos]

        def avance(a: dict) -> None:
            cfg = a["config"]
            nombre = " ".join(str(cfg.get(k)) for k in ("modelo", "tipo") if cfg.get(k))
            if a["fase"] == "cargando":
                print(f"{nombre}: cargando el modelo…", flush=True)
            elif a["hechas"] == a["total"] or a["hechas"] % 10 == 0:
                print(f"{nombre}: {a['hechas']} de {a['total']}", flush=True)
        try:
            resultado = medir(configs, avance, aparatos=(args.aparato,) if args.aparato else None)
        except (ValueError, Ocupado, RuntimeError) as exc:
            print(f"no se midió: {exc}")
            return 1
        print()
        print(_tabla(resultado))
        print(f"\nGuardado en {carpeta() / 'resultados' / (resultado['fecha'] + '.json')}")
        return 0
    lista = resultados()
    if args.json:
        print(json.dumps(lista, ensure_ascii=False, indent=1))
        return 0
    if not lista:
        print("Todavía no se ha medido nada.")
    for r in lista:
        print(f"── {r['cuando']} · {r['grabaciones']} grabaciones · lista v{r['version']}"
              + ("" if r["terminada"] else " · a medias (se cortó)"))
        print(_tabla(r))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
