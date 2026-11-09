"""La bandeja de ideas del dueño (decisión 342, C-0146).

Lo que se fija: una idea se apunta por una sola puerta (`ideas.apuntar`) venga
de la pantalla, del secretario o de la terminal; no se pierde ni se pisa; y la
ficha nace al tomarla, no antes.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from hub import config, db, ideas, web

RAIZ = Path(__file__).resolve().parents[1]

# El guion de las fichas es del flujo de desarrollo y no viaja con el producto
# (`publicacion.EXCLUIDOS`): allí estas dos pruebas no tienen qué probar.
_SIN_GUION_DE_CAMBIOS = pytest.mark.skipif(not (RAIZ / "scripts" / "cambios.py").is_file(),
                                           reason="scripts/cambios.py no viaja con el producto")


@pytest.fixture
def con():
    c = db.conectar(config.DB_PATH)
    db.inicializar(c)
    yield c
    c.close()


def test_se_apunta_se_lista_en_orden_y_se_toma(con):
    a = ideas.apuntar(con, "  que el respaldo   diga cuándo fue el último push ", "con la fecha", origen="web")
    b = ideas.apuntar(con, "segunda", origen="cli")
    assert [i["id"] for i in ideas.listar(con)] == [a, b], "se toman de la más antigua a la más nueva"
    assert ideas.ver(con, a)["texto"] == "que el respaldo diga cuándo fue el último push"
    ideas.tomar(con, a, "C-0999")
    assert [i["id"] for i in ideas.listar(con)] == [b]
    assert ideas.listar(con, "tomada")[0]["ref"] == "C-0999"
    with pytest.raises(ValueError, match="ya está tomada"):
        ideas.descartar(con, a, "da igual")


@pytest.mark.parametrize("texto", ["", "   ", "x" * 301])
def test_una_idea_vacia_o_que_no_cabe_en_una_linea_no_se_apunta(con, texto):
    with pytest.raises(ValueError):
        ideas.apuntar(con, texto)


def test_tomar_sin_decir_donde_sigue_y_descartar_sin_motivo_no_valen(con):
    i = ideas.apuntar(con, "algo")
    with pytest.raises(ValueError):
        ideas.tomar(con, i, " ")
    with pytest.raises(ValueError):
        ideas.descartar(con, i, "")
    assert ideas.ver(con, i)["estado"] == "nueva"


def test_un_proyecto_que_no_esta_en_el_registro_no_se_acepta(con):
    with pytest.raises(ValueError, match="no hay ningún proyecto"):
        ideas.apuntar(con, "algo", proyecto="no-existe-este")


# ── la pantalla ──────────────────────────────────────────────────────────────

def test_desde_el_tablero_se_apunta_y_se_ve(con):
    cliente = TestClient(web.app)
    r = cliente.post("/tablero/idea", data={"texto": "botón para copiar la ruta", "detalle": "en Archivos"},
                     follow_redirects=False)
    assert r.status_code == 303 and "Apuntada" in r.headers["location"]
    pagina = cliente.get("/tablero")
    assert pagina.status_code == 200
    assert "botón para copiar la ruta" in pagina.text and "en Archivos" in pagina.text


def test_un_error_al_apuntar_se_dice_en_la_pantalla(con):
    r = TestClient(web.app).post("/tablero/idea", data={"texto": "  "}, follow_redirects=False)
    assert r.status_code == 303 and "aviso=" in r.headers["location"] and "fugaz" not in r.headers["location"]


def test_descartar_desde_el_tablero_la_deja_a_la_vista_con_su_motivo(con):
    i = ideas.apuntar(con, "idea floja")
    con.commit()
    cliente = TestClient(web.app)
    cliente.post(f"/tablero/idea/{i}/descartar", data={"motivo": "ya existe en Archivos"})
    texto = cliente.get("/tablero").text
    assert "descartada: ya existe en Archivos" in texto


def test_el_menu_lleva_al_tablero(con):
    assert 'href="/tablero"' in TestClient(web.app).get("/").text


# ── el secretario, por la misma puerta ───────────────────────────────────────

def test_el_secretario_apunta_por_la_misma_puerta(con):
    from hub.secretario import memoria, piezas
    accion = piezas.acciones()["apuntar_idea"]
    m = memoria.conectar()
    try:
        r = accion.ejecutar(m, {"texto": "que el resumen del día diga el tiempo"})
    finally:
        m.close()
    assert "apuntada en el tablero" in r
    (i,) = ideas.listar(con)
    assert i["origen"] == "secretario" and i["texto"] == "que el resumen del día diga el tiempo"


# ── la ficha nace al tomarla ─────────────────────────────────────────────────

@_SIN_GUION_DE_CAMBIOS
def test_cambios_nueva_con_idea_crea_la_ficha_y_la_toma(con, tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("cambios_guion", RAIZ / "scripts" / "cambios.py")
    cambios = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cambios)
    monkeypatch.setattr(cambios, "CARPETA", tmp_path)
    monkeypatch.setattr(cambios, "RAIZ", tmp_path.parent)
    i = ideas.apuntar(con, "un botón de pausa", "en Trabajo")
    con.commit()
    monkeypatch.setattr(sys, "argv", ["cambios.py", "nueva", "Pausa en Trabajo", "--tipo", "mejora",
                                      "--tamano", "S", "--idea", str(i)])
    assert cambios.main() == 0
    (ficha,) = tmp_path.glob("C-*.md")
    assert "Del tablero (idea #" in ficha.read_text(encoding="utf-8") and "un botón de pausa" in ficha.read_text()
    assert ideas.ver(con, i)["estado"] == "tomada" and ideas.ver(con, i)["ref"] == ficha.name[:6]
    monkeypatch.setattr(sys, "argv", ["cambios.py", "nueva", "Otra vez", "--tipo", "mejora",
                                      "--tamano", "S", "--idea", str(i)])
    assert cambios.main() == 2, "una idea ya tomada no se toma dos veces"


# ── adjuntos y dictado (C-0149) ──────────────────────────────────────────────

PNG = bytes.fromhex("89504e470d0a1a0a0000000d4948445200000001000000010806000000"
                    "1f15c4890000000d49444154789c6360000000020001e221bc330000000049454e44ae426082")


def test_una_idea_lleva_adjuntos_y_se_ven_en_el_tablero(con):
    cliente = TestClient(web.app)
    r = cliente.post("/tablero/idea", data={"texto": "con captura"},
                     files=[("archivos", ("image.png", PNG, "image/png")),
                            ("archivos", ("notas.txt", b"hola", "text/plain"))], follow_redirects=False)
    assert "Apuntada" in r.headers["location"]
    (i,) = ideas.listar(con)
    nombres = sorted(a["archivo"] for a in ideas.adjuntos(i["id"]))
    assert nombres[0].startswith("notas") and nombres[1].startswith("pegado-"), "una captura pegada lleva la hora"
    pagina = cliente.get("/tablero").text
    imagen = next(a for a in ideas.adjuntos(i["id"]) if a["imagen"])
    assert f'/intercambio/ver/{imagen["nombre"]}' in pagina
    ver = cliente.get(f'/intercambio/ver/{imagen["nombre"]}')
    assert ver.status_code == 200 and ver.headers["content-type"] == "image/png"
    assert ver.headers["x-content-type-options"] == "nosniff" and "sandbox" in ver.headers["content-security-policy"]


def test_en_linea_solo_se_sirven_imagenes_y_nunca_fuera_de_la_carpeta(con):
    from hub import intercambio
    intercambio.guardar("truco.svg", b"<svg onload=alert(1)>", dentro="_tablero/1")
    intercambio.guardar("pagina.html", b"<script>x</script>", dentro="_tablero/1")
    cliente = TestClient(web.app)
    assert cliente.get("/intercambio/ver/_tablero/1/truco.svg").status_code == 415
    assert cliente.get("/intercambio/ver/_tablero/1/pagina.html").status_code == 415
    # `%2e%2e` y no `..`: el cliente normaliza `..` y la petición ni llegaba
    # a la ruta (revisor de C-0149).
    r = cliente.get("/intercambio/ver/_tablero/%2e%2e/%2e%2e/hub.db")
    assert r.status_code == 404


def test_adjuntar_tiene_tope_y_solo_mientras_la_idea_espera(con, monkeypatch):
    i = ideas.apuntar(con, "idea")
    monkeypatch.setattr(ideas, "MAX_ADJUNTOS", 2)
    ideas.adjuntar(con, i, "a.txt", b"1")
    ideas.adjuntar(con, i, "b.txt", b"2")
    with pytest.raises(ValueError, match="hasta 2"):
        ideas.adjuntar(con, i, "c.txt", b"3")
    ideas.tomar(con, i, "C-0999")
    monkeypatch.setattr(ideas, "MAX_ADJUNTOS", 10)
    with pytest.raises(ValueError, match="mientras espera"):
        ideas.adjuntar(con, i, "d.txt", b"4")
    with pytest.raises(ValueError, match="vacío"):
        ideas.adjuntar(con, ideas.apuntar(con, "otra"), "e.txt", b"")


@_SIN_GUION_DE_CAMBIOS
def test_al_tomar_la_idea_la_ficha_cita_sus_adjuntos(con, tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("cambios_guion2", RAIZ / "scripts" / "cambios.py")
    cambios = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cambios)
    monkeypatch.setattr(cambios, "CARPETA", tmp_path)
    monkeypatch.setattr(cambios, "RAIZ", tmp_path.parent)
    i = ideas.apuntar(con, "con adjunto")
    ruta = ideas.adjuntar(con, i, "boceto.png", PNG)
    con.commit()
    monkeypatch.setattr(sys, "argv", ["cambios.py", "nueva", "X", "--tipo", "mejora", "--tamano", "S",
                                      "--idea", str(i)])
    assert cambios.main() == 0
    (ficha,) = tmp_path.glob("C-*.md")
    assert f"`{ruta}`" in ficha.read_text(encoding="utf-8")


def test_el_tablero_trae_el_boton_de_dictar_contra_api_voz(con):
    texto = TestClient(web.app).get("/tablero").text
    assert 'data-grabar="detalle-idea"' in texto and 'data-grabar-url="/api/voz"' in texto
    assert '/static/grabar.js' in texto


def test_lo_que_no_va_a_entrar_no_se_lee(con, monkeypatch):
    """Con el tope lleno, el archivo de más se rechaza sin leerlo a memoria."""
    monkeypatch.setattr(ideas, "MAX_ADJUNTOS", 1)
    r = TestClient(web.app).post("/tablero/idea", data={"texto": "dos adjuntos"},
                                 files=[("archivos", ("a.txt", b"1", "text/plain")),
                                        ("archivos", ("b.txt", b"2", "text/plain"))], follow_redirects=False)
    from urllib.parse import unquote
    aviso = unquote(r.headers["location"])
    assert "no entró: b.txt" in aviso and "hasta 1" in aviso
    (i,) = ideas.listar(con)
    assert [a["archivo"] for a in ideas.adjuntos(i["id"])] == ["a.txt"]
