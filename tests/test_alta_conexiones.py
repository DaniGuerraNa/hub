"""Dar de alta una conexión escribe en `projects.yml` — la fuente de verdad.

Por eso se prueba con más cuidado que un formulario normal: si esto deja el
archivo mal, el hub se queda sin proyectos. Las tres cosas que hay que
garantizar son que lo de antes sigue ahí, que lo nuevo se lee, y que nunca entra
un secreto (decisión 28).
"""

from __future__ import annotations

import pytest
import yaml

from hub import registry

BASE = """\
# Un comentario que tiene que sobrevivir.
proyectos:
  - id: demo
    nombre: Demo
    rutas:
      - ruta: /tmp/demo
        tipo: repo

conexiones:
  - alias: vps-viejo
    host: 10.0.0.1
    proposito: el de siempre
"""


@pytest.fixture()
def yml(tmp_path):
    ruta = tmp_path / "projects.yml"
    ruta.write_text(BASE, encoding="utf-8")
    return ruta


def test_añade_sin_tocar_lo_que_ya_estaba(yml):
    registry.añadir_conexion(
        {"alias": "vps-pruebas", "host": "10.0.0.4", "usuario": "deploy",
         "proposito": "pruebas", "referencia_secreto": "~/.ssh/config#pruebas",
         "proyectos": ["demo"]},
        ruta=yml,
    )
    texto = yml.read_text()
    # El comentario y el proyecto siguen donde estaban: se inserta un bloque, no
    # se vuelca el documento entero. Un `safe_dump` habría borrado el comentario
    # y reordenado las claves de un archivo que se edita a mano.
    assert "# Un comentario que tiene que sobrevivir." in texto
    datos = yaml.safe_load(texto)
    assert [p["id"] for p in datos["proyectos"]] == ["demo"]
    alias = [c["alias"] for c in datos["conexiones"]]
    assert alias == ["vps-viejo", "vps-pruebas"]

    nueva = datos["conexiones"][1]
    assert nueva["host"] == "10.0.0.4"
    assert nueva["proyectos"] == ["demo"]
    # Y se lee de vuelta por el camino normal, que es lo que de verdad importa.
    assert "vps-pruebas" in [c.alias for c in registry.cargar_conexiones(yml)]


def test_crea_la_seccion_si_no_existe(tmp_path):
    ruta = tmp_path / "projects.yml"
    ruta.write_text("proyectos:\n  - id: demo\n    nombre: Demo\n", encoding="utf-8")
    registry.añadir_conexion({"alias": "solo"}, ruta=ruta)
    assert [c.alias for c in registry.cargar_conexiones(ruta)] == ["solo"]


def test_los_campos_vacios_no_ensucian_el_archivo(yml):
    registry.añadir_conexion({"alias": "pelada", "host": "", "nota": ""}, ruta=yml)
    bloque = [c for c in yaml.safe_load(yml.read_text())["conexiones"]
              if c["alias"] == "pelada"][0]
    # Sólo la clave que tiene valor: un `host: ''` se lee como «tiene host y es
    # vacío», que es distinto de «no tiene host».
    assert bloque == {"alias": "pelada"}


def test_rechaza_un_alias_repetido(yml):
    with pytest.raises(registry.YamlInvalido, match="Ya existe"):
        registry.añadir_conexion({"alias": "vps-viejo"}, ruta=yml)
    assert yml.read_text() == BASE   # no se tocó


def test_rechaza_el_alias_vacio(yml):
    with pytest.raises(registry.YamlInvalido):
        registry.añadir_conexion({"alias": "   "}, ruta=yml)
    assert yml.read_text() == BASE


def test_un_campo_que_no_esta_en_la_lista_blanca_no_llega_al_archivo(yml):
    """La defensa contra guardar secretos es la lista blanca, no un filtro.

    Aunque el formulario mande `password`, el archivo no puede recibirlo: sólo
    se escriben los seis campos declarados.
    """
    registry.añadir_conexion(
        {"alias": "limpia", "password": "hunter2", "token": "abc"}, ruta=yml
    )
    texto = yml.read_text()
    assert "hunter2" not in texto and "password" not in texto and "token" not in texto


def test_los_valores_raros_se_escapan(yml):
    """Un alias con dos puntos rompería el YAML si se pegara en crudo."""
    registry.añadir_conexion(
        {"alias": "raro: si", "nota": "con # almohadilla y 'comillas'"}, ruta=yml
    )
    datos = yaml.safe_load(yml.read_text())
    nueva = [c for c in datos["conexiones"] if c["alias"] == "raro: si"][0]
    assert nueva["nota"] == "con # almohadilla y 'comillas'"
