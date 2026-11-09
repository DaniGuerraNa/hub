"""Lo que escribe un agente corre encerrado (decisión 350, C-0145).

Se prueba ejecutando de verdad dentro del encierro, no con dobles: lo que
importa es lo que el código de dentro puede ver y tocar, y eso sólo lo dice el
kernel. Sin user namespaces en la máquina, se saltan (y `servir` se niega).
"""

from __future__ import annotations

import json
import socket
import sys
import tempfile
import time
from pathlib import Path

import pytest

from hub import config, encierro, procesos

pytestmark = pytest.mark.skipif(not encierro.disponible(), reason="sin user namespaces en esta máquina")

VENV = config.RAIZ_REPO / ".venv"

SONDA = r'''
import json, os, socket, sys
fuera, salida, solo_lectura, puerto = sys.argv[1:5]
r = {}
r["home"] = sorted(os.listdir(fuera)) if os.path.isdir(fuera) else []
r["procesos"] = sum(1 for n in os.listdir("/proc") if n.isdigit())
try:
    open(os.path.join(solo_lectura, "x"), "w")
    r["escribe_en_leer"] = True
except OSError:
    r["escribe_en_leer"] = False
try:
    socket.create_connection(("127.0.0.1", int(puerto)), timeout=2)
    r["red"] = True
except OSError:
    r["red"] = False
r["entorno"] = sorted(os.environ)
r["run"] = os.path.exists("/run") or os.path.exists("/mnt")
json.dump(r, open(os.path.join(salida, "r.json"), "w"))
'''


def _corta(prefijo: str) -> Path:
    return Path(tempfile.mkdtemp(prefix=prefijo))


@pytest.fixture
def dentro(monkeypatch):
    """Ejecuta la sonda encerrada y devuelve lo que vio."""
    monkeypatch.setenv("SECRETO_DE_PRUEBA", "no-deberia-verse")
    mesa, leer = _corta("enc-mesa-"), _corta("enc-leer-")
    (mesa / "raiz").mkdir()
    (mesa / "datos").mkdir()
    (leer / "sonda.py").write_text(SONDA)
    escucha = socket.socket()
    escucha.bind(("127.0.0.1", 0))
    escucha.listen(1)
    p = encierro.lanzar([str(VENV / "bin" / "python"), str(leer / "sonda.py"), str(Path.home()),
                         str(mesa / "datos"), str(leer), str(escucha.getsockname()[1])],
                        raiz=mesa / "raiz", leer=[leer, VENV], escribir=[mesa / "datos"], cwd=leer,
                        entorno={"PYTHONDONTWRITEBYTECODE": "1"})
    p.wait(30)
    escucha.close()
    return json.loads((mesa / "datos" / "r.json").read_text())


def test_no_ve_el_home_ni_run_ni_mnt(dentro):
    """Del HOME sólo existe el camino vacío hasta el venv, que se monta."""
    camino = VENV.relative_to(Path.home()).parts[0] if Path.home() in VENV.parents else None
    assert dentro["home"] in ([], [camino])
    assert dentro["run"] is False


def test_no_tiene_red_ni_siquiera_hasta_el_hub(dentro):
    assert dentro["red"] is False


def test_no_ve_los_procesos_de_la_maquina(dentro):
    assert dentro["procesos"] <= 3


def test_lo_de_leer_no_se_escribe(dentro):
    assert dentro["escribe_en_leer"] is False


def test_no_hereda_el_entorno_de_quien_lanza(dentro):
    assert "SECRETO_DE_PRUEBA" not in dentro["entorno"]
    assert set(dentro["entorno"]) <= {"PATH", "HOME", "PYTHONDONTWRITEBYTECODE", "PWD", "LC_CTYPE", "SHLVL", "_"}


def test_no_monta_lo_que_pasa_por_un_enlace(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    (tmp_path / "enlace").symlink_to(real)
    with pytest.raises(ValueError, match="enlace"):
        encierro.lanzar(["true"], raiz=_corta("enc-r-"), leer=[tmp_path / "enlace"], cwd=real, entorno={})


def test_parar_se_lleva_todo_lo_de_dentro_y_no_toca_otro_proceso():
    mesa = _corta("enc-p-")
    (mesa / "raiz").mkdir()
    p = encierro.lanzar(["/bin/sleep", "60"], raiz=mesa / "raiz", leer=[], cwd=Path("/"), entorno={})
    time.sleep(1)
    h = procesos.huella(p.pid)
    assert encierro.parar(h) is True
    p.wait(10)
    assert not procesos.vivo(h)
    assert encierro.parar(h) is False, "un muerto no se vuelve a matar"
    otro = {"pid": 1, "arranque": "0"}
    assert encierro.parar(otro) is False, "un pid con otra huella no se toca"


def _app_por_socket(html: bytes):
    import http.server
    import socketserver
    import threading

    class Pagina(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(html if self.path.startswith("/pagina") else self.path.encode())

        def address_string(self):
            return "app"

        def log_message(self, *a):
            pass

    class PorSocket(socketserver.ThreadingUnixStreamServer):
        daemon_threads = True

    ruta = _corta("enc-s-") / "app.sock"
    servidor = PorSocket(str(ruta), Pagina)
    threading.Thread(target=servidor.serve_forever, daemon=True).start()
    return ruta, servidor


def test_peticion_llega_por_el_socket():
    ruta, servidor = _app_por_socket(b"")
    try:
        assert encierro.peticion(ruta, "GET", "/salud") == (200, b"/salud")
    finally:
        servidor.shutdown()


def test_la_foto_se_hace_encerrada_y_la_pagina_no_sale_a_la_red():
    """El navegador también va encerrado (revisor de C-0145): la página pinta,
    pero lo que pide fuera —aquí, a un servidor de 127.0.0.1 de la máquina—
    no llega."""
    from hub import mirar
    if not mirar.cual_linux():
        pytest.skip("sin un Chromium de Linux")
    import http.server
    import threading

    pedidos: list[str] = []

    class Chivato(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            pedidos.append(self.path)
            self.send_response(204)
            self.end_headers()

        def log_message(self, *a):
            pass

    fuera = http.server.HTTPServer(("127.0.0.1", 0), Chivato)
    threading.Thread(target=fuera.serve_forever, daemon=True).start()
    html = (f"<h1>hola</h1><img src='http://127.0.0.1:{fuera.server_port}/fuga'>"
            f"<script>fetch('http://127.0.0.1:{fuera.server_port}/fetch')</script>").encode()
    ruta, servidor = _app_por_socket(html)
    destino = _corta("enc-foto-") / "f.png"
    try:
        assert encierro.fotografiar(ruta, "/pagina", destino, ancho=390, alto=600).stat().st_size > 1000
    finally:
        servidor.shutdown()
        fuera.shutdown()
    assert pedidos == []


def test_un_enlace_en_lugar_del_socket_no_se_sigue(tmp_path):
    otro = tmp_path / "otro"
    otro.write_text("")
    enlace = _corta("enc-l-") / "app.sock"
    enlace.symlink_to(otro)
    with pytest.raises(ConnectionError):
        encierro.peticion(enlace, "GET", "/")


APP = """
import os, socket
from fastapi import FastAPI
app = FastAPI()

@app.get("/salud")
def salud():
    return {"ok": True}

@app.get("/api/sonda")
def sonda():
    try:
        socket.create_connection(("127.0.0.1", 8787), timeout=2)
        red = True
    except OSError:
        red = False
    return {"datos": os.environ.get("DATOS"), "red": red, "ssh": os.path.exists(os.environ["FUERA"])}
"""


def test_servir_api_y_parar_con_una_app_de_verdad(con, monkeypatch, capsys):
    """De punta a punta, como lo usa el implementador (C-0145)."""
    from hub import encargos, encargos_cli

    encargos.anotar_persona(con, 77, "quien", "Quien")
    encargos.crear(con, "encargo-1", 77)
    con.commit()
    app_ = encargos.carpeta("encargo-1") / "app"
    app_.mkdir(parents=True)
    (app_ / "main.py").write_text(APP.replace('os.environ["FUERA"]', repr(str(Path.home() / ".ssh"))))
    mesa = _corta("enc-e2e-")
    monkeypatch.setattr(encargos_cli, "_mesa", lambda e: mesa / "m")
    parser = encargos_cli.construir_parser()

    assert encargos_cli.cmd_servir(con, parser.parse_args(["--encargo", "encargo-1", "servir"])) == 0, \
        capsys.readouterr().err
    try:
        assert encargos_cli.cmd_api(con, parser.parse_args(["--encargo", "encargo-1", "api", "GET", "/api/sonda"])) == 0
        estado, cuerpo = capsys.readouterr().out.strip().splitlines()[-2:]
        r = json.loads(cuerpo)
        assert estado == "200" and r["red"] is False and r["ssh"] is False
        assert r["datos"] == str(mesa / "m" / "datos")
    finally:
        assert encargos_cli.cmd_parar(con, parser.parse_args(["--encargo", "encargo-1", "parar"])) == 0
    assert encargos_cli._servidor("encargo-1") is None
