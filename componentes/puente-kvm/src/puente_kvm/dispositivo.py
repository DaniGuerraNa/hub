"""Lo que el puente necesita de un aparato: ver la pantalla, teclado y ratón.

Hay dos: el JetKVM real (`jetkvm.JetKVM`) y un Mac simulado
(`simulador.Simulador`) que recibe los MISMOS informes HID y los interpreta
como lo haría macOS. El simulador no está para fingir que todo va bien: está
para que la parte de arriba —tecleo, paginado, verificación— se pruebe
ejecutándola, y para enseñar la demo sin el aparato delante.
"""

from __future__ import annotations

import abc

from PIL import Image


class AparatoNoDisponible(RuntimeError):
    """No hay conexión con el aparato (o se perdió)."""


class Dispositivo(abc.ABC):
    tipo: str = "?"

    @abc.abstractmethod
    async def conectar(self) -> None: ...

    @abc.abstractmethod
    async def cerrar(self) -> None: ...

    @abc.abstractmethod
    async def captura(self) -> Image.Image:
        """La pantalla entera, en RGB, a la resolución que entrega el aparato."""

    @abc.abstractmethod
    async def informe_teclado(self, modificadores: int, teclas: list[int]) -> None:
        """Estado completo del teclado: qué modificadores y qué teclas están abajo."""

    @abc.abstractmethod
    async def raton(self, x: int, y: int, botones: int = 0) -> None:
        """Puntero absoluto en píxeles de la captura; `botones` 1=izq, 2=der, 4=centro."""

    @abc.abstractmethod
    async def rueda(self, pasos: int) -> None:
        """Pasos de rueda: positivo baja el contenido (como el dedo hacia ti)."""

    @abc.abstractmethod
    def estado(self) -> dict:
        """Para la pantalla: conectado, resolución y lo que haga falta saber."""
