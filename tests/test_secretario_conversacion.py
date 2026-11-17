"""Lo que le llega al modelo en cada turno del dueño, y qué pasa con el hilo
cuando algo se cruza: un reinicio a mitad, un mensaje mientras se resume.

El modelo se sustituye en la frontera (`motor.llamar`), como en
`test_secretario_trabajos.py`: aquí se mira el prompt que se arma y lo que
queda en la memoria.
"""

from __future__ import annotations

import sqlite3

import pytest

from hub.secretario import conversacion, memoria, motor


@pytest.fixture
def con():
    c = memoria.conectar()
    yield c
    c.close()


class Modelo:
    """Lo que habría contestado `claude -p`, y lo que se le pidió."""

    def __init__(self, *respuestas):
        self.respuestas = list(respuestas)
        self.llamadas: list[dict] = []

    def __call__(self, prompt, **kw):
        self.llamadas.append({"prompt": prompt, **kw})
        r = self.respuestas.pop(0)
        if isinstance(r, Exception):
            raise r
        if callable(r):
            r = r(prompt, kw)
        texto, datos = (r, None) if isinstance(r, str) else ("", r)
        return motor.Respuesta(texto=texto, sesion=kw.get("sesion") or "s-1", estructurada=datos,
                               segundos=1.0, coste=0, modelo=kw["modelo"])


# ── el turno que cortó un reinicio (C-0269) ──────────────────────────────────

def _cortar_a_mitad(con) -> None:
    """Como queda la memoria si el servicio muere contestando: el turno
    tomado y la respuesta a medio escribir."""
    t = con.execute("SELECT id, hilo FROM turno WHERE rol = 'dueno' AND estado = 'pendiente'").fetchone()
    con.execute("UPDATE turno SET estado = 'atendiendo' WHERE id = ?", (t["id"],))
    con.execute("INSERT INTO turno (hilo, rol, estado, creado) VALUES (?, 'secretario', 'escribiendo', ?)",
                (t["hilo"], memoria.ahora()))


def test_un_turno_cortado_por_un_reinicio_se_repite_diciendo_que_lo_hecho_ya_esta_hecho(con, monkeypatch):
    """Se repetía como nuevo: si el corte cayó después de apuntar un compromiso
    o de pedir un permiso, el modelo lo hacía otra vez. Cuando es el proceso
    de `claude` el que muere, el motor ya antepone este aviso (C-0185); cuando
    muere el servicio entero, no lo anteponía nadie."""
    m = Modelo("Ya te lo había apuntado.", "De nada.")
    monkeypatch.setattr(motor, "llamar", m)
    conversacion.recibir(con, "recuérdame llamar a la clínica mañana")
    _cortar_a_mitad(con)
    memoria.comprometer(con, "Llamar a la clínica")   # lo que le dio tiempo a hacer

    conversacion.retomar_cortados(con)                # lo que hace el servicio al arrancar
    conversacion.atender(con)
    prompt = m.llamadas[0]["prompt"]
    assert prompt.startswith(motor.RETOMAR)
    assert prompt.endswith("recuérdame llamar a la clínica mañana"), "con su mensaje, por si no llegó a guardarse"

    # Sólo ese turno: el siguiente es uno más.
    conversacion.recibir(con, "gracias")
    conversacion.atender(con)
    assert motor.RETOMAR not in m.llamadas[1]["prompt"]
    assert con.execute("SELECT COUNT(*) FROM estado WHERE clave LIKE 'retomar:%'").fetchone()[0] == 0


def test_un_turno_que_esperaba_sin_tomar_no_lleva_el_aviso_de_corte(con, monkeypatch):
    """Lo que estaba `pendiente` al reiniciar no llegó al modelo: no hay nada
    hecho que no repetir, y decírselo le haría buscar lo que no existe."""
    m = Modelo("Hola.")
    monkeypatch.setattr(motor, "llamar", m)
    conversacion.recibir(con, "hola")
    conversacion.retomar_cortados(con)
    conversacion.atender(con)
    assert motor.RETOMAR not in m.llamadas[0]["prompt"]


def test_si_el_reinicio_vuelve_a_cortarlo_el_aviso_no_se_pierde(con, monkeypatch):
    def muere(prompt, kw):
        raise KeyboardInterrupt   # el servicio se va con el turno otra vez a medias
    m = Modelo(muere, "Listo.")
    monkeypatch.setattr(motor, "llamar", m)
    conversacion.recibir(con, "apunta que el lunes no trabajo")
    _cortar_a_mitad(con)
    conversacion.retomar_cortados(con)
    with pytest.raises(KeyboardInterrupt):
        conversacion.atender(con)
    conversacion.retomar_cortados(con)
    conversacion.atender(con)
    assert m.llamadas[1]["prompt"].startswith(motor.RETOMAR)


# ── escribir mientras se resume el hilo (C-0270) ─────────────────────────────

def _envejecer(con, minutos: float) -> None:
    from datetime import datetime, timedelta, timezone
    hace = (datetime.now(timezone.utc) - timedelta(minutes=minutos)).isoformat(timespec="seconds")
    con.execute("UPDATE hilo SET ultimo = ?", (hace,))


_RESUMEN = {"titulo": "Facturas", "resumen": "Hablaron de facturas.", "notas": [{"texto": "Factura en pesos"}]}


def test_lo_que_escribe_mientras_se_resume_el_hilo_no_cae_en_un_hilo_cerrado(con, monkeypatch):
    """Resumir tarda (medido: 16 s de mediana, hasta 62). Si en ese rato
    volvía a escribir, su mensaje entraba en ese hilo —que al acabar se
    cerraba igual— y desaparecía de su chat, que sólo pinta el abierto."""
    from hub import api

    def resumir(prompt, kw):
        conversacion.recibir(con, "oye, una cosa más")   # hub-web, mientras el modelo resume
        return _RESUMEN

    monkeypatch.setattr(motor, "llamar", Modelo("Respuesta.", resumir, "Dime."))
    hilo = conversacion.recibir(con, "lo de las facturas")["hilo"]
    conversacion.atender(con)
    _envejecer(con, 31)

    assert conversacion.cerrar_inactivos(con) == 0, "no se cerró: no cuenta como cerrado"
    abierto = conversacion.hilo_abierto(con)
    assert abierto is not None and abierto["id"] == hilo
    assert "oye, una cosa más" in [t["texto"] for t in api.secretario_turnos()["turnos"]]
    # El resumen se tira entero: sus notas saldrían otra vez al cerrarlo de verdad.
    assert memoria.notas(con) == []
    assert abierto["resumen"] == "" and abierto["titulo"] == ""

    conversacion.atender(con)
    assert conversacion.turnos(con, hilo)[-1]["texto"] == "Dime."


def test_el_hilo_que_se_salvo_se_cierra_despues_con_su_resumen_y_sus_notas_una_vez(con, monkeypatch):
    def resumir(prompt, kw):
        conversacion.recibir(con, "oye, una cosa más")
        return _RESUMEN

    monkeypatch.setattr(motor, "llamar", Modelo("Respuesta.", resumir, "Dime.", _RESUMEN))
    hilo = conversacion.recibir(con, "lo de las facturas")["hilo"]
    conversacion.atender(con)
    _envejecer(con, 31)
    conversacion.cerrar_inactivos(con)
    conversacion.atender(con)
    _envejecer(con, 31)
    assert conversacion.cerrar_inactivos(con) == 1
    cerrado = con.execute("SELECT * FROM hilo WHERE id = ?", (hilo,)).fetchone()
    assert cerrado["cerrado"] and cerrado["titulo"] == "Facturas"
    assert [n["texto"] for n in memoria.notas(con)] == ["Factura en pesos"]


def test_si_resumir_falla_tres_veces_y_el_escribio_mientras_tampoco_se_cierra(con, monkeypatch):
    """A la tercera se cierra sin resumen; pero no encima de un mensaje suyo."""
    def falla_y_escribe(prompt, kw):
        conversacion.recibir(con, "sigo aquí")
        raise motor.MotorCaido("sin red")

    monkeypatch.setattr(motor, "llamar", Modelo("Respuesta.", motor.MotorCaido("sin red"),
                                                motor.MotorCaido("sin red"), falla_y_escribe))
    # Antes de cerrar sin resumen se sondea (C-0307): aquí el motor contesta.
    monkeypatch.setattr(motor, "responde", lambda modelo=None: True)
    hilo = conversacion.recibir(con, "hola")["hilo"]
    conversacion.atender(con)
    for _ in range(3):
        _envejecer(con, 31)
        conversacion.cerrar_inactivos(con)
    assert conversacion.hilo_abierto(con)["id"] == hilo


# ── el turno lleva su hora (C-0272) ──────────────────────────────────────────

def _dicho_el(con, cuando_utc: str) -> None:
    con.execute("UPDATE turno SET creado = ? WHERE rol = 'dueno' AND estado = 'pendiente'", (cuando_utc,))


def test_cada_turno_lleva_delante_el_dia_y_la_hora_en_que_lo_dijo(con, monkeypatch):
    """Sin esto, cada «mañana» o «el jueves» costaba una vuelta a la
    herramienta `ahora` (medido: 2,8 s más de mediana en el primer turno de un
    hilo) y, si no la daba, una fecha mal calculada."""
    monkeypatch.setenv("TZ", "America/Mexico_City")
    m = Modelo("Apuntado.", "Vale.")
    monkeypatch.setattr(motor, "llamar", m)
    conversacion.recibir(con, "recuérdame mañana llamar al banco")
    _dicho_el(con, "2026-11-12T22:42:00+00:00")
    conversacion.atender(con)
    assert m.llamadas[0]["prompt"].endswith(
        "(Te lo dice el jueves 2026-11-12 a las 16:42, hora de America/Mexico_City.)\n\n"
        "recuérdame mañana llamar al banco")

    # También en los turnos siguientes del hilo: la sesión sigue, la hora no.
    conversacion.recibir(con, "mejor el lunes")
    _dicho_el(con, "2026-11-13T06:05:00+00:00")
    conversacion.atender(con)
    assert m.llamadas[1]["prompt"] == ("(Te lo dice el viernes 2026-11-13 a las 00:05, hora de America/Mexico_City.)"
                                       "\n\nmejor el lunes")


def test_la_hora_es_la_de_cuando_lo_dijo_no_la_de_cuando_se_contesta(con, monkeypatch):
    """Un turno que esperó a un reinicio pasada la medianoche: «mañana» sigue
    siendo el día siguiente al que lo dijo."""
    monkeypatch.setenv("TZ", "Europe/Madrid")
    m = Modelo("Hecho.")
    monkeypatch.setattr(motor, "llamar", m)
    conversacion.recibir(con, "mañana tengo dentista")
    _dicho_el(con, "2020-02-29T22:59:00+00:00")
    conversacion.atender(con)
    assert "(Te lo dice el sábado 2020-02-29 a las 23:59, hora de Europe/Madrid.)" in m.llamadas[0]["prompt"]


def test_las_demas_marcas_siguen_pegadas_a_lo_que_dice_y_la_hora_va_por_fuera(con, monkeypatch):
    monkeypatch.setenv("TZ", "America/Mexico_City")
    m = Modelo("Sí.")
    monkeypatch.setattr(motor, "llamar", m)
    conversacion.recibir(con, "¿me oyes?", pantalla="/trabajo", voz=True)
    _dicho_el(con, "2026-11-12T22:42:00+00:00")
    conversacion.atender(con)
    assert m.llamadas[0]["prompt"].endswith(
        "(Te lo dice el jueves 2026-11-12 a las 16:42, hora de America/Mexico_City.)\n\n"
        "(por voz) (Me escribe desde la pantalla /trabajo del hub.)\n\n¿me oyes?")


def test_el_sistema_le_dice_que_la_fecha_ya_viene_en_el_turno():
    texto = conversacion.SISTEMA
    assert "Te lo dice el" in texto, "nombra la marca tal como llega"
    assert "Antes de interpretar «mañana», «el jueves» o «la semana pasada», usa `ahora`" not in texto


def test_la_herramienta_ahora_ya_no_pide_que_se_la_llame_antes_de_cada_fecha():
    from hub.secretario import herramientas
    descripcion = herramientas.todas()["ahora"].descripcion
    assert "Úsala antes de interpretar" not in descripcion


# ── cambiar archivos: no escribe, pero sabe a quién encargarlo (C-0273) ──────

def test_el_sistema_le_dice_como_encargar_un_cambio_en_vez_de_prohibirle_prometerlo():
    """Decía «Sólo puedes leer; no escribas ni prometas cambiar archivos», y
    ante «arregla el README de tal proyecto» contestaba que no podía, teniendo
    dos formas de encargarlo."""
    from hub.secretario import piezas

    texto = conversacion.SISTEMA
    assert "no escribas ni prometas cambiar archivos" not in texto
    for accion in ("encargar_al_orquestador", "escribir_en_sesion"):
        assert f"`accion_{accion}`" in texto
        assert accion in piezas.acciones(), "el sistema no puede nombrar una acción que no existe"
    # Sigue sin escribir él (regla dura 16) y sin darlo por hecho: las dos piden permiso.
    assert "Tú no escribes en sus archivos" in texto
    assert "no que ya está cambiado" in texto


# ── lo dictado sin revisar (C-0291) ──────────────────────────────────────────

def test_un_dictado_sin_revisar_llega_con_su_marca_junto_a_las_demas(con, monkeypatch):
    """Whisper oye «prisa» por «Brisa»: el modelo tiene que saber que el texto
    puede traer palabras mal oídas. La marca va con las demás, pegada a lo
    que dice, y la hora por fuera."""
    monkeypatch.setenv("TZ", "America/Mexico_City")
    m = Modelo("¿Brisa mantenimiento?")
    monkeypatch.setattr(motor, "llamar", m)
    turno = conversacion.recibir(con, "abre lo de prisa mantenimiento", voz=True, dictado=True)["turno"]
    _dicho_el(con, "2026-11-12T22:42:00+00:00")
    conversacion.atender(con)
    assert m.llamadas[0]["prompt"].endswith(
        "(Te lo dice el jueves 2026-11-12 a las 16:42, hora de America/Mexico_City.)\n\n"
        "(por voz) (dictado) abre lo de prisa mantenimiento")
    # La marca es del turno: no se queda en la memoria ni pasa al siguiente.
    assert memoria.leer(con, f"dictado:{turno}") is None


def test_lo_escrito_no_lleva_la_marca_de_dictado(con, monkeypatch):
    m = Modelo("Vale.")
    monkeypatch.setattr(motor, "llamar", m)
    conversacion.recibir(con, "abre lo de Brisa mantenimiento")
    conversacion.atender(con)
    assert "(dictado)" not in m.llamadas[0]["prompt"]


def test_el_sistema_explica_la_marca_de_dictado():
    texto = conversacion.SISTEMA
    assert "«(dictado)»" in texto and "mal oídas" in texto


# ── si no puede contestar, en llano y con qué hacer (C-0301) ─────────────────

#: Como llega de la clasificación del motor (C-0307): con su causa.
_Clasificado = motor.MotorNoDisponible


@pytest.mark.parametrize("fallo, dice", [
    # Los textos de `motor.py` tal cual los arma hoy.
    (motor.MotorCaido("no se pudo arrancar claude: [Errno 2] No such file or directory: 'claude'"),
     "Claude Code no arranca en esta máquina"),
    (motor.MotorCaido("el modelo no contestó en 600 s"), "Tardaba demasiado y lo corté"),
    # Medido (C-0170): el `result` de un corte a mitad.
    (motor.MotorCaido("claude: API Error: stream idle timeout - partial response received"),
     "Claude contestó con un error"),
    (motor.MotorCaido("claude: api_error"), "Claude contestó con un error"),
    (motor.MotorCaido("`claude -p` salió con 1: Error: algo"), "Claude contestó con un error"),
    (sqlite3.OperationalError("database is locked"), "Mi memoria estaba ocupada"),
    (KeyError("tarjetas"), "Falló algo por dentro"),
    # Lo que traiga la clasificación, sin tocar esto.
    (_Clasificado("claude: You have hit your limit", "cuota", "15:00"), "Se acabó tu uso de Claude hasta las 15:00"),
    (_Clasificado("claude: Invalid API key", "sin_sesion"), "no tiene la sesión iniciada"),
    (_Clasificado("claude: API Error: Connection error.", "red"), "parece un corte de la conexión"),
])
def test_si_no_puede_contestar_lo_dice_en_llano_con_que_hacer_y_el_detalle_va_al_registro(
        con, monkeypatch, capsys, fallo, dice):
    """Salía «No pude contestar: claude: <lo que dijera la CLI>» o «falló algo
    por dentro (OperationalError: …)»: en inglés o en jerga, y sin saber si
    esperar, reintentar o arreglar algo. Lo técnico sigue diciéndose, en el
    registro del servicio (regla 21)."""
    monkeypatch.setattr(motor, "llamar", Modelo(fallo))
    conversacion.recibir(con, "¿qué tengo?")
    conversacion.atender(con)
    t = con.execute("SELECT texto, estado FROM turno WHERE rol = 'secretario'").fetchone()
    assert t["estado"] == "error"
    assert t["texto"].startswith("No pude contestar") and dice in t["texto"]
    tecnico = str(fallo)
    assert tecnico not in t["texto"]
    # De la salida de `claude`, al registro sólo va que la hubo (C-0314).
    assert (tecnico.split(": ", 1)[0] if tecnico.startswith("`claude -p`") else tecnico) in capsys.readouterr().err


def test_lo_que_falla_por_lo_que_mandaste_ya_se_dice_en_llano_y_se_queda(con, monkeypatch):
    """Una imagen o un PDF que no entra ya dice qué pasó y cómo seguir."""
    texto = "la imagen «captura.png» pesa 30 MB, más de lo que admite el modelo, y no encuentro ffmpeg para reducirla"
    monkeypatch.setattr(motor, "llamar", Modelo(motor.MotorCaido(texto)))
    conversacion.recibir(con, "¿qué pone aquí?")
    conversacion.atender(con)
    t = con.execute("SELECT texto FROM turno WHERE rol = 'secretario'").fetchone()
    assert t["texto"] == f"No pude contestar: {texto}"


# ── lo que queda tras un fallo: el registro, el turno y la memoria (C-0314) ──

def test_al_registro_va_el_motivo_del_fallo_y_no_la_salida_de_claude(con, monkeypatch, capsys):
    """Al fallar un turno, el texto del `MotorCaido` iba crudo al journal:
    hasta 400 caracteres de la cola de la salida de `claude`, que con
    `--output-format json` es la respuesta misma (regla dura 22)."""
    salida = '{"type": "result", "result": "Tu cita con el dentista es el lunes", "session_id": "s-1"}'
    monkeypatch.setattr(motor, "llamar", Modelo(motor.MotorCaido(f"`claude -p` salió con 1: {salida}")))
    conversacion.recibir(con, "¿qué tengo?")
    conversacion.atender(con)
    err = capsys.readouterr().err
    assert "MotorCaido: `claude -p` salió con 1" in err
    assert "dentista" not in err


def test_al_registro_no_van_llaves_ni_mas_de_una_linea_corta(con, monkeypatch, capsys):
    llave = "sk-ant-api03-" + "a" * 40
    monkeypatch.setattr(motor, "llamar", Modelo(motor.MotorCaido(f"claude: API Error: 401 {llave} " + "x" * 600)))
    conversacion.recibir(con, "hola")
    conversacion.atender(con)
    [linea] = [l for l in capsys.readouterr().err.splitlines() if "no contesté el turno" in l]
    assert llave not in linea and "[secreto oculto]" in linea
    assert len(linea) < 300


def _ocupada(*_a, **_k):
    raise sqlite3.OperationalError("database is locked")


def test_si_algo_falla_antes_de_llamar_al_modelo_el_turno_no_se_queda_atendiendo(con, monkeypatch):
    """Lo que se prepara antes de llamar al modelo iba fuera del `try`: un
    fallo ahí dejaba el turno «atendiendo» y un globo «pensando» hasta el
    próximo reinicio, y nadie volvía a mirarlo."""
    m = Modelo("no llega")
    monkeypatch.setattr(motor, "llamar", m)
    monkeypatch.setattr(conversacion, "_contexto_inicial", _ocupada)
    conversacion.recibir(con, "¿qué tengo?")
    conversacion.atender(con)
    filas = {f["rol"]: (f["estado"], f["texto"]) for f in con.execute("SELECT rol, estado, texto FROM turno")}
    assert filas["dueno"][0] == "error"
    assert filas["secretario"] == ("error", conversacion.explicar_fallo(sqlite3.OperationalError("database is locked")))
    assert m.llamadas == []


def test_si_ni_siquiera_se_puede_abrir_la_respuesta_el_fallo_se_ve_igual(con, monkeypatch):
    """El primer paso tras tomarlo es apuntar la respuesta: si es ése el que
    falla, el fallo se dice en un turno nuevo."""
    monkeypatch.setattr(motor, "llamar", Modelo("no llega"))
    conversacion.recibir(con, "hola")
    real, veces = memoria.ahora, []

    def ahora():
        veces.append(1)
        if len(veces) == 1:
            _ocupada()
        return real()
    monkeypatch.setattr(memoria, "ahora", ahora)
    conversacion.atender(con)
    filas = [tuple(f) for f in con.execute("SELECT rol, estado FROM turno ORDER BY id")]
    assert filas == [("dueno", "error"), ("secretario", "error")]


def test_si_el_turno_se_corta_mientras_escala_no_queda_la_marca_de_escalar(con, monkeypatch):
    """La herramienta `escalar` deja `escalar:<turno>` y el motor cae antes de
    que `contestar` la recoja: la marca se quedaba para siempre."""
    def escala_y_se_corta(prompt, kw):
        hilo = kw["entorno_extra"]["SECRETARIO_HILO"]
        memoria.poner(con, f"escalar:{memoria.leer(con, f'turno_en_curso:{hilo}')}", {"motivo": "difícil"})
        raise motor.MotorCaido("el modelo no contestó en 600 s")
    monkeypatch.setattr(motor, "llamar", Modelo(escala_y_se_corta))
    conversacion.recibir(con, "piénsalo a fondo")
    conversacion.atender(con)
    assert con.execute("SELECT COUNT(*) FROM estado WHERE clave LIKE 'escalar:%'").fetchone()[0] == 0


def test_al_arrancar_se_quita_la_marca_de_escalar_de_la_respuesta_cortada(con):
    """El turno se repite con otra respuesta: la marca de la cortada no la
    recoge nadie."""
    conversacion.recibir(con, "hola")
    _cortar_a_mitad(con)
    rid = con.execute("SELECT id FROM turno WHERE rol = 'secretario' AND estado = 'escribiendo'").fetchone()[0]
    memoria.poner(con, f"escalar:{rid}", {"motivo": "difícil"})
    conversacion.retomar_cortados(con)
    assert memoria.leer(con, f"escalar:{rid}") is None


@pytest.mark.parametrize("al_resumir", [
    [motor.MotorCaido("sin red"), _RESUMEN],                                          # falla y luego sale
    [motor.MotorCaido("sin red"), motor.MotorCaido("sin red"), motor.MotorCaido("sin red")],   # sin resumen
])
def test_un_hilo_que_se_cierra_tras_fallar_el_resumen_no_deja_su_cuenta_de_intentos(con, monkeypatch, al_resumir):
    monkeypatch.setattr(motor, "llamar", Modelo("Respuesta.", *al_resumir))
    # Antes de cerrar sin resumen se sondea (C-0307): aquí el motor contesta.
    monkeypatch.setattr(motor, "responde", lambda modelo=None: True)
    hilo = conversacion.recibir(con, "hola")["hilo"]
    conversacion.atender(con)
    for _ in al_resumir:
        _envejecer(con, 31)
        conversacion.cerrar_inactivos(con)
    assert con.execute("SELECT cerrado FROM hilo WHERE id = ?", (hilo,)).fetchone()[0]
    assert memoria.leer(con, f"cierre:{hilo}") is None


# ── el latido mientras contesta un turno largo (C-0320) ──────────────────────

class _Reloj:
    """Un reloj que sólo avanza cuando el doble del motor lo dice."""

    def __init__(self, monkeypatch):
        from datetime import datetime, timedelta, timezone
        self.t, base = 1000.0, datetime(2026, 11, 13, 12, 0, tzinfo=timezone.utc)
        self.fecha = lambda: (base + timedelta(seconds=self.t)).isoformat(timespec="seconds")
        # Sólo el reloj que mira `conversacion`: el de verdad sigue para los demás.
        from types import SimpleNamespace
        monkeypatch.setattr(conversacion, "time", SimpleNamespace(monotonic=lambda: self.t), raising=False)
        monkeypatch.setattr(memoria, "ahora", self.fecha)

    def edad_del_latido(self, con) -> float:
        from datetime import datetime
        latido = memoria.leer(con, "latido")
        assert latido, "no latió"
        return (datetime.fromisoformat(self.fecha()) - datetime.fromisoformat(latido)).total_seconds()


def test_mientras_contesta_un_turno_largo_el_latido_no_envejece(con, monkeypatch):
    """SEC2-21: el hilo del chat sólo latía entre turno y turno. Con el ciclo
    atascado en el triaje y un turno de más de dos minutos, la pantalla decía
    «no está en marcha» mientras el secretario contestaba."""
    reloj, edades, escrituras = _Reloj(monkeypatch), [], []
    real = memoria.poner
    monkeypatch.setattr(memoria, "poner", lambda c, clave, valor: (
        escrituras.append(clave) if clave == "latido" else None, real(c, clave, valor))[1])

    def tarda_150_s(prompt, kw):
        texto = ""
        for paso in range(75):
            reloj.t += 2
            if paso % 3:
                texto += "palabra "
                kw["al_trozo"](texto)
            else:
                kw["al_evento"]({"tipo": "pensando"})
            edades.append(reloj.edad_del_latido(con))
        return texto.strip()
    monkeypatch.setattr(motor, "llamar", Modelo(tarda_150_s))
    conversacion.recibir(con, "cuéntame todo lo de la semana")
    conversacion.atender(con)
    assert max(edades) <= 10
    # Y sin escribir en cada trozo: una vez cada pocos segundos.
    assert len(escrituras) <= 150 / conversacion.LATIR_CADA_S + 1


def test_un_latido_que_no_se_puede_escribir_no_tumba_el_turno(con, monkeypatch):
    real = memoria.poner

    def poner(c, clave, valor):
        if clave == "latido":
            raise sqlite3.OperationalError("database is locked")
        return real(c, clave, valor)
    monkeypatch.setattr(memoria, "poner", poner)
    monkeypatch.setattr(motor, "llamar", Modelo(lambda prompt, kw: kw["al_trozo"]("Hecho.") or "Hecho."))
    conversacion.recibir(con, "hola")
    conversacion.atender(con)
    assert [tuple(f) for f in con.execute("SELECT rol, estado, texto FROM turno ORDER BY id")][-1] == (
        "secretario", "listo", "Hecho.")


# ── cuánto tarda la primera palabra (C-0321) ─────────────────────────────────

def _linea_del_turno(capsys) -> str:
    [linea] = [l for l in capsys.readouterr().out.splitlines() if l.startswith("[turno]")]
    return linea


def test_queda_dicho_cuanto_tardo_la_primera_palabra_sin_el_texto_del_turno(con, monkeypatch, capsys):
    """SEC2-22: `turno.segundos` es la respuesta entera. Lo que se nota —y en
    voz, lo que se espera en silencio— es cuánto tarda en empezar. Una línea
    en el journal, como la de `[aprobada]`: sin esquema y sin contenido."""
    reloj = _Reloj(monkeypatch)

    def con_herramienta_y_trozos(prompt, kw):
        reloj.t += 1.5
        kw["al_evento"]({"tipo": "herramienta", "nombre": "buscar", "args": {"texto": "el contrato de Ana"}})
        reloj.t += 1.0
        kw["al_evento"]({"tipo": "fin_herramienta"})
        reloj.t += 0.5
        kw["al_trozo"]("El contrato")
        reloj.t += 4.0
        kw["al_trozo"]("El contrato vence el viernes.")
        return "El contrato vence el viernes."
    monkeypatch.setattr(motor, "llamar", Modelo(con_herramienta_y_trozos))
    t = conversacion.recibir(con, "¿cuándo vence el contrato de Ana?", voz=True)
    conversacion.atender(con)
    linea = _linea_del_turno(capsys)
    assert linea.startswith(f"[turno] {t['turno']}: ")
    assert "primer_trozo=3.0 s" in linea and "total=7.0 s" in linea
    assert "voz=sí" in linea and "herramientas=1" in linea and "estado=listo" in linea
    for contenido in ("contrato", "Ana", "viernes", "buscar"):
        assert contenido not in linea


def test_un_turno_que_falla_antes_de_decir_nada_lo_dice_sin_inventar_la_primera_palabra(con, monkeypatch, capsys):
    monkeypatch.setattr(motor, "llamar", Modelo(motor.MotorCaido("el modelo no contestó en 600 s")))
    conversacion.recibir(con, "hola")
    conversacion.atender(con)
    linea = _linea_del_turno(capsys)
    assert "primer_trozo=- " in linea and "voz=no" in linea and "herramientas=0" in linea and "estado=error" in linea


# ── la red para los «no puedo» (C-0324) ──────────────────────────────────────

def _huecos(con) -> list[dict]:
    import json
    return [{"params": json.loads(b["params"]), "resultado": b["resultado"]}
            for b in memoria.bitacora(con)[::-1] if b["accion"] == "hueco"]


@pytest.mark.parametrize("respuesta", [
    "No puedo hacer eso: no manejo tu correo.",
    "Eso aún no sé hacerlo.",
    "Para eso no tengo herramienta, lo siento.",
    "Ahí no tengo acceso.",
])
def test_si_dice_que_no_puede_y_no_apunto_que_faltaba_queda_un_hueco_sin_clasificar(con, monkeypatch, respuesta):
    """SEC2-07: el registro de C-0247 depende de que el modelo llame a
    `no_se_hacer`, y en dos días no lo llamó ni una vez. Sin fiarse de él: si
    la respuesta suena a «no puedo», queda apuntado con el turno y sin texto."""
    monkeypatch.setattr(motor, "llamar", Modelo(respuesta))
    conversacion.recibir(con, "contéstale a Ana el correo del contrato")
    conversacion.atender(con)
    rid = con.execute("SELECT id FROM turno WHERE rol = 'secretario'").fetchone()[0]
    assert _huecos(con) == [{"params": {"turno": rid}, "resultado": conversacion.HUECO_SIN_CLASIFICAR}]
    assert tuple(con.execute("SELECT estado, texto FROM turno WHERE id = ?", (rid,)).fetchone()) == ("listo", respuesta)


def test_si_ya_apunto_el_hueco_en_ese_turno_la_red_no_lo_duplica(con, monkeypatch):
    from hub.secretario import herramientas

    def lo_apunta(prompt, kw):
        herramientas.todas(con_el_dueno=True)["no_se_hacer"].funcion(con, {"que": "contestar un correo"})
        return "No puedo contestar correos todavía. ¿Lo apunto como mejora en el tablero?"
    monkeypatch.setattr(motor, "llamar", Modelo(lo_apunta))
    conversacion.recibir(con, "contéstale a Ana")
    conversacion.atender(con)
    assert _huecos(con) == [{"params": {"que": "contestar un correo"}, "resultado": "sin herramienta"}]


def test_una_respuesta_normal_o_de_practica_de_ingles_no_deja_hueco(con, monkeypatch):
    monkeypatch.setattr(motor, "llamar", Modelo("Hecho: ya puedo decirte que vence el viernes.",
                                                "No puedo: in English we say «I can't»."))
    conversacion.recibir(con, "¿cuándo vence?")
    conversacion.atender(con)
    conversacion.poner_ingles(con, True)
    conversacion.recibir(con, "how do you say no puedo?")
    conversacion.atender(con)
    assert _huecos(con) == []


def test_si_la_red_no_puede_apuntar_la_respuesta_queda_igual(con, monkeypatch):
    real = memoria.apuntar

    def apuntar(c, accion, **kw):
        if accion == "hueco":
            raise sqlite3.OperationalError("database is locked")
        return real(c, accion, **kw)
    monkeypatch.setattr(memoria, "apuntar", apuntar)
    monkeypatch.setattr(motor, "llamar", Modelo("No puedo hacer eso."))
    conversacion.recibir(con, "manda el correo")
    conversacion.atender(con)
    assert [tuple(f) for f in con.execute("SELECT rol, estado, texto FROM turno ORDER BY id")][-1] == (
        "secretario", "listo", "No puedo hacer eso.")
