"""Los recordatorios: lo que el dueño quedó en hacer, a su hora (definición 4.3).

🔴 **Una clase de aviso nueva** (regla dura 3, decisión 302). La lista de avisos
es cerrada porque «llevas cinco días sin tocar esto» es el hub gestionando al
dueño. Esto es lo contrario: cada recordatorio lo pidió él —o salió de algo que
él dijo que iba a hacer— y lleva la hora que él dio. El secretario no se
inventa plazos: un compromiso sin `recordar_en` no avisa nunca.
"""

from __future__ import annotations

import sqlite3

from . import avisos, memoria
from .tiempo import a_local


def revisar(con: sqlite3.Connection, momento: str | None = None) -> int:
    """Manda los que ya tocan. Devuelve cuántos salieron.

    Si no hay por dónde mandarlos, **no se marcan**: se reintentan en la
    vuelta siguiente, y la pantalla dice arriba que no están saliendo. Se
    apunta una vez por motivo, no en cada vuelta de 30 segundos.
    """
    salidos = 0
    for c in memoria.por_recordar(con, momento):
        quien = "" if c["quien"] in ("yo", "Yo", "") else f" (te lo pidió {c['quien']})"
        vence = f" — vence {a_local(c['vence'])}" if c.get("vence") and c["vence"] != c["recordar_en"] else ""
        try:
            canal = avisos.mandar(f"{c['que']}{quien}{vence}", titulo="⏰ Recordatorio",
                                  enlace="/secretario?p=pendientes")
        except (avisos.SinCanal, LookupError) as exc:
            if memoria.leer(con, "avisos_error") != str(exc):
                memoria.poner(con, "avisos_error", str(exc))
                memoria.apuntar(con, "recordatorio", resultado=f"no salió: {exc}", ok=False)
            return salidos
        memoria.poner(con, "avisos_error", None)
        memoria.marcar_recordado(con, c["id"])
        memoria.apuntar(con, "recordatorio", nivel="auto", params={"compromiso": c["id"]},
                        resultado=f"aviso enviado por {canal}")
        salidos += 1
    return salidos
