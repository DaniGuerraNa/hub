/* Grabar la voz en el navegador: un solo grabador para todo el hub (C-0311).
 *
 * `window.HubGrabar` abre el micrófono, graba, entrega el audio y lo sube.
 * Antes había cuatro aperturas de micrófono con la subida copiada tres veces,
 * y cada mejora (calentar, reintentar, errores claros, medir con el banco)
 * había que hacerla en cada una. Aquí vive lo común; cada cliente se queda
 * con sus textos y con qué hace con el audio o con el texto. Lo usan
 * `data-grabar` (aquí abajo), el banco de dictado, el dictado de la terminal
 * y el chat del secretario (hablarle y el vigía que deja interrumpirle).
 * Nadie más abre el micrófono ni sube la voz: lo vigila `test_grabar_js.py`.
 *
 *   HubGrabar.puede()                       ¿hay micrófono en este contexto?
 *   HubGrabar.RESTRICCIONES.{llano,conversacion}
 *   HubGrabar.microfono(restricciones)      el flujo, o un Error con `.motivo`:
 *                                           sin-soporte, sin-permiso, sin-micro,
 *                                           ocupado, otro (sin grabar: el vigía
 *                                           del chat sólo mide el volumen)
 *   HubGrabar.grabar({restricciones})       → toma {flujo, grabadora, ajustes,
 *                                           parar(), descartar(), terminado}
 *                                           `parar()` da el audio (o null)
 *   HubGrabar.subir(audio, {url, campos})   el JSON del servidor TAL CUAL; si
 *                                           la red falla dos veces,
 *                                           {ok:false, red:true, error}
 *   HubGrabar.calentar()                    que el Whisper cargado se vaya
 *                                           cargando (C-0292)
 *
 * 🔴 Las restricciones NO se unifican: cambiarlas cambia cómo se oye, y cada
 * cliente pasa la suya. `ajustes` es lo que el micrófono dio de verdad
 * (`getSettings()`), que no tiene por qué ser lo pedido.
 *
 * Encima va lo declarativo de siempre: un botón con `data-grabar="<id del
 * campo>"` dicta en ese campo. Sube a `data-grabar-url`, o a
 * /orquestador/audio si no lo dice; el tablero sube a /api/voz
 * (`transcribir.dictado`, C-0149). 🔴 No envía nada: una transcripción
 * equivocada en una orden que se ejecuta sin nadie delante es el error que no
 * se ve hasta que ya pasó, así que el texto se queda a la vista y lo manda
 * una persona.
 *
 * Va en el `<head>` de `base.html`, como `sondeo.js`: los scripts de cada
 * pantalla lo usan al arrancar. Por eso los botones se enganchan al terminar
 * de leerse el documento, y una segunda carga no hace nada.
 *
 * El micrófono sólo existe en un contexto seguro (HTTPS o localhost). Por el
 * tailnet el hub va por HTTPS, así que en el teléfono está; si no, se dice.
 */
(() => {
  if (window.HubGrabar) return;

  const RESTRICCIONES = Object.freeze({
    // El dictado del tablero, el orquestador y la terminal.
    llano: Object.freeze({ audio: true }),
    // La conversación con el secretario: sin el eco de su propia voz leída en
    // alto ni el ruido de fondo (decisión 318).
    conversacion: Object.freeze({ audio: Object.freeze({ echoCancellation: true, noiseSuppression: true }) }),
  });

  const puede = () => !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia && window.MediaRecorder);

  const conMotivo = (motivo, texto) => Object.assign(new Error(texto), { motivo });

  /* Por qué no hay micrófono (C-0290): sin permiso, sin micrófono u ocupado
   * por otra aplicación —una reunión— se arreglan de formas distintas. */
  function porQue(e) {
    const nombre = (e && e.name) || '';
    if (nombre === 'NotAllowedError' || nombre === 'SecurityError') {
      return conMotivo('sin-permiso', 'sin permiso para el micrófono: permítelo en los ajustes del sitio (el candado junto a la dirección)');
    }
    if (nombre === 'NotFoundError' || nombre === 'OverconstrainedError') {
      return conMotivo('sin-micro', 'no hay ningún micrófono conectado');
    }
    if (nombre === 'NotReadableError' || nombre === 'AbortError') {
      return conMotivo('ocupado', 'el micrófono está ocupado por otra aplicación (¿una llamada o una reunión?)');
    }
    return conMotivo('otro', `no se pudo abrir el micrófono${nombre ? ` (${nombre})` : ''}`);
  }

  async function microfono(restricciones) {
    if (!puede()) {
      throw conMotivo('sin-soporte', 'este navegador no deja grabar aquí (hace falta HTTPS o localhost)');
    }
    try {
      return await navigator.mediaDevices.getUserMedia(restricciones || RESTRICCIONES.llano);
    } catch (e) {
      throw porQue(e);
    }
  }

  const soltar = (flujo) => { try { flujo.getTracks().forEach((p) => p.stop()); } catch (e) { /* ya suelto */ } };

  function ajustesDe(flujo) {
    try {
      const pistas = flujo.getAudioTracks ? flujo.getAudioTracks() : flujo.getTracks();
      const pista = pistas && pistas[0];
      return (pista && pista.getSettings) ? { ...pista.getSettings() } : {};
    } catch (e) {
      return {};
    }
  }

  async function grabar(opciones) {
    const o = opciones || {};
    const flujo = await microfono(o.restricciones);
    let grabadora;
    try {
      grabadora = new MediaRecorder(flujo);
    } catch (e) {
      soltar(flujo);
      throw conMotivo('otro', 'este navegador no sabe grabar este micrófono: ' + (e && e.message ? e.message : e));
    }
    const trozos = [];
    let tirar = false;
    let parada = false;
    let fin;
    const terminado = new Promise((listo) => { fin = listo; });
    grabadora.addEventListener('dataavailable', (ev) => { if (ev.data && ev.data.size) trozos.push(ev.data); });
    grabadora.addEventListener('stop', () => {
      soltar(flujo);
      fin(tirar || !trozos.length ? null : new Blob(trozos, { type: grabadora.mimeType || 'audio/webm' }));
    });
    // Dentro de su `try`, como la grabadora (C-0427): si `start()` lanza, el
    // micrófono se quedaba abierto sin toma con la que pararlo.
    try {
      grabadora.start();
    } catch (e) {
      soltar(flujo);
      throw conMotivo('otro', 'no se pudo empezar a grabar: ' + (e && e.message ? e.message : e));
    }
    const toma = {
      flujo, grabadora, ajustes: ajustesDe(flujo), terminado,
      parar() {
        if (!parada) { parada = true; grabadora.stop(); }
        return terminado;
      },
      descartar() { tirar = true; return toma.parar(); },
    };
    return toma;
  }

  const extension = (tipo) => {
    const t = String(tipo || '');
    return t.includes('ogg') ? 'ogg' : t.includes('mp4') ? 'm4a' : 'webm';
  };

  async function subir(audio, opciones) {
    const o = opciones || {};
    const datos = new FormData();
    datos.append('audio', audio, o.nombre || ('audio.' + extension(audio && audio.type)));
    Object.entries(o.campos || {}).forEach(([clave, valor]) => {
      if (valor !== undefined && valor !== null && valor !== '') datos.append(clave, valor);
    });
    const url = o.url || '/api/voz';
    const una = async () => (await fetch(url, { method: 'POST', body: datos })).json();
    try {
      try {
        return await una();
      } catch (e) {
        // Un corte de un segundo (la red del teléfono, el hub reiniciando)
        // costaba lo dictado entero: se reintenta una vez, sola (C-0287).
        await new Promise((listo) => setTimeout(listo, 1500));
        return await una();
      }
    } catch (e) {
      return { ok: false, red: true, error: String((e && e.message) || e) };
    }
  }

  // Un adelanto: si falla, se transcribe igual, sólo que en frío.
  function calentar() {
    try { fetch('/api/voz/calentar', { method: 'POST' }).catch(() => {}); } catch (e) { /* es un adelanto */ }
  }

  window.HubGrabar = { puede, RESTRICCIONES, microfono, grabar, subir, calentar };

  // ── Lo declarativo: `data-grabar` dicta en un campo ──────────────────────
  // Cada botón se engancha una vez; se repasa tras `hub:repintado` porque una
  // acción sin recargar (C-0167) pinta botones nuevos —«Dictar» la respuesta
  // al orquestador— que al cargar no existían.
  function enganchar(boton) {
    if (boton.dataset.grabarListo) return;
    boton.dataset.grabarListo = '1';
    const destino = document.getElementById(boton.dataset.grabar);
    const estado = document.getElementById(boton.dataset.grabarEstado);
    const origen = document.getElementById(boton.dataset.grabarOrigen);
    const inicial = boton.textContent;
    const url = boton.dataset.grabarUrl || '/orquestador/audio';
    let toma = null;
    let abriendo = false;

    const decir = (texto) => { if (estado) estado.textContent = texto; };

    // Al vaciarse el formulario —`sin-recarga.js` lo hace tras enviarlo bien
    // (C-0233, «Encolar»)— vuelve todo a como estaba antes de dictar. El
    // origen es un campo oculto y `reset()` no lo devuelve solo (su valor ES
    // su atributo): la tarea siguiente, tecleada, salía como «dictada».
    const origenInicial = origen ? origen.value : '';
    const estadoInicial = estado ? estado.textContent : '';
    if (boton.form) {
      boton.form.addEventListener('reset', () => {
        if (origen) origen.value = origenInicial;
        decir(estadoInicial);
      });
    }

    const transcribir = async (audio) => {
      decir('Transcribiendo…');
      boton.disabled = true;
      try {
        // Quién dicta, para medir cada voz por separado (C-0246).
        const j = await subir(audio, { url, campos: { origen: boton.dataset.grabarQuien } });
        if (!j || !j.ok) {
          decir('No se pudo transcribir: ' + (j && j.error));
          return;
        }
        const previo = (destino.value || '').trimEnd();
        destino.value = previo ? previo + '\n' + j.texto : j.texto;
        if (origen) origen.value = 'audio';
        decir('Listo. Revísalo antes de mandarlo.');
      } catch (e) {
        // Sin esto, un campo destino que no está dejaba «Transcribiendo…» para siempre.
        decir('No se pudo pegar lo dictado: ' + (e && e.message ? e.message : e));
      } finally {
        boton.disabled = false;
      }
    };

    boton.addEventListener('click', async () => {
      if (toma) { toma.parar(); return; }
      if (abriendo) return;
      if (!puede()) {
        decir('Este navegador no deja grabar aquí (hace falta HTTPS). Escríbelo.');
        return;
      }
      // Que el Whisper cargado se vaya cargando mientras hablas (C-0292). Sólo
      // /api/voz lo usa: el audio del orquestador va por su camino.
      if (url === '/api/voz') calentar();
      abriendo = true;
      let esta;
      try {
        esta = await grabar({ restricciones: RESTRICCIONES.llano });
      } catch (e) {
        decir('No se puede grabar: ' + e.message);
        return;
      } finally {
        abriendo = false;
      }
      toma = esta;
      boton.textContent = 'Parar y transcribir';
      boton.classList.add('grabando');
      decir('Grabando… pulsa otra vez para terminar.');
      const audio = await esta.terminado;
      toma = null;
      boton.textContent = inicial;
      boton.classList.remove('grabando');
      if (!audio) {
        decir('No se grabó nada.');
        return;
      }
      transcribir(audio);
    });
  }

  const repasar = () => document.querySelectorAll('[data-grabar]').forEach(enganchar);
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', repasar);
  else repasar();
  document.addEventListener('hub:repintado', repasar);
})();
