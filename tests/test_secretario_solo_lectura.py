"""`hub-web` mira la memoria del secretario sin crearla ni migrarla (C-0099, C-0061).

`memoria.db` es de `hub-secretario` (decisión 299) y es fuente de verdad
(regla dura 1): la crea y la pone al día quien escribe —el servicio y las rutas
POST, por `memoria.conectar`—. Una pantalla que sólo mira la abre con
`memoria.abrir_lectura`, en sólo lectura. Antes, pintar el raíl de cualquier
pantalla, `/secretario` o el sondeo de los turnos ejecutaba el esquema y sus
`ALTER`: un GET podía crear la base o añadirle columnas antes que el servicio.
"""

from __future__ import annotations

import sqlite3

import pytest
from fastapi.testclient import TestClient

from hub import config, web
from hub.secretario import memoria
from hub.secretario.avisos import webpush

#: Lo que se pinta o se sondea sin escribir nada.
MIRAR = ["/", "/secretario", "/api/secretario/turnos", "/secretario?p=pendientes", "/secretario?p=avisos",
         "/secretario?p=fuentes", "/secretario?p=memoria", "/secretario/monitor"]


@pytest.fixture
def cliente(tmp_path, monkeypatch):
    from hub import db

    def conexion():
        c = db.conectar(tmp_path / "hub.db")
        db.inicializar(c)
        return c

    monkeypatch.setattr(web, "conexion", conexion)
    return TestClient(web.app)


def _carpeta():
    return config.HUB_HOME / "secretario"


def _esquema(ruta) -> list[tuple]:
    """Tablas y columnas tal cual están en el archivo, sin abrirlo con `conectar`."""
    c = sqlite3.connect(f"file:{ruta}?mode=ro", uri=True)
    try:
        return sorted(c.execute("SELECT m.name, p.name FROM sqlite_master AS m, pragma_table_info(m.name) AS p"
                                " WHERE m.type = 'table'"))
    finally:
        c.close()


def _base_vieja() -> object:
    """Una memoria de una versión anterior: sin la columna ni la tabla que
    llegaron las últimas (`turno.responde_a`, C-0243; `asunto`, 380)."""
    con = memoria.conectar()
    con.execute("INSERT INTO estado (clave, valor) VALUES ('latido', ?)", (f'"{memoria.ahora()}"',))
    con.close()
    c = sqlite3.connect(memoria.ruta())
    c.execute("ALTER TABLE turno DROP COLUMN responde_a")
    c.execute("DROP TABLE asunto")
    c.close()
    return memoria.ruta()


@pytest.mark.parametrize("ruta", MIRAR)
def test_mirar_sin_secretario_no_crea_su_carpeta(cliente, ruta):
    r = cliente.get(ruta)
    assert r.status_code == 200
    assert not _carpeta().exists(), f"{ruta} dejó la carpeta del secretario"


#: Lo que contesta el sondeo de los turnos cuando no hay memoria que leer: la
#: misma forma que con ella (C-0421 trajo `permisos`; C-0422, `ingles`).
SONDEO_VACIO = {"hilo": None, "turnos": [], "espera": None, "vivo": False, "permisos": [], "ingles": False}


def test_sin_secretario_el_sondeo_de_los_turnos_sale_vacio_y_parado(cliente):
    assert cliente.get("/api/secretario/turnos").json() == SONDEO_VACIO


def test_el_sondeo_de_los_turnos_trae_lo_mismo_con_base_y_sin_ella(cliente):
    sin = cliente.get("/api/secretario/turnos").json()
    memoria.conectar().close()
    con = cliente.get("/api/secretario/turnos").json()
    assert set(sin) == set(con)


def test_sin_secretario_su_pantalla_dice_que_no_esta_en_marcha(cliente):
    assert "No está en marcha" in cliente.get("/secretario").text
    assert not _carpeta().exists()


@pytest.mark.parametrize("ruta", MIRAR)
def test_con_una_base_de_una_version_anterior_mirar_no_la_migra(cliente, ruta):
    base = _base_vieja()
    antes = _esquema(base)
    r = cliente.get(ruta)
    assert r.status_code == 200
    assert _esquema(base) == antes, f"{ruta} le cambió el esquema a la memoria"


def test_quien_escribe_si_la_pone_al_dia():
    """La otra mitad: la migración no se pierde, la hace quien abre para escribir."""
    base = _base_vieja()
    memoria.conectar().close()
    assert ("turno", "responde_a") in _esquema(base) and ("asunto", "clave") in _esquema(base)


def test_abrir_lectura_sin_base_no_crea_nada():
    assert memoria.abrir_lectura() is None
    assert not _carpeta().exists()


def test_abrir_lectura_lee_y_no_deja_escribir():
    con = memoria.conectar()
    memoria.poner(con, "latido", "ahora")
    con.close()
    lectura = memoria.abrir_lectura()
    try:
        assert memoria.leer(lectura, "latido") == "ahora"
        with pytest.raises(sqlite3.OperationalError):
            memoria.poner(lectura, "latido", "otra vez")
    finally:
        lectura.close()


def test_abrir_lectura_trata_una_base_de_una_version_anterior_como_si_no_estuviera():
    """Leída a medias, la consulta nueva fallaría en una pantalla cualquiera;
    se lee vacía hasta que la ponga al día quien escribe."""
    _base_vieja()
    assert memoria.abrir_lectura() is None


def test_la_ruta_de_la_memoria_no_crea_la_carpeta_y_conectar_si():
    assert memoria.ruta() == _carpeta() / "memoria.db"
    assert not memoria.existe() and not _carpeta().exists()
    memoria.conectar().close()
    assert memoria.existe()


def test_el_canal_del_telefono_sin_memoria_dice_que_no_hay_aparatos_sin_crearla():
    """C-0061: `hub-web` pinta por dónde saldría un aviso con `disponible()`,
    que abría la memoria con `conectar`."""
    llave = webpush.carpeta() / "vapid.key"
    llave.parent.mkdir(parents=True)
    llave.write_text("x", encoding="utf-8")
    assert webpush.PROVEEDOR.disponible() == "ningún aparato tiene los avisos activados"
    assert not _carpeta().exists()


# ── una memoria que no se deja leer ─────────────────────────────────────────


def _ilegible():
    """Lo que no es una base SQLite: `abrir_lectura` lanza `sqlite3.DatabaseError`."""
    _carpeta().mkdir(parents=True)
    memoria.ruta().write_bytes(b"esto no es una base de datos" * 40)


def _bloqueada(monkeypatch):
    """Como queda tras esperar los 5 s de `timeout` con otro escribiendo."""
    def abrir():
        raise sqlite3.OperationalError("database is locked")
    monkeypatch.setattr(memoria, "abrir_lectura", abrir)


@pytest.mark.parametrize("estropear", ["ilegible", "bloqueada"])
def test_con_la_memoria_ilegible_o_bloqueada_se_pinta_como_sin_base(cliente, monkeypatch, estropear):
    """Daba 500 en /secretario y en el sondeo del chat de todas las pantallas."""
    _ilegible() if estropear == "ilegible" else _bloqueada(monkeypatch)
    r = cliente.get("/secretario")
    assert r.status_code == 200 and "No está en marcha" in r.text
    t = cliente.get("/api/secretario/turnos")
    assert t.status_code == 200 and t.json() == SONDEO_VACIO


def test_una_memoria_que_no_se_deja_leer_se_dice_en_el_registro_una_vez_por_racha(cliente, monkeypatch, capsys):
    """Regla dura 21: se dice, pero no cada 1,5 s que sondea el chat."""
    from hub import api

    monkeypatch.setitem(api._MEMORIA_SIN_LEER, "racha", False)   # la de otro test no cuenta
    memoria.conectar().close()
    abrir, bloqueada = memoria.abrir_lectura, {"si": True}

    def abrir_a_ratos():
        if bloqueada["si"]:
            raise sqlite3.OperationalError("database is locked")
        return abrir()

    monkeypatch.setattr(memoria, "abrir_lectura", abrir_a_ratos)
    for _ in range(3):
        cliente.get("/api/secretario/turnos")
    cliente.get("/secretario")
    err = capsys.readouterr().err
    assert err.count("memoria del secretario") == 1 and "database is locked" in err
    bloqueada["si"] = False
    cliente.get("/api/secretario/turnos")         # se lee otra vez: la racha acaba
    bloqueada["si"] = True
    cliente.get("/api/secretario/turnos")
    assert capsys.readouterr().err.count("memoria del secretario") == 1


def test_el_enrutador_lee_su_tabla_sin_crear_la_carpeta():
    from hub.secretario import enrutador

    assert enrutador.tabla() == enrutador.POR_OMISION
    assert not _carpeta().exists()
