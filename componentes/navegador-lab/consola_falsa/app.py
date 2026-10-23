"""Consola de AWS de mentira, para ensayar sin cuenta.

Imita lo que le importa a un agente que navega: un inicio de sesión cuya cookie
puede sobrevivir o no al cierre del navegador, listas y detalles de API Gateway,
y un Logs Insights asíncrono (se lanza, se espera, se leen resultados). Y tiene
botones que MUTAN —borrar, desplegar, crear— que registran cada intento en
`mutaciones.jsonl`: así un test puede comprobar que la barrera de solo-lectura los
paró, en vez de suponerlo.
"""
import json
import secrets
import time
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from . import datos, insights

AQUI = Path(__file__).parent
REGISTRO = Path.cwd() / "mutaciones.jsonl"
plantillas = Jinja2Templates(directory=AQUI / "templates")
app = FastAPI()

SESIONES: dict[str, dict] = {}
CONSULTAS: dict[str, dict] = {}
COOKIE = "aws-falsa-sesion"


def _usuario(req: Request):
    s = SESIONES.get(req.cookies.get(COOKIE, ""))
    if s and s["expira"] > time.time():
        return s
    return None


def _pagina(req, nombre, **ctx):
    u = _usuario(req)
    if not u:
        return RedirectResponse(f"/login?siguiente={req.url.path}", status_code=303)
    region = req.query_params.get("region", "us-east-1")
    return plantillas.TemplateResponse(req, nombre, {"u": u, "region": region,
                                                     "regiones": datos.REGIONES, **ctx})


@app.get("/login", response_class=HTMLResponse)
def login(req: Request, siguiente: str = "/console/home"):
    return plantillas.TemplateResponse(req, "login.html", {"siguiente": siguiente})


@app.post("/login")
def login_post(usuario: str = Form(...), clave: str = Form(...),
               recordar: str = Form(""), siguiente: str = Form("/console/home")):
    # Cualquier usuario/clave entra: es de mentira. Lo que se ensaya es la cookie.
    sid = secrets.token_hex(16)
    SESIONES[sid] = {"usuario": usuario, "cuenta": "123456789012",
                     "rol": "ReadOnly", "expira": time.time() + 12 * 3600}
    r = RedirectResponse(siguiente if siguiente.startswith("/") else "/", status_code=303)
    # «Recordar» = cookie persistente (sobrevive al cierre del navegador si el
    # perfil se guarda); sin marcar = cookie de sesión, que se pierde al cerrar.
    r.set_cookie(COOKIE, sid, httponly=True, samesite="lax",
                 max_age=12 * 3600 if recordar else None)
    return r


@app.post("/logout")
def logout(req: Request):
    SESIONES.pop(req.cookies.get(COOKIE, ""), None)
    r = RedirectResponse("/login", status_code=303)
    r.delete_cookie(COOKIE)
    return r


@app.get("/")
@app.get("/console/home", response_class=HTMLResponse)
def inicio(req: Request):
    return _pagina(req, "inicio.html")


@app.get("/apigateway/main/apis", response_class=HTMLResponse)
def apis(req: Request, region: str = "us-east-1"):
    return _pagina(req, "apis.html", apis=[a for a in datos.APIS if a["region"] == region])


@app.get("/apigateway/main/apis/{api_id}/resources", response_class=HTMLResponse)
def api_detalle(req: Request, api_id: str):
    api = next((a for a in datos.APIS if a["id"] == api_id), None)
    if not api:
        return HTMLResponse("No existe", status_code=404)
    return _pagina(req, "api.html", api=api)


@app.get("/cloudwatch/home", response_class=HTMLResponse)
def cloudwatch(req: Request):
    # La consola real mete Logs Insights tras un fragmento (#logsV2:logs-insights):
    # el servidor nunca lo ve, la página decide en el navegador.
    return _pagina(req, "cloudwatch.html", grupos=datos.GRUPOS_DE_LOGS)


def _api_auth(req):
    return _usuario(req) is not None


@app.post("/api/logs/StartQuery")
async def start_query(req: Request):
    if not _api_auth(req):
        return JSONResponse({"error": "sesión caducada"}, status_code=401)
    cuerpo = await req.json()
    qid = secrets.token_hex(8)
    try:
        res = insights.ejecutar(cuerpo.get("queryString", ""), cuerpo.get("logGroupNames", []))
        CONSULTAS[qid] = {"listo": time.time() + 1.5, "res": res}
    except insights.ErrorDeConsulta as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    return {"queryId": qid}


@app.post("/api/logs/GetQueryResults")
async def get_results(req: Request):
    if not _api_auth(req):
        return JSONResponse({"error": "sesión caducada"}, status_code=401)
    q = CONSULTAS.get((await req.json()).get("queryId", ""))
    if not q:
        return JSONResponse({"error": "consulta desconocida"}, status_code=404)
    if time.time() < q["listo"]:
        return {"status": "Running"}
    return {"status": "Complete", **q["res"]}


def _mutar(req: Request, accion: str, objetivo: str):
    with REGISTRO.open("a") as f:
        f.write(json.dumps({"t": time.time(), "accion": accion, "objetivo": objetivo,
                            "usuario": (_usuario(req) or {}).get("usuario")}) + "\n")


@app.post("/api/apigateway/DeleteRestApi")
async def borrar_api(req: Request):
    _mutar(req, "DeleteRestApi", (await req.json()).get("restApiId", ""))
    return {"ok": True}


@app.post("/api/apigateway/CreateDeployment")
async def desplegar(req: Request):
    _mutar(req, "CreateDeployment", (await req.json()).get("restApiId", ""))
    return {"ok": True}


@app.get("/api/estado/notificaciones")
def notificaciones():
    # Algo que cambia solo, como el reloj y avisos de la consola real: el ruido que
    # una instantánea incremental debería ignorar o resumir.
    return {"hora": time.strftime("%H:%M:%S"), "avisos": int(time.time()) % 5}
