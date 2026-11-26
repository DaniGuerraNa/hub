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


class SinControl(RuntimeError):
    """Claude no tiene el control del Mac ahora mismo."""


@dataclass
class Control:
    modo: str = LIBRE
    desde: float = field(default_factory=time.time)
    motivo: str = "arranque"
    ultima_accion: float = field(default_factory=time.time)

    def dar(self) -> None:
        self.modo, self.desde, self.motivo = CLAUDE, time.time(), "dado en la pantalla"
        self.ultima_accion = time.time()

    def _caducar(self) -> None:
        if self.modo == CLAUDE and time.time() - self.ultima_accion > INACTIVIDAD_S:
            self.modo, self.desde = LIBRE, time.time()
            self.motivo = f"volvió a la persona tras {INACTIVIDAD_S // 60} min sin que Claude hiciera nada"

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
