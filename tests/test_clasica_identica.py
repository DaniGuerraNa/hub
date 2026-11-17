"""Quien no enciende la interfaz nueva no nota que existe (decisión 413).

La interfaz nueva entra detrás de un interruptor por aparato, y la promesa
que la hace aceptable es que sin su cookie no cambia nada. Mientras vivió en
su rama eso se midió contra `main`, pantalla a pantalla y byte a byte; una vez
mezclada, comparar con `main` pondría en rojo cualquier cambio visible de
cualquier pantalla, que no es lo que se quiere vigilar.

Lo que sigue valiendo, y esto mide: cada pantalla sale igual sin cookie, con
la cookie de la de siempre y con una cookie que no está en la lista. Y la de
los colores, sin la interfaz nueva, tampoco cambia un byte.

Cuando la interfaz de siempre se retire, este archivo se va con ella.
"""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

import arnes_tmux
from hub import interfaz, recorrido, web

#: Lo que se pinta además de las rutas sin parámetros: el detalle de lo
#: sembrado, las pestañas del secretario y una dirección que no existe.
DE_DETALLE = ("/proyecto/demo", "/trabajo?slot=1", "/secretario?p=pendientes",
              "/secretario?p=memoria", "/secretario?p=avisos", "/no-existe-esta-pantalla")

#: Con qué cookies tiene que salir lo mismo que sin ninguna.
SIN_EFECTO = (
    {interfaz.COOKIE: interfaz.CLASICA},
    {interfaz.COOKIE: "otra-que-no-existe"},
    {interfaz.COOKIE_COLORES: "brasa"},
    {interfaz.COOKIE: interfaz.CLASICA, interfaz.COOKIE_COLORES: "brasa"},
)


def _rutas() -> list[str]:
    llanas = [r for r in recorrido.rutas_get()
              if "{" not in r and r not in recorrido.NO_SE_VISITAN and not r.startswith("/api/")]
    return [*llanas, *DE_DETALLE]


@pytest.fixture
def hub_sembrado_sin_servidor(tmp_path, monkeypatch):
    """Lo mismo que siembra el recorrido en navegador, sin arrancar nada."""
    from test_pantallas_navegador import _sembrar
    _sembrar(tmp_path, monkeypatch)
    yield tmp_path
    # El servidor de `_sembrar` y su socket, que `kill-server` solo dejaba (C-0325).
    arnes_tmux.apagar(os.environ["HUB_TMUX_SOCKET"])


def _pintar(ruta: str, cookies: dict[str, str]) -> tuple[int, str]:
    # Un cliente por petición: las cookies de uno no se quedan para el siguiente.
    http = TestClient(web.app, cookies=cookies)
    r = http.get(ruta, headers={"accept": "text/html"}, follow_redirects=False)
    return r.status_code, r.text


def test_sin_encenderla_cada_pantalla_sale_igual_traiga_la_cookie_que_traiga(hub_sembrado_sin_servidor):
    rutas = _rutas()
    paginas = 0
    for ruta in rutas:
        de_siempre = _pintar(ruta, {})
        paginas += "<html" in de_siempre[1]
        assert 'data-interfaz="nueva"' not in de_siempre[1], ruta
        for cookies in SIN_EFECTO:
            con_cookie = _pintar(ruta, cookies)
            # Una pantalla que cuenta segundos («hace 4 s») puede cambiar entre
            # una petición y la siguiente: si difiere, se pintan otra vez seguidas.
            if con_cookie != de_siempre:
                de_siempre, con_cookie = _pintar(ruta, {}), _pintar(ruta, cookies)
            assert con_cookie == de_siempre, f"{ruta} cambia con {cookies}"
    assert paginas >= 25, f"sólo {paginas} páginas: esto no ha recorrido el hub"


@pytest.mark.skipif(not interfaz.disponible(), reason="esta instalación no trae la interfaz nueva")
def test_el_control_con_su_cookie_la_pantalla_si_cambia(hub_sembrado_sin_servidor):
    """Sin esto, el test de arriba pasaría igual si las cookies no llegaran."""
    assert 'data-interfaz="nueva"' in _pintar("/guia", {interfaz.COOKIE: interfaz.NUEVA})[1]
