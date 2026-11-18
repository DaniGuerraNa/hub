"""Del texto y los atajos a informes de teclado USB (HID, página 0x07).

El JetKVM no envía caracteres: envía códigos de tecla, y el Mac los convierte
en caracteres según SU distribución activa. Por eso la tabla de aquí tiene que
casar con la fuente de entrada del Mac mientras Claude teclea. Hay dos:
**«U.S.» de macOS** (`mac-us`) y **«Español - ISO» de macOS** (`mac-es`).

🔴 La española no se escribió a mano: sale de la distribución de Apple
(un `.keylayout` exportado con Ukelele, convertido con un guion), porque
adivinar dónde están `{ } [ ] | \\ ~ @` es escribir otro carácter sin que nadie
se entere. Supone que el Mac tomó el teclado del JetKVM como **ANSI** (lo que
se elige en el asistente de teclado): con ISO, macOS intercambia dos teclas y
`< >` saldrían como `º ª`. La prueba de tecleo de `primera-conexion` lo caza.
La latinoamericana no está: no hay una copia fiable de la de Apple, y no se
adivina.

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
    "iso": 0x64,  # la de al lado de Mayús izquierda en ISO (`< >` en «Español - ISO»)
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

# macOS «Español - ISO», generada de la de Apple (ver arriba). Cada carácter,
# sus pulsaciones: las teclas muertas (` ´ ^ ¨ ~) van seguidas de la letra, o
# de un espacio para el acento suelto.
_MAC_ES: dict[str, tuple[tuple[int, str], ...]] = {
    '!': ((SHIFT, '1'),), '"': ((SHIFT, '2'),), '#': ((ALT, '3'),),
    '$': ((SHIFT, '4'),), '%': ((SHIFT, '5'),), '&': ((SHIFT, '6'),),
    "'": ((0, '-'),), '(': ((SHIFT, '8'),), ')': ((SHIFT, '9'),),
    '*': ((SHIFT, ']'),), '+': ((0, ']'),), ',': ((0, ','),),
    '-': ((0, '/'),), '.': ((0, '.'),), '/': ((SHIFT, '7'),),
    '0': ((0, '0'),), '1': ((0, '1'),), '2': ((0, '2'),),
    '3': ((0, '3'),), '4': ((0, '4'),), '5': ((0, '5'),),
    '6': ((0, '6'),), '7': ((0, '7'),), '8': ((0, '8'),),
    '9': ((0, '9'),), ':': ((SHIFT, '.'),), ';': ((SHIFT, ','),),
    '<': ((0, '`'),), '=': ((SHIFT, '0'),), '>': ((SHIFT, '`'),),
    '?': ((SHIFT, '-'),), '@': ((ALT, '2'),), 'A': ((SHIFT, 'a'),),
    'B': ((SHIFT, 'b'),), 'C': ((SHIFT, 'c'),), 'D': ((SHIFT, 'd'),),
    'E': ((SHIFT, 'e'),), 'F': ((SHIFT, 'f'),), 'G': ((SHIFT, 'g'),),
    'H': ((SHIFT, 'h'),), 'I': ((SHIFT, 'i'),), 'J': ((SHIFT, 'j'),),
    'K': ((SHIFT, 'k'),), 'L': ((SHIFT, 'l'),), 'M': ((SHIFT, 'm'),),
    'N': ((SHIFT, 'n'),), 'O': ((SHIFT, 'o'),), 'P': ((SHIFT, 'p'),),
    'Q': ((SHIFT, 'q'),), 'R': ((SHIFT, 'r'),), 'S': ((SHIFT, 's'),),
    'T': ((SHIFT, 't'),), 'U': ((SHIFT, 'u'),), 'V': ((SHIFT, 'v'),),
    'W': ((SHIFT, 'w'),), 'X': ((SHIFT, 'x'),), 'Y': ((SHIFT, 'y'),),
    'Z': ((SHIFT, 'z'),), '[': ((ALT, '['),), '\\': ((ALT, 'iso'),),
    ']': ((ALT, ']'),), '^': ((SHIFT, '['), (0, 'space'),), '_': ((SHIFT, '/'),),
    '`': ((0, '['), (0, 'space'),), 'a': ((0, 'a'),), 'b': ((0, 'b'),),
    'c': ((0, 'c'),), 'd': ((0, 'd'),), 'e': ((0, 'e'),),
    'f': ((0, 'f'),), 'g': ((0, 'g'),), 'h': ((0, 'h'),),
    'i': ((0, 'i'),), 'j': ((0, 'j'),), 'k': ((0, 'k'),),
    'l': ((0, 'l'),), 'm': ((0, 'm'),), 'n': ((0, 'n'),),
    'o': ((0, 'o'),), 'p': ((0, 'p'),), 'q': ((0, 'q'),),
    'r': ((0, 'r'),), 's': ((0, 's'),), 't': ((0, 't'),),
    'u': ((0, 'u'),), 'v': ((0, 'v'),), 'w': ((0, 'w'),),
    'x': ((0, 'x'),), 'y': ((0, 'y'),), 'z': ((0, 'z'),),
    '{': ((ALT, "'"),), '|': ((ALT, '1'),), '}': ((ALT, '\\'),),
    '~': ((ALT, ';'), (0, 'space'),), '¡': ((0, '='),), '¢': ((ALT, '4'),),
    '£': ((ALT | SHIFT, '4'),), '¥': ((ALT, 'y'),), '§': ((ALT, 'k'),),
    '¨': ((SHIFT, "'"), (0, 'space'),), '©': ((ALT, 'c'),), 'ª': ((SHIFT, 'iso'),),
    '«': ((ALT | SHIFT, "'"),), '¬': ((ALT, '6'),), '®': ((ALT, 'r'),),
    '¯': ((ALT | SHIFT, 'j'),), '°': ((ALT | SHIFT, 'iso'),), '±': ((ALT | SHIFT, ']'),),
    '´': ((ALT, '-'),), 'µ': ((ALT, 'm'),), '¶': ((ALT, 'j'),),
    '·': ((SHIFT, '3'),), '¸': ((ALT | SHIFT, '-'),), 'º': ((0, 'iso'),),
    '¿': ((SHIFT, '='),), 'À': ((0, '['), (SHIFT, 'a'),), 'Á': ((0, "'"), (SHIFT, 'a'),),
    'Â': ((SHIFT, '['), (SHIFT, 'a'),), 'Ã': ((ALT, ';'), (SHIFT, 'a'),), 'Ä': ((SHIFT, "'"), (SHIFT, 'a'),),
    'Å': ((ALT | SHIFT, 'a'),), 'Æ': ((ALT | SHIFT, 'w'),), 'Ç': ((SHIFT, '\\'),),
    'È': ((0, '['), (SHIFT, 'e'),), 'É': ((0, "'"), (SHIFT, 'e'),), 'Ê': ((SHIFT, '['), (SHIFT, 'e'),),
    'Ë': ((SHIFT, "'"), (SHIFT, 'e'),), 'Ì': ((0, '['), (SHIFT, 'i'),), 'Í': ((0, "'"), (SHIFT, 'i'),),
    'Î': ((SHIFT, '['), (SHIFT, 'i'),), 'Ï': ((SHIFT, "'"), (SHIFT, 'i'),), 'Ñ': ((SHIFT, ';'),),
    'Ò': ((0, '['), (SHIFT, 'o'),), 'Ó': ((0, "'"), (SHIFT, 'o'),), 'Ô': ((SHIFT, '['), (SHIFT, 'o'),),
    'Õ': ((ALT, ';'), (SHIFT, 'o'),), 'Ö': ((SHIFT, "'"), (SHIFT, 'o'),), 'Ø': ((ALT | SHIFT, 'o'),),
    'Ù': ((0, '['), (SHIFT, 'u'),), 'Ú': ((0, "'"), (SHIFT, 'u'),), 'Û': ((SHIFT, '['), (SHIFT, 'u'),),
    'Ü': ((SHIFT, "'"), (SHIFT, 'u'),), 'ß': ((ALT, 'b'),), 'à': ((0, '['), (0, 'a'),),
    'á': ((0, "'"), (0, 'a'),), 'â': ((SHIFT, '['), (0, 'a'),), 'ã': ((ALT, ';'), (0, 'a'),),
    'ä': ((SHIFT, "'"), (0, 'a'),), 'å': ((ALT, 'a'),), 'æ': ((ALT, 'w'),),
    'ç': ((0, '\\'),), 'è': ((0, '['), (0, 'e'),), 'é': ((0, "'"), (0, 'e'),),
    'ê': ((SHIFT, '['), (0, 'e'),), 'ë': ((SHIFT, "'"), (0, 'e'),), 'ì': ((0, '['), (0, 'i'),),
    'í': ((0, "'"), (0, 'i'),), 'î': ((SHIFT, '['), (0, 'i'),), 'ï': ((SHIFT, "'"), (0, 'i'),),
    'ñ': ((0, ';'),), 'ò': ((0, '['), (0, 'o'),), 'ó': ((0, "'"), (0, 'o'),),
    'ô': ((SHIFT, '['), (0, 'o'),), 'õ': ((ALT, ';'), (0, 'o'),), 'ö': ((SHIFT, "'"), (0, 'o'),),
    '÷': ((ALT, '7'),), 'ø': ((ALT, 'o'),), 'ù': ((0, '['), (0, 'u'),),
    'ú': ((0, "'"), (0, 'u'),), 'û': ((SHIFT, '['), (0, 'u'),), 'ü': ((SHIFT, "'"), (0, 'u'),),
    'ÿ': ((SHIFT, "'"), (0, 'y'),), 'ı': ((ALT | SHIFT, '1'),), 'Œ': ((ALT | SHIFT, 'q'),),
    'œ': ((ALT, 'q'),), 'Ÿ': ((SHIFT, "'"), (SHIFT, 'y'),), 'ƒ': ((ALT, 'f'),),
    'ˆ': ((ALT | SHIFT, '['),), 'ˇ': ((ALT | SHIFT, 'k'),), '˘': ((ALT | SHIFT, 'l'),),
    '˙': ((ALT | SHIFT, 'n'),), '˚': ((ALT | SHIFT, 'm'),), '˛': ((ALT | SHIFT, '='),),
    '˜': ((ALT | SHIFT, ';'),), '˝': ((ALT | SHIFT, '2'),), 'Ω': ((ALT, 'z'),),
    'π': ((ALT, 'p'),), '–': ((ALT, '/'),), '—': ((ALT | SHIFT, '/'),),
    '‘': ((ALT | SHIFT, '8'),), '’': ((ALT | SHIFT, '9'),), '‚': ((ALT, '='),),
    '“': ((ALT, '8'),), '”': ((ALT, '9'),), '„': ((ALT, ','),),
    '†': ((ALT, 't'),), '‡': ((ALT | SHIFT, 't'),), '•': ((ALT | SHIFT, '3'),),
    '…': ((ALT, '.'),), '‰': ((ALT | SHIFT, '5'),), '‹': ((ALT | SHIFT, 'z'),),
    '›': ((ALT | SHIFT, 'x'),), '⁄': ((ALT | SHIFT, '7'),), '€': ((ALT, 'e'),),
    '™': ((ALT, 'h'),), '∂': ((ALT, 'd'),), '∆': ((ALT | SHIFT, 'd'),),
    '∏': ((ALT | SHIFT, 'p'),), '∑': ((ALT, 'x'),), '√': ((ALT, 'v'),),
    '∞': ((ALT, '5'),), '∫': ((ALT, 's'),), '≈': ((ALT | SHIFT, '0'),),
    '≠': ((ALT, '0'),), '≤': ((ALT, '`'),), '≥': ((ALT | SHIFT, '`'),),
    '◊': ((ALT | SHIFT, 'v'),), 'ﬁ': ((ALT | SHIFT, 'f'),), 'ﬂ': ((ALT | SHIFT, 'g'),),
}

# Sus teclas muertas y el acento que dejan (los «terminadores» de la de Apple).
_MUERTAS_MAC_ES = {(0, "["): "`", (0, "'"): "´", (SHIFT, "["): "^", (SHIFT, "'"): "¨", (ALT, ";"): "~"}

DISTRIBUCIONES = ("mac-us", "mac-es")
NOMBRES_DISTRIBUCION = {"mac-us": "macOS «U.S.»", "mac-es": "macOS «Español - ISO»"}


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


def _blanco(c: str) -> Pulsacion | None:
    return {"\n": Pulsacion(0, TECLAS["enter"]), "\t": Pulsacion(0, TECLAS["tab"]),
            " ": Pulsacion(0, TECLAS["space"])}.get(c)


def caracter(c: str, distribucion: str = "mac-us") -> list[Pulsacion] | None:
    """Las pulsaciones que producen `c`, o None si no se sabe."""
    if distribucion == "mac-es":
        blanco = _blanco(c)
        if blanco:
            return [blanco]
        pasos = _MAC_ES.get(c)
        return [Pulsacion(m, TECLAS[t]) for m, t in pasos] if pasos else None
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
