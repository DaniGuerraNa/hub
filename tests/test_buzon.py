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


def test_el_mismo_mensaje_reentregado_tras_un_reinicio_se_aparca_una_sola_vez(con, encargo):
    """El relé guarda y muere antes del siguiente getUpdates: Telegram lo da
    otra vez, y entraría dos veces al panel del agente (C-0184)."""
    primero = buzon.aparcar(con, encargo, 77, "fío a los vecinos", message_id=9)
    otra_vez = buzon.aparcar(con, encargo, 77, "fío a los vecinos", message_id=9)

    assert otra_vez == primero
    assert [m["texto"] for m in buzon.en_cola(con, encargo)] == ["fío a los vecinos"]


def test_ya_entregado_tampoco_vuelve_a_la_cola_si_llega_repetido(con, encargo):
    """Lo que cuenta es haberlo recibido, no que siga en cola: si ya salió al
    panel, repetirlo sería repetirle la instrucción al agente."""
    buzon.aparcar(con, encargo, 77, "fío a los vecinos", message_id=9)
    con.execute("UPDATE encargo_mensaje SET estado = 'entregado'")

    buzon.aparcar(con, encargo, 77, "fío a los vecinos", message_id=9)

    assert buzon.en_cola(con, encargo) == []


def test_un_audio_repetido_tampoco_se_aparca_dos_veces(con, encargo):
    buzon.aparcar(con, encargo, 77, "", clase="audio", adjunto="tg:abc", message_id=12)
    buzon.aparcar(con, encargo, 77, "", clase="audio", adjunto="tg:abc", message_id=12)

    assert len(buzon.sin_transcribir(con)) == 1


def test_el_mismo_numero_de_mensaje_de_otra_persona_no_es_un_repetido(con, encargo):
    """🔴 El `message_id` de Telegram cuenta por conversación y el del chat web
    es del servidor del chat (decisión 246): el 9 de Rosa en Telegram y el 9 de
    alguien del chat web son mensajes distintos. Lo que los separa es quién
    lo mandó, que en el chat web nace en otro rango de ids."""
    encargos.anotar_persona(con, 900_000_001, "lupe", "Lupe")
    encargos.editar_persona(con, 900_000_001, estado="activo", canal="web")
    encargos.crear(con, "fonda-lupe", 900_000_001, "Fonda de Lupe")

    buzon.aparcar(con, encargo, 77, "de Telegram", message_id=9)
    buzon.aparcar(con, "fonda-lupe", 900_000_001, "del chat web", message_id=9)

    assert [m["texto"] for m in buzon.en_cola(con, encargo)] == ["de Telegram"]
    assert [m["texto"] for m in buzon.en_cola(con, "fonda-lupe")] == ["del chat web"]


def test_el_mismo_numero_pasado_un_dia_ya_es_otro_mensaje(con, encargo):
    """C-0186: si se rehace la base del servidor del chat web, sus números de
    mensaje reempiezan, y un filtro sin fecha se tragaba lo nuevo por llevar
    el número de algo viejo. Telegram no guarda un update sin confirmar más de
    un día: pasado eso, el mismo número no puede ser una reentrega."""
    viejo = buzon.aparcar(con, encargo, 77, "lo de anteayer", message_id=5)
    con.execute("UPDATE encargo_mensaje SET recibido_en = ? WHERE id = ?", (t(hours=-25), viejo))

    assert not buzon.ya_recibido(con, 77, 5)
    nuevo = buzon.aparcar(con, encargo, 77, "lo de hoy", message_id=5)

    assert nuevo != viejo
    assert [m["texto"] for m in buzon.en_cola(con, encargo)] == ["lo de anteayer", "lo de hoy"]


def test_ya_recibido_ve_lo_aparcado_y_lo_apuntado_sin_alta(con, encargo):
    """La puerta del relé mira los dos sitios donde se guarda lo que entra: la
    cola, y el registro para quien todavía no tenía alta (C-0186)."""
    buzon.aparcar(con, encargo, 77, "fío a los vecinos", message_id=9)
    encargos.anotar_persona(con, 99, "nueva", "Nueva")
    encargos.registrar(con, "falla", encargos.marca_sin_alta(31), user_id=99, cuerpo="hola")

    assert buzon.ya_recibido(con, 77, 9)
    assert buzon.ya_recibido(con, 99, 31)
    assert not buzon.ya_recibido(con, 99, 9)
    assert not buzon.ya_recibido(con, 77, 31)
    assert not buzon.ya_recibido(con, 77, None)


def test_una_fecha_sin_zona_en_el_registro_no_rompe_la_puerta(con, encargo):
    """Comparar una fecha sin zona con una con zona lanza, y la puerta corre en
    mitad de tratar un mensaje: tres intentos y el relé lo saltaba."""
    encargos.registrar(con, "falla", encargos.marca_sin_alta(31), user_id=99, cuerpo="hola")
    sin_zona = datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds")
    con.execute("UPDATE encargo_registro SET momento = ?", (sin_zona,))

    assert buzon.ya_recibido(con, 99, 31)
    assert encargos.escrito_sin_alta(con, 99, buzon.VENTANA_REENTREGA) == ["hola"]


def test_lo_que_no_trae_numero_de_mensaje_se_aparca_siempre(con, encargo):
    """Un botón pulsado o lo que aparca el entrevistador no tienen `message_id`:
    sin él no hay forma de saber si es el mismo, y perder uno es peor."""
    buzon.aparcar(con, encargo, 77, "sí")
    buzon.aparcar(con, encargo, 77, "sí")

    assert len(buzon.en_cola(con, encargo)) == 2


def test_lo_que_sale_con_ese_numero_no_cuenta_como_recibido(con, encargo):
    """En el chat web un id de mensaje es único entre las dos direcciones, pero
    la fila de lo que sale lleva el id que le dio el canal: que nunca tape lo
    que entra."""
    saliente = buzon.encolar_salida(con, encargo, "¿a qué hora abres?", user_id=77)
    buzon.marcar_enviado(con, saliente, 9)

    buzon.aparcar(con, encargo, 77, "a las siete", message_id=9)

    assert [m["texto"] for m in buzon.en_cola(con, encargo)] == ["a las siete"]


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


# ── Las puertas de la cola (C-0137) ─────────────────────────────────────────


def _fila(con, mensaje_id: int) -> dict:
    return dict(con.execute("SELECT * FROM encargo_mensaje WHERE id = ?", (mensaje_id,)).fetchone())


def test_lo_que_sale_se_marca_enviado_y_su_secreto_se_tapa_en_el_mismo_paso(con, encargo):
    """El tapado iba aparte, una línea debajo del UPDATE en el relé: quien
    marcara enviado sin él dejaba la contraseña en la fila (regla 22, C-0127).
    Ahora va en la misma sentencia que el estado (C-0186)."""
    i = buzon.encolar_salida(con, encargo, f"tu clave es {buzon.secreto('Zq9-77')}", con_secreto=True)
    buzon.anotar_detalle(con, i, "no salió: red")

    buzon.marcar_enviado(con, i, 555)

    fila = _fila(con, i)
    assert (fila["estado"], fila["message_id"], fila["detalle"]) == ("enviado", 555, "")
    assert fila["movido_en"] and "Zq9-77" not in fila["texto"] and buzon.TAPADO in fila["texto"]


def test_lo_retirado_queda_a_la_vista_como_retirado_y_con_su_secreto_tapado(con, encargo):
    uno = buzon.encolar_salida(con, encargo, "uno")
    dos = buzon.encolar_salida(con, encargo, f"clave {buzon.secreto('s3creta')}", con_secreto=True)

    buzon.retirar(con, [uno, dos])

    for i in (uno, dos):
        fila = _fila(con, i)
        assert fila["estado"] == "descartado" and "retirado" in fila["detalle"] and fila["movido_en"]
    assert "s3creta" not in _fila(con, dos)["texto"]
    assert buzon.salientes(con) == []


class _MuereTrasLaPrimeraEscritura:
    """La conexión de un proceso que muere tras su primera escritura: lo que
    `kill -9` o un apagón hacen entre dos sentencias en autocommit."""

    def __init__(self, con):
        self._con, self.escrituras = con, 0

    def _escribe(self):
        if self.escrituras:
            raise SystemExit("el proceso muere aquí")
        self.escrituras += 1

    def execute(self, sql, *args):
        if sql.lstrip().split(None, 1)[0].upper() in ("UPDATE", "INSERT", "DELETE"):
            self._escribe()
        return self._con.execute(sql, *args)

    def executemany(self, sql, *args):
        self._escribe()
        return self._con.executemany(sql, *args)

    def __getattr__(self, nombre):
        return getattr(self._con, nombre)


def _con_la_clave_en_claro(con, estado):
    return con.execute("SELECT COUNT(*) FROM encargo_mensaje WHERE estado = ? AND texto LIKE '%Zq9-77%'",
                       (estado,)).fetchone()[0]


def test_morir_al_marcar_enviado_no_deja_la_clave_en_claro_en_lo_enviado(con, encargo):
    """C-0186: eran dos UPDATE sueltos en autocommit —el estado y después el
    tapado—, y un proceso que muriera entre los dos dejaba «enviado» con la
    contraseña en la fila y en las copias diarias (regla 22, C-0127)."""
    i = buzon.encolar_salida(con, encargo, f"tu clave es {buzon.secreto('Zq9-77')}", con_secreto=True)

    try:
        buzon.marcar_enviado(_MuereTrasLaPrimeraEscritura(con), i, 555)
    except SystemExit:
        pass

    assert _con_la_clave_en_claro(con, "enviado") == 0


def test_morir_al_retirar_no_deja_la_clave_en_claro_en_lo_retirado(con, encargo):
    i = buzon.encolar_salida(con, encargo, f"tu clave es {buzon.secreto('Zq9-77')}", con_secreto=True)

    try:
        buzon.retirar(_MuereTrasLaPrimeraEscritura(con), [i])
    except SystemExit:
        pass

    assert _con_la_clave_en_claro(con, "descartado") == 0


def test_lo_que_ya_salio_no_se_retira_aunque_se_pida(con, encargo):
    """C-0186: `encargo deshacer` lee la cola y retira; si entre las dos cosas
    el relé lo mandó, lo marcaba «retirado antes de salir» sobre algo que ya
    había llegado. Retirar sólo saca de la cola, y dice qué sacó."""
    uno = buzon.encolar_salida(con, encargo, "uno")
    dos = buzon.encolar_salida(con, encargo, "dos")
    buzon.marcar_enviado(con, uno, 555)

    assert buzon.retirar(con, [uno, dos]) == [dos]
    assert _fila(con, uno)["estado"] == "enviado"
    assert _fila(con, dos)["estado"] == "descartado"


def test_lo_retirado_mientras_salia_sigue_retirado_y_dice_que_llego(con, encargo):
    """C-0186: si se retira en el instante en que el relé lo está mandando, ya
    no se puede deshacer. `marcar_enviado` sólo pasa de la cola a enviado: no
    pisa el «descartado», pero la fila deja de decir que no salió."""
    i = buzon.encolar_salida(con, encargo, "esto mejor no")
    assert buzon.sigue_en_cola(con, i)
    buzon.retirar(con, [i])
    assert not buzon.sigue_en_cola(con, i)

    assert buzon.marcar_enviado(con, i, 556) is False

    fila = _fila(con, i)
    assert fila["estado"] == "descartado" and fila["message_id"] == 556
    assert "le llegó igual" in fila["detalle"]


def test_el_motivo_y_el_adjunto_se_apuntan_por_la_cola(con, encargo):
    i = buzon.aparcar(con, encargo, 77, "", clase="audio", adjunto="telegram:abc")
    buzon.anotar_detalle(con, i, "no se pudo bajar el audio: red")
    assert _fila(con, i)["detalle"] == "no se pudo bajar el audio: red"

    buzon.apuntar_adjunto(con, i, "/tmp/a.webm")
    fila = _fila(con, i)
    assert (fila["adjunto"], fila["detalle"], fila["estado"]) == ("/tmp/a.webm", "", buzon.SIN_TRANSCRIBIR)
