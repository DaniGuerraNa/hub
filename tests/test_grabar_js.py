"""Dictar en el teléfono, ejecutando el JavaScript (regla dura 11).

Lo que importa probar es la promesa del archivo: **el texto se pega en el
campo y no se manda nada**. Una transcripción equivocada en una orden que se
ejecuta sin nadie delante es el error que no se ve hasta que ya pasó.
"""

from __future__ import annotations

import re

import pytest

from arnes_js import ESTATICOS, MICROFONO_VIVO, PLANTILLAS, ejecutar, script_estatico

GUION = script_estatico("grabar.js")

# Un micrófono y una grabadora de mentira: `stop` entrega un trozo y dispara el
# evento, que es lo que hace el navegador de verdad.
MICROFONO = """
  navigator.mediaDevices = { getUserMedia: () => Promise.resolve({
    getTracks: () => [{ stop(){ registro.pistas = (registro.pistas || 0) + 1; } }] }) };
  global.MediaRecorder = class {
    constructor(flujo) { this.mimeType = 'audio/webm'; this._o = {}; }
    addEventListener(ev, fn) { (this._o[ev] ||= []).push(fn); }
    start() { registro.grabando = true; }
    stop() {
      (this._o.dataavailable || []).forEach(f => f({ data: new Blob(['x']) }));
      (this._o.stop || []).forEach(f => f({}));
    }
  };
  document.querySelectorAll('[data-grabar]').forEach((b, i) => {
    b.dataset.grabar = 'destino-' + i;
    b.dataset.grabarEstado = 'estado-' + i;
    b.dataset.grabarOrigen = 'origen-' + i;
  });
"""

PULSAR_DOS_VECES = """
  const b = document.querySelectorAll('[data-grabar]')[0];
  b.disparar('click');
  setTimeout(() => b.disparar('click'), 5);
  setTimeout(() => {
    registro.texto = nodo('destino-0').value;
    registro.origen = nodo('origen-0').value;
    registro.estado = nodo('estado-0').textContent;
  }, 15);
"""


def test_arranca_sin_reventar(tmp_path):
    assert ejecutar(GUION, tmp_path)["errores"] == []


def test_lo_dictado_se_pega_en_el_campo_y_no_se_manda(tmp_path):
    r = ejecutar(GUION, tmp_path, previo=MICROFONO, accion=PULSAR_DOS_VECES,
                 respuestas={"POST /orquestador/audio": {"ok": True, "texto": "revisa alfa"}})

    assert r["errores"] == []
    assert r["texto"] == "revisa alfa"
    assert r["origen"] == "audio"
    assert "Revísalo" in r["estado"]
    # Una sola petición, y es la de transcribir: nada va a /orquestador/tarea.
    assert [e["url"] for e in r["enviados"]] == ["/orquestador/audio"]
    assert r["pistas"] == 1   # el micrófono se suelta al terminar


def test_si_no_se_pudo_transcribir_se_dice_y_el_campo_no_cambia(tmp_path):
    r = ejecutar(GUION, tmp_path, previo=MICROFONO, accion=PULSAR_DOS_VECES,
                 respuestas={"POST /orquestador/audio": {"ok": False, "error": "sin transcriptor"}})

    assert r["texto"] == ""
    assert "sin transcriptor" in r["estado"]


def test_sin_microfono_lo_dice_en_vez_de_callar(tmp_path):
    """Sin HTTPS el navegador no da micrófono: se dice, no se queda mudo."""
    r = ejecutar(GUION, tmp_path, previo="""
      document.querySelectorAll('[data-grabar]').forEach((b, i) => {
        b.dataset.grabarEstado = 'estado-' + i; });
    """, accion="""
      document.querySelectorAll('[data-grabar]')[0].disparar('click');
      setTimeout(() => { registro.estado = nodo('estado-0').textContent; }, 5);
    """)

    assert "HTTPS" in r["estado"]


def test_el_tablero_dicta_contra_su_url_y_el_orquestador_sigue_en_la_suya(tmp_path):
    """C-0149: `data-grabar-url` lleva el audio a /api/voz (`transcribir.dictado`,
    que borra el audio al salir bien); sin él, como siempre, /orquestador/audio."""
    r = ejecutar(GUION, tmp_path, previo=MICROFONO + """
      document.querySelectorAll('[data-grabar]')[0].dataset.grabarUrl = '/api/voz';
    """, accion=PULSAR_DOS_VECES, respuestas={"POST /api/voz": {"ok": True, "texto": "una idea dictada"}})
    assert r["errores"] == []
    assert r["texto"] == "una idea dictada"
    assert [e["url"] for e in r["enviados"]] == ["/api/voz"]


def test_al_vaciarse_el_formulario_lo_siguiente_ya_no_sale_como_dictado(tmp_path):
    """C-0233: «Encolar» ya no recarga, y `sin-recarga.js` vacía el formulario
    con `reset()`. El origen es un campo oculto y `reset()` no lo devuelve —su
    valor ES su atributo—: la tarea siguiente, tecleada, salía «dictada», y
    el «Revísalo antes de mandarlo» se quedaba hablando de lo ya mandado."""
    r = ejecutar(GUION, tmp_path, previo=MICROFONO + """
      nodo('origen-0').value = 'texto';
      document.querySelectorAll('[data-grabar]')[0].form = nodo('formulario-0');
    """, accion="""
      const b = document.querySelectorAll('[data-grabar]')[0];
      b.disparar('click');
      setTimeout(() => b.disparar('click'), 3);
      setTimeout(() => {
        registro.antes = nodo('origen-0').value;
        nodo('formulario-0').disparar('reset');
        registro.despues = nodo('origen-0').value;
        registro.estado = nodo('estado-0').textContent;
      }, 12);
    """, respuestas={"POST /orquestador/audio": {"ok": True, "texto": "revisa alfa"}})

    assert r["errores"] == []
    assert r["antes"] == "audio"
    assert r["despues"] == "texto"
    assert r["estado"] == ""


def test_el_dictado_manda_quien_lo_pide_para_medirlo_y_sin_el_no_manda_nada(tmp_path):
    """C-0246: `/api/voz` mide cada dictado por origen; el orquestador no lo lleva."""
    previo = MICROFONO + """
      global.FormData = class { constructor(){ registro.campos = registro.campos || []; }
        append(k, v){ registro.campos.push(k); } };
      document.querySelectorAll('[data-grabar]')[0].dataset.grabarQuien = 'tablero';
    """
    r = ejecutar(GUION, tmp_path, previo=previo, accion=PULSAR_DOS_VECES,
                 respuestas={"POST /orquestador/audio": {"ok": True, "texto": "x"}})
    assert r["errores"] == []
    assert r["campos"] == ["audio", "origen"]

    r = ejecutar(GUION, tmp_path, previo=previo.replace("dataset.grabarQuien = 'tablero'", "dataset.otra = 'x'"),
                 accion=PULSAR_DOS_VECES, respuestas={"POST /orquestador/audio": {"ok": True, "texto": "x"}})
    assert r["campos"] == ["audio"]


def test_si_la_subida_falla_una_vez_se_reintenta_sola_y_no_se_pierde_lo_dictado(tmp_path):
    """C-0287: un corte de red de un segundo costaba lo dictado entero."""
    # `Blob` y `FormData` de mentira: los de node tardan ~15 ms en cargarse la
    # primera vez y el reintento no llegaba antes de que el arnés volcara.
    previo = MICROFONO + """
      global.Blob = class { constructor(p){ this.partes = p; this.size = 1; } };
      global.FormData = class { append(k, v){ this[k] = v; } };
      let fallos = 1; const _fetch = global.fetch;
      global.fetch = (url, o) => {
        if (fallos > 0) { fallos -= 1; registro.fallidas = (registro.fallidas || 0) + 1;
                          return Promise.reject(new TypeError('Failed to fetch')); }
        return _fetch(url, o); };
      const _st = global.setTimeout; global.setTimeout = (f, ms) => _st(f, ms === 1500 ? 2 : ms);
    """
    r = ejecutar(GUION, tmp_path, previo=previo, accion=PULSAR_DOS_VECES,
                 respuestas={"POST /orquestador/audio": {"ok": True, "texto": "revisa alfa"}})
    assert r["errores"] == []
    assert r["fallidas"] == 1
    assert r["texto"] == "revisa alfa"


def test_el_dictado_del_tablero_calienta_el_whisper_al_empezar_y_el_del_orquestador_no(tmp_path):
    """C-0292: sólo /api/voz tiene el Whisper cargado; /orquestador/audio va por su camino."""
    r = ejecutar(GUION, tmp_path, previo=MICROFONO + """
      document.querySelectorAll('[data-grabar]')[0].dataset.grabarUrl = '/api/voz';
    """, accion=PULSAR_DOS_VECES, respuestas={"POST /api/voz": {"ok": True, "texto": "una idea"}})
    assert r["errores"] == []
    assert [p for p in r["peticiones"]] == ["/api/voz/calentar", "/api/voz"]
    r = ejecutar(GUION, tmp_path, previo=MICROFONO, accion=PULSAR_DOS_VECES,
                 respuestas={"POST /orquestador/audio": {"ok": True, "texto": "revisa alfa"}})
    assert "/api/voz/calentar" not in r["peticiones"]


# ── HubGrabar: un solo grabador para todo el hub (C-0311) ────────────────────
# La API que comparten el dictado declarativo (`data-grabar`) y el banco de
# dictado; el chat y la terminal se mudarán a ella. Lo que se prueba es su
# contrato: con qué restricciones abre el micrófono, qué entrega al parar, por
# qué no hay micrófono y qué devuelve al subir.

MICRO_CON_AJUSTES = """
  registro.restricciones = [];
  navigator.mediaDevices = { getUserMedia: (r) => { registro.restricciones.push(r);
    return Promise.resolve({ getTracks: () => [{
      getSettings: () => ({ echoCancellation: true, noiseSuppression: false, sampleRate: 48000 }),
      stop(){ registro.pistas = (registro.pistas || 0) + 1; } }] }); } };
  global.MediaRecorder = class {
    constructor(flujo) { this.mimeType = 'audio/webm'; this._o = {}; }
    addEventListener(ev, fn) { (this._o[ev] ||= []).push(fn); }
    start() { registro.grabando = true; }
    stop() {
      (this._o.dataavailable || []).forEach(f => f({ data: new Blob(['x']) }));
      (this._o.stop || []).forEach(f => f({}));
    }
  };
"""


def _api(cuerpo: str) -> str:
    """Una acción asíncrona sobre la API: lo que falle dentro sale en `errores`."""
    return "(async () => {" + cuerpo + "})().catch(e => registro.errores.push('async: ' + e));"


def test_la_api_graba_con_las_restricciones_del_cliente_y_entrega_el_audio_al_parar(tmp_path):
    r = ejecutar(GUION, tmp_path, previo=MICRO_CON_AJUSTES, accion=_api("""
      const toma = await HubGrabar.grabar({ restricciones: HubGrabar.RESTRICCIONES.conversacion });
      registro.ajustes = toma.ajustes;
      const audio = await toma.parar();
      registro.tam = audio && audio.size;
      registro.tipo = audio && audio.type;
    """))
    assert r["errores"] == []
    assert r["restricciones"] == [{"audio": {"echoCancellation": True, "noiseSuppression": True}}]
    assert r["ajustes"] == {"echoCancellation": True, "noiseSuppression": False, "sampleRate": 48000}
    assert r["tam"] == 1 and r["tipo"] == "audio/webm"
    assert r["pistas"] == 1   # el micrófono se suelta al parar


def test_las_restricciones_son_dos_nombres_y_cada_cliente_conserva_la_suya(tmp_path):
    """No se unifican: cambiarlas altera cómo se oye (C-0311). `llano` es lo
    que usan hoy el tablero, el orquestador y la terminal."""
    r = ejecutar(GUION, tmp_path, previo=MICRO_CON_AJUSTES, accion=_api("""
      registro.nombres = Object.keys(HubGrabar.RESTRICCIONES).sort();
      registro.llano = HubGrabar.RESTRICCIONES.llano;
      const toma = await HubGrabar.grabar();
      await toma.parar();
    """))
    assert r["errores"] == []
    assert r["nombres"] == ["conversacion", "llano"]
    assert r["llano"] == {"audio": True}
    assert r["restricciones"] == [{"audio": True}]   # sin decir nada, llano


def test_descartar_suelta_el_micro_y_no_entrega_audio(tmp_path):
    r = ejecutar(GUION, tmp_path, previo=MICRO_CON_AJUSTES, accion=_api("""
      const toma = await HubGrabar.grabar();
      registro.audio = await toma.descartar();
    """))
    assert r["errores"] == []
    assert r["audio"] is None and r["pistas"] == 1


@pytest.mark.parametrize("nombre,motivo", [
    ("NotAllowedError", "sin-permiso"), ("SecurityError", "sin-permiso"),
    ("NotFoundError", "sin-micro"), ("NotReadableError", "ocupado"), ("TypeError", "otro")])
def test_por_que_no_hay_micro_se_distingue(tmp_path, nombre, motivo):
    """Sin permiso, sin micrófono u ocupado se arreglan de formas distintas (C-0290)."""
    r = ejecutar(GUION, tmp_path, previo=f"""
      navigator.mediaDevices = {{ getUserMedia: () => Promise.reject({{ name: '{nombre}', message: 'x' }}) }};
      global.MediaRecorder = class {{}};
    """, accion=_api("""
      try { await HubGrabar.grabar(); } catch (e) { registro.motivo = e.motivo; registro.texto = e.message; }
    """))
    assert r["errores"] == []
    assert r["motivo"] == motivo
    assert r["texto"] and r["texto"] != "x"


def test_sin_soporte_lo_dice_sin_pedir_el_micro(tmp_path):
    r = ejecutar(GUION, tmp_path, accion=_api("""
      registro.puede = HubGrabar.puede();
      try { await HubGrabar.microfono(); } catch (e) { registro.motivo = e.motivo; registro.texto = e.message; }
    """))
    assert r["errores"] == []
    assert r["puede"] is False and r["motivo"] == "sin-soporte" and "HTTPS" in r["texto"]


def test_subir_devuelve_lo_que_dice_el_servidor_tal_cual(tmp_path):
    r = ejecutar(GUION, tmp_path, respuestas={"POST /api/voz/banco": {"ok": True, "progreso": {"hechas": 3}}},
                 accion=_api("""
      registro.vuelta = await HubGrabar.subir(new Blob(['x'], { type: 'audio/ogg' }),
                                              { url: '/api/voz/banco', campos: { frase: 'c01', vacio: '' } });
    """))
    assert r["errores"] == []
    assert r["vuelta"] == {"ok": True, "progreso": {"hechas": 3}}
    assert [e["url"] for e in r["enviados"]] == ["/api/voz/banco"]


def test_con_la_red_caida_subir_reintenta_una_vez_y_lo_dice_sin_lanzar(tmp_path):
    r = ejecutar(GUION, tmp_path, previo="""
      global.fetch = () => { registro.intentos = (registro.intentos || 0) + 1;
                             return Promise.reject(new TypeError('Failed to fetch')); };
      const _st = global.setTimeout; global.setTimeout = (f, ms) => _st(f, ms === 1500 ? 2 : ms);
    """, accion=_api("""
      registro.vuelta = await HubGrabar.subir(new Blob(['x']));
    """))
    assert r["errores"] == []
    assert r["intentos"] == 2
    assert r["vuelta"]["ok"] is False and r["vuelta"]["red"] is True and "Failed to fetch" in r["vuelta"]["error"]


def test_cargado_dos_veces_no_engancha_dos_veces(tmp_path):
    """Va en el `<head>` de todas las páginas: si una pantalla lo vuelve a
    cargar, un clic no puede abrir dos micrófonos ni subir dos veces."""
    r = ejecutar(GUION + "\n" + GUION, tmp_path, previo=MICRO_CON_AJUSTES + """
      document.querySelectorAll('[data-grabar]').forEach((b, i) => { b.dataset.grabar = 'destino-' + i; });
    """, accion=PULSAR_DOS_VECES, respuestas={"POST /orquestador/audio": {"ok": True, "texto": "una vez"}})
    assert r["errores"] == []
    assert len(r["restricciones"]) == 1
    assert [e["url"] for e in r["enviados"]] == ["/orquestador/audio"]


def test_en_el_head_espera_al_documento_para_enganchar_los_botones(tmp_path):
    """Cargado antes que el cuerpo, los botones aún no existen: se repasan al
    terminar de leerse el documento."""
    r = ejecutar(GUION, tmp_path, previo=MICRO_CON_AJUSTES + "document.readyState = 'loading';",
                 accion="""
      const b = document.querySelectorAll('[data-grabar]')[0];
      registro.antes = !!b.dataset.grabarListo;
      (globalThis.DOC_OYENTES['DOMContentLoaded'] || []).forEach(f => f({}));
      registro.despues = !!b.dataset.grabarListo;
    """)
    assert r["errores"] == []
    assert r["antes"] is False and r["despues"] is True


def test_grabar_va_una_vez_en_el_head_de_base_y_no_en_cada_pantalla():
    from fastapi.testclient import TestClient

    from hub import web
    from arnes_js import PLANTILLAS

    base = (PLANTILLAS / "base.html").read_text(encoding="utf-8")
    cabeza = base.split("</head>", 1)[0]
    assert '<script src="/static/grabar.js"></script>' in cabeza
    for pantalla in ("tablero.html", "orquestador.html"):
        assert "grabar.js" not in (PLANTILLAS / pantalla).read_text(encoding="utf-8"), pantalla
    assert TestClient(web.app).get("/tablero").text.count("/static/grabar.js") == 1


def test_si_no_se_puede_pegar_lo_dictado_lo_dice_en_vez_de_quedarse_transcribiendo(tmp_path):
    """Un campo destino que no existe dejaba «Transcribiendo…» para siempre."""
    r = ejecutar(GUION, tmp_path, previo=MICROFONO + """
      const _porId = document.getElementById;
      document.getElementById = (id) => id === 'destino-0' ? null : _porId(id);
    """, accion=PULSAR_DOS_VECES, respuestas={"POST /orquestador/audio": {"ok": True, "texto": "revisa alfa"}})
    assert r["errores"] == []
    assert "Transcribiendo" not in r["estado"] and "No se pudo" in r["estado"]


# Abrir el micrófono, grabar y subir la voz: lo que sólo hace `grabar.js`.
# El menú del modelo (C-0313) pregunta y elige en `/api/voz/estado` y
# `/api/voz/modelo`: no graba ni sube voz, y no cuenta.
_POR_SU_CUENTA = re.compile(r"getUserMedia\s*\(|new\s+MediaRecorder\b|fetch\(\s*['\"`]/api/voz(?!/estado|/modelo|/descargar)")


def _quien_graba_por_su_cuenta() -> list[str]:
    archivos = [*PLANTILLAS.rglob("*.html"), *ESTATICOS.rglob("*.js")]
    return sorted(f"{a.parent.name}/{a.name}" for a in archivos
                  if a.name != "grabar.js" and _POR_SU_CUENTA.search(a.read_text(encoding="utf-8")))


def test_fuera_de_grabar_js_nadie_abre_el_microfono_ni_sube_la_voz_por_su_cuenta():
    """Un solo grabador (C-0311). Con cuatro, cada mejora —calentar el
    Whisper, reintentar la subida, decir por qué no hay micrófono— se hacía
    en una copia y las otras se quedaban sin ella: la terminal no tenía
    ninguna de las tres. El que quiera grabar, que use `HubGrabar`."""
    assert _quien_graba_por_su_cuenta() == []


# ── el micrófono no se queda abierto (C-0427) ───────────────────────────────


def test_si_la_grabadora_no_arranca_se_suelta_el_microfono(tmp_path):
    """`grabadora.start()` iba fuera del `try` que suelta el flujo: si
    lanzaba, el micrófono quedaba abierto —el punto rojo del navegador— sin
    que nadie pudiera pararlo."""
    r = ejecutar(GUION, tmp_path, previo=MICROFONO_VIVO + "globalThis.FALLA_START = true;", accion=_api("""
      try { await HubGrabar.grabar(); registro.grabo = true; }
      catch (e) { registro.motivo = e.motivo; }
    """))
    assert r["errores"] == []
    assert r["microfonos"] == 1 and r["motivo"] == "otro" and "grabo" not in r
    assert r["pistas_vivas"] == 0


def test_un_doble_clic_en_dictar_abre_un_solo_microfono_y_parar_lo_cierra(tmp_path):
    """El segundo clic llega mientras el micrófono se abre: no abre otro."""
    r = ejecutar(GUION, tmp_path, previo=MICROFONO_VIVO + """
      document.querySelectorAll('[data-grabar]').forEach((b, i) => { b.dataset.grabar = 'destino-' + i; });
    """, accion="""
      const b = document.querySelectorAll('[data-grabar]')[0];
      b.disparar('click'); setTimeout(() => b.disparar('click'), 1);
      setTimeout(() => b.disparar('click'), 8);
    """, respuestas={"POST /orquestador/audio": {"ok": True, "texto": "x"}})
    assert r["errores"] == []
    assert r["microfonos"] == 1 and r["pistas_vivas"] == 0


# ── El botón de dictar, grabando y en reposo (C-0480) ────────────────────────

# Un botón con el icono dentro, como lo pinta `ui.microfono`: el texto que
# tenía y los atributos que se le ponen se anotan, y el reloj se puede adelantar.
BOTON_CON_ICONO = """
  globalThis.atributos = (b) => { b.attrs = {}; b.setAttribute = (k, v) => { b.attrs[k] = String(v); };
                                  b.getAttribute = (k) => (k in b.attrs ? b.attrs[k] : null); return b; };
  globalThis.tics = [];
  global.setInterval = (fn) => { tics.push(fn); return tics.length; };
  globalThis.adelantar = (ms) => { const antes = Date.now; Date.now = () => antes() + ms; tics.forEach(f => f()); };
"""


def test_marcar_no_borra_el_icono_cuenta_los_segundos_y_vuelve_al_reposo(tmp_path):
    r = ejecutar(GUION, tmp_path, previo=BOTON_CON_ICONO, accion="""
      const b = atributos(nodo('micro'));
      b.textContent = '<svg micrófono>';
      b.setAttribute('aria-label', 'Dictar'); b.title = 'Dictar: se escribe sin enviarlo';
      HubGrabar.marcar(b, { parar(){} });
      registro.grabando = { texto: b.textContent, seg: b.querySelector('[data-mic-seg]').textContent,
                            on: b.classList.contains('on'), pulsado: b.attrs['aria-pressed'],
                            nombre: b.attrs['aria-label'], pista: b.title };
      adelantar(65000);
      registro.pasado = b.querySelector('[data-mic-seg]').textContent;
      HubGrabar.marcar(b, null);
      registro.reposo = { texto: b.textContent, seg: b.querySelector('[data-mic-seg]').textContent,
                          on: b.classList.contains('on'), pulsado: b.attrs['aria-pressed'],
                          nombre: b.attrs['aria-label'], pista: b.title };
    """)
    assert r["errores"] == []
    assert r["grabando"] == {"texto": "<svg micrófono>", "seg": "0:00", "on": True, "pulsado": "true",
                             "nombre": "Parar y transcribir", "pista": "Parar y transcribir"}
    assert r["pasado"] == "1:05"
    assert r["reposo"] == {"texto": "<svg micrófono>", "seg": "", "on": False, "pulsado": "false",
                           "nombre": "Dictar", "pista": "Dictar: se escribe sin enviarlo"}


def test_data_grabar_no_toca_el_texto_del_boton_al_grabar(tmp_path):
    """Escribía «Parar y transcribir» y luego el texto de antes en el
    `textContent`, que con el icono dentro lo borraba (C-0480)."""
    r = ejecutar(GUION, tmp_path, previo=MICROFONO + BOTON_CON_ICONO + """
      const b = atributos(document.querySelectorAll('[data-grabar]')[0]);
      b.textContent = '<svg micrófono>';
    """, accion="""
      const b = document.querySelectorAll('[data-grabar]')[0];
      b.disparar('click');
      setTimeout(() => { registro.durante = [b.textContent, b.attrs['aria-pressed'], b.classList.contains('on')];
                         b.disparar('click'); }, 3);
      setTimeout(() => { registro.despues = [b.textContent, b.attrs['aria-pressed'], b.classList.contains('on')];
                         registro.texto = nodo('destino-0').value; }, 12);
    """, respuestas={"POST /orquestador/audio": {"ok": True, "texto": "revisa alfa"}})
    assert r["errores"] == []
    assert r["durante"] == ["<svg micrófono>", "true", True]
    assert r["despues"] == ["<svg micrófono>", "false", False]
    assert r["texto"] == "revisa alfa"
