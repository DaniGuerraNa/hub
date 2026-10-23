"""Crear proyecto y slot desde Trabajo, y retomar conversaciones, ejecutando el
JavaScript de verdad (regla dura 11). Vienen de la primera persona que usó el
hub sin que se lo enseñaran (22-oct)."""
from __future__ import annotations

from arnes_js import ejecutar, script_estatico

# Un botón con `data-*` y un `closest` que lo encuentra: así llega un clic.
CLIC = """
  const boton = Object.assign(nodo('boton'), { dataset: %s, textContent: 'Crear' });
  const ev = { target: { closest: (sel) => sel.includes(%r) ? boton : null },
               preventDefault(){} };
  (DOC_OYENTES.click || []).forEach(f => f(ev));
"""

# Un `document.createElement` que deja ver el formulario que se envía.
FORMULARIOS = """
  globalThis.ENVIADOS = [];
  document.createElement = (tipo) => {
    const el = { tipo, hijos: [], appendChild(h){ this.hijos.push(h); },
                 submit(){ ENVIADOS.push({ action: this.action,
                   campos: Object.fromEntries(this.hijos.map(h => [h.name, h.value])) }); } };
    return el;
  };
  document.body.appendChild = () => {};
"""


def test_slot_nuevo_explica_que_es_un_slot_y_envia_el_formulario(tmp_path):
    previo = FORMULARIOS + """
      nodo('proyectos-para-slot').textContent = '[["demo","Demo"],["otro","Otro"]]';
      HubUI.formulario = (o) => { globalThis.DIALOGO = o;
                                  return Promise.resolve({ nombre: 'Arreglar login', ruta: '' }); };
    """
    accion = CLIC % ("{ nuevoSlot: 'otro' }", "data-nuevo-slot") + """
      setTimeout(() => { registro.dialogo = DIALOGO.titulo + ' | ' + DIALOGO.nota;
                         registro.campos = DIALOGO.campos.map(c => c.nombre);
                         registro.formularios = ENVIADOS; }, 0);
    """
    r = ejecutar(script_estatico("slot-nuevo.js"), tmp_path, previo=previo, accion=accion)
    assert r["errores"] == []
    assert r["dialogo"].startswith("Slot nuevo en Otro")
    assert "línea de trabajo" in r["dialogo"]
    # Con el proyecto ya elegido no se pregunta otra vez.
    assert r["campos"] == ["nombre", "ruta"]
    [f] = r["formularios"]
    assert f["action"] == "/slot/nuevo"
    assert f["campos"]["proyecto_id"] == "otro" and f["campos"]["ir"] == "trabajo"
    assert f["campos"]["nombre"] == "Arreglar login"


def test_slot_nuevo_sin_proyecto_deja_elegirlo(tmp_path):
    previo = FORMULARIOS + """
      nodo('proyectos-para-slot').textContent = '[["demo","Demo"]]';
      HubUI.formulario = (o) => { globalThis.DIALOGO = o; return Promise.resolve(null); };
    """
    accion = CLIC % ("{ nuevoSlot: '' }", "data-nuevo-slot") + """
      setTimeout(() => { registro.campos = DIALOGO.campos.map(c => c.nombre);
                         registro.formularios = ENVIADOS; }, 0);
    """
    r = ejecutar(script_estatico("slot-nuevo.js"), tmp_path, previo=previo, accion=accion)
    assert r["errores"] == []
    assert r["campos"][0] == "proyecto_id"
    assert r["formularios"] == []   # cancelar no envía nada


def test_proyecto_nuevo_se_abre_con_cualquier_boton_marcado(tmp_path):
    """Antes sólo existía `#nuevo-proyecto`, en Panorama. Trabajo tiene el suyo."""
    previo = "HubUI.formulario = (o) => { registro.titulo = o.titulo; return Promise.resolve(null); };"
    accion = CLIC % ("{}", "data-nuevo-proyecto")
    r = ejecutar(script_estatico("proyecto-nuevo.js"), tmp_path, previo=previo, accion=accion)
    assert r["errores"] == []
    assert r["titulo"] == "Proyecto nuevo"


RESPUESTA = {"/conversaciones": {"conversaciones": [
    {"id": "11111111-1111-4111-8111-111111111111", "titulo": None, "primera": "arregla el <login>",
     "fin": "2026-10-22T10:00:00Z", "turnos": 3, "viva": False, "ventana": None},
    {"id": "22222222-2222-4222-8222-222222222222", "titulo": "Tests", "primera": "x",
     "fin": "2026-10-22T11:00:00Z", "turnos": 1, "viva": True,
     "ventana": {"session": "demo", "ventana": 2}},
]}}


def test_el_hueco_de_un_slot_vacio_pinta_sus_conversaciones(tmp_path):
    previo = """
      const [hueco] = document.querySelectorAll('[data-conversaciones]');
      hueco.dataset = { conversaciones: '5' };
      hueco.closest = () => null;   // no está dentro de un desplegable: se carga ya
      globalThis.HUECO = hueco;
    """
    accion = "registro.html = HUECO.innerHTML;"
    r = ejecutar(script_estatico("conversaciones.js"), tmp_path, respuestas=RESPUESTA,
                 previo=previo, accion=accion)
    assert r["errores"] == []
    assert "/api/slot/5/conversaciones" in r["peticiones"]
    html = r["html"]
    assert 'action="/slot/5/retomar"' in html and "Retomar" in html
    assert "arregla el &lt;login&gt;" in html          # escapado
    # La abierta no se retoma otra vez: se va a su ventana.
    assert "/trabajo?session=demo&ventana=2" in html and "abierta ahora" in html


def test_el_desplegable_no_pide_nada_hasta_que_se_abre(tmp_path):
    previo = """
      const [caja] = document.querySelectorAll('[data-conversaciones]');
      caja.dataset = { conversaciones: '5' };
      const menu = nodo('menu'); caja.closest = () => menu; globalThis.MENU = menu;
    """
    accion = """
      registro.antes = registro.peticiones.length;
      MENU.open = true; MENU.disparar('toggle');
    """
    r = ejecutar(script_estatico("conversaciones.js"), tmp_path, respuestas=RESPUESTA,
                 previo=previo, accion=accion)
    assert r["errores"] == []
    assert r["antes"] == 0
    assert "/api/slot/5/conversaciones" in r["peticiones"]
