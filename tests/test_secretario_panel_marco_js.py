"""El panel del secretario en la interfaz nueva, ejecutado (regla dura 11).

Desde C-0450 es el panel flotante de siempre, con su marcado y su clave
(`hub.secretario.abierto`): arranca como lo dejaste y lo recuerda. La nueva
—`<html data-interfaz="nueva">`— sólo le añade `Ctrl .`, que lo abre y lo
pliega también con el foco en la terminal, y en una ventana de menos de
861 px no se pinta: ahí el secretario es un destino de la barra de abajo.
Sin esa marca, todo sigue como en la interfaz de siempre.
"""

from __future__ import annotations

from arnes_js import ejecutar, script_estatico

# Con `grabar.js` delante, como en la página: el chat graba con `HubGrabar` (C-0311).
CHAT = (script_estatico("grabar.js") + "\n" + script_estatico("formato-chat.js") + "\n"
        + script_estatico("chat-secretario.js"))

# El panel de las demás pantallas (`data-cargar`), con la preferencia guardada
# en «abierto» por una visita anterior.
_PANEL = ("nodo('sec-chat').dataset.cargar = '1';"
          "localStorage.setItem('hub.secretario.abierto', '1');"
          "nodo('sec-texto').focus = () => registro.valores.push('FOCO EN EL CUADRO');")
NUEVA = _PANEL + "document.documentElement.dataset.interfaz = 'nueva';"
TELEFONO = "global.matchMedia = (q) => ({ matches: /max-width: 860px/.test(q), addEventListener(){} });"
# El sondeo lento, a mano: se guarda su función para poder llamarla una vez.
SONDEO = "window.HubSondeo = { cada: (fn) => { globalThis.SONDEO_LENTO = fn; return () => {}; } };"

TECLAS = """
  const tecla = (o) => {
    const e = { key: '.', code: 'Period', ctrlKey: true, altKey: false, metaKey: false, shiftKey: false, repeat: false,
                parado: false, cancelado: false, preventDefault() { this.cancelado = true; },
                stopPropagation() { this.parado = true; }, ...o };
    (DOC_OYENTES.keydown || []).forEach(f => f(e));
    return e;
  };
  const panel = nodo('secretario-panel');
  const estado = () => (panel.classList.contains('abierto') ? 'ABIERTO' : 'PLEGADO');
"""

RESPUESTAS = {"/api/secretario/turnos": {"hilo": 1, "turnos": []},
              "POST /api/secretario/mensaje": {"ok": True, "hilo": 1, "turno": 1}}


def _correr(tmp_path, previo: str, accion: str = "") -> dict:
    r = ejecutar(CHAT, tmp_path, RESPUESTAS, previo=previo,
                 accion=TECLAS + accion + "registro.valores.push('GUARDADO:' + localStorage.getItem('hub.secretario.abierto'));")
    assert not r["errores"], r["errores"]
    return r


def _del_panel(r) -> list:
    return [v for clave, v in r["alternadas"] if clave == "secretario-panel:abierto"]


def test_con_la_nueva_arranca_como_lo_dejaste(tmp_path):
    """Antes arrancaba plegado siempre y no recordaba: lo acoplado se retiró
    (C-0450) y vuelve a ser el panel de siempre, con su clave."""
    abierto = _correr(tmp_path, NUEVA, "registro.valores.push(estado());")
    assert _del_panel(abierto) == [True] and "ABIERTO" in abierto["valores"]
    plegado = _correr(tmp_path, NUEVA + "localStorage.setItem('hub.secretario.abierto', '');",
                      "registro.valores.push(estado());")
    assert _del_panel(plegado) == [False] and "PLEGADO" in plegado["valores"]


def test_el_flotante_de_siempre_sigue_recordando_como_lo_dejaste(tmp_path):
    r = _correr(tmp_path, _PANEL, "registro.valores.push(estado());")
    assert _del_panel(r) == [True] and "ABIERTO" in r["valores"]


def test_con_la_nueva_abrir_y_plegar_escriben_la_misma_clave_que_la_de_siempre(tmp_path):
    accion = """
      nodo('secretario-pestana').disparar('click');
      registro.valores.push(estado(), 'TRAS PLEGAR:' + localStorage.getItem('hub.secretario.abierto'));
      nodo('secretario-pestana').disparar('click'); registro.valores.push(estado());
    """
    r = _correr(tmp_path, NUEVA, accion)
    assert [v for v in r["valores"] if v in ("ABIERTO", "PLEGADO")] == ["PLEGADO", "ABIERTO"]
    assert "TRAS PLEGAR:" in r["valores"] and "GUARDADO:1" in r["valores"]


def test_en_el_telefono_con_la_nueva_arranca_plegado_sin_pisar_la_clave_ni_sondear(tmp_path):
    """Con la nueva y menos de 861 px el panel no se pinta. Abrirlo por lo
    guardado de otra visita lo dejaba abierto e invisible, preguntando cada
    6 s; y plegarlo no es decisión de quien lo usa: lo guardado se queda."""
    accion = """
      const antes = registro.peticiones.length;
      SONDEO_LENTO();
      registro.valores.push(estado(), 'SONDEOS:' + (registro.peticiones.length - antes));
    """
    r = _correr(tmp_path, TELEFONO + SONDEO + NUEVA, accion)
    assert _del_panel(r) == [False]
    assert "PLEGADO" in r["valores"] and "SONDEOS:0" in r["valores"] and "GUARDADO:1" in r["valores"]


def test_el_control_abierto_el_sondeo_lento_si_pregunta(tmp_path):
    """Sin esto, el de arriba pasaría igual con un sondeo que no pregunta nunca."""
    accion = """
      const antes = registro.peticiones.length;
      SONDEO_LENTO();
      registro.valores.push('SONDEOS:' + (registro.peticiones.length - antes));
    """
    assert "SONDEOS:1" in _correr(tmp_path, SONDEO + NUEVA, accion)["valores"]


def test_ctrl_punto_lo_abre_con_el_foco_en_el_cuadro_y_lo_vuelve_a_plegar(tmp_path):
    accion = """
      nodo('secretario-pestana').disparar('click');      // llegó abierto: se pliega a mano
      const terminal = { focus() { registro.valores.push('FOCO DE VUELTA'); } };
      document.activeElement = terminal;
      const abre = tecla({});
      registro.valores.push(estado(), abre.cancelado && abre.parado ? 'CAPTURADA' : 'SE ESCAPA');
      const pliega = tecla({});
      registro.valores.push(estado(), pliega.cancelado && pliega.parado ? 'CAPTURADA' : 'SE ESCAPA');
    """
    r = _correr(tmp_path, NUEVA, accion)
    limpio = [v for v in r["valores"] if isinstance(v, str) and not v.startswith("GUARDADO")]
    # En captura y parada: con el foco en la terminal, el punto no llega a la sesión.
    assert limpio == ["FOCO EN EL CUADRO", "ABIERTO", "CAPTURADA", "FOCO DE VUELTA", "PLEGADO", "CAPTURADA"]
    assert "document:keydown" in r["oyentes"]


def test_mantener_ctrl_punto_no_lo_abre_y_lo_pliega_sin_parar(tmp_path):
    accion = ("nodo('secretario-pestana').disparar('click');"
              "tecla({}); tecla({ repeat: true }); tecla({ repeat: true }); registro.valores.push(estado());")
    assert "ABIERTO" in _correr(tmp_path, NUEVA, accion)["valores"]


def test_el_punto_solo_y_otras_combinaciones_siguen_escribiendo(tmp_path):
    accion = """
      nodo('secretario-pestana').disparar('click');
      const sueltas = [tecla({ ctrlKey: false }), tecla({ shiftKey: true }), tecla({ altKey: true }),
                       tecla({ key: ',', code: 'Comma' })];
      registro.valores.push(sueltas.some(e => e.cancelado || e.parado) ? 'TOCADA' : 'LIBRES', estado());
    """
    r = _correr(tmp_path, NUEVA, accion)
    assert "LIBRES" in r["valores"] and "PLEGADO" in r["valores"] and "ABIERTO" not in r["valores"]


def test_en_la_interfaz_de_siempre_ctrl_punto_no_hace_nada(tmp_path):
    accion = """
      nodo('secretario-pestana').disparar('click');      // llegó abierto: se pliega a mano
      const e = tecla({});
      registro.valores.push(e.cancelado || e.parado ? 'TOCADA' : 'LIBRE', estado());
    """
    r = _correr(tmp_path, _PANEL, accion)
    assert "LIBRE" in r["valores"] and "PLEGADO" in r["valores"]


def test_en_el_telefono_con_la_nueva_el_atajo_no_lo_abre(tmp_path):
    r = _correr(tmp_path, TELEFONO + NUEVA,
                "const e = tecla({}); registro.valores.push(e.cancelado ? 'TOCADA' : 'LIBRE', estado());")
    assert "LIBRE" in r["valores"] and "PLEGADO" in r["valores"]


def test_guiame_en_el_telefono_manda_la_pregunta_y_lleva_a_su_pantalla(tmp_path):
    """Sin panel a la vista, abrirlo no enseñaría nada: la respuesta se lee en /secretario."""
    accion = """
      location.assign = (a) => registro.valores.push('VA A ' + a);
      window.HubSecretario.preguntar('¿Qué es un slot?');
      registro.valores.push(estado());
    """
    r = _correr(tmp_path, TELEFONO + NUEVA, accion)
    assert [e["cuerpo"]["texto"] for e in r["enviados"] if e["url"] == "/api/secretario/mensaje"] == ["¿Qué es un slot?"]
    assert "PLEGADO" in r["valores"] and "VA A /secretario" in r["valores"]


def test_guiame_en_el_pc_abre_el_panel_con_la_pregunta_hecha(tmp_path):
    accion = ("nodo('secretario-pestana').disparar('click');"
              "window.HubSecretario.preguntar('¿Qué es un slot?'); registro.valores.push(estado());")
    r = _correr(tmp_path, NUEVA, accion)
    assert "ABIERTO" in r["valores"]
    assert [e["cuerpo"]["texto"] for e in r["enviados"] if e["url"] == "/api/secretario/mensaje"] == ["¿Qué es un slot?"]


# ── lo que marcó el revisor de C-0169 ────────────────────────────────────────

def test_win_punto_no_es_el_atajo_del_panel(tmp_path):
    """En Windows, `Win + .` abre el panel de emojis: la tecla Meta no cuenta,
    igual que en Ctrl+Espacio."""
    accion = """
      nodo('secretario-pestana').disparar('click');
      const win = tecla({ ctrlKey: false, metaKey: true });
      const las_dos = tecla({ metaKey: true });
      registro.valores.push([win, las_dos].some(e => e.cancelado || e.parado) ? 'TOCADA' : 'LIBRES', estado());
    """
    r = _correr(tmp_path, NUEVA, accion)
    assert "LIBRES" in r["valores"] and "PLEGADO" in r["valores"] and "ABIERTO" not in r["valores"]


# Un micrófono y una grabadora de mentira, como en `test_secretario_atajo_js.py`.
_MICRO = """
  Object.defineProperty(globalThis, 'navigator', { configurable: true, value: {
    mediaDevices: { getUserMedia: () => { registro.valores.push('MICRO'); return Promise.resolve({ getTracks: () => [] }); } } } });
  global.MediaRecorder = class {
    constructor() { this.l = {}; this.state = 'inactive'; registro.valores.push('GRABA'); }
    addEventListener(ev, f) { this.l[ev] = f; }
    start() { this.state = 'recording'; }
    stop() { this.state = 'inactive'; if (this.l.stop) this.l.stop(); }
  };
"""
_CTRL_ESPACIO = "const espacio = tecla({ key: ' ', code: 'Space' });"


def test_ctrl_espacio_sin_panel_a_la_vista_no_graba_y_lleva_a_su_pantalla(tmp_path):
    """En una ventana de PC de menos de 861 px el panel de la nueva no se pinta.
    Grabar y mandar ahí era hablarle a ciegas: ni se veía que escuchaba ni lo
    que contestaba. Como «Guíame»: a su pantalla, donde el atajo sí se ve."""
    accion = """
      location.assign = (a) => registro.valores.push('VA A ' + a);
    """ + _CTRL_ESPACIO + """
      registro.valores.push(espacio.cancelado && espacio.parado ? 'CAPTURADA' : 'SE ESCAPA', estado());
    """
    r = _correr(tmp_path, TELEFONO + _MICRO + NUEVA, accion)
    assert "GRABA" not in r["valores"] and "MICRO" not in r["valores"]
    assert "VA A /secretario" in r["valores"] and "CAPTURADA" in r["valores"] and "PLEGADO" in r["valores"]
    assert "/api/voz" not in [str(p) for p in r["peticiones"]]


def test_ctrl_espacio_con_el_panel_a_la_vista_sigue_abriendolo_y_grabando(tmp_path):
    # Se suelta enseguida: con la tecla pulsada el atajo espera hasta un minuto.
    soltar = "(DOC_OYENTES.keyup || []).forEach(f => f({ code: 'Space', key: ' ', preventDefault() {} }));"
    r = _correr(tmp_path, _MICRO + NUEVA,
                "nodo('secretario-pestana').disparar('click');"
                + _CTRL_ESPACIO + "registro.valores.push(estado()); setTimeout(() => { " + soltar + " }, 2);")
    assert "GRABA" in r["valores"] and "ABIERTO" in r["valores"]
