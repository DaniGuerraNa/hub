"""El agente abre en el navegador de la PC las pantallas del hub que pide el secretario."""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]


@pytest.fixture
def agente(tmp_path, monkeypatch):
    monkeypatch.setenv("REUNIONES_LOG", str(tmp_path / "agente.log"))
    monkeypatch.setenv("REUNIONES_HUB", "http://127.0.0.1:8787")
    spec = importlib.util.spec_from_file_location("agente_abrir", RAIZ / "agente" / "agente.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    abiertas = []
    # El navegador es lo único que no se abre de verdad en un test.
    monkeypatch.delattr(m.os, "startfile", raising=False)
    import webbrowser
    monkeypatch.setattr(webbrowser, "open", abiertas.append)
    m.ABIERTAS = abiertas
    return m


def test_abre_la_ruta_pegada_a_la_direccion_del_hub(agente):
    assert agente.abrir("/trabajo?slot=3") is True
    assert agente.ABIERTAS == ["http://127.0.0.1:8787/trabajo?slot=3"]


@pytest.mark.parametrize("ruta", ["https://malo.example/x", "//malo.example/x", "trabajo", "/\\\\malo\\x"])
def test_una_url_de_fuera_no_se_abre(agente, ruta):
    assert agente.abrir(ruta) is False
    assert agente.ABIERTAS == []
