"""Los talleres (C-0220, decisión 391): cada sesión con agente es un taller.

La página (`/talleres`) pinta cada panel donde corre Claude Code o Codex como
una casa de muñecas de dos plantas: la rana herrera es la sesión, junto al
yunque de la herrería, y sus subagentes vivos entran por la puerta y van a la
estación de su oficio. Este módulo es la tabla de esa escena: dónde está cada
estación en el fondo, qué rol va a cuál y con qué rana se pinta. Los datos
(qué sesiones hay y qué subagentes tienen) los da `api.talleres`.

Lista cerrada a propósito, como los puestos del monitor (389): cada estación
existe porque algún rol lleva a ella, y cada rol de `personaje.ROLES` que puede
ser un subagente tiene la suya. Lo comprueba `tests/test_talleres.py`.

Las coordenadas van en % del escenario (16:9) y son los PIES de quien está
ahí. Se midieron con una rejilla sobre `static/talleres/fondo.webp`, que es una
imagen 3:2: el escenario enseña de su 11 % a su 95,4 % de alto
(`posicion`), así que `y_escena = (y_imagen − 11) / 0,844`.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

#: Dónde viven las imágenes (las monta `scripts/talleres.py`).
CARPETA = Path(__file__).parent / "static" / "talleres"
URL = "/static/talleres/"

#: La rana de la sesión: la herrera, en el yunque de la herrería.
SESION = "rana-herrera"

#: Los roles que no llegan como subagentes de una sesión: `obrero` ES la
#: sesión, y `experto` es el modelo mayor del secretario (358); `rol_de` no
#: devuelve ninguno de los dos para un `subagent_type`.
NO_SON_SUBAGENTES = frozenset({"obrero", "experto"})

#: rol → estación. «otro» es un tipo que no se conoce: va a la entrada y se
#: pinta neutro, con su inicial (nunca con una skin que no le toca, 358).
ESTACION_DE_ROL: dict[str, str] = {
    "arquitecto": "mapa",
    "planificador": "chimenea",
    "explorador": "escritorio",
    "resumidor": "escritorio",
    "investigador": "alquimia",
    "disenador": "caballete",
    "revisor": "entrada",
    "ayudante": "entrada",
    "orquestador": "entrada",
    "otro": "entrada",
}

#: rol → rana (`static/talleres/ranas/<id>.webp`). «otro» no tiene: neutro.
FIGURA_DE_ROL: dict[str, str | None] = {
    "arquitecto": "rana-cartografa",
    "planificador": "rana-estratega",
    "explorador": "rana-exploradora",
    "resumidor": "rana-cronista",
    "investigador": "rana-alquimista",
    "disenador": "rana-bardo",
    "revisor": "rana-guardiana",
    "ayudante": "rana-escudero",
    "orquestador": "rana-capitana",
    "otro": None,
}

#: rol → cómo se le llama en la lista de su taller.
NOMBRE_DE_ROL: dict[str, str] = {
    "arquitecto": "Cartógrafa", "planificador": "Estratega", "explorador": "Exploradora",
    "resumidor": "Cronista", "investigador": "Alquimista", "disenador": "Bardo",
    "revisor": "Guardiana", "ayudante": "Escudero", "orquestador": "Capitana", "otro": "Subagente",
}

#: rol → su balanceo mientras trabaja, si no tiene cuadros (`talleres.css`,
#: `data-oficio`). Quien tiene cuadros (`cuadros()`) los usa en su lugar.
OFICIO_DE_ROL: dict[str, str] = {
    "arquitecto": "mapa", "planificador": "plan", "explorador": "inspeccion", "resumidor": "leer",
    "investigador": "plan", "disenador": "plan", "revisor": "inspeccion", "ayudante": "plan",
    "orquestador": "plan", "otro": "plan",
}

#: Las ranas que se pintan: ni una más en `static/talleres/ranas/` (un test).
RANAS = frozenset({SESION, *(f for f in FIGURA_DE_ROL.values() if f)})

#: El fondo y sus sitios fijos. `maestro.yunque` es el yunque DEL FONDO: la
#: herrera no lleva el suyo (se le quitó de los cuadros) y la página la coloca
#: para que su golpe caiga encima (decisión 391).
FONDO: dict[str, Any] = {
    "img": URL + "fondo.webp",
    "posicion": "center 70.5%",
    # Casa de muñecas: no hay profundidad, todas del mismo tamaño.
    "escala": 1.2,
    "puerta": {"x": 14.5, "y": 85},
    "luz": {"left": 10.5, "top": 56.5, "width": 7.5, "height": 27.5},
    "maestro": {"x": 58, "y": 86.5, "yunque": {"x": 65.5, "arriba": 80, "base": 86.5}},
    "entrega": {"x": 54, "y": 92},
}

_SUBIR = [[6, 96], [9, 39.5]]  # de la puerta al pie de la escalera y arriba

#: estación → sitio. `mira`: hacia dónde mira quien trabaja (1, derecha).
#: `huecos`: dónde se ponen las que llegan (el primero, el del sitio). `via`:
#: por dónde se llega desde la puerta; las de arriba suben la escalera.
ESTACIONES: dict[str, dict[str, Any]] = {
    "entrada": {"x": 26, "y": 92.5, "mira": -1, "huecos": [[0, 0], [7, 0.5], [-4, 2], [10, 2]]},
    "alquimia": {"x": 79, "y": 92.5, "mira": 1,
                 "huecos": [[0, 0], [8, 0.3], [15, 0], [4, -2.5], [11.5, -2.5]]},
    "escritorio": {"x": 12.5, "y": 43.5, "mira": -1, "huecos": [[0, 0], [6, 0.4], [3, -1.6]], "via": _SUBIR},
    "mapa": {"x": 26, "y": 43.5, "mira": -1,
             "huecos": [[0, 0], [-6.5, 0.4], [6.5, 0.4], [-3, -1.6], [3.5, -1.6]], "via": _SUBIR},
    "caballete": {"x": 57, "y": 43.5, "mira": 1, "huecos": [[0, 0], [-8, 0.4], [-4, -1.6]],
                  "via": [*_SUBIR, [36, 43]]},
    "chimenea": {"x": 85, "y": 43.5, "mira": 1, "huecos": [[0, 0], [-7, 0.4], [6, 0.4]],
                 "via": [*_SUBIR, [36, 43], [70, 43]]},
}


def estacion_de(rol: str) -> str:
    """La estación de un rol; lo que no está en la tabla, a la entrada."""
    return ESTACION_DE_ROL.get(rol, "entrada")


@lru_cache(maxsize=1)
def cuadros() -> dict[str, Any]:
    """Los cuadros de trabajo de cada rana y dónde va su capa: lo deja
    `scripts/talleres.py` junto a las imágenes. Sin el archivo, ninguno (las
    ranas trabajan con su balanceo)."""
    try:
        datos = json.loads((CARPETA / "cuadros.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {k: v for k, v in datos.items() if k in RANAS}


def escena() -> dict[str, Any]:
    """La tabla que aplica `static/talleres.js`, tal cual: así el JS no lleva
    una segunda copia que se quede vieja (como `personaje.escenario`, 389)."""
    return {"fondo": FONDO, "estaciones": ESTACIONES, "figuras": FIGURA_DE_ROL,
            "nombres": NOMBRE_DE_ROL, "oficios": OFICIO_DE_ROL,
            "sesion": SESION, "url": URL, "cuadros": cuadros()}
