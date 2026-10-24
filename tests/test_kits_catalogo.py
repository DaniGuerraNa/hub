"""El catálogo de Inventario → Kits: qué hay, qué tiene esta máquina y un botón por paso.

Es la pantalla de quien USA kits, no de quien los hace: tiene que poder ver
cuáles le faltan e instalarlos sin abrir una terminal, y aplicarlos a un
proyecto como ya lo hacía el asistente (decisión 287).
"""

from __future__ import annotations

import textwrap
from urllib.parse import urlparse

import pytest
import yaml
from fastapi.testclient import TestClient

from hub import agentes, api, config, kits, slots, web

ORIGEN = {"origin": "http://127.0.0.1:8787"}


@pytest.fixture
def catalogo_propio():
    """Dos kits más en el catálogo del usuario: uno de proyecto, otro de máquina."""
    (config.HUB_HOME / "kits.yml").write_text(yaml.safe_dump({"kits": [
        {"id": "demo", "nombre": "Demo", "version": "1.0", "origen": "https://ejemplo.invalid/demo.git",
         "descripcion": "Un kit de proyecto"},
        {"id": "herramienta", "nombre": "Herramienta", "version": "1.0",
         "origen": "https://ejemplo.invalid/herramienta.git"},
    ]}), encoding="utf-8")


def _instalado(id_kit, version, de_maquina=False):
    raiz = kits.ruta_de(id_kit, version)
    raiz.mkdir(parents=True)
    if de_maquina:
        (raiz / "instalar.sh").write_text("echo hola\n")
        cuerpo = f'id: {id_kit}\nversion: "{version}"\naplica: []\ninstalar: instalar.sh\n'
    else:
        (raiz / "guia.md").write_text("la guía\n")
        cuerpo = textwrap.dedent(f"""
            id: {id_kit}
            version: "{version}"
            aplica:
              - origen: guia.md
                destino: docs/guia.md
                modo: apuntador
        """)
    (raiz / "kit.yml").write_text(cuerpo, encoding="utf-8")
    return raiz


@pytest.fixture
def cliente(tmp_path, monkeypatch):
    from hub import db

    def conexion():
        c = db.conectar(tmp_path / "hub.db")
        db.inicializar(c)
        return c

    monkeypatch.setattr(web, "conexion", conexion)
    c = conexion()
    c.execute("INSERT INTO proyecto (id, nombre, asiento, estado_ref) VALUES ('app','App','/tmp/app','ESTADO.md')")
    c.commit()
    c.close()
    return TestClient(web.app)


# ───────────────────────────── qué tiene esta máquina ─────────────────────────────


def _estado(id_kit):
    return next(k for k in api.catalogo_kits() if k["id"] == id_kit)


def test_un_kit_sin_descargar_sale_sin_instalar(catalogo_propio):
    assert _estado("demo")["estado"] == "sin-instalar"


def test_un_kit_descargado_en_su_version_sale_instalado(catalogo_propio):
    _instalado("demo", "1.0")
    assert _estado("demo")["estado"] == "instalado"


def test_otra_version_en_disco_no_es_la_del_catalogo(catalogo_propio):
    """Tener la 0.9 no es tener la 1.0: el botón ofrece instalar la nueva."""
    _instalado("demo", "0.9")
    e = _estado("demo")
    assert e["estado"] == "otra-version" and e["instalada"] == "0.9"


def test_la_base_viene_con_el_hub_y_no_se_instala():
    assert _estado("base")["estado"] == "con-el-hub"


def test_un_kit_de_maquina_dice_donde_esta_su_instalador(catalogo_propio):
    raiz = _instalado("herramienta", "1.0", de_maquina=True)
    e = _estado("herramienta")
    assert e["de_maquina"] and e["instalador"] == str(raiz / "instalar.sh")


# ───────────────────────────── la pantalla ─────────────────────────────


def test_el_catalogo_ofrece_instalar_lo_que_falta_y_aplicar_lo_que_hay(cliente, catalogo_propio):
    _instalado("herramienta", "1.0", de_maquina=True)
    html = cliente.get("/inventario?ver=kits").text
    assert 'id="catalogo"' in html
    assert 'action="/kits/instalar"' in html and 'value="demo"' in html
    assert 'action="/kits/instalar-en-maquina"' in html


def test_un_kit_instalado_se_aplica_eligiendo_el_proyecto(cliente, catalogo_propio):
    _instalado("demo", "1.0")
    html = cliente.get("/inventario?ver=kits").text
    assert 'action="/kits/aplicar"' in html and '<option value="app">App</option>' in html


def test_instalar_clona_la_version_del_catalogo(cliente, catalogo_propio, monkeypatch):
    pedidos = []
    monkeypatch.setattr(kits, "instalar", lambda i, v, o: pedidos.append((i, v, o)) or kits.ruta_de(i, v))
    r = cliente.post("/kits/instalar", data={"id": "demo"}, headers=ORIGEN, follow_redirects=False)
    assert r.status_code == 303
    assert pedidos == [("demo", "1.0", "https://ejemplo.invalid/demo.git")]


def test_instalar_algo_que_no_esta_en_el_catalogo_no_clona_nada(cliente, monkeypatch):
    monkeypatch.setattr(kits, "instalar", lambda *a: pytest.fail("no debía clonar"))
    r = cliente.post("/kits/instalar", data={"id": "../../etc"}, headers=ORIGEN, follow_redirects=False)
    assert r.status_code == 303


def test_aplicar_prepara_la_ventana_del_proyecto_y_lleva_a_ella(cliente, catalogo_propio, monkeypatch):
    llamadas = []
    monkeypatch.setattr(agentes, "preparar_kits", lambda con, p, ids: llamadas.append((p, ids))
                        or {"session": "app", "ventana": 3, "kits": ids, "ruta": "/tmp/app"})
    r = cliente.post("/kits/aplicar", data={"kit": "demo", "proyecto": "app"},
                     headers=ORIGEN, follow_redirects=False)
    assert llamadas == [("app", ["demo"])]
    assert r.headers["location"] == "/trabajo?session=app&ventana=3"


def test_el_instalador_de_maquina_se_escribe_sin_lanzar(cliente, catalogo_propio, monkeypatch):
    """Es un script de otro repositorio: lo lanza la persona, nunca el hub."""
    raiz = _instalado("herramienta", "1.0", de_maquina=True)
    abiertas = []
    monkeypatch.setattr(slots, "abrir_en", lambda ruta, nombre, sesion, texto: abiertas.append(texto) or "%1")
    cliente.post("/kits/instalar-en-maquina", data={"id": "herramienta"}, headers=ORIGEN,
                 follow_redirects=False)
    assert abiertas == [f"bash {raiz / 'instalar.sh'}"]


# ───────────────────────────── el catálogo publicado ─────────────────────────────


def test_el_catalogo_publicado_solo_apunta_a_repos_que_cualquiera_puede_clonar():
    """Una carpeta propia como `origen` funciona en la máquina del dueño y en la
    de nadie más: el kit saldría en el catálogo y fallaría al instalarlo."""
    datos = yaml.safe_load((config.RAIZ_REPO / "kits.yml").read_text(encoding="utf-8"))
    for k in datos["kits"]:
        if k["origen"] == "interno":
            continue
        assert urlparse(k["origen"]).scheme == "https", k
