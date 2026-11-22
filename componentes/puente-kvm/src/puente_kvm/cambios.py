"""Escribir de vuelta en el Mac sólo lo que cambia, con el sí de la persona.

Un cambio nace de una lectura (el original, línea a línea) y de un texto
nuevo que Claude propone. Se parte en **tramos** —cada bloque de líneas que
difiere— y se escribe tramo a tramo **de abajo arriba**, para que los números
de línea de los de arriba no se muevan mientras se escribe.

Las puertas, en orden, y ninguna se salta:
1. **Aprobación en la pantalla.** Claude propone; la persona mira el diff y
   pulsa «Aprobar». Claude no puede aprobar.
2. **Todo el texto se puede teclear.** Si un carácter no tiene tecla en la
   distribución, no se escribe ni el primer tramo.
3. **El documento es el que se leyó, hasta el tramo más bajo.** Antes de
   escribir se recorre el documento desde el principio, página a página como
   al leerlo, y cada página se compara con su captura de la lectura, hasta la
   que contiene la línea más baja que se va a tocar. Si el foco está en otra
   ventana, o alguien cambió el texto por encima de esa línea (los números de
   los tramos ya no valdrían), no casa y no se escribe nada. Lo que cambie
   por debajo no mueve ningún número; eso lo dirá la huella al final.
4. **La pantalla está quieta.** Si no se queda quieta, no se compara ni se
   teclea sobre ella.
5. **Control.** Cada pulsación comprueba que la persona no ha pulsado Parar.

Escribir no es guardar: el puente deja el texto en el editor y **la persona
ejecuta** el `ALTER` o guarda. Después, la huella de la base dice si lo que
quedó guardado es exactamente lo acordado (con la misma variante con la que
se verificó la lectura).
"""

from __future__ import annotations

import difflib
import json
import re
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

from PIL import Image

from . import hid, huellas, lecturas
from .config import hogar
from .control import SinControl
from .motor import Motor, PantallaInesperada, caja_cambiada, diferencia_local

# La pantalla «es la misma» que la primera página leída si ningún cuadro
# cambia más que esto (ver `motor.diferencia_local`): una letra ya lo supera.
MISMA_PANTALLA = 0.03


@dataclass
class Tramo:
    i: int
    desde: int  # primera línea del original afectada (1 = primera)
    hasta: int  # última, inclusive; desde-1 si sólo se insertan líneas
    nuevas: list[str]
    antes: list[str]
    estado: str = "pendiente"  # pendiente, escrito, fallido
    # La captura de comprobación se tomó con la pantalla aún moviéndose.
    captura_inestable: bool = False
    # Las filas de píxeles [desde, hasta) de esa captura que cambiaron respecto de
    # justo antes de teclear el tramo, con dos filas de texto de margen: lo que
    # `ver_tramo` le enseña a Claude. [] si no cambió nada visible o apenas (quizá
    # sólo el cursor); None si no se sabe (un cambio de antes, o no se pudo
    # capturar o comparar).
    franja: list[int] | None = None


@dataclass
class Cambio:
    id: str
    lectura: str
    descripcion: str
    creado: float
    original: list[str]
    nuevo: list[str]
    tramos: list[Tramo]
    estado: str = "propuesto"  # propuesto, aprobado, rechazado, escribiendo, escrito, fallido, verificado
    error: str = ""
    aprobado_en: float | None = None
    huella_esperada: str | None = None
    huella_final: str = ""
    historial: list[dict] = field(default_factory=list)
    # La lectura de la que parte no estaba verificada con la huella al proponerlo:
    # los tramos se calcularon contra lo transcrito, que puede tener errores.
    sin_verificar: bool = False
    # Cómo calcula la base la huella, si se supo al verificar lo guardado.
    variante: dict | None = None

    @property
    def carpeta(self) -> Path:
        return carpeta_de(self.id)

    def guardar(self) -> None:
        self.carpeta.mkdir(parents=True, exist_ok=True)
        tmp = self.carpeta / "cambio.json.tmp"
        tmp.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=1))
        tmp.replace(self.carpeta / "cambio.json")
        (self.carpeta / "nuevo.txt").write_text("\n".join(self.nuevo) + "\n")

    def anotar(self, que: str, quien: str) -> None:
        self.historial.append({"t": time.time(), "que": que, "quien": quien})

    def png(self, tramo: int) -> Path:
        return self.carpeta / f"tramo-{tramo:02d}.png"


def carpeta_de(id_: str) -> Path:
    if not re.fullmatch(r"[a-z0-9-]{1,64}", id_):
        raise ValueError("identificador de cambio inválido")
    return hogar() / "cambios" / id_


def cargar(id_: str) -> Cambio:
    datos = json.loads((carpeta_de(id_) / "cambio.json").read_text())
    datos["tramos"] = [Tramo(**t) for t in datos["tramos"]]
    return Cambio(**datos)


def todos() -> list[Cambio]:
    raiz = hogar() / "cambios"
    if not raiz.exists():
        return []
    salida = []
    for d in raiz.iterdir():
        if (d / "cambio.json").exists():
            try:
                salida.append(cargar(d.name))
            except Exception:
                continue
    return sorted(salida, key=lambda c: c.creado, reverse=True)


def tramos_de(original: list[str], nuevo: list[str]) -> list[Tramo]:
    sm = difflib.SequenceMatcher(None, original, nuevo, autojunk=False)
    salida = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        salida.append(Tramo(i=len(salida) + 1, desde=i1 + 1, hasta=i2, nuevas=nuevo[j1:j2],
                            antes=original[i1:i2]))
    return salida


def proponer(lectura: lecturas.Lectura, nuevo_texto: str, descripcion: str) -> Cambio:
    ens = lecturas.ensamblar(lectura)
    if not ens.completo:
        raise ValueError("la lectura no está completa (páginas sin transcribir, huecos o conflictos)")
    nuevo = nuevo_texto.replace("\r\n", "\n").rstrip("\n").split("\n")
    tramos = tramos_de(ens.lineas, nuevo)
    if not tramos:
        raise ValueError("el texto propuesto es idéntico al leído: no hay nada que escribir")
    # Fallar aquí, no a mitad de la escritura.
    for t in tramos:
        hid.secuencia("\n".join(t.nuevas))
    base = lecturas.slug(descripcion, 30) or "cambio"
    c = Cambio(id=f"{base}-{uuid.uuid4().hex[:6]}", lectura=lectura.id, descripcion=descripcion,
               creado=time.time(), original=ens.lineas, nuevo=nuevo, tramos=tramos,
               sin_verificar=not lectura.verificada)
    if lectura.variante:
        c.huella_esperada = huellas.con_variante(nuevo, lectura.variante)
    c.anotar("propuesto", "claude")
    c.guardar()
    return c


def aprobar(c: Cambio) -> None:
    if c.estado != "propuesto":
        raise ValueError(f"sólo se aprueba un cambio propuesto (está {c.estado})")
    c.estado, c.aprobado_en = "aprobado", time.time()
    c.anotar("aprobado", "persona")
    c.guardar()


def rechazar(c: Cambio) -> None:
    if c.estado not in ("propuesto", "aprobado"):
        raise ValueError(f"no se rechaza un cambio {c.estado}")
    c.estado = "rechazado"
    c.anotar("rechazado", "persona")
    c.guardar()


# ── escribir ────────────────────────────────────────────────────────────────
def pagina_hasta(lectura: lecturas.Lectura, c: Cambio) -> int:
    """La página de la lectura que contiene la línea más baja que toca el cambio."""
    total = len(c.original)
    mas_baja = min(total, max(max(t.desde, t.hasta) for t in c.tramos))
    for pg in lectura.paginas:
        if pg.primera is not None and pg.ultima is not None and pg.primera <= mas_baja <= pg.ultima:
            return pg.n
    return len(lectura.paginas)  # sin números que lo digan: todas


async def comprobar_paginas(motor: Motor, lectura: lecturas.Lectura, hasta: int) -> None:
    """Recorre el documento como al leerlo y compara cada página con su captura."""
    perfil = motor.perfil
    await motor.atajo(perfil["inicio_documento"], apuntar=False)
    for n in range(1, hasta + 1):
        motor.progreso = f"comprobando la página {n} de {hasta} antes de escribir"
        if n > 1:
            await motor.atajo(perfil["pagina_abajo"], apuntar=False)
        ahora, quieta = await motor.esperar_estable()
        if not quieta:
            raise PantallaInesperada(
                f"la pantalla no se queda quieta (página {n}): no comparo ni escribo sobre algo "
                "que se mueve. ¿Hay algo animándose encima del editor?")
        if diferencia_local(ahora, Image.open(lectura.png(n))) > MISMA_PANTALLA:
            pg = lectura.paginas[n - 1]
            lineas = f" (líneas {pg.primera}–{pg.ultima})" if pg.primera else ""
            raise PantallaInesperada(
                f"la página {n}{lineas} no es la que se leyó: ¿otra ventana al frente, otro "
                "documento, o el texto cambió después de leerlo? No escribo nada; si cambió, "
                "hay que leerlo de nuevo.")


async def escribir(motor: Motor, c: Cambio, quien: str) -> Cambio:
    if c.estado != "aprobado":
        raise ValueError("el cambio no está aprobado: lo aprueba la persona en la pantalla del puente")
    lectura = lecturas.cargar(c.lectura)
    c.estado, c.error = "escribiendo", ""
    c.anotar("escribiendo", quien)
    c.guardar()
    try:
        await motor.aparcar_raton()
        hasta = pagina_hasta(lectura, c)
        t0 = time.monotonic()
        await comprobar_paginas(motor, lectura, hasta)
        motor.bitacora.apuntar(
            "comprobacion", f"{c.id}: las páginas 1–{hasta} son las leídas ({time.monotonic() - t0:.1f} s)",
            cambio=c.id)
        total = len(c.original)
        fila = alto_de_fila(lectura)
        for t in sorted(c.tramos, key=lambda t: t.desde, reverse=True):
            motor.progreso = f"tramo {t.i} de {len(c.tramos)}"
            ultima_actual = total + sum(len(o.nuevas) - (o.hasta - o.desde + 1)
                                        for o in c.tramos if o.desde > t.desde)
            antes = await _escribir_tramo(motor, t, ultima_actual, c.id)
            t.estado = "escrito"
            await motor.aparcar_raton()
            await motor.ir_a_linea(max(1, t.desde))
            img, quieta = await motor.esperar_estable()
            img.save(c.png(t.i))
            t.captura_inestable = not quieta
            t.franja = _franja_sin_cortar(motor, c, antes, img, fila)
            motor.bitacora.apuntar("tramo", f"{c.id}: tramo {t.i} escrito (líneas {t.desde}–{t.hasta})"
                                   + ("; su captura salió con la pantalla moviéndose" if not quieta else ""),
                                   cambio=c.id)
            c.guardar()
        c.estado = "escrito"
        c.anotar("escrito en el editor; falta que la persona lo guarde o ejecute", quien)
    except SinControl as e:
        c.estado, c.error = "fallido", f"cortado: {e}"
        c.anotar("cortado", quien)
    except PantallaInesperada as e:
        c.estado, c.error = "fallido", str(e)
        c.anotar(f"no escrito: {c.error}", quien)
        motor.bitacora.apuntar("error", c.error, cambio=c.id)
    except Exception as e:
        c.estado, c.error = "fallido", f"{type(e).__name__}: {e}"
        c.anotar(f"falló: {c.error}", quien)
        motor.bitacora.apuntar("error", c.error, cambio=c.id)
    c.guardar()
    return c


# Sin una lectura que diga cuántas líneas caben en su página, un alto de fila
# holgado: más margen sólo enseña más, nunca esconde.
FILA_POR_OMISION = 40


def alto_de_fila(lectura: lecturas.Lectura) -> int:
    """Cuántos px mide una fila del editor, por la página de la lectura con más líneas."""
    lineas = max((pg.ultima - pg.primera + 1 for pg in lectura.paginas
                  if pg.primera is not None and pg.ultima is not None and pg.ultima >= pg.primera), default=0)
    if not lineas or not lectura.paginas or not lectura.png(1).exists():
        return FILA_POR_OMISION
    with Image.open(lectura.png(1)) as img:
        return max(1, -(-img.height // lineas))


# Un cursor de texto mide 1–3 px de ancho (2 en el Mac simulado, que lo pinta).
# Si parpadea entre la captura de antes de teclear y la de después, sale como
# «lo que cambió»: una caja así de estrecha no se enseña sola, porque lo que se
# escribió puede no estar en ella. 4 deja margen al borde suavizado del vídeo.
ANCHO_CURSOR = 4


def franja(antes: Image.Image | None, despues: Image.Image, fila: int) -> list[int] | None:
    """Las filas de píxeles de `despues` que cambiaron respecto de `antes`, con dos filas de margen.

    Es lo único que `ver_tramo` le enseña a Claude (C-0474): un reemplazo de una o
    tres líneas cambia unas pocas filas, y mandarle el editor entero en cada tramo
    era pagar la pantalla completa por ellas. Las dos filas de margen son para que
    vea el número de línea y lo que tiene alrededor. Fuera de la franja, cada
    píxel está igual (por debajo de `UMBRAL_PIXEL`) que justo antes de teclear.
    Si no cambió nada o sólo una caja de la anchura de un cursor, [] (entera).
    """
    if antes is None or antes.size != despues.size:
        return None
    caja = caja_cambiada(antes, despues)
    if caja is None or caja[2] - caja[0] <= ANCHO_CURSOR:
        return []
    return [max(0, caja[1] - 2 * fila), min(despues.height, caja[3] + 2 * fila)]


def _franja_sin_cortar(motor: Motor, c: Cambio, antes: Image.Image | None, despues: Image.Image,
                       fila: int) -> list[int] | None:
    """`franja`, sin que un fallo al comparar corte la escritura: el tramo ya está tecleado
    y sólo se pierde el recorte (se enseña entero)."""
    try:
        return franja(antes, despues, fila)
    except Exception as e:
        motor.bitacora.apuntar("error", f"{c.id}: no pude comparar el tramo con lo de antes de teclearlo "
                               f"({type(e).__name__}: {e}); se enseña entero", cambio=c.id)
        return None


async def _vista(motor: Motor, cambio: str) -> Image.Image | None:
    """La región del editor tal como está, para comparar con la del tramo ya escrito.

    Una sola captura, sin esperar a que se quede quieta: aquí ya se está a punto
    de teclear, y lo que se escribe, en qué orden y con qué esperas sigue igual que
    sin ella. Si la pantalla aún se estaba pintando, la franja sale más grande, no
    más pequeña. Si no se puede capturar, se escribe igual y el tramo se enseña
    entero.
    """
    try:
        return motor.recortar(await motor.captura())
    except Exception as e:
        motor.bitacora.apuntar("error", f"{cambio}: no pude capturar antes de teclear el tramo "
                               f"({type(e).__name__}: {e}); se enseña entero", cambio=cambio)
        return None


async def _escribir_tramo(motor: Motor, t: Tramo, ultima_actual: int, cambio: str) -> Image.Image | None:
    """Teclea el tramo y devuelve la vista de justo antes de teclear (ver `franja`).

    La vista se captura ya colocado (tras «Ir a la línea» o ir al final) y antes
    de la primera tecla que cambia algo: ni la selección con Mayús+↓ ha salido aún.
    """
    p = motor.perfil
    fin = p["fin_de_linea"]
    cuantas = t.hasta - t.desde + 1
    texto = "\n".join(t.nuevas)
    if cuantas == 0:  # sólo insertar
        if t.desde <= ultima_actual:
            await motor.ir_a_linea(t.desde)
            antes = await _vista(motor, cambio)
            await motor.teclear(texto + "\n")
        else:
            await motor.atajo(p["fin_documento"])
            antes = await _vista(motor, cambio)
            await motor.teclear("\n" + texto)
        return antes
    if t.hasta < ultima_actual:
        await motor.ir_a_linea(t.desde)
        antes = await _vista(motor, cambio)
        await motor.atajo("shift+down", veces=cuantas)
        if t.nuevas:
            await motor.teclear(texto + "\n")
        else:
            await motor.atajo("backspace")
        return antes
    # El tramo llega a la última línea: Mayús+↓ ahí no baja, va al final.
    if t.nuevas:
        await motor.ir_a_linea(t.desde)
        antes = await _vista(motor, cambio)
        if cuantas > 1:
            await motor.atajo("shift+down", veces=cuantas - 1)
        await motor.atajo("shift+" + fin)
        await motor.teclear(texto)
    else:
        if t.desde == 1:
            raise RuntimeError("el cambio borra el documento entero: eso no se hace tecleando")
        await motor.ir_a_linea(t.desde - 1)
        antes = await _vista(motor, cambio)
        await motor.atajo(fin)
        await motor.atajo("shift+down", veces=cuantas)
        await motor.atajo("shift+" + fin)
        await motor.atajo("backspace")
    return antes


def comprobar_huella(c: Cambio, referencia: str) -> dict:
    c.huella_final = huellas.normalizar(referencia)
    if c.huella_esperada is None:
        # Sin variante conocida: se prueban todas, y la que case queda con el cambio.
        c.variante = huellas.buscar(c.nuevo, referencia)
        ok = c.variante is not None
    else:
        ok = c.huella_final == c.huella_esperada
    if ok:
        c.estado = "verificado"
        c.anotar("la huella de la base coincide con lo acordado", "persona")
    else:
        c.anotar("la huella de la base NO coincide", "persona")
    c.guardar()
    return {"verificado": ok}
