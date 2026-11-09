'use strict';
// El único que puede arrancar el anfitrión nativo (`anfitrion.js` en Windows),
// que es quien escribe para el hub (decisión 331). Un puerto nativo abierto
// mantiene vivo este service worker mientras WhatsApp Web está abierto.
const ANFITRION = 'com.hub.whatsapp_lector';
let nativo = null;

function haciaAnfitrion(m) {
    if (!nativo) {
        nativo = chrome.runtime.connectNative(ANFITRION);
        nativo.onDisconnect.addListener(() => {
            console.warn('anfitrión desconectado:', chrome.runtime.lastError && chrome.runtime.lastError.message);
            nativo = null;
        });
    }
    nativo.postMessage(m);
}

chrome.runtime.onConnect.addListener((p) => {
    if (p.name !== 'lector' || !p.sender || !String(p.sender.url || '').startsWith('https://web.whatsapp.com/')) return;
    p.onMessage.addListener((m) => {
        try {
            haciaAnfitrion(m);
        } catch (e) {
            nativo = null;
        }
    });
});
