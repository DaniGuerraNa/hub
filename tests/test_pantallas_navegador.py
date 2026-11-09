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
        if shutil.which("tmux"):
            subprocess.run([*tmux.orden_base(), "kill-server"],
                           capture_output=True, check=False, timeout=10)


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
