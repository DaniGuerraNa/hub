"""El Puente KVM visto desde el hub: si contesta, y poco más (decisión 438).

El puente es un programa aparte —su repo, su servicio `puente-kvm`, su web
sólo en 127.0.0.1— que teclea en un Mac de otra persona a través de un JetKVM.
El hub no lo funde ni lo envuelve: **sólo apunta**. Pregunta si contesta, con
un GET a loopback que tarda como mucho `ESPERA_S`, y enseña el enlace para
abrirlo en una pestaña aparte.

🔴 Lo que esto no hace, y no debe hacer nunca:

- **Un POST al puente.** Dar el control a Claude, parar y aprobar un cambio
  son de la persona, en la pantalla del puente: el hub no tiene botón para
  nada de eso.
- **Leer su archivo de entorno**, donde vive la contraseña del JetKVM (regla
  dura 5). Ni para saber si está puesta.
- **Hacer de proxy** de su web o de su terminal: la puerta de `/acceso` no la
  cubre (regla dura 8), así que se abre en la PC donde corre y en ningún otro
  sitio. La dirección es literal, nunca sacada de la petición.
- **Dejar pasar lo que lee del Mac.** Su `/api/estado` trae la tarea, las
  lecturas y los cambios con sus descripciones, que es trabajo de otra
  persona. De aquí sólo salen las claves de `CLAVES`, y cada una de una lista
  cerrada o recortada.

La pregunta la hace `consulta_local`, el cliente común de los programas
aparte (decisión 461): un GET HTTP/1.0 por un socket propio, con un plazo
absoluto y un tope de bytes.
"""

from __future__ import annotations

import os
import re
from typing import Any

from . import consulta_local

PUERTO_POR_OMISION = 8794
#: Cuánto se espera como mucho a que conteste, en total.
ESPERA_S = 0.8
#: Lo más que se lee de su estado. Trae diez lecturas y diez cambios: sobra.
TOPE_BYTES = 256 * 1024

_ANFITRION = consulta_local.ANFITRION

#: Lo único que sale de aquí.
CLAVES = ("vivo", "aparato", "conectado", "control", "motivo", "version")

#: Con qué está conectado, por su `tipo`. Otro tipo no se nombra.
APARATOS = {"jetkvm": "JetKVM", "simulador": "Mac simulado (sin aparato)"}

#: Quién tiene el teclado del Mac, por su `modo`.
CONTROLES = {
    "libre": "La persona: Claude no puede tocar el Mac",
    "claude": "Claude, porque la persona se lo dio",
    "parado": "Nadie: alguien pulsó Parar",
}

#: Por qué no llega al aparato, para quien mira desde otro aparato. El detalle
#: —el fallo al conectar, que con un JetKVM puede llevar su dirección en la
#: red de casa— se queda en la PC donde corre (`para_fuera`).
SIN_APARATO = "no está conectado al aparato"
SIN_APARATO_DESDE_FUERA = "no está conectado al aparato; el detalle, en la PC donde corre"

_VERSION = re.compile(r"[0-9][0-9A-Za-z.+-]{0,31}")
MOTIVO_MAX = 160


def puerto() -> int:
    """`PUENTE_PUERTO` si es un puerto; si no, el de siempre."""
    try:
        n = int(os.environ.get("PUENTE_PUERTO") or PUERTO_POR_OMISION)
    except ValueError:
        return PUERTO_POR_OMISION
    return n if 0 < n < 65536 else PUERTO_POR_OMISION


def direccion() -> str:
    """Dónde se abre el puente, en la PC donde corre."""
    return f"http://{_ANFITRION}:{puerto()}"


def _sin_estado(motivo: str) -> dict[str, Any]:
    return {"vivo": False, "aparato": None, "conectado": None, "control": None, "motivo": motivo}


def _recortar(texto: object) -> str | None:
    return consulta_local.recortar(texto, MOTIVO_MAX)


def _filtrar(datos: dict) -> dict[str, Any]:
    """Del estado entero del puente, sólo lo de `CLAVES` y de listas cerradas."""
    disp = datos.get("dispositivo") if isinstance(datos.get("dispositivo"), dict) else {}
    ctl = datos.get("control") if isinstance(datos.get("control"), dict) else {}
    tipo, modo = disp.get("tipo"), ctl.get("modo")
    conectado = disp.get("conectado") if isinstance(disp.get("conectado"), bool) else None
    motivo = None
    if conectado is False:
        # Por qué no llega al aparato: el fallo al conectar y, si no lo hay, lo
        # que dice el aparato (con un JetKVM real, un «sin conectar» que no
        # explica nada). Es diagnóstico, no lo que se leyó del Mac.
        motivo = (_recortar(datos.get("error_conexion")) or _recortar(disp.get("motivo"))
                  or SIN_APARATO)
    salida: dict[str, Any] = {
        "vivo": True,
        "aparato": tipo if tipo in APARATOS else None,
        "conectado": conectado,
        "control": modo if modo in CONTROLES else None,
        "motivo": motivo,
    }
    version = datos.get("version")
    if isinstance(version, str) and _VERSION.fullmatch(version):
        salida["version"] = version
    return salida


def estado(espera: float = ESPERA_S) -> dict[str, Any]:
    """Cómo está el puente: `vivo`, `aparato`, `conectado`, `control` y
    `motivo` (y `version`, si el puente la da). Nunca lanza.

    `vivo` es que contestó con su estado. Si no, `motivo` dice por qué, sin
    la dirección: quien mira desde otro aparato no la necesita.
    """
    try:
        datos = consulta_local.pedir_json(puerto(), "/api/estado", espera, TOPE_BYTES)
    except consulta_local.NoContesta as exc:
        return _sin_estado(exc.motivo)
    if not isinstance(datos, dict):
        return _sin_estado("contesta algo que no es su estado")
    return _filtrar(datos)


def para_fuera(e: dict[str, Any]) -> dict[str, Any]:
    """El estado para quien mira desde otro aparato: sin el detalle de por qué
    no llega al aparato, que puede llevar su dirección en la red de casa."""
    if e.get("vivo") and e.get("conectado") is False:
        return {**e, "motivo": SIN_APARATO_DESDE_FUERA}
    return e
