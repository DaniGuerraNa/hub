"""Las puertas que protegen el Mac al cambiar de aparato, de ajustes o de página.

Cada una cierra un camino por el que Claude acabaría tecleando donde nadie le
ha dado permiso: el control dado con el simulador no vale para el Mac real, y
unos ajustes no pueden quedar a medias con una tarea en marcha.
"""

import time

import pytest

from puente_kvm import config

from .ayuda import PERSONA, esperar, puente_simulado

# Un JetKVM que no existe: la conexión se rechaza en el acto.
NINGUN_JETKVM = {"tipo": "jetkvm", "url": "http://127.0.0.1:1"}


@pytest.fixture
def entorno():
    with puente_simulado() as (c, sim):
        yield c, sim


def bitacora(c) -> list[dict]:
    return c.get("/api/bitacora").json()


def test_cambiar_de_aparato_devuelve_el_control_a_la_persona_y_lo_apunta(entorno):
    c, _ = entorno
    c.post("/api/control", json={"accion": "dar"}, headers=PERSONA)
    r = c.post("/api/ajustes", json={"dispositivo": NINGUN_JETKVM}, headers=PERSONA)
    assert r.status_code == 200, r.text
    control = c.get("/api/estado").json()["control"]
    assert control["modo"] == "libre"
    assert "aparato" in control["motivo"]
    assert any(e["tipo"] == "control" and "aparato" in e["detalle"] for e in bitacora(c))
    # Y con el control devuelto, Claude no teclea en el aparato nuevo.
    assert c.post("/api/teclear", json={"texto": "x"}).status_code == 423


def test_reconectar_el_aparato_devuelve_el_control_a_la_persona(entorno):
    c, _ = entorno
    c.post("/api/control", json={"accion": "dar"}, headers=PERSONA)
    assert c.post("/api/reconectar", headers=PERSONA).status_code == 200
    assert c.get("/api/estado").json()["control"]["modo"] == "libre"
    assert any(e["tipo"] == "control" and "reconect" in e["detalle"] for e in bitacora(c))


def test_guardar_otros_ajustes_sin_cambiar_de_aparato_no_quita_el_control(entorno):
    c, _ = entorno
    c.post("/api/control", json={"accion": "dar"}, headers=PERSONA)
    perfil = {**config.PERFIL_POR_OMISION, "retardo_tecla_ms": 7}
    assert c.post("/api/ajustes", json={"perfil": perfil}, headers=PERSONA).status_code == 200
    assert c.get("/api/estado").json()["control"]["modo"] == "claude"


def test_con_una_tarea_en_marcha_los_ajustes_no_se_guardan_ni_se_aplican():
    with puente_simulado(lineas=400, retardo_ms=60) as (c, _):
        antes = config.leer_ajustes()
        c.post("/api/control", json={"accion": "dar"}, headers=PERSONA)
        assert c.post("/api/lecturas", json={"nombre": "larga"}).status_code == 200
        time.sleep(0.3)
        assert c.get("/api/estado").json()["tarea"]
        perfil = {**antes["perfil"], "retardo_tecla_ms": 150}
        r = c.post("/api/ajustes", json={"perfil": perfil, "dispositivo": NINGUN_JETKVM}, headers=PERSONA)
        assert r.status_code == 409
        assert config.leer_ajustes() == antes  # nada en disco
        estado = c.get("/api/estado").json()
        assert estado["perfil"]["retardo_tecla_ms"] == 60  # ni en memoria
        assert estado["dispositivo"]["tipo"] == "simulador"
        c.post("/api/control", json={"accion": "parar"}, headers=PERSONA)
        esperar(c)


def test_con_una_tarea_en_marcha_no_se_reconecta():
    with puente_simulado(lineas=400, retardo_ms=60) as (c, _):
        c.post("/api/control", json={"accion": "dar"}, headers=PERSONA)
        c.post("/api/lecturas", json={"nombre": "larga"})
        time.sleep(0.3)
        assert c.post("/api/reconectar", headers=PERSONA).status_code == 409
        c.post("/api/control", json={"accion": "parar"}, headers=PERSONA)
        esperar(c)


@pytest.mark.parametrize("ver", ["/\\sitio.example", "//sitio.example", "/\\/sitio.example", "https://sitio.example",
                                 "javascript:alert(1)", "/panel/../../x", "/api/estado", "/lecturas/../ajustes"])
def test_el_marco_de_la_izquierda_solo_abre_paginas_de_esta_web(entorno, ver):
    c, _ = entorno
    r = c.get("/", params={"ver": ver})
    assert r.status_code == 200
    assert 'src="/panel"' in r.text


@pytest.mark.parametrize("ver", ["/panel", "/claude", "/ajustes", "/lecturas/usp-x-1a2b3c", "/cambios/cambio-9f8e7d"])
def test_el_marco_de_la_izquierda_abre_las_paginas_conocidas(entorno, ver):
    c, _ = entorno
    assert f'src="{ver}"' in c.get("/", params={"ver": ver}).text


@pytest.mark.parametrize("ruta", ["/", "/panel", "/claude", "/ajustes"])
def test_ninguna_otra_web_puede_enmarcar_el_puente(entorno, ruta):
    # Enmarcado en otra web, un clic robado en «Dar el control» o «Aprobar» las salta.
    c, _ = entorno
    r = c.get(ruta)
    assert r.headers["content-security-policy"] == "frame-ancestors 'self'"
    assert r.headers["x-frame-options"] == "SAMEORIGIN"


def test_el_estado_dice_la_version_del_codigo_que_corre(entorno):
    import tomllib

    c, _ = entorno
    version = tomllib.loads((config.CODIGO / "pyproject.toml").read_text())["project"]["version"]
    assert c.get("/api/estado").json()["version"] == version


@pytest.fixture
def sin_aparato():
    """Un puente con un JetKVM que no responde: lo que ve quien lo instala mal."""
    from fastapi.testclient import TestClient

    from puente_kvm.app import crear_app
    from puente_kvm.jetkvm import JetKVM
    with TestClient(crear_app(JetKVM("http://127.0.0.1:1", ""), hosts={"testserver"})) as c:
        yield c


def test_sin_aparato_el_error_de_conexion_dice_que_hacer(sin_aparato):
    e = sin_aparato.get("/api/estado").json()["error_conexion"]
    assert "no responde en http://127.0.0.1:1" in e and "Ajustes" in e


@pytest.mark.parametrize("ruta", ["/api/pantalla.png", "/api/pantalla.jpg"])
def test_sin_aparato_la_captura_es_un_503_que_lo_dice(sin_aparato, ruta):
    r = sin_aparato.get(ruta)
    assert r.status_code == 503
    assert "JetKVM" in r.json()["detail"]


def test_la_imagen_que_sustituye_al_directo_es_un_jpeg_que_se_lee():
    import io

    from PIL import Image

    from puente_kvm.app import imagen_sin_video
    img = Image.open(io.BytesIO(imagen_sin_video("sin vídeo del JetKVM: conexión failed")))
    assert img.format == "JPEG" and img.size == (1280, 720)


@pytest.mark.parametrize("ruta", ["/api/lecturas/no-existe-123abc/texto", "/api/cambios/no-existe-123abc/tramos/1.png"])
def test_lo_que_no_existe_es_un_404_no_un_500(entorno, ruta):
    assert entorno[0].get(ruta).status_code == 404


def test_sin_pedir_permisos_solo_si_la_persona_lo_marca(entorno):
    from puente_kvm import terminal

    c, _ = entorno
    assert "--dangerously-skip-permissions" not in terminal.orden_claude()
    # Un valor que no es «sí» de verdad no lo enciende.
    c.post("/api/ajustes", json={"claude": {"saltar_permisos": "true"}}, headers=PERSONA)
    assert config.leer_ajustes()["claude"]["saltar_permisos"] is False
    assert c.post("/api/ajustes", json={"claude": {"saltar_permisos": True}}, headers=PERSONA).status_code == 200
    orden = terminal.orden_claude()
    assert "--dangerously-skip-permissions" in orden and "--permission-mode" not in orden
    # Una regla «ask» del proyecto gana al modo sin permisos (seguía preguntando
    # antes de cada clic): sin la fuente «project», con sus ajustes menos «ask».
    assert "--setting-sources user,local" in orden and "--mcp-config" in orden
    import json
    ajustes = json.loads(terminal.ajustes_sin_preguntar().read_text())
    assert "ask" not in ajustes["permissions"]
    assert "Bash(curl:*)" in ajustes["permissions"]["deny"] and ajustes["hooks"]
    # Y tocar el Mac sigue pidiendo el control: lo comprueba el puente, no Claude Code.
    assert c.post("/api/teclear", json={"texto": "x"}).status_code == 423


def test_una_distribucion_de_teclado_desconocida_no_se_guarda(entorno):
    c, _ = entorno
    perfil = {**config.PERFIL_POR_OMISION, "distribucion": "mac-latam"}
    assert c.post("/api/ajustes", json={"perfil": perfil}, headers=PERSONA).status_code >= 400
    assert config.leer_ajustes()["perfil"]["distribucion"] == "mac-us"


def test_elegir_espanol_cambia_tambien_la_fuente_del_mac_simulado(entorno):
    c, sim = entorno
    perfil = {**config.PERFIL_POR_OMISION, "distribucion": "mac-es"}
    assert c.post("/api/ajustes", json={"perfil": perfil}, headers=PERSONA).status_code == 200
    assert sim.editor.distribucion == "mac-es"


def test_la_rueda_lleva_antes_el_puntero_a_donde_tiene_que_girar(entorno):
    # Aparcado, el puntero quedaba fuera de la hoja y la rueda no movía nada
    # (primera prueba con el JetKVM, 17-nov).
    c, sim = entorno
    c.post("/api/control", json={"accion": "dar"}, headers=PERSONA)
    r = c.post("/api/rueda", json={"pasos": 2, "x": 700, "y": 500})
    assert r.status_code == 200, r.text
    assert sim.puntero == (700, 500)
    assert any(e["tipo"] == "rueda" and "(700, 500)" in e["detalle"] for e in bitacora(c))
