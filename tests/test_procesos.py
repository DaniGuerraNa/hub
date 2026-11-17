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


# ── una shell en reposo (C-0352, revisión cruzada) ───────────────────────────
#
# tmux dice `bash` con `bash x.sh` o con un comando compuesto: el nombre no
# basta para decir «sin nada en marcha». Procesos de verdad, mirados en /proc.

SHELLS = frozenset({"bash", "sh"})


def _hijos(pid: int) -> list[int]:
    return [int(h) for t in Path(f"/proc/{pid}/task").iterdir()
            for h in Path(t, "children").read_text().split()]


def _esperar_hijo(pid: int) -> list[int]:
    limite = time.monotonic() + 3
    while time.monotonic() < limite:
        if hijos := _hijos(pid):
            return hijos
        time.sleep(0.02)
    raise AssertionError("el hijo no llegó a nacer")


def _lanzar(orden, entrada=b""):
    p = subprocess.Popen(orden, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if entrada:
        p.stdin.write(entrada)
        p.stdin.flush()
    return p


def test_una_shell_a_secas_sin_nada_debajo_esta_en_reposo():
    p = _lanzar(["bash", "--norc", "--noprofile"])
    try:
        time.sleep(0.1)
        assert procesos.shell_en_reposo(p.pid, SHELLS) is True
    finally:
        p.kill()
        p.wait()


def test_una_shell_con_algo_en_marcha_debajo_no_esta_en_reposo():
    p = _lanzar(["bash", "--norc", "--noprofile"], b"sleep 30\n")
    hijos = []
    try:
        hijos = _esperar_hijo(p.pid)
        assert procesos.shell_en_reposo(p.pid, SHELLS) is False
    finally:
        for h in hijos:   # por su pid, el que da /proc: nunca por patrón
            os.kill(h, 9)
        p.kill()
        p.wait()


@pytest.mark.parametrize("orden", [
    ["bash", "GUION"],                       # `bash x.sh`: un guion, aunque sólo haga `read`
    ["bash", "-c", "read x; read y"],         # un comando compuesto
    ["sleep", "30"],                         # no es una shell
])
def test_lo_que_tmux_llamaria_shell_pero_ejecuta_algo_no_esta_en_reposo(orden, tmp_path):
    guion = tmp_path / "x.sh"
    guion.write_text("read x\n", encoding="utf-8")
    p = _lanzar([str(guion) if a == "GUION" else a for a in orden])
    try:
        time.sleep(0.1)
        assert procesos.shell_en_reposo(p.pid, SHELLS) is False
    finally:
        p.kill()
        p.wait()


def test_lo_que_no_se_puede_leer_no_cuenta_como_en_reposo():
    p = subprocess.Popen(["true"])
    p.wait()
    assert procesos.shell_en_reposo(p.pid, SHELLS) is False
