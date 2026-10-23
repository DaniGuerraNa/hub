/* Refresca /navegante sola mientras algo está pasando (una corrida en curso,
 * una grabación, una pregunta esperando): son cosas que cambian sin que la
 * persona haga nada, y la pantalla no tiene otra forma de enterarse.
 *
 * Nunca mientras se escribe: recargar con el foco en un campo se come lo
 * tecleado (el nombre de un flujo a medio poner, una consulta).
 */
(function () {
  const raiz = document.querySelector('[data-refrescar]');
  if (!raiz) return;
  const segundos = Math.max(3, parseInt(raiz.dataset.refrescar, 10) || 5);
  function escribiendo() {
    const a = document.activeElement;
    if (a && /^(INPUT|TEXTAREA|SELECT)$/.test(a.tagName)) return true;
    return [...document.querySelectorAll('textarea, input[type=text], input:not([type])')]
      .some((c) => c.value && c.value !== c.defaultValue);
  }
  setInterval(() => { if (!escribiendo()) location.reload(); }, segundos * 1000);
})();
