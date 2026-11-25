"""El menú del modelo del dictado, ejecutando su JavaScript (regla dura 11, C-0313).

Lo que promete: cerrado no pregunta nada (nvidia-smi cuesta), al abrirse
pinta lo que dice el hub, y elegir manda el modelo y repinta con la respuesta.
"""

from __future__ import annotations

from arnes_js import ejecutar, script_estatico

GUION = script_estatico("modelo-dictado.js")

ESTADO = {"eleccion": "large-v3-turbo", "selector": True, "motivo": "",
          "modelos": [{"modelo": "small", "nombre": "Ligero (small)", "disponible": True},
                      {"modelo": "large-v3-turbo", "nombre": "Preciso (turbo, en la GPU)", "disponible": True},
                      {"modelo": "apagado", "nombre": "Apagado (por la CPU, más lento)", "disponible": True}],
          "cargado": {"modelo": "large-v3-turbo", "dispositivo": "cuda"},
          "gpu": {"usada_mb": 3947, "total_mb": 12282}}

ABRIR = """
  const m = document.querySelectorAll('[data-modelo-dictado]')[0];
  m.open = true;
  m.disparar('toggle');
  setTimeout(() => {
    registro.nota = m.querySelector('[data-md-nota]').textContent;
    registro.resumen = m.querySelector('[data-md-resumen]').textContent;
  }, 10);
"""

ELEGIR = """
  const m = document.querySelectorAll('[data-modelo-dictado]')[0];
  m.disparar('click', { target: { closest: () => ({ dataset: { mdModelo: 'apagado' }, disabled: false }) } });
  setTimeout(() => { registro.nota = m.querySelector('[data-md-nota]').textContent; }, 10);
"""


def test_cerrado_solo_pregunta_lo_elegido_para_el_rotulo(tmp_path):
    r = ejecutar(GUION, tmp_path, respuestas={"GET /api/voz/estado?solo": {"eleccion": "apagado", "selector": True}},
                 accion="""setTimeout(() => { registro.resumen = document.querySelectorAll('[data-modelo-dictado]')[0]
                     .querySelector('[data-md-resumen]').textContent; }, 10);""")
    assert r["errores"] == []
    assert [p for p in r["peticiones"] if "/api/voz" in str(p)] == ["/api/voz/estado?solo=eleccion"]
    assert r["resumen"] == "Dictado: apagado"


def test_al_abrirse_pinta_lo_cargado_y_la_memoria_de_la_gpu(tmp_path):
    r = ejecutar(GUION, tmp_path, accion=ABRIR, respuestas={"GET /api/voz/estado": ESTADO})
    assert r["errores"] == []
    assert "/api/voz/estado?gpu=1" in r["peticiones"]
    assert r["nota"] == "En memoria: turbo en la GPU. GPU: 3,9 de 12,0 GB en uso."
    assert r["resumen"] == "Dictado: turbo"


def test_elegir_manda_el_modelo_y_repinta_con_lo_que_contesta(tmp_path):
    apagado = {**ESTADO, "ok": True, "eleccion": "apagado", "cargado": None}
    r = ejecutar(GUION, tmp_path, accion=ELEGIR, respuestas={"POST /api/voz/modelo": apagado})
    assert r["errores"] == []
    assert {"url": "/api/voz/modelo", "metodo": "POST", "cuerpo": "modelo=apagado"} in r["enviados"]
    assert r["nota"].startswith("Apagado: cada frase se transcribe en la CPU")


def test_si_no_se_puede_cambiar_dice_por_que(tmp_path):
    r = ejecutar(GUION, tmp_path, accion=ELEGIR, respuestas={
        "POST /api/voz/modelo": {"ok": False, "error": "no se pudo cargar Preciso (turbo, en la GPU)"},
        "GET /api/voz/estado": ESTADO})
    assert r["errores"] == []
    assert r["nota"] == "no se pudo cargar Preciso (turbo, en la GPU)"


def test_junto_al_microfono_lo_elegido_va_al_titulo_y_no_borra_la_flecha(tmp_path):
    """La forma `flecha` (C-0480) es un icono: escribir el rótulo en su texto
    borraba el SVG. Lo elegido va al `title` y al `aria-label`."""
    r = ejecutar(GUION, tmp_path, respuestas={"GET /api/voz/estado?solo": {"eleccion": "large-v3-turbo", "selector": True}},
                 previo="""
      const m = document.querySelectorAll('[data-modelo-dictado]')[0];
      m.dataset.mdForma = 'flecha';
      const s = m.querySelector('[data-md-resumen]');
      s.textContent = '<svg flecha>';
      s.attrs = {}; s.setAttribute = (k, v) => { s.attrs[k] = v; };
    """, accion="""setTimeout(() => {
      const s = document.querySelectorAll('[data-modelo-dictado]')[0].querySelector('[data-md-resumen]');
      registro.resumen = [s.textContent, s.title, s.attrs['aria-label']]; }, 10);""")
    assert r["errores"] == []
    assert r["resumen"] == ["<svg flecha>", "Modelo del dictado: turbo", "Modelo del dictado: turbo"]
