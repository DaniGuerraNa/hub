"""Las mediciones de uso: sólo números, sí/no y palabras de una lista cerrada (C-0483).

La persona que tiene el aparato las manda tras unos días de uso. Lo que se
prueba aquí es lo que no se puede negociar: que lo tecleado, lo leído y los
nombres no llegan ni a los archivos ni al .zip (el canario), que lo que no casa
con la lista no se escribe ni se empaqueta, y que medir no rompe nada.
"""

import asyncio
import io
import json
import time
import uuid
import zipfile
from datetime import date, timedelta

import pytest

from puente_kvm import config, conversaciones, mcp_servidor, mediciones, teclados

from .ayuda import (PERSONA, ejecutar_como_sql_server, esperar, mcp_contra, puente_simulado, rejilla,
                    transcribir_como_oraculo)

CANARIO = "CANARIO_ZX9"
NOMBRE = "CANARIO_NOMBRE"


def lineas_guardadas() -> list[dict]:
    salida = []
    for f in sorted(mediciones.carpeta().glob("*.jsonl")):
        salida += [json.loads(l) for l in f.read_text().splitlines() if l.strip()]
    return salida


def textos_guardados() -> str:
    return "".join(f.read_text() for f in mediciones.carpeta().glob("*")) if mediciones.carpeta().exists() else ""


def textos_del_zip(datos: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(datos)) as z:
        return "".join(z.read(n).decode() for n in z.namelist())


def de(tipo: str, **filtro) -> list[dict]:
    return [l for l in lineas_guardadas() if l["tipo"] == tipo and all(l.get(k) == v for k, v in filtro.items())]


def hook(c, evento: str, sesion: str, **extra) -> None:
    assert c.post("/api/claude/actividad", json={"hook_event_name": evento, "session_id": sesion,
                                                 **extra}).status_code == 200


def herramienta(_nombre: str, **args):
    """Por el servidor MCP de verdad (`call_tool`), con su envoltorio: es él quien mide."""
    return asyncio.run(mcp_servidor.mcp.call_tool(_nombre, args))


# ── 🔴 el canario ───────────────────────────────────────────────────────────
def test_lo_tecleado_lo_leido_y_los_nombres_no_llegan_ni_a_los_archivos_ni_al_zip(monkeypatch):
    with puente_simulado() as (c, sim):
        mcp_contra(c, monkeypatch)
        conv = conversaciones.nueva(NOMBRE, "")
        conversaciones.marcar_abierta(conv.id)
        sesion = conv.id

        def dar():
            assert c.post("/api/control", json={"accion": "dar"}, headers=PERSONA).status_code == 200

        # Un turno de Claude, con lo que traen sus hooks (que lleva contenido).
        hook(c, "UserPromptSubmit", sesion, prompt=f"lee {NOMBRE} y escribe {CANARIO}")
        dar()
        hook(c, "PreToolUse", sesion, tool_name="mcp__puente-kvm__teclear", tool_input={"texto": CANARIO})
        herramienta("teclear", texto=CANARIO + "\n")
        hook(c, "PreToolUse", sesion, tool_name="Read", tool_input={"file_path": f"/trabajo/{NOMBRE}.sql"})

        # Leer, con el nombre del canario, por la herramienta (espera a que acabe).
        sim.editor.guardado = list(sim.editor.lineas)
        hook(c, "PreToolUse", sesion, tool_name="mcp__puente-kvm__leer_documento", tool_input={"nombre": NOMBRE})
        herramienta("leer_documento", nombre=NOMBRE)
        lid = c.get("/api/estado").json()["lecturas"][0]["id"]
        assert c.get(f"/api/lecturas/{lid}").json()["nombre"] == NOMBRE
        transcribir_como_oraculo(c, sim, lid)
        herramienta("comprobar_huella", lectura=lid, huella=sim.estado()["huella_base"])

        # Proponer, aprobar y escribir un cambio que lleva el canario.
        nuevo = list(sim.editor.guardado)
        nuevo[3] += f" -- {CANARIO}"
        herramienta("proponer_cambio", lectura=lid, descripcion=NOMBRE, texto="\n".join(nuevo))
        cid = c.get("/api/estado").json()["cambios"][0]["id"]
        assert c.post(f"/api/cambios/{cid}/aprobar", headers=PERSONA).status_code == 200
        herramienta("escribir_cambio", cambio=cid)
        esperar(c)
        assert any(CANARIO in l for l in sim.editor.lineas)
        hook(c, "Stop", sesion)

        # Una corrección con el canario, aprobada por el permiso de correcciones
        # pequeñas (C-0489): la aprobación la mide el puente, no un clic.
        sim.editor.guardado = list(sim.editor.lineas)  # la persona guardó lo escrito
        hook(c, "UserPromptSubmit", sesion, prompt=f"corrige {NOMBRE} con {CANARIO}")
        assert c.post("/api/control", json={"accion": "dar", "correcciones": True},
                      headers=PERSONA).status_code == 200
        herramienta("leer_documento", nombre=NOMBRE)
        lid2 = next(l["id"] for l in c.get("/api/estado").json()["lecturas"] if l["id"] != lid)
        transcribir_como_oraculo(c, sim, lid2)
        herramienta("comprobar_huella", lectura=lid2, huella=sim.estado()["huella_base"])
        nuevo = list(sim.editor.guardado)
        nuevo[5] += f" -- {CANARIO}_2"
        herramienta("proponer_cambio", lectura=lid2, descripcion=NOMBRE, texto="\n".join(nuevo))
        cid2 = next(x["id"] for x in c.get("/api/estado").json()["cambios"] if x["id"] != cid)
        assert c.get(f"/api/cambios/{cid2}").json()["estado"] == "aprobado"  # sin ningún clic
        herramienta("escribir_cambio", cambio=cid2)
        esperar(c)
        assert any(f"{CANARIO}_2" in l for l in sim.editor.lineas)
        hook(c, "Stop", sesion)

        # La persona usa el Mac y pega el canario: le quita el control a Claude.
        dar()
        with c.websocket_connect("/ws/mando", headers=PERSONA) as ws:
            ws.receive_json()
            ws.send_text(json.dumps({"t": "pegar", "texto": CANARIO}))
            assert ws.receive_json().get("hecho") == "pegar"
            ws.send_text(json.dumps({"t": "raton", "x": 5, "y": 5, "b": 1}))
            ws.send_text(json.dumps({"t": "raton", "x": 5, "y": 5, "b": 0}))

        # Calibrar el teclado con una medida que se llama como el canario.
        dar()
        sim.editor.lineas, sim.editor.cursor, sim.editor.ancla = [""], (0, 0), None
        herramienta("sondear_teclado")
        r = c.post("/api/teclado/medir", json={"texto": "\n".join(sim.editor.lineas), "nombre": NOMBRE})
        assert r.status_code == 200, r.text
        medida = r.json()["id"]
        dar()
        sim.editor.lineas, sim.editor.cursor, sim.editor.ancla = [""], (0, 0), None
        herramienta("probar_teclado", medida=medida)
        herramienta("comprobar_teclado", medida=medida, huellas=rejilla(ejecutar_como_sql_server(sim.editor.lineas)))
        assert teclados.cargar(medida)["nombre"] == NOMBRE

        mediciones.SUMAS.volcar({"modo": "mjpeg", "conectado": True})
        zip_de_la_persona = c.post("/api/mediciones/preparar", headers=PERSONA)
        assert zip_de_la_persona.status_code == 200
        # La prueba sirve: el canario pasó por el puente (la bitácora sí lo lleva, a propósito).
        assert NOMBRE in json.dumps(c.get("/api/bitacora").json(), ensure_ascii=False)

    tipos = {l["tipo"] for l in lineas_guardadas()}
    assert {"herramienta", "espera", "tras", "lectura", "cambio", "control", "mando", "calibracion", "turno",
            "contexto", "teclado", "raton", "conexion"} <= tipos, tipos
    guardado = textos_guardados()
    empaquetado = textos_del_zip(zip_de_la_persona.content) + textos_del_zip(mediciones.empaquetar())
    for texto in (guardado, empaquetado):
        assert CANARIO not in texto and NOMBRE not in texto and "CANARIO" not in texto
        assert "/trabajo" not in texto and "usp_" not in texto
    # Y se midió lo que pasó, con su clase.
    assert {"teclear", "leer_documento", "proponer_cambio", "escribir_cambio"} <= {l["nombre"] for l in
                                                                                 de("herramienta")}
    assert de("cambio", evento="escritura", ok=True, fallo="ninguno")
    # Una aprobación por cada camino, y una sola línea cada una: la API no la mide aparte.
    aprobados = de("cambio", evento="aprobado")
    assert sorted(l["por"] for l in aprobados) == ["correcciones", "persona"], aprobados
    for l in aprobados + de("cambio", evento="propuesta", ok=True):
        assert l["lineas"] == 2 and l["caracteres"] > 0
    assert {l["por"] for l in de("cambio", evento="escritura", ok=True)} == {"persona", "correcciones"}
    assert de("control", evento="dado", correcciones=True)
    assert de("mando", pegados=1, clics=1, retomo=True)
    assert de("control", evento="devuelto", por="usar_mac")
    assert de("turno", conversacion=True, fin="stop", lecturas=1, otras=1)


# ── la lista cerrada ────────────────────────────────────────────────────────
def test_validar_acepta_numeros_si_no_y_palabras_de_su_lista():
    mediciones.validar("tras", {"ms_cambio": 1250, "cambio": True, "quieta": True, "antes_quieta": False,
                                "tope_ms": 4000, "ms": 1600.5, "ms_antes": None, "clase": "pagina", "t": 3.2,
                                "a": 7})
    mediciones.validar("contexto", {"version": "0.1.0", "firmware": "0.5.11", "claude_code": "2.1.322"})


@pytest.mark.parametrize("tipo, valores", [
    ("tras", {"ms": 10, "texto": "SELECT 1"}),  # una clave de más
    ("lectura", {"nombre": "usp_Algo"}),  # el nombre de una lectura no es una clave
    ("herramienta", {"nombre": "SELECT * FROM clientes"}),  # una cadena libre donde va la lista
    ("control", {"por": "la persona se fue a comer"}),  # un motivo fuera de la lista
    ("tras", {"clase": "Pagina"}),
    ("tras", {"ms": "1200"}),  # un número escrito como texto
    ("tras", {"ms": True}),  # un sí/no no es un número
    ("tras", {"cambio": 1}),
    ("tras", {"ms": float("nan")}),
    ("tras", {"ms": 10**13}),
    ("contexto", {"version": "0.1.0 de Ana"}),
    ("contexto", {"firmware": "dev-build"}),
    ("tras", {"ms": [1, 2]}),
    ("tras", {"ms": {"x": 1}}),
    ("inventado", {"ms": 1}),
])
def test_validar_rechaza_claves_de_mas_cadenas_libres_y_valores_fuera_de_la_lista(tipo, valores):
    with pytest.raises(mediciones.NoValida) as e:
        mediciones.validar(tipo, valores)
    # El mensaje sale al registro del servicio: nunca con el valor.
    for v in valores.values():
        if isinstance(v, str) and len(v) > 3:
            assert v not in str(e.value)


def test_ninguna_clave_del_esquema_es_texto_libre():
    for tipo, claves in mediciones.ESQUEMA.items():
        for clave, clase in claves.items():
            assert clase in (mediciones.NUMERO, mediciones.SI_NO, mediciones.VERSION) or (
                isinstance(clase, frozenset) and all(isinstance(v, str) for v in clase)), (tipo, clave)


def test_la_lista_de_herramientas_es_la_de_las_registradas_en_el_mcp():
    registradas = {t.name for t in asyncio.run(mcp_servidor.mcp.list_tools())}
    assert mediciones.HERRAMIENTAS == registradas


# ── apuntar ─────────────────────────────────────────────────────────────────
def test_apuntar_escribe_una_linea_de_hoy_con_hora_relativa_al_arranque():
    assert mediciones.apuntar("espera", ms=120, quieta=True, capturas=2, dif_min=0.004, tope_ms=4000)
    archivo = mediciones.carpeta() / f"{date.today().isoformat()}.jsonl"
    linea = json.loads(archivo.read_text())
    assert linea["tipo"] == "espera" and linea["a"] == mediciones.ARRANQUE_ID
    assert 0 <= linea["t"] < time.monotonic() - mediciones.ARRANQUE + 1  # segundos desde el arranque, no una hora


def test_apuntar_nunca_lanza_y_lo_que_no_valida_no_se_escribe(monkeypatch, capsys):
    assert mediciones.apuntar("tras", ms=10, texto=CANARIO) is False
    assert mediciones.apuntar("inventado", x=1) is False
    assert mediciones.apuntar("tras", ms=object()) is False
    assert not mediciones.carpeta().exists() or not list(mediciones.carpeta().glob("*.jsonl"))
    assert CANARIO not in capsys.readouterr().err
    # Un disco que no deja escribir tampoco lanza.
    monkeypatch.setattr(mediciones, "carpeta", lambda: config.hogar() / "ajustes.json" / "no")
    config.guardar_ajustes(config.leer_ajustes())
    assert mediciones.apuntar("tras", ms=10) is False


def test_con_el_interruptor_apagado_no_se_escribe_nada():
    with puente_simulado(lineas=40) as (c, sim):
        r = c.post("/api/ajustes", json={"mediciones": {"activas": False}}, headers=PERSONA)
        assert r.status_code == 200 and r.json()["mediciones"]["activas"] is False
        mediciones.borrar()  # lo del arranque
        c.post("/api/control", json={"accion": "dar"}, headers=PERSONA)
        assert c.post("/api/teclear", json={"texto": "hola"}).status_code == 200
        assert c.post("/api/lecturas", json={"nombre": "x"}).status_code == 200
        esperar(c)
        assert c.post("/api/mediciones/herramienta", json={"nombre": "teclear", "ms": 5, "ok": True,
                                                          "error": "ninguno"}).status_code == 200
        mediciones.SUMAS.volcar({"modo": "mjpeg", "conectado": True})
        assert mediciones.apuntar("tras", ms=1) is False
    assert not list(mediciones.carpeta().glob("*.jsonl"))
    assert config.leer_ajustes()["mediciones"] == {"activas": False}


def test_un_interruptor_que_no_es_verdadero_o_falso_se_rechaza_y_no_cambia_nada():
    """Lo encontró el revisor de C-0483: `{"activas": "false"}` como texto las
    dejaba encendidas y contestaba 200, como si se hubieran apagado."""
    with puente_simulado(lineas=40) as (c, _):
        for valor in ("false", "no", 0, None, [], {}):
            r = c.post("/api/ajustes", json={"mediciones": {"activas": valor}}, headers=PERSONA)
            assert r.status_code == 400, valor
            assert "verdadero o falso" in r.json()["detail"]
        assert c.post("/api/ajustes", json={"mediciones": "apagadas"}, headers=PERSONA).status_code == 400
        assert mediciones.activas() is True
        assert c.post("/api/ajustes", json={"mediciones": {"activas": False}}, headers=PERSONA).status_code == 200
        assert mediciones.activas() is False


def test_vienen_encendidas_de_fabrica_y_se_apagan_aunque_haya_una_tarea_en_marcha():
    assert mediciones.activas() is True
    with puente_simulado(lineas=400, retardo_ms=60) as (c, _):
        c.post("/api/control", json={"accion": "dar"}, headers=PERSONA)
        assert c.post("/api/lecturas", json={"nombre": "larga"}).status_code == 200
        time.sleep(0.3)
        assert c.get("/api/estado").json()["tarea"]
        # Otros ajustes esperan a que acabe; el interruptor, no.
        assert c.post("/api/ajustes", json={"perfil": {"retardo_tecla_ms": 9}}, headers=PERSONA).status_code == 409
        assert c.post("/api/ajustes", json={"mediciones": {"activas": False}}, headers=PERSONA).status_code == 200
        assert mediciones.activas() is False
        c.post("/api/control", json={"accion": "parar"}, headers=PERSONA)
        esperar(c)


def test_la_poda_borra_los_dias_de_hace_mas_de_un_mes_y_nada_mas():
    carpeta = mediciones.carpeta()
    carpeta.mkdir(parents=True)
    hoy = date.today()
    for dias in (0, 29, 30, 31, 90):
        (carpeta / f"{(hoy - timedelta(days=dias)).isoformat()}.jsonl").write_text("")
    (carpeta / "otra-cosa.txt").write_text("")
    assert mediciones.podar() == 2
    quedan = sorted(f.name for f in carpeta.iterdir())
    assert quedan == sorted([f"{(hoy - timedelta(days=d)).isoformat()}.jsonl" for d in (0, 29, 30)]
                            + ["otra-cosa.txt"])


# ── empaquetar ──────────────────────────────────────────────────────────────
def test_empaquetar_deja_fuera_una_linea_tocada_a_mano():
    assert mediciones.apuntar("tras", ms=900, cambio=True, clase="pagina")
    assert mediciones.apuntar("control", evento="dado")
    archivo = mediciones.carpeta() / f"{date.today().isoformat()}.jsonl"
    with archivo.open("a") as f:
        f.write(json.dumps({"tipo": "tras", "ms": 1, "nota": CANARIO}) + "\n")  # una clave de más
        f.write(json.dumps({"tipo": "control", "por": CANARIO}) + "\n")  # fuera de la lista
        f.write('{"tipo": "tras", "ms": 1, "ms": "%s"}\n' % CANARIO)  # la clave repetida: vale la última
        f.write("esto no es JSON " + CANARIO + "\n")
        f.write(json.dumps(["tras", CANARIO]) + "\n")
    with zipfile.ZipFile(io.BytesIO(mediciones.empaquetar())) as z:
        assert set(z.namelist()) == {"LEEME.txt", f"mediciones/{date.today().isoformat()}.jsonl"}
        lineas = z.read(f"mediciones/{date.today().isoformat()}.jsonl").decode().splitlines()
        leeme = z.read("LEEME.txt").decode()
    assert [json.loads(l)["tipo"] for l in lineas] == ["tras", "control"]
    assert CANARIO not in "".join(lineas)
    assert "(5 líneas)" in leeme and "No se manda nada solo" in leeme


def test_preparar_y_borrar_son_de_la_persona_y_el_estado_dice_dias_y_kb():
    with puente_simulado(lineas=5) as (c, _):
        assert c.post("/api/mediciones/preparar").status_code == 403  # sin Origin: el MCP o un curl
        assert c.post("/api/mediciones/borrar").status_code == 403
        otra = {"Origin": "http://otra.web"}
        assert c.post("/api/mediciones/preparar", headers=otra).status_code == 403
        assert c.post("/api/mediciones/borrar", headers=otra).status_code == 403
        assert c.post("/api/mediciones/herramienta", headers=otra, json={"nombre": "estado"}).status_code == 403
        e = c.get("/api/mediciones").json()
        assert e["activas"] is True and e["dias"] == 1 and e["texto"].startswith("Guardadas: 1 día, ")
        assert "KB" in c.get("/ajustes").text and "Mediciones de uso" in c.get("/ajustes").text
        r = c.post("/api/mediciones/preparar", headers=PERSONA)
        assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
        assert "attachment" in r.headers["content-disposition"]
        assert "LEEME.txt" in zipfile.ZipFile(io.BytesIO(r.content)).namelist()
        r = c.post("/api/mediciones/borrar", headers=PERSONA)
        assert r.status_code == 200 and r.json()["dias"] == 0
        assert r.json()["texto"] == "Aún no hay mediciones guardadas."


def test_una_herramienta_que_manda_algo_de_mas_no_se_apunta():
    with puente_simulado(lineas=5) as (c, _):
        mediciones.borrar()
        for cuerpo in ({"nombre": "teclear", "ms": 5, "texto": CANARIO}, {"nombre": CANARIO, "ms": 5},
                       {"nombre": "teclear", "ms": 5, "hueco_ms": 1}, []):
            r = c.post("/api/mediciones/herramienta", json=cuerpo)
            assert r.status_code == 400 and CANARIO not in r.text
    assert not de("herramienta")


# ── lo que mide el servicio ─────────────────────────────────────────────────
def test_el_servicio_calcula_lo_que_piensa_claude_entre_dos_herramientas():
    with puente_simulado(lineas=5) as (c, _):
        sesion = str(uuid.uuid4())
        hook(c, "UserPromptSubmit", sesion)
        time.sleep(0.05)
        uno = {"nombre": "estado", "ms": 10, "ok": True, "error": "ninguno"}
        assert c.post("/api/mediciones/herramienta", json=uno).status_code == 200
        time.sleep(0.3)
        assert c.post("/api/mediciones/herramienta", json={**uno, "nombre": "ver_pantalla"}).status_code == 200
    primera, segunda = de("herramienta")
    assert primera["hueco_ms"] is None and primera["desde_mensaje_ms"] >= 30
    assert segunda["desde_mensaje_ms"] is None and 250 <= segunda["hueco_ms"] < 2000


def test_el_error_de_una_herramienta_se_mide_por_su_clase_y_medir_no_la_rompe(monkeypatch):
    with puente_simulado(lineas=5) as (c, _):
        mcp_contra(c, monkeypatch)
        with pytest.raises(Exception, match="control"):
            herramienta("teclear", texto=CANARIO)  # sin el control: 423
        # Que el envío de la medición reviente no cambia lo que devuelve la herramienta.
        def revienta(cuerpo):
            raise RuntimeError("el servicio no contesta")
        monkeypatch.setattr(mcp_servidor, "_enviar", revienta)
        assert herramienta("estado")
    l, = de("herramienta")
    assert l["nombre"] == "teclear" and l["ok"] is False and l["error"] == "sin_control"
    assert mcp_servidor.clase_de_error(mcp_servidor.ErrorPuente("x", estado=409)) == "ocupado"
    assert mcp_servidor.clase_de_error(mcp_servidor.ErrorPuente("zona mal")) == "local"


def test_cada_vuelta_del_control_dice_por_que(monkeypatch):
    from puente_kvm import control as control_mod
    with puente_simulado(lineas=5) as (c, _):
        conv = conversaciones.nueva("Encargo", "")
        conversaciones.marcar_abierta(conv.id)
        dar = lambda: c.post("/api/control", json={"accion": "dar"}, headers=PERSONA)  # noqa: E731
        dar()
        hook(c, "UserPromptSubmit", conv.id)
        hook(c, "Stop", conv.id)
        dar()
        hook(c, "UserPromptSubmit", conv.id)
        hook(c, "PreToolUse", conv.id, tool_name="AskUserQuestion")
        dar()
        c.post("/api/control", json={"accion": "retomar"}, headers=PERSONA)
        dar()
        c.post("/api/control", json={"accion": "parar"}, headers=PERSONA)
        c.post("/api/control", json={"accion": "parar"}, headers=PERSONA)  # ya parado: no lo tenía Claude
        dar()
        p = c.app.state.puente
        p.control.ultima_accion -= control_mod.INACTIVIDAD_S + 1
        assert c.get("/api/estado").json()["control"]["modo"] == "libre"
    devueltos = [l["por"] for l in de("control", evento="devuelto")]
    assert devueltos == ["fin_turno", "pregunta", "retomar", "parar", "caducidad"]
    assert len(de("control", evento="dado")) == 5
    assert all(l["ms_con_claude"] >= 0 for l in de("control", evento="devuelto"))


def test_un_fin_de_turno_con_una_escritura_en_marcha_se_mide_al_acabarla_y_por_el_fin_de_turno():
    """C-0488: el `Stop` deja el control hasta que acaba la tarea. La medición
    dice lo que lo devolvió (el fin de turno, no el respaldo de la tarea) y
    cuánto lo tuvo Claude de verdad: hasta que acabó de escribir."""
    from .ayuda import leer, proponer_y_aprobar
    with puente_simulado() as (c, sim):
        conv = conversaciones.nueva("Encargo", "")
        conversaciones.marcar_abierta(conv.id)
        hook(c, "UserPromptSubmit", conv.id)
        lid = leer(c)
        transcribir_como_oraculo(c, sim, lid)
        nuevo = list(sim.editor.guardado)
        for i in range(10, 60):
            nuevo[i] += " -- una línea bastante larga añadida para que escribir tarde un buen rato"
        cid = proponer_y_aprobar(c, lid, nuevo, "muchas líneas")
        assert c.post(f"/api/cambios/{cid}/escribir").status_code == 200
        fin = time.time() + 20
        while c.get(f"/api/cambios/{cid}").json()["estado"] != "escribiendo":
            assert time.time() < fin
            time.sleep(0.02)
        p = c.app.state.puente
        hook(c, "Stop", conv.id)
        hasta_el_stop = time.time() - p.control.desde
        time.sleep(0.3)
        assert p.motor.tarea, "la escritura tenía que seguir en marcha tras el Stop"
        assert not de("control", evento="devuelto")  # aún no ha vuelto
        esperar(c)
        assert c.get("/api/estado").json()["control"]["modo"] == "libre"
    devueltos = de("control", evento="devuelto")
    assert [l["por"] for l in devueltos] == ["fin_turno"], devueltos
    assert devueltos[0]["ms_con_claude"] >= (hasta_el_stop + 0.3) * 1000


def test_un_turno_cuenta_sus_herramientas_y_un_mensaje_con_el_turno_abierto_es_un_esc():
    with puente_simulado(lineas=5) as (c, _):
        sesion = str(uuid.uuid4())
        hook(c, "UserPromptSubmit", sesion)
        for nombre in ("mcp__puente-kvm__leer_documento", "mcp__puente-kvm__leer_documento",
                       "mcp__puente-kvm__estado", "Bash"):
            hook(c, "PreToolUse", sesion, tool_name=nombre, tool_input={"command": CANARIO})
        hook(c, "UserPromptSubmit", sesion)
        hook(c, "PreToolUse", sesion, tool_name="mcp__puente-kvm__escribir_cambio")
        hook(c, "SessionEnd", sesion)
    cortado, cerrado = de("turno")
    assert cortado["fin"] == "cortado" and cortado["herramientas"] == 3 and cortado["lecturas"] == 2
    assert cortado["otras"] == 1 and cortado["conversacion"] is False
    assert cerrado["fin"] == "sesion_cerrada" and cerrado["cambios"] == 1
    assert CANARIO not in textos_guardados()


def test_tras_apunta_lo_que_tardo_el_cambio_con_su_clase():
    with puente_simulado(lineas=60) as (c, _):
        c.post("/api/control", json={"accion": "dar"}, headers=PERSONA)
        assert c.post("/api/lecturas", json={"nombre": "x"}).status_code == 200
        esperar(c)
    tras = de("tras")
    assert {l["clase"] for l in tras} == {"inicio", "pagina"}
    paginas = [l for l in tras if l["clase"] == "pagina"]
    assert paginas[-1]["cambio"] is False and paginas[-1]["ms_cambio"] is None  # el final: Av Pág ya no mueve
    assert all(l["ms_cambio"] is not None and l["ms_cambio"] <= l["tope_ms"] for l in paginas[:-1])
    quietas = [l for l in de("espera") if l["quieta"]]
    assert quietas and all(l["dif_min"] < 0.03 and l["capturas"] >= 2 for l in quietas)
    lectura, = de("lectura", evento="captura")
    assert lectura["estado"] == "capturada" and lectura["paginas"] >= 2 and lectura["con_zona"] is False


# ── las sumas ────────────────────────────────────────────────────────────
def test_el_volcado_de_sumas_sobrevive_a_una_excepcion(monkeypatch):
    sumas = mediciones.Sumas()
    vueltas = {"n": 0}

    def video():
        vueltas["n"] += 1
        if vueltas["n"] == 1:
            raise RuntimeError("el aparato no contesta")
        return {"modo": "h264", "conectado": True}

    original = sumas.volcar

    def volcar(extra):
        if vueltas["n"] == 2:
            raise OSError("disco lleno")
        return original(extra)
    monkeypatch.setattr(sumas, "volcar", volcar)

    async def correr():
        tarea = asyncio.create_task(mediciones.volcar_siempre(sumas, video, intervalo=0.02))
        for _ in range(5):
            sumas.sumar("fotogramas", 30)
            await asyncio.sleep(0.03)
        assert not tarea.done()
        tarea.cancel()
    asyncio.run(correr())
    assert vueltas["n"] >= 3
    videos = de("video")
    assert videos and all(l["modo"] == "h264" and l["conectado"] is True for l in videos[1:])


def test_un_minuto_sin_nada_no_escribe_salvo_el_video_conectado():
    sumas = mediciones.Sumas()
    assert sumas.volcar({"modo": "mjpeg", "conectado": False}) == 0
    assert sumas.volcar({"modo": "mjpeg", "conectado": True}) == 1
    sumas.sumar("pulsaciones", 12)
    sumas.sumar("ms_tecleando", 300.4)
    assert sumas.volcar({}) == 1
    teclado, = de("teclado")
    assert teclado["pulsaciones"] == 12 and teclado["ms_tecleando"] == 300
    assert de("video")[0]["fotogramas"] == 0


# ── el resumen ──────────────────────────────────────────────────────────────
def test_el_resumen_de_un_paquete_da_tiempos_por_herramienta_y_lo_que_tarda_el_video(tmp_path, monkeypatch, capsys):
    for ms in (100, 200, 300, 400, 1000):
        mediciones.apuntar("herramienta", nombre="ver_pantalla", ms=ms, ok=True, error="ninguno", hueco_ms=ms * 10)
    mediciones.apuntar("herramienta", nombre="teclear", ms=50, ok=False, error="sin_control")
    for ms_cambio in (800, 1200, 1900, None):
        mediciones.apuntar("tras", ms_cambio=ms_cambio, cambio=ms_cambio is not None, quieta=True, tope_ms=4000,
                           ms=2000, ms_antes=300, clase="pagina")
    mediciones.apuntar("control", evento="devuelto", por="fin_turno", ms_con_claude=60_000)
    mediciones.apuntar("cambio", evento="escritura", ok=False, fallo="pagina_distinta", tramos=2, escritos=0)
    mediciones.apuntar("video", s=60, fotogramas=1800, fps=30.0, cortes=1, conectado=True, modo="h264")
    zip_ = tmp_path / "paquete.zip"
    zip_.write_bytes(mediciones.empaquetar())
    from puente_kvm.__main__ import main
    monkeypatch.setattr("sys.argv", ["puente-kvm", "mediciones", "resumir", str(zip_)])
    main()
    texto = capsys.readouterr().out
    assert "ver_pantalla" in texto and "300 ms / 1000 ms" in texto  # p50 / p90
    assert "fallos   1 (sin_control 1)" in texto
    assert "1 sin cambio" in texto and "p50 1200 ms" in texto
    assert "fin_turno 1" in texto and "pagina_distinta 1" in texto
    assert "cortes 1" in texto and "p50 30.0" in texto
    assert "dos herramientas: p50 3000 ms" in texto  # lo que piensa Claude


def test_el_resumen_de_algo_que_no_es_un_zip_lo_dice_sin_traza(tmp_path, monkeypatch):
    falso = tmp_path / "no.zip"
    falso.write_text("hola")
    from puente_kvm.__main__ import main
    monkeypatch.setattr("sys.argv", ["puente-kvm", "mediciones", "resumir", str(falso)])
    with pytest.raises(SystemExit, match="no puedo leer"):
        main()
