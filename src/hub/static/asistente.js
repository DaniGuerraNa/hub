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
      // Lo suyo con formato —enlaces del hub, negritas—; lo tuyo, tal cual.
      const formato = !mio && window.formatearMensaje ? window.formatearMensaje : escapar;
      return `<div class="msj ${mio ? 'mio' : 'suyo'}">${formato(m.texto)}${utiles}</div>`;
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

  /* El aviso vive encima del hilo y no lo pisa: la conversación es lo que uno
   * está leyendo, y borrarla para poner un error sería cambiar un problema por
   * dos. Se retira solo en cuanto un sondeo vuelve bien. */
  function avisar(texto) {
    let banda = document.getElementById('asistente-aviso');
    if (!texto) { if (banda) banda.remove(); return; }
    if (!banda) {
      banda = document.createElement('div');
      banda.id = 'asistente-aviso';
      banda.className = 'asistente-aviso';
      hilo.parentNode.insertBefore(banda, hilo);
    }
    banda.textContent = texto;
  }

  /* Por qué falló, en una frase que se pueda leer.
   *
   * El hub contesta JSON en `/api/…` con su propio motivo dentro —«la clave
   * conexiones está dos veces, línea 282»—, y ésa es justo la frase que hace
   * falta. Si no lo trae, al menos el código: «el hub respondió 422» ya dice
   * dónde mirar, y es infinitamente más que el silencio de antes. */
  async function porQue(r) {
    if (!r) return 'el hub no respondió';
    try {
      const d = await r.clone().json();
      // Las dos primeras líneas con algo, no sólo la primera: la primera nombra
      // el archivo y la segunda dice QUÉ le pasa —«la clave conexiones está dos
      // veces»—, que es la mitad con la que se arregla.
      if (d && d.error) {
        return String(d.error).split('\n').map(s => s.trim())
          .filter(Boolean).slice(0, 2).join(' — ');
      }
    } catch {}
    return `el hub respondió ${r.status}`;
  }

  // ── Sondeo ───────────────────────────────────────────────────────────────

  async function refrescar() {
    if (enCurso) return;
    enCurso = true;
    try {
      const url = ultimo ? `/api/asistente?desde=${encodeURIComponent(ultimo)}` : '/api/asistente';
      const r = await fetch(url);
      // Un 500 daba `datos = {}`, que abajo es indistinguible de «no hay nada
      // que contar». Se convierte en error para que lo recoja el catch y se
      // pueda DECIR, en vez de quedarse callado con cara de estar cargando.
      if (!r || !r.ok) throw new Error(await porQue(r));
      const datos = await r.json();
      avisar(null);   // volvió: se retira el aviso anterior, si lo había
      pintarLuz(datos);
      pintarContexto(datos.contexto);
      pintarConfirmacion(datos.confirmacion);

      const mensajes = datos.mensajes || [];
      // 🔴 El marcador se retira en cuanto LLEGA una respuesta, tenga mensajes o
      // no. Antes se pedía además `mensajes.length || datos.abierto`, y con las
      // dos cosas falsas —el asistente declarado pero nunca arrancado, que es el
      // estado de cualquiera recién instalado— no se limpiaba; y como el hilo no
      // quedaba vacío, el `else` de abajo tampoco entraba. El panel se quedaba
      // en «Cargando…» para siempre, justo cuando lo que había que leer era «no
      // está abierto, escribe y se arranca solo».
      //
      // Vaciar aquí no puede llevarse ningún mensaje por delante: el marcador
      // sólo existe mientras no se haya pintado ninguno.
      if (document.getElementById('asistente-vacio')) { hilo.innerHTML = ''; }
      pintar(mensajes, false);
      if (!hilo.innerHTML) {
        hilo.innerHTML = `<div id="asistente-vacio"><p>${datos.abierto
          ? 'Pregúntale algo. Es de consulta: no toca tus proyectos.'
          : 'No está abierto. Escribe y se arranca solo.'}</p>${sugerencias()}</div>`;
      }
    } catch (e) {
      // Un sondeo fallido no puede romper la página: el hub puede estar
      // reiniciándose y la pestaña tiene que seguir ahí cuando vuelva. Y la
      // conversación NO se borra por un sondeo perdido.
      //
      // 🔴 Pero el aviso va SIEMPRE, no sólo con el hilo vacío. Ésa era la
      // versión anterior, y por eso esto se vivió en silencio: con diez
      // mensajes ya pintados no había ningún `#asistente-vacio`, así que un
      // 422 en cada sondeo no cambiaba un solo píxel. Se preguntó algo, no
      // apareció nada, no apareció ningún error, y hubo que abrir la terminal
      // para descubrir que el hub llevaba rato sin poder leer su registro.
      avisar(String(e && e.message || e));
      if (document.getElementById('asistente-vacio')) {
        hilo.innerHTML = '<p id="asistente-vacio">No se pudo hablar con el hub.'
          + ' Se reintenta solo.</p>';
      }
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

  // ── Por dónde empezar ────────────────────────────────────────────────────

  // Con el chat vacío, quien acaba de instalar no sabe qué se le puede pedir.
  // Tres preguntas que se contestan en cualquier pantalla (decisión 271).
  const SUGERENCIAS = [
    '¿Qué hago primero?',
    '¿Qué es esta pantalla y qué puedo hacer aquí?',
    'Quiero registrar un proyecto que ya tengo',
  ];

  function sugerencias() {
    return '<div class="sugerencias">' + SUGERENCIAS.map(p =>
      `<button type="button" class="sugerencia" data-pregunta="${escapar(p)}">${escapar(p)}</button>`
    ).join('') + '</div>';
  }

  hilo.addEventListener('click', (e) => {
    const boton = e.target && e.target.closest ? e.target.closest('[data-pregunta]') : null;
    if (boton) preguntar(boton.dataset.pregunta);
  });

  function preguntar(texto) {
    alternar(true);
    caja.value = texto;
    mandar();
  }

  // Para que otra pantalla —la guía— pueda abrir el chat con una pregunta hecha.
  window.HubAsistente = { preguntar };

  // ── Enviar ───────────────────────────────────────────────────────────────

  async function mandar() {
    const texto = (caja.value || '').trim();
    if (!texto) return;
    caja.value = '';
    // Desde qué pantalla se pregunta: sin esto «¿qué es esto?» no tiene
    // respuesta, porque el asistente no ve la web. El hub la pone delante del
    // mensaje y el chat la quita al pintarlo.
    const pagina = typeof location !== 'undefined' ? location.pathname + location.search : '';
    const titulo = typeof document !== 'undefined' ? (document.title || '') : '';

    // Se arranca solo si no estaba: preguntar es el gesto, abrir la sesión es
    // maquinaria y no debería ser un paso más.
    await fetch('/api/asistente/abrir', { method: 'POST' });
    const r = await fetch('/api/asistente/enviar', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ texto, pagina, titulo }),
    });
    // 🔴 Un HTTP que no es `ok` se quedaba en `{}`, y entonces ninguna de las
    // dos ramas de abajo entraba: ni se decía nada ni se devolvía lo escrito.
    // La pregunta desaparecía de la caja y no pasaba nada más. Es el peor de
    // los tres fallos de este archivo, porque además se lleva el texto.
    if (!r || !r.ok) {
      const porq = await porQue(r);
      avisar(porq);
      HubUI.avisar({ titulo: 'No se pudo enviar', mensaje: porq });
      caja.value = texto;
      return;
    }
    const d = (await r.json()) || {};
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
