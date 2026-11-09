'use strict';
/**
 * El anfitrión de mensajería nativa de la extensión (decisión 331).
 *
 * Una extensión no puede escribir archivos ni, sin abrirle un puerto al hub,
 * hablar con él. Chrome sí puede arrancar un programa registrado para ella
 * (`chrome.runtime.connectNative`) y hablarle por stdin/stdout: cuatro bytes
 * con la longitud y un JSON. Este es ese programa: lo arranca Chrome cuando
 * la pestaña de WhatsApp Web abre el puerto, y muere cuando se cierra.
 *
 * Así el hub no gana ningún endpoint (regla dura 8): sólo aparece un archivo
 * más en la carpeta que ya leía la fuente.
 */

const fs = require('fs');
const path = require('path');
const { crear } = require('./escritor');

const LATIDO_MS = 60 * 1000;

function config() {
    return JSON.parse(fs.readFileSync(path.join(__dirname, 'config.json'), 'utf-8'));
}

/** Los mensajes de Chrome: [longitud uint32 LE][JSON], uno detrás de otro. */
function troceador(alMensaje) {
    let resto = Buffer.alloc(0);
    return (trozo) => {
        resto = Buffer.concat([resto, trozo]);
        while (resto.length >= 4) {
            const n = resto.readUInt32LE(0);
            if (resto.length < 4 + n) break;
            const cuerpo = resto.subarray(4, 4 + n);
            resto = resto.subarray(4 + n);
            try {
                alMensaje(JSON.parse(cuerpo.toString('utf-8')));
            } catch (e) {
                /* uno roto no para los demás */
            }
        }
    };
}

function responder(obj) {
    const cuerpo = Buffer.from(JSON.stringify(obj), 'utf-8');
    const cabeza = Buffer.alloc(4);
    cabeza.writeUInt32LE(cuerpo.length, 0);
    process.stdout.write(Buffer.concat([cabeza, cuerpo]));
}

function main() {
    const escritor = crear(config().destino, 'extension');
    escritor.estado('escuchando', 'extensión conectada, esperando a WhatsApp Web');
    const latido = setInterval(escritor.latido, LATIDO_MS);
    process.stdin.on('data', troceador((m) => {
        if (!m || typeof m.tipo !== 'string') return;
        try {
            escritor.recibir(m.tipo, m.datos);
        } catch (e) {
            responder({ error: String(e).slice(0, 200) });
        }
    }));
    process.stdin.on('end', () => {
        clearInterval(latido);
        escritor.estado('parado', 'se cerró WhatsApp Web en Chrome');
        process.exit(0);
    });
}

if (require.main === module) main();
module.exports = { troceador };
