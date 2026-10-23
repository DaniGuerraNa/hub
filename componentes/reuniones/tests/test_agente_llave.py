"""El agente se identifica ante el hub con su llave (decisión 280 del hub)."""
from __future__ import annotations

import importlib.util
import io
import urllib.error
import urllib.request
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]


@pytest.fixture
def agente(tmp_path, monkeypatch):
    monkeypatch.delenv("REUNIONES_TOKEN", raising=False)
    monkeypatch.setenv("REUNIONES_TOKEN_ARCHIVO", str(tmp_path / "token"))
    monkeypatch.setenv("REUNIONES_LOG", str(tmp_path / "agente.log"))
    spec = importlib.util.spec_from_file_location("agente_prueba", RAIZ / "agente" / "agente.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_la_llave_del_archivo_va_en_la_cabecera_y_se_relee_en_cada_llamada(agente, tmp_path):
    assert "X-Reuniones-Token" not in agente._cabeceras("application/json")
    (tmp_path / "token").write_text("primera\n")
    assert agente._cabeceras("application/json")["X-Reuniones-Token"] == "primera"
    (tmp_path / "token").write_text("segunda")
    assert agente._cabeceras("image/jpeg")["X-Reuniones-Token"] == "segunda"


def test_la_variable_de_entorno_manda_sobre_el_archivo(agente, tmp_path, monkeypatch):
    (tmp_path / "token").write_text("archivo")
    monkeypatch.setenv("REUNIONES_TOKEN", "variable")
    assert agente.llave() == "variable"


def test_un_401_del_hub_se_distingue_de_un_hub_caido(agente, monkeypatch):
    def rechaza(req, timeout=0):
        raise urllib.error.HTTPError(req.full_url, 401, "llave", {}, io.BytesIO(b"{}"))
    monkeypatch.setattr(urllib.request, "urlopen", rechaza)
    with pytest.raises(agente.SinLlave):
        agente._post("/api/reuniones/latido", {})
