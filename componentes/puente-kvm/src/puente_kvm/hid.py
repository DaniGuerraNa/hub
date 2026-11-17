"""Del texto y los atajos a informes de teclado USB (HID, página 0x07).

El JetKVM no envía caracteres: envía códigos de tecla, y el Mac los convierte
en caracteres según SU distribución activa. Por eso la tabla de aquí tiene que
casar con la fuente de entrada del Mac mientras Claude teclea. La única que
se soporta es **«U.S.» de macOS** (`mac-us`): en la española, `{ } [ ] | \\ ~`
necesitan Option y cambian según el modelo de teclado, y adivinarlas es
escribir otro carácter sin que nadie se entere.

Todo el texto se traduce ANTES de pulsar nada: si un carácter no tiene
traducción, no se escribe ni el primero (escribir medio fragmento es peor que
no escribirlo).
"""

from __future__ import annotations

from dataclasses import dataclass

# Bits del byte de modificadores del informe de teclado.
CTRL = 0x01
SHIFT = 0x02
ALT = 0x04  # «Option» en el Mac
GUI = 0x08  # «Command» en el Mac
CTRL_DER = 0x10
SHIFT_DER = 0x20
ALT_DER = 0x40
GUI_DER = 0x80

MODIFICADORES = {
    "cmd": GUI, "command": GUI, "gui": GUI, "meta": GUI, "super": GUI,
    "ctrl": CTRL, "control": CTRL,
    "alt": ALT, "option": ALT, "opt": ALT,
    "shift": SHIFT, "mayus": SHIFT,
}

TECLAS: dict[str, int] = {}
for _i, _c in enumerate("abcdefghijklmnopqrstuvwxyz"):
    TECLAS[_c] = 0x04 + _i
for _i, _c in enumerate("1234567890"):
    TECLAS[_c] = 0x1E + _i
TECLAS.update({
    "enter": 0x28, "return": 0x28, "intro": 0x28,
    "escape": 0x29, "esc": 0x29,
    "backspace": 0x2A, "borrar": 0x2A,
    "tab": 0x2B,
    "space": 0x2C, "espacio": 0x2C,
    "-": 0x2D, "=": 0x2E, "[": 0x2F, "]": 0x30, "\\": 0x31,
    ";": 0x33, "'": 0x34, "`": 0x35, ",": 0x36, ".": 0x37, "/": 0x38,
    "capslock": 0x39,
    "home": 0x4A, "inicio": 0x4A,
    "pageup": 0x4B, "repag": 0x4B,
    "delete": 0x4C, "supr": 0x4C,
    "end": 0x4D, "fin": 0x4D,
    "pagedown": 0x4E, "avpag": 0x4E,
    "right": 0x4F, "derecha": 0x4F,
    "left": 0x50, "izquierda": 0x50,
    "down": 0x51, "abajo": 0x51,
    "up": 0x52, "arriba": 0x52,
})
for _i in range(12):
    TECLAS[f"f{_i + 1}"] = 0x3A + _i

NOMBRE_DE_TECLA = {}
for _n, _c in TECLAS.items():
    NOMBRE_DE_TECLA.setdefault(_c, _n)

# Lo que en U.S. sale con Shift sobre otra tecla.
_CON_SHIFT_US = {
    "!": "1", "@": "2", "#": "3", "$": "4", "%": "5", "^": "6", "&": "7",
    "*": "8", "(": "9", ")": "0", "_": "-", "+": "=", "{": "[", "}": "]",
    "|": "\\", ":": ";", '"': "'", "~": "`", "<": ",", ">": ".", "?": "/",
}

# macOS «U.S.»: Option + tecla compone un acento que se aplica a la siguiente
# letra (tecla muerta). Es como se escriben á, ñ o ü sin cambiar de fuente.
_MUERTAS_MAC_US = {
    "´": "e",  # agudo
    "˜": "n",  # tilde
    "¨": "u",  # diéresis
    "`": "`",  # grave
    "ˆ": "i",  # circunflejo
}
_COMPUESTAS_MAC_US = {
    "á": ("´", "a"), "é": ("´", "e"), "í": ("´", "i"), "ó": ("´", "o"), "ú": ("´", "u"),
    "Á": ("´", "A"), "É": ("´", "E"), "Í": ("´", "I"), "Ó": ("´", "O"), "Ú": ("´", "U"),
    "ñ": ("˜", "n"), "Ñ": ("˜", "N"),
    "ü": ("¨", "u"), "Ü": ("¨", "U"),
    "à": ("`", "a"), "è": ("`", "e"), "ò": ("`", "o"),
}
# Option (y Shift) directos, sin tecla muerta.
_OPTION_MAC_US = {
    "¡": (ALT, "1"), "¿": (ALT | SHIFT, "/"), "º": (ALT, "0"), "ª": (ALT, "9"),
    "€": (ALT | SHIFT, "2"), "°": (ALT | SHIFT, "8"), "…": (ALT, ";"),
    "«": (ALT, "\\"), "»": (ALT | SHIFT, "\\"),
}

DISTRIBUCIONES = ("mac-us",)


class TextoIntraducible(ValueError):
    """Hay caracteres que la distribución no sabe teclear; no se escribe nada."""

    def __init__(self, caracteres: list[str]):
        self.caracteres = caracteres
        legibles = ", ".join(repr(c) for c in caracteres)
        super().__init__(f"no sé teclear estos caracteres: {legibles}")


@dataclass(frozen=True)
class Pulsacion:
    """Una tecla pulsada y soltada con unos modificadores mantenidos."""

    modificadores: int
    tecla: int

    def __str__(self) -> str:
        partes = [n for n, b in (("cmd", GUI), ("ctrl", CTRL), ("alt", ALT), ("shift", SHIFT))
                  if self.modificadores & b]
        partes.append(NOMBRE_DE_TECLA.get(self.tecla, hex(self.tecla)))
        return "+".join(partes)


def _simple_us(c: str) -> Pulsacion | None:
    if c == "\n":
        return Pulsacion(0, TECLAS["enter"])
    if c == "\t":
        return Pulsacion(0, TECLAS["tab"])
    if c == " ":
        return Pulsacion(0, TECLAS["space"])
    if c in TECLAS and len(c) == 1:
        return Pulsacion(0, TECLAS[c])
    if "A" <= c <= "Z":
        return Pulsacion(SHIFT, TECLAS[c.lower()])
    if c in _CON_SHIFT_US:
        return Pulsacion(SHIFT, TECLAS[_CON_SHIFT_US[c]])
    return None


def caracter(c: str, distribucion: str = "mac-us") -> list[Pulsacion] | None:
    """Las pulsaciones que producen `c`, o None si no se sabe."""
    if distribucion != "mac-us":
        raise ValueError(f"distribución desconocida: {distribucion}")
    simple = _simple_us(c)
    if simple:
        return [simple]
    if c in _OPTION_MAC_US:
        mods, base = _OPTION_MAC_US[c]
        return [Pulsacion(mods, TECLAS[base])]
    if c in _COMPUESTAS_MAC_US:
        acento, letra = _COMPUESTAS_MAC_US[c]
        return [Pulsacion(ALT, TECLAS[_MUERTAS_MAC_US[acento]]), *_simple_lista(letra)]
    return None


def _simple_lista(c: str) -> list[Pulsacion]:
    p = _simple_us(c)
    assert p is not None
    return [p]


def secuencia(texto: str, distribucion: str = "mac-us") -> list[Pulsacion]:
    """Todo el texto como pulsaciones; si falta alguna, no devuelve ninguna."""
    texto = texto.replace("\r\n", "\n")
    salida: list[Pulsacion] = []
    faltan: list[str] = []
    for c in texto:
        p = caracter(c, distribucion)
        if p is None:
            if c not in faltan:
                faltan.append(c)
        else:
            salida.extend(p)
    if faltan:
        raise TextoIntraducible(faltan)
    return salida


def combinacion(atajo: str) -> Pulsacion:
    """«cmd+shift+down» → una Pulsacion. Los nombres van en minúsculas."""
    partes = [p.strip().lower() for p in atajo.replace(" ", "").split("+") if p.strip()]
    if not partes:
        raise ValueError("atajo vacío")
    *mods, tecla = partes
    bits = 0
    for m in mods:
        if m not in MODIFICADORES:
            raise ValueError(f"modificador desconocido: {m}")
        bits |= MODIFICADORES[m]
    if tecla in MODIFICADORES:
        raise ValueError(f"falta la tecla en «{atajo}»")
    if tecla not in TECLAS:
        raise ValueError(f"tecla desconocida: {tecla}")
    return Pulsacion(bits, TECLAS[tecla])
