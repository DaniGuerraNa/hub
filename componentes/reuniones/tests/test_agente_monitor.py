"""El agente graba el monitor donde está la ventana de la app, no el de la última vez.

Las ventanas y los monitores son los medidos el 18-nov con Teams en una llamada:
tres monitores (el 1 principal, el 2 encima, el 3 a la izquierda) y dos ventanas
del proceso, la de la reunión y la principal.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]

MONITORES = [
    {"n": 1, "izq": 0, "arr": 0, "ancho": 1920, "alto": 1080},
    {"n": 2, "izq": 4, "arr": -1080, "ancho": 1920, "alto": 1080},
    {"n": 3, "izq": -1920, "arr": 0, "ancho": 1920, "alto": 1080},
]
REUNION = {"hwnd": 7017416, "titulo": "Revisión semanal | Microsoft Teams",
           "izq": -8, "arr": -8, "ancho": 1936, "alto": 1056}
PRINCIPAL = {"hwnd": 17370652, "titulo": "Chat | Microsoft Teams",
             "izq": -1928, "arr": -8, "ancho": 1936, "alto": 1056}


@pytest.fixture
def agente(tmp_path, monkeypatch):
    monkeypatch.setenv("REUNIONES_LOG", str(tmp_path / "agente.log"))
    monkeypatch.setenv("REUNIONES_RAIZ", str(tmp_path / "grabaciones"))
    spec = importlib.util.spec_from_file_location("agente_monitor", RAIZ / "agente" / "agente.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_una_ventana_maximizada_cae_en_su_monitor_aunque_asome_8_px(agente):
    assert agente.monitor_de(REUNION, MONITORES) == 1
    assert agente.monitor_de(PRINCIPAL, MONITORES) == 3


def test_entre_la_principal_y_la_de_la_reunion_elige_la_de_la_reunion(agente):
    # La principal va primero en orden Z y aun así no es ella.
    assert agente.elegir_ventana([PRINCIPAL, REUNION]) == REUNION


def test_si_solo_esta_la_principal_graba_esa(agente):
    assert agente.elegir_ventana([PRINCIPAL]) == PRINCIPAL


def test_se_queda_con_la_ventana_que_ya_seguia(agente):
    otra = {**REUNION, "hwnd": 1, "titulo": "Otra reunión | Microsoft Teams"}
    assert agente.elegir_ventana([otra, REUNION], preferida=REUNION["hwnd"]) == REUNION


def test_ignora_los_avisos_pequenos(agente):
    aviso = {"hwnd": 2, "titulo": "Notificación", "izq": 1500, "arr": 900, "ancho": 360, "alto": 100}
    assert agente.elegir_ventana([aviso]) is None


def grabacion(agente, monkeypatch, ventanas, **orden):
    g = agente.Grabacion({"id": "20261118-100000", "monitor": 3, "app": "ms-teams.exe",
                          "seguir_app": True, **orden})
    monkeypatch.setattr(agente, "ventanas_de", lambda nombre: ventanas[0])
    return g


def test_al_empezar_cambia_al_monitor_de_la_ventana(agente, monkeypatch):
    g = grabacion(agente, monkeypatch, [[REUNION]])
    assert g._seguir_ventana(MONITORES, 0, al_empezar=True) is True
    assert (g.monitor, g.monitor_origen, g.cambios_monitor) == (1, "ventana", [])


def test_si_no_la_encuentra_se_queda_en_el_de_la_orden_y_lo_dice(agente, monkeypatch):
    g = grabacion(agente, monkeypatch, [[]])
    g.monitor_origen = "heredado"
    assert g._seguir_ventana(MONITORES, 0, al_empezar=True) is False
    assert (g.monitor, g.monitor_origen) == (3, "heredado")


def test_si_la_ventana_aparece_despues_la_adopta_y_apunta_cuando(agente, monkeypatch):
    ventanas = [[]]
    g = grabacion(agente, monkeypatch, ventanas)
    g.monitor_origen = "heredado"
    g._seguir_ventana(MONITORES, 0, al_empezar=True)
    ventanas[0] = [REUNION]
    assert g._seguir_ventana(MONITORES, 30) is True
    assert (g.monitor, g.monitor_origen, g.cambios_monitor) == (1, "ventana", [{"segundo": 30, "monitor": 1, "origen": "ventana"}])


def test_si_la_minimizan_a_mitad_no_salta_a_otra_pantalla(agente, monkeypatch):
    ventanas = [[REUNION]]
    g = grabacion(agente, monkeypatch, ventanas)
    g._seguir_ventana(MONITORES, 0, al_empezar=True)
    ventanas[0] = []
    assert g._seguir_ventana(MONITORES, 15) is False
    assert (g.monitor, g.monitor_origen) == (1, "ventana")


def test_si_la_mueven_de_monitor_la_sigue(agente, monkeypatch):
    ventanas = [[REUNION]]
    g = grabacion(agente, monkeypatch, ventanas)
    g._seguir_ventana(MONITORES, 0, al_empezar=True)
    ventanas[0] = [{**REUNION, "izq": -1928}]
    assert g._seguir_ventana(MONITORES, 45) is True
    assert g.monitor == 3
    assert g.cambios_monitor[-1] == {"segundo": 45, "monitor": 3, "origen": "ventana"}


def test_si_buscar_ventanas_falla_la_grabacion_sigue_y_queda_anotado(agente, monkeypatch):
    g = agente.Grabacion({"id": "20261118-100000", "monitor": 3, "app": "ms-teams.exe", "seguir_app": True})

    def falla(nombre):
        raise OSError("sin user32")
    monkeypatch.setattr(agente, "ventanas_de", falla)
    assert g._seguir_ventana(MONITORES, 0, al_empezar=True) is False
    assert g._seguir_ventana(MONITORES, 15) is False
    assert g.monitor == 3 and g.errores == ["ventanas: sin user32"]


def test_el_estado_y_la_meta_dicen_que_monitor_se_graba_y_de_donde_salio(agente, monkeypatch):
    import json
    g = grabacion(agente, monkeypatch, [[REUNION]])
    g._seguir_ventana(MONITORES, 0, al_empezar=True)
    g.meta()
    m = json.loads((g.dir / "meta.json").read_text(encoding="utf-8"))
    assert (m["monitor"], m["monitor_pedido"], m["monitor_origen"]) == (1, 3, "ventana")
    assert g.estado()["monitor"] == 1 and g.estado()["monitor_origen"] == "ventana"
