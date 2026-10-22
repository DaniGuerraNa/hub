"""La salud del hub: lo que tiene que estar en pie para que un apagón tenga
vuelta (decisión 289). Un usuario apagó, encendió al día siguiente y no le
volvió nada; ninguna pantalla lo había advertido antes."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from hub import config, salud, web

from test_vistas_web import cliente  # noqa: F401  — el cliente con base de pruebas


AHORA = datetime(2026, 10, 22, 12, 0, tzinfo=timezone.utc)


def _latido(hace_segundos, desde=AHORA):
    (config.HUB_HOME / salud.ARCHIVO_LATIDO).write_text(json.dumps(
        {"en": (desde - timedelta(seconds=hace_segundos)).isoformat(), "pid": 1}))


@pytest.mark.parametrize("hace, estado", [(15, "ok"), (150, "aviso"), (3600, "mal")])
def test_el_muestreo_se_juzga_por_su_latido(hace, estado):
    _latido(hace)
    assert salud.muestreo(AHORA)["estado"] == estado


def test_sin_latido_nunca_el_muestreo_esta_mal_y_dice_que_no_habra_restauracion():
    m = salud.muestreo(AHORA)
    assert m["estado"] == "mal" and "restaurar" in m["detalle"]
    assert "systemctl --user restart hub-snapshotter" in m["arreglo"]


def test_latir_deja_un_latido_de_ahora():
    salud.latir()
    assert salud.muestreo()["estado"] == "ok"


def test_avisa_si_ningun_slot_vuelve_tras_un_apagon(con):
    con.execute("INSERT INTO proyecto (id, nombre) VALUES ('p','P')")
    con.execute("INSERT INTO slot (proyecto_id, nombre, creado_en) VALUES ('p','a','x'), ('p','b','x')")
    r = salud._restauracion(con)
    assert r["estado"] == "aviso" and "Ninguno de tus 2 slots" in r["detalle"]

    con.execute("UPDATE slot SET restaurar=1 WHERE nombre='a'")
    assert salud._restauracion(con)["detalle"].startswith("1 de 2 slots")


def test_con_el_muestreo_parado_todas_las_pantallas_lo_dicen(cliente):  # noqa: F811
    _latido(3600, datetime.now(timezone.utc))
    assert "no late desde hace 60 min" in cliente.get("/guia").text
    _latido(5, datetime.now(timezone.utc))
    assert "no late desde hace" not in cliente.get("/guia").text


def test_la_salud_sale_en_maquina_con_su_arreglo(cliente):  # noqa: F811
    html = cliente.get("/maquina").text
    assert 'id="salud"' in html and "Muestreo" in html and "Arreglo:" in html
    assert cliente.get("/api/salud").json()["revisiones"][0]["estado"] == "mal"
