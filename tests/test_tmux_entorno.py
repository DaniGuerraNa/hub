"""El entorno que pide el hub llega al proceso de la ventana (C-0041, decisión 231).

`-e PATH=` de tmux no llega: medido el 2-nov, una ventana pedida desde el PATH
de `hub-web` arrancaba `/usr/bin/claude` 2.1.112 en vez del `claude` del dueño.
Esto se prueba con un tmux de verdad (el servidor aparte de `conftest.py`) y
con el PATH del cliente mutilado como el de systemd: un doble no lo vería.
"""

from __future__ import annotations

import shutil
import time

import pytest

from hub import tmux

pytestmark = pytest.mark.skipif(not shutil.which("tmux"), reason="sin tmux")

MUTILADO = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"


def _leer(ruta, espera=5.0) -> str:
    fin = time.monotonic() + espera
    while time.monotonic() < fin:
        if ruta.exists() and ruta.read_text().strip():
            return ruta.read_text().strip()
        time.sleep(0.05)
    raise AssertionError("la ventana no escribió nada")


@pytest.fixture
def cliente_de_systemd(monkeypatch):
    monkeypatch.setenv("PATH", MUTILADO)


@pytest.fixture
def sesion(request):
    nombre = f"entorno-{request.node.name[-12:]}".replace("_", "-")
    yield nombre
    try:
        tmux._correr(["kill-session", "-t", f"={nombre}"])
    except RuntimeError:
        pass


def _apuntar_path(destino) -> str:
    return f"sh -c 'echo \"$PATH\" > {destino}'"


def test_nueva_ventana_entrega_el_path_pedido(tmp_path, cliente_de_systemd, sesion):
    tmux.nueva_sesion(sesion, str(tmp_path))
    salida = tmp_path / "path"
    tmux.nueva_ventana(sesion, str(tmp_path), "x", _apuntar_path(salida), {"PATH": f"{tmp_path}/bin:{MUTILADO}"})
    assert _leer(salida).startswith(f"{tmp_path}/bin:")


def test_nueva_sesion_entrega_el_path_pedido_al_primer_panel(tmp_path, cliente_de_systemd, sesion):
    salida = tmp_path / "path"
    tmux.nueva_sesion(sesion, str(tmp_path), comando=_apuntar_path(salida),
                      entorno={"PATH": f"{tmp_path}/bin:{MUTILADO}"}, conservar=True)
    assert _leer(salida).startswith(f"{tmp_path}/bin:")


def test_relanzar_panel_entrega_el_path_pedido(tmp_path, cliente_de_systemd, sesion):
    tmux.nueva_sesion(sesion, str(tmp_path), comando="sleep 30")
    pane = tmux._correr(["display-message", "-p", "-t", f"={sesion}:", "#{pane_id}"]).strip()
    salida = tmp_path / "path"
    tmux.relanzar_panel(pane, str(tmp_path), _apuntar_path(salida), {"PATH": f"{tmp_path}/bin:{MUTILADO}"})
    assert _leer(salida).startswith(f"{tmp_path}/bin:")


def test_el_entorno_va_entrecomillado_dentro_del_comando():
    assert tmux.con_entorno("claude 'hola'", {"PATH": "/a b:/c", "X": "1"}) == "env 'PATH=/a b:/c' X=1 claude 'hola'"
    assert tmux.con_entorno("claude", None) == "claude"


def test_tmux_pone_el_path_del_cliente_aunque_se_le_pida_otro_con_e(tmp_path, cliente_de_systemd, sesion):
    """La medida de C-0058, para que se repita sola si tmux cambia: `-e PATH=`
    no llega nunca —tmux 3.4 pone el PATH del CLIENTE que da la orden—, y otra
    variable por `-e` sí. Por eso el entorno del hub va con `env` dentro del
    comando, y sin comando no se manda nada: la shell de login lee su perfil."""
    tmux.nueva_sesion(sesion, str(tmp_path))
    salida = tmp_path / "path"
    tmux._correr(["new-window", "-t", f"={sesion}:", "-e", f"PATH={tmp_path}/bin:{MUTILADO}", "-e", "HUB_X=1",
                  f"sh -c 'echo \"$HUB_X $PATH\" > {salida}'"])
    assert _leer(salida) == f"1 {MUTILADO}"


def test_sin_comando_no_se_manda_un_e_que_no_llegaria(monkeypatch):
    """C-0058: los `-e` de las primitivas sólo podían servir sin comando, y
    medido no sirven: el único que el hub pasaba así era PATH."""
    ordenes = []
    monkeypatch.setattr(tmux, "_correr", lambda args, **k: ordenes.append(args) or "1")
    entorno = {"PATH": "/x/bin:/usr/bin"}
    tmux.nueva_sesion("s", "/tmp", entorno=entorno)
    tmux.nueva_ventana("s", "/tmp", "v", None, entorno)
    tmux.nueva_ventana("s", "/tmp", "v", "claude", entorno)
    tmux.relanzar_panel("%1", "/tmp", "claude", entorno)
    assert not [a for a in ordenes if "-e" in a], ordenes
    assert all("env PATH=/x/bin:/usr/bin claude" in a for a in ordenes if "claude" in " ".join(a))


def test_abrir_ventana_entrega_el_path_pedido(tmp_path, cliente_de_systemd, sesion):
    """La rama más común de «Lanzar» (la sesión ya existe): si se pierde el
    `entorno`, vuelve el `claude` equivocado de la decisión 231 (340)."""
    tmux.nueva_sesion(sesion, str(tmp_path))
    salida = tmp_path / "path"
    tmux.abrir_ventana(str(tmp_path), "x", _apuntar_path(salida), sesion, entorno={"PATH": f"{tmp_path}/bin:{MUTILADO}"})
    assert _leer(salida).startswith(f"{tmp_path}/bin:")
