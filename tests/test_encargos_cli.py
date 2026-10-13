"""Las manos del agente entrevistador: lo que puede hacer, y lo que no.

🔴 Este archivo prueba un contrato, no una utilidad. Lo que el agente puede
hacer en el mundo es exactamente lo que hay en `encargos_cli`, así que lo que
más importa aquí es que siga sin poder mandar nada por su cuenta, sin construir
y sin cerrar una ficha con huecos escondidos.
"""

from __future__ import annotations

from pathlib import Path
import pytest

from hub import buzon, config, db, encargos, encargos_cli, entrevistador


@pytest.fixture
def escena(con, monkeypatch, tmp_path):
    """Un encargo abierto, con su dueño, y la CLI apuntando a esta base."""
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "hub.db")
    otra = db.conectar(config.DB_PATH)
    db.inicializar(otra)
    encargos.anotar_persona(otra, 77, "quien", "Quien")
    encargos.editar_persona(otra, 77, estado="activo", alias="Rosa")
    encargos.anotar_persona(otra, 1, "eldueno", "El Dueño")
    encargos.marcar_dueno(otra, 1)
    encargos.crear(otra, "encargo-1", 77)
    otra.commit()
    return otra


def corre(*argv) -> int:
    return encargos_cli.main(list(argv))


# ── Mirar: el «dónde estoy» que hace inofensivo compactar ───────────────────


def test_la_ficha_dice_que_sabe_que_falta_y_que_toca(escena, capsys):
    """🔴 Un agente recién reiniciado sabe lo mismo que uno de media hora."""
    assert corre("ficha") == 0

    salida = capsys.readouterr().out
    assert "LO QUE YA SÉ" in salida and "LO QUE FALTA" in salida
    assert "QUÉ TOCA AHORA" in salida
    assert "Rosa" in salida


def test_la_fase_que_se_elige_se_dice_como_tal_en_vez_de_como_pregunta(escena, capsys):
    """Quien no puede describir sí puede señalar: ahí se enseña, no se pregunta."""
    ficha = encargos.cargar_ficha(escena, "encargo-1")
    ficha.responde("dia", "abro a las siete")
    ficha.responde("duele", "apuntar los fiados")
    ficha.responde("como_hoy", "en una libreta")
    ficha.responde("datos", "quién y cuánto")
    ficha.responde("nombre", "La Esquina")
    ficha.responde("alcance", "dale, mándalo")
    encargos.guardar_ficha(escena, ficha)
    escena.commit()

    corre("ficha")

    assert "ELIGIENDO" in capsys.readouterr().out


def test_la_ficha_avisa_de_lo_que_hay_sin_leer_en_la_cola(escena, capsys):
    buzon.aparcar(escena, "encargo-1", 77, "una cosa más")
    escena.commit()

    corre("ficha")

    assert "sin leer" in capsys.readouterr().out


# ── Preguntar, con su tope ──────────────────────────────────────────────────


def test_preguntar_encola_en_vez_de_mandar(escena, capsys):
    """🔴 El agente no tiene el token, y por eso no puede mandar nada (regla 22)."""
    assert corre("preguntar") == 0

    pendientes = buzon.salientes(escena)
    assert len(pendientes) == 1 and pendientes[0]["direccion"] == "sale"


def test_preguntar_con_sus_palabras_cuenta_igual_para_el_tope(escena):
    """Lo que se mide es insistir, no qué frase se usó."""
    corre("preguntar", "¿a qué hora abres la tienda?")

    ficha = encargos.cargar_ficha(escena, "encargo-1")
    assert ficha.preguntado["dia"] == 1
    assert buzon.salientes(escena)[0]["texto"] == "¿a qué hora abres la tienda?"


def test_agotado_el_tope_esa_fase_deja_de_pedir_turno(escena, capsys):
    for _ in range(encargos.TOPE_POR_FASE):
        corre("preguntar")

    corre("ficha")
    assert "duele" in capsys.readouterr().out    # ya pasó a la siguiente


def test_una_fase_que_se_elige_no_se_pregunta_por_texto(escena, capsys):
    ficha = encargos.cargar_ficha(escena, "encargo-1")
    ficha.responde("dia", "abro a las siete")
    ficha.responde("duele", "los fiados")
    ficha.responde("como_hoy", "en una libreta")
    ficha.responde("datos", "quién y cuánto")
    ficha.responde("nombre", "La Esquina")
    ficha.responde("alcance", "dale, mándalo")
    encargos.guardar_ficha(escena, ficha)
    escena.commit()

    assert corre("preguntar") == 2
    assert "muestras" in capsys.readouterr().err


# ── Recoger lo que diga, venga cuando venga ─────────────────────────────────


def test_una_respuesta_cae_en_su_casilla_aunque_no_sea_su_turno(escena):
    """Va a decir las cosas como se le vengan a la mente; la ficha las coloca."""
    corre("responde", "duele", "apuntar los fiados en la libreta")

    ficha = encargos.cargar_ficha(escena, "encargo-1")
    assert ficha.campos["dolor"] == "apuntar los fiados en la libreta"
    assert ficha.siguiente().id == "dia"      # la suya sigue abierta


def test_una_fase_inventada_se_rechaza_en_vez_de_tragarse(escena, capsys):
    assert corre("responde", "colores", "azul") == 2


def test_lo_que_no_cabe_en_una_casilla_no_se_tira(escena):
    """Lo que hoy es una divagación puede ser el requisito de la ronda tres."""
    corre("anota", "me contó veinte minutos de su vecina y del perro")

    assert encargos.cargar_ficha(escena, "encargo-1").dicho


def test_rendirse_declara_el_hueco_y_no_lo_esconde(escena):
    """🔴 Un hueco declarado viaja en el informe; uno escondido es una sorpresa."""
    corre("rendirse", "duele")

    ficha = encargos.cargar_ficha(escena, "encargo-1")
    assert ficha.campos["dolor"] == encargos.NO_LO_SABE
    assert "dolor" in ficha.huecos()


# ── Proponer: el único sitio donde esto toca dinero ─────────────────────────


def _informe(tmp_path):
    ruta = tmp_path / "informe.md"
    ruta.write_text("Una tienda de barrio. La primera pantalla lista los fiados.",
                    encoding="utf-8")
    return str(ruta)


def _ficha_completa(con):
    ficha = encargos.cargar_ficha(con, "encargo-1")
    ficha.responde("dia", "abro a las siete")
    ficha.responde("duele", "los fiados")
    ficha.responde("como_hoy", "en una libreta")
    ficha.responde("datos", "quién y cuánto")
    ficha.responde("nombre", "La Esquina")
    ficha.responde("alcance", "dale, mándalo")
    ficha.responde("estilo", "claro")
    encargos.guardar_ficha(con, ficha)
    con.commit()


def test_no_se_propone_con_fases_abiertas(escena, tmp_path, capsys):
    assert corre("proponer", _informe(tmp_path)) == 2
    assert "rendirse" in capsys.readouterr().err


def test_el_plan_sale_hacia_el_dueno_y_no_hacia_quien_encargo(escena, tmp_path):
    """Es él quien autoriza el gasto; ella no tiene por qué ver un plan."""
    _ficha_completa(escena)

    assert corre("proponer", _informe(tmp_path)) == 0

    plan = buzon.salientes(escena)[-1]
    assert plan["clase"] == "plan" and plan["user_id"] == 1


def test_el_plan_dice_como_se_aprueba_y_que_un_si_suelto_no_vale(escena, tmp_path):
    """La instrucción va dentro del propio mensaje: es donde se va a leer."""
    _ficha_completa(escena)
    corre("proponer", _informe(tmp_path))

    texto = buzon.salientes(escena)[-1]["texto"]
    assert "ESTE mensaje" in texto and "Aprobar" in texto


def test_los_huecos_viajan_en_el_plan(escena, tmp_path):
    ficha = encargos.cargar_ficha(escena, "encargo-1")
    ficha.responde("dia", "abro a las siete")
    ficha.rendirse("duele")
    ficha.responde("como_hoy", "en una libreta")
    ficha.responde("datos", "quién y cuánto")
    ficha.responde("nombre", "La Esquina")
    ficha.responde("alcance", "dale, mándalo")
    ficha.responde("estilo", "claro")
    encargos.guardar_ficha(escena, ficha)
    escena.commit()

    corre("proponer", _informe(tmp_path))

    assert "Sin respuesta" in buzon.salientes(escena)[-1]["texto"]


def test_proponer_deja_el_encargo_esperando_y_no_construyendo(escena, tmp_path):
    """🔴 El agente no puede empezar: el gasto lo autoriza una persona después."""
    _ficha_completa(escena)
    corre("proponer", _informe(tmp_path))

    assert encargos.ver(escena, "encargo-1")["estado"] == "propuesta"


def test_sin_dueno_el_plan_no_se_manda_a_nadie(escena, tmp_path, capsys):
    _ficha_completa(escena)
    encargos.marcar_dueno(escena, None)
    escena.commit()

    assert corre("proponer", _informe(tmp_path)) == 2
    assert "dueño" in capsys.readouterr().err


def test_un_informe_que_no_existe_no_manda_un_plan_vacio(escena, capsys):
    _ficha_completa(escena)

    assert corre("proponer", "/no/existe.md") == 2


# ── Ponerle nombre antes de que sea una URL ─────────────────────────────────


def test_nombrar_apunta_el_nombre_y_NO_mueve_la_carpeta(escena, capsys):
    """🔴 Decisión 241. Se movía, y el agente que acababa de teclear la orden se
    quedaba en una carpeta que ya no existía; al reabrirlo pedía el nombre otra
    vez y el hub le decía «cogido» por él mismo. Ahora se apunta en la ficha, la
    fase queda cerrada, y el id cambia al publicar."""
    assert corre("nombrar", "Abarrotes del Centro") == 0
    assert encargos.ver(escena, "encargo-1")
    assert encargos.ver(escena, "abarrotes-del-centro") is None
    assert encargos.carpeta("encargo-1").is_dir()
    ficha = encargos.cargar_ficha(escena, "encargo-1")
    assert ficha.contestada("nombre") and ficha.campos["nombre"] == "Abarrotes del Centro"
    assert encargos.nombre_sugerido(escena, ficha) == "abarrotes-del-centro"


def test_nombrar_dos_veces_lo_mismo_no_es_estar_cogido(escena, capsys):
    """El agente reabierto vuelve a teclear la orden: tiene que salir bien."""
    assert corre("nombrar", "La Tienda") == 0
    assert corre("nombrar", "La Tienda") == 0
    encargos.renombrar(escena, "encargo-1", "la-tienda")
    escena.commit()
    assert corre("--encargo", "la-tienda", "nombrar", "La Tienda") == 0


def test_nombrar_acepta_lo_que_ella_dijo_y_devuelve_la_direccion(escena, capsys, monkeypatch):
    """Decisión 233: cualquier nombre vale; se convierte, se comprueba y se le dice."""
    from hub import rele_encargos

    monkeypatch.setattr(rele_encargos, "ajustes", lambda: {"despliegue": {
        "servidor": "s", "caddy": "c", "dominio": "ejemplo.com"}})
    assert corre("nombrar", "Peluches de Ana!") == 0
    assert "https://peluches-de-ana.ejemplo.com" in capsys.readouterr().out


def test_un_nombre_del_que_no_sale_nada_o_reservado_o_cogido_se_rechaza(escena, capsys):
    assert corre("nombrar", "¿?¡!") == 2
    assert corre("nombrar", "pizarra") == 2 and "reservado" in capsys.readouterr().err
    encargos.crear(escena, "la-tienda", 77)
    escena.commit()
    assert corre("--encargo", "encargo-1", "nombrar", "La Tienda") == 2
    assert "cogido" in capsys.readouterr().err


def test_proponer_le_dice_a_ella_que_ya_tiene_lo_que_necesita(escena, tmp_path):
    """La primera persona real sólo vio que el bot dejó de contestar (233)."""
    _ficha_completa(escena)
    corre("proponer", _informe(tmp_path))

    a_ella = [m["texto"] for m in buzon.salientes(escena) if m["user_id"] is None]
    assert any("Te aviso yo en cuanto esté" in t for t in a_ella)


# ── Lo que el contrato NO le da ─────────────────────────────────────────────


def test_no_hay_ninguna_orden_para_construir_ni_desplegar_ni_borrar(escena):
    """🔴 Si un día aparece una, el gate de la aprobación deja de significar nada."""
    prohibidas = {"desplegar", "publicar", "construir", "borrar", "ejecutar", "shell"}

    assert prohibidas & set(encargos_cli.ORDENES) == set()


def test_la_lista_de_ordenes_es_exactamente_la_documentada(escena):
    """El docstring del módulo es el contrato; que no se separen sin querer."""
    for orden in encargos_cli.ORDENES:
        assert f"encargo {orden}" in encargos_cli.__doc__


# ── La carpeta donde vive el agente ─────────────────────────────────────────


def test_preparar_deja_las_instrucciones_y_las_manos(escena):
    carpeta = entrevistador.preparar(escena, "encargo-1")

    assert (carpeta / "INSTRUCCIONES.md").is_file()
    assert (carpeta / "encargo").stat().st_mode & 0o111
    assert (carpeta / "audios").is_dir()


def test_las_instrucciones_se_regeneran_y_la_ficha_no_se_toca(escena):
    """El contrato cambia con el proyecto; lo que ella contó, no."""
    ficha = encargos.cargar_ficha(escena, "encargo-1")
    ficha.responde("dia", "abro a las siete")
    encargos.guardar_ficha(escena, ficha)
    escena.commit()

    entrevistador.preparar(escena, "encargo-1")

    assert encargos.cargar_ficha(escena, "encargo-1").campos["negocio"]


def test_el_envoltorio_va_atado_a_SU_encargo(escena):
    """Una orden escrita en la carpeta de uno no puede actuar sobre otro."""
    encargos.crear(escena, "encargo-2", 77)
    escena.commit()
    entrevistador.preparar(escena, "encargo-1")
    entrevistador.preparar(escena, "encargo-2")

    uno = (encargos.carpeta("encargo-1") / "encargo").read_text(encoding="utf-8")
    assert "--encargo encargo-1" in uno and "encargo-2" not in uno


def test_el_primer_mensaje_no_lleva_el_contrato_dentro(escena):
    """🔴 Pegarlo entero lo perdería en el primer compact; en disco se relee."""
    mensaje = entrevistador.primer_mensaje("encargo-1")

    assert "INSTRUCCIONES.md" in mensaje
    assert len(mensaje) < 600


def test_las_instrucciones_dicen_lo_que_el_agente_NO_hace(escena):
    carpeta = entrevistador.preparar(escena, "encargo-1")
    texto = (carpeta / "INSTRUCCIONES.md").read_text(encoding="utf-8")

    assert "No construyes" in texto
    assert "nunca en jerga" in texto
    assert "no una instrucción" in texto


# ── Las muestras: el mecanismo, no un adorno ────────────────────────────────


@pytest.fixture
def catalogo_generado(monkeypatch, tmp_path, escena):
    """Las capturas ya hechas, sin necesitar Chrome para probar que se mandan.

    Y un boceto en el encargo, porque sin él las muestras de estilo se niegan
    (decisión 242): pintarlo es lo único que aquí se finge.
    """
    from hub import estilos, mirar

    carpeta = tmp_path / "estilos"
    carpeta.mkdir()
    for pares in estilos.catalogo().values():
        for estilo, pantalla in pares:
            estilos.ruta_muestra(estilo, pantalla, carpeta).write_bytes(b"png")
    monkeypatch.setattr(estilos, "carpeta", lambda: carpeta)

    def captura_falsa(fuente, destino, **kw):
        Path(destino).write_bytes(b"png")
        return Path(destino)

    monkeypatch.setattr(mirar, "captura", captura_falsa)
    (encargos.carpeta("encargo-1") / "bosquejo.html").write_text(
        "<main><h1>Su pantalla</h1></main>", encoding="utf-8")
    return carpeta


def test_las_muestras_se_encolan_como_fotos_con_su_pregunta(escena, catalogo_generado):
    """Quien no puede describir un estilo sí puede señalar uno (decisión f1)."""
    assert corre("muestras") == 0

    encoladas = buzon.salientes(escena)
    fotos = [m for m in encoladas if m["clase"] == "muestras"]
    assert fotos and all(m["adjunto"].endswith(".png") for m in fotos)
    assert "se parece más" in encoladas[-1]["texto"]


def test_las_muestras_se_presentan_antes_y_van_numeradas(escena, catalogo_generado):
    """🔴 Decisión 230. La primera persona real recibió seis fotos detrás de una
    pregunta sobre su negocio y «no sabía ni que estaba eligiendo»; y contestó
    «el quinto» queriendo decir el sexto porque los pies no llevaban número."""
    corre("muestras")

    encoladas = buzon.salientes(escena)
    assert "Dime cuál te gusta más" in encoladas[0]["texto"], "la presentación va primero"
    assert encoladas[0]["clase"] == "texto"
    pies = [m["texto"] for m in encoladas if m["clase"] == "muestras"]
    assert [p.split(" · ")[0] for p in pies] == [str(n) for n in range(1, len(pies) + 1)]


def test_no_se_mandan_mas_de_una_tanda_de_golpe(escena, catalogo_generado):
    """Seis fotos seguidas en un móvil ya son un muro, y deja de comparar."""
    corre("muestras")

    fotos = [m for m in buzon.salientes(escena) if m["clase"] == "muestras"]
    assert len(fotos) <= encargos_cli.POR_TANDA


def test_el_catalogo_de_pantallas_es_otro_y_se_pide_aparte(escena, catalogo_generado):
    """Los dos catálogos contestan preguntas distintas; mezclarlos los arruina."""
    corre("muestras", "pantallas")

    fotos = [m for m in buzon.salientes(escena) if m["clase"] == "muestras"]
    assert fotos and all("claro" in m["adjunto"] for m in fotos)


def test_si_falta_alguna_captura_no_se_manda_media_tanda(escena, catalogo_generado, capsys):
    """🔴 Elegiría entre las que llegaron creyendo que las vio todas.

    Y no basta con devolver error: encolando sobre la marcha, las cinco que sí
    estaban ya habían salido. Por eso esto mira también la cola, que es donde se
    veía el fallo de verdad.
    """
    from hub import estilos

    # Sobre el catálogo de pantallas: el de estilos ya no sale del catálogo
    # sino del boceto, que se pinta entero cada vez (242).
    estilo, pantalla = estilos.catalogo()["pantallas"][0]
    estilos.ruta_muestra(estilo, pantalla, catalogo_generado).unlink()

    assert corre("muestras", "pantallas") == 2
    assert "generar" in capsys.readouterr().err
    assert buzon.salientes(escena) == []


# ── Poner al agente a vivir en un panel ─────────────────────────────────────


@pytest.fixture
def tmux_falso(monkeypatch):
    """tmux sustituido: lo que se apunta es qué ventana se habría abierto."""
    from hub import slots

    abiertas = []

    def _abrir(con, slot_id, session=None, **_):
        abiertas.append(slot_id)
        return f"%{slot_id}"

    monkeypatch.setattr(slots, "abrir", _abrir)
    monkeypatch.setattr(entrevistador, "comprobar_arranque", lambda pane_id: None)
    return abiertas


def test_abrir_el_agente_lo_deja_en_su_propio_slot(escena, tmux_falso):
    """El slot es lo que deja resolver el panel EN EL INSTANTE de entregar."""
    from hub import entrevistador

    hecho = entrevistador.abrir_agente(escena, "encargo-1")

    assert hecho["slot_id"]
    assert encargos.ver(escena, "encargo-1")["slot_id"] == hecho["slot_id"]


def test_el_agente_arranca_dentro_de_la_carpeta_de_su_encargo(escena, tmux_falso):
    from hub import api, entrevistador

    hecho = entrevistador.abrir_agente(escena, "encargo-1")

    slot = api.obtener_slot(escena, hecho["slot_id"])
    assert slot["ruta"] == str(encargos.carpeta("encargo-1"))


def test_el_agente_no_arranca_saltandose_los_permisos(escena, tmux_falso):
    """🔴 `bypassPermissions` ignoraría el settings.json entero, y entonces el
    «no construye, y no puede aunque quiera» dejaría de ser cierto."""
    from hub import api, entrevistador

    hecho = entrevistador.abrir_agente(escena, "encargo-1")

    assert "bypass" not in api.obtener_slot(escena, hecho["slot_id"])["comando"]


def test_los_permisos_lo_acotan_a_su_carpeta_y_a_sus_manos(escena, tmux_falso):
    import json

    from hub import entrevistador

    entrevistador.abrir_agente(escena, "encargo-1")
    carpeta = encargos.carpeta("encargo-1")
    permisos = json.loads((carpeta / ".claude" / "settings.json").read_text())["permissions"]

    concedido = " ".join(permisos["allow"])
    assert str(carpeta) in concedido
    assert "encargo:*" in concedido
    for prohibido in ("git", "rm", "curl", "ssh"):
        assert f"Bash({prohibido}" not in concedido


def test_no_se_abren_dos_agentes_sobre_la_misma_ficha(escena, tmux_falso, monkeypatch):
    """Se pisarían el archivo y los dos le contestarían a la misma persona."""
    from hub import entrevistador, tmux

    hecho = entrevistador.abrir_agente(escena, "encargo-1")
    escena.execute("INSERT INTO snapshot (id, tomado_en, server_pid) VALUES (1,?,99)",
                   (encargos.ahora(),))
    escena.execute(
        """INSERT INTO panel (snapshot_id, pane_id, session, window_idx, pane_idx,
                              cwd, titulo, comando, slot_id)
           VALUES (1,'%9','encargos',0,0,'/tmp','⠂ encargo-1','claude',?)""",
        (hecho["slot_id"],),
    )
    # Que ese panel siga vivo lo dice tmux, no la fila: un panel apuntado que ya
    # no existe no cuenta como abierto.
    monkeypatch.setattr(tmux, "servidor_pid", lambda: 99)   # el del snapshot
    monkeypatch.setattr(tmux, "titulo_panel", lambda pane_id: "⠂ encargo-1")
    monkeypatch.setattr(tmux, "listar_paneles", lambda incluir_espejos=False: [
        {"pane_id": "%9", "session": "encargos", "window_idx": 0}])

    otra = entrevistador.abrir_agente(escena, "encargo-1")

    assert otra["ya_estaba"] is True
    assert otra["session"] == "encargos" and otra["ventana"] == 0
    assert len(tmux_falso) == 1


def test_un_panel_apuntado_que_ya_no_existe_no_cuenta_como_abierto(escena, tmux_falso, monkeypatch):
    """🔴 Lo contrario del anterior, y por eso hay dos.

    Si un `pane_id` apuntado bastara, cerrar la ventana del agente dejaría el
    encargo creyendo que sigue abierto: nadie podría reabrirlo y todo lo que
    ella mandara se quedaría en cola para siempre.
    """
    from hub import entrevistador, tmux

    hecho = entrevistador.abrir_agente(escena, "encargo-1")
    monkeypatch.setattr(tmux, "titulo_panel", lambda pane_id: None)

    assert entrevistador.panel_vivo(escena, hecho["slot_id"]) is None
    assert entrevistador.abrir_agente(escena, "encargo-1")["ya_estaba"] is False


def test_los_encargos_cuelgan_de_un_solo_proyecto(escena, tmux_falso):
    """🔴 Uno por encargo los metería en el registro «como uno más», y entonces
    todo lo que el hub mide sobre proyectos actuaría sobre trabajo ajeno."""
    from hub import api, entrevistador

    encargos.crear(escena, "encargo-2", 77)
    entrevistador.abrir_agente(escena, "encargo-1")
    entrevistador.abrir_agente(escena, "encargo-2")

    proyectos = [p["id"] for p in api.listar_proyectos(escena)]
    assert proyectos.count(entrevistador.PROYECTO) == 1
    assert api.obtener_proyecto(escena, entrevistador.PROYECTO)["dominio"] == "encargos"


def test_un_encargo_cerrado_no_reabre_una_entrevista(escena, tmux_falso):
    from hub import entrevistador

    encargos.tocar(escena, "encargo-1", estado="descartado")

    with pytest.raises(ValueError, match="descartado"):
        entrevistador.abrir_agente(escena, "encargo-1")


# ── Construir: lo que empieza sólo cuando alguien ya dijo que sí ────────────


def _aprobado(con, tmux_falso=None):
    _ficha_completa(con)
    encargos.tocar(con, "encargo-1", estado="aprobado")
    con.commit()


def test_construir_no_empieza_sobre_algo_sin_aprobar(escena, tmux_falso):
    """🔴 Es el gate entero: separa «alguien vio el plan» de «un agente gastó»."""
    from hub import constructor

    with pytest.raises(ValueError, match="aprobado"):
        constructor.abrir_agente(escena, "encargo-1")

    assert tmux_falso == []


def test_el_constructor_trabaja_en_su_propio_panel(escena, tmux_falso):
    """Dos contratos distintos en la misma carpeta: reusar el panel dejaría al
    constructor heredando las instrucciones del entrevistador."""
    from hub import api, constructor, entrevistador

    entrevistador.abrir_agente(escena, "encargo-1")
    _aprobado(escena)
    hecho = constructor.abrir_agente(escena, "encargo-1")

    assert hecho["slot_id"] != encargos.ver(escena, "encargo-1")["slot_id"]
    assert api.obtener_slot(escena, hecho["slot_id"])["nombre"].endswith("-construir")


def test_se_construye_con_el_CSS_QUE_ELLA_ELIGIO(escena, tmux_falso):
    """🔴 Lo único que ella pudo decidir viendo. Con otro CSS sería un trámite."""
    from hub import constructor, estilos

    ficha = encargos.cargar_ficha(escena, "encargo-1")
    ficha.responde("dia", "abro a las siete")
    ficha.responde("duele", "los fiados")
    ficha.responde("como_hoy", "en una libreta")
    ficha.responde("datos", "quién y cuánto")
    ficha.responde("nombre", "La Esquina")
    ficha.responde("alcance", "dale, mándalo")
    ficha.responde("estilo", "nocturno")
    encargos.guardar_ficha(escena, ficha)
    encargos.tocar(escena, "encargo-1", estado="aprobado")
    escena.commit()

    constructor.abrir_agente(escena, "encargo-1")

    hoja = (constructor.sitio("encargo-1") / "estilo.css").read_text(encoding="utf-8")
    assert hoja == estilos.hoja("nocturno")
    assert hoja != estilos.hoja(estilos.ESTILO_DE_REFERENCIA)
    # El id, no sólo el nombre: son distintos —«nocturno» se llama «Oscuro»— y
    # el id es lo que hay en la ficha.
    assert "nocturno" in hoja


def test_sin_estilo_elegido_se_construye_igual_y_se_dice(escena, tmux_falso):
    """Que no eligiera no puede impedir construir; suponer en silencio, sí."""
    from hub import constructor

    _aprobado(escena)
    ficha = encargos.cargar_ficha(escena, "encargo-1")
    ficha.campos["estilo"] = "que sea bonito"
    encargos.guardar_ficha(escena, ficha)
    escena.commit()

    constructor.abrir_agente(escena, "encargo-1")

    assert (constructor.sitio("encargo-1") / "estilo.css").is_file()


def test_el_constructor_tampoco_arranca_saltandose_los_permisos(escena, tmux_falso):
    """Éste sí escribe archivos, así que aquí importa todavía más."""
    from hub import api, constructor

    _aprobado(escena)
    hecho = constructor.abrir_agente(escena, "encargo-1")

    assert "bypass" not in api.obtener_slot(escena, hecho["slot_id"])["comando"]


def test_el_estilo_css_de_un_sitio_no_lleva_el_marco_de_la_captura(escena):
    """La muestra son 720×1000 para comparar; un sitio se mira en un teléfono."""
    from hub import estilos

    hoja = estilos.hoja("claro")
    assert "720px" not in hoja and "100vh" in hoja


# ── Cerrar: el agente cambia el estado; publicar es del relé ────────────────


def test_listo_no_cierra_algo_que_no_se_estaba_construyendo(escena):
    assert corre("listo") == 2


def test_listo_sin_portada_no_da_por_bueno_un_sitio_vacio(escena, capsys):
    """La URL devolvería un listado de archivos y parecería el servidor roto."""
    encargos.tocar(escena, "encargo-1", estado="construyendo")
    escena.commit()

    assert corre("listo") == 2
    assert "index.html" in capsys.readouterr().err


def _construyendo_con_portada(escena):
    encargos.tocar(escena, "encargo-1", estado="construyendo")
    portada = encargos.carpeta("encargo-1") / "sitio" / "index.html"
    portada.parent.mkdir(parents=True, exist_ok=True)
    portada.write_text("<h1>Los fiados</h1>", encoding="utf-8")
    escena.commit()


def test_listo_avisa_a_quien_aprobo_y_el_agente_NO_despliega(escena, monkeypatch):
    """🔴 Lo que un agente consigue al terminar es cambiar un estado. Publicar
    lo hace el relé en su vuelta (decisión 228), y sin configurar dónde, el
    aviso trae el comando para hacerlo a mano."""
    from hub import rele_encargos

    monkeypatch.setattr(rele_encargos, "ajustes", lambda: {})
    _construyendo_con_portada(escena)

    assert corre("listo") == 0
    assert encargos.ver(escena, "encargo-1")["estado"] == "construido"
    aviso = buzon.salientes(escena)[-1]
    assert aviso["user_id"] == 1 and "desplegar-encargo.sh" in aviso["texto"]


def test_con_despliegue_configurado_el_aviso_dice_que_sale_solo(escena, monkeypatch):
    from hub import rele_encargos

    monkeypatch.setattr(rele_encargos, "ajustes", lambda: {"despliegue": {
        "servidor": "vps-prueba", "caddy": "caddy", "dominio": "ejemplo.com"}})
    _construyendo_con_portada(escena)

    assert corre("listo") == 0
    aviso = buzon.salientes(escena)[-1]
    assert "Se publica solo" in aviso["texto"] and "desplegar-encargo.sh" not in aviso["texto"]


def test_el_enlace_publicado_le_llega_tambien_a_ella(escena):
    """🔴 Decisión n6: quien puede decir «así no es» es quien describió el negocio.

    Sin esto el circuito se cierra entre el hub y quien paga, y nadie sabe si lo
    construido encaja con lo que se contó.
    """
    encargos.renombrar(escena, "encargo-1", "abarrotes-del-centro")
    encargos.tocar(escena, "abarrotes-del-centro", estado="construido")
    escena.commit()

    assert corre("publicado", "https://abarrotes.ejemplo.com") == 0

    destinos = {m["user_id"] for m in buzon.salientes(escena)}
    assert destinos == {None, 1}      # None = quien encargó; 1 = el dueño
    assert encargos.ver(escena, "abarrotes-del-centro")["url"] == "https://abarrotes.ejemplo.com"


def test_publicado_a_mano_acepta_un_nombre_provisional(escena):
    """Decisión 232: la barrera del nombre se quitó de los dos caminos a la vez."""
    assert corre("publicado", "https://encargo-1.ejemplo.com") == 0
    assert encargos.ver(escena, "encargo-1")["url"] == "https://encargo-1.ejemplo.com"


def test_una_url_a_medias_no_se_apunta(escena):
    encargos.tocar(escena, "encargo-1", estado="construido")
    escena.commit()

    assert corre("publicado", "abarrotes.ejemplo.com") == 2


def test_una_fase_que_se_elige_guarda_el_ID_y_no_la_frase(escena):
    """🔴 Quien construye busca un id; la frase lo dejaría sin saber qué eligió."""
    corre("responde", "estilo", "Cálido, como una tienda de barrio")

    ficha = encargos.cargar_ficha(escena, "encargo-1")
    assert ficha.campos["estilo"] == "calido"
    # Y lo que dijo con sus palabras no se tira: va a «lo que contó».
    assert any("tienda de barrio" in a["texto"] for a in ficha.dicho)


def test_si_no_se_sabe_que_muestra_eligio_no_se_guarda_una_suposicion(escena, capsys):
    assert corre("responde", "estilo", "que sea bonito") == 2
    assert "vuelve a preguntarle" in capsys.readouterr().err
    assert "estilo" not in encargos.cargar_ficha(escena, "encargo-1").campos


def test_los_agentes_de_encargo_dicen_en_que_modo_corren(escena, tmux_falso):
    """🔴 Sin decirlo se hereda el del usuario, y en esta máquina era `auto`.

    Se vio mirando un agente real: el `settings.json` que lo acota estaba
    puesto y aun así se aprobaba todo, porque el modo por omisión de la
    instalación lo permitía. Aquí importa más que en ningún otro agente del
    hub, porque **lo que guía a éstos lo escribió alguien de fuera**: la ficha y
    el informe salen de los audios de otra persona.
    """
    from hub import api, constructor, entrevistador

    hecho = entrevistador.abrir_agente(escena, "encargo-1")
    comando = api.obtener_slot(escena, hecho["slot_id"])["comando"]

    # `dontAsk`, no `manual`: lo no permitido se deniega al instante en vez de
    # dejar al agente parado en un cuadro que nadie ve (decisión 240).
    assert "--permission-mode dontAsk" in comando
    assert "bypass" not in comando
    assert constructor.MODO == entrevistador.MODO == "dontAsk"


# ── Mirar lo construido, y poder retirar un desliz ──────────────────────────


def test_mirar_pinta_el_movil_primero(escena, monkeypatch, tmp_path):
    """🔴 390 px es donde se va a abrir de verdad; 1000 es la comprobación."""
    from pathlib import Path

    from hub import constructor, mirar

    portada = constructor.sitio("encargo-1")
    portada.mkdir(parents=True, exist_ok=True)
    (portada / "index.html").write_text("<h1>Fiado</h1>", encoding="utf-8")

    pedidos = []

    def _captura(fuente, destino, ancho=1000, **resto):
        pedidos.append(ancho)
        Path(destino).parent.mkdir(parents=True, exist_ok=True)
        Path(destino).write_bytes(b"png")
        return Path(destino)

    monkeypatch.setattr(mirar, "captura", _captura)

    assert corre("mirar") == 0
    assert pedidos == [390, 1000]


def test_sin_nada_construido_no_se_pinta_nada(escena, capsys):
    assert corre("mirar") == 2
    assert "que mirar" in capsys.readouterr().err


def test_el_navegador_de_windows_avisa_de_que_no_baja_de_500(capsys, monkeypatch, tmp_path):
    """🔴 Maqueta a 500 y recorta: una pantalla correcta parece desbordada.

    Callarlo convierte una comprobación en una mentira con formato de prueba.
    """
    from hub import mirar

    fuente = tmp_path / "x.html"
    fuente.write_text("<h1>x</h1>", encoding="utf-8")
    monkeypatch.setattr(mirar.subprocess, "run",
                        lambda *a, **k: (tmp_path / "s.png").write_bytes(b"png"))
    monkeypatch.setattr(mirar, "para", lambda chrome, ruta: str(ruta))

    mirar.captura(str(fuente), tmp_path / "s.png", ancho=390,
                  chrome="/mnt/c/Program Files/Google/Chrome/Application/chrome.exe")

    assert "500" in capsys.readouterr().out


def test_no_se_repite_el_catalogo_a_quien_ya_eligio(escena, catalogo_generado, capsys):
    """🔴 Un catálogo repetido no se lee como un error del bot: se lee como que
    no le hicieron caso. Lo destapó un agente de verdad haciéndolo."""
    corre("responde", "estilo", "calido")

    assert corre("muestras") == 2
    assert "no le hiciste caso" in capsys.readouterr().err
    assert buzon.salientes(escena) == []


def test_repetirlo_a_proposito_se_puede_pero_hay_que_pedirlo(escena, catalogo_generado):
    """La puerta existe; lo que no existe es hacerlo sin querer."""
    corre("responde", "estilo", "calido")

    assert corre("muestras", "--otra-vez") == 0
    assert buzon.salientes(escena)


def test_lo_encolado_por_error_se_retira_mientras_no_haya_salido(escena, capsys):
    """🔴 Un desliz encoló siete mensajes de golpe y no había forma de pararlos."""
    for i in range(3):
        buzon.encolar_salida(escena, "encargo-1", f"mensaje {i}")

    assert corre("deshacer", "2") == 0
    assert [m["texto"] for m in buzon.salientes(escena)] == ["mensaje 0"]


def test_lo_retirado_se_ve_retirado_y_no_desaparece(escena):
    """Un mensaje que desaparece sin rastro es peor que uno que se ve retirado."""
    buzon.encolar_salida(escena, "encargo-1", "uno")
    corre("deshacer")

    retirado = buzon.conversacion(escena, "encargo-1")[-1]
    assert retirado["estado"] == "descartado" and "retirado" in retirado["detalle"]


def test_lo_que_ya_salio_no_se_puede_retirar(escena, capsys):
    """Y eso no se finge: salió de la máquina y ya no vuelve."""
    buzon.encolar_salida(escena, "encargo-1", "uno")
    escena.execute("UPDATE encargo_mensaje SET estado = 'enviado'")

    assert corre("deshacer") == 2
    assert "ya salió" in capsys.readouterr().err


def test_el_permiso_casa_con_lo_que_el_agente_ESCRIBE(escena, tmux_falso):
    """🔴 Una regla de `Bash` casa contra la cadena tecleada, no contra el archivo.

    El contrato le dice al agente que use `./encargo`, y la regla estaba escrita
    con la ruta absoluta: en modo `manual` se quedaba pidiendo permiso para lo
    único que sabe hacer, con nadie delante para dárselo. Se vio abriéndolo,
    porque leyendo el JSON las dos formas parecen la misma cosa.
    """
    import json

    from hub import constructor, entrevistador

    entrevistador.abrir_agente(escena, "encargo-1")
    for carpeta in (encargos.carpeta("encargo-1"),):
        constructor.acotar(carpeta)
        permisos = json.loads(
            (carpeta / ".claude" / "settings.json").read_text())["permissions"]
        assert "Bash(./encargo:*)" in permisos["allow"], (
            "sin la forma relativa, el agente pide permiso para su propia CLI")


# ── Su visto bueno, y la confianza por persona (decisión 236) ───────────────


def _ficha_sin_visto_bueno(con):
    ficha = encargos.cargar_ficha(con, "encargo-1")
    for fase, texto in (("dia", "abro a las siete"), ("duele", "los fiados"),
                        ("como_hoy", "libreta"), ("datos", "quién y cuánto"),
                        ("nombre", "La Esquina"), ("estilo", "claro")):
        ficha.responde(fase, texto)
    encargos.guardar_ficha(con, ficha)
    con.commit()


def test_sin_su_visto_bueno_no_se_propone(escena, tmp_path, capsys):
    """«Contestó preguntas y le llegó una página» es lo que esto evita."""
    _ficha_sin_visto_bueno(escena)

    assert corre("proponer", _informe(tmp_path)) == 2
    assert "visto bueno" in capsys.readouterr().err
    assert encargos.ver(escena, "encargo-1")["estado"] == "recogiendo"


def test_la_ficha_guia_el_visto_bueno_como_una_pregunta_suya(escena, capsys):
    _ficha_sin_visto_bueno(escena)
    corre("ficha")
    salida = capsys.readouterr().out
    assert "VISTO BUENO" in salida and "responde alcance" in salida


def test_de_confianza_el_plan_se_aprueba_solo_y_el_dueno_lo_recibe_como_aviso(escena, tmp_path):
    """El gate de n7 lo pone él por persona desde el hub; puesto, no se pregunta."""
    encargos.editar_persona(escena, 77, de_confianza="1")
    escena.commit()
    _ficha_completa(escena)

    assert corre("proponer", _informe(tmp_path)) == 0

    assert encargos.ver(escena, "encargo-1")["estado"] == "aprobado"
    assert encargos.ver(escena, "encargo-1")["plan_msg"] is None
    salientes = buzon.salientes(escena)
    al_dueno = [m for m in salientes if m["user_id"] == 1]
    assert al_dueno and al_dueno[-1]["clase"] == "texto" and "de confianza" in al_dueno[-1]["texto"]
    a_ella = [m["texto"] for m in salientes if m["user_id"] is None]
    assert any("Lo construyo y te aviso" in t for t in a_ella)


def test_sin_confianza_el_plan_sigue_esperando_al_dueno(escena, tmp_path):
    _ficha_completa(escena)
    corre("proponer", _informe(tmp_path))
    assert encargos.ver(escena, "encargo-1")["estado"] == "propuesta"


def test_el_plan_lleva_los_botones_de_aprobar_y_descartar(escena, tmp_path):
    """Decisión 237: decidir con un dedo, sobre ESE mensaje, igual que escribiendo."""
    _ficha_completa(escena)
    corre("proponer", _informe(tmp_path))
    plan = buzon.salientes(escena)[-1]
    import json
    assert plan["clase"] == "plan" and [d for _, d in json.loads(plan["botones"])] == ["aprobado", "no"]
    assert "Pulsa «Aprobar»" in plan["texto"]


def test_a_los_agentes_se_les_deniega_el_codigo_del_hub_y_el_buscar(escena):
    """Decisión 238: lo denegado se rechaza al instante y el agente sigue; lo no
    permitido pregunta, y sin nadie delante eso es quedarse parado. Dos
    constructores reales se atascaron queriendo leer el código del hub."""
    import json
    from hub import config, constructor, entrevistador

    for acotar in (entrevistador.acotar, constructor.acotar):
        acotar(encargos.carpeta("encargo-1"))
        reglas = json.loads((encargos.carpeta("encargo-1") / ".claude" / "settings.json").read_text())
        deny = reglas["permissions"]["deny"]
        assert any(str(config.RAIZ_REPO) in d and d.startswith("Read(") for d in deny)
        assert {"Bash(grep:*)", "Bash(find:*)"} <= set(deny)
        assert "Bash(./encargo:*)" in reglas["permissions"]["allow"]


def test_quitar_borra_solo_dentro_del_sitio(escena, capsys):
    """Decisión 238: el constructor no tiene `rm`; esto es lo que le sobra."""
    sitio = encargos.carpeta("encargo-1") / "sitio"
    sitio.mkdir(parents=True, exist_ok=True)
    (sitio / "girar.html").write_text("x"); (sitio / "estilo.css").write_text("x")
    fuera = encargos.carpeta("encargo-1") / "ficha.json"

    assert corre("quitar", "girar.html") == 0 and not (sitio / "girar.html").exists()
    assert corre("quitar", "../ficha.json") == 2 and fuera.exists()
    assert corre("quitar", "estilo.css") == 2 and (sitio / "estilo.css").exists()
    assert corre("quitar", "no-esta.html") == 2


# ── El boceto: el estilo se elige sobre SU pantalla (decisión 239) ──────────


def test_con_bosquejo_las_muestras_son_su_pantalla_en_seis_aires(escena, catalogo_generado, monkeypatch):
    """La misma pantalla de fiados en seis paletas le parece de otro sitio a
    quien tiene una tómbola; el boceto lo escribe el agente con sus palabras."""
    from pathlib import Path

    from hub import mirar

    pintados = []

    def captura_falsa(fuente, destino, **kw):
        pintados.append((fuente, kw.get("ancho")))
        Path(destino).write_bytes(b"png")
        return Path(destino)

    monkeypatch.setattr(mirar, "captura", captura_falsa)
    (encargos.carpeta("encargo-1") / "bosquejo.html").write_text(
        '<main><ul class="lista"><li>10 premios chicos</li></ul></main>')
    ficha = encargos.cargar_ficha(escena, "encargo-1"); ficha.responde("nombre", "GiraYGana")
    encargos.guardar_ficha(escena, ficha); escena.commit()

    assert corre("muestras") == 0

    encoladas = buzon.salientes(escena)
    assert "boceto" in encoladas[0]["texto"]
    fotos = [m for m in encoladas if m["clase"] == "muestras"]
    assert len(fotos) == 6 and all("bosquejo-" in m["adjunto"] for m in fotos)
    assert len(pintados) == 6 and all(a == 390 for _, a in pintados)
    vestido = Path(pintados[0][0]).read_text(encoding="utf-8")
    assert "GiraYGana" in vestido and 'class="hoja"' in vestido and ":root{" in vestido


def test_sin_bosquejo_las_muestras_de_estilo_se_niegan(escena, catalogo_generado, capsys):
    """🔴 Decisión 242. El contrato pedía el boceto antes de las muestras y el
    primer agente que llegó ahí se lo saltó: le mandó a una manicurista seis
    tiendas de fiados. Una valla se lee cada vez; un contrato, una."""
    (encargos.carpeta("encargo-1") / "bosquejo.html").unlink()
    assert corre("muestras") == 2
    assert "bosquejo.html" in capsys.readouterr().err
    assert not [m for m in buzon.salientes(escena) if m["clase"] == "muestras"]
    # El otro catálogo no depende del boceto: contesta otra pregunta.
    assert corre("muestras", "pantallas") == 0


def test_el_entrevistador_tiene_el_css_de_referencia_a_mano(escena):
    from hub import entrevistador

    carpeta = entrevistador.preparar(escena, "encargo-1")
    assert (carpeta / "estilo-referencia.css").is_file()
    assert "<main" in (carpeta / "bosquejo-ejemplo.html").read_text(encoding="utf-8")
    assert "bosquejo.html" in (carpeta / "INSTRUCCIONES.md").read_text(encoding="utf-8")


def test_mirar_pinta_todas_las_pantallas_de_la_maqueta(escena, monkeypatch, capsys):
    """🔴 Decisión 243. La maqueta es navegable: varias pantallas. Mirar sólo la
    portada dejaría sin ver justo la que está rota."""
    from hub import mirar

    pintadas = []

    def captura_falsa(fuente, destino, **kw):
        pintadas.append((Path(fuente).name, kw.get("ancho")))
        Path(destino).parent.mkdir(parents=True, exist_ok=True)
        Path(destino).write_bytes(b"png")
        return Path(destino)

    monkeypatch.setattr(mirar, "captura", captura_falsa)
    sitio = encargos.carpeta("encargo-1") / "sitio"
    sitio.mkdir(parents=True, exist_ok=True)
    for nombre in ("index.html", "clientas.html", "cuentas.html"):
        (sitio / nombre).write_text("<main></main>", encoding="utf-8")

    assert corre("mirar") == 0
    assert {n for n, _ in pintadas} == {"index.html", "clientas.html", "cuentas.html"}
    assert pintadas[0][0] == "index.html", "la portada va primero"
    assert "clientas.html" in capsys.readouterr().out


def test_los_contratos_piden_que_se_vea_bien_en_el_telefono_y_en_la_pc():
    """Petición suya del 19-sep: él lo revisa desde la PC. `mirar` ya pinta a
    1000 px; el contrato tiene que pedir que esa captura se mire."""
    from hub import constructor, implementador

    assert "en la PC" in constructor.INSTRUCCIONES and "1000 px" in constructor.INSTRUCCIONES
    assert "en la\n   PC" in implementador.INSTRUCCIONES or "en la PC" in implementador.INSTRUCCIONES.replace("\n   ", " ")
    assert (1000, "ancho") in encargos_cli.ANCHOS
