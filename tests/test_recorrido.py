"""`hub.recorrido` sin navegador: lo que tiene que valer aunque falte Playwright.

El recorrido de verdad está en `test_pantallas_navegador.py` y se salta sin
Chromium. Esto corre siempre: que sus listas de excepciones no se queden
muertas al renombrar una ruta, que casa los ids como dice, y que sin el
navegador adecuado se niega en voz alta en vez de medir mal (C-0168).
"""

from __future__ import annotations

import time

import pytest

from hub import mirar, recorrido


def test_cada_ruta_excluida_existe_en_la_app():
    """Una exclusión de una ruta renombrada no excluye nada y nadie lo nota."""
    rutas = set(recorrido.rutas_get())
    assert not set(recorrido.NO_SE_VISITAN) - rutas
    assert not set(recorrido.PIDEN_CONSULTA) - rutas
    assert not set(recorrido.SIN_PRESTAR) - rutas


def test_las_rutas_son_las_del_hub_y_no_la_documentacion_de_fastapi():
    rutas = recorrido.rutas_get()
    assert "/" in rutas and "/proyecto/{proyecto_id}" in rutas and "/trabajo" in rutas
    assert not [r for r in rutas if r.startswith(("/static", "/api/docs", "/redoc", "/docs"))]
    assert "/openapi.json" not in rutas
    assert len(rutas) == len(set(rutas))


def test_el_patron_casa_un_camino_real_y_saca_cada_parametro():
    m = recorrido.patron("/reuniones/{id_}/foto/{segundo}").match("/reuniones/20261020-0900/foto/4")
    assert m and m.groupdict() == {"id_": "20261020-0900", "segundo": "4"}
    assert not recorrido.patron("/reuniones/{id_}").match("/reuniones/a/foto/4")
    assert recorrido.patron("/intercambio/ver/{nombre:path}").match("/intercambio/ver/_tablero/3/a.png")


def test_un_id_aprendido_se_rellena_escapado():
    assert recorrido._rellenar("/api/estado/{proyecto_id}", {"proyecto_id": "a b/c"}) == \
        "/api/estado/a%20b%2Fc"


def test_con_solo_el_chrome_de_windows_se_niega_en_vez_de_medir_mal(monkeypatch):
    monkeypatch.setattr(mirar, "cual", lambda: "/mnt/c/Program Files/Google/Chrome/Application/chrome.exe")
    assert mirar.cual_linux() is None
    with pytest.raises(mirar.SinNavegador, match="500 px"):
        recorrido.recorrer("http://127.0.0.1:1")


@pytest.mark.parametrize("error,dice", [
    (ModuleNotFoundError("playwright"), "uv run --group navegador"),
    (mirar.SinNavegador("no hay Chromium"), "no hay Chromium"),
])
def test_la_orden_sin_lo_que_necesita_sale_con_2_y_dice_que_falta(monkeypatch, capsys, error, dice):
    def falla(*a, **kw):
        raise error
    monkeypatch.setattr(recorrido, "recorrer", falla)
    assert recorrido.main(["--url", "http://127.0.0.1:1"]) == 2
    assert dice in capsys.readouterr().err


def test_el_informe_dice_lo_que_no_se_pudo_visitar_y_cada_fallo():
    informe = recorrido.Informe("http://h", visitadas=["/"], sin_visitar=["/api/pregunta/{pregunta_id}"],
                                fallos=[recorrido.Fallo("/", 390, "desborde", "473 px")])
    texto = informe.texto()
    assert "/api/pregunta/{pregunta_id}" in texto and "[desborde] / @390: 473 px" in texto


def _recorrido_sin_navegador(enlaces):
    r = object.__new__(recorrido._Recorrido)
    r.patrones = [recorrido.patron(x) for x in recorrido.rutas_get() if recorrido._parametros(x)]
    r.enlaces, r.valores, r.visitadas = [], {}, []
    r.visitar = r.visitadas.append
    r._aprender(enlaces)
    return r


def test_el_visor_de_imagenes_no_toma_prestado_el_nombre_de_una_descarga():
    """El `nombre` de `/intercambio/bajar/…` puede ser un .json, y el visor sólo
    enseña imágenes (415 a propósito): rellenarlo con él era un fallo inventado."""
    r = _recorrido_sin_navegador(["/intercambio/bajar/ux-capturas/medidas.json"])
    assert r.valores.get("nombre") == "ux-capturas/medidas.json"
    assert r._detalle("/intercambio/ver/{nombre:path}") is False
    assert r.visitadas == []


def test_el_visor_si_se_visita_con_un_enlace_que_lleva_a_el():
    r = _recorrido_sin_navegador(["/intercambio/ver/_tablero/3/a.png"])
    assert r._detalle("/intercambio/ver/{nombre:path}") is True
    assert r.visitadas == ["/intercambio/ver/_tablero/3/a.png"]


def test_un_id_suelto_se_sigue_prestando_entre_rutas():
    r = _recorrido_sin_navegador(["/proyecto/demo"])
    assert r._detalle("/api/estado/{proyecto_id}") is True
    assert r.visitadas == ["/api/estado/demo"]


# --- avisos de calidad (C-0248): con un navegador de verdad y una página sintética ---

import http.server
import threading

_CUMPLE = """<!doctype html><html><head><meta name="viewport" content="width=device-width, initial-scale=1"><title>ok</title><style>
a,button,input{display:inline-block;min-width:44px;min-height:44px;font-size:16px}</style></head>
<body><main><h1>Hola</h1><a href="#x">uno</a><input aria-label="campo"><button class="cta">Sí</button>
</main></body></html>"""

_INCUMPLE = """<!doctype html><html><head><meta name="viewport" content="width=device-width, initial-scale=1"><title>mal</title><style>
a{display:inline-block;width:10px;height:10px;font-size:8px}input{font-size:10px}</style></head>
<body><div><a href="#x">u</a><input aria-label="campo">
<button class="cta">A</button><button class="cta">B</button></div></body></html>"""


@pytest.fixture
def sitio():
    """Un servidor propio en un puerto libre de 127.0.0.1: nunca el hub real."""
    paginas = {"/cumple": (_CUMPLE, 0), "/incumple": (_INCUMPLE, 0.7)}

    class Manejador(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            html, espera = paginas[self.path]
            time.sleep(espera)
            cuerpo = html.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(cuerpo)))
            self.end_headers()
            self.wfile.write(cuerpo)

        def log_message(self, *a):
            pass

    servidor = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Manejador)
    threading.Thread(target=servidor.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{servidor.server_address[1]}"
    servidor.shutdown()


def _recorrer_o_saltar(base, ruta, anchos=(390, 1200)):
    pytest.importorskip("playwright.sync_api")
    if not mirar.cual_linux():
        pytest.skip("no hay un Chromium de Linux")
    return recorrido.recorrer(base, anchos=anchos, rutas=[ruta])


def test_una_pagina_que_incumple_cada_regla_saca_un_aviso_de_cada_clase(sitio):
    informe = _recorrer_o_saltar(sitio, "/incumple")
    clases_390 = {a.clase for a in informe.avisos if a.ancho == 390}
    assert clases_390 == {"objetivos", "campos", "sin_h1", "sin_main", "ttfb", "cta"}
    # Los campos sólo se miran en el teléfono; el resto, a todos los anchos.
    assert "campos" not in {a.clase for a in informe.avisos if a.ancho == 1200}
    assert not informe.fallos


def test_una_pagina_que_cumple_todo_no_saca_ningun_aviso(sitio):
    informe = _recorrer_o_saltar(sitio, "/cumple")
    assert informe.avisos == [] and informe.fallos == []


def test_los_avisos_se_leen_en_el_texto_del_informe_y_no_cambian_el_codigo_de_salida(monkeypatch, capsys):
    informe = recorrido.Informe("http://h", visitadas=["/"], avisos=[
        recorrido.Aviso("/", 390, "objetivos", "3 de menos de 24 px: a «u» 10×10")])
    assert "1 avisos (no rompen el recorrido)" in informe.texto()
    assert "[objetivos] / @390: 3 de menos de 24 px" in informe.texto()
    monkeypatch.setattr(recorrido, "recorrer", lambda *a, **kw: informe)
    assert recorrido.main(["--url", "http://127.0.0.1:1"]) == 0


# --- recorrer con la interfaz nueva (C-0169) ---

# Un panel como el del secretario: al pulsar su pestaña se abre y, aquí, algo se sale de lado.
_CON_PANEL = """<!doctype html><html><head><meta name="viewport" content="width=device-width, initial-scale=1"><title>p</title>
<style>body{margin:0}#ancho{display:none;width:3000px;height:10px}.abierto + #ancho{display:block}</style></head>
<body><main><h1>Hola</h1></main>
<aside id="secretario-panel"><button id="secretario-pestana" style="min-width:44px;min-height:44px">abrir</button></aside>
<div id="ancho">sale</div>
<script>document.getElementById('secretario-pestana').addEventListener('click',
  () => document.getElementById('secretario-panel').classList.add('abierto'));</script></body></html>"""


@pytest.fixture
def sitio_con_panel():
    """Como `sitio`, y apunta la cookie con que llega cada petición."""
    recibidas = []

    class Manejador(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            recibidas.append(self.headers.get("Cookie", ""))
            cuerpo = _CON_PANEL.encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(cuerpo)))
            self.end_headers()
            self.wfile.write(cuerpo)

        def log_message(self, *a):
            pass

    servidor = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Manejador)
    threading.Thread(target=servidor.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{servidor.server_address[1]}", recibidas
    servidor.shutdown()


def _recorrer_con(base, **kw):
    pytest.importorskip("playwright.sync_api")
    if not mirar.cual_linux():
        pytest.skip("no hay un Chromium de Linux")
    return recorrido.recorrer(base, anchos=(1200,), rutas=["/panel"], **kw)


def test_con_la_interfaz_nueva_lleva_su_cookie_y_mide_tambien_con_el_panel_abierto(sitio_con_panel):
    base, recibidas = sitio_con_panel
    informe = _recorrer_con(base, interfaz="nueva")
    assert recibidas and all("hub_interfaz=nueva" in c for c in recibidas), recibidas
    [fallo] = informe.fallos
    assert fallo.clase == "desborde" and fallo.detalle.startswith("con el panel abierto, 3000 px")


def test_sin_pedir_interfaz_no_manda_cookie_ni_abre_el_panel(sitio_con_panel):
    base, recibidas = sitio_con_panel
    informe = _recorrer_con(base)
    assert recibidas and not any("hub_interfaz" in c for c in recibidas)
    assert informe.fallos == []


def test_una_interfaz_que_no_existe_se_rechaza_antes_de_abrir_nada(monkeypatch):
    monkeypatch.setattr(mirar, "cual_linux", lambda: "/no/existe/chrome")
    with pytest.raises(ValueError, match="no hay ninguna interfaz «otra»"):
        recorrido.recorrer("http://127.0.0.1:1", interfaz="otra")


def test_la_orden_pasa_la_interfaz_y_los_anchos_que_se_le_piden(monkeypatch):
    pedido = {}

    def falso(base, anchos, **kw):
        pedido.update(base=base, anchos=anchos, **kw)
        return recorrido.Informe(base)

    monkeypatch.setattr(recorrido, "recorrer", falso)
    assert recorrido.main(["--url", "http://127.0.0.1:1", "--interfaz", "nueva", "--anchos", "390,861"]) == 0
    assert pedido["interfaz"] == "nueva" and pedido["anchos"] == (390, 861)
    assert recorrido.main(["--url", "http://127.0.0.1:1"]) == 0 and pedido["interfaz"] is None



def test_con_colores_lleva_tambien_la_cookie_de_ese_juego(sitio_con_panel):
    base, recibidas = sitio_con_panel
    _recorrer_con(base, interfaz="nueva", colores="brasa")
    assert recibidas and all("hub_interfaz=nueva" in c and "hub_colores=brasa" in c for c in recibidas), recibidas


def test_unos_colores_que_no_existen_o_sin_la_nueva_se_rechazan_antes_de_abrir_nada(monkeypatch):
    monkeypatch.setattr(mirar, "cual_linux", lambda: "/no/existe/chrome")
    with pytest.raises(ValueError, match="no hay ningún juego de colores «fosforito»"):
        recorrido.recorrer("http://127.0.0.1:1", interfaz="nueva", colores="fosforito")
    # Con la de siempre la cookie no pinta nada: se mediría otra cosa de la que se dice.
    with pytest.raises(ValueError, match="los colores son de la interfaz nueva"):
        recorrido.recorrer("http://127.0.0.1:1", colores="brasa")


def test_la_orden_pasa_los_colores_y_no_los_admite_sin_la_nueva(monkeypatch):
    pedido = {}

    def falso(base, anchos, **kw):
        pedido.update(base=base, anchos=anchos, **kw)
        return recorrido.Informe(base)

    monkeypatch.setattr(recorrido, "recorrer", falso)
    assert recorrido.main(["--url", "http://127.0.0.1:1", "--interfaz", "nueva", "--colores", "brasa"]) == 0
    assert pedido["colores"] == "brasa"
    assert recorrido.main(["--url", "http://127.0.0.1:1", "--interfaz", "nueva"]) == 0 and pedido["colores"] is None
    with pytest.raises(SystemExit):
        recorrido.main(["--url", "http://127.0.0.1:1", "--colores", "brasa"])
