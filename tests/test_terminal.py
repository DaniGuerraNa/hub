"""Terminal embebida.

Lo que se prueba aquí no es el transporte de bytes (eso lo hace tmux), sino las
dos trampas del modelo espejo: que no se dupliquen paneles y que no se pueda
inyectar un destino arbitrario en la línea de comandos de tmux.
"""

from __future__ import annotations

import pytest

from hub import terminal, tmux

SALIDA_TMUX = "\t".join(["work", "0", "0", "%1", "/tmp/w", "⠂ Tarea", "claude", "1"]) + "\n" + \
              "\t".join(["hub-work", "0", "0", "%1", "/tmp/w", "⠂ Tarea", "claude", "0"]) + "\n" + \
              "\t".join(["game", "0", "0", "%2", "/tmp/g", "DESKTOP", "bash", "0"])


@pytest.fixture
def tmux_falso(monkeypatch):
    monkeypatch.setattr(tmux, "_correr", lambda args: SALIDA_TMUX)
    monkeypatch.setattr(tmux, "rama_git", lambda cwd: None)


def test_las_sesiones_espejo_no_duplican_paneles(tmux_falso):
    """Una sesión agrupada comparte ventanas: contarla sería contar dos veces."""
    paneles = tmux.listar_paneles()
    assert [p["session"] for p in paneles] == ["work", "game"]


def test_se_pueden_pedir_los_espejos_explicitamente(tmux_falso):
    paneles = tmux.listar_paneles(incluir_espejos=True)
    assert "hub-work" in [p["session"] for p in paneles]


def test_sesiones_disponibles_agrupa_y_oculta_espejos(tmux_falso):
    sesiones = terminal.sesiones_disponibles()
    assert [s["session"] for s in sesiones] == ["game", "work"]
    assert sesiones[1]["paneles"] == 1
    assert sesiones[1]["etiquetas"] == ["Tarea"]


@pytest.mark.parametrize(
    "malicioso",
    ["; rm -rf /", "work; kill-server", "$(whoami)", "../otra", "a b"],
)
def test_rechaza_destinos_que_no_son_un_nombre_de_sesion(malicioso):
    with pytest.raises(terminal.DestinoInvalido):
        terminal.crear_espejo(malicioso)


def test_crea_un_espejo_agrupado_y_unico(monkeypatch):
    llamadas = []
    monkeypatch.setattr(tmux, "_correr", lambda args: llamadas.append(args) or "")

    a = terminal.crear_espejo("work")
    b = terminal.crear_espejo("work")

    assert a.startswith("hub-work-") and b.startswith("hub-work-")
    # Uno por pestaña: dos vistas del mismo trabajo no se encogen entre sí.
    assert a != b
    assert ["new-session", "-d", "-t", "work", "-s", a] in llamadas


def test_el_barrido_respeta_el_periodo_de_gracia(monkeypatch):
    import time as reloj

    ahora = int(reloj.time())
    listado = (
        f"hub-work-viejo\t0\t{ahora - 300}\n"      # huérfano de verdad
        f"hub-work-recien\t0\t{ahora}\n"           # detached por milisegundos
        f"hub-game-vivo\t1\t{ahora - 300}\n"       # con cliente
        f"work\t1\t{ahora - 900}\n"                # no es espejo
    )
    matadas = []

    def falso(args):
        if args[0] == "list-sessions":
            return listado
        if args[0] == "kill-session":
            matadas.append(args[2])
        return ""

    monkeypatch.setattr(tmux, "_correr", falso)
    assert terminal.limpiar_espejos_huerfanos() == ["hub-work-viejo"]
    assert matadas == ["=hub-work-viejo"]


def test_destruir_espejo_nunca_toca_una_sesion_real(monkeypatch):
    matadas = []
    monkeypatch.setattr(tmux, "_correr", lambda args: matadas.append(args) or "")
    terminal.destruir_espejo("work")
    terminal.destruir_espejo("Facturador")
    assert matadas == []


# --------------------------------------------------------------------------- #
# El ancho de las ventanas compartidas
# --------------------------------------------------------------------------- #


def test_el_espejo_ajusta_cada_ventana_a_quien_la_mira(monkeypatch):
    """🔴 Sin esto se pierde texto en silencio. tmux trae `window-size latest`,
    así que una ventana conserva el ancho del último cliente que la tocó:
    medido, con un solo cliente de 168 columnas, `work:0` estaba a 168 y
    `work:1` a 172. Al saltar a esa pestaña, tmux contaba 172 columnas y el
    navegador pintaba 168 — «cuan» donde decía «cuando»."""
    llamadas = []
    monkeypatch.setattr(
        terminal.tmux, "listar_ventanas",
        lambda s: [{"indice": 0}, {"indice": 3}],
    )
    monkeypatch.setattr(terminal.tmux, "_correr",
                        lambda args, **k: llamadas.append(args) or "")

    terminal.dimensionar_al_espectador("hub-work-abc123")

    ajustes = [a for a in llamadas if a[0] == "set-window-option"]
    assert [a[2] for a in ajustes] == ["=hub-work-abc123:0", "=hub-work-abc123:3"]
    assert all(a[-2:] == ["aggressive-resize", "on"] for a in ajustes)


def test_el_ajuste_no_se_aplica_globalmente(monkeypatch):
    """🔴 La primera versión usaba `-g` y dejó la opción puesta en TODO el
    el servidor de tmux del usuario, incluidas sus sesiones de trabajo. El hub no debe
    tener efectos laterales sobre lo que no le pertenece."""
    llamadas = []
    monkeypatch.setattr(terminal.tmux, "listar_ventanas", lambda s: [{"indice": 0}])
    monkeypatch.setattr(terminal.tmux, "_correr",
                        lambda args, **k: llamadas.append(args) or "")

    terminal.dimensionar_al_espectador("hub-work-abc123")

    ajustes = [a for a in llamadas if a[0] == "set-window-option"]
    assert ajustes, "debe haberse aplicado"
    assert all("-g" not in a for a in ajustes), "sin -g: la opción es por ventana"


def test_un_tmux_que_falla_no_tumba_la_terminal(monkeypatch):
    """Sin el ajuste se ve mal, pero la terminal sigue siendo usable: no puede
    ser la diferencia entre tener terminal y no tenerla."""
    monkeypatch.setattr(terminal.tmux, "listar_ventanas", lambda s: [{"indice": 0}])

    def explota(*a, **k):
        raise RuntimeError("tmux dice que no")

    monkeypatch.setattr(terminal.tmux, "_correr", explota)
    terminal.dimensionar_al_espectador("hub-work-abc123")   # no debe levantar


def test_no_se_encoge_la_ventana_si_otra_terminal_la_esta_mirando(monkeypatch):
    """🔴 Encoger una ventana **trunca de forma irreversible** lo ya escrito:
    tmux no reenvuelve el historial, lo recorta.

    Medido en una máquina real: `Facturador:0` estaba a 237 columnas porque su
    Windows Terminal la tenía abierta, y la vista del hub daba 168. Abrir esa
    sesión en el navegador se llevaba por delante el final de cada línea, y al
    volver a su terminal el texto seguía perdido. Se prefiere recortar la VISTA
    —reversible, basta bajar la letra— antes que romper el CONTENIDO."""
    llamadas = []

    def correr(args, **k):
        if args[0] == "list-clients":
            return "Facturador\tFacturador\nhub-Facturador-abc\tFacturador\n"
        if args[0] == "display-message":
            return "Facturador\n"
        llamadas.append(args)
        return ""

    monkeypatch.setattr(terminal.tmux, "_correr", correr)
    monkeypatch.setattr(terminal.tmux, "listar_ventanas", lambda s: [{"indice": 0}])

    terminal.dimensionar_al_espectador("hub-Facturador-abc")
    assert llamadas == [], "con otra terminal mirando, no se toca el tamaño"


def test_se_encoge_cuando_el_hub_es_el_unico_que_mira(monkeypatch):
    llamadas = []

    def correr(args, **k):
        if args[0] == "list-clients":
            return "hub-work-abc\twork\nPersonal\tPersonal\n"
        if args[0] == "display-message":
            return "work\n"
        llamadas.append(args)
        return ""

    monkeypatch.setattr(terminal.tmux, "_correr", correr)
    monkeypatch.setattr(terminal.tmux, "listar_ventanas", lambda s: [{"indice": 0}])

    terminal.dimensionar_al_espectador("hub-work-abc")
    assert llamadas and llamadas[0][-2:] == ["aggressive-resize", "on"]


def test_ante_la_duda_no_se_encoge(monkeypatch):
    """Si tmux no responde, la respuesta segura es «hay alguien más»: dejar la
    ventana como está sólo estropea la vista; encogerla borra contenido."""
    def explota(*a, **k):
        raise RuntimeError("tmux mudo")

    monkeypatch.setattr(terminal.tmux, "_correr", explota)
    assert terminal._hay_otro_espectador("hub-work-abc") is True
