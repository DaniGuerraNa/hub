/* Los talleres (C-0220, decisión 391): cada sesión con agente es un taller.
 *
 * La rana herrera es la sesión, en el yunque de la herrería: martilla si
 * trabaja, duerme si está quieta y pide permiso si espera tu sí. Sus
 * subagentes vivos entran por la puerta y van a la estación de su oficio
 * (varios por estación, hasta sus huecos; luego «+N»). Al terminar le llevan
 * el resultado y se van.
 *
 * No sabe nada por su cuenta: los datos llegan en la región `talleres` de la
 * página (`api.talleres`), que se pide de nuevo cada 10 s por
 * `HubSinRecarga.refrescar` mientras la pestaña se ve; la tabla del dibujo
 * (`talleres.escena`), aparte. Cada vez se compara con lo anterior y sólo se
 * mueve lo que cambió. Con la pestaña oculta no programa nada; con «reducir
 * movimiento», se pone en su sitio sin andar ni animar.
 *
 * 🔴 Todo lo que viene de los datos se escribe con `textContent`, nunca como
 * HTML: el título de un panel lo escribe cualquier programa, y esta página
 * comparte origen con la terminal.
 *
 * Lo puro (`comparar`, `repartir`, `figuraDe`, `edad`) va aparte para
 * probarlo en node; `crear` recibe relojes y medidas por `op`. */
(function () {
  'use strict';
  const LATIDO_MS = 10000;
  // Con la muestra más vieja que esto, no se pinta nada como si fuera de ahora.
  const VIEJA_S = 120;
  // El ritmo de los cuadros de trabajo, y cuál lleva efecto (y dónde, en la capa).
  const SECUENCIAS = {
    'rana-herrera': { pasos: [['f0', 260], ['f1', 430], ['f2', 320, 'chispa'], ['f0', 160]], fx: { u: 0.8, v: 0.69 } },
    'rana-alquimista': { pasos: [['f1', 210], ['f2', 210], ['f1', 210], ['f2', 210], ['f3', 950, 'burbuja'], ['f0', 320]],
                         fx: { u: 0.6, v: 0.2 } },
    'rana-bardo': { pasos: [['f1', 520], ['f2', 470], ['f0', 380]], fx: null },
  };
  const TEXTO_ESTADO = { trabajando: 'trabajando', quieta: 'quieta', espera: 'espera tu sí' };

  // ── Lo puro ──────────────────────────────────────────────────────────────

  /* Qué cambió entre dos sondeos, por `clave` de taller (panel:conversación)
   * e `id` de subagente. Si un lado no trae la conversación —un ciclo en que
   * no se pudo leer, o recién abierta—, es el mismo taller si es el mismo
   * panel: se renombra en vez de borrarlo y crearlo otra vez. */
  function comparar(antes, ahora) {
    const panel = (c) => String(c).split(':')[0];
    const sinConversacion = (c) => !String(c).split(':')[1];
    const A = new Map((antes || []).map((t) => [t.clave, t]));
    const usados = new Set();
    const r = { nuevos: [], idos: [], estados: [], llegan: [], salen: [], renombrar: [] };
    for (const t of ahora || []) {
      const k = t.clave;
      let v = A.get(k);
      if (!v) {
        v = [...A.values()].find((x) => !usados.has(x.clave) && panel(x.clave) === panel(k)
                                         && (sinConversacion(x.clave) || sinConversacion(k)));
        if (v) r.renombrar.push({ de: v.clave, a: k });
      }
      if (!v) { r.nuevos.push(t); continue; }
      usados.add(v.clave);
      if (v.estado !== t.estado) r.estados.push({ clave: k, estado: t.estado });
      const antes_ = new Set((v.subagentes || []).map((s) => s.id));
      const ahora_ = new Set((t.subagentes || []).map((s) => s.id));
      for (const s of t.subagentes || []) if (!antes_.has(s.id)) r.llegan.push({ clave: k, sub: s });
      for (const s of v.subagentes || []) if (!ahora_.has(s.id)) r.salen.push({ clave: k, id: s.id });
    }
    for (const k of A.keys()) if (!usados.has(k)) r.idos.push(k);
    return r;
  }

  /* El primer hueco libre de una estación con `n` huecos; -1 si no cabe. */
  function repartir(usados, n) {
    for (let i = 0; i < n; i++) if (!usados.includes(i)) return i;
    return -1;
  }

  /* La rana de un subagente; «otro» (o un rol sin rana) va neutro, con su inicial. */
  function figuraDe(sub, escena) {
    const id = (escena.figuras || {})[sub.rol];
    return id ? { id, img: `${escena.url}ranas/${id}.webp` } : { id: null, inicial: sub.inicial || '?' };
  }

  /* Segundos desde `tomado` (ISO) hasta `ahora` (ms); Infinity sin muestra. */
  function edad(tomado, ahora) {
    const t = Date.parse(tomado || '');
    return Number.isFinite(t) ? Math.max(0, (ahora - t) / 1000) : Infinity;
  }

  // ── La escena ────────────────────────────────────────────────────────────

  function crear(raiz, op) {
    const E = op.escena;
    const F = E.fondo;
    const rejilla = raiz.querySelector('[data-escenas]');
    const resumen = raiz.querySelector('[data-resumen]');
    const aviso = raiz.querySelector('[data-vieja]');
    const talleres = new Map();
    const relojes = new Set();
    let previos = null;

    const quieto = () => op.reducido();
    /* Los bucles (cuadros, zetas, globos): con la pestaña oculta no se
     * programan, y `pausar` los cancela. */
    function programar(fn, ms) {
      if (op.oculta()) return null;
      const id = op.programar(() => { relojes.delete(id); fn(); }, ms);
      relojes.add(id);
      return id;
    }
    /* Lo que termina (andar, entrar, salir) no se cancela nunca: si se
     * cortara a medias, la rana se quedaría a mitad de camino para siempre.
     * Con la pestaña oculta no se espera: se llega al momento. */
    const espera = (ms) => (op.oculta() ? Promise.resolve() : new Promise((r) => op.programar(r, ms)));
    const escala = () => F.escala || 1;
    const el = (etiqueta, clase, texto) => {
      const n = document.createElement(etiqueta);
      if (clase) n.className = clase;
      if (texto != null) n.textContent = texto;
      return n;
    };

    // ── personajes ──
    function personaje(T, figura) {
      const a = { el: el('div', 'tll-pj oculto quieto'), id: figura.id, x: F.puerta.x, y: F.puerta.y };
      const giro = el('div', 'giro');
      const cuerpo = el('div', 'cuerpo');
      if (figura.img) {
        const im = el('img', 'andar');
        im.src = figura.img; im.alt = '';
        cuerpo.appendChild(im);
        // Su alto lo da la imagen: medir antes de que cargue descuadra.
        a.lista = im.decode ? im.decode().catch(() => {}) : Promise.resolve();
        const C = (E.cuadros || {})[figura.id];
        if (C) {
          const capa = el('div', 'capa');
          capa.style.left = C.izquierda + '%';
          capa.style.width = C.ancho + '%';
          capa.style.aspectRatio = `${C.ancho} / ${C.alto}`;
          capa.style.transform = `translateY(${C.bajar}%)`;
          for (const c of C.cuadros) {
            const ci = el('img');
            ci.src = `${E.url}cuadros/${figura.id}/${c}.webp`; ci.alt = ''; ci.dataset.c = c;
            capa.appendChild(ci);
          }
          cuerpo.appendChild(capa);
        }
      } else {
        cuerpo.appendChild(el('div', 'neutro', figura.inicial));
      }
      giro.appendChild(cuerpo);
      a.el.append(giro, el('div', 'tll-globo'));
      T.esc.appendChild(a.el);
      return a;
    }
    function colocar(a, x, y, ya) {
      if (ya) a.el.style.transitionDuration = '0ms';
      a.x = x; a.y = y;
      a.el.style.left = x + '%';
      a.el.style.top = y + '%';
      a.el.style.setProperty('--s', String(a.sFijo || escala()));
      a.el.style.setProperty('--z', String(a.z || Math.round(y * 2)));
    }
    function mirar(a, dir) { a.dir = dir; a.el.style.setProperty('--dir', String(dir)); }
    // Un taller quitado no sigue moviendo a nadie: lo que estaba en camino
    // se para en el siguiente paso, sin programar nada más.
    const fuera = (a) => !!(a.taller && a.taller.quitado);
    async function andar(a, x, y) {
      parar(a);
      if (fuera(a)) return;
      const dist = Math.hypot(x - a.x, (y - a.y) * 1.5);
      if (quieto() || dist < 0.5 || op.oculta()) { colocar(a, x, y, true); return; }
      const ms = Math.max(350, dist * 70);
      mirar(a, x < a.x ? -1 : 1);
      a.el.classList.remove('quieto'); a.el.classList.add('andando');
      a.el.style.transitionDuration = ms + 'ms';
      colocar(a, x, y);
      await espera(ms);
      a.el.classList.remove('andando'); a.el.classList.add('quieto');
    }
    function decir(a, texto, ms, clase) {
      if (fuera(a)) return;
      const g = a.el.querySelector('.tll-globo');
      g.textContent = texto;
      g.className = 'tll-globo visible' + (clase ? ' ' + clase : '');
      if (ms) programar(() => g.classList.remove('visible'), ms);
    }
    function callar(a) { a.el.querySelector('.tll-globo').className = 'tll-globo'; }

    // ── animación de trabajo ──
    function animar(a) {
      const S = SECUENCIAS[a.id];
      if (!S || !(E.cuadros || {})[a.id] || quieto()) return false;
      parar(a);
      a.trabaja = true;
      a.el.classList.add('animado', 'capa-on');
      const imgs = [...a.el.querySelectorAll('.capa img')];
      // Cada una a su ritmo: tres alquimistas no van al compás.
      let i = Math.floor(Math.random() * S.pasos.length);
      const paso = () => {
        const [c, ms, fx] = S.pasos[i++ % S.pasos.length];
        for (const im of imgs) im.classList.toggle('ver', im.dataset.c === c);
        if (fx && S.fx) efecto(a, S.fx, fx);
        a.reloj = programar(paso, ms * (0.92 + Math.random() * 0.18));
      };
      paso();
      return true;
    }
    function parar(a) {
      if (a.reloj) { op.cancelar(a.reloj); relojes.delete(a.reloj); a.reloj = null; }
      a.trabaja = false;
      a.el.classList.remove('animado', 'capa-on');
    }
    /* Un cuadro quieto: la sesión, cuando no trabaja, se queda así junto al
     * yunque (con su imagen de andar quedaría descolocada). */
    function posar(a, c) {
      const imgs = a.el.querySelectorAll('.capa img');
      if (!imgs.length) return;
      for (const im of imgs) im.classList.toggle('ver', im.dataset.c === c);
      a.el.classList.add('capa-on');
    }
    function efecto(a, fx, tipo) {
      const capa = a.el.querySelector('.capa');
      const T = a.taller;
      if (!capa || !capa.getBoundingClientRect || quieto()) return;
      const r = capa.getBoundingClientRect(), e = T.esc.getBoundingClientRect();
      if (!r.width || !e.width) return;
      const u = (a.dir || 1) < 0 ? 1 - fx.u : fx.u;
      const x = (r.left + r.width * u - e.left) / e.width * 100;
      const y = (r.top + r.height * fx.v - e.top) / e.height * 100;
      if (tipo === 'chispa') suelta(T, el('div', 'tll-destello'), x, y);
      const n = tipo === 'chispa' ? 12 : 4;
      for (let k = 0; k < n; k++) {
        const c = el('div', 'tll-chispa ' + tipo);
        const ang = (-90 + (tipo === 'burbuja' ? 40 : 140) * (Math.random() - 0.5)) * Math.PI / 180;
        const radio = tipo === 'burbuja' ? 50 + Math.random() * 50 : 25 + Math.random() * 40;
        c.style.setProperty('--dx', Math.cos(ang) * radio + 'px');
        c.style.setProperty('--dy', Math.sin(ang) * radio + 'px');
        if (tipo === 'chispa') c.style.setProperty('--caida', 15 + Math.random() * 20 + 'px');
        c.style.setProperty('--t', tipo === 'burbuja' ? '1.6s' : '.9s');
        suelta(T, c, x, y);
      }
    }
    function suelta(T, n, x, y) {
      n.style.left = x + '%'; n.style.top = y + '%';
      T.esc.appendChild(n);
      n.addEventListener('animationend', () => n.remove());
    }
    function zetas(T) {
      const m = T.sesion;
      if (quieto() || T.quitado || T.estado !== 'quieta') return;
      const z = el('div', 'tll-zeta', 'z');
      suelta(T, z, m.x + 3, m.y - 20);
      T.zeta = programar(() => zetas(T), 1300);
    }

    /* La herrera junto al yunque DEL FONDO (sus cuadros no traen el suyo,
     * decisión 391): la escala que hace que el yunque que tenía mida lo que
     * mide el del fondo, y el sitio que hace que caigan uno encima del otro.
     * Se mide en la página: todo va en %, así que vale aunque el taller crezca. */
    function alYunque(T) {
      const a = T.sesion, Y = F.maestro.yunque, C = (E.cuadros || {})[a.id];
      const capa = a.el.querySelector('.capa');
      if (!Y || !C || !C.objeto || !capa || !capa.getBoundingClientRect) return;
      const e = T.esc.getBoundingClientRect();
      const r0 = capa.getBoundingClientRect();
      if (!e.height || !r0.height) return;
      const alto = (C.objeto.v_base - C.objeto.v_arriba) * r0.height / e.height * 100;
      a.sFijo = (a.sFijo || escala()) * (Y.base - Y.arriba) / alto;
      colocar(a, a.x, a.y, true);
      const r = capa.getBoundingClientRect();
      const ux = (r.left + r.width * C.objeto.u - e.left) / e.width * 100;
      const uy = (r.top + r.height * C.objeto.v_base - e.top) / e.height * 100;
      a.z = Math.round(Y.base * 2) + 1;
      colocar(a, a.x + (Y.x - ux), a.y + (Y.base - uy), true);
    }

    // ── un taller ──
    function nuevoTaller(t) {
      const T = { clave: t.clave, datos: t, ranas: [], cola: Promise.resolve() };
      T.el = el('article', 'tll-taller');
      const cab = el('div', 'tll-cab');
      cab.setAttribute('role', 'button');
      cab.tabIndex = 0;
      cab.setAttribute('aria-label', 'Ver este taller en grande');
      const h2 = el('h2');
      T.titulo = el('span'); T.agente = el('small');
      h2.append(T.titulo, T.agente);
      T.chip = el('span', 'tll-chip');
      T.cuantas = el('span', 'tll-cuantas');
      cab.append(h2, T.chip, T.cuantas);
      const grande = () => T.el.classList.toggle('grande');
      cab.addEventListener('click', grande);
      cab.addEventListener('keydown', (ev) => {
        if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); grande(); }
      });
      T.esc = el('div', 'tll-esc');
      T.esc.style.backgroundImage = `url("${F.img}")`;
      T.esc.style.backgroundPosition = F.posicion || 'top center';
      T.luz = el('div', 'tll-luz');
      for (const [k, v] of Object.entries(F.luz)) T.luz.style[k] = v + '%';
      T.esc.appendChild(T.luz);
      T.lista = el('div', 'tll-lista');
      T.el.append(cab, T.esc, T.lista);
      rejilla.appendChild(T.el);

      T.sesion = personaje(T, { id: E.sesion, img: `${E.url}ranas/${E.sesion}.webp` });
      T.sesion.taller = T;
      T.sesion.el.classList.add('sesion');
      colocar(T.sesion, F.maestro.x, F.maestro.y, true);
      T.sesion.el.classList.remove('oculto');
      mirar(T.sesion, 1);
      // Medir pide la imagen cargada y la caja ya pintada.
      Promise.resolve(T.sesion.lista).then(() => (window.requestAnimationFrame || ((f) => f()))(() => alYunque(T)));
      talleres.set(t.clave, T);
      cabecera(T, t);
      ponerEstado(T, t.estado);
      for (const s of t.subagentes || []) llega(T, s, true);
      pintarLista(T);
      return T;
    }
    function cabecera(T, t) {
      T.datos = t;
      T.titulo.textContent = t.proyecto ? `${t.proyecto} · ${t.nombre}` : t.nombre;
      T.agente.textContent = t.agente;
    }
    function ponerEstado(T, e) {
      T.estado = e;
      T.el.classList.toggle('quieta', e === 'quieta');
      T.el.classList.toggle('espera', e === 'espera');
      T.chip.className = 'tll-chip ' + e;
      T.chip.textContent = TEXTO_ESTADO[e] || T.datos.agente;
      const m = T.sesion;
      parar(m);
      if (T.zeta) { op.cancelar(T.zeta); relojes.delete(T.zeta); T.zeta = null; }
      callar(m);
      m.el.classList.add('quieto');
      if (!(e === 'trabajando' && animar(m))) posar(m, 'f0');
      if (e === 'espera') decir(m, '¿Me das permiso?', 0, 'pide');
      else if (e === 'quieta') zetas(T);
    }

    // ── sus subagentes ──
    function hueco(T, estacion) {
      const n = (E.estaciones[estacion].huecos || [[0, 0]]).length;
      return repartir(T.ranas.filter((r) => r.estacion === estacion).map((r) => r.hueco), n);
    }
    function marcarMas(T) {
      for (const m of T.esc.querySelectorAll('.tll-mas')) m.remove();
      for (const [nombre, S] of Object.entries(E.estaciones)) {
        const fuera = T.ranas.filter((r) => r.estacion === nombre && r.hueco < 0).length;
        if (fuera) suelta(T, el('div', 'tll-mas', '+' + fuera), S.x + 8, S.y - 16);
      }
    }
    async function llega(T, sub, ya) {
      const S = E.estaciones[sub.estacion] ? sub.estacion : 'entrada';
      const r = { id: sub.id, sub, estacion: S, hueco: hueco(T, S) };
      T.ranas.push(r);
      if (r.hueco < 0) { marcarMas(T); return; } // no cabe: cuenta en el «+N»
      const est = E.estaciones[S];
      const a = r.actor = personaje(T, figuraDe(sub, E));
      a.taller = T;
      const [dx, dy] = est.huecos[r.hueco];
      const x = est.x + dx, y = est.y + dy;
      if (ya || quieto()) {
        colocar(a, x, y, true);
        a.el.classList.remove('oculto');
      } else {
        await aparecer(T, a);
        decir(a, '¡Voy!', 900);
        for (const [px, py] of est.via || []) await andar(a, px, py);
        await andar(a, x, y);
      }
      if (r.saliendo || !a.el.isConnected) return;
      mirar(a, est.mira);
      a.el.classList.remove('quieto');
      const oficio = (E.oficios || {})[sub.rol];
      if (!animar(a) && oficio) a.el.dataset.oficio = oficio;
    }
    async function sale(T, id) {
      const r = T.ranas.find((x) => x.id === id);
      if (!r || r.saliendo) return;
      r.saliendo = true;
      T.ranas = T.ranas.filter((x) => x !== r);
      // Si alguien esperaba sitio en esa estación, entra en el hueco que queda.
      const espera_ = T.ranas.find((x) => x.estacion === r.estacion && x.hueco < 0);
      if (espera_) { T.ranas = T.ranas.filter((x) => x !== espera_); llega(T, espera_.sub, false); }
      marcarMas(T);
      pintarLista(T);
      const a = r.actor;
      if (!a) return;
      parar(a);
      delete a.el.dataset.oficio;
      a.el.classList.add('quieto');
      if (quieto()) { a.el.remove(); return; }
      const est = E.estaciones[r.estacion];
      for (const [px, py] of [...(est.via || [])].reverse()) await andar(a, px, py);
      // Los resultados, de uno en uno: la sesión recibe un pergamino cada vez.
      T.cola = T.cola.then(async () => {
        await andar(a, F.entrega.x, F.entrega.y);
        mirar(a, 1);
        decir(a, '¡Listo!', 900);
        await pergamino(T, a, T.sesion);
      }).catch(() => {}); // una entrega que falla no puede dejar a las de detrás sin irse
      await T.cola;
      await irse(T, a);
    }
    async function aparecer(T, a) {
      if (T.quitado) return;
      colocar(a, F.puerta.x, F.puerta.y, true);
      T.luz.classList.add('abierta');
      await espera(30);
      a.el.style.transitionDuration = '400ms';
      a.el.classList.remove('oculto');
      await espera(420);
      T.luz.classList.remove('abierta');
    }
    async function irse(T, a) {
      if (T.quitado) { a.el.remove(); return; }
      await andar(a, F.puerta.x, F.puerta.y);
      T.luz.classList.add('abierta');
      a.el.style.transitionDuration = '400ms';
      a.el.classList.add('oculto');
      await espera(420);
      T.luz.classList.remove('abierta');
      a.el.remove();
    }
    async function pergamino(T, de, a) {
      if (T.quitado || quieto() || op.oculta() || !document.createElement('div').animate) return;
      const p = el('img', 'tll-pergamino');
      p.src = `${E.url}pergamino.svg`; p.alt = '';
      T.esc.appendChild(p);
      const punto = (q, dy) => ({ left: q.x + '%', top: q.y + dy + '%' });
      try {
        await p.animate([punto(de, -13), { left: (de.x + a.x) / 2 + '%', top: Math.min(de.y, a.y) - 25 + '%' },
                         punto(a, -13)], { duration: 600, easing: 'ease-in-out' }).finished;
      } finally { p.remove(); }
    }
    function pintarLista(T) {
      T.lista.replaceChildren();
      if (!T.ranas.length) T.lista.appendChild(el('span', 'vacia', 'Sin subagentes ahora.'));
      for (const r of T.ranas) {
        const f = figuraDe(r.sub, E);
        const chip = el('div', 'tll-rana');
        if (f.img) { const im = el('img'); im.src = f.img; im.alt = ''; chip.appendChild(im); }
        else chip.appendChild(el('span', 'ini', f.inicial));
        const texto = el('span');
        texto.append(el('b', null, (E.nombres || {})[r.sub.rol] || r.sub.tipo || 'Subagente'));
        if (r.sub.que) texto.append(' · ' + r.sub.que);
        chip.title = (r.sub.tipo || '') + (r.sub.que ? ': ' + r.sub.que : '');
        chip.appendChild(texto);
        T.lista.appendChild(chip);
      }
      const n = T.ranas.length + 1;
      T.cuantas.textContent = `${n} ${n === 1 ? 'rana' : 'ranas'}`;
    }
    function quitar(T) {
      T.quitado = true;
      if (T.zeta) { op.cancelar(T.zeta); relojes.delete(T.zeta); T.zeta = null; }
      parar(T.sesion);
      for (const r of T.ranas) if (r.actor) parar(r.actor);
      T.el.remove();
      talleres.delete(T.clave);
    }
    function pintarResumen() {
      const ts = [...talleres.values()];
      const trab = ts.filter((t) => t.estado === 'trabajando').length;
      const esp = ts.filter((t) => t.estado === 'espera').length;
      const ranas = ts.reduce((n, t) => n + t.ranas.length + 1, 0);
      resumen.replaceChildren();
      for (const [n, texto, clase] of [[ts.length, 'talleres'], [trab, 'trabajando'],
                                        [esp, 'esperan tu sí', esp ? 'hay-espera' : ''], [ranas, 'ranas']]) {
        const s = el('span', clase || null);
        s.append(el('b', null, String(n)), ' ' + texto);
        resumen.appendChild(s);
      }
    }

    // ── lo que llega de cada sondeo ──
    function aplicar(datos) {
      const lista = (datos && datos.talleres) || [];
      ultimo = datos || {};
      const vieja = esVieja();
      const c = comparar(previos, lista);
      const primera = previos === null;
      previos = lista;
      for (const { de, a } of c.renombrar) {
        const T = talleres.get(de);
        if (T) { talleres.delete(de); T.clave = a; talleres.set(a, T); }
      }
      for (const k of c.idos) { const T = talleres.get(k); if (T) quitar(T); }
      for (const t of c.nuevos) nuevoTaller(t);
      for (const t of lista) { const T = talleres.get(t.clave); if (T) cabecera(T, t); }
      for (const { clave, estado } of c.estados) { const T = talleres.get(clave); if (T) ponerEstado(T, estado); }
      for (const { clave, sub } of c.llegan) {
        const T = talleres.get(clave);
        if (T) { llega(T, sub, primera || vieja); pintarLista(T); }
      }
      for (const { clave, id } of c.salen) { const T = talleres.get(clave); if (T) sale(T, id); }
      pintarResumen();
      revisar();
      return c;
    }

    /* ¿La última muestra es de ahora? Se mira en cada latido, cambie o no la
     * región: si el muestreo muere con la página abierta, lo que llega es
     * idéntico y `aplicar` no corre. Vieja: se dice y la escena se para.
     * Cuando vuelve una buena, sigue. */
    let ultimo = {};
    let estabaVieja = false;
    function esVieja() {
      return edad(ultimo.tomado_en, op.ahora()) > VIEJA_S && ((ultimo.talleres || []).length > 0);
    }
    function revisar() {
      const vieja = esVieja();
      if (aviso) {
        aviso.hidden = !vieja;
        aviso.textContent = vieja ? 'Esto es lo último que se midió y ya no es de ahora: el muestreo del hub no ' +
          'está corriendo. Mira Máquina o Servicios.' : '';
      }
      if (vieja && !estabaVieja) pausar();
      else if (!vieja && estabaVieja) reanudar();
      estabaVieja = vieja;
    }

    /* Pestaña oculta: fuera todos los relojes. Al volver, cada uno a lo suyo. */
    function pausar() {
      for (const id of relojes) op.cancelar(id);
      relojes.clear();
      for (const T of talleres.values()) {
        T.zeta = null;
        for (const a of [T.sesion, ...T.ranas.map((r) => r.actor).filter(Boolean)]) { a.reloj = null; a.el.classList.remove('animado'); }
      }
    }
    function reanudar() {
      if (esVieja() || op.oculta()) return;
      for (const T of talleres.values()) {
        ponerEstado(T, T.estado);
        for (const r of T.ranas) {
          if (!r.actor || !r.actor.el.isConnected || r.saliendo) continue;
          callar(r.actor); // un «¡Voy!» cuyo plazo se canceló al pausar
          animar(r.actor);
        }
      }
    }

    return { aplicar, revisar, pausar, reanudar, talleres };
  }

  // ── Arranque ─────────────────────────────────────────────────────────────

  function arrancar() {
    const raiz = document.querySelector('[data-talleres]');
    if (!raiz) return;
    let escena;
    try {
      escena = JSON.parse(raiz.querySelector('[data-escena]').textContent);
    } catch (e) {
      if (window.HubUI) window.HubUI.avisar({ titulo: 'Los talleres no se pueden pintar', mensaje: String(e) });
      return;
    }
    const leer = () => {
      const d = raiz.querySelector('[data-datos]');
      try { return d ? JSON.parse(d.textContent) : { talleres: [] }; } catch (e) { return { talleres: [] }; }
    };
    const mm = window.matchMedia ? window.matchMedia('(prefers-reduced-motion: reduce)') : null;
    const t = crear(raiz, {
      escena,
      programar: (f, ms) => setTimeout(f, ms),
      cancelar: (id) => clearTimeout(id),
      oculta: () => document.hidden,
      reducido: () => !!(mm && mm.matches),
      ahora: () => Date.now(),
    });
    t.aplicar(leer());
    raiz.classList.add('con-escena');
    document.addEventListener('hub:repintado', (ev) => {
      const r = ev.detail && ev.detail.regiones;
      if (!r || r.includes('talleres')) t.aplicar(leer());
    });

    let latido = 0;
    let fallos = 0;
    async function pedir() {
      if (document.hidden || !window.HubSinRecarga) return;
      try {
        await window.HubSinRecarga.refrescar(['talleres']);
        fallos = 0;
      } catch (e) {
        // Uno suelto es un reinicio de hub-web; se sigue intentando, y se
        // dice una vez al tercero seguido (regla dura 21).
        if (++fallos === 3 && window.HubUI) {
          window.HubUI.avisar({ titulo: 'Los talleres no se están actualizando',
                                mensaje: `${e.message}. Se sigue intentando cada 10 s.` });
        }
      }
      t.revisar();
    }
    const marcha = () => { if (!latido && !document.hidden) latido = setInterval(pedir, LATIDO_MS); };
    document.addEventListener('visibilitychange', () => {
      if (document.hidden) { clearInterval(latido); latido = 0; t.pausar(); }
      else { t.reanudar(); t.revisar(); pedir(); marcha(); }
    });
    marcha();
  }

  const global = typeof window !== 'undefined' ? window : globalThis;
  global.HubTalleres = { comparar, repartir, figuraDe, edad, crear };
  if (typeof document !== 'undefined' && document.querySelector) {
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', arrancar);
    else arrancar();
  }
})();
