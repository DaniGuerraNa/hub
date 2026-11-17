"""Un motor caído no es un lote malo (C-0307).

Si el modelo no estaba disponible —`claude` que no arranca, la API con error,
el uso agotado—, cada tres vueltas del ciclo el triaje apartaba para siempre
otro lote de mensajes buenos, y el cierre de hilos cerraba sin resumen. Ahora
lo que es del motor no cuenta: se espera, con retroceso, y antes de apartar o
de cerrar sin resumen se sondea si el motor contesta.

El modelo es siempre un doble: aquí no se llama a ninguno. La sonda
(`motor.responde`) gasta una llamada mínima de verdad, y por eso en cada test
va doblada o contra el `claude` de mentira.
"""

from __future__ import annotations

import json
import sys
import threading
from datetime import datetime, timedelta, timezone

import pytest

from hub.secretario import conversacion, investigar, memoria, motor, servicio, triaje
from hub.secretario.piezas import Evento

FALSO = r'''#!{py}
import json, os, sys
with open(os.environ["REGISTRO"], "a") as f:
    f.write(json.dumps({{"args": sys.argv[1:]}}) + "\n")
sys.stdin.read()
d = {{"type": "result", "result": "ok", "session_id": "s", "total_cost_usd": 0.001,
     "usage": {{"input_tokens": 5, "output_tokens": 2}}}}
d.update(json.loads(open(os.environ["RESPUESTA"]).read()))
print(json.dumps(d))
sys.exit(1 if d.get("is_error") else 0)
'''

#: El `result` de la API caída, como lo da el `claude` real cuando su vigilante
#: de red agota los reintentos (medido con una API falsa, C-0170).
API_CAIDA = {"is_error": True, "terminal_reason": "api_error", "result": "API Error: stream idle: no bytes for 45000ms"}


@pytest.fixture
def con():
    c = memoria.conectar()
    yield c
    c.close()


@pytest.fixture
def falso(tmp_path, monkeypatch):
    """Un `claude` de mentira en el PATH: contesta lo que se le deje dicho."""
    from hub import tmux
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    (bin_ / "claude").write_text(FALSO.format(py=sys.executable))
    (bin_ / "claude").chmod(0o755)
    registro, respuesta = tmp_path / "registro.jsonl", tmp_path / "respuesta.json"
    respuesta.write_text("{}")
    monkeypatch.setenv("REGISTRO", str(registro))
    monkeypatch.setenv("RESPUESTA", str(respuesta))
    monkeypatch.setattr(tmux, "path_de_usuario", lambda: f"{bin_}:/usr/bin:/bin")

    class Falso:
        carpeta = bin_

        def lineas(self):
            return [json.loads(l)["args"] for l in registro.read_text().splitlines()] if registro.exists() else []

        def contesta(self, **d):
            respuesta.write_text(json.dumps(d))

    yield Falso()
    motor.soltar()


class Modelo:
    """`motor.llamar` de mentira: una respuesta por llamada; la última se repite."""

    def __init__(self, *respuestas):
        self.respuestas, self.llamadas = list(respuestas), []

    def __call__(self, prompt, **kw):
        self.llamadas.append({"prompt": prompt, **kw})
        r = self.respuestas.pop(0) if len(self.respuestas) > 1 else self.respuestas[0]
        if isinstance(r, Exception):
            raise r
        texto, datos = (r, None) if isinstance(r, str) else ("", r)
        return motor.Respuesta(texto=texto, sesion="s", estructurada=datos, segundos=1.0, coste=0, modelo=kw["modelo"])


def _ev(con, i, texto="Mañana te mando el contrato firmado"):
    return memoria.guardar_evento(con, Evento(fuente="telegram", id_externo=str(i), fecha="2026-10-21T15:00:00+00:00",
                                              texto=texto, conversacion="Trabajo", autor="Ana"))


def _apartados(con) -> int:
    return con.execute("SELECT COUNT(*) FROM evento WHERE triado = ?", (memoria.APARTADO,)).fetchone()[0]


def _ya_toca(con) -> None:
    """Como si hubiera pasado la espera: el próximo intento, ya."""
    e = memoria.leer(con, motor.CLAVE_PAUSA)
    e["proximo"] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(timespec="seconds")
    memoria.poner(con, motor.CLAVE_PAUSA, e)


def _lineas(con, accion: str) -> list[dict]:
    return [b for b in memoria.bitacora(con) if b["accion"] == accion]


def _sonda(monkeypatch, contesta: bool) -> list:
    hechas = []
    monkeypatch.setattr(motor, "responde", lambda modelo=None: hechas.append(modelo) or contesta)
    return hechas


# ── la clasificación: qué es del motor y qué del pedido ──────────────────────

def test_la_api_caida_es_del_motor_y_no_del_pedido(falso):
    falso.contesta(**API_CAIDA)
    with pytest.raises(motor.MotorNoDisponible) as e:
        motor.llamar("hola", modelo="claude-haiku-4-5", herramientas=False, nueva=True, persistir=False)
    assert e.value.causa == "api" and e.value.causa in motor.CAUSAS and e.value.hasta is None
    assert isinstance(e.value, motor.MotorCaido), "quien ya atrapaba MotorCaido lo sigue atrapando"


def test_que_claude_no_arranque_es_del_motor(falso, monkeypatch):
    from hub import tmux
    vacia = falso.carpeta.parent / "sin-claude"
    vacia.mkdir()
    # Un PATH sin `claude` y sin nada más: no hay otro que pueda arrancar.
    monkeypatch.setattr(tmux, "path_de_usuario", lambda: str(vacia))
    with pytest.raises(motor.MotorNoDisponible) as e:
        motor.llamar("hola", modelo="claude-haiku-4-5", herramientas=False, nueva=True, persistir=False)
    assert e.value.causa == "no_arranca" and str(e.value).startswith("no se pudo arrancar claude")


def test_un_motor_que_no_existe_en_el_yml_es_del_motor_y_su_texto_ya_lo_dice(monkeypatch):
    monkeypatch.setattr(conversacion, "ajustes", lambda: {"motor": "inventado"})
    with pytest.raises(motor.MotorNoDisponible) as e:
        motor.llamar("hola", modelo="claude-haiku-4-5")
    # Sin causa: el mensaje ya dice qué arreglar, y `explicar_fallo` lo deja tal cual.
    assert e.value.causa is None and "secretario.yml" in conversacion.explicar_fallo(e.value)


@pytest.mark.parametrize("resultado", [
    # Lo que es del pedido y sigue contando: no dio la salida con el esquema, o no dio JSON.
    {"is_error": True, "terminal_reason": "structured_output_retry_exhausted", "result": None},
    {"is_error": True, "result": "algo que la CLI dice y nadie ha medido"},
    {"is_error": True, "subtype": "error_max_budget_usd", "terminal_reason": "budget_exhausted"},
])
def test_lo_que_no_esta_medido_como_del_motor_sigue_siendo_un_fallo_corriente(falso, resultado):
    falso.contesta(**resultado)
    with pytest.raises(motor.MotorCaido) as e:
        motor.llamar("hola", modelo="claude-haiku-4-5", herramientas=False, nueva=True, persistir=False,
                     tope_usd=0.5)
    assert not isinstance(e.value, motor.MotorNoDisponible)


def test_el_tope_de_tiempo_y_cancelar_no_son_del_motor():
    """Un lote que siempre agota el tiempo tiene que poder apartarse: si
    contara como «no disponible», el triaje se quedaría sordo (decisión 376)."""
    class Proceso:
        returncode = -9

    for motivo in ("tope", "parar"):
        vigia = motor._Vigia.__new__(motor._Vigia)
        vigia.p, vigia.motivo = Proceso(), motivo
        with pytest.raises(motor.MotorCaido) as e:
            vigia.comprobar()
        assert not isinstance(e.value, motor.MotorNoDisponible)


# ── la pausa: retroceso, una línea por racha y vuelta ────────────────────────

def test_la_espera_crece_hasta_quince_minutos_y_se_apunta_una_vez_por_racha(con, capsys):
    t0 = datetime(2026, 11, 13, 10, 0, tzinfo=timezone.utc)
    ahora, esperas = t0, []
    for _ in range(8):
        e = motor.pausar(con, motor.MotorNoDisponible("claude: API Error", "api"), "triaje", ahora=ahora)
        espera = (datetime.fromisoformat(e["proximo"]) - ahora).total_seconds()
        esperas.append(espera)
        assert motor.en_pausa(con, ahora=ahora + timedelta(seconds=espera - 1)), "antes de tiempo no se llama"
        assert motor.en_pausa(con, ahora=ahora + timedelta(seconds=espera)) is None, "a su hora, se intenta"
        ahora += timedelta(seconds=espera)
    assert esperas == [30, 60, 120, 300, 600, 900, 900, 900] and tuple(esperas[:6]) == motor.RETROCESO_S
    e = memoria.leer(con, motor.CLAVE_PAUSA)
    assert set(e) == {"desde", "causa", "fallos", "proximo", "apuntada"}
    assert (e["desde"], e["causa"], e["fallos"]) == (t0.isoformat(timespec="seconds"), "api", 8)
    lineas = _lineas(con, "triaje")
    assert len(lineas) == 1 and lineas[0]["ok"] == 0 and "no está disponible" in lineas[0]["resultado"]
    # En voz alta cada vez (regla 21), pero al registro del servicio, no a la bitácora.
    assert capsys.readouterr().err.count("motor: no disponible") == 8


def test_una_racha_que_dura_un_dia_se_vuelve_a_apuntar_para_que_el_parte_la_vea(con):
    """El parte saca «Falló» de la bitácora de las últimas 24 h: con una sola
    línea por racha, al segundo día de caída ya no diría nada."""
    t0 = datetime(2026, 11, 13, 10, 0, tzinfo=timezone.utc)
    exc = motor.MotorNoDisponible("claude: API Error", "api")
    motor.pausar(con, exc, "triaje", ahora=t0)
    motor.pausar(con, exc, "triaje", ahora=t0 + timedelta(hours=19))
    assert len(_lineas(con, "triaje")) == 1
    motor.pausar(con, exc, "triaje", ahora=t0 + timedelta(hours=21))
    assert len(_lineas(con, "triaje")) == 2


def test_al_volver_el_motor_la_racha_se_borra_y_la_siguiente_empieza_de_cero(con):
    exc = motor.MotorNoDisponible("claude: API Error", "api")
    for _ in range(4):
        motor.pausar(con, exc, "triaje")
    assert motor.reanudar(con) is True and memoria.leer(con, motor.CLAVE_PAUSA) is None
    assert motor.reanudar(con) is False and motor.en_pausa(con) is None
    assert motor.pausar(con, exc, "triaje")["fallos"] == 1
    assert len(_lineas(con, "triaje")) == 2, "otra racha, otra línea"


@pytest.mark.parametrize("estado", [
    "basura", {"proximo": "no es una fecha"}, {"proximo": None}, {"proximo": "2026-11-13T10:00:00"},
    # Un reloj que saltó: más espera que la mayor posible no se cree.
    {"proximo": (datetime.now(timezone.utc) + timedelta(days=2)).isoformat(timespec="seconds")},
])
def test_una_pausa_que_no_se_entiende_no_deja_sordo_al_triaje(con, estado):
    """Regla dura 2: lo que decide saltarse un paso no puede saltárselo para siempre."""
    memoria.poner(con, motor.CLAVE_PAUSA, estado)
    assert motor.en_pausa(con) is None
    assert motor.pausar(con, motor.MotorNoDisponible("x", "api"), "triaje")["fallos"] >= 1


# ── la sonda ─────────────────────────────────────────────────────────────────

def test_la_sonda_es_una_llamada_minima_sin_herramientas_ni_rastro(falso):
    assert motor.responde("claude-haiku-4-5") is True
    (linea,) = falso.lineas()
    assert linea[linea.index("--model") + 1] == "claude-haiku-4-5"
    assert "--no-session-persistence" in linea and "--mcp-config" not in linea
    c = memoria.conectar()
    assert [f["trabajo"] for f in c.execute("SELECT trabajo FROM llamada")] == ["sonda"], "lo que gasta, apuntado"
    c.close()
    falso.contesta(**API_CAIDA)
    assert motor.responde("claude-haiku-4-5") is False


def test_la_sonda_que_falla_por_lo_que_sea_dice_que_no_contesta(monkeypatch, capsys):
    """Si la sonda se rompe no se aparta nada: lo dudoso espera, no se pierde."""
    monkeypatch.setattr(motor, "llamar", Modelo(RuntimeError("un fallo de dentro")))
    assert motor.responde() is False
    assert "RuntimeError" in capsys.readouterr().err
    m = Modelo("ok")
    monkeypatch.setattr(motor, "llamar", m)
    assert motor.responde() is True
    kw = m.llamadas[0]
    assert (kw["herramientas"], kw["persistir"], kw["nueva"], kw["trabajo"]) == (False, False, True, "sonda")
    assert kw["modelo"] == "claude-haiku-4-5" and callable(kw["parar"]), "con su propio tope de tiempo"


# ── el triaje ────────────────────────────────────────────────────────────────

def test_por_el_camino_entero_con_el_modelo_caido_no_se_aparta_nada_y_al_volver_se_tria(falso, con):
    """Lo de hoy (SEC-02): con el modelo sin contestar, a la tercera vuelta el
    lote entero quedaba apartado para siempre. Aquí todo va contra el `claude`
    de mentira, también la sonda: primero con un error que nadie ha medido
    (como llegaría el uso agotado), luego con el de la API caída."""
    for i in range(3):
        _ev(con, i)
    falso.contesta(is_error=True, result="un error de la CLI que no está clasificado")
    for _ in range(3):
        assert triaje.triar(con) == 0
    assert _apartados(con) == 0 and len(memoria.sin_triar(con)) == 3, "el motor no contesta: no es el lote"
    assert len(falso.lineas()) == 4, "tres intentos y la sonda"
    falso.contesta(**API_CAIDA)
    for _ in range(6):
        _ya_toca(con)
        assert triaje.triar(con) == 0
    assert _apartados(con) == 0
    # Vuelve.
    _ya_toca(con)
    falso.contesta(structured_output={"items": []})
    assert triaje.triar(con) == 3
    assert memoria.sin_triar(con) == [] and _apartados(con) == 0 and memoria.leer(con, motor.CLAVE_PAUSA) is None


def test_diez_vueltas_con_el_motor_caido_no_apartan_nada_y_dejan_una_sola_linea(con, monkeypatch):
    for i in range(3):
        _ev(con, i)
    m = Modelo(motor.MotorNoDisponible("claude: API Error: stream idle", "api"))
    monkeypatch.setattr(motor, "llamar", m)
    sondas = _sonda(monkeypatch, False)
    for vuelta in range(10):
        assert triaje.triar(con) == 0
        # Entre intento e intento, las vueltas del ciclo no llaman al modelo.
        assert triaje.triar(con) == 0 and len(m.llamadas) == vuelta + 1
        _ya_toca(con)
    assert _apartados(con) == 0 and len(memoria.sin_triar(con)) == 3
    assert len(_lineas(con, "triaje")) == 1, "una línea por racha, no una cada 30 s"
    e = memoria.leer(con, motor.CLAVE_PAUSA)
    assert e["fallos"] == 10 and memoria.leer(con, "triaje_fallos", 0) == 0, "no cuenta contra el lote"
    assert len(sondas) == 1, "sólo la comprobación de cada tantos fallos seguidos"
    # Vuelve el motor: el lote se tría, y la racha se acaba.
    m.respuestas = [{"items": []}]
    assert triaje.triar(con) == 3
    assert memoria.sin_triar(con) == [] and _apartados(con) == 0
    assert memoria.leer(con, motor.CLAVE_PAUSA) is None


def test_tres_fallos_sin_clasificar_y_la_sonda_no_contesta_el_lote_no_se_aparta(con, monkeypatch):
    """El `result` del uso agotado o de la sesión sin iniciar no está medido:
    llega como un fallo corriente. Por eso, antes de apartar, se sondea."""
    _ev(con, 1)
    m = Modelo(motor.MotorCaido("claude: algo que nadie ha medido"))
    monkeypatch.setattr(motor, "llamar", m)
    sondas = _sonda(monkeypatch, False)
    for _ in range(3):
        assert triaje.triar(con) == 0
    assert sondas == ["claude-haiku-4-5"], "con el modelo del triaje, al tercer fallo y no antes"
    assert _apartados(con) == 0 and len(memoria.sin_triar(con)) == 1
    assert motor.en_pausa(con)["causa"] == "api"
    assert triaje.triar(con) == 0 and len(m.llamadas) == 3, "en pausa: ni se llama ni se sondea"
    # A su hora se intenta otra vez; sigue caído, sigue sin apartarse, y espera más.
    _ya_toca(con)
    assert triaje.triar(con) == 0 and _apartados(con) == 0 and len(sondas) == 2
    assert memoria.leer(con, motor.CLAVE_PAUSA)["fallos"] == 2
    assert [b["ok"] for b in _lineas(con, "triaje")] == [0, 0, 0], "los dos primeros fallos y la racha"
    # Vuelve: se tría entero.
    _ya_toca(con)
    m.respuestas = [{"items": []}]
    assert triaje.triar(con) == 1 and memoria.leer(con, motor.CLAVE_PAUSA) is None
    assert memoria.leer(con, "triaje_fallos") == 0


def test_tres_fallos_y_la_sonda_contesta_el_malo_es_el_lote_y_se_aparta_como_siempre(con, monkeypatch):
    _ev(con, 1)
    monkeypatch.setattr(motor, "llamar", Modelo(motor.MotorCaido("el modelo no contestó en 600 s")))
    sondas = _sonda(monkeypatch, True)
    for _ in range(2):
        assert triaje.triar(con) == 0
    assert _apartados(con) == 0 and sondas == []
    assert triaje.triar(con) == 0
    assert _apartados(con) == 1 and memoria.sin_triar(con) == [], "no atasca la cola"
    assert memoria.leer(con, "triaje_fallos") == 0 and motor.en_pausa(con) is None


def test_en_pausa_el_triaje_sigue_descartando_lo_trivial_sin_llamar(con, monkeypatch):
    _ev(con, 1)
    motor.pausar(con, motor.MotorNoDisponible("x", "api"), "triaje")
    monkeypatch.setattr(motor, "llamar", Modelo(RuntimeError("no debía llamarse")))
    _ev(con, 2, "jaja")
    assert triaje.triar(con) == 1
    assert [e["id_externo"] for e in memoria.sin_triar(con)] == ["1"]


def test_un_lote_que_siempre_da_error_de_la_api_no_deja_el_triaje_sordo_para_siempre(con, monkeypatch):
    """La red contra quedarse sordo (regla dura 2): si lo que falla «por el
    motor» es en realidad ese lote —una petición que la API rechaza siempre—,
    la pausa sola lo reintentaría sin fin y nada de detrás se leería. Cada
    `COMPROBAR_CADA` fallos seguidos se sondea, y si el motor contesta, ese
    fallo cuenta contra el lote."""
    _ev(con, 1)
    m = Modelo(motor.MotorNoDisponible("claude: API Error: 400", "api"))
    monkeypatch.setattr(motor, "llamar", m)
    sondas = _sonda(monkeypatch, True)
    for _ in range(motor.FALLOS_PARA_RENDIRSE * motor.COMPROBAR_CADA):
        triaje.triar(con)
        if memoria.leer(con, motor.CLAVE_PAUSA):
            _ya_toca(con)
    assert len(sondas) == motor.FALLOS_PARA_RENDIRSE
    assert _apartados(con) == 1 and memoria.sin_triar(con) == []


# ── el cierre de hilos ───────────────────────────────────────────────────────

_RESUMEN = {"titulo": "Facturas", "resumen": "Hablaron de facturas.", "notas": []}


def _hilo_vencido(con, monkeypatch) -> int:
    monkeypatch.setattr(motor, "llamar", Modelo("Respuesta."))
    hilo = conversacion.recibir(con, "hola")["hilo"]
    conversacion.atender(con)
    _envejecer(con)
    return hilo


def _envejecer(con) -> None:
    hace = (datetime.now(timezone.utc) - timedelta(minutes=31)).isoformat(timespec="seconds")
    con.execute("UPDATE hilo SET ultimo = ? WHERE cerrado IS NULL", (hace,))


def _cerrado(con, hilo):
    return con.execute("SELECT cerrado, titulo, resumen FROM hilo WHERE id = ?", (hilo,)).fetchone()


def test_con_el_motor_caido_un_hilo_no_se_cierra_sin_resumen_y_al_volver_se_resume(con, monkeypatch):
    hilo = _hilo_vencido(con, monkeypatch)
    m = Modelo(motor.MotorNoDisponible("no se pudo arrancar claude: [Errno 2]", "no_arranca"))
    monkeypatch.setattr(motor, "llamar", m)
    _sonda(monkeypatch, False)
    for vuelta in range(5):
        assert conversacion.cerrar_inactivos(con) == 0
        assert conversacion.cerrar_inactivos(con) == 0 and len(m.llamadas) == vuelta + 1, "en pausa no se llama"
        _ya_toca(con)
    assert _cerrado(con, hilo)["cerrado"] is None
    assert memoria.leer(con, f"cierre:{hilo}") is None, "no cuenta contra el hilo"
    assert len(_lineas(con, "cerrar_hilo")) == 1
    m.respuestas = [_RESUMEN]
    assert conversacion.cerrar_inactivos(con) == 1
    assert _cerrado(con, hilo)["titulo"] == "Facturas" and memoria.leer(con, motor.CLAVE_PAUSA) is None


@pytest.mark.parametrize("contesta", [False, True])
def test_antes_de_cerrar_un_hilo_sin_resumen_se_sondea(con, monkeypatch, contesta):
    hilo = _hilo_vencido(con, monkeypatch)
    monkeypatch.setattr(motor, "llamar", Modelo(motor.MotorCaido("claude: algo que nadie ha medido")))
    sondas = _sonda(monkeypatch, contesta)
    for _ in range(3):
        conversacion.cerrar_inactivos(con)
        _envejecer(con)
    assert sondas == [conversacion.enrutador.modelo("cierre")]
    if contesta:
        c = _cerrado(con, hilo)
        assert c["cerrado"] and c["resumen"] == "", "el malo es el hilo: se cierra sin resumen, como siempre"
        assert memoria.leer(con, f"cierre:{hilo}") is None
    else:
        assert _cerrado(con, hilo)["cerrado"] is None and motor.en_pausa(con)


def test_en_pausa_los_hilos_que_no_necesitan_al_modelo_se_siguen_cerrando(con, monkeypatch):
    conversacion.decir(con, None, "El parte de la mañana.")
    # Donde sólo habló el secretario se espera horas, no media hora, antes de cerrar.
    hace = (datetime.now(timezone.utc) - timedelta(hours=conversacion.ESPERA_SIN_EL_HORAS + 1)).isoformat(timespec="seconds")
    con.execute("UPDATE hilo SET ultimo = ?", (hace,))
    motor.pausar(con, motor.MotorNoDisponible("x", "api"), "triaje")
    monkeypatch.setattr(motor, "llamar", Modelo(RuntimeError("no debía llamarse")))
    assert conversacion.cerrar_inactivos(con) == 1


def test_la_racha_es_una_sola_para_el_triaje_y_para_el_cierre(con, monkeypatch):
    hilo = _hilo_vencido(con, monkeypatch)
    _ev(con, 1)
    m = Modelo(motor.MotorNoDisponible("claude: API Error", "api"))
    monkeypatch.setattr(motor, "llamar", m)
    assert triaje.triar(con) == 0
    assert conversacion.cerrar_inactivos(con) == 0 and len(m.llamadas) == 1, "lo que supo el triaje vale al cierre"
    assert _cerrado(con, hilo)["cerrado"] is None


# ── lo que NO se pausa ───────────────────────────────────────────────────────

def test_la_conversacion_no_espera_a_la_pausa_y_dice_la_causa_en_llano(con, monkeypatch):
    """Él está delante: se intenta siempre, y si falla se le dice por qué."""
    motor.pausar(con, motor.MotorNoDisponible("x", "api"), "triaje")
    m = Modelo(motor.MotorNoDisponible("no se pudo arrancar claude: [Errno 2] No such file", "no_arranca"))
    monkeypatch.setattr(motor, "llamar", m)
    conversacion.recibir(con, "¿qué tengo?")
    conversacion.atender(con)
    assert len(m.llamadas) == 1
    t = con.execute("SELECT texto, estado FROM turno WHERE rol = 'secretario'").fetchone()
    assert t["estado"] == "error" and "Claude Code no arranca en esta máquina" in t["texto"]


def test_una_investigacion_dice_la_causa_del_motor_en_llano_y_no_la_repite(con, monkeypatch):
    """C-0323 dejó dicho que usaría esta clasificación: lo que es del motor no
    se repite con otro modelo, y se dice por su causa."""
    m = Modelo(motor.MotorNoDisponible("no se pudo arrancar claude: [Errno 2] No such file", "no_arranca"))
    monkeypatch.setattr(motor, "llamar", m)
    hilo = conversacion.recibir(con, "investiga")["hilo"]
    investigar.encargar(con, "¿Cuánto se conserva?", hilo=hilo, modelo="sonnet")
    investigar.atender(con)
    assert len(m.llamadas) == 1
    texto = conversacion.turnos(con, hilo)[-1]["texto"]
    assert texto.startswith("No pude investigar «¿Cuánto se conserva?»")
    assert "Claude Code no arranca en esta máquina" in texto and "Errno" not in texto


def test_un_fallo_del_motor_que_hable_del_formato_no_se_toma_por_un_fallo_de_formato():
    exc = motor.MotorNoDisponible("claude: API Error mientras structured_output", "api")
    assert investigar._sin_formato(exc) is False
    assert investigar._sin_formato(motor.MotorCaido("claude: structured_output_retry_exhausted")) is True


# ── el ciclo no muere ni se queda sordo (regla dura 2) ───────────────────────

def test_con_el_motor_en_pausa_la_vuelta_hace_todo_lo_demas_y_el_triaje_no_llama(con, monkeypatch):
    from hub.secretario import recordatorios
    _ev(con, 1)
    motor.pausar(con, motor.MotorNoDisponible("x", "api"), "triaje")
    monkeypatch.setattr(motor, "llamar", Modelo(RuntimeError("no debía llamarse")))
    hechos = []
    monkeypatch.setattr(recordatorios, "revisar", lambda c: hechos.append("recordatorios"))
    monkeypatch.setattr(servicio, "leer_fuentes", lambda c: hechos.append("fuentes"))
    monkeypatch.setattr(servicio.copia_base, "hacer", lambda c, **k: hechos.append("copia"))
    servicio.una_vuelta(con, threading.Event())
    assert hechos == ["recordatorios", "fuentes", "copia"]
    assert not [b for b in memoria.bitacora(con) if b["accion"] in ("triaje", "cerrar_hilos") and "Error" in
                str(b["resultado"])], "la pausa no es un fallo del paso"
    assert len(memoria.sin_triar(con)) == 1


def test_si_mirar_la_pausa_falla_el_paso_lo_apunta_y_la_vuelta_sigue(con, monkeypatch):
    _ev(con, 1)
    monkeypatch.setattr(motor, "en_pausa", lambda c: 1 / 0)
    hechos = []
    monkeypatch.setattr(servicio.copia_base, "hacer", lambda c, **k: hechos.append("copia"))
    monkeypatch.setattr(servicio, "leer_fuentes", lambda c: 0)
    servicio.una_vuelta(con, threading.Event())
    assert hechos == ["copia"], "cada paso en su try: el que falla no tumba a los de detrás"
    assert "ZeroDivisionError" in _lineas(con, "triaje")[0]["resultado"]


# ── tras la revisión (C-0307) ────────────────────────────────────────────────

@pytest.mark.parametrize("que", ["triaje", "cierre"])
def test_tras_una_caida_sin_clasificar_un_fallo_pasajero_ya_con_el_motor_de_vuelta_no_se_rinde(con, monkeypatch, que):
    """La cuenta del pedido se quedaba sumada durante la caída (8 fallos, cuenta
    en 8): al volver el motor, un solo fallo pasajero apartaba el lote bueno o
    cerraba el hilo sin resumen."""
    if que == "triaje":
        _ev(con, 1)
        clave, paso = "triaje_fallos", lambda: triaje.triar(con)
    else:
        hilo = _hilo_vencido(con, monkeypatch)
        clave, paso = f"cierre:{hilo}", lambda: conversacion.cerrar_inactivos(con)
    m = Modelo(motor.MotorCaido("claude: algo que nadie ha medido"))
    monkeypatch.setattr(motor, "llamar", m)
    contesta = [False]
    sondas = []
    monkeypatch.setattr(motor, "responde", lambda modelo=None: sondas.append(modelo) or contesta[0])
    for _ in range(8):
        if memoria.leer(con, motor.CLAVE_PAUSA):
            _ya_toca(con)
        paso()
    assert len(m.llamadas) == 8 and len(sondas) == 6, "con la racha en curso se sondea en cada fallo, sin contar hasta tres"
    assert not memoria.leer(con, clave), "lo que falló con el motor caído no cuenta contra el pedido"
    # Vuelve el motor, y justo este pedido falla una vez por otra cosa.
    contesta[0] = True
    m.respuestas = [motor.MotorCaido("el modelo no contestó en 600 s")]
    _ya_toca(con)
    paso()
    assert memoria.leer(con, clave) == 1 and memoria.leer(con, motor.CLAVE_PAUSA) is None
    if que == "triaje":
        assert _apartados(con) == 0 and len(memoria.sin_triar(con)) == 1
    else:
        assert _cerrado(con, hilo)["cerrado"] is None


def test_un_hilo_que_siempre_da_error_de_la_api_se_cierra_aunque_el_triaje_acierte_entre_medias(con, monkeypatch):
    """La red contra quedarse sordo contaba los fallos de la racha, que es de
    todos y la borra el acierto de otro trabajo: 200 vueltas, ninguna sonda, y
    el hilo no se cerraba nunca. Ahora cada pedido lleva su cuenta."""
    hilo = _hilo_vencido(con, monkeypatch)

    def modelo(prompt, **kw):
        if kw["trabajo"] == "cierre":
            raise motor.MotorNoDisponible("claude: API Error: 400", "api")
        return motor.Respuesta(texto="", sesion="s", estructurada={"items": []}, segundos=1.0, coste=0,
                               modelo=kw["modelo"])

    monkeypatch.setattr(motor, "llamar", modelo)
    sondas = _sonda(monkeypatch, True)
    for i in range(motor.FALLOS_PARA_RENDIRSE * motor.COMPROBAR_CADA):
        if memoria.leer(con, motor.CLAVE_PAUSA):
            _ya_toca(con)
        _ev(con, i)
        assert triaje.triar(con) == 1
        _envejecer(con)
        conversacion.cerrar_inactivos(con)
    assert len(sondas) == motor.FALLOS_PARA_RENDIRSE
    assert _cerrado(con, hilo)["cerrado"], "a la tercera comprobación se cierra sin resumen"
    assert not [f[0] for f in con.execute("SELECT clave FROM estado WHERE clave LIKE 'cierre:%'")], "sin cuentas sueltas"


def test_al_acertar_se_olvida_tambien_la_cuenta_de_fallos_del_motor_de_ese_pedido(con, monkeypatch):
    _ev(con, 1)
    m = Modelo(motor.MotorNoDisponible("claude: API Error", "api"))
    monkeypatch.setattr(motor, "llamar", m)
    _sonda(monkeypatch, False)
    for _ in range(4):
        triaje.triar(con)
        _ya_toca(con)
    assert memoria.leer(con, "triaje_fallos:motor") == 4
    m.respuestas = [{"items": []}]
    triaje.triar(con)
    assert memoria.leer(con, "triaje_fallos:motor") is None


def test_al_volver_queda_dicho_en_la_bitacora_una_vez_por_racha(con):
    exc = motor.MotorNoDisponible("claude: API Error", "api")
    for _ in range(5):
        motor.pausar(con, exc, "triaje")
    assert motor.reanudar(con) is True and motor.reanudar(con) is False
    (linea,) = _lineas(con, motor.ACCION_VUELTA)
    assert linea["ok"] == 1 and "vuelve a contestar" in linea["resultado"] and "5" in linea["resultado"]


def test_el_parte_dice_que_el_modelo_ya_volvio_y_no_solo_que_fallo(con, monkeypatch):
    from hub.secretario import resumen

    class P:
        paso, fallos = [], []

        def fallo(self, n, linea):
            self.fallos.append(linea)

    desde = "2000-01-01T00:00:00+00:00"
    motor.pausar(con, motor.MotorNoDisponible("claude: API Error", "api"), "triaje")
    p = P()
    resumen._de_la_memoria(con, p, desde)
    assert len(p.fallos) == 1 and "no está disponible" in p.fallos[0] and "volvió" not in p.fallos[0]
    motor.reanudar(con)
    p = P()
    p.paso, p.fallos = [], []
    resumen._de_la_memoria(con, p, desde)
    assert len(p.fallos) == 1 and "ya volvió" in p.fallos[0] and "no estuvo disponible" in p.fallos[0]
    assert not any("motor" in linea for linea in p.paso), "que volviera no es algo que «hizo»"
    # Si después vuelve a caerse, lo último es que no está.
    motor.pausar(con, motor.MotorNoDisponible("claude: API Error", "api"), "triaje")
    p = P()
    p.paso, p.fallos = [], []
    resumen._de_la_memoria(con, p, desde)
    assert "no está disponible" in p.fallos[0] and "volvió" not in p.fallos[0]
