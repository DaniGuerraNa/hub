"""La ficha de un encargo: qué se sabe, qué falta y cuándo se deja de preguntar.

Todo lo de aquí es puro: ni Telegram, ni audio, ni agentes. Es a propósito —la
ficha es el estado de la entrevista, y que se pueda probar entera sin nada
alrededor es lo mismo que hace que compactar el agente sea inofensivo.
"""

from __future__ import annotations

import pytest

from hub import encargos


@pytest.fixture
def ficha():
    return encargos.Ficha("tienda-de-abarrotes")


# ── el orden lo pone el agente, no quien habla ────────────────────────────────


def test_lo_que_dice_fuera_de_turno_cae_en_su_casilla(ficha):
    """🔴 El matiz suyo, y el que más cambia el diseño: «el usuario final va a
    decir las cosas como se le vengan a la mente».

    Las fases son el orden del agente. Si ella contesta la tercera mientras se
    le preguntaba la primera, eso no es ruido: es la tercera contestada.
    """
    assert ficha.siguiente().id == "dia"
    ficha.responde("estilo", "e4")

    assert ficha.contestada("estilo")
    assert ficha.siguiente().id == "dia"   # se sigue por donde iba


def test_un_audio_que_cubre_todas_las_fases_termina_la_entrevista(ficha):
    """Y el premio del matiz: no es sólo tolerar el desorden, es acabar antes.

    Quien cuenta su día entero y de paso dice qué le duele ya no tiene que
    contestar nada más. Preguntárselo igual es la forma más rápida de que deje
    de contestar.
    """
    ficha.responde("dia", "abro a las siete, acomodo, y apunto los fiados a mano")
    ficha.responde("duele", "los fiados, se me olvida quién debe")
    ficha.responde("como_hoy", "en una libreta")
    ficha.responde("datos", "quién y cuánto")
    ficha.responde("nombre", "La Esquina")
    ficha.responde("alcance", "dale, mándalo")
    ficha.responde("estilo", "e2")

    assert ficha.siguiente() is None
    assert ficha.suficiente()


def test_preguntar_no_es_haber_contestado(ficha):
    """Se cuentan las preguntas, no las respuestas: el tope se apoya en eso."""
    ficha.preguntar("dia")
    assert not ficha.contestada("dia")
    assert ficha.siguiente().id == "dia"


# ── cuándo se para ────────────────────────────────────────────────────────────


def test_tras_el_tope_el_hueco_se_declara_y_se_sigue(ficha):
    """🔴 Quien no sabe algo no lo sabrá a la quinta pregunta.

    Insistir es cómo se abandona un chat, y sin tope el coste de la entrevista
    no tiene techo — que es justo lo que el gate de cuota vigila.
    """
    for _ in range(encargos.TOPE_POR_FASE):
        ficha.preguntar("dia")

    assert ficha.agotada("dia")
    assert ficha.cerrada("dia")
    assert ficha.siguiente().id == "duele"   # se pasa a lo siguiente


def test_un_hueco_declarado_no_impide_construir_pero_SE_DICE(ficha):
    """Un hueco conocido es información y viaja en el informe que él aprueba.
    Uno escondido es una sorpresa a mitad de la construcción."""
    for _ in range(encargos.TOPE_POR_FASE):
        ficha.preguntar("dia")
    ficha.rendirse("dia")
    ficha.responde("duele", "los fiados")
    ficha.responde("como_hoy", "en una libreta")
    ficha.responde("datos", "quién y cuánto")
    ficha.responde("nombre", "La Esquina")
    ficha.responde("alcance", "dale, mándalo")
    ficha.responde("estilo", "e1")

    assert ficha.suficiente()
    assert ficha.huecos() == ["negocio"]


def test_suficiente_es_la_primera_pantalla_y_son_tres_cosas(ficha):
    """🔴 La decisión que controla el coste. Como el ciclo es iterativo, no hace
    falta saberlo todo: hace falta lo justo para enseñarle algo a lo que
    reaccionar. Definirlo como «entenderlo todo» es la entrevista de una hora
    que acaba sin nada que enseñar."""
    assert [f.campo for f in encargos.FASES if f.minimo] == ["negocio", "dolor", "estilo"]
    assert not ficha.suficiente()
    ficha.responde("dia", "una tienda de abarrotes")
    ficha.responde("duele", "los fiados")
    assert not ficha.suficiente()
    ficha.responde("como_hoy", "en una libreta")
    ficha.responde("datos", "quién y cuánto")
    ficha.responde("nombre", "La Esquina")
    ficha.responde("alcance", "dale, mándalo")
    ficha.responde("estilo", "e1")
    assert ficha.suficiente()


def test_el_estilo_se_elige_no_se_describe(ficha):
    """La regla que gobierna al entrevistador: quien no tiene vocabulario
    técnico no puede describir, pero sí puede elegir. Si esta marca se pierde,
    el agente vuelve a preguntar «¿qué estilo quieres?», que no tiene respuesta."""
    assert encargos.POR_ID["estilo"].se_elige is True
    assert not any(f.se_elige for f in encargos.FASES if f.id != "estilo")


def test_un_solo_usuario_no_es_una_fase(ficha):
    """Decisión suya: los MVP son de una persona, sin uso simultáneo. No se
    pregunta porque no es una pregunta — es la restricción que mantiene simple
    lo que se construye, y preguntarla invitaría a contestar que no."""
    assert encargos.UN_SOLO_USUARIO is True
    assert "usuarios" not in [f.campo for f in encargos.FASES]


# ── nada se tira ──────────────────────────────────────────────────────────────


def test_lo_que_divaga_se_guarda_entero(ficha):
    """Si el agente lo ignora, ella siente que no la escuchan y deja de mandar
    audios — que son la materia prima. Lo que hoy es una divagación puede ser el
    requisito de la ronda tres."""
    ficha.anota("mi hija me ayuda los sábados y se pelea con la libreta")

    assert len(ficha.dicho) == 1
    assert "sábados" in ficha.dicho[0]["texto"]


def test_una_respuesta_vacia_no_cierra_una_fase(ficha):
    """Un audio que no se entendió, o un «mmm», no puede dar por contestado
    nada: dejaría la fase cerrada sin haber sabido lo que se quería saber."""
    ficha.responde("dia", "   ")
    assert not ficha.contestada("dia")


def test_una_respuesta_vacia_TAMPOCO_se_esconde_del_informe(ficha):
    """🔴 Lo cazó el sabotaje, no la lectura.

    Guardar la cadena vacía dejaba la fase sin contestar —eso sí lo veía el otro
    test— pero la sacaba de `huecos()`, porque un `""` guardado no es
    `no-lo-sabe`. O sea: el hueco seguía ahí y **dejaba de salir en el informe
    que él aprueba**, que es exactamente el hueco escondido contra el que existe
    este módulo. Un vacío no se guarda.
    """
    ficha.responde("dia", "   ")
    ficha.responde("duele", "los fiados")
    ficha.responde("como_hoy", "en una libreta")
    ficha.responde("datos", "quién y cuánto")
    ficha.responde("nombre", "La Esquina")
    ficha.responde("alcance", "dale, mándalo")
    ficha.responde("estilo", "e1")

    assert "negocio" in ficha.huecos()


def test_una_fase_que_no_existe_se_dice(ficha):
    with pytest.raises(ValueError, match="no es una fase"):
        ficha.responde("presupuesto", "poco")


# ── que compactar sea inofensivo ──────────────────────────────────────────────


def test_la_ficha_sobrevive_a_ida_y_vuelta(ficha):
    """🔴 Esto es lo que hace que compactar —o reiniciar, o cambiar de agente—
    no pierda la entrevista. Si el estado viviera en la conversación, un compact
    a mitad se llevaría lo que ella contestó y nadie se enteraría."""
    ficha.responde("dia", "abro a las siete")
    ficha.preguntar("duele")
    ficha.anota("y los sábados viene mi hija")

    vuelta = encargos.Ficha.de_json(ficha.a_json())

    assert vuelta.campos == ficha.campos
    assert vuelta.preguntado == ficha.preguntado
    assert vuelta.dicho == ficha.dicho
    assert vuelta.siguiente().id == ficha.siguiente().id


# ── la segunda ronda ──────────────────────────────────────────────────────────


def test_otra_ronda_conserva_lo_que_ya_contó(ficha):
    """Ella vio lo publicado y pide cambios. Volver a preguntarle su día entero
    es la forma más rápida de que abandone."""
    ficha.responde("dia", "una tienda de abarrotes")
    ficha.responde("duele", "los fiados")
    ficha.responde("como_hoy", "en una libreta")
    ficha.responde("datos", "quién y cuánto")
    ficha.responde("nombre", "La Esquina")
    ficha.responde("alcance", "dale, mándalo")
    ficha.responde("estilo", "e1")

    dos = encargos.otra_ronda(ficha)

    assert dos.ronda == 2
    assert dos.estado == "recogiendo"
    assert dos.campos == ficha.campos
    assert dos.suficiente()          # no hay nada que volver a preguntar


def test_reabrir_una_fase_devuelve_su_turno_y_su_cupo(ficha):
    """«El estilo no me gustó» reabre esa fase y sólo esa — con el tope otra vez
    entero, porque es una pregunta nueva, no la insistencia de la anterior."""
    ficha.responde("dia", "una tienda")
    ficha.responde("duele", "los fiados")
    ficha.responde("como_hoy", "en una libreta")
    ficha.responde("datos", "quién y cuánto")
    ficha.responde("nombre", "La Esquina")
    ficha.responde("alcance", "dale, mándalo")
    ficha.responde("estilo", "e1")
    for _ in range(encargos.TOPE_POR_FASE):
        ficha.preguntar("estilo")

    encargos.reabrir(ficha, "estilo")

    assert not ficha.suficiente()
    assert ficha.siguiente().id == "estilo"
    assert not ficha.agotada("estilo")


# ── Dónde vive todo esto ────────────────────────────────────────────────────


def test_el_id_vale_a_la_vez_de_carpeta_y_de_subdominio(con):
    """Un solo nombre para las dos cosas, así que una sola validación."""
    for malo in ("", "ab", "Abarrotes", "abarrotes_rosa", "-rosa", "rosa-",
                 "../../etc", "a" * 45):
        with pytest.raises(ValueError):
            encargos.valido(malo)
    assert encargos.valido("abarrotes-rosa") == "abarrotes-rosa"


def test_un_id_con_puntos_no_escribe_fuera_de_hub_home(con):
    """🔴 Sin la validación, la carpeta de un encargo sería cualquier ruta."""
    with pytest.raises(ValueError):
        encargos.carpeta("../../../tmp")


def test_crear_dos_veces_no_reinicia_la_entrevista(con):
    """Quien llama es el relé al ver un mensaje: reiniciar perdería lo contado."""
    encargos.anotar_persona(con, 77, "rosa", "Rosa")
    encargos.crear(con, "abarrotes-rosa", 77)

    ficha = encargos.cargar_ficha(con, "abarrotes-rosa")
    ficha.responde("dia", "abro a las siete y fío a los vecinos")
    encargos.guardar_ficha(con, ficha)

    encargos.crear(con, "abarrotes-rosa", 77)

    assert encargos.cargar_ficha(con, "abarrotes-rosa").campos["negocio"]


def test_la_ficha_se_escribe_entera_o_no_se_escribe(con):
    """Un corte a mitad dejaría un JSON truncado, y la ficha no se reconstruye."""
    encargos.anotar_persona(con, 77, "rosa", "Rosa")
    encargos.crear(con, "abarrotes-rosa", 77)
    ruta = encargos.ruta_ficha("abarrotes-rosa")

    assert ruta.is_file()
    assert not list(ruta.parent.glob("*.parcial"))


def test_el_estado_lo_manda_el_indice_y_no_el_archivo(con):
    """🔴 Lo mueve el relé —él aprueba por Telegram— y el relé no escribe la ficha.

    Si mandara el archivo, su aprobación se perdería en cuanto el agente
    guardara lo siguiente, y el gasto habría quedado autorizado sin efecto.
    """
    encargos.anotar_persona(con, 77, "rosa", "Rosa")
    encargos.crear(con, "abarrotes-rosa", 77)
    encargos.tocar(con, "abarrotes-rosa", estado="aprobado")

    assert encargos.cargar_ficha(con, "abarrotes-rosa").estado == "aprobado"


def test_un_estado_inventado_no_entra_en_el_indice(con):
    encargos.anotar_persona(con, 77, "rosa", "Rosa")
    encargos.crear(con, "abarrotes-rosa", 77)

    with pytest.raises(ValueError, match="no es un estado"):
        encargos.tocar(con, "abarrotes-rosa", estado="casi")


def test_sin_ficha_en_disco_se_empieza_una_en_vez_de_reventar(con):
    """Un encargo cuya carpeta se borró sigue siendo un encargo."""
    encargos.anotar_persona(con, 77, "rosa", "Rosa")
    encargos.crear(con, "abarrotes-rosa", 77)
    encargos.ruta_ficha("abarrotes-rosa").unlink()

    assert encargos.cargar_ficha(con, "abarrotes-rosa").campos == {}


# ── Quién puede hablar con el bot ───────────────────────────────────────────


def test_escribirle_al_bot_no_concede_nada(con):
    """🔴 El alta es siempre un acto suyo. Aparecer sólo sirve para que la vea."""
    encargos.anotar_persona(con, 77, "rosa", "Rosa")

    assert encargos.ver_persona(con, 77)["estado"] == "pendiente"
    assert encargos.puede_hablar(con, 77) is False


def test_dar_de_alta_es_lo_unico_que_abre_el_canal(con):
    encargos.anotar_persona(con, 77, "rosa", "Rosa")
    encargos.editar_persona(con, 77, estado="activo")

    assert encargos.puede_hablar(con, 77) is True


def test_volver_a_escribir_no_pisa_el_alias_que_le_puso_el(con):
    encargos.anotar_persona(con, 77, "rosa", "Rosa")
    encargos.editar_persona(con, 77, alias="Mamá", estado="activo")
    encargos.anotar_persona(con, 77, "rosa2", "Rosa M.")

    persona = encargos.ver_persona(con, 77)
    assert persona["alias"] == "Mamá" and persona["estado"] == "activo"


def test_solo_hay_un_dueno_porque_dos_es_no_tener_ninguno(con):
    """Es quien autoriza el gasto: la acción más privilegiada del sistema."""
    encargos.anotar_persona(con, 1, "primero", "Primero")
    encargos.anotar_persona(con, 2, "otro", "Otro")
    encargos.marcar_dueno(con, 1)
    encargos.marcar_dueno(con, 2)

    assert encargos.dueno(con)["user_id"] == 2
    assert encargos.ver_persona(con, 1)["es_dueno"] == 0


def test_el_encargo_abierto_de_alguien_es_a_donde_va_lo_que_escriba(con):
    encargos.anotar_persona(con, 77, "rosa", "Rosa")
    encargos.crear(con, "abarrotes-rosa", 77)

    assert encargos.abierto_de(con, 77)["id"] == "abarrotes-rosa"


def test_un_encargo_descartado_ya_no_recoge_lo_que_llegue(con):
    encargos.anotar_persona(con, 77, "rosa", "Rosa")
    encargos.crear(con, "abarrotes-rosa", 77)
    encargos.tocar(con, "abarrotes-rosa", estado="descartado")

    assert encargos.abierto_de(con, 77) is None


# ── Ponerle nombre al encargo ───────────────────────────────────────────────


def test_un_encargo_nace_con_un_id_provisional_que_no_es_el_de_nadie(con):
    """No se deriva del nombre de quien escribe: el id acaba siendo un subdominio."""
    assert encargos.siguiente_provisional(con) == "encargo-1"
    encargos.anotar_persona(con, 77, "rosa", "Rosa")
    encargos.crear(con, "encargo-1", 77)

    assert encargos.siguiente_provisional(con) == "encargo-2"
    assert encargos.ES_PROVISIONAL.match("encargo-1")
    assert not encargos.ES_PROVISIONAL.match("abarrotes-rosa")


def test_renombrar_se_lleva_la_carpeta_la_ficha_y_la_conversacion(con):
    from hub import buzon

    encargos.anotar_persona(con, 77, "rosa", "Rosa")
    encargos.crear(con, "encargo-1", 77)
    ficha = encargos.cargar_ficha(con, "encargo-1")
    ficha.responde("dia", "abro a las siete")
    encargos.guardar_ficha(con, ficha)
    buzon.aparcar(con, "encargo-1", 77, "abro a las siete")

    encargos.renombrar(con, "encargo-1", "abarrotes-rosa")

    assert not encargos.carpeta("encargo-1").exists()
    assert encargos.cargar_ficha(con, "abarrotes-rosa").campos["negocio"]
    assert encargos.cargar_ficha(con, "abarrotes-rosa").encargo_id == "abarrotes-rosa"
    assert len(buzon.en_cola(con, "abarrotes-rosa")) == 1


def test_lo_publicado_ya_no_se_renombra(con):
    """🔴 El id es la URL que alguien tiene guardada, y no hay cómo avisarle."""
    encargos.anotar_persona(con, 77, "rosa", "Rosa")
    encargos.crear(con, "abarrotes-rosa", 77)
    encargos.tocar(con, "abarrotes-rosa", url="https://abarrotes-rosa.ejemplo.com")

    with pytest.raises(ValueError, match="rompería el enlace"):
        encargos.renombrar(con, "abarrotes-rosa", "otro-nombre")


def test_no_se_renombra_encima_de_otro_encargo(con):
    encargos.anotar_persona(con, 77, "rosa", "Rosa")
    encargos.crear(con, "encargo-1", 77)
    encargos.crear(con, "encargo-2", 77)

    with pytest.raises(ValueError, match="ya hay un encargo"):
        encargos.renombrar(con, "encargo-1", "encargo-2")


def test_lo_publicado_no_es_un_encargo_abierto_pero_se_encuentra_aparte(con):
    """Lo que diga tras ver su página no es una respuesta de entrevista (234)."""
    encargos.anotar_persona(con, 77, "quien", "Quien")
    encargos.crear(con, "la-tienda", 77)
    encargos.tocar(con, "la-tienda", estado="publicado", url="https://x")

    assert encargos.abierto_de(con, 77) is None
    assert encargos.publicado_de(con, 77)["id"] == "la-tienda"


def test_renombrar_arrastra_los_slots_de_sus_agentes(con):
    """Con el nombre viejo, `cerrar_agentes` no encontraba el constructor (234)."""
    from hub import slots

    encargos.anotar_persona(con, 77, "quien", "Quien")
    encargos.crear(con, "encargo-1", 77)
    con.execute("INSERT OR IGNORE INTO proyecto (id, nombre) VALUES ('encargos','Encargos')")
    a = slots.crear(con, "encargos", "encargo-1", ruta=str(encargos.carpeta("encargo-1")))
    b = slots.crear(con, "encargos", "encargo-1-construir", ruta=str(encargos.carpeta("encargo-1")))
    encargos.tocar(con, "encargo-1", slot_id=a)

    encargos.renombrar(con, "encargo-1", "la-tienda")

    nombres = {r["id"]: (r["nombre"], r["ruta"]) for r in
               con.execute("SELECT id, nombre, ruta FROM slot WHERE id IN (?, ?)", (a, b))}
    assert nombres[a] == ("la-tienda", str(encargos.carpeta("la-tienda")))
    assert nombres[b] == ("la-tienda-construir", str(encargos.carpeta("la-tienda")))


def test_implementando_es_un_estado_del_encargo(con):
    """Visto en el ensayo del 19-sep: la ventana del implementador abrió y el
    estado no se pudo poner porque la lista no lo conocía."""
    encargos.crear(con, "encargo-1", 7)
    encargos.tocar(con, "encargo-1", estado="implementando")
    assert encargos.ver(con, "encargo-1")["estado"] == "implementando"


def test_las_dos_primeras_preguntas_hablan_del_sistema_y_no_del_dia():
    """Petición suya del 19-sep: «cómo es tu día» y «qué te quitarías de encima»
    se malentendían; la persona ya sabe que viene a hacerse un sistema."""
    dia, duele = encargos.POR_ID["dia"], encargos.POR_ID["duele"]
    assert "sistema" in dia.pregunta and "día normal" not in dia.pregunta
    assert "primero" in duele.pregunta and "quitarte" not in duele.pregunta
    assert dia.campo == "negocio" and duele.campo == "dolor", "los campos de la ficha no cambian"
