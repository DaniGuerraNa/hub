/* Diálogos propios en lugar de alert/confirm/prompt del navegador.
 *
 * Los nativos bloquean el hilo, no se pueden estilar y en una app donde se pasan
 * horas se sienten ajenos. Se usa <dialog>, que ya trae Esc, foco y backdrop sin
 * ninguna librería.
 *
 * Todas devuelven una promesa: `if (await HubUI.confirmar({...}))`.
 */
(function () {
  function construir({ titulo, cuerpo, botones }) {
    const dlg = document.createElement('dialog');
    dlg.className = 'dlg';
    dlg.innerHTML = `
      <form method="dialog">
        <h3>${titulo || ''}</h3>
        <div class="dlg-cuerpo">${cuerpo || ''}</div>
        <div class="dlg-pie">${botones}</div>
      </form>`;
    document.body.appendChild(dlg);
    return dlg;
  }

  function escapar(s) {
    return String(s ?? '').replace(/[&<>"']/g, c =>
      ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }

  function cerrarDespues(dlg, resolver, valor) {
    dlg.addEventListener('close', () => { dlg.remove(); resolver(valor()); }, { once: true });
  }

  const HubUI = {
    confirmar({ titulo, mensaje, aceptar = 'Aceptar', peligro = false }) {
      return new Promise(resolver => {
        const dlg = construir({
          titulo: escapar(titulo),
          cuerpo: `<p>${escapar(mensaje)}</p>`,
          botones: `
            <button value="no" class="declinar">Cancelar</button>
            <button value="si" class="${peligro ? 'peligro' : 'aceptar'}">${escapar(aceptar)}</button>`,
        });
        cerrarDespues(dlg, resolver, () => dlg.returnValue === 'si');
        dlg.showModal();
        dlg.querySelector('button[value="no"]').focus();
      });
    },

    preguntar({ titulo, etiqueta, valor = '', aceptar = 'Guardar',
                multilinea = false, nota = '', cta = false }) {
      return new Promise(resolver => {
        const campoHtml = multilinea
          ? `<textarea name="dato" rows="9">${escapar(valor)}</textarea>`
          : `<input type="text" name="dato" value="${escapar(valor)}" autocomplete="off">`;
        const dlg = construir({
          titulo: escapar(titulo),
          cuerpo: `
            <label>${escapar(etiqueta || '')}</label>
            ${campoHtml}
            ${nota ? `<p class="tenue" style="margin-top:10px">${escapar(nota)}</p>` : ''}`,
          botones: `
            <button value="no" class="declinar">Cancelar</button>
            <button value="si" class="${cta ? 'cta' : 'aceptar'}">${escapar(aceptar)}</button>`,
        });
        const campo = dlg.querySelector(multilinea ? 'textarea[name=dato]' : 'input[name=dato]');
        cerrarDespues(dlg, resolver, () =>
          dlg.returnValue === 'si' && campo.value.trim() ? campo.value.trim() : null);
        dlg.showModal();
        multilinea ? campo.focus() : campo.select();
      });
    },

    avisar({ titulo, mensaje }) {
      return new Promise(resolver => {
        const dlg = construir({
          titulo: escapar(titulo),
          cuerpo: `<p>${escapar(mensaje)}</p>`,
          botones: `<button value="ok" class="aceptar">Entendido</button>`,
        });
        cerrarDespues(dlg, resolver, () => undefined);
        dlg.showModal();
      });
    },
  };

  window.HubUI = HubUI;
})();

/* Comportamientos compartidos de los componentes de `_ui.html`.
 *
 * Todo por DELEGACIÓN desde el documento: las vistas pintan menús y nombres
 * editables en sitios que no existen al cargar —la bandeja se repinta, las
 * pestañas se reconcilian— y engancharse a cada nodo obligaría a reengancharse
 * en cada pintado. Un oyente arriba funciona para lo que venga después. */
(function () {
  // Marca de que el JS vive. El CSS lo usa para esconder el formulario de
  // renombrar: sin script no se pone la clase, se ve el campo de siempre y la
  // página se degrada a lo que había en vez de a nada.
  document.body.classList.add('con-js');

  const menus = () => document.querySelectorAll('details.menu[open]');

  // Cerrar los menús que no contienen a lo que se ha pulsado. Sin esto quedan
  // dos abiertos a la vez y el segundo tapa al primero.
  //
  // En `pointerdown` y no sólo en `click`: se dispara antes y en casos donde el
  // `click` no llega a producirse —arrastrar el tirador del terminal, empezar a
  // seleccionar texto, pulsar sobre una barra de scroll—. Con `click` a secas el
  // menú se quedaba abierto en todos ellos.
  const cerrarAjenos = (e) => {
    for (const m of menus()) if (!m.contains(e.target)) m.open = false;
  };
  document.addEventListener('pointerdown', cerrarAjenos, true);

  document.addEventListener('click', (e) => {
    cerrarAjenos(e);

    const lapiz = e.target.closest && e.target.closest('.editable > .lapiz');
    if (lapiz) {
      const caja = lapiz.parentElement;
      caja.classList.add('editando');
      const campo = caja.querySelector('input[type=text]');
      if (campo) { campo.focus(); campo.select(); }
      return;
    }
    const cancelar = e.target.closest && e.target.closest('.editable .cancelar');
    if (cancelar) {
      const caja = cancelar.closest('.editable');
      const campo = caja.querySelector('input[type=text]');
      // Devolver el valor original: si no, cancelar y volver a abrir enseña lo
      // que se estaba escribiendo, que ya no es el nombre de nada.
      if (campo) campo.value = campo.defaultValue;
      caja.classList.remove('editando');
    }
  });

  document.addEventListener('keydown', (e) => {
    if (e.key !== 'Escape') return;
    let algo = false;
    for (const m of menus()) { m.open = false; algo = true; }
    const editando = document.querySelector('.editable.editando');
    if (editando) {
      const campo = editando.querySelector('input[type=text]');
      if (campo) campo.value = campo.defaultValue;
      editando.classList.remove('editando');
      algo = true;
    }
    // Sólo se traga la tecla si de verdad cerró algo: `Escape` también sirve
    // para salir de la paleta y del chat, y comérselo aquí los rompería.
    if (algo) e.stopPropagation();
  }, true);

  /* Los `<select>` de proyecto: acotados y con búsqueda.
   *
   * Un `<select>` nativo despliega tantas filas como opciones haya —con veinte
   * proyectos, media pantalla— y no deja escribir para encontrar una. Se le
   * pone delante un campo de texto que filtra, y la lista tiene altura máxima.
   *
   * Se construye sobre el `<select>` real, que sigue en el DOM y sigue siendo
   * lo que se envía: si esto falla, el formulario sigue funcionando. */
  function comboDe(sel) {
    if (sel.dataset.combo === 'listo' || sel.multiple) return;
    sel.dataset.combo = 'listo';

    const caja = document.createElement('div');
    caja.className = 'combo';
    sel.parentNode.insertBefore(caja, sel);
    caja.appendChild(sel);

    const boton = document.createElement('button');
    boton.type = 'button';
    boton.className = 'combo-abre';
    const pop = document.createElement('div');
    pop.className = 'combo-pop';
    const busca = document.createElement('input');
    busca.type = 'text';
    busca.className = 'combo-busca';
    busca.placeholder = 'Escribe para filtrar…';
    busca.setAttribute('aria-label', 'Filtrar opciones');
    const lista = document.createElement('div');
    lista.className = 'combo-lista';
    pop.append(busca, lista);
    caja.append(boton, pop);

    const opciones = [...sel.options];
    const pintarBoton = () => {
      const o = sel.options[sel.selectedIndex];
      boton.textContent = o ? o.textContent.trim() : '—';
    };
    const pintarLista = (filtro) => {
      const f = (filtro || '').toLowerCase();
      lista.innerHTML = '';
      const vistos = opciones.filter(o => o.textContent.toLowerCase().includes(f));
      if (!vistos.length) {
        const v = document.createElement('div');
        v.className = 'combo-vacio';
        v.textContent = 'Nada coincide';
        lista.appendChild(v);
        return;
      }
      for (const o of vistos) {
        const b = document.createElement('button');
        b.type = 'button';
        b.className = 'combo-op' + (o.selected ? ' puesta' : '');
        b.textContent = o.textContent.trim();
        b.addEventListener('click', () => {
          sel.value = o.value;
          // `change` a mano: cambiar `value` por código no lo dispara, y las
          // vistas que filtran al vuelo escuchan justamente eso.
          sel.dispatchEvent(new Event('change', { bubbles: true }));
          pintarBoton();
          caja.classList.remove('abierto');
        });
        lista.appendChild(b);
      }
    };

    boton.addEventListener('click', () => {
      const abre = !caja.classList.contains('abierto');
      document.querySelectorAll('.combo.abierto').forEach(c => c.classList.remove('abierto'));
      caja.classList.toggle('abierto', abre);
      if (abre) { busca.value = ''; pintarLista(''); busca.focus(); }
    });
    busca.addEventListener('input', () => pintarLista(busca.value));
    busca.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') { caja.classList.remove('abierto'); boton.focus(); e.stopPropagation(); }
      if (e.key === 'Enter') {
        e.preventDefault();
        const primera = lista.querySelector('.combo-op');
        if (primera) primera.click();
      }
    });
    document.addEventListener('click', (e) => {
      if (!caja.contains(e.target)) caja.classList.remove('abierto');
    });
    pintarBoton();
  }

  const combos = () => document.querySelectorAll('select[data-combo="si"]');
  combos().forEach(comboDe);
  // Global aparte y no colgado de `HubUI`: eso es el contrato de los diálogos
  // —«las tres formas de preguntar»— y tiene un test que lo afirma entero.
  // Meter aquí una cuarta cosa lo habría roto por mezclar dos conceptos.
  // Se expone porque hay listas que se repintan y hay que volver a pasar.
  window.HubCombos = { repasar: () => combos().forEach(comboDe) };
})();
