"""El YAML se lee con libyaml cuando está (C-0279).

`projects.yml` (15,7 KB) se leía con el cargador en Python puro: 14,9 ms por
carga frente a 1,6 ms con libyaml, mismo resultado, y el registro se lee dos
veces por latido, en cada vuelta del secretario y en muchas pantallas. Lo que
se exige: que los dos cargadores den exactamente lo mismo con todo lo que el
hub lee, y que sin libyaml se siga leyendo igual.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from hub import config, registry

RAIZ = Path(__file__).resolve().parents[1]


def _muestras() -> list[tuple[str, str]]:
    """Todo YAML del repo y la cabecera de cada ficha de `cambios/`: fechas,
    listas, nulos, cadenas con comillas y sin ellas, tildes."""
    archivos = [p for p in RAIZ.rglob("*.y*ml")
                if ".venv" not in p.parts and p.suffix in (".yml", ".yaml")]
    muestras = [(str(p.relative_to(RAIZ)), p.read_text(encoding="utf-8")) for p in archivos]
    for ficha in sorted((RAIZ / "cambios").glob("C-*.md")):
        m = re.match(r"---\n(.*?)\n---\n", ficha.read_text(encoding="utf-8"), re.S)
        if m:
            muestras.append((ficha.name, m.group(1)))
    return muestras


def test_con_libyaml_instalado_se_usa():
    if not yaml.__with_libyaml__:
        pytest.skip("este PyYAML no trae libyaml")
    assert config.cargador_yaml() is yaml.CSafeLoader
    assert issubclass(registry._SinDuplicados, yaml.CSafeLoader)


def _resultado(leer, texto):
    """Lo leído, o que no se pudo: las plantillas de `semillas/base/contenido/`
    llevan huecos (`@ID@`) y no son YAML hasta rellenarlas. Ahí los dos tienen
    que fallar."""
    try:
        return leer(texto)
    except yaml.YAMLError:
        return "no es YAML"


def test_los_dos_cargadores_leen_lo_mismo_en_todo_lo_del_repo():
    muestras = _muestras()
    # `cambios/` no viaja con el producto: allí sólo quedan los YAML del repo
    # (18 en noviembre de 2026), y exigir 100 dejaba en rojo la suite de quien clona.
    minimo = 100 if (RAIZ / "cambios").is_dir() else 10
    assert len(muestras) > minimo, "sin muestras esto no prueba nada"
    for nombre, texto in muestras:
        assert _resultado(config.leer_yaml, texto) == _resultado(
            lambda t: yaml.load(t, Loader=yaml.SafeLoader), texto), nombre


def test_el_registro_lee_lo_mismo_que_con_el_cargador_de_python(tmp_path):
    ejemplo = (RAIZ / "projects.ejemplo.yml").read_text(encoding="utf-8")
    assert registry._leer(RAIZ / "projects.ejemplo.yml") == yaml.safe_load(ejemplo)


def test_sin_libyaml_se_lee_igual_con_el_de_python(monkeypatch):
    monkeypatch.delattr(yaml, "CSafeLoader", raising=False)
    assert config.cargador_yaml() is yaml.SafeLoader
    assert config.leer_yaml("a: [1, 2]\nb: 2026-11-12\n") == yaml.safe_load(
        "a: [1, 2]\nb: 2026-11-12\n")


def test_un_yaml_roto_sigue_dando_el_error_de_yaml_con_su_linea():
    with pytest.raises(yaml.YAMLError) as exc:
        config.leer_yaml("a: 1\nb: [2, 3\nc: 4\n")
    assert "line" in str(exc.value)
