/* «Guíame»: abre el chat del asistente con la pregunta de ese paso ya hecha.
 *
 * Por delegación y no un oyente por botón: los pasos los pinta el servidor y
 * así no hay que volver a enlazar nada. Si el asistente no está —no se instaló,
 * o su script no cargó— el botón no se pinta en el servidor; y si aun así se
 * pulsa, se dice en vez de no hacer nada.
 */
(function () {
  document.addEventListener('click', (e) => {
    const boton = e.target && e.target.closest ? e.target.closest('[data-guiame]') : null;
    if (!boton) return;
    if (window.HubAsistente && window.HubAsistente.preguntar) {
      window.HubAsistente.preguntar(boton.dataset.guiame);
    } else if (window.HubUI) {
      window.HubUI.avisar({ titulo: 'El asistente no está',
                            mensaje: 'Instálalo con el primer paso de esta guía.' });
    }
  });
})();
