"""El Puente KVM como herramienta opcional del hub (decisión 438).

Lo que se protege, en este orden: que apagado —como viene— no se note en
ninguna pantalla; que el interruptor sólo guarde lo de su lista y sólo desde
el propio hub; que al puente sólo se le haga una pregunta corta, sin dejar
pasar lo que lee del Mac y sin colgar la pantalla si no contesta; y que
abrirlo sólo se ofrezca desde la PC donde corre.
"""

from __future__ import annotations

import json
import os
import re
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from fastapi.testclient import TestClient

import arnes_tmux
from hub import acceso, api, componentes, interfaz, opcionales, puente, recorrido, web

ORIGEN = {"origin": "http://127.0.0.1:8787"}


@pytest.fixture
def cliente():
    return TestClient(web.app)


@pytest.fixture
def encendido():
    opcionales.poner("puente-kvm", True)
    return opcionales.archivo()


# ───────────────────────────── el interruptor ─────────────────────────────


def test_sin_archivo_viene_apagada():
    assert not opcionales.archivo().exists()
    assert opcionales.encendidas() == frozenset()
    assert not opcionales.encendida("puente-kvm")


@pytest.mark.parametrize("contenido", ["{", "[]", '{"encendidas": "puente-kvm"}',
                                       '{"encendidas": ["otra-que-no-existe"]}', ""])
def test_un_archivo_ilegible_o_con_claves_ajenas_no_enciende_nada(contenido):
    opcionales.archivo().write_text(contenido, encoding="utf-8")
    assert opcionales.encendidas() == frozenset()


def test_encender_y_apagar_se_guarda_y_se_lee_de_nuevo():
    assert opcionales.poner("puente-kvm", True) == {"puente-kvm"}
    assert opcionales.encendida("puente-kvm")
    assert json.loads(opcionales.archivo().read_text(encoding="utf-8")) == {"encendidas": ["puente-kvm"]}
    assert opcionales.poner("puente-kvm", False) == frozenset()
    assert not opcionales.encendida("puente-kvm")
    assert not opcionales.archivo().with_name("opcionales.json.tmp").exists()


def test_una_clave_fuera_de_la_lista_no_se_guarda():
    with pytest.raises(ValueError):
        opcionales.poner("../../etc/passwd", True)
    assert not opcionales.archivo().exists()


@pytest.mark.parametrize("contenido", ["{", "[]", '{"encendidas": "puente-kvm"}', '{"encendidas": [3]}', ""])
def test_un_archivo_que_no_se_entiende_no_se_pisa_al_encender(contenido):
    opcionales.archivo().write_text(contenido, encoding="utf-8")
    with pytest.raises(opcionales.Ilegible):
        opcionales.poner("puente-kvm", True)
    assert opcionales.archivo().read_text(encoding="utf-8") == contenido
    assert not opcionales.encendida("puente-kvm")


def test_por_la_web_un_archivo_que_no_se_entiende_se_dice_y_no_se_toca(cliente):
    opcionales.archivo().write_text("{", encoding="utf-8")
    r = cliente.post("/opcionales", data={"clave": "puente-kvm", "encendida": "si"},
                     headers=ORIGEN, follow_redirects=False)
    assert "No%20se%20ha%20cambiado%20nada" in r.headers["location"]
    assert opcionales.archivo().read_text(encoding="utf-8") == "{"


def test_lo_que_esta_version_no_conoce_se_conserva_al_escribir():
    """Otra versión pudo encender una herramienta que ésta no tiene, o guardar
    otra clave: apagar el puente no puede borrárselas."""
    opcionales.archivo().write_text(json.dumps({"encendidas": ["de-otra-version", "puente-kvm"],
                                                "nota": "otra clave"}), encoding="utf-8")
    assert opcionales.poner("puente-kvm", False) == frozenset()
    assert json.loads(opcionales.archivo().read_text(encoding="utf-8")) == {
        "encendidas": ["de-otra-version"], "nota": "otra clave"}


def test_se_lleva_al_disco_antes_de_renombrar(monkeypatch):
    orden = []
    monkeypatch.setattr(opcionales.os, "fsync", lambda fd: orden.append("fsync"))
    real = type(opcionales.archivo()).replace
    monkeypatch.setattr(type(opcionales.archivo()), "replace",
                        lambda self, destino: orden.append("replace") or real(self, destino))
    opcionales.poner("puente-kvm", True)
    assert orden == ["fsync", "replace"]
    assert opcionales.encendida("puente-kvm")


def test_por_la_web_una_clave_fuera_de_la_lista_tampoco_se_guarda(cliente):
    r = cliente.post("/opcionales", data={"clave": "navegante", "encendida": "si"},
                     headers=ORIGEN, follow_redirects=False)
    assert r.status_code == 303 and "aviso=" in r.headers["location"]
    assert not opcionales.archivo().exists()


def test_por_la_web_se_enciende_y_se_vuelve_a_la_guia(cliente):
    r = cliente.post("/opcionales", data={"clave": "puente-kvm", "encendida": "si"},
                     headers=ORIGEN, follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"].startswith("/guia?aviso=") and r.headers["location"].endswith("#opcionales")
    assert opcionales.encendida("puente-kvm")
    cliente.post("/opcionales", data={"clave": "puente-kvm", "encendida": "no"}, headers=ORIGEN)
    assert not opcionales.encendida("puente-kvm")


def test_un_valor_que_no_es_si_ni_no_no_cambia_nada(cliente, encendido):
    cliente.post("/opcionales", data={"clave": "puente-kvm", "encendida": "quizá"}, headers=ORIGEN)
    assert opcionales.encendida("puente-kvm")


@pytest.mark.parametrize("origen", ["https://sitio-malicioso.example", "http://127.0.0.1:5173", "null"])
def test_post_opcionales_sin_origen_valido_se_rechaza(origen, monkeypatch):
    """Por el nombre y el puerto de verdad del hub, sin el `testserver` del
    arnés: así también cuenta la otra web de casa en otro puerto (C-0153)."""
    monkeypatch.setattr(web, "_hosts_de_prueba", lambda: ())
    http = TestClient(web.app, base_url="http://127.0.0.1:8787")
    r = http.post("/opcionales", data={"clave": "puente-kvm", "encendida": "si"},
                  headers={"origin": origen}, follow_redirects=False)
    assert r.status_code == 403 and "otro sitio web" in r.text
    assert not opcionales.archivo().exists()


def test_la_guia_ofrece_encenderla_con_un_formulario_normal(cliente):
    html = cliente.get("/guia").text
    bloque = html[html.index('id="opcionales"'):]
    bloque = bloque[:bloque.index("</section>")]
    assert "Puente KVM: apagado" in bloque and "JetKVM" in bloque
    assert 'action="/opcionales"' in bloque and 'name="encendida" value="si"' in bloque
    assert ">Encender<" in bloque and 'href="/puente"' not in bloque


# ───────────────────────────── apagada, no se nota ─────────────────────────────


def test_apagada_no_sale_en_el_rail_de_siempre_ni_en_el_mapa_de_la_guia(cliente):
    html = cliente.get("/guia").text
    assert 'href="/puente"' not in html
    con = web.conexion()
    try:
        assert api.rail(con)["opcionales"] == []
    finally:
        con.close()
    assert "/puente" not in json.dumps(cliente.get("/api/guia").json()["mapa"])


@pytest.mark.skipif(not interfaz.disponible(), reason="esta instalación no trae la interfaz nueva")
def test_apagada_tampoco_sale_en_la_interfaz_nueva(cliente):
    cliente.cookies.set(interfaz.COOKIE, interfaz.NUEVA)
    for ruta in ("/", "/reuniones", "/guia"):
        assert 'href="/puente"' not in cliente.get(ruta).text, ruta


def test_tecleada_a_mano_dice_que_esta_apagada_y_donde_se_enciende(cliente, monkeypatch):
    monkeypatch.setattr(puente, "estado", lambda *a, **k: pytest.fail("apagado no se le pregunta"))
    r = cliente.get("/puente")
    assert r.status_code == 200
    assert "Apagado en esta instalación" in r.text and 'href="/guia#opcionales"' in r.text
    assert "Abrir el puente" not in r.text and 'action="/componentes/preparar"' not in r.text


#: Las que cambian con la herramienta encendida a propósito.
CAMBIAN = {"/guia", "/puente"}
#: Las notas de una versión dicen lo que trae, también una herramienta opcional
#: (es como se entera quien instala de que existe y de dónde se enciende): ahí
#: su nombre puede salir apagada, pero encendida sigue sin cambiar más que el raíl.
NOTAS = {"/actualizaciones"}
_ENTRADA = re.compile(r'\s*<a href="/puente" class="enlace[^"]*"[^>]*>.*?</a>', re.S)
#: Lo que una pantalla dice de lo encendido porque es su trabajo decirlo: los
#: datos del equipo de /incidencia nombran las herramientas encendidas
#: (C-0468). Esa línea se iguala; el resto de la pantalla, no.
_DICE_LO_ENCENDIDO = re.compile(r"Herramientas opcionales: [^\n<]*")


def _sin_su_entrada(html: str, ruta: str = "") -> str:
    if ruta.startswith("/incidencia"):  # sólo ahí: en otra pantalla taparía un cambio de verdad
        html = _DICE_LO_ENCENDIDO.sub("Herramientas opcionales: …", html)
    return _junto(_ENTRADA.sub("", html))


def _rutas() -> list[str]:
    from test_clasica_identica import DE_DETALLE
    llanas = [r for r in recorrido.rutas_get()
              if "{" not in r and r not in recorrido.NO_SE_VISITAN and not r.startswith("/api/")]
    return [*llanas, *DE_DETALLE]


def _pintar(ruta: str, cookies: dict[str, str] | None = None) -> str:
    http = TestClient(web.app, cookies=cookies or {})
    return http.get(ruta, headers={"accept": "text/html"}, follow_redirects=False).text


def _junto(texto: str) -> str:
    return " ".join(texto.split())


@pytest.fixture
def hub_sembrado(tmp_path, monkeypatch):
    from test_pantallas_navegador import _sembrar
    _sembrar(tmp_path, monkeypatch)
    monkeypatch.setattr(puente, "estado", lambda *a, **k: pytest.fail("sólo /puente le pregunta"))
    yield tmp_path
    arnes_tmux.apagar(os.environ["HUB_TMUX_SOCKET"])


def test_apagada_ninguna_pantalla_lo_nombra_y_encendida_solo_suma_su_entrada_del_rail(hub_sembrado):
    """La promesa de «apagada no se nota», medida pantalla a pantalla: apagada,
    ni un enlace ni su nombre fuera de la Guía y de su propia dirección; y
    encendida, cada pantalla es la de apagada más su entrada en el raíl, y
    nada más. Sin esto, «sale igual que antes» sólo estaría razonado."""
    rutas = _rutas()
    apagadas = {}
    for ruta in rutas:
        html = _pintar(ruta)
        apagadas[ruta] = html
        if ruta not in CAMBIAN | NOTAS:
            assert 'href="/puente"' not in html and "Puente KVM" not in html, ruta
    opcionales.poner("puente-kvm", True)
    vistas = 0
    for ruta in rutas:
        if ruta in CAMBIAN:
            continue
        encendida = _pintar(ruta)
        if "<html" not in encendida:
            continue
        vistas += 1
        assert len(_ENTRADA.findall(encendida)) == 1, f"{ruta}: la entrada del raíl no sale una vez"
        sin_ella = _sin_su_entrada(encendida, ruta)
        if sin_ella != _sin_su_entrada(apagadas[ruta], ruta):
            # Lo que cuenta segundos («hace 4 s») cambia entre peticiones.
            opcionales.poner("puente-kvm", False)
            apagadas[ruta] = _pintar(ruta)
            opcionales.poner("puente-kvm", True)
            sin_ella = _sin_su_entrada(_pintar(ruta), ruta)
        assert sin_ella == _sin_su_entrada(apagadas[ruta], ruta), f"{ruta} cambia más que su entrada del raíl"
    assert vistas >= 25, f"sólo {vistas} páginas: esto no ha recorrido el hub"


# ───────────────────────────── encendida ─────────────────────────────


def test_encendida_sale_en_el_grupo_agentes_del_rail_de_siempre(cliente, encendido):
    html = cliente.get("/reuniones").text
    agentes = html[html.index('<span class="nom">Agentes</span>'):]
    agentes = agentes[:agentes.index("</details>")]
    assert 'href="/puente"' in agentes and "Puente KVM" in agentes


@pytest.mark.parametrize("texto", ["puente", "kvm", "Puente KVM"])
def test_donde_esta_del_secretario_solo_la_encuentra_encendida(texto):
    """«Dónde está» (`hub_buscar`) recorría todas las secciones a pelo:
    apagada, el secretario mandaba a una pantalla que no está en ningún menú."""
    from hub import db
    from hub.secretario import herramientas, memoria
    h = db.conectar()
    db.inicializar(h)
    h.close()
    con = memoria.conectar()
    try:
        buscar = herramientas.todas()["hub_buscar"].funcion
        urls = lambda: [r["url"] for r in buscar(con, {"texto": texto})["resultados"]]  # noqa: E731
        assert "/puente" not in urls()
        opcionales.poner("puente-kvm", True)
        assert "/puente" in urls()
    finally:
        con.close()


def test_el_asistente_lo_ve_encendido_y_sabe_que_esta_apagado(monkeypatch, capsys):
    """`hub componentes` del asistente, ejecutado (`semillas/asistente/bin/hub`)."""
    from importlib.machinery import SourceFileLoader
    from importlib.util import module_from_spec, spec_from_loader
    from pathlib import Path
    ruta = Path(__file__).resolve().parents[1] / "semillas" / "asistente" / "bin" / "hub"
    cargador = SourceFileLoader("hub_cli_de_prueba", str(ruta))
    cli = module_from_spec(spec_from_loader(cargador.name, cargador))
    cargador.exec_module(cli)
    monkeypatch.setattr(puente, "estado", lambda *a, **k: pytest.fail("el asistente no le pregunta"))
    monkeypatch.setattr(cli, "pedir", lambda camino, cuerpo=None: api.componentes())

    cli.cmd_componentes([])
    apagado = capsys.readouterr().out
    assert "navegante:" in apagado and "reuniones:" in apagado
    assert "puente: herramienta opcional apagada; se enciende en Ajustes → Guía" in apagado

    opcionales.poner("puente-kvm", True)
    cli.cmd_componentes([])
    encendido = capsys.readouterr().out
    assert "puente: sin preparar · /puente" in encendido and "El puente está en el clon" in encendido
    assert "hub preparar <navegante|reuniones|puente>" in cli.__doc__


def test_encendida_sale_en_herramientas_de_la_interfaz_nueva():
    from hub import navegacion
    for rail in ({"opcionales": ["puente-kvm"]}, {}):
        herramientas = next(s for s in navegacion.con_cifras(rail) if s["clave"] == "herramientas")
        rutas = [p["ruta"] for p in herramientas["pantallas"]]
        assert ("/puente" in rutas) is bool(rail), rail
    assert navegacion.de_pantalla("puente", "/puente") == "herramientas"


def test_desde_la_pc_con_el_puente_vivo_se_ofrece_abrirlo_en_pestana_aparte(cliente, encendido, monkeypatch):
    monkeypatch.setattr(puente, "estado", lambda *a, **k: {
        "vivo": True, "aparato": "simulador", "conectado": True, "control": "libre", "motivo": None})
    html = cliente.get("/puente").text
    enlace = re.search(r'<a class="boton cta" href="([^"]+)" target="_blank" rel="noopener">Abrir el puente</a>', html)
    assert enlace and enlace.group(1) == puente.direccion()
    assert "Mac simulado" in html and "La persona: Claude no puede tocar el Mac" in html
    assert "<iframe" not in html
    assert html.count('class="boton cta"') == 1


@pytest.fixture
def de_fuera_con_alta():
    """Un aparato dado de alta que entra por el nombre de la red privada."""
    import yaml
    from test_acceso import FUERA, _dar_de_alta
    acceso.archivo().parent.mkdir(parents=True, exist_ok=True)
    acceso.archivo().write_text(yaml.safe_dump({"hosts": [FUERA]}), encoding="utf-8")
    http = TestClient(web.app, base_url=f"https://{FUERA}")
    http.cookies.set(acceso.COOKIE, _dar_de_alta(http, "Móvil"))
    return http


def test_desde_fuera_no_se_ofrece_abrir_ni_se_da_la_direccion(de_fuera_con_alta, encendido, monkeypatch):
    monkeypatch.setattr(puente, "estado", lambda *a, **k: {
        "vivo": True, "aparato": "jetkvm", "conectado": True, "control": "claude", "motivo": None})
    r = de_fuera_con_alta.get("/puente")
    assert r.status_code == 200
    assert "Abrir el puente" not in r.text.replace("tendrás «Abrir el puente»", "")
    assert puente.direccion() not in r.text and "127.0.0.1:" not in r.text
    assert "Se abre en la PC donde corre" in r.text
    # Lo que sí ve: cómo está.
    assert "JetKVM" in r.text and "Claude, porque la persona se lo dio" in r.text
    assert "direccion" not in api.puente(local=False)


def test_un_puente_caido_no_tumba_la_pantalla_y_dice_por_que(cliente, encendido):
    antes = time.monotonic()
    r = cliente.get("/puente")
    assert time.monotonic() - antes < 3
    assert r.status_code == 200
    assert "Caído" in r.text and "no hay nada escuchando en su puerto" in r.text
    assert "Abrir el puente</a>" not in r.text
    assert "Cuando conteste" in r.text
    assert 'id="prep-contesta"' in r.text


def test_sin_preparar_ensena_sus_pasos_y_preparar_con_claude(cliente, encendido):
    html = cliente.get("/puente").text
    assert 'id="preparar"' in html and 'name="nombre" value="puente-kvm"' in html
    assert 'id="prep-componente"' in html and 'id="prep-entorno"' in html


def test_el_rail_y_las_demas_pantallas_no_le_preguntan_al_puente(cliente, encendido, monkeypatch):
    monkeypatch.setattr(puente, "estado", lambda *a, **k: pytest.fail("sólo /puente le pregunta"))
    for ruta in ("/", "/guia", "/reuniones", "/navegante", "/api/componentes"):
        assert cliente.get(ruta).status_code == 200, ruta


def test_el_asistente_ve_los_pasos_del_puente_sin_que_se_le_pregunte(cliente, monkeypatch):
    monkeypatch.setattr(puente, "estado", lambda *a, **k: pytest.fail("sólo /puente le pregunta"))
    c = cliente.get("/api/componentes").json()["puente"]
    assert c["pantalla"] == "/puente" and c["encendida"] is False
    assert [p["id"] for p in c["pasos"]] == ["componente", "entorno", "servicio"]


# ───────────────────────────── qué le falta ─────────────────────────────


def _clon(raiz):
    raiz.mkdir(parents=True)
    (raiz / "pyproject.toml").write_text("[project]\nname = 'puente-kvm'\n")
    (raiz / ".venv").mkdir()
    return raiz


def test_la_variable_manda_y_si_no_se_busca_junto_a_los_proyectos(tmp_path, monkeypatch):
    monkeypatch.setenv("PUENTE_KVM", str(tmp_path / "otro"))
    assert componentes.carpeta("puente-kvm") == tmp_path / "otro"
    monkeypatch.delenv("PUENTE_KVM")
    monkeypatch.setattr(componentes.config, "RAIZ_REPO", tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path / "casa"))
    assert componentes.carpeta("puente-kvm") == tmp_path / "casa" / "projects" / "puente-kvm"


def test_en_el_clon_del_producto_se_usa_la_copia_que_viaja_con_el_hub(tmp_path, monkeypatch):
    """Es el caso de quien instala el hub: el puente viene en `componentes/`.
    Documenta lo que `carpeta` ya hacía desde la 1a (la misma regla que para
    Navegante y Reuniones); no prueba nada nuevo de la 1b."""
    monkeypatch.delenv("PUENTE_KVM")
    monkeypatch.setattr(componentes.config, "RAIZ_REPO", tmp_path)
    copia = _clon(tmp_path / "componentes" / "puente-kvm")
    assert componentes.carpeta("puente-kvm") == copia
    pasos = {p["id"]: p for p in componentes.pasos_puente()}
    assert pasos["componente"]["hecho"] and pasos["entorno"]["hecho"]


def test_los_pasos_mandan_a_su_carpeta_de_trabajo_fuera_del_clon(tmp_path, monkeypatch):
    """Dentro del clon del hub, la sesión del puente cargaría el CLAUDE.md del
    hub y lo leído del Mac quedaría en una carpeta que se vuelve a clonar."""
    from hub import salud
    monkeypatch.setenv("PUENTE_KVM", str(tmp_path / "no-hay"))
    # `conftest` deja la suite sin systemd; luego, uno con el servicio parado.
    sin_systemd = {p["id"]: p for p in componentes.pasos_puente({"vivo": False, "motivo": "x"})}
    monkeypatch.setattr(salud, "estado_servicio", lambda n: {"activo": "inactive", "habilitado": False})
    con_systemd = {p["id"]: p for p in componentes.pasos_puente({"vivo": False, "motivo": "x"})}
    variable = 'PUENTE_TRABAJO="$HOME/puente-trabajo"'
    assert f"{variable} bash scripts/arrancar.sh" in sin_systemd["servicio"]["como"]
    # La unidad que se enseña tiene que ser la que se instala: la variable,
    # delante de las dos órdenes, o `unidad` sale sin su `Environment=`.
    assert f"{variable} bash scripts/servicio.sh unidad" in con_systemd["servicio"]["como"]
    assert f"{variable} bash scripts/servicio.sh instalar" in con_systemd["servicio"]["como"]
    # Sin `--sin-entrar`, `comprobar` entra en el JetKVM y le cierra su web.
    assert "puente-kvm comprobar --sin-entrar" in con_systemd["contesta"]["como"]
    assert "componentes/puente-kvm" in con_systemd["componente"]["como"]
    texto = componentes.ENCARGOS["puente-kvm"]
    assert "INSTALAR.md" in texto and "fuera del clon" in texto
    assert "Si esta carpeta está dentro del clon del hub (componentes/puente-kvm)" in texto
    assert "PUENTE_TRABAJO=… bash scripts/servicio.sh unidad" in texto
    assert "PUENTE_TRABAJO=… bash scripts/servicio.sh instalar" in texto
    assert "PUENTE_TRABAJO=… bash scripts/arrancar.sh" in texto
    assert "usa siempre uv run --frozen" in texto.lower() and "no hagas git pull" in texto
    assert texto.count("puente-kvm comprobar") == texto.count("puente-kvm comprobar --sin-entrar") == 2


def test_con_el_servicio_en_marcha_y_contestando_esta_listo(tmp_path, monkeypatch):
    from hub import salud
    monkeypatch.setenv("PUENTE_KVM", str(_clon(tmp_path / "puente")))
    monkeypatch.setattr(salud, "estado_servicio", lambda n: {"activo": "active", "habilitado": True})
    pasos = componentes.pasos_puente({"vivo": True})
    assert [p["id"] for p in pasos] == ["componente", "entorno", "servicio", "contesta"]
    assert componentes.listo(pasos)
    assert not componentes.listo(componentes.pasos_puente({"vivo": False, "motivo": "no contesta"}))


def test_sin_systemd_el_servicio_no_se_da_por_parado_y_manda_que_conteste(tmp_path, monkeypatch):
    monkeypatch.setenv("PUENTE_KVM", str(_clon(tmp_path / "puente")))
    pasos = {p["id"]: p for p in componentes.pasos_puente({"vivo": True})}
    assert pasos["servicio"]["opcional"] and not pasos["servicio"]["hecho"]
    assert "bash scripts/arrancar.sh" in pasos["servicio"]["como"]
    assert componentes.listo(list(pasos.values()))


def test_el_documento_del_puente_da_las_ordenes_como_hay_que_darlas():
    """`conocimiento/15-puente-kvm.md` es lo que lee quien instala y lo que
    repite el asistente: una orden copiada de ahí tiene que valer tal cual."""
    import re
    from pathlib import Path
    raiz = Path(__file__).resolve().parents[1]
    doc = next(r for r in (raiz / "producto/conocimiento/15-puente-kvm.md",
                           raiz / "conocimiento/15-puente-kvm.md") if r.is_file()).read_text(encoding="utf-8")
    # Sin `--sin-entrar`, `comprobar` entra en el JetKVM y le cierra su web.
    ordenes = re.findall(r"puente-kvm comprobar[^`]*", doc)
    assert ordenes and all("--sin-entrar" in o for o in ordenes), ordenes
    # La unidad que se enseña es la que se instala: la variable, delante de las dos.
    for orden in ("unidad", "instalar"):
        usos = re.findall(rf"`([^`]*scripts/servicio\.sh {orden})`", doc)
        assert usos and all(u.startswith('PUENTE_TRABAJO="$HOME/puente-trabajo" bash') for u in usos), usos
    assert "misma `PUENTE_TRABAJO` delante" in doc          # al relanzar sin systemd
    assert "tailscale serve" in doc and "No la" in doc     # regla 8 y no hacerla slot
    assert "puente-claude" in doc and "interfaz nueva" not in doc
    assert "servicio.sh quitar" in doc and "puente-trabajo" in doc


def test_el_encargo_dice_donde_va_la_contrasena_y_no_la_escribe():
    texto = componentes.ENCARGOS["puente-kvm"]
    assert "uv sync --frozen" in texto and "scripts/servicio.sh instalar" in texto
    assert "~/.config/puente-kvm/entorno" in texto and "NO la escribas" in texto
    assert "ni me la pidas" in texto and "no uses sudo" in texto


def test_preparar_el_puente_abre_su_ventana_sin_enter(cliente, tmp_path, monkeypatch):
    from hub import slots, tmux
    raiz = _clon(tmp_path / "puente")
    monkeypatch.setenv("PUENTE_KVM", str(raiz))
    abiertas = []
    monkeypatch.setattr(slots, "abrir_en", lambda ruta, nombre, sesion, texto: abiertas.append(
        (ruta, nombre, texto)) or "%9")
    monkeypatch.setattr(tmux, "listar_paneles", lambda: [{"pane_id": "%9", "window_idx": 2}])
    r = cliente.post("/componentes/preparar", data={"nombre": "puente"}, headers=ORIGEN,
                     follow_redirects=False)
    assert r.headers["location"] == "/trabajo?session=hub&ventana=2"
    ruta, nombre, texto = abiertas[0]
    assert ruta == str(raiz) and nombre == "preparar-puente-kvm" and not texto.endswith("\n")


def test_si_preparar_el_puente_falla_se_vuelve_a_su_pantalla(cliente):
    r = cliente.post("/componentes/preparar", data={"nombre": "puente-kvm"}, headers=ORIGEN,
                     follow_redirects=False)
    assert r.headers["location"].startswith("/puente?aviso=")


# ───────────────────────────── la pregunta al puente ─────────────────────────────


class _Puente(BaseHTTPRequestHandler):
    """Un puente falso que contesta su `/api/estado` con lo que diga la prueba."""

    respuesta: bytes = b"{}"
    estado_http: int = 200
    vistos: list = []

    def do_GET(self):  # noqa: N802
        type(self).vistos.append((self.command, self.path, self.headers.get("Host")))
        self.send_response(self.estado_http)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(self.respuesta)))
        self.end_headers()
        self.wfile.write(self.respuesta)

    def do_POST(self):  # noqa: N802
        type(self).vistos.append((self.command, self.path, self.headers.get("Host")))
        self.send_response(405)
        self.end_headers()

    def log_message(self, *a):
        pass


@pytest.fixture
def puente_falso(monkeypatch):
    def montar(datos, estado_http=200):
        manejador = type("P", (_Puente,), {"respuesta": json.dumps(datos).encode(),
                                           "estado_http": estado_http, "vistos": []})
        servidor = ThreadingHTTPServer(("127.0.0.1", 0), manejador)
        threading.Thread(target=servidor.serve_forever, daemon=True).start()
        servidores.append(servidor)
        monkeypatch.setenv("PUENTE_PUERTO", str(servidor.server_address[1]))
        return manejador
    servidores: list = []
    yield montar
    for s in servidores:
        s.shutdown()
        s.server_close()


#: Lo que trae el `/api/estado` de verdad (medido el 13-nov con el Mac
#: simulado), con lo laboral marcado para buscarlo en la salida.
ESTADO_DE_VERDAD = {
    "control": {"modo": "libre", "desde": 1794253327.18, "motivo": "terminó de escribir: SECRETO-CONTROL"},
    "dispositivo": {"tipo": "simulador", "conectado": True, "resolucion": "1920×1080", "lineas": 2017,
                    "huella_base": "E1144433", "nota": "Mac simulado: SECRETO-NOTA"},
    "claude": {"estado": "trabajando", "skill": "leer", "herramienta": "puente: SECRETO-HERRAMIENTA"},
    "error_conexion": "", "tarea": "leer el procedimiento SECRETO-TAREA", "progreso": "página 3",
    "perfil": {"nombre": "DBeaver (Mac)"}, "t": 1794616612.0,
    "lecturas": [{"id": "l1", "nombre": "SECRETO-LECTURA", "paginas": 12}],
    "cambios": [{"id": "c1", "descripcion": "SECRETO-CAMBIO", "estado": "propuesto", "tramos": 2}],
}


def test_del_estado_del_puente_solo_salen_las_claves_de_la_lista(puente_falso):
    falso = puente_falso(ESTADO_DE_VERDAD)
    e = puente.estado()
    assert e == {"vivo": True, "aparato": "simulador", "conectado": True, "control": "libre", "motivo": None}
    assert set(e) <= set(puente.CLAVES)
    assert "SECRETO" not in json.dumps(e)
    assert falso.vistos == [("GET", "/api/estado", f"127.0.0.1:{puente.puerto()}")]


def test_lo_que_no_esta_en_sus_listas_no_pasa(puente_falso):
    puente_falso({"dispositivo": {"tipo": "<script>", "conectado": "sí"},
                  "control": {"modo": "SECRETO"}, "version": "0.2.0 SECRETO"})
    e = puente.estado()
    assert e["aparato"] is None and e["conectado"] is None and e["control"] is None
    assert "version" not in e
    puente_falso({"version": "0.2.0", "dispositivo": {"tipo": "jetkvm", "conectado": True}})
    assert puente.estado()["version"] == "0.2.0"


def test_sin_conectar_al_aparato_dice_por_que_recortado(puente_falso):
    puente_falso({"dispositivo": {"tipo": "jetkvm", "conectado": False,
                                  "motivo": "otra sesión\x1b[2J abrió el JetKVM " + "x" * 400}})
    e = puente.estado()
    assert e["vivo"] and e["conectado"] is False
    assert e["motivo"].startswith("otra sesión [2J abrió el JetKVM") and len(e["motivo"]) <= puente.MOTIVO_MAX
    assert "\x1b" not in e["motivo"]


def test_el_fallo_al_conectar_manda_sobre_el_sin_conectar_del_aparato(puente_falso):
    """Con un JetKVM real, `dispositivo.motivo` vale «sin conectar» mientras
    no conecta: tapaba el fallo, que es lo que explica algo."""
    puente_falso({"dispositivo": {"tipo": "jetkvm", "conectado": False, "motivo": "sin conectar"},
                  "error_conexion": "ClientConnectorError: no llega a 192.168.1.40"})
    assert puente.estado()["motivo"] == "ClientConnectorError: no llega a 192.168.1.40"
    puente_falso({"dispositivo": {"tipo": "jetkvm", "conectado": False, "motivo": "sin conectar"},
                  "error_conexion": ""})
    assert puente.estado()["motivo"] == "sin conectar"


def test_desde_fuera_por_que_no_llega_al_aparato_va_sin_detalle(cliente, encendido, puente_falso,
                                                                de_fuera_con_alta):
    puente_falso({"dispositivo": {"tipo": "jetkvm", "conectado": False},
                  "error_conexion": "ClientConnectorError: no llega a 192.168.1.40"})
    de_fuera = de_fuera_con_alta.get("/puente").text
    assert "192.168.1.40" not in de_fuera and puente.SIN_APARATO_DESDE_FUERA in de_fuera
    assert api.puente(local=False)["estado"]["motivo"] == puente.SIN_APARATO_DESDE_FUERA
    assert "192.168.1.40" in cliente.get("/puente").text


@pytest.mark.parametrize("version", [None, "0.2.0"])
def test_la_version_solo_se_pinta_si_el_puente_la_da(cliente, encendido, puente_falso, version):
    datos = {"dispositivo": {"tipo": "simulador", "conectado": True}, "control": {"modo": "libre"}}
    puente_falso({**datos, "version": version} if version else datos)
    html = cliente.get("/puente").text
    assert ("<dt>Versión</dt>" in html) is bool(version)
    if version:
        assert f"<dd>{version}</dd>" in html


def test_api_puente_no_lleva_la_carpeta(encendido):
    assert "carpeta" not in api.puente(local=True)


def test_un_puente_que_contesta_con_error_no_esta_vivo(puente_falso):
    puente_falso({"detail": "nombre de host no admitido"}, estado_http=403)
    e = puente.estado()
    assert e["vivo"] is False and "403" in e["motivo"]


def test_un_puente_caido_contesta_en_menos_de_un_segundo():
    antes = time.monotonic()
    e = puente.estado()
    assert time.monotonic() - antes < 1
    assert e == {"vivo": False, "aparato": None, "conectado": None, "control": None,
                 "motivo": "no hay nada escuchando en su puerto"}


def test_un_puente_colgado_no_hace_esperar_mas_de_un_segundo(monkeypatch):
    """Acepta la conexión y no contesta nunca."""
    mudo = socket.socket()
    mudo.bind(("127.0.0.1", 0))
    mudo.listen(4)
    monkeypatch.setenv("PUENTE_PUERTO", str(mudo.getsockname()[1]))
    try:
        antes = time.monotonic()
        e = puente.estado()
        assert time.monotonic() - antes < 1
        assert e["vivo"] is False and e["motivo"] == "no contestó a tiempo"
    finally:
        mudo.close()


@pytest.fixture
def puente_a_mano(monkeypatch):
    """Un puente de un solo uso que contesta lo que diga la prueba, byte a
    byte si hace falta: `montar(primero, goteo)` manda `primero` y luego
    `goteo` de uno en uno, cada décima, hasta que se cierra."""
    servidor = socket.socket()
    servidor.bind(("127.0.0.1", 0))
    servidor.listen(1)
    monkeypatch.setenv("PUENTE_PUERTO", str(servidor.getsockname()[1]))
    parar = threading.Event()

    def montar(primero: bytes, goteo: bytes = b"", cerrar: bool = True):
        def contestar():
            con, _ = servidor.accept()
            with con:
                con.recv(4096)
                con.sendall(primero)
                for byte in goteo:
                    if parar.is_set():
                        return
                    try:
                        con.sendall(bytes([byte]))
                    except OSError:
                        return
                    time.sleep(0.1)
                if not cerrar:
                    parar.wait(5)
        threading.Thread(target=contestar, daemon=True).start()

    yield montar
    parar.set()
    servidor.close()


@pytest.mark.parametrize("primero, goteo", [
    # El cuerpo, de byte en byte.
    (b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: 5000\r\n\r\n{", b" " * 100),
    # Las cabeceras, de byte en byte: con `http.client` esto tardaba 6 s (medido).
    (b"HTTP/1.1 200 OK\r\n", b"X-Algo: " + b"a" * 100),
], ids=["cuerpo", "cabeceras"])
def test_un_puente_que_gotea_se_corta_al_plazo_total_y_no_por_lectura(puente_a_mano, primero, goteo):
    puente_a_mano(primero, goteo)
    antes = time.monotonic()
    e = puente.estado()
    assert time.monotonic() - antes < 1
    assert e["vivo"] is False and e["motivo"] == "no contestó a tiempo"


def test_con_su_largo_entero_no_espera_a_que_cierre(puente_a_mano):
    """Un servidor que deja la conexión abierta tras contestar no puede dar
    «no contestó a tiempo»: con el `Content-Length` cumplido, ya está."""
    cuerpo = json.dumps({"dispositivo": {"tipo": "simulador", "conectado": True}}).encode()
    puente_a_mano(b"HTTP/1.1 200 OK\r\nContent-Length: %d\r\n\r\n" % len(cuerpo) + cuerpo, cerrar=False)
    antes = time.monotonic()
    e = puente.estado()
    assert time.monotonic() - antes < 0.5
    assert e["vivo"] and e["aparato"] == "simulador"


@pytest.mark.parametrize("respuesta", [
    b"no soy http\r\n\r\n{}",
    b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n2\r\n{}\r\n0\r\n\r\n",
    b"HTTP/1.1 200 OK\r\nContent-Length: 50\r\n\r\n{}",   # cierra con el cuerpo a medias
    b"HTTP/1.1 200 OK\r\nContent-",                      # cierra a media cabecera
])
def test_lo_que_no_es_una_respuesta_entera_no_se_da_por_su_estado(puente_a_mano, respuesta):
    puente_a_mano(respuesta)
    e = puente.estado()
    assert e["vivo"] is False and e["motivo"] == "contesta algo que no es su estado"


@pytest.mark.parametrize("valor, esperado", [("8800", 8800), ("", 8794), ("no", 8794), ("70000", 8794)])
def test_el_puerto_sale_de_su_variable_y_uno_raro_vale_el_de_siempre(monkeypatch, valor, esperado):
    monkeypatch.setenv("PUENTE_PUERTO", valor)
    assert puente.puerto() == esperado
    assert puente.direccion() == f"http://127.0.0.1:{esperado}"
