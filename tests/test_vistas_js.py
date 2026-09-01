"""Ejecuta el JavaScript en línea de las vistas nuevas.

Sus scripts son los que paran contenedores y lanzan agentes: si revientan al
arrancar, los botones quedan inertes sin que se note (regla dura 11).
"""

from __future__ import annotations

import pytest

from arnes_js import ejecutar, script_de

CONTEXTO_SERVICIOS = {
    "s": {
        "contenedores": [{
            "contenedor": "facturador-dev-postgres", "proyecto_id": "facturador",
            "proyecto_nombre": "Facturador", "imagen": "pgvector", "estado": "running",
            "detalle": "Up 2 hours", "ultima_vez_visto": "2026-08-28T00:00:00+00:00",
        }],
        "total": 1, "vivos": 1, "sin_atribuir": [], "medido_en": None,
    },
    "hay_docker": True, "titulo": "Servicios", "seccion": "servicios",
}

CONTEXTO_PROYECTO = {
    "p": {"id": "demo", "nombre": "Demo", "dominio": "personal", "status": "activo",
          "guardrail": "ask", "estado_ref": "ESTADO.md", "rutas": [], "asiento": "/tmp/demo"},
    "slots": [], "paneles": [], "archivados": False,
    "estado": {"ruta": "/tmp/demo/ESTADO.md", "declarado": "ESTADO.md", "existe": True,
               "campos": {"estado": "verde"}, "modificado": "2026-08-28T00:00:00+00:00"},
    "capa": {"presente": False, "carpeta": None, "version": None, "tiene_project": False,
             "tiene_capabilities": False, "al_dia": False, "prompt_sembrar": "Crea la capa base"},
    "repos": [], "servicios": {"contenedores": [], "total": 0, "vivos": 0,
                               "sin_atribuir": [], "medido_en": None},
    "titulo": "Demo", "seccion": "panorama",
}


@pytest.fixture(scope="module")
def servicios(tmp_path_factory):
    return ejecutar(script_de("servicios.html", CONTEXTO_SERVICIOS), tmp_path_factory.mktemp("js"))


@pytest.fixture(scope="module")
def proyecto(tmp_path_factory):
    return ejecutar(script_de("proyecto.html", CONTEXTO_PROYECTO), tmp_path_factory.mktemp("js"))


def test_el_script_de_servicios_arranca_sin_reventar(servicios):
    assert servicios["errores"] == []


def test_servicios_engancha_los_botones_de_arrancar_y_parar(servicios):
    assert "document:click" in servicios["oyentes"]


def test_el_script_de_proyecto_arranca_sin_reventar(proyecto):
    assert proyecto["errores"] == []


def test_proyecto_engancha_el_boton_de_sembrar_la_capa_base(proyecto):
    assert "document:click" in proyecto["oyentes"]


@pytest.fixture(scope="module")
def contexto(tmp_path_factory):
    return ejecutar(
        script_de("contexto.html", {"markdown": "# Estado\n", "titulo": "Contexto",
                                    "seccion": "contexto"}),
        tmp_path_factory.mktemp("js"),
    )


def test_el_script_de_contexto_arranca_sin_reventar(contexto):
    assert contexto["errores"] == []


def test_el_boton_de_copiar_queda_enganchado(contexto):
    """Si revienta, el botón de copiar queda mudo y no hay síntoma visible."""
    assert "click" in contexto["oyentes"]
