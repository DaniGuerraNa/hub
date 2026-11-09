"""Hablarle manteniendo Ctrl+Espacio en el PC (C-0172), ejecutado (regla dura 11).

Mantener la combinación graba; soltarla lo transcribe y lo manda, sin pasar
por el cuadro. Un toque corto, o perder el foco con la tecla pulsada, no
manda nada. Espacio solo, o Ctrl con otra tecla, siguen escribiendo.
"""

from __future__ import annotations

from arnes_js import ejecutar, script_estatico

CHAT = script_estatico("formato-chat.js") + "\n" + script_estatico("chat-secretario.js")

# Un micrófono y una grabadora falsos: la grabadora suelta un trozo al parar.
MICRO = """
  Object.defineProperty(globalThis, 'navigator', { configurable: true, value: {
    mediaDevices: { getUserMedia: () => Promise.resolve({ getTracks: () => [] }) } } });
  global.MediaRecorder = class {
    constructor() { this.l = {}; this.state = 'inactive'; registro.valores.push('GRABA'); }
    addEventListener(ev, f) { this.l[ev] = f; }
    start() { this.state = 'recording'; }
    stop() { this.state = 'inactive'; registro.valores.push('PARA');
             if (this.l.dataavailable) this.l.dataavailable({ data: { size: 5 } });
             if (this.l.stop) this.l.stop(); }
  };
  const _ahora = Date.now;
  let saltado = 0;
  Date.now = () => _ahora() + saltado;
  globalThis.SALTAR = (ms) => { saltado += ms; };
"""

TECLAS = """
  const tecla = (tipo, o) => {
    const e = { code: 'Space', key: ' ', ctrlKey: true, altKey: false, metaKey: false, shiftKey: false, repeat: false,
                parado: false, cancelado: false, preventDefault() { this.cancelado = true; }, stopPropagation() { this.parado = true; },
                ...o };
    (DOC_OYENTES[tipo] || []).forEach(f => f(e));
    return e;
  };
"""

RESPUESTAS = {"POST /api/voz": {"ok": True, "texto": "recuérdame llamar a Ana"},
              "POST /api/secretario/mensaje": {"ok": True, "hilo": 1, "turno": 1},
              "/api/secretario/turnos": {"hilo": 1, "turnos": []}}


def _correr(tmp_path, accion: str) -> dict:
    r = ejecutar(CHAT, tmp_path, RESPUESTAS, previo=MICRO, accion=TECLAS + accion)
    assert not r["errores"], r["errores"]
    return r


def _mandados(r):
    return [e["cuerpo"]["texto"] for e in r["enviados"] if e["url"] == "/api/secretario/mensaje"]


def test_mantener_ctrl_espacio_graba_y_al_soltar_lo_manda_sin_pasar_por_el_cuadro(tmp_path):
    accion = """
      const e = tecla('keydown', {});
      registro.valores.push(e.cancelado && e.parado ? 'CAPTURADA' : 'SE ESCAPA');
      setTimeout(() => { SALTAR(1500); tecla('keyup', { ctrlKey: false }); }, 2);
    """
    r = _correr(tmp_path, accion)
    assert r["valores"][:3] == ["CAPTURADA", "GRABA", "PARA"]
    assert "/api/voz" in r["peticiones"]
    assert _mandados(r) == ["recuérdame llamar a Ana"]
    assert "recuérdame llamar a Ana" not in r["valores"]     # no se quedó en el cuadro para revisarlo


def test_un_toque_corto_no_manda_nada(tmp_path):
    accion = "tecla('keydown', {}); setTimeout(() => tecla('keyup', {}), 2);"
    r = _correr(tmp_path, accion)
    assert "GRABA" in r["valores"] and "PARA" in r["valores"]
    assert "/api/voz" not in r["peticiones"] and _mandados(r) == []


def test_soltar_la_tecla_antes_de_que_se_abra_el_microfono_no_graba_nada_util(tmp_path):
    accion = "SALTAR(5000); tecla('keydown', {}); tecla('keyup', {});"
    r = _correr(tmp_path, accion)
    assert "/api/voz" not in r["peticiones"] and _mandados(r) == []


def test_perder_el_foco_con_la_tecla_pulsada_tira_lo_grabado(tmp_path):
    accion = """
      tecla('keydown', {});
      setTimeout(() => { SALTAR(3000); document.hidden = true;
                         (DOC_OYENTES.visibilitychange || []).forEach(f => f({})); }, 2);
    """
    r = _correr(tmp_path, accion)
    assert "PARA" in r["valores"] and "/api/voz" not in r["peticiones"]


def test_espacio_solo_y_ctrl_con_otra_tecla_siguen_escribiendo(tmp_path):
    accion = """
      const solo = tecla('keydown', { ctrlKey: false });
      const otra = tecla('keydown', { code: 'KeyK', key: 'k' });
      const con_mayus = tecla('keydown', { shiftKey: true });
      registro.valores.push([solo, otra, con_mayus].some(e => e.cancelado) ? 'TOCADA' : 'LIBRES');
    """
    r = _correr(tmp_path, accion)
    assert "LIBRES" in r["valores"] and "GRABA" not in r["valores"]


def test_mantenerla_pulsada_no_abre_dos_grabaciones(tmp_path):
    accion = """
      tecla('keydown', {});
      setTimeout(() => { tecla('keydown', { repeat: true }); tecla('keydown', {});
                         SALTAR(1200); tecla('keyup', {}); }, 2);
    """
    r = _correr(tmp_path, accion)
    assert r["valores"].count("GRABA") == 1
    assert _mandados(r) == ["recuérdame llamar a Ana"]
