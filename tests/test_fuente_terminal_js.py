"""El tamaño de letra del terminal tiene que sobrevivir a una recarga.

Sale de una pregunta suya sin responder: el terminal del móvil enseñaba **79
filas en 806 px**, o sea letra de unos 10 px, y hacía falta saber si la había
encogido él con «Ajustar a tmux» o si algo la encogía solo. Leyendo el código se
vio que sólo hay dos caminos por debajo de 12 y los dos son un clic suyo — pero
de paso apareció lo contrario, y peor: el tamaño **no se guardaba**.

Al arrancar, `aplicarPreset` se llamaba igual que al hacer clic, así que el
tamaño del preset pisaba el guardado Y lo reescribía. Los tres
`guardado.set('fuente', ...)` del archivo no servían para nada, y ningún test lo
veía porque todos empezaban con el localStorage vacío — que es justo lo que el
parámetro `previo` del arnés existe ahora para poder no hacer.
"""

from __future__ import annotations

import pytest

from arnes_js import ejecutar, script_de
from test_vista_trabajo_js import CONTEXTO

SONDA = "registro.valores.push(['fuente', TERM.options.fontSize]);"


def _fuente(tmp_path, previo=""):
    salida = ejecutar(
        script_de("trabajo.html", CONTEXTO), tmp_path, {}, SONDA, previo=previo
    )
    assert not salida["errores"], salida["errores"]
    return next(v[1] for v in salida["valores"]
                if isinstance(v, list) and len(v) == 2 and v[0] == "fuente")


def test_el_tamano_de_letra_elegido_sobrevive_a_la_recarga(tmp_path):
    """🔴 Lo que se rompía. En un teléfono es donde se toca el tamaño casi
    siempre, y donde perderlo en cada carga se nota en cada carga."""
    assert _fuente(tmp_path, "localStorage.setItem('hub.fuente', '17');") == 17


def test_un_tamano_pequeno_tambien_se_respeta(tmp_path):
    """El caso de «Ajustar a tmux», que baja la letra hasta que quepan las
    columnas. Si al recargar volviera a 14, la vista se recortaría otra vez."""
    assert _fuente(tmp_path, "localStorage.setItem('hub.fuente', '9');") == 9


def test_sin_nada_guardado_manda_el_preset(tmp_path):
    """Una visita nueva no tiene tamaño elegido: el del preset es lo correcto."""
    assert _fuente(tmp_path) == 14


def test_elegir_un_preset_SI_pone_su_tamano(tmp_path):
    """La salida de un tamaño ilegible, y por eso no se toca.

    Sin esto, quien baje la letra hasta las 8 px en el móvil sólo puede volver
    acertando cuántas veces darle a «+». Pulsar «Cómodo» tiene que devolverle
    su 14 aunque haya un 9 guardado.
    """
    salida = ejecutar(
        script_de("trabajo.html", CONTEXTO), tmp_path, {},
        "document.querySelectorAll('[data-preset]').forEach(b => b.onclick());" + SONDA,
        previo="localStorage.setItem('hub.fuente', '9');",
    )
    assert not salida["errores"], salida["errores"]
    fuentes = [v[1] for v in salida["valores"]
               if isinstance(v, list) and len(v) == 2 and v[0] == "fuente"]
    assert fuentes[-1] == 14
