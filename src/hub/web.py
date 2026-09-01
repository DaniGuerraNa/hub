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

from fastapi import FastAPI, Form, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import (agentes, api, asistente, busqueda, catalogo, config, db,
               insignias, registry, servicios, slots, snapshotter, terminal,
               tmux, transcripts)
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
HOSTS = ("127.0.0.1", "localhost", "::1")
MUTAN = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def origen_permitido(origen: str | None) -> bool:
    """Sin `Origin` se pasa; con un `Origin` ajeno, no.

    Ausente significa que no lo mandó un navegador: `curl`, el `bin/hub` del
    asistente o un script. Ésos ya tienen la máquina, y rechazarlos rompería el
    CLI sin ganar seguridad. Lo que se cierra es el caso en que un navegador
    dice de dónde viene y no es de aquí.

    🔴 Se compara el HOSTNAME y no la URL entera con su puerto. La primera
    versión montaba la lista de orígenes válidos con `config.WEB_PORT`, y en la
    prueba rechazó al origen legítimo: basta arrancar uvicorn en otro puerto sin
    exportar `HUB_PORT` —que es justo lo que imprime el instalador con
    `--sin-servicios`— para quedarse sin terminal y sin saber por qué. El puerto
    no aporta defensa aquí: una página de internet jamás tendrá un `Origin` cuyo
    host sea `localhost`, y otro servicio del propio equipo ya está dentro.
    """
    if origen is None:
        return True
    partes = urlsplit(origen)
    return partes.scheme in ("http", "https") and partes.hostname in HOSTS


@app.middleware("http")
async def _mismo_origen(request: Request, siguiente):
    if request.method in MUTAN and not origen_permitido(
        request.headers.get("origin")
    ):
        return JSONResponse(
            {"ok": False,
             "error": "petición rechazada: viene de otro sitio web"},
            status_code=403,
        )
    return await siguiente(request)


app.add_middleware(TrustedHostMiddleware, allowed_hosts=[*HOSTS, "testserver"])

_AQUI = Path(__file__).parent
plantillas = Jinja2Templates(directory=str(_AQUI / "templates"))
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


def _volver(destino: str = "/") -> RedirectResponse:
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
def inicio(request: Request):
    con = conexion()
    try:
        datos = api.resumen(con)
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
                "titulo": p["nombre"],
                "seccion": "panorama",
                "proyecto_actual": proyecto_id,
            },
        )
    finally:
        con.close()


# ───────────────────────── respaldo, servicios, conexiones ─────────────────────────


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
            from fastapi.responses import PlainTextResponse

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
        # —y de hecho lo estaba.
        if proyecto:
            kits = [k for k in kits if k["id"] == proyecto]
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


def _ventana_activa(session: str) -> int | None:
    """Qué ventana de esa sesión está en primer plano, según tmux."""
    try:
        return next(v["indice"] for v in tmux.listar_ventanas(session) if v["activa"])
    except (StopIteration, tmux.DestinoInvalido):
        return None


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
        if not ctx["session"] and sesiones:
            ctx["session"] = sesiones[0]["session"]
        # La barra lista sesiones como bandeja: sólo lo que sigue sin slot.
        pendientes, organizadas = api.clasificar_sesiones(
            sesiones, ctx["paneles"], ctx["session"]
        )
        return _vista(
            request,
            "trabajo.html",
            {
                **ctx,
                "sesiones": pendientes,
                "sesiones_organizadas": organizadas,
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


@app.get("/api/sesion/{session}/ventanas")
def api_ventanas(session: str):
    try:
        return tmux.listar_ventanas(session)
    except tmux.DestinoInvalido:
        return []


@app.post("/api/sesion/{session}/ventanas")
async def api_nueva_ventana(session: str, request: Request):
    cuerpo = await request.json()
    try:
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

    🔴 El origen se comprueba ANTES de aceptar. Este socket es una shell: es la
    superficie más peligrosa del hub y la única donde un `accept()` de más
    entrega la máquina. Se rechaza sin aceptar —código 1008— para no llegar
    siquiera a abrir el espejo del PTY.
    """
    if not origen_permitido(ws.headers.get("origin")):
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
        salida.cancel()
        adjunto.cerrar()
        terminal.destruir_espejo(espejo)


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
            # Un slot puede moverse entre proyectos: una investigación que empezó
            # suelta y termina perteneciendo a algo (decisión 12).
            proyecto_id=mover_a.strip() or None,
        )
    finally:
        con.close()
    return _volver(f"/proyecto/{mover_a.strip() or proyecto_id}")


@app.post("/slot/{slot_id}/estado")
def slot_estado(slot_id: int, accion: str = Form(...), proyecto_id: str = Form(...)):
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
    return _volver(f"/proyecto/{proyecto_id}")


@app.post("/slot/{slot_id}/abrir")
def slot_abrir(slot_id: int, proyecto_id: str = Form(...), session: str = Form("")):
    con = conexion()
    try:
        slots.abrir(con, slot_id, session.strip() or None)
    except Exception:
        pass  # si tmux no responde, la vista lo refleja en el próximo ciclo
    finally:
        con.close()
    return _volver(f"/proyecto/{proyecto_id}")


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
        return {"ok": True, **asistente.enviar(cuerpo.get("texto", ""))}
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
