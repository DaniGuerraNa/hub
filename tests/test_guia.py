"""La guía de primeros pasos y el mapa de pantallas (decisión 271).

Lo que se protege: que «hecho» salga del estado real y no de una casilla
marcada a mano (regla dura 13), que el mapa no apunte a pantallas que ya no
existen, y que «Guíame» de verdad abra el chat con la pregunta.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from hub import api, db, guia, web


def _proyecto(con, pid, tipo="proyecto"):
    con.execute("INSERT INTO proyecto (id, nombre, asiento, guardrail, tipo) VALUES (?,?,?,?,?)",
                (pid, pid.title(), f"/tmp/{pid}", "ask", tipo))
    con.commit()


def _por_id(pasos):
    return {p["id"]: p for p in pasos}


def test_en_un_hub_recien_instalado_nada_esta_hecho_y_el_siguiente_es_el_asistente(con):
    pasos = _por_id(guia.pasos(con, [], {}))

    assert not any(p["hecho"] for p in pasos.values())
    assert pasos["asistente"]["siguiente"] is True
    # Sin asistente, «Guíame» sólo podría fallar: no se ofrece.
    assert all(p["pregunta"] is None for p in pasos.values())


def test_los_pasos_se_marcan_por_lo_que_hay_de_verdad(con):
    _proyecto(con, "asistente", "asistente")
    _proyecto(con, "mi-app")
    con.execute("INSERT INTO slot (proyecto_id, nombre, status, creado_en) "
                "VALUES ('mi-app', 'bug del login', 'activo', '2026-10-16')")
    con.commit()

    pasos = _por_id(guia.pasos(con, [{"pane_id": "%3", "slot_id": None}], {"mi-app": "nada"}))

    assert [k for k, p in pasos.items() if p["hecho"]] == ["asistente", "proyecto", "slot"]
    assert pasos["trabajo"]["siguiente"] is True
    assert pasos["slot"]["enlace"]["ruta"] == "/proyecto/mi-app#slots"
    assert pasos["trabajo"]["pregunta"]          # con asistente, sí se ofrece
    assert pasos["orquestador"]["hecho"] is False  # «nada» no es alcance


def test_el_asistente_no_cuenta_como_tu_primer_proyecto(con):
    _proyecto(con, "asistente", "asistente")

    assert _por_id(guia.pasos(con, [], {}))["proyecto"]["hecho"] is False


def test_cada_pantalla_del_mapa_existe_de_verdad():
    """Si una pantalla cambia de ruta, el mapa que lee el asistente no puede
    seguir mandando a la vieja."""
    rutas = {r.path for r in web.app.routes if "GET" in getattr(r, "methods", set())}
    for p in guia.PANTALLAS:
        ruta = p["ruta"].replace("<id>", "{proyecto_id}")
        assert ruta in rutas, p["ruta"]


def test_cada_pantalla_del_raíl_está_en_el_mapa():
    plantilla = (Path(web.__file__).parent / "templates" / "base.html").read_text(encoding="utf-8")
    en_mapa = {p["ruta"] for p in guia.PANTALLAS} | {"/guia"}
    import re
    raíl = set(re.findall(r"\('(/[a-z]*)', '[a-z]+', '[^']+', '[a-z]+'\)", plantilla))
    assert raíl and raíl <= en_mapa, raíl - en_mapa


@pytest.fixture
def cliente(tmp_path, monkeypatch):
    def conexion():
        c = db.conectar(tmp_path / "hub.db")
        db.inicializar(c)
        return c
    monkeypatch.setattr(web, "conexion", conexion)
    return TestClient(web.app), conexion


def test_la_pantalla_se_pinta_con_los_pasos_y_el_mapa(cliente):
    http, conexion = cliente
    c = conexion()
    _proyecto(c, "asistente", "asistente")
    c.close()

    pagina = http.get("/guia")

    assert pagina.status_code == 200
    assert "Primeros pasos" in pagina.text and "0 de 5 hechos" not in pagina.text
    assert "1 de 5 hechos" in pagina.text
    assert 'data-guiame="Quiero registrar mi primer proyecto' in pagina.text
    assert 'href="/respaldo"' in pagina.text and 'src="/static/guia.js"' in pagina.text
    assert http.get("/api/guia").json()["total"] == 5


@pytest.mark.skipif(not shutil.which("node"), reason="hace falta node")
def test_guiame_abre_el_chat_con_la_pregunta_del_paso():
    """Se ejecuta el script (regla dura 11): un `data-guiame` mal leído no da
    ningún error, simplemente el botón no hace nada."""
    guion = Path(web.__file__).parent / "static" / "guia.js"
    programa = """
      let oyente; const preguntas = [];
      global.document = { addEventListener: (ev, f) => { oyente = f; } };
      global.window = { HubAsistente: { preguntar: (t) => preguntas.push(t) } };
      require(%s);
      oyente({ target: { closest: () => ({ dataset: { guiame: '¿Qué es un slot?' } }) } });
      oyente({ target: { closest: () => null } });
      console.log(JSON.stringify(preguntas));
    """ % json.dumps(str(guion))
    salida = subprocess.run(["node", "-e", programa], capture_output=True, text=True,
                            timeout=20, check=True).stdout

    assert json.loads(salida) == ["¿Qué es un slot?"]


def test_los_proyectos_de_ejemplo_del_registro_no_cuentan_como_tuyos(con, tmp_path):
    """🔴 Sala limpia, 16-oct: el registro recién instalado trae «mi-proyecto» y
    «otro-proyecto» con rutas inventadas, y el paso salía hecho sin haber
    registrado nada."""
    real = tmp_path / "mi-tienda"
    real.mkdir()
    for pid, asiento in (("mi-proyecto", "~/dev/mi-proyecto"), ("otro-proyecto", "~/trabajo/otro")):
        con.execute("INSERT INTO proyecto (id, nombre, asiento, guardrail) VALUES (?,?,?,?)",
                    (pid, pid, asiento, "ask"))
    con.commit()

    paso = _por_id(api.guia(con)["pasos"])["proyecto"]
    assert paso["hecho"] is False
    assert "hay 2 cuya carpeta no existe (mi-proyecto, otro-proyecto)" in paso["como"]
    assert api.rail(con)["total_proyectos"] == 0      # y la portada sí enseña la guía

    con.execute("INSERT INTO proyecto (id, nombre, asiento, guardrail) VALUES ('mi-tienda','T',?,'ask')",
                (str(real),))
    con.commit()
    assert _por_id(api.guia(con)["pasos"])["proyecto"]["hecho"] is True
    assert api.rail(con)["total_proyectos"] == 1
