"""La carpeta de intercambio: lo que entra, lo que sale y lo que nunca.

Este módulo existe para no romper dos reglas —el hub no escribe dentro de otros
proyectos, y el navegador no lee contenido (decisión 203)—, así que la mitad de
estas pruebas son intentos de salirse de la carpeta. Un endpoint que recibe un
nombre de archivo desde un móvil es exactamente donde se prueba `../`.
"""

from __future__ import annotations

import re
from urllib.parse import unquote

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


# ───────────────── por proyecto y slot, y lo de paso (decisión 288) ─────────────


@pytest.fixture
def registrados(cliente):
    con = web.conexion()
    con.execute("INSERT INTO proyecto (id, nombre, asiento) VALUES "
                "('tienda','Tienda','/tmp/t'), ('blog','Blog','/tmp/b')")
    con.execute("INSERT INTO slot (id, proyecto_id, nombre, creado_en) VALUES "
                "(4,'tienda','front','2026-10-21'), (9,'blog','textos','2026-10-21')")
    return con


def test_lo_subido_va_a_la_carpeta_del_proyecto_y_slot_elegidos(cliente, home, registrados):
    cliente.post("/intercambio/subir", data={"destino": "tienda:4"},
                 files={"archivo": ("logo.png", b"x", "image/png")})
    cliente.post("/intercambio/subir", data={"destino": "blog"},
                 files={"archivo": ("idea.md", b"y", "text/markdown")})
    # Un slot de OTRO proyecto no se mezcla: se queda en el proyecto.
    cliente.post("/intercambio/subir", data={"destino": "tienda:9"},
                 files={"archivo": ("raro.txt", b"z", "text/plain")})

    assert (home / "intercambio/tienda/4-front/logo.png").exists()
    assert (home / "intercambio/blog/idea.md").exists()
    assert (home / "intercambio/tienda/raro.txt").exists()
    assert intercambio.caduca_en("tienda/4-front/logo.png") is None   # subido: no caduca


def test_la_pantalla_agrupa_por_proyecto_y_dentro_por_slot_lo_nuevo_primero(
        cliente, home, registrados):
    import os
    from hub import api
    for ruta, cuando in (("tienda/4-front/a.png", 100), ("tienda/b.md", 300),
                         ("blog/9-textos/c.md", 200), ("suelto.txt", 50),
                         ("landing-de-una-sesion/index.html", 400)):
        destino = home / "intercambio" / ruta
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text("x")
        os.utime(destino, (cuando, cuando))

    grupos = api.intercambio(registrados)["grupos"]

    assert [g["titulo"] for g in grupos] == ["Sin proyecto", "Tienda", "Blog"]
    tienda = grupos[1]
    assert [(s["titulo"], [a["archivo"] for a in s["archivos"]]) for s in tienda["secciones"]] \
        == [("Sin slot", ["b.md"]), ("front", ["a.png"])]
    assert grupos[2]["secciones"][0]["titulo"] == "textos"
    pagina = cliente.get("/intercambio").text
    assert "Tienda" in pagina and "front" in pagina and "Sin proyecto" in pagina


def test_lo_pegado_en_la_terminal_va_a_su_slot_y_caduca_a_los_diez_dias(
        cliente, home, registrados):
    r = cliente.post("/api/terminal/adjuntar", data={"pegado": "1", "slot": "4"},
                     files={"archivo": ("image.png", b"\x89PNG", "image/png")})
    ruta = r.json()["ruta"]
    relativa = ruta.split("/intercambio/", 1)[1]

    assert relativa.startswith("tienda/4-front/pegado-")
    assert intercambio.caduca_en(relativa) is not None
    assert "se borra el" in cliente.get("/intercambio").text


def test_la_poda_borra_solo_lo_de_paso_vencido_y_las_carpetas_que_quedan_vacias(home):
    import time
    viejo = intercambio.guardar("viejo.png", b"1", "tienda/4-front", de_paso=True)
    nuevo = intercambio.guardar("nuevo.png", b"2", "blog", de_paso=True)
    guardado = intercambio.guardar("informe.pdf", b"3", "tienda")
    registro = intercambio._leer_de_paso()
    registro["tienda/4-front/viejo.png"] = time.time() - 11 * 86400
    registro["../../fuera.txt"] = 0          # un registro manipulado no saca el borrado
    intercambio._escribir_de_paso(registro)
    (home / "fuera.txt").write_text("no se toca")

    borrados = intercambio.podar_de_paso()

    assert borrados == ["tienda/4-front/viejo.png"]
    assert not viejo.exists() and not viejo.parent.exists()
    assert nuevo.exists() and guardado.exists() and (home / "fuera.txt").exists()
    assert set(intercambio._leer_de_paso()) == {"blog/nuevo.png"}


# ───────── miniaturas, un solo selector de sesión y subir varios (C-0385) ─────────
#
# Medido el 13-nov con 163 archivos: cada fila repetía el `<select>` de
# sesiones (3.311 `<option>`, 718 KB de HTML), las imágenes salían sólo por su
# nombre y el selector de archivo era el nativo, «Choose File» en inglés.

PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
    "1f15c4890000000d49444154789c6360f8cf000000030101001899f05e"
    "0000000049454e44ae426082")

PANELES = [{"pane_id": f"%{n}", "slot_id": n, "proyecto_id": "tienda",
            "proyecto_nombre": "Tienda", "slot_nombre": f"slot {n}"} for n in (1, 2, 3)]


@pytest.fixture
def con_sesiones(monkeypatch):
    monkeypatch.setattr(web.api, "paneles_abiertos", lambda con: PANELES)


def _fila(html: str, nombre: str) -> str:
    """El trozo de la fila de un archivo: de su nombre al de la siguiente."""
    desde = html.index(f'<span class="nombre">{nombre}')
    desde = html.rindex('<div class="inter-fila">', 0, desde)
    hasta = html.find('<div class="inter-fila">', desde + 1)
    return html[desde:hasta if hasta > 0 else None]


def test_una_imagen_raster_sale_con_su_miniatura_por_intercambio_ver(cliente, home):
    intercambio.guardar("foto.png", PNG)

    fila = _fila(cliente.get("/intercambio").text, "foto.png")

    img = re.search(r"<img [^>]*>", fila).group(0)
    assert 'src="/intercambio/ver/foto.png"' in img
    assert 'loading="lazy"' in img and 'alt="foto.png"' in img
    assert 'width="' in img and 'height="' in img


def test_un_svg_o_un_heic_no_llevan_miniatura(cliente, home):
    """🔴 Lo decide `ideas.TIPOS_IMAGEN`, la lista de `/intercambio/ver`, y no
    el grupo «Imágenes», que mete svg y heic: un SVG en línea en el mismo
    origen que la terminal es un XSS (343)."""
    intercambio.guardar("dibujo.svg", b"<svg onload='alert(1)'/>")
    intercambio.guardar("foto.heic", b"heic")

    html = cliente.get("/intercambio").text

    assert "<img" not in _fila(html, "dibujo.svg")
    assert "<img" not in _fila(html, "foto.heic")
    assert "/intercambio/ver/dibujo.svg" not in html


def test_una_imagen_mayor_que_el_tope_sale_solo_con_su_nombre(cliente, home, monkeypatch):
    """`/intercambio/ver` sirve el archivo entero: una foto de 5 MB por fila en
    el teléfono no es una miniatura."""
    monkeypatch.setattr(intercambio, "MINIATURA_HASTA", len(PNG))
    intercambio.guardar("chica.png", PNG)
    intercambio.guardar("grande.png", PNG + b"\0")

    html = cliente.get("/intercambio").text

    assert "<img" in _fila(html, "chica.png")
    assert "<img" not in _fila(html, "grande.png")


def test_la_pagina_lleva_un_solo_selector_de_sesion(cliente, home, con_sesiones):
    for n in range(5):
        intercambio.guardar(f"nota-{n}.txt", b"x")

    html = cliente.get("/intercambio").text

    assert html.count('name="pane_id"') == 1
    assert html.count("<option value=\"%1\"") == 1
    # Fuera de la región que se repinta: si no, elegir sesión se perdería en
    # cada acción sin recargar.
    region = html[html.index('data-region="archivos"'):]
    assert 'id="inter-a-sesion"' not in region and 'id="inter-borrar"' not in region
    assert "Sesión a la que pasar rutas" in html


def test_el_boton_de_cada_fila_manda_su_archivo_al_formulario_comun(
        cliente, home, con_sesiones, monkeypatch):
    intercambio.guardar("captura.png", PNG)
    html = cliente.get("/intercambio").text
    boton = re.search(r'<button [^>]*form="inter-a-sesion"[^>]*>', _fila(html, "captura.png"))
    assert boton and 'name="nombre"' in boton.group(0) and 'value="captura.png"' in boton.group(0)
    escrito = {}
    monkeypatch.setattr(web.entrega, "panel_apto", lambda pane_id: (True, ""))
    monkeypatch.setattr(web.tmux, "pegar_en_panel",
                        lambda pane_id, texto, enter=True: escrito.update(
                            {"pane": pane_id, "texto": texto, "enter": enter}))

    # Lo que manda el navegador: el `pane_id` del formulario y el `nombre` del botón.
    cliente.post("/intercambio/a-la-sesion", data={"pane_id": "%2", "nombre": "captura.png"},
                 follow_redirects=False)

    assert escrito["pane"] == "%2" and escrito["enter"] is False
    assert escrito["texto"].endswith("/intercambio/captura.png")


def test_borrar_desde_el_menu_pregunta_y_lleva_peligro(cliente, home):
    intercambio.guardar("viejo.txt", b"x")

    fila = _fila(cliente.get("/intercambio").text, "viejo.txt")

    boton = re.search(r'<button [^>]*form="inter-borrar"[^>]*>', fila).group(0)
    assert 'name="nombre"' in boton and 'value="viejo.txt"' in boton
    assert "peligro" in boton and "data-confirmar=" in boton
    assert 'class="menu' in fila


def test_el_selector_de_archivos_esta_en_castellano_y_admite_varios(cliente, home):
    html = cliente.get("/intercambio").text

    entrada = re.search(r'<input [^>]*type="file"[^>]*>', html).group(0)
    assert "multiple" in entrada and 'name="archivo"' in entrada
    # Sin `required`: escondido, el navegador bloquearía el envío sin decir nada.
    assert "required" not in entrada
    assert re.search(r'<label class="boton[^"]*"[^>]*>.*?Elegir archivos', html, re.S)


def test_subir_varios_a_la_vez_guarda_cada_uno_y_dice_cuantos(cliente, home):
    r = cliente.post("/intercambio/subir", files=[
        ("archivo", ("uno.txt", b"1", "text/plain")),
        ("archivo", ("dos.png", PNG, "image/png")),
    ], follow_redirects=False)

    assert (home / "intercambio/uno.txt").read_bytes() == b"1"
    assert (home / "intercambio/dos.png").read_bytes() == PNG
    aviso = unquote(r.headers["location"])
    assert "Subidos 2" in aviso and "fugaz=1" in aviso


def test_uno_que_no_cabe_no_impide_subir_los_demas(cliente, home):
    r = cliente.post("/intercambio/subir", files=[
        ("archivo", ("bueno.txt", b"1", "text/plain")),
        ("archivo", ("vacio.txt", b"", "text/plain")),
    ], follow_redirects=False)

    assert (home / "intercambio/bueno.txt").exists()
    assert not (home / "intercambio/vacio.txt").exists()
    aviso = unquote(r.headers["location"])
    assert "«vacio.txt»" in aviso and "vacío" in aviso and "Subido" in aviso
    # Se hizo lo que se pudo: el formulario puede vaciarse, que volver a
    # pulsar subiría otra vez los buenos.
    assert "hecho=1" in aviso and "fugaz" not in aviso


def test_subir_se_enciende_al_elegir_y_dice_que_se_eligio(cliente, home, tmp_path):
    """Regla dura 11: el script en línea se ejecuta. Con el campo nativo
    escondido, sin esto no se sabría qué se va a subir, y «Subir» sin nada
    elegido mandaría un formulario vacío."""
    from arnes_js import ejecutar, scripts_en_linea

    html = cliente.get("/intercambio").text
    guion = next(g for g in scripts_en_linea(html) if "inter-archivo" in g)
    r = ejecutar(guion, tmp_path, accion="""
      const e = nodo('inter-archivo'), s = nodo('inter-subir');
      registro.valores.push('al cargar: ' + s.disabled);
      e.files = [{ name: 'uno.png' }, { name: 'dos.pdf' }];
      e.disparar('change');
      registro.valores.push('elegidos: ' + s.disabled + ' ' + nodo('inter-elegidos').textContent);
    """)

    assert r["errores"] == []
    assert r["valores"] == ["al cargar: true", "elegidos: false uno.png · dos.pdf"]


# ──────────────────────── a qué subcarpeta va lo que llega ────────────────────────


def test_lo_que_llega_va_a_la_subcarpeta_del_proyecto_o_del_slot_elegido(proyecto_demo, con):
    """Lo decide `intercambio.destino` (C-0102: vivía en `api`, que es la
    costura de lectura y no decide dónde se escribe)."""
    from hub import slots

    sid = slots.crear(con, proyecto_demo, "back")
    assert intercambio.destino(con, "demo") == "demo"
    assert intercambio.destino(con, f"demo:{sid}") == f"demo/{sid}-back"
    assert intercambio.destino(con, slot_id=sid) == f"demo/{sid}-back"
    assert intercambio.destino(con, f"otro:{sid}") == intercambio.SIN_PROYECTO   # un slot no cambia de proyecto
    assert intercambio.destino(con, "no-existe") == intercambio.SIN_PROYECTO
    assert intercambio.destino(con) == intercambio.SIN_PROYECTO


def test_subir_lee_y_guarda_fuera_del_bucle_de_eventos(cliente, home, monkeypatch):
    """Tras la revisión cruzada de C-0385: la ruta era `async` y guardaba en
    síncrono, así que varios archivos grandes paraban el bucle de eventos, y
    con él la terminal. Cada archivo se guarda en un hilo aparte: ahí no hay
    bucle corriendo."""
    import asyncio

    donde, real = [], intercambio.guardar

    def guardar(*args, **kwargs):
        try:
            asyncio.get_running_loop()
            donde.append("en el bucle")
        except RuntimeError:
            donde.append("aparte")
        return real(*args, **kwargs)

    monkeypatch.setattr(intercambio, "guardar", guardar)
    cliente.post("/intercambio/subir", files=[
        ("archivo", ("uno.txt", b"1", "text/plain")),
        ("archivo", ("dos.txt", b"2", "text/plain")),
    ], follow_redirects=False)

    assert donde == ["aparte", "aparte"]
    assert (home / "intercambio/uno.txt").exists() and (home / "intercambio/dos.txt").exists()


def test_uno_que_pasa_del_tope_no_impide_subir_los_demas_y_dice_cuanto(cliente, home, monkeypatch):
    monkeypatch.setattr(intercambio, "LIMITE", 4)
    r = cliente.post("/intercambio/subir", files=[
        ("archivo", ("grande.txt", b"0123456789", "text/plain")),
        ("archivo", ("bueno.txt", b"1", "text/plain")),
    ], follow_redirects=False)

    assert (home / "intercambio/bueno.txt").exists()
    assert not (home / "intercambio/grande.txt").exists()
    aviso = unquote(r.headers["location"])
    assert "«grande.txt»: son 10 B y el límite son 4 B" in aviso and "hecho=1" in aviso
