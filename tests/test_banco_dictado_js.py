"""La pantalla del banco de dictado, ejecutando su JavaScript (regla dura 11).

Va con `grabar.js` delante, como en la página: graba con `HubGrabar`. Lo que
se prueba es lo que verá quien lee: qué frase toca en cada aparato, que al
parar se sube la toma con su frase, su aparato y lo que dio el micrófono, y
que la cuenta sólo sube cuando el hub dice que la guardó.
"""

from __future__ import annotations

import json

from arnes_js import ejecutar, script_estatico

GUION = script_estatico("grabar.js") + "\n" + script_estatico("banco-dictado.js")

DATOS = {
    "aparato": "pc",
    "aparatos": [{"id": "pc", "nombre": "PC", "hechas": 1, "total": 3},
                 {"id": "telefono", "nombre": "Teléfono", "hechas": 0, "total": 3}],
    "frases": [{"id": "x01", "categoria": "corta", "texto": "Uno dos.", "grabada": {"pc": True, "telefono": False}},
               {"id": "x02", "categoria": "tecnica", "texto": "Tres cuatro.", "grabada": {"pc": False, "telefono": False}},
               {"id": "x03", "categoria": "larga", "texto": "Cinco seis siete.",
                "grabada": {"pc": False, "telefono": False}}],
    "categorias": {"corta": "Corta", "tecnica": "Técnica", "larga": "Larga"},
}

GUARDADA = {"POST /api/voz/banco": {"ok": True, "progreso": {"hechas": 2}}}


def previo(ancho: int = 1600, busqueda: str = "", micro: str = "") -> str:
    """Los datos de la página, un micrófono y una grabadora de mentira, y
    `Blob`/`FormData` que anotan qué se sube (los de node tardan en cargar)."""
    return f"""
      nodo('banco-datos').textContent = {json.dumps(json.dumps(DATOS))};
      global.innerWidth = {ancho};
      global.location.search = {json.dumps(busqueda)};
      global.Blob = class {{ constructor(p, o) {{ this.size = 1; this.type = (o && o.type) || ''; }} }};
      global.FormData = class {{
        constructor() {{ registro.campos = {{}}; registro.subidas = (registro.subidas || 0) + 1; }}
        append(k, v) {{ registro.campos[k] = typeof v === 'string' ? v : '(audio)'; }} }};
      navigator.mediaDevices = {{ getUserMedia: (r) => {{ registro.restricciones = r;
        return Promise.resolve({{ getTracks: () => [{{ stop() {{}},
          getSettings: () => ({{ echoCancellation: true, noiseSuppression: true, autoGainControl: false,
                                 sampleRate: 48000, channelCount: 1 }}) }}] }}); }} }};
      global.MediaRecorder = class {{
        constructor() {{ this.mimeType = 'audio/webm'; this._o = {{}}; }}
        addEventListener(ev, fn) {{ (this._o[ev] ||= []).push(fn); }}
        start() {{}}
        stop() {{ (this._o.dataavailable || []).forEach(f => f({{ data: new Blob(['x']) }}));
                  (this._o.stop || []).forEach(f => f({{}})); }} }};
      document.querySelectorAll('[data-elegir-aparato]').forEach((b, i) => {{
        b.dataset.elegirAparato = ['pc', 'telefono'][i]; }});
      document.querySelectorAll('[data-ir]').forEach((b, i) => {{ b.dataset.ir = ['x01', 'x02', 'x03'][i]; }});
      {micro}
    """


VER = """
  const ver = (id) => nodo(id);
  registro.texto = ver('banco-texto').textContent;
  registro.meta = ver('banco-meta').textContent;
  registro.estado = ver('banco-estado').textContent;
  registro.cuenta = ver('banco-cuenta').textContent;
  registro.principal = ver('banco-grabar').hidden ? null : ver('banco-grabar').textContent;
  registro.repetir = !ver('banco-repetir').hidden;
  registro.siguiente = ver('banco-siguiente').hidden ? null : ver('banco-siguiente').textContent;
  registro.siguienteCta = ver('banco-siguiente').classList.contains('cta');
  registro.micro = ver('banco-micro').textContent;
"""


def pasos(cuerpo: str) -> str:
    """Una secuencia de clics, cada uno con una vuelta del bucle: lo de detrás
    (micrófono, grabadora, subida) son promesas ya resueltas, y una vuelta las
    termina todas. Al final, lo que se ve. El arnés vuelca a los 20 ms: con
    una vuelta por clic sobra margen."""
    return ("(async () => { const tic = () => new Promise(r => setTimeout(r, 0));"
            " const pulsar = async (id) => { nodo(id).disparar('click'); await tic(); };"
            + cuerpo + VER + "})().catch(e => registro.errores.push('async: ' + e));")


def test_en_la_pc_arranca_en_la_primera_frase_sin_grabar(tmp_path):
    r = ejecutar(GUION, tmp_path, previo=previo(), accion=pasos(""))
    assert r["errores"] == []
    assert r["texto"] == "Tres cuatro." and r["meta"] == "Técnica · 2 de 3"
    assert r["cuenta"] == "1"
    assert r["principal"] == "Grabar" and r["siguiente"] == "Saltar esta" and not r["siguienteCta"]
    assert r["repetir"] is False


def test_en_un_telefono_elige_el_telefono_por_el_ancho_y_la_direccion_manda(tmp_path):
    r = ejecutar(GUION, tmp_path, previo=previo(ancho=390), accion=pasos(""))
    assert r["errores"] == []
    assert r["texto"] == "Uno dos." and r["cuenta"] == "0"
    r = ejecutar(GUION, tmp_path, previo=previo(ancho=390, busqueda="?aparato=pc"), accion=pasos(""))
    assert r["texto"] == "Tres cuatro." and r["cuenta"] == "1"


def test_grabar_y_parar_sube_la_frase_con_su_aparato_y_lo_que_dio_el_micro(tmp_path):
    r = ejecutar(GUION, tmp_path, previo=previo(), respuestas=GUARDADA, accion=pasos("""
      await pulsar('banco-grabar');
      registro.grabando = nodo('banco-grabar').textContent;
      await pulsar('banco-grabar');
    """))
    assert r["errores"] == []
    assert r["grabando"] == "Parar"
    # Con las restricciones del chat del secretario, que es por donde más se dicta.
    assert r["restricciones"] == {"audio": {"echoCancellation": True, "noiseSuppression": True}}
    assert [e["url"] for e in r["enviados"]] == ["/api/voz/banco"]
    campos = r["campos"]
    assert campos["audio"] == "(audio)" and campos["frase"] == "x02" and campos["aparato"] == "pc"
    assert campos["texto"] == "Tres cuatro."
    assert json.loads(campos["micro"]) == {"echoCancellation": True, "noiseSuppression": True,
                                           "autoGainControl": False, "sampleRate": 48000, "channelCount": 1,
                                           "restricciones": "conversacion"}
    assert r["cuenta"] == "2" and "Guardada" in r["estado"]
    assert r["principal"] is None and r["repetir"] is True
    assert r["siguiente"] == "Siguiente" and r["siguienteCta"]
    assert "48000 Hz" in r["micro"] and "quitar ruido: sí" in r["micro"]


def test_siguiente_va_a_la_que_falta_y_al_final_dice_que_queda_el_otro_aparato(tmp_path):
    r = ejecutar(GUION, tmp_path, previo=previo(), respuestas=GUARDADA, accion=pasos("""
      await pulsar('banco-grabar'); await pulsar('banco-grabar');
      await pulsar('banco-siguiente');
      registro.tercera = nodo('banco-texto').textContent;
      await pulsar('banco-grabar'); await pulsar('banco-grabar');
      await pulsar('banco-siguiente');
    """))
    assert r["errores"] == []
    assert r["tercera"] == "Cinco seis siete."
    assert r["cuenta"] == "3" and r["texto"].startswith("Las 3 frases están grabadas")
    assert "Teléfono" in r["estado"]
    assert r["principal"] is None and r["siguiente"] is None and r["repetir"] is False


def test_repetir_vuelve_a_grabar_la_misma_frase(tmp_path):
    r = ejecutar(GUION, tmp_path, previo=previo(), respuestas=GUARDADA, accion=pasos("""
      await pulsar('banco-grabar'); await pulsar('banco-grabar');
      registro.frases = [registro.campos.frase];
      await pulsar('banco-repetir');
      registro.repitiendo = nodo('banco-grabar').textContent;
      await pulsar('banco-grabar');
      registro.frases.push(registro.campos.frase);
    """))
    assert r["errores"] == []
    assert r["repitiendo"] == "Parar"
    assert r["frases"] == ["x02", "x02"] and r["subidas"] == 2
    assert r["cuenta"] == "2"   # repetir no la cuenta dos veces


def test_saltar_no_la_cuenta_como_grabada(tmp_path):
    r = ejecutar(GUION, tmp_path, previo=previo(), accion=pasos("await pulsar('banco-siguiente');"))
    assert r["errores"] == []
    assert r["texto"] == "Cinco seis siete." and r["cuenta"] == "1"
    assert r["enviados"] == []


def test_si_el_hub_no_la_guarda_lo_dice_y_la_cuenta_no_sube(tmp_path):
    r = ejecutar(GUION, tmp_path, previo=previo(),
                 respuestas={"POST /api/voz/banco": {"ok": False, "error": "la frase cambió"}},
                 accion=pasos("await pulsar('banco-grabar'); await pulsar('banco-grabar');"))
    assert r["errores"] == []
    assert "la frase cambió" in r["estado"] and r["cuenta"] == "1"
    assert r["principal"] == "Grabar" and r["texto"] == "Tres cuatro."


def test_sin_permiso_para_el_micro_lo_dice_y_no_sube_nada(tmp_path):
    sin_permiso = "navigator.mediaDevices = { getUserMedia: () => Promise.reject({ name: 'NotAllowedError' }) };"
    r = ejecutar(GUION, tmp_path, previo=previo(micro=sin_permiso), accion=pasos("await pulsar('banco-grabar');"))
    assert r["errores"] == []
    assert "sin permiso para el micrófono" in r["estado"]
    assert r["principal"] == "Grabar" and r["enviados"] == []


def test_cambiar_de_aparato_cambia_la_cuenta_la_frase_y_los_formularios(tmp_path):
    r = ejecutar(GUION, tmp_path, previo=previo(), accion=pasos("""
      document.querySelectorAll('[data-elegir-aparato]')[1].disparar('click'); await tic();
    """))
    assert r["errores"] == []
    assert r["texto"] == "Uno dos." and r["cuenta"] == "0"
    assert r["valores"][-1] == "telefono"   # borrar y vaciar llevan el aparato que se ve


def test_ir_a_una_ya_grabada_ofrece_repetirla_o_seguir(tmp_path):
    r = ejecutar(GUION, tmp_path, previo=previo(), accion=pasos("""
      document.querySelectorAll('[data-ir]')[0].disparar('click'); await tic();
    """))
    assert r["errores"] == []
    assert r["texto"] == "Uno dos." and r["repetir"] is True
    assert r["siguiente"] == "Siguiente" and r["principal"] is None


# ── mientras se abre el micrófono (lo que marcó el revisor) ──────────────────
# `getUserMedia` tarda: entre el clic y su respuesta la pantalla no puede
# cambiar de frase ni abrir otro micrófono, o se sube una toma con la
# referencia de otra frase.

MICRO_LENTO = """
  registro.abiertos = 0; registro.soltados = 0;
  navigator.mediaDevices = { getUserMedia: (r) => new Promise((ok) => setTimeout(() => {
    registro.abiertos += 1;
    ok({ getTracks: () => [{ stop() { registro.soltados += 1; }, getSettings: () => ({ sampleRate: 48000 }) }] });
  }, 3)) };
"""


def test_mientras_se_abre_el_micro_no_se_cambia_de_frase_ni_de_aparato(tmp_path):
    r = ejecutar(GUION, tmp_path, previo=previo(micro=MICRO_LENTO), respuestas=GUARDADA, accion=pasos("""
      nodo('banco-grabar').disparar('click');
      nodo('banco-siguiente').disparar('click');
      document.querySelectorAll('[data-ir]')[2].disparar('click');
      document.querySelectorAll('[data-elegir-aparato]')[1].disparar('click');
      nodo('banco-grabar').disparar('click');
      await new Promise(r => setTimeout(r, 6));
      registro.enPantalla = nodo('banco-texto').textContent;
      registro.boton = nodo('banco-grabar').textContent;
      await pulsar('banco-grabar');
    """))
    assert r["errores"] == []
    assert r["enPantalla"] == "Tres cuatro." and r["boton"] == "Parar"
    assert r["abiertos"] == 1
    assert r["campos"]["frase"] == "x02" and r["campos"]["texto"] == "Tres cuatro." and r["campos"]["aparato"] == "pc"


def test_dos_toques_a_repetir_abren_un_solo_micro(tmp_path):
    r = ejecutar(GUION, tmp_path, previo=previo(micro=MICRO_LENTO), respuestas=GUARDADA, accion=pasos("""
      document.querySelectorAll('[data-ir]')[0].disparar('click'); await tic();
      nodo('banco-repetir').disparar('click'); nodo('banco-repetir').disparar('click');
      await new Promise(r => setTimeout(r, 6));
      await pulsar('banco-grabar');
    """))
    assert r["errores"] == []
    assert r["abiertos"] == 1 and r["soltados"] == 1 and r["subidas"] == 1
    assert r["campos"]["frase"] == "x01"


def test_una_toma_que_corta_el_tope_no_se_guarda_y_se_ofrece_repetirla(tmp_path):
    tope_corto = "const _st = global.setTimeout; global.setTimeout = (f, ms, ...x) => _st(f, ms === 90000 ? 2 : ms, ...x);"
    r = ejecutar(GUION, tmp_path, previo=previo(micro=tope_corto), respuestas=GUARDADA, accion=pasos("""
      await pulsar('banco-grabar');
      await new Promise(r => setTimeout(r, 6));
    """))
    assert r["errores"] == []
    assert r["enviados"] == [] and r["cuenta"] == "1"
    assert "90 s" in r["estado"] and "no la guardé" in r["estado"]
    assert r["principal"] == "Grabar"
