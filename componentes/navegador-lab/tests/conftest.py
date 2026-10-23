"""Piezas reales para los tests: la consola falsa, un Chromium con CDP y el guardián.

Nada de dobles: el guardián se prueba con un navegador de verdad pidiendo cosas de
verdad a un servidor de verdad, porque lo que hay que demostrar es que la petición
no LLEGA, y eso sólo lo dice el servidor.
"""
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
CHROME = os.environ.get("NAV_CHROME") or str(next(Path.home().glob(".cache/ms-playwright/chromium-*/chrome-linux64/chrome")))


def puerto_libre():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def esperar_url(url, segundos=15):
    fin = time.time() + segundos
    while time.time() < fin:
        try:
            urllib.request.urlopen(url, timeout=1)
            return
        except Exception:
            time.sleep(0.2)
    raise TimeoutError(url)


@pytest.fixture
def consola(tmp_path):
    puerto = puerto_libre()
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "consola_falsa.app:app", "--port", str(puerto)],
                            cwd=tmp_path, env={**os.environ, "PYTHONPATH": str(RAIZ)},
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    url = f"http://127.0.0.1:{puerto}"
    esperar_url(url + "/login")
    yield {"url": url, "mutaciones": tmp_path / "mutaciones.jsonl"}
    proc.terminate(); proc.wait()


def mutaciones(consola):
    m = consola["mutaciones"]
    return [json.loads(l) for l in m.read_text().splitlines()] if m.exists() else []


@pytest.fixture
def chrome(tmp_path):
    """Un Chromium con perfil propio y CDP: lo mismo que el Chrome dedicado de Windows."""
    puerto = puerto_libre()
    perfil = tmp_path / "perfil"

    def lanzar():
        return subprocess.Popen([CHROME, "--headless=new", f"--remote-debugging-port={puerto}",
                                 f"--user-data-dir={perfil}", "--no-first-run", "--no-default-browser-check",
                                 "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    estado = {"proc": lanzar(), "cdp": f"http://127.0.0.1:{puerto}", "perfil": perfil}
    esperar_url(estado["cdp"] + "/json/version")

    def reiniciar():
        # Cerrar bien (Browser.close), no matar: Chrome escribe las cookies a disco
        # en diferido y un SIGTERM se lleva las últimas. Medido: con terminate()
        # la sesión recordada no sobrevivía.
        import asyncio, websockets
        ws = json.load(urllib.request.urlopen(estado["cdp"] + "/json/version"))["webSocketDebuggerUrl"]

        async def cerrar():
            async with websockets.connect(ws) as c:
                await c.send(json.dumps({"id": 1, "method": "Browser.close"}))
                try:
                    await c.recv()
                except Exception:
                    pass
        asyncio.run(cerrar())
        estado["proc"].wait(timeout=15)
        estado["proc"] = lanzar()
        esperar_url(estado["cdp"] + "/json/version")
    estado["reiniciar"] = reiniciar
    yield estado
    estado["proc"].terminate(); estado["proc"].wait()


def politica(tmp_path, url, modo="lectura"):
    ruta = tmp_path / f"politica-{modo}.yml"
    ruta.write_text(f"nombre: prueba\nmodo: {modo}\norigenes: ['{url}']\npermitir: [login, logout]\n")
    return ruta


@pytest.fixture
def guardian(tmp_path, chrome, consola):
    procs = []

    def arrancar(modo="lectura", espera=20):
        registro = tmp_path / "registro.jsonl"
        p = subprocess.Popen([sys.executable, "-m", "navegador.guardian", "--cdp", chrome["cdp"],
                              "--politica", str(politica(tmp_path, consola["url"], modo)),
                              "--registro", str(registro), "--aprobaciones", str(tmp_path / "aprob"),
                              "--espera", str(espera)], cwd=RAIZ,
                             env={**os.environ, "NAV_DATOS": str(tmp_path / "datos")})
        procs.append(p)
        fin = time.time() + 10
        while time.time() < fin and not (registro.exists() and "guardian-arranca" in registro.read_text()):
            time.sleep(0.1)
        return {"registro": registro, "aprob": tmp_path / "aprob"}
    yield arrancar
    for p in procs:
        p.terminate(); p.wait()
