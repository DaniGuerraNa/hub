/* El chat del asistente.
 *
 * Detrás de esta pestaña no hay ningún motor de chat: hay una ventana de tmux
 * con `claude --model sonnet` dentro. Esto lee su transcript y lo pinta. Por eso
 * no hay historial que guardar, ni sesión que reanudar, ni «compactar» que
 * implementar — `/compact` y `/clear` ya existen y son de Claude Code.
 *
 * Vive en base.html, así que si revienta al arrancar se lo lleva por delante en
 * TODAS las pantallas sin ningún síntoma visible (regla dura 11).
 */
(function () {
  const raiz = document.getElementById('asistente');
  if (!raiz) return;

  const pestana   = document.getElementById('asistente-pestana');
  const hilo      = document.getElementById('asistente-hilo');
  const caja      = document.getElementById('asistente-texto');
  const enviar    = document.getElementById('asistente-enviar');
  const luz       = document.getElementById('asistente-luz');
  const ctx       = document.getElementById('asistente-ctx');
  const estado    = document.getElementById('asistente-estado');
  const flecha    = document.getElementById('asistente-flecha');
  const btCompact = document.getElementById('asistente-compactar');
  const btLimpiar = document.getElementById('asistente-limpiar');

  const CLAVE = 'hub.asistente.abierto';
  const CADENCIA = 1500;

  let abierto = false;
  let ultimo = null;      // uuid del último mensaje pintado: el sondeo pide sólo lo nuevo
  let latido = 0;
  let enCurso = false;

  // ── Pintado ──────────────────────────────────────────────────────────────

  function escapar(s) {
    return String(s ?? '').replace(/[&<>"']/g, c =>
      ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }

  function pintar(mensajes, reemplazar) {
    if (reemplazar) { hilo.innerHTML = ''; }
    if (!mensajes.length) return;

    const html = mensajes.map(m => {
      const mio = m.rol === 'user';
      // Las herramientas van colapsadas a una línea. El `thinking` y la salida
      // de las herramientas ni llegan: los filtra el hub antes de servirlos.
      const utiles = (m.herramientas || [])
        .map(u => `<span class="util">⚙ ${escapar(u).replace(/^\[|\]$/g, '')}</span>`)
        .join('');
      return `<div class="msj ${mio ? 'mio' : 'suyo'}">${escapar(m.texto)}${utiles}</div>`;
    }).join('');

    hilo.insertAdjacentHTML('beforeend', html);
    ultimo = mensajes[mensajes.length - 1].uuid || ultimo;
    hilo.scrollTop = hilo.scrollHeight;
  }

  function pintarContexto(c) {
    if (!c) { ctx.textContent = ''; ctx.classList.remove('lleno'); return; }
    // El porcentaje es el dato exacto (vía statusline) y el que él quiere ver.
    // Sin él se enseñan los tokens, que es lo que se puede defender: inventar
    // un porcentaje sobre una ventana supuesta sería peor que no dar ninguno.
    if (c.porcentaje != null) {
      ctx.textContent = `${Math.round(c.porcentaje)}%`;
      ctx.classList.toggle('lleno', c.porcentaje >= 70);
    } else if (c.tokens) {
      // Sólo antes del primer statusline, cuando aún no se sabe el tamaño de
      // la ventana. Lleva unidad para que no se lea como un porcentaje raro.
      ctx.textContent = `${Math.round(c.tokens / 1000)}k tok`;
      ctx.classList.remove('lleno');
    } else {
      ctx.textContent = '';
    }
  }

  function pintarLuz(datos) {
    luz.classList.toggle('vivo', !!datos.abierto && !datos.ocupado);
    luz.classList.toggle('pensando', !!datos.ocupado);
    estado.textContent = datos.abierto
      ? (datos.ocupado ? 'pensando…' : '')
      : 'sin abrir';
  }

  // Un cuadro de permisos no se puede contestar tecleando en el chat, y sin
  // enseñarlo la conversación se queda colgada sin motivo aparente: ni
  // pensando, ni respondiendo. Pasó de verdad la primera vez que el asistente
  // lanzó `hub estado` y, en paralelo, un `which hub` que sí pedía permiso.
  function pintarConfirmacion(c) {
    const previo = document.getElementById('asistente-permiso');
    if (!c) { if (previo) previo.remove(); return; }
    if (previo && previo.dataset.peticion === c.peticion.join('\n')) return;
    if (previo) previo.remove();

    const caja2 = document.createElement('div');
    caja2.id = 'asistente-permiso';
    caja2.dataset.peticion = c.peticion.join('\n');
    caja2.innerHTML =
      `<p class="frio">Te pide permiso:</p>`
      + `<pre>${escapar(c.peticion.join('\n'))}</pre>`
      + `<div class="barra"><button class="aceptar" data-r="si">Permitir una vez</button>`
      + `<button class="declinar" data-r="no">No</button></div>`;
    hilo.appendChild(caja2);
    hilo.scrollTop = hilo.scrollHeight;

    caja2.querySelectorAll('button').forEach(b => b.addEventListener('click', async () => {
      // No se ofrece el «no volver a preguntar» de Claude Code: amplía sus
      // permisos para siempre y eso se decide en su settings.json, no aquí.
      await fetch('/api/asistente/responder', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ respuesta: b.dataset.r }),
      });
      caja2.remove();
      refrescar();
    }));
  }

  // ── Sondeo ───────────────────────────────────────────────────────────────

  async function refrescar() {
    if (enCurso) return;
    enCurso = true;
    try {
      const url = ultimo ? `/api/asistente?desde=${encodeURIComponent(ultimo)}` : '/api/asistente';
      const r = await fetch(url);
      const datos = (r && r.ok && await r.json()) || {};
      pintarLuz(datos);
      pintarContexto(datos.contexto);
      pintarConfirmacion(datos.confirmacion);

      const mensajes = datos.mensajes || [];
      const vacio = document.getElementById('asistente-vacio');
      if (vacio && (mensajes.length || datos.abierto)) { hilo.innerHTML = ''; }
      pintar(mensajes, false);
      if (!hilo.innerHTML) {
        hilo.innerHTML = `<p id="asistente-vacio">${datos.abierto
          ? 'Pregúntale algo. Es de consulta: no toca tus proyectos.'
          : 'No está abierto. Escribe y se arranca solo.'}</p>`;
      }
    } catch (e) {
      // Un sondeo fallido no puede romper la página: el hub puede estar
      // reiniciándose y la pestaña tiene que seguir ahí cuando vuelva.
    } finally {
      enCurso = false;
    }
  }

  function sondear(activo) {
    // Cerrado no pide nada. Es una barra en TODAS las pantallas: un sondeo de
    // fondo permanente sería coste puro por algo que no se está mirando.
    if (latido) { clearInterval(latido); latido = 0; }
    if (activo) { refrescar(); latido = setInterval(refrescar, CADENCIA); }
  }

  // ── Abrir y cerrar ───────────────────────────────────────────────────────

  function alternar(valor) {
    abierto = valor === undefined ? !abierto : valor;
    raiz.classList.toggle('abierto', abierto);
    pestana.setAttribute('aria-expanded', abierto ? 'true' : 'false');
    flecha.textContent = abierto ? '▾' : '▴';
    try { localStorage.setItem(CLAVE, abierto ? '1' : '0'); } catch (e) {}
    sondear(abierto);
    if (abierto) caja.focus();
  }

  pestana.addEventListener('click', () => alternar());

  // ── Enviar ───────────────────────────────────────────────────────────────

  async function mandar() {
    const texto = (caja.value || '').trim();
    if (!texto) return;
    caja.value = '';

    // Se arranca solo si no estaba: preguntar es el gesto, abrir la sesión es
    // maquinaria y no debería ser un paso más.
    await fetch('/api/asistente/abrir', { method: 'POST' });
    const r = await fetch('/api/asistente/enviar', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ texto }),
    });
    const d = (r && r.ok && await r.json()) || {};
    if (d.ok === false) {
      HubUI.avisar({ titulo: 'No se pudo enviar', mensaje: d.error || 'sin detalle' });
      caja.value = texto;   // no se pierde lo escrito
    } else if (d.enviado === false) {
      estado.textContent = 'está ocupado, espera a que termine';
      caja.value = texto;
    }
    refrescar();
  }

  enviar.addEventListener('click', mandar);
  caja.addEventListener('keydown', (ev) => {
    // Enter envía, Shift+Enter hace salto de línea. El mensaje llega entero
    // aunque tenga saltos: el hub lo pega de una pieza, no tecla a tecla.
    if (ev.key === 'Enter' && !ev.shiftKey) { ev.preventDefault(); mandar(); }
  });

  // ── Compactar y limpiar ──────────────────────────────────────────────────

  // Viven bajo la rueda, y el menú sólo se cierra solo al pulsar FUERA. Sin
  // esto se quedaba abierto detrás del diálogo de confirmación y seguía abierto
  // al volver.
  const cerrarMenu = (bt) => {
    const m = bt.closest('details.menu');
    if (m) m.open = false;
  };

  btCompact.addEventListener('click', async () => {
    cerrarMenu(btCompact);
    if (!await HubUI.confirmar({
      titulo: 'Compactar su contexto',
      mensaje: 'Le pedirá primero que escriba sus propias instrucciones de '
             + 'compactado y luego ejecutará /compact con ellas. No es reversible.',
      aceptar: 'Compactar',
    })) return;

    estado.textContent = 'preparando el compactado…';
    await fetch('/api/asistente/compactar', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ paso: 'preparar' }),
    });

    // Segundo tiempo: se reintenta hasta que haya contestado. Las instrucciones
    // que escriba son de uso interno y no se enseñan (así lo pidió).
    let intentos = 40;
    const esperar = setInterval(async () => {
      const r = await fetch('/api/asistente/compactar', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ paso: 'ejecutar' }),
      });
      const d = (r && r.ok && await r.json()) || {};
      if (d.ok || --intentos <= 0) {
        clearInterval(esperar);
        estado.textContent = d.ok ? '' : 'no llegó a compactar';
        ultimo = null;
        refrescar();
      }
    }, 2000);
  });

  btLimpiar.addEventListener('click', async () => {
    cerrarMenu(btLimpiar);
    if (!await HubUI.confirmar({
      titulo: 'Limpiar su contexto',
      mensaje: 'Olvida la conversación entera. No es reversible.',
      aceptar: 'Limpiar', peligro: true,
    })) return;
    await fetch('/api/asistente/limpiar', { method: 'POST' });
    ultimo = null;
    hilo.innerHTML = '';
    refrescar();
  });

  // Arranca como se dejó la última vez (decisión 38). Por defecto, plegado:
  // ocupa la mitad de la pantalla y quien no lo pidió no debería encontrárselo.
  let recordado = '0';
  try { recordado = localStorage.getItem(CLAVE) || '0'; } catch (e) {}
  alternar(recordado === '1');
})();
