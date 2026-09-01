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

import sqlite3
from pathlib import Path

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


def sincronizar(con: sqlite3.Connection, conexiones: list[Conexion]) -> None:
    """Refleja las conexiones de `projects.yml` en el índice. El YAML manda."""
    con.execute("DELETE FROM conexion")
    con.execute("DELETE FROM conexion_proyecto")
    for c in conexiones:
        con.execute(
            """INSERT INTO conexion (alias, host, usuario, proposito, referencia_secreto,
                                     puntero_ok, nota)
               VALUES (?,?,?,?,?,?,?)""",
            (c.alias, c.host, c.usuario, c.proposito, c.referencia_secreto,
             _a_entero(puntero_existe(c.referencia_secreto)), c.nota),
        )
        for proyecto_id in c.proyectos:
            con.execute(
                "INSERT OR IGNORE INTO conexion_proyecto (alias, proyecto_id) VALUES (?,?)",
                (c.alias, proyecto_id),
            )


def _a_entero(valor: bool | None) -> int | None:
    return None if valor is None else int(valor)
