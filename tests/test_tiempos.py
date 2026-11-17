"""Por qué tarda una petición, visto en la propia respuesta (C-0310).

Lo que importa probar no es la suma —es trivial— sino que la cuenta llega:
la abre un middleware ASGI, la llena una ruta `def` que corre en otro hilo,
y en medio hay un `BaseHTTPMiddleware` (`_la_puerta`) que corre lo de dentro
en otra tarea y una compresión que reescribe las cabeceras. Eso no se razona:
se hace una petición de verdad con `TestClient` y se mira la cabecera.
"""

from __future__ import annotations

import gzip

import pytest
from fastapi.testclient import TestClient

from hub import db, tiempos, web


@tiempos.medido
def _leer_algo(ruta: str) -> str:
    return ruta.upper()


@tiempos.medido
def tamaño_del_año() -> int:
    return 1


def test_fuera_de_una_peticion_medir_no_hace_nada_mas_que_llamar():
    """El muestreo y el secretario llaman a las mismas funciones sin petición."""
    assert _leer_algo("x") == "X"
    assert tiempos._CUENTA.get() is None


def test_cada_llamada_suma_bajo_el_nombre_de_su_funcion():
    tramos = tiempos.empezar()
    try:
        _leer_algo("a")
        _leer_algo("b")
        with tiempos.tramo("pintar"):
            pass
    finally:
        tiempos._CUENTA.set(None)
    assert set(tramos) == {"_leer_algo", "pintar"}
    assert tramos["_leer_algo"][0] == 2


def test_la_cabecera_lleva_el_total_y_los_mas_largos_primero():
    cabecera = tiempos.cabecera({"corto": [1, 0.001], "largo": [3, 0.5]}, total=0.6)
    assert cabecera == 'total;dur=600.0, largo;dur=500.0;desc="3 veces", corto;dur=1.0'


def test_un_nombre_con_eñe_sale_como_token_valido_de_http():
    """`Server-Timing` exige un token ASCII; una función en castellano no lo es."""
    tramos = tiempos.empezar()
    try:
        tamaño_del_año()
    finally:
        tiempos._CUENTA.set(None)
    valor = tiempos.cabecera(tramos)
    assert valor.startswith("tamano_del_ano;dur=")
    valor.encode("latin-1")  # lo que exige ASGI para una cabecera


def test_la_cabecera_y_la_linea_nunca_llevan_los_argumentos():
    """Lo que se lee (una ruta de un proyecto) no sale ni al teléfono ni al journal."""
    tramos = tiempos.empezar()
    try:
        _leer_algo("/srv/cliente-secreto/.env")
    finally:
        tiempos._CUENTA.set(None)
    for texto in (tiempos.cabecera(tramos, total=0.1), tiempos.resumen(tramos)):
        assert "secreto" not in texto and "/srv" not in texto
        assert "_leer_algo" in texto


def test_el_tope_deja_fuera_los_tramos_mas_cortos():
    tramos = {f"f{i}": [1, i / 1000] for i in range(40)}
    partes = tiempos.cabecera(tramos).split(", ")
    assert len(partes) == tiempos.TOPE_CABECERA
    assert partes[0].startswith("f39;")


# ───────────── la petición de verdad: puerta, hilo y compresión ─────────────


@pytest.fixture
def cliente(tmp_path, monkeypatch):
    raiz = tmp_path / "proyectos"
    for i in range(30):
        # Carpetas de sobra para que la página pase del mínimo de la compresión.
        (raiz / f"repo-con-un-nombre-largo-{i:02d}").mkdir(parents=True)

    def conexion():
        con = db.conectar(tmp_path / "hub.db")
        db.inicializar(con)
        return con

    con = conexion()
    con.execute("INSERT INTO proyecto (id, nombre, asiento) VALUES ('demo','Demo',?)", (str(raiz),))
    con.execute("INSERT INTO proyecto_ruta (proyecto_id, ruta, tipo) VALUES ('demo',?,'asiento')",
                (str(raiz),))
    con.commit()
    con.close()
    monkeypatch.setattr(web, "conexion", conexion)
    return TestClient(web.app), raiz


def test_una_ruta_def_detras_de_la_puerta_dice_en_que_tardo(cliente):
    """`/archivos` es una ruta `def` (pool de hilos) detrás de `_la_puerta`
    (`BaseHTTPMiddleware`, otra tarea): la cuenta abierta fuera se llena dentro."""
    c, raiz = cliente
    r = c.get("/archivos", params={"ruta": str(raiz)})
    assert r.status_code == 200
    cabecera = r.headers["server-timing"]
    assert cabecera.startswith("total;dur=")
    nombres = {parte.split(";")[0] for parte in cabecera.split(", ")}
    assert {"explorar", "confin", "pintar"} <= nombres
    assert str(raiz) not in cabecera


def test_la_cabecera_sobrevive_a_la_compresion(cliente):
    c, raiz = cliente
    with c.stream("GET", "/archivos", params={"ruta": str(raiz)},
                  headers={"Accept-Encoding": "gzip"}) as r:
        cuerpo = b"".join(r.iter_raw())
        assert r.headers["content-encoding"] == "gzip"
        assert "explorar;dur=" in r.headers["server-timing"]
    assert b"repo-con-un-nombre-largo-07" in gzip.decompress(cuerpo)


def test_la_linea_de_una_peticion_lenta_lleva_sus_tramos(cliente, capsys, monkeypatch):
    c, raiz = cliente
    monkeypatch.setattr(web, "UMBRAL_LENTA_S", 0.0)
    c.get("/archivos", params={"ruta": str(raiz)})
    linea = capsys.readouterr().out
    assert "GET /archivos -> 200 en " in linea
    assert " · " in linea and "explorar " in linea and " ms" in linea
    # Ni la cadena de consulta ni la ruta pedida (C-0245).
    assert str(raiz) not in linea and "ruta=" not in linea


def test_dos_peticiones_seguidas_no_se_mezclan_la_cuenta(cliente):
    """Cada petición abre la suya: la segunda no hereda los tramos de la primera."""
    c, raiz = cliente
    c.get("/archivos", params={"ruta": str(raiz)})
    r = c.get("/static/hub-ui.js")
    assert r.status_code == 200
    assert "explorar" not in r.headers["server-timing"]
