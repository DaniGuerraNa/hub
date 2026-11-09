"""El propio hub como fuente (definición 1.3): reuniones grabadas y notas de slots.

Va primero porque no pide nada: ni cuentas, ni llaves, ni salir de la máquina
para leer. Lo vivo —qué sesiones hay, qué proyectos— no se copia aquí: lo
consulta el modelo en el momento con las herramientas del hub
(`herramientas.py`), porque guardarlo sería guardar algo que caduca en 20 s.

Una reunión es **un evento**: título, resumen, decisiones, tareas y la
transcripción entera. Se mete cuando ya tiene resumen: antes, la transcripción
sola no dice quién dijo qué ni qué quedó.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3

from ... import api, config, db, reuniones
from ..piezas import Evento, Fuente

# Una reunión de dos horas son ~20 000 palabras; más que esto no ayuda a
# buscar y engorda la base.
TOPE_TRANSCRIPCION = 60_000


def _lista(valor) -> list:
    return valor if isinstance(valor, list) else []


def _texto_reunion(det: dict) -> str:
    res = det.get("resumen") or {}
    partes = [res.get("titulo") or "", res.get("resumen") or ""]
    if _lista(res.get("decisiones")):
        partes.append("Decisiones: " + "; ".join(map(str, res["decisiones"])))
    tareas = []
    for t in _lista(res.get("tareas")):
        if isinstance(t, dict):
            tareas.append(f"{t.get('quien') or '?'}: {t.get('que') or ''}"
                          + (f" ({t['cuando']})" if t.get("cuando") else ""))
    if tareas:
        partes.append("Tareas: " + "; ".join(tareas))
    if _lista(res.get("para_mi")):
        partes.append("Para mí: " + "; ".join(map(str, res["para_mi"])))
    if _lista(res.get("preguntas_abiertas")):
        partes.append("Preguntas abiertas: " + "; ".join(map(str, res["preguntas_abiertas"])))
    frases = [f"{s.get('quien') or ''}: {s.get('texto') or ''}" for s in _lista(det.get("transcripcion"))
              if isinstance(s, dict)]
    if frases:
        partes.append("Transcripción:\n" + "\n".join(frases)[:TOPE_TRANSCRIPCION])
    return "\n\n".join(p for p in partes if p.strip())


def _fecha_de_id(id_: str) -> str:
    # Los ids de Reuniones son `AAAAMMDD-HHMMSS`, en hora local de quien graba;
    # en la memoria todo va en UTC para poder ordenar fuentes distintas juntas.
    from ..tiempo import a_utc
    return a_utc(f"{id_[0:4]}-{id_[4:6]}-{id_[6:8]}T{id_[9:11]}:{id_[11:13]}:{id_[13:15]}")


class FuenteHub(Fuente):
    id = "hub"
    nombre = "El hub"
    descripcion = "Reuniones grabadas con su resumen y las notas de los slots."
    intervalo = 120

    def conversaciones(self) -> list[str]:
        return ["reuniones", "slots"]

    def leer(self, cursor: str, ajustes: dict) -> tuple[list[Evento], str]:
        """El cursor guarda lo justo para no releer, acotado: las reuniones
        vistas de entre las que aún lista Reuniones, y la huella de la última
        nota de cada slot. Antes era la lista de TODO lo visto (cada versión de
        cada nota) y crecía sin fin; repetir algo no duplica, porque la memoria
        ignora un evento que ya tiene (`UNIQUE (fuente, id_externo)`)."""
        previo = json.loads(cursor) if cursor else {}
        if isinstance(previo, list):  # el formato viejo: una lista de claves
            previo = {"reuniones": [c.split(":", 1)[1] for c in previo if c.startswith("reunion:")],
                      "slots": {}}
        vistas = set(previo.get("reuniones") or [])
        huellas = dict(previo.get("slots") or {})
        eventos: list[Evento] = []
        eventos += self._reuniones(vistas)
        eventos += self._slots(huellas)
        return eventos, json.dumps({"reuniones": sorted(vistas), "slots": huellas})

    def _reuniones(self, vistas: set) -> list[Evento]:
        out = []
        try:
            lista = reuniones.lista(200)
        except (OSError, ValueError):
            return []
        # Sólo se recuerdan las que siguen en la lista: las que salen de ella ya
        # no pueden volver a leerse, y recordarlas era lo que hacía crecer el cursor.
        vistas &= {r["id"] for r in lista}
        for r in lista:
            if r["id"] in vistas or not r.get("terminada"):
                continue
            try:
                det = reuniones.detalle(r["id"])
            except (OSError, ValueError):
                continue
            if not det.get("resumen"):
                continue
            out.append(Evento(fuente=self.id, id_externo=f"reunion:{r['id']}", fecha=_fecha_de_id(r["id"]),
                              conversacion="reuniones", autor="Reunión",
                              texto=_texto_reunion(det), enlace=f"/reuniones/{r['id']}"))
            vistas.add(r["id"])
        return out

    def _slots(self, huellas: dict) -> list[Evento]:
        """Cada versión de la nota de un slot es un evento: si la nota cambia,
        la nueva se busca igual que la vieja, y la vieja dice qué se pensaba."""
        if not config.DB_PATH.is_file():
            return []
        try:
            con = db.conectar()
        except db.BaseIlegible:
            return []
        try:
            filas = api.notas_de_slots(con)
        except sqlite3.Error:
            return []
        finally:
            con.close()
        out = []
        for f in filas:
            huella = hashlib.sha1(f["nota"].encode()).hexdigest()[:12]
            if huellas.get(str(f["id"])) == huella:
                continue
            out.append(Evento(fuente=self.id, id_externo=f"slot:{f['id']}:{huella}", fecha=f["fecha"] or "",
                              conversacion="slots", autor=f"{f['proyecto_id']} / {f['nombre']}",
                              texto=f"Nota del slot «{f['nombre']}» del proyecto {f['proyecto_id']}: {f['nota']}",
                              enlace="/trabajo"))
            huellas[str(f["id"])] = huella
        # Un slot borrado deja de contar.
        for viejo in set(huellas) - {str(f["id"]) for f in filas}:
            del huellas[viejo]
        return out


FUENTE = FuenteHub()
