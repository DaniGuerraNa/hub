"""`hub conexiones`, ejecutado de verdad contra un hub levantado.

Igual que `test_lienzo_cli`: no se importa el script ni se simula la red. Lo
que puede fallar aquí no es la lógica —esa ya está probada en
`test_conexiones.py`— sino que el CLI y la API se hablen, y que el proyecto se
deduzca del directorio DESDE EL QUE SE EJECUTA, que es lo único que convierte
la lista `proyectos:` en un permiso en vez de en una etiqueta (decisión 197).
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

from hub import conexiones, config, db, registry
from hub.models import Conexion, Proyecto

CLI = Path(__file__).resolve().parents[1] / "semillas" / "asistente" / "bin" / "hub"


def _puerto_libre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def hub_vivo(tmp_path):
    """Un hub de verdad con dos proyectos y una conexión concedida a uno solo."""
    casa = tmp_path / "casa"
    (casa / "facturador" / "apps").mkdir(parents=True)
    (casa / "tienda").mkdir(parents=True)
    llaves = tmp_path / ".ssh"
    llaves.mkdir()
    (llaves / "config").write_text("Host vps-facturador\n", encoding="utf-8")

    con = db.conectar(config.DB_PATH)
    db.inicializar(con)
    registry.sincronizar(con, [
        Proyecto(id="facturador", nombre="Facturador",
                 asiento=str(casa / "facturador")),
        Proyecto(id="tienda", nombre="Tienda", asiento=str(casa / "tienda")),
    ])
    conexiones.sincronizar(con, [
        Conexion(alias="VPS - Facturador", host="203.0.113.10", usuario="root",
                 proposito="produccion", proyectos=["facturador"],
                 referencia_secreto=f"{llaves / 'config'}#vps-facturador"),
    ])
    con.commit()
    con.close()

    puerto = _puerto_libre()
    entorno = {**os.environ, "HUB_HOME": str(config.HUB_HOME),
               "HUB_PORT": str(puerto)}
    proceso = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "hub.web:app",
         "--host", "127.0.0.1", "--port", str(puerto), "--log-level", "error"],
        env=entorno, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    for _ in range(100):
        try:
            urllib.request.urlopen(
                f"http://127.0.0.1:{puerto}/api/conexiones", timeout=1)
            break
        except Exception:
            time.sleep(0.1)
    else:
        proceso.terminate()
        pytest.skip("el hub de pruebas no llegó a levantar")

    yield entorno, casa
    proceso.terminate()
    proceso.wait(timeout=10)


def _hub(entorno, desde: Path, *args):
    return subprocess.run(
        [sys.executable, str(CLI), *args], cwd=str(desde),
        env=entorno, capture_output=True, text=True, timeout=30,
    )


def test_desde_el_proyecto_dice_a_donde_entrar_y_donde_esta_la_llave(hub_vivo):
    entorno, casa = hub_vivo

    r = _hub(entorno, casa / "facturador" / "apps", "conexiones")

    assert r.returncode == 0, r.stderr
    assert "facturador" in r.stdout
    assert "VPS - Facturador" in r.stdout
    assert "root@203.0.113.10" in r.stdout
    # Lo que hace útil el puntero: el comando para entrar sale de él solo.
    assert "ssh vps-facturador" in r.stdout
    assert "✓ existe" in r.stdout


def test_desde_otro_proyecto_no_sale_la_conexion_ajena(hub_vivo):
    """🔴 La prueba que justifica todo: estar dentro de un proyecto no da acceso
    a los servidores de otro, aunque los dos sean del mismo usuario."""
    entorno, casa = hub_vivo

    r = _hub(entorno, casa / "tienda", "conexiones")

    assert r.returncode == 0, r.stderr
    assert "203.0.113.10" not in r.stdout
    assert "VPS - Facturador" not in r.stdout
    assert "no tiene ninguna conexión concedida" in r.stdout


def test_desde_fuera_de_todo_proyecto_lo_dice_y_explica_como_arreglarlo(hub_vivo):
    entorno, casa = hub_vivo

    r = _hub(entorno, casa, "conexiones")

    assert r.returncode == 0, r.stderr
    assert "no está dentro de ningún proyecto" in r.stdout
    assert "projects.yml" in r.stdout


def test_el_proyecto_no_se_puede_forzar_con_un_argumento(hub_vivo):
    """El comando ignora lo que se le pase: el proyecto sale del directorio.

    Si algún día acepta un nombre, este test se pone rojo — y debe ponerse,
    porque ese día la concesión deja de conceder.
    """
    entorno, casa = hub_vivo

    r = _hub(entorno, casa / "tienda", "conexiones", "facturador")

    assert "203.0.113.10" not in r.stdout
    assert "VPS - Facturador" not in r.stdout


def test_un_puntero_roto_se_canta_en_vez_de_pasar_desapercibido(hub_vivo):
    """Una llave que ya no está donde dice es exactamente lo que hace perder una
    tarde: el comando falla con «Permission denied» y nadie mira el puntero."""
    entorno, casa = hub_vivo
    con = db.conectar(config.DB_PATH)
    conexiones.sincronizar(con, [
        Conexion(alias="VPS - Facturador", host="203.0.113.10", usuario="root",
                 proyectos=["facturador"],
                 referencia_secreto="/no/existe/config#vps-facturador"),
    ])
    con.commit()
    con.close()

    r = _hub(entorno, casa / "facturador", "conexiones")

    assert "NO existe" in r.stdout
