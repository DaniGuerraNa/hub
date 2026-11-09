/* Refresca /navegante sola mientras algo está pasando (una corrida en curso,
 * una grabación, una pregunta esperando): son cosas que cambian sin que la
 * persona haga nada, y la pantalla no tiene otra forma de enterarse. La usan
 * también /reuniones y la ficha de una reunión.
 *
 * Nunca mientras se escribe: repintar con el foco en un campo se come lo
 * tecleado (el nombre de un flujo a medio poner, una consulta).
 *
 * Por `HubSinRecarga.refrescar` y no `location.reload()` (C-0167): recargar
 * cada cinco segundos era la página entera parpadeando, volviendo arriba y
 * cerrando lo que se hubiera abierto. Ahora se cambia sólo lo que cambió, y en
 * cuanto deja de haber algo en marcha —la página ya no trae `data-refrescar`—
 * se deja de preguntar. Si el hub no contesta se dice una vez y se para.
 */
(function () {
  // Sólo lo que está dentro de una región, que es lo único que se repinta
  // (C-0187). El panel del secretario va en todas las pantallas y marca sus
  // casillas desde lo guardado al cargar: mirando el documento entero, con
  // «Leer las respuestas en voz alta» puesta la pantalla no volvía a
  // actualizarse nunca. Su borrador, el foco en él o la paleta, igual.
  const CAMPOS = ['textarea', 'input[type=text]', 'input:not([type])', 'select',
                  'input[type=checkbox]', 'input[type=radio]']
    .map((c) => '[data-region] ' + c).join(', ');

  // También lo elegido y no enviado: en /reuniones, repintar devolvía el
  // monitor y el micro de «Grabar» a los de por omisión, y se podía grabar el
  // equivocado.
  function escribiendo() {
    const a = document.activeElement;
    if (a && /^(INPUT|TEXTAREA|SELECT)$/.test(a.tagName) && a.closest('[data-region]')) return true;
    const tocado = (c) => {
      // Sin ninguna `<option selected>`, la de por omisión es la primera: medido
      // en /navegante, comparar `selected` con `defaultSelected` daba «tocado»
      // a un `<select>` que nadie había tocado, y la pantalla dejaba de
      // actualizarse.
      if (c.tagName === 'SELECT') {
        const opciones = [...(c.options || [])];
        const inicial = Math.max(0, opciones.findIndex((o) => o.defaultSelected));
        return opciones.length > 0 && c.selectedIndex !== inicial;
      }
      if (c.type === 'checkbox' || c.type === 'radio') return c.checked !== c.defaultChecked;
      return c.value && c.value !== c.defaultValue;
    };
    return [...document.querySelectorAll(CAMPOS)].some(tocado);
  }
  let latido = 0;
  let ocupado = false;

  async function mirar() {
    if (ocupado || escribiendo()) return;
    if (!window.HubSinRecarga) { location.reload(); return; }
    ocupado = true;
    try {
      await window.HubSinRecarga.refrescar();
    } catch (e) {
      clearInterval(latido); latido = 0;
      if (window.HubUI) {
        window.HubUI.avisar({ titulo: 'La pantalla dejó de actualizarse',
                             mensaje: `${e.message}. Recarga la página cuando el hub vuelva.` });
      }
    } finally {
      ocupado = false;
    }
  }

  // Arranca si hay algo en marcha y para si ya no. Se repasa tras cada
  // repintado: una acción sin recargar («Grabar») puede empezar algo que antes
  // no estaba, y la página ya no se carga de nuevo para enterarse.
  function repasar() {
    const raiz = document.querySelector('[data-refrescar]');
    if (!raiz) { if (latido) { clearInterval(latido); latido = 0; } return; }
    if (latido) return;
    const segundos = Math.max(3, parseInt(raiz.dataset.refrescar, 10) || 5);
    latido = setInterval(mirar, segundos * 1000);
  }

  repasar();
  document.addEventListener('hub:repintado', repasar);
})();
