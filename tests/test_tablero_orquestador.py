"""Del tablero al trabajo: una idea se encarga por su número y la trabaja la sesión fija (C-0151, decisión 347)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from hub import config, db, ideas, orquestador, web

ORIGEN = {"origin": "http://127.0.0.1:8787"}


@pytest.fixture
def con(tmp_path, monkeypatch):
    # La base del hub del test, la misma que abren la web y el secretario.
    c = db.conectar(config.DB_PATH)
    db.inicializar(c)
    yield from _preparar(c, tmp_path, monkeypatch)
    c.close()


def _preparar(con, tmp_path, monkeypatch):
    monkeypatch.setattr(orquestador, "_tareas", lambda: (tmp_path / "tareas").mkdir(exist_ok=True) or tmp_path / "tareas")
    monkeypatch.setattr(orquestador, "exigir", lambda c, p: "medio")
    copia = tmp_path / "hub-tablero"
    (copia / ".git").mkdir(parents=True)
    monkeypatch.setattr(orquestador, "copia_de_trabajo", lambda c, p: copia if p == "hub" else None)
    yield con


def test_encargar_una_idea_deja_una_tarea_con_su_sesion_fija_y_su_si(con):
    i = ideas.apuntar(con, "que el modo voz tarde menos")
    con.commit()
    t = orquestador.cargar(orquestador.encargar_idea(con, i, confirmado_por_dueno=True))
    assert t["idea"] == i and t["sesion_fija"]["nombre"] == "Tablero"
    assert t["sesion_fija"]["ruta"].endswith("hub-tablero")
    assert [c["proyecto"] for c in t["confirmaciones"] if c["estado"] == "aprobada"] == ["hub"]
    assert f"--idea {i}" in t["pedido"] and "Tablero" in t["pedido"]
    assert ideas.ver(con, i)["estado"] == "nueva", "la toma la sesión, con su ficha"


def test_una_idea_no_se_encarga_dos_veces_ni_tomada_ni_sin_copia(con, monkeypatch):
    i = ideas.apuntar(con, "una")
    con.commit()
    orquestador.encargar_idea(con, i, confirmado_por_dueno=True)
    with pytest.raises(ValueError, match="ya está encargada"):
        orquestador.encargar_idea(con, i, confirmado_por_dueno=True)
    j = ideas.apuntar(con, "otra")
    ideas.tomar(con, j, "C-0999")
    with pytest.raises(ValueError, match="ya está tomada"):
        orquestador.encargar_idea(con, j, confirmado_por_dueno=True)
    monkeypatch.setattr(orquestador, "copia_de_trabajo", lambda c, p: None)
    k = ideas.apuntar(con, "sin carpeta")
    with pytest.raises(ValueError, match="no tiene carpeta registrada"):
        orquestador.encargar_idea(con, k, confirmado_por_dueno=True)


def test_sin_el_si_del_dueno_no_lleva_confirmado_el_proyecto(con):
    i = ideas.apuntar(con, "por el secretario")
    con.commit()
    t = orquestador.cargar(orquestador.encargar_idea(con, i, confirmado_por_dueno=False, origen="secretario"))
    assert t["confirmaciones"] == []


def test_mandar_rechaza_cualquier_sesion_que_no_sea_la_fija(con, monkeypatch):
    i = ideas.apuntar(con, "x")
    con.commit()
    tarea = orquestador.encargar_idea(con, i, confirmado_por_dueno=True)
    with orquestador.editar(tarea) as t:
        t["estado"] = orquestador.ACTIVA
    monkeypatch.setattr(orquestador, "sesiones", lambda c, p: [
        {"pane_id": "%4", "nombre": "Hub - Dev", "fija": False},
        {"pane_id": "%9", "nombre": "Tablero", "fija": True}])
    with pytest.raises(ValueError, match="sólo trabaja en la sesión «Tablero»"):
        orquestador.mandar(con, "hub", "%4", "haz algo")


def test_compactar_comprueba_el_panel_con_la_misma_cerradura_que_mandar(con, monkeypatch):
    """`mandar` llevaba su copia de `_de_su_proyecto` (C-0094), y la copia
    decía cómo abrir la fija mientras compactar y ajustar no lo decían."""
    i = ideas.apuntar(con, "x")
    con.commit()
    tarea = orquestador.encargar_idea(con, i, confirmado_por_dueno=True)
    with orquestador.editar(tarea) as t:
        t["estado"] = orquestador.ACTIVA
    monkeypatch.setattr(orquestador, "sesiones", lambda c, p: [
        {"pane_id": "%4", "nombre": "Hub - Dev", "fija": False}])
    for llamar in (lambda: orquestador.mandar(con, "hub", "%4", "haz algo"),
                   lambda: orquestador.compactar(con, "hub", "%4")):
        with pytest.raises(ValueError, match="si no está abierta: `./orq abrir hub --nombre Tablero`"):
            llamar()


def test_el_boton_trabajarla_la_encarga_y_el_tablero_lo_dice(con):
    i = ideas.apuntar(con, "con botón")
    con.commit()
    cliente = TestClient(web.app)
    assert f'action="/tablero/idea/{i}/trabajar"' in cliente.get("/tablero").text
    r = cliente.post(f"/tablero/idea/{i}/trabajar", headers=ORIGEN, follow_redirects=False)
    assert r.status_code == 303 and "Encargada" in __import__("urllib.parse").parse.unquote(r.headers["location"])
    html = cliente.get("/tablero").text
    assert "encargada →" in html and f'action="/tablero/idea/{i}/trabajar"' not in html


def test_el_secretario_encarga_y_solo_su_aprobacion_vale_como_si(con, monkeypatch):
    from hub.secretario import memoria, piezas, servicio

    accion = piezas.acciones()["trabajar_idea"]
    assert accion.nivel_inicial == "ask"
    i = ideas.apuntar(con, "por voz")
    con.commit()
    # Un `aprobada` metido en los parámetros (los escribe el modelo) no cuenta.
    m = memoria.conectar()
    try:
        accion.ejecutar(m, {"idea": i, "aprobada": True})
    finally:
        m.close()
    t = orquestador.tarea_de_idea(i)
    assert t["confirmaciones"] == []
    with orquestador.editar(t["id"]) as x:
        x["estado"] = orquestador.DETENIDA
    # Por el camino de verdad: «ask» deja la solicitud, el dueño la aprueba en
    # la pantalla y el servicio se lo dice a la acción.
    from hub.secretario import herramientas
    monkeypatch.setattr(herramientas.avisos, "mandar", lambda *a, **k: None)
    m = memoria.conectar()
    try:
        r = herramientas.usar_accion(m, accion, {"idea": i}, "lo pidió por voz")
        assert r["hecho"] is False and r["solicitud"]
        memoria.resolver_solicitud(m, r["solicitud"], "aprobada")
        servicio.ejecutar_aprobadas(m)
    finally:
        m.close()
    t = orquestador.tarea_de_idea(i)
    assert [c["proyecto"] for c in t["confirmaciones"]] == ["hub"]


def test_la_sesion_fija_se_abre_en_la_copia_aunque_el_dueno_tenga_otras_y_se_reutiliza(con, monkeypatch):
    from hub import agentes, api, entrevistador, slots, tui

    i = ideas.apuntar(con, "abrir")
    con.commit()
    tarea = orquestador.encargar_idea(con, i, confirmado_por_dueno=True)
    with orquestador.editar(tarea) as t:
        t["estado"] = orquestador.ACTIVA
    monkeypatch.setattr(orquestador, "sesiones", lambda c, p: [{"pane_id": "%4", "nombre": "Hub - Dev", "fija": False}])
    monkeypatch.setattr(api, "obtener_proyecto", lambda c, p: {"id": "hub", "asiento": "/x/hub"})
    monkeypatch.setattr(agentes, "confiar", lambda r: None)
    monkeypatch.setattr(entrevistador, "comprobar_arranque", lambda p: None)
    monkeypatch.setattr(tui, "listo", lambda *a: True)
    creados, abiertos = [], []
    real_crear = slots.crear
    monkeypatch.setattr(slots, "crear", lambda c, p, n, **k: creados.append((n, k["ruta"])) or real_crear(c, p, n, **k))
    monkeypatch.setattr(slots, "abrir", lambda c, sid, **k: abiertos.append(sid) or "%9")
    con.execute("INSERT OR IGNORE INTO proyecto (id, nombre) VALUES ('hub', 'hub')")
    orquestador.abrir_sesion(con, "hub")
    assert creados == [("Tablero", orquestador.cargar(tarea)["sesion_fija"]["ruta"])]
    orquestador.abrir_sesion(con, "hub")
    assert len(creados) == 1 and len(abiertos) == 2 and abiertos[0] == abiertos[1], "el mismo slot, otra vez"


def test_la_fija_es_la_que_trabaja_en_la_copia_no_la_que_se_llama_tablero(con, monkeypatch):
    """Revisor: un slot «Tablero» del dueño en su carpeta no es la fija, y el
    panel de la copia se ve aunque el muestreo no lo atribuya al proyecto."""
    from hub import api, entrega, tui

    i = ideas.apuntar(con, "fija")
    con.commit()
    tarea = orquestador.encargar_idea(con, i, confirmado_por_dueno=True)
    copia = orquestador.cargar(tarea)["sesion_fija"]["ruta"]
    with orquestador.editar(tarea) as t:
        t["estado"] = orquestador.ACTIVA
    monkeypatch.setattr(api, "paneles_abiertos", lambda c: [
        {"pane_id": "%4", "proyecto_id": "hub", "cwd": "/home/x/projects/hub", "slot_nombre": "Tablero",
         "session": "s", "window_idx": 0},
        {"pane_id": "%9", "proyecto_id": None, "cwd": copia + "/src", "slot_nombre": "Tablero",
         "session": "s", "window_idx": 1}])
    monkeypatch.setattr(orquestador, "_pestanas_de", lambda c, s: {})
    monkeypatch.setattr(entrega, "quien_hay", lambda p: (object.__new__(type("A", (), {"nombre": "claude"})), None))
    monkeypatch.setattr(tui, "ocupado", lambda a, p: False)
    vistas = {s["pane_id"]: s["fija"] for s in orquestador.sesiones(con, "hub")}
    assert vistas == {"%4": False, "%9": True}
    with pytest.raises(ValueError, match="ya está abierta: %9"):
        orquestador.abrir_sesion(con, "hub")


def test_una_idea_fuera_del_alcance_se_dice_en_el_tablero_sin_un_500(con, monkeypatch):
    def sin_permiso(c, p):
        raise orquestador.SinPermiso("el orquestador no llega a «hub»")

    monkeypatch.setattr(orquestador, "exigir", sin_permiso)
    i = ideas.apuntar(con, "sin alcance")
    con.commit()
    r = TestClient(web.app).post(f"/tablero/idea/{i}/trabajar", headers=ORIGEN, follow_redirects=False)
    assert r.status_code == 303 and "no%20llega" in r.headers["location"]


def test_el_encargo_lleva_las_piezas_delicadas_que_vuelven_como_plan(con):
    """D3: un S sigue solo, salvo en las piezas delicadas (decisión 348)."""
    i = ideas.apuntar(con, "algo")
    con.commit()
    pedido = orquestador.cargar(orquestador.encargar_idea(con, i, confirmado_por_dueno=True))["pedido"]
    assert "--motivo plan" in pedido
    for pieza in orquestador.PIEZAS_DELICADAS:
        assert pieza in pedido


def test_la_pantalla_distingue_la_pregunta_del_secretario_y_la_elevada(con):
    t = orquestador.crear("algo")
    with orquestador.editar(t) as d:
        d["estado"] = orquestador.ACTIVA
    orquestador.preguntar("¿a cuál de las dos?", "sesion")
    cliente = TestClient(web.app)
    texto = cliente.get("/orquestador").text
    assert "Pregunta al secretario" in texto and "consultando al secretario" in texto
    orquestador.elevar(t, "Hay dos sesiones y no sé cuál es la tuya.")
    texto = cliente.get("/orquestador").text
    assert "Te pregunta" in texto and "El secretario te la pasa: Hay dos sesiones" in texto



# ── fase 3: ideas de otros proyectos (D1) ────────────────────────────────────

@pytest.fixture
def otro(con, tmp_path, monkeypatch):
    """Un proyecto «otro» con su repositorio git de verdad, sin copia todavía."""
    import subprocess
    from hub import api

    asiento = tmp_path / "otro"
    asiento.mkdir()
    for orden in (["init", "-q", "-b", "main"], ["-c", "user.email=a@b", "-c", "user.name=a", "commit", "-q",
                                                  "--allow-empty", "-m", "inicio"]):
        subprocess.run(["git", "-C", str(asiento), *orden], check=True)
    real = api.obtener_proyecto
    monkeypatch.setattr(api, "obtener_proyecto",
                        lambda c, p: {"id": "otro", "asiento": str(asiento)} if p == "otro" else real(c, p))
    monkeypatch.setattr(orquestador, "copia_de_trabajo", _copia_real)
    monkeypatch.setattr(ideas, "_proyecto_valido", lambda p: p)
    con.execute("INSERT OR IGNORE INTO proyecto (id, nombre, asiento) VALUES ('otro', 'otro', ?)", (str(asiento),))
    con.commit()
    return asiento


_copia_real = orquestador.copia_de_trabajo


def test_un_proyecto_con_git_sin_copia_pide_crearla_y_el_tablero_lo_ofrece(con, otro):
    i = ideas.apuntar(con, "en otro", proyecto="otro")
    con.commit()
    with pytest.raises(orquestador.FaltaCopia):
        orquestador.encargar_idea(con, i, confirmado_por_dueno=True)
    html = TestClient(web.app).get("/tablero").text
    assert "Crear la copia y trabajarla" in html and "otro-tablero" in html


def test_crear_la_copia_es_un_worktree_en_la_rama_tablero_y_no_toca_su_carpeta(con, otro):
    import subprocess

    i = ideas.apuntar(con, "en otro", proyecto="otro")
    con.commit()
    r = TestClient(web.app).post(f"/tablero/idea/{i}/trabajar", data={"crear_copia": "1"}, headers=ORIGEN,
                                 follow_redirects=False)
    assert r.status_code == 303 and "Encargada" in __import__("urllib.parse").parse.unquote(r.headers["location"])
    copia = otro.parent / "otro-tablero"
    rama = subprocess.run(["git", "-C", str(copia), "branch", "--show-current"], capture_output=True, text=True)
    assert rama.stdout.strip() == "tablero"
    actual = subprocess.run(["git", "-C", str(otro), "branch", "--show-current"], capture_output=True, text=True)
    assert actual.stdout.strip() == "main", "su carpeta sigue en su rama"
    t = orquestador.tarea_de_idea(i)
    assert t["sesion_fija"]["ruta"] == str(copia) and t["sesion_fija"]["modo"] == "copia"
    assert orquestador.crear_copia(con, "otro") == copia, "crearla otra vez no hace nada"


def test_sin_git_se_trabaja_en_su_carpeta_y_solo_sin_una_sesion_del_dueno(con, otro, monkeypatch):
    import shutil

    shutil.rmtree(otro / ".git")
    i = ideas.apuntar(con, "sin git", proyecto="otro")
    con.commit()
    tarea = orquestador.encargar_idea(con, i, confirmado_por_dueno=True)
    fija = orquestador.cargar(tarea)["sesion_fija"]
    assert fija["modo"] == "carpeta" and fija["ruta"] == str(otro)
    with orquestador.editar(tarea) as t:
        t["estado"] = orquestador.ACTIVA
    # En su carpeta la fija es la que abrió esta tarea, no la que se llame
    # «Tablero»: un slot suyo con ese nombre no lo es (revisor).
    assert orquestador._es_la_fija({"pane_id": "%9", "cwd": str(otro)}, fija, ("%9",))
    assert not orquestador._es_la_fija({"pane_id": "%4", "cwd": str(otro), "slot_nombre": "Tablero"}, fija, ("%9",))
    monkeypatch.setattr(orquestador, "sesiones", lambda c, p: [
        {"pane_id": "%4", "nombre": "Mío", "fija": False},
        {"pane_id": "%9", "nombre": "Tablero", "fija": True}])
    with pytest.raises(ValueError, match="el dueño tiene una sesión abierta"):
        orquestador.mandar(con, "otro", "%9", "haz algo")
    with pytest.raises(ValueError, match="el dueño tiene una sesión abierta"):
        orquestador._sin_el_dueno_en_su_carpeta(fija, orquestador.sesiones(con, "otro"))
    monkeypatch.setattr(orquestador.tmux, "validar_panel", lambda p: None)
    with pytest.raises(ValueError, match="sólo trabaja en la sesión"):
        orquestador._de_su_proyecto(con, "otro", "%4")


def test_en_su_carpeta_no_se_abre_la_fija_con_una_sesion_del_dueno(con, otro, monkeypatch):
    import shutil
    from hub import api

    shutil.rmtree(otro / ".git")
    i = ideas.apuntar(con, "sin git", proyecto="otro")
    con.commit()
    tarea = orquestador.encargar_idea(con, i, confirmado_por_dueno=True)
    with orquestador.editar(tarea) as t:
        t["estado"] = orquestador.ACTIVA
    monkeypatch.setattr(orquestador, "sesiones", lambda c, p: [{"pane_id": "%4", "nombre": "Mío", "fija": False}])
    with pytest.raises(ValueError, match="el dueño tiene una sesión abierta"):
        orquestador.abrir_sesion(con, "otro")


def test_una_rama_tablero_suya_no_se_adopta(con, otro):
    import subprocess
    subprocess.run(["git", "-C", str(otro), "branch", "tablero"], check=True)
    with pytest.raises(ValueError, match="ya tiene una rama"):
        orquestador.crear_copia(con, "otro")
    assert not (otro.parent / "otro-tablero").exists()


def test_una_subcarpeta_de_un_repositorio_no_cuenta_como_sin_git(con, otro, monkeypatch):
    from hub import api
    sub = otro / "web"
    sub.mkdir()
    monkeypatch.setattr(api, "obtener_proyecto", lambda c, p: {"id": p, "asiento": str(sub)})
    with pytest.raises(ValueError, match="dentro del repositorio"):
        orquestador.donde_trabajar(con, "web")
