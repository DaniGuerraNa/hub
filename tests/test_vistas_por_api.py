"""Las pantallas que armaban su vista en `web.py` la piden a `api` (C-0100).

La costura única de lectura (decisión 25) dice que todo lo que la UI enseña
sale de `api.py`: el asistente, el secretario y el futuro MCP leen por ahí, y
lo que una ruta calcula por su cuenta no lo ve ninguno de ellos. Aquí se
afirma, pantalla por pantalla, que `api` da **todo** lo que lee su plantilla:
un nombre que falte no revienta en Jinja —sale vacío— y la pantalla se sirve
en 200 diciendo que no hay nada.

La ruta se queda sólo con lo que depende de la petición (el enlace del QR,
mirar si hay versión nueva al entrar), y eso se nombra en cada test.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import arnes_plantillas as plantilla
from hub import api, db, web


@pytest.fixture
def cliente(tmp_path, monkeypatch):
    ruta = tmp_path / "hub.db"
    db.inicializar(db.conectar(ruta))

    def conexion():
        con = db.conectar(ruta)
        db.inicializar(con)
        return con

    monkeypatch.setattr(web, "conexion", conexion)
    return TestClient(web.app)


# ── actualizaciones ──────────────────────────────────────────────────────────

def test_actualizaciones_da_todo_lo_que_lee_su_plantilla():
    datos = api.actualizaciones()
    assert plantilla.nombres("actualizaciones.html") <= set(datos)
    assert plantilla.campos("actualizaciones.html", "vers") <= set(datos["vers"])
    assert plantilla.campos("actualizaciones.html", "a") <= set(datos["a"])


def test_la_pantalla_de_actualizaciones_pinta_lo_que_da_api(cliente, monkeypatch):
    """Y lo que pregunta la pantalla mientras actualiza sale del mismo sitio."""
    datos = api.actualizaciones()
    datos["vers"]["codigo"] = "77.7.7"
    datos["a"] = {**datos["a"], "registro": "paso de prueba", "en_marcha": True}
    monkeypatch.setattr(api, "actualizaciones", lambda: datos)
    monkeypatch.setattr(api, "actualizacion", lambda: datos["a"])
    monkeypatch.setenv("HUB_BUSCAR_VERSIONES", "0")
    assert "<strong>77.7.7</strong>" in cliente.get("/actualizaciones").text
    assert cliente.get("/api/actualizacion").json()["registro"] == "paso de prueba"


# ── acceso ───────────────────────────────────────────────────────────────────

def test_acceso_da_todo_lo_que_lee_su_plantilla_menos_el_qr():
    """El enlace del QR y el propio QR los arma la ruta: el nombre por el que
    va a entrar el aparato depende de por dónde se mira la pantalla."""
    from hub import acceso

    codigo = acceso.alta_pendiente("Móvil")
    assert acceso.canjear(codigo)
    otro = acceso.alta_pendiente("Tableta")
    datos = api.acceso(otro)
    assert plantilla.nombres("acceso.html") <= set(datos) | {"qr", "enlace"}
    assert plantilla.campos("acceso.html", "pendiente") <= set(datos["pendiente"])
    (aparato,) = datos["dispositivos"]
    assert plantilla.campos_de_cada("acceso.html", "dispositivos") <= set(aparato)
    assert "hash" not in aparato
    assert api.acceso()["pendiente"] is None


def test_un_acceso_yml_invalido_se_dice_en_la_pantalla_y_quedan_los_nombres_locales():
    from hub import acceso

    acceso.archivo().parent.mkdir(parents=True, exist_ok=True)
    acceso.archivo().write_text('hosts: ["*.red-privada.net"]\n', encoding="utf-8")
    datos = api.acceso()
    assert datos["error"] and tuple(datos["hosts"]) == acceso.HOSTS_LOCALES


def test_la_pantalla_de_acceso_pinta_lo_que_da_api(monkeypatch):
    datos = api.acceso()
    datos["archivo"] = "/ruta/de/prueba/acceso.yml"
    monkeypatch.setattr(api, "acceso", lambda codigo=None: datos)
    assert "/ruta/de/prueba/acceso.yml" in TestClient(web.app).get("/acceso").text


# ── máquina ──────────────────────────────────────────────────────────────────

@pytest.fixture
def con(tmp_path):
    c = db.conectar(tmp_path / "hub.db")
    db.inicializar(c)
    yield c
    c.close()


def _medir(con, monkeypatch, *medidas):
    from hub import maquina

    monkeypatch.setattr(maquina, "medir", lambda: list(medidas))
    maquina.escanear(con)


def test_maquina_da_todo_lo_que_lee_su_plantilla(con, monkeypatch):
    from hub.maquina import SOBRE_BATERIA, Medida

    _medir(con, monkeypatch, Medida("gpu.temperatura", 62), Medida("gpu.nombre", texto="GPU de prueba"),
           Medida("disco.wsl.libre", 120), Medida("disco.wsl.uso", 40),
           Medida("ups.estado", SOBRE_BATERIA), Medida("carga", 0.5))
    datos = api.maquina(con)
    assert plantilla.nombres("maquina.html") <= set(datos)
    assert plantilla.campos("maquina.html", "limites") <= set(datos["limites"])
    leidos = plantilla.campos_de_cada("maquina.html", "tarjetas")
    assert datos["tarjetas"] and all(leidos <= set(t) for t in datos["tarjetas"])
    # `arreglo` sólo lo trae lo que tiene arreglo, y la plantilla lo pregunta.
    leidos = plantilla.campos_de_cada("maquina.html", "salud") - {"arreglo"}
    assert datos["salud"] and all(leidos <= set(r) for r in datos["salud"])
    assert datos["medido_en"]


def test_urge_sale_del_mismo_limite_con_el_que_avisa_el_rele(con, monkeypatch):
    """Lo que decidía `urge` vivía en la ruta: ahora lo ve cualquiera que lea
    `api`, con los límites de `canal.yml` y no con unos propios."""
    from hub import config
    from hub.maquina import Medida

    config.canal_yml().parent.mkdir(parents=True, exist_ok=True)
    config.canal_yml().write_text("avisos:\n  temperatura: 70\n  disco: 50\n", encoding="utf-8")
    _medir(con, monkeypatch, Medida("gpu.temperatura", 72), Medida("disco.wsl.libre", 60),
           Medida("disco.windows.libre", 40), Medida("carga", 9.0))
    urge = {t["nombre"]: t["urge"] for t in api.maquina(con)["tarjetas"]}
    assert urge == {"GPU": True, "Disco de WSL": False, "Disco de Windows": True, "Carga": False}


def test_la_pantalla_de_maquina_pinta_lo_que_da_api(cliente, monkeypatch):
    monkeypatch.setattr(api, "maquina", lambda con: {
        "medidas": {"carga": {}}, "tarjetas": [{"nombre": "Cifra de prueba", "valor": "42", "unidad": "",
                                                "urge": False, "pie": "", "icono": "lineas"}],
        "medido_en": "2026-11-06T10:00:00", "limites": {"temperatura": 80, "disco": 20},
        "armadas": False, "dueno_nombre": "", "salud": []})
    assert "Cifra de prueba" in cliente.get("/maquina").text


# ── canal ────────────────────────────────────────────────────────────────────

# Lo que pone la ruta: los filtros con el nombre que llevan en la URL, para que
# la plantilla arme los enlaces que los quitan, y el error de la petición.
DE_LA_RUTA_EN_CANAL = {"preg_filtros", "reg_filtros", "error"}


def test_canal_da_todo_lo_que_lee_su_plantilla_menos_los_filtros_de_la_url(con):
    from hub import canal

    canal.anotar_contacto(con, 777, "ana_t", "Ana")
    for i in range(45):
        canal.registrar(con, "sale" if i % 2 else "falla", f"evento {i}")
    con.commit()
    datos = api.canal(con)
    assert plantilla.nombres("canal.html") <= set(datos) | DE_LA_RUTA_EN_CANAL
    for nombre in ("canal_estado", "avisos"):
        assert plantilla.campos("canal.html", nombre) <= set(datos[nombre]), nombre
    for coleccion in ("usuarios", "registro"):
        leidos = plantilla.campos_de_cada("canal.html", coleccion)
        assert datos[coleccion] and all(leidos <= set(e) for e in datos[coleccion]), coleccion
    assert (datos["reg_total"], datos["reg_paginas"]) == (canal.cuenta_registro(con), 2)


def test_el_canal_filtra_y_pagina_en_api(con):
    from hub import canal

    for i in range(45):
        canal.registrar(con, "sale" if i % 2 else "falla", f"evento {i}")
    con.commit()
    fallos = api.canal(con, direccion="falla", pagina=0)
    assert fallos["reg_pag"] == 1 and fallos["reg_total"] == 23
    assert {e["direccion"] for e in fallos["registro"]} == {"falla"}
    assert len(api.canal(con, pagina=2)["registro"]) == 45 - api.CANAL_POR_PAGINA


def test_la_pantalla_del_canal_pinta_lo_que_da_api(cliente, monkeypatch):
    original = api.canal
    vistos = []

    def espia(con, **filtros):
        vistos.append(filtros)
        datos = original(con, **filtros)
        datos["registro"] = [{"direccion": "sale", "momento": "2026-11-06T10:00:00",
                              "cuerpo": "Entrada de prueba", "detalle": ""}]
        datos["reg_total"] = 1
        return datos

    monkeypatch.setattr(api, "canal", espia)
    assert "Entrada de prueba" in cliente.get("/canal?dir=sale&pag=3&psit=pendiente").text
    assert vistos == [{"direccion": "sale", "quien": None, "proyecto": "", "pagina": 3,
                       "situacion": "pendiente", "proyecto_preguntas": ""}]


# ── encargos ─────────────────────────────────────────────────────────────────

# Una plantilla para las dos vistas: la lista y la ficha de un encargo.
DE_LA_RUTA_EN_ENCARGOS = {"reg_filtro", "error"}


@pytest.fixture
def con_encargo(con, monkeypatch, tmp_path):
    from hub import buzon, encargos

    monkeypatch.setenv("HUB_ENCARGOS_YML", str(tmp_path / "encargos.yml"))
    encargos.anotar_persona(con, 777, "tienda_t", "Tienda")
    con.execute("UPDATE encargo_persona SET estado='activo' WHERE user_id=777")
    encargos.crear(con, "tienda", 777, "La tienda")
    buzon.aparcar(con, "tienda", 777, "vendo pan")
    con.commit()
    return con


def test_encargos_da_todo_lo_que_lee_su_plantilla(con_encargo):
    lista, ficha = api.encargos(con_encargo), api.encargo(con_encargo, "tienda")
    assert plantilla.nombres("encargos.html") <= set(lista) | set(ficha) | DE_LA_RUTA_EN_ENCARGOS
    (fila,) = lista["encargos"]
    assert plantilla.campos_de_cada("encargos.html", "encargos") <= set(fila)
    assert (fila["quien"], fila["sin_entregar"]) == ("Tienda", 1)
    assert plantilla.campos_de_cada("encargos.html", "fases") <= set(ficha["fases"][0])
    assert plantilla.campos("encargos.html", "enc") <= set(ficha["enc"])
    # `transcriptor` sólo está cuando falta, y la plantilla lo pregunta.
    leidos = plantilla.campos("encargos.html", "canal_estado") - {"transcriptor"}
    for vista in (lista, ficha):
        assert leidos <= set(vista["canal_estado"])
    assert ficha["sin_entregar"] == 1 and ficha["conversacion"]
    assert [p["user_id"] for p in lista["activas"]] == [777]


def test_un_encargo_que_no_existe_es_none_y_la_ruta_vuelve_a_la_lista(con_encargo, cliente):
    assert api.encargo(con_encargo, "no-existe") is None
    r = cliente.get("/encargos/no-existe", follow_redirects=False)
    assert r.status_code in (302, 303) and "/encargos?error=" in r.headers["location"]


def test_las_pantallas_de_encargos_pintan_lo_que_da_api(con_encargo, cliente, monkeypatch):
    lista, ficha = api.encargos(con_encargo), api.encargo(con_encargo, "tienda")
    lista["encargos"][0]["titulo"] = "Encargo de la lista de prueba"
    ficha["siguiente"] = "Fase de prueba"
    monkeypatch.setattr(api, "encargos", lambda con, filtro="": lista)
    monkeypatch.setattr(api, "encargo", lambda con, encargo_id: ficha)
    assert "Encargo de la lista de prueba" in cliente.get("/encargos").text
    assert "Fase de prueba" in cliente.get("/encargos/tienda").text
