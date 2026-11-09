"""Lo que un servicio lanza para que siga corriendo nace fuera de su cgroup (decisión 344, C-0148).

`start_new_session` cambiaba la sesión y no el cgroup: con
`KillMode=control-group`, reiniciar `hub-web` mató a medias el resumen de una
reunión. Desde pytest no se puede reiniciar una unidad, así que lo que se
comprueba es la causa: el proceso lanzado está en otro cgroup que quien lo
lanza.
"""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

import pytest

from hub import procesos


def _cgroup(pid: int) -> str:
    return Path(f"/proc/{pid}/cgroup").read_text().strip()


@pytest.mark.skipif(not procesos.puede_desasir(), reason="sin systemd de usuario no hay scope que montar")
def test_lo_lanzado_queda_en_su_propio_cgroup_con_su_pid_y_su_salida(tmp_path):
    with open(tmp_path / "log", "w") as log:
        p = procesos.desasir(["sh", "-c", "echo hola; exec sleep 30"], cwd=tmp_path, salida=log)
    try:
        time.sleep(0.5)
        assert Path(f"/proc/{p.pid}/comm").read_text().strip() == "sleep", "el pid es el del comando"
        assert _cgroup(p.pid) != _cgroup(os.getpid())
        assert _cgroup(p.pid).endswith(".scope")
        assert (tmp_path / "log").read_text() == "hola\n"
    finally:
        p.kill()
        p.wait()


def test_sin_systemd_se_lanza_igual(monkeypatch, tmp_path):
    monkeypatch.setattr(procesos, "_puede", False)
    p = procesos.desasir(["true"], cwd=tmp_path)
    assert p.wait(timeout=5) == 0


def test_no_hereda_lo_que_systemd_le_da_al_servicio(monkeypatch, tmp_path):
    monkeypatch.setattr(procesos, "_puede", False)
    with open(tmp_path / "env", "w") as salida:
        p = procesos.desasir(["env"], env={"PATH": os.environ["PATH"], "NOTIFY_SOCKET": "/run/x",
                                           "INVOCATION_ID": "abc", "QUEDA": "1"}, salida=salida)
        p.wait(timeout=5)
    texto = (tmp_path / "env").read_text()
    assert "QUEDA=1" in texto and "NOTIFY_SOCKET" not in texto and "INVOCATION_ID" not in texto


def test_vivo_distingue_un_muerto_un_zombi_y_un_pid_reutilizado():
    p = subprocess.Popen(["sleep", "30"])
    h = procesos.huella(p.pid)
    assert procesos.vivo(h)
    assert not procesos.vivo({**h, "arranque": "1"}), "otro proceso con el mismo número no es éste"
    p.kill()
    time.sleep(0.3)
    assert not procesos.vivo(h), "un zombi sin recoger cuenta como muerto"
    p.wait()
    assert not procesos.vivo(h)
    assert not procesos.vivo(None) and procesos.huella(p.pid) is None


def test_la_sonda_de_systemd_no_se_repite(monkeypatch):
    """Se pregunta una vez por proceso, no en cada llamada: tmux la usa en
    su camino más caliente."""
    monkeypatch.setattr(procesos, "_puede", None)
    monkeypatch.setattr(procesos.shutil, "which", lambda _: "/usr/bin/systemd-run")
    monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", "unix:path=/run/user/1000/bus")
    sondas = []
    monkeypatch.setattr(procesos.subprocess, "run",
                        lambda orden, **kw: sondas.append(orden) or subprocess.CompletedProcess(orden, 0, "", ""))
    assert procesos.puede_desasir() is True
    assert procesos.puede_desasir() is True
    assert len(sondas) == 1
