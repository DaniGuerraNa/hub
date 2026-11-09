/* El escenario del modo monitor (C-0202, decisión 389).
 *
 * El personaje va al puesto de lo que hace: a Mensajes cuando lee lo que te
 * escribieron, a la Agenda cuando mira tu calendario, junto a «Te espera»
 * cuando algo necesita tu sí. Lleva encima el rótulo de lo que hace, y al
 * volver a su mesa trae el objeto del puesto del que viene.
 *
 * No sabe nada por su cuenta. Envuelve al personaje de avatar-secretario.js
 * sin tocarlo: lo que hace lo lee de los atributos que ese script pone en su
 * raíz (`data-estado`, `data-gesto`), con sus 600 ms y su prioridad ya
 * resueltos, y lo que espera de ti (`espera.asuntos.nuevas`), del evento
 * `secretario:estado` que emite chat-secretario.js. Ningún sondeo propio.
 *
 * Qué puesto toca lo dice la tabla de `personaje.escenario()` (en
 * `data-puestos`); `puestoDe` es `personaje.puesto_de` aplicada a ella, y un
 * test compara las dos con todos los estados y gestos.
 *
 * No distrae ni gasta (389):
 * - se mueve sólo cuando cambia el puesto, no con cada cosa que le cuentan;
 * - con «reducir movimiento», cambia de sitio sin andar;
 * - con la pestaña oculta no programa nada: el cambio espera a que vuelvas y
 *   entonces se pone en su sitio, sin andar.
 */
(() => {
  // Lo que tarda en cruzar el escenario; el CSS lo lee de `--esc-andar`.
  const ANDAR_MS = 1100;
  const PUESTO_VALIDO = /^[a-z]+$/;

  /* `personaje.puesto_de`, con su tabla. */
  function puestoDe(mapa, estado, gesto, nuevas) {
    const m = mapa || {};
    const reposo = m.reposo || 'escritorio';
    if (estado === 'trabajando') return (m.gesto || {})[gesto] || reposo;
    const puesto = (m.estado || {})[estado] || reposo;
    return nuevas > 0 && (m.ceden || []).includes(puesto) ? 'asuntos' : puesto;
  }

  /* Lo que te espera sin haberlo visto. Sin la cifra (un hub sin asuntos), 0. */
  function nuevasDe(espera) {
    const n = Number(espera && espera.asuntos && espera.asuntos.nuevas);
    return Number.isFinite(n) && n > 0 ? Math.floor(n) : 0;
  }

  const leer = (json) => { try { return JSON.parse(json || 'null'); } catch (e) { return null; } };

  /* Dónde se para en un puesto: el centro de abajo de su sitio, relativo al
   * escenario, y lo ancho que es el puesto (su rótulo no se sale de él). */
  function medirEnPagina(escena, puesto) {
    const caja = escena.querySelector(`[data-puesto="${puesto}"]`);
    const sitio = (caja && caja.querySelector('[data-sitio]')) || caja;
    if (!sitio || typeof sitio.getBoundingClientRect !== 'function') return { x: 0, y: 0, ancho: 0 };
    const e = escena.getBoundingClientRect();
    const s = sitio.getBoundingClientRect();
    return { x: Math.round((s.left || 0) - (e.left || 0) + (s.width || 0) / 2),
             y: Math.round((s.top || 0) - (e.top || 0) + (s.height || 0)),
             ancho: Math.round(caja.getBoundingClientRect().width || 0) };
  }

  /* El hueco libre del puesto más justo: entre su letrero y donde él se para.
   * El CSS saca de aquí su tamaño, para que con el rótulo encima quepa en
   * todos sin tapar el nombre (medido en un 1366×768, donde a ojo no cabía). */
  function huecoEnPagina(escena) {
    let menor = Infinity;
    for (const caja of escena.querySelectorAll('[data-puesto]')) {
      const letrero = caja.querySelector('[data-letrero]');
      const sitio = caja.querySelector('[data-sitio]');
      if (!letrero || !sitio) continue;
      menor = Math.min(menor, sitio.getBoundingClientRect().top - letrero.getBoundingClientRect().bottom);
    }
    return Number.isFinite(menor) ? Math.floor(menor) : 0;
  }

  /* Un escenario. `op` deja cambiar el reloj, la medida, lo oculto y el
   * movimiento reducido en las pruebas. */
  function crear(escena, op) {
    op = op || {};
    const programar = op.programar || ((f, ms) => setTimeout(f, ms));
    const cancelar = op.cancelar || ((t) => clearTimeout(t));
    const oculta = op.oculta || (() => !!document.hidden);
    const medir = op.medir || medirEnPagina;
    const hueco = op.hueco || huecoEnPagina;
    // Se pregunta en cada cambio y no sólo al cargar: el sistema puede pedirlo después.
    const reducido = () => (op.reducido !== undefined ? op.reducido
      : !!(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches));
    const q = (sel) => (escena.querySelector ? escena.querySelector(sel) : null);
    const andador = q('[data-andador]');
    const raiz = q('[data-personaje]');
    const trae = q('[data-trae] use');
    const cifra = q('[data-nuevas]');
    const mapa = leer(escena.dataset && escena.dataset.puestos) || {};
    let nuevas = nuevasDe(leer(raiz && raiz.dataset && raiz.dataset.espera));
    let actual = null, pendiente = null, reloj = null, x = null;

    if (reducido() && escena.classList) escena.classList.add('sin-movimiento');
    if (andador && andador.style) andador.style.setProperty('--esc-andar', `${ANDAR_MS}ms`);

    function medirHueco() {
      const h = hueco(escena);
      if (h > 0 && escena.style) escena.style.setProperty('--esc-hueco', `${h}px`);
    }

    function destino() {
      const d = (raiz && raiz.dataset) || {};
      const p = puestoDe(mapa, d.estado || 'quieto', d.gesto || '', nuevas);
      return PUESTO_VALIDO.test(p) ? p : (mapa.reposo || 'escritorio');
    }

    function situar(p) {
      const c = medir(escena, p);
      const antes = x;
      x = c.x;
      if (andador) {
        andador.style.setProperty('--esc-x', `${c.x}px`);
        andador.style.setProperty('--esc-y', `${c.y}px`);
        if (c.ancho > 0) andador.style.setProperty('--esc-cabe', `${c.ancho}px`);
        // Mira hacia donde va: se inclina en el sentido de la marcha.
        if (antes !== null && c.x !== antes) andador.dataset.hacia = c.x < antes ? 'izq' : 'der';
      }
      // `data-en` y no `data-puesto`: ése es de los puestos, y lo buscan por él.
      escena.dataset.en = p;
      const cajas = escena.querySelectorAll ? escena.querySelectorAll('[data-puesto]') : [];
      for (const caja of cajas) {
        if (caja.classList) caja.classList.toggle('aqui', caja.dataset.puesto === p);
      }
      actual = p;
    }

    /* Al sitio sin andar: la primera vez, con movimiento reducido, al volver
     * a la pestaña y si cambia el tamaño. La transición se quita y se vuelve a
     * poner leyendo la medida en medio, sin ningún temporizador. */
    function colocar(p) {
      if (!andador) { situar(p); return; }
      andador.classList.add('sin-transicion');
      situar(p);
      void andador.offsetWidth;
      andador.classList.remove('sin-transicion');
    }

    function andar(p) {
      const desde = actual;
      situar(p);
      // Vuelve de un puesto a su mesa o a tus asuntos: trae lo de allí.
      const vuelve = (p === (mapa.reposo || 'escritorio') || p === 'asuntos')
        && desde && desde !== (mapa.reposo || 'escritorio') && desde !== 'asuntos';
      const acc = vuelve ? (mapa.accesorio || {})[desde] : '';
      if (acc && PUESTO_VALIDO.test(acc)) {
        if (trae) trae.setAttribute('href', `#acc-${acc}`);
        andador.dataset.trae = desde;
      } else {
        delete andador.dataset.trae;
      }
      andador.classList.add('andando');
      if (reloj !== null) cancelar(reloj);
      reloj = programar(() => {
        reloj = null;
        andador.classList.remove('andando');
        delete andador.dataset.trae;
      }, ANDAR_MS);
    }

    /* Mira si cambió de puesto, y sólo entonces se mueve. */
    function revisar() {
      const p = destino();
      if (p === actual) { pendiente = null; return; }
      if (actual === null) { colocar(p); return; }
      // Oculta, no se programa nada: se apunta y se pone al volver.
      if (oculta()) { pendiente = p; return; }
      if (reducido() || !andador) colocar(p);
      else andar(p);
    }

    function pintarNuevas() {
      if (!cifra) return;
      cifra.textContent = nuevas ? `${nuevas} ${nuevas === 1 ? 'nueva' : 'nuevas'}` : '';
      cifra.hidden = !nuevas;
    }

    function recibir(d) {
      if (!d || typeof d !== 'object') return;
      if ('espera' in d) { nuevas = nuevasDe(d.espera); pintarNuevas(); }
      // Sin hub, la cifra de antes ya no se puede defender (regla 13): vuelve
      // con el siguiente sondeo que conteste.
      if (d.red === 'caida' && nuevas) { nuevas = 0; pintarNuevas(); }
      revisar();
    }

    function visibilidad(visible) {
      if (!visible || pendiente === null) return;
      pendiente = null;
      medirHueco();
      const p = destino();
      if (p !== actual) colocar(p);
    }

    /* Otro tamaño, otras medidas: al mismo puesto, sin andar. */
    function recolocar() {
      if (oculta()) return;
      medirHueco();
      if (actual !== null) colocar(actual);
    }

    pintarNuevas();
    medirHueco();
    revisar();
    return { recibir, revisar, visibilidad, recolocar, puesto: () => actual };
  }

  window.HubEscenario = { ANDAR_MS, puestoDe, nuevasDe, crear };

  const escena = document.querySelector('[data-escenario]');
  if (!escena) return;
  const s = crear(escena);
  // avatar-secretario.js se carga antes y oye el evento primero: cuando
  // llega aquí, la raíz ya dice lo que hace.
  document.addEventListener('secretario:estado', (e) => s.recibir((e && e.detail) || {}));
  // Lo que el personaje pinta pasados sus 600 ms llega sin evento: se mira
  // cuando cambia su raíz.
  const raiz = escena.querySelector('[data-personaje]');
  if (raiz && typeof MutationObserver === 'function') {
    new MutationObserver(() => s.revisar()).observe(raiz, { attributes: true, attributeFilter: ['data-estado', 'data-gesto'] });
  }
  document.addEventListener('visibilitychange', () => s.visibilidad(!document.hidden));
  if (typeof ResizeObserver === 'function') new ResizeObserver(() => s.recolocar()).observe(escena);
  else window.addEventListener('resize', () => s.recolocar());
})();
