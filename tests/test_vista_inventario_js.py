"""Ejecuta el JavaScript del inventario.

Su script es el que lanza agentes: si revienta al arrancar, los botones quedan
inertes sin ningún síntoma visible. Misma lección que la terminal en negro.
"""

from __future__ import annotations

import pytest

from arnes_js import ejecutar, script_de

CONSUMIDOR = {
    "id": "idle", "nombre": "Idle", "enlaces": [], "divergencias": [],
    "cuenta": {"igual": 3}, "deriva": 0,
    "prompt_mantenedor": "Usa el agente mantenedor…",
}

CONTEXTO = {
    "inv": {
        "capacidades": [{
            "tipo": "agente", "nombre": "dev-backend", "ruta": "/a/dev-backend.md",
            "descripcion": "Implementador backend.", "modelo": "opus", "status": "activo",
            "origen": "convencion", "modificado": "2026-08-01T00:00:00+00:00",
            "usado": None, "medible": 1, "proyecto_id": "demo", "proyecto_nombre": "Demo",
        }],
        "por_tipo": {"agente": 1}, "total": 1, "sin_uso": 1, "no_medibles": 0,
        "incompletas": 0, "tipos": ["agente"],
        "proyectos": [{"id": "demo", "nombre": "Demo"}],
    },
    "kits": [{"id": "kit", "nombre": "Kit", "consumidores": [CONSUMIDOR],
              "deriva_total": 0, "capacidades": 5}],
    "tipo": "", "proyecto": "", "titulo": "Inventario", "seccion": "inventario",
}


@pytest.fixture(scope="module")
def ejecucion(tmp_path_factory):
    return ejecutar(script_de("inventario.html", CONTEXTO), tmp_path_factory.mktemp("js"))


def test_el_script_arranca_sin_reventar(ejecucion):
    assert ejecucion["errores"] == []


def test_engancha_el_lanzador_de_agentes(ejecucion):
    """Sin este oyente los botones «Lanzar» quedan inertes y no se nota."""
    assert "document:click" in ejecucion["oyentes"]
