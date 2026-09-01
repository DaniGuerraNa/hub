"""La barra lateral de /trabajo: qué se enseña y con qué jerarquía.

Sale de un fallo de lectura real. La barra pintaba proyectos, slots y el rótulo
«Sesiones tmux» con estilos equivalentes, y el subtítulo del slot mostraba sólo
el último segmento de su ruta. Con el slot «respaldo pendiente» en
`~/dev/tienda`, eso daba:

    TIENDA                ← proyecto
      respaldo pendiente  ← slot
      tienda              ← ruta del slot, idéntica al nombre del proyecto

y se leía como si existieran dos proyectos Tienda. No los había: uno solo.
Aquí se fija lo que hace que eso no vuelva.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hub import api, slots, snapshotter, tmux
from hub.models import Proyecto
from hub.registry import Atribuidor

# El home real: `ruta_corta` abrevia el del usuario que corre el hub, y cablear
# uno concreto haría pasar el test sólo en la máquina donde se escribió.
HOME = str(Path.home())


# ── la ruta tiene que leerse como una ruta ────────────────────────────────────

@pytest.mark.parametrize(
    "entrada,esperado",
    [
        (f"{HOME}/dev/tienda", "~/dev/tienda"),
        (HOME, "~"),
        ("/mnt/c/Users/ana/Escritorio/trabajo/plataforma", "…/trabajo/plataforma"),
        ("/tmp/demo", "/tmp/demo"),               # ya es corta: se deja entera
        (f"{HOME}/dev/tienda/", "~/dev/tienda"),  # sin barra final
        (None, ""),
        ("", ""),
    ],
)
def test_ruta_corta(entrada, esperado):
    assert api.ruta_corta(entrada) == esperado


def test_ruta_corta_conserva_el_padre():
    """Un solo segmento no distingue: el padre es lo que desambigua."""
    a = api.ruta_corta("/mnt/c/proyectos/tienda-main/web")
    b = api.ruta_corta("/mnt/c/otro/sitio/web")
    assert a != b


def test_el_slot_trae_su_ruta_corta(con):
    con.execute("INSERT INTO proyecto (id, nombre) VALUES ('tienda','Tienda')")
    slots.crear(con, "tienda", "respaldo pendiente", ruta=f"{HOME}/dev/tienda")
    (s,) = api.slots_de(con, "tienda")
    # El fallo original: el subtítulo era «tienda», igual que el proyecto.
    assert s["ruta_corta"] == "~/dev/tienda"
    assert s["ruta_corta"] != "tienda"


# ── la bandeja: sólo lo que sigue sin organizar ───────────────────────────────

@pytest.fixture
def escena(con, monkeypatch):
    """Una sesión con dos ventanas y otra con una, como la máquina real."""
    con.execute("INSERT INTO proyecto (id, nombre, asiento) VALUES ('demo','Demo','/tmp/demo')")
    monkeypatch.setattr(tmux, "servidor_pid", lambda: 100)
    monkeypatch.setattr(tmux, "rama_git", lambda cwd: None)
    monkeypatch.setattr(
        tmux, "listar_paneles",
        lambda *a, **k: [
            {"session": "work", "window_idx": 0, "pane_idx": 0, "pane_id": "%1",
             "cwd": "/tmp/demo", "titulo": "Back", "comando": "claude", "activo": True},
            {"session": "work", "window_idx": 1, "pane_idx": 0, "pane_id": "%2",
             "cwd": "/tmp/demo", "titulo": "Front", "comando": "claude", "activo": False},
            {"session": "suelta", "window_idx": 0, "pane_idx": 0, "pane_id": "%3",
             "cwd": "/tmp/demo", "titulo": "Otra", "comando": "bash", "activo": False},
        ],
    )
    snapshotter.capturar(
        con, Atribuidor([Proyecto(id="demo", nombre="Demo", asiento="/tmp/demo")])
    )
    return con


SESIONES = [{"session": "work", "paneles": 2}, {"session": "suelta", "paneles": 1}]


def test_sin_slots_todas_estan_pendientes(escena):
    pendientes, organizadas = api.clasificar_sesiones(
        SESIONES, api.paneles_abiertos(escena)
    )
    assert [s["session"] for s in pendientes] == ["work", "suelta"]
    assert organizadas == []


def test_vincular_una_ventana_no_organiza_la_sesion(escena):
    """`work:0` en un slot deja `work:1` suelta: la sesión sigue en la bandeja.

    Ocultarla aquí dejaría a la ventana 1 sin ningún camino para llegar a ella.
    """
    slot_id = slots.crear(escena, "demo", "Trabajo")
    slots.vincular(escena, "%1", slot_id)

    pendientes, organizadas = api.clasificar_sesiones(
        SESIONES, api.paneles_abiertos(escena)
    )
    work = next(s for s in pendientes if s["session"] == "work")
    assert work["sin_slot"] == 1 and work["ventanas"] == 2
    assert organizadas == []


def test_con_todas_las_ventanas_en_slots_sale_de_la_bandeja(escena):
    slot_id = slots.crear(escena, "demo", "Trabajo")
    slots.vincular(escena, "%1", slot_id)
    slots.vincular(escena, "%2", slot_id)

    pendientes, organizadas = api.clasificar_sesiones(
        SESIONES, api.paneles_abiertos(escena)
    )
    assert [s["session"] for s in pendientes] == ["suelta"]
    assert [s["session"] for s in organizadas] == ["work"]


def test_la_sesion_que_se_mira_nunca_se_oculta(escena):
    """Verla desaparecer en el momento de vincularla es desorientador."""
    slot_id = slots.crear(escena, "demo", "Trabajo")
    slots.vincular(escena, "%1", slot_id)
    slots.vincular(escena, "%2", slot_id)

    pendientes, organizadas = api.clasificar_sesiones(
        SESIONES, api.paneles_abiertos(escena), session_actual="work"
    )
    assert [s["session"] for s in pendientes] == ["work", "suelta"]
    assert organizadas == []


def test_una_sesion_que_el_snapshotter_no_ha_visto_sigue_visible(escena):
    """Sin paneles conocidos no se puede afirmar que esté organizada."""
    sesiones = [*SESIONES, {"session": "recien-creada", "paneles": 1}]
    pendientes, _ = api.clasificar_sesiones(sesiones, api.paneles_abiertos(escena))
    assert "recien-creada" in [s["session"] for s in pendientes]


# ── la jerarquía que ve el navegador ──────────────────────────────────────────

def test_en_uso_marca_los_proyectos_con_algo_que_mirar(escena):
    slots.crear(escena, "demo", "Trabajo")
    ctx = api.contexto_trabajo(escena, session="work", ventana=0)
    demo = next(p for p in ctx["proyectos"] if p["id"] == "demo")
    assert demo["en_uso"] is True


def test_un_proyecto_sin_slots_ni_ventanas_no_entra_en_la_barra(escena):
    escena.execute("INSERT INTO proyecto (id, nombre) VALUES ('quieto','Quieto')")
    ctx = api.contexto_trabajo(escena, session="work", ventana=0)
    quieto = next(p for p in ctx["proyectos"] if p["id"] == "quieto")
    assert quieto["en_uso"] is False
