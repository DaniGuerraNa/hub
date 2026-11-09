"""El script de la portada, ejecutado (regla dura 11, C-0109).

Es lo primero que ve quien acaba de instalar el hub: la guía de primer
arranque. Se pinta oculta y la enseña el script, así que si el script
revienta, quien instala ve una portada vacía y no sabe por dónde empezar.
Ningún test lo ejecutaba.

Se toma de la página **servida** por la app y no de la plantilla con un
contexto armado a mano: la portada necesita el resumen y el raíl enteros, y
copiarlos aquí sería probar una vista que la app no sirve.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from arnes_js import ejecutar, scripts_en_linea
from hub import web

CLAVE = "hub.primer-arranque-oculto"

_MIRAR = """
registro.valores.push('oculta=' + nodo('primer-arranque').hidden);
"""

_CERRAR = _MIRAR + """
nodo('primer-arranque').remove = () => registro.valores.push('quitada');
nodo('primer-arranque-cerrar').disparar('click');
registro.valores.push('guardado=' + localStorage.getItem('CLAVE'));
""".replace("CLAVE", CLAVE)


@pytest.fixture
def guion():
    """El script en línea de la portada de un hub recién instalado."""
    html = TestClient(web.app).get("/").text
    assert 'id="primer-arranque"' in html, "sin proyectos, la portada trae la guía"
    bloques = scripts_en_linea(html)
    assert len(bloques) == 1, "la portada trae un solo script en línea"
    return bloques[0]


def test_sin_proyectos_la_guia_de_primer_arranque_se_enseña(guion, tmp_path):
    r = ejecutar(guion, tmp_path, accion=_MIRAR)
    assert r["errores"] == []
    assert r["valores"] == ["oculta=false"]


def test_no_volver_a_mostrar_la_quita_y_lo_recuerda_en_el_navegador(guion, tmp_path):
    r = ejecutar(guion, tmp_path, accion=_CERRAR)
    assert r["errores"] == []
    assert r["valores"] == ["oculta=false", "quitada", "guardado=1"]


def test_si_ya_se_descarto_no_vuelve_a_salir(guion, tmp_path):
    r = ejecutar(guion, tmp_path, previo=f"localStorage.setItem('{CLAVE}', '1');",
                 accion=_MIRAR)
    assert r["errores"] == []
    assert r["valores"] == ["oculta=undefined"]


def test_con_un_proyecto_la_portada_no_trae_la_guia(tmp_path):
    """Con su carpeta: los de ejemplo del registro recién instalado no cuentan."""
    from hub import db
    con = db.abrir()
    con.execute("INSERT INTO proyecto (id, nombre, asiento) VALUES ('demo','Demo',?)",
                (str(tmp_path),))
    con.commit()
    con.close()
    html = TestClient(web.app).get("/").text
    assert 'id="primer-arranque"' not in html and scripts_en_linea(html) == []
