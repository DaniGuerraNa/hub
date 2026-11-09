"""El tercer agente: de la maqueta al sistema (decisión 244).

Lo que se fija aquí es dónde están las puertas —quién puede abrirlo y sobre
qué— y qué NO hace: no ve contraseñas, no sale de su carpeta, y la maqueta
que le sirve de especificación no se toca.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hub import config, constructor, db, encargos, encargos_cli, implementador, procesos


@pytest.fixture
def con(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "hub.db")
    con = db.conectar(config.DB_PATH)
    db.inicializar(con)
    yield con
    con.close()


@pytest.fixture
def escena(con):
    encargos.anotar_persona(con, 77, "quien", "Quien")
    encargos.editar_persona(con, 77, estado="activo", alias="Rosa")
    encargos.anotar_persona(con, 1, "eldueno", "El Dueño")
    encargos.marcar_dueno(con, 1)
    encargos.crear(con, "encargo-1", 77)
    con.commit()
    return con


@pytest.fixture
def maqueta_publicada(escena):
    sitio = constructor.sitio("encargo-1")
    sitio.mkdir(parents=True, exist_ok=True)
    (sitio / "index.html").write_text("<main>Citas de hoy</main>", encoding="utf-8")
    (sitio / "clientas.html").write_text("<main>Clientas</main>", encoding="utf-8")
    (sitio / "estilo.css").write_text(":root{}", encoding="utf-8")
    encargos.tocar(escena, "encargo-1", estado="publicado", url="https://encargo-1.test")
    escena.commit()
    return escena


def test_preparar_copia_la_maqueta_a_static_y_deja_el_arranque(maqueta_publicada):
    destino = implementador.preparar(maqueta_publicada, "encargo-1")

    assert (destino / "static" / "index.html").is_file()
    assert (destino / "static" / "clientas.html").is_file()
    assert (destino / "static" / "estilo.css").is_file()
    main = (destino / "main.py").read_text(encoding="utf-8")
    assert "DATOS" in main and "StaticFiles" in main and "/salud" in main
    contrato = (encargos.carpeta("encargo-1") / "INSTRUCCIONES-IMPLEMENTAR.md").read_text(encoding="utf-8")
    assert "localStorage" in contrato and "./encargo api" in contrato and "Nada de acceso" in contrato
    assert "curl" not in contrato
    # La maqueta sigue intacta: es la especificación.
    assert (constructor.sitio("encargo-1") / "index.html").is_file()


def test_preparar_no_pisa_lo_que_el_agente_ya_escribio(maqueta_publicada):
    destino = implementador.preparar(maqueta_publicada, "encargo-1")
    (destino / "main.py").write_text("# lo mío", encoding="utf-8")
    (destino / "static" / "index.html").write_text("<main>ya con fetch</main>", encoding="utf-8")

    implementador.preparar(maqueta_publicada, "encargo-1")

    assert (destino / "main.py").read_text(encoding="utf-8") == "# lo mío"
    assert "fetch" in (destino / "static" / "index.html").read_text(encoding="utf-8")


def test_sin_maqueta_no_hay_que_implementar(escena):
    encargos.tocar(escena, "encargo-1", estado="publicado")
    with pytest.raises(ValueError, match="no tiene maqueta"):
        implementador.preparar(escena, "encargo-1")


def test_empezar_solo_sobre_una_maqueta_publicada(escena, monkeypatch):
    monkeypatch.setattr(implementador, "abrir_agente", lambda c, e: {"pane_id": "%1"})
    for estado in ("recogiendo", "construyendo", "construido"):
        encargos.tocar(escena, "encargo-1", estado=estado)
        with pytest.raises(ValueError, match="no es una maqueta publicada"):
            implementador.empezar(escena, "encargo-1")


def test_empezar_cambia_la_etapa_cierra_agentes_y_abre_el_implementador(maqueta_publicada, monkeypatch):
    from hub import entrevistador

    pasos = []
    monkeypatch.setattr(entrevistador, "cerrar_agentes", lambda c, e: pasos.append("cerrar") or [])
    monkeypatch.setattr(implementador, "abrir_agente", lambda c, e: pasos.append("abrir") or {"pane_id": "%1"})

    implementador.empezar(maqueta_publicada, "encargo-1")

    fila = encargos.ver(maqueta_publicada, "encargo-1")
    assert fila["etapa"] == "sistema" and fila["estado"] == "aprobado" and fila["plan_msg"] is None
    assert pasos == ["cerrar", "abrir"]
    # Y no se puede empezar dos veces: ya no es maqueta.
    with pytest.raises(ValueError):
        implementador.empezar(maqueta_publicada, "encargo-1")


def test_abrir_el_implementador_exige_etapa_sistema(maqueta_publicada):
    with pytest.raises(ValueError, match="etapa maqueta"):
        implementador.abrir_agente(maqueta_publicada, "encargo-1")


def test_el_acceso_deja_el_hash_y_devuelve_la_contrasena_una_sola_vez(escena):
    import bcrypt

    assert not implementador.tiene_acceso("encargo-1")
    clave = implementador.generar_acceso("encargo-1")

    assert len(clave) >= 10
    hash_ = (encargos.carpeta("encargo-1") / implementador.ACCESO).read_text(encoding="utf-8").strip()
    assert hash_.startswith("$2") and clave not in hash_
    assert bcrypt.checkpw(clave.encode(), hash_.encode())
    assert implementador.tiene_acceso("encargo-1")
    # Regla dura 5: en ningún archivo del encargo queda la contraseña.
    for archivo in encargos.carpeta("encargo-1").rglob("*"):
        if archivo.is_file():
            assert clave not in archivo.read_text(encoding="utf-8", errors="replace")


def test_acotar_no_le_deja_sacar_archivos_ni_leer_el_hub(escena, tmp_path, monkeypatch):
    """`curl` lee cualquier archivo (`file:///…`, `-d @~/…`) y lo manda fuera,
    y acotarlo por prefijo no basta: acepta varias URL en una línea (C-0128).
    Su API la prueba con `./encargo api`."""
    monkeypatch.setenv("HOME", str(tmp_path))
    carpeta = encargos.carpeta("encargo-1")
    implementador.acotar(carpeta)
    reglas = json.loads((carpeta / ".claude" / "settings.json").read_text(encoding="utf-8"))["permissions"]
    assert not any(r.startswith(("Bash(curl", "Bash(wget")) for r in reglas["allow"])
    assert "Bash(curl:*)" in reglas["deny"]
    # La carpeta del hub, sea cual sea su nombre: con «"hub" in r» fallaba en
    # un clon que no se llamara así (lo vio la suite sobre una copia publicada).
    assert f"Read(//{str(config.RAIZ_REPO).lstrip('/')}/**)" in reglas["deny"]
    assert not any("bypass" in r for r in reglas["allow"])


def test_el_arranque_generado_sirve_de_verdad(maqueta_publicada, tmp_path, monkeypatch):
    """No es un texto: `main.py` tiene que importar y contestar /salud con la
    base en DATOS, porque es lo que el agente extiende y lo que la imagen corre."""
    import importlib.util
    import sys

    destino = implementador.preparar(maqueta_publicada, "encargo-1")
    monkeypatch.setenv("DATOS", str(tmp_path / "datos"))
    spec = importlib.util.spec_from_file_location("app_de_prueba", destino / "main.py")
    modulo = importlib.util.module_from_spec(spec)
    sys.modules["app_de_prueba"] = spec.loader and spec.loader.exec_module(modulo) or modulo

    from fastapi.testclient import TestClient

    cliente = TestClient(modulo.app)
    assert cliente.get("/salud").json() == {"ok": True}
    assert "Citas de hoy" in cliente.get("/").text
    assert (tmp_path / "datos" / "app.db").is_file()


@pytest.fixture
def app_en_local(escena):
    """Una app de mentira escuchando donde `servir` habría dejado la suya."""
    import http.server
    import os
    import socketserver
    import threading

    class Eco(http.server.BaseHTTPRequestHandler):
        def _contestar(self):
            largo = int(self.headers.get("Content-Length") or 0)
            cuerpo = json.dumps({"metodo": self.command, "ruta": self.path,
                                 "cuerpo": self.rfile.read(largo).decode()}).encode()
            self.send_response(201 if self.command == "POST" else 200)
            self.end_headers()
            self.wfile.write(cuerpo)

        do_GET = do_POST = do_DELETE = _contestar

        def log_message(self, *a):
            pass

    # Como la de verdad (C-0145): escucha en un socket Unix, no en un puerto.
    class PorSocket(socketserver.ThreadingUnixStreamServer):
        daemon_threads = True

    class EcoUnix(Eco):
        def address_string(self):
            return "app"

    import tempfile
    # Corto: un socket Unix no admite rutas de más de 108 caracteres.
    enchufe = Path(tempfile.mkdtemp(prefix="enc-")) / "app.sock"
    servidor = PorSocket(str(enchufe), EcoUnix)
    threading.Thread(target=servidor.serve_forever, daemon=True).start()
    estado = encargos_cli._estado_servir("encargo-1")
    estado.parent.mkdir(parents=True, exist_ok=True)
    estado.write_text(json.dumps({"huella": procesos.huella(os.getpid()), "socket": str(enchufe)}))
    yield escena
    servidor.shutdown()


def _api(con, *argv):
    args = encargos_cli.construir_parser().parse_args(["--encargo", "encargo-1", "api", *argv])
    return encargos_cli.cmd_api(con, args)


def test_encargo_api_llega_a_su_app_en_local(app_en_local, capsys):
    assert _api(app_en_local, "post", "/api/citas", '{"hora": "10:00"}') == 0
    salida = capsys.readouterr().out
    assert salida.startswith("201") and '"ruta": "/api/citas"' in salida and "10:00" in salida


@pytest.mark.parametrize("ruta", ["http://ejemplo.com/x", "//ejemplo.com/x", "file:///etc/passwd", "api/citas",
                                  "/api x", "/api\r\nHost: fuera"])
def test_encargo_api_no_va_a_ningun_otro_sitio(app_en_local, capsys, ruta):
    _api(app_en_local, "GET", ruta)
    assert not capsys.readouterr().out.startswith("200")


def test_encargo_api_sin_app_corriendo_lo_dice(escena, capsys):
    _api(escena, "GET", "/api/citas")
    assert "./encargo servir" in capsys.readouterr().err


def test_el_puerto_de_la_app_no_lo_puede_tocar_el_agente(app_en_local):
    """El agente edita su carpeta entera (`acotar`). Si el puerto viviera ahí,
    cambiarlo a 8787 llevaba `./encargo api` al hub, desde loopback y sin
    `Origin`: todos sus POST (revisor de C-0128)."""
    carpeta = encargos.carpeta("encargo-1")
    estado = encargos_cli._estado_servir("encargo-1")
    assert carpeta.resolve() not in estado.resolve().parents
    implementador.acotar(carpeta)
    reglas = json.loads((carpeta / ".claude" / "settings.json").read_text(encoding="utf-8"))["permissions"]
    suya = "//" + str(carpeta).lstrip("/") + "/**"
    assert [r for r in reglas["allow"] if r.startswith(("Edit(", "Write("))] == [f"Edit({suya})"]


@pytest.mark.parametrize("url", ["http://127.0.0.1@fuera.example/?d=x", "http://localhost.fuera.example/",
                                 "https://127.0.0.1/", "file:///etc/passwd", "//fuera.example/"])
def test_mirar_solo_mira_su_app_en_local(app_en_local, capsys, url):
    args = encargos_cli.construir_parser().parse_args(["--encargo", "encargo-1", "mirar", url])
    assert encargos_cli.cmd_mirar(app_en_local, args) != 0
    assert "sólo se mira tu app" in capsys.readouterr().err


def test_mirar_va_a_su_app_aunque_pida_el_puerto_del_hub(app_en_local, monkeypatch):
    """De la URL sólo cuenta la ruta: el destino es su app, fotografiada con el
    navegador encerrado (C-0145). Pedir el 8787 ya no llega al hub."""
    vistos = []
    monkeypatch.setattr(encargos_cli.encierro, "fotografiar",
                        lambda enchufe, camino, destino, **kw: vistos.append((enchufe, camino)) or destino)
    args = encargos_cli.construir_parser().parse_args(["--encargo", "encargo-1", "mirar", "http://127.0.0.1:8787/citas?x=1"])
    assert encargos_cli.cmd_mirar(app_en_local, args) == 0
    servidor = encargos_cli._servidor("encargo-1")
    assert vistos and all(e == servidor["socket"] and c == "/citas?x=1" for e, c in vistos)
