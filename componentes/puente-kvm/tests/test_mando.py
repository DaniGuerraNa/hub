"""La persona usa el Mac desde la pantalla del puente (/ws/mando).

Sin la web del JetKVM, que sólo admite una sesión y desconectaba el puente.
Se prueba contra el Mac simulado: lo que se pulsa llega como texto, nada
llega mientras Claude tiene el control, y lo tecleado no queda en ningún sitio.
"""

import json

import pytest
from starlette.websockets import WebSocketDisconnect

from puente_kvm import config

from .ayuda import PERSONA, puente_simulado

A, H, L, O = 0x04, 0x0B, 0x0F, 0x12
SHIFT_IZQ = 0xE1


@pytest.fixture
def entorno():
    with puente_simulado(lineas=3) as (c, sim):
        yield c, sim


def pulsar(ws, *codigos):
    for c in codigos:
        ws.send_text(json.dumps({"t": "tecla", "codigo": c, "abajo": True}))
        ws.send_text(json.dumps({"t": "tecla", "codigo": c, "abajo": False}))


def test_lo_que_teclea_la_persona_llega_al_mac_y_con_mayusculas(entorno):
    c, sim = entorno
    sim.editor.lineas, sim.editor.cursor = [""], (0, 0)
    with c.websocket_connect("/ws/mando", headers=PERSONA) as ws:
        pulsar(ws, H, O)
        ws.send_text(json.dumps({"t": "tecla", "codigo": SHIFT_IZQ, "abajo": True}))
        pulsar(ws, L)
        ws.send_text(json.dumps({"t": "tecla", "codigo": SHIFT_IZQ, "abajo": False}))
        pulsar(ws, A)
        ws.send_text(json.dumps({"t": "soltar"}))
    assert sim.editor.lineas == ["hoLa"]


def test_otra_web_no_puede_usar_el_mac():
    with puente_simulado(lineas=3) as (c, _):
        with pytest.raises(WebSocketDisconnect):
            with c.websocket_connect("/ws/mando", headers={"Origin": "http://otra.web"}) as ws:
                ws.receive_text()


def test_con_el_control_de_claude_no_llega_nada_y_se_dice_por_que(entorno):
    c, sim = entorno
    antes = list(sim.editor.lineas)
    c.post("/api/control", json={"accion": "dar"}, headers=PERSONA)
    with c.websocket_connect("/ws/mando", headers=PERSONA) as ws:
        pulsar(ws, H)
        respuesta = ws.receive_json()
    assert "Claude tiene el Mac" in respuesta["no"]
    assert sim.editor.lineas == antes


def test_si_se_corta_con_una_tecla_abajo_se_suelta(entorno):
    c, sim = entorno
    with c.websocket_connect("/ws/mando", headers=PERSONA) as ws:
        ws.send_text(json.dumps({"t": "tecla", "codigo": H, "abajo": True}))
        ws.send_text(json.dumps({"t": "raton", "x": 500, "y": 400, "b": 1}))
    assert sim._pulsadas == set() and sim._botones == 0


def test_lo_tecleado_no_queda_en_la_bitacora_solo_cuanto_rato(entorno):
    c, sim = entorno
    with c.websocket_connect("/ws/mando", headers=PERSONA) as ws:
        pulsar(ws, H, O, L, A)
        ws.send_text(json.dumps({"t": "pegar", "texto": "contrasena-secreta"}))
        assert ws.receive_json() == {"hecho": "pegar"}
    bitacora = json.dumps(c.get("/api/bitacora").json(), ensure_ascii=False)
    assert "usó el Mac desde la pantalla" in bitacora
    assert "hola" not in bitacora and "secreta" not in bitacora


def test_pegar_teclea_con_la_distribucion_de_ajustes(entorno):
    c, sim = entorno
    sim.editor.lineas, sim.editor.cursor = [""], (0, 0)
    with c.websocket_connect("/ws/mando", headers=PERSONA) as ws:
        ws.send_text(json.dumps({"t": "pegar", "texto": "SELECT [id] FROM t;"}))
        assert ws.receive_json() == {"hecho": "pegar"}
    assert sim.editor.lineas == ["SELECT [id] FROM t;"]


def test_solo_las_combinaciones_de_la_lista(entorno):
    c, sim = entorno
    antes = sim.informes
    with c.websocket_connect("/ws/mando", headers=PERSONA) as ws:
        ws.send_text(json.dumps({"t": "combinacion", "atajo": "cmd+q"}))  # cerrar la app: no
        ws.send_text(json.dumps({"t": "soltar"}))
    assert sim.informes == antes


def test_el_raton_se_queda_dentro_de_la_pantalla(entorno):
    c, sim = entorno
    with c.websocket_connect("/ws/mando", headers=PERSONA) as ws:
        ws.send_text(json.dumps({"t": "raton", "x": 99999, "y": -5, "b": 0}))
        ws.send_text(json.dumps({"t": "soltar"}))
    assert sim.puntero == (1919, 0)


def test_invertir_la_rueda_vale_para_claude_y_para_la_persona(entorno):
    c, sim = entorno
    sim.editor.lineas = [f"l{i}" for i in range(200)]
    perfil = {**config.PERFIL_POR_OMISION, "invertir_rueda": True}
    assert c.post("/api/ajustes", json={"perfil": perfil}, headers=PERSONA).status_code == 200
    sim.editor.arriba = 30
    c.post("/api/control", json={"accion": "dar"}, headers=PERSONA)
    assert c.post("/api/rueda", json={"pasos": 2, "x": 700, "y": 500}).status_code == 200
    assert sim.editor.arriba < 30  # «baja» con la rueda invertida: el simulador la ve subir
    c.post("/api/control", json={"accion": "retomar"}, headers=PERSONA)
    sim.editor.arriba = 30
    with c.websocket_connect("/ws/mando", headers=PERSONA) as ws:
        ws.send_text(json.dumps({"t": "rueda", "pasos": 2}))
        ws.send_text(json.dumps({"t": "soltar"}))
    assert sim.editor.arriba < 30


def test_dos_que_miran_a_la_vez_comparten_la_imagen_recien_hecha(entorno, monkeypatch):
    # Cada imagen del directo cuesta; dos pestañas no la hacen dos veces.
    from puente_kvm import app as modulo

    monkeypatch.setattr(modulo, "INTERVALO_MANDO", 60)  # «a la vez», aunque la máquina vaya lenta
    c, sim = entorno
    llamadas = []
    original = sim.miniatura

    async def contar(ancho):
        llamadas.append(ancho)
        return await original(ancho)

    sim.miniatura = contar
    a = c.get("/api/pantalla.jpg?ancho=1280")
    b = c.get("/api/pantalla.jpg?ancho=1280")
    assert a.status_code == b.status_code == 200
    assert a.content == b.content and len(llamadas) == 1
