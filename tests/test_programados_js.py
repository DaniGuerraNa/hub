"""El panel de mensajes programados, ejecutando su JavaScript (regla dura 11).

🔴 Lo único que este panel tiene que hacer bien es **la hora**, y es lo único que
no se puede comprobar leyendo el código: un `datetime-local` no lleva zona, y
convertirlo mal no da error en ninguna parte — da un mensaje entregado seis horas
tarde, sin un solo síntoma. Por eso los tests de aquí corren con `TZ` fijada: sin
eso probarían la zona de la máquina que ejecuta la suite y darían verde en una
máquina y rojo en otra (regla dura 19).

Vive en /trabajo, así que si revienta al arrancar se lleva la terminal por
delante y la página se sirve perfecta igualmente.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

GUION = Path(__file__).resolve().parents[1] / "src" / "hub" / "static" / "programados.js"

ARNES = r"""
const nodos = {};
function nuevo(id) {
  const n = {
    id, innerHTML: '', textContent: '', value: '', hidden: false, dataset: {},
    classList: { _s: new Set(), add(c){this._s.add(c)}, remove(c){this._s.delete(c)},
                 contains(c){return this._s.has(c)},
                 toggle(c, f){ const v = f === undefined ? !this._s.has(c) : f;
                               v ? this._s.add(c) : this._s.delete(c); return v; } },
    _oyentes: {},
    addEventListener(ev, fn){ (this._oyentes[ev] ||= []).push(fn); },
    disparar(ev, arg){ (this._oyentes[ev] || []).forEach(f => f(arg || {})); },
    querySelector(sel){ return SIN_SLOT ? null : nodos['nota']; },
    querySelectorAll(){ return []; },
  };
  return (nodos[id] = n);
}

nuevo('programados-lista');
nuevo('programar-forma');
nuevo('programar-sin-slot');
nuevo('programar-texto');
nuevo('programar-cuando');
nuevo('programar-enviar');
nuevo('programar-estado');
const pestana = nuevo('pest-programados');
pestana.dataset.hoja = 'programados';

const nota = nuevo('nota');
nota.dataset.slot = '7';
const bloque = nuevo('bloque');
bloque.querySelector = (sel) => (SIN_SLOT ? null : nota);

const REG = { peticiones: [], enviados: [], avisos: [], cambios: [] };

/* 🔴 Cada cambio de `hidden` queda apuntado, y ése es el único sitio desde el
 * que se puede ver un PARPADEO. Mirando sólo el estado final, «lo enseñó, lo
 * quitó y lo volvió a enseñar» y «nunca lo enseñó» son indistinguibles — y lo
 * que él vio en su teléfono fue exactamente lo primero. */
['programar-forma', 'programar-sin-slot'].forEach(id => {
  const n = nodos[id];
  let valor = false;
  Object.defineProperty(n, 'hidden', {
    get: () => valor,
    set: (x) => {
      const nuevo = !!x;
      if (nuevo !== valor) REG.cambios.push(id + (nuevo ? '=oculto' : '=visible'));
      valor = nuevo;
    },
  });
});

/* 🔴 El DOM de verdad, y no el que le convenga al script.
 *
 * `trabajo.html` pinta CADA bloque `.por-ventana` con el atributo `hidden`, y
 * revela el activo poniéndole la clase `viendo` — el atributo NO se quita nunca
 * (`.por-ventana.viendo { display:flex }` gana al `[hidden]` del navegador por
 * especificidad). O sea que `:not([hidden])` no casa jamás.
 *
 * La primera versión de este arnés contestaba a ese selector, así que el test
 * daba verde sobre un panel que en la pantalla decía «esta ventana no pertenece
 * a ningún slot» teniéndolo. Un arnés que responde a lo que le pregunten no
 * prueba nada: sólo repite la suposición de quien escribió el script.
 */
const SELECTOR_BUENO = '.por-ventana.viendo .nota-texto';

global.document = {
  getElementById: (id) => nodos[id] || null,
  querySelector: (sel) => {
    if (sel === '.por-ventana.viendo') {
      // `SIN_BLOQUE` es «la página aún no ha marcado la ventana activa», que no
      // es lo mismo que «esta ventana no tiene slot» (`SIN_SLOT`).
      return SIN_BLOQUE ? null : bloque;
    }
    if (sel !== SELECTOR_BUENO) return null;
    return SIN_SLOT ? null : nota;
  },
  querySelectorAll: (sel) => (sel === '.pest-lado button' ? [pestana] : []),
};
global.window = { addEventListener(){} };
global.setInterval = () => 0;
global.clearInterval = () => {};
global.HubUI = { avisar: (o) => { REG.avisos.push(o); return Promise.resolve(); } };
global.fetch = (url, opciones) => {
  REG.peticiones.push(String(url));
  const metodo = ((opciones && opciones.method) || 'GET').toUpperCase();
  if (opciones && opciones.body) {
    REG.enviados.push(JSON.parse(opciones.body));
  }
  if (metodo === 'POST') return Promise.resolve({ ok: true, status: 200,
                                                  json: () => Promise.resolve(RESPUESTA_POST) });
  return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(MENSAJES) });
};

/* 🔴 El reloj del arnés corre deprisa, y hace falta que corra.
 *
 * El script reintenta doce veces cada 250 ms antes de rendirse: tres segundos
 * reales. Lo que hay que probar es la SECUENCIA —qué se enseña mientras no se
 * sabe y qué se enseña al agotarse—, no la duración, y esperar tres segundos
 * por prueba es cómo un test que protege algo deja de ejecutarse. El arnés se
 * queda con el reloj de verdad para su propio volcado.
 *
 * Sin esto, las pruebas del estado agotado NO son posibles: el volcado ocurría
 * a los 20 ms, o sea siempre dentro de los reintentos, y el parpadeo que él vio
 * en su teléfono era invisible desde aquí. */
const _reloj = setTimeout;
global.setTimeout = (fn, ms) => _reloj(fn, Math.min(ms || 0, 2));

__GUION__

_reloj(() => {
  if (ACCION) { eval(ACCION); }
  _reloj(() => {
    console.log(JSON.stringify({
      ...REG,
      html: nodos['programados-lista'].innerHTML,
      estado: nodos['programar-estado'].textContent,
      caja: nodos['programar-texto'].value,
      forma_oculta: nodos['programar-forma'].hidden,
      aviso_sin_slot: !nodos['programar-sin-slot'].hidden,
    }));
  }, 300);
}, 60);
"""


def _correr(mensajes=None, accion="", sin_slot=False, sin_bloque=False,
            respuesta_post=None, tz="America/Mexico_City") -> dict:
    """Ejecuta el script. `tz` se fija a propósito: ver el docstring del módulo."""
    node = shutil.which("node")
    if not node:
        pytest.skip("hace falta node para ejecutar el JS")
    guion = (
        f"const MENSAJES = {json.dumps(mensajes or [])};\n"
        f"const ACCION = {json.dumps(accion)};\n"
        f"const SIN_SLOT = {json.dumps(sin_slot)};\n"
        f"const SIN_BLOQUE = {json.dumps(sin_bloque)};\n"
        f"const RESPUESTA_POST = {json.dumps(respuesta_post or {'ok': True, 'id': 3})};\n"
        + ARNES.replace("__GUION__", GUION.read_text(encoding="utf-8"))
    )
    salida = subprocess.run(
        [node, "-e", guion], capture_output=True, text=True, timeout=30,
        env={**os.environ, "TZ": tz},
    )
    assert salida.returncode == 0, salida.stderr
    return json.loads(salida.stdout.strip().splitlines()[-1])


def _mensaje(**campos):
    base = {"id": 1, "texto": "empieza por los tests", "estado": "pendiente",
            "cuando": "2026-09-12T15:00:00+00:00", "motivo": "", "slot_nombre": "back"}
    return {**base, **campos}


# ── La hora ─────────────────────────────────────────────────────────────────


ESCRIBIR = (
    "nodos['programar-texto'].value = 'empieza por los tests';"
    "nodos['programar-cuando'].value = '2026-09-12T09:00';"
    "nodos['programar-enviar'].disparar('click');"
)


def test_la_hora_local_se_manda_en_UTC():
    """🔴 El test que justifica este archivo.

    Se escriben «las 9:00» en México (UTC−6) y lo que tiene que salir hacia el
    hub son las 15:00 UTC. Si se mandara el valor crudo del `datetime-local`, el
    servidor lo rechazaría por no llevar zona; si alguien «arreglara» eso
    suponiendo UTC, el mensaje saldría a las tres de la tarde y nada lo diría.
    """
    r = _correr(accion=ESCRIBIR)
    assert r["enviados"] == [
        {"slot_id": 7, "texto": "empieza por los tests",
         "cuando": "2026-09-12T15:00:00.000Z"}
    ]


def test_la_misma_hora_en_otra_zona_sale_distinta():
    """La conversión usa la zona de quien mira, no una fija. Con el hub en
    remoto esto deja de ser teórico: se programa desde otro país."""
    r = _correr(accion=ESCRIBIR, tz="Europe/Madrid")
    assert r["enviados"][0]["cuando"] == "2026-09-12T07:00:00.000Z"


def test_lo_que_llega_en_UTC_se_ENSEÑA_en_la_hora_de_quien_mira():
    """Una lista que dijera «15:00 UTC» obligaría a restar seis a mano cada vez,
    y el día que se reste mal se cancela el mensaje equivocado."""
    r = _correr([_mensaje(cuando="2026-09-12T15:00:00+00:00")])
    assert "12/09 09:00" in r["html"]


# ── Lo que se manda y lo que no ─────────────────────────────────────────────


def test_sin_hora_no_se_manda_nada_y_se_dice():
    r = _correr(accion="nodos['programar-texto'].value = 'hola';"
                       "nodos['programar-enviar'].disparar('click');")
    assert r["enviados"] == []
    assert "hora" in r["estado"].lower()


def test_sin_texto_no_se_manda_nada_y_se_dice():
    r = _correr(accion="nodos['programar-cuando'].value = '2026-09-12T09:00';"
                       "nodos['programar-enviar'].disparar('click');")
    assert r["enviados"] == []
    assert "mensaje" in r["estado"].lower()


def test_si_el_hub_dice_que_no_se_avisa_y_NO_se_pierde_lo_escrito():
    """El fallo de la decisión 196, que no se repite: borrar la caja antes de
    saber si salió pierde lo escrito sin que nada lo diga."""
    r = _correr(accion=ESCRIBIR,
                respuesta_post={"ok": False, "error": "no dice en qué zona horaria es"})

    assert [a["titulo"] for a in r["avisos"]] == ["No se pudo programar"]
    assert "zona horaria" in r["avisos"][0]["mensaje"]
    assert r["caja"] == "empieza por los tests", "se perdió lo escrito"


def test_cuando_sale_bien_se_limpia_la_caja():
    r = _correr(accion=ESCRIBIR)
    assert r["avisos"] == []
    assert r["caja"] == ""


# ── La lista ────────────────────────────────────────────────────────────────


def test_arranca_pidiendo_los_del_slot_de_la_ventana_que_se_mira():
    r = _correr([_mensaje()])
    assert r["peticiones"][0] == "/api/programados?slot=7"
    assert "empieza por los tests" in r["html"]


def test_sin_slot_no_se_ofrece_programar_y_se_explica():
    """No hay dónde entregarlo: el destino es el panel de un slot, que es lo
    único sobre lo que el hub puede comprobar qué corre dentro (regla 15)."""
    r = _correr([], sin_slot=True)
    assert r["forma_oculta"] is True
    assert r["aviso_sin_slot"] is True
    assert r["peticiones"] == []


def test_el_motivo_de_que_no_saliera_se_ve():
    """Sin esto, un mensaje que lleva veinte minutos sin poder entregarse se ve
    igual que uno que acaba de programarse."""
    r = _correr([_mensaje(motivo="está trabajando ahora mismo")])
    assert "está trabajando ahora mismo" in r["html"]


def test_solo_lo_pendiente_ofrece_cancelar():
    """Cancelar algo ya entregado reescribiría la historia, y el servidor lo
    rechaza: ofrecer el botón sería prometer algo que no se puede hacer."""
    pendiente = _correr([_mensaje(estado="pendiente")])
    entregado = _correr([_mensaje(estado="entregado")])
    assert "data-cancelar" in pendiente["html"]
    assert "data-cancelar" not in entregado["html"]


def test_el_texto_del_mensaje_va_escapado():
    """Lo escribe él, pero acaba en `innerHTML` en la página que sirve el
    endpoint de terminal (regla dura 8). Escapar no depende de quién escriba."""
    r = _correr([_mensaje(texto="<img src=x onerror=alert(1)>")])
    assert "<img" not in r["html"]
    assert "&lt;img" in r["html"]


def test_cancelar_llama_al_hub_y_refresca():
    r = _correr([_mensaje()],
                accion="nodos['programados-lista'].disparar('click', "
                       "{ target: { dataset: { cancelar: '9' } } });")
    assert "/api/programado/9/cancelar" in r["peticiones"]


def test_un_fallo_de_red_no_pisa_la_lista_ya_pintada():
    """Cambiar información por ruido es peor que dejar la lista un poco vieja."""
    r = _correr([_mensaje()],
                # Se rompe la red Y se provoca un refresco: sin el segundo paso
                # el test pasaría sin ejercitar nada, mirando el pintado inicial.
                accion="global.fetch = () => Promise.reject(new Error('sin red'));"
                       "nodos['pest-programados'].disparar('click');")
    assert "empieza por los tests" in r["html"]


def test_mientras_no_se_sabe_el_slot_NO_se_afirma_que_no_lo_haya():
    """🔴 La clase `viendo` la pone el script de la página DESPUÉS de pedirle las
    ventanas al hub; esto corre antes. En ese hueco el panel decía «esta ventana
    no pertenece a ningún slot» sobre una que sí tenía — afirmar algo que no se
    ha mirado, el error que el estado `nueva` de la franja existe para no
    cometer. Ahora no se afirma nada y se vuelve a mirar enseguida.
    """
    r = _correr([], sin_bloque=True)

    assert r["aviso_sin_slot"] is False, "dijo «no hay slot» sin haber podido mirar"
    assert r["forma_oculta"] is True
    assert r["peticiones"] == []


def test_la_espera_por_el_bloque_tiene_tope():
    """🔴 Sin tope, una sesión sin ninguna ventana —no hay bloque que marcar,
    nunca— dejaría esto sondeando cuatro veces por segundo mientras la pestaña
    siga abierta.

    Se comprueba EJECUTÁNDOLO y no buscando `porMirar--` en el texto: una
    comprobación de cadena da verde sobre cualquier refactor que la conserve y
    rojo sobre cualquiera que no, y en ninguno de los dos casos ha mirado lo que
    hace el panel.
    """
    r = _correr([], sin_bloque=True)
    assert r["peticiones"] == [], "sondeó al hub sin saber de qué slot"


def test_agotada_la_espera_SIGUE_sin_afirmar_que_no_haya_slot():
    """🔴 El fallo que él vio, y sale de una línea.

    `porMirar` se reiniciaba SIEMPRE, también cuando los doce intentos se habían
    agotado sin saberlo. Entonces «no lo sé» se contaba como «no tiene slot»: se
    ocultaba el formulario, salían los dos avisos, y al latido siguiente volvían
    los tres segundos en blanco. Cada diez segundos, para siempre.

    Dicho por él: *«me dice "Nada programado para este slot", y parpadea y
    muestra el texto de que la ventana no pertenece a un slot, y repite»*.
    """
    r = _correr([], sin_bloque=True)

    assert "programar-sin-slot=visible" not in r["cambios"], \
        "afirmó que la ventana no tiene slot sin haber podido mirarla"
    assert r["aviso_sin_slot"] is False
    assert r["forma_oculta"] is True
    assert "No se ve qué ventana" in r["html"], \
        "se quedó callado: hay que decir por qué no se puede programar"


def test_no_parpadea_entre_las_dos_pantallas():
    """Dos vueltas seguidas tienen que dejar la MISMA pantalla.

    Es lo que distingue «no lo sabe y lo dice» de «lo dice, se arrepiente y
    vuelve a decirlo»: mirando sólo el final las dos se ven iguales.
    """
    r = _correr([], sin_bloque=True,
                accion="nodos['pest-programados'].disparar('click');")
    assert r["cambios"].count("programar-sin-slot=visible") == 0
    assert r["cambios"].count("programar-forma=visible") == 0


def test_sin_slot_la_lista_no_habla_de_un_slot():
    """«Nada programado para este slot» sobre una ventana sin slot afirma que
    hay un slot, y contradice al aviso de al lado en la misma pantalla."""
    r = _correr([], sin_slot=True)
    assert "este slot" not in r["html"]
    assert r["aviso_sin_slot"] is True


def test_cuando_SI_hay_bloque_y_no_tiene_slot_se_dice(monkeypatch=None):
    """La otra mitad: «no lo sé» no puede tragarse el caso real de no tener
    slot, o el aviso no saldría nunca."""
    r = _correr([], sin_slot=True)
    assert r["aviso_sin_slot"] is True and r["forma_oculta"] is True
