/* El personaje del secretario (C-0166, decisión 358).
 *
 * Enseña lo que hace, y sólo lo que hace. Todo lo que sabe le llega por el
 * evento `secretario:estado` que emite chat-secretario.js —el mismo sondeo de
 * siempre, sin otro—, y lo del raíl al cargar (`data-espera` en su raíz):
 *
 *   { voz: 'escuchando'|'transcribiendo'|'hablando'|'pausa'|'' }
 *   { nivel: 0..1 }                 cuánto se oye (tu voz, o cada palabra suya)
 *   { turnos: [...], espera: {...} } lo que trae /api/secretario/turnos
 *   { enviado: <ms> }               acabas de mandarle algo
 *   { red: 'ok'|'caida' }
 *
 * De ahí sale UNA vista (`derivar`, pura): estado, gesto, rótulo y
 * acompañantes. El JS sólo pone atributos (`data-estado`, `data-gesto`,
 * `--nivel`) y el texto del rótulo; lo demás es CSS (avatar-secretario.css).
 * Sólo conoce la lista cerrada `GESTOS`, nunca nombres de herramientas: el
 * gesto y el rótulo los resuelve el servidor.
 *
 * Cada estado se ve al menos `MIN_MS`: si llegan varios seguidos, gana el
 * último (una herramienta de 50 ms no hace parpadear nada).
 */
(() => {
  // = `hub.secretario.personaje.GESTOS` (lo comprueba un test).
  const GESTOS = ['leer', 'buscar', 'mensajes', 'agenda', 'compromisos', 'mirar', 'maquina', 'carpeta',
                  'anotar', 'idea', 'mostrar', 'avisar', 'pc', 'grabar', 'tele', 'hacer', 'delegar',
                  'escalar', 'hora'];
  const MIN_MS = 600;
  const HECHO_MS = 1600;
  const ERROR_MS = 2600;
  const COLA_MS = 4000;      // un mensaje que nadie ha cogido en 4 s está en cola de verdad
  const DORMIR_MS = 180000;
  // Lo que espera y lo que delegó se enseña mientras sea de los últimos tres
  // minutos: el panel plegado no pregunta, y un dato viejo no se pinta como
  // si fuera de ahora. Con el panel abierto se renueva cada 6 s.
  const ESPERA_VIGENTE_MS = 180000;
  const MAX_ACOMP = 3;
  const ROTULOS = {
    quieto: '', dormido: 'Descansando', escuchando: 'Te escucho', transcribiendo: 'Transcribiendo…',
    pensando: 'Pensando…', 'pensando-fondo': 'Pensándolo a fondo', escribiendo: 'Escribiendo la respuesta',
    hablando: 'Hablando', esperando: 'Espera tu sí', 'esperando-otro': 'Esperando…', 'en-cola': 'En cola',
    hecho: 'Listo', error: 'Algo falló', pausa: 'En pausa', 'sin-hub': 'El hub no contesta',
  };
  // Lo que lleva en la mano fuera de una herramienta.
  const ACCESORIO = { transcribiendo: 'ondas', 'en-cola': 'arena', escribiendo: 'anotar' };
  // Sólo esto se anuncia a un lector de pantalla: cada herramienta sería ruido.
  const IMPORTANTES = { esperando: true, error: true, hecho: true };

  const plural = (n, uno, varios) => `${n} ${n === 1 ? uno : varios}`;

  /* Quién trabaja para él ahora: lo que delegó y sigue vivo (`api.secretario_espera`)
   * y el modelo mayor si le pasó el turno. Nunca compañeros inventados. */
  // El estado de una tarea del orquestador, dicho como lo que hace su figura:
  // sólo trabaja la que trabaja; la que espera una respuesta, levanta la mano.
  const ESTADO_TAREA = { activa: 'trabajando', 'esperando-sesion': 'trabajando', 'en-cola': 'en-cola',
                         'esperando-dueno': 'esperando', 'esperando-secretario': 'esperando' };

  function acompanantes(espera, experto) {
    const lista = [];
    if (experto) lista.push({ rol: 'experto', que: 'El modelo mayor, con este turno', estado: 'trabajando' });
    for (const e of (espera && espera.encargos) || []) {
      const estado = ESTADO_TAREA[e.estado] || 'en-cola';
      lista.push({ rol: 'orquestador', estado,
                   que: `Orquestador${estado === 'esperando' ? ' (espera una respuesta)' : ''}: ${e.pedido || ''}` });
      for (const s of e.sesiones || []) {
        lista.push({ rol: 'obrero', que: `Sesión ${s.nombre || s.proyecto || ''}`, estado: 'trabajando' });
        for (const a of s.subagentes || []) {
          lista.push({ rol: a.rol || 'otro', inicial: a.inicial || '', estado: 'trabajando',
                       que: `${a.tipo || a.rol}${a.que ? `: ${a.que}` : ''}` });
        }
      }
    }
    // Sólo uno se lee a la vez; los demás esperan su turno en la cola.
    const resumenes = (espera && espera.resumenes) || 0;
    const leyendo = (espera && espera.resumiendo) || 0;
    for (let i = 0; i < resumenes; i += 1) {
      lista.push(i < leyendo ? { rol: 'resumidor', que: 'Leyendo una sesión para resumirla', estado: 'trabajando' }
                             : { rol: 'resumidor', que: 'Un resumen en cola', estado: 'en-cola' });
    }
    // Lo que investiga en la web (385): igual, sólo trabaja la que se hace.
    const investigaciones = (espera && espera.investigaciones) || 0;
    const investigando = (espera && espera.investigando) || 0;
    for (let i = 0; i < investigaciones; i += 1) {
      lista.push(i < investigando ? { rol: 'investigador', que: 'Investigando en la web', estado: 'trabajando' }
                                  : { rol: 'investigador', que: 'Una investigación en cola', estado: 'en-cola' });
    }
    return lista;
  }

  /* La vista que toca, de mayor a menor prioridad. Pura: el modelo y la hora. */
  function derivar(m, ahora) {
    // Lo que espera, mientras sea reciente: con el panel plegado no se
    // pregunta, y lo de hace rato ya no se puede defender (regla 13).
    const espera = (m.espera && ahora - (m.esperaEn || 0) < ESPERA_VIGENTE_MS) ? m.espera : {};
    const abierto = m.abierto;
    const act = (abierto && abierto.actividad) || null;
    const experto = !!(act && act.experto);
    const acomp = acompanantes(espera, experto && !!abierto);
    const vista = (estado, extra) => ({ estado, gesto: '', rotulo: ROTULOS[estado], acompanantes: acomp, ...extra });
    if (m.red === 'caida') return vista('sin-hub');
    if (m.voz === 'escuchando') return vista('escuchando');
    if (m.voz === 'transcribiendo') return vista('transcribiendo', { gesto: ACCESORIO.transcribiendo });
    if (m.voz === 'hablando') return vista('hablando');
    if (m.flash && ahora < m.flash.hasta) return vista(m.flash.tipo);
    if (abierto) {
      if (act && act.estado === 'trabajando') {
        const gesto = GESTOS.includes(act.gesto) ? act.gesto : 'hacer';
        return vista('trabajando', { gesto, rotulo: String(act.rotulo || '') || 'Trabajando' });
      }
      if (act && act.estado === 'escribiendo') return vista('escribiendo', { gesto: ACCESORIO.escribiendo });
      return vista(experto ? 'pensando-fondo' : 'pensando');
    }
    if (m.enCola) {
      return ahora - m.enCola < COLA_MS ? vista('pensando') : vista('en-cola', { gesto: ACCESORIO['en-cola'] });
    }
    const n = espera.solicitudes || 0;
    if (n > 0) return vista('esperando', { rotulo: n > 1 ? `Esperan tu sí (${n})` : ROTULOS.esperando });
    const encargos = espera.encargos || [];
    if (encargos.some(e => e.estado === 'esperando-dueno')) {
      return vista('esperando', { rotulo: 'El orquestador espera tu respuesta' });
    }
    if (encargos.length || espera.resumenes || espera.investigaciones) {
      // Los subagentes, de las sesiones de sus encargos: por rol no, que
      // «investigador» es también lo que investiga aparte (385).
      const subagentes = encargos.reduce((n, e) => n + (e.sesiones || []).reduce(
        (m, s) => m + (s.subagentes || []).length, 0), 0);
      const aparte = espera.resumiendo ? 'Resumiendo una sesión aparte'
        : espera.investigando ? 'Investigando en la web'
          : espera.resumenes ? 'Un resumen en cola' : 'Una investigación en cola';
      const rotulo = encargos.length
        ? (encargos.some(e => ESTADO_TAREA[e.estado] === 'trabajando')
          ? `Esperando al orquestador${subagentes ? ` · ${plural(subagentes, 'subagente', 'subagentes')}` : ''}`
          : `Encargado al orquestador (${encargos.some(e => e.estado === 'en-cola') ? 'en cola' : 'le pregunta algo'})`)
        : aparte;
      return vista('esperando-otro', { rotulo });
    }
    if (m.voz === 'pausa') return vista('pausa');
    if (ahora - (m.ultimo || ahora) >= DORMIR_MS) return vista('dormido');
    return vista('quieto');
  }

  const escapar = (s) => String(s ?? '').replace(/[&<>"']/g, c =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const clave = (v) => v && [v.estado, v.gesto, v.rotulo,
                             (v.acompanantes || []).map(a => `${a.rol}/${a.estado}/${a.que}`).join('|')].join('·');

  function leerEspera(raiz) {
    try { return JSON.parse((raiz.dataset && raiz.dataset.espera) || 'null'); } catch (e) { return null; }
  }

  /* Una escena: una raíz con su personaje. `op` deja cambiar el reloj en las pruebas. */
  function crear(raiz, op) {
    op = op || {};
    const ahora = op.ahora || (() => Date.now());
    const programar = op.programar || ((f, ms) => setTimeout(f, ms));
    const cancelar = op.cancelar || ((t) => clearTimeout(t));
    const quieto = op.reducido !== undefined ? op.reducido
      : !!(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);
    if (quieto && raiz.classList) raiz.classList.add('sin-movimiento');
    const m = { voz: '', red: 'ok', abierto: null, enCola: 0, flash: null, espera: leerEspera(raiz),
                esperaEn: ahora(), vistos: {}, ultimo: ahora() };
    const q = (sel) => (raiz.querySelector ? raiz.querySelector(sel) : null);
    const accesorio = q('.pj-accesorio use');
    const rotulo = q('[data-rotulo]');
    // Fuera de la raíz si la raíz es un botón: una región viva dentro de un
    // control se lee como parte de su nombre.
    const padre = raiz.parentNode && raiz.parentNode.querySelector ? raiz.parentNode : null;
    const anuncio = q('[data-anuncio]') || (padre && padre.querySelector('[data-anuncio]'));
    const caja = q('[data-acompanantes]');
    const plantilla = document.getElementById('pj-plantilla-acomp');
    let mostrada = null, desde = 0, pendiente = null, espera = null, revision = null, pintados = null;

    function pintarAcompanantes(lista) {
      // Rehacerlos reinicia su animación: sólo si cambió quién está.
      const k = lista.map(a => `${a.rol}/${a.estado}/${a.que}`).join('|');
      if (!caja || k === pintados) return;
      pintados = k;
      const molde = (plantilla && plantilla.innerHTML) || '';
      const vistos = lista.slice(0, MAX_ACOMP);
      const resto = lista.length - vistos.length;
      caja.innerHTML = vistos.map(a => {
        const rol = /^[a-z-]+$/.test(a.rol || '') ? a.rol : 'otro';
        return `<span class="pj-acomp" data-rol="${rol}" data-estado="${escapar(a.estado)}" title="${escapar(a.que)}">`
               + molde.replace(/__ROL__/g, rol).replace(/__INICIAL__/g, escapar(a.inicial || '')) + '</span>';
      }).join('') + (resto > 0 ? `<span class="pj-mas" title="${escapar(lista.slice(MAX_ACOMP).map(a => a.que).join('\n'))}">+${resto}</span>` : '');
    }

    function pintar(v) {
      raiz.dataset.estado = v.estado;
      raiz.dataset.gesto = v.gesto || '';
      if (accesorio && v.gesto) accesorio.setAttribute('href', `#acc-${v.gesto}`);
      if (rotulo) rotulo.textContent = v.rotulo || '';
      if (anuncio && IMPORTANTES[v.estado]) anuncio.textContent = v.rotulo || '';
      pintarAcompanantes(v.acompanantes || []);
    }

    function aplicar() {
      espera = null;
      const v = pendiente;
      pendiente = null;
      if (!v || clave(v) === clave(mostrada)) return;
      mostrada = v;
      desde = ahora();
      pintar(v);
    }

    /* Cada estado se ve al menos MIN_MS; lo que llegue antes espera, y gana el último. */
    function poner(v) {
      pendiente = v;
      if (espera !== null) return;
      const falta = mostrada ? MIN_MS - (ahora() - desde) : 0;
      if (falta > 0) espera = programar(aplicar, falta);
      else aplicar();
    }

    /* Lo que depende de la hora (el ✓ que se va, la cola, dormirse) se revisa
     * en su momento, con un solo temporizador. */
    function recalcular() {
      const t = ahora();
      let v = derivar(m, t);
      // Lo quieto cuenta desde que dejó de hacer algo, no desde lo último que se le dijo.
      const activo = (e) => e && e !== 'quieto' && e !== 'dormido';
      if (activo(v.estado)) m.ultimo = t;
      else if (activo(m.previo)) { m.ultimo = t; v = derivar(m, t); }
      m.previo = v.estado;
      poner(v);
      if (revision !== null) cancelar(revision);
      revision = null;
      const plazos = [];
      if (m.flash && m.flash.hasta > t) plazos.push(m.flash.hasta - t);
      if (m.enCola && !m.abierto && t - m.enCola < COLA_MS) plazos.push(COLA_MS - (t - m.enCola));
      if (m.espera && t - m.esperaEn < ESPERA_VIGENTE_MS) plazos.push(ESPERA_VIGENTE_MS - (t - m.esperaEn));
      if (v.estado === 'quieto') plazos.push(DORMIR_MS - (t - m.ultimo));
      if (plazos.length) revision = programar(() => { revision = null; recalcular(); }, Math.max(50, Math.min(...plazos)));
    }

    function nivel(x) {
      if (quieto || !raiz.style) return;
      raiz.style.setProperty('--nivel', String(Math.round(Math.max(0, Math.min(1, Number(x) || 0)) * 100) / 100));
    }

    function recibir(d) {
      if (!d || typeof d !== 'object') return;
      if ('nivel' in d) nivel(d.nivel);
      if ('red' in d) m.red = d.red === 'caida' ? 'caida' : 'ok';
      if ('voz' in d) {
        m.voz = ['escuchando', 'transcribiendo', 'hablando', 'pausa'].includes(d.voz) ? d.voz : '';
        if (m.voz !== 'escuchando' && m.voz !== 'hablando') nivel(0);
      }
      if ('espera' in d) { m.espera = d.espera || null; m.esperaEn = ahora(); }
      if (d.enviado) m.enCola = Number(d.enviado) || ahora();
      if (Array.isArray(d.turnos)) {
        let abierto = null, cola = 0;
        for (const t of d.turnos) {
          if (t.rol === 'secretario') {
            if (t.estado === 'escribiendo') abierto = t;
            else if ((t.estado === 'listo' || t.estado === 'error') && m.vistos[t.id] === 'escribiendo') {
              // Sólo lo que se vio a medias: lo ya contestado al cargar no salta.
              m.flash = { tipo: t.estado === 'listo' ? 'hecho' : 'error',
                          hasta: ahora() + (t.estado === 'listo' ? HECHO_MS : ERROR_MS) };
            }
            m.vistos[t.id] = t.estado;
          } else if (t.estado === 'pendiente') {
            cola = Date.parse(t.creado || '') || m.enCola || ahora();
          }
        }
        m.abierto = abierto;
        // Sin turnos nuevos se respeta el «acabas de mandarlo» un rato, por si
        // el sondeo llegó antes que el mensaje; pasado, ya no está en cola.
        const reciente = m.enCola && ahora() - m.enCola < 10000;
        m.enCola = abierto ? 0 : (cola || (!d.turnos.length && reciente ? m.enCola : 0));
      }
      if (Object.keys(d).some(k => k !== 'nivel')) recalcular();
    }

    recalcular();
    // Lo pintado al cargar es provisional (aún no hay sondeo): no retiene al
    // primer estado de verdad sus 600 ms.
    desde = ahora() - MIN_MS;
    return { recibir, poner, recalcular, modelo: m, vista: () => mostrada };
  }

  window.HubPersonaje = { GESTOS, MIN_MS, derivar, acompanantes, crear };

  const escenas = [];
  document.querySelectorAll('[data-personaje]:not([data-fijo])').forEach(r => escenas.push(crear(r)));
  document.addEventListener('secretario:estado', (e) => escenas.forEach(s => s.recibir((e && e.detail) || {})));
  // Con la pestaña escondida, quieto: no se gasta nada en moverlo.
  document.addEventListener('visibilitychange', () => {
    document.querySelectorAll('[data-personaje]').forEach(r => {
      if (document.hidden) r.dataset.oculta = '1'; else delete r.dataset.oculta;
    });
  });

  /* La escena de la galería (Ajustes → Personaje): una conversación de
   * ejemplo con los mismos eventos que manda el chat de verdad, para verlo
   * sin tener que provocarlo. Sólo existe ahí, y dice que es un ejemplo. */
  const boton = document.getElementById('pj-reproducir');
  const escena = document.getElementById('pj-escena');
  if (boton && escena && boton.addEventListener) {
    const demo = crear(escena);
    let relojes = [];
    const turno = (estado, actividad) => ({ turnos: [{ id: 'ejemplo', rol: 'secretario', estado, actividad }] });
    const trabajo = (gesto, rotulo) => turno('escribiendo', { estado: 'trabajando', gesto, rotulo });
    const subagentes = [
      { rol: 'arquitecto', tipo: 'arquitecto', que: 'Revisa el diseño' },
      { rol: 'revisor', tipo: 'revisor', que: 'Revisa el cambio' },
      { rol: 'disenador', tipo: 'diseñador', que: 'Pule la pantalla' },
      { rol: 'explorador', tipo: 'Explore', que: 'Busca en el código' },
    ];
    const encargo = { id: 'ejemplo', estado: 'activa', pedido: 'Arreglar la pantalla de respaldo',
                      sesiones: [{ nombre: 'Tablero', proyecto: 'hub', subagentes }] };
    const guion = [
      [0, { voz: 'escuchando', nivel: 0.3 }], [400, { nivel: 0.8 }], [800, { nivel: 0.4 }], [1200, { nivel: 0.9 }],
      [1700, { voz: 'transcribiendo' }],
      [2600, { voz: '', enviado: 1 }],
      [3000, turno('escribiendo', { estado: 'pensando' })],
      [4000, trabajo('buscar', 'Buscando «despliegue» en lo que ha leído')],
      [5300, trabajo('agenda', 'Mirando tu agenda')],
      [6500, trabajo('leer', 'Leyendo notas.md')],
      [7800, { ...trabajo('delegar', 'Encargar al orquestador'), espera: { solicitudes: 0, resumenes: 0, encargos: [encargo] } }],
      [9200, turno('escribiendo', { estado: 'escribiendo' })],
      [10400, turno('listo', null)],
      [10500, { turnos: [] }],
      [10700, { voz: 'hablando', nivel: 0.7 }], [11000, { nivel: 0.2 }], [11300, { nivel: 0.9 }], [11600, { nivel: 0.3 }],
      [12600, { voz: '' }],
      [12700, { espera: { solicitudes: 1, resumenes: 0, encargos: [encargo] } }],
      [15200, { espera: { solicitudes: 0, resumenes: 1, encargos: [encargo] } }],
      [18500, { espera: { solicitudes: 0, resumenes: 0, encargos: [] } }],
    ];
    boton.addEventListener('click', () => {
      relojes.forEach(r => clearTimeout(r));
      demo.modelo.vistos = {};
      relojes = guion.map(([ms, d]) => setTimeout(() => demo.recibir(d.enviado ? { ...d, enviado: Date.now() } : d), ms));
    });
  }
})();
