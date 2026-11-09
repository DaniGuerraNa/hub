"""Los talleres (C-0220, decisión 391): cada sesión con agente es un taller."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import arnes_webp
import pytest

from hub import api, avisos, db, talleres, transcripts, tui
from hub.secretario import personaje

ESTATICOS = Path(talleres.__file__).parent / "static"
SESION = "11111111-2222-3333-4444-555555555555"
TRABAJANDO, QUIETA = "⠋ Construyendo el taller", "✳ Construyendo el taller"


# ── la tabla ────────────────────────────────────────────────────────────────

def test_cada_rol_que_puede_ser_subagente_tiene_su_estacion():
    assert set(talleres.ESTACION_DE_ROL) | talleres.NO_SON_SUBAGENTES == set(personaje.ROLES)
    assert not set(talleres.ESTACION_DE_ROL) & talleres.NO_SON_SUBAGENTES


def test_ninguna_estacion_es_un_decorado_al_que_no_lleva_ningun_rol():
    assert set(talleres.ESTACION_DE_ROL.values()) == set(talleres.ESTACIONES)


def test_un_rol_que_no_esta_en_la_tabla_va_a_la_entrada():
    assert talleres.estacion_de("rol-que-no-existe") == "entrada"


def test_cada_estacion_tiene_sitio_dentro_del_escenario_y_al_menos_un_hueco():
    for nombre, e in talleres.ESTACIONES.items():
        assert e["huecos"] and e["huecos"][0] == [0, 0], nombre
        for dx, dy in e["huecos"]:
            assert 0 < e["x"] + dx < 100 and 0 < e["y"] + dy <= 100, nombre


def test_otro_va_neutro_y_nunca_con_una_skin_que_no_le_toca():
    assert talleres.FIGURA_DE_ROL["otro"] is None


def test_las_tablas_por_rol_son_las_mismas_para_todos_los_roles():
    """Nombre, balanceo y rana van en `talleres.py` y no en el JS: una
    segunda tabla en la página se quedaría vieja (389)."""
    roles = set(talleres.ESTACION_DE_ROL)
    assert set(talleres.FIGURA_DE_ROL) == set(talleres.NOMBRE_DE_ROL) == set(talleres.OFICIO_DE_ROL) == roles
    escena = talleres.escena()
    assert escena["nombres"] == talleres.NOMBRE_DE_ROL and escena["oficios"] == talleres.OFICIO_DE_ROL


# ── las imágenes ────────────────────────────────────────────────────────────

def test_cada_rana_que_se_pinta_tiene_su_imagen_y_no_sobra_ninguna():
    ranas = {p.stem for p in (talleres.CARPETA / "ranas").glob("*.webp")}
    assert ranas == set(talleres.RANAS)


def test_los_cuadros_de_quien_los_tiene_existen_y_la_herrera_sabe_donde_estaba_su_yunque():
    cuadros = talleres.cuadros()
    assert talleres.SESION in cuadros
    for pid, c in cuadros.items():
        for nombre in c["cuadros"]:
            assert (talleres.CARPETA / "cuadros" / pid / f"{nombre}.webp").is_file(), (pid, nombre)
    objeto = cuadros[talleres.SESION]["objeto"]
    assert 0 < objeto["v_arriba"] < objeto["v_base"] <= 1


def test_las_imagenes_no_llevan_nada_que_no_sea_imagen():
    """Los PNG generados traen C2PA; lo publicado no lee binarios (C-0188)."""
    for webp in talleres.CARPETA.rglob("*.webp"):
        assert {n for n, _ in arnes_webp.trozos(webp.read_bytes())} <= arnes_webp.DE_IMAGEN, webp


# ── qué agente corre ────────────────────────────────────────────────────────

def test_reconoce_el_agente_por_el_comando_y_a_claude_tambien_por_su_glifo():
    assert tui.reconocer("claude") is tui.CLAUDE
    assert tui.reconocer("codex") is tui.CODEX
    assert tui.reconocer("node", QUIETA) is tui.CLAUDE
    assert tui.reconocer("node", "un título cualquiera") is None


def test_una_shell_con_el_glifo_heredado_no_es_un_agente():
    """tmux-resurrect devuelve el título de antes a un bash recién nacido (261)."""
    assert tui.reconocer("bash", QUIETA) is None


def test_detectar_aplica_la_misma_regla_y_solo_pide_el_titulo_si_hace_falta(monkeypatch):
    pedidos = []
    monkeypatch.setattr(tui.tmux, "titulo_panel", lambda p: pedidos.append(p) or QUIETA)
    monkeypatch.setattr(tui.tmux, "comando_de_panel", lambda p: "claude")
    assert tui.detectar("%1") is tui.CLAUDE and pedidos == []
    monkeypatch.setattr(tui.tmux, "comando_de_panel", lambda p: "bash")
    assert tui.detectar("%1") is None and pedidos == []
    monkeypatch.setattr(tui.tmux, "comando_de_panel", lambda p: "node")
    assert tui.detectar("%1") is tui.CLAUDE and pedidos == ["%1"]


# ── los datos ───────────────────────────────────────────────────────────────

def _subagentes(tmp_path, monkeypatch, cwd: str, *agentes: tuple[str, str, str]) -> None:
    monkeypatch.setattr(transcripts, "TRANSCRIPTS", tmp_path / "projects")
    carpeta = tmp_path / "projects" / transcripts.slug_de(cwd)
    sub = carpeta / SESION / "subagents"
    sub.mkdir(parents=True)
    (carpeta / f"{SESION}.jsonl").write_text("{}\n")
    usa = {"type": "assistant", "message": {"stop_reason": "tool_use",
                                            "content": [{"type": "tool_use", "id": "t", "name": "Read"}]}}
    for ident, tipo, que in agentes:
        (sub / f"agent-{ident}.meta.json").write_text(json.dumps({"agentType": tipo, "description": que}))
        (sub / f"agent-{ident}.jsonl").write_text(json.dumps(usa) + "\n")


def _muestra(con, *paneles: dict) -> None:
    sid = con.execute("INSERT INTO snapshot (tomado_en, server_pid) VALUES ('2026-11-09T10:00:00+00:00', 1)").lastrowid
    for p in paneles:
        fila = {"snapshot_id": sid, "session": "trabajo", "window_idx": 1, "pane_idx": 0, "cwd": "/srv/demo", **p}
        con.execute(f"INSERT INTO panel ({', '.join(fila)}) VALUES ({', '.join('?' * len(fila))})", tuple(fila.values()))
    con.commit()


def test_cada_sesion_con_agente_es_un_taller_con_su_estado(con):
    _muestra(con,
             {"pane_id": "%1", "comando": "claude", "titulo": TRABAJANDO},
             {"pane_id": "%2", "comando": "claude", "titulo": QUIETA},
             {"pane_id": "%3", "comando": "claude", "titulo": QUIETA},
             {"pane_id": "%4", "comando": "codex", "titulo": "codex"},
             {"pane_id": "%5", "comando": "bash", "titulo": QUIETA})
    avisos.anotar(con, "%3", "preguntando", "2026-11-09T10:00:00+00:00")
    datos = api.talleres(con)
    estados = {t["clave"].split(":")[0]: t["estado"] for t in datos["talleres"]}
    assert estados == {"%1": "trabajando", "%2": "quieta", "%3": "espera", "%4": "neutro"}
    assert datos["talleres"][0]["clave"].startswith("%3"), "lo que te espera va primero"
    assert datos["tomado_en"] and datos["escena"]["fondo"]


def test_espera_tu_si_solo_si_el_titulo_tambien_dice_que_esta_quieta(con):
    """El relé midió el cuadro de permisos, pero si ya vuelve a trabajar, trabaja."""
    _muestra(con, {"pane_id": "%1", "comando": "claude", "titulo": TRABAJANDO})
    avisos.anotar(con, "%1", "preguntando", "2026-11-09T10:00:00+00:00")
    assert api.talleres(con)["talleres"][0]["estado"] == "trabajando"


def test_preguntando_da_los_paneles_que_el_rele_vio_pidiendo_permiso(con):
    avisos.anotar(con, "%1", "preguntando", "2026-11-09T10:00:00+00:00")
    avisos.anotar(con, "%2", "detenido", "2026-11-09T10:00:00+00:00")
    assert avisos.preguntando(con) == {"%1"}


def test_sus_subagentes_vivos_llevan_su_rol_su_estacion_y_su_id(con, tmp_path, monkeypatch):
    _subagentes(tmp_path, monkeypatch, "/srv/demo",
                ("a1", "investigador-web", "Precios de vuelos"),
                ("a2", "investigador-web", "Otra fuente"),
                ("a3", "agente-desconocido", "Algo"))
    _muestra(con, {"pane_id": "%1", "comando": "claude", "titulo": TRABAJANDO, "claude_sesion": SESION})
    [t] = api.talleres(con)["talleres"]
    assert t["clave"] == f"%1:{SESION}"
    por_id = {s["id"]: s for s in t["subagentes"]}
    assert por_id["a1"]["rol"] == "investigador" and por_id["a1"]["estacion"] == "alquimia"
    assert por_id["a3"]["rol"] == "otro" and por_id["a3"]["estacion"] == "entrada"


def test_sin_muestra_no_hay_talleres(con):
    assert api.talleres(con)["talleres"] == []


# ── la pantalla ─────────────────────────────────────────────────────────────

@pytest.fixture
def cliente(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from hub import web

    def conexion():
        c = db.conectar(tmp_path / "hub.db")
        db.inicializar(c)
        return c

    monkeypatch.setattr(web, "conexion", conexion)
    return TestClient(web.app), conexion


def test_la_pantalla_lleva_los_datos_en_su_region_y_el_titulo_de_un_panel_no_es_html(cliente):
    """El título de un panel lo escribe cualquier programa, y esta página
    comparte origen con la terminal: nunca puede llegar como marcado."""
    c, conexion = cliente
    con = conexion()
    malo = "<img src=x onerror=alert(1)>"
    _muestra(con, {"pane_id": "%1", "comando": "claude", "titulo": QUIETA, "etiqueta": malo})
    con.close()
    r = c.get("/talleres")
    assert r.status_code == 200
    assert 'data-region="talleres"' in r.text and "/static/talleres.js" in r.text
    assert malo not in r.text
    assert "&lt;img src=x" in r.text or "\\u003cimg src=x" in r.text


def test_desde_el_menu_se_llega_a_los_talleres(cliente):
    c, _ = cliente
    assert 'href="/talleres"' in c.get("/").text


def test_sin_sesiones_lo_dice(cliente):
    c, _ = cliente
    assert "Ninguna sesión con un agente ahora mismo" in c.get("/talleres").text


# ── el JS, ejecutado ────────────────────────────────────────────────────────

def _node(codigo: str):
    if not shutil.which("node"):
        pytest.skip("sin node")
    js = (ESTATICOS / "talleres.js").as_posix()
    guion = ("globalThis.window = globalThis; globalThis.document = {querySelector: () => null, readyState: 'complete'};"
             f"require({json.dumps(js)}); const H = window.HubTalleres; console.log(JSON.stringify({codigo}));")
    r = subprocess.run(["node", "-e", guion], capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def test_compara_dos_sondeos_por_taller_y_por_subagente():
    c = _node("""H.comparar(
        [{clave: 'a', estado: 'trabajando', subagentes: [{id: 'x'}]}, {clave: 'b', estado: 'quieta', subagentes: []}],
        [{clave: 'a', estado: 'espera', subagentes: [{id: 'y'}]}, {clave: 'c', estado: 'quieta', subagentes: []}])""")
    assert [t["clave"] for t in c["nuevos"]] == ["c"] and c["idos"] == ["b"]
    assert c["estados"] == [{"clave": "a", "estado": "espera"}]
    assert [x["sub"]["id"] for x in c["llegan"]] == ["y"] and c["salen"] == [{"clave": "a", "id": "x"}]


def test_si_un_ciclo_no_trae_la_conversacion_es_el_mismo_taller_y_otra_conversacion_es_otro():
    """`claude_sesion` puede faltar en un ciclo (o al abrir): renombrar y no
    borrar y crear de nuevo. Un `/clear` sí es otro taller."""
    mismo = _node("""H.comparar([{clave: '%1:', estado: 'quieta', subagentes: []}],
                                 [{clave: '%1:abc', estado: 'trabajando', subagentes: []}])""")
    assert mismo["renombrar"] == [{"de": "%1:", "a": "%1:abc"}] and not mismo["nuevos"] and not mismo["idos"]
    assert mismo["estados"] == [{"clave": "%1:abc", "estado": "trabajando"}]
    otro = _node("""H.comparar([{clave: '%1:abc', estado: 'quieta', subagentes: []}],
                                [{clave: '%1:def', estado: 'quieta', subagentes: []}])""")
    assert [t["clave"] for t in otro["nuevos"]] == ["%1:def"] and otro["idos"] == ["%1:abc"]


def test_reparte_los_huecos_y_cuando_no_cabe_va_al_mas():
    assert _node("[H.repartir([0, 2], 4), H.repartir([0, 1, 2], 3)]") == [1, -1]


def test_otro_se_pinta_neutro_con_su_inicial():
    figura = _node("H.figuraDe({rol: 'otro', inicial: 'Q'}, {figuras: {otro: null}, url: '/s/'})")
    assert figura == {"id": None, "inicial": "Q"}


def test_una_muestra_sin_hora_es_infinitamente_vieja():
    assert _node("[H.edad('2026-11-09T10:00:00Z', Date.parse('2026-11-09T10:02:00Z')), H.edad(null, 0)]") == [120, None]
