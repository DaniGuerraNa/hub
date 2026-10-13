"""El filtro de la pantalla de archivos, ejecutando su JavaScript (regla dura 11).

🔴 **El DOM sale de la página que sirve FastAPI, no de uno escrito a mano.**

Es la lección de la decisión 202, y costó cara: los tres arneses de JS de
entonces contestaban al selector que el script preguntaba, así que daban verde
sobre un panel que en pantalla decía lo contrario de la verdad. Un arnés que
responde a lo que le pregunten sólo repite la suposición de quien escribió el
script.

Aquí se pide `/archivos` de verdad, se sacan las filas del HTML servido y ésas
son las que ve el script. Si la plantilla deja de pintar `.nom`, o le cambia la
clase a las filas, estos tests se ponen rojos — que es justo lo que no pasaba
antes.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from html.parser import HTMLParser
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from hub import db, web

GUION = Path(__file__).resolve().parents[1] / "src" / "hub" / "static" / "archivos.js"


class _Filas(HTMLParser):
    """Saca de la página las filas y el texto de su `.nom`.

    Un parser mínimo y no una dependencia nueva: lo que hace falta es una lista
    de `(clases, data-fijo, nombre)`, y eso cabe en treinta líneas.
    """

    def __init__(self):
        super().__init__()
        self.filas: list[dict] = []
        self._dentro_nom = False

    def handle_starttag(self, tag, attrs):
        at = dict(attrs)
        clases = (at.get("class") or "").split()
        if "fila-arch" in clases:
            self.filas.append({"clases": clases, "fijo": "data-fijo" in at, "nom": ""})
        elif "nom" in clases and self.filas:
            self._dentro_nom = True

    def handle_endtag(self, tag):
        self._dentro_nom = False

    def handle_data(self, datos):
        if self._dentro_nom and self.filas:
            self.filas[-1]["nom"] += datos


ARNES = r"""
const FILAS = __FILAS__;

/* Cada fila con un `hidden` de verdad y su `.nom`, igual que en la página. */
const filas = FILAS.map(f => ({
  _clases: f.clases, _fijo: f.fijo, hidden: false,
  querySelector(sel) { return sel === '.nom' ? { textContent: f.nom } : null; },
}));

function casaSelector(fila, sel) {
  /* El único selector que usa el script. Se implementa de verdad —incluido el
   * `:not([data-fijo])`— porque contestar que sí a todo es justo el fallo que
   * este archivo existe para no repetir. */
  if (sel !== '.fila-arch:not([data-fijo])') throw new Error('selector no previsto: ' + sel);
  return fila._clases.includes('fila-arch') && !fila._fijo;
}

const campo = {
  id: 'filtro-arch', value: '', _oyentes: {},
  addEventListener(ev, fn) { (this._oyentes[ev] ||= []).push(fn); },
  escribir(texto) { this.value = texto; (this._oyentes['input'] || []).forEach(f => f({})); },
  closest(sel) { return sel === '.tarjeta' ? tarjeta : null; },
};
const insertados = [];
const tarjeta = { insertBefore(nodo, antes) { insertados.push(nodo); } };
const pie = { id: 'pie-arch' };

global.document = {
  getElementById(id) { return id === 'filtro-arch' ? campo : (id === 'pie-arch' ? pie : null); },
  querySelectorAll(sel) { return filas.filter(f => casaSelector(f, sel)); },
  createElement() { return { className: '', style: { cssText: '' }, hidden: false, textContent: '' }; },
};

__GUION__

__ACCION__

console.log(JSON.stringify({
  visibles: filas.map((f, i) => (f.hidden ? null : FILAS[i].nom.trim())).filter(x => x !== null),
  ocultas: filas.filter(f => f.hidden).length,
  vacio: insertados.map(n => ({ hidden: n.hidden, texto: n.textContent })),
}));
"""


def _ejecutar(filas: list[dict], accion: str, tmp_path) -> dict:
    node = shutil.which("node")
    if not node:
        pytest.skip("node no disponible")
    archivo = tmp_path / "arnes-archivos.js"
    archivo.write_text(
        ARNES.replace("__FILAS__", json.dumps(filas))
             .replace("__GUION__", GUION.read_text(encoding="utf-8"))
             .replace("__ACCION__", accion),
        encoding="utf-8",
    )
    salida = subprocess.run([node, str(archivo)], capture_output=True, text=True, timeout=30)
    assert salida.returncode == 0, salida.stderr
    return json.loads(salida.stdout.strip().splitlines()[-1])


@pytest.fixture
def pagina(tmp_path, monkeypatch):
    """La pantalla servida de verdad, sobre un árbol de mentira en el disco."""
    raiz = tmp_path / "proyectos"
    for nombre in ("api-clientes", "api-pedidos", "web-facturación", "notas.md"):
        destino = raiz / nombre
        if nombre.endswith(".md"):
            destino.parent.mkdir(parents=True, exist_ok=True)
            destino.write_text("x")
        else:
            destino.mkdir(parents=True)

    ruta_db = tmp_path / "hub.db"

    def conexion_de_pruebas():
        con = db.conectar(ruta_db)
        db.inicializar(con)
        return con

    monkeypatch.setattr(web, "conexion", conexion_de_pruebas)
    con = conexion_de_pruebas()
    con.execute(
        "INSERT INTO proyecto (id, nombre, asiento, estado_ref) VALUES ('demo','Demo',?,'E.md')",
        (str(raiz),),
    )
    con.execute(
        "INSERT INTO proyecto_ruta (proyecto_id, ruta, tipo) VALUES ('demo',?,'asiento')",
        (str(raiz),),
    )
    con.close()
    html = TestClient(web.app).get("/archivos", params={"ruta": str(raiz)}).text
    parser = _Filas()
    parser.feed(html)
    return {"html": html, "filas": parser.filas}


def test_la_pagina_pinta_las_filas_que_el_script_espera(pagina):
    """Si esto falla, todo lo demás de aquí abajo estaría probando aire."""
    nombres = [f["nom"].strip() for f in pagina["filas"] if not f["fijo"]]
    assert sorted(nombres) == ["api-clientes", "api-pedidos", "notas.md", "web-facturación"]


def test_sin_escribir_nada_se_ven_todas(pagina, tmp_path):
    r = _ejecutar(pagina["filas"], "", tmp_path)
    assert r["ocultas"] == 0


def test_escribir_tres_letras_deja_sólo_lo_que_casa(pagina, tmp_path):
    r = _ejecutar(pagina["filas"], "campo.escribir('api');", tmp_path)
    assert sorted(r["visibles"]) == ["api-clientes", "api-pedidos"]


def test_no_distingue_mayusculas(pagina, tmp_path):
    r = _ejecutar(pagina["filas"], "campo.escribir('API-PED');", tmp_path)
    assert r["visibles"] == ["api-pedidos"]


def test_no_hace_falta_escribir_la_tilde(pagina, tmp_path):
    """Las rutas que vienen de OneDrive traen nombres en castellano.

    Obligar a teclear la tilde exacta es justo el trabajo que este campo quita.
    """
    r = _ejecutar(pagina["filas"], "campo.escribir('facturacion');", tmp_path)
    assert r["visibles"] == ["web-facturación"]


def test_lo_que_no_casa_con_nada_lo_dice(pagina, tmp_path):
    r = _ejecutar(pagina["filas"], "campo.escribir('zzz');", tmp_path)
    assert r["visibles"] == []
    assert [n for n in r["vacio"] if not n["hidden"]], "tenía que salir el aviso de vacío"


def test_borrar_el_filtro_devuelve_todas(pagina, tmp_path):
    r = _ejecutar(pagina["filas"], "campo.escribir('api'); campo.escribir('');", tmp_path)
    assert r["ocultas"] == 0
    assert all(n["hidden"] for n in r["vacio"])


def test_la_fila_de_subir_no_se_filtra_nunca(pagina, tmp_path, monkeypatch):
    """Filtrar «.. subir» dejaría sin salida a quien escribe algo que no casa.

    Se comprueba sobre una carpeta de dentro, que es donde esa fila existe.
    """
    filas = [{"clases": ["fila-arch"], "fijo": True, "nom": ".. subir"}] + [
        f for f in pagina["filas"] if not f["fijo"]
    ]
    r = _ejecutar(filas, "campo.escribir('zzz');", tmp_path)
    assert r["ocultas"] == len(filas) - 1  # todas menos la fija


# ───────────────────────── la trampa de la 202 ─────────────────────────


def test_el_css_deshace_el_hidden_del_navegador_para_estas_filas(pagina):
    """🔴 Sin esta regla el filtro no esconde NADA, y no da ningún error.

    `.fila-arch { display:flex }` y el `[hidden]` del navegador tienen la misma
    especificidad, así que gana la última escrita —la de la plantilla— y
    `el.hidden = true` queda sin efecto visible. Es exactamente el fallo de la
    decisión 202, que salió por otro sitio y costó dos causas y tres archivos.

    El arnés de JavaScript NO puede verlo: ahí `hidden` es una propiedad y no
    hay CSS. Por eso se comprueba sobre el HTML servido.
    """
    css = " ".join(re.findall(r"<style>(.*?)</style>", pagina["html"], re.S))
    assert re.search(r"\.fila-arch\s*\[hidden\]\s*\{[^}]*display\s*:\s*none", css), (
        "falta `.fila-arch[hidden] { display:none }`: el filtro dejaría de esconder"
    )
