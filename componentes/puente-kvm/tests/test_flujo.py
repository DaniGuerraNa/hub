"""El recorrido completo contra el Mac simulado, por la API, como lo haría Claude.

Leer → transcribir → verificar con la huella → proponer → aprobar (la
persona) → escribir → guardar (la persona) → verificar otra vez. Y las
puertas: sin control no se toca nada, sin aprobación no se escribe, Claude no
puede aprobar ni darse el control, y Parar corta a mitad.
"""

import time

import pytest

from .ayuda import PERSONA, esperar, leer, puente_simulado, transcribir_como_oraculo


@pytest.fixture
def entorno():
    with puente_simulado() as (c, sim):
        yield c, sim


def test_lee_el_documento_entero_y_la_copia_es_exacta_segun_la_huella(entorno):
    c, sim = entorno
    lid = leer(c)
    r = c.get(f"/api/lecturas/{lid}").json()
    assert r["estado"] == "capturada"
    assert r["paginas"] >= len(sim.editor.guardado) // sim.editor.filas + 1
    transcribir_como_oraculo(c, sim, lid)
    r = c.get(f"/api/lecturas/{lid}").json()
    assert r["completo"] and r["lineas"] == len(sim.editor.guardado) and r["conflictos"] == 0
    h = c.post(f"/api/lecturas/{lid}/huella", json={"referencia": sim.estado()["huella_base"]}).json()
    assert h["verificada"]
    assert c.get(f"/api/lecturas/{lid}/texto").text.splitlines() == sim.editor.guardado


def test_una_letra_mal_leida_no_pasa_la_huella(entorno):
    c, sim = entorno
    lid = leer(c)
    transcribir_como_oraculo(c, sim, lid, estropear=45)
    h = c.post(f"/api/lecturas/{lid}/huella", json={"referencia": sim.estado()["huella_base"]}).json()
    assert not h["verificada"]


def test_escribe_solo_lo_aprobado_y_la_base_queda_con_exactamente_lo_acordado(entorno):
    c, sim = entorno
    lid = leer(c)
    transcribir_como_oraculo(c, sim, lid)
    assert c.post(f"/api/lecturas/{lid}/huella", json={"referencia": sim.estado()["huella_base"]}).json()["verificada"]

    original = list(sim.editor.guardado)
    nuevo = list(original)
    nuevo[20] = nuevo[20] + "  -- revisado: año fiscal"  # cambiar una línea
    nuevo[60:60] = ["    -- Señal nueva: ¿cuadra?", "    SET @Filas = 0;"]  # insertar
    del nuevo[100]  # borrar
    nuevo[-1] = "END; -- fin"  # tocar la última
    r = c.post("/api/cambios", json={"lectura": lid, "texto": "\n".join(nuevo), "descripcion": "Prueba"})
    assert r.status_code == 200, r.text
    cid = r.json()["id"]

    # Claude no puede escribir lo que la persona no aprobó, ni aprobárselo.
    assert c.post(f"/api/cambios/{cid}/escribir").status_code == 400
    assert c.post(f"/api/cambios/{cid}/aprobar").status_code == 403
    assert c.post(f"/api/cambios/{cid}/aprobar", headers=PERSONA).status_code == 200

    c.post("/api/control", json={"accion": "dar"}, headers=PERSONA)
    assert c.post(f"/api/cambios/{cid}/escribir").status_code == 200
    esperar(c)
    cambio = c.get(f"/api/cambios/{cid}").json()
    assert cambio["estado"] == "escrito", cambio["error"]
    assert sim.editor.lineas == nuevo
    assert sim.editor.guardado == original  # escrito no es guardado

    c.post("/api/simulador/guardar", headers=PERSONA)
    h = c.post(f"/api/cambios/{cid}/huella", json={"referencia": sim.estado()["huella_base"]}).json()
    assert h["verificado"]


def test_si_la_pantalla_no_es_la_que_se_leyo_no_escribe_nada(entorno):
    c, sim = entorno
    lid = leer(c)
    transcribir_como_oraculo(c, sim, lid)
    nuevo = list(sim.editor.guardado)
    nuevo[10] = "-- cambio"
    cid = c.post("/api/cambios", json={"lectura": lid, "texto": "\n".join(nuevo), "descripcion": "x"}).json()["id"]
    c.post(f"/api/cambios/{cid}/aprobar", headers=PERSONA)
    # Alguien toca el documento entre la lectura y la escritura.
    sim.editor.lineas[2] = "    @FechaCorte DATETIME,"
    sim.editor.version += 1
    antes = list(sim.editor.lineas)
    c.post("/api/control", json={"accion": "dar"}, headers=PERSONA)
    c.post(f"/api/cambios/{cid}/escribir")
    esperar(c)
    cambio = c.get(f"/api/cambios/{cid}").json()
    assert cambio["estado"] == "fallido"
    assert "no es la que se leyó" in cambio["error"]
    assert sim.editor.lineas == antes


def test_sin_control_claude_no_puede_tocar_el_mac_ni_darse_el_control(entorno):
    c, sim = entorno
    r = c.post("/api/teclear", json={"texto": "hola"})
    assert r.status_code == 423
    assert c.post("/api/control", json={"accion": "dar"}).status_code == 403
    assert c.post("/api/lecturas", json={"nombre": "x"}).status_code == 423
    assert sim.pulsaciones == 0


def test_otra_pestana_del_navegador_no_puede_teclear(entorno):
    c, _ = entorno
    c.post("/api/control", json={"accion": "dar"}, headers=PERSONA)
    r = c.post("/api/teclear", json={"texto": "x"}, headers={"Origin": "http://malo.example"})
    assert r.status_code == 403


def test_parar_corta_una_lectura_a_medias(entorno):
    c, sim = entorno
    c.post("/api/control", json={"accion": "dar"}, headers=PERSONA)
    lid = c.post("/api/lecturas", json={"nombre": "larga"}).json()["id"]
    time.sleep(0.4)
    c.post("/api/control", json={"accion": "parar"}, headers=PERSONA)
    esperar(c)
    r = c.get(f"/api/lecturas/{lid}").json()
    assert r["estado"] == "cortada"
    pulsaciones = sim.pulsaciones
    time.sleep(0.3)
    assert sim.pulsaciones == pulsaciones  # ya no sale ninguna tecla


def test_las_paginas_del_html_se_sirven(entorno):
    c, sim = entorno
    lid = leer(c)
    assert c.get("/").status_code == 200
    assert c.get(f"/lecturas/{lid}").status_code == 200
    assert c.get("/ajustes").status_code == 200
    assert c.get("/api/pantalla.jpg").headers["content-type"] == "image/jpeg"


def test_el_control_vuelve_solo_a_la_persona_si_claude_no_hace_nada(entorno, monkeypatch):
    c, sim = entorno
    from puente_kvm import control

    c.post("/api/control", json={"accion": "dar"}, headers=PERSONA)
    assert c.post("/api/atajo", json={"atajo": "down"}).status_code == 200
    monkeypatch.setattr(control, "INACTIVIDAD_S", 0)
    time.sleep(0.05)
    assert c.get("/api/estado").json()["control"]["modo"] == "libre"
    assert c.post("/api/teclear", json={"texto": "x"}).status_code == 423


def test_al_terminar_de_leer_o_de_escribir_el_mac_vuelve_a_la_persona(entorno):
    c, sim = entorno
    lid = leer(c)
    assert c.get("/api/estado").json()["control"]["modo"] == "libre"
    transcribir_como_oraculo(c, sim, lid)
    nuevo = list(sim.editor.guardado)
    nuevo[5] = nuevo[5] + " -- x"
    cid = c.post("/api/cambios", json={"lectura": lid, "texto": "\n".join(nuevo), "descripcion": "x"}).json()["id"]
    c.post(f"/api/cambios/{cid}/aprobar", headers=PERSONA)
    assert c.post(f"/api/cambios/{cid}/escribir").status_code == 423  # sin control, ni aprobado basta
    c.post("/api/control", json={"accion": "dar"}, headers=PERSONA)
    c.post(f"/api/cambios/{cid}/escribir")
    esperar(c)
    assert c.get(f"/api/cambios/{cid}").json()["estado"] == "escrito"
    assert c.get("/api/estado").json()["control"]["modo"] == "libre"
