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


# ── Un modelo sin descargar se baja desde el menú (C-0505) ──────────────────

SIN_TURBO = {**ESTADO, "eleccion": "small", "mirado": True, "descarga": None,
             "cargado": {"modelo": "small", "dispositivo": "cuda"},
             "modelos": [{"modelo": "small", "nombre": "Ligero (small)", "disponible": True,
                          "tamano": 486212372, "solo_gpu": False},
                         {"modelo": "large-v3-turbo", "nombre": "Preciso (turbo, en la GPU)",
                          "disponible": False, "tamano": 1621665983, "solo_gpu": True},
                         {"modelo": "apagado", "nombre": "Apagado (por la CPU, más lento)", "disponible": True}]}

# Lo que se añade a las opciones, en orden: `appendChild` del arnés no guarda nada.
HIJOS = """
  const m = document.querySelectorAll('[data-modelo-dictado]')[0];
  const caja = m.querySelector('[data-md-opciones]');
  registro.hijos = [];
  caja.appendChild = (h) => registro.hijos.push(h);
"""

VER_HIJOS = """
  const m = document.querySelectorAll('[data-modelo-dictado]')[0];
  m.open = true;
  m.disparar('toggle');
  setTimeout(() => {
    registro.vistos = registro.hijos.map(h => [h.textContent, !!h.disabled, h.dataset.mdDescargar || null]);
    registro.nota = m.querySelector('[data-md-nota]').textContent;
  }, 10);
"""


def test_sin_descargar_se_lee_y_trae_su_boton_de_descargar_con_lo_que_pesa(tmp_path):
    r = ejecutar(GUION, tmp_path, previo=HIJOS, accion=VER_HIJOS,
                 respuestas={"GET /api/voz/estado": SIN_TURBO})
    assert r["errores"] == []
    assert ["Preciso (turbo, en la GPU) — sin descargar", True, None] in r["vistos"]
    assert ["↓ Descargar (≈1,6 GB)", False, "large-v3-turbo"] in r["vistos"]


def test_si_no_se_pudo_mirar_no_dice_sin_descargar_ni_ofrece_bajarlo(tmp_path):
    r = ejecutar(GUION, tmp_path, previo=HIJOS, accion=VER_HIJOS,
                 respuestas={"GET /api/voz/estado": {**SIN_TURBO, "mirado": False}})
    assert r["errores"] == []
    assert not any("sin descargar" in t or d for t, _, d in r["vistos"])


def test_sin_gpu_turbo_no_ofrece_bajarse(tmp_path):
    r = ejecutar(GUION, tmp_path, previo=HIJOS, accion=VER_HIJOS,
                 respuestas={"GET /api/voz/estado": {**SIN_TURBO, "gpu": None}})
    assert r["errores"] == []
    assert not any(d for _, _, d in r["vistos"])
    assert any("GPU NVIDIA" in t for t, _, _ in r["vistos"])


def test_mientras_baja_lo_dice_y_no_deja_lanzar_otra(tmp_path):
    bajando = {**SIN_TURBO, "descarga": {"modelo": "large-v3-turbo", "nombre": "Preciso (turbo, en la GPU)",
                                         "estado": "bajando", "error": "", "desde": None}}
    # Cerrado tras mirarlo: abierto, el menú sigue preguntando mientras baje.
    cerrar = VER_HIJOS.replace("registro.nota = m.querySelector('[data-md-nota]').textContent;",
                               "registro.nota = m.querySelector('[data-md-nota]').textContent; m.open = false;")
    r = ejecutar(GUION, tmp_path, previo=HIJOS, accion=cerrar,
                 respuestas={"GET /api/voz/estado?gpu": bajando,
                             "GET /api/voz/estado?solo=descarga": {"descarga": bajando["descarga"]}})
    assert r["errores"] == []
    assert ["Descargando…", False, None] in r["vistos"]
    assert not any(d for _, _, d in r["vistos"])
    assert "Puedes cerrar el menú: sigue sola" in r["nota"]


def test_pulsar_descargar_manda_el_modelo_y_no_elige_nada(tmp_path):
    accion = """
      const m = document.querySelectorAll('[data-modelo-dictado]')[0];
      m.disparar('click', { target: { closest: (sel) => sel === '[data-md-descargar]'
          ? ({ dataset: { mdDescargar: 'large-v3-turbo' }, disabled: false }) : null } });
      setTimeout(() => { registro.nota = m.querySelector('[data-md-nota]').textContent; }, 10);
    """
    r = ejecutar(GUION, tmp_path, accion=accion, respuestas={
        "POST /api/voz/descargar": {"ok": False, "error": "ya se está bajando Preciso: de uno en uno"},
        "GET /api/voz/estado": SIN_TURBO})
    assert r["errores"] == []
    assert {"url": "/api/voz/descargar", "metodo": "POST", "cuerpo": "modelo=large-v3-turbo"} in r["enviados"]
    assert not any(e["url"] == "/api/voz/modelo" for e in r["enviados"])
    assert r["nota"] == "ya se está bajando Preciso: de uno en uno"


def test_un_fallo_de_la_descarga_se_dice_en_claro(tmp_path):
    fallo = {**SIN_TURBO, "descarga": {"modelo": "large-v3-turbo", "nombre": "Preciso (turbo, en la GPU)",
                                       "estado": "fallo", "error": "Connection reset by peer", "desde": None}}
    r = ejecutar(GUION, tmp_path, previo=HIJOS, accion=VER_HIJOS, respuestas={"GET /api/voz/estado": fallo})
    assert r["errores"] == []
    assert "No se pudo bajar Preciso (turbo, en la GPU): Connection reset by peer." in r["nota"]
    assert ["↓ Descargar (≈1,6 GB)", False, "large-v3-turbo"] in r["vistos"]
