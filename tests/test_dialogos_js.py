"""Los diálogos de `static/hub-ui.js`, ejecutados de verdad en node.

Sustituyen a alert/confirm/prompt del navegador. Como son promesas, un fallo al
resolverlas deja la UI colgada sin ningún síntoma visible — de ahí que se
ejecuten en el test en lugar de sólo leerlos.
"""

from __future__ import annotations

import json
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
  ultimo.returnValue = 'no'; ultimo._cierre();
  registro.resultados.sinDato = await p3;

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


def test_abre_un_dialogo_por_llamada(ejecucion):
    assert ejecucion["abiertos"] == 5


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


def test_borrar_un_slot_pide_confirmacion():
    """🔴 Era un submit normal: un clic y la nota no volvía.

    Un slot borrado se lleva SU NOTA, que es lo único del hub que no se
    reconstruye escaneando — por eso `desinstalar.sh` no borra `HUB_HOME` sin
    que se lo pidas, y por eso `06-problemas.md` avisa de lo mismo al hablar de
    la base. El botón que las borraba de una en una no avisaba de nada.
    """
    plantilla = (
        Path(__file__).resolve().parents[1]
        / "src" / "hub" / "templates" / "proyecto.html"
    ).read_text(encoding="utf-8")

    assert 'value="borrar"' in plantilla
    assert "data-borrar-slot" in plantilla, "el botón vuelve a ser un submit pelado"
    assert "HubUI.confirmar" in plantilla
    # Y que diga qué se lleva: «¿seguro?» no informa de nada.
    assert "NOTA" in plantilla and "Archivar" in plantilla


def test_el_boton_se_envia_a_si_mismo():
    """`form.submit()` a secas pierde el `name`/`value` del botón.

    El servidor recibiría el formulario sin `accion=borrar` y no haría nada, o
    peor, haría otra cosa. Se usa `requestSubmit(boton)`.
    """
    plantilla = (
        Path(__file__).resolve().parents[1]
        / "src" / "hub" / "templates" / "proyecto.html"
    ).read_text(encoding="utf-8")
    assert "requestSubmit(boton)" in plantilla
