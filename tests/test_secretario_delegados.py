"""Lo delegado vuelve, con su evidencia (decisión 384, C-0196 F2 y F3).

El secretario encarga al orquestador —con el proyecto, los adjuntos del hilo
y el asunto que delega—, y su aprobación vale como el sí del proyecto (279).
Cuando la tarea se cierra, `delegados.recoger` la dice en su chat una vez,
enmarcada como lo que cuenta el orquestador, con las imágenes de lo que se vio
en una tarjeta `imagenes`. La primera vez no inunda el chat con lo viejo.
"""

from __future__ import annotations

import base64
import io
import json
import sys

import pytest

from arnes_js import ejecutar, script_estatico
from hub import config, db, intercambio, orquestador
from hub.secretario import asuntos, conversacion, delegados, herramientas, mcp, memoria, piezas, servicio

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32


@pytest.fixture
def con(monkeypatch):
    monkeypatch.setenv("TZ", "America/Mexico_City")
    h = db.conectar(config.DB_PATH)
    db.inicializar(h)
    h.execute("INSERT INTO proyecto (id, nombre, dominio, status, tipo, guardrail)"
              " VALUES ('alfa', 'Alfa', 'personal', 'activo', 'proyecto', 'ask')")
    h.execute("INSERT INTO proyecto (id, nombre, dominio, status, tipo, guardrail)"
              " VALUES ('beta', 'Beta', 'personal', 'activo', 'proyecto', 'never')")
    h.commit()
    h.close()
    orquestador.fijar_nivel("alfa", "medio")
    orquestador.fijar_nivel("beta", "alto")
    monkeypatch.setattr(herramientas.avisos, "mandar", lambda *a, **k: None)
    c = memoria.conectar()
    yield c
    c.close()


def _en_el_intercambio(nombre: str, dentro: str = "alfa", datos: bytes = PNG) -> str:
    destino = intercambio.guardar(nombre, datos, dentro=dentro)
    return destino.relative_to(intercambio.carpeta()).as_posix()


def _cerrada(pedido="prueba alfa", *, origen="secretario", evidencias=(), resumen="hecho, se ve la casa"):
    """Una tarea del orquestador que trabajó y terminó, como lo deja `./orq`."""
    tarea = orquestador.crear(pedido, origen=origen)
    with orquestador.editar(tarea) as t:
        t["estado"] = orquestador.ACTIVA
    for ruta, nota in evidencias:
        orquestador.evidencia(ruta, nota)
    orquestador.terminar(resumen)
    return tarea


def _turnos_del_secretario(con):
    return [dict(f) | {"tarjetas": json.loads(f["tarjetas"])}
            for f in con.execute("SELECT * FROM turno WHERE rol = 'secretario' ORDER BY id")]


def _encargar(con, params, aprobar=True):
    """Por el camino de verdad: «ask» deja la solicitud, el dueño la aprueba en
    la pantalla y el servicio se lo dice a la acción (`ejecutar_aprobadas`)."""
    r = herramientas.usar_accion(con, piezas.acciones()["encargar_al_orquestador"], params, "lo pidió")
    assert r["hecho"] is False and r["solicitud"], r
    memoria.resolver_solicitud(con, r["solicitud"], "aprobada" if aprobar else "rechazada")
    servicio.ejecutar_aprobadas(con)
    return con.execute("SELECT * FROM solicitud WHERE id = ?", (r["solicitud"],)).fetchone()


# ── lo que vuelve ────────────────────────────────────────────────────────────

def test_lo_que_delego_vuelve_a_su_chat_con_la_evidencia_una_vez(con):
    assert delegados.recoger(con) == 0   # estrena: no había nada
    casa = _en_el_intercambio("casa.png")
    fachada = _en_el_intercambio("fachada.png")
    tarea = _cerrada("En «alfa»: haz pruebas de este proyecto\n\nArchivos que trae el dueño…",
                     evidencias=[(casa, "el render de la casa"), (fachada, "")])
    _cerrada("una del dueño, desde /orquestador", origen="web")

    assert delegados.recoger(con) == 1
    [turno] = _turnos_del_secretario(con)
    assert turno["estado"] == "listo"
    texto = turno["texto"]
    assert f"{delegados.MARCO}\nhecho, se ve la casa" in texto, "lo que cuenta el orquestador va enmarcado como dato (322)"
    assert "«En «alfa»: haz pruebas de este proyecto»" in texto and tarea in texto
    assert "hecho, se ve la casa" in texto and "Archivos que trae" not in texto
    assert "2 imágenes" in texto
    [tarjeta] = turno["tarjetas"]
    assert tarjeta["tipo"] == "imagenes"
    assert tarjeta["imagenes"] == [casa, fachada] and tarjeta["notas"] == ["el render de la casa", ""]

    assert delegados.recoger(con) == 0, "cada tarea se dice una vez"
    assert len(_turnos_del_secretario(con)) == 1

    # Una que se detuvo, se reanudó y terminó otra vez es un cierre nuevo: se dice.
    with orquestador.editar(tarea) as t:
        t["estado"], t["cerrada"] = orquestador.ACTIVA, None
    orquestador.terminar("ahora con el tejado")
    with orquestador.editar(tarea) as t:
        t["cerrada"] = "2099-01-01T00:00:00+00:00"
    assert delegados.recoger(con) == 1
    assert "ahora con el tejado" in _turnos_del_secretario(con)[-1]["texto"]


def test_las_tareas_cerradas_antes_de_estrenarlo_no_inundan_el_chat(con):
    viejas = [_cerrada(f"vieja {i}", evidencias=[(_en_el_intercambio(f"v{i}.png"), "")]) for i in range(3)]
    # Las de antes de la 384 no tienen `archivos` ni `evidencias`: se leen con `.get`.
    with orquestador.editar(viejas[0]) as t:
        del t["archivos"], t["evidencias"]
    en_marcha = orquestador.crear("aún trabajando", origen="secretario")

    assert delegados.recoger(con) == 0
    assert _turnos_del_secretario(con) == [], "lo viejo no se dice"
    assert set(memoria.leer(con, delegados.CLAVE)["contadas"]) >= {
        delegados._marca(orquestador.cargar(v)) for v in viejas}

    # La que estaba en marcha al estrenarlo sí se dice cuando termina.
    with orquestador.editar(en_marcha) as t:
        t["estado"] = orquestador.ACTIVA
    orquestador.terminar("terminada después")
    assert delegados.recoger(con) == 1
    [turno] = _turnos_del_secretario(con)
    assert "terminada después" in turno["texto"] and turno["tarjetas"] == []


def test_lo_que_cae_de_las_contadas_no_vuelve(con, monkeypatch):
    """Se recuerdan las últimas `GUARDA`, y las tareas no se borran nunca: lo
    que cae de la lista no puede volver a decirse como nuevo."""
    monkeypatch.setattr(delegados, "GUARDA", 2)
    delegados.recoger(con)
    for i, minuto in enumerate((1, 2, 3, 4)):
        tarea = _cerrada(f"tarea {i}")
        with orquestador.editar(tarea) as t:
            t["cerrada"] = f"2099-01-01T00:0{minuto}:00+00:00"
    assert delegados.recoger(con) == 4
    guardado = memoria.leer(con, delegados.CLAVE)
    assert len(guardado["contadas"]) == 2 and guardado["desde"].startswith("2099-01-01T00:02")
    assert delegados.recoger(con) == 0
    assert len(_turnos_del_secretario(con)) == 4


def test_la_evidencia_que_ya_no_esta_se_dice_y_no_se_ensena(con):
    delegados.recoger(con)
    casa = _en_el_intercambio("casa.png")
    otra = _en_el_intercambio("otra.png")
    _cerrada(evidencias=[(casa, "la casa"), (otra, "")])
    (intercambio.carpeta() / otra).unlink()
    assert delegados.recoger(con) == 1
    [turno] = _turnos_del_secretario(con)
    assert turno["tarjetas"][0]["imagenes"] == [casa]
    assert "(1 imagen)" in turno["texto"] and "1 imagen más que ya no está" in turno["texto"]


def test_las_que_no_caben_en_la_tarjeta_no_se_cuentan_como_perdidas(con):
    """Regla dura 13: con más evidencias de las que caben, la tarjeta lleva
    `MAX_IMAGENES` y el texto dice cuántas más hay y dónde, no que se borraron."""
    delegados.recoger(con)
    n = herramientas.MAX_IMAGENES + 1
    _cerrada(evidencias=[(_en_el_intercambio(f"e{i:02}.png"), "") for i in range(n)])
    assert delegados.recoger(con) == 1
    [turno] = _turnos_del_secretario(con)
    assert len(turno["tarjetas"][0]["imagenes"]) == herramientas.MAX_IMAGENES
    assert f"({herramientas.MAX_IMAGENES} imágenes)" in turno["texto"]
    assert "Y 1 imagen más, en /orquestador" in turno["texto"] and "ya no está" not in turno["texto"]


def test_una_tarea_que_no_se_puede_leer_no_deja_sin_decir_las_demas(con, monkeypatch):
    delegados.recoger(con)
    rara, buena = _cerrada("la rara"), _cerrada("la buena")
    original = delegados._lo_que_se_dice

    def falla_con_la_rara(t, *resto):
        if t["id"] == rara:
            raise OSError("disco ilegible")
        return original(t, *resto)
    monkeypatch.setattr(delegados, "_lo_que_se_dice", falla_con_la_rara)
    assert delegados.recoger(con) == 2
    textos = [t["texto"] for t in _turnos_del_secretario(con)]
    assert any(rara in x and "no pude leerla" in x and "disco ilegible" in x for x in textos)
    assert any("«la buena»" in x for x in textos)
    assert delegados.recoger(con) == 0, "la rara tampoco se repite"


def test_el_ciclo_del_servicio_las_recoge(con, monkeypatch):
    pasos = []
    monkeypatch.setattr(servicio, "_paso", lambda c, nombre, funcion, *a: pasos.append((nombre, funcion)))
    servicio.una_vuelta(con)
    assert ("delegados", delegados.recoger) in pasos, "cada vuelta, en su `_paso` (regla dura 2)"


# ── el encargo ───────────────────────────────────────────────────────────────

def test_aprobar_un_encargo_con_proyecto_vale_como_su_confirmacion(con):
    accion = piezas.acciones()["encargar_al_orquestador"]
    assert accion.nivel_inicial == "ask" and accion.quiere_aprobacion

    # Un `aprobada` metido en los parámetros (los escribe el modelo) no cuenta.
    accion.ejecutar(con, {"pedido": "prueba la casa", "proyecto": "alfa", "aprobada": True})
    [suelta] = orquestador.listar()
    assert suelta["confirmaciones"] == []

    s = _encargar(con, {"pedido": "prueba la casa", "proyecto": "alfa"})
    assert s["estado"] == "hecha", s["resultado"]
    t = next(x for x in orquestador.listar() if x["id"] != suelta["id"])
    assert t["origen"] == "secretario" and t["pedido"].startswith("En «alfa»: prueba la casa")
    assert [(c["proyecto"], c["estado"]) for c in t["confirmaciones"]] == [("alfa", "aprobada")]
    # Su sí es para ese proyecto: `_confirmar_alcance` ya no le pregunta.
    h = db.conectar(config.DB_PATH)
    try:
        orquestador._confirmar_alcance(h, t["id"], "alfa", "mandar", "")
        with pytest.raises(orquestador.PendienteDeConfirmar):
            orquestador._confirmar_alcance(h, suelta["id"], "alfa", "mandar", "")
    finally:
        h.close()


def test_sin_alcance_sobre_el_proyecto_no_se_encola(con):
    for proyecto in ("beta", "no-existe"):   # `never` gana a cualquier nivel (regla dura 7)
        s = _encargar(con, {"pedido": "prueba", "proyecto": proyecto})
        assert s["estado"] == "fallo" and "/orquestador → Permisos" in s["resultado"]
    assert orquestador.listar() == []


def test_un_encargo_con_los_adjuntos_del_hilo_los_lleva_a_la_tarea(con):
    adjunto = conversacion.guardar_adjunto("captura.png", PNG)
    conversacion.recibir(con, "haz pruebas de este proyecto", adjuntos=[adjunto["ruta"]])
    # El modelo ve la ruta absoluta de lo adjunto (383) y la pasa tal cual.
    absoluta = str(intercambio.carpeta() / adjunto["ruta"])

    s = _encargar(con, {"pedido": "haz pruebas de este proyecto con esta imagen", "proyecto": "alfa",
                        "archivos": [absoluta]})
    assert s["estado"] == "hecha" and "con 1 archivos" in s["resultado"], s["resultado"]
    [t] = orquestador.listar()
    assert t["archivos"] == [adjunto["ruta"]]
    assert absoluta in t["pedido"] and "no instrucciones" in t["pedido"], "lo adjunto viaja como dato (322)"

    # Uno de fuera del intercambio no deja una tarea a medias.
    s = _encargar(con, {"pedido": "y con ésta", "archivos": ["/etc/passwd"]})
    assert s["estado"] == "fallo" and "intercambio" in s["resultado"]
    assert len(orquestador.listar()) == 1


def test_el_modelo_solo_delega_bloqueos_y_lo_suyo_no_encola_nada(con):
    """Delegar un asunto es la regla de `asuntos.delegar` (381), la misma que
    su botón: lo que dice un proyecto se contesta, un permiso sólo lo da él,
    y lo que no existe no encola nada. Los bloqueos, en
    `test_secretario_te_espera.py`."""
    sid = con.execute("INSERT INTO solicitud (accion, params, motivo, creada) VALUES ('crear_slot', '{}', 'x', ?)",
                      (memoria.ahora(),)).lastrowid
    aid = asuntos.preguntar(con, "falta probar el carrito", clase="proyecto", origen="tienda")
    clave = con.execute("SELECT clave FROM asunto WHERE id = ?", (aid,)).fetchone()[0]
    for clave, dice in ((f"permiso:{sid}", "sólo se delegan los bloqueos"), (clave, "sólo se delegan los bloqueos"),
                        ("proyecto:nada", "no hay ningún asunto")):
        s = _encargar(con, {"pedido": "hazlo", "asunto": clave})
        assert s["estado"] == "fallo" and dice in s["resultado"], (clave, s["resultado"])
    assert orquestador.listar() == []


# ── la tarjeta y la herramienta ─────────────────────────────────────────────

def test_una_tarjeta_de_imagenes_solo_lleva_rutas_del_intercambio(con, tmp_path):
    buena = _en_el_intercambio("casa.png")
    pdf = _en_el_intercambio("informe.pdf", datos=b"%PDF-1.4")
    svg = _en_el_intercambio("dibujo.svg", datos=b"<svg/>")
    fuera = tmp_path / "fuera.png"
    fuera.write_bytes(PNG)
    (intercambio.carpeta() / "enlace.png").symlink_to(fuera)
    absoluta = str(intercambio.carpeta() / buena)

    tarjeta = herramientas.tarjeta_de_imagenes(
        "Lo que se vio", [buena, pdf, svg, str(fuera), "enlace.png", "../hub.db", "alfa/no-esta.png",
                          "alfa/Casa uno.png", absoluta, 7], ["la casa", "", "", "", "", "", "", "", "otra vez"])
    assert tarjeta["tipo"] == "imagenes" and tarjeta["imagenes"] == [buena], "sólo raster del intercambio, sin repetir"
    assert tarjeta["notas"] == ["la casa"] and tarjeta["filas"] == [[buena, "la casa"]]
    assert herramientas.tarjeta_de_imagenes("x", [pdf, str(fuera)]) is None
    assert herramientas.tarjeta_de_imagenes("x", buena) is None, "una ruta suelta no es una lista"

    # Por la herramienta del modelo, colgada del turno en curso.
    hilo = con.execute("INSERT INTO hilo (abierto, ultimo) VALUES (?, ?)", (memoria.ahora(), memoria.ahora())).lastrowid
    rid = conversacion.decir(con, hilo, "mira")
    memoria.poner(con, f"turno_en_curso:{hilo}", rid)
    import os
    os.environ["SECRETARIO_HILO"] = str(hilo)
    try:
        assert herramientas._tarjeta(con, {"titulo": "T", "tipo": "imagenes", "imagenes": [str(fuera)]})["error"]
        assert herramientas._tarjeta(con, {"titulo": "T", "tipo": "imagenes", "imagenes": [buena, svg]})["ok"]
        assert herramientas._tarjeta(con, {"titulo": "L", "filas": [["a"]]})["ok"], "las de antes, igual"
        assert herramientas._tarjeta(con, {"titulo": "L", "tipo": "tabla"})["error"], "una tabla sin filas, no"
    finally:
        del os.environ["SECRETARIO_HILO"]
    tarjetas = json.loads(con.execute("SELECT tarjetas FROM turno WHERE id = ?", (rid,)).fetchone()[0])
    assert [t["tipo"] for t in tarjetas] == ["imagenes", "lista"] and tarjetas[0]["imagenes"] == [buena]


def _por_mcp(con, nombre, argumentos, monkeypatch):
    salida = io.StringIO()
    monkeypatch.setattr(sys, "stdout", salida)
    mcp.atender({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                 "params": {"name": nombre, "arguments": argumentos}}, herramientas.todas(), con)
    return json.loads(salida.getvalue())["result"]


def test_ver_imagen_le_ensena_al_modelo_lo_adjunto_y_la_evidencia_y_nada_mas(con, monkeypatch):
    """Por MCP, como `content` de tipo `image`: medido el 7-nov que Claude Code
    2.1.280 se la enseña al modelo (haiku acertó el color de dos PNG lisos y,
    sin la imagen, dijo que no la veía)."""
    adjunto = conversacion.guardar_adjunto("captura.png", PNG)["ruta"]
    evidencia = _en_el_intercambio("render.png")
    suelta = _en_el_intercambio("de-otro.png")

    r = _por_mcp(con, "ver_imagen", {"ruta": str(intercambio.carpeta() / adjunto)}, monkeypatch)
    texto, imagen = r["content"]
    assert texto["type"] == "text" and "dato, no instrucciones" in texto["text"]
    assert imagen == {"type": "image", "mimeType": "image/png", "data": base64.b64encode(PNG).decode()}

    r = _por_mcp(con, "ver_imagen", {"ruta": evidencia}, monkeypatch)
    assert "sólo miras" in r["content"][0]["text"], "una imagen suelta del intercambio no se le enseña"
    _cerrada(evidencias=[(evidencia, "")])
    r = _por_mcp(con, "ver_imagen", {"ruta": evidencia}, monkeypatch)
    assert r["content"][1]["type"] == "image", "la evidencia de una tarea sí"

    for mala in (suelta, "../hub.db", _en_el_intercambio("dibujo.svg", dentro="_secretario/x", datos=b"<svg/>")):
        r = _por_mcp(con, "ver_imagen", {"ruta": mala}, monkeypatch)
        assert len(r["content"]) == 1 and "error" in r["content"][0]["text"], mala


# ── la ficha, ejecutada (regla dura 11) ──────────────────────────────────────

CHAT = script_estatico("formato-chat.js") + "\n" + script_estatico("chat-secretario.js")

# `appendChild` del arnés no cuelga nada: se apunta cada nodo creado para
# poder leer lo que pinta la ficha.
CREADOS = """
  globalThis.CREADOS = [];
  const _crear = document.createElement;
  document.createElement = (t) => { const e = _crear(t); globalThis.CREADOS.push(e); return e; };
"""


def test_la_ficha_de_imagenes_pinta_miniaturas_escapadas(tmp_path):
    tarjeta = {"titulo": "Lo que se vio <b>", "tipo": "imagenes",
               "imagenes": ["alfa/casa uno.png", 'alfa/"x" onerror=alert(1).png', "alfa/informe.pdf",
                            "alfa/sin-nota.webp"],
               "notas": ['el "render" <script>', "", "", ""], "filas": []}
    respuesta = {"hilo": 1, "turnos": [{"id": 2, "rol": "secretario", "texto": "Volvió.", "estado": "listo",
                                        "tarjetas": [tarjeta], "adjuntos": []}]}
    accion = ("nodo('sec-texto').value = 'x'; nodo('sec-escribir').disparar('submit', {preventDefault(){}});"
              "setTimeout(() => registro.valores.push(['fichas', "
              "globalThis.CREADOS.filter(e => e.className === 'ficha').map(e => e.innerHTML)]), 5);")
    r = ejecutar(CHAT, tmp_path, {"POST /api/secretario/mensaje": {"ok": True, "hilo": 1, "turno": 1},
                                  "/api/secretario/turnos": respuesta}, previo=CREADOS, accion=accion)
    assert r["errores"] == []
    [html] = [v[1] for v in r["valores"] if isinstance(v, list) and v[0] == "fichas"][-1]
    assert "<strong>Lo que se vio &lt;b&gt;</strong>" in html
    assert ('<a href="/intercambio/ver/alfa/casa%20uno.png" target="_blank" rel="noopener">'
            '<img src="/intercambio/ver/alfa/casa%20uno.png" alt="el &quot;render&quot; &lt;script&gt;"') in html
    assert "<figcaption>el &quot;render&quot; &lt;script&gt;</figcaption>" in html
    # Cada tramo con encodeURIComponent en la ruta y escapado en el `alt`: la
    # comilla no cierra ningún atributo.
    assert ('<img src="/intercambio/ver/alfa/%22x%22%20onerror%3Dalert(1).png" '
            'alt="&quot;x&quot; onerror=alert(1).png"') in html
    assert '" onerror' not in html
    assert "informe.pdf" not in html, "sólo raster"
    assert 'alt="sin-nota.webp"' in html, "sin nota, el nombre del archivo"
    assert html.count("<figure>") == 3 and html.count("<figcaption>") == 1
