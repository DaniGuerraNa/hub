"""Las herramientas de Claude Code para el Mac remoto (servidor MCP por stdio).

No habla con el aparato: llama a la API del servicio (`app.py`), que es quien
tiene la sesión con el JetKVM y quien enseña todo a la persona. Así lo que
hace Claude aparece en la pantalla del puente en el momento, y las puertas
(control, aprobación) se comprueban en un solo sitio.

Las peticiones salen sin `Origin`: el servicio las trata como de Claude, que
no puede darse el control ni aprobar cambios.
"""

from __future__ import annotations

import asyncio
import io
import os
from pathlib import Path

import httpx
from mcp.server.fastmcp import FastMCP, Image
from PIL import Image as PILImage

from . import config

URL = os.environ.get("PUENTE_URL", f"http://127.0.0.1:{os.environ.get('PUENTE_PUERTO', '8794')}")

mcp = FastMCP(
    "puente-kvm",
    instructions=(
        "Manejas un Mac remoto a través de un JetKVM: ves su pantalla y tecleas como un "
        "teclado USB. Sólo puedes actuar cuando la persona te ha dado el control en la "
        "pantalla del puente; si una herramienta dice que no tienes el control, pídeselo "
        "y espera. Para documentos largos usa leer_documento → ver_pagina → "
        "transcribir_pagina, y para escribir, proponer_cambio (la persona lo aprueba) → "
        "escribir_cambio. Nunca guardes ni ejecutes en el Mac: eso lo hace la persona."
    ),
)


class ErrorPuente(RuntimeError):
    pass


async def _llamar(metodo: str, ruta: str, cuerpo: dict | None = None, timeout: float = 60) -> dict:
    async with httpx.AsyncClient(base_url=URL, timeout=timeout) as c:
        try:
            r = await c.request(metodo, ruta, json=cuerpo)
        except httpx.ConnectError as e:
            raise ErrorPuente(f"el servicio del puente no responde en {URL}: ¿está arrancado?") from e
    if r.status_code >= 400:
        try:
            detalle = r.json().get("detail")
        except Exception:
            detalle = r.text
        raise ErrorPuente(str(detalle))
    return r.json()


async def _bajar(ruta: str) -> PILImage.Image:
    async with httpx.AsyncClient(base_url=URL, timeout=30) as c:
        try:
            r = await c.get(ruta)
        except httpx.ConnectError as e:
            raise ErrorPuente(f"el servicio del puente no responde en {URL}: ¿está arrancado?") from e
    if r.status_code >= 400:
        try:
            detalle = r.json().get("detail")
        except Exception:
            detalle = r.text
        raise ErrorPuente(str(detalle))
    return PILImage.open(io.BytesIO(r.content)).convert("RGB")


async def _imagen(ruta: str, ancho: int | None = None, recorte: str | None = None,
                  img: PILImage.Image | None = None) -> Image:
    img = img or await _bajar(ruta)
    if recorte in ("arriba", "abajo"):
        mitad = img.height // 2
        # Un poco de solape para que la línea partida por la mitad salga entera en una.
        img = img.crop((0, 0, img.width, mitad + 40)) if recorte == "arriba" else img.crop(
            (0, mitad - 40, img.width, img.height))
    if ancho and img.width > ancho:
        img = img.resize((ancho, round(img.height * ancho / img.width)), PILImage.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return Image(data=buf.getvalue(), format="png")


# ── ver ─────────────────────────────────────────────────────────────────────
@mcp.tool()
async def estado() -> dict:
    """Quién tiene el control del Mac, el aparato, la tarea en curso y las últimas lecturas y cambios."""
    e = await _llamar("GET", "/api/estado")
    e.pop("perfil", None)
    return e


@mcp.tool()
async def ver_pantalla(region: str = "completa") -> list:
    """Captura la pantalla del Mac. region: "completa" o "editor" (sólo la región del editor).

    La imagen completa se reduce a 1280 px de ancho: para hacer clic, multiplica las
    coordenadas que veas por el factor que acompaña a la imagen (la pantalla real
    mide lo que diga ese texto; con 1920×1080, el factor es 1,5).
    """
    if region not in ("completa", "editor"):
        raise ErrorPuente('region tiene que ser "completa" o "editor"')
    if region == "completa":
        real = await _bajar("/api/pantalla.png?region=completa")
        factor = real.width / 1280 if real.width > 1280 else 1
        img = await _imagen("", ancho=1280, img=real)
        return [f"Pantalla completa ({real.width}×{real.height}), reducida a 1280 px de ancho: multiplica "
                f"las coordenadas que veas por {factor:.4g} para hacer clic.", img]
    return ["Región del editor, a tamaño real.", await _imagen("/api/pantalla.png?region=editor")]


# ── actuar ──────────────────────────────────────────────────────────────────
@mcp.tool()
async def teclear(texto: str) -> dict:
    """Teclea texto en la ventana que tenga el foco del Mac. Los saltos de línea son Enter.

    Todo o nada: si un carácter no se puede teclear con la distribución configurada, no
    se escribe ninguno. Mira la pantalla antes: el texto va a donde esté el foco.
    """
    return await _llamar("POST", "/api/teclear", {"texto": texto}, timeout=600)


@mcp.tool()
async def atajo(atajo: str, veces: int = 1) -> dict:
    """Pulsa un atajo, p. ej. "cmd+up", "pagedown", "shift+down", "enter", "escape", "cmd+tab".

    Modificadores: cmd, ctrl, alt (Option), shift. Teclas: letras, dígitos, enter, escape,
    tab, space, backspace, delete, up/down/left/right, home/end, pageup/pagedown, f1–f12.
    """
    return await _llamar("POST", "/api/atajo", {"atajo": atajo, "veces": veces})


@mcp.tool()
async def ir_a_linea(linea: int) -> dict:
    """Lleva el cursor del editor a esa línea con el atajo del perfil (Cmd+L en DBeaver)."""
    return await _llamar("POST", "/api/ir_a_linea", {"linea": linea})


@mcp.tool()
async def clic(x: int, y: int, boton: str = "izquierdo", doble: bool = False) -> dict:
    """Clic en coordenadas REALES de la pantalla (las de la captura sin reducir). boton: izquierdo, derecho o centro."""
    return await _llamar("POST", "/api/clic", {"x": x, "y": y, "boton": boton, "doble": doble})


@mcp.tool()
async def rueda(pasos: int, x: int, y: int) -> dict:
    """Rueda del ratón en (x, y), coordenadas REALES: positivo baja el contenido, negativo lo
    sube. Gira donde está el puntero, así que primero lo lleva a (x, y): pon un punto DENTRO
    de lo que quieres desplazar (aparcado, el puntero queda fuera). Para leer, mejor leer_documento."""
    return await _llamar("POST", "/api/rueda", {"pasos": pasos, "x": x, "y": y})


# ── leer un documento largo ─────────────────────────────────────────────────
async def _esperar_tarea(tope: float) -> None:
    fin = asyncio.get_event_loop().time() + tope
    while asyncio.get_event_loop().time() < fin:
        e = await _llamar("GET", "/api/estado")
        if not e.get("tarea"):
            return
        await asyncio.sleep(1)
    raise ErrorPuente("la tarea sigue en marcha; consulta estado() más tarde")


@mcp.tool()
async def leer_documento(nombre: str) -> dict:
    """Recorre el documento abierto en el editor del Mac, de principio a fin, página a página.

    Captura cada página (sin transcribirla) y devuelve la lectura. Después, por cada
    página: ver_pagina(lectura, n) y transcribir_pagina(lectura, n, texto). Las páginas
    se pueden repartir entre subagentes: cada una es independiente.
    """
    r = await _llamar("POST", "/api/lecturas", {"nombre": nombre})
    await _esperar_tarea(1800)
    res = await _llamar("GET", f"/api/lecturas/{r['id']}")
    res.pop("paginas_detalle", None)
    res["siguiente"] = (f"Transcribe las {res['paginas']} páginas: ver_pagina('{r['id']}', n) y "
                        f"transcribir_pagina('{r['id']}', n, texto), n = 1…{res['paginas']}.")
    if res.get("inestables"):
        res["siguiente"] += (f" Ojo: las páginas {res['inestables']} se capturaron con la pantalla aún "
                             "moviéndose y pueden estar a medio pintar: míralas antes de transcribirlas, y "
                             "si lo están, dilo y vuelve a leer el documento.")
    return res


@mcp.tool()
async def ver_pagina(lectura: str, n: int, zoom: str = "no") -> list:
    """La captura de la página n de una lectura, tal cual se vio.

    zoom: "no" (entera), "arriba" o "abajo" (media página con más resolución, para
    caracteres dudosos). Las dos mitades se solapan unas líneas.
    """
    img = await _imagen(f"/api/lecturas/{lectura}/paginas/{n}.png",
                        recorte=zoom if zoom in ("arriba", "abajo") else None)
    return [f"Página {n} de la lectura {lectura}" + (f" (mitad {zoom})" if zoom != "no" else ""), img]


@mcp.tool()
async def transcribir_pagina(lectura: str, n: int, texto: str) -> dict:
    """Guarda la transcripción de la página n, en formato «número|contenido» por renglón.

    Formato estricto, una línea por renglón del editor:

        número|contenido

    El número es el de la columna de números del editor. Tras la barra, el contenido
    EXACTO: misma sangría (cuenta los espacios por la rejilla monoespaciada), mismas
    mayúsculas, comillas y signos. Incluye las líneas vacías ("57|"). No inventes lo que
    no se ve: si una línea sale cortada por el borde derecho, dilo en vez de completarla.
    Devuelve errores de formato y conflictos con otras páginas que se solapan.
    """
    return await _llamar("POST", f"/api/lecturas/{lectura}/paginas/{n}", {"texto": texto})


@mcp.tool()
async def estado_lectura(lectura: str) -> dict:
    """Cómo va una lectura: páginas transcritas, huecos, conflictos, si está verificada y
    la ruta del archivo ensamblado (el texto completo, para leerlo o copiarlo y editarlo)."""
    r = await _llamar("GET", f"/api/lecturas/{lectura}")
    r.pop("paginas_detalle", None)
    return r


@mcp.tool()
async def resolver_linea(lectura: str, linea: int, texto: str) -> dict:
    """Fija el texto correcto de una línea en conflicto (tras mirar las capturas)."""
    return await _llamar("POST", f"/api/lecturas/{lectura}/resolver", {"linea": linea, "texto": texto})


@mcp.tool()
async def comprobar_huella(lectura: str, huella: str) -> dict:
    """Compara la copia con la huella que da la base (hex). Si coincide, la copia es exacta."""
    return await _llamar("POST", f"/api/lecturas/{lectura}/huella", {"referencia": huella})


# ── escribir de vuelta ──────────────────────────────────────────────────────
def _leer_propuesta(ruta: str) -> str:
    """Sólo de `trabajo/` o de los datos del puente: esta herramienta no pregunta,
    y sin esa puerta leería cualquier archivo del equipo (la contraseña incluida)."""
    p = Path(ruta).expanduser()
    if not p.is_absolute():
        p = config.espacio() / p
    real = p.resolve()  # sigue enlaces y `..`: lo que cuenta es adónde lleva
    permitidas = (config.trabajo().resolve(), config.hogar().resolve())
    if not any(real.is_relative_to(base) for base in permitidas):
        raise ErrorPuente(f"sólo leo propuestas de {config.trabajo()} o de los datos del puente "
                          f"({config.hogar()}): copia ahí el archivo")
    try:
        return real.read_text()
    except OSError as e:
        raise ErrorPuente(f"no puedo leer {ruta}: {e.strerror}") from e


@mcp.tool()
async def proponer_cambio(lectura: str, descripcion: str, ruta: str = "", texto: str = "") -> dict:
    """Propone el texto nuevo COMPLETO del documento (desde un archivo `ruta` o en `texto`).

    El puente calcula los tramos que cambian y la persona los revisa y aprueba en su
    pantalla. Hasta que lo apruebe, escribir_cambio no hace nada. Parte siempre del
    archivo ensamblado de una lectura verificada.
    """
    if ruta:
        texto = _leer_propuesta(ruta)
    if not texto:
        raise ErrorPuente("falta el texto nuevo (ruta o texto)")
    r = await _llamar("POST", "/api/cambios", {"lectura": lectura, "texto": texto, "descripcion": descripcion})
    r["url_para_la_persona"] = f"{URL}{r['url']}"
    return r


@mcp.tool()
async def estado_cambio(cambio: str) -> dict:
    """Estado de un cambio (propuesto, aprobado, escribiendo, escrito, fallido, verificado) y sus tramos."""
    return await _llamar("GET", f"/api/cambios/{cambio}")


@mcp.tool()
async def escribir_cambio(cambio: str) -> dict:
    """Escribe en el editor del Mac un cambio YA APROBADO por la persona, tramo a tramo.

    Antes comprueba que la pantalla es la del documento leído; si no, no escribe nada.
    No guarda: al terminar, dile a la persona que lo revise y lo guarde o ejecute ella.
    """
    await _llamar("POST", f"/api/cambios/{cambio}/escribir", {})
    await _esperar_tarea(1800)
    r = await _llamar("GET", f"/api/cambios/{cambio}")
    for t in r["tramos"]:
        t.pop("antes", None)
        t.pop("nuevas", None)
    return r


@mcp.tool()
async def ver_tramo(cambio: str, i: int) -> list:
    """La captura del editor tras escribir el tramo i, para comprobar que quedó como debía."""
    return [f"Tramo {i} del cambio {cambio}, tras escribirlo",
            await _imagen(f"/api/cambios/{cambio}/tramos/{i}.png")]


def main() -> None:
    mcp.run()
