"""🔴 Cómo escribe el hub en un panel de tmux.

Es la mecánica de la única excepción a la decisión 22, y es frágil de una manera
que no se ve leyendo el código: los tres comandos parecen correctos y aun así
parten el mensaje. Se comprobó contra el asistente real y estos tests fijan lo
que se aprendió, para que un refactor no lo deshaga en silencio.
"""

from __future__ import annotations

import pytest

from hub import terminal, tmux


@pytest.fixture
def llamadas(monkeypatch):
    registro = []

    def correr(args, entrada=None):
        registro.append((args, entrada))
        return ""

    monkeypatch.setattr(tmux, "_correr", correr)
    return registro


def test_el_texto_viaja_por_stdin_y_no_en_la_linea_de_comandos(llamadas):
    # Es texto libre del usuario: interpolarlo en la línea de comandos es
    # ejecución arbitraria (regla dura 10).
    veneno = "$(rm -rf ~) `id` \"; whoami\""
    tmux.pegar_en_panel("%9", veneno)

    args, entrada = llamadas[0]
    assert args == ["load-buffer", "-b", tmux.BUFER, "-"]
    assert entrada == veneno
    assert not any(veneno in " ".join(a) for a, _ in llamadas)


def test_el_pegado_va_en_bracketed_paste(llamadas):
    """🔴 `-p` no es opcional y su ausencia no se nota leyendo el código.

    Comprobado contra el asistente real: sin `-p`, tmux manda los saltos de
    línea como pulsaciones de Enter y Claude Code despacha en cada una. Un
    mensaje de dos párrafos llegó como dos mensajes, y el segundo contestó fuera
    de contexto. `-p` es lo que distingue un pegado de alguien tecleando.
    """
    tmux.pegar_en_panel("%9", "una\n\ndos")
    pegado = next(a for a, _ in llamadas if a[0] == "paste-buffer")
    assert "-p" in pegado


def test_el_enter_va_aparte_y_despues_del_texto(llamadas):
    # Si fuera dentro del pegado, se despacharía a mitad del mensaje.
    tmux.pegar_en_panel("%9", "hola")
    ordenes = [a[0] for a, _ in llamadas]
    assert ordenes == ["load-buffer", "paste-buffer", "send-keys"]
    assert llamadas[-1][0][-1] == "Enter"


def test_el_bufer_es_propio_y_se_borra_tras_pegarlo(llamadas):
    """Sin `-b`, `load-buffer` apila en la pila global y pisaría lo que el usuario
    tenga copiado a mano; sin `-d`, el mensaje se queda ahí colgando."""
    tmux.pegar_en_panel("%9", "hola")
    pegado = next(a for a, _ in llamadas if a[0] == "paste-buffer")
    assert "-b" in pegado and tmux.BUFER in pegado and "-d" in pegado


def test_se_puede_pegar_sin_despachar(llamadas):
    tmux.pegar_en_panel("%9", "borrador", enter=False)
    assert [a[0] for a, _ in llamadas] == ["load-buffer", "paste-buffer"]


def test_un_pane_id_que_no_tenga_forma_de_pane_id_no_llega_a_tmux(llamadas):
    for veneno in ["%9; rm -rf /", "sesion:0.1", "$(id)", "%", "", "9", None]:
        with pytest.raises(tmux.DestinoInvalido):
            tmux.pegar_en_panel(veneno, "hola")
    assert llamadas == []


# --------------------------------------------------------------------------- #
# Teclas sueltas
# --------------------------------------------------------------------------- #


def test_solo_se_pueden_pulsar_las_teclas_de_la_lista_cerrada(llamadas):
    """`send-keys` acepta cualquier cosa, incluido texto entero, y ahí es donde
    vive el peligro de la decisión 22. La lista cerrada hace que lo peor que
    pueda llegar por esta puerta sea un dígito."""
    for veneno in ["rm -rf /", "C-c", "q", "Enter Enter", ""]:
        with pytest.raises(tmux.DestinoInvalido):
            tmux.tecla_en_panel("%9", veneno)
    assert llamadas == []


def test_una_tecla_va_por_send_keys_y_no_por_el_bufer(llamadas):
    """Comprobado contra el cuadro de permisos real: un `1` entregado por
    `paste-buffer -p` no selecciona nada, porque el bracketed paste es para
    campos de texto y un menú espera una pulsación."""
    tmux.tecla_en_panel("%9", "1")
    assert llamadas == [(["send-keys", "-t", "%9", "1"], None)]


def test_el_pane_id_se_valida_antes_que_la_tecla(llamadas):
    with pytest.raises(tmux.DestinoInvalido):
        tmux.tecla_en_panel("no-es-un-panel", "1")
    assert llamadas == []


# --------------------------------------------------------------------------- #
# Dónde está trabajando el usuario
# --------------------------------------------------------------------------- #


def test_el_panel_enfocado_sale_del_cliente_mas_reciente(monkeypatch):
    """`pane_active` vale 1 en el panel activo de CADA ventana —diez paneles
    abiertos, diez «activos»—, así que no sirve para saber dónde está. Lo que sí
    distingue es `client_activity`: con sus tres pantallas daba 1787937361,
    1787937266 y 1787872737, que separa dónde está de dónde estuvo ayer."""
    def correr(args, entrada=None):
        if args[0] == "list-clients":
            return ("1787872737\tFacturador\n1787937361\tPersonal\n"
                    "1787937266\thub-work-c95325\n")
        if args[0] == "list-panes":
            return {"=Personal": "%4\n"}.get(args[2], "")
        return ""

    monkeypatch.setattr(tmux, "_correr", correr)
    assert tmux.panel_enfocado() == "%4"


def test_un_cliente_en_una_sesion_que_ya_no_existe_no_deja_sin_respuesta(monkeypatch):
    """Pasó de verdad: `list-clients` traía `hub-<proyecto>-0ee191`, que era la
    sesión más reciente y ya no existía. Con una sola oportunidad, ninguna nota
    encontraba nunca su slot."""
    def correr(args, entrada=None):
        if args[0] == "list-clients":
            return "1787940300\tfantasma\n1787937361\tPersonal\n"
        if args[0] == "list-panes":
            if args[2] == "=fantasma":
                raise RuntimeError("can't find window: fantasma")
            return "%4\n"
        return ""

    monkeypatch.setattr(tmux, "_correr", correr)
    assert tmux.panel_enfocado() == "%4"


def test_la_sesion_del_asistente_se_puede_excluir(monkeypatch):
    """Una nota sobre en qué se está trabajando no puede caer sobre el propio
    asistente."""
    def correr(args, entrada=None):
        if args[0] == "list-clients":
            return "1787940300\tasistente\n1787937361\tPersonal\n"
        if args[0] == "list-panes":
            return "%4\n" if args[2] == "=Personal" else "%9\n"
        return ""

    monkeypatch.setattr(tmux, "_correr", correr)
    assert tmux.panel_enfocado(excluir={"asistente"}) == "%4"


def test_un_nombre_de_sesion_raro_no_llega_a_la_linea_de_comandos(monkeypatch):
    vistos = []

    def correr(args, entrada=None):
        vistos.append(args)
        return "1\t$(rm -rf ~)\n" if args[0] == "list-clients" else ""

    monkeypatch.setattr(tmux, "_correr", correr)
    assert tmux.panel_enfocado() is None
    assert all(a[0] != "list-panes" for a in vistos)


# ── tmux instalado pero sin servidor ─────────────────────────────────────────


@pytest.mark.parametrize("mensaje", [
    "error connecting to /tmp/tmux-1000/default (No such file or directory)",
    "no server running on /tmp/tmux-1000/default",
    "failed to connect to server",
])
def test_sin_servidor_de_tmux_no_es_una_averia(monkeypatch, mensaje):
    """🔴 `/trabajo` daba 500 a quien acabara de instalar el hub.

    Es el estado normal de una máquina recién instalada: tmux está, pero no hay
    ninguna sesión abierta, así que su socket no existe. tmux contesta «error
    connecting to … (No such file or directory)», que NO contenía ninguna de
    las dos cadenas que se clasificaban como «no disponible»: se convertía en
    `RuntimeError` y tumbaba la pantalla principal.

    No se detectó nunca porque en la máquina de quien lo escribió siempre hay
    tmux corriendo. Y quitar tmux del PATH tampoco lo destapa — eso da
    `FileNotFoundError`, que sí estaba cubierto. Hay que tenerlo instalado y sin
    servidor, que es justo el caso de quien lo recibe.
    """
    import subprocess

    def falla(*_a, **_k):
        return subprocess.CompletedProcess([], 1, "", mensaje)

    monkeypatch.setattr(tmux.subprocess, "run", falla)

    # `_correr` lo clasifica como «no disponible»...
    with pytest.raises(tmux.TmuxNoDisponible):
        tmux._correr(["list-panes"])
    # ...y por eso quien lo usa ve una lista vacía en vez de un 500.
    assert tmux.listar_paneles() == []
    assert terminal.sesiones_disponibles() == []


def test_un_error_de_verdad_sigue_siendo_un_error(monkeypatch):
    """El control negativo: tragarse todo dejaría de distinguir avería de vacío.

    Un fallo real de tmux tiene que seguir doliendo, o el hub enseñaría «no
    tienes sesiones» cuando lo que pasa es que algo se rompió.
    """
    import subprocess

    def falla(*_a, **_k):
        return subprocess.CompletedProcess([], 1, "", "unknown option -- z")

    monkeypatch.setattr(tmux.subprocess, "run", falla)
    with pytest.raises(RuntimeError):
        tmux._correr(["list-panes"])
