import socket

import pytest


def puerto_libre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(autouse=True)
def hogar_aparte(tmp_path, monkeypatch):
    """Cada prueba con su propia carpeta de datos y su archivo de contraseña: nunca los de verdad.

    Y con un puerto propio: si en el equipo hay un puente en marcha (el 8794),
    ninguna prueba le pregunta nada.
    """
    from puente_kvm import config

    monkeypatch.setenv("PUENTE_HOME", str(tmp_path / "puente"))
    monkeypatch.setenv("PUENTE_ENTORNO", str(tmp_path / "config" / "entorno"))
    monkeypatch.setattr(config, "PUERTO", puerto_libre())
    return tmp_path / "puente"
