"""Ejecuta el JavaScript en línea de las vistas nuevas.

Sus scripts son los que paran contenedores y lanzan agentes: si revientan al
arrancar, los botones quedan inertes sin que se note (regla dura 11).
"""

from __future__ import annotations

import pytest

from arnes_js import ejecutar, script_de

CONTEXTO_SERVICIOS = {
    "s": {
        "contenedores": [{
            "contenedor": "facturador-dev-postgres", "proyecto_id": "facturador",
            "proyecto_nombre": "Facturador", "imagen": "pgvector", "estado": "running",
            "detalle": "Up 2 hours", "ultima_vez_visto": "2026-08-28T00:00:00+00:00",
        }],
        "total": 1, "vivos": 1, "sin_atribuir": [], "medido_en": None,
    },
    "hay_docker": True, "titulo": "Servicios", "seccion": "servicios",
}

CONTEXTO_PROYECTO = {
    "p": {"id": "demo", "nombre": "Demo", "dominio": "personal", "status": "activo",
          "guardrail": "ask", "estado_ref": "ESTADO.md", "rutas": [], "asiento": "/tmp/demo"},
    "slots": [], "paneles": [], "archivados": False,
    "estado": {"ruta": "/tmp/demo/ESTADO.md", "declarado": "ESTADO.md", "existe": True,
               "campos": {"estado": "verde"}, "modificado": "2026-08-28T00:00:00+00:00"},
    "capa": {"presente": False, "carpeta": None, "version": None, "tiene_project": False,
             "tiene_capabilities": False, "al_dia": False, "prompt_sembrar": "Crea la capa base"},
    "repos": [], "servicios": {"contenedores": [], "total": 0, "vivos": 0,
                               "sin_atribuir": [], "medido_en": None},
    # 🔴 El contexto del arnés tiene que traer lo MISMO que pasa la ruta. Faltó
    # `consumo` al añadir su sección y los dos tests de JS de esta plantilla
    # murieron con `UndefinedError` antes de llegar al script — que es el arnés
    # haciendo su trabajo: en Jinja, leer un atributo de algo indefinido no
    # devuelve vacío, revienta la plantilla entera.
    "consumo": {"hay_datos": False},
    "titulo": "Demo", "seccion": "panorama",
}


@pytest.fixture(scope="module")
def servicios(tmp_path_factory):
    return ejecutar(script_de("servicios.html", CONTEXTO_SERVICIOS), tmp_path_factory.mktemp("js"))


@pytest.fixture(scope="module")
def proyecto(tmp_path_factory):
    return ejecutar(script_de("proyecto.html", CONTEXTO_PROYECTO), tmp_path_factory.mktemp("js"))


def test_el_script_de_servicios_arranca_sin_reventar(servicios):
    assert servicios["errores"] == []


def test_servicios_engancha_los_botones_de_arrancar_y_parar(servicios):
    assert "document:click" in servicios["oyentes"]


def test_arrancar_un_contenedor_repinta_la_lista_y_la_cifra_del_rail(tmp_path):
    """C-0187: sólo se repintaba la lista, y el raíl seguía contando los
    contenedores de antes hasta cambiar de pantalla."""
    accion = """
    HubSinRecarga = { refrescar: (r) => { registro.pedidos = (registro.pedidos || []).concat([r]);
                                          return Promise.resolve([]); } };
    const boton = { dataset: { contenedor: 'facturador-dev-postgres', accion: 'start' }, textContent: 'Arrancar' };
    DOC_OYENTES.click.forEach((fn) => fn({ target: { closest: (s) => s === '.accion-svc' ? boton : null } }));
    """
    r = ejecutar(script_de("servicios.html", CONTEXTO_SERVICIOS), tmp_path,
                 respuestas={"POST /api/servicio/accion": {"ok": True}}, accion=accion)
    assert r["errores"] == []
    assert r["pedidos"] and set(r["pedidos"][-1]) == {"servicios", "rail"}


def test_el_script_de_proyecto_arranca_sin_reventar(proyecto):
    assert proyecto["errores"] == []


def test_proyecto_engancha_el_boton_de_sembrar_la_capa_base(proyecto):
    assert "document:click" in proyecto["oyentes"]


@pytest.fixture(scope="module")
def contexto(tmp_path_factory):
    return ejecutar(
        script_de("contexto.html", {"markdown": "# Estado\n", "titulo": "Contexto",
                                    "seccion": "contexto"}),
        tmp_path_factory.mktemp("js"),
    )


def test_el_script_de_contexto_arranca_sin_reventar(contexto):
    assert contexto["errores"] == []


def test_el_boton_de_copiar_queda_enganchado(contexto):
    """Si revienta, el botón de copiar queda mudo y no hay síntoma visible."""
    assert "click" in contexto["oyentes"]


# ── Tablero (C-0146): «Descartar» pide el motivo y manda el formulario ────────

CONTEXTO_TABLERO = {
    "t": {"nuevas": [{"id": 5, "texto": "una idea", "detalle": "", "proyecto": None, "origen": "web",
                      "creada": "2026-11-03T10:00:00+00:00",
                      "adjuntos": [{"nombre": "_tablero/5/foto.png", "archivo": "foto.png", "imagen": True,
                                    "tamano": "1 KB"}]}],
          "recientes": [], "proyectos": ["hub"], "max_adjuntos": 10},
    "titulo": "Tablero", "seccion": "tablero",
}

_DESCARTAR = """
const f = nodo('form-descartar');
f.elements = { motivo: nodo('motivo') };
f.submit = () => registro.enviados.push(f.action + ' | ' + f.elements.motivo.value);
HubUI.preguntar = (o) => { registro.avisos.push(o.titulo); return Promise.resolve(RESPUESTA); };
const boton = { dataset: { id: '5', texto: 'una idea' } };
DOC_OYENTES.click.forEach(fn => fn({ target: { closest: (s) => s === '.descartar-idea' ? boton : null } }));
"""


@pytest.mark.parametrize("respuesta,esperado", [
    ("'ya existe en Archivos'", ["/tablero/idea/5/descartar | ya existe en Archivos"]),
    ("null", []),
    ("'   '", []),
])
def test_descartar_una_idea_pide_el_motivo_y_sin_motivo_no_manda_nada(tmp_path, respuesta, esperado):
    r = ejecutar(script_de("tablero.html", CONTEXTO_TABLERO), tmp_path,
                 accion=_DESCARTAR.replace("RESPUESTA", respuesta))
    assert r["errores"] == []
    assert r["avisos"] == ["Descartar la idea #5"]
    assert r["enviados"] == esperado


_PEGAR = """
global.DataTransfer = class { constructor(){ const l = []; this.items = { add: f => l.push(f) }; this.files = l; } };
const entrada = nodo('archivos-idea');
entrada.files = [];
const form = nodo('form-idea');
let evitado = false;
form.disparar('paste', { clipboardData: { files: [{ name: 'image.png' }] }, preventDefault(){ evitado = true; } });
form.disparar('drop', { dataTransfer: { files: [{ name: 'notas.pdf' }] }, preventDefault(){} });
registro.enviados.push(entrada.files.map(f => f.name).join(',') + ' | ' + nodo('elegidos-idea').textContent + ' | ' + evitado);
"""


def test_pegar_y_soltar_suman_archivos_al_mismo_campo_del_formulario(tmp_path):
    """C-0149: una captura pegada (Ctrl+V) y un archivo soltado acaban en el
    mismo `<input type=file>` que viaja con «Apuntar»; no hay otro camino."""
    r = ejecutar(script_de("tablero.html", CONTEXTO_TABLERO), tmp_path, accion=_PEGAR)
    assert r["errores"] == []
    assert r["enviados"] == ["image.png,notas.pdf | image.png · notas.pdf | true"]


def test_el_boton_adjuntar_abre_el_selector_de_su_campo(tmp_path):
    accion = """
    const campo = nodo('archivos-5');
    campo.click = () => registro.enviados.push('selector:archivos-5');
    const b = { dataset: { elegir: 'archivos-5' } };
    DOC_OYENTES.click.forEach(fn => fn({ target: { closest: (s) => s === '[data-elegir]' ? b : null } }));
    """
    r = ejecutar(script_de("tablero.html", CONTEXTO_TABLERO), tmp_path, accion=accion)
    assert r["errores"] == [] and r["enviados"] == ["selector:archivos-5"]


# ── El primer script de proyecto.html: sembrar la capa base (C-0109) ─────────
#
# `script_de` sólo tomaba el último, y éste no lo ejecutaba ningún test: el
# de arriba que dice «engancha el botón de sembrar» mira el de borrar slots,
# que también escucha `click` en el documento.

_SEMBRAR = """
HubUI.preguntar = (o) => { registro.avisos.push(o.titulo + ' | ' + o.valor); return Promise.resolve(PROMPT); };
const boton = { dataset: { proyecto: 'demo', prompt: 'Crea la capa base' }, textContent: 'Crear capa base' };
DOC_OYENTES.click.forEach(fn => fn({ target: { closest: (s) => s === '#sembrar-base' ? boton : null } }));
setTimeout(() => registro.valores.push('href=' + location.href, 'boton=' + boton.textContent), 5);
"""


def test_sembrar_la_capa_base_manda_el_prompt_editado_y_lleva_a_verlo_trabajar(tmp_path):
    r = ejecutar(script_de("proyecto.html", CONTEXTO_PROYECTO, indice=0), tmp_path,
                 respuestas={"POST /api/base/sembrar": {"ok": True, "session": "demo", "ventana": 3}},
                 accion=_SEMBRAR.replace("PROMPT", "'Crea la capa base, sin tocar src/'"))
    assert r["errores"] == []
    assert r["avisos"] == ["Crear la capa base de este proyecto | Crea la capa base"]
    assert r["enviados"] == [{"url": "/api/base/sembrar", "metodo": "POST",
                              "cuerpo": {"proyecto_id": "demo",
                                         "prompt": "Crea la capa base, sin tocar src/"}}]
    assert "href=/trabajo?session=demo&ventana=3" in r["valores"]


def test_sembrar_la_capa_base_con_el_guardrail_cerrado_lo_dice_y_no_navega(tmp_path):
    r = ejecutar(script_de("proyecto.html", CONTEXTO_PROYECTO, indice=0), tmp_path,
                 respuestas={"POST /api/base/sembrar": {"ok": False, "bloqueado": True,
                                                        "error": "guardrail never"}},
                 accion=_SEMBRAR.replace("PROMPT", "'adelante'"))
    assert r["errores"] == []
    assert {"titulo": "Guardrail activo", "mensaje": "guardrail never"} in r["avisos"]
    assert "href=" in r["valores"] and "boton=Crear capa base" in r["valores"]


def test_cancelar_el_prompt_de_la_capa_base_no_lanza_nada(tmp_path):
    r = ejecutar(script_de("proyecto.html", CONTEXTO_PROYECTO, indice=0), tmp_path,
                 accion=_SEMBRAR.replace("PROMPT", "null"))
    assert r["errores"] == [] and r["enviados"] == []
