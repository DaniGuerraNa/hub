"""Las herramientas de Claude: lo que leen y lo que devuelven."""

import asyncio

import pytest

from puente_kvm import config, mcp_servidor


class Respuesta(Exception):
    pass


@pytest.fixture
def sin_red(monkeypatch):
    """`_llamar` no sale a la red: devuelve lo que se le habría mandado."""
    async def llamar(metodo, ruta, cuerpo=None, timeout=60):
        return {"url": "/cambios/x", "enviado": cuerpo}
    monkeypatch.setattr(mcp_servidor, "_llamar", llamar)


def proponer(**k):
    return asyncio.run(mcp_servidor.proponer_cambio(lectura="l", descripcion="d", **k))


def test_proponer_un_cambio_lee_un_archivo_de_trabajo(sin_red, tmp_path, monkeypatch):
    monkeypatch.setenv("PUENTE_TRABAJO", str(tmp_path))
    (tmp_path / "trabajo").mkdir()
    (tmp_path / "trabajo" / "x.sql").write_text("SELECT 1;\n")
    assert proponer(ruta="trabajo/x.sql")["enviado"]["texto"] == "SELECT 1;\n"
    assert proponer(ruta=str(tmp_path / "trabajo" / "x.sql"))["enviado"]["texto"] == "SELECT 1;\n"


def test_proponer_un_cambio_lee_el_ensamblado_de_una_lectura(sin_red):
    ruta = config.hogar() / "lecturas" / "l-1" / "ensamblado.txt"
    ruta.parent.mkdir(parents=True)
    ruta.write_text("SELECT 2;\n")
    assert proponer(ruta=str(ruta))["enviado"]["texto"] == "SELECT 2;\n"


@pytest.mark.parametrize("ajena", ["~/.config/puente-kvm/entorno", "/etc/passwd", "trabajo/../pyproject.toml",
                                   "../../etc/hostname"])
def test_proponer_un_cambio_no_lee_archivos_de_fuera(sin_red, tmp_path, monkeypatch, ajena):
    monkeypatch.setenv("PUENTE_TRABAJO", str(tmp_path))
    (tmp_path / "trabajo").mkdir()
    with pytest.raises(mcp_servidor.ErrorPuente, match="trabajo"):
        proponer(ruta=ajena)


def test_proponer_un_cambio_no_sigue_un_enlace_que_saca_de_trabajo(sin_red, tmp_path, monkeypatch):
    monkeypatch.setenv("PUENTE_TRABAJO", str(tmp_path))
    (tmp_path / "trabajo").mkdir()
    secreto = tmp_path / "secreto.txt"
    secreto.write_text("clave")
    (tmp_path / "trabajo" / "enlace.sql").symlink_to(secreto)
    with pytest.raises(mcp_servidor.ErrorPuente):
        proponer(ruta="trabajo/enlace.sql")
