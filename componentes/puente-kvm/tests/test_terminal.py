"""La terminal de Claude Code dentro del puente: tmux de verdad, en un servidor aparte.

Las pruebas no tocan el tmux del usuario: `PUENTE_TMUX_SOCKET` las lleva a un
servidor propio, y dentro corre una bash en vez de Claude.
"""

import json
import shlex
import subprocess
import time
import uuid

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from puente_kvm.app import crear_app
from puente_kvm.simulador import Simulador

PERSONA = {"Origin": "http://testserver"}


@pytest.fixture
def cliente(monkeypatch, tmp_path):
    socket = f"puente-pruebas-{uuid.uuid4().hex[:6]}"
    monkeypatch.setenv("PUENTE_TMUX_SOCKET", socket)
    monkeypatch.setenv("PUENTE_TERMINAL_ORDEN", "exec bash --norc --noprofile")
    monkeypatch.setenv("JETKVM_CLAVE", "secreto-de-prueba")
    with TestClient(crear_app(Simulador(lineas=["x"]), hosts={"testserver"})) as c:
        yield c, tmp_path
    subprocess.run(["tmux", "-L", socket, "kill-server"], capture_output=True)


def leer_hasta(ws, texto: str, tope: float = 10) -> str:
    visto = ""
    fin = time.time() + tope
    while texto not in visto:
        assert time.time() < fin, f"no llegó {texto!r}; llegó {visto[-300:]!r}"
        visto += ws.receive_bytes().decode(errors="replace")
    return visto


def test_lo_que_se_teclea_llega_a_la_sesion_y_su_salida_vuelve(cliente):
    c, _ = cliente
    with c.websocket_connect("/ws/terminal", headers=PERSONA) as ws:
        ws.send_text('{"filas": 30, "columnas": 100}')
        ws.send_bytes(b"echo hola-$((40+2))\r")
        leer_hasta(ws, "hola-42")


def test_la_sesion_sigue_viva_al_cerrar_la_pestana_y_se_vuelve_a_enganchar(cliente):
    c, _ = cliente
    with c.websocket_connect("/ws/terminal", headers=PERSONA) as ws:
        ws.send_bytes(b"export MARCA=sigo-aqui\r")
        time.sleep(0.3)
    with c.websocket_connect("/ws/terminal", headers=PERSONA) as ws:
        ws.send_bytes(b"echo $MARCA-$((1+1))\r")
        leer_hasta(ws, "sigo-aqui-2")


def test_un_pegado_largo_llega_entero(cliente):
    c, tmp = cliente
    destino = tmp / "pegado.txt"
    linea = "x" * 99
    with c.websocket_connect("/ws/terminal", headers=PERSONA) as ws:
        ws.send_bytes(f"stty -echo; cat > {destino}\r".encode())
        time.sleep(0.5)
        ws.send_bytes(("\r".join([linea] * 300) + "\r").encode())  # 30.000 bytes de una vez
        fin = time.time() + 15
        while (not destino.exists() or destino.stat().st_size < 300 * 100) and time.time() < fin:
            time.sleep(0.1)
        ws.send_bytes(b"\x04")
    assert destino.stat().st_size == 300 * 100


def test_otra_web_no_puede_abrir_la_terminal(cliente):
    c, _ = cliente
    with pytest.raises(WebSocketDisconnect):
        with c.websocket_connect("/ws/terminal", headers={"Origin": "http://malo.example"}) as ws:
            ws.receive_bytes()
    with pytest.raises(WebSocketDisconnect):
        with c.websocket_connect("/ws/terminal") as ws:  # sin Origin: no es un navegador de esta web
            ws.receive_bytes()


def test_un_nombre_de_host_ajeno_no_entra_aunque_origen_y_host_coincidan():
    # DNS rebinding: la web maliciosa manda su Host y su Origin, que coinciden entre sí.
    with TestClient(crear_app(Simulador(lineas=["x"]), hosts={"127.0.0.1:8794"}),
                    base_url="http://malo.example:8794") as c:
        r = c.post("/api/control", json={"accion": "dar"}, headers={"Origin": "http://malo.example:8794"})
        assert r.status_code == 403
        assert c.get("/api/estado").status_code == 403


def test_cambiar_el_tamano_de_la_pestana_cambia_el_de_la_sesion(cliente):
    # Si tmux no se entera, cree tener otras columnas y las letras del borde se pierden
    # (medido en otra terminal web). Sin barra de estado de tmux, todas las filas son de la sesión.
    c, _ = cliente
    with c.websocket_connect("/ws/terminal", headers=PERSONA) as ws:
        ws.send_text('{"filas": 33, "columnas": 111}')
        time.sleep(0.5)
        ws.send_bytes(b"echo tam-$(stty size | tr ' ' x)\r")
        leer_hasta(ws, "tam-33x111")


def test_la_contrasena_del_jetkvm_no_llega_a_la_sesion_de_claude(monkeypatch, cliente):
    # El servicio la tiene en su entorno para conectar; Claude no la necesita y
    # con ella en el entorno bastaría un `echo` para leerla.
    c, _ = cliente
    with c.websocket_connect("/ws/terminal", headers=PERSONA) as ws:
        ws.send_bytes(b'echo "clave:[$JETKVM_CLAVE]-$((2+3))"\r')
        visto = leer_hasta(ws, "]-5")
    assert "clave:[]-5" in visto
    assert "secreto-de-prueba" not in visto


def test_la_sesion_sabe_donde_esta_el_codigo_y_el_puerto_del_puente(cliente):
    # Se compara en la propia shell: una ruta larga se parte en el borde del
    # panel y tmux la repinta con secuencias de control entre medias.
    c, _ = cliente
    from puente_kvm import config
    with c.websocket_connect("/ws/terminal", headers=PERSONA) as ws:
        ws.send_bytes((f'test "$PUENTE_CODIGO" = {shlex.quote(str(config.CODIGO))} && '
                       f'test "$PUENTE_PUERTO" = {config.PUERTO} && echo "si-$((40+2))"\r').encode())
        leer_hasta(ws, "si-42")


def test_con_un_espacio_de_trabajo_aparte_claude_arranca_alli_con_lo_que_necesita(monkeypatch, tmp_path):
    from puente_kvm import config
    espacio = tmp_path / "espacio"
    socket = f"puente-pruebas-{uuid.uuid4().hex[:6]}"
    monkeypatch.setenv("PUENTE_TRABAJO", str(espacio))
    monkeypatch.setenv("PUENTE_TMUX_SOCKET", socket)
    monkeypatch.setenv("PUENTE_TERMINAL_ORDEN", "exec bash --norc --noprofile")
    try:
        with TestClient(crear_app(Simulador(lineas=["x"]), hosts={"testserver"})) as c:
            with c.websocket_connect("/ws/terminal", headers=PERSONA) as ws:
                ws.send_bytes(f'test "$(pwd -P)" = {shlex.quote(str(espacio.resolve()))} && echo "si-$((2+2))"\r'
                              .encode())
                leer_hasta(ws, "si-4")
        assert (espacio / "trabajo").is_dir()
        assert (espacio / "CLAUDE.md").resolve() == config.CODIGO / "CLAUDE.md"
        assert (espacio / ".claude" / "skills").resolve() == config.CODIGO / ".claude" / "skills"
        assert (espacio / ".claude" / "settings.json").resolve() == config.CODIGO / ".claude" / "settings.json"
        mcp = json.loads((espacio / ".mcp.json").read_text())["mcpServers"]["puente-kvm"]
        assert str(config.CODIGO) in mcp["args"]
    finally:
        subprocess.run(["tmux", "-L", socket, "kill-server"], capture_output=True)


def test_el_espacio_aparte_es_un_repositorio_que_no_guarda_nada(tmp_path, monkeypatch):
    # Medido con Claude Code 2.1.322: fuera de un repositorio git no aplica los
    # ajustes del proyecto (las herramientas del puente quedan «pendientes de
    # aprobar»). Dentro sí. Y lo traído del Mac no puede acabar en un commit.
    from puente_kvm import espacio
    destino = tmp_path / "espacio"
    monkeypatch.setenv("PUENTE_TRABAJO", str(destino))
    assert espacio.preparar() == []
    (destino / "trabajo" / "usp_x.sql").write_text("SELECT 1;\n")
    r = subprocess.run(["git", "-C", str(destino), "status", "--porcelain", "--ignored=no"], capture_output=True,
                       text=True, check=True)
    assert r.stdout == ""
    assert (destino / ".git" / "info" / "exclude").read_text().strip().endswith("*")
    assert espacio.preparar() == []  # dos veces, igual


def test_el_claude_de_la_persona_gana_al_del_sistema(monkeypatch, tmp_path):
    """Bajo systemd el PATH trae primero las carpetas del sistema: si ahí hay un
    Claude Code viejo, no puede ganarle al que la persona mantiene al día."""
    from puente_kvm import terminal

    casa, sistema = tmp_path / "casa", tmp_path / "usr-bin"
    propio = casa / ".npm-global" / "bin"
    for carpeta in (propio, sistema):
        carpeta.mkdir(parents=True)
        (carpeta / "claude").write_text("#!/bin/sh\n")
        (carpeta / "claude").chmod(0o755)
    monkeypatch.setenv("HOME", str(casa))
    monkeypatch.setenv("PATH", f"{sistema}:/usr/bin:/bin")
    monkeypatch.delenv("PUENTE_TERMINAL_ORDEN", raising=False)

    assert terminal._path_de_usuario().split(":")[:3] == [
        str(casa / ".local/bin"), str(propio), str(casa / ".claude/local")]
    # La orden empieza poniendo el PATH del puente (bash -l lo reescribe) y llama a ése.
    assert f" ; {propio}/claude --permission-mode" in terminal.orden_claude()


@pytest.fixture
def sin_setsid(monkeypatch):
    """El Python de uv no trae setsid en posix_spawn (Ubuntu 22.04)."""
    import os

    original = os.posix_spawn

    def falso(*args, **kwargs):
        if kwargs.get("setsid"):
            raise NotImplementedError("posix_spawn: setsid unavailable on this platform")
        return original(*args, **kwargs)

    monkeypatch.setattr(os, "posix_spawn", falso)


def test_sin_setsid_en_posix_spawn_la_terminal_abre_y_sigue_el_tamano(sin_setsid, cliente):
    # La terminal no abría. Por `setsid --ctty` el PTY sigue siendo su terminal
    # de control, y cambiar el tamaño llega a tmux.
    c, _ = cliente
    with c.websocket_connect("/ws/terminal", headers=PERSONA) as ws:
        ws.send_text('{"filas": 31, "columnas": 107}')
        time.sleep(0.5)
        ws.send_bytes(b"echo tam-$(stty size | tr ' ' x)\r")
        leer_hasta(ws, "tam-31x107")


def test_lo_tecleado_nada_mas_abrir_no_se_pierde(sin_setsid, cliente):
    # tmux descarta lo pendiente al poner su terminal en crudo; con un exec más
    # (setsid) el primer «echo» llegaba antes y se perdía (22.04).
    c, _ = cliente
    with c.websocket_connect("/ws/terminal", headers=PERSONA) as ws:
        ws.send_bytes(b"echo pronto-$((20+3))\r")
        leer_hasta(ws, "pronto-23")
