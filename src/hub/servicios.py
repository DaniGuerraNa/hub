"""Contenedores Docker, atribuidos a proyectos.

Entra al modelo porque lo pedían los documentos de un proyecto real, que avisaban
a quien fuera a tocar su Docker:

    En este Docker conviven contenedores de OTROS proyectos. Un
    `docker stop $(docker ps -q)` se los lleva por delante.

Ese es exactamente el daño que esta vista evita: saber de quién es cada
contenedor antes de parar nada. La atribución inicial es por prefijo de nombre
y se corrige a mano en `projects.yml`.

El hub arranca y para contenedores concretos, **nunca en lote**: un "parar todo"
reproduce el accidente que este módulo existe para prevenir.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
import subprocess
from datetime import datetime, timezone

from .models import Proyecto

TIEMPO_LIMITE = 20

# Formato JSON por línea: `docker ps` con `--format` deja el parseo sin ambigüedad.
_FORMATO = (
    '{"nombre":"{{.Names}}","imagen":"{{.Image}}","estado":"{{.State}}",'
    '"detalle":"{{.Status}}","creado":"{{.CreatedAt}}"}'
)


def disponible() -> bool:
    return shutil.which("docker") is not None


class NoRespondio(RuntimeError):
    """Docker está instalado pero no contestó (daemon parado, permisos, cuelgue).

    Es distinto de «no hay contenedores», y confundirlos es caro: la UI diría
    que tienes cero cuando en realidad no pudimos preguntar. Mismo principio
    que la regla dura 4 — no se pisa la última muestra buena con una vacía.
    """


def listar() -> list[dict]:
    """Todos los contenedores, vivos y parados.

    Los parados importan tanto como los vivos: en el inventario que originó esto
    había un contenedor detenido desde hacía cuatro meses, sin dueño conocido y
    sin que nadie supiera si podía borrarse. Ésa es la clase de cosa que se
    olvida, y un listado que sólo enseña lo que corre no la enseña nunca.
    """
    if not disponible():
        raise NoRespondio("docker no está instalado en este entorno")
    try:
        salida = subprocess.run(
            ["docker", "ps", "-a", "--no-trunc", "--format", _FORMATO],
            capture_output=True, text=True, timeout=TIEMPO_LIMITE,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise NoRespondio(str(exc)) from exc
    if salida.returncode != 0:
        raise NoRespondio(salida.stderr.strip() or "docker devolvió un error")

    contenedores = []
    for linea in salida.stdout.splitlines():
        linea = linea.strip()
        if not linea:
            continue
        try:
            contenedores.append(json.loads(linea))
        except ValueError:
            continue  # una línea rota no invalida el resto del inventario
    return contenedores


def atribuir(nombre: str, proyectos: list[Proyecto]) -> str | None:
    """Asigna un contenedor a un proyecto por el prefijo declarado más largo.

    El prefijo más largo gana, igual que con las rutas: si un proyecto declara
    `app` y otro `app-front`, el segundo se queda lo suyo.
    """
    candidatos = [
        (prefijo, p.id)
        for p in proyectos
        for prefijo in p.contenedores
        if nombre == prefijo or nombre.startswith(prefijo)
    ]
    if not candidatos:
        return None
    return max(candidatos, key=lambda par: len(par[0]))[1]


def escanear(con: sqlite3.Connection, proyectos: list[Proyecto]) -> int:
    """Repuebla la tabla `servicio`.

    `ultima_vez_visto` se conserva de la fila anterior cuando el contenedor ya
    se conocía: es un dato acumulado, no una lectura, y perderlo en cada escaneo
    borraría la única señal de "esto lleva meses sin aparecer".

    Si docker no responde **no se toca nada**: dejar la tabla vacía haría que la
    UI dijera que tienes cero contenedores cuando lo cierto es que no pudimos
    preguntar. Se propaga `NoRespondio` para que quien llame lo diga.
    """
    ahora = datetime.now(timezone.utc).isoformat()
    previos = {
        f["contenedor"]: f["ultima_vez_visto"]
        for f in con.execute("SELECT contenedor, ultima_vez_visto FROM servicio")
    }

    contenedores = listar()  # si lanza, la tabla anterior queda intacta
    con.execute("DELETE FROM servicio")
    for c in contenedores:
        nombre = c.get("nombre", "")
        if not nombre:
            continue
        vivo = c.get("estado") == "running"
        con.execute(
            """INSERT INTO servicio (contenedor, proyecto_id, imagen, estado, detalle,
                                     creado, ultima_vez_visto, medido_en)
               VALUES (?,?,?,?,?,?,?,?)""",
            (
                nombre,
                atribuir(nombre, proyectos),
                c.get("imagen", ""),
                c.get("estado", ""),
                c.get("detalle", ""),
                c.get("creado", ""),
                # Sólo cuenta como "visto" cuando está corriendo: un contenedor
                # parado sigue listado, pero no se está usando.
                ahora if vivo else previos.get(nombre),
                ahora,
            ),
        )
    return len(contenedores)


class AccionInvalida(RuntimeError):
    pass


def accionar(contenedor: str, accion: str) -> None:
    """Arranca o para UN contenedor por nombre exacto.

    Nunca en lote y nunca por patrón: el accidente que este módulo previene es
    precisamente `docker stop $(docker ps -q)`.
    """
    if accion not in ("start", "stop", "restart"):
        raise AccionInvalida(f"acción no permitida: {accion}")
    if not contenedor or any(c.isspace() for c in contenedor):
        raise AccionInvalida("nombre de contenedor inválido")
    if not disponible():
        raise AccionInvalida("docker no está disponible")
    try:
        salida = subprocess.run(
            ["docker", accion, contenedor],
            capture_output=True, text=True, timeout=TIEMPO_LIMITE,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise AccionInvalida(str(exc)) from exc
    if salida.returncode != 0:
        raise AccionInvalida(salida.stderr.strip() or f"docker {accion} falló")
