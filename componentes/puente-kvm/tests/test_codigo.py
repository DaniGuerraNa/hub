"""El puente dice cuándo corre un código que ya no es el del disco.

Tras actualizar, sus pantallas (que se leen del disco en cada visita) salían
nuevas, pero lo que hacían seguía siendo lo de antes hasta reiniciarlo: las
casillas de «Sin pedir permisos» y de la rueda estaban y no hacían nada.
"""

import os

import pytest

from puente_kvm import config

from .ayuda import puente_simulado


def test_avisa_solo_si_el_contenido_del_codigo_cambio(tmp_path):
    (tmp_path / "a.py").write_text("x = 1\n")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.py").write_text("y = 2\n")
    codigo = config.Codigo(tmp_path)
    assert not codigo.viejo()
    # Tocado con el mismo contenido (un checkout que vuelve a escribirlo): no es otro código.
    os.utime(tmp_path / "a.py", ns=(10**9, 10**9))
    assert not codigo.viejo()
    (tmp_path / "sub" / "b.py").write_text("y = 3\n")
    assert codigo.viejo()


def test_un_modulo_nuevo_tambien_es_otro_codigo(tmp_path):
    (tmp_path / "a.py").write_text("x = 1\n")
    codigo = config.Codigo(tmp_path)
    (tmp_path / "nuevo.py").write_text("")
    assert codigo.viejo()


def test_la_huella_del_disco_cambia_con_el_contenido_y_no_con_la_fecha(tmp_path):
    """La que guarda cada conversación al abrirse, para saber si sus
    herramientas son de antes de actualizar (C-0470)."""
    (tmp_path / "a.py").write_text("x = 1\n")
    codigo = config.Codigo(tmp_path)
    primera = codigo.huella_disco()
    os.utime(tmp_path / "a.py", ns=(10**9, 10**9))
    assert codigo.huella_disco() == primera
    (tmp_path / "a.py").write_text("x = 2\n")
    assert codigo.huella_disco() != primera and codigo.viejo()


def test_el_estado_lo_dice_para_que_la_pantalla_lo_avise(monkeypatch):
    with puente_simulado(lineas=3) as (c, sim):
        assert c.get("/api/estado").json()["codigo_viejo"] is False
        monkeypatch.setattr(config.CODIGO_EN_MARCHA, "viejo", lambda: True)
        assert c.get("/api/estado").json()["codigo_viejo"] is True


def test_ocupado_es_una_tarea_en_marcha_o_el_control_dado_a_claude():
    from puente_kvm.comprobar import ocupado
    libre = {"tarea": None, "control": {"modo": "libre"}}
    assert ocupado(libre) == ""
    assert ocupado(None) == ""  # no está en marcha: reiniciar no corta nada
    assert "capturando" in ocupado({**libre, "tarea": "capturando"})
    assert "control" in ocupado({**libre, "control": {"modo": "claude"}})
    # Lo que la persona teclea en el Mac desde la pantalla también se cortaría (C-0470).
    assert "pantalla" in ocupado({**libre, "mando": True})
    assert ocupado({**libre, "mando": False}) == ""


@pytest.mark.parametrize("estado, sale", [(None, 0), ({"tarea": None, "control": {"modo": "libre"}}, 0),
                                          ({"tarea": "capturando", "control": {"modo": "libre"}}, 3),
                                          ({"ajeno": 500}, 4), ({"ajeno": "ocupado"}, 4)])
def test_si_en_su_puerto_contesta_otra_cosa_no_se_da_por_libre(monkeypatch, estado, sale):
    from puente_kvm import comprobar
    monkeypatch.setattr(comprobar, "_preguntar_al_puente", lambda: estado)
    assert comprobar.orden_ocupado() == sale
