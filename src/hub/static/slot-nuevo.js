/* «Slot nuevo» desde Trabajo: un diálogo y, al aceptar, el formulario normal.
 *
 * Antes sólo se creaba desde la ficha del proyecto o pidiéndoselo al
 * asistente, y quien lo usó por primera vez no sabía ni qué era un slot ni
 * dónde se hacía (22-oct). Por eso el diálogo lo explica en una frase.
 *
 * `data-nuevo-slot="<proyecto>"` lo abre con ese proyecto elegido; vacío,
 * deja elegir entre los de `#proyectos-para-slot`. Lo lleva un botón, que se
 * pulsa, o una `<option>` del selector del móvil (`#ir-a`), que se elige
 * (C-0011).
 */
(function () {
  function proyectos() {
    try {
      return JSON.parse(document.getElementById('proyectos-para-slot').textContent || '[]');
    } catch (e) { return []; }
  }

  async function abrir(proyecto) {
    const todos = proyectos();
    const elegido = proyecto || (todos[0] || [])[0] || '';
    const campos = [];
    if (!proyecto) {
      campos.push({ nombre: 'proyecto_id', etiqueta: 'Proyecto', valor: elegido, opciones: todos });
    }
    campos.push(
      { nombre: 'nombre', etiqueta: 'Nombre', requerido: true, marca: 'Arreglar el login',
        pista: 'En qué vas a trabajar. Es lo que verás en la lista.' },
      { nombre: 'ruta', etiqueta: 'Carpeta (opcional)', marca: 'la del proyecto',
        pista: 'Vacía, sus terminales se abren en la carpeta del proyecto.' },
    );
    const nombreProyecto = (todos.find(p => p[0] === elegido) || [])[1] || elegido;
    const datos = await HubUI.formulario({
      titulo: proyecto ? `Slot nuevo en ${nombreProyecto}` : 'Slot nuevo',
      aceptar: 'Crear y abrir',
      campos,
      nota: 'Un slot es una línea de trabajo dentro de un proyecto: sus terminales, '
          + 'su nota y sus conversaciones con Claude. Si cierras la terminal, el slot '
          + 'sigue ahí y puedes retomar la conversación.',
    });
    if (!datos) return;

    const form = document.createElement('form');
    form.method = 'post';
    form.action = '/slot/nuevo';
    form.hidden = true;
    const valores = { proyecto_id: elegido, ...datos, ir: 'trabajo', autostart_claude: '1' };
    for (const [k, v] of Object.entries(valores)) {
      const i = document.createElement('input');
      i.type = 'hidden'; i.name = k; i.value = v;
      form.appendChild(i);
    }
    document.body.appendChild(form);
    form.submit();
  }

  document.addEventListener('click', (e) => {
    const boton = e.target.closest && e.target.closest('[data-nuevo-slot]');
    // Una opción se abre al elegirla, abajo. Firefox además le manda el clic
    // al elegirla en el desplegable: abrirla también aquí daría dos diálogos.
    if (!boton || boton.tagName === 'OPTION') return;
    e.preventDefault();
    abrir(boton.dataset.nuevoSlot);
  });

  /* En el móvil el raíl es un `<select>`, y a una `<option>` no le llega el
   * clic en Chrome: se abre con el `change` del selector. El selector vuelve a
   * lo que enseñaba —«+ Slot nuevo» no es un sitio— y, si se crea, la página
   * nueva ya marca el slot. */
  document.addEventListener('change', (e) => {
    const selector = e.target;
    if (!selector || selector.tagName !== 'SELECT') return;
    const opcion = selector.selectedOptions && selector.selectedOptions[0];
    if (!opcion || !opcion.dataset || !('nuevoSlot' in opcion.dataset)) return;
    const antes = [...selector.options].findIndex(o => o.defaultSelected);
    selector.selectedIndex = antes >= 0 ? antes : 0;
    abrir(opcion.dataset.nuevoSlot);
  });
})();
