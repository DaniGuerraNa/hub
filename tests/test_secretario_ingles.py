"""El modo inglés del secretario (C-0159, decisión 354).

Práctica de conversación: el modelo contesta en inglés, y lo que lo frena de
hacer cosas no es el prompt sino el código. Las acciones se ejecutan de verdad
(una acción que cuenta), no con dobles del freno.
"""

from __future__ import annotations

import json

import pytest

from hub.secretario import conversacion, herramientas, memoria, motor, piezas

pytestmark = pytest.mark.usefixtures("canal_telegram")


@pytest.fixture
def con():
    c = memoria.conectar()
    yield c
    c.close()


class Contadora(piezas.Accion):
    id, riesgo, nivel_inicial = "contar", "reversible", "auto"
    hechas = 0

    def ejecutar(self, con, params):
        Contadora.hechas += 1
        return "contado"


def _contestando(con, texto, monkeypatch):
    """Él dijo `texto` y el secretario lo está contestando."""
    t = conversacion.recibir(con, texto)
    rid = conversacion.decir(con, t["hilo"], "…")
    memoria.poner(con, f"turno_en_curso:{t['hilo']}", rid)
    monkeypatch.setenv("SECRETARIO_HILO", str(t["hilo"]))
    return t


def test_el_modo_se_queda_puesto_hasta_quitarlo_y_marca_cada_turno(con):
    assert conversacion.ingles(con) is False
    conversacion.poner_ingles(con, True)
    a = conversacion.recibir(con, "hi there")
    conversacion.poner_ingles(con, False)
    b = conversacion.recibir(con, "hola")
    marcas = dict(con.execute("SELECT id, ingles FROM turno").fetchall())
    assert marcas == {a["turno"]: 1, b["turno"]: 0}


def test_en_ingles_una_accion_automatica_pide_permiso_y_no_se_hace(con, monkeypatch):
    monkeypatch.setattr(piezas, "acciones", lambda: {"contar": Contadora()})
    Contadora.hechas = 0
    conversacion.poner_ingles(con, True)
    _contestando(con, "we should count that", monkeypatch)
    r = herramientas.todas()["accion_contar"].funcion(con, {"motivo": "he said so"})
    assert r["hecho"] is False and r["solicitud"]
    assert Contadora.hechas == 0
    assert con.execute("SELECT estado FROM solicitud").fetchone()[0] == "pendiente"


def test_fuera_del_modo_la_misma_accion_se_hace(con, monkeypatch):
    monkeypatch.setattr(piezas, "acciones", lambda: {"contar": Contadora()})
    Contadora.hechas = 0
    _contestando(con, "cuéntalo", monkeypatch)
    assert herramientas.todas()["accion_contar"].funcion(con, {})["hecho"] is True
    assert Contadora.hechas == 1


def test_los_disparadores_no_los_frena_el_modo(con):
    """Lo que él programó sigue a su hora: el freno es sólo de la conversación."""
    Contadora.hechas = 0
    conversacion.poner_ingles(con, True)
    assert herramientas.usar_accion(con, Contadora(), {})["hecho"] is True


def test_never_sigue_siendo_never_con_el_techo(con, monkeypatch):
    monkeypatch.setattr(piezas, "niveles", lambda: {"contar": "never"})
    r = herramientas.usar_accion(con, Contadora(), {}, techo="ask")
    assert r["hecho"] is False and con.execute("SELECT COUNT(*) FROM solicitud").fetchone()[0] == 0


def test_en_ingles_no_se_contesta_al_orquestador(con, monkeypatch):
    conversacion.poner_ingles(con, True)
    _contestando(con, "tell the orchestrator yes", monkeypatch)
    r = herramientas.todas()["contestar_al_orquestador"].funcion(con, {})
    assert r["ok"] is False and "inglés" in r["error"]


def test_el_turno_llega_al_modelo_marcado_y_la_respuesta_hereda_la_marca(con, monkeypatch):
    vistos = []

    def falso(prompt, **kw):
        vistos.append(prompt)
        return motor.Respuesta(texto="Sounds good!", sesion=kw["sesion"], estructurada=None, segundos=0.1,
                               coste=0, modelo=kw["modelo"])
    monkeypatch.setattr(motor, "llamar", falso)
    monkeypatch.setattr(conversacion, "sistema", lambda: "S")
    conversacion.poner_ingles(con, True)
    conversacion.recibir(con, "I'm working on the hub")
    conversacion.atender(con)
    assert vistos[0].endswith("(english mode) I'm working on the hub")
    assert con.execute("SELECT ingles FROM turno WHERE rol = 'secretario'").fetchone()[0] == 1


def test_al_cerrar_la_practica_va_marcada_y_solo_da_una_nota_de_nivel(con, monkeypatch):
    pedidos = []

    def falso(prompt, **kw):
        pedidos.append(prompt)
        return motor.Respuesta(texto="", sesion="s", segundos=0.1, coste=0, modelo=kw["modelo"],
                               estructurada={"titulo": "Práctica", "resumen": "Practicó inglés.", "notas": []})
    monkeypatch.setattr(motor, "llamar", falso)
    conversacion.poner_ingles(con, True)
    t = conversacion.recibir(con, "I goed to the gym")
    conversacion.cerrar(con, conversacion.hilo_abierto(con))
    assert "[práctica de inglés] Él: I goed to the gym" in pedidos[0]
    assert "tema «inglés»" in pedidos[0]
    assert t["hilo"]


def test_la_regla_del_modo_va_en_el_sistema(con):
    s = conversacion.SISTEMA
    assert "(english mode)" in s and "Tip:" in s and "solicitud" in s
    # Visto en el teléfono el 5-nov: sin errores ponía «Tip: todo bien».
    assert "Si no hay error, NO pongas «Tip»" in s



def test_si_escala_al_modelo_mayor_sigue_en_ingles_y_con_el_freno(con, monkeypatch):
    monkeypatch.setattr(piezas, "acciones", lambda: {"contar": Contadora()})
    Contadora.hechas = 0
    vistos = []

    def falso(prompt, **kw):
        vistos.append(prompt)
        if len(vistos) == 1:
            herramientas._escalar(con, {"motivo": "plan"})
        else:
            # El mayor, con el mismo hilo (su MCP), intenta hacerlo.
            vistos.append(herramientas.todas()["accion_contar"].funcion(con, {}))
        return motor.Respuesta(texto="ok", sesion=kw["sesion"], estructurada=None, segundos=0.1, coste=0,
                               modelo=kw["modelo"])
    monkeypatch.setattr(motor, "llamar", falso)
    monkeypatch.setattr(conversacion, "sistema", lambda: "S")
    conversacion.poner_ingles(con, True)
    t = conversacion.recibir(con, "plan my week")
    monkeypatch.setenv("SECRETARIO_HILO", str(t["hilo"]))
    conversacion.atender(con)
    assert vistos[1].startswith("(english mode) ")
    assert vistos[2]["hecho"] is False and Contadora.hechas == 0
