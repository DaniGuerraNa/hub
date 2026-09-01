"""Contenedores Docker atribuidos a proyectos.

El daño concreto que esto evita salió de un caso real: en un mismo Docker
conviven contenedores de cinco proyectos y un `docker stop $(docker ps -q)` se
los lleva por delante. Una atribución equivocada haría parar lo ajeno creyendo
que es propio.
"""

from __future__ import annotations

import pytest

from hub import servicios
from hub.models import Proyecto

PROYECTOS = [
    Proyecto(id="facturador", nombre="Facturador", contenedores=["facturador-"]),
    Proyecto(id="analitica", nombre="Analítica", contenedores=["sql-lab"]),
    Proyecto(id="trabajo", nombre="Trabajo", contenedores=["oracle-", "localstack-"]),
]


def test_atribuye_por_prefijo_declarado():
    assert servicios.atribuir("facturador-dev-postgres", PROYECTOS) == "facturador"
    assert servicios.atribuir("oracle-interno", PROYECTOS) == "trabajo"


def test_un_nombre_exacto_tambien_atribuye():
    assert servicios.atribuir("sql-lab", PROYECTOS) == "analitica"


def test_gana_el_prefijo_mas_largo():
    """Si dos proyectos declaran prefijos que solapan, el más específico manda."""
    proyectos = [
        Proyecto(id="general", nombre="General", contenedores=["app-"]),
        Proyecto(id="front", nombre="Front", contenedores=["app-front-"]),
    ]
    assert servicios.atribuir("app-front-web", proyectos) == "front"
    assert servicios.atribuir("app-api", proyectos) == "general"


def test_lo_no_declarado_queda_sin_dueno():
    """El caso real: un contenedor parado hace meses y sin atribuir.

    Inventarle un dueño sería peor que dejarlo huérfano: haría que alguien lo
    parase o lo borrase creyendo saber de qué es.
    """
    assert servicios.atribuir("viejo_postgis_db", PROYECTOS) is None


def test_sin_docker_se_distingue_de_no_tener_contenedores(monkeypatch):
    """Confundirlos haría que la UI dijera «tienes cero» cuando lo cierto es
    que no se pudo preguntar. Mismo principio que la regla dura 4."""
    monkeypatch.setattr(servicios.shutil, "which", lambda x: None)
    with pytest.raises(servicios.NoRespondio):
        servicios.listar()


def test_el_daemon_parado_tambien_es_no_respondio(monkeypatch):
    class Salida:
        returncode = 1
        stdout = ""
        stderr = "Cannot connect to the Docker daemon"

    monkeypatch.setattr(servicios.shutil, "which", lambda x: "/usr/bin/docker")
    monkeypatch.setattr(servicios.subprocess, "run", lambda *a, **k: Salida())
    with pytest.raises(servicios.NoRespondio, match="daemon"):
        servicios.listar()


def test_si_docker_no_responde_no_se_borra_la_ultima_lectura_buena(con, monkeypatch):
    """Un cero se lee como «no tienes contenedores»; el dato viejo y fechado no."""
    _falsear(monkeypatch, [{"nombre": "db", "imagen": "x", "estado": "running",
                            "detalle": "Up", "creado": ""}])
    servicios.escanear(con, PROYECTOS)

    def mudo():
        raise servicios.NoRespondio("daemon parado")

    monkeypatch.setattr(servicios, "listar", mudo)
    with pytest.raises(servicios.NoRespondio):
        servicios.escanear(con, PROYECTOS)
    assert con.execute("SELECT COUNT(*) FROM servicio").fetchone()[0] == 1


def test_una_linea_corrupta_no_invalida_el_resto(monkeypatch):
    class Salida:
        returncode = 0
        stdout = '{"nombre":"uno","estado":"running"}\n{roto\n{"nombre":"dos","estado":"exited"}\n'

    monkeypatch.setattr(servicios.shutil, "which", lambda x: "/usr/bin/docker")
    monkeypatch.setattr(servicios.subprocess, "run", lambda *a, **k: Salida())
    assert [c["nombre"] for c in servicios.listar()] == ["uno", "dos"]


def _falsear(monkeypatch, contenedores):
    monkeypatch.setattr(servicios, "listar", lambda: contenedores)


def test_escanear_atribuye_y_persiste(con, monkeypatch):
    _falsear(monkeypatch, [
        {"nombre": "facturador-dev-redis", "imagen": "redis", "estado": "running",
         "detalle": "Up 2 hours", "creado": ""},
        {"nombre": "viejo_postgis_db", "imagen": "postgis", "estado": "exited",
         "detalle": "Exited (0) 4 months ago", "creado": ""},
    ])
    assert servicios.escanear(con, PROYECTOS) == 2

    filas = {f["contenedor"]: f for f in con.execute("SELECT * FROM servicio")}
    assert filas["facturador-dev-redis"]["proyecto_id"] == "facturador"
    assert filas["viejo_postgis_db"]["proyecto_id"] is None


def test_solo_se_marca_visto_lo_que_esta_corriendo(con, monkeypatch):
    _falsear(monkeypatch, [{"nombre": "parado", "imagen": "x", "estado": "exited",
                            "detalle": "", "creado": ""}])
    servicios.escanear(con, PROYECTOS)
    assert con.execute("SELECT ultima_vez_visto FROM servicio").fetchone()[0] is None


def test_un_reescaneo_conserva_cuando_se_vio_vivo_por_ultima_vez(con, monkeypatch):
    """Perderlo borraría la única señal de «esto lleva meses sin usarse»."""
    _falsear(monkeypatch, [{"nombre": "db", "imagen": "x", "estado": "running",
                            "detalle": "Up", "creado": ""}])
    servicios.escanear(con, PROYECTOS)
    visto = con.execute("SELECT ultima_vez_visto FROM servicio").fetchone()[0]
    assert visto

    _falsear(monkeypatch, [{"nombre": "db", "imagen": "x", "estado": "exited",
                            "detalle": "Exited", "creado": ""}])
    servicios.escanear(con, PROYECTOS)
    assert con.execute("SELECT ultima_vez_visto FROM servicio").fetchone()[0] == visto


@pytest.mark.parametrize("accion", ["rm", "kill $(docker ps -q)", "", "prune"])
def test_solo_se_permiten_arrancar_parar_y_reiniciar(accion):
    """Nada de borrar ni de operar en lote desde la UI: el radio de daño es real."""
    with pytest.raises(servicios.AccionInvalida):
        servicios.accionar("algo", accion)


@pytest.mark.parametrize("nombre", ["", "uno dos", "$(docker ps -q)", "a\tb"])
def test_un_nombre_de_contenedor_con_espacios_se_rechaza(nombre):
    with pytest.raises(servicios.AccionInvalida):
        servicios.accionar(nombre, "stop")
