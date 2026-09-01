"""Un `projects.yml` mal escrito se explica; no da un 500 desnudo.

Este archivo se edita a mano a propósito (decisión 7), así que equivocarse
escribiéndolo es lo normal y no un caso raro. En la auditoría del 1 de
septiembre se probaron 20 variantes rotas: **9 salían como `KeyError`,
`TypeError` o `AttributeError` crudos** y llegaban a la web como «Internal
Server Error», mientras las demás pantallas seguían en 200 enseñando datos
viejos. Ni decía qué línea, ni que el problema fuera del archivo.

Lo que se exige aquí: `YamlInvalido` siempre, con el proyecto y el campo
nombrados, y 422 en la web.
"""

from __future__ import annotations

import pytest

from hub import registry


ROTOS = {
    "yaml_invalido": ("proyectos:\n  - id: x\n   nombre: mal indentado\n",
                      "no es YAML válido"),
    "raiz_es_lista": ("- uno\n- dos\n", "debe empezar por"),
    "proyectos_no_es_lista": ("proyectos: hola\n", "tiene que ser una lista"),
    "item_escalar": ("proyectos:\n  - texto suelto\n", "no es un bloque de campos"),
    "sin_id": ("proyectos:\n  - nombre: Sin identidad\n", "no tiene `id`"),
    "ruta_sin_ruta": ("proyectos:\n  - id: x\n    rutas:\n      - tipo: repo\n",
                      "están mal"),
    "id_duplicado": ("proyectos:\n  - id: dup\n    nombre: A\n  - id: dup\n"
                     "    nombre: B\n", "mismo id"),
}


@pytest.mark.parametrize("caso", list(ROTOS))
def test_todo_error_de_formato_sale_como_yaml_invalido(tmp_path, caso):
    texto, esperado = ROTOS[caso]
    ruta = tmp_path / "projects.yml"
    ruta.write_text(texto, encoding="utf-8")
    with pytest.raises(registry.YamlInvalido) as exc:
        registry.cargar(ruta)
    assert esperado in str(exc.value)


def test_el_mensaje_nombra_al_proyecto_culpable(tmp_path):
    """«Algo falla» no sirve en un archivo de veinte proyectos."""
    ruta = tmp_path / "projects.yml"
    ruta.write_text(
        "proyectos:\n  - id: bueno\n    nombre: B\n"
        "  - id: culpable\n    rutas:\n      - tipo: repo\n",
        encoding="utf-8",
    )
    with pytest.raises(registry.YamlInvalido, match="culpable"):
        registry.cargar(ruta)


def test_un_id_duplicado_no_desaparece_en_silencio(tmp_path):
    """Antes ganaba el último y el otro se perdía sin avisar.

    De un id cuelgan los slots, las notas y el índice: perder uno en silencio es
    perder sus notas.
    """
    ruta = tmp_path / "projects.yml"
    ruta.write_text(
        "proyectos:\n  - id: dup\n    nombre: Primero\n"
        "  - id: dup\n    nombre: Segundo\n",
        encoding="utf-8",
    )
    with pytest.raises(registry.YamlInvalido, match="dup"):
        registry.cargar(ruta)


VALIDOS = {
    "registro_vacio": "proyectos:\n",
    "lista_vacia": "proyectos: []\n",
    "archivo_vacio": "",
    "id_numerico": "proyectos:\n  - id: 12345\n",
    "acentos_y_emojis": "proyectos:\n  - id: nandu\n    nombre: Proyecto ñandú 😀\n",
    "campos_desconocidos": "proyectos:\n  - id: x\n    inventado: sí\n",
}


@pytest.mark.parametrize("caso", list(VALIDOS))
def test_lo_que_es_raro_pero_valido_se_acepta(tmp_path, caso):
    """La otra mitad: endurecer no puede volverse quisquilloso.

    Un registro vacío es un estado legítimo —acabas de instalar— y un id
    numérico o un nombre con emojis no son un error de nadie.
    """
    ruta = tmp_path / "projects.yml"
    ruta.write_text(VALIDOS[caso], encoding="utf-8")
    registry.cargar(ruta)  # no levanta


def test_la_web_lo_cuenta_en_vez_de_reventar(tmp_path):
    """Y los módulos se dejan como estaban.

    Aquí el entorno se toca con `os.environ` y un `finally`, no con
    `monkeypatch`: el `undo()` de monkeypatch deshace **todo** lo que se puso
    con ese mismo objeto, incluido lo que pusieron los fixtures autouse, y eso
    dejaba el entorno a medias justo antes del `reload` final.
    """
    import importlib
    import os

    from fastapi.testclient import TestClient

    from hub import config, db, web

    roto = tmp_path / "projects.yml"
    roto.write_text("- esto\n- no vale\n", encoding="utf-8")
    antes = os.environ.get("HUB_PROJECTS_YML")
    os.environ["HUB_PROJECTS_YML"] = str(roto)
    for modulo in (config, db, web):
        importlib.reload(modulo)
    try:
        c = TestClient(web.app, raise_server_exceptions=False)
        r = c.post("/refrescar")
        assert r.status_code == 422
        assert "projects.yml" in r.text
    finally:
        if antes is None:
            os.environ.pop("HUB_PROJECTS_YML", None)
        else:
            os.environ["HUB_PROJECTS_YML"] = antes
        for modulo in (config, db, web):
            importlib.reload(modulo)
