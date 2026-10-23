"""Navegante y Reuniones sin preparar: qué falta, dónde, y cómo se consigue (decisión 293).

Quien instala el hub no tiene ninguno de los dos preparado, y la pantalla que
ve entonces es la única que le dice qué son y qué le falta. Por eso se prueba
en ese estado, el de una máquina recién instalada, y no en la de quien
desarrolla el hub, donde todo está ya hecho.
"""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from arnes_js import ejecutar
from hub import componentes, config, reuniones, web


@pytest.fixture
def cliente():
    return TestClient(web.app)


def _laboratorio(raiz):
    """Un laboratorio con todo lo que mide `pasos_navegante`."""
    (raiz / "bin").mkdir(parents=True)
    (raiz / "bin" / "nav").write_text("#!/bin/sh\n")
    (raiz / ".venv").mkdir()
    (raiz / "node_modules").mkdir()
    return raiz


# ───────────────────────────── dónde están ─────────────────────────────


def test_la_variable_manda_sobre_la_copia_del_clon(tmp_path, monkeypatch):
    monkeypatch.setenv("NAV_LAB", str(tmp_path / "otro"))
    assert componentes.carpeta("navegador-lab") == tmp_path / "otro"


def test_sin_variable_se_usa_la_copia_que_viaja_en_el_clon(tmp_path, monkeypatch):
    monkeypatch.delenv("REUNIONES_PROYECTO")
    monkeypatch.setattr(config, "RAIZ_REPO", tmp_path)
    (tmp_path / "componentes" / "reuniones").mkdir(parents=True)
    assert componentes.carpeta("reuniones") == tmp_path / "componentes" / "reuniones"


def test_sin_copia_en_el_clon_se_busca_junto_a_los_proyectos(tmp_path, monkeypatch):
    """Es el caso de quien desarrolla el hub: los componentes son repos suyos."""
    monkeypatch.delenv("NAV_LAB")
    monkeypatch.setattr(config, "RAIZ_REPO", tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path / "casa"))
    assert componentes.carpeta("navegador-lab") == tmp_path / "casa" / "projects" / "navegador-lab"


# ───────────────────────────── qué les falta ─────────────────────────────


def test_un_laboratorio_sin_entorno_no_esta_listo_y_dice_el_siguiente_paso(tmp_path, monkeypatch):
    monkeypatch.setenv("NAV_LAB", str(tmp_path / "lab"))
    pasos = componentes.pasos_navegante()
    assert not componentes.listo(pasos)
    assert [p["id"] for p in pasos if not p["hecho"] and not p["opcional"]][0] == "componente"


def test_xvfb_es_opcional_y_no_impide_estar_listo(tmp_path, monkeypatch):
    monkeypatch.setenv("NAV_LAB", str(_laboratorio(tmp_path / "lab")))
    monkeypatch.setenv("NAV_CHROME", "/usr/bin/chrome-de-mentira")
    monkeypatch.setattr(componentes.shutil, "which", lambda c: None)
    pasos = {p["id"]: p for p in componentes.pasos_navegante()}
    assert not pasos["xvfb"]["hecho"] and pasos["xvfb"]["opcional"]
    assert componentes.listo(list(pasos.values()))


# ───────────────────────────── la carpeta del agente ─────────────────────────────


@pytest.mark.parametrize("windows, wsl", [
    (r"C:\reuniones\agente", "/mnt/c/reuniones/agente"),
    (r"d:\Mis cosas\agente\\", "/mnt/d/Mis cosas/agente"),
])
def test_una_ruta_de_windows_se_ve_desde_wsl_en_su_unidad(windows, wsl):
    assert str(reuniones.a_wsl(windows)) == wsl


@pytest.mark.parametrize("mala", [
    "/etc/passwd", r"C:\\", r"C:\a\..\b", r"C:\a/..\b", r"C:\a\b:c", "", r"\\servidor\x",
])
def test_una_ruta_que_no_es_una_carpeta_de_windows_no_se_acepta(mala):
    """Llega de un formulario y es donde el hub va a escribir: se valida entera."""
    with pytest.raises(ValueError):
        reuniones.a_wsl(mala)


def test_sin_ajustes_el_agente_esta_donde_estuvo_siempre(monkeypatch):
    """Una instalación de antes de poder elegir la carpeta sigue funcionando."""
    monkeypatch.delenv("REUNIONES_AGENTE")
    monkeypatch.delenv("REUNIONES_RAIZ")
    assert reuniones.carpeta_agente() == reuniones.a_wsl(reuniones.POR_OMISION_WINDOWS)
    assert reuniones.raiz() == reuniones.carpeta_agente().parent / "grabaciones"


def test_la_carpeta_elegida_manda_y_las_grabaciones_van_a_su_lado(monkeypatch):
    monkeypatch.delenv("REUNIONES_AGENTE")
    monkeypatch.delenv("REUNIONES_RAIZ")
    reuniones.guardar_carpeta_windows(r"E:\grabar\agente")
    assert str(reuniones.carpeta_agente()) == "/mnt/e/grabar/agente"
    assert str(reuniones.raiz()) == "/mnt/e/grabar/grabaciones"


def _agente_de_origen(tmp_path, monkeypatch):
    origen = tmp_path / "procesado" / "agente"
    origen.mkdir(parents=True)
    for nombre in reuniones.ARCHIVOS_AGENTE:
        (origen / nombre).write_text(f"contenido de {nombre}\n", encoding="utf-8")
    (origen / "iniciar.cmd").write_text(
        "@echo off\nset REUNIONES_HUB=http://127.0.0.1:8787\ncd /d \"%~dp0\"\n", encoding="utf-8")
    monkeypatch.setenv("REUNIONES_PROYECTO", str(tmp_path / "procesado"))
    destino = tmp_path / "unidad" / "reuniones" / "agente"
    (tmp_path / "unidad").mkdir()
    monkeypatch.setenv("REUNIONES_AGENTE", str(destino))
    return destino


def test_copiar_el_agente_lo_deja_con_el_puerto_de_este_hub_y_saltos_de_windows(tmp_path, monkeypatch):
    destino = _agente_de_origen(tmp_path, monkeypatch)
    monkeypatch.setattr(config, "WEB_PORT", 8799)

    reuniones.copiar_agente()

    iniciar = (destino / "iniciar.cmd").read_bytes()
    assert b"set REUNIONES_HUB=http://127.0.0.1:8799\r\n" in iniciar
    assert b"\n" not in iniciar.replace(b"\r\n", b"")
    assert all((destino / n).exists() for n in reuniones.ARCHIVOS_AGENTE)


def test_copiar_otra_vez_el_agente_no_toca_su_llave(tmp_path, monkeypatch):
    destino = _agente_de_origen(tmp_path, monkeypatch)
    reuniones.copiar_agente()
    (destino / "token").write_text("la-llave")

    reuniones.copiar_agente()

    assert (destino / "token").read_text() == "la-llave"


def test_sin_la_unidad_montada_no_se_copia_y_se_dice_por_que(tmp_path, monkeypatch):
    _agente_de_origen(tmp_path, monkeypatch)
    monkeypatch.setenv("REUNIONES_AGENTE", str(tmp_path / "no-hay" / "reuniones" / "agente"))
    with pytest.raises(ValueError, match="unidad de Windows"):
        reuniones.copiar_agente()


def test_un_agente_que_llama_sin_llave_cuenta_como_instalado(monkeypatch):
    """Lo que le falta es la llave, que es otro paso: no reinstalarlo."""
    reuniones.llave_rechazada()
    pasos = {p["id"]: p for p in reuniones.preparacion()["pasos"]}
    assert pasos["instalado"]["hecho"]
    assert not pasos["llave"]["hecho"]


# ───────────────────────────── las pantallas ─────────────────────────────


def test_navegante_sale_en_el_rail_aunque_no_este_preparado(cliente):
    html = cliente.get("/guia").text
    assert 'href="/navegante"' in html and 'href="/reuniones"' in html


def test_navegante_sin_preparar_enseña_sus_pasos_y_no_sus_mandos(cliente):
    html = cliente.get("/navegante").text
    assert 'id="preparar"' in html
    assert 'name="nombre" value="navegador-lab"' in html
    assert "Te pregunta" not in html


def test_reuniones_sin_preparar_pide_la_carpeta_y_no_ofrece_grabar(cliente):
    html = cliente.get("/reuniones").text
    assert 'id="preparar"' in html
    assert 'action="/reuniones/carpeta"' in html
    assert 'action="/reuniones/copiar-agente"' in html
    assert "agente desconectado" not in html
    assert 'value="grabar"' not in html


def test_guardar_la_carpeta_del_agente_vuelve_diciendo_donde_se_ve(cliente, monkeypatch):
    monkeypatch.delenv("REUNIONES_AGENTE")
    monkeypatch.delenv("REUNIONES_RAIZ")
    r = cliente.post("/reuniones/carpeta", data={"ruta": r"C:\reuniones\agente"},
                     headers={"origin": "http://127.0.0.1:8787"}, follow_redirects=False)
    assert r.status_code == 303
    assert reuniones.carpeta_windows() == r"C:\reuniones\agente"


def test_una_carpeta_mala_no_se_guarda(cliente):
    cliente.post("/reuniones/carpeta", data={"ruta": "/etc"},
                 headers={"origin": "http://127.0.0.1:8787"}, follow_redirects=False)
    assert reuniones.carpeta_windows() is None


def test_preparar_abre_una_ventana_con_el_encargo_escrito_y_sin_enter(cliente, tmp_path, monkeypatch):
    """El tercer caso de la regla dura 15: la ventana nace con el texto, y el
    Enter lo pone la persona."""
    from hub import slots, tmux

    lab = _laboratorio(tmp_path / "lab")
    monkeypatch.setenv("NAV_LAB", str(lab))
    abiertas = []
    monkeypatch.setattr(slots, "abrir_en", lambda ruta, nombre, sesion, texto: abiertas.append(
        (ruta, nombre, sesion, texto)) or "%9")
    monkeypatch.setattr(tmux, "listar_paneles", lambda: [{"pane_id": "%9", "window_idx": 4}])

    r = cliente.post("/componentes/preparar", data={"nombre": "navegador-lab"},
                     headers={"origin": "http://127.0.0.1:8787"}, follow_redirects=False)

    assert r.headers["location"] == "/trabajo?session=hub&ventana=4"
    ruta, nombre, sesion, texto = abiertas[0]
    assert ruta == str(lab) and sesion == "hub"
    assert "claude" in texto and "no uses sudo" in texto
    assert not texto.endswith("\n")


def test_preparar_algo_que_no_es_un_componente_no_abre_nada(cliente, monkeypatch):
    from hub import slots

    monkeypatch.setattr(slots, "abrir_en", lambda *a: pytest.fail("no debía abrir nada"))
    r = cliente.post("/componentes/preparar", data={"nombre": "../../etc"},
                     headers={"origin": "http://127.0.0.1:8787"}, follow_redirects=False)
    assert r.status_code == 303


# ───────────────────────────── el script de una reunión ─────────────────────────────


def test_copiar_ruta_para_claude_copia_las_rutas_y_lo_dice(cliente, tmp_path, monkeypatch):
    """El `<script>` en línea de reunion.html, ejecutado (regla dura 11)."""
    import json

    raiz = tmp_path / "grabaciones"
    d = raiz / "20261023-100000"
    d.mkdir(parents=True)
    (d / "meta.json").write_text(json.dumps({"inicio": 0, "fin": 60}))
    (d / "resumen.json").write_text(json.dumps({"titulo": "Revisión"}))
    monkeypatch.setenv("REUNIONES_RAIZ", str(raiz))

    html = cliente.get(f"/reuniones/{d.name}").text
    guion = re.findall(r"<script>\s*(.*?)\s*</script>", html, re.S)[-1]
    salida = ejecutar(guion, tmp_path, accion="""
      const b = nodo('copiar-ruta');
      b.dataset = { texto: 'Reunión «Revisión»' };
      b.disparar('click');
      setTimeout(() => registro.valores.push(['aviso', nodo('copiada').textContent]), 5);
    """)
    assert salida["portapapeles"] == ["Reunión «Revisión»"]
    assert ["aviso", "Copiada: pégala en la sesión de Claude"] in salida["valores"]
