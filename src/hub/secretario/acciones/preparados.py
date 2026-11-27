"""Los comandos preparados del dueño, usados por el secretario (C-0507, decisión 464).

Dijo «no existe ningún script» cuando el dueño le pidió unos repos: los
comandos de `comandos.yml` existían, pero sólo como un botón de Archivos.
Ahora son suyos también, por las mismas puertas:

- **`dejar_comando_escrito`**: abre la ventana en la carpeta con la orden (o
  las de una lista, en una línea unida por ` ; `) escrita y SIN Enter —
  `comandos.dejar_escrito`, la misma de Archivos—. Tiene vuelta atrás: no
  corre nada; el Enter lo pone él.
- **`clonar_lista`**: las corre él mismo, una por valor, con el sí del dueño
  en Pendientes a las órdenes exactas ya rellenadas (un «sí» en el chat no
  vale, 303). Lo que hace el sí es encargarlo a `lotes`, que corre
  `comandos.ejecutar_lote` en `hub-secretario` y deja el informe en el chat.

🔴 La plantilla nunca sale del modelo: el modelo elige un `preparado` por su
id y pone los valores. Qué se puede correr lo decide el dueño en su archivo
(`ejecutable: true`), y qué carpeta crea cada uno, también (`crea`).
"""

from __future__ import annotations

from pathlib import Path

from ... import comandos, db
from .. import lotes
from ..piezas import Accion

_PARAMETROS = {"type": "object", "properties": {
    "preparado": {"type": "string", "description": "El id del comando preparado (míralos con `comandos_preparados`)."},
    "ruta": {"type": "string", "description": "La carpeta donde se corre, absoluta (la de `comandos_preparados`)."},
    "valores": {"type": "array", "items": {"type": "string"},
                "description": "Un valor por orden: los nombres de los repos, tal cual te los dio."},
    "hueco": {"type": "string", "description": "Qué hueco lleva cada valor; sólo si el comando tiene más de uno."},
    "fijos": {"type": "object", "additionalProperties": {"type": "string"},
              "description": "Los demás huecos, si los tiene, con el mismo valor para todas."}},
    "required": ["preparado", "ruta", "valores"]}


def _hay_comandos() -> bool:
    return bool(comandos.leer())


def _hay_ejecutables() -> bool:
    return any(c.get("ejecutable") is True and c.get("crea") for c in comandos.leer())


def _lote(params: dict) -> tuple[Path, list[tuple[str, str, Path | None]]]:
    """La carpeta resuelta y las órdenes de esa lista, comprobando lo mismo
    que `ejecutar_lote` antes de correr: lo que no se va a poder hacer no
    llega a pedirse."""
    h = db.conectar()
    try:
        destino, _ = comandos.carpeta_para(h, str(params.get("ruta") or ""), respetar_never=True)
    finally:
        h.close()
    return destino, comandos.ordenes(str(params.get("preparado") or ""), params.get("hueco") or None,
                                     params.get("valores") or [], str(destino), params.get("fijos") or None)


class DejarComandoEscrito(Accion):
    id = "dejar_comando_escrito"
    gesto = "pc"
    nombre = "Dejarte un comando preparado escrito"
    resumen = ("Abre una ventana en la carpeta con uno de tus comandos preparados escrito, sin Enter: lo lanzas "
               "tú. Con una lista, todas las órdenes en una sola línea.")
    descripcion = ("Abre una ventana de tmux en una carpeta con uno de SUS comandos preparados (`comandos.yml`, "
                   "míralos con `comandos_preparados`) escrito y SIN Enter, para que lo lance él: lo mismo que "
                   "«Clonar repo» en Archivos. `preparado`: su id. `ruta`: la carpeta absoluta. `valores`: uno o "
                   "varios (p. ej. nombres de repos); con varios van todos en una línea, separados por « ; ». "
                   "Los que ya tienen su carpeta se saltan. Devuelve el enlace a la ventana en /trabajo: dáselo, o "
                   "ábreselo con abrir_en_pc. Si quiere que los clones tú, `clonar_lista`.")
    parametros = _PARAMETROS
    riesgo = "reversible"
    nivel_inicial = "auto"
    solo_con_el_dueno = True
    disponible = staticmethod(_hay_comandos)
    como_configurar = "Declara tus comandos en comandos.yml (Archivos → comandos preparados)."

    def ejecutar(self, con, params):
        h = db.conectar()
        try:
            r = comandos.dejar_escrito(h, str(params.get("preparado") or ""), params.get("valores") or [],
                                       str(params.get("ruta") or ""), hueco=params.get("hueco") or None,
                                       fijos=params.get("fijos") or None, respetar_never=True)
        finally:
            h.close()
        partes = [f"escrito sin Enter en una ventana de {r['ruta']}: {r['url']}"]
        if r["saltados"]:
            partes.append("ya estaban y no los escribí: " + ", ".join(r["saltados"]))
        if r["sin_crea"]:
            partes.append("ese comando no dice qué carpeta crea, así que no salté ninguno aunque ya estuviera")
        return "; ".join(partes)


class ClonarLista(Accion):
    id = "clonar_lista"
    gesto = "pc"
    nombre = "Correr un comando preparado sobre una lista"
    resumen = ("Corre uno de tus comandos preparados (p. ej. clonar un repo) para cada valor de una lista, de uno "
               "en uno, y te dice cuáles salieron. Sólo los que marcaste ejecutables en comandos.yml, siempre con "
               "tu sí a las órdenes exactas; si apruebas pasados 15 minutos, no lo corre.")
    descripcion = ("Corre TÚ uno de sus comandos preparados para cada valor de una lista —«clóname estos repos»—, "
                   "de uno en uno, y comprueba que cada carpeta quedó creada. `preparado`: su id (de "
                   "`comandos_preparados`, sólo los `ejecutable`). `ruta`: la carpeta absoluta donde van. "
                   "`valores`: los nombres, tal cual te los dio (hasta 30). Los que ya están se saltan. SIEMPRE "
                   "pide su sí en Pendientes, donde ve cada orden: dile que se lo pediste, no que ya está. El "
                   "informe llega después a este chat. Si no es ejecutable, `dejar_comando_escrito`.")
    parametros = _PARAMETROS
    # 🔴 Irreversible: corre un script suyo con sus credenciales y crea
    # carpetas en un proyecto. Pregunta siempre (techo de la 303), y el sí es
    # su toque en Pendientes viendo las órdenes (`detalle`), nunca el chat.
    riesgo = "irreversible"
    nivel_inicial = "ask"
    solo_con_el_dueno = True
    # Sólo `ejecutar_aprobadas` sabe que la aprobó, y en qué hilo se pidió.
    quiere_aprobacion = True
    quiere_hilo = True
    caduca_s = 15 * 60
    disponible = staticmethod(_hay_ejecutables)
    como_configurar = ("En comandos.yml, añade a ese comando `ejecutable: true` y `crea: \"{repo}\"` (la carpeta "
                       "que crea). Lo decides tú: el hub no escribe ese archivo.")

    def _comprobado(self, params) -> tuple:
        preparado = str(params.get("preparado") or "")
        comando = comandos.por_id(preparado)
        if not comando:
            raise ValueError(f"no hay ningún comando preparado «{preparado}»")
        if comando.get("ejecutable") is not True:
            raise ValueError(f"«{preparado}» no está marcado `ejecutable: true` en comandos.yml: eso lo decide él. "
                             "Puedes dejárselo escrito con dejar_comando_escrito")
        if not comando.get("crea"):
            raise ValueError(f"«{preparado}» no dice qué carpeta crea (`crea` en comandos.yml)")
        destino, lote = _lote(params)
        return comando, destino, lote

    def comprobar(self, params):
        _, _, lote = self._comprobado(params)
        # Sólo cuántas: lo que devuelve esto se guarda y sale en el aviso, y
        # los repos o el nombre del comando pueden nombrar a un cliente (regla
        # dura 22). Las órdenes enteras las enseña `detalle`, en Pendientes.
        # El `motivo` que redacta el modelo también va al aviso, como en toda
        # acción: eso no lo controla esta.
        return f"{len(lote)} órdenes"

    def detalle(self, con, params):
        """Las órdenes exactas, rellenadas ahora: lo que va a correr si dice que sí."""
        try:
            _, destino, lote = self._comprobado(params)
        except (ValueError, comandos.CarpetaInvalida) as exc:
            return [("no se puede", str(exc))]
        filas = [("carpeta", str(destino))]
        for i, (_, orden, carpeta) in enumerate(lote, 1):
            filas.append((f"orden {i}", orden + (" — ya está: se salta" if carpeta.exists() else "")))
        return filas

    def ejecutar(self, con, params, aprobada: bool = False, hilo: int | None = None):
        if not aprobada:
            raise RuntimeError("esto sólo se hace con el sí del dueño a esta solicitud")
        _, destino, lote = self._comprobado(params)
        # Con las órdenes tal cual las vio: si `comandos.yml` cambia mientras
        # espera en la cola, `ejecutar_lote` no corre lo que no aprobó.
        pedido = {"preparado": str(params["preparado"]), "ruta": str(destino), "valores": [v for v, _, _ in lote],
                  "hueco": params.get("hueco") or None, "fijos": params.get("fijos") or None, "hilo": hilo,
                  "ordenes": [orden for _, orden, _ in lote]}
        if not lotes.encargar(con, pedido):
            return "esa misma lista ya estaba esperando; el informe sale en este chat"
        return f"encargadas {len(lote)} órdenes; van de una en una y el informe sale en este chat al acabar"


ACCIONES = [DejarComandoEscrito(), ClonarLista()]
