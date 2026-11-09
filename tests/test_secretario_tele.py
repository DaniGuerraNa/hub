"""La tele por ECP de Roku (decisión 321).

🔴 Nada sale a la red de verdad: cada test levanta en 127.0.0.1, en un puerto
libre, un servidor que imita lo que contesta una Roku (device-info, apps,
active-app, keypress y launch) y apunta `secretario.yml` a él. Las acciones se
ejecutan enteras, con HTTP real, contra ese servidor.
"""

from __future__ import annotations

import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
import yaml

from hub.secretario import herramientas, memoria, piezas, roku
from hub.secretario.acciones import tele

pytestmark = pytest.mark.usefixtures("canal_telegram")

DEVICE_INFO = """<?xml version="1.0" encoding="UTF-8" ?>
<device-info>
  <vendor-name>TCL</vendor-name>
  <model-name>55S455</model-name>
  <friendly-device-name>TCL Roku TV</friendly-device-name>
  <user-device-name>Tele del cuarto</user-device-name>
  <power-mode>{modo}</power-mode>
</device-info>"""

APPS = {"tvinput.dtv": "Antena", "12": "Netflix", "837": "YouTube", "2213": "Roku Media Player",
        "22297": "Spotify Music", "tvinput.hdmi1": "HDMI 1", "tvinput.hdmi2": "HDMI 2"}


class RokuFalsa:
    """Lo mínimo de una Roku: guarda lo que recibe y cambia de estado como ella."""

    def __init__(self):
        self.modo = "PowerOn"
        self.activa = "tvinput.hdmi1"
        self.recibido: list[str] = []
        self.limitada = False           # «Control por apps móviles» en Limitado: 403 a las teclas
        self.lenta = 0.0                # segundos antes de contestar
        self.arranque = 0.0             # lo que tarda en pasar a PowerOn tras la tecla
        self.ignora_entradas = False
        self.muda_al_apagar = False     # sin Fast TV Start: apagada deja de contestar
        self._encendida_en = None
        self.apagada_del_todo = False


@pytest.fixture
def falsa(monkeypatch):
    estado = RokuFalsa()

    class Manejador(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _responder(self, codigo, cuerpo=b""):
            self.send_response(codigo)
            self.send_header("Content-Type", "text/xml; charset=utf-8")
            self.send_header("Content-Length", str(len(cuerpo)))
            self.end_headers()
            self.wfile.write(cuerpo)

        def _antes(self):
            if estado.lenta:
                time.sleep(estado.lenta)
            if estado._encendida_en and time.monotonic() >= estado._encendida_en:
                estado.modo, estado._encendida_en = "PowerOn", None
            if estado.apagada_del_todo:
                self.close_connection = True
                self.connection.close()
                return False
            return True

        def do_GET(self):
            if not self._antes():
                return
            if self.path == "/query/device-info":
                self._responder(200, DEVICE_INFO.format(modo=estado.modo).encode())
            elif self.path == "/query/apps":
                filas = "".join(f'<app id="{i}" type="appl" version="1.0">{n}</app>' for i, n in APPS.items())
                self._responder(200, f"<apps>{filas}</apps>".encode())
            elif self.path == "/query/active-app":
                self._responder(200, f'<active-app><app id="{estado.activa}">{APPS.get(estado.activa, "")}'
                                     "</app></active-app>".encode())
            else:
                self._responder(404)

        def do_POST(self):
            if not self._antes():
                return
            estado.recibido.append(self.path)
            if self.path.startswith("/keypress/"):
                if estado.limitada:
                    return self._responder(403)
                k = self.path.removeprefix("/keypress/")
                if k == "PowerOn":
                    if estado.arranque:
                        estado._encendida_en = time.monotonic() + estado.arranque
                    else:
                        estado.modo = "PowerOn"
                elif k == "PowerOff":
                    estado.modo = "DisplayOff"
                    estado.apagada_del_todo = estado.muda_al_apagar
                elif k.startswith("Input") and not estado.ignora_entradas:
                    estado.activa = roku.id_de_entrada(k)
                return self._responder(200)
            if self.path.startswith("/launch/"):
                estado.activa = self.path.removeprefix("/launch/")
                return self._responder(200)
            self._responder(404)

    srv = ThreadingHTTPServer(("127.0.0.1", 0), Manejador)
    srv.daemon_threads = True
    hilo = threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    hilo.start()
    _configurar({"ip": "127.0.0.1", "puerto": srv.server_address[1],
                 "entradas": {"pc": "InputHDMI2", "Consola": "InputHDMI1", "rara": "Lit_a"}})
    monkeypatch.setattr(tele, "PAUSA_S", 0.05)
    monkeypatch.setattr(tele, "ESPERA_CAMBIO_S", 1.0)
    monkeypatch.setattr(tele, "ESPERA_ENCENDER_S", 1.5)
    yield estado
    srv.shutdown()
    srv.server_close()


def _configurar(t):
    (memoria.carpeta() / "secretario.yml").write_text(yaml.safe_dump({"tele": t}), encoding="utf-8")


@pytest.fixture
def con():
    c = memoria.conectar()
    yield c
    c.close()


def _hacer(con, accion_id, **params):
    return piezas.acciones()[accion_id].ejecutar(con, params)


# ── las acciones aparecen como las demás ─────────────────────────────────────

def test_las_acciones_de_la_tele_se_descubren_y_sus_niveles_estan_decididos():
    a = piezas.acciones()
    assert {"tele_estado", "tele_encender", "tele_apagar", "tele_entrada", "tele_app"} <= set(a)
    assert a["tele_estado"].riesgo == "lectura" and piezas.nivel(a["tele_estado"]) == "auto"
    for i in ("tele_encender", "tele_apagar", "tele_entrada", "tele_app"):
        assert a[i].riesgo == "reversible" and piezas.nivel(a[i]) == "ask", i


def test_encender_en_ask_pide_permiso_y_no_manda_nada_a_la_tele(con, falsa):
    r = herramientas.usar_accion(con, piezas.acciones()["tele_encender"], {"entrada": "pc"})
    assert r["hecho"] is False and r["solicitud"]
    assert falsa.recibido == []


# ── sin configurar ───────────────────────────────────────────────────────────

def test_sin_ip_configurada_dice_como_configurarla(con):
    for accion in ("tele_estado", "tele_encender", "tele_apagar"):
        with pytest.raises(roku.TeleError, match="falta su IP") as e:
            _hacer(con, accion)
        assert "tele:\n  ip:" in str(e.value)


def test_una_ip_que_no_es_de_casa_no_recibe_teclas(con):
    _configurar({"ip": "8.8.8.8"})
    with pytest.raises(roku.TeleError, match="red de casa"):
        _hacer(con, "tele_estado")
    _configurar({"ip": "la-tele"})
    with pytest.raises(roku.TeleError, match="no es una IP"):
        _hacer(con, "tele_estado")


# ── estado ───────────────────────────────────────────────────────────────────

def test_el_estado_dice_encendida_modelo_nombre_y_que_se_ve(con, falsa):
    r = _hacer(con, "tele_estado")
    assert r.startswith("tele encendida")
    assert "Tele del cuarto · TCL 55S455" in r and "se ve: HDMI 1" in r
    assert "pc=InputHDMI2" in r and "consola=InputHDMI1" in r
    assert "rara" not in r          # una entrada que no es una entrada no se acepta
    assert falsa.recibido == []     # mirar no manda ninguna tecla


@pytest.mark.parametrize("modo", ["DisplayOff", "Ready", "Headless", "PowerOff"])
def test_en_espera_lo_dice_con_su_modo(con, falsa, modo):
    falsa.modo = modo
    assert _hacer(con, "tele_estado").startswith(f"tele en espera ({modo})")


# ── encender ─────────────────────────────────────────────────────────────────

def test_encender_espera_a_ver_power_on_y_pone_la_entrada_pedida(con, falsa):
    falsa.modo, falsa.arranque = "DisplayOff", 0.3
    assert _hacer(con, "tele_encender", entrada="PC") == "tele encendida y en HDMI 2"
    assert falsa.recibido == ["/keypress/PowerOn", "/keypress/InputHDMI2"]
    assert falsa.modo == "PowerOn"


def test_encender_sin_entrada_no_cambia_de_entrada(con, falsa):
    falsa.modo = "Ready"
    assert _hacer(con, "tele_encender") == "tele encendida"
    assert falsa.recibido == ["/keypress/PowerOn"]


def test_si_tras_power_on_sigue_en_espera_no_dice_que_la_encendio(con, falsa):
    falsa.modo, falsa.arranque = "DisplayOff", 30
    with pytest.raises(roku.TeleError, match="Fast TV Start"):
        _hacer(con, "tele_encender")


def test_una_entrada_desconocida_se_rechaza_antes_de_encender(con, falsa):
    falsa.modo = "DisplayOff"
    with pytest.raises(roku.TeleError, match="no conozco la entrada «cocina»"):
        _hacer(con, "tele_encender", entrada="cocina")
    assert falsa.recibido == []


# ── apagar ───────────────────────────────────────────────────────────────────

def test_apagar_comprueba_que_queda_en_espera(con, falsa):
    assert _hacer(con, "tele_apagar") == "tele apagada (DisplayOff)"
    assert falsa.recibido == ["/keypress/PowerOff"]


def test_sin_fast_tv_start_apagada_deja_de_contestar_y_eso_cuenta_como_apagada(con, falsa):
    falsa.muda_al_apagar = True
    assert _hacer(con, "tele_apagar") == "tele apagada (ya no contesta en la red)"


# ── entrada ──────────────────────────────────────────────────────────────────

def test_cambia_de_entrada_por_nombre_amigable_y_lo_comprueba(con, falsa):
    assert _hacer(con, "tele_entrada", entrada="pc") == "tele en HDMI 2"
    assert _hacer(con, "tele_entrada", entrada="hdmi 1") == "tele en HDMI 1"
    assert _hacer(con, "tele_entrada", entrada="Antena") == "tele en Antena"
    assert falsa.recibido == ["/keypress/InputHDMI2", "/keypress/InputHDMI1", "/keypress/InputTuner"]


def test_si_la_tele_no_cambia_de_entrada_no_lo_da_por_hecho(con, falsa):
    falsa.ignora_entradas = True
    with pytest.raises(roku.TeleError, match="no cambió .*HDMI 1"):
        _hacer(con, "tele_entrada", entrada="pc")


def test_con_la_tele_en_espera_cambiar_de_entrada_pide_encenderla(con, falsa):
    falsa.modo = "DisplayOff"
    with pytest.raises(roku.TeleError, match="tele_encender"):
        _hacer(con, "tele_entrada", entrada="pc")
    assert falsa.recibido == []


def test_control_por_apps_en_limitado_dice_que_ajuste_cambiar(con, falsa):
    falsa.limitada = True
    with pytest.raises(roku.TeleError, match="403.*Control por apps móviles.*Habilitado"):
        _hacer(con, "tele_entrada", entrada="pc")


# ── apps ─────────────────────────────────────────────────────────────────────

def test_abre_una_app_por_su_nombre_resolviendola_con_la_lista_de_la_tele(con, falsa):
    assert _hacer(con, "tele_app", app="youtube") == "YouTube abierta en la tele"
    assert _hacer(con, "tele_app", app="spotify") == "Spotify Music abierta en la tele"
    assert falsa.recibido == ["/launch/837", "/launch/22297"]


def test_una_app_que_no_esta_dice_cuales_hay(con, falsa):
    with pytest.raises(roku.TeleError, match="no hay ninguna app «Disney».*Netflix"):
        _hacer(con, "tele_app", app="Disney")
    assert falsa.recibido == []


def test_un_nombre_que_casa_con_varias_pregunta_cual(con, falsa):
    with pytest.raises(roku.TeleError, match="di cuál"):
        _hacer(con, "tele_app", app="hdmi")
    assert falsa.recibido == []


# ── la red ───────────────────────────────────────────────────────────────────

def test_una_tele_que_tarda_mas_que_el_timeout_se_da_por_muda(con, falsa, monkeypatch):
    monkeypatch.setattr(roku, "TIMEOUT_S", 0.2)
    falsa.lenta = 1.0
    t0 = time.monotonic()
    with pytest.raises(roku.TeleError, match="no contesta en 127.0.0.1.*Control por apps móviles"):
        _hacer(con, "tele_estado")
    assert time.monotonic() - t0 < 0.9


def test_una_tele_que_no_existe_lo_dice_en_castellano(con):
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    puerto = s.getsockname()[1]
    s.close()                      # nadie escucha ahí
    _configurar({"ip": "127.0.0.1", "puerto": puerto})
    r = herramientas.usar_accion(con, piezas.acciones()["tele_estado"], {})
    assert r["hecho"] is False and "la tele no contesta en 127.0.0.1" in r["error"]


def test_una_tecla_fuera_de_la_lista_no_sale(falsa):
    t = tele.tele()
    for k in ("Lit_a", "Search", "PowerOn/../launch/12", "Enter"):
        with pytest.raises(roku.TeleError, match="no está permitida"):
            t.tecla(k)
    with pytest.raises(roku.TeleError, match="no es un id"):
        t.abrir_app("12?contentId=x")
    assert falsa.recibido == []


def test_el_proxy_del_entorno_no_se_usa_para_hablar_con_la_tele(con, falsa, monkeypatch):
    monkeypatch.setenv("http_proxy", "http://127.0.0.1:9")
    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:9")
    assert _hacer(con, "tele_estado").startswith("tele encendida")
