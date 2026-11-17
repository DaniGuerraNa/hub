"""Lo que reescribe el ciclo lento no se ve a medias desde otra conexión (C-0429).

El ciclo lento corre en su propio hilo y con su conexión (C-0309), y la web
lee la misma base desde otro proceso. `db.conectar` abre en autocommit, así
que un `DELETE` seguido de los `INSERT` era una ventana en la que quien
leyera veía la tabla vacía —«cero contenedores», «sin consumo», una búsqueda
sin nada— o mezclada, con unas filas de esta vuelta y otras de la anterior.

Se mide con dos conexiones de verdad sobre el mismo archivo: cada vez que la
que escribe va a empezar un `INSERT`, la otra lee la tabla. En WAL, dentro
de una transacción la otra ve lo de antes, entero; sin ella, ve el hueco.
"""

from __future__ import annotations

import json
import shutil
import subprocess

import pytest

from hub import busqueda, consumo, db, repos, servicios
from hub.models import Proyecto, Ruta


@pytest.fixture
def ruta(tmp_path):
    return tmp_path / "hub.db"


@pytest.fixture
def escritor(ruta):
    con = db.conectar(ruta)
    db.inicializar(con)
    yield con
    con.set_trace_callback(None)
    con.close()


@pytest.fixture
def lector(ruta, escritor):
    con = db.conectar(ruta)
    yield con
    con.close()


def _mirar_mientras_escribe(escritor, lector, consulta: str) -> list:
    """Lo que ve `lector` justo antes de cada `INSERT` de `escritor`."""
    vistas: list = []

    def al_empezar(sql: str) -> None:
        if sql.lstrip().upper().startswith("INSERT") and len(vistas) < 50:
            vistas.append([tuple(f) for f in lector.execute(consulta)])

    escritor.set_trace_callback(al_empezar)
    return vistas


def test_servicios_no_se_ve_vacio_mientras_se_reescribe(escritor, lector, monkeypatch):
    contenedores = [{"nombre": f"web-{n}", "imagen": "nginx", "estado": "running",
                     "detalle": "Up", "creado": ""} for n in range(3)]
    monkeypatch.setattr(servicios, "listar", lambda: contenedores)
    servicios.escanear(escritor, [])
    antes = [tuple(f) for f in lector.execute("SELECT contenedor FROM servicio ORDER BY contenedor")]

    vistas = _mirar_mientras_escribe(escritor, lector, "SELECT contenedor FROM servicio ORDER BY contenedor")
    servicios.escanear(escritor, [])
    assert vistas, "no hubo ningún INSERT que mirar"
    assert all(v == antes for v in vistas), "otra conexión vio la tabla de servicios a medias"


def test_el_indice_no_se_ve_vacio_mientras_se_reindexa(escritor, lector):
    if not db.hay_fts(escritor):
        pytest.skip("SQLite sin FTS5")
    for n in range(3):
        escritor.execute("INSERT INTO proyecto (id, nombre, asiento) VALUES (?, ?, ?)",
                         (f"p{n}", f"Proyecto {n}", f"/tmp/p{n}"))
    busqueda.reindexar(escritor)
    antes = lector.execute("SELECT COUNT(*) FROM indice").fetchone()[0]
    assert antes == 3

    vistas = _mirar_mientras_escribe(escritor, lector, "SELECT COUNT(*) FROM indice")
    busqueda.reindexar(escritor)
    assert vistas
    assert all(v == [(antes,)] for v in vistas), "una búsqueda a mitad de reindexar no encontraba nada"


def _linea(request_id, salida):
    return json.dumps({
        "type": "assistant", "cwd": "/tmp/demo", "requestId": request_id,
        "timestamp": "2026-08-20T10:00:00.000Z", "uuid": f"{request_id}-{salida}",
        "message": {"model": "claude-opus-5", "usage": {
            "input_tokens": 2, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0,
            "output_tokens": salida, "output_tokens_details": {"thinking_tokens": 0}}},
    })


def test_el_consumo_no_se_ve_vacio_mientras_se_reescribe(escritor, lector, tmp_path, monkeypatch):
    raiz = tmp_path / "transcripts"
    (raiz / "-tmp-demo").mkdir(parents=True)
    (raiz / "-tmp-demo" / "s1.jsonl").write_text(
        "\n".join(_linea(f"req_{n}", 10 + n) for n in range(3)) + "\n", encoding="utf-8")
    monkeypatch.setenv("HUB_TRANSCRIPTS", str(raiz))
    proyectos = [Proyecto(id="demo", nombre="Demo", asiento="/tmp/demo",
                          rutas=[Ruta(ruta="/tmp/demo", tipo="asiento")])]
    consumo.escanear(escritor, proyectos)
    antes = [tuple(f) for f in lector.execute("SELECT peticiones, salida FROM consumo")]
    assert antes

    vistas = _mirar_mientras_escribe(escritor, lector, "SELECT peticiones, salida FROM consumo")
    consumo.escanear(escritor, proyectos)
    assert vistas
    assert all(v == antes for v in vistas), "/consumo a mitad del ciclo lento decía que no había nada"


def _repo(ruta):
    ruta.mkdir()
    for args in (("init", "-q", "-b", "main"), ("config", "user.email", "t@t"), ("config", "user.name", "t")):
        subprocess.run(["git", "-C", str(ruta), *args], check=True, capture_output=True)
    (ruta / "a.txt").write_text("a", encoding="utf-8")
    subprocess.run(["git", "-C", str(ruta), "add", "-A"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(ruta), "commit", "-qm", "a"], check=True, capture_output=True)
    return ruta


def test_el_respaldo_no_mezcla_filas_de_dos_vueltas_mientras_se_reescribe(escritor, lector, tmp_path):
    """Cada vuelta sella sus filas con la misma hora, y `/respaldo` marca como
    «de otra vuelta» las que no la llevan (C-0295). Leída a mitad, la tabla
    tenía filas de las dos y la pantalla daba por viejas las que no lo eran."""
    if not shutil.which("git"):
        pytest.skip("git no disponible")
    proyectos = [Proyecto(id=f"p{n}", nombre=f"P{n}", asiento=str(_repo(tmp_path / f"repo{n}")))
                 for n in range(3)]
    repos.escanear(escritor, proyectos)
    consulta = "SELECT COUNT(*), COUNT(DISTINCT medido_en) FROM repo"
    assert lector.execute(consulta).fetchone()[:] == (3, 1)

    vistas = _mirar_mientras_escribe(escritor, lector, consulta)
    repos.escanear(escritor, proyectos)
    assert vistas
    assert all(v == [(3, 1)] for v in vistas), "otra conexión vio repos de dos vueltas a la vez"
