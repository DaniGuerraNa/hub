"""Dictar en el teléfono, ejecutando el JavaScript (regla dura 11).

Lo que importa probar es la promesa del archivo: **el texto se pega en el
campo y no se manda nada**. Una transcripción equivocada en una orden que se
ejecuta sin nadie delante es el error que no se ve hasta que ya pasó.
"""

from __future__ import annotations

from arnes_js import ejecutar, script_estatico

GUION = script_estatico("grabar.js")

# Un micrófono y una grabadora de mentira: `stop` entrega un trozo y dispara el
# evento, que es lo que hace el navegador de verdad.
MICROFONO = """
  navigator.mediaDevices = { getUserMedia: () => Promise.resolve({
    getTracks: () => [{ stop(){ registro.pistas = (registro.pistas || 0) + 1; } }] }) };
  global.MediaRecorder = class {
    constructor(flujo) { this.mimeType = 'audio/webm'; this._o = {}; }
    addEventListener(ev, fn) { (this._o[ev] ||= []).push(fn); }
    start() { registro.grabando = true; }
    stop() {
      (this._o.dataavailable || []).forEach(f => f({ data: new Blob(['x']) }));
      (this._o.stop || []).forEach(f => f({}));
    }
  };
  document.querySelectorAll('[data-grabar]').forEach((b, i) => {
    b.dataset.grabar = 'destino-' + i;
    b.dataset.grabarEstado = 'estado-' + i;
    b.dataset.grabarOrigen = 'origen-' + i;
  });
"""

PULSAR_DOS_VECES = """
  const b = document.querySelectorAll('[data-grabar]')[0];
  b.disparar('click');
  setTimeout(() => b.disparar('click'), 5);
  setTimeout(() => {
    registro.texto = nodo('destino-0').value;
    registro.origen = nodo('origen-0').value;
    registro.estado = nodo('estado-0').textContent;
  }, 15);
"""


def test_arranca_sin_reventar(tmp_path):
    assert ejecutar(GUION, tmp_path)["errores"] == []


def test_lo_dictado_se_pega_en_el_campo_y_no_se_manda(tmp_path):
    r = ejecutar(GUION, tmp_path, previo=MICROFONO, accion=PULSAR_DOS_VECES,
                 respuestas={"POST /orquestador/audio": {"ok": True, "texto": "revisa alfa"}})

    assert r["errores"] == []
    assert r["texto"] == "revisa alfa"
    assert r["origen"] == "audio"
    assert "Revísalo" in r["estado"]
    # Una sola petición, y es la de transcribir: nada va a /orquestador/tarea.
    assert [e["url"] for e in r["enviados"]] == ["/orquestador/audio"]
    assert r["pistas"] == 1   # el micrófono se suelta al terminar


def test_si_no_se_pudo_transcribir_se_dice_y_el_campo_no_cambia(tmp_path):
    r = ejecutar(GUION, tmp_path, previo=MICROFONO, accion=PULSAR_DOS_VECES,
                 respuestas={"POST /orquestador/audio": {"ok": False, "error": "sin transcriptor"}})

    assert r["texto"] == ""
    assert "sin transcriptor" in r["estado"]


def test_sin_microfono_lo_dice_en_vez_de_callar(tmp_path):
    """Sin HTTPS el navegador no da micrófono: se dice, no se queda mudo."""
    r = ejecutar(GUION, tmp_path, previo="""
      document.querySelectorAll('[data-grabar]').forEach((b, i) => {
        b.dataset.grabarEstado = 'estado-' + i; });
    """, accion="""
      document.querySelectorAll('[data-grabar]')[0].disparar('click');
      setTimeout(() => { registro.estado = nodo('estado-0').textContent; }, 5);
    """)

    assert "HTTPS" in r["estado"]
