'use strict';
/**
 * Lo que llega del lector de la página, escrito donde lo lee la fuente
 * `whatsapp` del secretario (`HUB_HOME/secretario/whatsapp/`): el mismo
 * `mensajes.jsonl`, `chats.json` y `estado.json` que el colector, con
 * `origen` diciendo quién lo vio (`extension` o `escritorio`). Corre en
 * Windows y escribe en la carpeta del hub por `\\wsl.localhost\…`.
 *
 * Sin dependencias: lo usan el anfitrión de la extensión y `escritorio.js`,
 * que se copian tal cual a Windows (`instalar.sh`).
 */

const path = require('path');
// En Windows van en la misma carpeta (`instalar.sh`); en el repo, formato está un nivel arriba.
let formato;
try { formato = require('./formato'); } catch { formato = require('../formato'); }

// La escritura es la del colector, con sus permisos (C-0123): no una copia.
const { asegurarCarpeta, escribirAtomico, anexar } = formato;

function crear(destino, origen) {
    asegurarCarpeta(destino);
    const R = {
        mensajes: path.join(destino, 'mensajes.jsonl'),
        chats: path.join(destino, 'chats.json'),
        estado: path.join(destino, 'estado.json'),
    };
    let ultimoError = '';

    function estado(est, detalle = '') {
        escribirAtomico(R.estado, { estado: est, detalle, latido: new Date().toISOString(), origen, pid: process.pid });
    }

    /** Un aviso del lector. Devuelve la línea escrita, si fue un mensaje. */
    function recibir(tipo, datos) {
        if (tipo === 'mensaje') {
            const l = formato.linea(datos, datos && datos.chat, origen);
            // Cuándo lo vio este lector: con `hora` da el retraso, que es una
            // de las dos cosas que se comparan entre la extensión y la app.
            if (l) l.visto = new Date().toISOString();
            if (l) anexar(R.mensajes, l);
            return l;
        }
        if (tipo === 'chats' && Array.isArray(datos)) {
            escribirAtomico(R.chats, formato.resumenChats(datos));
        } else if (tipo === 'listo') {
            ultimoError = '';
            estado('escuchando', `lector en ${origen}`);
        } else if (tipo === 'error') {
            ultimoError = String(datos).slice(0, 300);
            estado('escuchando', `lector en ${origen}; último error: ${ultimoError}`);
        }
        return null;
    }

    return { recibir, estado, rutas: R, latido: () => estado('escuchando', `lector en ${origen}` + (ultimoError ? `; último error: ${ultimoError}` : '')) };
}

module.exports = { crear };
