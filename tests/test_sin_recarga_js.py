"""Enviar un formulario sin recargar la página, ejecutando el JS (regla dura 11, C-0167).

`sin-recarga.js` hace el mismo POST por `fetch`, sigue el mismo 303 y cambia
sólo las `data-region` de la página de destino. Aquí se ejecuta en node sobre
un DOM mínimo —sólo lo que el script toca— y se mira qué hizo con cada
respuesta: la buena, la que lleva a otra pantalla y las que fallan.
"""

from __future__ import annotations

import pytest

from arnes_js import ejecutar, script_estatico

GUION = script_estatico("sin-recarga.js")

# Un DOM de juguete: árbol de nodos con lo que el script usa (selectores
# concretos, `replaceWith`, `closest`, `dataset`). El HTML que «llega» no se
# parsea: `DOMParser` devuelve el árbol que el test declaró para ese texto.
DOM = r"""
class Nodo {
  constructor(tag, datos = {}, hijos = []) {
    this.tagName = tag.toUpperCase();
    this.id = datos.id || '';
    this.dataset = { ...(datos.dataset || {}) };
    this.clases = new Set(datos.clases || []);
    this.texto = datos.texto || '';
    this.name = datos.name || ''; this.value = datos.value || '';
    this.open = !!datos.open; this.disabled = false; this.scrollTop = datos.scrollTop || 0;
    this.offsetHeight = 120; this.style = {}; this.atributos = {};
    this.action = datos.action || ''; this.complete = true;
    this.padre = null; this.hijos = [];
    hijos.forEach((h) => this.append(h));
    const yo = this;
    this.classList = { add(c){ yo.clases.add(c); }, remove(c){ yo.clases.delete(c); },
                       contains(c){ return yo.clases.has(c); } };
    if (this.tagName === 'FORM') {
      this.reseteado = 0;
      this.reset = () => { this.reseteado++; };
    }
  }
  get textContent() { return this.texto; }
  set textContent(v) { this.texto = v; }
  append(h) { h.padre = this; this.hijos.push(h); }
  after(h) { const i = this.padre.hijos.indexOf(this); h.padre = this.padre; this.padre.hijos.splice(i + 1, 0, h); }
  prepend(h) { h.padre = this; this.hijos.unshift(h); }
  remove() { if (this.padre) this.padre.hijos.splice(this.padre.hijos.indexOf(this), 1); this.padre = null; }
  replaceWith(n) { const p = this.padre; const i = p.hijos.indexOf(this); n.padre = p; p.hijos[i] = n; this.padre = null; }
  get isConnected() { let n = this; while (n.padre) n = n.padre; return n === RAIZ; }
  get form() { let n = this.padre; while (n && n.tagName !== 'FORM') n = n.padre; return n; }
  getAttribute(k) { if (k === 'method') return this.dataset.metodo || 'post';
                    if (k === 'action') return this.action || null;
                    return k in this.atributos ? this.atributos[k] : null; }
  setAttribute(k, v) { this.atributos[k] = v; }
  removeAttribute(k) { delete this.atributos[k]; }
  get outerHTML() { return JSON.stringify([this.tagName, this.id, this.dataset, [...this.clases],
                                          this.texto, this.hijos.map((h) => h.outerHTML)]); }
  todos() { return this.hijos.flatMap((h) => [h, ...h.todos()]); }
  casa(sel) {
    if (sel === '[data-region]') return 'region' in this.dataset;
    if (sel === '[data-aviso-fugaz]') return 'avisoFugaz' in this.dataset;
    if (sel === 'details:not(.menu)') return this.tagName === 'DETAILS' && !this.clases.has('menu');
    if (sel === 'form[data-sin-recarga]') return this.tagName === 'FORM' && 'sinRecarga' in this.dataset;
    if (sel === 'button, input[type=submit]') return this.tagName === 'BUTTON';
    if (sel === '[id]') return !!this.id;
    if (sel.startsWith('#')) return this.id === sel.slice(1);
    return this.tagName === sel.toUpperCase();
  }
  querySelectorAll(sel) {
    if (sel === ':scope > summary') return this.hijos.filter((h) => h.tagName === 'SUMMARY');
    return this.todos().filter((n) => n.casa(sel));
  }
  querySelector(sel) {
    if (sel === '.envoltura > header') return this.todos().find((n) => n.tagName === 'HEADER') || null;
    return this.querySelectorAll(sel)[0] || null;
  }
  matches(sel) { return this.casa(sel); }
  closest(sel) { let n = this; while (n && !(n.casa && n.casa(sel))) n = n.padre; return n || null; }
}
const N = (tag, datos, hijos) => new Nodo(tag, datos, hijos);
const clonar = (n) => N(n.tagName.toLowerCase(), { id: n.id, dataset: n.dataset, clases: [...n.clases],
                                                   texto: n.texto }, n.hijos.map(clonar));

// La página que se está mirando.
const boton = N('button', { name: 'accion', value: 'borrar', texto: 'Borrar' });
const formLista = N('form', { id: 'f-lista', action: 'http://localhost/tablero/idea/3/descartar',
                             dataset: { sinRecarga: '' } }, [boton]);
const formFuera = N('form', { id: 'f-fuera', action: 'http://localhost/tablero/idea',
                             dataset: { sinRecarga: '' } }, [N('button', { texto: 'Apuntar' })]);
const plegado = N('details', { open: true }, [N('summary', { texto: '3 permisos' }), formLista]);
const region = N('div', { dataset: { region: 'ideas' }, texto: 'vieja', scrollTop: 40 }, [plegado]);
const RAIZ = N('html', {}, [N('body', {}, [N('div', { clases: ['envoltura'] },
                [N('header'), formFuera, region])])]);
globalThis.RAIZ = RAIZ; globalThis.REGION = region; globalThis.BOTON = boton;
globalThis.FORM_LISTA = formLista; globalThis.FORM_FUERA = formFuera;

// Las páginas que puede devolver el servidor, por el texto de la respuesta.
const PAGINAS = {
  destino: () => N('html', {}, [N('body', {}, [N('div', { clases: ['envoltura'] }, [
    N('header'),
    N('div', { dataset: { avisoFugaz: '' }, clases: ['aviso-accion', 'fugaz'], texto: 'Descartada' }),
    N('div', { dataset: { region: 'ideas' }, texto: 'nueva' },
      [N('details', {}, [N('summary', { texto: '4 permisos' }),
                         N('form', { action: 'http://localhost/tablero/idea/3/descartar' }),
                         N('form', { action: 'http://localhost/otra' })])]),
  ])])]),
  'hecho-con-fallo': () => N('html', {}, [N('body', {}, [N('div', { clases: ['envoltura'] }, [
    N('header'),
    N('div', { dataset: { avisoFugaz: '', hecho: '' }, clases: ['aviso-accion'], texto: 'Apuntada, pero no entró' }),
    N('div', { dataset: { region: 'ideas' }, texto: 'nueva' }),
  ])])]),
  'tres-editar': () => N('html', {}, [N('body', {}, [N('div', { clases: ['envoltura'] }, [
    N('header'),
    N('div', { dataset: { region: 'ideas' }, texto: 'nueva' }, [
      N('details', {}, [N('summary', { texto: 'Editar' })]),
      N('details', {}, [N('summary', { texto: 'Editar' })]),
      N('details', {}, [N('summary', { texto: 'Editar' })]),
    ]),
  ])])]),
  'tarea': () => N('html', {}, [N('body', {}, [N('div', { clases: ['envoltura'] }, [
    N('header'),
    N('div', { dataset: { region: 'ideas' }, texto: 'la tarea t-1' }),
  ])])]),
  'con-fallo': () => N('html', {}, [N('body', {}, [N('div', { clases: ['envoltura'] }, [
    N('header'),
    N('div', { dataset: { avisoFugaz: '' }, clases: ['aviso-accion'], texto: 'No entró' }),
    N('div', { dataset: { region: 'ideas' }, texto: 'nueva' }),
  ])])]),
  'sin-regiones': () => N('html', {}, [N('body', {}, [N('div', { texto: 'otra cosa' })])]),
  // La pantalla tal cual se cargó: lo que el servidor contestaría si nada cambió.
  'la-misma': () => N('html', {}, [N('body', {}, [N('div', { clases: ['envoltura'] }, [
    N('header'), clonar(globalThis.REGION)])])]),
};
global.DOMParser = class { parseFromString(t) { const r = PAGINAS[t](); return {
  querySelectorAll: (s) => r.querySelectorAll(s), querySelector: (s) => r.querySelector(s) }; } };

const oyentesSubmit = [];
const eventos = [];
global.document = {
  querySelectorAll: (s) => RAIZ.querySelectorAll(s),
  querySelector: (s) => s === '[data-params-de-region]' ? (globalThis.PARAMS || null) : RAIZ.querySelector(s),
  adoptNode: (n) => n,
  body: RAIZ.hijos[0],
  addEventListener(ev, fn) { if (ev === 'submit') oyentesSubmit.push(fn); },
  dispatchEvent(e) { eventos.push([e.type, e.detail]); },
};
global.CSS = { escape: (s) => s };
global.FormData = class {
  constructor(form, boton) { this.campos = [['formulario', form.id]];
                             if (boton && boton.name) this.campos.push([boton.name, boton.value]); }
  has(k) { return this.campos.some(([c]) => c === k); }
  append(k, v) { this.campos.push([k, v]); }
};
global.location = { href: 'http://localhost/tablero?aviso=Vieja&fugaz=1', hash: '#ideas',
  assign(u) { registro.asignada = u; }, reload() { registro.recargada = true; } };
global.history = { state: null, replaceState(s, t, u) { registro.direccion = u; } };

// El servidor: `RESPUESTA` la pone cada test.
const contestar = (r) => ({ ok: r.estado < 400, status: r.estado, url: r.url, redirected: r.redirigida,
    headers: { get: () => r.tipo || 'text/html; charset=utf-8' },
    text: () => Promise.resolve(r.texto) });
// `RETENER`: las respuestas se quedan en `PENDIENTES` y el test decide cuándo
// llega cada una (para ver qué pasa si llegan desordenadas).
globalThis.PENDIENTES = [];
global.fetch = (url, op) => {
  registro.peticiones.push([String(url), (op && op.method) || 'GET',
                            op && op.body ? op.body.campos : null]);
  const r = { ...globalThis.RESPUESTA, ...((globalThis.POR_METODO || {})[(op && op.method) || 'GET'] || {}) };
  if (r.red) return Promise.reject(new TypeError('Failed to fetch'));
  if (globalThis.RETENER) return new Promise((ok) => globalThis.PENDIENTES.push(() => ok(contestar(r))));
  return Promise.resolve(contestar(r));
};

globalThis.ENVIAR = (form, submitter, prevenido) => {
  const e = { target: form, submitter, defaultPrevented: !!prevenido,
              preventDefault() { this.defaultPrevented = true; } };
  oyentesSubmit.forEach((f) => f(e));
  registro.prevenido = e.defaultPrevented;
};
globalThis.FOTO = () => {
  const r = document.querySelector('[data-region]');
  registro.region = r ? r.texto : null;
  registro.mismaRegion = r === REGION;
  registro.plegadoAbierto = r ? r.querySelectorAll('details:not(.menu)').map((d) => d.open) : [];
  registro.scrollRegion = r ? r.scrollTop : null;
  const a = document.querySelector('[data-aviso-fugaz]');
  registro.aviso = a ? a.texto : null;
  registro.avisoTrasCabecera = a ? a.padre.hijos.indexOf(a) === 1 : null;
  registro.eventos = eventos;
  registro.botonApagado = BOTON.disabled;
  registro.reseteadoFuera = FORM_FUERA.reseteado;
  registro.ocupado = FORM_LISTA.dataset.enviando || null;
};
"""


def _respuesta(**r) -> str:
    base = {"estado": 200, "url": "http://localhost/tablero?aviso=Descartada&fugaz=1",
            "redirigida": True, "texto": "destino"}
    base.update(r)
    import json
    return f"globalThis.RESPUESTA = {json.dumps(base)};"


def _correr(tmp_path, accion: str, **respuesta) -> dict:
    # Dos vueltas: la acción y, cuando ya resolvieron las promesas, la foto.
    return ejecutar(GUION, tmp_path, previo=DOM + _respuesta(**respuesta),
                    accion=accion + "; setTimeout(FOTO, 5);")


def test_hace_el_mismo_post_y_cambia_solo_su_region(tmp_path):
    r = _correr(tmp_path, "ENVIAR(FORM_LISTA, BOTON)")

    assert r["errores"] == []
    assert r["prevenido"] is True
    url, metodo, campos = r["peticiones"][0]
    assert (url, metodo) == ("http://localhost/tablero/idea/3/descartar", "POST")
    # El `name=value` del botón viaja: «accion=borrar» es lo que decide la ruta.
    assert ["accion", "borrar"] in campos
    assert r["region"] == "nueva" and r["mismaRegion"] is False
    assert "asignada" not in r and "recargada" not in r
    assert ["hub:repintado", {"regiones": ["ideas"]}] in r["eventos"]


def test_la_direccion_queda_sin_el_aviso_y_con_su_seccion(tmp_path):
    r = _correr(tmp_path, "ENVIAR(FORM_LISTA, BOTON)")

    assert r["direccion"] == "/tablero#ideas"


def test_lo_abierto_sigue_abierto_y_el_scroll_de_la_lista_tambien(tmp_path):
    """Conceder un permiso cerraba el plegado donde estaba el botón (medido el
    6-nov en /canal). Aquí el plegado tiene varios formularios... uno: se casa
    por orden y vuelve abierto aunque su resumen cambió de cifra."""
    r = _correr(tmp_path, """
      REGION.hijos[0].append(new FORM_LISTA.constructor('form', {}));
      ENVIAR(FORM_LISTA, BOTON)""")

    assert r["plegadoAbierto"] == [True]
    assert r["scrollRegion"] == 40


def test_el_plegado_de_editar_se_cierra_al_guardar_bien(tmp_path):
    """Un plegado con un solo formulario es una edición: guardada, acabó."""
    r = _correr(tmp_path, "ENVIAR(FORM_LISTA, BOTON)")

    assert r["plegadoAbierto"] == [False]


def test_el_aviso_de_la_accion_se_pinta_tras_la_cabecera(tmp_path):
    r = _correr(tmp_path, "ENVIAR(FORM_LISTA, BOTON)")

    assert r["aviso"] == "Descartada"
    assert r["avisoTrasCabecera"] is True


def test_un_formulario_fuera_de_la_region_se_vacia_si_salio_bien(tmp_path):
    r = _correr(tmp_path, "ENVIAR(FORM_FUERA, null)")

    assert r["reseteadoFuera"] == 1


def test_si_vuelve_un_fallo_lo_escrito_no_se_borra(tmp_path):
    r = _correr(tmp_path, "ENVIAR(FORM_FUERA, null)", texto="con-fallo",
                url="http://localhost/tablero?aviso=No%20entr%C3%B3")

    assert r["aviso"] == "No entró"
    assert r["reseteadoFuera"] == 0


def test_si_el_303_lleva_a_otra_pantalla_navega_como_antes(tmp_path):
    r = _correr(tmp_path, "ENVIAR(FORM_LISTA, BOTON)",
                url="http://localhost/trabajo?session=hub&ventana=2")

    assert r["asignada"] == "http://localhost/trabajo?session=hub&ventana=2"
    assert r["region"] == "vieja"


def test_si_las_regiones_no_casan_navega_en_vez_de_mezclar(tmp_path):
    r = _correr(tmp_path, "ENVIAR(FORM_LISTA, BOTON)", texto="sin-regiones")

    assert r["asignada"] == "http://localhost/tablero?aviso=Descartada&fugaz=1"
    assert r["region"] == "vieja"


def test_un_403_de_origen_se_dice_y_no_toca_nada(tmp_path):
    """Regla dura 21: lo que falla se dice. Y el botón vuelve a estar vivo."""
    r = _correr(tmp_path, "ENVIAR(FORM_LISTA, BOTON)", estado=403, redirigida=False,
                url="http://localhost/tablero/idea/3/descartar", tipo="application/json",
                texto='{"ok": false, "error": "petición rechazada: viene de otro sitio web"}')

    assert r["avisos"] and "viene de otro sitio web" in r["avisos"][0]["mensaje"]
    assert r["region"] == "vieja" and r["mismaRegion"] is True
    assert r["botonApagado"] is False and r["ocupado"] is None
    assert "asignada" not in r


def test_un_500_tambien_se_dice(tmp_path):
    r = _correr(tmp_path, "ENVIAR(FORM_LISTA, BOTON)", estado=500, redirigida=False,
                texto="Internal Server Error")

    assert "500" in r["avisos"][0]["mensaje"]
    assert r["region"] == "vieja"


def test_sin_red_se_dice_que_no_se_sabe_si_llego(tmp_path):
    r = _correr(tmp_path, "ENVIAR(FORM_LISTA, BOTON)", red=True)

    assert "Sin conexión" in r["avisos"][0]["mensaje"]
    assert r["region"] == "vieja" and r["botonApagado"] is False


def test_si_la_confirmacion_paro_el_envio_no_hace_nada(tmp_path):
    """`data-confirmar` va antes, en captura: si pregunta, aquí no se envía."""
    r = _correr(tmp_path, "ENVIAR(FORM_LISTA, BOTON, true)")

    assert r["peticiones"] == []


@pytest.mark.parametrize("codigo", ["refrescar()", "refrescar(['ideas'])"])
def test_refrescar_cambia_la_region_y_no_toca_el_aviso(tmp_path, codigo):
    """Para el navegante y los contenedores: la misma pantalla, por GET."""
    r = _correr(tmp_path, f"""
      const aviso = new FORM_LISTA.constructor('div', {{ dataset: {{ avisoFugaz: '' }}, texto: 'sin cerrar' }});
      RAIZ.hijos[0].hijos[0].prepend(aviso);
      HubSinRecarga.{codigo}""")

    assert r["peticiones"][0] == ["/tablero", "GET", None]
    assert r["region"] == "nueva"
    assert r["aviso"] == "sin cerrar", "un sondeo no se lleva un aviso que nadie cerró"


def test_refrescar_dos_veces_lo_mismo_no_repinta_la_segunda(tmp_path):
    """El parpadeo de los sondeos: repintar lo mismo cada pocos segundos."""
    r = _correr(tmp_path, """
      HubSinRecarga.refrescar().then(() => {
        globalThis.PRIMERA = document.querySelector('[data-region]');
        return HubSinRecarga.refrescar();
      }).then((hechas) => {
        registro.segunda = hechas;
        registro.mismoNodo = document.querySelector('[data-region]') === globalThis.PRIMERA;
      })""")

    assert r["segunda"] == []
    assert r["mismoNodo"] is True


def test_el_primer_sondeo_no_repinta_lo_que_no_cambio_desde_que_se_cargo(tmp_path):
    """C-0187: lo servido empezaba vacío y el primer `refrescar()` repintaba
    todas las regiones aunque nada hubiera cambiado: el botón que tenía el
    foco desaparecía bajo el dedo."""
    r = _correr(tmp_path, """
      HubSinRecarga.refrescar().then((hechas) => { registro.primera = hechas; })""", texto="la-misma")

    assert r["primera"] == []
    assert r["mismaRegion"] is True


def test_un_fallo_que_dice_que_se_hizo_vacia_el_formulario(tmp_path):
    """«Apuntada, pero no entró el adjunto»: la idea está. Dejar el texto
    escrito invitaba a pulsar otra vez y duplicarla (`_volver(hecho=True)`)."""
    r = _correr(tmp_path, "ENVIAR(FORM_FUERA, null)", texto="hecho-con-fallo",
                url="http://localhost/tablero?aviso=Apuntada&hecho=1")

    assert r["aviso"] == "Apuntada, pero no entró"
    assert r["reseteadoFuera"] == 1
    assert r["direccion"] == "/tablero#ideas"


def test_lo_que_solo_cambia_regiones_no_obliga_a_recargar(tmp_path):
    """El orquestador vuelve a `?tarea=<id>` aunque se actúe desde
    `/orquestador`; la página declara que `tarea` sólo cambia sus regiones."""
    r = _correr(tmp_path, """
      globalThis.PARAMS = { dataset: { paramsDeRegion: 'tarea proyecto' } };
      ENVIAR(FORM_LISTA, BOTON)""", texto="tarea", url="http://localhost/tablero?tarea=t-1")

    assert "asignada" not in r
    assert r["region"] == "la tarea t-1"
    assert r["direccion"] == "/tablero?tarea=t-1#ideas"


def test_sin_declararlo_otro_parametro_es_otra_pantalla(tmp_path):
    r = _correr(tmp_path, "ENVIAR(FORM_LISTA, BOTON)", texto="tarea",
                url="http://localhost/tablero?tarea=t-1")

    assert r["asignada"] == "http://localhost/tablero?tarea=t-1"


def test_un_sondeo_que_llega_despues_de_una_accion_no_la_deshace(tmp_path):
    """Permitir quitaba la pregunta y el sondeo que había salido antes la
    devolvía hasta el siguiente latido."""
    r = _correr(tmp_path, """
      globalThis.RETENER = true;
      globalThis.POR_METODO = { GET: { texto: 'tarea', url: 'http://localhost/tablero' } };
      const sondeo = HubSinRecarga.refrescar();
      ENVIAR(FORM_LISTA, BOTON);
      setTimeout(() => {
        PENDIENTES[1]();               // llega antes la acción
        setTimeout(() => {
          PENDIENTES[0]();             // y después el sondeo de antes
          sondeo.then((h) => { registro.sondeo = h; });
        }, 1);
      }, 1)""")

    assert r["region"] == "nueva"
    assert r["sondeo"] == []


def test_la_respuesta_de_un_envio_anterior_no_pisa_la_de_uno_posterior(tmp_path):
    r = _correr(tmp_path, """
      globalThis.RETENER = true;
      ENVIAR(FORM_LISTA, BOTON);
      globalThis.RESPUESTA = { ...RESPUESTA, texto: 'tarea' };
      ENVIAR(FORM_FUERA, null);
      setTimeout(() => {
        PENDIENTES[1]();
        setTimeout(() => PENDIENTES[0](), 1);
      }, 1)""")

    assert r["region"] == "la tarea t-1"


def test_un_422_dice_que_campo_falta_y_no_object_object(tmp_path):
    r = _correr(tmp_path, "ENVIAR(FORM_LISTA, BOTON)", estado=422, redirigida=False,
                tipo="application/json",
                texto='{"detail": [{"loc": ["body", "texto"], "msg": "Field required"}]}')

    assert "Field required" in r["avisos"][0]["mensaje"]
    assert "object" not in r["avisos"][0]["mensaje"]


def test_una_respuesta_sin_303_ni_html_se_dice_y_no_se_pinta(tmp_path):
    r = _correr(tmp_path, "ENVIAR(FORM_LISTA, BOTON)", redirigida=False, tipo="application/json",
                url="http://localhost/tablero/idea/3/descartar", texto='{"ok": true}')

    assert "recarga la página" in r["avisos"][0]["mensaje"]
    assert r["region"] == "vieja" and "asignada" not in r


def test_con_el_texto_repetido_no_se_abren_todos_los_plegados(tmp_path):
    """Borrar un slot con el «Editar» de otro abierto: el número de plegados
    cambia, el resumen es el mismo en todos, y no se puede saber cuál era."""
    r = _correr(tmp_path, """
      const P = globalThis.PAGINAS_EXTRA = true;
      REGION.hijos.length = 0;
      const d1 = new FORM_LISTA.constructor('details', { open: true }, [new FORM_LISTA.constructor('summary', { texto: 'Editar' })]);
      const d2 = new FORM_LISTA.constructor('details', {}, [new FORM_LISTA.constructor('summary', { texto: 'Editar' })]);
      REGION.append(d1); REGION.append(d2); REGION.append(FORM_LISTA);
      ENVIAR(FORM_LISTA, BOTON)""", texto="tres-editar")

    assert r["plegadoAbierto"] == [False, False, False]



def test_un_fallo_que_llega_en_error_se_ensena_entero_aunque_se_repita(tmp_path):
    """Revisor de C-0233: tras un primer fallo la dirección ya es
    `?error=X`; un segundo fallo igual volvía a la misma, se tomaba por un
    acierto, se vaciaba el formulario y no salía nada nuevo."""
    previo_error = "location.href = 'http://localhost/conexiones?error=ya%20existe';"
    r = ejecutar(GUION, tmp_path, previo=DOM + _respuesta(url="http://localhost/conexiones?error=ya%20existe") + previo_error,
                 accion="ENVIAR(FORM_FUERA, null); setTimeout(FOTO, 5);")
    assert r["asignada"] == "http://localhost/conexiones?error=ya%20existe"
    assert r["reseteadoFuera"] == 0
