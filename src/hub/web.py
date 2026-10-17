"""UI web y endpoints JSON.

Renderizado en servidor con formularios normales: sin build de frontend y sin
estado de cliente. Agregar una función es tocar una plantilla y un endpoint
(decisión 23) — que es lo que hace que un agente de mantenimiento pueda crecerla
sin romperla.
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import quote, urlsplit

import asyncio
import contextlib
import html
import json
import sqlite3
import sys

from fastapi import FastAPI, File, Form, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import (FileResponse, HTMLResponse, JSONResponse,
                               PlainTextResponse, RedirectResponse)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import consumo as _consumo_mod
from . import (acceso, agentes, api, asistente, avisos, busqueda, buzon, canal, catalogo,
               comandos, config, db, encargos, entrega, entrevistador, insignias,
               intercambio, lienzos, maquina, navegador, orquestador,
               programados, registry, rele, rele_encargos, servicios,
               slots, snapshotter, terminal, tmux, transcripts)
from . import conexiones as conexiones_mod
from . import repos as repos_git

@contextlib.asynccontextmanager
async def _al_arrancar(_app: FastAPI):
    """Leer el registro antes de servir la primera pantalla.

    🔴 Sin esto el hub arranca CIEGO. Se vio instalando de cero: el registro
    recién sembrado declaraba dos proyectos y la portada decía «No hay proyectos
    en projects.yml» — un diagnóstico falso que manda a editar un archivo que
    está bien. La causa es que el único que sincronizaba el YAML con el índice
    era el snapshotter, y `hub-web` puede correr solo: es exactamente lo que
    imprime el instalador con `--sin-servicios`, donde el hub se quedaba así
    para siempre.

    Falla en silencio a propósito: un registro roto no puede impedir que
    arranque la web, porque la web es donde se lee el aviso de que está roto.
    """
    try:
        con = db.abrir()
        try:
            registry.sincronizar(con, registry.cargar())
            con.commit()
        finally:
            con.close()
    except Exception as exc:  # noqa: BLE001 — arrancar es más importante
        print(f"[web] no se pudo leer el registro al arrancar: {exc}", flush=True)
    yield


app = FastAPI(title="Hub", docs_url="/api/docs", lifespan=_al_arrancar)

# ── Quién puede hablarle al hub ───────────────────────────────────────────────
#
# 🔴 Escuchar sólo en 127.0.0.1 protege de la RED, no del NAVEGADOR. Y esa
# distinción no es teórica: se midió en una instalación limpia. Cualquier página
# abierta en el navegador del usuario podía abrir
# `ws://127.0.0.1:8787/ws/terminal/<sesión>` y recibir el contenido del PTY —244
# bytes en la prueba— y escribir en él. Los navegadores permiten WebSockets entre
# orígenes y no aplican la restricción de lectura que sí aplican a `fetch`. Los
# nombres de sesión son adivinables, y con la cabecera `Host` sin validar se
# enumeran (DNS-rebinding).
#
# La defensa es comprobar el ORIGEN, y funciona por una asimetría que conviene
# tener escrita: `Origin` se falsifica trivialmente desde `curl`, pero **no
# desde el JavaScript de una página** — lo pone el navegador y es una cabecera
# prohibida. Como el vector es el navegador, validarla lo cierra entero.
#
# Que un proceso local con `curl` pueda saltárselo no es un hueco que tape la
# autenticación: quien puede ejecutar `curl` en esta máquina ya puede ejecutar
# `bash`. Por eso no hay token: no defendería de nada nuevo.
# 🔴 Desde el acceso remoto la lista deja de ser una constante: entrar por el
# nombre de la red privada tiene que valer, y ese nombre no se puede escribir
# aquí porque es distinto en cada máquina (decisión 162). Vive en `acceso.yml` y
# lo sirve `acceso.hosts()`, que **rechaza un comodín** en vez de admitirlo:
# volver a abrir el DNS-rebinding sería deshacer justo lo que esta lista cerró.
MUTAN = frozenset({"POST", "PUT", "PATCH", "DELETE"})

def _hosts_de_prueba() -> tuple[str, ...]:
    """`testserver`, el nombre con el que entra el arnés de Starlette.

    🔴 **Sólo bajo pytest.** Antes estaba en `allowed_hosts` sin condición y no
    importaba, porque pasar el `Host` no daba nada. Ahora sí: el nombre decide si
    hace falta dispositivo, así que un `testserver` admitido en producción sería
    una llave que abre la puerta desde fuera con sólo escribir una cabecera.
    """
    return ("testserver",) if "pytest" in sys.modules else ()

# Por dónde se entra sin haber dado de alta el dispositivo: **canjear** un
# código de alta, y los estáticos, que los pide el navegador antes de tener
# cookie y sin ellos la pantalla de alta se ve en blanco.
#
# 🔴 Con la barra final, y sólo para GET/HEAD. Las dos cosas a propósito, y
# ninguna es cosmética (decisión 183). Sin la barra, `"/acceso/alta"` también
# casaba con el **POST que CREA** un código, y ése era el agujero: un aparato
# cualquiera de la red privada pedía un alta, leía el código en la cabecera
# `Location` de la redirección y lo canjeaba. Se dio de alta a sí mismo.
SIN_PUERTA = ("/acceso/alta/", "/static/")

# Los métodos que no cambian nada. La exención de `SIN_PUERTA` se limita a
# éstos: crear algo nunca es un paso previo a poder entrar.
SOLO_MIRAN = frozenset({"GET", "HEAD"})


def origen_permitido(origen: str | None) -> bool:
    """Se conserva el nombre porque lo usa el resto del módulo; la lista ahora
    es dinámica. El porqué entero está en `acceso.origen_permitido`."""
    return acceso.origen_permitido(origen)


def _hosts_validos() -> tuple[str, ...]:
    try:
        return (*acceso.hosts(), *_hosts_de_prueba())
    except acceso.AccesoInvalido:
        # Un `acceso.yml` roto no puede dejar al hub inalcanzable: se sigue
        # entrando por casa, y el manejador de `AccesoInvalido` explica qué pasa.
        return (*acceso.HOSTS_LOCALES, *_hosts_de_prueba())


@app.middleware("http")
async def _la_puerta(request: Request, siguiente):
    """Quién puede hablarle al hub: el nombre, el origen y el dispositivo.

    Las tres comprobaciones van en el mismo sitio y en este orden porque las
    tres empiezan a importar en el mismo instante —cuando el hub deja de ser
    sólo `localhost`— y soltar una sin las otras deja un hueco abierto.
    """
    host = request.headers.get("host")
    if not _en_lista(host, _hosts_validos()):
        # 🔴 En castellano y diciendo qué hacer. `TrustedHostMiddleware` contesta
        # «Invalid host header» y ya: medido el 2026-09-07, es literalmente lo
        # primero que se ve al abrir el hub desde el móvil por la red privada, y
        # no da ninguna pista de que falta un nombre en un archivo.
        nombre = (host or "").rsplit(":", 1)[0]
        return PlainTextResponse(
            f"El hub no acepta el nombre «{nombre}».\n\n"
            f"Añádelo a la lista `hosts` de {acceso.archivo()} y reinicia el "
            "servicio. Tiene que ser el nombre exacto: aquí no se admiten "
            "comodines, porque sin validar el `Host` los nombres de sesión se "
            "pueden enumerar desde una página cualquiera.\n",
            status_code=400,
        )

    if request.method in MUTAN and not origen_permitido(request.headers.get("origin")):
        return JSONResponse(
            {"ok": False,
             "error": "petición rechazada: viene de otro sitio web"},
            status_code=403,
        )

    respuesta = _puerta_de_dispositivo(request)
    if respuesta is not None:
        return respuesta
    return await siguiente(request)


def _es_de_casa(host: str | None) -> bool:
    """Local de verdad, o el arnés de tests cuando corre bajo pytest."""
    return acceso.es_host_local(host) or _en_lista(host, _hosts_de_prueba())


def _en_lista(host: str | None, permitidos: tuple[str, ...]) -> bool:
    if not host:
        return True
    nombre = host.rsplit(":", 1)[0].strip("[]").lower() if ":" in host else host.lower()
    return nombre in permitidos


def _esquema(request: Request) -> str:
    """Con qué esquema abrió el navegador el hub, no con cuál llegó a uvicorn.

    🔴 Detrás de `tailscale serve` el proxy corre en Windows y habla con el hub
    por `http://127.0.0.1:8787`, así que `request.url.scheme` dice **http**
    aunque el móvil haya escrito `https://`. Donde eso duele es en el QR del
    alta: se pintaría un enlace `http://` a un nombre que sólo se sirve por
    `https`, y el aparato no llegaría a ninguna parte — justo el paso que no se
    puede repetir desde fuera, porque para arreglarlo hay que estar en casa.

    Se cree a `X-Forwarded-Proto` sólo para construir enlaces y decidir si la
    cookie va marcada como segura. **Ninguna decisión de acceso depende de esta
    función**: una cabecera que pone quien llama no puede abrir ninguna puerta.
    """
    reenviado = (request.headers.get("x-forwarded-proto") or "").split(",")[0].strip().lower()
    if reenviado in ("http", "https"):
        return reenviado
    # Sin la cabecera: por un nombre de fuera sólo se llega por la red privada,
    # y ahí `tailscale serve` es https. Por casa, lo que diga la petición.
    if not _es_de_casa(request.headers.get("host")):
        return "https"
    return request.url.scheme


def _puerta_de_dispositivo(request: Request):
    """Exige dispositivo dado de alta cuando se entra por un nombre de fuera.

    🔴 **Por el `Host` y no por la IP del cliente**, y no es un descuido. Con
    `tailscale serve` el proxy corre en Windows y se conecta al hub por
    `127.0.0.1`: mirando `request.client.host` **todo el tráfico remoto parece
    local**, así que esa comprobación daría una puerta que no cierra nada. El
    nombre por el que se ha entrado sí distingue, porque el nombre de la red
    privada no existe hasta que alguien lo pone en `acceso.yml`.

    🔴 **La exención de `SIN_PUERTA` es de sólo mirar.** La primera versión la
    daba por prefijo y para cualquier método, y eso incluía el POST que crea un
    código de alta: desde fuera se pedía un alta, se leía el código en la
    cabecera `Location` y se canjeaba acto seguido — el aparato se daba de alta
    a sí mismo y la puerta no cerraba nada (decisión 183).

    Lo que esto NO cubre, dicho en voz alta para que nadie lo dé por cubierto:
    un dispositivo que ya esté aprobado en la red privada puede pedir con `curl`
    y `Host: localhost` y pasar. La defensa ahí es el `tailnet lock` y la
    aprobación manual (decisión 158), no esta puerta. **La terminal no depende
    de eso**: ésa exige dispositivo siempre, venga por donde venga (regla dura 8).
    """
    if _es_de_casa(request.headers.get("host")):
        return None
    if request.method in SOLO_MIRAN and request.url.path.startswith(SIN_PUERTA):
        return None
    dispositivo = acceso.reconocer(request.cookies.get(acceso.COOKIE))
    if dispositivo:
        acceso.marcar_uso(str(dispositivo.get("id")))
        return None
    # 🔴 El comando va **entero y tal cual se escribe**. La primera versión decía
    # `hub-acceso alta "…"`, que no existe: no hay `[project.scripts]` en
    # `pyproject.toml` y el único `hub` del PATH es el CLI del asistente. Este es
    # el mensaje que se lee desde otro país, con el móvil fuera y sin poder
    # preguntar — mandar a un comando inventado deja sin salida justo ahí.
    return PlainTextResponse(
        "Este dispositivo no está dado de alta en el hub.\n\n"
        "Desde la máquina de casa, en una terminal:\n\n"
        f"    cd {config.RAIZ_REPO}\n"
        "    uv run python -m hub.acceso alta \"Nombre del aparato\"\n\n"
        "Escanea el QR que imprime. Si no hay nadie en casa, queda el escritorio "
        "remoto.\n",
        status_code=403,
    )

_AQUI = Path(__file__).parent
plantillas = Jinja2Templates(directory=str(_AQUI / "templates"))


def millones(n: int | None) -> str:
    """Una cifra grande en la escala en que se lee de un vistazo.

    13 655 752 110 no se lee: se cuenta con el dedo. Y las cifras de consumo se
    comparan entre sí —qué proyecto pesa más—, no se auditan al token, así que
    la escala corta gana. Donde hace falta el número exacto, como las peticiones,
    la plantilla lo enseña entero y no pasa por aquí.

    Un decimal por debajo de 100 y ninguno por encima: «8,5 G» dice algo y
    «845,3 M» ya no — el decimal de una cifra de tres dígitos es ruido con
    aspecto de precisión. Coma decimal y punto de millar, que es como se escribe
    en castellano.
    """
    if n is None:
        return "—"
    for corte, sufijo in ((1_000_000_000, "G"), (1_000_000, "M"), (1_000, "k")):
        # El umbral cede lo que va a ceder el redondeo. Con `>= corte` a secas,
        # 999 999 no llegaba a «M» y salía como «999.999» entre cifras que van
        # en M: la escala cambiando a mitad de columna es justo lo que esto
        # existe para evitar.
        if abs(n) < corte * 0.9995:
            continue
        valor = n / corte
        texto = f"{valor:.1f}" if abs(valor) < 100 else f"{valor:.0f}"
        return texto.replace(".", ",") + " " + sufijo
    return f"{n:,}".replace(",", ".")


# Los dos formateadores viven en `consumo`, que es donde nacieron y el único
# sitio que hoy los usa. Se registran aquí como globales de Jinja porque una
# plantilla no importa módulos; si algún día los pide una segunda pantalla, se
# mudan a su propio módulo y esta línea no cambia.
plantillas.env.globals["millones"] = _consumo_mod.millones
plantillas.env.globals["numero"] = _consumo_mod.numero
plantillas.env.globals["tamano"] = navegador.tamano
# Disponible en TODA plantilla sin pasarla por el contexto de cada vista: si
# hubiera que acordarse de inyectarla, la vista que se olvide pinta el estado
# mudo y nadie lo nota. El arnés de tests llama a la MISMA función sobre su
# entorno, para no acabar probando plantillas distintas de las que se sirven.
insignias.registrar(plantillas.env)


def _con_rail(datos: dict) -> dict:
    """Añade lo que necesita el raíl global a cualquier contexto de plantilla.

    Va por aquí y no por cada vista a propósito: el raíl sale en las siete
    pantallas, y si dependiera de que cada una se acordase de pasarlo, la que se
    olvidara se quedaría sin navegación y sin ningún error que lo dijera.
    """
    if "rail" in datos:
        return datos
    con = conexion()
    try:
        return {**datos, "rail": api.rail(con)}
    finally:
        con.close()


def _vista(request: Request, plantilla: str, datos: dict):
    return plantillas.TemplateResponse(request, plantilla, _con_rail(datos))
class _EstaticosSinCache(StaticFiles):
    """Estáticos que SIEMPRE se revalidan.

    Por defecto FastAPI manda `ETag` y `Last-Modified` pero no `Cache-Control`, y
    sin él el navegador aplica caché heurística: puede reutilizar el archivo sin
    preguntar. El síntoma es de los que cuestan una tarde — un arreglo en el JS
    no llega, la pantalla se comporta como la versión de antes, y el servidor
    tiene el archivo nuevo. Pasó el 2026-08-30 con el cierre de los menús: aquí
    funcionaba y en su navegador no.

    `no-cache` no significa «no guardes»: significa «revalida antes de usar». Con
    el ETag que ya se manda, la respuesta habitual es un 304 vacío. En una
    herramienta local eso no se nota, y a cambio el código que se sirve es
    siempre el que hay en disco.
    """

    async def get_response(self, path: str, scope):
        respuesta = await super().get_response(path, scope)
        respuesta.headers["Cache-Control"] = "no-cache, must-revalidate"
        return respuesta


app.mount("/static", _EstaticosSinCache(directory=str(_AQUI / "static")), name="static")


def conexion():
    # 🔴 `asegurar_home()` hace `mkdir` y estaba FUERA de toda guarda: con
    # `HUB_HOME` inexistente y su padre de sólo lectura —disco lleno, o un
    # primer arranque en un sitio donde no se puede escribir— las siete
    # pantallas daban 500 desnudo. Es literalmente el caso que `BaseIlegible`
    # dice cubrir, escapándose una línea antes de llegar a ella.
    try:
        config.asegurar_home()
    except OSError as exc:
        raise db.BaseIlegible(db._porque_no_abre(config.DB_PATH, exc)) from exc
    return db.abrir()


def _volver(destino: str = "/", aviso: str | None = None,
            fugaz: bool = False) -> RedirectResponse:
    """Redirige, y si algo falló lo dice en la página de destino.

    🔴 Un `except: pass` alrededor de tmux esconde fallos que se manifiestan
    como bugs de UI (regla dura 21): «Lanzar» no abría nada en una máquina
    recién instalada y nadie lo supo hasta que otra persona lo probó. Lo que
    falla se dice en voz alta, en la pantalla a la que se vuelve.

    `fugaz` es para lo que salió bien («Encolada», «Detenida»): se lee una vez
    y se va solo, porque *«que siempre esté ahí no aporta nada»*. Un fallo no
    es fugaz nunca: se queda hasta que se cierra a mano.
    """
    if aviso:
        separador = "&" if "?" in destino else "?"
        fragmento = ""
        if "#" in destino:
            destino, fragmento = destino.split("#", 1)
            fragmento = "#" + fragmento
        destino = f"{destino}{separador}aviso={quote(aviso)}{'&fugaz=1' if fugaz else ''}{fragmento}"
    return RedirectResponse(destino, status_code=303)


@app.exception_handler(registry.YamlInvalido)
def _registro_invalido(request: Request, exc: Exception):
    """El registro está mal escrito: decir dónde, no dar un 500.

    `projects.yml` se edita a mano a propósito (decisión 7), así que
    equivocarse escribiéndolo es lo normal. Antes eso salía como `Internal
    Server Error` en las tres acciones que releen el archivo mientras las demás
    pantallas seguían enseñando datos viejos: ni te decía qué línea, ni que el
    problema fuera del archivo.
    """
    # 🔴 A `/api/…` se le contesta JSON, no una página.
    #
    # Devolver HTML aquí dejaba mudo al panel del asistente: su JavaScript hace
    # `r.json()`, se encontraba una página, y el error se perdía por el camino.
    # El hub SABÍA exactamente qué pasaba —«la clave conexiones está dos veces,
    # línea 282»— y esa frase no llegaba a ninguna pantalla. Hubo que ir a la
    # terminal a leer la conversación para enterarse de que el hub estaba roto.
    if request.url.path.startswith("/api/"):
        return JSONResponse(
            {"ok": False, "error": str(exc),
             "archivo": str(config.projects_yml())},
            status_code=422,
        )
    cuerpo = (
        "<!doctype html><meta charset=utf-8><title>Hub — registro inválido</title>"
        "<body style='font:14px/1.6 system-ui;max-width:70ch;margin:8vh auto;padding:0 5vw'>"
        "<h1 style='font-size:20px'>El registro no se puede leer</h1>"
        f"<pre style='white-space:pre-wrap'>{html.escape(str(exc))}</pre>"
        "<p>Está en <code>~/.local/share/hub/projects.yml</code>. Arréglalo con "
        "un editor y recarga: el hub no lo toca por su cuenta.</p></body>"
    )
    return HTMLResponse(cuerpo, status_code=422)


@app.exception_handler(db.BaseIlegible)
@app.exception_handler(sqlite3.DatabaseError)
def _indice_ilegible(request: Request, exc: Exception):
    """Cuando el índice no se puede leer, decirlo. No un 500 desnudo.

    Las siete pantallas leen la base, así que una `hub.db` corrupta las tumbaba
    todas a `Internal Server Error` — la pantalla que menos ayuda de todas las
    posibles, porque el remedio (renombrar un archivo) no se deduce de ahí.

    Se sirve 503 y no 500: el hub no está roto, está sin índice, y eso se
    arregla. El texto trae la orden exacta y la advertencia de que con la base
    se van las notas y los slots.
    """
    detalle = str(exc) if isinstance(exc, db.BaseIlegible) else db._porque_no_abre(
        config.DB_PATH, exc
    )
    cuerpo = (
        "<!doctype html><meta charset=utf-8><title>Hub — índice ilegible</title>"
        "<body style='font:14px/1.6 system-ui;max-width:70ch;margin:8vh auto;padding:0 5vw'>"
        "<h1 style='font-size:20px'>El índice del hub no se puede leer</h1>"
        f"<pre style='white-space:pre-wrap'>{html.escape(detalle)}</pre>"
        "<p>El registro (<code>projects.yml</code>) no está afectado: la base es "
        "sólo el índice.</p></body>"
    )
    return HTMLResponse(cuerpo, status_code=503)


# ─────────────────────────── vistas ───────────────────────────


@app.get("/")
def inicio(request: Request, muestra: int | None = None):
    con = conexion()
    try:
        datos = api.resumen(con, muestra)
        # Cuántos proyectos DECLARA el registro, que no es lo mismo que cuántos
        # hay indexados. Si el índice está vacío y el registro no, decir «no hay
        # proyectos en projects.yml» es mentira, y de las que hacen perder una
        # tarde: manda a arreglar el único archivo que estaba bien.
        try:
            declarados = len(registry.cargar())
        except Exception:  # noqa: BLE001 — la portada se pinta igual
            declarados = 0
        return _vista(
            request, "index.html",
            {"r": datos, "declarados": declarados,
             "titulo": "Hub", "seccion": "panorama"},
        )
    finally:
        con.close()


@app.get("/proyecto/{proyecto_id}")
def proyecto(request: Request, proyecto_id: str, archivados: int = 0):
    con = conexion()
    try:
        p = api.obtener_proyecto(con, proyecto_id)
        if not p:
            return _volver()
        abiertos = [
            x for x in api.paneles_abiertos(con) if x["proyecto_id"] == proyecto_id
        ]
        return _vista(
            request,
            "proyecto.html",
            {
                "p": p,
                "slots": api.slots_de(con, proyecto_id, bool(archivados)),
                "paneles": abiertos,
                "archivados": bool(archivados),
                "estado": api.estado_de(con, proyecto_id),
                "capa": api.capa_base(con, proyecto_id),
                "repos": api.repos_de(con, proyecto_id),
                "servicios": api.servicios(con, proyecto_id),
                "consumo": api.consumo(con, proyecto_id),
                "titulo": p["nombre"],
                "seccion": "panorama",
                "proyecto_actual": proyecto_id,
            },
        )
    finally:
        con.close()


# ───────────────────────── respaldo, servicios, conexiones ─────────────────────────


# ── La puerta, por dentro ────────────────────────────────────────────────────

def _enlace_de_alta(request: Request, codigo: str) -> str:
    """A dónde tiene que llevar el QR: al nombre por el que ese aparato va a
    entrar, que casi nunca es el nombre por el que se está mirando la pantalla.

    🔴 El caso normal es dar de alta el móvil **desde casa**, mirando el hub en
    `http://127.0.0.1:8787`. Armar el enlace con el nombre de la petición pintaba
    entonces un QR a `127.0.0.1`: perfectamente válido, ilegible en la práctica, y
    sin ningún error — el móvil escanea, no carga, y no hay nada que mirar. Se usa
    el primer nombre de la red privada, igual que hace el CLI del alta
    (decisión 185); sólo si no hay ninguno se cae al nombre de la petición, que
    para dar de alta un segundo aparato desde otro que ya entró es el correcto.
    """
    anfitrion = request.headers.get("host") or ""
    if _es_de_casa(anfitrion):
        remotos = [h for h in _hosts_validos() if h not in acceso.HOSTS_LOCALES
                   and h not in _hosts_de_prueba()]
        if remotos:
            return f"https://{remotos[0]}/acceso/alta/{codigo}"
    return f"{_esquema(request)}://{anfitrion}/acceso/alta/{codigo}"


@app.get("/acceso")
def vista_acceso(request: Request, codigo: str | None = None):
    """Quién puede entrar y por dónde.

    El `codigo` en la URL es el alta recién creada: se pasa por la URL y no por
    sesión para que recargar la página siga enseñando el mismo QR en vez de
    generar otro y dejar el primero colgando.
    """
    error = None
    try:
        lista_hosts = acceso.hosts()
    except acceso.AccesoInvalido as exc:
        lista_hosts, error = acceso.HOSTS_LOCALES, str(exc)

    pendiente = next((p for p in acceso.pendientes() if p["codigo"] == codigo), None) \
        if codigo else None
    enlace = qr = None
    if pendiente:
        enlace = _enlace_de_alta(request, codigo)
        qr = acceso.qr_svg(enlace)

    return _vista(request, "acceso.html", {
        "titulo": "Acceso", "seccion": "acceso",
        "hosts": lista_hosts, "locales": acceso.HOSTS_LOCALES,
        "dispositivos": acceso.dispositivos(),
        "terminal_remota": acceso.terminal_remota(),
        "pendiente": pendiente, "qr": qr, "enlace": enlace,
        "minutos": acceso.MINUTOS_DE_ALTA,
        "archivo": str(acceso.archivo()), "error": error,
    })


@app.get("/api/acceso/terminal")
def api_estado_terminal(request: Request):
    """Por qué NO conectó la terminal. Lo necesita `/trabajo`, no `/acceso`.

    🔴 Existe por una mentira medida el 2026-09-16, con el hub ya en su móvil: el
    WebSocket se rechaza con 403 **antes del `accept()`** —que es exactamente lo
    que la decisión 163 pide— pero el navegador no puede leer el estado de un
    apretón de manos fallido: le llega un cierre 1006 y nada más. La pantalla
    decía «desconectado · reintento en 8 s», que se lee como «se cayó la red».

    Estando fuera, eso son horas buscando un fallo que no existe. La respuesta
    verdadera —«esto está cerrado a propósito y se abre aquí»— el hub la sabe y
    sólo le faltaba dónde decirla.
    """
    return {
        "de_casa": _es_de_casa(request.headers.get("host")),
        "remota_abierta": acceso.terminal_remota(),
    }


@app.post("/acceso/alta")
def crear_alta(nombre: str = Form(...)):
    return RedirectResponse(f"/acceso?codigo={quote(acceso.alta_pendiente(nombre))}",
                            status_code=303)


@app.get("/acceso/alta/{codigo}")
def canjear_alta(request: Request, codigo: str):
    """El aparato escanea el QR y aterriza aquí. Una sola vez.

    🔴 Esta ruta está en `SIN_PUERTA` —tiene que estarlo, es por donde se entra
    la primera vez— así que es la única que un aparato sin dar de alta puede
    tocar. Lo que la protege es que el código es de un solo uso, caduca en
    `acceso.MINUTOS_DE_ALTA` y son 128 bits: probar códigos no lleva a ningún sitio.
    """
    testigo = acceso.canjear(codigo)
    if not testigo:
        return PlainTextResponse(
            "Este código ya no vale: o se usó, o caducó, o nunca existió.\n\n"
            "Genera otro desde la pantalla de Acceso del hub.\n",
            status_code=410,
        )
    respuesta = RedirectResponse("/", status_code=303)
    respuesta.set_cookie(
        acceso.COOKIE, testigo,
        max_age=acceso.DIAS_DE_COOKIE * 24 * 3600,
        httponly=True,   # que el JS de la página no pueda leerla
        samesite="lax",  # que no viaje en una petición nacida en otro sitio
        # 🔴 Segura sólo si se entró por https, nunca «siempre». Marcarla
        # siempre haría que el navegador la tirara al darse de alta desde casa
        # por `http://127.0.0.1:8787`, y el aparato quedaría dado de alta en el
        # archivo y fuera del hub — un fallo mudo justo donde no hay reintento.
        secure=_esquema(request) == "https",
        path="/",
    )
    return respuesta


@app.post("/acceso/revocar")
def revocar_dispositivo(dispositivo_id: str = Form(...)):
    acceso.revocar(dispositivo_id)
    return RedirectResponse("/acceso", status_code=303)


@app.post("/acceso/terminal")
def interruptor_terminal(abrir: int = Form(...)):
    acceso.abrir_terminal_remota(bool(abrir))
    return RedirectResponse("/acceso", status_code=303)


@app.get("/respaldo")
def respaldo(request: Request, proyecto: str = "", no_medido: str = ""):
    """Qué trabajo hay hoy sin respaldar. La razón de ser del hub."""
    con = conexion()
    try:
        return _vista(
            request,
            "respaldo.html",
            {
                "r": api.respaldo(con, proyecto or None),
                "proyecto": proyecto,
                # Por qué el último intento de medir no llegó a nada. Hace falta
                # aparte de `hay_git` porque el caso peor —git instalado pero que
                # falla, `dubious ownership` en `/mnt/c`— deja `hay_git` en True
                # y sin esto la pantalla no tendría nada que decir.
                "no_medido": no_medido,
                "titulo": "Respaldo",
                "seccion": "respaldo",
            },
        )
    finally:
        con.close()


@app.post("/respaldo/escanear")
def respaldo_escanear():
    con = conexion()
    try:
        try:
            repos_git.escanear(con, registry.cargar())
        except repos_git.RespaldoNoMedido as exc:
            # Lo que había se queda: borrarlo y enseñar cero sería afirmar que
            # no hay nada sin respaldar cuando lo que pasa es que no se ha
            # podido mirar. Y se devuelve el motivo, porque el caso peor —git
            # instalado pero que falla— deja `hay_git` en True y sin esto la
            # pantalla no tendría nada que decir.
            print(f"[respaldo] {exc}", flush=True)
            busqueda.reindexar(con)
            return _volver("/respaldo?no_medido=" + quote(str(exc)))
        busqueda.reindexar(con)
    finally:
        con.close()
    return _volver("/respaldo")


@app.get("/consumo")
def vista_consumo(request: Request, proyecto: str = ""):
    """Cuántos tokens ha costado cada proyecto.

    El filtro recorta la tabla pero **no** las cifras de cabecera ni el reparto,
    al revés que `/respaldo`. Aquí el dato es comparativo —qué proyecto pesa más
    de todo lo gastado— y recalcular el total sobre un solo proyecto daría
    siempre 100 %, que no dice nada.
    """
    con = conexion()
    try:
        datos = api.consumo(con)
        if proyecto:
            datos = {**datos,
                     "proyectos": [e for e in datos["proyectos"]
                                   if e["proyecto_id"] == proyecto]}
        return _vista(request, "consumo.html", {
            "titulo": "Consumo", "seccion": "consumo",
            "c": datos, "proyecto": proyecto,
        })
    finally:
        con.close()


@app.get("/servicios")
def servicios_vista(request: Request, docker: str = "", proyecto: str = ""):
    """De quién es cada contenedor, antes de parar ninguno."""
    con = conexion()
    try:
        return _vista(
            request,
            "servicios.html",
            {
                "s": api.servicios(con, proyecto or None),
                "proyecto": proyecto,
                "hay_docker": servicios.disponible(),
                "docker_mudo": docker == "no",
                "titulo": "Servicios",
                "seccion": "servicios",
            },
        )
    finally:
        con.close()


@app.post("/servicios/escanear")
def servicios_escanear():
    con = conexion()
    try:
        servicios.escanear(con, registry.cargar())
        busqueda.reindexar(con)
    except servicios.NoRespondio:
        # La tabla anterior queda intacta: mejor un dato viejo y fechado que
        # un cero que se lee como «no tienes contenedores».
        return _volver("/servicios?docker=no")
    finally:
        con.close()
    return _volver("/servicios")


@app.post("/api/servicio/accion")
async def api_servicio_accion(request: Request):
    """Arranca o para UN contenedor.

    Nunca en lote: el accidente que documentaba un proyecto real es exactamente
    `docker stop $(docker ps -q)` llevándose contenedores de otros proyectos.
    """
    cuerpo = await request.json()
    try:
        servicios.accionar(cuerpo.get("contenedor", ""), cuerpo.get("accion", ""))
    except servicios.AccionInvalida as exc:
        return {"ok": False, "error": str(exc)}
    con = conexion()
    try:
        servicios.escanear(con, registry.cargar())
    finally:
        con.close()
    return {"ok": True}


@app.get("/conexiones")
def conexiones_vista(request: Request, error: str = ""):
    """Dónde despliega cada cosa y dónde vive su credencial — nunca la credencial."""
    con = conexion()
    try:
        return _vista(
            request,
            "conexiones.html",
            {
                "cs": api.conexiones(con),
                "proyectos": api.listar_proyectos(con),
                "error": error,
                "titulo": "Conexiones",
                "seccion": "conexiones",
            },
        )
    finally:
        con.close()


@app.post("/conexiones/nueva")
async def conexiones_nueva(request: Request):
    """Da de alta una conexión escribiendo en `projects.yml`.

    El YAML sigue mandando (decisión 7): esto no crea una segunda fuente de
    verdad, escribe en la única que hay y luego reindexa. Lo que se gana es no
    tener que abrir un editor para algo de seis campos.
    """
    formulario = await request.form()
    datos = {k: formulario.get(k, "") for k in
             ("alias", "host", "usuario", "proposito", "referencia_secreto", "nota")}
    datos["proyectos"] = formulario.getlist("proyectos")
    try:
        registry.añadir_conexion(datos)
    except registry.YamlInvalido as exc:
        return _volver(f"/conexiones?error={quote(str(exc))}")
    except OSError as exc:
        # HUB_HOME de sólo lectura o disco lleno: el alta escribe en disco y
        # sólo se capturaba el YAML mal formado, así que esto salía como 500.
        return _volver(f"/conexiones?error={quote(f'no se pudo escribir: {exc}')}")
    con = conexion()
    try:
        conexiones_mod.sincronizar(con, registry.cargar_conexiones())
        busqueda.reindexar(con)
    finally:
        con.close()
    return _volver("/conexiones")


# ───────────────────────── canal de consulta ─────────────────────────
#
# Quién puede recibir preguntas de qué proyecto, y qué ha pasado por el canal.
# 🔴 Aquí NO se manda nada: preguntar es de `hub preguntar` y del relé. Esta
# pantalla concede y audita, que son las dos cosas que sólo puede hacer él.


# Cuántas entradas del registro por página. 40 es lo que cabe sin scroll infinito
# y sin obligar a paginar por todo: el registro crece y no se poda nunca, porque
# es la auditoría de lo que sale de la máquina.
POR_PAGINA = 40


@app.get("/archivos")
def archivos_vista(request: Request, ruta: str = ""):
    """Qué hay y dónde, sin poder tocarlo.

    Nació de un caso de viaje: estando fuera le preguntan «¿tienes el repo tal?»
    y la respuesta vive en una máquina que no tiene delante. Por eso enseña
    nombres y rutas y **nada más** —ni contenido, ni escritura, ni ejecutar—, que
    es lo que la deja fuera del interruptor de terminal (decisión 163): se puede
    usar con la terminal remota apagada.

    Los errores de confinamiento se pintan como aviso y no como 500: el que los
    ve está lejos, y un error genérico ahí no se puede depurar.
    """
    con = conexion()
    try:
        error = ""
        try:
            datos = api.explorar(con, ruta)
        except (navegador.FueraDeRaiz, navegador.NoNavegable) as exc:
            error, datos = str(exc), api.explorar(con, "")
        return _vista(
            request,
            "archivos.html",
            {
                "d": datos,
                "error": error,
                # Las plantillas con huecos (decisión 251). Se leen aquí y no en
                # el módulo de la pantalla porque la costura de lectura es
                # `api.py` y sus vecinos, nunca la plantilla.
                "comandos": [
                    {**c, "huecos": comandos.huecos(c["plantilla"])}
                    for c in comandos.leer()
                ],
                "titulo": "Archivos",
                "seccion": "archivos",
            },
        )
    finally:
        con.close()


@app.get("/maquina")
def maquina_vista(request: Request):
    """Cómo está el equipo de casa cuando no hay nadie delante.

    Lee lo que midió el ciclo lento y **no vuelve a medir**: la pantalla se abre
    para mirar, y lanzar `nvidia-smi` y un `powershell` en cada visita metería
    un segundo de espera en algo que se consulta desde el móvil (regla dura 14).
    Por eso dice la hora de la lectura en vez de dar el dato como si fuera de
    ahora mismo.
    """
    con = conexion()
    try:
        medidas = maquina.ultimas(con)
        limites = avisos.limites_maquina(rele.ajustes())
        dueno = canal.dueno(con)
        return _vista(
            request,
            "maquina.html",
            {
                "medidas": medidas,
                "tarjetas": _tarjetas_de_maquina(medidas, limites),
                "medido_en": max(
                    (m["medido_en"] for m in medidas.values()), default=""
                ),
                "limites": limites,
                "armadas": bool(dueno) and avisos.activos(rele.ajustes()),
                "dueno_nombre": canal.nombre_visible(dueno) if dueno else "",
                "titulo": "Máquina",
                "seccion": "maquina",
            },
        )
    finally:
        con.close()


def _tarjetas_de_maquina(medidas: dict, limites: dict) -> list[dict]:
    """Las cifras de arriba, en el orden en que se miran con prisa.

    El orden no es decorativo: primero lo que puede matar la máquina estando
    sola —calor y disco—, y después lo que sólo dice cómo va. `urge` se calcula
    con el MISMO límite con el que avisa el relé: dos números distintos para la
    misma cosa es cómo se aprende a no creerse ninguno.
    """
    def numero(clave: str) -> float | None:
        medida = medidas.get(clave) or {}
        return medida.get("valor")

    filas = []
    temperatura = numero("gpu.temperatura")
    if temperatura is not None:
        filas.append({
            "nombre": "GPU", "valor": f"{temperatura:.0f}", "unidad": "°C",
            "icono": "aviso" if temperatura >= limites["temperatura"] else "punto",
            "urge": temperatura >= limites["temperatura"],
            "pie": (medidas.get("gpu.nombre") or {}).get("texto", ""),
        })
    for clave, nombre in (
        ("disco.windows", "Disco de Windows"), ("disco.wsl", "Disco de WSL"),
    ):
        libre, uso = numero(f"{clave}.libre"), numero(f"{clave}.uso")
        if libre is None:
            continue
        filas.append({
            "nombre": nombre, "valor": f"{libre:.0f}", "unidad": "GB libres",
            "icono": "pilas",
            "urge": libre <= limites["disco"],
            "pie": f"{uso:.0f} % ocupado" if uso is not None else "",
        })
    # El SAI va justo después del calor y el disco: es el único dato que avisa
    # de algo que está pasando AHORA en la casa, no de cómo va el equipo.
    estado_ups = numero("ups.estado")
    if estado_ups is not None:
        sobre_bateria = estado_ups == maquina.SOBRE_BATERIA
        minutos, carga_ups = numero("ups.minutos"), numero("ups.carga")
        filas.append({
            "nombre": "SAI",
            "valor": "sin luz" if sobre_bateria else "con luz",
            "unidad": "",
            "urge": sobre_bateria,
            "icono": "aviso" if sobre_bateria else "escudo",
            "pie": " · ".join(
                p for p in (
                    f"{carga_ups:.0f} % de batería" if carga_ups is not None else "",
                    f"~{minutos:.0f} min de margen" if minutos is not None else "",
                    (medidas.get("ups.nombre") or {}).get("texto", ""),
                ) if p
            ),
        })

    memoria, carga, uso_gpu = numero("memoria.libre"), numero("carga"), numero("gpu.uso")
    if memoria is not None:
        filas.append({"nombre": "Memoria de WSL", "valor": f"{memoria:.1f}",
                      "unidad": "GB libres", "urge": False, "pie": "",
                      "icono": "rejilla"})
    if carga is not None:
        filas.append({"nombre": "Carga", "valor": f"{carga:.2f}", "unidad": "",
                      "urge": False, "pie": "media del último minuto",
                      "icono": "lineas"})
    if uso_gpu is not None:
        filas.append({"nombre": "Uso de GPU", "valor": f"{uso_gpu:.0f}", "unidad": "%",
                      "urge": False, "pie": "", "icono": "lineas"})
    return filas


@app.get("/intercambio")
def intercambio_vista(request: Request, aviso: str = "", por: str = "tema", q: str = ""):
    """La carpeta por la que pasan los archivos entre el móvil y las sesiones.

    Existe porque desde el teléfono no había forma de meter un archivo en una
    sesión ni de sacar lo que produjo, y las dos formas obvias estaban
    prohibidas: escribir dentro de un proyecto (la primera regla) y leer el
    contenido de cualquier archivo indexado (decisión 203). Esta carpeta es del
    hub, y en las dos direcciones hay un gesto humano en medio.
    """
    con = conexion()
    try:
        return _vista(
            request,
            "intercambio.html",
            {
                "i": api.intercambio(por, q),
                "limite": intercambio.tamano(intercambio.LIMITE),
                "carpeta": str(intercambio.carpeta()),
                # A qué sesión se le puede pasar la ruta. Del último muestreo,
                # igual que en el canal: quién puede recibirla de verdad lo
                # comprueba `entrega` en el instante de escribir (regla 15).
                "paneles": [p for p in api.paneles_abiertos(con) if p.get("slot_id")],
                "aviso": aviso,
                "titulo": "Intercambio",
                "seccion": "intercambio",
            },
        )
    finally:
        con.close()


@app.post("/intercambio/subir")
async def intercambio_subir(archivo: UploadFile = File(...)):
    """Lo que llega del móvil aterriza en la carpeta del hub y en ningún otro sitio."""
    try:
        datos = await archivo.read()
        destino = intercambio.guardar(archivo.filename or "archivo", datos)
    except ValueError as exc:
        return _volver("/intercambio", f"No se subió: {exc}")
    return _volver("/intercambio", f"Subido como «{destino.name}».")


@app.get("/intercambio/bajar/{nombre:path}")
def intercambio_bajar(nombre: str):
    """Descarga. Sólo de esta carpeta: lo que esté aquí lo puso alguien a mano."""
    try:
        destino = intercambio.resolver(nombre)
    except ValueError as exc:
        return _volver("/intercambio", str(exc))
    return FileResponse(destino, filename=destino.name,
                        media_type="application/octet-stream")


@app.post("/intercambio/borrar")
async def intercambio_borrar(request: Request):
    """Borrar es un acto humano, y aquí no se poda nada solo (principio 9)."""
    formulario = await request.form()
    try:
        intercambio.borrar(str(formulario.get("nombre") or ""))
    except (ValueError, OSError) as exc:
        return _volver("/intercambio", f"No se borró: {exc}")
    return _volver("/intercambio")


@app.post("/intercambio/a-la-sesion")
async def intercambio_a_la_sesion(request: Request):
    """Pega la RUTA del archivo en el panel de una sesión, sin Enter.

    Es lo que convierte «lo subí» en «la sesión puede usarlo»: Claude Code lee
    un archivo por su ruta, y teclear esa ruta en un móvil es justo lo que no se
    puede hacer. Se escribe **sin Enter** para que puedas añadir a mano qué
    quieres que haga con él.

    Que ahí siga corriendo un agente se comprueba **en el instante de escribir**
    (regla dura 15), no al pintar la lista.
    """
    formulario = await request.form()
    pane_id = str(formulario.get("pane_id") or "").strip()
    try:
        destino = intercambio.resolver(str(formulario.get("nombre") or ""))
    except ValueError as exc:
        return _volver("/intercambio", str(exc))

    apto, motivo = entrega.panel_apto(pane_id)
    if not apto:
        return _volver("/intercambio", f"No se pudo escribir ahí: {motivo}")
    try:
        tmux.pegar_en_panel(pane_id, str(destino), enter=False)
    except Exception as exc:  # noqa: BLE001 — en voz alta (regla dura 21)
        return _volver("/intercambio", f"No se pudo escribir ahí: {exc}")
    return _volver("/intercambio", "Ruta escrita en la sesión, sin Enter.")


@app.get("/orquestador")
def orquestador_vista(request: Request, tarea: str = "", proyecto: str = "", aviso: str = ""):
    """La casa del orquestador: la tarea en curso, su bandeja, la cola y los permisos.

    Pensada para el teléfono: es desde donde se le van a dar las tareas estando
    fuera, y desde donde se contesta lo que pregunta (PLAN-ORQUESTADOR.md).
    """
    con = conexion()
    try:
        return _vista(request, "orquestador.html", {
            "o": api.orquestador(con, tarea, proyecto),
            "aviso": aviso,
            "titulo": "Orquestador",
            "seccion": "orquestador",
        })
    finally:
        con.close()


@app.get("/orquestador/permisos")
def orquestador_permisos_vista(request: Request, aviso: str = ""):
    """Aparte de las tareas: se conceden una vez y se revisan de tarde en tarde,
    y en la misma página se iban quedando debajo de la lista, cada vez más lejos."""
    con = conexion()
    try:
        return _vista(request, "orquestador_permisos.html", {
            "p": api.orquestador_permisos(con),
            "aviso": aviso,
            "titulo": "Orquestador · permisos",
            "seccion": "orquestador",
        })
    finally:
        con.close()


@app.post("/orquestador/tarea")
async def orquestador_nueva(request: Request):
    formulario = await request.form()
    try:
        tarea_id = orquestador.crear(str(formulario.get("pedido") or ""),
                                     str(formulario.get("origen") or "texto"))
    except ValueError as exc:
        return _volver("/orquestador", f"No se encoló: {exc}")
    # Si no hay otra en curso, arranca en el siguiente latido del snapshotter
    # (≤ 20 s). No se arranca desde aquí: hub-web no despierta agentes, y un
    # solo sitio que lo haga es lo que mantiene la cola en orden.
    return _volver(f"/orquestador?tarea={tarea_id}",
                   "Encolada. Arranca en unos segundos si no hay otra en curso.", fugaz=True)


@app.post("/orquestador/responder")
async def orquestador_responder(request: Request):
    formulario = await request.form()
    tarea_id = str(formulario.get("tarea_id") or "")
    try:
        orquestador.responder(tarea_id, str(formulario.get("texto") or ""),
                              str(formulario.get("origen") or "texto"))
    except ValueError as exc:
        return _volver(f"/orquestador?tarea={quote(tarea_id)}", f"No se mandó: {exc}")
    return _volver(f"/orquestador?tarea={quote(tarea_id)}", "Respuesta entregada: sigue trabajando.", fugaz=True)


@app.post("/orquestador/detener")
async def orquestador_detener(request: Request):
    formulario = await request.form()
    tarea_id = str(formulario.get("tarea_id") or "")
    try:
        r = orquestador.detener(tarea_id)
    except ValueError as exc:
        return _volver("/orquestador", f"No se detuvo: {exc}")
    if not r["ok"]:
        return _volver(f"/orquestador?tarea={quote(tarea_id)}", f"No se detuvo: {r['motivo']}.")
    extra = f" Interrumpidas: {', '.join(r['interrumpidas'])}." if r["interrumpidas"] else ""
    return _volver(f"/orquestador?tarea={quote(tarea_id)}", "Detenida." + extra, fugaz=True)


@app.post("/orquestador/reanudar")
async def orquestador_reanudar(request: Request):
    formulario = await request.form()
    tarea_id = str(formulario.get("tarea_id") or "")
    try:
        r = orquestador.reanudar(tarea_id, str(formulario.get("nota") or ""))
    except ValueError as exc:
        return _volver(f"/orquestador?tarea={quote(tarea_id)}", f"No se reanudó: {exc}")
    if r["en_cola"]:
        return _volver(f"/orquestador?tarea={quote(tarea_id)}",
                       "Vuelve a la cola: sigue cuando acabe la que está en curso.", fugaz=True)
    return _volver("/orquestador", "Reanudada: el orquestador sigue en el próximo latido.", fugaz=True)


@app.post("/orquestador/permiso")
async def orquestador_permiso(request: Request):
    """🔴 El único sitio donde se conceden permisos al orquestador (decisión 256).

    Ninguna orden de `./orq` escribe aquí. Un guardrail `never` en projects.yml
    gana siempre, se ponga aquí lo que se ponga (regla dura 7).
    """
    formulario = await request.form()
    proyecto_id = str(formulario.get("proyecto_id") or "")
    nivel = str(formulario.get("nivel") or "")
    con = conexion()
    try:
        proyecto = api.obtener_proyecto(con, proyecto_id)
        if not proyecto:
            return _volver("/orquestador/permisos", f"No existe el proyecto «{proyecto_id}».")
        # La pantalla ni ofrece el selector, pero el servidor no puede fiarse
        # de eso: guardar y contestar «Guardado» sobre un `never` engaña,
        # aunque luego `nivel_de` no lo aplique (regla dura 7).
        if proyecto.get("guardrail") == "never" and nivel != "nada":
            return _volver(
                "/orquestador/permisos",
                f"«{proyecto_id}» tiene guardrail never en projects.yml: el "
                "orquestador no llega ahí. Cámbialo primero allí si quieres darle nivel.")
    finally:
        con.close()
    try:
        orquestador.fijar_nivel(proyecto_id, nivel)
    except ValueError as exc:
        return _volver("/orquestador/permisos", f"No se cambió: {exc}")
    return _volver("/orquestador/permisos", f"Guardado: {proyecto_id} en «{nivel}».", fugaz=True)


@app.post("/orquestador/audio")
def orquestador_audio(audio: UploadFile = File(...)):
    """Pasa a texto lo que se grabó. Devuelve el texto; no manda nada.

    `def` y no `async def`: transcribir tarda segundos y bloquearía el bucle
    de eventos entero —la terminal incluida—. FastAPI lo corre en su pool.
    """
    from . import transcribir

    try:
        texto = orquestador.transcribir_audio(audio.file.read(), audio.filename or "audio.webm")
    except (ValueError, transcribir.SinTranscriptor, transcribir.NoSeEntendio) as exc:
        return JSONResponse({"ok": False, "error": str(exc)})
    return JSONResponse({"ok": True, "texto": texto})


@app.post("/archivos/terminal")
async def archivos_terminal(request: Request):
    """Abre una ventana de tmux en esa carpeta, con el comando escrito y sin Enter.

    🔴 **No ejecuta nada**, y de eso depende que el navegador siga viviendo
    fuera del interruptor de la terminal (decisiones 203 y 163): crear la
    ventana y dejar la orden escrita es el tercer caso de la regla dura 15, el
    mismo de «Restaurar». El Enter lo pone una persona.

    La carpeta se resuelve **contra las raíces indexadas** antes de tocar tmux:
    lo que llega es texto de un formulario, y abrir una ventana en una ruta que
    nadie declaró sería salirse del confinamiento por la puerta de atrás.
    """
    formulario = await request.form()
    ruta = str(formulario.get("ruta") or "").strip()
    id_comando = str(formulario.get("comando") or "").strip()
    volver = f"/archivos?ruta={quote(ruta)}"

    con = conexion()
    try:
        try:
            destino = navegador.resolver(ruta, api._confin(con))
        except (navegador.FueraDeRaiz, navegador.NoNavegable) as exc:
            return _volver(volver, str(exc))
        if not destino.is_dir():
            return _volver(volver, "sólo se puede abrir una terminal en una carpeta")

        texto = ""
        if id_comando:
            comando = comandos.por_id(id_comando)
            if not comando:
                return _volver(volver, f"no hay ningún comando «{id_comando}»")
            valores = {
                h: str(formulario.get(f"hueco_{h}") or "")
                for h in comandos.huecos(comando["plantilla"])
            }
            # La carpeta de donde salió el botón rellena `{ruta}` sola: es el
            # dato que el móvil no puede teclear y el que da sentido a todo esto.
            valores.setdefault("ruta", str(destino))
            if not (valores.get("ruta") or "").strip():
                valores["ruta"] = str(destino)
            try:
                texto = comandos.expandir(comando["plantilla"], valores)
            except comandos.ComandoInvalido as exc:
                return _volver(volver, f"no se escribió nada: {exc}")

        proyecto_id = api._atribuidor(con).atribuir(str(destino))
        session = slots.sesion_para(con, proyecto_id) if proyecto_id else "hub"
        try:
            slots.abrir_en(str(destino), destino.name or "archivos", session, texto)
        except Exception as exc:  # noqa: BLE001 — se dice en voz alta (regla 21)
            return _volver(volver, f"no se pudo abrir la ventana: {exc}")
    finally:
        con.close()
    return _volver(f"/trabajo?session={quote(session)}")


@app.get("/canal")
def canal_vista(
    request: Request,
    error: str = "",
    dir: str = "",
    quien: int | None = None,
    proy: str = "",
    pag: int = 1,
    psit: str = "",
    pproy: str = "",
):
    """La matriz de permisos y el registro de todo lo que entra y sale.

    Los filtros del registro van por la URL y no por JavaScript: así una vista
    filtrada se puede guardar, compartir y recargar, y la página sigue siendo
    HTML servido (decisión 23).
    """
    con = conexion()
    try:
        pag = max(1, int(pag or 1))
        filtros = {
            "direccion": dir or None,
            "user_id": quien,
            "proyecto_id": proy or None,
        }
        total = canal.cuenta_registro(con, **filtros)
        vistas = canal.preguntas(con, pproy or None, situacion=psit or None)
        return _vista(
            request,
            "canal.html",
            {
                "usuarios": canal.usuarios(con),
                "proyectos": api.listar_proyectos(con),
                "acciones": canal.ACCIONES,
                "preguntas": vistas[:30],
                # Las dos cifras: sin la de arriba, un filtro que deja 30 y el
                # tope que deja 30 se ven exactamente igual.
                "preg_mostradas": len(vistas[:30]),
                "preg_total": len(vistas),
                "preg_todas": canal.cuenta_preguntas(con),
                "preg_filtros": {"psit": psit, "pproy": pproy},
                "situaciones": tuple(canal.SITUACIONES),
                # Los paneles a los que se puede empujar a mano una respuesta
                # que nació sin destino. Salen del último muestreo y no de
                # preguntarle a tmux uno por uno: la comprobación de verdad la
                # hace `entrega` en el instante de escribir (regla dura 15), y
                # consultar veinte paneles para pintar un desplegable haría
                # lenta una pantalla que se abre para leer.
                "paneles": [
                    p for p in api.paneles_abiertos(con) if p.get("slot_id")
                ],
                "registro": canal.registro(
                    con, POR_PAGINA, desde=(pag - 1) * POR_PAGINA, **filtros
                ),
                "reg_total": total,
                "reg_pag": pag,
                "reg_paginas": max(1, -(-total // POR_PAGINA)),
                "reg_filtros": {"dir": dir, "quien": quien, "proy": proy},
                "direcciones": ("sale", "entra", "falla"),
                "canal_estado": rele.estado(),
                "avisos": avisos.panorama(con, rele.ajustes(), canal.dueno(con)),
                "error": error,
                "titulo": "Canal",
                "seccion": "canal",
            },
        )
    finally:
        con.close()


@app.post("/canal/usuario")
async def canal_usuario(request: Request):
    """Alias, estado y nota. Dar de alta es SIEMPRE un acto suyo, y pasa aquí."""
    formulario = await request.form()
    con = conexion()
    try:
        user_id = int(formulario.get("user_id") or 0)
        canal.editar_usuario(
            con,
            user_id,
            alias=formulario.get("alias"),
            estado=formulario.get("estado"),
            nota=formulario.get("nota"),
        )
        # Sólo se toca si esta persona pasa a serlo o deja de serlo: una casilla
        # sin marcar en OTRA ficha no puede desmarcar al dueño de golpe.
        if formulario.get("es_dueno"):
            canal.marcar_dueno(con, user_id)
        elif (actual := canal.dueno(con)) and actual["user_id"] == user_id:
            canal.marcar_dueno(con, None)
        con.commit()
    except (canal.CanalInvalido, ValueError) as exc:
        return _volver(f"/canal?error={quote(str(exc))}")
    finally:
        con.close()
    return _volver("/canal")


@app.post("/canal/pregunta/{pregunta_id}/entregar")
async def canal_entregar(pregunta_id: int, request: Request):
    """Empuja a mano una respuesta que nació sin panel al que volver.

    El hub no adivina el destino: lo elige él viendo qué hay abierto
    (principio 9). Lo único que el hub sí decide, y en el último instante, es si
    en ese panel se puede escribir — de eso se encarga `entrega` (regla dura
    15), así que aquí no se comprueba nada que pueda cambiar antes de escribir.
    """
    formulario = await request.form()
    pane_id = str(formulario.get("pane_id") or "").strip()
    con = conexion()
    try:
        pregunta = canal.ver_pregunta(con, pregunta_id)
        if not pregunta or not pregunta["respuesta"]:
            return _volver("/canal?error=" + quote("esa pregunta todavía no tiene respuesta"))
        panel = api.panel_por_id(con, pane_id) if pane_id else None
        if panel is None:
            return _volver("/canal?error=" + quote("ese panel ya no sale en el último muestreo"))
        canal.apuntar_destino(con, pregunta_id, pane_id, panel.get("slot_id"))
        con.commit()
        entregada = rele.entregar_respuesta(con, pregunta_id)
        con.commit()
        if entregada:
            return _volver("/canal")
        # El motivo lo escribió `entrega` en `detalle`; enseñarlo es lo que
        # convierte «no se pudo» en algo que se puede arreglar.
        motivo = (canal.ver_pregunta(con, pregunta_id) or {}).get("detalle") or "no se pudo escribir en ese panel"
        return _volver("/canal?error=" + quote(motivo))
    except (canal.CanalInvalido, ValueError) as exc:
        return _volver(f"/canal?error={quote(str(exc))}")
    finally:
        con.close()


@app.post("/canal/tutorial")
async def canal_tutorial(request: Request):
    """Encola el tutorial. **No lo manda**: eso es del relé, que es quien tiene
    el token. `hub-web` no puede escribirle a nadie ni queriendo."""
    formulario = await request.form()
    con = conexion()
    try:
        canal.pedir_tutorial(con, int(formulario.get("user_id") or 0))
        con.commit()
    except (canal.CanalInvalido, ValueError) as exc:
        return _volver(f"/canal?error={quote(str(exc))}")
    finally:
        con.close()
    return _volver("/canal")


@app.post("/canal/permiso")
async def canal_permiso(request: Request):
    """Concede o revoca UNA acción sobre UN proyecto. No hay atajos por diseño."""
    formulario = await request.form()
    con = conexion()
    try:
        user_id = int(formulario.get("user_id") or 0)
        proyecto_id = str(formulario.get("proyecto_id") or "")
        accion = str(formulario.get("accion") or "")
        if formulario.get("quitar"):
            canal.revocar(con, user_id, proyecto_id, accion)
        else:
            canal.conceder(con, user_id, proyecto_id, accion)
        con.commit()
    except (canal.CanalInvalido, ValueError) as exc:
        return _volver(f"/canal?error={quote(str(exc))}")
    finally:
        con.close()
    return _volver("/canal")


@app.post("/api/pregunta")
async def api_pregunta(request: Request):
    """Registra una pregunta. **No la manda**: eso es del relé, en su vuelta.

    Separado a propósito. Si esto hablara con Telegram, `hub-web` —que expone el
    puerto y con él una shell (regla dura 8)— necesitaría el token, y la única
    razón de que el relé sea un proceso aparte es que no lo tenga.
    """
    datos = await request.json()
    con = conexion()
    try:
        destino = str(datos.get("a") or "").strip()
        user_id = None
        if destino and destino.lower() not in ("mi", "mí", "yo", "dueño", "dueno"):
            usuario = canal.por_alias(con, destino)
            if not usuario:
                return {"ok": False, "error": f"no conozco a «{destino}»: nadie con ese alias"}
            user_id = usuario["user_id"]

        # Varias preguntas en una sola llamada son un LOTE: viajan sueltas —cada
        # una necesita su mensaje para poder casar el reply— pero **vuelven
        # juntas**, en un solo turno. El lote nace completo aquí, y por eso
        # saber si está entero es contar filas y no adivinar si vendrán más.
        textos = datos.get("textos")
        if not isinstance(textos, list) or not textos:
            textos = [str(datos.get("texto") or "")]
        lote = str(datos.get("lote") or "").strip() or None
        if len(textos) > 1 and not lote:
            lote = canal.nombre_de_lote(str(datos.get("proyecto_id") or ""))

        creadas = [
            canal.crear_pregunta(
                con,
                str(datos.get("proyecto_id") or ""),
                str(t or ""),
                user_id=user_id,
                slot_id=datos.get("slot_id"),
                pane_id=datos.get("pane_id"),
                vence_en=datos.get("vence_en"),
                lote=lote,
            )
            for t in textos
        ]
        con.commit()
        return {"ok": True, "pregunta": canal.ver_pregunta(con, creadas[0]),
                "preguntas": [canal.ver_pregunta(con, i) for i in creadas],
                "lote": lote,
                "para": "el dueño del hub" if user_id is None else destino}
    except canal.SinPermiso as exc:
        return {"ok": False, "error": str(exc)}
    except canal.CanalInvalido as exc:
        return {"ok": False, "error": str(exc)}
    finally:
        con.close()


@app.get("/api/pregunta/{pregunta_id}")
def api_ver_pregunta(pregunta_id: int):
    con = conexion()
    try:
        pregunta = canal.ver_pregunta(con, pregunta_id)
        if not pregunta:
            return {"ok": False, "error": f"no hay ninguna pregunta {pregunta_id}"}
        return {"ok": True, "pregunta": pregunta}
    finally:
        con.close()


@app.get("/api/preguntas")
def api_preguntas(proyecto: str = "", estado: str = "", slot: int | None = None):
    con = conexion()
    try:
        return {"ok": True,
                "preguntas": canal.preguntas(con, proyecto or None, estado or None, slot)}
    finally:
        con.close()


@app.get("/contexto")
def contexto_vista(request: Request):
    """Todo el estado, escrito para pegarlo al principio de una sesión."""
    con = conexion()
    try:
        return _vista(
            request,
            "contexto.html",
            {
                "markdown": api.contexto_markdown(con),
                "titulo": "Contexto",
                "seccion": "contexto",
            },
        )
    finally:
        con.close()


@app.get("/api/contexto")
def api_contexto(formato: str = "json"):
    """La costura de lectura del asistente y del futuro MCP (decisión 25)."""
    con = conexion()
    try:
        if formato == "md":

            return PlainTextResponse(api.contexto_markdown(con))
        return api.contexto(con)
    finally:
        con.close()


@app.get("/api/buscar")
def api_buscar(q: str = "", limite: int = 20):
    """Alimenta la paleta de comandos. Devuelve destino, no sólo coincidencia."""
    con = conexion()
    try:
        return busqueda.buscar(con, q, max(1, min(limite, 50)))
    finally:
        con.close()


@app.post("/api/base/sembrar")
async def api_base_sembrar(request: Request):
    """Lanza un agente que cree la capa base dentro del proyecto.

    El hub no la escribe él: escribir dentro de otro proyecto es justo lo que
    `CLAUDE.md` prohíbe. Propone el prompt y el agente, que sí corre ahí, decide.
    """
    cuerpo = await request.json()
    proyecto_id = cuerpo.get("proyecto_id", "")
    con = conexion()
    try:
        prompt = cuerpo.get("prompt") or api.capa_base(con, proyecto_id).get("prompt_sembrar", "")
        destino = agentes.lanzar(con, proyecto_id, prompt, "capa-base")
        return {"ok": True, **destino}
    except agentes.GuardrailBloqueado as exc:
        return {"ok": False, "bloqueado": True, "error": str(exc)}
    except (ValueError, RuntimeError, tmux.DestinoInvalido) as exc:
        return {"ok": False, "error": str(exc)}
    finally:
        con.close()


@app.get("/inventario")
def inventario(
    request: Request,
    tipo: str = "",
    proyecto: str = "",
    archivadas: str = "",
    ver: str = "",
):
    """Qué tienes construido, quién lo usa y qué lleva meses sin tocarse."""
    con = conexion()
    try:
        kits = api.kits(con)
        # Los kits también obedecen al filtro de proyecto. Antes se pintaban
        # todos siempre: elegir un proyecto recortaba la lista de arriba y
        # dejaba la de abajo intacta, así que el filtro parecía a medio aplicar
        # —y de hecho lo estaba. Y el arreglo de entonces preguntaba mal: ver
        # `api.kits_de`.
        if proyecto:
            kits = api.kits_de(kits, proyecto)
        return _vista(
            request,
            "inventario.html",
            {
                "inv": api.inventario(
                    con, tipo or None, proyecto or None, archivadas=bool(archivadas)
                ),
                "kits": kits,
                "tipo": tipo,
                "ver": ver,
                "proyecto": proyecto,
                "archivadas": archivadas,
                "titulo": "Inventario",
                "seccion": "inventario",
            },
        )
    finally:
        con.close()


@app.post("/inventario/escanear")
def inventario_escanear(medir: str = Form("")):
    """Repuebla el catálogo. Medir el uso recorre los transcripts y tarda más."""
    con = conexion()
    try:
        catalogo.escanear(con, registry.cargar(), medir=bool(medir))
        busqueda.reindexar(con)
    finally:
        con.close()
    return _volver("/inventario")


@app.post("/api/agente/lanzar")
async def api_lanzar_agente(request: Request):
    """Abre una ventana de tmux con `claude` y un prompt inicial.

    El hub no ejecuta el agente: lo pone a correr donde siempre corre el trabajo.
    """
    cuerpo = await request.json()
    con = conexion()
    try:
        destino = agentes.lanzar(
            con,
            cuerpo.get("proyecto_id", ""),
            cuerpo.get("prompt", ""),
            cuerpo.get("nombre") or "agente",
        )
        return {"ok": True, **destino}
    except agentes.GuardrailBloqueado as exc:
        return {"ok": False, "bloqueado": True, "error": str(exc)}
    except (ValueError, RuntimeError, tmux.DestinoInvalido) as exc:
        return {"ok": False, "error": str(exc)}
    finally:
        con.close()


@app.post("/api/proyecto/nuevo")
async def api_proyecto_nuevo(request: Request):
    """Crea un proyecto en blanco y lanza al agente que lo rellena.

    El hub pone la carpeta vacía, los permisos acotados a ella y el alta en su
    registro; el contenido lo escribe el agente, dentro de esa carpeta y sólo
    dentro. Así se puede pedir desde el chat sin que el asistente —que es de
    sólo lectura— escriba nada.
    """
    cuerpo = await request.json()
    con = conexion()
    try:
        hecho = agentes.crear_proyecto(
            con,
            cuerpo.get("id", ""),
            cuerpo.get("nombre", ""),
            cuerpo.get("ruta", ""),
            cuerpo.get("dominio") or "personal",
            cuerpo.get("guardrail") or "ask",
            cuerpo.get("estado_ref") or "ESTADO.md",
            # Una por línea desde el formulario. Se parte aquí y no en el JS
            # porque el mismo endpoint lo usa el CLI del asistente, y dos sitios
            # partiendo la misma cadena acaban partiéndola distinto.
            rutas=[r for r in str(cuerpo.get("rutas") or "").splitlines() if r.strip()]
            if isinstance(cuerpo.get("rutas"), str) else (cuerpo.get("rutas") or []),
        )
        return {"ok": True, **hecho}
    except agentes.CarpetaOcupada as exc:
        return {"ok": False, "ocupada": True, "error": str(exc)}
    except agentes.GuardrailBloqueado as exc:
        return {"ok": False, "bloqueado": True, "error": str(exc)}
    except (ValueError, RuntimeError, OSError, registry.YamlInvalido,
            tmux.DestinoInvalido) as exc:
        return {"ok": False, "error": str(exc)}
    finally:
        con.close()


@app.post("/api/proyecto/anexar")
async def api_proyecto_anexar(request: Request):
    """Registra un proyecto que ya existe. Sólo el alta: no toca la carpeta."""
    cuerpo = await request.json()
    con = conexion()
    try:
        return {"ok": True, **agentes.anexar_proyecto(
            con, cuerpo.get("id", ""), cuerpo.get("nombre", ""), cuerpo.get("ruta", ""),
            cuerpo.get("dominio") or "personal", cuerpo.get("guardrail") or "ask",
            cuerpo.get("estado_ref") or "")}
    except (ValueError, OSError, registry.YamlInvalido) as exc:
        return {"ok": False, "error": str(exc)}
    finally:
        con.close()


@app.post("/api/kit/nuevo")
async def api_kit_nuevo(request: Request):
    """Crea el repo de un kit desde la semilla y lanza al agente que lo diseña.

    Mismo reparto que crear un proyecto: el hub pone la carpeta, la semilla y el
    alta; el diseño lo escribe el agente dentro de esa carpeta y sólo dentro.
    """
    cuerpo = await request.json()
    con = conexion()
    try:
        hecho = agentes.crear_kit(
            con,
            cuerpo.get("id", ""),
            cuerpo.get("nombre", ""),
            cuerpo.get("ruta", ""),
            cuerpo.get("guardrail") or "ask",
        )
        return {"ok": True, **hecho}
    except agentes.CarpetaOcupada as exc:
        return {"ok": False, "ocupada": True, "error": str(exc)}
    except agentes.GuardrailBloqueado as exc:
        return {"ok": False, "bloqueado": True, "error": str(exc)}
    except (ValueError, RuntimeError, OSError, registry.YamlInvalido,
            tmux.DestinoInvalido) as exc:
        return {"ok": False, "error": str(exc)}
    finally:
        con.close()


@app.get("/api/inventario")
def api_inventario(tipo: str = "", proyecto: str = ""):
    con = conexion()
    try:
        return api.inventario(con, tipo or None, proyecto or None)
    finally:
        con.close()


@app.get("/api/kits")
def api_kits():
    con = conexion()
    try:
        return api.kits(con)
    finally:
        con.close()


# ───────────────────────────── lienzos ─────────────────────────────
#
# Lo que Claude publica para que se vea aquí. La carpeta es la fuente de verdad
# (regla dura 1): estos endpoints la leen y la escriben, y no hay índice que
# mantener sincronizado.


def _ficha_lienzo(lienzo, con_cuerpo: bool = False) -> dict:
    ficha = {
        "id": lienzo.id,
        "titulo": lienzo.titulo,
        "plantilla": lienzo.plantilla,
        "proyecto_id": lienzo.proyecto_id,
        "slot": lienzo.slot,
        "publicado_en": lienzo.publicado_en,
        "archivado_en": lienzo.archivado_en,
        # Lo que decide si Claude puede republicar encima. Va en la ficha para
        # que el panel lo pueda enseñar sin una segunda llamada.
        "tuyo": lienzo.editado_por_el_usuario(),
    }
    if con_cuerpo:
        ficha["cuerpo"] = lienzo.cuerpo
    return ficha


@app.get("/api/lienzos")
def api_lienzos(proyecto: str = "", q: str = "", archivados: int = 0):
    """Los del proyecto, o los que casen con `q` en todos los proyectos.

    Buscar sale del proyecto a propósito: el panel enseña lo que tienes delante
    y buscar sirve justamente para lo que no. Y **buscar sí encuentra los
    archivados**: archivar los quita de la lista, no de la memoria.
    """
    try:
        hallados = (lienzos.buscar(q) if q
                    else (lienzos.listar(proyecto, archivados=bool(archivados))
                          if proyecto else []))
    except ValueError as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
    return {"ok": True, "lienzos": [_ficha_lienzo(l) for l in hallados]}


@app.get("/api/lienzo/{proyecto_id}/{lienzo_id}")
def api_lienzo(proyecto_id: str, lienzo_id: str):
    try:
        lienzo = lienzos.leer(proyecto_id, lienzo_id)
    except ValueError as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
    if lienzo is None:
        return JSONResponse({"ok": False, "error": "no existe"}, status_code=404)
    return {"ok": True, "lienzo": _ficha_lienzo(lienzo, con_cuerpo=True)}


@app.post("/api/lienzo")
async def api_lienzo_publicar(request: Request):
    """Publica un lienzo. Es lo que ejecuta `hub lienzo nuevo`.

    🔴 `SinPermiso` se devuelve como **409**, no como 400: no es una petición
    mal formada, es un conflicto con algo que ya existe y que el usuario tocó.
    El mensaje trae las dos salidas, y quien lo lee es un agente — así que tiene
    que poder decidir sin preguntar dos veces.
    """
    datos = await request.json()
    proyecto_id = (datos.get("proyecto_id") or "").strip()
    titulo = (datos.get("titulo") or "").strip()
    if not proyecto_id or not titulo:
        return JSONResponse(
            {"ok": False, "error": "hacen falta `proyecto_id` y `titulo`"},
            status_code=400,
        )
    try:
        lienzo = lienzos.escribir(
            proyecto_id=proyecto_id,
            titulo=titulo,
            cuerpo=datos.get("cuerpo") or "",
            plantilla=(datos.get("plantilla") or "decisiones"),
            slot=datos.get("slot") or None,
            forzar=bool(datos.get("forzar")),
            revisar=bool(datos.get("revisar")),
        )
    except lienzos.SinPermiso as exc:
        return JSONResponse({"ok": False, "error": str(exc), "conflicto": True},
                            status_code=409)
    except ValueError as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
    return {"ok": True, "lienzo": _ficha_lienzo(lienzo)}


@app.post("/api/lienzo/{proyecto_id}/{lienzo_id}/archivar")
async def api_lienzo_archivar(proyecto_id: str, lienzo_id: str, request: Request):
    """Fuera de la lista, no del disco. Reversible, y siempre un acto humano
    (principio 9: el hub no poda nada por su cuenta)."""
    datos = await request.json()
    try:
        lienzo = lienzos.archivar(proyecto_id, lienzo_id, bool(datos.get("archivar", True)))
    except ValueError as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
    if lienzo is None:
        return JSONResponse({"ok": False, "error": "no existe"}, status_code=404)
    return {"ok": True, "lienzo": _ficha_lienzo(lienzo)}


@app.post("/api/lienzo/{proyecto_id}/{lienzo_id}")
async def api_lienzo_guardar(proyecto_id: str, lienzo_id: str, request: Request):
    """Guarda lo que ha editado el usuario en la web.

    No toca `publicado_en`: esa marca es de la última vez que escribió Claude, y
    es contra ella contra la que se protege la edición.
    """
    datos = await request.json()
    try:
        lienzo = lienzos.leer(proyecto_id, lienzo_id)
    except ValueError as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
    if lienzo is None:
        return JSONResponse({"ok": False, "error": "no existe"}, status_code=404)
    lienzos.guardar_edicion(lienzo, datos.get("cuerpo") or "")
    return {"ok": True, "lienzo": _ficha_lienzo(lienzo)}


@app.delete("/api/lienzo/{proyecto_id}/{lienzo_id}")
def api_lienzo_borrar(proyecto_id: str, lienzo_id: str):
    """Borrar es del usuario (regla dura 3): el hub no poda lienzos por su cuenta."""
    try:
        borrado = lienzos.borrar(proyecto_id, lienzo_id)
    except ValueError as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)
    if not borrado:
        return JSONResponse({"ok": False, "error": "no existe"}, status_code=404)
    return {"ok": True}


def _ventana_activa(session: str) -> int | None:
    """Qué ventana de esa sesión está en primer plano, según tmux."""
    try:
        return next(v["indice"] for v in tmux.listar_ventanas(session) if v["activa"])
    except (StopIteration, tmux.DestinoInvalido):
        return None


@app.get("/guia")
def guia_vista(request: Request):
    """Por dónde empezar, y qué hay en cada pantalla."""
    con = conexion()
    try:
        return _vista(request, "guia.html", {
            "g": api.guia(con), "titulo": "Guía", "seccion": "guia",
        })
    finally:
        con.close()


@app.get("/api/guia")
def api_guia():
    con = conexion()
    try:
        return api.guia(con)
    finally:
        con.close()


@app.get("/trabajo")
def trabajo(
    request: Request,
    slot: int | None = None,
    session: str = "",
    ventana: int | None = None,
):
    """El espacio de trabajo: slots a la izquierda, terminal en medio, nota a la derecha."""
    con = conexion()
    try:
        sesiones = terminal.sesiones_disponibles()
        # Entrar por `?session=` sin decir ventana es lo normal desde la bandeja
        # y desde el panorama. Se le pregunta a tmux cuál está activa: sin eso,
        # el servidor no sabe qué ventana se está mirando y no puede ni resolver
        # su slot ni ofrecer vincularla — y elegir la primera escribiría la nota
        # en el trabajo equivocado.
        if session and ventana is None:
            ventana = _ventana_activa(session)
        ctx = api.contexto_trabajo(con, slot, session or None, ventana)
        # 🔴 «Si no hay sesión, enseña la primera» vale para entrar a /trabajo
        # sin pedir nada, y SÓLO para eso. Con un slot pedido a mano y sin
        # ventana abierta, ponía debajo la primera sesión de la lista: la barra
        # decía «test-formato» —el slot de personal-test— y la terminal que
        # cargaba era `114`, una ventana suelta de otra carpeta que no tiene
        # nada que ver con ese slot. Y como esa misma ventana sale en la bandeja
        # como no vinculada, acababa en dos sitios diciendo cosas contrarias.
        #
        # Un slot sin ventana tiene una respuesta honesta —«no hay ninguna
        # abierta, ábrela»— y prestarle la terminal de otro no lo es.
        # Se mira el slot RESUELTO y no el parámetro: un `?slot=` que ya no
        # existe —la página llevaba horas abierta y se borró— no tiene nombre
        # que enseñar en la barra, así que ahí no hay nada que contradecir y el
        # respaldo sigue siendo lo mejor que se puede hacer.
        if not ctx["session"] and sesiones and not ctx["slot"]:
            ctx["session"] = sesiones[0]["session"]
        # La barra lista VENTANAS sueltas, una por fila. Por sesión, una
        # medio organizada salía arriba bajo su slot y abajo como pendiente:
        # dos sitios diciendo cosas distintas de la misma cosa.
        sueltas, tapadas = api.bandeja_de_ventanas(con, sesiones, ctx["paneles"])
        return _vista(
            request,
            "trabajo.html",
            {
                **ctx,
                "sueltas": sueltas,
                "ocultas": tapadas,
                "slot_id": slot,
                "ancho_completo": True,
                "seccion": "trabajo",
                "titulo": (ctx["slot"] or {}).get("nombre") or ctx["session"] or "Trabajo",
            },
        )
    finally:
        con.close()


@app.get("/terminal")
def terminal_vista(session: str = ""):
    destino = f"/trabajo?session={session}" if session else "/trabajo"
    return RedirectResponse(destino, status_code=307)


@app.post("/api/slot/{slot_id}/nota")
async def api_guardar_nota(slot_id: int, request: Request):
    """Autoguardado de la nota desde la vista de trabajo."""
    cuerpo = await request.json()
    con = conexion()
    try:
        api.guardar_nota(con, slot_id, cuerpo.get("nota", ""))
        return {"ok": True}
    finally:
        con.close()


@app.get("/api/trabajo/pulso")
def api_pulso_trabajo(notas: str = ""):
    """El latido de la vista de trabajo: estado de los slots y notas frescas.

    `notas` es una lista de ids separados por coma —los del panel derecho—. Se
    filtra a dígitos aquí y no en el modelo: lo que llega de la URL no se pasa a
    una consulta sin mirarlo, aunque el parámetro sea de la propia página.
    """
    ids = [int(x) for x in notas.split(",") if x.strip().isdigit()]
    con = conexion()
    try:
        return api.pulso_trabajo(con, ids)
    finally:
        con.close()


@app.get("/api/sesion/{session}/ventanas")
def api_ventanas(session: str, slot: int | None = None):
    """🔴 Pasa por `api.py` y ya no por `tmux` a pelo.

    Llamar a `tmux.listar_ventanas` desde aquí era un camino de lectura paralelo
    —lo que `CLAUDE.md` llama defecto en su primera regla— y tenía consecuencia
    visible: tmux no sabe de slots, así que la franja de pestañas no podía decir
    que una ventana no es del slot que la cabecera anuncia.
    """
    con = conexion()
    try:
        return api.ventanas_de_sesion(con, session, slot)
    except tmux.DestinoInvalido:
        return []
    finally:
        con.close()


@app.post("/api/sesion/{session}/ventanas")
async def api_nueva_ventana(session: str, request: Request):
    cuerpo = await request.json()
    # Antes que el error crudo de tmux: «can't find session» dentro de la línea
    # de comandos entera no es lo que hay que leer en un cuadro de diálogo, y
    # este caso —cerrar la última ventana mata la sesión— es el que pasa.
    try:
        # 🔴 Dentro del `try`: `existe_sesion` valida el nombre, y un destino
        # inválido tiene que salir como el error de siempre y no como un 500.
        if not tmux.existe_sesion(session):
            return {"ok": False,
                    "error": f"la sesión «{session}» ya no existe en tmux — se habrá "
                             "cerrado su última ventana. Vuelve a abrirla desde su slot."}
        tmux.nueva_ventana(session, cuerpo.get("ruta") or None, cuerpo.get("nombre") or None)
    except (tmux.DestinoInvalido, RuntimeError) as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True}


@app.post("/api/sesion/{session}/ventana/{indice}")
async def api_editar_ventana(session: str, indice: int, request: Request):
    """Renombrar o cerrar. Cerrar mata lo que corra dentro: la UI lo confirma."""
    cuerpo = await request.json()
    try:
        if cuerpo.get("accion") == "cerrar":
            tmux.cerrar_ventana(session, indice)
        elif cuerpo.get("nombre"):
            tmux.renombrar_ventana(session, indice, cuerpo["nombre"])
    except (tmux.DestinoInvalido, RuntimeError) as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True}


@app.websocket("/ws/terminal/{session}")
async def terminal_socket(ws: WebSocket, session: str, ventana: int | None = None):
    """Transporta bytes entre xterm.js y un `tmux attach`.

    Cerrar la pestaña sólo desata el cliente: los procesos siguen vivos.

    🔴 Las tres comprobaciones van ANTES de aceptar. Este socket es una shell: es
    la superficie más peligrosa del hub y la única donde un `accept()` de más
    entrega la máquina. Se rechaza sin aceptar —código 1008— para no llegar
    siquiera a abrir el espejo del PTY.

    🔴 **Desde fuera hacen falta las dos cosas: aparato dado de alta Y el
    interruptor abierto.** Desde casa no hace falta ninguna, igual que en el
    resto del hub y por el mismo motivo: quien puede abrir este socket en
    `localhost` ya puede ejecutar `bash` en esa máquina, así que pedirle una
    cookie no defiende de nada.

    🔴 **Y esto se probó al revés primero, con daño.** La primera versión exigía
    aparato SIEMPRE —razonando que con `tailscale serve` el tráfico remoto llega
    por loopback y «parece local» no prueba nada— y como no había ningún aparato
    dado de alta, **cerró todas las terminales de la máquina**: el hub servía las
    pantallas perfectas y ninguna ventana se veía. Endurecer el endpoint que se
    usa todos los días sin probar el camino de todos los días es la forma cara de
    tener razón. Lo que aquel razonamiento defiende sigue en pie y sigue escrito
    en la decisión 173: contra un `Host: localhost` forjado desde la red privada
    quien defiende es el `tailnet lock`, no esta comprobación.
    """
    if not origen_permitido(ws.headers.get("origin")):
        await ws.close(code=1008)
        return
    # 🔴 Sin `Host` NO cuenta como de casa, al revés que en el resto del hub.
    # `acceso.es_host_local(None)` devuelve `True` a propósito —lo mandan `curl`
    # y el CLI del asistente, que no son navegadores— y para leer proyectos eso
    # está bien. Aquí no: éste es el endpoint que da una shell, y un valor por
    # defecto que abre es la clase de descuido que sólo se ve cuando ya pasó.
    anfitrion = ws.headers.get("host")
    if not anfitrion or not _es_de_casa(anfitrion):
        if not acceso.reconocer(ws.cookies.get(acceso.COOKIE)):
            await ws.close(code=1008)
            return
        # El interruptor de la decisión 163: apagado de fábrica y apagado otra
        # vez cada vez que `hub-web` reinicia.
        if not acceso.terminal_remota():
            await ws.close(code=1008)
            return
    await ws.accept()
    try:
        espejo = terminal.crear_espejo(session, ventana)
    except (terminal.DestinoInvalido, RuntimeError) as exc:
        await ws.send_bytes(f"\r\n[hub] no se pudo abrir {session}: {exc}\r\n".encode())
        await ws.close()
        return

    adjunto = terminal.Adjunto(espejo)
    salida = asyncio.create_task(terminal.bombear(adjunto, ws.send_bytes))
    try:
        while True:
            mensaje = await ws.receive()
            if mensaje["type"] == "websocket.disconnect":
                break
            if mensaje.get("bytes") is not None:
                adjunto.escribir(mensaje["bytes"])
            elif mensaje.get("text"):
                # Canal de control: el texto es JSON, los bytes son tecleo.
                # Separarlos evita tener que adivinar si escribiste JSON a mano.
                try:
                    control = json.loads(mensaje["text"])
                    if "columnas" in control:
                        adjunto.redimensionar(
                            int(control["filas"]), int(control["columnas"])
                        )
                    elif control.get("accion") == "ventana":
                        # Sobre el espejo: no arrastra a la terminal nativa.
                        tmux.seleccionar_ventana(espejo, int(control["indice"]))
                        # Una ventana creada después del espejo no heredó el
                        # ajuste automático de tamaño, y ahí es donde se pierde
                        # texto sin avisar. Es idempotente y cuesta una llamada.
                        terminal.dimensionar_al_espectador(espejo)
                except (ValueError, KeyError, TypeError, RuntimeError):
                    pass
    except WebSocketDisconnect:
        pass
    finally:
        # El orden importa y no se ve: `terminal.soltar` lo documenta y lo fija.
        await terminal.soltar(adjunto, salida)
        terminal.destruir_espejo(espejo)


# ───────────────────────── canal de encargos ─────────────────────────
#
# El otro canal, aparte del de consulta (decisión n1). Por aquí entra gente que
# no ha especificado software en su vida y cuenta su negocio hablando; de ahí
# sale un MVP. Esta pantalla es donde él lo gobierna: a quién deja escribir, qué
# encargos hay, qué se sabe de cada uno y qué se le ha dicho al bot.
#
# 🔴 Aquí NO se manda nada, igual que en `/canal` y por lo mismo (regla dura 22):
# el token lo lee `hub-encargos`, que es un servicio aparte, y `hub-web` expone
# el puerto —y con él una shell, regla dura 8—. Esta vista da de alta, crea,
# renombra y abre el agente; hablar con Telegram no es suya y no puede serlo.

# Cuántas líneas del registro se enseñan de una vez. Es un TOPE y no una página:
# `encargos.registro` no acepta desplazamiento, al revés que el del canal de
# consulta, así que aquí no se puede paginar sin tocar el dominio.
ENCARGOS_EN_REGISTRO = 60


def _encargo_para_la_lista(con, fila: dict, por_persona: dict) -> dict:
    """Un encargo con lo que hace falta para leerlo de un vistazo.

    La cuenta de sin entregar va aquí y no en la plantilla porque es lo único
    de la fila que pide una acción: un encargo con mensajes en cola y sin agente
    abierto es exactamente el caso que el buzón existe para que no se pierda.
    """
    return {
        **fila,
        "quien": encargos.nombre_visible(por_persona.get(fila["user_id"])),
        "sin_entregar": len(buzon.en_cola(con, fila["id"])),
    }


@app.get("/encargos")
def encargos_vista(request: Request, error: str = "", enc: str = ""):
    """Los encargos, quién puede mandarlos y todo lo que ha pasado por el bot.

    El filtro del registro viaja por la URL y no por JavaScript (decisión 23):
    una vista filtrada se puede guardar, compartir y recargar, que es lo que
    hace falta cuando se mira esto desde el móvil y se quiere volver luego.
    """
    con = conexion()
    try:
        gente = encargos.personas(con)
        por_persona = {p["user_id"]: p for p in gente}
        return _vista(
            request,
            "encargos.html",
            {
                "personas": gente,
                # Sólo a alguien activo se le puede abrir un encargo, así que el
                # desplegable de crear no puede ofrecer a los demás: una opción
                # que siempre falla es una trampa, no un filtro.
                "activas": [p for p in gente if p["estado"] == "activo"],
                "encargos": [_encargo_para_la_lista(con, f, por_persona)
                             for f in encargos.listar(con)],
                "propuesto": encargos.siguiente_provisional(con),
                "canal_estado": rele_encargos.estado(),
                "registro": encargos.registro(con, ENCARGOS_EN_REGISTRO, enc),
                "reg_filtro": enc,
                "error": error,
                "titulo": "Encargos",
                "seccion": "encargos",
            },
        )
    finally:
        con.close()


@app.get("/encargos/{encargo_id}")
def encargo_vista(request: Request, encargo_id: str, error: str = ""):
    """La ficha de un encargo y la conversación entera de la que salió.

    Las dos cosas juntas a propósito: la ficha es el estado y la conversación no
    (el porqué está en `encargos.py`), pero cuando algo de la ficha extraña, lo
    primero que se quiere ver es qué dijo ella exactamente.
    """
    con = conexion()
    try:
        fila = encargos.ver(con, encargo_id)
        if not fila:
            return _volver(
                "/encargos?error=" + quote(f"no hay ningún encargo «{encargo_id}»")
            )
        ficha = encargos.cargar_ficha(con, encargo_id)
        siguiente = ficha.siguiente()
        return _vista(
            request,
            "encargos.html",
            {
                "enc": fila,
                "quien": encargos.nombre_visible(
                    encargos.ver_persona(con, fila["user_id"])),
                # La ficha se aplana aquí y no en la plantilla: así la vista
                # pinta y no razona, y lo que se enseña se puede afirmar en un
                # test sin renderizar nada.
                "fases": [
                    {
                        "id": f.id, "titulo": f.titulo, "pregunta": f.pregunta,
                        "campo": f.campo, "minimo": f.minimo, "se_elige": f.se_elige,
                        "valor": ficha.campos.get(f.campo, ""),
                        "contestada": ficha.contestada(f.id),
                        "agotada": ficha.agotada(f.id),
                        "veces": ficha.preguntado.get(f.id, 0),
                        "tope": encargos.TOPE_POR_FASE,
                    }
                    for f in encargos.FASES
                ],
                "huecos": ficha.huecos(),
                "suficiente": ficha.suficiente(),
                "siguiente": siguiente.titulo if siguiente else "",
                "dicho": ficha.dicho,
                "conversacion": buzon.conversacion(con, encargo_id),
                "sin_entregar": len(buzon.en_cola(con, encargo_id)),
                "registro": encargos.registro(con, ENCARGOS_EN_REGISTRO, encargo_id),
                "canal_estado": rele_encargos.estado(),
                "error": error,
                "titulo": fila["titulo"] or fila["id"],
                "seccion": "encargos",
            },
        )
    finally:
        con.close()


@app.post("/encargos/persona")
async def encargos_persona(request: Request):
    """Alias, estado y nota. Dar de alta es SIEMPRE un acto suyo, y pasa aquí.

    Escribirle al bot no da de alta a nadie: el relé apunta quién escribió —para
    que aparezca y se pueda decidir— y el estado nace `pendiente`. Esto es lo
    único del sistema que lo mueve.
    """
    formulario = await request.form()
    con = conexion()
    try:
        user_id = int(formulario.get("user_id") or 0)
        antes = encargos.ver_persona(con, user_id) or {}
        # Sólo lo que venga en el formulario: `editar_persona` escribe tal cual
        # lo que reciba, y un campo ausente como `None` dejaría la columna a
        # NULL en una tabla que las declara `NOT NULL`.
        encargos.editar_persona(con, user_id, **{
            c: str(formulario[c]) for c in ("alias", "estado", "nota")
            if c in formulario
        })
        # La casilla de confianza: una sin marcar no viaja, así que se lee su
        # ausencia como «no» SÓLO cuando el formulario es el de esta persona
        # (lleva su alias), igual que con el dueño.
        if "alias" in formulario:
            encargos.editar_persona(
                con, user_id, de_confianza="1" if formulario.get("de_confianza") else "0")
            # A quien entra por el chat web el alias le cambia también el nombre
            # con el que la página la saluda (246). Si el chat no responde, el
            # alias se guarda igual y se dice.
            if antes.get("canal") == "web" and str(formulario["alias"]).strip():
                from . import chatweb, rele_encargos

                try:
                    chat = chatweb.bot(rele_encargos.ajustes())
                    if chat:
                        chat.renombrar(user_id, str(formulario["alias"]).strip())
                        con.execute("UPDATE encargo_persona SET nombre = ? WHERE user_id = ?",
                                    (str(formulario["alias"]).strip(), user_id))
                except Exception as exc:  # noqa: BLE001 - se dice, no se esconde
                    encargos.registrar(con, "falla", f"el chat web no tomó el nombre nuevo: {exc}",
                                       user_id=user_id)
        # Mismo matiz que `/canal/usuario`: sólo se toca si ESTA persona pasa a
        # serlo o deja de serlo. Una casilla sin marcar en otra ficha no puede
        # desmarcar al dueño de golpe.
        if formulario.get("es_dueno"):
            encargos.marcar_dueno(con, user_id)
        elif (actual := encargos.dueno(con)) and actual["user_id"] == user_id:
            encargos.marcar_dueno(con, None)
        con.commit()

        # 🔴 Dar de alta ES empezar (decisión 229): a quien acaba de pasar a
        # «activo» se le abre su encargo y su entrevistador aquí mismo, y la
        # primera pregunta le llega por el relé. Sólo en esa transición —no al
        # guardar un alias— y nunca al dueño, que aprueba y no encarga. Si no
        # se puede abrir, el alta se queda y el motivo se dice (regla dura 21).
        estrena = (formulario.get("estado") == "activo"
                   and antes.get("estado") != "activo"
                   and not formulario.get("es_dueno"))
        if estrena:
            try:
                entrevistador.empezar_con(con, user_id)
                con.commit()
            except (ValueError, RuntimeError) as exc:
                con.commit()
                return _volver("/encargos?error=" + quote(
                    f"de alta, pero no se pudo abrir su entrevista: {exc}"))
    except ValueError as exc:
        return _volver(f"/encargos?error={quote(str(exc))}")
    finally:
        con.close()
    return _volver("/encargos#personas")


@app.post("/encargos/crear")
async def encargos_crear(request: Request):
    """Abre un encargo a nombre de alguien que esté de alta.

    🔴 La comprobación es de aquí y no de `encargos.crear`, que es idempotente a
    propósito y no sabe de permisos porque lo llama el relé al ver un mensaje.
    Sin ella esta pantalla sería la puerta lateral que el alta invertida cierra:
    un encargo abierto a nombre de alguien bloqueado o que nunca se aprobó.
    """
    formulario = await request.form()
    con = conexion()
    try:
        user_id = int(formulario.get("user_id") or 0)
        encargo_id = str(formulario.get("encargo_id") or "").strip()
        if not encargos.puede_hablar(con, user_id):
            quien = encargos.nombre_visible(encargos.ver_persona(con, user_id))
            return _volver("/encargos?error=" + quote(
                f"{quien} no está de alta, así que no se le puede abrir un "
                "encargo. Dale de alta en Personas y vuelve."))
        encargos.crear(con, encargo_id, user_id)
        con.commit()
    except ValueError as exc:
        return _volver(f"/encargos?error={quote(str(exc))}")
    finally:
        con.close()
    return _volver(f"/encargos/{encargo_id}")


@app.post("/encargos/{encargo_id}/renombrar")
async def encargos_renombrar(request: Request, encargo_id: str):
    """Le pone su nombre de verdad, en cuanto se sabe cómo se llama el negocio.

    🔴 El «no» de `encargos.renombrar` sobre un encargo publicado se ENSEÑA. Es
    una barrera con motivo —el id es la URL que la persona tiene guardada—, y un
    formulario que no hace nada y tampoco lo explica se lee como una pantalla
    rota, que es justo lo que hace que se deje de usar.
    """
    formulario = await request.form()
    con = conexion()
    nuevo = encargo_id
    try:
        # 🔴 Renombrar mueve la carpeta, y un agente abierto dentro se queda
        # sin suelo (decisión 241): se cierran antes y, si el entrevistador
        # estaba trabajando, se reabre en la carpeta nueva. La ficha es el
        # estado, así que no pierde nada.
        fila = encargos.ver(con, encargo_id)
        habia_agente = bool(fila and fila["slot_id"] and entrevistador.cerrar_agentes(con, encargo_id))
        nuevo = encargos.renombrar(
            con, encargo_id, str(formulario.get("nombre") or "").strip())
        if habia_agente and fila["estado"] == "recogiendo":
            entrevistador.abrir_agente(con, nuevo)
        con.commit()
    except (ValueError, RuntimeError) as exc:
        return _volver(f"/encargos/{quote(nuevo)}?error={quote(str(exc))}")
    finally:
        con.close()
    return _volver(f"/encargos/{nuevo}")


@app.post("/encargos/persona-web", response_class=HTMLResponse)
async def encargos_persona_web(request: Request):
    """Da de alta a alguien que NO tiene Telegram: entra por la página del chat
    (decisión 246). Es el mismo alta de siempre —activo, encargo y entrevistador
    abiertos— más un usuario y una contraseña que se enseñan UNA vez aquí y no
    se guardan (regla dura 5): al servidor del chat va el hash.
    """
    from . import chatweb, rele_encargos

    formulario = await request.form()
    nombre = str(formulario.get("nombre") or "").strip()
    usuario = encargos.a_id(str(formulario.get("usuario") or nombre))
    if not nombre or not usuario:
        return _volver("/encargos?error=" + quote("hace falta un nombre para dar de alta por el chat"))
    chat = chatweb.bot(rele_encargos.ajustes())
    if chat is None:
        return _volver("/encargos?error=" + quote("el chat web no está configurado en encargos.yml (chat_web)"))
    con = conexion()
    try:
        try:
            user_id, clave = chat.crear_persona(usuario, nombre)
        except Exception as exc:  # noqa: BLE001 - se enseña, no se esconde (regla 21)
            return _volver("/encargos?error=" + quote(f"el chat web no dio de alta a «{usuario}»: {exc}"))
        encargos.anotar_persona(con, user_id, usuario, nombre)
        encargos.editar_persona(con, user_id, estado="activo", alias=nombre, canal="web")
        con.commit()
        aviso = ""
        try:
            entrevistador.empezar_con(con, user_id)
            con.commit()
        except (ValueError, RuntimeError) as exc:
            aviso = f"Queda de alta, pero el entrevistador no se abrió: {exc}"
    finally:
        con.close()
    url = str(chatweb.configurado(rele_encargos.ajustes())["url"]).rstrip("/")
    return _vista(request, "encargos_acceso.html", {
        "nombre": nombre, "usuario": usuario, "clave": clave, "url": url, "aviso": aviso,
    })


@app.post("/encargos/{encargo_id}/implementar")
async def encargos_implementar(encargo_id: str):
    """«Implementar»: la maqueta publicada pasa a ser el sistema (decisión 244).

    Es la misma decisión que el botón del canal; aquí para cuando él está en
    el hub y no en el teléfono. Lo que falle se enseña en la ficha.
    """
    from . import implementador

    con = conexion()
    try:
        implementador.empezar(con, encargo_id)
        con.commit()
    except (ValueError, RuntimeError) as exc:
        return _volver(f"/encargos/{quote(encargo_id)}?error={quote(str(exc))}")
    finally:
        con.close()
    return _volver(f"/encargos/{quote(encargo_id)}")


@app.post("/encargos/{encargo_id}/agente")
async def encargos_agente(encargo_id: str):
    """Abre el entrevistador de este encargo y vuelve a su ficha.

    Lo que falle se dice en voz alta y en la pantalla a la que se vuelve (regla
    dura 21): «no abrió nada» sin motivo es el fallo que estuvo semanas sin que
    nadie se enterase, y aquí sería peor — quien espera al otro lado es alguien
    de fuera que no tiene forma de saber que no le escucha nadie.
    """
    con = conexion()
    try:
        abierto = entrevistador.abrir_agente(con, encargo_id)
        con.commit()
    except (ValueError, RuntimeError) as exc:
        return _volver(f"/encargos/{quote(encargo_id)}?error={quote(str(exc))}")
    finally:
        con.close()
    return _volver(
        f"/encargos/{quote(encargo_id)}",
        aviso=(f"El entrevistador está abierto en «{abierto['session']}», "
               f"ventana {abierto['ventana']} — slot {abierto['slot_id']}."),
    )


# ─────────────────────────── acciones ───────────────────────────


@app.post("/refrescar")
def refrescar():
    """Toma una muestra ahora mismo, sin esperar al ciclo del demonio."""
    con = conexion()
    try:
        snapshotter.un_ciclo(con)
    finally:
        con.close()
    return _volver()


@app.post("/slot/nuevo")
def slot_nuevo(
    proyecto_id: str = Form(...),
    nombre: str = Form(...),
    ruta: str = Form(""),
    nota: str = Form(""),
    comando: str = Form(""),
    autostart_claude: str = Form(""),
):
    con = conexion()
    try:
        slots.crear(
            con,
            proyecto_id,
            nombre.strip(),
            ruta.strip() or None,
            nota,
            comando.strip() or None,
            bool(autostart_claude),
        )
    finally:
        con.close()
    return _volver(f"/proyecto/{proyecto_id}")


@app.post("/slot/{slot_id}/editar")
def slot_editar(
    slot_id: int,
    proyecto_id: str = Form(...),
    nombre: str = Form(...),
    ruta: str = Form(""),
    nota: str = Form(""),
    comando: str = Form(""),
    autostart_claude: str = Form(""),
    restaurar: str = Form(""),
    mover_a: str = Form(""),
):
    con = conexion()
    try:
        slots.editar(
            con,
            slot_id,
            nombre=nombre.strip(),
            ruta=ruta.strip() or "",
            nota=nota,
            comando=comando.strip() or "",
            autostart_claude=bool(autostart_claude),
            restaurar=bool(restaurar),
            # Un slot puede moverse entre proyectos: una investigación que empezó
            # suelta y termina perteneciendo a algo (decisión 12).
            proyecto_id=mover_a.strip() or None,
        )
    finally:
        con.close()
    return _volver(f"/proyecto/{mover_a.strip() or proyecto_id}")


@app.post("/slot/{slot_id}/estado")
def slot_estado(
    slot_id: int,
    accion: str = Form(...),
    proyecto_id: str = Form(...),
    destino: str = Form(""),
):
    """Archivar, desarchivar o borrar un slot. Las tres son actos suyos (regla 3).

    `destino` existe porque estas acciones ya no se piden sólo desde la ficha
    del proyecto: en `/trabajo` un slot sin ventana se ve con su «Lanzar» al
    lado, y devolver a la ficha a quien estaba trabajando es mandarlo a otra
    pantalla a mitad de lo suyo. Es el mismo `destino` que ya usan las acciones
    de panel, con su misma forma.
    """
    con = conexion()
    try:
        if accion == "archivar":
            slots.archivar(con, slot_id)
        elif accion == "desarchivar":
            slots.desarchivar(con, slot_id)
        elif accion == "borrar":
            slots.borrar(con, slot_id)
    finally:
        con.close()
    return _volver(destino.strip() or f"/proyecto/{proyecto_id}")


@app.post("/slot/{slot_id}/abrir")
def slot_abrir(
    slot_id: int,
    proyecto_id: str = Form(...),
    session: str = Form(""),
    destino: str = Form(""),
):
    con = conexion()
    aviso = None
    try:
        slots.abrir(con, slot_id, session.strip() or None)
    except (tmux.TmuxNoDisponible, RuntimeError, ValueError) as exc:
        # Se dice, no se traga (regla dura 21). Hasta el 3-sep un `except:
        # pass` aquí convertía «no hay servidor de tmux» en un botón que no
        # hacía nada.
        aviso = f"No se pudo abrir la ventana: {exc}"
    finally:
        con.close()
    return _volver(destino.strip() or f"/proyecto/{proyecto_id}", aviso)


@app.post("/restaurar")
def restaurar_todo(destino: str = Form(""), muestra: int | None = Form(None)):
    """El botón de después del apagón. Abre ventanas; no relanza nada.

    `muestra` viaja desde la pantalla para que lo que se abre sea **lo que
    estaba en el plan que él miró**, y no lo que el defecto elija medio segundo
    después. Sin esto, mirar un plan y ejecutar otro sería posible.
    """
    con = conexion()
    try:
        resultado = slots.restaurar(con, muestra)
    except (tmux.TmuxNoDisponible, RuntimeError) as exc:
        return _volver(destino.strip() or "/", f"No se pudo restaurar: {exc}")
    finally:
        con.close()

    cuantos = len(resultado["abiertos"])
    aviso = (f"{cuantos} ventana{'s' if cuantos != 1 else ''} abierta"
             f"{'s' if cuantos != 1 else ''} con el comando escrito, sin lanzar.")
    if resultado["fallos"]:
        aviso += " No salió todo: " + " · ".join(resultado["fallos"])
    return _volver(destino.strip() or "/", aviso)


@app.post("/panel/accion")
def panel_accion(
    pane_id: str = Form(...),
    accion: str = Form(...),
    slot_id: str = Form(""),
    nombre: str = Form(""),
    destino: str = Form("/"),
):
    con = conexion()
    try:
        if accion == "vincular" and slot_id:
            slots.vincular(con, pane_id, int(slot_id))
        elif accion == "promover":
            slots.promover(con, pane_id, nombre.strip())
        elif accion == "desvincular":
            # Suelta la ventana del slot. La nota no se toca: vive en el slot.
            slots.desvincular(con, pane_id)
        elif accion == "descartar":
            slots.descartar(con, pane_id)
        elif accion == "cerrar_ventana":
            # Cerrar de verdad, no ocultar: mata lo que corra dentro, y si es la
            # única ventana de su sesión, tmux se lleva la sesión con ella. La
            # confirmación la pone la vista; aquí sólo se ejecuta.
            #
            # Sale del `pane_id` y no del formulario por lo mismo que renombrar:
            # sesión e índice se mueven solos mientras el HTML espera abierto, y
            # cerrar la ventana equivocada no tiene deshacer.
            panel = api.panel_por_id(con, pane_id)
            if panel:
                try:
                    tmux.cerrar_ventana(panel["session"], panel["window_idx"])
                except (tmux.DestinoInvalido, RuntimeError) as exc:
                    return _volver(destino, f"No se pudo cerrar: {exc}")
        elif accion in ("ocultar", "ocultar_sesion"):
            # Ocultar NO cierra nada ni toca tmux: la ventana sigue corriendo y
            # sigue siendo suya, sólo deja de ocupar sitio en la bandeja. Es lo
            # que pidió para los servidores de node, que están siempre abiertos
            # y nunca son un trabajo.
            #
            # La sesión y el índice salen del `pane_id` y no del formulario: el
            # HTML puede llevar minutos abierto y esos dos se mueven solos.
            panel = api.panel_por_id(con, pane_id)
            if panel:
                slots.ocultar(
                    con, panel["session"],
                    None if accion == "ocultar_sesion" else panel["window_idx"],
                )
        elif accion == "renombrar_ventana" and nombre.strip():
            # Renombra la VENTANA de tmux, no el slot: en la bandeja todavía no
            # hay slot al que ponerle nombre. Ya existía por JSON —el doble clic
            # en las pestañas de /trabajo—, pero la edición en línea del
            # panorama es un formulario y necesita una entrada por POST.
            #
            # `pane_id` identifica el panel, y de él salen la sesión y el
            # índice: pedirlos por separado en el formulario sería fiarse de que
            # el HTML no se ha quedado viejo.
            panel = api.panel_por_id(con, pane_id)
            if panel:
                tmux.renombrar_ventana(
                    panel["session"], panel["window_idx"], nombre.strip()
                )
    finally:
        con.close()
    return _volver(destino)


@app.post("/oculto/mostrar")
def oculto_mostrar(
    session: str = Form(...), ventana: str = Form(""), destino: str = Form("/trabajo")
):
    """Devuelve a la bandeja algo que se había ocultado.

    Por NOMBRE y no por `pane_id`: lo oculto puede estar apagado hoy —un
    servidor de node que no se ha levantado— y entonces no hay ningún panel del
    que partir. Sin esta ruta, ocultar sería de ida y sólo se podría deshacer
    volviendo a abrir la ventana.
    """
    con = conexion()
    try:
        indice = int(ventana) if ventana.strip().isdigit() else None
        slots.mostrar(con, session, indice)
    finally:
        con.close()
    return _volver(destino)


@app.post("/recuperacion/{snapshot_id}/revisada")
def recuperacion_revisada(snapshot_id: int):
    con = conexion()
    try:
        api.marcar_recuperacion_revisada(con, snapshot_id)
    finally:
        con.close()
    return _volver()


# ─────────────────────── capa de lectura (JSON) ───────────────────────
# Los mismos datos que consume la UI. El futuro MCP se monta sobre esto.


@app.get("/api/resumen")
def api_resumen():
    con = conexion()
    try:
        return api.resumen(con)
    finally:
        con.close()


@app.get("/api/proyectos")
def api_proyectos(dominio: str | None = None):
    con = conexion()
    try:
        return api.listar_proyectos(con, dominio)
    finally:
        con.close()


@app.get("/api/proyecto/{proyecto_id}")
def api_proyecto(proyecto_id: str):
    con = conexion()
    try:
        p = api.obtener_proyecto(con, proyecto_id)
        if p:
            p["slots"] = api.slots_de(con, proyecto_id, True)
        return p or {}
    finally:
        con.close()


@app.get("/api/paneles")
def api_paneles():
    con = conexion()
    try:
        return api.paneles_abiertos(con)
    finally:
        con.close()


@app.get("/api/recuperacion")
def api_recuperacion():
    con = conexion()
    try:
        return api.recuperacion_pendiente(con) or {}
    finally:
        con.close()


@app.get("/api/respaldo")
def api_respaldo():
    con = conexion()
    try:
        return api.respaldo(con)
    finally:
        con.close()


@app.get("/api/servicios")
def api_servicios(proyecto: str = ""):
    con = conexion()
    try:
        return api.servicios(con, proyecto or None)
    finally:
        con.close()


@app.get("/api/conexiones")
def api_conexiones():
    con = conexion()
    try:
        return api.conexiones(con)
    finally:
        con.close()


@app.get("/api/conexiones/aqui")
def api_conexiones_aqui(ruta: str = ""):
    """Lo que este directorio tiene concedido: a dónde se conecta y dónde está su llave.

    Existe para que una sesión de Claude trabajando en un proyecto pueda
    preguntar «¿a qué servidor puedo entrar desde aquí?» sin que nadie le pegue
    la credencial en un archivo. Lo que devuelve es un PUNTERO (decisión 197).

    `ruta` en vez de deducirla del socket: el hub no puede saber el cwd de quien
    llama, y el cliente sí. Sus límites están en `api.conexiones_concedidas`.
    """
    con = conexion()
    try:
        return api.conexiones_concedidas(con, ruta)
    finally:
        con.close()


@app.get("/api/estado/{proyecto_id}")
def api_estado(proyecto_id: str):
    """El documento vigente del proyecto, resuelto y resumido.

    Es lo que el asistente leerá en vez de adivinar cuál de los quince
    documentos de un proyecto está al día.
    """
    con = conexion()
    try:
        return api.estado_de(con, proyecto_id)
    finally:
        con.close()


# ───────────────────────────── sesiones de Claude ─────────────────────────────


@app.get("/api/sesiones")
def api_sesiones(proyecto: str = "", desde: str = "", limite: int = 30):
    """Índice de sesiones de Claude Code: qué hubo, cuándo y de qué iba.

    El caso de uso rector: dejaste un proyecto trabajando de forma semiautónoma,
    se completó una sesión de 7 h 51 min, y al día siguiente quieres que el
    asistente te diga qué se hizo. Esto es por dónde empieza.
    """
    return {
        "sesiones": transcripts.listar_sesiones(
            registry.cargar(), proyecto or None, desde or None, min(limite, 200)
        )
    }


@app.get("/api/sesion/{session_id}")
def api_sesion(session_id: str, desde: str = "", hasta: str = "", crudo: int = 0):
    """El contenido de una sesión: esqueleto por defecto, zoom si se pide tramo.

    El esqueleto tira `thinking`, `tool_result` y el `input` de las herramientas,
    que es donde vive casi todo el volumen, y conserva **todo el texto**. Con
    `crudo=1` o con un tramo `desde`/`hasta` se baja al detalle.
    """
    ruta = transcripts.ruta_de_sesion(session_id)
    if not ruta:
        return {"ok": False, "error": f"sesión desconocida: {session_id}"}
    if crudo or desde or hasta:
        return {"ok": True, **transcripts.zoom(ruta, desde or None, hasta or None)}
    return {"ok": True, **transcripts.esqueleto(ruta)}


# ─────────────────────────────── el asistente ───────────────────────────────


@app.get("/api/asistente")
def api_asistente(desde: str = ""):
    """Lo que el chat necesita para pintarse.

    `desde` es el uuid del último mensaje ya pintado: así el sondeo pide sólo lo
    nuevo en vez de releer la conversación entera cada segundo y medio.
    """
    return asistente.conversacion(registry.cargar(), desde or None)


@app.post("/api/asistente/abrir")
def api_asistente_abrir():
    """Arranca la sesión del asistente si no está. Idempotente."""
    try:
        return {"ok": True, **asistente.asegurar_sesion(registry.cargar())}
    except asistente.AsistenteNoDisponible as exc:
        return {"ok": False, "error": str(exc)}


@app.post("/api/asistente/enviar")
async def api_asistente_enviar(request: Request):
    cuerpo = await request.json()
    try:
        return {"ok": True, **asistente.enviar(cuerpo.get("texto", ""),
                                               ruta=str(cuerpo.get("pagina") or ""),
                                               titulo=str(cuerpo.get("titulo") or ""))}
    except asistente.DestinoNoAutorizado as exc:
        return {"ok": False, "error": str(exc)}
    except (asistente.AsistenteNoDisponible, ValueError, tmux.DestinoInvalido) as exc:
        return {"ok": False, "error": str(exc)}


@app.post("/api/asistente/compactar")
async def api_asistente_compactar(request: Request):
    """Compactar en dos tiempos, que es como lo pidió el usuario.

    *«La idea es que haga lo mismo que hago en estos chats: que al darle compact,
    el propio chat genere un prompt que se adjuntará con el compact y luego se
    ejecute el compact con ese argumento.»*

    Paso 1 (`preparar`): se le manda un mensaje interno pidiéndole que escriba
    las instrucciones de compactado de su propia conversación.
    Paso 2 (`ejecutar`): se extrae su respuesta del transcript y se lanza
    `/compact <esa respuesta>`.

    Ni el mensaje ni la respuesta se pintan en el chat. La UI hace los dos pasos
    seguidos; van separados para que el segundo pueda esperar a que conteste.
    """
    cuerpo = await request.json()
    proyectos = registry.cargar()
    try:
        if cuerpo.get("paso") != "ejecutar":
            asistente.enviar(asistente.PETICION_DE_COMPACTADO)
            return {"ok": True, "paso": "preparar"}

        conversacion = asistente.conversacion(proyectos)
        if conversacion["ocupado"]:
            return {"ok": False, "esperando": True}

        ruta = asistente.transcript_vivo(proyectos)
        crudo = transcripts.esqueleto(ruta)["mensajes"] if ruta else []
        instrucciones = asistente.extraer_instrucciones(crudo)
        if not instrucciones:
            return {"ok": False, "esperando": True}

        # Las instrucciones son para uso interno: no se devuelven al chat.
        asistente.enviar_comando("compact", instrucciones)
        return {"ok": True, "paso": "ejecutar"}
    except (asistente.AsistenteNoDisponible, asistente.DestinoNoAutorizado,
            ValueError, tmux.DestinoInvalido) as exc:
        return {"ok": False, "error": str(exc)}


@app.post("/api/asistente/responder")
async def api_asistente_responder(request: Request):
    """Contesta el cuadro de permisos de Claude Code desde el chat.

    Existe porque desde la web no hay forma de pulsar «Yes» y la conversación se
    queda colgada sin decir por qué. Sólo se ofrecen «sí, esta vez» y «no»: el
    «no volver a preguntar» amplía los permisos para siempre y eso se decide
    editando `.claude/settings.json`, no con un botón.
    """
    cuerpo = await request.json()
    try:
        return asistente.responder_confirmacion(cuerpo.get("respuesta", ""))
    except (asistente.AsistenteNoDisponible, asistente.DestinoNoAutorizado,
            ValueError) as exc:
        return {"ok": False, "error": str(exc)}


@app.post("/api/asistente/limpiar")
def api_asistente_limpiar():
    """`/clear`. La UI pide confirmación: no es reversible y deja el transcript
    viejo huérfano."""
    try:
        return {"ok": True, **asistente.enviar_comando("clear")}
    except (asistente.AsistenteNoDisponible, asistente.DestinoNoAutorizado,
            ValueError) as exc:
        return {"ok": False, "error": str(exc)}


# ─────────────────── escritura acotada: lo único que el asistente escribe ───────────────────
#
# 🔴 No hay ningún endpoint de borrado aquí, y no es un olvido (regla dura 16):
# el asistente escribe notas y crea slots dentro del hub, y nada más. Sobre los
# proyectos del usuario es sólo lectura. Añadir un borrado no sería «uno más».


@app.post("/api/nota")
async def api_nota(request: Request):
    """Deja una nota. Sin `slot_id`, en el slot del panel donde el usuario está.

    Si ese panel no tiene slot, responde con la sugerencia de crearlo en vez de
    con un error: ofrecerlo es útil, fallar no.
    """
    cuerpo = await request.json()
    con = conexion()
    try:
        slot_id = cuerpo.get("slot_id")
        return asistente.escribir_nota(
            con, cuerpo.get("texto", ""), int(slot_id) if slot_id else None
        )
    except (ValueError, TypeError) as exc:
        return {"ok": False, "error": str(exc)}
    finally:
        con.close()


@app.get("/api/programados")
def api_programados(slot: int | None = None):
    con = conexion()
    try:
        return api.programados(con, slot)
    finally:
        con.close()


@app.post("/api/programado")
async def api_programar(request: Request):
    """Programa un mensaje para el panel de un slot.

    La hora llega en UTC porque la manda el navegador, que es el único que sabe
    en qué zona está quien la escribió. `programados.normalizar` rechaza una
    hora sin zona en vez de suponerla (aquí, CST, suponer mal son seis horas).
    """
    cuerpo = await request.json()
    con = conexion()
    try:
        ident = programados.crear(
            con, int(cuerpo.get("slot_id") or 0),
            cuerpo.get("texto", ""), cuerpo.get("cuando", ""),
        )
        return {"ok": True, "id": ident}
    except (ValueError, TypeError) as exc:
        # `SlotDesconocido` hereda de `ValueError`: cae aquí a propósito, con su
        # frase, en vez de salir como un 500 sin motivo.
        return {"ok": False, "error": str(exc)}
    finally:
        con.close()


@app.post("/api/programado/{mensaje_id}/cancelar")
def api_cancelar_programado(mensaje_id: int):
    con = conexion()
    try:
        if programados.cancelar(con, mensaje_id):
            return {"ok": True}
        # No es un fallo del servidor: es que ya se entregó, ya caducó o ya
        # estaba cancelado. Decir cuál evita el «no hizo nada» de siempre.
        return {"ok": False,
                "error": "ese mensaje ya no estaba pendiente: se entregó, caducó "
                         "o ya estaba cancelado"}
    finally:
        con.close()


@app.post("/api/slot")
async def api_crear_slot(request: Request):
    cuerpo = await request.json()
    con = conexion()
    try:
        return asistente.crear_slot(
            con,
            cuerpo.get("proyecto_id", ""),
            cuerpo.get("nombre", ""),
            cuerpo.get("ruta") or None,
        )
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    finally:
        con.close()


def main() -> None:  # pragma: no cover
    import uvicorn

    uvicorn.run(app, host=config.WEB_HOST, port=config.WEB_PORT)


if __name__ == "__main__":  # pragma: no cover
    main()
