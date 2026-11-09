"""La cola de avisos al dueño que manda `hub-canal` por Telegram (decisión 341, C-0046).

La escriben el orquestador y el canal `telegram` del secretario; la lee y la
borra el relé. Los de caracterización fijan cómo llegaba antes de unificar la
escritura, para que unificarla no cambie lo que el dueño ve.
"""

from __future__ import annotations

import json

import pytest

from hub import orquestador as orq, rele
from hub.secretario.avisos import Aviso
from hub.secretario.avisos.telegram import CanalTelegram


class _Bot:
    def __init__(self):
        self.enviados: list[str] = []

    def enviar(self, chat_id, texto):
        self.enviados.append(texto)
        return 1


@pytest.fixture
def con_dueno(con):
    rele.canal.anotar_contacto(con, 777, "duena", "La dueña")
    rele.canal.marcar_dueno(con, 777)
    return con


def _salen(con) -> list[str]:
    bot = _Bot()
    rele.enviar_timbres(con, bot)
    return bot.enviados


def test_el_timbre_del_orquestador_llega_diciendo_orquestador(con_dueno):
    orq.timbre("Tarea t-1 terminada.")
    assert _salen(con_dueno) == ["🧭 Tarea t-1 terminada.\nMíralo en el hub → Orquestador."]


def test_el_aviso_del_secretario_por_telegram_llega_diciendo_secretario_y_recortado(con_dueno):
    CanalTelegram().mandar(Aviso("x" * 2000))
    (texto,) = _salen(con_dueno)
    assert texto.endswith("Míralo en el hub → Secretario.")
    assert texto.count("x") == 900


def test_un_timbre_sin_pantalla_de_una_version_anterior_sale_como_del_orquestador(con_dueno):
    d = orq.carpeta() / "timbres"
    d.mkdir(exist_ok=True)
    (d / "1.json").write_text(json.dumps({"texto": "viejo", "cuando": "2026-11-01T00:00:00+00:00"}))
    assert _salen(con_dueno) == ["🧭 viejo\nMíralo en el hub → Orquestador."]
    assert orq.timbres_pendientes() == []


def test_el_aviso_del_secretario_por_telegram_conserva_su_titulo(con_dueno):
    """De respaldo, un recordatorio llegaba sin decir que era un recordatorio."""
    CanalTelegram().mandar(Aviso("Llamar a Ana", titulo="⏰ Recordatorio"))
    assert _salen(con_dueno) == ["⏰ Recordatorio\nLlamar a Ana\nMíralo en el hub → Secretario."]


def test_un_timbre_a_medio_escribir_no_se_lee_ni_se_borra(con_dueno):
    """Se escribe en `.tmp` y se renombra: el relé, que lee `*.json`, no ve
    uno a medias. Antes se escribía directo en `.json` y el relé lo podía
    dar por ilegible y borrarlo: el aviso se perdía."""
    from hub import timbre
    d = timbre.carpeta()
    d.mkdir(parents=True, exist_ok=True)
    (d / "5.tmp").write_text('{"texto": "a me')
    assert _salen(con_dueno) == []
    assert (d / "5.tmp").exists()


def test_tocar_deja_el_json_entero_y_ningun_tmp():
    from hub import timbre
    ruta = timbre.tocar("hola", pantalla="Secretario", titulo="⏰ Recordatorio")
    assert timbre.leer(ruta) | {"cuando": None} == {"texto": "hola", "cuando": None, "pantalla": "Secretario",
                                                     "titulo": "⏰ Recordatorio"}
    assert list(timbre.carpeta().glob("*.tmp")) == []


@pytest.mark.parametrize("contenido", ["[1]", '"x"', "7"])
def test_un_timbre_que_no_es_un_objeto_se_descarta_y_no_deja_sordo_al_rele(con_dueno, contenido):
    """Antes daba `TypeError`, el archivo se quedaba y cada vuelta del relé
    moría en el mismo sitio, antes de leer Telegram (regla dura 2)."""
    import os
    import time

    from hub import timbre
    d = timbre.carpeta()
    d.mkdir(parents=True, exist_ok=True)
    (d / "1.json").write_text(contenido)
    viejo = time.time() - 60
    os.utime(d / "1.json", (viejo, viejo))
    assert _salen(con_dueno) == []
    assert timbre.pendientes() == []


def test_un_timbre_recien_escrito_que_aun_no_se_lee_espera_a_la_vuelta_siguiente(con_dueno):
    """C-0062: el guardián del navegante (otro repo) escribe sus timbres sin
    `.tmp`, y uno pillado a medio escribir se daba por ilegible y se borraba:
    el aviso se perdía. Arreglarlo allí es de ese proyecto (regla dura 16);
    aquí, quien lee no borra lo que acaba de aparecer."""
    from hub import timbre
    d = timbre.carpeta()
    d.mkdir(parents=True, exist_ok=True)
    (d / "2.json").write_text('{"texto": "Navegante: hace falta tu ')
    assert _salen(con_dueno) == []
    assert timbre.pendientes() == [d / "2.json"]

    (d / "2.json").write_text(json.dumps({"texto": "hace falta tu clave", "pantalla": "Navegante"}))
    assert _salen(con_dueno) == ["🧭 hace falta tu clave\nMíralo en el hub → Navegante."]
