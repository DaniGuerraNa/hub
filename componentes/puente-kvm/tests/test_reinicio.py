"""Reiniciar el puente y reabrir la conversación de Claude con botones (C-0470).

Tras actualizar, el aviso de código viejo pedía dos comandos a mano, y quien
lo usa no es técnico. Ahora son dos pasos con botón: «Reiniciar el puente»
(`POST /api/reiniciar`) y «Reabrir la conversación de Claude». Reiniciar no
corta nada a medias —lo mismo que mira `servicio.sh reiniciar --si-libre`— y
sólo vale si el proceso es el de su unidad de systemd.

`systemctl` es de mentira (apunta lo que se le pide): uno de verdad
reiniciaría el puente de quien corre las pruebas. Que el reinicio de verdad
funciona, y cuánto tarda, se midió a mano con una unidad de prueba (la ficha
C-0470 del repositorio que lo contiene lo cuenta).
"""

import contextlib
import json
import sys
import threading
import time

import httpx
import pytest
import uvicorn
from fastapi.testclient import TestClient

from puente_kvm import config, conversaciones, reinicio
from puente_kvm.app import crear_app
from puente_kvm.simulador import Simulador

from .ayuda import PERSONA, esperar, puente_simulado
from .test_conversaciones import puente  # noqa: F401  (el puente con un claude de mentira)

UNIDAD = "puente-de-prueba"
INVOCACION = "0123456789abcdef0123456789abcdef"


@pytest.fixture
def con_systemd(tmp_path, monkeypatch):
    """Un `systemctl` de mentira que dice que este proceso es el de su unidad y
    apunta lo que se le pide; `restart` tarda, como el de verdad."""
    bin_ = tmp_path / "bin-systemctl"
    bin_.mkdir()
    registro = tmp_path / "systemctl.log"
    (bin_ / "systemctl").write_text(
        "#!/bin/sh\n"
        f'echo "$(date +%s.%N) $*" >> "{registro}"\n'
        'case "$*" in\n'
        f'  *"show -p InvocationID --value {UNIDAD}"*) sleep "${{RETARDO_SHOW:-0}}"; echo "{INVOCACION}" ;;\n'
        '  *restart*) sleep 2; exit "${SALE_RESTART:-0}" ;;\n'
        "esac\n")
    (bin_ / "systemctl").chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_}:/usr/bin:/bin")
    monkeypatch.setenv("INVOCATION_ID", INVOCACION)
    monkeypatch.setenv("PUENTE_SERVICIO", UNIDAD)
    reinicio._sabido.clear()
    yield registro
    reinicio._sabido.clear()


# ── con qué se reinicia ─────────────────────────────────────────────────────
def test_sin_systemd_el_estado_dice_a_mano_y_el_boton_se_niega():
    with puente_simulado(lineas=3) as (c, _):
        e = c.get("/api/estado").json()
        assert e["reinicio"] == "a_mano" and e["arrancado"] == reinicio.ARRANQUE
        r = c.post("/api/reiniciar", headers=PERSONA)
        assert r.status_code == 409 and "scripts/arrancar.sh" in r.json()["detail"]


def test_con_el_invocation_id_de_otra_unidad_tampoco_se_ofrece(con_systemd, monkeypatch):
    monkeypatch.setenv("INVOCATION_ID", "f" * 32)  # lanzado desde otra unidad, o desde una shell suya
    assert reinicio.como() == "a_mano"


def test_si_es_el_de_su_unidad_se_ofrece_el_boton(con_systemd):
    assert reinicio.como() == "systemd"
    with puente_simulado(lineas=3) as (c, _):
        assert c.get("/api/estado").json()["reinicio"] == "boton"


def test_reiniciar_es_de_la_persona(con_systemd):
    with puente_simulado(lineas=3) as (c, _):
        assert c.post("/api/reiniciar").status_code == 403
        assert c.post("/api/reiniciar", headers={"Origin": "http://otra.web"}).status_code == 403
    assert "restart" not in con_systemd.read_text()


@contextlib.contextmanager
def en_marcha():
    """El puente servido de verdad (uvicorn en un hilo): con el cliente de
    pruebas, la tarea de después de contestar corre antes de que llegue la
    respuesta, y no se vería en qué orden pasan."""
    base = f"127.0.0.1:{config.PUERTO}"
    servidor = uvicorn.Server(uvicorn.Config(crear_app(Simulador(lineas=["x"]), hosts={base}), host="127.0.0.1",
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


def test_pide_a_systemd_que_lo_reinicie_sin_esperar_y_contesta_antes(con_systemd):
    """🔴 Con `--no-block`: el `restart` que espera, lanzado desde dentro de la
    unidad, no vuelve nunca (systemd lo mata con el puente) y retiene la parada."""
    with en_marcha() as base:
        antes = time.time()
        r = httpx.post(base + "/api/reiniciar", headers={"Origin": base}, timeout=10)
        contestado = time.time()
        assert r.status_code == 200, r.text
        assert r.json() == {"arrancado": reinicio.ARRANQUE}
        assert contestado - antes < 1.5  # el restart de mentira tarda 2 s: no se le esperó
        for _ in range(60):
            if "restart" in con_systemd.read_text():
                break
            time.sleep(0.05)
        pedido = next(l for l in con_systemd.read_text().splitlines() if "restart" in l)
        assert pedido.split(" ", 1)[1] == f"--user --no-block restart {UNIDAD}"
        assert float(pedido.split()[0]) >= contestado - 0.2  # después de contestar, no antes
        bitacora = httpx.get(base + "/api/bitacora", timeout=5).json()
        assert any(e["tipo"] == "reinicio" and e["quien"] == "persona" for e in bitacora)


def test_un_nombre_de_unidad_raro_no_llega_a_la_linea_de_ordenes(con_systemd, monkeypatch):
    monkeypatch.setenv("PUENTE_SERVICIO", "puente; rm -rf ~")
    assert reinicio.como() == "a_mano"
    reinicio.pedir()
    assert not con_systemd.exists()  # ni se le preguntó ni se le pidió nada


def test_el_estado_no_espera_a_systemd_y_le_vuelve_a_preguntar_aparte(con_systemd, monkeypatch):
    """El estado se pide cada segundo y se contesta desde el bucle: un
    `systemctl show` lento lo pararía todo (el directo, el mando, los hooks)."""
    with puente_simulado(lineas=3) as (c, _):
        monkeypatch.setenv("RETARDO_SHOW", "1.5")
        # Lo sabido hace más de un minuto, «a_mano»: toca volver a mirarlo.
        reinicio._sabido[(INVOCACION, UNIDAD)] = ("a_mano", time.monotonic() - reinicio.VOLVER_A_MIRAR - 1)
        preguntas = con_systemd.read_text().count(" show ")
        antes = time.time()
        assert c.get("/api/estado").json()["reinicio"] == "a_mano"  # lo de antes, hasta que conteste
        assert time.time() - antes < 0.8
        visto = []
        for _ in range(60):
            visto.append(c.get("/api/estado").json()["reinicio"])
            if visto[-1] == "boton":
                break
            time.sleep(0.05)
        assert visto[-1] == "boton"
        # Una sola pregunta aunque el estado se pidiera muchas veces mientras.
        assert con_systemd.read_text().count(" show ") == preguntas + 1


def test_un_segundo_reiniciar_mientras_se_reinicia_dice_que_ya_va(con_systemd):
    with puente_simulado(lineas=3) as (c, _):
        assert c.post("/api/reiniciar", headers=PERSONA).status_code == 200
        r = c.post("/api/reiniciar", headers=PERSONA)
        assert r.status_code == 409 and "Ya se está reiniciando" in r.json()["detail"]
    assert con_systemd.read_text().count("restart") == 1


def test_si_systemd_no_acepta_el_reinicio_se_puede_volver_a_pulsar(con_systemd, monkeypatch):
    monkeypatch.setenv("SALE_RESTART", "1")
    with puente_simulado(lineas=3) as (c, _):
        assert c.post("/api/reiniciar", headers=PERSONA).status_code == 200
        assert c.post("/api/reiniciar", headers=PERSONA).status_code == 200
    assert con_systemd.read_text().count("restart") == 2


# ── no corta nada a medias ──────────────────────────────────────────────────
def test_con_una_tarea_en_marcha_no_lo_reinicia_y_dice_por_que(con_systemd):
    with puente_simulado(lineas=400, retardo_ms=60) as (c, _):
        c.post("/api/control", json={"accion": "dar"}, headers=PERSONA)
        c.post("/api/lecturas", json={"nombre": "larga"})
        time.sleep(0.3)
        r = c.post("/api/reiniciar", headers=PERSONA)
        assert r.status_code == 409 and "tarea" in r.json()["detail"]
        c.post("/api/control", json={"accion": "parar"}, headers=PERSONA)
        esperar(c)
    assert "restart" not in con_systemd.read_text()


def test_con_el_control_dado_a_claude_no_lo_reinicia(con_systemd):
    with puente_simulado(lineas=3) as (c, _):
        c.post("/api/control", json={"accion": "dar"}, headers=PERSONA)
        r = c.post("/api/reiniciar", headers=PERSONA)
        assert r.status_code == 409 and "Claude tiene el control" in r.json()["detail"]
    assert "restart" not in con_systemd.read_text()


def test_grabando_una_reunion_no_lo_reinicia(con_systemd):
    with puente_simulado(lineas=3) as (c, _):
        assert c.post("/api/reunion/empezar", json={}, headers=PERSONA).status_code == 200
        r = c.post("/api/reiniciar", headers=PERSONA)
        assert r.status_code == 409 and "reunión" in r.json()["detail"]
        c.post("/api/reunion/parar", headers=PERSONA)
    assert "restart" not in con_systemd.read_text()


def test_con_el_mac_en_uso_desde_la_pantalla_no_lo_reinicia_y_al_cerrarlo_deja_de_contar(con_systemd):
    """Lo que la persona teclea en el Mac desde la pantalla del puente se
    cortaría. Vale también para `servicio.sh reiniciar --si-libre`, que mira lo
    mismo (`comprobar.ocupado`) por `/api/estado`."""
    from puente_kvm import comprobar
    with puente_simulado(lineas=3) as (c, _):
        assert c.get("/api/estado").json()["mando"] is False
        with c.websocket_connect("/ws/mando", headers=PERSONA) as ws:
            ws.send_text(json.dumps({"t": "raton", "x": 10, "y": 10, "b": 0}))
            ws.send_text(json.dumps({"t": "soltar"}))
            time.sleep(0.2)
            estado = c.get("/api/estado").json()
            assert estado["mando"] is True
            assert comprobar.ocupado(estado) == "se está usando el Mac desde la pantalla del puente"
            r = c.post("/api/reiniciar", headers=PERSONA)
            assert r.status_code == 409 and "pantalla del puente" in r.json()["detail"]
        # Cerrado el último mando, nadie lo usa: no hay que esperar a que caduque.
        for _ in range(40):
            if c.get("/api/estado").json()["mando"] is False:
                break
            time.sleep(0.05)
        assert c.get("/api/estado").json()["mando"] is False


def test_quien_tiene_abierto_usar_el_mac_aunque_no_mueva_nada_tambien_cuenta(con_systemd):
    """Leyendo lo que hay en el Mac, sin tocar nada, la persona lo está usando:
    reiniciar le cortaría la imagen y el mando a medias."""
    with puente_simulado(lineas=3) as (c, _):
        with c.websocket_connect("/ws/mando", headers=PERSONA):
            for _ in range(40):
                if c.get("/api/estado").json()["mando"]:
                    break
                time.sleep(0.05)
            assert c.get("/api/estado").json()["mando"] is True
            r = c.post("/api/reiniciar", headers=PERSONA)
            assert r.status_code == 409 and "pantalla del puente" in r.json()["detail"]
    assert "restart" not in con_systemd.read_text()


# ── reabrir la conversación ─────────────────────────────────────────────────
def _conversacion(c) -> dict:
    return c.get("/api/estado").json()["conversacion"]


def test_una_conversacion_recien_abierta_tiene_las_herramientas_del_disco(puente):  # noqa: F811
    c, _ = puente
    a = c.post("/api/conversaciones", json={"nombre": "Nueva"}, headers=PERSONA).json()
    assert conversaciones.buscar(a["id"]).codigo == config.CODIGO_EN_MARCHA.huella_disco()
    assert _conversacion(c)["herramientas_viejas"] is False


def test_sin_huella_apuntada_cuenta_como_viejas_y_reabrir_la_apunta(puente):  # noqa: F811
    """Las conversaciones de antes de apuntar la huella: no se sabe con qué
    código se abrieron, así que se pide reabrirlas una vez."""
    c, _ = puente
    a = c.post("/api/conversaciones", json={"nombre": "De antes"}, headers=PERSONA).json()
    ruta = config.hogar() / "conversaciones.json"
    datos = json.loads(ruta.read_text())
    for d in datos["conversaciones"]:
        d.pop("codigo", None)  # como la escribía el puente de antes
    ruta.write_text(json.dumps(datos))
    assert _conversacion(c)["herramientas_viejas"] is True
    assert c.post(f"/api/conversaciones/{a['id']}/abrir", headers=PERSONA).status_code == 200
    assert _conversacion(c)["herramientas_viejas"] is False


def test_tras_actualizar_el_codigo_sus_herramientas_son_viejas_hasta_reabrirla(puente, monkeypatch):  # noqa: F811
    c, _ = puente
    a = c.post("/api/conversaciones", json={"nombre": "Antes de actualizar"}, headers=PERSONA).json()
    monkeypatch.setattr(config.CODIGO_EN_MARCHA, "huella_disco", lambda: "la-del-codigo-nuevo")
    assert _conversacion(c)["herramientas_viejas"] is True
    assert c.post(f"/api/conversaciones/{a['id']}/abrir", headers=PERSONA).status_code == 200
    assert conversaciones.buscar(a["id"]).codigo == "la-del-codigo-nuevo"
    assert _conversacion(c)["herramientas_viejas"] is False


def test_con_claude_trabajando_reabrir_pide_confirmarlo(puente):  # noqa: F811
    c, _ = puente
    a = c.post("/api/conversaciones", json={"nombre": "Ocupada"}, headers=PERSONA).json()
    c.post("/api/claude/actividad", json={"hook_event_name": "UserPromptSubmit"})
    r = c.post(f"/api/conversaciones/{a['id']}/abrir", headers=PERSONA)
    assert r.status_code == 409 and "trabajando" in r.json()["detail"]
    assert r.headers["X-Puente-Motivo"] == "trabajando"  # la pantalla pregunta y repite
    # Una nueva también lo cerraría a medias.
    assert c.post("/api/conversaciones", json={"nombre": "Otra"}, headers=PERSONA).status_code == 409
    r = c.post(f"/api/conversaciones/{a['id']}/abrir", json={"aunque_trabaje": True}, headers=PERSONA)
    assert r.status_code == 200, r.text


def test_sin_que_claude_trabaje_reabrir_no_pregunta_nada(puente):  # noqa: F811
    c, _ = puente
    a = c.post("/api/conversaciones", json={"nombre": "Libre"}, headers=PERSONA).json()
    c.post("/api/claude/actividad", json={"hook_event_name": "Stop"})
    assert c.post(f"/api/conversaciones/{a['id']}/abrir", headers=PERSONA).status_code == 200


# ── tras reiniciar el puente, la conversación sigue viva en tmux ────────────
# El puente nuevo no ha oído nada de los hooks de Claude: sin lo guardado,
# Reabrir cerraba la conversación sin preguntar, aunque Claude estuviera a medias.
@contextlib.contextmanager
def puente_nuevo():
    """El puente de después de reiniciarlo: otro proceso (otro `Puente`), con los
    mismos datos y la conversación de Claude que dejó el de antes."""
    with TestClient(crear_app(Simulador(lineas=["x"]), hosts={"testserver"})) as c:
        yield c


def test_tras_reiniciar_el_puente_reabrir_pregunta_si_claude_estaba_trabajando(puente):  # noqa: F811
    c, _ = puente
    a = c.post("/api/conversaciones", json={"nombre": "A medias"}, headers=PERSONA).json()
    c.post("/api/claude/actividad", json={"hook_event_name": "UserPromptSubmit"})
    with puente_nuevo() as nuevo:
        assert nuevo.get("/api/estado").json()["claude"]["estado"] == "trabajando"
        r = nuevo.post(f"/api/conversaciones/{a['id']}/abrir", headers=PERSONA)
        assert r.status_code == 409 and "trabajando" in r.json()["detail"]
        assert r.headers["X-Puente-Motivo"] == "trabajando"
        r = nuevo.post(f"/api/conversaciones/{a['id']}/abrir", json={"aunque_trabaje": True}, headers=PERSONA)
        assert r.status_code == 200, r.text


def test_tras_reiniciar_sin_saber_nada_de_claude_reabrir_pregunta_igual(puente):  # noqa: F811
    """Sin nada guardado (un puente de antes de guardarlo, o un archivo que no
    se pudo escribir): con la conversación viva, «no sé» no es «está libre»."""
    c, _ = puente
    a = c.post("/api/conversaciones", json={"nombre": "Sin noticias"}, headers=PERSONA).json()
    (config.hogar() / "actividad.json").unlink(missing_ok=True)
    with puente_nuevo() as nuevo:
        assert nuevo.get("/api/estado").json()["claude"]["estado"] == "sin noticias"
        r = nuevo.post(f"/api/conversaciones/{a['id']}/abrir", headers=PERSONA)
        assert r.status_code == 409 and r.headers["X-Puente-Motivo"] == "trabajando"
        assert "No sé si Claude está a medias: el puente se acaba de reiniciar" in r.json()["detail"]
        # Una nueva también la cerraría.
        assert nuevo.post("/api/conversaciones", json={"nombre": "Otra"}, headers=PERSONA).status_code == 409
        r = nuevo.post(f"/api/conversaciones/{a['id']}/abrir", json={"aunque_trabaje": True}, headers=PERSONA)
        assert r.status_code == 200, r.text


def test_al_reabrirla_claude_queda_esperando_aunque_el_de_antes_no_dijera_que_acabo(puente):  # noqa: F811
    """El Claude que se cierra para reabrir no manda su `Stop`: la placa se
    quedaba en «trabajando», y la siguiente vez volvía a preguntar."""
    c, _ = puente
    a = c.post("/api/conversaciones", json={"nombre": "Ocupada"}, headers=PERSONA).json()
    c.post("/api/claude/actividad", json={"hook_event_name": "UserPromptSubmit"})
    r = c.post(f"/api/conversaciones/{a['id']}/abrir", json={"aunque_trabaje": True}, headers=PERSONA)
    assert r.status_code == 200, r.text
    assert c.get("/api/estado").json()["claude"]["estado"] == "esperando"
    with puente_nuevo() as nuevo:  # y lo sabe también el puente de después
        assert nuevo.get("/api/estado").json()["claude"]["estado"] == "esperando"
        assert nuevo.post(f"/api/conversaciones/{a['id']}/abrir", headers=PERSONA).status_code == 200


def test_la_conversacion_que_abre_el_propio_puente_no_pregunta_al_cambiar(puente):  # noqa: F811
    """La abre la terminal al conectarse: Claude acaba de arrancar y espera su
    primer mensaje. Que sea «sin noticias» no puede hacer preguntar."""
    c, _ = puente
    from puente_kvm import terminal
    with c.websocket_connect("/ws/terminal", headers=PERSONA):
        for _ in range(100):
            if terminal.existe():
                break
            time.sleep(0.05)
    assert c.get("/api/estado").json()["claude"]["estado"] == "esperando"
    assert c.post("/api/conversaciones", json={"nombre": "Otra"}, headers=PERSONA).status_code == 200


def test_lo_guardado_de_una_conversacion_que_ya_no_vive_no_cuenta():
    (config.hogar() / "actividad.json").write_text(json.dumps({"estado": "trabajando", "t": time.time()}))
    with puente_simulado(lineas=3) as (c, _):  # sin la sesión de tmux
        assert c.get("/api/estado").json()["claude"]["estado"] == "sin noticias"


def test_de_la_actividad_solo_se_guardan_el_estado_y_la_hora():
    """La skill y la herramienta llevan rutas y nombres del trabajo: no salen de la memoria."""
    with puente_simulado(lineas=3) as (c, _):
        c.post("/api/claude/actividad", json={"hook_event_name": "PreToolUse", "tool_name": "Read",
                                              "tool_input": {"file_path": "/x/trabajo/usp_Secreto.sql"}})
        texto = (config.hogar() / "actividad.json").read_text()
    assert set(json.loads(texto)) == {"estado", "t"} and json.loads(texto)["estado"] == "trabajando"
    assert "usp_Secreto" not in texto


# ── al pararlo ──────────────────────────────────────────────────────────────
def test_al_pararlo_no_espera_mas_de_5_s_a_las_peticiones_abiertas(monkeypatch):
    """El directo no termina mientras una pestaña lo mira: el 17-nov un stop
    tardó 93 s, hasta el SIGKILL de systemd. Cuánto tarda de verdad con el
    directo abierto se midió con una unidad de prueba."""
    from puente_kvm import __main__ as orden
    visto = {}
    monkeypatch.setattr(uvicorn, "run", lambda app, **kw: visto.update(kw))
    monkeypatch.setattr(sys, "argv", ["puente-kvm", "web"])
    orden.main()
    assert visto["timeout_graceful_shutdown"] == 5 and visto["host"] == "127.0.0.1"
