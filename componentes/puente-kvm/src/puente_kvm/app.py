"""El servicio: la web para la persona y la API para Claude (vía MCP).

Es el único proceso que habla con el aparato —el JetKVM admite una sesión de
vídeo a la vez— y por eso el MCP no se conecta al aparato: llama a esta API.
Una sola costura: todo lo que hace Claude y todo lo que ve la persona pasa
por aquí.

Escucha **sólo en 127.0.0.1**. Hay dos clases de petición:
- las de **la persona** (dar el control, aprobar, ajustes): exigen `Origin`
  de esta misma web, o sea, un clic en el navegador. El MCP no manda `Origin`
  y por eso no puede darse el control ni aprobarse un cambio a sí mismo. Es una
  barrera contra accidentes, no contra quien quiera saltarla a propósito.
- las de **Claude** (teclear, leer, proponer, escribir lo aprobado): aceptan
  peticiones sin `Origin`; si traen uno, tiene que ser el de esta web, para
  que otra pestaña del navegador no pueda teclear en el Mac.
"""

from __future__ import annotations

import asyncio
import contextlib
import io
import json
import os
import re
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import (FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, Response,
                               StreamingResponse)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from PIL import Image, ImageDraw, ImageFont

from . import cambios, config, conversaciones, hid, huellas, lecturas, repertorio, terminal
from .control import Bitacora, Control, SinControl
from .dispositivo import AparatoNoDisponible, Dispositivo
from .motor import Motor, Ocupado, PantallaInesperada

AQUI = Path(__file__).parent
plantillas = Jinja2Templates(directory=AQUI / "plantillas")

# Lo único que se abre en el marco de la izquierda: las páginas de esta web,
# por su forma exacta. Un filtro por prefijo deja pasar `/\sitio.com`, que el
# navegador entiende como `//sitio.com`, otra web.
PAGINAS_DEL_MARCO = re.compile(r"/(panel|claude|ajustes)|/(lecturas|cambios)/[a-z0-9-]{1,64}")


def explicar_error(e: Exception, dispositivo: Dispositivo) -> str:
    """El error de conexión dicho de forma que se sepa qué hacer, con el detalle técnico al final."""
    tecnico = f"{type(e).__name__}: {e}"
    if isinstance(e, AparatoNoDisponible):
        return str(e)
    url = getattr(dispositivo, "url", "")
    if isinstance(e, (OSError, asyncio.TimeoutError)) or "Connector" in type(e).__name__:
        return (f"el JetKVM no responde en {url}: ¿está encendido, en la misma red, y es ésa su dirección "
                f"en Ajustes? ({tecnico})")
    return tecnico


_avisos_sin_video: dict[str, bytes] = {}


def imagen_sin_video(motivo: str) -> bytes:
    """Lo que enseña el directo cuando no hay vídeo: un fotograma que lo dice.

    Sin él, la imagen en directo se queda cargando para siempre (la página
    nunca acaba de cargar) y la persona no ve más que un recuadro negro.
    """
    if motivo not in _avisos_sin_video:
        from .simulador import FUENTE_UI

        img = Image.new("RGB", (1280, 720), "#131a23")
        d = ImageDraw.Draw(img)
        grande = ImageFont.truetype(FUENTE_UI, 34) if FUENTE_UI else ImageFont.load_default(34)
        normal = ImageFont.truetype(FUENTE_UI, 22) if FUENTE_UI else ImageFont.load_default(22)
        d.text((60, 280), "Sin imagen del aparato", font=grande, fill="#e3e9f2")
        lineas, linea = [], ""
        for palabra in motivo.split():
            if len(linea) + len(palabra) > 90:
                lineas.append(linea)
                linea = ""
            linea += palabra + " "
        lineas.append(linea)
        for i, l in enumerate(lineas[:4]):
            d.text((60, 340 + i * 32), l.strip(), font=normal, fill="#b6c2d4")
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=80)
        if len(_avisos_sin_video) > 20:  # los motivos cambian poco; esto sólo pone un tope
            _avisos_sin_video.clear()
        _avisos_sin_video[motivo] = buf.getvalue()
    return _avisos_sin_video[motivo]


def crear_dispositivo(ajustes: dict) -> Dispositivo:
    d = ajustes["dispositivo"]
    if d["tipo"] == "jetkvm":
        from .jetkvm import JetKVM

        return JetKVM(d["url"], os.environ.get(d.get("clave_env") or "JETKVM_CLAVE", ""))
    from .simulador import Simulador

    # El Mac simulado escribe con la fuente de entrada que se eligió para el de verdad.
    return Simulador(distribucion=ajustes.get("perfil", {}).get("distribucion", "mac-us"))


# El directo: 2 imágenes por segundo mirando, ~8 mientras la persona usa el Mac.
INTERVALO_DIRECTO = 0.5
INTERVALO_MANDO = 0.12
# Lo que la persona puede pulsar con un botón y no con su teclado (Windows se
# queda la tecla ⌘ y algunas combinaciones).
COMBINACIONES_MANDO = ("cmd+tab", "cmd+space")
# Códigos de tecla HID que acepta el mando: de la «a» al Ctrl/Mayús/⌥/⌘ derechos.
TECLA_MIN, TECLA_MAX = 0x04, 0xE7


class Puente:
    def __init__(self, dispositivo: Dispositivo | None = None):
        self.ajustes = config.leer_ajustes()
        self.dispositivo = dispositivo or crear_dispositivo(self.ajustes)
        self.control = Control()
        self.bitacora = Bitacora()
        self.motor = Motor(self.dispositivo, self.control, self.bitacora, self.ajustes["perfil"])
        self.error_conexion = ""
        self.tareas: set[asyncio.Task] = set()
        self.actividad = repertorio.Actividad()
        # Hasta cuándo la persona está usando el Mac desde la pantalla: mientras,
        # el directo va más fluido.
        self.mando_hasta = 0.0

    async def conectar(self) -> None:
        try:
            await self.dispositivo.conectar()
            self.error_conexion = ""
            e = self.dispositivo.estado()
            self.bitacora.apuntar("conexion", f"conectado a {self.dispositivo.tipo}"
                                  + (f", firmware {e['firmware']}" if e.get("firmware") else ""), quien="puente")
            if e.get("aviso"):
                self.bitacora.apuntar("aviso", e["aviso"], quien="puente")
        except Exception as e:  # se enseña en la pantalla, no se traga
            self.error_conexion = explicar_error(e, self.dispositivo)
            self.bitacora.apuntar("error", f"no conecta: {self.error_conexion}", quien="puente")

    def devolver_control(self, motivo: str) -> None:
        """El control dado vale para el aparato al que se dio, no para otro."""
        if self.control.modo == "claude":
            self.control.retomar(motivo)
            self.bitacora.apuntar("control", motivo, quien="puente")

    def en_segundo_plano(self, coro) -> None:
        t = asyncio.create_task(coro)
        self.tareas.add(t)
        t.add_done_callback(self.tareas.discard)


def crear_app(dispositivo: Dispositivo | None = None, hosts: set[str] | None = None) -> FastAPI:
    admitidos = hosts if hosts is not None else config.HOSTS

    @contextlib.asynccontextmanager
    async def vida(app: FastAPI):
        app.state.puente = Puente(dispositivo)
        await app.state.puente.conectar()
        yield
        with contextlib.suppress(Exception):
            await app.state.puente.dispositivo.cerrar()

    app = FastAPI(title="Puente KVM", lifespan=vida)
    app.mount("/static", StaticFiles(directory=AQUI / "static"), name="static")

    @app.middleware("http")
    async def solo_por_su_nombre(req: Request, siguiente):
        if req.headers.get("host", "") not in admitidos:
            return JSONResponse({"detail": "nombre de host no admitido"}, status_code=403)
        r = await siguiente(req)
        # Sólo esta web puede enmarcar sus páginas (el espacio de trabajo enmarca
        # el panel). Enmarcadas en otra web, un clic robado sobre «Dar el
        # control» o «Aprobar» se saltaría la única puerta que no es de Claude.
        r.headers["Content-Security-Policy"] = "frame-ancestors 'self'"
        r.headers["X-Frame-Options"] = "SAMEORIGIN"
        return r

    def puente(req: Request) -> Puente:
        return req.app.state.puente

    def mismo_origen(req: Request) -> bool:
        origen = req.headers.get("origin")
        if not origen:
            return False
        anfitrion = req.headers.get("host", "")
        return origen in (f"http://{anfitrion}", f"https://{anfitrion}")

    def de_la_persona(req: Request) -> None:
        if not mismo_origen(req):
            raise HTTPException(403, "esto lo hace la persona desde la pantalla del puente")

    def de_claude(req: Request) -> None:
        if req.headers.get("origin") and not mismo_origen(req):
            raise HTTPException(403, "origen no admitido")

    async def cuerpo(req: Request) -> dict:
        try:
            return await req.json()
        except Exception:
            return {}

    def fallo(e: Exception) -> HTTPException:
        if isinstance(e, SinControl):
            return HTTPException(423, str(e))
        if isinstance(e, (Ocupado, PantallaInesperada, terminal.ClaudeCodeViejo)):
            return HTTPException(409, str(e))
        if isinstance(e, hid.TextoIntraducible):
            return HTTPException(422, str(e))
        if isinstance(e, AparatoNoDisponible):
            return HTTPException(503, str(e))
        if isinstance(e, (ValueError, FileNotFoundError, KeyError)):
            return HTTPException(400, str(e))
        return HTTPException(500, f"{type(e).__name__}: {e}")

    # ── páginas ─────────────────────────────────────────────────────────────
    def pagina(req: Request, plantilla: str, **ctx) -> HTMLResponse:
        p = puente(req)
        return plantillas.TemplateResponse(req, plantilla, {"estado": estado(p), **ctx})

    @app.get("/", response_class=HTMLResponse)
    async def espacio(req: Request, ver: str = "/panel"):
        ver = ver if PAGINAS_DEL_MARCO.fullmatch(ver) else "/panel"
        return pagina(req, "espacio.html", titulo="Puente KVM", ver=ver)

    @app.get("/panel", response_class=HTMLResponse)
    async def inicio(req: Request):
        return pagina(req, "panel.html", titulo="Panel",
                      lecturas=[lecturas.resumen(l) for l in lecturas.todas()[:20]],
                      cambios=[c for c in cambios.todos()[:20]])

    @app.get("/lecturas/{id_}", response_class=HTMLResponse)
    async def ver_lectura(req: Request, id_: str):
        try:
            l = lecturas.cargar(id_)
        except Exception as e:
            raise HTTPException(404, "no existe esa lectura") from e
        ens = lecturas.ensamblar(l)
        return pagina(req, "lectura.html", titulo=l.nombre, l=l, r=lecturas.resumen(l), ens=ens,
                      textos={p.n: l.transcripcion(p.n) for p in l.paginas},
                      consultas=huellas.CONSULTAS,
                      cambios=[c for c in cambios.todos() if c.lectura == l.id])

    @app.get("/cambios/{id_}", response_class=HTMLResponse)
    async def ver_cambio(req: Request, id_: str):
        try:
            c = cambios.cargar(id_)
        except Exception as e:
            raise HTTPException(404, "no existe ese cambio") from e
        return pagina(req, "cambio.html", titulo=c.descripcion, c=c)

    @app.get("/claude", response_class=HTMLResponse)
    async def ver_claude(req: Request):
        return pagina(req, "claude.html", titulo="Claude", skills=repertorio.skills(),
                      permisos=repertorio.permisos(), herramientas=await repertorio.herramientas(),
                      conocimiento=repertorio.conocimiento(),
                      actividad=list(puente(req).actividad.eventos)[::-1],
                      lecturas=[lecturas.resumen(l) for l in lecturas.todas()[:10]])

    @app.get("/ajustes", response_class=HTMLResponse)
    async def ver_ajustes(req: Request):
        p = puente(req)
        clave_env = p.ajustes["dispositivo"].get("clave_env") or "JETKVM_CLAVE"
        return pagina(req, "ajustes.html", titulo="Ajustes", ajustes=p.ajustes,
                      clave_puesta=bool(os.environ.get(clave_env)),
                      distribuciones=hid.DISTRIBUCIONES, modelos=config.MODELOS,
                      nombres_distribucion=hid.NOMBRES_DISTRIBUCION)

    # ── estado y pantalla ───────────────────────────────────────────────────
    def estado(p: Puente) -> dict:
        try:
            disp = p.dispositivo.estado()
        except Exception as e:
            disp = {"tipo": p.dispositivo.tipo, "conectado": False, "error": str(e)}
        conv = conversaciones.actual()
        return {"version": config.VERSION, "control": p.control.estado(), "dispositivo": disp,
                "claude": p.actividad.publico(), "error_conexion": p.error_conexion, "tarea": p.motor.tarea,
                "progreso": p.motor.progreso, "perfil": p.ajustes["perfil"], "t": time.time(),
                # Dónde trabaja Claude y con qué conversación: rutas y el nombre que le puso la persona.
                "espacio": str(config.espacio()), "codigo": str(config.CODIGO),
                "conversacion": {"nombre": conv.nombre, "modelo": conv.modelo, "claude_code": conv.claude_code,
                                 "modelo_texto": config.texto_modelo(conv.modelo)} if conv else None,
                # Sin registro: ¿hay una de antes abierta, o aún no se ha abierto ninguna?
                "conversacion_anterior": False if conv else terminal.existe(),
                # El `claude` que abriría el puente con SU PATH (no el de una shell).
                "claude_code": terminal.claude_code()}

    @app.get("/api/estado")
    async def api_estado(req: Request):
        p = puente(req)
        return {**estado(p),
                "lecturas": [lecturas.resumen(l) for l in lecturas.todas()[:10]],
                "cambios": [{"id": c.id, "descripcion": c.descripcion, "estado": c.estado,
                             "tramos": len(c.tramos)} for c in cambios.todos()[:10]]}

    @app.get("/api/bitacora")
    async def api_bitacora(req: Request, desde: int = 0):
        return puente(req).bitacora.ultimas(desde)

    async def jpeg(p: Puente, region: str, ancho: int) -> bytes:
        img = await p.motor.captura()
        if region == "editor":
            img = p.motor.recortar(img)
        if ancho and img.width > ancho:
            img = img.resize((ancho, round(img.height * ancho / img.width)), Image.LANCZOS)
        buf = io.BytesIO()
        img.convert("RGB").save(buf, "JPEG", quality=80)
        return buf.getvalue()

    @app.get("/api/pantalla.jpg")
    async def api_pantalla(req: Request, region: str = "completa", ancho: int = 1280):
        try:
            return Response(await jpeg(puente(req), region, ancho), media_type="image/jpeg",
                            headers={"Cache-Control": "no-store"})
        except Exception as e:
            raise fallo(e) from e

    @app.get("/api/pantalla.png")
    async def api_pantalla_png(req: Request, region: str = "completa"):
        p = puente(req)
        try:
            img = await p.motor.captura()
        except Exception as e:
            raise fallo(e) from e
        if region == "editor":
            img = p.motor.recortar(img)
        buf = io.BytesIO()
        img.save(buf, "PNG")
        return Response(buf.getvalue(), media_type="image/png", headers={"Cache-Control": "no-store"})

    @app.get("/api/pantalla.mjpg")
    async def api_directo(req: Request):
        p = puente(req)

        async def fotogramas():
            while not await req.is_disconnected():
                try:
                    datos = await jpeg(p, "completa", 1280)
                except Exception as e:  # sin vídeo, un fotograma que dice por qué
                    datos = imagen_sin_video(str(e) or type(e).__name__)
                yield (b"--fotograma\r\nContent-Type: image/jpeg\r\nContent-Length: "
                       + str(len(datos)).encode() + b"\r\n\r\n" + datos + b"\r\n")
                await asyncio.sleep(INTERVALO_MANDO if time.time() < p.mando_hasta else INTERVALO_DIRECTO)

        return StreamingResponse(fotogramas(), media_type="multipart/x-mixed-replace; boundary=fotograma")

    # ── control (la persona) ────────────────────────────────────────────────
    @app.post("/api/control")
    async def api_control(req: Request):
        de_la_persona(req)
        p = puente(req)
        accion = (await cuerpo(req)).get("accion")
        if accion == "dar":
            p.control.dar()
        elif accion == "retomar":
            p.control.retomar()
        elif accion == "parar":
            p.control.parar()
        else:
            raise HTTPException(400, "acción desconocida")
        p.bitacora.apuntar("control", {"dar": "la persona da el control a Claude",
                                       "retomar": "la persona retoma el Mac",
                                       "parar": "PARAR"}[accion], quien="persona")
        with contextlib.suppress(Exception):
            await p.dispositivo.informe_teclado(0, [])
        return p.control.estado()

    # ── acciones sueltas (Claude) ───────────────────────────────────────────
    @app.post("/api/teclear")
    async def api_teclear(req: Request):
        de_claude(req)
        p, datos = puente(req), await cuerpo(req)
        try:
            async with p.motor.ocupar("teclear"):
                n = await p.motor.teclear(str(datos.get("texto", "")))
            return {"pulsaciones": n}
        except Exception as e:
            raise fallo(e) from e

    @app.post("/api/atajo")
    async def api_atajo(req: Request):
        de_claude(req)
        p, datos = puente(req), await cuerpo(req)
        try:
            veces = max(1, min(int(datos.get("veces", 1)), 200))
            async with p.motor.ocupar(f"atajo {datos.get('atajo')}"):
                await p.motor.atajo(str(datos.get("atajo", "")), veces=veces)
            return {"ok": True}
        except Exception as e:
            raise fallo(e) from e

    @app.post("/api/ir_a_linea")
    async def api_ir_a_linea(req: Request):
        de_claude(req)
        p, datos = puente(req), await cuerpo(req)
        try:
            async with p.motor.ocupar("ir a línea"):
                await p.motor.ir_a_linea(int(datos["linea"]))
            return {"ok": True}
        except Exception as e:
            raise fallo(e) from e

    @app.post("/api/clic")
    async def api_clic(req: Request):
        de_claude(req)
        p, datos = puente(req), await cuerpo(req)
        try:
            async with p.motor.ocupar("clic"):
                await p.motor.clic(int(datos["x"]), int(datos["y"]), datos.get("boton", "izquierdo"),
                                   bool(datos.get("doble")))
            return {"ok": True}
        except Exception as e:
            raise fallo(e) from e

    @app.post("/api/rueda")
    async def api_rueda(req: Request):
        de_claude(req)
        p, datos = puente(req), await cuerpo(req)
        try:
            async with p.motor.ocupar("rueda"):
                x, y = datos.get("x"), datos.get("y")
                await p.motor.rueda(int(datos.get("pasos", 1)),
                                    None if x is None else int(x), None if y is None else int(y))
            return {"ok": True}
        except Exception as e:
            raise fallo(e) from e

    # ── lecturas ────────────────────────────────────────────────────────────
    @app.post("/api/lecturas")
    async def api_nueva_lectura(req: Request):
        de_claude(req)
        p, datos = puente(req), await cuerpo(req)
        nombre = str(datos.get("nombre") or "documento").strip()[:80]
        try:
            p.control.comprobar()
        except Exception as e:
            raise fallo(e) from e
        if p.motor.tarea:
            raise HTTPException(409, f"ya estoy con: {p.motor.tarea}")
        l = lecturas.nueva(nombre)

        async def correr():
            try:
                async with p.motor.ocupar(f"leer «{nombre}»"):
                    await lecturas.capturar(p.motor, l)
                # Transcribir no toca el Mac: no hay por qué seguir con el teclado tomado.
                p.control.devolver("terminó de capturar: el Mac vuelve a ti")
            except Ocupado as e:
                l.estado, l.error = "error", str(e)
                l.guardar()

        p.en_segundo_plano(correr())
        await asyncio.sleep(0.05)
        return {"id": l.id, "url": f"/lecturas/{l.id}"}

    @app.get("/api/lecturas/{id_}")
    async def api_lectura(id_: str):
        try:
            l = lecturas.cargar(id_)
        except Exception as e:
            raise HTTPException(404, "no existe esa lectura") from e
        return {**lecturas.resumen(l),
                "paginas_detalle": [{"n": pg.n, "transcrita": pg.transcrita, "quien": pg.quien,
                                     "primera": pg.primera, "ultima": pg.ultima,
                                     "png": str(l.png(pg.n))} for pg in l.paginas]}

    @app.get("/api/lecturas/{id_}/paginas/{n}.png")
    async def api_pagina_png(id_: str, n: int):
        try:
            ruta = lecturas.cargar(id_).png(n)
        except Exception as e:
            raise HTTPException(404, "no existe") from e
        if not ruta.exists():
            raise HTTPException(404, "no existe esa página")
        return FileResponse(ruta, media_type="image/png")

    @app.get("/api/lecturas/{id_}/texto", response_class=PlainTextResponse)
    async def api_lectura_texto(id_: str):
        try:
            l = lecturas.cargar(id_)
        except Exception as e:
            raise HTTPException(404, "no existe esa lectura") from e
        return lecturas.texto_ensamblado(l)

    @app.post("/api/lecturas/{id_}/paginas/{n}")
    async def api_transcribir(req: Request, id_: str, n: int):
        datos = await cuerpo(req)
        quien = "persona" if mismo_origen(req) else "claude"
        de_claude(req)
        try:
            l = lecturas.cargar(id_)
            pg = lecturas.transcribir(l, n, str(datos.get("texto", "")), quien)
            ens = lecturas.ensamblar(l)
            p = puente(req)
            p.bitacora.apuntar("transcripcion", f"«{l.nombre}» página {n} ({pg.primera}–{pg.ultima})",
                               quien=quien, lectura=l.id)
            return {"pagina": n, "primera": pg.primera, "ultima": pg.ultima, "errores": pg.errores,
                    "conflictos": [c for c in ens.conflictos
                                   if pg.primera <= c["linea"] <= pg.ultima]}
        except Exception as e:
            raise fallo(e) from e

    @app.post("/api/lecturas/{id_}/resolver")
    async def api_resolver(req: Request, id_: str):
        de_claude(req)
        datos = await cuerpo(req)
        try:
            l = lecturas.cargar(id_)
            lecturas.resolver(l, int(datos["linea"]), str(datos["texto"]))
            puente(req).bitacora.apuntar(
                "resolucion", f"«{l.nombre}» línea {datos['linea']}",
                quien="persona" if mismo_origen(req) else "claude", lectura=l.id)
            return lecturas.resumen(l)
        except Exception as e:
            raise fallo(e) from e

    @app.post("/api/lecturas/{id_}/huella")
    async def api_huella_lectura(req: Request, id_: str):
        de_claude(req)
        datos = await cuerpo(req)
        try:
            l = lecturas.cargar(id_)
            r = lecturas.comprobar_huella(l, str(datos.get("referencia", "")))
            puente(req).bitacora.apuntar(
                "huella", f"«{l.nombre}»: {'EXACTA' if r['verificada'] else 'no coincide'}",
                quien="persona" if mismo_origen(req) else "claude", lectura=l.id)
            return r
        except Exception as e:
            raise fallo(e) from e

    # ── cambios ─────────────────────────────────────────────────────────────
    @app.post("/api/cambios")
    async def api_proponer(req: Request):
        de_claude(req)
        datos = await cuerpo(req)
        try:
            l = lecturas.cargar(str(datos["lectura"]))
            c = cambios.proponer(l, str(datos["texto"]), str(datos.get("descripcion") or "cambio"))
            puente(req).bitacora.apuntar(
                "propuesta", f"{c.descripcion}: {len(c.tramos)} {'tramo' if len(c.tramos) == 1 else 'tramos'}"
                + (" (sobre una lectura sin verificar)" if c.sin_verificar else ""), cambio=c.id)
            aviso = "Espera a que la persona lo apruebe en la pantalla del puente."
            if c.sin_verificar:
                aviso = ("La lectura de la que parte está sin verificar con la huella de la base: los "
                         "tramos se calcularon contra lo transcrito, que puede tener errores. Díselo a "
                         "la persona antes de que apruebe. " + aviso)
            return {"id": c.id, "url": f"/cambios/{c.id}", "tramos": len(c.tramos),
                    "estado": c.estado, "lectura_verificada": not c.sin_verificar, "aviso": aviso}
        except Exception as e:
            raise fallo(e) from e

    @app.get("/api/cambios/{id_}")
    async def api_cambio(id_: str):
        try:
            c = cambios.cargar(id_)
        except Exception as e:
            raise HTTPException(404, "no existe ese cambio") from e
        return {"id": c.id, "descripcion": c.descripcion, "estado": c.estado, "error": c.error,
                "lectura": c.lectura, "huella_esperada": c.huella_esperada,
                "lectura_verificada": not c.sin_verificar,
                "tramos": [{"i": t.i, "desde": t.desde, "hasta": t.hasta, "estado": t.estado,
                            "antes": t.antes, "nuevas": t.nuevas, "captura_inestable": t.captura_inestable,
                            "png": str(c.png(t.i)) if c.png(t.i).exists() else None}
                           for t in c.tramos]}

    @app.get("/api/cambios/{id_}/tramos/{i}.png")
    async def api_tramo_png(id_: str, i: int):
        try:
            ruta = cambios.cargar(id_).png(i)
        except Exception as e:
            raise HTTPException(404, "no existe ese cambio") from e
        if not ruta.exists():
            raise HTTPException(404, "sin captura")
        return FileResponse(ruta, media_type="image/png")

    @app.post("/api/cambios/{id_}/aprobar")
    async def api_aprobar(req: Request, id_: str):
        de_la_persona(req)
        try:
            c = cambios.cargar(id_)
            cambios.aprobar(c)
            puente(req).bitacora.apuntar("aprobacion", f"{c.descripcion}: aprobado", quien="persona",
                                         cambio=c.id)
            return {"estado": c.estado}
        except Exception as e:
            raise fallo(e) from e

    @app.post("/api/cambios/{id_}/rechazar")
    async def api_rechazar(req: Request, id_: str):
        de_la_persona(req)
        try:
            c = cambios.cargar(id_)
            cambios.rechazar(c)
            puente(req).bitacora.apuntar("aprobacion", f"{c.descripcion}: rechazado", quien="persona",
                                         cambio=c.id)
            return {"estado": c.estado}
        except Exception as e:
            raise fallo(e) from e

    @app.post("/api/cambios/{id_}/escribir")
    async def api_escribir(req: Request, id_: str):
        de_claude(req)
        p = puente(req)
        quien = "persona" if mismo_origen(req) else "claude"
        try:
            c = cambios.cargar(id_)
            if c.estado != "aprobado":
                raise ValueError(f"el cambio está {c.estado}: sólo se escribe uno aprobado por la persona")
            p.control.comprobar()
            if p.motor.tarea:
                raise Ocupado(f"ya estoy con: {p.motor.tarea}")
        except Exception as e:
            raise fallo(e) from e

        async def correr():
            try:
                async with p.motor.ocupar(f"escribir «{c.descripcion}»"):
                    await cambios.escribir(p.motor, c, quien)
                # Lo siguiente es revisar y guardar, y eso lo hace la persona en el Mac.
                p.control.devolver("terminó de escribir: el Mac vuelve a ti para revisar y guardar")
            except Ocupado as e:
                c.estado, c.error = "fallido", str(e)
                c.guardar()

        p.en_segundo_plano(correr())
        await asyncio.sleep(0.05)
        return {"id": c.id, "estado": "escribiendo"}

    @app.post("/api/cambios/{id_}/huella")
    async def api_huella_cambio(req: Request, id_: str):
        de_claude(req)
        datos = await cuerpo(req)
        try:
            c = cambios.cargar(id_)
            r = cambios.comprobar_huella(c, str(datos.get("referencia", "")))
            puente(req).bitacora.apuntar(
                "huella", f"{c.descripcion}: {'coincide' if r['verificado'] else 'NO coincide'}",
                quien="persona" if mismo_origen(req) else "claude", cambio=c.id)
            return r
        except Exception as e:
            raise fallo(e) from e

    # ── ajustes y simulador (la persona) ────────────────────────────────────
    @app.post("/api/ajustes")
    async def api_ajustes(req: Request):
        de_la_persona(req)
        p, datos = puente(req), await cuerpo(req)
        # Antes de tocar nada: con una tarea en marcha, unos ajustes nuevos
        # cambiarían los atajos o el aparato a mitad de escribir.
        if p.motor.tarea:
            raise HTTPException(409, f"hay una tarea en marcha ({p.motor.tarea}): espera a que acabe o pulsa Parar")
        try:
            nuevos = config.leer_ajustes()
            for seccion in ("dispositivo", "perfil", "claude"):
                nuevos[seccion].update(datos.get(seccion, {}))
            config.validar_modelo(nuevos["claude"]["modelo"])
            nuevos["claude"]["saltar_permisos"] = nuevos["claude"].get("saltar_permisos") is True
            if nuevos["perfil"].get("distribucion", "mac-us") not in hid.DISTRIBUCIONES:
                raise ValueError("distribución de teclado desconocida")
            for clave in ("inicio_documento", "fin_documento", "pagina_abajo", "ir_a_linea", "fin_de_linea"):
                hid.combinacion(nuevos["perfil"][clave])
            r = [int(v) for v in nuevos["perfil"]["region_editor"]]
            if len(r) != 4 or r[2] < 50 or r[3] < 50:
                raise ValueError("la región del editor tiene que ser x, y, ancho, alto")
            nuevos["perfil"]["region_editor"] = r
            nuevos["perfil"]["aparcar_raton"] = [int(v) for v in nuevos["perfil"]["aparcar_raton"]]
            nuevos["perfil"]["retardo_tecla_ms"] = max(2, min(int(nuevos["perfil"]["retardo_tecla_ms"]), 200))
            nuevos["perfil"]["invertir_rueda"] = nuevos["perfil"].get("invertir_rueda") is True
            config.guardar_ajustes(nuevos)
        except Exception as e:
            raise fallo(e) from e
        cambia_aparato = nuevos["dispositivo"] != p.ajustes["dispositivo"]
        p.ajustes = nuevos
        p.motor.perfil = nuevos["perfil"]
        editor = getattr(p.dispositivo, "editor", None)
        if editor is not None:  # el simulador: su Mac cambia de fuente con el ajuste
            editor.distribucion = nuevos["perfil"].get("distribucion", "mac-us")
        if cambia_aparato:
            p.devolver_control("cambió el aparato: el control vuelve a la persona")
            with contextlib.suppress(Exception):
                await p.dispositivo.cerrar()
            p.dispositivo = crear_dispositivo(nuevos)
            p.motor.dispositivo = p.dispositivo
            await p.conectar()
        p.bitacora.apuntar("ajustes", "ajustes guardados" + (" y aparato cambiado" if cambia_aparato else ""),
                           quien="persona")
        return {"ok": True, "error_conexion": p.error_conexion}

    @app.post("/api/reconectar")
    async def api_reconectar(req: Request):
        de_la_persona(req)
        p = puente(req)
        if p.motor.tarea:
            raise HTTPException(409, f"hay una tarea en marcha ({p.motor.tarea}): espera a que acabe o pulsa Parar")
        # Tras reconectar, lo que hay al otro lado puede no ser lo que era.
        p.devolver_control("se reconectó el aparato: el control vuelve a la persona")
        with contextlib.suppress(Exception):
            await p.dispositivo.cerrar()
        await p.conectar()
        return {"error_conexion": p.error_conexion}

    @app.post("/api/simulador/guardar")
    async def api_sim_guardar(req: Request):
        """Lo que en el Mac haría la persona: guardar (ejecutar el ALTER)."""
        de_la_persona(req)
        p = puente(req)
        if p.dispositivo.tipo != "simulador":
            raise HTTPException(400, "sólo en el simulador")
        p.dispositivo.editor.guardar()  # type: ignore[attr-defined]
        p.bitacora.apuntar("simulador", "la persona guarda en la base (Cmd+S)", quien="persona")
        return p.dispositivo.estado()

    # ── qué sabe y qué hace Claude ──────────────────────────────────────────
    @app.post("/api/claude/actividad")
    async def api_actividad(req: Request):
        # La mandan los hooks de Claude Code (sin Origin). Sólo se guarda el resumen.
        de_claude(req)
        datos = await cuerpo(req)
        if datos.get("hook_event_name") == "UserPromptSubmit":
            # Su `session_id` es el de la conversación del puente: se usó ahora.
            conversaciones.tocar(datos.get("session_id"))
        return puente(req).actividad.registrar(datos)

    @app.get("/api/claude/actividad")
    async def api_ver_actividad(req: Request):
        a = puente(req).actividad
        return {**a.publico(), "eventos": list(a.eventos)[::-1]}

    @app.get("/api/claude/repertorio")
    async def api_repertorio():
        return {"skills": repertorio.skills(), "permisos": repertorio.permisos(),
                "herramientas": await repertorio.herramientas(), "conocimiento": repertorio.conocimiento()}

    # ── las conversaciones con Claude Code (la persona) ─────────────────────
    def estado_conversaciones() -> dict:
        actual = conversaciones.actual()
        # La que dejó una versión anterior del puente: viva en tmux, sin registro.
        anterior = actual is None and terminal.existe()
        return {"actual": actual.publica() if actual else None, "anterior": anterior,
                "lista": [c.publica() for c in conversaciones.todas()],
                "modelo_siguiente": config.texto_modelo(terminal.modelo_elegido()),
                "espacio": str(config.espacio())}

    async def cambiar(req: Request, abrir) -> None:
        """Cerrar la abierta y abrir otra: nunca con una tarea en marcha sobre el Mac,
        y el control vuelve a la persona (la otra conversación no sabe qué se le dio)."""
        p = puente(req)
        if p.motor.tarea:
            raise HTTPException(409, f"hay una tarea en marcha ({p.motor.tarea}): espera a que acabe o pulsa "
                                     "Parar antes de cambiar de conversación")
        p.devolver_control("se cambió de conversación con Claude: el control vuelve a la persona")
        try:
            await asyncio.to_thread(abrir)
        except Exception as e:
            raise fallo(e) from e

    @app.get("/api/conversaciones")
    async def api_conversaciones():
        return await asyncio.to_thread(estado_conversaciones)

    @app.post("/api/conversaciones")
    async def api_nueva_conversacion(req: Request):
        de_la_persona(req)
        nombre = str((await cuerpo(req)).get("nombre") or "")
        hecha: dict = {}

        def abrir():
            hecha["c"] = terminal.reiniciar(nombre)
        await cambiar(req, abrir)
        # Los nombres pueden ser del trabajo: a la bitácora, sin él.
        puente(req).bitacora.apuntar("terminal", "conversación nueva con Claude", quien="persona")
        return conversaciones.buscar(hecha["c"].id).publica()

    def de_la_lista(id_: str) -> conversaciones.Conversacion:
        try:
            conversaciones.validar_id(id_)
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
        c = conversaciones.buscar(id_)
        if c is None:
            raise HTTPException(404, "no existe esa conversación en la lista del puente")
        return c

    @app.post("/api/conversaciones/{id_}/abrir")
    async def api_abrir_conversacion(req: Request, id_: str):
        de_la_persona(req)
        c = de_la_lista(id_)
        await cambiar(req, lambda: terminal.abrir(c, retomar=True))
        puente(req).bitacora.apuntar("terminal", "se retomó otra conversación con Claude", quien="persona")
        return conversaciones.buscar(id_).publica()

    @app.post("/api/conversaciones/{id_}/renombrar")
    async def api_renombrar_conversacion(req: Request, id_: str):
        de_la_persona(req)
        de_la_lista(id_)
        return conversaciones.renombrar(id_, str((await cuerpo(req)).get("nombre") or "")).publica()

    @app.post("/api/conversaciones/{id_}/quitar")
    async def api_quitar_conversacion(req: Request, id_: str):
        de_la_persona(req)
        c = de_la_lista(id_)
        actual = conversaciones.actual()
        if actual and actual.id == c.id:
            raise HTTPException(409, "es la conversación abierta: cambia a otra antes de quitarla de la lista")
        conversaciones.quitar(c.id)
        return {"ok": True, "aviso": "Quitada de la lista del puente. En Claude Code sigue guardada: no se ha "
                                     "borrado nada (su /resume la encuentra)."}

    # ── la terminal de Claude Code ──────────────────────────────────────────
    @app.post("/api/terminal/reiniciar")
    async def api_terminal_reiniciar(req: Request):
        """La de antes de las conversaciones: una nueva, con su nombre por omisión."""
        de_la_persona(req)
        await cambiar(req, terminal.reiniciar)
        puente(req).bitacora.apuntar("terminal", "conversación nueva con Claude", quien="persona")
        return {"ok": True}

    @app.websocket("/ws/mando")
    async def ws_mando(ws: WebSocket):
        """La persona usa el Mac desde la pantalla del puente: su ratón y su teclado.

        Mismas puertas que la terminal (nombre y origen de esta web). Sólo vale
        cuando Claude NO tiene el control ni hay una tarea en marcha: dos manos
        en el mismo teclado escriben basura. 🔴 Lo tecleado no se guarda en
        ningún sitio (puede ser una contraseña del Mac): la bitácora sólo dice
        cuánto rato se usó.
        """
        anfitrion = ws.headers.get("host", "")
        origen = ws.headers.get("origin", "")
        if anfitrion not in admitidos or origen not in (f"http://{anfitrion}", f"https://{anfitrion}"):
            await ws.close(code=4403)
            return
        await ws.accept()
        p: Puente = ws.app.state.puente
        teclas: list[int] = []
        estado = {"mods": 0, "botones": 0, "x": 0, "y": 0, "desde": 0.0}

        async def soltar() -> None:
            if not (teclas or estado["mods"] or estado["botones"]):
                return
            teclas.clear()
            estado["mods"] = 0
            with contextlib.suppress(Exception):
                await p.dispositivo.informe_teclado(0, [])
            if estado["botones"]:
                estado["botones"] = 0
                with contextlib.suppress(Exception):
                    await p.dispositivo.raton(estado["x"], estado["y"], 0)

        async def pulsar(pulsacion: hid.Pulsacion) -> None:
            retardo = p.ajustes["perfil"].get("retardo_tecla_ms", 12) / 1000
            await p.dispositivo.informe_teclado(pulsacion.modificadores, [pulsacion.tecla])
            await asyncio.sleep(retardo)
            await p.dispositivo.informe_teclado(0, [])
            await asyncio.sleep(retardo)

        try:
            while True:
                m = await ws.receive()
                if m["type"] == "websocket.disconnect":
                    break
                try:
                    orden = json.loads(m.get("text") or "{}")
                    tipo = orden.get("t")
                except (ValueError, AttributeError):
                    continue
                p.control.estado()  # que caduque el control de Claude si toca
                if p.control.modo == "claude" or p.motor.tarea:
                    await soltar()
                    await ws.send_json({"no": "Claude tiene el Mac ahora: retómalo para usarlo tú."
                                        if p.control.modo == "claude" else
                                        f"Hay una tarea en marcha ({p.motor.tarea}): espera o pulsa Parar."})
                    continue
                if not estado["desde"]:
                    estado["desde"] = time.time()
                p.mando_hasta = time.time() + 3
                try:
                    if tipo == "raton":
                        ancho = getattr(p.dispositivo, "ancho", 1920) or 1920
                        alto = getattr(p.dispositivo, "alto", 1080) or 1080
                        estado["x"] = max(0, min(int(orden["x"]), ancho - 1))
                        estado["y"] = max(0, min(int(orden["y"]), alto - 1))
                        estado["botones"] = int(orden.get("b", 0)) & 0x07
                        await p.dispositivo.raton(estado["x"], estado["y"], estado["botones"])
                    elif tipo == "rueda":
                        pasos = max(-10, min(int(orden["pasos"]), 10))
                        if pasos:
                            invertir = p.ajustes["perfil"].get("invertir_rueda")
                            await p.dispositivo.rueda(-pasos if invertir else pasos)
                    elif tipo == "tecla":
                        codigo = int(orden["codigo"])
                        if not TECLA_MIN <= codigo <= TECLA_MAX:
                            continue
                        abajo = bool(orden.get("abajo"))
                        if codigo >= 0xE0:  # Ctrl, Mayús, ⌥ y ⌘: bits, no teclas
                            bit = 1 << (codigo - 0xE0)
                            estado["mods"] = estado["mods"] | bit if abajo else estado["mods"] & ~bit
                        elif abajo and codigo not in teclas:
                            teclas.append(codigo)
                            del teclas[:-6]  # el informe lleva como mucho seis
                        elif not abajo and codigo in teclas:
                            teclas.remove(codigo)
                        await p.dispositivo.informe_teclado(estado["mods"], list(teclas))
                    elif tipo == "soltar":
                        await soltar()
                    elif tipo == "combinacion" and orden.get("atajo") in COMBINACIONES_MANDO:
                        await soltar()
                        await pulsar(hid.combinacion(orden["atajo"]))
                    elif tipo == "pegar":
                        texto = str(orden.get("texto", ""))[:5000]
                        await soltar()
                        for pulsacion in hid.secuencia(texto, p.ajustes["perfil"].get("distribucion", "mac-us")):
                            await pulsar(pulsacion)
                        await ws.send_json({"hecho": "pegar"})
                except hid.TextoIntraducible as e:
                    await ws.send_json({"no": f"No pegué nada: {e}"})
                except (KeyError, TypeError, ValueError):
                    continue
                except AparatoNoDisponible as e:
                    await ws.send_json({"no": str(e)})
        except WebSocketDisconnect:
            pass
        finally:
            await soltar()
            if estado["desde"]:
                minutos = max(1, round((time.time() - estado["desde"]) / 60))
                p.bitacora.apuntar("mando", f"la persona usó el Mac desde la pantalla (~{minutos} min)",
                                   quien="persona")

    @app.websocket("/ws/terminal")
    async def ws_terminal(ws: WebSocket):
        # 🔴 Una shell: el nombre y el origen de ESTA web, o nada.
        anfitrion = ws.headers.get("host", "")
        origen = ws.headers.get("origin", "")
        if anfitrion not in admitidos or origen not in (f"http://{anfitrion}", f"https://{anfitrion}"):
            await ws.close(code=4403)
            return
        await ws.accept()
        try:
            await asyncio.to_thread(terminal.asegurar_sesion)
        except Exception as e:
            await ws.send_text(f"\r\n[no se pudo abrir Claude Code: {e}]\r\n")
            await ws.close()
            return
        adjunto = terminal.Adjunto()
        bucle = asyncio.get_running_loop()
        salida: asyncio.Queue[bytes | None] = asyncio.Queue()

        def hay_datos():
            try:
                datos = adjunto.leer()
            except EOFError:
                bucle.remove_reader(adjunto.fd)
                salida.put_nowait(None)
                return
            if datos:
                salida.put_nowait(datos)

        bucle.add_reader(adjunto.fd, hay_datos)

        async def enviar():
            while True:
                datos = await salida.get()
                if datos is None:
                    await ws.close()
                    return
                await ws.send_bytes(datos)

        envio = asyncio.create_task(enviar())
        try:
            while True:
                m = await ws.receive()
                if m["type"] == "websocket.disconnect":
                    break
                if m.get("bytes"):
                    adjunto.escribir(m["bytes"])
                elif m.get("text"):
                    try:
                        orden = json.loads(m["text"])
                        adjunto.redimensionar(int(orden["filas"]), int(orden["columnas"]))
                    except (ValueError, KeyError, TypeError):
                        adjunto.escribir(m["text"].encode())
        except WebSocketDisconnect:
            pass
        finally:
            envio.cancel()
            adjunto.cerrar()

    return app
