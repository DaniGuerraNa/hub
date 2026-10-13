"""Las vistas nuevas, servidas de verdad por FastAPI.

No sustituye al arnés de JavaScript —un HTTP 200 no detecta un script que
revienta al arrancar (regla dura 11)— pero sí atrapa lo que el arnés no ve:
plantillas rotas, contextos incompletos y endpoints que fallan al montarse.
"""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from hub import busqueda, db, servicios, tmux, web


@pytest.fixture
def cliente(tmp_path, monkeypatch):
    """Una app apuntando a una base de pruebas, sin tocar la real."""
    ruta = tmp_path / "hub.db"

    def conexion_de_pruebas():
        con = db.conectar(ruta)
        db.inicializar(con)
        return con

    monkeypatch.setattr(web, "conexion", conexion_de_pruebas)
    con = conexion_de_pruebas()
    con.execute(
        """INSERT INTO proyecto (id, nombre, asiento, estado_ref)
           VALUES ('demo','Demo','/tmp/demo','ESTADO.md')"""
    )
    con.execute(
        """INSERT INTO repo (proyecto_id, ruta, rama, sin_push, regimen, sucios,
                             worktrees, repo_comun, head, medido_en)
           VALUES ('demo','/tmp/demo','dev',250,'sin-upstream',0,1,'/tmp/demo/.git','abc','2026-08-28')"""
    )
    con.execute(
        """INSERT INTO servicio (contenedor, proyecto_id, imagen, estado, detalle, medido_en)
           VALUES ('demo-postgres','demo','pg','running','Up 2h','2026-08-28')"""
    )
    con.execute(
        """INSERT INTO servicio (contenedor, proyecto_id, imagen, estado, detalle, medido_en)
           VALUES ('huerfano','','x','exited','Exited','2026-08-28')"""
    )
    con.execute(
        """INSERT INTO conexion (alias, host, proposito, referencia_secreto, puntero_ok)
           VALUES ('vps','h','pruebas','~/.ssh/config#vps',1)"""
    )
    busqueda.reindexar(con)
    con.close()
    return TestClient(web.app)


@pytest.mark.parametrize(
    "ruta", ["/", "/respaldo", "/servicios", "/conexiones", "/inventario",
             "/contexto", "/consumo"]
)
def test_todas_las_vistas_responden(cliente, ruta):
    assert cliente.get(ruta).status_code == 200


def test_el_respaldo_muestra_los_commits_en_riesgo(cliente):
    cuerpo = cliente.get("/respaldo").text
    assert "250" in cuerpo and "sin push" in cuerpo


def test_el_panorama_avisa_de_lo_que_no_esta_respaldado(cliente):
    """Es el hallazgo que originó el hub: va arriba del todo, no escondido."""
    assert "250 commits sin respaldo" in cliente.get("/").text


def test_los_servicios_marcan_lo_que_no_tiene_dueno(cliente):
    cuerpo = cliente.get("/servicios").text
    assert "huerfano" in cuerpo and "sin dueño" in cuerpo


def test_las_conexiones_avisan_de_que_nunca_se_guarda_el_secreto(cliente):
    assert "nunca guarda el secreto" in cliente.get("/conexiones").text


def test_la_vista_de_proyecto_trae_estado_capa_repos_y_servicios(cliente):
    cuerpo = cliente.get("/proyecto/demo").text
    assert "sin capa base" in cuerpo
    assert "demo-postgres" in cuerpo
    assert "250" in cuerpo


def test_cada_entrada_del_indice_de_proyecto_tiene_su_seccion(cliente):
    """El índice y las secciones se escriben en sitios distintos de la plantilla.

    Un `{% if %}` mal cerrado deja una entrada del menú apuntando a una sección
    que no se renderizó: el enlace no hace nada y la página se queda en blanco
    sin ningún error. Aquí se comprueba que cuadran, y de paso que no sobra
    ningún `</section>`.
    """
    cuerpo = cliente.get("/proyecto/demo").text
    del_indice = set(re.findall(r'data-sec="([a-z]+)"', cuerpo))
    presentes = set(re.findall(r'<section class="seccion" id="sec-([a-z]+)"', cuerpo))
    assert del_indice == presentes
    assert cuerpo.count("</section>") == len(presentes)


def test_la_vista_de_consumo_sin_medicion_lo_dice_en_vez_de_reventar(cliente):
    """Es lo que se ve antes del primer ciclo lento, y también si `~/.claude` no
    existe. Una pantalla en blanco no distingue «todavía no» de «está roto»."""
    r = cliente.get("/consumo")
    assert r.status_code == 200
    assert "Todavía no hay ninguna medición" in r.text


def _sembrar_consumo(cliente, con_ruta, **extra):
    con = db.conectar(con_ruta)
    filas = extra.get("filas") or [
        ("demo", "/tmp/demo", "2026-08-20", "claude-opus-5", 10, 2, 300, 9000, 500),
        (None, "/tmp/suelto", "2026-08-21", "claude-opus-5", 3, 1, 100, 2000, 200),
    ]
    for f in filas:
        con.execute(
            """INSERT INTO consumo (proyecto_id, ruta, dia, modelo, peticiones,
                                    entrada, escritura, lectura, salida, razonado,
                                    razonadas, desde, hasta, medido_en)
               VALUES (?,?,?,?,?,?,?,?,?,0,0,?,?,'2026-09-10T00:00:00')""",
            (*f, f"{f[2]}T09:00:00.000Z", f"{f[2]}T21:00:00.000Z"))
    con.close()


def test_la_vista_de_consumo_pinta_la_grafica_y_las_categorias(cliente, tmp_path):
    """🔴 La gráfica es SVG servido por el servidor, sin una línea de JavaScript:
    se comprueba que los rectángulos están en el HTML. Una gráfica que sólo
    existe si arranca un script es una pantalla que se puede quedar en blanco
    sin decirlo, y eso ya pasó una vez en este hub."""
    _sembrar_consumo(cliente, tmp_path / "hub.db")
    r = cliente.get("/consumo")
    assert r.status_code == 200
    assert r.text.count("<rect") >= 2, "la gráfica no pintó ninguna columna"
    assert "var(--serie-1)" in r.text, "la rampa de tono no se está usando"
    for etiqueta in ("Dominio", "Tipo", "Estado", "Modelo"):
        assert etiqueta in r.text


def test_la_vista_de_consumo_dice_su_ventana_ANTES_que_las_cifras(cliente, tmp_path):
    """🔴 Claude Code poda a los 30 días. El aviso va encima porque debajo ya se
    han leído las cifras, y un número grande sin su ventana se lee como total."""
    _sembrar_consumo(cliente, tmp_path / "hub.db")
    texto = cliente.get("/consumo").text
    assert texto.index("no el histórico") < texto.index("peticiones a la API")


def test_la_vista_de_consumo_no_habla_de_dinero(cliente, tmp_path):
    """Regla dura 13: la tabla de precios cambia sola y no se puede verificar."""
    _sembrar_consumo(cliente, tmp_path / "hub.db")
    texto = cliente.get("/consumo").text
    for moneda in ("€", "USD", "$", "coste estimado"):
        assert moneda not in texto


def test_la_ficha_de_un_proyecto_trae_su_consumo_con_su_parte_del_total(
    cliente, tmp_path
):
    """Es lo que se pidió: verlo en los proyectos, no sólo en su pantalla."""
    _sembrar_consumo(cliente, tmp_path / "hub.db")
    r = cliente.get("/proyecto/demo")
    assert r.status_code == 200
    assert "de todo lo gastado" in r.text
    assert "<rect" in r.text
    # La ventana también aquí: quien entra por la ficha no pasó por /consumo.
    assert "poda su registro" in r.text


def test_un_proyecto_sin_consumo_no_ofrece_esa_seccion(cliente):
    """Igual que repos y servicios: una sección vacía es ruido con forma de dato."""
    assert "de todo lo gastado" not in cliente.get("/proyecto/demo").text


def test_el_indice_y_las_secciones_cuadran_TAMBIEN_con_consumo(cliente, tmp_path):
    """🔴 El test de arriba corre sobre un proyecto sin consumo, así que la
    entrada nueva del índice no llegaba a renderizarse y no se comprobaba nada de
    ella. El caso que hay que cubrir es justo el que la enseña: el índice y la
    sección se escriben a 100 líneas de distancia en la misma plantilla, y un
    `{% if %}` con condición distinta en cada sitio deja un enlace que no lleva a
    ninguna parte y no da ningún error."""
    _sembrar_consumo(cliente, tmp_path / "hub.db")
    cuerpo = cliente.get("/proyecto/demo").text
    del_indice = set(re.findall(r'data-sec="([a-z]+)"', cuerpo))
    presentes = set(re.findall(r'<section class="seccion" id="sec-([a-z]+)"', cuerpo))
    assert "consumo" in del_indice
    assert del_indice == presentes
    assert cuerpo.count("</section>") == len(presentes)


def test_un_proyecto_sin_repos_ni_servicios_no_ofrece_esas_secciones(cliente):
    """Un menú con entradas muertas es peor que un menú corto."""
    con = web.conexion()
    con.execute("INSERT INTO proyecto (id, nombre) VALUES ('pelado','Pelado')")
    con.commit()
    cuerpo = cliente.get("/proyecto/pelado").text
    assert set(re.findall(r'data-sec="([a-z]+)"', cuerpo)) == {"estado", "paneles", "slots"}


def test_la_busqueda_devuelve_destinos(cliente):
    datos = cliente.get("/api/buscar?q=demo").json()
    assert any(r["url"] == "/proyecto/demo" for r in datos)


def test_la_busqueda_acota_el_limite_que_llega_por_la_url(cliente):
    """Un `limite` de la URL es entrada de usuario: no puede pedir 10 000 filas."""
    assert cliente.get("/api/buscar?q=demo&limite=99999").status_code == 200
    assert cliente.get("/api/buscar?q=demo&limite=-5").status_code == 200


def test_la_api_de_lectura_expone_lo_mismo_que_la_ui(cliente):
    """Decisión 25: el futuro MCP se monta sobre esto, no sobre las plantillas."""
    assert cliente.get("/api/respaldo").json()["commits_sin_respaldo"] == 250
    assert cliente.get("/api/servicios").json()["total"] == 2
    assert cliente.get("/api/conexiones").json()[0]["alias"] == "vps"
    assert "campos" in cliente.get("/api/estado/demo").json()


def test_una_accion_de_docker_no_permitida_se_rechaza_con_mensaje(cliente):
    respuesta = cliente.post(
        "/api/servicio/accion", json={"contenedor": "demo-postgres", "accion": "rm"}
    ).json()
    assert respuesta["ok"] is False and "no permitida" in respuesta["error"]


def test_parar_un_contenedor_llega_a_docker_con_su_nombre_exacto(cliente, monkeypatch):
    """Nunca en lote y nunca por patrón: un `docker stop $(docker ps -q)` es el
    accidente que esta pantalla existe para prevenir."""
    llamadas = []
    monkeypatch.setattr(servicios, "accionar", lambda c, a: llamadas.append((c, a)))
    monkeypatch.setattr(servicios, "escanear", lambda con, p: 0)

    respuesta = cliente.post(
        "/api/servicio/accion", json={"contenedor": "demo-postgres", "accion": "stop"}
    ).json()
    assert respuesta["ok"] is True
    assert llamadas == [("demo-postgres", "stop")]


def test_el_contexto_se_sirve_tambien_en_crudo_para_pegarlo(cliente):
    """La costura del asistente y del MCP: el mismo dato, sin plantilla."""
    respuesta = cliente.get("/api/contexto?formato=md")
    assert respuesta.status_code == 200
    assert "# Estado del sistema" in respuesta.text
    assert cliente.get("/api/contexto").json()["respaldo"]["commits_sin_respaldo"] == 250


def test_la_paleta_esta_disponible_en_todas_las_pantallas(cliente):
    """Vive en `base.html` porque su valor está en responder desde cualquier sitio."""
    for ruta in ("/", "/respaldo", "/servicios", "/inventario"):
        assert "/static/paleta.js" in cliente.get(ruta).text


# ── el latido de la vista de trabajo ──────────────────────────────────────────

def test_el_pulso_responde_sin_notas_que_pedir(cliente):
    """La página lo llama en cada vuelta, también cuando no hay ninguna nota."""
    r = cliente.get("/api/trabajo/pulso")
    assert r.status_code == 200
    assert r.json() == {"slots": {}, "notas": {}}


def test_el_pulso_ignora_lo_que_no_sea_un_id(cliente):
    """`notas` viene de la URL. Aunque lo escriba la propia página, no se pasa
    a una consulta sin mirarlo."""
    r = cliente.get("/api/trabajo/pulso?notas=1,,x,'; DROP TABLE slot;--,2")
    assert r.status_code == 200
    assert r.json()["notas"] == {}  # ninguno de esos slots existe
    assert cliente.get("/api/trabajo/pulso").status_code == 200


def test_lanzar_un_slot_sin_tmux_lo_dice_en_pantalla(cliente, monkeypatch):
    """Regla dura 21: lo que falla en tmux se dice, no se traga."""
    from hub import slots, tmux

    def revienta(*a, **k):
        raise tmux.TmuxNoDisponible("error connecting to /tmp/tmux-1000/default")

    monkeypatch.setattr(slots, "abrir", revienta)
    r = cliente.post("/slot/1/abrir", data={"proyecto_id": "demo", "destino": "/trabajo?slot=1"},
                     follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"].startswith("/trabajo?slot=1&aviso=")
    pagina = cliente.get(r.headers["location"])
    assert "No se pudo abrir la ventana" in pagina.text
    assert "error connecting" in pagina.text


# ── un slot sin ventana no toma prestada la terminal de otro ──────────────────
#
# Lo vio él, y es el mismo defecto que el de la bandeja por otra puerta: *«test2
# está en sin organizar pero también está en personal-test en test-formato»*.
#
# La vista tenía un respaldo —«si no hay sesión, enseña la primera que haya»—
# pensado para entrar a /trabajo sin pedir nada. Con un slot pedido a mano y sin
# ventana abierta también se disparaba: la barra decía «test-formato» y debajo
# corría la terminal de `114`, una ventana suelta de otra carpeta. Y como esa
# misma ventana sale en la bandeja como no vinculada, acababa en dos sitios a la
# vez diciendo cosas contrarias.

@pytest.fixture
def cliente_con_tmux(cliente, monkeypatch):
    """Hay tmux y hay sesiones, pero ninguna es de este slot."""
    from hub import terminal

    monkeypatch.setattr(
        terminal, "sesiones_disponibles",
        lambda: [{"session": "114", "paneles": 1}, {"session": "otra", "paneles": 1}],
    )
    monkeypatch.setattr(web, "_ventana_activa", lambda s: 0)
    # Un slot de verdad y sin ninguna ventana: es el caso entero.
    con = web.conexion()
    con.execute(
        """INSERT INTO slot (id, proyecto_id, nombre, ruta, status, creado_en)
           VALUES (1,'demo','test-formato','/tmp/demo','activo','2026-09-08')"""
    )
    con.commit()
    con.close()
    return cliente


def _sesion_que_carga(html: str) -> str:
    return re.search(r"const SESION = (\"[^\"]*\"|null);", html).group(1)


def test_un_slot_sin_ventana_no_carga_la_sesion_de_otro(cliente_con_tmux):
    """🔴 El defecto: la barra decía un slot y la terminal era de otra cosa."""
    html = cliente_con_tmux.get("/trabajo?slot=1").text
    assert _sesion_que_carga(html) == '""'
    assert '"114"' not in _sesion_que_carga(html)


def test_un_slot_sin_ventana_lo_dice_y_ofrece_abrirla(cliente_con_tmux):
    """No basta con no mentir: el hueco necesita salida, o es una pantalla muerta."""
    html = cliente_con_tmux.get("/trabajo?slot=1").text
    assert '<div class="slot-vacio">' in html
    assert "no tiene ninguna ventana abierta" in html
    assert 'action="/slot/1/abrir"' in html


def test_entrar_sin_pedir_nada_sigue_enseñando_la_primera_sesion(cliente_con_tmux):
    """El respaldo sigue valiendo donde se escribió: sin slot no hay qué mentir."""
    html = cliente_con_tmux.get("/trabajo").text
    assert _sesion_que_carga(html) == '"114"'
    assert '<div class="slot-vacio">' not in html


def test_una_sesion_pedida_a_mano_se_respeta(cliente_con_tmux):
    html = cliente_con_tmux.get("/trabajo?session=otra").text
    assert _sesion_que_carga(html) == '"otra"'


def test_un_slot_que_ya_no_existe_no_deja_la_pantalla_muerta(cliente_con_tmux):
    """La página pudo quedarse abierta y el slot borrarse desde otra pestaña.

    Sin nombre en la barra no hay nada que contradecir, así que ahí el respaldo
    de enseñar la primera sesión sigue siendo lo correcto — y lo contrario sería
    una pantalla en blanco sin explicación.
    """
    html = cliente_con_tmux.get("/trabajo?slot=9999").text
    assert _sesion_que_carga(html) == '"114"'
    assert '<div class="slot-vacio">' not in html


# ── cerrar una ventana desde el raíl ──────────────────────────────────────────
#
# Petición suya: *«los sin organizar y en general cualquier ventana no permiten
# cerrarlas cuando sólo tienen una terminal, debería poder descartar lo que no
# necesito»*. Y era literal: la × de las pestañas se escondía con
# `ventanas.length > 1`, o sea justo en las sesiones de una sola ventana, que es
# la forma de casi todo lo que se acumula en la bandeja. Desde el hub no había
# ningún camino para cerrarlas.

@pytest.fixture
def con_panel(cliente, monkeypatch):
    """Un panel real en la base, para que la acción tenga de dónde sacar la ventana."""
    con = web.conexion()
    con.execute("INSERT INTO snapshot (id, tomado_en, server_pid) VALUES (1,'2026-09-08',100)")
    con.execute(
        """INSERT INTO panel (snapshot_id, pane_id, session, window_idx, pane_idx,
                              cwd, titulo, comando, etiqueta)
           VALUES (1,'%7','ctd-api',0,0,'/tmp/demo','node','node','node · dev')"""
    )
    con.commit()
    con.close()
    cerradas = []
    monkeypatch.setattr(tmux, "cerrar_ventana", lambda s, i: cerradas.append((s, i)))
    return cliente, cerradas


def test_cerrar_manda_la_sesion_y_la_ventana_del_panel(con_panel):
    """Salen del `pane_id`, no del formulario: el HTML pudo quedarse viejo y
    cerrar la ventana equivocada no tiene deshacer."""
    cliente, cerradas = con_panel
    r = cliente.post(
        "/panel/accion",
        data={"pane_id": "%7", "accion": "cerrar_ventana", "destino": "/trabajo"},
        follow_redirects=False,
    )
    assert r.status_code in (302, 303)
    assert cerradas == [("ctd-api", 0)]


def test_un_pane_que_ya_no_existe_no_cierra_nada(con_panel):
    """La bandeja pudo pintarse hace diez minutos."""
    cliente, cerradas = con_panel
    cliente.post(
        "/panel/accion",
        data={"pane_id": "%404", "accion": "cerrar_ventana", "destino": "/trabajo"},
        follow_redirects=False,
    )
    assert cerradas == []


def test_si_tmux_falla_se_dice_y_no_se_traga(con_panel, monkeypatch):
    """Regla dura 21. Un `except: pass` aquí es un botón que no hace nada."""
    cliente, _ = con_panel

    def revienta(s, i):
        raise RuntimeError("no hay servidor de tmux")

    monkeypatch.setattr(tmux, "cerrar_ventana", revienta)
    r = cliente.post(
        "/panel/accion",
        data={"pane_id": "%7", "accion": "cerrar_ventana", "destino": "/trabajo"},
        follow_redirects=False,
    )
    assert "aviso=" in r.headers["location"]
    assert "no%20se%20pudo" in r.headers["location"].lower()


# ── /inventario, filtrado por proyecto: sus kits ──────────────────────────────

def test_inventario_de_un_consumidor_lista_sus_kits(cliente):
    """Servido de verdad: que la función acierte no basta si la vista no la usa.

    Era justo el hueco — `api.kits_de` no existía y la vista filtraba por su
    cuenta comparando ids de kit con ids de proyecto.
    """
    con = web.conexion()
    con.execute("INSERT INTO proyecto (id, nombre, tipo) VALUES ('orq','Kit de orquestación','kit')")
    con.execute(
        """INSERT INTO dependencia (kit_id, consumidor_id, origen, destino, estado)
           VALUES ('orq','demo','metodo/m.md','docs/m.md','igual')"""
    )
    con.commit()
    con.close()

    html = cliente.get("/inventario?proyecto=demo&ver=kits").text
    # 🔴 Se mira la TARJETA, no el nombre suelto. La primera versión de este test
    # comprobaba `"Kit de orquestación" in html` y pasaba con el filtro roto: ese
    # nombre también sale en el desplegable de proyectos, que lista todos. Un
    # test verde que no distingue el arreglo del defecto es peor que no tenerlo.
    assert '<div class="kit-cab">' in html, "no se pintó ninguna tarjeta de kit"
    assert "<strong>Demo</strong>" in html, "la tarjeta no trae a este consumidor"


def test_un_proyecto_sin_kits_no_dice_que_no_tengas_ninguno(cliente):
    """«Todavía no tienes ningún kit» mientras hay siete sería mentir sobre el
    hub entero: lo que pasa es que ESTE proyecto no declara ninguno."""
    con = web.conexion()
    con.execute("INSERT INTO proyecto (id, nombre, tipo) VALUES ('orq','Kit','kit')")
    con.commit()
    con.close()

    html = cliente.get("/inventario?proyecto=demo&ver=kits").text
    assert "no declara ningún kit" in html
    assert "Todavía no tienes ningún kit" not in html
    assert '<div class="kit-cab">' not in html


def test_pedir_una_ventana_en_una_sesion_muerta_da_un_motivo_legible(cliente):
    """El error crudo de tmux trae la línea de comandos entera, que no es lo que
    hay que leer en un cuadro de diálogo. Y este caso es el que pasa: cerrar la
    última ventana de un slot mata la sesión."""
    r = cliente.post("/api/sesion/no-existe-esta-sesion/ventanas", json={})
    datos = r.json()
    assert datos["ok"] is False
    assert "ya no existe en tmux" in datos["error"]
    assert "new-window" not in datos["error"]


# ── Mensajes programados ────────────────────────────────────────────────────


def test_programar_un_mensaje_de_punta_a_punta(cliente):
    cliente.post("/api/slot", json={"proyecto_id": "demo", "nombre": "back",
                                    "ruta": "/tmp/demo"})
    r = cliente.post("/api/programado", json={
        "slot_id": 1, "texto": "empieza por los tests",
        "cuando": "2026-09-12T09:00:00-06:00"})
    assert r.json()["ok"] is True, r.json()

    lista = cliente.get("/api/programados").json()
    assert [m["texto"] for m in lista] == ["empieza por los tests"]
    assert lista[0]["cuando"] == "2026-09-12T15:00:00+00:00"
    assert lista[0]["slot_nombre"] == "back"


def test_una_hora_sin_zona_se_rechaza_con_su_motivo(cliente):
    """🔴 El servidor no supone la zona. Suponerla mal no da error en ninguna
    parte: da un mensaje entregado seis horas tarde."""
    cliente.post("/api/slot", json={"proyecto_id": "demo", "nombre": "back",
                                    "ruta": "/tmp/demo"})
    r = cliente.post("/api/programado", json={
        "slot_id": 1, "texto": "hola", "cuando": "2026-09-12T09:00:00"})

    datos = r.json()
    assert datos["ok"] is False and "zona horaria" in datos["error"]


def test_programar_sobre_un_slot_que_no_existe_lo_dice_sin_reventar(cliente):
    r = cliente.post("/api/programado", json={
        "slot_id": 999, "texto": "hola", "cuando": "2026-09-12T09:00:00Z"})
    datos = r.json()
    assert datos["ok"] is False and "999" in datos["error"]


def test_cancelar_dos_veces_lo_dice_en_vez_de_callar(cliente):
    cliente.post("/api/slot", json={"proyecto_id": "demo", "nombre": "back",
                                    "ruta": "/tmp/demo"})
    ident = cliente.post("/api/programado", json={
        "slot_id": 1, "texto": "hola", "cuando": "2026-09-12T09:00:00Z"}).json()["id"]

    assert cliente.post(f"/api/programado/{ident}/cancelar").json()["ok"] is True
    segunda = cliente.post(f"/api/programado/{ident}/cancelar").json()
    assert segunda["ok"] is False and "ya no estaba pendiente" in segunda["error"]
