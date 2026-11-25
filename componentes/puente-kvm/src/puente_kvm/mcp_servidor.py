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
import functools
import io
import json
import os
from pathlib import Path

import httpx
from mcp.server.fastmcp import FastMCP, Image
from PIL import Image as PILImage

from . import config
from .motor import filas_distintas

URL = os.environ.get("PUENTE_URL", f"http://127.0.0.1:{os.environ.get('PUENTE_PUERTO', '8794')}")

# Van en cada llamada de la conversación, y el cómo ya lo dicen CLAUDE.md, las
# skills y la descripción de cada herramienta: aquí, sólo lo que no se negocia.
mcp = FastMCP(
    "puente-kvm",
    instructions=("Manejas un Mac ajeno por un JetKVM: sólo con el control que te da la persona en el "
                  "puente (si no lo tienes, pídeselo y espera), y nunca guardes ni ejecutes en el Mac."),
)


def herramienta(f):
    """Registra `f` como herramienta del puente y la devuelve tal cual.

    Lo que devuelve un `dict` llega a Claude como JSON compacto: FastMCP lo
    sangra, un ~22 % más de caracteres en cada resultado. Con
    `ensure_ascii=False`, porque si no `json` escapa lo que no es ASCII (una
    «ñ» sale `\\u00f1`, seis caracteres).

    `structured_output=False` no es para que llegue una sola vez: con mcp
    1.30.0 y un `-> dict` sin parámetros ya llegaba un solo texto, sin
    `outputSchema`. Hace falta porque el envoltorio devuelve `str` y `wraps`
    le copia la anotación de `f`: si una dijera `-> dict[str, …]` (o un
    TypedDict), FastMCP anunciaría un esquema de objeto y rechazaría el texto
    («Input should be a valid dictionary», visto con 1.30.0). Así no mira la
    anotación.
    """
    @functools.wraps(f)
    async def envuelta(*args, **kwargs):
        r = await f(*args, **kwargs)
        if isinstance(r, dict):
            return json.dumps(r, ensure_ascii=False, separators=(",", ":"), default=str)
        return r

    mcp.tool(structured_output=False)(envuelta)
    return f


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


async def _imagen(ruta: str, ancho: int | None = None, img: PILImage.Image | None = None,
                  caja: tuple[int, int, int, int] | None = None) -> Image:
    img = img or await _bajar(ruta)
    if caja:
        x, y, w, h = caja
        img = img.crop((x, y, x + w, y + h))
    if ancho and img.width > ancho:
        img = img.resize((ancho, round(img.height * ancho / img.width)), PILImage.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return Image(data=buf.getvalue(), format="png")


# ── ver ─────────────────────────────────────────────────────────────────────
# Más ancha que esto, una imagen se reduce antes de mandársela a Claude.
ANCHO_IMAGEN = 1600


# Lo que Claude usa de `/api/estado` (la pantalla del puente lo sigue leyendo
# entero): una lista blanca, para que un campo nuevo para la pantalla no le
# llegue sin decidirlo. None: el valor entero; una tupla: sólo esas claves (de
# un dict, o de cada dict de una lista). Nunca `huella_base` (en el simulador
# le daría la respuesta de comprobar_huella) ni la `url` del aparato.
PARA_CLAUDE = {
    "control": ("modo", "motivo"),
    "dispositivo": ("tipo", "conectado", "motivo", "error", "resolucion", "firmware", "firmware_contrastado",
                    "aviso", "ultimo_fotograma_s", "nota", "mac", "senal"),
    "tarea": None, "progreso": None, "error_conexion": None, "jiggler_texto": None, "mando": None,
    "lecturas": ("id", "nombre", "estado", "error", "paginas", "transcritas", "lineas", "conflictos", "huecos",
                 "pendientes", "completo", "verificada", "errores_por_pagina", "inestables"),
    "cambios": None,
}


def _vacio(v) -> bool:
    return v is None or isinstance(v, (str, list, dict)) and not v


def _sin_vacios(valor):
    """Fuera "", None, [] y {}; un `False` o un 0 dicen algo y se quedan."""
    if isinstance(valor, dict):
        limpio = {k: _sin_vacios(v) for k, v in valor.items()}
        return {k: v for k, v in limpio.items() if not _vacio(v)}
    if isinstance(valor, list):
        return [_sin_vacios(v) for v in valor]
    return valor


def para_claude(e: dict) -> dict:
    salida = {}
    for clave, claves in PARA_CLAUDE.items():
        if clave not in e:
            continue
        valor = e[clave]
        if claves is not None and isinstance(valor, dict):
            valor = {k: valor[k] for k in claves if k in valor}
        elif claves is not None and isinstance(valor, list):
            valor = [{k: v[k] for k in claves if k in v} if isinstance(v, dict) else v for v in valor]
        salida[clave] = valor
    return _sin_vacios(salida)


@herramienta
async def estado() -> dict:
    """Quién tiene el control del Mac, el aparato, la tarea en curso y las últimas lecturas y cambios."""
    e = para_claude(await _llamar("GET", "/api/estado"))
    if config.CODIGO_EN_MARCHA.viejo():
        # Este servidor nace con la conversación: tras actualizar, sigue con lo de antes.
        e["aviso_mcp"] = ("las herramientas del puente de esta conversación son de antes de actualizar: "
                          "pide a la persona que la reabra (el botón «Reabrir la conversación de Claude», en el "
                          "aviso de arriba de su pantalla, o el menú de conversaciones → Reabrir)")
    return e


@herramienta
async def ver_pantalla(region: str = "completa", x: int = 0, y: int = 0, ancho: int = 0, alto: int = 0) -> list:
    """Captura la pantalla del Mac. region: "completa" o "editor" (sólo la región del editor).

    La imagen completa se reduce a 1280 px de ancho: para hacer clic, multiplica las
    coordenadas que veas por el factor que acompaña a la imagen (la pantalla real
    mide lo que diga ese texto; con 1920×1080, el factor es 1,5).

    Con ancho y alto (y x, y: la esquina de arriba a la izquierda), en píxeles REALES
    del Mac, devuelve sólo esa zona y a tamaño real: se lee mejor que la pantalla
    entera reducida y cuesta menos. Para una tabla o una hoja, la zona de las celdas.
    """
    if region not in ("completa", "editor"):
        raise ErrorPuente('region tiene que ser "completa" o "editor"')
    if ancho or alto:
        real = await _bajar("/api/pantalla.png?region=completa")
        if ancho < 20 or alto < 20 or x < 0 or y < 0 or x + ancho > real.width or y + alto > real.height:
            raise ErrorPuente(f"la zona se sale de la pantalla, que mide {real.width}×{real.height} "
                              "(x, y, ancho y alto en píxeles reales)")
        texto = f"Zona {ancho}×{alto} en ({x}, {y}), a tamaño real: suma ({x}, {y}) a lo que veas para hacer clic."
        if ancho > ANCHO_IMAGEN:
            texto = (f"Zona {ancho}×{alto} en ({x}, {y}), reducida a {ANCHO_IMAGEN} px de ancho: multiplica lo "
                     f"que veas por {ancho / ANCHO_IMAGEN:.4g} y suma ({x}, {y}) para hacer clic.")
        return [texto, await _imagen("", ancho=ANCHO_IMAGEN, img=real, caja=(x, y, ancho, alto))]
    if region == "completa":
        real = await _bajar("/api/pantalla.png?region=completa")
        factor = real.width / 1280 if real.width > 1280 else 1
        img = await _imagen("", ancho=1280, img=real)
        return [f"Pantalla completa ({real.width}×{real.height}), reducida a 1280 px de ancho: multiplica "
                f"las coordenadas que veas por {factor:.4g} para hacer clic.", img]
    return ["Región del editor, a tamaño real.", await _imagen("/api/pantalla.png?region=editor")]


# ── actuar ──────────────────────────────────────────────────────────────────
@herramienta
async def teclear(texto: str) -> dict:
    """Teclea texto en la ventana que tenga el foco del Mac. Los saltos de línea son Enter.

    Todo o nada: si un carácter no se puede teclear con la distribución configurada, no
    se escribe ninguno. Mira la pantalla antes: el texto va a donde esté el foco.
    """
    return await _llamar("POST", "/api/teclear", {"texto": texto}, timeout=600)


@herramienta
async def atajo(atajo: str, veces: int = 1) -> dict:
    """Pulsa un atajo, p. ej. "cmd+up", "pagedown", "shift+down", "enter", "escape", "cmd+tab".

    Modificadores: cmd, ctrl, alt (Option), shift. Teclas: letras, dígitos, enter, escape,
    tab, space, backspace, delete, up/down/left/right, home/end, pageup/pagedown, f1–f12.
    """
    return await _llamar("POST", "/api/atajo", {"atajo": atajo, "veces": veces})


@herramienta
async def ir_a_linea(linea: int) -> dict:
    """Lleva el cursor del editor a esa línea con el atajo del perfil (Cmd+L en DBeaver)."""
    return await _llamar("POST", "/api/ir_a_linea", {"linea": linea})


@herramienta
async def clic(x: int, y: int, boton: str = "izquierdo", doble: bool = False) -> dict:
    """Clic en coordenadas REALES de la pantalla (las de la captura sin reducir). boton: izquierdo, derecho o centro."""
    return await _llamar("POST", "/api/clic", {"x": x, "y": y, "boton": boton, "doble": doble})


def desde_donde(alto: int, subio: int | None) -> int:
    """Desde qué fila de una página k>1 de un recorrido se le manda a Claude (0: entera).

    El puente sigue bajando con solape —sin él, `motor.desplazamiento` no tiene con
    qué medir cuánto subió y los pasos no se ajustan—, pero lo de arriba de la página
    ya le llegó al final de la anterior: cada página entera repetía un 22–26 %
    (C-0471). Se le deja una franja repetida de un octavo de la zona (64 px como
    poco, unas dos filas de una hoja) para que empalme las dos sin perder la fila del
    corte. Sin una medida de cuánto subió (None), sin que subiera (0) o sin nada en
    común (≥ alto), entera: recortar a ciegas podría quitarle una fila nueva.
    """
    if not subio or subio >= alto:
        return 0
    return max(0, alto - subio - max(alto // 8, 64))


def ya_salia(previa: PILImage.Image | None, img: PILImage.Image, subio: int, corte: int) -> bool:
    """¿Cada una de las `corte` filas de arriba que se le quitan a `img` ya estaba en la
    página anterior, a resolución completa: `subio` px más abajo (lo que se desplazó) o
    en su mismo sitio (lo que no se mueve, como un borde o una cabecera fija)?

    `desplazamiento` mide en una copia reducida y puede quedarse corto: si la medida
    se queda por debajo de lo que subió de verdad, el recorte se llevaría filas nuevas
    que Claude no vería nunca. Comprobándolo aquí, cada fila quitada es igual, por
    debajo del umbral de ruido, a una de la página anterior entera, que le llegó o
    que, a su vez, era igual a una de la anterior a ésa.
    """
    if previa is None or previa.size != img.size or subio + corte > img.height:
        return False
    w = img.width
    arriba = img.crop((0, 0, w, corte))
    movida = filas_distintas(previa.crop((0, subio, w, subio + corte)), arriba)
    quieta = filas_distintas(previa.crop((0, 0, w, corte)), arriba)
    return not any(a and b for a, b in zip(movida, quieta))


@herramienta
async def recorrer_pantalla(x: int, y: int, ancho: int, alto: int, pasos: int = 5, max_paginas: int = 10) -> list:
    """Baja una zona de la pantalla con la rueda, de donde esté hasta su final, y la devuelve página a página.

    Para una hoja de cálculo, una web, una rejilla de resultados: todo lo que no es el
    editor de leer_documento. Una sola llamada en vez de rueda + ver_pantalla una y otra
    vez. La zona (x, y, ancho, alto) va en píxeles REALES del Mac: la de las celdas, sin
    barras ni menús, que se repetirían en cada página. Antes, ponte arriba del todo si
    quieres leerla entera (⌘↑, o un clic en la primera celda).

    Cada página llega quieta y a tamaño real, con cuánto subió el contenido desde la
    anterior. De la segunda en adelante, sin lo que ya salía al final de la anterior salvo
    una franja de arriba para empalmar: el texto dice cuántos px repiten, no los cuentes
    dos veces. Los pasos de rueda se ajustan solos para que cada bajada sea unas tres
    cuartas partes de la zona. Para cuando la zona deja de cambiar (el final) o en
    max_paginas (20 como mucho): entonces vuelve a llamarla para seguir desde ahí.
    Necesita el control.
    """
    r = await _llamar("POST", "/api/recorrer", {"x": x, "y": y, "ancho": ancho, "alto": alto,
                                                "pasos": pasos, "max_paginas": max_paginas}, timeout=300)
    n = r["paginas"]
    salida: list = []
    previa = None
    for k in range(1, n + 1):
        img = await _bajar(f"/api/recorridos/{r['id']}/{k}.png")
        subio = r["subio"][k - 1]
        corte = desde_donde(img.height, subio) if k > 1 else 0
        dudosa = bool(corte) and not ya_salia(previa, img, subio, corte)
        if dudosa:
            corte = 0
        previa = img
        if k == 1:
            texto = f"Página 1 de {n}: la zona {ancho}×{alto} en ({x}, {y}), a tamaño real."
        elif subio == 0:
            texto = (f"Página {k} de {n}: el contenido no bajó; sólo cambió algo pequeño en la zona, así que "
                     "es casi la misma que la anterior.")
        elif subio is None:
            texto = (f"Página {k} de {n}: no sé cuánto subió el contenido (no encuentro lo que tiene en "
                     "común con la anterior): compáralas tú antes de contar filas.")
        elif dudosa:
            texto = (f"Página {k} de {n}: el contenido subió {subio} px, según la medida, pero lo de arriba "
                     "no casa del todo con el final de la anterior: te llega entera, compáralas tú antes de "
                     "contar filas.")
        elif corte:
            texto = (f"Página {k} de {n}: el contenido subió {subio} px. Te llega desde {corte} px por debajo "
                     f"del borde de arriba de la zona (lo de encima ya salía en la anterior), y sus primeros "
                     f"{img.height - subio - corte} px repiten el final de la anterior, para empalmar.")
        elif subio < img.height:
            texto = (f"Página {k} de {n}: el contenido subió {subio} px; sus primeros {img.height - subio} px "
                     "ya salían al final de la anterior.")
        else:
            texto = f"Página {k} de {n}: el contenido subió {subio} px, sin nada en común con la anterior."
        if img.width > ANCHO_IMAGEN:
            texto += f" Reducida a {ANCHO_IMAGEN} px de ancho."
        caja = (0, corte, img.width, img.height - corte) if corte else None
        salida += [texto, await _imagen("", ancho=ANCHO_IMAGEN, img=img, caja=caja)]
    salida.append("Final: tras la última página la zona ya no cambia." if r["final"] else
                  f"Paré en {n} páginas sin llegar al final: vuelve a llamarla para seguir desde aquí.")
    return salida


@herramienta
async def rueda(pasos: int, x: int, y: int) -> dict:
    """Rueda del ratón en (x, y), coordenadas REALES: positivo baja el contenido, negativo lo
    sube. Gira donde está el puntero, así que primero lo lleva a (x, y): pon un punto DENTRO
    de lo que quieres desplazar (aparcado, el puntero queda fuera). Para leer, mejor leer_documento."""
    return await _llamar("POST", "/api/rueda", {"pasos": pasos, "x": x, "y": y})


# ── el aparato: despertar el Mac y el jiggler (C-0463) ──────────────────────
@herramienta
async def despertar_mac() -> dict:
    """Saca al Mac del reposo (la señal de «despertar» por USB del JetKVM, como su botón
    «Intentar despertar»). Una tecla normal no lo despierta. Necesita el control.

    Espera hasta 8 s a que vuelva la imagen: `despierto` sólo es true si llegó. Si no,
    `texto` dice qué se notó; un Mac apagado (no en reposo) no se enciende así.
    """
    return await _llamar("POST", "/api/despertar", {}, timeout=30)


@herramienta
async def jiggler(encendido: bool, horario: str = "", zona: str = "", inactividad_s: int = 30) -> dict:
    """Enciende o apaga el jiggler del JetKVM: mueve un poco el ratón cuando nadie lo toca,
    para que el Mac no se bloquee ni salga «ausente». Queda guardado en el aparato y sigue
    aunque se cierre el puente. No hace falta el control: no teclea ni hace clic.

    Sin `horario`, al encenderlo pone «Frecuente, cada 30 s» todo el día (si ya había un
    horario propio guardado, lo deja). Con `horario`, un cron de SEIS campos, con
    segundos: «segundos minutos horas día-del-mes mes día-de-la-semana» (0 = domingo),
    sólo números, *, a-b, /n y comas; en segundos, un número o «*/n» con n ≥ 10. Ejemplos:
    «*/30 * 9-17 * * 1-5» = cada 30 s entre semana de 9:00 a 18:00; «0 * 8-13 * * 1-6» =
    cada minuto de lunes a sábado de 8 a 14. Con horario, `zona` es obligatoria: la zona
    IANA de esas horas (p. ej. «America/Mexico_City»); pregúntasela a la persona si no la
    sabes. `inactividad_s` (30–3600): cuánto tiempo sin que nadie toque el ratón antes de
    moverlo; sólo cuenta con horario.
    """
    cuerpo: dict = {"encendido": encendido}
    if horario:
        cuerpo.update({"horario": horario, "zona": zona, "inactividad_s": inactividad_s})
    return await _llamar("POST", "/api/jiggler", cuerpo)


# ── calibrar el teclado del Mac (C-0481, skill calibrar-teclado) ─────────────
@herramienta
async def sondear_teclado() -> dict:
    """Teclea el sondeo del teclado donde esté el foco: cada tecla que escribe en sus
    cuatro capas (sin nada, Mayús, Opción, Mayús+Opción), una línea por tecla y capa.

    Sólo en una pestaña de script NUEVA Y VACÍA, con el Bloq Mayús quitado: mira la
    pantalla antes. Necesita el control. Las teclas reservadas en Ajustes (Opción+X,
    que en DBeaver ejecuta el script) no se pulsan: su línea sale vacía. Después, lee
    la pestaña entera con leer_documento y pásale esa lectura a medir_teclado.
    """
    return await _llamar("POST", "/api/teclado/sondear", {}, timeout=900)


@herramienta
async def medir_teclado(lectura: str, nombre: str) -> dict:
    """Arma un borrador de teclado con la lectura del sondeo (de leer_documento, ya
    transcrita entera). `nombre`: cómo lo llama la persona («Latinoamericano»).

    No teclea nada. Rechaza un sondeo con líneas de menos o hecho con Bloq Mayús. El
    borrador queda «sin verificar»: no se puede usar hasta pasar por probar_teclado y
    comprobar_teclado. Devuelve su id (`medida-…`).
    """
    return await _llamar("POST", "/api/teclado/medir", {"lectura": lectura, "nombre": nombre})


@herramienta
async def probar_teclado(medida: str, motor: str = "SQL Server") -> dict:
    """Teclea, con el borrador `medida`, una consulta de sólo lectura que calcula la huella
    de lo que llega al editor, en filas de 8–10 caracteres. motor: "SQL Server" o "PostgreSQL".

    En una pestaña de script vacía y con el control, que al acabar vuelve a la persona.
    NO la ejecutes: la ejecuta ella. Después lee la rejilla de resultados (n, largo, huella) y pásasela a
    comprobar_teclado. Cada ronda sólo lleva lo que falta por verificar.
    """
    return await _llamar("POST", "/api/teclado/probar", {"medida": medida, "motor": motor}, timeout=600)


@herramienta
async def comprobar_teclado(medida: str, huellas: str) -> dict:
    """Compara las huellas que dio la base con las que calcula el puente y apunta lo verificado.

    `huellas`: la rejilla de la consulta de probar_teclado, una fila por línea, «n largo
    huella» (p. ej. «1001 9 3F2A0C…»). No teclea nada. Dice qué filas coinciden, qué
    corrigió (dudosos a la vista como ^/ˆ o º/°) y si la medida ya se puede usar: eso
    lo decide la persona en Ajustes («Usar»), no tú.
    """
    return await _llamar("POST", "/api/teclado/comprobar", {"medida": medida, "huellas": huellas})


# ── leer un documento largo ─────────────────────────────────────────────────
async def _esperar_tarea(tope: float) -> None:
    fin = asyncio.get_event_loop().time() + tope
    while asyncio.get_event_loop().time() < fin:
        e = await _llamar("GET", "/api/estado")
        if not e.get("tarea"):
            return
        await asyncio.sleep(1)
    raise ErrorPuente("la tarea sigue en marcha; consulta estado() más tarde")


@herramienta
async def leer_documento(nombre: str) -> dict:
    """Recorre el documento abierto en el editor del Mac, de principio a fin, página a página.

    Captura cada página (sin transcribirla) y devuelve la lectura. Después, ver_pagina
    de la primera y, en cada respuesta, transcribir_pagina de la que acabas de ver junto
    con ver_pagina de la siguiente. Las páginas se pueden repartir entre subagentes:
    cada una es independiente.
    """
    r = await _llamar("POST", "/api/lecturas", {"nombre": nombre})
    await _esperar_tarea(1800)
    res = await _llamar("GET", f"/api/lecturas/{r['id']}")
    res.pop("paginas_detalle", None)
    # Una vuelta por página, no dos (C-0474): cada vuelta vuelve a leer de la
    # caché toda la conversación, y ver la página n+1 no depende de haber
    # guardado la n.
    res["siguiente"] = (f"Transcribe las {res['paginas']} páginas, n = 1…{res['paginas']}: "
                        f"ver_pagina('{r['id']}', 1) y, en cada respuesta, a la vez, "
                        f"transcribir_pagina('{r['id']}', n, texto) de la que acabas de ver y "
                        f"ver_pagina('{r['id']}', n+1) de la siguiente (en la última, sólo transcribir).")
    if res.get("inestables"):
        res["siguiente"] += (f" Ojo: las páginas {res['inestables']} se capturaron con la pantalla aún "
                             "moviéndose y pueden estar a medio pintar: míralas antes de transcribirlas, y "
                             "si lo están, dilo y vuelve a leer el documento.")
    return res


# Sin zoom (C-0471): la página ya llega a tamaño real, y media página ampliada
# hasta el lado que el modelo ve entero (×1,59) no distinguió 0/O ni 1/l/I en
# el Mac simulado: la mitad de las líneas siguieron mal. Lo que dice si una
# copia es exacta es la huella, no mirar más de cerca.
@herramienta
async def ver_pagina(lectura: str, n: int) -> list:
    """La captura de la página n de una lectura, tal cual se vio, a tamaño real."""
    img = await _imagen(f"/api/lecturas/{lectura}/paginas/{n}.png")
    return [f"Página {n} de la lectura {lectura}", img]


@herramienta
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


@herramienta
async def estado_lectura(lectura: str) -> dict:
    """Cómo va una lectura: páginas transcritas, huecos, conflictos, si está verificada y
    la ruta del archivo ensamblado (el texto completo, para leerlo o copiarlo y editarlo)."""
    r = await _llamar("GET", f"/api/lecturas/{lectura}")
    r.pop("paginas_detalle", None)
    return r


@herramienta
async def resolver_linea(lectura: str, linea: int, texto: str) -> dict:
    """Fija el texto correcto de una línea en conflicto (tras mirar las capturas)."""
    return await _llamar("POST", f"/api/lecturas/{lectura}/resolver", {"linea": linea, "texto": texto})


@herramienta
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


@herramienta
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


@herramienta
async def estado_cambio(cambio: str) -> dict:
    """Estado de un cambio (propuesto, aprobado, escribiendo, escrito, fallido, verificado) y sus tramos."""
    return await _llamar("GET", f"/api/cambios/{cambio}")


@herramienta
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


@herramienta
async def ver_tramo(cambio: str, i: int, entera: bool = False) -> list:
    """La captura del editor tras escribir el tramo i, para comprobar que quedó como debía.

    Llega sólo la franja de filas que cambió al escribirlo, con dos filas de margen:
    fuera de ella la pantalla está igual, por debajo del umbral de ruido, que justo
    antes de teclearlo. Llega entera si no cambió nada visible o apenas (quizá sólo el
    cursor), si cambió de arriba abajo (p. ej. se movió la vista) o con entera=True.
    """
    c = await _llamar("GET", f"/api/cambios/{cambio}")
    t = next((t for t in c["tramos"] if t["i"] == i), None)
    if t is None:
        raise ErrorPuente(f"el cambio {cambio} no tiene tramo {i} (tiene {len(c['tramos'])})")
    img = await _bajar(f"/api/cambios/{cambio}/tramos/{i}.png")
    franja = t.get("franja")
    if t["hasta"] < t["desde"]:
        donde = f"inserta antes de la línea {t['desde']} del original"
    elif t["hasta"] == t["desde"]:
        donde = f"línea {t['desde']} del original"
    else:
        donde = f"líneas {t['desde']}–{t['hasta']} del original"
    cabeza = f"Tramo {i} del cambio {cambio} ({donde}), tras escribirlo"
    # La web enseña siempre la captura entera; aquí se recorta (C-0474): un
    # reemplazo de una a tres líneas cambia unas pocas filas, y el editor entero
    # costaba lo mismo en cada tramo.
    if entera or franja is None:
        motivo = "" if entera else " (no sé qué cambió al escribirlo)"
        return [f"{cabeza}: la captura entera del editor{motivo}.", await _imagen("", img=img)]
    if not franja:
        return [f"{cabeza}: la captura entera del editor, porque al escribirlo apenas cambió nada visible "
                "respecto de justo antes de teclear (quizá sólo el cursor): mírala entera, y mira si se "
                "escribió y dónde.", await _imagen("", img=img)]
    desde, hasta = franja
    if desde <= 0 and hasta >= img.height:
        return [f"{cabeza}: la captura entera del editor, porque cambió de arriba abajo (puede que se moviera "
                "la vista).", await _imagen("", img=img)]
    return [f"{cabeza}: sólo las filas {desde}–{hasta} px de la captura del editor ({img.width}×{img.height}), "
            "lo que cambió y dos filas de margen. Fuera de ellas, la pantalla está igual, por debajo del "
            "umbral de ruido, que justo antes de teclearlo. Para verla entera, entera=True.",
            await _imagen("", img=img, caja=(0, desde, img.width, hasta - desde))]


def main() -> None:
    mcp.run()
