"""El jiggler y despertar el Mac (C-0463): los botones de la persona y lo que puede Claude.

«Busco un botón que lo active y desactive, que traiga por default el de 30
segundos, para ya poder programarlo en cierto horario con Claude», y uno que
despierte al Mac «cuando yo la mande a reposo desde el puente». Contra el Mac
simulado; el JetKVM de verdad, en `test_jetkvm.py` contra el falso.
"""

import json

import pytest

from puente_kvm import jiggler, repertorio

from .ayuda import PERSONA, puente_simulado

FRECUENTE = jiggler.PREAJUSTES["frecuente"][1]


@pytest.fixture
def entorno():
    with puente_simulado(lineas=3) as (c, sim):
        yield c, sim


def test_el_boton_lo_enciende_con_frecuente_y_lo_apaga(entorno):
    c, sim = entorno
    assert c.get("/api/estado").json()["jiggler_texto"] == "apagado"  # como viene el JetKVM
    r = c.post("/api/jiggler", json={"encendido": True}, headers=PERSONA)
    assert r.status_code == 200, r.text
    assert r.json()["texto"] == "Frecuente, cada 30 s"
    assert sim._jiggler == {"encendido": True, "config": FRECUENTE}
    assert c.get("/api/estado").json()["jiggler_texto"] == "Frecuente, cada 30 s"
    assert c.post("/api/jiggler", json={"encendido": False}, headers=PERSONA).json()["texto"] == "apagado"
    ultima = c.get("/api/bitacora").json()[-1]
    assert ultima["tipo"] == "jiggler" and ultima["quien"] == "persona"


def test_claude_lo_programa_con_horario_y_zona_y_el_boton_no_lo_pisa(entorno):
    c, sim = entorno
    r = c.post("/api/jiggler", json={"encendido": True, "horario": "*/30  *  9-17 * * 1-5",
                                     "zona": "America/Mexico_City", "inactividad_s": 45})
    assert r.status_code == 200, r.text
    assert r.json()["texto"] == "entre semana de 9:00 a 18:00, cada 30 s (America/Mexico_City)"
    assert sim._jiggler["config"] == {"inactivity_limit_seconds": 45, "jitter_percentage": 25,
                                      "schedule_cron_tab": "*/30 * 9-17 * * 1-5", "timezone": "America/Mexico_City"}
    assert c.get("/api/bitacora").json()[-1]["quien"] == "claude"
    # La persona lo apaga y lo vuelve a encender: su horario sigue.
    c.post("/api/jiggler", json={"encendido": False}, headers=PERSONA)
    c.post("/api/jiggler", json={"encendido": True}, headers=PERSONA)
    assert sim._jiggler["config"]["schedule_cron_tab"] == "*/30 * 9-17 * * 1-5"


@pytest.mark.parametrize("cuerpo, motivo", [
    ({}, "encendido"),  # nunca «alternar»: dos pestañas lo deshacen
    ({"encendido": "si"}, "encendido"),
    ({"encendido": True, "horario": "*/30 * 9-17 * *", "zona": "UTC"}, "seis campos"),
    ({"encendido": True, "horario": "*/30 * 9-25 * * 1-5", "zona": "UTC"}, "horas va de 0 a 23"),
    ({"encendido": True, "horario": "0 * 9-17 * * MON-FRI", "zona": "UTC"}, "sólo números"),
    ({"encendido": True, "horario": "*/0 * * * * *", "zona": "UTC"}, "paso de 0"),
    ({"encendido": True, "horario": "0 * 17-9 * * *", "zona": "UTC"}, "hacia atrás"),
    ({"encendido": True, "horario": "* * 9-17 * * 1-5", "zona": "UTC"}, "cada segundo"),
    ({"encendido": True, "horario": "٣ * * * * *", "zona": "UTC"}, "sólo números"),
    ({"encendido": True, "horario": "0 * * * * *", "zona": "Marte/Olympus"}, "zona"),
    # Sin zona, el aparato usa UTC: «de 9 a 18» en México correría de 3 a 12.
    ({"encendido": True, "horario": "0 * 9-17 * * 1-5"}, "falta la zona"),
    ({"encendido": True, "horario": "0 * * * * *", "zona": "UTC", "inactividad_s": 5}, "inactividad"),
    ({"encendido": True, "zona": "UTC"}, "con un horario"),
])
def test_lo_que_no_vale_no_llega_al_aparato_y_se_dice_por_que(entorno, cuerpo, motivo):
    # Un horario que el JetKVM no entiende lo deja sin jiggler sin decirlo.
    c, sim = entorno
    antes = json.dumps(sim._jiggler, sort_keys=True)
    r = c.post("/api/jiggler", json=cuerpo)
    assert r.status_code == 400 and motivo in r.json()["detail"], r.text
    assert json.dumps(sim._jiggler, sort_keys=True) == antes


def test_otra_web_no_toca_el_jiggler_ni_despierta_al_mac(entorno):
    c, sim = entorno
    fuera = {"Origin": "http://otra.web"}
    assert c.post("/api/jiggler", json={"encendido": True}, headers=fuera).status_code == 403
    assert c.post("/api/despertar", headers=fuera).status_code == 403
    assert sim._jiggler["encendido"] is False and sim.despertado == 0


def test_la_persona_despierta_al_mac_sin_dar_el_control_y_claude_solo_con_el(entorno):
    c, sim = entorno
    sim.dormido = True
    r = c.post("/api/despertar", headers=PERSONA)
    assert r.status_code == 200 and r.json()["despierto"] is True, r.text
    assert sim.despertado == 1 and sim.dormido is False
    # Despertar es actuar sobre el Mac: a Claude le hace falta el control.
    assert c.post("/api/despertar").status_code == 423
    c.post("/api/control", json={"accion": "dar"}, headers=PERSONA)
    sim.dormido = True
    assert c.post("/api/despertar").json()["texto"] == "El Mac despertó: ya hay imagen."
    # Ya despierto, no se manda nada ni se presume de haberlo despertado.
    assert c.post("/api/despertar").json()["texto"] == "El Mac ya estaba despierto."
    assert sim.despertado == 2


def test_la_conexion_que_vuelve_sola_quita_el_aviso_y_lo_apunta(entorno):
    # Con el Mac dormido al conectar no hay vídeo y la conexión se da por fallida;
    # al despertarlo, el aparato vuelve a estar conectado sin reconectar.
    c, sim = entorno
    p = c.app.state.puente
    p.error_conexion = "conectado, pero no llega vídeo (¿el Mac está dormido, apagado o sin HDMI?)"
    assert c.get("/api/estado").json()["error_conexion"] == ""
    assert any(e["tipo"] == "conexion" for e in c.get("/api/bitacora").json())


def test_en_el_mcp_despertar_pide_el_control_y_el_jiggler_pregunta_antes():
    assert "despertar_mac" in repertorio.NECESITA_CONTROL and "jiggler" not in repertorio.NECESITA_CONTROL
    permisos = repertorio.reglas()
    assert "mcp__puente-kvm__jiggler" in permisos["ask"]  # cambia algo guardado en el aparato
    assert "mcp__puente-kvm__despertar_mac" in permisos["allow"]


@pytest.mark.parametrize("config, texto", [
    (jiggler.PREAJUSTES["ligero"][1], "Ligero, cada 5 min"),
    ({**FRECUENTE, "timezone": "UTC"}, "Frecuente, cada 30 s"),  # la zona no cuenta en un preajuste
    ({"schedule_cron_tab": "0 * 8-13 * * 1-6", "timezone": "Europe/Madrid"},
     "de lunes a sábado de 8:00 a 14:00, cada minuto (Europe/Madrid)"),
    ({"schedule_cron_tab": "*/10 * * * * 0,6"}, "los fines de semana a todas horas, cada 10 s (UTC)"),
    # Una vez por hora no es «de 9 a 18» a secas: la frecuencia también se dice.
    ({"schedule_cron_tab": "0 0 9-17 * * 1-5", "timezone": "UTC"}, "entre semana de 9:00 a 18:00, cada hora (UTC)"),
    ({"schedule_cron_tab": "*/10 5 1,2 * * *"}, "horario «*/10 5 1,2 * * *» (UTC)"),
])
def test_la_placa_dice_el_horario_en_palabras(config, texto):
    assert jiggler.describir({"encendido": True, "config": config}) == texto
