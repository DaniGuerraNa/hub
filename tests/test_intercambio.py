"""La carpeta de intercambio: lo que entra, lo que sale y lo que nunca.

Este módulo existe para no romper dos reglas —el hub no escribe dentro de otros
proyectos, y el navegador no lee contenido (decisión 203)—, así que la mitad de
estas pruebas son intentos de salirse de la carpeta. Un endpoint que recibe un
nombre de archivo desde un móvil es exactamente donde se prueba `../`.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from hub import db, intercambio, web


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(intercambio.config, "HUB_HOME", tmp_path)
    return tmp_path


@pytest.fixture
def cliente(tmp_path, monkeypatch):
    def conexion():
        con = db.conectar(tmp_path / "hub.db")
        db.inicializar(con)
        return con

    monkeypatch.setattr(web, "conexion", conexion)
    return TestClient(web.app)


# ─────────────────────────────── el dominio ────────────────────────────────


@pytest.mark.parametrize(
    "crudo, esperado",
    [
        ("../../.ssh/id_rsa", "id_rsa"),
        ("/etc/passwd", "passwd"),
        ("C:\\Users\\x\\nota.txt", "nota.txt"),
        ("Informe final (v2).pdf", "Informe-final-v2-.pdf"),
        (".env", "env"),          # nada oculto: aquí se ve lo que hay
        ("   ", "archivo"),
    ],
)
def test_el_nombre_no_puede_salirse_ni_esconderse(crudo, esperado):
    assert intercambio.nombre_seguro(crudo) == esperado


def test_subir_dos_veces_lo_mismo_no_pisa_lo_de_antes(home):
    """Lo de antes puede ser justo lo que el agente dejó para que te lo lleves."""
    primero = intercambio.guardar("foto.jpg", b"uno")
    segundo = intercambio.guardar("foto.jpg", b"dos")

    assert primero.name == "foto.jpg" and segundo.name == "foto-2.jpg"
    assert primero.read_bytes() == b"uno"


def test_un_archivo_vacio_o_demasiado_grande_no_entra(home, monkeypatch):
    with pytest.raises(ValueError):
        intercambio.guardar("x.bin", b"")

    monkeypatch.setattr(intercambio, "LIMITE", 4)
    with pytest.raises(ValueError) as exc:
        intercambio.guardar("x.bin", b"12345")
    assert "límite" in str(exc.value)


def test_resolver_no_alcanza_nada_de_fuera(home):
    """La base de datos del hub vive justo al lado, un nivel arriba."""
    (home / "hub.db").write_text("no")

    with pytest.raises(ValueError):
        intercambio.resolver("../hub.db")


# ──────────────────────────────── la pantalla ───────────────────────────────


def test_lo_que_sube_del_movil_aterriza_en_la_carpeta_del_hub(cliente, home):
    r = cliente.post("/intercambio/subir",
                     files={"archivo": ("nota.txt", b"hola", "text/plain")},
                     follow_redirects=False)

    assert r.status_code in (302, 303)
    assert (home / "intercambio/nota.txt").read_bytes() == b"hola"


def test_se_puede_bajar_lo_que_esta_en_la_carpeta(cliente, home):
    intercambio.guardar("informe.md", b"# listo")

    r = cliente.get("/intercambio/bajar/informe.md")

    assert r.status_code == 200
    assert r.content == b"# listo"
    assert "attachment" in r.headers.get("content-disposition", "")


def test_no_se_puede_bajar_nada_de_fuera_de_la_carpeta(cliente, home):
    """🔴 El intento que importa: la decisión 203 sigue en pie fuera de aquí.

    Los dos caminos: el `../` ni siquiera llega al manejador —la ruta deja de
    casar y son 404—, y el nombre pelado de un archivo que está fuera llega
    pero no encuentra nada, porque se busca **dentro** de la carpeta.
    """
    (home / "hub.db").write_bytes(b"secreto")

    por_arriba = cliente.get("/intercambio/bajar/..%2Fhub.db", follow_redirects=False)
    pelado = cliente.get("/intercambio/bajar/hub.db", follow_redirects=False)

    assert por_arriba.status_code != 200
    assert b"secreto" not in por_arriba.content
    assert pelado.status_code in (302, 303)   # vuelve con aviso
    assert b"secreto" not in pelado.content


def test_borrar_quita_el_archivo_y_nada_mas(cliente, home):
    intercambio.guardar("viejo.txt", b"x")

    cliente.post("/intercambio/borrar", data={"nombre": "viejo.txt"},
                 follow_redirects=False)

    assert intercambio.listar() == []


def test_la_ruta_se_escribe_en_el_panel_sin_enter(cliente, home, monkeypatch):
    """Sin Enter: la mitad que falta la pone una persona (regla dura 15)."""
    intercambio.guardar("captura.png", b"png")
    escrito = {}
    monkeypatch.setattr(web.entrega, "panel_apto", lambda pane_id: (True, ""))
    monkeypatch.setattr(web.tmux, "pegar_en_panel",
                        lambda pane_id, texto, enter=True: escrito.update(
                            {"pane": pane_id, "texto": texto, "enter": enter}))

    cliente.post("/intercambio/a-la-sesion",
                 data={"nombre": "captura.png", "pane_id": "%3"},
                 follow_redirects=False)

    assert escrito["enter"] is False
    assert escrito["texto"].endswith("/intercambio/captura.png")


def test_si_en_el_panel_ya_no_hay_un_agente_no_se_escribe(cliente, home, monkeypatch):
    """Se comprueba en el instante de escribir, no al pintar la lista."""
    intercambio.guardar("captura.png", b"png")
    monkeypatch.setattr(web.entrega, "panel_apto",
                        lambda pane_id: (False, "ahí hay una shell"))
    monkeypatch.setattr(web.tmux, "pegar_en_panel",
                        lambda *a, **k: pytest.fail("no debía escribir"))

    r = cliente.post("/intercambio/a-la-sesion",
                     data={"nombre": "captura.png", "pane_id": "%3"},
                     follow_redirects=False)

    assert "shell" in r.headers["location"]


# ─────────────────────────────── agrupar ────────────────────────────────────


def _dejar(home, relativa, datos=b"x"):
    destino = home / "intercambio" / relativa
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_bytes(datos)
    return destino


def test_lo_que_una_sesion_deja_en_una_subcarpeta_tambien_se_ve(home):
    """Hasta el 29-sep la landing que una sesión dejó como carpeta no salía."""
    _dejar(home, "tienda-landing-2026-09-25/index.html")

    nombres = [a["nombre"] for a in intercambio.listar()]

    assert nombres == ["tienda-landing-2026-09-25/index.html"]


def test_lo_de_una_subcarpeta_se_puede_bajar_pero_no_se_sale_por_ella(cliente, home):
    _dejar(home, "landing/index.html", b"<h1>hola</h1>")
    (home / "hub.db").write_bytes(b"secreto")

    dentro = cliente.get("/intercambio/bajar/landing/index.html")
    fuera = cliente.get("/intercambio/bajar/landing/../../hub.db", follow_redirects=False)

    assert dentro.content == b"<h1>hola</h1>"
    assert b"secreto" not in fuera.content
    with pytest.raises(ValueError):
        intercambio.resolver("landing/../../hub.db")


def test_un_enlace_que_apunta_fuera_ni_se_lista_ni_se_baja(home):
    (home / "hub.db").write_bytes(b"secreto")
    (home / "intercambio").mkdir(exist_ok=True)
    (home / "intercambio" / "trampa.db").symlink_to(home / "hub.db")

    assert intercambio.listar() == []
    with pytest.raises(ValueError):
        intercambio.resolver("trampa.db")


def test_por_tema_junta_lo_que_empieza_igual_y_lo_nombra_por_lo_comun(home):
    for n in ("feria-muestras-2026-09-29-01-impresos.jpg",
              "feria-muestras-2026-09-29-LEEME.md",
              "tienda-memo-precio-2026-09-25.md",
              "tienda-investigacion-mercado-2026-09-24.md",
              "tienda-landing-2026-09-25/index.html",
              "casa-planos.jpeg"):
        _dejar(home, n)

    grupos = {g["titulo"]: g["cuantos"]
              for g in intercambio.agrupar(intercambio.listar(), "tema")}

    assert grupos == {"feria muestras": 2, "tienda": 3, "casa planos": 1}


def test_por_tipo_y_por_fecha_los_grupos_dicen_lo_que_son(home):
    import os
    from datetime import datetime

    foto = _dejar(home, "foto.jpg")
    _dejar(home, "app.apk")
    vieja = _dejar(home, "nota.md")
    hace_un_mes = datetime(2026, 8, 20, 12).timestamp()
    os.utime(vieja, (hace_un_mes, hace_un_mes))
    hoy = datetime.fromtimestamp(foto.stat().st_mtime)
    archivos = intercambio.listar()

    por_tipo = {g["titulo"] for g in intercambio.agrupar(archivos, "tipo")}
    por_fecha = [g["titulo"] for g in intercambio.agrupar(archivos, "fecha", hoy)]

    assert por_tipo == {"Imágenes", "Apps", "Documentos"}
    assert por_fecha == ["Hoy", "Agosto 2026"]


def test_la_pantalla_agrupa_busca_y_abre_solo_el_grupo_mas_nuevo(cliente, home):
    _dejar(home, "tienda-memo.md")
    _dejar(home, "feria-foto.jpg")

    todo = cliente.get("/intercambio?por=tema").text
    buscado = cliente.get("/intercambio?q=tienda").text

    assert todo.count('class="tarjeta inter-grupo"') == 2
    assert todo.count(" open>") == 1
    assert "feria-foto.jpg" not in buscado
    assert "1 de 2" in buscado


def test_recientes_es_una_sola_lista_con_lo_ultimo_arriba_y_marcado(cliente, home):
    """Para ver lo que una sesión acaba de subir sin abrir carpetas."""
    import os
    import time

    viejo = _dejar(home, "tienda-memo.md")
    antes = time.time() - 3 * 86400
    os.utime(viejo, (antes, antes))
    _dejar(home, "feria-foto.jpg")

    grupos = intercambio.agrupar(intercambio.listar(), "recientes")
    pagina = cliente.get("/intercambio?por=recientes").text

    assert len(grupos) == 1
    assert [a["nombre"] for a in grupos[0]["archivos"]] == ["feria-foto.jpg", "tienda-memo.md"]
    assert pagina.count(">nuevo<") == 1


def test_dos_tandas_en_la_misma_hora_se_separan_y_solo_la_ultima_es_nueva(cliente, home):
    """Lo que pidió: dos bloques en la misma hora, y saber cuál acaba de llegar."""
    import os
    import time

    ahora = time.time()
    for n, hace in (("feria-muestras-01.jpg", 50 * 60), ("feria-muestras-02.jpg", 49 * 60),
                    ("feria-repertorio-01.jpg", 60), ("feria-repertorio-02.jpg", 30)):
        f = _dejar(home, n)
        os.utime(f, (ahora - hace, ahora - hace))

    (grupo,) = intercambio.agrupar(intercambio.listar(), "tema")
    pagina = cliente.get("/intercambio?por=tema").text

    assert [[a["nombre"] for a in t["archivos"]] for t in grupo["tandas"]] == [
        ["feria-repertorio-02.jpg", "feria-repertorio-01.jpg"],
        ["feria-muestras-02.jpg", "feria-muestras-01.jpg"],
    ]
    assert pagina.count('class="inter-tanda"') == 2
    assert pagina.count(">nuevo<") == 2
    assert pagina.index("feria-repertorio-02.jpg") < pagina.index("feria-muestras-02.jpg")
