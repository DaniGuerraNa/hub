"""El guardián: se engancha al navegador por CDP y decide cada petición.

Es un proceso aparte del que maneja el navegador (Playwright MCP, DevTools MCP o
lo que sea), y eso es lo que lo hace útil: no depende de que el agente se porte
bien ni de qué herramienta use. Se conecta como un cliente CDP más, se adjunta a
cada pestaña (también a las que se abran después) y pausa sus peticiones con el
dominio Fetch hasta decidir.

Registro: una línea por petición que no sea lectura simple, sin cuerpos ni
cabeceras —pueden llevar tokens— y sin la query de la URL.
"""
import argparse
import hashlib
import os
import signal
import asyncio
import itertools
import json
import time
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

import websockets

from .aprobaciones import Aprobaciones
from .politica import Politica, decidir

from .config import DATOS  # noqa: E402  (se reexporta: lo usan reproducir y los tests)


def vigilancia(cdp: str) -> Path:
    """Dónde deja constancia el guardián de que vigila ese navegador.

    Lo lee el reproductor antes de correr un flujo: sin guardián vivo sobre el
    mismo CDP, no corre (salvo que se le diga explícitamente)."""
    d = DATOS / "vigilancia"
    d.mkdir(parents=True, exist_ok=True)
    return d / (hashlib.sha1(cdp.rstrip("/").encode()).hexdigest()[:12] + ".json")


def vigilado(cdp: str) -> dict | None:
    f = vigilancia(cdp)
    if not f.exists():
        return None
    d = json.loads(f.read_text())
    return d if Path(f"/proc/{d['pid']}").exists() else None


def timbre_del_hub(pid: str) -> None:
    """Deja el aviso donde el relé del hub recoge los del orquestador.

    🔴 Sólo el aviso y el id (regla dura 22 del hub): ni la acción ni la URL,
    que pueden llevar nombres de recursos de un cliente. Se contesta en el hub.
    """
    casa = Path(os.environ.get("HUB_HOME") or Path.home() / ".local/share/hub")
    d = casa / "orquestador" / "timbres"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{time.time_ns()}.json").write_text(json.dumps(
        {"texto": f"El navegante pide permiso para una acción (pregunta {pid}).",
         "cuando": time.strftime("%Y-%m-%dT%H:%M:%S"), "pantalla": "Navegante"}, ensure_ascii=False))


class Guardian:
    def __init__(self, cdp: str, politica: Politica, registro: Path, aprob: Aprobaciones):
        self.cdp, self.p, self.registro, self.aprob = cdp, politica, registro, aprob
        self.ids = itertools.count(1)
        self.esperando: dict[int, asyncio.Future] = {}
        self.adjuntas: set[str] = set()
        # Una sesión por objetivo: si quedan dos (la del auto-adjunte y la de un
        # attachToTarget explícito) cada petición se pausa dos veces y se pregunta
        # dos veces por el mismo borrado.
        self.objetivos: set[str] = set()

    async def mandar(self, metodo, params=None, sesion=None, esperar=True):
        i = next(self.ids)
        msg = {"id": i, "method": metodo, "params": params or {}}
        if sesion:
            msg["sessionId"] = sesion
        fut = asyncio.get_running_loop().create_future()
        self.esperando[i] = fut
        await self.ws.send(json.dumps(msg))
        return await fut if esperar else None

    def anotar(self, **d):
        self.registro.parent.mkdir(parents=True, exist_ok=True)
        with self.registro.open("a") as f:
            f.write(json.dumps({"t": round(time.time(), 3), **d}, ensure_ascii=False) + "\n")

    async def adjuntar(self, sesion, info, esperando_depurador):
        try:
            await self.mandar("Fetch.enable", {"patterns": [{"urlPattern": "*", "requestStage": "Request"}]}, sesion)
            await self.mandar("Target.setAutoAttach", {"autoAttach": True, "waitForDebuggerOnStart": True,
                                                      "flatten": True}, sesion)
        finally:
            if esperando_depurador:
                await self.mandar("Runtime.runIfWaitingForDebugger", {}, sesion)

    async def pausada(self, sesion, ev):
        req = ev["request"]
        url, metodo, tipo = req["url"], req["method"], ev.get("resourceType", "")
        v = decidir(self.p, metodo, url, tipo, req.get("headers", {}), req.get("postData"))
        s = urlsplit(url)
        destino = f"{s.scheme}://{s.netloc}{s.path}"
        if v.decision == "preguntar":
            self.anotar(evento="pregunta", metodo=metodo, url=destino, accion=v.accion)
            ok = await self.aprob.pedir(accion=v.accion, metodo=metodo, url=destino,
                                        politica=self.p.nombre)
            v.decision = "permitir" if ok else "bloquear"
            v.motivo = "aprobada por el dueño" if ok else "denegada o sin respuesta"
        if v.decision == "permitir":
            if v.motivo != "método de lectura":
                self.anotar(evento="permitida", id=ev["requestId"], metodo=metodo, url=destino, accion=v.accion, motivo=v.motivo)
            await self.mandar("Fetch.continueRequest", {"requestId": ev["requestId"]}, sesion, esperar=False)
        else:
            self.anotar(evento="bloqueada", id=ev["requestId"], metodo=metodo, url=destino, accion=v.accion,
                        motivo=v.motivo, tipo=tipo)
            await self.mandar("Fetch.failRequest", {"requestId": ev["requestId"],
                                                    "errorReason": "BlockedByClient"}, sesion, esperar=False)

    async def _sobra(self, sesion, esperando):
        if esperando:
            await self.mandar("Runtime.runIfWaitingForDebugger", {}, sesion)
        await self.mandar("Target.detachFromTarget", {"sessionId": sesion})

    async def correr(self, listo: asyncio.Event | None = None):
        ver = json.load(urllib.request.urlopen(f"{self.cdp}/json/version"))
        async with websockets.connect(ver["webSocketDebuggerUrl"], max_size=None) as self.ws:
            lector = asyncio.create_task(self.leer())
            await self.mandar("Target.setDiscoverTargets", {"discover": True})
            await self.mandar("Target.setAutoAttach", {"autoAttach": True, "waitForDebuggerOnStart": True,
                                                      "flatten": True})
            for t in (await self.mandar("Target.getTargets"))["targetInfos"]:
                if t["type"] == "page" and not t.get("attached_by_us"):
                    await self.mandar("Target.attachToTarget", {"targetId": t["targetId"], "flatten": True})
            self.anotar(evento="guardian-arranca", politica=self.p.nombre, modo=self.p.modo)
            vigilancia(self.cdp).write_text(json.dumps({"pid": os.getpid(), "cdp": self.cdp,
                                                         "politica": self.p.nombre, "modo": self.p.modo}))
            if listo:
                listo.set()
            await lector

    async def leer(self):
        async for crudo in self.ws:
            m = json.loads(crudo)
            if "id" in m:
                fut = self.esperando.pop(m["id"], None)
                if fut and not fut.done():
                    fut.set_result(m.get("result", {}))
                continue
            metodo, params, sesion = m.get("method"), m.get("params", {}), m.get("sessionId")
            if metodo == "Target.attachedToTarget":
                sid, tid = params["sessionId"], params["targetInfo"]["targetId"]
                if tid in self.objetivos:
                    asyncio.create_task(self._sobra(sid, params.get("waitingForDebugger")))
                elif sid not in self.adjuntas:
                    self.objetivos.add(tid)
                    self.adjuntas.add(sid)
                    asyncio.create_task(self.adjuntar(sid, params["targetInfo"], params.get("waitingForDebugger")))
            elif metodo == "Target.detachedFromTarget":
                self.objetivos.discard(params.get("targetId", ""))
            elif metodo == "Target.targetDestroyed":
                self.objetivos.discard(params.get("targetId", ""))
            elif metodo == "Target.targetCreated" and params["targetInfo"]["type"] == "page" \
                    and not params["targetInfo"].get("attached"):
                asyncio.create_task(self.mandar("Target.attachToTarget",
                                                {"targetId": params["targetInfo"]["targetId"], "flatten": True}))
            elif metodo == "Fetch.requestPaused":
                asyncio.create_task(self.pausada(sesion, params))


def main():
    a = argparse.ArgumentParser(description="Guardián de red del navegador")
    a.add_argument("--cdp", default="http://127.0.0.1:9222")
    a.add_argument("--politica", required=True)
    a.add_argument("--registro", default=str(DATOS / "registro.jsonl"))
    a.add_argument("--aprobaciones", default=str(DATOS / "aprobaciones"))
    a.add_argument("--espera", type=float, default=300, help="segundos antes de dar una pregunta por denegada")
    args = a.parse_args()
    p = Politica.cargar(Path(args.politica))
    aprob = Aprobaciones(Path(args.aprobaciones), args.espera,
                         timbre_del_hub if p.avisar == "telegram" else None)
    # Al salir se borra la constancia de vigilancia: si no, el hub enseñaría
    # guardianes «parados» que nadie va a volver a arrancar. Si muere de un
    # SIGKILL queda, y el hub lo ve parado por su pid: es la verdad.
    def salir(*_):
        try:
            vigilancia(args.cdp).unlink()
        except OSError:
            pass
        raise SystemExit(0)
    signal.signal(signal.SIGTERM, salir)
    signal.signal(signal.SIGINT, salir)
    try:
        asyncio.run(Guardian(args.cdp, p, Path(args.registro), aprob).correr())
    finally:
        salir()


if __name__ == "__main__":
    main()
