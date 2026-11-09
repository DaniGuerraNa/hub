"""Resumir una sesión de trabajo larga (C-0163): «¿qué se hizo en esas 8 horas?».

No va dentro del turno: leer horas de conversación tarda más de lo que el
dueño espera una respuesta, y `pedir_modelo_mayor` rehace el turno, no lee.
La conversación lo **encarga** (`encargar`) y el servicio lo hace en su ciclo
lento (`atender`), sobre `transcripts.esqueleto` —todo el texto, las
herramientas en una línea—, y deja el resumen en el mismo hilo.
"""

from __future__ import annotations

import sqlite3

from .. import transcripts
from . import conversacion, enrutador, memoria, motor

CLAVE = "resumenes_pendientes"
#: El que se está leyendo ahora, con su hora: ya salió de la cola y sigue
#: siendo algo que delegó (C-0166). Si el servicio muere a mitad se queda
#: escrito; quien lo lee lo da por muerto pasado `motor.TOPE_SEGUNDOS`.
EN_CURSO = "resumen_en_curso"
#: Lo que cabe de una sesión: el final manda (es donde queda cómo acabó).
TOPE_CARACTERES = 300_000


def encargar(con: sqlite3.Connection, sesion: str, hilo: int | None) -> dict:
    ruta = transcripts.ruta_de_sesion(sesion)
    if not ruta:
        return {"error": f"no encuentro la sesión «{sesion}» (míralas con `sesiones`)"}
    # La cola común de lo que se hace aparte (`memoria.encolar`, 385): la tocan
    # dos procesos, y leer y escribir van en la misma transacción.
    if not memoria.encolar(con, CLAVE, {"sesion": sesion, "hilo": hilo}, igual=lambda x: x.get("sesion")):
        return {"encargado": True, "nota": "Ya la estaba leyendo; el resumen sale en este chat."}
    return {"encargado": True, "nota": "La estoy leyendo aparte; el resumen saldrá en este chat en unos minutos. "
                                       "Díselo así."}


def _texto(ruta) -> str:
    lineas = []
    for m in transcripts.esqueleto(ruta)["mensajes"]:
        quien = "Él" if m["rol"] == "user" else "Claude"
        extra = f" [{'; '.join(m['herramientas'])}]" if m.get("herramientas") else ""
        lineas.append(f"{(m.get('ts') or '')[:16]} {quien}: {m.get('texto') or ''}{extra}")
    return "\n".join(lineas)[-TOPE_CARACTERES:]


def atender(con: sqlite3.Connection) -> int:
    """Los resúmenes encargados, de uno en uno. Uno que falla se dice en su hilo."""
    pedido = memoria.sacar(con, CLAVE)
    if pedido is None:
        return 0
    memoria.poner(con, EN_CURSO, {"sesion": pedido["sesion"], "desde": memoria.ahora()})
    try:
        ruta = transcripts.ruta_de_sesion(pedido["sesion"])
        if not ruta:
            raise motor.MotorCaido("la sesión ya no está")
        r = motor.llamar(
            "Esta es una sesión de trabajo con Claude Code, condensada (texto y herramientas usadas). Cuéntale "
            "a quien la lanzó qué se hizo: lo que se consiguió, lo que se decidió, lo que quedó a medias o "
            "falló, y en qué punto acabó. Breve y concreto, en español, sin inventar nada que no esté.\n\n"
            + _texto(ruta),
            modelo=enrutador.modelo("conversacion"), esfuerzo="low", herramientas=False, nueva=True,
            persistir=False, trabajo="resumen_sesion")
        texto = f"Resumen de la sesión {pedido['sesion'][:8]}:\n\n{r.texto}"
    except Exception as exc:  # noqa: BLE001 — ya se le dijo que llegaría: si falla, se le dice
        texto = f"No pude resumir la sesión {pedido['sesion'][:8]}: {exc}"
    finally:
        memoria.quitar(con, EN_CURSO)
    # Sin hilo (lo encargó algo que no es la conversación) va al abierto o a
    # uno nuevo: antes se perdía sin decirlo.
    conversacion.decir(con, int(pedido["hilo"]) if pedido.get("hilo") else None, texto)
    memoria.apuntar(con, "resumen_sesion", nivel="auto", params={"sesion": pedido["sesion"]}, resultado=texto[:200])
    return 1
