"""Lo que el puente necesita de un aparato: ver la pantalla, teclado y ratón.

Hay dos: el JetKVM real (`jetkvm.JetKVM`) y un Mac simulado
(`simulador.Simulador`) que recibe los MISMOS informes HID y los interpreta
como lo haría macOS. El simulador no está para fingir que todo va bien: está
para que la parte de arriba —tecleo, paginado, verificación— se pruebe
ejecutándola, y para enseñar la demo sin el aparato delante.
"""

from __future__ import annotations

import abc
import asyncio
from collections.abc import Callable

from PIL import Image


class AparatoNoDisponible(RuntimeError):
    """No hay conexión con el aparato (o se perdió)."""


class Dispositivo(abc.ABC):
    tipo: str = "?"
    #: Quién oye lo que suena en el Mac: recibe PCM de 16 bits a 16 kHz, mono, y
    #: la hora de llegada. Sólo mientras se graba una reunión (`reunion.py`).
    oido: Callable[[bytes, float], None] | None = None

    @abc.abstractmethod
    async def conectar(self) -> None: ...

    @abc.abstractmethod
    async def cerrar(self) -> None: ...

    @abc.abstractmethod
    async def captura(self) -> Image.Image:
        """La pantalla entera, en RGB, a la resolución que entrega el aparato."""

    async def miniatura(self, ancho: int) -> Image.Image:
        """La pantalla reducida a `ancho` para mirarla (el directo), no para leerla.

        Por omisión, la captura reducida en otro hilo: así el bucle que atiende
        el ratón y el teclado no se para mientras se reduce. Un aparato que
        sepa reducir más barato (el JetKVM, desde el vídeo) la sustituye."""
        img = await self.captura()
        if img.width <= ancho:
            return img
        alto = round(img.height * ancho / img.width)
        return await asyncio.to_thread(img.resize, (ancho, alto), Image.BILINEAR)

    @abc.abstractmethod
    async def informe_teclado(self, modificadores: int, teclas: list[int]) -> None:
        """Estado completo del teclado: qué modificadores y qué teclas están abajo."""

    @abc.abstractmethod
    async def raton(self, x: int, y: int, botones: int = 0) -> None:
        """Puntero absoluto en píxeles de la captura; `botones` 1=izq, 2=der, 4=centro."""

    @abc.abstractmethod
    async def rueda(self, pasos: int) -> None:
        """Pasos de rueda: positivo baja el contenido (como el dedo hacia ti)."""

    async def girar(self, pasos: int) -> None:
        """La rueda de la persona (el mando): un solo giro de `pasos`, sin esperar a
        que el aparato conteste. Por omisión, la rueda de siempre."""
        await self.rueda(pasos)

    @abc.abstractmethod
    def estado(self) -> dict:
        """Para la pantalla: conectado, resolución y lo que haga falta saber."""

    # ── el sonido del Mac, para grabar una reunión (C-0461) ─────────────────
    @property
    def da_sonido(self) -> bool:
        """Si la conexión de ahora trae lo que suena en el Mac."""
        return False

    async def encender_sonido(self) -> bool:
        """Pide al aparato lo que suena en el Mac. True si hace falta reconectar
        para que llegue (el JetKVM sólo lo añade al empezar una conexión)."""
        raise AparatoNoDisponible("este aparato no da el sonido del Mac")

    async def apagar_sonido(self) -> None:
        """Que el aparato deje de capturarlo. Sin sonido que apagar, no hace nada."""

    # ── el jiggler y despertar el Mac, del propio aparato (C-0463) ──────────
    #: Lo último leído del jiggler, {"encendido", "config"}: `estado()` lo
    #: enseña sin preguntarle al aparato en cada vuelta de la pantalla.
    jiggler: dict | None = None

    async def leer_jiggler(self) -> dict:
        """{"encendido": bool, "config": {...}} tal como lo tiene guardado el aparato."""
        raise AparatoNoDisponible("este aparato no tiene jiggler")

    async def poner_jiggler(self, encendido: bool, config: dict | None = None) -> dict:
        """Lo enciende o lo apaga; con `config`, cambia antes su horario. Devuelve lo leído después."""
        raise AparatoNoDisponible("este aparato no tiene jiggler")

    async def zonas(self) -> list[str]:
        """Las zonas horarias que el aparato sabe usar para el horario del jiggler."""
        raise AparatoNoDisponible("este aparato no tiene jiggler")

    async def despertar(self, tope: float = 8.0) -> dict:
        """Manda al Mac la señal de despertar y espera, como mucho `tope` segundos,
        a que se note. {"antes", "despues": estado del USB, "imagen": llegó una nueva}."""
        raise AparatoNoDisponible("este aparato no sabe despertar al Mac")
