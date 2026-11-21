"""Las nueve secciones del hub y qué pantallas cuelgan de cada una (C-0169).

El raíl de siempre enseña veintiún destinos en grupos que se despliegan
(decisión 297). La interfaz nueva los ordena en **nueve secciones**: el raíl
lleva a cada una, y dentro una tira enseña sus pantallas. Ninguna pantalla
cambia de dirección ni desaparece: sólo cambia desde dónde se llega.

Aquí vive ese reparto y nada más: no lee la base ni pinta. `con_cifras`
recoloca en las secciones las cifras que `api.rail` ya daba —ni una señal
nueva: una cifra que no existía en el raíl de siempre no nace aquí (el «te
esperan N» roza la decisión 379)—, y una sección cerrada sigue enseñando lo
urgente de dentro, como los grupos de la 297.

Un test exige que toda pantalla del raíl de siempre tenga sección: lo que se
añada allí y no aquí dejaría una pantalla sin camino en la interfaz nueva.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any
from urllib.parse import parse_qs


def _p(ruta: str, clave: str, nombre: str, icono: str, **mas: Any) -> dict:
    return {"ruta": ruta, "clave": clave, "nombre": nombre, "icono": icono, **mas}


#: Cada sección: `clave`, `nombre`, `icono` (de `_ui.html`) y sus `pantallas`
#: —la primera es a donde lleva la sección—. La `clave` de una pantalla es la
#: `seccion` que su vista pasa a la plantilla, que es como se sabe dónde estás.
#: `corto` es el nombre en la barra del teléfono, donde no cabe el largo.
#: `tira: False`, donde la pantalla ya trae su propia barra con todo lo suyo.
#: `del_secretario`: el nombre es el que le puso el dueño, no uno escrito aquí.
#: `opcional`: la clave de una herramienta de `opcionales.OPCIONALES`; la
#: pantalla sólo sale si está encendida (decisión 438).
SECCIONES: tuple[dict, ...] = (
    {"clave": "hoy", "nombre": "Hoy", "icono": "casa", "pantallas": (
        # Sigue siendo Panorama hasta que «Hoy» tenga su fase.
        _p("/", "panorama", "Panorama", "casa"),
    )},
    {"clave": "secretario", "nombre": "Secretario", "icono": "secretario",
     "del_secretario": True, "tira": False, "pantallas": (
        _p("/secretario", "secretario", "Secretario", "secretario", del_secretario=True),
        _p("/secretario/monitor", "secretario_monitor", "Modo monitor", "equipo"),
    )},
    {"clave": "trabajo", "nombre": "Trabajo", "icono": "terminal", "pantallas": (
        _p("/trabajo", "trabajo", "Trabajo", "terminal"),
    )},
    {"clave": "proyectos", "nombre": "Proyectos", "icono": "carpeta", "pantallas": (
        _p("/inventario", "inventario", "Inventario", "lineas"),
        _p("/archivos", "archivos", "Archivos", "carpeta"),
        _p("/contexto", "contexto", "Contexto", "documento"),
    )},
    {"clave": "ideas", "nombre": "Ideas y tareas", "corto": "Ideas", "icono": "lapiz", "pantallas": (
        _p("/tablero", "tablero", "Tablero", "lapiz"),
        _p("/orquestador", "orquestador", "Orquestador", "agente"),
    )},
    {"clave": "salud", "nombre": "Salud", "icono": "escudo", "pantallas": (
        _p("/maquina", "maquina", "Máquina", "equipo"),
        _p("/respaldo", "respaldo", "Respaldo", "escudo"),
        _p("/servicios", "servicios", "Servicios", "pilas"),
        _p("/consumo", "consumo", "Consumo", "lineas"),
    )},
    {"clave": "herramientas", "nombre": "Herramientas", "icono": "rejilla", "pantallas": (
        _p("/reuniones", "reuniones", "Reuniones", "reunion"),
        _p("/navegante", "navegante", "Navegante", "navegador"),
        _p("/intercambio", "intercambio", "Intercambio", "intercambio"),
        _p("/talleres", "talleres", "Talleres", "rejilla"),
        # Herramienta opcional (438): sólo sale si está encendida.
        _p("/puente", "puente", "Puente KVM", "teclado", opcional="puente-kvm"),
    )},
    {"clave": "fuera", "nombre": "Fuera", "icono": "conversacion", "pantallas": (
        _p("/canal", "canal", "Canal", "conversacion"),
        _p("/encargos", "encargos", "Encargos", "bandeja"),
    )},
    {"clave": "ajustes", "nombre": "Ajustes", "icono": "ajustes", "pantallas": (
        _p("/conexiones", "conexiones", "Conexiones", "enlace"),
        _p("/acceso", "acceso", "Acceso", "llave"),
        _p("/actualizaciones", "actualizaciones", "Actualizaciones", "actualizar"),
        _p("/guia", "guia", "Guía", "ok"),
        # Tampoco está en el raíl de siempre: allí se llega desde
        # Actualizaciones, la Guía y el Puente KVM (C-0468).
        _p("/incidencia", "incidencia", "Contar un fallo o una idea", "enviar"),
        _p("/orquestador/permisos", "orquestador_permisos", "Permisos del orquestador", "escudo"),
        # No está en el raíl de siempre: allí se llega por el mapa de la guía.
        _p("/voz/banco", "banco", "Banco de dictado", "microfono"),
        # Las pestañas de ajuste del secretario se pintan en su pantalla, pero
        # son de Ajustes: estando en ellas se marca esta sección y sale su
        # tira, que es por donde se vuelve (`_del_secretario`).
        _p("/secretario?p=avisos", "secretario_ajustes", "Secretario", "secretario",
           del_secretario=True),
    )},
)

#: La barra fija del teléfono, en su orden: cuatro secciones y «Más», que
#: lleva a las otras cinco. El pulgar llega a lo de cada momento sin abrir nada.
BARRA: tuple[str, ...] = ("secretario", "trabajo", "hoy", "ideas")

#: Pantallas de detalle que cuelgan de una sección distinta de la que dice su
#: `seccion`: la ficha de un proyecto se pinta con la de Panorama, que es de
#: donde se llega hoy, pero es de Proyectos.
_PREFIJOS: tuple[tuple[str, str], ...] = (("/proyecto/", "proyectos"),)

#: De qué clave de `api.rail` sale la cifra de cada pantalla. `urge` pide algo
#: (rojo en el raíl de siempre); `cuenta` sólo informa.
_CIFRAS: dict[str, tuple[str, str]] = {
    "navegante": ("urge", "navegante_pendientes"),
    "respaldo": ("urge", "sin_respaldo"),
    "secretario": ("urge", "secretario_pendientes"),
    "servicios": ("cuenta", "servicios"),
    "trabajo": ("cuenta", "paneles"),
}


#: Las pestañas de `/secretario` que son suyas. Cualquier otra (`?p=avisos`,
#: `fuentes`, `confianza`…) es de ajuste: la misma cuenta que hace su vista.
_PESTANAS_DEL_SECRETARIO = ("conversacion", "pendientes", "memoria")


def _del_secretario(camino: str, consulta: str) -> bool:
    """¿Es una pestaña de ajuste del secretario? Va en su pantalla, pero es de Ajustes."""
    if camino != "/secretario":
        return False
    pestana = (parse_qs(consulta).get("p") or [""])[0]
    return bool(pestana) and pestana not in _PESTANAS_DEL_SECRETARIO


def _situar(clave: str | None, ruta: str | None) -> tuple[str | None, str | None]:
    """La sección y la pantalla de donde se está: `(seccion, pantalla)`.

    Manda la dirección —con su consulta, si la trae—: la exacta primero
    (`/orquestador/permisos` es de Ajustes aunque su vista diga «orquestador»),
    luego las de detalle (`/proyecto/…`, de Proyectos y sin pantalla en la
    tira). Si la dirección no dice nada, vale la `clave` de la vista.
    """
    por_clave = {p["clave"]: s["clave"] for s in SECCIONES for p in s["pantallas"]}
    if ruta:
        camino, _, consulta = ruta.partition("?")
        if _del_secretario(camino, consulta):
            return por_clave["secretario_ajustes"], "secretario_ajustes"
        for s in SECCIONES:
            for p in s["pantallas"]:
                if p["ruta"] == camino:
                    return s["clave"], p["clave"]
        for prefijo, seccion in _PREFIJOS:
            if camino.startswith(prefijo):
                return seccion, None
    if clave and clave in por_clave:
        return por_clave[clave], clave
    return None, None


def de_pantalla(clave: str | None, ruta: str | None = None) -> str | None:
    """La sección de una pantalla, por su `clave` (la `seccion` de su vista)
    y, si se da, su dirección. Una sin sección —el «no existe»— devuelve `None`."""
    return _situar(clave, ruta)[0]


def pantalla_actual(clave: str | None, ruta: str | None = None) -> str | None:
    """La `clave` de la pantalla en la que se está, para marcarla en la tira."""
    return _situar(clave, ruta)[1]


def _cifras_de(clave: str, rail: dict) -> dict[str, int]:
    cifras = {"urge": 0, "cuenta": 0}
    if clave in _CIFRAS:
        tipo, origen = _CIFRAS[clave]
        cifras[tipo] = int(rail.get(origen) or 0)
    elif clave == "actualizaciones":
        v = rail.get("version") or {}
        cifras["urge"] = 1 if (v.get("hay_nueva") or v.get("falta_terminar")) else 0
    return cifras


def visibles(encendidas: Iterable[str] = ()) -> list[dict]:
    """Las secciones con sólo las pantallas que se enseñan: las de una
    herramienta opcional, sólo si está en `encendidas` (decisión 438).

    🔴 Es la única forma de recorrer las pantallas para enseñarlas o
    buscarlas —el raíl nuevo (`con_cifras`), «dónde está» del secretario—:
    apagada, una herramienta no sale en ningún menú ni en ninguna búsqueda.
    Recorrer `SECCIONES` a pelo fuera de aquí es el camino que la deja
    asomar (`tests/test_puertas.py`). Saber en qué sección cae una dirección
    (`de_pantalla`) no enseña nada y sí las mira todas."""
    encendidas = set(encendidas)
    return [{**s, "pantallas": tuple(p for p in s["pantallas"]
                                      if not p.get("opcional") or p["opcional"] in encendidas)}
            for s in SECCIONES]


def con_cifras(rail: dict) -> list[dict]:
    """Las secciones listas para pintar, con las cifras que `rail` ya trae.

    Cada pantalla lleva su `urge` y su `cuenta`; la sección, la suma de lo que
    urge dentro (decisión 297: un aviso no puede quedar detrás de un pliegue).
    Una sección de una sola pantalla enseña también su `cuenta` —las sesiones
    abiertas en Trabajo—; en las demás, la cuenta se queda en la tira. Una
    herramienta opcional apagada no sale (`visibles`, 438).
    """
    nombre_secretario = rail.get("secretario_nombre") or "Secretario"
    secciones = []
    for s in visibles(rail.get("opcionales") or ()):
        pantallas = [
            {**p, **_cifras_de(p["clave"], rail),
             "nombre": nombre_secretario if p.get("del_secretario") else p["nombre"]}
            for p in s["pantallas"]]
        nombre = nombre_secretario if s.get("del_secretario") else s["nombre"]
        secciones.append({
            "clave": s["clave"], "nombre": nombre, "icono": s["icono"],
            "corto": nombre if s.get("del_secretario") else s.get("corto", nombre),
            "ruta": pantallas[0]["ruta"],
            "tira": s.get("tira", True) and len(pantallas) > 1,
            "en_barra": BARRA.index(s["clave"]) + 1 if s["clave"] in BARRA else 0,
            "urge": sum(p["urge"] for p in pantallas),
            "cuenta": pantallas[0]["cuenta"] if len(pantallas) == 1 else 0,
            "pantallas": pantallas,
        })
    return secciones
