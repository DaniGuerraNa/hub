"""Los relés no repiten ni pierden lo que llega cuando una vuelta falla a medias (decisión 345, C-0130)."""

# Sin transacción por mensaje, a propósito: ver la cabecera de `rele_base`.

from __future__ import annotations

import sqlite3

import pytest

from hub import rele_base


@pytest.fixture
def con(con):
    con.execute("CREATE TABLE prueba_rele (u INTEGER)")
    return con


def _guardados(con):
    return [r[0] for r in con.execute("SELECT u FROM prueba_rele ORDER BY rowid")]


def _telegram(desde, ids=(1, 2, 3)):
    return [{"update_id": i} for i in ids if desde is None or i >= desde]


def test_un_fallo_no_repite_lo_ya_tratado_ni_salta_lo_que_viene_detras(con):
    fallar = {2}

    def tratar(u):
        if u["update_id"] in fallar:
            raise RuntimeError("a mitad")
        con.execute("INSERT INTO prueba_rele VALUES (?)", (u["update_id"],))
        return "ok"

    fallos, registro = {}, []
    offset = rele_base.recorrer(con, _telegram(None), None, tratar, registrar=registro.append, fallos=fallos)
    assert offset == 2 and _guardados(con) == [1], "el 3 espera su turno detrás del 2"
    fallar.clear()
    offset = rele_base.recorrer(con, _telegram(offset), offset, tratar, registrar=registro.append, fallos=fallos)
    assert offset == 4 and _guardados(con) == [1, 2, 3], "cada uno una vez"
    assert fallos == {}


def test_uno_que_falla_siempre_se_salta_tras_tres_intentos_sin_su_texto(con):
    def tratar(u):
        if u["update_id"] == 2:
            raise ValueError("contenido privado del mensaje")
        con.execute("INSERT INTO prueba_rele VALUES (?)", (u["update_id"],))
        return "ok"

    fallos, registro, offset = {}, [], None
    for _ in range(3):
        offset = rele_base.recorrer(con, _telegram(offset), offset, tratar, registrar=registro.append, fallos=fallos)
    assert offset == 4 and _guardados(con) == [1, 3]
    assert "saltado tras 3 intentos: ValueError" in registro[-1]
    assert not any("privado" in r for r in registro)


def test_la_base_bloqueada_no_cuenta_como_intento(con):
    def tratar(u):
        raise sqlite3.OperationalError("database is locked")

    fallos, registro = {}, []
    for _ in range(5):
        assert rele_base.recorrer(con, _telegram(None), None, tratar, registrar=registro.append, fallos=fallos) is None
    assert fallos == {}


def test_lo_de_la_red_va_despues_y_si_falla_no_se_repite_el_mensaje(con):
    def tratar(u):
        con.execute("INSERT INTO prueba_rele VALUES (?)", (u["update_id"],))
        return "ok"

    def despues(u, resultado):
        raise ConnectionError("telegram caído")

    registro = []
    offset = rele_base.recorrer(con, _telegram(None), None, tratar, despues=despues,
                                registrar=registro.append, fallos={})
    assert offset == 4 and _guardados(con) == [1, 2, 3]
    assert len(registro) == 3 and "guardado, pero lo de después falló" in registro[0]


def test_el_chat_web_solo_confirma_lo_guardado_y_no_mueve_el_offset(con):
    web = [{"update_id": 7, "id_canal": 10, "canal": "web"}, {"update_id": 7, "id_canal": 11, "canal": "web"}]
    confirmados = []

    def tratar(u):
        if u["id_canal"] == 11:
            raise RuntimeError("falla")
        return "ok"

    offset = rele_base.recorrer(con, web, 7, tratar, registrar=lambda t: None, fallos={},
                                confirmar=lambda u: confirmados.append(u["id_canal"]))
    assert offset == 7 and confirmados == [10], "el 11 no se da por leído"


def test_si_falla_el_propio_registro_la_vuelta_sigue(con):
    def registrar(texto):
        raise sqlite3.DatabaseError("registro roto")

    def tratar(u):
        raise RuntimeError("x")

    assert rele_base.recorrer(con, _telegram(None), None, tratar, registrar=registrar, fallos={}) is None


def test_un_fallo_de_esquema_si_cuenta_como_intento(con):
    """`no such column` también es OperationalError; si no contara, el canal
    se quedaría atascado para siempre en ese mensaje (revisor de C-0130)."""
    def tratar(u):
        raise sqlite3.OperationalError("no such column: x")

    fallos, offset = {}, None
    for _ in range(3):
        offset = rele_base.recorrer(con, _telegram(offset, ids=(1,)), offset, tratar,
                                    registrar=lambda t: None, fallos=fallos)
    assert offset == 2


# ── con los relés de verdad ──────────────────────────────────────────────────


def test_el_rele_de_encargos_no_aparca_dos_veces_si_falla_cerrar_el_boton(con, monkeypatch):
    """Antes, `pulsado` iba antes del commit y sin `try`: un Telegram caído
    hacía que se reentregara y se tratara otra vez."""
    from hub import rele_encargos, telegram

    monkeypatch.setattr(rele_encargos, "FALLOS", {})
    tratados = []
    monkeypatch.setattr(rele_encargos, "procesar_mensaje", lambda c, m: tratados.append(m["callback_id"]) or "comentario")
    for nombre in ("bajar_audios", "transcribir_pendientes", "desplegar_construidos", "construir_lo_aprobado",
                   "mandar_salientes", "atender_esperas", "saludar_a_los_que_no_pueden"):
        monkeypatch.setattr(rele_encargos, nombre, lambda *a, **k: None)
    monkeypatch.setattr(rele_encargos.buzon, "drenar_todos", lambda c: None)

    class Bot:
        def actualizaciones(self, offset=None):
            u = {"update_id": 9, "callback_query": {"id": "cb-9", "data": "x", "from": {"id": 1},
                                                    "message": {"message_id": 3, "chat": {"id": 1}}}}
            return [u] if offset is None or offset <= 9 else []

        def pulsado(self, *a):
            raise telegram.TelegramCaido("sin red")

    bot = Bot()
    offset = rele_encargos.una_vuelta(con, bot, None, {})
    offset = rele_encargos.una_vuelta(con, bot, offset, {})
    assert offset == 10 and tratados == ["cb-9"]


# ── el veredicto del token (C-0144) ──────────────────────────────────────────


def test_la_web_no_abre_el_token_y_dice_lo_que_vio_el_rele(tmp_path, monkeypatch):
    from hub import rele, telegram

    env = tmp_path / "t.env"
    env.write_text("TELEGRAM_BOT_TOKEN=\n", encoding="utf-8")
    yml = tmp_path / "canal.yml"
    yml.write_text(f"token_ref: '{env}#TELEGRAM_BOT_TOKEN'\n", encoding="utf-8")
    monkeypatch.setenv("HUB_CANAL_YML", str(yml))
    leer = telegram.leer_token

    def prohibido(_):
        raise AssertionError("hub-web abrió el token")

    monkeypatch.setattr(telegram, "leer_token", prohibido)
    e = rele.estado()
    assert e["configurado"] is False and e.get("sin_comprobar") and "hub-canal" in e["detalle"]

    # El relé lo abre: con la clave vacía, el diagnóstico de siempre llega a la web.
    monkeypatch.setattr(telegram, "leer_token", leer)
    with pytest.raises(telegram.SinToken):
        rele.bot()
    monkeypatch.setattr(telegram, "leer_token", prohibido)
    e = rele.estado()
    assert e["configurado"] is False and "vacía" in e["detalle"] and not e.get("sin_comprobar")

    env.write_text("TELEGRAM_BOT_TOKEN=123:abc\n", encoding="utf-8")
    monkeypatch.setattr(telegram, "leer_token", leer)
    rele.bot()
    monkeypatch.setattr(telegram, "leer_token", prohibido)
    assert rele.estado()["configurado"] is True
    assert "123:abc" not in (rele_base._veredictos() / "canal.json").read_text(), "el veredicto no lleva el token"

    # Otro puntero: lo que vio el relé era de otro, así que no vale.
    yml.write_text(f"token_ref: '{env}#OTRA'\n", encoding="utf-8")
    assert rele.estado().get("sin_comprobar")


def test_la_transaccion_deshace_todo_y_no_se_anida(tmp_path):
    """C-0152: o todo o nada, y un `BEGIN` dentro de otro se niega antes de
    llegar a SQLite (su error no es «locked» y contaría como intento)."""
    from hub import db

    c = db.conectar(tmp_path / "t.db")
    c.execute("CREATE TABLE x (n INTEGER)")
    with pytest.raises(RuntimeError, match="a mitad"):
        with db.transaccion(c):
            c.execute("INSERT INTO x VALUES (1)")
            raise RuntimeError("a mitad")
    assert c.execute("SELECT COUNT(*) FROM x").fetchone()[0] == 0
    with db.transaccion(c):
        c.execute("INSERT INTO x VALUES (2)")
        with pytest.raises(RuntimeError, match="ya hay una transacción"):
            with db.transaccion(c):
                pass
    assert c.execute("SELECT n FROM x").fetchall()[0][0] == 2


def test_los_efectos_se_difieren_solo_dentro_y_el_ultimo_resultado_manda():
    hechos = []
    assert rele_base.efecto(lambda: hechos.append("ya") or "en el acto") == "en el acto"
    with rele_base.diferidos() as efectos:
        assert rele_base.efecto(lambda: hechos.append("luego") or "uno") is None
        rele_base.efecto(lambda: None)
    assert hechos == ["ya"]
    assert rele_base.ejecutar(efectos) == "uno" and hechos == ["ya", "luego"]


# ── C-0138: si ni apuntar el fallo se puede, el bucle sigue ──────────────────


class _Basta(BaseException):
    """Para el bucle infinito de `correr` desde el `sleep`, que es donde
    llega una vuelta que no tumbó nada. `BaseException` para que el
    `except Exception` del bucle no se la trague."""


@pytest.mark.parametrize("modulo, registro", [("rele", "canal"), ("rele_encargos", "encargos")])
def test_una_vuelta_fallida_con_la_base_bloqueada_no_tumba_el_rele(modulo, registro, monkeypatch, capsys):
    """El apunte del `except` iba sin protección: con la base bloqueada,
    `registrar` lanzaba, el relé salía del `while` y systemd lo levantaba con
    el offset a `None` (regla dura 2)."""
    import importlib

    rele = importlib.import_module(f"hub.{modulo}")
    dueño = importlib.import_module(f"hub.{registro}")

    def vuelta(*_a):
        raise RuntimeError("una vuelta mala")

    def bloqueada(*_a, **_k):
        raise sqlite3.OperationalError("database is locked")

    def dormir(_s):
        raise _Basta

    monkeypatch.setattr(rele, "bot", lambda *a: object())
    monkeypatch.setattr(rele, "una_vuelta", vuelta)
    monkeypatch.setattr(dueño, "registrar", bloqueada)
    monkeypatch.setattr(rele.time, "sleep", dormir)

    with pytest.raises(_Basta):
        rele.correr()
    err = capsys.readouterr().err
    assert "una vuelta mala" in err and "database is locked" in err


# ── El bucle del servicio, uno para los dos relés (C-0134) ───────────────────


class _Relé:
    """Lo que `correr` necesita de un relé, con lo que pasa apuntado."""

    def __init__(self, guion):
        # `guion`: por vuelta, una excepción que lanzar o el offset que devolver.
        self.guion = list(guion)
        self.bots = 0
        self.vistos: list = []
        self.apuntes: list[str] = []
        self.pausas: list[float] = []

    def abrir_bot(self):
        self.bots += 1
        return f"bot-{self.bots}"

    def una_vuelta(self, bot_, offset):
        self.vistos.append((bot_, offset))
        paso = self.guion.pop(0)
        if isinstance(paso, BaseException):
            raise paso
        return paso

    def correr(self, vueltas):
        return rele_base.correr("prueba", self.abrir_bot, self.una_vuelta, self.apuntes.append,
                                dormir=self.pausas.append, vueltas=vueltas)


def test_el_offset_pasa_de_una_vuelta_a_la_siguiente_y_una_vuelta_mala_no_lo_pierde():
    from hub import telegram

    rele = _Relé([5, RuntimeError("una vuelta mala"), telegram.TelegramCaido("sin red"), 9])

    assert rele.correr(vueltas=4) == 9
    assert [o for _, o in rele.vistos] == [None, 5, 5, 5]
    assert rele.pausas == [rele_base.PAUSA, rele_base.PAUSA_TRAS_FALLO, rele_base.PAUSA_TRAS_FALLO, rele_base.PAUSA]
    assert rele.bots == 1, "un fallo de la vuelta no obliga a abrir otro bot"
    assert rele.apuntes == ["vuelta fallida: RuntimeError('una vuelta mala')", "telegram no responde: sin red"]


def test_cada_fallo_se_apunta_con_lo_que_es_y_sin_token_se_vuelve_a_abrir_el_bot():
    """Mismas pausas y excepciones que tenían los dos `correr` copiados: un
    409 se dice siempre (dos pollers se roban los mensajes), y sin token se
    reabre el bot en la vuelta siguiente, que es como se recoge un token
    arreglado sin reiniciar el servicio."""
    from hub import telegram

    rele = _Relé([telegram.DosPollers("otro"), telegram.SinToken("no está"), ValueError("rota"), 3])

    assert rele.correr(vueltas=4) == 3
    assert [b for b, _ in rele.vistos] == ["bot-1", "bot-1", "bot-2", "bot-2"]
    assert [a.split(":")[0] for a in rele.apuntes] == [
        "409, hay otro poller con el mismo token", "sin token utilizable", "vuelta fallida"]
    assert "ValueError('rota')" in rele.apuntes[-1]
    assert rele.pausas == [rele_base.PAUSA_TRAS_FALLO] * 3 + [rele_base.PAUSA]


def test_si_no_se_puede_abrir_el_bot_se_reintenta_en_la_vuelta_siguiente():
    from hub import telegram

    rele = _Relé([7])
    abiertos = iter([telegram.SinToken("vacío"), "bot-bueno"])

    def abrir():
        siguiente = next(abiertos)
        if isinstance(siguiente, BaseException):
            raise siguiente
        return siguiente

    assert rele_base.correr("prueba", abrir, rele.una_vuelta, rele.apuntes.append,
                            dormir=rele.pausas.append, vueltas=2) == 7
    assert rele.vistos == [("bot-bueno", None)]
    assert rele.apuntes == ["sin token utilizable: vacío"]


def test_si_ni_apuntar_el_fallo_se_puede_lo_dice_por_stderr_y_sigue(capsys):
    """El apunte protegido de C-0138, ahora en un solo sitio (regla dura 2)."""
    rele = _Relé([RuntimeError("una vuelta mala"), 4])

    def bloqueada(_texto):
        raise sqlite3.OperationalError("database is locked")

    assert rele_base.correr("prueba", rele.abrir_bot, rele.una_vuelta, bloqueada,
                            dormir=rele.pausas.append, vueltas=2) == 4
    err = capsys.readouterr().err
    assert "[rele prueba]" in err and "una vuelta mala" in err and "database is locked" in err


def test_lo_que_no_es_un_fallo_de_la_vuelta_si_para_el_bucle():
    """Ctrl-C no es una vuelta mala: `except Exception`, no `BaseException`."""
    rele = _Relé([KeyboardInterrupt()])
    with pytest.raises(KeyboardInterrupt):
        rele.correr(vueltas=3)
    assert rele.pausas == []


@pytest.mark.parametrize("modulo", ["rele", "rele_encargos"])
def test_los_dos_relés_corren_el_bucle_comun(modulo):
    """Que no vuelva a haber dos copias del bucle: cada relé abre su base y
    le pasa a `rele_base.correr` su bot, su vuelta y su registro."""
    import importlib
    import inspect

    rele = importlib.import_module(f"hub.{modulo}")
    fuente = inspect.getsource(rele.correr)
    assert "rele_base.correr(" in fuente and "while" not in fuente
    assert not hasattr(rele, "_apuntar_fallo") and not hasattr(rele, "PAUSA")


# ── Los ajustes, por un solo lector (C-0134) ─────────────────────────────────


def test_un_archivo_de_ajustes_que_no_esta_es_nada_y_uno_roto_se_dice_con_su_ruta(tmp_path):
    """Sin configurar es lo normal al llegar; un YAML roto no se traga, o el
    síntoma sería «no llegan mensajes» sin ninguna pista."""
    from hub import config

    ruta = tmp_path / "ajustes.yml"
    assert config.leer_ajustes(ruta) == {}
    ruta.write_text("", encoding="utf-8")
    assert config.leer_ajustes(ruta) == {}
    ruta.write_text("token_ref: secretos.env#BOT\n", encoding="utf-8")
    assert config.leer_ajustes(ruta) == {"token_ref": "secretos.env#BOT"}
    ruta.write_text("token_ref: [sin cerrar\n", encoding="utf-8")
    with pytest.raises(ValueError, match="no es YAML válido") as exc:
        config.leer_ajustes(ruta)
    assert str(ruta) in str(exc.value)


@pytest.mark.parametrize("modulo, archivo", [("rele", "canal_yml"), ("rele_encargos", "encargos_yml")])
def test_cada_relé_lee_su_archivo_por_el_lector_comun(modulo, archivo):
    import importlib
    import inspect

    from hub import config

    rele = importlib.import_module(f"hub.{modulo}")
    assert "yaml." not in inspect.getsource(rele), "el YAML se lee en config.leer_ajustes"
    assert rele.ajustes() == {} and rele.token_configurado() == ""
    getattr(config, archivo)().write_text("token_ref: s.env#UNO\n", encoding="utf-8")
    assert rele.token_configurado() == "s.env#UNO"


# ── Lo de antes de pedir lo nuevo (C-0186) ───────────────────────────────────


def test_un_paso_que_falla_no_impide_los_siguientes_y_se_apunta_una_vez_por_racha():
    """Regla dura 2: el relé no moría, pero un paso que fallaba siempre cortaba
    la vuelta antes de pedir lo nuevo —el último paso— y se quedaba sordo. Cada
    paso va en su `try`, como las mediciones del ciclo lento, y su fallo se
    apunta una vez: uno por vuelta, cada dos segundos, sería ruido."""
    hechos, registro, fallando = [], [], {}

    def roto():
        raise FileNotFoundError("/no/existe.png")

    for _ in range(3):
        rele_base.pasos("prueba", [("mandar", roto), ("esperas", lambda: hechos.append("esperas"))],
                        registrar=registro.append, fallando=fallando)

    assert hechos == ["esperas"] * 3
    assert len(registro) == 1
    assert "mandar" in registro[0] and "FileNotFoundError" in registro[0]


def test_un_paso_que_se_arregla_y_vuelve_a_fallar_se_apunta_otra_vez():
    registro, fallando, roto = [], {}, [True]

    def paso():
        if roto[0]:
            raise RuntimeError("otra vez")

    for estado in (True, False, True):
        roto[0] = estado
        rele_base.pasos("prueba", [("desplegar", paso)], registrar=registro.append, fallando=fallando)

    assert len(registro) == 2


def test_si_ni_el_apunte_se_puede_hacer_los_pasos_siguen():
    hechos = []

    def no_apunta(texto):
        raise sqlite3.OperationalError("database is locked")

    rele_base.pasos("prueba", [("roto", lambda: 1 / 0), ("sigue", lambda: hechos.append(1))],
                    registrar=no_apunta, fallando={})
    assert hechos == [1]
