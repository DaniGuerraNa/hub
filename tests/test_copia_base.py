"""La copia diaria de `hub.db` (decisión 277)."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta

import pytest
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


def test_la_copia_es_un_solo_archivo_y_no_queda_en_modo_wal(tmp_path, monkeypatch):
    """C-0280: la copia heredaba el modo WAL de la base (bytes 18 y 19 de la
    cabecera a 2), y abrirla para mirarla le creaba sus `-wal` y `-shm`: dejaba
    de ser un archivo autocontenido."""
    monkeypatch.setenv("HUB_RESPALDO", str(tmp_path / "copias"))
    con = _base_con_una_nota(tmp_path / "hub.db")
    destino = copia_base.hacer(con, ahora=datetime(2026, 10, 20, 12))
    assert tuple(destino.read_bytes()[18:20]) == (1, 1)
    mirada = sqlite3.connect(destino)
    assert mirada.execute("SELECT texto FROM prueba").fetchone() == ("lo que sólo vive aquí",)
    assert mirada.execute("PRAGMA journal_mode").fetchone()[0] == "delete"
    mirada.close()
    assert sorted(p.name for p in (tmp_path / "copias").iterdir()) == ["hub-20261020.db"]


def test_la_poda_se_lleva_los_wal_y_shm_de_las_copias_que_quita(tmp_path, monkeypatch):
    """C-0280: la poda sólo borraba los `.db` y dejaba sus hermanos (30 había
    el 11-nov). Los de una copia que se queda no se tocan: alguien puede
    tenerla abierta."""
    copias = tmp_path / "copias"
    monkeypatch.setenv("HUB_RESPALDO", str(copias))
    con = _base_con_una_nota(tmp_path / "hub.db")
    inicio = datetime(2026, 10, 1)
    for n in range(14):
        copia_base.hacer(con, ahora=inicio + timedelta(days=n))
    for nombre in ("hub-20261001.db", "hub-20261010.db", "hub-20260920.db"):
        for cola in ("-wal", "-shm"):
            (copias / (nombre + cola)).write_bytes(b"x")   # la del 20-sep ya no existe

    copia_base.hacer(con, ahora=inicio + timedelta(days=14))

    sueltos = sorted(p.name for p in copias.iterdir() if not p.name.endswith(".db"))
    assert sueltos == ["hub-20261010.db-shm", "hub-20261010.db-wal"]
    assert not (copias / "hub-20261001.db").exists()


# ── la copia de la memoria del secretario (C-0282) ──

def _copia_de(carpeta, nombre, hace_dias):
    from datetime import datetime as _dt
    import os
    carpeta.mkdir(parents=True, exist_ok=True)
    archivo = carpeta / nombre
    archivo.write_bytes(b"x" * 1000)
    cuando = (_dt.now() - timedelta(days=hace_dias)).timestamp()
    os.utime(archivo, (cuando, cuando))
    return archivo


def _memoria_en_uso():
    from hub import config
    (config.HUB_HOME / "secretario").mkdir(parents=True, exist_ok=True)
    (config.HUB_HOME / "secretario" / "memoria.db").write_bytes(b"")


def test_el_estado_mira_la_copia_de_cada_base_por_su_prefijo(tmp_path, monkeypatch):
    copias = tmp_path / "copias"
    monkeypatch.setenv("HUB_RESPALDO", str(copias))
    _copia_de(copias, "hub-20261111.db", 0)
    _copia_de(copias, "secretario-20261108.db", 3)
    assert copia_base.estado()["vieja"] is False
    secretario = copia_base.estado(prefijo="secretario-")
    assert secretario["copias"] == 1 and secretario["vieja"] is True


def test_una_copia_de_la_memoria_de_hace_tres_dias_sale_en_la_salud(tmp_path, monkeypatch):
    """C-0282: la memoria del secretario es la base que más vale y más crece, y
    su copia diaria (la hace `hub-secretario`) no la vigilaba nadie: si dejaba
    de hacerse, sólo quedaba en su bitácora. No es un aviso que salga solo
    (`avisos.CLASES` es lista cerrada): es una revisión de Máquina, como la de
    `hub.db`."""
    from hub import salud
    copias = tmp_path / "copias"
    monkeypatch.setenv("HUB_RESPALDO", str(copias))
    _memoria_en_uso()
    _copia_de(copias, "hub-20261111.db", 0)
    _copia_de(copias, "secretario-20261108.db", 3)
    revision = next(r for r in salud.revisar([]) if r["clave"] == "copia-secretario")
    assert revision["estado"] == "aviso"
    assert "memoria del secretario" in revision["nombre"]


def test_sin_secretario_no_se_echa_en_falta_su_copia(tmp_path, monkeypatch):
    from hub import salud
    monkeypatch.setenv("HUB_RESPALDO", str(tmp_path / "copias"))
    _copia_de(tmp_path / "copias", "hub-20261111.db", 0)
    assert not [r for r in salud.revisar([]) if r["clave"] == "copia-secretario"]


def test_la_pantalla_de_respaldo_pinta_la_copia_de_la_memoria(tmp_path, monkeypatch):
    copias = tmp_path / "copias"
    monkeypatch.setenv("HUB_RESPALDO", str(copias))
    _memoria_en_uso()
    _copia_de(copias, "hub-20261111.db", 0)
    _copia_de(copias, "secretario-20261108.db", 3)
    html = TestClient(web.app).get("/respaldo").text
    assert 'data-que="copia-memoria"' in html
    assert "La última copia de la memoria del secretario es del" in html


# ── la segunda carpeta, en otro disco, y la comprobación (C-0417) ──

def _base_rota(ruta):
    """Una base con una página de su índice machacada: abre, la API de copia
    la copia tal cual y `PRAGMA quick_check` lo ve. Es lo que pasa cuando el
    disco estropea un trozo: la copia hereda el defecto sin quejarse."""
    con = sqlite3.connect(ruta)
    con.execute("CREATE TABLE prueba (texto TEXT)")
    con.execute("CREATE INDEX por_texto ON prueba(texto)")
    con.executemany("INSERT INTO prueba VALUES (?)", [(f"fila {n:05d} " + "x" * 50,) for n in range(2000)])
    con.commit()
    con.close()
    with open(ruta, "r+b") as f:
        f.seek(4096 * 5 + 100)
        f.write(b"\xff" * 400)
    return sqlite3.connect(ruta)


def test_una_copia_que_no_pasa_la_comprobacion_no_se_da_por_buena_y_respaldo_lo_dice(tmp_path, monkeypatch):
    copias = tmp_path / "copias"
    monkeypatch.setenv("HUB_RESPALDO", str(copias))
    con = _base_rota(tmp_path / "hub.db")
    with pytest.raises(copia_base.CopiaDefectuosa):   # no pasa en silencio: el ciclo lento lo dice
        copia_base.hacer(con, ahora=datetime(2026, 10, 20, 12))
    assert not list(copias.glob("hub-*.db")), "no queda ningún hub-<fecha>.db que parezca bueno"
    assert not list(copias.glob("*.tmp"))
    e = copia_base.estado()
    assert e["defecto"] and e["comprobada"] is False
    html = TestClient(web.app).get("/respaldo").text
    assert 'data-que="copia-defectuosa"' in html
    assert "no pasó la comprobación" in html


def test_una_copia_sana_queda_comprobada_y_respaldo_lo_dice(tmp_path, monkeypatch):
    monkeypatch.setenv("HUB_RESPALDO", str(tmp_path / "copias"))
    con = _base_con_una_nota(tmp_path / "hub.db")
    copia_base.hacer(con)
    e = copia_base.estado()
    assert e["comprobada"] is True and e["defecto"] is None
    assert "Comprobada al hacerla" in TestClient(web.app).get("/respaldo").text


def test_la_copia_se_lleva_tambien_a_la_segunda_carpeta_y_alli_se_poda(tmp_path, monkeypatch):
    monkeypatch.setenv("HUB_RESPALDO", str(tmp_path / "copias"))
    otro = tmp_path / "otro-disco"
    otro.mkdir()
    monkeypatch.setenv("HUB_RESPALDO_EXTRA", str(otro))
    con = _base_con_una_nota(tmp_path / "hub.db")
    inicio = datetime(2026, 10, 1)
    for n in range(20):
        copia_base.hacer(con, ahora=inicio + timedelta(days=n))
    nombres = sorted(p.name for p in otro.iterdir())
    assert len(nombres) == 14 and nombres[-1] == "hub-20261020.db"
    leida = sqlite3.connect(otro / "hub-20261020.db").execute("SELECT texto FROM prueba").fetchone()
    assert leida == ("lo que sólo vive aquí",)
    e = copia_base.estado()
    assert e["extra"]["carpeta"] == str(otro) and e["extra"]["copias"] == 14 and e["extra"]["error"] is None


def test_la_segunda_carpeta_se_enciende_con_un_archivo_de_una_linea_sin_reiniciar(tmp_path, monkeypatch):
    from hub import config
    monkeypatch.delenv("HUB_RESPALDO_EXTRA", raising=False)
    monkeypatch.setenv("HUB_RESPALDO", str(tmp_path / "copias"))
    assert copia_base.carpeta_extra() is None
    otro = tmp_path / "otro-disco"
    otro.mkdir()
    (config.HUB_HOME / copia_base.ARCHIVO_EXTRA).write_text(f"{otro}\n", encoding="utf-8")
    assert copia_base.carpeta_extra() == otro
    con = _base_con_una_nota(tmp_path / "hub.db")
    copia_base.hacer(con, ahora=datetime(2026, 10, 20, 12))
    assert (otro / "hub-20261020.db").is_file()


def test_si_la_segunda_carpeta_no_existe_la_copia_local_sale_igual_y_se_dice(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("HUB_RESPALDO", str(tmp_path / "copias"))
    falta = tmp_path / "disco-sin-montar" / "respaldos"
    monkeypatch.setenv("HUB_RESPALDO_EXTRA", str(falta))
    con = _base_con_una_nota(tmp_path / "hub.db")
    destino = copia_base.hacer(con, ahora=datetime(2026, 10, 20, 12))
    assert destino is not None and destino.is_file()
    assert not falta.exists(), "no se crea sola: con el disco sin montar llenaría el de siempre"
    assert "no existe" in capsys.readouterr().out
    e = copia_base.estado()
    assert e["extra"]["error"] and "no existe" in e["extra"]["error"]
    html = TestClient(web.app).get("/respaldo").text
    assert 'data-que="copia-extra-falla"' in html and str(falta) in html


def test_la_segunda_carpeta_se_reintenta_cuando_vuelve_aunque_la_local_ya_estuviera(tmp_path, monkeypatch):
    monkeypatch.setenv("HUB_RESPALDO", str(tmp_path / "copias"))
    otro = tmp_path / "otro-disco"
    monkeypatch.setenv("HUB_RESPALDO_EXTRA", str(otro))
    con = _base_con_una_nota(tmp_path / "hub.db")
    dia = datetime(2026, 10, 20, 9)
    assert copia_base.hacer(con, ahora=dia) is not None
    assert copia_base.estado()["extra"]["error"]
    otro.mkdir()   # vuelve el disco
    assert copia_base.hacer(con, ahora=dia + timedelta(hours=1)) is None   # la local ya estaba
    assert (otro / "hub-20261020.db").is_file()
    assert copia_base.estado()["extra"]["error"] is None


def test_mis_datos_no_va_ni_a_las_copias_ni_a_la_segunda_carpeta(tmp_path, monkeypatch):
    """Decisión 382: la ficha de sus datos no se copia nunca, para que
    «olvidar» sea olvidar. La segunda carpeta no puede ser la excepción."""
    from hub.secretario import memoria, misdatos
    copias, otro = tmp_path / "copias", tmp_path / "otro-disco"
    otro.mkdir()
    monkeypatch.setenv("HUB_RESPALDO", str(copias))
    monkeypatch.setenv("HUB_RESPALDO_EXTRA", str(otro))
    misdatos.confirmar("domicilio_fiscal", "Calle Inventada 742, Ciudad Ficticia")
    hub = _base_con_una_nota(tmp_path / "hub.db")
    mem = memoria.conectar()
    copia_base.hacer(hub, ahora=datetime(2026, 10, 20, 12))
    copia_base.hacer(mem, ahora=datetime(2026, 10, 20, 12), prefijo=copia_base.PREFIJO_SECRETARIO)
    mem.close()
    for carpeta in (copias, otro):
        archivos = sorted(p.name for p in carpeta.iterdir() if p.suffix == ".db")
        assert archivos == ["hub-20261020.db", "secretario-20261020.db"]
    en_otro = sorted(p.name for p in otro.iterdir())
    assert en_otro == ["hub-20261020.db", "secretario-20261020.db"]
    for archivo in [*copias.iterdir(), *otro.iterdir()]:
        assert b"Inventada" not in archivo.read_bytes(), archivo.name
    assert misdatos.ruta().is_file()


def test_una_base_con_un_defecto_no_se_vuelve_a_copiar_entera_en_cada_vuelta(tmp_path, monkeypatch):
    """El defecto sigue ahí en el siguiente intento: rehacer la copia cada
    minuto no arregla nada. Se vuelve a decir sin copiar, y pasada la hora
    se intenta de nuevo."""
    import json
    from hub import config
    monkeypatch.setenv("HUB_RESPALDO", str(tmp_path / "copias"))
    con = _base_rota(tmp_path / "hub.db")
    dia = datetime(2026, 10, 20, 12)
    with pytest.raises(copia_base.CopiaDefectuosa):
        copia_base.hacer(con, ahora=dia)
    anotacion = config.HUB_HOME / "copia-hub.json"

    def con_intento_de_hace(minutos):
        datos = json.loads(anotacion.read_text(encoding="utf-8"))
        datos["comprobacion"]["cuando"] = (datetime.now() - timedelta(minutes=minutos)).isoformat(timespec="minutes")
        anotacion.write_text(json.dumps(datos), encoding="utf-8")
        return datos["comprobacion"]["cuando"]

    hace_media_hora = con_intento_de_hace(30)
    with pytest.raises(copia_base.CopiaDefectuosa):
        copia_base.hacer(con, ahora=dia)
    assert json.loads(anotacion.read_text(encoding="utf-8"))["comprobacion"]["cuando"] == hace_media_hora

    hace_dos_horas = con_intento_de_hace(120)
    with pytest.raises(copia_base.CopiaDefectuosa):
        copia_base.hacer(con, ahora=dia)
    assert json.loads(anotacion.read_text(encoding="utf-8"))["comprobacion"]["cuando"] != hace_dos_horas


def test_la_poda_solo_toca_lo_que_es_suyo_sin_duda_en_las_dos_carpetas(tmp_path, monkeypatch):
    """Revisión cruzada de C-0417: la segunda carpeta es del dueño, y la poda
    borraba por `hub-*.db`. Un `hub-notas.db` suyo (o sus `-wal`/`-shm`) caía
    con la primera poda. Sólo es nuestro `<prefijo>` + 8 cifras + `.db`."""
    from hub import db as _db
    copias, otro = tmp_path / "copias", tmp_path / "otro-disco"
    otro.mkdir()
    monkeypatch.setenv("HUB_RESPALDO", str(copias))
    monkeypatch.setenv("HUB_RESPALDO_EXTRA", str(otro))
    con = _base_con_una_nota(tmp_path / "hub.db")
    inicio = datetime(2026, 10, 1)
    copia_base.hacer(con, ahora=inicio)
    ajenos = ["hub-notas.db", "hub-notas.db-wal", "hub-notas.db-shm", "hub-2026.db", "secretario-viejo.db",
              "hub-202610011.db"]
    for carpeta in (copias, otro):
        for nombre in ajenos:
            (carpeta / nombre).write_bytes(b"de quien lo usa")
    for n in range(1, 20):
        copia_base.hacer(con, ahora=inicio + timedelta(days=n))
    for carpeta in (copias, otro):
        quedan = {p.name for p in carpeta.iterdir()}
        assert set(ajenos) <= quedan, carpeta.name
        assert len([n for n in quedan if n not in ajenos]) == 14
    assert copia_base.estado()["copias"] == 14
    assert copia_base.estado()["extra"]["copias"] == 14
    assert _db._ultima_copia().name == "hub-20261020.db"


def test_en_el_secretario_una_copia_defectuosa_se_apunta_una_vez_por_racha_y_otra_al_volver(
        tmp_path, monkeypatch, capsys):
    """Revisión cruzada de C-0417: `CopiaDefectuosa` caía en `servicio._paso`,
    que deja una fila y una traza en cada vuelta (30 s) mientras dure: medido,
    5 vueltas, 5 filas, 5 trazas. Como en el snapshotter, una vez por racha y
    otra al volver; el paso se sigue intentando en cada vuelta."""
    from hub.secretario import memoria, servicio
    monkeypatch.setenv("HUB_RESPALDO", str(tmp_path / "copias"))
    monkeypatch.setattr(copia_base, "REINTENTO", timedelta(0))   # que cada vuelta copie de verdad
    monkeypatch.setattr(servicio, "_racha_copia", None)

    con = memoria.conectar()
    con.execute("CREATE TABLE prueba (texto TEXT)")
    con.execute("CREATE INDEX por_texto ON prueba(texto)")
    con.executemany("INSERT INTO prueba VALUES (?)", [(f"fila {n:05d} " + "x" * 50,) for n in range(2000)])
    con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    raiz = con.execute("SELECT rootpage FROM sqlite_master WHERE name = 'por_texto'").fetchone()[0]
    tam = con.execute("PRAGMA page_size").fetchone()[0]
    con.close()
    ruta = memoria.carpeta() / "memoria.db"
    with open(ruta, "r+b") as f:
        f.seek(tam * (raiz - 1))
        buena = f.read(tam)
        f.seek(tam * (raiz - 1) + 12)
        f.write(b"\xff" * 200)

    def filas_de_la_copia(c):
        return [(f["ok"], f["resultado"]) for f in c.execute(
            "SELECT ok, resultado FROM bitacora WHERE accion = 'copia' ORDER BY id")]

    con = memoria.conectar()
    capsys.readouterr()
    for _ in range(5):
        servicio._paso(con, "copia", servicio.copia_diaria)
    filas = filas_de_la_copia(con)
    assert len(filas) == 1 and filas[0][0] == 0 and "comprobación" in filas[0][1]
    assert capsys.readouterr().err.count("Traceback") == 1
    assert not list((tmp_path / "copias").glob("secretario-*.db"))
    con.close()

    with open(ruta, "r+b") as f:   # el defecto se arregla
        f.seek(tam * (raiz - 1))
        f.write(buena)
    con = memoria.conectar()
    servicio._paso(con, "copia", servicio.copia_diaria)
    servicio._paso(con, "copia", servicio.copia_diaria)
    filas = filas_de_la_copia(con)
    assert len(filas) == 2 and filas[1][0] == 1 and "vuelve" in filas[1][1]
    assert len(list((tmp_path / "copias").glob("secretario-*.db"))) == 1
    con.close()


# ── C-0448: la copia de antes de actualizar ──────────────────────────────────
#
# `actualizar.sh` la pide antes de los pasos de versión y del reinicio, que es
# cuando el código nuevo cambia el esquema al abrir las bases. La diaria puede
# tener 23 horas; ésta es de un momento antes de tocarlas.

def _base_de_ayer(ruta, tabla, filas=1):
    """Una base con el esquema de una versión anterior, en WAL y cerrada: lo
    que hay en disco cuando se corre `actualizar.sh`. A propósito sin
    `db.conectar` ni `memoria.conectar`, que la pondrían al día."""
    ruta.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(ruta)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute(f"CREATE TABLE {tabla} (texto TEXT)")
    con.executemany(f"INSERT INTO {tabla} VALUES (?)", [(f"fila {n}",) for n in range(filas)])
    con.commit()
    con.close()


def _esquema(ruta):
    con = sqlite3.connect(f"{ruta.resolve().as_uri()}?mode=ro", uri=True)
    try:
        return sorted(con.execute(
            "SELECT m.name, c.name FROM sqlite_master AS m, pragma_table_info(m.name) AS c"
            " WHERE m.type = 'table'").fetchall())
    finally:
        con.close()


def _filas(ruta, tabla):
    con = sqlite3.connect(ruta)
    try:
        return con.execute(f"SELECT count(*) FROM {tabla}").fetchone()[0]
    finally:
        con.close()


def test_antes_de_actualizar_copia_las_dos_bases_sin_migrarlas(tmp_path, monkeypatch):
    """`db.conectar` y `memoria.conectar` ponen el esquema al día al abrir: la
    copia «de antes» hecha con ellas ya no sería de antes, y la base tampoco."""
    from hub import config
    from hub.secretario import memoria
    _base_de_ayer(config.DB_PATH, "proyecto")
    _base_de_ayer(memoria.ruta(), "turno")
    ayer_hub, ayer_memoria = _esquema(config.DB_PATH), _esquema(memoria.ruta())

    hechas = copia_base.antes_de_actualizar(ahora=datetime(2026, 11, 13, 9))

    carpeta = config.HUB_HOME / "respaldos"
    assert hechas == [carpeta / "antes-hub-20261113.db", carpeta / "antes-secretario-20261113.db"]
    assert _esquema(hechas[0]) == ayer_hub == [("proyecto", "texto")]
    assert _esquema(hechas[1]) == ayer_memoria == [("turno", "texto")]
    # Y las bases siguen como estaban: copiar no es abrirlas para escribir.
    assert _esquema(config.DB_PATH) == ayer_hub and _esquema(memoria.ruta()) == ayer_memoria
    for copia in hechas:
        assert copia_base.comprobar(copia) == "ok"
        assert sqlite3.connect(copia).execute("PRAGMA journal_mode").fetchone() == ("delete",)


def test_antes_de_actualizar_no_rehace_la_de_hoy_en_un_reintento(tmp_path, monkeypatch):
    """Si el primer intento falló a medias, el código nuevo ya pudo tocar la
    base: la buena es la del primer intento, y un reintento no la pisa."""
    from hub import config
    _base_de_ayer(config.DB_PATH, "proyecto", filas=1)
    hoy = datetime(2026, 11, 13, 9)
    primera = copia_base.antes_de_actualizar(ahora=hoy)
    con = sqlite3.connect(config.DB_PATH)
    con.execute("INSERT INTO proyecto VALUES ('escrito por la versión nueva')")
    con.commit()
    con.close()

    segunda = copia_base.antes_de_actualizar(ahora=hoy.replace(hour=11))

    assert segunda == primera
    assert _filas(primera[0], "proyecto") == 1


def test_sin_secretario_solo_se_copia_hub_db_y_no_se_crea_su_carpeta(tmp_path, monkeypatch):
    from hub import config
    _base_de_ayer(config.DB_PATH, "proyecto")
    hechas = copia_base.antes_de_actualizar(ahora=datetime(2026, 11, 13, 9))
    assert [p.name for p in hechas] == ["antes-hub-20261113.db"]
    assert not (config.HUB_HOME / "secretario").exists()


def test_sin_ninguna_base_no_hay_nada_que_copiar(tmp_path, monkeypatch):
    from hub import config
    assert copia_base.antes_de_actualizar(ahora=datetime(2026, 11, 13, 9)) == []
    assert not config.DB_PATH.exists()


def test_de_las_de_antes_se_guardan_tres_y_no_se_mezclan_con_las_diarias(tmp_path, monkeypatch):
    """Tres de cada una (C-0448), con su propio prefijo: ni la poda de las de
    antes toca las catorce diarias ni `/respaldo` cuenta las de antes como
    si fueran la copia de cada día."""
    from hub import config
    from hub.secretario import memoria
    _base_de_ayer(config.DB_PATH, "proyecto")
    _base_de_ayer(memoria.ruta(), "turno")
    carpeta = config.HUB_HOME / "respaldos"
    _copia_de(carpeta, "hub-20261101.db", 12)
    _copia_de(carpeta, "secretario-20261101.db", 12)
    for dia in range(1, 6):
        copia_base.antes_de_actualizar(ahora=datetime(2026, 11, 8 + dia, 9))

    nombres = sorted(p.name for p in carpeta.glob("*.db"))
    assert nombres == [
        "antes-hub-20261111.db", "antes-hub-20261112.db", "antes-hub-20261113.db",
        "antes-secretario-20261111.db", "antes-secretario-20261112.db", "antes-secretario-20261113.db",
        "hub-20261101.db", "secretario-20261101.db",
    ]
    assert copia_base.estado()["copias"] == 1
    assert copia_base.estado(prefijo=copia_base.PREFIJO_SECRETARIO)["copias"] == 1


def test_la_orden_antes_dice_donde_quedaron_las_copias(tmp_path, monkeypatch, capsys):
    """Lo que lee `actualizar.sh` para decir, si falla, dónde están."""
    from hub import config
    _base_de_ayer(config.DB_PATH, "proyecto")
    assert copia_base.main(["antes"]) == 0
    salida = capsys.readouterr().out.splitlines()
    assert len(salida) == 1 and salida[0].endswith(".db") and "/antes-hub-" in salida[0]
    assert copia_base.main(["otra"]) == 2


def test_lo_que_se_dice_por_el_camino_no_se_mezcla_con_las_rutas(tmp_path, monkeypatch, capsys):
    """Las de antes también van a la segunda carpeta, como las diarias. Si no
    está, se dice —por stderr—: en stdout `actualizar.sh` lee rutas, y una
    línea más saldría como «copia de antes: [copia …]»."""
    from hub import config
    monkeypatch.setenv("HUB_RESPALDO_EXTRA", str(tmp_path / "disco-sin-montar"))
    _base_de_ayer(config.DB_PATH, "proyecto")
    assert copia_base.main(["antes"]) == 0
    salida = capsys.readouterr()
    assert salida.out.splitlines() == [
        str(config.HUB_HOME / "respaldos" / f"antes-hub-{datetime.now():%Y%m%d}.db")]
    assert "segunda carpeta" in salida.err


def test_las_de_antes_tambien_van_a_la_segunda_carpeta_y_alli_se_quedan_tres(tmp_path, monkeypatch):
    from hub import config
    otro = tmp_path / "otro-disco"
    otro.mkdir()
    monkeypatch.setenv("HUB_RESPALDO_EXTRA", str(otro))
    _base_de_ayer(config.DB_PATH, "proyecto")
    for dia in range(1, 6):
        copia_base.antes_de_actualizar(ahora=datetime(2026, 11, 8 + dia, 9))
    assert sorted(p.name for p in otro.iterdir()) == [
        "antes-hub-20261111.db", "antes-hub-20261112.db", "antes-hub-20261113.db"]


def test_si_la_copia_de_antes_no_se_puede_hacer_la_orden_falla_y_lo_dice(tmp_path, monkeypatch, capsys):
    """Sin copia no se sigue: `actualizar.sh` para antes de tocar nada."""
    from hub import config
    config.DB_PATH.write_bytes(b"esto no es una base de SQLite" * 200)
    assert copia_base.main(["antes"]) == 1
    assert "no se pudo copiar" in capsys.readouterr().err
    assert not list((config.HUB_HOME / "respaldos").glob("antes-hub-*.db"))
