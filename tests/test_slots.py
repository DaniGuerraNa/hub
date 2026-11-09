"""Slots y bandeja de entrada.

Regla de fondo: el hub informa, no gestiona. Nada se archiva ni se borra solo.
"""

from __future__ import annotations

import pytest

from hub import api, slots, snapshotter, tmux
from hub.models import Proyecto
from hub.registry import Atribuidor


@pytest.fixture(autouse=True)
def tmux_de_la_muestra(monkeypatch):
    """El servidor de tmux es el de la muestra de mentira (pid 100), no el de la
    máquina donde corre la suite.

    🔴 `vincular` le pregunta el epoch al tmux REAL. Sin esto, el resultado
    dependía de si quien corre los tests tiene tmux abierto: aquí lo está, el
    pid no casaba con el 100 de la muestra y la separación de ventanas fallaba;
    en una máquina recién instalada, sin tmux, pasaba. Un test cuyo veredicto
    depende de la máquina no prueba nada.
    """
    monkeypatch.setattr(tmux, "servidor_pid", lambda: 100)


@pytest.fixture
def escena(con, monkeypatch):
    con.execute("INSERT INTO proyecto (id, nombre, asiento) VALUES ('demo','Demo','/tmp/demo')")
    monkeypatch.setattr(tmux, "servidor_pid", lambda: 100)
    monkeypatch.setattr(tmux, "rama_git", lambda cwd: None)
    monkeypatch.setattr(
        tmux,
        "listar_paneles",
        lambda: [
            {
                "session": "demo", "window_idx": 0, "pane_idx": 0, "pane_id": "%1",
                "cwd": "/tmp/demo", "titulo": "⠂ Investigar el gate",
                "comando": "claude", "activo": True,
            }
        ],
    )
    snapshotter.capturar(
        con, Atribuidor([Proyecto(id="demo", nombre="Demo", asiento="/tmp/demo")])
    )
    return con


def test_un_panel_sin_slot_cae_a_la_bandeja(escena):
    bandeja = api.bandeja(escena)
    assert len(bandeja) == 1
    assert bandeja[0]["etiqueta"] == "Investigar el gate"


def test_promover_crea_el_slot_y_lo_saca_de_la_bandeja(escena):
    slot_id = slots.promover(escena, "%1", "investigación")
    assert slot_id is not None

    slot = api.obtener_slot(escena, slot_id)
    assert slot["nombre"] == "investigación"
    assert slot["ruta"] == "/tmp/demo"
    assert api.bandeja(escena) == []


def test_promover_usa_la_etiqueta_si_no_se_da_nombre(escena):
    slot_id = slots.promover(escena, "%1", "")
    assert api.obtener_slot(escena, slot_id)["nombre"] == "Investigar el gate"


def test_descartar_saca_de_la_bandeja_sin_crear_slot(escena):
    slots.descartar(escena, "%1")
    assert api.bandeja(escena) == []
    assert api.slots_de(escena, "demo") == []


def test_archivar_conserva_el_slot_y_su_nota(escena):
    slot_id = slots.crear(escena, "demo", "back", nota="nota larga que debe sobrevivir")
    slots.archivar(escena, slot_id)

    assert api.slots_de(escena, "demo") == []
    archivados = api.slots_de(escena, "demo", incluir_archivados=True)
    assert len(archivados) == 1
    assert archivados[0]["nota"] == "nota larga que debe sobrevivir"


def test_la_nota_sobrevive_al_cambio_de_proyecto(escena):
    escena.execute("INSERT INTO proyecto (id, nombre) VALUES ('otro','Otro')")
    slot_id = slots.crear(escena, "demo", "investigación", nota="contexto acumulado")

    slots.editar(escena, slot_id, proyecto_id="otro")

    slot = api.obtener_slot(escena, slot_id)
    assert slot["proyecto_id"] == "otro"
    assert slot["nota"] == "contexto acumulado"


def test_mover_a_un_proyecto_que_no_existe_se_niega_con_su_nombre(escena):
    """La clave ajena lo frenaba con una `IntegrityError`, y la web la
    enseñaba como «el índice del hub no se puede leer» (C-0103)."""
    slot_id = slots.crear(escena, "demo", "investigación")

    with pytest.raises(ValueError, match="no hay ningún proyecto «no-existe»"):
        slots.editar(escena, slot_id, nombre="otro nombre", proyecto_id="no-existe")

    slot = api.obtener_slot(escena, slot_id)
    assert (slot["proyecto_id"], slot["nombre"]) == ("demo", "investigación")


def test_borrar_es_definitivo(escena):
    slot_id = slots.crear(escena, "demo", "temporal")
    slots.borrar(escena, slot_id)
    assert api.obtener_slot(escena, slot_id) is None


def test_comando_manual_para_copiar_a_mano(escena):
    slot_id = slots.crear(escena, "demo", "back", ruta="/tmp/demo", autostart_claude=True)
    comando = slots.comando_manual(escena, slot_id)
    assert "tmux new-window" in comando
    assert "/tmp/demo" in comando
    assert comando.endswith("claude")


# --------------------------------------------------------------------------- #
# Resolver el slot al entrar por una sesión
# --------------------------------------------------------------------------- #


def _panel(con, pane_id, session, ventana, slot_id=None):
    """Un panel en el snapshot actual, sin pasar por tmux."""
    actual = api.snapshot_actual(con)
    if not actual:
        con.execute(
            "INSERT INTO snapshot (tomado_en, server_pid, preservado) VALUES (?,?,0)",
            ("2026-08-28T18:00:00+00:00", 100),
        )
        actual = api.snapshot_actual(con)
    con.execute(
        """INSERT INTO panel (snapshot_id, pane_id, session, window_idx, pane_idx,
                              cwd, titulo, comando, etiqueta, proyecto_id, slot_id)
           VALUES (?,?,?,?,0,'/tmp/demo','t','claude','t','demo',?)""",
        (actual["id"], pane_id, session, ventana, slot_id),
    )


def test_entrar_por_una_sesion_resuelve_el_slot_de_esa_ventana(con, proyecto_demo):
    """Entrar por `?session=` es el atajo de la bandeja. Si esa ventana YA tiene
    slot y no se resuelve, la nota no aparece y el único camino para escribirla
    es el rodeo por el proyecto — que es justo lo que el atajo evitaba."""
    slot_id = slots.crear(con, proyecto_demo, "back")
    _panel(con, "%1", "work", 0, slot_id=slot_id)
    _panel(con, "%2", "work", 1)

    ctx = api.contexto_trabajo(con, session="work", ventana=0)
    assert ctx["slot"]["id"] == slot_id and ctx["slot"]["nombre"] == "back"


def test_una_ventana_sin_slot_sigue_sin_nota(con, proyecto_demo):
    slot_id = slots.crear(con, proyecto_demo, "back")
    _panel(con, "%1", "work", 0, slot_id=slot_id)
    _panel(con, "%2", "work", 1)

    assert api.contexto_trabajo(con, session="work", ventana=1)["slot"] is None


def test_con_varios_slots_en_la_sesion_y_sin_ventana_no_se_elige_ninguno(
    con, proyecto_demo
):
    """Una sesión de tmux puede tener tres ventanas de tres trabajos distintos.
    Quedarse con la primera escribiría la nota en el sitio equivocado y sin
    avisar, que es peor que no ofrecer nota."""
    uno = slots.crear(con, proyecto_demo, "back")
    otro = slots.crear(con, proyecto_demo, "front")
    _panel(con, "%1", "work", 0, slot_id=uno)
    _panel(con, "%2", "work", 1, slot_id=otro)

    assert api.contexto_trabajo(con, session="work")["slot"] is None


def test_con_un_solo_slot_en_la_sesion_sin_ventana_si_se_resuelve(con, proyecto_demo):
    slot_id = slots.crear(con, proyecto_demo, "back")
    _panel(con, "%1", "work", 0, slot_id=slot_id)
    _panel(con, "%2", "work", 1)

    assert api.contexto_trabajo(con, session="work")["slot"]["id"] == slot_id


# --------------------------------------------------------------------------- #
# Vincular desde la propia vista de trabajo
# --------------------------------------------------------------------------- #


def test_una_ventana_sin_slot_ofrece_con_que_vincularse(con, proyecto_demo):
    """Sin slot no hay nota, y mandar a la bandeja a buscar este mismo panel
    para poder volver aquí es un rodeo. El hueco de la nota ofrece lo único que
    desbloquea escribirla."""
    slots.crear(con, proyecto_demo, "back")
    _panel(con, "%2", "work", 1)

    v = api.contexto_trabajo(con, session="work", ventana=1)["vinculable"]
    assert v["pane_id"] == "%2"
    assert v["proyecto_id"] == "demo"
    assert [s["nombre"] for s in v["slots"]] == ["back"]


def test_una_ventana_ya_vinculada_puede_separarse_o_moverse(con, proyecto_demo):
    """Que no hubiera nada que ofrecer una vez vinculada convertía el primer
    acierto en definitivo: dos ventanas atadas al mismo slot no se podían volver
    a separar sin borrar el slot."""
    suyo = slots.crear(con, proyecto_demo, "back")
    otro = slots.crear(con, proyecto_demo, "front")
    _panel(con, "%1", "work", 0, slot_id=suyo)

    ctx = api.contexto_trabajo(con, session="work", ventana=0)
    assert ctx["slot"]["id"] == suyo
    v = ctx["vinculable"]
    assert v["slot"]["id"] == suyo
    # Mover ofrece los OTROS: incluir el suyo sería ofrecer quedarse donde está.
    assert [s["id"] for s in v["otros_slots"]] == [otro]


def test_sin_proyecto_no_se_ofrece_crear_slot_pero_si_se_explica(con):
    """Un slot cuelga de un proyecto; adivinar cuál sería inventarse la
    atribución. Se dice qué ruta registrar en vez de callar el botón."""
    con.execute(
        "INSERT INTO snapshot (tomado_en, server_pid, preservado) VALUES (?,100,0)",
        ("2026-08-28T18:00:00+00:00",),
    )
    actual = api.snapshot_actual(con)
    con.execute(
        """INSERT INTO panel (snapshot_id, pane_id, session, window_idx, pane_idx,
                              cwd, titulo, comando, etiqueta, proyecto_id, slot_id)
           VALUES (?,'%9','suelta',0,0,'/tmp/x','t','bash','x',NULL,NULL)""",
        (actual["id"],),
    )

    v = api.contexto_trabajo(con, session="suelta", ventana=0)["vinculable"]
    assert v["proyecto_id"] is None and v["slots"] == []
    assert v["cwd"] == "/tmp/x"   # la ruta que hay que registrar


def test_sin_saber_que_ventana_se_mira_no_se_ofrece_vincular(con, proyecto_demo):
    """Ofrecerlo sin saber la ventana ataría el panel equivocado."""
    _panel(con, "%2", "work", 1)
    assert api.contexto_trabajo(con, session="work")["vinculable"] is None


def test_separar_una_ventana_deja_al_slot_viejo_con_su_nota_y_su_otra_ventana(
    con, proyecto_demo
):
    """El caso que el usuario preguntó: dos ventanas en un slot, y quiere una cada una.
    Separar crea un slot nuevo para esa ventana; el anterior no pierde nada."""
    compartido = slots.crear(con, proyecto_demo, "Trabajo")
    slots.editar(con, compartido, nota="lo que llevaba escrito")
    _panel(con, "%1", "work", 0, slot_id=compartido)
    _panel(con, "%2", "work", 1, slot_id=compartido)

    nuevo = slots.promover(con, "%2", "Debugar lambda")

    assert nuevo != compartido
    ctx0 = api.contexto_trabajo(con, session="work", ventana=0)
    ctx1 = api.contexto_trabajo(con, session="work", ventana=1)
    assert ctx0["slot"]["id"] == compartido
    assert ctx0["slot"]["nota"] == "lo que llevaba escrito"
    assert ctx1["slot"]["id"] == nuevo and ctx1["slot"]["nombre"] == "Debugar lambda"


def test_soltar_una_ventana_la_devuelve_a_la_bandeja_sin_tocar_la_nota(
    con, proyecto_demo
):
    """Vincular era irreversible: el único arreglo era moverlo a otro slot, y si
    no había otro, ninguno. La nota no se toca — vive en el slot."""
    slot_id = slots.crear(con, proyecto_demo, "back")
    slots.editar(con, slot_id, nota="no se pierde")
    _panel(con, "%1", "work", 0, slot_id=slot_id)

    slots.desvincular(con, "%1")

    assert api.contexto_trabajo(con, session="work", ventana=0)["slot"] is None
    assert api.obtener_slot(con, slot_id)["nota"] == "no se pierde"
    assert [p["pane_id"] for p in api.bandeja(con)] == ["%1"]


def test_cada_ventana_de_la_sesion_trae_su_propio_estado(con, proyecto_demo):
    """Cambiar de pestaña no recarga la página. Si el panel derecho se calculara
    sólo para la ventana con la que se entró, escribirías en la nota de otro
    trabajo sin que nada lo dijera."""
    uno = slots.crear(con, proyecto_demo, "back")
    _panel(con, "%1", "work", 0, slot_id=uno)
    _panel(con, "%2", "work", 1)

    estados = api.contexto_trabajo(con, session="work", ventana=0)["ventanas_estado"]
    assert [e["ventana"] for e in estados] == [0, 1]
    assert estados[0]["slot"]["id"] == uno
    assert estados[1]["slot"] is None


def test_abrir_crea_la_sesion_cuando_tmux_no_tiene_servidor(escena, monkeypatch):
    """🔴 Máquina recién instalada: tmux está, nadie lo abrió. «Lanzar» tiene que
    crear la sesión, no pedir una ventana a un servidor que no existe."""
    llamadas = []
    monkeypatch.setattr(tmux, "existe_sesion", lambda s: False)
    monkeypatch.setattr(tmux, "path_de_usuario", lambda: "/usr/bin")
    monkeypatch.setattr(tmux, "nueva_sesion", lambda *a, **k: llamadas.append(("nueva", a, k)))
    monkeypatch.setattr(tmux, "abrir_ventana", lambda *a, **k: llamadas.append(("ventana", a)) or "%x")
    monkeypatch.setattr(tmux, "panel_de_sesion", lambda s: "%9")
    monkeypatch.setattr(tmux, "escribir_titulo", lambda *a: None)
    slot_id = slots.crear(escena, "demo", "Primer slot", "/tmp/demo", "", None, True)
    pane = slots.abrir(escena, slot_id)
    assert pane == "%9"
    assert [l[0] for l in llamadas] == ["nueva"]
    _, args, kw = llamadas[0]
    assert args[1] == "/tmp/demo" and args[2] == "Primer slot"
    # 🔴 El PATH va DENTRO del comando (regla 18, decisiones 231 y 339), y lo
    # pone la primitiva de tmux con `con_entorno`: aquí se pasa como entorno, y
    # sólo una vez (antes salía `env PATH=… env PATH=…`, decisión 340).
    assert args[3] == "claude"
    assert kw["entorno"]["PATH"] == "/usr/bin"
    assert tmux.con_entorno(args[3], kw["entorno"]) == "env PATH=/usr/bin claude"
    assert escena.execute("SELECT slot_id FROM binding WHERE pane_id='%9'").fetchone()[0] == slot_id


def test_abrir_usa_el_asiento_del_proyecto_cuando_el_slot_no_tiene_ruta(escena, monkeypatch):
    """«Creé el slot sobre el proyecto»: sin ruta propia, se abre en el asiento."""
    abiertas = []
    monkeypatch.setattr(tmux, "existe_sesion", lambda s: True)
    monkeypatch.setattr(tmux, "abrir_ventana", lambda ruta, *a, **k: abiertas.append(ruta) or "%5")
    monkeypatch.setattr(tmux, "escribir_titulo", lambda *a: None)
    slot_id = slots.crear(escena, "demo", "Sin ruta", None, "", None, False)
    assert slots.abrir(escena, slot_id) == "%5"
    assert abiertas == ["/tmp/demo"]


def test_abrir_en_una_sesion_que_existe_pasa_el_path_a_la_ventana(escena, monkeypatch):
    """La rama más común de «Lanzar». Sin el `entorno`, la ventana arrancaría
    el `claude` del PATH de systemd (decisiones 231, 339 y 340)."""
    llamadas = []
    monkeypatch.setattr(tmux, "existe_sesion", lambda s: True)
    monkeypatch.setattr(tmux, "path_de_usuario", lambda: "/usr/bin")
    monkeypatch.setattr(tmux, "abrir_ventana", lambda *a, **k: llamadas.append((a, k)) or "%x")
    monkeypatch.setattr(tmux, "escribir_titulo", lambda *a: None)
    slot_id = slots.crear(escena, "demo", "Primer slot", "/tmp/demo", "", None, True)
    assert slots.abrir(escena, slot_id, session="demo") == "%x"
    (args, kw), = llamadas
    assert args[2] == "claude" and kw["entorno"] == {"PATH": "/usr/bin"}


def test_un_titulo_que_no_se_puede_poner_no_tumba_la_apertura_pero_se_dice(escena, monkeypatch, capsys):
    """C-0085: el título es cosmético, pero un `except: pass` alrededor de
    tmux esconde fallos que salen luego como bugs de UI (regla dura 21)."""
    def explota(*a):
        raise RuntimeError("no such pane")

    monkeypatch.setattr(tmux, "existe_sesion", lambda s: True)
    monkeypatch.setattr(tmux, "abrir_ventana", lambda *a, **k: "%5")
    monkeypatch.setattr(tmux, "escribir_titulo", explota)
    slot_id = slots.crear(escena, "demo", "Con título", "/tmp/demo", "", None, False)
    assert slots.abrir(escena, slot_id) == "%5"
    salida = capsys.readouterr().out
    assert "Con título" in salida and "no such pane" in salida
