"""Conversaciones anteriores de un slot y del asistente (decisión 290).

Quien usó el hub sin que se lo enseñaran perdió el hilo al cerrarse la consola
y tuvo que contarle a Claude desde cero en qué estaban. La conversación seguía
guardada; lo que faltaba era una puerta para volver a ella.
"""
from __future__ import annotations

import json
import os

import pytest

from hub import asistente, conversaciones, slots, snapshotter, tmux, transcripts, web
from hub.models import Proyecto

from test_vistas_web import cliente  # noqa: F401  — el cliente con base de pruebas

UNO = "11111111-1111-4111-8111-111111111111"
DOS = "22222222-2222-4222-8222-222222222222"
VACIA = "33333333-3333-4333-8333-333333333333"


def _sesion(directorio, sid, pedidos, cuando="2026-10-22T10:00:00Z", titulo=None, mtime=None):
    directorio.mkdir(parents=True, exist_ok=True)
    lineas = []
    if titulo:
        lineas.append({"type": "ai-title", "aiTitle": titulo})
    for i, texto in enumerate(pedidos):
        lineas.append({"type": "user", "timestamp": cuando, "cwd": "/tmp/demo",
                       "message": {"role": "user", "content": texto}})
        lineas.append({"type": "assistant", "timestamp": cuando,
                       "message": {"role": "assistant", "content": [{"type": "text", "text": "vale"}]}})
    if not pedidos:
        lineas.append({"type": "assistant", "timestamp": cuando,
                       "message": {"role": "assistant", "content": [{"type": "text", "text": "hola"}]}})
    archivo = directorio / f"{sid}.jsonl"
    archivo.write_text("\n".join(json.dumps(l) for l in lineas) + "\n")
    if mtime:
        os.utime(archivo, (mtime, mtime))
    return archivo


@pytest.fixture
def registro(tmp_path, monkeypatch):
    raiz = tmp_path / "claude-projects"
    monkeypatch.setattr(transcripts, "TRANSCRIPTS", raiz)
    conversaciones._FICHAS.clear()
    return raiz


@pytest.fixture
def slot_demo(con, proyecto_demo):
    con.execute("INSERT INTO slot (id, proyecto_id, nombre, status, creado_en) "
                "VALUES (5,'demo','login','activo','x')")
    return 5


def _con_panel_vivo(con, sid, slot_id=5):
    con.execute("INSERT INTO snapshot (id, tomado_en) VALUES (1, '2026-10-22')")
    con.execute("""INSERT INTO panel (snapshot_id, pane_id, session, window_idx, pane_idx, cwd,
                   comando, slot_id, claude_sesion) VALUES (1,'%3','demo',2,0,'/tmp/demo','claude',?,?)""",
                (slot_id, sid))


def test_lista_las_de_la_carpeta_del_slot_la_ultima_primero(con, slot_demo, registro):
    carpeta = registro / transcripts.slug_de("/tmp/demo")
    _sesion(carpeta, UNO, ["arregla el login"], mtime=1_000)
    _sesion(carpeta, DOS, ["<command-name>/clear</command-name>", "y ahora los tests"],
            titulo="Tests del login", mtime=2_000)
    lista = conversaciones.de_slot(con, slot_demo)
    assert [c["id"] for c in lista] == [DOS, UNO]
    assert lista[0]["titulo"] == "Tests del login"
    # Sin título, lo primero que se pidió; y lo que escribe Claude Code no cuenta.
    assert lista[1]["primera"] == "arregla el login"
    assert lista[0]["primera"] == "y ahora los tests"


def test_una_sesion_sin_ninguna_peticion_no_se_ofrece(con, slot_demo, registro):
    _sesion(registro / transcripts.slug_de("/tmp/demo"), VACIA, [])
    assert conversaciones.de_slot(con, slot_demo) == []


def test_la_abierta_ahora_se_marca_y_dice_en_que_ventana(con, slot_demo, registro):
    _sesion(registro / transcripts.slug_de("/tmp/demo"), UNO, ["hola"])
    _con_panel_vivo(con, UNO)
    c = conversaciones.de_slot(con, slot_demo)[0]
    assert c["viva"] and c["de_este_slot"]
    assert c["ventana"] == {"session": "demo", "ventana": 2}


def test_no_se_retoma_una_ajena_ni_una_abierta_ni_un_id_raro(con, slot_demo, registro):
    carpeta = registro / transcripts.slug_de("/tmp/demo")
    _sesion(carpeta, UNO, ["hola"])
    _sesion(registro / "otra-carpeta", DOS, ["de otro sitio"])
    assert conversaciones.retomable(con, slot_demo, UNO)["id"] == UNO
    with pytest.raises(ValueError, match="no es de este slot"):
        conversaciones.retomable(con, slot_demo, DOS)
    with pytest.raises(ValueError, match="id válido"):
        conversaciones.retomable(con, slot_demo, "x; rm -rf ~")
    _con_panel_vivo(con, UNO)
    with pytest.raises(ValueError, match="ya está abierta"):
        conversaciones.retomable(con, slot_demo, UNO)


def test_retomar_abre_una_ventana_del_slot_con_resume(cliente, registro, monkeypatch):  # noqa: F811
    con = web.conexion()
    con.execute("INSERT INTO slot (id, proyecto_id, nombre, status, creado_en) "
                "VALUES (5,'demo','login','activo','x')")
    con.commit()
    con.close()
    _sesion(registro / transcripts.slug_de("/tmp/demo"), UNO, ["hola"])
    abiertos = []
    monkeypatch.setattr(slots, "abrir", lambda con, sid, comando=None, **k: abiertos.append((sid, comando)) or None)
    monkeypatch.setattr(snapshotter, "un_ciclo", lambda con: None)

    r = cliente.post("/slot/5/retomar", data={"sesion": UNO},
                     headers={"Origin": "http://localhost"}, follow_redirects=False)
    assert r.status_code == 303
    assert abiertos == [(5, f"claude --resume {UNO}")]

    r = cliente.post("/slot/5/retomar", data={"sesion": DOS},
                     headers={"Origin": "http://localhost"}, follow_redirects=False)
    assert "no+es+de+este+slot" in r.headers["location"] or "no%20es%20de%20este%20slot" in r.headers["location"]
    assert len(abiertos) == 1


def test_crear_un_slot_desde_trabajo_lo_abre_y_lleva_a_el(cliente, monkeypatch):  # noqa: F811
    abiertos = []
    monkeypatch.setattr(slots, "abrir", lambda con, sid, **k: abiertos.append(sid) or None)
    monkeypatch.setattr(snapshotter, "un_ciclo", lambda con: None)
    r = cliente.post("/slot/nuevo", data={"proyecto_id": "demo", "nombre": "Arreglar login",
                                          "ir": "trabajo", "autostart_claude": "1"},
                     headers={"Origin": "http://localhost"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/trabajo?slot=")
    assert len(abiertos) == 1


def test_trabajo_ofrece_crear_proyecto_y_slot(cliente):  # noqa: F811
    html = cliente.get("/trabajo").text
    assert "data-nuevo-proyecto" in html
    assert "/static/proyecto-nuevo.js" in html and "/static/slot-nuevo.js" in html
    assert 'id="proyectos-para-slot"' in html and '["demo", "Demo"]' in html


def test_un_slot_sin_ventana_ofrece_retomar(cliente):  # noqa: F811
    con = web.conexion()
    con.execute("INSERT INTO slot (id, proyecto_id, nombre, ruta, status, creado_en) "
                "VALUES (5,'demo','login','/tmp/demo','activo','x')")
    con.commit()
    con.close()
    html = cliente.get("/trabajo?slot=5").text
    assert 'data-conversaciones="5"' in html and "/static/conversaciones.js" in html


# ── el asistente ─────────────────────────────────────────────────────────────


@pytest.fixture
def con_asistente(tmp_path, registro):
    asiento = tmp_path / "asistente"
    asiento.mkdir()
    p = Proyecto(id="asistente", nombre="Asistente", asiento=str(asiento), tipo="asistente")
    return [p], registro / transcripts.slug_de(str(asiento))


def test_el_asistente_arranca_con_la_conversacion_pedida():
    assert f"--resume {UNO}" in asistente.comando_de_arranque(None, UNO)
    assert "--resume" not in asistente.comando_de_arranque(None)


def test_el_asistente_lista_sus_chats_y_marca_el_de_ahora(con_asistente):
    proyectos, carpeta = con_asistente
    _sesion(carpeta, UNO, ["ayer"], mtime=1_000)
    _sesion(carpeta, DOS, ["hoy"], mtime=2_000)
    lista = asistente.conversaciones_anteriores(proyectos)
    assert [(c["id"], c["actual"]) for c in lista] == [(DOS, True), (UNO, False)]


def test_volver_a_un_chat_relanza_su_panel_y_lo_pone_delante(con_asistente, monkeypatch):
    proyectos, carpeta = con_asistente
    viejo = _sesion(carpeta, UNO, ["ayer"], mtime=1_000)
    _sesion(carpeta, DOS, ["hoy"], mtime=2_000)
    relanzados = []
    monkeypatch.setattr(asistente, "localizar", lambda: "%9")
    monkeypatch.setattr(asistente, "_esperar_panel", lambda: "%9")
    monkeypatch.setattr(asistente, "_esperar_listo", lambda p: True)
    monkeypatch.setattr(tmux, "relanzar_panel", lambda p, r, c, e=None: relanzados.append((p, c)))

    assert asistente.retomar(proyectos, UNO)["ok"]
    assert relanzados and relanzados[0][0] == "%9" and f"--resume {UNO}" in relanzados[0][1]
    # El chat pinta el más reciente: ahora es el retomado.
    assert asistente.transcript_vivo(proyectos) == viejo

    with pytest.raises(ValueError, match="no es del asistente"):
        asistente.retomar(proyectos, VACIA)


def test_cada_slot_trae_sus_ventanas_una_por_ventana_de_tmux(con, slot_demo):
    """Decisión 291: el raíl cuelga las ventanas de su slot. Una ventana partida
    en dos paneles es UNA ventana, y las de otro slot no se cuelan."""
    from hub import api
    con.execute("INSERT INTO slot (id, proyecto_id, nombre, status, creado_en) "
                "VALUES (6,'demo','otro','activo','x')")
    con.execute("INSERT INTO snapshot (id, tomado_en) VALUES (1, '2026-10-22')")
    for pane, idx, pane_idx, slot in (("%1", 0, 0, 5), ("%2", 0, 1, 5), ("%3", 3, 0, 5), ("%4", 1, 0, 6)):
        con.execute("""INSERT INTO panel (snapshot_id, pane_id, session, window_idx, pane_idx, cwd,
                       comando, slot_id, etiqueta) VALUES (1,?,'demo',?,?,'/tmp/demo','bash',?,?)""",
                    (pane, idx, pane_idx, slot, f"v{idx}"))
    ctx = api.contexto_trabajo(con)
    slots_demo = {s["id"]: s for s in next(p for p in ctx["proyectos"] if p["id"] == "demo")["slots"]}
    assert [(v["ventana"], v["etiqueta"]) for v in slots_demo[5]["ventanas"]] == [(0, "v0"), (3, "v3")]
    assert [v["ventana"] for v in slots_demo[6]["ventanas"]] == [1]


def test_el_mas_de_las_pestanas_abre_la_ventana_atada_a_su_slot(cliente, monkeypatch):  # noqa: F811
    """23-oct: dos ventanas abiertas con el «+» de las pestañas sobre un slot
    salieron sueltas. Con slot, la ventana nace atada a él, como con «+ Ventana»."""
    con = web.conexion()
    con.execute("INSERT INTO slot (id, proyecto_id, nombre, status, creado_en) "
                "VALUES (5,'demo','estudio','activo','x')")
    con.commit()
    con.close()
    abiertos, sueltas = [], []
    monkeypatch.setattr(tmux, "existe_sesion", lambda s: True)
    monkeypatch.setattr(slots, "abrir", lambda con, sid, session=None, **k: abiertos.append((sid, session)))
    monkeypatch.setattr(snapshotter, "un_ciclo", lambda con: None)
    monkeypatch.setattr(tmux, "nueva_ventana", lambda *a, **k: sueltas.append(a))
    h = {"Origin": "http://localhost"}

    assert cliente.post("/api/sesion/demo/ventanas", json={"ruta": "/tmp/demo", "slot": 5},
                        headers=h).json()["ok"]
    assert abiertos == [(5, "demo")] and sueltas == []

    # Sin slot (una ventana suelta), como siempre: sólo la carpeta.
    assert cliente.post("/api/sesion/demo/ventanas", json={"ruta": "/tmp/demo", "slot": None},
                        headers=h).json()["ok"]
    assert len(sueltas) == 1 and len(abiertos) == 1
