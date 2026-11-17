"""Releer lo ya hablado con el secretario (C-0393).

El chat sólo pintaba el hilo abierto: cerrado un hilo (30 minutos sin hablar),
al abrir la app por la mañana el chat salía vacío y, para releer una respuesta
de ayer, había que pedirla y pagarla otra vez. Lo anterior se lee de `turno`,
en sólo lectura y por páginas hacia atrás, con la misma forma que el sondeo;
el modelo sigue naciendo limpio en cada hilo (299).
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from hub import api, web
from hub.secretario import conversacion, memoria


@pytest.fixture
def con():
    c = memoria.conectar()
    yield c
    c.close()


def _hilo(con, *, cerrado: bool = True, titulo: str = "", resumen: str = "",
          abierto: str = "2026-11-10T09:15:00+00:00") -> int:
    return con.execute("INSERT INTO hilo (abierto, ultimo, cerrado, titulo, resumen) VALUES (?, ?, ?, ?, ?)",
                       (abierto, abierto, abierto if cerrado else None, titulo, resumen)).lastrowid


def _turno(con, hilo: int, rol: str, texto: str, **extra) -> int:
    campos = {"hilo": hilo, "rol": rol, "texto": texto, "estado": "listo", "creado": memoria.ahora(), **extra}
    return con.execute(f"INSERT INTO turno ({', '.join(campos)}) VALUES ({', '.join('?' * len(campos))})",
                       list(campos.values())).lastrowid


# ── la lectura ───────────────────────────────────────────────────────────────


def test_lo_anterior_trae_turnos_de_hilos_cerrados_de_mas_viejo_a_mas_nuevo_con_su_hilo(con):
    ayer = _hilo(con, titulo="El dentista", resumen="Movió la cita al jueves.")
    hoy = _hilo(con, cerrado=False, abierto="2026-11-13T08:00:00+00:00")
    a = _turno(con, ayer, "dueno", "¿Cuándo es el dentista?")
    b = _turno(con, ayer, "secretario", "El jueves a las 10.")
    c = _turno(con, hoy, "dueno", "Buenos días")

    d = api.secretario_anteriores()

    assert [(t["id"], t["hilo"]) for t in d["turnos"]] == [(a, ayer), (b, ayer), (c, hoy)]
    assert d["hay_mas"] is False
    assert d["hilos"][str(ayer)] == {"titulo": "El dentista", "abierto_local": d["hilos"][str(ayer)]["abierto_local"],
                                     "cerrado": True, "resumido": True}
    assert d["hilos"][str(hoy)]["cerrado"] is False and d["hilos"][str(hoy)]["resumido"] is False


def test_la_fecha_del_separador_sale_en_la_hora_de_la_casa_como_las_demas(con, monkeypatch):
    """Tras la revisión: salía en crudo («2026-11-11 10:40»). Es la pieza
    `local` de `reloj.cuando`, la de todas las fechas de pantalla (C-0396)."""
    from datetime import datetime, timezone

    monkeypatch.setenv("TZ", "America/Mexico_City")
    ano = datetime.now(timezone.utc).year
    h = _hilo(con, abierto=f"{ano}-03-11T05:30:00+00:00")
    _turno(con, h, "dueno", "hola")

    assert api.secretario_anteriores()["hilos"][str(h)]["abierto_local"] == "10/03 23:30"


def test_un_antes_de_que_no_cabe_en_sqlite_no_da_un_500(con):
    """Tras la revisión: más de 2^63 daba un `OverflowError`; y `desde` del sondeo, igual."""
    h = _hilo(con)
    ids = [_turno(con, h, "dueno", f"m{i}") for i in range(3)]
    cliente = TestClient(web.app, raise_server_exceptions=False)

    r = cliente.get("/api/secretario/anteriores?antes_de=99999999999999999999999")

    assert r.status_code == 200 and [t["id"] for t in r.json()["turnos"]] == ids
    assert cliente.get("/api/secretario/turnos?desde=99999999999999999999999").status_code == 200


def test_pedir_antes_de_un_turno_pagina_sin_repetir_ni_saltar_y_dice_si_hay_mas(con):
    hilos = [_hilo(con) for _ in range(3)]
    ids = [_turno(con, hilos[i % 3], "dueno" if i % 2 else "secretario", f"mensaje {i}") for i in range(23)]

    vistos, antes_de, paginas = [], 0, []
    while True:
        d = api.secretario_anteriores(antes_de, n=10)
        paginas.append((len(d["turnos"]), d["hay_mas"]))
        vistos = [t["id"] for t in d["turnos"]] + vistos
        if not d["hay_mas"]:
            break
        antes_de = d["turnos"][0]["id"]

    assert vistos == ids, "todos, una vez cada uno y en orden"
    assert paginas == [(10, True), (10, True), (3, False)]


def test_el_tamano_de_pagina_se_queda_entre_uno_y_el_tope(con):
    h = _hilo(con)
    for i in range(api.ANTERIORES_TOPE + 5):
        _turno(con, h, "dueno", f"m{i}")

    assert len(api.secretario_anteriores(0, n=0)["turnos"]) == 1
    assert len(api.secretario_anteriores(0, n=10_000)["turnos"]) == api.ANTERIORES_TOPE


def test_lo_anterior_lleva_cita_tarjetas_y_adjuntos_con_la_misma_forma_que_el_sondeo(con):
    h = _hilo(con, cerrado=False)
    citado = _turno(con, h, "secretario", "Dos cosas: el dentista y el banco.")
    _turno(con, h, "dueno", "la segunda", responde_a=citado,
           adjuntos=json.dumps(["_secretario/20261113/captura.png"]))
    _turno(con, h, "secretario", "Hecho.", tarjetas=json.dumps([{"tipo": "lista", "titulo": "Banco", "filas": [["a"]]}]),
           actividad=json.dumps({"estado": "listo"}))

    del_sondeo = api.secretario_turnos()["turnos"]
    de_lo_anterior = api.secretario_anteriores()["turnos"]

    assert de_lo_anterior == del_sondeo, "turno a turno, campo a campo"
    assert de_lo_anterior[1]["cita"]["id"] == citado and de_lo_anterior[1]["adjuntos"] == ["_secretario/20261113/captura.png"]
    assert de_lo_anterior[2]["tarjetas"][0]["titulo"] == "Banco"


def test_lo_anterior_se_lee_sin_crear_ni_migrar_la_memoria():
    assert not memoria.ruta().exists()

    assert api.secretario_anteriores() == {"turnos": [], "hilos": {}, "hay_mas": False}
    assert not memoria.ruta().exists(), "un GET que sólo mira no le crea la base al servicio (C-0099)"


def test_una_memoria_ilegible_se_lee_como_vacia_y_no_da_un_500(monkeypatch):
    import sqlite3

    def rota():
        raise sqlite3.OperationalError("database is locked")
    monkeypatch.setattr(api, "_memoria_secretario", rota)
    # La racha del registro es del módulo: se devuelve como estaba al acabar.
    monkeypatch.setitem(api._MEMORIA_SIN_LEER, "racha", False)

    r =TestClient(web.app).get("/api/secretario/anteriores")

    assert r.status_code == 200 and r.json() == {"turnos": [], "hilos": {}, "hay_mas": False}


def test_turnos_sin_parametros_nuevos_devuelve_lo_mismo_que_antes(con):
    uno, otro = _hilo(con), _hilo(con, cerrado=False)
    a = _turno(con, uno, "dueno", "a")
    b = _turno(con, otro, "dueno", "b")
    c = _turno(con, otro, "secretario", "c")
    _turno(con, uno, "secretario", "d")

    assert [t["id"] for t in conversacion.turnos(con, otro)] == [b, c], "sólo su hilo, del más viejo al más nuevo"
    assert [t["id"] for t in conversacion.turnos(con, otro, b)] == [c], "`desde` sigue siendo «después de»"
    assert [t["id"] for t in conversacion.turnos(con, None, antes_de=c, n=2)] == [a, b]


def test_la_ruta_sirve_lo_anterior_y_antes_de_cero_es_lo_ultimo(con):
    h = _hilo(con)
    ids = [_turno(con, h, "dueno", f"m{i}") for i in range(5)]
    cliente = TestClient(web.app)

    ultimo = cliente.get("/api/secretario/anteriores?n=2").json()
    anterior = cliente.get(f"/api/secretario/anteriores?antes_de={ids[3]}&n=2").json()

    assert [t["id"] for t in ultimo["turnos"]] == ids[3:] and ultimo["hay_mas"] is True
    assert [t["id"] for t in anterior["turnos"]] == ids[1:3]
    assert cliente.get("/api/secretario/anteriores?antes_de=-4&n=2").json() == ultimo


# ── el chat, ejecutado (regla dura 11) ───────────────────────────────────────

from arnes_js import PLANTILLAS, ejecutar, script_estatico  # noqa: E402

CHAT = script_estatico("formato-chat.js") + "\n" + script_estatico("chat-secretario.js")

#: Un `#sec-chat` con hijos de verdad: orden, `insertBefore`, hermanos, búsqueda
#: por clase y por `data-*`, y un alto que crece con lo que se cuelga (globo 40,
#: separador 20, botón 30). El del arnés tira los hijos y siempre «encuentra»
#: lo que se busca, y aquí hay que ver justo dónde se pinta cada cosa y cuánto
#: se mueve el scroll. Encima, un servidor de lo anterior que pagina de verdad
#: sobre `TODOS` y `HILOS`.
DOM = r"""
  const casa = (n, sel) => {
    let m;
    if ((m = /^\.([\w-]+)$/.exec(sel))) return String(n.className || '').split(/\s+/).includes(m[1]);
    if ((m = /^\[data-(\w+)="([^"]*)"\]$/.exec(sel))) return !!n.dataset && String(n.dataset[m[1]]) === m[2];
    if ((m = /^\[data-(\w+)\]$/.exec(sel))) return !!n.dataset && n.dataset[m[1]] !== undefined;
    if ((m = /^#([\w-]+)$/.exec(sel))) return n.id === m[1];
    if (/^[a-z]+$/.test(sel)) return n.etiqueta === sel;
    return false;
  };
  const ALTOS = { p: 20, button: 30 };
  globalThis.hacer = (etiqueta) => {
    const clases = new Set();
    const n = {
      etiqueta, tagName: String(etiqueta).toUpperCase(), dataset: {}, textContent: '', innerHTML: '', hidden: false,
      alto: ALTOS[etiqueta] || 40, padre: null, hijos: [], style: {}, disabled: false,
      classList: { add: c => clases.add(c), remove: c => clases.delete(c), contains: c => clases.has(c),
                   toggle(c, f) { const v = f === undefined ? !clases.has(c) : f; v ? clases.add(c) : clases.delete(c); return v; } },
      appendChild(h) { if (h.padre) h.remove(); n.hijos.push(h); h.padre = n; return h; },
      insertBefore(h, ref) {
        if (h.padre) h.remove();
        const i = ref ? n.hijos.indexOf(ref) : -1;
        if (i < 0) n.hijos.push(h); else n.hijos.splice(i, 0, h);
        h.padre = n; return h;
      },
      remove() { if (n.padre) { n.padre.hijos.splice(n.padre.hijos.indexOf(n), 1); n.padre = null; } },
      replaceWith(otro) { const p = n.padre; p.hijos[p.hijos.indexOf(n)] = otro; otro.padre = p; n.padre = null; },
      get previousElementSibling() { const i = n.padre ? n.padre.hijos.indexOf(n) : -1; return i > 0 ? n.padre.hijos[i - 1] : null; },
      get parentNode() { return n.padre; },
      querySelector(sel) { return n.hijos.find(h => casa(h, sel)) || null; },
      querySelectorAll(sel) { return n.hijos.filter(h => casa(h, sel)); },
      closest(sel) { let x = n; while (x) { if (casa(x, sel)) return x; x = x.padre; } return null; },
      _oyentes: {},
      addEventListener(ev, fn) { (n._oyentes[ev] ||= []).push(fn); },
      disparar(ev, arg) { (n._oyentes[ev] || []).forEach(f => f(arg || {})); },
      setAttribute() {}, getAttribute() { return null; }, focus() {},
      scrollIntoView() {
        registro.valores.push(['visto', n.className, n.dataset.sep || String(n.dataset.turno || '')]);
        // Dentro del chat, lo deja arriba de la caja, como `block: 'start'`.
        if (n.padre && n.padre.id === 'sec-chat') {
          const i = n.padre.hijos.indexOf(n);
          n.padre.scrollTop = n.padre.hijos.slice(0, i).reduce((s, h) => s + (h.hidden ? 0 : h.alto), 0);
        }
      },
      getBoundingClientRect() { return { top: 0, bottom: 0 }; },
    };
    Object.defineProperty(n, 'className', {
      get: () => [...clases].join(' '),
      set: v => { clases.clear(); String(v).split(/\s+/).filter(Boolean).forEach(c => clases.add(c)); },
    });
    return n;
  };
  document.createElement = globalThis.hacer;

  // El chat: el botón arriba, los globos que pintó el servidor y, si se pide, las ideas.
  globalThis.montarChat = (globos, { conBoton = true, conIdeas = false } = {}) => {
    const chat = hacer('div');
    chat.id = 'sec-chat';
    let tope = 0;
    Object.defineProperty(chat, 'scrollHeight', { get: () => chat.hijos.reduce((s, h) => s + (h.hidden ? 0 : h.alto), 0) });
    chat.clientHeight = 200;
    Object.defineProperty(chat, 'scrollTop', {
      get: () => tope, set: v => { tope = Math.max(0, Math.min(Number(v) || 0, chat.scrollHeight - chat.clientHeight)); } });
    const propios = { 'sec-chat': chat };
    if (conBoton) {
      const b = hacer('button'); b.id = 'sec-anteriores'; b.className = 'chip-modo'; b.hidden = true;
      chat.appendChild(b); propios['sec-anteriores'] = b;
    }
    for (const g of globos) {
      const n = hacer('div');
      n.className = `burbuja ${g.rol}`;
      Object.assign(n.dataset, { turno: String(g.id), hilo: String(g.hilo), texto: g.texto, estado: g.estado || 'listo',
                                 tarjetas: '[]', adjuntos: '[]', cita: 'null', modelo: '', segundos: '' });
      chat.appendChild(n);
    }
    if (conIdeas) {
      const v = hacer('div'); v.id = 'sec-vacio'; v.className = 'vacio-chat'; chat.appendChild(v); propios['sec-vacio'] = v;
    }
    const _g = document.getElementById;
    document.getElementById = (id) => (id in propios ? propios[id]
                                       : id === 'sec-anteriores' && !conBoton ? null : _g(id));
    globalThis.CHAT = chat;
    return chat;
  };
  // Lo que se ve, de arriba abajo: un globo es «turno:hilo», un separador «— su texto».
  globalThis.vista = () => CHAT.hijos.filter(h => !h.hidden).map(h =>
    h.classList.contains('burbuja') ? `${h.dataset.turno}:${h.dataset.hilo}`
    : h.classList.contains('sep-hilo') ? `— ${h.textContent}` : h.id ? `#${h.id}` : h.className);

  // El servidor de lo anterior, sobre TODOS (de más viejo a más nuevo) y HILOS.
  globalThis.TODOS = []; globalThis.HILOS = {};
  const _fetch = global.fetch;
  global.fetch = (url, o) => {
    const u = String(url);
    if (!u.includes('/api/secretario/anteriores')) return _fetch(url, o);
    registro.peticiones.push(u);
    const q = new URL(u, 'http://hub').searchParams;
    const antes = Number(q.get('antes_de')) > 0 ? Number(q.get('antes_de')) : Infinity;
    const n = Number(q.get('n')) || 30;
    const previos = TODOS.filter(t => t.id < antes);
    const pagina = previos.slice(-n);
    const hilos = {};
    pagina.forEach(t => { hilos[String(t.hilo)] = HILOS[t.hilo]; });
    return Promise.resolve({ json: () => Promise.resolve({ turnos: pagina, hilos, hay_mas: previos.length > pagina.length }) });
  };
"""


def _t(id: int, hilo: int, rol: str = "secretario", texto: str = "", **extra) -> dict:
    return {"id": id, "hilo": hilo, "rol": rol, "texto": texto or f"mensaje {id}", "estado": "listo",
            "tarjetas": [], "adjuntos": [], "cita": None, **extra}


AYER = {"titulo": "El dentista", "abierto_local": "2026-11-12 10:15", "cerrado": True, "resumido": True}
HOY = {"titulo": "", "abierto_local": "2026-11-13 08:00", "cerrado": False, "resumido": False}


def _correr(tmp_path, pintados: list[dict], todos: list[dict], hilos: dict, accion: str = "",
            respuestas: dict | None = None, montar: str = "", mas_previo: str = "") -> dict:
    previo = (DOM + f"montarChat({json.dumps(pintados)}{', ' + montar if montar else ''});"
              f"TODOS = {json.dumps(todos)}; HILOS = {json.dumps(hilos)};" + mas_previo)
    r = ejecutar(CHAT, tmp_path, respuestas or {"/api/secretario/turnos": {"hilo": 2, "turnos": []}},
                 previo=previo, accion=accion)
    assert r["errores"] == []
    return r


def _valor(r: dict, clave: str):
    hallados = [v[1:] for v in r["valores"] if isinstance(v, list) and v and v[0] == clave]
    assert hallados, f"no se apuntó «{clave}»"
    return hallados[-1] if len(hallados[-1]) > 1 else hallados[-1][0]


def test_el_chat_lleva_el_boton_arriba_escondido_y_cada_globo_su_hilo():
    from jinja2 import Environment, FileSystemLoader

    html = Environment(loader=FileSystemLoader(str(PLANTILLAS))).get_template("_chat_secretario.html").render(
        chat={"turnos": [_t(5, 2)], "ingles": False})
    boton = html.split('id="sec-anteriores"')[1].split(">")[0]
    assert html.index('id="sec-chat"') < html.index('id="sec-anteriores"') < html.index('data-turno="5"')
    assert "hidden" in boton and 'data-hilo="2"' in html


def test_con_un_hilo_cerrado_y_otro_abierto_se_ven_los_dos_con_su_separador(tmp_path):
    todos = [_t(1, 1, "dueno"), _t(2, 1), _t(3, 2, "dueno")]
    r = _correr(tmp_path, [todos[2]], todos, {"1": AYER, "2": HOY},
                accion="registro.valores.push(['vista', vista()]);")
    assert _valor(r, "vista") == [
        "— Conversación del 2026-11-12 10:15 · El dentista · resumida", "1:1", "2:1",
        "— Esta conversación · lo de arriba lo recuerda sólo por su resumen", "3:2"]
    assert [p for p in r["peticiones"] if "anteriores" in p] == ["/api/secretario/anteriores?antes_de=3"], \
        "una vez al abrir, lo que va antes del globo más viejo pintado"


def test_por_la_manana_la_conversacion_de_ayer_sale_con_su_separador(tmp_path):
    """Tras la revisión: sin hilo abierto y con una sola conversación en la
    primera página, salían 30 globos de ayer sin nada que dijera que es
    anterior ni que el secretario ya no la tiene delante."""
    todos = [_t(1, 1, "dueno"), _t(2, 1)]
    r = _correr(tmp_path, [], todos, {"1": AYER}, montar="{ conIdeas: true }",
                respuestas={"/api/secretario/turnos": {"hilo": None, "turnos": []}},
                accion="registro.valores.push(['vista', vista()]);")
    assert _valor(r, "vista") == ["— Conversación del 2026-11-12 10:15 · El dentista · resumida", "1:1", "2:1",
                                  "#sec-vacio"]


def test_con_solo_la_conversacion_de_ahora_no_sale_ningun_separador(tmp_path):
    todos = [_t(1, 2, "dueno"), _t(2, 2)]
    r = _correr(tmp_path, [todos[1]], todos, {"2": HOY}, accion="registro.valores.push(['vista', vista()]);")
    assert _valor(r, "vista") == ["1:2", "2:2"]


def test_el_responder_de_un_globo_de_un_hilo_cerrado_manda_responde_a(tmp_path):
    todos = [_t(1, 1, texto="El jueves a las 10."), _t(3, 2, "dueno")]
    r = _correr(tmp_path, [todos[1]], todos, {"1": AYER, "2": HOY},
                respuestas={"/api/secretario/turnos": {"hilo": 2, "turnos": []},
                            "POST /api/secretario/mensaje": {"ok": True, "hilo": 2, "turno": 9}},
                accion="""
      const globo = CHAT.querySelector('[data-turno="1"]');
      registro.valores.push(['flecha', globo.innerHTML.includes('data-citar')]);
      CHAT.disparar('click', { target: { closest: s => s === '[data-citar]' ? {} : s === '.burbuja' ? globo : null } });
      nodo('sec-texto').value = '¿y a qué hora salgo?';
      nodo('sec-escribir').disparar('submit', { preventDefault(){} });
    """)
    assert _valor(r, "flecha") is True
    [mensaje] = [e["cuerpo"] for e in r["enviados"] if e["url"] == "/api/secretario/mensaje"]
    assert mensaje["responde_a"] == 1 and mensaje["texto"] == "¿y a qué hora salgo?"


def test_cargar_lo_anterior_no_lo_lee_en_voz_alta_ni_lo_anuncia(tmp_path):
    todos = [_t(1, 1, texto="Lo de ayer."), _t(3, 2, "dueno", texto="hola")]
    voz = ("global.SpeechSynthesisUtterance = class { constructor(t){ this.text = t; } };"
           "global.speechSynthesis = { cancel(){}, addEventListener(){},"
           "  getVoices(){ return [{ lang: 'es-MX', localService: true, name: 'Local', voiceURI: 'local' }]; },"
           "  speak(u){ registro.valores.push(['dicho', u.text]); } };")
    # Al final contesta de verdad, por el sondeo: eso sí se anuncia. Sin ese
    # contraste, «no lo anunció» podría ser que el arnés no anuncia nada.
    r = _correr(tmp_path, [todos[1]], todos, {"1": AYER, "2": HOY}, mas_previo=voz,
                respuestas={"/api/secretario/turnos": {"hilo": 2, "turnos": [_t(4, 2, texto="Buenos días.")]},
                            "POST /api/secretario/mensaje": {"ok": True, "hilo": 2, "turno": 3}},
                accion="""
      registro.valores.push(['anuncio', nodo('sec-anuncio').textContent]);
      nodo('sec-texto').value = 'hola';
      nodo('sec-escribir').disparar('submit', { preventDefault(){} });
      setTimeout(() => registro.valores.push(['despues', nodo('sec-anuncio').textContent]), 5);
    """)
    assert _valor(r, "anuncio") == ""
    assert "Lo de ayer" not in json.dumps([v for v in r["valores"] if isinstance(v, list) and v[0] == "dicho"])
    assert _valor(r, "despues") == "Contestó: Buenos días."


def test_cargar_lo_anterior_no_mueve_lo_que_se_estaba_leyendo(tmp_path):
    """Al abrir, pegado al final: lo que llega por arriba no lo despega."""
    hoy = [_t(i, 2) for i in range(10, 20)]                       # 10 globos: 400 px en una caja de 200
    ayer = [_t(i, 1) for i in range(1, 6)]
    r = _correr(tmp_path, hoy, ayer + hoy, {"1": AYER, "2": HOY},
                accion="registro.valores.push(['al-final', CHAT.scrollTop, CHAT.scrollHeight - CHAT.clientHeight,"
                       " vista().length]);")
    arriba, maximo, cuantos = _valor(r, "al-final")
    assert cuantos == 17, "los diez de hoy, los cinco de ayer y sus dos separadores"
    assert arriba == maximo, "estaba pegado al final y sigue pegado"


def test_subir_a_leer_y_pedir_mas_conserva_lo_que_tenia_delante(tmp_path):
    hoy = [_t(i, 2) for i in range(20, 30)]
    ayer = [_t(i, 1) for i in range(1, 11)]
    r = _correr(tmp_path, hoy, ayer + hoy, {"1": AYER, "2": HOY}, accion="""
      // Abrir trajo 1..10. Sube a leer y pide lo de antes, que apareció
      // después: el botón está a la vista (30 px) y al traerlo todo se va.
      document.getElementById('sec-anteriores').hidden = false;
      CHAT.scrollTop = 100;
      CHAT.disparar('scroll');
      const delante = CHAT.scrollTop;
      const alto = CHAT.scrollHeight;
      TODOS = [{ id: 0, hilo: 0, rol: 'dueno', texto: 'el primero', estado: 'listo', tarjetas: [], adjuntos: [] }].concat(TODOS);
      HILOS['0'] = { titulo: '', abierto_local: '2026-11-01 09:00', cerrado: true, resumido: false };
      document.getElementById('sec-anteriores').disparar('click');
      setTimeout(() => registro.valores.push(['movido', CHAT.scrollTop - delante, CHAT.scrollHeight - alto,
                                              vista().slice(0, 2)]), 5);
    """)
    movido, crecio, arriba = _valor(r, "movido")
    assert crecio == 20 + 40 - 30 and movido == crecio, "se le suma al scroll lo que creció por arriba, botón incluido"
    assert arriba == ["— Conversación del 2026-11-01 09:00", "0:0"]


def test_en_el_panel_lo_anterior_se_pide_tras_el_primer_sondeo_desplegado(tmp_path):
    todos = [_t(1, 1), _t(2, 2, "dueno"), _t(3, 2)]
    # El panel: nada pintado, el sondeo trae el hilo abierto y lo anterior, todo (antes_de=0).
    r = _correr(tmp_path, [], todos, {"1": AYER, "2": HOY},
                respuestas={"/api/secretario/turnos": {"hilo": 2, "turnos": todos[1:]}},
                # Desplegado desde la visita anterior: el panel se abre al cargar.
                mas_previo="CHAT.dataset = { cargar: '1' }; localStorage.setItem('hub.secretario.abierto', '1');",
                accion="registro.valores.push(['vista', vista()]);")
    assert [p for p in r["peticiones"] if "anteriores" in p] == ["/api/secretario/anteriores?antes_de=2"]
    assert _valor(r, "vista") == ["— Conversación del 2026-11-12 10:15 · El dentista · resumida", "1:1",
                                  "— Esta conversación · lo de arriba lo recuerda sólo por su resumen", "2:2", "3:2"]


def test_un_turno_que_llega_por_el_sondeo_y_por_lo_anterior_se_pinta_una_vez(tmp_path):
    todos = [_t(1, 1), _t(2, 2, "dueno")]
    r = _correr(tmp_path, [], todos, {"1": AYER, "2": HOY},
                respuestas={"/api/secretario/turnos": {"hilo": 2, "turnos": [todos[1], _t(3, 2)]},
                            "POST /api/secretario/mensaje": {"ok": True, "hilo": 2, "turno": 2}},
                accion="""
      nodo('sec-texto').value = 'hola';
      nodo('sec-escribir').disparar('submit', { preventDefault(){} });
      setTimeout(() => registro.valores.push(['vista', vista()]), 5);
    """)
    vistos = _valor(r, "vista")
    assert [v for v in vistos if not v.startswith("—")] == ["1:1", "2:2", "3:2"], "cada globo una vez"


def test_en_el_panel_plegado_no_se_pide_lo_anterior(tmp_path):
    """Cada petición abre la memoria, y el panel va en todas las pestañas."""
    r = _correr(tmp_path, [], [_t(1, 1)], {"1": AYER}, mas_previo="CHAT.dataset = { cargar: '1' };")
    assert any("/api/secretario/turnos" in p for p in r["peticiones"])
    assert not [p for p in r["peticiones"] if "anteriores" in p]


def test_sin_nada_anterior_el_boton_no_sale_y_las_ideas_siguen(tmp_path):
    r = _correr(tmp_path, [], [], {}, montar="{ conIdeas: true }",
                accion="registro.valores.push(['vista', vista()]);")
    assert _valor(r, "vista") == ["#sec-vacio"], "ni botón ni separadores: sólo las ideas"


def test_lo_anterior_va_encima_de_las_ideas_del_chat_vacio(tmp_path):
    todos = [_t(1, 1, "dueno"), _t(2, 1)]
    r = _correr(tmp_path, [], todos, {"1": AYER}, montar="{ conIdeas: true }",
                accion="registro.valores.push(['vista', vista()]);")
    assert _valor(r, "vista")[1:] == ["1:1", "2:1", "#sec-vacio"]


def test_quedando_mas_atras_sale_ver_lo_anterior_y_pide_la_pagina_siguiente(tmp_path):
    todos = [_t(i, 1) for i in range(1, 41)] + [_t(50, 2, "dueno")]
    r = _correr(tmp_path, [todos[-1]], todos, {"1": AYER, "2": HOY}, accion="""
      registro.valores.push(['boton', document.getElementById('sec-anteriores').hidden]);
      document.getElementById('sec-anteriores').disparar('click');
      setTimeout(() => registro.valores.push(['despues', document.getElementById('sec-anteriores').hidden,
                                              vista().filter(v => v.endsWith(':1')).length]), 5);
    """)
    assert _valor(r, "boton") is False
    assert [p for p in r["peticiones"] if "anteriores" in p] == [
        "/api/secretario/anteriores?antes_de=50", "/api/secretario/anteriores?antes_de=11"]
    assert _valor(r, "despues") == [True, 40]


def test_una_conversacion_nueva_con_la_pagina_abierta_lleva_su_separador(tmp_path):
    # Hilo 2 pintado al cargar; mientras, se cerró y el sondeo trae el 3.
    r = _correr(tmp_path, [_t(3, 2, "dueno")], [_t(3, 2, "dueno")], {"2": HOY},
                respuestas={"/api/secretario/turnos": {"hilo": 3, "turnos": [_t(7, 3, "dueno", estado="listo")]},
                            "POST /api/secretario/mensaje": {"ok": True, "hilo": 3, "turno": 7}},
                accion="""
      nodo('sec-texto').value = 'otra cosa';
      nodo('sec-escribir').disparar('submit', { preventDefault(){} });
      setTimeout(() => registro.valores.push(['vista', vista()]), 5);
    """)
    # De la vieja no se pidió nada (no había nada antes): se sabe sólo que ya no es esta.
    assert _valor(r, "vista") == ["— Conversación anterior", "3:2",
                                  "— Esta conversación · lo de arriba lo recuerda sólo por su resumen", "7:3"]


def test_una_miniatura_que_ya_no_esta_deja_su_nombre(tmp_path):
    r = _correr(tmp_path, [], [], {}, accion="""
      const globo = hacer('div'); globo.className = 'burbuja dueno';
      const caja = hacer('div'); caja.className = 'adjuntos'; globo.appendChild(caja);
      const enlace = hacer('a'); caja.appendChild(enlace);
      const img = hacer('img'); img.alt = 'captura.png'; enlace.appendChild(img);
      CHAT.disparar('error', { target: img });
      registro.valores.push(['queda', caja.hijos.map(h => [h.tagName, h.className, h.textContent])]);
    """)
    assert _valor(r, "queda") == [["SPAN", "ido", "captura.png"]]


def test_sin_el_boton_en_la_pagina_el_chat_arranca_igual(tmp_path):
    todos = [_t(1, 1), _t(3, 2, "dueno")]
    r = _correr(tmp_path, [todos[1]], todos, {"1": AYER, "2": HOY}, montar="{ conBoton: false }",
                accion="registro.valores.push(['vista', vista()]);")
    assert _valor(r, "vista")[1:] == ["1:1", "— Esta conversación · lo de arriba lo recuerda sólo por su resumen", "3:2"]


# ── abrir una conversación de la lista (`/secretario?hilo=`) ─────────────────


def test_cada_conversacion_de_la_lista_enlaza_al_chat_con_su_hilo(con):
    h = _hilo(con, titulo="El dentista", resumen="Movió la cita.")

    html = TestClient(web.app).get("/secretario").text

    assert f'href="/secretario?hilo={h}"' in html


def test_abrir_con_hilo_marca_el_chat_para_ir_a_el_y_lo_que_no_es_un_numero_se_ignora(con):
    cliente = TestClient(web.app)

    con_hilo = cliente.get("/secretario?hilo=7")
    raro = cliente.get("/secretario?hilo=7%27%3E")
    exponente = cliente.get("/secretario?hilo=%C2%B2")

    assert con_hilo.status_code == 200 and 'data-ir-hilo="7"' in con_hilo.text
    assert raro.status_code == 200 and "data-ir-hilo" not in raro.text
    assert exponente.status_code == 200 and "data-ir-hilo" not in exponente.text
    # «Conversación nueva» vuelve sin el hilo: si no, volvería a bajar a él.
    nueva = con_hilo.text.split('id="sec-nueva"')[1].split("</form>")[0]
    assert 'name="volver" value="/secretario"' in nueva, nueva


def test_abrir_una_conversacion_de_la_lista_carga_hasta_ella_y_baja_a_su_separador(tmp_path):
    # El hilo 3 queda a 120 turnos de lo pintado: hacen falta tres páginas de 50.
    todos = ([_t(i, 2) for i in range(1, 11)] + [_t(i, 3) for i in range(11, 21)]
             + [_t(i, 4) for i in range(21, 141)] + [_t(200, 5, "dueno")])
    hilos = {"2": AYER | {"titulo": "dos"}, "3": AYER | {"titulo": "tres"}, "4": AYER | {"titulo": "cuatro"}, "5": HOY}
    # Con el turno de ahora sin contestar: el sondeo que lo trae no la mueve.
    pendiente = todos[-1] | {"estado": "pendiente"}
    r = _correr(tmp_path, [pendiente], todos, hilos, mas_previo="CHAT.dataset.irHilo = '3';" + SONDEOS_A_MANO,
                respuestas={"/api/secretario/turnos": {"hilo": 5, "turnos": [pendiente]}}, accion="""
      const sep = CHAT.querySelector('[data-sep="3"]');
      const arriba = CHAT.hijos.slice(0, CHAT.hijos.indexOf(sep)).reduce((s, h) => s + (h.hidden ? 0 : h.alto), 0);
      registro.valores.push(['al-llegar', CHAT.scrollTop === arriba, SONDEOS.length]);
      SONDEOS.shift()();
      setTimeout(() => registro.valores.push(['tras-un-sondeo', CHAT.scrollTop === arriba]), 3);
    """)
    pedidas = [p for p in r["peticiones"] if "anteriores" in p]
    assert pedidas == ["/api/secretario/anteriores?antes_de=200&n=50", "/api/secretario/anteriores?antes_de=91&n=50",
                       "/api/secretario/anteriores?antes_de=41&n=50"], "contiguas, hasta pasar del hilo 3"
    assert ["visto", "sep-hilo", "3"] in r["valores"], "baja a su separador"
    assert _valor(r, "al-llegar") == [True, 1]
    assert _valor(r, "tras-un-sondeo") is True, "y lo que llegue después no lo vuelve a bajar"


def test_si_la_conversacion_queda_demasiado_atras_lo_dice(tmp_path):
    todos = [_t(1, 1)] + [_t(i, 2) for i in range(2, 600)] + [_t(700, 3, "dueno")]
    r = _correr(tmp_path, [todos[-1]], todos, {"1": AYER, "2": AYER, "3": HOY},
                mas_previo="CHAT.dataset.irHilo = '1';",
                accion="registro.valores.push(['dicho', nodo('estado-sec').textContent, nodo('estado-sec').dataset.tono]);")
    assert len([p for p in r["peticiones"] if "anteriores" in p]) == 10, "el tope: diez páginas"
    assert _valor(r, "dicho") == ["Esa conversación queda más atrás: pulsa «Ver lo anterior» para seguir.", "aviso"]
    assert not [v for v in r["valores"] if isinstance(v, list) and v[0] == "visto"]


def test_una_conversacion_sin_mensajes_lo_dice_en_vez_de_cargar_sin_fin(tmp_path):
    todos = [_t(1, 1), _t(5, 3, "dueno")]
    r = _correr(tmp_path, [todos[-1]], todos, {"1": AYER, "3": HOY}, mas_previo="CHAT.dataset.irHilo = '2';",
                accion="registro.valores.push(['dicho', nodo('estado-sec').textContent]);")
    assert len([p for p in r["peticiones"] if "anteriores" in p]) == 1
    assert _valor(r, "dicho") == "Esa conversación no tiene mensajes."


# ── tras la revisión: lo que se lee no se mueve ──────────────────────────────

#: Los sondeos rápidos (1,5 s) se guardan en vez de correr: el test los lanza
#: uno a uno, sin depender del reloj del arnés.
SONDEOS_A_MANO = """
  globalThis.SONDEOS = [];
  const _st = global.setTimeout;
  global.setTimeout = (f, ms, ...r) => ms === 1500 ? (SONDEOS.push(() => f(...r)), 0) : _st(f, ms, ...r);
"""


def test_un_turno_sin_contestar_no_arrastra_al_final_a_quien_subio_a_leer(tmp_path):
    """Tras la revisión: cada sondeo que traía ese turno acababa en `bajar()`.
    Con el secretario pensando (o parado), lo anterior no se podía leer y
    `?hilo=` dejaba el separador a −7323 px a los 2,5 s."""
    hoy = [_t(i, 2) for i in range(10, 19)] + [_t(19, 2, "dueno", estado="pendiente")]
    r = _correr(tmp_path, hoy, hoy, {"2": HOY}, mas_previo=SONDEOS_A_MANO,
                respuestas={"/api/secretario/turnos": {"hilo": 2, "turnos": [hoy[-1]]}}, accion="""
      CHAT.scrollTop = 0;
      CHAT.disparar('scroll');
      const corre = () => { const f = SONDEOS.shift(); if (f) f(); };
      corre();
      setTimeout(() => { corre(); setTimeout(() => registro.valores.push(['arriba', CHAT.scrollTop, SONDEOS.length > 0]), 2); }, 2);
    """)
    assert _valor(r, "arriba") == [0, True], "sigue sondeando y no lo mueve"


def test_un_globo_nuevo_suyo_si_baja_al_final(tmp_path):
    hoy = [_t(i, 2) for i in range(10, 20)]
    r = _correr(tmp_path, hoy, hoy, {"2": HOY}, mas_previo=SONDEOS_A_MANO,
                respuestas={"/api/secretario/turnos": {"hilo": 2, "turnos": [_t(20, 2, "dueno", estado="pendiente")]},
                            "POST /api/secretario/mensaje": {"ok": True, "hilo": 2, "turno": 20}}, accion="""
      CHAT.scrollTop = 0;
      CHAT.disparar('scroll');
      nodo('sec-texto').value = 'otra cosa';
      nodo('sec-escribir').disparar('submit', { preventDefault(){} });
      setTimeout(() => registro.valores.push(['al-final', CHAT.scrollHeight - CHAT.clientHeight - CHAT.scrollTop]), 5);
    """)
    assert _valor(r, "al-final") == 0, "lo acaba de mandar: se ve"


def test_subir_de_golpe_hasta_arriba_y_pedir_mas_no_lleva_al_final(tmp_path):
    """Tras la revisión: el centinela `puesto = -1` hacía que un scroll que
    caía justo en 0 no contara, y «Ver lo anterior» lo daba por pegado."""
    hoy = [_t(i, 2) for i in range(20, 30)]
    ayer = [_t(i, 1) for i in range(1, 11)]
    r = _correr(tmp_path, hoy, ayer + hoy, {"1": AYER, "2": HOY}, accion="""
      const fondo = CHAT.scrollHeight - CHAT.clientHeight;
      CHAT.scrollTop = fondo - 10;              // un poco: aún cuenta como al final
      CHAT.disparar('scroll');
      CHAT.scrollTop = 0;                       // y de golpe arriba del todo
      CHAT.disparar('scroll');
      TODOS = [{ id: 0, hilo: 0, rol: 'dueno', texto: 'el primero', estado: 'listo', tarjetas: [], adjuntos: [] }].concat(TODOS);
      HILOS['0'] = { titulo: '', abierto_local: '01/11 09:00', cerrado: true, resumido: false };
      document.getElementById('sec-anteriores').hidden = false;
      document.getElementById('sec-anteriores').disparar('click');
      setTimeout(() => registro.valores.push(['tras', CHAT.scrollTop, CHAT.scrollHeight - CHAT.clientHeight]), 5);
    """)
    arriba, fondo = _valor(r, "tras")
    assert 0 < arriba < fondo, "conserva lo que tenía delante, no baja al final"


def test_al_cargar_queda_al_final_aunque_salga_ver_lo_anterior(tmp_path):
    """Tras la revisión: el botón salía después de bajar, y sin anclaje de
    scroll (Safari) faltaban 40-56 px para el final."""
    hoy = [_t(i, 2) for i in range(100, 110)]
    ayer = [_t(i, 1) for i in range(1, 41)]
    r = _correr(tmp_path, hoy, ayer + hoy, {"1": AYER, "2": HOY},
                accion="registro.valores.push(['falta', CHAT.scrollHeight - CHAT.clientHeight - CHAT.scrollTop,"
                       " document.getElementById('sec-anteriores').hidden]);")
    assert _valor(r, "falta") == [0, False]
