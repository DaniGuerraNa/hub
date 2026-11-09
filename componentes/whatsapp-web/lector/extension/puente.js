'use strict';
// Mundo aislado de la extensión: recibe lo del lector y lo pasa a `fondo.js`.
// Sólo mensajes de esta misma ventana y con la marca del lector.
const puerto = chrome.runtime.connect({ name: 'lector' });
window.addEventListener('message', (e) => {
    if (e.source !== window || !e.data || e.data.__hub !== 'lector') return;
    try {
        puerto.postMessage({ tipo: String(e.data.tipo), datos: e.data.datos });
    } catch (err) {
        /* la extensión se recargó: la página tendrá que recargarse también */
    }
});
