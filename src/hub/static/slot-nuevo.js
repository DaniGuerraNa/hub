/* «Slot nuevo» desde Trabajo: un diálogo y, al aceptar, el formulario normal.
 *
 * Antes sólo se creaba desde la ficha del proyecto o pidiéndoselo al
 * asistente, y quien lo usó por primera vez no sabía ni qué era un slot ni
 * dónde se hacía (22-oct). Por eso el diálogo lo explica en una frase.
 *
 * `data-nuevo-slot="<proyecto>"` lo abre con ese proyecto elegido; vacío,
 * deja elegir entre los de `#proyectos-para-slot`.
 */
(function () {
  function proyectos() {
    try {
      return JSON.parse(document.getElementById('proyectos-para-slot').textContent || '[]');
    } catch (e) { return []; }
  }

  document.addEventListener('click', async (e) => {
    const boton = e.target.closest && e.target.closest('[data-nuevo-slot]');
    if (!boton) return;
    e.preventDefault();
    const todos = proyectos();
    const elegido = boton.dataset.nuevoSlot || (todos[0] || [])[0] || '';
    const campos = [];
    if (!boton.dataset.nuevoSlot) {
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
      titulo: boton.dataset.nuevoSlot ? `Slot nuevo en ${nombreProyecto}` : 'Slot nuevo',
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
  });
})();
