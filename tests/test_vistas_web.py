"""Las vistas nuevas, servidas de verdad por FastAPI.

No sustituye al arnés de JavaScript —un HTTP 200 no detecta un script que
revienta al arrancar (regla dura 11)— pero sí atrapa lo que el arnés no ve:
plantillas rotas, contextos incompletos y endpoints que fallan al montarse.
"""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from hub import busqueda, db, servicios, web


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
    "ruta", ["/", "/respaldo", "/servicios", "/conexiones", "/inventario", "/contexto"]
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
