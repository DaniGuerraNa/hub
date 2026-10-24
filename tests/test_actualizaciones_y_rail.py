"""La pantalla Actualizaciones y el menú agrupado (decisiones 296 y 297)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from arnes_js import ejecutar, script_estatico
from hub import web

GUION = script_estatico("actualizaciones.js")


def test_mientras_actualiza_lee_el_registro_y_al_terminar_lo_dice(tmp_path):
    """El JavaScript, ejecutado (regla dura 11)."""
    r = ejecutar(GUION, tmp_path, {"/api/actualizacion": {
        "ok": True, "en_marcha": False, "rc": 0, "registro": "7/7 · Comprobación\n  ✓ instalada la 0.4.0"}},
        previo="nodo('act').dataset = { enMarcha: 'si' };"
               " location.reload = () => registro.valores.push('recargada');",
        accion="setTimeout(() => registro.valores.push(['resultado', nodo('resultado').textContent],"
               " ['registro', nodo('registro').textContent]), 5);")
    assert r["errores"] == []
    assert "/api/actualizacion" in r["peticiones"]
    assert ["resultado", "terminada"] in r["valores"]
    assert ["registro", "7/7 · Comprobación\n  ✓ instalada la 0.4.0"] in r["valores"]


def test_sin_actualizacion_en_marcha_no_pregunta_nada(tmp_path):
    r = ejecutar(GUION, tmp_path, previo="nodo('act').dataset = { enMarcha: 'no' };")
    assert r["errores"] == []
    assert "/api/actualizacion" not in r["peticiones"]


# ── el menú ───────────────────────────────────────────────────────────────────

@pytest.fixture
def cliente(tmp_path, monkeypatch):
    from hub import db

    def conexion():
        c = db.conectar(tmp_path / "hub.db")
        db.inicializar(c)
        return c

    monkeypatch.setattr(web, "conexion", conexion)
    return TestClient(web.app)


def test_el_menu_va_en_grupos_y_se_abre_el_de_la_pantalla_donde_estas(cliente):
    html = cliente.get("/maquina").text
    assert html.count('class="grupo-rail"') == 5
    assert '<details open class="grupo-rail">' in html
    abierto = html.split('<details open class="grupo-rail">')[1].split("</details>")[0]
    assert 'title="Vigilar"' in abierto and 'href="/maquina" class="enlace aqui"' in abierto


def test_panorama_y_trabajo_quedan_fuera_de_los_grupos(cliente):
    html = cliente.get("/").text
    rail = html.split('<nav class="rail-global">')[1].split("</nav>")[0]
    primer_grupo = rail.index('class="grupo-rail"')
    assert rail.index('href="/trabajo"') < primer_grupo


def test_lo_urgente_se_ve_aunque_su_grupo_este_cerrado(cliente, monkeypatch):
    """Un aviso no puede quedar escondido detrás de un pliegue."""
    from hub import api
    original = api.rail
    monkeypatch.setattr(api, "rail", lambda *a, **k: {**original(*a, **k), "sin_respaldo": 7})
    html = cliente.get("/guia").text
    vigilar = html.split('title="Vigilar"')[1].split("</summary>")[0]
    assert 'class="cuenta urge">7<' in vigilar
