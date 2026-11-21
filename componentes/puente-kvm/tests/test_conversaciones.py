"""Varias conversaciones con Claude Code, una viva a la vez, y el modelo elegido.

Lo medido con Claude Code 2.1.322 (sin mandar mensajes al modelo):
- `--session-id <uuid> -n <nombre>` abre una conversación con ese id y ese nombre;
- mientras no se escribe nada, no se guarda nada: `--resume` de ese id dice
  «No conversation found with session ID» y sale con 1 en el acto;
- `--session-id` de un id ya usado sale con 1 («already in use»);
- `--resume <uuid> -n <nombre>` la retoma y le pone ese nombre;
- un modelo desconocido no se rechaza al arrancar (sólo avisa).
Por eso retomar es `claude --resume U … || claude --session-id U …`: si nunca se
escribió, arranca de nuevo con el mismo id; si se usó, el segundo falla y no pisa nada.
"""

import shlex
import subprocess
import time
import uuid

import pytest
from fastapi.testclient import TestClient

from puente_kvm import config, conversaciones, terminal
from puente_kvm.app import crear_app
from puente_kvm.simulador import Simulador

from .ayuda import PERSONA

FABLE = "claude-fable-5-2"


# ── el registro ─────────────────────────────────────────────────────────────
def test_una_conversacion_nueva_queda_registrada_con_su_id_su_modelo_y_su_carpeta():
    c = conversaciones.nueva("Revisión del SP", FABLE)
    assert conversaciones.UUID.fullmatch(c.id)
    guardada = conversaciones.buscar(c.id)
    assert guardada.nombre == "Revisión del SP" and guardada.modelo == FABLE
    assert guardada.espacio == str(config.espacio())
    assert (config.hogar() / "conversaciones.json").exists()


def test_la_lista_va_de_la_usada_mas_reciente_a_la_mas_antigua():
    a = conversaciones.nueva("a", FABLE)
    time.sleep(0.01)
    b = conversaciones.nueva("b", FABLE)
    time.sleep(0.01)
    conversaciones.tocar(a.id)
    assert [c.id for c in conversaciones.todas()] == [a.id, b.id]


@pytest.mark.parametrize("sucio, limpio", [
    ("  hola\x1b[31m  mundo\n ", "hola[31m mundo"),
    ("x" * 200, "x" * conversaciones.NOMBRE_MAX),
    ("\t\r\n", None),
])
def test_el_nombre_se_limpia_de_caracteres_de_control_y_de_largo(sucio, limpio):
    nombre = conversaciones.limpiar_nombre(sucio)
    if limpio is None:
        assert nombre.startswith("Conversación del ")
    else:
        assert nombre == limpio


@pytest.mark.parametrize("malo", ["", "1234", "../../etc", "8a0f…", "8A0F1F2E-1111-4111-8111-111111111111; rm -rf ~"])
def test_un_id_que_no_es_un_uuid_no_se_acepta(malo):
    with pytest.raises(ValueError):
        conversaciones.validar_id(malo)


def test_quitar_de_la_lista_no_toca_nada_de_claude_code():
    c = conversaciones.nueva("para quitar", FABLE)
    conversaciones.quitar(c.id)
    assert conversaciones.buscar(c.id) is None


# ── la orden que lanza Claude Code ──────────────────────────────────────────
def argumentos(orden: str) -> list[list[str]]:
    """Las llamadas a claude que hay en la orden, partidas como lo haría la shell."""
    partes = shlex.split(orden)
    llamadas, actual = [], None
    for p in partes:
        if p.endswith("claude") and "/" in p or p == "claude":
            actual = []
            llamadas.append(actual)
        elif p in ("||", ";", "&&"):
            actual = None
        elif actual is not None:
            actual.append(p)
    return llamadas


def test_una_conversacion_nueva_lleva_su_id_su_nombre_y_el_modelo_exacto(monkeypatch):
    monkeypatch.delenv("PUENTE_TERMINAL_ORDEN", raising=False)
    c = conversaciones.nueva("O'Brien; rm -rf ~", FABLE)
    [args] = argumentos(terminal.orden_claude(c, retomar=False))
    assert args[args.index("--session-id") + 1] == c.id
    assert args[args.index("-n") + 1] == "O'Brien; rm -rf ~"  # un solo argumento, tal cual
    assert args[args.index("--model") + 1] == FABLE
    assert "--permission-mode" in args


def test_retomar_usa_resume_y_si_nunca_se_escribio_arranca_con_el_mismo_id(monkeypatch):
    monkeypatch.delenv("PUENTE_TERMINAL_ORDEN", raising=False)
    c = conversaciones.nueva("dos", "claude-opus-5-5")
    retomar, de_nuevo = argumentos(terminal.orden_claude(c, retomar=True))
    assert retomar[retomar.index("--resume") + 1] == c.id and "-n" in retomar
    assert de_nuevo[de_nuevo.index("--session-id") + 1] == c.id
    assert "||" in shlex.split(terminal.orden_claude(c, retomar=True))


def test_con_el_modelo_de_mi_claude_code_no_se_pasa_model(monkeypatch):
    monkeypatch.delenv("PUENTE_TERMINAL_ORDEN", raising=False)
    c = conversaciones.nueva("tres", "")
    [args] = argumentos(terminal.orden_claude(c, retomar=False))
    assert "--model" not in args


def test_si_claude_code_no_arranca_la_shell_dice_donde_se_cambia_el_modelo(monkeypatch):
    monkeypatch.delenv("PUENTE_TERMINAL_ORDEN", raising=False)
    orden = terminal.orden_claude(conversaciones.nueva("x", FABLE), retomar=False)
    assert "Ajustes → Modelo de Claude" in orden


# ── la API: sólo la persona, una viva a la vez, y el control vuelve ─────────
def claude_falso(carpeta, version: str = "2.1.322"):
    """Un `claude` de mentira: dice su versión, cómo lo llamaron, y se queda abierto."""
    carpeta.mkdir(parents=True, exist_ok=True)
    falso = carpeta / "claude"
    falso.write_text('#!/bin/sh\n'
                     f'[ "$1" = "--version" ] && {{ echo "{version} (Claude Code)"; exit 0; }}\n'
                     'echo "falso-claude $*"\n'
                     'case "$*" in *--resume*) [ -f "$MARCA_CLAUDE" ] || { echo "No conversation found"; exit 1; } ;; esac\n'
                     'exec sleep 300\n')
    falso.chmod(0o755)
    return falso


@pytest.fixture
def puente(tmp_path, monkeypatch):
    """El puente con un `claude` de mentira en las carpetas de una persona de mentira.

    La casa es de mentira a propósito: las carpetas de la persona van delante en
    el PATH, y con la casa de verdad ganaría el Claude Code real.
    """
    casa = tmp_path / "casa"
    claude_falso(casa / ".local" / "bin")
    socket = f"puente-pruebas-{uuid.uuid4().hex[:6]}"
    monkeypatch.setenv("HOME", str(casa))
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    monkeypatch.setenv("PUENTE_TMUX_SOCKET", socket)
    monkeypatch.setenv("MARCA_CLAUDE", str(tmp_path / "con-mensajes"))
    monkeypatch.delenv("PUENTE_TERMINAL_ORDEN", raising=False)
    with TestClient(crear_app(Simulador(lineas=["x"]), hosts={"testserver"})) as c:
        yield c, tmp_path
    subprocess.run(["tmux", "-L", socket, "kill-server"], capture_output=True)


def pantalla(texto: str, tope: float = 10) -> str:
    fin = time.time() + tope
    while True:
        r = subprocess.run([*terminal.tmux(), "capture-pane", "-p", "-t", f"={terminal.SESION}:"],
                           capture_output=True, text=True)
        if texto in r.stdout or time.time() > fin:
            return r.stdout
        time.sleep(0.1)


def test_crear_conversaciones_es_de_la_persona(puente):
    c, _ = puente
    assert c.post("/api/conversaciones", json={"nombre": "x"}).status_code == 403
    assert c.post("/api/conversaciones", json={"nombre": "Revisión"}, headers=PERSONA).status_code == 200


def test_una_conversacion_nueva_arranca_claude_con_su_id_y_la_anterior_se_cierra(puente):
    c, _ = puente
    a = c.post("/api/conversaciones", json={"nombre": "Primera"}, headers=PERSONA).json()
    assert f"--session-id {a['id']}" in pantalla(a["id"])
    b = c.post("/api/conversaciones", json={"nombre": "Segunda"}, headers=PERSONA).json()
    visto = pantalla(b["id"])
    assert f"--session-id {b['id']}" in visto and a["id"] not in visto  # una sola viva
    estado = c.get("/api/conversaciones").json()
    assert estado["actual"]["id"] == b["id"]
    assert [x["id"] for x in estado["lista"]] == [b["id"], a["id"]]


def test_retomar_una_en_la_que_nunca_se_escribio_la_arranca_otra_vez_con_su_id(puente):
    c, _ = puente
    a = c.post("/api/conversaciones", json={"nombre": "Vacía"}, headers=PERSONA).json()
    c.post("/api/conversaciones", json={"nombre": "Otra"}, headers=PERSONA)
    assert c.post(f"/api/conversaciones/{a['id']}/abrir", headers=PERSONA).status_code == 200
    visto = pantalla(f"--session-id {a['id']}")
    assert "No conversation found" in visto and f"--session-id {a['id']}" in visto


def test_retomar_una_con_mensajes_usa_resume(puente):
    c, tmp = puente
    a = c.post("/api/conversaciones", json={"nombre": "Con mensajes"}, headers=PERSONA).json()
    c.post("/api/conversaciones", json={"nombre": "Otra"}, headers=PERSONA)
    (tmp / "con-mensajes").write_text("")
    c.post(f"/api/conversaciones/{a['id']}/abrir", headers=PERSONA)
    visto = pantalla(f"--resume {a['id']}")
    assert f"--resume {a['id']}" in visto and "No conversation found" not in visto


def test_cambiar_de_conversacion_devuelve_el_control_y_no_apunta_el_nombre(puente):
    c, _ = puente
    c.post("/api/control", json={"accion": "dar"}, headers=PERSONA)
    c.post("/api/conversaciones", json={"nombre": "usp_Secreto_Del_Trabajo"}, headers=PERSONA)
    assert c.get("/api/estado").json()["control"]["modo"] == "libre"
    bitacora = c.get("/api/bitacora").json()
    assert any(e["tipo"] == "control" for e in bitacora)
    assert any(e["tipo"] == "terminal" for e in bitacora)
    assert "usp_Secreto" not in str(bitacora)


def test_con_una_tarea_en_marcha_no_se_cambia_de_conversacion():
    from .ayuda import puente_simulado
    with puente_simulado(lineas=400, retardo_ms=60) as (c, _):
        c.post("/api/control", json={"accion": "dar"}, headers=PERSONA)
        c.post("/api/lecturas", json={"nombre": "larga"})
        time.sleep(0.3)
        r = c.post("/api/conversaciones", json={"nombre": "x"}, headers=PERSONA)
        assert r.status_code == 409 and "tarea" in r.json()["detail"]
        assert conversaciones.todas() == []
        c.post("/api/control", json={"accion": "parar"}, headers=PERSONA)


def test_renombrar_y_quitar_son_de_la_persona_y_la_abierta_no_se_quita(puente):
    c, _ = puente
    a = c.post("/api/conversaciones", json={"nombre": "Uno"}, headers=PERSONA).json()
    b = c.post("/api/conversaciones", json={"nombre": "Dos"}, headers=PERSONA).json()
    assert c.post(f"/api/conversaciones/{a['id']}/renombrar", json={"nombre": "x"}).status_code == 403
    assert c.post(f"/api/conversaciones/{a['id']}/renombrar", json={"nombre": "Uno bis\x07"},
                  headers=PERSONA).json()["nombre"] == "Uno bis"
    assert c.post(f"/api/conversaciones/{b['id']}/quitar", headers=PERSONA).status_code == 409
    assert c.post(f"/api/conversaciones/{a['id']}/quitar", headers=PERSONA).status_code == 200
    assert [x["id"] for x in c.get("/api/conversaciones").json()["lista"]] == [b["id"]]
    assert c.post("/api/conversaciones/no-es-un-uuid/abrir", headers=PERSONA).status_code == 400


def test_la_sesion_que_ya_estaba_sin_registro_aparece_como_conversacion_anterior(puente):
    c, _ = puente
    # La que dejó una versión anterior del puente: viva, sin registro.
    subprocess.run([*terminal.tmux(), "new-session", "-d", "-s", terminal.SESION, "sleep 300"], check=True)
    e = c.get("/api/conversaciones").json()
    assert e["actual"] is None and e["anterior"] is True
    # De ella no se sabe si Claude está a medias (C-0470): se pregunta, y confirmado se cierra.
    r = c.post("/api/conversaciones", json={"nombre": "Nueva"}, headers=PERSONA)
    assert r.status_code == 409 and r.headers["X-Puente-Motivo"] == "trabajando"
    c.post("/api/conversaciones", json={"nombre": "Nueva", "aunque_trabaje": True}, headers=PERSONA)
    assert c.get("/api/conversaciones").json()["anterior"] is False


# ── el modelo en Ajustes ────────────────────────────────────────────────────
def test_el_modelo_por_omision_es_fable_y_se_cambia_en_ajustes_contra_una_lista_cerrada(puente):
    c, _ = puente
    assert config.leer_ajustes()["claude"]["modelo"] == FABLE
    assert c.post("/api/ajustes", json={"claude": {"modelo": "opus"}}, headers=PERSONA).status_code == 400
    assert c.post("/api/ajustes", json={"claude": {"modelo": "claude-sonnet-5"}}, headers=PERSONA).status_code == 200
    a = c.post("/api/conversaciones", json={"nombre": "Con Sonnet"}, headers=PERSONA).json()
    assert "--model claude-sonnet-5" in pantalla(a["id"])
    assert c.get("/api/conversaciones").json()["actual"]["modelo_texto"] == "Sonnet 5"


def test_comprobar_avisa_si_fable_pide_un_claude_code_mas_nuevo(monkeypatch):
    from puente_kvm import comprobar
    p = comprobar.punto_modelo(FABLE, "2.1.300 (Claude Code)")
    assert p.estado == comprobar.OJO and "2.1.322" in p.detalle and "Opus 5.5" in p.arreglo
    assert comprobar.punto_modelo(FABLE, "2.1.322 (Claude Code)").estado == comprobar.BIEN
    assert comprobar.punto_modelo("claude-opus-5-5", "2.1.300 (Claude Code)").estado == comprobar.BIEN


def test_el_diagnostico_cuenta_las_conversaciones_sin_sus_nombres():
    from puente_kvm import comprobar
    conversaciones.nueva("usp_NombreDelTrabajo", FABLE)
    texto = comprobar.informe()
    assert "usp_NombreDelTrabajo" not in texto and "Conversaciones con Claude: 1" in texto


# ── el Claude Code que se usa de verdad ─────────────────────────────────────
def test_el_puente_dice_que_claude_code_usa_y_su_version(puente):
    c, tmp = puente
    cc = c.get("/api/estado").json()["claude_code"]
    assert cc["ruta"] == str(tmp / "casa" / ".local" / "bin" / "claude") and cc["version"] == "2.1.322"
    a = c.post("/api/conversaciones", json={"nombre": "Con versión"}, headers=PERSONA).json()
    assert a["claude_code"] == "2.1.322"
    assert c.get("/api/estado").json()["conversacion"]["claude_code"] == "2.1.322"


def test_fable_con_un_claude_code_viejo_no_se_arranca_a_ciegas_y_la_abierta_sigue(puente):
    c, tmp = puente
    a = c.post("/api/conversaciones", json={"nombre": "La buena"}, headers=PERSONA).json()
    claude_falso(tmp / "casa" / ".local" / "bin", version="2.1.112")  # alguien deja uno viejo delante
    r = c.post("/api/conversaciones", json={"nombre": "Con Fable"}, headers=PERSONA)
    assert r.status_code == 409
    detalle = r.json()["detail"]
    assert "2.1.112" in detalle and "2.1.322" in detalle and "Ajustes → Modelo de Claude" in detalle
    assert a["id"] in pantalla(a["id"])  # la que estaba abierta no se cerró
    # Con otro modelo, ese mismo Claude Code sí vale.
    c.post("/api/ajustes", json={"claude": {"modelo": "claude-opus-5-5"}}, headers=PERSONA)
    assert c.post("/api/conversaciones", json={"nombre": "Con Opus"}, headers=PERSONA).status_code == 200


def test_dentro_de_la_sesion_el_path_es_el_del_puente_aunque_el_login_lo_reinicie(monkeypatch):
    # bash -l (en Ubuntu, /etc/profile) reescribe el PATH: el `uv` de .mcp.json y el
    # `curl` de los hooks se buscarían en otro orden que el `claude` que lanza el puente.
    monkeypatch.delenv("PUENTE_TERMINAL_ORDEN", raising=False)
    orden = terminal.orden_claude(conversaciones.nueva("x", FABLE), retomar=False)
    partes = shlex.split(orden)
    assert partes[0] == "export" and partes[1] == f"PATH={terminal._path_de_usuario()}"
    assert partes[1].startswith(f"PATH={terminal.Path.home()}/.local/bin:")
