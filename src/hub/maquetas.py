"""Ver en el hub las maquetas HTML, también desde el teléfono (C-0249).

Una maqueta es un prototipo sin función: una página estática con su CSS y su
JS, hecha para elegir entre opciones mirándolas. Se abrían con un servidor
aparte, y eso no llega al teléfono sin abrir otro puerto (regla dura 8). Por
el hub sí llegan, y por la misma puerta que todo lo demás —el nombre admitido,
el aparato dado de alta—, sin abrir nada nuevo. Sólo se leen: aquí no hay
nada que las escriba.

🔴 **Un HTML con scripts servido en el origen del hub es un XSS con una shell
detrás.** Su JavaScript podría abrir `/ws/terminal`, leer cualquier pantalla y
mandar cualquier POST con el `Origin` bueno, porque sería el del hub. Por eso
cada página sale con `CABECERAS`, y la que manda es `sandbox` **sin**
`allow-same-origin`: el navegador le da un origen opaco, así que para el hub
pasa a ser «otro sitio» —la comprobación de `Origin` la para como a cualquier
web ajena— y no ve sus cookies ni su almacenamiento.

Ese mismo origen opaco es la razón de **incrustar**. Desde él, lo que la
página pide (su hoja, su guion) es una petición entre sitios, y la cookie del
aparato (`SameSite=Lax`) no viaja en los subrecursos entre sitios: desde el
teléfono la puerta contestaría 403 a cada hoja y la maqueta se vería desnuda.
Así que la página sale con sus hojas y sus guiones dentro, y la CSP no deja
pedir nada más. Lo que cargue de un CDN o como imagen suelta no se ve; las
imágenes, en `data:` o SVG en línea.
"""

from __future__ import annotations

import html
import os
import re
from pathlib import Path
from urllib.parse import unquote, urlsplit

from . import config

# 🔴 Ni `allow-same-origin` (le devolvería el origen del hub, y con él la
# terminal), ni `allow-forms` (mandaría formularios en nombre de quien mira),
# ni `allow-popups` (abriría ventanas fuera del encierro). `allow-scripts` sí:
# una maqueta sin su JS no enseña lo que se quiere elegir, y encerrado en el
# origen opaco no alcanza nada del hub. `default-src 'none'` con sólo lo en
# línea es lo que hace verdad «no pide nada más»; `frame-ancestors 'none'`,
# que nadie la meta en un marco de otra página.
CABECERAS = {
    "Content-Security-Policy": (
        "sandbox allow-scripts; default-src 'none'; style-src 'unsafe-inline'; "
        "script-src 'unsafe-inline'; img-src data:; font-src data:; base-uri 'none'; "
        "form-action 'none'; frame-ancestors 'none'"),
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    # Se edita a mano y se recarga para verla: una copia vieja en el teléfono
    # haría elegir sobre algo que ya no es.
    "Cache-Control": "no-cache",
}

# Lo único que se vuelca dentro de la página. Un `<script src>` que apunte a
# otra cosa de la carpeta (un `.py`, otro `.html`) no tiene por qué acabar
# leído en voz alta dentro de ella.
_HOJAS = (".css",)
_GUIONES = (".js", ".mjs")

# Una pasada que reconoce, en este orden: comentarios, guiones (con o sin
# `src`), estilos en línea y `<link>`. Los tres primeros se reconocen para
# **no tocar lo de dentro**: un `<link>` escrito en una cadena de JavaScript
# o comentado no es una hoja que pedir. Cada valor de atributo entre comillas
# se salta entero, para que un `>` dentro de él no corte la etiqueta.
_ATRIBUTOS = r"""(?:[^>"']|"[^"]*"|'[^']*')*"""
_PIEZA = re.compile(
    r"(?P<comentario><!--.*?-->)"
    rf"|<script\b(?P<guion>{_ATRIBUTOS})>(?P<cuerpo>.*?)</script\s*>"
    r"|(?P<estilo><style\b.*?</style\s*>)"
    rf"|<link\b(?P<enlace>{_ATRIBUTOS})>",
    re.I | re.S)
_ATRIBUTO = re.compile(r"""([^\s"'<>/=]+)(?:\s*=\s*("[^"]*"|'[^']*'|[^\s"'=<>`]+))?""")

# Lo que no tiene sentido en un guion en línea: ya no hay nada que pedir.
# `defer` y `async` se pierden con él, y el guion corre donde está.
_SOBRAN_EN_LINEA = {"src", "integrity", "crossorigin", "defer", "async", "referrerpolicy"}


def raiz() -> Path:
    """`HUB_MAQUETAS` si está; si no, `maquetas/` del repo.

    Se lee en cada llamada y no al importar, para que una prueba la mueva sin
    recargar el módulo. En el producto esa carpeta no viaja: sin la variable,
    la ruta existe y contesta 404.
    """
    propia = os.environ.get("HUB_MAQUETAS")
    return Path(propia).expanduser() if propia else config.RAIZ_REPO / "maquetas"


def _dentro(candidato: Path) -> Path:
    """`candidato` ya resuelto, o `ValueError` si cae fuera de la raíz.

    Se resuelve y **después** se comprueba, el mismo orden que
    `intercambio.resolver`: resolver sigue los enlaces simbólicos, así que uno
    que apunte fuera se queda fuera.
    """
    base = raiz().resolve()
    if not base.is_dir():
        raise ValueError("no hay carpeta de maquetas")
    try:
        destino = candidato.resolve()
    except (OSError, RuntimeError, ValueError) as exc:  # un bucle de enlaces, un nombre imposible, un byte nulo
        raise ValueError("esa maqueta no se puede abrir") from exc
    if destino != base and base not in destino.parents:
        raise ValueError("eso no está en la carpeta de maquetas")
    return destino


def _relativa(ruta: str) -> Path:
    # Siempre relativa: una absoluta, aunque cayera dentro, sólo serviría para
    # tantear dónde está la carpeta en el disco.
    if str(ruta).startswith(("/", "\\")) or Path(ruta).is_absolute():
        raise ValueError("la ruta de una maqueta es relativa a su carpeta")
    return raiz() / ruta


def es_carpeta(ruta: str) -> bool:
    """Si `ruta` nombra una carpeta de dentro. La web la usa para añadir la
    barra final antes de servir su `index.html`."""
    try:
        return _dentro(_relativa(ruta)).is_dir()
    except (ValueError, OSError):
        return False


def resolver(ruta: str) -> Path:
    """El `.html` que nombra `ruta`, o `ValueError`. Una carpeta, su `index.html`.

    El `index.html` se comprueba otra vez al añadirlo: puede ser él el enlace
    que apunta fuera.
    """
    try:
        destino = _dentro(_relativa(ruta))
        if destino.is_dir():
            destino = _dentro(destino / "index.html")
        hay = destino.is_file()
    except OSError as exc:
        # Un nombre demasiado largo, sin permiso…: el mensaje del sistema lleva
        # la ruta absoluta de la carpeta, y eso no tiene por qué salir en un 404.
        raise ValueError("esa maqueta no se puede abrir") from exc
    if destino.suffix.lower() != ".html":
        raise ValueError("sólo se ven páginas .html")
    if not hay:
        raise ValueError("no hay ninguna maqueta con ese nombre")
    return destino


def pagina(ruta: str) -> str:
    """La maqueta, con sus hojas y sus guiones locales incrustados en línea.

    Lo que no es local (`http(s):`, `//`, `data:`, un camino absoluto) se deja
    tal cual: la CSP no lo deja cargar, pero cambiarlo sería mentir sobre lo
    que la página pide. Lo que no existe, sale de la raíz o no es `.css`/`.js`,
    también se deja: una hoja que falta no impide ver el resto.
    """
    destino = resolver(ruta)
    try:
        texto = destino.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise ValueError("esa maqueta no se puede abrir") from exc
    return _PIEZA.sub(lambda m: _incrustar(m, destino.parent), texto)


def _incrustar(m: re.Match, carpeta: Path) -> str:
    original = m.group(0)
    if m.group("enlace") is not None:
        atributos = _atributos(m.group("enlace"))
        if "stylesheet" not in atributos.get("rel", "").lower().split():
            return original
        css = _leer(atributos.get("href"), carpeta, _HOJAS)
        if css is None:
            return original
        media = atributos.get("media")
        abre = f'<style media="{html.escape(media)}">' if media else "<style>"
        return f"{abre}{_sin_cierre(css, 'style')}</style>"
    if m.group("guion") is not None and not m.group("cuerpo").strip():
        crudos = m.group("guion")
        js = _leer(_atributos(crudos).get("src"), carpeta, _GUIONES)
        if js is None:
            return original
        resto = "".join(f" {a.group(0)}" for a in _ATRIBUTO.finditer(crudos)
                        if a.group(1).lower() not in _SOBRAN_EN_LINEA)
        return f"<script{resto}>{_sin_cierre(js, 'script')}</script>"
    return original


def _atributos(crudos: str) -> dict[str, str]:
    salida = {}
    for a in _ATRIBUTO.finditer(crudos):
        valor = a.group(2) or ""
        if valor[:1] in ("'", '"'):
            valor = valor[1:-1]
        salida.setdefault(a.group(1).lower(), html.unescape(valor))
    return salida


def _leer(enlace: str | None, carpeta: Path, extensiones: tuple[str, ...]) -> str | None:
    """El texto del archivo local al que apunta `enlace`, o `None` si no se incrusta."""
    if not enlace:
        return None
    partes = urlsplit(enlace.strip())
    if partes.scheme or partes.netloc or not partes.path or partes.path.startswith("/"):
        return None
    try:
        archivo = _dentro(carpeta / unquote(partes.path))
        if archivo.suffix.lower() not in extensiones or not archivo.is_file():
            return None
        return archivo.read_text(encoding="utf-8", errors="replace")
    except (ValueError, OSError):
        return None


def _sin_cierre(texto: str, etiqueta: str) -> str:
    """Que lo incrustado no cierre su propia etiqueta antes de tiempo.

    `</script` dentro de una cadena de JS cerraría el guion ahí mismo y el
    resto saldría como HTML; `<\\/script` es la misma cadena para JavaScript y
    para CSS. En un guion, además, `<!--` seguido de `<script` deja al
    analizador en un estado en el que el `</script>` de cierre ya no cierra, y
    el resto de la página sería guion: sólo en ese caso se escapa también.
    """
    texto = re.sub(rf"</(?={etiqueta})", r"<\\/", texto, flags=re.I)
    if etiqueta == "script" and "<!--" in texto and re.search(r"<script", texto, re.I):
        texto = texto.replace("<!--", r"<\!--")
    return texto
