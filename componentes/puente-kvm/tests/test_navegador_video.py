"""El vídeo directo en un Chromium de verdad (C-0469): WebCodecs, el canvas y su reserva.

Contra el JetKVM falso, que manda H.264 por WebRTC como el aparato, y contra el
Mac simulado, que no da vídeo y se ve por imágenes. Lo que se mira es lo que
pasa en la página: qué superficie se ve, que el mando cae donde se ve, y que
cortar el directo cierra de verdad su WebSocket.
"""

import contextlib

import httpx
import pytest

from puente_kvm.jetkvm import JetKVM
from puente_kvm.simulador import Simulador

from .test_navegador import en_marcha, navegador, pagina  # noqa: F401  (las fijaciones)
from .test_video import FalsoAparte

playwright = pytest.importorskip("playwright.sync_api")

EN_VIDEO = "#directo-video:not([hidden])"
# Cuenta los WebSocket que abre la página, para ver cuáles siguen abiertos.
CONTAR_WS = """
(() => {
  const W = window.WebSocket;
  window.__ws = [];
  window.WebSocket = function (url, p) { const w = new W(url, p); window.__ws.push(w); return w; };
  window.WebSocket.prototype = W.prototype;
})();
"""
PANTALLAS_ABIERTAS = "window.__ws.filter((w) => w.url.endsWith('/ws/pantalla') && w.readyState <= 1).length"


@contextlib.contextmanager
def con_el_falso(pagina):  # noqa: F811
    falso = FalsoAparte()
    try:
        with en_marcha(JetKVM(falso.url, "secreta")) as base:
            try:
                yield base, falso.falso, falso
            finally:
                # Fuera de la página antes de parar: el directo de imágenes no
                # termina mientras se mira, y el puente esperaría por él.
                pagina.goto("about:blank")
    finally:
        falso.parar()


def test_con_el_jetkvm_la_pantalla_es_su_video_pintado_en_el_canvas(pagina):  # noqa: F811
    with con_el_falso(pagina) as (base, _, _):
        pagina.goto(base + "/panel")
        pagina.wait_for_selector(EN_VIDEO, timeout=15000)
        assert pagina.evaluate("PuenteDirecto.modo()") == "h264"
        assert pagina.evaluate("[document.querySelector('#directo-video').width, "
                               "document.querySelector('#directo-video').height]") == [1920, 1080]
        # Las imágenes se dejan de pedir: nadie las mira.
        assert pagina.locator("#directo").get_attribute("src") is None
        assert pagina.locator("#directo").is_hidden()
        # Pinta lo que se ve en el Mac (su fondo blanco, no un canvas vacío).
        claro = pagina.evaluate("""(() => { const c = document.querySelector('#directo-video');
            const d = c.getContext('2d').getImageData(900, 500, 20, 20).data;
            let s = 0; for (let i = 0; i < d.length; i += 4) s += d[i]; return s / (d.length / 4); })()""")
        assert claro > 200
    assert pagina.errores == []


def test_con_el_simulador_se_ve_por_imagenes_y_no_abre_el_video(pagina):  # noqa: F811
    pagina.add_init_script(CONTAR_WS)
    with en_marcha(Simulador(lineas=["x"])) as base:
        pagina.goto(base + "/panel")
        pagina.wait_for_timeout(800)
        assert pagina.evaluate("PuenteDirecto.modo()") == "mjpeg"
        assert pagina.locator("#directo-video").is_hidden()
        assert "/api/pantalla.mjpg" in pagina.locator("#directo").get_attribute("src")
        assert pagina.evaluate("window.__ws.filter((w) => w.url.endsWith('/ws/pantalla')).length") == 0
    assert pagina.errores == []


# Las tres van con `if`: también corren en about:blank, donde no hay WebCodecs.
ROMPER_DECODIFICADOR = """
if (window.VideoDecoder) (() => {
  const Original = window.VideoDecoder;
  window.VideoDecoder = class extends Original {
    constructor(init) { super(init); this.__error = init.error; }
    decode() { setTimeout(() => this.__error(new DOMException('roto a propósito', 'EncodingError'))); }
  };
})();
"""


@pytest.mark.parametrize("romper", [ROMPER_DECODIFICADOR, "delete window.VideoDecoder;",
                                    "if (window.VideoDecoder) VideoDecoder.isConfigSupported = async () => ({ supported: false });"],
                         ids=["decodificador-que-falla", "sin-webcodecs", "codec-que-no-sabe"])
def test_si_el_video_no_se_puede_pintar_vuelve_a_las_imagenes(pagina, romper):  # noqa: F811
    pagina.add_init_script(romper)
    with con_el_falso(pagina) as (base, _, _):
        pagina.goto(base + "/panel")
        pagina.wait_for_timeout(2500)
        assert pagina.evaluate("PuenteDirecto.modo()") == "mjpeg"
        assert pagina.locator("#directo-video").is_hidden() and pagina.locator("#directo").is_visible()
        assert "/api/pantalla.mjpg" in pagina.locator("#directo").get_attribute("src")
        # Y la imagen llega: el directo de imágenes sigue vivo detrás.
        pagina.wait_for_function("document.querySelector('#directo').naturalWidth > 0", timeout=10000)
    assert pagina.errores == []


def test_cortar_cierra_el_websocket_del_video_y_reanudar_lo_vuelve_a_abrir(pagina):  # noqa: F811
    pagina.add_init_script(CONTAR_WS)
    with con_el_falso(pagina) as (base, _, _):
        pagina.goto(base + "/panel")
        pagina.wait_for_selector(EN_VIDEO, timeout=15000)
        assert pagina.evaluate(PANTALLAS_ABIERTAS) == 1
        # Lo que hace la página antes de reiniciar el puente: nada abierto contra él.
        pagina.evaluate("PuenteUI.cortar()")
        pagina.wait_for_function(f"{PANTALLAS_ABIERTAS} === 0", timeout=5000)
        pagina.wait_for_timeout(500)
        assert pagina.evaluate(PANTALLAS_ABIERTAS) == 0
        pagina.evaluate("PuenteUI.reanudar()")
        pagina.wait_for_function(f"{PANTALLAS_ABIERTAS} === 1", timeout=5000)
        assert pagina.evaluate("PuenteDirecto.modo()") == "h264"
    assert pagina.errores == []


def test_el_mando_sobre_el_canvas_llega_al_aparato_donde_se_ve(pagina):  # noqa: F811
    with con_el_falso(pagina) as (base, falso, _):
        sim = falso.sim
        sim.editor.lineas, sim.editor.cursor = [""], (0, 0)
        pagina.goto(base + "/panel")
        pagina.wait_for_selector(EN_VIDEO, timeout=15000)
        pagina.click("#mando-usar")
        r = pagina.locator("#directo-video").bounding_box()
        pagina.mouse.click(r["x"] + r["width"] * 0.5, r["y"] + r["height"] * 0.5)
        pagina.keyboard.type("hola")
        pagina.wait_for_timeout(500)
        assert "hola" in "".join(sim.editor.lineas)
        # El último punto de un movimiento llega siempre, aunque la mano vaya rápida.
        x, y = r["x"] + r["width"] * 0.8, r["y"] + r["height"] * 0.3
        pagina.mouse.move(x, y, steps=8)
        pagina.wait_for_timeout(400)
        esperado = (round((x - r["x"]) / r["width"] * 1920), round((y - r["y"]) / r["height"] * 1080))
        assert abs(sim.puntero[0] - esperado[0]) <= 2 and abs(sim.puntero[1] - esperado[1]) <= 2
        # Y la rueda, sobre el canvas.
        sim.editor.lineas = [f"línea {i}" for i in range(200)]
        sim.editor.arriba = 0
        pagina.mouse.wheel(0, 300)
        pagina.wait_for_timeout(400)
        assert sim.editor.arriba > 0
    assert pagina.errores == []


def test_con_el_video_el_zoom_llega_al_tamano_real_y_el_clic_cae_donde_se_ve(pagina):  # noqa: F811
    with con_el_falso(pagina) as (base, falso, _):
        pagina.goto(base + "/panel")
        pagina.wait_for_selector(EN_VIDEO, timeout=15000)
        pagina.click("#ampliar")
        for _ in range(12):
            if pagina.locator("#zoom-valor").inner_text().strip() == "100 %":
                break
            pagina.click("#zoom-mas")
        assert pagina.evaluate("document.querySelector('#directo-video').clientWidth") == 1920
        # El vídeo ya llega entero: no se piden imágenes a su tamaño real por detrás.
        assert pagina.locator("#directo").get_attribute("src") is None
        pagina.click("#mando-usar")
        pagina.evaluate("document.querySelector('#pantalla').scrollLeft = 500")
        r = pagina.locator("#directo-video").bounding_box()
        pagina.mouse.click(400, 300)
        pagina.wait_for_timeout(400)
        px, py = falso.sim.puntero
        assert abs(px - round(400 - r["x"])) <= 2 and abs(py - round(300 - r["y"])) <= 2
    assert pagina.errores == []


def test_con_medir_la_pantalla_dice_cuantos_fotogramas_pinta_y_el_retraso_del_puntero(pagina):  # noqa: F811
    with con_el_falso(pagina) as (base, _, _):
        pagina.goto(base + "/panel?medir=1")
        pagina.wait_for_selector(EN_VIDEO, timeout=15000)
        pagina.click("#mando-usar")
        r = pagina.locator("#directo-video").bounding_box()
        for i in range(8):
            pagina.mouse.move(r["x"] + r["width"] * (0.3 + i * 0.07), r["y"] + r["height"] * 0.5, steps=2)
            pagina.wait_for_timeout(350)
        texto = pagina.locator("#medida").inner_text()
        assert "vídeo H.264" in texto and "fotogramas/s" in texto
        assert "(0)" not in texto  # midió algún movimiento del puntero
    assert pagina.errores == []


def _reconectar(base: str) -> dict:
    """«Reconectar el aparato» de Ajustes, como lo pulsa la persona."""
    return httpx.post(base + "/api/reconectar", headers={"Origin": base}, timeout=30).json()


OSCURA = """(() => { const i = document.querySelector('#directo'); if (!i.naturalWidth) return false;
  const c = document.createElement('canvas'); c.width = 4; c.height = 4;
  const x = c.getContext('2d'); x.drawImage(i, 40, 40, 4, 4, 0, 0, 4, 4);
  const d = x.getImageData(0, 0, 1, 1).data; return d[0] + d[1] + d[2] < 150; })()"""


def test_si_el_aparato_se_va_se_ve_por_que_y_al_volver_otra_vez_el_video(pagina):  # noqa: F811
    # Con el canvas, el último fotograma se quedaba como si fuera el directo.
    pagina.add_init_script(CONTAR_WS)
    with con_el_falso(pagina) as (base, _, aparte):
        pagina.goto(base + "/panel")
        pagina.wait_for_selector(EN_VIDEO, timeout=15000)
        aparte.apagar()
        assert _reconectar(base)["error_conexion"]
        # Las imágenes, que dicen «Sin imagen del aparato» (un fotograma oscuro con el motivo).
        pagina.wait_for_selector("#directo:not([hidden])", timeout=5000)
        assert pagina.locator("#directo-video").is_hidden()
        pagina.wait_for_function(OSCURA, timeout=10000)
        # Sin rendirse: el vídeo sigue abierto, esperando al aparato.
        assert pagina.evaluate(PANTALLAS_ABIERTAS) == 1
        aparte.volver()
        assert not _reconectar(base)["error_conexion"]
        pagina.wait_for_selector(EN_VIDEO, timeout=15000)
        assert pagina.evaluate("PuenteDirecto.modo()") == "h264"
        assert pagina.locator("#directo").get_attribute("src") is None
    assert [e for e in pagina.errores if "status of 503" not in e] == []


def test_cambiar_de_aparato_no_deja_la_pantalla_en_imagenes_para_siempre(pagina, monkeypatch):  # noqa: F811
    monkeypatch.setenv("JETKVM_CLAVE", "secreta")
    pagina.add_init_script(CONTAR_WS)
    with con_el_falso(pagina) as (base, _, aparte):
        pagina.goto(base + "/panel")
        pagina.wait_for_selector(EN_VIDEO, timeout=15000)
        # Otro aparato (el mismo falso por otro nombre): el puente cierra el vídeo del de antes.
        otro = aparte.url.replace("127.0.0.1", "localhost")
        r = httpx.post(base + "/api/ajustes", headers={"Origin": base}, timeout=30,
                       json={"dispositivo": {"tipo": "jetkvm", "url": otro}})
        assert r.status_code == 200 and not r.json()["error_conexion"]
        pagina.wait_for_function(
            "window.__ws.filter((w) => w.url.endsWith('/ws/pantalla')).length >= 2", timeout=15000)
        pagina.wait_for_selector(EN_VIDEO, timeout=15000)
        assert pagina.evaluate(PANTALLAS_ABIERTAS) == 1
    assert pagina.errores == []


FALLA_A_MEDIAS = """
if (window.VideoDecoder) (() => {
  const Original = window.VideoDecoder;
  window.VideoDecoder = class extends Original {
    constructor(init) { super(init); this.__error = init.error; this.__n = 0; }
    decode(c) { if (++this.__n > 40) { this.__error(new DOMException('roto a medias', 'EncodingError')); return; }
                return super.decode(c); }
  };
})();
"""


def test_si_el_decodificador_falla_con_el_video_ya_pintado_vuelve_a_las_imagenes(pagina):  # noqa: F811
    pagina.add_init_script(FALLA_A_MEDIAS)
    with con_el_falso(pagina) as (base, _, _):
        pagina.goto(base + "/panel")
        pagina.wait_for_selector(EN_VIDEO, timeout=15000)
        pagina.wait_for_selector("#directo:not([hidden])", timeout=10000)
        assert pagina.evaluate("PuenteDirecto.modo()") == "mjpeg"
        assert "/api/pantalla.mjpg" in pagina.locator("#directo").get_attribute("src")
        pagina.wait_for_function("document.querySelector('#directo').naturalWidth > 0", timeout=10000)
    assert pagina.errores == []


def test_si_el_mac_cambia_de_resolucion_el_video_se_reconfigura_y_sigue(pagina):  # noqa: F811
    # Otro SPS a mitad: el puente vuelve a mandar el códec y la página reconfigura.
    with con_el_falso(pagina) as (base, falso, _):
        pagina.goto(base + "/panel")
        pagina.wait_for_selector(EN_VIDEO, timeout=15000)
        falso.tamano = (1280, 720)
        pagina.wait_for_function("document.querySelector('#directo-video').width === 1280", timeout=10000)
        pagina.wait_for_timeout(500)
        assert pagina.evaluate("PuenteDirecto.modo()") == "h264"
        assert pagina.evaluate("document.querySelector('#directo-video').height") == 720
    assert pagina.errores == []
