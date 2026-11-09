"""Adjuntos que entran en el chat del secretario (decisión 383, C-0196 F1).

Lo que se adjunta cae en el intercambio, de paso, bajo `_secretario/<día>/`;
el mensaje lleva sus rutas, y sólo esas. Las imágenes (y los PDF) los ve el
modelo como bloques **en el mismo proceso abierto** del hilo: nunca dos
procesos escriben una sesión (328). Lo demás va como su ruta, marcado como
dato (322). Con un `claude` falso que habla stream-json, como en
`test_secretario_motor.py`; que el real los ve se midió con haiku el 7-nov.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient

from arnes_js import ejecutar, script_estatico
from hub import db, intercambio, web
from hub.secretario import conversacion, memoria, motor
from test_secretario_motor import FALSO

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32

# El falso de `test_secretario_motor`, que además entiende un mensaje en
# bloques: apunta qué bloques le llegaron y contesta al texto, como el real.
_TEXTO = '        texto = json.loads(linea)["message"]["content"]\n'
assert _TEXTO in FALSO, "el falso de test_secretario_motor cambió: ajusta este parche"
FALSO_CON_BLOQUES = FALSO.replace(_TEXTO, '''        texto = json.loads(linea)["message"]["content"]
        if isinstance(texto, list):
            with open(os.environ["REGISTRO"] + ".bloques", "a") as f:
                f.write(json.dumps({{"pid": os.getpid(), "bloques": [
                    {{"type": b["type"], **({{"media_type": b["source"]["media_type"]}} if "source" in b else {{}})}}
                    for b in texto]}}) + "\\n")
            texto = " ".join(b["text"] for b in texto if b.get("type") == "text")
''')


@pytest.fixture
def falso(tmp_path, monkeypatch):
    from hub import tmux
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    (bin_ / "claude").write_text(FALSO_CON_BLOQUES.format(py=sys.executable))
    (bin_ / "claude").chmod(0o755)
    registro = tmp_path / "registro.jsonl"
    monkeypatch.setenv("REGISTRO", str(registro))
    monkeypatch.setattr(tmux, "path_de_usuario", lambda: f"{bin_}:/usr/bin:/bin")

    def leer(cual=""):
        archivo = registro.with_name(registro.name + cual)
        return [json.loads(l) for l in archivo.read_text().splitlines()] if archivo.exists() else []
    yield leer
    motor.soltar()


@pytest.fixture
def cliente(tmp_path, monkeypatch):
    def conexion():
        c = db.conectar(tmp_path / "hub.db")
        db.inicializar(c)
        return c

    monkeypatch.setattr(web, "conexion", conexion)
    return TestClient(web.app)


def _abierta(prompt, sesion="s-1", nueva=False, **kw):
    return motor.llamar(prompt, modelo="claude-sonnet-5", sesion=sesion, nueva=nueva, herramientas=False,
                        abierta=True, trabajo="conversacion", **kw)


def _foto(tmp_path, nombre="foto.png"):
    ruta = tmp_path / nombre
    ruta.write_bytes(PNG)
    return ruta


# ── la web: guardar y aceptar sólo lo del chat ───────────────────────────────

def test_un_adjunto_del_chat_se_guarda_de_paso_en_el_intercambio(cliente):
    r = cliente.post("/api/secretario/adjuntar", files={"archivo": ("captura de hoy.png", PNG, "image/png")})
    d = r.json()
    assert r.status_code == 200 and d["ok"] and d["imagen"] is True
    assert re.fullmatch(r"_secretario/\d{8}/captura-de-hoy\.png", d["ruta"]), d["ruta"]
    assert (intercambio.carpeta() / d["ruta"]).read_bytes() == PNG
    # De paso: caduca a los diez días, como lo pegado en la terminal (288).
    assert intercambio.caduca_en(d["ruta"]) is not None
    assert cliente.get(f"/intercambio/ver/{d['ruta']}").status_code == 200

    otro = cliente.post("/api/secretario/adjuntar", files={"archivo": ("datos.zip", b"PK..", "application/zip")})
    assert otro.json()["imagen"] is False

    # El mensaje lleva sus rutas, y con adjuntos el texto puede ir vacío.
    m = cliente.post("/api/secretario/mensaje", json={"texto": "", "adjuntos": [d["ruta"], otro.json()["ruta"]]})
    assert m.json()["ok"] is True
    [t] = cliente.get("/api/secretario/turnos").json()["turnos"]
    assert (t["rol"], t["texto"], t["adjuntos"]) == ("dueno", "", [d["ruta"], otro.json()["ruta"]])


def test_un_adjunto_que_no_es_del_chat_no_se_acepta(cliente):
    suelto = intercambio.guardar("suelto.png", PNG)                       # lo subido sin proyecto
    del_tablero = intercambio.guardar("idea.png", PNG, dentro="_tablero/3")
    for ruta in (suelto.name, "_tablero/3/idea.png", "../hub.db", "_secretario/20261107/no-existe.png",
                 str(del_tablero)):
        r = cliente.post("/api/secretario/mensaje", json={"texto": "mira", "adjuntos": [ruta]})
        assert r.status_code == 400 and not r.json()["ok"], ruta
    assert cliente.post("/api/secretario/mensaje", json={"texto": "mira", "adjuntos": "x.png"}).status_code == 400
    assert cliente.post("/api/secretario/mensaje", json={"texto": "", "adjuntos": []}).status_code == 400
    assert cliente.get("/api/secretario/turnos").json()["turnos"] == []


def test_adjuntar_pide_mismo_origen(cliente):
    r = cliente.post("/api/secretario/adjuntar", files={"archivo": ("a.png", PNG, "image/png")},
                     headers={"Origin": "https://malo.example"})
    assert r.status_code == 403
    assert not (intercambio.carpeta() / "_secretario").exists()


def test_lo_pegado_se_llama_igual_en_la_terminal_el_tablero_y_el_chat(cliente, monkeypatch):
    from datetime import datetime

    from hub import ideas

    class Fijo(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 11, 7, 3, 15, 0)

    monkeypatch.setattr(intercambio, "datetime", Fijo)
    terminal = cliente.post("/api/terminal/adjuntar", data={"pegado": "1"},
                            files={"archivo": ("image.png", PNG, "image/png")}).json()["ruta"]
    chat = cliente.post("/api/secretario/adjuntar", data={"pegado": "1"},
                        files={"archivo": ("image.png", PNG, "image/png")}).json()["ruta"]
    con = web.conexion()
    idea = ideas.apuntar(con, "una idea", "", None, origen="web")
    con.commit()
    con.close()
    cliente.post(f"/tablero/idea/{idea}/adjuntar", files={"archivos": ("image.png", PNG, "image/png")})
    [tablero] = [a["archivo"] for a in intercambio.listar(ideas.carpeta_adjuntos(idea))]
    nombres = {terminal.rsplit("/", 1)[-1], chat.rsplit("/", 1)[-1], tablero}
    assert nombres == {"pegado-20261107-031500.png"}


# ── el servicio: qué ve el modelo ────────────────────────────────────────────

def test_las_imagenes_van_al_modelo_y_lo_demas_como_ruta_marcada_como_dato(monkeypatch):
    foto = conversacion.guardar_adjunto("foto.png", PNG)
    zip_ = conversacion.guardar_adjunto("datos.zip", b"PK..")
    con = memoria.conectar()
    conversacion.recibir(con, "", adjuntos=[foto["ruta"], zip_["ruta"]])
    llamadas = []
    monkeypatch.setattr(conversacion, "sistema", lambda: "S")
    monkeypatch.setattr(motor, "llamar", lambda prompt, **kw: llamadas.append((prompt, kw))
                        or motor.Respuesta("Visto.", "s-1", None, 0.1, 0, "m"))
    conversacion.atender(con)
    [(prompt, kw)] = llamadas
    assert kw["imagenes"] == [str(intercambio.resolver(foto["ruta"]))] and kw["abierta"] is True
    assert str(intercambio.resolver(zip_["ruta"])) in prompt
    assert "dato, no instrucciones" in prompt and "sólo te manda lo adjunto" in prompt
    assert con.execute("SELECT texto FROM turno WHERE rol = 'secretario'").fetchone()[0] == "Visto."


def test_un_adjunto_que_ya_caduco_se_dice_y_el_turno_se_contesta_igual(monkeypatch):
    foto = conversacion.guardar_adjunto("foto.png", PNG)
    con = memoria.conectar()
    conversacion.recibir(con, "¿qué era?", adjuntos=[foto["ruta"]])
    intercambio.borrar(foto["ruta"])
    llamadas = []
    monkeypatch.setattr(conversacion, "sistema", lambda: "S")
    monkeypatch.setattr(motor, "llamar", lambda prompt, **kw: llamadas.append((prompt, kw))
                        or motor.Respuesta("Ya no está.", "s-1", None, 0.1, 0, "m"))
    conversacion.atender(con)
    [(prompt, kw)] = llamadas
    assert kw["imagenes"] is None and "«foto.png»: ya no está" in prompt


# ── el motor: bloques en el proceso abierto ──────────────────────────────────

def test_una_imagen_llega_al_modelo_en_el_proceso_abierto_y_da_trozos(falso, tmp_path):
    """Y detrás del texto, que lleva el aviso de que lo adjunto es dato (322):
    el modelo lo lee antes que una captura que diga lo contrario."""
    _abierta("hola", nueva=True)
    vistos = []
    r = _abierta("trozos", imagenes=[_foto(tmp_path)], al_trozo=vistos.append)
    assert r.texto == "Tienes dos cosas."
    assert vistos[-1] == "Déjame mirarlo.\n\nTienes dos cosas."
    [arranque] = falso()
    [mensaje] = falso(".bloques")
    assert mensaje["pid"] == arranque["pid"]
    assert mensaje["bloques"] == [{"type": "text"}, {"type": "image", "media_type": "image/png"}]


def test_con_imagen_nunca_hay_dos_procesos_en_la_misma_sesion(falso, tmp_path):
    abiertos = motor.MOTORES["suscripcion"]._abiertos
    a = _abierta("hola", nueva=True)
    b = _abierta("mira", imagenes=[_foto(tmp_path)])
    assert a.texto.split(":")[0] == b.texto.split(":")[0] and len(falso()) == 1
    # Una llamada suelta con imágenes a la misma sesión cierra antes el abierto.
    proceso = abiertos["s-1"].p
    motor.llamar("suelta", modelo="claude-opus-5-5", sesion="s-1", herramientas=False, imagenes=[_foto(tmp_path)])
    assert proceso.poll() is not None and "s-1" not in abiertos


def test_si_el_proceso_muere_con_imagen_se_repite_con_ella(falso, tmp_path):
    _abierta("hola", nueva=True)
    r = _abierta("muere", imagenes=[_foto(tmp_path)])
    assert r.texto.endswith("muere") and "--resume" in falso()[-1]["args"]
    assert [m["bloques"][-1]["type"] for m in falso(".bloques")] == ["image", "image"]


def test_un_pdf_va_como_documento_y_uno_enorme_solo_por_su_ruta(falso, tmp_path, monkeypatch):
    pdf = tmp_path / "factura.pdf"
    pdf.write_bytes(b"%PDF-1.4 falso")
    _abierta("lee", nueva=True, imagenes=[pdf])
    assert falso(".bloques")[0]["bloques"][-1] == {"type": "document", "media_type": "application/pdf"}
    assert motor.para_el_modelo(pdf) == (14, "")
    (tmp_path / "datos.zip").write_bytes(b"PK..")
    assert motor.para_el_modelo(tmp_path / "datos.zip") == (0, "")
    monkeypatch.setattr(motor, "TOPE_PDF", 5)
    assert motor.para_el_modelo(pdf)[0] == 0 and "MB" in motor.para_el_modelo(pdf)[1]


def test_una_foto_que_no_se_puede_reducir_no_tumba_el_turno_y_se_le_dice(monkeypatch):
    """Sin ffmpeg, la foto de más de 3,5 MB va como ruta con el motivo: el modelo
    contesta lo demás y le cuenta por qué no la vio."""
    from hub import maquina
    foto = conversacion.guardar_adjunto("foto.jpg", b"\xff\xd8" + b"x" * 64)
    monkeypatch.setattr(motor, "TOPE_IMAGEN", 10)
    monkeypatch.setattr(maquina, "encontrar", lambda nombre: None)
    imagenes, lineas = conversacion._adjuntos_para_el_modelo([foto["ruta"]])
    assert imagenes == [] and "no hay ffmpeg" in lineas and "díselo" in lineas


def test_lo_que_pasa_del_tope_del_mensaje_va_solo_por_su_ruta(monkeypatch):
    fotos = [conversacion.guardar_adjunto(f"f{i}.png", PNG)["ruta"] for i in range(3)]
    monkeypatch.setattr(motor, "TOPE_MENSAJE", 2 * len(PNG))
    imagenes, lineas = conversacion._adjuntos_para_el_modelo(fotos)
    assert len(imagenes) == 2 and "no cabe con los demás" in lineas


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="sin ffmpeg no hay qué reducir")
def test_una_imagen_demasiado_grande_se_reduce_con_ffmpeg_y_sin_el_se_dice(falso, tmp_path, monkeypatch):
    grande = tmp_path / "grande.png"
    # Ruido: un PNG que pesa de verdad, como una foto, y en JPEG mucho menos.
    subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i",
                    "nullsrc=s=2000x1400,geq=lum='random(1)*255':cb=128:cr=128", "-frames:v", "1", str(grande)],
                   check=True)
    monkeypatch.setattr(motor, "TOPE_IMAGEN", grande.stat().st_size - 1)
    [bloque] = motor._bloques([grande], "")
    assert bloque["source"]["media_type"] == "image/jpeg"
    from hub import maquina
    monkeypatch.setattr(maquina, "encontrar", lambda nombre: None)
    # Sin ffmpeg no se manda a ciegas, pero tampoco se tumba el turno: el
    # modelo recibe por qué no la ve y se lo dice (revisión cruzada del 7-nov).
    [aviso] = motor._bloques([grande], "")
    assert aviso["type"] == "text" and "ffmpeg" in aviso["text"] and "Díselo" in aviso["text"]


# ── el chat, ejecutado (regla dura 11) ───────────────────────────────────────

CHAT = script_estatico("formato-chat.js") + "\n" + script_estatico("chat-secretario.js")

# Un FormData que se deja leer: el del arnés se serializa vacío.
FORMDATA = """
  global.FormData = class { constructor(){ this.campos = {}; }
    append(k, v, n){ this.campos[k] = typeof v === 'string' ? v : (n || 'blob'); }
    toJSON(){ return this.campos; } };
"""

RUTA = "_secretario/20261107/pegado-20261107-031500.png"


def test_pegar_una_imagen_la_sube_y_la_manda_con_el_mensaje(tmp_path):
    accion = """
      const f = new File([new Uint8Array([137, 80])], 'image.png', { type: 'image/png' });
      let detenido = 0;
      nodo('sec-texto').disparar('paste', { clipboardData: { files: [f], items: [] },
                                            preventDefault(){ detenido++; } });
      nodo('sec-texto').disparar('paste', { clipboardData: { files: [], items: [] },
                                            preventDefault(){ detenido++; } });
      setTimeout(() => {
        registro.valores.push(['miniaturas', nodo('sec-adjuntos').innerHTML]);
        nodo('sec-texto').value = 'mira esto';
        nodo('sec-escribir').disparar('submit', { preventDefault(){} });
        registro.valores.push(['detenido', detenido]);
      }, 2);
    """
    r = ejecutar(CHAT, tmp_path, {"POST /api/secretario/adjuntar": {"ok": True, "ruta": RUTA, "imagen": True},
                                  "POST /api/secretario/mensaje": {"ok": True, "hilo": 1, "turno": 1},
                                  "/api/secretario/turnos": {"hilo": 1, "turnos": []}},
                 previo=FORMDATA, accion=accion)
    assert r["errores"] == []
    [subida] = [e for e in r["enviados"] if e["url"] == "/api/secretario/adjuntar"]
    assert subida["cuerpo"] == {"archivo": "image.png", "pegado": "1"}
    [mensaje] = [e for e in r["enviados"] if e["url"] == "/api/secretario/mensaje"]
    assert mensaje["cuerpo"]["texto"] == "mira esto" and mensaje["cuerpo"]["adjuntos"] == [RUTA]
    # Un pegado de texto no se toca: lo pega el navegador como siempre.
    assert ["detenido", 1] in r["valores"]
    # La miniatura se ve antes de mandar.
    [miniaturas] = [v[1] for v in r["valores"] if isinstance(v, list) and v[0] == "miniaturas"]
    assert f'<img src="/intercambio/ver/{RUTA}"' in miniaturas


def test_el_turno_del_dueno_ensena_lo_que_adjunto(tmp_path):
    respuesta = {"hilo": 1, "turnos": [
        {"id": 1, "rol": "dueno", "texto": "", "estado": "listo", "tarjetas": [],
         "adjuntos": ["_secretario/20261107/foto uno.png", "_secretario/20261107/datos.zip"]}]}
    accion = ("nodo('sec-texto').value = 'x'; nodo('sec-escribir').disparar('submit', {preventDefault(){}});"
              "setTimeout(() => registro.valores.push(['html', "
              "nodo('sec-chat').querySelector('[data-turno=\"1\"]').innerHTML]), 5);")
    r = ejecutar(CHAT, tmp_path, {"POST /api/secretario/mensaje": {"ok": True, "hilo": 1, "turno": 1},
                                  "/api/secretario/turnos": respuesta}, accion=accion)
    assert r["errores"] == []
    html = [v[1] for v in r["valores"] if isinstance(v, list) and v[0] == "html"][-1]
    assert '<img src="/intercambio/ver/_secretario/20261107/foto%20uno.png"' in html
    assert 'href="/intercambio/bajar/_secretario/20261107/datos.zip"' in html


def test_si_un_adjunto_no_sube_el_mensaje_no_sale_sin_avisar(tmp_path):
    accion = """
      const f = new File([new Uint8Array([1])], 'foto.png', { type: 'image/png' });
      nodo('sec-texto').disparar('paste', { clipboardData: { files: [f], items: [] }, preventDefault(){} });
      nodo('sec-texto').value = 'mira esto';
      nodo('sec-escribir').disparar('submit', { preventDefault(){} });
      setTimeout(() => {
        registro.valores.push(['estado', nodo('estado-sec').textContent]);
        // La segunda vez sale, ya sin lo que falló.
        nodo('sec-escribir').disparar('submit', { preventDefault(){} });
      }, 2);
    """
    r = ejecutar(CHAT, tmp_path, {"POST /api/secretario/adjuntar": {"ok": False, "error": "pesa demasiado"},
                                  "POST /api/secretario/mensaje": {"ok": True, "hilo": 1, "turno": 1},
                                  "/api/secretario/turnos": {"hilo": 1, "turnos": []}},
                 previo=FORMDATA, accion=accion)
    assert r["errores"] == []
    [estado] = [v[1] for v in r["valores"] if isinstance(v, list) and v[0] == "estado"]
    assert "no se mandó" in estado and "pesa demasiado" in estado
    mensajes = [e["cuerpo"] for e in r["enviados"] if e["url"] == "/api/secretario/mensaje"]
    assert mensajes == [{"texto": "mira esto", "voz": False}]


def test_lo_soltado_que_la_pagina_ya_reclamo_no_se_sube_al_chat(tmp_path):
    """En /trabajo todo lo soltado va a la terminal: el chat no lo marca ni lo sube."""
    accion = """
      const f = new File([new Uint8Array([1])], 'captura.png', { type: 'image/png' });
      const dt = { files: [f], types: ['Files'] };
      const ev = (reclamado) => ({ dataTransfer: dt, defaultPrevented: reclamado, preventDefault(){} });
      nodo('sec-escribir').disparar('dragover', ev(true));
      nodo('sec-escribir').disparar('drop', ev(true));
      registro.valores.push(['reclamado', nodo('sec-escribir').classList.contains('soltando')]);
      nodo('sec-escribir').disparar('dragover', ev(false));
      registro.valores.push(['libre', nodo('sec-escribir').classList.contains('soltando')]);
      nodo('sec-escribir').disparar('drop', ev(false));
    """
    r = ejecutar(CHAT, tmp_path, {"POST /api/secretario/adjuntar": {"ok": True, "ruta": RUTA, "imagen": True}},
                 previo=FORMDATA, accion=accion)
    assert r["errores"] == []
    assert ["reclamado", False] in r["valores"] and ["libre", True] in r["valores"]
    assert r["peticiones"].count("/api/secretario/adjuntar") == 1
