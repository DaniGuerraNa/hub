"""Lo que escribe el secretario pasa por `memoria.ocultar_secretos` antes de
guardarse (C-0434, el resto de SEC-06; regla dura 5, decisión 302).

Hasta ahora sólo se tapaba lo que entraba de las fuentes (`guardar_evento`).
Una llave que el modelo repitiera al contestar, o que apuntara en una nota o
en un compromiso, se quedaba en `memoria.db`, en su copia diaria y en lo que
se lee en voz alta. Es una red de patrones, no una garantía (regla dura 22):
lo que no tiene forma de llave pasa.
"""

from __future__ import annotations

import pytest

from hub.secretario import conversacion, memoria, motor

#: Una llave de mentira, evidente, con la forma que el filtro conoce.
LLAVE = "sk-ant-EJEMPLO" + "0" * 24


@pytest.fixture
def con():
    c = memoria.conectar()
    yield c
    c.close()


def _tapado(texto: str) -> bool:
    return LLAVE not in texto and "EJEMPLO" not in texto and "[secreto oculto]" in texto


def test_una_nota_se_guarda_con_la_llave_tapada(con):
    nid = memoria.anotar(con, f"la del proveedor es {LLAVE}", tema="claves")
    texto = con.execute("SELECT texto FROM nota WHERE id = ?", (nid,)).fetchone()[0]
    assert _tapado(texto) and texto.startswith("la del proveedor es")


def test_un_compromiso_se_guarda_con_la_llave_tapada(con):
    cid = memoria.comprometer(con, f"rotar {LLAVE} antes del viernes")
    que = con.execute("SELECT que FROM compromiso WHERE id = ?", (cid,)).fetchone()[0]
    assert _tapado(que) and que.startswith("rotar")
    # El mismo compromiso dicho otra vez sigue siendo uno solo.
    assert memoria.comprometer(con, f"rotar {LLAVE} antes del viernes") == cid


def test_lo_que_dice_sin_pasar_por_el_modelo_se_guarda_tapado(con):
    tid = conversacion.decir(con, None, f"Hecho: la guardé como {LLAVE}.")
    assert _tapado(con.execute("SELECT texto FROM turno WHERE id = ?", (tid,)).fetchone()[0])


def test_lo_que_contesta_se_guarda_tapado_y_tambien_mientras_lo_escribe(con, monkeypatch):
    mientras: list[str] = []

    def contesta(prompt, **kw):
        kw["al_trozo"](f"La que pusiste es {LLAVE}")
        mientras.append(con.execute("SELECT texto FROM turno WHERE rol = 'secretario'"
                                    " AND estado = 'escribiendo'").fetchone()[0])
        return motor.Respuesta(texto=f"La que pusiste es {LLAVE}. No la compartas.", sesion="s-1",
                               estructurada=None, segundos=1.0, coste=0, modelo=kw["modelo"])

    monkeypatch.setattr(motor, "llamar", contesta)
    conversacion.recibir(con, "¿qué clave puse ayer?")
    conversacion.atender(con)
    assert mientras and _tapado(mientras[0])
    final = con.execute("SELECT texto, estado FROM turno WHERE rol = 'secretario'").fetchone()
    assert final["estado"] == "listo" and _tapado(final["texto"])
    assert final["texto"].endswith("No la compartas.")


def test_lo_que_no_tiene_forma_de_llave_pasa_igual(con):
    """Una red, no una garantía: no se promete más de lo que tapa."""
    nid = memoria.anotar(con, "la clave del wifi es la de siempre")
    assert con.execute("SELECT texto FROM nota WHERE id = ?", (nid,)).fetchone()[0] == "la clave del wifi es la de siempre"
