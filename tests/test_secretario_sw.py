"""El service worker del secretario, ejecutado en node (regla dura 11).

Tocar un aviso tiene que llevar a su enlace (idea 2 del tablero, C-0158). La
app vive en `/secretario` y este service worker en `/secretario/`: no la
controla, y `WindowClient.navigate` rechaza siempre con un cliente que no
controla. Con la app abierta, el aviso sólo la traía al frente.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from hub import web

SW = Path(web.__file__).parent / "static" / "secretario-sw.js"

ARNES = r"""
const registro = [];
const oyentes = {};
global.self = {
  addEventListener: (ev, f) => { oyentes[ev] = f; },
  registration: { showNotification: async () => {} },
  skipWaiting() {},
  clients: {
    claim: async () => {},
    matchAll: async () => VENTANAS,
    openWindow: async (url) => { registro.push(['nueva', url]); },
  },
};
const VENTANAS = __VENTANAS__.map(v => ({
  url: v,
  // Como Chrome con un cliente que este service worker no controla.
  navigate: async () => { throw new TypeError('not controlled'); },
  focus: async () => { registro.push(['foco', v]); },
  postMessage: (m) => { registro.push(['mensaje', m]); },
}));
__SW__
let espera;
oyentes.notificationclick({
  notification: { close() {}, data: { url: __URL__ } }, action: '',
  waitUntil: (p) => { espera = p; },
});
espera.then(() => console.log(JSON.stringify(registro)), (e) => console.log(JSON.stringify(['error', String(e)])));
"""


def _tocar(tmp_path, ventanas: list[str], url: str) -> list:
    node = shutil.which("node")
    if not node:
        pytest.skip("sin node")
    guion = (ARNES.replace("__VENTANAS__", json.dumps(ventanas)).replace("__URL__", json.dumps(url))
             .replace("__SW__", SW.read_text(encoding="utf-8")))
    (tmp_path / "sw.js").write_text(guion, encoding="utf-8")
    r = subprocess.run([node, str(tmp_path / "sw.js")], capture_output=True, text=True, timeout=20)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def test_con_la_app_abierta_el_aviso_le_pide_que_vaya_al_enlace(tmp_path):
    url = "https://hub.ejemplo.ts.net/secretario?p=pendientes"
    r = _tocar(tmp_path, ["https://hub.ejemplo.ts.net/secretario"], url)
    assert ["mensaje", {"tipo": "abrir", "url": url}] in r
    assert ["foco", "https://hub.ejemplo.ts.net/secretario"] in r


def test_sin_la_app_abierta_abre_el_enlace(tmp_path):
    url = "https://hub.ejemplo.ts.net/reuniones/3"
    assert _tocar(tmp_path, [], url) == [["nueva", url]]


# ── el navegador renueva la suscripción por su cuenta (C-0232) ───────────────

ARNES_RENOVAR = r"""
const enviados = [];
const oyentes = {};
global.self = {
  addEventListener: (ev, f) => { oyentes[ev] = f; },
  registration: { pushManager: { subscribe: async (o) => ({
    toJSON: () => ({ endpoint: 'https://push.ejemplo.org/nueva', keys: { p256dh: 'P', auth: 'A' },
                     clave: o.applicationServerKey }) }) } },
  skipWaiting() {},
  clients: { claim: async () => {} },
};
global.fetch = async (url, o) => { enviados.push([url, JSON.parse(o.body)]); return { ok: true }; };
__SW__
let espera = null;
oyentes.pushsubscriptionchange({ oldSubscription: __VIEJA__, waitUntil: (p) => { espera = p; } });
Promise.resolve(espera).then(() => console.log(JSON.stringify(enviados)),
                             (e) => console.log(JSON.stringify(['error', String(e)])));
"""


def _renovar(tmp_path, vieja) -> list:
    node = shutil.which("node")
    if not node:
        pytest.skip("sin node")
    guion = ARNES_RENOVAR.replace("__VIEJA__", json.dumps(vieja)).replace("__SW__", SW.read_text(encoding="utf-8"))
    (tmp_path / "sw.js").write_text(guion, encoding="utf-8")
    r = subprocess.run([node, str(tmp_path / "sw.js")], capture_output=True, text=True, timeout=20)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def test_al_renovarse_la_suscripcion_le_dice_al_hub_cual_era_la_vieja(tmp_path):
    """Con la dirección vieja el hub le deja su nombre al aparato; sin ella salía «renovada»."""
    vieja = {"endpoint": "https://push.ejemplo.org/vieja", "options": {"applicationServerKey": "CLAVE"}}
    [(url, cuerpo)] = _renovar(tmp_path, vieja)
    assert url == "/api/secretario/push/alta"
    assert cuerpo["endpoint"] == "https://push.ejemplo.org/nueva" and cuerpo["clave"] == "CLAVE"
    assert cuerpo["motivo"] == "renovar" and cuerpo["anterior"] == "https://push.ejemplo.org/vieja"
    assert cuerpo["aparato"] == "renovada"
