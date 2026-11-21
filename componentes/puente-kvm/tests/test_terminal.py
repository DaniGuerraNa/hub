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


def test_ninguna_prueba_ve_el_tmux_de_quien_las_corre():
    """Las páginas de prueba se enganchan a la conversación de Claude al cargar:
    con el servidor de tmux de siempre, era la de verdad del puente de quien
    corre las pruebas (y si no había, abrían un `claude` real). Cada prueba va
    a un servidor suyo con una bash dentro, salvo las que ponen el suyo."""
    import os

    from puente_kvm import terminal
    socket = os.environ.get("PUENTE_TMUX_SOCKET", "")
    assert socket.startswith("puente-pruebas-")
    assert terminal.tmux()[-2:] == ["-L", socket]
    assert os.environ.get("PUENTE_TERMINAL_ORDEN") == "exec bash --norc --noprofile"
    assert not terminal.existe()  # en uno nuevo no hay ninguna `puente-claude`


# ── la sesión, aislada de la configuración de quien la abre (C-0471) ────────
def _ajustes_de_usuario(tmp_path, datos: dict) -> None:
    import os
    carpeta = tmp_path / "claude-de-la-persona"
    carpeta.mkdir(exist_ok=True)
    (carpeta / "settings.json").write_text(json.dumps(datos))
    assert os.environ["CLAUDE_CONFIG_DIR"] == str(carpeta)  # la de conftest, nunca la de verdad


@pytest.mark.parametrize("saltar", [False, True])
def test_los_dos_modos_cargan_el_proyecto_y_solo_el_servidor_del_puente(monkeypatch, saltar):
    # Sin la fuente «project», «Sin pedir permisos» arrancaba sin las skills del
    # puente; sin --strict-mcp-config, cada sesión cargaba los conectores de quien la abre.
    from puente_kvm import config, terminal
    monkeypatch.delenv("PUENTE_TERMINAL_ORDEN", raising=False)
    monkeypatch.setattr(terminal, "saltar_permisos", lambda: saltar)
    orden = terminal.orden_claude()
    assert "--setting-sources project,local" in orden
    assert "--strict-mcp-config" in orden
    assert f"--mcp-config {shlex.quote(str(config.espacio() / '.mcp.json'))}" in orden
    assert f"--settings {shlex.quote(str(config.hogar() / 'claude-sesion.json'))}" in orden


def test_el_json_de_la_sesion_lleva_lo_de_la_persona_y_nunca_llaves_hooks_plugins_ni_control_remoto(tmp_path):
    from puente_kvm import terminal
    _ajustes_de_usuario(tmp_path, {
        "model": "opus", "effortLevel": "high", "modelSettings": {"claude-sonnet-5": {"effortLevel": "high"}},
        "tui": "fullscreen", "statusLine": {"type": "command", "command": "mi-barra.sh"},
        "agentPushNotifEnabled": True, "inputNeededNotifEnabled": True, "taskCompleteNotifEnabled": False,
        "remoteControlAtStartup": True, "enabledPlugins": {"algo@ajeno": True}, "syncClaudeAiSkills": True,
        "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "otro.sh"}]}]},
        "mcpServers": {"ajeno": {"command": "x"}}, "autoMode": {"environment": ["x"]},
        "permissions": {"allow": ["Bash"], "deny": ["Read(~/secretos/**)"], "defaultMode": "bypassPermissions"},
    })
    for saltar in (False, True):
        fuentes, ruta = terminal.ajustes_de_sesion(saltar)
        datos = json.loads(ruta.read_text())
        assert fuentes == "project,local"
        assert set(datos) - {"permissions"} == {*terminal.DE_LA_PERSONA, *terminal.SIEMPRE}
        assert datos["statusLine"]["command"] == "mi-barra.sh" and datos["model"] == "opus"
        assert datos["taskCompleteNotifEnabled"] is False and datos["inputNeededNotifEnabled"] is True
        # Su «true» no pasa: el control remoto es otro camino para manejar la
        # sesión, y las skills sincronizadas de claude.ai cuestan en cada llamada.
        assert datos["remoteControlAtStartup"] is False
        assert datos["syncClaudeAiSkills"] is False and datos["syncClaudeAiPlugins"] is False
        assert set(datos["permissions"]) <= {"ask", "deny"}
        assert datos["permissions"]["deny"] == ["Read(~/secretos/**)"]


def test_con_autenticacion_en_los_ajustes_de_usuario_se_carga_tambien_su_fuente_sin_copiar_la_llave(tmp_path):
    # Sin la fuente «user», Claude Code no sabría autenticarse; y la llave no se
    # copia a PUENTE_HOME.
    from puente_kvm import terminal
    for llave in terminal.AUTENTICACION:
        _ajustes_de_usuario(tmp_path, {llave: {"ANTHROPIC_API_KEY": "sk-falsa"} if llave == "env" else "dame-la.sh"})
        fuentes, ruta = terminal.ajustes_de_sesion(saltar=False)
        assert fuentes == "user,project,local", llave
        texto = ruta.read_text()
        assert llave not in json.loads(texto) and "sk-falsa" not in texto and "dame-la" not in texto
        # Con la fuente «user» cargada llegaría el suyo: `--settings` le gana.
        assert json.loads(texto)["remoteControlAtStartup"] is False


def test_las_reglas_ask_van_solo_en_el_modo_normal():
    from puente_kvm import repertorio, terminal
    _, ruta = terminal.ajustes_de_sesion(saltar=False)
    preguntas = json.loads(ruta.read_text())["permissions"]["ask"]
    assert len(preguntas) == len(repertorio.reglas()["ask"]) and "mcp__puente-kvm__clic" in preguntas
    _, ruta = terminal.ajustes_de_sesion(saltar=True)
    assert "permissions" not in json.loads(ruta.read_text())


def test_las_rutas_de_las_reglas_siguen_apuntando_a_su_carpeta_desde_puente_home(tmp_path, monkeypatch):
    # Medido con la 2.1.322: en un archivo de --settings, «/x» es relativo a la
    # carpeta de ESE archivo; «Edit(/src/**)» habría pasado a ser PUENTE_HOME/src.
    from puente_kvm import config, terminal
    espacio = tmp_path / "espacio"
    monkeypatch.setenv("PUENTE_TRABAJO", str(espacio))
    _ajustes_de_usuario(tmp_path, {"permissions": {"deny": ["Read(/secretos/**)", "Bash(curl:*)", "Read(~/x/**)"]}})
    _, ruta = terminal.ajustes_de_sesion(saltar=False)
    permisos = json.loads(ruta.read_text())["permissions"]
    assert f"Edit(/{config.espacio().as_posix()}/src/**)" in permisos["ask"]
    assert "WebFetch" in permisos["ask"] and "mcp__puente-kvm__teclear" in permisos["ask"]
    usuario = tmp_path / "claude-de-la-persona"
    assert permisos["deny"] == [f"Read(/{usuario.as_posix()}/secretos/**)", "Bash(curl:*)", "Read(~/x/**)"]


def test_el_aviso_del_modo_sin_permisos_solo_se_salta_si_la_persona_ya_lo_acepto(tmp_path):
    from puente_kvm import terminal
    _, ruta = terminal.ajustes_de_sesion(saltar=True)
    assert "skipDangerousModePermissionPrompt" not in json.loads(ruta.read_text())
    _ajustes_de_usuario(tmp_path, {"skipDangerousModePermissionPrompt": True})
    _, ruta = terminal.ajustes_de_sesion(saltar=True)
    assert json.loads(ruta.read_text())["skipDangerousModePermissionPrompt"] is True
    _, ruta = terminal.ajustes_de_sesion(saltar=False)  # en el modo normal no hay aviso que saltar
    assert "skipDangerousModePermissionPrompt" not in json.loads(ruta.read_text())


def test_unos_ajustes_de_usuario_ilegibles_no_impiden_abrir_la_sesion(tmp_path):
    from puente_kvm import terminal
    carpeta = tmp_path / "claude-de-la-persona"
    carpeta.mkdir()
    (carpeta / "settings.json").write_text("{ esto no es json")
    fuentes, ruta = terminal.ajustes_de_sesion(saltar=False)
    assert fuentes == "project,local" and set(json.loads(ruta.read_text())) == {"permissions", *terminal.SIEMPRE}


def test_un_env_vacio_no_cuenta_como_autenticacion_y_uno_con_algo_si(tmp_path):
    # No se sabe si un `env` lleva una llave, un proxy o la dirección de la API:
    # con algo dentro, la fuente «user» vuelve; vacío no dice nada de autenticarse.
    from puente_kvm import terminal
    _ajustes_de_usuario(tmp_path, {"env": {}, "apiKeyHelper": ""})
    fuentes, ruta = terminal.ajustes_de_sesion(saltar=False)
    assert fuentes == "project,local"
    _ajustes_de_usuario(tmp_path, {"env": {"HTTPS_PROXY": "http://proxy.ejemplo:3128"}})
    fuentes, ruta = terminal.ajustes_de_sesion(saltar=False)
    assert fuentes == "user,project,local"
    datos = json.loads(ruta.read_text())
    assert datos["remoteControlAtStartup"] is False and "env" not in datos and "proxy" not in ruta.read_text()


def test_las_ask_de_la_persona_tambien_preguntan_en_el_modo_normal_ancladas_a_su_carpeta(tmp_path):
    # Sin la fuente «user», sus «pregúntame» se perdían sin decirlo; en el modo
    # sin permisos no van, como las del puente (una «ask» gana a ese modo).
    from puente_kvm import repertorio, terminal
    _ajustes_de_usuario(tmp_path, {"permissions": {"ask": ["Bash(git push:*)", "Edit(/notas/**)"],
                                                   "deny": ["Read(~/x/**)"]}})
    usuario = tmp_path / "claude-de-la-persona"
    _, ruta = terminal.ajustes_de_sesion(saltar=False)
    preguntas = json.loads(ruta.read_text())["permissions"]["ask"]
    assert preguntas[-2:] == ["Bash(git push:*)", f"Edit(/{usuario.as_posix()}/notas/**)"]
    assert len(preguntas) == len(repertorio.reglas()["ask"]) + 2
    _, ruta = terminal.ajustes_de_sesion(saltar=True)
    assert json.loads(ruta.read_text())["permissions"] == {"deny": ["Read(~/x/**)"]}


def test_los_archivos_de_la_sesion_solo_los_lee_quien_corre_el_puente(monkeypatch):
    # Llevan lo que la persona tiene prohibido (sus rutas) y la orden de su barra
    # de estado; uno que ya existiera con otros permisos no los conserva.
    import os
    import stat

    from puente_kvm import config, terminal
    monkeypatch.delenv("PUENTE_TERMINAL_ORDEN")
    for nombre in ("claude-sesion.json", "claude-despues.bashrc"):
        (config.hogar() / nombre).write_text("{}")
        os.chmod(config.hogar() / nombre, 0o644)
    terminal.orden_claude()
    for nombre in ("claude-sesion.json", "claude-despues.bashrc"):
        assert stat.S_IMODE((config.hogar() / nombre).stat().st_mode) == 0o600, nombre
    assert not [p.name for p in config.hogar().iterdir() if p.name.endswith(".tmp")]


@pytest.mark.parametrize("saltar", [False, True])
def test_al_cerrarse_claude_la_shell_de_despues_lo_vuelve_a_abrir_aislado_y_en_el_mismo_modo(monkeypatch, tmp_path,
                                                                                             saltar):
    # 🔴 Con un `exec bash` a secas, un `claude` escrito ahí cargaba los ajustes
    # de usuario (con sus `allow`) y el .mcp.json del espacio sin ninguna «ask»:
    # las herramientas del puente sin preguntar nada. Se ejecuta de verdad: su
    # ~/.bashrc carga, y un alias suyo no le gana a la función.
    import os

    from puente_kvm import conversaciones, terminal
    casa = tmp_path / "casa"
    (casa / ".local" / "bin").mkdir(parents=True)
    falso = casa / ".local" / "bin" / "claude"
    falso.write_text('#!/bin/sh\nprintf "%s\\n" "$@" > "$SALIDA"\n')
    falso.chmod(0o755)
    (casa / ".bashrc").write_text("export DE_SU_BASHRC=si\nalias claude='echo el-alias-de-la-persona'\n")
    monkeypatch.setenv("HOME", str(casa))
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    monkeypatch.delenv("PUENTE_TERMINAL_ORDEN")
    monkeypatch.setattr(terminal, "saltar_permisos", lambda: saltar)
    conv = conversaciones.nueva("la del puente", terminal.modelo_elegido())

    orden = terminal.orden_claude(conv)
    lanzada = shlex.split(orden.split(" ; ")[1])  # «<claude> <banderas> --session-id U -n nombre»
    banderas = lanzada[1:lanzada.index("--session-id")]
    despues = shlex.split(orden.rsplit(" ; ", 1)[1])
    assert despues[:3] == ["exec", "bash", "--rcfile"]
    salida = tmp_path / "argumentos.txt"
    r = subprocess.run(["bash", "--rcfile", despues[3], "-i"], input="echo bashrc-$DE_SU_BASHRC\nclaude --continue\n",
                       capture_output=True, text=True, timeout=20, env={**os.environ, "SALIDA": str(salida)})
    assert "bashrc-si" in r.stdout and "el-alias-de-la-persona" not in r.stdout
    assert salida.read_text().splitlines() == [*banderas, "--continue"]
    assert ("--dangerously-skip-permissions" in banderas) is saltar
    for bandera in ("--setting-sources", "--settings", "--strict-mcp-config", "--mcp-config", "--model"):
        assert bandera in banderas, bandera
    # Lo primero que se le dice es el botón: retoma ESTA conversación, la de la lista.
    assert "el menú de la conversación, arriba de la terminal → Reabrir" in orden


def test_si_no_se_puede_preparar_la_orden_abrir_falla_y_la_conversacion_de_antes_sigue(monkeypatch, tmp_path):
    # `abrir` cerraba antes de preparar la orden, que lee los permisos del puente
    # y escribe en PUENTE_HOME: un preguntar.json roto dejaba a la persona sin ninguna.
    from puente_kvm import conversaciones, repertorio, terminal
    primera = conversaciones.nueva("primera", terminal.modelo_elegido())
    terminal.abrir(primera, retomar=False)  # con la bash de conftest
    assert terminal.existe()
    roto = tmp_path / "preguntar.json"
    roto.write_text("{ esto no es json")
    monkeypatch.setattr(repertorio, "PREGUNTAR", roto)
    monkeypatch.delenv("PUENTE_TERMINAL_ORDEN")
    monkeypatch.setattr(terminal, "saltar_permisos", lambda: False)
    monkeypatch.setattr(terminal, "comprobar_claude", lambda modelo: {"ruta": None, "version": None})
    segunda = conversaciones.nueva("segunda", terminal.modelo_elegido())
    with pytest.raises(ValueError, match="permisos de Claude del puente"):
        terminal.abrir(segunda, retomar=False)
    assert terminal.existe()
    assert conversaciones.actual().id == primera.id
