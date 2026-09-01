"""Búsqueda sobre todo lo que el hub indexa.

Es lo que hace navegable un sistema con ~20 ubicaciones y ~60 capacidades: para
nombres de proyecto, de archivo y de agente, FTS5 le gana a los embeddings y
cabe en el mismo archivo de SQLite, sin infraestructura nueva.

Alimenta la paleta de comandos (Ctrl+K). El índice se reconstruye entero cada
vez: son unos miles de filas y así nunca queda desincronizado — que es el modo
de falla que de verdad importa en un buscador.
"""

from __future__ import annotations

import re
import sqlite3

from . import db

# Cada clase sabe a dónde lleva su resultado. Sin esto la búsqueda encuentra
# cosas pero no te lleva a ellas, que es la mitad inútil del trabajo.
_DESTINOS = {
    "proyecto": lambda ref, pid: f"/proyecto/{ref}",
    "slot": lambda ref, pid: f"/trabajo?slot={ref}",
    "capacidad": lambda ref, pid: f"/inventario?proyecto={pid}" if pid else "/inventario",
    "servicio": lambda ref, pid: "/servicios",
    "conexion": lambda ref, pid: "/conexiones",
    "sesion": lambda ref, pid: f"/trabajo?session={ref}",
}


def reindexar(con: sqlite3.Connection) -> int:
    """Repuebla el índice desde las tablas ya pobladas. Devuelve cuántas filas."""
    if not db.hay_fts(con):
        return 0
    filas: list[tuple] = []

    for f in con.execute("SELECT id, nombre, nota, dominio, status FROM proyecto"):
        filas.append(
            ("proyecto", f["id"], f["nombre"], f"{f['nota']} {f['dominio']} {f['status']}", f["id"])
        )
    for f in con.execute(
        """SELECT s.id, s.nombre, s.nota, s.ruta, s.proyecto_id, p.nombre AS proyecto
           FROM slot s LEFT JOIN proyecto p ON p.id = s.proyecto_id
           WHERE s.status = 'activo'"""
    ):
        filas.append(
            ("slot", str(f["id"]), f["nombre"],
             f"{f['nota'] or ''} {f['ruta'] or ''} {f['proyecto'] or ''}", f["proyecto_id"])
        )
    for f in con.execute("SELECT tipo, nombre, descripcion, ruta, proyecto_id FROM capacidad"):
        filas.append(
            ("capacidad", f["nombre"], f["nombre"],
             f"{f['tipo']} {f['descripcion']} {f['ruta']}", f["proyecto_id"])
        )
    for f in con.execute("SELECT contenedor, imagen, estado, proyecto_id FROM servicio"):
        filas.append(
            ("servicio", f["contenedor"], f["contenedor"],
             f"{f['imagen']} {f['estado']} docker contenedor", f["proyecto_id"])
        )
    for f in con.execute("SELECT alias, host, proposito FROM conexion"):
        filas.append(
            ("conexion", f["alias"], f["alias"], f"{f['host'] or ''} {f['proposito']}", None)
        )

    con.execute("DELETE FROM indice")
    con.executemany(
        "INSERT INTO indice (clase, ref, titulo, cuerpo, proyecto_id) VALUES (?,?,?,?,?)", filas
    )
    return len(filas)


# Qué clase de resultado quieres ver primero cuando todo empata. Un proyecto es
# un sitio al que ir; un contenedor casi nunca lo es. Sin esto, buscar
# el nombre de un proyecto devolvía catorce contenedores suyos y el proyecto no.
_PRIORIDAD = {"proyecto": 0, "slot": 1, "capacidad": 2, "conexion": 3, "servicio": 4}


def _orden(fila, texto: str) -> tuple:
    """Coincidencia más exacta primero, y a igualdad, la clase más navegable."""
    titulo = (fila["titulo"] or "").lower()
    consulta = texto.lower()
    exactitud = 0 if titulo == consulta else (1 if titulo.startswith(consulta) else 2)
    return (exactitud, _PRIORIDAD.get(fila["clase"], 9), len(titulo))


def _consulta_fts(texto: str) -> str:
    """Convierte lo tecleado en una consulta FTS de prefijo, término a término.

    Se citan los términos porque el texto es libre: un guion, un punto o un
    paréntesis sueltos son sintaxis para FTS5 y harían reventar la consulta
    justo cuando alguien busca `dev-backend` o `mutar.py`.
    """
    terminos = [t for t in re.split(r"\W+", texto, flags=re.UNICODE) if t]
    return " AND ".join(f'"{t}"*' for t in terminos)


def buscar(con: sqlite3.Connection, texto: str, limite: int = 20) -> list[dict]:
    """Resultados ordenados por relevancia, cada uno con su destino."""
    texto = (texto or "").strip()
    if len(texto) < 2:
        return []

    if db.hay_fts(con):
        consulta = _consulta_fts(texto)
        if not consulta:
            return []
        try:
            # Se pide de más y se reordena abajo: recortar antes del reordenado
            # dejaría fuera el proyecto que se buscaba porque catorce
            # contenedores puntúan mejor en bm25.
            filas = con.execute(
                """SELECT clase, ref, titulo, cuerpo, proyecto_id
                   FROM indice WHERE indice MATCH ? ORDER BY rank LIMIT ?""",
                (consulta, limite * 5),
            ).fetchall()
        except sqlite3.OperationalError:
            filas = []
    else:
        filas = _buscar_like(con, texto, limite * 5)

    filas = sorted(filas, key=lambda f: _orden(f, texto))[:limite]

    return [
        {
            "clase": f["clase"],
            "ref": f["ref"],
            "titulo": f["titulo"],
            "detalle": " ".join((f["cuerpo"] or "").split())[:120],
            "proyecto_id": f["proyecto_id"],
            "url": _DESTINOS.get(f["clase"], lambda r, p: "/")(f["ref"], f["proyecto_id"]),
        }
        for f in filas
    ]


def _buscar_like(con: sqlite3.Connection, texto: str, limite: int) -> list[sqlite3.Row]:
    """Respaldo sin FTS5. Peor ordenado, pero encuentra."""
    patron = f"%{texto}%"
    salida: list[sqlite3.Row] = []
    salida += con.execute(
        """SELECT 'proyecto' AS clase, id AS ref, nombre AS titulo, nota AS cuerpo,
                  id AS proyecto_id
           FROM proyecto WHERE nombre LIKE ? OR nota LIKE ? LIMIT ?""",
        (patron, patron, limite),
    ).fetchall()
    salida += con.execute(
        """SELECT 'slot' AS clase, CAST(id AS TEXT) AS ref, nombre AS titulo,
                  nota AS cuerpo, proyecto_id
           FROM slot WHERE status='activo' AND (nombre LIKE ? OR nota LIKE ?) LIMIT ?""",
        (patron, patron, limite),
    ).fetchall()
    salida += con.execute(
        """SELECT 'capacidad' AS clase, nombre AS ref, nombre AS titulo,
                  descripcion AS cuerpo, proyecto_id
           FROM capacidad WHERE nombre LIKE ? OR descripcion LIKE ? LIMIT ?""",
        (patron, patron, limite),
    ).fetchall()
    return salida[:limite]
