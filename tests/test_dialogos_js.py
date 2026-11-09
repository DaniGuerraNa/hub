"""Los diálogos de `static/hub-ui.js`, ejecutados de verdad en node.

Sustituyen a alert/confirm/prompt del navegador. Como son promesas, un fallo al
resolverlas deja la UI colgada sin ningún síntoma visible — de ahí que se
ejecuten en el test en lugar de sólo leerlos.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

GUION = Path(__file__).resolve().parents[1] / "src" / "hub" / "static" / "hub-ui.js"

ARNES = r"""
// Lo que "hay escrito" en cada campo cuando se cierra el diálogo. `formulario`
// lee los campos por `[name=…]`, así que sin esto todos valdrían lo mismo y el
// test no distinguiría recoger bien de recoger cualquier cosa.
const valores = {};

function elemento() {
  const el = {
    className: '', innerHTML: '', value: '', returnValue: '', _cierre: null,
    appendChild(){}, remove(){}, focus(){}, select(){},
    addEventListener(ev, fn){ if (ev === 'close') this._cierre = fn; },
    querySelector(sel){
      const hijo = elemento();
      const m = /\[name="([^"]+)"\]/.exec(sel || '');
      if (m && valores[m[1]] !== undefined) hijo.value = valores[m[1]];
      return hijo;
    },
    showModal(){ registro.abiertos++; },
  };
  return el;
}

const registro = { abiertos: 0, expuesto: [], resultados: {} };
let ultimo = null;

global.window = {};
// `hub-ui.js` no es sólo los diálogos: también lleva el comportamiento común de
// los menús, los nombres editables y los selectores con búsqueda, que se
// enganchan al cargar. Este arnés tiene que sostener eso aunque no lo pruebe,
// o el fichero entero deja de poder ejecutarse aquí.
global.document = {
  createElement(){ ultimo = elemento(); return ultimo; },
  body: { appendChild(){}, classList: { add(){}, remove(){} } },
  addEventListener(){},
  querySelector(){ return null; },
  querySelectorAll(){ return []; },
};

require(GUION_RUTA);

registro.expuesto = Object.keys(window.HubUI).sort();

(async () => {
  // Confirmar: el usuario cancela.
  const p1 = window.HubUI.confirmar({ titulo: 't', mensaje: 'm' });
  ultimo.returnValue = 'no'; ultimo._cierre();
  registro.resultados.cancelado = await p1;

  // Confirmar: el usuario acepta.
  const p2 = window.HubUI.confirmar({ titulo: 't', mensaje: 'm', peligro: true });
  ultimo.returnValue = 'si'; ultimo._cierre();
  registro.resultados.aceptado = await p2;

  // Preguntar: se cierra sin aceptar.
  const p3 = window.HubUI.preguntar({ titulo: 't', etiqueta: 'e', valor: 'v' });
  registro.htmlPreguntar = ultimo.innerHTML;
  ultimo.returnValue = 'no'; ultimo._cierre();
  registro.resultados.sinDato = await p3;

  // Preguntar con el dato obligatorio (C-0230).
  const p3b = window.HubUI.preguntar({ titulo: 't', etiqueta: 'Por qué', obligatorio: true });
  registro.htmlObligatorio = ultimo.innerHTML;
  ultimo.returnValue = 'no'; ultimo._cierre();
  await p3b;

  const CAMPOS = [
    { nombre: 'id', etiqueta: 'Identificador', requerido: true },
    { nombre: 'ruta', etiqueta: 'Carpeta', requerido: true },
    { nombre: 'guardrail', etiqueta: 'Permiso', valor: 'ask',
      opciones: [['ask', 'Preguntar'], ['never', 'Nunca']] },
  ];

  // Formulario: se cancela. Tiene que dar null y NO un objeto con los campos a
  // medio escribir, que es lo que se enviaría al servidor sin darse cuenta.
  const p4 = window.HubUI.formulario({ titulo: 't', campos: CAMPOS });
  valores.id = 'mi-kit'; valores.ruta = '/tmp/x'; valores.guardrail = 'ask';
  ultimo.returnValue = 'no'; ultimo._cierre();
  registro.resultados.formCancelado = await p4;

  // Formulario: se acepta. Se recogen los tres campos, con los espacios fuera.
  const p5 = window.HubUI.formulario({ titulo: 't', campos: CAMPOS });
  valores.id = '  mi-kit  '; valores.ruta = '/tmp/x'; valores.guardrail = 'never';
  ultimo.returnValue = 'si'; ultimo._cierre();
  registro.resultados.formAceptado = await p5;

  // El HTML que pinta: el select con su opción marcada, y `required` sólo donde
  // se pidió. Se mira el innerHTML porque es lo único que el navegador valida.
  registro.html = ultimo.innerHTML;

  console.log(JSON.stringify(registro));
})();
"""


@pytest.fixture(scope="module")
def ejecucion(tmp_path_factory):
    node = shutil.which("node")
    if not node:
        pytest.skip("node no disponible")
    archivo = tmp_path_factory.mktemp("js") / "arnes.js"
    archivo.write_text(
        ARNES.replace("GUION_RUTA", json.dumps(str(GUION))), encoding="utf-8"
    )
    salida = subprocess.run([node, str(archivo)], capture_output=True, text=True, timeout=30)
    assert salida.returncode == 0, salida.stderr
    return json.loads(salida.stdout.strip().splitlines()[-1])


def test_expone_las_cuatro_formas_de_preguntar(ejecucion):
    assert ejecucion["expuesto"] == ["avisar", "confirmar", "formulario", "preguntar"]


def test_nadie_le_pasa_una_cadena_suelta_a_avisar():
    """`avisar` recibe `{ titulo, mensaje }` y los saca por nombre: con una
    cadena, el diálogo sale vacío, sólo con «Entendido», y nada lo dice. Pasó
    en `lienzos.js` al fallar «Archivar» (C-0182). Esto mira también las
    plantillas, cuyos scripts en línea no ejecuta ningún test entero."""
    import re
    raiz = GUION.parents[1]
    llamada = re.compile(r"HubUI\.avisar\(\s*['\"`]")
    culpables = [
        f"{f.relative_to(raiz)}:{n}"
        for f in sorted([*raiz.glob("static/*.js"), *raiz.glob("templates/*.html")])
        for n, linea in enumerate(f.read_text(encoding="utf-8").splitlines(), 1)
        if llamada.search(linea)
    ]
    assert not culpables, f"HubUI.avisar con una cadena (sale vacío): {culpables}"


def test_abre_un_dialogo_por_llamada(ejecucion):
    assert ejecucion["abiertos"] == 6


def test_el_formulario_cancelado_no_devuelve_datos_a_medias(ejecucion):
    """🔴 Devolver el objeto igualmente sería peor que fallar: quien llama hace
    `if (!datos) return`, y un objeto con los campos a medio escribir pasa esa
    guarda y se manda al servidor como si el usuario lo hubiera aceptado."""
    assert ejecucion["resultados"]["formCancelado"] is None


def test_el_formulario_recoge_cada_campo_por_su_nombre(ejecucion):
    """Y con los espacios fuera: una ruta con un espacio al final, pegada del
    explorador, es una carpeta distinta para el sistema de archivos."""
    assert ejecucion["resultados"]["formAceptado"] == {
        "id": "mi-kit", "ruta": "/tmp/x", "guardrail": "never",
    }


def test_el_select_marca_la_opcion_por_defecto(ejecucion):
    assert '<option value="ask" selected>' in ejecucion["html"]


def test_solo_lleva_required_lo_que_se_declaro_obligatorio(ejecucion):
    """El control negativo del formulario. Ponerlo en todos sería cómodo y
    dejaría al usuario sin poder aceptar hasta rellenar campos que tienen
    valor por defecto."""
    html = ejecucion["html"]
    assert html.count("required") == 2          # id y ruta, no guardrail
    assert 'name="guardrail"' in html and "<select" in html


def test_confirmar_distingue_aceptar_de_cancelar(ejecucion):
    assert ejecucion["resultados"]["cancelado"] is False
    assert ejecucion["resultados"]["aceptado"] is True


def test_preguntar_devuelve_nulo_si_no_se_acepta(ejecucion):
    assert ejecucion["resultados"]["sinDato"] is None


def test_el_contenido_va_escapado():
    """El nombre de una ventana entra en el HTML del diálogo: no puede inyectar."""
    fuente = GUION.read_text(encoding="utf-8")
    assert "escapar(titulo)" in fuente and "escapar(mensaje)" in fuente


# ── acciones que destruyen algo irrecuperable ────────────────────────────────


def _ficha_con_un_slot_con_nota_y_otro_sin():
    """La ficha de un proyecto servida de verdad, con los dos casos."""
    from fastapi.testclient import TestClient

    from hub import db, slots, web
    con = db.abrir()
    try:
        con.execute("INSERT INTO proyecto (id, nombre, asiento) VALUES ('demo','Demo','/tmp/demo')")
        slots.crear(con, "demo", "con-nota", nota="lo que no se reconstruye")
        slots.crear(con, "demo", "sin-nota")
    finally:
        con.close()
    return TestClient(web.app).get("/proyecto/demo").text


def _botones_de(html: str, slot: str) -> dict:
    """El formulario de estado de la tarjeta de ese slot y sus botones."""
    i = html.index(f'<span class="etiqueta">{slot} ')
    m = re.search(r'(<form\b[^>]*/estado"[^>]*>)(.*?)</form>', html[i:], re.S)
    botones = re.findall(r'<button\b[^>]*>', m.group(2), re.S)
    return {"form": m.group(1),
            "borrar": next(b for b in botones if 'value="borrar"' in b),
            "archivar": next(b for b in botones if 'value="archivar"' in b)}


def test_borrar_un_slot_pregunta_por_la_puerta_comun_y_dice_si_se_lleva_su_nota():
    """🔴 Era un submit normal: un clic y la nota no volvía.

    Un slot borrado se lleva SU NOTA, que es lo único del hub que no se
    reconstruye escaneando — por eso `desinstalar.sh` no borra `HUB_HOME` sin
    que se lo pidas, y por eso `06-problemas.md` avisa de lo mismo al hablar de
    la base. C-0233: la pregunta va en el botón (decisión 397) y la hace
    `hub-ui.js`, que reenvía con ese mismo botón y su `accion=borrar`; antes
    la hacía un `click` propio de esta pantalla, aparte de la puerta común.
    """
    html = _ficha_con_un_slot_con_nota_y_otro_sin()
    con_nota = _botones_de(html, "con-nota")
    sin_nota = _botones_de(html, "sin-nota")

    for nombre, b in (("con-nota", con_nota), ("sin-nota", sin_nota)):
        assert 'name="accion"' in b["borrar"]
        assert f'data-confirmar-titulo="Borrar el slot «{nombre}»"' in b["borrar"]
        assert 'data-confirmar-ok="Borrar el slot"' in b["borrar"]
        # Y que diga qué hacer en vez de borrar: «¿seguro?» no informa de nada.
        assert "«Archivar» lo conserva" in b["borrar"]
        # Archivar y desarchivar no preguntan: la pregunta no va en el formulario.
        assert "data-confirmar" not in b["archivar"] and "data-confirmar" not in b["form"]
    assert "Se borra también su NOTA" in con_nota["borrar"]
    assert "NOTA" not in sin_nota["borrar"]


def test_borrar_un_slot_ya_no_pregunta_con_un_click_propio():
    """Dos sitios que preguntan lo mismo divergen: el `click` de esta
    pantalla era el camino duplicado que señalaba `MAPA.md` (decisión 397)."""
    plantilla = (
        Path(__file__).resolve().parents[1]
        / "src" / "hub" / "templates" / "proyecto.html"
    ).read_text(encoding="utf-8")
    assert "data-borrar-slot" not in plantilla
    assert "data-tiene-nota" not in plantilla
    assert "requestSubmit(boton)" not in plantilla


# ── confirmación para formularios normales ────────────────────────────────────

def test_un_formulario_con_data_confirmar_pregunta_antes_de_enviar():
    """Las acciones destructivas estaban repartidas: las de JavaScript
    preguntaban con `HubUI.confirmar` y los formularios normales no preguntaban
    nada. Cerrar una ventana desde el raíl es un formulario, y mata lo que corra
    dentro."""
    guion = GUION.read_text("utf-8")
    # En el formulario, o en el botón que se pulsó (C-0229).
    assert "boton.dataset.confirmar ? boton.dataset : form.dataset" in guion
    assert "pide.confirmar" in guion
    # Delegado en `document`: hay listas que se repintan y un enganche por nodo
    # se pierde en el primer repintado.
    assert "document.addEventListener('submit'" in guion
    # Y la marca que evita volver a entrar con el envío de verdad.
    assert "form.dataset.confirmado" in guion


def test_la_confirmacion_de_formularios_no_cuelga_de_HubUI():
    """`HubUI` es el contrato de «las tres formas de preguntar» y hay un test
    que lo afirma entero. Esto es comportamiento, como los combos."""
    guion = GUION.read_text("utf-8")
    i = guion.index("document.addEventListener('submit'")
    assert "HubUI.confirmar" in guion[i:i + 800]
    assert "HubUI.confirmarFormulario" not in guion


ARNES_UNA_VEZ = r"""
const oyentes = [];
global.window = {};
global.document = {
  createElement(){ return { appendChild(){}, addEventListener(){} }; },
  body: { appendChild(){}, classList: { add(){}, remove(){} } },
  addEventListener(ev, fn){ if (ev === 'submit') oyentes.push(fn); },
  querySelector(){ return null; },
  querySelectorAll(){ return []; },
};
require(GUION_RUTA);

function formulario(dataset) {
  const boton = { tagName: 'BUTTON', disabled: false, textContent: 'Lanzar' };
  return { boton, form: { dataset, querySelectorAll(){ return [boton]; } } };
}
function enviar(form, prevenido) {
  const e = { target: form, defaultPrevented: !!prevenido, preventDefault(){ this.defaultPrevented = true; } };
  for (const fn of oyentes) fn(e);
}
const a = formulario({ unaVez: 'Abriendo…' }); enviar(a.form);
const b = formulario({}); enviar(b.form);
const c = formulario({ unaVez: 'Abriendo…' }); enviar(c.form, true);
console.log(JSON.stringify({ a: a.boton, b: b.boton, c: c.boton }));
"""


def test_un_formulario_de_una_vez_apaga_su_boton_al_enviarse(tmp_path):
    """«Lanzar» abre una ventana por pulsación (21-oct): el segundo clic no
    puede llegar. Y si la confirmación detuvo el envío, no se apaga nada."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node no disponible")
    archivo = tmp_path / "una-vez.js"
    archivo.write_text(ARNES_UNA_VEZ.replace("GUION_RUTA", json.dumps(str(GUION))), encoding="utf-8")
    salida = subprocess.run([node, str(archivo)], capture_output=True, text=True, timeout=30)
    assert salida.returncode == 0, salida.stderr
    r = json.loads(salida.stdout.strip().splitlines()[-1])

    assert r["a"] == {"tagName": "BUTTON", "disabled": True, "textContent": "Abriendo…"}
    assert r["b"]["disabled"] is False
    assert r["c"]["disabled"] is False


ARNES_CONFIRMAR = r"""
const oyentes = [];
global.window = global;
global.document = {
  createElement(){ return { appendChild(){}, addEventListener(){} }; },
  body: { appendChild(){}, classList: { add(){}, remove(){} } },
  addEventListener(ev, fn){ if (ev === 'submit') oyentes.push(fn); },
  querySelector(){ return null; },
  querySelectorAll(){ return []; },
};
require(GUION_RUTA);
HubUI.confirmar = () => Promise.resolve(RESPUESTA);

const registro = { eventos: [], pedidos: [], submitNativo: 0 };
const boton = { tagName: 'BUTTON', disabled: false, textContent: 'Borrar', name: 'accion', value: 'borrar' };
const otro = { tagName: 'BUTTON', disabled: false, textContent: 'Guardar', dataset: {} };
const form = {
  dataset: { confirmar: 'Se borra.' },
  querySelectorAll(){ return [boton]; },
  // El navegador: `requestSubmit` vuelve a disparar el evento `submit`, con el
  // botón como `submitter`; `submit()` no dispara nada.
  requestSubmit(b) { registro.pedidos.push(b === boton ? 'con-boton' : String(b));
                     enviar(b); },
  submit() { registro.submitNativo++; },
};
boton.form = form;
otro.form = form;
EN_EL_BOTON
function enviar(submitter) {
  const e = { target: form, submitter, defaultPrevented: false,
              preventDefault(){ this.defaultPrevented = true; } };
  for (const fn of oyentes) fn(e);
  registro.eventos.push(e.defaultPrevented ? 'parado' : 'pasa');
}
enviar(PRIMERO);
setTimeout(() => {
  registro.marca = form.dataset.confirmado || null;
  // Una segunda vez, con el formulario aún en la página (sin recargar):
  // tiene que volver a preguntar.
  enviar(boton);
  setTimeout(() => console.log(JSON.stringify(registro)), 10);
}, 10);
"""


def _confirmar(tmp_path, respuesta: bool, en_el_boton: bool = False, primero: str = "boton") -> dict:
    node = shutil.which("node")
    if not node:
        pytest.skip("node no disponible")
    archivo = tmp_path / "confirmar.js"
    en_boton = ("delete form.dataset.confirmar; boton.dataset = { confirmar: 'Se borra.' };"
                if en_el_boton else "")
    archivo.write_text(ARNES_CONFIRMAR.replace("GUION_RUTA", json.dumps(str(GUION)))
                       .replace("RESPUESTA", "true" if respuesta else "false")
                       .replace("EN_EL_BOTON", en_boton).replace("PRIMERO", primero), encoding="utf-8")
    salida = subprocess.run([node, str(archivo)], capture_output=True, text=True, timeout=30)
    assert salida.returncode == 0, salida.stderr
    return json.loads(salida.stdout.strip().splitlines()[-1])


def test_confirmar_reenvia_con_requestsubmit_y_el_boton_pulsado(tmp_path):
    """C-0167: `form.submit()` no dispara `submit` —ningún interceptor veía los
    «Borrar»— y perdía el `name=value` del botón. Ahora el envío de verdad sale
    con `requestSubmit(botón)` y pasa sin volver a preguntar."""
    r = _confirmar(tmp_path, True)

    assert r["pedidos"][0] == "con-boton"
    assert r["submitNativo"] == 0
    # El primero lo para la pregunta; el que sale de `requestSubmit`, pasa.
    assert r["eventos"][:2] == ["parado", "pasa"]


def test_confirmado_no_deja_la_marca_puesta_para_la_siguiente_vez(tmp_path):
    """Sin recargar, el formulario sigue ahí: con la marca puesta, el segundo
    «Borrar» se iría sin preguntar."""
    r = _confirmar(tmp_path, True)

    assert r["marca"] is None
    assert r["pedidos"] == ["con-boton", "con-boton"]


def test_si_se_cancela_no_se_envia_nada(tmp_path):
    r = _confirmar(tmp_path, False)

    assert r["pedidos"] == []
    assert r["submitNativo"] == 0


def test_la_pregunta_puede_ir_en_el_boton_y_solo_pregunta_ese(tmp_path):
    """C-0229: una nota del secretario tiene «Guardar» y «Borrar» en el mismo
    formulario, y borrar no preguntaba (la memoria no se reconstruye). Con la
    pregunta en el botón, «Borrar» pregunta y «Guardar» pasa."""
    r = _confirmar(tmp_path, True, en_el_boton=True)
    assert r["eventos"][:2] == ["parado", "pasa"] and r["pedidos"][0] == "con-boton"

    # «Guardar» sale sin pregunta; el único reenvío es el del «Borrar» de después.
    r = _confirmar(tmp_path, True, en_el_boton=True, primero="otro")
    assert r["eventos"][0] == "pasa" and r["pedidos"] == ["con-boton"]


def test_preguntar_con_el_dato_obligatorio_no_deja_aceptar_vacio_y_si_cancelar(ejecucion):
    """C-0230: vacío daba `null`, igual que cancelar, y «Descartar» en el
    Tablero se cerraba sin hacer nada ni decir por qué. Lo valida el
    navegador, como en `formulario`; Cancelar no valida."""
    html = ejecucion["htmlObligatorio"]
    assert " required" in html and 'pattern=".*\\S.*"' in html
    assert 'value="no" class="declinar" formnovalidate' in html
    assert " required" not in ejecucion["htmlPreguntar"]


def test_descartar_una_idea_exige_el_motivo():
    plantilla = (Path(__file__).parents[1] / "src/hub/templates/tablero.html").read_text("utf-8")
    i = plantilla.index("titulo: 'Descartar la idea #'")
    assert "obligatorio: true" in plantilla[i:i + 300]
