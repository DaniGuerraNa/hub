"""Cómo se llama el secretario (C-0226, idea 10 del tablero).

«Secretario» es lo que es, no un nombre para llamarlo a cada rato: cada quien
le pone el suyo en Ajustes → Personaje, como le cambia el aspecto, y vale en
todas las pantallas, en la app instalada y en lo que él sabe de sí mismo.
"""
from __future__ import annotations

import pytest

from hub import api
from hub.secretario import conversacion, memoria, personaje

CASA = {"origin": "http://127.0.0.1:8787"}


@pytest.fixture
def cliente(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from hub import db, web

    def conexion():
        c = db.conectar(tmp_path / "hub.db")
        db.inicializar(c)
        return c

    monkeypatch.setattr(web, "conexion", conexion)
    memoria.conectar().close()
    return TestClient(web.app)


@pytest.mark.parametrize("valor", ["Leskin", "Sr. Pérez", "R2-D2", "Ana María", "O’Neil"])
def test_un_nombre_de_verdad_se_guarda_tal_cual(valor):
    assert personaje.nombrar(memoria.conectar(), valor) == valor
    assert api.nombre_secretario(memoria.conectar()) == valor


@pytest.mark.parametrize("valor", ["<script>", "a" * 25, "_x", "{{ 7*7 }}", "Leskin\x00"])
def test_lo_que_no_es_un_nombre_no_se_guarda(valor):
    con = memoria.conectar()
    personaje.nombrar(con, "Leskin")
    with pytest.raises(ValueError):
        personaje.nombrar(con, valor)
    assert api.nombre_secretario(con) == "Leskin"


def test_los_saltos_y_espacios_de_mas_se_juntan_en_uno():
    assert personaje.nombrar(memoria.conectar(), "  Hola\n  mundo ") == "Hola mundo"


def test_vacio_vuelve_a_secretario():
    con = memoria.conectar()
    personaje.nombrar(con, "Leskin")
    assert personaje.nombrar(con, "   ") == "Secretario"
    assert api.nombre_secretario(con) == "Secretario"


def test_sin_memoria_todavia_se_llama_secretario_y_no_la_crea():
    """Una instalación sin secretario no tiene memoria: el raíl no puede crearla (C-0099)."""
    assert not memoria.ruta().exists()
    assert api.nombre_secretario() == "Secretario"
    assert not memoria.ruta().exists()


def test_el_nombre_lo_llevan_el_menu_su_pantalla_y_la_app_instalada(cliente):
    r = cliente.post("/secretario/nombre", data={"nombre": "Leskin"}, headers=CASA, follow_redirects=False)
    assert r.status_code == 303 and "Leskin" in r.headers["location"]

    portada = cliente.get("/").text
    entrada = portada[portada.index('href="/secretario"'):]
    assert "Leskin" in entrada[:entrada.index("</a>")]
    pantalla = cliente.get("/secretario").text
    assert "<title>Leskin" in pantalla and "<h1>Leskin" in pantalla
    ajustes = cliente.get("/secretario?p=personaje").text
    assert 'value="Leskin"' in ajustes
    assert cliente.get("/secretario/manifest.webmanifest").json()["short_name"] == "Leskin"
    assert "<h1>Leskin" in cliente.get("/secretario/monitor").text


def test_un_nombre_raro_no_se_guarda_y_se_dice(cliente):
    r = cliente.post("/secretario/nombre", data={"nombre": "<img src=x>"}, headers=CASA, follow_redirects=False)
    assert r.status_code == 303 and "aviso=" in r.headers["location"]
    assert "<img src=x>" not in cliente.get("/").text


def test_cambiarlo_desde_otro_sitio_no_cambia_nada(cliente):
    r = cliente.post("/secretario/nombre", data={"nombre": "Leskin"},
                     headers={"origin": "https://sitio-malicioso.example"}, follow_redirects=False)
    assert r.status_code == 403
    assert api.nombre_secretario(memoria.conectar()) == "Secretario"


def test_el_modelo_sabe_como_se_llama_y_sin_nombre_no_se_le_dice_nada():
    memoria.conectar().close()
    assert "Te llamas" not in conversacion.sistema()
    personaje.nombrar(memoria.conectar(), "Leskin")
    assert conversacion.sistema().startswith("Te llamas Leskin")
    assert "no firmes cada mensaje" in conversacion.sistema()
