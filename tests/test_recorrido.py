"""`hub.recorrido` sin navegador: lo que tiene que valer aunque falte Playwright.

El recorrido de verdad está en `test_pantallas_navegador.py` y se salta sin
Chromium. Esto corre siempre: que sus listas de excepciones no se queden
muertas al renombrar una ruta, que casa los ids como dice, y que sin el
navegador adecuado se niega en voz alta en vez de medir mal (C-0168).
"""

from __future__ import annotations

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
