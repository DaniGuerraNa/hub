"""Rechazar una solicitud diciendo por qué (C-0395).

Tres de cada cuatro se rechazaban sin que el secretario supiera qué estaba
mal: lo volvía a proponer igual o se quedaba sin hacerlo. Y el chat decía
«No lo hago: rechazaste «escribir_en_sesion»», con el id. Ahora el motivo es
un mensaje del dueño que cita ese «No lo hago…», con el nombre de Confianza;
no se copia a la solicitud ni a la bitácora.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from hub import api, web
from hub.secretario import conversacion, memoria, piezas

pytestmark = pytest.mark.usefixtures("canal_telegram")

MOTIVO = "No a esa sesión: el login lo lleva la otra, la de pagos <b>no</b>."


@pytest.fixture
def con():
    c = memoria.conectar()
    yield c
    c.close()


@pytest.fixture
def cliente(tmp_path, monkeypatch):
    from hub import db

    def conexion():
        c = db.conectar(tmp_path / "hub.db")
        db.inicializar(c)
        return c

    monkeypatch.setattr(web, "conexion", conexion)
    return TestClient(web.app)


def _pedir(con, accion: str = "escribir_en_sesion", params: dict | None = None, motivo: str = "me lo pediste",
           hilo: int | None = None) -> int:
    if hilo is None:
        hilo = conversacion.decir(con, None, "Te pido permiso para escribirle.")
        hilo = con.execute("SELECT hilo FROM turno WHERE id = ?", (hilo,)).fetchone()[0]
    return con.execute("INSERT INTO solicitud (accion, params, motivo, hilo, creada) VALUES (?, ?, ?, ?, ?)",
                       (accion, json.dumps(params or {"slot": 3, "texto": "revisa el login"}), motivo, hilo or None,
                        memoria.ahora())).lastrowid


def _rechazar(cliente, sid: int, por_que=None) -> dict:
    cuerpo = {"decision": "rechazar"} | ({} if por_que is None else {"por_que": por_que})
    return cliente.post(f"/api/secretario/solicitud/{sid}", json=cuerpo).json()


def _turnos(con) -> list[dict]:
    return [dict(f) for f in con.execute("SELECT id, hilo, rol, texto, estado, responde_a FROM turno ORDER BY id")]


def test_rechazar_con_motivo_deja_el_no_lo_hago_y_su_motivo_como_turno_suyo_que_lo_cita(cliente, con):
    sid = _pedir(con)
    antes = len(_turnos(con))

    assert _rechazar(cliente, sid, MOTIVO) == {"ok": True, "error": None}

    no_lo_hago, suyo = _turnos(con)[antes:]
    assert no_lo_hago["rol"] == "secretario" and no_lo_hago["texto"].startswith("No lo hago: rechazaste")
    assert suyo["rol"] == "dueno" and suyo["responde_a"] == no_lo_hago["id"], "cita el «No lo hago…» (406)"
    assert suyo["hilo"] == no_lo_hago["hilo"]


def test_el_motivo_entra_tal_cual_y_queda_pendiente_para_que_el_secretario_lo_conteste(cliente, con):
    sid = _pedir(con)

    _rechazar(cliente, sid, f"  {MOTIVO}\n")

    suyo = _turnos(con)[-1]
    assert suyo["texto"] == MOTIVO, "literal, sin redactar ni escapar (351)"
    assert suyo["estado"] == "pendiente"


def test_el_no_lo_hago_nombra_la_accion_como_en_confianza_y_no_por_su_id(cliente, con):
    sid = _pedir(con, motivo="Para que revise el login. Y nada más.")

    _rechazar(cliente, sid)

    texto = _turnos(con)[-1]["texto"]
    assert texto == "No lo hago: rechazaste «Escribirle a una sesión de trabajo» (Para que revise el login. Y nada más)."
    assert "escribir_en_sesion" not in texto


def test_rechazar_sin_motivo_no_crea_ningun_turno_del_dueno(cliente, con):
    sid, otra = _pedir(con), _pedir(con)

    _rechazar(cliente, sid)
    _rechazar(cliente, otra, "   \n ")

    assert [t["rol"] for t in _turnos(con)].count("dueno") == 0, "vacío o sólo espacios es rechazar a secas"
    assert memoria.bitacora(con)[0]["resultado"] == "el dueño dijo que no"


def test_una_que_ya_estaba_resuelta_no_deja_el_motivo_suelto_en_el_chat(cliente, con):
    sid = _pedir(con)
    memoria.resolver_solicitud(con, sid, "aprobada", solo_pendiente=True)
    antes = _turnos(con)

    r = _rechazar(cliente, sid, MOTIVO)

    assert r == {"ok": False, "error": "Esa solicitud ya estaba resuelta."}
    assert _turnos(con) == antes
    assert con.execute("SELECT estado FROM solicitud WHERE id = ?", (sid,)).fetchone()[0] == "aprobada", \
        "el reclamo no se toca: sigue aprobada, para quien la ejecuta (C-0315)"


def test_el_motivo_no_se_copia_en_la_solicitud_ni_en_la_bitacora(cliente, con):
    sid = _pedir(con)

    _rechazar(cliente, sid, MOTIVO)

    fila = dict(con.execute("SELECT * FROM solicitud WHERE id = ?", (sid,)).fetchone())
    assert MOTIVO not in json.dumps(fila, ensure_ascii=False)
    [b] = memoria.bitacora(con)
    assert MOTIVO not in json.dumps(b, ensure_ascii=False)
    suyo = _turnos(con)[-1]
    assert b["nivel"] == "rechazada" and b["resultado"] == f"el dueño dijo que no, y dijo por qué (turno {suyo['id']})"


def test_rechazada_con_motivo_sus_parametros_se_quedan_tapados_igual(cliente, con, monkeypatch):
    """El tapado de lo resuelto (C-0431) no depende de que haya motivo."""
    llamadas = []
    monkeypatch.setattr(piezas, "solicitud_tapada", lambda c, s: llamadas.append(s) or {"tapado": True})
    sid = _pedir(con)

    _rechazar(cliente, sid, MOTIVO)

    assert llamadas == [sid]
    assert json.loads(con.execute("SELECT params FROM solicitud WHERE id = ?", (sid,)).fetchone()[0]) == {"tapado": True}


def test_rechazar_con_motivo_una_solicitud_sin_hilo_lo_dice_en_el_hilo_abierto(cliente, con):
    abierto = conversacion.recibir(con, "hola")["hilo"]
    sid = _pedir(con, hilo=0)          # nació en un disparador: sin hilo

    _rechazar(cliente, sid, MOTIVO)

    no_lo_hago, suyo = _turnos(con)[-2:]
    assert no_lo_hago["hilo"] == suyo["hilo"] == abierto
    assert suyo["texto"] == MOTIVO


def test_sin_hilo_y_sin_motivo_el_chat_no_dice_nada_como_hasta_ahora(cliente, con):
    sid = _pedir(con, hilo=0)

    _rechazar(cliente, sid)

    assert _turnos(con) == []


def test_aprobar_ignora_el_motivo(cliente, con):
    sid = _pedir(con)
    antes = _turnos(con)

    r = cliente.post(f"/api/secretario/solicitud/{sid}", json={"decision": "aprobar", "por_que": MOTIVO}).json()

    assert r["ok"] and _turnos(con) == antes
    assert con.execute("SELECT estado FROM solicitud WHERE id = ?", (sid,)).fetchone()[0] == "aprobada"


def test_un_motivo_que_no_es_texto_se_ignora(cliente, con):
    sid = _pedir(con)

    assert _rechazar(cliente, sid, {"b": 1})["ok"]

    assert [t["rol"] for t in _turnos(con)].count("dueno") == 0


def test_el_formulario_de_pendientes_tambien_lleva_el_motivo(cliente, con):
    sid = _pedir(con)

    r = cliente.post(f"/secretario/solicitud/{sid}", data={"decision": "rechazar", "por_que": MOTIVO,
                                                          "volver": "/secretario?p=pendientes"},
                     follow_redirects=False)

    assert r.status_code == 303 and "porqu" in r.headers["location"]
    assert _turnos(con)[-1]["texto"] == MOTIVO


def test_el_nombre_de_una_accion_sale_de_una_sola_regla(con):
    """Pendientes, la bitácora, la tarjeta del chat y el «No lo hago…»."""
    _pedir(con, accion="escribir_en_sesion")
    _pedir(con, accion="accion_retirada")
    memoria.apuntar(con, "escribir_en_sesion", nivel="aprobada")
    memoria.apuntar(con, "accion_retirada", nivel="aprobada")

    s = api.secretario()
    tarjeta = {p["accion"]: p["nombre"] for p in api.secretario_turnos()["permisos"]}

    for accion in ("escribir_en_sesion", "accion_retirada"):
        esperado = piezas.nombre_de_accion(accion)
        assert {x["nombre"] for x in s["solicitudes"] if x["accion"] == accion} == {esperado}
        assert {x["nombre"] for x in s["bitacora"] if x["accion"] == accion} == {esperado}
        assert tarjeta[accion] == esperado
    assert piezas.nombre_de_accion("escribir_en_sesion") == "Escribirle a una sesión de trabajo"
    assert piezas.nombre_de_accion("accion_retirada") == "accion retirada"


def test_si_falla_a_mitad_no_queda_nada_a_medias(con, tmp_path, monkeypatch):
    """Tras la revisión: la conexión va en autocommit, y si `recibir` fallaba
    quedaba la solicitud rechazada, el «No lo hago…» sin su motivo y la
    bitácora vacía. Los cuatro pasos van en una transacción: o todo o nada, y
    la solicitud sigue esperando su sí, con sus parámetros en claro."""
    import sqlite3

    from hub import db

    def conexion():
        c = db.conectar(tmp_path / "hub.db")
        db.inicializar(c)
        return c

    monkeypatch.setattr(web, "conexion", conexion)
    sid = _pedir(con)
    antes = _turnos(con)
    params = con.execute("SELECT params FROM solicitud WHERE id = ?", (sid,)).fetchone()[0]

    def rota(*a, **kw):
        raise sqlite3.OperationalError("database is locked")
    recibir = conversacion.recibir
    monkeypatch.setattr(conversacion, "recibir", rota)

    r = TestClient(web.app, raise_server_exceptions=False).post(
        f"/api/secretario/solicitud/{sid}", json={"decision": "rechazar", "por_que": MOTIVO})

    assert r.status_code >= 500, "no dice que salió"
    fila = con.execute("SELECT estado, params FROM solicitud WHERE id = ?", (sid,)).fetchone()
    assert tuple(fila) == ("pendiente", params)
    assert _turnos(con) == antes and memoria.bitacora(con) == []
    # 🔴 Sólo `recibir` de vuelta, nunca `monkeypatch.undo()`: desharía
    # también el `HUB_HOME` aislado de `conftest.py` y la petición siguiente
    # iría a la memoria de verdad.
    monkeypatch.setattr(conversacion, "recibir", recibir)
    otra = _rechazar(TestClient(web.app), sid, MOTIVO)
    assert otra["ok"], otra
