import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
import yaml
from playwright.sync_api import sync_playwright

from conftest import RAIZ, mutaciones
from test_guardian import entrar

FLUJOS = RAIZ / "flujos"


@pytest.fixture
def datos(tmp_path, monkeypatch):
    """Los datos del laboratorio (vigilancia, salidas) a una carpeta del test."""
    d = tmp_path / "datos"
    monkeypatch.setenv("HOME", str(tmp_path / "casa"))
    import navegador.guardian as g, navegador.reproducir as r
    monkeypatch.setattr(g, "DATOS", d)
    monkeypatch.setattr(r, "SALIDAS", d / "salidas")
    return d


def logueado(chrome, consola):
    with sync_playwright() as p:
        entrar(p.chromium.connect_over_cdp(chrome["cdp"]).contexts[0].new_page(), consola["url"])


def guardian_proc(chrome, consola, tmp_path, datos, modo="lectura"):
    from conftest import politica
    env = {**os.environ, "HOME": str(tmp_path / "casa")}
    # el guardián calcula DATOS desde HOME
    p = subprocess.Popen([sys.executable, "-m", "navegador.guardian", "--cdp", chrome["cdp"],
                          "--politica", str(politica(tmp_path, consola["url"], modo)),
                          "--registro", str(tmp_path / "reg.jsonl"), "--aprobaciones", str(tmp_path / "ap")],
                         cwd=RAIZ, env=env)
    vig = tmp_path / "casa/.local/share/navegador-lab/vigilancia"
    fin = time.time() + 10
    while time.time() < fin and not list(vig.glob("*.json")):
        time.sleep(0.1)
    return p


def test_el_mapa_de_api_gateway_recorre_cada_api_y_trae_sus_rutas(chrome, consola, tmp_path, datos, monkeypatch):
    import navegador.guardian as g
    monkeypatch.setattr(g, "DATOS", tmp_path / "casa/.local/share/navegador-lab")
    from navegador.reproducir import correr
    gp = guardian_proc(chrome, consola, tmp_path, datos)
    try:
        logueado(chrome, consola)
        ok, salida = correr(yaml.safe_load((FLUJOS / "apigateway-mapa.yml").read_text()),
                            {"base": consola["url"]}, chrome["cdp"])
    finally:
        gp.terminate(); gp.wait()
    assert ok, (salida / "fallo.json").read_text()
    r = json.loads((salida / "resultado.json").read_text())
    assert [d["Nombre"] for d in r["datos"]["detalle"]] == ["pedidos-api", "usuarios-http", "notificaciones-ws"]
    pedidos = r["datos"]["detalle"][0]
    assert pedidos["etapas"] == "dev, prod"
    assert {"Método": "DELETE", "Ruta": "/pedidos/{id}", "Integración": "lambda:pedidos-cancelar"} in pedidos["rutas"]
    assert mutaciones(consola) == []


def test_la_consulta_de_logs_insights_devuelve_las_filas_que_da_el_motor(chrome, consola, tmp_path, datos, monkeypatch):
    import navegador.guardian as g
    monkeypatch.setattr(g, "DATOS", tmp_path / "casa/.local/share/navegador-lab")
    from navegador.reproducir import correr
    gp = guardian_proc(chrome, consola, tmp_path, datos)
    try:
        logueado(chrome, consola)
        ok, salida = correr(yaml.safe_load((FLUJOS / "logs-insights-consulta.yml").read_text()),
                            {"base": consola["url"], "grupo": "/aws/lambda/pedidos-crear",
                             "consulta": "stats count(*) by bin(30m)"}, chrome["cdp"])
    finally:
        gp.terminate(); gp.wait()
    assert ok, (salida / "fallo.json").read_text()
    r = json.loads((salida / "resultado.json").read_text())
    assert r["datos"]["resumen"] == "Completada: 4 registros de 120 escaneados"
    assert [f["count(*)"] for f in r["datos"]["filas"]] == ["30"] * 4


def test_sin_guardian_vigilando_ese_navegador_no_corre(chrome, consola, datos):
    from navegador.reproducir import correr
    with pytest.raises(SystemExit, match="No hay guardián"):
        correr({"nombre": "x", "pasos": []}, {}, chrome["cdp"])


def test_si_un_paso_no_encuentra_su_elemento_se_para_y_deja_lo_que_veia(chrome, consola, tmp_path, datos, monkeypatch):
    import navegador.guardian as g
    monkeypatch.setattr(g, "DATOS", tmp_path / "casa/.local/share/navegador-lab")
    from navegador.reproducir import correr
    gp = guardian_proc(chrome, consola, tmp_path, datos)
    flujo = {"nombre": "roto", "pasos": [
        {"ir": consola["url"] + "/apigateway/main/apis"},
        {"pulsar": {"rol": "button", "nombre": "Botón que ya no existe"}},
        {"pulsar": {"rol": "button", "nombre": "Eliminar"}}]}
    try:
        logueado(chrome, consola)
        ok, salida = correr(flujo, {}, chrome["cdp"], espera_ms=1500)
    finally:
        gp.terminate(); gp.wait()
    assert not ok
    f = json.loads((salida / "fallo.json").read_text())
    assert f["paso"] == 2
    assert "Botón que ya no existe" in json.dumps(f["definicion"], ensure_ascii=False)
    assert 'table "APIs"' in f["lo_que_se_veia"]
    assert (salida / "fallo.png").exists()


def test_grabar_a_una_persona_produce_un_flujo_que_se_puede_repetir(chrome, consola, tmp_path, datos, monkeypatch):
    """De punta a punta: playwright-cli graba mientras «el dueño» (Playwright, que manda
    eventos de entrada reales por CDP) hace una consulta; `nav grabar parar` la
    convierte, y el flujo resultante se repite con otro grupo de logs."""
    env = {**os.environ, "NAV_CDP": chrome["cdp"], "NAV_FLUJOS": str(tmp_path / "flujos"),
           "HOME": str(tmp_path / "casa")}
    nav = [sys.executable, "-m", "navegador.cli"]
    logueado(chrome, consola)
    r = subprocess.run(nav + ["grabar", "empezar"], cwd=RAIZ, env=env, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr
    with sync_playwright() as p:
        pg = p.chromium.connect_over_cdp(chrome["cdp"]).contexts[0].pages[0]
        pg.goto(consola["url"] + "/cloudwatch/home#logsV2:logs-insights")
        pg.get_by_label("/aws/lambda/pedidos-crear").check()
        pg.get_by_label("Editor de consultas").click()
        pg.keyboard.press("Control+a")
        pg.keyboard.type("fields @message | filter @message like /ERROR/ | limit 3")
        pg.get_by_role("button", name="Ejecutar consulta").click()
        pg.get_by_text("Completada").wait_for()
    r = subprocess.run(nav + ["grabar", "parar", "errores", "-p", f"base={consola['url']}",
                              "-p", "grupo=/aws/lambda/pedidos-crear"],
                       cwd=RAIZ, env=env, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr
    flujo = yaml.safe_load((tmp_path / "flujos/errores.yml").read_text())
    assert set(flujo["parametros"]) == {"base", "grupo"}
    flujo["pasos"] += [{"esperar": {"texto": "Completada"}}, {"extraer": {"tabla": "Resultados", "a": "filas"}}]
    import navegador.guardian as g
    monkeypatch.setattr(g, "DATOS", tmp_path / "casa/.local/share/navegador-lab")
    from navegador.reproducir import correr
    gp = guardian_proc(chrome, consola, tmp_path, datos)
    try:
        ok, salida = correr(flujo, {"base": consola["url"], "grupo": "/aws/lambda/usuarios-obtener"}, chrome["cdp"])
    finally:
        gp.terminate(); gp.wait()
    assert ok, (salida / "fallo.json").read_text()
    filas = json.loads((salida / "resultado.json").read_text())["datos"]["filas"]
    assert len(filas) == 3 and all("ERROR" in f["@message"] for f in filas)


def test_un_flujo_compuesto_corre_sus_fragmentos_en_orden_y_junta_lo_extraido(chrome, consola, tmp_path, datos, monkeypatch):
    import navegador.guardian as g
    monkeypatch.setattr(g, "DATOS", tmp_path / "casa/.local/share/navegador-lab")
    from navegador.reproducir import correr
    gp = guardian_proc(chrome, consola, tmp_path, datos)
    flujo = {"nombre": "compuesto", "pasos": [
        {"usar": {"flujo": "lab/apigw-lista", "con": {"base": consola["url"]}}},
        {"usar": {"flujo": "lab/apigw-detalle", "con": {"api": "notificaciones-ws"}, "a": "detalle"}}]}
    try:
        logueado(chrome, consola)
        ok, salida = correr(flujo, {}, chrome["cdp"])
    finally:
        gp.terminate(); gp.wait()
    assert ok, (salida / "fallo.json").read_text()
    d = json.loads((salida / "resultado.json").read_text())["datos"]
    assert len(d["apis"]) == 3
    assert d["detalle"]["etapas"] == "prod"
    assert [r["Ruta"] for r in d["detalle"]["rutas"]] == ["$connect", "$default"]
