"""Sus datos para los trámites: «mis datos» (C-0201, decisión 382).

Se dan una vez y sirven para todos sus proyectos: lo que el secretario
encuentra queda propuesto, sólo su botón lo confirma, lo que lo saca a otro
sitio pide permiso y una investigación no lo lleva a la web. Viven en un
archivo propio (600), fuera de `memoria.db` y de sus copias, para que
olvidarlo sea olvidarlo.

Los valores son inventados: un identificador que no es de ningún sitio y una
calle que no existe.
"""

from __future__ import annotations

import os
import stat
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient

from hub import api, config, db, web
from hub.secretario import asuntos, herramientas, investigar, memoria, misdatos, piezas
from hub.secretario.piezas import Accion

ID_FISCAL = "IDF000000EJ1"
DOMICILIO = "Calle Falsa 123, Springfield"


@pytest.fixture
def con():
    h = db.conectar()   # la del hub existe donde corre el secretario
    db.inicializar(h)
    h.close()
    c = memoria.conectar()
    yield c
    c.close()


@pytest.fixture
def cliente():
    return TestClient(web.app)


@pytest.fixture(autouse=True)
def _sin_telefono(monkeypatch):
    """Lo que pide permiso avisaría al teléfono: aquí no sale nada."""
    monkeypatch.setattr(herramientas.avisos, "mandar", lambda *a, **k: None)


def _proponer(con, campo, valor, fuente="me lo dijiste en el chat"):
    return herramientas.usar_accion(con, piezas.acciones()["proponer_dato"],
                                    {"campo": campo, "valor": valor, "fuente": fuente})


def _post(cliente, campo, como, **datos):
    return cliente.post(f"/secretario/datos/{campo}", data={"como": como, **datos}, follow_redirects=False)


def _aviso(r) -> str:
    """El aviso con que vuelve una redirección."""
    assert r.status_code == 303, (r.status_code, r.text[:300])
    return parse_qs(urlsplit(r.headers["location"]).query).get("aviso", [""])[0]


def _asunto(con, campo):
    return next((a for a in asuntos.reunir(con, clases=("dato",), todos=True).asuntos
                 if a.clave == f"dato:{campo}"), None)


def _todo_lo_de_la_memoria(con) -> str:
    return "\n".join(con.iterdump())


# ── propuesto, confirmado ─────────────────────────────────────────────────────

def test_un_dato_propuesto_pide_confirmacion_y_no_se_usa_hasta_confirmarlo(con, cliente):
    r = _proponer(con, "id_fiscal", ID_FISCAL, "tu CV en la carpeta de documentos")
    assert r["hecho"] and "propuesto" in r["resultado"]
    assert misdatos.leer()["id_fiscal"]["estado"] == "propuesto"
    assert misdatos.confirmados() == {}
    # El secretario lo ve como propuesto, no como algo que puede usar.
    vista = herramientas.todas()["mis_datos"].funcion(con, {})
    assert vista["confirmados"] == [] and [x["valor"] for x in vista["propuestos"]] == [ID_FISCAL]
    # Le espera en sus asuntos, de los que sólo él contesta, con su puerta.
    a = _asunto(con, "id_fiscal")
    assert a and a.clase == "dato" and a.estado == "nueva" and a.solo_el
    assert a.enlace == "/secretario?p=datos" and a.opciones == ("confirmar", "corregir", "olvidar")
    assert ID_FISCAL not in a.texto + a.detalle

    # Un «sí» suyo en el chat no lo confirma: no hay acción que lo haga.
    assert not any("confirmar" in i and "dato" in i for i in piezas.acciones())
    assert _post(cliente, "id_fiscal", "confirmar", visto=ID_FISCAL).status_code == 303
    assert misdatos.confirmados() == {"id_fiscal": ID_FISCAL}
    assert _asunto(con, "id_fiscal").estado == "resuelta"


def test_un_dato_confirmado_sirve_para_otro_proyecto_sin_volver_a_preguntar(con, cliente):
    _proponer(con, "domicilio_fiscal", DOMICILIO, "el registro de la tienda")
    _post(cliente, "domicilio_fiscal", "confirmar", visto=DOMICILIO)
    assert _asunto(con, "domicilio_fiscal").estado == "resuelta"

    # Otro proyecto lo encuentra igual (otra caja, otros espacios): no se le pregunta.
    r = _proponer(con, "domicilio_fiscal", "  calle falsa   123,  SPRINGFIELD ", "el alta del proyecto nuevo")
    assert r["hecho"] and "ya estaba confirmado" in r["resultado"]
    assert _asunto(con, "domicilio_fiscal").estado == "resuelta"
    d = misdatos.leer()["domicilio_fiscal"]
    assert (d["valor"], d["estado"], d["fuente"]) == (DOMICILIO, "confirmado", "el registro de la tienda")
    assert "propuesta" not in d

    # Uno distinto no pisa el confirmado: queda al lado hasta que él elija.
    _proponer(con, "domicilio_fiscal", "Avenida Siempre Viva 742", "un correo de envío")
    d = misdatos.leer()["domicilio_fiscal"]
    assert d["valor"] == DOMICILIO and d["propuesta"]["valor"] == "Avenida Siempre Viva 742"
    assert misdatos.confirmados()["domicilio_fiscal"] == DOMICILIO
    assert _asunto(con, "domicilio_fiscal").estado == "nueva"
    # «Dejar el de antes» confirma el viejo y conserva de dónde salió.
    _post(cliente, "domicilio_fiscal", "corregir", valor=DOMICILIO)
    d = misdatos.leer()["domicilio_fiscal"]
    assert (d["valor"], d["fuente"], d.get("propuesta")) == (DOMICILIO, "el registro de la tienda", None)



def test_confirmar_confirma_lo_que_viste_y_no_lo_que_llego_mientras_mirabas(con, cliente):
    """C-0430: el botón mandaba sólo «confirmar» y se confirmaba lo propuesto
    al pulsar. Si llegaba otro valor entre ver y pulsar —el secretario corre
    en paralelo y la pantalla no recarga—, quedaba confirmado sin verlo."""
    _proponer(con, "domicilio_fiscal", "Calle Vista 1", "un correo")
    html = cliente.get("/secretario?p=datos").text
    assert 'name="visto" value="Calle Vista 1"' in html
    _proponer(con, "domicilio_fiscal", "Calle Otra 99", "otra fuente")   # mientras lo mira

    aviso = _aviso(_post(cliente, "domicilio_fiscal", "confirmar", visto="Calle Vista 1"))
    assert "cambió mientras lo mirabas" in aviso.lower()
    assert misdatos.confirmados() == {}
    assert misdatos.leer()["domicilio_fiscal"]["valor"] == "Calle Otra 99"
    assert _asunto(con, "domicilio_fiscal").estado != "resuelta"

    # Lo que ve ahora sí se confirma.
    _post(cliente, "domicilio_fiscal", "confirmar", visto="Calle Otra 99")
    assert misdatos.confirmados() == {"domicilio_fiscal": "Calle Otra 99"}


def test_usar_el_nuevo_confirma_la_propuesta_que_viste_y_no_otra(con, cliente):
    misdatos.confirmar("domicilio_fiscal", DOMICILIO)
    _proponer(con, "domicilio_fiscal", "Avenida Uno 1", "un correo")
    assert 'name="visto" value="Avenida Uno 1"' in cliente.get("/secretario?p=datos").text
    _proponer(con, "domicilio_fiscal", "Avenida Dos 2", "otro correo")   # pisa la propuesta

    aviso = _aviso(_post(cliente, "domicilio_fiscal", "confirmar", visto="Avenida Uno 1"))
    assert "cambió mientras lo mirabas" in aviso.lower()
    assert misdatos.confirmados()["domicilio_fiscal"] == DOMICILIO
    assert misdatos.leer()["domicilio_fiscal"]["propuesta"]["valor"] == "Avenida Dos 2"


def test_confirmar_sin_decir_lo_que_viste_no_confirma_nada(con, cliente):
    _proponer(con, "telefono", "5512345678", "el chat")
    aviso = _aviso(_post(cliente, "telefono", "confirmar"))
    assert "recarga" in aviso.lower()
    assert misdatos.confirmados() == {}

def test_la_ficha_no_guarda_llaves_ni_campos_fuera_de_la_lista(con, cliente):
    llave = "sk-ant-api03-" + "a" * 30
    with pytest.raises(ValueError, match="llave"):
        misdatos.proponer("id_fiscal", llave, "chat")
    with pytest.raises(ValueError, match="no es uno de tus datos"):
        misdatos.proponer("tarjeta_de_credito", "4111 1111 1111 1111", "chat")
    with pytest.raises(ValueError):
        misdatos.confirmar("password", "lo-que-sea")
    with pytest.raises(ValueError, match="vacío"):
        misdatos.confirmar("telefono", "   ")
    # Por la acción, el modelo se entera, y la bitácora no se queda la llave.
    r = _proponer(con, "id_fiscal", f"password: {llave}")
    assert r["hecho"] is False and "llave" in r["error"]
    assert llave not in _todo_lo_de_la_memoria(con)
    # Por la pantalla, lo mismo, y se dice.
    assert "llave" in _aviso(_post(cliente, "id_fiscal", "corregir", valor=f"token={llave}"))
    assert "no está en la lista" in _aviso(_post(cliente, "pasaporte", "corregir", valor=ID_FISCAL))
    assert misdatos.leer() == {}
    assert not misdatos.ruta().exists() or llave not in misdatos.ruta().read_text(encoding="utf-8")


# ── lo que sale ───────────────────────────────────────────────────────────────

class _Saca(Accion):
    id = "prueba_saca"
    nombre = "Mandar algo fuera"
    riesgo = "reversible"
    nivel_inicial = "auto"
    saca_datos = True
    hechas: list = []

    def ejecutar(self, con, params):
        self.hechas.append(params)
        return "mandado"


def test_una_accion_que_saca_un_dato_tuyo_pide_permiso_aunque_este_en_auto(con):
    misdatos.confirmar("domicilio_fiscal", DOMICILIO)
    accion = _Saca()
    accion.hechas = []
    assert piezas.nivel(accion) == "auto"

    r = herramientas.usar_accion(con, accion, {"texto": "Envíalo a calle  falsa 123, springfield"}, "para el alta")
    assert r["hecho"] is False and r["solicitud"] and accion.hechas == []
    s = con.execute("SELECT motivo, params FROM solicitud WHERE id = ?", (r["solicitud"],)).fetchone()
    assert "lleva tus datos: domicilio fiscal" in s["motivo"]
    # Lo que se ejecuta al aprobar va tal cual; lo que se apunta, sin el dato.
    assert "calle  falsa 123" in s["params"]
    assert "falsa 123" not in con.execute("SELECT group_concat(params) FROM bitacora").fetchone()[0]

    # Sin un dato suyo dentro, `auto` sigue siendo `auto`.
    assert herramientas.usar_accion(con, accion, {"texto": "Envíalo a la oficina"})["hecho"]
    assert accion.hechas == [{"texto": "Envíalo a la oficina"}]
    # Y uno propuesto también es suyo: pide permiso igual.
    misdatos.proponer("telefono", "55-1234-5678", "chat")
    assert not herramientas.usar_accion(con, accion, {"texto": "llama al 5512345678"})["hecho"]
    # Las que sacan algo del hub llevan la marca.
    acciones = piezas.acciones()
    assert {i for i, a in acciones.items() if a.saca_datos} >= {"encargar_al_orquestador", "publicar_lienzo",
                                                                  "anotar_en_slot", "apuntar_idea"}
    assert not acciones["proponer_dato"].saca_datos


def test_una_ficha_rota_hace_pedir_permiso_y_se_dice(con, cliente):
    misdatos.ruta().parent.mkdir(parents=True, exist_ok=True)
    misdatos.ruta().write_text("esto: [no cierra\n", encoding="utf-8")
    accion = _Saca()
    accion.hechas = []
    r = herramientas.usar_accion(con, accion, {"texto": "cualquier cosa"})
    assert r["hecho"] is False and r["solicitud"] and accion.hechas == []
    assert "no pude leer tu ficha" in con.execute("SELECT motivo FROM solicitud").fetchone()[0]
    assert "No puedo leer tu ficha" in cliente.get("/secretario?p=datos").text
    # Y no se reescribe a ciegas: sigue como estaba.
    _post(cliente, "telefono", "corregir", valor="5512345678")
    assert misdatos.ruta().read_text(encoding="utf-8") == "esto: [no cierra\n"


def test_una_investigacion_no_lleva_tus_datos_a_la_web(con):
    misdatos.confirmar("id_fiscal", ID_FISCAL)
    r = investigar.encargar(con, "¿Qué pide el portal para dar de alta a idf000000ej1 como emisor?")
    assert "error" in r and "identificador fiscal" in r["error"] and ID_FISCAL not in r["error"]
    assert not memoria.leer(con, investigar.CLAVE)
    # Lo público, sin el dato, sí.
    assert investigar.encargar(con, "¿Qué pide el portal para dar de alta a un emisor?")["encargado"]
    assert len(memoria.leer(con, investigar.CLAVE)) == 1


# ── el archivo ────────────────────────────────────────────────────────────────

def test_olvidar_un_dato_lo_borra_del_archivo(con, cliente):
    _proponer(con, "id_fiscal", ID_FISCAL, "tu CV")
    _post(cliente, "id_fiscal", "confirmar", visto=ID_FISCAL)
    misdatos.confirmar("telefono", "5512345678")
    assert ID_FISCAL in misdatos.ruta().read_text(encoding="utf-8")

    r = _post(cliente, "id_fiscal", "olvidar")
    assert r.status_code == 303
    texto = misdatos.ruta().read_text(encoding="utf-8")
    assert ID_FISCAL not in texto and "id_fiscal" not in texto and "5512345678" in texto
    assert "id_fiscal" not in misdatos.leer()
    # Y no quedó en la memoria, que se copia cada día: ni en el asunto ni en la bitácora.
    assert ID_FISCAL not in _todo_lo_de_la_memoria(con)
    assert misdatos.olvidar("id_fiscal") is False


def test_el_archivo_de_mis_datos_solo_lo_lee_el_dueno(con, cliente):
    _proponer(con, "nombre_legal", "Juana Pérez Ejemplo")
    assert stat.S_IMODE(os.stat(misdatos.ruta()).st_mode) == 0o600
    _post(cliente, "nombre_legal", "confirmar", visto="Juana Pérez Ejemplo")
    misdatos.olvidar("nombre_legal")
    assert stat.S_IMODE(os.stat(misdatos.ruta()).st_mode) == 0o600
    # Sin temporales sueltos a la vista.
    assert not list(misdatos.ruta().parent.glob("mis-datos.yml.*.tmp"))


def test_leer_la_ficha_desde_la_web_no_crea_carpetas():
    carpeta = config.HUB_HOME / "secretario"
    d = api.secretario_datos()
    assert [f["campo"] for f in d["filas"]] == list(misdatos.CAMPOS)
    assert all(f["valor"] == "" for f in d["filas"]) and d["error"] is None
    assert misdatos.leer() == {} and misdatos.confirmados() == {} and misdatos.aparece_en("x") == []
    misdatos.ruta()
    assert not carpeta.exists()


# ── la pantalla ───────────────────────────────────────────────────────────────

def test_la_pestana_mis_datos_enseña_cada_campo_y_lo_escrito_a_mano_queda_confirmado(con, cliente):
    _proponer(con, "id_fiscal", ID_FISCAL, "tu CV")
    html = cliente.get("/secretario?p=datos").text
    assert 'href="/secretario?p=datos" class="aqui"' in html
    for nombre in misdatos.CAMPOS.values():
        assert nombre in html
    assert ID_FISCAL in html and "propuesto" in html and "tu CV" in html
    # Escribirlo él: queda confirmado, con «lo escribiste tú».
    r = _post(cliente, "correo_contacto", "corregir", valor="ana@ejemplo.com", volver="/secretario?p=pendientes")
    assert r.headers["location"].startswith("/secretario?p=pendientes")
    d = misdatos.leer()["correo_contacto"]
    assert (d["estado"], d["fuente"]) == ("confirmado", misdatos.A_MANO)
    # Lo que no es confirmar, corregir u olvidar no toca nada.
    _post(cliente, "id_fiscal", "borrar_todo")
    assert misdatos.leer()["id_fiscal"]["estado"] == "propuesto"


def test_confirmar_sin_secretario_no_crea_su_memoria(cliente):
    _post(cliente, "telefono", "corregir", valor="5512345678")
    assert misdatos.confirmados() == {"telefono": "5512345678"}
    assert not memoria.existe()


def test_la_bitacora_no_es_otra_ficha_aunque_el_dato_venga_escrito_de_otra_forma(con):
    """Tapa igual que la guarda compara: sin tildes, sin mayúsculas y, los
    largos, sin separadores. Y el motivo, que sale también al teléfono."""
    misdatos.confirmar("telefono", "55-1234-5678")
    misdatos.confirmar("domicilio_envios", "Calle Juárez 12")
    accion = _Saca()
    accion.hechas = []
    r = herramientas.usar_accion(con, accion, {"texto": "Llama al 5512345678 y envía a calle JUAREZ 12"},
                                 "por el 55 1234 5678")
    assert r["solicitud"]
    todo = _todo_lo_de_la_memoria(con)
    bitacora = con.execute("SELECT params || motivo FROM bitacora").fetchone()[0]
    assert "5512345678" not in bitacora and "JUAREZ" not in bitacora and "1234" not in bitacora
    assert "[tu teléfono]" in bitacora and "[tu domicilio de envíos]" in bitacora
    # La solicitud lleva tal cual lo que se ejecuta; su motivo, tapado.
    s = con.execute("SELECT params, motivo FROM solicitud").fetchone()
    assert "5512345678" in s["params"] and "1234" not in s["motivo"]
    assert "5512345678" in todo   # sólo en la solicitud, que es lo que él aprueba


def test_lo_aprobado_se_apunta_tapado_en_la_bitacora(con):
    from hub.secretario import servicio
    misdatos.confirmar("domicilio_fiscal", DOMICILIO)
    r = herramientas.usar_accion(con, piezas.acciones()["apuntar_idea"],
                                 {"texto": f"Darse de alta con {DOMICILIO}"}, "la tienda")
    assert r["solicitud"]
    memoria.resolver_solicitud(con, r["solicitud"], "aprobada")
    assert servicio.ejecutar_aprobadas(con) == 1
    fila = con.execute("SELECT params, ok FROM bitacora WHERE nivel = 'aprobada'").fetchone()
    assert fila["ok"] == 1 and "Falsa" not in fila["params"] and "[tu domicilio fiscal]" in fila["params"]



def test_un_dato_propuesto_no_queda_en_claro_en_la_bitacora_por_el_motivo(con):
    """C-0431: el motivo se tapaba antes de ejecutar, cuando el dato aún no
    estaba en la ficha, y el modelo lo escribe ahí con toda naturalidad. La
    bitácora va a `memoria.db`, que se copia catorce veces (382)."""
    r = herramientas.usar_accion(con, piezas.acciones()["proponer_dato"],
                                 {"campo": "id_fiscal", "valor": ID_FISCAL, "fuente": "el chat"},
                                 f"me dio su identificador {ID_FISCAL}")
    assert r["hecho"]
    fila = con.execute("SELECT params, motivo FROM bitacora WHERE accion = 'proponer_dato'").fetchone()
    assert ID_FISCAL not in fila["params"] + fila["motivo"]
    assert "[tu identificador fiscal]" in fila["params"] and "[tu identificador fiscal]" in fila["motivo"]
    assert ID_FISCAL not in _todo_lo_de_la_memoria(con)


def test_un_dato_rechazado_tampoco_queda_en_claro_en_la_bitacora(con):
    """Uno que no se guarda (aquí, demasiado largo) no llega a la ficha, así
    que nada lo tapaba: la fila llevaba el domicilio entero en `params`."""
    largo = "Calle Inexistente 4321, " + "Colonia Inventada de los Ejemplos, " * 9
    assert len(largo) > misdatos.MAX_VALOR
    r = herramientas.usar_accion(con, piezas.acciones()["proponer_dato"],
                                 {"campo": "domicilio_fiscal", "valor": largo, "fuente": "un correo"},
                                 "lo saqué de un correo")
    assert r["hecho"] is False and "largo" in r["error"]
    # Y uno que no es de la lista, con el valor también en el motivo.
    r = herramientas.usar_accion(con, piezas.acciones()["proponer_dato"],
                                 {"campo": "pasaporte", "valor": "PAS1234567", "fuente": "el chat"},
                                 "su pasaporte es PAS1234567")
    assert r["hecho"] is False
    assert misdatos.leer() == {}
    filas = con.execute("SELECT params, motivo, ok FROM bitacora WHERE accion = 'proponer_dato'").fetchall()
    assert len(filas) == 2 and not any(f["ok"] for f in filas)
    for fila in filas:
        assert "Inexistente" not in fila["params"] and "PAS1234567" not in fila["params"] + fila["motivo"]
    todo = _todo_lo_de_la_memoria(con)
    assert "Inexistente" not in todo and "PAS1234567" not in todo


def test_un_dato_propuesto_con_permiso_y_que_falla_al_aprobarlo_tampoco_queda_en_claro(con):
    """Por el camino de la solicitud (el modelo sin hilo, o en inglés): el
    motivo de la solicitud y la fila de «aprobada» que falla, tapados igual."""
    from hub.secretario import servicio
    r = herramientas.usar_accion(con, piezas.acciones()["proponer_dato"],
                                 {"campo": "pasaporte", "valor": "PAS1234567", "fuente": "el chat"},
                                 "su pasaporte es PAS1234567", techo="ask")
    assert r["solicitud"]
    s = con.execute("SELECT motivo FROM solicitud WHERE id = ?", (r["solicitud"],)).fetchone()
    assert "PAS1234567" not in s["motivo"]
    memoria.resolver_solicitud(con, r["solicitud"], "aprobada")
    servicio.ejecutar_aprobadas(con)
    filas = con.execute("SELECT nivel, params, motivo, ok FROM bitacora").fetchall()
    assert any(f["nivel"] == "aprobada" and not f["ok"] for f in filas)
    for fila in filas:
        assert "PAS1234567" not in fila["params"] + fila["motivo"]


# ── la solicitud, una vez resuelta (C-0431, tras la revisión cruzada) ──

def _pide_permiso_con_tu_domicilio(con):
    misdatos.confirmar("domicilio_fiscal", DOMICILIO)
    r = herramientas.usar_accion(con, piezas.acciones()["apuntar_idea"],
                                 {"texto": f"Darse de alta con {DOMICILIO}"}, "la tienda")
    sid = r["solicitud"]
    # Mientras espera, en claro: es lo que se ejecuta si dice que sí.
    assert "Falsa" in con.execute("SELECT params FROM solicitud WHERE id = ?", (sid,)).fetchone()[0]
    return sid


def _params(con, sid) -> str:
    return con.execute("SELECT params FROM solicitud WHERE id = ?", (sid,)).fetchone()[0]


def test_una_solicitud_hecha_no_guarda_tu_dato_en_claro(con):
    """Resuelta, la solicitud sigue en `memoria.db` (y en sus 14 copias), y
    Pendientes enseña las últimas: sus parámetros ya no hacen falta en claro."""
    from hub.secretario import servicio
    sid = _pide_permiso_con_tu_domicilio(con)
    memoria.resolver_solicitud(con, sid, "aprobada")
    assert servicio.ejecutar_aprobadas(con) == 1
    fila = con.execute("SELECT estado, params FROM solicitud WHERE id = ?", (sid,)).fetchone()
    assert fila["estado"] == "hecha"
    assert "Falsa" not in fila["params"] and "[tu domicilio fiscal]" in fila["params"]
    # Lo que se hizo, se hizo con el dato de verdad.
    from hub import api, db as _db
    h = _db.conectar()
    try:
        assert any(DOMICILIO in i["texto"] for i in api.tablero(h)["nuevas"])
    finally:
        h.close()


def test_una_solicitud_rechazada_no_guarda_tu_dato_en_claro(con, cliente):
    sid = _pide_permiso_con_tu_domicilio(con)
    r = cliente.post(f"/secretario/solicitud/{sid}", data={"decision": "rechazar"}, follow_redirects=False)
    assert r.status_code == 303
    assert con.execute("SELECT estado FROM solicitud WHERE id = ?", (sid,)).fetchone()[0] == "rechazada"
    assert "Falsa" not in _params(con, sid) and "[tu domicilio fiscal]" in _params(con, sid)


def test_una_solicitud_cortada_no_guarda_tu_dato_en_claro(con):
    from hub.secretario import servicio
    sid = _pide_permiso_con_tu_domicilio(con)
    memoria.resolver_solicitud(con, sid, "aprobada")
    assert memoria.resolver_solicitud(con, sid, "ejecutando", de="aprobada") is not None   # y murió a mitad
    try:
        assert servicio.recoger_cortadas(con) == 1
    finally:
        servicio._cortadas.clear()
    assert con.execute("SELECT estado FROM solicitud WHERE id = ?", (sid,)).fetchone()[0] == "cortada"
    assert "Falsa" not in _params(con, sid)


def test_un_dato_propuesto_con_permiso_queda_tapado_en_la_solicitud_al_hacerse(con):
    from hub.secretario import servicio
    r = herramientas.usar_accion(con, piezas.acciones()["proponer_dato"],
                                 {"campo": "id_fiscal", "valor": ID_FISCAL, "fuente": "el chat"}, techo="ask")
    memoria.resolver_solicitud(con, r["solicitud"], "aprobada")
    servicio.ejecutar_aprobadas(con)
    assert misdatos.leer()["id_fiscal"]["valor"] == ID_FISCAL
    assert ID_FISCAL not in _todo_lo_de_la_memoria(con)

def test_el_regimen_fiscal_no_hace_pedir_permiso_porque_no_identifica_a_nadie(con):
    misdatos.confirmar("regimen_fiscal", "General")
    accion = _Saca()
    accion.hechas = []
    assert herramientas.usar_accion(con, accion, {"texto": "Revisión general del proyecto"})["hecho"]
    assert misdatos.aparece_en("régimen general") == []
