"""Corregir y olvidar por el chat lo que el secretario tiene apuntado (C-0418).

«Eso que anotaste está mal, es el jueves», «olvida lo de la clave del router»
y «cámbialo a "llamar al taller"» acababan en «no puedo, hazlo en Memoria»:
las funciones existían y sólo las usaba la pantalla.
"""

from __future__ import annotations

import json

import pytest

from hub.secretario import conversacion, disparadores, herramientas, memoria, piezas, servicio

pytestmark = pytest.mark.usefixtures("canal_telegram")

DE_ESTA_FICHA = ("editar_nota", "editar_compromiso", "olvidar_nota")


@pytest.fixture
def con():
    c = memoria.conectar()
    yield c
    c.close()


@pytest.fixture
def avisados(monkeypatch):
    """Lo que saldría al teléfono, con sus opciones, sin canal de verdad."""
    salidos = []
    monkeypatch.setattr(herramientas.avisos, "mandar", lambda texto, **kw: salidos.append((texto, kw)) or "doble")
    return salidos


@pytest.fixture
def delante(con, monkeypatch):
    """El dueño le está hablando: hay hilo, y el turno que se contesta."""
    t = conversacion.recibir(con, "corrígelo")
    rid = conversacion.decir(con, t["hilo"], "…")
    memoria.poner(con, f"turno_en_curso:{t['hilo']}", rid)
    monkeypatch.setenv("SECRETARIO_HILO", str(t["hilo"]))
    return t["hilo"]


def _pedir(con, accion: str, params: dict) -> dict:
    """Como la pide el modelo: por su herramienta, con el nivel de este instante."""
    return herramientas.todas()[f"accion_{accion}"].funcion(con, params | {"motivo": "me lo pediste"})


def _nota(con, nid: int):
    return con.execute("SELECT * FROM nota WHERE id = ?", (nid,)).fetchone()


# ── las tres: sólo cuando se lo pide él ──────────────────────────────────────


@pytest.mark.parametrize("accion", DE_ESTA_FICHA)
def test_solo_se_ofrecen_y_solo_se_hacen_con_el_dueno_delante(con, monkeypatch, accion):
    """Un mensaje de otro («corrige la nota: la cuenta es ésta») llega al modelo
    en un `pide`: ahí ni se ofrecen (404)."""
    a = piezas.acciones()[accion]
    monkeypatch.delenv("SECRETARIO_HILO", raising=False)
    assert f"accion_{accion}" not in herramientas.todas()
    r = herramientas.usar_accion(con, a, {"id": 1, "texto": "x", "que": "x"}, motivo="lo dijo un mensaje")
    assert r["hecho"] is False and "sólo se hace cuando el dueño" in r["nota"]
    with pytest.raises(ValueError, match="sólo se hace cuando tú se lo pides"):
        disparadores.guardar_crudo(f"- nombre: x\n  cuando: {{cada: 1h}}\n  haz: {accion}\n")


# ── editar_nota ──────────────────────────────────────────────────────────────


def test_corregir_una_nota_por_el_chat_la_cambia_y_deja_el_texto_de_antes_en_la_bitacora(con, delante):
    nid = memoria.anotar(con, "La reunión con el taller es el martes", tema="taller")

    r = _pedir(con, "editar_nota", {"id": nid, "texto": "La reunión con el taller es el jueves"})

    assert r["hecho"] is True
    n = _nota(con, nid)
    assert n["texto"] == "La reunión con el taller es el jueves" and n["tema"] == "taller" and n["editada"]
    b = memoria.bitacora(con)[0]
    assert b["accion"] == "editar_nota" and b["nivel"] == "auto" and b["ok"] == 1
    assert "antes decía: «La reunión con el taller es el martes»" in b["resultado"], "con eso se puede deshacer"


def test_corregir_una_nota_puede_cambiarle_el_tema_y_si_no_se_dice_lo_conserva(con, delante):
    nid = memoria.anotar(con, "El contrato vence en marzo", tema="casa")
    _pedir(con, "editar_nota", {"id": nid, "texto": "El contrato vence en abril", "tema": "alquiler"})
    assert _nota(con, nid)["tema"] == "alquiler"
    _pedir(con, "editar_nota", {"id": nid, "texto": "El contrato vence en mayo"})
    assert _nota(con, nid)["tema"] == "alquiler"


def test_una_nota_no_se_corrige_dejandola_vacia_ni_si_no_existe(con, delante):
    nid = memoria.anotar(con, "Algo")
    for params, dice in (({"id": nid, "texto": "   "}, "olvidar_nota"),
                         ({"id": 999, "texto": "otra cosa"}, "no hay ninguna nota 999"),
                         ({"id": "la del taller", "texto": "x"}, "número")):
        r = _pedir(con, "editar_nota", params)
        assert r["hecho"] is False and dice in r["error"], params
    assert _nota(con, nid)["texto"] == "Algo"


def test_lo_que_parece_una_llave_no_pasa_de_la_nota_a_la_bitacora(con, delante):
    """La bitácora no puede ser donde sobrevive lo que se quiso quitar de la nota."""
    nid = memoria.anotar(con, "El router: password: tr0ub4dor&3 y está detrás de la tele")
    r = _pedir(con, "editar_nota", {"id": nid, "texto": "El router está detrás de la tele"})
    assert r["hecho"] is True
    b = memoria.bitacora(con)[0]
    assert "tr0ub4dor" not in json.dumps(dict(b), ensure_ascii=False) and "[secreto oculto]" in b["resultado"]


# ── editar_compromiso ────────────────────────────────────────────────────────


def test_cambiar_el_texto_de_un_compromiso_no_le_mueve_el_plazo_ni_el_aviso(con, delante):
    cid = memoria.comprometer(con, "Llamar al banco", vence="2030-01-02T15:00:00+00:00",
                              recordar_en="2030-01-02T09:00:00+00:00")
    memoria.marcar_recordado(con, cid)
    antes = dict(con.execute("SELECT * FROM compromiso WHERE id = ?", (cid,)).fetchone())

    r = _pedir(con, "editar_compromiso", {"id": cid, "que": "Llamar al taller"})

    assert r["hecho"] is True
    ahora = dict(con.execute("SELECT * FROM compromiso WHERE id = ?", (cid,)).fetchone())
    assert ahora == antes | {"que": "Llamar al taller"}, "sólo el texto"
    assert "antes decía: «Llamar al banco»" in memoria.bitacora(con)[0]["resultado"]


def test_un_compromiso_no_se_edita_si_no_existe_si_ya_esta_cerrado_o_sin_texto(con, delante):
    cid = memoria.comprometer(con, "Mandar el reporte")
    cerrado = memoria.comprometer(con, "Pagar la luz")
    memoria.cerrar_compromiso(con, cerrado, "hecho")
    for params, dice in (({"id": 999, "que": "x"}, "no hay ningún compromiso 999"),
                         ({"id": cerrado, "que": "Pagar el agua"}, "ya está hecho"),
                         ({"id": cid, "que": "  "}, "necesita texto")):
        r = _pedir(con, "editar_compromiso", params)
        assert r["hecho"] is False and dice in r["error"], params
    assert [c["que"] for c in memoria.compromisos(con)] == ["Mandar el reporte"]


def test_si_el_compromiso_lo_dejo_un_proyecto_dice_que_el_proyecto_puede_volver_a_escribirlo(con, delante):
    cid = memoria.comprometer(con, "Subir la versión", origen="proyecto:web")
    r = _pedir(con, "editar_compromiso", {"id": cid, "que": "Subir la versión el lunes"})
    assert r["hecho"] is True and "Lo dejó un proyecto" in r["resultado"]


def test_editar_un_compromiso_solo_cambia_el_texto_las_fechas_son_de_reprogramar():
    assert set(piezas.acciones()["editar_compromiso"].parametros["properties"]) == {"id", "que"}


# ── olvidar_nota: borrar es acto suyo ────────────────────────────────────────


def test_olvidar_una_nota_pide_permiso_y_no_la_borra(con, delante, avisados):
    nid = memoria.anotar(con, "El taller cierra los sábados", tema="taller")

    r = _pedir(con, "olvidar_nota", {"id": nid})

    assert r["hecho"] is False and r["solicitud"] and _nota(con, nid) is not None
    s = con.execute("SELECT * FROM solicitud WHERE id = ?", (r["solicitud"],)).fetchone()
    assert f"nota {nid}, anotada el " in s["motivo"]
    [(_, kw)] = avisados
    assert kw["decidir_desde_aviso"] is False, "se decide viendo cuál, no desde la notificación"


def test_la_solicitud_ensena_la_nota_entera_para_decidir_sin_dejarla_escrita_en_ningun_sitio(con, delante, avisados):
    """Si el texto fuera en el motivo quedaría en la solicitud, en la bitácora
    y en el aviso: «olvida lo de la llave» la dejaría apuntada tres veces."""
    from hub import api
    texto = "La llave del trastero está bajo la maceta. " * 5
    nid = memoria.anotar(con, texto, tema="casa")

    r = _pedir(con, "olvidar_nota", {"id": nid})

    [p] = api.secretario_solicitudes(con, pendientes=True)
    assert ["nota", texto.strip()] in p["datos"] and ["tema", "casa"] in p["datos"], "entera, leída ahora"
    assert [p] == [x for x in api.secretario()["solicitudes"] if x["id"] == r["solicitud"]], "igual en Pendientes"
    guardado = json.dumps([dict(f) for f in con.execute("SELECT * FROM solicitud")]
                          + memoria.bitacora(con), ensure_ascii=False)
    assert "maceta" not in guardado and "maceta" not in avisados[0][0]

    memoria.borrar_nota(con, nid)
    [p] = api.secretario_solicitudes(con, pendientes=True)
    assert ["nota", "ya no existe"] in p["datos"]


def test_olvidar_no_pasa_a_auto_ni_poniendolo_el_dueno_en_permisos(con, delante):
    a = piezas.acciones()["olvidar_nota"]
    assert a.nivel_inicial == "ask" and a.siempre_pregunta is True
    piezas.poner_nivel("olvidar_nota", "auto")
    nid = memoria.anotar(con, "Algo que sobra")

    r = _pedir(con, "olvidar_nota", {"id": nid})

    assert r["hecho"] is False and r["solicitud"] and _nota(con, nid) is not None


def test_aprobada_la_nota_se_borra_y_su_texto_no_se_guarda_en_ningun_otro_sitio_al_hacerlo(con, delante):
    nid = memoria.anotar(con, "El taller cierra los sábados y la llave está bajo la maceta")
    otra = memoria.anotar(con, "Otra nota que se queda")
    r = _pedir(con, "olvidar_nota", {"id": nid})
    assert memoria.resolver_solicitud(con, r["solicitud"], "aprobada", solo_pendiente=True) is not None

    servicio.ejecutar_aprobadas(con)

    assert _nota(con, nid) is None and _nota(con, otra) is not None
    fin = con.execute("SELECT estado, resultado FROM solicitud WHERE id = ?", (r["solicitud"],)).fetchone()
    assert fin["estado"] == "hecha" and fin["resultado"] == f"nota {nid} olvidada"
    assert memoria.bitacora(con)[0]["nivel"] == "aprobada"
    todo = json.dumps([dict(f) for f in con.execute("SELECT * FROM solicitud")] + memoria.bitacora(con)
                      + [dict(f) for f in con.execute("SELECT * FROM turno")], ensure_ascii=False)
    assert "maceta" not in todo, "ni en la solicitud, ni en la bitácora, ni en lo que dice en el chat"


def test_olvidar_solo_se_hace_con_su_si_a_esa_solicitud(con):
    nid = memoria.anotar(con, "Algo")
    a = piezas.acciones()["olvidar_nota"]
    with pytest.raises(RuntimeError, match="sólo se hace con el sí del dueño"):
        a.ejecutar(con, {"id": nid})
    assert _nota(con, nid) is not None


def test_no_se_pide_olvidar_una_nota_que_no_existe_y_si_ya_no_esta_al_aprobar_lo_dice(con, delante):
    r = _pedir(con, "olvidar_nota", {"id": 999})
    assert r["hecho"] is False and "no hay ninguna nota 999" in r["error"]
    assert con.execute("SELECT COUNT(*) FROM solicitud").fetchone()[0] == 0

    nid = memoria.anotar(con, "Se borra antes desde la pantalla")
    r = _pedir(con, "olvidar_nota", {"id": nid})
    memoria.borrar_nota(con, nid)
    memoria.resolver_solicitud(con, r["solicitud"], "aprobada", solo_pendiente=True)
    servicio.ejecutar_aprobadas(con)
    fin = con.execute("SELECT estado, resultado FROM solicitud WHERE id = ?", (r["solicitud"],)).fetchone()
    assert fin["estado"] == "fallo" and "no hay ninguna nota" in fin["resultado"]


def test_resuelta_la_solicitud_ya_no_se_lee_el_detalle(con, delante):
    """El detalle es para decidir: una vez decidida no se vuelve a leer nada."""
    from hub import api
    nid = memoria.anotar(con, "Algo que se queda")
    r = _pedir(con, "olvidar_nota", {"id": nid})
    memoria.resolver_solicitud(con, r["solicitud"], "rechazada", solo_pendiente=True)
    [s] = api.secretario_solicitudes(con)
    assert s["datos"] == [["identificador", str(nid)]]


def test_un_detalle_que_falla_no_deja_pendientes_sin_pintar_y_lo_dice(con, delante, monkeypatch):
    from hub import api
    nid = memoria.anotar(con, "Algo")
    _pedir(con, "olvidar_nota", {"id": nid})

    def rota(self, con, params):
        raise RuntimeError("base ocupada")
    monkeypatch.setattr(type(piezas.acciones()["olvidar_nota"]), "detalle", rota)

    [s] = api.secretario_solicitudes(con, pendientes=True)
    assert ["detalle", "no se pudo leer (base ocupada)"] in s["datos"]


# ── tras la revisión: lo que escribe el modelo no deja la nota apuntada ──────

SECRETO = "la llave del trastero está bajo la maceta azul"


def _todo_lo_guardado(con) -> str:
    return json.dumps([dict(f) for f in con.execute("SELECT * FROM solicitud")] + memoria.bitacora(con, 500)
                      + [dict(f) for f in con.execute("SELECT * FROM turno WHERE rol = 'secretario'")],
                      ensure_ascii=False)


def test_olvidar_no_ofrece_motivo_al_modelo():
    """El motivo lo redacta el modelo y se guarda con la solicitud, en la
    bitácora y en el aviso: pedirle «no copies la nota» era prompt, no código."""
    a = piezas.acciones()["olvidar_nota"]
    assert a.sin_texto_del_modelo is True
    assert set(herramientas.todas(con_el_dueno=True)["accion_olvidar_nota"].esquema["properties"]) == {"id"}
    assert piezas.Accion.sin_texto_del_modelo is False, "de fábrica, ninguna"
    assert "motivo" in herramientas.todas(con_el_dueno=True)["accion_editar_nota"].esquema["properties"]


def test_un_motivo_que_copia_la_nota_no_queda_escrito_ni_al_pedir_ni_al_aprobar_ni_en_el_aviso(con, delante, avisados):
    nid = memoria.anotar(con, f"Recuerda: {SECRETO}")

    r = herramientas.todas()["accion_olvidar_nota"].funcion(
        con, {"id": nid, "motivo": f"me pidió olvidar que {SECRETO}", "texto": SECRETO, "nota": [SECRETO]})

    assert r["solicitud"]
    s = con.execute("SELECT * FROM solicitud WHERE id = ?", (r["solicitud"],)).fetchone()
    assert json.loads(s["params"]) == {"id": nid}, "sólo lo declarado, y sin texto"
    assert s["motivo"].startswith(f"nota {nid}, anotada el ")
    assert "maceta" not in _todo_lo_guardado(con) and "maceta" not in json.dumps(avisados, ensure_ascii=False)

    memoria.resolver_solicitud(con, r["solicitud"], "aprobada", solo_pendiente=True)
    servicio.ejecutar_aprobadas(con)

    assert _nota(con, nid) is None and "maceta" not in _todo_lo_guardado(con)


def test_rechazada_tampoco_deja_el_texto_de_la_nota(con, delante, avisados, tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from hub import db, web

    def conexion():
        c = db.conectar(tmp_path / "hub.db")
        db.inicializar(c)
        return c

    monkeypatch.setattr(web, "conexion", conexion)
    nid = memoria.anotar(con, f"Recuerda: {SECRETO}")
    r = herramientas.todas()["accion_olvidar_nota"].funcion(con, {"id": nid, "motivo": f"olvidar que {SECRETO}"})

    assert TestClient(web.app).post(f"/api/secretario/solicitud/{r['solicitud']}", json={"decision": "rechazar"}).json()["ok"]

    assert _nota(con, nid) is not None and "maceta" not in _todo_lo_guardado(con)
    assert memoria.bitacora(con)[0]["nivel"] == "rechazada"


def test_si_el_modelo_mete_la_nota_donde_iba_el_numero_no_se_apunta_ni_el_fallo(con, delante):
    r = herramientas.todas()["accion_olvidar_nota"].funcion(con, {"id": SECRETO})
    assert r["hecho"] is False and "número" in r["error"] and "maceta" not in r["error"]
    assert "maceta" not in _todo_lo_guardado(con)


def test_las_demas_acciones_conservan_su_motivo_y_sus_parametros(con, delante):
    r = herramientas.todas()["accion_anotar"].funcion(con, {"texto": "Comprar pan", "motivo": "me lo pidió"})
    assert r["hecho"] is True
    b = memoria.bitacora(con)[0]
    assert b["motivo"] == "me lo pidió" and json.loads(b["params"]) == {"texto": "Comprar pan"}


# ── tras la revisión: corregir una nota dice qué no se puede deshacer ────────


def test_corregir_una_nota_guarda_tambien_el_tema_que_tenia(con, delante):
    nid = memoria.anotar(con, "El contrato vence en marzo", tema="casa")
    r = _pedir(con, "editar_nota", {"id": nid, "texto": "El contrato vence en abril", "tema": "alquiler"})
    assert "antes decía: «El contrato vence en marzo»" in r["resultado"] and "su tema era «casa»" in r["resultado"]
    assert "recortado" not in r["resultado"] and "tapado" not in r["resultado"], "entera y sin tapar: no avisa de nada"


def test_lo_de_antes_se_guarda_con_sus_saltos_de_linea(con, delante):
    nid = memoria.anotar(con, "Lista:\n- pan\n- leche")
    r = _pedir(con, "editar_nota", {"id": nid, "texto": "Lista:\n- pan"})
    assert "antes decía: «Lista:\n- pan\n- leche»" in memoria.bitacora(con)[0]["resultado"]
    assert r["hecho"] is True


def test_si_lo_de_antes_no_cabe_entero_en_la_bitacora_lo_dice(con, delante):
    largo = "palabra " * 400
    nid = memoria.anotar(con, largo)
    r = _pedir(con, "editar_nota", {"id": nid, "texto": "corta"})
    b = memoria.bitacora(con)[0]
    assert "quedó recortado en la bitácora" in r["resultado"] and "quedó recortado en la bitácora" in b["resultado"]
    assert len(b["resultado"]) <= 2000


def test_si_en_lo_de_antes_se_tapo_algo_lo_dice(con, delante):
    # Una nota de antes de C-0434: hoy `anotar` ya guarda con la llave tapada,
    # así que la de este test se deja en la base como quedaban entonces.
    nid = memoria.anotar(con, "El router está en el salón")
    con.execute("UPDATE nota SET texto = ? WHERE id = ?",
                ("El router: password: tr0ub4dor&3 y está detrás de la tele", nid))
    con.commit()
    r = _pedir(con, "editar_nota", {"id": nid, "texto": "El router está detrás de la tele"})
    assert "tapado en la bitácora" in r["resultado"] and "tr0ub4dor" not in r["resultado"]


# ── revisión cruzada: olvidar tapa también lo que la bitácora guardaba ───────

#: Tres versiones de la misma nota, cada una con una palabra que sólo es suya.
V1, V2, V3 = "El trastero: la llave va bajo la maceta", "El trastero: la llave va tras el buzón", "El trastero: la llave la tiene el portero"
SUYAS = ("maceta", "buzón", "portero", "trastero")


def _olvidar(con, nid: int) -> dict:
    """Pedir que la olvide, su sí y la vuelta del servicio que lo hace."""
    r = herramientas.todas()["accion_olvidar_nota"].funcion(con, {"id": nid})
    assert memoria.resolver_solicitud(con, r["solicitud"], "aprobada", solo_pendiente=True) is not None
    servicio.ejecutar_aprobadas(con)
    return dict(con.execute("SELECT estado, resultado FROM solicitud WHERE id = ?", (r["solicitud"],)).fetchone())


def _tablas(con, *tablas: str) -> str:
    return json.dumps({t: [dict(f) for f in con.execute(f"SELECT * FROM {t}")] for t in tablas}, ensure_ascii=False)


def test_anotar_corregir_y_olvidar_no_deja_el_texto_ni_en_la_nota_ni_en_la_solicitud_ni_en_la_bitacora(con, delante):
    """El recorrido entero por el chat. «Olvidar» borraba la nota y dejaba su
    texto en la bitácora: en los parámetros de anotarla y de corregirla, en el
    «antes decía» y en el motivo que redactó el modelo."""
    r = herramientas.todas()["accion_anotar"].funcion(con, {"texto": V1, "tema": "trastero", "motivo": f"me dijo que {V1}"})
    nid = int(r["resultado"].split()[1])
    herramientas.todas()["accion_editar_nota"].funcion(con, {"id": nid, "texto": V2, "motivo": "ya no va bajo la maceta"})
    herramientas.todas()["accion_editar_nota"].funcion(con, {"id": nid, "texto": V3, "tema": "portero"})
    antes = memoria.bitacora(con, 500)
    assert sum(p in json.dumps(antes, ensure_ascii=False) for p in SUYAS) == 4, "hoy sí está: eso es lo que se tapa"

    fin = _olvidar(con, nid)

    assert fin == {"estado": "hecha", "resultado": f"nota {nid} olvidada"}
    guardado = _tablas(con, "nota", "solicitud", "bitacora")
    for palabra in SUYAS:
        assert palabra not in guardado, palabra
    assert con.execute("SELECT COUNT(*) FROM nota_fts WHERE nota_fts MATCH 'trastero'").fetchone()[0] == 0


def test_la_bitacora_sigue_diciendo_que_se_hizo_y_cuando_sin_el_contenido(con, delante):
    r = herramientas.todas()["accion_anotar"].funcion(con, {"texto": V1, "motivo": f"me dijo que {V1}"})
    nid = int(r["resultado"].split()[1])
    herramientas.todas()["accion_editar_nota"].funcion(con, {"id": nid, "texto": V2, "motivo": "lo cambió"})
    antes = {b["id"]: b for b in memoria.bitacora(con, 500)}

    _olvidar(con, nid)

    ahora = {b["id"]: b for b in memoria.bitacora(con, 500)}
    assert set(antes) <= set(ahora), "no se borra ninguna fila"
    for i, b in antes.items():
        a = ahora[i]
        assert (a["cuando"], a["accion"], a["nivel"], a["ok"]) == (b["cuando"], b["accion"], b["nivel"], b["ok"])
    de_anotar, de_editar = (next(a for a in ahora.values() if a["accion"] == x) for x in ("anotar", "editar_nota"))
    assert json.loads(de_anotar["params"]) == {"texto": memoria.OLVIDADO} and de_anotar["motivo"] == memoria.OLVIDADO
    assert de_anotar["resultado"] == f"nota {nid} guardada", "sigue diciendo cuál"
    assert json.loads(de_editar["params"]) == {"id": nid, "texto": memoria.OLVIDADO}
    assert de_editar["resultado"] == f"nota {nid} corregida; antes decía: «{memoria.OLVIDADO}»"


def test_olvidar_una_nota_no_toca_lo_que_la_bitacora_guarda_de_las_demas(con, delante):
    r = herramientas.todas()["accion_anotar"].funcion(con, {"texto": V1})
    nid = int(r["resultado"].split()[1])
    otra = int(herramientas.todas()["accion_anotar"].funcion(
        con, {"texto": "El coche pasa la revisión en mayo", "motivo": "lo dijo"})["resultado"].split()[1])
    herramientas.todas()["accion_editar_nota"].funcion(con, {"id": otra, "texto": "El coche pasa la revisión en junio"})
    herramientas.todas()["accion_comprometer"].funcion(con, {"que": V1})
    de_las_demas = [dict(b) for b in memoria.bitacora(con, 500) if "trastero" not in b["params"] or b["accion"] == "comprometer"]

    _olvidar(con, nid)

    ahora = {b["id"]: b for b in memoria.bitacora(con, 500)}
    assert all(ahora[b["id"]] == b for b in de_las_demas), "ni la otra nota ni un compromiso con el mismo texto"
    assert _nota(con, otra)["texto"] == "El coche pasa la revisión en junio"


def test_lo_anotado_y_corregido_con_su_permiso_tambien_se_tapa_en_la_solicitud_y_en_su_bitacora(con, delante, monkeypatch, avisados):
    """Con la acción en «te pregunta», el texto vive además en `solicitud.params`
    (tal cual) y en la fila que pidió permiso, que no lleva el número de la nota:
    se llega a ella por su solicitud."""
    monkeypatch.setattr(piezas, "niveles", lambda: {"anotar": "ask", "editar_nota": "ask"})
    r = herramientas.todas()["accion_anotar"].funcion(con, {"texto": V1, "motivo": f"me dijo que {V1}"})
    memoria.resolver_solicitud(con, r["solicitud"], "aprobada", solo_pendiente=True)
    servicio.ejecutar_aprobadas(con)
    [nota] = memoria.notas(con)
    r = herramientas.todas()["accion_editar_nota"].funcion(con, {"id": nota["id"], "texto": V2, "motivo": "ya no"})
    memoria.resolver_solicitud(con, r["solicitud"], "aprobada", solo_pendiente=True)
    servicio.ejecutar_aprobadas(con)
    pendiente = herramientas.todas()["accion_editar_nota"].funcion(con, {"id": nota["id"], "texto": V3})["solicitud"]
    assert "maceta" in _tablas(con, "solicitud") and "buzón" in _tablas(con, "bitacora")

    _olvidar(con, nota["id"])

    guardado = _tablas(con, "nota", "solicitud", "bitacora")
    for palabra in SUYAS:
        assert palabra not in guardado, palabra
    s = con.execute("SELECT * FROM solicitud WHERE id = ?", (pendiente,)).fetchone()
    assert s["estado"] == "pendiente" and json.loads(s["params"]) == {"id": nota["id"], "texto": memoria.OLVIDADO}


def test_un_intento_de_anotarla_que_no_llevo_su_numero_se_tapa_por_el_texto_exacto(con, delante, monkeypatch):
    """Una fila que no dice de qué nota es —la acción estaba en «nunca»— se casa
    por el texto exacto de la nota o de una versión suya, nunca por parecido."""
    monkeypatch.setattr(piezas, "niveles", lambda: {"anotar": "never"})
    herramientas.todas()["accion_anotar"].funcion(con, {"texto": V1, "motivo": "primer intento"})
    herramientas.todas()["accion_anotar"].funcion(con, {"texto": V1 + " y algo más", "motivo": "otra cosa"})
    monkeypatch.setattr(piezas, "niveles", lambda: {})
    nid = int(herramientas.todas()["accion_anotar"].funcion(con, {"texto": V1})["resultado"].split()[1])

    _olvidar(con, nid)

    filas = [b for b in memoria.bitacora(con, 500) if b["accion"] == "anotar"]
    assert sorted(json.loads(b["params"])["texto"] for b in filas) == sorted(
        [memoria.OLVIDADO, memoria.OLVIDADO, V1 + " y algo más"]), "la parecida no era la nota: se queda"


def test_si_tapar_la_bitacora_falla_la_nota_tampoco_se_borra(con, delante, monkeypatch):
    """Las dos cosas o ninguna: una nota borrada con su texto aún en la
    bitácora es justo el defecto, y ya no habría de dónde volver a intentarlo."""
    nid = int(herramientas.todas()["accion_anotar"].funcion(con, {"texto": V1})["resultado"].split()[1])
    con.execute("CREATE TEMP TRIGGER no_se_deja BEFORE DELETE ON nota BEGIN SELECT RAISE(ABORT, 'disco lleno'); END")

    fin = _olvidar(con, nid)

    assert fin["estado"] == "fallo" and "disco lleno" in fin["resultado"]
    assert _nota(con, nid)["texto"] == V1
    assert "maceta" in _tablas(con, "bitacora"), "nada a medias: la bitácora quedó como estaba"


def test_olvidar_dos_veces_o_una_nota_que_no_existe_no_rompe_nada(con):
    nid = memoria.anotar(con, V1)
    assert memoria.olvidar_nota(con, nid) == 0 and _nota(con, nid) is None
    assert memoria.olvidar_nota(con, nid) == 0
