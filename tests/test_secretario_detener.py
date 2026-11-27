"""«Detener» la respuesta en curso del secretario (C-0506).

Con un `claude` falso de verdad en el PATH que habla stream-json y atiende el
`control_request` «interrupt» como el real (medido el 27-nov con Claude Code
2.1.322: el turno se cierra con su `result` —`is_error`,
`terminal_reason: aborted_streaming` o `aborted_tools`— y el proceso sigue
vivo). Lo que se prueba es que el proceso abierto corta entre herramientas,
sigue vivo para el turno siguiente, y que la conversación deja lo escrito con
«Detenido.» en vez de «No pude contestar».
"""

from __future__ import annotations

import json
import os
import sys
import threading
import time

import pytest

from hub.secretario import conversacion, memoria, motor

FALSO = r'''#!{py}
import json, os, queue, subprocess, sys, threading, time
args = sys.argv[1:]
REG = os.environ["REGISTRO"]
def apuntar(**d):
    with open(REG, "a") as f:
        f.write(json.dumps({{"pid": os.getpid(), "t": time.monotonic(), **d}}) + "\n")
apuntar(args=args)
sid = args[args.index("--session-id") + 1] if "--session-id" in args else args[args.index("--resume") + 1]
def sale(d):
    print(json.dumps(d), flush=True)
def res(texto, **mas):
    return {{"type": "result", "result": texto, "session_id": sid, "total_cost_usd": 0.001,
             "usage": {{"input_tokens": 5, "output_tokens": 2}}, **mas}}
def trozo(t):
    return {{"type": "stream_event", "event": {{"type": "content_block_delta", "delta": {{"type": "text_delta", "text": t}}}}}}
if "--input-format" not in args:
    texto = sys.stdin.read()
    sale(res(f"una-vez:{{texto}}"))
    sys.exit(0)
entrada = queue.Queue()
def leer():
    for l in sys.stdin:
        entrada.put(json.loads(l))
    entrada.put(None)
threading.Thread(target=leer, daemon=True).start()
def interrumpido(espera):
    """Lo que llegó en `espera` s: si es un «interrupt», contesta como el real."""
    try:
        m = entrada.get(timeout=espera)
    except queue.Empty:
        return False
    if m is None:
        sys.exit(0)
    if m.get("type") == "control_request":
        apuntar(interrupt=True)
        if os.environ.get("SORDO"):
            return False
        sale({{"type": "control_response", "response": {{"subtype": "success", "request_id": m["request_id"]}}}})
        return True
    entrada.queue.appendleft(m)
    return False
def escribir(reason):
    for i in range(400):
        sale(trozo(f"frase {{i}}. "))
        if interrumpido(0.05):
            sale({{"type": "user", "message": {{"content": [{{"type": "text", "text": "[Request interrupted by user]"}}]}}}})
            sale(res("", is_error=True, subtype="error_during_execution", terminal_reason=reason))
            return
    sale(res("terminé de escribir"))
n = 0
while True:
    m = entrada.get()
    if m is None:
        break
    if m.get("type") == "control_request":
        apuntar(interrupt=True, tarde=True)
        sale({{"type": "control_response", "response": {{"subtype": "success", "request_id": m["request_id"]}}}})
        continue
    if m.get("type") != "user":
        continue
    n += 1
    texto = m["message"]["content"]
    texto = texto.rsplit("\n", 1)[-1] if isinstance(texto, str) else ""
    sale({{"type": "system", "subtype": "init"}})
    if texto == "larga":
        if os.environ.get("NIETO"):
            # Lo que haría el servidor MCP: un hijo que hereda las tuberías.
            nieto = subprocess.Popen(["sleep", "60"])
            apuntar(nieto=nieto.pid)
        escribir("aborted_streaming")
    elif texto == "herramienta-lenta":
        sale({{"type": "assistant", "message": {{"content": [
            {{"type": "tool_use", "id": "toolu_9", "name": "mcp__secretario__buscar", "input": {{"texto": "x"}}}}]}}}})
        time.sleep(1.5)          # la herramienta en vuelo; lo que llegue, espera
        apuntar(fin_herramienta=True)
        sale({{"type": "user", "message": {{"content": [{{"type": "tool_result", "tool_use_id": "toolu_9"}}]}}}})
        escribir("aborted_streaming")
    elif texto == "rapida":
        sale(trozo("Listo."))
        sale(res("Listo."))
    else:
        sale(res(f"{{os.getpid()}}:{{n}}:{{texto}}"))
'''


@pytest.fixture
def falso(tmp_path, monkeypatch):
    from hub import tmux
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    (bin_ / "claude").write_text(FALSO.format(py=sys.executable))
    (bin_ / "claude").chmod(0o755)
    registro = tmp_path / "registro.jsonl"
    registro.touch()
    monkeypatch.setenv("REGISTRO", str(registro))
    monkeypatch.setattr(tmux, "path_de_usuario", lambda: f"{bin_}:/usr/bin:/bin")
    monkeypatch.setattr(motor, "CADA_PARAR_S", 0.1)
    yield lambda: [json.loads(l) for l in registro.read_text().splitlines()]
    motor.soltar()


def _abierta(prompt, sesion="s-1", nueva=False, **kw):
    return motor.llamar(prompt, modelo="claude-sonnet-5", sesion=sesion, nueva=nueva, herramientas=False,
                        abierta=True, trabajo="conversacion", **kw)


def _al_cabo(segundos):
    t0 = time.monotonic()
    return lambda: time.monotonic() - t0 > segundos


# ── el motor ────────────────────────────────────────────────────────────────

def test_parar_corta_el_turno_abierto_y_el_proceso_sigue_vivo_para_el_siguiente(falso):
    """Antes `parar` con `abierta` lanzaba ValueError: el chat no se podía parar."""
    primero = _abierta("hola", nueva=True).texto
    vistos = []
    with pytest.raises(motor.Cancelada):
        _abierta("larga", al_trozo=vistos.append, parar=_al_cabo(0.4))
    assert vistos and vistos[-1].startswith("frase 0."), "lo escrito hasta el corte se da entero"
    assert any(r.get("interrupt") for r in falso())
    otro = _abierta("sigue").texto
    assert otro.split(":")[0] == primero.split(":")[0], "el mismo proceso: no se pierde el hilo (328)"
    assert otro.endswith(":3:sigue")


def test_lo_cortado_no_se_repite_por_resume(falso):
    """`None` hace que `llamar` repita el turno por `--resume`: lo parado no puede volver."""
    _abierta("hola", nueva=True)
    with pytest.raises(motor.Cancelada):
        _abierta("larga", parar=_al_cabo(0.3))
    assert not any("--resume" in (r.get("args") or []) for r in falso())


def test_con_una_herramienta_en_vuelo_espera_a_que_acabe_antes_de_pedir_parar(falso):
    """Cortada, el servidor del MCP puede acabarla igual y el modelo la creería no hecha."""
    _abierta("hola", nueva=True)
    with pytest.raises(motor.Cancelada):
        _abierta("herramienta-lenta", parar=lambda: True)
    registro = falso()
    fin = next(r["t"] for r in registro if r.get("fin_herramienta"))
    pedido = next(r["t"] for r in registro if r.get("interrupt"))
    assert pedido >= fin


def test_si_el_proceso_no_atiende_la_peticion_se_mata_su_grupo_entero(falso, monkeypatch):
    """Matar sólo a `claude` dejaba vivo a su servidor MCP (el defecto de C-0241)."""
    monkeypatch.setenv("SORDO", "1")
    monkeypatch.setenv("NIETO", "1")
    monkeypatch.setattr(motor, "ESPERA_INTERRUMPIR_S", 0.5)
    _abierta("hola", nueva=True)
    with pytest.raises(motor.Cancelada):
        _abierta("larga", parar=_al_cabo(0.2))
    nieto = next(r["nieto"] for r in falso() if r.get("nieto"))
    for _ in range(50):
        try:
            os.kill(nieto, 0)
        except ProcessLookupError:
            break
        time.sleep(0.05)
    else:
        pytest.fail("el nieto sigue vivo")
    # Muerto el proceso, el turno siguiente abre otro y retoma la sesión.
    assert _abierta("sigue").texto.endswith(":1:sigue")


def test_si_acaba_solo_antes_de_atender_la_peticion_gana_lo_terminado(falso):
    _abierta("hola", nueva=True)
    assert _abierta("rapida", parar=lambda: True).texto == "Listo."
    # El proceso siguió vivo y el turno siguiente no recibe nada de esa petición.
    assert _abierta("sigue").texto.endswith(":3:sigue")


# ── la conversación ─────────────────────────────────────────────────────────

@pytest.fixture
def chat(falso, monkeypatch):
    """`contestar` de verdad, con el `claude` falso y el prompt reducido a la
    última línea (el guion del falso se elige con ella)."""
    monkeypatch.setattr(conversacion, "sistema", lambda: "S")
    return memoria.conectar()


def _contestar_en_otro_hilo(texto: str):
    """Como `hub-secretario`: el turno se contesta en su hilo, con su conexión,
    y `detener` llega de otra (la de `hub-web`)."""
    con = memoria.conectar()
    t = conversacion.recibir(con, texto)
    con.close()

    def contestar():
        c = memoria.conectar()
        conversacion.contestar(c, c.execute("SELECT * FROM turno WHERE id = ?", (t["turno"],)).fetchone())
        c.close()
    hilo = threading.Thread(target=contestar, daemon=True)
    hilo.start()
    return t, hilo


def _esperar(cond, tope=10.0):
    fin = time.monotonic() + tope
    while time.monotonic() < fin:
        if cond():
            return True
        time.sleep(0.05)
    return False


def _respuesta(con, dueno):
    return con.execute("SELECT * FROM turno WHERE rol = 'secretario' AND id > ? ORDER BY id LIMIT 1",
                       (dueno,)).fetchone()


def test_detener_a_mitad_deja_lo_escrito_con_detenido_y_no_un_fallo(chat):
    t, hilo = _contestar_en_otro_hilo("larga")
    assert _esperar(lambda: (_respuesta(chat, t["turno"]) or {"texto": ""})["texto"])
    assert conversacion.detener(chat, t["turno"]) == {"pedido": True}
    hilo.join(15)
    assert not hilo.is_alive()
    r = _respuesta(chat, t["turno"])
    assert r["estado"] == "listo" and r["texto"].startswith("frase 0.") and r["texto"].endswith("Detenido.")
    assert "No pude contestar" not in r["texto"]
    assert chat.execute("SELECT estado FROM turno WHERE id = ?", (t["turno"],)).fetchone()[0] == "listo"
    assert memoria.leer(chat, conversacion.PARAR_TURNO.format(t["turno"])) is None, "la marca la quita contestar"
    assert conversacion.detener(chat, t["turno"]) == {"ya_terminado": True}


def test_el_turno_siguiente_lleva_la_nota_una_sola_vez(chat, monkeypatch):
    t, hilo = _contestar_en_otro_hilo("larga")
    assert _esperar(lambda: (_respuesta(chat, t["turno"]) or {"texto": ""})["texto"])
    conversacion.detener(chat, t["turno"])
    hilo.join(15)
    enviados = []
    real = motor.llamar
    monkeypatch.setattr(motor, "llamar", lambda prompt, **kw: enviados.append(prompt) or real("rapida", **kw))
    for texto in ("otra", "y otra"):
        conversacion.recibir(chat, texto)
        conversacion.atender(chat)
    assert "detuvo tu respuesta anterior" in enviados[0]
    assert "detuvo tu respuesta anterior" not in enviados[1]


def test_detener_uno_que_aun_espera_no_lo_contesta(chat, monkeypatch):
    t = conversacion.recibir(chat, "hola")
    assert conversacion.detener(chat, t["turno"]) == {"detenido": True}
    llamadas = []
    monkeypatch.setattr(motor, "llamar", lambda prompt, **kw: llamadas.append(prompt))
    assert conversacion.atender(chat) == 0 and llamadas == []
    r = _respuesta(chat, t["turno"])
    assert r["estado"] == "listo" and r["texto"].startswith("Detenido.")


def test_contestar_no_toma_un_turno_que_ya_no_esta_pendiente(chat, monkeypatch):
    """`atender` lee la lista antes: el que él detuvo entretanto se salta."""
    t = conversacion.recibir(chat, "hola")
    fila = chat.execute("SELECT * FROM turno WHERE id = ?", (t["turno"],)).fetchone()
    conversacion.detener(chat, t["turno"])
    monkeypatch.setattr(motor, "llamar", lambda *a, **k: pytest.fail("no debía llamar al modelo"))
    assert conversacion.contestar(chat, fila) is False


def test_al_detenerse_dice_lo_que_ya_hizo_y_lo_que_espera_permiso(chat):
    from hub.secretario import piezas
    accion = next(iter(piezas.acciones()))
    t, hilo = _contestar_en_otro_hilo("larga")
    assert _esperar(lambda: (_respuesta(chat, t["turno"]) or {"texto": ""})["texto"])
    # Lo que habría apuntado el servidor del MCP mientras contestaba.
    memoria.apuntar(chat, accion, nivel="auto", resultado="hecho")
    memoria.apuntar(chat, "pantalla_actual", nivel="lectura")
    chat.execute("INSERT INTO solicitud (accion, params, hilo, creada) VALUES (?,?,?,?)",
                 ("escribir_en_sesion", "{}", t["hilo"], memoria.ahora()))
    conversacion.detener(chat, t["turno"])
    hilo.join(15)
    texto = _respuesta(chat, t["turno"])["texto"]
    assert f"quedó hecho: {piezas.nombre_de_accion(accion)}." in texto and "no lo deshace" in texto
    assert piezas.nombre_de_accion("escribir_en_sesion") in texto and "Pendientes" in texto
    assert "pantalla" not in texto.split("Detenido.")[1], "las lecturas no son acciones"


def test_la_peticion_es_de_ese_turno_y_no_alcanza_al_siguiente(chat):
    t = conversacion.recibir(chat, "hola")
    conversacion.atender(chat)
    assert conversacion.detener(chat, t["turno"]) == {"ya_terminado": True}
    assert memoria.leer(chat, conversacion.PARAR_TURNO.format(t["turno"])) is None
    otro = conversacion.recibir(chat, "rapida")
    conversacion.atender(chat)
    assert _respuesta(chat, otro["turno"])["texto"] == "Listo."


def test_detener_sin_turno_valido_lo_dice(chat):
    for malo in (None, "3", True, 0, 2 ** 70):
        with pytest.raises(ValueError):
            conversacion.detener(chat, malo)
    with pytest.raises(ValueError):
        conversacion.detener(chat, 999)


def test_el_que_se_cortaba_al_reiniciar_ya_detenido_no_se_repite(chat):
    """`retomar_cortados` volvía a poner en cola lo que él había parado."""
    t = conversacion.recibir(chat, "hola")
    chat.execute("UPDATE turno SET estado = 'atendiendo' WHERE id = ?", (t["turno"],))
    rid = chat.execute("INSERT INTO turno (hilo, rol, texto, estado, creado) VALUES (?,?,?,?,?)",
                       (t["hilo"], "secretario", "Iba por aquí", "escribiendo", memoria.ahora())).lastrowid
    memoria.poner(chat, f"turno_en_curso:{t['hilo']}", rid)
    memoria.poner(chat, conversacion.PARAR_TURNO.format(t["turno"]), {"pedida": memoria.ahora()})
    conversacion.retomar_cortados(chat)
    assert chat.execute("SELECT estado FROM turno WHERE id = ?", (t["turno"],)).fetchone()[0] == "listo"
    r = chat.execute("SELECT texto, estado FROM turno WHERE id = ?", (rid,)).fetchone()
    assert tuple(r) == ("Iba por aquí\n\nDetenido.", "listo")
    assert memoria.leer(chat, f"retomar:{t['turno']}") is None


def test_el_detenido_al_reiniciar_sin_respuesta_a_medias_lo_dice_en_un_globo(chat):
    t = conversacion.recibir(chat, "hola")
    chat.execute("UPDATE turno SET estado = 'atendiendo' WHERE id = ?", (t["turno"],))
    memoria.poner(chat, conversacion.PARAR_TURNO.format(t["turno"]), {"pedida": memoria.ahora()})
    conversacion.retomar_cortados(chat)
    r = _respuesta(chat, t["turno"])
    assert (r["texto"], r["estado"]) == ("Detenido.", "listo")


def test_el_escalado_al_modelo_mayor_tambien_se_puede_parar(chat, monkeypatch):
    t = conversacion.recibir(chat, "hola")
    vistos = []

    def espiar(prompt, **kw):
        vistos.append(kw.get("parar"))
        if len(vistos) == 1:
            rid = chat.execute("SELECT MAX(id) FROM turno WHERE rol = 'secretario'").fetchone()[0]
            memoria.poner(chat, f"escalar:{rid}", {"motivo": "difícil"})
            return motor.Respuesta(texto="menor", sesion="s-9", estructurada=None, segundos=0.1, coste=0,
                                   modelo="m")
        raise motor.Cancelada("parado")
    monkeypatch.setattr(motor, "llamar", espiar)
    conversacion.atender(chat)
    assert len(vistos) == 2 and all(callable(p) for p in vistos)
    assert _respuesta(chat, t["turno"])["texto"].endswith("Detenido.")


# ── la web ──────────────────────────────────────────────────────────────────

def test_el_post_de_detener_pide_parar_y_comprueba_el_origen(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from hub import web
    con = memoria.conectar()
    t = conversacion.recibir(con, "hola")
    con.execute("UPDATE turno SET estado = 'atendiendo' WHERE id = ?", (t["turno"],))
    c = TestClient(web.app)
    origen = {"Origin": "http://127.0.0.1:8787"}
    assert c.post("/api/secretario/detener", json={"turno": t["turno"]},
                  headers={"Origin": "http://otra.example"}).status_code == 403
    r = c.post("/api/secretario/detener", json={"turno": t["turno"]}, headers=origen)
    assert r.json() == {"ok": True, "pedido": True}
    assert memoria.leer(con, conversacion.PARAR_TURNO.format(t["turno"])) is not None
    assert c.post("/api/secretario/detener", json={"turno": "x"}, headers=origen).status_code == 400
