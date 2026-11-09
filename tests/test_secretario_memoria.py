"""La memoria del secretario: buscar, compromisos y recordatorios (decisión 299)."""

from __future__ import annotations

import json

import pytest

from hub.secretario import memoria, recordatorios, tiempo
from hub.secretario.piezas import Evento

# Los avisos de estos tests salen por el timbre de Telegram (el respaldo, decisión 310).
pytestmark = pytest.mark.usefixtures("canal_telegram")


@pytest.fixture
def con():
    c = memoria.conectar()
    yield c
    c.close()


def _ev(i, texto, **kw):
    return Evento(fuente=kw.pop("fuente", "telegram"), id_externo=str(i), fecha=kw.pop("fecha", f"2026-10-2{i % 10}T10:00:00+00:00"),
                  texto=texto, conversacion=kw.pop("conversacion", "Trabajo"), autor=kw.pop("autor", "Ana"), **kw)


def test_la_base_vive_en_su_carpeta_y_no_en_hub_db(con):
    from hub import config
    assert memoria.ruta() == config.HUB_HOME / "secretario" / "memoria.db"
    assert memoria.ruta().is_file()
    # `hub.db` puede existir (el dueño del Canal vive ahí, C-0060), pero sin
    # nada del secretario dentro.
    hub_db = config.HUB_HOME / "hub.db"
    if hub_db.exists():
        import sqlite3
        tablas = {r[0] for r in sqlite3.connect(hub_db).execute("SELECT name FROM sqlite_master")}
        assert not tablas & {"evento", "turno", "compromiso", "bitacora"}


def test_un_evento_repetido_no_se_guarda_dos_veces(con):
    assert memoria.guardar_evento(con, _ev(1, "hola")) is not None
    assert memoria.guardar_evento(con, _ev(1, "hola")) is None
    assert con.execute("SELECT COUNT(*) FROM evento").fetchone()[0] == 1


def test_busca_sin_acentos_y_dice_de_donde_sale_cada_resultado(con):
    memoria.guardar_evento(con, _ev(1, "Mañana se despliega la lambda de facturación", autor="Luis"))
    memoria.guardar_evento(con, _ev(2, "¿Quién trae el pastel?"))
    r = memoria.buscar(con, "facturacion lambda")
    assert len(r) == 1
    assert r[0]["autor"] == "Luis" and r[0]["conversacion"] == "Trabajo"
    assert r[0]["fuente"] == "telegram" and r[0]["fecha"].startswith("2026-10-21")


def test_si_ningun_mensaje_tiene_todas_las_palabras_se_conforma_con_alguna(con):
    memoria.guardar_evento(con, _ev(1, "el despliegue quedó para el jueves"))
    assert memoria.buscar(con, "despliegue viernes producción")[0]["texto"].startswith("el despliegue")


def test_una_busqueda_con_sintaxis_de_fts_no_revienta(con):
    memoria.guardar_evento(con, _ev(1, "precio: 30-40 dólares"))
    assert memoria.buscar(con, 'precio: "30-40" AND OR NEAR(')[0]["texto"].startswith("precio")
    assert memoria.buscar(con, "") == []


def test_las_notas_tambien_se_encuentran_y_al_editarlas_se_busca_lo_nuevo(con):
    i = memoria.anotar(con, "El cliente prefiere factura en pesos", tema="facturación", origen="reunión")
    assert memoria.buscar(con, "pesos")[0]["tipo"] == "nota"
    memoria.editar_nota(con, i, "El cliente prefiere factura en dólares")
    assert memoria.buscar(con, "pesos") == []
    assert memoria.buscar(con, "dólares")[0]["id"] == i
    memoria.borrar_nota(con, i)
    assert memoria.buscar(con, "dólares") == []


def test_un_compromiso_igual_no_se_duplica_y_las_fechas_nuevas_mandan(con):
    """Medido el 2026-10-24: «recuérdamelo el lunes» sobre uno vencido se quedaba
    con la fecha vieja y el modelo, viéndolo vencido, lo descartó."""
    a = memoria.comprometer(con, "Revisar los PR", vence="2026-10-21T15:00:00+00:00")
    b = memoria.comprometer(con, "revisar los pr", recordar_en="2026-10-26T16:00:00+00:00")
    assert a == b
    c = memoria.compromisos(con)[0]
    assert c["recordar_en"] == "2026-10-26T16:00:00+00:00" and c["recordado"] is None


def test_avisa_una_sola_vez_lo_que_ya_toca(con, tmp_path):
    from hub import orquestador
    memoria.comprometer(con, "Llamar a Ana", recordar_en="2026-10-24T15:00:00+00:00")
    memoria.comprometer(con, "Sin fecha")
    memoria.comprometer(con, "Futuro", recordar_en="2099-01-01T00:00:00+00:00")
    assert recordatorios.revisar(con, "2026-10-24T15:00:01+00:00") == 1
    assert recordatorios.revisar(con, "2026-10-24T15:05:00+00:00") == 0
    timbres = orquestador.timbres_pendientes()
    assert len(timbres) == 1
    datos = json.loads(timbres[0].read_text())
    assert "Llamar a Ana" in datos["texto"] and datos["pantalla"] == "Secretario"


def test_las_horas_que_dice_el_dueño_son_de_su_zona(monkeypatch):
    monkeypatch.setenv("TZ", "America/Mexico_City")
    assert tiempo.a_utc("2026-10-26T10:00") == "2026-10-26T16:00:00+00:00"
    # Un día sin hora es a las nueve de la mañana, no a medianoche.
    assert tiempo.a_utc("2026-10-26") == "2026-10-26T15:00:00+00:00"
    assert tiempo.a_local("2026-10-26T16:00:00+00:00") == "2026-10-26 10:00"
    with pytest.raises(ValueError):
        tiempo.a_utc("el lunes")


@pytest.mark.parametrize("llave", [
    "sk_" + "a7" + "B" * 30, "sk-ant-" + "x" * 40, "ghp_" + "Z" * 36, "AKIA" + "ABCDEFGHIJKLMNOP",
    "123456789:" + "A" * 35, "Bearer " + "e" * 40,
])
def test_lo_que_parece_una_llave_no_llega_a_la_memoria(con, llave):
    """La primera lectura real trajo una clave de API pegada en la nota de un slot."""
    memoria.guardar_evento(con, _ev(1, f"usa esta: {llave} y listo"))
    texto = con.execute("SELECT texto FROM evento").fetchone()[0]
    assert llave not in texto and "[secreto oculto]" in texto and texto.startswith("usa esta:")
    assert memoria.buscar(con, llave[:12]) == [] or llave not in json.dumps(memoria.buscar(con, llave[:12]))


def test_una_asignacion_tapa_el_valor_y_deja_de_que_era(con):
    memoria.guardar_evento(con, _ev(1, "contraseña: hunter2hunter y token=abcdef123456"))
    texto = con.execute("SELECT texto FROM evento").fetchone()[0]
    assert texto == "contraseña: [secreto oculto] y token=[secreto oculto]"


@pytest.mark.parametrize("texto", [
    '{"password": "hunter2-largo", "api_key": "abcdef123456"}',
    # Como sale dentro de una línea de stream-json: las comillas, escapadas.
    '{"content": "{\\"password\\": \\"hunter2-largo\\", \\"api_key\\": \\"abcdef123456\\"}"}',
    "secret = 'hunter2-largo'; token: \"abcdef123456\"",
    # Con algo delante de la clave: las formas de OAuth y de un `.env`.
    '{"access_token":"hunter2-largo","client_secret":"abcdef123456"}',
    "DB_PASSWORD=hunter2-largo refresh_token=abcdef123456",
])
def test_una_asignacion_en_forma_de_json_tambien_se_tapa(texto):
    """Con comilla entre la clave y los dos puntos, el patrón no la veía (C-0185)."""
    limpio = memoria.ocultar_secretos(texto)
    assert "hunter2-largo" not in limpio and "abcdef123456" not in limpio, limpio
    assert limpio.count("[secreto oculto]") == 2


def test_lo_que_cuenta_tokens_no_es_una_llave():
    texto = '{"input_tokens": 123456, "cache_read_input_tokens": 654321, "max_tokens": 4096, "token_count": 999999}'
    assert memoria.ocultar_secretos(texto) == texto
