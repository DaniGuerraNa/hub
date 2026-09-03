"""El cliente de la Bot API: el único sitio del canal que toca la red.

Tiene tests propios porque el `BotFalso` de `test_rele.py` sólo prueba el
contrato que el relé usa: si este cliente cambiara de forma, aquellos seguirían
verdes protegiendo nada.

Aquí tampoco se sale a internet — se sustituye `urlopen`.
"""

from __future__ import annotations

import io
import json
import urllib.error

import pytest

from hub import telegram


# ── el token: lo único que no puede estar en la base ──────────────────────────


def test_el_token_se_saca_de_un_env_por_su_clave(tmp_path):
    env = tmp_path / "telegram.env"
    env.write_text(
        "# comentario\nOTRA=xxx\nTELEGRAM_BOT_TOKEN=123:abc\n", encoding="utf-8"
    )
    assert telegram.leer_token(f"{env}#TELEGRAM_BOT_TOKEN") == "123:abc"


def test_se_admite_export_y_comillas(tmp_path):
    """Es como acaban escritos estos archivos; rechazarlo sólo daría un fallo
    confuso sobre algo que es correcto en un `.env`."""
    env = tmp_path / "t.env"
    env.write_text('export TELEGRAM_BOT_TOKEN="123:abc"\n', encoding="utf-8")
    assert telegram.leer_token(f"{env}#TELEGRAM_BOT_TOKEN") == "123:abc"


def test_un_archivo_sin_ancla_es_el_token_entero(tmp_path):
    solo = tmp_path / "token"
    solo.write_text("123:abc\n", encoding="utf-8")
    assert telegram.leer_token(str(solo)) == "123:abc"


@pytest.mark.parametrize(
    "referencia,esperado",
    [
        ("", "ninguna referencia"),
        ("/no/existe.env#X", "no existe"),
    ],
)
def test_un_puntero_que_no_lleva_a_nada_lo_dice(referencia, esperado):
    """Se dice DÓNDE se buscó. «Sin token» a secas no se puede arreglar."""
    with pytest.raises(telegram.SinToken, match=esperado):
        telegram.leer_token(referencia)


def test_una_clave_que_no_esta_lo_dice(tmp_path):
    env = tmp_path / "t.env"
    env.write_text("OTRA=x\n", encoding="utf-8")
    with pytest.raises(telegram.SinToken, match="TELEGRAM_BOT_TOKEN"):
        telegram.leer_token(f"{env}#TELEGRAM_BOT_TOKEN")


def test_una_clave_vacia_no_es_un_token(tmp_path):
    """🔴 `CLAVE=` a secas es el estado NORMAL antes de pegar el token.

    Encontrado montando el canal de verdad: se dejó el `.env` preparado con la
    clave vacía y `rele.estado()` contestó «el puntero lleva a un token». El
    fallo habría salido tres capas más tarde, como un 401 de Telegram.
    """
    env = tmp_path / "t.env"
    env.write_text("TELEGRAM_BOT_TOKEN=\n", encoding="utf-8")
    with pytest.raises(telegram.SinToken, match="vacía"):
        telegram.leer_token(f"{env}#TELEGRAM_BOT_TOKEN")


# ── los errores que hay que distinguir ────────────────────────────────────────


def _respuesta(payload):
    return io.BytesIO(json.dumps(payload).encode())


def test_el_409_sale_como_dos_pollers(monkeypatch):
    """🔴 `HTTPError` hereda de `URLError`.

    Si se atrapara la clase padre primero, un 409 se vería como «la red no va» y
    el fallo que más importa distinguir de este canal —dos pollers robándose los
    mensajes— se perdería entre los de conexión.
    """
    def urlopen_409(peticion, timeout=None):
        raise urllib.error.HTTPError(
            "u", 409, "Conflict", {},
            io.BytesIO(json.dumps(
                {"description": "terminated by other getUpdates request"}
            ).encode()),
        )

    monkeypatch.setattr(telegram.urllib.request, "urlopen", urlopen_409)
    with pytest.raises(telegram.DosPollers, match="getUpdates"):
        telegram.Bot("123:abc").actualizaciones()


def test_un_fallo_de_red_es_reintentable_y_no_un_409(monkeypatch):
    def urlopen_caido(peticion, timeout=None):
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(telegram.urllib.request, "urlopen", urlopen_caido)
    with pytest.raises(telegram.TelegramCaido):
        telegram.Bot("123:abc").actualizaciones()


def test_un_ok_false_no_se_toma_por_bueno(monkeypatch):
    """La API contesta 200 con `ok: false`. Fiarse del HTTP daría por enviado
    algo que no salió."""
    monkeypatch.setattr(
        telegram.urllib.request, "urlopen",
        lambda p, timeout=None: _CtxFalso({"ok": False, "description": "chat not found"}),
    )
    with pytest.raises(telegram.TelegramCaido, match="chat not found"):
        telegram.Bot("123:abc").enviar(1, "hola")


class _CtxFalso:
    def __init__(self, payload):
        self._r = _respuesta(payload)

    def __enter__(self):
        return self._r

    def __exit__(self, *a):
        return False


def test_enviar_devuelve_el_message_id(monkeypatch):
    """Ese id es lo que casa la respuesta con su pregunta."""
    monkeypatch.setattr(
        telegram.urllib.request, "urlopen",
        lambda p, timeout=None: _CtxFalso({"ok": True, "result": {"message_id": 42}}),
    )
    assert telegram.Bot("123:abc").enviar(777, "¿lleva IVA?") == 42


def test_el_token_no_aparece_en_el_texto_del_error(monkeypatch):
    """🔴 El token va en la URL. Un error que la incluya lo filtra al registro,
    que es exactamente donde no debe estar."""
    def urlopen_error(peticion, timeout=None):
        raise urllib.error.HTTPError("u", 400, "Bad Request", {}, io.BytesIO(b"{}"))

    monkeypatch.setattr(telegram.urllib.request, "urlopen", urlopen_error)
    with pytest.raises(telegram.TelegramCaido) as exc:
        telegram.Bot("123:secreto").enviar(1, "hola")
    assert "secreto" not in str(exc.value)


# ── normalizar lo que llega ───────────────────────────────────────────────────


def test_el_reply_se_extrae_explicitamente():
    """Es la pieza sobre la que descansa todo el casado; enterrada en un
    `.get().get()` se vuelve fácil de romper sin que nada lo diga."""
    update = {
        "update_id": 3,
        "message": {
            "text": "sí",
            "from": {"id": 777, "username": "ana_t", "first_name": "Ana"},
            "reply_to_message": {"message_id": 5001},
        },
    }
    partes = telegram.partes_del_mensaje(update)
    assert partes["responde_a"] == 5001
    assert partes["user_id"] == 777


@pytest.mark.parametrize(
    "update",
    [
        {"update_id": 1, "message": {"from": {"id": 7}}},          # sin texto
        {"update_id": 1, "message": {"text": "x"}},                 # sin remitente
        {"update_id": 1, "edited_message": {"text": "x"}},          # no es un mensaje
        {"update_id": 1},
    ],
)
def test_lo_que_no_es_un_mensaje_de_texto_se_descarta(update):
    assert telegram.partes_del_mensaje(update) is None
