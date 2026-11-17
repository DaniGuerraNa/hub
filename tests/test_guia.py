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


def _pasos(con, paneles=(), niveles=None):
    """Los pasos con lo que `api.guia` les pasaría de la base (C-0056)."""
    return _por_id(guia.pasos(api.listar_proyectos(con, incluir_archivados=True), api.slots_activos(con),
                              api.repos_de(con), list(paneles), niveles or {}))


def test_en_un_hub_recien_instalado_nada_esta_hecho_y_el_siguiente_es_el_asistente(con):
    pasos = _pasos(con)

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

    pasos = _pasos(con, [{"pane_id": "%3", "slot_id": None}], {"mi-app": "nada"})

    assert [k for k, p in pasos.items() if p["hecho"]] == ["asistente", "proyecto", "slot"]
    assert pasos["trabajo"]["siguiente"] is True
    assert pasos["slot"]["enlace"]["ruta"] == "/proyecto/mi-app#slots"
    assert pasos["trabajo"]["pregunta"]          # con asistente, sí se ofrece
    assert pasos["orquestador"]["hecho"] is False  # «nada» no es alcance


def test_el_asistente_no_cuenta_como_tu_primer_proyecto(con):
    _proyecto(con, "asistente", "asistente")

    assert _pasos(con)["proyecto"]["hecho"] is False


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


def test_cada_pantalla_del_raíl_nuevo_está_en_el_mapa():
    """El raíl de la interfaz nueva (C-0169) sale de `navegacion.SECCIONES`, no
    de la plantilla: lo que se añada allí también tiene que estar explicado.
    Las dos que el mapa cuenta dentro de su pantalla madre se declaran aquí."""
    from hub import navegacion
    dentro_de_otra = {"/orquestador/permisos": "se explica en Orquestador",
                      "/secretario/monitor": "se explica en Secretario"}
    en_mapa = {p["ruta"] for p in guia.PANTALLAS} | {"/guia"}
    del_rail = {p["ruta"].split("?")[0] for s in navegacion.SECCIONES for p in s["pantallas"]}
    assert del_rail - en_mapa == set(dentro_de_otra), del_rail - en_mapa - set(dentro_de_otra)


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


def test_la_guia_cuenta_los_proyectos_como_el_rail_archivados_incluidos(con, tmp_path):
    """La guía sale en la portada según lo que cuenta el raíl: si contaran
    distinto, la portada la enseñaría con «registra tu primer proyecto» ya
    hecho, o al revés. Al pasar la lectura a `api.py` (C-0056) no podía
    perderse el archivado por el camino."""
    viejo = tmp_path / "viejo"
    viejo.mkdir()
    con.execute("INSERT INTO proyecto (id, nombre, asiento, guardrail, status) VALUES ('viejo','V',?,'ask','archivado')",
                (str(viejo),))
    con.commit()

    assert api.rail(con)["total_proyectos"] == 1
    assert _por_id(api.guia(con)["pasos"])["proyecto"]["hecho"] is True


# ── Donde la voz es el secretario, no se habla del asistente (C-0355) ────────

def _secretario_como_voz(nombre="Atenea"):
    """El secretario en todas las pantallas y con su nombre, en el HUB_HOME de
    pruebas: lo que `api.rail` lee para decidir quién habla."""
    from hub.secretario import memoria, personaje
    con = memoria.conectar()
    try:
        personaje.nombrar(con, nombre)
    finally:
        con.close()
    (memoria.carpeta() / "secretario.yml").write_text("en_todo_el_hub: true\n", encoding="utf-8")


def texto_visible(html: str) -> str:
    """Lo que se lee en la página: el texto y los rótulos (`title`,
    `aria-label`, `placeholder`), sin scripts, estilos ni comentarios."""
    import re
    rotulos = " ".join(re.findall(r'(?:title|aria-label|placeholder)="([^"]*)"', html))
    sin = re.sub(r"<(script|style)\b.*?</\1>|<!--.*?-->", " ", html, flags=re.S | re.I)
    return re.sub(r"<[^>]+>", " ", sin) + " " + rotulos


def test_con_el_secretario_como_voz_la_guia_no_manda_a_buscar_al_asistente(cliente):
    """«Instala el asistente» y «Guíame para que el asistente te acompañe»
    donde el asistente está retirado: mandaba a buscar algo que no está."""
    http, conexion = cliente
    c = conexion()
    _proyecto(c, "asistente", "asistente")     # declarado, pero retirado
    _proyecto(c, "mi-app")
    c.close()
    _secretario_como_voz()

    pagina = http.get("/guia").text
    visible = " ".join(texto_visible(pagina).split())

    assert "asistente" not in visible.lower()
    assert "Conoce a Atenea" in visible and "para que Atenea te acompañe" in visible
    assert 'data-guiame="Quiero registrar mi primer proyecto' in pagina   # «Guíame» lo abre él


def test_con_el_secretario_su_paso_esta_hecho_y_guiame_se_ofrece(con):
    pasos = _por_id(guia.pasos(api.listar_proyectos(con, incluir_archivados=True), [], [], [], {},
                               secretario="Atenea"))

    assert "asistente" not in pasos
    assert pasos["secretario"]["titulo"] == "Conoce a Atenea" and pasos["secretario"]["hecho"] is True
    assert pasos["proyecto"]["siguiente"] is True and pasos["proyecto"]["pregunta"]
    assert "a Atenea" in pasos["proyecto"]["como"]


def test_con_el_secretario_de_nombre_por_omision_se_le_llama_el_secretario(con):
    pasos = _por_id(guia.pasos([], [], [], [], {}, secretario="Secretario"))

    assert pasos["secretario"]["titulo"] == "Conoce al secretario"
    assert "al secretario" in pasos["proyecto"]["como"]
