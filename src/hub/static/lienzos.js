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
  const pestanas = document.querySelectorAll('.pest-lado button[data-hoja]');
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
    /* `.viendo`, no `:not([hidden])`: los bloques conservan el atributo `hidden`
     * y se revelan por clase, así que aquel selector no casaba con ninguno y
     * esto caía SIEMPRE al respaldo de abajo. O sea que el arreglo que describe
     * el comentario de arriba nunca llegó a funcionar: el panel enseñaba los
     * lienzos del slot con el que entraste aunque cambiaras de pestaña. */
    const bloque = document.querySelector('.por-ventana.viendo');
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

  const ES_GRAFO = { arquitectura: true, pasos: true };

  /* 🔴 Una plantilla que no se sabe pintar se enseña CRUDA, nunca vacía.
   *
   * Es como estuvieron `arquitectura`, `pasos` y `comparativa` hasta que se
   * portaron sus motores: el lienzo se guardaba bien y se leía como texto, que
   * es feo pero recuperable. La que viene después seguirá igual. */
  function crudo(texto, aviso) {
    return (aviso ? `<p class="lienzo-fallo">⚠ ${escapar(aviso)}</p>` : '')
      + `<div class="lienzo-crudo">${escapar(texto)}</div>`;
  }

  /* El cuerpo pintado de un lienzo. Una sola función porque la lupa pinta lo
   * MISMO a otro tamaño: si fueran dos caminos, el diagrama grande podría
   * enseñar algo distinto del pequeño sin que nada lo dijera. */
  function contenido(l, sufijo) {
    if (l.plantilla === 'decisiones') return decisiones(l);
    if (ES_GRAFO[l.plantilla]) return grafo(l, sufijo);
    if (l.plantilla === 'comparativa') return comparativa(l);
    return crudo(l.cuerpo);
  }

  function pintar(l) {
    if (!l) { vista.innerHTML = ''; return; }
    const cuerpo = contenido(l, '');

    /* La lupa se ofrece cuando hay algo que no cabe en una columna de ~330 px:
     * un diagrama, que ahí se escala hasta que las etiquetas no se leen, y una
     * comparativa, cuyas columnas se cortan — y lo que decide en una
     * comparativa es ver los valores del mismo criterio uno al lado de otro.
     *
     * `decisiones` queda fuera a propósito: sus botones escriben en el archivo
     * y una copia en la capa sería un segundo sitio desde donde guardar. */
    const ampliable = (ES_GRAFO[l.plantilla] && cuerpo.indexOf('<svg') >= 0)
      || (l.plantilla === 'comparativa' && cuerpo.indexOf('<table') >= 0);
    const lupa = ampliable
      ? '<button type="button" class="sutil" id="lienzo-ampliar">Ampliar</button>' : '';
    vista.innerHTML = `<div class="cabl"><b>${escapar(l.titulo)}</b>
      <span class="tenue">${escapar(l.plantilla)}</span>${lupa}</div>${cuerpo}`;
    if (l.plantilla === 'decisiones') atarDecisiones(l);
    if (ampliable) atarLupa(l);
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

  // ── Las plantillas de dibujo: `arquitectura`, `pasos`, `comparativa` ─────
  //
  // Portadas de `maquetas/h-lienzo-vivo.html`, que existió para contestar la
  // pregunta de la que dependía todo: si el hub podía dibujar un diagrama
  // decente sin traerse una librería. Podía — y aquí, además, tiene que caber
  // en una columna estrecha con nombres largos de verdad, que es lo que la
  // maqueta no tuvo delante.
  //
  // 🔴 Ni una sola dependencia y ni un color literal: las piezas salen con su
  // clase y el color lo pone el sistema visual desde `trabajo.html`. Un hex
  // aquí sería una pieza que no cambia cuando cambie la paleta.

  const G = {
    ANCHO: 168, ALTO_MIN: 40, SEP_X: 60, SEP_Y: 20,
    /* Alto de línea, cuántos caracteres caben en una y cuántas líneas admite
       una caja. `CARS` es una estimación y no una medida: medir texto exige
       montar el SVG y volver a leerlo del DOM, y equivocarse en un carácter
       sólo cuesta un salto de línea de más — no un dibujo roto.

       🔴 Los tres números salen del navegador, no del cálculo (regla 20). Con
       22×4 —lo que parecía de sobra— tres de los diez pasos del lienzo del 23
       de septiembre salían cortados con «…»: el más largo mide 90 caracteres.
       A 12,5 px una línea de caja ocupa ~5,9 px por carácter, así que en los
       152 px útiles caben 24 cómodos. Y seis líneas en vez de cuatro porque la
       caja sólo crece cuando hace falta, mientras que un nombre cortado no se
       recupera: en un lienzo de `pasos`, «3 · 10-13 sep · Las tres puertas:
       hosts configurables, alta por QR, interruptor d…» no es un paso. */
    LINEA: 15, CARS: 24, LINEAS: 6,
  };

  const TIPOS = { entrada: 1, computo: 1, cola: 1, almacen: 1 };

  /* ── 1. Leer ────────────────────────────────────────────────────────────
   * El mismo subconjunto deliberadamente pequeño que en `decisiones`: sólo lo
   * que la plantilla define. Traer un YAML entero al navegador para leer dos
   * secciones sería pagar un bundle por nada. */
  function leerGrafo(cuerpo) {
    const piezas = [], flujo = [];
    let seccion = null, orientacion = 'auto';
    for (const cruda of String(cuerpo || '').split('\n')) {
      const linea = cruda.trim();
      if (!linea || linea.startsWith('#')) continue;
      if (/^piezas:/.test(linea)) { seccion = 'p'; continue; }
      if (/^flujo:/.test(linea)) { seccion = 'f'; continue; }
      if (/^orientacion:/.test(linea)) {
        orientacion = linea.slice(linea.indexOf(':') + 1).trim();
        continue;
      }
      if (/^plantilla:/.test(linea)) continue;
      if (!linea.startsWith('-')) continue;
      const cuerpoLinea = linea.slice(1).trim();

      if (seccion === 'p') {
        const m = cuerpoLinea.match(/^\{(.*)\}$/);
        if (!m) throw new Error('pieza mal escrita: ' + cuerpoLinea);
        const campos = {};
        // Se parte por comas que NO estén dentro de comillas: un nombre lleva
        // comas con toda naturalidad («λ validar, cobrar y avisar»).
        for (const par of m[1].split(/,(?=(?:[^"]*"[^"]*")*[^"]*$)/)) {
          const i = par.indexOf(':');
          if (i < 0) continue;
          campos[par.slice(0, i).trim()] = sinComillas(par.slice(i + 1).trim());
        }
        if (!campos.id) throw new Error('una pieza sin id');
        piezas.push({
          id: campos.id,
          // Un tipo que no existe cae en `computo` en vez de quedarse sin
          // estilo: el color dejaría de decir nada, pero la caja se ve.
          tipo: TIPOS[campos.tipo] ? campos.tipo : 'computo',
          nombre: campos.nombre || campos.id,
        });
      } else if (seccion === 'f') {
        const m = cuerpoLinea.match(/^(\S+)\s*(->|~>)\s*(\S+)$/);
        if (!m) throw new Error('flujo mal escrito: ' + cuerpoLinea);
        flujo.push({ de: m[1], a: m[3], flojo: m[2] === '~>' });
      }
    }
    const ids = new Set(piezas.map(p => p.id));
    // Se dice cuál falta, no «hay un error». Lo corrige él en la web, y sin el
    // nombre tendría que buscarlo a ojo entre veinte líneas.
    for (const f of flujo) {
      if (!ids.has(f.de)) throw new Error(`«${f.de}» no está en piezas`);
      if (!ids.has(f.a)) throw new Error(`«${f.a}» no está en piezas`);
    }
    return { piezas, flujo, orientacion };
  }

  function sinComillas(s) {
    return String(s == null ? '' : s).trim().replace(/^["']|["']$/g, '');
  }

  /* ── 2. Repartir en niveles ─────────────────────────────────────────────
   * La profundidad de cada pieza es su camino más largo desde una raíz. Es lo
   * que hace que NO haya que colocar ninguna caja a mano — y lo que un SVG
   * escrito por el modelo no puede tener: él sabe qué va después de qué, pero
   * no dónde cae eso en la pantalla.
   *
   * Las flechas `~>` (lectura) no cuentan para la profundidad: si contaran,
   * una tabla que todo el mundo consulta tiraría de sus lectores hacia el
   * fondo y el camino principal dejaría de leerse en línea recta. */
  function repartir({ piezas, flujo }) {
    const nivel = new Map(piezas.map(p => [p.id, 0]));
    const duros = flujo.filter(f => !f.flojo);
    for (let i = 0; i < piezas.length; i++) {      // relajación: |V| pasadas bastan
      let cambio = false;
      for (const f of duros) {
        if (nivel.get(f.a) < nivel.get(f.de) + 1) {
          nivel.set(f.a, nivel.get(f.de) + 1);
          cambio = true;
        }
      }
      if (!cambio) break;
    }

    /* 🔴 Segunda pasada, y hace falta: se vio en el navegador, no leyendo esto.
       Una pieza cuya ÚNICA entrada es de lectura se quedaba en el nivel 0 y
       salía dibujada ANTES de quien la consulta — la tabla de idempotencia
       aparecía a la izquierda del API Gateway. Se la arrastra JUNTO a su
       lector, no detrás: empujarla un nivel más allá volvería a alargar el
       flujo principal, que es justo lo que las flechas flojas no deben hacer. */
    const conEntradaDura = new Set(duros.map(f => f.a));
    for (let i = 0; i < piezas.length; i++) {
      let cambio = false;
      for (const f of flujo) {
        if (f.flojo && !conEntradaDura.has(f.a) && nivel.get(f.a) < nivel.get(f.de)) {
          nivel.set(f.a, nivel.get(f.de));
          cambio = true;
        }
      }
      if (!cambio) break;
    }

    const columnas = new Map();
    for (const p of piezas) {
      const n = nivel.get(p.id);
      if (!columnas.has(n)) columnas.set(n, []);
      columnas.get(n).push(p);
    }
    return [...columnas.entries()].sort((a, b) => a[0] - b[0]).map(e => e[1]);
  }

  /* Un nombre en varias líneas dentro de su caja.
   *
   * 🔴 Esto es lo que la maqueta no necesitaba y aquí es imprescindible. Allí
   * las piezas se llamaban «λ validar»; el primer lienzo de `pasos` de verdad
   * traía «1 · 7-8 sep · Respaldo del trabajo: tar.gz nuevo y `patron` en
   * projects.yml», y cortar a 20 caracteres deja «1 · 7-8 sep · Resp…», que no
   * es un paso: es un número. Un diagrama cuyas cajas no se pueden leer no
   * está dibujado, sólo pintado. */
  function envolver(texto) {
    const palabras = String(texto || '').split(/\s+/).filter(Boolean);
    const lineas = [];
    let linea = '';
    for (let palabra of palabras) {
      // Una palabra sola más larga que la caja —una ruta, un identificador— se
      // parte: si no, se saldría del recuadro y pisaría a la vecina.
      while (palabra.length > G.CARS) {
        if (linea) { lineas.push(linea); linea = ''; }
        lineas.push(palabra.slice(0, G.CARS - 1) + '-');
        palabra = palabra.slice(G.CARS - 1);
      }
      if (!linea) linea = palabra;
      else if ((linea + ' ' + palabra).length <= G.CARS) linea += ' ' + palabra;
      else { lineas.push(linea); linea = palabra; }
    }
    if (linea) lineas.push(linea);
    if (!lineas.length) return [''];
    if (lineas.length > G.LINEAS) {
      const cortadas = lineas.slice(0, G.LINEAS);
      const ultima = cortadas[G.LINEAS - 1];
      cortadas[G.LINEAS - 1] =
        (ultima.length > G.CARS - 1 ? ultima.slice(0, G.CARS - 1) : ultima) + '…';
      return cortadas;
    }
    return lineas;
  }

  /* ── 3. Colocar ─────────────────────────────────────────────────────────
   * Cada caja tiene SU alto, porque cada nombre ocupa lo que ocupa. La maqueta
   * podía dar por bueno un alto fijo con nombres de tres palabras; aquí un
   * alto fijo dejaría medio texto fuera del recuadro. */
  function colocar(datos) {
    const niveles = repartir(datos);
    const cajas = new Map(datos.piezas.map(p => {
      const lineas = envolver(p.nombre);
      return [p.id, { lineas, alto: Math.max(G.ALTO_MIN, lineas.length * G.LINEA + 18) }];
    }));

    /* 🔴 Se vio en el navegador (regla 20): una cadena de ocho pasos salía en
       ocho columnas, y al caber sólo el ancho del panel el SVG se escalaba
       hasta que las etiquetas no se leían. Una cadena larga y estrecha se lee
       en vertical, que además es como se lee una lista de pasos. `pasos` va
       en vertical siempre —es su razón de ser—; `arquitectura` lo decide por
       la forma del grafo, y el cuerpo puede forzarlo con `orientacion:`. */
    const anchoMax = Math.max(...niveles.map(n => n.length));
    const vertical = datos.orientacion === 'vertical'
      || (datos.orientacion !== 'horizontal'
          && (datos.plantilla === 'pasos' || (niveles.length > 4 && anchoMax <= 2)));

    const pos = new Map();
    if (vertical) {
      const anchoTotal = anchoMax * (G.ANCHO + G.SEP_X) - G.SEP_X;
      let y = 0;
      for (const fila of niveles) {
        const altoFila = Math.max(...fila.map(p => cajas.get(p.id).alto));
        let x = (anchoTotal - (fila.length * (G.ANCHO + G.SEP_X) - G.SEP_X)) / 2;
        for (const p of fila) {
          const c = cajas.get(p.id);
          pos.set(p.id, { x, y, w: G.ANCHO, h: c.alto, lineas: c.lineas, p });
          x += G.ANCHO + G.SEP_X;
        }
        y += altoFila + G.SEP_Y;
      }
    } else {
      const altos = niveles.map(col =>
        col.reduce((s, p) => s + cajas.get(p.id).alto, 0) + G.SEP_Y * (col.length - 1));
      const altoTotal = Math.max(...altos);
      niveles.forEach((col, i) => {
        let y = (altoTotal - altos[i]) / 2;
        for (const p of col) {
          const c = cajas.get(p.id);
          pos.set(p.id, { x: i * (G.ANCHO + G.SEP_X), y, w: G.ANCHO, h: c.alto,
                          lineas: c.lineas, p });
          y += c.alto + G.SEP_Y;
        }
      });
    }
    return { pos, vertical };
  }

  /* ── 4. Dibujar ───────────────────────────────────────────────────────── */
  function dibujar(datos, sufijo) {
    const { pos, vertical } = colocar(datos);
    const cajas = [...pos.values()];
    const W = Math.max(...cajas.map(v => v.x + v.w));
    const H = Math.max(...cajas.map(v => v.y + v.h));
    const cx = v => v.x + v.w / 2, cy = v => v.y + v.h / 2;
    const partes = [];

    for (const f of datos.flujo) {
      const a = pos.get(f.de), b = pos.get(f.a);
      let d;
      if (vertical) {
        if (b.y > a.y) {                       // baja: curva suave entre niveles
          const y1 = a.y + a.h, my = (y1 + b.y) / 2;
          d = `M${cx(a)} ${y1}C${cx(a)} ${my} ${cx(b)} ${my} ${cx(b)} ${b.y - 7}`;
        } else if (b.y === a.y) {
          /* 🔴 Vecinos del mismo nivel: recto, de canto a canto. Se vio en el
             navegador (regla 20). Antes caían en el rodeo de abajo, que sale
             por la derecha de quien lee y vuelve a entrar por la derecha de lo
             leído: la línea pasaba POR ENCIMA de la caja de destino y la punta
             quedaba fuera, a su derecha. Y es justo el caso más común de este
             motor —una pieza de lectura se coloca junto a su lector a
             propósito—, así que el fallo salía en casi todos los diagramas. */
          d = b.x > a.x
            ? `M${a.x + a.w} ${cy(a)}L${b.x - 7} ${cy(b)}`
            : `M${a.x} ${cy(a)}L${b.x + b.w + 7} ${cy(b)}`;
        } else {                               // vuelve hacia arriba: por el lado
          const lado = Math.max(a.x + a.w, b.x + b.w) + 22;
          d = `M${a.x + a.w} ${cy(a)}L${lado} ${cy(a)}L${lado} ${cy(b)}L${b.x + b.w + 7} ${cy(b)}`;
        }
      } else if (b.x > a.x) {                  // hacia adelante: curva suave
        const x1 = a.x + a.w, mx = (x1 + b.x) / 2;
        d = `M${x1} ${cy(a)}C${mx} ${cy(a)} ${mx} ${cy(b)} ${b.x - 7} ${cy(b)}`;
      } else if (b.x === a.x) {                // misma columna: por el lateral
        const dy = cy(b) - cy(a);
        d = `M${a.x + a.w} ${cy(a)}q26 0 26 ${dy / 2}q0 ${dy / 2} -26 ${dy / 2}`;
      } else {                                 // hacia atrás: rodea por abajo
        const y = H + 26;
        d = `M${cx(a)} ${a.y + a.h}L${cx(a)} ${y}L${cx(b)} ${y}L${cx(b)} ${b.y + b.h + 7}`;
      }
      partes.push(`<path class="ar${f.flojo ? ' flojo' : ''}" d="${d}"`
        + ` marker-end="url(#${f.flojo ? 'lec' : 'flu'}${sufijo})"/>`);
    }

    for (const v of cajas) {
      // El texto se centra sobre la caja: la primera línea sube media pila.
      const y0 = cy(v) - (v.lineas.length - 1) * G.LINEA / 2 + 4.5;
      const filas = v.lineas.map((t, i) =>
        `<tspan x="${cx(v)}" y="${y0 + i * G.LINEA}">${escapar(t)}</tspan>`).join('');
      partes.push(
        `<g class="nd nd-${escapar(v.p.tipo)}"><title>${escapar(v.p.id)} · ${escapar(v.p.tipo)}</title>`
        + `<rect x="${v.x}" y="${v.y}" width="${v.w}" height="${v.h}" rx="9"/>`
        + `<text text-anchor="middle">${filas}</text></g>`);
    }

    // El `viewBox` deja margen para las flechas que rodean por fuera; el ancho
    // se cierra con `max-width:100%` desde el CSS, así que en el panel encoge y
    // en la lupa se ve a tamaño natural.
    return `<svg class="lienzo-svg" viewBox="-16 -16 ${W + 64} ${H + 64}"`
      + ` width="${W + 64}" xmlns="http://www.w3.org/2000/svg">`
      + `<defs>${flecha('flu' + sufijo, 'flu')}${flecha('lec' + sufijo, 'lec')}</defs>`
      + partes.join('') + '</svg>';
  }

  function flecha(id, clase) {
    return `<marker id="${id}" class="${clase}" markerWidth="8" markerHeight="8"`
      + ` refX="7" refY="4" orient="auto"><path d="M0 0l8 4L0 8z"/></marker>`;
  }

  const LEYENDA = `<div class="lienzo-leyenda">
    <span class="nd-entrada"><i></i>entrada</span>
    <span class="nd-computo"><i></i>cómputo</span>
    <span class="nd-cola"><i></i>cola</span>
    <span class="nd-almacen"><i></i>almacén</span>
    <span class="tenue">— flujo · ⇢ lectura</span></div>`;

  function grafo(l, sufijo) {
    let datos;
    try {
      datos = leerGrafo(l.cuerpo);
      if (!datos.piezas.length) throw new Error('no hay ninguna pieza');
    } catch (e) {
      // 🔴 El cuerpo se enseña igual. Un lienzo mal escrito sigue siendo el
      // trabajo de alguien, y dejar el panel en blanco con el error a un lado
      // le quitaría lo único que puede corregir.
      return crudo(l.cuerpo, 'No se pudo dibujar: ' + e.message);
    }
    datos.plantilla = l.plantilla;
    return dibujar(datos, sufijo || '') + LEYENDA;
  }

  /* La lupa. El panel vive en una columna de ~330 px y una arquitectura de
   * cinco niveles mide 1000: ahí dentro el SVG se escala hasta que las
   * etiquetas dejan de leerse, que es la única forma en que este motor puede
   * fallar sin que nada parezca roto. Se abre a pantalla completa y se cierra
   * con Escape, con el fondo o con la ✕ — tres salidas, porque una capa que no
   * se sabe cerrar tapa la terminal. */
  function atarLupa(l) {
    const boton = document.getElementById('lienzo-ampliar');
    if (!boton) return;
    boton.addEventListener('click', () => {
      const capa = document.createElement('div');
      capa.className = 'lienzo-lupa';
      // Ids de marcador distintos: los dos SVG conviven en el documento y dos
      // `id` iguales hacen que el segundo apunte al primero.
      capa.innerHTML = `<div class="lupa-caja"><div class="cabl"><b>${escapar(l.titulo)}</b>
        <button type="button" class="sutil lupa-cerrar">✕</button></div>
        <div class="lupa-tela">${contenido(l, '-lupa')}</div></div>`;
      const cerrar = () => {
        capa.remove();
        document.removeEventListener('keydown', porTecla);
      };
      const porTecla = (ev) => { if (ev.key === 'Escape') cerrar(); };
      capa.addEventListener('click', (ev) => {
        if (ev.target === capa || (ev.target.classList
            && ev.target.classList.contains('lupa-cerrar'))) cerrar();
      });
      document.addEventListener('keydown', porTecla);
      document.body.appendChild(capa);
    });
  }

  /* La plantilla `comparativa`: opciones contra criterios.
   *
   * Una tabla y no tarjetas, y no es cosmética: lo que decide es DÓNDE
   * DIFIEREN las opciones, y eso sólo se ve cuando los valores del mismo
   * criterio quedan uno encima de otro. */
  function leerComparativa(cuerpo) {
    const criterios = [], opciones = [];
    let eleccion = '', porque = '', actual = null, destino = null;
    for (const cruda of String(cuerpo || '').split('\n')) {
      const linea = cruda.trim();
      if (!linea || linea.startsWith('#')) continue;
      let m;
      if ((m = linea.match(/^(criterios|valores):\s*(.*)$/))) {
        const lista = m[1] === 'criterios' ? criterios : (actual ? actual.valores : []);
        // En línea (`[a, b, c]`) o en bloque, con un guion por elemento: las
        // dos formas son YAML válido y el modelo escribe la que le sale.
        if (m[2]) { for (const v of partirLista(m[2])) lista.push(v); destino = null; }
        else destino = lista;
        continue;
      }
      if ((m = linea.match(/^eleccion:\s*(.*)$/))) { eleccion = sinComillas(m[1]); continue; }
      if ((m = linea.match(/^porque:\s*(.*)$/))) { porque = sinComillas(m[1]); continue; }
      if ((m = linea.match(/^-\s*nombre:\s*(.*)$/))) {
        actual = { nombre: sinComillas(m[1]), valores: [], nota: '' };
        opciones.push(actual);
        destino = null;
        continue;
      }
      if (actual && (m = linea.match(/^nota:\s*(.*)$/))) { actual.nota = sinComillas(m[1]); continue; }
      if (destino && (m = linea.match(/^-\s*(.+)$/))) { destino.push(sinComillas(m[1])); continue; }
    }
    return { criterios, opciones, eleccion, porque };
  }

  // Parte por comas que no estén dentro de comillas, igual que las piezas.
  function partirLista(texto) {
    const dentro = String(texto).trim().replace(/^\[|\]$/g, '');
    if (!dentro) return [];
    return dentro.split(/,(?=(?:[^"]*"[^"]*")*[^"]*$)/).map(sinComillas);
  }

  function comparativa(l) {
    const { criterios, opciones, eleccion, porque } = leerComparativa(l.cuerpo);
    if (!opciones.length) return crudo(l.cuerpo, 'No se pudo leer: no hay opciones');

    const filas = opciones.map(o => {
      const elegida = eleccion && o.nombre === eleccion;
      // 🔴 Un hueco se rellena con «—» y no se deja en blanco. La plantilla lo
      // pide por escrito: un vacío silencioso se lee como «no aplica» cuando
      // casi siempre significa «no lo he mirado», y eso decide mal.
      const celdas = criterios.map((_, i) =>
        `<td>${escapar(o.valores[i] || '—')}</td>`).join('');
      return `<tr${elegida ? ' class="elegida"' : ''}>
        <th scope="row">${escapar(o.nombre)}${elegida ? '<span class="et-eleccion">propuesta</span>' : ''}
          ${o.nota ? `<div class="nota-op">${escapar(o.nota)}</div>` : ''}</th>${celdas}</tr>`;
    }).join('');

    return `<div class="lienzo-tabla"><table>
        <thead><tr><th></th>${criterios.map(c => `<th>${escapar(c)}</th>`).join('')}</tr></thead>
        <tbody>${filas}</tbody></table></div>`
      + (porque ? `<p class="lienzo-porque"><b>Porque:</b> ${escapar(porque)}</p>` : '');
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
