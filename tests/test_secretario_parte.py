"""El parte de la mañana (C-0171, decisión 360): el resumen del día con la
noche —lo que espera del dueño, lo que pasó y lo que falló—, armado por script,
dejado entero en el chat y con su primera línea al teléfono."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from hub import api, avisos as avisos_hub, db, fichas, orquestador as orq, transcripts
from hub.secretario import conversacion, disparadores, herramientas, memoria, motor, piezas, resumen, tiempo

pytestmark = pytest.mark.usefixtures("canal_telegram")


@pytest.fixture
def con(monkeypatch):
    monkeypatch.setenv("TZ", "America/Mexico_City")
    # Lo que mira de la máquina de quien corre la suite, fuera: el parte no
    # puede depender de qué servicios tiene en marcha ni de sus sesiones.
    monkeypatch.setattr(api, "salud", lambda h: [])
    monkeypatch.setattr(transcripts, "listar_sesiones", lambda *a, **k: [])
    monkeypatch.setattr(motor, "llamar", lambda *a, **k: pytest.fail("el parte no usa el modelo"))
    h = db.conectar()   # la del hub ya existe donde corre el secretario: aquí se crea
    db.inicializar(h)
    h.close()
    c = memoria.conectar()
    yield c
    c.close()


def _timbres() -> list[dict]:
    return [json.loads(t.read_text()) for t in orq.timbres_pendientes()]


def _ficha(carpeta: Path, n: int, titulo: str, estado: str = "esperando", quien: str = "dueno",
           abierta: str = "2026-10-01", gravedad: str | None = None, cerrada: str | None = None) -> None:
    carpeta.mkdir(exist_ok=True)
    cab = {"id": f"C-{n:04d}", "titulo": titulo, "tipo": "ajuste", "tamano": "S", "gravedad": gravedad,
           "estado": estado, "quien": quien, "modulos": [], "abierta": abierta, "cerrada": cerrada}
    import yaml
    (carpeta / f"C-{n:04d}-x.md").write_text("---\n" + yaml.safe_dump(cab, allow_unicode=True) + "---\n\n## Qué\n",
                                             encoding="utf-8")


def _con_fichas(carpeta: Path) -> None:
    (memoria.carpeta() / "secretario.yml").write_text(f"parte_fichas: {carpeta}\n", encoding="utf-8")


# ── qué dice y en qué orden ──────────────────────────────────────────────────

def test_primero_lo_que_espera_de_el_luego_lo_que_paso_y_al_final_lo_que_fallo(con, tmp_path):
    con.execute("INSERT INTO solicitud (accion, params, motivo, creada) VALUES ('crear_slot', '{}', '', ?)",
                (memoria.ahora(),))
    tarea = orq.crear("revisa los logs de anoche")
    with orq.editar(tarea) as t:
        t["estado"] = orq.ACTIVA
    orq.preguntar("¿Borro los temporales o los dejo?")
    memoria.anotar(con, "El deploy se movió al jueves")
    memoria.apuntar(con, "recordatorio", resultado="salió")
    memoria.apuntar(con, "disparador", params={"nombre": "x"}, resultado="no salió: sin canal", ok=False)
    _ficha(tmp_path / "cambios", 7, "Actualizar la BIOS", gravedad="alta")
    _con_fichas(tmp_path / "cambios")

    t = resumen.del_dia(con, noche=True)

    lineas = t.split("\n")
    assert lineas[0] == "Te esperan 1 permiso, 1 pregunta del orquestador y 1 ficha · 1 fallo", \
        "la primera línea es la del teléfono"
    assert t.index("Te espera:") < t.index("De noche:") < t.index("Falló:")
    espera = t[t.index("Te espera:"):t.index("De noche:")]
    assert "1 permiso espera tu sí" in espera
    assert "El orquestador te pregunta: «¿Borro los temporales o los dejo?»" in espera
    assert "1 ficha espera algo tuyo:\n  C-0007 Actualizar la BIOS" in espera
    noche = t[t.index("De noche:"):t.index("Falló:")]
    assert "Orquestador, esperando tu respuesta: «revisa los logs de anoche»" in noche
    assert "Anoté: «El deploy se movió al jueves»" in noche
    assert "Hice 1 cosa: recordatorio (1)" in noche
    assert "disparador: no salió: sin canal" in t[t.index("Falló:"):]


def test_si_no_hay_nada_es_una_sola_linea(con):
    assert resumen.del_dia(con, noche=True) == "Noche tranquila: nada pasó, nada falló y nada te espera."


def test_una_seccion_vacia_no_aparece(con):
    memoria.anotar(con, "Algo que dijo")
    t = resumen.del_dia(con, noche=True)
    assert t.startswith("Nada te espera ni falló de noche.\n\nDe noche:")
    assert "Te espera" not in t and "Falló" not in t


def test_sin_noche_el_resumen_es_el_de_siempre(con):
    memoria.anotar(con, "Algo que dijo")
    assert resumen.del_dia(con) == "Anotado desde ayer: 1\n· Algo que dijo"


def test_lo_de_hace_mas_de_un_dia_no_es_de_anoche(con):
    memoria.apuntar(con, "disparador", resultado="roto", ok=False)
    con.execute("UPDATE bitacora SET cuando = '2020-01-01T00:00:00+00:00'")
    assert "Falló" not in resumen.del_dia(con, noche=True)


def test_lo_que_no_se_puede_leer_se_dice_y_el_resto_sale(con, monkeypatch):
    def roto():
        raise OSError("disco lleno")
    monkeypatch.setattr(orq, "listar", roto)
    memoria.anotar(con, "Algo que dijo")
    t = resumen.del_dia(con, noche=True)
    assert "No pude leer el orquestador: disco lleno" in t
    assert "Anoté: «Algo que dijo»" in t


def test_no_lleva_secretos_aunque_los_traiga_lo_que_lee(con):
    memoria.anotar(con, "La clave es sk-ant-api03-abcdefghijklmnopqrstuvwxyz")
    memoria.apuntar(con, "disparador", resultado="falló con token=supersecreto123", ok=False)
    t = resumen.del_dia(con, noche=True)
    assert "abcdefghijklmnop" not in t and "supersecreto123" not in t
    assert "[secreto oculto]" in t


def test_una_sesion_cuyo_archivo_se_toco_pero_sin_mensajes_nuevos_no_cuenta(con, monkeypatch):
    """El filtro de `listar_sesiones` mira la fecha del archivo; la sesión
    cuenta por su último mensaje (regla 19)."""
    ahora = datetime.now(timezone.utc)
    monkeypatch.setattr(transcripts, "listar_sesiones", lambda *a, **k: [
        {"proyecto_id": "web", "titulo": "Arreglar el login", "fin": ahora.isoformat().replace("+00:00", "Z")},
        {"proyecto_id": "web", "titulo": "Una vieja", "fin": (ahora - timedelta(days=3)).isoformat()},
    ])
    t = resumen.del_dia(con, noche=True)
    assert "1 sesión de Claude:\n  web «Arreglar el login»" in t
    assert "Una vieja" not in t


def test_un_aviso_del_hub_que_sigue_igual_va_a_lo_que_fallo(con):
    h = db.conectar()
    try:
        avisos_hub.anotar(h, "maquina:gpu.temperatura", "caliente", memoria.ahora())
        avisos_hub.marcar_avisado(h, "maquina:gpu.temperatura")
        avisos_hub.anotar(h, "%5", "preguntando", memoria.ahora())
        avisos_hub.marcar_avisado(h, "%5")
        h.commit()
    finally:
        h.close()
    t = resumen.del_dia(con, noche=True)
    assert "1 sesión te pregunta algo en /trabajo" in t[t.index("Te espera:"):t.index("Falló:")]
    assert t.startswith("Te espera 1 sesión que pregunta · 1 fallo")
    assert "Te avisé y sigue igual: gpu.temperatura, caliente" in t[t.index("Falló:"):]


# ── las fichas: sólo donde las hay ───────────────────────────────────────────

def test_sin_parte_fichas_en_secretario_yml_no_hay_seccion_de_fichas(con, tmp_path):
    _ficha(tmp_path / "cambios", 1, "Algo del dueño")
    assert "ficha" not in resumen.del_dia(con, noche=True)


def test_las_fichas_nuevas_y_graves_primero_y_solo_las_que_esperan_al_dueno(con, tmp_path):
    hoy = tiempo.ahora_local().date().isoformat()
    _ficha(tmp_path / "cambios", 1, "Vieja y baja", gravedad="baja")
    _ficha(tmp_path / "cambios", 2, "Vieja y alta", gravedad="alta")
    _ficha(tmp_path / "cambios", 3, "Nueva", abierta=hoy)
    _ficha(tmp_path / "cambios", 4, "Es de Claude", quien="claude")
    _ficha(tmp_path / "cambios", 5, "Ya hecha", estado="hecha", cerrada=hoy)
    _con_fichas(tmp_path / "cambios")
    t = resumen.del_dia(con, noche=True)
    assert "3 fichas esperan algo tuyo (1 desde ayer):\n  C-0003 Nueva\n  C-0002 Vieja y alta\n  C-0001" in t
    assert "Es de Claude" not in t
    assert "Fichas desde ayer: 1 nueva, 1 cerrada" in t


def test_fichas_lista_filtra_y_no_se_cae_por_una_rota(tmp_path):
    _ficha(tmp_path, 1, "Una", estado="anotada", quien="claude")
    _ficha(tmp_path, 2, "Dos")
    (tmp_path / "C-0003-rota.md").write_text("---\nid: [sin cerrar\n---\n", encoding="utf-8")
    assert [f.get("id") for f in fichas.listar(tmp_path)] == ["C-0001", "C-0002", None]
    assert [f["id"] for f in fichas.listar(tmp_path, estado=fichas.ABIERTOS, quien="dueno")] == ["C-0002"]
    assert fichas.listar(tmp_path / "no-existe") == []


# ── la entrega: el chat entero, el teléfono sólo la primera línea ────────────

def test_con_en_chat_el_texto_va_al_chat_y_al_telefono_solo_su_primera_linea(con):
    memoria.anotar(con, "Algo que dijo")
    r = herramientas.usar_accion(con, piezas.acciones()["resumen_del_dia"], {"noche": True, "en_chat": True})
    assert r["hecho"] is True
    h = conversacion.hilo_abierto(con)
    [turno] = conversacion.turnos(con, h["id"])
    assert turno["rol"] == "secretario" and "Anoté: «Algo que dijo»" in turno["texto"]
    [timbre] = _timbres()
    assert "Nada te espera ni falló de noche." in timbre["texto"] and "Algo que dijo" not in timbre["texto"]


def test_sin_parametros_la_accion_sigue_mandando_el_resumen_entero_al_telefono(con):
    memoria.anotar(con, "Algo que dijo")
    herramientas.usar_accion(con, piezas.acciones()["resumen_del_dia"], {})
    assert conversacion.hilo_abierto(con) is None
    assert "Algo que dijo" in _timbres()[0]["texto"]


def test_si_el_aviso_no_sale_el_parte_queda_en_el_chat_y_se_apunta(con, monkeypatch):
    from hub.secretario import avisos

    def sin_canal(*a, **k):
        raise avisos.SinCanal("webpush: sin aparatos")
    monkeypatch.setattr(avisos, "mandar", sin_canal)
    r = herramientas.usar_accion(con, piezas.acciones()["resumen_del_dia"], {"noche": True, "en_chat": True})
    assert r["hecho"] is True and "aviso no salió" in r["resultado"]
    assert conversacion.turnos(con, conversacion.hilo_abierto(con)["id"])
    assert memoria.leer(con, "avisos_error") == "webpush: sin aparatos"


def test_la_linea_del_disparador_de_la_manana_manda_el_parte(con):
    """La que el dueño pone en disparadores.yml, tal cual."""
    disparadores.guardar_crudo('- nombre: parte de la mañana\n  cuando: {horario: "07:30", dias: L-V}\n'
                               '  haz: resumen_del_dia\n  noche: true\n  en_chat: true\n')
    lunes = datetime(2026, 11, 9, 7, 31, tzinfo=tiempo.ahora_local().tzinfo)
    assert disparadores.por_horario(con, lunes) == 1
    [turno] = conversacion.turnos(con, conversacion.hilo_abierto(con)["id"])
    assert turno["texto"].startswith("Noche tranquila")


# ── el hilo que abre: espera a que lo lea y se cierra sin modelo ─────────────

def test_decir_sin_hilo_abre_uno_y_si_hay_uno_abierto_escribe_en_el(con):
    conversacion.decir(con, None, "Primero")
    h = conversacion.hilo_abierto(con)
    conversacion.decir(con, None, "Segundo")
    assert conversacion.hilo_abierto(con)["id"] == h["id"]
    assert [t["texto"] for t in conversacion.turnos(con, h["id"])] == ["Primero", "Segundo"]


def _envejecer(con, horas: float) -> None:
    hace = (datetime.now(timezone.utc) - timedelta(hours=horas)).isoformat(timespec="seconds")
    con.execute("UPDATE hilo SET ultimo = ?", (hace,))


def test_un_hilo_donde_solo_hablo_el_secretario_espera_a_que_lo_lea(con):
    conversacion.decir(con, None, "2 cosas te esperan\n\nTe espera:\n· …")
    _envejecer(con, 1)
    assert conversacion.cerrar_inactivos(con) == 0, "a la media hora el parte seguiría sin leer"
    _envejecer(con, conversacion.ESPERA_SIN_EL_HORAS + 1)
    assert conversacion.cerrar_inactivos(con) == 1


def test_al_cerrarse_sin_que_el_hablara_no_llama_al_modelo_y_guarda_el_texto(con):
    conversacion.decir(con, None, "2 cosas te esperan\n\nTe espera:\n· …")
    conversacion.cerrar(con, conversacion.hilo_abierto(con))
    h = con.execute("SELECT * FROM hilo").fetchone()
    assert h["cerrado"] and h["titulo"] == "2 cosas te esperan"
    assert "Te espera:" not in h["resumen"], "lo que esperaba ayer no entra como vigente en el hilo siguiente"


def test_si_luego_escribe_la_sesion_nace_sabiendo_lo_que_se_le_dijo(con, monkeypatch):
    vistos = []

    def falso(prompt, **kw):
        vistos.append(prompt)
        return motor.Respuesta(texto="Vale.", sesion="s1", segundos=0.1, coste=0, modelo=kw["modelo"],
                               estructurada=None)
    monkeypatch.setattr(motor, "llamar", falso)
    monkeypatch.setattr(conversacion, "sistema", lambda: "S")
    conversacion.decir(con, None, "1 cosa te espera\n\nTe espera:\n· El orquestador te pregunta: «¿Sigo?»")
    conversacion.recibir(con, "dile que sí")
    conversacion.atender(con)
    assert "Lo que ya le dijiste en esta conversación" in vistos[0]
    assert "«¿Sigo?»" in vistos[0] and vistos[0].endswith("dile que sí")


# ── las lecturas que se ampliaron ────────────────────────────────────────────

def test_bitacora_y_avisos_desde_una_hora(con):
    memoria.apuntar(con, "viejo")
    con.execute("UPDATE bitacora SET cuando = '2020-01-01T00:00:00+00:00'")
    memoria.apuntar(con, "nuevo")
    assert [b["accion"] for b in memoria.bitacora(con, desde="2026-01-01T00:00:00+00:00")] == ["nuevo"]
    assert len(memoria.bitacora(con)) == 2
    h = db.conectar()
    try:
        avisos_hub.anotar(h, "hub", "callado", "2020-01-01T00:00:00+00:00")
        avisos_hub.marcar_avisado(h, "hub", "2020-01-01T00:00:00+00:00")
        assert avisos_hub.ultimos(h, desde="2026-01-01T00:00:00+00:00") == []
        assert len(avisos_hub.ultimos(h)) == 1
    finally:
        h.close()


# ── lo que vio el revisor ────────────────────────────────────────────────────

def test_la_primera_linea_cuenta_cosas_y_no_lineas(con):
    for _ in range(3):
        con.execute("INSERT INTO solicitud (accion, params, motivo, creada) VALUES ('crear_slot', '{}', '', ?)",
                    (memoria.ahora(),))
    for _ in range(7):
        memoria.apuntar(con, "disparador", resultado="roto", ok=False)
    t = resumen.del_dia(con, noche=True)
    assert t.split("\n")[0] == "Te esperan 3 permisos · 7 fallos"
    assert "disparador (×7): roto" in t


def test_solo_lo_que_esta_mal_en_la_salud_es_un_fallo(con, monkeypatch):
    monkeypatch.setattr(api, "salud", lambda h: [
        {"nombre": "tmux", "estado": "aviso", "detalle": "No hay tmux abierto. Es normal nada más encender."},
        {"nombre": "hub-canal", "estado": "mal", "detalle": "Parado."},
        {"nombre": "hub-web", "estado": "ok", "detalle": "En marcha."}])
    t = resumen.del_dia(con, noche=True)
    assert "· hub-canal: Parado." in t
    assert "tmux" not in t and t.startswith("1 fallo")


def test_un_aviso_que_no_salio_no_cuenta_dos_veces(con):
    memoria.poner(con, "avisos_error", "webpush: sin aparatos")
    memoria.apuntar(con, "resumen_del_dia", resultado="no salió: webpush: sin aparatos", ok=False)
    memoria.apuntar(con, "recordatorio", resultado="no salió: webpush: sin aparatos", ok=False)
    t = resumen.del_dia(con, noche=True)
    assert t.split("\n")[0] == "2 fallos"
    assert t.count("sin aparatos") == 1
    assert "Los avisos al teléfono no salen (2 avisos perdidos): webpush: sin aparatos" in t


def test_una_agenda_conectada_que_no_se_puede_leer_se_dice(con, monkeypatch):
    from hub.secretario import agenda

    def rota(*a, **k):
        raise OSError("Google no contesta")
    monkeypatch.setattr(agenda, "disponible", lambda: None)
    monkeypatch.setattr(agenda, "eventos", rota)
    assert "No pude leer la agenda: Google no contesta" in resumen.del_dia(con, noche=True)
    assert resumen.del_dia(con) == "Nada pendiente para hoy.", "el resumen de siempre sale igual sin ella"


def test_con_en_chat_y_sin_noche_al_telefono_no_va_una_cabecera_suelta(con):
    memoria.comprometer(con, "Revisar PRs", vence="2020-01-01T15:00:00+00:00")
    herramientas.usar_accion(con, piezas.acciones()["resumen_del_dia"], {"en_chat": True})
    assert _timbres()[0]["texto"].endswith("Tu resumen del día está en el chat.")


# ── lo que vio la revisión cruzada (C-0185) ──────────────────────────────────

def test_los_partes_que_nadie_contesto_no_desplazan_lo_que_se_hablo_de_verdad(con, monkeypatch):
    """Con tres partes cerrados sin respuesta, el contexto de la sesión nueva
    traía sólo partes —«Te esperan 3 fichas · 2 fallos», caducado— y ninguna
    conversación real."""
    real = conversacion.recibir(con, "busca vuelos a Oaxaca")["hilo"]
    con.execute("UPDATE turno SET estado = 'listo'")
    con.execute("UPDATE hilo SET cerrado = ?, titulo = 'Viaje a Oaxaca', resumen = 'Quedó en mirar vuelos.'"
                " WHERE id = ?", (memoria.ahora(), real))
    for _ in range(conversacion.RESUMENES_PREVIOS):
        conversacion.decir(con, None, "Te esperan 3 fichas · 2 fallos\n\nTe espera:\n· …")
        conversacion.cerrar(con, conversacion.hilo_abierto(con))
    # Lo mismo un resumen de sesión que llegó sin hilo.
    conversacion.decir(con, None, "Resumen de la sesión abcd1234:\n\nSe arregló el login.")
    conversacion.cerrar(con, conversacion.hilo_abierto(con))
    vistos = []

    def falso(prompt, **kw):
        vistos.append(prompt)
        return motor.Respuesta(texto="Vale.", sesion="s1", segundos=0.1, coste=0, modelo=kw["modelo"],
                               estructurada=None)
    monkeypatch.setattr(motor, "llamar", falso)
    monkeypatch.setattr(conversacion, "sistema", lambda: "S")
    conversacion.recibir(con, "¿qué tal?")
    conversacion.atender(con)
    assert "Viaje a Oaxaca" in vistos[0]
    assert "Te esperan 3 fichas" not in vistos[0] and "Resumen de la sesión" not in vistos[0]


def _modelo_falso(monkeypatch) -> list[str]:
    vistos: list[str] = []

    def falso(prompt, **kw):
        vistos.append(prompt)
        return motor.Respuesta(texto="Vale.", sesion="s1", segundos=0.1, coste=0, modelo=kw["modelo"],
                               estructurada={"titulo": "", "resumen": "", "notas": []})
    monkeypatch.setattr(motor, "llamar", falso)
    monkeypatch.setattr(conversacion, "sistema", lambda: "S")
    return vistos


def test_el_parte_que_cae_en_una_conversacion_abierta_llega_al_modelo_con_su_hora(con, monkeypatch):
    """Habló a las 7:15 y el parte de las 7:30 entró en ese hilo, que ya tiene
    sesión: al preguntar «¿qué falla?», el modelo sólo recibía eso."""
    vistos = _modelo_falso(monkeypatch)
    conversacion.recibir(con, "hola")
    conversacion.atender(con)
    tid = conversacion.decir(con, None, "Te esperan 2 fallos\n\n· el disparador de la agenda")
    creado = con.execute("SELECT creado FROM turno WHERE id = ?", (tid,)).fetchone()[0]
    conversacion.recibir(con, "¿qué falla?")
    conversacion.atender(con)
    assert "el disparador de la agenda" in vistos[1] and vistos[1].endswith("¿qué falla?")
    assert tiempo.a_local(creado) in vistos[1], "sin la hora, un parte de ayer parece de ahora"
    conversacion.recibir(con, "gracias")
    conversacion.atender(con)
    assert "el disparador de la agenda" not in vistos[2], "lo que ya vio no se le repite"


def test_lo_que_se_le_dijo_antes_de_que_escribiera_va_con_su_hora(con, monkeypatch):
    vistos = _modelo_falso(monkeypatch)
    tid = conversacion.decir(con, None, "1 cosa te espera")
    creado = con.execute("SELECT creado FROM turno WHERE id = ?", (tid,)).fetchone()[0]
    conversacion.recibir(con, "¿cuál?")
    conversacion.atender(con)
    assert tiempo.a_local(creado) in vistos[0] and "1 cosa te espera" in vistos[0]


def test_el_parte_no_resucita_un_hilo_que_el_dio_por_terminado(con, monkeypatch):
    """«Empezar de cero» deja el hilo para que lo cierre la vuelta; si el parte
    salía antes en esa misma vuelta, lo revivía media hora más."""
    _modelo_falso(monkeypatch)
    conversacion.recibir(con, "hola")
    conversacion.atender(con)
    viejo = conversacion.hilo_abierto(con)["id"]
    conversacion.nuevo_hilo(con)
    conversacion.decir(con, None, "Te esperan 2 fallos")
    nuevo = conversacion.hilo_abierto(con)["id"]
    assert nuevo != viejo
    conversacion.cerrar_inactivos(con)
    assert [h["id"] for h in con.execute("SELECT id FROM hilo WHERE cerrado IS NULL")] == [nuevo]


def test_si_el_escribe_pasada_la_media_hora_antes_de_que_se_cierre_sigue_la_misma_charla(con, monkeypatch):
    """Lo vio el revisor de C-0185: abrir otro hilo ahí dejaba al modelo sin
    nada de lo que se acababa de hablar (el viejo aún no tiene resumen)."""
    _modelo_falso(monkeypatch)
    h = conversacion.recibir(con, "busca vuelos a Oaxaca")["hilo"]
    conversacion.atender(con)
    _envejecer(con, 0.6)
    assert conversacion.recibir(con, "¿y el de vuelta?")["hilo"] == h


def test_lo_hecho_de_una_solicitud_en_un_hilo_que_toca_cerrar_va_al_abierto(con, monkeypatch):
    """Las aprobadas van antes que el cierre en la misma vuelta: el «Hecho:»
    caía en el hilo viejo y esa vuelta lo cerraba sin que se viera."""
    _modelo_falso(monkeypatch)
    viejo = conversacion.recibir(con, "crea un slot")["hilo"]
    conversacion.atender(con)
    conversacion.nuevo_hilo(con)
    tid = conversacion.decir(con, viejo, "Hecho: slot creado")
    conversacion.cerrar_inactivos(con)
    donde = con.execute("SELECT hilo FROM turno WHERE id = ?", (tid,)).fetchone()[0]
    assert donde != viejo and donde == conversacion.hilo_abierto(con)["id"]


def test_si_su_turno_dio_error_el_siguiente_vuelve_a_llevar_el_parte(con, monkeypatch):
    """No se sabe si el modelo llegó a verlo: se le vuelve a pasar."""
    vistos = _modelo_falso(monkeypatch)
    conversacion.recibir(con, "hola")
    conversacion.atender(con)
    conversacion.decir(con, None, "Te esperan 2 fallos\n\n· el disparador de la agenda")
    bueno = motor.llamar

    def cae(prompt, **kw):
        raise motor.MotorCaido("la API se cayó")
    monkeypatch.setattr(motor, "llamar", cae)
    conversacion.recibir(con, "¿qué falla?")
    conversacion.atender(con)
    monkeypatch.setattr(motor, "llamar", bueno)
    conversacion.recibir(con, "¿qué falla?")
    conversacion.atender(con)
    assert "el disparador de la agenda" in vistos[-1]


def test_las_marcas_de_voz_e_ingles_valen_aunque_el_turno_lleve_contexto_delante():
    """Con lo no visto o el aviso del corte delante, el turno ya no «empieza
    por» la marca: el sistema no puede pedir eso (C-0185)."""
    assert "empieza por «(" not in conversacion.SISTEMA
    assert "«(por voz)»" in conversacion.SISTEMA and "«(english mode)»" in conversacion.SISTEMA


def test_escribir_justo_despues_de_empezar_de_cero_abre_un_hilo_nuevo(con, monkeypatch):
    _modelo_falso(monkeypatch)
    conversacion.recibir(con, "hola")
    conversacion.atender(con)
    viejo = conversacion.hilo_abierto(con)["id"]
    conversacion.nuevo_hilo(con)
    assert conversacion.recibir(con, "otra cosa")["hilo"] != viejo


def test_el_parte_y_lo_que_el_escribe_a_la_vez_no_abren_dos_hilos(con, monkeypatch):
    """Tres escriben (hub-web, el ciclo con el parte, el hilo de resúmenes):
    mirar si hay hilo y crearlo iban sin transacción, y uno de los dos hilos
    dejaba de verse."""
    import threading
    import time as _time
    web = memoria.conectar()
    real = conversacion.hilo_abierto
    miro = threading.Event()
    fallos = []

    def despacio(c):
        h = real(c)
        if c is web:
            miro.set()
            _time.sleep(0.4)
        return h
    monkeypatch.setattr(conversacion, "hilo_abierto", despacio)

    def parte():
        servicio = memoria.conectar()
        try:
            miro.wait(5)
            conversacion.decir(servicio, None, "Te esperan 2 fallos")
        except Exception as exc:  # noqa: BLE001 — que el test lo vea, no el hilo
            fallos.append(exc)
        finally:
            servicio.close()
    hilo = threading.Thread(target=parte)
    hilo.start()
    conversacion.recibir(web, "hola")
    hilo.join(15)
    assert not fallos
    assert con.execute("SELECT COUNT(*) FROM hilo WHERE cerrado IS NULL").fetchone()[0] == 1
    assert con.execute("SELECT COUNT(*) FROM turno").fetchone()[0] == 2


def test_la_sesion_nueva_lee_lo_dicho_en_el_hilo_del_turno_y_no_en_otro(con, monkeypatch):
    vistos = _modelo_falso(monkeypatch)
    conversacion.decir(con, None, "Parte del hilo de él")
    conversacion.recibir(con, "¿y eso?")
    otro = con.execute("INSERT INTO hilo (abierto, ultimo) VALUES (?, ?)",
                       (memoria.ahora(), memoria.ahora())).lastrowid
    con.execute("INSERT INTO turno (hilo, rol, texto, estado, creado) VALUES (?, 'secretario', ?, 'listo', ?)",
                (otro, "Parte de otro hilo", memoria.ahora()))
    conversacion.atender(con)
    assert "Parte del hilo de él" in vistos[0] and "Parte de otro hilo" not in vistos[0]


def test_lo_que_se_dice_en_un_hilo_ya_cerrado_va_al_abierto(con):
    """Un resumen de sesión que tarda llegaba a un hilo cerrado y nadie lo veía."""
    conversacion.decir(con, None, "Hola")
    h = conversacion.hilo_abierto(con)
    conversacion.cerrar(con, h)
    tid = conversacion.decir(con, h["id"], "Resumen de la sesión abcd1234: …")
    donde = con.execute("SELECT hilo FROM turno WHERE id = ?", (tid,)).fetchone()[0]
    assert donde != h["id"] and donde == conversacion.hilo_abierto(con)["id"]


def test_una_hora_sin_zona_en_el_parte_es_de_la_casa_y_no_de_la_maquina(monkeypatch):
    """`_hora` llevaba su propia idea de hora local: lo que no dice su zona lo
    leía como hora de la máquina; el resto del hub, como de la casa (C-0051)."""
    monkeypatch.setenv("TZ", "Asia/Tokyo")
    assert resumen._hora("2026-11-06T10:00") == "10:00"
    assert resumen._hora("2026-11-06T01:00:00+00:00") == "10:00"
    assert resumen._hora("2026-11-06") == "todo el día"
    assert resumen._hora("") == "todo el día"


def test_un_fallo_que_no_es_del_modelo_no_deja_al_personaje_trabajando_para_siempre(con, monkeypatch, capsys):
    import sqlite3

    def bloqueada(prompt, **kw):
        raise sqlite3.OperationalError("database is locked")
    monkeypatch.setattr(motor, "llamar", bloqueada)
    monkeypatch.setattr(conversacion, "sistema", lambda: "S")
    conversacion.recibir(con, "hola")
    conversacion.atender(con)
    filas = {f["rol"]: (f["estado"], f["actividad"] or "") for f in con.execute("SELECT * FROM turno")}
    assert filas == {"dueno": ("error", ""), "secretario": ("error", "")}
    assert "database is locked" in capsys.readouterr().err, "se dice en voz alta (regla dura 21)"
    assert memoria.leer(con, f"turno_en_curso:{conversacion.hilo_abierto(con)['id']}") is None
    [b] = memoria.bitacora(con)
    assert b["ok"] == 0 and "database is locked" in b["resultado"], "y el parte lo cuenta en «Falló»"
