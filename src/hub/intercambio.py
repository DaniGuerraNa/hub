"""Pasar archivos entre el teléfono y las sesiones, sin romper las dos reglas.

Lo encontró él usándolo: *«estando en el teléfono no puedo ni mandar ni recibir
archivos de las sesiones de Claude Code»*. Es un hueco de verdad —un mes
trabajando así— y a la vez choca de frente con lo que sostiene este proyecto:

* el hub **nunca escribe dentro de otros proyectos** (la primera regla), así que
  subir un archivo «a la carpeta del repo» está descartado;
* el navegador de archivos **no lee contenido** (decisión 203, elegida por él),
  así que descargarse cualquier archivo indexado está descartado también — esa
  garantía es estructural y no un filtro de nombres.

La salida no es relajar ninguna: es **una carpeta del hub** por la que pasan las
cosas a propósito. Lo que sube del teléfono aterriza aquí y en ningún otro
sitio; lo que quieras bajarte, lo copia aquí la sesión —tú o el agente, con un
`cp`— y entonces existe para el hub. Las dos direcciones tienen un gesto humano
en medio, que es exactamente el gate del principio 6: el hub no decide nunca qué
archivo cruza.

🔴 **El nombre se sanea y la ruta se resuelve contra la carpeta**, siempre. Lo
que llega es texto de un formulario en un móvil, y `../../.ssh/id_rsa` es la
primera cosa que prueba cualquiera — aquí sería tanto escribir fuera como leer
fuera.
"""

from __future__ import annotations

import json
import re
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

from . import config

CARPETA = "intercambio"

# 64 MB. Cabe un vídeo corto del móvil y un `tar.gz` de trabajo, y no cabe algo
# que llene el disco de casa estando lejos — que es el fallo que nadie podría
# arreglar desde fuera.
LIMITE = 64 * 1024 * 1024

# Lo que se permite en un nombre. El resto se sustituye: es más honesto que
# rechazar, porque quien sube una foto desde el móvil no elige cómo se llama.
LIMPIO = re.compile(r"[^A-Za-z0-9._-]+")

# Cuántos niveles de subcarpeta se miran. Una sesión deja una carpeta con su
# landing o sus muestras; un árbol entero no es algo que cruce por aquí.
#
# Cinco y no tres desde que lo de dentro va por proyecto y slot (decisión 288):
# `proyecto/slot/` ya gasta dos, y una landing dentro necesita las suyas.
PROFUNDIDAD = 5

# 🔴 Lo que se arrastra o se pega en la terminal es DE PASO: se borra solo a
# los diez días (decisión 288). Lo pidió el dueño: *«esa parte del hub sólo es
# de paso, no permanente; cada proyecto guarda lo que necesita en su propia
# carpeta»*. Sólo eso caduca: lo que se sube desde el móvil o deja una sesión
# para que te lo lleves se guardó a propósito y se queda hasta que lo borres.
#
# Cuáles son se apunta en un registro y no en el nombre: un archivo soltado
# conserva el suyo, y adivinar por el nombre borraría lo que no tocaba.
CADUCAN_DIAS = 10
REGISTRO_DE_PASO = ".de-paso.json"

# Lo que no es de ningún proyecto: lo subido sin elegir, o lo de antes.
SIN_PROYECTO = ""


def carpeta() -> Path:
    ruta = config.HUB_HOME / CARPETA
    ruta.mkdir(parents=True, exist_ok=True)
    return ruta


def nombre_seguro(nombre: str) -> str:
    """Un nombre de archivo que no puede salirse de la carpeta ni esconderse.

    Se queda con la última parte de la ruta —así `../../x` es `x`—, quita los
    acentos y reduce todo lo demás a guiones. Un nombre que se quedara vacío, o
    que empezara por punto, se sustituye: un archivo oculto en la carpeta de
    intercambio es un archivo que nadie va a ver que está ahí.
    """
    base = str(nombre).replace("\\", "/").split("/")[-1].strip()
    base = unicodedata.normalize("NFKD", base).encode("ascii", "ignore").decode()
    base = LIMPIO.sub("-", base).strip("-.")
    return base[:120] or "archivo"


def subcarpeta(proyecto_id: str = "", slot_id: int | None = None,
               slot_nombre: str = "") -> str:
    """Dónde va algo de ese proyecto y ese slot: `proyecto/12-back`.

    El número delante es lo que identifica al slot —el nombre se puede
    cambiar—; el nombre va detrás para que la carpeta se entienda sola en el
    disco.
    """
    if not proyecto_id:
        return SIN_PROYECTO
    tramos = [nombre_seguro(proyecto_id)]
    if slot_id:
        tramos.append(f"{int(slot_id)}-{nombre_seguro(slot_nombre or 'slot')}".rstrip("-"))
    return "/".join(tramos)


def libre(nombre: str, dentro: str = "") -> Path:
    """Un destino que no pisa nada. Subir dos veces «foto.jpg» son dos archivos.

    Pisar en silencio sería perder lo de antes sin decirlo, y aquí lo de antes
    puede ser justo lo que el agente acaba de dejar para que te lo lleves.
    """
    base = carpeta() / ruta_segura(dentro) if dentro else carpeta()
    base.mkdir(parents=True, exist_ok=True)
    destino = base / nombre_seguro(nombre)
    if not destino.exists():
        return destino
    tronco, punto, extension = destino.name.partition(".")
    for n in range(2, 1000):
        candidato = base / f"{tronco}-{n}{punto}{extension}"
        if not candidato.exists():
            return candidato
    raise ValueError(f"demasiados archivos llamados «{destino.name}»")


def ruta_segura(nombre: str) -> str:
    """Como `nombre_seguro`, pero conservando subcarpetas: `landing/index.html`.

    Las sesiones dejan a veces una carpeta entera (una landing, un lote de
    muestras) y lo de dentro también tiene que poder bajarse. Cada tramo se
    sanea por separado y `..`/`.` se tiran: no hay forma de escribir un tramo
    que suba. Lo que decide igualmente es `resolver`, que comprueba el destino
    ya resuelto.
    """
    tramos = [t for t in str(nombre).replace("\\", "/").split("/")
              if t.strip() not in ("", ".", "..")]
    return "/".join(nombre_seguro(t) for t in tramos[-PROFUNDIDAD:]) or "archivo"


def resolver(nombre: str) -> Path:
    """El archivo dentro de la carpeta, o nada. Nunca sale de ella.

    Se resuelve y **después** se comprueba que cae dentro, que es el orden que
    importa: hacerlo al revés es lo que dejaba salirse al navegador antes de la
    auditoría. Resolver sigue los enlaces, así que uno que apunte fuera también
    se queda fuera.
    """
    destino = (carpeta() / ruta_segura(nombre)).resolve()
    raiz = carpeta().resolve()
    if destino == raiz or raiz not in destino.parents:
        raise ValueError("ese archivo no está en la carpeta de intercambio")
    if not destino.is_file():
        raise ValueError(f"no hay ningún «{destino.name}» ahí")
    return destino


def guardar(nombre: str, datos: bytes, dentro: str = "", de_paso: bool = False) -> Path:
    """Escribe lo que llegó. Devuelve dónde quedó.

    `dentro` es la subcarpeta del proyecto y el slot (`subcarpeta`). `de_paso`
    es lo soltado o pegado en la terminal: se apunta para que caduque.
    """
    if not datos:
        raise ValueError("el archivo llegó vacío")
    if len(datos) > LIMITE:
        raise ValueError(
            f"son {tamano(len(datos))} y el límite son {tamano(LIMITE)}"
        )
    destino = libre(nombre, dentro)
    destino.write_bytes(datos)
    if de_paso:
        registro = _leer_de_paso()
        registro[destino.relative_to(carpeta()).as_posix()] = destino.stat().st_mtime
        _escribir_de_paso(registro)
    return destino


def _leer_de_paso() -> dict[str, float]:
    try:
        datos = json.loads((carpeta() / REGISTRO_DE_PASO).read_text())
        return {str(k): float(v) for k, v in datos.items()}
    except (OSError, ValueError, AttributeError):
        return {}


def _escribir_de_paso(registro: dict[str, float]) -> None:
    destino = carpeta() / REGISTRO_DE_PASO
    tmp = destino.with_suffix(".tmp")
    tmp.write_text(json.dumps(registro, indent=0, sort_keys=True))
    tmp.replace(destino)


def caduca_en(nombre: str, registro: dict[str, float] | None = None) -> float | None:
    """Cuándo se borra solo, o `None` si no caduca."""
    registro = _leer_de_paso() if registro is None else registro
    llegado = registro.get(nombre)
    return None if llegado is None else llegado + CADUCAN_DIAS * 86400


def podar_de_paso(ahora: float | None = None) -> list[str]:
    """Borra lo de paso que cumplió sus diez días. Devuelve qué borró.

    Va en el ciclo lento. Sólo toca lo apuntado en el registro, y cada ruta se
    resuelve contra la carpeta antes de borrar: el registro es un archivo, y
    lo que diga no puede sacar el borrado de aquí. Las carpetas de proyecto o
    slot que se quedan vacías se quitan también.
    """
    ahora = time.time() if ahora is None else ahora
    registro = _leer_de_paso()
    borrados = []
    for nombre in list(registro):
        if ahora < registro[nombre] + CADUCAN_DIAS * 86400:
            continue
        try:
            resolver(nombre).unlink()
            borrados.append(nombre)
        except ValueError:
            pass  # ya no estaba (lo borraste tú): sólo sale del registro
        del registro[nombre]
        padre = (carpeta() / nombre).parent
        raiz = carpeta().resolve()
        while padre.resolve() != raiz and raiz in padre.resolve().parents:
            try:
                padre.rmdir()   # sólo si está vacía
            except OSError:
                break
            padre = padre.parent
    if borrados or len(registro) != len(_leer_de_paso()):
        _escribir_de_paso(registro)
    return borrados


def listar() -> list[dict]:
    """Lo que hay, lo más nuevo primero: se viene aquí a por lo último.

    Entra en las subcarpetas (hasta `PROFUNDIDAD`): hasta el 29-sep sólo se
    listaba lo suelto, y la landing que una sesión dejó como carpeta el 25 no
    salía en la página — estaba ahí y nadie podía verla.
    """
    raiz = carpeta().resolve()
    de_paso = _leer_de_paso()
    archivos = []
    for hijo in carpeta().rglob("*"):
        relativa = hijo.relative_to(carpeta())
        if (len(relativa.parts) > PROFUNDIDAD
                or any(p.startswith(".") for p in relativa.parts)
                or not hijo.is_file()
                or raiz not in hijo.resolve().parents):
            continue
        info = hijo.stat()
        archivos.append({
            "nombre": relativa.as_posix(),
            "archivo": hijo.name,
            "subcarpeta": relativa.parent.as_posix() if len(relativa.parts) > 1 else "",
            "ruta": str(hijo),
            "bytes": info.st_size,
            "tamano": tamano(info.st_size),
            "tipo": tipo(hijo.name),
            "mtime": info.st_mtime,
            "cuando": datetime.fromtimestamp(
                info.st_mtime, timezone.utc
            ).isoformat(timespec="seconds"),
            # Los dos primeros tramos, tal cual: a qué proyecto y slot
            # corresponden lo decide `api`, que es quien conoce el registro.
            "tramos": list(relativa.parts[:-1]),
            "caduca": caduca_en(relativa.as_posix(), de_paso),
        })
    return sorted(archivos, key=lambda a: a["mtime"], reverse=True)


# ─────────────────────────────── agrupar ────────────────────────────────────
#
# Lo pidió al ver la lista crecer: *«se hace una lista interminable de archivos
# que no sé de qué son»*. Los archivos no guardan qué sesión los dejó —el hub
# no mira quién hace un `cp`—, así que «por conversación» se aproxima por lo que
# sí hay: las sesiones nombran lo que dejan con su tema delante
# (`feria-muestras-…`, `tienda-memo-…`), y ese prefijo es el tema.

# «Proyecto» primero y por omisión (decisión 288): lo que pasa por aquí es de
# un proyecto y de un slot, como todo lo demás en el hub. Lo agrupa `api`, que
# es quien sabe cómo se llaman.
AGRUPACIONES = {"proyecto": "Proyecto", "recientes": "Recientes", "tema": "Tema",
                "fecha": "Fecha", "tipo": "Tipo"}

# Cuánto tiempo algo cuenta como «nuevo»: lo que una sesión acaba de dejar
# mientras él mira. Una hora cubre una tanda de trabajo sin marcar el día entero.
NUEVO_SEGUNDOS = 3600

# Dos archivos separados por más que esto son dos tandas de subida. Una sesión
# copia una tanda en segundos; entre tandas hay una conversación de por medio.
# Lo pidió al ver dos bloques en la misma hora: *«quiero ver cuáles los acaba
# de subir»* — «la última hora» no los distinguía.
HUECO_TANDA = 600


def tandas(archivos: list[dict]) -> list[list[dict]]:
    """Cortar una lista ya ordenada (lo nuevo primero) donde hay un hueco."""
    cortes: list[list[dict]] = []
    for a in archivos:
        if cortes and cortes[-1][-1]["mtime"] - a["mtime"] <= HUECO_TANDA:
            cortes[-1].append(a)
        else:
            cortes.append([a])
    return cortes

TIPOS = (
    ("Imágenes", {"jpg", "jpeg", "png", "gif", "webp", "heic", "heif", "svg", "bmp"}),
    ("Documentos", {"pdf", "md", "txt", "doc", "docx", "odt", "rtf"}),
    ("Hojas de cálculo", {"xls", "xlsx", "csv", "ods", "tsv"}),
    ("Presentaciones", {"ppt", "pptx", "odp", "key"}),
    ("Audio", {"mp3", "m4a", "ogg", "opus", "wav", "webm", "aac", "flac"}),
    ("Vídeo", {"mp4", "mov", "mkv", "avi"}),
    ("Apps", {"apk", "aab", "ipa"}),
    ("Comprimidos", {"zip", "tar", "gz", "tgz", "7z", "rar", "bz2", "xz"}),
    ("Web y código", {"html", "htm", "css", "js", "json", "py", "ts", "yml", "yaml",
                      "xml", "sh", "sql"}),
)

# La fecha que las sesiones meten en el nombre: lo que va de ahí en adelante es
# el número de pieza, no el tema.
_FECHA_EN_NOMBRE = re.compile(r"-?\d{4}-\d{2}-\d{2}.*$")

MESES = ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio",
         "agosto", "septiembre", "octubre", "noviembre", "diciembre")


def tipo(nombre: str) -> str:
    extension = nombre.rsplit(".", 1)[-1].lower() if "." in nombre else ""
    for etiqueta, extensiones in TIPOS:
        if extension in extensiones:
            return etiqueta
    return "Otros"


def _tramos_de_tema(archivo: dict) -> list[str]:
    """Las palabras del nombre que dicen de qué va, sin fecha ni extensión.

    Si vive en una subcarpeta, manda la carpeta: quien la creó ya agrupó.
    """
    base = archivo["nombre"].split("/", 1)[0] if archivo["subcarpeta"] else archivo["archivo"]
    tronco = base.split(".", 1)[0] if not archivo["subcarpeta"] else base
    tronco = _FECHA_EN_NOMBRE.sub("", tronco)
    return [t for t in re.split(r"[-_.]+", tronco.lower()) if t] or ["archivo"]


def _por_tema(archivos: list[dict]) -> list[tuple[str, list[dict]]]:
    """Juntar por la primera palabra y nombrar el grupo por lo que comparten.

    La primera palabra sola junta de más (`feria` sola puede juntar dos cosas distintas), así que el
    grupo se llama por el prefijo común de sus miembros: tres fotos
    `feria-muestras-…` son «feria muestras», y un memo y un estudio
    `tienda-…` son «tienda».
    """
    cubos: dict[str, list[tuple[list[str], dict]]] = {}
    for a in archivos:
        tramos = _tramos_de_tema(a)
        cubos.setdefault(tramos[0], []).append((tramos, a))
    grupos = []
    for miembros in cubos.values():
        comun = miembros[0][0]
        for tramos, _ in miembros[1:]:
            n = 0
            while n < min(len(comun), len(tramos)) and comun[n] == tramos[n]:
                n += 1
            comun = comun[:n]
        grupos.append((" ".join(comun), [a for _, a in miembros]))
    return grupos


def _dia(archivo: dict, hoy: datetime) -> str:
    cuando = datetime.fromtimestamp(archivo["mtime"])
    dias = (hoy.date() - cuando.date()).days
    if dias <= 0:
        return "Hoy"
    if dias == 1:
        return "Ayer"
    if dias < 7:
        return "Esta semana"
    return f"{MESES[cuando.month - 1].capitalize()} {cuando.year}"


def agrupar(archivos: list[dict], por: str = "tema",
            hoy: datetime | None = None) -> list[dict]:
    """Los grupos, el que tiene lo más nuevo primero; dentro, lo más nuevo arriba.

    Entran ya ordenados por fecha (`listar`), y los diccionarios de Python
    guardan el orden de inserción: así el orden de los grupos sale solo.
    """
    hoy = hoy or datetime.now()
    if por == "recientes":
        # Sin carpetas: todo en fila, lo último arriba. Es lo que pidió para
        # ver lo que una sesión acaba de subir sin abrir grupos.
        pares = [("Lo más reciente", archivos)] if archivos else []
    elif por == "tema":
        pares = _por_tema(archivos)
    else:
        clave = (lambda a: _dia(a, hoy)) if por == "fecha" else (lambda a: a["tipo"])
        cubos: dict[str, list[dict]] = {}
        for a in archivos:
            cubos.setdefault(clave(a), []).append(a)
        pares = list(cubos.items())
    grupos = [{
        "titulo": titulo,
        "archivos": miembros,
        "tandas": [{"archivos": t, "desde": t[-1]["mtime"], "hasta": t[0]["mtime"]}
                   for t in tandas(miembros)],
        "cuantos": len(miembros),
        "tamano": tamano(sum(a["bytes"] for a in miembros)),
        "ultimo": max(a["mtime"] for a in miembros),
    } for titulo, miembros in pares]
    return sorted(grupos, key=lambda g: g["ultimo"], reverse=True)


def borrar(nombre: str) -> None:
    """Borrar es un acto humano. La única excepción es lo de paso (decisión
    288), y la página dice en cada archivo cuándo se irá."""
    resolver(nombre).unlink()


def tamano(bytes_: int) -> str:
    for unidad, corte in (("GB", 1024**3), ("MB", 1024**2), ("kB", 1024)):
        if bytes_ >= corte:
            return f"{bytes_ / corte:.1f} {unidad}"
    return f"{bytes_} B"
