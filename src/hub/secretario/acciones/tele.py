"""La tele del dueño, por ECP de Roku (decisión 321).

Encender, apagar, cambiar de entrada, abrir una app y mirar cómo está. El
cliente es `roku.py`; aquí sólo la configuración y comprobar que salió.

La configuración vive en `secretario.yml`, no en la base (regla dura 1: es del
dueño, no se deriva):

    tele:
      ip: 192.168.1.50
      entradas:
        pc: InputHDMI2
        consola: InputHDMI1

**Niveles** (decisión 321). Mirar el estado es lectura y va en `auto`. Lo
demás es `reversible` —se deshace con el control en un segundo— pero empieza
en `ask`: encender o apagar una tele cambia un cuarto donde puede haber
alguien, y que el dueño vea las primeras veces qué pide el modelo es lo que le
deja subirlo a `auto` con conocimiento. Que la tele se encienda **sola** para
un aviso sería una clase de aviso nueva (regla dura 3) y no existe: aquí sólo
se enciende porque alguien lo pidió.

🔴 Cada acción comprueba que pasó (regla dura 17): tras PowerOn espera a ver
`power-mode=PowerOn`, tras una entrada o una app espera a verla en
`/query/active-app`. Mandar la tecla no es haberlo hecho.
"""

from __future__ import annotations

import time
import unicodedata

from .. import piezas, roku
from ..piezas import Accion

#: Cuánto se espera a ver el cambio. Una Roku con Fast TV Start enciende en
#: 2-5 s; cambiar de entrada, en uno.
ESPERA_ENCENDER_S = 15.0
ESPERA_CAMBIO_S = 6.0
PAUSA_S = 0.5

#: Nombres que valen siempre, aunque el dueño no haya puesto ninguno.
ENTRADAS_DE_SERIE = {
    "hdmi1": "InputHDMI1", "hdmi2": "InputHDMI2", "hdmi3": "InputHDMI3", "hdmi4": "InputHDMI4",
    "antena": "InputTuner", "tdt": "InputTuner", "av": "InputAV1",
}

COMO_CONFIGURAR = ("No sé dónde está la tele: falta su IP. Ponla en secretario.yml (en la carpeta del "
                   "secretario, dentro de HUB_HOME) así:\n"
                   "tele:\n  ip: 192.168.1.50\n  entradas:\n    pc: InputHDMI2\n"
                   "La IP está en la tele, en Ajustes → Red → Acerca de; resérvala en el router para que no cambie.")


def _normal(t: str) -> str:
    t = unicodedata.normalize("NFKD", str(t or "")).encode("ascii", "ignore").decode()
    return " ".join(t.lower().split())


def configuracion() -> dict:
    c = piezas.ajuste("tele")
    return c if isinstance(c, dict) else {}


def tele() -> roku.Tele:
    c = configuracion()
    if not str(c.get("ip") or "").strip():
        raise roku.TeleError(COMO_CONFIGURAR)
    return roku.Tele(str(c["ip"]), int(c.get("puerto") or roku.PUERTO))


def entradas() -> dict[str, str]:
    """Nombre amigable → tecla. Las del dueño mandan sobre las de serie; una
    que no es una entrada de verdad se ignora en vez de mandarse."""
    out = dict(ENTRADAS_DE_SERIE)
    for nombre, tecla in (configuracion().get("entradas") or {}).items():
        if str(tecla) in roku.ENTRADAS:
            out[_normal(nombre)] = str(tecla)
    return out


def resolver_entrada(nombre: str) -> str:
    n = _normal(nombre)
    todas = entradas()
    if n in todas:
        return todas[n]
    if str(nombre) in roku.ENTRADAS:
        return str(nombre)
    if n.replace(" ", "") in todas:            # «hdmi 2»
        return todas[n.replace(" ", "")]
    raise roku.TeleError(f"no conozco la entrada «{nombre}» (hay: {', '.join(sorted(todas))}). "
                         "Se ponen nombres en secretario.yml, tele → entradas")


def _esperar(condicion, segundos: float):
    """Vuelve a mirar hasta que `condicion()` dé algo verdadero, o devuelve el último valor."""
    fin = time.monotonic() + segundos
    ultimo = None
    while True:
        try:
            ultimo = condicion()
        except roku.TeleError:
            ultimo = None
        if ultimo and ultimo[0]:
            return ultimo
        if time.monotonic() >= fin:
            return ultimo
        time.sleep(PAUSA_S)


def _poner_entrada(t: roku.Tele, tecla: str) -> str:
    t.tecla(tecla)
    esperado = roku.id_de_entrada(tecla)

    def mirar():
        a = t.activa()
        return a["id"] == esperado, a

    r = _esperar(mirar, ESPERA_CAMBIO_S)
    if not r or not r[0]:
        visto = (r[1]["nombre"] or r[1]["id"]) if r else "no contestó"
        raise roku.TeleError(f"mandé {tecla} pero la tele no cambió (se ve: {visto})")
    return r[1]["nombre"] or tecla


def _exige_encendida(t: roku.Tele) -> None:
    e = t.estado()
    if not e["encendida"]:
        raise roku.TeleError(f"la tele está en espera ({e['power_mode']}): enciéndela primero con tele_encender")


class TeleEstado(Accion):
    id = "tele_estado"
    gesto = "tele"
    nombre = "Mirar cómo está la tele"
    resumen = "Si la tele está encendida o en espera, y qué se ve. Sólo mira."
    descripcion = ("Mira la tele del dueño: si está encendida o en espera, su modelo, qué entrada o app se ve, "
                   "y qué nombres de entrada conoces. Úsala antes de decir cómo está la tele.")
    parametros = {"type": "object", "properties": {}}
    riesgo = "lectura"
    nivel_inicial = "auto"

    def ejecutar(self, con, params):
        t = tele()
        e = t.estado()
        partes = [("encendida" if e["encendida"] else f"en espera ({e['power_mode']})")]
        if e["nombre"] or e["modelo"]:
            partes.append(" · ".join(p for p in (e["nombre"], e["modelo"]) if p))
        if e["encendida"]:
            try:
                a = t.activa()
                if a["id"]:
                    partes.append(f"se ve: {a['nombre'] or a['id']}")
            except roku.TeleError:
                pass
        partes.append("entradas: " + ", ".join(f"{k}={v}" for k, v in sorted(entradas().items())))
        return "tele " + "; ".join(partes)


class TeleEncender(Accion):
    id = "tele_encender"
    gesto = "tele"
    nombre = "Encender la tele"
    resumen = "Enciende la tele y, si se lo dices, la pone en una entrada (por ejemplo, la PC)."
    descripcion = ("Enciende la tele del dueño y, si das `entrada`, la cambia a ella después. `entrada` es un "
                   "nombre amigable («pc», «consola», «hdmi2», «antena»); mira tele_estado para ver cuáles hay.")
    parametros = {"type": "object", "properties": {"entrada": {"type": "string"}}}
    riesgo = "reversible"
    nivel_inicial = "ask"

    def ejecutar(self, con, params):
        t = tele()
        tecla = resolver_entrada(params["entrada"]) if params.get("entrada") else None
        t.tecla("PowerOn")
        r = _esperar(lambda: (t.estado()["encendida"], None), ESPERA_ENCENDER_S)
        if not r or not r[0]:
            raise roku.TeleError("mandé PowerOn pero la tele sigue en espera: en la tele, activa «Fast TV Start» "
                                 "(Ajustes → Sistema → Energía)")
        if not tecla:
            return "tele encendida"
        return f"tele encendida y en {_poner_entrada(t, tecla)}"


class TeleApagar(Accion):
    id = "tele_apagar"
    gesto = "tele"
    nombre = "Apagar la tele"
    resumen = "Apaga la tele (la deja en espera)."
    descripcion = "Apaga la tele del dueño (queda en espera; se puede volver a encender con tele_encender)."
    parametros = {"type": "object", "properties": {}}
    riesgo = "reversible"
    nivel_inicial = "ask"

    def ejecutar(self, con, params):
        t = tele()
        t.tecla("PowerOff")
        fin = time.monotonic() + ESPERA_CAMBIO_S
        while True:
            try:
                e = t.estado()
            except roku.TeleError:
                # Sin Fast TV Start, apagada deja de contestar: es la prueba de que se apagó.
                return "tele apagada (ya no contesta en la red)"
            if not e["encendida"]:
                return f"tele apagada ({e['power_mode']})"
            if time.monotonic() >= fin:
                raise roku.TeleError("mandé PowerOff pero la tele sigue encendida")
            time.sleep(PAUSA_S)


class TeleEntrada(Accion):
    id = "tele_entrada"
    gesto = "tele"
    nombre = "Cambiar la entrada de la tele"
    resumen = "Pone la tele en una entrada por su nombre: la PC, la consola, la antena…"
    descripcion = ("Cambia la entrada de la tele del dueño, que tiene que estar encendida. `entrada` es un nombre "
                   "amigable («pc», «consola», «hdmi2», «antena»). Si está apagada, usa tele_encender con entrada.")
    parametros = {"type": "object", "properties": {"entrada": {"type": "string"}}, "required": ["entrada"]}
    riesgo = "reversible"
    nivel_inicial = "ask"

    def ejecutar(self, con, params):
        t = tele()
        tecla = resolver_entrada(params["entrada"])
        _exige_encendida(t)
        return f"tele en {_poner_entrada(t, tecla)}"


class TeleApp(Accion):
    id = "tele_app"
    gesto = "tele"
    nombre = "Abrir una app en la tele"
    resumen = "Abre en la tele una app instalada (YouTube, Netflix…) por su nombre."
    descripcion = ("Abre en la tele del dueño (encendida) una app instalada por su nombre: «YouTube», «Netflix», "
                   "«Spotify». Si el nombre no casa con ninguna, dice cuáles hay.")
    parametros = {"type": "object", "properties": {"app": {"type": "string"}}, "required": ["app"]}
    riesgo = "reversible"
    nivel_inicial = "ask"

    def ejecutar(self, con, params):
        t = tele()
        _exige_encendida(t)
        buscada = _normal(params["app"])
        if not buscada:
            raise roku.TeleError("falta el nombre de la app")
        apps = t.apps()
        exactas = [a for a in apps if _normal(a["nombre"]) == buscada]
        parecidas = exactas or [a for a in apps if buscada in _normal(a["nombre"])]
        if not parecidas:
            raise roku.TeleError(f"no hay ninguna app «{params['app']}» en la tele (hay: "
                                 f"{', '.join(a['nombre'] for a in apps) or 'ninguna'})")
        if len(parecidas) > 1:
            raise roku.TeleError(f"«{params['app']}» puede ser {', '.join(a['nombre'] for a in parecidas)}: "
                                 "di cuál")
        app = parecidas[0]
        t.abrir_app(app["id"])
        r = _esperar(lambda: (t.activa()["id"] == app["id"], None), ESPERA_CAMBIO_S)
        if not r or not r[0]:
            raise roku.TeleError(f"pedí abrir {app['nombre']} pero la tele no la muestra")
        return f"{app['nombre']} abierta en la tele"


ACCIONES = [TeleEstado(), TeleEncender(), TeleApagar(), TeleEntrada(), TeleApp()]
