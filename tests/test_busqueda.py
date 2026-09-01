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
