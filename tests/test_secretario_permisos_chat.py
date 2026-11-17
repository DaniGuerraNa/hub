"""Aprobar sin salir del chat lo que el secretario pide (C-0421).

Para decir que sí a lo que él mismo acababa de pedir había que irse a
Pendientes. La solicitud sale como tarjeta al final del chat, con el texto
exacto y entero de lo que hará, y se decide por la ruta que ya existía.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from hub import api, web
from hub.secretario import memoria

pytestmark = pytest.mark.usefixtures("canal_telegram")

#: Más largo que cualquier recorte razonable: lo que se aprueba se lee entero (395).
TEXTO_LARGO = "Revisa el login y dime qué falta. " * 40


@pytest.fixture
def con():
    c = memoria.conectar()
    yield c
    c.close()


def _pedir(con, accion: str, params: dict, motivo: str = "") -> int:
    return con.execute("INSERT INTO solicitud (accion, params, motivo, creada) VALUES (?, ?, ?, ?)",
                       (accion, json.dumps(params, ensure_ascii=False), motivo, memoria.ahora())).lastrowid


# ── la lectura: una sola, para Pendientes y para el chat ─────────────────────


def test_el_sondeo_del_chat_trae_la_solicitud_pendiente_con_su_texto_entero(con):
    sid = _pedir(con, "escribir_en_sesion", {"slot": 3, "texto": TEXTO_LARGO}, "me lo pediste")

    [p] = api.secretario_turnos()["permisos"]

    assert p["id"] == sid and p["nombre"] == "Escribirle a una sesión de trabajo" and p["motivo"] == "me lo pediste"
    assert ["texto", TEXTO_LARGO] in [list(d) for d in p["datos"]], "entero: es lo que se va a escribir"
    assert p["con_techo"] is True and p["riesgo_rotulo"] == "No tiene vuelta atrás"


def test_una_orden_para_la_pc_viaja_aparte_y_tal_cual(con):
    _pedir(con, "cambiar_en_pc", {"comando": "ipconfig /all"})

    [p] = api.secretario_turnos()["permisos"]

    assert p["orden"] == "ipconfig /all" and p["datos"] == []


def test_resuelta_ya_no_viaja_y_sin_pendientes_la_lista_sale_vacia(con):
    assert api.secretario_turnos()["permisos"] == []
    sid = _pedir(con, "anotar", {"texto": "x"})
    assert len(api.secretario_turnos()["permisos"]) == 1

    memoria.resolver_solicitud(con, sid, "rechazada", solo_pendiente=True)

    assert api.secretario_turnos()["permisos"] == []


def test_sin_nada_pendiente_el_sondeo_no_lee_las_solicitudes(con, monkeypatch):
    """Va cada 1,5 s mientras contesta: la lista sólo se arma si hay alguna."""
    _pedir(con, "anotar", {"texto": "x"})
    con.execute("UPDATE solicitud SET estado = 'hecha'")
    monkeypatch.setattr(api, "secretario_solicitudes", lambda *a, **kw: pytest.fail("no hacía falta leerlas"))

    assert api.secretario_turnos()["permisos"] == []


def test_pendientes_y_el_chat_salen_de_la_misma_lectura(con):
    _pedir(con, "agendar", {"titulo": "Dentista", "minutos_aviso": 30})
    hecha = _pedir(con, "anotar", {"texto": "x"})
    memoria.resolver_solicitud(con, hecha, "rechazada", solo_pendiente=True)

    [del_chat] = api.secretario_turnos()["permisos"]
    de_pendientes = api.secretario()["solicitudes"]

    assert [s["estado"] for s in de_pendientes] == ["rechazada", "pendiente"]
    assert del_chat == json.loads(json.dumps(de_pendientes[1])), "la misma fila, campo a campo"
    assert api.secretario_solicitudes(con, pendientes=True) == [de_pendientes[1]]


def test_una_accion_que_ya_no_existe_se_pinta_igual_con_su_nombre_legible(con):
    _pedir(con, "accion_retirada", {"dato": 1})

    [p] = api.secretario_solicitudes(con, pendientes=True)

    assert p["nombre"] == "accion retirada" and p["con_techo"] is False and p["riesgo_rotulo"] == ""


def test_la_ruta_del_sondeo_los_sirve(tmp_path, monkeypatch, con):
    from hub import db

    def conexion():
        c = db.conectar(tmp_path / "hub.db")
        db.inicializar(c)
        return c

    monkeypatch.setattr(web, "conexion", conexion)
    sid = _pedir(con, "anotar", {"texto": "<img src=x onerror=alert(1)>"})

    d = TestClient(web.app).get("/api/secretario/turnos").json()

    assert [p["id"] for p in d["permisos"]] == [sid]
    assert d["permisos"][0]["datos"] == [["texto", "<img src=x onerror=alert(1)>"]], "tal cual: lo escapa quien pinta"


# ── la pantalla: el marcado y el JavaScript, ejecutado (regla dura 11) ────────

from arnes_js import ejecutar, script_estatico  # noqa: E402

CHAT = script_estatico("formato-chat.js") + "\n" + script_estatico("chat-secretario.js")

#: Un DOM que recuerda lo que se le cuelga: el del arnés tira los hijos, y aquí
#: lo que hay que ver es justo qué tarjeta se pintó, con qué texto y por dónde
#: entró ese texto (`textContent` o `innerHTML`).
DOM = r"""
  globalThis.CREADOS = [];
  const _crear = document.createElement;
  const conHijos = (n) => {
    n.hijos = [];
    n.appendChild = (h) => { n.hijos.push(h); h.padre = n; return h; };
    n.remove = () => { if (n.padre) n.padre.hijos = n.padre.hijos.filter(x => x !== n); };
    return n;
  };
  document.createElement = (etiqueta) => {
    const n = conHijos(_crear(etiqueta));
    n.etiqueta = etiqueta; n.dataset = {}; n.disabled = false;
    globalThis.CREADOS.push(n);
    return n;
  };
  conHijos(nodo('sec-permisos')).hidden = true;
  nodo('sec-chat').dataset = {};
  nodo('sec-texto').placeholder = 'Escríbele';
  nodo('sec-texto').focus = () => registro.valores.push(['foco', nodo('sec-texto').placeholder]);
  // Lo que se ve: las tarjetas colgadas, con su texto y sus botones.
  globalThis.tarjetas = () => nodo('sec-permisos').hijos;
  const todos = (n) => [n, ...(n.hijos || []).flatMap(todos)];
  globalThis.textos = (n) => todos(n).map(x => x.textContent).filter(Boolean);
  globalThis.botones = (n) => todos(n).filter(x => x.etiqueta === 'button');
  globalThis.pulsar = (n, texto) => botones(n).find(b => b.textContent === texto).disparar('click');
  globalThis.conHtml = () => globalThis.CREADOS.filter(x => x.innerHTML).length;
"""

PERMISO = {"id": 7, "accion": "escribir_en_sesion", "nombre": "Escribirle a una sesión de trabajo",
           "motivo": "me lo pediste", "orden": None, "con_techo": True, "riesgo_rotulo": "No tiene vuelta atrás",
           "datos": [["slot", "3"], ["texto", TEXTO_LARGO]]}


def _sondeo(*permisos) -> dict:
    return {"hilo": 1, "turnos": [], "espera": {"solicitudes": len(permisos)}, "vivo": True,
            "permisos": list(permisos)}


#: El primer sondeo, lanzado a mano: en la página lo lanza el reloj cada 6 s.
MIRAR = "globalThis.DOC_OYENTES.visibilitychange.forEach(f => f());"


def _correr(tmp_path, respuestas: dict, accion: str, previo: str = "") -> dict:
    # En el panel (`data-cargar`) el chat pregunta nada más arrancar.
    r = ejecutar(CHAT, tmp_path, respuestas, previo=DOM + "nodo('sec-chat').dataset = { cargar: '1' };" + previo,
                 accion=accion)
    assert r["errores"] == []
    return r


def _decisiones(r: dict) -> list:
    return [(e["url"], e["cuerpo"]) for e in r["enviados"] if "/solicitud/" in e["url"]]


def test_el_chat_trae_el_hueco_de_los_permisos_entre_la_conversacion_y_el_cuadro():
    from jinja2 import Environment, FileSystemLoader

    from arnes_js import PLANTILLAS
    html = Environment(loader=FileSystemLoader(str(PLANTILLAS))).get_template("_chat_secretario.html").render(
        chat={"turnos": [], "ingles": False})
    assert html.index('id="sec-chat"') < html.index('id="sec-permisos"') < html.index('id="sec-escribir"')
    assert 'id="sec-permisos" class="sec-permisos"' in html and "hidden" in html.split('id="sec-permisos"')[1].split(">")[0]


def test_una_solicitud_pendiente_sale_como_tarjeta_con_su_texto_entero_y_tres_botones(tmp_path):
    r = _correr(tmp_path, {"/api/secretario/turnos": _sondeo(PERMISO)}, """
      const [t] = tarjetas();
      registro.valores.push(['tarjetas', tarjetas().length, nodo('sec-permisos').hidden, t.dataset.sid, t.className]);
      registro.valores.push(['botones', botones(t).map(b => [b.textContent, b.className, b.type])]);
      registro.valores.push(['textos', textos(t)]);
    """)
    assert ["tarjetas", 1, False, "7", "permiso con-techo"] in r["valores"]
    # «Aprobar» en el tono de aceptar y no `.cta`: hay una tarjeta por permiso y
    # puede haber varias; `.cta` es una por región (C-0402, tras la revisión).
    assert ["botones", [["Rechazar", "boton", "button"], ["Rechazar y decir por qué", "boton", "button"],
                        ["Aprobar", "boton aceptar", "button"]]] in r["valores"]
    [textos] = [v[1] for v in r["valores"] if isinstance(v, list) and v[0] == "textos"]
    assert textos[:3] == ["Pide tu permiso", "Escribirle a una sesión de trabajo", "me lo pediste"]
    assert TEXTO_LARGO in textos, "entero: se aprueba viendo el texto exacto"
    assert "No tiene vuelta atrás" in textos


def test_lo_que_escribe_el_modelo_sale_como_texto_y_nunca_como_html(tmp_path):
    malo = "<img src=x onerror=alert(1)>"
    permiso = PERMISO | {"nombre": malo, "motivo": malo, "orden": malo, "riesgo_rotulo": malo,
                         "datos": [[malo, malo]]}
    r = _correr(tmp_path, {"/api/secretario/turnos": _sondeo(permiso)}, """
      registro.valores.push(['pintado', textos(tarjetas()[0]).filter(x => x.includes('onerror')).length, conHtml()]);
    """)
    assert ["pintado", 6, 0] in r["valores"], "las seis veces por textContent, ninguna por innerHTML"


def test_aprobar_manda_la_decision_a_la_ruta_de_siempre_y_vuelve_a_mirar(tmp_path):
    r = _correr(tmp_path, {"/api/secretario/turnos": _sondeo(PERMISO),
                           "POST /api/secretario/solicitud/7": {"ok": True, "error": None}}, """
      pulsar(tarjetas()[0], 'Aprobar');
    """)
    assert _decisiones(r) == [("/api/secretario/solicitud/7", {"decision": "aprobar"})]
    assert [e["metodo"] for e in r["enviados"] if "/solicitud/" in e["url"]] == ["POST"]
    # Lo que diga al hacerlo es un turno nuevo: no espera al sondeo lento.
    assert sum("/api/secretario/turnos" in p for p in r["peticiones"]) >= 2, "vuelve a mirar tras decidir"


def test_decidida_la_tarjeta_se_va_y_el_bloque_se_esconde(tmp_path):
    r = _correr(tmp_path, {"/api/secretario/turnos": _sondeo(PERMISO),
                           "POST /api/secretario/solicitud/7": {"ok": True, "error": None}}, """
      // Desde aquí el hub ya no la da por pendiente.
      const _fetch = fetch;
      global.fetch = (url, o) => String(url).includes('/turnos')
        ? Promise.resolve({ json: () => Promise.resolve({ hilo: 1, turnos: [], vivo: true, permisos: [],
                                                          espera: { solicitudes: 0 } }) })
        : _fetch(url, o);
      pulsar(tarjetas()[0], 'Aprobar');
      setTimeout(() => registro.valores.push(['despues', tarjetas().length, nodo('sec-permisos').hidden]), 10);
    """)
    assert ["despues", 0, True] in r["valores"]


def test_dos_toques_seguidos_son_una_sola_decision(tmp_path):
    r = _correr(tmp_path, {"/api/secretario/turnos": _sondeo(PERMISO),
                           "POST /api/secretario/solicitud/7": {"ok": True, "error": None}}, """
      const [t] = tarjetas();
      pulsar(t, 'Aprobar');
      registro.valores.push(['apagados', botones(t).map(b => b.disabled)]);
      pulsar(t, 'Aprobar'); pulsar(t, 'Rechazar');
    """)
    assert _decisiones(r) == [("/api/secretario/solicitud/7", {"decision": "aprobar"})]
    assert ["apagados", [True, True, True]] in r["valores"], "mientras va, no se puede tocar otro"


#: El campo del porqué apunta cuándo recibe el foco: es lo que se ve al abrirlo.
FOCO_CAMPO = """
  const _ce = document.createElement;
  document.createElement = (e) => { const n = _ce(e);
    if (e === 'textarea') n.focus = () => registro.valores.push(['foco-campo']); return n; };
  globalThis.porQue = () => CREADOS.find(x => x.className === 'por-que');
  globalThis.campo = () => CREADOS.find(x => x.etiqueta === 'textarea');
"""


def test_rechazar_y_decir_por_que_abre_el_campo_en_la_tarjeta_y_no_rechaza_todavia(tmp_path):
    """Cambia a propósito la de C-0421, que rechazaba y dejaba «Dile por qué…»
    en el cuadro: lo escrito después iba aparte y, con dos rechazadas, el
    secretario no sabía a cuál contestaba (C-0395)."""
    r = _correr(tmp_path, {"/api/secretario/turnos": _sondeo(PERMISO),
                           "POST /api/secretario/solicitud/7": {"ok": True, "error": None}}, """
      const [t] = tarjetas();
      pulsar(t, 'Rechazar y decir por qué');
      const fila = t.hijos.find(x => x.className === 'botones');
      registro.valores.push(['abierto', !porQue().hidden, fila.hidden, botones(porQue()).map(b => b.textContent),
                             nodo('sec-texto').placeholder]);
    """, previo=FOCO_CAMPO)
    assert _decisiones(r) == [], "abrir el campo no decide nada"
    assert ["abierto", True, True, ["Cancelar", "Rechazar"], "Escríbele"] in r["valores"]
    assert ["foco-campo"] in r["valores"]


def test_rechazar_a_secas_no_abre_el_campo_ni_manda_por_que(tmp_path):
    """Cambia a propósito la de C-0421 (`…no_mueve_el_foco`): ya no hay cuadro
    que preparar; lo que se mira es que no salga el campo ni viaje un porqué."""
    r = _correr(tmp_path, {"/api/secretario/turnos": _sondeo(PERMISO),
                           "POST /api/secretario/solicitud/7": {"ok": True, "error": None}},
                "pulsar(tarjetas()[0], 'Rechazar'); registro.valores.push(['campos', campo() ? 1 : 0]);",
                previo=FOCO_CAMPO)
    assert _decisiones(r) == [("/api/secretario/solicitud/7", {"decision": "rechazar"})]
    assert ["campos", 0] in r["valores"]
    assert not [v for v in r["valores"] if isinstance(v, list) and v[0] in ("foco", "foco-campo")]


def test_mandar_el_motivo_viaja_en_por_que_y_el_chat_se_pone_a_esperar_la_respuesta(tmp_path):
    r = _correr(tmp_path, {"/api/secretario/turnos": _sondeo(PERMISO),
                           "POST /api/secretario/solicitud/7": {"ok": True, "error": None}}, """
      pulsar(tarjetas()[0], 'Rechazar y decir por qué');
      campo().value = '  a la otra sesión, no a ésta  ';
      // Desde aquí el hub tiene su motivo pendiente de contestar; a la
      // segunda vez, ya contestado (si no, el sondeo seguiría sin fin).
      const _fetch = fetch;
      let vueltas = 0;
      const suyo = (estado) => ({ id: 10, hilo: 1, rol: 'dueno', texto: 'a la otra sesión', estado, tarjetas: [] });
      global.fetch = (url, o) => String(url).includes('/turnos')
        ? Promise.resolve({ json: () => Promise.resolve({ hilo: 1, vivo: true, permisos: [], espera: { solicitudes: 0 },
            turnos: [suyo(vueltas++ ? 'listo' : 'pendiente')] }) })
        : _fetch(url, o);
      registro.temporizadores.length = 0;
      pulsar(porQue(), 'Rechazar');
      setTimeout(() => registro.valores.push(['tras', tarjetas().length, nodo('estado-sec').textContent,
                                              registro.temporizadores.includes(1500)]), 5);
    """, previo=FOCO_CAMPO)
    assert _decisiones(r) == [("/api/secretario/solicitud/7",
                               {"decision": "rechazar", "por_que": "a la otra sesión, no a ésta"})]
    assert ["tras", 0, "pensando…", True] in r["valores"], "la tarjeta se va y el chat espera su respuesta"


def test_un_porque_en_blanco_es_rechazar_a_secas(tmp_path):
    r = _correr(tmp_path, {"/api/secretario/turnos": _sondeo(PERMISO),
                           "POST /api/secretario/solicitud/7": {"ok": True, "error": None}}, """
      pulsar(tarjetas()[0], 'Rechazar y decir por qué');
      campo().value = '   ';
      pulsar(porQue(), 'Rechazar');
    """, previo=FOCO_CAMPO)
    assert _decisiones(r) == [("/api/secretario/solicitud/7", {"decision": "rechazar"})]


def test_si_el_hub_no_contesta_el_motivo_escrito_sigue_en_la_tarjeta(tmp_path):
    r = _correr(tmp_path, {"/api/secretario/turnos": _sondeo(PERMISO)}, """
      const _fetch = fetch;
      global.fetch = (url, o) => String(url).includes('/solicitud/')
        ? (registro.enviados.push({ url: String(url), cuerpo: JSON.parse(o.body) }), Promise.reject(new Error('sin red')))
        : _fetch(url, o);
      const [t] = tarjetas();
      pulsar(t, 'Rechazar y decir por qué');
      campo().value = 'no era eso';
      pulsar(porQue(), 'Rechazar');
      setTimeout(() => {
        registro.valores.push(['tras-fallo', tarjetas().length, campo().value, !porQue().hidden,
                               botones(porQue()).map(b => b.disabled), nodo('estado-sec').dataset.tono]);
        pulsar(porQue(), 'Rechazar');
      }, 5);
    """, previo=FOCO_CAMPO)
    assert ["tras-fallo", 1, "no era eso", True, [False, False], "error"] in r["valores"]
    assert [c for _, c in _decisiones(r)] == [{"decision": "rechazar", "por_que": "no era eso"}] * 2


def test_si_ya_estaba_resuelta_lo_escrito_se_queda_en_la_tarjeta_hasta_quitarla(tmp_path):
    r = _correr(tmp_path, {"/api/secretario/turnos": _sondeo(PERMISO),
                           "POST /api/secretario/solicitud/7": {"ok": False, "error": "Esa solicitud ya estaba resuelta."}}, """
      const _fetch = fetch;
      global.fetch = (url, o) => String(url).includes('/turnos')
        ? Promise.resolve({ json: () => Promise.resolve({ hilo: 1, turnos: [], vivo: true, permisos: [],
                                                          espera: { solicitudes: 0 } }) })
        : _fetch(url, o);
      pulsar(tarjetas()[0], 'Rechazar y decir por qué');
      campo().value = 'no era eso';
      pulsar(porQue(), 'Rechazar');
      setTimeout(() => {
        registro.valores.push(['queda', tarjetas().length, campo().value, botones(porQue()).map(b => b.textContent),
                               nodo('estado-sec').textContent]);
        pulsar(porQue(), 'Quitar');
        registro.valores.push(['quitada', tarjetas().length, nodo('sec-permisos').hidden]);
      }, 10);
    """, previo=FOCO_CAMPO)
    assert ["queda", 1, "no era eso", ["Quitar", "Rechazar"], "Esa solicitud ya estaba resuelta."] in r["valores"]
    assert ["quitada", 0, True] in r["valores"]


def test_cancelar_cierra_el_campo_y_vuelven_los_tres_botones(tmp_path):
    r = _correr(tmp_path, {"/api/secretario/turnos": _sondeo(PERMISO)}, """
      const [t] = tarjetas();
      pulsar(t, 'Rechazar y decir por qué');
      campo().value = 'a medias';
      pulsar(porQue(), 'Cancelar');
      const fila = t.hijos.find(x => x.className === 'botones');
      registro.valores.push(['cerrado', porQue().hidden, fila.hidden]);
      pulsar(t, 'Rechazar y decir por qué');
      registro.valores.push(['otra-vez', campo().value, CREADOS.filter(x => x.etiqueta === 'textarea').length]);
    """, previo=FOCO_CAMPO)
    assert _decisiones(r) == []
    assert ["cerrado", True, False] in r["valores"]
    assert ["otra-vez", "a medias", 1] in r["valores"], "el mismo campo, con lo que llevaba"


def test_la_tarjeta_dice_cuando_se_pidio(tmp_path):
    r = _correr(tmp_path, {"/api/secretario/turnos": _sondeo(PERMISO | {"creada_local": "2026-11-13 09:40"})}, """
      registro.valores.push(['textos', textos(tarjetas()[0])]);
    """)
    [textos] = [v[1] for v in r["valores"] if isinstance(v, list) and v[0] == "textos"]
    assert "Lo pidió el 2026-11-13 09:40" in textos


def test_la_tarjeta_dice_cuando_se_pidio_con_lo_que_trae_el_sondeo_de_verdad(tmp_path, con, monkeypatch):
    """Tras la revisión: el JS leía `creada_local` y el sondeo ya no la traía
    (las fechas pasaron a `reloj.cuando`); el test de arriba la fingía. Aquí
    la tarjeta se pinta con lo que devuelve `api.secretario_turnos`."""
    from datetime import datetime, timezone

    monkeypatch.setenv("TZ", "America/Mexico_City")
    ano = datetime.now(timezone.utc).year
    sid = _pedir(con, "anotar", {"texto": "x"})
    con.execute("UPDATE solicitud SET creada = ? WHERE id = ?", (f"{ano}-03-11T05:30:00+00:00", sid))
    sondeo = json.loads(json.dumps(api.secretario_turnos()))

    r = _correr(tmp_path, {"/api/secretario/turnos": sondeo}, "registro.valores.push(['textos', textos(tarjetas()[0])]);")

    assert sondeo["permisos"][0]["creada_local"] == "10/03 23:30", "la hora de la casa, como `reloj.cuando`"
    [textos] = [v[1] for v in r["valores"] if isinstance(v, list) and v[0] == "textos"]
    assert "Lo pidió el 10/03 23:30" in textos


def test_al_abrir_el_campo_la_tarjeta_se_desplaza_hasta_sus_botones(tmp_path):
    """Tras la revisión: en el panel, con dos solicitudes, «Cancelar» y
    «Rechazar» quedaban cortados bajo el tope de la caja de permisos."""
    r = _correr(tmp_path, {"/api/secretario/turnos": _sondeo(PERMISO)}, """
      pulsar(tarjetas()[0], 'Rechazar y decir por qué');
      const fila = porQue().hijos.find(x => x.className === 'botones');
      registro.valores.push(['a-la-vista', (fila.vistos || []).length, (fila.vistos || [])[0]]);
    """, previo=FOCO_CAMPO + """
      const _ce2 = document.createElement;
      document.createElement = (e) => { const n = _ce2(e);
        n.scrollIntoView = (o) => { (n.vistos ||= []).push(o); }; return n; };
    """)
    assert ["a-la-vista", 1, {"block": "nearest"}] in r["valores"]


def test_pendientes_lleva_el_porque_plegado_con_el_formulario_de_rechazar(tmp_path, monkeypatch, con):
    from hub import db

    def conexion():
        c = db.conectar(tmp_path / "hub.db")
        db.inicializar(c)
        return c

    monkeypatch.setattr(web, "conexion", conexion)
    sid = _pedir(con, "anotar", {"texto": "x"})

    html = TestClient(web.app).get("/secretario?p=pendientes").text

    fila = html.split(f'id="solicitud-{sid}"')[1].split('<div class="fila')[0]
    assert f'id="rechazar-{sid}"' in fila
    assert f'<textarea name="por_que" form="rechazar-{sid}"' in fila
    assert '<details class="por-que">' in fila and "<details class=\"por-que\" open" not in fila


def test_si_ya_estaba_resuelta_lo_dice_y_quita_la_tarjeta(tmp_path):
    r = _correr(tmp_path, {"/api/secretario/turnos": _sondeo(PERMISO),
                           "POST /api/secretario/solicitud/7": {"ok": False, "error": "Esa solicitud ya estaba resuelta."}}, """
      const _fetch = fetch;
      global.fetch = (url, o) => String(url).includes('/turnos')
        ? Promise.resolve({ json: () => Promise.resolve({ hilo: 1, turnos: [], vivo: true, permisos: [],
                                                          espera: { solicitudes: 0 } }) })
        : _fetch(url, o);
      pulsar(tarjetas()[0], 'Aprobar');
      setTimeout(() => registro.valores.push(['despues', tarjetas().length, nodo('estado-sec').textContent,
                                              nodo('estado-sec').dataset.tono]), 10);
    """)
    assert ["despues", 0, "Esa solicitud ya estaba resuelta.", "aviso"] in r["valores"]


def test_si_el_hub_no_contesta_la_tarjeta_sigue_y_se_puede_volver_a_tocar(tmp_path):
    r = _correr(tmp_path, {"/api/secretario/turnos": _sondeo(PERMISO)}, """
      const _fetch = fetch;
      global.fetch = (url, o) => String(url).includes('/solicitud/')
        ? (registro.enviados.push({ url: String(url), cuerpo: JSON.parse(o.body) }), Promise.reject(new Error('sin red')))
        : _fetch(url, o);
      const [t] = tarjetas();
      pulsar(t, 'Aprobar');
      setTimeout(() => {
        registro.valores.push(['tras-fallo', tarjetas().length, botones(t).map(b => b.disabled),
                               nodo('estado-sec').dataset.tono]);
        pulsar(t, 'Aprobar');
      }, 5);
    """)
    assert ["tras-fallo", 1, [False, False, False], "error"] in r["valores"]
    assert len(_decisiones(r)) == 2, "el segundo toque sí sale"


def test_un_sondeo_tras_otro_no_rehace_la_tarjeta_que_ya_esta(tmp_path):
    r = _correr(tmp_path, {"/api/secretario/turnos": _sondeo(PERMISO, PERMISO | {"id": 5, "nombre": "Anotar"})}, f"""
      const antes = tarjetas().slice();
      {MIRAR}
      setTimeout(() => registro.valores.push(['mismas', tarjetas().length, tarjetas().every((t, i) => t === antes[i]),
                                              tarjetas().map(t => t.dataset.sid)]), 5);
    """)
    assert sum("/api/secretario/turnos" in p for p in r["peticiones"]) == 2, "el segundo sondeo sí se hizo"
    # En el orden en que las pidió: la más vieja arriba.
    assert ["mismas", 2, True, ["5", "7"]] in r["valores"]


def test_sin_el_bloque_en_la_pagina_el_chat_arranca_igual(tmp_path):
    r = ejecutar(CHAT, tmp_path, {"/api/secretario/turnos": _sondeo(PERMISO)},
                 previo="const _g = document.getElementById; document.getElementById = (id) => "
                        "id === 'sec-permisos' ? null : _g(id); nodo('sec-chat').dataset = { cargar: '1' };")
    assert r["errores"] == []


def test_en_su_pantalla_con_algo_esperando_pregunta_al_cargar_sin_aguardar_al_sondeo_lento(tmp_path):
    previo = DOM + "document.querySelector = () => ({ dataset: { espera: JSON.stringify({ solicitudes: %d }) } });"
    con_una = ejecutar(CHAT, tmp_path, {"/api/secretario/turnos": _sondeo(PERMISO)}, previo=previo % 1,
                       accion="registro.valores.push(['tarjetas', tarjetas().length]);")
    sin_nada = ejecutar(CHAT, tmp_path, {"/api/secretario/turnos": _sondeo()}, previo=previo % 0)
    assert con_una["errores"] == [] and ["tarjetas", 1] in con_una["valores"]
    assert not [p for p in sin_nada["peticiones"] if "/turnos" in p], "sin nada que aprobar, como hasta ahora"


def test_el_alto_de_la_caja_de_permisos_no_depende_de_que_el_padre_tenga_altura():
    """Un `max-height` en % sólo cuenta si el padre tiene altura definida: en
    el panel o en el teléfono podía no tenerla, y la caja crecería sin tope
    hasta sacar el cuadro de escribir de la pantalla."""
    import re

    from arnes_js import ESTATICOS
    css = (ESTATICOS / "chat-secretario.css").read_text(encoding="utf-8")
    [regla] = re.findall(r"\.sec-permisos \{([^}]*)\}", css)
    topes = re.findall(r"max-height:([^;]+);", regla)
    assert topes and all("%" not in t for t in topes), topes
    # Primero en `vh`, para el navegador que no sabe de `dvh`; después en `dvh`.
    assert ["dvh" in t for t in topes] == [False, True] and "vh" in topes[0]
    assert "overflow-y:auto" in regla
