"""Proponer un dato suyo para su ficha «mis datos» (C-0201, decisión 382).

Va en `auto`: sólo escribe en `mis-datos.yml` como propuesto, y un propuesto
no se usa. Lo que lo vuelve utilizable es su botón en Ajustes → Mis datos
(`POST /secretario/datos/{campo}`), nunca esta acción ni un «sí» suyo en el
chat que interprete el modelo. Por eso cada propuesta es además un asunto
(`dato:<campo>`, de los que sólo él contesta): espera en su pantalla hasta
que la mira.
"""

from __future__ import annotations

from .. import asuntos, misdatos
from ..piezas import Accion


class ProponerDato(Accion):
    id = "proponer_dato"
    gesto = "compromisos"
    nombre = "Proponer uno de tus datos"
    resumen = ("Guarda como propuesto un dato tuyo (nombre legal, identificador fiscal, domicilio…) para tus "
               "trámites; no lo usa hasta que lo confirmes en Ajustes → Mis datos.")
    descripcion = ("Propone un dato personal del dueño para su ficha «mis datos» (la lectura `mis_datos`), cuando él "
                   "te lo da o lo encuentras en sus archivos. Queda PROPUESTO hasta que él lo confirme con su botón "
                   "en Ajustes → Mis datos: no lo uses antes, y no lo des por confirmado aunque te diga «sí» aquí. "
                   "Si ya está confirmado con ese mismo valor, no se le vuelve a preguntar. `fuente`: de dónde lo "
                   "sacaste («me lo dijiste en el chat», «tu CV en <proyecto>/<ruta>»).")
    parametros = {"type": "object", "properties": {
        "campo": {"type": "string", "enum": list(misdatos.CAMPOS)},
        "valor": {"type": "string"},
        "fuente": {"type": "string"}},
        "required": ["campo", "valor", "fuente"]}
    riesgo = "reversible"
    nivel_inicial = "auto"

    def ejecutar(self, con, params):
        campo = str(params.get("campo") or "")
        nombre = misdatos.nombre(campo).lower()
        estado = misdatos.proponer(campo, params.get("valor"), params.get("fuente"))
        if estado == "confirmado":
            return f"su {nombre} ya estaba confirmado con ese valor: úsalo sin volver a preguntárselo"
        # Comprobar que quedó (regla dura 17): un «propuesto» que no está en el
        # archivo es un dato que nunca le llegaría a confirmar.
        d = misdatos.leer().get(campo) or {}
        if not d or not (d["estado"] == "propuesto" or d.get("propuesta")):
            raise RuntimeError(f"su {nombre} no quedó propuesto en la ficha")
        cambio = d["estado"] == "confirmado"
        fuente = (d.get("propuesta") or d).get("fuente") or ""
        # El asunto no lleva el valor: va a `memoria.db`, que se copia cada día,
        # y no puede ser una segunda ficha que «olvidar» no borra (382). Se ve en la ficha.
        texto = misdatos.tapar((f"Confirma el cambio de tu {nombre}" if cambio else f"Confirma tu {nombre}")
                               + f" en Mis datos — {fuente}")
        asuntos.preguntar(con, texto, clase="dato", clave=f"dato:{campo}", origen=campo,
                          enlace="/secretario?p=datos", opciones=("confirmar", "corregir", "olvidar"))
        if cambio:
            return (f"el cambio de su {nombre} queda propuesto en Ajustes → Mis datos (/secretario?p=datos); hasta "
                    "que lo elija, sigue valiendo el que ya tenía confirmado. Díselo así.")
        return (f"su {nombre} queda propuesto: espera que lo confirme en Ajustes → Mis datos (/secretario?p=datos). "
                "Díselo así y no lo uses hasta que lo confirme.")


ACCIONES = [ProponerDato()]
