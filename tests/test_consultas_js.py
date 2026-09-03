"""El panel de consultas, ejecutando su JavaScript de verdad (regla dura 11).

🔴 Lo que hace peligroso a este panel: **el texto de una respuesta lo escribió
alguien de fuera, en un móvil**. Es el único contenido de todo el hub con ese
origen, y aquí se pinta con `innerHTML`. Sin escapar, cualquiera con permiso
para responder ejecutaría JavaScript en el hub — que sirve el endpoint de
terminal (regla dura 8).

Vive en /trabajo, así que un fallo al arrancar se lleva la terminal por delante
sin ningún síntoma visible.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

GUION = Path(__file__).resolve().parents[1] / "src" / "hub" / "static" / "consultas.js"

ARNES = r"""
const nodos = {};
function nuevo(id) {
  const n = {
    id, innerHTML: '', hidden: false, dataset: {},
    classList: { _s: new Set(),
      add(c){this._s.add(c)}, remove(c){this._s.delete(c)},
      contains(c){return this._s.has(c)},
      // Faltaba, y el script —perfectamente válido— moría aquí. Un arnés al
      // que le falta una API estándar convierte código correcto en un fallo.
      toggle(c, f){ const v = f === undefined ? !this._s.has(c) : f;
                    v ? this._s.add(c) : this._s.delete(c); return v; } },
    _oyentes: {},
    addEventListener(ev, fn){ (this._oyentes[ev] ||= []).push(fn); },
    disparar(ev){ (this._oyentes[ev] || []).forEach(f => f({})); },
    querySelector(){ return null; },
    querySelectorAll(){ return []; },
  };
  return (nodos[id] = n);
}

nuevo('consultas-lista');
nuevo('consultas-punto');
const pestana = nuevo('pest-consultas');
pestana.dataset.hoja = 'consultas';

const filtros = ['todas', 'pendientes', 'contestadas'].map(f => {
  const b = nuevo('filtro-' + f);
  b.dataset.filtro = f;
  return b;
});

const ventana = nuevo('ventana');
ventana.dataset.proyecto = 'pedidos';
const nota = nuevo('nota');
nota.dataset.slot = '7';

const REG = { peticiones: [] };

global.document = {
  getElementById: (id) => nodos[id] || null,
  querySelector: (sel) => {
    if (sel === '.por-ventana:not([hidden])') return ventana;
    if (sel === '.por-ventana:not([hidden]) .nota-texto') return nota;
    return null;
  },
  querySelectorAll: (sel) => {
    if (sel === '.pest-lado button') return [pestana];
    if (sel === '[data-filtro]') return filtros;
    return [];
  },
};
global.window = { addEventListener(){} };
global.setInterval = () => 0;
global.clearInterval = () => {};
global.fetch = (url) => {
  REG.peticiones.push(url);
  return Promise.resolve({ ok: true, json: () => Promise.resolve({ preguntas: PREGUNTAS }) });
};

__GUION__

// Se vuelca tras un turno: el pintado ocurre cuando resuelve el `fetch`.
setTimeout(() => {
  if (ABRIR) pestana.disparar('click');
  if (FILTRO) filtros.find(f => f.dataset.filtro === FILTRO).disparar('click');
  setTimeout(() => {
    console.log(JSON.stringify({
      ...REG,
      html: nodos['consultas-lista'].innerHTML,
      punto: nodos['consultas-punto'].classList.contains('hay'),
    }));
  }, 10);
}, 10);
"""


def _correr(preguntas: list[dict], abrir: bool = False, filtro: str = "") -> dict:
    node = shutil.which("node")
    if not node:
        pytest.skip("hace falta node para ejecutar el JS")
    guion = (
        f"const PREGUNTAS = {json.dumps(preguntas)};\n"
        f"const ABRIR = {json.dumps(abrir)};\n"
        f"const FILTRO = {json.dumps(filtro)};\n"
        + ARNES.replace("__GUION__", GUION.read_text(encoding="utf-8"))
    )
    salida = subprocess.run([node, "-e", guion], capture_output=True, text=True, timeout=30)
    assert salida.returncode == 0, salida.stderr
    return json.loads(salida.stdout.strip().splitlines()[-1])


def _pregunta(**campos):
    base = {
        "id": 1, "texto": "¿lleva IVA?", "respuesta": "", "estado": "enviada",
        "quien": "ana", "slot_id": 7, "lote": None, "creada_en": "2026-09-02T20:00:00+00:00",
    }
    return {**base, **campos}


def test_el_script_arranca_y_pide_las_del_proyecto_de_la_ventana():
    """El proyecto sale de la ventana que se MIRA, no de la que abrió la
    página: cambiar de pestaña de tmux cambia de trabajo."""
    r = _correr([_pregunta()])
    assert r["peticiones"] == ["/api/preguntas?proyecto=pedidos"]
    assert "¿lleva IVA?" in r["html"]


def test_la_respuesta_se_ve_junto_a_su_pregunta():
    """Es lo que se pidió: ver en el slot lo que se preguntó y lo que
    contestaron, sin salir del taller a /canal."""
    r = _correr([_pregunta(respuesta="sí, del 21%", estado="entregada")])
    assert "sí, del 21%" in r["html"]
    assert "¿lleva IVA?" in r["html"]


def test_lo_que_escribio_alguien_de_fuera_va_ESCAPADO():
    """🔴 El texto de una respuesta llega de un móvil ajeno por Telegram.

    Es el único contenido del hub con ese origen. Sin escapar, quien tenga
    permiso para responder ejecuta JavaScript en la página que sirve el
    endpoint de terminal — que da acceso de shell (regla dura 8).
    """
    r = _correr([_pregunta(
        texto="<img src=x onerror=alert(1)>",
        respuesta="<script>fetch('/api/slot/1/nota',{method:'POST'})</script>",
        quien="<b>ana</b>",
    )])
    assert "<script>" not in r["html"]
    assert "<img" not in r["html"]
    assert "&lt;script&gt;" in r["html"]
    assert "<b>ana</b>" not in r["html"]


def test_el_punto_se_enciende_con_una_RESPUESTA_no_con_una_pregunta():
    """Preguntar lo hace Claude y ya lo sabes; que alguien conteste es la
    novedad que justifica ir a mirar."""
    assert _correr([_pregunta(respuesta="ya está")])["punto"] is True
    assert _correr([_pregunta(respuesta="")])["punto"] is False


def test_al_abrir_la_hoja_el_punto_se_apaga():
    """No roba el foco: se enciende y lo abres tú (principio 9)."""
    assert _correr([_pregunta(respuesta="ya está")], abrir=True)["punto"] is False


def test_las_de_otro_slot_se_atenuan_pero_NO_se_esconden():
    """`--slot` es opcional al preguntar, así que filtrar por slot escondería
    preguntas reales y el panel diría «no hay» sobre cosas que sí hay."""
    r = _correr([_pregunta(id=9, slot_id=99, texto="la de otro trabajo")])
    assert "la de otro trabajo" in r["html"]
    assert "ajena" in r["html"] and "de otro slot" in r["html"]


def test_sin_ninguna_pregunta_lo_dice_en_vez_de_quedarse_en_blanco():
    r = _correr([])
    assert "Nada preguntado fuera" in r["html"]


# ── el filtro ─────────────────────────────────────────────────────────────────


def _dos():
    return [
        _pregunta(id=1, texto="la que espera", respuesta="", estado="enviada"),
        _pregunta(id=2, texto="la contestada", respuesta="ya está", estado="entregada"),
    ]


def test_pendientes_deja_fuera_las_contestadas():
    r = _correr(_dos(), filtro="pendientes")
    assert "la que espera" in r["html"]
    assert "la contestada" not in r["html"]


def test_contestadas_deja_fuera_las_que_esperan():
    r = _correr(_dos(), filtro="contestadas")
    assert "la contestada" in r["html"]
    assert "la que espera" not in r["html"]


def test_contestada_es_TENER_respuesta_no_estar_en_un_estado():
    """Los estados son del transporte: `entregada` dice que llegó al panel y
    `sin-confirmar` que se escribió sin poder confirmarlo. Filtrar por ellos
    dejaría fuera respuestas que existen — y `sin-confirmar` es justo el caso
    que hay que poder revisar."""
    r = _correr([_pregunta(id=3, texto="escrita sin confirmar",
                           respuesta="contestó igual", estado="sin-confirmar")],
                filtro="contestadas")
    assert "escrita sin confirmar" in r["html"]


def test_un_filtro_vacio_lo_dice_en_vez_de_quedarse_en_blanco():
    r = _correr([_pregunta(respuesta="")], filtro="contestadas")
    assert "Todavía no ha contestado nadie" in r["html"]
