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


def test_un_patron_en_rutas_se_expande_a_los_repos_git_que_existen(tmp_path):
    """Un workspace que contiene repos los declara con `patron:`, no uno a uno."""
    ws = tmp_path / "workspace"
    for nombre in ("ext/repos/a", "ext/repos/b", "int/repos/c", "ext/repos/sin-git"):
        (ws / nombre).mkdir(parents=True)
    (ws / "ext/repos/a/.git").mkdir()
    (ws / "int/repos/c/.git").write_text("gitdir: /otro/sitio")   # un worktree
    (ws / "ext/repos/b/.git").mkdir()
    (ws / "ext/repos/archivo.txt").write_text("no soy un repo")
    yml = tmp_path / "projects.yml"
    yml.write_text(f"""
proyectos:
  - id: trabajo
    nombre: Trabajo
    asiento: {ws}
    rutas:
      - patron: "*/repos/*"
""", encoding="utf-8")
    [p] = registry.cargar(yml)
    assert [Path(r.ruta).relative_to(ws).as_posix() for r in p.rutas] == [
        "ext/repos/a", "ext/repos/b", "int/repos/c",
    ]
    assert all(r.tipo == "repo" for r in p.rutas)
    assert p.todas_las_rutas()[-1] == str(ws)


def test_un_patron_sin_coincidencias_no_es_error(tmp_path):
    """Un workspace recién instalado está vacío a propósito: cero rutas, no un fallo."""
    ws = tmp_path / "vacio"
    ws.mkdir()
    yml = tmp_path / "projects.yml"
    yml.write_text(f"""
proyectos:
  - id: trabajo
    nombre: Trabajo
    asiento: {ws}
    rutas:
      - patron: "*/repos/*"
""", encoding="utf-8")
    [p] = registry.cargar(yml)
    assert p.rutas == []


def test_un_patron_relativo_sin_asiento_se_rechaza(tmp_path):
    yml = tmp_path / "projects.yml"
    yml.write_text("""
proyectos:
  - id: trabajo
    nombre: Trabajo
    rutas:
      - patron: "*/repos/*"
""", encoding="utf-8")
    with pytest.raises(registry.YamlInvalido, match="asiento"):
        registry.cargar(yml)
