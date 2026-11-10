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

from arnes_js import ejecutar, script_estatico
from hub import web
from hub.secretario import memoria, piezas

# Los avisos de estos tests salen por el timbre de Telegram (el respaldo, decisión 310).
pytestmark = pytest.mark.usefixtures("canal_telegram")

# Con el formateador del chat delante, como en la página.
GUION = (script_estatico("formato-chat.js") + "\n" + script_estatico("chat-secretario.js") + "\n"
         + script_estatico("secretario.js"))


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


def test_con_voz_encendida_lee_la_respuesta_sin_markdown(tmp_path):
    respuesta = {"hilo": 1, "turnos": [{"id": 5, "rol": "secretario", "texto": "Tienes **dos** cosas en [Trabajo](/trabajo).",
                                        "estado": "listo", "tarjetas": []}]}
    r = ejecutar(GUION, tmp_path, {"POST /api/secretario/mensaje": {"ok": True},
                                   "/api/secretario/turnos": respuesta},
                 previo=PREVIO + "localStorage.setItem('secretario.voz', '1');",
                 accion="nodo('sec-texto').value = 'hola'; nodo('sec-escribir').disparar('submit', {preventDefault(){}});")
    assert r["errores"] == []
    assert ["dicho", "Tienes dos cosas en Trabajo."] in r["valores"]


def test_sin_nada_que_esperar_no_se_queda_preguntando_en_bucle(tmp_path):
    r = ejecutar(GUION, tmp_path, previo=PREVIO)
    assert r["errores"] == []
    assert 1500 not in r["temporizadores"]


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
    # Un ventilador a 0.03: hablar es pasar de 0.09, no del mínimo fijo.
    fin, _ = _silencio(tmp_path, "[[0.03, 400], [0.05, 9000]]")
    assert fin == "nada"


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


def test_el_modo_voz_es_un_boton_y_no_una_casilla_de_opciones(cliente):
    html = cliente.get("/secretario").text
    assert 'id="sec-modo-voz"' in html and 'id="continua"' not in html


def test_fuentes_ensena_lo_que_gasta_cada_trabajo(cliente):
    memoria.apuntar_llamada("triaje", "claude-haiku", 4.2, 0.0312, 1200, 80)
    html = cliente.get("/secretario?p=fuentes").text
    assert "Lo que gasta, últimos 7 días" in html
    assert "<td>triaje</td><td>1</td><td>0</td>" in html and "0.03 USD" in html and "1,280" in html


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
    assert ["voz", "en-US", "en-US"] in r["valores"]


def test_el_boton_english_lo_cambia_en_el_servidor(tmp_path):
    r = ejecutar(GUION, tmp_path, {"POST /api/secretario/ingles": {"ok": True, "activo": True}},
                 previo=PREVIO + "nodo('sec-modo-ingles').dataset = { activo: '' };",
                 accion="nodo('sec-modo-ingles').disparar('click');"
                        "setTimeout(() => registro.valores.push(['pulsado', nodo('sec-modo-ingles').dataset.activo]), 5);")
    assert r["errores"] == []
    assert {"url": "/api/secretario/ingles", "metodo": "POST", "cuerpo": {"activo": True}} in r["enviados"]
    assert ["pulsado", "1"] in r["valores"]


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
