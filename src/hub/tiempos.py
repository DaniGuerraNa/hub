"""Por qué tarda una petición, sin perfilador (C-0310).

Varias pantallas tardaban más de 300 ms en el servidor y la única forma de
saber en qué era un `cProfile` a mano: medio día para una pregunta que se
repite con cada pantalla nueva. Ahora cada petición lleva su cuenta y la dice
en la cabecera `Server-Timing` (la pinta el navegador: DevTools, pestaña Red,
«Timing»), y la línea del journal de una petición lenta (C-0245) lleva los
mismos tramos.

Cómo se llena: `web._RegistroDeAcceso` abre la cuenta (`empezar`) al llegar
la petición; cada función marcada con `@medido` —y cada bloque `tramo(...)`—
suma su tiempo bajo su nombre; al arrancar la respuesta, `cabecera` la
escribe. Fuera de una petición (el muestreo, el secretario, los tests que
llaman a `api` directamente) no hay cuenta, y medir no hace nada más que
llamar.

🔴 **Sólo nombres de función.** Nunca argumentos, rutas ni nada de lo que se
leyó: la cabecera viaja al teléfono por la red privada y la línea se queda en
el journal, y una ruta de un proyecto es justo lo que no tiene que salir de la
máquina sin querer. `medido` usa el nombre con que se definió la función, y
`tramo` se llama siempre con un literal; ninguno de los dos se arma con datos
de la petición.

Por qué un `ContextVar` con un diccionario dentro, y no un valor que se
reasigna: la variable se COPIA al cruzar a otro hilo (las rutas `def` corren
en el pool de Starlette) y a otra tarea (`_la_puerta` es un
`BaseHTTPMiddleware`, que corre lo de dentro en una tarea aparte). Lo que se
reasigna en la copia no vuelve; lo que se añade al mismo diccionario sí, porque
las dos copias apuntan al mismo objeto. Lo comprueba `tests/test_tiempos.py`
con una ruta `def` de verdad detrás de `_la_puerta`.

🔴 **Módulo hoja: sólo librería estándar**, como `reloj`: lo importan `api`,
`base`, `kits` y `transcripts`, y si esto importara algo del hub cerraría un
círculo.
"""

from __future__ import annotations

import contextlib
import functools
import re
import time
import unicodedata
from collections.abc import Callable, Iterator
from contextvars import ContextVar
from typing import Any, TypeVar

F = TypeVar("F", bound=Callable[..., Any])

# Nombre → [veces, segundos]. Se acumula por nombre y no se guarda cada
# llamada: una pantalla que lee 47 manifiestos daría 47 entradas iguales y una
# cabecera que no cabe.
Tramos = dict[str, list]

_CUENTA: ContextVar[Tramos | None] = ContextVar("hub_tiempos", default=None)

# Cuántos tramos salen, los más largos. Una cabecera tiene tope en los proxies
# (8 KB es lo habitual) y la línea del journal se lee de un vistazo o no se lee.
TOPE_CABECERA = 12
TOPE_LINEA = 6

# Un nombre de métrica de `Server-Timing` es un `token` de HTTP: sin espacios,
# sin comas ni `;`, y en ASCII. Un nombre de función en castellano puede
# llevar «ñ» o tilde.
_NO_TOKEN = re.compile(r"[^A-Za-z0-9_.\-]")


def empezar() -> Tramos:
    """Abre la cuenta de la petición en curso y la devuelve.

    Quien la abre se queda con el diccionario: es el mismo que llenan los
    hilos y tareas de dentro, así que al final lo lee sin volver a preguntar
    a la variable (que en su contexto podría ser otra copia)."""
    tramos: Tramos = {}
    _CUENTA.set(tramos)
    return tramos


@contextlib.contextmanager
def tramo(nombre: str) -> Iterator[None]:
    """Suma lo que tarde el bloque bajo `nombre`, si hay una petición abierta.

    `nombre` es un literal escrito en el código, nunca algo de la petición
    (ver el porqué arriba)."""
    tramos = _CUENTA.get()
    if tramos is None:
        yield
        return
    inicio = time.perf_counter()
    try:
        yield
    finally:
        cuenta = tramos.setdefault(nombre, [0, 0.0])
        cuenta[0] += 1
        cuenta[1] += time.perf_counter() - inicio


def medido(funcion: F) -> F:
    """Decorador: cada llamada a `funcion` suma su tiempo bajo su nombre."""
    nombre = funcion.__name__

    @functools.wraps(funcion)
    def envoltura(*args, **kwargs):
        if _CUENTA.get() is None:
            return funcion(*args, **kwargs)
        with tramo(nombre):
            return funcion(*args, **kwargs)

    return envoltura  # type: ignore[return-value]


def _token(nombre: str) -> str:
    ascii_ = unicodedata.normalize("NFKD", nombre).encode("ascii", "ignore").decode()
    return _NO_TOKEN.sub("_", ascii_) or "_"


def _mas_largos(tramos: Tramos, tope: int) -> list[tuple[str, int, float]]:
    filas = [(nombre, int(v[0]), float(v[1])) for nombre, v in list(tramos.items())]
    return sorted(filas, key=lambda f: -f[2])[:tope]


def cabecera(tramos: Tramos, total: float | None = None) -> str:
    """El valor de `Server-Timing`: `total` primero y luego los tramos más
    largos, en milisegundos. Las funciones anidadas se solapan (la de fuera
    incluye a las de dentro), que es como lo lee DevTools."""
    partes = []
    if total is not None:
        partes.append(f"total;dur={total * 1000:.1f}")
    for nombre, veces, segundos in _mas_largos(tramos, TOPE_CABECERA):
        parte = f"{_token(nombre)};dur={segundos * 1000:.1f}"
        if veces > 1:
            parte += f';desc="{veces} veces"'
        partes.append(parte)
    return ", ".join(partes)


def resumen(tramos: Tramos) -> str:
    """Los tramos más largos para la línea del journal: `explorar 1750 ms,
    confin 1210 ms ×2`. Vacío si no se midió nada."""
    return ", ".join(
        f"{_token(nombre)} {segundos * 1000:.0f} ms" + (f" ×{veces}" if veces > 1 else "")
        for nombre, veces, segundos in _mas_largos(tramos, TOPE_LINEA)
    )
