/* Las consultas del canal, en el lado de /trabajo.
 *
 * Lo que se preguntó fuera y lo que contestaron, junto al trabajo al que
 * pertenece. Antes eso sólo se veía en `/canal`, que es la pantalla de
 * administrar el canal —quién puede qué— y no la de trabajar: para saber si ya
 * te habían contestado una duda había que salir del taller.
 *
 * 🔴 Hoja propia y no un lienzo con etiqueta. Una pregunta tiene su propio
 * ciclo —sale, se contesta, vuelve al panel— y meterla en el motor de lienzos
 * obligaría a inventarle un tipo y a duplicar ese estado en dos sitios que
 * luego divergen. Comparten el sitio, no el modelo.
 *
 * Tampoco roba el foco: cuando llega una respuesta se enciende el punto de la
 * pestaña y la abres tú (principio 9). Vive en /trabajo, así que si revienta al
 * arrancar se lleva la terminal por delante sin ningún síntoma (regla dura 11):
 * por eso se prueba ejecutándolo.
 */
(function () {
  const lista = document.getElementById('consultas-lista');
  const punto = document.getElementById('consultas-punto');
  const pestanas = document.querySelectorAll('.pest-lado button');
  if (!lista) return;

  const CADENCIA = 6000;
  let respondidasVistas = new Set();
  let abierta = false;
  let latido = 0;
  let filtro = 'todas';
  let ultimas = [];

  function escapar(s) {
    return String(s ?? '').replace(/[&<>"']/g, c =>
      ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }

  /* El mismo criterio que los lienzos: el proyecto sale de la ventana que se
   * está mirando, no de la que abrió la página. Cambiar de pestaña de tmux
   * cambia de trabajo, y sin esto verías las consultas de otro. */
  function proyectoActual() {
    const bloque = document.querySelector('.por-ventana:not([hidden])');
    if (bloque && bloque.dataset.proyecto) return bloque.dataset.proyecto;
    const taller = document.getElementById('taller');
    return (taller && taller.dataset.proyecto) || '';
  }

  function slotActual() {
    const nota = document.querySelector('.por-ventana:not([hidden]) .nota-texto');
    return nota ? nota.dataset.slot : '';
  }

  function cuando(iso) {
    if (!iso) return '';
    const min = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
    if (!isFinite(min) || min < 0) return '';
    if (min < 60) return `hace ${min} min`;
    if (min < 1440) return `hace ${Math.round(min / 60)} h`;
    return `hace ${Math.round(min / 1440)} d`;
  }

  // Las mismas palabras que en /canal: dos vocabularios para los mismos
  // estados obligan a traducir mentalmente entre dos pantallas del mismo hub.
  const COLOR = {
    entregada: 'ok', respondida: 'ok',
    vencida: 'riesgo', archivada: 'riesgo', 'sin-confirmar': 'riesgo',
  };

  /* Contestada es tener respuesta, no estar en un estado concreto.
   *
   * Los estados son del transporte —`entregada` dice que llegó al panel,
   * `sin-confirmar` que se escribió sin poder confirmarlo— y filtrar por ellos
   * dejaría fuera respuestas que existen. Lo que se pregunta aquí es «¿ya me
   * contestaron?», y eso lo dice el campo. */
  const contestada = (q) => !!(q.respuesta && q.respuesta.trim());

  function filtrar(preguntas) {
    if (filtro === 'pendientes') return preguntas.filter(q => !contestada(q));
    if (filtro === 'contestadas') return preguntas.filter(contestada);
    return preguntas;
  }

  function pintar(todas, slot) {
    const preguntas = filtrar(todas);
    if (!preguntas.length) {
      lista.innerHTML = '<p class="tenue">' + (
        filtro === 'pendientes' ? 'Ninguna esperando respuesta.'
        : filtro === 'contestadas' ? 'Todavía no ha contestado nadie.'
        : 'Nada preguntado fuera en este proyecto. '
          + 'Lo que Claude consulte por el canal aparecerá aquí con su respuesta.'
      ) + '</p>';
      return;
    }
    lista.innerHTML = preguntas.map(q => {
      // Las de OTRO slot del mismo proyecto se atenúan en vez de esconderse:
      // `--slot` es opcional al preguntar, así que filtrar por slot escondería
      // preguntas reales y el panel diría «no hay» sobre cosas que sí hay.
      const ajena = slot && q.slot_id && String(q.slot_id) !== String(slot);
      return `
      <div class="consulta ${ajena ? 'ajena' : ''}">
        <div class="quien">
          #${q.id} · ${q.quien ? 'a ' + escapar(q.quien) : 'para ti'}
          ${q.lote ? ' · en lote' : ''}
          ${ajena ? ' · de otro slot' : ''}
          <span class="insignia ${COLOR[q.estado] || 'espera'}">${escapar(q.estado)}</span>
          ${cuando(q.creada_en)}
        </div>
        <div class="texto">${escapar(q.texto)}</div>
        ${q.respuesta ? `<div class="resp">${escapar(q.respuesta)}</div>` : ''}
        ${q.estado === 'sin-confirmar'
          ? '<div class="quien" style="color:var(--alerta)">Se escribió en el panel'
            + ' sin poder confirmar que saliera. No se reintenta.</div>'
          : ''}
      </div>`;
    }).join('');
  }

  async function refrescar() {
    const proyecto = proyectoActual();
    if (!proyecto) { pintar([], ''); return; }
    try {
      const r = await fetch(`/api/preguntas?proyecto=${encodeURIComponent(proyecto)}`);
      if (!r || !r.ok) throw new Error('el hub no contestó');
      const datos = await r.json();
      const preguntas = datos.preguntas || [];

      // El punto se enciende con lo que se ha CONTESTADO desde que miraste, no
      // con lo que se ha preguntado: preguntar lo hace Claude y ya lo sabes;
      // que alguien conteste es la novedad que justifica ir a mirar.
      const contestadas = preguntas.filter(q => q.respuesta).map(q => q.id);
      if (!abierta && contestadas.some(id => !respondidasVistas.has(id))) {
        if (punto) punto.classList.add('hay');
      }
      if (abierta) contestadas.forEach(id => respondidasVistas.add(id));

      ultimas = preguntas;
      pintar(preguntas, slotActual());
    } catch (e) {
      if (!lista.querySelector('.consulta')) {
        lista.innerHTML = '<p class="tenue">No se pudo consultar. Se reintenta solo.</p>';
      }
    }
  }

  document.querySelectorAll('[data-filtro]').forEach(bt =>
    bt.addEventListener('click', () => {
      filtro = bt.dataset.filtro;
      document.querySelectorAll('[data-filtro]').forEach(o =>
        o.classList.toggle('on', o === bt));
      refrescar();
    }));

  pestanas.forEach(bt => bt.addEventListener('click', () => {
    abierta = bt.dataset.hoja === 'consultas';
    if (abierta) {
      if (punto) punto.classList.remove('hay');
      refrescar();
    }
  }));

  // Se sondea con la hoja cerrada, y despacio: es lo que enciende el punto.
  refrescar();
  latido = setInterval(refrescar, CADENCIA);
  window.addEventListener('beforeunload', () => clearInterval(latido));
})();
