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
// `clases` y `valores` guardan lo que el script ESCRIBIÓ en el DOM. Sin ellos
// sólo se podía comprobar que no reventaba y a quién le pedía datos, no qué
// hacía con la respuesta — y lo que se ve en pantalla es justo eso.
const registro = { sockets: [], peticiones: [], errores: [], oyentes: [],
                   observados: [], clases: [], valores: [], portapapeles: [],
                   osc: [] };

function elemento(id) {
  const el = {
    id, textContent: '', innerHTML: '', open: false, className: '',
    children: [], scrollTop: 0, scrollHeight: 0,
    dataset: { slot: '7', slotPunto: '7', lado: 'rail', preset: 'comodo',
               contenedor: 'demo-db', accion: 'stop', proyecto: 'demo', prompt: 'x' },
    style: { setProperty(){} },
    append(){}, appendChild(){}, showModal(){ this.open = true; }, close(){ this.open = false; },
    scrollIntoView(){},
    classList: { _s: new Set(),
      add(c){this._s.add(c); registro.clases.push(c);}, remove(c){this._s.delete(c)},
      contains(c){return this._s.has(c)},
      toggle(c, f){ const v = f === undefined ? !this._s.has(c) : f;
                    v ? this._s.add(c) : this._s.delete(c); return v; } },
    // Se guarda la FUNCIÓN, no sólo el nombre: sin ella no se puede disparar el
    // evento y sólo se podía comprobar que alguien escuchaba, no qué hace.
    _oyentes: {},
    addEventListener(ev, fn){ registro.oyentes.push(ev);
                              (this._oyentes[ev] ||= []).push(fn); },
    disparar(ev, arg){ (this._oyentes[ev] || []).forEach(f => f(arg || {})); },
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
  // `value` con setter para poder ver qué texto se escribió. Escribir en un
  // `textarea` es una asignación normal, así que no hay otra forma de mirarlo.
  let valor = '';
  Object.defineProperty(el, 'value', {
    get(){ return valor; },
    set(v){ valor = v; registro.valores.push(v); },
    enumerable: true,
  });
  return el;
}

global.localStorage = { _d: {}, getItem(k){ return this._d[k] ?? null; }, setItem(k,v){ this._d[k]=v; } };

// 🔴 Cacheado por id, como en el navegador: dos `getElementById` del mismo id
// dan el MISMO nodo. Antes fabricaba uno nuevo cada vez, así que un oyente
// atado en una llamada no existía en la siguiente — y el test podía «disparar»
// un evento que no escuchaba nadie, pasando por no hacer nada.
const _porId = {};
global.nodo = (id) => (_porId[id] ||= elemento(id));

global.document = {
  getElementById: (id) => nodo(id),
  // `querySelector` en el documento, no sólo en los elementos: faltaba, y un
  // script que lo usara moría con «is not a function» — que en el navegador
  // funciona perfectamente. Un arnés al que le falta una API estándar convierte
  // código correcto en un fallo, que es el peor tipo de test.
  querySelector: () => elemento('x'),
  querySelectorAll: () => [elemento('a'), elemento('b'), elemento('c')],
  createElement: () => elemento('nuevo'),
  body: elemento('body'),
  addEventListener(ev){ registro.oyentes.push('document:' + ev); },
  execCommand(orden){ if (orden === 'copy') registro.portapapeles.push('(execCommand)');
                      return !global.EXECCOMMAND_FALLA; },
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
// Un `fetch` que puede contestar. La respuesta por defecto sigue siendo `[]`,
// pero un test puede dar cuerpos por trozo de URL: sin eso sólo se comprobaba
// a quién se le piden los datos, nunca qué se hace con ellos.
const RESPUESTAS = __RESPUESTAS__;
global.fetch = (url) => {
  registro.peticiones.push(url);
  const clave = Object.keys(RESPUESTAS).find(k => String(url).includes(k));
  const cuerpo = clave === undefined ? [] : RESPUESTAS[clave];
  return Promise.resolve({ ok: true, json: () => Promise.resolve(cuerpo) });
};
global.WebSocket = class {
  static OPEN = 1;
  constructor(url) { this.url = url; this.readyState = 0; registro.sockets.push(url); }
  send() {} close() {}
};
global.Terminal = class {
  constructor(opts) {
    this.options = opts; this.rows = 30; this.cols = 100;
    // El registro de secuencias OSC, y la instancia a mano: sin poder DISPARAR
    // el manejador, un test sólo podría comprobar que alguien lo registró, que
    // es precisamente lo que no dice nada sobre lo que hace.
    this.parser = {
      _osc: {},
      registerOscHandler: (codigo, fn) => {
        this.parser._osc[codigo] = fn;
        registro.osc.push(codigo);
      },
    };
    globalThis.TERM = this;
  }
  loadAddon() {} open() {} onData() {} write() {} focus() {}
  // Lo que hay seleccionado con el ratón. `SELECCION` lo fija el test.
  getSelection() { return typeof globalThis.SELECCION === 'string'
                     ? globalThis.SELECCION : ''; }
};
// El portapapeles del navegador: `registro.portapapeles` es lo que de verdad
// habría salido de la máquina.
//
// 🔴 Con `defineProperty` y no con una asignación: Node ya trae un `navigator`
// global de SÓLO LECTURA, así que `global.navigator = {...}` no toma y se
// queda el nativo —que no tiene `clipboard`—. El síntoma era que el test veía
// usarse el plan B de `execCommand` y parecía que el camino bueno fallaba.
Object.defineProperty(globalThis, 'navigator', {
  configurable: true,
  value: {
    clipboard: {
      writeText(t) {
        if (globalThis.CLIPBOARD_FALLA) return Promise.reject(new Error('denegado'));
        registro.portapapeles.push(t);
        return Promise.resolve();
      },
    },
  },
});
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

// El volcado se aplaza un turno: lo que llega por `fetch` se resuelve en
// microtareas, y volcar en la misma vuelta sólo enseñaba la petición saliendo,
// nunca el efecto de la respuesta.
setTimeout(() => {
  // Lo que el test quiera provocar una vez la página ya arrancó.
  try { __ACCION__ } catch (e) { registro.errores.push('accion: ' + String(e)); }
  setTimeout(() => console.log(JSON.stringify(registro)), 20);
}, 20);
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


def ejecutar(
    guion: str, tmp_path, respuestas: dict | None = None, accion: str = ""
) -> dict:
    """Ejecuta el script.

    `respuestas` mapea trozo de URL → cuerpo JSON. `accion` es JavaScript que
    se ejecuta cuando la página ya arrancó — para provocar un clic, un
    `mouseup` o lo que el test quiera comprobar.
    """
    node = shutil.which("node")
    if not node:
        pytest.skip("node no disponible")
    archivo = tmp_path / "arnes.js"
    archivo.write_text(
        ARNES.replace("__RESPUESTAS__", json.dumps(respuestas or {}))
             .replace("__ACCION__", accion or "")
             .replace("__GUION__", guion),
        encoding="utf-8",
    )
    salida = subprocess.run([node, str(archivo)], capture_output=True, text=True, timeout=30)
    assert salida.returncode == 0, salida.stderr
    return json.loads(salida.stdout.strip().splitlines()[-1])
