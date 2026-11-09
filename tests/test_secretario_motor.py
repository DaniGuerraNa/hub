"""El motor detrás de su costura y el proceso abierto entre turnos (decisión 328).

Con un `claude` falso de verdad en el PATH, que habla `stream-json` como el
real: lo que se prueba es que el proceso se reutiliza, se cierra cuando debe y
que si muere a mitad el turno se contesta igual. Que el `claude` real se
comporta así se midió el 2-nov (ver el docstring de `motor`).
"""

from __future__ import annotations

import json
import sys

import pytest

from hub.secretario import conversacion, herramientas, memoria, motor

FALSO = r'''#!{py}
import json, os, sys
args = sys.argv[1:]
CORTES = ("CLAUDE_BYTE_STREAM_IDLE_TIMEOUT_MS", "CLAUDE_STREAM_FIRST_BYTE_TIMEOUT_MS")
with open(os.environ["REGISTRO"], "a") as f:
    f.write(json.dumps({{"pid": os.getpid(), "args": args,
                        "entorno": {{k: os.environ.get(k) for k in CORTES}}}}) + "\n")
sid = args[args.index("--session-id") + 1] if "--session-id" in args else args[args.index("--resume") + 1]
def res(texto):
    return {{"type": "result", "result": texto, "session_id": sid, "total_cost_usd": 0.001,
             "usage": {{"input_tokens": 5, "output_tokens": 2}}}}
def ev(e):
    return {{"type": "stream_event", "event": e}}
USO = {{"type": "tool_use", "id": "toolu_1", "name": "mcp__secretario__buscar", "input": {{"texto": "Ana"}}}}
# Una herramienta como la cuenta el real (medido el 6-nov, 2.1.280): con
# parciales, el mensaje entero con los argumentos llega ANTES que el stop.
HERRAMIENTA_PARCIAL = [
    ev({{"type": "message_start"}}),
    ev({{"type": "content_block_start", "index": 0, "content_block": {{"type": "thinking", "thinking": ""}}}}),
    ev({{"type": "content_block_stop", "index": 0}}),
    ev({{"type": "content_block_start", "index": 1, "content_block": {{**USO, "input": {{}}}}}}),
    ev({{"type": "content_block_delta", "index": 1, "delta": {{"type": "input_json_delta", "partial_json": "{{\"texto\": \"An"}}}}),
    ev({{"type": "content_block_delta", "index": 1, "delta": {{"type": "input_json_delta", "partial_json": "a\"}}"}}}}),
    {{"type": "assistant", "message": {{"content": [USO]}}}},
    ev({{"type": "content_block_stop", "index": 1}}),
    {{"type": "user", "message": {{"content": [{{"type": "tool_result", "tool_use_id": "toolu_1"}}]}}}},
    ev({{"type": "message_start"}}),
    ev({{"type": "content_block_delta", "index": 0, "delta": {{"type": "text_delta", "text": "Hecho."}}}}),
]
# Sin parciales (el camino de un solo uso): sólo los mensajes enteros.
HERRAMIENTA_ENTERA = [
    {{"type": "assistant", "message": {{"content": [{{"type": "thinking", "thinking": "…"}}]}}}},
    {{"type": "assistant", "message": {{"content": [USO]}}}},
    {{"type": "user", "message": {{"content": [{{"type": "tool_result", "tool_use_id": "toolu_1"}}]}}}},
    {{"type": "assistant", "message": {{"content": [{{"type": "text", "text": "Hecho."}}]}}}},
]
if "--input-format" in args:
    n = 0
    for linea in sys.stdin:
        n += 1
        texto = json.loads(linea)["message"]["content"]
        if texto == "muere":
            sys.exit(1)
        if texto == "cuelga":
            import time
            time.sleep(60)
        if texto == "cuelga-tras-herramienta":
            # Lo del 5-nov: la herramienta contesta y la llamada siguiente a la
            # API no llega nunca; el CLI no dice nada más.
            import time
            for l in HERRAMIENTA_PARCIAL[:9]:
                print(json.dumps(l), flush=True)
            time.sleep(60)
        if texto == "api_error":
            # Como el real cuando su vigilante agota los reintentos (C-0170,
            # medido con una API falsa): un `result` con error, y vivo.
            print(json.dumps({{**res("API Error: stream idle: no bytes for 45000ms"), "is_error": True,
                              "terminal_reason": "api_error"}}), flush=True)
            continue
        if texto == "trozos-y-api_error":
            # Empieza a contestar y la API se corta a mitad (C-0185).
            for t in ["Déjame ", "mirarlo."]:
                print(json.dumps(ev({{"type": "content_block_delta", "delta": {{"type": "text_delta", "text": t}}}})),
                      flush=True)
            print(json.dumps({{**res("API Error: stream idle"), "is_error": True, "terminal_reason": "api_error"}}),
                  flush=True)
            continue
        if texto == "api_error con llave":
            print(json.dumps({{"type": "user", "message": {{"content": [{{"type": "tool_result",
                  "tool_use_id": "toolu_1", "content": "{{\"password\": \"hunter2-largo\"}}"}}]}}}}), flush=True)
            print(json.dumps({{**res("API Error: 401 token=abcdef0123456789xyz"), "is_error": True,
                              "terminal_reason": "api_error"}}), flush=True)
            continue
        print(json.dumps({{"type": "system", "subtype": "init"}}), flush=True)
        if texto == "trozos" and "--include-partial-messages" in args:
            # Como el real: una frase, una herramienta, y la respuesta en otro
            # mensaje; el `result` trae sólo el último.
            for mensaje in (["Déjame ", "mirarlo."], ["Tienes ", "dos ", "cosas."]):
                print(json.dumps({{"type": "stream_event", "event": {{"type": "message_start"}}}}), flush=True)
                for t in mensaje:
                    print(json.dumps({{"type": "stream_event", "event": {{"type": "content_block_delta",
                          "delta": {{"type": "text_delta", "text": t}}}}}}), flush=True)
            print(json.dumps(res("Tienes dos cosas.")), flush=True)
            continue
        if texto == "herramienta" and "--include-partial-messages" in args:
            for l in HERRAMIENTA_PARCIAL:
                print(json.dumps(l), flush=True)
            print(json.dumps(res("Hecho.")), flush=True)
            continue
        print(json.dumps(res(f"{{os.getpid()}}:{{n}}:{{texto}}")), flush=True)
elif "stream-json" in args:
    texto = sys.stdin.read()
    for l in (HERRAMIENTA_ENTERA if texto == "herramienta" else []):
        print(json.dumps(l), flush=True)
    if texto == "muere":
        print("se cayó", file=sys.stderr)
        sys.exit(3)
    print(json.dumps(res(f"una-vez:{{texto}}")))
else:
    texto = sys.stdin.read()
    print(json.dumps(res(f"una-vez:{{texto}}")))
'''


@pytest.fixture
def falso(tmp_path, monkeypatch):
    from hub import tmux
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    (bin_ / "claude").write_text(FALSO.format(py=sys.executable))
    (bin_ / "claude").chmod(0o755)
    registro = tmp_path / "registro.jsonl"
    monkeypatch.setenv("REGISTRO", str(registro))
    monkeypatch.setattr(tmux, "path_de_usuario", lambda: f"{bin_}:/usr/bin:/bin")
    yield lambda: [json.loads(l) for l in registro.read_text().splitlines()]
    motor.soltar()


def _abierta(prompt, sesion="s-1", nueva=False, **kw):
    return motor.llamar(prompt, modelo="claude-sonnet-5", sesion=sesion, nueva=nueva, herramientas=False,
                        abierta=True, trabajo="conversacion", **kw)


def _otra_vez(texto: str) -> str:
    """Lo que contesta el falso a un turno repetido por `--resume`: el mensaje
    va con el aviso del corte delante (C-0185)."""
    return f"una-vez:{motor.RETOMAR}{texto}"


def test_los_turnos_de_un_hilo_reusan_el_mismo_proceso(falso):
    a = _abierta("hola", nueva=True)
    b = _abierta("otra")
    pid_a, n_a, _ = a.texto.split(":")
    pid_b, n_b, _ = b.texto.split(":")
    assert pid_a == pid_b and (n_a, n_b) == ("1", "2")
    assert a.sesion == b.sesion == "s-1"
    [arranque] = falso()
    assert "--session-id" in arranque["args"] and "stream-json" in arranque["args"]


def test_cada_turno_abierto_cuenta_su_gasto(falso):
    con = memoria.conectar()
    _abierta("hola", nueva=True)
    _abierta("otra")
    [u] = memoria.uso(con)
    assert u["llamadas"] == 2 and u["entrada"] == 10 and u["salida"] == 4


def test_una_llamada_suelta_a_la_misma_sesion_cierra_el_proceso_y_el_siguiente_turno_la_retoma(falso):
    a = _abierta("hola", nueva=True)
    e = motor.llamar("escala", modelo="claude-opus-5-5", sesion="s-1", herramientas=False)
    assert e.texto == "una-vez:escala"
    b = _abierta("sigue")
    assert a.texto.split(":")[0] != b.texto.split(":")[0]
    tercero = falso()[2]["args"]
    assert "--resume" in tercero and "--session-id" not in tercero


def test_si_el_proceso_muere_a_mitad_el_turno_se_contesta_igual(falso):
    _abierta("hola", nueva=True)
    r = _abierta("muere")
    assert r.texto == _otra_vez("muere")
    assert "--resume" in falso()[-1]["args"]


def test_cambiar_de_modelo_abre_otro_proceso(falso):
    a = _abierta("hola", nueva=True)
    b = motor.llamar("otra", modelo="claude-haiku-4-5", sesion="s-1", herramientas=False, abierta=True)
    assert a.texto.split(":")[0] != b.texto.split(":")[0]


def test_lo_abierto_sin_usarse_se_cierra(falso, monkeypatch):
    _abierta("hola", nueva=True)
    monkeypatch.setattr(motor, "ABIERTO_MAX_S", -1)
    motor.podar()
    assert motor.MOTORES["suscripcion"]._abiertos == {}


def test_una_llamada_sin_sesion_no_cierra_lo_abierto(falso):
    a = _abierta("hola", nueva=True)
    motor.llamar("triaje", modelo="claude-haiku-4-5", herramientas=False, persistir=False)
    b = _abierta("otra")
    assert a.texto.split(":")[0] == b.texto.split(":")[0]


def test_un_motor_que_no_existe_se_dice_con_los_que_hay(falso):
    (memoria.carpeta() / "secretario.yml").write_text("motor: api\n")
    with pytest.raises(motor.MotorCaido, match="suscripcion"):
        motor.llamar("hola", modelo="claude-haiku-4-5", herramientas=False)


def test_el_motor_se_elige_en_secretario_yml(monkeypatch):
    llamadas = []

    class Otro(motor.Motor):
        id = "otro"

        def llamar(self, prompt, **kw):
            llamadas.append(prompt)
            return motor.Respuesta("de otro", "s", None, 0.1, 0, kw["modelo"])

    monkeypatch.setitem(motor.MOTORES, "otro", Otro())
    (memoria.carpeta() / "secretario.yml").write_text("motor: otro\n")
    assert motor.llamar("hola", modelo="m").texto == "de otro" and llamadas == ["hola"]


def test_la_tarjeta_va_al_turno_en_curso_aunque_el_entorno_sea_del_primero(monkeypatch):
    con = memoria.conectar()
    conversacion.recibir(con, "hola")
    hilo = conversacion.hilo_abierto(con)["id"]
    rid = con.execute("INSERT INTO turno (hilo, rol, estado, creado) VALUES (?,?,?,?)",
                      (hilo, "secretario", "escribiendo", memoria.ahora())).lastrowid
    memoria.poner(con, f"turno_en_curso:{hilo}", rid)
    monkeypatch.setenv("SECRETARIO_HILO", str(hilo))
    monkeypatch.setenv("SECRETARIO_TURNO", "999")   # el del primer turno del proceso
    assert herramientas._tarjeta(con, {"titulo": "T", "filas": [["a"]]})["ok"]
    assert json.loads(con.execute("SELECT tarjetas FROM turno WHERE id = ?", (rid,)).fetchone()[0])[0]["titulo"] == "T"


def test_una_llamada_con_imagenes_va_como_bloques_de_stream_json(falso, tmp_path):
    foto = tmp_path / "pantalla.jpg"
    foto.write_bytes(b"\xff\xd8\xff falso")
    r = motor.llamar("¿hay reunión?", modelo="claude-haiku-4-5", herramientas=False, imagenes=[foto])
    # El claude falso contesta con el texto del mensaje; con bloques, el último es el texto.
    assert r.texto.endswith("¿hay reunión?") or "¿hay reunión?" in r.texto
    assert "--input-format" in falso()[-1]["args"]


# ── la respuesta por trozos (C-0155) ─────────────────────────────────────────

def test_el_proceso_abierto_da_el_texto_acumulado_de_todos_sus_mensajes(falso):
    vistos = []
    r = _abierta("trozos", nueva=True, al_trozo=vistos.append)
    assert r.texto == "Tienes dos cosas."
    assert vistos[-1] == "Déjame mirarlo.\n\nTienes dos cosas."
    # Al cerrar la primera frase ya se avisó, sin esperar al resultado.
    assert "Déjame mirarlo." in vistos


def test_quien_no_pide_trozos_recibe_la_respuesta_igual(falso):
    assert _abierta("trozos", nueva=True).texto == "Tienes dos cosas."


def test_un_motor_que_no_sabe_de_trozos_sigue_sirviendo(monkeypatch):
    """`al_trozo` es opcional en el contrato: cambiar de motor no rompe a quien lo pide."""
    class Viejo(motor.Motor):
        def llamar(self, prompt, *, modelo, sistema, sesion, nueva, herramientas, esquema, esfuerzo,
                   entorno_extra, persistir, abierta):
            return motor.Respuesta(texto="entera", sesion="s", estructurada=None, segundos=0.1, coste=0,
                                   modelo=modelo)
    monkeypatch.setitem(motor.MOTORES, "viejo", Viejo())
    monkeypatch.setattr(conversacion, "ajustes", lambda: {"motor": "viejo"})
    vistos = []
    assert motor.llamar("hola", modelo="m", al_trozo=vistos.append, abierta=True).texto == "entera"
    assert vistos == []


def test_el_turno_guarda_lo_dicho_antes_de_la_herramienta_y_marca_lo_que_llego_por_voz(falso, monkeypatch):
    monkeypatch.setattr(conversacion, "sistema", lambda: "S")
    con = memoria.conectar()
    conversacion.recibir(con, "trozos", voz=True)
    turno = con.execute("SELECT * FROM turno WHERE rol = 'dueno'").fetchone()
    assert turno["voz"] == 1
    enviados = []
    real = motor.llamar
    monkeypatch.setattr(motor, "llamar", lambda prompt, **kw: enviados.append(prompt) or real("trozos", **kw))
    conversacion.atender(con)
    assert enviados[0].startswith("(por voz) ")
    respuesta = con.execute("SELECT texto, estado FROM turno WHERE rol = 'secretario'").fetchone()
    assert tuple(respuesta) == ("Déjame mirarlo.\n\nTienes dos cosas.", "listo")


def test_si_el_primer_turno_de_un_hilo_muere_a_mitad_se_contesta_igual(falso):
    """El primer turno va ahora por el proceso abierto (C-0155): si muere, se retoma."""
    assert _abierta("muere", nueva=True).texto == _otra_vez("muere")


def test_un_proceso_abierto_que_se_queda_mudo_se_mata_y_el_turno_se_repite(falso, monkeypatch):
    """Medido el 5-nov: 2 min 8 s sin contestar tras una herramienta, y lo de detrás esperando."""
    import time
    monkeypatch.setattr(motor, "SIN_NOTICIAS_S", 1)
    _abierta("hola", nueva=True)
    t0 = time.monotonic()
    assert _abierta("cuelga").texto == _otra_vez("cuelga")
    assert time.monotonic() - t0 < 15


# ── por qué se quedó mudo, y qué hace el propio CLI (C-0170) ─────────────────

def test_el_cli_lleva_su_corte_de_red_corto_en_cada_camino(falso):
    """Sin un byte de la API en 45 s, el propio `claude` corta y reintenta en el
    mismo proceso. Por omisión espera 180-300 s: más que nuestro `SIN_NOTICIAS_S`,
    así que nunca llegaba a hacerlo (medido con una API falsa, C-0170)."""
    _abierta("hola", nueva=True)
    motor.llamar("triaje", modelo="claude-haiku-4-5", herramientas=False, persistir=False)
    motor.llamar("herramienta", modelo="claude-opus-5-5", sesion="s-9", herramientas=False,
                 al_evento=lambda e: None)
    llamadas = falso()
    assert len(llamadas) == 3
    for llamada in llamadas:
        assert llamada["entorno"] == {"CLAUDE_BYTE_STREAM_IDLE_TIMEOUT_MS": "45000",
                                      "CLAUDE_STREAM_FIRST_BYTE_TIMEOUT_MS": "45000"}


def test_un_error_de_la_api_en_el_proceso_abierto_se_repite_por_resume(falso):
    """Agotados sus reintentos, el CLI da un `result` con error y sigue vivo:
    eso no es «el modelo no contestó» sino una red que falló, y un intento más
    con conexión nueva es lo que el 5-nov contestó en 6,7 s."""
    _abierta("hola", nueva=True)
    r = _abierta("api_error")
    assert r.texto == _otra_vez("api_error")
    assert "--resume" in falso()[-1]["args"]
    assert motor.MOTORES["suscripcion"]._abiertos == {}, "nunca dos procesos con la misma sesión"


def test_al_matar_un_proceso_mudo_cuenta_lo_ultimo_que_dijo_y_apunta_lo_perdido(falso, monkeypatch, capsys):
    """El 5-nov hizo falta el transcript para saber dónde se paró; ahora queda
    en el journal. Y el intento tirado cuenta como llamada fallida con su tiempo:
    sin eso, `uso` decía «una llamada de 7 s» de un turno que tardó dos minutos."""
    monkeypatch.setattr(motor, "SIN_NOTICIAS_S", 1)
    _abierta("hola", nueva=True)
    assert _abierta("cuelga-tras-herramienta").texto == _otra_vez("cuelga-tras-herramienta")
    err = capsys.readouterr().err
    assert "tool_result" in err and "toolu_1" in err
    filas = memoria.conectar().execute("SELECT ok, segundos FROM llamada ORDER BY id").fetchall()
    assert [f["ok"] for f in filas] == [1, 0, 1]
    assert filas[1]["segundos"] >= 1


def test_al_llegar_al_tope_cuenta_lo_ultimo_que_dijo_y_lo_apunta_como_fallo(falso, monkeypatch, capsys):
    monkeypatch.setattr(motor, "TOPE_SEGUNDOS", 2)
    _abierta("hola", nueva=True)
    with pytest.raises(motor.MotorCaido, match="no contestó"):
        _abierta("cuelga-tras-herramienta")
    assert "tool_result" in capsys.readouterr().err
    filas = memoria.conectar().execute("SELECT ok, segundos FROM llamada ORDER BY id").fetchall()
    assert [f["ok"] for f in filas] == [1, 0] and filas[1]["segundos"] >= 2


# ── lo que hace mientras contesta (C-0166, decisión 358) ─────────────────────

def test_el_proceso_abierto_cuenta_que_piensa_que_herramienta_usa_con_que_y_cuando_acaba(falso):
    eventos = []
    r = _abierta("herramienta", nueva=True, al_evento=eventos.append)
    assert r.texto == "Hecho."
    # Al empezar, sin argumentos (para enseñarlo ya); con ellos, una sola vez
    # más aunque lleguen por el mensaje entero Y por el stop; y el prefijo del
    # MCP fuera: el catálogo habla de «buscar», no de «mcp__secretario__buscar».
    assert eventos == [{"tipo": "pensando"},
                       {"tipo": "herramienta", "nombre": "buscar", "args": {}},
                       {"tipo": "herramienta", "nombre": "buscar", "args": {"texto": "Ana"}},
                       {"tipo": "fin_herramienta"}]


def test_la_llamada_suelta_tambien_cuenta_lo_que_hace_por_stream_json(falso):
    """La del modelo mayor al escalar: sin esto se quedaba «pensando» mientras buscaba."""
    eventos = []
    r = motor.llamar("herramienta", modelo="claude-opus-5-5", sesion="s-9", herramientas=False,
                     al_evento=eventos.append)
    assert r.texto == "una-vez:herramienta"
    assert eventos == [{"tipo": "pensando"},
                       {"tipo": "herramienta", "nombre": "buscar", "args": {"texto": "Ana"}},
                       {"tipo": "fin_herramienta"}]
    args = falso()[-1]["args"]
    assert args[args.index("--output-format") + 1] == "stream-json" and "--verbose" in args


def test_la_llamada_suelta_que_muere_lo_dice_con_su_error(falso):
    with pytest.raises(motor.MotorCaido, match="se cayó"):
        motor.llamar("muere", modelo="claude-opus-5-5", sesion="s-9", herramientas=False, al_evento=lambda e: None)


def test_quien_escucha_y_falla_no_tumba_el_turno(falso):
    def roto(evento):
        raise RuntimeError("el personaje se rompió")
    assert _abierta("herramienta", nueva=True, al_evento=roto).texto == "Hecho."


def test_un_motor_que_no_sabe_de_eventos_sigue_sirviendo(monkeypatch):
    """`al_evento` es opcional en el contrato, como `al_trozo` (decisión 358)."""
    class Viejo(motor.Motor):
        def llamar(self, prompt, *, modelo, sistema, sesion, nueva, herramientas, esquema, esfuerzo,
                   entorno_extra, persistir, abierta, al_trozo=None):
            return motor.Respuesta(texto="entera", sesion="s", estructurada=None, segundos=0.1, coste=0,
                                   modelo=modelo)
    monkeypatch.setitem(motor.MOTORES, "viejo", Viejo())
    monkeypatch.setattr(conversacion, "ajustes", lambda: {"motor": "viejo"})
    vistos = []
    assert motor.llamar("hola", modelo="m", al_evento=vistos.append, abierta=True).texto == "entera"
    assert vistos == []


def test_el_turno_guarda_lo_que_hace_con_su_rotulo_y_lo_vacia_al_acabar(falso, monkeypatch):
    monkeypatch.setattr(conversacion, "sistema", lambda: "S")
    con = memoria.conectar()
    conversacion.recibir(con, "herramienta")
    vistas = []
    real = motor.llamar

    def espiar(prompt, **kw):
        listo = kw["al_evento"]

        def al_evento(e):
            listo(e)
            vistas.append(con.execute("SELECT actividad FROM turno WHERE rol = 'secretario'").fetchone()[0])
        return real("herramienta", **{**kw, "al_evento": al_evento})
    monkeypatch.setattr(motor, "llamar", espiar)
    conversacion.atender(con)
    actividades = [json.loads(v) for v in vistas]
    assert {"estado": "trabajando", "gesto": "buscar", "rotulo": "Buscando «Ana» en lo que ha leído"} in actividades
    assert actividades[-1] == {"estado": "pensando"}
    # Nunca lo que recibió la herramienta en crudo: sólo estado, gesto y rótulo.
    assert all(set(a) <= {"estado", "gesto", "rotulo", "experto"} for a in actividades)
    fila = con.execute("SELECT estado, actividad FROM turno WHERE rol = 'secretario'").fetchone()
    assert tuple(fila) == ("listo", "")
    [t] = [t for t in conversacion.turnos(con, 1) if t["rol"] == "secretario"]
    assert t["actividad"] is None


def test_un_turno_que_falla_o_se_corta_no_deja_actividad_colgada(falso, monkeypatch):
    monkeypatch.setattr(conversacion, "sistema", lambda: "S")
    con = memoria.conectar()
    conversacion.recibir(con, "hola")

    def caido(prompt, **kw):
        raise motor.MotorCaido("no")
    monkeypatch.setattr(motor, "llamar", caido)
    conversacion.atender(con)
    assert tuple(con.execute("SELECT estado, actividad FROM turno WHERE rol = 'secretario'").fetchone()) == ("error", "")
    hilo = conversacion.hilo_abierto(con)["id"]
    con.execute("INSERT INTO turno (hilo, rol, estado, actividad, creado) VALUES (?,?,?,?,?)",
                (hilo, "secretario", "escribiendo", '{"estado": "pensando"}', memoria.ahora()))
    conversacion.retomar_cortados(con)
    assert con.execute("SELECT COUNT(*) FROM turno WHERE actividad != ''").fetchone()[0] == 0


# ── el turno repetido y lo que se vuelca al journal (C-0185) ─────────────────

def test_al_repetir_el_turno_avisa_y_pide_terminar_sin_rehacer_lo_hecho(falso):
    """Tras un corte se reenviaba el mismo mensaje por `--resume`: el modelo lo
    veía otra vez y podía repetir una tarjeta, una nota o un aviso ya hechos."""
    _abierta("hola", nueva=True)
    eventos = []
    r = _abierta("api_error", al_evento=eventos.append)
    assert {"tipo": "reintento"} in eventos
    assert "no lo repitas" in r.texto and r.texto.endswith("api_error"), "lleva su mensaje por si no se guardó"


def test_al_repetirse_el_turno_la_pantalla_tira_lo_del_intento_cortado(falso, monkeypatch):
    """Seguía enseñando «Déjame mirarlo.» del intento tirado, y con texto la
    pantalla no enseña el rótulo de lo que hace."""
    monkeypatch.setattr(conversacion, "sistema", lambda: "S")
    con = memoria.conectar()
    conversacion.recibir(con, "trozos-y-api_error")
    real = motor.Suscripcion._suelta
    durante = []

    def espiar(self, *a, **k):
        durante.append(tuple(memoria.conectar().execute(
            "SELECT texto, actividad FROM turno WHERE rol = 'secretario'").fetchone()))
        return real(self, *a, **k)
    monkeypatch.setattr(motor.Suscripcion, "_suelta", espiar)
    conversacion.atender(con)
    [(texto, actividad)] = durante
    assert texto == "" and json.loads(actividad)["estado"] == "pensando"
    assert con.execute("SELECT estado FROM turno WHERE rol = 'secretario'").fetchone()[0] == "listo"


def test_un_motor_que_no_avisa_del_reintento_sigue_sirviendo(monkeypatch):
    """`reintento` es opcional en el contrato: quien no lo da contesta igual."""
    class Callado(motor.Motor):
        def llamar(self, prompt, *, modelo, sistema, sesion, nueva, herramientas, esquema, esfuerzo,
                   entorno_extra, persistir, abierta, al_trozo=None, al_evento=None):
            if al_trozo:
                al_trozo("Primer intento.")
            return motor.Respuesta(texto="Entera.", sesion="s", estructurada=None, segundos=0.1, coste=0,
                                   modelo=modelo)
    monkeypatch.setitem(motor.MOTORES, "callado", Callado())
    monkeypatch.setattr(conversacion, "ajustes", lambda: {"motor": "callado"})
    monkeypatch.setattr(conversacion, "sistema", lambda: "S")
    con = memoria.conectar()
    conversacion.recibir(con, "hola")
    conversacion.atender(con)
    fila = con.execute("SELECT texto, estado FROM turno WHERE rol = 'secretario'").fetchone()
    assert tuple(fila) == ("Entera.", "listo")


def test_el_volcado_al_journal_no_saca_lo_que_devolvio_una_herramienta_ni_llaves(falso, capsys):
    _abierta("hola", nueva=True)
    _abierta("api_error con llave")
    err = capsys.readouterr().err
    assert "user/tool_result" in err, "la clase y el tamaño sí: es lo que dice dónde se paró"
    assert "hunter2-largo" not in err and "abcdef0123456789xyz" not in err
