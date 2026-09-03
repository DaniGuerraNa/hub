"""El canal de consulta: quién puede qué, y el ciclo de una pregunta.

Aquí no se prueba que Telegram funcione —eso es de `test_rele.py`, con la API
simulada—: se prueba la parte donde un fallo se convierte en **un permiso que no
debía existir**, que es la que hay que poder auditar leyendo.

El diseño y sus porqués, en `PLAN-TELEGRAM.md`.
"""

from __future__ import annotations

import pytest

from hub import canal


@pytest.fixture
def escena(con):
    con.execute("INSERT INTO proyecto (id, nombre) VALUES ('contab','Contabilidad')")
    con.execute("INSERT INTO proyecto (id, nombre) VALUES ('otro','Otro')")
    canal.anotar_contacto(con, 777, "ana_t", "Ana")
    return con


def _activa(con, user_id=777, proyecto="contab", acciones=canal.ACCIONES):
    canal.editar_usuario(con, user_id, alias="ana", estado="activo")
    for a in acciones:
        canal.conceder(con, user_id, proyecto, a)


# ── el alta ───────────────────────────────────────────────────────────────────


def test_escribir_al_bot_no_da_ningun_permiso(escena):
    """🔴 El único camino de alta que existe, y no concede nada.

    La Bot API no deja escribir a un teléfono: el bot sólo puede contestar a
    quien le habló primero. Eso invierte el alta —no eliges a quién añadir,
    apruebas a quien apareció— y por eso importa que aparecer no valga de nada.
    """
    usuario = canal.ver_usuario(escena, 777)
    assert usuario["estado"] == "pendiente"
    assert canal.permisos_de(escena, 777) == []
    assert canal.puede(escena, 777, "contab", "responder") is False


def test_volver_a_escribir_no_reabre_nada(escena):
    """Un mensaje entrante refresca cómo se le reconoce y NADA más.

    `username` y `nombre` son lo único que permite identificar a la persona al
    aprobarla, y su dueño los cambia cuando quiere. El alias, el estado y los
    permisos son del dueño del hub: si un mensaje pudiera moverlos, bloquear a
    alguien duraría hasta su siguiente mensaje.
    """
    _activa(escena)
    canal.editar_usuario(escena, 777, estado="bloqueado")

    canal.anotar_contacto(escena, 777, "otro_nombre", "Ana Cambiada")

    usuario = canal.ver_usuario(escena, 777)
    assert usuario["estado"] == "bloqueado"
    assert usuario["alias"] == "ana"
    assert usuario["username"] == "otro_nombre"   # esto sí se refresca


def test_el_alias_manda_sobre_el_username(escena):
    """El username lo cambia su dueño; el alias lo pone el dueño del hub.

    Importa porque ese nombre acaba dentro del marco de la respuesta, o sea en
    el contexto de Claude: si cambiara solo, cambiaría quién parece haber
    decidido algo.
    """
    assert canal.nombre_visible(canal.ver_usuario(escena, 777)) == "@ana_t"
    canal.editar_usuario(escena, 777, alias="Ana (contabilidad)")
    assert canal.nombre_visible(canal.ver_usuario(escena, 777)) == "Ana (contabilidad)"


# ── la matriz ─────────────────────────────────────────────────────────────────


def test_un_permiso_no_se_derrama_a_otro_proyecto(escena):
    """🔴 Sin comodines y sin permiso global.

    Con uno, añadir un proyecto nuevo se lo regalaría a quien ya tuviera acceso
    sin que nadie lo decidiera.
    """
    _activa(escena, proyecto="contab")
    assert canal.puede(escena, 777, "contab", "responder") is True
    assert canal.puede(escena, 777, "otro", "responder") is False


def test_un_permiso_no_se_derrama_a_otra_accion(escena):
    _activa(escena, acciones=["leer-estado"])
    assert canal.puede(escena, 777, "contab", "leer-estado") is True
    assert canal.puede(escena, 777, "contab", "responder") is False
    assert canal.puede(escena, 777, "contab", "recibir-preguntas") is False


def test_bloquear_basta_sin_borrar_los_permisos(escena):
    """El estado manda sobre la matriz: cortar tiene que ser una sola acción."""
    _activa(escena)
    canal.editar_usuario(escena, 777, estado="bloqueado")
    assert canal.puede(escena, 777, "contab", "responder") is False
    assert canal.permisos_de(escena, 777) != []    # siguen ahí para restaurarlo


def test_una_accion_inventada_se_rechaza(escena):
    """La lista es cerrada: si conceder algo nuevo fuera escribir otra cadena,
    el día que alguien añada `enviar-prompt` nadie se enteraría."""
    canal.editar_usuario(escena, 777, estado="activo")
    with pytest.raises(canal.CanalInvalido, match="acción"):
        canal.conceder(escena, 777, "contab", "enviar-prompt")


def test_no_se_concede_sobre_un_proyecto_que_no_existe(escena):
    canal.editar_usuario(escena, 777, estado="activo")
    with pytest.raises(canal.CanalInvalido, match="proyecto"):
        canal.conceder(escena, 777, "fantasma", "responder")


def test_denegar_deja_rastro(escena):
    """Sin registro no se puede decir después qué se intentó."""
    with pytest.raises(canal.SinPermiso):
        canal.exigir(escena, 777, "contab", "responder")
    assert any(r["direccion"] == "falla" for r in canal.registro(escena))


# ── el ciclo de la pregunta ───────────────────────────────────────────────────


def test_no_se_pregunta_a_quien_no_puede_recibir(escena):
    canal.editar_usuario(escena, 777, estado="activo")
    with pytest.raises(canal.SinPermiso):
        canal.crear_pregunta(escena, "contab", "¿lleva IVA?", user_id=777)


def test_la_pregunta_para_el_dueno_no_necesita_permiso(escena):
    """`user_id` nulo = es para él: no viaja contenido, lo lee en el hub."""
    pid = canal.crear_pregunta(escena, "contab", "¿migramos a decimal?")
    assert canal.ver_pregunta(escena, pid)["user_id"] is None


def test_solo_contesta_aquel_a_quien_se_le_pregunto(escena):
    """🔴 Dos comprobaciones, y ésta es la que se olvida.

    Sin ella, alguien con permiso en el proyecto podría contestar preguntas
    dirigidas a otro — y el marco diría un nombre que no es el que decidió.
    """
    _activa(escena)
    canal.anotar_contacto(escena, 888, "luis_t", "Luis")
    _activa(escena, user_id=888)

    pid = canal.crear_pregunta(escena, "contab", "¿lleva IVA?", user_id=777)
    with pytest.raises(canal.SinPermiso, match="no era para"):
        canal.anotar_respuesta(escena, pid, 888, "sí")

    assert canal.ver_pregunta(escena, pid)["estado"] == "pendiente"


def test_una_respuesta_se_casa_por_su_message_id(escena):
    """Es lo que permite que el relé sea central sin interpretar nada."""
    _activa(escena)
    pid = canal.crear_pregunta(escena, "contab", "¿lleva IVA?", user_id=777)
    canal.marcar_enviada(escena, pid, 5001)

    assert canal.por_message_id(escena, 5001)["id"] == pid
    assert canal.por_message_id(escena, 9999) is None


def test_la_respuesta_queda_registrada_integra(escena):
    """El registro guarda el cuerpo: lo que sale de aquí sale de la máquina."""
    _activa(escena)
    pid = canal.crear_pregunta(escena, "contab", "¿lleva IVA?", user_id=777)
    canal.anotar_respuesta(escena, pid, 777, "  ya lo lleva  ")

    assert canal.ver_pregunta(escena, pid)["respuesta"] == "ya lo lleva"
    entradas = [r for r in canal.registro(escena) if r["direccion"] == "entra"]
    assert any("ya lo lleva" == r["cuerpo"] for r in entradas)


def test_un_fallo_de_entrega_no_consume_la_respuesta(escena):
    """🔴 Si el panel ya no tiene un Claude, la respuesta NO se pierde.

    Se queda en `respondida` para poder reintentarla cuando el panel vuelva. Si
    se marcara entregada, alguien habría contestado y su respuesta no habría
    llegado a ninguna parte sin que nada lo dijera.
    """
    _activa(escena)
    pid = canal.crear_pregunta(escena, "contab", "¿lleva IVA?", user_id=777)
    canal.anotar_respuesta(escena, pid, 777, "sí")
    canal.marcar_fallo_de_entrega(escena, pid, "en ese panel ya no corre Claude Code")

    pregunta = canal.ver_pregunta(escena, pid)
    assert pregunta["estado"] == "respondida"
    assert "ya no corre Claude" in pregunta["detalle"]


def test_solo_vence_lo_que_traia_plazo(escena):
    """El plazo lo fija el pacto. Sin `vence_en`, el hub no inventa ninguno."""
    _activa(escena)
    con_plazo = canal.crear_pregunta(
        escena, "contab", "urge", user_id=777, vence_en="2026-01-01T00:00:00+00:00"
    )
    sin_plazo = canal.crear_pregunta(escena, "contab", "cuando puedas", user_id=777)
    canal.marcar_enviada(escena, con_plazo, 1)
    canal.marcar_enviada(escena, sin_plazo, 2)

    vencidas = canal.vencidas(escena, "2026-06-01T00:00:00+00:00")
    assert [v["id"] for v in vencidas] == [con_plazo]


def test_una_pregunta_vacia_no_se_manda(escena):
    _activa(escena)
    with pytest.raises(canal.CanalInvalido):
        canal.crear_pregunta(escena, "contab", "   ", user_id=777)


def test_destinatarios_solo_lista_a_quien_puede_hoy(escena):
    canal.anotar_contacto(escena, 888, "luis_t", "Luis")
    _activa(escena, user_id=777, acciones=["recibir-preguntas"])
    _activa(escena, user_id=888, acciones=["responder"])   # puede contestar, no recibir

    assert [u["user_id"] for u in canal.destinatarios(escena, "contab")] == [777]
