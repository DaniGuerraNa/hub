"""Conexiones: dónde despliega cada cosa y dónde vive su credencial.

Recupera la intención de `commons` —centralizar los datos de VPS para poder
decir *"despliega en X vps para probar"*— sin repetir su error: `commons` acabó
siendo una carpeta con un `.env` suelto y nada más.

🔴 **El hub nunca almacena el secreto** (decisión 28, regla dura 5). Sólo guarda
datos de conexión y un **puntero** a dónde vive: la config de ssh, un gestor de
secretos, un `.env`. Un índice de proyectos no es un almacén de credenciales, y
convertirlo en uno multiplica el radio de daño de cualquier fallo.

Lo único que se comprueba del puntero es **si existe**. Nunca se lee.
"""

from __future__ import annotations

import contextlib
import sqlite3
from pathlib import Path

from . import db
from .models import Conexion

# Nombres de campo que jamás deben aparecer en `projects.yml`. Si alguien pega
# aquí una contraseña "temporalmente", el hub lo dice en voz alta en vez de
# guardarla en silencio.
_PROHIBIDOS = {
    "password", "passwd", "clave", "contrasena", "contraseña", "secret", "secreto",
    "token", "api_key", "apikey", "private_key", "llave", "pass",
}


def revisar_secretos(crudo: dict) -> list[str]:
    """Campos sospechosos de contener un secreto en claro."""
    return sorted(k for k in crudo if k.lower().replace("-", "_") in _PROHIBIDOS)


def puntero_existe(referencia: str | None) -> bool | None:
    """Si el sitio al que apunta la referencia existe. `None` si no se puede saber.

    Formato `ruta#ancla`: la parte antes de `#` es un archivo. No se abre — sólo
    se comprueba su presencia, que es lo máximo que un índice debe hacer con
    algo que guarda credenciales.
    """
    if not referencia:
        return None
    ruta = referencia.split("#", 1)[0].strip()
    if not ruta or "://" in ruta:  # una URL de gestor de secretos no se sondea
        return None
    return Path(ruta).expanduser().exists()


def sincronizar(con: sqlite3.Connection, conexiones: list[Conexion]) -> bool:
    """Refleja las conexiones de `projects.yml` en el índice. El YAML manda.

    Devuelve si escribió. Como el registro (C-0275): el latido la llama cada
    20 s, así que sólo se escribe si lo que quedaría difiere de lo que hay, y
    de una vez. Se compara lo que se escribiría —con `puntero_ok` ya medido—
    y no el YAML: que aparezca el archivo del puntero también es un cambio.
    El puntero se mira antes de abrir la transacción: dentro, sólo base
    (decisión 352).
    """
    filas = [
        (c.alias, c.host, c.usuario, c.proposito, c.referencia_secreto,
         _a_entero(puntero_existe(c.referencia_secreto)), c.nota)
        for c in conexiones
    ]
    # `INSERT OR IGNORE`: un proyecto repetido en la lista entra una vez.
    vinculos = list(dict.fromkeys(
        (c.alias, proyecto_id) for c in conexiones for proyecto_id in c.proyectos))
    hay = [tuple(f) for f in con.execute(
        "SELECT alias, host, usuario, proposito, referencia_secreto, puntero_ok, nota"
        " FROM conexion ORDER BY rowid")]
    hay_vinculos = [tuple(f) for f in con.execute(
        "SELECT alias, proyecto_id FROM conexion_proyecto ORDER BY rowid")]
    if hay == filas and hay_vinculos == vinculos:
        return False

    with contextlib.nullcontext() if con.in_transaction else db.transaccion(con):
        con.execute("DELETE FROM conexion")
        con.execute("DELETE FROM conexion_proyecto")
        con.executemany(
            """INSERT INTO conexion (alias, host, usuario, proposito, referencia_secreto,
                                     puntero_ok, nota)
               VALUES (?,?,?,?,?,?,?)""",
            filas,
        )
        con.executemany(
            "INSERT OR IGNORE INTO conexion_proyecto (alias, proyecto_id) VALUES (?,?)",
            vinculos,
        )
    return True


def _a_entero(valor: bool | None) -> int | None:
    return None if valor is None else int(valor)
