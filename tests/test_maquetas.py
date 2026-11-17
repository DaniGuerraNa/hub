"""Las maquetas se ven en el hub, aisladas y sin salirse de su carpeta (C-0249).

🔴 Como los de `test_acceso.py`, estos tests miran sobre todo lo que tiene que
**fallar**: un HTML con scripts servido en el origen del hub sería un XSS con
una shell detrás, así que lo que se prueba es que la página llega encerrada en
su `sandbox`, que no se sale de la carpeta por ningún camino y que la puerta de
acceso la cierra igual que cierra todo lo demás.
"""

from __future__ import annotations

import os

import pytest
import yaml
from fastapi.testclient import TestClient
from starlette.routing import Route

from hub import acceso, intercambio, maquetas, web

FUERA = "desktop.tail1a2b3c.ts.net"

# Escrita aquí entera y no leída del módulo: si alguien la relaja en el código,
# este test tiene que ponerse en rojo, no darle la razón.
CSP = ("sandbox allow-scripts; default-src 'none'; style-src 'unsafe-inline'; "
       "script-src 'unsafe-inline'; img-src data:; font-src data:; base-uri 'none'; "
       "form-action 'none'; frame-ancestors 'none'")


@pytest.fixture
def raiz(tmp_path, monkeypatch):
    """Una carpeta de maquetas aparte, con algo fuera de ella que no debe verse."""
    carpeta = tmp_path / "maquetas"
    (carpeta / "ux").mkdir(parents=True)
    (carpeta / "index.html").write_text("<h1>Índice de maquetas</h1>", encoding="utf-8")
    (carpeta / "ux" / "index.html").write_text("<h1>Dirección UX</h1>", encoding="utf-8")
    (tmp_path / "fuera.html").write_text("<p>SECRETO-DE-FUERA</p>", encoding="utf-8")
    (tmp_path / "fuera.css").write_text("body{color:red} /* SECRETO-DE-FUERA */", encoding="utf-8")
    monkeypatch.setenv("HUB_MAQUETAS", str(carpeta))
    return carpeta


@pytest.fixture
def cliente():
    return TestClient(web.app)


# ── Lo que se sirve, y cómo ──────────────────────────────────────────────────

def test_sirve_un_html_de_la_raiz_con_su_csp_sandbox_y_nosniff(raiz, cliente):
    r = cliente.get("/maquetas/index.html")
    assert r.status_code == 200
    assert "Índice de maquetas" in r.text
    assert r.headers["content-type"].startswith("text/html")
    assert r.headers["content-security-policy"] == CSP
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["referrer-policy"] == "no-referrer"
    assert r.headers["cache-control"] == "no-cache"


def test_la_raiz_con_barra_sirve_su_index(raiz, cliente):
    r = cliente.get("/maquetas/")
    assert r.status_code == 200 and "Índice de maquetas" in r.text
    assert r.headers["content-security-policy"] == CSP


def test_la_csp_no_lleva_allow_same_origin_ni_allow_forms_ni_allow_popups():
    """`allow-same-origin` le devolvería el origen del hub —y con él la terminal—;
    `allow-forms` y `allow-popups`, mandar o abrir cosas en su nombre."""
    politica = maquetas.CABECERAS["Content-Security-Policy"]
    assert politica == CSP
    for permiso in ("allow-same-origin", "allow-forms", "allow-popups", "allow-top-navigation"):
        assert permiso not in politica
    assert politica.startswith("sandbox allow-scripts;")


# ── Lo que no se sale de la carpeta ──────────────────────────────────────────

@pytest.mark.parametrize("ruta", ["../fuera.html", "ux/../../fuera.html", "./../fuera.html", ".."])
def test_no_sale_de_la_raiz_con_puntos(raiz, ruta):
    with pytest.raises(ValueError):
        maquetas.resolver(ruta)


def test_no_sale_de_la_raiz_con_ruta_absoluta(raiz, tmp_path):
    with pytest.raises(ValueError):
        maquetas.resolver(str(tmp_path / "fuera.html"))
    # Ni siquiera una absoluta que cae dentro: la ruta es siempre relativa.
    with pytest.raises(ValueError):
        maquetas.resolver(str(raiz / "index.html"))


@pytest.mark.parametrize("camino", [
    "/maquetas/%2e%2e/fuera.html",
    "/maquetas/ux/%2e%2e/%2e%2e/fuera.html",
    "/maquetas/..%2ffuera.html",
    "/maquetas/%2Ftmp%2Ffuera.html",
])
def test_por_http_tampoco_sale_de_la_raiz(raiz, cliente, camino):
    r = cliente.get(camino, follow_redirects=False)
    assert r.status_code == 404
    assert "SECRETO-DE-FUERA" not in r.text
    assert r.headers["content-type"].startswith("text/plain")


def test_un_enlace_simbolico_que_apunta_fuera_no_se_sirve_ni_se_incrusta(raiz, tmp_path, cliente):
    os.symlink(tmp_path / "fuera.html", raiz / "enlace.html")
    os.symlink(tmp_path / "fuera.css", raiz / "enlace.css")
    os.symlink(tmp_path, raiz / "carpeta-de-fuera")
    (raiz / "pide.html").write_text(
        '<link rel="stylesheet" href="enlace.css"><p>pide</p>', encoding="utf-8")

    assert cliente.get("/maquetas/enlace.html").status_code == 404
    assert cliente.get("/maquetas/carpeta-de-fuera/fuera.html").status_code == 404
    r = cliente.get("/maquetas/pide.html")
    assert r.status_code == 200
    assert "SECRETO-DE-FUERA" not in r.text
    assert '<link rel="stylesheet" href="enlace.css">' in r.text, "debía quedar sin incrustar"


@pytest.mark.parametrize("nombre", ["estilo.css", "guion.js", "dibujo.svg", "programa.py", "LEEME.md"])
def test_solo_sirve_html(raiz, cliente, nombre):
    (raiz / nombre).write_text("<script>alert(1)</script>", encoding="utf-8")
    r = cliente.get(f"/maquetas/{nombre}")
    assert r.status_code == 404
    assert "alert(1)" not in r.text


def test_lo_que_no_existe_da_404_en_texto_plano(raiz, cliente):
    r = cliente.get("/maquetas/no-esta.html")
    assert r.status_code == 404 and r.headers["content-type"].startswith("text/plain")


def test_un_fallo_del_sistema_da_404_sin_ensenar_la_ruta_del_disco(raiz, cliente):
    """Un nombre demasiado largo es un `OSError` cuyo mensaje lleva la ruta
    absoluta de la carpeta: medido, salía entero en el 404."""
    r = cliente.get("/maquetas/" + "x" * 5000 + ".html")
    assert r.status_code == 404
    assert str(raiz) not in r.text and "Errno" not in r.text


def test_una_hoja_con_un_nombre_imposible_se_deja_sin_reventar_la_pagina(raiz):
    pagina = f'<link rel="stylesheet" href="{"x" * 5000}.css"><p>sigue</p>'
    (raiz / "larga.html").write_text(pagina, encoding="utf-8")
    assert maquetas.pagina("larga.html") == pagina


def test_sin_carpeta_de_maquetas_responde_404(tmp_path, monkeypatch, cliente):
    """El caso del producto: `maquetas/` no viaja, y la ruta existe igual."""
    monkeypatch.setenv("HUB_MAQUETAS", str(tmp_path / "no-existe"))
    for camino in ("/maquetas/", "/maquetas/index.html", "/maquetas/ux"):
        r = cliente.get(camino, follow_redirects=False)
        assert r.status_code == 404, camino


def test_sin_variable_la_raiz_es_la_carpeta_maquetas_del_repo(monkeypatch):
    from hub import config
    monkeypatch.delenv("HUB_MAQUETAS", raising=False)
    assert maquetas.raiz() == config.RAIZ_REPO / "maquetas"


# ── Las carpetas ─────────────────────────────────────────────────────────────

def test_una_carpeta_sin_barra_redirige_a_la_barra_y_sirve_su_index(raiz, cliente):
    """Sin la barra, el navegador resolvería los enlaces relativos de su
    `index.html` contra la carpeta de arriba y todos darían 404."""
    r = cliente.get("/maquetas/ux", follow_redirects=False)
    assert r.status_code == 307
    assert r.headers["location"] == "/maquetas/ux/"
    r = cliente.get("/maquetas/ux/")
    assert r.status_code == 200 and "Dirección UX" in r.text
    assert r.headers["content-security-policy"] == CSP


def test_maquetas_a_secas_redirige_a_la_raiz_con_un_camino_relativo(raiz, cliente):
    """Relativo a propósito: detrás de `tailscale serve` el hub ve `http`, y una
    redirección absoluta mandaría al teléfono a un `http://` que no se sirve."""
    r = cliente.get("/maquetas", follow_redirects=False)
    assert r.status_code == 307 and r.headers["location"] == "/maquetas/"


def test_una_carpeta_con_espacios_redirige_escapada(raiz, cliente):
    (raiz / "dos palabras").mkdir()
    (raiz / "dos palabras" / "index.html").write_text("<p>dos</p>", encoding="utf-8")
    r = cliente.get("/maquetas/dos%20palabras", follow_redirects=False)
    assert r.headers["location"] == "/maquetas/dos%20palabras/"


def test_una_carpeta_sin_index_da_404(raiz, cliente):
    (raiz / "vacia").mkdir()
    assert cliente.get("/maquetas/vacia/").status_code == 404


# ── Lo que se incrusta ───────────────────────────────────────────────────────

def test_incrusta_la_hoja_y_el_guion_relativos_tambien_con_dos_puntos(raiz):
    (raiz / "comun.css").write_text("body{color:COMUN}", encoding="utf-8")
    (raiz / "vendor").mkdir()
    (raiz / "vendor" / "lib.js").write_text("var LIB = 1;", encoding="utf-8")
    (raiz / "ux" / "propio.css").write_text(".propio{color:PROPIO}", encoding="utf-8")
    (raiz / "ux" / "pantalla.html").write_text(
        '<html><head>\n'
        '<link rel="stylesheet" href="../comun.css">\n'
        "<link href='propio.css' rel='stylesheet' media='screen'>\n"
        '<script src="../vendor/lib.js"></script>\n'
        '</head><body><p>hola</p></body></html>', encoding="utf-8")

    html = maquetas.pagina("ux/pantalla.html")

    assert "<style>body{color:COMUN}</style>" in html
    assert '<style media="screen">.propio{color:PROPIO}</style>' in html
    assert "<script>var LIB = 1;</script>" in html
    assert "<link" not in html and "src=" not in html
    assert "<p>hola</p>" in html


def test_deja_intacto_lo_que_no_es_local(raiz):
    pagina = (
        '<link rel="stylesheet" href="https://cdn.example/x.css">\n'
        '<link rel="stylesheet" href="//cdn.example/y.css">\n'
        '<link rel="stylesheet" href="data:text/css,body{}">\n'
        '<link rel="stylesheet" href="/static/hub.css">\n'
        '<link rel="icon" href="icono.css">\n'
        '<script src="http://cdn.example/z.js"></script>\n'
        '<script src="data:text/javascript,1"></script>\n'
        '<script src="no-existe.js"></script>\n'
        '<script>var enLinea = 1;</script>\n')
    (raiz / "icono.css").write_text("NO-SE-INCRUSTA", encoding="utf-8")
    (raiz / "externa.html").write_text(pagina, encoding="utf-8")

    assert maquetas.pagina("externa.html") == pagina


def test_solo_incrusta_hojas_css_y_guiones_js(raiz):
    """Un `<script src>` que apunte a otra cosa de la carpeta (un `.html`, un
    `.py`) no la vuelca dentro de la página."""
    (raiz / "datos.py").write_text("CLAVE = 'NO-SE-INCRUSTA'", encoding="utf-8")
    (raiz / "rara.html").write_text(
        '<script src="datos.py"></script><link rel="stylesheet" href="index.html">',
        encoding="utf-8")
    html = maquetas.pagina("rara.html")
    assert "NO-SE-INCRUSTA" not in html and "Índice de maquetas" not in html


def test_un_cierre_de_script_dentro_del_guion_no_cierra_la_etiqueta(raiz):
    (raiz / "trampa.js").write_text(
        'var a = "</script><p>FUERA</p>"; var b = "</SCRIPT >";', encoding="utf-8")
    (raiz / "trampa.css").write_text('p::after{content:"</style><b>FUERA</b>"}', encoding="utf-8")
    (raiz / "trampa.html").write_text(
        '<link rel="stylesheet" href="trampa.css"><script src="trampa.js"></script><p>fin</p>',
        encoding="utf-8")

    html = maquetas.pagina("trampa.html")

    assert html.lower().count("</script") == 1, html
    assert html.lower().count("</style") == 1, html
    assert html.endswith("</script><p>fin</p>")
    assert r'var a = "<\/script><p>FUERA</p>"' in html


def test_un_comentario_dentro_del_guion_no_se_traga_el_resto_de_la_pagina(raiz):
    """`<!--` seguido de `<script` deja al analizador en un estado en el que el
    `</script>` de cierre ya no cierra: el resto de la página sería guion."""
    (raiz / "plantilla.js").write_text('var t = "<!-- <script>";', encoding="utf-8")
    (raiz / "plantilla.html").write_text('<script src="plantilla.js"></script><p>fin</p>',
                                         encoding="utf-8")
    html = maquetas.pagina("plantilla.html")
    assert "<!--" not in html
    assert html.endswith("</script><p>fin</p>")


def test_no_toca_lo_que_hay_dentro_de_un_guion_en_linea_ni_de_un_comentario(raiz):
    (raiz / "comun.css").write_text("body{}", encoding="utf-8")
    pagina = ('<script>var t = \'<link rel="stylesheet" href="comun.css">\';</script>\n'
              '<!-- <link rel="stylesheet" href="comun.css"> -->\n')
    (raiz / "plantilla.html").write_text(pagina, encoding="utf-8")
    assert maquetas.pagina("plantilla.html") == pagina


def test_un_guion_conserva_su_tipo_al_incrustarse(raiz):
    (raiz / "modulo.js").write_text("export const x = 1;", encoding="utf-8")
    (raiz / "mod.html").write_text(
        '<script type="module" src="modulo.js" integrity="sha384-x" crossorigin></script>',
        encoding="utf-8")
    assert maquetas.pagina("mod.html") == '<script type="module">export const x = 1;</script>'


# ── Lo que no existe y la puerta ─────────────────────────────────────────────

def test_no_existe_post_en_maquetas(raiz, cliente):
    rutas = [r for r in web.app.routes if isinstance(r, Route) and r.path.startswith("/maquetas")]
    assert rutas, "no hay ruta de maquetas"
    assert all(r.methods <= {"GET", "HEAD"} for r in rutas), [(r.path, r.methods) for r in rutas]
    assert cliente.post("/maquetas/index.html").status_code == 405


@pytest.fixture
def de_fuera(raiz):
    ruta = acceso.archivo()
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(yaml.safe_dump({"hosts": [FUERA]}), encoding="utf-8")
    return TestClient(web.app, base_url=f"https://{FUERA}")


def test_desde_un_nombre_de_fuera_sin_aparato_dado_de_alta_no_se_sirve(de_fuera):
    for camino in ("/maquetas/", "/maquetas/index.html", "/maquetas/ux"):
        r = de_fuera.get(camino, follow_redirects=False)
        assert r.status_code == 403, camino
        assert "no está dado de alta" in r.text
        assert "Índice de maquetas" not in r.text


def test_desde_fuera_con_aparato_dado_de_alta_se_ve(de_fuera):
    """Es para lo que existe: abrirlas en el teléfono por la puerta de siempre."""
    codigo = acceso.alta_pendiente("Teléfono")
    alta = de_fuera.get(f"/acceso/alta/{codigo}", follow_redirects=False)
    de_fuera.cookies.set(acceso.COOKIE, alta.cookies.get(acceso.COOKIE))
    r = de_fuera.get("/maquetas/index.html")
    assert r.status_code == 200 and "Índice de maquetas" in r.text
    assert r.headers["content-security-policy"] == CSP


def test_intercambio_ver_sigue_negando_html(cliente):
    """Las maquetas tienen su ruta, con su `sandbox`: el visor de imágenes no
    se vuelve otra forma de servir HTML en línea."""
    (intercambio.carpeta() / "pagina.html").write_text("<script>alert(1)</script>",
                                                       encoding="utf-8")
    r = cliente.get("/intercambio/ver/pagina.html")
    assert r.status_code == 415
    assert "alert(1)" not in r.text


def test_un_byte_nulo_en_la_ruta_es_un_error_dicho_en_espanol(tmp_path, monkeypatch):
    (tmp_path / "index.html").write_text("<p>hola</p>", encoding="utf-8")
    monkeypatch.setenv("HUB_MAQUETAS", str(tmp_path))
    from hub import maquetas
    with pytest.raises(ValueError) as exc:
        maquetas.resolver("ux\x00")
    assert "null" not in str(exc.value)
