"""Un Mac simulado con un cliente de base de datos abierto en un procedimiento.

Recibe los mismos informes HID que recibiría el Mac por el JetKVM y los
interpreta como macOS con SU fuente de entrada —«U.S.» si no se dice otra,
incluidas las teclas muertas de Option para á, ñ, ü—. Esa fuente es del Mac
simulado, no del ajuste del puente (C-0481): como en el de verdad, la elige
quien usa el Mac. Si siguiera al ajuste, nunca se podría probar un puente que
teclea con una distribución distinta de la del Mac, que es lo que mide
`teclados.py`. Pinta una pantalla de 1920×1080 con la misma pinta que
tendría un cliente en «modo captura»: Menlo —aquí DejaVu Sans Mono, de la que
Menlo deriva—, fondo blanco, números de línea y barra de estado.

Lo que imita a propósito, porque en el Mac de verdad también pasa:
- el puntero del ratón se pinta encima del texto y tapa letras;
- Av Pág avanza una página y en la última se queda quieto;
- «Ir a la línea» es un diálogo (Cmd+L, como DBeaver);
- lo escrito en el editor no está en la base hasta que alguien guarda
  (Cmd+S): la huella de la base sólo cambia entonces.

Lo que NO imita: autocompletado, cierre automático de paréntesis y sangría
automática. En el Mac de verdad hay que apagarlos (ver el README).
"""

from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from . import hid, jiggler, muestras
from .dispositivo import Dispositivo

ANCHO, ALTO = 1920, 1080
# Las zonas del Mac simulado (el JetKVM da las de su tzdata, unas 600).
ZONAS = ("UTC", "America/Mexico_City", "America/Bogota", "America/Lima", "America/Santiago",
         "America/Argentina/Buenos_Aires", "Europe/Madrid")

# Dónde suele estar cada fuente según el sistema (Debian/Ubuntu, Fedora, Arch, macOS).
_MONO = ("/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
         "/usr/share/fonts/dejavu-sans-mono-fonts/DejaVuSansMono.ttf",
         "/usr/share/fonts/TTF/DejaVuSansMono.ttf",
         "/System/Library/Fonts/Menlo.ttc")
_UI = ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
       "/usr/share/fonts/dejavu-sans-fonts/DejaVuSans.ttf",
       "/usr/share/fonts/TTF/DejaVuSans.ttf",
       "/System/Library/Fonts/Helvetica.ttc")
# El metapaquete existe en Ubuntu 22.04 y 24.04; `fonts-dejavu-mono` sólo en 24.04 y apt,
# si falta uno de los nombres, no instala ninguno.
ARREGLO_FUENTES = "sudo apt install fonts-dejavu"


def buscar_fuente(candidatas: tuple[str, ...]) -> str | None:
    return next((r for r in candidatas if Path(r).exists()), None)


FUENTE_MONO = buscar_fuente(_MONO)
FUENTE_UI = buscar_fuente(_UI)

# Geometría de la ventana (píxeles de pantalla).
BARRA_MENU = 28
TITULO = (BARRA_MENU, 64)
PESTANAS = (64, 98)
EDITOR_Y0, EDITOR_Y1 = 98, 1050
NAVEGADOR_X1 = 300
GUTTER_X0, GUTTER_X1 = NAVEGADOR_X1, NAVEGADOR_X1 + 76
TEXTO_X0 = GUTTER_X1 + 14
ESTADO_Y0 = 1050

# La región que una persona marcaría en Ajustes: el editor con su columna de
# números, sin el navegador ni la barra de estado.
REGION_EDITOR = (GUTTER_X0, EDITOR_Y0, ANCHO - GUTTER_X0, EDITOR_Y1 - EDITOR_Y0)

TAM_FUENTE = 20
ALTO_LINEA = 26


def _fuente(ruta: str | None, tam: int) -> ImageFont.FreeTypeFont:
    # Sin la fuente, el simulador arranca igual con la de Pillow (no es
    # monoespaciada: el texto se lee, pero los clics caen algo desplazados).
    # Que el servicio no arranque por una fuente sería peor; `comprobar` lo dice.
    return ImageFont.truetype(ruta, tam) if ruta else ImageFont.load_default(tam)


# Del informe HID al carácter, como lo haría macOS con la fuente de entrada
# del Mac simulado: (Shift/Option, tecla) → carácter, las teclas muertas → su
# acento, y (acento, letra) → la letra compuesta.
_BITS = hid.SHIFT | hid.ALT


def _tablas(fuente: hid.Distribucion) -> tuple[dict, dict, dict]:
    # El ASCII primero: si dos caracteres comparten tecla, la tecla da el primero.
    orden = [chr(i) for i in range(32, 127)] + [c for c in fuente.tabla if not " " <= c <= "~"]
    pasos = {c: hid.caracter(c, fuente) for c in orden}
    caracter: dict[tuple[int, int], str] = {}
    for c, p in pasos.items():
        if p and len(p) == 1:
            caracter.setdefault((p[0].modificadores & _BITS, p[0].tecla), c)
    caracter[(0, hid.TECLAS["space"])] = " "
    muerta = {(m, hid.TECLAS[t]): acento for (m, t), acento in fuente.muertas.items()}
    componer: dict[tuple[str, str], str] = {}
    for c, p in pasos.items():
        if p and len(p) == 2 and p[1].tecla != hid.TECLAS["space"]:
            acento = muerta.get((p[0].modificadores & _BITS, p[0].tecla))
            letra = caracter.get((p[1].modificadores & _BITS, p[1].tecla))
            if acento and letra:
                componer[(acento, letra)] = c
    return caracter, muerta, componer


def fuente_del_mac(fuente: str | hid.Distribucion) -> hid.Distribucion:
    """Una de serie por su id, o una tabla cualquiera (las pruebas montan Macs con
    fuentes que el puente no tiene). Un id desconocido es un error: caer a «U.S.»
    haría pasar una prueba que no prueba lo que dice."""
    return fuente if isinstance(fuente, hid.Distribucion) else hid.de_serie(fuente)


@dataclass
class EditorSimulado:
    """El estado del editor: texto, cursor, selección, vista y diálogo."""

    lineas: list[str]
    filas: int
    columnas: int
    cursor: tuple[int, int] = (0, 0)
    ancla: tuple[int, int] | None = None
    arriba: int = 0
    izquierda: int = 0
    dialogo: str | None = None  # texto del «Ir a la línea» si está abierto
    muerta: str | None = None
    fuente: hid.Distribucion = hid.MAC_US  # la fuente de entrada del Mac simulado
    version: int = 0
    guardado: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.poner_fuente(self.fuente)

    def poner_fuente(self, fuente: str | hid.Distribucion) -> None:
        """Cambia la fuente de entrada del Mac simulado, como Ctrl+Espacio en el de verdad."""
        self.fuente = fuente_del_mac(fuente)
        self._tablas = _tablas(self.fuente)
        self.muerta = None

    # ── utilidades ──────────────────────────────────────────────────────────
    def _ajustar_vista(self) -> None:
        f, c = self.cursor
        if f < self.arriba:
            self.arriba = f
        elif f >= self.arriba + self.filas:
            self.arriba = f - self.filas + 1
        self.arriba = max(0, min(self.arriba, max(0, len(self.lineas) - self.filas)))
        if c < self.izquierda:
            self.izquierda = c
        elif c > self.izquierda + self.columnas - 2:
            self.izquierda = c - self.columnas + 2

    def _mover(self, f: int, c: int, extender: bool) -> None:
        f = max(0, min(f, len(self.lineas) - 1))
        c = max(0, min(c, len(self.lineas[f])))
        if extender:
            if self.ancla is None:
                self.ancla = self.cursor
        else:
            self.ancla = None
        self.cursor = (f, c)
        self._ajustar_vista()

    def seleccion(self) -> tuple[tuple[int, int], tuple[int, int]] | None:
        if self.ancla is None or self.ancla == self.cursor:
            return None
        return tuple(sorted([self.ancla, self.cursor]))  # type: ignore[return-value]

    def _borrar_seleccion(self) -> bool:
        sel = self.seleccion()
        if not sel:
            self.ancla = None
            return False
        (f0, c0), (f1, c1) = sel
        self.lineas[f0:f1 + 1] = [self.lineas[f0][:c0] + self.lineas[f1][c1:]]
        self.cursor = (f0, c0)
        self.ancla = None
        return True

    def _insertar(self, texto: str) -> None:
        self._borrar_seleccion()
        f, c = self.cursor
        actual = self.lineas[f]
        partes = (actual[:c] + texto + actual[c:]).split("\n")
        self.lineas[f:f + 1] = partes
        ultima = f + len(partes) - 1
        self.cursor = (ultima, len(partes[-1]) - len(actual[c:]))
        self._ajustar_vista()

    # ── teclas ──────────────────────────────────────────────────────────────
    def tecla(self, mods: int, codigo: int) -> None:
        self.version += 1
        cmd = bool(mods & (hid.GUI | hid.GUI_DER))
        shift = bool(mods & (hid.SHIFT | hid.SHIFT_DER))
        alt = bool(mods & (hid.ALT | hid.ALT_DER))
        T = hid.TECLAS
        f, c = self.cursor

        if self.dialogo is not None:
            self._tecla_dialogo(mods, codigo)
            return

        if cmd:
            if codigo == T["up"]:
                self._mover(0, 0, shift)
            elif codigo == T["down"]:
                self._mover(len(self.lineas) - 1, len(self.lineas[-1]), shift)
            elif codigo == T["left"]:
                self._mover(f, 0, shift)
            elif codigo == T["right"]:
                self._mover(f, len(self.lineas[f]), shift)
            elif codigo == T["l"]:
                self.dialogo = ""
            elif codigo == T["a"]:
                self.ancla = (0, 0)
                self.cursor = (len(self.lineas) - 1, len(self.lineas[-1]))
            elif codigo == T["s"]:
                self.guardar()
            return

        if codigo == T["up"]:
            self._mover(f - 1, c, shift)
        elif codigo == T["down"]:
            if f == len(self.lineas) - 1:
                self._mover(f, len(self.lineas[f]), shift)
            else:
                self._mover(f + 1, c, shift)
        elif codigo == T["left"]:
            if c > 0:
                self._mover(f, c - 1, shift)
            elif f > 0:
                self._mover(f - 1, len(self.lineas[f - 1]), shift)
        elif codigo == T["right"]:
            if c < len(self.lineas[f]):
                self._mover(f, c + 1, shift)
            elif f < len(self.lineas) - 1:
                self._mover(f + 1, 0, shift)
        elif codigo == T["home"]:
            self._mover(f, 0, shift)
        elif codigo == T["end"]:
            self._mover(f, len(self.lineas[f]), shift)
        elif codigo in (T["pagedown"], T["pageup"]):
            paso = self.filas if codigo == T["pagedown"] else -self.filas
            tope = max(0, len(self.lineas) - self.filas)
            self.arriba = max(0, min(self.arriba + paso, tope))
            nf = max(0, min(f + paso, len(self.lineas) - 1))
            if not shift:
                self.ancla = None
            elif self.ancla is None:
                self.ancla = self.cursor
            self.cursor = (nf, min(c, len(self.lineas[nf])))
        elif codigo == T["enter"]:
            self._insertar("\n")
        elif codigo == T["tab"]:
            self._insertar("\t")
        elif codigo == T["backspace"]:
            if not self._borrar_seleccion():
                if c > 0:
                    self.lineas[f] = self.lineas[f][:c - 1] + self.lineas[f][c:]
                    self.cursor = (f, c - 1)
                elif f > 0:
                    previa = self.lineas[f - 1]
                    self.lineas[f - 1:f + 1] = [previa + self.lineas[f]]
                    self.cursor = (f - 1, len(previa))
            self._ajustar_vista()
        elif codigo == T["delete"]:
            if not self._borrar_seleccion():
                if c < len(self.lineas[f]):
                    self.lineas[f] = self.lineas[f][:c] + self.lineas[f][c + 1:]
                elif f < len(self.lineas) - 1:
                    self.lineas[f:f + 2] = [self.lineas[f] + self.lineas[f + 1]]
            self._ajustar_vista()
        elif codigo == T["escape"]:
            self.ancla = None
            self.muerta = None
        else:
            self._caracter(mods, codigo, shift, alt)

    def _caracter(self, mods: int, codigo: int, shift: bool, alt: bool) -> None:
        caracteres, muertas, componer = self._tablas
        bits = (hid.SHIFT if shift else 0) | (hid.ALT if alt else 0)
        if (bits, codigo) in muertas:
            self.muerta = muertas[(bits, codigo)]
            return
        car = caracteres.get((bits, codigo))
        if car is None:
            return
        if self.muerta:
            compuesto = componer.get((self.muerta, car))
            # macOS: con espacio, el acento suelto; si no casan, el acento y la letra.
            car = compuesto if compuesto else self.muerta if car == " " else self.muerta + car
            self.muerta = None
        self._insertar(car)

    def _tecla_dialogo(self, mods: int, codigo: int) -> None:
        T = hid.TECLAS
        if codigo == T["escape"]:
            self.dialogo = None
        elif codigo == T["enter"]:
            if self.dialogo and self.dialogo.isdigit():
                destino = max(1, min(int(self.dialogo), len(self.lineas))) - 1
                self.ancla = None
                self.cursor = (destino, 0)
                if not (self.arriba <= destino < self.arriba + self.filas):
                    self.arriba = destino - self.filas // 3
                self._ajustar_vista()
            self.dialogo = None
        elif codigo == T["backspace"]:
            self.dialogo = self.dialogo[:-1] if self.dialogo else ""
        else:
            car = self._tablas[0].get((0, codigo))
            if car and car.isdigit() and len(self.dialogo or "") < 6:
                self.dialogo = (self.dialogo or "") + car

    # ── la «base de datos» ──────────────────────────────────────────────────
    def guardar(self) -> None:
        self.guardado = list(self.lineas)
        self.version += 1

    @property
    def modificado(self) -> bool:
        return self.lineas != self.guardado


def huella_sqlserver(lineas: list[str]) -> str:
    """Lo que daría HASHBYTES('SHA2_256', OBJECT_DEFINITION(...)): UTF-16LE y CRLF."""
    return hashlib.sha256("\r\n".join(lineas).encode("utf-16-le")).hexdigest().upper()


class Simulador(Dispositivo):
    tipo = "simulador"

    def __init__(self, lineas: list[str] | None = None, fuente: str | hid.Distribucion = "mac-us"):
        self._mono = _fuente(FUENTE_MONO, TAM_FUENTE)
        self._ui = _fuente(FUENTE_UI, 15)
        self._ui_peq = _fuente(FUENTE_UI, 13)
        self.ancho_car = self._mono.getlength("M")
        filas = (EDITOR_Y1 - EDITOR_Y0 - 8) // ALTO_LINEA
        columnas = int((ANCHO - TEXTO_X0 - 10) // self.ancho_car)
        texto = list(lineas) if lineas is not None else muestras.procedimiento()
        self.editor = EditorSimulado(lineas=list(texto), filas=filas, columnas=columnas,
                                     guardado=list(texto), fuente=fuente_del_mac(fuente))
        self._pulsadas: set[int] = set()
        self._botones = 0
        self.puntero = (1500, 600)
        self._cache: tuple[tuple, Image.Image] | None = None
        self.conectado = False
        self.informes = 0
        self.pulsaciones = 0  # teclas que bajaron: soltarlo todo no cuenta
        # El Mac simulado no suena: con el sonido encendido, lo que llega es lo que
        # las pruebas le hagan sonar (`sonar`), como el JetKVM, que en silencio no manda nada.
        self.sonido = False
        # El jiggler del Mac simulado, como viene el JetKVM: apagado y con «Estándar».
        self._jiggler = {"encendido": False, "config": dict(jiggler.PREAJUSTES["estandar"][1])}
        self.jiggler = dict(self._jiggler)
        # Dormido no cambia la pantalla (las pruebas leen igual); sólo lo que
        # dice el USB, que es lo que mira `despertar`.
        self.dormido = False
        self.despertado = 0

    # ── Dispositivo ─────────────────────────────────────────────────────────
    async def conectar(self) -> None:
        self.conectado = True

    async def cerrar(self) -> None:
        self.conectado = False

    @property
    def da_sonido(self) -> bool:
        return self.sonido

    async def encender_sonido(self) -> bool:
        self.sonido = True
        return False

    async def apagar_sonido(self) -> None:
        self.sonido = False

    async def leer_jiggler(self) -> dict:
        self.jiggler = {"encendido": self._jiggler["encendido"], "config": dict(self._jiggler["config"])}
        return self.jiggler

    async def poner_jiggler(self, encendido: bool, config: dict | None = None) -> dict:
        if config is not None:
            self._jiggler["config"] = dict(config)
        self._jiggler["encendido"] = bool(encendido)
        return await self.leer_jiggler()

    async def zonas(self) -> list[str]:
        return list(ZONAS)

    async def despertar(self, tope: float = 8.0) -> dict:
        if not self.dormido:
            return {"antes": "configured", "despues": "configured", "imagen": True, "ya_despierto": True}
        self.dormido = False
        self.despertado += 1
        return {"antes": "suspended", "despues": "configured", "imagen": True}

    def sonar(self, pcm: bytes, t: float) -> None:
        """Lo que suena en el Mac simulado: llega a quien lo oiga, si el sonido está encendido."""
        if self.sonido and self.oido is not None:
            self.oido(pcm, t)

    async def informe_teclado(self, modificadores: int, teclas: list[int]) -> None:
        self.informes += 1
        nuevas = [t for t in teclas if t and t not in self._pulsadas]
        self._pulsadas = {t for t in teclas if t}
        for t in nuevas:
            self.pulsaciones += 1
            self.editor.tecla(modificadores, t)
        await asyncio.sleep(0)

    async def raton(self, x: int, y: int, botones: int = 0) -> None:
        self.puntero = (max(0, min(x, ANCHO - 1)), max(0, min(y, ALTO - 1)))
        if botones & 1 and not self._botones & 1:
            self._clic(*self.puntero)
        self._botones = botones
        self.editor.version += 1

    async def rueda(self, pasos: int) -> None:
        e = self.editor
        e.arriba = max(0, min(e.arriba + 3 * pasos, max(0, len(e.lineas) - e.filas)))
        e.version += 1

    async def captura(self) -> Image.Image:
        clave = (self.editor.version, self.puntero)
        if self._cache and self._cache[0] == clave:
            return self._cache[1].copy()
        img = self._pintar()
        self._cache = (clave, img)
        return img.copy()

    def estado(self) -> dict:
        e = self.editor
        return {
            "tipo": self.tipo, "conectado": self.conectado,
            "resolucion": f"{ANCHO}×{ALTO}", "ancho": ANCHO, "alto": ALTO,
            "lineas": len(e.lineas), "modificado": e.modificado,
            "huella_base": huella_sqlserver(e.guardado), "jiggler": self.jiggler,
            # Dormido sólo cambia lo que dice el USB (ver `dormido`): conectado sigue.
            "mac": ("reposo" if self.dormido else "despierto") if self.conectado else None,
            "senal": "ok" if self.conectado else None,
            "nota": "Mac simulado: cliente de BD con un procedimiento de muestra"
                    + ("" if FUENTE_MONO else f". Falta la fuente monoespaciada ({ARREGLO_FUENTES})"),
        }

    # ── ratón ───────────────────────────────────────────────────────────────
    def _clic(self, x: int, y: int) -> None:
        e = self.editor
        if TEXTO_X0 <= x < ANCHO and EDITOR_Y0 + 4 <= y < EDITOR_Y1:
            f = e.arriba + (y - EDITOR_Y0 - 4) // ALTO_LINEA
            c = e.izquierda + round((x - TEXTO_X0) / self.ancho_car)
            e._mover(f, c, False)

    # ── pintar ──────────────────────────────────────────────────────────────
    def _pintar(self) -> Image.Image:
        e = self.editor
        img = Image.new("RGB", (ANCHO, ALTO), "#ffffff")
        d = ImageDraw.Draw(img)
        # Barra de menús de macOS.
        d.rectangle([0, 0, ANCHO, BARRA_MENU], fill="#ececec")
        x = 18
        d.text((x, 6), "", font=self._ui, fill="#000")
        for nombre in ["ClienteBD", "Archivo", "Editar", "Navegar", "Buscar", "Editor SQL",
                       "Base de datos", "Ventana", "Ayuda"]:
            d.text((x + 22, 5), nombre, font=self._ui, fill="#111")
            x += int(self._ui.getlength(nombre)) + 26
        d.text((ANCHO - 170, 5), "lun 9 nov  11:40", font=self._ui, fill="#111")
        # Título de la ventana.
        d.rectangle([0, TITULO[0], ANCHO, TITULO[1]], fill="#e3e3e3")
        for i, color in enumerate(["#ff5f57", "#febc2e", "#28c840"]):
            cx = 22 + i * 22
            d.ellipse([cx - 7, 46 - 7, cx + 7, 46 + 7], fill=color)
        titulo = "dbo.usp_ConciliarMovimientos — SQLSERVER-01 · Contabilidad"
        d.text(((ANCHO - self._ui.getlength(titulo)) / 2, 37), titulo, font=self._ui, fill="#333")
        # Navegador de objetos.
        d.rectangle([0, TITULO[1], NAVEGADOR_X1, ESTADO_Y0], fill="#f4f4f4")
        d.line([NAVEGADOR_X1, TITULO[1], NAVEGADOR_X1, ESTADO_Y0], fill="#d0d0d0")
        arbol = ["▾ SQLSERVER-01", "  ▾ Contabilidad", "    ▸ Tablas", "    ▸ Vistas",
                 "    ▾ Procedimientos", "        dbo.usp_CerrarPeriodo",
                 "      ▸ dbo.usp_ConciliarMovimientos", "        dbo.usp_GenerarPolizas",
                 "        dbo.usp_ReabrirPeriodo", "    ▸ Funciones"]
        for i, t in enumerate(arbol):
            y = TITULO[1] + 14 + i * 24
            if "Conciliar" in t:
                d.rectangle([4, y - 3, NAVEGADOR_X1 - 4, y + 19], fill="#dbe7fb")
            d.text((12, y), t, font=self._ui_peq, fill="#222")
        # Pestaña.
        d.rectangle([NAVEGADOR_X1 + 1, PESTANAS[0], ANCHO, PESTANAS[1]], fill="#efefef")
        nombre = ("• " if e.modificado else "") + "usp_ConciliarMovimientos"
        d.rectangle([NAVEGADOR_X1 + 8, PESTANAS[0] + 4, NAVEGADOR_X1 + 300, PESTANAS[1]], fill="#ffffff")
        d.text((NAVEGADOR_X1 + 20, PESTANAS[0] + 9), nombre, font=self._ui, fill="#111")
        d.line([NAVEGADOR_X1, PESTANAS[1], ANCHO, PESTANAS[1]], fill="#d0d0d0")
        # Columna de números.
        d.rectangle([GUTTER_X0 + 1, EDITOR_Y0 + 1, GUTTER_X1, EDITOR_Y1], fill="#f6f6f6")
        sel = e.seleccion()
        for i in range(e.filas):
            n = e.arriba + i
            if n >= len(e.lineas):
                break
            y = EDITOR_Y0 + 4 + i * ALTO_LINEA
            num = str(n + 1)
            d.text((GUTTER_X1 - 8 - self._mono.getlength(num), y), num, font=self._mono, fill="#7a7a7a")
            visible = e.lineas[n].replace("\t", "    ")
            tramo = visible[e.izquierda:e.izquierda + e.columnas]
            if sel:
                (f0, c0), (f1, c1) = sel
                if f0 <= n <= f1:
                    a = c0 if n == f0 else 0
                    b = c1 if n == f1 else len(visible) + 1
                    a, b = max(a - e.izquierda, 0), max(b - e.izquierda, 0)
                    if b > a:
                        d.rectangle([TEXTO_X0 + a * self.ancho_car, y - 2,
                                     TEXTO_X0 + b * self.ancho_car, y + ALTO_LINEA - 4], fill="#b3d7ff")
            d.text((TEXTO_X0, y), tramo, font=self._mono, fill="#000000")
            if n == e.cursor[0] and e.dialogo is None:
                cx = TEXTO_X0 + (e.cursor[1] - e.izquierda) * self.ancho_car
                d.rectangle([cx - 1, y - 2, cx, y + ALTO_LINEA - 5], fill="#000")
        # Barra de estado.
        d.rectangle([0, ESTADO_Y0, ANCHO, ALTO], fill="#e9e9e9")
        d.line([0, ESTADO_Y0, ANCHO, ESTADO_Y0], fill="#cfcfcf")
        estado = (f"Ln {e.cursor[0] + 1}, Col {e.cursor[1] + 1}     {len(e.lineas)} líneas"
                  "     UTF-8     CRLF     Insertar")
        d.text((NAVEGADOR_X1 + 12, ESTADO_Y0 + 6), estado, font=self._ui_peq, fill="#222")
        d.text((12, ESTADO_Y0 + 6), "SQLSERVER-01 · Contabilidad", font=self._ui_peq, fill="#555")
        if e.dialogo is not None:
            self._pintar_dialogo(d, e)
        self._pintar_puntero(d)
        return img

    def _pintar_dialogo(self, d: ImageDraw.ImageDraw, e: EditorSimulado) -> None:
        x0, y0, x1, y1 = ANCHO // 2 - 220, 300, ANCHO // 2 + 220, 430
        d.rectangle([x0, y0, x1, y1], fill="#f2f2f2", outline="#9a9a9a")
        d.text((x0 + 20, y0 + 16), "Ir a la línea", font=self._ui, fill="#000")
        d.text((x0 + 20, y0 + 44), f"Número de línea (1..{len(e.lineas)}):", font=self._ui_peq, fill="#333")
        d.rectangle([x0 + 20, y0 + 70, x1 - 20, y0 + 100], fill="#fff", outline="#5b8def")
        d.text((x0 + 28, y0 + 75), e.dialogo or "", font=self._mono, fill="#000")

    def _pintar_puntero(self, d: ImageDraw.ImageDraw) -> None:
        x, y = self.puntero
        flecha = [(x, y), (x, y + 22), (x + 6, y + 17), (x + 10, y + 26), (x + 14, y + 24),
                  (x + 10, y + 16), (x + 17, y + 16)]
        d.polygon(flecha, fill="#000", outline="#fff")
