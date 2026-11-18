"""`marco.js`, ejecutado (regla dura 11): «Más» se cierra con Escape y tocando
fuera, y la barra se pliega y se abre (C-0450).

«Más» es un `<details>` y se abre sin este script; lo que aquí se prueba es
lo único que añade. Y que al cargar no toca nada: la barra vive en una región
que `sin-recarga.js` compara con lo que manda el servidor.
"""

from __future__ import annotations

import pytest

from arnes_js import ejecutar, script_estatico

MARCO = script_estatico("marco.js")

# «Más» abierto, con su `summary`, y un registro de quién recibe el foco.
ABIERTO = """
  globalThis.mas = nodo('marco-mas');   // `previo` corre en su propio bloque
  mas.open = true;
  mas.querySelector('summary').focus = () => registro.valores.push('FOCO EN MAS');
"""

SUCESOS = """
  const tecla = (key) => { const e = { key, cancelado: false, preventDefault() { this.cancelado = true; } };
                           (DOC_OYENTES.keydown || []).forEach(f => f(e)); return e; };
  const clic = (dentro) => (DOC_OYENTES.click || []).forEach(f => f({ target: { closest: () => (dentro ? mas : null) } }));
"""


def _correr(tmp_path, accion: str, previo: str = ABIERTO) -> dict:
    r = ejecutar(MARCO, tmp_path, previo=previo, accion=SUCESOS + accion)
    assert not r["errores"], r["errores"]
    return r


def test_escape_cierra_mas_y_devuelve_el_foco_a_su_boton(tmp_path):
    r = _correr(tmp_path, "const e = tecla('Escape'); registro.valores.push(mas.open ? 'ABIERTO' : 'CERRADO', e.cancelado);")
    assert r["valores"] == ["FOCO EN MAS", "CERRADO", True]


def test_escape_con_mas_cerrado_no_se_come_la_tecla(tmp_path):
    """La paleta, los diálogos y la terminal también cierran con Escape."""
    accion = "mas.open = false; const e = tecla('Escape'); registro.valores.push(e.cancelado);"
    assert _correr(tmp_path, accion)["valores"] == [False]


def test_otra_tecla_no_la_cierra(tmp_path):
    r = _correr(tmp_path, "tecla('a'); registro.valores.push(mas.open ? 'ABIERTO' : 'CERRADO');")
    assert r["valores"] == ["ABIERTO"]


def test_tocar_fuera_la_cierra_y_tocar_dentro_no(tmp_path):
    accion = """
      clic(true);  registro.valores.push(mas.open ? 'ABIERTO' : 'CERRADO');
      clic(false); registro.valores.push(mas.open ? 'ABIERTO' : 'CERRADO');
    """
    assert _correr(tmp_path, accion)["valores"] == ["ABIERTO", "CERRADO"]


def test_al_cargar_no_toca_el_documento(tmp_path):
    """Sólo escucha: ni clases, ni atributos, ni peticiones."""
    r = ejecutar(MARCO, tmp_path)
    assert not r["errores"], r["errores"]
    assert sorted(r["oyentes"]) == ["document:click", "document:keydown"]
    assert not r["clases"] and not r["alternadas"] and not r["peticiones"] and not r["valores"]


# Una tira de teléfono que no cabe: 800 px de pantallas en 358 de ancho, y la
# de ahora al final, fuera de la vista.
TIRA = """
  const aqui = { getBoundingClientRect: () => ({ left: 616 - tira.scrollLeft, width: 120 }) };
  globalThis.tira = { scrollWidth: 800, clientWidth: 358, scrollLeft: 0,
                      getBoundingClientRect: () => ({ left: 16, width: 358 }),
                      querySelector: (s) => (s === '.aqui' ? aqui : null) };
  document.querySelector = (s) => (s === '.marco-tira' ? tira : null);
"""


def test_la_tira_del_telefono_llega_con_la_pantalla_de_ahora_a_la_vista(tmp_path):
    r = ejecutar(MARCO, tmp_path, previo=TIRA, accion="registro.valores.push(tira.scrollLeft);")
    assert not r["errores"], r["errores"]
    # Centrada: su medio (616 + 60) en el medio de la tira (16 + 179).
    assert r["valores"] == [481]


def test_una_tira_que_cabe_entera_no_se_mueve(tmp_path):
    previo = TIRA + "tira.scrollWidth = 358;"
    r = ejecutar(MARCO, tmp_path, previo=previo, accion="registro.valores.push(tira.scrollLeft);")
    assert not r["errores"] and r["valores"] == [0]


# ── Plegar la barra (C-0450) ─────────────────────────────────────────────────
#
# El menú y, en /trabajo, la lista de proyectos se pliegan juntos y por
# aparato (`hub.sinBarra`). El estado efectivo va en `<html data-barra>`
# —nunca dentro de la región `rail`, que `sin-recarga.js` sustituye—, y al
# cambiar se avisa con `hub:barra` para que /trabajo esconda su lista.

# Los dos botones del raíl, con su `data-marco-barra`; el documento los
# encuentra por él y anota a quién va el foco y qué eventos salen.
BARRA = """
  // Una ventana de PC: el arnés contesta «no» a toda consulta, y el marco
  // pregunta por `min-width: 861px`, la misma que enseña el botón de abrir.
  global.matchMedia = (q) => ({ matches: /min-width: 861px/.test(q), addEventListener(){} });
  for (const quien of ['plegar', 'abrir']) {
    nodo(quien).dataset = { marcoBarra: quien };
    nodo(quien).focus = () => registro.valores.push('FOCO EN ' + quien.toUpperCase());
  }
  document.querySelector = (s) => {
    const m = /^\\[data-marco-barra="(\\w+)"\\]$/.exec(s);
    return m ? nodo(m[1]) : null;
  };
  document.dispatchEvent = (e) => registro.valores.push(e.type + ':' + JSON.stringify(e.detail));
"""
ESTRECHA = "global.matchMedia = (q) => ({ matches: /max-width: 860px/.test(q), addEventListener(){} });"

PULSAR = """
  const pulsar = (quien) => (DOC_OYENTES.click || []).forEach(f => f({
    target: { closest: (s) => (s === '[data-marco-barra]' ? nodo(quien) : null) } }));
  const html = document.documentElement;
  const efectivo = () => html.dataset.barra || 'SIN ATRIBUTO';
"""


def _barra(tmp_path, accion: str, previo: str = "") -> dict:
    r = ejecutar(MARCO, tmp_path, previo=BARRA + previo,
                 accion=PULSAR + accion + "registro.valores.push('GUARDADO:' + localStorage.getItem('hub.sinBarra'));")
    assert not r["errores"], r["errores"]
    return r


def test_plegar_guarda_la_barra_la_pone_en_html_avisa_y_deja_el_foco_en_abrir(tmp_path):
    r = _barra(tmp_path, "pulsar('plegar'); registro.valores.push(efectivo());")
    assert r["valores"] == ['hub:barra:{"plegada":true}', "FOCO EN ABRIR", "plegada", "GUARDADO:true"]


def test_abrir_la_quita_avisa_y_devuelve_el_foco_a_plegar(tmp_path):
    previo = "localStorage.setItem('hub.sinBarra', 'true'); document.documentElement.dataset.barra = 'plegada';"
    r = _barra(tmp_path, "pulsar('abrir'); registro.valores.push(efectivo());", previo)
    assert r["valores"] == ['hub:barra:{"plegada":false}', "FOCO EN PLEGAR", "SIN ATRIBUTO", "GUARDADO:false"]


def test_hubmarco_dice_el_estado_efectivo_y_lo_cambia(tmp_path):
    accion = """
      const b = window.HubMarco.barra;
      registro.valores.push(b.plegada()); b.poner(true); registro.valores.push(b.plegada());
      b.poner(true);       // ya lo estaba: ni otro aviso ni otro guardado distinto
      b.poner(false); registro.valores.push(b.plegada());
    """
    r = _barra(tmp_path, accion)
    assert r["valores"] == [False, 'hub:barra:{"plegada":true}', True,
                            'hub:barra:{"plegada":false}', False, "GUARDADO:false"]


def test_por_debajo_de_861_px_se_guarda_pero_no_se_pliega_ni_se_avisa(tmp_path):
    """En el teléfono el menú es la barra de abajo y la lista, el `select`."""
    r = _barra(tmp_path, "window.HubMarco.barra.poner(true); registro.valores.push(efectivo());", ESTRECHA)
    assert r["valores"] == ["SIN ATRIBUTO", "GUARDADO:true"]


def test_al_cruzar_los_861_px_se_aplica_lo_guardado_y_se_retira(tmp_path):
    previo = """
      localStorage.setItem('hub.sinBarra', 'true');
      globalThis.ANCHA = false;
      global.matchMedia = (q) => ({ get matches() { return /min-width: 861px/.test(q) ? ANCHA : (/max-width: 860px/.test(q) && !ANCHA); },
                                    addEventListener(ev, f) { if (ev === 'change') globalThis.AL_CAMBIAR = f; } });
    """
    accion = """
      registro.valores.push(efectivo());
      ANCHA = true;  AL_CAMBIAR({}); registro.valores.push(efectivo());
      ANCHA = false; AL_CAMBIAR({}); registro.valores.push(efectivo());
    """
    r = _barra(tmp_path, accion, previo)
    assert r["valores"] == ["SIN ATRIBUTO", 'hub:barra:{"plegada":true}', "plegada",
                            'hub:barra:{"plegada":false}', "SIN ATRIBUTO", "GUARDADO:true"]


def test_sin_localstorage_no_revienta_y_vale_para_esta_pagina(tmp_path):
    """Una ventana privada o los datos del sitio bloqueados: no se recuerda,
    pero el botón hace lo que dice."""
    previo = ("global.localStorage = { getItem() { throw new Error('bloqueado'); },"
              " setItem() { throw new Error('bloqueado'); } };")
    r = ejecutar(MARCO, tmp_path, previo=BARRA + previo,
                 accion=PULSAR + "pulsar('plegar'); registro.valores.push(efectivo());")
    assert not r["errores"], r["errores"]
    assert r["valores"] == ['hub:barra:{"plegada":true}', "FOCO EN ABRIR", "plegada"]


def test_un_clic_fuera_de_los_botones_no_toca_la_barra(tmp_path):
    r = _barra(tmp_path, """
      (DOC_OYENTES.click || []).forEach(f => f({ target: { closest: () => null } }));
      registro.valores.push(efectivo());""")
    assert r["valores"] == ["SIN ATRIBUTO", "GUARDADO:null"]


def _antes_de_pintar(guardado: str | None, estrecha: bool, falla: bool = False) -> dict:
    """El guion que pone `data-barra` antes del primer pintado, sacado de la
    base nueva tal como se sirve y ejecutado en node."""
    import json
    import re
    import shutil
    import subprocess

    from hub import interfaz, web
    if not interfaz.disponible():
        pytest.skip("esta instalación no trae la interfaz nueva")
    node = shutil.which("node")
    if not node:
        pytest.skip("node no disponible")
    html = web._PLANTILLAS[interfaz.NUEVA].get_template("base.html").render(titulo="x")
    (guion,) = [g for g in re.findall(r"<script data-antes-de-pintar>(.*?)</script>", html, re.S)
                if "hub.sinBarra" in g]
    programa = f"""
      const raiz = {{ dataset: {{}} }};
      global.document = {{ documentElement: raiz }};
      global.localStorage = {{ getItem: (k) => {{ if ({json.dumps(falla)}) throw new Error('bloqueado');
                                                  return k === 'hub.sinBarra' ? {json.dumps(guardado)} : null; }} }};
      global.matchMedia = (q) => ({{ matches: /min-width: 861px/.test(q) ? !{json.dumps(estrecha)} : (/max-width: 860px/.test(q) && {json.dumps(estrecha)}) }});
    """ + guion + "\nconsole.log(JSON.stringify(raiz.dataset));"
    salida = subprocess.run([node, "-e", programa], capture_output=True, text=True, timeout=20)
    assert salida.returncode == 0, salida.stderr
    return json.loads(salida.stdout)


def test_antes_de_pintar_la_barra_sale_ya_plegada_si_se_dejo_asi():
    """Si la plegara `marco.js`, al final de la página, se vería el menú
    entero un instante y luego encogerse, y en /trabajo la terminal se
    ajustaría dos veces."""
    assert _antes_de_pintar("true", estrecha=False) == {"barra": "plegada"}
    assert _antes_de_pintar("false", estrecha=False) == {}
    assert _antes_de_pintar(None, estrecha=False) == {}
    assert _antes_de_pintar("true", estrecha=True) == {}
    assert _antes_de_pintar("true", estrecha=False, falla=True) == {}


def test_el_guion_de_antes_de_pintar_va_delante_del_rail_y_fuera_de_su_region():
    from hub import interfaz, web
    if not interfaz.disponible():
        pytest.skip("esta instalación no trae la interfaz nueva")
    html = web._PLANTILLAS[interfaz.NUEVA].get_template("base.html").render(titulo="x")
    assert html.index("hub.sinBarra") < html.index('<nav class="rail-global" data-region="rail"')
