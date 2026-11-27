"""El estudio como herramienta opcional del hub (decisión 461).

Lo que se protege, en este orden: que apagado —como viene— no salga en ningún
menú ni se le pregunte nada; que al estudio sólo se le hagan dos preguntas
cortas, sin dejar pasar más que las claves de su lista y sin colgar la
pantalla si no contesta o gotea; y que abrirlo sólo se ofrezca desde la PC
donde corre. El interruptor y el cliente HTTP son los del Puente KVM, y sus
pruebas están en `test_puente.py`.
"""

from __future__ import annotations

import json
import re
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from fastapi.testclient import TestClient

from hub import api, estudio, interfaz, kits, navegacion, opcionales, web
from test_puente import de_fuera_con_alta  # noqa: F401  (fixture)


@pytest.fixture
def cliente():
    return TestClient(web.app)


@pytest.fixture
def encendido():
    opcionales.poner("estudio", True)


class _Estudio(BaseHTTPRequestHandler):
    """Un estudio falso: contesta su salud y sus proyectos con lo que diga la prueba."""

    respuestas: dict = {}
    vistos: list = []

    def do_GET(self):  # noqa: N802
        type(self).vistos.append((self.command, self.path, self.headers.get("Host")))
        codigo, cuerpo = self.respuestas.get(self.path, (404, {"detail": "no"}))
        crudo = json.dumps(cuerpo).encode()
        self.send_response(codigo)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(crudo)))
        self.end_headers()
        self.wfile.write(crudo)

    def do_POST(self):  # noqa: N802
        type(self).vistos.append((self.command, self.path, self.headers.get("Host")))
        self.send_response(405)
        self.end_headers()

    def log_message(self, *a):
        pass


#: Un proyecto como los que da el estudio, con lo que no debe salir marcado.
PROYECTO = {"id": "viajes", "nombre": "Reservas de viajes", "momento": "Iteración 2 · maqueta",
            "esperando": 2, "trabajando": True,
            "ruta": "/ruta/SECRETO-RUTA", "ultimo_mensaje": "SECRETO-CONVERSACION"}


@pytest.fixture
def estudio_falso(monkeypatch):
    def montar(proyectos=(PROYECTO,), salud=None, codigo_proyectos=200):
        respuestas = {"/api/salud": (200, salud if salud is not None else {"vivo": True, "version": "0.1"}),
                      "/api/proyectos": (codigo_proyectos, list(proyectos))}
        manejador = type("E", (_Estudio,), {"respuestas": respuestas, "vistos": []})
        servidor = ThreadingHTTPServer(("127.0.0.1", 0), manejador)
        threading.Thread(target=servidor.serve_forever, daemon=True).start()
        servidores.append(servidor)
        monkeypatch.setenv("ESTUDIO_PUERTO", str(servidor.server_address[1]))
        return manejador
    servidores: list = []
    yield montar
    for s in servidores:
        s.shutdown()
        s.server_close()


# ───────────────────────────── apagada, no se nota ─────────────────────────────


def test_viene_apagada_y_se_enciende_por_su_cuenta():
    assert "estudio" in opcionales.OPCIONALES
    assert not opcionales.encendida("estudio")
    assert opcionales.poner("estudio", True) == {"estudio"}
    assert not opcionales.encendida("puente-kvm")


def test_apagada_no_sale_en_el_rail_de_siempre_ni_en_el_mapa_de_la_guia_y_encendida_si(cliente):
    assert 'href="/estudio"' not in cliente.get("/reuniones").text
    assert "/estudio" not in json.dumps(cliente.get("/api/guia").json()["mapa"])
    opcionales.poner("estudio", True)
    html = cliente.get("/reuniones").text
    agentes = html[html.index('<span class="nom">Agentes</span>'):]
    agentes = agentes[:agentes.index("</details>")]
    assert 'href="/estudio"' in agentes
    assert "/estudio" in json.dumps(cliente.get("/api/guia").json()["mapa"])


def test_apagada_no_sale_en_herramientas_de_la_interfaz_nueva_y_encendida_si():
    for rail in ({"opcionales": ["estudio"]}, {"opcionales": ["puente-kvm"]}, {}):
        herramientas = next(s for s in navegacion.con_cifras(rail) if s["clave"] == "herramientas")
        rutas = [p["ruta"] for p in herramientas["pantallas"]]
        assert ("/estudio" in rutas) is ("estudio" in rail.get("opcionales", [])), rail
    assert navegacion.de_pantalla("estudio", "/estudio") == "herramientas"


@pytest.mark.skipif(not interfaz.disponible(), reason="esta instalación no trae la interfaz nueva")
def test_apagada_tampoco_sale_en_las_pantallas_de_la_interfaz_nueva(cliente):
    cliente.cookies.set(interfaz.COOKIE, interfaz.NUEVA)
    for ruta in ("/", "/reuniones", "/guia"):
        assert 'href="/estudio"' not in cliente.get(ruta).text, ruta


def test_donde_esta_del_secretario_solo_la_encuentra_encendida():
    from hub import db
    from hub.secretario import herramientas, memoria
    h = db.conectar()
    db.inicializar(h)
    h.close()
    con = memoria.conectar()
    try:
        buscar = herramientas.todas()["hub_buscar"].funcion
        urls = lambda: [r["url"] for r in buscar(con, {"texto": "estudio"})["resultados"]]  # noqa: E731
        assert "/estudio" not in urls()
        opcionales.poner("estudio", True)
        assert "/estudio" in urls()
    finally:
        con.close()


def test_la_guia_ofrece_encenderla_con_un_formulario_normal(cliente):
    html = cliente.get("/guia").text
    tarjeta = html[html.index('id="opcional-estudio"'):]
    tarjeta = tarjeta[:tarjeta.index("</form>")]
    assert "Estudio: apagado" in tarjeta and 'name="clave" value="estudio"' in tarjeta
    r = cliente.post("/opcionales", data={"clave": "estudio", "encendida": "si"},
                     headers={"origin": "http://127.0.0.1:8787"}, follow_redirects=False)
    assert r.status_code == 303 and opcionales.encendida("estudio")


def test_tecleada_a_mano_apagada_dice_donde_se_enciende_y_no_le_pregunta(cliente, monkeypatch):
    monkeypatch.setattr(estudio, "estado", lambda *a, **k: pytest.fail("apagado no se le pregunta"))
    r = cliente.get("/estudio")
    assert r.status_code == 200
    assert "Apagado en esta instalación" in r.text and 'href="/guia#opcionales"' in r.text
    assert "Abrir el estudio" not in r.text


def test_el_rail_y_las_demas_pantallas_no_le_preguntan_al_estudio(cliente, encendido, monkeypatch):
    monkeypatch.setattr(estudio, "estado", lambda *a, **k: pytest.fail("sólo /estudio le pregunta"))
    for ruta in ("/", "/reuniones", "/guia"):
        assert cliente.get(ruta).status_code == 200, ruta


# ───────────────────────────── la pregunta al estudio ─────────────────────────────


def test_contesta_con_su_version_y_sus_proyectos_solo_con_las_claves_de_la_lista(estudio_falso):
    falso = estudio_falso()
    e = estudio.estado()
    assert e["vivo"] and e["version"] == "0.1" and e["motivo"] is None
    assert set(e) <= set(estudio.CLAVES)
    assert e["proyectos"] == [{"id": "viajes", "nombre": "Reservas de viajes",
                               "momento": "Iteración 2 · maqueta", "esperando": 2, "trabajando": True}]
    assert "SECRETO" not in json.dumps(e)
    puerto = estudio.puerto()
    assert falso.vistos == [("GET", "/api/salud", f"127.0.0.1:{puerto}"),
                            ("GET", "/api/proyectos", f"127.0.0.1:{puerto}")]


def test_las_claves_y_los_valores_que_no_estan_en_su_lista_no_pasan(estudio_falso):
    estudio_falso(proyectos=[
        {"id": "../fuera", "nombre": "con un id que no cabe en una dirección"},
        {"id": "a b", "nombre": "otro"},
        {"nombre": "sin id"},
        "no soy un proyecto",
        {"id": "raro", "nombre": "con\x1b[2J control\n y saltos " + "x" * 300,
         "momento": {"no": "texto"}, "esperando": True, "trabajando": "sí", "extra": "SECRETO"},
        {"id": "negativo", "esperando": -3, "trabajando": False},
    ], salud={"vivo": True, "version": "0.1 SECRETO", "ruta": "SECRETO"})
    e = estudio.estado()
    assert "version" not in e and "SECRETO" not in json.dumps(e)
    assert [p["id"] for p in e["proyectos"]] == ["raro", "negativo"]
    raro, negativo = e["proyectos"]
    assert set(raro) == set(estudio.CLAVES_PROYECTO)
    assert raro["nombre"].startswith("con [2J control y saltos") and len(raro["nombre"]) <= estudio.NOMBRE_MAX
    assert "\x1b" not in raro["nombre"] and "\n" not in raro["nombre"]
    assert raro["momento"] is None and raro["esperando"] is None and raro["trabajando"] is None
    assert negativo["nombre"] == "negativo" and negativo["esperando"] is None and negativo["trabajando"] is False


def test_una_salud_que_no_dice_vivo_no_cuenta_como_que_contesta(estudio_falso):
    estudio_falso(salud={"version": "0.1"})
    e = estudio.estado()
    assert e["vivo"] is False and e["motivo"] == "contesta algo que no es su estado"
    assert e["proyectos"] is None


def test_si_sus_proyectos_fallan_contesta_igual_y_dice_por_que(estudio_falso):
    estudio_falso(codigo_proyectos=500)
    e = estudio.estado()
    assert e["vivo"] and e["proyectos"] is None and "HTTP 500" in e["motivo_proyectos"]


def test_no_contesta_al_momento_si_no_hay_nadie_en_su_puerto():
    antes = time.monotonic()
    e = estudio.estado()
    assert time.monotonic() - antes < 1
    assert e == {"vivo": False, "motivo": "no hay nada escuchando en su puerto",
                 "proyectos": None, "motivo_proyectos": None}


def test_un_estudio_colgado_no_hace_esperar_mas_de_un_segundo(monkeypatch):
    mudo = socket.socket()
    mudo.bind(("127.0.0.1", 0))
    mudo.listen(4)
    monkeypatch.setenv("ESTUDIO_PUERTO", str(mudo.getsockname()[1]))
    try:
        antes = time.monotonic()
        e = estudio.estado()
        assert time.monotonic() - antes < 1
        assert e["vivo"] is False and e["motivo"] == "no contestó a tiempo"
    finally:
        mudo.close()


def test_un_estudio_que_gotea_sus_proyectos_se_corta_al_plazo_de_las_dos_preguntas(monkeypatch):
    """La salud al momento y los proyectos de byte en byte: el plazo es uno
    para las dos, así que la pantalla no espera 0,8 s por cada pregunta."""
    servidor = socket.socket()
    servidor.bind(("127.0.0.1", 0))
    servidor.listen(2)
    monkeypatch.setenv("ESTUDIO_PUERTO", str(servidor.getsockname()[1]))
    parar = threading.Event()
    salud = json.dumps({"vivo": True}).encode()

    def contestar():
        for i in range(2):
            try:
                con, _ = servidor.accept()
            except OSError:
                return
            with con:
                con.recv(4096)
                if i == 0:
                    con.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: %d\r\n\r\n" % len(salud) + salud)
                    time.sleep(0.5)
                    continue
                con.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 5000\r\n\r\n[")
                for _ in range(100):
                    if parar.is_set():
                        return
                    try:
                        con.sendall(b" ")
                    except OSError:
                        return
                    time.sleep(0.1)
    threading.Thread(target=contestar, daemon=True).start()
    try:
        antes = time.monotonic()
        e = estudio.estado()
        assert time.monotonic() - antes < 1.1
        assert e["vivo"] and e["proyectos"] is None and e["motivo_proyectos"] == "no contestó a tiempo"
    finally:
        parar.set()
        servidor.close()


def test_mas_de_su_tope_no_se_lee(estudio_falso):
    muchos = [{"id": f"p{i}", "nombre": "x" * 80, "momento": "y" * 60} for i in range(2000)]
    estudio_falso(proyectos=muchos)
    e = estudio.estado()
    assert e["vivo"] and e["proyectos"] is None
    assert e["motivo_proyectos"] == "contesta demasiado: eso no es su lista de proyectos"


def test_no_ensena_mas_de_su_tope_de_proyectos(estudio_falso):
    estudio_falso(proyectos=[{"id": f"p{i}"} for i in range(estudio.MAX_PROYECTOS + 5)])
    assert len(estudio.estado()["proyectos"]) == estudio.MAX_PROYECTOS


@pytest.mark.parametrize("valor, esperado", [("8800", 8800), ("", 8795), ("no", 8795), ("70000", 8795)])
def test_el_puerto_sale_de_su_variable_y_uno_raro_vale_el_de_siempre(monkeypatch, valor, esperado):
    monkeypatch.setenv("ESTUDIO_PUERTO", valor)
    assert estudio.puerto() == esperado
    assert estudio.direccion() == f"http://127.0.0.1:{esperado}"
    assert estudio.direccion_de("viajes") == f"http://127.0.0.1:{esperado}/p/viajes/"
    assert estudio.direccion_de("../fuera") is None


# ───────────────────────────── la pantalla ─────────────────────────────


def test_desde_la_pc_se_ofrece_abrir_el_estudio_y_cada_proyecto_en_pestana_aparte(cliente, encendido,
                                                                                   estudio_falso):
    estudio_falso()
    html = cliente.get("/estudio").text
    base = estudio.direccion()
    assert re.search(rf'<a class="boton cta" href="{re.escape(base)}" target="_blank" rel="noopener">'
                     r"Abrir el estudio</a>", html)
    assert re.search(rf'<a class="boton aceptar" href="{re.escape(base)}/p/viajes/" target="_blank" '
                     r'rel="noopener">Abrir</a>', html)
    assert "Reservas de viajes" in html and "Te espera 2" in html and "Claude está trabajando" in html
    assert "versión 0.1" in html
    assert "<iframe" not in html and html.count('class="boton cta"') == 1
    assert "SECRETO" not in html


def test_desde_fuera_se_ve_como_esta_pero_no_se_ofrece_abrir(de_fuera_con_alta, encendido,  # noqa: F811
                                                            estudio_falso):
    estudio_falso()
    r = de_fuera_con_alta.get("/estudio")
    assert r.status_code == 200
    assert "Reservas de viajes" in r.text and "Te espera 2" in r.text
    assert "Abrir el estudio" not in r.text and "127.0.0.1:" not in r.text
    assert "Se abre en la PC donde corre" in r.text
    assert "direccion" not in json.dumps(api.estudio(local=False))


def test_sin_contestar_dice_por_que_y_como_se_instala_si_el_kit_no_esta(cliente, encendido):
    antes = time.monotonic()
    r = cliente.get("/estudio")
    assert time.monotonic() - antes < 3
    assert r.status_code == 200
    assert "No contesta" in r.text and "no hay nada escuchando en su puerto" in r.text
    assert "Abrir el estudio</a>" not in r.text and "Cuando conteste" in r.text
    assert 'id="instalar"' in r.text and "no está instalado en esta máquina" in r.text
    assert "bash scripts/kit.sh ruta estudio" in r.text and "systemctl --user start estudio" in r.text


def test_sin_contestar_y_con_el_kit_instalado_da_su_instalador(cliente, encendido):
    carpeta = kits.ruta_de("estudio", "0.1")
    carpeta.mkdir(parents=True)
    html = cliente.get("/estudio").text
    assert f"<code>bash \"{carpeta}/install.sh\"</code>" in html
    assert "no está instalado en esta máquina" not in html


def test_desde_fuera_sin_contestar_no_da_la_carpeta_del_kit(de_fuera_con_alta, encendido):  # noqa: F811
    kits.ruta_de("estudio", "0.1").mkdir(parents=True)
    html = de_fuera_con_alta.get("/estudio").text
    assert "install.sh" not in html and "kit" not in api.estudio(local=False)
    assert "Se instala y se arranca en la PC donde corre" in html


def test_sin_proyectos_lo_dice(cliente, encendido, estudio_falso):
    estudio_falso(proyectos=[])
    assert "Aún no tiene ningún proyecto" in cliente.get("/estudio").text
