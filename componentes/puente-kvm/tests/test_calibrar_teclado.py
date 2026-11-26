"""Calibrar el teclado del Mac desde el puente (C-0481).

El Mac de verdad tenía la fuente latinoamericana, que el puente no trae, y lo
tecleado en «Español - ISO» salía cambiado: `<`→`|`, `>`→`°`, `{`→`^`… Aquí
el Mac simulado tiene una fuente de prueba que el puente tampoco conoce (la
española con `< > { } [ ] # ^` en otras teclas), y el puente la mide, la
verifica con huellas y, sólo cuando la persona la elige, teclea bien con ella.

Todo contra el simulador y en la carpeta de datos de cada prueba.
"""

import asyncio
import json
import re

import pytest
from fastapi.testclient import TestClient

from puente_kvm import config, hid, mcp_servidor, teclados
from puente_kvm.app import crear_app
from puente_kvm.simulador import Simulador

from .ayuda import (PERSONA, ejecutar_como_sql_server, esperar, mcp_contra, medida_verificada, puente_simulado,
                    pulsar_en, rejilla, transcribir_como_oraculo, vaciar)

# Un trozo de HTML, como el que salió mal en el Mac de verdad.
HTML = '<a href="#x">{uno} [dos] | 3 > 2 < 4</a>'
# Pares de caracteres que cambian de tecla respecto de «Español - ISO».
CAMBIADOS = (("<", "|"), (">", "°"), ("{", "["), ("}", "]"), ("#", "·"), ("^", "ˆ"))


def fuente_de_prueba() -> hid.Distribucion:
    """Una fuente que el puente no tiene: la española con esos pares intercambiados, y
    su tecla muerta del circunflejo dejando `ˆ` (U+02C6) en vez de `^`."""
    tabla = dict(hid.MAC_ES.tabla)
    for a, b in CAMBIADOS:
        tabla[a], tabla[b] = tabla[b], tabla[a]
    muertas = {**hid.MAC_ES.muertas, (hid.SHIFT, "["): "ˆ"}
    return hid.Distribucion("prueba", "Mac de prueba", tabla, muertas)


def lineas_del_sondeo(fuente, reservadas=("alt+x",)) -> list[str]:
    sim = Simulador(lineas=[""], fuente=fuente)
    pulsar_en(sim, teclados.sondeo(reservadas))
    return sim.editor.lineas


def cambiar(lineas: list[str], cambios: dict[str, str]) -> list[str]:
    """Cambia el contenido de las líneas del sondeo, sin tocar su número: comparar
    la línea entera ya no casaría con ninguna, y el test dejaría de probar nada."""
    salida = []
    for l in lineas:
        numero, dentro = l[:4], l[4:]
        salida.append(numero + cambios.get(dentro, dentro))
    assert salida != lineas, "ningún cambio casó con una línea"
    return salida


def una_ronda(b: dict, sim: Simulador, estropear: int | None = None) -> dict:
    """Probar, «ejecutar» como SQL Server lo tecleado y comprobar, sin la API."""
    consulta, ronda = teclados.consulta(b, reservadas=["alt+x"])
    vaciar(sim)
    pulsar_en(sim, hid.secuencia(consulta, teclados.distribucion_del_borrador(b), ["alt+x"]))
    teclados.empezar_ronda(b, ronda)
    filas = ejecutar_como_sql_server(sim.editor.lineas)
    if estropear is not None:
        filas[estropear]["huella"] = "0" * 16
    return teclados.comprobar(b, rejilla(filas))


# ── las distribuciones son datos ────────────────────────────────────────────
def test_las_dos_de_serie_son_tablas_con_todo_el_ascii_imprimible():
    for d in hid.DE_SERIE.values():
        assert isinstance(d, hid.Distribucion)
        assert set(teclados.ASCII_IMPRIMIBLE) <= set(d.tabla), d.id
    # La tabla y el id dan las mismas teclas: U.S. dejó de ser código aparte.
    for c in "{}[]|\\~`^<>@#áñ€":
        assert hid.caracter(c, hid.MAC_US) == hid.caracter(c, "mac-us")


def test_el_mac_simulado_con_un_id_desconocido_es_un_error_y_no_cae_a_us():
    with pytest.raises(ValueError, match="desconocida"):
        Simulador(lineas=[""], fuente="mac-latam")


# ── Opción+X, reservada (el riesgo que ya existía) ──────────────────────────
@pytest.mark.parametrize("distribucion, caracter", [("mac-us", "≈"), ("mac-es", "∑")])
def test_un_caracter_que_pide_una_tecla_reservada_cuenta_como_intraducible(distribucion, caracter):
    # En DBeaver para Mac, Opción+X es «Ejecutar script»: pegar «≈» lo ejecutaba.
    assert [str(p) for p in hid.caracter(caracter, distribucion)] == ["alt+x"]
    with pytest.raises(hid.TextoIntraducible) as e:
        hid.secuencia(f"SELECT 1 -- {caracter}", distribucion, ["alt+x"])
    assert e.value.caracteres == [caracter] and e.value.reservadas == {caracter: "alt+x"}
    assert "reservada" in str(e.value)
    assert hid.secuencia(caracter, distribucion)  # sin reservas, sí


def test_teclear_por_la_api_no_pulsa_opcion_x_ni_un_caracter_antes():
    with puente_simulado() as (c, sim):
        assert config.leer_ajustes()["perfil"]["reservadas"] == ["alt+x"]  # de fábrica
        c.post("/api/control", json={"accion": "dar"}, headers=PERSONA)
        r = c.post("/api/teclear", json={"texto": "SELECT 1 -- ≈ 2"})
        assert r.status_code == 422 and "alt+x" in r.json()["detail"]
        assert sim.pulsaciones == 0


def test_pegar_texto_de_la_persona_tampoco_pulsa_las_reservadas():
    with puente_simulado() as (c, sim):
        with c.websocket_connect("/ws/mando", headers=PERSONA) as ws:
            ws.send_text(json.dumps({"t": "pegar", "texto": "a ≈ b"}))
            respuesta = ws.receive_json()
        assert "No pegué nada" in respuesta["no"] and "alt+x" in respuesta["no"]
        assert sim.pulsaciones == 0


def test_las_reservadas_se_validan_en_ajustes_y_se_guardan_como_las_escribe_el_puente():
    with puente_simulado() as (c, _):
        perfil = {**config.leer_ajustes()["perfil"], "reservadas": ["option+x", "alt+x", "cmd+shift+e"]}
        assert c.post("/api/ajustes", json={"perfil": perfil}, headers=PERSONA).status_code == 200
        assert config.leer_ajustes()["perfil"]["reservadas"] == ["alt+x", "cmd+shift+e"]
        for mal in (["hiper+x"], "alt+x"):
            r = c.post("/api/ajustes", json={"perfil": {**perfil, "reservadas": mal}}, headers=PERSONA)
            assert r.status_code == 400
        assert config.leer_ajustes()["perfil"]["reservadas"] == ["alt+x", "cmd+shift+e"]


# ── sondear y medir ─────────────────────────────────────────────────────────
def test_el_sondeo_da_una_linea_por_tecla_y_capa_y_no_pulsa_las_reservadas():
    pulsaciones = teclados.sondeo(["alt+x"])
    assert hid.combinacion("alt+x") not in pulsaciones
    lineas = lineas_del_sondeo("mac-es")
    assert len(lineas) == teclados.LINEAS_SONDEO == 4 * len(teclados.TECLAS_SONDEO)
    alt_x = 2 * len(teclados.TECLAS_SONDEO) + teclados.TECLAS_SONDEO.index(hid.TECLAS["x"])
    assert lineas[alt_x] == f"{alt_x + 1:03d} x x"  # sin pulsar: vacía, y no se usa nunca
    # Con su número delante: en un texto plano no hay margen que lo diga (C-0482).
    assert all(l[:4] == f"{i:03d} " and l[4] == "x" and l[-1] == "x" for i, l in enumerate(lineas, 1))


def test_el_sondeo_distingue_la_tecla_normal_la_muerta_y_la_vacia():
    lineas = lineas_del_sondeo("mac-es")
    b = teclados.construir(lineas, "Español medido")
    crudas = {(m, t): (tipo, salida) for m, t, tipo, salida in b["crudas"]}
    assert crudas[(0, "a")] == ("normal", "a")
    assert crudas[(hid.SHIFT, "`")] == ("normal", ">")
    assert crudas[(0, "'")] == ("muerta", "´")  # se comió el espacio: «x´x»
    assert crudas[(hid.ALT, "x")] == ("vacia", "")
    r = teclados.resumen(b)
    assert r["estado"] == "sin verificar" and not r["elegible"]
    assert r["muertas"] == {"[": "`", "'": "´", "shift+[": "^", "shift+'": "¨", "alt+;": "~"}


def test_un_sondeo_con_bloq_mayus_se_rechaza():
    lineas = [l.upper() for l in lineas_del_sondeo("mac-es")]
    with pytest.raises(ValueError, match="Bloq Mayús"):
        teclados.construir(lineas, "con mayúsculas")


def test_un_sondeo_con_lineas_de_menos_se_rechaza():
    lineas = lineas_del_sondeo("mac-es")
    with pytest.raises(ValueError, match="faltan"):
        teclados.construir(lineas[:-1], "corto")
    del lineas[5]  # una línea perdida corre las demás de sitio: su número lo delata
    with pytest.raises(ValueError, match="línea 6 lleva el número 007"):
        teclados.construir(lineas + ["193 x x"], "corrido")


def test_el_sondeo_sin_numero_de_antes_sigue_valiendo_pero_no_mezclado():
    # Las lecturas de antes de C-0482 no llevan número: se miden igual.
    lineas = [l[4:] for l in lineas_del_sondeo("mac-es")]
    assert teclados.construir(lineas, "de antes")["crudas"] == \
        teclados.construir(lineas_del_sondeo("mac-es"), "de ahora")["crudas"]
    mezcladas = lineas_del_sondeo("mac-es")
    mezcladas[40] = mezcladas[40][4:]
    with pytest.raises(ValueError, match="no lleva su número"):
        teclados.construir(mezcladas, "mezclado")


def test_un_teclado_cuya_fila_de_numeros_no_da_cifras_lo_dice():
    # En la francesa del Mac, la fila de números sin Mayús da «&é"'(§è!çà».
    francesa = str.maketrans("1234567890", "&é\"'(§è!çà")
    lineas = [l[:3].translate(francesa) + l[3:] for l in lineas_del_sondeo("mac-es")]
    with pytest.raises(ValueError, match="no da cifras"):
        teclados.construir(lineas, "francés")


def test_un_sondeo_con_comillas_tipograficas_se_rechaza():
    # TextEdit con «Comillas inteligentes»: «'» llega como «’» y «"» como «”».
    lineas = [l.replace("'", "’").replace('"', "”") for l in lineas_del_sondeo("mac-us", reservadas=())]
    with pytest.raises(ValueError, match="comillas inteligentes"):
        teclados.construir(lineas, "con sustituciones")


def test_los_compuestos_se_deducen_pero_no_se_teclean_hasta_verificarlos():
    b = teclados.guardar(teclados.construir(lineas_del_sondeo("mac-es"), "Español medido"))
    borrador = teclados.distribucion_del_borrador(b)
    assert [str(p) for p in hid.caracter("á", borrador)] == ["'", "a"]  # muerta + letra, por NFC
    assert b["id"] not in {d["id"] for d in teclados.disponibles()}
    with pytest.raises(ValueError, match="no está verificada"):
        teclados.resolver(b["id"])


# ── probar y comprobar ──────────────────────────────────────────────────────
def test_la_consulta_dobla_las_comillas_y_evita_lo_que_el_cliente_toma_por_variables():
    b = teclados.construir(lineas_del_sondeo("mac-es"), "Español medido")
    consulta, ronda = teclados.consulta(b)
    assert "ronda" not in b or b["ronda"] is None  # se apunta al acabar de teclearla, no antes
    filas = ronda["filas"]
    assert [n for n, _, _ in filas] == list(range(1001, 1001 + len(filas)))
    assert all(1 <= len(t) <= 10 for _, t, _ in filas)
    literales = re.findall(r"N'((?:[^']|'')*)'", consulta)
    assert [l.replace("''", "'") for l in literales] == [t for _, t, _ in filas]
    assert "''" in consulta  # la comilla, doblada al teclearla
    assert "?" not in consulta  # hasta que la comilla esté verificada
    assert "${" not in consulta and not re.search(r":[A-Za-z_]", consulta)
    # La huella se calcula sobre la comilla simple, que es lo que guarda la base.
    con_comilla = next(t for _, t, _ in filas if "'" in t)
    assert teclados._huella(con_comilla, "SQL Server") == teclados.huellas.calcular(
        [con_comilla], "sha256", "utf-16-le", "LF", False)


def test_una_fila_que_no_coincide_solo_deja_sin_verificar_sus_caracteres():
    sim = Simulador(lineas=[""], fuente="mac-es")
    b = teclados.construir(lineas_del_sondeo("mac-es"), "Español medido")
    r = una_ronda(b, sim, estropear=1003)
    mala = next(f for f in r["filas"] if f["n"] == 1003)
    assert mala["estado"] == "no coincide"
    # Las demás coinciden, salvo las de «ý Ý»: se deducen por NFC, pero la española
    # de Apple no las compone, y lo deducido falla en su fila (después, se descarta).
    assert all(f["estado"] == "coincide" for f in r["filas"] if f["n"] != 1003 and not set(f["texto"]) & set("ýÝ"))
    sospechosos = set(b["sospechosos"])
    fallidas = [f for f in r["filas"] if f["estado"] == "no coincide"]
    assert sospechosos == {c for f in fallidas for c in f.get("prueba", f["texto"])}
    # La ronda siguiente los prueba uno a uno, para saber cuál era.
    _, ronda = teclados.consulta(b)
    solos = {p for _, _, p in ronda["filas"] if len(p) == 1}
    assert sospechosos <= solos


def test_un_dudoso_a_la_vista_se_resuelve_con_la_huella_de_su_fila():
    # En «Español - ISO», Mayús+Opción+[ da «ˆ» (U+02C6) y la iso sin nada «º»;
    # quien lee las confunde con «^» y «°». La huella lo corrige sin preguntar.
    lineas = lineas_del_sondeo("mac-es")
    lineas = cambiar(lineas, {"xˆ x": "x^ x", "xº x": "x° x"})
    b = teclados.construir(lineas, "Español mal leído")
    borrador = teclados.distribucion_del_borrador(b)
    assert [str(p) for p in hid.caracter("°", borrador)] == ["iso"]  # mal: la iso da «º»
    sim = Simulador(lineas=[""], fuente="mac-es")
    r = una_ronda(b, sim)
    corregidos = {k: v for f in r["filas"] for k, v in f.get("corregidos", {}).items()}
    assert corregidos == {"^": "ˆ", "°": "º"}
    for _ in range(6):
        try:
            una_ronda(b, sim)
        except ValueError:
            break
    medida = teclados.resolver(teclados.guardar(b)["id"])
    for c in "^ˆº°":
        assert medida.tabla[c] == hid.MAC_ES.tabla[c], c


def test_unas_huellas_de_una_consulta_vieja_se_rechazan():
    b = teclados.construir(lineas_del_sondeo("mac-es"), "Español medido")
    teclados.empezar_ronda(b, teclados.consulta(b)[1])
    with pytest.raises(ValueError, match="consulta vieja"):
        teclados.comprobar(b, "999001 9 0123456789ABCDEF")


def test_una_medida_rota_no_impide_arrancar_ni_elegir_las_demas():
    medida_verificada()
    (teclados.carpeta() / "medida-20260101-0000.json").write_text("{roto")
    estados = {m["id"]: m["estado"] for m in teclados.medidas()}
    assert estados["medida-20260101-0000"] == "ilegible"
    ids = [d["id"] for d in teclados.disponibles()]
    assert ids[:2] == ["mac-us", "mac-es"] and len(ids) == 3
    with puente_simulado() as (c, _):
        assert c.get("/ajustes").status_code == 200
        assert c.get("/panel").status_code == 200


# ── de punta a punta, por la API y las herramientas de Claude ───────────────
def test_calibrar_un_mac_con_una_fuente_que_el_puente_no_tiene_de_punta_a_punta(monkeypatch):
    config.guardar_ajustes({**config.AJUSTES_POR_OMISION,
                            "perfil": {**config.PERFIL_POR_OMISION, "distribucion": "mac-es", "retardo_tecla_ms": 2}})
    sim = Simulador(lineas=[""], fuente=fuente_de_prueba())
    with TestClient(crear_app(sim, hosts={"testserver"})) as c:
        mcp_contra(c, monkeypatch)

        def dar():
            c.post("/api/control", json={"accion": "dar"}, headers=PERSONA)

        # Lo que pasó: con «Español - ISO», el HTML sale cambiado.
        dar()
        assert c.post("/api/teclear", json={"texto": HTML}).status_code == 200
        assert sim.editor.lineas != [HTML] and "|" in sim.editor.lineas[0]

        # Sondear sin control no teclea nada.
        vaciar(sim)
        c.post("/api/control", json={"accion": "retomar"}, headers=PERSONA)
        assert c.post("/api/teclado/sondear").status_code == 423
        assert sim.editor.lineas == [""]

        dar()
        assert asyncio.run(mcp_servidor.sondear_teclado())["lineas"] == teclados.LINEAS_SONDEO
        sim.editor.guardado = list(sim.editor.lineas)  # lo que «muestra» la pestaña, para el lector
        r = c.post("/api/lecturas", json={"nombre": "sondeo del teclado"})
        esperar(c)
        lectura = r.json()["id"]
        transcribir_como_oraculo(c, sim, lectura)
        medida = asyncio.run(mcp_servidor.medir_teclado(lectura, "Latinoamericano"))
        assert medida["estado"] == "sin verificar" and re.fullmatch(r"medida-\d{8}-\d{4}", medida["id"])

        resultado = None
        for _ in range(4):
            dar()
            vaciar(sim)
            try:
                asyncio.run(mcp_servidor.probar_teclado(medida["id"]))
            except mcp_servidor.ErrorPuente as e:
                assert "nada por verificar" in str(e)
                break
            # Teclear la consulta devuelve el Mac a la persona, que es quien la ejecuta
            # (sin hooks de Claude: con ellos, lo devuelve el Stop de su turno, C-0486).
            assert c.get("/api/estado").json()["control"]["modo"] == "libre"
            resultado = asyncio.run(mcp_servidor.comprobar_teclado(
                medida["id"], rejilla(ejecutar_como_sql_server(sim.editor.lineas))))
        assert resultado and resultado["elegible"] and resultado["estado"] == "verificada"

        # Verificada no es activada: la activa la persona.
        assert config.leer_ajustes()["perfil"]["distribucion"] == "mac-es"
        usar = {"perfil": {"distribucion": medida["id"]}}
        assert c.post("/api/ajustes", json=usar).status_code == 403  # sin Origin: no es la persona
        assert c.post("/api/ajustes", json=usar, headers=PERSONA).status_code == 200

        dar()
        vaciar(sim)
        texto = HTML + " ¿Año? ñandú, pingüino ^ ˆ"
        assert c.post("/api/teclear", json={"texto": texto}).status_code == 200
        assert sim.editor.lineas == [texto]
        assert c.get("/api/teclado").json()["activa"] == medida["id"]


def test_una_medida_sin_verificar_no_se_puede_elegir_en_ajustes():
    b = teclados.guardar(teclados.construir(lineas_del_sondeo("mac-es"), "Español medido"))
    with puente_simulado() as (c, _):
        r = c.post("/api/ajustes", json={"perfil": {"distribucion": b["id"]}}, headers=PERSONA)
        assert r.status_code == 400 and "sin verificar" in r.json()["detail"]
        assert config.leer_ajustes()["perfil"]["distribucion"] == "mac-us"


def test_las_herramientas_que_teclean_preguntan_y_las_que_calculan_no():
    from puente_kvm import repertorio
    reglas = repertorio.reglas()
    for t in ("sondear_teclado", "probar_teclado"):
        assert f"mcp__puente-kvm__{t}" in reglas["ask"]
        assert t in repertorio.NECESITA_CONTROL
    for t in ("medir_teclado", "comprobar_teclado"):
        assert f"mcp__puente-kvm__{t}" in reglas["allow"]
    # Las medidas las escribe el puente al verificarlas, no Claude a mano.
    assert "Edit(~/.local/share/puente-kvm/teclados/**)" in reglas["deny"]


# ── lo que encontró el revisor ──────────────────────────────────────────────
def test_una_tecla_muerta_leida_como_normal_no_queda_verificada_ni_escribe_otra_cosa():
    # «x´x» leído «x´ x»: el borrador cree que la tecla da «´» sola. Seguida de «<» o
    # de la comilla de cierre, la muerta escribe «´<» igual que una normal y su fila
    # coincidía; después, «'´e'» salía «'é'». Con su letra detrás, la huella la caza.
    lineas = cambiar(lineas_del_sondeo("mac-es"), {"x´x": "x´ x"})
    b = teclados.guardar(teclados.construir(lineas, "mal leída"))
    muerta = [(0, "'")]
    assert [list(p) for p in teclados.distribucion_del_borrador(b).tabla["´"]] == [list(p) for p in muerta]
    sim = Simulador(lineas=[""], fuente="mac-es")
    for _ in range(6):
        try:
            una_ronda(b, sim)
        except ValueError:
            break
    assert ["´", "'"] in b["descartes"]  # la huella probó que esa tecla, sola, no da «´»
    r = teclados.resumen(teclados.guardar(b))
    if r["elegible"]:
        medida = teclados.resolver(b["id"])
        assert medida.tabla.get("´") != ((0, "'"),)
        texto = "SELECT '´e' -- x´a" if "´" in medida.tabla else "SELECT 'e' -- xa"
        vaciar(sim)
        pulsar_en(sim, hid.secuencia(texto, medida, ["alt+x"]))
        assert sim.editor.lineas == [texto]


def test_con_bloq_mayus_al_probar_se_rechaza_la_ronda_sin_apuntar_nada():
    sim = Simulador(lineas=[""], fuente="mac-es")
    b = teclados.construir(lineas_del_sondeo("mac-es"), "Español medido")
    consulta, ronda = teclados.consulta(b, reservadas=["alt+x"])
    pulsar_en(sim, hid.secuencia(consulta, teclados.distribucion_del_borrador(b), ["alt+x"]))
    teclados.empezar_ronda(b, ronda)
    # Lo que daría la base si las letras hubieran salido en mayúsculas.
    import hashlib
    filas = {}
    for n, t, _ in ronda["filas"]:
        m = "".join(c.upper() if len(c.upper()) == 1 else c for c in t)
        filas[n] = {"largo": len(m), "huella": hashlib.sha256(m.encode("utf-16-le")).hexdigest()[:16].upper()}
    with pytest.raises(ValueError, match="Bloq Mayús"):
        teclados.comprobar(b, filas)
    assert b["verificados"] == {} and b["descartes"] == [] and b["ronda"] == ronda


def test_una_huella_corta_o_vacia_no_verifica_ni_descarta_nada():
    assert teclados._buscar_uno("SQL Server", "") is None
    assert teclados._buscar_uno("SQL Server", "4F") is None
    b = teclados.construir(lineas_del_sondeo("mac-es"), "Español medido")
    _, ronda = teclados.consulta(b)
    teclados.empezar_ronda(b, ronda)
    r = teclados.comprobar(b, {n: {"largo": 1, "huella": "4F"} for n, _, _ in ronda["filas"]})
    assert {f["estado"] for f in r["filas"]} == {"sin huella"}
    assert b["verificados"] == {} and b["descartes"] == []


def test_la_consulta_no_lleva_lo_que_necesita_una_tecla_reservada():
    # Un sondeo hecho sin reservas pulsó Opción+X: «≈» está en la tabla.
    b = teclados.construir(lineas_del_sondeo("mac-us", reservadas=()), "U.S. medido")
    assert "≈" in teclados.distribucion_del_borrador(b).tabla
    assert any("≈" in p for _, _, p in teclados.consulta(b)[1]["filas"])
    assert not any("≈" in p for _, _, p in teclados.consulta(b, reservadas=["alt+x"])[1]["filas"])


def test_sin_hooks_si_probar_falla_a_mitad_el_control_vuelve_y_la_ronda_no_se_apunta(monkeypatch):
    from puente_kvm.motor import Motor
    b = teclados.guardar(teclados.construir(lineas_del_sondeo("mac-es"), "Español medido"))
    with puente_simulado() as (c, _):
        async def corta(self, *a, **k):
            raise RuntimeError("se cortó el USB a mitad")
        monkeypatch.setattr(Motor, "teclear", corta)
        c.post("/api/control", json={"accion": "dar"}, headers=PERSONA)
        r = c.post("/api/teclado/probar", json={"medida": b["id"]})
        assert r.status_code == 500 and "se cortó" in r.json()["detail"]
        assert c.get("/api/estado").json()["control"]["modo"] == "libre"
    guardada = teclados.cargar(b["id"])
    assert guardada["ronda"] is None and guardada["rondas"] == 0


def test_leer_documento_con_zona_captura_esa_ventana_y_una_zona_fuera_de_pantalla_se_rechaza(monkeypatch):
    # El sondeo se lee en la ventana de un texto plano, no en la región del
    # editor de Ajustes (C-0482).
    from PIL import Image

    from puente_kvm import lecturas

    with puente_simulado(lineas=40) as (c, _):
        mcp_contra(c, monkeypatch)
        c.post("/api/control", json={"accion": "dar"}, headers=PERSONA)
        fuera = c.post("/api/lecturas", json={"nombre": "x", "x": 1800, "y": 0, "ancho": 400, "alto": 300})
        assert fuera.status_code == 400 and "se sale" in fuera.text
        a_medias = c.post("/api/lecturas", json={"nombre": "x", "x": 10, "y": 10, "ancho": 400})
        assert a_medias.status_code == 400
        r = asyncio.run(mcp_servidor.leer_documento("sondeo del teclado", x=40, y=60, ancho=700, alto=500))
        l = lecturas.cargar(r["id"])
        assert l.zona == [40, 60, 700, 500] and l.paginas
        assert Image.open(l.png(1)).size == (700, 500)
        # Sin zona, como siempre: la región del editor. (Al capturar, el control volvió.)
        c.post("/api/control", json={"accion": "dar"}, headers=PERSONA)
        r = asyncio.run(mcp_servidor.leer_documento("procedimiento"))
        x, y, w, h = config.leer_ajustes()["perfil"]["region_editor"]
        assert lecturas.cargar(r["id"]).zona is None
        assert Image.open(lecturas.cargar(r["id"]).png(1)).size == (w, h)
