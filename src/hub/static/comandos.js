/* Los huecos del comando preparado, en el navegador de archivos.
 *
 * Cada plantilla pide lo suyo —una quiere `{repo}`, otra nada— y enseñar todos
 * los campos a la vez obliga a adivinar cuáles hay que rellenar. Se enseña sólo
 * lo que pide la que está elegida.
 *
 * Si esto no llegara a ejecutarse, el formulario sigue siendo usable: los
 * campos nacen ocultos con `hidden` y el servidor ya contesta «falta «repo»»
 * sin escribir nada en ningún panel. Degradar así es a propósito.
 */
(() => {
  const selector = document.getElementById('comando-preparado');
  if (!selector) return;

  const campos = document.querySelectorAll('[data-hueco]');

  const refrescar = () => {
    const opcion = selector.options[selector.selectedIndex];
    const piden = ((opcion && opcion.dataset && opcion.dataset.huecos) || '')
      .split(',').filter(Boolean);
    campos.forEach((campo) => {
      campo.hidden = !piden.includes(campo.dataset.hueco);
    });
  };

  selector.addEventListener('change', refrescar);
  refrescar();
})();
