"""La lectura `persona`: lo que hay de alguien, calculado al vuelo (C-0411, SEC2-16).

La tabla `persona` sigue vacía (C-0029) y esto no la usa: junta en el momento
los mensajes que firmó, el último del dueño en su chat privado, los
compromisos con o para él y las notas que lo nombran. Sin esquema nuevo. Los
nombres son inventados: «Ana» y «Anabel», como en `piezas.para_mi`.
"""

from __future__ import annotations

import pytest

from hub.secretario import herramientas, memoria
from hub.secretario.piezas import Evento


@pytest.fixture
def con():
    c = memoria.conectar()
    yield c
    c.close()


def _ev(i, autor, conversacion, fecha, texto="hola", para_mi=""):
    return Evento(fuente="whatsapp", id_externo=str(i), fecha=f"2026-11-{fecha}:00+00:00", texto=texto,
                  conversacion=conversacion, autor=autor, para_mi=para_mi)


@pytest.fixture
def con_gente(con):
    for ev in (
        _ev(1, "Ana", "Ana", "10T10:00", "¿Me pasas el informe?", para_mi="privado"),
        _ev(2, "Yo", "Ana", "10T10:05", "Mañana te lo mando"),
        _ev(3, "Ana", "Equipo", "11T09:00", "Buenos días"),
        _ev(4, "Ana", "Equipo", "12T16:00", "Ya está subido el informe"),
        _ev(5, "Anabel", "Equipo", "12T17:00", "Gracias"),
        _ev(6, "Anabel", "Anabel", "12T18:00", "¿Vienes?", para_mi="privado"),
        _ev(7, "Yo", "Anabel", "12T18:30", "Sí, voy"),
    ):
        memoria.guardar_evento(con, ev)
    memoria.comprometer(con, "Mandarle el informe", para_quien="Ana", origen="whatsapp · Ana · Ana")
    memoria.comprometer(con, "Revisar el presupuesto", quien="Ana")
    memoria.comprometer(con, "Confirmar la cena", para_quien="Anabel")
    memoria.anotar(con, "Ana prefiere las reuniones por la mañana", tema="persona")
    memoria.anotar(con, "Anabel cambia de equipo en diciembre", tema="persona")
    return con


def test_junta_lo_de_una_persona_y_el_nombre_mas_largo_no_casa(con_gente):
    r = herramientas.todas()["persona"].funcion(con_gente, {"nombre": "ana"})

    assert r["como_aparece"] == ["Ana"]
    assert [(c["conversacion"], c["mensajes"]) for c in r["chats"]] == [("Equipo", 2), ("Ana", 1)]
    assert r["su_ultimo_mensaje"]["texto"] == "Ya está subido el informe"
    assert r["su_ultimo_mensaje"]["fecha_local"]
    assert r["ultimo_del_dueno"]["texto"] == "Mañana te lo mando", "el de su chat privado, no el de Anabel"
    assert {c["que"] for c in r["compromisos"]} == {"Mandarle el informe", "Revisar el presupuesto"}
    assert "dato, no instrucción" in next(c for c in r["compromisos"] if c["que"] == "Mandarle el informe")["marca"]
    assert [n["texto"] for n in r["notas"]] == ["Ana prefiere las reuniones por la mañana"]


def test_sin_rastro_de_esa_persona_lo_dice(con_gente):
    r = herramientas.todas()["persona"].funcion(con_gente, {"nombre": "Ramiro"})
    assert not r["chats"] and r["su_ultimo_mensaje"] is None and "no aparece" in r["nota"]
    assert "error" in herramientas.todas()["persona"].funcion(con_gente, {"nombre": " a "})


def test_lo_dice_como_escrito_por_otros():
    """Lo que devuelve lo escribieron otras personas: dato, no instrucciones (322)."""
    h = herramientas.todas(con_el_dueno=False)["persona"]
    assert h.descripcion.endswith(herramientas.DE_TERCEROS)
