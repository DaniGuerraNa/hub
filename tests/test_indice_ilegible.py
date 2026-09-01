"""Qué se ve cuando el índice no se puede leer.

Medido en la auditoría previa al release: una `hub.db` corrupta tumbaba las
siete pantallas a `Internal Server Error` desnudo. La cabecera de `db.py`
prometía que «si esto se corrompe, se reconstruye escaneando», y era cierto
como principio y falso como experiencia — no había nada que lo detectara, nada
que lo dijera, y el remedio (renombrar un archivo) no se deduce de un 500.

Los tres casos que se probaron a mano y que aquí quedan fijados: base corrupta
entera, base MEDIO corrupta —la peor, porque abre sin quejarse y revienta en la
primera consulta— y `HUB_HOME` sin permiso de escritura, que es lo que ocurre
con un disco lleno.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


VISTAS = ["/", "/trabajo", "/inventario", "/respaldo", "/servicios"]


@pytest.fixture
def cliente(tmp_path, monkeypatch):
    """Un hub con su HUB_HOME propio, recargado para que tome la ruta nueva.

    🔴 Y **restaurado al salir**. `importlib.reload` deja el módulo cargado con
    la configuración del test; sin deshacerlo, los tests siguientes heredan un
    `HUB_HOME` que ya no existe y fallan por algo que no tiene que ver con
    ellos. Pasó al añadir estos tests: cuatro rojos en `test_snapshotter` y
    `test_vistas_web` que pasaban corriendo solos. Un falso rojo cuesta lo mismo
    de diagnosticar que un falso verde.
    """
    import importlib

    from hub import config, db, web

    def montar():
        monkeypatch.setenv("HUB_HOME", str(tmp_path))
        importlib.reload(config)
        importlib.reload(db)
        importlib.reload(web)
        return TestClient(web.app, raise_server_exceptions=False), db

    yield montar

    monkeypatch.undo()
    importlib.reload(config)
    importlib.reload(db)
    importlib.reload(web)


def _base_corrupta(tmp_path):
    (tmp_path / "hub.db").write_bytes(b"esto no es una base de datos" * 500)


def _base_medio_corrupta(tmp_path, db):
    """Abre bien y falla al consultar: el caso que más despista."""
    con = db.abrir()
    con.execute(
        "INSERT INTO proyecto (id,nombre,dominio,tipo) VALUES ('p','P','personal','proyecto')"
    )
    con.commit()
    con.close()
    ruta = tmp_path / "hub.db"
    crudo = bytearray(ruta.read_bytes())
    for i in range(4096, min(len(crudo), 20000)):
        crudo[i] = 0xFF
    ruta.write_bytes(bytes(crudo))


@pytest.mark.parametrize("vista", VISTAS)
def test_una_base_corrupta_da_503_con_remedio_y_no_500_desnudo(cliente, tmp_path, vista):
    _base_corrupta(tmp_path)
    c, _ = cliente()
    r = c.get(vista)
    assert r.status_code == 503, f"{vista} debería explicarse, no reventar"
    # Lo que hace útil la pantalla es la orden exacta, no el diagnóstico.
    assert "mv " in r.text and "hub.db" in r.text


def test_dice_que_con_la_base_se_van_las_notas_y_los_slots(cliente, tmp_path):
    """Es lo único del hub que no se reconstruye escaneando.

    Sin esta frase, «renómbralo» se lee como «bórralo» y la avería recuperable
    se convierte en una pérdida.
    """
    _base_corrupta(tmp_path)
    c, _ = cliente()
    texto = c.get("/").text
    assert "notas" in texto and "slots" in texto
    assert "no lo borres" in texto


def test_una_base_medio_corrupta_tambien_se_explica(cliente, tmp_path):
    c, db = cliente()
    _base_medio_corrupta(tmp_path, db)
    assert c.get("/").status_code == 503


def test_sin_permiso_de_escritura_el_diagnostico_es_otro(cliente, tmp_path):
    """Disco lleno o permisos: no es corrupción, y decir «corrupto» despista."""
    (tmp_path / "hub.db").write_bytes(b"")
    tmp_path.chmod(0o500)
    try:
        c, _ = cliente()
        r = c.get("/")
        assert r.status_code == 503
        assert "No se puede escribir" in r.text
    finally:
        tmp_path.chmod(0o700)


def test_el_registro_se_declara_a_salvo(cliente, tmp_path):
    """La base es el índice; `projects.yml` es la fuente de verdad y no se toca.

    Quien ve la pantalla está asustado por sus datos: hay que responder a eso.
    """
    _base_corrupta(tmp_path)
    c, _ = cliente()
    assert "projects.yml" in c.get("/").text
