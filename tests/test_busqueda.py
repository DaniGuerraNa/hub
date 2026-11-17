"""Búsqueda y paleta de comandos.

El problema que el hub resuelve no es de pantallas, es de memoria: con ~20
ubicaciones y ~60 capacidades, escribir el nombre gana a recordar la sección.
Un buscador que revienta con un guion o que devuelve resultados sin destino no
sirve para eso.
"""

from __future__ import annotations

import pytest

from hub import busqueda, db


def _poblar(con):
    con.execute(
        "INSERT INTO proyecto (id, nombre, nota) VALUES ('facturador','Facturador','45 sesiones')"
    )
    con.execute(
        """INSERT INTO slot (proyecto_id, nombre, nota, ruta, creado_en)
           VALUES ('facturador','back','levantar la lambda de notificaciones','/dev/x','2026-01-01')"""
    )
    con.execute(
        """INSERT INTO capacidad (proyecto_id, tipo, nombre, ruta, descripcion)
           VALUES ('facturador','agente','dev-backend','/a/dev-backend.md','Implementador backend')"""
    )
    con.execute(
        """INSERT INTO servicio (contenedor, proyecto_id, imagen, estado, medido_en)
           VALUES ('facturador-dev-postgres','facturador','pgvector','running','2026-01-01')"""
    )
    busqueda.reindexar(con)


def test_encuentra_por_prefijo_sin_escribir_la_palabra_entera(con):
    _poblar(con)
    titulos = {r["titulo"] for r in busqueda.buscar(con, "fact")}
    assert "Facturador" in titulos


def test_un_guion_no_revienta_la_consulta(con):
    """`dev-backend` y `mutar.py` son sintaxis para FTS5: hay que citarlos."""
    _poblar(con)
    assert [r["titulo"] for r in busqueda.buscar(con, "dev-backend")] == ["dev-backend"]


@pytest.mark.parametrize("texto", ['a.b(c', 'NEAR("x")', 'a OR', '"sin cerrar', 'x AND AND'])
def test_la_sintaxis_de_fts_tecleada_por_accidente_no_lanza(con, texto):
    """Lo que se escribe en la paleta es texto libre, no una consulta FTS."""
    _poblar(con)
    assert isinstance(busqueda.buscar(con, texto), list)


def test_busca_en_el_cuerpo_no_solo_en_el_nombre(con):
    """La nota larga de un slot es donde vive el contexto que se busca."""
    _poblar(con)
    assert [r["clase"] for r in busqueda.buscar(con, "lambda")] == ["slot"]


def test_un_proyecto_gana_a_los_contenedores_que_llevan_su_nombre(con):
    """Buscar «facturador» devolvía catorce contenedores y ningún proyecto.

    Ordenar sólo por relevancia de FTS entierra justo lo que se buscaba: un
    proyecto es un sitio al que ir, un contenedor casi nunca lo es.
    """
    _poblar(con)
    assert busqueda.buscar(con, "facturador")[0]["clase"] == "proyecto"


def test_cada_resultado_trae_su_destino(con):
    """Encontrar sin poder ir es la mitad inútil del trabajo."""
    _poblar(con)
    destinos = {r["clase"]: r["url"] for r in busqueda.buscar(con, "facturador")}
    assert destinos["proyecto"] == "/proyecto/facturador"
    assert destinos["servicio"] == "/servicios"


def test_no_busca_con_menos_de_dos_letras(con):
    """Con una letra todo coincide: sería ruido, no resultados."""
    _poblar(con)
    assert busqueda.buscar(con, "c") == []
    assert busqueda.buscar(con, "") == []


def test_reindexar_refleja_lo_borrado(con):
    _poblar(con)
    con.execute("DELETE FROM capacidad")
    busqueda.reindexar(con)
    assert busqueda.buscar(con, "dev-backend") == []


def test_sin_fts5_la_busqueda_degrada_a_like_en_vez_de_desaparecer(con, monkeypatch):
    """FTS5 no está en todos los builds de SQLite; el hub tiene que arrancar igual."""
    _poblar(con)
    monkeypatch.setattr(db, "hay_fts", lambda c: False)
    resultados = busqueda.buscar(con, "backend")
    assert any(r["titulo"] == "dev-backend" for r in resultados)


# Llave de mentira, con el formato que ya usan los tests de `ocultar_secretos`.
_LLAVE_FALSA = "sk-ant-api03-abcdefghijklmnopqrstuvwxyz0123456789"


def _slot_con_llave(con):
    con.execute("INSERT INTO proyecto (id, nombre) VALUES ('web','Web')")
    con.execute(
        "INSERT INTO slot (proyecto_id, nombre, nota, ruta, creado_en) VALUES "
        "('web','login',?,'/dev/x','2026-01-01')",
        (f"migrar el despliegue, la clave es {_LLAVE_FALSA} y falta el cron",))


@pytest.mark.parametrize("con_fts", [True, False])
def test_la_nota_se_encuentra_por_sus_palabras_pero_no_enseña_la_llave(con, monkeypatch, con_fts):
    _slot_con_llave(con)
    if not con_fts:
        monkeypatch.setattr(db, "hay_fts", lambda c: False)
    busqueda.reindexar(con)
    (r,) = [x for x in busqueda.buscar(con, "despliegue") if x["clase"] == "slot"]
    assert "sk-ant-api03" not in r["detalle"] and "abcdefghijklmnop" not in r["detalle"]
    assert r["detalle"] == "Web · /dev/x"      # y de la nota, nada (C-0356)


def test_buscar_un_trozo_de_la_llave_no_la_revela_en_el_extracto(con):
    _slot_con_llave(con)
    busqueda.reindexar(con)
    for r in busqueda.buscar(con, "abcdefghijklmnop"):
        assert "abcdefghijklmnop" not in r["detalle"]


# ── La nota del slot no se enseña nunca (C-0356) ─────────────────────────────

# Una llave de mentira que la red de patrones NO caza (es corta): lo que la
# protege aquí no es taparla, es que la nota no se enseñe.
_LLAVE_QUE_NO_SE_CAZA = "sk-ant-EJEMPLO"


def _slot_con_nota_y_llave(con):
    con.execute("INSERT INTO proyecto (id, nombre) VALUES ('web','Web')")
    con.execute(
        "INSERT INTO slot (proyecto_id, nombre, nota, ruta, creado_en) VALUES "
        "('web','login',?,'/dev/web','2026-01-01')",
        (f"revisar el cron; la llave del bot es {_LLAVE_QUE_NO_SE_CAZA}",))


@pytest.mark.parametrize("con_fts", [True, False])
def test_un_slot_se_encuentra_por_su_nota_pero_enseña_su_proyecto_y_su_ruta(con, monkeypatch, con_fts):
    _slot_con_nota_y_llave(con)
    if not con_fts:
        monkeypatch.setattr(db, "hay_fts", lambda c: False)
    busqueda.reindexar(con)

    (r,) = [x for x in busqueda.buscar(con, "cron") if x["clase"] == "slot"]

    assert r["titulo"] == "login" and r["detalle"] == "Web · /dev/web"


def test_ni_la_nota_ni_su_llave_salen_en_lo_que_devuelve_la_busqueda(con, tmp_path, monkeypatch):
    """Lo que recibe la paleta, por HTTP: ni una palabra de la nota."""
    import json

    from fastapi.testclient import TestClient

    from hub import web
    _slot_con_nota_y_llave(con)
    busqueda.reindexar(con)
    con.commit()

    def conexion():          # la misma base que el fixture `con`
        c = db.conectar(tmp_path / "hub.db")
        db.inicializar(c)
        return c
    monkeypatch.setattr(web, "conexion", conexion)

    respuesta = TestClient(web.app).get("/api/buscar", params={"q": "cron"})

    texto = json.dumps(respuesta.json(), ensure_ascii=False)
    assert '"login"' in texto
    assert "EJEMPLO" not in texto and "revisar" not in texto and "llave del bot" not in texto
