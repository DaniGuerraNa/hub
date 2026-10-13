"""El chat web de encargos (decisión 246): el servidor, el bot del hub y el reparto.

El servidor se prueba de verdad con `TestClient`, importado desde
`scripts/chat-web/main.py` con una base en tmp y un token de prueba.
"""

from __future__ import annotations

import importlib.util
import io
import json
import sys
from pathlib import Path

import bcrypt
import pytest

RAIZ = Path(__file__).resolve().parents[1]
TOKEN = "token-de-prueba"


@pytest.fixture
def servidor(tmp_path, monkeypatch):
    monkeypatch.setenv("DATOS", str(tmp_path / "datos"))
    monkeypatch.setenv("CHAT_TOKEN", TOKEN)
    spec = importlib.util.spec_from_file_location("chat_web_main", RAIZ / "scripts" / "chat-web" / "main.py")
    modulo = importlib.util.module_from_spec(spec)
    sys.modules["chat_web_main"] = modulo
    spec.loader.exec_module(modulo)
    from fastapi.testclient import TestClient

    return TestClient(modulo.app)


def _hub(servidor):
    return {"Authorization": f"Bearer {TOKEN}"}


def _alta(servidor, usuario="rosa", clave="secreta1"):
    hash_ = bcrypt.hashpw(clave.encode(), bcrypt.gensalt()).decode()
    r = servidor.post("/hub/personas", data={"usuario": usuario, "nombre": "Rosa", "hash": hash_}, headers=_hub(servidor))
    assert r.status_code == 200, r.text
    return r.json()["user_id"]


def test_sin_token_la_puerta_del_hub_no_abre(servidor):
    assert servidor.get("/hub/actualizaciones").status_code == 401
    assert servidor.post("/hub/mensajes", data={"user_id": 1, "texto": "x"},
                         headers={"Authorization": "Bearer otro"}).status_code == 401


def test_entra_con_usuario_y_contrasena_y_solo_con_los_suyos(servidor):
    _alta(servidor)
    assert servidor.post("/entrar", data={"usuario": "rosa", "clave": "mala"}).status_code == 401
    assert servidor.get("/api/mensajes").status_code == 401
    r = servidor.post("/entrar", data={"usuario": "Rosa", "clave": "secreta1"})
    assert r.status_code == 200 and r.json()["nombre"] == "Rosa"
    assert servidor.get("/api/yo").json()["usuario"] == "rosa"


def test_lo_que_escribe_llega_al_hub_como_un_update_de_telegram(servidor):
    uid = _alta(servidor)
    servidor.post("/entrar", data={"usuario": "rosa", "clave": "secreta1"})
    servidor.post("/api/mensajes", data={"texto": "tengo una tienda"})

    r = servidor.get("/hub/actualizaciones", params={"desde": 0}, headers=_hub(servidor))
    (u,) = r.json()["result"]
    assert u["message"]["text"] == "tengo una tienda"
    assert u["message"]["from"]["id"] == uid and u["message"]["chat"]["id"] == uid
    # `desde` es INCLUSIVE, como el offset de Telegram: el relé pide «último + 1».
    assert len(servidor.get("/hub/actualizaciones", params={"desde": u["update_id"]}, headers=_hub(servidor)).json()["result"]) == 1
    assert servidor.get("/hub/actualizaciones", params={"desde": u["update_id"] + 1}, headers=_hub(servidor)).json()["result"] == []


def test_el_evento_siguiente_al_cursor_no_se_salta(servidor):
    """🔴 Pasó de verdad: el primer audio por la web se quedó en el servidor sin
    que el hub lo viera, porque el servidor excluía el id pedido."""
    _alta(servidor)
    servidor.post("/entrar", data={"usuario": "rosa", "clave": "secreta1"})
    servidor.post("/api/mensajes", data={"texto": "uno"})
    (u1,) = servidor.get("/hub/actualizaciones", params={"desde": 0}, headers=_hub(servidor)).json()["result"]
    cursor = u1["update_id"] + 1
    servidor.post("/api/mensajes", data={"texto": "dos"})
    (u2,) = servidor.get("/hub/actualizaciones", params={"desde": cursor}, headers=_hub(servidor)).json()["result"]
    assert u2["message"]["text"] == "dos"


def test_el_hub_puede_cambiarle_el_nombre_sin_tocar_el_usuario(servidor, bot_web):
    uid, clave = bot_web.crear_persona("jacky", "Jacky")
    bot_web.renombrar(uid, "Jackie")
    r = servidor.post("/entrar", data={"usuario": "jacky", "clave": clave})
    assert r.status_code == 200 and r.json()["nombre"] == "Jackie"


def test_lo_que_manda_el_hub_lo_ve_ella_con_sus_botones_y_al_pulsar_llega_un_callback(servidor):
    uid = _alta(servidor)
    r = servidor.post("/hub/mensajes", data={"user_id": uid, "texto": "¿cuál te gusta?",
                                             "botones": json.dumps([["Así", "maqueta-lista"]])}, headers=_hub(servidor))
    mid = r.json()["message_id"]
    servidor.post("/entrar", data={"usuario": "rosa", "clave": "secreta1"})
    vistos = servidor.get("/api/mensajes").json()["mensajes"]
    assert vistos[-1]["texto"] == "¿cuál te gusta?" and json.loads(vistos[-1]["botones"]) == [["Así", "maqueta-lista"]]

    assert servidor.post("/api/botones", data={"mensaje_id": mid, "dato": "maqueta-lista"}).status_code == 200
    (u,) = servidor.get("/hub/actualizaciones", headers=_hub(servidor)).json()["result"]
    assert u["callback_query"]["data"] == "maqueta-lista" and u["callback_query"]["message"]["message_id"] == mid
    servidor.post("/hub/quitar_botones", data={"user_id": uid, "message_id": mid}, headers=_hub(servidor))
    assert servidor.get("/api/mensajes").json()["mensajes"][-1]["botones"] == ""


def test_un_audio_sube_y_el_hub_lo_baja_y_una_foto_del_hub_se_ve(servidor):
    uid = _alta(servidor)
    servidor.post("/entrar", data={"usuario": "rosa", "clave": "secreta1"})
    servidor.post("/api/mensajes", files={"audio": ("a.webm", io.BytesIO(b"opus"), "audio/webm")})
    (u,) = servidor.get("/hub/actualizaciones", headers=_hub(servidor)).json()["result"]
    file_id = u["message"]["voice"]["file_id"]
    assert file_id.startswith("web:")
    r = servidor.get(f"/hub/medios/{file_id[4:]}", headers=_hub(servidor))
    assert r.status_code == 200 and r.content == b"opus"

    r = servidor.post("/hub/fotos", data={"user_id": uid, "pie": "1 · Claro"},
                      files={"foto": ("m.png", io.BytesIO(b"png"), "image/png")}, headers=_hub(servidor))
    assert r.status_code == 200
    foto = servidor.get("/api/mensajes").json()["mensajes"][-1]
    assert foto["tipo"] == "foto" and foto["texto"] == "1 · Claro"
    assert servidor.get(f"/medios-hub/{foto['medio']}").content == b"png"


def test_escribiendo_se_ve_un_rato_y_se_apaga_al_contestar(servidor):
    uid = _alta(servidor)
    servidor.post("/entrar", data={"usuario": "rosa", "clave": "secreta1"})
    servidor.post("/hub/escribiendo", data={"user_id": uid}, headers=_hub(servidor))
    assert servidor.get("/api/mensajes").json()["escribiendo"] is True
    servidor.post("/hub/mensajes", data={"user_id": uid, "texto": "ya"}, headers=_hub(servidor))
    assert servidor.get("/api/mensajes").json()["escribiendo"] is False


def test_nadie_ve_los_medios_de_otra_persona(servidor):
    _alta(servidor, "rosa", "secreta1"); _alta(servidor, "ana", "secreta2")
    servidor.post("/entrar", data={"usuario": "rosa", "clave": "secreta1"})
    servidor.post("/api/mensajes", files={"audio": ("a.webm", io.BytesIO(b"opus"), "audio/webm")})
    medio = servidor.get("/api/mensajes").json()["mensajes"][-1]["medio"]
    servidor.post("/salir")
    servidor.post("/entrar", data={"usuario": "ana", "clave": "secreta2"})
    assert servidor.get(f"/medios/{medio}").status_code == 404
    assert servidor.get("/api/mensajes").json()["mensajes"] == []


# ── El bot del hub, contra ese servidor ─────────────────────────────────────


@pytest.fixture
def bot_web(servidor, monkeypatch):
    """`BotDeChat` cuyo transporte es el TestClient: prueba el bot Y el servidor."""
    from hub import chatweb

    class Respuesta:
        def __init__(self, r): self.r = r
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self): return self.r.content

    def abrir(self, peticion):
        import urllib.error
        r = servidor.request(peticion.get_method(), peticion.full_url.replace("http://chat", ""),
                             content=peticion.data, headers=dict(peticion.header_items()))
        if r.status_code >= 400:
            raise urllib.error.HTTPError(peticion.full_url, r.status_code, r.text, {}, None)
        return Respuesta(r)

    monkeypatch.setattr(chatweb.BotDeChat, "_abrir", abrir)
    return chatweb.BotDeChat("http://chat", TOKEN)


def test_el_bot_da_de_alta_y_devuelve_la_contrasena_una_vez(bot_web, servidor):
    uid, clave = bot_web.crear_persona("rosa", "Rosa")
    assert uid >= 900_000_000 and len(clave) >= 10
    assert servidor.post("/entrar", data={"usuario": "rosa", "clave": clave}).status_code == 200


def test_el_bot_manda_y_recoge_como_el_de_telegram(bot_web, servidor, tmp_path):
    uid, clave = bot_web.crear_persona("rosa", "Rosa")
    mid = bot_web.enviar(uid, "hola")
    assert isinstance(mid, int)
    mid2 = bot_web.enviar_con_botones(uid, "¿así?", [("Así", "maqueta-lista")])
    foto = tmp_path / "f.png"; foto.write_bytes(b"png")
    assert isinstance(bot_web.enviar_foto(uid, foto, "1 · Claro"), int)
    bot_web.escribiendo(uid)

    servidor.post("/entrar", data={"usuario": "rosa", "clave": clave})
    servidor.post("/api/mensajes", data={"texto": "me gusta"})
    servidor.post("/api/botones", data={"mensaje_id": mid2, "dato": "maqueta-lista"})
    servidor.post("/api/mensajes", files={"audio": ("a.webm", io.BytesIO(b"opus"), "audio/webm")})

    updates = bot_web.actualizaciones(None)
    assert [("message" in u, "callback_query" in u) for u in updates] == [(True, False), (False, True), (True, False)]
    voz = updates[2]["message"]["voice"]["file_id"]
    bajado = bot_web.descargar(voz, tmp_path / "audios" / "000001.ogg")
    assert bajado.suffix == ".webm" and bajado.read_bytes() == b"opus"
    bot_web.quitar_botones(uid, mid2)


def test_si_el_servidor_no_esta_el_bot_levanta_lo_mismo_que_telegram(monkeypatch):
    from hub import chatweb, telegram

    def caido(self, peticion):
        raise OSError("sin red")
    monkeypatch.setattr(chatweb.BotDeChat, "_abrir", caido)
    with pytest.raises(telegram.TelegramCaido):
        chatweb.BotDeChat("http://chat", "t").enviar(1, "x")


# ── El reparto por canal ────────────────────────────────────────────────────


class BotEspia:
    def __init__(self, nombre): self.nombre = nombre; self.llamadas = []; self.updates = []
    def enviar(self, chat_id, texto): self.llamadas.append(("enviar", chat_id, texto)); return 1
    def enviar_con_botones(self, chat_id, texto, botones): self.llamadas.append(("botones", chat_id)); return 2
    def enviar_foto(self, chat_id, ruta, pie=""): self.llamadas.append(("foto", chat_id)); return 3
    def escribiendo(self, chat_id): self.llamadas.append(("escribiendo", chat_id))
    def quitar_botones(self, chat_id, message_id): self.llamadas.append(("quitar", chat_id))
    def pulsado(self, callback_id, texto=""): self.llamadas.append(("pulsado", callback_id))
    def descargar(self, file_id, destino): self.llamadas.append(("descargar", file_id)); return destino
    def actualizaciones(self, offset=None): self.llamadas.append(("updates", offset)); return list(self.updates)


@pytest.fixture
def con(tmp_path, monkeypatch):
    from hub import config, db
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "hub.db")
    c = db.conectar(config.DB_PATH); db.inicializar(c)
    yield c
    c.close()


def test_cada_persona_recibe_por_su_canal(con):
    from hub import chatweb, encargos

    encargos.anotar_persona(con, 10, "tg", "De Telegram")
    encargos.anotar_persona(con, 900000001, "rosa", "Rosa")
    encargos.editar_persona(con, 900000001, canal="web")
    tg, web = BotEspia("tg"), BotEspia("web")
    bots = chatweb.Bots(con, {"telegram": tg, "web": web})

    bots.enviar(10, "a"); bots.enviar(900000001, "b"); bots.escribiendo(900000001)
    bots.descargar("web:x.webm", Path("/tmp/x")); bots.descargar("AbC", Path("/tmp/y"))
    bots.pulsado("web7"); bots.pulsado("123")
    assert [l[0] for l in tg.llamadas] == ["enviar", "descargar", "pulsado"]
    assert [l[0] for l in web.llamadas] == ["enviar", "escribiendo", "descargar", "pulsado"]


def test_las_entradas_del_chat_no_mueven_el_offset_de_telegram(con):
    from hub import chatweb

    tg, web = BotEspia("tg"), BotEspia("web")
    tg.updates = [{"update_id": 500, "message": {}}]
    web.updates = [{"update_id": 3, "message": {}}, {"update_id": 4, "message": {}}]
    bots = chatweb.Bots(con, {"telegram": tg, "web": web})

    todos = bots.actualizaciones(400)
    assert len(todos) == 3
    assert [u.get("canal") for u in todos] == [None, "web", "web"]
    assert bots.cursores["web"] == 5
    # La vuelta siguiente pide al chat desde su cursor, y a Telegram desde el suyo.
    bots.actualizaciones(501)
    assert web.llamadas[-1] == ("updates", 5) and tg.llamadas[-1] == ("updates", 501)


def test_una_persona_de_un_canal_sin_configurar_no_se_pierde_en_silencio(con):
    from hub import chatweb, encargos, telegram

    encargos.anotar_persona(con, 900000001, "rosa", "Rosa")
    encargos.editar_persona(con, 900000001, canal="web")
    bots = chatweb.Bots(con, {"telegram": BotEspia("tg")})
    with pytest.raises(telegram.TelegramCaido, match="web"):
        bots.enviar(900000001, "x")


def test_si_el_chat_se_cae_telegram_sigue_y_se_apunta_una_vez(con):
    from hub import chatweb, telegram

    class Caido(BotEspia):
        def actualizaciones(self, offset=None):
            raise telegram.TelegramCaido("sin red")

    tg = BotEspia("tg"); tg.updates = [{"update_id": 9, "message": {}}]
    bots = chatweb.Bots(con, {"telegram": tg, "web": Caido("web")})
    assert len(bots.actualizaciones(None)) == 1
    assert len(bots.actualizaciones(10)) == 1
    fallas = con.execute("SELECT COUNT(*) FROM encargo_registro WHERE detalle LIKE '%web%no responde%'").fetchone()[0]
    assert fallas == 1, "una vez por racha, no una por vuelta"


def test_un_relé_que_se_reinicia_solo_recibe_lo_que_no_había_confirmado(servidor):
    """Pedir desde N confirma lo anterior, como el offset de Telegram: tras un
    reinicio, «desde 0» no repite lo ya entregado al agente."""
    _alta(servidor)
    servidor.post("/entrar", data={"usuario": "rosa", "clave": "secreta1"})
    servidor.post("/api/mensajes", data={"texto": "uno"})
    servidor.post("/api/mensajes", data={"texto": "dos"})
    u1, u2 = servidor.get("/hub/actualizaciones", params={"desde": 0}, headers=_hub(servidor)).json()["result"]
    # El relé procesó «uno» y pide desde el siguiente: eso confirma «uno».
    servidor.get("/hub/actualizaciones", params={"desde": u1["update_id"] + 1}, headers=_hub(servidor))
    tras_reinicio = servidor.get("/hub/actualizaciones", params={"desde": 0}, headers=_hub(servidor)).json()["result"]
    assert [u["message"]["text"] for u in tras_reinicio] == ["dos"]
