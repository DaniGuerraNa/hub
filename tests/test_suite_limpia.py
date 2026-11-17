"""La suite no espera lo que no hace falta esperar ni deja basura al acabar (C-0325).

Una suite más rápida se corre más, y lo que deja en `/tmp` se va comiendo el
disco de quien la ejecuta: medido el 11-nov, cada pasada dejaba 0,8-1,0 GB en
`/tmp/pytest-of-*` y un socket de tmux muerto por cada servidor de pruebas
(144 en `/tmp/tmux-<uid>`). Aquí está lo que lo evita, para que no se pierda
sin que nadie se entere.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time

import pytest

import arnes_tmux
from arnes_js import ejecutar
from hub import entrevistador


def test_un_temporizador_tardio_no_se_espera_y_si_revienta_el_test_falla_igual(tmp_path):
    """El aviso que se va a los 5 s costaba 5,5 s de reloj por test: node
    seguía vivo hasta que vencía. Se adelanta el reloj, pero lo que valía
    esperar —que un error en ese temporizador tumbe el test— se conserva."""
    t0 = time.monotonic()
    with pytest.raises(AssertionError, match="vencio el de cinco segundos"):
        ejecutar("setTimeout(() => { throw new Error('vencio el de cinco segundos'); }, 5000);",
                 tmp_path)
    assert time.monotonic() - t0 < 2


def test_el_reloj_adelantado_respeta_el_orden_y_la_hora_de_cada_temporizador(tmp_path):
    """Adelantar no es ejecutar en cualquier orden: el de 1 s va antes que el
    de 3 s aunque se programara después, y `Date.now()` avanza con ellos (hay
    pantallas que deciden por el tiempo pasado, como el chat del secretario)."""
    guion = """
      const orden = []; const t0 = Date.now();
      setTimeout(() => orden.push('tres'), 3000);
      setTimeout(() => { orden.push('uno');
                         setTimeout(() => orden.push('uno-y-medio'), 500); }, 1000);
      setTimeout(() => { throw new Error('fin ' + JSON.stringify(
        { orden, paso: Date.now() - t0 >= 4990 })); }, 5000);
    """
    with pytest.raises(AssertionError) as fallo:
        ejecutar(guion, tmp_path)
    assert 'fin {"orden":["uno","uno-y-medio","tres"],"paso":true}' in str(fallo.value)


def test_lo_que_se_cancela_no_se_ejecuta_al_adelantar(tmp_path):
    r = ejecutar("""
      const asa = setTimeout(() => { throw new Error('no debia correr'); }, 4000);
      clearTimeout(asa);
    """, tmp_path)
    assert r["errores"] == []
    assert 4000 in r["temporizadores"]


def test_la_espera_de_arranque_de_un_agente_no_se_paga_en_cada_test():
    """`entrevistador.ESPERA_ARRANQUE` (1,5 s) se pagaba en cada ventana que
    abría un test de verdad. El único que necesita la espera real —el que
    comprueba que una ventana que muere al arrancar se dice— la pide con la
    marca `espera_de_arranque_real`."""
    assert entrevistador.ESPERA_ARRANQUE == 0


@pytest.mark.espera_de_arranque_real
def test_quien_lleva_la_marca_tiene_la_espera_de_arranque_de_verdad():
    assert entrevistador.ESPERA_ARRANQUE > 0


def test_el_servidor_de_tmux_de_la_suite_es_de_esta_pasada():
    """Uno por proceso: así al acabar se puede apagar y borrar su socket sin
    tumbar las sesiones de otra pasada que use el mismo nombre a la vez."""
    assert os.environ["HUB_TMUX_SOCKET"].endswith(f"-{os.getpid()}")


@pytest.mark.skipif(not shutil.which("tmux"), reason="tmux no disponible")
def test_apagar_un_tmux_de_pruebas_quita_el_servidor_y_su_socket():
    """`kill-server` deja el archivo del socket: medido con tmux 3.4, también
    cuando el servidor se va solo al cerrarse su última sesión."""
    zocalo = f"hub-tests-apagar-{os.getpid()}"
    subprocess.run(["tmux", "-L", zocalo, "-f", "/dev/null", "new-session", "-d", "-s", "x"],
                   check=True, timeout=10)
    ruta = arnes_tmux.ruta_del_socket(zocalo)
    assert ruta.exists()

    arnes_tmux.apagar(zocalo)

    vivo = subprocess.run(["tmux", "-L", zocalo, "list-sessions"], capture_output=True, timeout=10)
    assert vivo.returncode != 0
    assert not ruta.exists()


def test_apagar_un_tmux_que_no_existe_no_falla():
    arnes_tmux.apagar(f"hub-tests-nunca-arrancado-{os.getpid()}")


def test_lo_temporal_de_un_test_que_pasa_se_borra_al_acabar(request):
    """Sólo se guarda lo de los que fallan, que es lo que alguien mira."""
    assert request.config.getini("tmp_path_retention_policy") == "failed"
