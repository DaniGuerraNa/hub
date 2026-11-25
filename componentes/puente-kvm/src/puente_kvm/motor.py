"""Las acciones sobre el Mac: ver, teclear, atajos, ratón y esperar.

Todo lo que toca el Mac pasa por aquí, y aquí se comprueba el control antes
de cada informe al aparato —no una vez por tarea—: si la persona pulsa
«Parar» a mitad de un tecleo, la tecla siguiente ya no sale.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from dataclasses import dataclass, field

from PIL import Image, ImageChops, ImageStat

from . import config, hid, teclados
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


def caja_cambiada(a: Image.Image, b: Image.Image) -> tuple[int, int, int, int] | None:
    """La caja (x0, y0, x1, y1; los finales, exclusivos) de los píxeles cambiados; None si ninguno.

    Por píxel y por el canal que más se mueve, no por cuadros ni por la media de
    los tres como `diferencia`: aquí no se pregunta «¿se movió algo?» sino «¿qué
    queda fuera?», y un «;» que pasa a «:» no llega a mover un cuadro de 64×32.
    """
    d = ImageChops.difference(a.convert("RGB"), b.convert("RGB"))
    r, g, v = d.split()
    return ImageChops.lighter(ImageChops.lighter(r, g), v).point(lambda x: 255 if x > UMBRAL_PIXEL else 0).getbbox()


def filas_distintas(a: Image.Image, b: Image.Image) -> list[bool]:
    """Para cada fila de píxeles, si tiene algún píxel cambiado (como `caja_cambiada`)."""
    d = ImageChops.difference(a.convert("RGB"), b.convert("RGB"))
    r, g, v = d.split()
    marca = ImageChops.lighter(ImageChops.lighter(r, g), v).point(lambda x: 255 if x > UMBRAL_PIXEL else 0)
    # En coma flotante, la media de una fila no redondea a 0 un solo píxel cambiado.
    return [m > 0 for m in marca.convert("F").resize((1, a.height), Image.BOX).get_flattened_data()]


def filas_cambiadas(a: Image.Image, b: Image.Image) -> tuple[int, int] | None:
    """La primera y la última (exclusiva) fila de píxeles con algún píxel cambiado; None si ninguno."""
    caja = caja_cambiada(a, b)
    return None if caja is None else (caja[1], caja[3])


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


# Dos capturas tan parecidas son la misma página: avanzar ya no mueve nada.
IGUAL = 0.002


def desplazamiento(antes: Image.Image, despues: Image.Image) -> int | None:
    """Cuántos píxeles subió el contenido de una zona entre dos capturas; None si no se reconoce.

    Busca el corrimiento con el que lo de abajo de `antes` coincide con lo de
    arriba de `despues`, en una copia reducida (96 px de ancho y la mitad de
    alto, de 2 en 2 px): ~30 ms en una zona de 1600×930. Sólo se da si encaja
    mucho mejor que sin moverse: una cifra que no se puede defender no se da.
    """
    if antes.size != despues.size or antes.height < 16:
        return None
    a, b = (i.convert("L").resize((96, i.height // 2)) for i in (antes, despues))
    h = a.height
    quieto = ImageStat.Stat(ImageChops.difference(a, b)).mean[0]
    if quieto < 0.5:
        return 0
    mejor, cual = None, 0
    for s in range(1, h - h // 8):  # con al menos un octavo de la zona en común
        d = ImageStat.Stat(ImageChops.difference(a.crop((0, s, 96, h)), b.crop((0, 0, 96, h - s)))).mean[0]
        if mejor is None or d < mejor:
            mejor, cual = d, s
    if mejor is None or mejor > 12 or mejor > quieto * 0.35:
        return None
    return cual * 2


@dataclass
class Recorrido:
    """Una zona de la pantalla, página a página (`Motor.recorrer`)."""
    paginas: list[Image.Image] = field(default_factory=list)
    # Cuánto subió el contenido desde la página anterior; la primera, None.
    subio: list[int | None] = field(default_factory=list)
    final: bool = False
    pasos: int = 5


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
                              intervalo: float = 0.15,
                              zona: tuple[int, int, int, int] | None = None) -> tuple[Image.Image, bool]:
        """Espera a que la pantalla deje de cambiar: devuelve la captura y si lo logró.

        Leer una pantalla a medio pintar da una transcripción a medias que
        parece buena: se pide que dos capturas seguidas coincidan. Si al
        agotar `tope` aún se mueve, devuelve la última con `False`: quien llama
        decide qué hacer, pero ya no puede no saberlo. Con `zona` (x, y, ancho,
        alto) se mira y se devuelve sólo esa parte; sin ella, la región del
        editor (o la pantalla entera, con `recortar=False`).
        """
        limite = time.monotonic() + (self.tope_estable if tope is None else tope)
        previa = None
        while True:
            img = await self.captura()
            if zona:
                x, y, w, h = zona
                img = img.crop((x, y, x + w, y + h))
            elif recortar:
                img = self.recortar(img)
            if previa is not None and diferencia_local(img, previa) < CUADRO_CAMBIADO:
                return img, True
            if time.monotonic() > limite:
                return img, False
            previa = img
            await asyncio.sleep(intervalo)

    async def paginas(self, avanzar, zona: tuple[int, int, int, int] | None = None, tope: int = 400):
        """La pantalla página a página: la de ahora y otra tras cada `avanzar()`,
        cada una ya quieta, hasta que avanzar no cambia nada (el final) o van `tope`.

        Lo comparten la lectura de un documento (Av Pág, en la región del
        editor) y el recorrido de una zona cualquiera (la rueda). Quien recibe
        menos de `tope` sabe que llegó al final.
        """
        previa, quieta = await self.esperar_estable(zona=zona)
        yield previa, quieta
        for _ in range(tope - 1):
            await avanzar()
            img, quieta = await self.esperar_estable(zona=zona)
            if diferencia(img, previa) < IGUAL:
                return
            yield img, quieta
            previa = img

    async def recorrer(self, zona: tuple[int, int, int, int], pasos: int = 5, tope: int = 10) -> Recorrido:
        """Baja una zona con la rueda hasta su final (o `tope` páginas) y la captura en cada parada.

        En la primera prueba con el aparato, recorrer una hoja así costó unas 40
        llamadas de Claude: rueda, mirar, «me pasé, vuelvo». Aquí cada bajada
        se mide y los pasos se ajustan para que suba unas tres cuartas partes de
        la zona: se solapa lo justo para no perder una fila entre dos páginas.
        """
        x, y, w, h = zona
        r = Recorrido(pasos=pasos)

        async def avanzar():
            self.progreso = f"página {len(r.paginas) + 1} de {tope} como mucho"
            await self.rueda(r.pasos, x + w // 2, y + h // 2, apuntar=False)
            await self.aparcar_raton()  # el puntero taparía lo que hay debajo

        await self.aparcar_raton()
        async for img, _ in self.paginas(avanzar, zona=zona, tope=tope):
            if r.paginas:
                s = await asyncio.to_thread(desplazamiento, r.paginas[-1], img)
                r.subio.append(s)
                if s:  # sin pasar de 4 veces arriba o abajo: una medida rara no lo dispara
                    r.pasos = max(1, min(60, round(r.pasos * max(0.25, min(4.0, 0.75 * h / s)))))
            else:
                r.subio.append(None)
            r.paginas.append(img)
        r.final = len(r.paginas) < tope
        self.bitacora.apuntar("recorrido", f"{len(r.paginas)} páginas de la zona {w}×{h} en ({x}, {y})"
                              + ("" if r.final else ", sin llegar al final"))
        return r

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

    def distribucion(self) -> hid.Distribucion:
        """La del ajuste, de serie o medida (`teclados.resolver`): una medida que ya
        no se lee es un error, no un «U.S.» que escribe otra cosa."""
        return teclados.resolver(self.perfil.get("distribucion", "mac-us"))

    def reservadas(self) -> set[hid.Pulsacion]:
        return hid.pulsaciones_reservadas(self.perfil.get("reservadas", config.PERFIL_POR_OMISION["reservadas"]))

    async def pulsar(self, pulsaciones: list[hid.Pulsacion]) -> int:
        """Pulsa estas teclas tal cual, sin pasar por ninguna distribución (el sondeo
        del teclado). Si alguna está reservada, no pulsa ninguna."""
        prohibidas = self.reservadas()
        choque = next((p for p in pulsaciones if p in prohibidas), None)
        if choque is not None:
            raise ValueError(f"{choque} está reservada en Ajustes (perfil.reservadas): no pulso nada")
        for i, p in enumerate(pulsaciones):
            await self._pulsar(p)
            if i % 50 == 0:
                self.progreso = f"tecleando {i}/{len(pulsaciones)}"
        return len(pulsaciones)

    async def teclear(self, texto: str, apuntar: bool = True,
                      distribucion: hid.Distribucion | None = None) -> int:
        """Teclea `texto` entero o nada (ver `hid.secuencia`). Devuelve pulsaciones.

        Con la distribución del ajuste, o con `distribucion` (la consulta de prueba
        de una medida se teclea con su borrador). Las teclas reservadas no se pulsan
        nunca, con una u otra.
        """
        pulsaciones = hid.secuencia(texto, distribucion or self.distribucion(), self.reservadas())
        if apuntar:
            muestra = texto if len(texto) <= 80 else texto[:77] + "…"
            self.bitacora.apuntar("teclear", f"{len(texto)} caracteres: {muestra!r}")
        return await self.pulsar(pulsaciones)

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

    async def rueda(self, pasos: int, x: int | None = None, y: int | None = None, apuntar: bool = True) -> None:
        """La rueda gira donde está el puntero: con (x, y) lo lleva ahí antes. Sin
        ella, tras aparcar el ratón la rueda caía fuera de la hoja y no movía nada
        (primera prueba con el aparato, 17-nov)."""
        self.control.comprobar()
        if x is not None and y is not None:
            await self.mover(x, y)
            await asyncio.sleep(0.06)
        await self.dispositivo.rueda(-pasos if self.perfil.get("invertir_rueda") else pasos)
        if apuntar:
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
