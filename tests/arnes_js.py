"""Arnés para ejecutar de verdad el JavaScript de las plantillas.

Existe por un fallo real: `let ws` declarado después de la función que lo leía al
arrancar dejaba el terminal en negro, y comprobar el HTTP 200 no lo detectaba —
la página se servía perfecta y el navegador moría al ejecutarla.

Regla que deja: **si el arranque del script falla, la página no funciona**, así
que el script se ejecuta en node con sustitutos mínimos de navegador y se
comprueba lo que haría (abrir el WebSocket, pedir datos…).
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest
from jinja2 import Environment, FileSystemLoader

from hub import insignias

RAIZ = Path(__file__).resolve().parents[1] / "src" / "hub"
PLANTILLAS = RAIZ / "templates"
ESTATICOS = RAIZ / "static"

# Sólo lo que las vistas usan. Cada hueco que falte sale como error explícito
# en el test, que es justo lo que queremos.
ARNES = r"""
const registro = { sockets: [], peticiones: [], errores: [], oyentes: [], observados: [] };

function elemento(id) {
  return {
    id, textContent: '', value: '', innerHTML: '', open: false, className: '',
    children: [], scrollTop: 0, scrollHeight: 0,
    dataset: { slot: '7', lado: 'rail', preset: 'comodo',
               contenedor: 'demo-db', accion: 'stop', proyecto: 'demo', prompt: 'x' },
    style: { setProperty(){} },
    append(){}, appendChild(){}, showModal(){ this.open = true; }, close(){ this.open = false; },
    scrollIntoView(){},
    classList: { _s: new Set(),
      add(c){this._s.add(c)}, remove(c){this._s.delete(c)},
      contains(c){return this._s.has(c)},
      toggle(c, f){ const v = f === undefined ? !this._s.has(c) : f;
                    v ? this._s.add(c) : this._s.delete(c); return v; } },
    addEventListener(ev){ registro.oyentes.push(ev); },
    setAttribute(){}, getAttribute(){ return null; }, removeAttribute(){},
    insertAdjacentHTML(pos, html){ this.innerHTML += html; },
    remove(){},
    setPointerCapture(){}, focus(){}, select(){},
    closest(){ return elemento('cercano'); },
    querySelector(){ return elemento('x'); },
    querySelectorAll(){ return []; },
    getBoundingClientRect(){ return { width: 800, height: 600 }; },
    // Lo que necesita un elemento para pasar por `<select>` y por nodo con
    // sitio en el árbol. Faltaba, y el código que envuelve un select —perfecta-
    // mente válido en el navegador— moría aquí con «parentNode is undefined».
    parentNode: { insertBefore(){}, removeChild(){} },
    options: [], selectedIndex: -1, multiple: false, type: '', defaultValue: '',
    contains(){ return false; },
  };
}

global.localStorage = { _d: {}, getItem(k){ return this._d[k] ?? null; }, setItem(k,v){ this._d[k]=v; } };
global.document = {
  getElementById: (id) => elemento(id),
  // `querySelector` en el documento, no sólo en los elementos: faltaba, y un
  // script que lo usara moría con «is not a function» — que en el navegador
  // funciona perfectamente. Un arnés al que le falta una API estándar convierte
  // código correcto en un fallo, que es el peor tipo de test.
  querySelector: () => elemento('x'),
  querySelectorAll: () => [elemento('a'), elemento('b'), elemento('c')],
  createElement: () => elemento('nuevo'),
  body: elemento('body'),
  addEventListener(ev){ registro.oyentes.push('document:' + ev); },
};
// Valores plausibles y no cadenas vacías: quien lo use suele medir con ellos, y
// un `fontSize` vacío da NaN en vez de un fallo que se vea.
global.getComputedStyle = () => ({
  fontFamily: 'monospace', fontSize: '13px', fontWeight: '400',
  fontStyle: 'normal', fontVariant: 'normal', fontFeatureSettings: 'normal',
  letterSpacing: 'normal', width: '800px', font: '',
});
global.location = { protocol: 'http:', host: 'localhost', href: '' };
global.innerWidth = 1600;
global.addEventListener = (ev) => registro.oyentes.push('window:' + ev);
global.removeEventListener = () => {};
// En el navegador `window` ES el objeto global. Sin esto, un script que use
// `window.addEventListener` —perfectamente válido— fallaba sólo en el arnés.
global.window = global;
global.fetch = (url) => { registro.peticiones.push(url);
                          return Promise.resolve({ ok: true, json: () => Promise.resolve([]) }); };
global.WebSocket = class {
  static OPEN = 1;
  constructor(url) { this.url = url; this.readyState = 0; registro.sockets.push(url); }
  send() {} close() {}
};
global.Terminal = class {
  constructor(opts) { this.options = opts; this.rows = 30; this.cols = 100; }
  loadAddon() {} open() {} onData() {} write() {} focus() {}
};
global.FitAddon = { FitAddon: class { activate(){} fit() {} dispose(){} } };
global.HubUI = {
  confirmar: () => Promise.resolve(false),
  preguntar: () => Promise.resolve(null),
  avisar: () => Promise.resolve(),
};
// Sin temporizadores: un sondeo periódico mantendría vivo el proceso de node y
// el arnés colgaría en lugar de reportar.
global.setInterval = () => 0;
// El fit del terminal se aplaza a un frame posterior (xterm recalcula el alto
// de celda de forma asíncrona). Se ejecuta el callback para que el arnés vea
// lo que hace, pero sin encadenar frames indefinidamente.
let framesPendientes = 4;
global.requestAnimationFrame = (fn) => { if (framesPendientes-- > 0) fn(); return 0; };
global.ResizeObserver = class {
  observe(el){ registro.observados.push(el && el.id); }
  unobserve(){} disconnect(){}
};

try {
  __GUION__
} catch (e) {
  registro.errores.push(String(e));
}

console.log(JSON.stringify(registro));
"""


def script_de(plantilla: str, contexto: dict) -> str:
    """Renderiza la plantilla y extrae su último `<script>` en línea."""
    entorno = Environment(loader=FileSystemLoader(str(PLANTILLAS)))
    # El mismo registro que hace `web.py`, y por la misma razón: si el arnés
    # montara su entorno a mano, probaría plantillas que la app no sirve. Ya
    # pasó — al añadir las insignias, cuatro tests reventaron con
    # `'insignia' is undefined` mientras la web funcionaba.
    insignias.registrar(entorno)
    html = entorno.get_template(plantilla).render(**contexto)
    bloques = re.findall(r"<script>\s*(.*?)\s*</script>", html, re.S)
    assert bloques, f"{plantilla} debe traer su script en línea"
    return bloques[-1]


def script_estatico(nombre: str) -> str:
    """El JS que vive en `static/`. Se prueba igual: ejecutándolo (regla dura 11)."""
    return (ESTATICOS / nombre).read_text(encoding="utf-8")


def ejecutar(guion: str, tmp_path) -> dict:
    node = shutil.which("node")
    if not node:
        pytest.skip("node no disponible")
    archivo = tmp_path / "arnes.js"
    archivo.write_text(ARNES.replace("__GUION__", guion), encoding="utf-8")
    salida = subprocess.run([node, str(archivo)], capture_output=True, text=True, timeout=30)
    assert salida.returncode == 0, salida.stderr
    return json.loads(salida.stdout.strip().splitlines()[-1])
