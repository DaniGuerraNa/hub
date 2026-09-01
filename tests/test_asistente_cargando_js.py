"""El panel del asistente se quedaba en «Cargando…» para siempre.

🔴 El estado en que pasaba es el de CUALQUIERA recién instalado: el proyecto
`tipo: asistente` declarado, pero la ventana nunca arrancada. Ahí la API contesta
`{"abierto": false, "mensajes": []}` —correcto— y el pintado tenía dos guardas
que juntas no dejaban salir del marcador inicial:

    if (vacio && (mensajes.length || datos.abierto)) hilo.innerHTML = '';
    ...
    if (!hilo.innerHTML) { ...el mensaje que explica qué pasa... }

Con las dos condiciones falsas no se limpiaba; y como el hilo NO quedaba vacío
—seguía dentro el «Cargando…»—, el `else` que explica «no está abierto, escribe y
se arranca solo» tampoco llegaba a pintarse nunca.

Se ejecuta el `asistente.js` de verdad en node, con `fetch` gobernado desde el
test: comprobar el HTML servido no habría visto nada, porque el HTML es correcto
y quien se queda quieto es el navegador.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

GUION = Path(__file__).resolve().parents[1] / "src" / "hub" / "static" / "asistente.js"

# El arnés abre el panel desde `localStorage` —que es como el script decide si
# sondea— en vez de simular el clic: así se ejercita el mismo camino que recorre
# alguien que lo dejó abierto la última vez.
ARNES = r"""
const nodos = {};
function elemento(id) {
  if (nodos[id]) return nodos[id];
  return (nodos[id] = {
    id, textContent: '', value: '', innerHTML: '', className: '',
    style: { setProperty(){} },
    dataset: {}, children: [], scrollTop: 0, scrollHeight: 0,
    classList: { _s: new Set(), add(c){this._s.add(c)}, remove(c){this._s.delete(c)},
      contains(c){return this._s.has(c)},
      toggle(c, f){ const v = f === undefined ? !this._s.has(c) : f;
                    v ? this._s.add(c) : this._s.delete(c); return v; } },
    addEventListener(){}, setAttribute(){}, getAttribute(){ return null; },
    removeAttribute(){}, append(){}, appendChild(){}, remove(){}, focus(){},
    insertAdjacentHTML(p, html){ this.innerHTML += html; },
    scrollIntoView(){}, closest(){ return elemento('cercano'); },
    querySelector(){ return null; }, querySelectorAll(){ return []; },
  });
}

// El marcador inicial que pinta la plantilla, tal cual está en `base.html`.
elemento('asistente-hilo').innerHTML = '<p id="asistente-vacio">Cargando…</p>';

global.document = {
  // 🔴 Devuelve el marcador SÓLO mientras siga dentro del hilo. Es lo que hace
  // `getElementById` de verdad, y es justo la distinción que el arreglo usa
  // para decidir si puede vaciar el hilo sin llevarse mensajes por delante.
  getElementById(id) {
    if (id === 'asistente-vacio') {
      return elemento('asistente-hilo').innerHTML.includes('asistente-vacio')
        ? elemento('vacio') : null;
    }
    return elemento(id);
  },
  querySelector(){ return null; },
  querySelectorAll(){ return []; },
  createElement(){ return elemento('nuevo'); },
  body: elemento('body'),
  addEventListener(){},
};
global.window = { HubUI: { confirmar: async () => false } };
global.HubUI = global.window.HubUI;
global.localStorage = { _d: { 'hub.asistente.abierto': '1' },
  getItem(k){ return this._d[k] ?? null; }, setItem(k, v){ this._d[k] = v; } };
global.setInterval = () => 0;
global.clearInterval = () => {};

let RESPUESTA = RESPUESTA_JSON;
global.fetch = async () => {
  if (RESPUESTA === null) throw new Error('sin red');
  return { ok: RESPUESTA.ok !== false, status: RESPUESTA.status || 200,
           json: async () => RESPUESTA.cuerpo };
};

require(GUION_RUTA);

setTimeout(() => {
  console.log(JSON.stringify({ hilo: elemento('asistente-hilo').innerHTML }));
}, 30);
"""


def _correr(tmp_path, respuesta) -> str:
    node = shutil.which("node")
    if not node:
        pytest.skip("node no disponible")
    archivo = tmp_path / "arnes.js"
    archivo.write_text(
        ARNES.replace("GUION_RUTA", json.dumps(str(GUION)))
             .replace("RESPUESTA_JSON", json.dumps(respuesta)),
        encoding="utf-8",
    )
    salida = subprocess.run([node, str(archivo)], capture_output=True,
                            text=True, timeout=30)
    assert salida.returncode == 0, salida.stderr
    return json.loads(salida.stdout.strip().splitlines()[-1])["hilo"]


SIN_ABRIR = {"cuerpo": {"abierto": False, "mensajes": []}}
ABIERTO_VACIO = {"cuerpo": {"abierto": True, "mensajes": []}}
CON_MENSAJE = {"cuerpo": {"abierto": True, "mensajes": [
    {"uuid": "1", "rol": "user", "texto": "hola", "ts": "2026-09-01T10:00:00Z"}]}}


def test_declarado_pero_nunca_abierto_explica_que_hacer(tmp_path):
    """El caso que fallaba, y el de cualquiera que acabe de instalar el hub."""
    hilo = _correr(tmp_path, SIN_ABRIR)
    assert "Cargando" not in hilo
    assert "No está abierto" in hilo


def test_abierto_y_sin_conversacion_invita_a_preguntar(tmp_path):
    hilo = _correr(tmp_path, ABIERTO_VACIO)
    assert "Cargando" not in hilo
    assert "Pregúntale algo" in hilo


def test_con_mensajes_los_pinta_y_retira_el_marcador(tmp_path):
    hilo = _correr(tmp_path, CON_MENSAJE)
    assert "Cargando" not in hilo and "asistente-vacio" not in hilo
    assert "hola" in hilo


def test_un_error_del_hub_se_dice_en_vez_de_fingir_que_carga(tmp_path):
    """🔴 Un 500 daba `datos = {}`, indistinguible de «no hay nada que contar», y
    el panel se quedaba igual de quieto que en el fallo original — pero por otra
    causa. Ahora se ve que el problema es del hub y no del asistente."""
    hilo = _correr(tmp_path, {"ok": False, "status": 500, "cuerpo": {}})
    assert "Cargando" not in hilo
    assert "No se pudo hablar con el hub" in hilo


def test_sin_red_tampoco_se_queda_callado(tmp_path):
    hilo = _correr(tmp_path, None)
    assert "Cargando" not in hilo
    assert "No se pudo hablar con el hub" in hilo
