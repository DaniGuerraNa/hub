'use strict';
/**
 * La app de escritorio de WhatsApp para Windows (decisión 331).
 *
 * Desde 2025 la app es WhatsApp Web dentro de un WebView2 (Edge incrustado).
 * Con el puerto de depuración abierto —sólo en 127.0.0.1, y sólo para
 * `WhatsApp.Root.exe`, por la directiva de WebView2 que pone `instalar.sh`—
 * este programa se engancha a esa página e inyecta el mismo lector que la
 * extensión (`pagina.js`). Lo que el lector ve vuelve por una «binding» de
 * CDP y se escribe con `escritor.js`.
 *
 * 🔴 No usa `Runtime.enable` ni abre la consola de la página: sólo
 * `addBinding` y `evaluate`, lo mínimo para que el lector corra y hable.
 * Mientras ese puerto esté abierto, cualquier programa de esta PC puede
 * manejar la app de WhatsApp: es el precio de esta vía, y se dice.
 *
 * Corre en Windows con Node 22 o más (trae `WebSocket` y `fetch`).
 */

const fs = require('fs');
const path = require('path');
const { crear } = require('./escritor');

const PUERTO = Number(process.env.HUB_WA_CDP || 9333);
// Cambiable sólo para probarlo contra una página falsa.
const URL_WA = process.env.HUB_WA_URL || 'https://web.whatsapp.com';
const VUELTA_MS = Number(process.env.HUB_WA_VUELTA_MS || 15 * 1000);
const LATIDO_MS = 60 * 1000;
const BINDING = '__hubLector';
const PAGINA = fs.readFileSync(path.join(__dirname, 'pagina.js'), 'utf-8');
const INYECCION = `window.__hubEnviar = (t, d) => window.${BINDING}(JSON.stringify({ tipo: t, datos: d }));\n${PAGINA}`;

function config() {
    try {
        return JSON.parse(fs.readFileSync(path.join(__dirname, 'config.json'), 'utf-8'));
    } catch {
        return { destino: process.env.HUB_WA_DESTINO };
    }
}

async function objetivo(puerto = PUERTO) {
    const r = await fetch(`http://127.0.0.1:${puerto}/json/list`);
    const lista = await r.json();
    return lista.find((t) => t.type === 'page' && String(t.url).startsWith(URL_WA)) || null;
}

/** Una conexión a la página: resuelve cuando se corta. */
function enganchar(t, escritor) {
    return new Promise((resolver) => {
        const ws = new WebSocket(t.webSocketDebuggerUrl);
        let n = 0;
        const pendientes = new Map();
        const pedir = (method, params = {}) => new Promise((ok) => {
            const id = ++n;
            pendientes.set(id, ok);
            ws.send(JSON.stringify({ id, method, params }));
        });
        let revisar;
        ws.onopen = async () => {
            await pedir('Runtime.addBinding', { name: BINDING });
            const inyectar = async () => {
                const r = await pedir('Runtime.evaluate', { expression: '!!window.__lectorHub', returnByValue: true });
                if (!(r.result && r.result.result && r.result.result.value)) {
                    await pedir('Runtime.evaluate', { expression: INYECCION });
                }
            };
            await inyectar();
            // Si la página se recarga, el lector se pierde y la binding no: se vuelve a inyectar.
            revisar = setInterval(() => inyectar().catch(() => {}), VUELTA_MS);
        };
        ws.onmessage = (ev) => {
            const m = JSON.parse(ev.data);
            if (m.id && pendientes.has(m.id)) {
                pendientes.get(m.id)(m);
                pendientes.delete(m.id);
            } else if (m.method === 'Runtime.bindingCalled' && m.params.name === BINDING) {
                try {
                    const { tipo, datos } = JSON.parse(m.params.payload);
                    escritor.recibir(tipo, datos);
                } catch (e) {
                    /* uno roto no para los demás */
                }
            }
        };
        ws.onclose = () => {
            clearInterval(revisar);
            resolver();
        };
        ws.onerror = () => {};
    });
}

async function main() {
    const escritor = crear(config().destino, 'escritorio');
    let conectado = false;
    setInterval(() => { if (conectado) escritor.latido(); }, LATIDO_MS);
    for (;;) {
        let t = null;
        try {
            t = await objetivo();
        } catch {
            t = null;
        }
        if (!t) {
            escritor.estado('parado', `la app de WhatsApp no está abierta o no tiene el puerto ${PUERTO}`);
            await new Promise((r) => setTimeout(r, VUELTA_MS));
            continue;
        }
        conectado = true;
        escritor.estado('escuchando', 'enganchado a la app de escritorio');
        await enganchar(t, escritor);
        conectado = false;
    }
}

if (require.main === module) main();
module.exports = { objetivo, enganchar, INYECCION };
