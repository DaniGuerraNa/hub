"""El alta de Telegram: el teléfono como lo acepta Telegram."""

import pytest


@pytest.mark.parametrize("crudo, esperado", [
    ("+52 55 1234 5678", "+525512345678"), ("55-1234-5678", "+525512345678"),
    ("+521 55 1234 5678", "+525512345678"), ("5215512345678", "+525512345678"),
    ("+34 600 111 222", "+34600111222"),
])
def test_el_telefono_se_deja_como_lo_quiere_telegram(crudo, esperado):
    from hub.secretario.fuentes.telegram import telefono
    assert telefono(crudo) == esperado


# ── a quién va un mensaje (decisión 332) ─────────────────────────────────────

from hub.secretario import disparadores, memoria, piezas, triaje  # noqa: E402

ALIAS = ["Leonardo", "Leo", "LeoRuizM"]


@pytest.mark.parametrize("texto, grupo, etiqueta, esperado", [
    ("hola", False, False, "privado"),
    ("me ayudas a validar porfis", True, True, "etiqueta"),
    ("@LeoRuizM puedes revisar porfis", True, False, "nombre"),
    ("ya se fueron con el cambio de Leo", True, False, "nombre"),
    ("Léó revisa esto", True, False, "nombre"),
    ("Leonor mañana sube el cambio", True, False, "otros"),
    ("@bhiotek @carlos8583 me ayudan a validar", True, False, "otros"),
])
def test_se_sabe_si_un_mensaje_va_para_el_dueno(texto, grupo, etiqueta, esperado):
    assert piezas.para_mi(texto, ALIAS, grupo=grupo, etiqueta=etiqueta) == esperado


def _evento(con, i, texto, para_mi_, autor="Ruben"):
    return memoria.guardar_evento(con, piezas.Evento(fuente="telegram", id_externo=str(i), fecha="2026-11-02T16:00:00+00:00",
                                                     texto=texto, conversacion="Atlas", autor=autor, para_mi=para_mi_))


def test_recientes_puede_quedarse_solo_con_lo_que_le_hablan_a_el():
    con = memoria.conectar()
    _evento(con, 1, "@bhiotek valida", "otros")
    _evento(con, 2, "Leo revisa el banner", "nombre")
    [m] = memoria.recientes(con, solo_para_mi=True)
    assert m["texto"] == "Leo revisa el banner" and m["para_mi"] == "nombre"
    assert len(memoria.recientes(con)) == 2


def test_el_triaje_ve_en_cada_mensaje_si_no_es_para_el():
    con = memoria.conectar()
    _evento(con, 1, "@bhiotek me ayudas a validar", "otros")
    _evento(con, 2, "Leo revisa el banner", "etiqueta")
    a, b = memoria.sin_triar(con)
    assert "NO va dirigido a él" in triaje._linea(a, True)
    assert "PARA ÉL" in triaje._linea(b, True)


def test_una_memoria_de_antes_gana_la_columna_sin_perder_nada(tmp_path):
    import sqlite3
    ruta = tmp_path / "vieja.db"
    vieja = sqlite3.connect(ruta)
    vieja.execute("CREATE TABLE evento (id INTEGER PRIMARY KEY, fuente TEXT NOT NULL, id_externo TEXT NOT NULL,"
                  " conversacion TEXT NOT NULL DEFAULT '', autor TEXT NOT NULL DEFAULT '', fecha TEXT NOT NULL,"
                  " texto TEXT NOT NULL DEFAULT '', adjuntos TEXT NOT NULL DEFAULT '[]', enlace TEXT NOT NULL DEFAULT '',"
                  " recibido TEXT NOT NULL, triado INTEGER NOT NULL DEFAULT 0, UNIQUE (fuente, id_externo))")
    vieja.execute("INSERT INTO evento (fuente, id_externo, fecha, texto, recibido) VALUES ('t','1','x','hola','x')")
    vieja.commit()
    vieja.close()
    con = memoria.conectar(ruta)
    assert con.execute("SELECT texto, para_mi FROM evento").fetchone()[:] == ("hola", "")


def test_un_disparador_solo_para_mi_no_salta_con_lo_que_es_para_otros():
    con = memoria.conectar()
    _evento(con, 1, "@bhiotek me ayudas", "otros")
    _evento(con, 2, "Leo me ayudas", "nombre")
    a, b = con.execute("SELECT * FROM evento ORDER BY id").fetchall()
    d = disparadores.de_formulario({"clase": "mensaje", "conversacion": "Atlas", "para_mi": "1", "que": "avisar"})
    assert d["cuando"] == {"conversacion": "Atlas", "para_mi": True}
    assert not disparadores._casa_evento(d["cuando"], a)
    assert disparadores._casa_evento(d["cuando"], b)
    assert "que sea para ti" in disparadores.describir(d)
