"""`nav`: la única puerta, para el dueño, para Claude y para el hub.

    nav estado [--json]              navegador, guardián, panel y grabación
    nav resumen --json               estado + flujos + políticas + config (lo que lee el hub)
    nav navegador [--visible] [URL]  abre el Chrome del laboratorio (perfil propio, CDP en 127.0.0.1)
    nav cerrar                       lo cierra BIEN (las cookies se escriben al cerrar)
    nav ir URL                       abre URL en la pestaña de trabajo
    nav panel                        vista en vivo para verlo y manejarlo (http://localhost:4848)
    nav guardian [--politica X] [--fondo]   vigila el navegador con una política
    nav parar-guardian
    nav politicas [--json] | nav flujos [--json]
    nav grabar empezar | parar NOMBRE [-p k=v] [--coleccion C] [--descripcion D]
               [--desde PANTALLA] [--hasta PANTALLA] [--pisar] | estado
    nav flujo NOMBRE [-p k=v] [--fondo] [--sin-guardian]
               (--sin-guardian: corre aunque nadie vigile; sólo el dueño, sólo contra
               la consola falsa — Claude lo tiene denegado)
    nav pantallas FLUJO DESDE [HASTA]  marca dónde empieza y acaba un fragmento
    nav componer NOMBRE FRAG1 FRAG2 … [--coleccion C] [--descripcion D] [--pisar]
                                     une fragmentos en orden en un flujo nuevo
    nav acceso NOMBRE URL | --quitar  accesos directos de la pantalla
    nav mapa [--json]                pantallas y los fragmentos que las conectan
    nav pendientes | aprobar ID | denegar ID   (aprobar/denegar: sólo el dueño)
    nav registro [N]

El hub llama a estos mismos comandos: lo que se puede hacer desde la pantalla se
puede hacer desde aquí, y al revés.
"""
import argparse
import asyncio
import json
import os
import shutil
import signal
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import yaml

from . import config
from .aprobaciones import Aprobaciones
from .config import CDP, DATOS, RAIZ
from .flujo import convertir
from .guardian import vigilado, vigilancia

PERFIL = Path(os.environ.get("NAV_PERFIL", DATOS / "perfil"))
SESION_PANEL = "panel"         # la sesión de agent-browser que se ve en el panel
GRABANDO = DATOS / "grabando.json"
PANEL = "http://localhost:4848"


def _chrome() -> str:
    for c in (os.environ.get("NAV_CHROME"), shutil.which("google-chrome"), shutil.which("chromium")):
        if c:
            return c
    cands = sorted(Path.home().glob(".cache/ms-playwright/chromium-*/chrome-linux64/chrome"))
    if not cands:
        sys.exit("No encuentro Chrome. Pon NAV_CHROME o: npx playwright install chromium")
    return str(cands[-1])


# Una pantalla virtual para el Chrome CON ventana (22-oct). En modo headless
# Chrome se anuncia como «HeadlessChrome», y hay sitios —el de solicitudes del
# trabajo, detrás de CloudFront— que lo cortan con un 403. Un Chrome con
# ventana es un navegador normal; la ventana se pinta aquí en vez de en el
# escritorio porque WSLg se cuelga, y se ve igual por el panel en vivo.
PANTALLA = os.environ.get("NAV_PANTALLA", ":99")


def _pantalla_virtual() -> str | None:
    """El DISPLAY de la pantalla virtual, levantándola si hace falta. None sin Xvfb."""
    if not shutil.which("Xvfb"):
        return None
    numero = PANTALLA.lstrip(":")
    try:
        viva = f"@/tmp/.X11-unix/X{numero}" in Path("/proc/net/unix").read_text()
    except OSError:
        viva = False
    if not viva:
        subprocess.Popen(["Xvfb", PANTALLA, "-screen", "0", "1366x900x24", "-nolisten", "tcp"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        time.sleep(1)
    return PANTALLA


def _npx(*args, timeout=60):
    return subprocess.run(["npx", "--no-install", *args], cwd=RAIZ, text=True, capture_output=True,
                          timeout=timeout)


def _ab(*args, timeout=60):
    puerto = CDP.rsplit(":", 1)[-1].strip("/")
    return subprocess.run(["npx", "--no-install", "agent-browser", "--cdp", puerto, *args], cwd=RAIZ,
                          text=True, capture_output=True, timeout=timeout,
                          env={**os.environ, "AGENT_BROWSER_SESSION": SESION_PANEL})


def _json_url(ruta, timeout=2):
    return json.load(urllib.request.urlopen(CDP.rstrip("/") + ruta, timeout=timeout))


def _vivo(url, timeout=1.5) -> bool:
    try:
        urllib.request.urlopen(url, timeout=timeout)
        return True
    except Exception:
        return False


def leer_estado() -> dict:
    e = {"cdp": CDP, "perfil": str(PERFIL)}
    try:
        v = _json_url("/json/version")
        pest = [{"titulo": t.get("title", ""), "url": t.get("url", "")}
                for t in _json_url("/json/list") if t.get("type") == "page"]
        e["navegador"] = {"vivo": True, "version": v.get("Browser", ""), "pestanas": pest}
    except Exception:
        e["navegador"] = {"vivo": False}
    g = vigilado(CDP)
    e["guardian"] = {"vivo": bool(g), **(g or {})}
    e["panel"] = {"vivo": _vivo(PANEL), "url": PANEL}
    gr = json.loads(GRABANDO.read_text()) if GRABANDO.exists() else None
    e["grabando"] = gr
    return e


def estado(a):
    e = leer_estado()
    if a.json:
        print(json.dumps(e, ensure_ascii=False))
        return
    n = e["navegador"]
    print(f"Navegador: {'encendido ' + n['version'] if n['vivo'] else 'apagado'} ({CDP})")
    for p in n.get("pestanas", []):
        print(f"   · {p['titulo'][:50]}  {p['url'][:80]}")
    g = e["guardian"]
    print(f"Guardián:  {'vigilando · política ' + g['politica'] + ' · modo ' + g['modo'] if g['vivo'] else 'parado'}")
    print(f"Panel:     {'abierto en ' + PANEL if e['panel']['vivo'] else 'cerrado (nav panel)'}")
    if e["grabando"]:
        print(f"Grabando desde las {time.strftime('%H:%M', time.localtime(e['grabando']['desde']))}")


def resumen(a):
    """Todo lo que pinta el hub, en una llamada: arrancar `uv run` cuesta más
    que lo que se consulta, y tres llamadas eran tres arranques."""
    print(json.dumps({"estado": leer_estado(), "flujos": config.flujos(), "mapa": config.mapa(),
                      "politicas": config.politicas(), "config": config.cargar()}, ensure_ascii=False))


def navegador(a):
    if leer_estado()["navegador"]["vivo"]:
        print(f"Ya está encendido en {CDP}.")
        if a.url != "about:blank":
            ir(argparse.Namespace(url=a.url))
        return
    puerto = CDP.rsplit(":", 1)[-1].strip("/")
    PERFIL.mkdir(parents=True, exist_ok=True)
    # 0700: el perfil guarda las cookies de la sesión de AWS; en Linux sin
    # llavero van casi en claro (investigacion/03).
    PERFIL.chmod(0o700)
    cmd = [_chrome(), f"--remote-debugging-port={puerto}", "--remote-debugging-address=127.0.0.1",
           f"--user-data-dir={PERFIL}", "--no-first-run", "--no-default-browser-check",
           "--window-size=1366,900"]
    entorno = dict(os.environ)
    if not a.visible:
        pantalla = _pantalla_virtual()
        if pantalla:
            entorno["DISPLAY"] = pantalla   # con ventana, en la pantalla virtual
        else:
            cmd.append("--headless=new")    # sin Xvfb: headless (algunos sitios lo bloquean)
    subprocess.Popen(cmd + [a.url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True, env=entorno)
    for _ in range(40):
        if _vivo(CDP + "/json/version"):
            break
        time.sleep(0.25)
    else:
        sys.exit("El navegador no abrió el puerto CDP en 10 s." +
                 (" En modo visible suele ser WSLg colgado: prueba sin --visible y usa `nav panel`." if a.visible else ""))
    print(f"Navegador encendido en {CDP} (perfil {PERFIL}).")


def cerrar(a):
    """Browser.close y no matar: Chrome escribe las cookies en diferido y un
    SIGTERM se lleva las últimas (medido: la sesión no sobrevivía)."""
    import websockets
    try:
        ws = _json_url("/json/version")["webSocketDebuggerUrl"]
    except Exception:
        print("Ya estaba apagado.")
        return

    async def c():
        async with websockets.connect(ws) as w:
            await w.send(json.dumps({"id": 1, "method": "Browser.close"}))
            try:
                await asyncio.wait_for(w.recv(), 5)
            except Exception:
                pass
    asyncio.run(c())
    for _ in range(40):
        if not _vivo(CDP + "/json/version", 0.5):
            print("Navegador cerrado; la sesión queda guardada en el perfil.")
            return
        time.sleep(0.25)
    sys.exit("Pidió cerrarse pero sigue respondiendo.")


def ir(a):
    if not leer_estado()["navegador"]["vivo"]:
        sys.exit("El navegador está apagado: nav navegador")
    r = _ab("open", a.url)
    if r.returncode:
        sys.exit((r.stdout + r.stderr).strip()[-400:])
    print(f"Abierto: {a.url}")


def panel(a):
    if not leer_estado()["navegador"]["vivo"]:
        sys.exit("El navegador está apagado: nav navegador")
    if not _vivo(PANEL):
        _npx("agent-browser", "dashboard", "start")
    # El panel enseña las sesiones de agent-browser: se engancha una al navegador
    # del laboratorio para que aparezca, sin navegar a ningún sitio.
    _ab("get", "url")
    print(f"Panel en vivo: {PANEL}  (sesión «{SESION_PANEL}»)")


def guardian(a):
    ruta = config.buscar_politica(a.politica)
    if vigilado(CDP):
        sys.exit("Ya hay un guardián vigilando este navegador: nav parar-guardian primero.")
    args = [sys.executable, "-m", "navegador.guardian", "--cdp", CDP, "--politica", str(ruta)]
    if not a.fondo:
        os.execvp(sys.executable, args)
    DATOS.mkdir(parents=True, exist_ok=True)
    log = open(DATOS / "guardian.log", "a")
    subprocess.Popen(args, cwd=RAIZ, stdout=log, stderr=log, start_new_session=True)
    for _ in range(40):
        if vigilado(CDP):
            print(f"Guardián vigilando con la política {ruta.stem}.")
            return
        time.sleep(0.25)
    sys.exit(f"El guardián no arrancó; mira {DATOS / 'guardian.log'}")


def parar_guardian(a):
    g = vigilado(CDP)
    if not g:
        print("No había guardián.")
        return
    os.kill(g["pid"], signal.SIGTERM)
    for _ in range(20):
        if not vigilado(CDP):
            print("Guardián parado. 🔴 Sin él, nada frena una petición que modifique.")
            return
        time.sleep(0.25)
    sys.exit("No se paró.")


def politicas(a):
    ps = config.politicas()
    if a.json:
        print(json.dumps(ps, ensure_ascii=False))
        return
    for p in ps:
        print(f"{p['archivo']:<28} modo {p['modo']:<10} {', '.join(p['origenes'])[:70]}")


def flujos(a):
    fs = config.flujos()
    if a.json:
        print(json.dumps(fs, ensure_ascii=False))
        return
    for f in fs:
        ps = ", ".join(f["parametros"])
        print(f"{f['coleccion']}/{f['nombre']:<28} {f.get('pasos', '?')} pasos  ({ps})")


def grabar(a):
    s = "-s=grabacion"
    if a.que == "estado":
        print(GRABANDO.read_text() if GRABANDO.exists() else "No se está grabando.")
        return
    if a.que == "empezar":
        if GRABANDO.exists():
            sys.exit("Ya se está grabando: nav grabar parar NOMBRE")
        r = _npx("playwright-cli", s, "attach", "--cdp", CDP)
        if r.returncode:
            sys.exit(r.stdout + r.stderr)
        r = _npx("playwright-cli", s, "recording-start")
        if r.returncode:
            sys.exit(r.stdout + r.stderr)
        DATOS.mkdir(parents=True, exist_ok=True)
        GRABANDO.write_text(json.dumps({"desde": time.time()}))
        print("Grabando. Haz el flujo en el navegador (con la sesión YA iniciada).")
        print("Al terminar: nav grabar parar NOMBRE")
        return
    if not a.nombre:
        sys.exit("Dime el nombre del flujo: nav grabar parar NOMBRE")
    r = _npx("playwright-cli", s, "recording-stop")
    _npx("playwright-cli", s, "detach")
    GRABANDO.unlink(missing_ok=True)
    # La grabación cruda NO se escribe a disco: puede llevar lo que se tecleó
    # en un campo de contraseña. Va de la memoria al conversor, que lo tacha.
    codigo = r.stdout.split("```js", 1)[-1].split("```", 1)[0] if "```js" in r.stdout else ""
    if not codigo.strip():
        sys.exit("La grabación salió vacía: ¿hiciste algo en el navegador mientras grababa?")
    params = dict(x.split("=", 1) for x in a.param if "=" in x)
    c = convertir(codigo, a.nombre, a.descripcion or "", params)
    pant = {k: v for k, v in (("desde", a.desde), ("hasta", a.hasta)) if v}
    if pant:
        c.flujo = {**{k: v for k, v in c.flujo.items() if k not in ("parametros", "pasos")}, "pantallas": pant,
                   "parametros": c.flujo["parametros"], "pasos": c.flujo["pasos"]}
    cols = {c_["nombre"]: Path(c_["ruta"]) for c_ in config.cargar()["colecciones"]}
    carpeta = cols.get(a.coleccion) or next(iter(cols.values()))
    carpeta.mkdir(parents=True, exist_ok=True)
    destino = carpeta / f"{a.nombre}.yml"
    if destino.exists() and not a.pisar:
        destino = carpeta / f"{a.nombre}.nuevo.yml"
    destino.write_text(yaml.safe_dump(c.flujo, allow_unicode=True, sort_keys=False))
    if a.json:
        print(json.dumps({"ruta": str(destino), "pasos": len(c.flujo["pasos"]), "avisos": c.avisos},
                         ensure_ascii=False))
        return
    print(f"✓ {destino}  ({len(c.flujo['pasos'])} pasos)")
    for av in c.avisos:
        print("  ! " + av)
    print("Revísalo: añade `esperar` tras lo que tarde y `extraer` para lo que quieras guardar.")


def componer_cmd(a):
    from .flujo import componer
    todos = config.flujos()
    elegidos = []
    for n in a.fragmentos:
        col, _, nom = n.rpartition("/")
        f = next((x for x in todos if x["nombre"] == nom and (not col or x["coleccion"] == col)), None)
        if not f:
            sys.exit(f"No hay ningún flujo «{n}».")
        elegidos.append(f)
    c = componer(a.nombre, elegidos, a.descripcion or "")
    cols = {c_["nombre"]: Path(c_["ruta"]) for c_ in config.cargar()["colecciones"]}
    carpeta = cols.get(a.coleccion) or next(iter(cols.values()))
    carpeta.mkdir(parents=True, exist_ok=True)
    destino = carpeta / f"{a.nombre}.yml"
    if destino.exists() and not a.pisar:
        sys.exit(f"Ya existe {destino}: usa otro nombre o --pisar.")
    destino.write_text(yaml.safe_dump(c.flujo, allow_unicode=True, sort_keys=False))
    if a.json:
        print(json.dumps({"ruta": str(destino), "pasos": len(c.flujo["pasos"]), "avisos": c.avisos},
                         ensure_ascii=False))
        return
    print(f"✓ {destino}  ({len(elegidos)} fragmentos)")
    for av in c.avisos:
        print("  ! " + av)


def pantallas_cmd(a):
    """Marca desde qué pantalla empieza un flujo y en cuál termina."""
    ruta = config.buscar_flujo(a.flujo)
    y = yaml.safe_load(ruta.read_text())
    p = {k: v for k, v in (("desde", a.desde), ("hasta", a.hasta)) if v}
    y = {**{k: v for k, v in y.items() if k not in ("parametros", "pasos")}, "pantallas": p,
         "parametros": y.get("parametros") or {}, "pasos": y.get("pasos") or []}
    ruta.write_text(yaml.safe_dump(y, allow_unicode=True, sort_keys=False))
    print(f"{ruta.stem}: {a.desde} → {a.hasta or a.desde}")


def mapa_cmd(a):
    m = config.mapa()
    if a.json:
        print(json.dumps(m, ensure_ascii=False))
        return
    for p, cs in m["salen"].items():
        print(p)
        for c in cs:
            print(f"   └─ {c['flujo']}  → {c['hasta'] if c['hasta'] != p else '(se queda)'}")
    if m["sin_pantalla"]:
        print("Sin pantalla marcada: " + ", ".join(m["sin_pantalla"]))


def acceso(a):
    """Los accesos directos de la pantalla (el portal de AWS del trabajo, la
    consola falsa…). Viven en config.yml de los datos: son tuyos, no del repo."""
    c = config.cargar()
    accs = [x for x in c.get("accesos", []) if x["nombre"] != a.nombre]
    if not a.quitar:
        if not a.url or not a.url.startswith(("http://", "https://")):
            sys.exit("La dirección tiene que empezar por http:// o https://")
        accs.append({"nombre": a.nombre, "url": a.url})
    guardable = {k: v for k, v in c.items() if k in ("colecciones", "politicas")}
    if os.environ.get("NAV_FLUJOS"):
        guardable["colecciones"] = guardable["colecciones"][1:]
    config.guardar({**guardable, "accesos": accs})
    print(("Quitado" if a.quitar else "Guardado") + f" el acceso «{a.nombre}».")


def flujo(a):
    ruta = config.buscar_flujo(a.nombre)
    args = [sys.executable, "-m", "navegador.reproducir", str(ruta), "--cdp", CDP]
    for p in a.param:
        args += ["-p", p]
    if a.sin_guardian:
        args.append("--sin-guardian")
    if a.fondo:
        log = open(DATOS / "flujos.log", "a")
        subprocess.Popen(args, cwd=RAIZ, stdout=log, stderr=log, start_new_session=True)
        print(f"Corriendo {ruta.stem} en segundo plano.")
        return
    sys.exit(subprocess.call(args, cwd=RAIZ))


def pendientes(a):
    ps = Aprobaciones(DATOS / "aprobaciones").pendientes()
    if not ps:
        print("Nada pendiente.")
    for p in ps:
        print(f"{p['id']}  {p['accion']}  {p['metodo']} {p['url']}  (política {p['politica']})")


def responder(a, aprobar):
    d = Aprobaciones(DATOS / "aprobaciones").responder(a.id, aprobar)
    print(f"{'Aprobada' if aprobar else 'Denegada'}: {d['accion']} {d['url']}")


def registro(a):
    f = DATOS / "registro.jsonl"
    if not f.exists():
        print("Sin registro todavía.")
        return
    for l in f.read_text().splitlines()[-a.n:]:
        e = json.loads(l)
        print(f"{e['evento']:<16} {e.get('accion', ''):<20} {e.get('metodo', '')} {e.get('url', '')} {e.get('motivo', '')}")


def main():
    a = argparse.ArgumentParser(prog="nav", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = a.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("estado"); s.add_argument("--json", action="store_true"); s.set_defaults(f=estado)
    s = sub.add_parser("resumen"); s.add_argument("--json", action="store_true"); s.set_defaults(f=resumen)
    s = sub.add_parser("navegador"); s.add_argument("--visible", action="store_true")
    s.add_argument("url", nargs="?", default="about:blank"); s.set_defaults(f=navegador)
    sub.add_parser("cerrar").set_defaults(f=cerrar)
    s = sub.add_parser("ir"); s.add_argument("url"); s.set_defaults(f=ir)
    sub.add_parser("panel").set_defaults(f=panel)
    s = sub.add_parser("guardian"); s.add_argument("--politica", default="aws-lectura")
    s.add_argument("--fondo", action="store_true"); s.set_defaults(f=guardian)
    sub.add_parser("parar-guardian").set_defaults(f=parar_guardian)
    s = sub.add_parser("politicas"); s.add_argument("--json", action="store_true"); s.set_defaults(f=politicas)
    s = sub.add_parser("flujos"); s.add_argument("--json", action="store_true"); s.set_defaults(f=flujos)
    s = sub.add_parser("grabar"); s.add_argument("que", choices=["empezar", "parar", "estado"])
    s.add_argument("nombre", nargs="?"); s.add_argument("-p", "--param", action="append", default=[])
    s.add_argument("--descripcion"); s.add_argument("--coleccion"); s.add_argument("--pisar", action="store_true")
    s.add_argument("--desde"); s.add_argument("--hasta")
    s.add_argument("--json", action="store_true"); s.set_defaults(f=grabar)
    s = sub.add_parser("componer"); s.add_argument("nombre"); s.add_argument("fragmentos", nargs="+")
    s.add_argument("--descripcion"); s.add_argument("--coleccion"); s.add_argument("--pisar", action="store_true")
    s.add_argument("--json", action="store_true"); s.set_defaults(f=componer_cmd)
    s = sub.add_parser("pantallas"); s.add_argument("flujo"); s.add_argument("desde"); s.add_argument("hasta", nargs="?")
    s.set_defaults(f=pantallas_cmd)
    s = sub.add_parser("acceso"); s.add_argument("nombre"); s.add_argument("url", nargs="?")
    s.add_argument("--quitar", action="store_true"); s.set_defaults(f=acceso)
    s = sub.add_parser("mapa"); s.add_argument("--json", action="store_true"); s.set_defaults(f=mapa_cmd)
    s = sub.add_parser("flujo"); s.add_argument("nombre"); s.add_argument("-p", "--param", action="append", default=[])
    s.add_argument("--sin-guardian", action="store_true"); s.add_argument("--fondo", action="store_true")
    s.set_defaults(f=flujo)
    sub.add_parser("pendientes").set_defaults(f=pendientes)
    s = sub.add_parser("aprobar"); s.add_argument("id"); s.set_defaults(f=lambda x: responder(x, True))
    s = sub.add_parser("denegar"); s.add_argument("id"); s.set_defaults(f=lambda x: responder(x, False))
    s = sub.add_parser("registro"); s.add_argument("n", nargs="?", type=int, default=20); s.set_defaults(f=registro)
    args = a.parse_args()
    args.f(args)


if __name__ == "__main__":
    main()
