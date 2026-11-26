"""El control vuelve a la persona cuando Claude acaba el encargo, no tras cada tarea (C-0486).

Con el aparato real: la persona pidió cambios en dos párrafos y dio el
control; Claude escribió el primero y lo perdió, porque escribir lo devolvía
al terminar, y el segundo no se hizo. Al leer, igual: una captura mala ya no
se podía repetir. Ahora lo devuelve el final del turno de Claude (su `Stop`),
una pregunta suya o un encargo cortado con Esc; y si el puente no sabe qué
turno corre (sin hooks, sin conversación del registro), tras cada tarea,
como antes.
"""

import json
import re
import time
import uuid

import pytest

from puente_kvm import comprobar, config, conversaciones, repertorio

from .ayuda import PERSONA, esperar, leer, proponer_y_aprobar, puente_simulado, transcribir_como_oraculo


@pytest.fixture
def entorno():
    with puente_simulado() as (c, sim):
        yield c, sim


def abierta() -> str:
    """La conversación abierta del registro, sin abrir la terminal: sólo su id."""
    conv = conversaciones.nueva("Encargo", "")
    conversaciones.marcar_abierta(conv.id)
    return conv.id


def hook(c, evento: str, sesion: str | None, **extra) -> None:
    datos = {"hook_event_name": evento, **extra}
    if sesion:
        datos["session_id"] = sesion
    assert c.post("/api/claude/actividad", json=datos).status_code == 200


def control(c) -> dict:
    return c.get("/api/estado").json()["control"]


def dar(c) -> None:
    assert c.post("/api/control", json={"accion": "dar"}, headers=PERSONA).status_code == 200


def lineas_de_control(c) -> list[dict]:
    return [e for e in c.get("/api/bitacora").json() if e["tipo"] == "control"]


# ── con hooks de la conversación abierta ────────────────────────────────────
def test_con_el_encargo_en_curso_el_control_sigue_tras_escribir_y_el_segundo_cambio_se_escribe(entorno):
    c, sim = entorno
    sesion = abierta()
    hook(c, "UserPromptSubmit", sesion)
    lid = leer(c)
    assert control(c)["modo"] == "claude"  # acabó la lectura: una captura mala se podría repetir
    transcribir_como_oraculo(c, sim, lid)
    primero = list(sim.editor.guardado)
    primero[10] += " -- párrafo 1"
    cid = proponer_y_aprobar(c, lid, primero, "párrafo 1")
    assert c.post(f"/api/cambios/{cid}/escribir").status_code == 200
    esperar(c)
    assert c.get(f"/api/cambios/{cid}").json()["estado"] == "escrito"
    assert control(c)["modo"] == "claude"
    # La página del cambio no le dice que ya le toca: Claude sigue.
    assert re.search(r'id="escrito-claude-sigue"\s*>', c.get(f"/cambios/{cid}").text)
    assert lineas_de_control(c)[-1]["detalle"] == ("terminó de escribir; Claude sigue con el control hasta que "
                                                   "termine el encargo")

    # El segundo, sobre una lectura nueva (compara con sus capturas), sin que nadie vuelva a dar el control.
    r = c.post("/api/lecturas", json={"nombre": "usp_ConciliarMovimientos"})
    assert r.status_code == 200, r.text
    esperar(c)
    sim.editor.guardado = list(sim.editor.lineas)  # lo que muestra ahora el editor, para el lector
    lid2 = r.json()["id"]
    transcribir_como_oraculo(c, sim, lid2)
    segundo = list(sim.editor.lineas)
    segundo[120] += " -- párrafo 2"
    cid2 = proponer_y_aprobar(c, lid2, segundo, "párrafo 2")
    assert c.post(f"/api/cambios/{cid2}/escribir").status_code == 200
    esperar(c)
    assert c.get(f"/api/cambios/{cid2}").json()["estado"] == "escrito"
    assert sim.editor.lineas[10].endswith("-- párrafo 1") and sim.editor.lineas[120].endswith("-- párrafo 2")
    assert control(c)["modo"] == "claude"

    hook(c, "Stop", sesion)
    assert control(c)["modo"] == "libre"
    assert re.search(r'id="escrito-claude-sigue"\s*hidden', c.get(f"/cambios/{cid2}").text)


def test_el_fin_de_turno_con_una_escritura_en_marcha_no_la_corta_y_el_mac_vuelve_al_acabar(entorno):
    """🔴 C-0488, visto con el aparato: Claude lanzó una escritura de ~55 min,
    avisó del progreso y terminó su turno; el `Stop` le quitó el control y el
    tecleo se cortó en la línea 204 de un HTML. Antes de C-0486 el control
    duraba hasta acabar la tarea: eso se conserva."""
    c, sim = entorno
    sesion = abierta()
    hook(c, "UserPromptSubmit", sesion)
    lid = leer(c)
    transcribir_como_oraculo(c, sim, lid)
    nuevo = list(sim.editor.guardado)
    for i in range(10, 40):
        nuevo[i] += " -- una línea bastante larga añadida para que escribir tarde un buen rato"
    cid = proponer_y_aprobar(c, lid, nuevo, "muchas líneas")
    assert c.post(f"/api/cambios/{cid}/escribir").status_code == 200
    fin = time.time() + 20
    while c.get(f"/api/cambios/{cid}").json()["estado"] != "escribiendo":
        assert time.time() < fin
        time.sleep(0.02)
    hook(c, "Stop", sesion)  # Claude avisa del progreso y termina su turno
    assert c.app.state.puente.motor.tarea, "la escritura tenía que seguir en marcha al llegar el Stop"
    assert control(c)["modo"] == "claude"
    assert "cuando acabe" in lineas_de_control(c)[-1]["detalle"]
    esperar(c)
    assert c.get(f"/api/cambios/{cid}").json()["estado"] == "escrito"
    assert all(sim.editor.lineas[i].endswith("buen rato") for i in range(10, 40))
    assert control(c)["modo"] == "libre"


def test_parar_sigue_cortando_una_escritura_en_marcha_en_el_acto(entorno):
    c, sim = entorno
    sesion = abierta()
    hook(c, "UserPromptSubmit", sesion)
    lid = leer(c)
    transcribir_como_oraculo(c, sim, lid)
    nuevo = list(sim.editor.guardado)
    for i in range(10, 40):
        nuevo[i] += " -- una línea bastante larga añadida para que escribir tarde un buen rato"
    cid = proponer_y_aprobar(c, lid, nuevo, "muchas líneas")
    assert c.post(f"/api/cambios/{cid}/escribir").status_code == 200
    fin = time.time() + 20
    while c.get(f"/api/cambios/{cid}").json()["estado"] != "escribiendo":
        assert time.time() < fin
        time.sleep(0.02)
    hook(c, "Stop", sesion)
    assert c.post("/api/control", json={"accion": "parar"}, headers=PERSONA).status_code == 200
    esperar(c)
    assert c.get(f"/api/cambios/{cid}").json()["estado"] == "fallido"
    assert control(c)["modo"] == "parado"


def test_retomar_y_volver_a_dar_el_control_olvida_la_devolucion_que_esperaba_a_la_escritura(entorno):
    """El `Stop` con una escritura en marcha deja la devolución pendiente
    (C-0488). Si la persona retoma el Mac y se lo vuelve a dar antes de que la
    escritura acabe, ese control es nuevo: acabar la escritura de antes no se
    lo puede quitar (lo encontró el revisor de la 0.15.0)."""
    import asyncio
    import threading

    c, sim = entorno
    p = c.app.state.puente
    sesion = abierta()
    hook(c, "UserPromptSubmit", sesion)
    lid = leer(c)
    transcribir_como_oraculo(c, sim, lid)
    nuevo = list(sim.editor.guardado)
    for i in range(10, 40):
        nuevo[i] += " -- una línea bastante larga añadida para que escribir tarde un buen rato"
    cid = proponer_y_aprobar(c, lid, nuevo, "muchas líneas")

    # Una puerta antes de cada tecla, para que Retomar y Dar lleguen entre dos
    # teclas sin depender de lo que tarde cada una.
    cerrada, en_la_puerta = threading.Event(), threading.Event()
    pulsar = p.motor._pulsar

    async def con_puerta(pulsacion):
        while cerrada.is_set():
            en_la_puerta.set()
            await asyncio.sleep(0.005)
        await pulsar(pulsacion)
    p.motor._pulsar = con_puerta

    assert c.post(f"/api/cambios/{cid}/escribir").status_code == 200
    fin = time.time() + 20
    while c.get(f"/api/cambios/{cid}").json()["estado"] != "escribiendo":
        assert time.time() < fin
        time.sleep(0.02)
    cerrada.set()
    assert en_la_puerta.wait(10)
    hook(c, "Stop", sesion)
    assert p.devolver_pendiente, "el Stop con la escritura en marcha deja la devolución pendiente"
    assert c.post("/api/control", json={"accion": "retomar"}, headers=PERSONA).status_code == 200
    assert p.devolver_pendiente is None, "Retomar ya devolvió el Mac: no queda nada que devolver al acabar"
    hook(c, "UserPromptSubmit", sesion)
    dar(c)
    cerrada.clear()
    esperar(c)
    assert control(c)["modo"] == "claude"
    assert control(c)["motivo"] == "dado en la pantalla"


def test_parar_y_usar_el_mac_tambien_olvidan_la_devolucion_pendiente(entorno):
    """Lo mismo por las otras puertas de la persona, sin escritura de por medio:
    lo que se comprueba es que pasan por `Puente.olvidar_pendiente`."""
    c, _ = entorno
    p = c.app.state.puente
    dar(c)
    p.devolver_pendiente, p.devolver_pendiente_por = "Claude terminó", "fin_turno"
    assert c.post("/api/control", json={"accion": "parar"}, headers=PERSONA).status_code == 200
    assert p.devolver_pendiente is None and p.devolver_pendiente_por is None
    dar(c)
    p.devolver_pendiente, p.devolver_pendiente_por = "Claude terminó", "fin_turno"
    with c.websocket_connect("/ws/mando", headers=PERSONA) as ws:
        assert "Le quitaste el control a Claude" in ws.receive_json()["aviso"]
    assert control(c)["modo"] == "libre"
    assert p.devolver_pendiente is None and p.devolver_pendiente_por is None


def test_el_stop_de_la_conversacion_abierta_devuelve_el_mac_y_lo_apunta(entorno):
    c, _ = entorno
    sesion = abierta()
    dar(c)
    hook(c, "UserPromptSubmit", sesion)
    hook(c, "Stop", sesion)
    e = control(c)
    assert e["modo"] == "libre" and e["motivo"] == "Claude terminó: el Mac vuelve a ti para revisar y guardar"
    ultima = lineas_de_control(c)[-1]
    assert ultima["quien"] == "puente" and ultima["detalle"] == e["motivo"]


def test_una_pregunta_de_claude_devuelve_el_mac(entorno):
    c, _ = entorno
    sesion = abierta()
    dar(c)
    hook(c, "UserPromptSubmit", sesion)
    hook(c, "PreToolUse", sesion, tool_name="AskUserQuestion", tool_input={})
    e = control(c)
    assert e["modo"] == "libre" and e["motivo"].startswith("Claude te pregunta algo")


def test_las_demas_herramientas_no_lo_devuelven(entorno):
    c, _ = entorno
    sesion = abierta()
    dar(c)
    hook(c, "UserPromptSubmit", sesion)
    hook(c, "PreToolUse", sesion, tool_name="mcp__puente-kvm__ver_pantalla", tool_input={})
    hook(c, "PreToolUse", sesion, tool_name="Read", tool_input={"file_path": "/x"})
    assert control(c)["modo"] == "claude"


@pytest.mark.parametrize("sesion", ["otra", None, "no-es-un-uuid"])
def test_el_stop_de_otra_sesion_no_hace_nada(entorno, sesion):
    """Los hooks están en el settings del proyecto: también los manda una
    sesión de desarrollo abierta en la carpeta del código."""
    c, _ = entorno
    abierta()
    dar(c)
    hook(c, "Stop", str(uuid.uuid4()) if sesion == "otra" else sesion)
    hook(c, "PreToolUse", str(uuid.uuid4()), tool_name="AskUserQuestion")
    assert control(c)["modo"] == "claude"


def test_sin_conversacion_del_registro_un_stop_no_hace_nada(entorno):
    c, _ = entorno
    dar(c)
    hook(c, "Stop", str(uuid.uuid4()))
    assert control(c)["modo"] == "claude"


# ── la red del Esc: un turno cortado no manda su Stop ───────────────────────
def test_un_mensaje_tras_un_encargo_cortado_devuelve_el_mac(entorno):
    c, _ = entorno
    sesion = abierta()
    dar(c)
    time.sleep(0.01)
    hook(c, "UserPromptSubmit", sesion)
    hook(c, "PreToolUse", sesion, tool_name="mcp__puente-kvm__ver_pantalla")
    # Esc: sin Stop. El siguiente mensaje lo delata.
    hook(c, "UserPromptSubmit", sesion)
    e = control(c)
    assert e["modo"] == "libre" and e["motivo"].startswith("el encargo anterior se cortó sin terminar")


def test_si_la_persona_dio_el_control_despues_del_corte_lo_conserva(entorno):
    c, _ = entorno
    sesion = abierta()
    hook(c, "UserPromptSubmit", sesion)
    time.sleep(0.01)
    dar(c)  # después del Esc: lo da para el mensaje que viene
    hook(c, "UserPromptSubmit", sesion)
    assert control(c)["modo"] == "claude"


def test_un_mensaje_tras_un_encargo_que_termino_no_lo_devuelve(entorno):
    c, _ = entorno
    sesion = abierta()
    hook(c, "UserPromptSubmit", sesion)
    hook(c, "Stop", sesion)
    dar(c)
    hook(c, "UserPromptSubmit", sesion)
    assert control(c)["modo"] == "claude"


# ── sin hooks: tras cada tarea, como antes ──────────────────────────────────
@pytest.mark.parametrize("como", ["sin conversacion", "sin noticias", "turno de otra sesion", "turno acabado"])
def test_sin_saber_que_turno_corre_cada_tarea_devuelve_el_mac_como_antes(entorno, como):
    c, sim = entorno
    if como != "sin conversacion":
        sesion = abierta()
    if como == "turno de otra sesion":
        hook(c, "UserPromptSubmit", str(uuid.uuid4()))
    if como == "turno acabado":
        hook(c, "UserPromptSubmit", sesion)
        hook(c, "Stop", sesion)
    leer(c)
    e = control(c)
    assert e["modo"] == "libre" and e["motivo"] == "terminó de capturar: el Mac vuelve a ti"
    assert lineas_de_control(c)[-1]["detalle"] == e["motivo"]


# ── 🔴 los hooks sólo devuelven: nunca dan el control ni sacan de Parar ──────
FINALES = [("Stop", {}), ("PreToolUse", {"tool_name": "AskUserQuestion"}), ("UserPromptSubmit", {})]


@pytest.mark.parametrize("evento, extra", FINALES)
@pytest.mark.parametrize("de_partida", ["libre", "parado"])
def test_ningun_hook_da_el_control_ni_saca_de_parado(entorno, evento, extra, de_partida):
    c, _ = entorno
    sesion = abierta()
    hook(c, "UserPromptSubmit", sesion)  # un turno abierto: la red del Esc se activaría
    if de_partida == "parado":
        dar(c)
        assert c.post("/api/control", json={"accion": "parar"}, headers=PERSONA).status_code == 200
    antes = control(c)
    hook(c, evento, sesion, **extra)
    despues = control(c)
    assert despues["modo"] == de_partida and despues["motivo"] == antes["motivo"]


def test_fin_de_turno_nunca_da_el_control_ni_pone_el_modo_a_mano():
    """La red bajo la de arriba: ni por un camino que no esté en las pruebas.
    Devolver es `devolver_control`, que sólo pasa de CLAUDE a LIBRE."""
    import inspect
    import re

    from puente_kvm.app import Puente

    for metodo in (Puente.fin_de_turno, Puente.al_acabar_tarea, Puente.devolver_control,
                   Puente.devolver_al_acabar, Puente._tras_tarea, Puente.resumen_correcciones):
        fuente = inspect.getsource(metodo)
        assert ".dar(" not in fuente and ".parar(" not in fuente
        assert not re.search(r"control\.modo\s*=[^=]", fuente)


# ── la actividad guarda de qué conversación es, sin contenido ──────────────
def test_la_actividad_guarda_la_sesion_y_sus_turnos_abiertos_y_los_recupera(tmp_path):
    ruta = tmp_path / "actividad.json"
    a = repertorio.Actividad(ruta)
    sesion = str(uuid.uuid4())
    a.registrar({"hook_event_name": "UserPromptSubmit", "session_id": sesion, "prompt": "usp_Secreta"})
    datos = json.loads(ruta.read_text())
    assert datos == {"estado": "trabajando", "t": datos["t"], "sesion": sesion, "abiertos": {sesion: datos["t"]}}
    assert "usp_Secreta" not in ruta.read_text()
    b = repertorio.Actividad(ruta)
    assert b.recuperar() and b.sesion == sesion and sesion in b.abiertos
    a.registrar({"hook_event_name": "Stop", "session_id": sesion})
    assert sesion not in a.abiertos and json.loads(ruta.read_text())["abiertos"] == {}


def test_un_session_id_que_no_es_un_uuid_no_se_guarda():
    a = repertorio.Actividad()
    a.registrar({"hook_event_name": "UserPromptSubmit", "session_id": "../../trabajo/usp_Secreta"})
    assert a.sesion is None and a.abiertos == {}


def test_al_reabrir_la_conversacion_no_queda_ningun_turno_abierto():
    a = repertorio.Actividad()
    a.registrar({"hook_event_name": "UserPromptSubmit", "session_id": str(uuid.uuid4())})
    a.recien_abierta()
    assert a.abiertos == {}


def test_las_sesiones_que_nunca_terminan_no_crecen_sin_fin():
    a = repertorio.Actividad()
    for _ in range(repertorio.MAX_ABIERTOS + 15):
        a.registrar({"hook_event_name": "UserPromptSubmit", "session_id": str(uuid.uuid4())})
    assert len(a.abiertos) == repertorio.MAX_ABIERTOS


# ── lo que encontró el revisor ──────────────────────────────────────────────
def test_reabrir_claude_code_a_mitad_de_un_encargo_devuelve_el_mac(entorno):
    """🔴 Claude Code se cerró a mitad y se abrió de nuevo: su `Stop` no llega, y
    el control dado para aquel encargo no vale para el siguiente."""
    c, _ = entorno
    sesion = abierta()
    dar(c)
    hook(c, "UserPromptSubmit", sesion)
    c.app.state.puente.conversacion_reabierta("Claude Code se volvió a abrir: el control vuelve a ti")
    assert control(c)["modo"] == "libre"
    assert c.app.state.puente.actividad.abiertos == {}
    hook(c, "UserPromptSubmit", sesion)
    assert control(c)["modo"] == "libre"


def test_la_terminal_y_cambiar_de_conversacion_pasan_por_conversacion_reabierta():
    import inspect

    from puente_kvm import app
    codigo = inspect.getsource(app)
    assert codigo.count("conversacion_reabierta(") >= 3  # la definición, la terminal y cambiar
    assert ".actividad.recien_abierta()" not in codigo.replace("self.actividad.recien_abierta()", "")


def test_el_fin_de_la_sesion_de_la_conversacion_devuelve_el_mac(entorno):
    c, _ = entorno
    sesion = abierta()
    dar(c)
    hook(c, "UserPromptSubmit", sesion)
    hook(c, "SessionEnd", sesion)
    assert control(c)["modo"] == "libre"


def test_un_mensaje_de_otra_sesion_no_tapa_el_encargo_cortado(entorno):
    """🔴 Con una sola casilla, el mensaje de una sesión de desarrollo pisaba el
    turno cortado y la red del Esc no saltaba."""
    c, _ = entorno
    sesion, otra = abierta(), str(uuid.uuid4())
    dar(c)
    time.sleep(0.01)
    hook(c, "UserPromptSubmit", sesion)
    hook(c, "PreToolUse", sesion, tool_name="mcp__puente-kvm__ver_pantalla")
    hook(c, "UserPromptSubmit", otra)  # Esc en la del puente; una de desarrollo habla
    hook(c, "UserPromptSubmit", sesion)
    assert control(c)["modo"] == "libre"


def test_otra_sesion_que_va_a_tocar_el_mac_le_devuelve_el_control(entorno):
    c, _ = entorno
    sesion, otra = abierta(), str(uuid.uuid4())
    dar(c)
    hook(c, "UserPromptSubmit", sesion)
    hook(c, "PreToolUse", otra, tool_name="mcp__puente-kvm__ver_pantalla")  # mirar no toca
    hook(c, "PreToolUse", otra, tool_name="Bash")
    assert control(c)["modo"] == "claude"
    hook(c, "PreToolUse", otra, tool_name="mcp__puente-kvm__teclear")
    e = control(c)
    assert e["modo"] == "libre" and e["motivo"].startswith("otra sesión de Claude")


def test_sin_conversacion_del_registro_sus_herramientas_no_le_quitan_el_control(entorno):
    c, _ = entorno
    dar(c)
    hook(c, "PreToolUse", str(uuid.uuid4()), tool_name="mcp__puente-kvm__leer_documento")
    assert control(c)["modo"] == "claude"


def test_un_registro_ilegible_al_acabar_una_tarea_devuelve_el_mac(entorno, monkeypatch):
    c, _ = entorno
    dar(c)

    def roto():
        raise ValueError("conversaciones.json ilegible")
    monkeypatch.setattr(conversaciones, "actual", roto)
    c.app.state.puente.al_acabar_tarea("terminó de capturar: el Mac vuelve a ti")
    assert c.app.state.puente.control.modo == "libre"


# ── comprobar ───────────────────────────────────────────────────────────────
def _settings(esp, hooks: dict) -> None:
    (esp / ".claude").mkdir(parents=True, exist_ok=True)
    (esp / ".claude" / "settings.json").write_text(json.dumps({"hooks": hooks}))


def _hacia_el_puente() -> list:
    return [{"hooks": [{"type": "command", "command": "curl … /api/claude/actividad …"}]}]


def test_comprobar_avisa_si_faltan_los_hooks_y_dice_que_pasa(tmp_path):
    p = comprobar.punto_hooks(tmp_path)
    assert p.estado == comprobar.OJO
    assert "UserPromptSubmit, Stop y SessionEnd" in p.detalle and "tras cada lectura o escritura" in p.detalle
    _settings(tmp_path, {"UserPromptSubmit": _hacia_el_puente(),
                         "Stop": [{"hooks": [{"type": "command", "command": "echo otra cosa"}]}]})
    p = comprobar.punto_hooks(tmp_path)
    assert p.estado == comprobar.OJO and "faltan Stop" in p.detalle and p.arreglo


def test_comprobar_cuenta_tambien_el_settings_local(tmp_path):
    _settings(tmp_path, {"UserPromptSubmit": _hacia_el_puente()})
    (tmp_path / ".claude" / "settings.local.json").write_text(
        json.dumps({"hooks": {"Stop": _hacia_el_puente(), "SessionEnd": _hacia_el_puente()}}))
    assert comprobar.punto_hooks(tmp_path).estado == comprobar.BIEN


def test_el_settings_del_puente_trae_los_hooks_del_turno():
    assert comprobar.punto_hooks(config.CODIGO).estado == comprobar.BIEN


def test_comprobar_sin_entrar_lleva_el_punto_de_los_hooks(tmp_path):
    assert any(p.que == "hooks de Claude" for p in comprobar._espacio({"espacio": str(tmp_path)}))


# ── C-0490: Claude Code corta una herramienta a los 30 min ──────────────────
def test_una_escritura_mas_larga_que_la_espera_contesta_que_sigue_y_acaba_sola(entorno, monkeypatch):
    """🔴 Visto con el aparato: `escribir_cambio` esperaba hasta 30 min, Claude Code
    cortó la herramienta y una escritura de 1.920 líneas se quedó en la 1.038.
    Ahora contesta antes «sigue en marcha», la tarea sigue en el servicio y el
    control no vuelve hasta que acaba."""
    import asyncio

    from puente_kvm import mcp_servidor

    from .ayuda import mcp_contra
    c, sim = entorno
    mcp_contra(c, monkeypatch)
    monkeypatch.setattr(mcp_servidor, "ESPERA_MAX_S", 0.3)
    sesion = abierta()
    hook(c, "UserPromptSubmit", sesion)
    lid = leer(c)
    transcribir_como_oraculo(c, sim, lid)
    nuevo = list(sim.editor.guardado)
    for i in range(10, 40):
        nuevo[i] += " -- una línea bastante larga añadida para que escribir tarde un buen rato"
    cid = proponer_y_aprobar(c, lid, nuevo, "muchas líneas")
    r = asyncio.run(mcp_servidor.escribir_cambio(cid))
    assert r["estado"] == "escribiendo" and r["siguiente"].startswith("Sigue en marcha")
    hook(c, "Stop", sesion)  # con eso, Claude termina su turno
    assert control(c)["modo"] == "claude"
    esperar(c)
    assert c.get(f"/api/cambios/{cid}").json()["estado"] == "escrito"
    assert all(sim.editor.lineas[i].endswith("buen rato") for i in range(10, 40))
    assert control(c)["modo"] == "libre"


def test_una_escritura_corta_contesta_como_siempre(entorno, monkeypatch):
    import asyncio

    from puente_kvm import mcp_servidor

    from .ayuda import mcp_contra
    c, sim = entorno
    mcp_contra(c, monkeypatch)
    lid = leer(c)
    transcribir_como_oraculo(c, sim, lid)
    nuevo = list(sim.editor.guardado)
    nuevo[10] += " -- corta"
    cid = proponer_y_aprobar(c, lid, nuevo, "corta")
    dar(c)
    r = asyncio.run(mcp_servidor.escribir_cambio(cid))
    assert r["estado"] == "escrito" and "siguiente" not in r
