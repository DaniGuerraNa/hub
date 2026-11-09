"""Investigar lo público, aparte y sin las manos del secretario (C-0198 modo 1, decisión 385).

Con un `claude` falso en el PATH que apunta su línea: lo que se prueba es la
línea que de verdad se lanza —sin herramientas, o con sólo buscar y leer en la
web, nunca con el MCP del secretario— y lo que vuelve al chat. Que el `claude`
real busca, lee y respeta el tope con esa línea se midió el 7-nov (ver el
docstring de `motor`).
"""

from __future__ import annotations

import json
import sys
import threading

import pytest

from hub import api
from hub.secretario import conversacion, herramientas, investigar, memoria, motor, servicio, sesiones

FALSO = r'''#!{py}
import json, os, sys
args = sys.argv[1:]
with open(os.environ["REGISTRO"], "a") as f:
    f.write(json.dumps({{"args": args}}) + "\n")
sys.stdin.read()
sid = args[args.index("--session-id") + 1] if "--session-id" in args else "s"
d = {{"type": "result", "result": "ok", "session_id": sid, "total_cost_usd": 0.02,
     "usage": {{"input_tokens": 5, "output_tokens": 2}}}}
if os.environ.get("RESPUESTA"):
    d.update(json.loads(open(os.environ["RESPUESTA"]).read()))
print(json.dumps(d))
sys.exit(1 if d.get("is_error") else 0)
'''


@pytest.fixture
def falso(tmp_path, monkeypatch):
    from hub import tmux
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    (bin_ / "claude").write_text(FALSO.format(py=sys.executable))
    (bin_ / "claude").chmod(0o755)
    registro = tmp_path / "registro.jsonl"
    respuesta = tmp_path / "respuesta.json"
    monkeypatch.setenv("REGISTRO", str(registro))
    monkeypatch.setenv("RESPUESTA", str(respuesta))
    respuesta.write_text("{}")
    monkeypatch.setattr(tmux, "path_de_usuario", lambda: f"{bin_}:/usr/bin:/bin")

    class Falso:
        def lineas(self):
            return [json.loads(l)["args"] for l in registro.read_text().splitlines()] if registro.exists() else []

        def contesta(self, **d):
            respuesta.write_text(json.dumps(d))

    yield Falso()
    motor.soltar()


@pytest.fixture
def con():
    c = memoria.conectar()
    yield c
    c.close()


def _valor(linea: list[str], bandera: str) -> str | None:
    return linea[linea.index(bandera) + 1] if bandera in linea else None


# ── el motor ──────────────────────────────────────────────────────────────────

def test_el_motor_solo_deja_pedir_busqueda_y_lectura_web(falso):
    for prohibidas in [("Bash",), ("WebSearch", "Read"), ("Edit",), ("webfetch",), ("",), "WebSearch"]:
        with pytest.raises(ValueError):
            motor.llamar("hola", modelo="claude-haiku-5", herramientas=False, nativas=prohibidas)
    # Nunca junto a las herramientas del secretario: lo leído no acciona nada.
    with pytest.raises(ValueError):
        motor.llamar("hola", modelo="claude-haiku-5", nativas=("WebSearch",))
    with pytest.raises(ValueError):
        motor.llamar("hola", modelo="claude-haiku-5", herramientas=False, nativas=("WebFetch",), tope_usd=0)
    assert falso.lineas() == []                       # nada de eso llegó a lanzarse

    motor.llamar("hola", modelo="claude-haiku-5", herramientas=False, nativas=("WebSearch", "WebFetch"),
                 tope_usd=0.5, persistir=False)
    [linea] = falso.lineas()
    assert _valor(linea, "--tools") == "WebSearch,WebFetch"
    # Con `dontAsk` y sin permitirlas, se deniegan (medido el 7-nov).
    assert _valor(linea, "--permission-mode") == "dontAsk" and _valor(linea, "--allowedTools") == "WebSearch,WebFetch"
    assert _valor(linea, "--max-budget-usd") == "0.5"
    assert "--mcp-config" not in linea and not any("mcp__secretario" in a for a in linea)
    assert "--setting-sources" in linea and "--strict-mcp-config" in linea
    # WebFetch pide desde esta máquina: ni ella ni la red privada (medido el 7-nov).
    vetadas = _valor(linea, "--disallowedTools").split(",")
    assert {"WebFetch(domain:localhost)", "WebFetch(domain:127.0.0.1)", "WebFetch(domain:*.ts.net)"} <= set(vetadas)

    motor.llamar("hola", modelo="claude-haiku-5", herramientas=False, nativas=("WebSearch",), persistir=False)
    assert "--disallowedTools" not in falso.lineas()[-1]          # sin WebFetch no hace falta


def test_sin_nativas_la_linea_sigue_sin_herramientas(falso):
    motor.llamar("hola", modelo="claude-haiku-5", herramientas=False, persistir=False, sesion="s-1", nueva=True)
    motor.llamar("hola", modelo="claude-haiku-5", sesion="s-2", nueva=True)
    sola, con_mcp = falso.lineas()
    assert sola[:11] == ["-p", "--model", "claude-haiku-5", "--tools", "", "--setting-sources", "",
                          "--strict-mcp-config", "--permission-mode", "dontAsk", "--no-session-persistence"]
    assert "--allowedTools" not in sola and "--max-budget-usd" not in sola and "--disallowedTools" not in sola
    # Con el MCP, lo de siempre: sólo sus herramientas, ninguna de claude.
    assert _valor(con_mcp, "--tools") == "" and _valor(con_mcp, "--allowedTools") == "mcp__secretario"
    assert con_mcp.count("--allowedTools") == 1


def test_un_proceso_abierto_con_otras_nativas_es_otro_proceso():
    clave = []

    class Abierto:
        def __init__(self, linea, entorno, c):
            clave.append(c)
            self.clave, self.usado = c, 0

        def vivo(self):
            return True

        def turno(self, *a, **k):
            return {"type": "result", "result": "ok", "session_id": "s"}

        def cerrar(self):
            pass

    m = motor.Suscripcion()
    kw = dict(modelo="m", sistema=None, sesion="s", nueva=True, herramientas=False, esquema=None, esfuerzo=None,
              entorno_extra={}, persistir=True, tope_usd=None)
    orig = motor._Abierto
    motor._Abierto = Abierto
    try:
        m._en_abierto("a", {"PATH": "/bin"}, {**kw, "nativas": ()})
        m._en_abierto("b", {"PATH": "/bin"}, {**kw, "nativas": ()})
        m._en_abierto("c", {"PATH": "/bin"}, {**kw, "nativas": ("WebFetch",)})
    finally:
        motor._Abierto = orig
    assert len(clave) == 2 and clave[0] != clave[1]


def test_al_agotar_el_tope_se_dice_y_se_apunta_lo_gastado(falso, con):
    falso.contesta(is_error=True, subtype="error_max_budget_usd", terminal_reason="budget_exhausted",
                   result=None, total_cost_usd=0.0276)
    with pytest.raises(motor.TopeAgotado) as exc:
        motor.llamar("hola", modelo="claude-haiku-5", herramientas=False, nativas=("WebSearch",), tope_usd=0.01,
                     trabajo="investigar")
    assert "tope" in str(exc.value) and exc.value.coste == pytest.approx(0.0276)
    fila = con.execute("SELECT coste, ok FROM llamada WHERE trabajo = 'investigar'").fetchone()
    assert (fila["coste"], fila["ok"]) == (pytest.approx(0.0276), 0)


# ── la cola común ─────────────────────────────────────────────────────────────

def test_la_cola_no_pierde_ni_repite_entre_dos_conexiones():
    memoria.conectar().close()
    n = 60
    sacados: list[int] = []
    cerrojo = threading.Lock()
    fallos: list[BaseException] = []

    def poner(desde: int):
        c = memoria.conectar()
        try:
            for i in range(desde, n, 2):
                assert memoria.encolar(c, "cola_prueba", {"i": i}, igual=lambda x: x["i"])
        except BaseException as e:  # noqa: BLE001 — se mira abajo
            fallos.append(e)
        finally:
            c.close()

    def sacar():
        c = memoria.conectar()
        try:
            vacias = 0
            while vacias < 200:
                x = memoria.sacar(c, "cola_prueba")
                if x is None:
                    vacias += 1
                    continue
                with cerrojo:
                    sacados.append(x["i"])
        except BaseException as e:  # noqa: BLE001
            fallos.append(e)
        finally:
            c.close()

    hilos = [threading.Thread(target=poner, args=(0,)), threading.Thread(target=poner, args=(1,)),
             threading.Thread(target=sacar), threading.Thread(target=sacar)]
    for h in hilos:
        h.start()
    for h in hilos:
        h.join(60)
    assert not fallos, fallos
    resto = memoria.leer(memoria.conectar(), "cola_prueba") or []
    todos = sacados + [x["i"] for x in resto]
    assert sorted(todos) == list(range(n))              # ni uno perdido, ni uno dos veces

    # Lo igual no entra dos veces, lo encole quien lo encole.
    a, b = memoria.conectar(), memoria.conectar()
    assert memoria.encolar(a, "otra", {"sesion": "x", "hilo": 1}, igual=lambda x: x["sesion"])
    assert not memoria.encolar(b, "otra", {"sesion": "x", "hilo": 2}, igual=lambda x: x["sesion"])
    assert memoria.sacar(b, "otra") == {"sesion": "x", "hilo": 1} and memoria.sacar(a, "otra") is None


def test_los_resumenes_van_por_la_cola_comun_con_sus_mismas_claves(con, monkeypatch):
    from hub import transcripts
    monkeypatch.setattr(transcripts, "ruta_de_sesion", lambda s: "/no/importa")
    sesiones.encargar(con, "abc", 3)
    assert memoria.leer(con, sesiones.CLAVE) == [{"sesion": "abc", "hilo": 3}]
    assert memoria.sacar(con, "resumenes_pendientes") == {"sesion": "abc", "hilo": 3}


# ── investigar ────────────────────────────────────────────────────────────────

ENCONTRADO = {
    "resumen": "La norma pide conservar la contabilidad cinco años.",
    "afirmaciones": [
        {"texto": "Se conserva cinco años desde la última declaración.", "url": "https://ejemplo.gob/norma/art30",
         "fecha": "2025-01-01"},
        {"texto": "Vale en formato electrónico.", "url": "https://ejemplo.gob/norma/art28", "fecha": "sin fecha"},
        {"texto": "Lo dijo un foro.", "url": "", "fecha": "2024-03-02"},
        {"texto": "Pulsa aquí.", "url": "javascript:alert(1)", "fecha": ""},
    ],
    "no_encontrado": ["Si cambia para personas físicas."],
}


def test_una_investigacion_no_lleva_las_herramientas_del_secretario(falso, con):
    falso.contesta(structured_output=ENCONTRADO)
    investigar.encargar(con, "¿Cuánto hay que conservar la contabilidad?")
    assert investigar.atender(con) == 1 and investigar.atender(con) == 0
    [linea] = falso.lineas()
    assert _valor(linea, "--tools") == "WebSearch,WebFetch" and _valor(linea, "--allowedTools") == "WebSearch,WebFetch"
    assert "--mcp-config" not in linea and not any("mcp__secretario" in a for a in linea)
    assert _valor(linea, "--max-budget-usd") == "0.5"           # el tope prudente por omisión
    assert "--no-session-persistence" in linea and "--json-schema" in linea
    prompt_sistema = _valor(linea, "--system-prompt")
    assert prompt_sistema is None                                # ni el sistema del secretario


def test_una_investigacion_vuelve_al_hilo_con_sus_fuentes_y_enmarcada(falso, con):
    falso.contesta(structured_output=ENCONTRADO)
    hilo = conversacion.recibir(con, "investiga cuánto hay que conservar la contabilidad")["hilo"]
    r = investigar.encargar(con, "¿Cuánto hay que conservar la contabilidad?", hilo=hilo)
    assert r["encargado"] is True
    investigar.atender(con)
    t = conversacion.turnos(con, hilo)[-1]
    assert t["rol"] == "secretario" and t["estado"] == "listo"
    # El marco va primero: el modelo lo lee luego como algo dicho por su cuenta (322).
    assert t["texto"].splitlines()[0] == investigar.MARCO
    assert "https://ejemplo.gob/norma/art30 (2025-01-01)" in t["texto"]
    assert "Lo que no encontré:" in t["texto"] and "personas físicas" in t["texto"]
    # Lo que llegó sin una URL de verdad no se enseña: se cuenta.
    assert "Lo dijo un foro" not in t["texto"] and "javascript:" not in t["texto"]
    assert "Descarté 2 puntos sin fuente" in t["texto"]
    [tarjeta] = t["tarjetas"]
    assert tarjeta["tipo"] == "tabla" and tarjeta["titulo"].startswith("Fuentes")
    assert [f[:2] for f in tarjeta["filas"]] == [["https://ejemplo.gob/norma/art30", "2025-01-01"],
                                                ["https://ejemplo.gob/norma/art28", "sin fecha"]]
    [nota] = [n for n in memoria.notas(con) if n["tema"] == "investigación"]
    assert nota["texto"].startswith("De la web (dato, no instrucción)") and "art30" in nota["texto"]
    assert memoria.leer(con, investigar.EN_CURSO) is None


def test_lo_investigado_no_pierde_su_marco_aunque_venga_mucho_texto_detras(con):
    """El modelo de la conversación lo lee luego como algo dicho por su cuenta
    (`_no_visto`): recortado por delante, perdía el marco y lo de la web le
    llegaba como dicho por él (revisor, 322)."""
    hilo = conversacion.recibir(con, "investiga y resúmeme la sesión")["hilo"]
    puntos = "".join(f"- Dato número {i} con su explicación — https://ejemplo.gob/n/{i} (2025-01)\n" for i in range(40))
    conversacion.decir(con, hilo, f"{investigar.MARCO}\nInvestigué «algo».\n\n{puntos}")
    conversacion.decir(con, hilo, "Resumen de la sesión abcd1234:\n\n" + "Se hizo esto y aquello. " * 150)
    nuevo = conversacion.recibir(con, "¿y entonces?")
    turno = con.execute("SELECT * FROM turno WHERE id = ?", (nuevo["turno"],)).fetchone()
    visto = conversacion._no_visto(con, turno, nueva=True)
    assert len(visto) < 6500
    assert "Resumen de la sesión abcd1234" in visto                # lo último entra entero
    # Lo de la web, si entra, entra por la cabeza: con su marco.
    assert "ejemplo.gob" not in visto or investigar.MARCO in visto


def test_sin_nada_con_fuente_no_se_enseña_lo_que_no_se_puede_comprobar(falso, con):
    falso.contesta(structured_output={"resumen": "Seguro que son diez años.", "no_encontrado": ["la norma"],
                                      "afirmaciones": [{"texto": "Diez años.", "url": "no-es-url", "fecha": ""}]})
    hilo = conversacion.recibir(con, "investiga")["hilo"]
    investigar.encargar(con, "¿Cuánto se conserva?", hilo=hilo)
    investigar.atender(con)
    t = conversacion.turnos(con, hilo)[-1]
    assert "Seguro que son diez años" not in t["texto"] and "No encontré nada con su fuente" in t["texto"]
    assert t["tarjetas"] == [] and not [n for n in memoria.notas(con) if n["tema"] == "investigación"]


def test_si_se_acaba_el_tope_se_dice_en_su_hilo(falso, con):
    falso.contesta(is_error=True, subtype="error_max_budget_usd", terminal_reason="budget_exhausted", result=None,
                   total_cost_usd=0.61)
    hilo = conversacion.recibir(con, "investiga")["hilo"]
    investigar.encargar(con, "Todo sobre todo", hilo=hilo)
    investigar.atender(con)
    texto = conversacion.turnos(con, hilo)[-1]["texto"]
    assert "No terminé de investigar" in texto and "tope" in texto and "0.50" in texto


def test_el_tope_se_cambia_en_secretario_yml(falso, con):
    (memoria.carpeta() / "secretario.yml").write_text("investigar:\n  tope_usd: 1.25\n")
    assert investigar.tope() == 1.25
    investigar.encargar(con, "una")
    investigar.atender(con)
    assert _valor(falso.lineas()[-1], "--max-budget-usd") == "1.25"
    (memoria.carpeta() / "secretario.yml").write_text("investigar:\n  tope_usd: -3\n")
    assert investigar.tope() == investigar.TOPE_USD             # uno que no vale no quita el tope


def test_desde_el_chat_se_encola_y_se_contesta_al_momento(con, monkeypatch):
    monkeypatch.setenv("SECRETARIO_HILO", "7")
    h = herramientas.todas()["investigar"]
    assert h.gesto in herramientas.GESTOS
    r = h.funcion(con, {"pregunta": "¿Qué dice la norma de facturación?"})
    assert r["encargado"] is True and "lo investigo y te lo dejo aquí" in r["nota"]
    # La misma pregunta otra vez no se encola de nuevo.
    assert "ya está en la cola" in h.funcion(con, {"pregunta": "¿qué dice la norma de facturación?"})["nota"]
    [pedido] = memoria.leer(con, investigar.CLAVE)
    assert (pedido["hilo"], pedido["tope_usd"]) == (7, investigar.TOPE_USD)
    assert "error" in h.funcion(con, {"pregunta": "   "})
    # La que se está haciendo tampoco; una de un servicio que murió, sí.
    memoria.poner(con, investigar.EN_CURSO, {"pregunta": "Otra cosa", "desde": memoria.ahora()})
    assert "investigando ahora" in h.funcion(con, {"pregunta": "otra cosa"})["nota"]
    memoria.poner(con, investigar.EN_CURSO, {"pregunta": "Otra cosa", "desde": "2020-01-01T00:00:00+00:00"})
    assert "lo investigo" in h.funcion(con, {"pregunta": "otra cosa"})["nota"]
    # Un modelo que encargase en bucle no multiplica el gasto sin fin.
    for i in range(investigar.MAX_EN_COLA):
        h.funcion(con, {"pregunta": f"pregunta {i}"})
    assert len(memoria.leer(con, investigar.CLAVE)) == investigar.MAX_EN_COLA
    assert "esperando" in h.funcion(con, {"pregunta": "una más"})["error"]
    memoria.quitar(con, investigar.CLAVE)
    # Lo que parece una llave no sale a los buscadores.
    h.funcion(con, {"pregunta": "busca sk-ant-api03-abcdefghijklmnopqrstuvwxyz0123456789"})
    assert "abcdefghijklmnop" not in json.dumps(memoria.leer(con, investigar.CLAVE))


def test_el_servicio_atiende_las_investigaciones_en_el_hilo_de_los_resumenes(monkeypatch):
    memoria.conectar().close()
    parar, hechos = threading.Event(), []
    monkeypatch.setattr(sesiones, "atender", lambda c: hechos.append("resumen") or (1 / 0))   # uno roto no frena
    monkeypatch.setattr(investigar, "atender", lambda c: hechos.append("investigación") or parar.set())
    servicio._bucle_resumenes(parar)
    assert hechos == ["resumen", "investigación"]


def test_la_espera_cuenta_las_investigaciones_en_cola_y_en_curso(con):
    memoria.poner(con, investigar.CLAVE, [{"pregunta": "a"}, {"pregunta": "b"}])
    memoria.poner(con, investigar.EN_CURSO, {"pregunta": "c", "desde": memoria.ahora()})
    e = api.secretario_espera()
    assert (e["investigaciones"], e["investigando"]) == (3, 1)
    memoria.poner(con, investigar.EN_CURSO, {"pregunta": "c", "desde": "2020-01-01T00:00:00+00:00"})
    assert (api.secretario_espera()["investigaciones"], api.secretario_espera()["investigando"]) == (2, 0)


# ── el personaje ──────────────────────────────────────────────────────────────

def test_el_personaje_pinta_la_investigacion_con_el_investigador(tmp_path):
    from arnes_js import ejecutar, script_estatico
    accion = """
      const R = (x) => registro.valores.push('R:' + JSON.stringify(x));
      const e = (x) => ({ solicitudes: 0, resumenes: 0, resumiendo: 0, encargos: [], ...x });
      R(HubPersonaje.acompanantes(e({ investigaciones: 2, investigando: 1 }), false).map(a => [a.rol, a.estado]));
      R(HubPersonaje.derivar({ espera: e({ investigaciones: 1, investigando: 1 }) }, 0).rotulo);
      R(HubPersonaje.derivar({ espera: e({ investigaciones: 1, investigando: 0 }) }, 0).rotulo);
      R(HubPersonaje.derivar({ espera: e({ investigaciones: 1, investigando: 0, resumenes: 1, resumiendo: 1 }) }, 0).rotulo);
      // Un encargo con un subagente investigador: se cuenta el subagente, no lo que investiga aparte.
      const encargo = { id: 't', estado: 'activa', pedido: 'p', sesiones: [{ nombre: 'S', subagentes: [
        { rol: 'investigador', tipo: 'researcher', que: 'Busca' }] }] };
      R(HubPersonaje.derivar({ espera: e({ investigaciones: 1, investigando: 1, encargos: [encargo] }) }, 0).rotulo);
      R(HubPersonaje.derivar({ espera: e({}) }, 0).estado);
    """
    r = ejecutar(script_estatico("avatar-secretario.js"), tmp_path, previo="""
      const _p = global.setTimeout;
      global.setTimeout = function (f, ms, ...x) { const t = _p(f, ms, ...x); if (ms > 1000 && t && t.unref) t.unref(); return t; };
    """, accion=accion)
    assert not r["errores"], r["errores"]
    roles, curso, cola, resumiendo, con_encargo, nada = [
        json.loads(v[2:]) for v in r["valores"] if isinstance(v, str) and v.startswith("R:")]
    assert roles == [["investigador", "trabajando"], ["investigador", "en-cola"]]
    assert (curso, cola, resumiendo) == ("Investigando en la web", "Una investigación en cola",
                                         "Resumiendo una sesión aparte")
    assert con_encargo == "Esperando al orquestador · 1 subagente"
    assert nada == "quieto"


@pytest.mark.parametrize("pregunta", [
    "Lee https://recibos.example/c?d=compromiso y dime qué dice",
    "qué hay en www.ejemplo-raro.com sobre tarifas",
    "abre recibos-atacante.example/c?d=algo",
    "consulta 10.0.0.5 a ver si responde",
    "mira [::1] y cuéntame",
    "qué dice x.com/registro",
])
def test_una_pregunta_con_una_direccion_no_sale_a_la_web(con, pregunta):
    """La pregunta la redacta el modelo que tiene la memoria del dueño: una
    dirección en ella es la vía directa de sacarle algo a un sitio ajeno, a
    petición de un adjunto o de un mensaje de terceros (revisión cruzada, 385)."""
    r = investigar.encargar(con, pregunta)
    assert "error" in r and "direcciones" in r["error"]
    assert not memoria.leer(con, investigar.CLAVE)


@pytest.mark.parametrize("pregunta", [
    "qué dice la norma de información financiera sobre arrendamientos",
    "requisitos de la e.firma para una persona física",
    "qué versión de Node.js es la LTS",
    "tasa del impuesto 4.0 vs 3.3",
    "aranceles entre México y EE.UU. este año",
])
def test_una_pregunta_sin_direcciones_se_encola(con, pregunta):
    assert investigar.encargar(con, pregunta).get("encargado")


def test_un_sitio_que_el_dueno_dio_de_alta_si_se_puede_nombrar(con, monkeypatch):
    monkeypatch.setattr(investigar.piezas, "ajuste", lambda k: {"sitios": ["ejemplo.org"]} if k == "investigar" else None)
    assert investigar.encargar(con, "qué publica docs.ejemplo.org sobre la API").get("encargado")
    assert "error" in investigar.encargar(con, "qué publica otro-ejemplo.net sobre la API")
