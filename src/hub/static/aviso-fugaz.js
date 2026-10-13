/* El aviso de después de una acción: se lee una vez y se va.
 *
 * Lo pidió así: *«está bien para leer una vez, pero que siempre esté ahí no
 * aporta nada»*. Dos cosas: se quita el `?aviso=` de la dirección —si no,
 * recargar la página lo volvía a pintar— y se desvanece solo a los pocos
 * segundos si es de los que salieron bien (`fugaz`, lo decide `_volver`). Un
 * fallo no se desvanece nunca —regla dura 21: lo que falla se dice—; se cierra
 * a mano, y recargar ya no lo repite.
 */
(() => {
  const aviso = document.querySelector('[data-aviso-fugaz]');
  if (!aviso) return;

  try {
    const url = new URL(location.href);
    if (url.searchParams.has('aviso')) {
      url.searchParams.delete('aviso');
      url.searchParams.delete('fugaz');
      history.replaceState(null, '', url.pathname + url.search + url.hash);
    }
  } catch (e) { /* sin History API, el aviso se queda: no pasa nada */ }

  const irse = () => {
    aviso.classList.add('ido');
    setTimeout(() => { aviso.hidden = true; }, 500);
  };
  const cerrar = aviso.querySelector('[data-cerrar-aviso]');
  if (cerrar) cerrar.addEventListener('click', irse);
  if (aviso.classList.contains('fugaz')) setTimeout(irse, 5000);
})();
