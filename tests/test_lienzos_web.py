"""Los endpoints de lienzos: publicar, listar, buscar, editar y borrar."""

from __future__ import annotations

import os

import pytest
from fastapi.testclient import TestClient

from hub import lienzos, web


@pytest.fixture
def cliente():
    return TestClient(web.app)


def _publicar(cliente, **cambios):
    cuerpo = dict(proyecto_id="pedidos", titulo="Flujo de pedidos",
                  plantilla="arquitectura", slot="diseño", cuerpo="piezas: []\n")
    cuerpo.update(cambios)
    return cliente.post("/api/lienzo", json=cuerpo)


def _envejecer(proyecto_id, lienzo_id, segundos=600):
    ruta = lienzos.leer(proyecto_id, lienzo_id).ruta
    marca = os.stat(ruta).st_mtime + segundos
    os.utime(ruta, (marca, marca))


# ─────────────────────────── publicar ───────────────────────────────────────


def test_publicar_devuelve_el_id_para_que_claude_pueda_decirtelo(cliente):
    r = _publicar(cliente)
    assert r.status_code == 200
    ficha = r.json()["lienzo"]
    assert ficha["id"] == "flujo-de-pedidos"
    assert ficha["plantilla"] == "arquitectura"
    assert ficha["slot"] == "diseño"
    # Recién publicado, no puede figurar como editado por el usuario.
    assert ficha["tuyo"] is False


def test_publicar_sin_titulo_es_400_y_no_deja_archivo(cliente):
    r = _publicar(cliente, titulo="")
    assert r.status_code == 400
    assert lienzos.listar("pedidos") == []


def test_publicar_encima_de_tu_edicion_da_409_y_no_pisa(cliente):
    """🔴 409 y no 400: no es una petición mal hecha, es un conflicto con algo
    tuyo. Y el agente que lo lea tiene que poder decidir sin preguntar dos veces,
    así que el mensaje trae las dos salidas."""
    _publicar(cliente)
    _envejecer("pedidos", "flujo-de-pedidos")

    r = _publicar(cliente, cuerpo="lo que él regenera\n")

    assert r.status_code == 409
    assert r.json()["conflicto"] is True
    assert "--revisar" in r.json()["error"]
    assert lienzos.leer("pedidos", "flujo-de-pedidos").cuerpo == "piezas: []\n"


def test_con_revisar_se_publica_al_lado(cliente):
    _publicar(cliente)
    _envejecer("pedidos", "flujo-de-pedidos")

    r = _publicar(cliente, cuerpo="la nueva\n", revisar=True)

    assert r.status_code == 200
    assert r.json()["lienzo"]["id"] == "flujo-de-pedidos-2"
    assert lienzos.leer("pedidos", "flujo-de-pedidos").cuerpo == "piezas: []\n"


def test_republicar_lo_que_nadie_toco_no_molesta(cliente):
    """CONTROL NEGATIVO del 409: si saltara siempre, se aprendería a forzarlo."""
    _publicar(cliente)
    assert _publicar(cliente, cuerpo="v2\n").status_code == 200


# ─────────────────────────── listar y buscar ────────────────────────────────


def test_listar_devuelve_los_del_proyecto(cliente):
    _publicar(cliente)
    _publicar(cliente, titulo="Contratos", plantilla="comparativa")

    fichas = cliente.get("/api/lienzos?proyecto=pedidos").json()["lienzos"]
    assert {f["id"] for f in fichas} == {"flujo-de-pedidos", "contratos"}
    # El listado no lleva cuerpo: son fichas para pintar una lista.
    assert "cuerpo" not in fichas[0]


def test_sin_proyecto_ni_consulta_no_devuelve_el_mundo_entero(cliente):
    _publicar(cliente)
    assert cliente.get("/api/lienzos").json()["lienzos"] == []


def test_buscar_cruza_proyectos_porque_para_eso_sirve(cliente):
    _publicar(cliente)
    _publicar(cliente, proyecto_id="estudio", titulo="Orden SQL", plantilla="pasos")

    fichas = cliente.get("/api/lienzos?q=orden").json()["lienzos"]
    assert [f["id"] for f in fichas] == ["orden-sql"]
    assert fichas[0]["proyecto_id"] == "estudio"


def test_un_proyecto_con_ruta_maliciosa_es_400_y_no_sale_de_la_carpeta(cliente):
    r = cliente.get("/api/lienzos?proyecto=../../etc")
    assert r.status_code == 400


# ─────────────────────────── leer, editar, borrar ───────────────────────────


def test_leer_trae_el_cuerpo_que_es_lo_que_claude_relee(cliente):
    _publicar(cliente)
    ficha = cliente.get("/api/lienzo/pedidos/flujo-de-pedidos").json()["lienzo"]
    assert ficha["cuerpo"] == "piezas: []\n"


def test_leer_lo_que_no_existe_es_404_y_no_un_500(cliente):
    assert cliente.get("/api/lienzo/pedidos/no-esta").status_code == 404


def test_guardar_tu_edicion_no_reinicia_la_marca_de_publicacion(cliente):
    """Si la refrescara, la señal que protege tu trabajo se borraría al usarla."""
    publicado = _publicar(cliente).json()["lienzo"]["publicado_en"]

    r = cliente.post("/api/lienzo/pedidos/flujo-de-pedidos",
                     json={"cuerpo": "lo que yo escribí\n"})

    assert r.status_code == 200
    ficha = cliente.get("/api/lienzo/pedidos/flujo-de-pedidos").json()["lienzo"]
    assert ficha["publicado_en"] == publicado
    assert ficha["cuerpo"] == "lo que yo escribí\n"


def test_editar_y_luego_republicar_choca_el_ciclo_entero(cliente):
    """El recorrido real de punta a punta: publica, editas, e intenta regenerar."""
    _publicar(cliente)
    cliente.post("/api/lienzo/pedidos/flujo-de-pedidos", json={"cuerpo": "mío\n"})
    _envejecer("pedidos", "flujo-de-pedidos")

    assert _publicar(cliente, cuerpo="suyo\n").status_code == 409
    assert cliente.get("/api/lienzo/pedidos/flujo-de-pedidos").json()["lienzo"]["cuerpo"] == "mío\n"


def test_borrar_lo_quita_y_repetirlo_es_404(cliente):
    _publicar(cliente)
    assert cliente.delete("/api/lienzo/pedidos/flujo-de-pedidos").status_code == 200
    assert cliente.delete("/api/lienzo/pedidos/flujo-de-pedidos").status_code == 404
    assert lienzos.listar("pedidos") == []


def test_publicar_desde_otro_sitio_web_se_rechaza(cliente):
    """El middleware de mismo origen también cubre esto: publicar es escribir."""
    r = cliente.post("/api/lienzo", json={"proyecto_id": "pedidos", "titulo": "X"},
                     headers={"Origin": "https://ajeno.example"})
    assert r.status_code == 403
    assert lienzos.listar("pedidos") == []


# ── archivar por HTTP ─────────────────────────────────────────────────────────


def test_archivar_y_desarchivar_de_punta_a_punta(cliente):
    cliente.post("/api/lienzo", json={"proyecto_id": "demo", "titulo": "Uno",
                                      "cuerpo": "a: 1\n"})

    r = cliente.post("/api/lienzo/demo/uno/archivar", json={"archivar": True})
    assert r.status_code == 200 and r.json()["ok"]

    assert cliente.get("/api/lienzos?proyecto=demo").json()["lienzos"] == []
    archivados = cliente.get("/api/lienzos?proyecto=demo&archivados=1").json()["lienzos"]
    assert [l["id"] for l in archivados] == ["uno"]
    assert archivados[0]["archivado_en"]

    cliente.post("/api/lienzo/demo/uno/archivar", json={"archivar": False})
    assert [l["id"] for l in cliente.get("/api/lienzos?proyecto=demo").json()["lienzos"]] == ["uno"]


def test_archivar_algo_que_no_existe_da_404(cliente):
    assert cliente.post("/api/lienzo/demo/fantasma/archivar", json={}).status_code == 404


def test_un_id_invalido_no_sale_de_la_carpeta(cliente):
    """La ruta la compone el id: sin validar, `../../` escribe fuera."""
    r = cliente.post("/api/lienzo/demo/..%2F..%2Fetc/archivar", json={})
    assert r.status_code in (400, 404)
