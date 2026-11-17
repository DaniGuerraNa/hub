"""Los temas de las notas y qué notas se leen (C-0424, SEC2-19).

Tres cosas, una ficha:

- **Una lista corta de temas** (`memoria.TEMAS`): lo único que pueden elegir
  el triaje y el cierre de un hilo, o ninguno. Con tema libre salían 88 temas
  para 127 notas, y un tema que no agrupa no sirve para filtrar. El dueño, y
  el secretario cuando él se lo dicta, siguen con tema libre.
- **Las preferencias** que él deja caer en la conversación, con su ejemplo en
  el prompt del cierre.
- **Qué notas se le sirven al modelo**, en una tabla aparte (`nota_uso`), y no
  en una columna de `nota`: el disparador `nota_au` reescribe el índice de
  texto con cualquier `UPDATE` de la nota, y `buscar` dejaría de ser una
  lectura. Lo apuntan las herramientas que le dan la nota al modelo, nunca
  `buscar`. La pantalla dice desde cuándo se cuenta: de antes no se sabe
  (regla dura 13).
"""

from __future__ import annotations

import sqlite3

import pytest
from fastapi.testclient import TestClient

from hub import api, reloj, web
from hub.secretario import conversacion, herramientas, investigar, memoria, motor, triaje
from hub.secretario.piezas import Evento

# Los avisos que pudiera mandar el triaje salen por el timbre (el respaldo, decisión 310).
pytestmark = pytest.mark.usefixtures("canal_telegram")


@pytest.fixture
def con():
    c = memoria.conectar()
    yield c
    c.close()


@pytest.fixture
def cliente(tmp_path, monkeypatch):
    from hub import db

    def conexion():
        c = db.conectar(tmp_path / "hub.db")
        db.inicializar(c)
        return c

    monkeypatch.setattr(web, "conexion", conexion)
    return TestClient(web.app)


def _tablas(ruta) -> dict[str, list[str]]:
    """Tablas y columnas tal cual están en el archivo, sin abrirlo con `conectar`."""
    c = sqlite3.connect(f"file:{ruta}?mode=ro", uri=True)
    try:
        filas = c.execute("SELECT m.name, p.name FROM sqlite_master AS m, pragma_table_info(m.name) AS p"
                          " WHERE m.type = 'table' ORDER BY m.name, p.cid").fetchall()
    finally:
        c.close()
    out: dict[str, list[str]] = {}
    for tabla, columna in filas:
        out.setdefault(tabla, []).append(columna)
    return out


def _memoria_de_ayer() -> list[int]:
    """Una memoria de antes de C-0424: con sus notas y sin `nota_uso`."""
    con = memoria.conectar()
    ids = [memoria.anotar(con, "El taller cierra los lunes", tema="dato"),
           memoria.anotar(con, "Luis lleva la cuenta del proveedor", tema="Proveedores del almacén")]
    con.close()
    c = sqlite3.connect(memoria.ruta())
    c.execute("DROP TABLE nota_uso")
    c.close()
    return ids


def _uso(con) -> dict[int, tuple[int, str]]:
    return {f["nota"]: (f["veces"], f["ultima"]) for f in con.execute("SELECT * FROM nota_uso")}


def _ev(i, texto, autor="Ana", fecha="2026-11-10T10:00:00+00:00"):
    return Evento(fuente="telegram", id_externo=str(i), fecha=fecha, texto=texto, conversacion="Trabajo",
                  autor=autor)


# ── el esquema ───────────────────────────────────────────────────────────────


def test_una_memoria_nueva_trae_la_cuenta_de_uso_de_las_notas(con):
    assert _tablas(memoria.ruta())["nota_uso"] == ["nota", "veces", "ultima"]


def test_la_cuenta_de_uso_dice_en_su_comentario_que_solo_vive_ahi():
    """Regla dura 1: una tabla que no se rehace se declara como tal."""
    antes, tabla, _ = memoria.ESQUEMA.partition("CREATE TABLE IF NOT EXISTS nota_uso")
    assert tabla, "no está en el esquema"
    assert "Sólo vive aquí" in antes.rsplit("\n\n", 1)[-1]


def test_una_memoria_de_ayer_se_lee_como_ausente_hasta_que_la_abre_quien_escribe():
    """Decisión 424: la web no migra. Con la tabla nueva, la memoria de ayer
    se lee como ausente hasta que `conectar` (el servicio, una ruta POST o
    el MCP) la pone al día; entonces gana la tabla y conserva sus notas."""
    ids = _memoria_de_ayer()
    assert memoria.abrir_lectura() is None
    assert "nota_uso" not in _tablas(memoria.ruta())

    memoria.conectar().close()

    assert _tablas(memoria.ruta())["nota_uso"] == ["nota", "veces", "ultima"]
    lectura = memoria.abrir_lectura()
    assert lectura is not None
    try:
        assert sorted(n["id"] for n in memoria.notas(lectura)) == sorted(ids)
        assert {n["texto"] for n in memoria.notas(lectura)} == {"El taller cierra los lunes",
                                                               "Luis lleva la cuenta del proveedor"}
    finally:
        lectura.close()


@pytest.mark.parametrize("ruta", ["/secretario?p=memoria", "/secretario?p=memoria&tema=dato&sin_salir=1",
                                  "/secretario?p=memoria&q=taller&tema=persona"])
def test_con_una_memoria_de_ayer_la_pantalla_de_memoria_se_pinta_y_no_la_migra(cliente, ruta):
    _memoria_de_ayer()
    r = cliente.get(ruta)
    assert r.status_code == 200
    assert "nota_uso" not in _tablas(memoria.ruta()), "una pantalla que sólo mira no crea la tabla"


# ── apuntar qué se sirvió ────────────────────────────────────────────────────


def test_apuntar_una_lectura_suma_cada_vez_y_guarda_la_ultima(con, monkeypatch):
    a = memoria.anotar(con, "El taller cierra los lunes")
    b = memoria.anotar(con, "La reunión de equipo es los martes")
    monkeypatch.setattr(memoria, "ahora", lambda: "2026-11-14T10:00:00+00:00")
    memoria.apuntar_lectura(con, [a])
    monkeypatch.setattr(memoria, "ahora", lambda: "2026-11-15T09:30:00+00:00")
    memoria.apuntar_lectura(con, [a, b, a])
    assert _uso(con) == {a: (2, "2026-11-15T09:30:00+00:00"), b: (1, "2026-11-15T09:30:00+00:00")}


def test_la_fecha_desde_la_que_se_cuenta_se_pone_una_vez(con, monkeypatch):
    """Con la primera búsqueda, aunque no trajera ninguna nota: desde ahí
    «no salió» ya es una afirmación que se puede defender."""
    assert memoria.leer(con, memoria.USO_DESDE) is None
    monkeypatch.setattr(memoria, "ahora", lambda: "2026-11-14T10:00:00+00:00")
    memoria.apuntar_lectura(con, [])
    assert _uso(con) == {}
    monkeypatch.setattr(memoria, "ahora", lambda: "2026-11-20T10:00:00+00:00")
    memoria.apuntar_lectura(con, [memoria.anotar(con, "Algo")])
    assert memoria.leer(con, memoria.USO_DESDE) == "2026-11-14T10:00:00+00:00"


def test_apuntar_no_toca_la_nota_ni_su_indice_de_texto(con):
    """Una columna en `nota` habría disparado `nota_au` en cada búsqueda."""
    a = memoria.anotar(con, "El taller cierra los lunes", tema="dato")
    nota_antes = [dict(f) for f in con.execute("SELECT * FROM nota")]
    indice_antes = con.execute("SELECT * FROM nota_fts_data ORDER BY id").fetchall()
    con.execute("CREATE TEMP TABLE tocadas (id INTEGER)")
    con.execute("CREATE TEMP TRIGGER vigia AFTER UPDATE ON main.nota BEGIN INSERT INTO tocadas VALUES (new.id); END")

    memoria.apuntar_lectura(con, [a])
    memoria.apuntar_lectura(con, [a])

    assert con.execute("SELECT COUNT(*) FROM tocadas").fetchone()[0] == 0
    assert [dict(f) for f in con.execute("SELECT * FROM nota")] == nota_antes
    assert nota_antes[0]["editada"] is None
    assert con.execute("SELECT * FROM nota_fts_data ORDER BY id").fetchall() == indice_antes


def test_apuntar_una_nota_que_ya_no_esta_no_falla_ni_deja_fila(con):
    """Entre que `buscar` la devuelve y se apunta, el dueño pudo borrarla."""
    memoria.apuntar_lectura(con, [999])
    assert _uso(con) == {}


@pytest.mark.parametrize("como", ["borrar", "olvidar"])
def test_borrar_u_olvidar_una_nota_se_lleva_su_cuenta_y_su_numero_vuelve_limpio(con, como):
    """El número de la última nota se reutiliza al borrarla (`olvidar_nota`
    lo cuenta): la nota nueva no puede heredar las lecturas de la vieja."""
    memoria.anotar(con, "La primera")
    b = memoria.anotar(con, "La que se va")
    memoria.apuntar_lectura(con, [b])
    (memoria.borrar_nota if como == "borrar" else memoria.olvidar_nota)(con, b)
    assert _uso(con) == {}
    nueva = memoria.anotar(con, "La que llega")
    assert nueva == b
    assert [n["texto"] for n in memoria.notas(con, sin_leer=True)] == ["La que llega", "La primera"]


def test_buscar_no_escribe_y_contesta_igual_en_solo_lectura(con):
    memoria.anotar(con, "El taller cierra los lunes", tema="dato")
    memoria.guardar_evento(con, _ev(1, "¿Abre el taller el lunes?"))
    con.close()
    escritura = memoria.conectar()
    lectura = sqlite3.connect(f"file:{memoria.ruta()}?mode=ro", uri=True)
    lectura.row_factory = sqlite3.Row
    try:
        esperado = memoria.buscar(escritura, "taller lunes")
        assert [r["tipo"] for r in esperado] == ["nota", "mensaje"]
        assert memoria.buscar(lectura, "taller lunes") == esperado
        assert _uso(escritura) == {}
    finally:
        lectura.close()
        escritura.close()


# ── listar con filtros ───────────────────────────────────────────────────────


def test_las_notas_se_filtran_por_su_tema_exacto(con):
    memoria.anotar(con, "Ana cambia de equipo", tema="persona")
    memoria.anotar(con, "Personas del proyecto nuevo", tema="Personas del proyecto")
    memoria.anotar(con, "Sin tema")
    assert [n["texto"] for n in memoria.notas(con, tema="persona")] == ["Ana cambia de equipo"]


def test_sin_leer_son_las_que_no_salieron_en_ninguna_busqueda(con):
    a = memoria.anotar(con, "Salió una vez")
    memoria.anotar(con, "Nunca salió", tema="dato")
    memoria.anotar(con, "Tampoco", tema="persona")
    memoria.apuntar_lectura(con, [a])
    assert [n["texto"] for n in memoria.notas(con, sin_leer=True)] == ["Tampoco", "Nunca salió"]
    assert [n["texto"] for n in memoria.notas(con, tema="dato", sin_leer=True)] == ["Nunca salió"]


def test_quien_ya_listaba_las_notas_recibe_lo_mismo(con):
    ids = [memoria.anotar(con, f"Nota {i}") for i in range(5)]
    assert [n["id"] for n in memoria.notas(con)] == ids[::-1]
    assert [n["id"] for n in memoria.notas(con, 2)] == ids[:2:-1][:2]
    assert set(memoria.notas(con)[0]) == {"id", "texto", "tema", "evento", "origen", "creada", "editada"}


# ── la lista de temas ────────────────────────────────────────────────────────


def _enum_de_tema(esquema: dict) -> list:
    notas = esquema["properties"]["notas"] if "notas" in esquema["properties"] else \
        esquema["properties"]["items"]["items"]["properties"]["notas"]
    return notas["items"]["properties"]["tema"]["enum"]


@pytest.mark.parametrize("esquema", [triaje.ESQUEMA, conversacion.ESQUEMA_CIERRE], ids=["triaje", "cierre"])
def test_el_triaje_y_el_cierre_solo_eligen_un_tema_de_la_lista_o_ninguno(esquema):
    assert _enum_de_tema(esquema) == [*memoria.TEMAS, ""]


def test_los_temas_fijos_que_usa_el_codigo_estan_en_la_lista():
    """`investigar` compara su tema para encontrar sus notas (`TEMA`), y el
    cierre pide «inglés» para la práctica: fuera de la lista, el esquema les
    impediría a ellos mismos guardarlo."""
    assert investigar.TEMA in memoria.TEMAS
    assert "inglés" in memoria.TEMAS and "preferencia" in memoria.TEMAS
    assert len(set(memoria.TEMAS)) == len(memoria.TEMAS)


@pytest.mark.parametrize("dado, queda", [("persona", "persona"), ("  Decisión ", "decisión"),
                                         ("Proyecto hub", ""), ("", ""), (None, "")])
def test_un_tema_que_no_esta_en_la_lista_queda_sin_tema(dado, queda):
    assert memoria.tema_automatico(dado) == queda


class _Modelo:
    def __init__(self, datos):
        self.datos, self.prompts = datos, []

    def __call__(self, prompt, **kw):
        self.prompts.append(prompt)
        return motor.Respuesta(texto="", sesion="s-1", estructurada=self.datos, segundos=0.1, coste=0,
                               modelo=kw["modelo"])


def test_el_triaje_no_guarda_un_tema_fuera_de_la_lista(con, monkeypatch):
    """El esquema ya se lo pide al modelo; esto es por si no lo cumple."""
    e = memoria.guardar_evento(con, _ev(1, "Luis lleva desde hoy la cuenta del proveedor de cartón"))
    monkeypatch.setattr(motor, "llamar", _Modelo({"items": [{"id": e, "notas": [
        {"texto": "Luis lleva la cuenta del proveedor de cartón", "tema": "Proveedores"},
        {"texto": "El proveedor de cartón es de Luis", "tema": "Persona"}]}]}))
    triaje.triar(con, "Alex")
    assert {n["texto"]: n["tema"] for n in memoria.notas(con)} == {
        "Luis lleva la cuenta del proveedor de cartón": "", "El proveedor de cartón es de Luis": "persona"}


def test_el_triaje_dice_la_lista_de_temas_en_su_prompt(con, monkeypatch):
    """Sin depender sólo de que el modelo lea el `enum` de `--json-schema`."""
    e = memoria.guardar_evento(con, _ev(1, "Luis lleva desde hoy la cuenta del proveedor de cartón"))
    vistos = []

    def falso(prompt, **kw):
        vistos.append(kw["sistema"])
        return motor.Respuesta(texto="", sesion="s-1", estructurada={"items": [{"id": e}]}, segundos=0.1, coste=0,
                               modelo=kw["modelo"])
    monkeypatch.setattr(motor, "llamar", falso)
    triaje.triar(con, "Alex")
    assert ", ".join(memoria.TEMAS) in vistos[0]


def test_el_cierre_pide_las_preferencias_con_su_ejemplo_y_no_guarda_un_tema_fuera_de_la_lista(con, monkeypatch):
    m = _Modelo({"titulo": "Avisos", "resumen": "Habló de cuándo quiere los avisos.", "notas": [
        {"texto": "Prefiere que el parte de la mañana llegue antes de las 8", "tema": "preferencia"},
        {"texto": "No le gusta que le resuman las reuniones en viñetas", "tema": "gustos"}]})
    monkeypatch.setattr(motor, "llamar", m)
    conversacion.recibir(con, "El parte, mejor antes de las 8")
    assert conversacion.cerrar(con, conversacion.hilo_abierto(con))

    prompt = m.prompts[0]
    assert "preferencia" in prompt and "«Prefiere" in prompt and "«No le gusta" in prompt
    assert "tema «preferencia»" in prompt and "tema «inglés»" in prompt
    assert ", ".join(memoria.TEMAS) in prompt
    assert {n["texto"]: n["tema"] for n in memoria.notas(con)} == {
        "Prefiere que el parte de la mañana llegue antes de las 8": "preferencia",
        "No le gusta que le resuman las reuniones en viñetas": ""}


def test_el_dueno_sigue_poniendo_el_tema_que_quiera(con):
    memoria.anotar(con, "El proveedor cobra por adelantado", tema="proveedores del almacén")
    assert memoria.notas(con)[0]["tema"] == "proveedores del almacén"


# ── las herramientas apuntan lo que sirven ───────────────────────────────────


def test_buscar_desde_el_secretario_cuenta_las_notas_que_le_sirve_y_no_los_mensajes(con):
    a = memoria.anotar(con, "El taller cierra los lunes", tema="dato")
    b = memoria.anotar(con, "La reunión de equipo es los martes")
    # Un mensaje con el mismo número que la nota `b`: los ids de mensajes y
    # de notas son de tablas distintas, y uno no puede contar por la otra.
    memoria.guardar_evento(con, _ev(1, "hola"))
    assert memoria.guardar_evento(con, _ev(2, "¿El taller abre el lunes?")) == b
    r = herramientas.catalogo()["buscar"].funcion(con, {"texto": "taller lunes"})
    assert {x["tipo"] for x in r} == {"nota", "mensaje"}
    assert set(_uso(con)) == {a}
    assert memoria.leer(con, memoria.USO_DESDE)


def test_preguntar_por_una_persona_cuenta_las_notas_que_la_nombran(con):
    a = memoria.anotar(con, "Luis lleva la cuenta del proveedor", tema="persona")
    memoria.anotar(con, "El taller cierra los lunes")
    r = herramientas.catalogo()["persona"].funcion(con, {"nombre": "Luis"})
    assert [n["id"] for n in r["notas"]] == [a]
    assert set(_uso(con)) == {a}


def test_una_busqueda_con_la_fecha_mal_no_cuenta_como_busqueda(con):
    memoria.anotar(con, "El taller cierra los lunes")
    r = herramientas.catalogo()["buscar"].funcion(con, {"texto": "taller", "desde": "el lunes que viene"})
    assert "error" in r
    assert memoria.leer(con, memoria.USO_DESDE) is None


@pytest.mark.parametrize("herramienta, args", [("buscar", {"texto": "taller"}), ("persona", {"nombre": "Luis"})])
def test_si_no_se_puede_apuntar_la_herramienta_contesta_igual_y_lo_dice(con, monkeypatch, capsys,
                                                                       herramienta, args):
    monkeypatch.setitem(herramientas._SIN_APUNTAR, "hubo", False)
    memoria.anotar(con, "Luis dice que el taller cierra los lunes")

    def bloqueada(*a, **k):
        raise sqlite3.OperationalError("database is locked")
    monkeypatch.setattr(memoria, "apuntar_lectura", bloqueada)
    r = herramientas.catalogo()[herramienta].funcion(con, args)
    notas = r["notas"] if isinstance(r, dict) else [x for x in r if x["tipo"] == "nota"]
    assert [n["texto"] for n in notas] == ["Luis dice que el taller cierra los lunes"]
    err = capsys.readouterr().err
    assert "database is locked" in err and "notas" in err


def test_tras_una_lectura_sin_apuntar_la_fecha_desde_la_que_se_cuenta_se_adelanta(con, monkeypatch):
    """Que el fallo vaya a stderr no basta: no está medido que llegue al
    journal. Con la fecha de antes, la nota de la búsqueda perdida saldría en
    «Sin salir…» sin que fuera verdad (regla dura 13)."""
    monkeypatch.setitem(herramientas._SIN_APUNTAR, "hubo", False)
    a = memoria.anotar(con, "El taller cierra los lunes")
    b = memoria.anotar(con, "Luis lleva la cuenta del proveedor")
    buscar = herramientas.catalogo()["buscar"].funcion
    monkeypatch.setattr(memoria, "ahora", lambda: "2026-11-14T10:00:00+00:00")
    buscar(con, {"texto": "proveedor"})                       # cuenta `b` y pone la fecha
    apuntar = memoria.apuntar_lectura

    def bloqueada(*x, **k):
        raise sqlite3.OperationalError("database is locked")
    monkeypatch.setattr(memoria, "apuntar_lectura", bloqueada)
    buscar(con, {"texto": "taller"})                          # `a` sale y no se apunta
    monkeypatch.setattr(memoria, "apuntar_lectura", apuntar)
    monkeypatch.setattr(memoria, "ahora", lambda: "2026-11-15T09:00:00+00:00")
    buscar(con, {"texto": "proveedor"})

    assert memoria.leer(con, memoria.USO_DESDE) == "2026-11-15T09:00:00+00:00"
    assert _uso(con) == {b: (2, "2026-11-15T09:00:00+00:00")}
    assert a in {n["id"] for n in memoria.notas(con, sin_leer=True)}, "no salió desde la fecha nueva: es verdad"
    # Y la siguiente ya no la mueve.
    monkeypatch.setattr(memoria, "ahora", lambda: "2026-11-16T09:00:00+00:00")
    buscar(con, {"texto": "proveedor"})
    assert memoria.leer(con, memoria.USO_DESDE) == "2026-11-15T09:00:00+00:00"


# ── la pantalla ──────────────────────────────────────────────────────────────


def _notas_vistas(html: str) -> list[str]:
    region = html.split('data-region="notas"')[1].split("</div>\n  </div>")[0]
    return [b.split('<p class="texto-nota">')[1].split("</p>")[0] for b in region.split('class="bloque nota"')[1:]]


@pytest.fixture
def con_notas(con):
    a = memoria.anotar(con, "Ana cambia de equipo en diciembre", tema="persona")
    memoria.anotar(con, "Prefiere los avisos antes de las 8", tema="preferencia")
    memoria.anotar(con, "Luis lleva el proveedor de cartón", tema="persona")
    memoria.anotar(con, "Una nota de antes, con su tema libre", tema="Cosas del almacén")
    return con, a


def test_memoria_ofrece_los_temas_de_la_lista_con_cuantas_notas_tiene_cada_uno(cliente, con_notas):
    s = api.secretario("memoria")
    assert [t["tema"] for t in s["temas"]] == list(memoria.TEMAS)
    assert {t["tema"]: t["notas"] for t in s["temas"]}["persona"] == 2
    html = cliente.get("/secretario?p=memoria").text
    assert '<select name="tema" id="fn-tema" data-region="notas-temas">' in html
    assert '<option value="persona">persona (2)</option>' in html


def test_la_cifra_de_cada_tema_es_lo_que_se_vera_al_elegirlo(cliente, con_notas):
    """Con la búsqueda o «sin salir» puestos, el total del tema no es lo que
    sale al elegirlo (revisor): el desplegable decía 2 y la lista enseñaba 1."""
    con, a = con_notas
    memoria.apuntar_lectura(con, [a])
    s = api.secretario("memoria", notas_sin_salir=True)
    assert {t["tema"]: t["notas"] for t in s["temas"]}["persona"] == 1
    s = api.secretario("memoria", notas_q="cartón")
    assert {t["tema"]: t["notas"] for t in s["temas"]} == {t: (1 if t == "persona" else 0) for t in memoria.TEMAS}


def test_memoria_filtra_por_tema_y_deja_el_filtro_a_la_vista(cliente, con_notas):
    s = api.secretario("memoria", notas_tema="persona")
    assert [n["texto"] for n in s["notas"]] == ["Luis lleva el proveedor de cartón", "Ana cambia de equipo en diciembre"]
    assert s["notas_halladas"] == 2
    html = cliente.get("/secretario", params={"p": "memoria", "tema": "persona"}).text
    assert _notas_vistas(html) == ["Luis lleva el proveedor de cartón", "Ana cambia de equipo en diciembre"]
    assert '<option value="persona" selected>' in html
    assert 'class="chip-filtro" href="/secretario?p=memoria"' in html, "el chip lo quita"
    assert "2 de 4 notas pasan el filtro." in html
    # Lo que se guarda vuelve con el mismo filtro (`sin-recarga.js` repinta por esa URL).
    assert 'name="volver" value="/secretario?p=memoria&amp;tema=persona"' in html


def test_un_tema_que_no_es_de_la_lista_no_filtra(cliente, con_notas):
    s = api.secretario("memoria", notas_tema="Cosas del almacén")
    assert s["notas_tema"] == "" and len(s["notas"]) == 4 and s["notas_halladas"] is None


def test_buscar_y_filtrar_por_tema_se_suman(cliente, con_notas):
    s = api.secretario("memoria", notas_q="cartón", notas_tema="persona")
    assert [n["texto"] for n in s["notas"]] == ["Luis lleva el proveedor de cartón"]
    html = cliente.get("/secretario", params={"p": "memoria", "q": "equipo", "tema": "preferencia"}).text
    assert "Ninguna de tus 4 notas dice «equipo» y pasa el filtro." in html
    assert "Aún no hay notas" not in html, "las hay: es el filtro el que no deja ver ninguna"
    # Buscar no suelta el filtro, ni filtrar la búsqueda.
    assert '<input type="hidden" name="tema" value="preferencia">' in html
    assert '<input type="hidden" name="q" value="equipo">' in html


def test_antes_de_la_primera_busqueda_no_se_ofrece_sin_salir_y_se_dice_por_que(cliente, con_notas):
    s = api.secretario("memoria", notas_sin_salir=True)
    assert s["notas_uso_desde"] is None and not s["notas_sin_salir"] and len(s["notas"]) == 4
    html = cliente.get("/secretario", params={"p": "memoria", "sin_salir": "1"}).text
    assert 'name="sin_salir"' not in html
    assert "Aún no se cuenta qué notas salen cuando busca" in html


def test_sin_salir_ensena_las_que_no_salieron_y_dice_desde_cuando_se_cuenta(cliente, con_notas, monkeypatch):
    con, a = con_notas
    monkeypatch.setattr(memoria, "ahora", lambda: "2026-11-14T15:20:00+00:00")
    memoria.apuntar_lectura(con, [a])
    s = api.secretario("memoria", notas_sin_salir=True)
    assert s["notas_uso_desde"] == "2026-11-14T15:20:00+00:00" and s["notas_sin_salir"]
    assert a not in {n["id"] for n in s["notas"]} and len(s["notas"]) == 3

    html = cliente.get("/secretario", params={"p": "memoria", "sin_salir": "1", "tema": "persona"}).text
    assert _notas_vistas(html) == ["Luis lleva el proveedor de cartón"]
    desde = reloj.cuando("2026-11-14T15:20:00+00:00")["local"]
    chip = html.split('class="chips-filtro notas-filtros"')[1].split("</div>")[0]
    assert "Sin salir en ninguna búsqueda desde el" in chip and desde in chip
    assert '<input type="checkbox" name="sin_salir" value="1" checked>' in html
    assert "1 de 4 notas pasa el filtro." in html
    # Quitar uno deja el otro.
    assert 'href="/secretario?p=memoria&amp;sin_salir=1"' in chip and 'href="/secretario?p=memoria&amp;tema=persona"' in chip


def test_abrir_memoria_no_cuenta_como_lectura(cliente, con_notas):
    """Lo que cuenta es lo que se le sirve al modelo; que él mire su memoria, no."""
    con, _ = con_notas
    cliente.get("/secretario?p=memoria")
    cliente.get("/secretario", params={"p": "memoria", "q": "cartón"})
    assert _uso(con) == {}
