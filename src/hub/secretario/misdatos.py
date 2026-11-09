"""Los datos personales del dueño para los trámites de sus proyectos (C-0201, decisión 382).

Su nombre legal, su identificador fiscal, sus domicilios, su correo y su
teléfono de contacto: lo que un trámite digital le pide en cada proyecto. Se
dan **una vez** y sirven para todos: si ya lo dio para uno, para el siguiente
no se le vuelve a preguntar, sólo se le pide permiso antes de usarlo.

🔴 **Un archivo, no la memoria** (`HUB_HOME/secretario/mis-datos.yml`, 600).
`memoria.db` se copia cada día y se guardan catorce copias: una ficha guardada
ahí viviría en quince sitios y «olvídalo» no la olvidaría. Aquí `olvidar`
quita la entrada del archivo, y de la ficha no queda copia: sólo vive aquí y
no se reconstruye (regla dura 1). Lo que no borra, dicho para no prometerlo:
lo que él escribió en el chat (los turnos y la sesión del modelo) y lo que ya
salió en algo que aprobó (la solicitud, y adonde fuera). La bitácora sí se
apunta tapada (`tapar`), para no ser una segunda ficha.

🔴 **De propuesto a confirmado, por un botón suyo.** Lo que el secretario
encuentra o le oye queda `propuesto` (`proponer`) y no se usa hasta que él lo
confirma en Ajustes → Mis datos (`confirmar`, desde `POST /secretario/datos`),
nunca con un «sí» que interprete el modelo. Lo que él escribe a mano ya
nace confirmado. Una propuesta distinta sobre uno confirmado no lo pisa: se
queda al lado hasta que él elige.

**Campos cerrados** (`CAMPOS`), genéricos y sin país: el nombre de cada
identificador cambia de un sitio a otro y el producto no lo sabe. Lo que
tiene forma de llave se rechaza (regla dura 5): esto son datos de contacto,
no secretos, y lo que `memoria.ocultar_secretos` taparía no entra.

**Lo que sale con ellos pide permiso.** Una acción que lleva un dato suyo a
otro sitio (`piezas.Accion.saca_datos`) pasa a `ask` aunque esté en `auto`, si
`aparece_en` lo encuentra en lo que manda (`herramientas.usar_accion`); y una
investigación no lo lleva a los buscadores (`investigar.encargar`).

`ruta()` y `leer()` no crean nada: `hub-web` lee la ficha sin que el
secretario exista (a diferencia de `memoria.carpeta()`, que crea la carpeta).
"""

from __future__ import annotations

import contextlib
import fcntl
import os
import re
import tempfile
import threading
import unicodedata
from pathlib import Path

import yaml

from .. import config
from ..reloj import ahora
from .memoria import ocultar_secretos

#: Lista cerrada, en el orden de la pantalla: campo → cómo se le dice.
CAMPOS: dict[str, str] = {
    "nombre_legal": "Nombre legal",
    "id_fiscal": "Identificador fiscal",
    "id_personal": "Identificación personal",
    "domicilio_fiscal": "Domicilio fiscal",
    "domicilio_envios": "Domicilio de envíos",
    "correo_contacto": "Correo de contacto",
    "telefono": "Teléfono",
    "regimen_fiscal": "Régimen fiscal",
}
ESTADOS = ("propuesto", "confirmado")
#: Lo que no identifica a nadie: un régimen fiscal es «General» o un número de
#: tres cifras. No hace pedir permiso ni se tapa: una guarda que salta con una
#: palabra corriente se aprende a ignorar, y el día que importe no se mira
#: (regla dura 13).
NO_IDENTIFICAN = frozenset({"regimen_fiscal"})
ARCHIVO = "mis-datos.yml"
#: Un domicilio entero cabe; un documento pegado, no.
MAX_VALOR = 300
MAX_FUENTE = 200
#: Lo que pone `confirmar` cuando él lo escribe en la pantalla.
A_MANO = "lo escribiste tú"
#: Por debajo de esto, la comparación sin separadores daría falsos positivos
#: con cualquier número suelto; por encima, «55 1234 5678» casa con «5512345678».
_COMPACTO_MIN = 8

_CABECERA = ("# Tus datos para los trámites de tus proyectos (decisión 382).\n"
             "# Los propone el secretario y los confirmas tú en Ajustes → Mis datos.\n"
             "# No van en memoria.db ni en sus copias: borrar aquí es olvidar.\n")


class FichaIlegible(ValueError):
    """El archivo existe y no se puede leer. Quien guarda los datos sale por
    lo seguro: sin saber qué hay, lo que los sacaría pide permiso."""


def ruta() -> Path:
    """Dónde viven. Sin crear la carpeta: leer no deja rastro."""
    return config.HUB_HOME / "secretario" / ARCHIVO


def nombre(campo: str) -> str:
    return CAMPOS.get(campo, campo)


# ───────────────────────────── leer ─────────────────────────────


def _crudo() -> dict:
    """El archivo tal cual, con lo que no es de `CAMPOS` incluido: si él lo
    editó a mano, reescribir no se lo lleva por delante."""
    r = ruta()
    try:
        texto = r.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    except OSError as exc:
        raise FichaIlegible(f"no pude leer {r}: {exc}") from exc
    try:
        datos = yaml.safe_load(texto) or {}
    except yaml.YAMLError as exc:
        raise FichaIlegible(f"{r} no es YAML válido: {exc}") from exc
    if not isinstance(datos, dict):
        raise FichaIlegible(f"{r} tiene que ser un mapa de campos, no {type(datos).__name__}")
    return datos


def _una_linea(texto, n: int) -> str:
    return " ".join(str(texto or "").split())[:n]


def _entrada(d) -> dict | None:
    """Una entrada del archivo, normalizada. Escrita a mano sin `estado`, o
    con uno que no existe, cuenta como propuesta: no se usa hasta que él la
    confirme con el botón."""
    if isinstance(d, (str, int, float)):
        d = {"valor": d}
    if not isinstance(d, dict):
        return None
    valor = _una_linea(d.get("valor"), MAX_VALOR)
    if not valor:
        return None
    out = {"valor": valor, "estado": d.get("estado") if d.get("estado") in ESTADOS else "propuesto",
           "fuente": _una_linea(d.get("fuente"), MAX_FUENTE), "cuando": str(d.get("cuando") or "")}
    p = d.get("propuesta")
    if out["estado"] == "confirmado" and isinstance(p, dict) and _una_linea(p.get("valor"), MAX_VALOR):
        out["propuesta"] = {"valor": _una_linea(p.get("valor"), MAX_VALOR),
                            "fuente": _una_linea(p.get("fuente"), MAX_FUENTE), "cuando": str(p.get("cuando") or "")}
    return out


def leer() -> dict[str, dict]:
    """`{campo: {valor, estado, fuente, cuando[, propuesta]}}`, sólo de `CAMPOS`
    y en su orden. `propuesta` es un valor distinto que espera su sí sobre
    uno ya confirmado. Sin archivo, `{}`; roto, `FichaIlegible`."""
    crudo = _crudo()
    out = {}
    for campo in CAMPOS:
        e = _entrada(crudo.get(campo))
        if e:
            out[campo] = e
    return out


def confirmados() -> dict[str, str]:
    """Los que se pueden usar: `{campo: valor}`."""
    return {c: d["valor"] for c, d in leer().items() if d["estado"] == "confirmado"}


# ───────────────────────────── buscar en lo que sale ─────────────────────────────


def _plano(texto: str) -> str:
    """Mayúsculas, sin tildes y con los espacios juntados: «Calle  Falsa» es
    «CALLE FALSA», y «Juárez» es «JUAREZ»."""
    t = unicodedata.normalize("NFKD", str(texto or ""))
    t = "".join(c for c in t if not unicodedata.combining(c))
    return " ".join(t.upper().split())


def _compacto(texto: str) -> str:
    return re.sub(r"[^0-9A-Z@]", "", _plano(texto))


def _textos(cosa) -> list[str]:
    """Todo lo que lleva escrito un dict de parámetros, sus listas y lo de
    dentro; las claves no, que las pone el esquema."""
    if isinstance(cosa, dict):
        return [t for v in cosa.values() for t in _textos(v)]
    if isinstance(cosa, (list, tuple, set)):
        return [t for v in cosa for t in _textos(v)]
    if isinstance(cosa, bool) or cosa is None:
        return []
    return [str(cosa)]


def _valores() -> dict[str, list[str]]:
    """Cada campo que lo identifica con lo que hay de él: lo confirmado, lo
    propuesto y la propuesta que espera al lado. Todos son suyos,
    confirmados o no. Sin `NO_IDENTIFICAN`."""
    out: dict[str, list[str]] = {}
    for campo, d in leer().items():
        if campo not in NO_IDENTIFICAN:
            out[campo] = [d["valor"]] + ([d["propuesta"]["valor"]] if d.get("propuesta") else [])
    return out


def aparece_en(cosa) -> list[str]:
    """Los campos cuyo valor va en `cosa` (un texto o los parámetros de una
    acción), en el orden de `CAMPOS`.

    Se compara normalizado —mayúsculas, sin tildes, espacios juntados— y entre
    bordes de palabra, para que un «601» no case dentro de cualquier número.
    Los largos se comparan además sin separadores: un teléfono escrito con
    guiones sigue siendo el mismo. Cuentan también los propuestos: siguen
    siendo suyos aunque él no los haya confirmado, y esto sólo sube a
    pedir permiso, nunca baja. Es una red, no una garantía: un dato
    reescrito con otras palabras no casa (regla dura 22)."""
    valores = _valores()
    if not valores:
        return []
    texto = "\n".join(_textos(cosa))
    plano, compacto = _plano(texto), _compacto(texto)
    out = []
    for campo, lista in valores.items():
        for v in lista:
            pv, cv = _plano(v), _compacto(v)
            if (pv and re.search(rf"(?<![0-9A-Z]){re.escape(pv)}(?![0-9A-Z])", plano)) \
                    or (len(cv) >= _COMPACTO_MIN and cv in compacto):
                out.append(campo)
                break
    return out


#: Entre dos letras de un valor, al taparlo, puede ir cualquiera de éstos: así
#: «55-1234-5678» tapa también «5512345678» y «55 1234 5678».
_ENTRE = r"[\s.,;:/()#_-]*"


def _letra(c: str) -> str:
    """Una letra o cifra de `_compacto`, como clase que casa con sus tildes y
    sus mayúsculas: «A» casa con «a», «á» o «Ä»."""
    if not c.isalpha():
        return re.escape(c)
    variantes = {c, c.lower()} | {x for x in _CON_TILDE.get(c, "")}
    return "[" + "".join(sorted(re.escape(x) for x in variantes)) + "]"


def _con_tilde() -> dict[str, str]:
    out: dict[str, str] = {}
    for n in range(0xC0, 0x250):
        x = chr(n)
        base = "".join(c for c in unicodedata.normalize("NFKD", x) if not unicodedata.combining(c))
        if len(base) == 1 and base.isascii() and base.isalpha() and base != x:
            out[base.upper()] = out.get(base.upper(), "") + x
    return out


_CON_TILDE = _con_tilde()


def _patron(valor: str) -> re.Pattern | None:
    """El valor tal como puede venir escrito: la misma comparación que
    `aparece_en` (sin tildes, sin mayúsculas, con o sin separadores), pero
    sobre el texto original, para poder cambiarlo en su sitio."""
    compacto = _compacto(valor)
    if not compacto:
        return None
    return re.compile(r"(?<![0-9A-Za-z])" + _ENTRE.join(_letra(c) for c in compacto) + r"(?![0-9A-Za-z])")


def tapar(cosa):
    """`cosa` (un texto o unos parámetros) para apuntarla en la memoria: cada
    valor suyo cambiado por «[tu <campo>]» y lo que tiene forma de llave,
    tapado (`ocultar_secretos`).

    Es para la bitácora y lo que se le parezca: lo que va a `memoria.db` se
    copia catorce veces, y la bitácora no puede ser una segunda ficha. Casa
    igual que `aparece_en` y tapa de más antes que de menos. Nunca lanza: con
    la ficha ilegible no sabe qué datos hay y sólo tapa las llaves (la guarda
    de `usar_accion` ya pidió permiso por eso)."""
    try:
        valores = _valores()
    except FichaIlegible:
        valores = {}
    patrones = [(p, f"[tu {nombre(campo).lower()}]")
                for campo, lista in valores.items()
                for v in sorted(lista, key=len, reverse=True) if (p := _patron(v))]

    def en_texto(t: str) -> str:
        t = ocultar_secretos(t)
        for patron, en_su_lugar in patrones:
            t = patron.sub(en_su_lugar, t)
        return t

    def recorrer(x):
        if isinstance(x, dict):
            return {k: recorrer(v) for k, v in x.items()}
        if isinstance(x, (list, tuple)):
            return [recorrer(v) for v in x]
        if isinstance(x, str):
            return en_texto(x)
        return x

    return recorrer(cosa)


# ───────────────────────────── escribir ─────────────────────────────


#: Dos escritores: `hub-secretario` (la acción `proponer_dato`) y `hub-web`
#: (los botones). El de hilos cubre las peticiones a la vez de la web; el
#: `flock`, al otro proceso. Sin los dos, uno reescribiría el archivo con lo
#: que leyó antes y se comería lo del otro (como en `acceso`, decisión 184).
_ESCRITURA = threading.Lock()


@contextlib.contextmanager
def _en_exclusiva():
    r = ruta()
    r.parent.mkdir(parents=True, exist_ok=True)
    with _ESCRITURA, open(r.with_name(f"{r.name}.lock"), "w") as cerrojo:
        fcntl.flock(cerrojo, fcntl.LOCK_EX)
        try:
            # Restos de una escritura que murió a medias: bajo el cerrojo no
            # hay ninguna otra en curso con la que confundirlos.
            for resto in r.parent.glob(f"{r.name}.*.tmp"):
                with contextlib.suppress(OSError):
                    resto.unlink()
            yield
        finally:
            fcntl.flock(cerrojo, fcntl.LOCK_UN)


def _escribir(datos: dict) -> None:
    """Entero o nada, y sólo para él (600) desde el primer byte: el temporal
    nace con 0600 (`NamedTemporaryFile`) y `os.replace` lo pone en su sitio,
    así que nadie lee nunca un archivo a medias ni uno abierto a otros."""
    r = ruta()
    texto = _CABECERA + (yaml.safe_dump(datos, allow_unicode=True, sort_keys=False) if datos else "{}\n")
    tmp = tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=r.parent, prefix=f"{r.name}.",
                                      suffix=".tmp", delete=False)
    try:
        tmp.write(texto)
        tmp.flush()
        os.fsync(tmp.fileno())
        tmp.close()
        os.chmod(tmp.name, 0o600)
        os.replace(tmp.name, r)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp.name)
        raise


def _campo(campo: str) -> str:
    campo = str(campo or "").strip()
    if campo not in CAMPOS:
        raise ValueError(f"«{campo}» no es uno de tus datos; los que hay: {', '.join(CAMPOS)}")
    return campo


def _valor(valor) -> str:
    v = _una_linea(valor, MAX_VALOR + 1)
    if not v:
        raise ValueError("un dato vacío no se guarda")
    if len(v) > MAX_VALOR:
        raise ValueError(f"es demasiado largo para un dato (más de {MAX_VALOR} caracteres)")
    # Si la red de llaves lo cambiaría, no es un dato de contacto (regla 5).
    if ocultar_secretos(v) != v:
        raise ValueError("eso tiene forma de llave o contraseña: aquí no se guardan secretos")
    return v


def _fuente(fuente) -> str:
    return ocultar_secretos(_una_linea(fuente, MAX_FUENTE)) or "sin decir"


def proponer(campo: str, valor: str, fuente: str) -> str:
    """Lo que el secretario encontró o le oyó, para que él lo confirme.

    Devuelve `confirmado` si ya lo estaba con ese mismo valor —no se le
    vuelve a preguntar: es el «si ya lo di, no me lo pidas otra vez»—, o
    `propuesto`. Sobre uno confirmado con otro valor, la propuesta queda al
    lado y el confirmado sigue en uso hasta que él elija."""
    campo, valor, fuente = _campo(campo), _valor(valor), _fuente(fuente)
    with _en_exclusiva():
        crudo = _crudo()
        actual = _entrada(crudo.get(campo))
        momento = ahora()
        if actual and actual["estado"] == "confirmado":
            if _plano(actual["valor"]) == _plano(valor):
                return "confirmado"
            crudo[campo] = {"valor": actual["valor"], "estado": "confirmado", "fuente": actual["fuente"],
                            "cuando": actual["cuando"],
                            "propuesta": {"valor": valor, "fuente": fuente, "cuando": momento}}
        else:
            crudo[campo] = {"valor": valor, "estado": "propuesto", "fuente": fuente, "cuando": momento}
        _escribir(crudo)
    return "propuesto"


def confirmar(campo: str, valor: str | None = None) -> None:
    """Su sí, desde su botón. Sin `valor`, confirma lo propuesto (o la
    propuesta que espera al lado del confirmado); con `valor`, guarda ése
    —corregido o escrito a mano— y queda confirmado porque lo escribió él."""
    campo = _campo(campo)
    with _en_exclusiva():
        crudo = _crudo()
        actual = _entrada(crudo.get(campo))
        momento = ahora()
        if valor is not None:
            valor = _valor(valor)
            # «Me quedo con el de antes» es el mismo valor: conserva de dónde salió.
            mismo = actual is not None and _plano(actual["valor"]) == _plano(valor)
            crudo[campo] = {"valor": valor, "estado": "confirmado",
                            "fuente": actual["fuente"] if mismo else A_MANO,
                            "cuando": momento}
        elif actual is None:
            raise ValueError(f"no hay ningún {nombre(campo).lower()} que confirmar")
        elif actual.get("propuesta"):
            p = actual["propuesta"]
            crudo[campo] = {"valor": p["valor"], "estado": "confirmado", "fuente": p["fuente"], "cuando": momento}
        else:
            crudo[campo] = {"valor": actual["valor"], "estado": "confirmado", "fuente": actual["fuente"],
                            "cuando": momento}
        _escribir(crudo)


def olvidar(campo: str) -> bool:
    """Lo quita del archivo, y con él cualquier propuesta. Devuelve si
    estaba. Lo que ya salió en algo que él aprobó, o lo que dijo en el chat,
    no lo borra: eso vive donde fue (ver el principio del módulo)."""
    campo = _campo(campo)
    with _en_exclusiva():
        crudo = _crudo()
        if campo not in crudo:
            return False
        del crudo[campo]
        _escribir(crudo)
    return True
