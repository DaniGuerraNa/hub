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
function elemento() {
  const el = {
    className: '', innerHTML: '', value: '', returnValue: '', _cierre: null,
    appendChild(){}, remove(){}, focus(){}, select(){},
    addEventListener(ev, fn){ if (ev === 'close') this._cierre = fn; },
    querySelector(){ return elemento(); },
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


def test_expone_las_tres_formas_de_preguntar(ejecucion):
    assert ejecucion["expuesto"] == ["avisar", "confirmar", "preguntar"]


def test_abre_un_dialogo_por_llamada(ejecucion):
    assert ejecucion["abiertos"] == 3


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
