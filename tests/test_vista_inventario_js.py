"""Ejecuta el JavaScript del inventario.

Su script es el que lanza agentes: si revienta al arrancar, los botones quedan
inertes sin ningún síntoma visible. Misma lección que la terminal en negro.
"""

from __future__ import annotations

import pytest

from arnes_js import ejecutar, script_de

CONSUMIDOR = {
    "id": "idle", "nombre": "Idle", "enlaces": [], "divergencias": [],
    "cuenta": {"igual": 3}, "deriva": 0,
    "prompt_mantenedor": "Usa el agente mantenedor…",
}

CONTEXTO = {
    "inv": {
        "capacidades": [{
            "tipo": "agente", "nombre": "dev-backend", "ruta": "/a/dev-backend.md",
            "descripcion": "Implementador backend.", "modelo": "opus", "status": "activo",
            "origen": "convencion", "modificado": "2026-08-01T00:00:00+00:00",
            "usado": None, "medible": 1, "proyecto_id": "demo", "proyecto_nombre": "Demo",
        }],
        "por_tipo": {"agente": 1}, "total": 1, "sin_uso": 1, "no_medibles": 0,
        "incompletas": 0, "tipos": ["agente"],
        "proyectos": [{"id": "demo", "nombre": "Demo"}],
    },
    "kits": [{"id": "kit", "nombre": "Kit", "consumidores": [CONSUMIDOR],
              "deriva_total": 0, "capacidades": 5}],
    "tipo": "", "proyecto": "", "titulo": "Inventario", "seccion": "inventario",
}


@pytest.fixture(scope="module")
def ejecucion(tmp_path_factory):
    return ejecutar(script_de("inventario.html", CONTEXTO), tmp_path_factory.mktemp("js"))


def test_el_script_arranca_sin_reventar(ejecucion):
    assert ejecucion["errores"] == []


def test_engancha_el_lanzador_de_agentes(ejecucion):
    """Sin este oyente los botones «Lanzar» quedan inertes y no se nota."""
    assert "document:click" in ejecucion["oyentes"]


# ── El lanzador de agentes, ejecutado de verdad (C-0109) ─────────────────────
#
# Es el PRIMER script de la plantilla y `script_de` sólo tomaba el último (el
# de «Kit nuevo»): el oyente de arriba existía en los dos, así que el test
# pasaba sin haber corrido nunca el que lanza agentes.

_LANZAR = """
HubUI.preguntar = (o) => { registro.avisos.push(o.titulo + ' | ' + o.valor); return Promise.resolve(PROMPT); };
const boton = { dataset: { titulo: 'Lanzar dev-backend', prompt: 'Usa el agente…',
                           proyecto: 'demo', nombre: 'dev-backend' }, textContent: 'Lanzar' };
DOC_OYENTES.click.forEach(fn => fn({ target: { closest: (s) => s === '.lanzar-agente' ? boton : null } }));
setTimeout(() => registro.valores.push('href=' + location.href, 'boton=' + boton.textContent), 5);
"""


def test_lanzar_un_agente_manda_el_prompt_editado_y_lleva_a_su_ventana(tmp_path):
    r = ejecutar(script_de("inventario.html", CONTEXTO, indice=0), tmp_path,
                 respuestas={"POST /api/agente/lanzar": {"ok": True, "session": "demo", "ventana": 4}},
                 accion=_LANZAR.replace("PROMPT", "'Revisa el login'"))
    assert r["errores"] == []
    assert r["avisos"] == ["Lanzar dev-backend | Usa el agente…"]
    assert r["enviados"] == [{"url": "/api/agente/lanzar", "metodo": "POST",
                              "cuerpo": {"proyecto_id": "demo", "nombre": "dev-backend",
                                         "prompt": "Revisa el login"}}]
    assert "href=/trabajo?session=demo&ventana=4" in r["valores"]


def test_lanzar_con_el_guardrail_cerrado_lo_dice_y_deja_el_boton_como_estaba(tmp_path):
    r = ejecutar(script_de("inventario.html", CONTEXTO, indice=0), tmp_path,
                 respuestas={"POST /api/agente/lanzar": {"ok": False, "bloqueado": True,
                                                         "error": "guardrail never"}},
                 accion=_LANZAR.replace("PROMPT", "'adelante'"))
    assert r["errores"] == []
    assert {"titulo": "Guardrail activo", "mensaje": "guardrail never"} in r["avisos"]
    assert "href=" in r["valores"] and "boton=Lanzar" in r["valores"]


def test_cancelar_el_prompt_no_lanza_ningun_agente(tmp_path):
    r = ejecutar(script_de("inventario.html", CONTEXTO, indice=0), tmp_path,
                 accion=_LANZAR.replace("PROMPT", "null"))
    assert r["errores"] == [] and r["enviados"] == []
