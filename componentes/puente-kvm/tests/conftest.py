import contextlib
import socket
import subprocess
import uuid

import pytest


def puerto_libre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(autouse=True)
def hogar_aparte(tmp_path, monkeypatch):
    """Cada prueba con su propia carpeta de datos y su archivo de contraseña: nunca los de verdad.

    Y sin los ajustes de usuario de Claude Code de quien las corre
    (`CLAUDE_CONFIG_DIR` vacío): lo que la sesión toma de ellos depende de lo
    que haya ahí, y una prueba no puede depender de eso.

    Y con un puerto propio: si en el equipo hay un puente en marcha (el 8794),
    ninguna prueba le pregunta nada. Y sin el `INVOCATION_ID` de quien las
    corre: lanzadas desde una unidad de systemd, el puente de prueba creería
    ser el de esa unidad y ofrecería reiniciarla.

    🔴 Y con su propio servidor de tmux, con una bash dentro en vez de Claude:
    una página de prueba se engancha a la conversación al cargar, y en el
    servidor de siempre era la de verdad del puente de quien corre las pruebas
    (o, si no había, abría un `claude` real). Las que necesitan otra cosa (un
    `claude` de mentira) ponen el suyo encima.
    """
    from puente_kvm import config

    tmux = f"puente-pruebas-{uuid.uuid4().hex[:8]}"
    monkeypatch.delenv("INVOCATION_ID", raising=False)
    monkeypatch.delenv("PUENTE_SERVICIO", raising=False)
    monkeypatch.setenv("PUENTE_HOME", str(tmp_path / "puente"))
    monkeypatch.setenv("PUENTE_ENTORNO", str(tmp_path / "config" / "entorno"))
    monkeypatch.setenv("PUENTE_TMUX_SOCKET", tmux)
    monkeypatch.setenv("PUENTE_TERMINAL_ORDEN", "exec bash --norc --noprofile")
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude-de-la-persona"))
    monkeypatch.setattr(config, "PUERTO", puerto_libre())
    yield tmp_path / "puente"
    with contextlib.suppress(OSError, subprocess.SubprocessError):
        subprocess.run(["tmux", "-L", tmux, "kill-server"], capture_output=True, timeout=10)
