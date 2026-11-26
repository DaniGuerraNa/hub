"""Quién tiene el teclado del Mac, y qué se ha hecho con él.

El Mac es de una persona que lo usa, y lo que el JetKVM teclea va a la ventana
que tenga el foco, sea la que sea. Por eso Claude sólo actúa cuando la persona
le ha dado el control **en la pantalla del puente**, y lo pierde al pulsar
«Parar» o al reiniciar el servicio: arranca siempre sin control, a
propósito: un reinicio no puede dejar a Claude con el teclado del Mac.

Cuando el puente se lo devuelve a la persona (Claude acabó el encargo, cambió
el aparato…) lo hace por `Puente.devolver_control`, que lo apunta en la
bitácora: aquí no hay otra puerta para eso (C-0486).

Cada acción queda en la bitácora (JSONL), con captura si cambió la pantalla.
"""

from __future__ import annotations

import json
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from .config import hogar

# Si Claude no toca el Mac en este tiempo, el control vuelve solo a la persona.
# Se mide: en la primera demo el control quedó dado tras una lectura y una
# prueba posterior tecleó en el editor sin que nadie lo esperara.
INACTIVIDAD_S = 10 * 60

LIBRE = "libre"  # la persona usa el Mac; Claude no puede tocarlo
CLAUDE = "claude"  # la persona se lo ha dado
PARADO = "parado"  # alguien pulsó Parar: lo que estuviera en marcha se corta


# El presupuesto de las correcciones pequeñas (C-0489, decisión 458 del hub): lo
# que Claude puede escribir sin una aprobación por cambio, sumando TODOS los
# cambios de una concesión (líneas y caracteres de lo que quita más lo que pone).
# Sumar es lo que impide partir un cambio grande en veinte pequeños. Es una
# política declarada en la casilla, no una medición: se revisa con lo que midan
# las mediciones de uso (C-0483).
TOPE_LINEAS = 20
TOPE_CARACTERES = 1500


class SinControl(RuntimeError):
    """Claude no tiene el control del Mac ahora mismo."""


@dataclass
class Permiso:
    """El permiso de correcciones pequeñas de UNA concesión del control.

    Nace sólo de la casilla del diálogo «Dar el control» y no se guarda en
    ningún sitio: un reinicio lo pierde, como pierde el control. Si sigue
    valiendo lo dice `Control.permiso_vigente`, no este objeto."""

    id: str
    tope_lineas: int = TOPE_LINEAS
    tope_caracteres: int = TOPE_CARACTERES
    lineas: int = 0
    caracteres: int = 0
    # Los cambios que aprobó (los ids), para el resumen al devolver el Mac.
    escritos: list[str] = field(default_factory=list)

    def cabe(self, lineas: int, caracteres: int) -> str | None:
        """None si cabe en lo que queda; si no, el motivo («34 líneas; quedan 12»)."""
        quedan = self.tope_lineas - self.lineas
        if lineas > quedan:
            return f"{lineas} líneas; quedan {max(0, quedan)}"
        quedan = self.tope_caracteres - self.caracteres
        if caracteres > quedan:
            return f"{caracteres} caracteres; quedan {max(0, quedan)}"
        return None

    def gastar(self, lineas: int, caracteres: int, cambio: str) -> None:
        self.lineas += lineas
        self.caracteres += caracteres
        self.escritos.append(cambio)


@dataclass
class Control:
    modo: str = LIBRE
    desde: float = field(default_factory=time.time)
    motivo: str = "arranque"
    ultima_accion: float = field(default_factory=time.time)
    #: A quién contarle que el control caducó: cuántos ms lo tuvo Claude (las
    #: mediciones, C-0483) y el permiso de correcciones que valía hasta entonces
    #: (el resumen de lo que escribió sin pedir, C-0489): después ya no es el
    #: vigente, así que se coge antes de soltar. Se llama después de devolverlo
    #: y lo que lance se traga: contarlo no puede dejar el control dado.
    al_caducar: Callable[[float, "Permiso | None"], None] | None = field(default=None, repr=False,
                                                                        compare=False)
    # Cada «dar» es una concesión nueva, con su id: un permiso de correcciones
    # sólo vale para la concesión en que se dio (C-0489).
    concesion: str = ""
    permiso: Permiso | None = None

    def dar(self, correcciones: bool = False) -> None:
        self.modo, self.desde, self.motivo = CLAUDE, time.time(), "dado en la pantalla"
        self.ultima_accion = time.time()
        self.concesion = uuid.uuid4().hex[:12]
        # Sin casilla, ningún permiso: el de una concesión anterior no pasa a ésta.
        self.permiso = Permiso(self.concesion) if correcciones else None

    def permiso_vigente(self) -> Permiso | None:
        """El permiso de correcciones pequeñas, si sigue valiendo.

        Vale mientras dure la concesión en que se dio: se acaba por construcción
        con cualquier cosa que quite el control (devolverlo, Parar, Retomar, la
        caducidad) y con un «dar» nuevo, sin que nadie tenga que acordarse de
        borrarlo."""
        self._caducar()
        return self._permiso_de_la_concesion()

    def _permiso_de_la_concesion(self) -> Permiso | None:
        if self.modo != CLAUDE or self.permiso is None or self.permiso.id != self.concesion:
            return None
        return self.permiso

    def _caducar(self) -> None:
        if self.modo == CLAUDE and time.time() - self.ultima_accion > INACTIVIDAD_S:
            # Hasta que caducó, no hasta que alguien lo miró.
            con_claude = max(0.0, (self.ultima_accion + INACTIVIDAD_S - self.desde) * 1000)
            permiso = self._permiso_de_la_concesion()  # antes de soltar: después no es el vigente
            self.modo, self.desde = LIBRE, time.time()
            self.motivo = f"volvió a la persona tras {INACTIVIDAD_S // 60} min sin que Claude hiciera nada"
            if self.al_caducar is not None:
                try:
                    self.al_caducar(con_claude, permiso)
                except Exception:
                    pass

    def retomar(self, motivo: str = "retomado en la pantalla") -> None:
        # No hace falta avisar a nadie: lo que esté en marcha comprueba el
        # control antes de cada tecla (`comprobar`) y se corta en la siguiente.
        self.modo, self.desde, self.motivo = LIBRE, time.time(), motivo

    def parar(self, motivo: str = "botón Parar") -> None:
        self.modo, self.desde, self.motivo = PARADO, time.time(), motivo

    def comprobar(self) -> None:
        """Se llama antes de CADA informe al aparato, no una vez por tarea."""
        self._caducar()
        if self.modo != CLAUDE:
            raise SinControl(
                "Claude no tiene el control del Mac. Pídeselo a la persona: "
                "lo da en la pantalla del puente con «Dar el control a Claude»."
            )
        self.ultima_accion = time.time()

    def estado(self) -> dict:
        self._caducar()
        e = {"modo": self.modo, "desde": self.desde, "motivo": self.motivo}
        if self.modo == CLAUDE:
            e["caduca"] = self.ultima_accion + INACTIVIDAD_S
        p = self.permiso_vigente()
        if p is not None:
            e["correcciones"] = {"lineas": p.lineas, "caracteres": p.caracteres,
                                 "tope_lineas": p.tope_lineas, "tope_caracteres": p.tope_caracteres}
        return e


class Bitacora:
    def __init__(self, ruta: Path | None = None):
        self.ruta = ruta or hogar() / "bitacora.jsonl"
        self._ultimas: list[dict] = []
        if self.ruta.exists():
            for linea in self.ruta.read_text().splitlines()[-200:]:
                try:
                    self._ultimas.append(json.loads(linea))
                except json.JSONDecodeError:
                    pass
        self._n = (self._ultimas[-1]["n"] + 1) if self._ultimas else 1

    def apuntar(self, tipo: str, detalle: str, quien: str = "claude", **extra) -> dict:
        entrada = {"n": self._n, "t": time.time(), "tipo": tipo, "detalle": detalle,
                   "quien": quien, **extra}
        self._n += 1
        self._ultimas = (self._ultimas + [entrada])[-200:]
        with self.ruta.open("a") as f:
            f.write(json.dumps(entrada, ensure_ascii=False) + "\n")
        return entrada

    def ultimas(self, desde: int = 0, cuantas: int = 60) -> list[dict]:
        return [e for e in self._ultimas if e["n"] > desde][-cuantas:]
