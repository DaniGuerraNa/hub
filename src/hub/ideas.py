"""La bandeja de ideas del dueño: apuntarlas sin interrumpir, tomarlas de una en una (decisión 342).

Se le ocurre una mejora mientras se trabaja en otra cosa. Decirla en la sesión
la interrumpe, y no decirla la pierde. Aquí se suelta en una línea (desde
`/tablero`, el teléfono, el secretario o la terminal) y se queda esperando.

🔴 **Una idea no es todavía un pendiente.** No tiene tamaño, tipo ni módulos:
eso lo decide quien la toma. Por eso no se crea una ficha al apuntarla. La
ficha nace al tomarla (`scripts/cambios.py nueva … --idea N` en el repo del
hub; en otro proyecto, lo que use ese proyecto), la idea queda `tomada` con la
referencia y desde ahí el pendiente vive en un solo sitio. `hub-web` tampoco
escribe en el árbol de git donde trabaja una sesión: los números de ficha
chocarían y los archivos se colarían en el commit de otro.

Nada la toma sola ni avisa de que hay ideas (principio 9, regla dura 3):
quien trabaja mira la bandeja al cerrar un cambio. Borrar no se expone
(decisión 69): se descarta, con su motivo, y se sigue viendo.

    uv run python -m hub.ideas lista
    uv run python -m hub.ideas apuntar "texto" [--proyecto id] [--detalle …]
    uv run python -m hub.ideas tomar <id> <ref>
    uv run python -m hub.ideas descartar <id> "motivo"
"""

from __future__ import annotations

import argparse
import sqlite3
import sys

from . import registry
from .reloj import ahora

ORIGENES = ("web", "secretario", "cli")
ESTADOS = ("nueva", "tomada", "descartada")
#: Una idea es una línea. Lo largo va en el detalle, y hasta ahí: esto no es
#: un documento.
LARGO_TEXTO = 300
LARGO_DETALLE = 4000
#: Adjuntos por idea (C-0149). Cada uno, hasta `intercambio.LIMITE`.
MAX_ADJUNTOS = 10
#: Lo que se enseña en línea en la pantalla. Sólo imágenes raster: un SVG o un
#: HTML servido en el mismo origen que la terminal sería un XSS con una shell
#: detrás. Lo demás se baja.
TIPOS_IMAGEN = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                ".gif": "image/gif", ".webp": "image/webp"}
IMAGENES = tuple(TIPOS_IMAGEN)


def _proyecto_valido(proyecto: str | None) -> str | None:
    proyecto = (proyecto or "").strip() or None
    if proyecto and proyecto not in {p.id for p in registry.cargar()}:
        raise ValueError(f"no hay ningún proyecto «{proyecto}» en el registro")
    return proyecto


def apuntar(con: sqlite3.Connection, texto: str, detalle: str = "", proyecto: str | None = None,
            origen: str = "web") -> int:
    texto = " ".join((texto or "").split())
    if not texto:
        raise ValueError("una idea vacía no se apunta")
    if len(texto) > LARGO_TEXTO:
        raise ValueError(f"la idea va en una línea (hasta {LARGO_TEXTO} caracteres); lo demás, en el detalle")
    if origen not in ORIGENES:
        raise ValueError(f"origen desconocido: {origen}")
    cursor = con.execute(
        "INSERT INTO idea (texto, detalle, proyecto, origen, estado, creada) VALUES (?, ?, ?, ?, 'nueva', ?)",
        (texto, (detalle or "").strip()[:LARGO_DETALLE], _proyecto_valido(proyecto), origen, ahora()))
    return int(cursor.lastrowid)


def ver(con: sqlite3.Connection, idea_id: int) -> dict | None:
    fila = con.execute("SELECT * FROM idea WHERE id = ?", (int(idea_id),)).fetchone()
    return dict(fila) if fila else None


def listar(con: sqlite3.Connection, estado: str = "nueva", proyecto: str | None = None,
           limite: int = 200) -> list[dict]:
    """Las nuevas, de la más antigua a la más nueva (se toman en ese orden);
    las tomadas y descartadas, al revés (lo reciente primero)."""
    if estado not in ESTADOS:
        raise ValueError(f"estado desconocido: {estado}")
    orden = "id ASC" if estado == "nueva" else "COALESCE(movida, creada) DESC"
    filtro, valores = "estado = ?", [estado]
    if proyecto:
        filtro += " AND proyecto = ?"
        valores.append(proyecto)
    return [dict(f) for f in con.execute(
        f"SELECT * FROM idea WHERE {filtro} ORDER BY {orden} LIMIT ?", (*valores, int(limite)))]


def _mover(con: sqlite3.Connection, idea_id: int, estado: str, ref: str = "", motivo: str = "") -> None:
    idea = ver(con, idea_id)
    if not idea:
        raise ValueError(f"no hay ninguna idea {idea_id}")
    if idea["estado"] != "nueva":
        raise ValueError(f"la idea {idea_id} ya está {idea['estado']}" + (f" ({idea['ref']})" if idea["ref"] else ""))
    con.execute("UPDATE idea SET estado = ?, ref = ?, motivo = ?, movida = ? WHERE id = ?",
                (estado, ref, motivo, ahora(), int(idea_id)))


def tomar(con: sqlite3.Connection, idea_id: int, ref: str) -> None:
    """Alguien la toma: `ref` dice dónde vive ya (una ficha, `C-0147`)."""
    ref = (ref or "").strip()
    if not ref:
        raise ValueError("al tomar una idea se dice dónde sigue (p.ej. su ficha, C-0147)")
    _mover(con, idea_id, "tomada", ref=ref)


def descartar(con: sqlite3.Connection, idea_id: int, motivo: str) -> None:
    motivo = (motivo or "").strip()
    if not motivo:
        raise ValueError("descartar una idea lleva su motivo")
    _mover(con, idea_id, "descartada", motivo=motivo)


# ── Adjuntos (C-0149, decisión 343) ──────────────────────────────────────────
#
# Por la puerta de `intercambio` y no por una carpeta propia: el saneado de
# nombres, el no pisar y el no salirse de la carpeta ya están ahí, y copiarlos
# es el defecto que la 338 existe para evitar. La lista se deriva de la carpeta,
# sin columna en la tabla: un segundo registro acabaría desincronizado.
# 🔴 No entran en la copia diaria de `hub.db`: viven en `HUB_HOME/intercambio/`.

def carpeta_adjuntos(idea_id: int) -> str:
    return f"_tablero/{int(idea_id)}"


def adjuntos(idea_id: int) -> list[dict]:
    from . import intercambio
    salida = []
    for a in intercambio.listar(dentro=carpeta_adjuntos(idea_id)):
        salida.append({**a, "imagen": a["archivo"].lower().endswith(IMAGENES)})
    return sorted(salida, key=lambda a: a["mtime"])


def adjuntar(con: sqlite3.Connection, idea_id: int, nombre: str, datos: bytes):
    """Guarda un archivo con la idea. Sólo mientras espera: una idea tomada ya
    sigue en su ficha, y lo que haga falta se le añade allí."""
    from . import intercambio
    idea = ver(con, idea_id)
    if not idea:
        raise ValueError(f"no hay ninguna idea {idea_id}")
    if idea["estado"] != "nueva":
        raise ValueError(f"la idea {idea_id} ya está {idea['estado']}: los adjuntos van mientras espera")
    if len(adjuntos(idea_id)) >= MAX_ADJUNTOS:
        raise ValueError(f"una idea lleva hasta {MAX_ADJUNTOS} adjuntos")
    return intercambio.guardar(nombre or "adjunto", datos, dentro=carpeta_adjuntos(idea_id))


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - fino sobre lo de arriba
    from . import db

    p = argparse.ArgumentParser(prog="hub.ideas", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="orden", required=True)
    l = sub.add_parser("lista")
    l.add_argument("--estado", choices=ESTADOS, default="nueva")
    l.add_argument("--proyecto")
    a = sub.add_parser("apuntar")
    a.add_argument("texto")
    a.add_argument("--detalle", default="")
    a.add_argument("--proyecto")
    t = sub.add_parser("tomar", help="en el repo del hub no: ahí se toma con scripts/cambios.py nueva --idea N, "
                                     "que crea la ficha; esto es para proyectos que siguen la suya en otro sitio")
    t.add_argument("id", type=int)
    t.add_argument("ref")
    d = sub.add_parser("descartar")
    d.add_argument("id", type=int)
    d.add_argument("motivo")
    args = p.parse_args(argv)
    con = db.abrir()
    try:
        if args.orden == "lista":
            for i in listar(con, args.estado, args.proyecto):
                donde = f" [{i['proyecto']}]" if i["proyecto"] else ""
                extra = f" → {i['ref']}" if i["ref"] else (f" — {i['motivo']}" if i["motivo"] else "")
                print(f"{i['id']:>4}  {i['creada'][:10]}{donde}  {i['texto']}{extra}")
                if i["detalle"] and args.estado == "nueva":
                    print("        " + i["detalle"].replace("\n", "\n        "))
                for adj in adjuntos(i["id"]):
                    print(f"        📎 {adj['ruta']}")
        elif args.orden == "apuntar":
            print(f"idea {apuntar(con, args.texto, args.detalle, args.proyecto, origen='cli')} apuntada")
        elif args.orden == "tomar":
            tomar(con, args.id, args.ref)
            print(f"idea {args.id} tomada → {args.ref}")
        else:
            descartar(con, args.id, args.motivo)
            print(f"idea {args.id} descartada")
        con.commit()
        return 0
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 2
    finally:
        con.close()


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
