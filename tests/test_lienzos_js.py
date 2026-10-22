"""El panel de lienzos, ejecutando su JavaScript de verdad (regla dura 11).

Lo que se prueba aquí no se ve sirviendo la página: el HTML sale perfecto y
quien se equivoca es el navegador. Y el riesgo concreto de este script es que
**reescribe el archivo del lienzo** al marcar una decisión: si toca una línea de
más, corrompe algo que el usuario había editado a mano.

Vive en /trabajo, así que un fallo al arrancar se lleva la terminal por delante
sin ningún síntoma.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

GUION = Path(__file__).resolve().parents[1] / "src" / "hub" / "static" / "lienzos.js"

CUERPO = """puntos:
  - id: n1
    punto: "contador en memoria"
    justificacion: "dos procesos dan el mismo numero"
    decision: pendiente
  - id: n2
    punto: "el IVA en tres sitios"
    decision: si
  - id: n3
    punto: "sin indice en cliente_id"
    decision: pendiente
inventado_por_una_plantilla_futura: 42
"""

ARNES = r"""
// ── DOM mínimo, sólo lo que el script toca ─────────────────────────────────
const nodos = {};
function nuevo(id) {
  const n = {
    id, value: '', innerHTML: '', hidden: false, dataset: {},
    classList: { _s: new Set(),
      add(c){this._s.add(c)}, remove(c){this._s.delete(c)},
      contains(c){return this._s.has(c)},
      toggle(c, f){ const v = f === undefined ? !this._s.has(c) : f;
                    v ? this._s.add(c) : this._s.delete(c); return v; } },
    _oyentes: {},
    addEventListener(ev, fn){ (this._oyentes[ev] ||= []).push(fn); },
    disparar(ev, arg){ (this._oyentes[ev] || []).forEach(f => f(arg || {preventDefault(){}})); },
    // 🔴 Delega en las MISMAS funciones que `document`. El script llama a
    // `vista.querySelectorAll('.dec')` para atar los botones, y si esto
    // devolviera otra lista —o una vacía— los clics del test caerían sobre
    // objetos que nadie escucha, y el test pasaría por no hacer nada.
    querySelectorAll(sel){
      if (sel === '.lienzo-item') return itemsDe(this);
      if (sel === '.dec') return decsDe(this);
      if (sel === '.arch') return archsDe(this);
      if (sel === '.dbb button') return this._hijos || [];
      if (sel === '.dresp') return respDe(this);
      return (this._hijos || []).filter(h => h._sel === sel);
    },
    querySelector(sel){
      // 🔴 Los dos caminos —desde el `.dec` y desde la vista— tienen que dar el
      // MISMO nodo, como en el navegador. Si no, el script ata el oyente a uno
      // y el test dispara el evento en otro, y el test pasa por no hacer nada.
      if (sel === '.dresp') return respDe(this);
      if (sel === '.dresp-estado') return (this._estado ||= nuevo('estado-' + this.id));
      return this.querySelectorAll(sel)[0] || null;
    },
  };
  return (nodos[id] = n);
}

// La ventana visible: de aquí sale el proyecto.
const ventana = nuevo('ventana');
ventana.dataset.proyecto = 'pedidos';

const REG = { guardados: [], peticiones: [], archivados: [], abiertos: [] };

global.document = {
  getElementById: (id) => nodos[id] || null,
  // `SIN_VENTANA` simula un slot recién creado que todavía no tiene ninguna
  // ventana abierta: entonces ese bloque no existe en el DOM.
  querySelector: (sel) => (sel === '.por-ventana.viendo' && !global.SIN_VENTANA)
    ? ventana : null,
  querySelectorAll: (sel) => {
    if (sel === '.pest-lado button[data-hoja]') return [nodos['pest-lienzos']];
    if (sel === '.hoja') return [];
    // `.lienzo-item` y `.dec` se resuelven contra lo que el script pintó: se
    // reconstruyen desde el innerHTML para poder pulsar de verdad.
    if (sel === '.lienzo-item') return itemsDe(nodos['lienzos-lista']);
    if (sel === '.dec') return decsDe(nodos['lienzos-vista']);
    if (sel === '.arch') return archsDe(nodos['lienzos-lista']);
    return [];
  },
};
global.window = { addEventListener(){} };
global.HubUI = { avisar(x){ REG.aviso = x; } };
global.setInterval = () => 0;
global.clearInterval = () => {};

// Reconstruye nodos pulsables a partir del HTML pintado. No es un navegador,
// pero recorre el MISMO camino: leer data-id y llamar al manejador.
// 🔴 Se CACHEA por contenido pintado. Sin la caché, cada llamada fabricaba
// nodos nuevos: el script ataba los oyentes a unos y el test pulsaba otros, y
// el clic no llegaba a ninguna parte — con el test pasando por no hacer nada.
const cache = {};
function reconstruir(caja, marca, patron, fabricar) {
  const clave = marca + '|' + String(caja.innerHTML);
  if (cache[clave]) return cache[clave];
  const salida = [];
  for (const m of String(caja.innerHTML).matchAll(patron)) salida.push(fabricar(m));
  return (cache[clave] = salida);
}

function itemsDe(caja) {
  return reconstruir(caja, 'item', /data-id="([^"]+)"\s+data-proyecto="([^"]+)"/g, m => {
    const it = nuevo('item-' + m[1]);
    it.dataset.id = m[1]; it.dataset.proyecto = m[2];
    return it;
  });
}

// Siempre desde la VISTA, que es donde está el HTML pintado; un `.dec`
// reconstruido no lo tiene. Si la caja trae id, se devuelve el suyo.
function respDe(caja) {
  const todos = respsDe(nodos['lienzos-vista']);
  if (caja && caja.dataset && caja.dataset.id) {
    return todos.find(r => r.dataset.id === caja.dataset.id) || todos[0] || null;
  }
  return todos[0] || null;
}

function respsDe(caja) {
  return reconstruir(caja, 'resp', /<textarea class="dresp" data-id="([^"]+)"[^>]*>([^<]*)<\/textarea>/g,
    m => {
      const c = nuevo('resp-' + m[1]);
      c.dataset.id = m[1];
      c.value = m[2];
      return c;
    });
}

function archsDe(caja) {
  return reconstruir(caja, 'arch',
    /data-arch="([^"]+)"\s+data-proy="([^"]+)"\s+data-vuelve="([^"]*)"/g, m => {
      const b = nuevo('arch-' + m[1]);
      b.dataset.arch = m[1]; b.dataset.proy = m[2];
      b.dataset.vuelve = m[3];
      return b;
    });
}

function decsDe(caja) {
  return reconstruir(caja, 'dec', /<details class="dec" data-id="([^"]+)"([^>]*)>/g, m => {
    const d = nuevo('dec-' + m[1] + '-' + Math.abs(hash(m[2])));
    d.dataset.id = m[1];
    // `data-e` sale del propio HTML: es lo que el script lee para saber si
    // volver a pulsar deshace la decisión.
    const e = m[2].match(/data-e="([^"]+)"/);
    if (e) d.dataset.e = e[1];
    d._hijos = ['si','no','luego'].map(v => {
      const b = nuevo(`bt-${m[1]}-${v}-${Math.abs(hash(m[2]))}`);
      b.dataset.v = v; b._sel = '.dbb button';
      return b;
    });
    return d;
  });
}
function hash(s){ let h = 0; for (const c of String(s)) h = (h * 31 + c.charCodeAt(0)) | 0; return h; }

// ── fetch gobernado desde el test ──────────────────────────────────────────
const LIENZO = { id: 'revision', titulo: 'Revisión', plantilla: PLANTILLA_DEL_TEST,
                 proyecto_id: 'pedidos', slot: 'refactor', publicado_en: null,
                 tuyo: false, cuerpo: CUERPO_DEL_TEST };

global.fetch = async (url, opciones) => {
  REG.peticiones.push(url);
  if (url.endsWith('/archivar')) {
    REG.archivados.push({ url, cuerpo: JSON.parse(opciones.body) });
    return { ok: true, status: 200, json: async () => ({ ok: true, lienzo: {} }) };
  }
  if (opciones && opciones.method === 'POST') {
    REG.guardados.push(JSON.parse(opciones.body).cuerpo);
    return { ok: true, status: 200, json: async () => ({ ok: true }) };
  }
  if (url.startsWith('/api/lienzos')) {
    return { ok: true, status: 200, json: async () => ({ ok: true, lienzos: [
      { id: 'revision', titulo: 'Revisión', plantilla: PLANTILLA_DEL_TEST,
        proyecto_id: 'pedidos', slot: 'refactor', publicado_en: null, tuyo: false }]})};
  }
  return { ok: true, status: 200, json: async () => ({ ok: true, lienzo: LIENZO }) };
};

// Los cuatro nodos que el script exige para arrancar.
nuevo('lienzos-lista'); nuevo('lienzos-vista');
nuevo('lienzos-buscar'); nuevo('lienzos-punto');
nuevo('pest-lienzos').dataset.hoja = 'lienzos';

// El botón de la lupa: el script lo busca por id nada más pintar un diagrama,
// así que tiene que existir ANTES, no cuando el test quiera pulsarlo.
nuevo('lienzo-ampliar');

// La lupa monta una capa nueva sobre el documento. Es lo único del panel que
// crea nodos en vez de pintar dentro de los suyos.
let creados = 0;
document.createElement = (etiqueta) => {
  const n = nuevo(`creado-${etiqueta}-${creados++}`);
  n.className = '';
  n.remove = () => { REG.cerrada = true; };
  return n;
};
document.body = { appendChild(n) { REG.capa = n; } };
document.addEventListener = (ev, fn) => { (REG.globales ||= {})[ev] = fn; };
document.removeEventListener = () => { REG.sueltos = true; };
"""

FINAL = r"""
global.vistaDe = () => nodos['lienzos-vista'];
(async () => {
  await new Promise(r => setTimeout(r, 60));   // deja correr los await del script
  const decs = decsDe(nodos['lienzos-vista']);
  ACCION
  await new Promise(r => setTimeout(r, 60));
  console.log(JSON.stringify({
    lista: nodos['lienzos-lista'].innerHTML,
    vista: nodos['lienzos-vista'].innerHTML,
    guardados: REG.guardados,
    aviso: REG.aviso || null,
    decs: decs.length,
    peticiones: REG.peticiones,
    archivados: REG.archivados || [],
    corto: !!REG.corto,
    capa: REG.capa ? String(REG.capa.innerHTML) : null,
    cerrada: !!REG.cerrada,
    sueltos: !!REG.sueltos,
  }));
})();
"""


def _correr(accion: str = "", cuerpo: str = CUERPO, plantilla: str = "decisiones") -> dict:
    node = shutil.which("node")
    if not node:
        pytest.skip("hace falta node para ejecutar el JS")
    guion = (
        f"const CUERPO_DEL_TEST = {json.dumps(cuerpo)};\n"
        f"const PLANTILLA_DEL_TEST = {json.dumps(plantilla)};\n"
        + ARNES
        + GUION.read_text(encoding="utf-8")
        + FINAL.replace("ACCION", accion)
    )
    r = subprocess.run([node, "-e", guion], capture_output=True, text=True, timeout=40)
    assert r.returncode == 0, f"el script reventó:\n{r.stderr}"
    return json.loads(r.stdout.strip().splitlines()[-1])


# ─────────────────────────── que arranque y pinte ───────────────────────────


def test_el_script_no_revienta_y_pinta_la_lista():
    salida = _correr()
    assert "Revisión" in salida["lista"]


def test_los_puntos_llegan_plegados_con_su_estado():
    """Plegados es el objetivo entero: ves 8 títulos, no 8 explicaciones."""
    salida = _correr()
    assert salida["decs"] == 3
    assert "contador en memoria" in salida["vista"]
    assert 'data-e="si"' in salida["vista"]          # n2 ya venía decidido
    assert "de 3 decididos" in salida["vista"]


def test_sin_sus_nodos_no_hace_nada_en_vez_de_reventar():
    """En cualquier pantalla que no sea /trabajo estos elementos no existen. Si
    el script no saliera limpio, se llevaría por delante lo que hubiera detrás."""
    node = shutil.which("node") or pytest.skip("hace falta node")
    r = subprocess.run(
        [node, "-e", "global.document={getElementById:()=>null,querySelectorAll:()=>[]};"
                     + GUION.read_text(encoding='utf-8')],
        capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, r.stderr


# ─────────── lo que de verdad puede corromper: reescribir el cuerpo ─────────


def test_marcar_una_decision_cambia_SOLO_esa_linea():
    """🔴 El riesgo real: este script reescribe el archivo del usuario."""
    salida = _correr('decs[0].querySelectorAll(".dbb button")[0].disparar("click");')

    assert len(salida["guardados"]) == 1
    nuevo = salida["guardados"][0]

    viejas = CUERPO.split("\n")
    nuevas = nuevo.split("\n")
    distintas = [(a, b) for a, b in zip(viejas, nuevas) if a != b]
    assert distintas == [("    decision: pendiente", "    decision: si")]
    # Y las decisiones de los otros puntos siguen donde estaban.
    assert nuevo.count("decision: si") == 2
    assert nuevo.count("decision: pendiente") == 1


def test_los_campos_que_el_hub_no_conoce_sobreviven_a_marcar():
    salida = _correr('decs[1].querySelectorAll(".dbb button")[1].disparar("click");')
    assert "inventado_por_una_plantilla_futura: 42" in salida["guardados"][0]


def test_volver_a_pulsar_lo_mismo_deshace_la_decision():
    """Sin esto, un clic accidental es una decisión que no se puede retirar."""
    salida = _correr('decs[1].querySelectorAll(".dbb button")[0].disparar("click");')
    assert "decision: pendiente" in salida["guardados"][0].split("- id: n2")[1]


def test_marcar_un_punto_sin_linea_de_decision_se_la_anade():
    cuerpo = 'puntos:\n  - id: n1\n    punto: "sin decision escrita"\n'
    salida = _correr('decs[0].querySelectorAll(".dbb button")[0].disparar("click");',
                     cuerpo=cuerpo)
    assert "decision: si" in salida["guardados"][0]


def test_si_el_guardado_falla_se_avisa_y_no_se_pinta_como_decidido():
    """Enseñar como decidido algo que no llegó al hub es la peor forma de fallar:
    él nunca lo leerá y tú creerás que sí."""
    guion_roto = ARNES.replace(
        "REG.guardados.push(JSON.parse(opciones.body).cuerpo);\n"
        "    return { ok: true, status: 200, json: async () => ({ ok: true }) };",
        "return { ok: false, status: 500, json: async () => ({}) };")
    node = shutil.which("node") or pytest.skip("hace falta node")
    guion = (f"const CUERPO_DEL_TEST = {json.dumps(CUERPO)};\n"
             'const PLANTILLA_DEL_TEST = "decisiones";\n' + guion_roto
             + GUION.read_text(encoding="utf-8")
             + FINAL.replace("ACCION",
                             'decs[0].querySelectorAll(".dbb button")[0].disparar("click");'))
    r = subprocess.run([node, "-e", guion], capture_output=True, text=True, timeout=40)
    assert r.returncode == 0, r.stderr
    salida = json.loads(r.stdout.strip().splitlines()[-1])
    assert salida["aviso"] is not None
    assert "No se pudo guardar" in salida["aviso"]["titulo"]


# ─────────────────────────── el punto de «hay algo nuevo» ───────────────────


def test_el_texto_del_lienzo_va_escapado():
    """Un lienzo lo escribe un modelo a partir de un repo que puede no ser tuyo,
    y esto se pinta con innerHTML dentro de la página que tiene el WebSocket de
    la terminal (regla dura 8)."""
    malo = 'puntos:\n  - id: n1\n    punto: "<img src=x onerror=alert(1)>"\n'
    salida = _correr(cuerpo=malo)
    assert "<img" not in salida["vista"]
    assert "&lt;img" in salida["vista"]


# ────────────────── de qué proyecto pregunta el panel ──────────────────


def test_manda_el_proyecto_de_la_ventana_que_se_mira():
    """El caso normal no cambia: la ventana visible decide."""
    salida = _correr()
    assert any("proyecto=pedidos" in u for u in salida["peticiones"])


def test_sin_ventana_abierta_el_proyecto_sale_del_slot():
    """🔴 El fallo que esto arregla no se veía como fallo.

    Creas un slot, lo pinchas antes de abrir nada, y el panel decía «aún no hay
    lienzos en este proyecto». No era que no hubiera: era que sin bloque de
    ventana el script no sabía por qué proyecto preguntar y mandaba vacío. Una
    lista vacía que afirma algo falso es peor que una que no dice nada.
    """
    salida = _correr(
        """
        global.SIN_VENTANA = true;
        nuevo('taller').dataset.proyecto = 'hub';
        nodos['lienzos-buscar'].disparar('input');
        """
    )
    assert any("proyecto=hub" in u for u in salida["peticiones"])


def test_la_ventana_gana_al_slot_cuando_las_dos_estan():
    """El fallback es fallback: cambiar de pestaña de tmux tiene que seguir
    cambiando de proyecto, que es para lo que se leía la ventana."""
    salida = _correr(
        """
        nuevo('taller').dataset.proyecto = 'hub';
        nodos['lienzos-buscar'].disparar('input');
        """
    )
    assert not any("proyecto=hub" in u for u in salida["peticiones"])
    assert any("proyecto=pedidos" in u for u in salida["peticiones"])


# ── archivar desde el panel ───────────────────────────────────────────────────


def test_archivar_manda_la_peticion_de_ese_lienzo():
    salida = _correr("archsDe(nodos['lienzos-lista'])[0].disparar('click');")
    assert len(salida["archivados"]) == 1
    assert salida["archivados"][0]["url"] == "/api/lienzo/pedidos/revision/archivar"
    assert salida["archivados"][0]["cuerpo"] == {"archivar": True}


def test_archivar_NO_abre_el_lienzo_que_acabas_de_quitar():
    """🔴 El botón vive DENTRO del item, que es clicable para abrirlo.

    Sin cortar la propagación, archivar abre en el visor justo lo que acabas de
    sacar de la lista — y el panel se queda enseñando algo que ya no está.
    """
    salida = _correr(
        "archsDe(nodos['lienzos-lista'])[0].disparar('click',"
        " { stopPropagation(){ REG.corto = true; } });")
    assert salida["corto"] is True, "el clic de archivar se propaga y abre el lienzo"


def test_el_boton_dice_lo_que_hace_segun_esté_archivado_o_no():
    """El mismo botón devuelve a la lista cuando estás mirando el archivo: sin
    la vuelta, archivar da miedo y lo que da miedo no se usa."""
    salida = _correr()
    assert 'data-vuelve=""' in salida["lista"]
    assert "no se borra" in salida["lista"]


# ── responder con tus palabras ────────────────────────────────────────────────
#
# 🔴 Pedido el 2026-09-02 y visto en el mismo momento: en un lienzo de ocho
# puntos marcó tres con los botones y los otros cinco tuvo que contestarlos por
# la terminal, porque no eran sí o no. Un lienzo que sólo admite tres botones
# obliga a partir la respuesta en dos sitios — justo el trabajo que venía a
# quitar.


def test_cada_punto_admite_una_respuesta_escrita():
    salida = _correr()
    assert 'class="dresp"' in salida["vista"]


def test_la_respuesta_guardada_se_vuelve_a_ver():
    cuerpo = ('puntos:\n  - id: n1\n    punto: "algo"\n'
              '    respuesta: "lo que contesté"\n    decision: pendiente\n')
    salida = _correr(cuerpo=cuerpo)
    assert "lo que contesté" in salida["vista"]


def test_una_respuesta_con_dos_puntos_comillas_y_SALTOS_no_rompe_el_yaml():
    """🔴 Lo que de verdad puede destruir un lienzo.

    Una respuesta libre lleva dos puntos, comillas y saltos de línea, y
    cualquiera de las tres cosas rompe un YAML escrito en plano. Roto el
    frontmatter o el cuerpo, el punto deja de leerse y con él los demás.
    """
    accion = (
        "const c = vistaDe().querySelector('.dresp');"
        "c.value = 'depende: si el PAC lo valida, \"sí\";\\nsi no, no';"
        "c.disparar('blur');"
    )
    salida = _correr(accion)
    guardado = salida["guardados"][-1]

    # Se guarda en UNA línea y entrecomillado: el lector es un parser de líneas.
    assert "\n" not in guardado.split("respuesta:")[1].split("\n")[0]
    assert "\\n" in guardado          # el salto va escapado, no crudo
    import yaml
    datos = yaml.safe_load(guardado)  # y sigue siendo YAML válido
    punto = datos["puntos"][0]
    assert punto["respuesta"] == 'depende: si el PAC lo valida, "sí";\nsi no, no'


def test_responder_NO_cierra_el_punto_que_estas_contestando():
    """Repintar reconstruye los `<details>` y cierra el punto justo al terminar
    de escribir en él. La decisión sí repinta, porque cambia la cabecera."""
    guion = GUION.read_text(encoding="utf-8")
    tras_guardar = guion.split("previo = campo.value;")[1][:400]
    assert "pintar(l)" not in tras_guardar


# ── los motores de dibujo: `arquitectura`, `pasos`, `comparativa` ─────────────
#
# 🔴 Estaban pendientes desde el 2026-09-02 (punto n2 de «Pendientes de
# lienzos»): el hub sólo sabía pintar `decisiones`, así que un lienzo de las
# otras tres se guardaba bien y se veía como el YAML en crudo. El primero que
# lo destapó fue uno de `pasos` de verdad — diez pasos hasta el 23 de
# septiembre— publicado desde otra terminal.

ARQ = """plantilla: arquitectura
piezas:
  - {id: apigw, tipo: entrada, nombre: "API Gateway /pedidos"}
  - {id: l1, tipo: computo, nombre: "validar"}
  - {id: q1, tipo: cola, nombre: "SQS pedidos"}
  - {id: db2, tipo: almacen, nombre: "DynamoDB idempotencia"}
flujo:
  - apigw -> l1
  - l1 ~> db2
  - l1 -> q1
"""

PASOS = """plantilla: pasos
piezas:
  - {id: p1, tipo: entrada, nombre: "1 - Respaldo del trabajo: tar.gz nuevo y patron en projects.yml"}
  - {id: p2, tipo: computo, nombre: "2 - Transporte: Tailscale en Windows, tailnet lock, RDP"}
  - {id: p3, tipo: almacen, nombre: "3 - Ensayo con corte real"}
flujo:
  - p1 -> p2
  - p2 -> p3
"""

COMP = """plantilla: comparativa
criterios: [peso, licencia, "sin build"]
opciones:
  - nombre: Drawflow
    valores: ["45 KB", MIT, "si"]
    nota: "vanilla, nodos HTML"
  - nombre: Cytoscape
    valores: ["365 KB", MIT]
eleccion: Drawflow
porque: "seis veces mas ligero que lo que ya se lleva vendorizado"
"""


def test_una_arquitectura_se_dibuja_en_vez_de_verse_como_yaml():
    salida = _correr(cuerpo=ARQ, plantilla="arquitectura")
    assert "<svg" in salida["vista"]
    assert "lienzo-crudo" not in salida["vista"]
    # Las cuatro piezas, cada una con el color de su tipo puesto por su clase.
    assert salida["vista"].count("<rect") == 4
    for tipo in ("entrada", "computo", "cola", "almacen"):
        assert f"nd-{tipo}" in salida["vista"]


def test_ningun_color_literal_sale_del_motor():
    """🔴 El sistema visual manda: el tono lo pone `trabajo.html` desde los
    tokens, no el JavaScript que dibuja. Un hex aquí sería la única pieza del
    hub que no cambia cuando cambie la paleta."""
    import re
    guion = GUION.read_text(encoding="utf-8")
    # La maqueta de la que se portó esto llevaba su paleta dentro, en hex. Lo
    # que se busca es justamente eso: que no haya vuelto al copiarla.
    assert not re.findall(r"#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})\b", guion)


def test_la_lectura_se_distingue_del_flujo():
    """`~>` no es cosmética: no cuenta para el orden, y por eso se dibuja
    distinta. Si se viera igual, el lector no sabría que puede ignorarla al
    seguir el camino principal."""
    salida = _correr(cuerpo=ARQ, plantilla="arquitectura")
    assert 'class="ar flojo"' in salida["vista"]
    assert salida["vista"].count('class="ar"') == 2


def test_un_nombre_largo_se_reparte_en_varias_lineas():
    """🔴 Lo que la maqueta no tuvo delante. Allí las piezas se llamaban «λ
    validar»; el primer lienzo de `pasos` de verdad traía nombres de setenta
    caracteres, y cortarlos a veinte deja «1 - Respaldo del t…», que no es un
    paso: es un número."""
    salida = _correr(cuerpo=PASOS, plantilla="pasos")
    assert salida["vista"].count("<tspan") > 6      # más de dos líneas por caja
    assert "projects.yml" in salida["vista"]        # el final del nombre llega
    assert "…" not in salida["vista"]


def test_el_paso_mas_largo_del_lienzo_real_entra_entero():
    """🔴 La medida, no el cálculo (regla 20). Con 22 caracteres por línea y
    cuatro líneas —lo que parecía de sobra— tres de los diez pasos del lienzo
    del 23 de septiembre salían cortados en el navegador. Éste es el más largo
    de aquéllos, con sus 90 caracteres; si alguien vuelve a estrechar la caja,
    esto es lo que se entera."""
    largo = ("3 - 10-13 sep - Las tres puertas: hosts configurables, "
             "alta por QR, interruptor de terminal")
    cuerpo = f'plantilla: pasos\npiezas:\n  - {{id: p3, tipo: computo, nombre: "{largo}"}}\n'
    salida = _correr(cuerpo=cuerpo, plantilla="pasos")
    assert "…" not in salida["vista"]
    assert "terminal" in salida["vista"]


def test_una_pieza_de_lectura_junto_a_su_lector_se_enlaza_en_recto():
    """🔴 Se vio en el navegador, no leyendo el código. Una lectura se coloca
    JUNTO a su lector a propósito, y ese caso caía en el rodeo de las flechas
    que vuelven: la línea pasaba por encima de la caja de destino y la punta
    quedaba fuera, a su derecha. Es el enlace más común de este motor, así que
    el fallo salía en casi todos los diagramas."""
    salida = _correr(cuerpo="orientacion: vertical\n" + ARQ, plantilla="arquitectura")
    import re
    flojo = re.search(r'class="ar flojo" d="([^"]+)"', salida["vista"]).group(1)
    # Un solo tramo recto: el rodeo daba tres, y el último entraba por detrás.
    assert flojo.count("L") == 1, f"la lectura da un rodeo: {flojo}"


def test_los_pasos_van_en_vertical():
    """Una cadena larga en horizontal se escala hasta que no se lee (regla 20),
    y una lista de pasos se lee hacia abajo. En vertical las tres cajas
    comparten la x y bajan; en horizontal sería al revés."""
    salida = _correr(cuerpo=PASOS, plantilla="pasos")
    import re
    xs = [m for m in re.findall(r'<rect x="([-\d.]+)" y="([-\d.]+)"', salida["vista"])]
    assert len({x for x, _ in xs}) == 1, "los pasos no están en una sola columna"
    assert len({y for _, y in xs}) == 3, "los pasos no bajan"


def test_un_flujo_que_apunta_a_una_pieza_que_no_existe_lo_dice_y_no_borra_nada():
    """🔴 El cuerpo se enseña igual. Un lienzo mal escrito sigue siendo trabajo
    de alguien, y un panel en blanco le quitaría lo único que puede corregir."""
    roto = ARQ.replace("- l1 -> q1", "- l1 -> fantasma")
    salida = _correr(cuerpo=roto, plantilla="arquitectura")
    assert "fantasma" in salida["vista"]
    assert "No se pudo dibujar" in salida["vista"]
    assert "lienzo-crudo" in salida["vista"]
    assert "<svg" not in salida["vista"]


def test_el_nombre_de_una_pieza_va_escapado():
    """Mismo motivo que en `decisiones`: esto se pinta con innerHTML dentro de
    la página que tiene el WebSocket de la terminal (regla dura 8)."""
    malo = ('plantilla: arquitectura\npiezas:\n'
            '  - {id: a, tipo: entrada, nombre: "<img src=x onerror=alert(1)>"}\nflujo:\n')
    salida = _correr(cuerpo=malo, plantilla="arquitectura")
    assert "<img" not in salida["vista"]
    assert "&lt;img" in salida["vista"]


def test_ampliar_abre_el_diagrama_a_pantalla_completa():
    """El panel mide ~330 px y una arquitectura de cinco niveles mide mil:
    dentro se escala hasta que las etiquetas no se leen, que es la única forma
    en que este motor falla sin que nada parezca roto."""
    salida = _correr("nodos['lienzo-ampliar'].disparar('click');",
                     cuerpo=ARQ, plantilla="arquitectura")
    assert salida["capa"] is not None
    assert "<svg" in salida["capa"]


def test_los_dos_diagramas_a_la_vez_no_comparten_el_id_de_la_flecha():
    """Los dos SVG conviven en el documento mientras la lupa está abierta, y
    dos `id` iguales hacen que el segundo apunte al marcador del primero."""
    salida = _correr("nodos['lienzo-ampliar'].disparar('click');",
                     cuerpo=ARQ, plantilla="arquitectura")
    assert 'id="flu-lupa"' in salida["capa"]
    assert 'id="flu-lupa"' not in salida["vista"]


def test_cerrar_la_lupa_suelta_el_oyente_de_teclado():
    """Un oyente global que sobrevive a su capa se acumula con cada apertura y
    acaba respondiendo Escape en nombre de un diagrama que ya no está."""
    salida = _correr(
        "nodos['lienzo-ampliar'].disparar('click');"
        "REG.globales.keydown({ key: 'Escape' });",
        cuerpo=ARQ, plantilla="arquitectura")
    assert salida["cerrada"] is True
    assert salida["sueltos"] is True


def test_una_comparativa_tambien_se_puede_ampliar():
    """Sus columnas se cortan en un panel de ~330 px —medido: el tercer
    criterio quedaba fuera—, y lo que decide en una comparativa es ver los
    valores del mismo criterio uno al lado de otro."""
    salida = _correr("nodos['lienzo-ampliar'].disparar('click');",
                     cuerpo=COMP, plantilla="comparativa")
    assert salida["capa"] is not None
    assert "<table>" in salida["capa"]


def test_las_decisiones_NO_se_amplian():
    """Sus botones escriben en el archivo del lienzo: una copia dentro de la
    capa sería un segundo sitio desde donde guardar lo mismo."""
    salida = _correr()
    assert "lienzo-ampliar" not in salida["vista"]


def test_una_comparativa_se_ve_como_tabla():
    """Lo que decide es DÓNDE difieren las opciones, y eso sólo se ve con los
    valores del mismo criterio uno encima de otro."""
    salida = _correr(cuerpo=COMP, plantilla="comparativa")
    assert "<table>" in salida["vista"]
    assert "Drawflow" in salida["vista"] and "Cytoscape" in salida["vista"]
    assert "sin build" in salida["vista"]
    assert "vanilla, nodos HTML" in salida["vista"]


def test_un_valor_que_falta_sale_como_raya_y_no_en_blanco():
    """🔴 La plantilla lo pide por escrito: un hueco silencioso se lee como «no
    aplica» cuando casi siempre significa «no lo he mirado» — y eso decide
    mal. A Cytoscape le falta el tercer criterio."""
    salida = _correr(cuerpo=COMP, plantilla="comparativa")
    assert "—" in salida["vista"]


def test_la_opcion_propuesta_se_distingue_y_dice_por_que():
    salida = _correr(cuerpo=COMP, plantilla="comparativa")
    assert 'class="elegida"' in salida["vista"]
    assert "seis veces mas ligero" in salida["vista"]


def test_los_criterios_tambien_valen_escritos_en_bloque():
    """Las dos formas son YAML válido y el modelo escribe la que le sale."""
    bloque = COMP.replace('criterios: [peso, licencia, "sin build"]',
                          "criterios:\n  - peso\n  - licencia\n  - sin build")
    salida = _correr(cuerpo=bloque, plantilla="comparativa")
    assert "<table>" in salida["vista"]
    assert "sin build" in salida["vista"]


def test_una_plantilla_que_el_hub_no_conoce_se_sigue_viendo_cruda():
    """Es como estuvieron estas tres hasta hoy: feo, pero recuperable. La que
    venga después seguirá igual, y eso es lo que se prueba."""
    salida = _correr(cuerpo="loquesea:\n  - a\n", plantilla="mapamundi")
    assert "lienzo-crudo" in salida["vista"]
    assert "loquesea" in salida["vista"]
