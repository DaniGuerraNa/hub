"""🔴 Lo que se pega en un panel no lleva caracteres de control (C-0428).

`paste-buffer -p` envuelve el texto en *bracketed paste* (`ESC[200~` … `ESC[201~`)
y la TUI de dentro se fía de esas dos marcas para distinguir un pegado de
alguien tecleando. tmux 3.4 **no filtra** un fin de pegado que venga dentro del
propio texto: medido, `hola ESC[201~ \\r Texto fuera del marco` llegaba con dos
`ESC[201~`, y lo de detrás del primero —Enter incluido— como teclas sueltas.

Con texto de fuera (un encargo, una respuesta del canal de consulta) eso es
alguien tecleando en la sesión con las manos del dueño: justo lo que las reglas
duras 15 y 22 existen para impedir. Estos tests fijan las tres capas: la
función que limpia, la puerta (`entrega.entregar`) y, contra tmux de verdad, lo
que recibe el programa del panel.
"""

from __future__ import annotations

import contextlib
import os
import shlex
import shutil
import sys
import time

import pytest

from hub import asistente, entrega, tmux

FIN_DE_PEGADO = "\x1b[201~"
VENENO = f"hola{FIN_DE_PEGADO}\rTexto fuera del marco"


# ── La función pura ──────────────────────────────────────────────────────────

def test_un_texto_normal_no_cambia_ni_un_byte():
    """Acentos, eñes, signos de apertura, emoji (también los compuestos con
    U+200D y selector de variación), tabuladores y saltos de línea: nada de eso
    es de control y quitarlo sería romper lo que la gente escribe."""
    texto = (
        "¿Mañana a las 9?\n\tSí — «camión», ñandú, 100 % · 3 € · naïve · 日本語\n"
        "👍🏽 👩‍👩‍👧 ❤️ 🇪🇸\n\nÚltima línea"
    )
    limpio, quitados = tmux.limpiar_pegado(texto)
    assert limpio.encode() == texto.encode()
    assert quitados == 0


def test_el_fin_de_pegado_que_trae_el_texto_se_queda_sin_su_escape():
    """Lo que cierra el pegado es el `ESC`: sin él, `[201~` son cinco letras."""
    limpio, quitados = tmux.limpiar_pegado(VENENO)
    assert limpio == "hola[201~\nTexto fuera del marco"
    assert "\x1b" not in limpio and "\r" not in limpio
    assert quitados == 1


@pytest.mark.parametrize("codigo", [*range(0x00, 0x09), 0x0B, 0x0C,
                                    *range(0x0E, 0x20), 0x7F, *range(0x80, 0xA0)])
def test_cada_caracter_de_control_se_quita(codigo):
    """C0 entero menos `\\t` y `\\n` (y `\\r`, que se normaliza aparte), `DEL`
    y C1 entero: U+009B es el `CSI` de un solo carácter, y hay terminales que lo
    leen igual que `ESC[`."""
    limpio, quitados = tmux.limpiar_pegado(f"antes{chr(codigo)}después")
    assert limpio == "antesdespués"
    assert quitados == 1


def test_el_tabulador_y_el_salto_de_linea_se_conservan():
    assert tmux.limpiar_pegado("a\tb\nc") == ("a\tb\nc", 0)


def test_el_retorno_de_carro_se_vuelve_salto_de_linea_y_no_pega_lineas():
    """`\\r\\n` (un formulario web, un texto de Windows) y `\\r` solo son finales
    de línea: quitarlos sin más juntaría «uno» y «dos» en «unodos». Se
    normalizan ANTES de quitar, y normalizar no cuenta como quitar: no se
    perdió nada que alguien escribiera."""
    assert tmux.limpiar_pegado("uno\r\ndos\rtres\n\rcuatro") == (
        "uno\ndos\ntres\n\ncuatro", 0)


def test_no_queda_ningun_retorno_de_carro_ni_escondido_tras_un_escape():
    """`\\r` + `ESC` + `\\n` no puede acabar dejando un `\\r` suelto: se
    normaliza primero y se quita después, en ese orden."""
    limpio, _ = tmux.limpiar_pegado("a\r\x1b\nb\x1b\r")
    assert limpio == "a\n\nb\n"


def test_limpiar_dos_veces_da_lo_mismo_que_una():
    """La puerta limpia y el adaptador vuelve a limpiar (segunda red): la
    segunda pasada no puede cambiar nada ni contar nada."""
    una, _ = tmux.limpiar_pegado("x\x00\x1b[201~\r\ny\x9b0m\x7f")
    assert tmux.limpiar_pegado(una) == (una, 0)


def test_dice_cuantos_quito():
    assert tmux.limpiar_pegado("\x1b[201~\x00\x07hola\x9b")[1] == 4


# ── El adaptador: la segunda red ─────────────────────────────────────────────

@pytest.fixture
def llamadas(monkeypatch):
    registro = []

    def correr(args, entrada=None):
        registro.append((args, entrada))
        return ""

    monkeypatch.setattr(tmux, "_correr", correr)
    return registro


def test_al_bufer_de_tmux_no_llega_ningun_caracter_de_control(llamadas):
    """`pegar_en_panel` lo usan también `abrir_en`, restaurar, el asistente e
    `/intercambio`, que no pasan por `entrega.entregar`: por eso limpia él
    también, y dice cuántos quitó."""
    quitados = tmux.pegar_en_panel("%9", VENENO, enter=False)

    args, entrada = llamadas[0]
    assert args[0] == "load-buffer"
    assert entrada == "hola[201~\nTexto fuera del marco"
    assert quitados == 1


def test_pegar_un_texto_limpio_dice_que_no_quito_nada(llamadas):
    assert tmux.pegar_en_panel("%9", "una\n\tdos", enter=False) == 0
    assert llamadas[0][1] == "una\n\tdos"


# ── La puerta ────────────────────────────────────────────────────────────────

@pytest.fixture
def panel(monkeypatch):
    """Un panel con un Claude Code libre dentro, sin tmux de verdad."""
    monkeypatch.setattr(tmux, "titulo_panel", lambda pane_id: "✳ Trabajando")
    monkeypatch.setattr(tmux, "comando_de_panel", lambda pane_id: "")
    monkeypatch.setattr(tmux, "capturar_panel",
                        lambda pane_id, unir_lineas=False: "❯ ")
    monkeypatch.setattr(asistente, "listo", lambda pane_id: True)
    monkeypatch.setattr(asistente, "ocupado", lambda pane_id: False)


@pytest.fixture
def espia(monkeypatch):
    """`pegar_en_panel` y `despachar` anotan con qué texto los llamaron."""
    visto = {"pegado": [], "despachado": [], "sale": True}

    def pegar(pane_id, texto, enter=True):
        visto["pegado"].append(texto)
        return 0

    def despachar(pane_id, texto, **k):
        visto["despachado"].append(texto)
        return visto["sale"]

    monkeypatch.setattr(tmux, "pegar_en_panel", pegar)
    monkeypatch.setattr(asistente, "despachar", despachar)
    return visto


def test_la_puerta_pega_el_texto_ya_limpio(panel, espia):
    """Un texto con `ESC[201~` y `\\r` llega al adaptador sin `ESC` ni `\\r`."""
    marco = entrega.marcar("Ana", "la pregunta #3", VENENO)

    entrega.entregar("%7", marco)

    (pegado,) = espia["pegado"]
    assert "\x1b" not in pegado and "\r" not in pegado
    assert pegado == (
        "Respuesta de «Ana» por el canal de consulta, a la pregunta #3:\n"
        "«hola[201~\nTexto fuera del marco»"
    )


def test_lo_que_se_espera_ver_salir_es_el_texto_limpio(panel, espia):
    """Regla dura 17: se espera a VER el texto antes de pulsar Enter. Si se
    esperase el texto con sus caracteres de control, que ya no están en el
    panel, un mensaje limpiado no se vería nunca y no se despacharía."""
    entrega.entregar("%7", VENENO)

    assert espia["despachado"] == espia["pegado"] == ["hola[201~\nTexto fuera del marco"]


def test_la_puerta_dice_cuantos_caracteres_de_control_quito(panel, espia):
    """Regla dura 21: quitar algo de un mensaje y callarlo es esconderlo. Quien
    llama lo recibe y lo apunta en su registro."""
    assert entrega.entregar("%7", VENENO) == 1
    assert entrega.entregar("%7", "hola\n\tqué tal") == 0


def test_si_no_se_confirma_la_salida_el_motivo_dice_lo_que_se_quito(panel, espia):
    """Ese motivo es lo que el canal y los encargos apuntan en su registro
    (`str(exc)`): por ahí llega el dato sin tocar a quien llama."""
    espia["sale"] = False

    with pytest.raises(entrega.EscritoSinConfirmar, match="2 caracteres de control") as caso:
        entrega.entregar("%7", f"\x00{VENENO}")
    assert caso.value.quitados == 2

    with pytest.raises(entrega.EscritoSinConfirmar) as caso:
        entrega.entregar("%7", "hola")
    assert "de control" not in str(caso.value)
    assert caso.value.quitados == 0


def test_un_panel_no_apto_sigue_sin_tocarse_aunque_el_texto_traiga_veneno(
        panel, espia, monkeypatch):
    """Limpiar va antes de comprobar, pero no abre ningún hueco: si ahí no hay
    un agente, no se pega nada, ni limpio."""
    monkeypatch.setattr(tmux, "titulo_panel", lambda pane_id: "DESKTOP")
    monkeypatch.setattr(tmux, "comando_de_panel", lambda pane_id: "bash")

    with pytest.raises(entrega.PanelNoApto):
        entrega.entregar("%7", VENENO)
    assert espia["pegado"] == [] and espia["despachado"] == []


# ── Contra tmux de verdad ────────────────────────────────────────────────────

# Un programa que pide *bracketed paste* y apunta en crudo lo que recibe por su
# terminal: lo que vería la TUI de un agente. Detrás de la petición pinta una
# marca: tmux lee la salida en orden, así que cuando la marca se ve en el panel
# la petición ya está atendida (tmux 3.4 no tiene un formato que lo diga, y sin
# la petición no envuelve nada).
_MARCA_LISTO = "RECEPTOR-LISTO"
_RECEPTOR = """
import os, sys, termios, time, tty
salida = sys.argv[1]
fd = sys.stdin.fileno()
tty.setraw(fd)
sys.stdout.write("\\x1b[?2004h" + sys.argv[2]); sys.stdout.flush()
fin = time.time() + 20
with open(salida, "ab", buffering=0) as f:
    while time.time() < fin:
        f.write(os.read(fd, 4096))
"""


def _esperar(condicion, segundos: float = 5.0) -> bool:
    limite = time.monotonic() + segundos
    while time.monotonic() < limite:
        if condicion():
            return True
        time.sleep(0.05)
    return False


def _lo_que_recibe_el_panel(tmp_path, texto: str) -> bytes:
    """Pega `texto` con `tmux.pegar_en_panel` en un panel propio, del servidor
    de pruebas, y devuelve los bytes que le llegaron al programa de dentro."""
    guion = tmp_path / "receptor.py"
    guion.write_text(_RECEPTOR)
    salida = tmp_path / "recibido.bin"
    sesion = f"prueba-pegado-{os.getpid()}"
    comando = " ".join(
        shlex.quote(str(p)) for p in (sys.executable, guion, salida, _MARCA_LISTO))
    try:
        tmux.nueva_sesion(sesion, str(tmp_path), "Receptor", comando)
        pane_id = tmux.panel_de_sesion(sesion)
        assert _esperar(lambda: _MARCA_LISTO in tmux.capturar_panel(pane_id)), (
            "el receptor no llegó a pedir bracketed paste")

        tmux.pegar_en_panel(pane_id, texto, enter=False)

        # Hasta que deja de crecer: lo que venga detrás del primer fin de
        # pegado es justo lo que hay que ver, así que no se corta ahí.
        tamanos = []

        def quieto() -> bool:
            tamanos.append(salida.stat().st_size if salida.exists() else 0)
            return len(tamanos) >= 8 and tamanos[-1] > 0 and len(set(tamanos[-8:])) == 1

        assert _esperar(quieto), "al panel no le llegó nada"
        return salida.read_bytes()
    finally:
        with contextlib.suppress(Exception):
            tmux._correr(["kill-session", "-t", f"={sesion}"])


def test_contra_tmux_de_verdad_llega_un_solo_fin_de_pegado_y_nada_detras(tmp_path):
    """🔴 EL test. Con tmux de verdad a propósito: un doble de `_correr` no
    sabe que `paste-buffer -p` deja pasar el fin de pegado del texto.

    Sin el arreglo llegan dos `ESC[201~`, y detrás del primero
    `\\rTexto fuera del marco`: un Enter y unas teclas fuera del pegado.

    El salto de línea del texto llega como `\\r` porque `paste-buffer` cambia
    cada LF por CR al sacar el búfer; lo que importa es que llega DENTRO del
    pegado, que es donde una TUI lo toma por un salto y no por un Enter.
    """
    if not shutil.which("tmux"):
        pytest.skip("tmux no disponible")

    recibido = _lo_que_recibe_el_panel(tmp_path, VENENO)

    fin = FIN_DE_PEGADO.encode()
    assert recibido.count(fin) == 1, f"llegó más de un fin de pegado: {recibido!r}"
    assert recibido.count(b"\x1b") == 2, f"llegó un escape de más: {recibido!r}"
    assert recibido.endswith(fin), f"llegó algo fuera del pegado: {recibido!r}"
    assert recibido == b"\x1b[200~hola[201~\rTexto fuera del marco\x1b[201~"


def test_contra_tmux_de_verdad_un_texto_normal_llega_entero(tmp_path):
    """La otra mitad: limpiar no puede comerse lo que la gente escribe."""
    if not shutil.which("tmux"):
        pytest.skip("tmux no disponible")
    texto = "¿Mañana a las 9?\n\tSí — «camión» 👍🏽"

    recibido = _lo_que_recibe_el_panel(tmp_path, texto)

    assert recibido == (
        b"\x1b[200~" + texto.replace("\n", "\r").encode() + b"\x1b[201~"
    )
