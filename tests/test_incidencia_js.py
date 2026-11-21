"""Contar un fallo o una idea, ejecutando su JavaScript (regla dura 11, C-0468).

`incidencia.js` es quien arma el enlace a GitHub: si arranca mal, la página
se sirve perfecta y el botón abre un formulario vacío. Aquí se ejecuta con el
arnés y se mira lo que de verdad saldría: la URL, la vista previa y lo que
llega al portapapeles.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient

from arnes_js import ESTATICOS, ejecutar, script_estatico
from hub import config, db, incidencias, version, web

GUION = script_estatico("incidencia.js")
DESTINO = "https://github.com/alguien/hub/issues/new"
EQUIPO = "Versión del hub: 0.8.0\nPython: 3.12.3"


def _pagina(destino: str = DESTINO, limite: int = incidencias.LIMITE_URL) -> str:
    """La pantalla como la deja el servidor: los nodos con sus datos."""
    tipos = {clave: {"plantilla": plantilla, **incidencias.ROTULOS[clave]}
             for clave, plantilla in incidencias.TIPOS.items()}
    return f"""
      const raiz = nodo('incidencia');
      raiz.dataset = {{ destino: {json.dumps(destino)}, limite: '{limite}',
                        tipos: {json.dumps(' '.join(incidencias.TIPOS))} }};
      const tipos = {json.dumps(tipos)};
      for (const [clave, t] of Object.entries(tipos)) {{
        const r = nodo('tipo-' + clave);
        r.dataset = {{ plantilla: t.plantilla, campo: t.campo, ejemplo: t.ejemplo }};
        r.checked = clave === 'fallo';
      }}
      nodo('inc-con-equipo').checked = true;
      nodo('inc-equipo').textContent = {json.dumps(EQUIPO)};
      nodo('inc-titulo').value = 'No abre la ventana';
    """


def _lee(extra: str = "") -> str:
    return extra + """
      registro.vista = nodo('inc-vista').value;
      registro.href = nodo('inc-abrir').href || null;
      registro.oculto = nodo('inc-recortado').hidden;
      registro.rotulo = nodo('inc-campo').textContent;
    """


def _consulta(url: str) -> dict[str, list[str]]:
    partes = urlsplit(url)
    assert f"{partes.scheme}://{partes.netloc}{partes.path}" == DESTINO
    return parse_qs(partes.query)


def test_armar_rellena_la_plantilla_por_sus_campos_y_nada_mas(tmp_path):
    r = ejecutar(GUION, tmp_path, accion="""
      registro.armado = HubIncidencia.armar({ destino: '%s', plantilla: 'fallo.yml', titulo: 'No abre & cierra',
        que_paso: 'Pulsé «Lanzar»\\ny nada', equipo: 'Python: 3.12', limite: 6000 });
    """ % DESTINO)

    assert r["errores"] == []
    assert r["armado"]["recortado"] is False
    consulta = _consulta(r["armado"]["url"])
    assert consulta == {"template": ["fallo.yml"], "title": ["No abre & cierra"],
                        "que_paso": ["Pulsé «Lanzar»\ny nada"], "equipo": ["Python: 3.12"]}
    assert set(consulta) <= {"template", "title", *incidencias.CAMPOS}


def test_sin_destino_no_hay_enlace(tmp_path):
    r = ejecutar(GUION, tmp_path, accion="""
      registro.armado = HubIncidencia.armar({ destino: '', plantilla: 'fallo.yml', titulo: 'x', limite: 6000 });
    """)
    assert r["armado"] == {"url": None, "recortado": False}


def test_lo_que_no_cabe_en_el_enlace_se_queda_fuera_y_se_dice(tmp_path):
    r = ejecutar(GUION, tmp_path, accion="""
      registro.armado = HubIncidencia.armar({ destino: '%s', plantilla: 'mejora.yml', titulo: 'Larga',
        que_paso: 'ñ'.repeat(3000), equipo: 'Python: 3.12', limite: %d });
    """ % (DESTINO, incidencias.LIMITE_URL))

    assert r["armado"]["recortado"] is True
    assert len(r["armado"]["url"]) <= incidencias.LIMITE_URL
    assert _consulta(r["armado"]["url"]) == {"template": ["mejora.yml"], "title": ["Larga"],
                                             "equipo": ["Python: 3.12"]}


def test_al_cargar_la_vista_previa_y_el_enlace_dicen_lo_mismo(tmp_path):
    r = ejecutar(GUION, tmp_path, previo=_pagina(), accion=_lee("""
      nodo('inc-que-paso').value = 'Pulsé Lanzar';
      nodo('inc-que-paso').disparar('input');
    """))

    assert r["errores"] == []
    assert r["vista"] == ("Título: No abre la ventana\n\n### Qué pasó\n\nPulsé Lanzar\n\n"
                          f"### Datos del equipo\n\n{EQUIPO}")
    assert _consulta(r["href"]) == {"template": ["fallo.yml"], "title": ["No abre la ventana"],
                                    "que_paso": ["Pulsé Lanzar"], "equipo": [EQUIPO]}
    assert r["oculto"] is True


def test_quitar_los_datos_del_equipo_los_quita_de_la_vista_y_del_enlace(tmp_path):
    r = ejecutar(GUION, tmp_path, previo=_pagina(), accion=_lee("""
      nodo('inc-con-equipo').checked = false;
      nodo('inc-con-equipo').disparar('change');
    """))

    assert "Datos del equipo" not in r["vista"] and "Python" not in r["vista"]
    assert "equipo" not in _consulta(r["href"])


def test_cambiar_a_una_idea_cambia_el_campo_y_la_plantilla(tmp_path):
    r = ejecutar(GUION, tmp_path, previo=_pagina(), accion=_lee("""
      nodo('tipo-fallo').checked = false;
      nodo('tipo-mejora').checked = true;
      nodo('tipo-mejora').disparar('change');
      registro.ejemplo = nodo('inc-que-paso').placeholder;
    """))

    assert r["rotulo"] == "Qué te gustaría"
    assert "### Qué te gustaría" in r["vista"]
    assert r["ejemplo"] == incidencias.ROTULOS["mejora"]["ejemplo"]
    assert _consulta(r["href"])["template"] == ["mejora.yml"]


def test_copiar_lleva_al_portapapeles_lo_mismo_que_se_ve(tmp_path):
    r = ejecutar(GUION, tmp_path, previo=_pagina(), accion=_lee("""
      nodo('inc-copiar').disparar('click');
    """))

    assert r["portapapeles"] == [r["vista"]]
    assert r["avisos"] == []


def test_sin_portapapeles_se_selecciona_el_texto_y_se_dice(tmp_path):
    """Fuera de https o de la propia máquina, el navegador no da portapapeles."""
    r = ejecutar(GUION, tmp_path, previo=_pagina() + "globalThis.CLIPBOARD_FALLA = true;", accion="""
      nodo('inc-vista').select = () => { registro.seleccionado = true; };
      nodo('inc-copiar').disparar('click');
    """)

    assert r["portapapeles"] == []
    assert r["seleccionado"] is True
    assert r["avisos"] and r["avisos"][0]["titulo"] == "Cópialo tú"


def test_si_no_cabe_abrir_lo_copia_en_el_mismo_clic_y_deja_abrir(tmp_path):
    r = ejecutar(GUION, tmp_path, previo=_pagina(), accion=_lee("""
      nodo('inc-que-paso').value = 'x'.repeat(7000);
      nodo('inc-que-paso').disparar('input');
      registro.prevenido = false;
      nodo('inc-abrir').disparar('click', { preventDefault() { registro.prevenido = true; } });
    """))

    assert r["oculto"] is False
    assert "que_paso" not in _consulta(r["href"])
    assert r["portapapeles"] == ["(execCommand)"]
    assert r["prevenido"] is False


def test_si_no_se_pudo_copiar_para_una_vez_y_avisa(tmp_path):
    r = ejecutar(GUION, tmp_path, previo=_pagina() + "globalThis.EXECCOMMAND_FALLA = true;", accion="""
      nodo('inc-que-paso').value = 'x'.repeat(7000);
      nodo('inc-que-paso').disparar('input');
      registro.prevenidos = 0;
      const clic = { preventDefault() { registro.prevenidos += 1; } };
      nodo('inc-abrir').disparar('click', clic);
      nodo('inc-abrir').disparar('click', clic);
    """)

    assert r["prevenidos"] == 1
    assert len(r["avisos"]) == 1 and r["avisos"][0]["titulo"] == "Cópialo antes de abrir"


def test_sin_destino_solo_se_copia(tmp_path):
    r = ejecutar(GUION, tmp_path, previo=_pagina(destino=""), accion="""
      registro.oyentesAbrir = Object.keys(nodo('inc-abrir')._oyentes);
      nodo('inc-copiar').disparar('click');
    """)

    assert r["errores"] == []
    assert r["oyentesAbrir"] == []
    assert len(r["portapapeles"]) == 1


# ── el script y la pantalla hablan de los mismos nodos ───────────────────────


@pytest.fixture
def http(monkeypatch):
    def conexion():
        con = db.conectar(config.DB_PATH)
        db.inicializar(con)
        return con
    monkeypatch.setattr(web, "conexion", conexion)
    return TestClient(web.app)


@pytest.mark.parametrize("repo", ["alguien/hub", None])
def test_cada_nodo_que_busca_el_script_esta_en_la_pantalla(http, monkeypatch, repo):
    """El arnés da un nodo a cualquier id: sin esto, un id renombrado en la
    plantilla pasaría aquí y en el navegador dejaría el script sin arrancar."""
    monkeypatch.setattr(version, "repo_github", lambda raiz=None: repo)
    html = http.get("/incidencia").text
    texto = (ESTATICOS / "incidencia.js").read_text(encoding="utf-8")
    pedidos = set(re.findall(r"\$\('([\w-]+)'\)", texto)) | {"incidencia"}
    pedidos |= {f"tipo-{clave}" for clave in incidencias.TIPOS}
    if not repo:
        pedidos.discard("inc-abrir")  # sin destino no se pinta, y el script no lo busca
    faltan = sorted(i for i in pedidos if f'id="{i}"' not in html)
    assert not faltan, faltan
    assert '<script src="/static/incidencia.js"></script>' in html
