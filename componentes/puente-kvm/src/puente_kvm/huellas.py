"""Huellas de un texto en todas las formas en que una base puede guardarlo.

La copia leída de la pantalla es exacta sólo si su huella coincide con la
que da la base. Pero «la huella del texto» no es una sola: depende de la
codificación (SQL Server usa UTF-16 en NVARCHAR), del salto de línea (CRLF o
LF), de si hay salto al final y del algoritmo. En vez de adivinar cuál usa la
base de cada uno, se calculan todas y se mira cuál coincide. Una vez
encontrada, esa variante se usa para comprobar lo que se escriba después.
"""

from __future__ import annotations

import hashlib
import re

ALGORITMOS = ("sha256", "sha1", "md5")
CODIFICACIONES = ("utf-16-le", "utf-8", "cp1252")
FINES = (("CRLF", "\r\n"), ("LF", "\n"))


def normalizar(hexa: str) -> str:
    # En mayúsculas, como las da SQL Server: así se comparan también a ojo.
    h = hexa.strip().upper()
    h = h[2:] if h.startswith("0X") else h
    return re.sub(r"[^0-9A-F]", "", h)


def calcular(lineas: list[str], algoritmo: str, codificacion: str, fin: str, final: bool) -> str | None:
    sep = dict(FINES)[fin]
    texto = sep.join(lineas) + (sep if final else "")
    try:
        datos = texto.encode(codificacion)
    except UnicodeEncodeError:
        return None
    return hashlib.new(algoritmo, datos).hexdigest().upper()


def variantes(lineas: list[str]) -> list[dict]:
    salida = []
    for alg in ALGORITMOS:
        for cod in CODIFICACIONES:
            for fin, _ in FINES:
                for final in (False, True):
                    h = calcular(lineas, alg, cod, fin, final)
                    if h:
                        salida.append({"algoritmo": alg, "codificacion": cod, "fin": fin,
                                       "final": final, "hex": h})
    return salida


def buscar(lineas: list[str], referencia: str) -> dict | None:
    """La variante cuya huella es `referencia`, o None si ninguna."""
    ref = normalizar(referencia)
    if not ref:
        return None
    for v in variantes(lineas):
        if v["hex"] == ref:
            return v
    return None


def con_variante(lineas: list[str], variante: dict) -> str | None:
    return calcular(lineas, variante["algoritmo"], variante["codificacion"], variante["fin"],
                    variante["final"])


def describir(v: dict) -> str:
    return (f"{v['algoritmo'].upper()} sobre {v['codificacion'].upper()}, saltos {v['fin']}"
            f"{', con salto final' if v['final'] else ''}")


# Consultas de sólo lectura para sacar la huella de un procedimiento en cada
# motor. Lo que devuelven puede no ser lo mismo que enseña el editor (algunos
# clientes añaden `CREATE OR ALTER` al abrir): por eso se prueban variantes y,
# si ninguna casa, hay que comparar a ojo la primera y la última línea.
CONSULTAS = {
    "SQL Server": (
        "SELECT CONVERT(varchar(64), HASHBYTES('SHA2_256', OBJECT_DEFINITION(OBJECT_ID('{objeto}'))), 2) AS huella,\n"
        "       LEN(OBJECT_DEFINITION(OBJECT_ID('{objeto}'))) AS caracteres;"
    ),
    "PostgreSQL": "SELECT md5(pg_get_functiondef('{objeto}'::regproc)) AS huella;",
    "MySQL": (
        "SELECT SHA2(ROUTINE_DEFINITION, 256) AS huella\n"
        "FROM information_schema.ROUTINES\n"
        "WHERE CONCAT(ROUTINE_SCHEMA, '.', ROUTINE_NAME) = '{objeto}';"
    ),
}
