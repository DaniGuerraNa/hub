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
const _porSelector = {};
globalThis.DOC_OYENTES = {};
const registro = { sockets: [], peticiones: [], errores: [], oyentes: [],
                   observados: [], clases: [], valores: [], portapapeles: [],
                   osc: [], avisos: [], enviados: [], temporizadores: [],
                   pantalla: [], encajes: [], variables: [], alternadas: [],
                   pegados: [], tecleado: [] };

function elemento(id) {
  const el = {
    id, textContent: '', innerHTML: '', open: false, className: '',
    children: [], scrollTop: 0, scrollHeight: 0,
    dataset: { slot: '7', slotPunto: '7', lado: 'rail', preset: 'comodo',
               contenedor: 'demo-db', accion: 'stop', proyecto: 'demo', prompt: 'x' },
    // Las variables de CSS se ANOTAN: son un efecto visible —de ellas depende
    // el alto del terminal cuando sale el teclado— y sin guardarlas un test no
    // puede distinguir «la puso» de «no hizo nada».
    style: { setProperty(k, v){ registro.variables.push([id + ':' + k, v]); },
              removeProperty(k){ registro.variables.push([id + ':' + k, null]); } },
    append(){}, appendChild(){}, showModal(){ this.open = true; }, close(){ this.open = false; },
    scrollIntoView(){},
    // 🔴 Quién pide la pantalla completa importa: al documento es «la página
    // entera» y al marco del terminal es «terminal completa». Un arnés que sólo
    // anotara «entrar» no distinguiría las dos — y eran exactamente las dos que
    // hubo que distinguir para arreglar esto.
    requestFullscreen(){ registro.pantalla.push('entrar:' + id); return Promise.resolve(); },
    classList: { _s: new Set(),
      add(c){this._s.add(c); registro.clases.push(c);}, remove(c){this._s.delete(c)},
      contains(c){return this._s.has(c)},
      toggle(c, f){ const v = f === undefined ? !this._s.has(c) : f;
                    v ? this._s.add(c) : this._s.delete(c);
                    // 🔴 Anotado con el ID delante: `viendo` sobre un bloque u
                    // otro es la diferencia entre mirar una ventana y mirar
                    // otra, y sin saber SOBRE CUÁL se alternó no se puede
                    // probar nada de eso. Es el mismo fallo que ya tuvo
                    // `requestFullscreen` aquí arriba.
                    registro.alternadas.push([id + ':' + c, v]);
                    return v; } },
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
    /* 🔴 Memorizado por selector, igual que el `querySelectorAll` del documento
       y por el mismo motivo: devolviendo un nodo nuevo cada vez, el botón al
       que el script le puso el `click` no volvía a aparecer nunca y era
       **imposible de pulsar** desde un test. */
    _hijos: {},
    querySelector(sel){ return (this._hijos[sel] ||= elemento(sel)); },
    // Los botones de la barra de teclas, con su tecla: sin ellos no había
    // nada que pulsar y la barra entera quedaba sin probar.
    querySelectorAll(sel){
      if (sel !== '[data-tecla]') return [];
      return (this._hijos[sel] ||= ['esc', 'ctrl-c', 'shift-tab', 'arriba'].map(t => {
        const b = elemento('tecla-' + t); b.dataset = { tecla: t }; return b; }));
    },
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
  /* 🔴 Memorizados por selector, no recién hechos en cada llamada.
     Devolviendo elementos nuevos, un `querySelectorAll(sel).forEach(b => b.onclick = ...)`
     ponía el manejador en objetos que nadie volvía a ver: esa forma de registrar
     —que la página usa para los presets y para los botones de lado— era
     **imposible de pulsar** desde un test, y por tanto imposible de probar. */
  querySelectorAll: (sel) => (_porSelector[sel] ||= (() => {
    const tres = [elemento('a'), elemento('b'), elemento('c')];
    /* Los bloques del panel derecho llevan SU índice de ventana, que es de lo
       único que depende cuál se enseña. Sin él, `mostrarPanelDe` no casaba con
       ninguno y el arnés no distinguía «marcó el bloque bueno» de «no marcó
       ninguno» — que era exactamente el fallo a cazar. */
    if (sel === '.por-ventana') tres.forEach((el, i) => { el.dataset.ventana = String(i); });
    return tres;
  })()),
  createElement: () => elemento('nuevo'),
  body: elemento('body'),
  // `documentElement` y la API de pantalla completa. Faltaban, y sin ellas un
  // `elemento.requestFullscreen?.()` —código perfectamente válido— moría en el
  // arnés y sólo en el arnés. Es la misma razón por la que se añadió
  // `querySelector` aquí arriba: un arnés al que le falta una API estándar
  // convierte código correcto en un fallo, que es el peor tipo de test.
  documentElement: elemento('html'),
  fullscreenElement: null,
  exitFullscreen: () => { registro.pantalla.push('salir'); return Promise.resolve(); },
  // Las funciones también, por evento: soltar un archivo se escucha en el
  // documento entero, y sin poder dispararlo no se podía probar.
  addEventListener(ev, fn){ registro.oyentes.push('document:' + ev);
                            (globalThis.DOC_OYENTES[ev] ||= []).push(fn); },
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
global.innerHeight = 844;
// 🔴 El viewport VISUAL, que no es el de maquetación. Faltaba, y sin él todo el
// manejo del teclado del móvil quedaba detrás de un `if (vista)` que nunca era
// cierto: los tests pasaban sin ejecutar una sola línea de eso. Un arnés que no
// trae una API no prueba que el código sobre ella funcione; prueba que no
// revienta al saltársela.
global.visualViewport = {
  height: 844, width: 390, offsetTop: 0, _oyentes: {},
  addEventListener(ev, fn){ (this._oyentes[ev] ||= []).push(fn); },
  // Para que un test pueda ABRIR el teclado, que es el único suceso que importa.
  // Abrir el teclado encoge Y DESPLAZA: medido en un teléfono real, 759 → 435
  // con un desplazamiento de 257. Un arnés que sólo encogiera no reproduciría
  // el fallo que hubo que arreglar.
  abrirTeclado(alto, desplazado){
    this.height = alto;
    this.offsetTop = desplazado === undefined ? (alto < 700 ? 257 : 0) : desplazado;
    (this._oyentes['resize'] || []).forEach(f => f({}));
    (this._oyentes['scroll'] || []).forEach(f => f({}));
  },
};
global.addEventListener = (ev) => registro.oyentes.push('window:' + ev);
global.removeEventListener = () => {};
// En el navegador `window` ES el objeto global. Sin esto, un script que use
// `window.addEventListener` —perfectamente válido— fallaba sólo en el arnés.
global.window = global;
// Un `fetch` que puede contestar. La respuesta por defecto sigue siendo `[]`,
// pero un test puede dar cuerpos por trozo de URL: sin eso sólo se comprobaba
// a quién se le piden los datos, nunca qué se hace con ellos.
const RESPUESTAS = __RESPUESTAS__;
global.fetch = (url, opciones) => {
  registro.peticiones.push(url);
  // Una misma URL sirve para dos cosas —`/ventanas` lista con GET y crea con
  // POST—, así que una respuesta puede declararse como «POST /api/…» cuando el
  // test necesita separarlas. Sin método, la clave vale para cualquiera.
  const metodo = ((opciones && opciones.method) || 'GET').toUpperCase();
  // El cuerpo, no sólo la URL: «a quién se le pide» no dice si se le pidió lo
  // correcto, y aquí lo que importaba era justo el dato que va dentro.
  if (opciones && opciones.body !== undefined) {
    let cuerpo = opciones.body;
    try { cuerpo = JSON.parse(cuerpo); } catch (e) {}
    registro.enviados.push({ url: String(url), metodo, cuerpo });
  }
  const claves = Object.keys(RESPUESTAS);
  const conMetodo = (k) => /^[A-Z]+ /.test(k);
  const clave =
    claves.find(k => conMetodo(k) && k.startsWith(metodo + ' ')
                     && String(url).includes(k.slice(k.indexOf(' ') + 1)))
    ?? claves.find(k => !conMetodo(k) && String(url).includes(k));
  const cuerpo = clave === undefined ? [] : RESPUESTAS[clave];
  return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(cuerpo) });
};
// Las INSTANCIAS, no sólo sus URLs. Sin poder disparar `onclose` sólo se podía
// comprobar que alguien abrió un socket, que no dice nada sobre qué pasa cuando
// se cierra — y ahí es donde vive el mensaje que el usuario lee.
global.__sockets = [];
// Los temporizadores programados, con su espera. El arnés vuelca el registro a
// los ~40 ms, así que un reintento a 1 s no llega a ejecutarse nunca: sin esto,
// «¿sigue reintentando?» no se puede comprobar sin dormir un segundo en cada
// test. Se registra y se delega — no es un reloj falso.
const _setTimeout = global.setTimeout;
global.setTimeout = function (fn, ms, ...resto) {
  registro.temporizadores.push(ms || 0);
  return _setTimeout(fn, ms, ...resto);
};
global.WebSocket = class {
  static OPEN = 1;
  constructor(url) { this.url = url; this.readyState = 0;
                     registro.sockets.push(url); global.__sockets.push(this); }
  // Lo que sale por el socket es lo tecleado: se anota como texto.
  send(d) { registro.tecleado.push(typeof d === 'string' ? d : new TextDecoder().decode(d)); }
  close() {}
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
  paste(d) { registro.pegados.push(d); }
  // El filtro de teclas: se guarda para poder preguntarle qué deja pasar.
  attachCustomKeyEventHandler(fn) { globalThis.FILTRO_TECLAS = fn; }
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
// Los `fit()` se CUENTAN: reajustar el terminal es lo que mantiene de acuerdo a
// xterm y a tmux sobre cuántas filas y columnas hay, y sin contarlos un test no
// puede distinguir «reajustó» de «no hizo nada» — que es justo la diferencia
// entre la pantalla correcta y letras que faltan (decisiones 90 y 93).
global.FitAddon = { FitAddon: class {
  activate(){} dispose(){} fit() { registro.encajes.push(1); }
} };
global.HubUI = {
  confirmar: () => Promise.resolve(false),
  preguntar: () => Promise.resolve(null),
  // Se registra: un aviso que el script decide enseñar es un efecto visible, y
  // sin guardarlo no se puede distinguir «avisó» de «no hizo nada».
  avisar: (opciones) => { registro.avisos.push(opciones); return Promise.resolve(); },
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

// Lo que el navegador ya trae ANTES de que la página arranque: lo guardado de
// una visita anterior. Sin esto no se puede probar nada que se restaure —y el
// tamaño de letra del terminal se perdía en cada carga sin que ningún test se
// enterara, porque todos empezaban con el localStorage vacío.
try { __PREVIO__ } catch (e) { registro.errores.push('previo: ' + String(e)); }

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
    guion: str, tmp_path, respuestas: dict | None = None, accion: str = "",
    previo: str = "",
) -> dict:
    """Ejecuta el script.

    `respuestas` mapea trozo de URL → cuerpo JSON. `accion` es JavaScript que
    se ejecuta cuando la página ya arrancó — para provocar un clic, un
    `mouseup` o lo que el test quiera comprobar. `previo` es JavaScript que se
    ejecuta ANTES, para dejar el navegador como lo dejó una visita anterior.
    """
    node = shutil.which("node")
    if not node:
        pytest.skip("node no disponible")
    archivo = tmp_path / "arnes.js"
    archivo.write_text(
        ARNES.replace("__RESPUESTAS__", json.dumps(respuestas or {}))
             .replace("__PREVIO__", previo or "")
             .replace("__ACCION__", accion or "")
             .replace("__GUION__", guion),
        encoding="utf-8",
    )
    salida = subprocess.run([node, str(archivo)], capture_output=True, text=True, timeout=30)
    assert salida.returncode == 0, salida.stderr
    return json.loads(salida.stdout.strip().splitlines()[-1])
