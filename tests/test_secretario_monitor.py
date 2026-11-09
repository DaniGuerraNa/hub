"""El modo monitor del secretario (C-0202, decisión 389).

Un escenario con puestos y el personaje yendo al de lo que hace. Se prueba el
vocabulario (cada estado y cada gesto tiene su puesto, y ningún puesto es
decorado), que el JavaScript lo aplica igual que `personaje.puesto_de`, que
sólo se mueve cuando cambia de puesto, que con movimiento reducido o con la
pestaña oculta no anda ni programa nada, que si algo te espera se queda junto
a tus asuntos, y que la pantalla se sirve sin el raíl y con el chat.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from arnes_js import ejecutar, script_estatico
from hub import api, config
from hub.secretario import memoria, personaje

ESCENARIO = script_estatico("escenario-secretario.js")
CSS = (Path(__file__).resolve().parents[1] / "src" / "hub" / "static" / "escenario-secretario.css").read_text(
    encoding="utf-8")
MAPA = personaje.escenario()


# ── el vocabulario ────────────────────────────────────────────────────────────

def test_cada_gesto_tiene_su_puesto():
    assert set(personaje.PUESTO_DE_GESTO) == set(personaje.GESTOS)
    assert set(personaje.PUESTO_DE_GESTO.values()) <= set(personaje.PUESTOS)
    for gesto in personaje.GESTOS:
        assert personaje.puesto_de("trabajando", gesto) == personaje.PUESTO_DE_GESTO[gesto]


def test_cada_estado_tiene_su_puesto_y_esperar_tu_si_es_junto_a_tus_asuntos():
    # «trabajando» va por gesto, como la pose (`pose_de`).
    assert set(personaje.PUESTO_DE_ESTADO) == set(personaje.ESTADOS) - {"trabajando"}
    assert set(personaje.PUESTO_DE_ESTADO.values()) <= set(personaje.PUESTOS)
    assert personaje.puesto_de("esperando") == "asuntos"
    assert personaje.puesto_de("esperando-otro") == "orquestador"
    assert personaje.puesto_de("quieto") == personaje.REPOSO == "escritorio"
    # Lo que no conoce descansa en su mesa; nunca un puesto inventado.
    assert personaje.puesto_de("bailando") == personaje.puesto_de("trabajando", "volar") == "escritorio"


def test_el_gesto_generico_lo_hace_en_su_mesa():
    """`hacer` es el de una acción sin gesto propio, el de una herramienta fuera
    del catálogo y aquel en que el JS convierte uno que no conoce: no dice de
    qué es, así que no lo lleva a ningún puesto que no le toca."""
    from hub.secretario import piezas
    assert piezas.Accion.gesto == "hacer"
    assert personaje.puesto_de("trabajando", "hacer") == "escritorio"


def test_ningun_puesto_es_un_decorado_al_que_no_lleva_nada():
    alcanzados = set(personaje.PUESTO_DE_ESTADO.values()) | set(personaje.PUESTO_DE_GESTO.values())
    assert alcanzados == set(personaje.PUESTOS)


def test_cada_puesto_se_dibuja_con_un_accesorio_que_existe():
    for puesto, (nombre, que, accesorio) in personaje.PUESTOS.items():
        assert nombre and que, puesto
        assert accesorio in personaje.GESTOS, puesto      # `_personaje.html` dibuja `#acc-<gesto>`


def test_si_algo_te_espera_lo_que_haria_en_su_mesa_lo_hace_junto_a_tus_asuntos():
    assert personaje.puesto_de("quieto", nuevas=2) == "asuntos"
    assert personaje.puesto_de("pensando", nuevas=1) == "asuntos"
    # Lo que espera de ti va antes que lo que espera de otros.
    assert personaje.puesto_de("esperando-otro", nuevas=1) == "asuntos"
    # Trabajando, va a donde le lleva el trabajo.
    assert personaje.puesto_de("trabajando", "agenda", nuevas=3) == "agenda"
    assert personaje.puesto_de("trabajando", "anotar", nuevas=3) == "escritorio"


def test_la_tabla_del_escenario_es_el_vocabulario_tal_cual():
    assert MAPA["estado"] == personaje.PUESTO_DE_ESTADO and MAPA["gesto"] == personaje.PUESTO_DE_GESTO
    assert MAPA["accesorio"] == {p: a for p, (_n, _q, a) in personaje.PUESTOS.items()}
    assert MAPA["reposo"] == "escritorio" and MAPA["ceden"] == list(personaje.CEDEN_A_ASUNTOS)


def test_cada_puesto_tiene_su_sitio_en_la_rejilla_del_escenario():
    rejillas = re.findall(r"grid-template-areas:((?:\s*\"[^\"]+\")+)", CSS)
    assert len(rejillas) == 2, rejillas                 # el teléfono y el monitor
    for rejilla in rejillas:
        assert set(" ".join(re.findall(r"\"([^\"]+)\"", rejilla)).split()) == set(personaje.PUESTOS)


# ── el CSS ────────────────────────────────────────────────────────────────────

COLOR_SUELTO = re.compile(r"#[0-9a-fA-F]{3,8}(?![\w-])|rgba?\(|hsla?\(")


def test_el_css_del_escenario_usa_tokens_sin_sombras_ni_degradados():
    sin_comentarios = re.sub(r"/\*.*?\*/", "", CSS, flags=re.S)
    assert not COLOR_SUELTO.search(sin_comentarios)
    assert "box-shadow" not in sin_comentarios and "drop-shadow" not in sin_comentarios
    assert "gradient" not in sin_comentarios


def test_con_movimiento_reducido_el_css_no_anda():
    bloque = CSS[CSS.index("@media (prefers-reduced-motion: reduce)"):]
    bloque = bloque[:bloque.index("}\n}") + 3]
    assert "transition:none !important" in bloque and "animation:none !important" in bloque
    assert ".sin-movimiento .esc-andador" in CSS


# ── el JavaScript, ejecutado (regla dura 11) ──────────────────────────────────

# Un reloj falso que cuenta lo que se programa: «no programa nada» se puede
# comprobar en vez de suponerlo.
RELOJ = """
let T = 1000000;
const cola = [];
let OCULTA = false;
const ORDEN = %s;
const op = { reducido: false, oculta: () => OCULTA,
             medir: (e, p) => ({ x: ORDEN.indexOf(p) * 100, y: 40 }),
             programar: (f, ms) => { cola.push({ t: T + ms, f }); return cola.length; },
             cancelar: (id) => { if (cola[id - 1]) cola[id - 1].f = null; } };
function avanzar(ms) {
  const fin = T + ms;
  for (;;) {
    const c = cola.filter(x => x.f && x.t <= fin).sort((a, b) => a.t - b.t)[0];
    if (!c) break;
    T = Math.max(T, c.t);
    const f = c.f; c.f = null; f();
  }
  T = fin;
}
const R = (x) => registro.valores.push('R:' + JSON.stringify(x));
const andadas = () => registro.clases.filter(c => c === 'andando').length;
const esc = nodo('esc');
esc.dataset.puestos = JSON.stringify(%s);
const pj = esc.querySelector('[data-personaje]');
const andador = esc.querySelector('[data-andador]');
pj.dataset.estado = 'quieto'; pj.dataset.gesto = '';
const poner = (s, estado, gesto) => { pj.dataset.estado = estado; pj.dataset.gesto = gesto || ''; s.revisar(); };
""" % (json.dumps(list(personaje.PUESTOS)), json.dumps(MAPA))


def _correr(tmp_path, accion: str, previo: str = "") -> list:
    r = ejecutar(ESCENARIO, tmp_path, previo=previo, accion=RELOJ + accion)
    assert not r["errores"], r["errores"]
    return [json.loads(v[2:]) for v in r["valores"] if isinstance(v, str) and v.startswith("R:")]


def test_el_js_pone_cada_estado_y_gesto_en_el_mismo_puesto_que_personaje(tmp_path):
    casos = [(e, g, n) for e in personaje.ESTADOS for g in ("", *personaje.GESTOS) for n in (0, 2)]
    accion = f"R({json.dumps(casos)}.map(([e, g, n]) => HubEscenario.puestoDe({json.dumps(MAPA)}, e, g, n)));"
    [del_js] = _correr(tmp_path, accion)
    assert del_js == [personaje.puesto_de(e, g, n) for e, g, n in casos]


def test_el_personaje_solo_se_mueve_cuando_cambia_lo_que_hace(tmp_path):
    accion = """
      registro.variables.length = 0;     // lo de la escena que arranca sola al cargar
      const s = HubEscenario.crear(esc, op);
      const ver = () => R([s.puesto(), andadas(), cola.length]);
      ver();                                   // en su mesa, puesto sin andar
      poner(s, 'trabajando', 'buscar'); ver(); // a Mensajes
      poner(s, 'trabajando', 'leer'); ver();   // otra herramienta del mismo puesto: quieto
      s.recibir({ nivel: 0.6 }); s.recibir({ turnos: [] }); s.recibir({ red: 'ok' }); ver();
      poner(s, 'trabajando', 'agenda'); ver(); // a la Agenda
      avanzar(5000);
      poner(s, 'escribiendo'); ver();          // vuelve a su mesa
      poner(s, 'hecho'); ver();
      poner(s, 'quieto'); ver();
      R(registro.variables.filter(v => v[0] === '[data-andador]:--esc-x').map(v => v[1]));
    """
    *pasos, xs = _correr(tmp_path, accion)
    assert pasos == [
        ["escritorio", 0, 0],
        ["mensajes", 1, 1],
        ["mensajes", 1, 1],
        ["mensajes", 1, 1],
        ["agenda", 2, 2],
        ["escritorio", 3, 3],
        ["escritorio", 3, 3],
        ["escritorio", 3, 3],
    ]
    orden = list(personaje.PUESTOS)
    assert xs == [f"{orden.index(p) * 100}px" for p in ("escritorio", "mensajes", "agenda", "escritorio")]


def test_al_volver_a_su_mesa_trae_lo_del_puesto_de_donde_viene(tmp_path):
    accion = """
      const s = HubEscenario.crear(esc, op);
      poner(s, 'trabajando', 'agenda'); R(andador.dataset.trae || '');   // va: no trae nada
      avanzar(5000);
      poner(s, 'hecho'); R(andador.dataset.trae || '');
      avanzar(HubEscenario.ANDAR_MS); R([andador.dataset.trae || '', andador.classList.contains('andando')]);
    """
    assert _correr(tmp_path, accion) == ["", "agenda", ["", False]]


def test_con_movimiento_reducido_no_se_mueve(tmp_path):
    """Cambia de sitio —lo que hace se sigue viendo— pero sin andar ni programar nada."""
    accion = """
      const s = HubEscenario.crear(esc, { ...op, reducido: true });
      poner(s, 'trabajando', 'agenda'); R([s.puesto(), andadas(), cola.length]);
      poner(s, 'esperando'); R([s.puesto(), andadas(), cola.length]);
    """
    r = ejecutar(ESCENARIO, tmp_path, accion=RELOJ + accion)
    assert not r["errores"], r["errores"]
    valores = [json.loads(v[2:]) for v in r["valores"] if isinstance(v, str) and v.startswith("R:")]
    assert valores == [["agenda", 0, 0], ["asuntos", 0, 0]]
    assert "sin-movimiento" in r["clases"]


def test_lo_que_pregunta_por_matchmedia_decide_si_anda(tmp_path):
    previo = "global.matchMedia = (q) => ({ matches: q.includes('reduced-motion'), addEventListener(){} });"
    accion = """
      const s = HubEscenario.crear(esc, { ...op, reducido: undefined });
      poner(s, 'trabajando', 'agenda'); R([s.puesto(), andadas()]);
    """
    assert _correr(tmp_path, accion, previo=previo) == [["agenda", 0]]


def test_si_reducir_movimiento_se_pide_despues_de_cargar_deja_de_andar(tmp_path):
    previo = "globalThis.REDUCIDO = false; global.matchMedia = () => ({ matches: REDUCIDO, addEventListener(){} });"
    accion = """
      const s = HubEscenario.crear(esc, { ...op, reducido: undefined });
      poner(s, 'trabajando', 'agenda'); R(andadas());
      REDUCIDO = true;
      poner(s, 'trabajando', 'pc'); R([s.puesto(), andadas()]);
    """
    assert _correr(tmp_path, accion, previo=previo) == [1, ["web", 1]]


def test_su_tamano_y_su_rotulo_salen_de_lo_que_cabe_en_los_puestos(tmp_path):
    """El hueco del puesto más justo da su tamaño, y el ancho del puesto al
    que va, lo largo de su rótulo: a ojo no cabían en un 1366×768."""
    accion = """
      registro.variables.length = 0;
      const s = HubEscenario.crear(esc, { ...op, hueco: () => 123, medir: (e, p) => ({ x: 10, y: 20, ancho: 280 }) });
      R(registro.variables.filter(v => /--esc-(hueco|cabe)$/.test(v[0])));
    """
    assert _correr(tmp_path, accion) == [[["esc:--esc-hueco", "123px"], ["[data-andador]:--esc-cabe", "280px"]]]


def test_en_una_pestana_oculta_no_programa_nada(tmp_path):
    accion = """
      const s = HubEscenario.crear(esc, op);
      OCULTA = true;
      poner(s, 'trabajando', 'buscar'); poner(s, 'trabajando', 'agenda');
      s.recibir({ espera: { asuntos: { nuevas: 1 } } });
      R([s.puesto(), andadas(), cola.length]);       // sigue donde estaba, sin nada programado
      s.recolocar(); R(cola.length);
      OCULTA = false;
      s.visibilidad(true);
      R([s.puesto(), andadas(), cola.length]);       // al volver, en su sitio y sin andar
      poner(s, 'quieto'); R([s.puesto(), andadas()]); // ya visible: nada que cambiar (te espera algo)
    """
    assert _correr(tmp_path, accion) == [["escritorio", 0, 0], 0, ["agenda", 0, 0], ["asuntos", 1]]


def test_si_algo_te_espera_se_queda_junto_a_tus_asuntos(tmp_path):
    accion = """
      pj.dataset.espera = JSON.stringify({ solicitudes: 0, asuntos: { nuevas: 1, total: 4 } });
      const cifra = esc.querySelector('[data-nuevas]');
      const s = HubEscenario.crear(esc, op);
      R([s.puesto(), cifra.textContent, cifra.hidden]);              // ya al cargar, con lo del raíl
      s.recibir({ espera: { solicitudes: 0 } }); R(s.puesto());      // sin la cifra cuenta 0
      s.recibir({ espera: { asuntos: { nuevas: 3, total: 5 } } });
      R([s.puesto(), cifra.textContent, cifra.hidden]);
      poner(s, 'trabajando', 'agenda'); R(s.puesto());               // a trabajar, donde toque
      avanzar(5000);
      poner(s, 'hecho'); R(s.puesto());                              // y de vuelta, a tus asuntos
      poner(s, 'esperando-otro'); R(s.puesto());                     // antes que lo de otros
      s.recibir({ espera: { asuntos: { nuevas: 0, total: 5 } } });
      R([s.puesto(), cifra.textContent, cifra.hidden]);
      // Sin hub, la cifra de antes no se puede defender: se quita hasta que conteste.
      s.recibir({ espera: { asuntos: { nuevas: 2 } } }); poner(s, 'quieto');
      s.recibir({ red: 'caida' }); R([s.puesto(), cifra.hidden]);
    """
    assert _correr(tmp_path, accion) == [
        ["asuntos", "1 nueva", False],
        "escritorio",
        ["asuntos", "3 nuevas", False],
        "agenda",
        "asuntos",
        "asuntos",
        ["orquestador", "", True],
        ["escritorio", True],
    ]


def test_oye_al_chat_por_su_evento_y_no_sondea_nada(tmp_path):
    """Envuelve al personaje: lo que hace lo lee de su raíz, y lo que te
    espera del evento que ya emite chat-secretario.js. Ni un `fetch` ni un
    temporizador propio."""
    previo = f"""
      globalThis.ESC = nodo('escena');
      ESC.dataset.puestos = JSON.stringify({json.dumps(MAPA)});
      document.querySelector = (s) => (s === '[data-escenario]' ? ESC : elemento('x'));
      globalThis.INTERVALOS = 0;
      global.setInterval = () => {{ globalThis.INTERVALOS += 1; return 0; }};
    """
    accion = """
      const raiz = ESC.querySelector('[data-personaje]');
      const oir = (d) => (DOC_OYENTES['secretario:estado'] || []).forEach(f => f({ detail: d }));
      R(ESC.dataset.en);
      raiz.dataset.estado = 'trabajando'; raiz.dataset.gesto = 'pc';
      oir({ turnos: [] }); R(ESC.dataset.en);
      raiz.dataset.estado = 'quieto'; raiz.dataset.gesto = '';
      oir({ espera: { solicitudes: 0, asuntos: { nuevas: 2 } } }); R(ESC.dataset.en);
      R([registro.peticiones.length, INTERVALOS]);
    """
    r = ejecutar(ESCENARIO, tmp_path, previo=previo, accion=RELOJ + accion)
    assert not r["errores"], r["errores"]
    valores = [json.loads(v[2:]) for v in r["valores"] if isinstance(v, str) and v.startswith("R:")]
    assert valores == ["escritorio", "web", "asuntos", [0, 0]]
    assert "document:visibilitychange" in r["oyentes"]


# ── la pantalla ───────────────────────────────────────────────────────────────

@pytest.fixture
def cliente(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from hub import db, web

    def conexion():
        c = db.conectar(tmp_path / "hub.db")
        db.inicializar(c)
        return c

    monkeypatch.setattr(web, "conexion", conexion)
    return TestClient(web.app)


def _con_secretario():
    memoria.conectar().close()
    (memoria.carpeta() / "secretario.yml").write_text("en_todo_el_hub: true\n", encoding="utf-8")


def test_el_monitor_se_sirve_sin_el_rail_y_con_el_chat(cliente):
    _con_secretario()
    r = cliente.get("/secretario/monitor")
    assert r.status_code == 200
    html = r.text
    cabeza, cuerpo = html.split("</head>", 1)
    # Sin raíl ni cabecera del hub: la regla que los quita va en `<head>`, antes
    # del primer pintado (C-0167), como en /secretario.
    assert re.search(r'<body class="[^"]*\bmonitor\b', html)
    assert '/static/escenario-secretario.css' in cabeza
    assert re.search(r"body\.monitor \.rail-global, body\.monitor \.envoltura > header[^{]*\{ *display:none", CSS)
    # El chat de siempre, y no el panel flotante: un solo chat por pantalla.
    assert 'id="sec-chat"' in cuerpo and 'id="sec-escribir"' in cuerpo and "/static/chat-secretario.js" in cuerpo
    assert 'id="secretario-panel"' not in html and 'id="secretario-pestana"' not in html
    # El personaje dentro de lo que se traslada, y el escenario con sus puestos.
    andador = cuerpo[cuerpo.index("data-andador"):]
    assert andador.index("data-personaje") < andador.index('class="pj') < andador.index("data-trae")
    for puesto in personaje.PUESTOS:
        assert f'data-puesto="{puesto}"' in cuerpo, puesto
    puestos = json.loads(re.search(r"data-puestos='([^']*)'", cuerpo).group(1))
    assert puestos == MAPA
    # El personaje oye el evento antes que el escenario.
    assert cuerpo.index("/static/avatar-secretario.js") < cuerpo.index("/static/escenario-secretario.js")


def test_desde_su_pantalla_se_llega_al_modo_monitor(cliente):
    _con_secretario()
    html = cliente.get("/secretario").text
    assert 'href="/secretario/monitor"' in html and "Modo monitor" in html
    assert 'href="/secretario"' in cliente.get("/secretario/monitor").text   # y se vuelve


def test_sale_ya_pintado_con_lo_que_espera_y_la_conversacion_abierta(cliente):
    from hub.secretario import conversacion
    _con_secretario()
    con = memoria.conectar()
    try:
        conversacion.recibir(con, "¿Qué tengo hoy?")
    finally:
        con.close()
    html = cliente.get("/secretario/monitor").text
    espera = json.loads(re.search(r"data-espera='([^']*)'", html).group(1))
    # Campo a campo: otros añaden claves a la espera (los asuntos), no las renombran.
    assert (espera["solicitudes"], espera["resumenes"], espera["resumiendo"], espera["encargos"]) == (0, 0, 0, [])
    assert "¿Qué tengo hoy?" in html


def test_la_cifra_de_lo_que_te_espera_sale_si_la_espera_la_trae(monkeypatch):
    """Los asuntos los cuenta otra pieza (`secretario_espera`): aquí sólo se
    pinta lo que trae, y sin ella, nada."""
    from jinja2 import Environment, FileSystemLoader

    from hub import insignias
    entorno = Environment(loader=FileSystemLoader(str(Path(api.__file__).parent / "templates")))
    insignias.registrar(entorno)
    m = api.secretario_monitor()
    plantilla = entorno.get_template("secretario_monitor.html")
    sin = plantilla.render(mon=m, rail={})
    assert re.search(r'data-nuevas\s+hidden', sin)
    con = plantilla.render(mon={**m, "espera": {"solicitudes": 0, "asuntos": {"nuevas": 2, "total": 3}}}, rail={})
    assert re.search(r'data-nuevas\s*>2 nuevas<', con)


def test_pintar_el_monitor_sin_secretario_no_le_crea_la_base(cliente):
    r = cliente.get("/secretario/monitor")
    assert r.status_code == 200
    assert 'data-escenario' in r.text and 'id="sec-chat"' in r.text
    assert not (config.HUB_HOME / "secretario" / "memoria.db").exists()
