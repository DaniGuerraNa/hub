"""El JavaScript de las páginas, ejecutado en un Chromium de verdad.

Un 200 no dice nada de un guion que revienta al arrancar: la página se sirve
perfecta y el navegador falla en silencio. Aquí se cargan las páginas con el
puente en marcha (Mac simulado) y se mira que no haya errores y que lo que
hace el guion se vea. Se salta si Playwright no tiene su Chromium instalado.
"""

import contextlib
import threading
import time

import httpx
import pytest
import uvicorn

from puente_kvm import config, muestras
from puente_kvm.app import crear_app
from puente_kvm.simulador import Simulador

playwright = pytest.importorskip("playwright.sync_api")


@pytest.fixture(scope="module")
def navegador():
    with playwright.sync_playwright() as pw:
        try:
            nav = pw.chromium.launch()
        except Exception as e:  # sin el Chromium de Playwright: `uv run playwright install chromium`
            pytest.skip(f"sin Chromium para Playwright: {e}")
        yield nav
        nav.close()


@contextlib.contextmanager
def en_marcha(dispositivo):
    base = f"127.0.0.1:{config.PUERTO}"
    servidor = uvicorn.Server(uvicorn.Config(crear_app(dispositivo, hosts={base}), host="127.0.0.1",
                                             port=config.PUERTO, log_level="error"))
    hilo = threading.Thread(target=servidor.run, daemon=True)
    hilo.start()
    for _ in range(100):
        with contextlib.suppress(httpx.HTTPError):
            httpx.get(f"http://{base}/api/estado", timeout=1)
            break
        time.sleep(0.05)
    try:
        yield f"http://{base}"
    finally:
        servidor.should_exit = True
        hilo.join(5)


@pytest.fixture
def pagina(navegador):
    contexto = navegador.new_context(viewport={"width": 1280, "height": 860})
    p = contexto.new_page()
    errores = []
    p.on("pageerror", lambda e: errores.append(str(e)))
    p.on("console", lambda m: m.type == "error" and errores.append(m.text))
    p.errores = errores
    yield p
    contexto.close()


@pytest.mark.parametrize("ruta", ["/", "/panel", "/claude", "/ajustes"])
def test_las_paginas_cargan_sin_errores_de_javascript(pagina, ruta):
    with en_marcha(Simulador(lineas=muestras.procedimiento(80))) as base:
        pagina.goto(base + ruta)
        pagina.wait_for_timeout(800)
    assert pagina.errores == []


@contextlib.contextmanager
def otra_web(carpeta, html: str):
    """Otra web en esta máquina (otro origen: `localhost` y otro puerto), servida de verdad.

    Tiene que ser local: Chrome ya impide por su cuenta que una web pública
    enmarque 127.0.0.1, y la prueba pasaría sin la cabecera (medido).
    """
    import functools
    import http.server

    from .conftest import puerto_libre

    (carpeta / "marco.html").write_text(html)
    puerto = puerto_libre()
    srv = http.server.ThreadingHTTPServer(
        ("127.0.0.1", puerto), functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(carpeta)))
    srv.RequestHandlerClass.log_message = lambda *a: None
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        yield f"http://localhost:{puerto}/marco.html"
    finally:
        srv.shutdown()


def test_el_espacio_de_trabajo_enmarca_el_panel_aunque_otras_webs_no_puedan(pagina, tmp_path):
    with en_marcha(Simulador(lineas=["x"])) as base:
        pagina.goto(base + "/")
        pagina.wait_for_timeout(800)
        marco = pagina.frame(name="marco")
        assert marco is not None and marco.locator("#boton-dar").count() == 1
        # Otra web no puede enmarcarlo: un clic robado sobre «Dar el control» se saltaría la puerta.
        with otra_web(tmp_path, f'<iframe name="ajeno" src="{base}/panel"></iframe>') as url:
            pagina.goto(url, wait_until="domcontentloaded")
            pagina.wait_for_timeout(1500)
            ajeno = pagina.frame(name="ajeno")
            assert ajeno is None or ajeno.locator("#boton-dar").count() == 0


def test_dos_avisos_seguidos_no_se_amontonan(pagina):
    with en_marcha(Simulador(lineas=["x"])) as base:
        pagina.goto(base + "/panel")
        pagina.evaluate("PuenteUI.fugaz('uno'); PuenteUI.fugaz('dos')")
        assert pagina.locator(".fugaz").count() == 1
        assert pagina.locator(".fugaz").inner_text() == "dos"


def test_sin_aparato_el_directo_carga_y_los_ajustes_dicen_por_que_no_hay_imagen(pagina):
    from puente_kvm.jetkvm import JetKVM
    with en_marcha(JetKVM("http://127.0.0.1:1", "")) as base:
        pagina.goto(base + "/panel", wait_until="load", timeout=8000)  # antes no terminaba nunca
        assert "no responde" in pagina.locator(".aviso.riesgo").inner_text()
        pagina.goto(base + "/ajustes")
        pagina.wait_for_timeout(800)
        assert pagina.locator("#sin-imagen").is_visible()
        assert not pagina.locator("#pantalla-ajustes").is_visible()


def test_la_consulta_de_la_huella_lleva_el_objeto_que_se_escriba(pagina):
    from puente_kvm import lecturas
    l = lecturas.nueva("usp_Prueba")
    with en_marcha(Simulador(lineas=["x"])) as base:
        pagina.goto(base + f"/lecturas/{l.id}")
        pagina.locator("details summary").first.click()
        pagina.fill("#objeto", "ventas.usp_Otro")
        assert "OBJECT_ID('ventas.usp_Otro')" in pagina.locator("pre.consulta").first.inner_text()


@pytest.fixture
def con_claude_falso(tmp_path, monkeypatch):
    """Una casa de mentira con un `claude` de mentira, y un servidor de tmux aparte."""
    import subprocess
    import uuid

    from .test_conversaciones import claude_falso
    casa = tmp_path / "casa"
    claude_falso(casa / ".local" / "bin")
    socket = f"puente-pruebas-{uuid.uuid4().hex[:6]}"
    monkeypatch.setenv("HOME", str(casa))
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    monkeypatch.setenv("PUENTE_TMUX_SOCKET", socket)
    monkeypatch.delenv("PUENTE_TERMINAL_ORDEN", raising=False)
    yield
    subprocess.run(["tmux", "-L", socket, "kill-server"], capture_output=True)


def esperar_conversacion(pagina):
    pagina.wait_for_function("document.querySelector('#conv-nombre').textContent.startsWith('Conversación del')",
                             timeout=10000)


def test_el_menu_de_conversaciones_se_maneja_con_teclado_y_cabe_en_el_telefono(navegador, con_claude_falso):
    contexto = navegador.new_context(viewport={"width": 390, "height": 844})
    p = contexto.new_page()
    errores = []
    p.on("pageerror", lambda e: errores.append(str(e)))
    with en_marcha(Simulador(lineas=["x"])) as base:
        p.goto(base + "/")
        esperar_conversacion(p)
        assert p.locator("#placa-modelo").inner_text().startswith("Fable 5.2 · Claude Code 2.1.322")
        p.focus("#conv-boton")
        p.keyboard.press("Enter")
        p.wait_for_selector("#conv-menu:not([hidden])")
        caja = p.locator("#conv-menu").bounding_box()
        assert caja["x"] >= 0 and caja["x"] + caja["width"] <= 390
        assert p.evaluate("document.activeElement.closest('#conv-menu') !== null")  # el foco entra en el menú
        p.keyboard.press("Escape")
        assert p.locator("#conv-menu").is_hidden()
        assert p.evaluate("document.activeElement.id") == "conv-boton"
    contexto.close()
    assert errores == []


def test_una_conversacion_nueva_desde_la_pantalla_pide_nombre_y_pasa_a_ser_la_abierta(pagina, con_claude_falso):
    from puente_kvm import conversaciones
    with en_marcha(Simulador(lineas=["x"])) as base:
        pagina.goto(base + "/")
        esperar_conversacion(pagina)
        primera = pagina.locator("#conv-nombre").inner_text()
        pagina.click("[data-reiniciar-claude]")
        campo = pagina.locator(".velo input")
        assert campo.input_value().startswith("Conversación del ")
        campo.fill("Revisar el rendimiento")
        pagina.keyboard.press("Enter")
        pagina.wait_for_function("document.querySelector('#conv-nombre').textContent === 'Revisar el rendimiento'",
                                 timeout=10000)
        nombres = [c.nombre for c in conversaciones.todas()]
        assert nombres[0] == "Revisar el rendimiento" and primera in nombres
    assert pagina.errores == []


def test_el_modelo_se_elige_en_ajustes(pagina):
    from puente_kvm import config
    with en_marcha(Simulador(lineas=["x"])) as base:
        pagina.goto(base + "/ajustes")
        assert pagina.locator("#modelo").input_value() == "claude-fable-5-2"
        pagina.select_option("#modelo", "claude-opus-5-5")
        pagina.click("button[type=submit]")
        pagina.wait_for_timeout(800)
        assert config.leer_ajustes()["claude"]["modelo"] == "claude-opus-5-5"
    assert pagina.errores == []


def test_sin_pedir_permisos_y_el_teclado_espanol_se_eligen_en_ajustes(pagina):
    # La casilla viaja como verdadero/falso, no como el texto «on».
    from puente_kvm import config
    with en_marcha(Simulador(lineas=["x"])) as base:
        pagina.goto(base + "/ajustes")
        assert not pagina.locator("#saltar_permisos").is_checked()
        assert "Español - ISO" in pagina.locator("#distribucion").inner_text()
        pagina.check("#saltar_permisos")
        pagina.select_option("#distribucion", "mac-es")
        pagina.click("button[type=submit]")
        pagina.wait_for_timeout(800)
        ajustes = config.leer_ajustes()
        assert ajustes["claude"]["saltar_permisos"] is True
        assert ajustes["perfil"]["distribucion"] == "mac-es"
    assert pagina.errores == []


def test_la_persona_usa_el_mac_desde_la_pantalla_con_su_teclado(pagina):
    # Sin la web del JetKVM: un clic en «Usar el Mac desde aquí», otro en la
    # imagen, y lo tecleado llega al Mac. Un clic fuera lo suelta.
    sim = Simulador(lineas=[""])
    with en_marcha(sim) as base:
        pagina.goto(base + "/panel")
        pagina.click("#mando-usar")
        assert "usando" in pagina.locator("#pantalla").get_attribute("class")
        pagina.click("#directo", position={"x": 200, "y": 150})
        pagina.keyboard.type("hola")
        pagina.keyboard.press("Shift+KeyA")
        pagina.wait_for_timeout(400)
        assert "holaA" in "".join(sim.editor.lineas)
        pagina.click("h2")  # fuera de la imagen
        assert "usando" not in (pagina.locator("#pantalla").get_attribute("class") or "")
        pagina.keyboard.type("zz")
        pagina.wait_for_timeout(300)
        assert "zz" not in "".join(sim.editor.lineas)
    assert pagina.errores == []
