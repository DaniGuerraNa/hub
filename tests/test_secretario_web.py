"""La pantalla del secretario y su JavaScript (decisiones 298 y 305).

🔴 `hub-web` sólo deja cosas en la base: lo que se dice, lo que se aprueba, lo
que se enciende. Ninguna ruta llama a una fuente ni ejecuta una acción.
"""

from __future__ import annotations

import json
import re
from urllib.parse import unquote

import pytest
from fastapi.testclient import TestClient

from arnes_js import MICROFONO_VIVO, ejecutar, script_estatico
from hub import api, web
from hub.secretario import memoria, piezas

# Los avisos de estos tests salen por el timbre de Telegram (el respaldo, decisión 310).
pytestmark = pytest.mark.usefixtures("canal_telegram")

# Con el grabador (`grabar.js`, en el `<head>` de `base.html`: el chat graba
# con `HubGrabar`, C-0311) y el formateador del chat delante, como en la página.
GUION = (script_estatico("grabar.js") + "\n" + script_estatico("formato-chat.js") + "\n"
         + script_estatico("chat-secretario.js") + "\n" + script_estatico("secretario.js"))


@pytest.fixture
def cliente(tmp_path, monkeypatch):
    from hub import db

    def conexion():
        c = db.conectar(tmp_path / "hub.db")
        db.inicializar(c)
        return c

    monkeypatch.setattr(web, "conexion", conexion)
    return TestClient(web.app)


@pytest.mark.parametrize("pestana", ["conversacion", "pendientes", "memoria", "ajustes", "avisos", "fuentes",
                                     "confianza", "disparadores", "personaje"])
def test_cada_pestana_se_pinta(cliente, pestana):
    r = cliente.get(f"/secretario?p={pestana}")
    assert r.status_code == 200
    assert 'href="/secretario" class="enlace aqui"' in r.text


def test_sin_el_servicio_lo_dice_arriba(cliente):
    assert "No está en marcha" in cliente.get("/secretario").text


@pytest.mark.parametrize("estado, dice, boton", [
    ({"activo": "inactive", "habilitado": False}, "Está apagado", True),
    ({"activo": "failed", "habilitado": True}, "Está apagado", True),
    ({"activo": "active", "habilitado": True}, "Está encendido pero no da señales", False),
    ({"activo": "activating", "habilitado": True}, "journalctl --user -u hub-secretario", False),
    (None, "uv run python -m hub.secretario", False),
])
def test_sin_latido_dice_por_que_y_ofrece_encenderlo_solo_si_lo_arregla(cliente, monkeypatch, estado, dice, boton):
    """C-0235: el botón donde encenderlo lo arregla. Uno que se cae al arrancar
    ya lo reintenta systemd, y sin systemd no se lanza desde la web (400)."""
    from hub import salud
    monkeypatch.setattr(salud, "estado_servicio", lambda nombre: estado)
    html = cliente.get("/secretario").text
    assert dice in html
    assert ('action="/secretario/encender"' in html) is boton
    assert "systemctl --user start" not in html   # no habilita: no aguantaba un reinicio


def test_con_latido_no_pregunta_a_systemd(cliente, monkeypatch):
    from hub import salud
    con = memoria.conectar()
    memoria.poner(con, "latido", memoria.ahora())
    con.close()
    monkeypatch.setattr(salud, "estado_servicio", lambda nombre: pytest.fail("pintó preguntando a systemd"))
    html = cliente.get("/secretario").text
    assert 'class="caido"' not in html


@pytest.mark.parametrize("estado, marca", [("encendido", "fugaz=1"), ("sin-senal", "hecho=1"), ("no", None)])
def test_encenderlo_vuelve_con_lo_que_paso(cliente, monkeypatch, estado, marca):
    """Encendido es un aviso que se va solo; arrancado sin latir, uno que se
    queda sin ser un fallo; lo demás, un fallo."""
    from hub import salud
    pedidos = []
    monkeypatch.setattr(salud, "encender", lambda nombre: pedidos.append(nombre) or (estado, "Lo que pasó."))
    r = cliente.post("/secretario/encender", follow_redirects=False)
    assert r.status_code == 303 and pedidos == ["hub-secretario"]
    destino = r.headers["location"]
    assert destino.startswith("/secretario?aviso=")
    for otra in ("fugaz=1", "hecho=1"):
        assert (otra in destino) is (otra == marca)


def test_encenderlo_pide_mismo_origen(cliente, monkeypatch):
    from hub import salud
    monkeypatch.setattr(salud, "encender", lambda nombre: pytest.fail("se encendió desde otro origen"))
    r = cliente.post("/secretario/encender", headers={"Origin": "https://malo.example"}, follow_redirects=False)
    assert r.status_code == 403


def test_un_hub_que_no_usa_el_secretario_no_crea_su_base_al_pintar_el_menu(cliente):
    cliente.get("/maquina")
    assert not memoria.existe()


def test_escribir_deja_el_turno_pendiente_y_no_contesta_la_web(cliente):
    r = cliente.post("/api/secretario/mensaje", json={"texto": "¿qué tengo?"})
    assert r.json()["ok"] is True
    t = cliente.get("/api/secretario/turnos").json()["turnos"]
    assert [(x["rol"], x["estado"]) for x in t] == [("dueno", "pendiente")]
    assert cliente.post("/api/secretario/mensaje", json={"texto": "  "}).status_code == 400


def test_aprobar_solo_la_marca_y_el_menu_cuenta_lo_que_espera(cliente):
    con = memoria.conectar()
    sid = con.execute("INSERT INTO solicitud (accion, params, creada) VALUES ('anotar', '{\"texto\": \"x\"}', ?)",
                      (memoria.ahora(),)).lastrowid
    con.close()
    html = cliente.get("/secretario").text
    assert '<span class="cuenta urge">1</span>' in html.split('href="/secretario"')[1].split("</a>")[0]
    cliente.post(f"/secretario/solicitud/{sid}", data={"decision": "aprobar"})
    con = memoria.conectar()
    assert con.execute("SELECT estado FROM solicitud").fetchone()[0] == "aprobada"
    assert memoria.notas(con) == []          # la ejecuta hub-secretario, no la web
    con.close()
    r = cliente.post(f"/secretario/solicitud/{sid}", data={"decision": "rechazar"}, follow_redirects=False)
    assert "ya+estaba+resuelta" in r.headers["location"] or "ya%20estaba%20resuelta" in r.headers["location"]


def test_encender_una_fuente_y_elegir_sus_conversaciones(cliente):
    cliente.post("/secretario/fuente/telegram", data={"activa": "1", "incluir": "Trabajo, Familia", "excluir": ""})
    a = piezas.ajustes_fuentes()["telegram"]
    assert a == {"activa": True, "incluir": ["Trabajo", "Familia"], "excluir": []}
    html = cliente.get("/secretario?p=fuentes").text
    assert "falta" in html and "telegram-entrar" in html


def test_el_nivel_y_los_disparadores_se_guardan_desde_la_pantalla(cliente):
    cliente.post("/secretario/nivel", data={"accion": "agendar", "nivel": "auto"})
    assert piezas.niveles()["agendar"] == "auto"
    r = cliente.post("/secretario/disparadores", data={"texto": "- haz: avisar"}, follow_redirects=False)
    assert "No+se+guard" in r.headers["location"] or "No%20se%20guard" in r.headers["location"]
    cliente.post("/secretario/disparadores", data={"texto": "- cuando: {horario: '08:00'}\n  pide: hola\n"})
    assert "pide: hola" in cliente.get("/secretario?p=disparadores").text


def test_el_manifiesto_abre_el_secretario(cliente):
    m = cliente.get("/secretario/manifest.webmanifest").json()
    assert m["start_url"] == "/secretario" and m["display"] == "standalone"
    assert '<link rel="manifest" href="/secretario/manifest.webmanifest" crossorigin="use-credentials">' \
        in cliente.get("/secretario").text
    assert '<link rel="manifest" href="/static/manifest.json" crossorigin="use-credentials">' \
        in cliente.get("/maquina").text


def test_el_manifiesto_se_pide_con_la_cookie_del_aparato(cliente):
    """Sin `use-credentials` el navegador lo pide sin cookie, la puerta de
    dispositivo contesta 403 y el teléfono no ofrece instalar (decisión 316).
    Medido en Chromium el 2026-11-01: la página 200 y el manifiesto 403."""
    for pantalla in ("/secretario", "/maquina"):
        assert 'crossorigin="use-credentials"' in cliente.get(pantalla).text.split('rel="manifest"')[1].split(">")[0]


def test_los_turnos_dicen_si_el_secretario_esta_en_marcha(cliente):
    """Lo mira el chat de todas las pantallas para no quedarse «pensando» sin
    decir que nadie va a contestar (C-0302)."""
    assert cliente.get("/api/secretario/turnos").json()["vivo"] is False
    con = memoria.conectar()
    memoria.poner(con, "latido", memoria.ahora())
    con.close()
    assert cliente.get("/api/secretario/turnos").json()["vivo"] is True


def test_un_mensaje_dictado_lo_dice_y_uno_que_no_dice_true_no(cliente):
    """C-0291: sólo `true` marca el dictado, como `voz`."""
    a = cliente.post("/api/secretario/mensaje", json={"texto": "abre prisa", "dictado": True}).json()
    b = cliente.post("/api/secretario/mensaje", json={"texto": "abre Brisa", "dictado": "si"}).json()
    con = memoria.conectar()
    try:
        assert memoria.leer(con, f"dictado:{a['turno']}") is True
        assert memoria.leer(con, f"dictado:{b['turno']}") is None
    finally:
        con.close()


def test_los_post_del_secretario_piden_mismo_origen(cliente):
    r = cliente.post("/api/secretario/mensaje", json={"texto": "x"}, headers={"Origin": "https://malo.example"})
    assert r.status_code == 403


# ── el JavaScript, ejecutado (regla dura 11) ─────────────────────────────────

PREVIO = ("nodo('sec').dataset = { ultimo: '0' };"
          "global.speechSynthesis = { cancel(){}, getVoices(){ return [{ lang: 'es-MX' }]; },"
          "  speak(u){ registro.valores.push(['dicho', u.text]); } };"
          "global.SpeechSynthesisUtterance = class { constructor(t){ this.text = t; } };")


def test_al_enviar_manda_el_texto_y_pinta_la_respuesta_marcada(tmp_path):
    respuesta = {"hilo": 1, "turnos": [
        {"id": 1, "rol": "dueno", "texto": "¿qué tengo?", "estado": "listo", "tarjetas": []},
        {"id": 2, "rol": "secretario", "texto": "Tienes **dos** cosas.", "estado": "listo", "modelo": "claude-sonnet-5",
         "segundos": 8.2, "tarjetas": [{"titulo": "Pendientes", "tipo": "tabla", "columnas": ["Qué"],
                                         "filas": [["<b>PRs</b>"]]}]}]}
    r = ejecutar(GUION, tmp_path, {"POST /api/secretario/mensaje": {"ok": True, "hilo": 1, "turno": 1},
                                   "/api/secretario/turnos": respuesta},
                 previo=PREVIO,
                 accion="nodo('sec-texto').value = '¿qué tengo?'; nodo('sec-escribir').disparar('submit', {preventDefault(){}});"
                        "setTimeout(() => registro.valores.push(['html', nodo('sec-chat').querySelector('[data-turno=\"2\"]').innerHTML]), 5);")
    assert r["errores"] == []
    assert {"url": "/api/secretario/mensaje", "metodo": "POST", "cuerpo": {"texto": "¿qué tengo?", "voz": False}} in r["enviados"]
    assert any(str(p).startswith("/api/secretario/turnos") for p in r["peticiones"])
    html = [v[1] for v in r["valores"] if isinstance(v, list) and v[0] == "html"][-1]
    # El texto del modelo se marca (la negrita sí) y lo de la tarjeta se escapa:
    # lo escribe un modelo que ha leído chats ajenos, no puede colar HTML.
    assert html.startswith("Tienes <strong>dos</strong> cosas.")


#: Las tarjetas que pinta `ficha()`: el arnés no tiene árbol, así que se
#: anotan los elementos que crea el chat y se miran los de clase `ficha`.
FICHAS = ("const _crear = document.createElement; global.CREADOS = [];"
          "document.createElement = (t) => { const e = _crear(t); CREADOS.push(e); return e; };"
          "nodo('sec-chat').dataset.cargar = '1';")


def _fichas(tmp_path, tarjetas: list[dict]) -> list[str]:
    turnos = {"hilo": 1, "turnos": [{"id": 2, "rol": "secretario", "texto": "Investigué algo.", "estado": "listo",
                                      "tarjetas": tarjetas}]}
    accion = ("setTimeout(() => registro.valores.push(['fichas',"
              " CREADOS.filter(e => e.className === 'ficha').map(e => e.innerHTML)]), 5);")
    r = ejecutar(GUION, tmp_path, {"/api/secretario/turnos": turnos}, previo=PREVIO + FICHAS, accion=accion)
    assert r["errores"] == []
    return [v[1] for v in r["valores"] if isinstance(v, list) and v[0] == "fichas"][-1]


def test_la_tarjeta_de_fuentes_pinta_cada_fuente_como_enlace_corto_y_sin_colar_nada(tmp_path):
    """C-0452, decisión 439: la URL entera ocupaba media tarjeta. Se pinta el
    dominio, con la URL en `href`, sólo si es http(s) y sólo en la columna que
    la tarjeta declara; el texto del enlace sale del `href`, nunca del modelo."""
    filas = [["1", "https://www.ejemplo.gob/norma/art30?x=1", "2025-01", "https://otra.org/no-es-enlace"],
             ["2", "javascript:alert(1)", "sin fecha", "Pulsa"],
             ["3", "data:text/html,<script>alert(1)</script>", "sin fecha", "Datos"],
             ["4", 'https://ejemplo.org/a"onmouseover="x<b>', "sin fecha", "Comillas"]]
    [html] = _fichas(tmp_path, [{"titulo": "Fuentes", "tipo": "tabla", "columnas": ["#", "Fuente", "Fecha", "Qué dice"],
                                 "enlaces": [1], "filas": filas}])
    assert ('<a class="fuente" href="https://www.ejemplo.gob/norma/art30?x=1" '
            'title="https://www.ejemplo.gob/norma/art30?x=1" target="_blank" rel="noopener noreferrer">'
            'ejemplo.<wbr>gob</a>' in html), "el dominio, partible por sus puntos en el móvil (medido a 390 px)"
    # Lo que no es http(s) se pinta escapado, como antes: ni enlace ni HTML.
    assert "<td>javascript:alert(1)</td>" in html
    assert "<td>data:text/html,&lt;script&gt;alert(1)&lt;/script&gt;</td>" in html
    assert "<script>" not in html and 'href="javascript' not in html and 'href="data' not in html
    # Comillas y «<» dentro de una URL no salen del atributo: `URL` las codifica.
    [comillas] = [td for td in html.split("<td>") if "ejemplo.org" in td]
    assert '">ejemplo.<wbr>org</a>' in comillas and '"onmouseover' not in comillas and "<b>" not in comillas
    # Una URL en una columna que no se declaró de enlaces es texto.
    assert "<td>https://otra.org/no-es-enlace</td>" in html
    assert html.count("<a ") == 2


def test_una_tarjeta_sin_columnas_de_enlaces_no_enlaza_nada(tmp_path):
    """La tarjeta que arma el modelo con la herramienta `tarjeta` no puede
    declarar `enlaces` (`herramientas._tarjeta` la rehace campo a campo): el
    texto del modelo sigue sin enlazar nada de fuera (271)."""
    [html] = _fichas(tmp_path, [{"titulo": "Mía", "tipo": "tabla", "columnas": ["Sitio"],
                                 "filas": [["https://ejemplo.gob/a"]]}])
    assert "<a " not in html and "<td>https://ejemplo.gob/a</td>" in html


def test_un_bloque_de_codigo_de_la_respuesta_se_copia_con_su_boton(tmp_path):
    """C-0306: una orden o una ruta en un bloque sale aparte y «Copiar» la
    deja en el portapapeles tal cual se ve, sin las comillas ni las marcas."""
    respuesta = {"hilo": 1, "turnos": [{"id": 2, "rol": "secretario", "estado": "listo", "tarjetas": [],
                                        "texto": "Lánzalo así:\n```bash\nuv run pytest -k 'a < b'\n```"}]}
    accion = ("nodo('sec-texto').value = 'hola'; nodo('sec-escribir').disparar('submit', {preventDefault(){}});"
              "setTimeout(() => {"
              "  registro.valores.push(['html', nodo('sec-chat').querySelector('[data-turno=\"2\"]').innerHTML]);"
              "  const codigo = { textContent: \"uv run pytest -k 'a < b'\" };"
              "  global.BOTON = { textContent: 'Copiar', parentElement: { querySelector: () => codigo },"
              "    closest(sel) { return sel === '[data-copiar-codigo]' ? global.BOTON : null; } };"
              "  nodo('sec-chat').disparar('click', { target: global.BOTON });"
              "}, 5);"
              "setTimeout(() => registro.valores.push(['boton', global.BOTON.textContent]), 9);")
    r = ejecutar(GUION, tmp_path, {"POST /api/secretario/mensaje": {"ok": True}, "/api/secretario/turnos": respuesta},
                 previo=PREVIO, accion=accion)
    assert r["errores"] == []
    html = _estado(r, "html")[0]
    assert ('<div class="bloque-codigo"><button type="button" class="copiar-codigo" data-copiar-codigo>Copiar</button>'
            "<pre><code>uv run pytest -k &#39;a &lt; b&#39;</code></pre></div>") in html
    assert r["portapapeles"] == ["uv run pytest -k 'a < b'"]
    assert ["boton", "Copiado"] in r["valores"]


def test_con_voz_encendida_lee_la_respuesta_sin_markdown(tmp_path):
    respuesta = {"hilo": 1, "turnos": [{"id": 5, "rol": "secretario", "texto": "Tienes **dos** cosas en [Trabajo](/trabajo).",
                                        "estado": "listo", "tarjetas": []}]}
    r = ejecutar(GUION, tmp_path, {"POST /api/secretario/mensaje": {"ok": True},
                                   "/api/secretario/turnos": respuesta},
                 previo=PREVIO + "localStorage.setItem('secretario.voz', '1');",
                 accion="nodo('sec-texto').value = 'hola'; nodo('sec-escribir').disparar('submit', {preventDefault(){}});")
    assert r["errores"] == []
    assert ["dicho", "Tienes dos cosas en Trabajo."] in r["valores"]


def test_con_leer_en_voz_alta_empieza_a_sonar_antes_de_que_acabe_y_el_mensaje_va_por_voz(tmp_path):
    """VOZ-23 (C-0360): con la casilla, la primera palabra tardaba lo que la
    respuesta entera (p50 9,4 s) y el modelo no sabía que se le iba a leer.
    Ahora va frase a frase con el mismo locutor que el modo voz, y el mensaje
    sale con `voz`: el modelo escribe para el oído (VOZ-21)."""
    a_medias = {"hilo": 1, "turnos": [{"id": 9, "rol": "secretario", "texto": "Déjame mirarlo. Tienes",
                                       "estado": "escribiendo", "tarjetas": []}]}
    entera = [{"id": 9, "rol": "secretario", "texto": "Déjame mirarlo. Tienes **dos** cosas.",
               "estado": "listo", "tarjetas": []}]
    accion = ("const st = global.setTimeout; global.setTimeout = (f, ms) => st(f, ms === 300 ? 3 : ms);"
              "nodo('sec-texto').value = 'hola'; nodo('sec-escribir').disparar('submit', {preventDefault(){}});"
              "setTimeout(() => { registro.valores.push('ya-escrito');"
              f"  RESPUESTAS['/api/secretario/turnos'].turnos = {json.dumps(entera)}; }}, 9);")
    r = ejecutar(GUION, tmp_path, {"POST /api/secretario/mensaje": {"ok": True}, "/api/secretario/turnos": a_medias},
                 previo=PREVIO + VOZ_FALSA + "localStorage.setItem('secretario.voz', '1');", accion=accion)
    assert r["errores"] == []
    v = r["valores"]
    dichos = [x[1] for x in v if isinstance(x, list) and x[0] == "dicho"]
    assert dichos == ["Déjame mirarlo.", "Tienes dos cosas."]
    assert v.index(["dicho", "Déjame mirarlo."]) < v.index("ya-escrito")
    assert {"url": "/api/secretario/mensaje", "metodo": "POST", "cuerpo": {"texto": "hola", "voz": True}} in r["enviados"]
    assert "escuchando" not in v, "fuera del modo voz, leer no abre el micrófono"


def test_la_conversacion_no_es_una_region_viva_entera(cliente):
    """UI-46 (C-0365): con `aria-live` en todo el chat, un lector de pantalla
    leería la misma respuesta creciente una y otra vez (se repinta con cada
    trozo). Lo que se anuncia va aparte, en su región."""
    html = cliente.get("/secretario").text
    etiqueta = re.search(r'<div class="chat" id="sec-chat"[^>]*>', html).group(0)
    assert "aria-live" not in etiqueta
    assert re.search(r'<span class="solo-lector" id="sec-anuncio" role="status" aria-live="polite"></span>', html)


_ANUNCIO = ("Object.defineProperty(nodo('sec-anuncio'), 'textContent', {"
            "  get(){ return ''; }, set(v){ registro.valores.push(['anuncio', v]); } });")


def test_se_anuncia_una_vez_la_respuesta_terminada_y_no_cada_trozo(tmp_path):
    a_medias = {"hilo": 1, "turnos": [{"id": 9, "rol": "secretario", "texto": "Déjame mirarlo. Tienes",
                                       "estado": "escribiendo", "tarjetas": []}]}
    entera = [{"id": 9, "rol": "secretario", "texto": "Déjame mirarlo. Tienes **dos** cosas.",
               "estado": "listo", "tarjetas": []}]
    accion = ("const st = global.setTimeout; global.setTimeout = (f, ms) => st(f, ms === 1500 ? 2 : ms);"
              "nodo('sec-texto').value = 'hola'; nodo('sec-escribir').disparar('submit', {preventDefault(){}});"
              f"setTimeout(() => {{ RESPUESTAS['/api/secretario/turnos'].turnos = {json.dumps(entera)}; }}, 8);")
    r = ejecutar(GUION, tmp_path, {"POST /api/secretario/mensaje": {"ok": True}, "/api/secretario/turnos": a_medias},
                 previo=PREVIO + _ANUNCIO, accion=accion)
    assert r["errores"] == []
    anuncios = [x[1] for x in r["valores"] if isinstance(x, list) and x[0] == "anuncio"]
    assert anuncios == ["Contestó: Déjame mirarlo. Tienes dos cosas."]


def test_una_respuesta_enorme_se_anuncia_acotada_y_dice_que_sigue(tmp_path):
    larga = {"hilo": 1, "turnos": [{"id": 9, "rol": "secretario", "texto": "Esto es una frase. " * 6000,
                                    "estado": "listo", "tarjetas": []}]}
    r = ejecutar(GUION, tmp_path, {"POST /api/secretario/mensaje": {"ok": True}, "/api/secretario/turnos": larga},
                 previo=PREVIO + _ANUNCIO,
                 accion="nodo('sec-texto').value = 'hola'; nodo('sec-escribir').disparar('submit', {preventDefault(){}});")
    assert r["errores"] == []
    [anuncio] = [x[1] for x in r["valores"] if isinstance(x, list) and x[0] == "anuncio"]
    assert len(anuncio) < 4200 and anuncio.endswith("frase. El resto sigue en el chat.")


def test_lo_que_ya_estaba_contestado_o_se_lee_en_voz_alta_no_se_anuncia(tmp_path):
    hecha = {"hilo": 1, "turnos": [{"id": 9, "rol": "secretario", "texto": "Hola.", "estado": "listo", "tarjetas": []}]}
    r = ejecutar(GUION, tmp_path, {"/api/secretario/turnos": hecha},
                 previo=PREVIO + _ANUNCIO + "nodo('sec-chat').dataset = { cargar: '1' };")
    assert r["errores"] == [] and not [x for x in r["valores"] if isinstance(x, list) and x[0] == "anuncio"]
    r = ejecutar(GUION, tmp_path, {"POST /api/secretario/mensaje": {"ok": True}, "/api/secretario/turnos": hecha},
                 previo=PREVIO + _ANUNCIO + "localStorage.setItem('secretario.voz', '1');",
                 accion="nodo('sec-texto').value = 'hola'; nodo('sec-escribir').disparar('submit', {preventDefault(){}});")
    assert r["errores"] == [] and not [x for x in r["valores"] if isinstance(x, list) and x[0] == "anuncio"]
    assert ["dicho", "Hola."] in r["valores"], "con la voz ya se oye: el lector no lo repite"


def test_sin_nada_que_esperar_no_se_queda_preguntando_en_bucle(tmp_path):
    r = ejecutar(GUION, tmp_path, previo=PREVIO)
    assert r["errores"] == []
    assert 1500 not in r["temporizadores"]


def test_el_panel_no_pinta_las_ideas_de_chat_vacio_antes_de_saber_si_lo_esta(cliente):
    """En el panel la conversación llega después (C-0304): pintaba «Pregúntale
    por tus mensajes…» y las tres ideas en cada pantalla, y luego saltaba a la
    conversación. En /secretario, que la trae pintada, siguen como siempre."""
    _en_todo_el_hub()
    panel = cliente.get("/").text.split('id="secretario-panel"')[1]
    assert 'id="sec-cargando"' in panel
    assert re.search(r'id="sec-vacio"[^>]*\bhidden\b', panel)
    propia = cliente.get("/secretario").text
    assert 'id="sec-cargando"' not in propia
    assert not re.search(r'id="sec-vacio"[^>]*\bhidden\b', propia)


# El panel: la conversación la pide al cargar. Lo que pasa con el hueco neutro
# (`sec-cargando`) y las ideas (`sec-vacio`) se apunta.
_PANEL_CARGANDO = ("nodo('sec-chat').dataset.cargar = '1';"
                   "nodo('sec-vacio').hidden = true;"
                   "nodo('sec-cargando').remove = () => registro.valores.push('hueco-fuera');"
                   "nodo('sec-vacio').remove = () => registro.valores.push('ideas-fuera');")


def test_el_panel_vacio_ensena_las_ideas_cuando_sabe_que_no_hay_conversacion(tmp_path):
    r = ejecutar(GUION, tmp_path, {"/api/secretario/turnos": {"hilo": None, "turnos": [], "vivo": True}},
                 previo=PREVIO + _PANEL_CARGANDO,
                 accion="registro.valores.push(['ideas', nodo('sec-vacio').hidden]);")
    assert r["errores"] == []
    assert "hueco-fuera" in r["valores"] and ["ideas", False] in r["valores"]


def test_el_panel_con_conversacion_no_ensena_nunca_las_ideas(tmp_path):
    hay = {"hilo": 1, "vivo": True,
           "turnos": [{"id": 1, "rol": "secretario", "texto": "Buenos días.", "estado": "listo", "tarjetas": []}]}
    r = ejecutar(GUION, tmp_path, {"/api/secretario/turnos": hay}, previo=PREVIO + _PANEL_CARGANDO,
                 accion="registro.valores.push(['ideas', nodo('sec-vacio').hidden]);")
    assert r["errores"] == []
    assert "hueco-fuera" in r["valores"] and "ideas-fuera" in r["valores"]
    assert ["ideas", True] in r["valores"]


def test_si_el_hub_no_contesta_al_cargar_el_panel_no_promete_un_chat_vacio(tmp_path):
    caido = ("const _fc = global.fetch; global.fetch = (url, o) => String(url).startsWith('/api/secretario/turnos')"
             " ? Promise.reject(new TypeError('Failed to fetch')) : _fc(url, o);")
    r = ejecutar(GUION, tmp_path, previo=PREVIO + _PANEL_CARGANDO + caido,
                 accion="registro.valores.push(['ideas', nodo('sec-vacio').hidden]);")
    assert r["errores"] == []
    assert "hueco-fuera" not in r["valores"] and ["ideas", True] in r["valores"]


# Un hub que no contesta a los mensajes mientras `RED_CAIDA` (C-0305).
_MENSAJE_NO_SALE = ("global.RED_CAIDA = true; const _fm = global.fetch;"
                    "global.fetch = (url, o) => (global.RED_CAIDA && String(url) === '/api/secretario/mensaje')"
                    " ? Promise.reject(new TypeError('Failed to fetch')) : _fm(url, o);")


def _estado(r, marca):
    return [v[1:] for v in r["valores"] if isinstance(v, list) and v[0] == marca][-1]


def test_si_no_se_envia_lo_dice_en_rojo_con_reintentar_y_lo_escrito_sigue_en_el_cuadro(tmp_path):
    """Un «no se envió» en gris pequeño, como «enviando…», se confundía con un
    mensaje que sí salió (C-0305, regla 17). Reintentar manda lo del cuadro."""
    mirar = ("const mirar = (m) => registro.valores.push([m, nodo('estado-sec').textContent,"
             " nodo('estado-sec').dataset.tono || '', nodo('sec-texto').value, nodo('sec-reintentar').hidden]);")
    accion = (mirar + "nodo('sec-texto').value = '¿qué tengo hoy?';"
              "nodo('sec-escribir').disparar('submit', {preventDefault(){}});"
              "setTimeout(() => mirar('fallo'), 4);"
              "setTimeout(() => { global.RED_CAIDA = false; nodo('sec-reintentar').disparar('click'); }, 6);"
              "setTimeout(() => mirar('tras'), 12);")
    r = ejecutar(GUION, tmp_path, {"POST /api/secretario/mensaje": {"ok": True, "hilo": 1, "turno": 1}},
                 previo=PREVIO + _MENSAJE_NO_SALE, accion=accion)
    assert r["errores"] == []
    texto, tono, cuadro, oculto = _estado(r, "fallo")
    assert "no se envió" in texto and tono == "error"
    assert cuadro == "¿qué tengo hoy?" and oculto is False
    mandados = [e["cuerpo"]["texto"] for e in r["enviados"] if e["url"] == "/api/secretario/mensaje"]
    assert mandados == ["¿qué tengo hoy?"]
    _, tono, cuadro, oculto = _estado(r, "tras")
    assert tono == "" and cuadro == "" and oculto is True


# Un turno que nadie contesta: el secretario no late (`vivo: false`, C-0302).
# El reloj salta con `SALTO`; las esperas del sondeo (300 ms en el modo voz,
# 1,5 y 6 s) son de 2 ms, y la de 6 s se apunta como «lento».
_SIN_SECRETARIO = ("const _now = Date.now; global.SALTO = 0; Date.now = () => _now() + global.SALTO;"
                   "const _st6 = global.setTimeout; global.setTimeout = (f, ms) => {"
                   "  if (ms === 6000) registro.valores.push('lento');"
                   "  return _st6(f, [300, 1500, 6000].includes(ms) ? 2 : ms); };")


def _sin_contestar():
    return {"hilo": 1, "vivo": False,
            "turnos": [{"id": 1, "rol": "dueno", "texto": "hola", "estado": "pendiente", "tarjetas": []}]}


def test_con_el_secretario_parado_lo_dice_ofrece_ver_que_le_pasa_y_sondea_despacio(tmp_path):
    """Con `hub-secretario` parado, el mensaje entraba y el chat se quedaba
    «pensando…» para siempre, preguntando cada 1,5 s (C-0302)."""
    mirar = ("const mirar = (m) => registro.valores.push([m, nodo('estado-sec').textContent,"
             " nodo('estado-sec').dataset.tono || '', nodo('sec-apagado').hidden]);")
    accion = (_SIN_SECRETARIO + mirar
              + "nodo('sec-texto').value = 'hola'; nodo('sec-escribir').disparar('submit', {preventDefault(){}});"
              "setTimeout(() => mirar('al-principio'), 4);"
              "setTimeout(() => { global.SALTO = 6000; }, 5);"
              "setTimeout(() => mirar('apagado'), 10);"
              "setTimeout(() => { RESPUESTAS['/api/secretario/turnos'].vivo = true; }, 11);"
              "setTimeout(() => mirar('vuelve'), 14);"
              # Que acabe, o el sondeo no deja terminar al arnés.
              "setTimeout(() => RESPUESTAS['/api/secretario/turnos'].turnos.forEach(t => { t.estado = 'listo'; }), 16);")
    r = ejecutar(GUION, tmp_path, {"POST /api/secretario/mensaje": {"ok": True, "hilo": 1, "turno": 1},
                                   "/api/secretario/turnos": _sin_contestar()}, previo=PREVIO, accion=accion)
    assert r["errores"] == []
    # Los primeros segundos no: puede estar arrancando.
    assert _estado(r, "al-principio") == ["pensando…", "", True]
    texto, tono, oculto = _estado(r, "apagado")
    assert "no está en marcha" in texto and "lo contestará al volver" in texto and tono == "aviso"
    assert oculto is False and "lento" in r["valores"]
    assert _estado(r, "vuelve") == ["pensando…", "", True]


def test_en_modo_voz_si_su_turno_espera_en_cola_dice_un_momento_una_sola_vez(tmp_path):
    """VOZ-28 (C-0362): dos turnos por voz esperaron 56 s y 124 s a que el
    secretario los tomara, con el panel en «pensando…»; en el modo voz el
    silencio se lee como «no me oyó», y se repite o se va. A los 3 s
    `pendiente` (no `atendiendo`) dice «un momento», una vez, y por qué."""
    en_cola = {"hilo": 1, "vivo": True, "turnos": [
        {"id": 1, "rol": "dueno", "texto": "lo de antes", "estado": "atendiendo", "tarjetas": []},
        {"id": 2, "rol": "dueno", "texto": "hola", "estado": "pendiente", "tarjetas": []}]}
    estado = "registro.valores.push([%r, nodo('sec-voz-estado').textContent]);"
    accion = (_SIN_SECRETARIO
              + "nodo('sec-modo-voz').disparar('click');"
              "setTimeout(() => { global.REC.stop(); nodo('sec-texto').value = 'hola'; }, 1);"
              "setTimeout(() => nodo('sec-escribir').disparar('submit', {preventDefault(){}}), 2);"
              f"setTimeout(() => {{ {estado % 'antes'} global.SALTO = 3500; }}, 6);"
              f"setTimeout(() => {{ {estado % 'despues'} }}, 12);"
              "setTimeout(() => RESPUESTAS['/api/secretario/turnos'].turnos.forEach(t => { t.estado = 'listo'; }), 16);")
    r = ejecutar(GUION, tmp_path, {"POST /api/secretario/mensaje": {"ok": True}, "/api/secretario/turnos": en_cola},
                 previo=PREVIO + VOZ_FALSA, accion=accion)
    assert r["errores"] == []
    v = r["valores"]
    dichos = [x[1] for x in v if isinstance(x, list) and x[0] == "dicho"]
    assert dichos == ["Un momento."]
    assert "momento" not in _estado(r, "antes")[0], "los primeros segundos, no: casi siempre lo toma enseguida"
    despues = _estado(r, "despues")[0]
    assert despues.startswith("Entendí: «hola»") and "está acabando lo anterior" in despues


def test_fuera_del_modo_voz_la_cola_no_habla(tmp_path):
    en_cola = {"hilo": 1, "vivo": True, "turnos": [{"id": 2, "rol": "dueno", "texto": "hola", "estado": "pendiente",
                                                   "tarjetas": []}]}
    accion = (_SIN_SECRETARIO
              + "nodo('sec-texto').value = 'hola'; nodo('sec-escribir').disparar('submit', {preventDefault(){}});"
              "setTimeout(() => { global.SALTO = 3500; }, 4);"
              "setTimeout(() => RESPUESTAS['/api/secretario/turnos'].turnos.forEach(t => { t.estado = 'listo'; }), 12);")
    r = ejecutar(GUION, tmp_path, {"POST /api/secretario/mensaje": {"ok": True}, "/api/secretario/turnos": en_cola},
                 previo=PREVIO + VOZ_FALSA, accion=accion)
    assert r["errores"] == []
    assert not [x for x in r["valores"] if isinstance(x, list) and x[0] == "dicho"]


def test_el_sondeo_lento_va_por_la_regla_comun_que_calla_con_la_pestana_oculta(tmp_path):
    """Preguntaba cada 6 s por su cuenta, también con la pestaña oculta (C-0277, C-0302)."""
    regla = ("window.HubSondeo = { cada(fn, ms) { registro.valores.push(['cada', ms]); global.SONDEO = fn;"
             " return () => {}; } };")
    r = ejecutar(GUION, tmp_path, previo=PREVIO + regla,
                 accion="registro.peticiones.length = 0; global.SONDEO();")
    assert r["errores"] == []
    assert ["cada", 6000] in r["valores"]
    assert any(str(p).startswith("/api/secretario/turnos") for p in r["peticiones"])


def test_en_modo_voz_con_el_secretario_parado_pausa_y_lo_dice(tmp_path):
    accion = (_SIN_SECRETARIO
              + "nodo('sec-modo-voz').disparar('click');"
              "setTimeout(() => { global.REC.stop(); nodo('sec-texto').value = 'hola'; }, 2);"
              "setTimeout(() => nodo('sec-escribir').disparar('submit', {preventDefault(){}}), 3);"
              "setTimeout(() => { global.SALTO = 6000; }, 5);"
              "setTimeout(() => registro.valores.push(['panel', nodo('sec-panel-voz').dataset.fase,"
              " nodo('sec-voz-estado').textContent, nodo('sec-voz-pausa').textContent]), 12);"
              "setTimeout(() => { RESPUESTAS['/api/secretario/turnos'].vivo = true; }, 13);"
              "setTimeout(() => registro.valores.push(['vuelve', nodo('sec-panel-voz').dataset.fase,"
              " nodo('sec-voz-estado').textContent]), 16);"
              "setTimeout(() => RESPUESTAS['/api/secretario/turnos'].turnos.forEach(t => { t.estado = 'listo'; }), 17);")
    r = ejecutar(GUION, tmp_path, {"POST /api/secretario/mensaje": {"ok": True},
                                   "/api/secretario/turnos": _sin_contestar()},
                 previo=PREVIO + VOZ_FALSA, accion=accion)
    assert r["errores"] == []
    fase, texto, boton = _estado(r, "panel")
    assert fase == "pausa" and "no está en marcha" in texto and boton == "Seguir"
    assert any(isinstance(x, list) and x[0] == "dicho" and "no está en marcha" in x[1] for x in r["valores"])
    # De vuelta, sigue en pausa (el micrófono no se abre solo) y ya no dice que está parado.
    assert _estado(r, "vuelve") == ["pausa", "Ya está en marcha: pulsa Seguir."]


def test_si_el_hub_no_contesta_al_sondear_lo_dice_y_al_volver_lo_quita(tmp_path):
    """El «sigo intentando» se quedaba escrito con el hub ya de vuelta (C-0305)."""
    caido = ("global.SONDEO_CAIDO = true; const _fs = global.fetch;"
             "global.fetch = (url, o) => (global.SONDEO_CAIDO && String(url).startsWith('/api/secretario/turnos'))"
             " ? Promise.reject(new TypeError('Failed to fetch')) : _fs(url, o);"
             # El sondeo rápido espera 1,5 s: en el arnés, 2 ms.
             "const _st = global.setTimeout; global.setTimeout = (f, ms) => _st(f, ms === 1500 ? 2 : ms);")
    mirar = ("const mirar = (m) => registro.valores.push([m, nodo('estado-sec').textContent,"
             " nodo('estado-sec').dataset.tono || '']);")
    accion = (mirar + "nodo('sec-texto').value = 'hola'; nodo('sec-escribir').disparar('submit', {preventDefault(){}});"
              "setTimeout(() => mirar('caido'), 4);"
              "setTimeout(() => { global.SONDEO_CAIDO = false; }, 6);"
              "setTimeout(() => mirar('vuelve'), 14);")
    r = ejecutar(GUION, tmp_path, {"POST /api/secretario/mensaje": {"ok": True}}, previo=PREVIO + caido, accion=accion)
    assert r["errores"] == []
    texto, tono = _estado(r, "caido")
    assert "no contesta" in texto and tono == "error"
    assert _estado(r, "vuelve") == ["", ""]


# ── avisos en este aparato (decisión 311) ────────────────────────────────────

PUBLICA = "BPsFDMYpqlGSHO2XbUyE8dADGqGHrnQXhAwTSA00AYf5Ax7fQ_ir9QmYfvhUqB3r9yr1s-uiQ4IVxfhMYFel1No"


def _navegador(ua: str, con_push: bool, permiso: str = "default", app: bool = False) -> str:
    """Un navegador con o sin Web Push, para la pantalla de Avisos."""
    js = (f"nodo('sec').dataset = {{ ultimo: '0', pendientes: '0' }};"
          f"nodo('push').dataset = {{ publica: '{PUBLICA}' }};"
          f"navigator.userAgent = {json.dumps(ua)}; navigator.platform = 'x'; navigator.maxTouchPoints = 5;"
          f"window.matchMedia = () => ({{ matches: {str(app).lower()} }});"
          "global.isSecureContext = true; location.reload = () => registro.valores.push('recargada');")
    if con_push:
        js += (f"global.Notification = {{ permission: '{permiso}' }}; global.PushManager = class {{}};"
               "const sub = { endpoint: 'https://push.ejemplo.org/1',"
               "  toJSON(){ return { endpoint: this.endpoint, keys: { p256dh: 'P', auth: 'A' } }; } };"
               "global.SUSCRITA = null;"
               "navigator.serviceWorker = { register: async (url, o) => { registro.valores.push(['sw', url, o.scope]);"
               "  return { pushManager: { getSubscription: async () => global.SUSCRITA,"
               "    subscribe: async (o) => { registro.valores.push(['clave', o.applicationServerKey.length,"
               "      o.userVisibleOnly]); global.SUSCRITA = sub; return sub; } } }; } };")
    return js


def _texto_push(r) -> str:
    return [v[1] for v in r["valores"] if isinstance(v, list) and v[0] == "texto"][-1]


VOLCAR = "setTimeout(() => registro.valores.push(['texto', nodo('push-texto').innerHTML]), 20);"


def test_en_un_iphone_sin_instalar_explica_como_instalarla_antes_de_ofrecer_avisos(tmp_path):
    r = ejecutar(GUION, tmp_path, previo=_navegador("Mozilla/5.0 (iPhone) Safari/605", con_push=False), accion=VOLCAR)
    assert r["errores"] == []
    assert "Añadir a pantalla de inicio" in _texto_push(r)


def test_activar_pide_el_permiso_al_pulsar_y_da_de_alta_el_aparato(tmp_path):
    previo = _navegador("Mozilla/5.0 (Linux; Android 15) Chrome/140 Mobile", con_push=True)
    r = ejecutar(GUION, tmp_path, {"POST /api/secretario/push/alta": {"ok": True}}, previo=previo,
                 accion="setTimeout(() => nodo('push-activar').disparar('click'), 5);")
    assert r["errores"] == []
    assert ["sw", "/secretario/sw.js", "/secretario/"] in r["valores"]
    # La clave del secretario, en bytes: 65 (punto sin comprimir de P-256).
    assert ["clave", 65, True] in r["valores"]
    alta = [e for e in r["enviados"] if e["url"] == "/api/secretario/push/alta"]
    assert alta and alta[0]["cuerpo"]["keys"] == {"p256dh": "P", "auth": "A"}
    assert alta[0]["cuerpo"]["aparato"] == "Android · Chrome"
    assert "recargada" in r["valores"]


def test_si_el_hub_no_apunta_el_aparato_lo_dice_y_no_recarga(tmp_path):
    """C-0229: decía «recibe avisos» aunque el hub hubiera rechazado el alta."""
    previo = _navegador("Mozilla/5.0 (Linux; Android 15) Chrome/140 Mobile", con_push=True)
    r = ejecutar(GUION, tmp_path, {"POST /api/secretario/push/alta": {"ok": False, "error": "falta endpoint"}},
                 previo=previo,
                 accion="setTimeout(() => nodo('push-activar').disparar('click'), 5);"
                        "setTimeout(() => registro.valores.push(['dicho', nodo('push-texto').textContent]), 15);")
    assert r["errores"] == []
    assert "recargada" not in r["valores"]
    assert ["dicho", "No se pudo activar: falta endpoint"] in r["valores"]


# El hub contesta como a un aparato quitado de la lista (C-0232) al alta de
# abrir la pantalla, y apunta la del botón.
QUITADO_AL_ABRIR = ("global.SUSCRITA = sub; const _alta = global.fetch; global.fetch = (u, o) => {"
                    "  const p = _alta(u, o);"
                    "  return String(u).includes('/push/alta') && JSON.parse(o.body).motivo === 'abrir'"
                    "    ? Promise.resolve({ ok: true, status: 200,"
                    "        json: () => Promise.resolve({ ok: false, quitado: true, error: 'quitaste este aparato' }) })"
                    "    : p; };")
VOLCAR_BOTONES = ("setTimeout(() => registro.valores.push(['botones', nodo('push-activar').hidden,"
                  " nodo('push-probar').hidden, nodo('push-quitar').hidden]), 20);")


def test_un_aparato_quitado_de_la_lista_lo_dice_y_ofrece_activar_no_probar(tmp_path):
    """C-0232: decía «recibe avisos» y ofrecía mandar uno de prueba a un aparato quitado."""
    previo = _navegador("Mozilla/5.0 (Linux; Android 15) Chrome/140 Mobile", con_push=True) + QUITADO_AL_ABRIR
    r = ejecutar(GUION, tmp_path, {"POST /api/secretario/push/alta": {"ok": True}}, previo=previo,
                 accion=VOLCAR + VOLCAR_BOTONES)
    assert r["errores"] == []
    assert [e["cuerpo"]["motivo"] for e in r["enviados"] if e["url"] == "/api/secretario/push/alta"] == ["abrir"]
    assert _texto_push(r).startswith("Quitaste este aparato de la lista: <strong>no recibe avisos</strong>.")
    assert "«Activar avisos aquí» para volver" in _texto_push(r)
    # [activar, probar, desactivar] escondidos: sólo se ofrece activar.
    assert ["botones", False, True, True] in r["valores"]


def test_desde_un_aparato_quitado_activar_dice_que_es_el_boton_y_recarga(tmp_path):
    previo = _navegador("Mozilla/5.0 (Linux; Android 15) Chrome/140 Mobile", con_push=True) + QUITADO_AL_ABRIR
    r = ejecutar(GUION, tmp_path, {"POST /api/secretario/push/alta": {"ok": True}}, previo=previo,
                 accion="setTimeout(() => nodo('push-activar').disparar('click'), 10);")
    assert r["errores"] == []
    assert [e["cuerpo"]["motivo"] for e in r["enviados"] if e["url"] == "/api/secretario/push/alta"] == \
        ["abrir", "activar"]
    assert "recargada" in r["valores"]


def test_fuera_de_la_pantalla_de_avisos_el_alta_de_siempre_dice_que_es_de_abrir_la_app(tmp_path):
    """Sin `#push` (cualquier otra pestaña) sólo se re-sincroniza lo que ya había."""
    previo = (_navegador("Mozilla/5.0 (Linux; Android 15) Chrome/140 Mobile", con_push=True, permiso="granted")
              + "global.SUSCRITA = sub; const _get = document.getElementById;"
                "document.getElementById = (id) => id === 'push' ? null : _get(id);"
                "navigator.serviceWorker.getRegistration = (alcance) =>"
                "  navigator.serviceWorker.register('/secretario/sw.js', { scope: alcance });")
    r = ejecutar(GUION, tmp_path, {"POST /api/secretario/push/alta": {"ok": True}}, previo=previo)
    assert r["errores"] == []
    assert [e["cuerpo"]["motivo"] for e in r["enviados"] if e["url"] == "/api/secretario/push/alta"] == ["abrir"]


def test_si_la_prueba_no_sale_no_dice_enviado(tmp_path):
    """C-0229: «Enviado» salía aunque el hub contestara 403 o 500."""
    previo = (_navegador("Mozilla/5.0 (Linux; Android 15) Chrome/140 Mobile", con_push=True)
              + "global.SUSCRITA = sub; const _f = global.fetch; global.fetch = (u, o) =>"
                " String(u).includes('/push/prueba') ? Promise.resolve({ ok: false, status: 500,"
                " json: () => Promise.resolve({}) }) : _f(u, o);")
    r = ejecutar(GUION, tmp_path, {"POST /api/secretario/push/alta": {"ok": True}}, previo=previo,
                 accion="setTimeout(() => nodo('push-probar').disparar('click'), 3);"
                        "setTimeout(() => registro.valores.push(['dicho', nodo('push-texto').textContent]), 15);")
    assert r["errores"] == []
    dicho = [v[1] for v in r["valores"] if isinstance(v, list) and v[0] == "dicho"][-1]
    assert dicho.startswith("No se pudo pedir (el hub contestó 500)")


def test_al_abrir_la_pantalla_no_pide_permiso_solo_lo_ofrece(tmp_path):
    previo = _navegador("Mozilla/5.0 (Windows NT 10.0) Chrome/140", con_push=True)
    r = ejecutar(GUION, tmp_path, previo=previo, accion=VOLCAR)
    assert r["errores"] == []
    assert not any(isinstance(v, list) and v[0] == "clave" for v in r["valores"])
    assert "no recibe avisos todavía" in _texto_push(r)


def test_con_los_avisos_bloqueados_dice_como_desbloquearlos(tmp_path):
    previo = _navegador("Mozilla/5.0 (Windows NT 10.0) Chrome/140", con_push=True, permiso="denied")
    r = ejecutar(GUION, tmp_path, previo=previo, accion=VOLCAR)
    assert "bloqueados" in _texto_push(r)


# ── el formulario de disparadores (decisión 320) ─────────────────────────────

def test_el_formulario_guarda_un_disparador_y_la_lista_lo_ensena_con_quitar(cliente):
    r = cliente.post("/secretario/disparadores/nuevo", follow_redirects=False,
                     data={"clase": "horario", "hora": "09:30", "dias": ["L", "M", "X", "J", "V"],
                           "que": "pide", "pide": "dame el resumen de ayer"})
    assert r.status_code == 303 and "Guardado" in unquote(r.headers["location"])
    html = cliente.get("/secretario?p=disparadores").text
    assert "A las 09:30, de lunes a viernes: te pregunta «dame el resumen de ayer»" in html
    assert 'action="/secretario/disparadores/0/quitar"' in html
    cliente.post("/secretario/disparadores/0/quitar")
    assert "Ninguno todavía" in cliente.get("/secretario?p=disparadores").text


def test_al_formulario_incompleto_le_dice_que_falta(cliente):
    r = cliente.post("/secretario/disparadores/nuevo", follow_redirects=False,
                     data={"clase": "horario", "hora": "9:30", "que": "pide", "pide": "x"})
    assert "marca al menos un día" in unquote(r.headers["location"])


def test_el_formulario_ensena_solo_los_campos_de_lo_elegido(tmp_path):
    previo = ("nodo('sec').dataset = { ultimo: '0', pendientes: '0' };"
              "const f = nodo('disparador-nuevo'); nodo('disp-clase').value = 'evento'; nodo('disp-que').value = 'pide';"
              "const campos = ['horario', 'evento', 'mensaje'].map(c => Object.assign(nodo('c-' + c), { dataset: { clase: c } }));"
              "const ques = ['pide', 'haz'].map(q => Object.assign(nodo('q-' + q), { dataset: { que: q } }));"
              "f.querySelectorAll = (sel) => sel === '.disp-si' ? campos : ques;")
    accion = ("registro.valores.push(['vistos', nodo('c-horario').hidden, nodo('c-evento').hidden, nodo('q-haz').hidden]);"
              "nodo('disp-clase').value = 'horario'; nodo('disp-clase').disparar('change');"
              "registro.valores.push(['luego', nodo('c-horario').hidden, nodo('c-evento').hidden]);")
    r = ejecutar(GUION, tmp_path, previo=previo, accion=accion)
    assert r["errores"] == []
    v = {x[0]: x[1:] for x in r["valores"] if isinstance(x, list)}
    assert v["vistos"] == [True, False, True] and v["luego"] == [False, True]


# ── instalarla como app (decisión 316) ───────────────────────────────────────

# Guarda los oyentes de `window` para poder disparar `beforeinstallprompt`. El
# bloque y su botón llegan visibles del servidor (C-0229).
OYENTES_VENTANA = ("global.VENTANA = {}; global.addEventListener = (ev, fn) => { (VENTANA[ev] ||= []).push(fn); };"
                   "nodo('instalar').hidden = false; nodo('instalar-boton').hidden = false;"
                   "nodo('instalar-texto').innerHTML = 'del servidor';")
VOLCAR_INSTALAR = ("setTimeout(() => registro.valores.push(['instalar', nodo('instalar').hidden,"
                   " nodo('instalar-boton').hidden, nodo('instalar-texto').innerHTML]), 20);")


def _instalar(r):
    return [v for v in r["valores"] if isinstance(v, list) and v[0] == "instalar"][-1][1:]


def test_al_cargar_el_bloque_de_instalar_no_cambia_de_tamano(tmp_path):
    """C-0229: venía oculto y el script lo enseñaba después de pintar,
    empujando toda la pestaña (0,11 de salto en el teléfono). Ni el bloque,
    ni el botón, ni el texto cambian al cargar."""
    previo = OYENTES_VENTANA + _navegador("Mozilla/5.0 (Linux; Android 15) Chrome/140 Mobile", con_push=False)
    r = ejecutar(GUION, tmp_path, previo=previo, accion=VOLCAR_INSTALAR)
    assert r["errores"] == []
    assert _instalar(r) == [False, False, "del servidor"]


def test_cuando_chrome_lo_permite_el_boton_abre_su_dialogo(tmp_path):
    previo = OYENTES_VENTANA + _navegador("Mozilla/5.0 (Linux; Android 15) Chrome/140 Mobile", con_push=False)
    accion = """
      const oferta = { preventDefault(){ registro.valores.push('sin-barra'); },
                       prompt(){ registro.valores.push('dialogo'); }, userChoice: Promise.resolve({ outcome: 'accepted' }) };
      VENTANA.beforeinstallprompt.forEach(f => f(oferta));
      setTimeout(() => nodo('instalar-boton').disparar('click'), 5);
    """ + VOLCAR_INSTALAR
    r = ejecutar(GUION, tmp_path, previo=previo, accion=accion)
    assert r["errores"] == []
    assert "sin-barra" in r["valores"] and "dialogo" in r["valores"]
    assert r["avisos"] == []


def test_sin_oferta_del_navegador_el_boton_dice_donde_esta_en_el_menu(tmp_path):
    previo = OYENTES_VENTANA + _navegador("Mozilla/5.0 (Linux; Android 15) Chrome/140 Mobile", con_push=False)
    accion = "setTimeout(() => nodo('instalar-boton').disparar('click'), 5);" + VOLCAR_INSTALAR
    r = ejecutar(GUION, tmp_path, previo=previo, accion=accion)
    assert r["errores"] == []
    assert len(r["avisos"]) == 1 and "menú" in r["avisos"][0]["mensaje"]
    assert _instalar(r)[1] is False   # el botón sigue ahí


def test_abierta_como_app_no_ofrece_instalarla(tmp_path):
    previo = OYENTES_VENTANA + _navegador("Mozilla/5.0 (Linux; Android 15) Chrome/140 Mobile", con_push=False, app=True)
    r = ejecutar(GUION, tmp_path, previo=previo, accion=VOLCAR_INSTALAR)
    assert _instalar(r)[0] is True


# ── rutas de avisos y de la notificación ─────────────────────────────────────

def test_el_service_worker_se_sirve_sin_cache_y_no_intercepta_peticiones(cliente):
    r = cliente.get("/secretario/sw.js")
    assert r.status_code == 200 and "javascript" in r.headers["content-type"]
    assert r.headers["cache-control"] == "no-cache"
    # Decisión 168: el hub no cachea pantallas. Este service worker sólo atiende avisos.
    assert "'fetch'" not in r.text and '"fetch"' not in r.text


def test_dar_de_alta_un_aparato_guarda_el_origen_desde_el_que_se_suscribio(cliente):
    r = cliente.post("/api/secretario/push/alta", headers={"Origin": "http://127.0.0.1:8787"},
                     json={"endpoint": "https://push.ejemplo.org/1", "keys": {"p256dh": "P", "auth": "A"},
                           "aparato": "Android · Chrome"})
    assert r.json()["ok"] is True
    con = memoria.conectar()
    s = memoria.suscripciones(con)[0]
    con.close()
    assert s["origen"] == "http://127.0.0.1:8787" and s["aparato"] == "Android · Chrome"
    assert "Android · Chrome" in cliente.get("/secretario?p=avisos").text


MISMO_ORIGEN = {"Origin": "http://127.0.0.1:8787"}


def _alta(cliente, endpoint: str, aparato: str = "Android · Chrome", **extra) -> dict:
    cuerpo = {"endpoint": endpoint, "keys": {"p256dh": "P", "auth": "A"}, "aparato": aparato, **extra}
    return cliente.post("/api/secretario/push/alta", headers=MISMO_ORIGEN, json=cuerpo).json()


def _aparatos() -> list[tuple[str, str]]:
    con = memoria.conectar()
    try:
        return [(s["endpoint"], s["aparato"]) for s in memoria.suscripciones(con)]
    finally:
        con.close()


def test_un_aparato_quitado_de_la_lista_no_vuelve_al_abrir_la_app(cliente):
    """C-0232: «Quitar» duraba hasta que ese aparato volvía a abrir la app."""
    sid = _alta(cliente, "https://push.ejemplo.org/1", motivo="abrir")["id"]
    r = cliente.post(f"/secretario/aparato/{sid}/quitar", headers=MISMO_ORIGEN, follow_redirects=False)
    assert r.status_code == 303 and "aunque vuelva a abrir la app" in unquote(r.headers["location"])
    assert _alta(cliente, "https://push.ejemplo.org/1", motivo="abrir") == {
        "ok": False, "quitado": True,
        "error": "quitaste este aparato de la lista; «Activar avisos aquí» lo vuelve a apuntar"}
    # Un cliente de antes no dice qué alta es: tampoco lo trae de vuelta.
    assert _alta(cliente, "https://push.ejemplo.org/1")["quitado"] is True
    assert _aparatos() == []


def test_activar_avisos_aqui_vuelve_a_apuntar_un_aparato_quitado_y_olvida_que_se_quito(cliente):
    sid = _alta(cliente, "https://push.ejemplo.org/1", motivo="abrir")["id"]
    cliente.post(f"/secretario/aparato/{sid}/quitar", headers=MISMO_ORIGEN)
    assert _alta(cliente, "https://push.ejemplo.org/1", motivo="abrir")["quitado"] is True
    assert _alta(cliente, "https://push.ejemplo.org/1", motivo="activar")["ok"] is True
    # Y desde ahí vuelve a ser uno más: el alta de abrir la app ya lo apunta.
    assert _alta(cliente, "https://push.ejemplo.org/1", motivo="abrir")["ok"] is True
    assert _aparatos() == [("https://push.ejemplo.org/1", "Android · Chrome")]


def test_quitar_un_aparato_no_impide_que_otro_se_de_de_alta(cliente):
    sid = _alta(cliente, "https://push.ejemplo.org/1", motivo="abrir")["id"]
    cliente.post(f"/secretario/aparato/{sid}/quitar", headers=MISMO_ORIGEN)
    assert _alta(cliente, "https://push.ejemplo.org/2", aparato="Windows · Edge", motivo="abrir")["ok"] is True
    assert _alta(cliente, "https://push.ejemplo.org/1", motivo="abrir")["quitado"] is True
    assert _aparatos() == [("https://push.ejemplo.org/2", "Windows · Edge")]


def test_una_suscripcion_renovada_conserva_el_nombre_del_aparato_y_sustituye_su_fila(cliente):
    """C-0232: salía «renovada» hasta que el aparato volvía a abrir la app."""
    _alta(cliente, "https://push.ejemplo.org/vieja", aparato="iPhone · Safari (app)", motivo="abrir")
    _alta(cliente, "https://push.ejemplo.org/otra", aparato="Windows · Edge", motivo="abrir")
    r = _alta(cliente, "https://push.ejemplo.org/nueva", aparato="renovada", motivo="renovar",
              anterior="https://push.ejemplo.org/vieja")
    assert r["ok"] is True
    assert _aparatos() == [("https://push.ejemplo.org/otra", "Windows · Edge"),
                           ("https://push.ejemplo.org/nueva", "iPhone · Safari (app)")]
    # Sin la dirección vieja, o una que el hub no tiene, sale como hasta ahora.
    assert _alta(cliente, "https://push.ejemplo.org/a", aparato="renovada", motivo="renovar")["ok"] is True
    assert _alta(cliente, "https://push.ejemplo.org/b", aparato="renovada", motivo="renovar",
                 anterior="https://push.ejemplo.org/desconocida")["ok"] is True
    assert _aparatos()[2:] == [("https://push.ejemplo.org/a", "renovada"), ("https://push.ejemplo.org/b", "renovada")]


def test_la_renovacion_de_un_aparato_quitado_no_lo_vuelve_a_apuntar_ni_al_abrir_la_app(cliente):
    sid = _alta(cliente, "https://push.ejemplo.org/vieja", motivo="abrir")["id"]
    cliente.post(f"/secretario/aparato/{sid}/quitar", headers=MISMO_ORIGEN)
    assert _alta(cliente, "https://push.ejemplo.org/nueva", aparato="renovada", motivo="renovar",
                 anterior="https://push.ejemplo.org/vieja")["quitado"] is True
    # La dirección nueva queda quitada con la vieja: si no, volvería al abrir la app.
    assert _alta(cliente, "https://push.ejemplo.org/nueva", motivo="abrir")["quitado"] is True
    assert _aparatos() == []


def test_un_alta_con_un_motivo_que_no_existe_se_rechaza(cliente):
    r = cliente.post("/api/secretario/push/alta", headers=MISMO_ORIGEN,
                     json={"endpoint": "https://push.ejemplo.org/1", "keys": {"p256dh": "P", "auth": "A"},
                           "motivo": "porque_si"})
    assert r.status_code == 400 and "motivo" in r.json()["error"]
    assert _aparatos() == []


def test_aprobar_desde_la_notificacion_contesta_json(cliente):
    con = memoria.conectar()
    sid = con.execute("INSERT INTO solicitud (accion, params, motivo, creada) VALUES ('crear_slot', '{}', 'x', ?)",
                      (memoria.ahora(),)).lastrowid
    con.close()
    assert cliente.post(f"/api/secretario/solicitud/{sid}", json={"decision": "aprobar"}).json() == {"ok": True, "error": None}
    r = cliente.post(f"/api/secretario/solicitud/{sid}", json={"decision": "aprobar"}).json()
    assert r["ok"] is False and "ya estaba resuelta" in r["error"]


def test_hecho_y_en_una_hora_desde_el_aviso_de_un_recordatorio_contestan_json(cliente):
    """C-0407: los botones del aviso, por las mismas puertas que Pendientes
    (`cerrar_compromiso` y `editar_compromiso`), contestados en JSON."""
    from datetime import datetime
    con = memoria.conectar()
    cid = memoria.comprometer(con, "Llamar a Ana", vence="2099-01-01T18:00:00+00:00",
                              recordar_en="2020-01-01T00:00:00+00:00")
    memoria.marcar_recordado(con, cid)
    con.close()
    antes = datetime.fromisoformat(memoria.ahora())
    assert cliente.post(f"/api/secretario/compromiso/{cid}", json={"accion": "aplazar"}).json() == {"ok": True, "error": None}
    con = memoria.conectar()
    [c] = memoria.compromisos(con)
    con.close()
    # El aviso, otra vez pendiente y dentro de una hora; el texto y el plazo, como estaban.
    assert c["recordado"] is None and c["que"] == "Llamar a Ana" and c["vence"] == "2099-01-01T18:00:00+00:00"
    assert 3595 <= (datetime.fromisoformat(c["recordar_en"]) - antes).total_seconds() <= 3605

    assert cliente.post(f"/api/secretario/compromiso/{cid}", json={"accion": "hecho"}).json() == {"ok": True, "error": None}
    con = memoria.conectar()
    assert [c["id"] for c in memoria.compromisos(con, "hecho")] == [cid]
    con.close()
    # Ya cerrado, un aviso viejo no lo toca: ni «En 1 h» lo vuelve a avisar, ni «Hecho»
    # pasa un descartado a hecho o le cambia la hora de cierre (revisor).
    con = memoria.conectar()
    memoria.cerrar_compromiso(con, cid, "descartado")
    antes_cerrado = memoria.compromisos(con, "descartado")[0]["cerrado"]
    con.close()
    for accion in ("aplazar", "hecho"):
        r = cliente.post(f"/api/secretario/compromiso/{cid}", json={"accion": accion}).json()
        assert r["ok"] is False and "cerrado" in r["error"]
    con = memoria.conectar()
    assert memoria.compromisos(con, "descartado")[0]["cerrado"] == antes_cerrado
    con.close()
    for cuerpo in ({"accion": "hecho"}, {"accion": "aplazar"}):
        r = cliente.post("/api/secretario/compromiso/999", json=cuerpo).json()
        assert r["ok"] is False and "no existe" in r["error"]
    r = cliente.post(f"/api/secretario/compromiso/{cid}", json={"accion": "descartar"}).json()
    assert r["ok"] is False


@pytest.mark.parametrize("estado", ["ejecutando", "cortada"])
def test_lo_que_se_esta_haciendo_o_se_corto_ya_no_se_aprueba_ni_se_rechaza(cliente, estado):
    """C-0315: aprobar otra vez una que quedó a medias sería hacerla dos veces."""
    con = memoria.conectar()
    sid = con.execute("INSERT INTO solicitud (accion, params, motivo, creada, estado) VALUES ('crear_slot', '{}', 'x', ?, ?)",
                      (memoria.ahora(), estado)).lastrowid
    con.close()
    for decision in ("aprobar", "rechazar"):
        r = cliente.post(f"/api/secretario/solicitud/{sid}", json={"decision": decision}).json()
        assert r["ok"] is False and "ya estaba resuelta" in r["error"]
    con = memoria.conectar()
    assert con.execute("SELECT estado FROM solicitud").fetchone()[0] == estado
    con.close()


def test_una_cortada_se_ensena_como_no_se_si_se_hizo_y_no_cuenta_como_pendiente(cliente):
    con = memoria.conectar()
    con.execute("INSERT INTO solicitud (accion, params, motivo, creada, estado, resultado) VALUES"
                " ('anotar', '{}', 'x', ?, 'cortada', 'se cortó a mitad: no sé si llegó a hacerse; no se repite sola')",
                (memoria.ahora(),))
    con.execute("INSERT INTO solicitud (accion, params, motivo, creada, estado) VALUES ('anotar', '{}', 'x', ?, 'hecha')",
                (memoria.ahora(),))
    con.close()
    assert api.secretario_pendientes() == 0
    rotulos = {s["estado"]: s["estado_rotulo"] for s in api.secretario()["solicitudes"]}
    assert rotulos == {"cortada": "no sé si se hizo", "hecha": "hecha"}
    html = cliente.get("/secretario?p=pendientes").text
    assert '<span class="marca mal">no sé si se hizo</span>' in html
    assert '<span class="marca ok">hecha</span>' in html and ">cortada<" not in html


def test_volver_tras_un_formulario_nunca_sale_del_secretario(cliente):
    con = memoria.conectar()
    sid = con.execute("INSERT INTO solicitud (accion, params, motivo, creada) VALUES ('crear_slot', '{}', 'x', ?)",
                      (memoria.ahora(),)).lastrowid
    con.close()
    r = cliente.post(f"/secretario/solicitud/{sid}", data={"decision": "rechazar", "volver": "https://malo.example/x"},
                     follow_redirects=False)
    assert r.headers["location"].startswith("/secretario?p=pendientes")


def test_el_aviso_de_prueba_solo_deja_el_encargo(cliente):
    assert cliente.post("/api/secretario/push/prueba").json()["ok"] is True
    con = memoria.conectar()
    assert memoria.leer(con, "aviso_prueba")
    con.close()


def test_ajustes_abre_avisos_y_la_conversacion_esconde_el_otro_asistente(cliente):
    assert 'class="aqui">Avisos' in cliente.get("/secretario?p=ajustes").text.replace("\n", "")
    html = cliente.get("/secretario").text
    assert "app-propia" in html and "#asistente { display:none; }" in html
    assert "interactive-widget=resizes-content" in html


# ── la conversación por voz continua (decisión 314) ──────────────────────────

def _silencio(tmp_path, secuencia: str):
    """`secuencia`: [[rms, ms], …] en orden; devuelve el `fin` y cuándo."""
    accion = (f"let e = silencioInicial(); for (const [rms, ms] of {secuencia}) {{ for (let t = 0; t < ms; t += 100)"
              f" {{ e = silencioTras(e, rms, 100); if (e.fin) break; }} if (e.fin) break; }}"
              "registro.valores.push(['fin', e.fin, e.t]);")
    r = ejecutar(GUION, tmp_path, previo=PREVIO, accion=accion)
    assert r["errores"] == []
    return next(v[1:] for v in r["valores"] if isinstance(v, list) and v[0] == "fin")


def test_corta_al_callarse_despues_de_hablar(tmp_path):
    fin, t = _silencio(tmp_path, "[[0.004, 400], [0.08, 2000], [0.005, 3000]]")
    assert fin == "callado" and t == 400 + 2000 + 1300


def test_una_pausa_corta_al_hablar_no_corta(tmp_path):
    fin, _ = _silencio(tmp_path, "[[0.004, 400], [0.08, 1000], [0.005, 800], [0.08, 1000], [0.005, 400]]")
    assert fin is None


def test_sin_hablar_deja_de_escuchar_a_los_ocho_segundos(tmp_path):
    fin, t = _silencio(tmp_path, "[[0.004, 9000]]")
    assert fin == "nada" and t == 8000


def test_con_ruido_de_fondo_el_ruido_no_cuenta_como_hablar(tmp_path):
    # Un ventilador a 0.03: el fondo se acota a 0.02 (C-0285) y hablar es
    # pasar de 0.06, no del mínimo fijo.
    fin, _ = _silencio(tmp_path, "[[0.03, 400], [0.05, 9000]]")
    assert fin == "nada"


@pytest.mark.parametrize("desde", [0, 100, 200])
def test_si_empieza_a_hablar_al_abrir_el_microfono_no_se_tira_la_frase(tmp_path, desde):
    """Contestar al instante (C-0285): con la media de los primeros 400 ms
    como fondo, su propia voz era el fondo y a los 8 s se tiraba lo dicho."""
    antes = f"[0.004, {desde}], " if desde else ""
    fin, t = _silencio(tmp_path, f"[{antes}[0.08, 2000], [0.005, 3000]]")
    assert fin == "callado" and t == desde + 2000 + 1300


def test_un_si_dicho_mientras_se_mide_el_fondo_tambien_cuenta(tmp_path):
    fin, t = _silencio(tmp_path, "[[0.08, 300], [0.004, 3000]]")
    assert fin == "callado" and t == 300 + 1300


# Un analizador de audio que mide silencio: basta para que corra el bucle de 100 ms.
_CON_AUDIO = ("global.AudioContext = class { createAnalyser(){ return { fftSize: 0, getFloatTimeDomainData(){} }; }"
              "  createMediaStreamSource(){ return { connect(){} }; } close(){} };")

# Un micrófono y una voz de mentira: `REC` es la última grabadora creada.
VOZ_FALSA = ("global.SpeechSynthesisUtterance = class { constructor(t){ this.text = t; } };"
             "global.speechSynthesis.speak = (u) => { registro.valores.push(['dicho', u.text]); setTimeout(() => u.onend && u.onend(), 1); };"
             "global.MediaRecorder = class { constructor(){ this.state = 'inactive'; this.o = {}; global.REC = this; }"
             "  addEventListener(ev, f){ this.o[ev] = f; }"
             "  start(){ this.state = 'recording'; registro.valores.push('escuchando'); }"
             "  stop(){ if (this.state === 'inactive') return; this.state = 'inactive'; this.o.stop && this.o.stop(); } };"
             "navigator.mediaDevices = { getUserMedia: async () => ({ getTracks: () => [] }) };")


def test_en_modo_voz_lee_la_respuesta_y_vuelve_a_escuchar(tmp_path):
    respuesta = {"hilo": 1, "turnos": [{"id": 9, "rol": "secretario", "texto": "Tienes **dos** cosas.",
                                        "estado": "listo", "tarjetas": []}]}
    r = ejecutar(GUION, tmp_path, {"POST /api/secretario/mensaje": {"ok": True}, "/api/secretario/turnos": respuesta},
                 previo=PREVIO + VOZ_FALSA,
                 accion="nodo('sec-modo-voz').disparar('click');"
                        "setTimeout(() => { global.REC.stop(); nodo('sec-texto').value = 'hola'; }, 2);"
                        "setTimeout(() => nodo('sec-escribir').disparar('submit', {preventDefault(){}}), 3);")
    assert r["errores"] == []
    assert ["dicho", "Tienes dos cosas."] in r["valores"]
    # Una vez al entrar y otra después de leer la respuesta.
    assert r["valores"].count("escuchando") >= 2


def test_en_modo_voz_callarse_no_lo_apaga_vuelve_a_escuchar(tmp_path):
    """Antes, 8 s sin hablar desmarcaban la casilla y el modo se iba solo (decisión 317)."""
    # El arnés no corre `setInterval`: aquí cada intervalo da sus vueltas de
    # golpe hasta que lo paran. El micro falso sólo da silencio, así que cada
    # escucha llega a los 8 s simulados y termina en «no oí nada».
    accion = ("global.setInterval = (f) => { const id = { parado: false };"
              "  setTimeout(() => { for (let i = 0; i < 200 && !id.parado; i++) f(); }, 0); return id; };"
              "global.clearInterval = (id) => { if (id) id.parado = true; };"
              "nodo('sec-modo-voz').disparar('click');"
              "setTimeout(() => registro.valores.push(['panel', nodo('sec-panel-voz').hidden,"
              " nodo('sec-escribir').classList.contains('en-modo-voz')]), 15);")
    r = ejecutar(GUION, tmp_path, previo=PREVIO + VOZ_FALSA + _CON_AUDIO, accion=accion)
    assert r["errores"] == []
    assert r["valores"].count("escuchando") >= 2
    [panel] = [v[1:] for v in r["valores"] if isinstance(v, list) and v[0] == "panel"]
    assert panel == [False, True]


# Un micrófono que da audio al parar: lo grabado sí se sube a /api/voz.
_MICRO_CON_AUDIO = ("global.MediaRecorder = class { constructor(){ this.state = 'inactive'; this.o = {}; global.REC = this; }"
                    "  addEventListener(ev, f){ this.o[ev] = f; }"
                    "  start(){ this.state = 'recording'; registro.valores.push('escuchando'); }"
                    "  stop(){ if (this.state === 'inactive') return; this.state = 'inactive';"
                    "    this.o.dataavailable && this.o.dataavailable({ data: { size: 5 } }); this.o.stop && this.o.stop(); } };"
                    "global.Blob = class { constructor(p, o){ this.type = (o || {}).type; } };"
                    "global.FormData = class { append(k, v){ this[k] = v; } };")


def _modo_voz_tras_transcribir(tmp_path, voz: dict, mas: str = "", red: str = ""):
    """Entra en el modo voz, «habla» y para: devuelve lo que pasó con `voz` de respuesta."""
    accion = ("nodo('sec-modo-voz').disparar('click');"
              "setTimeout(() => global.REC.stop(), 2);"
              "setTimeout(() => registro.valores.push(['panel', nodo('sec-panel-voz').dataset.fase,"
              " nodo('sec-voz-pausa').textContent]), 15);" + mas)
    r = ejecutar(GUION, tmp_path, {"POST /api/voz": voz, "POST /api/secretario/mensaje": {"ok": True}},
                 previo=PREVIO + VOZ_FALSA + _MICRO_CON_AUDIO + red, accion=accion)
    assert r["errores"] == []
    return r


def test_en_modo_voz_una_tos_pregunta_y_vuelve_a_escuchar_sin_pausar(tmp_path):
    """Whisper no oyó palabras (C-0286): no es un error, no pausa."""
    r = _modo_voz_tras_transcribir(tmp_path, {"ok": False, "nada": True, "error": "no se oyó a nadie hablar"})
    v = r["valores"]
    assert ["dicho", "¿Perdón?"] in v
    assert "escuchando" in v[v.index(["dicho", "¿Perdón?"]):]
    [panel] = [x[1:] for x in v if isinstance(x, list) and x[0] == "panel"]
    assert panel == ["escuchando", "Pausar"]
    assert not [e for e in r["enviados"] if e["url"] == "/api/secretario/mensaje"]


def test_en_modo_voz_un_fallo_de_transcripcion_pausa_y_lo_dice(tmp_path):
    r = _modo_voz_tras_transcribir(tmp_path, {"ok": False, "error": "no hay transcriptor"})
    v = r["valores"]
    [panel] = [x[1:] for x in v if isinstance(x, list) and x[0] == "panel"]
    assert panel == ["pausa", "Seguir"]
    assert any(isinstance(x, list) and x[0] == "dicho" and "pausé" in x[1].lower() for x in v)


# Una red que se cae: las `fallos` primeras subidas a /api/voz no llegan.
# Se guarda lo que se intentó subir (`INTENTOS`) y lo que llegó (`SUBIDOS`),
# y `MISMO_AUDIO()` dice si todos los intentos llevaban el mismo trozo grabado.
def _red_que_falla(fallos: int) -> str:
    return (f"let fallos = {fallos}; globalThis.SUBIDOS = []; globalThis.INTENTOS = []; const _fetch = global.fetch;"
            "global.Blob = class { constructor(p, o){ this.partes = p; this.type = (o || {}).type; } };"
            "globalThis.MISMO_AUDIO = () => INTENTOS.every(a => a.partes[0] === INTENTOS[0].partes[0]);"
            "global.fetch = (url, o) => {"
            "  if (String(url) === '/api/voz') {"
            "    INTENTOS.push(o.body.audio);"
            "    if (fallos > 0) { fallos -= 1; registro.valores.push('subida-fallida');"
            "                      return Promise.reject(new TypeError('Failed to fetch')); }"
            "    SUBIDOS.push(o.body.audio); }"
            "  return _fetch(url, o); };"
            # El reintento espera 1,5 s: en el arnés, 2 ms.
            "const _st = global.setTimeout; global.setTimeout = (f, ms) => _st(f, ms === 1500 ? 2 : ms);")


def test_en_modo_voz_si_la_subida_falla_una_vez_se_reintenta_con_el_mismo_audio(tmp_path):
    """Un corte de la red del teléfono no puede costar lo dicho (C-0287)."""
    r = _modo_voz_tras_transcribir(tmp_path, {"ok": True, "texto": "lo que te explicaba"},
                                   mas="setTimeout(() => registro.valores.push(['subidos', SUBIDOS.length,"
                                       " MISMO_AUDIO()]), 18);",
                                   red=_red_que_falla(1))
    v = r["valores"]
    assert v.count("subida-fallida") == 1 and ["subidos", 1, True] in v
    mandados = [e["cuerpo"]["texto"] for e in r["enviados"] if e["url"] == "/api/secretario/mensaje"]
    assert mandados == ["lo que te explicaba"]


def test_si_la_subida_falla_dos_veces_lo_grabado_espera_a_reintentar(tmp_path):
    # El arnés vuelca a los 20 ms: todo antes.
    accion = ("setTimeout(() => registro.valores.push(['boton', nodo('sec-reintentar').hidden,"
              " nodo('sec-panel-voz').dataset.fase]), 10);"
              "setTimeout(() => { fallos = 0; nodo('sec-reintentar').disparar('click'); }, 11);"
              "setTimeout(() => registro.valores.push(['tras', nodo('sec-reintentar').hidden, SUBIDOS.length,"
              " MISMO_AUDIO()]), 18);")
    r = _modo_voz_tras_transcribir(tmp_path, {"ok": True, "texto": "lo que te explicaba"}, mas=accion,
                                   red=_red_que_falla(2))
    v = r["valores"]
    assert v.count("subida-fallida") == 2
    assert ["boton", False, "pausa"] in v
    assert ["tras", True, 1, True] in v
    mandados = [e["cuerpo"]["texto"] for e in r["enviados"] if e["url"] == "/api/secretario/mensaje"]
    assert mandados == ["lo que te explicaba"]


def test_en_modo_voz_si_el_mensaje_no_sale_pausa_lo_dice_y_reintentar_manda_lo_mismo(tmp_path):
    """El panel se quedaba en «transcribiendo» sin volver a escuchar ni decir
    nada, y lo dicho no estaba en ningún cuadro (C-0305): se perdía."""
    accion = ("setTimeout(() => registro.valores.push(['boton', nodo('sec-reintentar').hidden]), 16);"
              "setTimeout(() => { global.RED_CAIDA = false; nodo('sec-reintentar').disparar('click'); }, 17);")
    r = _modo_voz_tras_transcribir(tmp_path, {"ok": True, "texto": "lo que te explicaba"}, mas=accion,
                                   red=_MENSAJE_NO_SALE)
    v = r["valores"]
    [panel] = [x[1:] for x in v if isinstance(x, list) and x[0] == "panel"]
    assert panel == ["pausa", "Seguir"]
    assert any(isinstance(x, list) and x[0] == "dicho" and "pausé" in x[1].lower() for x in v)
    assert ["boton", False] in v
    [cuerpo] = [e["cuerpo"] for e in r["enviados"] if e["url"] == "/api/secretario/mensaje"]
    assert cuerpo["texto"] == "lo que te explicaba" and cuerpo["dictado"] is True and cuerpo["voz"] is True


def test_reintentar_manda_lo_escrito_y_sube_lo_grabado_sin_que_uno_pise_al_otro(tmp_path):
    """Lo grabado que no subió (C-0287) y lo escrito que no salió (C-0305)
    esperaban en la misma ranura: con el hub sin contestar, dictar y luego
    escribir dejaba sólo el texto, y Reintentar perdía el audio (C-0314)."""
    accion = ("nodo('sec-hablar').disparar('click');"
              "setTimeout(() => global.REC.stop(), 2);"
              "setTimeout(() => { nodo('sec-texto').value = 'lo escribo a mano';"
              "  nodo('sec-escribir').disparar('submit', {preventDefault(){}}); }, 10);"
              "setTimeout(() => registro.valores.push(['antes', nodo('sec-reintentar').hidden]), 13);"
              "setTimeout(() => { global.RED_CAIDA = false; nodo('sec-reintentar').disparar('click'); }, 14);"
              "setTimeout(() => registro.valores.push(['tras', nodo('sec-reintentar').hidden, SUBIDOS.length,"
              " nodo('sec-texto').value]), 19);")
    r = ejecutar(GUION, tmp_path, {"POST /api/voz": {"ok": True, "texto": "lo dictado"},
                                   "POST /api/secretario/mensaje": {"ok": True}},
                 previo=PREVIO + VOZ_FALSA + _MICRO_CON_AUDIO + _red_que_falla(2) + _MENSAJE_NO_SALE,
                 accion=accion)
    assert r["errores"] == []
    assert _estado(r, "antes") == [False]
    mandados = [e["cuerpo"]["texto"] for e in r["enviados"] if e["url"] == "/api/secretario/mensaje"]
    assert mandados == ["lo escribo a mano"]
    # Lo escrito salió primero; lo grabado se subió después y espera en el
    # cuadro a que lo revise, como cualquier dictado.
    oculto, subidos, cuadro = _estado(r, "tras")
    assert subidos == 1 and cuadro == "lo dictado" and oculto is True


def test_reintentar_mientras_sale_otro_mensaje_no_pierde_lo_que_esperaba(tmp_path):
    """Reintentar vaciaba la ranura antes de llamar a `enviar`, que con otro
    mensaje saliendo vuelve sin hacer nada: lo pendiente se perdía sin que
    nadie lo dijera (C-0314). Ahora espera hasta que se acepte."""
    red = ("global.RED_CAIDA = true; global.LENTO = false; const _fl = global.fetch;"
           "global.fetch = (url, o) => {"
           "  if (String(url) !== '/api/secretario/mensaje') return _fl(url, o);"
           "  if (global.RED_CAIDA) return Promise.reject(new TypeError('Failed to fetch'));"
           "  return global.LENTO ? new Promise(ok => setTimeout(() => ok(_fl(url, o)), 4)) : _fl(url, o); };")
    accion = ("const idea = document.querySelectorAll('[data-idea]')[0];"
              "idea.textContent = '¿qué tengo hoy?'; idea.disparar('click');"
              "setTimeout(() => { global.RED_CAIDA = false; global.LENTO = true; nodo('sec-texto').value = 'otra cosa';"
              "  nodo('sec-escribir').disparar('submit', {preventDefault(){}}); }, 3);"
              "setTimeout(() => nodo('sec-reintentar').disparar('click'), 4);"
              "setTimeout(() => registro.valores.push(['sigue', nodo('sec-reintentar').hidden]), 10);"
              "setTimeout(() => { global.LENTO = false; nodo('sec-reintentar').disparar('click'); }, 11);"
              "setTimeout(() => registro.valores.push(['tras', nodo('sec-reintentar').hidden]), 16);")
    r = ejecutar(GUION, tmp_path, {"POST /api/secretario/mensaje": {"ok": True}}, previo=PREVIO + red, accion=accion)
    assert r["errores"] == []
    assert _estado(r, "sigue") == [False]
    mandados = [e["cuerpo"]["texto"] for e in r["enviados"] if e["url"] == "/api/secretario/mensaje"]
    assert mandados == ["otra cosa", "¿qué tengo hoy?"]
    assert _estado(r, "tras") == [True]


@pytest.mark.parametrize("voz,red,dice", [
    (None, 2, "no se transcribió: el hub no contesta"),
    ({"ok": False, "error": "no hay transcriptor"}, 0, "no se transcribió: no hay transcriptor"),
])
def test_un_dictado_que_no_se_transcribe_lo_dice_en_rojo(tmp_path, voz, red, dice):
    """Los fallos del dictado se escribían a mano en la línea: salían en gris,
    como «transcribiendo…», y el vigía del tono le quitaba el rojo a un fallo
    anterior (C-0314, lo que C-0305 dejó para después)."""
    accion = ("nodo('sec-hablar').disparar('click');"
              "setTimeout(() => global.REC.stop(), 2);"
              "setTimeout(() => registro.valores.push(['linea', nodo('estado-sec').textContent,"
              " nodo('estado-sec').dataset.tono || '']), 12);")
    r = ejecutar(GUION, tmp_path, {"POST /api/voz": voz or {"ok": True, "texto": "x"}},
                 previo=PREVIO + VOZ_FALSA + _MICRO_CON_AUDIO + _red_que_falla(red), accion=accion)
    assert r["errores"] == []
    texto, tono = _estado(r, "linea")
    assert texto.startswith(dice) and tono == "error"


def test_si_no_se_grabo_nada_lo_dice_en_rojo(tmp_path):
    accion = ("nodo('sec-hablar').disparar('click');"
              "setTimeout(() => global.REC.stop(), 2);"
              "setTimeout(() => registro.valores.push(['linea', nodo('estado-sec').textContent,"
              " nodo('estado-sec').dataset.tono || '']), 6);")
    r = ejecutar(GUION, tmp_path, previo=PREVIO + VOZ_FALSA, accion=accion)
    assert r["errores"] == []
    assert _estado(r, "linea") == ["no se grabó nada", "error"]


def test_en_modo_voz_el_panel_dice_que_transcribe_y_luego_lo_que_entendio(tmp_path):
    """Al parar de grabar ya no dice «te escucho…» (C-0289), y mientras piensa
    enseña lo entendido, para ver de un vistazo si oyó mal e interrumpirle."""
    lento = ("const _f = global.fetch; global.fetch = (url, o) => String(url) === '/api/voz'"
             " ? new Promise(ok => setTimeout(() => ok(_f(url, o)), 6)) : _f(url, o);")
    abierto = {"hilo": 1, "turnos": [{"id": 2, "rol": "secretario", "texto": "", "estado": "pendiente", "tarjetas": []}]}
    accion = ("nodo('sec-modo-voz').disparar('click');"
              "setTimeout(() => global.REC.stop(), 2);"
              "const panel = (n) => registro.valores.push([n, nodo('sec-panel-voz').dataset.fase,"
              " nodo('sec-voz-estado').textContent]);"
              "setTimeout(() => panel('durante'), 4);"
              "setTimeout(() => panel('despues'), 15);"
              # Que acabe, o el sondeo no deja terminar al arnés.
              "setTimeout(() => RESPUESTAS['/api/secretario/turnos'].turnos.forEach(t => { t.estado = 'listo'; }), 16);")
    r = ejecutar(GUION, tmp_path, {"POST /api/voz": {"ok": True, "texto": "abre lo de Brisa mantenimiento"},
                                   "POST /api/secretario/mensaje": {"ok": True}, "/api/secretario/turnos": abierto},
                 previo=PREVIO + VOZ_FALSA + _MICRO_CON_AUDIO + lento, accion=accion)
    assert r["errores"] == []
    v = {x[0]: x[1:] for x in r["valores"] if isinstance(x, list) and x[0] in ("durante", "despues")}
    assert v["durante"][0] == "transcribiendo" and "escucho" not in v["durante"][1]
    assert v["despues"] == ["pensando", "Entendí: «abre lo de Brisa mantenimiento»"]


@pytest.mark.parametrize("nombre,dice", [
    ("NotAllowedError", "permiso"),
    ("NotFoundError", "no hay ningún micrófono"),
    ("NotReadableError", "ocupado por otra aplicación"),
])
def test_cada_fallo_del_microfono_dice_el_suyo_y_en_modo_voz_pausa(tmp_path, nombre, dice):
    """Sin permiso, sin micrófono u ocupado (una reunión) se arreglan distinto
    (C-0290). En el modo voz el panel se quedaba en la fase de antes."""
    micro = ("navigator.mediaDevices = { getUserMedia: async () => {"
             f" const e = new Error('x'); e.name = '{nombre}'; throw e; }} }};")
    accion = ("nodo('sec-hablar').disparar('click');"
              "setTimeout(() => registro.valores.push(['suelto', nodo('estado-sec').textContent]), 3);"
              "setTimeout(() => nodo('sec-modo-voz').disparar('click'), 4);"
              "setTimeout(() => registro.valores.push(['modo', nodo('sec-panel-voz').dataset.fase,"
              " nodo('sec-voz-estado').textContent, nodo('sec-voz-pausa').textContent]), 10);")
    r = ejecutar(GUION, tmp_path, previo=PREVIO + VOZ_FALSA + micro, accion=accion)
    assert r["errores"] == []
    v = {x[0]: x[1:] for x in r["valores"] if isinstance(x, list) and x[0] in ("suelto", "modo")}
    assert dice in v["suelto"][0]
    assert v["modo"][0] == "pausa" and dice in v["modo"][1] and v["modo"][2] == "Seguir"


# ── el chat graba con `HubGrabar` (C-0311) ───────────────────────────────────

# Un `HubGrabar` de mentira puesto antes de cargar `grabar.js`, que con uno ya
# presente no hace nada: anota con qué se le llama. `TOMA` es la última toma.
# El navegador no tiene micrófono propio que valga: si el chat abriera el suyo
# por su cuenta, no grabaría nada.
HUBGRABAR_ESPIA = """
  registro.api = [];
  globalThis.HubGrabar = {
    RESTRICCIONES: { llano: 'LLANO', conversacion: 'CONVERSACION' },
    puede: () => true,
    calentar: () => { registro.api.push(['calentar']); },
    microfono: async (r) => { registro.api.push(['microfono', r]);
                              return { getTracks: () => [{ stop() { registro.api.push(['suelta']); } }] }; },
    grabar: async (o) => {
      registro.api.push(['grabar', o.restricciones]);
      let fin;
      const terminado = new Promise((ok) => { fin = ok; });
      const grabadora = { state: 'recording' };
      const toma = { flujo: { getTracks: () => [] }, grabadora, ajustes: {}, terminado,
                     parar() { grabadora.state = 'inactive'; fin('AUDIO'); return terminado; },
                     descartar() { grabadora.state = 'inactive'; fin(null); return terminado; } };
      globalThis.TOMA = toma;
      return toma;
    },
    subir: async (audio, o) => { registro.api.push(['subir', audio, o]);
                                 return { ok: true, texto: 'por el grabador común' }; },
  };
"""


def test_hablarle_graba_y_sube_por_el_grabador_comun_con_las_restricciones_de_la_conversacion(tmp_path):
    """Un solo grabador (C-0311). El chat conserva SUS restricciones —sin el
    eco de su propia voz ni el ruido, decisión 318— y su idioma y su origen
    en la subida; lo que hace con el texto (al cuadro, a revisar) es suyo."""
    accion = ("nodo('sec-hablar').disparar('click');"
              "setTimeout(() => nodo('sec-hablar').disparar('click'), 2);"
              "setTimeout(() => registro.valores.push(['cuadro', nodo('sec-texto').value,"
              " nodo('estado-sec').textContent]), 8);")
    r = ejecutar(GUION, tmp_path, previo=PREVIO + HUBGRABAR_ESPIA, accion=accion)
    assert r["errores"] == []
    assert r["api"] == [["calentar"], ["grabar", "CONVERSACION"],
                        ["subir", "AUDIO", {"campos": {"idioma": "es", "origen": "secretario"}}]]
    assert _estado(r, "cuadro") == ["por el grabador común", "revísalo y pulsa Enviar"]


def test_el_vigia_que_le_deja_interrumpir_abre_el_micro_por_el_grabador_comun_y_lo_suelta(tmp_path):
    """El vigía de interrupción (decisión 318) sigue siendo del chat; el
    micrófono lo abre `HubGrabar.microfono`, sin grabar, con las mismas
    restricciones que la conversación. Al acabar de leer, lo suelta y vuelve
    a escuchar."""
    respuesta = {"hilo": 1, "turnos": [{"id": 9, "rol": "secretario", "texto": "Tienes dos cosas.",
                                        "estado": "listo", "tarjetas": []}]}
    accion = ("nodo('sec-modo-voz').disparar('click');"
              "setTimeout(() => TOMA.parar(), 2);")
    r = ejecutar(GUION, tmp_path, {"POST /api/secretario/mensaje": {"ok": True}, "/api/secretario/turnos": respuesta},
                 previo=PREVIO + VOZ_FALSA + _CON_AUDIO + HUBGRABAR_ESPIA, accion=accion)
    assert r["errores"] == []
    api = r["api"]
    assert ["dicho", "Tienes dos cosas."] in r["valores"]
    assert ["microfono", "CONVERSACION"] in api
    # Lo suelta, y después vuelve a escuchar con la misma conversación.
    tras = api[api.index(["microfono", "CONVERSACION"]):]
    assert ["suelta"] in tras and ["grabar", "CONVERSACION"] in tras[tras.index(["suelta"]):]
    assert all(x == ["grabar", "CONVERSACION"] for x in api if x[0] == "grabar")


def test_el_chat_y_su_vigia_abren_el_microfono_con_eco_y_ruido_quitados(tmp_path):
    """Las restricciones no se unifican con las de la terminal: cambiarlas
    cambia cómo se oye (C-0311). Con el micrófono de verdad del navegador."""
    respuesta = {"hilo": 1, "turnos": [{"id": 9, "rol": "secretario", "texto": "Tienes dos cosas.",
                                        "estado": "listo", "tarjetas": []}]}
    micro = ("registro.restricciones = [];"
             "navigator.mediaDevices = { getUserMedia: async (r) => { registro.restricciones.push(r);"
             " return { getTracks: () => [{ stop(){} }] }; } };")
    accion = ("nodo('sec-modo-voz').disparar('click');"
              "setTimeout(() => { global.REC.stop(); nodo('sec-texto').value = 'hola'; }, 2);"
              "setTimeout(() => nodo('sec-escribir').disparar('submit', {preventDefault(){}}), 3);")
    r = ejecutar(GUION, tmp_path, {"POST /api/secretario/mensaje": {"ok": True}, "/api/secretario/turnos": respuesta},
                 previo=PREVIO + VOZ_FALSA + _CON_AUDIO + micro, accion=accion)
    assert r["errores"] == []
    assert ["dicho", "Tienes dos cosas."] in r["valores"]
    # Al entrar, el vigía mientras lee, y otra vez al acabar de leer.
    assert len(r["restricciones"]) >= 3
    assert all(x == {"audio": {"echoCancellation": True, "noiseSuppression": True}} for x in r["restricciones"])


def test_lo_que_sale_de_whisper_sin_pasar_por_tus_ojos_va_marcado_como_dictado(tmp_path):
    """C-0291: el modo voz manda lo dictado como `dictado: true`."""
    r = _modo_voz_tras_transcribir(tmp_path, {"ok": True, "texto": "abre lo de prisa"})
    [cuerpo] = [e["cuerpo"] for e in r["enviados"] if e["url"] == "/api/secretario/mensaje"]
    assert cuerpo["dictado"] is True and cuerpo["voz"] is True


def _dictar_al_cuadro(tmp_path, editar: str):
    """Dicta con el micrófono (el texto va al cuadro), `editar` lo toca o no, y se envía."""
    accion = ("nodo('sec-hablar').disparar('click');"
              "setTimeout(() => global.REC.stop(), 2);"
              f"setTimeout(() => {{ {editar} nodo('sec-escribir').disparar('submit', {{preventDefault(){{}}}}); }}, 8);")
    r = ejecutar(GUION, tmp_path, {"POST /api/voz": {"ok": True, "texto": "abre lo de prisa"},
                                   "POST /api/secretario/mensaje": {"ok": True}},
                 previo=PREVIO + VOZ_FALSA + _MICRO_CON_AUDIO, accion=accion)
    assert r["errores"] == []
    [cuerpo] = [e["cuerpo"] for e in r["enviados"] if e["url"] == "/api/secretario/mensaje"]
    return cuerpo


def test_lo_dictado_al_cuadro_y_enviado_sin_tocar_va_marcado_y_lo_editado_no(tmp_path):
    sin_tocar = _dictar_al_cuadro(tmp_path, "")
    assert sin_tocar["texto"] == "abre lo de prisa" and sin_tocar.get("dictado") is True
    editado = _dictar_al_cuadro(tmp_path, "nodo('sec-texto').value = 'abre lo de Brisa';")
    assert editado["texto"] == "abre lo de Brisa" and "dictado" not in editado


def test_entrar_al_modo_voz_y_el_microfono_calientan_el_whisper_una_vez_cada_rato(tmp_path):
    """C-0292: al empezar a grabar, no al mandar. Cada escucha del modo voz
    no vuelve a pedirlo: con una vez cada 30 s basta, el servidor dura 15 min."""
    accion = ("nodo('sec-modo-voz').disparar('click');"
              "setTimeout(() => nodo('sec-voz-salir').disparar('click'), 2);"
              "setTimeout(() => nodo('sec-hablar').disparar('click'), 4);")
    r = ejecutar(GUION, tmp_path, {"POST /api/voz/calentar": {"ok": True, "estado": "arrancando"}},
                 previo=PREVIO + VOZ_FALSA, accion=accion)
    assert r["errores"] == []
    calentar = [e for e in r["enviados"] if e["url"] == "/api/voz/calentar"]
    peticiones = [p for p in r["peticiones"] if p == "/api/voz/calentar"]
    assert len(peticiones) == 1 and calentar == []   # un POST sin cuerpo
    assert r["valores"].count("escuchando") == 2


def test_pausar_y_seguir_no_salen_del_modo_y_la_x_si(tmp_path):
    accion = """
      nodo('sec-modo-voz').disparar('click');
      setTimeout(() => nodo('sec-voz-pausa').disparar('click'), 2);
      setTimeout(() => registro.valores.push(['pausa', nodo('sec-panel-voz').dataset.fase, nodo('sec-voz-pausa').textContent,
                                               nodo('sec-panel-voz').hidden]), 4);
      setTimeout(() => nodo('sec-voz-pausa').disparar('click'), 6);
      setTimeout(() => registro.valores.push(['sigue', nodo('sec-panel-voz').dataset.fase]), 8);
      setTimeout(() => nodo('sec-voz-salir').disparar('click'), 10);
      setTimeout(() => registro.valores.push(['fuera', nodo('sec-panel-voz').hidden,
                                               nodo('sec-escribir').classList.contains('en-modo-voz')]), 12);
    """
    r = ejecutar(GUION, tmp_path, previo=PREVIO + VOZ_FALSA, accion=accion)
    assert r["errores"] == []
    v = {x[0]: x[1:] for x in r["valores"] if isinstance(x, list) and x[0] in ("pausa", "sigue", "fuera")}
    assert v["pausa"] == ["pausa", "Seguir", False]
    assert v["sigue"] == ["escuchando"]
    assert v["fuera"] == [True, False]


# ── leer frase a frase mientras escribe (C-0155) ─────────────────────────────

def _frases(tmp_path, pasos: str):
    """`pasos`: [[texto, final], …]; devuelve lo que se diría en cada paso."""
    accion = (f"let d = ''; for (const [t, f] of {pasos}) {{ const r = frasesNuevas(d, t, f); d = r.dicho;"
              " registro.valores.push(['paso', r.frases, r.final]); }")
    r = ejecutar(GUION, tmp_path, previo=PREVIO, accion=accion)
    assert r["errores"] == []
    return [v[1:] for v in r["valores"] if isinstance(v, list) and v[0] == "paso"]


def test_una_frase_a_medias_espera_y_la_completa_se_dice_una_sola_vez(tmp_path):
    pasos = _frases(tmp_path, '[["Tienes dos reun", false], ["Tienes dos reuniones. La pri", false],'
                              ' ["Tienes dos reuniones. La primera a las 10.", true]]')
    assert pasos == [[[], False], [["Tienes dos reuniones."], False], [["La primera a las 10."], False]]


def test_los_decimales_y_la_hora_no_parten_la_frase(tmp_path):
    pasos = _frases(tmp_path, '[["Son las 10.30 y faltan 2.5 h", false], ["Son las 10.30 y faltan 2.5 h. Bien.", true]]')
    assert pasos == [[[], False], [["Son las 10.30 y faltan 2.5 h.", "Bien."], False]]


def test_una_abreviatura_no_parte_la_frase(tmp_path):
    """VOZ-20 (C-0357): «p. ej.» y «Sr.» partían la frase en dos, con su pausa."""
    pasos = _frases(tmp_path, '[["Habla con el Sr. Pérez, p. ej. mañana. Luego lo otro. Y", false]]')
    assert pasos == [[["Habla con el Sr. Pérez, p. ej. mañana.", "Luego lo otro."], False]]


# ── lo que se dice en voz alta, limpio (VOZ-20, C-0357) ──────────────────────

PARA_OIR = [
    ("Tienes **dos** cosas en [Trabajo](/trabajo).", "Tienes dos cosas en Trabajo."),
    ("Lo leí con `hub_estado`.", "Lo leí con hub estado."),
    ("Está en src/hub/secretario/conversacion.py, al principio.", "Está en conversacion, al principio."),
    ("Míralo en ~/proyectos/voz-lab/INFORME.md", "Míralo en INFORME"),
    ("Lo dice secretario.yml y la pantalla /trabajo.", "Lo dice secretario y la pantalla trabajo."),
    ("¡Hecho! 🎉 Ya está ✅.", "¡Hecho! Ya está."),
    ("Mañana → reunión · 10 personas", "Mañana a reunión, 10 personas"),
    ("Lo dejé en C-0155. La C-0244 sigue.", "Lo dejé en la ficha 155. La ficha 244 sigue."),
    ("Tardó 3,2 s y 300 ms; 1 s más.", "Tardó 3,2 segundos y 300 milisegundos; 1 segundo más."),
    ("Ocupa 2 GB, el 45%, y faltan 2.5 h y 10 min.", "Ocupa 2 gigas, el 45 por ciento, y faltan 2.5 horas y 10 minutos."),
    ("Vence el 2026-11-11 y el otro el 2025-03-01.", "Vence el 11 de noviembre y el otro el 1 de marzo de 2025."),
    ("¿Sí/no? Llama y/o escribe.", "¿Sí o no? Llama o escribe."),
    ("Del 12/11 al 1/2, con https://ejemplo.org/a?b=1 dentro.", "Del 12/11 al 1/2, con un enlace dentro."),
    ("- primero\n- segundo", "primero\nsegundo"),
    ("Algo corto, p. ej. esto.", "Algo corto, por ejemplo esto."),
    # Las citas de una investigación digerida (C-0452): «corchete uno» no se lee.
    # Sólo detrás de un signo o en grupo: «elige la [2]» puede ser lo que dice (revisión de C-0452).
    ("- Cuesta 80 dólares. [1][3]\nSale en marzo. [2]\nO en abril [2][4].", "Cuesta 80 dólares.\nSale en marzo.\nO en abril."),
    ("Hay dos: elige la [2].", "Hay dos: elige la [2]."),
]


def test_lo_que_se_lee_en_voz_alta_no_dice_simbolos_rutas_ni_codigos(tmp_path):
    """VOZ-20 (C-0357): la voz leía «barra», nombres de emojis, «ce guion cero
    ciento cincuenta y cinco» y «tres coma dos ese». `paraOir` es pura y se
    prueba con pares; el año en curso se le pasa para que no dependa del día."""
    accion = f"for (const [a] of {json.dumps(PARA_OIR)}) registro.valores.push(['oido', paraOir(a, 2026)]);"
    r = ejecutar(GUION, tmp_path, previo=PREVIO, accion=accion)
    assert r["errores"] == []
    oidos = [v[1] for v in r["valores"] if isinstance(v, list) and v[0] == "oido"]
    assert list(zip([a for a, _ in PARA_OIR], oidos)) == [(a, b) for a, b in PARA_OIR]


def test_lo_que_se_lee_se_acota_y_cien_mil_caracteres_no_tardan(tmp_path):
    """`paraOir` no tiene regex exponenciales pero sí cuadráticas: 100 000
    caracteres seguidos tardaban 6,6 s, y `anunciar` le pasa el turno entero.
    Se acota antes de limpiar, cortando en frase. El margen es holgado: acotado
    tarda milésimas."""
    accion = ("const t0 = performance.now();"
              "const a = paraOir('x'.repeat(100000), 2026);"
              "const b = paraOir('Una frase corta en ruta/de/algo. '.repeat(3000), 2026);"
              "registro.valores.push(['oir', performance.now() - t0, a.length, b.length, b.slice(-5)]);")
    r = ejecutar(GUION, tmp_path, previo=PREVIO, accion=accion)
    assert r["errores"] == []
    [(ms, largo_a, largo_b, final_b)] = [x[1:] for x in r["valores"] if isinstance(x, list) and x[0] == "oir"]
    assert ms < 1500, f"{ms:.0f} ms"
    assert 0 < largo_a <= 4000 and 0 < largo_b <= 4000
    assert final_b == "algo.", "se corta donde acaba una frase, no a media palabra"


def test_si_la_respuesta_se_rehace_espera_a_la_final_y_la_lee_entera(tmp_path):
    pasos = _frases(tmp_path, '[["Déjame mirarlo. ", false], ["Otra cosa", false], ["Otra cosa distinta.", true]]')
    assert pasos[1:] == [[[], False], [["Otra cosa distinta."], False]]
    pasos = _frases(tmp_path, '[["Déjame mirarlo. ", false], ["", false], ["La buena.", true]]')
    assert pasos[1:] == [[[], False], [["La buena."], False]]


def test_en_modo_voz_empieza_a_leer_antes_de_que_termine_de_escribir(tmp_path):
    """La primera frase suena con el turno aún «escribiendo»; al acabar se
    lee sólo lo que faltaba y vuelve a escuchar."""
    a_medias = {"hilo": 1, "turnos": [{"id": 9, "rol": "secretario", "texto": "Déjame mirarlo. Tienes",
                                       "estado": "escribiendo", "tarjetas": []}]}
    entera = [{"id": 9, "rol": "secretario", "texto": "Déjame mirarlo. Tienes **dos** cosas.",
               "estado": "listo", "tarjetas": []}]
    # El arnés vuelca a los 20 ms: el sondeo de 300 ms del modo voz se acorta.
    accion = ("const st = global.setTimeout; global.setTimeout = (f, ms) => st(f, ms === 300 ? 3 : ms);"
              "nodo('sec-modo-voz').disparar('click');"
              "setTimeout(() => { global.REC.stop(); nodo('sec-texto').value = 'hola'; }, 2);"
              "setTimeout(() => nodo('sec-escribir').disparar('submit', {preventDefault(){}}), 3);"
              "setTimeout(() => { registro.valores.push('ya-escrito');"
              f"  RESPUESTAS['/api/secretario/turnos'].turnos = {json.dumps(entera)}; }}, 9);")
    r = ejecutar(GUION, tmp_path, {"POST /api/secretario/mensaje": {"ok": True}, "/api/secretario/turnos": a_medias},
                 previo=PREVIO + VOZ_FALSA, accion=accion)
    assert r["errores"] == []
    v = r["valores"]
    dichos = [x[1] for x in v if isinstance(x, list) and x[0] == "dicho"]
    assert dichos == ["Déjame mirarlo.", "Tienes dos cosas."]
    assert v.index(["dicho", "Déjame mirarlo."]) < v.index("ya-escrito")
    assert {"url": "/api/secretario/mensaje", "metodo": "POST", "cuerpo": {"texto": "hola", "voz": True}} in r["enviados"]
    assert "escuchando" in v[v.index(["dicho", "Tienes dos cosas."]):]


def test_la_frase_que_acaba_un_bloque_se_dice_aunque_no_lleve_nada_detras(tmp_path):
    """El motor deja «Déjame mirarlo.» sin espacio detrás mientras corre la
    herramienta (C-0284): con el bloque cerrado, el punto final cuenta. Sin
    cerrar, no: «las 10.» puede seguir con «30»."""
    pasos = _frases(tmp_path, '[["Son las 10.", false]]')
    assert pasos == [[[], False]]
    accion = ("registro.valores.push(['cerrado', frasesNuevas('', 'Déjame mirarlo.', false, true)]);"
              "registro.valores.push(['sin-punto', frasesNuevas('', 'Déjame mirar', false, true)]);")
    r = ejecutar(GUION, tmp_path, previo=PREVIO, accion=accion)
    assert r["errores"] == []
    v = {x[0]: x[1] for x in r["valores"] if isinstance(x, list) and x[0] in ("cerrado", "sin-punto")}
    assert v["cerrado"] == {"frases": ["Déjame mirarlo."], "dicho": "Déjame mirarlo.", "final": False}
    assert v["sin-punto"]["frases"] == []


def test_en_modo_voz_dejame_mirarlo_suena_mientras_corre_la_herramienta(tmp_path):
    """Lo que de verdad da el motor: «Déjame mirarlo.» sin nada detrás y el
    turno «trabajando» (C-0284). Suena antes de que llegue la respuesta."""
    mirando = {"hilo": 1, "turnos": [{"id": 9, "rol": "secretario", "texto": "Déjame mirarlo.",
                                      "estado": "escribiendo", "tarjetas": [],
                                      "actividad": {"estado": "trabajando", "gesto": "buscar",
                                                    "rotulo": "Mirando tu agenda"}}]}
    entera = [{"id": 9, "rol": "secretario", "texto": "Déjame mirarlo.\n\nTienes dos cosas.",
               "estado": "listo", "tarjetas": [], "actividad": None}]
    accion = ("const st = global.setTimeout; global.setTimeout = (f, ms) => st(f, ms === 300 ? 3 : ms);"
              "nodo('sec-modo-voz').disparar('click');"
              "setTimeout(() => { global.REC.stop(); nodo('sec-texto').value = 'hola'; }, 2);"
              "setTimeout(() => nodo('sec-escribir').disparar('submit', {preventDefault(){}}), 3);"
              "setTimeout(() => { registro.valores.push('herramienta-acabada');"
              f"  RESPUESTAS['/api/secretario/turnos'].turnos = {json.dumps(entera)}; }}, 12);")
    r = ejecutar(GUION, tmp_path, {"POST /api/secretario/mensaje": {"ok": True}, "/api/secretario/turnos": mirando},
                 previo=PREVIO + VOZ_FALSA, accion=accion)
    assert r["errores"] == []
    v = r["valores"]
    dichos = [x[1] for x in v if isinstance(x, list) and x[0] == "dicho"]
    assert dichos == ["Déjame mirarlo.", "Tienes dos cosas."]
    assert v.index(["dicho", "Déjame mirarlo."]) < v.index("herramienta-acabada")


def test_en_modo_voz_si_escala_al_modelo_mayor_lee_su_respuesta(tmp_path):
    """El menor dice «déjame mirarlo», escala, el turno se vacía y llega la del mayor."""
    pasos = [[{"id": 9, "rol": "secretario", "texto": "Déjame mirarlo. ", "estado": "escribiendo", "tarjetas": []}],
             [{"id": 9, "rol": "secretario", "texto": "", "estado": "escribiendo", "tarjetas": []}],
             [{"id": 9, "rol": "secretario", "texto": "La respuesta del mayor.", "estado": "listo", "tarjetas": []}]]
    accion = ("const st = global.setTimeout; global.setTimeout = (f, ms) => st(f, ms === 300 ? 2 : ms);"
              f"const PASOS = {json.dumps(pasos)};"
              "nodo('sec-modo-voz').disparar('click');"
              "setTimeout(() => { global.REC.stop(); nodo('sec-texto').value = 'hola'; }, 2);"
              "setTimeout(() => nodo('sec-escribir').disparar('submit', {preventDefault(){}}), 3);"
              "setTimeout(() => { RESPUESTAS['/api/secretario/turnos'].turnos = PASOS[1]; }, 7);"
              "setTimeout(() => { RESPUESTAS['/api/secretario/turnos'].turnos = PASOS[2]; }, 11);")
    r = ejecutar(GUION, tmp_path, {"POST /api/secretario/mensaje": {"ok": True},
                                   "/api/secretario/turnos": {"hilo": 1, "turnos": pasos[0]}},
                 previo=PREVIO + VOZ_FALSA, accion=accion)
    assert r["errores"] == []
    dichos = [x[1] for x in r["valores"] if isinstance(x, list) and x[0] == "dicho"]
    assert dichos == ["Déjame mirarlo.", "La respuesta del mayor."]


# ── interrumpirle hablando (decisión 318) ────────────────────────────────────

def _interrupcion(tmp_path, secuencia: str):
    accion = (f"let e = interrupcionInicial(); for (const [rms, ms] of {secuencia}) {{ for (let t = 0; t < ms; t += 100)"
              f" {{ e = interrupcionTras(e, rms, 100); if (e.fin) break; }} if (e.fin) break; }}"
              "registro.valores.push(['fin', e.fin, e.t]);")
    r = ejecutar(GUION, tmp_path, previo=PREVIO, accion=accion)
    assert r["errores"] == []
    return next(v[1:] for v in r["valores"] if isinstance(v, list) and v[0] == "fin")


def test_su_propio_eco_no_le_interrumpe(tmp_path):
    fin, _ = _interrupcion(tmp_path, "[[0.04, 600], [0.07, 5000]]")
    assert fin is False


def test_tu_voz_por_encima_del_eco_le_interrumpe_a_los_300_ms(tmp_path):
    fin, t = _interrupcion(tmp_path, "[[0.04, 600], [0.2, 2000]]")
    assert fin is True and t == 600 + 300


def test_un_golpe_suelto_no_le_interrumpe(tmp_path):
    fin, _ = _interrupcion(tmp_path, "[[0.02, 600], [0.3, 200], [0.02, 3000]]")
    assert fin is False


def test_en_modo_voz_hablarle_mientras_lee_le_calla_y_vuelve_a_escuchar(tmp_path):
    respuesta = {"hilo": 1, "turnos": [{"id": 9, "rol": "secretario", "texto": "Una respuesta larga.",
                                        "estado": "listo", "tarjetas": []}]}
    # Habla sin terminar nunca, salvo que se le calle. El micro da 6 muestras
    # de eco bajo y después voz fuerte.
    previo = (PREVIO + VOZ_FALSA +
              "global.speechSynthesis.speak = (u) => { registro.valores.push('habla'); global.HABLANDO = u; };"
              "global.speechSynthesis.cancel = () => { const u = global.HABLANDO; global.HABLANDO = null;"
              "  if (u) { registro.valores.push('callado'); u.onend && u.onend(); } };"
              "let muestras = 0;"
              "global.AudioContext = class { createAnalyser(){ return { fftSize: 4,"
              "  getFloatTimeDomainData(m){ muestras += 1; m.fill(muestras <= 6 ? 0.02 : 0.3); } }; }"
              "  createMediaStreamSource(){ return { connect(){} }; } close(){} };")
    accion = ("global.setInterval = (f) => { const id = { parado: false };"
              "  setTimeout(() => { for (let i = 0; i < 50 && !id.parado; i++) f(); }, 0); return id; };"
              "global.clearInterval = (id) => { if (id) id.parado = true; };"
              "nodo('sec-modo-voz').disparar('click');"
              "setTimeout(() => { global.REC.stop(); nodo('sec-texto').value = 'hola'; }, 1);"
              "setTimeout(() => nodo('sec-escribir').disparar('submit', {preventDefault(){}}), 2);")
    r = ejecutar(GUION, tmp_path, {"POST /api/secretario/mensaje": {"ok": True}, "/api/secretario/turnos": respuesta},
                 previo=previo, accion=accion)
    assert r["errores"] == []
    v = r["valores"]
    assert "habla" in v and "callado" in v
    # Después de callarle, vuelve a escuchar.
    assert "escuchando" in v[v.index("callado"):]


def test_en_modo_voz_lo_que_dices_tras_interrumpirle_se_transcribe(tmp_path):
    """Tras callarle, el micrófono se reabre con él ya hablando (C-0285).
    Cada analizador tiene su serie: la primera escucha calla, el vigía oye
    su eco y luego tu voz, y la escucha de después te oye seguir y callar."""
    respuesta = {"hilo": 1, "turnos": [{"id": 9, "rol": "secretario", "texto": "Una respuesta larga.",
                                        "estado": "listo", "tarjetas": []}]}
    # La primera grabadora se para a mano y sin audio; las de después sí dan audio.
    previo = (PREVIO + VOZ_FALSA +
              "let grabadoras = 0;"
              "global.MediaRecorder = class { constructor(){ this.state = 'inactive'; this.o = {}; this.n = ++grabadoras;"
              "    global.REC = this; }"
              "  addEventListener(ev, f){ this.o[ev] = f; }"
              "  start(){ this.state = 'recording'; registro.valores.push('escuchando'); }"
              "  stop(){ if (this.state === 'inactive') return; this.state = 'inactive';"
              "    if (this.n > 1 && this.o.dataavailable) this.o.dataavailable({ data: { size: 5 } });"
              "    this.o.stop && this.o.stop(); } };"
              "global.Blob = class { constructor(p, o){ this.type = (o || {}).type; } };"
              "global.FormData = class { append(k, v){ this[k] = v; } };"
              "global.speechSynthesis.speak = (u) => { registro.valores.push('habla'); global.HABLANDO = u; };"
              "global.speechSynthesis.cancel = () => { const u = global.HABLANDO; global.HABLANDO = null;"
              "  if (u) { registro.valores.push('callado'); u.onend && u.onend(); } };"
              "const SERIES = [(k) => 0.004, (k) => (k <= 6 ? 0.02 : 0.3), (k) => (k <= 10 ? 0.3 : 0.004)];"
              "let contextos = 0;"
              "global.AudioContext = class { constructor(){ this.serie = SERIES[Math.min(contextos++, 2)]; }"
              "  createAnalyser(){ const serie = this.serie; let k = 0; return { fftSize: 4,"
              "    getFloatTimeDomainData(m){ k += 1; m.fill(serie(k)); } }; }"
              "  createMediaStreamSource(){ return { connect(){} }; } close(){} };")
    accion = ("global.setInterval = (f) => { const id = { parado: false };"
              "  setTimeout(() => { for (let i = 0; i < 50 && !id.parado; i++) f(); }, 0); return id; };"
              "global.clearInterval = (id) => { if (id) id.parado = true; };"
              "nodo('sec-modo-voz').disparar('click');"
              "setTimeout(() => { global.REC.stop(); nodo('sec-texto').value = 'hola'; }, 1);"
              "setTimeout(() => nodo('sec-escribir').disparar('submit', {preventDefault(){}}), 2);")
    r = ejecutar(GUION, tmp_path, {"POST /api/secretario/mensaje": {"ok": True}, "/api/secretario/turnos": respuesta,
                                   "POST /api/voz": {"ok": True, "texto": "y otra cosa"}},
                 previo=previo, accion=accion)
    assert r["errores"] == []
    assert "callado" in r["valores"]
    mandados = [e["cuerpo"]["texto"] for e in r["enviados"] if e["url"] == "/api/secretario/mensaje"]
    assert mandados == ["hola", "y otra cosa"]


def test_en_modo_voz_si_el_navegador_no_avisa_del_final_vuelve_a_escuchar(tmp_path):
    """Chrome con voces de red puede parar una frase sin `onend` (C-0288): un
    tope por frase calla la voz y el modo sigue, sin repetirla."""
    respuesta = {"hilo": 1, "turnos": [{"id": 9, "rol": "secretario", "texto": "Una respuesta larga.",
                                        "estado": "listo", "tarjetas": []}]}
    # Habla y nunca avisa, ni al callarla. El tope (20 caracteres: 2 s + 3 s) va a 3 ms.
    previo = (PREVIO + VOZ_FALSA +
              "global.speechSynthesis.speak = (u) => { registro.valores.push(['dicho', u.text]); };"
              "global.speechSynthesis.cancel = () => { registro.valores.push('cancelada'); };"
              "const _st = global.setTimeout; global.setTimeout = (f, ms) => _st(f, ms === 5000 ? 3 : ms);")
    accion = ("nodo('sec-modo-voz').disparar('click');"
              "setTimeout(() => { global.REC.stop(); nodo('sec-texto').value = 'hola'; }, 1);"
              "setTimeout(() => nodo('sec-escribir').disparar('submit', {preventDefault(){}}), 2);"
              "setTimeout(() => registro.valores.push(['fase', nodo('sec-panel-voz').dataset.fase]), 15);")
    r = ejecutar(GUION, tmp_path, {"POST /api/secretario/mensaje": {"ok": True}, "/api/secretario/turnos": respuesta},
                 previo=previo, accion=accion)
    assert r["errores"] == []
    v = r["valores"]
    i = v.index(["dicho", "Una respuesta larga."])
    assert "cancelada" in v[i:] and "escuchando" in v[i:]
    assert ["fase", "escuchando"] in v
    assert [x for x in v if x == ["dicho", "Una respuesta larga."]] == [["dicho", "Una respuesta larga."]]


def test_el_modo_voz_es_un_boton_y_no_una_casilla_de_opciones(cliente):
    html = cliente.get("/secretario").text
    assert 'id="sec-modo-voz"' in html and 'id="continua"' not in html


def test_fuentes_ensena_lo_que_gasta_cada_trabajo(cliente):
    memoria.apuntar_llamada("triaje", "claude-haiku", 4.2, 0.0312, 1200, 80)
    html = cliente.get("/secretario?p=fuentes").text
    assert "Lo que gasta, últimos 7 días" in html
    assert "<td>triaje</td><td>1</td><td>0</td>" in html and "0,03 USD" in html and "1.280" in html


def test_memoria_lista_las_investigaciones_con_su_modelo_estado_y_coste(cliente):
    """SEC-20: las investigaciones sólo se encontraban como notas o en la
    bitácora; para volver a una había que preguntarle."""
    con = memoria.conectar()
    memoria.apuntar(con, "investigar", nivel="auto", ok=True, resultado="(De la web…",
                    params={"pregunta": "¿Cuánto se conserva?", "id": "0123456789ab", "modelo": "claude-opus-5-5",
                            "estado": "hecha", "segundos": 92, "coste": 0.38})
    con.close()
    html = cliente.get("/secretario?p=memoria").text
    assert "Investigaciones (1)" in html and "¿Cuánto se conserva?" in html
    assert "Opus 5.5" in html and "1 min 32 s" in html and "equivale a 0,38 USD" in html
    assert 'href="/secretario?p=memoria&amp;q=ref.%200123456789ab"' in html


def test_fuentes_dice_que_lo_cortado_a_mitad_no_suma_lo_que_gasto(cliente):
    """SEC-23: lo que corta el vigía se apunta con coste 0 —NULL pediría
    cambiar el esquema (C-0323)— y la tabla parecía decir que no costó nada."""
    memoria.apuntar_llamada("investigar", "claude-opus-5-5", 1200.0, ok=False)
    html = cliente.get("/secretario?p=fuentes").text
    assert "<td>investigar</td><td>1</td><td>1</td>" in html
    assert "no se sabe" in html and "no suma" in html


def test_un_compromiso_se_corrige_a_mano_y_el_aviso_vuelve_a_quedar_pendiente(cliente, monkeypatch):
    monkeypatch.setenv("TZ", "America/Mexico_City")
    con = memoria.conectar()
    cid = memoria.comprometer(con, "Revisar el PR", quien="yo", vence="2026-11-02T15:00:00+00:00",
                              recordar_en="2026-11-02T14:30:00+00:00")
    con.execute("UPDATE compromiso SET recordado = '2026-11-02T14:30:00+00:00' WHERE id = ?", (cid,))
    con.close()
    html = cliente.get("/secretario?p=pendientes").text
    assert f'action="/secretario/compromiso/{cid}/editar"' in html
    r = cliente.post(f"/secretario/compromiso/{cid}/editar", follow_redirects=False,
                     data={"que": "Revisar el PR de pagos", "vence": "2026-11-03T10:00", "recordar": "2026-11-03T09:00",
                           "volver": "/secretario?p=pendientes"})
    assert r.status_code == 303
    con = memoria.conectar()
    c = con.execute("SELECT * FROM compromiso WHERE id = ?", (cid,)).fetchone()
    con.close()
    assert c["que"] == "Revisar el PR de pagos" and c["recordado"] is None
    assert c["vence"].startswith("2026-11-03T16:00") and c["recordar_en"].startswith("2026-11-03T15:00")
    # Sin texto no se guarda.
    r = cliente.post(f"/secretario/compromiso/{cid}/editar", follow_redirects=False, data={"que": " "})
    assert "necesita texto" in unquote(r.headers["location"])


def test_fuentes_ofrece_las_conversaciones_ya_leidas_para_elegirlas(cliente):
    from hub.secretario.piezas import Evento
    con = memoria.conectar()
    memoria.guardar_evento(con, Evento(fuente="hub", id_externo="x1", fecha="2026-11-01T10:00:00+00:00",
                                       texto="hola", conversacion="slots", autor="a"))
    con.close()
    html = cliente.get("/secretario?p=fuentes").text
    assert 'data-conv="slots"' in html


def test_tocar_una_conversacion_la_pone_y_la_quita_de_solo_estas(tmp_path):
    previo = """
      nodo('sec').dataset = { ultimo: '0', pendientes: '0' };
      const campo = Object.assign(nodo('campo'), { value: 'Familia' });
      const chips = ['Trabajo', 'familia'].map((c, i) => Object.assign(nodo('chip' + i), { dataset: { conv: c } }));
      const form = Object.assign(nodo('form'), { querySelector: () => campo });
      const caja = Object.assign(nodo('caja'), { dataset: { para: 'incluir' }, closest: () => form,
                                                 querySelectorAll: () => chips });
      document.querySelectorAll = (sel) => sel === '.vistas' ? [caja] : [];
    """
    accion = """
      registro.valores.push(['antes', nodo('chip1').classList.contains('on'), nodo('chip0').classList.contains('on')]);
      nodo('chip0').disparar('click');
      registro.valores.push(['tras', nodo('campo').value]);
      nodo('chip1').disparar('click');
      registro.valores.push(['quitada', nodo('campo').value]);
    """
    r = ejecutar(GUION, tmp_path, previo=previo, accion=accion)
    assert r["errores"] == []
    v = {x[0]: x[1:] for x in r["valores"] if isinstance(x, list)}
    assert v["antes"] == [True, False]          # «Familia» casa con «familia»
    assert v["tras"] == ["Familia, Trabajo"]
    assert v["quitada"] == ["Trabajo"]


# ── la animación (idea 5 del tablero) ────────────────────────────────────────

def test_pensando_son_tres_puntos_y_a_medias_lleva_cursor(tmp_path):
    turnos = {"hilo": 1, "turnos": [
        {"id": 7, "rol": "secretario", "texto": "", "estado": "escribiendo", "tarjetas": []},
        {"id": 8, "rol": "secretario", "texto": "Déjame mirarlo.", "estado": "escribiendo", "tarjetas": []}]}
    accion = ("nodo('sec-texto').value = 'hola'; nodo('sec-escribir').disparar('submit', {preventDefault(){}});"
              "setTimeout(() => { const c = nodo('sec-chat');"
              " registro.valores.push(['7', c.querySelector('[data-turno=\"7\"]').innerHTML,"
              "   c.querySelector('[data-turno=\"7\"]').className]);"
              " registro.valores.push(['8', c.querySelector('[data-turno=\"8\"]').className]);"
              # Que acabe, o el sondeo no deja terminar al arnés.
              " RESPUESTAS['/api/secretario/turnos'].turnos.forEach(t => { t.estado = 'listo'; }); }, 5);")
    r = ejecutar(GUION, tmp_path, {"POST /api/secretario/mensaje": {"ok": True}, "/api/secretario/turnos": turnos},
                 previo=PREVIO, accion=accion)
    assert r["errores"] == []
    v = {x[0]: x[1:] for x in r["valores"] if isinstance(x, list) and x[0] in ("7", "8")}
    assert 'class="puntos"' in v["7"][0] and "a-medias" not in v["7"][1]
    assert "a-medias" in v["8"][0]


def test_al_escuchar_el_orbe_sigue_tu_voz(tmp_path):
    accion = ("global.setInterval = (f) => { const id = { parado: false };"
              "  setTimeout(() => { for (let i = 0; i < 12 && !id.parado; i++) f(); }, 0); return id; };"
              "global.clearInterval = (id) => { if (id) id.parado = true; };"
              "nodo('sec-modo-voz').disparar('click');")
    previo = (PREVIO + VOZ_FALSA +
              "let n = 0; global.AudioContext = class { createAnalyser(){ return { fftSize: 4,"
              "  getFloatTimeDomainData(m){ n += 1; m.fill(n <= 4 ? 0.004 : 0.1); } }; }"
              "  createMediaStreamSource(){ return { connect(){} }; } close(){} };")
    r = ejecutar(GUION, tmp_path, previo=previo, accion=accion)
    assert r["errores"] == []
    niveles = [float(v) for k, v in r["variables"] if k == "sec-orbe-voz:--nivel"]
    # Callado, quieto; al hablar, al máximo.
    assert niveles[0] == 0 and max(niveles) == 1


def test_el_aviso_tocado_con_la_app_abierta_la_lleva_al_enlace_de_este_hub(tmp_path):
    """El service worker no controla la página y le pide ir al enlace (C-0158).
    Un origen distinto (se suscribió desde otra dirección) se queda en su ruta."""
    previo = ("global.location = { protocol: 'https:', host: 'hub.ejemplo.ts.net', origin: 'https://hub.ejemplo.ts.net',"
              "  href: 'https://hub.ejemplo.ts.net/secretario', assign(u){ registro.valores.push(['ir', u]); } };"
              "navigator.serviceWorker = { addEventListener(ev, f){ global.OYENTE = f; }, startMessages(){} };")
    accion = ("global.OYENTE({ data: { tipo: 'abrir', url: 'http://127.0.0.1:8787/secretario?p=pendientes#solicitud-4' } });"
              "global.OYENTE({ data: { tipo: 'otra', url: '/x' } });")
    r = ejecutar(GUION, tmp_path, previo=PREVIO + previo, accion=accion)
    assert r["errores"] == []
    assert [v for v in r["valores"] if isinstance(v, list) and v[0] == "ir"] == [
        ["ir", "https://hub.ejemplo.ts.net/secretario?p=pendientes#solicitud-4"]]


# ── el modo inglés (C-0159) ──────────────────────────────────────────────────
def test_el_modo_ingles_se_pone_y_se_quita_desde_la_web(cliente):
    assert cliente.post("/api/secretario/ingles", json={"activo": True}).json() == {"ok": True, "activo": True}
    assert 'aria-pressed="true"' in cliente.get("/secretario").text
    assert cliente.post("/api/secretario/ingles", json={"activo": False}).json()["activo"] is False
    assert 'id="sec-modo-ingles" data-activo="" aria-pressed="false"' in cliente.get("/secretario").text


def test_en_modo_ingles_transcribe_y_habla_en_ingles(tmp_path):
    respuesta = {"hilo": 1, "turnos": [{"id": 9, "rol": "secretario", "texto": "Sounds good.",
                                        "estado": "listo", "tarjetas": []}]}
    previo = (PREVIO + VOZ_FALSA + "nodo('sec-modo-ingles').dataset = { activo: '1' };"
              "global.speechSynthesis.getVoices = () => [{ lang: 'es-MX' }, { lang: 'en-US' }];"
              "global.speechSynthesis.speak = (u) => { registro.valores.push(['voz', u.lang, u.voice && u.voice.lang]);"
              "  setTimeout(() => u.onend && u.onend(), 1); };"
              "global.FormData = class { constructor(){ this.d = {}; } append(k, v){ this.d[k] = v; registro.valores.push(['form', k, typeof v === 'string' ? v : 'blob']); } };"
              "global.Blob = class { constructor(){} };")
    r = ejecutar(GUION, tmp_path, {"POST /api/voz": {"ok": True, "texto": "hello"},
                                   "POST /api/secretario/mensaje": {"ok": True}, "/api/secretario/turnos": respuesta},
                 previo=previo,
                 accion="nodo('sec-modo-voz').disparar('click');"
                        "setTimeout(() => { global.REC.o.dataavailable({ data: { size: 3 } }); global.REC.stop(); }, 2);")
    assert r["errores"] == []
    assert ["form", "idioma", "en"] in r["valores"]
    assert ["form", "origen", "secretario"] in r["valores"]   # C-0246: para medir cada voz
    assert ["voz", "en-US", "en-US"] in r["valores"]


def test_una_pestana_abierta_graba_y_habla_en_ingles_si_se_puso_desde_otro_aparato(tmp_path):
    """VOZ-32 (C-0363): puesto el modo inglés desde el teléfono, la pestaña de
    la PC seguía grabando en español y hablando con voz española hasta
    recargar. El sondeo trae `ingles` (C-0422) y con él cambian la siguiente
    grabación y la voz, no sólo el botón."""
    sondeo = {"hilo": 1, "turnos": [], "ingles": True, "vivo": True, "espera": None, "permisos": []}
    contesta = [{"id": 9, "rol": "secretario", "texto": "Sounds good.", "estado": "listo", "tarjetas": []}]
    previo = (PREVIO + VOZ_FALSA + "nodo('sec-chat').dataset = { cargar: '1' };"
              "nodo('sec-modo-ingles').dataset = { activo: '' };"
              "global.speechSynthesis.getVoices = () => [{ lang: 'es-MX' }, { lang: 'en-US' }];"
              "global.speechSynthesis.speak = (u) => { registro.valores.push(['voz', u.lang, u.voice && u.voice.lang]);"
              "  setTimeout(() => u.onend && u.onend(), 1); };"
              "global.FormData = class { append(k, v){ registro.valores.push(['form', k, typeof v === 'string' ? v : 'blob']); } };"
              "global.Blob = class { constructor(){} };")
    accion = ("registro.valores.push(['boton', nodo('sec-modo-ingles').dataset.activo]);"
              "nodo('sec-modo-voz').disparar('click');"
              "setTimeout(() => { RESPUESTAS['/api/secretario/turnos'].turnos = "
              f"{json.dumps(contesta)}; global.REC.o.dataavailable({{ data: {{ size: 3 }} }}); global.REC.stop(); }}, 2);")
    r = ejecutar(GUION, tmp_path, {"POST /api/voz": {"ok": True, "texto": "hello"}, "POST /api/secretario/mensaje": {"ok": True},
                                   "/api/secretario/turnos": sondeo}, previo=previo, accion=accion)
    assert r["errores"] == []
    assert ["boton", "1"] in r["valores"], "lo puso otro aparato: esta pestaña lo sigue sin recargar"
    assert ["form", "idioma", "en"] in r["valores"] and ["form", "idioma", "es"] not in r["valores"]
    assert ["voz", "en-US", "en-US"] in r["valores"]


def test_el_boton_english_lo_cambia_en_el_servidor(tmp_path):
    r = ejecutar(GUION, tmp_path, {"POST /api/secretario/ingles": {"ok": True, "activo": True}},
                 previo=PREVIO + "nodo('sec-modo-ingles').dataset = { activo: '' };",
                 accion="nodo('sec-modo-ingles').disparar('click');"
                        "setTimeout(() => registro.valores.push(['pulsado', nodo('sec-modo-ingles').dataset.activo]), 5);")
    assert r["errores"] == []
    assert {"url": "/api/secretario/ingles", "metodo": "POST", "cuerpo": {"activo": True}} in r["enviados"]
    assert ["pulsado", "1"] in r["valores"]


def test_con_el_modo_ingles_puesto_lo_dice_encima_del_cuadro_y_el_cuadro_en_ingles(cliente):
    """UI-34 (C-0364): sólo lo decía el chip relleno, el aviso salía en inglés y
    el cuadro seguía en español. Mientras dura, lo que haría solo pide permiso
    (C-0159): se ve siempre, no sólo al ponerlo."""
    html = cliente.get("/secretario").text
    assert re.search(r'<div class="en-ingles" id="sec-en-ingles"\s+hidden>', html) and 'placeholder="Escríbele"' in html
    cliente.post("/api/secretario/ingles", json={"activo": True})
    html = cliente.get("/secretario").text
    assert re.search(r'<div class="en-ingles" id="sec-en-ingles"\s*>', html)
    assert "Practicando inglés · no hace nada sin tu permiso" in html and 'placeholder="Write to him"' in html


def test_la_linea_del_ingles_sigue_al_sondeo_y_quitar_lo_quita_en_el_servidor(tmp_path):
    sondeo = {"hilo": None, "turnos": [], "ingles": True, "vivo": True, "espera": None, "permisos": []}
    ver = ("registro.valores.push([%r, nodo('sec-en-ingles').hidden, nodo('sec-texto').placeholder,"
           " nodo('estado-sec').textContent]);")
    accion = (ver % "puesto"
              + "nodo('sec-quitar-ingles').disparar('click');"
              f"setTimeout(() => {{ {ver % 'quitado'} }}, 5);")
    r = ejecutar(GUION, tmp_path, {"/api/secretario/turnos": sondeo,
                                   "POST /api/secretario/ingles": {"ok": True, "activo": False}},
                 previo=PREVIO + "nodo('sec-chat').dataset = { cargar: '1' }; nodo('sec-modo-ingles').dataset = { activo: '' };"
                        "nodo('sec-en-ingles').hidden = true; nodo('sec-texto').placeholder = 'Escríbele';",
                 accion=accion)
    assert r["errores"] == []
    assert _estado(r, "puesto")[:2] == [False, "Write to him"]
    assert {"url": "/api/secretario/ingles", "metodo": "POST", "cuerpo": {"activo": False}} in r["enviados"]
    assert _estado(r, "quitado") == [True, "Escríbele", "modo inglés quitado"]


def test_ponerlo_con_el_boton_no_avisa_en_ingles(tmp_path):
    r = ejecutar(GUION, tmp_path, {"POST /api/secretario/ingles": {"ok": True, "activo": True}},
                 previo=PREVIO + "nodo('sec-modo-ingles').dataset = { activo: '' };",
                 accion="nodo('sec-modo-ingles').disparar('click');"
                        "setTimeout(() => registro.valores.push(['puesto', nodo('sec-en-ingles').hidden,"
                        " nodo('estado-sec').textContent]), 5);")
    assert r["errores"] == []
    assert _estado(r, "puesto") == [False, ""]


# ── la voz que le lee, por aparato (VOZ-24, C-0361; VOZ-22, C-0359) ──────────

# Voces como las da un Chrome de escritorio: las del sistema, locales, y las
# de Google, de red. `VOCES()` las devuelve; un test puede vaciarlas.
VOCES = ("global.LISTA_VOCES = ["
         "  { name: 'Sabina', lang: 'es-MX', voiceURI: 'sabina', localService: true },"
         "  { name: 'Google español', lang: 'es-ES', voiceURI: 'google-es', localService: false },"
         "  { name: 'Raúl', lang: 'es-MX', voiceURI: 'raul', localService: true },"
         "  { name: 'Zira', lang: 'en-US', voiceURI: 'zira', localService: true } ];"
         "global.OYENTES_VOZ = {};"
         "global.speechSynthesis = { getVoices(){ return global.LISTA_VOCES; }, cancel(){},"
         "  addEventListener(ev, f){ (global.OYENTES_VOZ[ev] ||= []).push(f); },"
         "  speak(u){ registro.valores.push(['dicho', u.text, u.voice ? u.voice.voiceURI : null, u.rate, u.lang]);"
         "            setTimeout(() => u.onend && u.onend(), 1); } };"
         "global.SpeechSynthesisUtterance = class { constructor(t){ this.text = t; this.rate = 1; } };")


def _dichos(r):
    return [x[1:] for x in r["valores"] if isinstance(x, list) and x[0] == "dicho"]


def test_ajustes_tiene_su_pestana_de_voz(cliente):
    html = cliente.get("/secretario?p=voz").text
    assert 'href="/secretario?p=voz" class="aqui"' in html
    assert 'id="voz-ajustes" data-voz-ajustes' in html and 'id="voz-es"' in html and 'id="voz-velocidad"' in html


def test_lee_con_la_voz_y_la_velocidad_elegidas_en_este_aparato_aunque_las_voces_lleguen_tarde(tmp_path):
    """Chrome da `getVoices()` vacío la primera vez: se espera a
    `voiceschanged` antes de la primera frase, y entonces suena la elegida
    en este aparato (no la primera de la lista) a su velocidad."""
    respuesta = {"hilo": 1, "turnos": [{"id": 5, "rol": "secretario", "texto": "Tienes dos cosas.",
                                        "estado": "listo", "tarjetas": []}]}
    previo = (PREVIO + VOCES + "global.LLENA = global.LISTA_VOCES; global.LISTA_VOCES = [];"
              "localStorage.setItem('secretario.voz', '1');"
              "localStorage.setItem('secretario.voz.ajustes', JSON.stringify({ es: 'raul', velocidad: 1.2 }));")
    accion = ("nodo('sec-texto').value = 'hola'; nodo('sec-escribir').disparar('submit', {preventDefault(){}});"
              "setTimeout(() => { registro.valores.push('llegan-las-voces'); global.LISTA_VOCES = global.LLENA;"
              "  (global.OYENTES_VOZ.voiceschanged || []).forEach(f => f()); }, 8);")
    r = ejecutar(GUION, tmp_path, {"POST /api/secretario/mensaje": {"ok": True}, "/api/secretario/turnos": respuesta},
                 previo=previo, accion=accion)
    assert r["errores"] == []
    assert _dichos(r) == [["Tienes dos cosas.", "raul", 1.2, "es-MX"]]
    assert r["valores"].index("llegan-las-voces") < r["valores"].index(["dicho", "Tienes dos cosas.", "raul", 1.2, "es-MX"])


_DE_RED_PRIMERO = ("global.LISTA_VOCES = ["
                   "  { name: 'Google español de México', lang: 'es-MX', voiceURI: 'google-mx', localService: false },"
                   "  { name: 'Helena', lang: 'es-ES', voiceURI: 'helena', localService: true } ];")
_SOLO_DE_RED = ("global.LISTA_VOCES = ["
                "  { name: 'Google español de México', lang: 'es-MX', voiceURI: 'google-mx', localService: false } ];")


def _leer_en_voz_alta(tmp_path, voces: str, mas: str = ""):
    """Dos respuestas seguidas con «Leer en voz alta» puesto."""
    respuesta = {"hilo": 1, "turnos": [{"id": 5, "rol": "secretario", "texto": "Tienes dos cosas.",
                                        "estado": "listo", "tarjetas": []}]}
    otra = [{"id": 6, "rol": "secretario", "texto": "Y otra más.", "estado": "listo", "tarjetas": []}]
    accion = ("nodo('sec-texto').value = 'hola'; nodo('sec-escribir').disparar('submit', {preventDefault(){}});"
              "setTimeout(() => { registro.valores.push(['aviso', nodo('estado-sec').textContent]);"
              f"  RESPUESTAS['/api/secretario/turnos'].turnos = {json.dumps(otra)};"
              "  nodo('sec-texto').value = 'y'; nodo('sec-escribir').disparar('submit', {preventDefault(){}}); }, 6);"
              "setTimeout(() => registro.valores.push(['fin', nodo('estado-sec').textContent,"
              "  nodo('sec-sin-voz').hidden]), 14);")
    r = ejecutar(GUION, tmp_path, {"POST /api/secretario/mensaje": {"ok": True}, "/api/secretario/turnos": respuesta},
                 previo=PREVIO + VOCES + voces + "localStorage.setItem('secretario.voz', '1');" + mas, accion=accion)
    assert r["errores"] == []
    return r


def test_lee_con_una_voz_de_este_aparato_aunque_la_de_red_vaya_primero(tmp_path):
    """VOZ-22 (C-0359): se tomaba la primera es-MX sin mirar `localService`,
    y en Chrome de escritorio ésa puede ser una de Google, que manda el texto
    —su agenda, nombres de terceros— a sintetizar fuera."""
    r = _leer_en_voz_alta(tmp_path, _DE_RED_PRIMERO)
    assert [d[1] for d in _dichos(r)] == ["helena", "helena"]


def test_con_solo_voces_de_red_no_lee_lo_dice_una_vez_y_ofrece_elegir(tmp_path):
    r = _leer_en_voz_alta(tmp_path, _SOLO_DE_RED)
    assert _dichos(r) == [], "sin su sí, el texto no sale a una voz de red"
    [aviso] = [x[1] for x in r["valores"] if isinstance(x, list) and x[0] == "aviso"]
    assert "sólo hay voces de red" in aviso and "Ajustes → Voz" in aviso
    [fin] = [x[1:] for x in r["valores"] if isinstance(x, list) and x[0] == "fin"]
    assert fin[1] is False, "el enlace «Elegir voz» se queda a la vista"


def test_una_voz_de_red_elegida_en_este_aparato_si_lee(tmp_path):
    r = _leer_en_voz_alta(tmp_path, _SOLO_DE_RED,
                          "localStorage.setItem('secretario.voz.ajustes', JSON.stringify({ es: 'google-mx' }));")
    assert [d[1] for d in _dichos(r)] == ["google-mx", "google-mx"]


def test_la_pestana_de_voz_dice_que_sin_voz_de_este_aparato_no_lee(tmp_path):
    accion = "registro.valores.push(['suena', nodo('voz-suena-es').textContent]);"
    r = ejecutar(GUION, tmp_path, previo=PREVIO + VOCES + _SOLO_DE_RED + _PAGINA_VOZ, accion=accion)
    assert r["errores"] == []
    [suena] = [x[1] for x in r["valores"] if isinstance(x, list) and x[0] == "suena"]
    assert suena.startswith("No te lee en voz alta: aquí sólo hay voces de red")


def test_probar_sin_voz_de_este_aparato_ni_elegida_no_habla_y_lo_dice(tmp_path):
    """C-0359: sin voz que usar, «Probar» hablaba igual con la voz por omisión
    del navegador, que puede ser de red: justo lo que el chat ya no hace."""
    accion = ("nodo('voz-probar-es').disparar('click');"
              "registro.valores.push(['suena', nodo('voz-suena-es').textContent]);")
    r = ejecutar(GUION, tmp_path, previo=PREVIO + VOCES + _SOLO_DE_RED + _PAGINA_VOZ, accion=accion)
    assert r["errores"] == []
    assert _dichos(r) == [], "sin su sí, ni la prueba sale a una voz de red"
    [suena] = [x[1] for x in r["valores"] if isinstance(x, list) and x[0] == "suena"]
    assert suena.startswith("No lo pruebo: no hay voz de este aparato"), suena


_PAGINA_VOZ = "nodo('voz-ajustes').dataset = { vozAjustes: '' };"


def test_la_pestana_de_voz_lista_las_voces_guarda_lo_elegido_y_lo_prueba(tmp_path):
    accion = ("registro.valores.push(['opciones', nodo('voz-es').innerHTML, nodo('voz-en').innerHTML]);"
              "nodo('voz-es').value = 'raul'; nodo('voz-es').disparar('change');"
              "nodo('voz-velocidad').value = '1.3'; nodo('voz-velocidad').disparar('input');"
              "nodo('voz-probar-es').disparar('click');"
              "setTimeout(() => registro.valores.push(['guardado', localStorage.getItem('secretario.voz.ajustes'),"
              "  nodo('voz-velocidad-valor').textContent, nodo('voz-suena-es').textContent]), 5);")
    r = ejecutar(GUION, tmp_path, previo=PREVIO + VOCES + _PAGINA_VOZ, accion=accion)
    assert r["errores"] == []
    [opciones] = [x[1:] for x in r["valores"] if isinstance(x, list) and x[0] == "opciones"]
    assert 'value="sabina">Sabina · de este aparato</option>' in opciones[0]
    assert "Google español · de red: el texto sale a internet" in opciones[0]
    assert "Zira" not in opciones[0] and "Zira · de este aparato" in opciones[1]
    [guardado] = [x[1:] for x in r["valores"] if isinstance(x, list) and x[0] == "guardado"]
    assert json.loads(guardado[0]) == {"es": "raul", "en": "", "velocidad": 1.3}
    assert guardado[1] == "1,3" and guardado[2] == "Suena: Raúl, de este aparato."
    assert _dichos(r) == [["Hola, así te leo las respuestas.", "raul", 1.3, "es-MX"]]


# ── el secretario en todas las pantallas (C-0160) ────────────────────────────

def _en_todo_el_hub(activo=True):
    con = memoria.conectar()
    con.close()
    (memoria.carpeta() / "secretario.yml").write_text(f"en_todo_el_hub: {'true' if activo else 'false'}\n")


def test_con_el_secretario_en_todo_el_hub_las_pantallas_lo_llevan_y_no_al_asistente(cliente):
    _en_todo_el_hub()
    html = cliente.get("/").text
    assert 'id="secretario-panel"' in html and 'data-cargar="1"' in html
    assert '<aside id="asistente">' not in html and "/static/asistente.js" not in html
    assert "/static/chat-secretario.js" in html


def test_en_su_propia_pantalla_no_se_pinta_el_panel(cliente):
    _en_todo_el_hub()
    html = cliente.get("/secretario").text
    assert 'id="secretario-panel"' not in html and 'id="sec-chat"' in html


def test_sin_pedirlo_sigue_el_asistente_como_siempre(cliente):
    _en_todo_el_hub(False)
    assert 'id="secretario-panel"' not in cliente.get("/").text


# ── ponerlo abajo con un botón (C-0239, decisión 403) ────────────────────────

def _late():
    con = memoria.conectar()
    memoria.poner(con, "latido", memoria.ahora())
    con.close()


def _en_todo_guardado():
    from hub.secretario import conversacion
    con = memoria.conectar()
    try:
        return memoria.leer(con, conversacion.CLAVE_EN_TODO)
    finally:
        con.close()


def test_ponerlo_con_el_boton_lo_lleva_a_todas_las_pantallas_sin_tocar_el_yml(cliente):
    """Un usuario de 0.5.x seguía viendo al asistente abajo: el ajuste sólo
    estaba en el CHANGELOG, como una línea del yml."""
    _late()
    yml = memoria.carpeta() / "secretario.yml"
    yml.write_text("# mío\ncontexto: |\n  trabajo en remoto\n", encoding="utf-8")
    html = cliente.get("/secretario?p=personaje").text
    assert 'action="/secretario/en-todo-el-hub"' in html and "Ponerlo en todas las pantallas" in html
    r = cliente.post("/secretario/en-todo-el-hub", data={"si": "1"}, follow_redirects=False)
    assert r.status_code == 303 and "fugaz=1" in r.headers["location"]
    assert 'id="secretario-panel"' in cliente.get("/").text
    assert yml.read_text(encoding="utf-8") == "# mío\ncontexto: |\n  trabajo en remoto\n"


def test_quitarlo_gana_a_un_yml_que_lo_pide(cliente):
    """Borrar la clave devolvería la palabra al yml y «Quitarlo» no haría nada."""
    _en_todo_el_hub()
    assert "Quitarlo de abajo" in cliente.get("/secretario?p=personaje").text
    cliente.post("/secretario/en-todo-el-hub", data={"si": "0"}, follow_redirects=False)
    assert _en_todo_guardado() is False
    assert 'id="secretario-panel"' not in cliente.get("/").text


def test_sin_pulsar_nada_manda_el_yml_como_antes(cliente):
    _en_todo_el_hub()
    assert _en_todo_guardado() is None
    assert 'id="secretario-panel"' in cliente.get("/").text


def test_si_no_se_puede_leer_su_memoria_vale_lo_ultimo_leido_y_no_vuelve_el_asistente(cliente, monkeypatch):
    """Quien lo puso con el botón no tiene nada en el yml: con un `database is
    locked`, decidir por el yml le devolvía al asistente."""
    import sqlite3
    from hub import api
    from hub.secretario import conversacion
    con = memoria.conectar()
    conversacion.poner_en_todo_el_hub(con, True)
    con.close()
    assert api.secretario_en_todo_el_hub() is True

    def ilegible(*a, **k):
        raise sqlite3.OperationalError("database is locked")
    monkeypatch.setattr(memoria, "leer_sin_abrir", ilegible)
    assert api.secretario_en_todo_el_hub() is True
    assert '<aside id="asistente">' not in cliente.get("/").text


def test_si_no_se_puede_leer_y_nunca_se_leyo_decide_el_yml(cliente, monkeypatch):
    import sqlite3
    from hub import api
    _en_todo_el_hub()
    monkeypatch.setattr(api, "_EN_TODO_LEIDO", {})

    def ilegible(*a, **k):
        raise sqlite3.OperationalError("database is locked")
    monkeypatch.setattr(memoria, "leer_sin_abrir", ilegible)
    assert api.secretario_en_todo_el_hub() is True


@pytest.mark.parametrize("estado, dice", [
    ({"activo": "inactive", "habilitado": False}, "Primero enciéndelo, con el botón de arriba"),
    ({"activo": "active", "habilitado": True}, "arriba dice por qué no lo está"),
    (None, "arriba dice por qué no lo está"),
])
def test_sin_latido_no_ofrece_ponerlo_ni_lo_pone(cliente, monkeypatch, estado, dice):
    """Con el asistente retirado y él parado, abajo no contestaría nadie. Y
    «enciéndelo con el botón de arriba» sólo cuando arriba hay ese botón."""
    from hub import salud
    monkeypatch.setattr(salud, "estado_servicio", lambda nombre: estado)
    memoria.conectar().close()
    html = cliente.get("/secretario?p=personaje").text
    assert "Ponerlo en todas las pantallas" not in html and dice in html
    r = cliente.post("/secretario/en-todo-el-hub", data={"si": "1"}, follow_redirects=False)
    assert "fugaz=1" not in r.headers["location"] and "no está en marcha" in unquote(r.headers["location"])
    assert _en_todo_guardado() is None


def test_ponerlo_pide_mismo_origen(cliente):
    _late()
    r = cliente.post("/secretario/en-todo-el-hub", data={"si": "1"}, headers={"Origin": "https://malo.example"},
                     follow_redirects=False)
    assert r.status_code == 403 and _en_todo_guardado() is None


def test_la_guia_de_arranque_manda_a_quien_esta_abajo(cliente):
    """Con él abajo, la portada seguía diciendo «pídeselo al asistente»; él
    también da de alta un proyecto que ya existe (`anexar_proyecto`)."""
    html = cliente.get("/").text
    assert "Declara un proyecto" in html and "pídeselo al secretario" not in html
    _en_todo_el_hub()
    html = cliente.get("/").text
    assert "pídeselo al secretario, abajo a la" in html and "pídeselo al asistente" not in html
    con = memoria.conectar()
    memoria.poner(con, "nombre", "Rita")
    con.close()
    assert "pídeselo a Rita, abajo a la" in cliente.get("/").text


def test_sin_ponerlo_su_pantalla_no_dice_que_te_sigue_por_todas(cliente):
    _late()
    html = cliente.get("/secretario?p=personaje").text
    assert "Te sigue por todas las pantallas" not in html
    _en_todo_el_hub()
    assert "Te sigue por todas las pantallas" in cliente.get("/secretario?p=personaje").text


def test_el_panel_carga_la_conversacion_y_dice_desde_que_pantalla_y_ventana_le_hablas(tmp_path):
    turnos = {"hilo": 1, "turnos": [{"id": 3, "rol": "secretario", "texto": "Hola.", "estado": "listo", "tarjetas": []}]}
    previo = (PREVIO + "nodo('sec-chat').dataset = { ultimo: '0', cargar: '1' };"
              "global.location = { pathname: '/trabajo', href: '', protocol: 'http:', host: 'localhost' };"
              "document.title = 'Trabajo'; document.body.dataset = { enfoque: 'hub:2' };")
    accion = ("setTimeout(() => window.HubSecretario.preguntar('¿qué miro?'), 2);"
              "setTimeout(() => registro.valores.push(['pintado', !!nodo('sec-chat').querySelector('[data-turno=\"3\"]')]), 6);")
    r = ejecutar(GUION, tmp_path, {"POST /api/secretario/mensaje": {"ok": True}, "/api/secretario/turnos": turnos},
                 previo=previo, accion=accion)
    assert r["errores"] == []
    assert ["pintado", True] in r["valores"]
    assert {"url": "/api/secretario/mensaje", "metodo": "POST",
            "cuerpo": {"texto": "¿qué miro?", "voz": False, "pantalla": "/trabajo · Trabajo · ventana hub:2",
                       "enfoque": "hub:2"}} in r["enviados"]


def test_al_cargar_el_panel_no_lee_en_voz_alta_lo_ya_contestado(tmp_path):
    """Con «leer en voz alta» marcado, cada carga de página leía la última respuesta."""
    turnos = {"hilo": 1, "turnos": [{"id": 3, "rol": "secretario", "texto": "Respuesta vieja.", "estado": "listo",
                                     "tarjetas": []}]}
    previo = (PREVIO + VOZ_FALSA + "nodo('sec-chat').dataset = { ultimo: '0', cargar: '1' };"
              "nodo('sec-en-voz').checked = true; localStorage.setItem('secretario.voz', '1');")
    r = ejecutar(GUION, tmp_path, {"/api/secretario/turnos": turnos}, previo=previo, accion="")
    assert r["errores"] == []
    assert not [v for v in r["valores"] if isinstance(v, list) and v[0] == "dicho"]


def test_conversacion_nueva_desde_el_panel_vuelve_con_su_query_y_sin_el_aviso_de_antes(cliente):
    """C-0230: en /trabajo?slot=7 volvía a /trabajo, sin el slot, y la terminal
    se conectaba a otra cosa. El aviso de la acción anterior no se arrastra."""
    _en_todo_el_hub()
    html = cliente.get("/trabajo?slot=7&aviso=Hecho&fugaz=1").text
    i = html.index('id="sec-nueva"')
    assert 'name="volver" value="/trabajo?slot=7"' in html[i:i + 600]


def test_conversacion_nueva_desde_el_panel_vuelve_a_su_pantalla_y_nunca_fuera(cliente):
    r = cliente.post("/secretario/nuevo", data={"volver": "/trabajo"}, follow_redirects=False)
    assert r.headers["location"].startswith("/trabajo")
    r = cliente.post("/secretario/nuevo", data={"volver": "//malo.example"}, follow_redirects=False)
    assert r.headers["location"].startswith("/secretario")


# ── el asistente retirado en su hub (C-0164) ─────────────────────────────────

@pytest.mark.parametrize("ruta", ["abrir", "enviar", "retomar", "compactar", "limpiar", "responder"])
def test_con_el_secretario_en_todo_el_hub_el_asistente_no_se_arranca_ni_se_le_escribe(cliente, monkeypatch, ruta):
    from hub import asistente
    _en_todo_el_hub()
    monkeypatch.setattr(asistente, "asegurar_sesion", lambda *a, **k: pytest.fail("no debía arrancarse"))
    r = cliente.post(f"/api/asistente/{ruta}", json={"texto": "hola", "sesion": "x"})
    assert r.status_code == 410 and "secretario" in r.json()["error"]


# ── tras actuar sin recargar (C-0181, resto de C-0167) ───────────────────────
#
# `sin-recarga.js` cambia sólo las regiones de la página y avisa con
# `hub:repintado`. Lo que `secretario.js` leyó al cargar se quedaba viejo: el
# número del icono hasta la próxima carga, el filtro hasta la próxima tecla.

SOLO_APP = script_estatico("secretario.js")

NUMERO = ("navigator.setAppBadge = (n) => { registro.valores.push(['numero', n]); return Promise.resolve(); };"
          "navigator.clearAppBadge = () => { registro.valores.push(['numero', 0]); return Promise.resolve(); };"
          # El número va en la región de la barra, que es lo que se repinta.
          "globalThis.BARRA = Object.assign(elemento('barra'), { dataset: { region: 'sec-nav', pendientes: '2' } });"
          "document.querySelector = (sel) => sel === '[data-pendientes]' ? BARRA : elemento('x');")


def _repintado(regiones):
    return ("(DOC_OYENTES['hub:repintado'] || []).forEach(f => f({ detail: { regiones: %s } }));"
            % json.dumps(regiones))


def test_el_numero_del_icono_baja_al_aprobar_sin_recargar(tmp_path):
    accion = ("BARRA = Object.assign(elemento('barra-nueva'), { dataset: { region: 'sec-nav', pendientes: '0' } });"
              + _repintado(["sec-nav", "pendientes"]))
    r = ejecutar(SOLO_APP, tmp_path, previo=NUMERO, accion=accion)
    assert r["errores"] == []
    numeros = [v[1] for v in r["valores"] if isinstance(v, list) and v[0] == "numero"]
    assert numeros == [2, 0], numeros


def test_la_pagina_lleva_el_numero_en_la_region_que_se_repinta(cliente):
    con = memoria.conectar()
    con.execute("INSERT INTO solicitud (accion, params, creada) VALUES ('anotar', '{\"texto\": \"x\"}', ?)",
                (memoria.ahora(),))
    con.commit()
    con.close()
    html = cliente.get("/secretario?p=pendientes").text
    [barra] = re.findall(r'<nav[^>]*data-region="sec-nav"[^>]*>', html)
    assert 'data-pendientes="1"' in barra
    assert html.count("data-pendientes=") == 1


NOTAS = ("globalThis.nota = (id, texto) => { const n = elemento(id); n.hidden = false;"
         "  n.querySelector('textarea').value = texto; n.querySelector('.tenue').textContent = 'a mano · hoy';"
         "  return n; };"
         "globalThis.LISTA = [nota('n1', 'comprar leche'), nota('n2', 'llamar al banco')];"
         "nodo('notas').querySelectorAll = (sel) => sel === '.nota' ? LISTA : [];")


def test_el_filtro_de_notas_sigue_puesto_tras_guardar_sin_recargar(tmp_path):
    accion = ("nodo('filtro-notas').value = 'leche'; nodo('filtro-notas').disparar('input');"
              "registro.valores.push(['antes', LISTA.filter(n => n.hidden).map(n => n.id)]);"
              # La región de notas llega nueva: ninguna escondida.
              "LISTA = [nota('n3', 'comprar leche'), nota('n4', 'llamar al banco'), nota('n5', 'pagar la luz')];"
              + _repintado(["notas"])
              + "registro.valores.push(['despues', LISTA.filter(n => n.hidden).map(n => n.id)]);")
    r = ejecutar(SOLO_APP, tmp_path, previo=NOTAS, accion=accion)
    assert r["errores"] == []
    assert ["antes", ["n2"]] in r["valores"]
    assert ["despues", ["n4", "n5"]] in r["valores"]


def test_sin_filtro_el_repintado_no_esconde_nada(tmp_path):
    accion = _repintado(["notas"]) + "registro.valores.push(['despues', LISTA.filter(n => n.hidden).map(n => n.id)]);"
    r = ejecutar(SOLO_APP, tmp_path, previo=NOTAS, accion=accion)
    assert ["despues", []] in r["valores"]


def test_el_filtro_de_notas_no_distingue_tildes_como_la_busqueda_en_todas(tmp_path):
    """Lo que trae la búsqueda del servidor (sin tildes ni mayúsculas) no lo
    puede esconder el filtro del navegador al repintar tras guardar."""
    accion = ("LISTA = [nota('n1', 'El proveedor de Cartón'), nota('n2', 'llamar al banco')];"
              "nodo('filtro-notas').value = 'carton'; nodo('filtro-notas').disparar('input');"
              "registro.valores.push(['escondidas', LISTA.filter(n => n.hidden).map(n => n.id)]);")
    r = ejecutar(SOLO_APP, tmp_path, previo=NOTAS, accion=accion)
    assert r["errores"] == []
    assert ["escondidas", ["n2"]] in r["valores"]


def _ciento_veinte_notas():
    con = memoria.conectar()
    memoria.anotar(con, "El proveedor de cartón cobra por adelantado", tema="proveedores")
    for i in range(2, 121):
        memoria.anotar(con, f"nota de relleno {i}")
    con.commit()
    con.close()


def test_una_nota_vieja_se_encuentra_buscando_en_todas(cliente):
    """SEC-35: la página carga las 80 últimas y el filtro era del navegador:
    la nota 1 de 120 no se podía ni encontrar para corregirla. Buscar va al
    servidor, sobre todas, y dice cuántas hay."""
    _ciento_veinte_notas()
    s = api.secretario("memoria")
    assert len(s["notas"]) == 80 and s["notas_total"] == 120
    assert all("cartón" not in n["texto"] for n in s["notas"])
    s = api.secretario("memoria", notas_q="CARTÓN")
    assert [n["texto"] for n in s["notas"]] == ["El proveedor de cartón cobra por adelantado"]
    assert s["notas_halladas"] == 1 and s["notas_q"] == "CARTÓN"
    html = cliente.get("/secretario", params={"p": "memoria", "q": "cartón"}).text
    assert "El proveedor de cartón" in html and 'name="q"' in html
    assert "de 120" in cliente.get("/secretario?p=memoria").text


def test_guardar_una_nota_buscada_vuelve_a_la_misma_busqueda(cliente):
    _ciento_veinte_notas()
    [n] = api.secretario("memoria", notas_q="cartón")["notas"]
    r = cliente.post(f"/secretario/nota/{n['id']}", headers=MISMO_ORIGEN, follow_redirects=False,
                     data={"texto": "El proveedor de cartón ya no cobra por adelantado",
                           "volver": "/secretario?p=memoria&q=cart%C3%B3n"})
    assert r.status_code == 303 and r.headers["location"].startswith("/secretario?p=memoria&q=cart%C3%B3n")
    # Fuera de /secretario no se vuelve.
    r = cliente.post(f"/secretario/nota/{n['id']}", headers=MISMO_ORIGEN, follow_redirects=False,
                     data={"texto": "otra vez", "volver": "https://malo.example/"})
    assert r.headers["location"].startswith("/secretario?p=memoria")


def test_las_hojas_del_panel_van_en_la_cabeza_y_no_en_el_cuerpo(cliente):
    """En el cuerpo, si la hoja tardaba, el `<aside>` del panel entraba sin
    estilo como una columna más del `body` en flex y estrechaba la página
    hasta que llegaba (lo apuntó C-0167). En `<head>` se espera a ella."""
    _en_todo_el_hub()
    html = cliente.get("/maquina").text
    cabeza, cuerpo = html.split("</head>", 1)
    for hoja in ("/static/chat-secretario.css", "/static/avatar-secretario.css"):
        assert hoja in cabeza, f"{hoja} no está en <head>"
        assert hoja not in cuerpo, f"{hoja} sigue en el cuerpo"
    assert 'id="secretario-panel"' in cuerpo


def test_en_su_pantalla_las_hojas_van_una_sola_vez(cliente):
    _en_todo_el_hub()
    html = cliente.get("/secretario").text
    assert html.count('href="/static/chat-secretario.css"') == 1
    assert html.count('href="/static/avatar-secretario.css"') == 1


def test_sin_el_secretario_en_todo_el_hub_no_se_piden_sus_hojas(cliente):
    _en_todo_el_hub(False)
    assert "/static/chat-secretario.css" not in cliente.get("/maquina").text


def test_tras_un_repintado_el_formulario_se_engancha_una_sola_vez(tmp_path):
    """C-0229: Disparadores guarda sin recargar y sus nodos llegan nuevos y sin
    oyentes; volver a enganchar en cada `hub:repintado` no puede duplicar los
    de un nodo que no cambió. Y al enganchar, `pintado` releva al CSS."""
    previo = ("nodo('sec').dataset = { ultimo: '0', pendientes: '0' };"
              "const f = nodo('disparador-nuevo'); nodo('disp-clase').value = 'evento'; nodo('disp-que').value = 'pide';"
              "f.querySelectorAll = () => [];")
    accion = ("(DOC_OYENTES['hub:repintado'] || []).forEach(fn => fn({}));"
              "(DOC_OYENTES['hub:repintado'] || []).forEach(fn => fn({}));"
              "registro.valores.push(['oyentes', (nodo('disp-clase')._oyentes.change || []).length,"
              " nodo('disparador-nuevo').classList.contains('pintado')]);")
    r = ejecutar(GUION, tmp_path, previo=previo, accion=accion)
    assert r["errores"] == []
    assert ["oyentes", 1, True] in r["valores"]


def test_quitar_de_una_lista_vieja_no_quita_otro_aparato_que_tomo_su_numero(cliente):
    """C-0232 (revisor): SQLite reutiliza el `id` de la última fila borrada. Con
    la huella del aparato, el «Quitar» de una página vieja no cae en otro."""
    origen = {"Origin": "http://127.0.0.1:8787"}
    alta = {"keys": {"p256dh": "P", "auth": "A"}, "motivo": "activar"}
    sid = cliente.post("/api/secretario/push/alta", headers=origen,
                       json={**alta, "endpoint": "https://push.ejemplo.org/a", "aparato": "Viejo"}).json()["id"]
    huella_vieja = memoria.huella_de("https://push.ejemplo.org/a")
    assert cliente.post(f"/secretario/aparato/{sid}/quitar", headers=origen,
                        data={"huella": huella_vieja}, follow_redirects=False).status_code == 303
    otro = cliente.post("/api/secretario/push/alta", headers=origen,
                        json={**alta, "endpoint": "https://push.ejemplo.org/b", "aparato": "Nuevo"}).json()["id"]
    r = cliente.post(f"/secretario/aparato/{otro}/quitar", headers=origen,
                     data={"huella": huella_vieja}, follow_redirects=False)
    assert "no%20se%20quit" in r.headers["location"]
    con = memoria.conectar()
    try:
        assert [s["aparato"] for s in memoria.suscripciones(con)] == ["Nuevo"]
    finally:
        con.close()


# ── C-0231: lo que se ve, con palabras y en el teléfono ──────────────────────

def _plegado_de_conversaciones(html: str) -> str:
    m = re.search(r'<details class="bloque plegado"[^>]*>\s*<summary>Conversaciones anteriores.*?</details>', html, re.S)
    assert m, "no está el plegado de las conversaciones anteriores"
    return m.group(0)


def test_las_conversaciones_anteriores_salen_tambien_en_memoria_donde_las_ve_el_telefono(cliente):
    """Al lado de la conversación sólo se ven desde 1180 px: en el teléfono y
    en la tablet no salían en ningún sitio (C-0231). En Memoria, lo mismo."""
    con = memoria.conectar()
    con.execute("INSERT INTO hilo (abierto, ultimo, cerrado, titulo, resumen) VALUES (?, ?, ?, ?, ?)",
                (memoria.ahora(), memoria.ahora(), memoria.ahora(), "El presupuesto de la obra",
                 "Quedó en pedir otra cotización."))
    con.close()

    en_memoria = _plegado_de_conversaciones(cliente.get("/secretario?p=memoria").text)

    assert "Conversaciones anteriores (1)" in en_memoria
    assert "El presupuesto de la obra" in en_memoria and "Quedó en pedir otra cotización." in en_memoria
    assert en_memoria == _plegado_de_conversaciones(cliente.get("/secretario").text), "lo mismo que al lado"


def test_un_permiso_dice_sus_datos_con_palabras_y_no_con_los_nombres_del_programa(cliente):
    con = memoria.conectar()
    sids = [con.execute("INSERT INTO solicitud (accion, params, creada) VALUES (?, ?, ?)",
                        (accion, json.dumps(params), memoria.ahora())).lastrowid
            for accion, params in (("agendar", {"titulo": "Dentista", "minutos_aviso": 30, "sala_virtual": "no"}),
                                   ("resumen_del_dia", {"en_chat": True}))]
    con.close()

    html = cliente.get("/secretario?p=pendientes").text
    agendar, resumen = (html.split(f'id="solicitud-{sid}"')[1].split('<div class="acciones">')[0] for sid in sids)

    assert "título: Dentista" in agendar and "aviso, minutos antes: 30" in agendar
    assert "sala virtual: no" in agendar, "lo que no tiene rótulo, con espacios"
    assert "en el chat: sí" in resumen, "un sí o un no, no el True de Python"
    for crudo in ("titulo:", "minutos_aviso", "sala_virtual", "en_chat", "True"):
        assert crudo not in agendar + resumen


def test_la_bitacora_dice_el_nombre_de_la_accion_y_no_su_id(cliente):
    con = memoria.conectar()
    memoria.apuntar(con, "tele_encender", nivel="auto", resultado="encendida")
    memoria.apuntar(con, "resumen_sesion", nivel="auto", resultado="resumida")
    con.close()

    bitacora = cliente.get("/secretario?p=confianza").text.split("Bitácora")[1]

    assert "<strong>Encender la tele</strong>" in bitacora and "tele_encender" not in bitacora
    assert "resumen_sesion" not in bitacora, "lo que no es una acción, al menos sin guiones bajos"


def test_confianza_dice_el_riesgo_con_palabras(cliente):
    html = cliente.get("/secretario?p=confianza").text.split('data-region="confianza"')[1].split("Bitácora")[0]
    assert "riesgo:" not in html
    for riesgo in ("lectura", "irreversible"):    # tele_estado y escribir_en_sesion
        assert piezas.ROTULOS_RIESGO[riesgo] in html


def test_confianza_sigue_ensenando_lo_que_no_esta_configurado_y_donde_se_configura(cliente, monkeypatch):
    """SEC-08: lo que no se le ofrece al modelo no desaparece para el dueño:
    sale «sin configurar», con dónde se hace, y su nivel se puede cambiar."""
    class SinConfigurar(piezas.Accion):
        id, nombre, resumen = "sin_configurar", "Algo sin configurar", "Hace algo."
        como_configurar = "Se configura en su sitio."
        disponible = staticmethod(lambda: False)

    class Configurada(piezas.Accion):
        id, nombre, resumen = "configurada", "Algo listo", "Hace otra cosa."
        como_configurar = "Esto no debería salir."
        disponible = staticmethod(lambda: True)

    monkeypatch.setattr(piezas, "acciones", lambda: {"sin_configurar": SinConfigurar(), "configurada": Configurada()})
    html = cliente.get("/secretario?p=confianza").text.split('data-region="confianza"')[1].split("Bitácora")[0]
    sin, lista = html.split("<strong>Algo listo</strong>")
    assert "Algo sin configurar" in sin and "sin configurar</span>" in sin and "Se configura en su sitio." in sin
    assert 'aria-label="Nivel de Algo sin configurar"' in sin
    assert "sin configurar</span>" not in lista and "Esto no debería salir." not in lista


def test_cada_riesgo_tiene_su_rotulo_y_no_es_su_valor_interno():
    assert set(piezas.ROTULOS_RIESGO) == set(piezas.RIESGOS)
    assert all(r != clave for clave, r in piezas.ROTULOS_RIESGO.items())


def test_la_galeria_del_personaje_no_ensena_identificadores(cliente):
    galeria = cliente.get("/secretario?p=personaje").text.split("Elegir personaje")[1]
    assert "<code>" not in galeria


def test_descartar_un_compromiso_pregunta_antes_con_su_texto(cliente):
    """Descartar no tiene vuelta atrás y se hacía de un toque, al lado de
    «Hecho» (C-0231). «Hecho» sigue sin preguntar."""
    con = memoria.conectar()
    cid = memoria.comprometer(con, "Mandar el reporte", quien="yo")
    con.close()

    html = cliente.get("/secretario?p=pendientes").text

    def formulario(estado: str) -> str:
        m = re.search(rf'<form method="post" action="/secretario/compromiso/{cid}"([^>]*)>\s*'
                      rf'<input type="hidden" name="estado" value="{estado}">', html)
        assert m, f"no está el formulario de «{estado}»"
        return m.group(1)

    descartar = formulario("descartado")
    assert 'data-confirmar-titulo="Descartar el compromiso"' in descartar
    assert 'data-confirmar-ok="Descartar"' in descartar
    pregunta = re.search(r'data-confirmar="([^"]*)"', descartar).group(1)
    assert "Mandar el reporte" in pregunta and "No se puede deshacer" in pregunta
    assert "data-confirmar" not in formulario("hecho")


def test_una_lista_en_un_permiso_deja_ver_donde_acaba_cada_elemento():
    """Revisor de C-0231: unidos con comas, «b, c.pdf» parecía dos archivos."""
    from hub import api
    assert api._valor_legible(["a.pdf", "b, c.pdf"]) == "«a.pdf» · «b, c.pdf»"
    assert api._valor_legible([]) == "(ninguno)"
    assert api._valor_legible(None) == "—"


def test_confianza_agrupa_lo_que_no_supo_y_cuenta_los_repetidos(cliente):
    con = memoria.conectar()
    for que in ("Cancelar una cita", "cancelar  una cita", "mover un archivo"):
        memoria.apuntar(con, "hueco", params={"que": que}, resultado="sin herramienta")
    huecos = api.secretario_huecos(con)
    con.close()

    assert [(h["que"], h["veces"]) for h in huecos] == [("Cancelar una cita", 2), ("mover un archivo", 1)]
    html = cliente.get("/secretario?p=confianza").text.split('data-region="huecos"')[1].split("Bitácora")[0]
    assert "Lo que le pediste y no supo" in html and "2 veces" in html and "1 vez " in html


def test_confianza_sin_huecos_lo_dice_con_texto_llano(cliente):
    html = cliente.get("/secretario?p=confianza").text.split('data-region="huecos"')[1].split("Bitácora")[0]
    assert "Nada todavía" in html


def test_confianza_ensena_los_no_puedo_que_quedaron_sin_clasificar(cliente):
    """C-0324: los que apunta la red de `contestar` no traen qué faltaba. Se
    cuentan aparte: mezclados con los demás no dirían nada, y sin verse la
    red no serviría."""
    con = memoria.conectar()
    memoria.apuntar(con, "hueco", params={"que": "mover un archivo"}, resultado="sin herramienta")
    for turno in (7, 9):
        memoria.apuntar(con, "hueco", params={"turno": turno}, resultado="sin clasificar")
    con.execute("UPDATE bitacora SET cuando = '2026-11-11T05:30:00+00:00' WHERE params LIKE '%9%'")
    huecos, sueltos = api.secretario_huecos(con), api.secretario_huecos_sin_clasificar(con)
    con.close()

    assert [h["que"] for h in huecos] == ["mover un archivo"]
    assert sueltos["veces"] == 2 and sueltos["ultimo"]
    html = cliente.get("/secretario?p=confianza").text.split('data-region="huecos"')[1].split("Bitácora")[0]
    assert "2 veces" in html and "sin apuntar qué le faltaba" in html


def test_confianza_sin_no_puedo_sueltos_no_dice_nada_de_ellos(cliente):
    con = memoria.conectar()
    memoria.apuntar(con, "hueco", params={"que": "mover un archivo"}, resultado="sin herramienta")
    assert api.secretario_huecos_sin_clasificar(con) == {"veces": 0, "ultimo": None}
    con.close()
    html = cliente.get("/secretario?p=confianza").text.split('data-region="huecos"')[1].split("Bitácora")[0]
    assert "sin apuntar qué le faltaba" not in html


# ── el recorrido de cada hueco (C-0252) ──────────────────────────────────────

def _hueco_con_idea(que, estado="nueva", ref=""):
    """Un hueco apuntado y, en el hub.db real de la suite, su idea con la marca."""
    from hub import config, db, ideas
    m = memoria.conectar()
    memoria.apuntar(m, "hueco", params={"que": que}, resultado="sin herramienta")
    m.close()
    h = db.conectar(config.DB_PATH)
    db.inicializar(h)
    i = ideas.apuntar(h, "poder " + que, origen="secretario", hueco=que)
    if estado == "tomada":
        ideas.tomar(h, i, ref)
    h.commit()
    h.close()
    return i


def _huecos():
    m = memoria.conectar()
    try:
        return {h["que"]: h for h in api.secretario_huecos(m)}
    finally:
        m.close()


def test_un_hueco_sin_idea_no_dice_nada_de_mejora(cliente):
    m = memoria.conectar()
    memoria.apuntar(m, "hueco", params={"que": "mover un archivo"}, resultado="sin herramienta")
    m.close()

    assert _huecos()["mover un archivo"]["mejora"] is None
    html = cliente.get("/secretario?p=confianza").text.split('data-region="huecos"')[1].split("Bitácora")[0]
    assert "apuntado como mejora" not in html


def test_un_hueco_con_idea_nueva_dice_que_espera_en_el_tablero(cliente):
    i = _hueco_con_idea("cancelar una cita")

    mejora = _huecos()["cancelar una cita"]["mejora"]
    assert mejora["idea"] == i and mejora["estado_idea"] == "nueva" and mejora["ficha"] is None
    html = cliente.get("/secretario?p=confianza").text.split('data-region="huecos"')[1].split("Bitácora")[0]
    assert "apuntado como mejora · en el tablero" in html


def test_un_hueco_con_idea_tomada_enseña_su_ficha_y_su_estado(cliente, tmp_path):
    import yaml
    fichas = tmp_path / "cambios"
    fichas.mkdir()
    cab = {"id": "C-0300", "titulo": "x", "estado": "en-curso", "quien": "claude"}
    (fichas / "C-0300-x.md").write_text("---\n" + yaml.safe_dump(cab) + "---\n", encoding="utf-8")
    (memoria.carpeta() / "secretario.yml").write_text(f"parte_fichas: {fichas}\n", encoding="utf-8")
    _hueco_con_idea("cancelar una cita", "tomada", "C-0300")

    mejora = _huecos()["cancelar una cita"]["mejora"]
    assert mejora["ficha"] == {"id": "C-0300", "estado": "en-curso"}
    html = cliente.get("/secretario?p=confianza").text.split('data-region="huecos"')[1].split("Bitácora")[0]
    assert "apuntado como mejora · en curso" in html and "C-0300" in html

    cab["estado"] = "hecha"
    (fichas / "C-0300-x.md").write_text("---\n" + yaml.safe_dump(cab) + "---\n", encoding="utf-8")
    assert _huecos()["cancelar una cita"]["mejora"]["etiqueta"] == "apuntado como mejora · hecha"


def test_sin_carpeta_de_fichas_se_queda_en_el_estado_de_la_idea(cliente):
    _hueco_con_idea("cancelar una cita", "tomada", "C-0300")

    mejora = _huecos()["cancelar una cita"]["mejora"]
    assert mejora["ficha"] is None and mejora["etiqueta"] == "apuntado como mejora · tomada"


def test_la_sugerencia_de_pasar_a_auto_cuenta_las_aprobadas_seguidas_sin_rechazo(cliente):
    """SEC-45: la 303 dice «tras cinco aprobaciones sin fallo». Contaba todas
    las de siempre, así que sugería `auto` para algo que acababa de rechazar."""
    piezas.poner_nivel("anotar", "ask")
    con = memoria.conectar()
    for _ in range(5):
        memoria.apuntar(con, "anotar", nivel="aprobada", resultado="anotada")
    memoria.apuntar(con, "anotar", nivel="rechazada", resultado="el dueño dijo que no")
    for _ in range(2):
        memoria.apuntar(con, "anotar", nivel="aprobada", resultado="anotada")
    con.commit()
    a = next(a for a in api.secretario("confianza")["acciones"] if a["id"] == "anotar")
    assert (a["aprobadas"], a["aprobadas_seguidas"]) == (7, 2)
    assert "¿la pasas a «Lo hace solo»?" not in cliente.get("/secretario?p=confianza").text
    # Un fallo también corta la racha; cinco seguidas después, sí.
    memoria.apuntar(con, "anotar", nivel="aprobada", resultado="falló: disco", ok=False)
    for _ in range(5):
        memoria.apuntar(con, "anotar", nivel="aprobada", resultado="anotada")
    con.commit()
    con.close()
    a = next(a for a in api.secretario("confianza")["acciones"] if a["id"] == "anotar")
    assert a["aprobadas_seguidas"] == 5
    assert "Ya la aprobaste 5 veces seguidas: ¿la pasas a «Lo hace solo»?" in cliente.get(
        "/secretario?p=confianza").text


# ── Memoria en lectura, con «Editar» (C-0370) ────────────────────────────────

def _notas_de(html: str) -> list[str]:
    region = html.split('data-region="notas"')[1].split("</div>\n  </div>")[0]
    return region.split('class="bloque nota"')[1:]


def test_las_notas_salen_en_lectura_y_el_cuadro_esta_tras_editar(cliente):
    """UI-35: 80 cuadros de texto siempre abiertos, y se podía tocar una nota
    sin querer. El texto se lee; el cuadro sigue en la página (lo lee el
    filtro, `secretario.js`), dentro de un «Editar» cerrado."""
    con = memoria.conectar()
    memoria.anotar(con, "El proveedor cobra por adelantado", tema="proveedores")
    con.commit()
    con.close()

    [nota] = _notas_de(cliente.get("/secretario?p=memoria").text)

    lectura, editar = nota.split('<details class="editar-fila">')
    assert "El proveedor cobra por adelantado" in lectura and "<textarea" not in lectura
    assert re.search(r'<summary class="boton">Editar</summary>.*<textarea name="texto"', editar, re.S)
    # El filtro lee el primer `.tenue` de la nota: el tema y el origen.
    assert lectura.split('class="tenue"')[1].lstrip(">").startswith("proveedores · ")


def test_borrar_una_nota_lleva_peligro_y_pregunta(cliente):
    con = memoria.conectar()
    nid = memoria.anotar(con, "Una nota para borrar")
    con.commit()
    con.close()

    [nota] = _notas_de(cliente.get("/secretario?p=memoria").text)

    menu = nota.split('class="menu-pop"')[1]
    assert re.search(r'<button class="peligro" name="borrar" value="1"[^>]*data-confirmar=', menu)
    assert "Borrar" not in nota.split('class="menu-pop"')[0]
    # Y el botón del menú sigue borrando por la ruta de siempre.
    r = cliente.post(f"/secretario/nota/{nid}", headers=MISMO_ORIGEN, follow_redirects=False,
                     data={"borrar": "1", "volver": "/secretario?p=memoria"})
    assert r.status_code == 303 and "Nota borrada" in unquote(r.headers["location"])


# ── «Vencidos» aparte de «Próximos», e ideas del chat de lo que hay (C-0369) ──

def test_lo_vencido_sale_aparte_encima_de_proximos_con_hecho_y_mover(cliente):
    """UI-33: compromisos vencidos el 27-oct salían en «Próximos» delante de
    los de noviembre, sin marca. Van aparte, encima, y se cierran o se mueven
    por las puertas de siempre."""
    con = memoria.conectar()
    viejo = memoria.comprometer(con, "Mandar el reporte", vence="2020-01-01T15:00:00+00:00")
    memoria.comprometer(con, "Renovar el dominio", vence="2999-01-01T15:00:00+00:00")
    con.commit()
    con.close()

    s = api.secretario()
    assert [c["que"] for c in s["vencidos"]] == ["Mandar el reporte"]
    assert [c["que"] for c in s["proximos"]] == ["Renovar el dominio"]

    lado = cliente.get("/secretario").text.split('data-region="lado"')[1].split("</aside>")[0]
    vencidos, proximos = lado.split("<h2>Próximos</h2>")
    assert "Vencidos o de hoy" in vencidos and "Mandar el reporte" in vencidos and "Renovar el dominio" in proximos
    assert f'action="/secretario/compromiso/{viejo}"' in vencidos and ">Hecho</button>" in vencidos
    assert re.search(r'<summary class="boton">Mover</summary>\s*<form method="post" '
                     rf'action="/secretario/compromiso/{viejo}/editar"', vencidos)


def test_las_ideas_del_chat_vacio_salen_de_lo_que_te_espera():
    """Tres preguntas fijas, siempre las mismas: con algo esperando, la idea
    es eso; las de siempre, de reserva."""
    assert api._ideas_del_chat(solicitudes=0, nuevas=0, encargos=0) == list(api.IDEAS_CHAT)
    assert api.secretario_ideas(None) == list(api.IDEAS_CHAT)
    ideas = api._ideas_del_chat(solicitudes=1, nuevas=0, encargos=2)
    assert ideas[:2] == ["¿Qué espera mi permiso?", "¿Cómo va lo que le encargaste al orquestador?"]
    assert len(ideas) == 3 and ideas[2] == api.IDEAS_CHAT[0]


def test_el_chat_vacio_no_empuja_los_vencidos_fuera_de_pendientes(cliente):
    """El dueño quiere lo vencido sólo en Pendientes y en el parte (C-0373):
    este chat sale en el panel de todas las pantallas."""
    con = memoria.conectar()
    memoria.comprometer(con, "Mandar el reporte", vence="2020-01-01T15:00:00+00:00")
    con.execute("INSERT INTO solicitud (accion, params, motivo, creada) VALUES ('crear_slot', '{}', '', ?)",
                (memoria.ahora(),))
    con.commit()
    con.close()

    assert "vencidos" not in api.secretario_espera()
    vacio = cliente.get("/secretario").text.split('id="sec-vacio"')[1].split("</div>")[0]
    assert '<button type="button" data-idea>¿Qué espera mi permiso?</button>' in vacio
    assert "vencid" not in vacio


# ── Los niveles, con palabras (C-0371) ───────────────────────────────────────

def test_confianza_dice_los_niveles_con_palabras_y_manda_el_valor_de_siempre(cliente):
    """UI-36: los desplegables decían `ask`/`auto` y el resumen del parte
    nombraba «noche» y «en_chat». El valor que se guarda no cambia (regla 7)."""
    region = cliente.get("/secretario?p=confianza").text.split('data-region="confianza"')[1].split(
        'data-region="huecos"')[0]

    assert not re.search(r"<option[^>]*>\s*(auto|ask|never)\s*</option>", region)
    assert re.search(r'<option value="ask"[^>]*>Te pregunta</option>', region)
    assert '<option value="auto"' in region and '<option value="never"' in region
    assert "en_chat" not in region and "«noche»" not in region
    assert "<strong>ask</strong>" not in region


# ── «Vencidos o de hoy» en Pendientes, para varios a la vez (C-0373) ─────────

def _tres_vencidos_y_uno_que_viene() -> list[int]:
    con = memoria.conectar()
    ids = [memoria.comprometer(con, que, vence="2020-01-01T15:00:00+00:00")
           for que in ("Mandar el reporte", "Llamar al banco", "Pagar la luz")]
    ids.append(memoria.comprometer(con, "Renovar el dominio", vence="2999-01-01T15:00:00+00:00"))
    con.commit()
    con.close()
    return ids


def _estados(ids) -> list[str]:
    con = memoria.conectar()
    try:
        return [con.execute("SELECT estado FROM compromiso WHERE id = ?", (i,)).fetchone()[0] for i in ids]
    finally:
        con.close()


def test_pendientes_junta_lo_vencido_con_hecho_y_descartar_para_varios(cliente):
    """SEC-34: 14 vencidos sin cerrar, el más viejo de hacía tres semanas, y
    nada que los repasara. Decidido por el dueño: en Pendientes (y en el
    parte), no en «Te espera» ni al teléfono, y nada se cierra solo."""
    a, b, c, futuro = _tres_vencidos_y_uno_que_viene()

    html = cliente.get("/secretario?p=pendientes").text
    filas, lote = html.split('id="vencidos"')[1].split('id="cerrar-vencidos"', 1)
    lote = lote.split("</form>")[0]

    assert "Vencidos o de hoy" in filas and '<span class="num">3</span>' in filas
    for i in (a, b, c):
        assert re.search(rf'name="ids" value="{i}" form="cerrar-vencidos"', filas)
    assert f'value="{futuro}"' not in filas
    assert re.search(r'<button class="boton aceptar" name="estado" value="hecho"', lote)
    assert re.search(r'<button class="boton" name="estado" value="descartado"[^>]*data-confirmar=', lote)
    # «Hecho» es el primero, el que dispara un Enter; sin nada marcado, ni éste
    # ni «Descartar» se ven (CSS) y queda dicho qué hacer.
    assert lote.index('value="hecho"') < lote.index('value="descartado"')
    assert 'class="tenue sin-marcar"' in lote
    # Nada sale marcado de partida: cerrar es un gesto suyo.
    assert "checked" not in filas
    # Lo vencido sale una vez: no se repite en la lista de abiertos de debajo.
    assert html.count(f'action="/secretario/compromiso/{a}/editar"') == 1


def test_cerrar_varios_vencidos_cierra_los_marcados_y_nada_mas(cliente):
    a, b, c, futuro = _tres_vencidos_y_uno_que_viene()
    r = cliente.post("/secretario/compromisos/cerrar", headers=MISMO_ORIGEN, follow_redirects=False,
                     data={"ids": [a, b, futuro], "estado": "hecho", "volver": "/secretario?p=pendientes"})

    assert r.status_code == 303
    # Uno que ya no está vencido (se movió en otra pestaña) no se cierra.
    assert _estados([a, b, c, futuro]) == ["hecho", "hecho", "abierto", "abierto"]
    assert "2 cerrados" in unquote(r.headers["location"].replace("+", " "))
    r = cliente.post("/secretario/compromisos/cerrar", headers=MISMO_ORIGEN, follow_redirects=False,
                     data={"ids": [c], "estado": "descartado", "volver": "/secretario?p=pendientes"})
    assert _estados([c]) == ["descartado"]


def test_cerrar_varios_sin_marcar_ninguno_o_con_otro_estado_no_toca_nada(cliente):
    a, *_ = _tres_vencidos_y_uno_que_viene()
    sin_marcar = cliente.post("/secretario/compromisos/cerrar", headers=MISMO_ORIGEN, follow_redirects=False,
                              data={"estado": "hecho", "volver": "/secretario?p=pendientes"})
    reabrir = cliente.post("/secretario/compromisos/cerrar", headers=MISMO_ORIGEN, follow_redirects=False,
                           data={"ids": [a], "estado": "abierto", "volver": "/secretario?p=pendientes"})
    assert "Marca" in unquote(sin_marcar.headers["location"].replace("+", " "))
    assert reabrir.status_code == 303 and _estados([a]) == ["abierto"]


def test_cerrar_marcados_que_ya_no_estan_vencidos_no_dice_cero_cerrados(cliente):
    *_, futuro = _tres_vencidos_y_uno_que_viene()
    r = cliente.post("/secretario/compromisos/cerrar", headers=MISMO_ORIGEN, follow_redirects=False,
                     data={"ids": [futuro], "estado": "hecho", "volver": "/secretario?p=pendientes"})
    aviso = unquote(r.headers["location"].replace("+", " "))
    assert "Ninguno de los marcados seguía vencido o de hoy" in aviso and "0 " not in aviso
    assert _estados([futuro]) == ["abierto"]


def test_un_compromiso_de_hoy_sin_vencer_sale_con_los_vencidos_y_no_en_proximos(cliente):
    """Uno de hoy sin hora se guarda a las 9 (`tiempo.a_utc`): con el corte en
    «ahora», a las 10 salía como vencido y a las 8 como próximo. El rótulo
    dice «Vencidos o de hoy», y lo es."""
    from hub.secretario import tiempo
    hoy = tiempo.ahora_local().date().isoformat()
    con = memoria.conectar()
    cid = memoria.comprometer(con, "Pagar la luz", vence=tiempo.a_utc(f"{hoy}T23:30"))
    con.commit()
    con.close()

    s = api.secretario()
    assert [c["id"] for c in s["vencidos"]] == [cid] and s["proximos"] == []
    r = cliente.post("/secretario/compromisos/cerrar", headers=MISMO_ORIGEN, follow_redirects=False,
                     data={"ids": [cid], "estado": "hecho", "volver": "/secretario?p=pendientes"})
    assert r.status_code == 303 and _estados([cid]) == ["hecho"]


# ── el micrófono del chat no se queda abierto (C-0427) ──────────────────────
# Con el micrófono que tarda en abrirse y cuenta sus pistas vivas: lo que
# pasa mientras se abre era lo que nadie probaba.


def test_un_doble_toque_en_hablar_abre_un_solo_microfono_y_parar_lo_cierra(tmp_path):
    accion = ("nodo('sec-hablar').disparar('click');"
              "setTimeout(() => nodo('sec-hablar').disparar('click'), 1);"
              "setTimeout(() => nodo('sec-hablar').disparar('click'), 8);")
    r = ejecutar(GUION, tmp_path, {"POST /api/voz": {"ok": True, "texto": "una vez"}},
                 previo=PREVIO + VOZ_FALSA + MICROFONO_VIVO, accion=accion)
    assert r["errores"] == []
    assert r["microfonos"] == 1 and r["pistas_vivas"] == 0


@pytest.mark.parametrize("boton", ["sec-voz-salir", "sec-voz-pausa"])
def test_salir_o_pausar_el_modo_voz_mientras_se_abre_el_microfono_no_deja_grabando(tmp_path, boton):
    """Salir o pausar llamaba a `callarTodo` con la grabación aún sin abrir:
    no había nada que parar, y al abrirse se quedaba grabando fuera del modo."""
    accion = ("nodo('sec-modo-voz').disparar('click');"
              f"setTimeout(() => nodo('{boton}').disparar('click'), 1);")
    r = ejecutar(GUION, tmp_path, {"POST /api/voz": {"ok": True, "texto": "x"}},
                 previo=PREVIO + VOZ_FALSA + MICROFONO_VIVO, accion=accion)
    assert r["errores"] == []
    assert r["microfonos"] == 1 and r["pistas_vivas"] == 0
    assert "/api/voz" not in r["peticiones"]


# ── con el dedo, en el chat (UI-47, C-0366) ──────────────────────────────────

def _reglas_del_chat(consulta: str) -> dict[str, str]:
    from arnes_js import ESTATICOS
    from test_css_componentes import _bloques_media, _sin_comentarios
    css = _sin_comentarios((ESTATICOS / "chat-secretario.css").read_text(encoding="utf-8"))
    return {" ".join(r.group(1).split()): r.group(2)
            for cuerpo in _bloques_media(css, consulta)
            for r in re.finditer(r"([^{}]+)\{([^}]*)\}", cuerpo)}


def test_con_el_dedo_lo_pequeno_del_chat_se_toca_en_44_px_sin_cambiar_su_dibujo():
    """Medido a 390 px: 12 de 21 controles del chat bajo 44 px —quitar un
    adjunto 20, responder 28, «Opciones» 26, los chips unos 25—. La regla
    común (C-0348) deja fuera el chat; aquí el toque crece con un `::before`
    transparente, sin mover el alto de nada."""
    reglas = _reglas_del_chat("(pointer: coarse)")
    toque = {s: c for s, c in reglas.items() if "::before" in s}
    for pequeno in (".por-mandar .quitar", ".burbuja .citar", ".copiar-codigo", ".chip-modo", ".menu > summary"):
        assert any(pequeno in s for s in toque), pequeno
    for selector, cuerpo in toque.items():
        assert re.search(r"content\s*:\s*''", cuerpo) and "background" not in cuerpo, selector
        alto = re.search(r"height\s*:\s*max\(100%,\s*44px\)", cuerpo) or "calc(100% - 38px)" in cuerpo
        assert alto, (selector, cuerpo)
    con_sitio = [s for s, c in reglas.items() if re.search(r"min-height\s*:\s*44px", c)]
    for holgado in (".permiso .botones", ".vacio-chat", "#sec-voz-pausa", ".opciones-pop", ".globo-asuntos", ".en-ingles"):
        assert any(holgado in s for s in con_sitio), holgado


def test_en_el_telefono_responder_va_dentro_del_globo():
    """En `sec-conversacion-390-vista.png` el ↩ del globo del dueño quedaba
    pegado al borde izquierdo, fuera del globo."""
    reglas = _reglas_del_chat("(hover:none)")
    dentro = [c for s, c in reglas.items() if s.endswith("> .citar") and ".burbuja.dueno" in s]
    assert dentro and re.search(r"left\s*:\s*auto", dentro[0]) and re.search(r"right\s*:\s*8px", dentro[0])
    assert any(":has(> .citar)" in s and re.search(r"padding-right\s*:\s*44px", c) for s, c in reglas.items())
