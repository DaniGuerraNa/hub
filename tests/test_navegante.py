"""La pantalla del navegante: contestar lo que el guardián pausó.

Los archivos los escribe aquí el test con la forma exacta que deja
`navegador-lab` (aprobaciones.py); el ciclo con el guardián de verdad se prueba
en ese proyecto.
"""
from __future__ import annotations

import json
import os

import pytest
from fastapi.testclient import TestClient

from hub import api, db, navegante, web


@pytest.fixture
def datos(tmp_path, monkeypatch):
    d = tmp_path / "navegador-lab"
    monkeypatch.setenv("NAV_DATOS", str(d))
    return d


def pregunta(datos, pid="014946-a9a0ba", estado="pendiente"):
    (datos / "aprobaciones").mkdir(parents=True, exist_ok=True)
    (datos / "aprobaciones" / f"{pid}.json").write_text(json.dumps(
        {"id": pid, "estado": estado, "creada": 1792396186.18, "accion": "DeleteRestApi",
         "metodo": "POST", "url": "https://apigateway.us-east-1.amazonaws.com/restapis/x",
         "politica": "aws-lectura"}))
    return datos / "aprobaciones" / f"{pid}.json"


@pytest.fixture
def cliente(tmp_path, monkeypatch):
    def conexion():
        c = db.conectar(tmp_path / "hub.db")
        db.inicializar(c)
        return c
    monkeypatch.setattr(web, "conexion", conexion)
    return TestClient(web.app)


def test_sin_laboratorio_la_pantalla_dice_como_prepararlo(cliente, datos):
    """Antes el raíl la escondía; ahora sale siempre y enseña sus pasos (decisión 293)."""
    html = cliente.get("/navegante").text
    assert '<a href="/navegante" class="enlace' in html
    assert 'id="preparar"' in html and 'id="control"' not in html


def test_con_una_pregunta_pendiente_el_rail_la_cuenta_y_la_pantalla_la_ofrece(cliente, datos):
    pregunta(datos)
    html = cliente.get("/navegante").text
    assert '<a href="/navegante" class="enlace' in html
    assert "DeleteRestApi" in html and "Permitir una vez" in html
    assert 'class="cuenta urge">1<' in html


def test_permitir_desde_el_hub_deja_la_respuesta_que_lee_el_guardian(cliente, datos):
    ruta = pregunta(datos)
    r = cliente.post("/navegante/responder", data={"id": "014946-a9a0ba", "aprobar": "si"},
                     follow_redirects=False)
    assert r.status_code == 303 and "Permitida" in r.headers["location"].replace("%20", " ")
    d = json.loads(ruta.read_text())
    assert d["estado"] == "aprobada" and d["desde"] == "hub"


def test_negar_y_volver_a_contestar_no_cambia_lo_ya_decidido(cliente, datos):
    ruta = pregunta(datos)
    cliente.post("/navegante/responder", data={"id": "014946-a9a0ba", "aprobar": "no"})
    r = cliente.post("/navegante/responder", data={"id": "014946-a9a0ba", "aprobar": "si"},
                     follow_redirects=False)
    from urllib.parse import unquote
    assert "ya está denegada" in unquote(r.headers["location"])
    assert json.loads(ruta.read_text())["estado"] == "denegada"


def test_un_id_con_ruta_no_sale_de_la_carpeta(cliente, datos, tmp_path):
    pregunta(datos)
    fuera = tmp_path / "fuera.json"
    fuera.write_text(json.dumps({"estado": "pendiente"}))
    r = cliente.post("/navegante/responder", data={"id": "../../fuera", "aprobar": "si"},
                     follow_redirects=False)
    from urllib.parse import unquote
    assert "no válido" in unquote(r.headers["location"])
    assert json.loads(fuera.read_text())["estado"] == "pendiente"


def test_el_registro_se_lee_del_final(datos):
    datos.mkdir(parents=True)
    with (datos / "registro.jsonl").open("w") as f:
        for i in range(100):
            f.write(json.dumps({"t": 1792396186 + i, "evento": "permitida", "accion": f"A{i}"}) + "\n")
    r = navegante.registro()
    assert [e["accion"] for e in r[:2]] == ["A99", "A98"] and len(r) == 40


def test_el_timbre_del_navegante_lleva_al_dueno_a_su_pantalla_y_no_al_orquestador(con):
    """El guardián del laboratorio deja su timbre en la misma carpeta que el
    orquestador, con `pantalla`; el relé lo manda igual, sólo con el aviso."""
    import time
    from hub import orquestador as orq, rele

    class Bot:
        enviados = []

        def enviar(self, chat_id, texto):
            self.enviados.append(texto)
            return 1
    rele.canal.anotar_contacto(con, 777, "duena", "La dueña")
    rele.canal.marcar_dueno(con, 777)
    d = orq.carpeta() / "timbres"
    d.mkdir(exist_ok=True)
    (d / f"{time.time_ns()}.json").write_text(json.dumps(
        {"texto": "El navegante pide permiso (pregunta 020533-2fef24).", "pantalla": "Navegante"}))
    orq.timbre("Tarea t-1 terminada.")
    bot = Bot()
    assert rele.enviar_timbres(con, bot) == 2
    assert bot.enviados[0].endswith("Míralo en el hub → Navegante.")
    assert bot.enviados[1].endswith("Míralo en el hub → Orquestador.")


# ───────────── las acciones: qué `nav` sale de cada botón ─────────────


@pytest.fixture
def lab(tmp_path, monkeypatch):
    """Un laboratorio cuyo `nav` sólo apunta con qué argumentos se le llamó y
    contesta un resumen fijo. Lo que se prueba aquí es la frontera del hub —qué
    línea de comandos sale de un formulario—; el laboratorio de verdad tiene
    sus propios tests con navegador real."""
    d = tmp_path / "lab"
    (d / "bin").mkdir(parents=True)
    # Preparado: con su entorno y un Chrome, como lo deja «Preparar con Claude».
    (d / ".venv").mkdir()
    (d / "node_modules").mkdir()
    monkeypatch.setenv("NAV_CHROME", "chrome")
    llamadas = tmp_path / "llamadas.jsonl"
    resumen = {"estado": {"navegador": {"vivo": True, "pestanas": []}, "guardian": {"vivo": True,
               "politica": "trabajo-aws", "modo": "preguntar"}, "panel": {"vivo": False}, "grabando": None},
               "flujos": [{"nombre": "lista", "coleccion": "lab", "parametros": {"base": {}}, "pasos": 3,
                           "pantallas": {"desde": "consola", "hasta": "lista"}, "usa": []},
                          {"nombre": "detalle", "coleccion": "trabajo", "parametros": {}, "pasos": 2,
                           "pantallas": {}, "usa": []}],
               "politicas": [{"archivo": "trabajo-aws", "modo": "preguntar", "origenes": []}],
               "mapa": {"pantallas": ["consola", "lista"], "salen": {"consola": [{"flujo": "lab/lista",
                        "hasta": "lista", "desde": "consola"}], "lista": []}, "sin_pantalla": ["trabajo/detalle"]},
               "config": {"colecciones": [{"nombre": "trabajo"}, {"nombre": "lab"}], "accesos": []}}
    (d / "bin" / "nav").write_text(
        "#!/usr/bin/env python3\nimport json, sys\n"
        f"open({str(llamadas)!r}, 'a').write(json.dumps(sys.argv[1:]) + '\\n')\n"
        f"print(json.dumps({resumen!r}) if sys.argv[1] == 'resumen' else 'hecho')\n")
    (d / "bin" / "nav").chmod(0o755)
    monkeypatch.setenv("NAV_LAB", str(d))

    def leer():
        return [json.loads(l) for l in llamadas.read_text().splitlines() if '"resumen"' not in l] \
            if llamadas.exists() else []
    return leer


def test_correr_un_flujo_pasa_cada_parametro_como_un_argumento(cliente, datos, lab):
    r = cliente.post("/navegante/accion", data={"que": "correr", "flujo": "lab/lista",
                                                 "p_base": "https://x; rm -rf ~", "p_vacio": ""},
                     follow_redirects=False)
    assert r.status_code == 303
    assert lab()[-1] == ["flujo", "lab/lista", "--fondo", "-p", "base=https://x; rm -rf ~"]


def test_no_se_corre_un_flujo_que_no_existe(cliente, datos, lab):
    from urllib.parse import unquote
    r = cliente.post("/navegante/accion", data={"que": "correr", "flujo": "../../etc"}, follow_redirects=False)
    assert "no existe" in unquote(r.headers["location"]) and lab() == []


def test_una_orden_que_no_esta_en_la_lista_no_se_ejecuta(cliente, datos, lab):
    from urllib.parse import unquote
    r = cliente.post("/navegante/accion", data={"que": "aprobar", "id": "x"}, follow_redirects=False)
    assert "orden desconocida" in unquote(r.headers["location"]) and lab() == []


def test_guardar_una_grabacion_lleva_nombre_pantallas_y_parametros(cliente, datos, lab):
    cliente.post("/navegante/accion", data={
        "que": "parar-grabacion", "nombre": "errores-pedidos", "coleccion": "trabajo",
        "desde": "logs-insights", "hasta": "", "parametros": "grupo=/aws/lambda/x\n\nregion = eu-west-1"})
    assert lab()[-1] == ["grabar", "parar", "errores-pedidos", "--json", "--desde", "logs-insights",
                         "--coleccion", "trabajo", "-p", "grupo=/aws/lambda/x", "-p", "region=eu-west-1"]


def test_un_parametro_sin_igual_o_un_nombre_raro_se_rechaza_antes_de_llamar(cliente, datos, lab):
    for datos_ in ({"que": "parar-grabacion", "nombre": "Mi Flujo"},
                   {"que": "parar-grabacion", "nombre": "ok", "parametros": "sin igual"},
                   {"que": "ir", "url": "javascript:alert(1)"},
                   {"que": "pantallas", "flujo": "lab/lista", "desde": "Pantalla Rara"}):
        cliente.post("/navegante/accion", data=datos_)
    assert lab() == []


def test_componer_exige_dos_fragmentos_que_existan_y_los_pasa_en_orden(cliente, datos, lab):
    cliente.post("/navegante/accion", data={"que": "componer", "nombre": "x", "pieza_1": "lab/lista"})
    assert lab() == []
    cliente.post("/navegante/accion", data={"que": "componer", "nombre": "todo", "pieza_1": "trabajo/detalle",
                                             "pieza_2": "", "pieza_3": "lab/lista", "coleccion": "trabajo"})
    assert lab()[-1] == ["componer", "todo", "trabajo/detalle", "lab/lista", "--json", "--coleccion", "trabajo"]


def test_la_pantalla_pinta_el_control_los_flujos_y_el_mapa(cliente, datos, lab):
    pregunta(datos)
    html = cliente.get("/navegante").text
    assert "vigilando" in html and "trabajo-aws" in html
    assert "consola → lista" in html and "lab/lista" in html
    assert "Sin pantallas marcadas" in html and "trabajo/detalle" in html
    assert 'data-refrescar="5"' in html          # hay una pregunta esperando


def test_las_imagenes_de_una_corrida_no_salen_de_su_carpeta(cliente, datos):
    c = datos / "salidas" / "lista" / "20261019-120000"
    c.mkdir(parents=True)
    (c / "fallo.png").write_bytes(b"\x89PNG")
    assert cliente.get("/navegante/imagen?flujo=lista&cuando=20261019-120000&nombre=fallo.png").status_code == 200
    for q in ("flujo=..&cuando=20261019-120000&nombre=fallo.png",
              "flujo=lista&cuando=../../x&nombre=fallo.png",
              "flujo=lista&cuando=20261019-120000&nombre=../../../etc/passwd"):
        assert cliente.get("/navegante/imagen?" + q).status_code == 404


def _refresco(cuerpo: str):
    """navegante.js ejecutado en node con un documento mínimo (regla dura 11)."""
    import shutil, subprocess
    from pathlib import Path
    if not shutil.which("node"):
        pytest.skip("hace falta node")
    guion = (Path(web.__file__).parent / "static" / "navegante.js").read_text()
    programa = """
    let recargas = 0, refrescos = 0, tick = null, parado = 0, hay = true;
    const avisos = [], oyentes = {};
    // Un campo sabe si está dentro de una región, que es lo único que el
    // refresco repinta (C-0187). El doble lee sólo los selectores que conoce y
    // revienta con cualquier otro: si lo leyera todo igual, un selector que en
    // el navegador no casa con nada pasaría aquí por bueno.
    const hacer = (c) => ({...c, closest: (s) => s === '[data-region]' && c.region ? {} : null});
    function coincide(c, lista) {
      return lista.split(',').some((parte) => {
        let s = parte.trim();
        const enRegion = s.startsWith('[data-region] ');
        if (enRegion) s = s.slice('[data-region] '.length);
        const m = /^(textarea|select|input)(?:\\[type=(\\w+)\\]|(:not\\(\\[type\\]\\)))?$/.exec(s);
        if (!m) throw new Error('selector que el doble no sabe leer: ' + s);
        if (enRegion && !c.region) return false;
        if (c.tagName !== m[1].toUpperCase()) return false;
        if (m[2]) return c.type === m[2];
        if (m[3]) return !c.type;
        return true;
      });
    }
    const campo = hacer({tagName: 'INPUT', value: '', defaultValue: '', region: true});
    const campos = [campo];
    global.window = global;
    global.document = {activeElement: null,
      querySelector: (s) => s === '[data-refrescar]' && hay ? {dataset: {refrescar: '5'}} : null,
      querySelectorAll: (s) => campos.filter((c) => coincide(c, s)),
      addEventListener: (ev, f) => { oyentes[ev] = f; }};
    global.location = {reload: () => recargas++};
    global.setInterval = (f) => { tick = f; return 7; };
    global.clearInterval = () => { parado++; };
    global.HubUI = {avisar: (o) => avisos.push(o.titulo)};
    global.HubSinRecarga = {refrescar: () => { refrescos++; return globalThis.FALLA
      ? Promise.reject(new Error('el hub contestó 502')) : Promise.resolve([]); }};
    """ + guion + "\n(async () => {" + cuerpo + "})();"
    salida = subprocess.run(["node", "-e", programa], capture_output=True, text=True, timeout=20, check=True)
    return json.loads(salida.stdout)


def test_el_refresco_no_repinta_mientras_se_escribe():
    r = _refresco("""
    await tick(); const libre = refrescos;
    document.activeElement = campo; await tick(); const enfocado = refrescos;
    document.activeElement = null; campo.value = 'errores-ped'; await tick();
    console.log(JSON.stringify([libre, enfocado, refrescos, recargas]));
    """)
    assert r == [1, 1, 1, 0]


def test_el_refresco_cambia_la_pantalla_sin_recargarla_y_para_al_acabar():
    """C-0167: `location.reload()` cada cinco segundos era la página entera
    parpadeando. Ahora repinta sus regiones, y cuando ya no hay nada en marcha
    —la página no trae `data-refrescar`— deja de preguntar."""
    r = _refresco("""
    await tick();
    hay = false; oyentes['hub:repintado']();
    console.log(JSON.stringify({ refrescos, recargas, parado }));
    """)
    assert r == {"refrescos": 1, "recargas": 0, "parado": 1}


def test_si_el_hub_no_contesta_lo_dice_una_vez_y_para():
    r = _refresco("""
    globalThis.FALLA = true; await tick();
    console.log(JSON.stringify({ avisos, parado }));
    """)
    assert r == {"avisos": ["La pantalla dejó de actualizarse"], "parado": 1}


def test_un_desplegable_sin_tocar_no_frena_el_refresco_y_uno_cambiado_si():
    """Medido en /navegante: un `<select>` sin `<option selected>` contaba como
    tocado y la pantalla no volvía a actualizarse. Y en /reuniones, el monitor
    o el micro elegidos y no enviados se perdían al repintar."""
    r = _refresco("""
    const opciones = [{defaultSelected: false}, {defaultSelected: false}];
    const desplegable = {tagName: 'SELECT', options: opciones, selectedIndex: 0};
    document.querySelectorAll = () => [desplegable];
    await tick(); const sinTocar = refrescos;
    desplegable.selectedIndex = 1; await tick();
    console.log(JSON.stringify([sinTocar, refrescos]));
    """)
    assert r == [1, 1]


def test_lo_que_queda_fuera_de_las_regiones_no_frena_el_refresco():
    """C-0187, medido en Chromium: el panel del secretario sale en todas las
    pantallas, y con «Leer las respuestas en voz alta» guardada su casilla la
    marca el JS al cargar —`checked` distinto de `defaultChecked` para
    siempre—. /navegante y /reuniones dejaban de actualizarse sin decirlo, y la
    pregunta que espera «Permitir» no llegaba a verse. Lo mismo el borrador del
    panel, el foco en él o lo escrito en la paleta: nada de eso se repinta, así
    que nada de eso se pierde."""
    r = _refresco("""
    const voz = hacer({tagName: 'INPUT', type: 'checkbox', checked: true, defaultChecked: false});
    const borrador = hacer({tagName: 'TEXTAREA', value: 'mañana a las', defaultValue: ''});
    const paleta = hacer({tagName: 'INPUT', type: 'text', value: 'serv', defaultValue: ''});
    campos.push(voz, borrador, paleta);
    await tick(); const conElPanel = refrescos;
    document.activeElement = borrador; await tick(); const conFocoFuera = refrescos;
    document.activeElement = campo; await tick(); const conFocoDentro = refrescos;
    document.activeElement = null; campo.value = 'errores-ped'; await tick();
    console.log(JSON.stringify([conElPanel, conFocoFuera, conFocoDentro, refrescos]));
    """)
    assert r == [1, 2, 2, 2]
