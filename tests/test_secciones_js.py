"""`static/secciones.js`, ejecutado en node (regla dura 11, C-0109).

Lo usan /proyecto, /canal y /encargos, y ningún test lo corría. Lleva su
propio documento mínimo y no el de `arnes_js`: lo que hay que comprobar aquí
—qué sección se enseña según el `#` de la URL, lo recordado y el clic— vive
en `location.hash`, `sessionStorage` e `history`, que aquel arnés no trae, y
en los enlaces del índice, que sus `querySelectorAll` no devuelven.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from hub import web

GUION = (Path(web.__file__).parent / "static" / "secciones.js").read_text(encoding="utf-8")

ARNES = r"""
const registro = { historia: [] };
const clases = (n) => ({ _s: new Set(), add(c){ this._s.add(c); },
  toggle(c, v){ v ? this._s.add(c) : this._s.delete(c); }, has(c){ return this._s.has(c); } });
const SECCIONES = ['estado', 'slots', 'registro'];
const secciones = SECCIONES.map(s => ({ id: 'sec-' + s, classList: clases() }));
const enlaces = SECCIONES.map(s => ({ dataset: { sec: s }, classList: clases(),
  closest(sel){ return sel.endsWith('a[data-sec]') ? this : null; } }));
// El estilo en línea de `ui.seccion_previa()`: lo quita al arrancar (C-0167).
const previa = { quitado: false, remove(){ this.quitado = true; } };
const oyentes = {};
const taller = { dataset: { secciones: 'proyecto' }, classList: clases(),
  querySelectorAll: (sel) => sel === '.seccion' ? secciones : [] };
const indice = { querySelectorAll: (sel) => sel === 'a[data-sec]' ? enlaces : [],
  addEventListener: (ev, f) => { oyentes[ev] = f; } };
// El clic va por delegación en el documento (C-0167): el índice puede
// repintarse sin recargar y un oyente atado a él se perdería.
global.document = {
  querySelector: (sel) => sel === '[data-secciones]' ? taller
                        : sel === '[data-indice-secciones]' ? indice : null,
  querySelectorAll: (sel) => sel === '[data-indice-secciones] a[data-sec]' ? enlaces
                           : sel === 'style[data-seccion-previa]' ? [previa] : [],
  getElementById: (id) => secciones.find(s => s.id === id) || null,
  addEventListener: (ev, f) => { oyentes[ev] = f; },
};
const guardado = __GUARDADO__;
global.sessionStorage = { getItem: (k) => guardado[k] ?? null,
                          setItem: (k, v) => { guardado[k] = v; } };
global.location = { hash: __HASH__ };
global.history = { replaceState: (a, b, url) => registro.historia.push(url) };
global.window = { addEventListener: (ev, f) => { oyentes['window:' + ev] = f; } };

const viendo = () => secciones.filter(s => s.classList.has('viendo')).map(s => s.id);
const aqui = () => enlaces.filter(a => a.classList.has('aqui')).map(a => a.dataset.sec);

__GUION__

registro.alArrancar = { viendo: viendo(), aqui: aqui(), activo: taller.classList.has('con-secciones'),
                        previaQuitada: previa.quitado };
let evitado = false;
oyentes.click({ target: enlaces[2], preventDefault(){ evitado = true; } });
registro.trasClic = { viendo: viendo(), aqui: aqui(), evitado, guardado: { ...guardado } };
location.hash = '#slots';
oyentes['window:hashchange']();
registro.trasHash = viendo();
// Un repintado sin recargar trae las secciones sin `viendo`: se vuelve a poner.
secciones.forEach(s => s.classList.toggle('viendo', false));
oyentes['hub:repintado']();
registro.trasRepintar = viendo();
console.log(JSON.stringify(registro));
"""


def _correr(tmp_path, hash_="", guardado=None):
    node = shutil.which("node")
    if not node:
        pytest.skip("node no disponible")
    archivo = tmp_path / "secciones.js"
    archivo.write_text(ARNES.replace("__GUARDADO__", json.dumps(guardado or {}))
                            .replace("__HASH__", json.dumps(hash_))
                            .replace("__GUION__", GUION), encoding="utf-8")
    salida = subprocess.run([node, str(archivo)], capture_output=True, text=True, timeout=30)
    assert salida.returncode == 0, salida.stderr
    return json.loads(salida.stdout.strip().splitlines()[-1])


def test_sin_hash_ni_recuerdo_enseña_la_primera_seccion(tmp_path):
    r = _correr(tmp_path)
    assert r["alArrancar"] == {"viendo": ["sec-estado"], "aqui": ["estado"], "activo": True,
                               "previaQuitada": True}


def test_el_hash_de_la_url_manda_sobre_lo_recordado(tmp_path):
    r = _correr(tmp_path, "#registro", {"hub:seccion:proyecto": "slots"})
    assert r["alArrancar"]["viendo"] == ["sec-registro"]


def test_sin_hash_vuelve_a_la_ultima_seccion_mirada(tmp_path):
    """Estas páginas hacen POST y redirigen: volver siempre a la primera
    sección perdía el sitio en cada acción."""
    r = _correr(tmp_path, "", {"hub:seccion:proyecto": "slots"})
    assert r["alArrancar"]["viendo"] == ["sec-slots"]


def test_un_hash_que_no_es_una_seccion_cae_en_la_primera(tmp_path):
    r = _correr(tmp_path, "#no-existe")
    assert r["alArrancar"]["viendo"] == ["sec-estado"]


def test_el_clic_cambia_de_seccion_sin_apilar_historia_y_la_recuerda(tmp_path):
    r = _correr(tmp_path)
    assert r["trasClic"] == {"viendo": ["sec-registro"], "aqui": ["registro"], "evitado": True,
                             "guardado": {"hub:seccion:proyecto": "registro"}}
    assert r["historia"] == ["#registro"]
    assert r["trasHash"] == ["sec-slots"]


def test_tras_repintar_sin_recargar_sigue_en_la_misma_seccion(tmp_path):
    """C-0167: `sin-recarga.js` cambia el taller entero y avisa con
    `hub:repintado`; las secciones nuevas llegan sin `viendo`."""
    r = _correr(tmp_path)
    assert r["trasRepintar"] == ["sec-slots"]
