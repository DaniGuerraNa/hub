"""projects.yml manda sobre el índice, y la atribución usa la ruta más específica."""

from __future__ import annotations

from pathlib import Path

import pytest

from hub import api, registry
from hub.registry import Atribuidor

YAML_DEMO = """
proyectos:
  - id: facturador
    nombre: Facturador
    asiento: /mnt/c/proyects/facturador-main
    rutas:
      - ruta: /home/ana/dev/facturador
      - ruta: /home/ana/dev/facturador-front
  - id: idle
    nombre: Idle
    dominio: personal
    asiento: /mnt/c/proyects/Idle
"""


@pytest.fixture
def yaml_demo(tmp_path) -> Path:
    ruta = tmp_path / "projects.yml"
    ruta.write_text(YAML_DEMO, encoding="utf-8")
    return ruta


def test_carga_asiento_y_repos(yaml_demo):
    proyectos = registry.cargar(yaml_demo)
    facturador = next(p for p in proyectos if p.id == "facturador")
    assert facturador.asiento == "/mnt/c/proyects/facturador-main"
    assert len(facturador.todas_las_rutas()) == 3


def test_sincronizar_refleja_altas_y_bajas(con, yaml_demo):
    registry.sincronizar(con, registry.cargar(yaml_demo))
    assert len(api.listar_proyectos(con)) == 2

    # El YAML manda: lo que desaparece de ahí, desaparece del índice.
    yaml_demo.write_text(
        "proyectos:\n  - id: idle\n    nombre: Idle\n", encoding="utf-8"
    )
    registry.sincronizar(con, registry.cargar(yaml_demo))
    assert [p["id"] for p in api.listar_proyectos(con)] == ["idle"]


def test_atribucion_prefiere_la_ruta_mas_larga(yaml_demo):
    """~/dev/facturador-front no debe caer en ~/dev/facturador."""
    atribuidor = Atribuidor(registry.cargar(yaml_demo))
    assert atribuidor.atribuir("/home/ana/dev/facturador-front/apps/web") == "facturador"
    assert atribuidor.atribuir("/home/ana/dev/facturador/apps") == "facturador"
    assert atribuidor.atribuir("/mnt/c/proyects/Idle") == "idle"


def test_atribucion_no_confunde_prefijos_parciales(yaml_demo):
    atribuidor = Atribuidor(registry.cargar(yaml_demo))
    assert atribuidor.atribuir("/home/ana/dev/facturador-otro-repo") is None
    assert atribuidor.atribuir("/home/ana/otra-cosa") is None
