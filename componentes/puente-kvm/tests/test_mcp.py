"""Las herramientas de Claude: lo que leen y lo que devuelven."""

import asyncio
import io
import json

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


# ── lo que le llega a Claude (C-0471) ───────────────────────────────────────
ESTADO_DE_LA_PANTALLA = {
    "version": "0.9.0", "codigo_viejo": False, "t": 1.0, "espacio": "/x", "codigo": "/x",
    "control": {"modo": "persona", "desde": 1.0, "motivo": "botón Parar"},
    "dispositivo": {"tipo": "simulador", "conectado": False, "motivo": "", "resolucion": None,
                    "huella_base": "944B13", "url": "http://jetkvm.local", "jiggler": {"encendido": False},
                    "nota": "Mac simulado"},
    "claude": {"estado": "esperando"}, "reunion": {"grabando": False}, "perfil": {"nombre": "x"},
    "error_conexion": "", "tarea": None, "progreso": "", "mando": False, "jiggler_texto": "apagado",
    "conversacion": None, "conversacion_anterior": False, "claude_code": {"ruta": "/x/claude"},
    "lecturas": [{"id": "l-1", "nombre": "usp_Año", "estado": "capturada", "error": "", "paginas": 2,
                  "transcritas": 0, "conflictos": 0, "huecos": [], "completo": False, "verificada": False,
                  "variante": None, "errores_por_pagina": {}, "inestables": [], "archivo": "/x/ensamblado.txt"}],
    "cambios": [],
}


@pytest.fixture
def estado_de_la_pantalla(monkeypatch):
    async def llamar(metodo, ruta, cuerpo=None, timeout=60):
        assert ruta == "/api/estado"
        return json.loads(json.dumps(ESTADO_DE_LA_PANTALLA))
    monkeypatch.setattr(mcp_servidor, "_llamar", llamar)


def test_estado_no_le_da_la_huella_base_ni_la_url_y_dice_que_no_hay_conexion(estado_de_la_pantalla):
    e = asyncio.run(mcp_servidor.estado())
    assert e["dispositivo"] == {"tipo": "simulador", "conectado": False, "nota": "Mac simulado"}
    assert e["control"] == {"modo": "persona", "motivo": "botón Parar"}
    assert e["mando"] is False  # un «no» también dice algo: no se quita como lo vacío
    assert e["lecturas"] == [{"id": "l-1", "nombre": "usp_Año", "estado": "capturada", "paginas": 2,
                              "transcritas": 0, "conflictos": 0, "completo": False, "verificada": False}]
    for fuera in ("version", "perfil", "reunion", "claude", "espacio", "tarea", "progreso", "cambios",
                  "error_conexion", "claude_code"):
        assert fuera not in e


def test_las_herramientas_le_devuelven_json_compacto_una_sola_vez_y_con_sus_acentos(estado_de_la_pantalla):
    salida = asyncio.run(mcp_servidor.mcp.call_tool("estado", {}))
    assert len(salida) == 1 and salida[0].type == "text"  # sin una copia estructurada al lado
    texto = salida[0].text
    assert json.loads(texto) == asyncio.run(mcp_servidor.estado())
    assert "\n" not in texto and ": " not in texto and "botón" in texto and "\\u" not in texto


def test_toda_herramienta_del_puente_devuelve_su_resultado_sin_copia_estructurada():
    for t in asyncio.run(mcp_servidor.mcp.list_tools()):
        assert t.outputSchema is None, t.name


def test_ver_pagina_da_la_pagina_entera_a_tamano_real_y_ya_no_ofrece_zoom(monkeypatch):
    # El zoom recortaba sin ampliar (media página con la misma resolución) y,
    # ampliado, no distinguió 0/O ni 1/l/I en el Mac simulado: se quitó.
    from PIL import Image as PILImage

    async def bajar(ruta):
        return PILImage.new("RGB", (1620, 952), "white")
    monkeypatch.setattr(mcp_servidor, "_bajar", bajar)
    _, img = asyncio.run(mcp_servidor.ver_pagina("l-1", 1))
    assert PILImage.open(io.BytesIO(img.data)).size == (1620, 952)
    esquema = next(t for t in asyncio.run(mcp_servidor.mcp.list_tools()) if t.name == "ver_pagina").inputSchema
    assert set(esquema["properties"]) == {"lectura", "n"}
