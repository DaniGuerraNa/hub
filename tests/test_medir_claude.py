"""El arnés de `scripts/medir_claude.py` (C-0327).

Con un `claude` falso en el PATH, que contesta `--version`, `--help` y `-p`
hablando de verdad con la API falsa del banco. La suite prueba el arnés —el
aislamiento, la lista cerrada, la tabla, que nada se escape—; las mediciones
se validan corriéndolo contra la CLI instalada (la tabla está en la ficha).
"""

from __future__ import annotations

import ast
import http.client
import importlib.util
import json
import os
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

from hub import config, modelos, tmux

RAIZ = Path(__file__).resolve().parents[1]
GUION = RAIZ / "scripts" / "medir_claude.py"


def _cargar():
    spec = importlib.util.spec_from_file_location("medir_claude", GUION)
    modulo = importlib.util.module_from_spec(spec)
    sys.modules["medir_claude"] = modulo
    spec.loader.exec_module(modulo)
    return modulo


medir = _cargar()

FALSO = r'''#!{py}
import json, os, sys, urllib.request
args = sys.argv[1:]
with open(os.environ["MEDIR_FALSO_REGISTRO"], "a") as f:
    f.write(json.dumps({{"args": args, **{{k: os.environ.get(v) for k, v in (
        ("home", "HOME"), ("socket", "HUB_TMUX_SOCKET"), ("base", "ANTHROPIC_BASE_URL"),
        ("llave", "ANTHROPIC_API_KEY"), ("hub_home", "HUB_HOME"), ("tmux", "TMUX"),
        ("sesion_de_claude", "CLAUDECODE"))}}}}) + "\n")
if "--version" in args:
    print("9.8.7 (Claude Code)")
    sys.exit(0)
if "--help" in args:
    print("Usage: claude [options]")
    for b in os.environ.get("MEDIR_FALSO_AYUDA", "").split(","):
        print(f"  {{b}} <valor>   lo que hace")
    sys.exit(0)
if "-p" in args:
    prompt = sys.stdin.read()
    modelo = args[args.index("--model") + 1]
    sid = args[args.index("--session-id") + 1] if "--session-id" in args else args[args.index("--resume") + 1]
    base = os.environ.get("ANTHROPIC_BASE_URL")
    if base:
        cuerpo = {{"model": modelo, "stream": False, "max_tokens": 10,
                  "messages": [{{"role": "user", "content": prompt}}]}}
        pet = urllib.request.Request(base + "/v1/messages", data=json.dumps(cuerpo).encode(),
                                     headers={{"content-type": "application/json",
                                              "user-agent": "claude-cli/9.8.7 (falso)"}})
        d = json.load(urllib.request.urlopen(pet, timeout=10))
        texto = "".join(b.get("text", "") for b in d["content"] if b.get("type") == "text")
        uso = d["usage"]
    else:
        texto, uso = "vale", {{"input_tokens": 3, "output_tokens": 1}}
    print(json.dumps({{"type": "result", "subtype": "success", "is_error": False, "result": texto,
                      "session_id": sid, "total_cost_usd": 0.0015, "usage": uso}}))
    sys.exit(0)
sys.exit(3)
'''


@pytest.fixture
def falso(tmp_path, monkeypatch):
    """La ruta del `claude` falso y lo que fue apuntando, una línea por llamada."""
    carpeta = tmp_path / "falso"
    carpeta.mkdir()
    claude = carpeta / "claude"
    claude.write_text(FALSO.format(py=sys.executable), encoding="utf-8")
    claude.chmod(0o755)
    registro = tmp_path / "registro.jsonl"
    registro.touch()
    monkeypatch.setenv("MEDIR_FALSO_REGISTRO", str(registro))
    monkeypatch.setenv("MEDIR_FALSO_AYUDA", ",".join(sorted(medir.banderas_del_hub())))

    def llamadas():
        return [json.loads(l) for l in registro.read_text(encoding="utf-8").splitlines() if l.strip()]

    return SimpleNamespace(ruta=claude, llamadas=llamadas)


def _pasa(m):
    return lambda b: "bien"


def test_la_tabla_lleva_la_version_y_un_resultado_por_medicion(falso):
    r = medir.correr(["L1", "L2", "F1", "N3"], claude=falso.ruta)
    assert [x.id for x in r] == ["L1", "L2", "F1", "N3"]
    assert r.version == "9.8.7"
    assert {x.id: x.estado for x in r} == {"L1": "pasa", "L2": "pasa", "F1": "pasa", "N3": "no medido"}
    t = medir.tabla(r, r.version)
    assert "Claude Code 9.8.7" in t
    assert "3 pasan · 0 fallan · 1 sin medir" in t
    for x in r:
        assert any(linea.startswith(x.id + " ") for linea in t.splitlines()), x.id
    assert "Intentó salir de la máquina (cortado en el proxy): nada" in t


def test_sin_pedirlas_no_corren_las_del_modelo_ni_las_lentas(falso, monkeypatch):
    M = medir.Medicion
    monkeypatch.setattr(medir, "MEDICIONES", (
        M("L1", "a", "x", medir.LOCAL, _pasa(1)), M("F1", "b", "x", medir.API_FALSA, _pasa(2)),
        M("F15", "c", "x", medir.API_FALSA, _pasa(3), lenta=True), M("M1", "d", "x", medir.MODELO, _pasa(4)),
        M("N1", "e", "x", medir.SIN_MEDIR, medir._sin_medir("porque sí"))))
    assert [x.id for x in medir.correr(claude=falso.ruta)] == ["L1", "F1", "N1"]
    # Nombradas sin su bandera, se dicen en vez de callarse.
    r = {x.id: (x.estado, x.detalle) for x in medir.correr(["M1", "F15"], claude=falso.ruta)}
    assert r == {"M1": ("no medido", "va con --con-modelo"), "F15": ("no medido", "va con --lentas")}


def test_una_bandera_que_falta_en_la_ayuda_se_nombra(falso, monkeypatch):
    todas = sorted(medir.banderas_del_hub())
    monkeypatch.setenv("MEDIR_FALSO_AYUDA", ",".join(b for b in todas if b != "--max-budget-usd"))
    [r] = medir.correr(["L2"], claude=falso.ruta)
    # Es aviso, no fallo: hay banderas que funcionan sin salir en la ayuda.
    assert r.estado == "pasa"
    assert "no salen: --max-budget-usd" in r.detalle
    monkeypatch.setenv("MEDIR_FALSO_AYUDA", ",".join(todas))
    [r] = medir.correr(["L2"], claude=falso.ruta)
    assert r.detalle == f"las {len(todas)} salen en la ayuda"


def test_una_medicion_que_revienta_no_tumba_las_demas(falso, monkeypatch):
    def revienta(b):
        raise KeyError("lo que la CLI ya no trae")

    def falla(b):
        raise medir.Falla("no casa")

    def no_se_sabe(b):
        raise medir.NoMedido("el control no pasó")

    M = medir.Medicion
    monkeypatch.setattr(medir, "MEDICIONES", (
        M("L1", "a", "x", medir.LOCAL, revienta), M("L2", "b", "x", medir.LOCAL, falla),
        M("L3", "c", "x", medir.LOCAL, no_se_sabe), M("L4", "d", "x", medir.LOCAL, _pasa(1))))
    r = {x.id: x for x in medir.correr(claude=falso.ruta)}
    assert [r[i].estado for i in ("L1", "L2", "L3", "L4")] == ["falla", "falla", "no medido", "pasa"]
    # Una que revienta cuenta como falla, para que la salida no sea 0 en silencio.
    assert "reventó" in r["L1"].detalle and "KeyError" in r["L1"].detalle


def test_sin_claude_en_el_path_sale_con_2_y_lo_dice(tmp_path, monkeypatch, capsys):
    vacia = tmp_path / "sin-nada"
    vacia.mkdir()
    monkeypatch.setenv("PATH", str(vacia))
    assert medir.main(["--solo", "L1"]) == 2
    assert "no encuentro `claude`" in capsys.readouterr().out
    assert medir.main(["--claude", str(tmp_path / "no-existe"), "--solo", "L1"]) == 2
    assert "no es un ejecutable" in capsys.readouterr().out


def test_nunca_usa_el_home_ni_el_tmux_de_quien_lo_corre(falso, monkeypatch):
    # Como si lo corriera desde una sesión de Claude Code y dentro de su tmux.
    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.setenv("TMUX", "/tmp/tmux-de-quien-lo-corre,1,0")
    antes = dict(os.environ)
    hub_home_antes = config.HUB_HOME
    medir.correr(["L1", "F1"], claude=falso.ruta)
    llamadas = falso.llamadas()
    assert llamadas
    for ll in llamadas:
        assert ll["home"] != antes["HOME"]
        assert "/hub-medir-" in ll["home"] and ll["home"].endswith("/home")
        assert ll["hub_home"] != antes["HUB_HOME"] and "/hub-medir-" in ll["hub_home"]
        assert ll["socket"] == f"hub-medir-{os.getpid()}"
        assert ll["tmux"] is None and ll["sesion_de_claude"] is None
    # Y todo vuelve a su sitio al acabar.
    assert dict(os.environ) == antes
    assert config.HUB_HOME == hub_home_antes
    assert not Path(llamadas[0]["home"]).exists(), "el HOME temporal se queda"


def test_sin_su_tmux_aparte_no_mide(falso, monkeypatch):
    antes = dict(os.environ)
    monkeypatch.setattr(tmux, "orden_base", lambda: ["tmux"])
    with pytest.raises(RuntimeError, match="servidor aparte"):
        medir.Banco(falso.ruta)
    assert dict(os.environ) == antes


def test_sin_con_modelo_toda_llamada_va_a_la_api_falsa(falso):
    r = {x.id: x for x in medir.correr(["F1", "F7"], claude=falso.ruta)}
    assert r["F1"].estado == "pasa", r["F1"].detalle
    assert r["F7"].estado == "pasa", r["F7"].detalle
    con_p = [ll for ll in falso.llamadas() if "-p" in ll["args"]]
    assert len(con_p) == 1 + len(modelos.PERMITIDOS | modelos.A_PETICION)
    for ll in con_p:
        assert ll["base"].startswith("http://127.0.0.1:")
        assert ll["llave"].startswith("sk-ant-api03-relleno-")


def test_un_modelo_a_peticion_no_se_llama_sin_nombrarlo(falso, tmp_path, monkeypatch):
    # «La sesión de quien lo corre» es aquí una carpeta de la prueba.
    casa = tmp_path / "casa-de-quien-lo-corre"
    casa.mkdir()
    monkeypatch.setenv("HOME", str(casa))

    def modelos_llamados():
        return [ll["args"][ll["args"].index("--model") + 1] for ll in falso.llamadas() if "-p" in ll["args"]]

    [r] = medir.correr(["M2"], claude=falso.ruta)
    assert r.estado == "no medido" and modelos_llamados() == []

    [r] = medir.correr(["M2"], con_modelo=True, claude=falso.ruta)
    assert r.estado == "pasa", r.detalle
    assert sorted(modelos_llamados()) == sorted(modelos.PERMITIDOS)
    assert all(ll["home"] == str(casa) and ll["base"] is None for ll in falso.llamadas() if "-p" in ll["args"])

    [r] = medir.correr(["M2"], con_modelo=True, a_peticion=("claude-fable-5-2",), claude=falso.ruta)
    assert "claude-fable-5-2" in modelos_llamados()
    with pytest.raises(ValueError):
        medir.correr(["M2"], con_modelo=True, a_peticion=("claude-sonnet-5",), claude=falso.ruta)


def test_la_api_falsa_solo_escucha_en_127_0_0_1():
    una, otra = medir.ApiFalsa(), medir.ApiFalsa()
    try:
        assert una.srv.server_address[0] == "127.0.0.1"
        assert una.puerto and una.puerto != otra.puerto, "el puerto es efímero, no fijo"
        marca = medir.nueva_marca("T")
        una.preparar(marca, medir.Plan(texto=f"hola {marca}"))
        c = http.client.HTTPConnection("127.0.0.1", una.puerto, timeout=5)
        c.request("POST", "/v1/messages", json.dumps({"model": "m", "messages": [
            {"role": "user", "content": [{"type": "text", "text": f"pregunta {marca}"}]}]}))
        d = json.loads(c.getresponse().read())
        assert d["content"] == [{"type": "text", "text": f"hola {marca}"}]
        assert [p.marca for p in una.peticiones] == [marca]
        # Hace de proxy que no deja salir: lo rechaza y lo apunta.
        c = http.client.HTTPConnection("127.0.0.1", una.puerto, timeout=5)
        c.request("CONNECT", "api.ejemplo.com:443")
        assert c.getresponse().status == 403
        assert una.salidas == ["api.ejemplo.com:443"]
    finally:
        una.cerrar()
        otra.cerrar()


def test_la_api_falsa_contesta_a_la_ultima_marca_del_usuario():
    """Una conversación de varios turnos lleva delante las marcas de los
    anteriores, y al retomar tras un turno sin respuesta la CLI junta los dos
    prompts en un mensaje (medido con 2.1.322): manda la última."""
    api = medir.ApiFalsa()
    try:
        vieja, nueva = medir.nueva_marca("A"), medir.nueva_marca("B")
        api.preparar(vieja, medir.Plan(texto="la vieja"))
        api.preparar(nueva, medir.Plan(texto="la nueva"))
        mensajes = [{"role": "user", "content": f"{vieja}"},
                    {"role": "assistant", "content": [{"type": "text", "text": f"Respuesta. {vieja}"}]},
                    {"role": "user", "content": [{"type": "text", "text": f"{vieja}"},
                                                 {"type": "text", "text": f"{nueva}"}]}]
        c = http.client.HTTPConnection("127.0.0.1", api.puerto, timeout=5)
        c.request("POST", "/v1/messages", json.dumps({"model": "m", "messages": mensajes}))
        assert json.loads(c.getresponse().read())["content"][0]["text"] == "la nueva"
        assert [p.marca for p in api.peticiones] == [nueva]
    finally:
        api.cerrar()


#: Lo que escribe en un panel sin pasar por `entrega.entregar`.
_ESCRIBEN = {"pegar_en_panel", "enter_en_panel", "tecla_en_panel", "despachar", "enviar", "enviar_comando",
             "responder_confirmacion", "relanzar_panel", "escribir_titulo"}


def test_el_guion_solo_escribe_en_paneles_por_entrega():
    arbol = ast.parse(GUION.read_text(encoding="utf-8"))
    atributos = [(n.value.id if isinstance(n.value, ast.Name) else "", n.attr)
                 for n in ast.walk(arbol) if isinstance(n, ast.Attribute)]
    assert not [a for _, a in atributos if a in _ESCRIBEN], "escribe en un panel por otra puerta"
    assert ("tmux", "_correr") not in atributos, "manda órdenes a tmux por su cuenta"
    assert ("entrega", "entregar") in atributos, "el vigía ya no ve la puerta"
    textos = [n.value for n in ast.walk(arbol) if isinstance(n, ast.Constant) and isinstance(n.value, str)]
    assert not [t for t in textos if any(o in t for o in ("send-keys", "paste-buffer", "load-buffer"))]
    # Ni un `tmux` lanzado a mano (`subprocess.run(["tmux", …])`): sólo por
    # las primitivas del hub.
    lanzados = [n for n in ast.walk(arbol) if isinstance(n, ast.Call)
                for a in n.args if isinstance(a, ast.List) and a.elts
                and isinstance(a.elts[0], ast.Constant) and a.elts[0].value == "tmux"]
    assert not lanzados


def test_las_banderas_medidas_son_las_que_el_hub_pasa(tmp_path):
    from hub.secretario import motor
    banderas = medir.banderas_del_hub()
    entorno = {"PATH": os.environ["PATH"]}
    s = motor.Suscripcion()
    lineas = [
        s._linea(entorno, modelo="claude-haiku-4-5", sistema="x", sesion=None, nueva=True, herramientas=False,
                 esquema={"type": "object"}, esfuerzo="low", entorno_extra={}, persistir=False,
                 nativas=("WebSearch", "WebFetch"), tope_usd=0.5)[0],
        s._linea(entorno, modelo="claude-haiku-4-5", sistema=None, sesion=str(uuid.uuid4()), nueva=False,
                 herramientas=True, esquema=None, esfuerzo=None, entorno_extra={}, persistir=True)[0],
        modelos.linea_claude("claude-sonnet-5", esfuerzo="high", permisos="default",
                             reanudar=str(uuid.uuid4()), prompt="hola").comando.split(),
    ]
    pasadas = {a for linea in lineas for a in linea if a.startswith("--")}
    assert pasadas <= banderas, f"el hub pasa banderas que no se miden: {sorted(pasadas - banderas)}"
    # Las de los otros caminos del motor (stream-json, proceso abierto) también.
    assert {"--output-format", "--verbose", "--include-partial-messages", "--input-format"} <= banderas
    # Las que sólo se nombran en un docstring no son del hub.
    assert "--bare" not in banderas
