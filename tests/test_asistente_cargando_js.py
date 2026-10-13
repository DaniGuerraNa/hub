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
    // Se guarda la FUNCIÓN, no sólo el nombre: sin ella no se puede disparar
    // el envío, y el fallo que se lleva el texto escrito sólo se ve enviando.
    _oyentes: {},
    addEventListener(ev, fn){ (this._oyentes[ev] ||= []).push(fn); },
    disparar(ev, arg){ (this._oyentes[ev] || []).forEach(f => f(arg || {})); },
    setAttribute(){}, getAttribute(){ return null; },
    removeAttribute(){}, append(){}, appendChild(){}, remove(){}, focus(){},
    insertAdjacentHTML(p, html){ this.innerHTML += html; },
    scrollIntoView(){}, closest(){ return elemento('cercano'); },
    querySelector(){ return null; }, querySelectorAll(){ return []; },
  });
}

// El marcador inicial que pinta la plantilla, tal cual está en `base.html`.
elemento('asistente-hilo').innerHTML = '<p id="asistente-vacio">Cargando…</p>';

// Los nodos que el script INSERTA en el DOM, para poder mirarlos después. La
// banda de aviso se crea así, y sin esto no habría forma de comprobar que
// aparece — que es justo lo que este archivo existe para comprobar.
const insertados = {};
elemento('asistente-hilo').parentNode = {
  insertBefore(nodo) { insertados[nodo.id] = nodo; return nodo; },
};

global.document = {
  // 🔴 Devuelve el marcador SÓLO mientras siga dentro del hilo. Es lo que hace
  // `getElementById` de verdad, y es justo la distinción que el arreglo usa
  // para decidir si puede vaciar el hilo sin llevarse mensajes por delante.
  getElementById(id) {
    if (insertados[id]) return insertados[id];
    // 🔴 `null` mientras no esté insertado, como el `getElementById` de verdad.
    // Devolviendo un nodo inventado, `avisar()` le escribía encima y el aviso
    // no llegaba nunca al documento: el arnés habría dado por bueno el fallo
    // que este archivo existe para cazar.
    if (id === 'asistente-aviso') return null;
    if (id === 'asistente-vacio') {
      return elemento('asistente-hilo').innerHTML.includes('asistente-vacio')
        ? elemento('vacio') : null;
    }
    return elemento(id);
  },
  querySelector(){ return null; },
  querySelectorAll(){ return []; },
  // Un nodo NUEVO cada vez, con su `remove()` de verdad: el aviso tiene que
  // poder retirarse solo cuando el hub vuelve, y con un nodo compartido eso no
  // se podía distinguir de «sigue ahí».
  createElement() {
    const n = { id: '', className: '', textContent: '',
                remove() { delete insertados[this.id]; } };
    return n;
  },
  body: elemento('body'),
  addEventListener(){},
};
global.window = { HubUI: { confirmar: async () => false,
                          avisar: (o) => { avisos.push(o); } } };
const avisos = [];
global.HubUI = global.window.HubUI;
global.localStorage = { _d: { 'hub.asistente.abierto': '1' },
  getItem(k){ return this._d[k] ?? null; }, setItem(k, v){ this._d[k] = v; } };
global.setInterval = () => 0;
global.clearInterval = () => {};

let RESPUESTA = RESPUESTA_JSON;
const peticiones = [];
global.fetch = async (url) => {
  peticiones.push(String(url));
  if (RESPUESTA === null) throw new Error('sin red');
  const r = {
    ok: RESPUESTA.ok !== false, status: RESPUESTA.status || 200,
    json: async () => RESPUESTA.cuerpo,
  };
  // `porQue()` clona antes de leer, como haría con una respuesta de verdad.
  r.clone = () => r;
  return r;
};

require(GUION_RUTA);

ACCION

setTimeout(() => {
  const banda = insertados['asistente-aviso'];
  console.log(JSON.stringify({
    hilo: elemento('asistente-hilo').innerHTML,
    aviso: banda ? banda.textContent : null,
    caja: elemento('asistente-texto').value,
    peticiones, avisos,
  }));
}, 40);
"""


def _correr(tmp_path, respuesta, accion: str = "") -> str:
    """Devuelve el hilo. `_todo` da además el aviso y la caja."""
    return _todo(tmp_path, respuesta, accion)["hilo"]


def _todo(tmp_path, respuesta, accion: str = "") -> dict:
    node = shutil.which("node")
    if not node:
        pytest.skip("node no disponible")
    archivo = tmp_path / "arnes.js"
    archivo.write_text(
        ARNES.replace("GUION_RUTA", json.dumps(str(GUION)))
             .replace("RESPUESTA_JSON", json.dumps(respuesta))
             .replace("ACCION", accion),
        encoding="utf-8",
    )
    salida = subprocess.run([node, str(archivo)], capture_output=True,
                            text=True, timeout=30)
    assert salida.returncode == 0, salida.stderr
    return json.loads(salida.stdout.strip().splitlines()[-1])


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


# ── El silencio con la conversación ya pintada ───────────────────────────────
#
# 🔴 Lo vivió él: *«asistente no está funcionando, le pregunté algo y no mostró
# texto alguno, tuve que ir a terminal para ver la conversación»*.
#
# La causa estaba fuera del asistente: `projects.yml` se había quedado con la
# clave `conexiones` dos veces, así que el registro no cargaba y `/api/asistente`
# contestaba 422 en cada sondeo. Pero lo que lo volvió INVISIBLE está aquí: el
# aviso de error sólo se pintaba `if (document.getElementById('asistente-vacio'))`,
# o sea sólo con el hilo vacío. Con diez mensajes ya pintados, un 422 cada dos
# segundos no cambiaba un solo píxel.

CON_HILO = {"cuerpo": {"abierto": True, "mensajes": [
    {"uuid": "1", "rol": "user", "texto": "hola", "ts": "2026-09-01T10:00:00Z"},
    {"uuid": "2", "rol": "assistant", "texto": "dime", "ts": "2026-09-01T10:00:01Z"}]}}
REGISTRO_ROTO = {"ok": False, "status": 422, "cuerpo": {
    "ok": False, "error": "`projects.yml` no es YAML válido.\n\nla clave "
                          "«conexiones» está dos veces"}}


def test_un_fallo_del_hub_se_avisa_AUNQUE_ya_haya_conversacion(tmp_path):
    """El test que faltaba. Los cinco de arriba comprueban el hilo vacío, que es
    donde el aviso ya funcionaba; el caso real es el contrario."""
    r = _todo(tmp_path, REGISTRO_ROTO)
    assert r["aviso"], "un 422 en cada sondeo no dijo absolutamente nada"


def test_el_aviso_dice_el_motivo_que_da_el_hub_y_no_sólo_el_codigo(tmp_path):
    """El hub SABÍA qué pasaba —«la clave conexiones está dos veces»— y esa frase
    no llegaba a ninguna pantalla. Hubo que abrir una terminal para leerla."""
    r = _todo(tmp_path, REGISTRO_ROTO)
    assert "conexiones" in r["aviso"] and "YAML" in r["aviso"]


def test_el_aviso_no_se_lleva_por_delante_la_conversacion(tmp_path):
    """Borrar el hilo para poner un error sería cambiar un problema por dos:
    lo que uno está leyendo es la conversación."""
    r = _todo(tmp_path, REGISTRO_ROTO)
    assert r["aviso"]
    # El hilo no se toca: sigue con lo último que se pintó, o vacío si nunca
    # llegó nada. Lo que NO puede es quedarse en «Cargando…» sin explicación.
    assert "Cargando…" not in r["hilo"]


def test_cuando_el_hub_vuelve_el_aviso_se_retira_solo(tmp_path):
    """Un aviso que se queda pegado después de arreglarlo enseña a ignorarlo."""
    r = _todo(tmp_path, CON_HILO)
    assert r["aviso"] is None


# ── El envío que se tragaba la pregunta ──────────────────────────────────────

ENVIAR = "elemento('asistente-enviar').disparar('click');"


def test_si_el_envio_falla_se_dice_y_NO_se_pierde_lo_escrito(tmp_path):
    """🔴 El peor de los tres, porque además se lleva el texto.

    `const d = (r && r.ok && await r.json()) || {}` convertía cualquier HTTP que
    no fuera `ok` en `{}`, así que ni `d.ok === false` ni `d.enviado === false`
    entraban: no se avisaba, y la caja ya se había vaciado. Se escribía una
    pregunta, desaparecía, y no pasaba nada más.
    """
    r = _todo(tmp_path, REGISTRO_ROTO,
              "elemento('asistente-texto').value = 'una pregunta';\n" + ENVIAR)
    assert r["caja"] == "una pregunta", "la pregunta se perdió al fallar el envío"
    assert r["aviso"], "el envío falló y no se dijo"


def test_un_envio_que_va_bien_deja_la_caja_vacia(tmp_path):
    """La otra mitad: devolver el texto SIEMPRE sería igual de malo, porque
    entonces cada pregunta enviada se quedaría escrita como si no hubiera salido."""
    r = _todo(tmp_path, CON_HILO,
              "elemento('asistente-texto').value = 'una pregunta';\n" + ENVIAR)
    assert r["caja"] == ""
    assert any("/enviar" in u for u in r["peticiones"])


OCUPADO = {"cuerpo": {"ok": True, "enviado": False}}


def test_si_el_asistente_esta_ocupado_tampoco_se_pierde_lo_escrito(tmp_path):
    """El tercer camino, y el que ya funcionaba: el hub contesta 200 diciendo
    que no lo envió porque hay un turno en curso. Perder un mensaje largo por
    eso sería la peor manera de fallar aquí.

    Vive aquí y ya no en `test_asistente_js.py`, donde se comprobaba contando
    apariciones de `caja.value = texto` en el fuente: ese contador se puso en
    rojo el día que se añadió un cuarto camino correcto (regla dura 11).
    """
    r = _todo(tmp_path, OCUPADO,
              "elemento('asistente-texto').value = 'una pregunta larga';\n" + ENVIAR)
    assert r["caja"] == "una pregunta larga"
