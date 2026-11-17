"""Ejecuta el JavaScript de la paleta de comandos.

Vive en `base.html`, así que si revienta al arrancar se lleva por delante el
atajo en TODAS las pantallas, sin ningún síntoma visible (regla dura 11).
"""

from __future__ import annotations

import pytest

from arnes_js import ejecutar, script_estatico


@pytest.fixture(scope="module")
def ejecucion(tmp_path_factory):
    return ejecutar(script_estatico("paleta.js"), tmp_path_factory.mktemp("js"))


def test_el_script_arranca_sin_reventar(ejecucion):
    assert ejecucion["errores"] == []


def test_registra_el_atajo_global_de_teclado(ejecucion):
    """Sin este oyente, Ctrl+K no hace nada y la paleta queda inalcanzable."""
    assert "window:keydown" in ejecucion["oyentes"]


def test_no_pide_nada_al_arrancar(ejecucion):
    """La paleta sólo consulta cuando se escribe: no cuesta nada estar ahí."""
    assert ejecucion["peticiones"] == []


def test_cubre_todas_las_secciones_de_la_navegacion():
    """Un atajo `g` que no llegue a una sección es peor que no tenerlo: se
    aprende el gesto y falla justo donde hace falta."""
    guion = script_estatico("paleta.js")
    for destino in ("/trabajo", "/inventario", "/respaldo", "/servicios",
                    "/conexiones", "/contexto"):
        assert f"'{destino}'" in guion


def test_no_roba_teclas_mientras_escribes(ejecucion):
    """En el terminal embebido, robar una tecla arruina el comando que ibas a
    lanzar — la peor forma posible de fallar aquí."""
    guion = script_estatico("paleta.js")
    assert ".xterm" in guion and "isContentEditable" in guion


# ── Lo que dice cuando no encuentra (C-0354) ─────────────────────────────────

# Las filas que pinta, con el texto de cada trozo: el arnés no guarda lo que se
# mete en un elemento, así que se anota aquí. Y el `button` lleva su etiqueta
# para poder pulsarlo.
_FILAS = r"""
const _crear = document.createElement;
document.createElement = (tag) => {
  const el = _crear(tag); el.tagName = String(tag).toUpperCase(); el.hijos = [];
  el.append = (...xs) => { el.hijos.push(...xs); };
  return el;
};
globalThis.FILAS = [];
nodo('paleta-res').appendChild = (li) => {
  FILAS.push(li);
  registro.valores.push('FILA:' + JSON.stringify({
    clase: li.className, textos: li.hijos.map((h) => h.textContent), boton: li.hijos.some((h) => h.tagName === 'BUTTON'),
  }));
};
"""

# El temporizador de 120 ms entre tecla y búsqueda, a cero: el arnés vuelca lo
# que pasó a los 20 ms y no vería la respuesta.
_TECLEAR = r"""
const _st = setTimeout;
globalThis.setTimeout = (fn, ms, ...r) => _st(fn, 0, ...r);
nodo('paleta-q').value = 'zzzxxyyqq';
nodo('paleta-q').disparar('input');
globalThis.setTimeout = _st;
"""

_SECRETARIO = r"""
window.HubSecretario = { preguntar: (t) => registro.valores.push('PREGUNTA:' + t) };
nodo('secretario-panel').getAttribute = (a) => (a === 'aria-label' ? 'Atenea' : null);
"""


def _filas(ejecucion):
    import json
    return [json.loads(v[5:]) for v in ejecucion["valores"] if isinstance(v, str) and v.startswith("FILA:")]


def test_sin_resultados_lo_dice_con_lo_que_se_busco(tmp_path):
    """Con «zzzxxyyqq» la lista quedaba vacía y sin texto: no se distinguía
    «no hay» de «aún busca» o «se ha roto»."""
    ejecucion = ejecutar(script_estatico("paleta.js"), tmp_path, respuestas={"/api/buscar": []},
                         previo=_FILAS, accion=_TECLEAR)

    assert ejecucion["errores"] == []
    (fila,) = _filas(ejecucion)
    assert fila["clase"] == "vacio" and "Nada con «zzzxxyyqq»" in " ".join(fila["textos"])
    assert fila["boton"] is False          # sin secretario, no se ofrece preguntarle


def test_con_el_secretario_ofrece_preguntarselo_y_al_pulsar_le_llega_lo_buscado(tmp_path):
    accion = _TECLEAR + r"""
      _st(() => {
        const boton = FILAS[0].hijos.find((h) => h.tagName === 'BUTTON');
        registro.valores.push('ROTULO:' + boton.textContent);
        boton.disparar('click');
        registro.valores.push('ABIERTA:' + nodo('paleta').open);
      }, 0);
    """
    ejecucion = ejecutar(script_estatico("paleta.js"), tmp_path, respuestas={"/api/buscar": []},
                         previo=_FILAS + _SECRETARIO + "nodo('paleta').open = true;", accion=accion)

    assert ejecucion["errores"] == []
    valores = ejecucion["valores"]
    assert "ROTULO:Preguntárselo a Atenea" in valores
    (pregunta,) = [v for v in valores if isinstance(v, str) and v.startswith("PREGUNTA:")]
    assert "zzzxxyyqq" in pregunta
    assert "ABIERTA:false" in valores     # la paleta se cierra para dejar ver su panel


def test_si_la_busqueda_falla_lo_dice_y_no_que_no_hay_nada(tmp_path):
    ejecucion = ejecutar(script_estatico("paleta.js"), tmp_path,
                         previo=_FILAS + _SECRETARIO + "fetch = () => Promise.reject(new Error('caído'));",
                         accion=_TECLEAR)

    assert ejecucion["errores"] == []
    (fila,) = _filas(ejecucion)
    texto = " ".join(fila["textos"])
    assert "No se pudo buscar" in texto and "Nada con" not in texto
    assert fila["boton"] is False


def test_con_resultados_no_pinta_la_fila_de_vacio(tmp_path):
    respuesta = [{"clase": "proyecto", "ref": "demo", "titulo": "Demo", "detalle": "", "url": "/proyecto/demo"}]
    ejecucion = ejecutar(script_estatico("paleta.js"), tmp_path, respuestas={"/api/buscar": respuesta},
                         previo=_FILAS, accion=_TECLEAR)

    assert [f["clase"] for f in _filas(ejecucion)] == ["marcado"]
