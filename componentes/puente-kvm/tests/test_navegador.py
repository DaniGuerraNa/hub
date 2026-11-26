"""El JavaScript de las páginas, ejecutado en un Chromium de verdad.

Un 200 no dice nada de un guion que revienta al arrancar: la página se sirve
perfecta y el navegador falla en silencio. Aquí se cargan las páginas con el
puente en marcha (Mac simulado) y se mira que no haya errores y que lo que
hace el guion se vea. Se salta si Playwright no tiene su Chromium instalado.
"""

import asyncio
import contextlib
import re
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
def en_marcha(dispositivo, apps: list | None = None):
    """El puente servido de verdad. En `apps`, la aplicación: para la prueba que
    hace como si se reiniciara (le cambia el `Puente` por uno nuevo)."""
    base = f"127.0.0.1:{config.PUERTO}"
    app = crear_app(dispositivo, hosts={base})
    if apps is not None:
        apps.append(app)
    servidor = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=config.PUERTO, log_level="error"))
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
        assert "no responde" in pagina.locator("main .aviso.riesgo").inner_text()
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


def test_una_medida_verificada_sale_en_ajustes_y_la_persona_la_usa_con_un_clic(pagina):
    # C-0481: la verificación no la activa; la persona pulsa «Usar». Y en el panel,
    # junto a «Pegar texto», sale con el mismo nombre.
    from puente_kvm import teclados

    from .ayuda import medida_verificada
    b = medida_verificada()
    nombre = teclados.nombre_visible(teclados.resumen(b))
    assert re.fullmatch(r"Medida: Latinoamericano \(\d{1,2}-[a-z]{3}\)", nombre)
    with en_marcha(Simulador(lineas=["x"])) as base:
        pagina.goto(base + "/ajustes")
        assert nombre in pagina.locator("#distribucion").inner_text()
        assert pagina.locator("#reservadas").input_value() == "alt+x"
        fila = pagina.locator("#teclados-medidos li", has_text=nombre)
        assert "verificada" in fila.inner_text()
        fila.locator("[data-usar-teclado]").click()
        pagina.wait_for_selector("#teclados-medidos li:has-text('en uso')")
        assert config.leer_ajustes()["perfil"]["distribucion"] == b["id"]
        assert pagina.locator("#distribucion").input_value() == b["id"]
        pagina.goto(base + "/panel")
        opcion = pagina.locator("#mando-teclado option:checked")
        assert opcion.inner_text() == nombre and opcion.get_attribute("value") == b["id"]
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


def test_el_teclado_del_mac_se_elige_junto_a_pegar_y_lo_pegado_llega_con_sus_acentos(navegador):
    # «No reconoce acentos, me pone caracteres feos» (20-nov): «Pegar texto»
    # tecleaba con la distribución de Ajustes, que nadie había cambiado.
    contexto = navegador.new_context(viewport={"width": 1280, "height": 860},
                                     permissions=["clipboard-read", "clipboard-write"])
    p = contexto.new_page()
    errores = []
    p.on("pageerror", lambda e: errores.append(str(e)))
    sim = Simulador(lineas=[""], fuente="mac-es")  # el Mac, en español
    texto = "¿Qué tal? “Listo” — ñandú, pingüino"
    with en_marcha(sim) as base:
        p.goto(base + "/panel")
        assert p.locator("#mando-teclado-caja").is_hidden()
        p.click("#mando-usar")
        p.click("#directo", position={"x": 200, "y": 150})
        # Primero como estaba: «U.S.» en un Mac español escribe otra cosa.
        p.evaluate("t => navigator.clipboard.writeText(t)", texto)
        p.click("#mando-pegar")
        p.wait_for_function("document.querySelector('.fugaz')?.textContent.includes('«U.S.»')")
        mal = "".join(sim.editor.lineas)
        assert mal and mal != texto and "€" in mal  # ⌥E en español es «€»: los «caracteres feos»
        sim.editor.lineas = [""]
        sim.editor.cursor = (0, 0)
        p.select_option("#mando-teclado", "mac-es")
        p.wait_for_function("document.querySelector('.fugaz')?.textContent.includes('Español - ISO')")
        assert config.leer_ajustes()["perfil"]["distribucion"] == "mac-es"
        p.click("#mando-pegar")
        p.wait_for_function("document.querySelector('.fugaz')?.textContent.includes('«Español - ISO»')")
        assert "".join(sim.editor.lineas) == texto
        assert p.locator("#pantalla.usando").count() == 1  # pegar no suelta el Mac
        p.evaluate("navigator.clipboard.writeText('')")  # es de todo el navegador de las pruebas
    contexto.close()
    assert errores == []


def test_el_jiggler_se_enciende_con_un_boton_y_despertar_dice_si_volvio_la_imagen(pagina):
    sim = Simulador(lineas=[""])
    with en_marcha(sim) as base:
        pagina.goto(base + "/panel")
        boton = pagina.locator("#jiggler")
        assert boton.text_content() == "Jiggler: apagado" and boton.get_attribute("aria-pressed") == "false"
        boton.click()
        pagina.wait_for_function("document.querySelector('#jiggler').getAttribute('aria-pressed') === 'true'")
        assert boton.text_content() == "Jiggler: Frecuente, cada 30 s"
        assert "sigue aunque cierres el puente" in pagina.locator(".fugaz").text_content()
        assert sim._jiggler["encendido"] is True
        # Despertarlo mientras se usa el Mac: la espera no echa a la persona del Mac.
        despertar = sim.despertar

        async def despacio(tope=8.0):
            await asyncio.sleep(1.5)
            return await despertar(tope)

        sim.despertar = despacio
        sim.dormido = True
        pagina.click("#mando-usar")
        pagina.click("#directo", position={"x": 200, "y": 150})
        pagina.click("[data-despertar]")
        for x in range(220, 420, 20):
            pagina.mouse.move(x, 300)
            pagina.wait_for_timeout(60)
        pagina.wait_for_function("document.querySelector('.fugaz')?.textContent.includes('El Mac despertó')")
        assert sim.despertado == 1
        assert pagina.locator("#pantalla.usando").count() == 1
        boton.click()
        pagina.wait_for_function("document.querySelector('#jiggler').getAttribute('aria-pressed') === 'false'")
    assert pagina.errores == []


def test_copiar_diagnostico_deja_en_el_portapapeles_el_informe_sin_la_direccion(navegador):
    # Para pegarlo en una incidencia del hub (C-0468), que es pública.
    contexto = navegador.new_context(viewport={"width": 1280, "height": 860},
                                     permissions=["clipboard-read", "clipboard-write"])
    p = contexto.new_page()
    errores = []
    p.on("pageerror", lambda e: errores.append(str(e)))
    with en_marcha(Simulador(lineas=["x"])) as base:
        ajustes = config.leer_ajustes()
        ajustes["dispositivo"].update({"tipo": "jetkvm", "url": "http://192.168.1.77"})
        config.guardar_ajustes(ajustes)
        p.goto(base + "/ajustes")
        p.evaluate("navigator.clipboard.writeText('')")
        p.click("[data-copiar-diagnostico]")
        p.wait_for_function("document.querySelector('.fugaz')?.textContent.includes('Diagnóstico copiado')", timeout=20000)
        copiado = p.evaluate("navigator.clipboard.readText()")
        p.evaluate("navigator.clipboard.writeText('')")  # es de todo el navegador de las pruebas
    contexto.close()
    assert copiado.startswith("# Diagnóstico del puente KVM") and "192.168.1.77" not in copiado
    assert errores == []


def test_las_mediciones_se_descargan_se_apagan_y_se_borran_desde_ajustes(navegador, tmp_path):
    # C-0483: el .zip lo descarga la persona (un blob, con el Origin de esta web);
    # la casilla se guarda sola; borrar pregunta con el diálogo del puente.
    import io
    import zipfile

    from puente_kvm import mediciones
    contexto = navegador.new_context(viewport={"width": 1280, "height": 860}, accept_downloads=True)
    p = contexto.new_page()
    errores = []
    p.on("pageerror", lambda e: errores.append(str(e)))
    with en_marcha(Simulador(lineas=["x"])) as base:
        p.goto(base + "/ajustes")
        assert p.locator("#mediciones-activas").is_checked()
        assert "No guarda" in p.locator("#ajustes-mediciones + label + p").inner_text()
        assert p.locator("#mediciones-resumen").inner_text().startswith("Guardadas: 1 día, ")
        with p.expect_download() as descarga:
            p.click("[data-mediciones-preparar]")
        d = descarga.value
        assert re.fullmatch(r"mediciones-puente-\d{4}-\d{2}-\d{2}\.zip", d.suggested_filename)
        destino = tmp_path / d.suggested_filename
        d.save_as(destino)
        assert "LEEME.txt" in zipfile.ZipFile(io.BytesIO(destino.read_bytes())).namelist()
        p.uncheck("#mediciones-activas")
        p.wait_for_function("document.querySelector('.fugaz')?.textContent.includes('apagadas')")
        assert config.leer_ajustes()["mediciones"]["activas"] is False
        p.click("[data-mediciones-borrar]")
        p.click(".dialogo [data-no]")  # cancelar no borra
        assert mediciones.estado()["dias"] == 1
        p.click("[data-mediciones-borrar]")
        p.click(".dialogo [data-si]")
        p.wait_for_function("document.querySelector('#mediciones-resumen').textContent.startsWith('Aún no hay')")
        assert mediciones.estado()["dias"] == 0
    contexto.close()
    assert errores == []


def test_un_clic_en_el_mac_le_quita_el_teclado_a_la_terminal_de_claude(pagina, con_claude_falso):
    # Hablando con Claude y con el Mac en uso a la vez: el clic en la imagen
    # no movía el foco (el mousedown se cancela para no arrastrarla) y lo
    # tecleado seguía yendo a la terminal hasta pulsar «Pantalla grande» (20-nov).
    sim = Simulador(lineas=[""])
    with en_marcha(sim) as base:
        pagina.goto(base + "/")
        esperar_conversacion(pagina)
        marco = pagina.frame(name="marco")
        marco.click("#mando-usar")
        pagina.click("#terminal")
        assert pagina.evaluate("document.activeElement.classList.contains('xterm-helper-textarea')")
        marco.click("#directo", position={"x": 200, "y": 150})
        pagina.keyboard.type("hola")
        pagina.wait_for_timeout(400)
        assert "hola" in "".join(sim.editor.lineas)
    assert pagina.errores == []


def test_el_boton_de_reunion_graba_cuenta_el_tiempo_y_al_salir_dice_donde_queda(pagina):
    sim = Simulador(lineas=[""])
    with en_marcha(sim) as base:
        pagina.goto(base + "/panel")
        pagina.click("#mando-usar")
        pagina.click("#reunion")  # con el Mac en uso: no se lo quita
        pagina.wait_for_function("document.querySelector('#reunion').textContent.includes('Salí')", timeout=10000)
        assert "usando" in pagina.locator("#pantalla").get_attribute("class")
        assert sim.sonido
        assert pagina.locator("#reunion-placa").is_visible()
        pagina.wait_for_timeout(2200)
        assert pagina.locator("#reunion-placa").text_content().startswith("Grabando 0:0")
        assert "Tu voz no se graba" in pagina.locator("#reunion-aviso").text_content()
        pagina.click("#reunion")
        pagina.wait_for_function("document.querySelector('#reunion').textContent.includes('Estoy')", timeout=10000)
        aviso = pagina.locator("#reunion-aviso")
        # El Mac simulado no suena: se guarda igual, y se dice.
        assert "Reuniones la transcribe" in aviso.text_content() and "no llegó nada de sonido" in aviso.text_content()
        assert "riesgo" in aviso.get_attribute("class")
        assert not pagina.locator("#reunion-placa").is_visible() and not sim.sonido
    assert pagina.errores == []


def test_la_rueda_de_un_touchpad_cuenta_como_en_la_web_del_jetkvm(pagina):
    # Muchos eventos pequeños: cada uno es un paso (antes, uno cada 100 px: lentísima).
    sim = Simulador(lineas=[f"l{i}" for i in range(400)])
    with en_marcha(sim) as base:
        pagina.goto(base + "/panel")
        pagina.click("#mando-usar")
        pagina.hover("#directo")
        for _ in range(10):
            pagina.mouse.wheel(0, 20)
            pagina.wait_for_timeout(30)
        pagina.wait_for_timeout(400)
        assert sim.editor.arriba == 30  # diez pasos de tres líneas
        pagina.mouse.wheel(0, 300)  # una rueda rápida: tres de golpe
        pagina.wait_for_timeout(400)
        assert sim.editor.arriba == 39
    assert pagina.errores == []


def test_lo_seleccionado_en_la_terminal_de_claude_se_copia_y_ctrl_c_no_lo_interrumpe(navegador, con_claude_falso):
    # Con el ratón selecciona tmux (la rueda recorre su historial): lo copiado no
    # llegaba al portapapeles de la PC, y Ctrl+C le mandaba ^C a Claude (20-nov).
    import os
    import subprocess
    contexto = navegador.new_context(viewport={"width": 1280, "height": 860},
                                     permissions=["clipboard-read", "clipboard-write"])
    p = contexto.new_page()
    errores = []
    p.on("pageerror", lambda e: errores.append(str(e)))
    with en_marcha(Simulador(lineas=["x"])) as base:
        p.goto(base + "/")
        esperar_conversacion(p)
        # El portapapeles es del navegador entero: lo que dejó otra prueba no cuenta como copiado.
        p.evaluate("navigator.clipboard.writeText('')")
        # Texto conocido en la pantalla del panel (servidor de tmux de la prueba): el eco del tty.
        tmux = ["tmux", "-L", os.environ["PUENTE_TMUX_SOCKET"]]
        subprocess.run([*tmux, "send-keys", "-t", "puente-claude", "-l", "copiame esto"], check=True)
        p.wait_for_function("document.querySelector('.xterm-rows').textContent.includes('copiame esto')")
        fila = p.locator(".xterm-rows > div", has_text="copiame esto").first
        caja = fila.bounding_box()
        ancho = caja["width"] * len("copiame esto") / max(1, len(fila.text_content().rstrip()))
        y = caja["y"] + caja["height"] / 2
        p.mouse.move(caja["x"] + 1, y)
        p.mouse.down()
        p.mouse.move(caja["x"] + ancho - 2, y, steps=8)
        p.mouse.up()
        copiado = ""
        for _ in range(50):
            copiado = p.evaluate("navigator.clipboard.readText()")
            if copiado:
                break
            p.wait_for_timeout(100)
        assert copiado == "copiame esto"
        p.keyboard.press("Control+c")  # justo después de copiar: es copiar, no interrumpir
        p.wait_for_timeout(500)
        pantalla = subprocess.run([*tmux, "capture-pane", "-p", "-t", "puente-claude"], capture_output=True, text=True)
        assert "copiame esto" in pantalla.stdout and "^C" not in pantalla.stdout
        # Pasado el copiar, Ctrl+C vuelve a ser interrumpir.
        p.keyboard.press("x")
        p.keyboard.press("Control+c")
        p.wait_for_timeout(500)
        despues = subprocess.run([*tmux, "capture-pane", "-p", "-t", "puente-claude"], capture_output=True, text=True)
        assert despues.returncode != 0 or "^C" in despues.stdout  # le llegó (y aquí cierra la sesión de prueba)
    contexto.close()
    assert errores == []


def test_la_pantalla_grande_ocupa_la_ventana_y_esc_la_devuelve(pagina):
    # «Pantalla completa pero dentro de la ventana»: el Mac ocupa el navegador
    # entero (sin la cabecera ni la terminal), no el monitor.
    with en_marcha(Simulador(lineas=["x"])) as base:
        pagina.goto(base + "/")
        pagina.wait_for_timeout(800)
        marco = pagina.frame(name="marco")
        marco.click("#ampliar")
        # A lo que pasa, no a un tiempo fijo: con la máquina cargada, 400 ms no bastaban.
        pagina.wait_for_function("document.getElementById('marco').getBoundingClientRect().y === 0")
        assert not pagina.locator("#dock").is_visible()
        caja = pagina.locator("#marco").bounding_box()
        assert caja["x"] == 0 and caja["y"] == 0 and caja["width"] == 1280 and caja["height"] == 860
        img = marco.locator("#directo").bounding_box()
        assert img["width"] > 1200  # en la tarjeta de siempre, unos 520 px
        assert "ancho=1280" in marco.locator("#directo").get_attribute("src")
        marco.locator("body").press("Escape")
        pagina.wait_for_timeout(300)
        assert pagina.locator("#dock").is_visible()
        assert "ampliada" not in (marco.locator("#tarjeta-pantalla").get_attribute("class") or "")
    assert pagina.errores == []


def test_el_zoom_llega_al_tamano_real_y_el_clic_cae_donde_se_ve(pagina):
    sim = Simulador(lineas=["x"])
    with en_marcha(sim) as base:
        pagina.goto(base + "/panel")
        pagina.click("#ampliar")
        for _ in range(12):
            if pagina.locator("#zoom-valor").inner_text().strip() == "100 %":
                break
            pagina.click("#zoom-mas")
        assert pagina.locator("#zoom-valor").inner_text().strip() == "100 %"
        assert pagina.evaluate("document.querySelector('#directo').clientWidth") == 1920
        # A más de 1280 px en pantalla, la imagen se pide a su tamaño real: si no, se lee peor.
        pagina.wait_for_timeout(300)
        assert "ancho=1920" in pagina.locator("#directo").get_attribute("src")
        caja = pagina.locator("#pantalla")
        assert pagina.evaluate("(p) => p.scrollWidth > p.clientWidth", caja.element_handle())
        # Usando el Mac, con la imagen desplazada: el clic va al píxel que se ve.
        pagina.click("#mando-usar")
        pagina.evaluate("document.querySelector('#pantalla').scrollLeft = 500")
        pagina.click("#zoom-menos")  # el zoom no suelta el Mac
        pagina.click("#zoom-mas")
        assert "usando" in caja.get_attribute("class")
        pagina.evaluate("document.querySelector('#pantalla').scrollLeft = 500")
        r = pagina.locator("#directo").bounding_box()
        pagina.mouse.click(400, 300)
        pagina.wait_for_timeout(300)
        assert sim.puntero == (round(400 - r["x"]), round(300 - r["y"]))
    assert pagina.errores == []


# ── tras actualizar: reiniciar el puente y reabrir la conversación (C-0470) ──
# Dos pasos con botón en el aviso de código viejo, sin comandos. El reinicio
# de verdad no se hace aquí (pararía el puente de las pruebas): `reinicio.pedir`
# se sustituye por lo que se vería después, otro `arrancado`, el código nuevo
# en marcha y otro `Puente`, que no ha oído nada de los hooks de Claude. El
# reinicio de verdad se midió a mano con una unidad de prueba.

def _sin_los_no_esperados(errores, *estados):
    """Los errores de la página menos el aviso de consola de un «no» que la prueba
    provoca a propósito (un 409, un 404): ése es el navegador contando la respuesta."""
    return [e for e in errores if not any(f"status of {s} " in e for s in estados)]


def _como(monkeypatch, como: str):
    """Cómo se reinicia este puente: lo que preguntaría a systemd y lo que ya sabe."""
    from puente_kvm import reinicio
    monkeypatch.setattr(reinicio, "como", lambda: como)
    monkeypatch.setattr(reinicio, "sabido", lambda: (como, False))


def _codigo_nuevo_en_disco(monkeypatch):
    """Lo que deja una actualización: en el disco, otro código que el que corre."""
    monkeypatch.setattr(config.CODIGO_EN_MARCHA, "huella_disco", lambda: "la-del-codigo-nuevo")


def test_tras_actualizar_se_reinicia_con_un_boton_y_despues_se_reabre_la_conversacion(
        pagina, con_claude_falso, monkeypatch):
    from puente_kvm import app as app_puente
    from puente_kvm import conversaciones, reinicio
    _como(monkeypatch, "systemd")
    monkeypatch.setattr(reinicio, "ARRANQUE", reinicio.ARRANQUE)
    monkeypatch.setattr(config.CODIGO_EN_MARCHA, "_contenido", config.CODIGO_EN_MARCHA._contenido)
    sim, apps = Simulador(lineas=["x"]), []

    def pedir():
        time.sleep(1.5)  # lo que tarda en parar: la página espera sin recargar
        # El proceso nuevo: otro `Puente`, que de Claude sólo sabe lo que dejó guardado el de antes.
        apps[0].state.puente = app_puente.Puente(sim)
        reinicio.ARRANQUE = time.time()
        config.CODIGO_EN_MARCHA._contenido = "la-del-codigo-nuevo"  # el nuevo corre lo del disco

    monkeypatch.setattr(reinicio, "pedir", pedir)
    with en_marcha(sim, apps) as base:
        pagina.goto(base + "/")
        esperar_conversacion(pagina)
        _codigo_nuevo_en_disco(monkeypatch)
        # Claude trabaja cuando se pulsa reiniciar: su conversación sigue viva en tmux.
        httpx.post(base + "/api/claude/actividad", json={"hook_event_name": "UserPromptSubmit"}, timeout=5)
        pagina.wait_for_selector("#aviso-codigo:not([hidden])")
        assert pagina.locator("#boton-reiniciar").is_enabled()
        assert not pagina.locator("[data-codigo='comando']").is_visible()  # nada de comandos
        # Primero el puente: el paso 2 espera.
        assert pagina.locator("#boton-reabrir").is_visible() and not pagina.locator("#boton-reabrir").is_enabled()
        pagina.evaluate("window.antesDeRecargar = true")
        pagina.click("#boton-reiniciar")
        # Mientras para: el directo, la terminal y el mando, cortados.
        pagina.wait_for_function("document.querySelector('#codigo-estado').textContent.includes('Reiniciando')")
        marco = pagina.frame(name="marco")
        assert marco.locator("#directo").get_attribute("src") is None
        assert pagina.locator("#placa-terminal").inner_text() == "en pausa"
        # Vuelve sola, y queda el paso 2.
        pagina.wait_for_function("window.antesDeRecargar === undefined", timeout=15000)
        pagina.wait_for_selector("#aviso-codigo:not([hidden])")
        assert pagina.locator("#codigo-titulo").inner_text().startswith("Claude sigue con las herramientas de antes")
        assert not pagina.locator("[data-paso='reiniciar']").is_visible()
        # Claude seguía trabajando antes del reinicio: el puente nuevo pregunta antes de cortarlo.
        pagina.click("#boton-reabrir")
        pagina.wait_for_selector(".velo")
        assert "trabajando" in pagina.locator(".velo p").inner_text()
        pagina.click(".velo [data-si]")
        pagina.wait_for_selector("#aviso-codigo", state="hidden", timeout=15000)
        assert conversaciones.actual().codigo == "la-del-codigo-nuevo"
    assert _sin_los_no_esperados(pagina.errores, 409) == []  # el 409 de «Claude está trabajando»


def test_mientras_pregunta_si_reabrir_el_sondeo_no_vuelve_a_habilitar_el_boton(pagina, con_claude_falso,
                                                                              monkeypatch):
    # El estado se pide cada segundo y repintaba el aviso: el botón volvía a
    # poderse pulsar con el diálogo abierto, y un segundo clic reabría otra vez.
    with en_marcha(Simulador(lineas=["x"])) as base:
        pagina.goto(base + "/")
        esperar_conversacion(pagina)
        # Ya reiniciado: el puente corre lo del disco y la conversación es de antes.
        monkeypatch.setattr(config.CODIGO_EN_MARCHA, "huella_disco", lambda: "la-del-codigo-nuevo")
        monkeypatch.setattr(config.CODIGO_EN_MARCHA, "_contenido", "la-del-codigo-nuevo")
        httpx.post(base + "/api/claude/actividad", json={"hook_event_name": "UserPromptSubmit"}, timeout=5)
        pagina.wait_for_selector("#boton-reabrir:not([disabled])")
        pagina.click("#boton-reabrir")
        pagina.wait_for_selector(".velo")
        pagina.wait_for_timeout(2500)  # dos vueltas del sondeo
        assert not pagina.locator("#boton-reabrir").is_enabled()
        pagina.click(".velo [data-no]")
        pagina.wait_for_selector("#boton-reabrir:not([disabled])")
    assert _sin_los_no_esperados(pagina.errores, 409) == []


def test_si_no_se_reinicia_lo_dice_en_segundos_y_devuelve_la_imagen_y_la_terminal(pagina, con_claude_falso,
                                                                                  monkeypatch):
    # systemd aceptó, pero el puente sigue siendo el mismo: no se deja la
    # página cortada los dos minutos del tope. El reloj de la página se
    # adelanta: los 15 s no se esperan de verdad.
    from puente_kvm import reinicio
    _como(monkeypatch, "systemd")
    monkeypatch.setattr(reinicio, "pedir", lambda: True)  # y no pasa nada
    with en_marcha(Simulador(lineas=["x"])) as base:
        pagina.clock.install()
        pagina.goto(base + "/")
        esperar_conversacion(pagina)
        _codigo_nuevo_en_disco(monkeypatch)
        pagina.wait_for_selector("#aviso-codigo:not([hidden])")
        pagina.click("#boton-reiniciar")
        pagina.wait_for_function("document.querySelector('#codigo-estado').textContent.includes('Reiniciando')")
        pagina.wait_for_timeout(1500)
        assert "Reiniciando" in pagina.locator("#codigo-estado").inner_text()  # antes de 15 s, espera
        pagina.clock.fast_forward(16000)
        pagina.wait_for_function("document.querySelector('#codigo-estado').textContent.includes('No se reinició')",
                                 timeout=5000)
        assert "registro del servicio" in pagina.locator("#codigo-estado").inner_text()
        assert pagina.locator("#boton-reiniciar").is_enabled()
        marco = pagina.frame(name="marco")
        assert "/api/pantalla.mjpg" in (marco.locator("#directo").get_attribute("src") or "")
        pagina.wait_for_function("document.querySelector('#placa-terminal').textContent === 'conectada'")
    assert pagina.errores == []


def test_si_esta_ocupado_lo_dice_y_la_pantalla_vuelve_a_su_directo(pagina, con_claude_falso, monkeypatch):
    from puente_kvm import reinicio
    _como(monkeypatch, "systemd")
    pedido = []
    monkeypatch.setattr(reinicio, "pedir", lambda: pedido.append(True))
    with en_marcha(Simulador(lineas=["x"])) as base:
        pagina.goto(base + "/")
        esperar_conversacion(pagina)
        _codigo_nuevo_en_disco(monkeypatch)
        httpx.post(base + "/api/control", json={"accion": "dar"}, headers={"Origin": base}, timeout=5)
        pagina.wait_for_selector("#aviso-codigo:not([hidden])")
        pagina.click("#boton-reiniciar")
        pagina.wait_for_function("document.querySelector('#codigo-estado').textContent.includes('Claude tiene el control')")
        assert pagina.locator("#boton-reiniciar").is_enabled()
        marco = pagina.frame(name="marco")
        assert "/api/pantalla.mjpg" in marco.locator("#directo").get_attribute("src")
        pagina.wait_for_function("document.querySelector('#placa-terminal').textContent === 'conectada'")
        assert pedido == []
    assert _sin_los_no_esperados(pagina.errores, 409) == []


def test_si_el_puente_aun_corre_el_programa_de_antes_ensena_el_comando_esa_vez(pagina, con_claude_falso, monkeypatch):
    # La ruta no existe en el Python de antes: 404, y el comando de siempre.
    _como(monkeypatch, "systemd")
    with en_marcha(Simulador(lineas=["x"])) as base:
        pagina.route("**/api/reiniciar", lambda r: r.fulfill(status=404, content_type="application/json",
                                                             body='{"detail": "Not Found"}'))
        pagina.goto(base + "/")
        esperar_conversacion(pagina)
        _codigo_nuevo_en_disco(monkeypatch)
        pagina.wait_for_selector("#aviso-codigo:not([hidden])")
        pagina.click("#boton-reiniciar")
        pagina.wait_for_selector("[data-codigo='comando']:not([hidden])")
        assert "systemctl --user restart puente-kvm" in pagina.locator("[data-codigo='comando']").inner_text()
        assert "programa de antes" in pagina.locator("#codigo-estado").inner_text()
        pagina.wait_for_timeout(1500)  # el sondeo no vuelve a enseñar el botón que no funciona
        assert not pagina.locator("#boton-reiniciar").is_visible()
    assert _sin_los_no_esperados(pagina.errores, 404) == []


@pytest.mark.parametrize("como", ["sin-las-claves-nuevas", "sin-systemd"])
def test_sin_boton_que_valga_el_aviso_dice_el_comando_de_siempre(pagina, con_claude_falso, monkeypatch, como):
    _como(monkeypatch, "a_mano" if como == "sin-systemd" else "systemd")
    with en_marcha(Simulador(lineas=["x"])) as base:
        if como == "sin-las-claves-nuevas":
            # Lo que contesta el Python de antes: sin `reinicio`, `arrancado` ni `mando`.
            def viejo(route):
                r = route.fetch()
                datos = r.json()
                for clave in ("reinicio", "arrancado", "mando"):
                    datos.pop(clave, None)
                if datos.get("conversacion"):
                    datos["conversacion"].pop("herramientas_viejas", None)
                route.fulfill(response=r, json=datos)
            pagina.route("**/api/estado", viejo)
        pagina.goto(base + "/")
        esperar_conversacion(pagina)
        _codigo_nuevo_en_disco(monkeypatch)
        pagina.wait_for_selector("#aviso-codigo:not([hidden])")
        assert pagina.locator("[data-codigo='comando']").is_visible()
        assert not pagina.locator("#boton-reiniciar").is_visible()
    assert pagina.errores == []


# ── el Mac en reposo y Reconectar en el panel (C-0477) ───────────────────────
# Una marca en `window` dice si la página se recargó: recargar cortaría el
# mando y el directo, y el aviso tiene que irse solo.

def test_con_el_mac_en_reposo_el_panel_lo_dice_y_despertarlo_quita_el_aviso_sin_recargar(pagina):
    sim = Simulador(lineas=[""])
    sim.dormido = True
    with en_marcha(sim) as base:
        pagina.goto(base + "/panel")
        pagina.evaluate("window.__sinRecargar = 1")
        aviso = pagina.locator("#aviso-conexion")
        pagina.wait_for_function("!document.querySelector('#aviso-conexion').hidden")
        assert aviso.locator("#aviso-conexion-titulo").text_content() == "El Mac está en reposo."
        assert "Mac en reposo" in pagina.locator("#placa-aparato").text_content()
        assert pagina.locator("#aviso-conexion-ajustes").is_hidden()
        aviso.locator("[data-despertar]").click()
        pagina.wait_for_function("document.querySelector('#aviso-conexion').hidden")
        assert sim.despertado == 1
        assert "Mac en reposo" not in pagina.locator("#placa-aparato").text_content()
        assert pagina.evaluate("window.__sinRecargar") == 1
    assert pagina.errores == []


def test_reconectar_esta_en_el_panel_sin_ningun_fallo_y_no_recarga_la_pagina(pagina):
    sim = Simulador(lineas=[""])
    with en_marcha(sim) as base:
        pagina.goto(base + "/panel")
        pagina.evaluate("window.__sinRecargar = 1")
        assert pagina.locator("#aviso-conexion").is_hidden()
        boton = pagina.locator("#mando [data-reconectar]")
        assert boton.is_visible() and boton.text_content() == "Reconectar"
        assert "admite una sola sesión" in boton.get_attribute("title")
        boton.click()
        pagina.wait_for_function("document.querySelector('.fugaz')?.textContent.includes('Conectado')")
        pagina.wait_for_timeout(1200)
        assert pagina.evaluate("window.__sinRecargar") == 1
    assert pagina.errores == []


def test_el_error_de_conexion_se_pinta_como_texto_y_se_va_solo_cuando_el_aparato_vuelve(pagina):
    apps: list = []
    sim = Simulador(lineas=[""])
    with en_marcha(sim, apps) as base:
        p = apps[0].state.puente
        sim.conectado = False
        p.error_conexion = "el JetKVM responde <b>500</b> en /device"
        pagina.goto(base + "/panel")
        pagina.evaluate("window.__sinRecargar = 1")
        pagina.wait_for_function("!document.querySelector('#aviso-conexion').hidden")
        assert pagina.locator("#aviso-conexion-titulo").text_content() == "No hay conexión con el aparato."
        assert pagina.locator("#aviso-conexion-texto").text_content() == "el JetKVM responde <b>500</b> en /device"
        assert pagina.locator("#aviso-conexion b b").count() == 0
        assert pagina.locator("#aviso-conexion-ajustes").is_visible()
        sim.conectado = True  # vuelve (el Mac despertó, el aparato volvió)
        pagina.wait_for_function("document.querySelector('#aviso-conexion').hidden", timeout=5000)
        assert p.error_conexion == ""
        assert pagina.evaluate("window.__sinRecargar") == 1
    assert pagina.errores == []



class SimuladorLento(Simulador):
    """Conecta en segundos, como el aparato de verdad (saludo, pista, imagen)."""

    async def conectar(self) -> None:
        self.conectado = False
        await asyncio.sleep(2.5)
        self.conectado = True


def test_mientras_reconecta_el_panel_dice_conectando_y_no_que_no_hay_conexion(pagina):
    # Lo que vio el revisor: con el aviso pintado por el sondeo, reconectar sin
    # ningún fallo enseñaba en rojo «No hay conexión con el aparato».
    sim = SimuladorLento(lineas=[""])
    with en_marcha(sim) as base:
        pagina.goto(base + "/panel")
        pagina.wait_for_function("document.querySelector('#aviso-conexion').hidden")
        pagina.locator("#mando [data-reconectar]").click()
        pagina.wait_for_function("!document.querySelector('#aviso-conexion').hidden")
        assert pagina.locator("#aviso-conexion-titulo").text_content() == "Conectando con el JetKVM…"
        assert "riesgo" not in pagina.locator("#aviso-conexion").get_attribute("class")
        # Los dos «Reconectar» a la vez, apagados mientras tanto.
        assert pagina.locator("[data-reconectar]:disabled").count() == 2
        assert set(pagina.locator("[data-reconectar]").all_text_contents()) == {"Reconectando…"}
        pagina.wait_for_function("document.querySelector('#aviso-conexion').hidden", timeout=8000)
        assert pagina.locator("#mando [data-reconectar]").text_content() == "Reconectar"
        assert pagina.locator("[data-reconectar]:disabled").count() == 0
    assert pagina.errores == []


def test_entre_dos_tareas_del_encargo_la_pantalla_dice_que_claude_sigue_con_el_control(pagina):
    """C-0486: acabada una lectura o un tramo, el Mac aún no es de la persona. Que
    la pantalla no la deje corregir pensando que ya es suyo; y al acabar, que lo diga."""
    from puente_kvm import conversaciones

    conv = conversaciones.nueva("Encargo", "")
    conversaciones.marcar_abierta(conv.id)
    with en_marcha(Simulador(lineas=["x"])) as base:
        def hook(evento):
            httpx.post(base + "/api/claude/actividad", json={"hook_event_name": evento, "session_id": conv.id},
                       timeout=5)
        pagina.goto(base + "/panel")
        httpx.post(base + "/api/control", json={"accion": "dar"}, headers={"Origin": base}, timeout=5)
        hook("UserPromptSubmit")
        pagina.wait_for_function("document.querySelector('#control-ayuda').textContent"
                                 ".includes('Claude sigue con el control hasta que termine el encargo')")
        assert pagina.locator("#control-estado").inner_text() == "Claude tiene el control"
        hook("Stop")
        pagina.wait_for_function("document.querySelector('#control-ayuda').textContent"
                                 ".startsWith('Claude terminó: el Mac vuelve a ti para revisar y guardar.')")
        assert pagina.locator("#control-estado").inner_text() == "Tú tienes el Mac"
    assert pagina.errores == []


def test_dar_el_control_saca_las_casillas_marcadas_segun_ajustes(pagina):
    """C-0491 (decisión 460): las casillas salen como diga Ajustes → Permisos de
    Claude, siempre a la vista; lo que se manda es lo que quede marcado. Y quien
    llama a `confirmar` sin casillas sigue recibiendo un booleano."""
    with en_marcha(Simulador(lineas=["x"])) as base:
        pagina.goto(base + "/panel")
        pagina.click("#boton-dar")
        correcciones = pagina.locator('.dialogo [data-casilla="correcciones"]')
        delicado = pagina.locator('.dialogo [data-casilla="delicado"]')
        # De fábrica, desmarcada; «Trabajo delicado», también y a la vista.
        assert correcciones.is_visible() and not correcciones.is_checked()
        assert delicado.is_visible() and not delicado.is_checked()
        texto = pagina.locator(".dialogo").inner_text()
        assert "Correcciones pequeñas sin pedirte aprobación" in texto and "Trabajo delicado: pregúntame todo" in texto
        pagina.click(".dialogo [data-no]")

        # Marcada en Ajustes: sale marcada, y aceptar la concede.
        pagina.goto(base + "/ajustes")
        assert not pagina.locator("#permiso-correcciones").is_checked()
        assert "ejecutar nada en el Mac" in pagina.locator("#permisos-nunca").inner_text()
        pagina.check("#permiso-correcciones")
        # Guardar recarga Ajustes a los 800 ms: irse antes cortaba esa recarga.
        with pagina.expect_navigation():
            pagina.click("button[type=submit]")
        assert config.leer_ajustes()["permisos"] == {"correcciones": True}
        pagina.goto(base + "/panel")
        pagina.click("#boton-dar")
        assert pagina.locator('.dialogo [data-casilla="correcciones"]').is_checked()
        pagina.click(".dialogo [data-si]")
        pagina.wait_for_function("!document.querySelector('#control-correcciones').hidden")
        assert pagina.locator("#control-correcciones").inner_text() == \
            "Correcciones pequeñas sin pedirte: lleva 0 de 20 líneas."
        assert httpx.get(base + "/api/estado", timeout=5).json()["control"]["correcciones"]["lineas"] == 0

        # Desmarcarla en el diálogo la quita esa vez, sin tocar Ajustes.
        pagina.click("#boton-retomar")
        pagina.wait_for_function("document.querySelector('#control-correcciones').hidden")
        pagina.click("#boton-dar")
        pagina.locator('.dialogo [data-casilla="correcciones"]').uncheck()
        pagina.click(".dialogo [data-si]")
        pagina.wait_for_function("document.querySelector('#control-estado').textContent === 'Claude tiene el control'")
        assert "correcciones" not in httpx.get(base + "/api/estado", timeout=5).json()["control"]
        assert pagina.locator("#control-correcciones").is_hidden()
        assert config.leer_ajustes()["permisos"] == {"correcciones": True}
        detalle = httpx.get(base + "/api/bitacora", timeout=5).json()[-1]["detalle"]
        assert detalle == "la persona da el control a Claude, sin permisos"

        # Sin casillas, un booleano; con ellas, cancelar sigue siendo false.
        def responder(llamada: str, boton: str):
            # Sin esperar la promesa desde aquí: el diálogo se contesta con un clic.
            pagina.evaluate("(l) => { window.__r = undefined; eval(l).then((v) => { window.__r = v; }); }", llamada)
            casillas = pagina.locator(".dialogo [data-casilla]").count()
            pagina.click(".dialogo " + boton)
            pagina.wait_for_function("window.__r !== undefined")
            return pagina.evaluate("window.__r"), casillas

        dos = "PuenteUI.confirmar('¿Seguro?', { casillas: [{ id: 'a', texto: 'A', marcada: true }, { id: 'b', texto: 'B' }] })"
        assert responder("PuenteUI.confirmar('¿Seguro?')", "[data-si]") == (True, 0)
        assert responder(dos, "[data-no]") == (False, 2)
        assert responder(dos, "[data-si]") == ({"casillas": {"a": True, "b": False}}, 2)
    assert pagina.errores == []


def test_trabajo_delicado_desmarca_todas_las_casillas_y_da_el_control_sin_permisos(pagina):
    config.guardar_ajustes({**config.leer_ajustes(), "permisos": {"correcciones": True}})
    with en_marcha(Simulador(lineas=["x"])) as base:
        pagina.goto(base + "/panel")
        pagina.click("#boton-dar")
        correcciones = pagina.locator('.dialogo [data-casilla="correcciones"]')
        assert correcciones.is_checked() and correcciones.is_enabled()
        pagina.locator('.dialogo [data-casilla="delicado"]').check()
        assert not correcciones.is_checked() and correcciones.is_disabled()
        # Quitarla las devuelve como salieron; volver a marcarla las apaga otra vez.
        pagina.locator('.dialogo [data-casilla="delicado"]').uncheck()
        assert correcciones.is_checked() and correcciones.is_enabled()
        pagina.locator('.dialogo [data-casilla="delicado"]').check()
        peticiones = []
        pagina.on("request", lambda r: r.url.endswith("/api/control") and peticiones.append(r.post_data_json))
        pagina.click(".dialogo [data-si]")
        pagina.wait_for_function("document.querySelector('#control-estado').textContent === 'Claude tiene el control'")
        assert peticiones == [{"accion": "dar", "permisos": []}]
        assert "correcciones" not in httpx.get(base + "/api/estado", timeout=5).json()["control"]
        assert pagina.locator("#control-correcciones").is_hidden()
        assert httpx.get(base + "/api/bitacora", timeout=5).json()[-1]["detalle"].endswith("sin permisos")
    assert pagina.errores == []


def test_con_una_tarea_en_otra_ventana_el_panel_marca_su_zona_y_lo_dice(pagina):
    """C-0491 (decisión 460): mientras se lee o se escribe en otra ventana, el
    recuadro del panel rodea esa zona, no la región de Ajustes, y la tarea dice dónde."""
    from puente_kvm import lecturas

    apps = []
    with en_marcha(Simulador(lineas=muestras.procedimiento(80)), apps) as base:
        pagina.goto(base + "/panel")
        pagina.wait_for_timeout(700)

        def ancho_relativo() -> float:
            return pagina.evaluate("document.querySelector('#region').getBoundingClientRect().width"
                                   " / document.querySelector('#marco-mac .superficie:not([hidden])')"
                                   ".getBoundingClientRect().width")

        assert ancho_relativo() == pytest.approx(1620 / 1920, abs=0.01)
        l = lecturas.nueva("en otra ventana")
        l.zona = [300, 98, 1200, 700]
        l.guardar()
        motor = apps[0].state.puente.motor
        motor.tarea = "leer «en otra ventana»"
        try:
            pagina.wait_for_function("document.querySelector('#tarea').textContent.includes('otra ventana')",
                                     timeout=10000)
            assert "en otra ventana: la zona (300, 98, 1200×700)" in pagina.locator("#tarea").inner_text()
            assert ancho_relativo() == pytest.approx(1200 / 1920, abs=0.01)
        finally:
            motor.tarea = None
        pagina.wait_for_function("document.querySelector('#tarea').textContent === ''", timeout=10000)
        assert ancho_relativo() == pytest.approx(1620 / 1920, abs=0.01)
    assert pagina.errores == []
