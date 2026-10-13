"""La cola de un encargo: que no se pierda nada mientras el agente no puede oír.

🔴 Lo que se prueba aquí es la promesa que sostiene la función entera: *«que los
mensajes durante ese tiempo no se pierdan»*. Un compact de Claude Code tarda dos
o tres minutos, y quien manda audios manda tres seguidos: si el mensaje se
apartara hasta que el panel estuviera listo, o se escribiera a la fuerza en una
TUI ocupada, se perdería exactamente en el momento en que más cuesta darse
cuenta — porque desde fuera todo parece normal.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from hub import buzon, encargos, entrega


def t(**delta) -> str:
    return (datetime.now(timezone.utc) + timedelta(**delta)).isoformat(timespec="seconds")


@pytest.fixture
def encargo(con):
    con.execute("INSERT INTO proyecto (id, nombre) VALUES ('demo','Demo')")
    con.execute(
        "INSERT INTO slot (id, proyecto_id, nombre, ruta, creado_en)"
        " VALUES (4,'demo','encargo','/tmp/demo',?)", (encargos.ahora(),)
    )
    encargos.anotar_persona(con, 77, "rosa", "Rosa")
    encargos.editar_persona(con, 77, estado="activo", alias="Rosa")
    encargos.crear(con, "abarrotes-rosa", 77, "Abarrotes de Rosa")
    return "abarrotes-rosa"


@pytest.fixture
def con_agente(con, encargo):
    """El encargo con su agente abierto en un panel vivo."""
    encargos.tocar(con, encargo, slot_id=4)
    con.execute("INSERT INTO snapshot (id, tomado_en, server_pid) VALUES (1,?,99)",
                (encargos.ahora(),))
    con.execute(
        """INSERT INTO panel (snapshot_id, pane_id, session, window_idx, pane_idx,
                              cwd, titulo, comando, slot_id)
           VALUES (1,'%7','work',0,0,'/tmp/demo','⠂ encargo','claude',4)"""
    )
    return encargo


@pytest.fixture
def entregas(monkeypatch):
    escritas = []
    monkeypatch.setattr(buzon.entrega, "entregar",
                        lambda pane_id, texto: escritas.append((pane_id, texto)))
    return escritas


# ── Aparcar ─────────────────────────────────────────────────────────────────


def test_lo_que_llega_se_guarda_antes_de_mirar_si_hay_alguien_escuchando(con, encargo):
    """Sin slot, sin panel y sin tmux: el mensaje se guarda igual."""
    buzon.aparcar(con, encargo, 77, "vendo abarrotes y fío a los vecinos")

    cola = buzon.en_cola(con, encargo)
    assert [m["texto"] for m in cola] == ["vendo abarrotes y fío a los vecinos"]
    assert cola[0]["estado"] == "en-cola"


def test_un_panel_que_no_existe_deja_el_mensaje_en_cola_y_dice_por_que(con, encargo):
    buzon.aparcar(con, encargo, 77, "hola")

    resultado = buzon.drenar(con, encargo)

    assert resultado["resultado"] == "sin-panel"
    assert buzon.en_cola(con, encargo)[0]["estado"] == "en-cola"
    assert "agente" in buzon.en_cola(con, encargo)[0]["detalle"]


def test_el_slot_cerrado_tampoco_pierde_nada(con, encargo):
    encargos.tocar(con, encargo, slot_id=4)      # el slot existe, tmux no lo tiene

    buzon.aparcar(con, encargo, 77, "hola")
    assert buzon.drenar(con, encargo)["resultado"] == "sin-panel"
    assert len(buzon.en_cola(con, encargo)) == 1


# ── Entregar en lote ────────────────────────────────────────────────────────


def test_cuatro_audios_seguidos_entran_en_UN_solo_turno(con, con_agente, entregas):
    """🔴 El motivo es medido: 148k tokens por llamada, y un turno relee todo.

    Cuatro entregas sueltas son cuatro despertares del agente. Es la misma
    razón por la que existen los lotes del canal de consulta, y aquí pesa más
    porque quien describe su negocio hablando manda los audios de tres en tres.
    """
    for texto in ("abro a las siete", "fío a los vecinos", "apunto en una libreta",
                  "los sábados vendo el doble"):
        buzon.aparcar(con, con_agente, 77, texto, clase="audio")

    resultado = buzon.drenar(con, con_agente)

    assert resultado["resultado"] == "entregado" and resultado["cuantos"] == 4
    assert len(entregas) == 1
    pane_id, texto = entregas[0]
    assert pane_id == "%7"
    for trozo in ("abro a las siete", "los sábados vendo el doble"):
        assert trozo in texto


def test_todo_lo_entregado_lleva_el_mismo_lote(con, con_agente, entregas):
    for texto in ("uno", "dos"):
        buzon.aparcar(con, con_agente, 77, texto)
    buzon.drenar(con, con_agente)

    lotes = {m["lote"] for m in buzon.conversacion(con, con_agente)}
    assert len(lotes) == 1 and lotes != {None}


def test_lo_entregado_sale_de_la_cola_y_no_vuelve_a_entrar(con, con_agente, entregas):
    buzon.aparcar(con, con_agente, 77, "hola")
    buzon.drenar(con, con_agente)

    assert buzon.en_cola(con, con_agente) == []
    assert buzon.drenar(con, con_agente)["resultado"] == "nada"
    assert len(entregas) == 1


def test_un_audio_se_marca_como_transcripcion_y_no_como_algo_que_dijo(con, con_agente, entregas):
    """🔴 Lo que hay ahí es lo que whisper OYÓ, y puede estar mal.

    Sin la distinción, un error de transcripción se lee como un requisito raro
    del negocio, y el agente lo construye. Importa justo aquí porque este canal
    existe para que el negocio se describa hablando.
    """
    buzon.aparcar(con, con_agente, 77, "vendo chicharrón", clase="audio")
    buzon.drenar(con, con_agente)

    _, texto = entregas[0]
    assert "transcrito" in texto and "errores" in texto


def test_el_marco_dice_de_quien_es_el_texto(con, con_agente, entregas):
    """Regla dura 22: lo escribió alguien en un móvil, no es una instrucción."""
    buzon.aparcar(con, con_agente, 77, "que sea bonito")
    buzon.drenar(con, con_agente)

    _, texto = entregas[0]
    assert "Rosa" in texto and "canal de encargos" in texto


# ── Los dos fallos, que no son el mismo fallo ───────────────────────────────


def test_un_panel_ocupado_deja_el_mensaje_en_cola_para_reintentarlo(con, con_agente, monkeypatch):
    """Compactando, el panel no acepta nada. No se escribe y no se pierde."""
    monkeypatch.setattr(buzon.entrega, "entregar", _no_apto("está trabajando ahora mismo"))

    buzon.aparcar(con, con_agente, 77, "hola")
    resultado = buzon.drenar(con, con_agente)

    assert resultado["resultado"] == "no-apto"
    assert buzon.en_cola(con, con_agente)[0]["estado"] == "en-cola"
    assert "trabajando" in buzon.en_cola(con, con_agente)[0]["detalle"]


def test_lo_escrito_sin_confirmar_NO_vuelve_a_la_cola(con, con_agente, monkeypatch):
    """🔴 El texto ya está en el panel: reintentarlo lo entregaría dos veces.

    Y en el panel de un agente un duplicado no es un mensaje repetido, es una
    instrucción repetida. Sale de la cola y se enseña para que lo mire alguien.
    """
    monkeypatch.setattr(buzon.entrega, "entregar", _sin_confirmar())

    buzon.aparcar(con, con_agente, 77, "hola")
    resultado = buzon.drenar(con, con_agente)

    assert resultado["resultado"] == "sin-confirmar"
    assert buzon.en_cola(con, con_agente) == []
    assert buzon.conversacion(con, con_agente)[0]["estado"] == "sin-confirmar"


def test_el_orden_de_los_except_no_manda_lo_escrito_de_vuelta_a_la_cola(con, con_agente, monkeypatch):
    """`EscritoSinConfirmar` hereda de `PanelNoApto`: atraparla después la pierde.

    Es la misma trampa del `HTTPError` sobre `URLError` que ya mordió en el CLI,
    y aquí el precio es que el agente reciba lo mismo dos veces.
    """
    monkeypatch.setattr(buzon.entrega, "entregar", _sin_confirmar())
    buzon.aparcar(con, con_agente, 77, "hola")
    buzon.drenar(con, con_agente)

    assert buzon.drenar(con, con_agente)["resultado"] == "nada"


def test_un_fallo_de_panel_no_toca_los_mensajes_de_otro_encargo(con, con_agente, monkeypatch):
    encargos.anotar_persona(con, 88, "luis", "Luis")
    encargos.crear(con, "escuela-luis", 88)
    monkeypatch.setattr(buzon.entrega, "entregar", _no_apto("está trabajando"))

    buzon.aparcar(con, con_agente, 77, "hola")
    buzon.aparcar(con, "escuela-luis", 88, "buenas")
    buzon.drenar_todos(con)

    assert len(buzon.en_cola(con, "escuela-luis")) == 1


# ── Que no parezca que nadie escucha ────────────────────────────────────────


def test_una_espera_corta_no_dice_nada(con, encargo):
    """Por debajo del umbral, callarse. Un bot que se narra acaba silenciado."""
    buzon.aparcar(con, encargo, 77, "hola")

    assert buzon.toca_avisar_de_la_espera(con, encargo) is False


def test_pasado_el_umbral_se_avisa_una_sola_vez(con, encargo):
    buzon.aparcar(con, encargo, 77, "hola")
    con.execute("UPDATE encargo_mensaje SET recibido_en = ?", (t(minutes=-5),))

    assert buzon.toca_avisar_de_la_espera(con, encargo) is True
    buzon.anotar_aviso_de_espera(con, encargo)
    assert buzon.toca_avisar_de_la_espera(con, encargo) is False


def test_sin_nada_sin_contestar_no_se_avisa_de_ninguna_espera(con, encargo):
    assert buzon.toca_avisar_de_la_espera(con, encargo) is False


def test_la_espera_es_lo_que_dijo_sin_que_el_agente_le_contestara(con, encargo):
    """🔴 Decisión 235: entregar al agente no es contestarle. La segunda persona
    real mandó «Hola?» en el minuto en que su mensaje ya estaba en el panel y el
    agente pensaba: no había cola, así que no había señal ninguna."""
    buzon.aparcar(con, encargo, 77, "el último, se ve bonito")
    con.execute("UPDATE encargo_mensaje SET estado = 'entregado'")
    assert [m["texto"] for m in buzon.sin_contestar(con, encargo)] == ["el último, se ve bonito"]

    # lo que sale hacia el DUEÑO no le contesta a ella
    buzon.encolar_salida(con, encargo, "el plan", clase="plan", user_id=1)
    con.execute("UPDATE encargo_mensaje SET estado = 'enviado' WHERE direccion = 'sale'")
    assert len(buzon.sin_contestar(con, encargo)) == 1

    buzon.encolar_salida(con, encargo, "Vas con GiraYGana…")
    con.execute("UPDATE encargo_mensaje SET estado = 'enviado' WHERE direccion = 'sale'")
    assert buzon.sin_contestar(con, encargo) == []


def test_una_espera_muy_vieja_deja_de_merecer_el_escribiendo(con, encargo):
    """Un «ok gracias» sin respuesta no puede dejar al bot tecleando para siempre."""
    buzon.aparcar(con, encargo, 77, "ok gracias")
    con.execute("UPDATE encargo_mensaje SET recibido_en = ?", (t(minutes=-6),))
    assert buzon.sin_contestar(con, encargo) and buzon.espera_viva(con, encargo) == []


# ── Lo que sale ─────────────────────────────────────────────────────────────


def test_el_agente_encola_y_no_manda(con, encargo):
    """🔴 Quien escribe esto corre en un panel y no tiene el token (regla 22)."""
    buzon.encolar_salida(con, encargo, "¿cómo es un día normal en tu tienda?")

    pendientes = buzon.salientes(con)
    assert len(pendientes) == 1
    assert pendientes[0]["direccion"] == "sale"
    assert pendientes[0]["estado"] == "en-cola"


def test_lo_que_sale_no_se_confunde_con_lo_que_entra(con, con_agente, entregas):
    buzon.encolar_salida(con, con_agente, "¿cómo es un día normal?")
    buzon.aparcar(con, con_agente, 77, "abro a las siete")

    assert buzon.drenar(con, con_agente)["cuantos"] == 1
    _, texto = entregas[0]
    assert "día normal" not in texto


def test_la_conversacion_se_lee_en_orden_y_con_las_dos_direcciones(con, encargo):
    buzon.encolar_salida(con, encargo, "¿cómo es un día normal?")
    buzon.aparcar(con, encargo, 77, "abro a las siete")

    assert [m["direccion"] for m in buzon.conversacion(con, encargo)] == ["sale", "entra"]


def _no_apto(motivo: str):
    def _entregar(pane_id: str, texto: str) -> None:
        raise entrega.PanelNoApto(motivo)
    return _entregar


def _sin_confirmar():
    def _entregar(pane_id: str, texto: str) -> None:
        raise entrega.EscritoSinConfirmar("se escribió pero no se pudo confirmar")
    return _entregar


def test_a_partir_de_la_segunda_ronda_la_url_no_llega_como_primer_borrador(con):
    """Ya lo vio y pidió un cambio: decirle otra vez «primer borrador» se lee
    como que no se enteraron. Visto en el recorrido completo del 19-sep."""
    encargos.crear(con, "encargo-1", 7, "x")
    buzon.anunciar_publicacion(con, "encargo-1", "https://x.test")
    primero = buzon.salientes(con)[-1]["texto"] if not encargos.dueno(con) else buzon.salientes(con)[0]["texto"]
    assert "primer borrador" in primero
    encargos.tocar(con, "encargo-1", ronda=2)
    buzon.anunciar_publicacion(con, "encargo-1", "https://x.test")
    ultimo = [m for m in buzon.salientes(con) if m["user_id"] is None][-1]["texto"]
    assert "lo que pediste" in ultimo and "primer borrador" not in ultimo
