"""El botón de pánico: quién puede pulsarlo, y qué se afirma después.

Lo que se protege aquí es la línea del módulo: **la lista es cerrada y sólo el
dueño**. Un ejecutor por Telegram que acepte cualquier cosa, o que acepte a
cualquiera, convierte la puerta entera del acceso remoto en la seguridad de una
cuenta de Telegram.

Y lo segundo: que «reiniciado» signifique que el hub contesta, no que
`systemctl` devolvió 0 — la trampa de la decisión 151, que aquí la pagaría
alguien que está lejos y se queda tranquilo con un hub muerto.
"""

from __future__ import annotations

import pytest

from hub import canal, panico, rele, telegram


class BotFalso:
    def __init__(self):
        self.enviados: list[tuple[int, str]] = []

    def enviar(self, user_id, texto, **kwargs):
        self.enviados.append((int(user_id), texto))
        return 1


@pytest.fixture
def escena(con):
    con.execute("INSERT INTO proyecto (id, nombre) VALUES ('contab','Contabilidad')")
    canal.anotar_contacto(con, 777, "duena_t", "La dueña")
    canal.editar_usuario(con, 777, alias="duena", estado="activo")
    canal.marcar_dueno(con, 777)
    canal.anotar_contacto(con, 888, "ana_t", "Ana")
    canal.editar_usuario(con, 888, alias="ana", estado="activo")
    return con


def _mensaje(user_id: int, texto: str) -> dict:
    return {"user_id": user_id, "username": "x", "nombre": "X", "texto": texto,
            "responde_a": None, "message_id": 5}


@pytest.mark.parametrize("texto", ["panico", "Pánico", " /panico ", "/PÁNICO"])
def test_el_dueno_lo_pulsa_escriba_como_escriba(escena, texto):
    assert rele.procesar_mensaje(escena, _mensaje(777, texto)) == "panico"


@pytest.mark.parametrize("texto", ["no me entra el panico", "panico!", "reinicia el hub"])
def test_una_frase_que_lo_contiene_no_es_el_boton(escena, texto):
    """🔴 Reiniciar el hub en mitad de una sesión de trabajo por una palabra
    suelta dentro de una frase sería peor que no tener botón."""
    assert rele.procesar_mensaje(escena, _mensaje(777, texto)) != "panico"


def test_otra_persona_activa_no_puede_reiniciar_la_maquina_de_casa(escena):
    """Tiene permisos del canal y aun así no: esto no es una acción del canal."""
    for accion in canal.ACCIONES:
        canal.conceder(escena, 888, "contab", accion)

    assert rele.procesar_mensaje(escena, _mensaje(888, "panico")) == "panico-denegado"
    assert any(
        "sin ser el dueño" in r["detalle"] for r in canal.registro(escena, 10)
    )


def test_se_avisa_antes_y_se_afirma_solo_si_el_hub_contesta(escena, monkeypatch):
    """Dos mensajes: «dame unos segundos» y el resultado. El silencio, a 2 000
    km y con el hub caído, se lee como que esto tampoco funcionó."""
    monkeypatch.setattr(panico, "reiniciar", lambda: (True, "Hub reiniciado y contestando en 0.4 s"))
    bot = BotFalso()

    assert rele.atender_panico(escena, bot, 777) is True
    assert len(bot.enviados) == 2
    assert "segundos" in bot.enviados[0][1]
    assert bot.enviados[1][1].startswith("✅")


def test_si_el_hub_no_vuelve_se_dice_que_no_volvio(escena, monkeypatch):
    """La peor salida posible sería un ✅ sobre un hub muerto."""
    monkeypatch.setattr(panico, "reiniciar", lambda: (False, "reinicié hub-web pero el hub no contesta"))
    bot = BotFalso()

    assert rele.atender_panico(escena, bot, 777) is False
    assert bot.enviados[-1][1].startswith("🔴")
    assert any("botón de pánico" in r["detalle"] for r in canal.registro(escena, 10))


def test_telegram_caido_no_se_lleva_por_delante_el_reinicio(escena, monkeypatch):
    """El reinicio es lo que importa; el acuse es un extra que puede fallar."""
    monkeypatch.setattr(panico, "reiniciar", lambda: (True, "listo"))

    class BotRoto(BotFalso):
        def enviar(self, *a, **k):
            raise telegram.TelegramCaido("502")

    assert rele.atender_panico(escena, BotRoto(), 777) is True


def test_el_relevo_no_se_reinicia_a_si_mismo(escena):
    """🔴 `hub-canal` lee el mensaje y contesta: reiniciarlo sería colgar la
    llamada en mitad de la frase, y systemd ya lo levanta solo."""
    assert "hub-canal" not in panico.SERVICIOS
    assert "hub-web" in panico.SERVICIOS
