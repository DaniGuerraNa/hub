"""Reuniones: la orden de grabar, el latido del agente y lo procesado.

El agente de Windows y el procesado tienen sus propias pruebas en
`~/projects/reuniones` (con audio y GPU de verdad). Aquí, la frontera del hub:
qué orden sale de un formulario y qué se enseña de una carpeta."""
from __future__ import annotations

import json
import os
import re
import subprocess
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from hub import api, db, procesos, reuniones, web

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


# ── el monitor donde está la ventana de la app (C-0456) ──────────────────────

INVENTARIO_03 = {**INVENTARIO, "agente": "0.3.0"}


def test_donde_este_la_ventana_manda_seguir_la_app_con_el_monitor_de_reserva(cliente, raiz):
    cliente.post("/api/reuniones/latido", json=INVENTARIO_03)
    cliente.post("/reuniones/accion", data={"que": "grabar", "monitor": "ventana", "app": "ms-teams.exe"})
    o = reuniones.orden()
    assert o["grabar"] and o["seguir_app"] is True and o["monitor"] == 1


def test_un_monitor_elegido_a_mano_no_sigue_la_ventana(cliente, raiz):
    cliente.post("/api/reuniones/latido", json=INVENTARIO_03)
    cliente.post("/reuniones/accion", data={"que": "grabar", "monitor": "3", "app": "ms-teams.exe"})
    assert reuniones.orden()["seguir_app"] is False and reuniones.orden()["monitor"] == 3


def test_seguir_la_ventana_sin_aplicacion_se_rechaza_en_vez_de_grabar_cualquier_monitor(cliente, raiz):
    from urllib.parse import unquote
    cliente.post("/api/reuniones/latido", json=INVENTARIO_03)
    r = cliente.post("/reuniones/accion", data={"que": "grabar", "monitor": "ventana"}, follow_redirects=False)
    assert "elige la aplicación" in unquote(r.headers["location"])
    assert reuniones.orden()["grabar"] is False


def test_la_reserva_es_donde_el_agente_vio_la_ventana_la_ultima_vez(cliente, raiz):
    reuniones._escribir(reuniones.carpeta() / "orden.json", {"grabar": False, "monitor": 1})
    cliente.post("/api/reuniones/latido", json=INVENTARIO_03)
    cliente.post("/api/reuniones/latido", json={"agente": "0.3.0", "grabando": {
        "id": "20261118-094651", "segundos": 5, "fotos": 1, "errores": [], "monitor": 3,
        "monitor_origen": "ventana"}})
    assert reuniones.grabar("", "ms-teams.exe", "", seguir_app=True)["monitor"] == 3


def test_un_monitor_heredado_no_se_recuerda_como_el_de_la_ventana(cliente, raiz):
    cliente.post("/api/reuniones/latido", json={**INVENTARIO_03, "grabando": {
        "id": "20261118-094651", "monitor": 3, "monitor_origen": "heredado"}})
    assert not (reuniones.carpeta() / "monitor-visto.json").exists()


def test_la_opcion_de_seguir_la_ventana_solo_se_ofrece_con_un_agente_que_sabe(cliente, raiz):
    cliente.post("/api/reuniones/latido", json=INVENTARIO)            # 0.1.0
    html = cliente.get("/reuniones").text
    assert re.search(r'value="ventana"\s+disabled', html) and "necesita el agente 0.3.0" in html
    assert re.search(r'value="1"\s+checked', html)                   # el primero, no el de número más alto
    cliente.post("/api/reuniones/latido", json=INVENTARIO_03)
    html = cliente.get("/reuniones").text
    assert re.search(r'value="ventana"\s+checked', html)


def test_mientras_graba_el_monitor_lo_dice_el_agente_y_no_la_orden(cliente, raiz):
    cliente.post("/api/reuniones/latido", json=INVENTARIO_03)
    reuniones.grabar("", "ms-teams.exe", "", seguir_app=True)        # reserva: el 1
    cliente.post("/api/reuniones/latido", json={"agente": "0.3.0", "grabando": {
        "id": reuniones.orden()["id"], "segundos": 20, "fotos": 2, "errores": [], "monitor": 3,
        "monitor_origen": "ventana"}})
    html = " ".join(cliente.get("/reuniones").text.split())
    assert "monitor 3 (donde está la ventana de ms-teams.exe)" in html
    cliente.post("/api/reuniones/latido", json={"agente": "0.3.0", "grabando": {
        "id": reuniones.orden()["id"], "monitor": 1, "monitor_origen": "heredado"}})
    html = " ".join(cliente.get("/reuniones").text.split())
    assert "No encuentro la ventana de ms-teams.exe" in html and "donde está la ventana" not in html


def test_con_un_agente_viejo_no_afirma_que_sigue_la_ventana(cliente, raiz):
    cliente.post("/api/reuniones/latido", json=INVENTARIO_03)
    reuniones.grabar("", "ms-teams.exe", "", seguir_app=True)
    cliente.post("/api/reuniones/latido", json={"agente": "0.2.0", "grabando": {
        "id": reuniones.orden()["id"], "segundos": 20, "fotos": 2, "errores": []}})
    html = " ".join(cliente.get("/reuniones").text.split())
    assert "monitor 1" in html and "donde está la ventana" not in html


def _reunion_con_meta(r, **meta):
    d = r / "20261118-094651"
    (d / "fotos").mkdir(parents=True)
    (d / "meta.json").write_text(json.dumps({"id": d.name, "inicio": 0, "fin": 600,
                                             "proceso": {"nombre": "ms-teams.exe"}, **meta}))
    (d / "procesado.json").write_text(json.dumps({"estado": "hecho"}))
    return d


def test_la_reunion_avisa_si_sus_capturas_no_son_de_la_ventana_de_la_llamada(cliente, raiz):
    r, _ = raiz
    d = _reunion_con_meta(r, monitor=3, monitor_pedido=3, monitor_origen="heredado",
                          cambios_monitor=[{"segundo": 0, "monitor": 3, "origen": "heredado"}])
    html = " ".join(cliente.get(f"/reuniones/{d.name}").text.split())
    assert "No se encontró la ventana de ms-teams.exe: las capturas son del monitor 3" in html


def test_la_reunion_cuenta_cuando_las_capturas_cambiaron_de_monitor(cliente, raiz):
    r, _ = raiz
    d = _reunion_con_meta(r, monitor=1, monitor_pedido=3, monitor_origen="ventana", cambios_monitor=[
        {"segundo": 0, "monitor": 3, "origen": "heredado"}, {"segundo": 75, "monitor": 1, "origen": "ventana"}])
    html = " ".join(cliente.get(f"/reuniones/{d.name}").text.split())
    assert ("Las capturas siguen la ventana de ms-teams.exe: monitor 3 (sin encontrar la ventana), "
            "desde el 1:15 monitor 1.") in html


def test_una_reunion_que_siguio_la_ventana_sin_moverse_o_vieja_no_lleva_aviso(cliente, raiz):
    r, _ = raiz
    d = _reunion_con_meta(r, monitor=1, monitor_pedido=3, monitor_origen="ventana",
                          cambios_monitor=[{"segundo": 0, "monitor": 1, "origen": "ventana"}])

    assert "Las capturas siguen" not in cliente.get(f"/reuniones/{d.name}").text


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
    assert "1 sin comprimir" in html and "sin comprimir · 2,4 MB" in html
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
      // Por delegación en el documento (C-0167): la ficha se repinta sin
      // recargar mientras se procesa y un oyente atado al botón se perdería.
      const delDoc = {};
      global.document = { getElementById: el, createElement: () => el('textarea'),
        body: { appendChild(){} }, execCommand: () => true,
        addEventListener(ev, f) { delDoc[ev] = f; } };
      const pulsar = () => delDoc.click({ target: { closest: (s) => s === '#copiar-ruta' ? el('copiar-ruta') : null } });
      const copiado = [];
      Object.defineProperty(globalThis, 'navigator', { configurable: true, value: {
        clipboard: { writeText: (t) => globalThis.NIEGA ? Promise.reject(new Error('no'))
                                                         : (copiado.push(t), Promise.resolve()) } } });
      GUION
      (async () => {
        await pulsar();
        const primero = nodos['copiada'].textContent;
        globalThis.NIEGA = true;
        await pulsar();
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
    monkeypatch.setattr(reuniones, "_lanzar", lambda *a, **k: ordenes.append(a))

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
    monkeypatch.setattr(reuniones, "_lanzar", lambda *a, **k: ordenes.append(a))
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
    monkeypatch.setattr(reuniones, "_lanzar", lambda *a, **k: ordenes.append(a))

    assert 'value="voces"' in cliente.get(f"/reuniones/{d.name}").text
    (d / "procesado.json").write_text(json.dumps(
        {"estado": "hecho", "etapas": {"voces": "sin separar: no se pudo descargar"}}))
    assert "README.md</code>, apartado" in cliente.get(f"/reuniones/{d.name}").text
    cliente.post("/reuniones/accion", data={"id": d.name, "que": "voces"})
    assert ordenes == [("voces", d.name, "--resumen")]

    (d / "procesado.json").write_text(json.dumps({"estado": "procesando"}))
    cliente.post("/reuniones/accion", data={"id": d.name, "que": "voces"})
    assert len(ordenes) == 1


# ── lo que se corta a medias (C-0148, decisión 344) ──


def _procesando(r, id_="20261020-090000", inicio=None):
    d = r / id_
    d.mkdir()
    (d / "meta.json").write_text(json.dumps({"id": id_, "inicio": 0, "fin": 60}))
    (d / "procesado.json").write_text(json.dumps({"estado": "procesando", "inicio": inicio or time.time(),
                                                  "etapas": {"transcribir": "hecho en 24 s", "resumir": "en-curso"}}))
    return d


def test_un_procesado_cuyo_proceso_murio_se_ve_cortado_y_se_puede_reintentar(cliente, raiz):
    r, _ = raiz
    d = _procesando(r)
    muerto = subprocess.Popen(["true"])
    huella = procesos.huella(muerto.pid)
    muerto.wait()
    reuniones._escribir(reuniones._lanzados(crear=True) / f"{d.name}-procesar.json", {**huella, "desde": time.time()})
    assert reuniones.lista()[0]["estado"] == "se cortó"
    html = cliente.get(f"/reuniones/{d.name}").text
    assert "se cortó" in html and "Reintentar" in html and "resumir: en-curso" in html
    assert 'data-refrescar' not in html, "algo cortado no se refresca esperando a que acabe"
    (d / "reunion.wav").write_bytes(b"\0" * 5000)
    assert reuniones.sin_comprimir() == [], "reuniones comprimir se negaría: primero se reintenta"
    assert "Comprimir audio" not in cliente.get(f"/reuniones/{d.name}").text


def test_lo_que_sigue_vivo_o_lo_que_lanzo_otro_sigue_procesando(cliente, raiz):
    r, _ = raiz
    d = _procesando(r)
    assert reuniones.lista()[0]["estado"] == "procesando", "sin registro no se sabe: lo lanzó otro"
    vivo = subprocess.Popen(["sleep", "30"])
    try:
        reuniones._escribir(reuniones._lanzados(crear=True) / f"{d.name}-procesar.json",
                            {**procesos.huella(vivo.pid), "desde": time.time()})
        assert reuniones.lista()[0]["estado"] == "procesando"
    finally:
        vivo.kill()
        vivo.wait()
    (d / "procesado.json").write_text(json.dumps({"estado": "procesando", "inicio": time.time() + 3600}))
    assert reuniones.lista()[0]["estado"] == "procesando", "un arranque posterior no es de este lanzamiento"


def test_una_compresion_cortada_deja_de_bloquear(raiz):
    r, _ = raiz
    d = r / "20261020-090000"
    d.mkdir()
    (d / "meta.json").write_text(json.dumps({"id": d.name, "inicio": 0, "fin": 60}))
    (d / "reunion.wav").write_bytes(b"\0" * 5000)
    (d / "comprimiendo").touch()
    assert reuniones.sin_comprimir() == []
    muerto = subprocess.Popen(["true"])
    huella = procesos.huella(muerto.pid)
    muerto.wait()
    reuniones._escribir(reuniones._lanzados(crear=True) / f"{d.name}-comprimir.json", {**huella, "desde": time.time()})
    assert reuniones.sin_comprimir() == [d.name]


def test_al_lanzar_se_apunta_la_huella_de_lo_lanzado(raiz, monkeypatch):
    lanzado = subprocess.Popen(["sleep", "30"])
    ordenes = []
    monkeypatch.setattr(procesos, "desasir", lambda orden, **kw: ordenes.append(orden) or lanzado)
    try:
        reuniones._lanzar("procesar", "20261020-090000", raiz=raiz[0], ids=("20261020-090000",))
        h = reuniones._leer(reuniones._lanzados() / "20261020-090000-procesar.json")
        assert h["pid"] == lanzado.pid and procesos.vivo(h)
        assert ordenes[0][-2:] == ["procesar", "20261020-090000"]
    finally:
        lanzado.kill()
        lanzado.wait()


def test_separar_voces_cortado_tambien_se_ve_cortado(raiz, monkeypatch):
    """`reuniones voces` pasa por `procesar` y escribe su «procesando» con un
    inicio nuevo: su huella va con la de procesar (revisor de C-0148)."""
    r, _ = raiz
    d = r / "20261020-090000"
    d.mkdir()
    (d / "meta.json").write_text(json.dumps({"id": d.name, "inicio": 0, "fin": 60}))
    (d / "procesado.json").write_text(json.dumps({"estado": "hecho", "inicio": time.time() - 7200}))
    muerto = subprocess.Popen(["true"])
    monkeypatch.setattr(procesos, "desasir", lambda orden, **kw: muerto)
    reuniones.lanzar_voces(d.name)
    (d / "procesado.json").write_text(json.dumps({"estado": "procesando", "inicio": time.time()}))
    muerto.wait()
    assert reuniones.lista()[0]["estado"] == "se cortó"
    with pytest.raises(ValueError, match="reinténtalo"):
        reuniones.lanzar_voces(d.name)


def test_una_compresion_de_varias_marca_tarde_y_aun_asi_se_ve_cortada(raiz):
    r, _ = raiz
    d = r / "20261020-090000"
    d.mkdir()
    (d / "meta.json").write_text(json.dumps({"id": d.name, "inicio": 0, "fin": 60}))
    (d / "reunion.wav").write_bytes(b"\0" * 5000)
    (d / "comprimiendo").touch()
    muerto = subprocess.Popen(["true"])
    huella = procesos.huella(muerto.pid)
    muerto.wait()
    reuniones._escribir(reuniones._lanzados(crear=True) / f"{d.name}-comprimir.json",
                        {**huella, "desde": time.time() - 3600})
    assert reuniones.sin_comprimir() == [d.name], "marcada una hora después de lanzarse"


# ── lo que ocupa cada una (C-0276) ──

def _grabacion(r, id_, fin, fotos=3):
    d = r / id_
    (d / "fotos").mkdir(parents=True)
    (d / "meta.json").write_text(json.dumps({"id": id_, "inicio": 0, "fin": fin}))
    (d / "reunion.opus").write_bytes(b"\0" * 1000)
    for s in range(fotos):
        (d / "fotos" / f"{s:06d}.jpg").write_bytes(b"\xff" * 500)
    return d


def _envejecer(carpeta):
    """La deja con una fecha de hace un rato: dos escrituras seguidas pueden
    caer en el mismo tic del reloj del sistema de archivos."""
    hace = time.time_ns() - 60 * 10**9
    os.utime(carpeta, ns=(hace, hace))
    return hace


def test_el_tamano_suma_lo_mismo_que_recorrer_archivo_a_archivo(raiz):
    r, _ = raiz
    d = _grabacion(r, "20261020-090000", 600)
    (d / "fotos" / "sub").mkdir()
    (d / "fotos" / "sub" / "x.bin").write_bytes(b"\0" * 77)
    (d / "roto").symlink_to(d / "no-existe")
    a_mano = sum(f.stat().st_size for f in d.rglob("*") if f.is_file())
    assert reuniones._tamano(d) == a_mano == 1000 + 3 * 500 + 77 + len((d / "meta.json").read_bytes())


def test_las_fotos_de_una_terminada_se_miden_una_vez_mientras_su_carpeta_no_cambie(raiz):
    """`/reuniones` tardaba 6,6–7,9 s: recorría cada foto de cada grabación en
    cada carga, y mientras se graba la pantalla se repinta cada 5 s. Las fotos
    de una reunión terminada ya no cambian: se recuerdan por la fecha de su
    carpeta, que cambia si se añade o se quita una."""
    r, _ = raiz
    d = _grabacion(r, "20261020-090000", 600)
    marca = _envejecer(d / "fotos")
    antes = reuniones.lista()[0]["tamano"]

    # Crecer una foto sin tocar su carpeta: no se vuelve a recorrer.
    (d / "fotos" / "000000.jpg").write_bytes(b"\xff" * 1500)
    os.utime(d / "fotos", ns=(marca, marca))
    assert reuniones.lista()[0]["tamano"] == antes

    # Lo de arriba (el audio, los .json) se mide siempre.
    (d / "reunion.opus").write_bytes(b"\0" * 3000)
    assert reuniones.lista()[0]["tamano"] == antes + 2000

    # Una foto nueva cambia la fecha de la carpeta: se mide otra vez entera.
    (d / "fotos" / "000009.jpg").write_bytes(b"\xff" * 500)
    assert reuniones.lista()[0]["tamano"] == antes + 2000 + 1000 + 500


def test_la_que_se_esta_grabando_se_mide_siempre_entera(raiz):
    r, _ = raiz
    d = _grabacion(r, "20261020-090000", None)
    marca = _envejecer(d / "fotos")
    antes = reuniones.lista()[0]["tamano"]
    (d / "fotos" / "000000.jpg").write_bytes(b"\xff" * 1500)
    os.utime(d / "fotos", ns=(marca, marca))
    assert reuniones.lista()[0]["tamano"] == antes + 1000


# ── C-0379: si el agente de Windows está al día ─────────────────────────────


def _version(carpeta: Path, version: str) -> None:
    carpeta.mkdir(parents=True, exist_ok=True)
    (carpeta / "agente.py").write_text(f'"""El agente."""\nimport sys\n\nVERSION = "{version}"\n', encoding="utf-8")


def _tarjeta_version(html: str) -> str:
    """La tarjeta de la versión, de su etiqueta a la que la cierra; vacía si no está."""
    i = html.find('id="version-agente"')
    if i < 0:
        return ""
    inicio = html.rfind("<", 0, i)
    return html[inicio:html.find("\n  </", i)]


def test_con_un_agente_mas_viejo_que_el_del_hub_lo_dice_y_ofrece_copiarlo(cliente, raiz):
    """Tras actualizar el hub no se sabía si había que «Copiar el agente» (HER-18)."""
    _version(reuniones.proyecto() / "agente", "0.2.0")
    cliente.post("/api/reuniones/latido", json=INVENTARIO)              # el agente dice 0.1.0
    v = api.reuniones()["version_agente"]
    assert (v["estado"], v["corre"], v["hay"]) == ("vieja", "0.1.0", "0.2.0")
    tarjeta = _tarjeta_version(cliente.get("/reuniones").text)
    assert "0.1.0" in tarjeta and "0.2.0" in tarjeta
    assert 'action="/reuniones/copiar-agente"' in tarjeta and "Copiar el agente" in tarjeta


def test_copiado_pero_sin_reiniciar_dice_que_falta_reiniciarlo_y_no_vuelve_a_ofrecer_copiar(cliente, raiz):
    _version(reuniones.proyecto() / "agente", "0.2.0")
    _version(reuniones.carpeta_agente(), "0.2.0")
    cliente.post("/api/reuniones/latido", json=INVENTARIO)
    assert api.reuniones()["version_agente"]["estado"] == "copiada"
    html = cliente.get("/reuniones").text
    assert "falta reiniciarlo" in html and "copiar-agente" not in _tarjeta_version(html)


def test_con_la_misma_version_dice_al_dia(cliente, raiz):
    _version(reuniones.proyecto() / "agente", "0.1.0")
    cliente.post("/api/reuniones/latido", json=INVENTARIO)
    assert api.reuniones()["version_agente"]["estado"] == "al-dia"
    html = cliente.get("/reuniones").text
    assert "0.1.0 · al día" in html and not _tarjeta_version(html)


@pytest.mark.parametrize("corre, hay", [(None, "0.2.0"), ("0.1.0", None), ("0.3.0", "0.2.0"), ("rara", "0.2.0")])
def test_lo_que_no_se_puede_comparar_no_se_afirma(cliente, raiz, corre, hay):
    """Regla dura 13: sin la versión de uno de los dos, o con un agente más
    nuevo que el del hub, ni «al día» ni «copia el agente», que lo bajaría."""
    if hay:
        _version(reuniones.proyecto() / "agente", hay)
    cliente.post("/api/reuniones/latido", json={**INVENTARIO, "agente": corre})
    assert api.reuniones()["version_agente"]["estado"] is None
    html = cliente.get("/reuniones").text
    assert not _tarjeta_version(html) and "al día" not in html


# ── C-0380: cerrar de una vez los compromisos que salieron de una reunión ────


def _reunion_con_compromisos(raiz_grabaciones: Path) -> tuple[str, list[int], int]:
    """Una reunión procesada, dos compromisos suyos y uno de otra reunión."""
    from hub.secretario import memoria
    from hub.secretario.piezas import Evento

    d = raiz_grabaciones / "20261020-090000"
    d.mkdir(parents=True)
    (d / "meta.json").write_text(json.dumps({"id": d.name, "inicio": 0, "fin": 600}))
    (d / "resumen.json").write_text(json.dumps({"titulo": "Seguimiento", "resumen": "Breve."}))
    (d / "procesado.json").write_text(json.dumps({"estado": "hecho"}))
    con = memoria.conectar()
    try:
        esta = memoria.guardar_evento(con, Evento(fuente="hub", id_externo=f"reunion:{d.name}", fecha="2026-10-20",
                                                  texto="…", conversacion="reuniones", autor="Reunión"))
        otra = memoria.guardar_evento(con, Evento(fuente="hub", id_externo="reunion:20261021-100000",
                                                  fecha="2026-10-21", texto="…", conversacion="reuniones",
                                                  autor="Reunión"))
        origen = "hub · reuniones · Reunión"       # el mismo para todas: no sirve para distinguirlas
        suyos = [memoria.comprometer(con, "Mandar el acta", evento=esta, origen=origen),
                 memoria.comprometer(con, "Revisar el despliegue", quien="Ana", evento=esta, origen=origen)]
        ajeno = memoria.comprometer(con, "Pedir presupuesto", evento=otra, origen=origen)
    finally:
        con.close()
    return d.name, suyos, ajeno


def _estados() -> dict[int, str]:
    from hub.secretario import memoria
    con = memoria.conectar()
    try:
        return {f["id"]: f["estado"] for f in con.execute("SELECT id, estado FROM compromiso")}
    finally:
        con.close()


def test_la_reunion_ensena_sus_compromisos_abiertos_y_el_boton_pide_confirmacion(cliente, raiz):
    rid, suyos, ajeno = _reunion_con_compromisos(raiz[0])
    assert [c["id"] for c in api.reunion(rid)["compromisos"]] == suyos
    html = cliente.get(f"/reuniones/{rid}").text
    assert "Mandar el acta" in html and "Revisar el despliegue" in html and "Pedir presupuesto" not in html
    form = html.split(f'action="/reuniones/{rid}/compromisos"', 1)[1].split("</form>", 1)[0]
    assert "data-confirmar=" in form and "2 compromisos" in form
    assert all(f'name="id" value="{i}"' in form for i in suyos) and f'value="{ajeno}"' not in form


@pytest.mark.parametrize("estado", ["hecho", "descartado"])
def test_cerrar_en_bloque_cierra_solo_los_de_esa_reunion(cliente, raiz, estado):
    rid, suyos, ajeno = _reunion_con_compromisos(raiz[0])
    # Aunque llegue el id de otra reunión, sólo se cierran los suyos.
    r = cliente.post(f"/reuniones/{rid}/compromisos", data={"estado": estado, "id": [*suyos, ajeno]},
                     follow_redirects=False)
    assert r.status_code == 303 and "2%20compromisos" in r.headers["location"]
    assert _estados() == {suyos[0]: estado, suyos[1]: estado, ajeno: "abierto"}
    assert api.reunion(rid)["compromisos"] == []


def test_cerrar_en_bloque_no_toca_uno_que_llego_despues_de_ver_la_pantalla(cliente, raiz):
    """Se cierran los que el dueño vio y confirmó, no los que haya ahora."""
    rid, suyos, _ = _reunion_con_compromisos(raiz[0])
    cliente.post(f"/reuniones/{rid}/compromisos", data={"estado": "hecho", "id": [suyos[0]]})
    assert (_estados()[suyos[0]], _estados()[suyos[1]]) == ("hecho", "abierto")


def test_cerrar_en_bloque_desde_otro_sitio_web_se_rechaza(cliente, raiz):
    rid, suyos, _ = _reunion_con_compromisos(raiz[0])
    r = cliente.post(f"/reuniones/{rid}/compromisos", data={"estado": "hecho", "id": suyos},
                     headers={"origin": "https://malo.example"})
    assert r.status_code == 403 and set(_estados().values()) == {"abierto"}


def test_sin_memoria_del_secretario_la_reunion_no_la_crea(cliente, raiz):
    from hub.secretario import memoria
    r = raiz[0] / "20261020-090000"
    r.mkdir(parents=True)
    (r / "meta.json").write_text(json.dumps({"id": r.name, "inicio": 0, "fin": 600}))
    assert api.reunion(r.name)["compromisos"] == []
    assert "compromisos" not in cliente.get(f"/reuniones/{r.name}").text.split('data-region="reunion"')[1]
    assert not memoria.existe()


def test_cuanto_hace_que_el_agente_dio_senales_se_lee_en_su_unidad(cliente, raiz, monkeypatch):
    """«hace 7200 s» se cuenta con el dedo: va con `reloj.duracion` («2 h»),
    como el resto del hub (tras la revisión de C-0396). Preparado y callado:
    es cuando la tarjeta del agente desconectado lo dice."""
    import json as _json
    import time as _time
    (reuniones.carpeta() / "latido.json").write_text(_json.dumps({"t": _time.time() - 7230}))
    original = reuniones.preparacion
    monkeypatch.setattr(reuniones, "preparacion", lambda: {**original(), "listo": True})

    html = cliente.get("/reuniones").text

    assert "dio señales hace 2 h." in html and "7230 s" not in html
