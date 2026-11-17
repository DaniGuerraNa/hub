"""El `-wal` de `hub.db` no se queda en su máximo histórico (C-0281).

Medido el 11-nov: `hub.db` 1,8 MB y `hub.db-wal` 14 MB. Sin
`journal_size_limit` SQLite reutiliza el archivo desde el principio tras cada
punto de control pero nunca lo encoge: un rato en que no se pudo completar uno
deja el disco ocupado para siempre.
"""

from __future__ import annotations

from hub import db

CUATRO_MB = 4 * 1024 * 1024


def test_cada_conexion_lleva_el_tope_del_wal(tmp_path):
    con = db.conectar(tmp_path / "hub.db")
    assert con.execute("PRAGMA journal_size_limit").fetchone()[0] == CUATRO_MB
    con.close()


def test_tras_un_punto_de_control_el_wal_vuelve_a_bajar_del_tope(tmp_path):
    ruta = tmp_path / "hub.db"
    con = db.conectar(ruta)
    con.execute("PRAGMA wal_autocheckpoint=0")   # que crezca como el 11-nov
    con.execute("CREATE TABLE relleno (x BLOB)")
    for _ in range(40):
        con.execute("INSERT INTO relleno VALUES (zeroblob(250000))")
    wal = tmp_path / "hub.db-wal"
    assert wal.stat().st_size > 2 * CUATRO_MB

    con.execute("PRAGMA wal_checkpoint(PASSIVE)")
    con.execute("INSERT INTO relleno VALUES (zeroblob(10))")   # vuelve a empezar el WAL
    assert wal.stat().st_size <= CUATRO_MB
    con.close()


def test_la_memoria_del_secretario_lleva_el_mismo_tope(tmp_path):
    from hub.secretario import memoria

    con = memoria.conectar(tmp_path / "memoria.db")
    try:
        assert con.execute("PRAGMA journal_size_limit").fetchone()[0] == db.TOPE_DEL_WAL
    finally:
        con.close()
