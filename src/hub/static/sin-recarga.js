/* Enviar un formulario sin recargar la página (C-0167, decisión 359).
 *
 * El síntoma, dicho por el dueño: «al eliminar el elemento parece que se
 * recarga la lista». Era literal: cada «Guardar», «Borrar» o «Conceder» era un
 * POST, un 303 y la página entera otra vez. Medido el 6-nov a 390 px: volvías
 * arriba del todo (de 1322 px a 0 en /canal), el plegado que habías abierto se
 * cerraba y el aviso entraba empujando el contenido.
 *
 * `<form method="post" data-sin-recarga>` hace el MISMO POST por `fetch`, sigue
 * el MISMO 303 y, de la página a la que lleva, sustituye sólo los bloques
 * marcados con `data-region="<nombre>"`. El servidor no cambia: ni JSON ni
 * trozos de plantilla por ruta. Cada fila se sigue pintando en un único sitio
 * —la plantilla— y lo que se ve sigue saliendo de la ruta GET, o sea de
 * `api.py`. Sin JavaScript, el formulario se envía como siempre.
 *
 * Cuándo NO sustituye y navega como antes (`location.assign`): si el 303 lleva
 * a otra pantalla, si la respuesta no es HTML, o si las regiones de una página
 * y otra no casan una a una. Mejor una recarga que media página vieja.
 *
 * Lo que hay dentro de una región se pinta de nuevo: un `<script>` en línea
 * ahí dentro no se vuelve a ejecutar, y un oyente atado a un nodo de dentro se
 * pierde. Lo que tenga que sobrevivir, por delegación en `document`, o
 * escuchando `hub:repintado`, que se dispara al acabar.
 *
 * Lo que falla se dice (regla dura 21): red caída, 4xx o 5xx —también el 403
 * de la comprobación de `Origin`— salen con `HubUI.avisar`, nunca en silencio.
 */
(function () {
  const PARAMS_DE_AVISO = ['aviso', 'fugaz', 'hecho'];
  // El HTML con que el servidor pintó cada región la última vez. Aparte y no
  // en un atributo: no es del documento, y con él se sabe si algo cambió.
  const servido = new WeakMap();

  // Respuestas en orden: cada petición lleva su número y lo que llega después
  // de algo más nuevo ya pintado se descarta. Sin esto, un sondeo que salió
  // antes de «Permitir» y llegó después devolvía a la pantalla la pregunta ya
  // contestada, invitando a pulsar otra vez.
  // `aplicada` es el último envío pintado; un sondeo no la mueve: si no, uno
  // que llegara antes que la respuesta de un envío la haría descartar.
  let secuencia = 0;
  let aplicada = 0;
  let ultimoEnvio = 0;
  let finEnvio = 0;
  let enVuelo = 0;

  function sinAviso(url) {
    const u = new URL(url, location.href);
    PARAMS_DE_AVISO.forEach((k) => u.searchParams.delete(k));
    const busqueda = u.searchParams.toString();
    return u.pathname + (busqueda ? '?' + busqueda : '');
  }

  /* La pantalla: la dirección sin el aviso —`/canal?aviso=Hecho` y `/canal`
   * son la misma— y sin los parámetros que la página declara que sólo cambian
   * lo de dentro de sus regiones (`data-params-de-region="tarea proyecto"`).
   * El orquestador vuelve a `?tarea=<id>` aunque se actúe desde `/orquestador`:
   * sin esto, contestarle recargaba la página entera igual que antes. */
  function pantalla(url) {
    const u = new URL(sinAviso(url), location.href);
    const marca = document.querySelector('[data-params-de-region]');
    const propios = marca ? marca.dataset.paramsDeRegion.split(/\s+/).filter(Boolean) : [];
    propios.forEach((k) => u.searchParams.delete(k));
    const busqueda = u.searchParams.toString();
    return u.pathname + (busqueda ? '?' + busqueda : '');
  }

  function regionesDe(raiz) {
    const mapa = new Map();
    raiz.querySelectorAll('[data-region]').forEach((r) => mapa.set(r.dataset.region, r));
    return mapa;
  }

  function mismas(a, b) {
    if (a.size !== b.size) return false;
    for (const k of a.keys()) if (!b.has(k)) return false;
    return true;
  }

  /* Lo que la persona había abierto sigue abierto. Sin esto, conceder un
   * permiso cerraba el plegado donde estaba el botón, que es justo lo que se
   * quería dejar de ver. Los menús (`details.menu`) no: son de un solo uso.
   * Se casan por `id`, `data-clave` o su propio formulario (la acción y el
   * primer campo oculto: `/slot/7/editar`, la persona de unos permisos); los
   * demás, por orden si hay los mismos, y si no por el texto del resumen sin
   * cifras («3 permisos» y «4 permisos»), sólo si ese texto es único: borrar
   * un slot con el «Editar» de otro abierto no puede abrir todos los «Editar». */
  function plegables(raiz) {
    return [...raiz.querySelectorAll('details:not(.menu)')];
  }
  function claveDe(d) {
    if (d.id) return '#' + d.id;
    if (d.dataset.clave) return 'c:' + d.dataset.clave;
    const propio = [...d.querySelectorAll('form')].find((f) => f.closest('details') === d);
    if (propio) {
      const oculto = propio.querySelector('input[type=hidden]');
      return 'f:' + (propio.getAttribute('action') || '') + '|' + (oculto ? oculto.value : '');
    }
    return null;
  }
  function resumenDe(d) {
    const s = d.querySelector(':scope > summary');
    return 't:' + (s ? s.textContent.replace(/\d+/g, '').replace(/\s+/g, ' ').trim() : '');
  }
  function conservarAbiertos(viejo, nuevo) {
    const antes = plegables(viejo);
    const despues = plegables(nuevo);
    const conClave = new Map();
    antes.forEach((d) => { const k = claveDe(d); if (k) conClave.set(k, d.open); });
    const sinClaveAntes = antes.filter((d) => !claveDe(d));
    const sinClaveDespues = despues.filter((d) => !claveDe(d));
    despues.forEach((d) => { const k = claveDe(d); if (k && conClave.has(k)) d.open = conClave.get(k); });
    if (sinClaveAntes.length === sinClaveDespues.length) {
      sinClaveDespues.forEach((d, i) => { d.open = sinClaveAntes[i].open; });
      return;
    }
    const cuantas = (lista) => lista.reduce((m, d) => m.set(resumenDe(d), (m.get(resumenDe(d)) || 0) + 1), new Map());
    const nAntes = cuantas(sinClaveAntes);
    const nDespues = cuantas(sinClaveDespues);
    const abiertos = new Set(sinClaveAntes.filter((d) => d.open).map(resumenDe));
    sinClaveDespues.forEach((d) => {
      const t = resumenDe(d);
      if (abiertos.has(t) && nAntes.get(t) === 1 && nDespues.get(t) === 1) d.open = true;
    });
  }

  // Las listas con su propio scroll no vuelven al principio. Se mide ANTES de
  // cambiar: un nodo ya fuera del documento dice que su scroll es cero.
  function medirScroll(viejo) {
    return [viejo, ...viejo.querySelectorAll('[id]')]
      .filter((n) => n.scrollTop > 0)
      .map((n) => [n === viejo ? null : n.id, n.scrollTop]);
  }
  function devolverScroll(nuevo, medidas) {
    medidas.forEach(([id, top]) => {
      const par = id === null ? nuevo : nuevo.querySelector('#' + CSS.escape(id));
      if (par) par.scrollTop = top;
    });
  }

  /* Cambiar el bloque de una vez, sin vaciarlo antes. La altura se sostiene
   * sólo mientras cargan las imágenes nuevas: una `<img>` recién puesta mide
   * cero hasta que se decodifica, aunque venga de la caché, y eso era otro
   * salto. Sin imágenes pendientes, se suelta antes del siguiente pintado. */
  function sustituir(viejo, nuevo) {
    conservarAbiertos(viejo, nuevo);
    const alto = viejo.offsetHeight;
    const medidas = medirScroll(viejo);
    const adoptado = document.adoptNode(nuevo);
    adoptado.style.minHeight = alto + 'px';
    viejo.replaceWith(adoptado);
    devolverScroll(adoptado, medidas);
    const pendientes = [...adoptado.querySelectorAll('img')].filter((i) => !i.complete);
    const soltar = () => { adoptado.style.minHeight = ''; if (!adoptado.getAttribute('style')) adoptado.removeAttribute('style'); };
    if (!pendientes.length) { soltar(); return; }
    const espera = pendientes.map((i) => new Promise((ok) => {
      i.addEventListener('load', ok, { once: true });
      i.addEventListener('error', ok, { once: true });
    }));
    Promise.race([Promise.all(espera), new Promise((ok) => setTimeout(ok, 1500))]).then(soltar);
  }

  /* El aviso de la acción («Guardado», o el fallo) viene en la página de
   * destino, como siempre. Se pinta flotando y lo despide `aviso-fugaz.js`. */
  function pintarAviso(doc) {
    document.querySelectorAll('[data-aviso-fugaz]').forEach((a) => a.remove());
    const aviso = doc.querySelector('[data-aviso-fugaz]');
    if (!aviso) return null;
    const sitio = document.querySelector('.envoltura > header');
    const nuevo = document.adoptNode(aviso);
    if (sitio) sitio.after(nuevo); else document.body.prepend(nuevo);
    return nuevo;
  }

  // Devuelve `false` si no se pudo sustituir y hay que navegar. `sondeo` es
  // `refrescar`: no trae aviso y no puede llevarse uno que nadie ha cerrado.
  // `antes(doc)` corre justo antes de cambiar nada.
  function aplicar(html, url, { soloEstas = null, sondeo = false, antes = null } = {}) {
    const doc = new DOMParser().parseFromString(html, 'text/html');
    const viejas = regionesDe(document);
    const nuevas = regionesDe(doc);
    if (!viejas.size || !mismas(viejas, nuevas)) return false;
    if (antes) antes(doc);
    const cuales = soloEstas && soloEstas.length ? soloEstas.filter((n) => viejas.has(n)) : [...viejas.keys()];
    const hechas = [];
    cuales.forEach((nombre) => {
      const viejo = viejas.get(nombre);
      const nuevo = nuevas.get(nombre);
      // Sin cambios no se toca: un sondeo cada pocos segundos no puede repintar
      // lo mismo una y otra vez (es el parpadeo de los programados, C-0167).
      const html = nuevo.outerHTML;
      if (servido.get(viejo) === html) return;
      sustituir(viejo, nuevo);
      servido.set(nuevo, html);
      hechas.push(nombre);
    });
    const aviso = sondeo ? null : pintarAviso(doc);
    // La dirección, sin el `?aviso=`: recargar no lo repite. Un sondeo pidió
    // esta misma, así que no hay nada que cambiar.
    if (!sondeo) {
      try {
        history.replaceState(history.state, '', sinAviso(url) + location.hash);
      } catch (e) { /* sin History API se queda la dirección de antes */ }
    }
    document.dispatchEvent(new CustomEvent('hub:repintado', { detail: { regiones: hechas } }));
    return { hechas, aviso };
  }

  /* Lo que trajo la carga cuenta como lo último servido (C-0187). Si no, el
   * primer sondeo repintaba todas las regiones aunque nada hubiera cambiado,
   * y el botón que tenía el foco desaparecía. Se toma del documento tal cual
   * está al llegar aquí: si algún script ya tocó una región, no casará y esa
   * se repinta una vez, que es lo que pasaba siempre. */
  regionesDe(document).forEach((r) => servido.set(r, r.outerHTML));

  /* El plegable donde se editaba algo («Editar» un slot o un compromiso) se
   * cierra al guardar bien: la edición acabó. Se distingue de un plegable que
   * agrupa una lista —los permisos de una persona— en que tiene un solo
   * formulario. Si volvió un fallo, se queda abierto para corregir. */
  function cerrarSiEsDeEdicion(form, doc) {
    const plegable = form.closest('details:not(.menu)');
    if (!plegable || plegable.querySelectorAll('form').length !== 1) return;
    const aviso = doc.querySelector('[data-aviso-fugaz]');
    if (aviso && !aviso.classList.contains('fugaz')) return;
    plegable.open = false;
  }

  function motivo(texto, estado) {
    try {
      const j = JSON.parse(texto);
      const detalle = Array.isArray(j && j.detail)
        ? j.detail.map((d) => (d && d.msg) || JSON.stringify(d)).join('; ') : j && j.detail;
      if (j && (j.error || detalle)) return String(j.error || detalle);
    } catch (e) { /* no era JSON */ }
    const plano = (texto || '').replace(/<[^>]*>/g, ' ').replace(/\s+/g, ' ').trim();
    return `El hub contestó ${estado}${plano ? ': ' + plano.slice(0, 200) : '.'}`;
  }

  function avisarFallo(mensaje) {
    if (window.HubUI) return window.HubUI.avisar({ titulo: 'No se pudo hacer', mensaje });
    // Sin diálogos cargados, al menos que no pase en silencio.
    console.error('sin-recarga:', mensaje);
  }

  function datosDe(form, boton) {
    let datos;
    try { datos = new FormData(form, boton || undefined); } catch (e) { datos = new FormData(form); }
    // Un navegador que no conoce el segundo argumento lo ignora sin decir nada:
    // el `name=value` del botón («accion=borrar») se perdería.
    if (boton && boton.name && !datos.has(boton.name)) datos.append(boton.name, boton.value);
    return datos;
  }

  async function enviar(form, boton) {
    if (form.dataset.enviando) return;
    form.dataset.enviando = '1';
    form.setAttribute('aria-busy', 'true');
    const botones = [...form.querySelectorAll('button, input[type=submit]')];
    const antes = botones.map((b) => [b, b.disabled, b.textContent]);
    const datos = datosDe(form, boton);
    botones.forEach((b) => {
      b.disabled = true;
      if (b.tagName === 'BUTTON' && form.dataset.unaVez) b.textContent = form.dataset.unaVez;
    });
    const n = ++secuencia;
    ultimoEnvio = n;
    enVuelo++;
    let r;
    let texto;
    try {
      r = await fetch(form.action, { method: 'POST', body: datos, credentials: 'same-origin' });
      texto = await r.text();
    } catch (e) {
      avisarFallo('Sin conexión con el hub: ' + (e && e.message ? e.message : 'la petición no llegó') +
        '. No se sabe si llegó a hacerse; recarga la página para verlo.');
      devolver(form, antes);
      return;
    } finally {
      enVuelo--;
      finEnvio = ++secuencia;
    }
    try {
      if (!r.ok) { avisarFallo(motivo(texto, r.status)); return; }
      const tipo = r.headers.get('content-type') || '';
      // `?error=` es como dicen el fallo Canal y Conexiones: se enseña la
      // página entera, con el formulario abierto. Si la dirección ya lo
      // llevaba (un segundo fallo igual), se veía igual que la de antes y se
      // tomaba por un acierto: se vaciaba y no salía nada nuevo (revisor, C-0233).
      const conError = r.redirected && new URL(r.url, location.href).searchParams.has('error');
      if (conError || !tipo.includes('text/html') || pantalla(r.url) !== pantalla(location.href)) {
        if (r.redirected) { location.assign(r.url); return; }
        // Sin 303 no hay página a la que ir, y repetir el POST no es opción:
        // se dice. Pasa sólo si un formulario marcado va a una ruta que no
        // redirige, y eso lo vigila `test_sin_recarga.py`.
        avisarFallo('El hub contestó algo que esta pantalla no sabe enseñar. ' +
          'La acción puede haberse hecho: recarga la página para verlo.');
        return;
      }
      // Algo más nuevo ya está pintado: esto es de antes y no se pinta.
      if (n < aplicada) return;
      const hecho = aplicar(texto, r.url, { antes: (doc) => cerrarSiEsDeEdicion(form, doc) });
      if (!hecho) { location.assign(r.url); return; }
      aplicada = Math.max(aplicada, n);
      // Lo escrito en un formulario que queda fuera de lo repintado ya se
      // mandó: se vacía. Salvo si volvió un fallo, que hay que poder
      // corregir y volver a mandar; pero no si el fallo dice que lo pedido se
      // hizo igual (`data-hecho`: «Apuntada, pero no entró el adjunto»), que
      // volver a pulsar lo duplicaría.
      const aviso = hecho.aviso;
      const fallo = aviso && !aviso.classList.contains('fugaz') && !('hecho' in aviso.dataset);
      if (form.isConnected && !fallo) form.reset();
    } catch (e) {
      avisarFallo('La acción llegó al hub, pero la pantalla no se pudo poner al día (' +
        (e && e.message ? e.message : e) + '). Recarga la página para verla.');
    } finally {
      devolver(form, antes);
    }
  }

  function devolver(form, antes) {
    delete form.dataset.enviando;
    form.removeAttribute('aria-busy');
    if (form.isConnected) antes.forEach(([b, desactivado, texto]) => {
      b.disabled = desactivado;
      if (b.tagName === 'BUTTON' && form.dataset.unaVez) b.textContent = texto;
    });
  }

  /* En captura y registrado después de `hub-ui.js`: la confirmación de
   * `data-confirmar` va antes y, si para el envío, aquí no se hace nada; el
   * `data-una-vez` va en burbuja y ve el envío ya parado, así que el botón lo
   * apaga y lo devuelve esta función. */
  document.addEventListener('submit', (e) => {
    const form = e.target;
    if (e.defaultPrevented || !form || !form.matches || !form.matches('form[data-sin-recarga]')) return;
    if ((form.getAttribute('method') || '').toLowerCase() !== 'post') return;
    if (!window.fetch || !window.DOMParser) return;
    e.preventDefault();
    enviar(form, e.submitter);
  }, true);

  /* Volver a pedir esta misma pantalla y cambiar sus regiones (o sólo las que
   * se digan). Para lo que cambia sin que la persona haga nada —el navegante,
   * las reuniones— y para lo que actúa por `fetch` —los contenedores—. Lo que
   * no cambió no se toca. Si falla, la promesa se rechaza: decide quien llama. */
  async function refrescar(regiones) {
    const n = ++secuencia;
    const r = await fetch(sinAviso(location.href), { credentials: 'same-origin' });
    if (!r.ok) throw new Error(`el hub contestó ${r.status}`);
    const texto = await r.text();
    // Un envío empezó o acabó mientras tanto, o sigue en vuelo: esto puede
    // ser la pantalla de antes de la acción. El siguiente latido la trae buena.
    if (enVuelo || n < ultimoEnvio || n < finEnvio) return [];
    const hecho = aplicar(texto, r.url, { soloEstas: regiones, sondeo: true });
    if (!hecho) { location.reload(); return []; }
    return hecho.hechas;
  }

  window.HubSinRecarga = { refrescar };
})();
