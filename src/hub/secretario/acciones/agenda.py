"""Poner algo en el calendario del dueño (definición 4.2), sea cual sea (decisión 306).

En `ask` al empezar: un evento en el calendario lo ve quien comparta ese
calendario, y el dueño todavía no ha visto cómo acierta con fechas dichas en
lenguaje normal («el jueves a primera hora»). Lo sube él cuando se fíe (8.3).
"""

from __future__ import annotations

from .. import agenda
from ..piezas import Accion


class Agendar(Accion):
    id = "agendar"
    gesto = "agenda"
    nombre = "Poner en tu calendario"
    resumen = "Crea un evento en tu calendario."
    descripcion = ("Crea un evento en el calendario del dueño. `inicio` en hora local: 'AAAA-MM-DD' para "
                   "todo el día o 'AAAA-MM-DDTHH:MM'. `fin` opcional (por omisión, 30 minutos).")
    parametros = {"type": "object", "properties": {
        "titulo": {"type": "string"}, "inicio": {"type": "string"}, "fin": {"type": "string"},
        "descripcion": {"type": "string"}, "minutos_aviso": {"type": "integer"}},
        "required": ["titulo", "inicio"]}
    riesgo = "reversible"
    nivel_inicial = "ask"

    def ejecutar(self, con, params):
        e = agenda.crear(params["titulo"], params["inicio"], params.get("fin"), params.get("descripcion", ""),
                         int(params.get("minutos_aviso") or 30))
        return f"evento creado en {agenda.actual().nombre}: {e['titulo']} ({e['inicio']}) {e['enlace']}"


ACCIONES = [Agendar()]
