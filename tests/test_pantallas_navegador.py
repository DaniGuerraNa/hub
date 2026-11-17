"""Todas las pantallas, abiertas en un Chromium de verdad a 390 y 1200 px (C-0168, decisión 361).

El HTTP 200 de `test_vistas_web.py` no ve un script que revienta al arrancar,
un `fetch` que da 500 ni algo que se sale de lado en el móvil: las tres cosas
han llegado a quien usa el hub con la suite en verde. Aquí se arranca un hub de
verdad —uvicorn, en un puerto libre de `127.0.0.1`, sobre los datos aislados de
`conftest.py`— con un poco de todo sembrado por las puertas de cada módulo, y
`hub.recorrido` lo abre entero como lo abriría una persona.

Necesita Playwright (grupo `navegador`) y un Chromium de Linux. Sin ellos se
salta, salvo con `HUB_EXIGIR_NAVEGADOR=1`, que es como se corre antes de
publicar: ahí saltarse en silencio sería pasar en verde sin haber mirado.

    uv run --group navegador pytest -m navegador
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from urllib.parse import urlsplit

import pytest

import arnes_tmux
from hub import (canal, db, encargos, ideas, intercambio, lienzos, mirar, recorrido,
                 registry, reuniones, slots, snapshotter, tmux)
from hub.registry import Atribuidor

pytestmark = pytest.mark.navegador

#: Las rutas de detalle que ninguna pantalla enlaza ni pide al cargar, y por
#: eso el recorrido no puede visitar con un id real. Una ruta nueva que no esté
#: aquí y no se alcance pone esto en rojo: o se siembra lo que la enlaza, o se
#: declara aquí con su porqué. Así «todas las pantallas» se puede demostrar.
SIN_ENLACE = {
    "/api/pregunta/{pregunta_id}": "la pide el relé, no una pantalla",
    "/api/sesion/{session_id}": "la pide el asistente con el id de un transcript",
    "/reuniones/miniatura/{n}": "sólo se enseña con el agente de Windows latiendo hace segundos",
}

# Un píxel PNG de verdad: el navegador lo decodifica y no se queja.
_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
    "1f15c4890000000d49444154789c6360f8cf000000030101001899f05e"
    "0000000049454e44ae426082")


def _requisitos():
    falta = None
    try:
        import playwright.sync_api  # noqa: F401
    except ModuleNotFoundError:
        falta = "falta Playwright: uv run --group navegador pytest -m navegador"
    if not falta and not mirar.cual_linux():
        falta = "no hay un Chromium de Linux (el de Windows no baja de 500 px)"
    if falta:
        if os.environ.get("HUB_EXIGIR_NAVEGADOR") == "1":
            pytest.fail(falta)
        pytest.skip(falta)


def _sembrar(tmp_path, monkeypatch) -> None:
    """Un poco de cada cosa que tiene pantalla de detalle, por su puerta, y un
    tmux propio con una sesión viva para que `/trabajo` pinte su terminal y no
    sólo el «no hay nada abierto»."""
    asiento = tmp_path / "proyectos" / "demo"
    asiento.mkdir(parents=True)
    (asiento / "ESTADO.md").write_text("# Estado\n\nTodo en marcha.\n", encoding="utf-8")
    registry.añadir_proyecto({"id": "demo", "nombre": "Demo", "asiento": str(asiento),
                              "estado_ref": "ESTADO.md", "guardrail": "ask"})

    con = db.abrir()
    try:
        registry.sincronizar(con, registry.cargar())
        slot = slots.crear(con, "demo", "Arreglo del formulario", ruta=str(asiento),
                           nota="Seguir por la validación.")
        idea = ideas.apuntar(con, "Que el tablero acepte capturas", proyecto="demo")
        ideas.adjuntar(con, idea, "captura.png", _PNG)
        encargos.crear(con, "panaderia", user_id=1, titulo="Web de la panadería")
        canal.crear_pregunta(con, "demo", "¿Sigo con la migración?", slot_id=slot)
        # 🔴 Una sesión perdida cuyo panel tiene por título una ruta sin
        # espacios: así se pintaba en el aviso de la portada, y la empujaba a
        # 473 px en el teléfono (medido el 6-nov en el hub de verdad). La
        # muestra la toma el snapshotter, que es su dueño; tmux se finge sólo
        # para esto.
        titulo = "srv/datos/usuarios/alguien/Escritorio/proyectos/una-carpeta-de-nombre-largo"
        monkeypatch.setattr(tmux, "rama_git", lambda cwd: None)
        monkeypatch.setattr(tmux, "servidor_pid", lambda: 4242)
        monkeypatch.setattr(tmux, "listar_paneles", lambda: [{
            "session": "demo", "window_idx": 0, "pane_idx": 0, "pane_id": "%1",
            "cwd": str(asiento), "titulo": titulo, "comando": "bash", "activo": True}])
        atribuidor = Atribuidor(registry.cargar())
        snapshotter.capturar(con, atribuidor)
        monkeypatch.setattr(tmux, "servidor_pid", lambda: None)
        monkeypatch.setattr(tmux, "listar_paneles", lambda: [])
        snapshotter.capturar(con, atribuidor)
        con.commit()
    finally:
        con.close()

    intercambio.guardar("notas.txt", b"Lo que vino del movil.\n")
    intercambio.guardar("foto.png", _PNG)
    lienzos.escribir("demo", "Decisiones del formulario",
                     cuerpo="- Validar en el servidor\n- Avisar en la misma pantalla\n")

    # Una reunión procesada, con su foto, y el agente de Windows latiendo.
    grabaciones = tmp_path / "reuniones-que-no-existen" / "grabaciones"
    reunion = grabaciones / "20261020-090000"
    (reunion / "fotos").mkdir(parents=True)
    (reunion / "fotos" / "000004.jpg").write_bytes(_PNG)
    for nombre, datos in {
        "meta.json": {"id": reunion.name, "inicio": 0, "fin": 600,
                      "proceso": {"nombre": "ms-teams.exe"}},
        "transcripcion.json": [{"ini": 1.0, "fin": 3, "texto": "Hola", "quien": "Reunión"},
                               {"ini": 5.0, "fin": 7, "texto": "Mirad esto", "quien": "Yo"}],
        "resumen.json": {"titulo": "Seguimiento", "resumen": "Breve.",
                         "tareas": [{"quien": "Yo", "que": "Revisar el despliegue"}]},
        "procesado.json": {"estado": "hecho"},
    }.items():
        (reunion / nombre).write_text(json.dumps(datos), encoding="utf-8")
    reuniones.latido({"agente": "0.1", "equipo": "PC", "grabando": None,
                      "monitores": [{"n": 1, "ancho": 1920, "alto": 1080}],
                      "microfonos": [{"n": 1, "nombre": "Micrófono"}],
                      "apps": [{"nombre": "ms-teams.exe", "pid": 1, "activa": True}]})
    reuniones.guardar_miniatura(1, b"\xff\xd8" + _PNG)

    # Una corrida del navegante, con su captura. La pantalla enseña las
    # corridas con el laboratorio preparado, así que va uno cuyo `nav` sólo
    # sabe contestar el resumen (como el de `test_navegante.py`).
    corrida = tmp_path / "navegador-lab-que-no-existe" / "salidas" / "lista" / "20261019-120000"
    corrida.mkdir(parents=True)
    (corrida / "resultado.json").write_text("{}", encoding="utf-8")
    (corrida / "pantalla.png").write_bytes(_PNG)
    lab = tmp_path / "lab"
    for carpeta in ("bin", ".venv", "node_modules"):
        (lab / carpeta).mkdir(parents=True)
    resumen = {"estado": {"navegador": {"vivo": False, "pestanas": []},
                          "guardian": {"vivo": False}, "panel": {"vivo": False}, "grabando": None},
               "flujos": [{"nombre": "lista", "coleccion": "lab", "parametros": {"base": {}},
                           "pasos": 3, "pantallas": {"desde": "consola", "hasta": "lista"}, "usa": []}],
               "politicas": [], "mapa": {"pantallas": [], "salen": {}, "sin_pantalla": []},
               "config": {"colecciones": [{"nombre": "lab"}], "accesos": []}}
    (lab / "bin" / "nav").write_text(
        "#!/usr/bin/env python3\nimport json, sys\n"
        f"print(json.dumps({resumen!r}) if sys.argv[1:2] == ['resumen'] else '')\n")
    (lab / "bin" / "nav").chmod(0o755)
    monkeypatch.setenv("NAV_LAB", str(lab))
    monkeypatch.setenv("NAV_CHROME", "chrome")

    # Por `tmux.orden_base()`, que es la puerta: con `-f /dev/null`, y así el
    # servidor de prueba no lee el `~/.tmux.conf` de quien ejecuta ni restaura
    # sus sesiones de verdad (264), que el recorrido visitaría.
    zocalo = f"hub-pantallas-{os.getpid()}"
    monkeypatch.setenv("HUB_TMUX_SOCKET", zocalo)
    monkeypatch.delenv("TMUX", raising=False)
    if shutil.which("tmux"):
        subprocess.run([*tmux.orden_base(), "new-session", "-d", "-s", "demo", "-c", str(asiento)],
                       check=False, timeout=10)


def _puerto_libre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def hub_sembrado(tmp_path, monkeypatch):
    _requisitos()
    _sembrar(tmp_path, monkeypatch)
    puerto = _puerto_libre()
    # El entorno de `conftest.py` tal cual —HUB_HOME, registro, componentes,
    # `HUB_BUSCAR_VERSIONES=0`— más el tmux propio de `_sembrar`: el servidor
    # lo hereda.
    entorno = dict(os.environ)
    registro = tmp_path / "uvicorn.log"
    with registro.open("w") as salida:
        proceso = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "hub.web:app",
             "--host", "127.0.0.1", "--port", str(puerto)],
            env=entorno, stdout=salida, stderr=subprocess.STDOUT)
    base = f"http://127.0.0.1:{puerto}"
    try:
        limite = time.monotonic() + 30
        while True:
            try:
                urllib.request.urlopen(base + "/api/salud", timeout=2)
                break
            except OSError:
                if proceso.poll() is not None or time.monotonic() > limite:
                    pytest.fail("el hub no arrancó:\n" + registro.read_text()[-3000:])
                time.sleep(0.2)
        yield base, registro
    finally:
        proceso.terminate()
        try:
            proceso.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proceso.kill()
        # Con su socket: `kill-server` solo lo dejaba, uno por pasada (C-0325).
        arnes_tmux.apagar(os.environ["HUB_TMUX_SOCKET"])


def test_ninguna_pantalla_falla_en_el_navegador_ni_se_queda_sin_visitar(hub_sembrado):
    base, registro = hub_sembrado
    informe = recorrido.recorrer(base)

    sobran = sorted(set(informe.sin_visitar) - set(SIN_ENLACE))
    assert not sobran, (
        f"rutas que el recorrido no pudo visitar con un id real: {sobran}. "
        "Siembra lo que las enlaza o decláralas en SIN_ENLACE con su porqué.")
    ya_se_visitan = sorted(set(SIN_ENLACE) - set(informe.sin_visitar))
    assert not ya_se_visitan, f"ya se visitan; quítalas de SIN_ENLACE: {ya_se_visitan}"
    assert not informe.fallos, (
        informe.texto() + "\n\nRegistro del servidor:\n" + registro.read_text()[-3000:])
    # Que de verdad recorrió el hub y no una página de error tras otra.
    assert len(informe.visitadas) >= 25, informe.texto()
    assert "/proyecto/demo" in informe.visitadas
    assert any(u.startswith("/trabajo?") for u in informe.visitadas), informe.visitadas
    assert "/secretario/monitor" in informe.visitadas   # a 390 y a 1200, como todas (C-0202)


# ── El panel del secretario, que va en todas las pantallas (C-0187) ─────────

def _secretario_en_todo_el_hub() -> None:
    from hub.secretario import memoria
    memoria.conectar().close()
    (memoria.carpeta() / "secretario.yml").write_text("en_todo_el_hub: true\n", encoding="utf-8")


@pytest.fixture
def chromium(hub_sembrado):
    """Un Chromium sobre el hub sembrado, con el panel del secretario en todas
    las pantallas. El servidor lee `secretario.yml` en cada petición, así que
    basta con escribirlo ya arrancado."""
    from playwright.sync_api import sync_playwright
    base, _ = hub_sembrado
    _secretario_en_todo_el_hub()
    with sync_playwright() as pw:
        navegador = pw.chromium.launch(executable_path=str(mirar.cual_linux()), headless=True,
                                       args=["--no-sandbox", "--disable-gpu"])
        try:
            yield base, navegador
        finally:
            navegador.close()


@pytest.mark.parametrize("ruta", ["/navegante", "/reuniones"])
def test_con_la_voz_del_secretario_guardada_la_pantalla_se_sigue_actualizando(chromium, ruta):
    """Medido el 6-nov en el hub de verdad: con «Leer las respuestas en voz
    alta» o «mandarlo solo» guardadas, el panel marca su casilla al cargar y
    `navegante.js` la tomaba por algo a medio escribir. 0 sondeos en 7,5 s:
    la pregunta que espera «Permitir» no aparecía nunca."""
    base, navegador = chromium
    contexto = navegador.new_context(viewport={"width": 1200, "height": 900})
    contexto.add_init_script("try { localStorage.setItem('secretario.voz', '1');"
                             " localStorage.setItem('secretario.manos', '1'); } catch (e) {}")
    pagina = contexto.new_page()
    sondeos = []
    pagina.on("request", lambda r: sondeos.append(r.url)
              if r.resource_type == "fetch" and urlsplit(r.url).path == ruta else None)
    pagina.goto(base + ruta, wait_until="load")
    assert pagina.evaluate("document.getElementById('sec-en-voz').checked"), \
        "la preferencia no llegó al panel: esto no prueba nada"
    # Lo que la pantalla trae cuando hay algo en marcha. Fingir una corrida o
    # una grabación de verdad no añade nada a lo que se mide aquí.
    pagina.evaluate("""() => {
      const r = document.querySelector('[data-region]:not([data-region=rail])');
      r.dataset.refrescar = '3';
      document.dispatchEvent(new CustomEvent('hub:repintado', { detail: { regiones: [] } }));
    }""")
    pagina.wait_for_timeout(3800)
    contexto.close()
    assert sondeos, f"{ruta} dejó de actualizarse sola"


# Lo que se mide del panel: la misma pieza tiene que verse igual en todas
# partes. Se le añaden una burbuja y una tarjeta de respuesta porque el panel
# sembrado está vacío.
_MEDIR_PANEL = """() => {
  const chat = document.querySelector('#secretario-cuerpo .chat');
  const burbuja = document.createElement('div');
  burbuja.className = 'burbuja secretario';
  const ficha = document.createElement('div');
  ficha.className = 'ficha';
  ficha.innerHTML = '<strong>Tarjeta</strong><ul><li>uno</li></ul>';
  burbuja.append(ficha);
  chat.append(burbuja);
  const de = (el, props) => { const c = getComputedStyle(el); return props.map((k) => c[k]).join(' '); };
  const medida = {
    chat: de(chat, ['rowGap', 'maxWidth', 'padding']),
    burbuja: de(burbuja, ['padding', 'fontSize', 'lineHeight', 'borderRadius']),
    ficha: de(ficha, ['padding', 'margin', 'borderBottomWidth', 'borderRadius']),
    escribir: de(document.querySelector('#secretario-cuerpo .escribir'), ['padding', 'gap']),
    texto: de(document.getElementById('sec-texto'), ['minHeight', 'borderRadius']),
  };
  burbuja.remove();
  return medida;
}"""


def test_el_panel_del_secretario_se_ve_igual_en_todas_las_pantallas(chromium):
    """C-0181 subió las hojas del panel a `<head>`: sus selectores van con
    `:where()` y empatan con los `<style>` de cada pantalla, que ahora llegan
    después y ganan. Medido el 6-nov: en /encargos el hueco entre burbujas era
    de 6 px y no de 12; en el proyecto, las tarjetas de respuesta llevaban
    22 px de relleno abajo."""
    base, navegador = chromium
    contexto = navegador.new_context(viewport={"width": 1200, "height": 900})
    pagina = contexto.new_page()
    medidas = {}
    for ruta in ("/", "/encargos", "/proyecto/demo", "/tablero", "/canal", "/servicios",
                 "/navegante", "/reuniones", "/intercambio", "/orquestador", "/maquina"):
        pagina.goto(base + ruta, wait_until="load")
        medidas[ruta] = pagina.evaluate(_MEDIR_PANEL)
    contexto.close()
    referencia = medidas["/"]
    assert referencia["chat"].startswith("12px none"), referencia
    distintas = {r: {k: v for k, v in m.items() if v != referencia[k]}
                 for r, m in medidas.items() if m != referencia}
    assert not distintas, f"en / el panel mide {referencia}; aquí no: {distintas}"


def test_sin_javascript_renombrar_se_ve_y_se_puede_enviar(chromium):
    """El formulario de renombrar estaba escondido también sin JS, al revés de
    lo que dice su comentario: sin el lápiz funcionando, no había forma de
    renombrar."""
    base, navegador = chromium
    contexto = navegador.new_context(java_script_enabled=False, viewport={"width": 1200, "height": 900})
    pagina = contexto.new_page()
    pagina.goto(base + "/encargos/panaderia", wait_until="load")
    formularios = pagina.locator(".editable > .edicion")
    assert formularios.count() >= 1
    assert all(formularios.nth(i).is_visible() for i in range(formularios.count()))
    contexto.close()


# ── el modo monitor del secretario (C-0202, decisión 389) ───────────────────

_ESTA_EN = """(puesto) => {
  const a = document.querySelector('[data-andador] .esc-pj').getBoundingClientRect();
  const p = document.querySelector(`[data-puesto="${puesto}"]`).getBoundingClientRect();
  const x = a.left + a.width / 2, y = a.bottom;
  return x >= p.left && x <= p.right && y >= p.top && y <= p.bottom + 2;
}"""

_CUENTA = """(turno) => document.dispatchEvent(new CustomEvent('secretario:estado', { detail: { turnos: [turno] } }))"""

# Que quepa: el rótulo, debajo del letrero del puesto y sin salirse de él; él, dentro.
_CABE = """(puesto) => {
  const caja = document.querySelector(`[data-puesto="${puesto}"]`).getBoundingClientRect();
  const letrero = document.querySelector(`[data-puesto="${puesto}"] [data-letrero]`).getBoundingClientRect();
  const r = document.querySelector('.esc-rotulo').getBoundingClientRect();
  const pj = document.querySelector('[data-andador] .esc-pj > .pj').getBoundingClientRect();
  return [r.top >= letrero.bottom - 1, r.left >= caja.left - 1 && r.right <= caja.right + 1,
          pj.left >= caja.left - 1 && pj.right <= caja.right + 1 && pj.bottom <= caja.bottom + 1];
}"""


@pytest.mark.parametrize("ancho, alto", [(1920, 1080), (1366, 768), (1280, 720), (390, 844)])
def test_el_monitor_lleva_al_personaje_al_puesto_de_lo_que_hace(chromium, ancho, alto):
    """Sin el raíl del hub, con el chat, y el personaje de pie en su mesa; lo
    que cuenta el chat lo lleva a la agenda, y de vuelta a su mesa. Medido en
    el navegador: que la cuenta sea buena no dice que se vea donde toca, ni
    que con el rótulo encima quepa sin tapar el nombre del puesto (a 1366×768
    lo tapaba, revisor del 7-nov)."""
    base, navegador = chromium
    contexto = navegador.new_context(viewport={"width": ancho, "height": alto})
    pagina = contexto.new_page()
    errores = []
    pagina.on("pageerror", lambda e: errores.append(str(e)))
    pagina.goto(base + "/secretario/monitor", wait_until="load")
    en = "document.querySelector('[data-escenario]').dataset.en"
    assert not pagina.locator(".rail-global").is_visible()
    assert not pagina.locator(".envoltura > header").is_visible()
    assert pagina.locator("[data-escenario]").is_visible() and pagina.locator("#sec-texto").is_visible()
    assert pagina.evaluate(en) == "escritorio" and pagina.evaluate(_ESTA_EN, "escritorio")

    pagina.evaluate(_CUENTA, {"id": 1, "rol": "secretario", "estado": "escribiendo",
                              "actividad": {"estado": "trabajando", "gesto": "agenda", "rotulo": "Mirando tu agenda"}})
    assert pagina.evaluate(en) == "agenda"
    assert pagina.evaluate("document.querySelector('[data-andador]').classList.contains('andando')")
    pagina.wait_for_timeout(1400)
    assert pagina.evaluate(_ESTA_EN, "agenda")
    assert pagina.locator(".esc-rotulo").inner_text() == "Mirando tu agenda"
    assert pagina.evaluate(_CABE, "agenda") == [True, True, True]

    largo = "Buscando «la revisión del despliegue del formulario» en lo que ha leído"
    pagina.evaluate(_CUENTA, {"id": 1, "rol": "secretario", "estado": "escribiendo",
                              "actividad": {"estado": "trabajando", "gesto": "buscar", "rotulo": largo}})
    pagina.wait_for_timeout(1400)
    assert pagina.evaluate(en) == "mensajes" and pagina.evaluate(_CABE, "mensajes") == [True, True, True]

    pagina.evaluate(_CUENTA, {"id": 1, "rol": "secretario", "estado": "listo"})
    pagina.wait_for_timeout(1400)
    assert pagina.evaluate(en) == "escritorio" and pagina.evaluate(_ESTA_EN, "escritorio")
    ancho_pagina = pagina.evaluate("document.documentElement.scrollWidth")
    contexto.close()
    assert not errores, errores
    assert ancho_pagina <= ancho


@pytest.mark.parametrize("ancho, se_ve", [(1200, True), (390, False)])
def test_el_boton_del_modo_monitor_sale_en_el_pc_y_no_en_el_telefono(chromium, ancho, se_ve):
    """`a.boton` pone su `display` y pesaba más que la clase sola: en el
    teléfono salía en la barra fija y le quitaba 112 px al personaje (revisor)."""
    base, navegador = chromium
    contexto = navegador.new_context(viewport={"width": ancho, "height": 844})
    pagina = contexto.new_page()
    pagina.goto(base + "/secretario", wait_until="load")
    visible = pagina.locator(".sec-monitor").is_visible()
    contexto.close()
    assert visible is se_ve


# ── el chat, al final al cargar (C-0303) ────────────────────────────────────

def _conversacion_larga(nuevas: int) -> None:
    """Catorce globos en el hilo abierto y `nuevas` asuntos en «Te espera»,
    por las puertas de la conversación y de los asuntos."""
    from hub.secretario import asuntos, conversacion, memoria
    con = memoria.conectar()
    try:
        if not conversacion.hilo_abierto(con):
            for n in range(7):
                r = conversacion.recibir(con, f"Pregunta {n}: ¿qué tengo pendiente de lo de esta semana?")
                con.execute("UPDATE turno SET estado = 'listo' WHERE id = ?", (r["turno"],))
                conversacion.decir(con, r["hilo"], f"Respuesta {n}. " + "Una línea con algo que contarte. " * 12)
        memoria.poner(con, asuntos.CLAVE_ESTADO, {"nuevas": nuevas, "total": nuevas})
    finally:
        con.close()


# Lo que falta por bajar, si el chat desplaza de verdad y si el globo se ve.
_FALTA_POR_BAJAR = """() => {
  const c = document.getElementById('sec-chat');
  return [Math.round(c.scrollHeight - c.clientHeight - c.scrollTop), c.scrollHeight > c.clientHeight + 50,
          !document.getElementById('sec-globo').hidden];
}"""


def test_al_cargar_el_chat_queda_al_final_aunque_salga_el_globo_te_espera(chromium):
    """Medido en la auditoría (UI-26): con algo en «Te espera», la última
    respuesta —la que se viene a leer— salía cortada 51 px por abajo. El chat
    bajaba al final y DESPUÉS salía el globo, que va encima y lo encoge. En
    /secretario, en el monitor y en el panel de las demás pantallas, a 1200 y
    a 390 px; y sin globo, igual."""
    base, navegador = chromium
    medidas = {}
    for nuevas in (2, 0):
        _conversacion_larga(nuevas)
        for ancho, alto in ((1200, 900), (390, 844)):
            contexto = navegador.new_context(viewport={"width": ancho, "height": alto})
            # El panel se recuerda abierto: así lo abre quien lo usa.
            contexto.add_init_script("try { localStorage.setItem('hub.secretario.abierto', '1'); } catch (e) {}")
            pagina = contexto.new_page()
            for ruta in ("/secretario", "/secretario/monitor", "/"):
                pagina.goto(base + ruta, wait_until="load")
                pagina.wait_for_function("document.querySelectorAll('#sec-chat .burbuja').length >= 14")
                pagina.wait_for_timeout(400)
                medidas[(nuevas, ancho, ruta)] = pagina.evaluate(_FALTA_POR_BAJAR)
            contexto.close()
    # Que el chat desplace y el globo salga: si no, esto no mide nada.
    assert all(m[1] for m in medidas.values()), medidas
    assert all(m[2] is (k[0] > 0) for k, m in medidas.items()), medidas
    cortados = {k: m[0] for k, m in medidas.items() if m[0] >= 2}
    assert not cortados, f"px que faltan por bajar al cargar: {cortados}"


def test_si_encoge_sigue_al_final_pero_a_quien_subio_a_leer_no_le_mueve(chromium):
    """El teclado del móvil encoge el chat como el globo (C-0303): al final,
    se queda al final; quien subió a leer algo de antes no se ve arrastrado."""
    base, navegador = chromium
    _conversacion_larga(0)
    contexto = navegador.new_context(viewport={"width": 390, "height": 844})
    pagina = contexto.new_page()
    pagina.goto(base + "/secretario", wait_until="load")
    pagina.wait_for_timeout(300)
    pagina.set_viewport_size({"width": 390, "height": 520})
    pagina.wait_for_timeout(300)
    al_final = pagina.evaluate(_FALTA_POR_BAJAR)[0]
    pagina.set_viewport_size({"width": 390, "height": 844})
    pagina.evaluate("document.getElementById('sec-chat').scrollTop = 40")
    pagina.wait_for_timeout(300)
    pagina.set_viewport_size({"width": 390, "height": 520})
    pagina.wait_for_timeout(300)
    arriba = pagina.evaluate("document.getElementById('sec-chat').scrollTop")
    contexto.close()
    assert al_final < 2
    assert arriba == 40


# Cómo se ve la línea de estado: su color frente al del token, su marca y su papel.
_LINEA_DE_ESTADO = """() => {
  const e = document.getElementById('estado-sec');
  const muestra = document.createElement('span');
  muestra.style.color = 'var(--riesgo)';
  document.body.append(muestra);
  const riesgo = getComputedStyle(muestra).color;
  muestra.remove();
  const r = document.getElementById('sec-reintentar');
  return { texto: e.textContent, rojo: getComputedStyle(e).color === riesgo,
           marca: getComputedStyle(e, '::before').content, papel: e.getAttribute('role'),
           cuadro: document.getElementById('sec-texto').value,
           reintentar: !!r && !r.hidden && r.getBoundingClientRect().width > 0,
           ancho: document.documentElement.scrollWidth };
}"""


@pytest.mark.parametrize("ancho, alto", [(1200, 900), (390, 844)])
def test_un_mensaje_que_no_sale_se_ve_en_rojo_y_reintentar_lo_manda(chromium, ancho, alto):
    """C-0305: en gris pequeño, como «enviando…», un mensaje que no salió se
    confundía con uno enviado. Y lo que escribe en esa línea el dictado, que
    no sabe de tonos, le quita el rojo."""
    base, navegador = chromium
    contexto = navegador.new_context(viewport={"width": ancho, "height": alto})
    contexto.add_init_script("try { localStorage.setItem('hub.secretario.abierto', '1'); } catch (e) {}")
    pagina = contexto.new_page()
    # En el panel de otra pantalla, sin nada que reintentar, no se ve: el
    # `display` de todo botón pesaba más que `hidden` (sólo /secretario lo tapaba).
    pagina.goto(base + "/", wait_until="load")
    reintentar_en_el_panel = pagina.locator("#sec-reintentar").is_visible()
    pagina.goto(base + "/secretario", wait_until="load")
    pagina.route("**/api/secretario/mensaje", lambda ruta: ruta.abort())
    pagina.fill("#sec-texto", "¿qué tengo hoy?")
    pagina.press("#sec-texto", "Enter")
    pagina.wait_for_function("document.getElementById('estado-sec').dataset.tono === 'error'")
    fallo = pagina.evaluate(_LINEA_DE_ESTADO)
    pagina.unroute("**/api/secretario/mensaje")
    with pagina.expect_request(lambda r: r.url.endswith("/api/secretario/mensaje") and r.method == "POST") as pedido:
        pagina.click("#sec-reintentar")
    mandado = json.loads(pedido.value.post_data)
    pagina.wait_for_function("document.getElementById('sec-texto').value === ''")
    tras = pagina.evaluate(_LINEA_DE_ESTADO)
    # Otro fallo, y el dictado escribe encima su «escuchando…».
    pagina.evaluate("""() => { const e = document.getElementById('estado-sec');
                               e.dataset.tono = 'error'; e.dataset.dicho = 'x'; e.textContent = 'x';
                               e.textContent = 'escuchando…'; }""")
    pagina.wait_for_timeout(50)
    encima = pagina.evaluate("document.getElementById('estado-sec').dataset.tono || ''")
    contexto.close()
    assert not reintentar_en_el_panel
    assert "no se envió" in fallo["texto"] and fallo["rojo"] and fallo["marca"] == '"!"', fallo
    assert fallo["papel"] == "alert" and fallo["cuadro"] == "¿qué tengo hoy?" and fallo["reintentar"], fallo
    assert fallo["ancho"] <= ancho, fallo
    assert mandado["texto"] == "¿qué tengo hoy?"
    assert not tras["rojo"] and tras["papel"] == "status" and tras["cuadro"] == "" and not tras["reintentar"], tras
    assert encima == ""


def test_el_panel_no_ensena_las_ideas_de_chat_vacio_mientras_llega_la_conversacion(chromium):
    """C-0304: con el panel abierto, cada pantalla pintaba «Pregúntale por tus
    mensajes…» y las tres ideas, y al llegar la conversación saltaba a ella.
    Se retiene la respuesta del hub para mirar lo que se ve mientras tanto."""
    base, navegador = chromium
    contexto = navegador.new_context(viewport={"width": 1200, "height": 900})
    contexto.add_init_script("try { localStorage.setItem('hub.secretario.abierto', '1'); } catch (e) {}")
    pagina = contexto.new_page()
    retenidas = []
    pagina.route("**/api/secretario/turnos*", lambda ruta: retenidas.append(ruta))
    ve = "(id) => { const n = document.getElementById(id); return !!n && n.getBoundingClientRect().height > 0; }"
    vistas = {}
    for caso in ("vacia", "con-conversacion"):
        if caso == "con-conversacion":
            _conversacion_larga(0)
        pagina.goto(base + "/", wait_until="load")
        pagina.wait_for_function("document.getElementById('sec-cargando')")
        pagina.wait_for_timeout(300)
        mientras = [pagina.evaluate(ve, "sec-cargando"), pagina.evaluate(ve, "sec-vacio")]
        while retenidas:
            retenidas.pop().continue_()
        pagina.wait_for_function("!document.getElementById('sec-cargando')")
        vistas[caso] = mientras + [pagina.evaluate(ve, "sec-vacio"),
                                   pagina.locator("#sec-chat .burbuja").count()]
    contexto.close()
    # [hueco mientras, ideas mientras, ideas después, globos después]
    assert vistas["vacia"] == [True, False, True, 0], vistas
    assert vistas["con-conversacion"] == [True, False, False, 14], vistas


_CODIGO = """() => {
  const b = document.querySelector('#sec-chat .burbuja.secretario');
  const pre = b.querySelector('.bloque-codigo > pre'), boton = b.querySelector('.copiar-codigo');
  const t = b.querySelector('.titulo');
  return { titulo: t ? t.textContent : null, almohadillas: b.textContent.includes('##'),
           comillas: b.textContent.includes('```'), mono: /mono/i.test(getComputedStyle(pre).fontFamily),
           desplaza: pre.scrollWidth > pre.clientWidth, cabe: b.getBoundingClientRect().right <= innerWidth,
           fondo: getComputedStyle(pre).backgroundColor !== getComputedStyle(b).backgroundColor,
           boton: boton.getBoundingClientRect().width > 0, ancho: document.documentElement.scrollWidth };
}"""


@pytest.mark.parametrize("ancho, alto", [(1200, 900), (390, 844)])
def test_el_codigo_y_los_titulos_de_una_respuesta_se_ven_sin_sus_marcas_y_se_copian(chromium, ancho, alto):
    """C-0306: un bloque de tres comillas salía literal y en letra normal, y
    «## Título» con sus almohadillas. Una línea larga no ensancha el globo ni
    la página: se desplaza dentro del bloque."""
    from hub.secretario import conversacion, memoria
    base, navegador = chromium
    orden = "uv run pytest tests/" + "test_una_ruta_muy_larga_que_no_cabe_en_el_telefono_" * 3 + ".py -q"
    con = memoria.conectar()
    try:
        if not conversacion.hilo_abierto(con):
            r = conversacion.recibir(con, "¿cómo lo pruebo?")
            con.execute("UPDATE turno SET estado = 'listo' WHERE id = ?", (r["turno"],))
            conversacion.decir(con, r["hilo"], f"## Para probarlo\nEn la carpeta del hub:\n```bash\n{orden}\n```\nY mira el código de salida.")
    finally:
        con.close()
    contexto = navegador.new_context(viewport={"width": ancho, "height": alto})
    contexto.grant_permissions(["clipboard-read", "clipboard-write"], origin=base)
    pagina = contexto.new_page()
    pagina.goto(base + "/secretario", wait_until="load")
    pagina.wait_for_selector("#sec-chat .burbuja.secretario .bloque-codigo")
    medida = pagina.evaluate(_CODIGO)
    pagina.click("#sec-chat .copiar-codigo")
    pagina.wait_for_function("document.querySelector('#sec-chat .copiar-codigo').textContent === 'Copiado'")
    copiado = pagina.evaluate("navigator.clipboard.readText()")
    contexto.close()
    assert medida["titulo"] == "Para probarlo" and not medida["almohadillas"] and not medida["comillas"], medida
    assert medida["mono"] and medida["fondo"] and medida["boton"], medida
    assert medida["desplaza"] and medida["cabe"] and medida["ancho"] <= ancho, medida
    assert copiado == orden


def test_con_el_secretario_parado_el_chat_lo_dice_en_vez_de_quedarse_pensando(chromium):
    """C-0302: el hub sembrado no tiene `hub-secretario`, así que nadie late.
    Lo que se le escribió espera, y a los pocos segundos el chat lo dice, con
    el enlace a su pantalla; en /secretario y en el panel de otra."""
    from hub.secretario import conversacion, memoria
    base, navegador = chromium
    con = memoria.conectar()
    try:
        conversacion.recibir(con, "¿sigues ahí?")
    finally:
        con.close()
    medidas = {}
    for ruta, ancho, alto in (("/secretario", 390, 844), ("/", 1200, 900)):
        contexto = navegador.new_context(viewport={"width": ancho, "height": alto})
        contexto.add_init_script("try { localStorage.setItem('hub.secretario.abierto', '1'); } catch (e) {}")
        pagina = contexto.new_page()
        pagina.goto(base + ruta, wait_until="load")
        pagina.wait_for_function("document.getElementById('estado-sec').dataset.tono === 'aviso'", timeout=15000)
        medidas[ruta] = pagina.evaluate("""() => {
          const e = document.getElementById('estado-sec'), a = document.getElementById('sec-apagado');
          const muestra = document.createElement('span');
          muestra.style.color = 'var(--espera)';
          document.body.append(muestra);
          const espera = getComputedStyle(muestra).color;
          muestra.remove();
          return { texto: e.textContent, tono: getComputedStyle(e).color === espera,
                   enlace: !a.hidden && a.getBoundingClientRect().width > 0 ? a.getAttribute('href') : null,
                   ancho: document.documentElement.scrollWidth };
        }""")
        contexto.close()
    for ruta, m in medidas.items():
        assert "no está en marcha" in m["texto"] and m["tono"] and m["enlace"] == "/secretario", (ruta, m)
    assert medidas["/secretario"]["ancho"] <= 390 and medidas["/"]["ancho"] <= 1200, medidas



_PINTAR_TALLERES = """d => {
  document.querySelector('[data-datos]').textContent = JSON.stringify(d);
  document.dispatchEvent(new CustomEvent('hub:repintado', {detail: {regiones: ['talleres']}}));
}"""


def test_los_talleres_ponen_cada_subagente_en_su_estacion_y_el_titulo_como_texto(chromium):
    """Una sesión con tres investigadores y seis ayudantes (C-0220): los tres
    en la alquimia, cuatro en la entrada y «+2»; si se va uno con sitio, el
    siguiente entra. Cerrada estando quieta, no deja nada programado (revisor),
    y una muestra vieja se dice. Y el título de un panel, que lo escribe
    cualquier programa, sale como texto: esta página comparte origen con la
    terminal."""
    from datetime import datetime, timezone
    base, navegador = chromium
    contexto = navegador.new_context(viewport={"width": 1200, "height": 900})
    pagina = contexto.new_page()
    errores = []
    pagina.on("pageerror", lambda e: errores.append(str(e)))
    pagina.goto(base + "/talleres", wait_until="load")
    # El hub sembrado no tiene sesiones: su sondeo borraría lo que se inyecta.
    pagina.evaluate("window.HubSinRecarga.refrescar = async () => []")
    malo = "<img src=x onerror=window.__malo=1>"
    subs = ([{"id": f"i{n}", "rol": "investigador", "tipo": "investigador", "inicial": "I", "que": f"Fuente {n}",
              "estacion": "alquimia"} for n in range(3)]
            + [{"id": f"a{n}", "rol": "ayudante", "tipo": "general-purpose", "inicial": "G", "que": f"Parte {n}",
                "estacion": "entrada"} for n in range(6)])
    taller = {"clave": "%1:s", "agente": "Claude Code", "proyecto": "demo", "nombre": malo,
              "estado": "trabajando", "subagentes": subs}
    ahora = datetime.now(timezone.utc).isoformat()
    pagina.evaluate(_PINTAR_TALLERES, {"tomado_en": ahora, "talleres": [taller]})
    pagina.wait_for_timeout(600)
    assert pagina.locator(".tll-taller").count() == 1
    assert pagina.locator(".tll-pj").count() == 1 + 3 + 4
    assert pagina.locator(".tll-mas").inner_text() == "+2"
    assert pagina.locator(".tll-taller h2 span").inner_text() == f"demo · {malo}"
    assert pagina.evaluate("window.__malo") is None

    # Se va uno que tenía sitio: el primero que esperaba entra en su hueco.
    sin_a0 = [s for s in subs if s["id"] != "a0"]
    pagina.evaluate(_PINTAR_TALLERES, {"tomado_en": ahora, "talleres": [{**taller, "subagentes": sin_a0}]})
    pagina.wait_for_timeout(300)
    assert pagina.locator(".tll-mas").inner_text() == "+1"
    pagina.wait_for_timeout(9000)
    assert pagina.locator(".tll-pj").count() == 1 + 3 + 4

    # La sesión se cierra estando quieta: no queda nada programado (sus «z»).
    quieta = {**taller, "estado": "quieta", "subagentes": []}
    pagina.evaluate(_PINTAR_TALLERES, {"tomado_en": ahora, "talleres": [quieta]})
    # Se van de uno en uno (cada una entrega su pergamino): hasta que no quede nadie.
    pagina.wait_for_function("document.querySelectorAll('.tll-pj').length === 1", timeout=60000)
    pagina.evaluate("""() => { window.__programados = 0; const st = window.setTimeout;
                             window.setTimeout = (f, ms) => { window.__programados++; return st(f, ms); }; }""")
    pagina.evaluate(_PINTAR_TALLERES, {"tomado_en": ahora, "talleres": []})
    pagina.wait_for_timeout(4000)
    assert pagina.locator(".tll-taller").count() == 0
    assert pagina.evaluate("window.__programados") == 0

    # Una muestra vieja se dice, en vez de pintarla como de ahora.
    pagina.evaluate(_PINTAR_TALLERES, {"tomado_en": "2026-01-01T00:00:00+00:00", "talleres": [taller]})
    assert pagina.locator("[data-vieja]").is_visible()
    ancho = pagina.evaluate("document.documentElement.scrollWidth")
    contexto.close()
    assert not errores, errores
    assert ancho <= 1200


# ── La interfaz nueva, detrás de su cookie (C-0169) ─────────────────────────
#
# Lo que se ve se mide en un navegador (regla dura 20): que el marco nuevo no
# rompa ninguna pantalla, que el secretario sea el panel flotante de siempre
# (C-0450), que la barra se pliegue sin romper /trabajo y que en el teléfono
# haya una sola barra.

from hub import interfaz  # noqa: E402

_nueva = pytest.mark.skipif(not interfaz.disponible(), reason="esta instalación no trae la interfaz nueva")
_con_tmux = pytest.mark.skipif(not shutil.which("tmux"), reason="hace falta tmux para abrir una terminal de verdad")


def _con_la_nueva(navegador, base, ancho, alto=900, **mas):
    movil = ancho < 700
    contexto = navegador.new_context(viewport={"width": ancho, "height": 844 if movil else alto},
                                     is_mobile=movil, has_touch=movil, locale="es-ES", **mas)
    contexto.add_cookies([{"name": interfaz.COOKIE, "value": interfaz.NUEVA, "url": base}])
    return contexto


_CAJAS = """() => {
  const caja = (sel) => { const e = document.querySelector(sel); if (!e) return null;
                          const r = e.getBoundingClientRect(); const c = getComputedStyle(e);
                          return { x: r.left, y: r.top, w: r.width, h: r.height, derecha: r.right, abajo: r.bottom,
                                   visible: c.display !== 'none' && r.width > 0 && r.height > 0, position: c.position }; };
  return { ancho: innerWidth, alto: innerHeight, documento: document.documentElement.scrollWidth,
           rail: caja('.rail-global'), contenido: caja('.principal-col'), panel: caja('#secretario-panel'),
           cuerpo: caja('#secretario-cuerpo'), abierto: !!document.querySelector('#secretario-panel.abierto'),
           interfaz: document.documentElement.dataset.interfaz || '' };
}"""


@_nueva
def test_la_interfaz_nueva_no_rompe_ninguna_pantalla(hub_sembrado):
    """El mismo recorrido de siempre, con la cookie: sin errores de JavaScript
    ni nada que se salga de lado, con el panel plegado y abierto. A tres
    anchos: el teléfono, el PC más estrecho y una pantalla grande. (Los seis del plan se miden con
    `python -m hub.recorrido --interfaz nueva --anchos 390,860,861,1024,1200,1750`.)"""
    base, registro = hub_sembrado
    _secretario_en_todo_el_hub()
    informe = recorrido.recorrer(base, anchos=(390, 861, 1750), interfaz=interfaz.NUEVA)
    assert not informe.fallos, (
        informe.texto() + "\n\nRegistro del servidor:\n" + registro.read_text()[-3000:])
    assert len(informe.visitadas) >= 25, informe.texto()
    assert not sorted(set(informe.sin_visitar) - set(SIN_ENLACE)), informe.sin_visitar


# El estado de la barra (C-0450) y lo que mueve: el raíl, el contenido, los
# dos botones y, en /trabajo, la lista de proyectos.
_BARRA = """() => {
  const caja = (sel) => { const e = document.querySelector(sel); if (!e) return null;
                          const r = e.getBoundingClientRect();
                          return { x: r.left, w: r.width, h: r.height, derecha: r.right,
                                   visible: getComputedStyle(e).display !== 'none' && r.width > 0 && r.height > 0 }; };
  let guardada = null;
  try { guardada = localStorage.getItem('hub.sinBarra'); } catch (e) {}
  return { barra: document.documentElement.dataset.barra || '', guardada,
           ancho: innerWidth, documento: document.documentElement.scrollWidth,
           rail: caja('.rail-global'), contenido: caja('.principal-col'),
           plegar: caja('.marco-plegar'), abrir: caja('.marco-desplegar'), lista: caja('.taller > .rail'),
           foco: (document.activeElement && document.activeElement.getAttribute('data-marco-barra')) || '' };
}"""


@_nueva
def test_con_la_nueva_el_secretario_es_el_panel_flotante_de_siempre(chromium):
    """C-0450: la tira acoplada se comía 68 px de todas las pantallas y,
    abierta, encogía el contenido. Ahora es la misma caja que con la de
    siempre, plegada y abierta; el contenido llega al borde derecho, y el
    panel vuelve a recordar cómo lo dejaste."""
    base, navegador = chromium
    medidas, errores = {}, []
    for cual in ("siempre", "nueva"):
        contexto = (navegador.new_context(viewport={"width": 1200, "height": 900}, locale="es-ES")
                    if cual == "siempre" else _con_la_nueva(navegador, base, 1200))
        pagina = contexto.new_page()
        pagina.on("pageerror", lambda e: errores.append(str(e)))
        pagina.goto(base + "/", wait_until="load")
        pagina.wait_for_timeout(300)
        plegado = pagina.evaluate(_CAJAS)
        pagina.click("#secretario-pestana")
        pagina.wait_for_function("document.querySelector('#secretario-panel.abierto')")
        pagina.wait_for_timeout(200)
        abierto = pagina.evaluate(_CAJAS)
        pagina.reload(wait_until="load")
        pagina.wait_for_timeout(300)
        recordado = pagina.evaluate(_CAJAS)
        medidas[cual] = (plegado, abierto, recordado)
        contexto.close()
    assert not errores, errores
    caja = lambda m: {k: round(m["panel"][k]) for k in ("x", "y", "w", "h")}   # noqa: E731
    for i, como in enumerate(("plegado", "abierto")):
        assert caja(medidas["nueva"][i]) == caja(medidas["siempre"][i]), (como, medidas["nueva"][i]["panel"])
        assert medidas["nueva"][i]["panel"]["position"] == "fixed"
    plegado, abierto, recordado = medidas["nueva"]
    assert plegado["interfaz"] == "nueva" and not plegado["abierto"] and abierto["cuerpo"]["visible"]
    for m in (plegado, abierto):
        # Sin columna a la derecha: el contenido es la ventana menos el raíl, y abrirlo no lo encoge.
        assert m["contenido"]["w"] == pytest.approx(1200 - m["rail"]["w"], abs=1), m
        assert m["contenido"]["derecha"] == pytest.approx(1200, abs=1) and m["documento"] <= 1200, m
    assert recordado["abierto"], "con la nueva, el panel no recordó que se dejó abierto"


@_nueva
def test_plegar_la_barra_deja_el_contenido_a_la_ventana_menos_la_franja(chromium):
    """La franja plegada mide lo justo para el botón de abrir: 36 px con 8 a
    cada lado. Se recuerda en este aparato: en la pantalla siguiente sigue
    plegada, y abrirla la devuelve como estaba."""
    base, navegador = chromium
    contexto = _con_la_nueva(navegador, base, 1200)
    pagina = contexto.new_page()
    errores = []
    pagina.on("pageerror", lambda e: errores.append(str(e)))
    pagina.goto(base + "/", wait_until="load")
    abierta = pagina.evaluate(_BARRA)
    assert abierta["barra"] == "" and abierta["plegar"]["visible"] and not abierta["abrir"]["visible"], abierta
    assert abierta["contenido"]["w"] == pytest.approx(1200 - abierta["rail"]["w"], abs=1)

    pagina.click(".marco-plegar")
    plegada = pagina.evaluate(_BARRA)
    assert plegada["barra"] == "plegada" and plegada["guardada"] == "true", plegada
    assert plegada["abrir"]["visible"] and not plegada["plegar"]["visible"], plegada
    assert plegada["rail"]["w"] == 52 and plegada["abrir"]["w"] == 36, plegada
    assert plegada["abrir"]["x"] - plegada["rail"]["x"] == pytest.approx(8, abs=0.5), plegada
    assert plegada["contenido"]["w"] == pytest.approx(1200 - 52, abs=1), plegada
    assert plegada["contenido"]["derecha"] == pytest.approx(1200, abs=1) and plegada["documento"] <= 1200
    # De la marca a «vista previa», nada del menú se ve.
    a_la_vista = pagina.evaluate("""() => [...document.querySelector('.rail-global').children]
        .filter((e) => getComputedStyle(e).display !== 'none').map((e) => e.className)""")
    assert a_la_vista == ["icono-solo marco-desplegar"], a_la_vista

    pagina.goto(base + "/maquina", wait_until="load")
    assert pagina.evaluate(_BARRA)["barra"] == "plegada"
    pagina.click(".marco-desplegar")
    otra_vez = pagina.evaluate(_BARRA)
    assert otra_vez["barra"] == "" and otra_vez["guardada"] == "false", otra_vez
    assert otra_vez["rail"]["w"] == abierta["rail"]["w"] and otra_vez["plegar"]["visible"], otra_vez
    contexto.close()
    assert not errores, errores


@_nueva
def test_a_los_dos_botones_se_llega_con_tab_y_enter_los_acciona(chromium):
    """El primer Tab es «Saltar al contenido»; el segundo, plegar. El que se
    pulsa desaparece, así que el foco pasa al otro y se ve dónde está."""
    base, navegador = chromium
    contexto = _con_la_nueva(navegador, base, 1200)
    pagina = contexto.new_page()
    pagina.goto(base + "/", wait_until="load")
    pagina.keyboard.press("Tab")
    pagina.keyboard.press("Tab")
    assert pagina.evaluate(_BARRA)["foco"] == "plegar"
    anillo = "() => { const c = getComputedStyle(document.activeElement); return [c.outlineStyle, parseFloat(c.outlineWidth)]; }"
    assert pagina.evaluate(anillo)[0] != "none" and pagina.evaluate(anillo)[1] >= 2
    pagina.keyboard.press("Enter")
    m = pagina.evaluate(_BARRA)
    assert m["barra"] == "plegada" and m["foco"] == "abrir" and m["abrir"]["visible"], m
    assert pagina.evaluate(anillo)[0] != "none"
    pagina.keyboard.press("Enter")
    m = pagina.evaluate(_BARRA)
    assert m["barra"] == "" and m["foco"] == "plegar" and m["plegar"]["visible"], m
    contexto.close()


@_nueva
def test_en_el_telefono_la_barra_no_se_pliega_ni_se_ofrece(chromium):
    """Con `hub.sinBarra` guardado desde el PC: aquí el menú es la barra de
    abajo y la lista de proyectos, el `select`. Siguen los dos."""
    base, navegador = chromium
    contexto = _con_la_nueva(navegador, base, 390)
    contexto.add_init_script("try { localStorage.setItem('hub.sinBarra', 'true'); } catch (e) {}")
    pagina = contexto.new_page()
    for ruta in ("/", "/trabajo"):
        pagina.goto(base + ruta, wait_until="load")
        pagina.wait_for_timeout(300)
        m, cajas = pagina.evaluate(_BARRA), pagina.evaluate(_CAJAS)
        assert m["barra"] == "" and m["guardada"] == "true", (ruta, m)
        assert not m["plegar"]["visible"] and not m["abrir"]["visible"], (ruta, m)
        assert cajas["rail"]["visible"] and cajas["rail"]["w"] == 390, (ruta, cajas["rail"])
        assert cajas["rail"]["abajo"] == pytest.approx(cajas["alto"], abs=1), (ruta, cajas["rail"])
    assert pagina.locator("#ir-a").is_visible()
    contexto.close()


_TERMINAL = """() => {
  const r = (sel) => { const e = document.querySelector(sel); return e ? e.getBoundingClientRect() : null; };
  const marco = r('#marco'), pantalla = r('#marco .xterm-screen'), lienzo = r('#lienzo-terminal');
  return { alto: innerHeight, ancho: innerWidth, documento: document.documentElement.scrollWidth,
           marco: marco && { w: marco.width, derecha: marco.right, abajo: marco.bottom },
           pantalla: pantalla && { w: pantalla.width, derecha: pantalla.right, abajo: pantalla.bottom },
           lienzo: lienzo && { abajo: lienzo.bottom },
           columnas: (document.getElementById('cols') || {}).textContent || '' };
}"""


def _columnas(pagina) -> int:
    """Las columnas de la terminal cuando ella y tmux están de acuerdo: la
    propia pantalla lo dice («116 col»; si no casan, «116 col · tmux 120»)."""
    pagina.wait_for_function(
        "/^\\d+ col$/.test((document.getElementById('cols') || {}).textContent || '')", timeout=15_000)
    return int(pagina.evaluate("document.getElementById('cols').textContent").split()[0])


@_nueva
@_con_tmux
def test_en_trabajo_abrir_y_plegar_el_secretario_no_mueve_la_terminal(chromium):
    """Flota sobre la esquina, como en la de siempre: ni una columna de
    cambio, así que la ventana de tmux no se reajusta por hablar con él."""
    base, navegador = chromium
    contexto = _con_la_nueva(navegador, base, 1200)
    pagina = contexto.new_page()
    pagina.goto(base + "/trabajo", wait_until="load")
    al_llegar = _columnas(pagina)
    for _ in range(2):          # abrir y plegar
        pagina.keyboard.press("Control+.")
        pagina.wait_for_timeout(900)
        assert _columnas(pagina) == al_llegar
        m = pagina.evaluate(_TERMINAL)
        assert m["pantalla"]["derecha"] <= m["marco"]["derecha"] + 1 and m["documento"] <= 1200, m
    assert pagina.evaluate("document.querySelector('#secretario-panel.abierto')") is None
    contexto.close()


@_nueva
@_con_tmux
def test_plegar_la_barra_en_trabajo_da_columnas_a_la_terminal_y_abrirla_las_devuelve(chromium):
    base, navegador = chromium
    contexto = _con_la_nueva(navegador, base, 1200)
    pagina = contexto.new_page()
    pagina.goto(base + "/trabajo", wait_until="load")
    al_llegar = _columnas(pagina)
    assert pagina.evaluate(_BARRA)["lista"]["visible"]

    pagina.click(".marco-plegar")
    pagina.wait_for_function(f"parseInt(document.getElementById('cols').textContent) > {al_llegar}", timeout=15_000)
    plegada = _columnas(pagina)
    m, b = pagina.evaluate(_TERMINAL), pagina.evaluate(_BARRA)
    assert not b["lista"]["visible"] and b["rail"]["w"] == 52, b
    assert m["pantalla"]["derecha"] <= m["marco"]["derecha"] + 1, m    # no se sale de su marco
    assert m["pantalla"]["abajo"] <= m["marco"]["abajo"] + 1, m        # ni pierde la última línea
    assert m["lienzo"]["abajo"] <= m["alto"] + 1 and m["documento"] <= 1200, m

    pagina.click(".marco-desplegar")
    pagina.wait_for_function(f"parseInt(document.getElementById('cols').textContent) < {plegada}", timeout=15_000)
    assert _columnas(pagina) == al_llegar
    assert pagina.evaluate(_BARRA)["lista"]["visible"]
    print(f"\n[C-0450] /trabajo a 1200 px: {al_llegar} columnas con la barra, {plegada} plegada")
    contexto.close()


# Lo que se pinta en cada fotograma desde el primero: el ancho del raíl y si
# la lista de /trabajo se ve. Y el desplazamiento acumulado al cargar.
_FOTOGRAMAS = """(() => {
  const f = window.__fotogramas = [];
  window.__desplazado = 0;
  window.__quien = [];
  try { new PerformanceObserver((l) => { for (const e of l.getEntries()) if (!e.hadRecentInput) {
          window.__desplazado += e.value;
          for (const s of e.sources || []) window.__quien.push([s.node ? (s.node.id || s.node.className || s.node.nodeName) : '?',
                                                                Math.round(s.previousRect.width), Math.round(s.currentRect.width),
                                                                Math.round(s.previousRect.x), Math.round(s.currentRect.x)]);
        } }).observe({ type: 'layout-shift', buffered: true }); } catch (e) {}
  const mirar = () => {
    const rail = document.querySelector('.rail-global'), lista = document.querySelector('.taller > .rail');
    if (rail) f.push([Math.round(rail.getBoundingClientRect().width),
                      lista ? getComputedStyle(lista).display : 'aún no']);
    if (f.length < 60) requestAnimationFrame(mirar);
  };
  requestAnimationFrame(mirar);
})();"""


@_nueva
@_con_tmux
def test_recargando_plegada_hay_un_solo_ajuste_y_el_rail_no_parpadea(chromium):
    """Plegada desde antes de pintar: ni un fotograma con el menú entero o la
    lista de proyectos, y la ventana de tmux recibe un solo tamaño.

    Puesta por el script de la vista, la lista se veía dos fotogramas y se
    iba. Lo que aún se desplaza al cargar (0,045 a 0,056 medido a 1200 px;
    abierta, 0,004) es la fila de pestañas de ventana que enseña `sin-rail`, que se
    llena cuando llega la lista de ventanas: lo mismo que con el preset «Foco»,
    que en la de siempre da 0,242 porque además esconde la lista tarde."""
    base, navegador = chromium
    contexto = _con_la_nueva(navegador, base, 1200)
    contexto.add_init_script("try { localStorage.setItem('hub.sinBarra', 'true'); } catch (e) {}")
    contexto.add_init_script(_FOTOGRAMAS)
    pagina = contexto.new_page()
    tamanos = []

    def al_abrir(ws):
        ws.on("framesent", lambda carga: tamanos.append(json.loads(carga)["columnas"])
              if isinstance(carga, str) and '"columnas"' in carga else None)
    pagina.on("websocket", al_abrir)
    pagina.goto(base + "/trabajo", wait_until="load")
    columnas = _columnas(pagina)
    pagina.wait_for_timeout(600)
    fotogramas = pagina.evaluate("window.__fotogramas")
    assert fotogramas, "no se midió ningún fotograma: esto no prueba nada"
    assert {ancho for ancho, _ in fotogramas} == {52}, fotogramas
    assert {lista for _, lista in fotogramas} <= {"none", "aún no"}, fotogramas
    assert tamanos and set(tamanos) == {columnas}, tamanos
    desplazado, quien = pagina.evaluate("window.__desplazado"), pagina.evaluate("window.__quien")
    print(f"\n[C-0450] recarga plegada: {len(fotogramas)} fotogramas, tamaños enviados {tamanos}, "
          f"desplazamiento {desplazado:.3f}")
    # Ni el raíl ni la lista se mueven, y la terminal no salta de lado.
    assert not [q for q in quien if "rail" in str(q[0])], quien
    assert all(q[3] == q[4] for q in quien if q[0] == "lienzo-terminal"), quien
    assert desplazado < 0.1, (desplazado, quien)
    contexto.close()


# Cuánto de la última línea de la terminal tapa la pestaña flotante, con la
# nota plegada (y la terminal, por tanto, hasta el borde derecho).
_TAPA = """() => {
  const filas = [...document.querySelectorAll('#marco .xterm-rows > div')];
  const pantalla = document.querySelector('#marco .xterm-screen').getBoundingClientRect();
  const columnas = parseInt(document.getElementById('cols').textContent);
  const celda = pantalla.width / columnas;
  const panel = document.getElementById('secretario-panel').getBoundingClientRect();
  const figura = document.querySelector('#secretario-pestana > .pj').getBoundingClientRect();
  const corte = (a, b) => ({ ancho: Math.max(0, Math.min(a.right, b.right) - Math.max(a.left, b.left)),
                             alto: Math.max(0, Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top)) });
  const tapadas = (caja) => filas.filter((f) => corte(f.getBoundingClientRect(), caja).alto > 0).length;
  const ultima = filas[filas.length - 1].getBoundingClientRect();
  const enLaUltima = corte(ultima, panel);
  return { columnas, celda, filas: filas.length, altoFila: ultima.height,
           panel: { izquierda: panel.left, arriba: panel.top, ancho: panel.width, alto: panel.height },
           figuraArriba: figura.top,
           filasTapadas: tapadas(panel), filasTapadasConFigura: tapadas({ left: figura.left, right: figura.right,
                                                                      top: figura.top, bottom: panel.bottom }),
           columnasTapadas: Math.round(enLaUltima.ancho / celda * 10) / 10,
           figuraColumnas: Math.round(figura.width / celda * 10) / 10,
           desdeColumna: Math.floor((panel.left - pantalla.left) / celda) + 1,
           sinNota: document.getElementById('taller').classList.contains('sin-nota') };
}"""


@_nueva
@_con_tmux
def test_con_la_nota_plegada_la_pestana_flotante_tapa_el_final_de_la_ultima_linea(chromium):
    """Lo que el dueño se lleva de vuelta (C-0450): como en la de siempre, la
    pestaña plegada se monta sobre la esquina de abajo a la derecha. Medido a
    1200×900 con la nota plegada (96 columnas, filas de 16 px): tapa las dos
    últimas líneas desde la columna 53, 43 de 96, y el personaje asoma sobre
    una tercera en unas 5 columnas. Reservarle sitio quedó fuera del cambio."""
    base, navegador = chromium
    contexto = _con_la_nueva(navegador, base, 1200)
    pagina = contexto.new_page()
    pagina.goto(base + "/trabajo", wait_until="load")
    con_nota = _columnas(pagina)
    pagina.click("#plegar-lado")
    pagina.wait_for_function(f"parseInt(document.getElementById('cols').textContent) > {con_nota}", timeout=15_000)
    _columnas(pagina)
    pagina.wait_for_timeout(400)
    m = pagina.evaluate(_TAPA)
    print(f"\n[C-0450] pestaña sobre la terminal: {m}")
    assert m["sinNota"] and not pagina.evaluate("document.querySelector('#secretario-panel.abierto')")
    assert m["filasTapadas"] == 2 and m["filasTapadasConFigura"] == 3, m
    assert 40 <= m["columnasTapadas"] <= 46 and m["figuraColumnas"] <= 6, m
    contexto.close()


@_nueva
def test_en_el_telefono_hay_una_sola_barra_abajo_y_el_panel_no_se_pinta(chromium):
    base, navegador = chromium
    contexto = _con_la_nueva(navegador, base, 390)
    pagina = contexto.new_page()
    for ruta in ("/", "/maquina", "/trabajo"):
        pagina.goto(base + ruta, wait_until="load")
        pagina.wait_for_timeout(300)
        for abajo in (False, True):
            if abajo:
                pagina.evaluate("window.scrollTo(0, document.documentElement.scrollHeight)")
                pagina.wait_for_timeout(150)
            m = pagina.evaluate(_CAJAS)
            assert m["rail"]["visible"] and m["rail"]["w"] == 390, (ruta, m)
            assert m["rail"]["abajo"] == pytest.approx(m["alto"], abs=1), (ruta, abajo, m)   # pegada al borde
            assert not m["panel"]["visible"] and m["documento"] <= 390, (ruta, m)
        # En el orden del DOM, que es el del tabulador: tiene que ser el que se ve.
        a_la_vista = pagina.evaluate("""() => [...document.querySelectorAll('.rail-global > .marco-destino, .marco-mas > summary')]
            .filter((e) => e.getBoundingClientRect().width > 0)
            .map((e) => [e.innerText.trim().replace(/\\s+\\d+$/, ''), Math.round(e.getBoundingClientRect().left)])""")
        assert [n for n, _ in a_la_vista] == ["Secretario", "Trabajo", "Hoy", "Ideas", "Más"], (ruta, a_la_vista)
        izquierdas = [x for _, x in a_la_vista]
        assert izquierdas == sorted(izquierdas), f"el tabulador no sigue lo que se ve: {a_la_vista}"
        # Al final de la página, lo último queda por encima de la barra.
        ultimo = pagina.evaluate("document.querySelector('.envoltura').getBoundingClientRect().bottom")
        assert ultimo <= pagina.evaluate(_CAJAS)["rail"]["y"] + 1, ruta

    # /secretario ya trae su barra: la del hub se esconde con el raíl.
    pagina.goto(base + "/secretario", wait_until="load")
    fijas = pagina.evaluate("""() => [...document.querySelectorAll('.rail-global, .sec-nav')]
        .filter((e) => getComputedStyle(e).display !== 'none' && e.getBoundingClientRect().height > 0)
        .map((e) => e.className.split(' ')[0])""")
    assert fijas == ["sec-nav"], fijas
    # Sus pestañas de ajuste son de Ajustes y en el PC traen su tira; aquí es
    # su app: sin la cabecera del hub tampoco hay tira, y sigue habiendo una barra.
    pagina.goto(base + "/secretario?p=avisos", wait_until="load")
    assert pagina.locator(".marco-tira").count() == 1 and not pagina.locator(".marco-tira").is_visible()
    assert pagina.locator(".sec-nav").is_visible() and not pagina.locator(".rail-global").is_visible()
    contexto.close()


@_nueva
@pytest.mark.skipif(not shutil.which("tmux"), reason="hace falta tmux para abrir una terminal de verdad")
def test_en_el_telefono_la_barra_no_tapa_la_ultima_linea_de_la_terminal(chromium):
    """C-0229, con la barra nueva: al llegar, la terminal entera queda por
    encima; a solas o con el teclado, la barra se va y no deja su hueco."""
    base, navegador = chromium
    contexto = _con_la_nueva(navegador, base, 390)
    pagina = contexto.new_page()
    pagina.goto(base + "/trabajo", wait_until="load")
    pagina.wait_for_selector("#marco .xterm-screen")
    pagina.wait_for_timeout(500)
    m, cajas = pagina.evaluate(_TERMINAL), pagina.evaluate(_CAJAS)
    assert m["lienzo"]["abajo"] <= cajas["rail"]["y"] + 1, (m, cajas["rail"])
    assert m["pantalla"]["abajo"] <= m["marco"]["abajo"] + 1 and m["documento"] <= 390, m

    for clase in ("terminal-sola", "teclado-abierto"):
        pagina.evaluate(f"document.body.classList.add('{clase}'); window.dispatchEvent(new Event('resize'))")
        pagina.wait_for_timeout(400)
        cajas, m = pagina.evaluate(_CAJAS), pagina.evaluate(_TERMINAL)
        assert not cajas["rail"]["visible"], clase
        assert cajas["contenido"]["h"] == pytest.approx(cajas["alto"], abs=1), (clase, cajas["contenido"])
        assert m["lienzo"]["abajo"] == pytest.approx(m["alto"], abs=1), (clase, m)   # hasta abajo, sin hueco
        assert m["pantalla"]["abajo"] <= m["alto"] + 1, (clase, m)
        pagina.evaluate(f"document.body.classList.remove('{clase}'); window.dispatchEvent(new Event('resize'))")
    contexto.close()


@_nueva
def test_en_el_telefono_la_barra_mide_lo_que_dice_su_token(chromium):
    """De `--marco-barra` salen el velo de «Más», el sitio del asistente de
    antes y lo que se deja libre al enfocar un campo: decía 60 y medía 64."""
    base, navegador = chromium
    contexto = _con_la_nueva(navegador, base, 390)
    pagina = contexto.new_page()
    pagina.goto(base + "/tablero", wait_until="load")
    m = pagina.evaluate("""() => ({
      barra: document.querySelector('.rail-global').getBoundingClientRect().height,
      token: parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--marco-barra')) })""")
    assert m["barra"] == m["token"] == 64, m
    pagina.tap("#marco-mas > summary")
    velo = pagina.evaluate("""() => { const v = getComputedStyle(document.querySelector('#marco-mas > summary'), '::before');
      return innerHeight - parseFloat(v.bottom); }""")
    assert velo == pytest.approx(pagina.locator(".rail-global").bounding_box()["y"], abs=0.5)   # hasta la barra, justo
    contexto.close()


@_nueva
def test_en_el_telefono_un_campo_enfocado_no_se_queda_debajo_de_la_barra(chromium):
    """En /tablero el desplegable de proyecto caía bajo la barra: el navegador
    lo daba por visible y no lo subía. Con una pantalla baja, que es donde pasa."""
    base, navegador = chromium
    contexto = navegador.new_context(viewport={"width": 390, "height": 700}, is_mobile=True, has_touch=True)
    contexto.add_cookies([{"name": interfaz.COOKIE, "value": interfaz.NUEVA, "url": base}])
    pagina = contexto.new_page()
    pagina.goto(base + "/tablero", wait_until="load")
    medir = """() => { const s = document.querySelector('select[name=proyecto]').getBoundingClientRect();
      return { abajo: s.bottom, barra: document.querySelector('.rail-global').getBoundingClientRect().top }; }"""
    antes = pagina.evaluate(medir)
    assert antes["abajo"] > antes["barra"], f"el campo ya no cae bajo la barra: esto no prueba nada ({antes})"
    pagina.evaluate("document.querySelector('select[name=proyecto]').focus()")
    pagina.wait_for_timeout(300)
    despues = pagina.evaluate(medir)
    assert despues["abajo"] <= despues["barra"], despues
    contexto.close()


@_nueva
def test_en_el_telefono_la_tira_va_en_una_linea_con_la_pantalla_de_ahora_a_la_vista(chromium):
    """Ajustes tiene siete pantallas: partida en filas, la tira se comía 200 px.
    Se mira en el banco de dictado, que está casi al final de la tira."""
    base, navegador = chromium
    contexto = _con_la_nueva(navegador, base, 390)
    pagina = contexto.new_page()
    errores = []
    pagina.on("pageerror", lambda e: errores.append(str(e)))
    pagina.goto(base + "/voz/banco", wait_until="load")
    pagina.wait_for_timeout(300)
    m = pagina.evaluate("""() => {
      const tira = document.querySelector('.marco-tira'), aqui = tira.querySelector('.aqui').getBoundingClientRect();
      const cajas = [...tira.querySelectorAll('a')].map((a) => a.getBoundingClientRect());
      return { alto: tira.getBoundingClientRect().height, altos: cajas.map((c) => c.height),
               filas: new Set(cajas.map((c) => Math.round(c.top))).size, enlaces: cajas.length,
               aqui: [aqui.left, aqui.right], texto: tira.querySelector('.aqui').innerText.trim(),
               documento: document.documentElement.scrollWidth,
               dentro: !!tira.closest('.envoltura > header'),
               seccion: document.querySelector('.marco-mas > summary').classList.contains('aqui') }; }""")
    assert m["texto"] == "Banco de dictado" and m["seccion"], m          # es de Ajustes, que va en «Más»
    assert m["enlaces"] == 7 and m["filas"] == 1 and m["alto"] <= 48, m
    assert min(m["altos"]) >= 44, m                                       # a dedo
    assert 0 <= m["aqui"][0] and m["aqui"][1] <= 390, m                  # a la vista sin deslizar
    assert m["documento"] <= 390 and m["dentro"], m
    # Y la barra no tapa lo último de la pantalla.
    pagina.evaluate("window.scrollTo(0, document.documentElement.scrollHeight)")
    assert pagina.evaluate("document.querySelector('.envoltura').getBoundingClientRect().bottom") <= \
        pagina.locator(".rail-global").bounding_box()["y"] + 1
    contexto.close()
    assert not errores, errores


@_nueva
def test_mas_se_abre_y_se_cierra_en_el_telefono(chromium):
    base, navegador = chromium
    contexto = _con_la_nueva(navegador, base, 390)
    pagina = contexto.new_page()
    pagina.goto(base + "/maquina", wait_until="load")
    hoja = pagina.locator(".marco-hoja")
    assert not hoja.is_visible()
    # Con la página a medias: tocar la barra no puede moverla. Pasó al dejar
    # sitio para el foco con `scroll-padding` —la barra vive dentro de ese
    # margen y el navegador intentaba «traerla a la vista»—.
    pagina.evaluate("window.scrollTo(0, 150)")
    pagina.tap("#marco-mas > summary")
    assert hoja.is_visible()
    assert pagina.evaluate("scrollY") == 150
    caja = hoja.bounding_box()
    barra = pagina.locator(".rail-global").bounding_box()
    assert caja["x"] == 0 and caja["width"] == 390 and caja["y"] >= 0
    assert caja["y"] + caja["height"] == pytest.approx(barra["y"], abs=1)      # encima de la barra, sin taparla
    assert pagina.locator(".marco-hoja a[aria-current=page]").inner_text().strip() == "Máquina"
    pagina.keyboard.press("Escape")
    assert not hoja.is_visible()
    pagina.tap("#marco-mas > summary")
    pagina.touchscreen.tap(195, 40)        # fuera: sobre la página
    assert not hoja.is_visible()
    pagina.tap("#marco-mas > summary")
    pagina.tap(".marco-hoja a[href='/respaldo']")
    pagina.wait_for_url(base + "/respaldo")
    contexto.close()


@_nueva
def test_sin_javascript_se_navega_se_abre_mas_y_se_apaga_la_interfaz(chromium):
    """Tiene que poder apagarse siempre, también desde el teléfono y aunque
    el script no cargue: enlaces, un `<details>` y un formulario normal."""
    base, navegador = chromium
    contexto = _con_la_nueva(navegador, base, 390, java_script_enabled=False)
    pagina = contexto.new_page()
    pagina.goto(base + "/", wait_until="load")
    assert pagina.locator("html[data-interfaz=nueva]").count() == 1
    pagina.tap(".rail-global > a.marco-destino.de-barra[href='/trabajo']")
    pagina.wait_for_url(base + "/trabajo")
    pagina.tap("#marco-mas > summary")
    assert pagina.locator(".marco-hoja").is_visible()
    pagina.touchscreen.tap(195, 40)        # el velo es del `summary`: cierra sin script
    assert not pagina.locator(".marco-hoja").is_visible()
    pagina.tap("#marco-mas > summary")
    pagina.tap(".marco-hoja-pie")
    pagina.wait_for_url(base + "/guia#interfaz")
    # Los colores (fase 1b) también se eligen sin script: su formulario, su 303.
    assert pagina.locator("html[data-colores=pizarra]").count() == 1
    with pagina.expect_navigation():
        pagina.locator("#colores form[data-colores=brasa] button").tap()
    assert pagina.locator("html[data-interfaz=nueva][data-colores=brasa]").count() == 1
    assert pagina.locator("#colores form[data-colores=brasa] button").count() == 0   # el que está en uso no se ofrece
    # El interruptor comparte sección con el catálogo: se le nombra por su formulario.
    interruptor = "#interfaz form[action='/interfaz'] button"
    with pagina.expect_navigation():       # el POST y su 303: ya se estaba en /guia
        pagina.locator(interruptor).tap()
    assert urlsplit(pagina.url).path == "/guia"
    assert pagina.locator("html[data-interfaz=nueva]").count() == 0
    assert pagina.locator("#colores").count() == 0          # con la de siempre no hay catálogo
    assert pagina.locator(interruptor).inner_text().strip() == "Probar la interfaz nueva"
    assert not [c for c in contexto.cookies() if c["name"] == interfaz.COOKIE]
    with pagina.expect_navigation():
        pagina.locator(interruptor).tap()
    assert urlsplit(pagina.url).path == "/"
    assert pagina.locator("html[data-interfaz=nueva]").count() == 1
    contexto.close()
