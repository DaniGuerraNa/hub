"""Terminal embebida.

Lo que se prueba aquí no es el transporte de bytes (eso lo hace tmux), sino las
dos trampas del modelo espejo: que no se dupliquen paneles y que no se pueda
inyectar un destino arbitrario en la línea de comandos de tmux.
"""

from __future__ import annotations

import asyncio
import os
import pty
import signal
import termios
import time
import tty

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


# ── lo que se pega llega entero ───────────────────────────────────────────────
#
# 🔴 Salió de un fallo real: el prompt para un `/compact` se pegó en la terminal
# web y llegó cortado —a mitad de palabra, en varios sitios y no sólo al final—
# mientras que el mismo texto en trozos pequeños llegaba bien.
#
# La causa no estaba en el portapapeles sino aquí: el PTY es NO BLOQUEANTE, así
# que `os.write` mete lo que cabe y devuelve cuánto. Medido en este mismo
# montaje: de 16.000 bytes entraron 11.776 y los otros 4.224 se tiraron sin que
# nadie se enterara.


def _pty_que_guarda(destino, esperados):
    """Un `Adjunto` real sobre un PTY cuyo otro extremo guarda lo que recibe.

    Dos detalles que costaron tres intentos, y ninguno es cosmético:

    · El `sleep` es lo que hace útil la prueba. Durante ese rato nadie lee, el
      buffer del PTY se llena y `os.write` se queda corto — que es el caso que
      se quiere provocar. Con un lector inmediato puede entrar todo de una vez
      y el test pasaría con el código roto.
    · `head -c` y no `cat`, porque el hijo tiene que terminar **por su cuenta**
      al llegar a la cuenta. Con `cat` el fin era cerrar el PTY, y cerrarlo
      manda SIGHUP y descarta lo que el otro extremo aún no había leído: el
      test acusaba al código de perder bytes que perdía él al recoger.
    """
    adjunto = terminal.Adjunto.__new__(terminal.Adjunto)
    adjunto.pid, adjunto.fd = pty.fork()
    if adjunto.pid == 0:  # pragma: no cover - proceso hijo
        os.execvp("sh", ["sh", "-c", f"sleep 0.2; head -c {esperados} > {destino}"])
        os._exit(1)
    # En crudo, como lo deja `tmux attach`: en modo canónico el tty DESCARTA
    # cuando se le llena la cola de línea —medido, 8.928 bytes de 180.000— y esa
    # pérdida no es la que se está probando aquí.
    tty.setraw(adjunto.fd)
    os.set_blocking(adjunto.fd, False)
    adjunto._pendiente = bytearray()
    adjunto._esperando = False
    return adjunto


def _recoger(adjunto, destino):
    """Espera a que el hijo se dé por servido, con tope.

    Si faltan bytes nunca llegará a su cuenta: el tope es para que eso salga
    como un test en rojo con el diff delante, y no como un cuelgue."""
    for _ in range(500):
        if os.waitpid(adjunto.pid, os.WNOHANG)[0]:
            break
        time.sleep(0.01)
    else:
        os.kill(adjunto.pid, signal.SIGKILL)
        os.waitpid(adjunto.pid, 0)
    os.close(adjunto.fd)
    return destino.read_bytes() if destino.exists() else b""


PEGADO = b"".join(b"linea %04d " % i + b"x" * 60 + b"\n" for i in range(2500))


def test_un_pegado_grande_llega_ENTERO(tmp_path):
    """Es el caso del usuario: 160 KB de golpe, como un prompt largo."""
    destino = tmp_path / "recibido"
    adjunto = _pty_que_guarda(destino, len(PEGADO))
    adjunto.escribir(PEGADO)
    assert _recoger(adjunto, destino) == PEGADO


def test_los_pegados_llegan_EN_ORDEN(tmp_path):
    """Lo que no cabe queda en cola, así que lo siguiente NO puede adelantarse:
    un pegado reordenado sería peor que uno cortado, porque parece correcto."""
    destino = tmp_path / "recibido"
    adjunto = _pty_que_guarda(destino, len(PEGADO) + 101)
    adjunto.escribir(PEGADO)
    adjunto.escribir(b"y" * 100 + b"\n")
    assert _recoger(adjunto, destino) == PEGADO + b"y" * 100 + b"\n"


def test_dentro_del_bucle_de_eventos_tampoco_se_pierde_nada(tmp_path):
    """El camino que usa de verdad el WebSocket.

    Ahí no se puede esperar a que tmux drene —pararía el servidor entero—, así
    que lo pendiente se aplaza con `add_writer`. Se comprueba que el aplazado
    también termina de escribir, y que suelta la vigilancia al acabar.
    """
    destino = tmp_path / "recibido"
    adjunto = _pty_que_guarda(destino, len(PEGADO))

    async def escribir_y_dejar_al_bucle():
        adjunto.escribir(PEGADO)
        assert adjunto._pendiente, "con un lector dormido tiene que quedar cola"
        for _ in range(400):
            if not adjunto._pendiente:
                return
            await asyncio.sleep(0.01)
        raise AssertionError("la cola nunca se vació")

    asyncio.run(escribir_y_dejar_al_bucle())
    assert adjunto._esperando is False
    assert _recoger(adjunto, destino) == PEGADO
