"""La cola de avisos al dueño que manda `hub-canal` por Telegram (decisión 341).

Avisar al dueño tiene dos transportes y cada llave vive en un proceso: el
token del bot sólo lo abre `hub-canal` (regla dura 22) y la clave de Web Push
sólo `hub-secretario` (311). Por eso, entre procesos, la cadena es una cola en
disco que lee quien tiene la llave, nunca una llave compartida. Ésta es la de
Telegram: un archivo por aviso, que el relé manda y borra sin pisarse con
quien escribe.

**Qué texto lleva lo decide quien escribe**, no la cola: el orquestador sólo
el id de la tarea y qué pasó (regla 22); el secretario, el contenido, porque
así lo decidió el dueño (302).

La carpeta es la de siempre, dentro de la del orquestador, para que lo que
haya en cola al actualizar siga saliendo.

🔴 **Hay un escritor fuera de este repo**: el guardián del navegante
(`navegador-lab/navegador/guardian.py`) deja timbres con
`pantalla: "Navegante"`, escritos a mano y sin `.tmp`. El formato de `leer`
es por tanto un contrato con él: `texto` obligatorio, `pantalla` y `titulo`
opcionales. Cambiarlo es cambiar los dos. Hacerlo atómico allí es de ese
proyecto (regla dura 16); aquí, un ilegible recién aparecido espera a la
vuelta siguiente en vez de borrarse (`reciente`, C-0062).
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from . import config

#: Lo que se da por pantalla a un timbre que no la dice: los de versiones
#: anteriores, que sólo escribía el orquestador.
PANTALLA_POR_OMISION = "Orquestador"


def carpeta() -> Path:
    return config.HUB_HOME / "orquestador" / "timbres"


def tocar(texto: str, *, pantalla: str = PANTALLA_POR_OMISION, titulo: str | None = None) -> Path:
    """Deja un aviso en la cola. La única que escribe en ella (`test_puertas`).

    🔴 Atómico: se escribe en `.tmp` y se renombra. El relé lee los `*.json`, y
    uno a medio escribir lo daría por ilegible y lo borraría: el aviso se
    perdería sin que nadie lo supiera.
    """
    d = carpeta()
    d.mkdir(parents=True, exist_ok=True)
    datos = {"texto": texto, "cuando": datetime.now(timezone.utc).isoformat(timespec="seconds"),
             "pantalla": pantalla}
    if titulo:
        datos["titulo"] = titulo
    destino = d / f"{time.time_ns()}.json"
    tmp = destino.with_suffix(".tmp")
    tmp.write_text(json.dumps(datos, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, destino)
    return destino


def pendientes() -> list[Path]:
    d = carpeta()
    return sorted(d.glob("*.json")) if d.is_dir() else []


#: Cuánto se espera a un timbre ilegible antes de darlo por roto. Un archivo
#: pequeño se escribe en milisegundos; esto sólo cubre la vuelta del relé.
ESPERA_ILEGIBLE_S = 10


def reciente(ruta: Path, ahora: float | None = None) -> bool:
    """Si un timbre que no se pudo leer acaba de aparecer: puede estar a medio
    escribir por el guardián del navegante, que no usa `.tmp` (C-0062). Ése
    se deja para la vuelta siguiente; borrarlo perdería el aviso."""
    try:
        edad = (time.time() if ahora is None else ahora) - ruta.stat().st_mtime
    except OSError:
        return False
    return edad < ESPERA_ILEGIBLE_S


def leer(ruta: Path) -> dict:
    """`{texto, cuando, pantalla, titulo}`. Lanza `OSError`, `ValueError` o
    `KeyError` si el archivo no es un timbre."""
    datos = json.loads(ruta.read_text(encoding="utf-8"))
    # 🔴 Un JSON válido que no es un objeto (`[1]`, `"x"`) daba `TypeError`,
    # que el relé no atrapaba: el archivo no se borraba y `hub-canal` se
    # quedaba sordo en cada vuelta sin que nadie lo notara (regla dura 2).
    if not isinstance(datos, dict):
        raise ValueError("no es un timbre: el JSON no es un objeto")
    return {"texto": datos["texto"], "cuando": datos.get("cuando"),
            "pantalla": str(datos.get("pantalla") or PANTALLA_POR_OMISION)[:30],
            "titulo": str(datos.get("titulo") or "")[:60]}
