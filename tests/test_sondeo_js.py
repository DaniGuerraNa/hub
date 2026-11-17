"""Sondear sólo con la pestaña a la vista (C-0277), ejecutando el JS (regla dura 11).

Un /trabajo de fondo seguía preguntando ~31 veces por minuto sin fin: lienzos,
consultas y programados, y el refresco de /navegante y /reuniones. Aquí se
ejecuta `sondeo.js` con un reloj de mentira, y cada uno de esos scripts de
verdad encima de él, con una pestaña que se oculta y vuelve.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

ESTATICOS = Path(__file__).resolve().parents[1] / "src" / "hub" / "static"
SONDEO = ESTATICOS / "sondeo.js"

# Un reloj que sólo avanza cuando se le pide, y una pestaña que se oculta.
RELOJ = r"""
let ahora = 0, sig = 1, disparos = 0;
const relojes = new Map();
global.setInterval = (f, ms) => { relojes.set(sig, { f, ms, prox: ahora + ms }); return sig++; };
global.clearInterval = (id) => { relojes.delete(id); };
function avanzar(ms) {
  const fin = ahora + ms;
  for (;;) {
    let siguiente = null;
    for (const r of relojes.values()) if (r.prox <= fin && (!siguiente || r.prox < siguiente.prox)) siguiente = r;
    if (!siguiente) break;
    ahora = siguiente.prox; siguiente.prox += siguiente.ms; disparos++; siguiente.f();
  }
  ahora = fin;
}
const oyentes = {};
global.window = global;
global.addEventListener = () => {};
global.document = {
  hidden: false, activeElement: null,
  addEventListener(ev, f) { (oyentes[ev] ||= []).push(f); },
  removeEventListener(ev, f) { oyentes[ev] = (oyentes[ev] || []).filter((g) => g !== f); },
};
function verse(si) { document.hidden = !si; (oyentes.visibilitychange || []).forEach((f) => f()); }
"""


def _node(programa: str) -> dict:
    node = shutil.which("node") or pytest.skip("hace falta node para ejecutar el JS")
    salida = subprocess.run([node, "-e", programa], capture_output=True, text=True, timeout=30)
    assert salida.returncode == 0, salida.stderr
    return json.loads(salida.stdout.strip().splitlines()[-1])


def _sondeo(cuerpo: str) -> dict:
    return _node(RELOJ + SONDEO.read_text(encoding="utf-8") + "\nlet n = 0;\n" + cuerpo)


def test_a_la_vista_pregunta_a_su_ritmo():
    r = _sondeo("""
    HubSondeo.cada(() => n++, 5000);
    avanzar(30000);
    console.log(JSON.stringify({ n }));
    """)
    assert r == {"n": 6}


def test_con_la_pestana_oculta_no_pregunta_y_al_volver_pregunta_enseguida():
    r = _sondeo("""
    document.hidden = true;
    HubSondeo.cada(() => n++, 5000);
    avanzar(30000);
    const oculta = n;
    verse(true);
    const alVolver = n;
    avanzar(5000);
    console.log(JSON.stringify({ oculta, alVolver, despues: n, relojes: relojes.size }));
    """)
    assert r == {"oculta": 0, "alVolver": 1, "despues": 2, "relojes": 1}


def test_al_ocultarse_a_medias_para_y_no_se_duplica_al_volver_dos_veces():
    r = _sondeo("""
    HubSondeo.cada(() => n++, 5000);
    avanzar(10000);
    verse(false);
    avanzar(60000);
    const oculta = n;
    verse(true); verse(true);
    avanzar(5000);
    console.log(JSON.stringify({ oculta, despues: n, relojes: relojes.size }));
    """)
    assert r == {"oculta": 2, "despues": 4, "relojes": 1}


def test_parado_no_vuelve_aunque_la_pestana_vuelva():
    r = _sondeo("""
    const parar = HubSondeo.cada(() => n++, 5000);
    parar();
    verse(false); verse(true);
    avanzar(30000);
    console.log(JSON.stringify({ n, relojes: relojes.size,
                                 oyentes: (oyentes.visibilitychange || []).length }));
    """)
    assert r == {"n": 0, "relojes": 0, "oyentes": 0}


# ── los que sondean, cada uno de verdad sobre `sondeo.js` ────────────────────
#
# Un documento donde todo existe y nada tiene contenido: lo justo para que cada
# script llegue a arrancar su sondeo. Lo que se mide es el reloj, no el pintado
# (eso lo prueban sus propios archivos de tests).
DOCUMENTO = r"""
function nodo() {
  return { innerHTML: '', textContent: '', value: '', hidden: false, disabled: false,
           dataset: { refrescar: '5', proyecto: 'demo', slot: '7' }, style: {},
           classList: { add() {}, remove() {}, contains() { return false; }, toggle() { return false; } },
           addEventListener() {}, removeEventListener() {}, setAttribute() {},
           getAttribute() { return null; }, removeAttribute() {},
           querySelector: () => nodo(), querySelectorAll() { return []; },
           closest() { return null; }, appendChild() {}, focus() {} };
}
Object.assign(document, { getElementById: () => nodo(), querySelector: () => nodo(),
                          querySelectorAll: () => [] });
let pedidas = 0;
global.fetch = () => { pedidas++; return Promise.resolve({ ok: true, status: 200,
  json: () => Promise.resolve({}), text: () => Promise.resolve('') }); };
global.location = { href: 'http://localhost/trabajo', pathname: '/trabajo', search: '', reload() {} };
global.HubUI = { avisar() {}, confirmar: () => Promise.resolve(false) };
global.HubSinRecarga = { refrescar: () => { pedidas++; return Promise.resolve([]); } };
"""

POLLERS = ["lienzos.js", "consultas.js", "programados.js", "navegante.js"]


def _poller(archivo: str, oculta: bool) -> dict:
    return _node(
        RELOJ + DOCUMENTO
        + f"document.hidden = {json.dumps(oculta)};\n"
        + SONDEO.read_text(encoding="utf-8") + "\n"
        + (ESTATICOS / archivo).read_text(encoding="utf-8")
        + r"""
        setTimeout(async () => {
          const alCargar = relojes.size;
          avanzar(60000);
          const enUnMinuto = disparos;
          await new Promise((ok) => setTimeout(ok, 5));
          const antes = pedidas;
          verse(true);
          const alVolver = relojes.size, preguntaAlVolver = pedidas > antes;
          verse(false);
          console.log(JSON.stringify({ alCargar, enUnMinuto, alVolver, preguntaAlVolver,
                                       alIrse: relojes.size }));
        }, 10);
        """)


@pytest.mark.parametrize("archivo", POLLERS)
def test_con_la_pestana_oculta_ningun_panel_pregunta_y_al_volver_si(archivo):
    """El caso medido en el informe: una pestaña de fondo, un minuto entero."""
    r = _poller(archivo, oculta=True)
    assert r == {"alCargar": 0, "enUnMinuto": 0, "alVolver": 1, "preguntaAlVolver": True,
                 "alIrse": 0}, archivo


@pytest.mark.parametrize("archivo", POLLERS)
def test_a_la_vista_cada_panel_sigue_preguntando(archivo):
    r = _poller(archivo, oculta=False)
    assert r["alCargar"] == 1 and r["enUnMinuto"] > 0, (archivo, r)


def test_ningun_panel_arranca_un_sondeo_por_su_cuenta():
    """Si uno vuelve a `setInterval` a pelo, vuelve a preguntar de fondo."""
    for archivo in POLLERS:
        texto = (ESTATICOS / archivo).read_text(encoding="utf-8")
        assert "setInterval(" not in texto, archivo
        assert "HubSondeo.cada(" in texto, archivo
