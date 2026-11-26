"""Antes de escribir, el puente comprueba que el documento sigue siendo el que se leyó.

Los números de línea de un cambio valen para el texto leído. Si alguien tocó
el documento después —en cualquier sitio por encima del tramo más bajo—, los
números ya no apuntan a lo mismo y escribir rompería otra cosa.
"""

import pytest

from puente_kvm import cambios, lecturas

from .ayuda import PERSONA, esperar, leer, leida_y_verificada, proponer_y_aprobar, puente_simulado, \
    transcribir_como_oraculo
from .test_motor import SimuladorInquieto


@pytest.fixture
def entorno():
    with puente_simulado() as (c, sim):
        yield c, sim


def tocar(sim, linea: int, texto: str) -> None:
    """Lo que haría alguien en el Mac: cambiar una línea a mano."""
    sim.editor.lineas[linea - 1] = texto
    sim.editor.version += 1


def escribir(c, cid: str) -> dict:
    c.post("/api/control", json={"accion": "dar"}, headers=PERSONA)
    r = c.post(f"/api/cambios/{cid}/escribir")
    assert r.status_code == 200, r.text
    esperar(c)
    return c.get(f"/api/cambios/{cid}").json()


def test_un_cambio_hecho_a_mitad_del_documento_despues_de_leer_impide_escribir(entorno):
    # La primera página está intacta: comparar sólo ésa no lo veía.
    c, sim = entorno
    lid = leida_y_verificada(c, sim)
    nuevo = list(sim.editor.guardado)
    nuevo[129] = nuevo[129] + " -- revisado"
    cid = proponer_y_aprobar(c, lid, nuevo)
    tocar(sim, 80, "    -- alguien tocó esto")
    antes = list(sim.editor.lineas)
    cambio = escribir(c, cid)
    assert cambio["estado"] == "fallido"
    assert "página 3" in cambio["error"] and "no es la que se leyó" in cambio["error"]
    assert sim.editor.lineas == antes


def test_un_cambio_por_debajo_del_tramo_mas_bajo_no_impide_escribir_y_la_huella_lo_dira(entorno):
    # Debajo del último tramo los números no se mueven: no hace falta recorrerlo.
    c, sim = entorno
    lid = leida_y_verificada(c, sim)
    nuevo = list(sim.editor.guardado)
    nuevo[10] = nuevo[10] + " -- revisado"
    cid = proponer_y_aprobar(c, lid, nuevo)
    tocar(sim, 150, "    -- alguien tocó esto")
    cambio = escribir(c, cid)
    assert cambio["estado"] == "escrito", cambio["error"]
    assert sim.editor.lineas[10] == nuevo[10]


def test_la_comprobacion_previa_queda_en_la_bitacora_con_lo_que_tardo(entorno):
    c, sim = entorno
    lid = leida_y_verificada(c, sim)
    nuevo = list(sim.editor.guardado)
    nuevo[-1] = "END; -- fin"
    cid = proponer_y_aprobar(c, lid, nuevo)
    assert escribir(c, cid)["estado"] == "escrito"
    paginas = len(lecturas.cargar(lid).paginas)
    entradas = [e for e in c.get("/api/bitacora").json() if e["tipo"] == "comprobacion"]
    assert entradas and f"páginas 1–{paginas}" in entradas[-1]["detalle"] and " s)" in entradas[-1]["detalle"]


def test_con_la_pantalla_moviendose_no_escribe():
    with puente_simulado() as (c, sim):
        lid = leida_y_verificada(c, sim)
        nuevo = list(sim.editor.guardado)
        nuevo[5] = nuevo[5] + " -- x"
        cid = proponer_y_aprobar(c, lid, nuevo)
    # El mismo cambio, ahora con algo moviéndose en la pantalla del Mac.
    inquieto = SimuladorInquieto(lineas=list(sim.editor.lineas))
    from fastapi.testclient import TestClient

    from puente_kvm.app import crear_app
    with TestClient(crear_app(inquieto, hosts={"testserver"})) as c:
        c.app.state.puente.motor.tope_estable = 0.6
        antes = list(inquieto.editor.lineas)
        cambio = escribir(c, cid)
        assert cambio["estado"] == "fallido"
        assert "quieta" in cambio["error"]
        assert inquieto.editor.lineas == antes


def test_una_pagina_capturada_con_la_pantalla_moviendose_queda_marcada_para_ambos():
    sim = SimuladorInquieto(lineas=__import__("puente_kvm").muestras.procedimiento(80))
    from fastapi.testclient import TestClient

    from puente_kvm.app import crear_app
    with TestClient(crear_app(sim, hosts={"testserver"})) as c:
        c.app.state.puente.motor.tope_estable = 0.4
        lid = leer(c)
        r = c.get(f"/api/lecturas/{lid}").json()
        assert r["inestables"] == list(range(1, r["paginas"] + 1))  # Claude lo ve en la API
        html = c.get(f"/lecturas/{lid}").text
        assert "se movía" in html  # y la persona en la página de la lectura


def test_proponer_sobre_una_lectura_sin_verificar_se_puede_pero_se_dice(entorno):
    c, sim = entorno
    lid = leer(c)
    transcribir_como_oraculo(c, sim, lid)  # completa, pero sin huella
    nuevo = list(sim.editor.guardado)
    nuevo[5] = nuevo[5] + " -- x"
    r = c.post("/api/cambios", json={"lectura": lid, "texto": "\n".join(nuevo), "descripcion": "sin huella"})
    assert r.status_code == 200
    assert r.json()["lectura_verificada"] is False
    assert "sin verificar" in r.json()["aviso"]
    html = c.get(f"/cambios/{r.json()['id']}").text
    assert html.index("sin verificar") < html.index("data-aprobar")


def test_proponer_sobre_una_lectura_verificada_no_lleva_aviso(entorno):
    c, sim = entorno
    lid = leida_y_verificada(c, sim)
    nuevo = list(sim.editor.guardado)
    nuevo[5] = nuevo[5] + " -- x"
    r = c.post("/api/cambios", json={"lectura": lid, "texto": "\n".join(nuevo), "descripcion": "con huella"})
    assert r.json()["lectura_verificada"] is True
    assert "sin verificar" not in c.get(f"/cambios/{r.json()['id']}").text


def test_la_huella_tras_guardar_un_cambio_sin_huella_esperada_queda_guardada_con_su_variante(entorno):
    c, sim = entorno
    lid = leer(c)
    transcribir_como_oraculo(c, sim, lid)
    nuevo = list(sim.editor.guardado)
    nuevo[5] = nuevo[5] + " -- x"
    cid = proponer_y_aprobar(c, lid, nuevo)
    assert escribir(c, cid)["estado"] == "escrito"
    c.post("/api/simulador/guardar", headers=PERSONA)
    r = c.post(f"/api/cambios/{cid}/huella", json={"referencia": sim.estado()["huella_base"]}).json()
    assert r["verificado"]
    guardado = cambios.cargar(cid)
    assert guardado.variante and guardado.variante["codificacion"] == "utf-16-le"
    assert guardado.estado == "verificado"


# ── todo o nada también con el teclado de Ajustes (C-0481) ──────────────────
def _reservadas(c, lista: list[str]) -> None:
    from puente_kvm import config
    perfil = {**config.leer_ajustes()["perfil"], "reservadas": lista}
    assert c.post("/api/ajustes", json={"perfil": perfil}, headers=PERSONA).status_code == 200


def test_proponer_un_cambio_con_un_caracter_de_tecla_reservada_se_rechaza_al_proponerlo(entorno):
    # `proponer` validaba con «U.S.» y sin reservadas; se teclea con las de Ajustes.
    c, sim = entorno
    lid = leida_y_verificada(c, sim)
    nuevo = list(sim.editor.guardado)
    nuevo[20] = nuevo[20] + " -- ≈ casi"
    r = c.post("/api/cambios", json={"lectura": lid, "texto": "\n".join(nuevo), "descripcion": "x"})
    assert r.status_code == 422 and "≈" in r.json()["detail"] and "alt+x" in r.json()["detail"]


def test_si_un_tramo_ya_no_se_puede_teclear_no_se_escribe_ningun_otro(entorno):
    # Se propuso sin reservas y luego se reservó Opción+X: antes, el tramo de abajo
    # se escribía y el de arriba fallaba, y el editor quedaba a medias.
    c, sim = entorno
    lid = leida_y_verificada(c, sim)
    _reservadas(c, [])
    nuevo = list(sim.editor.guardado)
    nuevo[10] = nuevo[10] + " -- ≈ casi"
    nuevo[130] = nuevo[130] + " -- revisado"
    cid = proponer_y_aprobar(c, lid, nuevo)
    _reservadas(c, ["alt+x"])
    antes, pulsaciones = list(sim.editor.lineas), sim.pulsaciones
    cambio = escribir(c, cid)
    assert cambio["estado"] == "fallido" and "≈" in cambio["error"]
    assert sim.editor.lineas == antes
    assert sim.pulsaciones == pulsaciones  # ni una tecla: tampoco los atajos de comprobar las páginas


# ── la zona de la lectura (C-0491, decisión 460) ────────────────────────────
# Una zona que no es la región del editor de Ajustes (300, 98, 1620×952): otra
# ventana. Recorta el editor del simulador, así que se lee igual de bien.
OTRA_ZONA = [300, 98, 1500, 900]


def leida_en_zona(c, sim, zona=OTRA_ZONA) -> str:
    x, y, w, h = zona
    assert c.post("/api/control", json={"accion": "dar"}, headers=PERSONA).status_code == 200
    r = c.post("/api/lecturas", json={"nombre": "en otra ventana", "x": x, "y": y, "ancho": w, "alto": h})
    assert r.status_code == 200, r.text
    esperar(c)
    lid = r.json()["id"]
    transcribir_como_oraculo(c, sim, lid)
    assert c.post(f"/api/lecturas/{lid}/huella", json={"referencia": sim.estado()["huella_base"]}).json()["verificada"]
    return lid


def test_una_lectura_hecha_en_otra_zona_se_escribe_en_esa_zona(entorno):
    """Antes se comparaba y se recortaba con la región de Ajustes: una lectura
    con zona no casaba nunca («no es la que se leyó») y no se podía escribir."""
    c, sim = entorno
    lid = leida_en_zona(c, sim)
    assert lecturas.cargar(lid).zona == OTRA_ZONA
    nuevo = list(sim.editor.guardado)
    nuevo[40] = nuevo[40] + " -- revisado"
    cid = proponer_y_aprobar(c, lid, nuevo)
    cambio = escribir(c, cid)
    assert cambio["estado"] == "escrito", cambio["error"]
    assert sim.editor.lineas[40] == nuevo[40]
    # La captura de cada tramo es de la zona de la lectura, como sus páginas.
    from PIL import Image
    assert Image.open(cambios.cargar(cid).png(1)).size == tuple(OTRA_ZONA[2:])


def test_una_lectura_antigua_sin_zona_se_escribe_en_la_region_de_ajustes(entorno):
    c, sim = entorno
    lid = leida_y_verificada(c, sim)
    l = lecturas.cargar(lid)
    l.zona = None  # como la guardaba el puente antes de C-0491
    l.guardar()
    nuevo = list(sim.editor.guardado)
    nuevo[10] = nuevo[10] + " -- revisado"
    cid = proponer_y_aprobar(c, lid, nuevo)
    assert escribir(c, cid)["estado"] == "escrito"
    assert sim.editor.lineas[10] == nuevo[10]


def test_con_la_region_de_ajustes_cambiada_una_lectura_antigua_no_se_escribe(entorno):
    # Sin zona guardada, la región es la de Ajustes de ahora: si ya no es la que
    # se usó al leer, las páginas no casan y no se teclea nada.
    c, sim = entorno
    lid = leida_y_verificada(c, sim)
    l = lecturas.cargar(lid)
    l.zona = None
    l.guardar()
    nuevo = list(sim.editor.guardado)
    nuevo[10] = nuevo[10] + " -- revisado"
    cid = proponer_y_aprobar(c, lid, nuevo)
    r = c.post("/api/ajustes", json={"perfil": {"region_editor": OTRA_ZONA}}, headers=PERSONA)
    assert r.status_code == 200, r.text
    antes = list(sim.editor.lineas)
    cambio = escribir(c, cid)
    assert cambio["estado"] == "fallido" and "no es la que se leyó" in cambio["error"]
    assert sim.editor.lineas == antes


def test_el_estado_ensena_la_zona_de_la_tarea_en_marcha_de_su_lectura_o_de_su_cambio(entorno):
    """Sin estado nuevo: sale de la lectura que se captura o de la del cambio que se
    escribe. Sin tarea, ninguna."""
    c, sim = entorno
    p = c.app.state.puente
    assert c.get("/api/estado").json()["zona_tarea"] is None
    l = lecturas.nueva("capturando en otra ventana")
    l.zona = OTRA_ZONA
    l.guardar()
    p.motor.tarea = "leer «capturando en otra ventana»"
    try:
        z = c.get("/api/estado").json()["zona_tarea"]
        assert z["zona"] == OTRA_ZONA and z["de_ajustes"] is False and "otra ventana" in z["texto"]
        l.estado = "capturada"
        l.guardar()
        assert c.get("/api/estado").json()["zona_tarea"] is None
        cambio = cambios.Cambio(id="escribiendo-000001", lectura=l.id, descripcion="d", creado=0.0,
                                original=["a"], nuevo=["b"], tramos=cambios.tramos_de(["a"], ["b"]),
                                estado="escribiendo")
        cambio.guardar()
        assert c.get("/api/estado").json()["zona_tarea"]["zona"] == OTRA_ZONA
    finally:
        p.motor.tarea = None
    assert c.get("/api/estado").json()["zona_tarea"] is None
