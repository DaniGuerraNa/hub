"""El contrato de las piezas y los niveles de confianza (decisiones 300 y 303)."""

from __future__ import annotations

import json
import subprocess
import sys

import pytest

from hub import config
from hub.secretario import herramientas, memoria, piezas

# Los avisos de estos tests salen por el timbre de Telegram (el respaldo, decisión 310).
pytestmark = pytest.mark.usefixtures("canal_telegram")


@pytest.fixture
def con():
    c = memoria.conectar()
    yield c
    c.close()


def test_las_piezas_se_descubren_solas():
    assert {"hub", "telegram", "correo"} <= set(piezas.fuentes())
    assert {"anotar", "comprometer", "cerrar_compromiso", "reprogramar_compromiso", "agendar",
            "encargar_al_orquestador", "avisar"} <= set(piezas.acciones())


def test_ninguna_fuente_tiene_forma_de_escribir():
    """Sólo lectura por construcción (1.4 y alcance A): una fuente sólo sabe
    decir si está, listar conversaciones y leer."""
    permitidos = {"disponible", "conversaciones", "leer"}
    for f in piezas.fuentes().values():
        propios = {n for n in dir(type(f)) if not n.startswith("_") and callable(getattr(f, n))}
        assert propios <= permitidos, (f.id, propios - permitidos)


def test_toda_accion_declara_un_riesgo_y_un_nivel_conocidos():
    for a in piezas.acciones().values():
        assert a.riesgo in piezas.RIESGOS, a.id
        assert a.nivel_inicial in piezas.NIVELES, a.id
        assert a.parametros.get("type") == "object", a.id


def test_por_omision_solo_se_lee_el_propio_hub():
    a = piezas.ajustes_fuentes()
    assert a["hub"]["activa"] is True
    assert not (a.get("telegram") or {}).get("activa")


def test_elegir_conversaciones_incluir_manda_y_excluir_quita():
    assert piezas.conversacion_admitida({}, "Cualquiera")
    assert piezas.conversacion_admitida({"incluir": ["Trabajo"]}, "trabajo")
    assert not piezas.conversacion_admitida({"incluir": ["Trabajo"]}, "Familia")
    assert not piezas.conversacion_admitida({"excluir": ["Familia"]}, "Familia")


def test_lo_irreversible_pregunta_aunque_el_dueño_lo_ponga_en_auto(monkeypatch):
    class Peligrosa(piezas.Accion):
        id, riesgo, nivel_inicial = "borrar_todo", "irreversible", "ask"

    monkeypatch.setattr(piezas, "niveles", lambda: {"borrar_todo": "auto"})
    assert piezas.nivel(Peligrosa()) == "ask"


def test_el_nivel_lo_guarda_el_dueño_y_no_acepta_inventos():
    piezas.poner_nivel("agendar", "auto")
    assert piezas.nivel(piezas.acciones()["agendar"]) == "auto"
    with pytest.raises(ValueError):
        piezas.poner_nivel("agendar", "siempre")
    with pytest.raises(ValueError):
        piezas.poner_nivel("no_existe", "auto")


# ── el nivel se mira al usar la acción, no en el prompt ──────────────────────

class Contadora(piezas.Accion):
    id, riesgo, nivel_inicial = "contar", "reversible", "auto"
    hechas = 0

    def ejecutar(self, con, params):
        Contadora.hechas += 1
        return "contado"


def test_en_ask_no_la_hace_deja_la_solicitud_y_avisa_al_telefono(con, monkeypatch):
    from hub import orquestador
    Contadora.hechas = 0
    monkeypatch.setattr(piezas, "niveles", lambda: {"contar": "ask"})
    r = herramientas.usar_accion(con, Contadora(), {"n": 1}, motivo="porque sí")
    assert r["hecho"] is False and r["solicitud"]
    assert Contadora.hechas == 0
    s = con.execute("SELECT * FROM solicitud").fetchone()
    assert s["estado"] == "pendiente" and json.loads(s["params"]) == {"n": 1}
    assert orquestador.timbres_pendientes()


def test_en_never_ni_la_hace_ni_la_pide(con, monkeypatch):
    Contadora.hechas = 0
    monkeypatch.setattr(piezas, "niveles", lambda: {"contar": "never"})
    assert herramientas.usar_accion(con, Contadora(), {})["hecho"] is False
    assert Contadora.hechas == 0
    assert con.execute("SELECT COUNT(*) FROM solicitud").fetchone()[0] == 0


def test_en_auto_la_hace_y_queda_en_la_bitacora_con_su_motivo(con):
    Contadora.hechas = 0
    r = herramientas.usar_accion(con, Contadora(), {}, motivo="me lo pidió")
    assert r == {"hecho": True, "resultado": "contado"} and Contadora.hechas == 1
    b = memoria.bitacora(con)[0]
    assert b["accion"] == "contar" and b["nivel"] == "auto" and b["motivo"] == "me lo pidió"


def test_una_accion_que_falla_lo_dice_y_no_tumba_nada(con):
    class Rota(piezas.Accion):
        id, nivel_inicial = "rota", "auto"

        def ejecutar(self, con, params):
            raise RuntimeError("Google no contestó")

    r = herramientas.usar_accion(con, Rota(), {})
    assert r["hecho"] is False and "Google no contestó" in r["error"]
    assert memoria.bitacora(con)[0]["ok"] == 0


# ── el servidor MCP, ejecutado ───────────────────────────────────────────────

def test_el_servidor_mcp_contesta_el_protocolo_y_sus_herramientas(con):
    from hub.secretario.piezas import Evento
    memoria.guardar_evento(con, Evento(fuente="hub", id_externo="r1", fecha="2026-10-21T10:00:00+00:00",
                                       texto="Se decidió cambiar el host de las lambdas", conversacion="reuniones"))
    entrada = "\n".join(json.dumps(m) for m in [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "buscar", "arguments": {"texto": "lambdas"}}},
        {"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "no_existe", "arguments": {}}},
    ]) + "\n"
    r = subprocess.run([sys.executable, "-m", "hub.secretario.mcp"], input=entrada, capture_output=True, text=True,
                       timeout=60, env={"HUB_HOME": str(config.HUB_HOME), "PATH": "/usr/bin:/bin"})
    respuestas = {m["id"]: m for m in map(json.loads, r.stdout.splitlines())}
    assert set(respuestas) == {1, 2, 3, 4}, r.stderr
    assert respuestas[1]["result"]["protocolVersion"] == "2025-06-18"
    nombres = {t["name"] for t in respuestas[2]["result"]["tools"]}
    assert {"buscar", "compromisos", "ahora", "tarjeta", "accion_comprometer", "accion_agendar"} <= nombres
    assert "lambdas" in respuestas[3]["result"]["content"][0]["text"]
    assert respuestas[4]["result"]["isError"] is True


def test_toda_accion_se_explica_al_dueño_con_sus_palabras():
    """La descripción es para el modelo; en Confianza lee el dueño."""
    for a in piezas.acciones().values():
        assert a.nombre and a.resumen, a.id
        assert "`" not in a.resumen, a.id


# ── capacidades: el que llama no sabe qué proveedor hay detrás (decisión 306) ──

def test_cada_capacidad_trae_su_proveedor_por_omision():
    from hub.secretario import agenda, avisos
    assert agenda.actual().id == "google"
    assert avisos.actual().id == "telegram"


def test_cambiar_de_proveedor_es_elegirlo_y_quien_llama_no_cambia(con, monkeypatch):
    """Recordatorios, permisos y la acción «avisar» salen por el canal elegido sin tocarlos."""
    from hub.secretario import avisos, recordatorios

    salidos = []

    class Paloma(avisos.Canal):
        id, nombre = "paloma", "Paloma mensajera"

        def mandar(self, aviso):
            salidos.append(aviso.texto)

    original = piezas.proveedores
    monkeypatch.setattr(piezas, "proveedores",
                        lambda cap: original(cap) | ({"paloma": Paloma()} if cap == "avisos" else {}))
    (memoria.carpeta() / "secretario.yml").write_text("avisos: paloma\n", encoding="utf-8")

    herramientas.usar_accion(con, piezas.acciones()["avisar"], {"texto": "hola"})
    memoria.comprometer(con, "Llamar a Ana", recordar_en="2020-01-01T00:00:00+00:00")
    recordatorios.revisar(con)
    assert salidos[0] == "hola" and "Llamar a Ana" in salidos[1]


def test_un_proveedor_que_no_existe_se_dice_y_no_cae_en_otro():
    from hub.secretario import agenda
    (memoria.carpeta() / "secretario.yml").write_text("agenda: outlook\n", encoding="utf-8")
    with pytest.raises(LookupError, match="outlook"):
        agenda.actual()


def test_la_agenda_sin_conectar_lo_dice_por_la_herramienta(con):
    r = herramientas.todas()["agenda"].funcion(con, {})
    assert "no está conectada" in r["error"] and "Google Calendar" in r["error"]


# ── proyectos y slots: las mismas funciones que el resto del hub (decisión 307) ──

def test_crear_proyecto_usa_la_funcion_del_hub(monkeypatch):
    from hub import agentes, api
    llamadas = []
    monkeypatch.setattr(agentes, "crear_proyecto", lambda con, *a, **k: llamadas.append(a) or {"id": a[0]})
    monkeypatch.setattr(api, "obtener_proyecto", lambda con, i: {"id": i})
    r = piezas.acciones()["crear_proyecto"].ejecutar(None, {"id": "mi-app", "nombre": "Mi App", "ruta": "/x/mi-app"})
    assert llamadas == [("mi-app", "Mi App", "/x/mi-app", "personal")] and "mi-app" in r


def test_crear_proyecto_no_dice_hecho_si_no_quedo_registrado(monkeypatch):
    from hub import agentes, api
    monkeypatch.setattr(agentes, "crear_proyecto", lambda con, *a, **k: {"id": a[0]})
    monkeypatch.setattr(api, "obtener_proyecto", lambda con, i: None)
    with pytest.raises(RuntimeError, match="no quedó registrado"):
        piezas.acciones()["crear_proyecto"].ejecutar(None, {"id": "a", "nombre": "A", "ruta": "/x/a"})


def test_crear_slot_lo_guarda_en_el_hub_y_rechaza_un_proyecto_que_no_existe(monkeypatch):
    from hub import db
    h = db.conectar()
    db.inicializar(h)
    h.execute("INSERT INTO proyecto (id, nombre, dominio, status, tipo) VALUES ('web', 'Web', 'personal', 'activo', 'proyecto')")
    accion = piezas.acciones()["crear_slot"]
    r = accion.ejecutar(None, {"proyecto": "web", "nombre": "Login", "nota": "rehacer el login"})
    assert "Login" in r
    s = h.execute("SELECT * FROM slot WHERE proyecto_id = 'web'").fetchone()
    assert s["nombre"] == "Login" and s["nota"] == "rehacer el login"
    with pytest.raises(ValueError, match="no hay ningún proyecto"):
        accion.ejecutar(None, {"proyecto": "otro", "nombre": "X"})
    h.close()


def test_las_acciones_de_proyectos_preguntan_al_empezar():
    a = piezas.acciones()
    assert {a[i].nivel_inicial for i in ("crear_proyecto", "anexar_proyecto", "crear_slot")} == {"ask"}


# ── las acciones y lecturas se ejecutan, no sólo se cargan ───────────────────
# 🔴 Medido el 24-oct: tras mover `a_utc` a `tiempo.py`, las acciones de
# compromisos lo seguían importando de `recordatorios` DENTRO de la función.
# Cargaban bien, ningún test las ejecutaba con fecha, y todo «recuérdame…»
# fallaba en producción. Estas pruebas recorren el camino que usa el modelo.

def test_apuntar_un_compromiso_con_fecha_por_la_accion_lo_deja_con_su_aviso(con, monkeypatch):
    monkeypatch.setenv("TZ", "America/Mexico_City")
    r = herramientas.usar_accion(con, piezas.acciones()["comprometer"],
                                 {"que": "Revisar el deploy", "recordar_en": "2026-10-26T10:00"})
    assert r["hecho"] is True, r
    assert "26 10:00" in r["resultado"]
    assert memoria.compromisos(con)[0]["recordar_en"] == "2026-10-26T16:00:00+00:00"


def test_reprogramar_por_la_accion_cambia_la_hora(con, monkeypatch):
    monkeypatch.setenv("TZ", "America/Mexico_City")
    i = memoria.comprometer(con, "Llamar a Ana")
    r = herramientas.usar_accion(con, piezas.acciones()["reprogramar_compromiso"], {"id": i, "recordar_en": "2026-10-27"})
    assert r["hecho"] is True and "2026-10-27 09:00" in r["resultado"], r


def test_cada_lectura_contesta_sin_reventar_con_una_memoria_vacia(con):
    from hub import db
    h = db.conectar()
    db.inicializar(h)
    h.close()
    minimos = {"buscar": {"texto": "algo"}, "mensaje": {"id": 1}, "reunion": {"id": "20260101-000000"}}
    for nombre, h in herramientas.todas().items():
        if nombre.startswith("accion_") or nombre in ("tarjeta", "pedir_modelo_mayor"):
            continue
        h.funcion(con, minimos.get(nombre, {}))   # un error de importación o de nombre revienta aquí


# ── lo que hacía el asistente, ahora del secretario (C-0161) ─────────────────

def _hub_con_slot(nota=""):
    from hub import db, slots
    h = db.conectar()
    db.inicializar(h)
    h.execute("INSERT INTO proyecto (id, nombre, dominio, status, tipo) VALUES ('web', 'Web', 'personal', 'activo', 'proyecto')")
    sid = slots.crear(h, "web", "Login", nota=nota)
    h.commit()
    return h, sid


def test_anotar_en_un_slot_anade_al_final_y_nunca_pisa_la_nota(con):
    h, sid = _hub_con_slot("lo que ya había")
    r = herramientas.usar_accion(con, piezas.acciones()["anotar_en_slot"], {"slot": sid, "texto": "falta el CSRF"})
    assert r["hecho"] is True and "Login" in r["resultado"]
    assert h.execute("SELECT nota FROM slot WHERE id = ?", (sid,)).fetchone()[0] == "lo que ya había\n\nfalta el CSRF"
    h.close()


def test_anotar_en_un_slot_que_no_existe_lo_dice(con):
    h, _ = _hub_con_slot()
    r = herramientas.usar_accion(con, piezas.acciones()["anotar_en_slot"], {"slot": 999, "texto": "x"})
    assert r["hecho"] is False and "no hay ningún slot" in r["error"]
    h.close()


def test_un_lienzo_editado_por_el_dueno_no_se_pisa_sale_al_lado(con):
    from hub import lienzos
    h, _ = _hub_con_slot()
    accion = piezas.acciones()["publicar_lienzo"]
    primero = accion.ejecutar(con, {"proyecto": "web", "titulo": "Plan", "cuerpo": "uno"})
    l = lienzos.leer("web", "plan")
    lienzos.guardar_edicion(l, "lo corregí yo")
    import os, time
    ruta = lienzos.carpeta_de("web") / "plan.md"
    os.utime(ruta, (time.time() + 60, time.time() + 60))   # editado después de publicarse (margen de 2 s)
    accion.ejecutar(con, {"proyecto": "web", "titulo": "Plan", "cuerpo": "dos"})
    assert "plan" in primero and lienzos.leer("web", "plan").cuerpo == "lo corregí yo"
    assert len(lienzos.listar("web")) == 2
    h.close()


def test_las_lecturas_de_kits_y_sesiones_se_ejecutan(con):
    t = herramientas.todas()
    assert "catalogo" in t["kits"].funcion(con, {})
    assert "error" in t["kits"].funcion(con, {"proyecto": "no-existe", "kit": "lienzos"})
    assert isinstance(t["sesiones"].funcion(con, {}), list)
