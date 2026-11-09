"""Un nombre o una ruta no se ejecuta en tmux (C-0078, reglas duras 9 y 10).

`-c` y `-n`, `rename-window` y `select-pane -T` expanden formatos de tmux, y
`#(orden)` dentro de un formato ejecuta la orden. Entran por ahí el nombre
libre de un slot, el de una carpeta clonada y el cwd de una muestra al
restaurar. Se prueba con un tmux de verdad (el servidor aparte de
`conftest.py`): lo que importa es lo que hace tmux, no la lista de argumentos.
"""

from __future__ import annotations

import shutil
import time

import pytest

from hub import tmux

pytestmark = pytest.mark.skipif(not shutil.which("tmux"), reason="sin tmux")


@pytest.fixture
def sesion(request):
    nombre = f"formatos-{request.node.name[-12:]}".replace("_", "-").replace("[", "").replace("]", "")
    yield nombre
    try:
        tmux._correr(["kill-session", "-t", f"={nombre}"])
    except RuntimeError:
        pass


def _trampa(tmp_path) -> tuple[str, object]:
    testigo = tmp_path / "ejecutado"
    return f"#(touch {testigo})", testigo


def _no_se_ejecuto(testigo) -> None:
    # `#()` corre como trabajo de fondo de tmux: se le da tiempo a aparecer.
    time.sleep(1.0)
    assert not testigo.exists(), "tmux ejecutó lo que venía en un nombre o una ruta"


def _ventanas(sesion: str) -> list[str]:
    return tmux._correr(["list-windows", "-t", f"={sesion}", "-F", "#{window_name}"]).splitlines()


def test_el_nombre_de_una_ventana_no_se_ejecuta_y_se_ve_tal_cual(tmp_path, sesion):
    trampa, testigo = _trampa(tmp_path)
    tmux.nueva_sesion(sesion, str(tmp_path), comando="sleep 30")
    tmux.nueva_ventana(sesion, str(tmp_path), trampa, "sleep 30")
    _no_se_ejecuto(testigo)
    assert trampa in _ventanas(sesion)


def test_la_ruta_de_una_sesion_nueva_no_se_ejecuta(tmp_path, sesion):
    trampa, testigo = _trampa(tmp_path)
    tmux.nueva_sesion(sesion, trampa, nombre_ventana=trampa, comando="sleep 30")
    _no_se_ejecuto(testigo)


def test_abrir_ventana_con_nombre_y_ruta_de_fuera_no_ejecuta_nada(tmp_path, sesion):
    trampa, testigo = _trampa(tmp_path)
    tmux.nueva_sesion(sesion, str(tmp_path), comando="sleep 30")
    rara = tmp_path / "carpeta#rara"
    rara.mkdir()
    panel = tmux.abrir_ventana(str(rara), trampa, "sleep 30", session=sesion)
    _no_se_ejecuto(testigo)
    ruta = tmux._correr(["display-message", "-p", "-t", panel, "#{pane_current_path}"]).strip()
    assert ruta == str(rara), "un # en la ruta tiene que llegar como #"


def test_renombrar_relanzar_y_titular_tampoco_ejecutan(tmp_path, sesion):
    trampa, testigo = _trampa(tmp_path)
    tmux.nueva_sesion(sesion, str(tmp_path), comando="sleep 30")
    panel = tmux.panel_de_sesion(sesion)
    tmux.renombrar_ventana(sesion, 0, trampa)
    tmux.escribir_titulo(panel, trampa)
    tmux.relanzar_panel(panel, trampa, "sleep 30")
    _no_se_ejecuto(testigo)
    assert _ventanas(sesion) == [trampa]
