"""🔴 De quién cuelga el servidor de tmux.

El servidor hereda el cgroup de quien lo arranca. Si nace dentro de `hub-web`
—que corre bajo systemd—, parar o reiniciar el servicio mata el cgroup entero y
con él TODAS las sesiones de trabajo. Pasó el 2026-09-04: tres abortos de
`hub-web` en 81 segundos, tres servidores de tmux muertos, y lo que el usuario
vio fue «está todo hecho un caos» (decisión 153).

Es invisible leyendo el código —`tmux new-session` parece una orden sin efectos
sobre nadie— y no se reproduce a mano, porque una shell interactiva arranca el
servidor en el cgroup de la sesión de login, que es el correcto.
"""

from __future__ import annotations

import subprocess

import pytest

from hub import tmux


@pytest.fixture
def ordenes(monkeypatch):
    """Registra lo que se manda a ejecutar, sin ejecutar nada."""
    registro = []

    def falso_run(orden, **kw):
        registro.append(orden)
        return subprocess.CompletedProcess(orden, 0, stdout="", stderr="")

    monkeypatch.setattr(tmux.subprocess, "run", falso_run)
    monkeypatch.setattr(tmux, "_hay_donde_desasir", lambda: True)
    return registro


def test_crear_una_sesion_le_da_al_servidor_su_propio_cgroup(ordenes):
    tmux._correr(["new-session", "-d", "-s", "demo"])

    corte = len(tmux._PREFIJO_DESASIR)
    assert ordenes[0][:corte] == tmux._PREFIJO_DESASIR
    assert ordenes[0][corte:] == [*tmux.orden_base(), "new-session", "-d", "-s", "demo"]


def test_lo_que_no_puede_crear_el_servidor_va_a_pelo(ordenes):
    """Envolver todo sería un subproceso de más en el camino más caliente.

    Y no haría falta: una vez el servidor existe, ninguna otra orden lo
    re-parenta — `list-panes` habla con él, no lo arranca.
    """
    tmux._correr(["list-panes", "-a"])
    assert ordenes[0] == [*tmux.orden_base(), "list-panes", "-a"]


def test_sin_systemd_se_crea_igual(monkeypatch):
    """Un contenedor no tiene bus. Quedarse sin terminal por no poder aislar un
    cgroup sería cambiar un riesgo por una avería."""
    ordenes = []

    def falso_run(orden, **kw):
        ordenes.append(orden)
        return subprocess.CompletedProcess(orden, 0, stdout="", stderr="")

    monkeypatch.setattr(tmux.subprocess, "run", falso_run)
    monkeypatch.setattr(tmux, "_hay_donde_desasir", lambda: False)

    tmux._correr(["new-session", "-d", "-s", "demo"])
    assert ordenes == [[*tmux.orden_base(), "new-session", "-d", "-s", "demo"]]


def test_si_systemd_run_falla_se_reintenta_a_pelo(monkeypatch):
    """`systemd-run` falla ANTES de ejecutar la orden, así que reintentar no
    puede duplicar una sesión."""
    ordenes = []

    def falso_run(orden, **kw):
        ordenes.append(orden)
        fallo = orden[0] == "systemd-run"
        return subprocess.CompletedProcess(
            orden, 1 if fallo else 0,
            stdout="" if fallo else "hecho",
            stderr="Failed to connect to bus" if fallo else "",
        )

    monkeypatch.setattr(tmux.subprocess, "run", falso_run)
    monkeypatch.setattr(tmux, "_hay_donde_desasir", lambda: True)

    assert tmux._correr(["new-session", "-d", "-s", "demo"]) == "hecho"
    assert len(ordenes) == 2
    assert ordenes[1] == [*tmux.orden_base(), "new-session", "-d", "-s", "demo"]


def test_la_sonda_de_systemd_no_se_repite(monkeypatch):
    """Se pregunta una vez por proceso, no en cada llamada."""
    monkeypatch.setattr(tmux, "_puede_desasir", None)
    monkeypatch.setattr(tmux.shutil, "which", lambda _: "/usr/bin/systemd-run")
    monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", "unix:path=/run/user/1000/bus")

    sondas = []

    def falso_run(orden, **kw):
        sondas.append(orden)
        return subprocess.CompletedProcess(orden, 0, stdout="", stderr="")

    monkeypatch.setattr(tmux.subprocess, "run", falso_run)

    assert tmux._hay_donde_desasir() is True
    assert tmux._hay_donde_desasir() is True
    assert len(sondas) == 1


def test_el_servidor_aparte_no_lee_la_configuracion_de_quien_ejecuta(monkeypatch):
    """🔴 Decisión 264: con tmux-continuum en el `~/.tmux.conf`, el servidor de
    pruebas restauraba las sesiones reales del usuario y los tests se
    encontraban sesiones que no habían creado."""
    monkeypatch.setenv("HUB_TMUX_SOCKET", "pruebas")
    assert tmux.orden_base() == ["tmux", "-L", "pruebas", "-f", "/dev/null"]

    monkeypatch.delenv("HUB_TMUX_SOCKET")
    assert tmux.orden_base() == ["tmux"]   # el de verdad sí usa su configuración
