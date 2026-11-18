"""Las acciones sobre el Mac: ver, teclear, atajos, ratón y esperar.

Todo lo que toca el Mac pasa por aquí, y aquí se comprueba el control antes
de cada informe al aparato —no una vez por tarea—: si la persona pulsa
«Parar» a mitad de un tecleo, la tecla siguiente ya no sale.
"""

from __future__ import annotations

import asyncio
import contextlib
import time

from PIL import Image, ImageChops

from . import hid
from .control import Bitacora, Control
from .dispositivo import Dispositivo

# Un píxel «cambia» si algún canal se mueve más que esto. El vídeo del JetKVM
# llega comprimido (H.264) y dos fotogramas de la misma pantalla no son
# idénticos byte a byte; el umbral absorbe ese ruido sin tragarse una letra.
UMBRAL_PIXEL = 40


def diferencia(a: Image.Image, b: Image.Image) -> float:
    """Fracción de píxeles que cambian entre dos imágenes del mismo tamaño."""
    if a.size != b.size:
        return 1.0
    d = ImageChops.difference(a.convert("RGB"), b.convert("RGB")).convert("L")
    cambiados = sum(d.point(lambda v: 255 if v > UMBRAL_PIXEL else 0).histogram()[255:])
    return cambiados / (a.size[0] * a.size[1])


# Cuadros para comparar por zonas. Una letra cambiada son ~80 píxeles: en la
# pantalla entera es un 0,005 %, invisible en una media; en su cuadro de
# 64×32 es más del 4 %. El cursor parpadeando (2×22 px) se queda en el 2 %.
CUADRO = (64, 32)


def _por_cuadros(a: Image.Image, b: Image.Image) -> Image.Image:
    """Cada cuadro de 64×32, con la fracción de sus píxeles que cambian (0–255)."""
    d = ImageChops.difference(a.convert("RGB"), b.convert("RGB")).convert("L")
    marca = d.point(lambda v: 255 if v > UMBRAL_PIXEL else 0)
    w, h = max(1, a.size[0] // CUADRO[0]), max(1, a.size[1] // CUADRO[1])
    return marca.resize((w, h), Image.BOX)


def diferencia_local(a: Image.Image, b: Image.Image) -> float:
    """La mayor fracción de píxeles cambiados en un cuadro: ¿cambió algo, aunque sea poco?"""
    if a.size != b.size:
        return 1.0
    return _por_cuadros(a, b).getextrema()[1] / 255


# Un cuadro «cambió» si cambia más de esto, lo mismo que para decir que una
# pantalla está quieta (el cursor parpadeando se queda por debajo).
CUADRO_CAMBIADO = 0.03


def cuadros_cambiados(a: Image.Image, b: Image.Image) -> int:
    """Cuántos cuadros de 64×32 cambian: el tamaño de lo que apareció."""
    if a.size != b.size:
        return 10**6
    umbral = round(CUADRO_CAMBIADO * 255)
    return sum(_por_cuadros(a, b).point(lambda v: 255 if v > umbral else 0).histogram()[255:])


# Para dar por abierto el diálogo de «Ir a la línea» tienen que cambiar al
# menos estos cuadros. El del simulador (440×130 px) cambia ~30; el reloj de
# la barra de menús, al pasar el minuto, uno o dos. Sin medir con el diálogo
# de un cliente real: si el suyo es más pequeño, el puente falla sin teclear,
# que es el lado seguro.
CUADROS_DIALOGO = 4


class Ocupado(RuntimeError):
    """Ya hay una tarea en marcha sobre el Mac."""


class PantallaInesperada(RuntimeError):
    """La pantalla no está como hace falta para teclear sin riesgo: no se teclea."""


class Motor:
    def __init__(self, dispositivo: Dispositivo, control: Control, bitacora: Bitacora, perfil: dict):
        self.dispositivo = dispositivo
        self.control = control
        self.bitacora = bitacora
        self.perfil = perfil
        self._cerrojo = asyncio.Lock()
        self.tarea: str | None = None
        self.progreso: str = ""
        # Cuánto se espera, como mucho, a que la pantalla se quede quieta.
        self.tope_estable = 4.0

    # ── una tarea a la vez ──────────────────────────────────────────────────
    @contextlib.asynccontextmanager
    async def ocupar(self, tarea: str):
        if self._cerrojo.locked():
            raise Ocupado(f"ya estoy con: {self.tarea}")
        async with self._cerrojo:
            self.tarea, self.progreso = tarea, ""
            try:
                yield
            finally:
                self.tarea, self.progreso = None, ""
                with contextlib.suppress(Exception):
                    await self.dispositivo.informe_teclado(0, [])

    # ── ver ─────────────────────────────────────────────────────────────────
    async def captura(self) -> Image.Image:
        return await self.dispositivo.captura()

    def recortar(self, img: Image.Image) -> Image.Image:
        x, y, w, h = self.perfil["region_editor"]
        return img.crop((x, y, x + w, y + h))

    async def esperar_estable(self, recortar: bool = True, tope: float | None = None,
                              intervalo: float = 0.15) -> tuple[Image.Image, bool]:
        """Espera a que la pantalla deje de cambiar: devuelve la captura y si lo logró.

        Leer una pantalla a medio pintar da una transcripción a medias que
        parece buena: se pide que dos capturas seguidas coincidan. Si al
        agotar `tope` aún se mueve, devuelve la última con `False`: quien llama
        decide qué hacer, pero ya no puede no saberlo.
        """
        limite = time.monotonic() + (self.tope_estable if tope is None else tope)
        previa = None
        while True:
            img = await self.captura()
            if recortar:
                img = self.recortar(img)
            if previa is not None and diferencia_local(img, previa) < CUADRO_CAMBIADO:
                return img, True
            if time.monotonic() > limite:
                return img, False
            previa = img
            await asyncio.sleep(intervalo)

    async def esperar_cambio(self, antes: Image.Image, cuadros: int, tope: float = 2.0,
                             intervalo: float = 0.1) -> Image.Image | None:
        """Espera a que en la pantalla entera aparezca algo de al menos `cuadros`
        cuadros respecto de `antes`, y a que se quede quieto. None si no aparece."""
        limite = time.monotonic() + tope
        while time.monotonic() <= limite:
            img = await self.captura()
            if cuadros_cambiados(antes, img) >= cuadros:
                quieta, estable = await self.esperar_estable(recortar=False, tope=1.5)
                if estable and cuadros_cambiados(antes, quieta) >= cuadros:
                    return quieta
            await asyncio.sleep(intervalo)
        return None

    # ── teclado ─────────────────────────────────────────────────────────────
    async def _pulsar(self, p: hid.Pulsacion) -> None:
        retardo = self.perfil.get("retardo_tecla_ms", 12) / 1000
        self.control.comprobar()
        await self.dispositivo.informe_teclado(p.modificadores, [p.tecla])
        await asyncio.sleep(retardo)
        await self.dispositivo.informe_teclado(0, [])
        await asyncio.sleep(retardo)

    async def atajo(self, atajo: str, veces: int = 1, apuntar: bool = True) -> None:
        p = hid.combinacion(atajo)
        for _ in range(veces):
            await self._pulsar(p)
        if apuntar:
            self.bitacora.apuntar("atajo", atajo + (f" ×{veces}" if veces > 1 else ""))

    async def teclear(self, texto: str, apuntar: bool = True) -> int:
        """Teclea `texto` entero o nada (ver `hid.secuencia`). Devuelve pulsaciones."""
        pulsaciones = hid.secuencia(texto, self.perfil.get("distribucion", "mac-us"))
        if apuntar:
            muestra = texto if len(texto) <= 80 else texto[:77] + "…"
            self.bitacora.apuntar("teclear", f"{len(texto)} caracteres: {muestra!r}")
        for i, p in enumerate(pulsaciones):
            await self._pulsar(p)
            if i % 50 == 0:
                self.progreso = f"tecleando {i}/{len(pulsaciones)}"
        return len(pulsaciones)

    # ── ratón ───────────────────────────────────────────────────────────────
    async def mover(self, x: int, y: int) -> None:
        self.control.comprobar()
        await self.dispositivo.raton(x, y, 0)

    async def clic(self, x: int, y: int, boton: str = "izquierdo", doble: bool = False) -> None:
        bits = {"izquierdo": 1, "derecho": 2, "centro": 4}[boton]
        self.control.comprobar()
        await self.dispositivo.raton(x, y, 0)
        for _ in range(2 if doble else 1):
            await self.dispositivo.raton(x, y, bits)
            await asyncio.sleep(0.04)
            await self.dispositivo.raton(x, y, 0)
            await asyncio.sleep(0.06)
        self.bitacora.apuntar("clic", f"{boton}{' doble' if doble else ''} en ({x}, {y})")

    async def rueda(self, pasos: int, x: int | None = None, y: int | None = None) -> None:
        """La rueda gira donde está el puntero: con (x, y) lo lleva ahí antes. Sin
        ella, tras aparcar el ratón la rueda caía fuera de la hoja y no movía nada
        (primera prueba con el aparato, 17-nov)."""
        self.control.comprobar()
        if x is not None and y is not None:
            await self.mover(x, y)
            await asyncio.sleep(0.06)
        await self.dispositivo.rueda(-pasos if self.perfil.get("invertir_rueda") else pasos)
        self.bitacora.apuntar("rueda", f"{pasos:+d}" + (f" en ({x}, {y})" if x is not None and y is not None else ""))

    async def aparcar_raton(self) -> None:
        """El puntero se pinta encima del texto y tapa letras: fuera del editor."""
        x, y = self.perfil["aparcar_raton"]
        await self.mover(x, y)

    async def ir_a_linea(self, n: int) -> None:
        """Abre «Ir a la línea», comprueba EN PANTALLA que se abrió y teclea el número.

        Con una espera fija, si el diálogo no llegaba a abrirse, el número y el
        Enter acababan dentro del documento.
        """
        atajo = self.perfil["ir_a_linea"]
        antes = await self.captura()
        await self.atajo(atajo, apuntar=False)
        if await self.esperar_cambio(antes, CUADROS_DIALOGO) is None:
            self.bitacora.apuntar("error", f"ir a la línea {n}: {atajo} no abrió nada en la pantalla")
            raise PantallaInesperada(
                f"pulsé {atajo} para ir a la línea {n} y no se abrió nada en la pantalla: no tecleo "
                "el número, que iría al documento. ¿Es ése el atajo de este programa (Ajustes) y "
                "tiene el foco el editor?")
        await self.teclear(str(n), apuntar=False)
        await self.atajo("enter", apuntar=False)
        await asyncio.sleep(0.15)
        self.bitacora.apuntar("ir_a_linea", str(n))
