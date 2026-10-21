"""La copia diaria de `hub.db` (decisión 277)."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta

from fastapi.testclient import TestClient

from hub import copia_base, db, snapshotter, web


def _base_con_una_nota(ruta):
    con = db.conectar(ruta)
    db.inicializar(con)
    con.execute("CREATE TABLE IF NOT EXISTS prueba (texto TEXT)")
    con.execute("INSERT INTO prueba VALUES ('lo que sólo vive aquí')")
    con.commit()
    return con


def test_la_copia_lleva_lo_ultimo_escrito_aunque_siga_en_el_wal(tmp_path, monkeypatch):
    monkeypatch.setenv("HUB_RESPALDO", str(tmp_path / "copias"))
    con = _base_con_una_nota(tmp_path / "hub.db")
    destino = copia_base.hacer(con, ahora=datetime(2026, 10, 20, 12))
    assert destino.name == "hub-20261020.db"
    leida = sqlite3.connect(destino).execute("SELECT texto FROM prueba").fetchone()
    assert leida == ("lo que sólo vive aquí",)
    assert not list((tmp_path / "copias").glob("*.tmp"))


def test_una_copia_por_dia_aunque_el_ciclo_lento_pase_muchas_veces(tmp_path, monkeypatch):
    monkeypatch.setenv("HUB_RESPALDO", str(tmp_path / "copias"))
    con = _base_con_una_nota(tmp_path / "hub.db")
    dia = datetime(2026, 10, 20, 9)
    assert copia_base.hacer(con, ahora=dia) is not None
    assert copia_base.hacer(con, ahora=dia + timedelta(hours=5)) is None
    assert len(list((tmp_path / "copias").glob("hub-*.db"))) == 1


def test_se_guardan_las_catorce_ultimas_y_se_borran_las_mas_viejas(tmp_path, monkeypatch):
    monkeypatch.setenv("HUB_RESPALDO", str(tmp_path / "copias"))
    con = _base_con_una_nota(tmp_path / "hub.db")
    inicio = datetime(2026, 10, 1)
    for n in range(20):
        copia_base.hacer(con, ahora=inicio + timedelta(days=n))
    nombres = sorted(p.name for p in (tmp_path / "copias").glob("hub-*.db"))
    assert len(nombres) == 14
    assert nombres[0] == "hub-20261007.db" and nombres[-1] == "hub-20261020.db"


def test_sin_variable_las_copias_van_a_respaldos_dentro_de_hub_home(tmp_path, monkeypatch):
    monkeypatch.delenv("HUB_RESPALDO", raising=False)
    from hub import config
    assert copia_base.carpeta() == config.HUB_HOME / "respaldos"


def test_sin_copias_el_estado_dice_que_no_hay_ninguna_y_avisa(tmp_path, monkeypatch):
    monkeypatch.setenv("HUB_RESPALDO", str(tmp_path / "vacia"))
    e = copia_base.estado()
    assert e["copias"] == 0 and e["ultima"] is None and e["vieja"] is True


def test_una_copia_de_hace_tres_dias_se_marca_como_vieja(tmp_path, monkeypatch):
    monkeypatch.setenv("HUB_RESPALDO", str(tmp_path / "copias"))
    con = _base_con_una_nota(tmp_path / "hub.db")
    copia_base.hacer(con)
    assert copia_base.estado()["vieja"] is False
    assert copia_base.estado(ahora=datetime.now() + timedelta(days=3))["vieja"] is True


def test_el_ciclo_lento_hace_la_copia_y_un_fallo_no_tumba_lo_demas(tmp_path, monkeypatch):
    monkeypatch.setenv("HUB_RESPALDO", str(tmp_path / "copias"))
    con = _base_con_una_nota(tmp_path / "hub.db")
    resultado = snapshotter.ciclo_lento(con)
    assert resultado["copia_base"] is not None
    assert len(list((tmp_path / "copias").glob("hub-*.db"))) == 1

    def revienta(_con):
        raise OSError("disco lleno")
    monkeypatch.setattr(copia_base, "hacer", revienta)
    otra = snapshotter.ciclo_lento(con)  # no lanza
    assert "repos" in otra


def test_la_pantalla_de_respaldo_dice_donde_esta_la_copia(tmp_path, monkeypatch):
    monkeypatch.setenv("HUB_RESPALDO", str(tmp_path / "copias-del-hub"))
    r = TestClient(web.app).get("/respaldo")
    assert r.status_code == 200
    assert "Los datos del hub" in r.text
    assert "Todavía no hay ninguna copia de la base" in r.text
    assert str(tmp_path / "copias-del-hub") in r.text
