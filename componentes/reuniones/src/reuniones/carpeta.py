"""Cómo es la carpeta de una reunión. Es el contrato entre quien la llena
mientras graba y el procesado (que la lee al acabar).

Hay dos escritores, y cada uno deja sus carpetas en su sitio:

- **El agente de Windows**, en `<raiz>/AAAAMMDD-HHMMSS/`.
- **El Puente KVM** (una reunión del Mac grabada por el JetKVM), en su propia
  carpeta de datos y con el id `AAAAMMDD-HHMMSS-kvm`: el sufijo evita que dos
  grabaciones del mismo segundo choquen y le dice al hub en qué carpeta mirar.
  Su `meta.json` lleva `origen: "jetkvm"`, y no hay `micro.wav`: el JetKVM no
  tiene micrófono, la voz de quien está en la reunión no pasa por él.

    <raiz>/<id>/
      meta.json          lo escribe quien graba: inicio, fin, monitor, proceso, micro;
                         desde el agente 0.3.0 también monitor_pedido, monitor_origen
                         («ventana», «heredado» o «elegido») y cambios_monitor
                         ([{segundo, monitor, origen}], desde el 0, si sigue la ventana).
                         `fin` se escribe lo último: es la señal de que está completa.
                         El puente pone además origen: "jetkvm" y, si la cerró al
                         arrancar tras una caída, cortada: "<por qué>"
      reunion.wav        audio SÓLO de la aplicación (Teams…), por proceso; en el
                         puente, lo que el Mac manda a la salida USB del JetKVM
      micro.wav          tu micrófono, aparte (no lo hay en las del puente)
                         (reunion.opus / micro.opus si se comprimió: comprimir.py)
      fotos/%06d.jpg     fotogramas que cambiaron; el número = segundos desde el
                         inicio, con seis cifras (000042.jpg)
      ── lo que deja el procesado ──
      transcripcion.json / .md
      resumen.json / .md
      procesado.json     estado por etapas y errores
      nombres.json       {"Persona 1": "Ana"}: el nombre de cada voz, si se pusieron (voces.py)
      ── lo que deja comprimir (a demanda) ──
      comprimiendo       marca vacía mientras se comprime (el hub no ofrece otra vez el botón)
      comprimido.json    antes/después en bytes y fecha, o {error}: si hay error, el WAV sigue ahí

`id` = AAAAMMDD-HHMMSS, con `-kvm` detrás si es del puente: ordena por fecha
sin leer nada (el sufijo va detrás, así que no cambia ese orden).
"""
import json
import os
import re
from pathlib import Path

ID = re.compile(r"^\d{8}-\d{6}(?:-kvm)?$")


def raiz() -> Path:
    return Path(os.environ.get("REUNIONES_RAIZ") or "/mnt/d/reuniones/grabaciones")


def de(id_: str) -> Path:
    if not ID.match(id_ or ""):
        raise ValueError("id de reunión no válido")
    return raiz() / id_


def leer(ruta: Path) -> dict | None:
    try:
        return json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def escribir(ruta: Path, datos) -> None:
    tmp = ruta.with_suffix(ruta.suffix + ".tmp")
    tmp.write_text(json.dumps(datos, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(ruta)


def hhmmss(s: float) -> str:
    s = int(s)
    return f"{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}"
