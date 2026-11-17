"""Recordar lo caro de leer mientras siga valiendo, en la memoria del proceso (C-0310).

Varias pantallas releían en cada visita lo mismo: el resumen de cada
transcript (megas de JSONL que no han cambiado), los `kit.yml` de todos los
kits, la resolución de cada ruta declarada sobre un disco lento. Esto lo
recuerda, de dos formas y ninguna más:

- `por_archivo`: mientras el archivo tenga la misma fecha, tamaño e inodo, lo
  que se sacó de él sigue valiendo. Sin plazo que esperar ni que
  ajustar. El inodo está porque reemplazar un archivo por otro del mismo
  tamaño en el mismo instante (escribir aparte y renombrar) no cambia lo
  demás; medido en la unidad de Windows montada, el inodo es estable entre
  lecturas, así que no cuesta aciertos.
- `por_tiempo`: lo que no tiene un archivo que mirar (resolver una ruta con
  sus enlaces) se fía un plazo corto que decide quien lo pide. Pasado el
  plazo, `ultimo` aún lo da a quien no pudo calcularlo de nuevo.

🔴 **Lo que esto NO es.** No es una caché compartida entre procesos ni algo que
rellene el ciclo lento para los demás: la web, el muestreo y el secretario
tienen cada uno la suya, empieza vacía al arrancar y se llena con la primera
lectura. (El ciclo lento sí la usa para lo suyo: `consumo` recuerda lo leído
de cada transcript, dentro del proceso del muestreo, C-0326.) No va a
ninguna base ni a ningún archivo (regla dura 1: no es fuente de nada, y
perderla sólo cuesta volver a leer). Y no se usa para decidir un acceso: el
navegador de archivos recuerda cómo se resuelven las raíces declaradas, pero
la ruta que pide quien navega se resuelve y se confina siempre en fresco.

Lo que se recuerda y se devuelve mutable va con `copia`: si quien llama
añade una clave a lo devuelto (`listar_sesiones` le pone `proyecto_id` a la
ficha), sin copia la estaría escribiendo en lo recordado para todos.

Un tope de entradas, y al llenarse se echa la que lleva más tiempo sin
usarse: el proceso de la web vive semanas, y un transcript por sesión de
trabajo son cientos de archivos al mes. `por_archivo` lleva **un almacén por
lector, cada uno con su tope** (C-0326): con uno solo para todos, quien
recorre más archivos que el tope —el consumo, con más de mil transcripts—
echaba en cada pasada justo lo que iba a pedir en la siguiente, y de paso lo
de los demás; fallaba todos los aciertos sin que se notara, porque el
resultado era el mismo. Quien sepa que va a recordar muchos pide su `tope`.
"""

from __future__ import annotations

import os
import threading
import time
from collections import OrderedDict
from collections.abc import Callable, Hashable
from pathlib import Path
from typing import Any, TypeVar

T = TypeVar("T")

TOPE = 2048

_cerrojo = threading.Lock()
# Lector → (ruta → (huella, lo leído)).
_por_archivo: dict[str, OrderedDict[str, tuple[tuple[int, int, int, int], Any]]] = {}
_por_tiempo: OrderedDict[Hashable, tuple[float, Any]] = OrderedDict()


def _nombre_de(leer: Callable) -> str:
    """La clave del lector: su módulo y su nombre.

    🔴 Una función de módulo, nunca una lambda ni una función anidada. Por la
    identidad del objeto, una lambda creada en cada llamada no acertaría
    nunca y llenaría el tope de basura; por el nombre, dos lambdas del mismo
    sitio se pisarían lo leído. Las dos cosas fallarían en silencio, así que se
    rechaza al primer uso."""
    nombre = getattr(leer, "__qualname__", "") or ""
    if not nombre or "<" in nombre:
        raise ValueError(
            f"recordar.por_archivo necesita una función de módulo, no «{nombre or leer!r}»"
        )
    return f"{leer.__module__}.{nombre}"


def _guardar(almacen: OrderedDict, clave: Hashable, valor: Any, tope: int) -> None:
    """Con `_cerrojo` tomado por quien llama."""
    almacen[clave] = valor
    almacen.move_to_end(clave)
    while len(almacen) > tope:
        almacen.popitem(last=False)


def por_archivo(ruta: str | Path, leer: Callable[[Path], T],
                copia: Callable[[T], T] | None = None, *, tope: int | None = None) -> T:
    """`leer(ruta)`, recordado mientras el archivo no cambie.

    Si el archivo no se puede mirar (no está, sin permiso), se lee tal cual y
    no se recuerda: qué significa «no está» lo decide quien lee. Si `leer`
    lanza, tampoco se recuerda nada y el error sube igual. `None` no se
    recuerda: quien lee suele tragarse un fallo de lectura y devolverlo, y un
    «no pude» recordado no se curaba hasta reiniciar el proceso.

    `tope` es cuántos archivos recuerda **este lector** (por omisión, `TOPE`).
    Quien recorre muchos en orden tiene que pedir uno mayor que su recorrido:
    con menos, cada pasada echa lo que la siguiente va a pedir y no acierta
    nunca. Lo que deja de pedirse (un archivo borrado) es lo primero en salir
    al llenarse; quien no quiera esperar a eso lo suelta con `quedarse_con`.
    """
    camino = Path(ruta)
    lector, clave = _nombre_de(leer), str(camino)
    try:
        st = os.stat(camino)
    except OSError:
        return leer(camino)
    # Con `ctime`: cambia también con un `chmod` y con una reescritura en el
    # sitio del mismo tamaño y la misma fecha, que la fecha sola no ve.
    huella = (st.st_mtime_ns, st.st_ctime_ns, st.st_size, st.st_ino)
    with _cerrojo:
        almacen = _por_archivo.setdefault(lector, OrderedDict())
        previa = almacen.get(clave)
        if previa is not None and previa[0] == huella:
            almacen.move_to_end(clave)
            valor = previa[1]
            acierto = True
        else:
            acierto = False
    if not acierto:
        # Se mira ANTES de leer: si el archivo crece mientras se lee, lo
        # guardado lleva la huella vieja y la siguiente lectura vuelve a leerlo.
        valor = leer(camino)
        if valor is not None:
            with _cerrojo:
                # Otra vez por el nombre: `olvidar` pudo vaciarlo mientras se leía.
                _guardar(_por_archivo.setdefault(lector, OrderedDict()), clave, (huella, valor),
                         TOPE if tope is None else tope)
    return copia(valor) if copia is not None and valor is not None else valor


def quedarse_con(leer: Callable, rutas) -> int:
    """Suelta de lo recordado por `leer` todo lo que no esté en `rutas`, y
    dice cuánto soltó.

    Para quien recorre una lista de archivos que mengua (el consumo: Claude
    Code poda sus transcripts): lo de un archivo borrado no vuelve a pedirse,
    y con un `tope` holgado no saldría nunca por viejo. Se llama con la lista
    ENTERA de la pasada, nunca con una a medias."""
    lector = _nombre_de(leer)
    vivas = {str(Path(ruta)) for ruta in rutas}
    with _cerrojo:
        almacen = _por_archivo.get(lector)
        sobran = [clave for clave in almacen or () if clave not in vivas]
        for clave in sobran:
            del almacen[clave]
    return len(sobran)


def por_tiempo(clave: Hashable, calcular: Callable[[], T], segundos: float) -> T:
    """`calcular()`, recordado `segundos` bajo `clave`.

    Lo devuelto se comparte entre quienes lo piden: sólo para valores que
    nadie modifica (un `Path`, una tupla). El instante se toma ANTES de
    calcular, para que el plazo nunca cuente de más."""
    ahora = time.monotonic()
    with _cerrojo:
        previa = _por_tiempo.get(clave)
        if previa is not None and ahora - previa[0] < segundos:
            _por_tiempo.move_to_end(clave)
            return previa[1]
    valor = calcular()
    with _cerrojo:
        _guardar(_por_tiempo, clave, (ahora, valor), TOPE)
    return valor


def ultimo(clave: Hashable, por_defecto: Any = None) -> Any:
    """Lo último que `por_tiempo` guardó bajo `clave`, aunque su plazo ya
    haya pasado; `por_defecto` si no hay nada (C-0435).

    Para quien, si calcular falla, prefiere lo último que salió bien a nada, y
    lo dice. Como `por_tiempo` no guarda cuando calcular lanza, esto es
    siempre la última vez que salió bien, de cuando sea. No lo renueva: la
    llamada siguiente a `por_tiempo` vuelve a calcular. Nunca para decidir un
    acceso, como todo lo de aquí."""
    with _cerrojo:
        previa = _por_tiempo.get(clave)
        if previa is None:
            return por_defecto
        # Mientras se use no es lo que lleva más tiempo sin usarse.
        _por_tiempo.move_to_end(clave)
        return previa[1]


def olvidar() -> None:
    """Todo fuera. Para las pruebas, que no pueden heredar lo de otra."""
    with _cerrojo:
        _por_archivo.clear()
        _por_tiempo.clear()
