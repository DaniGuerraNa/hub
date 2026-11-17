"""El orden de la vuelta de `hub-secretario` y lo que no puede retrasarla.

La vuelta va en un solo hilo, paso tras paso. Lo que tiene hora —un
recordatorio, cortar la grabación de una reunión que ya acabó— no puede ir
detrás de lo que espera a la red o al modelo: medido del 1 al 11 de noviembre,
el triaje llegó a tardar 136 s, y 77 de sus 986 llamadas pasaron de 30 s
(C-0267).
"""

from __future__ import annotations

import pytest

from hub import copia_base, orquestador
from hub.secretario import (asuntos, consultas, conversacion, de_proyectos, delegados, disparadores, huecos,
                            memoria, recordatorios, servicio, triaje)


@pytest.fixture
def con():
    c = memoria.conectar()
    yield c
    c.close()


#: Cada paso de la vuelta, por el nombre con que se apunta en la bitácora.
_PASOS = {
    "fuentes": (servicio, "leer_fuentes"), "triaje": (triaje, "triar"),
    "recordatorios": (recordatorios, "revisar"), "horario": (disparadores, "por_horario"),
    "estado": (disparadores, "por_estado"), "parar grabación": (disparadores, "parar_si_acabo"),
    "agenda": (disparadores, "por_agenda"), "aprobadas": (servicio, "ejecutar_aprobadas"),
    "consultas": (consultas, "atender"), "de proyectos": (de_proyectos, "recoger"),
    "delegados": (delegados, "recoger"), "huecos": (huecos, "recoger"), "asuntos": (asuntos, "recalcular"),
    "cerrar_hilos": (conversacion, "cerrar_inactivos"), "copia": (copia_base, "hacer"),
}


@pytest.fixture
def orden(monkeypatch):
    """La vuelta con todos sus pasos de mentira: sólo queda en qué orden van."""
    visto: list[str] = []
    for nombre, (modulo, funcion) in _PASOS.items():
        monkeypatch.setattr(modulo, funcion, lambda *a, _n=nombre, **k: visto.append(_n))
    return visto


def test_lo_que_tiene_hora_va_antes_que_lo_que_espera_a_la_red_o_al_modelo(con, orden):
    servicio.una_vuelta(con)
    assert sorted(orden) == sorted(_PASOS), "la vuelta sigue dando todos sus pasos"
    for con_hora in ("recordatorios", "parar grabación"):
        for lento in ("fuentes", "triaje", "horario", "estado", "agenda", "consultas", "cerrar_hilos"):
            assert orden.index(con_hora) < orden.index(lento), f"«{con_hora}» espera a «{lento}»"


def test_leer_las_fuentes_el_triaje_y_cerrar_hilos_no_retrasan_nada_mas_que_la_copia(con, orden):
    """Son los tres que esperan sin tope corto: Telethon sin red, y el modelo
    en el triaje y en el resumen de cada hilo."""
    servicio.una_vuelta(con)
    lentos = ("fuentes", "triaje", "cerrar_hilos")
    primero = min(orden.index(p) for p in lentos)
    assert orden[primero:] == [*lentos, "copia"]
    assert orden.index("fuentes") < orden.index("triaje"), "lo recién leído se tría en la misma vuelta"


def test_un_paso_que_revienta_se_apunta_y_no_deja_sin_dar_los_demas(con, orden, monkeypatch):
    """Regla dura 2: decir que ya sabe hacer algo lee el tablero y las fichas,
    y un fallo ahí no puede dejar la vuelta a medias."""
    monkeypatch.setattr(huecos, "recoger", lambda c: 1 / 0)
    servicio.una_vuelta(con)
    assert sorted(orden) == sorted(set(_PASOS) - {"huecos"})
    assert con.execute("SELECT ok FROM bitacora WHERE accion = 'huecos'").fetchone()["ok"] == 0


def test_la_cuenta_de_lo_que_le_espera_sigue_saliendo_tras_lo_que_la_cambia(con, orden):
    servicio.una_vuelta(con)
    for antes in ("aprobadas", "consultas", "de proyectos", "delegados"):
        assert orden.index(antes) < orden.index("asuntos")


def test_un_recordatorio_que_vence_sale_aunque_el_triaje_tarde(con, canal_telegram, monkeypatch):
    """El triaje de mentira no tarda: mira si, cuando le toca, el recordatorio
    ya salió. Antes iba delante, y el aviso esperaba lo que durase."""
    memoria.comprometer(con, "Llamar a la clínica", recordar_en="2020-01-01T00:00:00+00:00")
    al_triar: list[int] = []
    monkeypatch.setattr(servicio, "leer_fuentes", lambda c: 0)
    monkeypatch.setattr(triaje, "triar", lambda c, dueno: al_triar.append(len(orquestador.timbres_pendientes())))
    monkeypatch.setattr(conversacion, "cerrar_inactivos", lambda c: 0)
    monkeypatch.setattr(copia_base, "hacer", lambda *a, **k: None)
    servicio.una_vuelta(con)
    assert al_triar == [1], "el recordatorio no había salido cuando empezó el triaje"


# ── el hilo de la conversación no muere callado (C-0268) ─────────────────────

@pytest.fixture
def charla(monkeypatch):
    """El hilo de la conversación de verdad, con un `atender` de mentira que
    apunta lo que contesta. Devuelve (contestados, hilo); al salir, lo para."""
    import threading

    contestados: list[str] = []
    llego = threading.Event()

    def atender(c, parar=None):
        for t in c.execute("SELECT id, texto FROM turno WHERE estado = 'pendiente'").fetchall():
            c.execute("UPDATE turno SET estado = 'listo' WHERE id = ?", (t["id"],))
            contestados.append(t["texto"])
        llego.set()
        return len(contestados)

    monkeypatch.setattr(conversacion, "atender", atender)
    monkeypatch.setattr(servicio, "TRAS_FALLO_S", 0.05)
    parar = threading.Event()
    hilo = threading.Thread(target=servicio._bucle_conversacion, args=(parar,), daemon=True)
    yield contestados, llego, hilo
    parar.set()
    hilo.join(5)


def test_un_fallo_al_mirar_si_hay_turnos_no_deja_sordo_al_secretario(con, charla, monkeypatch, capsys):
    """La consulta que mira si hay algo pendiente iba fuera de todo `try`: una
    base bloqueada más de diez segundos terminaba el hilo, y el otro seguía
    latiendo. La pantalla decía «en marcha» y nadie contestaba."""
    import time

    contestados, llego, hilo = charla
    buena = servicio.PENDIENTE
    monkeypatch.setattr(servicio, "PENDIENTE", "SELECT 1 FROM una_tabla_que_no_existe")
    hilo.start()
    time.sleep(0.4)
    assert hilo.is_alive(), "el hilo murió con el primer fallo"
    monkeypatch.setattr(servicio, "PENDIENTE", buena)
    conversacion.recibir(con, "¿sigues ahí?")
    assert llego.wait(5), "no volvió a mirar"
    assert contestados == ["¿sigues ahí?"]
    assert "una_tabla_que_no_existe" in capsys.readouterr().err, "un fallo así se dice en voz alta (regla 21)"


def test_si_la_base_no_abre_el_hilo_de_la_conversacion_insiste(con, charla, monkeypatch):
    import sqlite3

    contestados, llego, hilo = charla
    real, intentos = memoria.conectar, []

    def conectar(*a, **k):
        intentos.append(1)
        if len(intentos) <= 2:
            raise sqlite3.OperationalError("database is locked")
        return real(*a, **k)

    conversacion.recibir(con, "hola")
    monkeypatch.setattr(memoria, "conectar", conectar)
    hilo.start()
    assert llego.wait(5), "no llegó a abrir la base"
    assert contestados == ["hola"] and len(intentos) == 3


# ── lo que aprobó no espera a la vuelta ni al modelo (C-0271) ────────────────

def _aprobar(con, texto: str = "aprobada") -> int:
    """Una solicitud como la deja `hub-web` al pulsar «Aprobar»."""
    import json

    sid = con.execute("INSERT INTO solicitud (accion, params, motivo, hilo, creada) VALUES (?,?,?,?,?)",
                      ("anotar", json.dumps({"texto": texto}), "prueba", None, memoria.ahora())).lastrowid
    assert memoria.resolver_solicitud(con, sid, "aprobada", solo_pendiente=True) is not None
    return sid


def test_lo_que_aprobo_va_en_la_vuelta_antes_que_todo_lo_que_pregunta_al_modelo(con, orden):
    """Iba detrás del triaje y de los disparadores con `pide`: tras aprobar en
    el teléfono pasaban de 30 s a más de dos minutos, con la pantalla
    diciendo «la hace en unos segundos»."""
    servicio.una_vuelta(con)
    for lento in ("horario", "estado", "agenda", "consultas", "fuentes", "triaje", "cerrar_hilos"):
        assert orden.index("aprobadas") < orden.index(lento), f"lo aprobado espera a «{lento}»"


def test_lo_que_aprueba_entre_vuelta_y_vuelta_se_hace_sin_esperar_a_la_siguiente(con, monkeypatch):
    import threading

    recuentos: list[int] = []
    monkeypatch.setattr(asuntos, "recalcular", lambda c: recuentos.append(1))
    monkeypatch.setattr(servicio, "MIRAR_APROBADAS_S", 0.02)
    _aprobar(con)
    servicio._entre_vueltas(con, threading.Event(), 0.1)
    assert [n["texto"] for n in memoria.notas(con)] == ["aprobada"]
    assert con.execute("SELECT estado FROM solicitud").fetchone()[0] == "hecha"
    assert recuentos == [1], "la cuenta de lo que le espera sale al día, y una sola vez"


def test_entre_vueltas_sin_nada_aprobado_no_se_hace_nada_y_al_pedir_parar_se_deja_de_esperar(con, monkeypatch):
    import threading
    import time

    monkeypatch.setattr(servicio, "ejecutar_aprobadas", lambda c: pytest.fail("no había nada aprobado"))
    monkeypatch.setattr(servicio, "MIRAR_APROBADAS_S", 0.02)
    servicio._entre_vueltas(con, threading.Event(), 0.1)
    parar = threading.Event()
    parar.set()
    t0 = time.monotonic()
    servicio._entre_vueltas(con, parar, 30)
    assert time.monotonic() - t0 < 1


def test_si_ejecutar_lo_aprobado_falla_a_medias_no_se_insiste_cada_segundo(con, monkeypatch, capsys):
    """Si la base no deja reclamar o cerrar la solicitud, insistir a cada
    mirada no la desocupa (y antes de C-0315 repetía la acción). Se deja para
    la vuelta, que es el ritmo de antes."""
    import sqlite3
    import threading

    intentos: list[int] = []

    def falla(c):
        intentos.append(1)
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(servicio, "ejecutar_aprobadas", falla)
    monkeypatch.setattr(servicio, "MIRAR_APROBADAS_S", 0.02)
    _aprobar(con)
    servicio._entre_vueltas(con, threading.Event(), 0.2)
    assert len(intentos) == 1
    assert "database is locked" in capsys.readouterr().err


def test_queda_dicho_cuanto_espero_lo_aprobado(con, capsys):
    """`resolver_solicitud` pisa la hora de aprobar con la de ejecutar: sin
    esto no se podía medir cuánto pasa de un «Aprobar» a verlo hecho."""
    from datetime import datetime, timedelta, timezone

    sid = _aprobar(con)
    hace = (datetime.now(timezone.utc) - timedelta(seconds=42)).isoformat(timespec="seconds")
    con.execute("UPDATE solicitud SET resuelta = ? WHERE id = ?", (hace, sid))
    servicio.ejecutar_aprobadas(con)
    [linea] = [l for l in capsys.readouterr().out.splitlines() if l.startswith("[aprobada]")]
    assert "anotar" in linea and "esperó 42 s" in linea
    assert "aprobada" not in linea.split("]", 1)[1], "ni los parámetros ni el resultado: sólo qué acción y cuánto"


# ── el hilo de lo aparte tampoco muere callado (C-0314) ──────────────────────

def test_si_la_base_no_abre_el_hilo_de_resumenes_e_investigaciones_insiste(monkeypatch, capsys):
    """Abría la base fuera de todo `try`: si fallaba, ese hilo moría y el
    servicio seguía latiendo sin resumir ni investigar nunca (lo mismo que
    C-0268 quitó del hilo de la conversación)."""
    import sqlite3
    import threading

    from hub.secretario import investigar, sesiones

    real, intentos = memoria.conectar, []

    def conectar(*a, **k):
        intentos.append(1)
        if len(intentos) <= 2:
            raise sqlite3.OperationalError("database is locked")
        return real(*a, **k)

    llego = threading.Event()
    monkeypatch.setattr(memoria, "conectar", conectar)
    monkeypatch.setattr(sesiones, "atender", lambda c: llego.set())
    monkeypatch.setattr(investigar, "atender", lambda c: 0)
    monkeypatch.setattr(servicio, "TRAS_FALLO_S", 0.05)
    parar = threading.Event()
    hilo = threading.Thread(target=servicio._bucle_resumenes, args=(parar,), daemon=True)
    hilo.start()
    try:
        assert llego.wait(5), "no llegó a abrir la base"
        assert len(intentos) == 3
    finally:
        parar.set()
        hilo.join(5)
    err = capsys.readouterr().err
    assert "database is locked" in err and "intento 2" in err, "se dice en voz alta, y una línea por intento"


# ── una acción aprobada se hace como mucho una vez (C-0315) ──────────────────
#
# Entre ejecutar y apuntar que se hizo nada reclamaba la solicitud: si el
# servicio caía ahí, seguía «aprobada» y se repetía al arrancar. Con
# `escribir_en_sesion` o `cambiar_en_pc`, repetir es hacer dos veces algo que
# no tiene vuelta atrás.

class _SeCorto(BaseException):
    """Como `servicio._SeAcaboLaEspera`: lo que corta el paso a mitad al parar."""


@pytest.fixture
def accion(monkeypatch):
    """Una acción de verdad en el catálogo, que cuenta las veces que se hace."""
    from hub.secretario import piezas

    class DePrueba(piezas.Accion):
        id = "de_prueba"
        nombre = "Hacer la prueba"

        def __init__(self):
            self.veces, self.estados, self.cortar = [], [], False

        def ejecutar(self, con, params):
            self.veces.append(params)
            self.estados += [f[0] for f in con.execute("SELECT estado FROM solicitud ORDER BY id")]
            if self.cortar:
                raise _SeCorto
            return "hecho de verdad"

    a = DePrueba()
    reales = piezas.acciones()
    monkeypatch.setattr(piezas, "acciones", lambda: {**reales, a.id: a})
    getattr(servicio, "_sin_cerrar", {}).clear()
    getattr(servicio, "_cortadas", set()).clear()
    yield a
    getattr(servicio, "_sin_cerrar", {}).clear()
    getattr(servicio, "_cortadas", set()).clear()


def _aprobada(con, hilo=None, params=None, motivo="porque lo pidió") -> int:
    import json

    sid = con.execute("INSERT INTO solicitud (accion, params, motivo, hilo, creada) VALUES (?,?,?,?,?)",
                      ("de_prueba", json.dumps(params or {"que": "x"}), motivo, hilo, memoria.ahora())).lastrowid
    assert memoria.resolver_solicitud(con, sid, "aprobada", solo_pendiente=True) is not None
    return sid


def _estados(con) -> list[str]:
    return [f[0] for f in con.execute("SELECT estado FROM solicitud ORDER BY id")]


def test_una_aprobada_se_reclama_antes_de_ejecutarla(con, accion):
    _aprobada(con)
    assert servicio.ejecutar_aprobadas(con) == 1
    assert accion.estados == ["ejecutando"], "mientras se hace ya no está «aprobada»"
    assert _estados(con) == ["hecha"]


def test_si_se_corta_a_mitad_no_se_vuelve_a_ejecutar(con, accion):
    _aprobada(con)
    accion.cortar = True
    with pytest.raises(_SeCorto):
        servicio.ejecutar_aprobadas(con)
    assert _estados(con) == ["ejecutando"]
    accion.cortar = False
    assert servicio.ejecutar_aprobadas(con) == 0
    assert con.execute(servicio.APROBADA).fetchone() is None, "entre vueltas tampoco la ve"
    assert len(accion.veces) == 1 and _estados(con) == ["ejecutando"], "ni se repite ni se cierra sola"


def test_una_vuelta_entera_tampoco_repite_lo_que_quedo_a_medias(con, accion):
    _aprobada(con)
    accion.cortar = True
    with pytest.raises(_SeCorto):
        servicio.ejecutar_aprobadas(con)
    accion.cortar = False
    servicio._paso(con, "aprobadas", servicio.ejecutar_aprobadas)
    assert len(accion.veces) == 1 and _estados(con) == ["ejecutando"]


def test_las_que_no_llego_a_empezar_siguen_aprobadas_y_se_hacen_despues(con, accion):
    """Se reclama una a una, justo antes de cada una, nunca el lote: lo que el
    corte no tocó no queda en duda."""
    _aprobada(con)
    _aprobada(con)
    accion.cortar = True
    with pytest.raises(_SeCorto):
        servicio.ejecutar_aprobadas(con)
    assert _estados(con) == ["ejecutando", "aprobada"]
    accion.cortar = False
    assert servicio.ejecutar_aprobadas(con) == 1
    assert _estados(con) == ["ejecutando", "hecha"] and len(accion.veces) == 2


def test_al_arrancar_lo_que_quedo_a_medias_se_cierra_y_se_le_dice_una_vez(con, accion):
    hilo = conversacion.recibir(con, "hazlo")["hilo"]
    con.execute("UPDATE turno SET estado = 'listo'")
    sid = _aprobada(con, hilo=hilo)
    accion.cortar = True
    with pytest.raises(_SeCorto):
        servicio.ejecutar_aprobadas(con)
    accion.cortar = False
    antes = len(conversacion.turnos(con, hilo))
    assert servicio.recoger_cortadas(con) == 1
    fila = con.execute("SELECT estado, resultado FROM solicitud WHERE id = ?", (sid,)).fetchone()
    assert (fila["estado"], fila["resultado"]) == ("cortada", servicio.RESULTADO_CORTADA)
    dichos = conversacion.turnos(con, hilo)[antes:]
    assert len(dichos) == 1 and dichos[0]["rol"] == "secretario"
    assert "no sé si llegó a hacerse" in dichos[0]["texto"] and "No la repito sola" in dichos[0]["texto"]
    assert "«Hacer la prueba»" in dichos[0]["texto"] and "(porque lo pidió)" in dichos[0]["texto"]
    apunte = [b for b in memoria.bitacora(con) if b["accion"] == "de_prueba"][0]
    assert (apunte["nivel"], apunte["ok"], apunte["resultado"]) == ("aprobada", 0, servicio.RESULTADO_CORTADA)
    assert len(accion.veces) == 1, "nunca se reintenta, tampoco al arrancar"
    # Una segunda vez no hay nada que cerrar ni que decir.
    assert servicio.recoger_cortadas(con) == 0 and len(conversacion.turnos(con, hilo)) == antes + 1
    assert servicio.ejecutar_aprobadas(con) == 0 and len(accion.veces) == 1


def test_una_cortada_sin_hilo_tambien_se_le_dice(con, accion):
    """Las hechas sin hilo no dicen nada; ésta sí: es una duda que sólo él puede resolver."""
    con.execute("INSERT INTO solicitud (accion, params, motivo, hilo, creada, estado) VALUES (?,?,?,?,?,?)",
                ("de_prueba", "{}", "", None, memoria.ahora(), "ejecutando"))
    assert conversacion.hilo_abierto(con) is None
    assert servicio.recoger_cortadas(con) == 1
    texto = conversacion.turnos(con, conversacion.hilo_abierto(con)["id"])[-1]["texto"]
    assert "Me reinicié a mitad de «Hacer la prueba», que habías aprobado" in texto


def test_lo_que_se_le_dice_de_una_cortada_no_lleva_sus_parametros(con, accion):
    """Los parámetros pueden llevar sus datos (382): ni al chat, ni al resultado."""
    sid = _aprobada(con, params={"que": "el-dato-secreto-del-dueño"})
    memoria.resolver_solicitud(con, sid, "ejecutando", de="aprobada")
    servicio.recoger_cortadas(con)
    texto = conversacion.turnos(con, conversacion.hilo_abierto(con)["id"])[-1]["texto"]
    assert "el-dato-secreto" not in texto
    assert "el-dato-secreto" not in con.execute("SELECT resultado FROM solicitud").fetchone()[0]


def test_una_cortada_que_no_se_pudo_decir_no_queda_cerrada_a_medias_y_se_reintenta_en_la_vuelta(
        con, accion, monkeypatch):
    """Estado, bitácora y chat iban en tres commits: si decirlo fallaba,
    quedaba «cortada» para siempre sin que él se enterase. Van juntos, y lo
    que no sale al arrancar se reintenta en las vueltas siguientes."""
    import sqlite3

    for _ in range(2):
        con.execute("INSERT INTO solicitud (accion, params, hilo, creada, estado) VALUES (?,?,?,?,?)",
                    ("de_prueba", "{}", None, memoria.ahora(), "ejecutando"))
    de_verdad, dichos = conversacion.decir, []

    def decir(c, hilo, texto):
        dichos.append(texto)
        if len(dichos) == 1:
            raise sqlite3.OperationalError("database is locked")
        return de_verdad(c, hilo, texto)

    monkeypatch.setattr(conversacion, "decir", decir)
    with pytest.raises(sqlite3.OperationalError):
        servicio.recoger_cortadas(con)       # en voz alta: `_paso` lo apunta
    assert _estados(con) == ["ejecutando", "cortada"], "la que no se pudo decir no se da por cerrada; la otra sí"
    assert len([b for b in memoria.bitacora(con) if b["accion"] == "de_prueba"]) == 1
    # La vuelta siguiente la acaba: una vez dicha, una vez apuntada.
    monkeypatch.setattr(servicio, "ejecutar_aprobadas", lambda c: 0)
    servicio._paso(con, "cortadas", servicio.cerrar_cortadas)
    assert _estados(con) == ["cortada", "cortada"] and len(dichos) == 3
    assert len([b for b in memoria.bitacora(con) if b["accion"] == "de_prueba"]) == 2
    turnos = conversacion.turnos(con, conversacion.hilo_abierto(con)["id"])
    assert len([t for t in turnos if "no sé si llegó a hacerse" in t["texto"]]) == 2
    assert servicio.cerrar_cortadas(con) == 0 and servicio._cortadas == set()
    assert accion.veces == []


def test_la_vuelta_reintenta_lo_cortado_que_falto_y_sin_nada_pendiente_ni_lo_mira(con, accion, monkeypatch, orden):
    llamadas = []
    monkeypatch.setattr(servicio, "cerrar_cortadas", lambda c: llamadas.append(1) or 0)
    servicio.una_vuelta(con)
    assert llamadas == [] and "cortadas" not in [b["accion"] for b in memoria.bitacora(con)]
    servicio._cortadas.add(7)
    servicio.una_vuelta(con)
    assert llamadas == [1]


def test_lo_que_no_estaba_ejecutando_al_arrancar_no_lo_cierra_ninguna_vuelta(con, accion):
    """«Cayó» frente a «sigue en ello», sin esquema: sólo se cierra lo que
    este servicio vio `ejecutando` al arrancar. Lo que aparece después es de
    quien lo está haciendo ahora (una vuelta lanzada a mano, o él mismo), y un
    proceso que no es el servicio no arrancó viendo nada."""
    assert servicio.recoger_cortadas(con) == 0
    con.execute("INSERT INTO solicitud (accion, params, hilo, creada, estado) VALUES (?,?,?,?,?)",
                ("de_prueba", "{}", None, memoria.ahora(), "ejecutando"))
    assert servicio.cerrar_cortadas(con) == 0
    servicio.una_vuelta(con)
    assert _estados(con) == ["ejecutando"] and conversacion.hilo_abierto(con) is None


def test_el_reclamo_se_asegura_en_disco_y_la_conexion_queda_como_estaba(con, accion):
    """La base va con `synchronous=NORMAL`: tras un corte de luz, el último
    commit puede perderse. Si el perdido es el reclamo, la solicitud vuelve a
    «aprobada» con la acción ya hecha, y se repetiría. Sólo el reclamo va con
    FULL: es una escritura por acción aprobada."""
    _aprobada(con)
    antes = con.execute("PRAGMA synchronous").fetchone()[0]
    visto: list[str] = []
    con.set_trace_callback(visto.append)
    servicio.ejecutar_aprobadas(con)
    con.set_trace_callback(None)
    sql = [v for v in visto if v.startswith(("PRAGMA synchronous=", "UPDATE solicitud"))]
    assert sql[0] == "PRAGMA synchronous=FULL" and sql[1].startswith("UPDATE solicitud")
    assert sql[2] == f"PRAGMA synchronous={antes}", "y vuelve a como estaba antes de ejecutar nada más"
    assert len([v for v in visto if v == "PRAGMA synchronous=FULL"]) == 1, "cerrarla no lo necesita"
    assert con.execute("PRAGMA synchronous").fetchone()[0] == antes == 1
    assert _estados(con) == ["hecha"]


def test_reclamar_dentro_de_una_transaccion_abierta_no_toca_el_modo_de_la_conexion(con, accion):
    from hub.db import transaccion

    sid = _aprobada(con)
    with transaccion(con):
        assert memoria.resolver_solicitud(con, sid, "ejecutando", de="aprobada") is not None
    assert con.execute("PRAGMA synchronous").fetchone()[0] == 1 and _estados(con) == ["ejecutando"]


def test_dos_que_reclaman_la_misma_solo_uno_la_ejecuta(con, accion):
    sid = _aprobada(con)
    otra = memoria.conectar()
    try:
        assert memoria.resolver_solicitud(otra, sid, "ejecutando", de="aprobada") is not None
        assert memoria.resolver_solicitud(con, sid, "ejecutando", de="aprobada") is None
        assert servicio.ejecutar_aprobadas(con) == 0 and accion.veces == []
    finally:
        otra.close()


def test_si_otro_la_reclama_entre_leerla_y_ejecutarla_no_se_hace_dos_veces(con, accion, monkeypatch):
    """El segundo proceso de verdad es una vuelta lanzada a mano con el servicio vivo."""
    sid = _aprobada(con)
    de_verdad = memoria.resolver_solicitud

    def reclama_otro_antes(c, s, estado, *a, **k):
        if estado == "ejecutando":
            otra = memoria.conectar()
            de_verdad(otra, s, "ejecutando", de="aprobada")
            otra.close()
        return de_verdad(c, s, estado, *a, **k)

    monkeypatch.setattr(memoria, "resolver_solicitud", reclama_otro_antes)
    assert servicio.ejecutar_aprobadas(con) == 0 and accion.veces == []
    assert _estados(con) == ["ejecutando"] and sid


def test_si_no_se_pudo_apuntar_el_resultado_se_apunta_en_la_siguiente_sin_repetir(con, accion, monkeypatch):
    """La base ocupada justo después de hacerla: el servicio no muere, así que
    el arranque no la recogería nunca. Se guarda y se cierra en la siguiente."""
    import sqlite3

    hilo = conversacion.recibir(con, "hazlo")["hilo"]
    con.execute("UPDATE turno SET estado = 'listo'")
    sid = _aprobada(con, hilo=hilo)
    de_verdad, fallos = memoria.resolver_solicitud, []

    def ocupada(c, s, estado, *a, **k):
        if estado == "hecha" and not fallos:
            fallos.append(1)
            raise sqlite3.OperationalError("database is locked")
        return de_verdad(c, s, estado, *a, **k)

    monkeypatch.setattr(memoria, "resolver_solicitud", ocupada)
    with pytest.raises(sqlite3.OperationalError):
        servicio.ejecutar_aprobadas(con)
    assert _estados(con) == ["ejecutando"] and sid in servicio._sin_cerrar
    assert servicio.ejecutar_aprobadas(con) == 1
    fila = con.execute("SELECT estado, resultado FROM solicitud").fetchone()
    assert (fila["estado"], fila["resultado"]) == ("hecha", "hecho de verdad")
    assert len(accion.veces) == 1 and servicio._sin_cerrar == {}
    assert [t["texto"] for t in conversacion.turnos(con, hilo)][-1] == "Hecho: hecho de verdad"
    assert len([b for b in memoria.bitacora(con) if b["accion"] == "de_prueba"]) == 1, "apuntada una vez"


def test_si_lo_que_falla_al_cerrar_es_lo_ultimo_no_se_apunta_ni_se_dice_dos_veces(con, accion, monkeypatch):
    import sqlite3

    hilo = conversacion.recibir(con, "hazlo")["hilo"]
    con.execute("UPDATE turno SET estado = 'listo'")
    _aprobada(con, hilo=hilo)
    de_verdad, fallos = conversacion.decir, []

    def ocupada(c, h, texto):
        if not fallos:
            fallos.append(1)
            raise sqlite3.OperationalError("database is locked")
        return de_verdad(c, h, texto)

    monkeypatch.setattr(conversacion, "decir", ocupada)
    with pytest.raises(sqlite3.OperationalError):
        servicio.ejecutar_aprobadas(con)
    assert _estados(con) == ["hecha"]
    assert servicio.ejecutar_aprobadas(con) == 1
    assert len([b for b in memoria.bitacora(con) if b["accion"] == "de_prueba"]) == 1
    assert [t["texto"] for t in conversacion.turnos(con, hilo)].count("Hecho: hecho de verdad") == 1
    assert len(accion.veces) == 1


def _nombres(funcion) -> dict[str, int]:
    """Los nombres y atributos que usa el código de `funcion` (no sus
    comentarios ni su docstring), con la primera línea en que sale cada uno."""
    import ast
    import inspect
    import textwrap

    vistos: dict[str, int] = {}
    for nodo in ast.walk(ast.parse(textwrap.dedent(inspect.getsource(funcion)))):
        nombre = nodo.id if isinstance(nodo, ast.Name) else nodo.attr if isinstance(nodo, ast.Attribute) else None
        if nombre:
            vistos[nombre] = min(vistos.get(nombre, nodo.lineno), nodo.lineno)
    return vistos


def test_una_que_no_se_deja_cerrar_nunca_no_impide_hacer_lo_que_apruebe_despues(con, accion, monkeypatch):
    """Regla dura 2: lo que falla siempre no puede dejar sordo al paso."""
    import sqlite3

    primera = _aprobada(con)
    de_verdad = memoria.resolver_solicitud

    def nunca_la_primera(c, s, estado, *a, **k):
        if s == primera and estado == "hecha":
            raise sqlite3.OperationalError("disk I/O error")
        return de_verdad(c, s, estado, *a, **k)

    monkeypatch.setattr(memoria, "resolver_solicitud", nunca_la_primera)
    with pytest.raises(sqlite3.OperationalError):
        servicio.ejecutar_aprobadas(con)
    _aprobada(con)
    with pytest.raises(sqlite3.OperationalError):
        servicio.ejecutar_aprobadas(con)          # lo sigue diciendo…
    assert _estados(con) == ["ejecutando", "hecha"], "…pero la nueva se hizo"
    assert len(accion.veces) == 2 and primera in servicio._sin_cerrar


def test_solo_el_arranque_recoge_lo_cortado():
    """Qué quedó a medias sólo se mira al arrancar, antes de los hilos y de la
    primera vuelta, cuando no hay otro vivo. Las vueltas sólo acaban de cerrar
    lo que el arranque vio (`_cortadas`), nunca miran la tabla."""
    import inspect

    arranque = _nombres(servicio.correr)
    assert arranque["recoger_cortadas"] < arranque["Thread"] < arranque["una_vuelta"]
    assert '_paso(con, "cortadas", recoger_cortadas)' in inspect.getsource(servicio.correr), \
        "en su paso: si falla, el servicio arranca igual"
    for funcion in (servicio.una_vuelta, servicio.ejecutar_aprobadas, servicio._entre_vueltas, servicio._cerrar,
                    servicio._bucle_conversacion, servicio._bucle_resumenes, servicio.cerrar_cortadas):
        assert "recoger_cortadas" not in _nombres(funcion), funcion.__name__
    assert "SELECT" not in inspect.getsource(servicio.cerrar_cortadas), "no busca en la tabla: sólo lo ya visto"
    for funcion in (servicio.cerrar_cortadas, servicio.recoger_cortadas):
        assert "ejecutar" not in _nombres(funcion), "nunca llama a la acción"


def test_una_cortada_corta_la_racha_de_confianza(con, accion):
    """No saber si se hizo no es «sin fallo» (303)."""
    for _ in range(3):
        _aprobada(con)
    servicio.ejecutar_aprobadas(con)
    assert memoria.aprobadas_seguidas(con, "de_prueba") == 3
    sid = _aprobada(con)
    memoria.resolver_solicitud(con, sid, "ejecutando", de="aprobada")
    servicio.recoger_cortadas(con)
    assert memoria.aprobadas_seguidas(con, "de_prueba") == 0


def test_resolver_con_de_solo_toca_la_que_esta_en_ese_estado_y_solo_pendiente_sigue_valiendo(con):
    sid = con.execute("INSERT INTO solicitud (accion, params, creada) VALUES ('anotar', '{}', ?)",
                      (memoria.ahora(),)).lastrowid
    assert memoria.resolver_solicitud(con, sid, "ejecutando", de="aprobada") is None
    assert memoria.resolver_solicitud(con, sid, "aprobada", solo_pendiente=True)["estado"] == "aprobada"
    assert memoria.resolver_solicitud(con, sid, "rechazada", solo_pendiente=True) is None
    assert memoria.resolver_solicitud(con, sid, "ejecutando", de="aprobada")["estado"] == "ejecutando"
    assert memoria.resolver_solicitud(con, sid, "cortada", "no se sabe", de="ejecutando")["resultado"] == "no se sabe"
    # Sin `de`, por id: es como cierra quien la ejecutó, pase lo que pase.
    assert memoria.resolver_solicitud(con, sid, "hecha", "al final sí")["estado"] == "hecha"
