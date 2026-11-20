"""`actualizar.sh` y el Puente KVM (C-0459).

Tras actualizar, el puente de quien lo usa seguía con el código de antes: sus
pantallas, que se leen del disco, salían nuevas, y lo que hacían era lo viejo
hasta reiniciarlo a mano. Ahora lo reinicia `actualizar.sh` si su servicio es
el de este clon y no tiene una tarea a medias.

`systemctl` es de mentira (apunta lo que se le pide): reiniciar un
servicio de verdad en una prueba tocaría el de quien la corre. El
`servicio.sh` del puente también, porque decidir si está libre es suyo (lo
prueban sus propias pruebas).
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
BASH = shutil.which("bash") or "/bin/bash"


@pytest.fixture
def clon(tmp_path):
    raiz = tmp_path / "hub"
    (raiz / "componentes" / "puente-kvm").mkdir(parents=True)
    falsos = tmp_path / "bin"
    falsos.mkdir()
    return raiz, falsos, tmp_path / "llamadas"


def _falsos(raiz: Path, falsos: Path, llamadas: Path, *, unidad_en: Path | None, activo=True,
            servicio_sale=0, motivo=""):
    """Un `systemctl` con una unidad `puente-kvm` (o ninguna), y el `servicio.sh` del
    puente, que es quien decide si está libre: aquí sólo apunta y sale como se le diga."""
    (falsos / "systemctl").write_text(f"""#!/bin/bash
echo "systemctl $*" >> {llamadas}
case "$*" in
  "--user cat puente-kvm") {'exit 0' if unidad_en else 'exit 1'} ;;
  "--user show -p WorkingDirectory --value puente-kvm") echo "{unidad_en or ''}" ;;
  "--user is-active --quiet puente-kvm") {'exit 0' if activo else 'exit 3'} ;;
esac
""")
    (falsos / "systemctl").chmod(0o755)
    guion = raiz / "componentes" / "puente-kvm" / "scripts" / "servicio.sh"
    if guion.parent.parent.is_dir():
        guion.parent.mkdir(exist_ok=True)
        guion.write_text(f'echo "servicio.sh $*" >> {llamadas}\necho "{motivo}"\nexit {servicio_sale}\n')


def _correr(raiz: Path, falsos: Path, encendido="no") -> subprocess.CompletedProcess:
    # Con las mismas opciones que `actualizar.sh`: un fallo suyo no puede tumbarla.
    orden = f'set -euo pipefail; RAIZ="{raiz}"; . "{RAIZ}/scripts/lib/puente.sh"; reiniciar_puente {encendido}'
    return subprocess.run([BASH, "-c", orden], capture_output=True, text=True, timeout=30,
                          env={**os.environ, "PATH": f"{falsos}:{os.environ['PATH']}"})


def test_reinicia_el_puente_de_este_clon_por_su_puerta_y_pide_reabrir_la_conversacion(clon):
    raiz, falsos, llamadas = clon
    _falsos(raiz, falsos, llamadas, unidad_en=raiz / "componentes" / "puente-kvm")
    r = _correr(raiz, falsos)
    assert r.returncode == 0, r.stderr
    assert "servicio.sh reiniciar --si-libre" in llamadas.read_text()
    assert "reiniciado" in r.stdout and "Reabrir" in r.stdout


def test_con_un_enlace_de_por_medio_tambien_lo_reconoce(clon, tmp_path):
    raiz, falsos, llamadas = clon
    enlace = tmp_path / "enlace-al-hub"
    enlace.symlink_to(raiz)
    _falsos(raiz, falsos, llamadas, unidad_en=raiz / "componentes" / "puente-kvm")
    r = _correr(enlace, falsos)
    assert r.returncode == 0, r.stderr
    assert "servicio.sh reiniciar --si-libre" in llamadas.read_text()


def test_ocupado_no_lo_corta_y_dice_como_hacerlo_despues(clon):
    raiz, falsos, llamadas = clon
    _falsos(raiz, falsos, llamadas, unidad_en=raiz / "componentes" / "puente-kvm",
            servicio_sale=3, motivo="está con una tarea: capturando")
    r = _correr(raiz, falsos)
    assert r.returncode == 0, r.stderr  # un aviso: no impide apuntar la versión
    assert "capturando" in r.stdout and "systemctl --user restart puente-kvm" in r.stdout


def test_si_no_se_puede_reiniciar_es_un_aviso_no_un_fallo(clon):
    raiz, falsos, llamadas = clon
    _falsos(raiz, falsos, llamadas, unidad_en=raiz / "componentes" / "puente-kvm",
            servicio_sale=4, motivo="no pude preguntarle al puente")
    r = _correr(raiz, falsos)
    assert r.returncode == 0, r.stderr
    assert "no se pudo reiniciar" in r.stdout


def test_el_puente_de_otra_carpeta_no_se_toca(clon, tmp_path):
    raiz, falsos, llamadas = clon
    (tmp_path / "otro" / "puente-kvm").mkdir(parents=True)
    _falsos(raiz, falsos, llamadas, unidad_en=tmp_path / "otro" / "puente-kvm")
    r = _correr(raiz, falsos)
    assert r.returncode == 0, r.stderr
    assert "servicio.sh" not in llamadas.read_text() and r.stdout == ""


def test_parado_se_queda_parado(clon):
    raiz, falsos, llamadas = clon
    _falsos(raiz, falsos, llamadas, unidad_en=raiz / "componentes" / "puente-kvm", activo=False)
    r = _correr(raiz, falsos)
    assert r.returncode == 0, r.stderr
    assert "servicio.sh" not in llamadas.read_text()


def test_sin_servicio_y_encendido_pide_reiniciarlo_a_mano(clon):
    raiz, falsos, llamadas = clon
    _falsos(raiz, falsos, llamadas, unidad_en=None)
    assert "arrancar.sh" in _correr(raiz, falsos, encendido="si").stdout
    # Apagado en Ajustes no se le habla de él a quien no lo usa.
    assert _correr(raiz, falsos, encendido="no").stdout == ""


def test_sin_el_componente_no_hace_nada(clon):
    raiz, falsos, llamadas = clon
    shutil.rmtree(raiz / "componentes")
    _falsos(raiz, falsos, llamadas, unidad_en=None)
    r = _correr(raiz, falsos, encendido="si")
    assert r.returncode == 0 and r.stdout == ""
    assert not llamadas.exists()
