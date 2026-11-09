"""El JavaScript del personaje, ejecutado (regla dura 11; C-0166, decisión 358).

Se prueba lo que se ve: qué estado pinta con cada cosa que le cuentan, que
cada estado dura al menos 600 ms y gana el último, que con movimiento
reducido no se mueve, y que el chat le cuenta lo que ya sabe.
"""

from __future__ import annotations

import json

from arnes_js import ejecutar, script_estatico

AVATAR = script_estatico("avatar-secretario.js")
CHAT = script_estatico("formato-chat.js") + "\n" + script_estatico("chat-secretario.js")

# Un reloj falso: `avanzar(ms)` ejecuta lo programado que ya toca.
RELOJ = """
let T = 1000000;
const cola = [];
const op = { ahora: () => T, reducido: false,
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
"""


# El personaje programa de verdad cuándo dormirse (3 min): en node, ese
# temporizador mantendría vivo el proceso y el arnés esperaría a que venza.
# Los largos no lo retienen; los cortos siguen ejecutándose como siempre.
SIN_RETENER = """
  const _programar = global.setTimeout;
  global.setTimeout = function (f, ms, ...resto) {
    const t = _programar(f, ms, ...resto);
    if (ms > 1000 && t && t.unref) t.unref();
    return t;
  };
"""


def _resultados(r: dict) -> list:
    assert not r["errores"], r["errores"]
    return [json.loads(v[2:]) for v in r["valores"] if isinstance(v, str) and v.startswith("R:")]


def ejecutar_sin_retener(guion, tmp_path, respuestas=None, previo="", accion=""):
    return ejecutar(guion, tmp_path, respuestas, previo=SIN_RETENER + previo, accion=accion)


def _correr(tmp_path, accion: str, previo: str = "", guion: str = AVATAR, respuestas: dict | None = None) -> list:
    return _resultados(ejecutar_sin_retener(guion, tmp_path, respuestas, previo=previo, accion=RELOJ + accion))


def test_arranca_sin_errores_y_expone_su_lista_cerrada_de_gestos(tmp_path):
    [gestos] = _correr(tmp_path, "R(window.HubPersonaje.GESTOS);")
    from hub.secretario import personaje
    assert gestos == list(personaje.GESTOS)


def test_lo_que_pinta_sale_de_lo_que_hace_con_su_prioridad(tmp_path):
    accion = """
      const d = (m) => { const v = HubPersonaje.derivar(m, 5000); return [v.estado, v.gesto, v.rotulo]; };
      const trabajando = { id: 1, rol: 'secretario', estado: 'escribiendo',
                           actividad: { estado: 'trabajando', gesto: 'buscar', rotulo: 'Buscando «Ana»' } };
      R(d({ abierto: trabajando }));
      R(d({ abierto: { ...trabajando, actividad: { estado: 'trabajando', gesto: 'bailar', rotulo: 'x' } } }));
      R(d({ abierto: { ...trabajando, actividad: { estado: 'pensando', experto: true } } }));
      R(d({ abierto: { ...trabajando, actividad: null } }));
      R(d({ abierto: trabajando, voz: 'escuchando' }));
      R(d({ abierto: trabajando, red: 'caida' }));
      R(d({ espera: { solicitudes: 2, resumenes: 0, encargos: [] } }));
      R(d({ espera: { solicitudes: 0, resumenes: 1, resumiendo: 1, encargos: [] } }));
      R(d({ enCola: 4000 }));
      R(d({ enCola: 100 }));
      R(d({ ultimo: 5000 - 200000 }));
      R(d({}));
    """
    assert _correr(tmp_path, accion) == [
        ["trabajando", "buscar", "Buscando «Ana»"],
        ["trabajando", "hacer", "x"],                       # un gesto que no conoce: el genérico, nunca uno inventado
        ["pensando-fondo", "", "Pensándolo a fondo"],
        ["pensando", "", "Pensando…"],
        ["escuchando", "", "Te escucho"],                   # tu voz manda sobre su trabajo
        ["sin-hub", "", "El hub no contesta"],
        ["esperando", "", "Esperan tu sí (2)"],
        ["esperando-otro", "", "Resumiendo una sesión aparte"],
        ["pensando", "", "Pensando…"],                      # acabas de mandarlo: aún no es «en cola»
        ["en-cola", "arena", "En cola"],
        ["dormido", "", "Descansando"],
        ["quieto", "", ""],
    ]


def test_los_acompanantes_son_lo_que_delego_con_sus_subagentes_y_su_rol(tmp_path):
    accion = """
      const espera = { solicitudes: 0, resumenes: 1, encargos: [{ id: 't', estado: 'activa', pedido: 'Arreglar',
        sesiones: [{ nombre: 'Tablero', proyecto: 'hub', subagentes: [
          { rol: 'revisor', tipo: 'revisor', inicial: 'R', que: 'Revisa' },
          { rol: 'otro', tipo: 'statusline-setup', inicial: 'S', que: '' }] }] }] };
      R(HubPersonaje.acompanantes(espera, false).map(a => [a.rol, a.inicial || '']));
      const v = HubPersonaje.derivar({ espera }, 0);
      R([v.estado, v.rotulo]);
    """
    roles, vista = _correr(tmp_path, accion)
    # La inicial viaja siempre; sólo la enseña el que no tiene skin («otro», por CSS).
    assert roles == [["orquestador", ""], ["obrero", ""], ["revisor", "R"], ["otro", "S"], ["resumidor", ""]]
    assert vista == ["esperando-otro", "Esperando al orquestador · 2 subagentes"]


def test_solo_trabaja_lo_que_trabaja_y_lo_que_espera_una_respuesta_lo_dice(tmp_path):
    """Regla 13 (revisor): una tarea que espera tu respuesta no se pinta afanándose,
    y de los resúmenes sólo trabaja el que se lee; los demás, en cola."""
    accion = """
      const tarea = (estado) => ({ solicitudes: 0, resumenes: 0, resumiendo: 0,
                                   encargos: [{ id: 't', estado, pedido: 'p', sesiones: [] }] });
      for (const e of ['activa', 'esperando-sesion', 'esperando-dueno', 'esperando-secretario', 'en-cola']) {
        const v = HubPersonaje.derivar({ espera: tarea(e) }, 0);
        R([e, v.estado, v.rotulo, v.acompanantes[0].estado]);
      }
      const r = HubPersonaje.acompanantes({ resumenes: 3, resumiendo: 1, encargos: [] }, false);
      R(r.map(a => a.estado));
      R(HubPersonaje.derivar({ espera: { resumenes: 2, resumiendo: 0, encargos: [] } }, 0).rotulo);
    """
    *tareas, resumenes, en_cola = _correr(tmp_path, accion)
    assert tareas == [
        ["activa", "esperando-otro", "Esperando al orquestador", "trabajando"],
        ["esperando-sesion", "esperando-otro", "Esperando al orquestador", "trabajando"],
        ["esperando-dueno", "esperando", "El orquestador espera tu respuesta", "esperando"],
        ["esperando-secretario", "esperando-otro", "Encargado al orquestador (le pregunta algo)", "esperando"],
        ["en-cola", "esperando-otro", "Encargado al orquestador (en cola)", "en-cola"],
    ]
    assert resumenes == ["trabajando", "en-cola", "en-cola"]
    assert en_cola == "Un resumen en cola"


def test_lo_que_espera_caduca_si_nadie_lo_renueva(tmp_path):
    """Con el panel plegado no se pregunta: lo de hace más de tres minutos no
    se enseña como si fuera de ahora (regla 13, revisor)."""
    accion = """
      const raiz = nodo('pj-prueba');
      raiz.dataset.espera = JSON.stringify({ solicitudes: 1, resumenes: 0, encargos: [] });
      const s = HubPersonaje.crear(raiz, op);
      R(raiz.dataset.estado);
      avanzar(179000); R(raiz.dataset.estado);
      avanzar(2000); R(raiz.dataset.estado);
      s.recibir({ espera: { solicitudes: 1, resumenes: 0, encargos: [] } }); avanzar(700); R(raiz.dataset.estado);
    """
    assert _correr(tmp_path, accion) == ["esperando", "esperando", "quieto", "esperando"]


def test_cada_estado_se_ve_al_menos_600_ms_y_si_llegan_varios_gana_el_ultimo(tmp_path):
    accion = """
      const raiz = nodo('pj-prueba');
      const s = HubPersonaje.crear(raiz, op);
      const turno = (gesto) => ({ turnos: [{ id: 9, rol: 'secretario', estado: 'escribiendo',
                                              actividad: { estado: 'trabajando', gesto, rotulo: gesto } }] });
      R(raiz.dataset.estado);
      s.recibir(turno('buscar'));      R([raiz.dataset.estado, raiz.dataset.gesto]);
      avanzar(100); s.recibir(turno('leer'));
      avanzar(100); s.recibir(turno('agenda'));
      R([raiz.dataset.estado, raiz.dataset.gesto]);   // aún «buscar»: no han pasado 600 ms
      avanzar(399); R(raiz.dataset.gesto);
      avanzar(1); R(raiz.dataset.gesto);                // a los 600 ms, el último; «leer» no se llegó a ver
    """
    assert _correr(tmp_path, accion) == ["quieto", ["trabajando", "buscar"], ["trabajando", "buscar"], "buscar", "agenda"]


def test_el_visto_bueno_sale_solo_si_lo_vio_trabajar_y_se_va_solo(tmp_path):
    accion = """
      const raiz = nodo('pj-prueba');
      const s = HubPersonaje.crear(raiz, op);
      // Lo ya contestado al cargar no salta.
      s.recibir({ turnos: [{ id: 1, rol: 'secretario', estado: 'listo' }] }); R(raiz.dataset.estado);
      s.recibir({ turnos: [{ id: 2, rol: 'secretario', estado: 'escribiendo', actividad: { estado: 'escribiendo' } }] });
      avanzar(700);
      s.recibir({ turnos: [{ id: 2, rol: 'secretario', estado: 'listo' }] });
      avanzar(700); R(raiz.dataset.estado);
      avanzar(2000); R(raiz.dataset.estado);
      s.recibir({ turnos: [{ id: 3, rol: 'secretario', estado: 'escribiendo' }] });
      avanzar(700);
      s.recibir({ turnos: [{ id: 3, rol: 'secretario', estado: 'error' }] });
      avanzar(700); R(raiz.dataset.estado);
    """
    assert _correr(tmp_path, accion) == ["quieto", "hecho", "quieto", "error"]


def test_se_duerme_tras_tres_minutos_quieto(tmp_path):
    accion = """
      const raiz = nodo('pj-prueba');
      HubPersonaje.crear(raiz, op);
      avanzar(179000); R(raiz.dataset.estado);
      avanzar(2000); R(raiz.dataset.estado);
    """
    assert _correr(tmp_path, accion) == ["quieto", "dormido"]


def test_con_movimiento_reducido_se_queda_en_su_pose_y_no_sigue_la_voz(tmp_path):
    accion = """
      const quieta = nodo('pj-quieta');
      const s = HubPersonaje.crear(quieta, { ...op, reducido: true });
      s.recibir({ voz: 'escuchando', nivel: 0.9 });
      R(quieta.dataset.estado);
      const viva = nodo('pj-viva');
      HubPersonaje.crear(viva, op).recibir({ voz: 'escuchando', nivel: 0.9 });
    """
    r = ejecutar_sin_retener(AVATAR, tmp_path, accion=RELOJ + accion)
    assert _resultados(r) == ["escuchando"]          # el estado sí: el rótulo dice lo que hace
    assert "sin-movimiento" in r["clases"]
    niveles = [v for v in r["variables"] if v[0].endswith(":--nivel")]
    assert niveles == [["pj-viva:--nivel", "0.9"]]  # la quieta no se mueve con tu voz


def test_lo_que_preguntan_por_matchmedia_decide_si_se_mueve(tmp_path):
    previo = "global.matchMedia = (q) => ({ matches: q.includes('reduced-motion'), addEventListener(){} });"
    r = ejecutar_sin_retener(AVATAR, tmp_path, previo=previo)
    assert not r["errores"] and "sin-movimiento" in r["clases"]


def test_caben_tres_acompanantes_y_el_resto_es_mas_n(tmp_path):
    accion = """
      const raiz = nodo('pj-prueba');
      const caja = raiz.querySelector('[data-acompanantes]');
      document.getElementById('pj-plantilla-acomp').innerHTML = '<svg data-r="__ROL__">__INICIAL__</svg>';
      const subagentes = ['revisor', 'arquitecto', '"><img src=x>'].map((rol, i) => ({ rol, tipo: rol, inicial: 'X', que: 'q' + i }));
      HubPersonaje.crear(raiz, op).recibir({ espera: { solicitudes: 0, resumenes: 0,
        encargos: [{ id: 't', estado: 'activa', pedido: 'p', sesiones: [{ nombre: 's', subagentes }] }] } });
      R(caja.innerHTML);
    """
    [html] = _correr(tmp_path, accion)
    assert html.count('class="pj-acomp"') == 3 and "+2" in html
    assert 'data-rol="orquestador"' in html and 'data-r="obrero"' in html
    assert "<img" not in html                       # un rol raro no inyecta nada


def test_oye_al_chat_por_su_evento(tmp_path):
    """Las escenas de la página (las raíces sin `data-fijo`) siguen `secretario:estado`."""
    accion = """
      (DOC_OYENTES['secretario:estado'] || []).forEach(f => f({ detail: { voz: 'hablando' } }));
      R(document.querySelectorAll('[data-personaje]:not([data-fijo])').map(r => r.dataset.estado));
    """
    assert _correr(tmp_path, accion) == [["hablando", "hablando", "hablando"]]


# ── el chat le cuenta lo que ya sabe (C-0166) ─────────────────────────────────

ESCUCHAR = """
  global.CustomEvent = class { constructor(tipo, o) { this.type = tipo; this.detail = (o || {}).detail; } };
  document.dispatchEvent = (e) => registro.valores.push('R:' + JSON.stringify(e.detail));
"""


def test_el_chat_cuenta_cada_sondeo_con_lo_que_espera(tmp_path):
    turnos = {"hilo": 1, "turnos": [{"id": 5, "rol": "secretario", "estado": "escribiendo", "texto": "",
                                      "actividad": {"estado": "trabajando", "gesto": "leer", "rotulo": "Leyendo"}}],
              "espera": {"solicitudes": 1, "resumenes": 0, "encargos": []}}
    previo = ESCUCHAR + "nodo('sec-chat').dataset.cargar = '1';"
    vistos = _resultados(ejecutar_sin_retener(CHAT, tmp_path, {"/api/secretario/turnos": turnos}, previo=previo))
    sondeo = next(v for v in vistos if "turnos" in v)
    assert sondeo["red"] == "ok" and sondeo["espera"]["solicitudes"] == 1
    assert sondeo["turnos"][0]["actividad"]["gesto"] == "leer"


INTERVALOS = "global.setInterval = (f) => { (globalThis.INTERVALOS ||= []).push(f); return 0; };"


def test_un_turno_que_empezo_en_otro_aparato_se_sigue_hasta_el_final(tmp_path):
    """El sondeo lento lo descubre y arranca la cadena rápida; antes la
    descubría y nadie seguía mirando: el panel se quedaba «pensando»."""
    turnos = {"hilo": 1, "turnos": [{"id": 4, "rol": "dueno", "estado": "atendiendo", "texto": "hola"},
                                     {"id": 5, "rol": "secretario", "estado": "escribiendo", "texto": ""}]}
    accion = """
      INTERVALOS[0]();
      setTimeout(() => { INTERVALOS[0](); R(registro.temporizadores.filter(ms => ms === 1500).length); }, 5);
    """
    r = ejecutar_sin_retener(CHAT, tmp_path, {"/api/secretario/turnos": turnos}, previo=INTERVALOS,
                             accion=RELOJ + accion)
    # Una sola cadena: el segundo sondeo lento ya no entra (hay un turno abierto).
    assert _resultados(r) == [1]


def test_desplegar_el_panel_con_un_turno_abierto_arranca_una_sola_cadena(tmp_path):
    turnos = {"hilo": 1, "turnos": [{"id": 5, "rol": "secretario", "estado": "escribiendo", "texto": ""}]}
    previo = INTERVALOS + "nodo('sec-chat').dataset.cargar = '1';"
    accion = """
      const pestana = nodo('secretario-pestana');
      pestana.disparar('click'); pestana.disparar('click'); pestana.disparar('click');
      setTimeout(() => R(registro.temporizadores.filter(ms => ms === 1500).length), 5);
    """
    r = ejecutar_sin_retener(CHAT, tmp_path, {"/api/secretario/turnos": turnos}, previo=previo,
                             accion=RELOJ + accion)
    assert _resultados(r) == [1]


def test_un_turno_que_venia_a_medias_se_vuelve_a_pedir(tmp_path):
    """Pidiendo «desde» el último turno pintado, el que se estaba escribiendo no
    volvía nunca: la burbuja se quedaba en «…» y el personaje sin saber nada."""
    previo = """
      const b = nodo('burbuja-7');
      b.dataset = { turno: '7', estado: 'escribiendo', texto: '', tarjetas: '[]' };
      b.classList.add('secretario');
      const chat = nodo('sec-chat');
      chat.dataset = { ultimo: '7', cargar: '1' };
      chat.querySelectorAll = (s) => (s === '.burbuja' ? [b] : []);
    """
    r = ejecutar_sin_retener(CHAT, tmp_path, {"/api/secretario/turnos": {"hilo": 1, "turnos": []}}, previo=previo)
    assert not r["errores"], r["errores"]
    assert "/api/secretario/turnos?desde=6" in r["peticiones"]


def test_el_chat_dice_lo_que_hace_en_la_burbuja_mientras_trabaja(tmp_path):
    turnos = {"hilo": 1, "turnos": [{"id": 5, "rol": "secretario", "estado": "escribiendo", "texto": "",
                                      "actividad": {"estado": "trabajando", "gesto": "leer", "rotulo": "Leyendo <b>x</b>"}}]}
    previo = "nodo('sec-chat').dataset.cargar = '1';"
    # La burbuja del turno 5: el arnés da el mismo nodo por selector.
    accion = "R(nodo('sec-chat').querySelector('[data-turno=\"5\"]').innerHTML);"
    r = ejecutar_sin_retener(CHAT, tmp_path, {"/api/secretario/turnos": turnos}, previo=previo, accion=RELOJ + accion)
    [html] = _resultados(r)
    assert 'class="que-hace">Leyendo &lt;b&gt;x&lt;/b&gt;' in html
