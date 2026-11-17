"""Lo que la pantalla «Claude» dice de Claude sale de los archivos que de verdad usa."""

import asyncio
import json

from fastapi.testclient import TestClient

from puente_kvm import repertorio, terminal
from puente_kvm.app import crear_app
from puente_kvm.simulador import Simulador

ESPERADAS = {"leer-documento", "explicar-funcion", "revisar-rendimiento", "consultar-catalogo",
             "proponer-cambio", "primera-conexion"}


def test_cada_skill_tiene_nombre_igual_a_su_carpeta_descripcion_y_acceso():
    skills = repertorio.skills()
    assert {s["nombre"] for s in skills} == ESPERADAS
    for s in skills:
        assert s["ruta"] == f".claude/skills/{s['nombre']}/SKILL.md"
        assert len(s["descripcion"]) > 40, s["nombre"]
        assert s["acceso"], f"{s['nombre']} no dice qué acceso necesita"


def test_toda_herramienta_del_puente_tiene_un_permiso_decidido():
    # Una herramienta nueva sin regla preguntaría siempre sin que nadie lo haya decidido.
    reglas = json.loads(repertorio.AJUSTES_CLAUDE.read_text())["permissions"]
    decididas = {r.removeprefix("mcp__puente-kvm__") for clave in ("allow", "ask", "deny")
                 for r in reglas[clave] if r.startswith("mcp__puente-kvm__")}
    nombres = {h["nombre"] for h in asyncio.run(repertorio.herramientas())}
    assert nombres == decididas


def test_teclear_y_hacer_clic_preguntan_y_curl_esta_prohibido():
    p = {k: {r["regla"] for r in v} for k, v in repertorio.permisos().items()}
    for t in ("teclear", "atajo", "clic", "rueda", "ir_a_linea"):
        assert f"mcp__puente-kvm__{t}" in p["ask"]
    assert "Bash(curl:*)" in p["deny"]  # que no se salte las puertas del puente por la API


def test_claude_arranca_con_el_modo_de_permisos_explicito(monkeypatch):
    monkeypatch.delenv("PUENTE_TERMINAL_ORDEN", raising=False)
    assert "--permission-mode default" in terminal.orden_claude()


def test_la_actividad_guarda_el_resumen_nunca_el_contenido():
    a = repertorio.Actividad()
    a.registrar({"hook_event_name": "UserPromptSubmit", "prompt": "revisa usp_Secreta"})
    a.registrar({"hook_event_name": "PreToolUse", "tool_name": "Skill", "tool_input": {"skill": "revisar-rendimiento"}})
    a.registrar({"hook_event_name": "PreToolUse", "tool_name": "Write",
                 "tool_input": {"file_path": str(repertorio.PROYECTO / "trabajo/x.sql"), "content": "SELECT secreto"}})
    assert a.publico()["skill"] == "revisar-rendimiento"
    assert a.publico()["estado"] == "trabajando"
    volcado = json.dumps(list(a.eventos), ensure_ascii=False)
    assert "secreto" not in volcado.lower() and "usp_Secreta" not in volcado
    assert "escribe trabajo/x.sql" in volcado
    a.registrar({"hook_event_name": "Stop"})
    assert a.publico()["estado"] == "esperando"


def test_los_hooks_llegan_al_puente_y_la_pantalla_claude_se_sirve():
    with TestClient(crear_app(Simulador(lineas=["x"]), hosts={"testserver"})) as c:
        r = c.post("/api/claude/actividad", json={"hook_event_name": "PreToolUse",
                                                  "tool_name": "mcp__puente-kvm__ver_pagina"})
        assert r.status_code == 200
        assert c.get("/api/estado").json()["claude"]["herramienta"] == "puente: ver_pagina"
        pagina = c.get("/claude")
        assert pagina.status_code == 200 and "/revisar-rendimiento" in pagina.text


def reglas() -> dict[str, list[str]]:
    return json.loads(repertorio.AJUSTES_CLAUDE.read_text())["permissions"]


def test_leer_sin_preguntar_esta_acotado_al_proyecto_y_a_los_datos_del_puente():
    # Un `Read` sin acotar deja leer cualquier archivo del equipo sin preguntar.
    permitidas = reglas()["allow"]
    for suelta in ("Read", "Glob", "Grep", "Edit", "Write", "Bash"):
        assert suelta not in permitidas
    for r in permitidas:
        if r.startswith(("Read(", "Edit(")):
            # «/x» es relativo a la carpeta del proyecto; «~/x», a la casa; «//x», absoluto.
            dentro = r.split("(", 1)[1].removesuffix(")")
            assert dentro.startswith("/") and not dentro.startswith("//") or \
                dentro == "~/.local/share/puente-kvm/**", r


def test_la_carpeta_de_la_contrasena_esta_prohibida_y_la_pantalla_lo_dice():
    prohibidas = reglas()["deny"]
    assert "Read(~/.config/puente-kvm/**)" in prohibidas
    assert "Edit(~/.config/puente-kvm/**)" in prohibidas
    textos = [r["texto"] for r in repertorio.permisos()["deny"]]
    assert any("contraseña" in t and "~/.config/puente-kvm" in t for t in textos)
    leer = [r["texto"] for r in repertorio.permisos()["allow"] if r["regla"].startswith("Read(")]
    assert any("esta carpeta" in t for t in leer) and any("datos del puente" in t for t in leer)


def test_los_hooks_avisan_al_puerto_que_diga_puente_puerto():
    import shlex
    import subprocess
    import threading

    import uvicorn

    hooks = json.loads(repertorio.AJUSTES_CLAUDE.read_text())["hooks"]
    ordenes = {h["hooks"][0]["command"] for evento in hooks.values() for h in evento}
    assert len(ordenes) == 1
    orden = ordenes.pop()
    assert "8794" not in orden.replace("${PUENTE_PUERTO:-8794}", "")

    from .conftest import puerto_libre

    puerto = puerto_libre()
    servidor = uvicorn.Server(uvicorn.Config(crear_app(Simulador(lineas=["x"]), hosts={f"127.0.0.1:{puerto}"}),
                                             host="127.0.0.1", port=puerto, log_level="error"))
    hilo = threading.Thread(target=servidor.run, daemon=True)
    hilo.start()
    try:
        import time
        import httpx
        for _ in range(50):
            try:
                httpx.get(f"http://127.0.0.1:{puerto}/api/estado", timeout=1)
                break
            except httpx.HTTPError:
                time.sleep(0.1)
        evento = json.dumps({"hook_event_name": "PreToolUse", "tool_name": "mcp__puente-kvm__estado"})
        subprocess.run(["sh", "-c", orden], input=evento, text=True, env={"PATH": "/usr/bin:/bin",
                       "PUENTE_PUERTO": str(puerto)}, timeout=10, check=True)
        e = httpx.get(f"http://127.0.0.1:{puerto}/api/estado", timeout=2).json()
        assert e["claude"]["herramienta"] == "puente: estado"
    finally:
        servidor.should_exit = True
        hilo.join(5)
