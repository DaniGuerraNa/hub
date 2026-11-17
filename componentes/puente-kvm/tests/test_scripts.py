"""Los scripts de arranque, ejecutados desde una copia del código en otra ruta.

El puente puede vivir en `~/projects/puente-kvm` o dentro de otro repositorio
(`<clon>/componentes/puente-kvm`): ninguna ruta del repositorio puede estar
fija, y la unidad de systemd se genera con la carpeta real de cada clon.
"""

import shutil
import subprocess
from pathlib import Path

import pytest

from puente_kvm import config


@pytest.fixture
def clon(tmp_path):
    """Una copia de los scripts en otra ruta, con un uv de mentira que cuenta cómo lo llamaron."""
    destino = tmp_path / "otro-repo" / "componentes" / "puente-kvm"
    shutil.copytree(config.CODIGO / "scripts", destino / "scripts")
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    uv = bin_ / "uv"
    uv.write_text('#!/bin/sh\necho "dir:$(pwd -P)"\necho "args:$*"\necho "clave:[$JETKVM_CLAVE]"\n')
    uv.chmod(0o755)
    casa = tmp_path / "casa"
    casa.mkdir()
    return destino, bin_, casa


def correr(script: Path, *args, bin_: Path, casa: Path, **env) -> subprocess.CompletedProcess:
    entorno = {"PATH": f"{bin_}:/usr/bin:/bin", "HOME": str(casa), **env}
    return subprocess.run(["bash", str(script), *args], capture_output=True, text=True, env=entorno, timeout=20)


def test_la_unidad_lleva_la_carpeta_real_del_clon_y_el_uv_que_encuentra(clon):
    destino, bin_, casa = clon
    r = correr(destino / "scripts/servicio.sh", "unidad", bin_=bin_, casa=casa, PUENTE_PUERTO="8899")
    assert r.returncode == 0, r.stderr
    unidad = r.stdout
    assert f"WorkingDirectory={destino.resolve()}\n" in unidad
    assert f"ExecStart={bin_}/uv run --frozen puente-kvm web\n" in unidad
    assert f"EnvironmentFile=-{casa}/.config/puente-kvm/entorno\n" in unidad
    assert 'Environment="PUENTE_PUERTO=8899"' in unidad
    assert f'Environment="PATH={bin_}:/usr/bin:/bin"' in unidad
    assert "%h/projects" not in unidad


def test_sin_uv_la_unidad_no_se_genera_y_dice_por_que(clon, tmp_path):
    destino, _, casa = clon
    vacio = tmp_path / "vacio"
    vacio.mkdir()
    r = subprocess.run(["/bin/bash", str(destino / "scripts/servicio.sh"), "unidad"], capture_output=True,
                       text=True, env={"PATH": str(vacio), "HOME": str(casa)}, timeout=20)
    assert r.returncode == 1 and "uv" in r.stderr


def test_el_repositorio_no_lleva_una_unidad_con_rutas_fijas():
    assert not (config.CODIGO / "scripts" / "puente-kvm.service").exists()


def test_arrancar_sin_systemd_lee_la_clave_como_systemd_y_arranca_en_el_clon(clon):
    destino, bin_, casa = clon
    entorno = casa / ".config/puente-kvm/entorno"
    entorno.parent.mkdir(parents=True)
    entorno.write_text('# la contraseña del JetKVM\nJETKVM_CLAVE="a b$HOME`id`"\n')
    entorno.chmod(0o600)
    r = correr(destino / "scripts/arrancar.sh", bin_=bin_, casa=casa)
    assert r.returncode == 0, r.stderr
    assert f"dir:{destino.resolve()}" in r.stdout
    assert "args:run --frozen puente-kvm web" in r.stdout
    assert "clave:[a b$HOME`id`]" in r.stdout  # tal cual: ni se expande ni se ejecuta
    assert "Ojo" not in r.stderr


def test_arrancar_avisa_si_otros_pueden_leer_la_clave(clon):
    destino, bin_, casa = clon
    entorno = casa / ".config/puente-kvm/entorno"
    entorno.parent.mkdir(parents=True)
    entorno.write_text("JETKVM_CLAVE=x\n")
    entorno.chmod(0o644)
    r = correr(destino / "scripts/arrancar.sh", bin_=bin_, casa=casa)
    assert "chmod 600" in r.stderr


def test_el_mcp_json_del_repositorio_no_lleva_rutas_de_nadie():
    texto = (config.CODIGO / ".mcp.json").read_text()
    assert "/home/" not in texto and "/Users/" not in texto
    assert '"command": "uv"' in texto and "${PUENTE_CODIGO:-.}" in texto


def test_parar_o_reiniciar_el_servicio_no_lo_deja_en_fallo(clon):
    # uvicorn sale con 143 (SIGTERM) al pararlo: para systemd tiene que ser un final normal.
    destino, bin_, casa = clon
    unidad = correr(destino / "scripts/servicio.sh", "unidad", bin_=bin_, casa=casa).stdout
    assert "SuccessExitStatus=143\n" in unidad


def test_quitar_limpia_el_fallo_y_cierra_la_conversacion_de_claude(clon):
    destino, bin_, casa = clon
    registro = casa / "ordenes.log"
    for nombre in ("systemctl", "tmux"):
        f = bin_ / nombre
        f.write_text(f'#!/bin/sh\necho "{nombre} $*" >> "{registro}"\nexit 0\n')
        f.chmod(0o755)
    r = correr(destino / "scripts/servicio.sh", "quitar", bin_=bin_, casa=casa)
    assert r.returncode == 0, r.stderr
    ordenes = registro.read_text()
    assert "systemctl --user reset-failed puente-kvm" in ordenes
    # La sesión de tmux nace fuera del servicio a propósito: si no se cierra, su
    # servidor MCP sigue con el código viejo tras actualizar o quitar.
    assert "tmux kill-session -t =puente-claude" in ordenes
