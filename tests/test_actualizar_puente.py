"""`actualizar.sh` y el Puente KVM (C-0459).

Tras actualizar, el puente de quien lo usa seguía con el código de antes: sus
pantallas, que se leen del disco, salían nuevas, y lo que hacían era lo viejo
hasta reiniciarlo a mano. Ahora lo reinicia `actualizar.sh` si su servicio es
el de este clon y no tiene una tarea a medias, y apunta cómo quedó para que
Actualizaciones lo cuente (C-0470, decisión 446): lo que falte se hace con
los botones de la pantalla del puente, no con un comando.

`systemctl` es de mentira (apunta lo que se le pide): reiniciar un
servicio de verdad en una prueba tocaría el de quien la corre. El
`servicio.sh` del puente también, porque decidir si está libre es suyo (lo
prueban sus propias pruebas).
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

from hub import actualizacion, config

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
    puente, que es quien decide si está libre: aquí sólo apunta, dice `motivo`
    (por la salida de errores, como sus fallos) y sale como se le diga."""
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
        guion.write_text(f'echo "servicio.sh $*" >> {llamadas}\nprintf "%b" "{motivo}" >&2\nexit {servicio_sale}\n')


def _correr(raiz: Path, falsos: Path, encendido="no") -> subprocess.CompletedProcess:
    # Con las mismas opciones que `actualizar.sh`: un fallo suyo no puede tumbarla.
    orden = f'set -euo pipefail; RAIZ="{raiz}"; . "{RAIZ}/scripts/lib/puente.sh"; reiniciar_puente {encendido}'
    return subprocess.run([BASH, "-c", orden], capture_output=True, text=True, timeout=30,
                          env={**os.environ, "PATH": f"{falsos}:{os.environ['PATH']}",
                               "HUB_HOME": str(config.HUB_HOME)})


def _apuntado() -> dict | None:
    ruta = config.HUB_HOME / "actualizacion" / "puente.json"
    return json.loads(ruta.read_text()) if ruta.exists() else None


def test_reinicia_el_puente_de_este_clon_por_su_puerta_y_pide_reabrir_la_conversacion(clon):
    raiz, falsos, llamadas = clon
    _falsos(raiz, falsos, llamadas, unidad_en=raiz / "componentes" / "puente-kvm")
    antes = int(time.time())
    r = _correr(raiz, falsos)
    assert r.returncode == 0, r.stderr
    assert "servicio.sh reiniciar --si-libre" in llamadas.read_text()
    assert "reiniciado" in r.stdout and "«Reabrir la conversación de Claude»" in r.stdout
    apuntado = _apuntado()
    assert apuntado["puente"] == "reiniciado" and apuntado["t"] >= antes


def test_con_un_enlace_de_por_medio_tambien_lo_reconoce(clon, tmp_path):
    raiz, falsos, llamadas = clon
    enlace = tmp_path / "enlace-al-hub"
    enlace.symlink_to(raiz)
    _falsos(raiz, falsos, llamadas, unidad_en=raiz / "componentes" / "puente-kvm")
    r = _correr(enlace, falsos)
    assert r.returncode == 0, r.stderr
    assert "servicio.sh reiniciar --si-libre" in llamadas.read_text()


def test_ocupado_no_lo_corta_y_dice_que_boton_pulsar_despues_sin_el_motivo(clon):
    """El motivo lleva nombres del trabajo (la tarea en curso) y el registro se
    ve también desde el teléfono (438): ni ahí ni en lo apuntado."""
    raiz, falsos, llamadas = clon
    _falsos(raiz, falsos, llamadas, unidad_en=raiz / "componentes" / "puente-kvm",
            servicio_sale=3, motivo="está con una tarea: leer usp_Secreto_Del_Trabajo")
    r = _correr(raiz, falsos)
    assert r.returncode == 0, r.stderr  # un aviso: no impide apuntar la versión
    assert "ocupado" in r.stdout and "«Reiniciar el puente»" in r.stdout
    assert "usp_Secreto" not in r.stdout + r.stderr
    assert "systemctl" not in r.stdout  # un botón, no un comando
    assert _apuntado()["puente"] == "ocupado"
    assert "usp_Secreto" not in (config.HUB_HOME / "actualizacion" / "puente.json").read_text()


def test_si_no_se_puede_reiniciar_es_un_aviso_no_un_fallo_y_dice_por_que(clon):
    """Sin el porqué no se sabría qué mirar. La última línea de su salida es de
    `systemctl` o la de «no pude preguntarle al puente» (rc 4), sin nombres del
    trabajo; el motivo de «ocupado» (rc 3), en cambio, no sale nunca."""
    raiz, falsos, llamadas = clon
    _falsos(raiz, falsos, llamadas, unidad_en=raiz / "componentes" / "puente-kvm",
            servicio_sale=4, motivo="no pude preguntarle al puente si está ocupado: no contesta\\n\\n")
    r = _correr(raiz, falsos)
    assert r.returncode == 0, r.stderr
    assert "no se pudo reiniciar: no pude preguntarle al puente si está ocupado: no contesta" in r.stdout
    assert "«Reiniciar el puente»" in r.stdout and "registro de su servicio" in r.stdout
    assert "ocupado. Cuando" not in r.stdout and "cuando no esté ocupado" not in r.stdout  # no lo estaba
    assert _apuntado()["puente"] == "no_pudo"


def test_si_systemd_no_lo_reinicia_dice_su_ultima_linea(clon):
    raiz, falsos, llamadas = clon
    _falsos(raiz, falsos, llamadas, unidad_en=raiz / "componentes" / "puente-kvm", servicio_sale=1,
            motivo="Job for puente-kvm.service failed because the control process exited with error code.\\n"
                   "See the logs for details.\\n")
    r = _correr(raiz, falsos)
    assert r.returncode == 0, r.stderr
    assert "no se pudo reiniciar: See the logs for details." in r.stdout
    assert "Job for" not in r.stdout  # sólo la última


@pytest.mark.parametrize("sale", [1, 2, 4, 127])
def test_cualquier_otra_salida_de_su_puerta_se_apunta_como_no_pudo(clon, sale):
    raiz, falsos, llamadas = clon
    _falsos(raiz, falsos, llamadas, unidad_en=raiz / "componentes" / "puente-kvm", servicio_sale=sale)
    assert _correr(raiz, falsos).returncode == 0
    assert _apuntado()["puente"] == "no_pudo"


def test_sin_hub_home_no_apunta_nada_y_no_tumba_la_actualizacion(clon):
    raiz, falsos, llamadas = clon
    _falsos(raiz, falsos, llamadas, unidad_en=raiz / "componentes" / "puente-kvm")
    orden = f'set -euo pipefail; unset HUB_HOME; RAIZ="{raiz}"; . "{RAIZ}/scripts/lib/puente.sh"; reiniciar_puente no'
    r = subprocess.run([BASH, "-c", orden], capture_output=True, text=True, timeout=30,
                       env={**os.environ, "PATH": f"{falsos}:{os.environ['PATH']}"})
    assert r.returncode == 0, r.stderr
    assert "reiniciado" in r.stdout and _apuntado() is None


def test_el_puente_de_otra_carpeta_no_se_toca(clon, tmp_path):
    raiz, falsos, llamadas = clon
    (tmp_path / "otro" / "puente-kvm").mkdir(parents=True)
    _falsos(raiz, falsos, llamadas, unidad_en=tmp_path / "otro" / "puente-kvm")
    r = _correr(raiz, falsos)
    assert r.returncode == 0, r.stderr
    assert "servicio.sh" not in llamadas.read_text() and r.stdout == ""
    assert _apuntado() is None  # de otro clon: ni se toca ni se cuenta


def test_parado_se_queda_parado(clon):
    raiz, falsos, llamadas = clon
    _falsos(raiz, falsos, llamadas, unidad_en=raiz / "componentes" / "puente-kvm", activo=False)
    r = _correr(raiz, falsos)
    assert r.returncode == 0, r.stderr
    assert "servicio.sh" not in llamadas.read_text()
    assert _apuntado() is None


def test_sin_servicio_y_encendido_pide_reiniciarlo_a_mano(clon):
    raiz, falsos, llamadas = clon
    _falsos(raiz, falsos, llamadas, unidad_en=None)
    # Apagado en Ajustes no se le habla de él a quien no lo usa.
    assert _correr(raiz, falsos, encendido="no").stdout == ""
    assert _apuntado() is None
    assert "arrancar.sh" in _correr(raiz, falsos, encendido="si").stdout
    assert _apuntado()["puente"] == "sin_servicio"


def test_sin_el_componente_no_hace_nada(clon):
    raiz, falsos, llamadas = clon
    shutil.rmtree(raiz / "componentes")
    _falsos(raiz, falsos, llamadas, unidad_en=None)
    r = _correr(raiz, falsos, encendido="si")
    assert r.returncode == 0 and r.stdout == ""
    assert not llamadas.exists()


# ── lo que cuenta Actualizaciones ────────────────────────────────────────────

def _actualizacion(t: int, *, puente: str | None = None, t_puente: int | None = None, rc: int | None = None,
                   t_resultado: int | None = None) -> None:
    carpeta = actualizacion.carpeta()
    (carpeta / "inicio.json").write_text(json.dumps({"t": t}))
    (carpeta / "registro.log").write_text("5/7 · Servicios\n")
    if puente:
        (carpeta / "puente.json").write_text(json.dumps({"puente": puente, "t": t_puente or t}))
    if rc is not None:
        (carpeta / "resultado.json").write_text(json.dumps({"rc": rc, "t": t_resultado or t + 10}))


def test_la_actualizacion_cuenta_como_quedo_el_puente_si_es_de_esta_vuelta():
    t = int(time.time()) - 60
    _actualizacion(t, puente="ocupado", t_puente=t + 5, rc=0, t_resultado=t + 10)
    assert actualizacion.estado()["puente"] == "ocupado"


def test_mientras_actualiza_ya_lo_cuenta():
    t = int(time.time())
    _actualizacion(t, puente="reiniciado", t_puente=t + 1)
    assert actualizacion.estado()["en_marcha"] and actualizacion.estado()["puente"] == "reiniciado"


@pytest.mark.parametrize("t_puente", [-30, 40], ids=["de-la-vuelta-anterior", "de-un-actualizar-a-mano-despues"])
def test_lo_apuntado_de_otra_actualizacion_no_se_cuenta(t_puente):
    t = int(time.time()) - 60
    _actualizacion(t, puente="ocupado", t_puente=t + t_puente, rc=0, t_resultado=t + 10)
    assert actualizacion.estado()["puente"] is None


@pytest.mark.parametrize("contenido", ['{"puente": "lo-que-sea", "t": 9999999999}', "no es json", '{"t": 1}'])
def test_lo_apuntado_que_no_se_entiende_no_se_cuenta(contenido):
    _actualizacion(int(time.time()))
    (actualizacion.carpeta() / "puente.json").write_text(contenido)
    assert actualizacion.estado()["puente"] is None


def test_sin_haber_lanzado_ninguna_no_se_cuenta_nada():
    (actualizacion.carpeta() / "puente.json").write_text(json.dumps({"puente": "ocupado", "t": int(time.time())}))
    assert actualizacion.estado()["puente"] is None


@pytest.fixture
def cliente(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from hub import db, web

    ruta = tmp_path / "hub.db"
    db.inicializar(db.conectar(ruta))

    def conexion_de_pruebas():
        con = db.conectar(ruta)
        db.inicializar(con)
        return con

    monkeypatch.setattr(web, "conexion", conexion_de_pruebas)
    monkeypatch.setattr(actualizacion, "cambios_locales", lambda raiz=None: [])
    monkeypatch.setenv("HUB_BUSCAR_VERSIONES", "0")
    return TestClient(web.app)


@pytest.mark.parametrize("como, dice", [
    ("ocupado", "no se reinició: estaba ocupado. Cuando acabe, ábrelo y pulsa «Reiniciar el puente»"),
    ("no_pudo", "no se pudo reiniciar (el registro de abajo dice por qué). Ábrelo: si dice que sigue con el "
                "código de antes, pulsa «Reiniciar el puente»; si no abre, mira el registro de su servicio"),
    ("sin_servicio", "no se reinició: no tiene servicio"),
    ("reiniciado", "se reinició. En su pantalla, pulsa «Reabrir la conversación de Claude»"),
])
def test_actualizaciones_lo_cuenta_en_pasado_y_lleva_al_puente(cliente, como, dice):
    t = int(time.time()) - 60
    _actualizacion(t, puente=como, t_puente=t + 5, rc=0, t_resultado=t + 10)
    html = cliente.get("/actualizaciones").text
    parrafo = html.split('id="puente-actualizado"')[1].split("</p>")[0]
    assert dice in " ".join(parrafo.split())
    assert 'href="/puente"' in parrafo
    assert "systemctl" not in parrafo
    if como != "ocupado":
        assert "ocupado" not in parrafo  # sólo lo dice cuando lo estaba


def test_sin_nada_del_puente_actualizaciones_no_lo_nombra(cliente):
    _actualizacion(int(time.time()) - 60, rc=0)
    assert 'id="puente-actualizado"' not in cliente.get("/actualizaciones").text
