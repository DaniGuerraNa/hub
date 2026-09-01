"""Lectura de los transcripts de Claude Code.

Es la base del asistente: su historial no se almacena en
ninguna parte: **es** el transcript JSONL que Claude Code ya escribe. El hub lo
lee y lo pinta. Nada se duplica (principio 1: el hub indexa, no copia).

La razón de que esto exista como módulo aparte del asistente es el factor de
reducción. Medido con este filtro sobre los cinco transcripts más grandes de la
una máquina real (2026-08-28): de 14,2 MB a 108 KB (135×) en el mejor caso, y de
7,9 MB a 507 KB (16×) en el peor, que es una sesión larguísima de conversación
donde casi todo el volumen ya era texto humano. **El peor caso cabe holgado en
una ventana de contexto**, y por eso el asistente no necesita un modelo grande
para contestar «qué se hizo ayer en tal proyecto»: filtrar es determinista y es
trabajo del hub; resumir es del modelo.

(El plan original decía «173×» sobre una estimación previa. No se reproduce con
el filtro real, que además conserva uuid y timestamp por mensaje. Regla dura 13:
la cifra se corrige, no se defiende.)

Tres niveles, para que quien pregunta decida cuánto baja:

    índice     — qué sesiones hubo, cuándo y de qué van
    esqueleto  — todo el texto humano y del modelo, sin ruido de herramientas
    zoom       — el detalle crudo de un tramo, cuando el esqueleto no basta

Un transcript se está escribiendo mientras se lee: la última línea puede estar a
medias. Aquí eso nunca es un error, sólo una línea menos.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .models import Proyecto

# Donde Claude Code guarda sus transcripts. Un directorio por ruta de trabajo.
TRANSCRIPTS = Path.home() / ".claude" / "projects"

# Sólo estos dos tipos de línea cuentan qué pasó. El resto —`mode`,
# `permission-mode`, `file-history-snapshot`, `attachment`, `system`,
# `last-prompt`, `queue-operation`…— es maquinaria de la sesión.
TIPOS_UTILES = ("user", "assistant")

# Un id de sesión es el nombre de un archivo: si viene de una URL y no se valida,
# `../../..` sale del directorio de transcripts.
ID_SESION = re.compile(r"^[0-9a-fA-F-]{8,64}$")

_NO_ALFANUMERICO = re.compile(r"[^a-zA-Z0-9]")

# Cuánto texto de una herramienta se conserva en la línea colapsada. Lo que
# importa es reconocer la acción, no reproducirla.
ANCHO_HERRAMIENTA = 60


def slug_de(ruta: str) -> str:
    """Nombre del directorio de transcripts para una ruta de trabajo.

    Cada carácter no alfanumérico pasa a `-`. Comprobado contra el disco:
    `/mnt/c/Users/ana_/proyectos/tienda` → `-mnt-c-Users-ana--proyectos-tienda`.
    La doble `--` sale de `ana_/`: **dos caracteres no alfanuméricos seguidos
    son dos guiones, no uno.** No se colapsan, y colapsarlos hacía que el hub
    buscara los transcripts en un directorio que no existe.
    """
    return _NO_ALFANUMERICO.sub("-", str(Path(ruta).expanduser()).rstrip("/"))


def directorios_de(proyecto: Proyecto) -> list[Path]:
    """Los directorios de transcripts de un proyecto: uno por ruta suya.

    Un proyecto se trabaja desde varias rutas —se orquesta desde `/mnt/c` y su
    código vive en `~/dev`— y cada una tiene su propio directorio.
    """
    vistos: dict[str, Path] = {}
    for ruta in proyecto.todas_las_rutas():
        camino = TRANSCRIPTS / slug_de(ruta)
        if camino.is_dir():
            vistos[camino.name] = camino
    return list(vistos.values())


# --------------------------------------------------------------------------- #
# Lectura cruda
# --------------------------------------------------------------------------- #


def leer_lineas(ruta: Path) -> Iterator[dict[str, Any]]:
    """Las líneas del JSONL ya parseadas, saltándose las rotas.

    Una línea a medio escribir es lo normal cuando la sesión está viva, y una
    sesión viva es justo el caso que más interesa mirar. Reventar ahí dejaría al
    asistente ciego sobre lo que está pasando ahora mismo.
    """
    try:
        with ruta.open(encoding="utf-8") as f:
            for linea in f:
                linea = linea.strip()
                if not linea:
                    continue
                try:
                    dato = json.loads(linea)
                except (json.JSONDecodeError, ValueError):
                    continue
                if isinstance(dato, dict):
                    yield dato
    except OSError:
        return


def ruta_de_sesion(session_id: str, directorios: list[Path] | None = None) -> Path | None:
    """Localiza el archivo de una sesión. None si el id no es válido o no está."""
    if not ID_SESION.match(session_id or ""):
        return None
    for directorio in directorios if directorios is not None else _todos_los_directorios():
        candidato = directorio / f"{session_id}.jsonl"
        if candidato.is_file():
            return candidato
    return None


def _todos_los_directorios() -> list[Path]:
    if not TRANSCRIPTS.is_dir():
        return []
    try:
        return sorted(d for d in TRANSCRIPTS.iterdir() if d.is_dir())
    except OSError:
        return []


# --------------------------------------------------------------------------- #
# Nivel 1 — índice
# --------------------------------------------------------------------------- #


def resumir_sesion(ruta: Path) -> dict[str, Any] | None:
    """Ficha de una sesión sin bajar a su contenido.

    El título no se inventa ni se pide a un modelo: Claude Code ya escribe
    líneas `ai-title` con el que él mismo puso. Si hay varias —una sesión larga
    cambia de tema— manda la última.
    """
    inicio = fin = None
    titulo = rama = cwd = None
    mensajes = 0
    humanos = 0

    for dato in leer_lineas(ruta):
        tipo = dato.get("type")
        if tipo == "ai-title":
            titulo = dato.get("aiTitle") or titulo
            continue
        if tipo not in TIPOS_UTILES or dato.get("isSidechain"):
            continue
        ts = dato.get("timestamp")
        if ts:
            inicio = inicio or ts
            fin = ts
        rama = dato.get("gitBranch") or rama
        cwd = cwd or dato.get("cwd")
        mensajes += 1
        if tipo == "user" and _texto_de(dato):
            humanos += 1

    if not mensajes:
        return None

    return {
        "id": ruta.stem,
        "titulo": titulo,
        "inicio": inicio,
        "fin": fin,
        "duracion_min": _duracion_min(inicio, fin),
        "mensajes": mensajes,
        "turnos": humanos,
        "rama": rama,
        "cwd": cwd,
        "bytes": _tamano(ruta),
    }


def listar_sesiones(
    proyectos: list[Proyecto],
    proyecto_id: str | None = None,
    desde: str | None = None,
    limite: int = 30,
) -> list[dict[str, Any]]:
    """Índice de sesiones, de la más reciente a la más vieja.

    `desde` es una fecha ISO y se aplica sobre el mtime del archivo **antes** de
    abrirlo. Es lo que hace que preguntar por «ayer» no cueste leer los 15 MB de
    todo lo demás.
    """
    corte = _a_epoch(desde)
    candidatos: list[tuple[float, Path, str | None]] = []

    for proyecto in proyectos:
        if proyecto_id and proyecto.id != proyecto_id:
            continue
        for directorio in directorios_de(proyecto):
            for archivo in jsonl_de(directorio):
                tocado = mtime(archivo)
                if corte is not None and tocado < corte:
                    continue
                candidatos.append((tocado, archivo, proyecto.id))

    candidatos.sort(key=lambda c: c[0], reverse=True)

    sesiones = []
    for _, archivo, dueno in candidatos[: max(0, limite)]:
        ficha = resumir_sesion(archivo)
        if ficha:
            ficha["proyecto_id"] = dueno
            sesiones.append(ficha)
    return sesiones


def jsonl_de(directorio: Path) -> list[Path]:
    try:
        return [a for a in directorio.iterdir() if a.is_file() and a.suffix == ".jsonl"]
    except OSError:
        return []


# --------------------------------------------------------------------------- #
# Nivel 2 — esqueleto
# --------------------------------------------------------------------------- #


def esqueleto(ruta: Path, limite: int | None = None, desde_uuid: str | None = None) -> dict[str, Any]:
    """La conversación sin el ruido: todo el texto, las herramientas en una línea.

    Qué se tira y por qué:
      `isSidechain`  — son subagentes; su conversación no es esta conversación.
      `thinking`     — razonamiento intermedio, no lo que se dijo ni lo que se hizo.
      `tool_result`  — la salida de una herramienta, que es el 99 % del volumen.
      el `input`     — de una llamada sólo queda su nombre y su argumento clave.

    Qué se conserva íntegro: **todo el texto** de `user` y `assistant`. Es lo
    único que cuenta qué pasó, y recortarlo sería resumir, que no es de este lado.

    `desde_uuid` devuelve sólo lo posterior a ese mensaje, que es como el chat
    pide lo nuevo sin releer la conversación entera en cada sondeo.
    """
    todos: list[dict[str, Any]] = []
    corte = -1

    for dato in leer_lineas(ruta):
        if dato.get("type") not in TIPOS_UTILES or dato.get("isSidechain"):
            continue
        mensaje = _condensar(dato)
        if not mensaje:
            continue
        todos.append(mensaje)
        if desde_uuid and mensaje["uuid"] == desde_uuid:
            # El uuid marca lo ya visto: se descarta él y todo lo anterior.
            corte = len(todos) - 1

    # Si el uuid no aparece, `corte` sigue en -1 y se devuelve la conversación
    # entera: la sesión se limpió o se compactó bajo los pies del chat, y
    # repintarlo todo es preferible a dejarlo en blanco.
    mensajes = todos[corte + 1:] if corte >= 0 else todos

    if limite is not None and limite >= 0:
        mensajes = mensajes[-limite:]

    return {"id": ruta.stem, "mensajes": mensajes}


def _condensar(dato: dict[str, Any]) -> dict[str, Any] | None:
    """Un mensaje reducido a texto + herramientas. None si no queda nada."""
    texto = _texto_de(dato)
    herramientas = _herramientas_de(dato)
    if not texto and not herramientas:
        return None
    return {
        "uuid": dato.get("uuid"),
        "rol": dato.get("type"),
        "ts": dato.get("timestamp"),
        "texto": texto,
        "herramientas": herramientas,
    }


def _bloques(dato: dict[str, Any]) -> list[dict[str, Any]]:
    """Los bloques de contenido, ya venga como lista o como string plano.

    `user.message.content` es **string** cuando el usuario escribe y **lista** cuando
    lleva `tool_result`. `assistant.message.content` es siempre lista. Normalizar
    aquí evita que cada consumidor se acuerde de las dos formas.
    """
    contenido = (dato.get("message") or {}).get("content")
    if isinstance(contenido, str):
        return [{"type": "text", "text": contenido}]
    if isinstance(contenido, list):
        return [b for b in contenido if isinstance(b, dict)]
    return []


def _texto_de(dato: dict[str, Any]) -> str:
    partes = [b.get("text", "") for b in _bloques(dato) if b.get("type") == "text"]
    return "\n".join(p for p in partes if p).strip()


def _herramientas_de(dato: dict[str, Any]) -> list[str]:
    return [
        etiqueta_herramienta(b.get("name", "?"), b.get("input"))
        for b in _bloques(dato)
        if b.get("type") == "tool_use"
    ]


# El argumento que identifica cada herramienta, en orden de preferencia. Sin
# esto la línea colapsada diría sólo «Edit», que no distingue una edición de otra.
ARGUMENTO_CLAVE = ("file_path", "command", "pattern", "path", "url", "description",
                   "query", "notebook_path", "prompt")


def etiqueta_herramienta(nombre: str, entrada: Any) -> str:
    """Una llamada a herramienta en ~60 caracteres: `[Bash: uv run pytest]`."""
    if not isinstance(entrada, dict):
        return f"[{nombre}]"
    for clave in ARGUMENTO_CLAVE:
        valor = entrada.get(clave)
        if isinstance(valor, str) and valor.strip():
            resumen = " ".join(valor.split())
            if len(resumen) > ANCHO_HERRAMIENTA:
                resumen = resumen[: ANCHO_HERRAMIENTA - 1] + "…"
            separador = " " if clave == "file_path" else ": "
            return f"[{nombre}{separador}{resumen}]"
    return f"[{nombre}]"


# --------------------------------------------------------------------------- #
# Nivel 3 — zoom
# --------------------------------------------------------------------------- #


def zoom(ruta: Path, desde: str | None = None, hasta: str | None = None) -> dict[str, Any]:
    """El tramo crudo entre dos uuids, con lo que el esqueleto descarta.

    Es la válvula de escape: cuando el esqueleto dice «aquí hubo 14 ediciones» y
    hace falta saber cuáles. Se pide por tramo justamente para que el volumen no
    vuelva por la puerta de atrás.
    """
    dentro = desde is None
    lineas: list[dict[str, Any]] = []

    for dato in leer_lineas(ruta):
        if dato.get("type") not in TIPOS_UTILES:
            continue
        uuid = dato.get("uuid")
        if not dentro:
            if uuid == desde:
                dentro = True
            else:
                continue
        lineas.append(_crudo(dato))
        if hasta and uuid == hasta:
            break

    return {"id": ruta.stem, "desde": desde, "hasta": hasta, "lineas": lineas}


def _crudo(dato: dict[str, Any]) -> dict[str, Any]:
    """Como viene, menos los campos de transporte que no dicen nada al leerlo."""
    mensaje = dato.get("message") or {}
    return {
        "uuid": dato.get("uuid"),
        "rol": dato.get("type"),
        "ts": dato.get("timestamp"),
        "sidechain": bool(dato.get("isSidechain")),
        "modelo": mensaje.get("model"),
        "contenido": _bloques(dato),
    }


# --------------------------------------------------------------------------- #
# Ocupación de la ventana de contexto — vía B
# --------------------------------------------------------------------------- #

# Lo que ocupa la ventana es la entrada del último turno, cacheada o no. La
# salida no cuenta: ya está dentro de la entrada del turno siguiente.
CAMPOS_ENTRADA = ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")


def ultima_ocupacion(ruta: Path) -> dict[str, Any] | None:
    """Tokens ocupados según el último `usage` del transcript.

    Es el **respaldo** de la medición de contexto, no la vía principal: la exacta
    es el JSON que Claude Code pasa al statusline, que es el
    número que enseña `/context`. Esta se calcula y funciona sin configurar nada,
    pero necesita saber el tamaño de la ventana del modelo para dar un
    porcentaje. Verificado contra el transcript real: 363.229 tokens.
    """
    ultimo = None
    for dato in leer_lineas(ruta):
        if dato.get("type") != "assistant" or dato.get("isSidechain"):
            continue
        mensaje = dato.get("message") or {}
        uso = mensaje.get("usage")
        if isinstance(uso, dict):
            ultimo = (uso, mensaje.get("model"), dato.get("timestamp"))

    if not ultimo:
        return None

    uso, modelo, ts = ultimo
    tokens = sum(int(uso.get(c) or 0) for c in CAMPOS_ENTRADA)
    return {"tokens": tokens, "modelo": modelo, "medido_en": ts, "origen": "transcript"}


# --------------------------------------------------------------------------- #
# Utilidades
# --------------------------------------------------------------------------- #


def _tamano(ruta: Path) -> int:
    try:
        return ruta.stat().st_size
    except OSError:
        return 0


def mtime(ruta: Path) -> float:
    try:
        return ruta.stat().st_mtime
    except OSError:
        return 0.0


def _a_epoch(cuando: str | None) -> float | None:
    if not cuando:
        return None
    try:
        momento = datetime.fromisoformat(cuando.replace("Z", "+00:00"))
    except ValueError:
        return None
    if momento.tzinfo is None:
        momento = momento.replace(tzinfo=timezone.utc)
    return momento.timestamp()


def _duracion_min(inicio: str | None, fin: str | None) -> int | None:
    """Cuánto duró la sesión. Es el dato del caso de uso rector: dejaste un
    proyecto trabajando y quieres saber qué salió de aquellas 7 h 51 min."""
    a, b = _a_epoch(inicio), _a_epoch(fin)
    if a is None or b is None:
        return None
    return max(0, round((b - a) / 60))
