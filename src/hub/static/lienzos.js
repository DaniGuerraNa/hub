/* El panel de lienzos, en el lado de /trabajo.
 *
 * Un lienzo es lo que Claude publica para que se VEA: unos puntos que decidir,
 * un flujo, unos pasos. Aquí se listan los del proyecto y se pinta el elegido.
 *
 * 🔴 El lienzo NO roba el foco. Cuando llega uno nuevo se enciende el punto de
 * la pestaña y la abres tú (principio 9: nada automático). Que la máquina
 * decida cuándo tienes que mirar algo es lo contrario de para lo que existe
 * esto — el objetivo era dejar de gastar atención, no que te la reclamen.
 *
 * Vive en /trabajo, así que si revienta al arrancar se lleva por delante la
 * terminal sin ningún síntoma visible (regla dura 11): por eso se prueba
 * ejecutándolo, en `test_lienzos_js.py`.
 */
(function () {
  const lista   = document.getElementById('lienzos-lista');
  const vista   = document.getElementById('lienzos-vista');
  const buscar  = document.getElementById('lienzos-buscar');
  const punto   = document.getElementById('lienzos-punto');
  const pestanas = document.querySelectorAll('.pest-lado button');
  if (!lista || !vista || !buscar) return;

  const CADENCIA = 4000;
  let elegido = null;
  let vistos = new Set();       // para saber cuál es nuevo desde que miraste
  let abierta = false;
  let latido = 0;
  // Mirando el archivo en vez de lo que está en uso. Archivar no es borrar:
  // esto es la puerta de vuelta, y sin ella archivar daría miedo.
  let viendoArchivados = false;

  function escapar(s) {
    return String(s ?? '').replace(/[&<>"']/g, c =>
      ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }

  /* El proyecto sale de la ventana que se está mirando, no de la que abrió la
   * página: cambiar de pestaña de tmux cambia de proyecto, y sin esto verías
   * los lienzos de otro trabajo sin que nada lo dijera — el mismo fallo que la
   * nota ya tuvo. */
  function proyectoActual() {
    const bloque = document.querySelector('.por-ventana:not([hidden])');
    if (bloque && bloque.dataset.proyecto) return bloque.dataset.proyecto;
    /* Sin ventana no hay bloque, y eso pasa en cuanto creas un slot y todavía
     * no has abierto nada en él. Antes se devolvía '' y la lista decía «aún no
     * hay lienzos en este proyecto», que no era que no hubiera: era que no
     * sabía cuál era el proyecto. Se cae al del slot elegido. */
    const taller = document.getElementById('taller');
    return (taller && taller.dataset.proyecto) || '';
  }

  function cuando(iso) {
    if (!iso) return '';
    const min = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
    if (!isFinite(min) || min < 0) return '';
    if (min < 60) return `hace ${min} min`;
    if (min < 1440) return `hace ${Math.round(min / 60)} h`;
    return `hace ${Math.round(min / 1440)} d`;
  }

  // ── Lista ────────────────────────────────────────────────────────────────

  async function refrescar() {
    const q = buscar.value.trim();
    const proyecto = proyectoActual();
    if (!q && !proyecto) { pintarLista([], false); return; }

    const url = q
      ? `/api/lienzos?q=${encodeURIComponent(q)}`
      : `/api/lienzos?proyecto=${encodeURIComponent(proyecto)}`
        + (viendoArchivados ? '&archivados=1' : '');
    try {
      const r = await fetch(url);
      // Un 400 o un 500 dan un objeto sin `lienzos`, que abajo es
      // indistinguible de «no hay ninguno». Se convierte en error para poder
      // decirlo en vez de enseñar un panel vacío con cara de estar bien.
      if (!r || !r.ok) throw new Error(`el hub respondió ${r ? r.status : 'nada'}`);
      const datos = await r.json();
      pintarLista(datos.lienzos || [], !!q);
    } catch (e) {
      if (!lista.querySelector('.lienzo-item')) {
        lista.innerHTML = '<p class="tenue">No se pudo consultar. Se reintenta solo.</p>';
      }
    }
  }

  function pintarLista(fichas, buscando) {
    // El punto se enciende con lo que no habías visto. La primera vuelta sólo
    // llena `vistos`: si no, al abrir /trabajo todo sería «nuevo» y el punto
    // dejaría de significar nada.
    const primeraVez = vistos.size === 0;
    let hayNuevo = false;
    for (const f of fichas) {
      const clave = `${f.proyecto_id}/${f.id}/${f.publicado_en || ''}`;
      if (!vistos.has(clave)) {
        vistos.add(clave);
        if (!primeraVez) hayNuevo = true;
      }
    }
    if (hayNuevo && !abierta) punto.classList.add('hay');

    if (!fichas.length) {
      lista.innerHTML = `<p class="tenue">${buscando
        ? 'Ningún lienzo se llama así.'
        : 'Aún no hay lienzos en este proyecto. Pídeselos a Claude.'}</p>`;
      vista.innerHTML = '';
      return;
    }

    lista.innerHTML = fichas.map(f => `
      <div class="lienzo-item${f.id === elegido ? ' on' : ''}"
           data-id="${escapar(f.id)}" data-proyecto="${escapar(f.proyecto_id)}">
        <div class="tt"><b>${escapar(f.titulo)}</b>
          ${f.tuyo ? '<span class="et-tuyo">editado por ti</span>' : ''}
          <button class="arch" data-arch="${escapar(f.id)}"
                  data-proy="${escapar(f.proyecto_id)}"
                  data-vuelve="${f.archivado_en ? '1' : ''}"
                  title="${f.archivado_en ? 'Devolver a la lista' : 'Archivar: sale de la lista, no se borra'}"
            >${f.archivado_en ? '↩' : '×'}</button>
        </div>
        <div class="mm">${escapar(f.plantilla)} · ${escapar(cuando(f.publicado_en))}
          ${buscando ? '· ' + escapar(f.proyecto_id) : ''}
          ${f.slot ? '· ' + escapar(f.slot) : ''}
          ${f.archivado_en ? '· archivado' : ''}</div>
      </div>`).join('');

    lista.querySelectorAll('.lienzo-item').forEach(it =>
      it.addEventListener('click', () => abrir(it.dataset.proyecto, it.dataset.id)));

    // El botón va DENTRO del item, así que su clic también abriría el lienzo:
    // se corta la propagación. Sin esto, archivar abre lo que acabas de quitar.
    lista.querySelectorAll('.arch').forEach(bt =>
      bt.addEventListener('click', async (ev) => {
        if (ev && ev.stopPropagation) ev.stopPropagation();
        await archivar(bt.dataset.proy, bt.dataset.arch, !bt.dataset.vuelve);
      }));

    if (!fichas.some(f => f.id === elegido)) abrir(fichas[0].proyecto_id, fichas[0].id);
  }

  async function archivar(proyecto, id, archivar_) {
    try {
      const r = await fetch(
        `/api/lienzo/${encodeURIComponent(proyecto)}/${encodeURIComponent(id)}/archivar`,
        { method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ archivar: archivar_ }) });
      if (!r || !r.ok) throw new Error('no se pudo');
      // El que estaba abierto desaparece de la lista: se suelta la selección
      // para no dejar el visor enseñando algo que ya no está listado.
      if (id === elegido) { elegido = null; vista.innerHTML = ''; }
      refrescar();
    } catch (e) {
      if (window.HubUI) HubUI.avisar('No se pudo archivar. El lienzo sigue como estaba.');
    }
  }

  // ── Un lienzo ────────────────────────────────────────────────────────────

  async function abrir(proyecto, id) {
    elegido = id;
    lista.querySelectorAll('.lienzo-item').forEach(it =>
      it.classList.toggle('on', it.dataset.id === id));
    try {
      const r = await fetch(`/api/lienzo/${encodeURIComponent(proyecto)}/${encodeURIComponent(id)}`);
      if (!r || !r.ok) throw new Error('no se pudo leer');
      pintar((await r.json()).lienzo);
    } catch (e) {
      vista.innerHTML = '<p class="tenue">No se pudo abrir el lienzo.</p>';
    }
  }

  function pintar(l) {
    if (!l) { vista.innerHTML = ''; return; }
    const cuerpo = l.plantilla === 'decisiones'
      ? decisiones(l)
      : `<div class="lienzo-crudo">${escapar(l.cuerpo)}</div>`;
    vista.innerHTML = `<div class="cabl"><b>${escapar(l.titulo)}</b>
      <span class="tenue">${escapar(l.plantilla)}</span></div>${cuerpo}`;
    if (l.plantilla === 'decisiones') atarDecisiones(l);
  }

  /* La plantilla `decisiones`: el caso que más atención ahorra.
   *
   * El cuerpo es YAML, pero aquí no se parsea YAML entero — se leen las tres
   * claves que la plantilla define. Traer un parser al navegador por esto sería
   * pagar un bundle para leer tres campos. Si el formato crece, crece el hub y
   * esto lee lo que le sirvan.
   */
  function leerPuntos(cuerpo) {
    const puntos = [];
    let actual = null;
    for (const cruda of String(cuerpo || '').split('\n')) {
      const linea = cruda.trim();
      let m;
      if ((m = linea.match(/^-\s*id:\s*(\S+)/))) {
        actual = { id: m[1], punto: '', justificacion: '', decision: 'pendiente' };
        puntos.push(actual);
      } else if (actual && (m = linea.match(/^(punto|justificacion|decision|propone|respuesta):\s*(.*)$/))) {
        actual[m[1]] = desescapar(m[2].replace(/^["']|["']$/g, ''));
      }
    }
    return puntos;
  }

  /* Una respuesta libre puede llevar dos puntos, comillas y saltos de línea, y
   * cualquiera de las tres cosas rompe un YAML escrito en plano. Se guarda como
   * una CADENA ENTRECOMILLADA de una sola línea, con los saltos escapados.
   *
   * En una línea y no como bloque literal (`|-`) porque el lector de esto es un
   * parser de líneas, no un YAML completo: un bloque indentado le obligaría a
   * llevar estado de indentación, y ahí es donde se rompen estos parsers. */
  function escaparYaml(s) {
    return '"' + String(s == null ? '' : s)
      .replace(/\\/g, '\\\\').replace(/"/g, '\\"').replace(/\r?\n/g, '\\n') + '"';
  }

  function desescapar(s) {
    return String(s == null ? '' : s)
      .replace(/\\n/g, '\n').replace(/\\"/g, '"').replace(/\\\\/g, '\\');
  }

  function decisiones(l) {
    const puntos = leerPuntos(l.cuerpo);
    if (!puntos.length) return `<div class="lienzo-crudo">${escapar(l.cuerpo)}</div>`;
    const hechos = puntos.filter(p => p.decision && p.decision !== 'pendiente').length;

    return `<p class="tenue" style="margin:0 0 8px">
        <b>${hechos}</b> de ${puntos.length} decididos${hechos === puntos.length
          ? ' — listo, avísale' : ''}</p>` + puntos.map((p, i) => `
      <details class="dec" data-id="${escapar(p.id)}"
               ${p.decision !== 'pendiente' ? `data-e="${escapar(p.decision)}"` : ''}>
        <summary><span class="dtt"><b>${i + 1}.</b> ${escapar(p.punto || p.id)}</span>
          <span class="dst">${escapar(p.decision || 'pendiente')}</span></summary>
        ${p.justificacion ? `<div class="djj">${escapar(p.justificacion)}
          ${p.propone ? `<div style="margin-top:5px"><b>Propone:</b> ${escapar(p.propone)}</div>` : ''}
        </div>` : ''}
        <div class="dbb">
          <button type="button" class="sutil" data-v="si">Sí</button>
          <button type="button" class="sutil" data-v="no">No</button>
          <button type="button" class="sutil" data-v="luego">Luego</button>
        </div>
        <!-- 🔴 Pedido el 2026-09-02, y se vio en el mismo momento: en el lienzo
             del kit de Telegram marcó tres puntos y los otros cinco tuvo que
             contestarlos por la terminal, porque no eran sí o no. Un lienzo que
             sólo admite tres botones obliga a partir la respuesta en dos
             sitios, que es justo el trabajo que venía a quitar. -->
        <textarea class="dresp" data-id="${escapar(p.id)}" rows="2"
                  placeholder="…o contesta con tus palabras">${escapar(p.respuesta || '')}</textarea>
        <span class="dresp-estado tenue"></span>
      </details>`).join('');
  }

  function atarDecisiones(l) {
    vista.querySelectorAll('.dec').forEach(caja => {
      caja.querySelectorAll('.dbb button').forEach(bt => {
        bt.addEventListener('click', async (ev) => {
          ev.preventDefault();
          // Volver a pulsar lo mismo lo deshace: sin esto, un clic accidental
          // es una decisión que no se puede retirar.
          const previo = caja.dataset.e || 'pendiente';
          const valor = previo === bt.dataset.v ? 'pendiente' : bt.dataset.v;
          const cuerpo = reemplazarCampo(l.cuerpo, caja.dataset.id, 'decision', valor);
          try {
            const r = await fetch(
              `/api/lienzo/${encodeURIComponent(l.proyecto_id)}/${encodeURIComponent(l.id)}`,
              { method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ cuerpo }) });
            if (!r || !r.ok) throw new Error('no se guardó');
            l.cuerpo = cuerpo;
            pintar(l);
          } catch (e) {
            // No se repinta: dejar la marca puesta sin haberla guardado sería
            // enseñar como decidido algo que él no leerá nunca.
            HubUI.avisar({ titulo: 'No se pudo guardar',
                           mensaje: 'La decisión no llegó al hub. Inténtalo otra vez.' });
          }
        });
      });

      /* La respuesta libre se guarda al salir del campo, no al teclear: cada
       * guardado reescribe el archivo entero del lienzo, y hacerlo en cada
       * pulsación son cien escrituras por párrafo. */
      const campo = caja.querySelector('.dresp');
      const marca = caja.querySelector('.dresp-estado');
      if (!campo) return;
      let previo = campo.value;
      campo.addEventListener('blur', async () => {
        if (campo.value === previo) return;      // no se toca lo que no cambió
        const cuerpo = reemplazarCampo(
          l.cuerpo, campo.dataset.id, 'respuesta', escaparYaml(campo.value));
        if (marca) marca.textContent = 'guardando…';
        try {
          const r = await fetch(
            `/api/lienzo/${encodeURIComponent(l.proyecto_id)}/${encodeURIComponent(l.id)}`,
            { method: 'POST', headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ cuerpo }) });
          if (!r || !r.ok) throw new Error('no se guardó');
          l.cuerpo = cuerpo;
          previo = campo.value;
          if (marca) marca.textContent = 'guardada';
          // 🔴 NO se repinta el lienzo: repintar reconstruye los `<details>` y
          // cierra el punto que se está contestando, justo al terminar de
          // escribir en él. La decisión sí repinta porque cambia la cabecera.
        } catch (e) {
          if (marca) marca.textContent = '';
          HubUI.avisar({ titulo: 'No se pudo guardar',
                         mensaje: 'Tu respuesta no llegó al hub. Cópiala antes de recargar.' });
        }
      });
    });
  }

  /* Sustituye la decisión de UN punto conservando el resto del archivo tal cual.
   * Se reescribe la línea y no el documento entero a propósito: el cuerpo puede
   * llevar campos que el hub todavía no conoce, y regenerarlo los borraría. */
  function reemplazarCampo(cuerpo, id, campo, valor) {
    const lineas = String(cuerpo || '').split('\n');
    let dentro = false, puesto = false;
    const salida = [];
    for (const linea of lineas) {
      const esId = linea.trim().match(/^-\s*id:\s*(\S+)/);
      if (esId) {
        // Al salir del punto sin haber encontrado su `decision:`, se añade.
        if (dentro && !puesto) salida.push(`    ${campo}: ${valor}`);
        dentro = esId[1] === id;
        puesto = false;
      }
      if (dentro && new RegExp('^\\s*' + campo + ':').test(linea)) {
        salida.push(linea.replace(new RegExp(campo + ':.*'), `${campo}: ${valor}`));
        puesto = true;
        continue;
      }
      salida.push(linea);
    }
    if (dentro && !puesto) salida.push(`    ${campo}: ${valor}`);
    return salida.join('\n');
  }

  // ── Pestañas y sondeo ────────────────────────────────────────────────────

  pestanas.forEach(bt => bt.addEventListener('click', () => {
    pestanas.forEach(b => b.classList.toggle('on', b === bt));
    document.querySelectorAll('.hoja').forEach(h =>
      h.hidden = h.dataset.hoja !== bt.dataset.hoja);
    abierta = bt.dataset.hoja === 'lienzos';
    if (abierta) { punto.classList.remove('hay'); refrescar(); }
  }));

  buscar.addEventListener('input', refrescar);

  const btArchivados = document.getElementById('lienzos-archivados');
  if (btArchivados) btArchivados.addEventListener('click', () => {
    viendoArchivados = !viendoArchivados;
    btArchivados.classList.toggle('on', viendoArchivados);
    // Se suelta lo elegido: el visor estaría enseñando algo de la otra lista.
    elegido = null;
    vista.innerHTML = '';
    refrescar();
  });

  // Se sondea aunque la hoja esté cerrada, pero despacio: es lo que enciende el
  // punto. Es una llamada a un directorio con pocos archivos.
  refrescar();
  latido = setInterval(refrescar, CADENCIA);
  window.addEventListener('beforeunload', () => clearInterval(latido));
})();
