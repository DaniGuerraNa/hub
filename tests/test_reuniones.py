"""Reuniones: la orden de grabar, el latido del agente y lo procesado.

El agente de Windows y el procesado tienen sus propias pruebas en
`~/projects/reuniones` (con audio y GPU de verdad). Aquí, la frontera del hub:
qué orden sale de un formulario y qué se enseña de una carpeta."""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from hub import api, db, reuniones, web

INVENTARIO = {"agente": "0.1.0", "equipo": "DESKTOP",
              "monitores": [{"n": 1, "ancho": 1920, "alto": 1080}, {"n": 3, "ancho": 1920, "alto": 1080}],
              "microfonos": [{"n": 49, "nombre": "Micrófono (HyperX Quadcast)"}],
              "apps": [{"nombre": "ms-teams.exe", "pid": 1234, "activa": True},
                       {"nombre": "Spotify.exe", "pid": 99, "activa": False}]}


@pytest.fixture
def raiz(tmp_path, monkeypatch):
    r = tmp_path / "grabaciones"
    r.mkdir()
    monkeypatch.setenv("REUNIONES_RAIZ", str(r))
    lanzados = []
    monkeypatch.setattr(reuniones, "lanzar_procesado", lambda id_: lanzados.append(id_))
    return r, lanzados


@pytest.fixture
def cliente(tmp_path, monkeypatch):
    def conexion():
        c = db.conectar(tmp_path / "hub.db")
        db.inicializar(c)
        return c
    monkeypatch.setattr(web, "conexion", conexion)
    llave = reuniones.conectar_agente()["llave"]
    return TestClient(web.app, headers={reuniones.CABECERA: llave})


@pytest.fixture
def sin_llave(tmp_path, monkeypatch):
    def conexion():
        c = db.conectar(tmp_path / "hub.db")
        db.inicializar(c)
        return c
    monkeypatch.setattr(web, "conexion", conexion)
    return TestClient(web.app)


def test_sin_orden_el_agente_recibe_no_grabar_y_su_inventario_queda(cliente, raiz):
    r = cliente.post("/api/reuniones/latido", json=INVENTARIO).json()
    assert r["orden"]["grabar"] is False
    a = reuniones.agente()
    assert a["vivo"] and [m["n"] for m in a["monitores"]] == [1, 3]


def test_un_latido_sin_inventario_no_borra_el_anterior(cliente, raiz):
    cliente.post("/api/reuniones/latido", json=INVENTARIO)
    cliente.post("/api/reuniones/latido", json={"agente": "0.1.0", "grabando": None})
    assert [x["nombre"] for x in reuniones.agente()["apps"]] == ["ms-teams.exe", "Spotify.exe"]


def test_grabar_manda_al_agente_el_monitor_la_app_con_su_pid_y_el_micro(cliente, raiz):
    cliente.post("/api/reuniones/latido", json=INVENTARIO)
    cliente.post("/reuniones/accion", data={"que": "grabar", "monitor": "3", "app": "ms-teams.exe",
                                            "micro": "49", "titulo": "Seguimiento"})
    o = cliente.post("/api/reuniones/latido", json={"agente": "0.1.0"}).json()["orden"]
    assert o["grabar"] and o["monitor"] == 3 and o["app"] == "ms-teams.exe" and o["pid"] == 1234
    assert o["micro"] == "49" and o["titulo"] == "Seguimiento"
    assert reuniones.ID.match(o["id"])


def test_solo_se_puede_elegir_lo_que_el_agente_dijo_que_ve(cliente, raiz):
    from urllib.parse import unquote
    cliente.post("/api/reuniones/latido", json=INVENTARIO)
    for datos, motivo in (({"monitor": "2"}, "monitor"), ({"monitor": "1", "app": "calc.exe"}, "aplicación"),
                          ({"monitor": "1", "micro": "7"}, "micrófono")):
        r = cliente.post("/reuniones/accion", data={"que": "grabar", **datos}, follow_redirects=False)
        assert motivo in unquote(r.headers["location"])
    assert reuniones.orden()["grabar"] is False


def test_sin_agente_vivo_no_se_da_la_orden(cliente, raiz):
    from urllib.parse import unquote
    cliente.post("/api/reuniones/latido", json=INVENTARIO)
    l = json.loads((reuniones.carpeta() / "latido.json").read_text())
    l["t"] = time.time() - 60
    (reuniones.carpeta() / "latido.json").write_text(json.dumps(l))
    r = cliente.post("/reuniones/accion", data={"que": "grabar", "monitor": "1"}, follow_redirects=False)
    assert "no está conectado" in unquote(r.headers["location"])


def test_cuando_el_agente_avisa_de_que_termino_se_lanza_su_procesado(cliente, raiz):
    _, lanzados = raiz
    cliente.post("/api/reuniones/latido", json={**INVENTARIO, "terminada": "20261020-121303"})
    cliente.post("/api/reuniones/latido", json={**INVENTARIO, "terminada": "../../etc"})
    assert lanzados == ["20261020-121303"]


def test_una_miniatura_que_no_es_jpeg_o_de_un_monitor_raro_se_rechaza(cliente, raiz):
    assert cliente.post("/api/reuniones/miniatura/1", content=b"\xff\xd8\xff fake").status_code == 200
    assert cliente.post("/api/reuniones/miniatura/1", content=b"<svg>").status_code == 400
    assert cliente.post("/api/reuniones/miniatura/12", content=b"\xff\xd8").status_code == 400
    assert cliente.get("/reuniones/miniatura/1").status_code == 200


def test_la_reunion_intercala_capturas_y_lo_dicho_por_su_segundo(cliente, raiz):
    r, _ = raiz
    d = r / "20261020-090000"
    (d / "fotos").mkdir(parents=True)
    (d / "fotos" / "000004.jpg").write_bytes(b"\xff\xd8")
    (d / "meta.json").write_text(json.dumps({"id": d.name, "inicio": 0, "fin": 600,
                                             "proceso": {"nombre": "ms-teams.exe"}}))
    (d / "transcripcion.json").write_text(json.dumps([
        {"ini": 1.0, "fin": 3, "texto": "Hola", "quien": "Reunión"},
        {"ini": 4.0, "fin": 6, "texto": "Mirad esto", "quien": "Yo"}]))
    (d / "resumen.json").write_text(json.dumps({"titulo": "Seguimiento", "resumen": "Breve.",
                                                "tareas": [{"quien": "Yo", "que": "Revisar el despliegue"}]}))
    (d / "procesado.json").write_text(json.dumps({"estado": "hecho"}))
    linea = api.reunion(d.name)["linea"]
    assert [e.get("texto") or f"foto {e['foto']}" for e in linea] == ["Hola", "foto 4", "Mirad esto"]
    html = cliente.get(f"/reuniones/{d.name}").text
    assert "Revisar el despliegue" in html and "Seguimiento" in html
    # La referencia para pegarla en una sesión: las rutas, y nunca el audio.
    assert f"Resumen: {d}/resumen.md" in html and f"{d}/transcripcion.md" in html
    assert ".wav" not in html
    lista = cliente.get("/reuniones").text
    assert "Seguimiento" in lista and "10 min" in lista and "1 tarea<" in lista
    assert cliente.get(f"/reuniones/{d.name}/foto/4").status_code == 200
    assert cliente.get(f"/reuniones/{d.name}/foto/5").status_code == 404
    assert cliente.get("/reuniones/..%2F..%2Fetc").status_code in (303, 404)


def test_dice_cuantas_quedan_sin_comprimir_y_comprime_solo_cuando_se_pide(cliente, raiz, monkeypatch):
    r, _ = raiz
    comprimidas = []
    monkeypatch.setattr(reuniones, "lanzar_compresion", lambda ids: comprimidas.append(list(ids)))
    for id_, fin, wav in (("20261020-090000", 600, True), ("20261020-100000", 600, False),
                          ("20261020-110000", None, True)):
        d = r / id_
        d.mkdir()
        (d / "meta.json").write_text(json.dumps({"id": id_, "inicio": 0, "fin": fin}))
        if wav:
            (d / "reunion.wav").write_bytes(b"\0" * 2_500_000)
        else:
            (d / "reunion.opus").write_bytes(b"\0" * 1000)
    datos = api.reuniones()
    assert datos["sin_comprimir"]["n"] == 1          # la que se está grabando no cuenta
    assert comprimidas == []                          # mirar no comprime nada
    html = cliente.get("/reuniones").text
    assert "1 sin comprimir" in html and "sin comprimir · 3 MB" in html
    cliente.post("/reuniones/accion", data={"que": "comprimir-todas"})
    assert comprimidas == [["20261020-090000"]]
    cliente.post("/reuniones/accion", data={"que": "comprimir", "id": "20261020-090000"})
    assert comprimidas[-1] == ["20261020-090000"]
    assert "Comprimir audio" in cliente.get("/reuniones/20261020-090000").text
    assert "Comprimir audio" not in cliente.get("/reuniones/20261020-100000").text


def test_lo_que_se_esta_procesando_ni_cuenta_ni_se_comprime(cliente, raiz):
    r, _ = raiz
    d = r / "20261020-090000"
    d.mkdir()
    (d / "meta.json").write_text(json.dumps({"id": d.name, "inicio": 0, "fin": 60}))
    (d / "procesado.json").write_text(json.dumps({"estado": "procesando"}))
    (d / "reunion.wav").write_bytes(b"\0" * 5000)
    assert api.reuniones()["sin_comprimir"]["n"] == 0
    assert reuniones.sin_comprimir() == []
    with pytest.raises(ValueError, match="procesando"):
        reuniones.lanzar_compresion([d.name])
    assert "Comprimir audio" not in cliente.get(f"/reuniones/{d.name}").text


# ── la llave del agente (decisión 280) ──


def test_sin_llave_el_latido_se_rechaza_y_no_se_guarda_nada(sin_llave, raiz):
    r = sin_llave.post("/api/reuniones/latido", json=INVENTARIO)
    assert r.status_code == 401
    assert not (reuniones.carpeta() / "latido.json").exists()


def test_con_una_llave_que_no_vale_tampoco_pasa_aunque_exista_otra(sin_llave, raiz):
    reuniones.conectar_agente()
    r = sin_llave.post("/api/reuniones/latido", json=INVENTARIO, headers={reuniones.CABECERA: "inventada"})
    assert r.status_code == 401
    assert sin_llave.post("/api/reuniones/miniatura/1", content=b"\xff\xd8",
                          headers={reuniones.CABECERA: "inventada"}).status_code == 401


def test_con_la_llave_buena_el_latido_pasa(sin_llave, raiz):
    llave = reuniones.conectar_agente()["llave"]
    r = sin_llave.post("/api/reuniones/latido", json=INVENTARIO, headers={reuniones.CABECERA: llave})
    assert r.status_code == 200 and r.json()["orden"]["grabar"] is False


def test_un_host_localhost_forjado_no_basta_sin_llave(sin_llave, raiz):
    reuniones.conectar_agente()
    for host in ("localhost", "127.0.0.1:8787", None):
        cab = {"host": host} if host else {}
        assert sin_llave.post("/api/reuniones/latido", json={**INVENTARIO, "terminada": "20261020-121303"},
                              headers=cab).status_code == 401
    assert raiz[1] == []                             # ni se lanzó el procesado


def test_una_llave_nueva_anula_la_anterior(sin_llave, raiz):
    vieja = reuniones.conectar_agente()["llave"]
    nueva = reuniones.conectar_agente()["llave"]
    assert not reuniones.llave_valida(vieja) and reuniones.llave_valida(nueva)


def test_el_hub_guarda_la_huella_y_no_la_llave(sin_llave, raiz):
    llave = reuniones.conectar_agente()["llave"]
    for f in reuniones.carpeta().rglob("*"):
        if f.is_file():
            assert llave not in f.read_text(errors="ignore")


def test_conectar_escribe_la_llave_donde_la_lee_el_agente_si_se_ve_su_carpeta(sin_llave, raiz, tmp_path, monkeypatch):
    agente = tmp_path / "agente"
    agente.mkdir()
    monkeypatch.setenv("REUNIONES_AGENTE", str(agente))
    r = sin_llave.post("/reuniones/conectar")
    assert r.status_code == 200
    llave = (agente / "token").read_text().strip()
    assert reuniones.llave_valida(llave)
    assert llave not in r.text                       # escrita: no hace falta enseñarla
    assert "Escrita en" in r.text


def test_sin_carpeta_del_agente_la_llave_se_ensena_una_sola_vez(sin_llave, raiz):
    r = sin_llave.post("/reuniones/conectar")
    llave = next(l.split('value="')[1].split('"')[0] for l in r.text.splitlines() if 'class="llave"' in l)
    assert reuniones.llave_valida(llave)
    assert llave not in sin_llave.get("/reuniones").text
    assert llave not in r.headers.get("location", "")


def test_la_pantalla_pide_conectar_mientras_no_hay_llave_y_avisa_del_rechazo(sin_llave, raiz):
    assert "Generar la llave" in sin_llave.get("/reuniones").text
    reuniones.conectar_agente()
    sin_llave.post("/api/reuniones/latido", json=INVENTARIO, headers={reuniones.CABECERA: "vieja"})
    t = sin_llave.get("/reuniones").text
    assert "Generar la llave" not in t and "sin una llave que valga" in t and "Cambiar la llave" in t


def test_conectar_desde_otro_sitio_web_se_rechaza(sin_llave, raiz):
    r = sin_llave.post("/reuniones/conectar", headers={"origin": "https://malo.example"})
    assert r.status_code == 403 and not reuniones.hay_llave()


def test_desde_fuera_las_fotos_y_las_miniaturas_exigen_aparato_dado_de_alta(sin_llave, raiz):
    import yaml
    from hub import acceso
    ruta = acceso.archivo()
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(yaml.safe_dump({"hosts": ["desktop.tail1a2b3c.ts.net"]}), encoding="utf-8")
    fuera = TestClient(web.app, base_url="https://desktop.tail1a2b3c.ts.net")
    for url in ("/reuniones", "/reuniones/miniatura/1", "/reuniones/20261020-121303/foto/3"):
        assert fuera.get(url).status_code == 403, url
    assert fuera.post("/reuniones/conectar").status_code == 403
    assert not reuniones.hay_llave()



def test_el_boton_de_copiar_la_ruta_la_copia_y_lo_dice(tmp_path):
    """Ejecutado (regla dura 11): con el portapapeles moderno y, si lo niega,
    con el de siempre."""
    import shutil, subprocess
    from jinja2 import Environment, FileSystemLoader
    node = shutil.which("node")
    if not node:
        pytest.skip("node no disponible")
    plantillas = Path(web.__file__).parent / "templates"
    guion = re.findall(r"<script>\s*(.*?)\s*</script>",
                       (plantillas / "reunion.html").read_text(), re.S)[-1]
    arnes = """
      const nodos = {};
      const el = (id) => nodos[id] ||= { id, dataset: { texto: 'Resumen: /r/resumen.md' },
        textContent: '', _f: {}, addEventListener(ev, f) { this._f[ev] = f; },
        setAttribute(){}, style: {}, select(){}, remove(){} };
      global.document = { getElementById: el, createElement: () => el('textarea'),
        body: { appendChild(){} }, execCommand: () => true };
      const copiado = [];
      Object.defineProperty(globalThis, 'navigator', { configurable: true, value: {
        clipboard: { writeText: (t) => globalThis.NIEGA ? Promise.reject(new Error('no'))
                                                         : (copiado.push(t), Promise.resolve()) } } });
      GUION
      (async () => {
        await nodos['copiar-ruta']._f.click();
        const primero = nodos['copiada'].textContent;
        globalThis.NIEGA = true;
        await nodos['copiar-ruta']._f.click();
        console.log(JSON.stringify({ copiado, primero, segundo: nodos['copiada'].textContent }));
      })();
    """.replace("GUION", guion)
    archivo = tmp_path / "copiar.js"
    archivo.write_text(arnes)
    salida = subprocess.run([node, str(archivo)], capture_output=True, text=True, timeout=30)
    assert salida.returncode == 0, salida.stderr
    r = json.loads(salida.stdout.strip().splitlines()[-1])
    assert r["copiado"] == ["Resumen: /r/resumen.md"]
    assert r["primero"].startswith("Copiada") and r["segundo"].startswith("Copiada")


# ─────────────────────────── quién habla (voces) ────────────────────────────


def _reunion_con(r, transcripcion, nombres=None):
    d = r / "20261021-100000"
    d.mkdir()
    (d / "meta.json").write_text(json.dumps({"id": d.name, "inicio": 0, "fin": 60}))
    (d / "transcripcion.json").write_text(json.dumps(transcripcion))
    (d / "resumen.json").write_text(json.dumps({"titulo": "Hotfix", "resumen": "x"}))
    (d / "procesado.json").write_text(json.dumps({"estado": "hecho", "etapas": {}}))
    if nombres:
        (d / "nombres.json").write_text(json.dumps(nombres))
    return d


def test_las_voces_salen_con_su_nombre_y_se_pueden_nombrar(cliente, raiz, monkeypatch):
    r, _ = raiz
    d = _reunion_con(r, [{"ini": 1, "fin": 2, "texto": "Hola", "quien": "Persona 2"},
                         {"ini": 3, "fin": 4, "texto": "Buenas", "quien": "Persona 1"},
                         {"ini": 5, "fin": 6, "texto": "Yo lo hago", "quien": "Yo"}],
                     {"Persona 1": "Ana"})
    ordenes = []
    monkeypatch.setattr(reuniones, "_lanzar", lambda *a: ordenes.append(a))

    html = cliente.get(f"/reuniones/{d.name}").text
    assert 'name="voz:Persona 1" value="Ana"' in html and 'name="voz:Persona 2" value=""' in html
    assert '<span class="quien">Ana</span>' in html and '<span class="quien">Persona 2</span>' in html

    cliente.post("/reuniones/accion", data={"id": d.name, "que": "nombres", "resumen": "1",
                                            "voz:Persona 1": "Ana", "voz:Persona 2": "Íñigo Pérez"})
    assert ordenes == [("nombres", d.name, "Persona 1=Ana", "Persona 2=Íñigo Pérez", "--resumen")]


def test_un_nombre_raro_o_una_clave_inventada_no_llegan_a_la_orden(cliente, raiz, monkeypatch):
    r, _ = raiz
    d = _reunion_con(r, [{"ini": 1, "fin": 2, "texto": "Hola", "quien": "Persona 1"}])
    ordenes = []
    monkeypatch.setattr(reuniones, "_lanzar", lambda *a: ordenes.append(a))
    for datos in ({"voz:Persona 1": "Ana; rm -rf"}, {"voz:--rehacer": "x"},
                  {"voz:Persona 1": "a" * 61}):
        r_ = cliente.post("/reuniones/accion", data={"id": d.name, "que": "nombres", **datos},
                          follow_redirects=False)
        assert "No+se+hizo" in r_.headers["location"] or "No%20se%20hizo" in r_.headers["location"]
    assert ordenes == []


def test_sin_voces_separadas_se_ofrece_separarlas_y_no_mientras_se_procesa(cliente, raiz, monkeypatch):
    r, _ = raiz
    d = _reunion_con(r, [{"ini": 1, "fin": 2, "texto": "Hola", "quien": "Reunión"}])
    ordenes = []
    monkeypatch.setattr(reuniones, "_lanzar", lambda *a: ordenes.append(a))

    assert 'value="voces"' in cliente.get(f"/reuniones/{d.name}").text
    (d / "procesado.json").write_text(json.dumps(
        {"estado": "hecho", "etapas": {"voces": "sin separar: no se pudo descargar"}}))
    assert "README.md</code>, apartado" in cliente.get(f"/reuniones/{d.name}").text
    cliente.post("/reuniones/accion", data={"id": d.name, "que": "voces"})
    assert ordenes == [("voces", d.name, "--resumen")]

    (d / "procesado.json").write_text(json.dumps({"estado": "procesando"}))
    cliente.post("/reuniones/accion", data={"id": d.name, "que": "voces"})
    assert len(ordenes) == 1
