"""Arrancar, parar o reiniciar UN contenedor de Docker (C-0422).

🔴 Regla dura 12: de uno en uno y por nombre exacto; nunca en lote, nunca por
patrón, y `rm` no existe. Lo valida la puerta (`hub.servicios.accionar`, la
misma del botón de /servicios) y aquí se le suma lo que el botón tiene por
estar en la pantalla: sólo un contenedor que el hub ya conoce (la tabla
`servicio`), nunca el de un proyecto con guardrail `never` (regla dura 7), y
siempre con el sí del dueño a esa solicitud, que mientras espera enseña de
qué proyecto es y cómo está (`detalle`): eso no se guarda con ella ni sale en
el aviso, porque nombra un proyecto y porque al aprobarla ya sería viejo.
"""

from __future__ import annotations

from ... import db, orquestador, registry, servicios
from ..piezas import Accion

QUE = ("start", "stop", "restart")


class Contenedor(Accion):
    id = "contenedor"
    gesto = "maquina"
    nombre = "Arrancar o parar un contenedor"
    resumen = ("Arranca, para o reinicia un contenedor de Docker de los que salen en Servicios, de uno en uno "
               "y por su nombre exacto. Pregunta siempre, diciendo cuál es y de qué proyecto; nunca toca los "
               "de un proyecto en never, y borrar no lo hace.")
    descripcion = ("Arranca (`que`: start), para (stop) o reinicia (restart) UN contenedor de Docker cuando el "
                   "dueño lo pide. `contenedor` es su nombre exacto, tal como sale en `hub_servicios`: uno "
                   "solo, sin comodines ni listas; si quiere varios, uno por llamada y cada uno con su "
                   "permiso. No borra contenedores ni toca los de un proyecto con guardrail never. Siempre "
                   "pide su permiso: dile que se lo pediste, no que ya está.")
    parametros = {"type": "object", "properties": {
        "contenedor": {"type": "string"}, "que": {"type": "string", "enum": list(QUE)}},
        "required": ["contenedor", "que"]}
    riesgo = "reversible"
    nivel_inicial = "ask"
    # Parar el contenedor que no era es el accidente que /servicios existe
    # para evitar (decisión 50): cuál y cuándo lo decide él, cada vez.
    siempre_pregunta = True
    solo_con_el_dueno = True
    # Sólo `ejecutar_aprobadas` sabe que la aprobó (como `cambiar_en_pc`).
    quiere_aprobacion = True

    @staticmethod
    def _leer(h, params) -> tuple[dict, str]:
        """El contenedor del índice y qué hacerle; lanza si no se puede ni pedir."""
        que = str(params.get("que") or "")
        if que not in QUE:
            raise ValueError("`que` es start, stop o restart; borrar un contenedor no se hace desde aquí")
        nombre = str(params.get("contenedor") or "")
        # La misma forma que exige la puerta: `-a` o un patrón no son un nombre.
        if not servicios.NOMBRE_CONTENEDOR.fullmatch(nombre):
            raise ValueError("nombre de contenedor inválido: uno solo y exacto, como sale en `hub_servicios`")
        fila = h.execute("SELECT * FROM servicio WHERE contenedor = ?", (nombre,)).fetchone()
        if fila is None:
            raise ValueError(f"no conozco ningún contenedor «{nombre}»: sólo los que salen en Servicios, "
                             "por su nombre exacto (`hub_servicios`)")
        proyecto = fila["proyecto_id"]
        # Un proyecto que ya no está en el índice cuenta como `never`: ante la duda, no.
        if proyecto and orquestador.guardrail_de(h, proyecto) == "never":
            raise PermissionError(f"«{nombre}» es de «{proyecto}», que tiene guardrail never: ahí el hub no "
                                  "toca nada; primero se cambia el guardrail")
        return dict(fila), que

    def comprobar(self, params):
        h = db.abrir()
        try:
            c, _ = self._leer(h, params)
        finally:
            h.close()
        # Sólo su nombre, que es lo que pidió. De quién es y cómo está van en
        # `detalle`: el proyecto no sale en el aviso (regla dura 22), y un
        # «ahora running» escrito aquí seguiría diciéndolo días después.
        return f"contenedor {c['contenedor']}"

    def detalle(self, con, params):
        """De quién es y cómo está, que es lo que hay que saber antes de parar
        nada. Del índice (`servicio`), no de docker: se pinta en cada sondeo."""
        h = db.conectar()
        try:
            fila = h.execute("SELECT proyecto_id, estado FROM servicio WHERE contenedor = ?",
                             (str(params.get("contenedor") or ""),)).fetchone()
        finally:
            h.close()
        if fila is None:
            return [("contenedor", "ya no está en Servicios")]
        return [("proyecto", fila["proyecto_id"] or "sin proyecto asignado"),
                ("estado en la última medición", fila["estado"] or "desconocido")]

    def ejecutar(self, con, params, aprobada: bool = False):
        if not aprobada:
            raise RuntimeError("esto sólo se hace con el sí del dueño a esta solicitud")
        h = db.abrir()
        try:
            # Otra vez, ahora: entre su sí y esto pudo cambiar el índice o el guardrail.
            c, que = self._leer(h, params)
            nombre = c["contenedor"]
            try:
                servicios.accionar(nombre, que)
            except servicios.AccionInvalida as exc:
                raise RuntimeError(f"docker no lo hizo: {exc}") from None
            # Como la pantalla (`/api/servicio/accion`): se vuelve a escanear, y de
            # ahí sale cómo quedó (regla dura 17). Falle lo que falle al mirar
            # —docker que no contesta, el registro mal escrito—, la orden ya
            # salió: se dice eso, no «falló» a secas ni «hecho» sin haberlo visto.
            try:
                servicios.escanear(h, registry.cargar())
                h.commit()
            except Exception as exc:  # noqa: BLE001 — se dice en voz alta, con lo que sí pasó
                raise RuntimeError(f"le mandé {que} a {nombre}, pero no pude mirar cómo quedó "
                                   f"({exc}): compruébalo en Servicios") from None
            fila = h.execute("SELECT estado FROM servicio WHERE contenedor = ?", (nombre,)).fetchone()
        finally:
            h.close()
        estado = fila["estado"] if fila else ""
        corre = estado == "running"
        if (que == "stop") == corre:
            raise RuntimeError(f"le mandé {que} a {nombre} y {'sigue ' + estado if fila else 'ya no aparece'}: "
                               "míralo en Servicios")
        return f"contenedor {nombre}: {que} hecho, ahora {estado}"


ACCIONES = [Contenedor()]
