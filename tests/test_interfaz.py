"""El interruptor de la interfaz nueva y su marco (C-0169).

Lo que se protege: que la interfaz nueva sólo se sirva al aparato que la
encendió —una cookie con una lista cerrada—, que se pueda apagar siempre y sin
JavaScript, y que el marco nuevo conserve el contrato de DOM del que dependen
las pantallas, que no se han tocado.

Que sin encenderla nada cambie, traiga el aparato la cookie que traiga, se
mide aparte (`test_clasica_identica.py`).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from hub import db, interfaz, navegacion, web
from hub.secretario import memoria

pytestmark = pytest.mark.skipif(not interfaz.disponible(),
                                reason="esta instalación no trae la interfaz nueva")

NUEVA = Path(web.__file__).parent / "templates" / "nueva" / "base.html"


@pytest.fixture
def cliente(tmp_path, monkeypatch):
    def conexion():
        c = db.conectar(tmp_path / "hub.db")
        db.inicializar(c)
        return c

    monkeypatch.setattr(web, "conexion", conexion)
    return TestClient(web.app), conexion


def _con_la_nueva(http: TestClient) -> TestClient:
    http.cookies.set(interfaz.COOKIE, interfaz.NUEVA)
    return http


def _secretario_en_todo_el_hub(nombre: str = "") -> None:
    con = memoria.conectar()
    try:
        if nombre:
            from hub.secretario import personaje
            memoria.poner(con, personaje.CLAVE_NOMBRE, nombre)
            con.commit()
    finally:
        con.close()
    (memoria.carpeta() / "secretario.yml").write_text("en_todo_el_hub: true\n", encoding="utf-8")


# ── qué interfaz toca ────────────────────────────────────────────────────────

def test_sin_cookie_o_con_una_que_no_se_conoce_toca_la_de_siempre():
    assert interfaz.elegida({}) == interfaz.CLASICA
    assert interfaz.elegida(None) == interfaz.CLASICA
    assert interfaz.elegida({interfaz.COOKIE: "otra"}) == interfaz.CLASICA
    assert interfaz.elegida({interfaz.COOKIE: ""}) == interfaz.CLASICA
    assert interfaz.elegida({interfaz.COOKIE: interfaz.CLASICA}) == interfaz.CLASICA
    assert interfaz.elegida({interfaz.COOKIE: interfaz.NUEVA}) == interfaz.NUEVA


def test_donde_no_estan_sus_plantillas_la_cookie_no_se_obedece(monkeypatch):
    monkeypatch.setattr(interfaz, "disponible", lambda: False)
    assert interfaz.elegida({interfaz.COOKIE: interfaz.NUEVA}) == interfaz.CLASICA


def test_la_pagina_solo_es_la_nueva_para_el_aparato_que_trae_su_cookie(cliente):
    http, _ = cliente
    assert 'data-interfaz="nueva"' not in http.get("/").text
    http.cookies.set(interfaz.COOKIE, "otra")
    assert 'data-interfaz="nueva"' not in http.get("/").text
    assert 'data-interfaz="nueva"' in _con_la_nueva(http).get("/").text


def test_el_entorno_de_siempre_sigue_siendo_el_que_usan_los_tests():
    assert web.plantillas is web._PLANTILLAS[interfaz.CLASICA]
    assert set(web._PLANTILLAS) == set(interfaz.INTERFACES)
    # La base nueva hereda de la de siempre; las pantallas no se copian.
    assert [p.name for p in NUEVA.parent.rglob("*.html")] == ["base.html"]
    assert NUEVA.read_text(encoding="utf-8").startswith('{% extends "@clasica/base.html" %}')


# ── encender y apagar ────────────────────────────────────────────────────────

def test_encenderla_deja_la_cookie_en_este_aparato_y_vuelve_a_una_pantalla_del_hub(cliente):
    http, _ = cliente
    r = http.post("/interfaz", data={"interfaz": "nueva", "destino": "/"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/?aviso=")
    galleta = r.headers["set-cookie"]
    assert galleta.startswith(f"{interfaz.COOKIE}=nueva;")
    assert "SameSite=lax" in galleta and "HttpOnly" in galleta and "Path=/" in galleta
    assert "Max-Age=" in galleta and "Secure" not in galleta   # se entró por http
    assert 'data-interfaz="nueva"' in http.get("/").text


def test_por_https_la_cookie_va_marcada_como_segura(cliente):
    http, _ = cliente
    r = http.post("/interfaz", data={"interfaz": "nueva"}, headers={"x-forwarded-proto": "https"},
                  follow_redirects=False)
    assert "Secure" in r.headers["set-cookie"]


def test_volver_a_la_de_siempre_borra_la_cookie(cliente):
    http, _ = cliente
    _con_la_nueva(http)
    r = http.post("/interfaz", data={"interfaz": "clasica", "destino": "/guia#interfaz"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].endswith("#interfaz")
    assert f'{interfaz.COOKIE}="";' in r.headers["set-cookie"] and "Max-Age=0" in r.headers["set-cookie"]
    http.cookies.clear()
    assert 'data-interfaz="nueva"' not in http.get("/").text


@pytest.mark.parametrize("valor", ["", "otra", "nueva; Path=/x", "../nueva"])
def test_un_valor_que_no_esta_en_la_lista_no_se_guarda(cliente, valor):
    http, _ = cliente
    r = http.post("/interfaz", data={"interfaz": valor}, follow_redirects=False)
    assert r.status_code == 303 and "set-cookie" not in r.headers
    assert "aviso=" in r.headers["location"] and "fugaz" not in r.headers["location"]


@pytest.mark.parametrize("destino", ["https://otro.example/", "//otro.example", "/\\otro"])
def test_solo_se_vuelve_a_una_ruta_de_este_hub(cliente, destino):
    http, _ = cliente
    r = http.post("/interfaz", data={"interfaz": "nueva", "destino": destino}, follow_redirects=False)
    assert r.headers["location"].startswith("/?aviso=")


def test_una_web_ajena_no_puede_cambiarle_la_interfaz_a_nadie(cliente):
    http, _ = cliente
    r = http.post("/interfaz", data={"interfaz": "nueva"}, headers={"origin": "https://otro.example"},
                  follow_redirects=False)
    assert r.status_code == 403 and "set-cookie" not in r.headers


def test_sin_sus_plantillas_no_se_ofrece_ni_se_enciende(cliente, monkeypatch):
    http, _ = cliente
    monkeypatch.setattr(interfaz, "disponible", lambda: False)
    assert 'id="interfaz"' not in http.get("/guia").text
    r = http.post("/interfaz", data={"interfaz": "nueva"}, follow_redirects=False)
    assert "set-cookie" not in r.headers and "aviso=" in r.headers["location"]


def test_si_sus_plantillas_llegan_con_el_hub_ya_arrancado_no_se_sirve_a_medias(cliente, monkeypatch):
    """Los entornos se montan al arrancar. Con la carpeta recién llegada y la
    cookie puesta, pedir un entorno que no existe era un 500 en cada pantalla."""
    http, _ = cliente
    monkeypatch.setattr(web, "_PLANTILLAS", {interfaz.CLASICA: web.plantillas})
    pagina = _con_la_nueva(http).get("/guia")
    assert pagina.status_code == 200 and 'data-interfaz="nueva"' not in pagina.text
    assert 'id="interfaz"' not in pagina.text
    r = http.post("/interfaz", data={"interfaz": "nueva"}, follow_redirects=False)
    assert "set-cookie" not in r.headers and "aviso=" in r.headers["location"]


def test_el_interruptor_esta_al_pie_de_la_guia_en_las_dos_y_funciona_sin_javascript(cliente):
    http, _ = cliente
    for nueva in (False, True):
        if nueva:
            _con_la_nueva(http)
        bloque = http.get("/guia").text.split('<section id="interfaz"')[1].split("</section>")[0]
        assert "Interfaz nueva (vista previa)" in bloque
        # Un formulario normal: sin `data-sin-recarga` ni nada que pida script.
        formulario = re.search(r"<form[^>]*>", bloque).group(0)
        assert formulario == '<form method="post" action="/interfaz">'
        assert f'name="interfaz" value="{"clasica" if nueva else "nueva"}"' in bloque
        assert ("Volver a la de siempre" if nueva else "Probar la interfaz nueva") in bloque


def test_desde_cualquier_pantalla_de_la_nueva_se_llega_a_apagarla(cliente):
    http, _ = cliente
    _con_la_nueva(http)
    for ruta in ("/", "/trabajo", "/maquina", "/tablero", "/acceso"):
        assert http.get(ruta).text.count('href="/guia#interfaz"') == 2, ruta   # el raíl y «Más»


# ── el marco: mismo contrato, otra navegación ────────────────────────────────

def _marco(html: str) -> str:
    """El raíl de la página, que es una región."""
    return re.search(r'<nav class="rail-global" data-region="rail".*?</nav>', html, re.S).group(0)


def test_el_marco_nuevo_conserva_el_contrato_de_dom(cliente):
    http, _ = cliente
    _secretario_en_todo_el_hub()
    html = _con_la_nueva(http).get("/").text
    assert html.count('data-region="rail"') == 1 and html.count('class="rail-global"') == 1
    assert '<div class="principal-col">\n<div class="envoltura">\n  <header>' in html
    assert '<aside id="secretario-panel"' in html and 'id="secretario-pestana"' in html
    assert 'id="secretario-cuerpo"' in html and 'id="sec-chat"' in html
    assert html.count('<script src="/static/marco.js"></script>') == 1
    assert '<meta name="theme-color" content="#11161d">' in html
    trabajo = http.get("/trabajo").text
    assert re.search(r'<body class="completo\s', trabajo) and 'class="rail-global"' in trabajo


def test_el_rail_son_las_nueve_secciones_con_donde_estas_marcado(cliente):
    http, _ = cliente
    _con_la_nueva(http)
    for ruta, seccion in (("/", "hoy"), ("/maquina", "salud"), ("/orquestador/permisos", "ajustes"),
                          ("/tablero", "ideas"), ("/reuniones", "herramientas"), ("/canal", "fuera")):
        marco = _marco(http.get(ruta).text)
        destinos = re.findall(r'<a href="([^"]+)" class="marco-destino del-rail ([^"]*)"', marco)
        assert [d for d, _ in destinos] == [s["pantallas"][0]["ruta"] for s in navegacion.SECCIONES]
        aqui = [d for d, clases in destinos if "aqui" in clases.split()]
        esperada = next(s for s in navegacion.SECCIONES if s["clave"] == seccion)["pantallas"][0]["ruta"]
        assert aqui == [esperada], (ruta, aqui)
        assert marco.count('aria-current="page"') >= 1


def _visibles(s: dict, encendidas) -> list[dict]:
    """Las pantallas de una sección que salen: las de una herramienta
    opcional, sólo encendida (decisión 438)."""
    return [p for p in s["pantallas"] if not p.get("opcional") or p["opcional"] in encendidas]


@pytest.mark.parametrize("encendidas", [(), ("puente-kvm",)])
def test_a_toda_pantalla_se_llega_desde_el_marco(cliente, encendidas):
    """Nueve destinos en vez de veintiuno: lo demás, por la tira de su sección
    (y en el teléfono, por «Más»). Una herramienta opcional, sólo encendida."""
    from hub import opcionales
    for clave in encendidas:
        opcionales.poner(clave, True)
    http, _ = cliente
    _con_la_nueva(http)
    for s in navegacion.SECCIONES:
        html = http.get(s["pantallas"][0]["ruta"]).text
        for p in s["pantallas"]:
            # La sección del secretario trae su propia barra, con todo lo suyo.
            if s["clave"] == "secretario" and p["clave"] != "secretario":
                assert 'href="/secretario/monitor"' in html
                continue
            sale = not p.get("opcional") or p["opcional"] in encendidas
            assert (f'href="{p["ruta"]}"' in html) is sale, (s["clave"], p["ruta"])
        if len(s["pantallas"]) > 1 and s.get("tira", True):
            tira = html.split('<nav class="marco-tira"')[1].split("</nav>")[0]
            assert [h for h in re.findall(r'<a href="([^"]+)"', tira)] == [
                p["ruta"] for p in _visibles(s, encendidas)]
            assert tira.count('aria-current="page"') == 1


def test_la_tira_va_dentro_de_la_cabecera_y_se_esconde_con_ella(cliente):
    """El secretario en el teléfono y el modo monitor esconden
    `.envoltura > header`: la tira, que es suya, se va sin regla aparte."""
    http, _ = cliente
    html = _con_la_nueva(http).get("/maquina").text
    cabecera = html.split('<div class="envoltura">')[1].split("</header>")[0]
    assert '<nav class="marco-tira"' in cabecera
    assert html.count('<nav class="marco-tira"') == 1


def test_las_pestanas_de_ajuste_del_secretario_son_de_ajustes_y_traen_su_tira(cliente):
    """Desde la tira de Ajustes se llega a `/secretario?p=avisos`. Allí se
    marcaba Secretario y no había tira: no había vuelta a Ajustes salvo por el
    raíl. Sus pestañas propias siguen siendo de su sección, sin tira."""
    http, _ = cliente
    _con_la_nueva(http)
    for pestana in ("avisos", "fuentes", "confianza", "disparadores", "personaje", "ajustes"):
        html = http.get(f"/secretario?p={pestana}").text
        assert re.search(r'<a href="/conexiones" class="marco-destino del-rail aqui', _marco(html)), pestana
        tira = html.split('<nav class="marco-tira"')[1].split("</nav>")[0]
        marcada = re.search(r'<a href="([^"]+)" class="aqui"', tira)
        assert marcada and marcada.group(1) == "/secretario?p=avisos", pestana
        assert 'href="/conexiones"' in tira and 'href="/guia"' in tira
    for propia in ("", "?p=conversacion", "?p=pendientes", "?p=memoria"):
        html = http.get("/secretario" + propia).text
        assert re.search(r'<a href="/secretario" class="marco-destino del-rail aqui', _marco(html)), propia
        assert '<nav class="marco-tira"' not in html, propia


def test_toda_pantalla_que_pinta_el_hub_tiene_seccion_en_el_marco(cliente):
    """El raíl de siempre no lista todas las pantallas —al banco de dictado se
    llega por la guía—, así que no basta con mirarlo: se pinta cada ruta GET y
    tiene que salir con su sección marcada. Una pantalla nueva sin sitio en
    `navegacion.SECCIONES` se queda sin camino de vuelta en el teléfono."""
    from hub import recorrido
    http, _ = cliente
    _con_la_nueva(http)
    sin_seccion = []
    vistas = 0
    for ruta in recorrido.rutas_get():
        if "{" in ruta or ruta in recorrido.NO_SE_VISITAN or ruta.startswith("/api/"):
            continue
        r = http.get(ruta, follow_redirects=False)
        if r.status_code != 200 or "text/html" not in r.headers.get("content-type", ""):
            continue
        vistas += 1
        if len(re.findall(r'class="marco-destino del-rail aqui', r.text)) != 1:
            sin_seccion.append(ruta)
    assert vistas >= 25, f"sólo {vistas} pantallas: esto no ha recorrido el hub"
    assert not sin_seccion, f"pantallas sin sección en `navegacion.SECCIONES`: {sin_seccion}"
    assert navegacion.de_pantalla("banco", "/voz/banco") == "ajustes"


def test_donde_la_seccion_es_una_sola_pantalla_no_hay_tira(cliente):
    http, _ = cliente
    _con_la_nueva(http)
    for ruta in ("/", "/trabajo", "/secretario", "/secretario/monitor", "/no-existe-esta-pantalla"):
        assert '<nav class="marco-tira"' not in http.get(ruta).text, ruta


def test_la_ficha_de_un_proyecto_es_de_proyectos_y_no_marca_ninguna_de_la_tira(cliente):
    http, conexion = cliente
    c = conexion()
    c.execute("INSERT INTO proyecto (id, nombre, asiento) VALUES ('demo','Demo','/tmp/demo')")
    c.commit()
    c.close()
    html = _con_la_nueva(http).get("/proyecto/demo").text
    assert re.search(r'<a href="/inventario" class="marco-destino del-rail aqui', _marco(html))
    tira = html.split('<nav class="marco-tira"')[1].split("</nav>")[0]
    assert 'aria-current="page"' not in tira


@pytest.mark.parametrize("encendidas", [(), ("puente-kvm",)])
def test_mas_es_un_details_con_las_secciones_que_no_caben_en_la_barra(cliente, encendidas):
    from hub import opcionales
    for clave in encendidas:
        opcionales.poner(clave, True)
    http, _ = cliente
    marco = _marco(_con_la_nueva(http).get("/").text)
    mas = marco.split('<details class="marco-mas" id="marco-mas">')[1]
    assert "<summary" in mas and "</details>" in mas
    titulos = re.findall(r'<h2 class="marco-hoja-titulo">([^<]+)</h2>', mas)
    assert titulos == ["Proyectos", "Salud", "Herramientas", "Fuera", "Ajustes"]
    for s in navegacion.SECCIONES:
        if s["clave"] not in navegacion.BARRA:
            for p in s["pantallas"]:
                sale = not p.get("opcional") or p["opcional"] in encendidas
                assert (f'href="{p["ruta"]}"' in mas) is sale, p["ruta"]


def test_la_barra_del_telefono_va_en_el_dom_en_el_orden_en_que_se_ve(cliente):
    """Secretario · Trabajo · Hoy · Ideas · Más. Antes eran los enlaces del
    raíl recolocados con `order`: se veía ese orden y el tabulador recorría
    Hoy, Secretario, Trabajo, Ideas. Ahora la barra tiene sus propios enlaces,
    escritos en su orden, y la hoja no declara ningún `order` para ellos."""
    http, _ = cliente
    marco = _marco(_con_la_nueva(http).get("/tablero").text)
    barra = re.findall(r'<a href="([^"]+)" class="marco-destino de-barra ([^"]*)"', marco)
    por_clave = {s["clave"]: s["pantallas"][0]["ruta"] for s in navegacion.SECCIONES}
    assert [d for d, _ in barra] == [por_clave[c] for c in navegacion.BARRA]
    assert [d for d, clases in barra if "aqui" in clases.split()] == ["/tablero"]
    # Tras ellos, «Más»; y antes, los del raíl: cada juego, seguido.
    assert marco.index('class="marco-destino de-barra') > marco.rindex('class="marco-destino del-rail')
    assert marco.index('<details class="marco-mas"') > marco.rindex('class="marco-destino de-barra')
    assert not re.search(r"\.marco-(destino|mas)[^{]*\{[^}]*\border\s*:", _css_del_marco())
    # El nombre corto, sólo en la barra.
    assert ">Ideas</span>" in marco and ">Ideas y tareas</span>" in marco


def test_mas_lleva_el_punto_solo_si_algo_de_dentro_urge(cliente):
    """Decisión 297: un aviso no puede quedar escondido detrás de un pliegue."""
    from hub import version
    http, _ = cliente
    _con_la_nueva(http)
    # Recién instalado falta terminar de actualizar: urge en Ajustes, que va dentro.
    marco = _marco(http.get("/").text)
    assert 'class="marco-punto"' in marco and "algo pide atención" in marco
    version.registrar(version.del_codigo())
    marco = _marco(http.get("/").text)
    assert 'class="marco-punto"' not in marco and "algo pide atención" not in marco
    assert 'class="marco-cifra' not in marco


def _pestana(html: str) -> str:
    return re.search(r'<button id="secretario-pestana".*?</button>', html, re.S).group(0)


def test_el_secretario_es_el_panel_de_siempre_con_su_nombre_y_su_atajo(cliente):
    """C-0450: el panel acoplado se retiró. La nueva no lleva marca propia en
    el panel ni copia su pestaña: sólo rellena `pestana_atajo` con `Ctrl .`."""
    http, _ = cliente
    _secretario_en_todo_el_hub("Ada")
    html = _con_la_nueva(http).get("/").text
    assert re.search(r'<span class="marco-nombre">Ada</span>', _marco(html))
    panel = html.split('<aside id="secretario-panel"')[1].split("</aside>")[0]
    assert panel.startswith(' aria-label="Ada">')
    assert "data-arranca" not in html and "Hablar con" not in panel
    assert re.search(r'<span class="tecla marco-atajo solo-teclado" aria-hidden="true">Ctrl \.</span>\s*'
                     r'<span class="tenue" id="secretario-flecha">', panel)
    # El personaje sigue siendo hijo directo de la pestaña: de eso cuelga su CSS.
    assert re.search(r'data-espera=\'[^\']*\'>\s*<(svg|span) class="pj', panel)
    assert "[data-rotulo]" not in panel and "data-rotulo" in panel and "data-acompanantes" in panel


def test_la_pestana_de_la_nueva_es_la_de_siempre_mas_su_atajo(cliente):
    """Un solo marcado: antes la nueva copiaba el bloque entero, y lo que
    cambiara en la base había que acordarse de cambiarlo allí."""
    http, _ = cliente
    _secretario_en_todo_el_hub("Ada")
    de_siempre = _pestana(http.get("/").text)
    nueva = _pestana(_con_la_nueva(http).get("/").text)
    atajo = '<span class="tecla marco-atajo solo-teclado" aria-hidden="true">Ctrl .</span>'
    assert nueva.count(atajo) == 1 and nueva.replace(atajo, "") == de_siempre
    fuente = NUEVA.read_text(encoding="utf-8")
    assert "{% block pestana_secretario %}" not in fuente and "{% block panel_attrs %}" not in fuente
    base = (NUEVA.parent.parent / "base.html").read_text(encoding="utf-8")
    assert "{% block panel_attrs %}" not in base
    pestana = base.split("{% block pestana_secretario %}")[1].split("</button>")[0]
    assert pestana.index("{% block pestana_atajo %}{% endblock %}") < pestana.index('id="secretario-flecha"')


def test_en_la_de_siempre_el_panel_no_arranca_plegado_ni_lleva_el_atajo(cliente):
    http, _ = cliente
    _secretario_en_todo_el_hub("Ada")
    html = http.get("/").text
    assert "data-arranca" not in html and "marco-" not in html and "Ctrl ." not in html
    assert "data-barra" not in html and "sinBarra" not in html


def test_los_dos_botones_de_la_barra_van_dentro_del_rail_y_los_primeros(cliente):
    """Plegar y abrir son dos botones fijos y el CSS enseña uno: un
    `aria-expanded` cambiado a mano dentro de la región `rail` lo deshace
    `sin-recarga.js` al repintarla."""
    http, _ = cliente
    for ruta in ("/", "/trabajo"):
        marco = _marco(_con_la_nueva(http).get(ruta).text)
        botones = re.findall(r"<button\b[^>]*>", marco)
        assert len(botones) == 2, (ruta, botones)
        plegar, abrir = botones
        assert 'class="icono-solo marco-plegar"' in plegar and 'data-marco-barra="plegar"' in plegar
        assert 'aria-expanded="true"' in plegar and 'aria-label="Plegar el menú y los proyectos"' in plegar
        assert 'class="icono-solo marco-desplegar"' in abrir and 'data-marco-barra="abrir"' in abrir
        assert 'aria-expanded="false"' in abrir and 'aria-label="Abrir el menú y los proyectos"' in abrir
        assert all('type="button"' in b for b in botones)
        # Los primeros del raíl: van antes que la marca.
        assert marco.index("marco-plegar") < marco.index("marco-desplegar") < marco.index('class="marco-marca"')
        # Sólo un icono: el nombre lo dice `aria-label`.
        for contenido in re.findall(r"<button\b[^>]*>(.*?)</button>", marco, re.S):
            assert "<svg" in contenido and not re.sub(r"<svg.*?</svg>", "", contenido, flags=re.S).strip()


@pytest.mark.parametrize("voz", ["secretario", "asistente", "ninguna"])
def test_el_marco_se_pinta_igual_con_cualquier_voz(cliente, voz):
    http, conexion = cliente
    if voz == "secretario":
        _secretario_en_todo_el_hub()
    elif voz == "asistente":
        c = conexion()
        c.execute("INSERT INTO proyecto (id, nombre, asiento, tipo) VALUES ('asistente','Asistente','/tmp/a','asistente')")
        c.commit()
        c.close()
    _con_la_nueva(http)
    for ruta in ("/", "/trabajo", "/maquina", "/secretario"):
        html = http.get(ruta).text
        # Nueve del raíl, cuatro de la barra y «Más».
        assert 'data-interfaz="nueva"' in html and len(re.findall(r'class="marco-destino ', html)) == 14, ruta
    html = http.get("/").text
    assert ('id="secretario-panel"' in html) == (voz == "secretario")
    assert ('<aside id="asistente">' in html) == (voz == "asistente")


# ── la hoja del marco ────────────────────────────────────────────────────────

def _css_del_marco() -> str:
    fuente = NUEVA.read_text(encoding="utf-8")
    css = fuente.split("{% block estilo_marco %}")[1].split("{% endblock %}")[0]
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def test_el_marco_no_declara_display_sobre_el_rail():
    """Las pantallas que esconden el raíl lo hacen con `display:none` y poco
    peso (`body.app-propia .rail-global`). Si el marco pusiera un `display`
    más fuerte, en /secretario del teléfono saldrían dos barras."""
    culpables = [regla.strip() for regla in re.findall(r"[^{}]+\{[^{}]*\}", _css_del_marco())
                 if re.search(r"\.rail-global\s*(,|\{)", regla.split("{")[0] + "{")
                 and re.search(r"(^|[;{\s])display\s*:", regla.split("{", 1)[1])]
    assert not culpables, culpables


def _cuerpos_de_los_juegos() -> dict[str, str]:
    tokens = _sin_comentarios_css(NUEVA.read_text(encoding="utf-8").split("{% block tokens %}")[1].split("{% endblock %}")[0])
    return dict(re.findall(r'\[data-colores="([\w-]+)"\]\s*\{(.*?)\n\}', tokens, re.S))


def _juegos() -> dict[str, dict[str, str]]:
    """Los tokens de cada juego de colores, tal como están escritos en la base nueva."""
    return {clave: dict(re.findall(r"(--[\w-]+)\s*:\s*([^;]+);", cuerpo))
            for clave, cuerpo in _cuerpos_de_los_juegos().items()}


def _lab(color: str) -> tuple[float, float, float]:
    """Un `#rrggbb` en CIELAB (D65), para medir cuánto se parecen dos colores."""
    def lineal(c: float) -> float:
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (lineal(int(color[i:i + 2], 16) / 255) for i in (1, 3, 5))
    x = (0.4124 * r + 0.3576 * g + 0.1805 * b) / 0.95047
    y = 0.2126 * r + 0.7152 * g + 0.0722 * b
    z = (0.0193 * r + 0.1192 * g + 0.9505 * b) / 1.08883
    def f(t: float) -> float:
        return t ** (1 / 3) if t > 0.008856 else 7.787 * t + 16 / 116
    return 116 * f(y) - 16, 500 * (f(x) - f(y)), 200 * (f(y) - f(z))


def _sin_comentarios_css(css: str) -> str:
    return re.sub(r"/\*.*?\*/", "", css, flags=re.S)


def test_los_colores_usan_los_nombres_de_token_de_siempre_y_no_hay_data_paleta():
    fuente = NUEVA.read_text(encoding="utf-8")
    base = (NUEVA.parent.parent / "base.html").read_text(encoding="utf-8")
    assert "data-paleta" not in fuente      # «paleta» es la de órdenes
    de_siempre = set(re.findall(r"^\s*(--[\w-]+):", base.split("{% block tokens %}")[1].split("{% endblock %}")[0], re.M))
    nuevos = set(_juegos()[interfaz.DE_FABRICA]) - de_siempre
    # Sólo lo que el marco usa: lo hondo, el tinte de «dónde estás» y sus medidas.
    assert nuevos == {"--lienzo-hondo", "--acento-suave", "--marco-rail", "--marco-barra",
                      "--marco-rail-plegado"}, nuevos
    for token in nuevos:
        assert f"var({token})" in fuente or f"var({token})" in (
            NUEVA.parent.parent.parent / "static" / "chat-secretario.css").read_text(encoding="utf-8"), token
    # Los radios y la letra, los de siempre: ningún juego los redefine (también
    # la escala `--letra-*`, C-0403).
    for tokens in _juegos().values():
        assert not [t for t in tokens if re.match(r"--r-|--fuente|--letra-", t)]


# ── el catálogo de colores (fase 1b) ─────────────────────────────────────────

def test_cada_juego_del_catalogo_tiene_su_bloque_y_cada_bloque_su_entrada():
    assert set(_juegos()) == set(interfaz.COLORES)
    assert interfaz.DE_FABRICA in interfaz.COLORES


def test_un_juego_solo_cambia_colores_y_los_cambia_todos():
    """Un juego que se dejara un color sin definir lo heredaría del de fábrica
    y saldría una pantalla cálida con rayas frías; uno que tocara las medidas
    del marco dejaría de ser sólo colores."""
    juegos = _juegos()
    de_color = {t for t in juegos[interfaz.DE_FABRICA] if not t.startswith("--marco-")}
    for clave, tokens in juegos.items():
        if clave != interfaz.DE_FABRICA:
            assert set(tokens) == de_color, (clave, set(tokens) ^ de_color)


def test_el_color_del_navegador_es_el_lienzo_de_su_juego():
    for clave, tokens in _juegos().items():
        assert interfaz.COLORES[clave].lienzo == tokens["--lienzo"].strip(), clave


def test_en_ningun_juego_el_acento_coincide_con_un_tono_de_atencion():
    """Si actuar y «te espera» son el mismo color, cada botón principal parece
    una alerta. Era el defecto de Brasa en la maqueta."""
    for clave, tokens in _juegos().items():
        acento = _lab(tokens["--acento"].strip())
        for atencion in ("--espera", "--ok", "--riesgo", "--alerta", "--neutro"):
            # No basta con que no sea la misma cadena: `#f2b881` tampoco se
            # distingue de `#f2b880`. 25 de distancia en CIELAB es el suelo;
            # el juego que menos los separa (Brasa) da 31.
            distancia = sum((a - b) ** 2 for a, b in zip(acento, _lab(tokens[atencion].strip()))) ** 0.5
            assert distancia >= 25, (clave, atencion, round(distancia, 1))


def test_un_bloque_de_juego_solo_declara_tokens_y_va_en_varias_lineas():
    """Lo que `test_css_componentes` da por bueno es el bloque entero: una
    declaración suelta (`color: #fff`) dentro de él pasaría sin que nadie la
    viera, y un juego en una sola línea le descuadra la cuenta de bloques."""
    cuerpos = _cuerpos_de_los_juegos()
    assert set(cuerpos) == set(interfaz.COLORES)
    for clave, cuerpo in cuerpos.items():
        resto = re.sub(r"--[\w-]+\s*:\s*[^;{}]+;", "", cuerpo).strip()
        assert not resto, (clave, resto)
        assert cuerpo.count("\n") >= 3, clave


def test_sin_interfaz_en_el_contexto_la_base_nueva_cae_en_los_de_fabrica():
    """La reserva escrita en la plantilla (quien pinta la base sin `_vista`)
    tiene que ser el juego de fábrica: si éste cambia, ella no se entera sola."""
    html = web._PLANTILLAS[interfaz.NUEVA].get_template("base.html").render(titulo="x")
    assert f'data-colores="{interfaz.DE_FABRICA}"' in html
    assert f'name="theme-color" content="{interfaz.COLORES[interfaz.DE_FABRICA].lienzo}"' in html


def test_sin_su_cookie_o_con_una_desconocida_tocan_los_colores_de_fabrica():
    assert interfaz.colores_elegidos(None) == interfaz.DE_FABRICA
    assert interfaz.colores_elegidos({}) == interfaz.DE_FABRICA
    assert interfaz.colores_elegidos({interfaz.COOKIE_COLORES: "fosforito"}) == interfaz.DE_FABRICA
    assert interfaz.colores_elegidos({interfaz.COOKIE_COLORES: "brasa"}) == "brasa"


def test_elegir_colores_deja_su_cookie_y_la_pagina_sale_con_ellos(cliente):
    http, _ = cliente
    _con_la_nueva(http)
    assert 'data-colores="pizarra"' in http.get("/").text
    r = http.post("/interfaz/colores", data={"colores": "brasa", "destino": "/guia#colores"},
                  follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].endswith("#colores")
    galleta = r.headers["set-cookie"]
    assert galleta.startswith(f"{interfaz.COOKIE_COLORES}=brasa;")
    assert "SameSite=lax" in galleta and "HttpOnly" in galleta and "Path=/" in galleta
    assert "Max-Age=" in galleta and "Secure" not in galleta
    html = http.get("/").text
    assert 'data-colores="brasa"' in html
    assert f'name="theme-color" content="{interfaz.COLORES["brasa"].lienzo}"' in html


def test_por_https_la_cookie_de_los_colores_va_marcada_como_segura(cliente):
    http, _ = cliente
    _con_la_nueva(http)
    r = http.post("/interfaz/colores", data={"colores": "brasa"}, headers={"x-forwarded-proto": "https"},
                  follow_redirects=False)
    assert "Secure" in r.headers["set-cookie"]


def test_con_la_de_siempre_no_se_guardan_colores_ni_se_dice_que_cambiaron(cliente):
    http, _ = cliente
    r = http.post("/interfaz/colores", data={"colores": "brasa"}, follow_redirects=False)
    assert r.status_code == 303 and "set-cookie" not in r.headers
    assert "interfaz%20nueva" in r.headers["location"] and "fugaz" not in r.headers["location"]


def test_volver_a_los_de_fabrica_borra_la_cookie(cliente):
    http, _ = cliente
    _con_la_nueva(http)
    r = http.post("/interfaz/colores", data={"colores": interfaz.DE_FABRICA}, follow_redirects=False)
    assert r.status_code == 303
    assert f'{interfaz.COOKIE_COLORES}="";' in r.headers["set-cookie"] and "Max-Age=0" in r.headers["set-cookie"]


@pytest.mark.parametrize("valor", ["", "fosforito", "brasa; Path=/x", "../brasa", "Brasa"])
def test_unos_colores_que_no_estan_en_el_catalogo_no_se_guardan(cliente, valor):
    http, _ = cliente
    r = http.post("/interfaz/colores", data={"colores": valor}, follow_redirects=False)
    assert r.status_code == 303 and "set-cookie" not in r.headers
    assert "aviso=" in r.headers["location"] and "fugaz" not in r.headers["location"]


@pytest.mark.parametrize("destino", ["https://otro.example/", "//otro.example", "/\\otro"])
def test_tras_elegir_colores_solo_se_vuelve_a_una_ruta_de_este_hub(cliente, destino):
    http, _ = cliente
    _con_la_nueva(http)
    r = http.post("/interfaz/colores", data={"colores": "brasa", "destino": destino}, follow_redirects=False)
    assert r.headers["location"].startswith("/?aviso=")


def test_una_web_ajena_no_puede_cambiarle_los_colores_a_nadie(cliente):
    http, _ = cliente
    r = http.post("/interfaz/colores", data={"colores": "brasa"}, headers={"origin": "https://otro.example"},
                  follow_redirects=False)
    assert r.status_code == 403 and "set-cookie" not in r.headers


def test_con_la_de_siempre_la_cookie_de_los_colores_no_cambia_ni_un_byte(cliente):
    http, _ = cliente
    sin_nada = {ruta: http.get(ruta).text for ruta in ("/", "/guia", "/trabajo")}
    http.cookies.set(interfaz.COOKIE_COLORES, "brasa")
    for ruta, html in sin_nada.items():
        assert http.get(ruta).text == html, ruta


def test_el_catalogo_solo_sale_con_la_nueva_y_se_elige_sin_javascript(cliente):
    http, _ = cliente
    assert "/interfaz/colores" not in http.get("/guia").text
    html = _con_la_nueva(http).get("/guia").text
    catalogo = html.split('id="colores"')[1].split("</section>")[0]
    for clave, juego in interfaz.COLORES.items():
        assert f'class="colores-juego" data-colores="{clave}"' in catalogo
        assert f'name="colores" value="{clave}"' in catalogo and juego.nombre in catalogo
    assert catalogo.count('method="post" action="/interfaz/colores"') == len(interfaz.COLORES)
    assert "data-sin-recarga" not in catalogo     # cambia `<html>`: hace falta la recarga entera
    # El que está en uso no ofrece su botón; los demás, sí.
    assert catalogo.count("En uso") == 1 and "Usar Brasa" in catalogo and "Usar Pizarra" not in catalogo
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|rgba?\(", catalogo)   # la muestra se pinta con tokens
