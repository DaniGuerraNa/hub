'use strict';
// El lado de la página del puente: lo que el lector envía sale con
// `postMessage` hacia `puente.js`, que es el que puede hablar con la extensión.
window.__hubEnviar = (tipo, datos) => window.postMessage({ __hub: 'lector', tipo, datos }, location.origin);
