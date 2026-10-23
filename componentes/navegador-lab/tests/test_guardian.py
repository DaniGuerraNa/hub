import json
import threading
import time

from playwright.sync_api import sync_playwright

from navegador.aprobaciones import Aprobaciones
from conftest import mutaciones


def entrar(pg, url):
    pg.goto(url + "/login")
    pg.get_by_label("Usuario").fill("usuario")
    pg.get_by_label("Contraseña").fill("x")
    pg.get_by_role("button", name="Iniciar sesión").click()
    pg.wait_for_url("**/console/home")


def borrar_pedidos(pg, url):
    pg.goto(url + "/apigateway/main/apis")
    pg.get_by_label("Seleccionar pedidos-api").check()
    pg.get_by_role("button", name="Eliminar").click()
    pg.get_by_label("Confirmación").fill("confirmar")
    pg.on("dialog", lambda d: d.accept())
    pg.locator("#si").click()
    time.sleep(1.5)


def eventos(registro):
    return [json.loads(l) for l in registro.read_text().splitlines()]


def test_en_modo_lectura_el_borrado_no_llega_al_servidor_pero_la_consulta_si(chrome, consola, guardian):
    g = guardian("lectura")
    with sync_playwright() as p:
        pg = p.chromium.connect_over_cdp(chrome["cdp"]).contexts[0].new_page()
        entrar(pg, consola["url"])
        borrar_pedidos(pg, consola["url"])
        pg.goto(consola["url"] + "/cloudwatch/home#logsV2:logs-insights")
        pg.get_by_label("/aws/lambda/pedidos-crear").check()
        pg.get_by_role("button", name="Ejecutar consulta").click()
        pg.get_by_text("Completada").wait_for(timeout=10000)
    assert mutaciones(consola) == []
    bloq = [e for e in eventos(g["registro"]) if e["evento"] == "bloqueada"]
    assert [e["accion"] for e in bloq] == ["DeleteRestApi"]
    perm = {e["accion"] for e in eventos(g["registro"]) if e["evento"] == "permitida"}
    assert {"StartQuery", "GetQueryResults", "login"} <= perm


def test_no_deja_navegar_fuera_de_los_origenes_permitidos(chrome, consola, guardian):
    g = guardian("lectura")
    with sync_playwright() as p:
        pg = p.chromium.connect_over_cdp(chrome["cdp"]).contexts[0].new_page()
        try:
            pg.goto("http://example.com/", timeout=5000)
        except Exception as e:
            assert "ERR_BLOCKED_BY_CLIENT" in str(e)
        else:
            raise AssertionError("la navegación salió")
    assert any(e["evento"] == "bloqueada" and "example.com" in e["url"] for e in eventos(g["registro"]))


def test_en_modo_preguntar_el_borrado_espera_y_sale_solo_si_el_dueno_lo_aprueba(chrome, consola, guardian):
    g = guardian("preguntar")
    aprob = Aprobaciones(g["aprob"])
    vistas = []

    def dueño():
        fin = time.time() + 15
        while time.time() < fin:
            pend = aprob.pendientes()
            if pend:
                vistas.append(pend[0])
                aprob.responder(pend[0]["id"], aprobar=True)
                return
            time.sleep(0.2)
    hilo = threading.Thread(target=dueño); hilo.start()
    with sync_playwright() as p:
        pg = p.chromium.connect_over_cdp(chrome["cdp"]).contexts[0].new_page()
        entrar(pg, consola["url"])
        borrar_pedidos(pg, consola["url"])
    hilo.join()
    assert vistas and vistas[0]["accion"] == "DeleteRestApi"
    assert "?" not in vistas[0]["url"]
    assert [m["accion"] for m in mutaciones(consola)] == ["DeleteRestApi"]


def test_sin_respuesta_la_pregunta_caduca_como_un_no(chrome, consola, guardian):
    g = guardian("preguntar", espera=2)
    with sync_playwright() as p:
        pg = p.chromium.connect_over_cdp(chrome["cdp"]).contexts[0].new_page()
        entrar(pg, consola["url"])
        borrar_pedidos(pg, consola["url"])
        time.sleep(2)
    assert mutaciones(consola) == []
    estados = [json.loads(f.read_text())["estado"] for f in g["aprob"].glob("*.json")]
    assert estados == ["caducada"]


def test_la_sesion_sobrevive_a_cerrar_y_reabrir_el_navegador_con_el_mismo_perfil(chrome, consola):
    """Lo que pidió el dueño: entrar una vez y que al reabrir siga dentro.

    Medido (Chromium 156): con un perfil persistente sobreviven las dos, la
    cookie persistente («Recordar este dispositivo») y también la de sesión —
    Chromium guarda las de sesión en la base y no las purgó al reabrir—. Por eso
    no se afirma que la de sesión se pierda: sería afirmar algo que no pasa. Lo
    que manda de verdad es la caducidad del lado del servidor (en AWS, 1–12 h).
    """
    def entrar_y_reabrir(recordar):
        with sync_playwright() as p:
            pg = p.chromium.connect_over_cdp(chrome["cdp"]).contexts[0].new_page()
            pg.goto(consola["url"] + "/login")
            pg.get_by_label("Usuario").fill("usuario"); pg.get_by_label("Contraseña").fill("x")
            if recordar:
                pg.get_by_label("Recordar este dispositivo").check()
            pg.get_by_role("button", name="Iniciar sesión").click()
            pg.wait_for_url("**/console/home")
            time.sleep(1.5)   # Chrome escribe las cookies a disco en diferido
        chrome["reiniciar"]()
        with sync_playwright() as p:
            pg = p.chromium.connect_over_cdp(chrome["cdp"]).contexts[0].new_page()
            pg.goto(consola["url"] + "/console/home")
            return "/login" not in pg.url
    assert entrar_y_reabrir(recordar=True) is True


def test_con_avisar_telegram_cada_pregunta_deja_un_timbre_sin_contenido(tmp_path, monkeypatch):
    import asyncio
    from navegador.guardian import timbre_del_hub
    monkeypatch.setenv("HUB_HOME", str(tmp_path / "hub"))
    a = Aprobaciones(tmp_path / "ap", espera=0.5, al_preguntar=timbre_del_hub)
    asyncio.run(a.pedir(accion="DeleteRestApi", metodo="POST", url="https://x/restapis/cliente-secreto",
                        politica="p"))
    timbres = list((tmp_path / "hub/orquestador/timbres").glob("*.json"))
    assert len(timbres) == 1
    t = json.loads(timbres[0].read_text())
    assert t["pantalla"] == "Navegante" and "pregunta" in t["texto"]
    assert "cliente-secreto" not in t["texto"] and "DeleteRestApi" not in t["texto"]
