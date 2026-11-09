"""Lo que el secretario hace sin que se lo pidan en ese momento: el resumen del
día, el aviso antes de un evento y saber que el dueño está en una llamada; y
las consultas sobre el ecosistema (decisiones 308 y 313)."""

from __future__ import annotations

import json
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from hub import orquestador
from hub.secretario import agenda, disparadores, herramientas, memoria, piezas, resumen

pytestmark = pytest.mark.usefixtures("canal_telegram")

MX = ZoneInfo("America/Mexico_City")


@pytest.fixture
def con(monkeypatch):
    monkeypatch.setenv("TZ", "America/Mexico_City")
    c = memoria.conectar()
    yield c
    c.close()


def _timbres() -> list[dict]:
    return [json.loads(t.read_text()) for t in orquestador.timbres_pendientes()]


def _agenda(monkeypatch, eventos):
    monkeypatch.setattr(agenda, "disponible", lambda: None)
    monkeypatch.setattr(agenda, "eventos", lambda desde, hasta, n=50: eventos)


# ── el resumen del día ───────────────────────────────────────────────────────

def test_el_resumen_junta_agenda_hoy_vencidos_permisos_y_notas_sin_llamar_al_modelo(con, monkeypatch):
    from hub.secretario import motor
    monkeypatch.setattr(motor, "llamar", lambda *a, **k: pytest.fail("el resumen no usa el modelo"))
    _agenda(monkeypatch, [{"titulo": "Daily", "inicio": "2026-10-26T10:00:00-06:00"}])
    ahora = datetime(2026, 10, 26, 8, 30, tzinfo=MX)
    memoria.comprometer(con, "Mandar el reporte", vence="2026-10-26T20:00:00+00:00")       # hoy 14:00
    memoria.comprometer(con, "Revisar PRs", vence="2026-10-21T15:00:00+00:00")             # vencido
    memoria.comprometer(con, "Algo de la semana que viene", vence="2026-11-02T15:00:00+00:00")
    con.execute("INSERT INTO solicitud (accion, params, motivo, creada) VALUES ('crear_slot', '{}', '', ?)",
                (memoria.ahora(),))
    memoria.anotar(con, "Se movió el deploy al jueves")
    con.execute("UPDATE nota SET creada = '2026-10-26T01:00:00+00:00'")    # anoche
    t = resumen.del_dia(con, ahora)
    assert "· 10:00 Daily" in t
    assert "Para hoy:\n· Mandar el reporte (14:00)" in t
    assert "Vencidos: 1\n· Revisar PRs" in t
    assert "Esperan tu sí: 1." in t
    assert "Se movió el deploy al jueves" in t
    assert "semana que viene" not in t


def test_sin_agenda_conectada_el_resumen_no_dice_que_no_hay_nada(con):
    t = resumen.del_dia(con, datetime(2026, 10, 26, 8, 30, tzinfo=MX))
    assert "Agenda" not in t
    assert t == "Nada pendiente para hoy."


def test_la_accion_manda_el_resumen_al_telefono(con):
    memoria.comprometer(con, "Revisar PRs", vence="2020-01-01T15:00:00+00:00")
    r = herramientas.usar_accion(con, piezas.acciones()["resumen_del_dia"], {})
    assert r["hecho"] is True
    t = _timbres()[0]["texto"]
    assert "Revisar PRs" in t


# ── antes de un evento ───────────────────────────────────────────────────────

@pytest.fixture
def antes_de_evento():
    (memoria.carpeta() / "disparadores.yml").write_text(
        "- nombre: antes\n  cuando: {antes_de_evento: 15}\n", encoding="utf-8")


def test_avisa_una_vez_antes_del_evento_con_lo_relacionado(con, antes_de_evento):
    memoria.comprometer(con, "Llevar las cifras del presupuesto")
    ev = [{"id": "e1", "titulo": "Revisión de presupuesto", "inicio": "2026-10-26T10:00:00-06:00", "lugar": "Sala 2"}]
    assert disparadores.por_agenda(con, datetime(2026, 10, 26, 9, 30, tzinfo=MX), ev) == 0, "aún faltan 30 min"
    assert disparadores.por_agenda(con, datetime(2026, 10, 26, 9, 50, tzinfo=MX), ev) == 1
    assert disparadores.por_agenda(con, datetime(2026, 10, 26, 9, 55, tzinfo=MX), ev) == 0, "una sola vez"
    t = _timbres()[0]["texto"]
    assert "Revisión de presupuesto a las 10:00 · Sala 2" in t and "Llevar las cifras del presupuesto" in t


def test_un_aviso_antes_del_evento_sin_canal_se_reintenta_y_queda_en_la_bitacora(con, antes_de_evento, monkeypatch):
    """C-0063. Se marcaba hecho ANTES de mandar: sin canal, el aviso no salía
    nunca, cortaba la vuelta y no dejaba rastro."""
    from hub.secretario import avisos

    ev = [{"id": "e1", "titulo": "Revisión", "inicio": "2026-10-26T10:00:00-06:00"}]
    real = avisos.mandar

    def sin_canal(*a, **k):
        raise avisos.SinCanal("telegram: sin red")
    monkeypatch.setattr(avisos, "mandar", sin_canal)
    assert disparadores.por_agenda(con, datetime(2026, 10, 26, 9, 50, tzinfo=MX), ev) == 0
    assert disparadores.por_agenda(con, datetime(2026, 10, 26, 9, 51, tzinfo=MX), ev) == 0
    fallos = con.execute("SELECT resultado FROM bitacora WHERE accion = 'disparador' AND ok = 0").fetchall()
    assert len(fallos) == 1 and "sin red" in fallos[0][0], "una vez por motivo, no cada vuelta"
    assert memoria.leer(con, "avisos_error") == "telegram: sin red"

    monkeypatch.setattr(avisos, "mandar", real)
    assert disparadores.por_agenda(con, datetime(2026, 10, 26, 9, 52, tzinfo=MX), ev) == 1, "vuelve el canal: sale"
    assert memoria.leer(con, "avisos_error") is None
    assert disparadores.por_agenda(con, datetime(2026, 10, 26, 9, 53, tzinfo=MX), ev) == 0, "y una sola vez"


def test_los_avisos_que_no_se_reintentan_tambien_dejan_rastro(con, monkeypatch):
    from hub.secretario import avisos

    def sin_canal(*a, **k):
        raise avisos.SinCanal("webpush: sin suscripción")
    monkeypatch.setattr(avisos, "mandar", sin_canal)
    assert avisos.intentar(con, "uno", "mover_compromiso") is None
    assert avisos.intentar(con, "dos", "mover_compromiso") is None
    assert con.execute("SELECT COUNT(*) FROM bitacora WHERE accion = 'mover_compromiso' AND ok = 0").fetchone()[0] == 2


def test_los_eventos_de_todo_el_dia_no_avisan_minutos_antes(con, antes_de_evento):
    ev = [{"id": "e2", "titulo": "Vacaciones", "inicio": "2026-10-26"}]
    assert disparadores.por_agenda(con, datetime(2026, 10, 26, 0, 5, tzinfo=MX), ev) == 0


def test_la_agenda_se_consulta_cada_pocos_minutos_no_en_cada_vuelta(con, antes_de_evento, monkeypatch):
    llamadas = []
    monkeypatch.setattr(agenda, "disponible", lambda: None)
    monkeypatch.setattr(agenda, "eventos", lambda d, h, n=50: llamadas.append(1) or [])
    disparadores.por_agenda(con)
    disparadores.por_agenda(con)
    assert len(llamadas) == 1


# ── en una llamada sin grabarla ──────────────────────────────────────────────

def _latido(monkeypatch, **datos):
    from hub import reuniones
    monkeypatch.setattr(reuniones, "agente", lambda: {"vivo": True, "grabando": None, "apps": [], **datos})


def test_teams_sonando_cuenta_como_reunion_aunque_no_se_grabe(monkeypatch):
    _latido(monkeypatch, apps=[{"nombre": "ms-teams.exe", "pid": 1, "activa": True}])
    assert disparadores.en_reunion() is True


def test_teams_abierto_pero_callado_no_es_una_reunion(monkeypatch):
    _latido(monkeypatch, apps=[{"nombre": "ms-teams.exe", "pid": 1, "activa": False},
                               {"nombre": "Spotify.exe", "pid": 2, "activa": True}])
    assert disparadores.en_reunion() is False


def test_las_apps_de_llamada_se_amplian_en_ajustes(monkeypatch):
    (memoria.carpeta() / "secretario.yml").write_text("apps_de_llamada: [Discord.exe]\n", encoding="utf-8")
    _latido(monkeypatch, apps=[{"nombre": "Discord.exe", "pid": 1, "activa": True}])
    assert disparadores.en_reunion() is True


def test_sin_agente_vivo_no_hay_reunion(monkeypatch):
    from hub import reuniones
    monkeypatch.setattr(reuniones, "agente", lambda: {"vivo": False, "grabando": "x"})
    assert disparadores.en_reunion() is False


# ── consultas del ecosistema, sobre un hub de verdad ─────────────────────────

@pytest.fixture
def hub_con_datos():
    from hub import db
    h = db.conectar()
    db.inicializar(h)
    h.execute("INSERT INTO proyecto (id, nombre) VALUES ('web', 'Web')")
    h.execute("INSERT INTO slot (proyecto_id, nombre, nota, status, creado_en) VALUES ('web', 'Login', 'rehacer', 'activo', ?)",
              (memoria.ahora(),))
    h.execute("INSERT INTO servicio (contenedor, proyecto_id, imagen, estado, detalle, ultima_vez_visto, medido_en)"
              " VALUES ('web-db', 'web', 'postgres:16', 'running', 'Up 2 days', ?, ?)", (memoria.ahora(), memoria.ahora()))
    yield h
    h.close()


def test_las_consultas_del_hub_contestan_compacto(con, hub_con_datos):
    t = herramientas.todas()
    s = t["hub_servicios"].funcion(con, {})
    assert s["vivos"] == 1 and s["contenedores"][0] == {"nombre": "web-db", "proyecto": "Web", "estado": "running",
                                                         "detalle": "Up 2 days", "imagen": "postgres:16"}
    slots = t["hub_slots"].funcion(con, {"proyecto": "web"})
    assert slots[0]["nombre"] == "Login" and slots[0]["sesion"] == "sin abrir"
    r = t["hub_respaldo"].funcion(con, {})
    assert {"commits_sin_respaldo", "repos_en_riesgo", "repos"} <= set(r)
    assert isinstance(t["hub_maquina"].funcion(con, {}), list)


# ── abrir en la PC, por el agente de Reuniones (decisión 313) ────────────────

def test_el_agente_recibe_la_pantalla_una_vez_y_su_confirmacion_cierra_el_circulo():
    from hub import reuniones
    pid = reuniones.pedir_abrir("/trabajo?slot=3")
    r = reuniones.latido({"agente": "0.2.0"})
    assert r["abrir"] == [{"id": pid, "ruta": "/trabajo?slot=3"}]
    assert reuniones.latido({"agente": "0.2.0"})["abrir"] == [], "una sola vez"
    assert not reuniones.abierta(pid)
    reuniones.latido({"agente": "0.2.0", "abiertas": [pid]})
    assert reuniones.abierta(pid)


@pytest.mark.parametrize("ruta", ["https://malo.example", "//malo.example/x", "trabajo", "/a\\b", "/a b"])
def test_solo_se_piden_pantallas_del_hub(ruta):
    from hub import reuniones
    with pytest.raises(ValueError):
        reuniones.pedir_abrir(ruta)


def test_un_pedido_de_hace_mas_de_un_minuto_ya_no_se_abre(monkeypatch):
    from hub import reuniones
    reuniones.pedir_abrir("/respaldo")
    t = __import__("time").time()
    monkeypatch.setattr(reuniones.time, "time", lambda: t + 120)
    assert reuniones.latido({})["abrir"] == []


def test_sin_agente_conectado_abrir_en_la_pc_lo_dice(con, monkeypatch):
    from hub import reuniones
    monkeypatch.setattr(reuniones, "agente", lambda: {"vivo": False})
    r = herramientas.usar_accion(con, piezas.acciones()["abrir_en_pc"], {"ruta": "/trabajo"})
    assert r["hecho"] is False and "agente de Windows no está conectado" in r["error"]


def test_abrir_en_la_pc_espera_a_que_el_agente_confirme(con, monkeypatch):
    import threading
    from hub import reuniones
    monkeypatch.setattr(reuniones, "agente", lambda: {"vivo": True})

    def agente_de_windows():
        # Lo que haría el agente en su siguiente latido: recoger y confirmar.
        for _ in range(30):
            pedidos = reuniones.latido({})["abrir"]
            if pedidos:
                reuniones.latido({"abiertas": [p["id"] for p in pedidos]})
                return
            __import__("time").sleep(0.1)

    threading.Thread(target=agente_de_windows).start()
    r = herramientas.usar_accion(con, piezas.acciones()["abrir_en_pc"], {"ruta": "/respaldo"})
    assert r == {"hecho": True, "resultado": "abierta en la PC: /respaldo"}


# ── grabar una reunión (definición 9.1) ──────────────────────────────────────

def _agente(grabando=False, apps=()):
    return {"vivo": True, "grabando": grabando, "monitores": [{"n": 1}, {"n": 3}],
            "microfonos": [{"n": 49}], "apps": [dict(a) for a in apps]}


def test_grabar_repite_lo_de_la_ultima_vez_y_prefiere_la_llamada_que_suena(con, monkeypatch):
    from hub import reuniones
    reuniones._escribir(reuniones.carpeta() / "orden.json",
                        {"grabar": False, "monitor": 3, "app": "chrome.exe", "micro": "49"})
    estado = {"grabando": False}
    apps = [{"nombre": "chrome.exe", "pid": 1, "activa": False}, {"nombre": "ms-teams.exe", "pid": 2, "activa": True}]

    def agente():
        a = _agente(estado["grabando"], apps)
        estado["grabando"] = bool(reuniones.orden().get("grabar"))   # el agente empieza al leer la orden
        return a

    monkeypatch.setattr(reuniones, "agente", agente)
    r = piezas.acciones()["grabar_reunion"].ejecutar(con, {"titulo": "Daily"})
    o = reuniones.orden()
    assert o["grabar"] is True and o["monitor"] == 3 and o["app"] == "ms-teams.exe" and o["titulo"] == "Daily"
    assert r.startswith("grabando (") and "ms-teams.exe" in r
    assert piezas.acciones()["parar_grabacion"].ejecutar(con, {}).startswith("parada la grabación")
    assert reuniones.orden()["grabar"] is False


def test_grabar_reconoce_la_app_de_llamada_que_el_dueno_anadio_en_ajustes(con, monkeypatch):
    """C-0067: la detección leía `apps_de_llamada` de `secretario.yml` y esta
    acción la constante: una app añadida disparaba la grabación, pero se
    grababa la app de la última vez en vez de la que sonaba."""
    from hub import reuniones
    (memoria.carpeta() / "secretario.yml").write_text("apps_de_llamada: [Discord.exe]\n", encoding="utf-8")
    reuniones._escribir(reuniones.carpeta() / "orden.json",
                        {"grabar": False, "monitor": 3, "app": "chrome.exe", "micro": "49"})
    estado = {"grabando": False}
    apps = [{"nombre": "chrome.exe", "pid": 1, "activa": False}, {"nombre": "Discord.exe", "pid": 2, "activa": True}]

    def agente():
        a = _agente(estado["grabando"], apps)
        estado["grabando"] = bool(reuniones.orden().get("grabar"))
        return a

    monkeypatch.setattr(reuniones, "agente", agente)
    piezas.acciones()["grabar_reunion"].ejecutar(con, {})
    assert reuniones.orden()["app"] == "Discord.exe"


def test_grabar_sin_una_grabacion_anterior_dice_que_la_primera_va_por_la_pantalla(con, monkeypatch):
    from hub import reuniones
    monkeypatch.setattr(reuniones, "agente", lambda: _agente())
    with pytest.raises(RuntimeError, match="la primera"):
        piezas.acciones()["grabar_reunion"].ejecutar(con, {})


def test_grabar_pide_permiso_y_parar_no(con):
    acciones = piezas.acciones()
    assert acciones["grabar_reunion"].nivel_inicial == "ask"
    assert acciones["parar_grabacion"].nivel_inicial == "auto"
