"""«Te espera» en pantalla y delegar por punto (C-0201, decisiones 379-381).

Los asuntos se leen en vivo de cada dueño (`asuntos.reunir`) y la pantalla
sólo añade lo que el dueño hace con cada uno: anotarlo, delegarlo o pedir que
se lo preparen, callarlo, contestarlo. Cada respuesta va por la puerta de su
dueño. Lo legal, lo de un proyecto sin alcance y lo de uno con `never` no se
delega. El globo del chat cuenta sólo lo nuevo, y lo que se tiene delante deja
de serlo por POST, nunca al pintar.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import unquote

import pytest
from fastapi.testclient import TestClient

from arnes_js import ejecutar, script_estatico
from hub import api, config, db, orquestador as orq, registry, web
from hub.secretario import asuntos, memoria

VOLVER = "/secretario?p=pendientes"


@pytest.fixture
def cliente():
    # `web.conexion()` de verdad: abre el `hub.db` de `HUB_HOME` aislado, el
    # mismo que leen los asuntos cuando abren su propia conexión.
    h = db.abrir()
    h.close()
    return TestClient(web.app)


@pytest.fixture
def con(cliente):
    c = memoria.conectar()
    yield c
    c.close()


def _proyecto(tmp_path, bloqueos: list[str], pid: str = "tienda", guardrail: str = "ask",
              nivel: str | None = "medio") -> None:
    """Un proyecto registrado, en el índice, con su `bloqueado_por` y, si se
    pide, alcance del orquestador."""
    carpeta = tmp_path / pid
    carpeta.mkdir(exist_ok=True)
    (carpeta / "ESTADO.md").write_text(
        "# Estado\n\n## Estado actual\nEn marcha.\n\n## Bloqueado por\n" + "".join(f"- {b}\n" for b in bloqueos),
        encoding="utf-8")
    config.projects_yml().write_text(
        f"proyectos:\n  - id: {pid}\n    nombre: La tienda\n    asiento: {carpeta}\n    estado_ref: ESTADO.md\n"
        f"    guardrail: {guardrail}\n", encoding="utf-8")
    h = db.abrir()
    try:
        registry.sincronizar(h, registry.cargar())   # lo que hace el snapshotter
        h.commit()
    finally:
        h.close()
    if nivel:
        orq.fijar_nivel(pid, nivel)


def _bloqueo(con) -> asuntos.Asunto:
    [a] = [x for x in asuntos.reunir(con).asuntos if x.clase == "bloqueo"]
    return a


def _vista(clave: str) -> dict:
    h = db.abrir()
    try:
        return api.secretario_asunto(h, clave)
    finally:
        h.close()


def _accion(cliente, clave: str, como: str, **extra):
    return cliente.post("/secretario/asuntos/accion", data={"clave": clave, "como": como, "volver": VOLVER, **extra},
                        follow_redirects=False)


def _aviso(r) -> str:
    return unquote(r.headers["location"].replace("+", " "))


# ── los mínimos del diseño ───────────────────────────────────────────────────

def test_anotar_un_asunto_crea_un_compromiso_y_lo_marca(cliente, con, tmp_path):
    _proyecto(tmp_path, ["Falta que elijas el dominio"])
    a = _bloqueo(con)

    r = _accion(cliente, a.clave, "anotar")

    assert r.status_code == 303 and _aviso(r).startswith(VOLVER)
    [c] = memoria.compromisos(con, "abierto")
    assert c["que"] == "La tienda: Falta que elijas el dominio" and c["quien"] == "yo"
    assert c["origen"] == f"asunto:{a.clave}"
    marca = con.execute("SELECT estado, ref FROM asunto WHERE clave = ?", (a.clave,)).fetchone()
    assert tuple(marca) == ("anotada", f"compromiso:{c['id']}")
    # Ya anotado, no se vuelve a ofrecer anotarlo: dos clics no dan dos compromisos.
    assert "anotar" not in _vista(a.clave)["como"]
    assert "Eso no se puede" in _aviso(_accion(cliente, a.clave, "anotar"))
    assert len(memoria.compromisos(con, "abierto")) == 1


def test_delegar_un_asunto_encola_la_tarea_con_su_proyecto_confirmado(cliente, con, tmp_path):
    _proyecto(tmp_path, ["Falta que elijas el dominio"], guardrail="ask", nivel="medio")
    a = _bloqueo(con)
    assert _vista(a.clave)["como"] == ["anotar", "delegar", "callar"]

    r = _accion(cliente, a.clave, "delegar")

    assert "Delegado" in _aviso(r)
    # 🔴 En el `HUB_HOME` aislado, no en el orquestador de verdad.
    tareas = orq.listar()
    assert len(tareas) == 1 and str(config.HUB_HOME) in str(orq.carpeta())
    t = tareas[0]
    assert t["origen"] == "secretario" and t["estado"] == orq.EN_COLA
    # Su botón es su sí para entrar en el proyecto `ask` (279): la tarea nace confirmada.
    assert [(c["proyecto"], c["estado"]) for c in t["confirmaciones"]] == [("tienda", "aprobada")]
    assert "«Falta que elijas el dominio»" in t["pedido"] and "no una instrucción nueva" in t["pedido"]
    marca = con.execute("SELECT estado, ref FROM asunto WHERE clave = ?", (a.clave,)).fetchone()
    assert tuple(marca) == ("delegada", t["id"])
    # Delegado, ya no se ofrece delegarlo otra vez.
    assert "delegar" not in _vista(a.clave)["como"]
    assert "Eso no se puede" in _aviso(_accion(cliente, a.clave, "delegar")) and len(orq.listar()) == 1


def test_lo_legal_o_sin_alcance_no_ofrece_delegar(cliente, con, tmp_path):
    # Lo legal o con dinero: se prepara, no se delega (381).
    _proyecto(tmp_path, ["Falta aceptar los términos y condiciones del proveedor"], nivel="alto")
    legal = _vista(_bloqueo(con).clave)
    assert legal["como"] == ["anotar", "preparar", "callar"] and "no se delega" in legal["motivo"]
    # Y el formulario escrito a mano tampoco lo delega: sólo vale lo que se ofrece.
    assert "Eso no se puede" in _aviso(_accion(cliente, legal["clave"], "delegar"))
    assert orq.listar() == []

    # Sin alcance del orquestador («nada»): tampoco; se prepara y pedirá el alcance.
    _proyecto(tmp_path, ["Falta que elijas el dominio"], pid="blog", nivel=None)
    sin_alcance = _vista(_bloqueo(con).clave)
    assert sin_alcance["como"] == ["anotar", "preparar", "callar"] and "Permisos" in sin_alcance["motivo"]

    # 🔴 Con `never`, ni delegar ni preparar (regla dura 7): el hub no le encarga nada.
    _proyecto(tmp_path, ["Falta que elijas el dominio"], pid="cerrado", guardrail="never", nivel="alto")
    nunca = _vista(_bloqueo(con).clave)
    assert nunca["como"] == ["anotar", "callar"] and "never" in nunca["motivo"]
    for como in ("delegar", "preparar"):
        assert "Eso no se puede" in _aviso(_accion(cliente, nunca["clave"], como))
    assert orq.listar() == []


def test_un_bloqueo_se_anota_o_se_delega_una_sola_vez(cliente, con, tmp_path):
    """Una marca y una `ref` por asunto: anotar tras delegar borraba la tarea
    de la `ref` y volvía a ofrecer delegarlo, dos tareas para el mismo punto
    (revisor). Ni tras callar y reabrir."""
    _proyecto(tmp_path, ["Falta que elijas el dominio"])
    a = _bloqueo(con)
    _accion(cliente, a.clave, "delegar")
    [t] = orq.listar()

    assert _vista(a.clave)["como"] == ["callar"] and _vista(a.clave)["decidido"] == "delegado"
    for como in ("anotar", "delegar", "preparar"):
        assert "Eso no se puede" in _aviso(_accion(cliente, a.clave, como))
    _accion(cliente, a.clave, "callar")
    _accion(cliente, a.clave, "reabrir")

    vista = _vista(a.clave)
    assert vista["como"] == ["callar"] and vista["decidido"] == "delegado" and vista["ref"] == t["id"]
    assert "Eso no se puede" in _aviso(_accion(cliente, a.clave, "delegar"))
    assert len(orq.listar()) == 1 and memoria.compromisos(con, "abierto") == []
    assert f'href="/orquestador?tarea={t["id"]}"' in cliente.get(VOLVER).text


def test_preparar_encola_un_pedido_que_no_ejecuta_lo_del_dueno(cliente, con, tmp_path):
    _proyecto(tmp_path, ["Falta firmar el contrato con la imprenta"], nivel="alto")
    a = _bloqueo(con)

    assert "Pedido que te lo preparen" in _aviso(_accion(cliente, a.clave, "preparar"))

    [t] = orq.listar()
    assert "no lo ejecutes" in t["pedido"] and "./orq preguntar --motivo nunca" in t["pedido"]
    assert [c["proyecto"] for c in t["confirmaciones"]] == ["tienda"]


def test_un_post_de_asuntos_sin_origen_propio_se_rechaza(cliente, con, tmp_path):
    _proyecto(tmp_path, ["Falta que elijas el dominio"])
    a = _bloqueo(con)
    ajeno = {"Origin": "https://malo.example"}

    r = cliente.post("/secretario/asuntos/accion", data={"clave": a.clave, "como": "delegar", "volver": VOLVER},
                     headers=ajeno)
    assert r.status_code == 403
    assert cliente.post("/secretario/asuntos/vista", json={"claves": [a.clave]}, headers=ajeno).status_code == 403
    assert orq.listar() == [] and con.execute("SELECT COUNT(*) FROM asunto").fetchone()[0] == 0
    # Y por GET no se marca nada: marcar es POST.
    assert cliente.get("/secretario/asuntos/vista").status_code == 405


def test_contestar_al_orquestador_desde_asuntos_lleva_su_testigo(cliente, con):
    tarea = orq.crear("revisa los logs de anoche")
    with orq.editar(tarea) as t:
        t["estado"] = orq.ACTIVA
    orq.preguntar("¿Borro los temporales o los dejo?")
    [a] = [x for x in api.secretario_asuntos()["asuntos"] if x["clase"] == "orquestador"]
    assert a["tarea"] == tarea and a["testigo"] == orq.cargar(tarea)["pregunta"]["id"]

    # La pantalla la pinta con su testigo y su vuelta a Pendientes.
    html = cliente.get(VOLVER).text
    assert f'name="testigo" value="{a["testigo"]}"' in html and 'action="/orquestador/responder"' in html

    # Si entretanto llegó otra pregunta, la respuesta no se le aplica a ésa.
    viejo = a["testigo"]
    with orq.editar(tarea) as t:
        t["pregunta"]["id"] = "0123456789ab"
    r = cliente.post("/orquestador/responder", data={"tarea_id": tarea, "texto": "Bórralos", "testigo": viejo,
                                                     "volver": VOLVER}, follow_redirects=False)
    assert _aviso(r).startswith(VOLVER) and "ya no es la que se leyó" in _aviso(r)
    assert orq.cargar(tarea)["pregunta"] is not None

    r = cliente.post("/orquestador/responder", data={"tarea_id": tarea, "texto": "Bórralos",
                                                     "testigo": "0123456789ab", "volver": VOLVER},
                     follow_redirects=False)
    assert _aviso(r).startswith(VOLVER) and "Respuesta entregada" in _aviso(r)
    assert orq.cargar(tarea)["pregunta"] is None
    assert "Bórralos" in orq.cargar(tarea)["despertar"][-1]


def test_volver_del_orquestador_es_siempre_una_ruta_de_este_hub(cliente):
    tarea = orq.crear("algo")
    for malo in ("//malo.example/x", "https://malo.example", "/\\malo.example"):
        r = cliente.post("/orquestador/responder", data={"tarea_id": tarea, "texto": "x", "volver": malo},
                         follow_redirects=False)
        assert r.headers["location"].startswith(f"/orquestador?tarea={tarea}"), malo


def test_el_globo_cuenta_solo_lo_nuevo(cliente, con, tmp_path):
    _proyecto(tmp_path, ["Falta que elijas el dominio", "Falta el logo"])
    assert api.secretario_espera()["asuntos"] == {"nuevas": 0, "total": 0}, "sin instantánea, cero"
    asuntos.recalcular(con)
    assert api.secretario_espera()["asuntos"] == {"nuevas": 2, "total": 2}

    visto, otro = [a for a in asuntos.reunir(con).asuntos if a.clase == "bloqueo"]
    r = cliente.post("/secretario/asuntos/vista", json={"claves": [visto.clave, "bloqueo:tienda:no-existe"]})

    assert r.json() == {"ok": True, "vistas": 1}
    # El POST rehace la cuenta: el globo no espera a la vuelta del servicio.
    assert api.secretario_espera()["asuntos"] == {"nuevas": 1, "total": 2}
    # Lo que no existe no deja marca: llegaría ya visto.
    assert [f["clave"] for f in con.execute("SELECT clave FROM asunto")] == [visto.clave]
    # Callado ya no cuenta, ni como nuevo ni en el total.
    _accion(cliente, otro.clave, "callar")
    assert api.secretario_espera()["asuntos"] == {"nuevas": 0, "total": 1}


# ── lo demás que se ve ───────────────────────────────────────────────────────

def test_sin_secretario_te_espera_esta_vacio_y_no_crea_su_base():
    assert api.secretario_asuntos() == {"asuntos": [], "fichas": [], "callados": [], "fallos": [], "nuevas": 0}
    assert api.secretario_asunto(None, "bloqueo:x:y") is None
    assert not memoria.existe()


def test_te_espera_pinta_cada_clase_con_su_puerta_y_lo_callado_aparte(cliente, con, tmp_path):
    sid = con.execute("INSERT INTO solicitud (accion, params, motivo, creada) VALUES ('crear_slot', '{}', ?, ?)",
                      ("para el informe", memoria.ahora())).lastrowid
    memoria.comprometer(con, "Mandar el reporte", vence="2020-01-01T15:00:00+00:00")
    _proyecto(tmp_path, ["Falta que elijas el dominio", "Falta el logo"])
    pregunta = asuntos.preguntar(con, "¿Publico el catálogo nuevo?", clase="proyecto", origen="tienda",
                                 opciones=("sí", "todavía no"))
    callado = [a for a in asuntos.reunir(con).asuntos if a.clase == "bloqueo"][1]
    asuntos.marcar(con, callado.clave, "callada")

    html = cliente.get(VOLVER).text
    bloque = html.split('id="te-espera"')[1].split('<div class="rejilla-2">')[0]

    # El permiso, con el macro de siempre y sin repetir su id (ya está en «Esperan tu sí»).
    assert f'action="/secretario/solicitud/{sid}"' in bloque and f'data-clave="permiso:{sid}"' in bloque
    assert html.count(f'id="solicitud-{sid}"') == 1
    assert "Te lo delego" in bloque and "Anótalo" in bloque
    assert 'href="#compromisos"' in bloque and 'id="compromisos"' in html
    # Lo propio con opciones: cada una es un botón que contesta.
    assert 'name="texto" value="todavía no"' in bloque
    # Lo callado no sale arriba: va en «Reabrir lo callado».
    arriba, plegado = bloque.split("Reabrir lo callado")
    assert "Falta el logo" not in arriba and "Falta el logo" in plegado
    assert "data-nueva" in arriba and "data-nueva" not in plegado

    clave = con.execute("SELECT clave FROM asunto WHERE id = ?", (pregunta,)).fetchone()[0]
    r = _accion(cliente, clave, "contestar", texto="todavía no")
    assert "Contestado" in _aviso(r)
    assert tuple(con.execute("SELECT estado, respuesta FROM asunto WHERE id = ?", (pregunta,)).fetchone()) == (
        "resuelta", "todavía no")
    assert "Vuelve a estar" in _aviso(_accion(cliente, callado.clave, "reabrir"))
    assert "Falta el logo" in cliente.get(VOLVER).text.split('id="te-espera"')[1].split("rejilla-2")[0]


def test_lo_que_solo_el_contesta_no_se_calla_ni_desde_el_formulario(cliente, con):
    sid = con.execute("INSERT INTO solicitud (accion, params, creada) VALUES ('crear_slot', '{}', ?)",
                      (memoria.ahora(),)).lastrowid
    assert "Eso no se puede" in _aviso(_accion(cliente, f"permiso:{sid}", "callar"))
    assert "no válida" in _aviso(_accion(cliente, f"permiso:{sid}", "borrar"))
    assert "no es la clave" in _aviso(_accion(cliente, "inventada", "callar"))
    assert con.execute("SELECT COUNT(*) FROM asunto").fetchone()[0] == 0


# ── el JavaScript, ejecutado (regla dura 11) ─────────────────────────────────

CHAT = script_estatico("formato-chat.js") + "\n" + script_estatico("chat-secretario.js")


def test_el_globo_sale_con_lo_nuevo_del_sondeo_y_se_va_sin_nada(tmp_path):
    accion = """
      setTimeout(() => {
        const g = nodo('sec-globo');
        registro.valores.push(['tras-sondeo', g.hidden, g.querySelector('[data-globo-texto]').textContent]);
      }, 5);
    """
    r = ejecutar(CHAT, tmp_path, {"/api/secretario/turnos": {
        "hilo": None, "turnos": [], "espera": {"asuntos": {"nuevas": 3, "total": 5}}}},
        previo="nodo('sec-chat').dataset = { cargar: '1' };", accion=accion)
    assert r["errores"] == []
    # El mismo nombre que el bloque al que lleva (C-0231): eran tres para lo mismo.
    assert ["tras-sondeo", False, "Te espera: 3"] in r["valores"]

    r = ejecutar(CHAT, tmp_path, {"/api/secretario/turnos": {
        "hilo": None, "turnos": [], "espera": {"asuntos": {"nuevas": 0, "total": 5}}}},
        previo="nodo('sec-chat').dataset = { cargar: '1' }; nodo('sec-globo').hidden = false;",
        accion="setTimeout(() => registro.valores.push(['sin-nuevas', nodo('sec-globo').hidden]), 5);")
    assert ["sin-nuevas", True] in r["valores"]


_CON_BLOQUE = """
  nodo('te-espera').dataset = { teEspera: '' };
  document.querySelectorAll('#te-espera [data-clave][data-nueva]').forEach((n, i) => {
    n.dataset = { clave: ['bloqueo:tienda:abc', 'permiso:7', ''][i] };
  });
"""


def test_abrir_el_globo_marca_vistos_por_post(tmp_path):
    """Llegar por el globo (`#te-espera`) es estar delante: lo nuevo que se ve
    se marca, una vez, por POST."""
    r = ejecutar(CHAT, tmp_path, {"POST /secretario/asuntos/vista": {"ok": True, "vistas": 2}},
                 previo=_CON_BLOQUE + "location.hash = '#te-espera';",
                 accion="(globalThis.DOC_OYENTES['hub:repintado'] || []).forEach(f => f({}));")
    assert r["errores"] == []
    vistas = [e for e in r["enviados"] if e["url"] == "/secretario/asuntos/vista"]
    assert [(e["metodo"], e["cuerpo"]) for e in vistas] == [("POST", {"claves": ["bloqueo:tienda:abc", "permiso:7"]})]


def test_una_pantalla_abierta_sola_no_da_nada_por_visto_hasta_que_estas(tmp_path):
    """El relevo abre Pendientes en la PC sin nadie delante (388): sin el
    globo, se marca al primer gesto en la página, no al cargar."""
    r = ejecutar(CHAT, tmp_path, {}, previo=_CON_BLOQUE,
                 accion="registro.valores.push(['antes', registro.enviados.length]);"
                        "(globalThis.DOC_OYENTES['pointerdown'] || []).forEach(f => f({}));")
    assert r["errores"] == []
    assert ["antes", 0] in r["valores"]
    assert [e["cuerpo"] for e in r["enviados"]] == [{"claves": ["bloqueo:tienda:abc", "permiso:7"]}]


def test_sin_el_bloque_no_se_marca_nada(tmp_path):
    r = ejecutar(CHAT, tmp_path, {}, previo="location.hash = '#te-espera';",
                 accion="(globalThis.DOC_OYENTES['pointerdown'] || []).forEach(f => f({}));")
    assert r["errores"] == [] and r["enviados"] == []


def test_lo_que_pide_un_gesto_va_primero_y_las_fichas_plegadas_aparte(cliente, con, monkeypatch):
    """Medido el 7-nov con su hub real: 51 fichas sin botones empujaban fuera
    de la vista los bloqueos que sí se delegan. Las fichas van en una línea
    plegada, como en el parte, y arriba lo que se resuelve aquí."""
    from hub.secretario.asuntos import Asunto, Reunidos
    lista = [Asunto(clave=f"ficha:C-{n:04d}", clase="ficha", texto=f"La ficha C-{n:04d} espera algo tuyo")
             for n in range(1, 4)]
    lista += [Asunto(clave="canal:7", clase="canal", texto="Una sesión te pregunta por el canal"),
              Asunto(clave="bloqueo:tienda:1", clase="bloqueo", texto="Falta que elijas el dominio", origen="tienda"),
              Asunto(clave="relevo:1", clase="relevo", texto="Resuelve el captcha")]
    monkeypatch.setattr(asuntos, "reunir", lambda *a, **k: Reunidos(asuntos=list(lista), fallos=[]))

    te = api.secretario_asuntos()
    assert [a["clase"] for a in te["asuntos"]] == ["relevo", "bloqueo", "canal"]
    assert [a["clave"] for a in te["fichas"]] == ["ficha:C-0001", "ficha:C-0002", "ficha:C-0003"]

    bloque = cliente.get(VOLVER).text.split('id="te-espera"')[1].split('<div class="rejilla-2">')[0]
    arriba, plegado = bloque.split('class="plegado fichas-espera"')
    assert "Resuelve el captcha" in arriba and "C-0001" not in arriba
    assert "3 fichas esperan algo tuyo (3 nuevas)" in plegado and "C-0003" in plegado
    assert '<span class="num">6</span>' in bloque


# ── una sola regla para delegar: el botón y el modelo (revisión cruzada del 7-nov) ──

def _por_el_modelo(con, accion: str, params: dict) -> dict:
    """Por el camino de verdad: `encargar_al_orquestador` va en «ask», así que
    deja su solicitud, él la aprueba y el servicio la ejecuta; `comprometer`
    va en «auto». Devuelve `{hecho, resultado|error}` como lo ve el modelo."""
    from hub.secretario import herramientas, piezas, servicio
    r = herramientas.usar_accion(con, piezas.acciones()[accion], params, "lo pidió")
    if not r.get("solicitud"):
        return r
    memoria.resolver_solicitud(con, r["solicitud"], "aprobada")
    servicio.ejecutar_aprobadas(con)
    s = con.execute("SELECT estado, resultado FROM solicitud WHERE id = ?", (r["solicitud"],)).fetchone()
    return {"hecho": s["estado"] == "hecha", "resultado": s["resultado"] or ""}


@pytest.fixture
def sin_telefono(monkeypatch):
    from hub.secretario import herramientas
    monkeypatch.setattr(herramientas.avisos, "mandar", lambda *a, **k: None)


def test_lo_que_delego_su_boton_no_lo_vuelve_a_delegar_el_modelo(cliente, con, tmp_path, sin_telefono):
    _proyecto(tmp_path, ["Falta que elijas el dominio"])
    a = _bloqueo(con)
    assert "Delegado" in _aviso(_accion(cliente, a.clave, "delegar"))
    r = _por_el_modelo(con, "encargar_al_orquestador",
                       {"pedido": "desbloquea el dominio", "proyecto": "tienda", "asunto": a.clave})
    assert not r["hecho"] and "ya está delegado" in r["resultado"], r
    assert len(orq.listar()) == 1


def test_el_modelo_delega_un_bloqueo_con_su_si_y_lo_legal_lo_prepara(cliente, con, tmp_path, sin_telefono):
    """El camino bueno del modelo, por la misma regla que el botón: aprobada
    la solicitud, su sí vale para el proyecto (279); sin aprobarla («auto»),
    la tarea nace sin confirmar y el orquestador se lo pide."""
    from hub.secretario import delegados, piezas
    _proyecto(tmp_path, ["Falta que elijas el dominio", "Falta firmar el contrato con la imprenta",
                         "Falta el logo", "Falta la foto de portada"], nivel="alto")
    assert delegados.recoger(con) == 0
    dominio, contrato, logo, foto = [x for x in asuntos.reunir(con).asuntos if x.clase == "bloqueo"]

    r = _por_el_modelo(con, "encargar_al_orquestador", {"pedido": "elige .com", "asunto": dominio.clave})
    assert r["hecho"] and "delegado" in r["resultado"], r
    [t] = orq.listar()
    assert (asuntos.buscar(con, dominio.clave).estado, asuntos.buscar(con, dominio.clave).ref) == ("delegada", t["id"])
    assert [(c["proyecto"], c["estado"]) for c in t["confirmaciones"]] == [("tienda", "aprobada")]
    assert "Lo que dijo el secretario al encargarlo: «elige .com»" in t["pedido"]

    r = _por_el_modelo(con, "encargar_al_orquestador", {"pedido": "fírmalo", "asunto": contrato.clave})
    assert r["hecho"] and "preparen" in r["resultado"], r
    # Lo legal que añade el modelo también cuenta, aunque el punto no lo diga.
    r = _por_el_modelo(con, "encargar_al_orquestador", {"pedido": "y paga la factura del diseñador",
                                                        "asunto": logo.clave})
    assert r["hecho"] and "preparen" in r["resultado"], r
    assert all("no lo ejecutes" in x["pedido"] for x in orq.listar() if x["id"] != t["id"])

    # En «auto», sin su sí: la tarea no entra confirmada en el proyecto.
    piezas.acciones()["encargar_al_orquestador"].ejecutar(con, {"pedido": "pon la foto", "asunto": foto.clave},
                                                          aprobada=False)
    ultima = orq.cargar(asuntos.buscar(con, foto.clave).ref)
    assert ("tienda", "aprobada") not in [(c["proyecto"], c["estado"]) for c in ultima.get("confirmaciones") or []]

    with orq.editar(t["id"]) as x:
        x["estado"] = orq.ACTIVA
    orq.terminar("listo, dominio elegido")
    delegados.recoger(con)
    cabeza = con.execute("SELECT texto FROM turno WHERE rol = 'secretario' ORDER BY id DESC").fetchone()[0]
    assert cabeza.startswith("Volvió lo que le encargué al orquestador de tus asuntos: «La tienda: Falta que "
                             "elijas el dominio»"), cabeza


def test_una_delegacion_que_murio_a_medias_se_suelta_al_reabrir(cliente, con, tmp_path):
    _proyecto(tmp_path, ["Falta que elijas el dominio"])
    a = _bloqueo(con)
    # Lo que queda si el proceso muere entre la marca y la tarea.
    con.execute("INSERT INTO asunto (clave, clase, estado, ref, creada) VALUES (?, 'bloqueo', 'delegada', ?, ?)",
                (a.clave, asuntos.DELEGANDO, memoria.ahora()))
    assert "delegar" not in _vista(a.clave)["como"]
    _accion(cliente, a.clave, "callar")
    _accion(cliente, a.clave, "reabrir")
    assert "delegar" in _vista(a.clave)["como"]
    with pytest.raises(ValueError, match="no se marca a mano"):
        asuntos.marcar(con, a.clave, "delegada", ref="t-1")


def test_el_modelo_no_encola_sobre_un_proyecto_never_aunque_no_diga_cual(cliente, con, tmp_path, sin_telefono):
    """El proyecto sale del asunto, no de un parámetro: sin `proyecto`, el
    modelo se saltaba el guardrail (regla dura 7)."""
    _proyecto(tmp_path, ["Falta que elijas el dominio"], guardrail="never", nivel="alto")
    a = _bloqueo(con)
    assert not {"delegar", "preparar"} & set(_vista(a.clave)["como"])
    r = _por_el_modelo(con, "encargar_al_orquestador", {"pedido": "desbloquea el dominio", "asunto": a.clave})
    assert not r["hecho"] and "guardrail never" in r["resultado"], r
    # Ni diciéndole otro proyecto: el del asunto manda.
    r = _por_el_modelo(con, "encargar_al_orquestador",
                       {"pedido": "desbloquea el dominio", "proyecto": "otro", "asunto": a.clave})
    assert not r["hecho"] and "es de «tienda»" in r["resultado"], r
    assert orq.listar() == []


def test_un_compromiso_que_vence_no_se_delega_ni_se_anota_otra_vez(cliente, con, tmp_path, sin_telefono):
    _proyecto(tmp_path, [])
    memoria.comprometer(con, "mandar el informe", vence=memoria.ahora())
    [v] = [x for x in asuntos.reunir(con).asuntos if x.clase == "vence"]
    assert _vista(v.clave)["como"] == []
    r = _por_el_modelo(con, "encargar_al_orquestador", {"pedido": "manda el informe", "asunto": v.clave})
    assert not r["hecho"] and "sólo se delegan los bloqueos" in r["resultado"], r
    r = _por_el_modelo(con, "comprometer", {"que": "mandar el informe", "asunto": v.clave})
    assert not r["hecho"] and "ya es un compromiso" in r["error"], r
    assert orq.listar() == [] and len(memoria.compromisos(con, "abierto")) == 1


def test_lo_callado_no_lo_saca_el_modelo_y_un_permiso_no_pierde_lo_nuevo(cliente, con, tmp_path, sin_telefono):
    _proyecto(tmp_path, ["Falta que elijas el dominio"])
    a = _bloqueo(con)
    asuntos.marcar(con, a.clave, "callada")
    for accion, params in (("comprometer", {"que": "x", "asunto": a.clave}),
                           ("encargar_al_orquestador", {"pedido": "x", "asunto": a.clave})):
        r = _por_el_modelo(con, accion, params)
        assert not r["hecho"] and "callado" in (r.get("error") or r.get("resultado")), (accion, r)
    assert a.clave not in [x.clave for x in asuntos.reunir(con).asuntos], "callar es para siempre (379)"
    with pytest.raises(ValueError, match="callado"):
        asuntos.marcar(con, a.clave, "resuelta")
    assert asuntos.marcar(con, a.clave, "vista") == "callada"

    sid = con.execute("INSERT INTO solicitud (accion, params, motivo, creada) VALUES ('crear_slot','{}','m',?)",
                      (memoria.ahora(),)).lastrowid
    antes = asuntos.recalcular(con)["nuevas"]
    r = _por_el_modelo(con, "comprometer", {"que": "y", "asunto": f"permiso:{sid}"})
    assert not r["hecho"] and "sólo lo contestas tú" in r["error"], r
    for estado in asuntos.DECIDIDAS:
        with pytest.raises(ValueError, match="no se anota ni se delega"):
            asuntos.marcar(con, f"permiso:{sid}", estado)
    assert asuntos.recalcular(con)["nuevas"] == antes and memoria.compromisos(con) == []


def test_delegar_marca_antes_de_crear_la_tarea_y_si_falla_lo_deja_como_estaba(cliente, con, tmp_path,
                                                                                monkeypatch):
    _proyecto(tmp_path, ["Falta que elijas el dominio"])
    a = _bloqueo(con)
    vistas: list[str] = []
    crear = orq.crear

    def mirando(*args, **kw):
        # Cuando se crea la tarea, el asunto ya está ocupado: otro clic no entra.
        vistas.append(con.execute("SELECT estado FROM asunto WHERE clave = ?", (a.clave,)).fetchone()[0])
        with pytest.raises(ValueError, match="ya está delegado"):
            asuntos.delegar(con, a.clave, por="boton")
        return crear(*args, **kw)
    monkeypatch.setattr(orq, "crear", mirando)
    tarea, como = asuntos.delegar(con, a.clave, por="boton")
    assert vistas == ["delegada"] and como == "delegar" and len(orq.listar()) == 1
    assert asuntos.buscar(con, a.clave).ref == tarea

    # Si crear la tarea falla, la marca vuelve a como estaba y se puede repetir.
    _proyecto(tmp_path, ["Falta que elijas el dominio", "Falta el logo"])
    [b] = [x for x in asuntos.reunir(con).asuntos if x.clase == "bloqueo" and x.clave != a.clave]

    def rota(*args, **kw):
        raise OSError("disco lleno")
    monkeypatch.setattr(orq, "crear", rota)
    assert "disco lleno" in _aviso(_accion(cliente, b.clave, "delegar"))
    b = asuntos.buscar(con, b.clave)
    assert (b.estado, b.ref) == ("nueva", "") and "delegar" in _vista(b.clave)["como"]


def test_un_enlace_con_un_espacio_o_un_control_no_es_una_ruta_del_hub(cliente, con, tmp_path):
    """El navegador quita el tabulador y el salto de línea de un `href`:
    `/\\t/otro.sitio/` acababa en `//otro.sitio/`, otro sitio."""
    from hub.secretario import de_proyectos
    for malo in ("/\t/ejemplo.invalid/", "/\n/ejemplo.invalid/", "/\r/ejemplo.invalid", "/ /ejemplo.invalid",
                 "/a\x00b", "/a b"):
        with pytest.raises(ValueError):
            asuntos.enlace_valido(malo)
        assert web._ruta_interna(malo, "/defecto") == "/defecto", repr(malo)
    assert asuntos.enlace_valido("/proyecto/tienda?x=1#y") == "/proyecto/tienda?x=1#y"
    assert web._ruta_interna("/secretario?p=pendientes", "/defecto") == "/secretario?p=pendientes"

    _proyecto(tmp_path, [])
    with pytest.raises(ValueError):
        de_proyectos.dejar("tienda", "aviso", "Mira esto", enlace="/\t/ejemplo.invalid/")
    tarea = orq.crear("algo")
    r = cliente.post("/orquestador/responder", data={"tarea_id": tarea, "texto": "x", "volver": "/\t/ejemplo.invalid/"},
                     follow_redirects=False)
    assert r.headers["location"].startswith(f"/orquestador?tarea={tarea}")


def test_contestar_lo_que_pregunta_un_proyecto_le_vuelve_por_su_carpeta(cliente, con, tmp_path, capsys):
    """La vuelta de `proyecto-dice` (387): la respuesta queda en
    `de-proyectos/<id>/respuestas/` y el proyecto la lee con su orden."""
    from hub.secretario import __main__ as cli, de_proyectos
    _proyecto(tmp_path, [])
    de_proyectos.dejar("tienda", "pregunta", "¿Envío el pedido 12 hoy o mañana?", clave="pedido-12")
    de_proyectos.dejar("tienda", "pregunta", "¿Abro los domingos?")
    assert de_proyectos.recoger(con) == 2
    con_clave, sin_clave = sorted((x for x in asuntos.reunir(con).asuntos if x.clase == "proyecto"),
                                  key=lambda x: "pedido-12" not in x.clave)
    assert _vista(con_clave.clave)["como"] == ["contestar", "hecho", "callar"]
    for a, texto in ((con_clave, "hoy"), (sin_clave, "no")):
        assert "Contestado" in _aviso(_accion(cliente, a.clave, "contestar", texto=texto))

    carpeta = de_proyectos.carpeta() / "tienda" / de_proyectos.RESPUESTAS
    assert sorted(p.name for p in carpeta.iterdir()) == sorted(["pedido-12.json", f"asunto-{sin_clave.id}.json"])
    assert asuntos.reunir(con).asuntos == [] and de_proyectos.recoger(con) == 0, "la vuelta no es la cola"

    capsys.readouterr()
    assert cli.proyecto_respuestas(["tienda", "--borrar"]) == 0
    leidas = [json.loads(x) for x in capsys.readouterr().out.splitlines()]
    assert {(r["clave"], r["respuesta"]) for r in leidas} == {("pedido-12", "hoy"), ("", "no")}
    assert all(r["pregunta"] and r["cuando"] for r in leidas)
    assert list(carpeta.iterdir()) == [], "con --borrar, leídas y quitadas"
    assert cli.proyecto_respuestas(["no-registrado"]) == 2


def test_una_clave_que_parece_de_asunto_no_pisa_otra_respuesta_y_borrar_no_pierde_la_nueva(cliente, con,
                                                                                        tmp_path, monkeypatch):
    from hub.secretario import de_proyectos
    _proyecto(tmp_path, [])
    de_proyectos.dejar("tienda", "pregunta", "¿Abro los domingos?")
    de_proyectos.dejar("tienda", "pregunta", "¿Y los sábados?", clave="asunto-1")
    de_proyectos.recoger(con)
    for a in [x for x in asuntos.reunir(con).asuntos if x.clase == "proyecto"]:
        _accion(cliente, a.clave, "contestar", texto=f"respuesta a {a.id}")
    carpeta = de_proyectos.carpeta() / "tienda" / "respuestas"
    assert len(list(carpeta.glob("*.json"))) == 2, "cada pregunta, su archivo"
    assert {r["clave"] for r in de_proyectos.respuestas("tienda")} == {"", "asunto-1"}

    # Si contesta otra vez mientras el proyecto las lee y borra, la nueva se queda.
    leer = Path.read_text

    def contesta_a_la_vez(ruta, *a, **k):
        texto = leer(ruta, *a, **k)
        if ruta.name.startswith(".leyendo-") and not (carpeta / "asunto-1.json").exists():
            (carpeta / "asunto-1.json").write_text('{"respuesta": "la nueva"}', encoding="utf-8")
        return texto
    monkeypatch.setattr(Path, "read_text", contesta_a_la_vez)
    de_proyectos.respuestas("tienda", borrar=True)
    monkeypatch.setattr(Path, "read_text", leer)
    assert [r["respuesta"] for r in de_proyectos.respuestas("tienda")] == ["la nueva"]


def test_un_relevo_se_da_por_hecho_y_no_se_contesta(cliente, con, monkeypatch):
    from hub.secretario import piezas
    monkeypatch.setattr(piezas, "ajuste", lambda clave: False if clave == "relevo_en_pc" else None)
    i = asuntos.pedir_relevo(con, "Resuelve el captcha en la PC", origen="navegador")
    clave = con.execute("SELECT clave FROM asunto WHERE id = ?", (i,)).fetchone()[0]
    assert _vista(clave)["como"] == ["hecho"]
    assert "Eso no se puede" in _aviso(_accion(cliente, clave, "contestar", texto="ya"))
    with pytest.raises(ValueError, match="sólo lo que pregunta un proyecto"):
        asuntos.responder(con, i, "ya")
    assert "Hecho" in _aviso(_accion(cliente, clave, "hecho"))


def test_lo_delegado_por_su_boton_vuelve_al_chat_diciendo_que_punto_era(cliente, con, tmp_path):
    from hub.secretario import delegados
    _proyecto(tmp_path, ["Falta que elijas el dominio"])
    assert delegados.recoger(con) == 0
    a = _bloqueo(con)
    _accion(cliente, a.clave, "delegar")
    [t] = orq.listar()
    with orq.editar(t["id"]) as x:
        x["estado"] = orq.ACTIVA
    orq.terminar("listo, dominio elegido")
    assert delegados.recoger(con) == 1
    cabeza = con.execute("SELECT texto FROM turno WHERE rol = 'secretario' ORDER BY id DESC").fetchone()[0]
    cabeza = cabeza.split("\n")[0]
    assert cabeza.startswith("Volvió lo que delegaste desde tus asuntos:"), cabeza
    assert "La tienda: Falta que elijas el dominio" in cabeza and t["id"] in cabeza


def test_lo_que_dice_un_proyecto_y_lo_que_se_le_contesta_van_con_sus_datos_tapados(cliente, con, tmp_path):
    from hub.secretario import de_proyectos, misdatos
    _proyecto(tmp_path, [])
    misdatos.confirmar("id_fiscal", "IDF000000EJ1")
    de_proyectos.dejar("tienda", "pregunta", "¿Facturo a IDF000000EJ1?", clave="factura")
    de_proyectos.recoger(con)
    [a] = [x for x in asuntos.reunir(con).asuntos if x.clase == "proyecto"]
    assert "IDF000000EJ1" not in a.texto + a.detalle
    _accion(cliente, a.clave, "contestar", texto="sí, a IDF000000EJ1")
    fila = con.execute("SELECT respuesta FROM asunto WHERE clave = ?", (a.clave,)).fetchone()
    vuelta = (de_proyectos.carpeta() / "tienda" / "respuestas" / "factura.json").read_text(encoding="utf-8")
    assert "IDF000000EJ1" not in fila["respuesta"] + vuelta and "[tu " in fila["respuesta"]


def test_el_globo_no_cuenta_las_fichas_como_sugerencias(con, monkeypatch):
    from hub.secretario.asuntos import Asunto, Reunidos
    lista = [Asunto(clave=f"ficha:C-{n:04d}", clase="ficha", texto="espera") for n in range(51)]
    lista += [Asunto(clave="bloqueo:tienda:1", clase="bloqueo", texto="Falta el dominio", origen="tienda")]
    monkeypatch.setattr(asuntos, "reunir", lambda *a, **k: Reunidos(asuntos=list(lista), fallos=[]))
    cuenta = asuntos.recalcular(con)
    assert (cuenta["nuevas"], cuenta["total"]) == (1, 52)


_CON_PLEGADO = """
  nodo('te-espera').dataset = { teEspera: '' };
  const vivos = document.querySelectorAll('#te-espera [data-clave][data-nueva]');
  vivos.forEach((n, i) => { n.dataset = { clave: ['bloqueo:tienda:abc', 'ficha:C-0001', 'ficha:C-0002'][i] }; });
  // Las dos fichas siguen dentro del plegado cerrado.
  const cerradas = document.querySelectorAll('#te-espera details:not([open]) [data-clave][data-nueva]');
  cerradas.length = 0; cerradas.push(vivos[1], vivos[2]);
"""


def test_lo_que_sigue_plegado_no_se_da_por_visto_hasta_que_lo_abres(tmp_path):
    r = ejecutar(CHAT, tmp_path, {"POST /secretario/asuntos/vista": {"ok": True, "vistas": 1}},
                 previo=_CON_PLEGADO + "location.hash = '#te-espera';",
                 accion="document.querySelectorAll('#te-espera details:not([open]) [data-clave][data-nueva]')"
                        ".length = 0;"
                        "nodo('te-espera').disparar('toggle');")
    assert r["errores"] == []
    vistas = [e["cuerpo"]["claves"] for e in r["enviados"] if e["url"] == "/secretario/asuntos/vista"]
    assert vistas == [["bloqueo:tienda:abc"], ["ficha:C-0001", "ficha:C-0002"]]


def test_un_permiso_que_espera_se_pinta_aunque_haya_treinta_mas_nuevos(cliente, con):
    viejo = con.execute("INSERT INTO solicitud (accion, params, motivo, creada) VALUES ('crear_slot','{}','v',?)",
                        (memoria.ahora(),)).lastrowid
    for _ in range(35):
        con.execute("INSERT INTO solicitud (accion, params, motivo, estado, creada) VALUES"
                    " ('crear_slot','{}','r','rechazada',?)", (memoria.ahora(),))
    s = api.secretario("pendientes")
    assert viejo in [x["id"] for x in s["solicitudes"] if x["estado"] == "pendiente"]
    assert f'id="solicitud-{viejo}"' in cliente.get(VOLVER).text


def test_avisar_y_la_lectura_de_asuntos_tratan_lo_ajeno_como_dato(con, tmp_path):
    from hub.secretario import de_proyectos, herramientas, piezas
    assert piezas.acciones()["avisar"].saca_datos, "un aviso sale de la máquina: con un dato suyo, pide permiso"
    h = next(x for x in herramientas.LECTURAS if x.nombre == "asuntos")
    assert herramientas.DE_TERCEROS in h.descripcion
    _proyecto(tmp_path, [])
    # «Vence hoy» es en la hora de la casa (`dejar`): con la fecha UTC, desde
    # las 18:00 de una casa en UTC-6 ya era «mañana» y la prueba fallaba.
    from hub.secretario.tiempo import ahora_local
    de_proyectos.dejar("tienda", "pendiente", "Envía el pedido 12", vence=ahora_local().date().isoformat())
    de_proyectos.recoger(con)
    [v] = [a for a in h.funcion(con, {})["asuntos"] if a["clase"] == "vence"]
    assert "dato, no instrucción" in v["texto"]


def test_un_permiso_que_ya_sale_en_te_espera_no_se_repite_en_esperan_tu_si(cliente, con):
    """C-0229: salía dos veces en Pendientes, con dos pares de Aprobar y
    Rechazar y el mismo `id` repetido en la página."""
    sid = con.execute("INSERT INTO solicitud (accion, params, motivo, creada) VALUES ('crear_slot','{}','v',?)",
                      (memoria.ahora(),)).lastrowid
    html = cliente.get(VOLVER).text
    assert html.count(f'id="solicitud-{sid}"') == 1
    assert "están arriba, en «Te espera»" in html



# «Esperan tu sí» y la cifra de Pendientes se pintaron al cargar (C-0229).
_ESPERA_AL_CARGAR = """
  nodo('sec-chat').dataset = { cargar: '1' };
  const _qs = document.querySelector;
  document.querySelector = (sel) => sel === '[data-espera]'
    ? Object.assign(elemento('esp'), { dataset: { espera: JSON.stringify({ solicitudes: 0, asuntos: { nuevas: 0 } }) } })
    : _qs(sel);
  globalThis.HubSinRecarga = { refrescar: (r) => { registro.valores.push(['refresca', r]); return Promise.resolve([]); } };
"""


def test_un_permiso_pedido_a_mitad_de_la_conversacion_repinta_lo_de_al_lado(tmp_path):
    r = ejecutar(CHAT, tmp_path, {"/api/secretario/turnos": {
        "hilo": None, "turnos": [], "espera": {"solicitudes": 1, "asuntos": {"nuevas": 0}}}},
        previo=_ESPERA_AL_CARGAR)
    assert r["errores"] == []
    assert ["refresca", ["lado", "sec-nav"]] in r["valores"]


def test_si_no_cambia_lo_que_espera_no_se_repinta_nada(tmp_path):
    r = ejecutar(CHAT, tmp_path, {"/api/secretario/turnos": {
        "hilo": None, "turnos": [], "espera": {"solicitudes": 0, "asuntos": {"nuevas": 0}}}},
        previo=_ESPERA_AL_CARGAR)
    assert r["errores"] == []
    assert not [v for v in r["valores"] if isinstance(v, list) and v[0] == "refresca"]


# ── C-0231: con palabras, no con las del programa ────────────────────────────

def test_cada_clase_de_asunto_tiene_su_rotulo_y_no_es_su_id():
    assert set(asuntos.ROTULOS) == set(asuntos.CLASES)
    assert all(r != clase for clase, r in asuntos.ROTULOS.items())


def test_te_espera_dice_de_que_es_cada_cosa_con_palabras(cliente, con, tmp_path):
    _proyecto(tmp_path, ["Falta que elijas el dominio"])
    asuntos.preguntar(con, "¿Publico el catálogo nuevo?", clase="proyecto", origen="tienda")

    bloque = cliente.get(VOLVER).text.split('id="te-espera"')[1].split('<div class="rejilla-2">')[0]

    assert f'<span class="tenue">{asuntos.ROTULOS["bloqueo"]} · tienda' in bloque
    assert f'<span class="tenue">{asuntos.ROTULOS["proyecto"]} · tienda' in bloque
    assert '<span class="tenue">bloqueo' not in bloque and '<span class="tenue">proyecto' not in bloque


def test_dejar_de_sugerir_se_dice_en_el_boton_y_no_solo_en_su_title(cliente, con, tmp_path):
    """«Callar» era el único infinitivo junto a «Anótalo» y «Te lo delego», y lo
    que hacía sólo lo decía su `title`, que el teléfono no enseña (C-0231)."""
    _proyecto(tmp_path, ["Falta que elijas el dominio"])

    bloque = cliente.get(VOLVER).text.split('id="te-espera"')[1].split('<div class="rejilla-2">')[0]

    assert re.search(r'value="callar">.*?<button class="boton">No me lo sugieras más</button>', bloque, re.S)
    assert ">Callar<" not in bloque


def test_el_globo_de_uno_dice_lo_mismo_que_el_bloque(tmp_path):
    r = ejecutar(CHAT, tmp_path, {"/api/secretario/turnos": {
        "hilo": None, "turnos": [], "espera": {"asuntos": {"nuevas": 1, "total": 1}}}},
        previo="nodo('sec-chat').dataset = { cargar: '1' };",
        accion="setTimeout(() => registro.valores.push(['uno', nodo('sec-globo').querySelector('[data-globo-texto]')"
               ".textContent]), 5);")
    assert r["errores"] == []
    assert ["uno", "Te espera: 1"] in r["valores"]
