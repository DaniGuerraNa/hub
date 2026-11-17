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


# ── el aviso: siempre enseña algo, y sus botones (LLA-13, C-0407) ────────────

ARNES_AVISO = r"""
const salida = { avisos: [], enviados: [], abiertas: [], intentos: [] };
const oyentes = {};
global.self = {
  addEventListener: (ev, f) => { oyentes[ev] = f; },
  registration: { showNotification: async (titulo, o) => { salida.avisos.push([titulo, o]); } },
  skipWaiting() {},
  clients: { claim: async () => {}, matchAll: async () => [],
             openWindow: async (url) => { salida.abiertas.push(url); } },
};
const RED = __RED__;
global.fetch = async (url, o) => {
  salida.intentos.push(url);
  if (!RED) throw new TypeError('Failed to fetch');
  salida.enviados.push([url, o.method, o.headers, JSON.parse(o.body)]);
  return { status: 200, json: async () => RED };
};
__SW__
let espera = null;
const esperar = (p) => { espera = p; };
__ESCENA__
Promise.resolve(espera).then(() => console.log(JSON.stringify(salida)),
                             (e) => console.log(JSON.stringify({ error: String(e) })));
"""


def _correr(tmp_path, escena: str, red=None) -> dict:
    node = shutil.which("node")
    if not node:
        pytest.skip("sin node")
    guion = (ARNES_AVISO.replace("__RED__", json.dumps(red)).replace("__ESCENA__", escena)
             .replace("__SW__", SW.read_text(encoding="utf-8")))
    (tmp_path / "sw.js").write_text(guion, encoding="utf-8")
    r = subprocess.run([node, str(tmp_path / "sw.js")], capture_output=True, text=True, timeout=20)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


def _push(tmp_path, crudo: str | None) -> list:
    """Un push con `crudo` como cuerpo (None: sin cuerpo). Devuelve los avisos enseñados."""
    escena = (f"const CRUDO = {json.dumps(crudo)};\n"
              "oyentes.push({ data: CRUDO === null ? null : { json: () => JSON.parse(CRUDO), text: () => CRUDO },"
              " waitUntil: esperar });")
    salida = _correr(tmp_path, escena)
    assert "error" not in salida, salida
    return salida["avisos"]


def _botones(aviso) -> list[str]:
    return [a["action"] for a in aviso[1].get("actions") or []]


@pytest.mark.parametrize("crudo, cuerpo", [(None, ""), ("{roto", "{roto"), ("null", ""), ("7", ""), ("[1]", "")])
def test_el_aviso_siempre_ensena_algo_aunque_el_cuerpo_no_sea_un_aviso(tmp_path, crudo, cuerpo):
    """🔴 En iOS un push sin notificación hace que Safari retire el permiso
    (LLA-13). `null` es JSON válido y `d.notification` reventaba."""
    [(titulo, opciones)] = _push(tmp_path, crudo)
    assert titulo == "Secretario" and opciones["body"] == cuerpo


def test_una_solicitud_trae_aprobar_y_rechazar_sólo_si_se_decide_desde_el_aviso(tmp_path):
    con = {"notification": {"title": "Permiso", "body": "Crear un slot"}, "secretario": {"solicitud": 3, "decidir": True}}
    [aviso] = _push(tmp_path, json.dumps(con))
    assert _botones(aviso) == ["aprobar", "rechazar"] and aviso[1]["data"]["solicitud"] == 3
    con["secretario"]["decidir"] = False
    assert _botones(_push(tmp_path, json.dumps(con))[0]) == []


def test_un_recordatorio_trae_hecho_y_en_una_hora(tmp_path):
    """C-0407: de 20 recordatorios, 11 seguían abiertos; el aviso no traía cómo cerrarlo."""
    [aviso] = _push(tmp_path, json.dumps({"notification": {"title": "⏰ Recordatorio", "body": "Llamar a Ana"},
                                          "secretario": {"compromiso": 7}}))
    assert _botones(aviso) == ["hecho", "aplazar"]
    assert [a["title"] for a in aviso[1]["actions"]] == ["Hecho", "En 1 h"]
    assert aviso[1]["data"]["compromiso"] == 7
    # No cambia cómo suena: ni se queda fijo ni sustituye a otro.
    assert "tag" not in aviso[1] and "requireInteraction" not in aviso[1]


def _tocar_boton(tmp_path, accion: str, red, compromiso=7) -> dict:
    escena = ("oyentes.notificationclick({ notification: { close() {}, data: { url: '/secretario?p=pendientes', "
              f"compromiso: {json.dumps(compromiso)} }} }}, action: {json.dumps(accion)}, waitUntil: esperar }});")
    salida = _correr(tmp_path, escena, red)
    assert "error" not in salida, salida
    return salida


@pytest.mark.parametrize("accion", ["hecho", "aplazar"])
def test_hecho_y_en_una_hora_hacen_el_post_y_dicen_lo_que_paso(tmp_path, accion):
    s = _tocar_boton(tmp_path, accion, {"ok": True, "error": None})
    assert s["enviados"] == [["/api/secretario/compromiso/7", "POST", {"Content-Type": "application/json"},
                              {"accion": accion}]]
    [(titulo, opciones)] = s["avisos"]
    assert opciones["body"] == ("Hecho." if accion == "hecho" else "Te lo vuelvo a recordar en una hora.")
    assert opciones["tag"] == "compromiso-7" and s["abiertas"] == []


def test_si_el_hub_dice_que_no_el_aviso_lo_dice(tmp_path):
    s = _tocar_boton(tmp_path, "hecho", {"ok": False, "error": "ese compromiso ya no existe"})
    assert s["avisos"][0][1]["body"] == "No se pudo: ese compromiso ya no existe"


def test_sin_red_el_boton_abre_la_app(tmp_path):
    """Lo intentó y no llegó: se abre Pendientes para hacerlo ahí, y no se dice «Hecho»."""
    s = _tocar_boton(tmp_path, "hecho", None)
    assert s["intentos"] == ["/api/secretario/compromiso/7"]
    assert s["enviados"] == [] and s["avisos"] == []
    assert s["abiertas"] == ["/secretario?p=pendientes"]


def test_aprobar_desde_el_aviso_sigue_yendo_a_su_solicitud(tmp_path):
    escena = ("oyentes.notificationclick({ notification: { close() {}, data: { url: '/secretario?p=pendientes', "
              "solicitud: 3 } }, action: 'aprobar', waitUntil: esperar });")
    s = _correr(tmp_path, escena, {"ok": True, "error": None})
    assert [e[0] for e in s["enviados"]] == ["/api/secretario/solicitud/3"] and s["enviados"][0][3] == {"decision": "aprobar"}
    assert s["avisos"][0][1]["body"] == "Aprobado: lo hace en unos segundos."
    assert s["avisos"][0][1]["tag"] == "decision-3"
