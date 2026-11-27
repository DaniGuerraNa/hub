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


class Delicada(piezas.Accion):
    """Tiene vuelta atrás, pero el acto es del dueño: pregunta siempre (C-0422)."""
    id, nombre, riesgo, nivel_inicial, siempre_pregunta = "delicada", "Hacer lo delicado", "reversible", "ask", True
    hechas = 0

    def ejecutar(self, con, params):
        Delicada.hechas += 1
        return "hecho"


def test_lo_que_pregunta_siempre_no_pasa_a_auto_aunque_tenga_vuelta_atras(monkeypatch):
    """El techo era sólo por riesgo: para que «archivar» preguntara siempre
    había que llamarlo «No tiene vuelta atrás», que es falso."""
    monkeypatch.setattr(piezas, "niveles", lambda: {"delicada": "auto"})
    assert piezas.con_techo(Delicada()) and piezas.nivel(Delicada()) == "ask"
    monkeypatch.setattr(piezas, "niveles", lambda: {"delicada": "never"})
    assert piezas.nivel(Delicada()) == "never", "quitársela sí puede"


def test_con_techo_es_lo_que_no_tiene_vuelta_lo_que_sale_y_lo_que_pregunta_siempre():
    class De(piezas.Accion):
        pass

    for riesgo, siempre, esperado in (("lectura", False, False), ("reversible", False, False),
                                      ("irreversible", False, True), ("sale-de-la-maquina", False, True),
                                      ("reversible", True, True), ("lectura", True, True)):
        a = De()
        a.riesgo, a.siempre_pregunta = riesgo, siempre
        assert piezas.con_techo(a) is esperado, (riesgo, siempre)
    assert piezas.Accion.siempre_pregunta is False, "de fábrica, ninguna"


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


# ── sin el dueño delante: un `pide` no hace, pide (C-0318) ───────────────────

#: Lo que hoy está en `auto` y el modelo podía hacer en un `pide`, sin hilo:
#: medido el 13-nov con los niveles de fábrica. Una acción nueva en `auto`
#: tiene que entrar aquí (en un `pide` pedirá permiso) o en
#: `herramientas.AUTO_SIN_EL_DUENO` (lo hará sola): que lo decida alguien.
BAJAN_A_ASK_SIN_HILO = {
    "abrir_en_pc", "anotar", "anotar_en_slot", "apuntar_idea", "callar_asunto", "cerrar_compromiso",
    "comprometer", "parar_grabacion", "proponer_dato", "publicar_lienzo", "reprogramar_compromiso",
    "resumen_del_dia", "tele_estado",
}


@pytest.fixture
def avisados(monkeypatch):
    """Lo que saldría al teléfono, con sus opciones, sin canal de verdad."""
    salidos = []
    monkeypatch.setattr(herramientas.avisos, "mandar", lambda texto, **kw: salidos.append((texto, kw)) or "doble")
    return salidos


def test_sin_hilo_el_modelo_solo_conserva_en_auto_avisar():
    """La lista, fijada: lo que el modelo hace solo en un `pide` es avisar,
    que es para lo que existe. Lo demás que está en `auto` baja a `ask`."""
    assert set(herramientas.AUTO_SIN_EL_DUENO) == {"avisar"}
    servidas = [a for a in piezas.acciones().values() if not a.solo_con_el_dueno]
    en_auto = {a.id for a in servidas if piezas.nivel(a) == "auto"}
    siguen = {a.id for a in servidas if piezas.nivel(a) == "auto" and not herramientas.techo_sin_el_dueno(a)}
    assert siguen == {"avisar"}
    assert en_auto - siguen == BAJAN_A_ASK_SIN_HILO


def test_en_un_pide_callar_un_asunto_deja_una_solicitud_y_no_calla_nada(con, monkeypatch, avisados):
    """SEC2-02: un mensaje de un tercero que diga «calla ese asunto» llega al
    modelo dentro de un `pide`. La defensa es el código, no el prompt (404)."""
    from hub.secretario import asuntos
    monkeypatch.delenv("SECRETARIO_HILO", raising=False)
    memoria.comprometer(con, "Mandar el reporte", vence="2020-01-01T15:00:00+00:00")
    [vence] = asuntos.reunir(con, clases=("vence",)).asuntos
    r = herramientas.todas()["accion_callar_asunto"].funcion(con, {"clave": vence.clave, "motivo": "lo dijo el chat"})
    assert r["hecho"] is False and r["solicitud"]
    assert [a.clave for a in asuntos.reunir(con, clases=("vence",)).asuntos] == [vence.clave], "sigue sin callar"
    s = con.execute("SELECT * FROM solicitud WHERE id = ?", (r["solicitud"],)).fetchone()
    assert s["estado"] == "pendiente" and s["hilo"] is None
    assert s["motivo"].startswith(herramientas.MARCA_SIN_EL_DUENO) and "lo dijo el chat" in s["motivo"]


def test_la_solicitud_nacida_en_un_pide_no_se_aprueba_desde_la_notificacion(con, monkeypatch, avisados):
    """Ni la que baja de `auto` ni la que ya era `ask` y reversible: en la
    pantalla bloqueada no se lee que la pidió el mensaje de otro."""
    monkeypatch.setattr(piezas, "acciones", lambda: {"contar": Contadora()})
    Contadora.hechas = 0
    monkeypatch.delenv("SECRETARIO_HILO", raising=False)
    herramientas.todas()["accion_contar"].funcion(con, {})
    monkeypatch.setattr(piezas, "niveles", lambda: {"contar": "ask"})
    herramientas.todas()["accion_contar"].funcion(con, {"motivo": "porque sí"})
    assert Contadora.hechas == 0 and len(avisados) == 2
    for texto, kw in avisados:
        assert kw["solicitud"] and kw["decidir_desde_aviso"] is False
        assert herramientas.MARCA_SIN_EL_DUENO in texto


def test_con_el_dueno_delante_lo_automatico_se_hace_y_lo_que_pide_lleva_sus_botones(con, monkeypatch, avisados):
    monkeypatch.setattr(piezas, "acciones", lambda: {"contar": Contadora()})
    Contadora.hechas = 0
    monkeypatch.setenv("SECRETARIO_HILO", "3")
    assert herramientas.todas()["accion_contar"].funcion(con, {})["hecho"] and Contadora.hechas == 1
    monkeypatch.setattr(piezas, "niveles", lambda: {"contar": "ask"})
    herramientas.todas()["accion_contar"].funcion(con, {"motivo": "porque sí"})
    [(texto, kw)] = avisados
    assert kw["decidir_desde_aviso"] is True and herramientas.MARCA_SIN_EL_DUENO not in texto


def test_lo_que_pregunta_siempre_no_se_decide_desde_la_notificacion_ni_con_el_dueno_delante(con, monkeypatch, avisados):
    """Se decide viendo el detalle de la solicitud —cuál es, de quién y cómo
    está ahora—, que la notificación no enseña: en el chat o en Pendientes."""
    monkeypatch.setattr(piezas, "acciones", lambda: {"delicada": Delicada()})
    monkeypatch.setattr(piezas, "niveles", lambda: {"delicada": "auto"})
    Delicada.hechas = 0
    monkeypatch.setenv("SECRETARIO_HILO", "3")
    r = herramientas.todas()["accion_delicada"].funcion(con, {"motivo": "me lo pediste"})
    assert r["hecho"] is False and r["solicitud"] and Delicada.hechas == 0
    [(texto, kw)] = avisados
    assert kw["decidir_desde_aviso"] is False and kw["solicitud"] == r["solicitud"]
    assert texto == "Hacer lo delicado: me lo pediste"


def test_en_un_pide_avisar_sigue_saliendo_solo(con, monkeypatch):
    """Es para lo que existe el `pide`: su respuesta va al teléfono."""
    monkeypatch.delenv("SECRETARIO_HILO", raising=False)
    r = herramientas.todas()["accion_avisar"].funcion(con, {"texto": "llegó lo que esperabas"})
    assert r["hecho"] and con.execute("SELECT COUNT(*) FROM solicitud").fetchone()[0] == 0


def test_en_un_pide_la_lectura_de_acciones_dice_el_nivel_que_le_va_a_tocar(con, monkeypatch):
    monkeypatch.delenv("SECRETARIO_HILO", raising=False)
    sin_el = {a["id"]: a["nivel"] for a in herramientas.todas()["acciones"].funcion(con, {})}
    assert sin_el["callar_asunto"] == "ask" and sin_el["avisar"] == "auto" and "mirar_en_pc" not in sin_el
    monkeypatch.setenv("SECRETARIO_HILO", "3")
    con_el = {a["id"]: a["nivel"] for a in herramientas.todas()["acciones"].funcion(con, {})}
    assert con_el["callar_asunto"] == "auto" and con_el["mirar_en_pc"] == "auto"


def test_el_haz_de_un_disparador_no_cambia(con, avisados):
    """Lo que el dueño escribió en `haz` no lo decide el modelo: sigue con su
    nivel, sin marca, y su permiso (si lo pide) con sus botones."""
    from hub.secretario import disparadores
    disparadores._hacer(con, {"nombre": "apunta", "haz": "anotar", "texto": "llegó {autor}"}, {"autor": "alguien"})
    assert [n["texto"] for n in memoria.notas(con)] == ["llegó alguien"]
    Contadora.hechas = 0
    herramientas.usar_accion(con, Contadora(), {}, motivo="disparador «x»", techo="ask")
    [(texto, kw)] = avisados
    assert kw["decidir_desde_aviso"] is True and herramientas.MARCA_SIN_EL_DUENO not in texto


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
    assert {"buscar", "compromisos", "ahora", "accion_comprometer", "accion_avisar"} <= nombres
    # Sin calendario que cree, `agendar` sólo podía fallar (C-0391).
    assert "accion_agendar" not in nombres
    # Sin hilo no hay turno del que colgar una tarjeta ni que escalar (SEC-39).
    assert not {"tarjeta", "pedir_modelo_mayor"} & nombres
    assert "lambdas" in respuestas[3]["result"]["content"][0]["text"]
    assert respuestas[4]["result"]["isError"] is True


def test_lo_que_cuelga_de_un_turno_solo_se_ofrece_con_el_dueno_delante(con, monkeypatch):
    """SEC-39: en un `pide` no hay turno. `pedir_modelo_mayor` dejaba la
    clave `escalar:` huérfana y le decía al modelo «responde sólo «…»», que
    llegaba tal cual al teléfono; `tarjeta` fallaba. Ni se ofrecen, y llamadas
    igual no dejan nada."""
    for nombre in ("tarjeta", "pedir_modelo_mayor"):
        assert nombre in herramientas.todas(con_el_dueno=True)
        assert nombre not in herramientas.todas(con_el_dueno=False)
    monkeypatch.delenv("SECRETARIO_HILO", raising=False)
    r = herramientas.todas(con_el_dueno=True)["pedir_modelo_mayor"].funcion(con, {"motivo": "es difícil"})
    assert r["ok"] is False and "…" not in json.dumps(r, ensure_ascii=False)
    assert memoria.leer(con, "escalar:") is None


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


class SinConfigurar(piezas.Accion):
    """Una acción que hoy sólo podría fallar: le falta su configuración."""
    id, nombre, riesgo, nivel_inicial = "sin_configurar", "Algo sin configurar", "reversible", "auto"
    como_configurar = "Se configura en su sitio."
    disponible = staticmethod(lambda: False)

    def ejecutar(self, con, params):
        raise AssertionError("sin configurar no debería llegar a hacerse")


def test_una_accion_sin_configurar_no_se_le_ofrece_al_modelo_ni_sale_en_sus_acciones(con, monkeypatch):
    """SEC-08: se le servían acciones que sólo podían fallar, y cada una
    costaba esquema en cada turno y un intento con su error técnico."""
    monkeypatch.setattr(piezas, "acciones", lambda: {"contar": Contadora(), "sin_configurar": SinConfigurar()})
    servidas = herramientas.todas(con_el_dueno=True)
    assert "accion_contar" in servidas and "accion_sin_configurar" not in servidas
    assert {a["id"] for a in servidas["acciones"].funcion(con, {})} == {"contar"}
    assert "accion_sin_configurar" not in herramientas.todas(con_el_dueno=False)


def test_un_disponible_que_revienta_cuenta_como_sin_configurar_y_no_tumba_la_lista(monkeypatch):
    class Rota(SinConfigurar):
        id = "rota"
        disponible = staticmethod(lambda: 1 / 0)

    monkeypatch.setattr(piezas, "acciones", lambda: {"contar": Contadora(), "rota": Rota()})
    assert {n for n in herramientas.todas(con_el_dueno=True) if n.startswith("accion_")} == {"accion_contar"}


def test_toda_accion_con_disponible_dice_donde_se_configura():
    """Confianza la sigue enseñando sin configurar: sin esto, sólo diría que no."""
    for a in piezas.acciones().values():
        if a.disponible is not None:
            assert a.como_configurar.strip(), a.id


def test_poner_en_el_calendario_solo_se_ofrece_con_un_calendario_que_crea(monkeypatch):
    """SEC-07 y SEC-08: sin calendario `agendar` sólo podía fallar, y con la
    dirección iCal —el paso de dos minutos que se le propone al dueño—
    también: se lee, pero no se crea. Confianza dice que hace falta Google."""
    from hub.secretario import agenda
    a = piezas.acciones()["agendar"]
    assert "accion_agendar" not in herramientas.todas(con_el_dueno=True)
    assert "Google" in a.como_configurar and "google-entrar" in a.como_configurar

    ical, google = piezas.proveedores("agenda")["ical"], piezas.proveedores("agenda")["google"]
    monkeypatch.setattr(ical, "disponible", lambda: None)
    monkeypatch.setattr(agenda, "actual", lambda: ical)
    servidas = herramientas.todas(con_el_dueno=True)
    assert "agenda" in servidas and "accion_agendar" not in servidas

    monkeypatch.setattr(google, "disponible", lambda: None)
    monkeypatch.setattr(agenda, "actual", lambda: google)
    servidas = herramientas.todas(con_el_dueno=True)
    assert "agenda" in servidas and "accion_agendar" in servidas


def test_la_agenda_sin_conectar_no_se_ofrece_y_si_se_llama_igual_lo_dice(con):
    """Sin conectar no se ofrece (C-0408); un proceso del MCP abierto antes de
    desconectarla aún puede llamarla, y entonces dice qué falta."""
    assert "agenda" not in herramientas.todas()
    r = next(h for h in herramientas.LECTURAS if h.nombre == "agenda").funcion(con, {})
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



# ── la hora del aviso, la misma regla que el triaje (C-0066) ─────────────────
# Apuntar o mover un compromiso por la acción avisaba a la hora del plazo,
# justo lo que el triaje dejó de hacer el 27-oct porque llegaba tarde.

def test_apuntar_un_plazo_con_hora_sin_aviso_avisa_media_hora_antes(con, monkeypatch):
    monkeypatch.setenv("TZ", "America/Mexico_City")
    r = herramientas.usar_accion(con, piezas.acciones()["comprometer"],
                                 {"que": "Mandar la propuesta", "vence": "2099-10-23T12:00"})
    assert r["hecho"] is True, r
    c = memoria.compromisos(con)[0]
    assert c["vence"] == "2099-10-23T18:00:00+00:00" and c["recordar_en"] == "2099-10-23T17:30:00+00:00"


def test_apuntar_un_plazo_de_solo_un_dia_avisa_esa_mañana_a_las_9(con, monkeypatch):
    monkeypatch.setenv("TZ", "America/Mexico_City")
    herramientas.usar_accion(con, piezas.acciones()["comprometer"], {"que": "Pagar la luz", "vence": "2099-10-23"})
    assert memoria.compromisos(con)[0]["recordar_en"] == "2099-10-23T15:00:00+00:00"


def test_apuntar_con_aviso_explicito_respeta_su_hora_aunque_haya_plazo(con, monkeypatch):
    monkeypatch.setenv("TZ", "America/Mexico_City")
    herramientas.usar_accion(con, piezas.acciones()["comprometer"],
                             {"que": "Mandar la propuesta", "vence": "2099-10-23T12:00", "recordar_en": "2099-10-22T20:00"})
    assert memoria.compromisos(con)[0]["recordar_en"] == "2099-10-23T02:00:00+00:00"


def test_apuntar_un_plazo_ya_pasado_sin_aviso_no_suena_de_golpe(con, monkeypatch):
    monkeypatch.setenv("TZ", "America/Mexico_City")
    r = herramientas.usar_accion(con, piezas.acciones()["comprometer"],
                                 {"que": "Llamar al banco", "vence": "2020-01-02T12:00"})
    assert r["hecho"] is True and "con aviso" not in r["resultado"], r
    c = memoria.compromisos(con)[0]
    assert c["vence"] and c["recordar_en"] is None


def test_mover_solo_el_plazo_avisa_media_hora_antes_del_nuevo(con, monkeypatch):
    monkeypatch.setenv("TZ", "America/Mexico_City")
    i = memoria.comprometer(con, "Llamar a Ana")
    r = herramientas.usar_accion(con, piezas.acciones()["reprogramar_compromiso"], {"id": i, "vence": "2099-10-23T12:00"})
    assert r["hecho"] is True and "2099-10-23 11:30" in r["resultado"], r
    assert memoria.compromisos(con)[0]["recordar_en"] == "2099-10-23T17:30:00+00:00"


def test_mover_el_plazo_conserva_la_antelacion_que_tenia_el_aviso(con, monkeypatch):
    """Lo mismo que hace el triaje al mover un pendiente (`_mover`, 333)."""
    monkeypatch.setenv("TZ", "America/Mexico_City")
    i = memoria.comprometer(con, "Preparar la demo", vence="2099-10-23T18:00:00+00:00",
                            recordar_en="2099-10-23T16:00:00+00:00")
    herramientas.usar_accion(con, piezas.acciones()["reprogramar_compromiso"], {"id": i, "vence": "2099-10-24T15:00"})
    c = memoria.compromisos(con)[0]
    assert c["vence"] == "2099-10-24T21:00:00+00:00" and c["recordar_en"] == "2099-10-24T19:00:00+00:00"


def test_mover_a_un_dia_sin_hora_avisa_esa_mañana_a_las_9(con, monkeypatch):
    monkeypatch.setenv("TZ", "America/Mexico_City")
    i = memoria.comprometer(con, "Pagar la luz")
    herramientas.usar_accion(con, piezas.acciones()["reprogramar_compromiso"], {"id": i, "vence": "2099-10-23"})
    assert memoria.compromisos(con)[0]["recordar_en"] == "2099-10-23T15:00:00+00:00"


def test_mover_un_plazo_al_pasado_no_deja_un_aviso_que_suene_de_golpe(con, monkeypatch):
    monkeypatch.setenv("TZ", "America/Mexico_City")
    i = memoria.comprometer(con, "Llamar al banco")
    r = herramientas.usar_accion(con, piezas.acciones()["reprogramar_compromiso"], {"id": i, "vence": "2020-01-02T12:00"})
    assert r["hecho"] is True and "sin aviso" in r["resultado"], r
    assert memoria.compromisos(con)[0]["recordar_en"] is None


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


# ── los «no puedo» quedan apuntados (C-0247) ─────────────────────────────────

def test_no_se_hacer_apunta_el_hueco_en_la_bitacora_y_nada_mas(con):
    r = herramientas.todas()["no_se_hacer"].funcion(
        con, {"que": "cancelar una cita en el calendario", "por_que": "no hay acción para ello"})

    filas = memoria.bitacora(con)
    assert r["hecho"] is True and len(filas) == 1
    assert filas[0]["accion"] == "hueco" and "cancelar una cita" in filas[0]["params"]
    assert filas[0]["motivo"] == "no hay acción para ello"
    assert not memoria.compromisos(con) and con.execute("SELECT COUNT(*) FROM solicitud").fetchone()[0] == 0


def test_no_se_hacer_oculta_las_llaves_y_acota_la_longitud(con):
    herramientas.todas()["no_se_hacer"].funcion(
        con, {"que": "usar la clave sk-ant-api03-" + "a" * 40 + " " + "x" * 500, "por_que": "y" * 500})

    fila = memoria.bitacora(con)[0]
    assert "sk-ant-api03" not in fila["params"]
    assert len(json.loads(fila["params"])["que"]) <= herramientas.HUECO_MAXIMO
    assert len(fila["motivo"]) <= herramientas.HUECO_MAXIMO


def test_no_se_hacer_sin_decir_que_falta_no_apunta_nada(con):
    r = herramientas.todas()["no_se_hacer"].funcion(con, {"que": "  ", "por_que": "algo"})

    assert r["hecho"] is False and memoria.bitacora(con) == []


@pytest.mark.parametrize("contenido", ["- motor\n- dueno\n", "solo una frase\n", ": : roto\n"])
def test_un_secretario_yml_que_no_es_un_diccionario_vale_vacio_en_todas_sus_lecturas(contenido):
    """C-0495: `piezas.ajustes` es la única que lee `secretario.yml`; una lista,
    un texto suelto o un YAML roto valen `{}` y nadie revienta al leerlo."""
    from hub.secretario import conversacion, motor
    (memoria.carpeta() / "secretario.yml").write_text(contenido, encoding="utf-8")
    assert motor.actual() is motor.MOTORES["suscripcion"]
    assert conversacion._dueno() == "su dueño"
    assert conversacion.ajustes() == {}
    assert piezas.ajustes() == {}
    assert piezas.ajuste("motor") is None


def test_secretario_yml_se_lee_en_un_solo_sitio():
    """C-0495: dos lectoras de lo mismo acabaron haciendo cosas distintas."""
    import pathlib
    import re
    nombre = re.compile(r"""["']secretario\.yml["']""")   # el nombre como literal, no en un docstring
    raiz = pathlib.Path(piezas.__file__).parents[1]
    lectoras = [str(p.relative_to(raiz)) for p in raiz.rglob("*.py")
                if nombre.search(p.read_text(encoding="utf-8"))]
    assert lectoras == ["secretario/piezas.py"]
