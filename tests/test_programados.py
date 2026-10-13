"""Mensajes programados: un texto que entra en el panel de un slot a una hora.

🔴 Lo que se prueba aquí, sobre todo, es lo que **no** pasa. Esta es la función
del hub que más se acerca a lo que la regla dura 6 prohíbe —escribir en un panel
de tmux—, y lo que la hace admisible no es que funcione: es que se niegue en
todos los casos en que la condición de la regla 15 no se cumple, comprobada en el
instante de entregar y no al programar.

Por eso casi ningún test de aquí mira que el mensaje salga. Miran que no salga.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from hub import api, entrega, programados


def t(**delta) -> str:
    """Un instante relativo a ahora, en UTC y en el formato de la base."""
    return (datetime.now(timezone.utc) + timedelta(**delta)).isoformat(timespec="seconds")


@pytest.fixture
def slot(con):
    con.execute("INSERT INTO proyecto (id, nombre) VALUES ('demo','Demo')")
    con.execute(
        "INSERT INTO slot (id, proyecto_id, nombre, ruta, creado_en)"
        " VALUES (4,'demo','back','/tmp/demo',?)", (programados.ahora(),)
    )
    return 4


@pytest.fixture
def panel_abierto(con, slot):
    """El slot con una ventana viva, que es la precondición para entregar."""
    con.execute(
        "INSERT INTO snapshot (id, tomado_en, server_pid) VALUES (1,?,99)",
        (programados.ahora(),),
    )
    con.execute(
        """INSERT INTO panel (snapshot_id, pane_id, session, window_idx, pane_idx,
                              cwd, titulo, comando, slot_id)
           VALUES (1,'%7','work',0,0,'/tmp/demo','⠂ back','claude',4)"""
    )
    return "%7"


@pytest.fixture
def entregas(monkeypatch):
    """Sustituye la escritura real. Lo que se apunta es qué se habría escrito.

    🔴 Se parchea `entrega.entregar` y no `tmux`: así un test que reordenara las
    cosas para escribir antes de comprobar seguiría pareciendo verde, y por eso
    hay además un test que exige que la entrega pase por esa función.
    """
    escritas = []
    monkeypatch.setattr(programados.entrega, "entregar",
                        lambda pane_id, texto: escritas.append((pane_id, texto)))
    return escritas


# ── Programar ───────────────────────────────────────────────────────────────


def test_programar_guarda_la_hora_en_utc(con, slot):
    ident = programados.crear(con, slot, "empieza por los tests", "2026-09-12T09:00:00-06:00")

    fila = con.execute("SELECT * FROM mensaje_programado WHERE id=?", (ident,)).fetchone()
    assert fila["cuando"] == "2026-09-12T15:00:00+00:00"
    assert fila["estado"] == "pendiente"


def test_una_hora_sin_zona_se_rechaza_en_vez_de_suponerla(con, slot):
    """🔴 El fallo que esto evita no se ve: se entrega, pero seis horas tarde.

    La máquina va en CST (UTC−6). Si el servidor tomara «09:00» por UTC, un
    mensaje para las nueve de la mañana saldría a las tres de la tarde — y nada
    en la pantalla diría que pasó eso, porque desde dentro todo fue bien.
    """
    with pytest.raises(ValueError, match="zona horaria"):
        programados.crear(con, slot, "hola", "2026-09-12T09:00:00")


def test_no_se_programa_contra_un_slot_que_no_existe(con):
    with pytest.raises(programados.SlotDesconocido):
        programados.crear(con, 999, "hola", t(hours=1))


def test_no_se_programa_un_mensaje_vacio(con, slot):
    for vacio in ("", "   ", "\n"):
        with pytest.raises(ValueError):
            programados.crear(con, slot, vacio, t(hours=1))


def test_se_puede_programar_sobre_un_slot_cerrado(con, slot):
    """Programar algo para mañana sobre una ventana que ahora está cerrada es el
    uso normal. Exigir que esté abierta convertiría eso en un error."""
    assert programados.crear(con, slot, "mañana seguimos", t(hours=12)) > 0


# ── Entregar: lo que NO se hace ─────────────────────────────────────────────


def test_antes_de_su_hora_no_se_toca_nada(con, slot, panel_abierto, entregas):
    programados.crear(con, slot, "todavía no", t(minutes=30))

    assert programados.entregar_pendientes(con) == {}
    assert entregas == []


def test_si_el_slot_no_tiene_ventana_abierta_no_se_escribe_y_se_dice(con, slot, entregas):
    """Sin ventana no hay panel al que escribir. Queda dicho, y no se reintenta."""
    ident = programados.crear(con, slot, "hola", t(minutes=-1))

    assert programados.entregar_pendientes(con) == {"no-entregado": 1}
    assert entregas == []
    fila = con.execute("SELECT * FROM mensaje_programado WHERE id=?", (ident,)).fetchone()
    assert fila["estado"] == "no-entregado"
    assert "ninguna ventana abierta" in fila["motivo"]


def test_si_en_el_panel_ya_no_corre_claude_no_se_escribe(
    con, slot, panel_abierto, monkeypatch
):
    """🔴 El corazón de todo esto (regla dura 15).

    Entre programar y entregar pueden pasar horas, y en ese rato el usuario pudo
    salirse de `claude` a una shell. Escribir ahí es ejecutar comandos reales en
    una terminal cuyo estado no se conoce, que es exactamente lo que la regla 6
    prohíbe. La comprobación la hace `entrega` en el instante de escribir; aquí
    se comprueba que su negativa se respeta y que nadie la rodea.
    """
    escrito = []

    def intentar(pane_id, texto):
        escrito.append(pane_id)
        raise entrega.PanelNoApto("en ese panel ya no corre Claude Code")

    monkeypatch.setattr(programados.entrega, "entregar", intentar)
    ident = programados.crear(con, slot, "hola", t(minutes=-1))

    assert programados.entregar_pendientes(con) == {"no-entregado": 1}
    # Se consultó —la comprobación ocurre DENTRO de `entrega.entregar`, pegada a
    # la escritura y sin hueco— y su negativa se respetó: nada salió y el motivo
    # queda escrito para poder enseñarlo.
    assert escrito == ["%7"]
    fila = con.execute("SELECT * FROM mensaje_programado WHERE id=?", (ident,)).fetchone()
    assert fila["estado"] == "no-entregado"
    assert "ya no corre Claude Code" in fila["motivo"]


def test_NADA_se_intenta_dos_veces(con, slot, panel_abierto, monkeypatch, entregas):
    """🔴 Decisión suya: «prefiero que no se mande a que se manden 90 mensajes».

    Aunque el fallo fuera transitorio y el panel estuviera libre un segundo
    después, no se vuelve. El precio es un mensaje que no sale; lo que compra es
    que la pregunta «¿cuántas veces puede escribir esto en mi terminal?» tenga
    una sola respuesta posible, y sea «una».
    """
    fallos = [entrega.PanelNoApto("está trabajando ahora mismo")]

    def intentar(pane_id, texto):
        if fallos:
            raise fallos.pop()
        entregas.append((pane_id, texto))

    monkeypatch.setattr(programados.entrega, "entregar", intentar)
    programados.crear(con, slot, "hola", t(minutes=-1))

    assert programados.entregar_pendientes(con) == {"no-entregado": 1}
    assert programados.entregar_pendientes(con) == {}, "volvió a la cola"
    assert entregas == []


def test_un_cuelgue_a_mitad_de_escribir_tampoco_deja_que_se_repita(
    con, slot, panel_abierto, monkeypatch
):
    """🔴 Lo que convierte «un intento» en garantía y no en intención.

    Si el proceso muere entre escribir en el panel y guardar el resultado, un
    `pendiente` superviviente volvería a la cola — y ESE sí sería el duplicado
    que se quiere evitar. Por eso el mensaje sale de la cola ANTES de tocar nada.
    """
    def reventar(pane_id, texto):
        raise KeyboardInterrupt("aquí muere el proceso")

    monkeypatch.setattr(programados.entrega, "entregar", reventar)
    ident = programados.crear(con, slot, "hola", t(minutes=-1))

    with pytest.raises(KeyboardInterrupt):
        programados.entregar_pendientes(con)

    assert con.execute(
        "SELECT estado FROM mensaje_programado WHERE id=?", (ident,)
    ).fetchone()[0] == "entregando"
    assert programados.entregar_pendientes(con) == {}, "se reintentó tras el cuelgue"


def test_lo_ya_escrito_nunca_se_reintenta(con, slot, panel_abierto, monkeypatch):
    """🔴 `EscritoSinConfirmar` significa que el texto YA está en el panel.

    Reintentarlo no repetiría un mensaje: repetiría una INSTRUCCIÓN, y Claude
    haría el trabajo dos veces. Sale de la cola y lo mira una persona, que es la
    única que puede ver si salió.

    El orden de los `except` es la lógica aquí: `EscritoSinConfirmar` hereda de
    `PanelNoApto`, así que atraparla después sería devolverlo a la cola.
    """
    intentos = []

    def intentar(pane_id, texto):
        intentos.append(pane_id)
        raise entrega.EscritoSinConfirmar("se escribió pero no se pudo confirmar")

    monkeypatch.setattr(programados.entrega, "entregar", intentar)
    ident = programados.crear(con, slot, "hola", t(minutes=-1))

    programados.entregar_pendientes(con)
    programados.entregar_pendientes(con)

    assert len(intentos) == 1, "se volvió a escribir algo que ya estaba escrito"
    fila = con.execute("SELECT * FROM mensaje_programado WHERE id=?", (ident,)).fetchone()
    assert fila["estado"] == "sin-confirmar"


def test_pasado_el_plazo_caduca_en_vez_de_entregarse_tarde(con, slot, entregas):
    """«Buenos días, empieza por los tests» a las cuatro de la tarde es peor que
    nada: quien lo lee no tiene forma de saber que llega tarde."""
    ident = programados.crear(
        con, slot, "buenos días", t(minutes=-(programados.PLAZO_MINUTOS + 1)))

    assert programados.entregar_pendientes(con) == {"caducado": 1}
    assert entregas == []
    fila = con.execute("SELECT * FROM mensaje_programado WHERE id=?", (ident,)).fetchone()
    assert fila["estado"] == "caducado"
    assert "pasó el plazo" in fila["motivo"]


def test_dentro_del_plazo_si_se_intenta(con, slot, panel_abierto, entregas):
    """El plazo decide si se intenta, no si se reintenta: un mensaje con cinco
    minutos de retraso sigue siendo el mensaje que se escribió."""
    programados.crear(
        con, slot, "buenos días", t(minutes=-(programados.PLAZO_MINUTOS - 1)))
    assert programados.entregar_pendientes(con) == {"entregado": 1}
    assert len(entregas) == 1


def test_un_mensaje_cancelado_ya_no_sale(con, slot, panel_abierto, entregas):
    ident = programados.crear(con, slot, "olvídalo", t(minutes=-1))

    assert programados.cancelar(con, ident) is True
    assert programados.entregar_pendientes(con) == {}
    assert entregas == []


def test_lo_ya_entregado_no_se_puede_cancelar(con, slot, panel_abierto, entregas):
    """Cancelar algo que ya pasó por el panel reescribiría la historia: la
    pantalla diría que no pasó algo que sí pasó."""
    ident = programados.crear(con, slot, "hola", t(minutes=-1))
    programados.entregar_pendientes(con)

    assert programados.cancelar(con, ident) is False
    assert con.execute(
        "SELECT estado FROM mensaje_programado WHERE id=?", (ident,)
    ).fetchone()[0] == "entregado"


# ── Entregar: lo que sí ─────────────────────────────────────────────────────


def test_se_entrega_una_sola_vez(con, slot, panel_abierto, entregas):
    programados.crear(con, slot, "empieza por los tests", t(minutes=-1))

    assert programados.entregar_pendientes(con) == {"entregado": 1}
    assert programados.entregar_pendientes(con) == {}
    assert len(entregas) == 1


def test_va_al_panel_que_tiene_el_slot_AHORA(con, slot, panel_abierto, entregas):
    """🔴 El panel se resuelve al entregar, no al programar.

    Guardar el `pane_id` al programarlo fijaría un permiso que caduca: ocho horas
    después esa ventana puede ser la shell de otra cosa. Aquí el slot se mueve de
    panel entre una cosa y la otra, y el mensaje tiene que seguirlo.
    """
    programados.crear(con, slot, "hola", t(minutes=-1))
    con.execute("UPDATE panel SET pane_id='%99' WHERE slot_id=4")

    programados.entregar_pendientes(con)

    assert [p for p, _ in entregas] == ["%99"]


def test_llega_EXACTAMENTE_el_texto_escrito(con, slot, panel_abierto, entregas):
    """🔴 Nada añadido: ni la hora, ni una etiqueta, ni un marco. Pedido suyo —
    «espero solo el texto limpio»— y con motivo de dominio: lo que entra en el
    cuadro de un agente es una instrucción, y unos metadatos delante son
    contexto que él no escribió y que el agente tiene que interpretar."""
    programados.crear(con, slot, "sigue con el refactor", t(minutes=-1))
    programados.entregar_pendientes(con)

    assert entregas == [("%7", "sigue con el refactor")]


def test_el_texto_no_lleva_el_marco_de_lo_que_viene_de_fuera(con, slot, panel_abierto, entregas):
    """`entrega.marcar` existe para que lo que escribió OTRA persona no se
    confunda con una instrucción del dueño (regla dura 22). Esto lo escribió él,
    así que marcarlo como ajeno sería mentir en la dirección contraria."""
    programados.crear(con, slot, "sigue", t(minutes=-1))
    programados.entregar_pendientes(con)

    assert "canal de consulta" not in entregas[0][1]


def test_la_escritura_pasa_por_entrega_y_no_por_tmux_a_pelo(monkeypatch, con, slot, panel_abierto):
    """🔴 Lo que hace admisible esta función es pasar por `entrega.entregar`, que
    comprueba y escribe sin hueco entre medias. Si alguien la rodeara llamando a
    `tmux` directamente, los tests de arriba —que parchean `entrega`— seguirían
    verdes mientras el hub escribe en shells desconocidas.

    Esto lo caza: se rompe `entrega.entregar` y se exige que la entrega muera.
    """
    def prohibido(*a, **k):
        raise AssertionError("se escribió sin pasar por entrega.entregar")

    monkeypatch.setattr(programados.entrega, "entregar", prohibido)
    programados.crear(con, slot, "hola", t(minutes=-1))

    with pytest.raises(AssertionError, match="sin pasar por"):
        programados.entregar_pendientes(con)


# ── Lo que ve la pantalla ───────────────────────────────────────────────────


def test_la_lista_trae_el_nombre_del_slot(con, slot):
    programados.crear(con, slot, "hola", t(hours=1))
    assert api.programados(con)[0]["slot_nombre"] == "back"


def test_los_pendientes_salen_primero(con, slot, panel_abierto, entregas):
    programados.crear(con, slot, "ya salió", t(minutes=-1))
    programados.entregar_pendientes(con)
    programados.crear(con, slot, "aún no", t(hours=5))

    assert [m["estado"] for m in api.programados(con)] == ["pendiente", "entregado"]


def test_la_lista_se_puede_acotar_a_un_slot(con, slot):
    con.execute(
        "INSERT INTO slot (id, proyecto_id, nombre, creado_en) VALUES (5,'demo','otro',?)",
        (programados.ahora(),),
    )
    programados.crear(con, slot, "del cuatro", t(hours=1))
    programados.crear(con, 5, "del cinco", t(hours=1))

    assert [m["texto"] for m in api.programados(con, slot)] == ["del cuatro"]


def test_borrar_el_slot_se_lleva_sus_mensajes(con, slot):
    """Un mensaje programado contra un slot que ya no existe no se puede
    entregar nunca; dejarlo sería acumular cola muerta."""
    programados.crear(con, slot, "hola", t(hours=1))
    con.execute("DELETE FROM slot WHERE id=?", (slot,))

    assert api.programados(con) == []
