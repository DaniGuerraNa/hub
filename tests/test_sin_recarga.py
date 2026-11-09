"""El contrato de `data-sin-recarga` del lado del servidor (C-0167, decisión 359).

`sin-recarga.js` no inventa nada: hace el mismo POST y sigue el mismo 303. Eso
sólo vale si cada formulario marcado va a una ruta que **redirige**, si la
página que lo lleva tiene regiones que cambiar, y si sin JavaScript el envío
normal sigue funcionando igual. Eso es lo que se comprueba aquí.
"""

from __future__ import annotations

import inspect
import re
import pytest
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from fastapi.testclient import TestClient
from starlette.routing import compile_path

from hub import web

PLANTILLAS = Path(__file__).resolve().parents[1] / "src" / "hub" / "templates"
FORM = re.compile(r"<form\b[^>]*>", re.S)


def _marcados():
    for p in sorted(PLANTILLAS.glob("*.html")):
        for etiqueta in FORM.findall(p.read_text(encoding="utf-8")):
            if "data-sin-recarga" in etiqueta:
                yield p.name, etiqueta


def test_hay_pantallas_marcadas():
    assert len({nombre for nombre, _ in _marcados()}) >= 10


def test_todo_formulario_sin_recarga_es_un_post():
    """El script sólo intercepta POST: un GET marcado no haría nada distinto y
    daría a entender lo contrario."""
    for nombre, etiqueta in _marcados():
        assert 'method="post"' in etiqueta, (nombre, etiqueta)


def test_toda_pantalla_con_formularios_sin_recarga_tiene_regiones():
    """Sin región, el script navega como antes: el formulario marcado no
    cambiaría nada y nadie sabría por qué."""
    for nombre in {n for n, _ in _marcados()}:
        texto = (PLANTILLAS / nombre).read_text(encoding="utf-8")
        if nombre == "_ui.html":
            continue
        assert "data-region=" in texto, nombre


def _ruta_post(accion: str):
    camino = re.sub(r"\{\{.*?\}\}", "X", accion).split("?")[0]
    for r in web.app.routes:
        if "POST" in getattr(r, "methods", set()):
            regex, _, _ = compile_path(r.path)
            if regex.match(camino):
                return r
    return None


def test_cada_formulario_marcado_va_a_una_ruta_que_redirige():
    """El 303 es la mitad del contrato: de ahí sale la página cuyas regiones
    se cambian. Una ruta que contestara HTML o JSON obligaría al script a
    adivinar."""
    for nombre, etiqueta in _marcados():
        m = re.search(r'action="([^"]+)"', etiqueta)
        if not m or "{{ accion }}" in m.group(1):
            continue
        ruta = _ruta_post(m.group(1))
        assert ruta is not None, (nombre, m.group(1))
        fuente = inspect.getsource(ruta.endpoint)
        assert "_volver(" in fuente or "RedirectResponse(" in fuente, (nombre, ruta.path)


def test_base_carga_sin_recarga_despues_de_hub_ui():
    """Después: la confirmación de `data-confirmar` (en `hub-ui.js`) tiene que
    oír el envío antes que este script."""
    base = (PLANTILLAS / "base.html").read_text(encoding="utf-8")
    assert base.index("/static/hub-ui.js") < base.index("/static/sin-recarga.js")


def test_la_marca_de_js_va_en_html_antes_del_primer_pintado():
    base = (PLANTILLAS / "base.html").read_text(encoding="utf-8")
    cabeza = base[:base.index("</head>")]
    assert "document.documentElement.classList.add('con-js')" in cabeza
    assert 'rel="preload" href="/static/inter.woff2?v=1"' in cabeza
    assert "body.con-js" not in base


def test_la_fuente_se_guarda_y_el_codigo_se_sigue_revalidando():
    """La fuente no cambia nunca: revalidarla en cada página era una ida y
    vuelta antes de pintar el texto con ella, y en el teléfono el texto
    saltaba al llegar. El JavaScript sí se revalida siempre (un arreglo que
    no llega es peor)."""
    cliente = TestClient(web.app)
    assert "immutable" in cliente.get("/static/inter.woff2").headers["cache-control"]
    assert cliente.get("/static/sin-recarga.js").headers["cache-control"] == "no-cache, must-revalidate"


def test_si_cambia_la_fuente_cambia_su_version():
    """Guardada un año sin preguntar, una fuente nueva con la misma dirección
    no llegaría nunca. Si este hash deja de casar: sube el `?v=` de
    `inter.woff2` en `base.html` (las dos veces) y pon aquí el nuevo."""
    import hashlib

    fuente = (PLANTILLAS.parent / "static" / "inter.woff2").read_bytes()
    assert hashlib.sha256(fuente).hexdigest() == \
        "f052ee44c3728dfd23aba8a4567150bc314d23903026fbb6ad089422c2df56af"
    base = (PLANTILLAS / "base.html").read_text(encoding="utf-8")
    assert base.count("/static/inter.woff2?v=1") == 2


def test_las_hojas_del_secretario_van_en_la_cabeza():
    """En el cuerpo, el teléfono pintaba el raíl antes de leer que ahí no va."""
    html = TestClient(web.app).get("/secretario").text
    cabeza = html[:html.index("</head>")]
    assert "/static/chat-secretario.css" in cabeza
    assert "body.app-propia .rail-global" in cabeza


def test_lo_que_se_hace_en_una_pestana_del_secretario_vuelve_a_esa_misma_pestana():
    """C-0187: «Conversación» enlazaba a `/secretario?p=conversacion` y aprobar
    desde su lado volvía a `/secretario`. Para `sin-recarga.js` eran dos
    pantallas, y aprobar recargaba la página entera —con la conversación—,
    que es justo lo que las regiones evitan."""
    from hub.secretario import memoria
    con = memoria.conectar()
    con.execute("INSERT INTO solicitud (accion, params, creada) VALUES ('anotar', '{\"texto\": \"x\"}', ?)",
                (memoria.ahora(),))
    con.commit()
    con.close()
    cliente = TestClient(web.app)
    barra = re.search(r'<nav class="sec-nav".*?</nav>', cliente.get("/secretario").text, re.S).group(0)
    pestanas = re.findall(r'href="([^"]+)"', barra)
    assert len(pestanas) == 4, pestanas
    vistas = 0
    for pestana in pestanas:
        html = cliente.get(pestana).text
        for etiqueta, cuerpo in re.findall(r"(<form\b[^>]*>)(.*?)</form>", html, re.S):
            volver = re.search(r'name="volver" value="([^"]*)"', cuerpo)
            if "data-sin-recarga" in etiqueta and volver:
                vistas += 1
                assert volver.group(1) == pestana, (pestana, etiqueta)
    assert vistas >= 4, "sin una solicitud a la vista esto no comprueba nada"


# ── Sin JavaScript, el envío normal sigue igual ─────────────────────────────

def test_sin_js_apuntar_una_idea_vuelve_al_tablero_con_su_aviso():
    r = TestClient(web.app).post("/tablero/idea", data={"texto": "una idea"},
                                 follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"].startswith("/tablero?aviso=")


def test_sin_js_guardar_un_nivel_vuelve_a_la_misma_pantalla():
    r = TestClient(web.app).post("/orquestador/permiso",
                                 data={"proyecto_id": "no-existe", "nivel": "leer"},
                                 follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"].startswith("/orquestador/permisos?aviso=")


def test_sin_js_subir_al_intercambio_vuelve_y_el_aviso_es_fugaz():
    """Fugaz porque salió bien, y es la señal con la que el script vacía el
    formulario de subir: si no, el archivo elegido se quedaba para subirlo dos
    veces."""
    r = TestClient(web.app).post("/intercambio/subir",
                                 files={"archivo": ("nota.txt", b"hola", "text/plain")},
                                 follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"].startswith("/intercambio?aviso=")
    assert "fugaz=1" in r.headers["location"]


def test_las_pantallas_marcadas_se_sirven_con_sus_regiones():
    """Las regiones van fuera de los `if`: si en la página de destino faltara
    una, el script recargaría entera en vez de cambiarla. Aquí, con todo
    vacío: sin sesión perdida, sin conexiones y sin tareas (C-0233)."""
    cliente = TestClient(web.app)
    for ruta, region in [("/tablero", "ideas"), ("/orquestador/permisos", "permisos"),
                         ("/intercambio", "archivos"), ("/servicios", "servicios"),
                         ("/", "bandeja"), ("/", "recuperacion"),
                         ("/orquestador", "atencion"), ("/orquestador", "listas"),
                         ("/conexiones", "llaves"), ("/conexiones", "destinos"),
                         ("/canal", "canal")]:
        r = cliente.get(ruta)
        assert r.status_code == 200, ruta
        assert f'data-region="{region}"' in r.text, (ruta, region)


# ── C-0233: las tres acciones que aún recargaban la página entera ────────────

def _sesion_perdida() -> int:
    """Una muestra preservada en un corte, con un panel: lo que hace salir
    «Se perdió una sesión de trabajo» y su «Ya lo revisé» en Panorama."""
    from hub import db
    con = db.abrir()
    try:
        sid = con.execute("INSERT INTO snapshot (tomado_en, server_pid, preservado) "
                          "VALUES ('2026-11-09T08:00:00', 4242, 1)").lastrowid
        con.execute("INSERT INTO panel (snapshot_id, pane_id, session, window_idx, pane_idx, cwd) "
                    "VALUES (?, '%1', 'demo', 0, 0, '/tmp/demo')", (sid,))
    finally:
        con.close()
    return sid


def _region(html: str, nombre: str) -> str:
    """Lo que hay desde `data-region="<nombre>"` hasta la región siguiente."""
    i = html.index(f'data-region="{nombre}"')
    j = html.find("data-region=", i + 1)
    return html[i:j if j != -1 else len(html)]


def _misma_pantalla(cliente, origen: str, destino: str) -> bool:
    """Lo que decide `pantalla()` en `sin-recarga.js`: la dirección sin el
    aviso y sin los parámetros que la página declara como de sus regiones
    (`data-params-de-region`). Si no casan, el script navega como antes."""
    m = re.search(r'data-params-de-region="([^"]*)"', cliente.get(origen).text)
    fuera = {"aviso", "fugaz", "hecho"} | (set(m.group(1).split()) if m else set())

    def limpia(url):
        u = urlsplit(url)
        return u.path, sorted((k, v) for k, vs in parse_qs(u.query).items()
                              for v in vs if k not in fuera)
    return limpia(origen) == limpia(destino)


@pytest.mark.parametrize("ruta,accion,regiones", [
    ("/", "/recuperacion/{id}/revisada", ["recuperacion"]),
    ("/conexiones", "/conexiones/nueva", ["destinos"]),
    ("/orquestador", "/orquestador/tarea", ["atencion", "listas"]),
], ids=["ya-lo-revise", "conexion-nueva", "encolar"])
def test_ya_lo_revise_conexion_nueva_y_encolar_van_sin_recargar(ruta, accion, regiones):
    """C-0233: eran las tres acciones que aún recargaban la página entera
    —arriba del todo y un parpadeo—. Su formulario va marcado y la página
    trae las regiones que la acción cambia."""
    if "{id}" in accion:
        accion = accion.replace("{id}", str(_sesion_perdida()))
    html = TestClient(web.app).get(ruta).text
    formulario = re.search(r'<form\b[^>]*action="' + re.escape(accion) + r'"[^>]*>', html)
    assert formulario, accion
    assert "data-sin-recarga" in formulario.group(0), formulario.group(0)
    for region in regiones:
        assert f'data-region="{region}"' in html, (ruta, region)


def test_las_tres_vuelven_a_la_misma_pantalla_y_no_obligan_a_navegar():
    """Si el 303 llevara a otra pantalla, `sin-recarga.js` navegaría igual y
    marcarlas no serviría de nada. «Encolar» lleva a su tarea (`?tarea=<id>`),
    que es por lo que C-0167 la dejó fuera; pero `tarea` es ya un parámetro
    de las regiones del orquestador y no cambia de pantalla."""
    cliente = TestClient(web.app)
    sid = _sesion_perdida()
    for origen, accion, datos in [
        ("/", f"/recuperacion/{sid}/revisada", {}),
        ("/conexiones", "/conexiones/nueva", {"alias": "vps-pruebas", "host": "203.0.113.7"}),
        ("/orquestador", "/orquestador/tarea", {"pedido": "revisa alfa"}),
    ]:
        r = cliente.post(accion, data=datos, follow_redirects=False)
        assert r.status_code == 303, accion
        assert _misma_pantalla(cliente, origen, r.headers["location"]), (accion, r.headers["location"])


def test_la_primera_conexion_cambia_el_no_hay_ninguna_por_la_lista_en_su_region():
    """La región va fuera de los dos `if` (vacía / con conexiones): si no,
    tras la primera alta el «No hay ninguna» se quedaría en pantalla."""
    cliente = TestClient(web.app)
    assert "No hay ninguna conexión declarada" in _region(cliente.get("/conexiones").text, "destinos")

    cliente.post("/conexiones/nueva", data={"alias": "vps-pruebas", "host": "203.0.113.7"},
                 follow_redirects=False)
    html = cliente.get("/conexiones").text
    assert "vps-pruebas" in _region(html, "destinos")
    assert "No hay ninguna conexión declarada" not in html


def test_ya_lo_revise_esta_dentro_de_su_region_y_al_marcarlo_la_region_queda_vacia():
    """El aviso entero es lo que cambia: dentro de la región, y la región
    sigue en la página cuando ya no hay nada que avisar."""
    cliente = TestClient(web.app)
    sid = _sesion_perdida()
    assert "Ya lo revisé" in _region(cliente.get("/").text, "recuperacion")

    cliente.post(f"/recuperacion/{sid}/revisada", follow_redirects=False)
    html = cliente.get("/").text
    assert 'data-region="recuperacion"' in html
    assert "Se perdió una sesión" not in html


@pytest.mark.parametrize("pestana,accion", [
    ("confianza", "/secretario/nivel"),
    ("fuentes", "/secretario/fuente/"),
    ("disparadores", "/secretario/disparadores"),
])
def test_los_ajustes_del_secretario_guardan_sin_recargar(pestana, accion):
    """C-0229: Confianza, Fuentes y Disparadores recargaban la página entera y
    volvían arriba (887 → 0 en el teléfono). Su región, y dentro sus
    formularios marcados."""
    html = TestClient(web.app).get(f"/secretario?p={pestana}").text
    i = html.index(f'data-region="{pestana}"')
    region = html[i:]
    formularios = re.findall(r'<form[^>]*action="' + re.escape(accion) + r'[^"]*"[^>]*>', region)
    assert formularios, pestana
    assert all("data-sin-recarga" in f for f in formularios), formularios


def test_elegir_personaje_vuelve_a_su_carta_y_no_arriba():
    """C-0229: recarga a propósito (la cabecera es una escena viva), pero en el
    teléfono son seis filas de cartas y volvía arriba del todo."""
    from hub.secretario import personaje
    otro = sorted(personaje.PERSONAJES)[-1]
    r = TestClient(web.app).post("/secretario/personaje", data={"personaje": otro}, follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"].endswith(f"#pj-{otro}")
    assert f'id="pj-{otro}"' in TestClient(web.app).get("/secretario?p=personaje").text


# ── Lo que corre antes del primer pintado (`<script data-antes-de-pintar>`) ──

def _seccion_previa(hash_: str, guardado: str | None, al_cargar: str = "") -> dict:
    import json
    import shutil
    import subprocess

    import pytest
    from jinja2 import Environment, FileSystemLoader

    node = shutil.which("node")
    if not node:
        pytest.skip("node no disponible")
    html = Environment(loader=FileSystemLoader(str(PLANTILLAS))).from_string(
        '{% import "_ui.html" as ui %}{{ ui.seccion_previa() }}').render()
    guion = re.search(r"<script data-antes-de-pintar>(.*?)</script>", html, re.S).group(1)
    programa = """
      const r = { estilos: [], clases: [] };
      const enlaces = ['personas', 'preguntas', 'registro'].map((s) => ({ dataset: { sec: s } }));
      const taller = { dataset: { secciones: 'canal' },
                       classList: { add: (c) => r.clases.push(c),
                                    remove: (c) => { r.clases = r.clases.filter((x) => x !== c); } },
                       querySelectorAll: () => enlaces };
      const alCargar = [];
      global.addEventListener = (ev, f) => { if (ev === 'load') alCargar.push(f); };
      global.location = { hash: HASH };
      global.sessionStorage = { getItem: (k) => (k === 'hub:seccion:canal' ? GUARDADO : null) };
      global.document = {
        currentScript: { closest: (s) => (s === '[data-secciones]' ? taller : null) },
        createElement: () => ({ setAttribute() {}, textContent: '',
                                remove() { r.estilos = r.estilos.filter((x) => x !== this.textContent); } }),
        head: { appendChild: (e) => r.estilos.push(e.textContent) },
      };
    """.replace("HASH", json.dumps(hash_)).replace("GUARDADO", json.dumps(guardado)) + guion + \
        "\n" + al_cargar + "\nconsole.log(JSON.stringify(r));"
    salida = subprocess.run([node, "-e", programa], capture_output=True, text=True, timeout=20)
    assert salida.returncode == 0, salida.stderr
    return json.loads(salida.stdout)


def test_la_seccion_se_elige_antes_de_pintar_con_el_hash_o_lo_recordado():
    """Antes se veían todas las secciones un instante y luego se plegaban."""
    assert _seccion_previa("#registro", "preguntas") == {
        "estilos": ["#sec-registro{display:block}"], "clases": ["con-secciones"]}
    assert _seccion_previa("", "preguntas")["estilos"] == ["#sec-preguntas{display:block}"]
    assert _seccion_previa("", None)["estilos"] == ["#sec-personas{display:block}"]


def test_un_hash_ajeno_no_se_cuela_en_el_estilo():
    """Lo que va al CSS sale de la lista del índice, nunca de la URL tal cual."""
    r = _seccion_previa("#x{}body{display:none", None)
    assert r["estilos"] == ["#sec-personas{display:block}"]


def test_si_secciones_js_no_llega_al_cargar_se_ve_la_pagina_entera():
    """Un script que no carga no puede dejar una sección suelta con un índice
    que no responde: se deshace lo puesto antes de pintar."""
    r = _seccion_previa("", None, "alCargar.forEach((f) => f());")
    assert r == {"estilos": [], "clases": []}


def test_si_secciones_js_llego_lo_puesto_se_queda():
    r = _seccion_previa("", None, "taller.dataset.seccionesListo = '1'; alCargar.forEach((f) => f());")
    assert r["clases"] == ["con-secciones"]


def test_trabajo_despliega_el_rail_si_plegar_js_no_llega():
    """Plegados desde el servidor, sin su script no se abrirían."""
    texto = (PLANTILLAS / "trabajo.html").read_text(encoding="utf-8")
    i = texto.index("dataset.plegarListo")
    assert "classList.remove('plegado')" in texto[i:i + 300]
    assert texto.index("dataset.plegarListo") < texto.index('<script src="/static/plegar.js">')
