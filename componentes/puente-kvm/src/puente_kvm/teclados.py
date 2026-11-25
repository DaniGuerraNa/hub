"""Distribuciones de teclado medidas en el propio Mac (C-0481).

El puente teclea códigos de tecla, y el Mac los convierte en caracteres con
su fuente de entrada. Para las que el puente no trae de serie (la
latinoamericana de Apple, de la que no hay copia fiable), no se adivina: se
mide en ese Mac, sin tocar su configuración. En dos partes, y ninguna pide un
programa concreto (C-0482):

**Medir, en un texto plano** (TextEdit, por ejemplo):

1. **Sondear** (`sondeo`): el puente pulsa cada tecla que escribe, en cuatro
   capas (nada, Mayús, Opción, Mayús+Opción), una línea por tecla y capa, con
   su número delante: un texto plano no numera las líneas.
2. **Leer**: Claude lee esas líneas de la pantalla (`leer_documento`, con la
   zona de esa ventana).
3. **Medir** (`construir`): de lo leído sale un borrador de tabla.

**Comprobar, en el programa donde la persona escribe sus consultas:**

4. **Probar** (`consulta`): el puente teclea con el borrador una consulta que
   calcula, fila a fila, la huella de lo que de verdad llegó al editor. La
   ejecuta la persona; Claude nunca ejecuta. Así se comprueba también que ese
   programa no cambia lo tecleado.
5. **Comprobar** (`comprobar`): se comparan esas huellas con las que calcula
   el puente (`huellas.py`). Sólo lo que coincide queda verificado.

Una medida se puede elegir en Ajustes sólo con **todo el ASCII imprimible
verificado**; y aun elegida, sólo teclea los caracteres verificados. Lo que se
vio en la pantalla pero no pasó por una huella no cuenta: «se ve bien» no es
exacto.

Las medidas viven en `PUENTE_HOME/teclados/<id>.json`, una por archivo: son de
ese Mac y no viajan en el repositorio. Este módulo es el único que las lee y
las escribe.
"""

from __future__ import annotations

import itertools
import json
import re
import time
import unicodedata
from pathlib import Path

from . import hid, huellas
from .config import hogar

# Las teclas que escriben: letras y dígitos (0x04–0x27), la puntuación de la
# fila de arriba y de la derecha (0x2D–0x31 y 0x33–0x38) y la ISO de al lado de
# Mayús izquierda (0x64). Ni la 0x2C (espacio, que es el mismo en todas) ni la
# 0x32 (la «# ~» de los teclados ISO de PC, que el teclado del Mac no tiene).
TECLAS_SONDEO = (*range(0x04, 0x28), *range(0x2D, 0x32), *range(0x33, 0x39), 0x64)
CAPAS = (0, hid.SHIFT, hid.ALT, hid.SHIFT | hid.ALT)
NOMBRES_CAPA = {0: "sin nada", hid.SHIFT: "Mayús", hid.ALT: "Opción", hid.SHIFT | hid.ALT: "Mayús+Opción"}
LINEAS_SONDEO = len(TECLAS_SONDEO) * len(CAPAS)

# La tecla con la que se enmarca cada línea del sondeo: la de la «x», que es
# una letra en todas las distribuciones latinas (QWERTY, QWERTZ y AZERTY la
# tienen en el mismo sitio) y nunca es muerta.
MARCO = hid.Pulsacion(0, hid.TECLAS["x"])
ESPACIO = hid.Pulsacion(0, hid.TECLAS["space"])
ENTER = hid.Pulsacion(0, hid.TECLAS["enter"])

# El número que lleva delante cada línea del sondeo (C-0482): tres cifras y un
# espacio, `007 xg x`. Un texto plano no tiene margen numerado, y sin número
# dos páginas que se solapan no se pueden casar (hay muchas líneas `x x`
# iguales). Las cifras van por código de tecla, sin modificador: en U.S.,
# Español y la latinoamericana dan cifras; donde no (la francesa del Mac),
# `construir` lo dice en vez de medir corrido.
CIFRAS = {str(d): hid.Pulsacion(0, hid.TECLAS[str(d)]) for d in range(10)}
PREFIJO = re.compile(r"(\d{3}) (.*)\Z", re.S)

ID_MEDIDA = re.compile(r"medida-\d{8}-\d{4}(-\d{1,3})?")
MESES = ("ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic")

# Lo que a la vista se confunde. Si la huella de su fila no coincide, se
# prueban las otras del grupo: la huella decide, no los ojos.
DUDOSOS = (("^", "ˆ"), ("~", "˜"), ("´", "'", "’"), ("º", "°"), ("-", "–", "—"))
_ALTERNATIVAS = {c: grupo for grupo in DUDOSOS for c in grupo}
TOPE_COMBINACIONES = 4096

# El acento que deja una tecla muerta y la marca con que compone su letra.
# Con ella se DEDUCE el compuesto (muerta + «a» → «á», por NFC); lo deducido no
# se da por bueno hasta que pasa por la huella.
COMBINANTES = {
    "´": "́", "'": "́", "`": "̀", "^": "̂", "ˆ": "̂", "~": "̃",
    "˜": "̃", "¨": "̈", "\"": "̈", "¸": "̧", "˚": "̊", "ˇ": "̌",
    "¯": "̄", "˘": "̆", "˙": "̇", "˝": "̋", "˛": "̨",
}

ASCII_IMPRIMIBLE = tuple(chr(i) for i in range(33, 127))
POR_FILA = 9  # 8–10 caracteres: un fallo cae en pocos, y la consulta no se alarga

# Cómo saca cada motor la huella de un texto literal. La codificación es la
# del tipo de la columna (NVARCHAR en SQL Server es UTF-16LE), y la consulta
# devuelve sólo 16 cifras hex: 64 bits bastan para distinguir, y son menos que
# leer de la rejilla.
MOTORES = {
    "SQL Server": {
        "codificacion": "utf-16-le",
        "literal": "N'{}'",
        "consulta": ("SELECT n, LEN(t) AS largo, CONVERT(VARCHAR(16), HASHBYTES('SHA2_256', t), 2) AS huella\n"
                     "FROM (VALUES\n{filas}\n) AS v(n, t)\nORDER BY n;"),
    },
    "PostgreSQL": {
        "codificacion": "utf-8",
        "literal": "'{}'",
        "consulta": ("SELECT n, length(t) AS largo, upper(left(encode(sha256(convert_to(t, 'UTF8')), 'hex'), 16)) "
                     "AS huella\nFROM (VALUES\n{filas}\n) AS v(n, t)\nORDER BY n;"),
    },
}

# Lo que un cliente de BD (DBeaver, por ejemplo) toma por variables o parámetros: `${x}`,
# `:x` y `?`. Dentro de un literal no deberían contar, pero con un borrador sin
# verificar la comilla puede salir mal, y entonces lo de después ya no está
# dentro de un literal: el cliente pediría valores en vez de ejecutar. Por eso
# `$` y `:` sólo van al final de su fila (les sigue la comilla de cierre), y
# `?` sólo cuando la comilla ya está verificada.
_AL_FINAL = ("$", ":", "?")


def carpeta() -> Path:
    return hogar() / "teclados"


# ── sondear ─────────────────────────────────────────────────────────────────
def sondeo(reservadas=()) -> list[hid.Pulsacion]:
    """Las pulsaciones del sondeo: una línea por tecla y capa, en el orden de
    `CAPAS` y `TECLAS_SONDEO`, cada una con su número delante (`PREFIJO`).

    Cada línea es su número, un espacio, `x`, la tecla, un espacio y `x`. Con
    eso se distinguen las tres cosas que puede hacer una tecla sin adivinar:
    - **normal**: deja su carácter y el espacio → `xK x`;
    - **muerta**: se come el espacio y deja su acento suelto → `x´x`;
    - **vacía** (no escribe nada) → `x x`.
    Las `x` de los bordes protegen lo que hay dentro: un espacio al principio o
    al final de una línea no se ve en una captura, y la lectura los quita.

    Una pulsación reservada (en DBeaver, Opción+X ejecuta el script) no se pulsa:
    su línea sale vacía y esa tecla no se usa nunca.
    """
    prohibidas = hid.pulsaciones_reservadas(reservadas)
    salida: list[hid.Pulsacion] = []
    for n, (capa, tecla) in enumerate(itertools.product(CAPAS, TECLAS_SONDEO), start=1):
        if salida:
            salida.append(ENTER)
        salida += [CIFRAS[c] for c in f"{n:03d}"]
        salida += [ESPACIO, MARCO]
        p = hid.Pulsacion(capa, tecla)
        if p not in prohibidas:
            salida.append(p)
        salida += [ESPACIO, MARCO]
    return salida


def _clave(m: int, tecla: str) -> str:
    return str(hid.Pulsacion(m, hid.TECLAS[tecla]))


def _donde(i: int) -> str:
    capa, tecla = CAPAS[i // len(TECLAS_SONDEO)], TECLAS_SONDEO[i % len(TECLAS_SONDEO)]
    return f"línea {i + 1} (tecla «{hid.NOMBRE_DE_TECLA[tecla]}» de U.S., capa {NOMBRES_CAPA[capa]})"


# ── medir ───────────────────────────────────────────────────────────────────
def _sin_numero(lineas: list[str]) -> list[str]:
    """Quita el número de delante de cada línea, comprobando que van 001, 002…

    Un número fuera de su sitio es una línea que falta o sobra en la
    transcripción: todas las de después quedarían de otra tecla. Sin número en
    la primera, es el formato de antes (C-0481); con algo que no son cifras,
    es que en ese teclado la fila de números no da cifras sin modificador.
    """
    if PREFIJO.match(lineas[0]) is None:
        if re.match(r"\S{3} \S", lineas[0]):
            raise ValueError(f"la línea 1 empieza por «{lineas[0][:3]}» y debería ser «001»: en este teclado la "
                             "fila de números no da cifras sin Mayús, y así no se puede medir en un texto plano. "
                             "¿Está bien transcrita?")
        return lineas
    salida = []
    for i, linea in enumerate(lineas):
        m = PREFIJO.match(linea)
        if m is None:
            raise ValueError(f"la {_donde(i)} no lleva su número delante y la primera sí: {linea!r}. "
                             "Corrígela con resolver_linea y vuelve a medir.")
        if int(m[1]) != i + 1:
            raise ValueError(f"la línea {i + 1} lleva el número {m[1]}: antes de ella falta o sobra una línea "
                             "(¿se saltó o se repitió al transcribir?). Corrígelo con resolver_linea.")
        salida.append(m[2])
    return salida


def _sin_comillas_tipograficas(crudas: list) -> None:
    """Con las comillas tipográficas encendidas, el editor cambia `'` por `’` y
    `"` por `”` al teclearlas: el borrador se quedaría sin ellas y ni siquiera
    se podría teclear el literal de la consulta de prueba."""
    todo = "".join(c[3] for c in crudas)
    if ("'" not in todo or '"' not in todo) and any(q in todo for q in "‘’“”"):
        raise ValueError("ninguna tecla da «'» o «\"», y salen comillas tipográficas (’ ”): el editor las cambia "
                         "al teclear. Apaga las comillas inteligentes (en TextEdit: Edición → Sustituciones), "
                         "borra el texto y vuelve a sondear.")


def construir(lineas: list[str] | str, nombre: str) -> dict:
    """Lo leído del sondeo → un borrador de medida, sin guardar.

    Rechaza un sondeo con líneas de menos (una tecla sin su línea correría
    todas las demás de sitio), uno tecleado con Bloq Mayús (la capa sin nada
    no da `a-z`: todo lo medido sería de otra capa) y uno tecleado con las
    comillas tipográficas encendidas. Acepta las líneas con su número delante
    (`007 xg x`) o, como las medidas de antes de C-0482, sin él; nunca mezcladas.
    """
    if isinstance(lineas, str):
        lineas = lineas.replace("\r\n", "\n").split("\n")
    lineas = list(lineas)
    while lineas and not lineas[-1].strip():
        lineas.pop()
    if len(lineas) != LINEAS_SONDEO:
        falta = "faltan" if len(lineas) < LINEAS_SONDEO else "sobran"
        raise ValueError(f"el sondeo tiene {len(lineas)} líneas y son {LINEAS_SONDEO}: {falta} "
                         "(¿se cortó el tecleo, o la lectura no llegó al final?). Vuelve a sondear en un "
                         "texto vacío.")
    lineas = _sin_numero(lineas)
    nombre = " ".join(str(nombre).split())[:60]
    if not nombre:
        raise ValueError("falta el nombre de la medida (p. ej. «Latinoamericano»)")
    marco = lineas[0][:1]
    crudas = []
    for i, linea in enumerate(lineas):
        if len(linea) < 2 or linea[0] != marco or linea[-1] != marco:
            raise ValueError(f"la {_donde(i)} no empieza y acaba con «{marco}»: {linea!r}. ¿Está bien "
                             "transcrita? Corrígela con resolver_linea y vuelve a medir.")
        dentro = linea[1:-1]
        if dentro.endswith(" "):
            tipo, salida = ("normal", dentro[:-1]) if dentro[:-1] else ("vacia", "")
        else:
            tipo, salida = "muerta", dentro
        capa, tecla = CAPAS[i // len(TECLAS_SONDEO)], TECLAS_SONDEO[i % len(TECLAS_SONDEO)]
        crudas.append([capa, hid.NOMBRE_DE_TECLA[tecla], tipo, salida])
    letras = [c[3] if c[2] == "normal" else "" for c in crudas[:26]]
    if "".join(letras) == "".join(letras).upper() and "".join(letras).isalpha():
        raise ValueError("la capa sin nada da mayúsculas: el Mac tenía el Bloq Mayús puesto. Quítalo, borra "
                         "el texto y vuelve a sondear.")
    if sorted(letras) != list("abcdefghijklmnopqrstuvwxyz"):
        raise ValueError("la capa sin nada no da las letras a-z: ¿Bloq Mayús, otra fuente de entrada a medias, "
                         "o la lectura no empieza en la línea 1 del sondeo?")
    if letras[TECLAS_SONDEO.index(MARCO.tecla)] != marco:
        raise ValueError(f"cada línea va enmarcada con la tecla «x», y aquí da «{marco}»: no casa con su propia "
                         "línea. Revisa la transcripción.")
    _sin_comillas_tipograficas(crudas)
    ahora = time.time()
    return {"id": "", "nombre": nombre, "creada": ahora, "crudas": crudas, "verificados": {},
            "compuestos": {}, "descartes": [], "sospechosos": [], "ronda": None, "rondas": 0}


def _pasos(pasos) -> tuple[tuple[int, str], ...]:
    return tuple((int(m), str(t)) for m, t in pasos)


def _texto_pasos(pasos) -> str:
    return " ".join(_clave(m, t) for m, t in pasos)


def _derivar(b: dict) -> tuple[dict[str, tuple[tuple[int, str], ...]], dict[tuple[int, str], str], set[str]]:
    """La tabla del borrador: cada carácter con su pulsación más simple.

    Lo verificado manda (la huella lo probó). Después, en este orden: una tecla
    sola por capas (sin nada, Mayús, Opción, Mayús+Opción), el acento suelto de
    una muerta (muerta + espacio), lo compuesto que ya probó una huella, y lo
    compuesto deducido (muerta + letra). Un par (carácter, pulsaciones) que una
    huella descartó no vuelve. Devuelve también las muertas y qué caracteres son
    deducidos.
    """
    descartes = {(c, p) for c, p in b.get("descartes", [])}
    tabla: dict[str, tuple[tuple[int, str], ...]] = {}

    def poner(c: str, pasos: tuple[tuple[int, str], ...]) -> bool:
        if c in tabla or not c or c.isspace() or (c, _texto_pasos(pasos)) in descartes:
            return False
        tabla[c] = pasos
        return True

    for c, pasos in b.get("verificados", {}).items():
        poner(c, _pasos(pasos))
    muertas: dict[tuple[int, str], str] = {}
    for m, tecla, tipo, salida in b["crudas"]:
        if tipo == "normal" and len(salida) == 1:
            poner(salida, ((m, tecla),))
        elif tipo == "muerta" and len(salida) == 1:
            muertas[(m, tecla)] = salida
    for (m, tecla), acento in muertas.items():
        poner(acento, ((m, tecla), (0, "space")))
    for c, pasos in b.get("compuestos", {}).items():
        poner(c, _pasos(pasos))
    deducidos: set[str] = set()
    letras = [(c, p[0]) for c, p in list(tabla.items()) if len(p) == 1 and c.isalpha()]
    for (m, tecla), acento in muertas.items():
        marca = COMBINANTES.get(acento)
        if not marca:
            continue
        for letra, paso in letras:
            compuesto = unicodedata.normalize("NFC", letra + marca)
            # Sólo los de Latin-1 (á, ñ, ü, ç…): son los que componen las fuentes de
            # Apple para estas lenguas. Uno que no compone hace fallar su fila entera
            # y cuesta otra ronda; con todos los de Unicode serían decenas.
            if (len(compuesto) == 1 and "\u00C0" <= compuesto <= "\u00FF" and compuesto != letra
                    and poner(compuesto, ((m, tecla), paso))):
                deducidos.add(compuesto)
    return tabla, muertas, deducidos


def _verificados_validos(b: dict, tabla: dict) -> dict[str, tuple[tuple[int, str], ...]]:
    return {c: _pasos(p) for c, p in b.get("verificados", {}).items() if tabla.get(c) == _pasos(p)}


def resumen(b: dict) -> dict:
    tabla, muertas, deducidos = _derivar(b)
    ok = _verificados_validos(b, tabla)
    faltan = [c for c in ASCII_IMPRIMIBLE if c not in ok]
    estado = "verificada" if not faltan else ("a medias" if ok else "sin verificar")
    return {"id": b["id"], "nombre": b["nombre"], "fecha": fecha(b["creada"]), "estado": estado,
            "elegible": not faltan, "caracteres": len(tabla), "verificados": len(ok),
            "muertas": {_clave(*k): v for k, v in muertas.items()},
            "faltan_ascii": "".join(faltan),
            "sin_verificar": "".join(c for c in tabla if c not in ok)[:200],
            "deducidos": len(deducidos), "rondas": b.get("rondas", 0)}


def fecha(t: float) -> str:
    lt = time.localtime(t)
    return f"{lt.tm_mday}-{MESES[lt.tm_mon - 1]}"


# ── probar ──────────────────────────────────────────────────────────────────
def distribucion_del_borrador(b: dict) -> hid.Distribucion:
    """Todo lo que el borrador cree saber, verificado o no: sólo para teclear la
    consulta de prueba, que existe para comprobarlo."""
    tabla, muertas, _ = _derivar(b)
    return hid.Distribucion(b["id"] or "borrador", f"borrador de {b['nombre']}", tabla, muertas)


def _literal(texto: str, motor: str) -> str:
    # Las comillas, dobladas en lo que se teclea; en lo que se hashea, simples.
    return MOTORES[motor]["literal"].format(texto.replace("'", "''"))


# Lo que puede ser el acento de una tecla muerta. Uno de éstos no se verifica
# solo: una muerta leída como tecla normal (`x´x` leído `x´ x`) seguida de algo
# que no compone (`<`, la comilla de cierre) escribe `´<`, igual que la normal,
# y la fila coincidiría. Seguido de una letra con la que compone, la muerta da
# `é` y la normal `´e`: la huella las distingue (lo encontró el revisor de C-0481).
ACENTOS = {**COMBINANTES, "’": "\u0301"}
_COMPANERAS = "eaonuicy"


def _companera(c: str, tabla: dict) -> str:
    """La letra que va detrás de un posible acento, para que la huella diga si es muerta."""
    marca = ACENTOS[c]
    for letra in _COMPANERAS:
        if letra in tabla and len(unicodedata.normalize("NFC", letra + marca)) == 1:
            return letra
    raise ValueError(f"no tengo ninguna letra con la que probar el acento {c!r}: ¿la capa sin nada está medida?")


def _filas(pendientes: list[str], sospechosos: set[str], tabla: dict) -> list[tuple[str, str]]:
    """Agrupa lo pendiente en filas (lo tecleado, y qué caracteres se prueban en ella).

    Los sospechosos (de una fila que falló) van solos, para saber cuál era; el
    resto, hasta `POR_FILA` + 1 caracteres por fila, con `$ : ?` al final y cada
    posible acento con su letra detrás (`ACENTOS`), sin separarlos.
    """
    def unidad(c: str) -> tuple[str, str]:
        return (c + _companera(c, tabla), c) if c in ACENTOS else (c, c)

    solos = [unidad(c) for c in pendientes if c in sospechosos]
    normales = [unidad(c) for c in pendientes if c not in sospechosos and c not in _AL_FINAL]
    finales = [c for c in pendientes if c not in sospechosos and c in _AL_FINAL]
    filas: list[list[str]] = []
    for texto, prueba in normales:
        if not filas or len(filas[-1][0]) + len(texto) > POR_FILA:
            filas.append(["", ""])
        filas[-1][0] += texto
        filas[-1][1] += prueba
    for i, c in enumerate(finales):
        if i < len(filas) and len(filas[i][0]) <= POR_FILA:
            filas[i][0] += c
            filas[i][1] += c
        else:
            filas.append([c, c])
    return [(t, p) for t, p in filas] + solos


def consulta(b: dict, motor: str = "SQL Server", reservadas=()) -> tuple[str, dict]:
    """La consulta de prueba con lo que falta por verificar, y su ronda.

    Un `SELECT … FROM (VALUES …)` con una fila por grupo: su número, su largo y
    las 16 primeras cifras de su huella. Los números llevan la ronda delante
    (1001, 1002… la primera; 2001… la segunda): unas huellas de una consulta
    vieja no se confunden con las de la nueva.

    No toca `b`: la ronda se apunta con `empezar_ronda` sólo cuando la consulta
    ya está tecleada entera. Lo que necesita una tecla de `reservadas` no entra.
    """
    if motor not in MOTORES:
        raise ValueError(f"motor desconocido: {motor} (sé {', '.join(MOTORES)})")
    tabla, _, _ = _derivar(b)
    ok = _verificados_validos(b, tabla)
    prohibidas = {(p.modificadores, hid.NOMBRE_DE_TECLA[p.tecla]) for p in hid.pulsaciones_reservadas(reservadas)}
    pendientes = [c for c in tabla if c not in ok and not prohibidas & set(tabla[c])]
    # `?` espera a que la comilla esté verificada (ver `_AL_FINAL`).
    if "'" not in ok:
        pendientes = [c for c in pendientes if c != "?"]
    if not pendientes:
        raise ValueError("no queda nada por verificar en esta medida")
    n_ronda = b.get("rondas", 0) + 1
    filas = [(n_ronda * 1000 + i, t, p)
             for i, (t, p) in enumerate(_filas(pendientes, set(b.get("sospechosos", [])), tabla), 1)]
    if len(filas) > 999:
        raise ValueError("demasiadas filas para una consulta")
    ronda = {"n": n_ronda, "motor": motor, "filas": filas,
             "pasos": {c: tabla[c] for _, t, _ in filas for c in t}}
    texto = ",\n".join(f"  ({n}, {_literal(t, motor)})" for n, t, _ in filas)
    return MOTORES[motor]["consulta"].format(filas=texto), ronda


def empezar_ronda(b: dict, ronda: dict) -> None:
    """La consulta de `ronda` ya está tecleada: sus huellas son las que se esperan."""
    b["rondas"], b["ronda"] = ronda["n"], ronda


# ── comprobar ───────────────────────────────────────────────────────────────
def _huella(texto: str, motor: str) -> str:
    return huellas.calcular([texto], "sha256", MOTORES[motor]["codificacion"], "LF", False) or ""


# «1001 | 9 | 3F2A…»: el número de fila, el largo si está y la huella, con lo
# que separe la rejilla al copiarla. El largo pide un separador detrás: si no,
# en una huella que empieza por cifras se tomaría su principio por el largo.
_FILA = re.compile(r"(\d{4,})[\s|,;:]+(?:(\d{1,3})[\s|,;:]+)?(?:0x)?([0-9A-Fa-f]{16,64})\b")


def leer_huellas(huellas_por_fila: dict | str) -> dict[int, tuple[int | None, str]]:
    """Las filas que devolvió la consulta: {n: (largo, huella)}.

    Vale un dict ({n: huella} o {n: {"largo": …, "huella": …}}) o el texto de la
    rejilla, una fila por línea: «n largo huella» (el largo se puede omitir).
    """
    salida: dict[int, tuple[int | None, str]] = {}
    if isinstance(huellas_por_fila, dict):
        for n, v in huellas_por_fila.items():
            if isinstance(v, dict):
                largo = v.get("largo")
                salida[int(n)] = (int(largo) if largo is not None else None, huellas.normalizar(str(v["huella"])))
            else:
                salida[int(n)] = (None, huellas.normalizar(str(v)))
        return salida
    for linea in str(huellas_por_fila).splitlines():
        m = _FILA.search(linea)
        if m:
            salida[int(m.group(1))] = (int(m.group(2)) if m.group(2) else None, huellas.normalizar(m.group(3)))
    return salida


def _coincide(texto: str, motor: str, largo: int | None, huella: str) -> bool:
    if largo is not None and largo != len(texto):
        return False
    return len(huella) >= 16 and _huella(texto, motor).startswith(huella)


def _buscar_uno(motor: str, huella: str) -> str | None:
    """El carácter (del plano básico) cuya huella es ésa: con una fila de uno, la
    huella dice qué salió aunque no fuera lo esperado. Son ~63 000 cálculos. Con
    menos de 16 cifras no se busca: una huella corta casaría con cualquier cosa."""
    if len(huella) < 16:
        return None
    for i in itertools.chain(range(0x20, 0xD800), range(0xE000, 0x10000)):
        if _huella(chr(i), motor).startswith(huella):
            return chr(i)
    return None


def _corregir(b: dict, esperado: str, real: str, pasos: tuple[tuple[int, str], ...]) -> None:
    """La huella dice que `pasos` escribe `real`, no `esperado`: se apunta donde toque."""
    if len(pasos) == 1:
        for cruda in b["crudas"]:
            if (cruda[0], cruda[1]) == pasos[0]:
                cruda[2], cruda[3] = "normal", real
    elif len(pasos) == 2 and pasos[1] == (0, "space"):
        for cruda in b["crudas"]:
            if (cruda[0], cruda[1]) == pasos[0]:
                cruda[2], cruda[3] = "muerta", real
    else:
        b.setdefault("compuestos", {})[real] = [list(p) for p in pasos]
    b.setdefault("descartes", []).append([esperado, _texto_pasos(pasos)])


def comprobar(b: dict, huellas_por_fila: dict | str) -> dict:
    """Compara las huellas de la ronda con las calculadas y apunta lo verificado en `b`.

    Por fila: si coincide, sus caracteres quedan verificados con sus teclas. Si
    no, se prueban las alternativas de los dudosos a la vista; y una fila de un
    solo carácter se busca entera (la huella dice qué salió). Lo que sigue sin
    casar queda sospechoso, y la siguiente ronda lo prueba solo, fila a fila.
    """
    ronda = b.get("ronda")
    if not ronda:
        raise ValueError("esta medida no tiene una consulta de prueba en curso: probar_teclado primero")
    motor = ronda["motor"]
    leidas = leer_huellas(huellas_por_fila)
    filas = {int(f[0]): (f[1], f[2] if len(f) > 2 else f[1]) for f in ronda["filas"]}
    ajenas = sorted(set(leidas) - set(filas))
    if ajenas:
        raise ValueError(f"las filas {ajenas} no son de la última consulta (ronda {ronda['n']}: filas "
                         f"{min(filas)}–{max(filas)}): ¿se ejecutó una consulta vieja?")
    if not leidas:
        raise ValueError("no encuentro ninguna fila «n largo huella» en lo que me das")
    pasos = {c: _pasos(p) for c, p in ronda["pasos"].items()}
    # Con el Bloq Mayús puesto al teclear la consulta, las letras salen en
    # mayúsculas: una fila de uno lo «corregiría» y la «a» pasaría a dar «A». Se
    # rechaza la ronda entera antes de apuntar nada.
    for n, (texto, _) in filas.items():
        largo, huella = leidas.get(n, (None, ""))
        mayus = "".join(c.upper() if len(c.upper()) == 1 else c for c in texto)
        if (len(huella) >= 16 and mayus != texto and not _coincide(texto, motor, largo, huella)
                and _coincide(mayus, motor, largo, huella)):
            raise ValueError(f"la fila {n} ({texto!r}) salió en mayúsculas: ¿Bloq Mayús? Quítalo, borra la "
                             "consulta y vuelve a probar_teclado. No apunté nada de esta ronda.")
    resultado = []
    sospechosos = set(b.get("sospechosos", []))
    for n, (texto, prueba) in sorted(filas.items()):
        largo, huella = leidas.get(n, (None, ""))
        if len(huella) < 16:  # sin huella, o tan corta que casaría con cualquier cosa
            resultado.append({"n": n, "texto": texto, "estado": "sin huella"})
            continue
        real = None
        if _coincide(texto, motor, largo, huella):
            real = texto
        else:
            posiciones = [i for i, c in enumerate(texto) if c in _ALTERNATIVAS]
            opciones = [_ALTERNATIVAS[texto[i]] for i in posiciones]
            total = 1
            for o in opciones:
                total *= len(o)
            if posiciones and total <= TOPE_COMBINACIONES:
                for combinacion in itertools.product(*opciones):
                    candidato = list(texto)
                    for i, c in zip(posiciones, combinacion):
                        candidato[i] = c
                    if _coincide("".join(candidato), motor, largo, huella):
                        real = "".join(candidato)
                        break
            if real is None and len(texto) == 1 and largo in (None, 1):
                real = _buscar_uno(motor, huella)
        if real is None:
            # Una fila que sólo prueba un carácter y no casa con nada demuestra que
            # esas teclas no lo dan: se descarta, para que no vuelva ronda tras ronda.
            if len(prueba) == 1:
                b.setdefault("descartes", []).append([prueba, _texto_pasos(pasos[prueba])])
                sospechosos.discard(prueba)
            else:
                sospechosos |= set(prueba)
            resultado.append({"n": n, "texto": texto, "estado": "no coincide",
                              **({"prueba": prueba} if prueba != texto else {})})
            continue
        corregidos = {}
        for esperado, salio in zip(texto, real):
            if salio != esperado:
                _corregir(b, esperado, salio, pasos[esperado])
                corregidos[esperado] = salio
            b.setdefault("verificados", {})[salio] = [list(p) for p in pasos[esperado]]
            sospechosos.discard(esperado)
        resultado.append({"n": n, "texto": texto, "estado": "coincide",
                          **({"salio": real, "corregidos": corregidos} if corregidos else {})})
    b["sospechosos"] = sorted(sospechosos)
    b["ronda"] = None
    r = resumen(b)
    tabla, _, _ = _derivar(b)
    queda = [c for c in tabla if c not in _verificados_validos(b, tabla)]
    r["filas"] = resultado
    r["siguiente"] = (
        "Verificada: todo el ASCII imprimible coincide. Dile a la persona que pulse «Usar» en Ajustes → Teclado."
        + (f" Quedan {len(queda)} caracteres sin verificar, que no se teclearán; otra ronda los prueba." if queda
           else "")
        if r["elegible"] else
        f"Faltan del ASCII: {r['faltan_ascii']!r}. Borra la consulta y vuelve a probar_teclado: la ronda "
        "siguiente sólo lleva lo que falta" + (", los sospechosos solos." if b["sospechosos"] else ".")
        if queda else
        f"Faltan del ASCII {r['faltan_ascii']!r} y no tienen teclas en lo medido: mira sus líneas del sondeo, "
        "corrígelas (resolver_linea) y vuelve a medir.")
    return r


# ── guardar, elegir y resolver ──────────────────────────────────────────────
def _ruta(id_: str) -> Path:
    if not ID_MEDIDA.fullmatch(id_):
        raise ValueError(f"no es el id de una medida: {id_}")
    return carpeta() / f"{id_}.json"


def guardar(b: dict) -> dict:
    """La guarda; si es nueva, le da su id (`medida-AAAAMMDD-HHMM`, con -2, -3… si
    en ese minuto ya había otra)."""
    carpeta().mkdir(parents=True, exist_ok=True)
    if not b.get("id"):
        base = time.strftime("medida-%Y%m%d-%H%M", time.localtime(b["creada"]))
        id_, k = base, 1
        while (carpeta() / f"{id_}.json").exists():
            k += 1
            id_ = f"{base}-{k}"
        b["id"] = id_
    ruta = _ruta(b["id"])
    tmp = ruta.with_suffix(".tmp")
    tmp.write_text(json.dumps(b, ensure_ascii=False, indent=1))
    tmp.replace(ruta)
    return b


def cargar(id_: str) -> dict:
    ruta = _ruta(id_)
    if not ruta.exists():
        raise FileNotFoundError(f"no existe la medida {id_}")
    try:
        b = json.loads(ruta.read_text())
        if b.get("id") != id_ or not isinstance(b.get("crudas"), list):
            raise ValueError("no es una medida")
        _derivar(b)
    except (ValueError, KeyError, TypeError) as e:
        raise ValueError(f"la medida {id_} no se puede leer: {e}") from e
    return b


def medidas() -> list[dict]:
    """Todas, con su estado; una que no se lee sale como «ilegible» y no tumba la lista."""
    salida = []
    if not carpeta().exists():
        return salida
    for ruta in sorted(carpeta().glob("medida-*.json"), reverse=True):
        id_ = ruta.stem
        if not ID_MEDIDA.fullmatch(id_):
            continue
        try:
            salida.append(resumen(cargar(id_)))
        except (OSError, ValueError) as e:
            salida.append({"id": id_, "estado": "ilegible", "elegible": False, "error": str(e)})
    return salida


def nombre_visible(r: dict) -> str:
    return f"Medida: {r['nombre']} ({r['fecha']})"


def disponibles() -> list[dict]:
    """Lo que se puede elegir en Ajustes: las de serie y las medidas verificadas."""
    salida = [{"id": d.id, "nombre": d.nombre, "corto": d.nombre.removeprefix("macOS ").strip("«»"),
               "tipo": "serie"} for d in hid.DE_SERIE.values()]
    for r in medidas():
        if r.get("elegible"):
            salida.append({"id": r["id"], "nombre": nombre_visible(r), "corto": nombre_visible(r), "tipo": "medida"})
    return salida


def resolver(id_: str) -> hid.Distribucion:
    """La distribución con ese id. De una medida, sólo lo verificado: lo que no
    pasó por la huella no se teclea. Una sin verificar, o que no existe, es un error."""
    if id_ in hid.DE_SERIE:
        return hid.DE_SERIE[id_]
    if not ID_MEDIDA.fullmatch(str(id_)):
        raise ValueError(f"distribución desconocida: {id_}")
    b = cargar(id_)
    r = resumen(b)
    if not r["elegible"]:
        raise ValueError(f"la medida {id_} no está verificada (faltan {r['faltan_ascii']!r}): no se puede usar")
    tabla, muertas, _ = _derivar(b)
    return hid.Distribucion(id_, nombre_visible(r), _verificados_validos(b, tabla), muertas)


def nombre_corto(id_: str) -> str:
    """Cómo se nombra al decir con qué se tecleó («U.S.», «Medida: … (24-nov)»)."""
    return next((d["corto"] for d in disponibles() if d["id"] == id_), id_)
