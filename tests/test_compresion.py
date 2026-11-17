"""Las pantallas viajan comprimidas a quien lo acepta (C-0278).

Se servían sin comprimir: `/trabajo` 290 KB, `/intercambio` casi 750, y cada
página lleva su CSS en línea. Desde el teléfono por la red privada eso se nota
en cada navegación. Comprimir no puede tocar lo que no es una página: la
terminal (WebSocket), lo que ya viene comprimido y una descarga.
"""

from __future__ import annotations

import gzip

import pytest
from fastapi.testclient import TestClient
from starlette.middleware.gzip import GZipMiddleware

from hub import db, intercambio, web


@pytest.fixture
def cliente(tmp_path, monkeypatch):
    def conexion():
        con = db.conectar(tmp_path / "hub.db")
        db.inicializar(con)
        return con

    monkeypatch.setattr(web, "conexion", conexion)
    return TestClient(web.app)


def _crudo(cliente, ruta, codificacion):
    """La respuesta tal como sale del hub, sin que el cliente la descomprima."""
    with cliente.stream("GET", ruta, headers={"Accept-Encoding": codificacion}) as r:
        return r, b"".join(r.iter_raw())


@pytest.mark.parametrize("ruta", ["/respaldo", "/static/sin-recarga.js"])
def test_una_pantalla_sale_comprimida_si_el_navegador_lo_acepta(cliente, ruta):
    r, cuerpo = _crudo(cliente, ruta, "gzip, deflate, br")
    assert r.status_code == 200
    assert r.headers["content-encoding"] == "gzip"
    assert "accept-encoding" in r.headers["vary"].lower()
    _, tal_cual = _crudo(cliente, ruta, "identity")
    assert gzip.decompress(cuerpo) == tal_cual
    assert len(cuerpo) < len(tal_cual) / 2


def test_sin_aceptarlo_sale_tal_cual(cliente):
    """`curl` a secas, el agente de reuniones y los relés (urllib) no piden
    compresión: a ellos les llega lo de siempre."""
    r, _ = _crudo(cliente, "/respaldo", "identity")
    assert "content-encoding" not in r.headers


def test_una_descarga_no_se_comprime_por_el_camino(cliente):
    """Lo que se baja de Intercambio puede ser cualquier cosa, y casi siempre
    ya va comprimido: recomprimirlo cuesta CPU y quita el tamaño, que es lo
    que pinta la barra de progreso."""
    intercambio.guardar("notas.txt", b"una linea\n" * 2000)
    r, cuerpo = _crudo(cliente, "/intercambio/bajar/notas.txt", "gzip")
    assert r.status_code == 200
    assert "content-encoding" not in r.headers
    assert int(r.headers["content-length"]) == len(cuerpo) == 20000


def test_una_respuesta_pequena_no_se_comprime(cliente):
    """Por debajo de 1 KB la cabecera de gzip se come lo que ahorra. (Un
    estático pequeño sí sale comprimido: Starlette lo manda por trozos y no
    sabe su tamaño de antemano; son unos bytes y da igual.)"""
    r, cuerpo = _crudo(cliente, "/api/lienzos?proyecto=ninguno", "gzip")
    assert r.status_code == 200 and len(cuerpo) < 1024
    assert "content-encoding" not in r.headers


def test_la_compresion_va_por_dentro_y_la_terminal_no_pasa_por_ella():
    """Por dentro de `_la_puerta`: por fuera, sus trozos le escondían el tamaño
    de todo. Y sólo para HTTP: el WebSocket de la terminal no se toca (lo
    prueban `test_mismo_origen` y `test_terminal`)."""
    assert web.app.user_middleware[-1].cls is GZipMiddleware
