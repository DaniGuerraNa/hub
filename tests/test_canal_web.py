"""La pantalla del canal y su API.

Lo que se protege aquí es que **la web no puede saltarse la matriz**: los
endpoints son la superficie más fácil de tocar sin leer el dominio, y el fallo
que dejarían es un permiso concedido sin querer.

🔴 Y una cosa que no se ve en el código: `hub-web` **no manda nada por Telegram**.
Registra la pregunta y el relé la manda en su vuelta. Es lo que permite que el
proceso que expone el puerto —y con él una shell, regla dura 8— no tenga el
token. Si algún día un endpoint de aquí llama a `telegram.Bot`, esa separación se
ha perdido.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from hub import canal, db, web


@pytest.fixture
def cliente(tmp_path, monkeypatch):
    ruta = tmp_path / "hub.db"
    monkeypatch.setenv("HUB_CANAL_YML", str(tmp_path / "canal.yml"))

    def conexion_de_pruebas():
        con = db.conectar(ruta)
        db.inicializar(con)
        return con

    monkeypatch.setattr(web, "conexion", conexion_de_pruebas)
    con = conexion_de_pruebas()
    con.execute("INSERT INTO proyecto (id, nombre) VALUES ('contab','Contabilidad')")
    con.execute("INSERT INTO proyecto (id, nombre) VALUES ('otro','Otro')")
    canal.anotar_contacto(con, 777, "ana_t", "Ana")
    con.commit()
    con.close()
    return TestClient(web.app)


def _activar(cliente, acciones=canal.ACCIONES):
    cliente.post("/canal/usuario", data={"user_id": 777, "alias": "ana", "estado": "activo"})
    for a in acciones:
        cliente.post("/canal/permiso",
                     data={"user_id": 777, "proyecto_id": "contab", "accion": a})


def test_la_pantalla_responde_sin_canal_configurado(cliente):
    """Lo normal es no tener canal: no puede tumbar la vista."""
    r = cliente.get("/canal")
    assert r.status_code == 200
    assert "no está configurado" in r.text


def test_quien_escribio_sale_como_pendiente_y_sin_permisos(cliente):
    r = cliente.get("/canal")
    assert "pendiente" in r.text
    assert "@ana_t" in r.text


def test_conceder_y_revocar_una_accion_concreta(cliente):
    _activar(cliente, acciones=["responder"])
    r = cliente.get("/canal")
    # El NOMBRE del proyecto y no su id: es lo que se lee de un vistazo cuando
    # hay varios, y equivocarse aquí es conceder sobre otro. Va UNA vez, como
    # cabecera del grupo, y las acciones cuelgan de ella — antes se repetía en
    # cada chip y quince chips seguidos había que leerlos uno a uno.
    assert "Contabilidad" in r.text
    assert r.text.count("Contabilidad</span>") == 1
    for accion in canal.ACCIONES:
        assert f">\n                {accion}\n" in r.text or f">{accion}<" in r.text \
            or accion in r.text

    cliente.post("/canal/permiso", data={
        "user_id": 777, "proyecto_id": "contab", "accion": "responder", "quitar": "1"
    })
    con = web.conexion()
    try:
        assert canal.puede(con, 777, "contab", "responder") is False
    finally:
        con.close()


def test_una_accion_inventada_no_pasa_por_la_web(cliente):
    """La lista cerrada tiene que serlo también desde fuera."""
    r = cliente.post("/canal/permiso", data={
        "user_id": 777, "proyecto_id": "contab", "accion": "enviar-prompt"
    }, follow_redirects=False)
    assert r.status_code == 303
    assert "error=" in r.headers["location"]

    con = web.conexion()
    try:
        assert canal.permisos_de(con, 777) == []
    finally:
        con.close()


def test_no_se_pregunta_a_quien_no_tiene_permiso(cliente):
    """El endpoint no puede ser una puerta lateral a la matriz."""
    cliente.post("/canal/usuario", data={"user_id": 777, "alias": "ana", "estado": "activo"})
    r = cliente.post("/api/pregunta", json={
        "proyecto_id": "contab", "texto": "¿lleva IVA?", "a": "ana"
    })
    assert r.json()["ok"] is False


def test_un_destinatario_desconocido_se_dice_por_su_nombre(cliente):
    """«no se pudo» no se puede arreglar; «no conozco a X» sí."""
    r = cliente.post("/api/pregunta", json={
        "proyecto_id": "contab", "texto": "¿?", "a": "quiensea"
    })
    assert r.json()["ok"] is False
    assert "quiensea" in r.json()["error"]


def test_se_pregunta_por_alias_y_no_por_id(cliente):
    """Un id de quince cifras se acaba copiando mal, y aquí equivocarse es
    mandarle la pregunta a otra persona."""
    _activar(cliente)
    r = cliente.post("/api/pregunta", json={
        "proyecto_id": "contab", "texto": "¿lleva IVA?", "a": "ana", "pane_id": "%7"
    })
    datos = r.json()
    assert datos["ok"] is True
    assert datos["pregunta"]["user_id"] == 777
    assert datos["pregunta"]["estado"] == "pendiente"   # la manda el relé, no la web


def test_la_pregunta_para_el_dueno_no_lleva_destinatario(cliente):
    r = cliente.post("/api/pregunta", json={
        "proyecto_id": "contab", "texto": "¿migramos a decimal?", "a": "mi"
    })
    assert r.json()["pregunta"]["user_id"] is None
    assert "dueño" in r.json()["para"]


def test_ver_una_pregunta_que_no_existe_no_es_un_500(cliente):
    assert cliente.get("/api/pregunta/999").json()["ok"] is False


def test_el_registro_guarda_lo_que_se_concedio(cliente):
    """La monitorización que se pidió: poder decir después qué pasó."""
    _activar(cliente, acciones=["responder"])
    assert "concedido responder" in cliente.get("/canal").text


def test_los_permisos_se_agrupan_por_proyecto(cliente):
    """🔴 Pedido el 2026-09-02, y era un problema de forma, no de información.

    Cada chip decía de qué proyecto era, así que el dato estaba; pero una
    persona con permisos en cinco proyectos son quince chips seguidos y hay que
    LEER cada etiqueta para saber dónde estás. La agrupación hace ese trabajo.
    """
    _activar(cliente, acciones=["responder"])
    texto = cliente.get("/canal").text

    assert "permiso-proy" in texto, "no hay grupo por proyecto"
    # El nombre del proyecto aparece una sola vez por persona, como cabecera.
    assert texto.count('class="proy-nombre">Contabilidad</span>') == 1
    # Y las tres acciones siguen ahí, sin el nombre repetido dentro del chip.
    assert "Contabilidad · responder" not in texto


# ── el registro: filtros y paginado ───────────────────────────────────────────
#
# Este registro crece y NO se poda: es la auditoría de lo que sale de la
# máquina, así que borrarlo sería quitarse la única prueba de qué se envió. Y
# uno que sólo se puede mirar entero deja de mirarse en cuanto tiene mil líneas.


def _ruido(n=95):
    con = web.conexion()
    try:
        for i in range(n):
            canal.registrar(con, "sale" if i % 2 else "falla", f"evento {i}")
        con.commit()
    finally:
        con.close()


def test_el_registro_se_pagina(cliente):
    _ruido()
    primera = cliente.get("/canal").text
    segunda = cliente.get("/canal?pag=2").text

    assert "página 1 de" in primera
    assert "evento 94" in primera and "evento 94" not in segunda
    assert "evento 40" in segunda


def test_filtrar_por_direccion_deja_fuera_lo_demas(cliente):
    _ruido()
    solo_fallos = cliente.get("/canal?dir=falla").text

    # Los pares son `falla` y los impares `sale` (i % 2 en el generador).
    assert "evento 93" not in solo_fallos     # impar: era `sale`
    assert "evento 94" in solo_fallos         # par: `falla`
    assert "evento 92" in solo_fallos
    assert "(filtrado)" in solo_fallos


def test_el_filtro_sobrevive_al_paginado(cliente):
    """Perder el filtro al pasar de página es la forma más rápida de que nadie
    use el paginado."""
    _ruido()
    pagina2 = cliente.get("/canal?dir=falla&pag=2").text
    assert "dir=falla" in pagina2, "el enlace de página pierde el filtro"
    assert "evento 93" not in pagina2   # impar: `sale`, no debería estar nunca


def test_un_filtro_sin_resultados_lo_dice(cliente):
    _ruido()
    vacio = cliente.get("/canal?quien=99999").text
    assert "Nada que case con ese filtro" in vacio


def test_sin_una_sola_pagina_extra_no_se_pinta_el_paginado(cliente):
    """Un «1 de 1» permanente es ruido que enseña a no mirar ahí."""
    assert "página 1 de" not in cliente.get("/canal").text


# ── la pantalla se navega, no se recorre ──────────────────────────────────────
#
# Pedido el 2026-09-02: tres cosas distintas viven aquí —a quién dejas entrar,
# qué se preguntó, y todo lo que ha pasado— y una debajo de otra son cuatro
# pantallas de scroll. Mismo índice que la ficha de proyecto y el inventario.


def test_el_indice_y_las_secciones_cuadran(cliente):
    """El índice y las secciones se escriben en sitios distintos de la
    plantilla. Un `{% if %}` mal cerrado deja una entrada apuntando a una
    sección que no se renderizó: el enlace no hace nada y la página se queda en
    blanco sin ningún error."""
    import re

    cuerpo = cliente.get("/canal").text
    del_indice = set(re.findall(r'data-sec="([a-z]+)"', cuerpo))
    presentes = set(re.findall(r'<section class="seccion" id="sec-([a-z]+)"', cuerpo))
    assert del_indice == presentes == {"personas", "preguntas", "registro"}
    assert cuerpo.count("</section>") == len(presentes)


def test_quien_acaba_de_escribir_se_ve_desde_el_indice(cliente):
    """Es lo único de esta pantalla que pide una acción tuya, y con las
    secciones conmutadas puede estar en la que no estás mirando."""
    cuerpo = cliente.get("/canal").text
    assert "1 nuevo" in cuerpo


# ── los permisos, plegados ────────────────────────────────────────────────────


def test_los_permisos_llegan_PLEGADOS(cliente):
    """🔴 Doce proyectos por tres acciones son 36 mandos por persona. Se
    conceden una vez y se revisan de tarde en tarde, así que su estado normal
    es cerrado: lo que se mira a diario quedaba debajo de esa rejilla."""
    _activar(cliente, acciones=["responder"])
    cuerpo = cliente.get("/canal").text

    assert "plegado-permisos" in cuerpo
    # `<details>` SIN `open`: si se le escapara el atributo, se abriría solo y
    # el plegado no serviría de nada.
    assert "<details class=\"plegado-permisos\" open" not in cuerpo
    assert "plegado-permisos" in cuerpo and " open>" not in cuerpo


def test_el_resumen_dice_lo_que_esconde(cliente):
    """Un plegado que no cuenta lo que hay dentro obliga a abrirlo para saber
    si hace falta abrirlo."""
    _activar(cliente, acciones=["responder", "leer-estado"])
    # Espacios colapsados: el resumen se escribe en varias líneas de plantilla y
    # comprobar el HTML crudo probaría el sangrado, no el texto.
    cuerpo = " ".join(cliente.get("/canal").text.split())
    assert "2 permisos en 1 proyecto" in cuerpo
    assert "Contabilidad" in cuerpo


def test_a_quien_no_tiene_ninguno_se_le_dice(cliente):
    """«Sin permisos» no es lo mismo que un plegado vacío: lo segundo se lee
    como que no se ha cargado."""
    assert "Sin ningún permiso" in cliente.get("/canal").text


# ── filtrar preguntas ─────────────────────────────────────────────────────────


def _sec(cuerpo, nombre):
    """El trozo de UNA sección.

    Buscar en la página entera no vale: el registro guarda el texto de cada
    pregunta que se crea, así que «no aparece» era cierto en la lista de
    preguntas y falso en la página — y el test acusaba al filtro de no filtrar.
    """
    i = cuerpo.index(f'id="sec-{nombre}"')
    return cuerpo[i:cuerpo.index("</section>", i)]


def _preguntar(cliente, texto, respuesta="", estado=None):
    cliente.post("/api/pregunta", json={
        "proyecto_id": "contab", "texto": texto, "a": "ana", "pane_id": "%7"})
    con = web.conexion()
    try:
        pid = con.execute("SELECT MAX(id) FROM canal_pregunta").fetchone()[0]
        if respuesta or estado:
            con.execute("UPDATE canal_pregunta SET respuesta=?, estado=? WHERE id=?",
                        (respuesta, estado or "pendiente", pid))
        con.commit()
    finally:
        con.close()


def test_pendientes_deja_fuera_las_contestadas(cliente):
    _activar(cliente)
    _preguntar(cliente, "la que espera")
    _preguntar(cliente, "la contestada", respuesta="sí", estado="entregada")

    preguntas = _sec(cliente.get("/canal?psit=pendientes").text, "preguntas")
    assert "la que espera" in preguntas
    assert "la contestada" not in preguntas


def test_contestada_es_TENER_respuesta_no_estar_en_un_estado(cliente):
    """🔴 Los estados describen el TRANSPORTE: `entregada` dice que llegó al
    panel y `sin-confirmar` que se escribió sin poder confirmarlo. Filtrar por
    ellos dejaría fuera respuestas que existen — y `sin-confirmar` es justo la
    que hay que poder revisar."""
    _activar(cliente)
    _preguntar(cliente, "escrita sin confirmar", respuesta="contestó igual",
               estado="sin-confirmar")

    preguntas = _sec(cliente.get("/canal?psit=contestadas").text, "preguntas")
    assert "escrita sin confirmar" in preguntas


def test_una_situacion_inventada_no_se_cuela_en_el_SQL(cliente):
    """🔴 Lo que llega es texto de una URL. Concatenarlo sería dejar escribir
    SQL desde la barra de direcciones."""
    _activar(cliente)
    _preguntar(cliente, "la única")
    r = cliente.get("/canal?psit=x')+OR+1=1+--")
    assert r.status_code == 200
    # El filtro basura se ignora, no rompe nada ni vacía la lista.
    assert "la única" in _sec(r.text, "preguntas")


def test_filtrar_preguntas_no_borra_el_filtro_del_registro(cliente):
    """Las dos secciones filtran por la misma URL: sin arrastrar los del otro,
    tocar uno vacía el otro en silencio."""
    _activar(cliente)
    cuerpo = cliente.get("/canal?dir=falla&psit=pendientes").text
    assert 'name="dir" value="falla"' in cuerpo, "el form de preguntas pierde el del registro"
    assert 'name="psit" value="pendientes"' in cuerpo, "el del registro pierde el de preguntas"


def test_el_paginado_conserva_los_DOS_filtros(cliente):
    _ruido()
    cuerpo = cliente.get("/canal?dir=falla&psit=pendientes").text
    assert "dir=falla" in cuerpo and "psit=pendientes" in cuerpo


# ── los filtros no se comen la pantalla ───────────────────────────────────────


def test_los_filtros_van_DENTRO_del_embudo(cliente):
    """🔴 Pedido el 2026-09-02: eran tres `<select>` sueltos encima de la tabla,
    y como todo campo del sistema mide `width:100%`, cada uno se comía una línea
    entera para elegir una palabra."""
    cuerpo = cliente.get("/canal").text
    assert "menu filtro" in cuerpo, "no está el embudo"
    assert "pop-filtro" in cuerpo, "el formulario no está dentro del desplegable"
    assert 'class="fila filtros-reg"' not in cuerpo, "quedó la fila de selects sueltos"


def test_lo_que_hay_filtrado_se_ve_SIN_abrir_el_desplegable(cliente):
    """Un filtro que sólo se ve al abrirlo se olvida, y entonces una lista
    recortada se lee como la lista entera."""
    _ruido()
    cuerpo = cliente.get("/canal?dir=falla").text
    assert 'class="chip-filtro"' in cuerpo
    # Y el contador sobre el propio embudo, que se ve aun cerrado.
    assert 'class="cuenta-filtro"' in cuerpo


def test_sin_filtros_no_hay_ni_chips_ni_contador(cliente):
    """El adorno permanente enseña a no mirar ahí."""
    # Con `class="`: los dos nombres viven también en el CSS de la página, y
    # buscarlos a secas encontraba la hoja de estilos y no un chip pintado.
    cuerpo = cliente.get("/canal").text
    assert 'class="chip-filtro"' not in cuerpo
    assert 'class="cuenta-filtro"' not in cuerpo


def test_la_pregunta_dice_a_QUIEN_se_le_hizo_no_su_id(cliente):
    """Un número de diez cifras no dice a quién se preguntó, y es el mismo
    criterio con el que se pregunta (`--a ana`)."""
    _activar(cliente)
    _preguntar(cliente, "¿lleva IVA?")
    preguntas = _sec(cliente.get("/canal").text, "preguntas")
    assert "ana" in preguntas
    assert "777" not in preguntas
