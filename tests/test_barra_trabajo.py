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


# ── el punto de estado ────────────────────────────────────────────────────────
#
# Sale de una pregunta suya: *"si tengo un segundo slot en ejecución y ese
# termina o se pausa para hacerme preguntas, quiero enterarme"*. El dato ya
# estaba en la base —`panel.titulo` se guarda con el glifo crudo de Claude
# Code— y no se usaba para nada.

@pytest.mark.parametrize(
    "panel,esperado",
    [
        # El spinner braille: está pensando.
        ({"titulo": "⠂ Continuar con los pendientes", "comando": "claude"}, "trabajando"),
        ({"titulo": "⠐ Otra cosa", "comando": "claude"}, "trabajando"),
        # ✳ es Claude quieto. NO se puede saber si acabó o si te espera.
        ({"titulo": "✳ Confirmar comprensión", "comando": "claude"}, "detenido"),
        # Una shell no reporta nada: tmux le pone el hostname.
        ({"titulo": "DESKTOP", "comando": "bash"}, "otro"),
        # 🔴 Los dos que me habrían salido mal mirando `pane_current_command`:
        # otro programa no es un asistente detenido...
        ({"titulo": "informe.md", "comando": "vim"}, "otro"),
        # ...y un panel recién abierto todavía no tiene título propio.
        ({"titulo": "", "comando": "claude"}, "otro"),
    ],
)
def test_estado_de_panel(panel, esperado):
    assert api.estado_de_panel(panel) == esperado


def test_un_slot_sin_panel_esta_cerrado():
    """None y «otro» no son lo mismo: uno no tiene ventana, el otro sí."""
    assert api.estado_de_panel(None) == "cerrado"


def test_el_glifo_tiene_una_sola_definicion():
    """El asistente y la barra leen «está pensando» del mismo sitio.

    Estaba duplicado en `asistente._es_spinner`. Dos copias del rango braille
    son dos definiciones que pueden separarse sin que nada avise.
    """
    from hub import asistente
    assert not hasattr(asistente, "_es_spinner")
    assert tmux.es_spinner("⠂ x") and not tmux.es_spinner("✳ x")


@pytest.fixture
def escena_con_estados(con, monkeypatch):
    """Dos slots del mismo proyecto: uno pensando y otro quieto."""
    con.execute("INSERT INTO proyecto (id, nombre, asiento) VALUES ('demo','Demo','/tmp/demo')")
    monkeypatch.setattr(tmux, "servidor_pid", lambda: 100)
    monkeypatch.setattr(tmux, "rama_git", lambda cwd: None)
    monkeypatch.setattr(
        tmux, "listar_paneles",
        lambda *a, **k: [
            {"session": "work", "window_idx": 0, "pane_idx": 0, "pane_id": "%1",
             "cwd": "/tmp/demo", "titulo": "⠂ Migrando", "comando": "claude", "activo": True},
            {"session": "work", "window_idx": 1, "pane_idx": 0, "pane_id": "%2",
             "cwd": "/tmp/demo", "titulo": "✳ Listo", "comando": "claude", "activo": False},
        ],
    )
    return con


def _slots_de_demo(con):
    ctx = api.contexto_trabajo(con, session="work", ventana=0)
    demo = next(p for p in ctx["proyectos"] if p["id"] == "demo")
    return {s["nombre"]: s["estado"] for s in demo["slots"]}


def test_cada_slot_trae_el_estado_de_su_panel(escena_con_estados):
    a = slots.crear(escena_con_estados, "demo", "Migración")
    b = slots.crear(escena_con_estados, "demo", "Revisión")
    c = slots.crear(escena_con_estados, "demo", "Sin abrir")
    snapshotter.capturar(
        escena_con_estados,
        Atribuidor([Proyecto(id="demo", nombre="Demo", asiento="/tmp/demo")]),
    )
    slots.vincular(escena_con_estados, "%1", a)
    slots.vincular(escena_con_estados, "%2", b)
    assert c  # existe, pero no tiene panel

    estados = _slots_de_demo(escena_con_estados)
    assert estados == {
        "Migración": "trabajando",
        "Revisión": "detenido",
        "Sin abrir": "cerrado",
    }


def test_los_cuatro_estados_tienen_estilo():
    """Un estado sin CSS se pinta con el punto de acento y miente.

    Es el fallo probable al añadir uno nuevo: se toca `estado_de_panel` y se
    olvida la hoja de estilo, que está en otro archivo.
    """
    html = (Path(__file__).parents[1] / "src/hub/templates/trabajo.html").read_text("utf-8")
    for estado in ("trabajando", "detenido", "otro", "cerrado"):
        assert f".punto.{estado}" in html, f"«{estado}» no tiene estilo"
    # Lo único que se mueve es «trabajando»: si el detenido también pulsara, la
    # barra entera parecería una alarma.
    assert "prefers-reduced-motion" in html


# ── el latido: que el punto no se quede congelado ─────────────────────────────
#
# El punto existe para enterarse de que un segundo slot paró. Pintado sólo al
# cargar la página, se enteraba únicamente quien recargara — o sea, lo contrario
# de para lo que se hizo.

def _escena_pulsante(con):
    """La escena de estados, ya capturada y con los dos slots vinculados."""
    a = slots.crear(con, "demo", "Migración")
    b = slots.crear(con, "demo", "Revisión")
    slots.crear(con, "demo", "Sin abrir")
    snapshotter.capturar(
        con, Atribuidor([Proyecto(id="demo", nombre="Demo", asiento="/tmp/demo")])
    )
    slots.vincular(con, "%1", a)
    slots.vincular(con, "%2", b)
    return a, b


def test_el_pulso_da_el_estado_de_todos_los_slots_activos(escena_con_estados):
    """Todos, no sólo los del proyecto abierto: el raíl los enseña todos."""
    a, b = _escena_pulsante(escena_con_estados)
    slots_ = api.pulso_trabajo(escena_con_estados)["slots"]
    assert slots_[a] == "trabajando"
    assert slots_[b] == "detenido"
    assert len(slots_) == 3  # el tercero, sin panel, también viene: «cerrado»


def test_el_pulso_dice_lo_mismo_que_el_primer_pintado(escena_con_estados):
    """Dos caminos para el mismo dato es dos formas de que uno mienta.

    El servidor pinta el punto con `contexto_trabajo` y el navegador lo repinta
    con `pulso_trabajo`. Si divergen, la página cambia de opinión sola a los
    cinco segundos sin que haya pasado nada.
    """
    _escena_pulsante(escena_con_estados)
    del_pulso = api.pulso_trabajo(escena_con_estados)["slots"]
    ctx = api.contexto_trabajo(escena_con_estados, session="work", ventana=0)
    demo = next(p for p in ctx["proyectos"] if p["id"] == "demo")
    assert {s["id"]: s["estado"] for s in demo["slots"]} == del_pulso


def test_el_pulso_solo_trae_las_notas_que_se_le_piden(escena_con_estados):
    """Las notas son texto largo y el latido va cada cinco segundos.

    Se piden las del panel derecho —una o dos— y no las de los veinte slots.
    """
    a, b = _escena_pulsante(escena_con_estados)
    api.guardar_nota(escena_con_estados, a, "lo que quedó pendiente")
    api.guardar_nota(escena_con_estados, b, "no debería viajar")
    assert api.pulso_trabajo(escena_con_estados, [a])["notas"] == {
        a: "lo que quedó pendiente"
    }


def test_el_pulso_no_se_cae_con_un_slot_que_ya_no_existe(escena_con_estados):
    """La página lleva horas abierta: el slot que pide pudo borrarse."""
    _escena_pulsante(escena_con_estados)
    assert api.pulso_trabajo(escena_con_estados, [9999])["notas"] == {}


def test_el_punto_lleva_el_id_de_su_slot(escena_con_estados):
    """Sin esto el latido no sabe qué punto es de quién.

    Es el fallo silencioso de este cambio: el HTML se sirve igual de bien, el
    latido corre, y ningún punto se actualiza nunca.
    """
    html = (Path(__file__).parents[1] / "src/hub/templates/trabajo.html").read_text("utf-8")
    assert "data-slot-punto" in html
    # El JS lo lee por `dataset`, que camelliza el guión. Un `data-slotPunto`
    # en el HTML no existiría para él.
    assert "dataset.slotPunto" in html


# ── atar una ventana a un trabajo de otro proyecto ────────────────────────────
#
# La ruta no siempre dice de qué va el trabajo: se puede estar en una carpeta
# cualquiera hablando del hub. Hasta aquí la barra sólo ofrecía slots del
# proyecto que salía del `cwd`, así que ese caso no tenía salida ninguna — el
# panel explicaba por qué no se podía hacer nada y la ventana se quedaba fuera.

@pytest.fixture
def escena_ajena(con, monkeypatch):
    """Dos proyectos, y una ventana en una carpeta que no es de ninguno."""
    con.execute("INSERT INTO proyecto (id, nombre, asiento) VALUES ('demo','Demo','/tmp/demo')")
    con.execute("INSERT INTO proyecto (id, nombre, asiento) VALUES ('hub','Hub','/tmp/hub')")
    monkeypatch.setattr(tmux, "servidor_pid", lambda: 100)
    monkeypatch.setattr(tmux, "rama_git", lambda cwd: None)
    monkeypatch.setattr(
        tmux, "listar_paneles",
        lambda *a, **k: [
            {"session": "suelta", "window_idx": 0, "pane_idx": 0, "pane_id": "%9",
             "cwd": "/tmp/en-ningun-sitio", "titulo": "✳ Hablando del hub",
             "comando": "claude", "activo": True},
        ],
    )
    snapshotter.capturar(
        con,
        Atribuidor([
            Proyecto(id="demo", nombre="Demo", asiento="/tmp/demo"),
            Proyecto(id="hub", nombre="Hub", asiento="/tmp/hub"),
        ]),
    )
    return con


def _ventana(con):
    return api.contexto_trabajo(con, session="suelta", ventana=0)["vinculable"]


def test_slots_activos_traen_el_nombre_de_su_proyecto(escena_ajena):
    """Sin el nombre, el desplegable enseña dos «Main» y no se sabe cuál es cuál."""
    slots.crear(escena_ajena, "hub", "Hub - Dev")
    (s,) = api.slots_activos(escena_ajena)
    assert s["proyecto_nombre"] == "Hub"


def test_una_ventana_sin_proyecto_puede_atarse_a_un_slot_existente(escena_ajena):
    """El caso que no tenía salida: sin proyecto no se ofrecía NADA."""
    slot_id = slots.crear(escena_ajena, "hub", "Hub - Dev")
    v = _ventana(escena_ajena)

    assert v["proyecto_id"] is None      # la ruta sigue sin ser de nadie
    assert not v["slots"]                # y por eso no hay hermanos
    assert [s["id"] for s in v["slots_ajenos"]] == [slot_id]


def test_vincular_a_otro_proyecto_cambia_el_trabajo_pero_no_la_ruta(escena_ajena):
    """🔴 Los dos proyectos hacen falta y significan cosas distintas.

    `proyecto_id` es un hecho de la ruta y decide si se puede CREAR un slot.
    `proyecto_efectivo` es de qué trabajo es la ventana, y es lo que miran la
    nota y los lienzos. Colapsarlos hacía que una ventana vinculada a un slot
    de otro proyecto enseñara los lienzos del proyecto de su carpeta.
    """
    slot_id = slots.crear(escena_ajena, "hub", "Hub - Dev")
    slots.vincular(escena_ajena, "%9", slot_id)

    v = _ventana(escena_ajena)
    assert v["proyecto_efectivo"] == "hub"
    assert v["proyecto_id"] is None
    assert v["slot"]["id"] == slot_id


def test_mover_no_ofrece_el_slot_en_el_que_ya_estas(escena_ajena):
    a = slots.crear(escena_ajena, "hub", "Hub - Dev")
    slots.crear(escena_ajena, "demo", "Otro")
    slots.vincular(escena_ajena, "%9", a)

    v = _ventana(escena_ajena)
    assert a not in [s["id"] for s in v["slots_ajenos"]]
    assert [s["nombre"] for s in v["slots_ajenos"]] == ["Otro"]


def test_el_desplegable_de_otro_proyecto_sale_en_el_html(escena_ajena):
    """Que el dato exista no basta: la plantilla tenía que ofrecerlo."""
    slots.crear(escena_ajena, "hub", "Hub - Dev")
    html = (Path(__file__).parents[1] / "src/hub/templates/trabajo.html").read_text("utf-8")
    # El bloque «Sin proyecto» ya no es sólo una explicación de por qué no.
    assert "Atarla a un slot que ya existe" in html
    assert "opciones_de_slot([], v.slots_ajenos)" in html
    # Y el panel de lienzos mira el proyecto del trabajo, no el de la carpeta.
    assert 'data-proyecto="{{ v.proyecto_efectivo or \'\' }}"' in html
