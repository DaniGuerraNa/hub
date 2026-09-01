"""Las skills que viajan con el repo: que existan y que se puedan descubrir.

Una skill mal formada no falla: simplemente Claude no la carga, y el usuario pide
«instala este repo» y no pasa nada. Ese silencio es lo que esto ataca.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

RAIZ = Path(__file__).resolve().parents[1]
SKILLS = sorted((RAIZ / ".claude" / "skills").glob("*/SKILL.md"))

ESPERADAS = {
    "instalar-hub", "anexar-proyecto", "nuevo-proyecto",
    "aplicar-kit", "nuevo-kit", "mantener-kit",
}


def test_estan_todas_las_skills_de_los_flujos():
    assert {s.parent.name for s in SKILLS} >= ESPERADAS


@pytest.mark.parametrize("skill", SKILLS, ids=lambda p: p.parent.name)
def test_el_frontmatter_permite_descubrirla(skill: Path):
    texto = skill.read_text(encoding="utf-8")
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n", texto, re.S)
    assert m, f"{skill.parent.name}: sin frontmatter, Claude no la carga"
    datos = yaml.safe_load(m.group(1))
    assert datos.get("name") == skill.parent.name, "el `name` debe ser el de la carpeta"
    # La descripción es lo ÚNICO que decide si la skill se activa: sin decir
    # cuándo usarla, existe pero no se encuentra nunca.
    assert len(str(datos.get("description", ""))) > 60


@pytest.mark.parametrize("skill", SKILLS, ids=lambda p: p.parent.name)
def test_las_ordenes_que_cita_existen(skill: Path):
    """Una skill que manda correr un script inexistente falla en manos del usuario."""
    texto = skill.read_text(encoding="utf-8")
    for guion in re.findall(r"bash (scripts/[\w.-]+)", texto):
        assert (RAIZ / guion).is_file(), f"{skill.parent.name} cita {guion}, que no existe"


def test_los_flujos_estan_documentados_en_un_solo_sitio():
    flujos = (RAIZ / "FLUJOS.md").read_text(encoding="utf-8")
    for nombre in ESPERADAS:
        assert nombre in flujos, f"{nombre} no aparece en FLUJOS.md"
