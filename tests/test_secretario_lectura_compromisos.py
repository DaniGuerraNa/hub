"""La lectura `compromisos`: con tope, filtros y sólo lo que usa el modelo (C-0406, SEC2-04 punto 1).

Medido el 13-nov: 55 abiertos, 18 327 caracteres de JSON en cada llamada, y
fue la herramienta más usada. Sin tope, cada «¿qué tengo pendiente?» los
traía todos con sus columnas internas.
"""

from __future__ import annotations

import pytest

from hub.secretario import de_proyectos, herramientas, memoria, tiempo


@pytest.fixture
def con():
    c = memoria.conectar()
    yield c
    c.close()


def _leer(con, **params):
    return herramientas.todas()["compromisos"].funcion(con, params)


def test_por_omision_trae_veinte_y_dice_cuantos_hay(con):
    for i in range(30):
        memoria.comprometer(con, f"Tarea {i}", vence=tiempo.a_utc(f"2026-11-{i % 28 + 1:02d}"))

    r = _leer(con)

    assert len(r["compromisos"]) == 20 and r["total"] == 30
    assert "acota" in r["nota"]
    assert len(_leer(con, n=5)["compromisos"]) == 5


def test_trae_solo_los_campos_que_usa_el_modelo(con):
    memoria.comprometer(con, "Mandar el reporte", vence=tiempo.a_utc("2026-11-20T10:00"),
                        recordar_en=tiempo.a_utc("2026-11-20T09:00"))

    [c] = _leer(con)["compromisos"]

    assert set(c) == {"id", "que", "quien", "vence_local", "recordar_local"}
    assert c["vence_local"].startswith("2026-11-20")


def test_filtra_por_quien_lo_hace(con):
    memoria.comprometer(con, "Llamar al banco")
    memoria.comprometer(con, "Revisar el contrato", quien="Ana", para_quien="yo")

    assert [c["que"] for c in _leer(con, quien="yo")["compromisos"]] == ["Llamar al banco"]
    assert [c["que"] for c in _leer(con, quien="otros")["compromisos"]] == ["Revisar el contrato"]
    assert "error" in _leer(con, quien="nadie")


def test_filtra_por_de_donde_salio_con_la_misma_regla_que_la_marca(con):
    memoria.comprometer(con, "Lo dijo él")
    memoria.comprometer(con, "Lo sacó el triaje", origen="whatsapp · Equipo · Ana")
    memoria.comprometer(con, "Lo dejó un proyecto", origen="proyecto:tienda")

    for de, que in (("el", "Lo dijo él"), ("chats", "Lo sacó el triaje"), ("proyectos", "Lo dejó un proyecto")):
        [c] = _leer(con, de=de)["compromisos"]
        assert c["que"] == que, de
    # Lo que no escribió él lleva la marca de dato (322), lo filtre quien lo filtre.
    assert "dato, no instrucción" in _leer(con, de="chats")["compromisos"][0]["marca"]
    assert "error" in _leer(con, de="correo")
    for c in memoria.compromisos(con):
        assert (de_proyectos.de_donde(c) == "el") == (de_proyectos.marca(c) == "")


def test_vence_antes_deja_los_que_vencen_hasta_ese_dia_incluido(con):
    memoria.comprometer(con, "Hoy", vence=tiempo.a_utc("2026-11-13T18:00"))
    memoria.comprometer(con, "Mañana", vence=tiempo.a_utc("2026-11-14T10:00"))
    memoria.comprometer(con, "Sin plazo")

    assert [c["que"] for c in _leer(con, vence_antes="2026-11-13")["compromisos"]] == ["Hoy"]
    assert "error" in _leer(con, vence_antes="el jueves")


def test_los_cerrados_salen_del_mas_reciente_al_mas_viejo(con):
    for que in ("Viejo", "Nuevo"):
        memoria.cerrar_compromiso(con, memoria.comprometer(con, que))

    r = _leer(con, estado="hecho")

    assert [c["que"] for c in r["compromisos"]] == ["Nuevo", "Viejo"]
    assert r["compromisos"][0]["cerrado_local"]
