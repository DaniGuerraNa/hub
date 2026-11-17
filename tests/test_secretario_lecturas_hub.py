"""Lecturas baratas del hub que el secretario no tenía (C-0405, SEC2-03).

Cada una entra por la puerta que ya pinta su pantalla —`api.tablero`,
`fichas.listar`, `api.consumo`, `api.actualizaciones`, `busqueda.buscar`—, sin
SQL propio: un segundo lector se queda atrás en cuanto cambia el primero.
"""

from __future__ import annotations

import pytest

from hub import busqueda, db, ideas
from hub.secretario import herramientas, memoria


@pytest.fixture
def con():
    c = memoria.conectar()
    yield c
    c.close()


@pytest.fixture
def hub():
    h = db.conectar()
    db.inicializar(h)
    yield h
    h.close()


def _leer(nombre, con, **params):
    return herramientas.todas()[nombre].funcion(con, params)


# ── ideas ────────────────────────────────────────────────────────────────────

def test_ideas_cuenta_las_nuevas_con_su_id_y_no_las_ya_tomadas(con, hub):
    a = ideas.apuntar(hub, "Que el parte diga cuántas ideas hay")
    b = ideas.apuntar(hub, "Un atajo para abrir el tablero")
    c = ideas.apuntar(hub, "Algo que ya se tomó")
    ideas.tomar(hub, c, "C-0001")
    hub.commit()

    r = _leer("ideas", con)

    assert r["nuevas"] == 2
    assert [i["id"] for i in r["ideas"]] == [a, b], "en el orden en que se tomarán"
    assert r["ideas"][0]["texto"] == "Que el parte diga cuántas ideas hay"
    assert [(i["id"], i["sigue_en"]) for i in r["recientes"]] == [(c, "C-0001")]


def test_sin_ideas_lo_dice_con_un_cero(con, hub):
    assert _leer("ideas", con)["nuevas"] == 0


# ── fichas ───────────────────────────────────────────────────────────────────

def _ficha(carpeta, num, estado, quien="claude", titulo="Algo"):
    (carpeta / f"C-{num:04d}-algo.md").write_text(
        f"---\nid: C-{num:04d}\ntitulo: {titulo}\nestado: {estado}\nquien: {quien}\ntamano: S\n"
        f"abierta: '2026-11-0{num}'\n---\n\n## Qué se pidió\n\nAlgo.\n", encoding="utf-8")


def test_fichas_lee_las_abiertas_por_la_puerta_de_las_fichas(con, tmp_path):
    carpeta = tmp_path / "cambios"
    carpeta.mkdir()
    _ficha(carpeta, 1, "hecha")
    _ficha(carpeta, 2, "anotada", titulo="Buscar en el hub")
    _ficha(carpeta, 3, "esperando", quien="dueno", titulo="Elegir el color")
    (memoria.carpeta() / "secretario.yml").write_text(f"parte_fichas: {carpeta}\n", encoding="utf-8")

    r = _leer("fichas", con)

    assert [f["id"] for f in r["fichas"]] == ["C-0003", "C-0002"], "las abiertas, la más nueva primero"
    assert r["fichas"][0] == {"id": "C-0003", "titulo": "Elegir el color", "estado": "esperando",
                              "quien": "dueno", "tamano": "S", "abierta": "2026-11-03"}
    assert [f["id"] for f in _leer("fichas", con, quien="dueno")["fichas"]] == ["C-0003"]
    assert [f["id"] for f in _leer("fichas", con, estado="todas")["fichas"]] == ["C-0003", "C-0002", "C-0001"]
    assert [f["id"] for f in _leer("fichas", con, estado="todas", texto="buscar")["fichas"]] == ["C-0002"]
    assert "error" in _leer("fichas", con, estado="perdida")


def test_sin_carpeta_de_fichas_dice_que_no_hay_y_no_revienta(con):
    """En el producto no hay `cambios/`: las fichas son del flujo con que se
    desarrolla el hub. Quien lo instala recibe un «no hay», no un error."""
    r = _leer("fichas", con)
    assert r["fichas"] == [] and "no hay fichas" in r["nota"]


def test_con_la_carpeta_de_fichas_borrada_tambien_lo_dice(con, tmp_path):
    (memoria.carpeta() / "secretario.yml").write_text(f"parte_fichas: {tmp_path / 'no-existe'}\n",
                                                      encoding="utf-8")
    r = _leer("fichas", con)
    assert r["fichas"] == [] and "no existe" in r["nota"]


# ── uso ──────────────────────────────────────────────────────────────────────

def test_uso_da_las_cifras_de_consumo_con_su_ventana(con, hub):
    hub.execute("INSERT INTO proyecto (id, nombre) VALUES ('ws', 'Mi web')")
    for ruta, pid, dia, salida in (("/a", "ws", "2026-11-10", 300), ("/b", None, "2026-11-11", 100)):
        hub.execute("INSERT INTO consumo (proyecto_id, ruta, dia, modelo, peticiones, entrada, escritura, lectura,"
                    " salida, desde, hasta, medido_en) VALUES (?,?,?,'claude-x',2,0,0,600,?,?,?,?)",
                    (pid, ruta, dia, salida, f"{dia}T10:00:00+00:00", f"{dia}T12:00:00+00:00",
                     "2026-11-12T08:00:00+00:00"))
    hub.commit()

    r = _leer("uso", con)

    assert r["tokens"]["total"] == 1600 and r["peticiones"] == 4
    assert r["desde"] and r["hasta"], "sin la ventana, una cifra se lee como un total (regla 13)"
    assert [p["proyecto"] for p in r["proyectos"]] == ["Mi web", "Sin proyecto"]
    assert r["proyectos"][0]["parte"] == pytest.approx(56.2, abs=0.1)
    assert "30 días" in r["nota"]


def test_uso_sin_registro_lo_dice(con, hub):
    assert "error" in _leer("uso", con)


# ── hub_version ──────────────────────────────────────────────────────────────

def test_hub_version_dice_la_version_y_si_hay_otra(con, monkeypatch):
    from hub import api
    monkeypatch.setattr(api, "actualizaciones", lambda: {
        "vers": {"codigo": "0.6.0", "instalada": "0.6.0", "falta_terminar": False, "publicada": "0.7.0",
                 "hay_nueva": True, "mirado_local": "13/11 09:00", "buscar": True, "error": None,
                 "novedades": "Nuevo: algo"},
        "a": {"en_marcha": False, "lanzada": None, "rc": None, "registro": "x" * 5000},
        "cambios": [" M src/algo.py"]})

    r = _leer("hub_version", con)

    assert (r["version"], r["publicada"], r["hay_nueva"]) == ("0.6.0", "0.7.0", True)
    assert r["cambios_locales"] == 1 and r["actualizando"] is False
    assert "registro" not in r, "el registro entero de la actualización no le sirve al modelo"


def test_hub_version_lee_lo_de_verdad_sin_reventar(con):
    r = _leer("hub_version", con)
    assert r["version"] and "hay_nueva" in r


# ── hub_buscar ───────────────────────────────────────────────────────────────

def test_hub_buscar_trae_la_pantalla_con_su_ruta_para_abrirla(con, hub):
    r = _leer("hub_buscar", con, texto="respaldo")
    assert r["resultados"][0] == {"clase": "pantalla", "titulo": "Respaldo", "url": "/respaldo",
                                  "seccion": "Salud"}


def test_hub_buscar_trae_lo_indexado_por_la_misma_busqueda_que_ctrl_k(con, hub):
    hub.execute("INSERT INTO proyecto (id, nombre, nota) VALUES ('tienda', 'Tienda', 'la web de ventas')")
    busqueda.reindexar(hub)
    hub.commit()

    r = _leer("hub_buscar", con, texto="tienda")

    assert {"clase": "proyecto", "titulo": "Tienda", "url": "/proyecto/tienda"}.items() <= r["resultados"][0].items()
    assert "abrir_en_pc" in r["nota"]
    assert "error" in _leer("hub_buscar", con, texto="x")


def test_las_cinco_lecturas_se_sirven_tambien_sin_el_duenio_delante():
    """Son lecturas: no hacen nada, y un `pide` también puede contar ideas."""
    sin_el = herramientas.todas(con_el_dueno=False)
    for nombre in ("ideas", "fichas", "uso", "hub_version", "hub_buscar"):
        assert nombre in sin_el, nombre
