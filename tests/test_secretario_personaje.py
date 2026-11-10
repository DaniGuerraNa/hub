"""El personaje del secretario enseña lo que hace, y sólo lo que hace (C-0166, decisión 358).

Lo que se comprueba aquí es la parte de los datos: que cada herramienta y
cada acción tiene su gesto de la lista cerrada, que el rótulo se compone sin
el argumento en crudo, que los acompañantes son lo que delegó y sigue vivo
(y los subagentes de verdad de la sesión que lo trabaja), y que el marcado y
el CSS cubren todo el vocabulario. El JavaScript se prueba ejecutándolo, en
`test_avatar_secretario_js.py`.
"""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

import arnes_webp

import pytest

from hub import api, config, orquestador, transcripts
from hub.secretario import herramientas, memoria, personaje, piezas, sesiones

RAIZ = Path(__file__).resolve().parents[1] / "src" / "hub"


# ── el vocabulario ────────────────────────────────────────────────────────────

def test_cada_herramienta_y_cada_accion_tiene_un_gesto_de_la_lista_cerrada():
    todas = herramientas.todas()
    assert len(todas) > 30
    fuera = {n: h.gesto for n, h in todas.items() if h.gesto not in personaje.GESTOS}
    assert not fuera, f"gestos fuera de personaje.GESTOS: {fuera}"
    for a in piezas.acciones().values():
        assert a.gesto in personaje.GESTOS, a.id
        # Su rótulo es su nombre dicho para el dueño, no el id.
        assert herramientas.actividad(f"accion_{a.id}", {})["rotulo"] == (a.nombre or a.id)


def test_una_herramienta_con_un_gesto_inventado_no_se_puede_crear():
    with pytest.raises(ValueError, match="lista cerrada"):
        herramientas.Herramienta("x", "x", {}, lambda c, p: None, gesto="bailar")


def test_cada_gesto_lo_usa_alguna_herramienta_o_accion():
    """Un gesto que nadie usa es un dibujo que nunca se ve: o sobra, o falta asignarlo."""
    usados = {h.gesto for h in herramientas.todas().values()}
    assert set(personaje.GESTOS) == usados


def test_el_rotulo_dice_lo_que_hace_con_sus_palabras_y_recortado():
    a = herramientas.actividad("leer_archivo", {"proyecto": "hub", "ruta": "docs/notas/largo.md"})
    assert a == {"gesto": "leer", "rotulo": "Leyendo largo.md"}
    largo = herramientas.actividad("buscar", {"texto": "x" * 500, "fuente": "telegram"})
    assert len(largo["rotulo"]) <= 90 and largo["rotulo"].startswith("Buscando «x") and "…" in largo["rotulo"]


def test_sin_argumentos_todavia_el_rotulo_se_lee_entero():
    """Al empezar una herramienta llega sin argumentos: no puede quedar «…en »."""
    for nombre in herramientas.todas():
        rotulo = herramientas.actividad(nombre, {})["rotulo"]
        assert rotulo and not rotulo.rstrip().endswith((" en", " de", "«»")), (nombre, rotulo)


@pytest.mark.parametrize("llave", ["sk-ant-api03-" + "A" * 40, "AIza" + "B" * 35,
                                   "123456789:" + "AAH" + "c" * 32])
def test_el_rotulo_tapa_las_llaves_antes_de_recortarlas(llave):
    """Recortada a 28 caracteres, una llave ya no casa con su patrón: se tapa
    antes (lo midió el revisor con una de Google y un token de Telegram)."""
    a = herramientas.actividad("buscar", {"texto": llave})
    assert llave[4:14] not in a["rotulo"], a["rotulo"]


def test_una_herramienta_que_no_esta_en_el_catalogo_se_ensena_con_su_nombre_real():
    assert herramientas.actividad("WebSearch", {"query": "x"}) == {"gesto": "hacer", "rotulo": "WebSearch"}


@pytest.mark.parametrize("tipo, rol", [
    ("arquitecto", "arquitecto"), ("revisor", "revisor"), ("Explore", "explorador"), ("Plan", "planificador"),
    ("general-purpose", "ayudante"), ("diseñador", "disenador"), ("seo-visual", "disenador"),
    ("deep-research", "investigador"), ("claude-code-guide", "ayudante"), ("statusline-setup", "otro"), ("", "otro"),
    ("planta", "otro"), ("planner", "planificador"), ("reviewer", "revisor"),
])
def test_el_rol_de_un_subagente_sale_de_su_tipo_por_palabras(tipo, rol):
    assert personaje.rol_de(tipo) == rol


def test_un_rol_desconocido_lleva_su_inicial():
    assert personaje.inicial("statusline-setup") == "S"
    assert personaje.inicial("") == "?"


# ── el marcado, el CSS y el JS cubren todo el vocabulario ─────────────────────

PLANTILLA = (RAIZ / "templates" / "_personaje.html").read_text(encoding="utf-8")
CSS = (RAIZ / "static" / "avatar-secretario.css").read_text(encoding="utf-8")
JS = (RAIZ / "static" / "avatar-secretario.js").read_text(encoding="utf-8")


def test_cada_gesto_y_cada_rol_tiene_su_dibujo():
    simbolos = set(re.findall(r'<symbol id="([\w-]+)"', PLANTILLA))
    assert {f"acc-{g}" for g in personaje.GESTOS} <= simbolos
    assert {f"rol-{r}" for r in personaje.ROLES} <= simbolos


def test_cada_rol_tiene_su_piel_y_cada_estado_su_pose():
    for rol in personaje.ROLES:
        assert f'.pj-acomp[data-rol="{rol}"]' in CSS, rol
    for estado in personaje.ESTADOS:
        if estado != "quieto":
            assert f'[data-estado="{estado}"]' in CSS, estado


def test_el_js_conoce_la_misma_lista_de_gestos_y_ningun_nombre_de_herramienta():
    lista = re.search(r"const GESTOS = \[(.*?)\];", JS, re.S).group(1)
    assert re.findall(r"'([\w-]+)'", lista) == list(personaje.GESTOS)
    # «buscar» o «leer» son gestos; los nombres que sólo son de herramientas, no.
    solo_herramientas = set(herramientas.todas()) - set(personaje.GESTOS)
    literales = set(re.findall(r"'([\w-]+)'", JS))
    assert not literales & solo_herramientas


COLOR_SUELTO = re.compile(r"#[0-9a-fA-F]{3,8}(?![\w-])|rgba?\(")


def test_el_css_usa_tokens_y_no_colores_sueltos():
    assert not COLOR_SUELTO.search(CSS)
    assert not COLOR_SUELTO.search(PLANTILLA)
    assert "box-shadow" not in CSS and "gradient" not in CSS


def test_con_movimiento_reducido_cada_estado_es_una_pose_fija():
    bloque = CSS[CSS.index("@media (prefers-reduced-motion: reduce)"):]
    assert "animation:none !important" in bloque.split("}")[0] + "}"


# ── lo que espera y lo que delegó ─────────────────────────────────────────────

def test_sin_secretario_no_hay_espera_y_no_se_crea_su_base():
    assert api.secretario_espera() is None
    assert not memoria.existe()


def test_la_espera_cuenta_solicitudes_y_resumenes_en_cola_y_en_curso():
    con = memoria.conectar()
    con.execute("INSERT INTO solicitud (accion, params, motivo, creada) VALUES ('avisar', '{}', '', ?)",
                (memoria.ahora(),))
    memoria.poner(con, sesiones.CLAVE, [{"sesion": "a", "hilo": 1}, {"sesion": "b", "hilo": 1}])
    memoria.poner(con, sesiones.EN_CURSO, {"sesion": "c", "desde": memoria.ahora()})
    e = api.secretario_espera()
    # Tres resúmenes, y de ellos uno leyéndose: los otros dos esperan, no trabajan.
    assert (e["solicitudes"], e["resumenes"], e["resumiendo"], e["encargos"]) == (1, 3, 1, [])


def test_un_resumen_en_curso_de_un_servicio_que_murio_no_se_cuenta_para_siempre():
    con = memoria.conectar()
    memoria.poner(con, sesiones.EN_CURSO, {"sesion": "c", "desde": "2020-01-01T00:00:00+00:00"})
    e = api.secretario_espera()
    assert (e["resumenes"], e["resumiendo"]) == (0, 0)


def test_el_rail_sin_personaje_no_mira_lo_delegado_pero_cuenta_los_permisos():
    from hub import db
    hub = db.conectar(config.HUB_HOME / "hub.db")
    db.inicializar(hub)
    con = memoria.conectar()
    con.execute("INSERT INTO solicitud (accion, params, motivo, creada) VALUES ('avisar', '{}', '', ?)",
                (memoria.ahora(),))
    r = api.rail(hub)
    assert r["secretario_espera"] is None and r["secretario_pendientes"] == 1
    (memoria.carpeta() / "secretario.yml").write_text("en_todo_el_hub: true\n")
    r = api.rail(hub)
    assert r["secretario_espera"]["solicitudes"] == 1 and r["secretario_pendientes"] == 1


def test_el_resumen_en_curso_se_apunta_mientras_se_lee_y_se_quita_al_acabar(monkeypatch):
    con = memoria.conectar()
    memoria.poner(con, sesiones.CLAVE, [{"sesion": "x" * 8, "hilo": None}])
    visto = []
    monkeypatch.setattr(transcripts, "ruta_de_sesion", lambda s: visto.append(memoria.leer(con, sesiones.EN_CURSO)))
    sesiones.atender(con)
    assert visto and visto[0]["sesion"] == "x" * 8
    assert memoria.leer(con, sesiones.EN_CURSO) is None


def _tarea_viva(pane_id: str = "%7", origen: str = "secretario", estado: str = orquestador.ACTIVA) -> str:
    tid = orquestador.crear("Arreglar la pantalla de respaldo", origen=origen)
    with orquestador.editar(tid) as t:
        t["estado"] = estado
        orquestador._nueva_espera(t, "demo", pane_id, "trabajo")
    return tid


def test_los_encargos_son_sus_tareas_del_orquestador_vivas_o_en_cola_y_nada_mas():
    memoria.conectar()
    viva = _tarea_viva()
    _tarea_viva(origen="texto")                                    # la encargó el dueño: no es suya
    _tarea_viva(estado=orquestador.TERMINADA)                      # ya acabó
    cola = orquestador.crear("Otra cosa", origen="secretario")     # en cola: sigue siendo suya
    e = api.secretario_espera()
    assert [x["id"] for x in e["encargos"]] == [viva, cola]
    assert e["encargos"][1]["estado"] == orquestador.EN_COLA


def test_mirar_la_espera_sin_orquestador_no_le_crea_carpeta():
    memoria.conectar()
    api.secretario_espera()
    assert not (config.HUB_HOME / "orquestador").exists()


def _sesion_con_subagentes(tmp_path, monkeypatch, cwd: str = "/srv/demo") -> str:
    """Una sesión de Claude Code con tres subagentes: uno trabajando, uno que
    acabó y uno que se calló hace mucho (como quedaron medidos el 6-nov)."""
    monkeypatch.setattr(transcripts, "TRANSCRIPTS", tmp_path / "projects")
    sesion = "11111111-2222-3333-4444-555555555555"
    carpeta = tmp_path / "projects" / transcripts.slug_de(cwd)
    sub = carpeta / sesion / "subagents"
    sub.mkdir(parents=True)
    (carpeta / f"{sesion}.jsonl").write_text("{}\n")

    def agente(nombre, tipo, que, ultima, hace=0):
        (sub / f"agent-{nombre}.meta.json").write_text(json.dumps({"agentType": tipo, "description": que}))
        ruta = sub / f"agent-{nombre}.jsonl"
        ruta.write_text(json.dumps({"type": "user", "message": {"content": "hazlo"}}) + "\n" + json.dumps(ultima) + "\n")
        if hace:
            os.utime(ruta, (time.time() - hace, time.time() - hace))

    usa = {"type": "assistant", "message": {"stop_reason": "tool_use",
                                            "content": [{"type": "tool_use", "id": "t", "name": "Read"}]}}
    acabo = {"type": "assistant", "message": {"stop_reason": "end_turn", "content": [{"type": "text", "text": "Listo"}]}}
    agente("a1", "revisor", "Revisa el cambio", usa)
    agente("a2", "Explore", "Busca dónde", acabo)
    agente("a3", "diseñador", "Pule la pantalla", usa, hace=transcripts.SUBAGENTE_QUIETO_S + 60)
    return sesion


def test_los_subagentes_vivos_son_los_que_no_acabaron_ni_se_callaron(tmp_path, monkeypatch):
    sesion = _sesion_con_subagentes(tmp_path, monkeypatch)
    ruta = transcripts.ruta_de_sesion(sesion)
    assert transcripts.subagentes_vivos(ruta) == [{"id": "a1", "tipo": "revisor", "que": "Revisa el cambio"}]


def test_una_sesion_sin_subagentes_no_tiene_ninguno(tmp_path):
    ruta = tmp_path / "s.jsonl"
    ruta.write_text("{}\n")
    assert transcripts.subagentes_vivos(ruta) == []


def test_el_encargo_trae_la_sesion_que_lo_trabaja_y_sus_subagentes_con_su_rol(tmp_path, monkeypatch):
    from hub import db
    sesion = _sesion_con_subagentes(tmp_path, monkeypatch)
    hub = db.conectar(tmp_path / "hub.db")
    db.inicializar(hub)
    sid = hub.execute("INSERT INTO snapshot (tomado_en, server_pid) VALUES (?, 1)", (memoria.ahora(),)).lastrowid
    columnas = {f[1] for f in hub.execute("PRAGMA table_info(panel)")}
    fila = {"snapshot_id": sid, "pane_id": "%7", "session": "trabajo", "window_idx": 1, "pane_idx": 0,
            "cwd": "/srv/demo", "claude_sesion": sesion}
    fila = {k: v for k, v in fila.items() if k in columnas}
    hub.execute(f"INSERT INTO panel ({', '.join(fila)}) VALUES ({', '.join('?' * len(fila))})", tuple(fila.values()))
    hub.commit()
    memoria.conectar()
    (memoria.carpeta() / "secretario.yml").write_text("en_todo_el_hub: true\n")
    _tarea_viva("%7")
    [encargo] = api.secretario_espera(hub)["encargos"]
    [s] = encargo["sesiones"]
    assert s["subagentes"] == [{"id": "a1", "rol": "revisor", "tipo": "revisor", "inicial": "R", "que": "Revisa el cambio"}]
    # El raíl y el sondeo traen lo mismo, del mismo sitio.
    assert api.rail(hub)["secretario_espera"]["encargos"][0]["sesiones"] == [s]
    assert api.secretario_turnos(0, hub)["espera"]["encargos"] == [encargo]


def test_un_panel_que_ya_no_esta_en_el_muestreo_no_se_inventa():
    from hub import db
    hub = db.conectar(config.HUB_HOME / "hub.db")
    db.inicializar(hub)
    memoria.conectar()
    _tarea_viva("%99")
    [encargo] = api.secretario_espera(hub)["encargos"]
    assert encargo["sesiones"] == []


@pytest.fixture
def cliente(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from hub import db, web

    def conexion():
        c = db.conectar(tmp_path / "hub.db")
        db.inicializar(c)
        return c

    monkeypatch.setattr(web, "conexion", conexion)
    memoria.conectar().close()
    (memoria.carpeta() / "secretario.yml").write_text("en_todo_el_hub: true\n")
    return TestClient(web.app)


def test_el_personaje_es_la_pestana_que_sigue_por_todas_las_pantallas(cliente):
    html = cliente.get("/").text
    pestana = html[html.index('id="secretario-pestana"'):]
    pestana = pestana[:pestana.index("</button>")]
    assert "data-personaje" in pestana and 'class="pj ' in pestana and "data-rotulo" in pestana
    # Sale ya pintado con lo del raíl (lo que espera y lo que delegó, y la
    # cuenta de sus asuntos para el globo, C-0201).
    assert json.loads(re.search(r"data-espera='([^']*)'", pestana).group(1)) == {
        "solicitudes": 0, "resumenes": 0, "resumiendo": 0, "encargos": [], "investigaciones": 0, "investigando": 0,
        "asuntos": {"nuevas": 0, "total": 0}}
    assert '<symbol id="acc-buscar"' in html and "/static/avatar-secretario.js" in html
    # Una sola vez: un personaje por pantalla (el otro SVG es la plantilla de un acompañante).
    assert html.count('class="pj-satelites"') == 1


def test_en_su_pantalla_va_en_la_cabecera(cliente):
    html = cliente.get("/secretario").text
    assert 'class="sec-personaje" data-personaje' in html and 'id="secretario-pestana"' not in html


def test_la_galeria_enseña_todos_los_estados_gestos_y_roles(cliente):
    html = cliente.get("/secretario?p=personaje").text
    for estado in personaje.ESTADOS:
        assert f'data-estado="{estado}"' in html, estado
    for gesto in personaje.GESTOS:
        assert f'data-gesto="{gesto}"' in html and f'href="#acc-{gesto}"' in html, gesto
    for rol in personaje.ROLES:
        assert f'data-rol="{rol}"' in html, rol
    assert 'id="pj-reproducir"' in html


def test_la_galeria_lista_todo_el_vocabulario():
    c = api.personaje_catalogo()
    assert [e["id"] for e in c["estados"]] == list(personaje.ESTADOS)
    assert [g["id"] for g in c["gestos"]] == list(personaje.GESTOS)
    assert [r["id"] for r in c["roles"]] == list(personaje.ROLES)


# ── quién es: el personaje elegido (C-0188, decisión 377) ─────────────────────

HOJAS = RAIZ / "static" / "personajes"
DIBUJADOS = [p for p in personaje.PERSONAJES if p != personaje.POR_OMISION]


def test_el_cubo_es_el_de_siempre_y_el_primero():
    assert personaje.POR_OMISION == "cubo" == next(iter(personaje.PERSONAJES))
    assert personaje.hoja("cubo") == "" and personaje.hoja("rana-mochi") == "/static/personajes/rana-mochi.webp"


def test_la_pose_de_cada_estado_y_de_cada_gesto_es_una_de_las_dibujadas():
    """Todos los estados tienen su pose, y «trabajando» la saca sólo del gesto."""
    assert set(personaje.POSE_DE_ESTADO) == set(personaje.ESTADOS) - {"trabajando"}
    assert set(personaje.POSE_DE_GESTO) == set(personaje.GESTOS)
    for estado in personaje.ESTADOS:
        if estado != "trabajando":
            assert personaje.pose_de(estado) in personaje.POSES, estado
    for gesto in personaje.GESTOS:
        assert personaje.pose_de("trabajando", gesto) in ("buscando", "anotando"), gesto
    # Lo que espera tu sí lleva el «?» del dibujo; lo que espera a otro, no.
    assert personaje.pose_de("esperando") == "esperando" and personaje.pose_de("esperando-otro") == "base"
    assert personaje.pose_de("hecho") == "listo" and personaje.pose_de("error") == "base"


# Sin comentarios: el de encima de una regla quedaría pegado a su selector.
_SIN_COMENTARIOS = re.sub(r"/\*.*?\*/", "", CSS, flags=re.S)


def _reglas_de_capa() -> dict[str, list[str]]:
    """pose → los selectores del CSS que encienden la capa del principal."""
    reglas: dict[str, list[str]] = {}
    for selector, cuerpo in re.findall(r"([^{}]+)\{([^{}]*)\}", _SIN_COMENTARIOS):
        m = re.search(r'\.pj-capa\[data-pose="([\w-]+)"\]\s*$', selector.strip())
        # Las del acompañante dibujado van aparte (C-0236): su propia prueba.
        if m and "opacity:1" in cuerpo.replace(" ", "") and not selector.strip().startswith(".pj-acomp"):
            reglas.setdefault(m.group(1), []).append(selector.strip())
    return reglas


def test_el_css_enciende_la_misma_pose_que_pose_de_y_solo_una():
    """La copia del CSS es la de `pose_de`, regla a regla: un estado o un gesto
    en dos reglas encendería dos capas a la vez."""
    por_estado: dict[str, list[str]] = {}
    por_gesto: dict[str, list[str]] = {}
    for pose, selectores in _reglas_de_capa().items():
        for sel in selectores:
            if '[data-estado="trabajando"]' in sel:
                for g in re.findall(r'\[data-gesto="([\w-]+)"\]', sel):
                    por_gesto.setdefault(g, []).append(pose)
            else:
                for e in re.findall(r'\[data-estado="([\w-]+)"\]', sel):
                    por_estado.setdefault(e, []).append(pose)
                if ":not([data-estado])" in sel:
                    por_estado.setdefault("(sin estado)", []).append(pose)
    assert por_estado.pop("(sin estado)") == ["base"]
    assert por_estado == {e: [p] for e, p in personaje.POSE_DE_ESTADO.items()}
    assert por_gesto == {g: [p] for g, p in personaje.POSE_DE_GESTO.items()}


# ── los acompañantes, con el personaje elegido (C-0236) ──────────────────────

def test_cada_rol_lleva_de_insignia_un_gesto_de_la_lista_y_solo_otro_va_sin_ella():
    assert list(personaje.GESTO_DE_ROL) == list(personaje.ROLES)
    sin = [r for r, g in personaje.GESTO_DE_ROL.items() if not g]
    assert sin == ["otro"]
    assert all(g in personaje.GESTOS for g in personaje.GESTO_DE_ROL.values() if g)


def test_la_plantilla_lleva_la_misma_insignia_por_rol_y_un_simbolo_para_cada_uno():
    lista = re.search(r"for rol, gesto in \[(.*?)\] %\}", PLANTILLA, re.S).group(1)
    assert dict(re.findall(r"\('([\w-]+)', '([\w-]*)'\)", lista)) == personaje.GESTO_DE_ROL
    assert 'id="ins-{{ rol }}"' in PLANTILLA


def _enciende(sel: str, estado: str) -> bool:
    """Si una regla de capa del acompañante vale para ese estado: o lo nombra,
    o lo deja fuera de su `:not(…)` y entonces vale para todos los demás."""
    fuera = re.search(r":not\(([^)]*)\)", sel)
    if fuera:
        return f'[data-estado="{estado}"]' not in fuera.group(1)
    return f'[data-estado="{estado}"]' in sel


def test_el_acompanante_dibujado_enciende_la_pose_de_pose_de_y_solo_una():
    """Trabajando busca, en cola descansa, esperando levanta la mano: lo que
    dice `pose_de` sin gesto, y una sola capa por estado, para cada estado que
    les pone `avatar-secretario.js` y para uno que aún no existe (que no lo
    deje sin capa: el cubo sí se vería)."""
    reglas = [(m.group(1), sel.strip()) for sel, cuerpo in re.findall(r"([^{}]+)\{([^{}]*)\}", _SIN_COMENTARIOS)
              if sel.strip().startswith(".pj-acomp") and "opacity:1" in cuerpo.replace(" ", "")
              and (m := re.search(r'\.pj-capa\[data-pose="([\w-]+)"\]\s*$', sel.strip()))]
    tarea = re.search(r"const ESTADO_TAREA = \{(.*?)\};", JS, re.S).group(1)
    funcion = re.search(r"function acompanantes\(.*?\n  \}\n", JS, re.S).group(0)
    del_js = set(re.findall(r":\s*'([\w-]+)'", tarea)) | set(re.findall(r"estado: '([\w-]+)'", funcion))
    assert {"trabajando", "en-cola", "esperando"} <= del_js
    for estado in sorted(del_js) + ["uno-nuevo"]:
        poses = [pose for pose, sel in reglas if _enciende(sel, estado)]
        assert poses == [personaje.pose_de(estado)], estado
    assert all(" > .pj " in sel for _, sel in reglas)   # nunca la capa del principal


def test_con_un_dibujo_la_plantilla_del_acompanante_es_el_mismo_en_pequeno(cliente):
    """Lo que vio el dueño: su personaje dibujado investigando y, a su lado, el cubo azul."""
    cliente.post("/secretario/personaje", data={"personaje": "rana-sombrero-hongo"}, headers=CASA)
    for html in (cliente.get("/").text, cliente.get("/secretario").text, cliente.get("/secretario/monitor").text):
        molde = re.search(r'<template id="pj-plantilla-acomp">(.*?)</template>', html, re.S).group(1)
        assert 'class="pj pj-dibujo pj-mini" data-pj="rana-sombrero-hongo"' in molde
        assert "/static/personajes/rana-sombrero-hongo.webp" in molde and 'href="#ins-__ROL__"' in molde
        # Ni el accesorio del principal (el JS lo busca por esa clase) ni sus globos.
        assert "pj-accesorio" not in molde and "pj-globo" not in molde and "rol-__ROL__" not in molde
        assert 'id="ins-investigador"' in html
    galeria = cliente.get("/secretario?p=personaje").text
    for rol in personaje.ROLES:
        assert re.search(rf'data-rol="{rol}" data-estado="trabajando">\s*<span class="pj pj-dibujo pj-mini"'
                         rf'[^>]*>.*?href="#ins-{rol}"', galeria, re.S), rol


def test_con_el_cubo_los_acompanantes_siguen_con_su_ropa(cliente):
    molde = re.search(r'<template id="pj-plantilla-acomp">(.*?)</template>', cliente.get("/").text, re.S).group(1)
    assert 'class="pj pj-mini"' in molde and 'href="#rol-__ROL__"' in molde and "pj-dibujo" not in molde


def test_cada_capa_lee_su_celda_de_la_hoja_en_el_orden_de_poses():
    capas = re.search(r"for pose in \[(.*?)\]", PLANTILLA).group(1)
    assert re.findall(r"'([\w-]+)'", capas) == list(personaje.POSES)
    for i, pose in enumerate(personaje.POSES):
        x, y = (i % 3) * 50, (i // 3) * 50
        assert re.search(rf'\.pj-capa\[data-pose="{pose}"\]\s*\{{\s*background-position:{x}% {y}%;', CSS), pose


def test_con_movimiento_reducido_tampoco_se_funde():
    """Las capas cambian con `transition`: con movimiento reducido, de golpe."""
    for inicio in ("@media (prefers-reduced-motion: reduce)", ".sin-movimiento .pj"):
        regla = CSS[CSS.index(inicio):].split("}")[0]
        assert "animation:none !important" in regla and "transition:none !important" in regla


def test_cada_personaje_dibujado_tiene_su_hoja_y_no_sobra_ninguna():
    assert sorted(p.name for p in HOJAS.iterdir()) == sorted(f"{p}.webp" for p in DIBUJADOS)


@pytest.mark.parametrize("pid", DIBUJADOS)
def test_cada_hoja_es_de_tres_por_tres_celdas_y_sin_metadatos(pid):
    """Los PNG de origen traen un bloque de procedencia (C2PA) y la revisión de
    lo publicado no lee binarios: de ahí sólo pueden salir los píxeles."""
    trozos = arnes_webp.trozos((HOJAS / f"{pid}.webp").read_bytes())
    assert {t for t, _ in trozos} <= {b"VP8X", b"VP8 ", b"VP8L", b"ALPH"}, [t for t, _ in trozos]
    vp8x = dict(trozos)[b"VP8X"]
    ancho = int.from_bytes(vp8x[4:7], "little") + 1
    alto = int.from_bytes(vp8x[7:10], "little") + 1
    assert (ancho, alto) == (768, 768)


def test_los_webp_se_publican_como_binarios():
    publicacion = pytest.importorskip("hub.publicacion", reason="no viaja con el producto")
    assert ".webp" in publicacion.SIN_TEXTO


def test_elegir_guarda_solo_uno_del_catalogo():
    con = memoria.conectar()
    assert personaje.elegir(con, "rana-mochi") == "rana-mochi"
    assert memoria.leer(con, personaje.CLAVE) == "rana-mochi"
    with pytest.raises(ValueError):
        personaje.elegir(con, "../../etc")
    assert memoria.leer(con, personaje.CLAVE) == "rana-mochi"


@pytest.mark.parametrize("valor", [None, "", "dragon", 7, ["rana-mochi"]])
def test_lo_guardado_que_no_esta_en_el_catalogo_se_pinta_como_el_cubo(valor):
    assert personaje.elegido(valor) == "cubo"
    assert api.personaje_vista(valor) == {"id": "cubo", "nombre": "El cubo", "familia": "Original", "hoja": ""}


def test_la_galeria_lista_los_personajes_del_catalogo():
    assert [p["id"] for p in api.personaje_catalogo()["personajes"]] == list(personaje.PERSONAJES)


CASA = {"origin": "http://127.0.0.1:8787"}


def _pestana(html: str) -> str:
    p = html[html.index('id="secretario-pestana"'):]
    return p[:p.index("</button>")]


def _cabecera(cliente) -> str:
    html = cliente.get("/secretario").text
    i = html.index('class="sec-personaje"')
    return html[i:html.index("pj-texto", i)]


def test_sin_elegir_es_el_cubo(cliente, tmp_path):
    from hub import db
    assert 'class="pj-satelites"' in _pestana(cliente.get("/").text)
    assert "pj-dibujo" not in _cabecera(cliente)
    hub = db.conectar(tmp_path / "hub.db")
    assert api.rail(hub)["personaje"]["id"] == "cubo"


def test_elegido_en_la_galeria_lo_llevan_la_pestana_la_cabecera_y_toda_la_galeria(cliente):
    r = cliente.post("/secretario/personaje", data={"personaje": "rana-mochi"}, headers=CASA, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/secretario?p=personaje")
    assert memoria.leer(memoria.conectar(), personaje.CLAVE) == "rana-mochi"

    pestana = _pestana(cliente.get("/").text)
    assert 'data-pj="rana-mochi"' in pestana and "/static/personajes/rana-mochi.webp" in pestana
    # El JS sigue encontrando dónde poner el objeto que usa (`.pj-accesorio use`).
    assert re.search(r'class="pj-accesorio">.*?<use href="#acc-hacer"', pestana, re.S)
    assert 'data-pj="rana-mochi"' in _cabecera(cliente)

    g = cliente.get("/secretario?p=personaje").text
    elegida = re.search(r'<form[^>]*class="carta elegido"[^>]*>(.*?)</form>', g, re.S)
    assert elegida and 'data-pj="rana-mochi"' in elegida.group(1) and "Usar este" not in elegida.group(1)
    assert g.count('aria-current="true"') == 1 and g.count("Usar este") == len(personaje.PERSONAJES) - 1
    # Las cartas de estados, herramientas y roles, con el elegido.
    for gesto in personaje.GESTOS:
        assert re.search(rf'data-gesto="{gesto}">\s*<span class="pj pj-dibujo\s*" data-pj="rana-mochi"', g), gesto
    for rol in personaje.ROLES:
        assert re.search(rf'data-pj="rana-mochi"[^<]*>(?:(?!class="carta).)*?data-rol="{rol}"', g, re.S), rol


def test_elegir_desde_otro_sitio_no_cambia_nada(cliente):
    r = cliente.post("/secretario/personaje", data={"personaje": "rana-mochi"},
                     headers={"origin": "https://sitio-malicioso.example"}, follow_redirects=False)
    assert r.status_code == 403
    assert memoria.leer(memoria.conectar(), personaje.CLAVE) is None


def test_un_personaje_que_no_existe_no_se_guarda_y_se_dice(cliente):
    r = cliente.post("/secretario/personaje", data={"personaje": "dragon"}, headers=CASA, follow_redirects=False)
    assert r.status_code == 303 and "aviso=" in r.headers["location"]
    assert memoria.leer(memoria.conectar(), personaje.CLAVE) is None
