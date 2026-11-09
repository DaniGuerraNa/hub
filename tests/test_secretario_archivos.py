"""Los archivos de sus proyectos, en sólo lectura (decisión 336)."""

import pytest

from hub.secretario import archivos, conversacion, herramientas, memoria


@pytest.fixture
def proyecto(tmp_path, monkeypatch):
    raiz = tmp_path / "Mis-Cosas" / "ws"
    (raiz / "hu-knowledge" / "traces" / "migracion-stream").mkdir(parents=True)
    (raiz / "hu-knowledge" / "traces" / "migracion-stream" / "plan-actividades.md").write_text(
        "# Plan\n\n- Sprint 1: revisar HLS (8 h)\n- Sprint 2: validar 80% visto (5 h)\n")
    (raiz / "interno" / "secrets").mkdir(parents=True)
    (raiz / "interno" / "secrets" / "llaves.txt").write_text("nada")
    (raiz / ".env").write_text("TOKEN=abc")
    (raiz / "application-prod.yml").write_text("clave: x")
    (raiz / "node_modules").mkdir()
    (tmp_path / "fuera.txt").write_text("fuera")
    monkeypatch.setattr(archivos, "raices", lambda: {"ws": raiz})
    return raiz


def test_lee_el_plan_por_la_ruta_relativa_o_la_de_windows_que_dicta(proyecto, monkeypatch):
    r = archivos.leer("ws", "hu-knowledge/traces/migracion-stream/plan-actividades.md")
    assert "Sprint 1: revisar HLS" in r["texto"] and r["lineas"] == 4
    monkeypatch.setattr(archivos, "raices", lambda: {"ws": proyecto})
    absoluta = str(proyecto / "hu-knowledge" / "traces" / "migracion-stream" / "plan-actividades.md")
    assert "Sprint 2" in archivos.leer("ws", absoluta)["texto"]


@pytest.mark.parametrize("ruta", ["../../fuera.txt", "/etc/passwd", ".env", "application-prod.yml",
                                  "interno/secrets/llaves.txt", "interno/secrets"])
def test_no_sale_del_proyecto_ni_abre_llaves(proyecto, ruta):
    with pytest.raises(archivos.FueraDeAlcance):
        archivos.leer("ws", ruta) if "." in ruta.rsplit("/", 1)[-1] else archivos.listar("ws", ruta)


def test_listar_y_lo_reciente_no_ensenan_llaves_ni_carpetas_pesadas(proyecto):
    nombres = {e["ruta"] for e in archivos.listar("ws")["entradas"]}
    assert nombres == {"hu-knowledge", "interno", "application-prod.yml"} - {"application-prod.yml"}
    rec = [a["ruta"] for a in archivos.recientes("ws")["archivos"]]
    assert rec == ["hu-knowledge/traces/migracion-stream/plan-actividades.md"]


def test_busca_por_nombre_y_por_contenido(proyecto):
    b = archivos.buscar("ws", "hls")
    assert b["por_contenido"][0]["ruta"].endswith("plan-actividades.md") and b["por_contenido"][0]["linea"] == 3
    assert [x["ruta"] for x in archivos.buscar("ws", "migracion")["por_nombre"]] == ["hu-knowledge/traces/migracion-stream"]


def test_lo_que_lee_pasa_por_el_filtro_de_secretos(proyecto):
    (proyecto / "notas.md").write_text("la llave es sk-ant-api03-" + "x" * 40)
    assert "sk-ant-api03" not in archivos.leer("ws", "notas.md")["texto"]


def test_como_herramienta_un_error_se_le_dice_al_modelo(proyecto):
    con = memoria.conectar()
    r = herramientas.todas()["leer_archivo"].funcion(con, {"proyecto": "ws", "ruta": "../../fuera.txt"})
    assert "fuera del proyecto" in r["error"]
    r = herramientas.todas()["leer_archivo"].funcion(con, {"proyecto": "otro", "ruta": "x"})
    assert "ws" in r["error"]


def test_el_contexto_de_su_entorno_va_al_final_del_prompt():
    (memoria.carpeta() / "secretario.yml").write_text("dueno: Leo\ncontexto: |\n  Mi trabajo vive en ws.\n")
    s = conversacion.sistema()
    assert s.startswith("Eres el secretario personal de Leo") and s.endswith("Mi trabajo vive en ws.")
