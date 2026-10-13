/* Mensajes programados, en el lado de /trabajo.
 *
 * Un texto que entra en la ventana de este slot a una hora. Vive junto al
 * trabajo al que pertenece y no en una pantalla aparte, por lo mismo que las
 * consultas: programar algo para «cuando siga con esto» es una idea que se tiene
 * mirando esto, no navegando a otro sitio.
 *
 * 🔴 Lo que esta pantalla tiene que hacer bien es UNA cosa: la hora. Se escribe
 * en la hora de quien mira (`datetime-local`, sin zona) y se manda en UTC, que
 * es como la guarda el hub. La conversión se hace aquí porque el navegador es el
 * único que sabe en qué zona está quien la escribió; el servidor RECHAZA una
 * hora sin zona en vez de suponer una. En esta máquina (CST) suponer mal no es
 * un detalle de formato: son seis horas entre lo que alguien quiso y lo que
 * pasaría.
 *
 * Vive en /trabajo, así que si revienta al arrancar se lleva la terminal por
 * delante sin ningún síntoma visible (regla dura 11): por eso se prueba
 * ejecutándolo, no comprobando que la página da 200.
 */
(function () {
  const lista = document.getElementById('programados-lista');
  const forma = document.getElementById('programar-forma');
  const sinSlot = document.getElementById('programar-sin-slot');
  const caja = document.getElementById('programar-texto');
  const cuandoInput = document.getElementById('programar-cuando');
  const boton = document.getElementById('programar-enviar');
  const estado = document.getElementById('programar-estado');
  const pestanas = document.querySelectorAll('.pest-lado button');
  if (!lista) return;

  const CADENCIA = 10000;
  /* Lo que se espera a que la página marque la ventana activa: 250 ms por
   * intento, doce como mucho. 🔴 El tope no es decoración — sin él, una sesión
   * sin ninguna ventana (no hay bloque que marcar, nunca) dejaría esto
   * sondeando a cuatro veces por segundo mientras la pestaña siga abierta. Tres
   * segundos son de sobra para una ida y vuelta contra 127.0.0.1, y al agotarse
   * se contesta lo que se vea, que a esas alturas ya es un dato y no un hueco. */
  const ESPERA_BLOQUE = 250;
  const INTENTOS_BLOQUE = 12;
  let porMirar = INTENTOS_BLOQUE;
  let latido = 0;
  let abierta = false;

  function escapar(s) {
    return String(s ?? '').replace(/[&<>"']/g, c =>
      ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }

  /* El slot sale de la ventana que se está MIRANDO, no de la que abrió la
   * página: cambiar de pestaña de tmux cambia de trabajo, y sin esto
   * programarías un mensaje para el panel de otro. */
  /* 🔴 `.viendo`, NO `:not([hidden])`. La plantilla pinta todos los bloques con
   * el atributo `hidden` y revela el activo poniéndole esta clase; el atributo
   * no se quita nunca, así que `:not([hidden])` no casa con ninguno. El síntoma
   * era «esta ventana no pertenece a ningún slot» sobre una ventana que sí
   * tiene, con la pestaña «Nota» funcionando al lado.
   *
   * 🔴 Y TRES respuestas, no dos. `null` es «todavía no lo sé», y es distinto de
   * «no tiene slot»:
   *
   *   - el id      → esta ventana es de ese slot
   *   - ''         → hay bloque y no tiene slot. Eso sí se puede afirmar.
   *   - null       → no hay bloque aún. La clase `viendo` la pone el script de
   *                  la página DESPUÉS de pedir las ventanas al hub, o sea tras
   *                  una ida y vuelta de red, y esto corre antes. Decir «no
   *                  pertenece a ningún slot» en ese hueco es afirmar algo que
   *                  no se ha mirado — el mismo error que el estado `nueva` de
   *                  la franja de pestañas existe para no cometer.
   */
  function slotActual() {
    const bloque = document.querySelector('.por-ventana.viendo');
    if (!bloque) return null;
    const nota = bloque.querySelector('.nota-texto');
    return nota ? nota.dataset.slot : '';
  }

  /* 🔴 La conversión que justifica este archivo.
   *
   * Un `datetime-local` no tiene zona: «2026-09-12T09:00» significa las nueve
   * DONDE ESTÁ quien lo escribió. `new Date()` lo interpreta en la zona del
   * navegador —que es justo la suya— y `toISOString()` lo pasa a UTC. Mandar el
   * valor crudo sería mandar una hora sin decir de dónde, y entonces alguien
   * tendría que adivinarla. */
  function aUTC(valor) {
    if (!valor) return '';
    const fecha = new Date(valor);
    return isFinite(fecha.getTime()) ? fecha.toISOString() : '';
  }

  /* Y la vuelta: lo que llega es UTC y se enseña en la hora de quien mira. Una
   * lista que dijera «15:00 UTC» obligaría a restar seis a mano cada vez. */
  function horaLocal(iso) {
    const fecha = new Date(iso);
    if (!isFinite(fecha.getTime())) return escapar(iso);
    const dos = (n) => String(n).padStart(2, '0');
    return `${dos(fecha.getDate())}/${dos(fecha.getMonth() + 1)} `
         + `${dos(fecha.getHours())}:${dos(fecha.getMinutes())}`;
  }

  /* Las mismas palabras que usa el hub por dentro: dos vocabularios para los
   * mismos estados obligan a traducir mentalmente. */
  const COLOR = {
    entregado: 'ok',
    'no-entregado': 'riesgo', caducado: 'riesgo',
    'sin-confirmar': 'riesgo', cancelado: 'riesgo',
    entregando: 'espera',
  };

  function pintar(mensajes) {
    if (!mensajes.length) {
      lista.innerHTML = '<p class="tenue">Nada programado para este slot.</p>';
      return;
    }
    lista.innerHTML = mensajes.map(m => `
      <div class="consulta programado">
        <div class="quien">
          ${m.estado === 'pendiente'
            ? `<button type="button" class="cancelar" data-cancelar="${m.id}"
                       title="Cancelar este mensaje">cancelar</button>`
            : ''}
          ${horaLocal(m.cuando)}
          <span class="insignia ${COLOR[m.estado] || 'espera'}">${escapar(m.estado)}</span>
        </div>
        <div class="texto">${escapar(m.texto)}</div>
        ${m.motivo ? `<div class="motivo">${escapar(m.motivo)}</div>` : ''}
      </div>`).join('');
  }

  /* Los tres estados de `slotActual`, cada uno con SU pantalla. Antes eran tres
   * respuestas y dos pantallas, y esa cuenta que no cuadra es todo el fallo.
   *
   * 🔴 El síntoma, dicho por él: «me dice "Nada programado para este slot", y
   * parpadea y muestra el texto de que la ventana no pertenece a un slot, y
   * repite». Sale de una línea: `porMirar` se reiniciaba SIEMPRE, también
   * cuando los doce intentos se habían agotado sin saberlo. Entonces «no lo sé»
   * se contaba como «no tiene slot» —se ocultaba el formulario y salían los dos
   * avisos— y al latido siguiente volvían los tres segundos en blanco. Cada diez
   * segundos, para siempre.
   *
   * Y los dos avisos se contradecían: uno decía que no hay slot y el otro
   * hablaba «de este slot». Cuando no hay slot, la lista no tiene nada que
   * decir; el aviso de al lado ya lo dice entero. */
  function noSeSabe() {
    if (forma) forma.hidden = true;
    if (sinSlot) sinSlot.hidden = true;
    if (lista) {
      lista.innerHTML = '<p class="tenue">No se ve qué ventana estás mirando: '
        + 'puede que acabe de abrirse y todavía no esté en el último muestreo. '
        + 'Se reintenta solo.</p>';
    }
  }

  async function refrescar() {
    const slot = slotActual();
    if (slot === null) {
      if (porMirar > 0) {
        /* Todavía no se sabe. No se afirma nada y se vuelve a mirar enseguida:
         * esperar al latido dejaría el aviso equivocado en pantalla diez
         * segundos, que es tiempo de sobra para leerlo y creérselo. */
        porMirar--;
        if (forma) forma.hidden = true;
        if (sinSlot) sinSlot.hidden = true;
        if (lista) lista.innerHTML = '';
        setTimeout(refrescar, ESPERA_BLOQUE);
        return;
      }
      /* Agotados los intentos SIGUE sin saberse, que no es lo mismo que «no
       * tiene slot»: la ventana que se mira no está en el último muestreo. Se
       * dice eso, y se dice UNA vez — `porMirar` se queda a cero, así que el
       * latido siguiente vuelve aquí sin repetir los tres segundos en blanco.
       * En cuanto aparezca el bloque, la rama de abajo lo devuelve a doce. */
      noSeSabe();
      return;
    }
    porMirar = INTENTOS_BLOQUE;
    if (forma) forma.hidden = !slot;
    if (sinSlot) sinSlot.hidden = !!slot;
    /* Sin slot no hay nada que listar, y «Nada programado para este slot» sobre
     * una ventana sin slot es afirmar que hay un slot. */
    if (!slot) { if (lista) lista.innerHTML = ''; return; }
    try {
      const r = await fetch(`/api/programados?slot=${encodeURIComponent(slot)}`);
      if (!r || !r.ok) throw new Error('el hub no contestó');
      pintar((await r.json()) || []);
    } catch (e) {
      /* Sólo si no hay nada pintado: pisar una lista buena con un error de red
       * pasajero es cambiar información por ruido. */
      if (!lista.querySelector('.programado')) {
        lista.innerHTML = '<p class="tenue">No se pudo consultar. Se reintenta solo.</p>';
      }
    }
  }

  function decir(texto) {
    if (estado) estado.textContent = texto || '';
  }

  async function programar() {
    const slot = slotActual();
    const texto = (caja && caja.value || '').trim();
    const cuando = aUTC(cuandoInput && cuandoInput.value);
    /* Se comprueba aquí además de en el servidor porque el aviso llega antes y
     * junto al campo. La comprobación que MANDA es la del servidor: ésta es
     * comodidad, no la garantía. */
    if (!texto) { decir('Escribe el mensaje.'); return; }
    if (!cuando) { decir('Pon la hora.'); return; }

    decir('Programando…');
    try {
      const r = await fetch('/api/programado', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ slot_id: Number(slot), texto, cuando }),
      });
      const d = (await r.json().catch(() => ({}))) || {};
      if (!d.ok) {
        /* El motivo del hub, no un «no se pudo» genérico: aquí los motivos son
         * accionables (la hora no se entendió, el slot no existe). */
        decir('');
        HubUI.avisar({ titulo: 'No se pudo programar',
                       mensaje: d.error || `el hub respondió ${r.status}` });
        return;
      }
      /* El texto se limpia sólo cuando el hub confirma. Si fallara y lo hubiera
       * borrado antes, se perdería lo escrito sin que nada lo dijera — el fallo
       * que ya mordió en el asistente (decisión 196). */
      if (caja) caja.value = '';
      decir('Programado.');
      refrescar();
    } catch (e) {
      decir('');
      HubUI.avisar({ titulo: 'No se pudo programar', mensaje: String(e && e.message || e) });
    }
  }

  if (boton) boton.addEventListener('click', programar);

  lista.addEventListener('click', async (e) => {
    const id = e.target && e.target.dataset ? e.target.dataset.cancelar : null;
    if (!id) return;
    try {
      const r = await fetch(`/api/programado/${encodeURIComponent(id)}/cancelar`,
                            { method: 'POST' });
      const d = (await r.json().catch(() => ({}))) || {};
      if (!d.ok) {
        HubUI.avisar({ titulo: 'No se pudo cancelar',
                       mensaje: d.error || `el hub respondió ${r.status}` });
      }
    } catch (err) {
      HubUI.avisar({ titulo: 'No se pudo cancelar', mensaje: String(err) });
    }
    refrescar();
  });

  pestanas.forEach(bt => bt.addEventListener('click', () => {
    abierta = bt.dataset.hoja === 'programados';
    if (abierta) refrescar();
  }));

  /* Se sondea también con la hoja cerrada, pero despacio: lo que cambia solo es
   * el estado —un pendiente que pasa a entregado o a caducado—, y abrir la
   * pestaña para encontrarse una lista vieja es peor que el sondeo. Sin punto de
   * aviso: nada automático reclama atención aquí (principio 9). */
  refrescar();
  latido = setInterval(refrescar, CADENCIA);
  window.addEventListener('beforeunload', () => clearInterval(latido));
})();
