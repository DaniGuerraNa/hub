'use strict';
/**
 * Lo que el colector decide sin navegador: qué mensaje se guarda, con qué
 * forma, y dónde está cada cosa. Aparte de `colector.js` para poder probarlo
 * ejecutándolo (`node --test pruebas/`) sin abrir WhatsApp.
 */

const fs = require('fs');
const os = require('os');
const path = require('path');

// Lo que no es una conversación: avisos del sistema, cifrado, reacciones,
// mensajes aún sin descifrar o borrados. Guardarlos sólo haría ruido en el
// triaje, y un «este mensaje se eliminó» no le dice nada al secretario.
const TIPOS_QUE_NO_SON_CONVERSACION = new Set([
    'e2e_notification', 'gp2', 'notification', 'notification_template',
    'group_notification', 'protocol', 'reaction', 'revoked', 'ciphertext',
    'debug', 'broadcast_notification', 'call_log', 'unknown',
]);

function expandir(ruta) {
    return ruta.startsWith('~') ? path.join(os.homedir(), ruta.slice(1)) : ruta;
}

/** Las carpetas, todas por variable de entorno y con el mismo valor por
 * omisión que lee la fuente de Python (`fuentes/whatsapp.py`). */
function rutas(env = process.env) {
    const hubHome = expandir(env.HUB_HOME || '~/.local/share/hub');
    const datos = path.join(hubHome, 'secretario', 'whatsapp');
    return {
        datos,
        mensajes: path.join(datos, 'mensajes.jsonl'),
        chats: path.join(datos, 'chats.json'),
        estado: path.join(datos, 'estado.json'),
        // La copia del HTML de WhatsApp Web que guarda la librería: no es
        // secreta, y fuera del repo para que no acabe en un commit.
        cacheWeb: path.join(datos, 'cache-web'),
        secretos: expandir(env.HUB_SECRETARIO_WHATSAPP || '~/.secretos/secretario-whatsapp'),
    };
}

/** El Chromium que ya instaló Playwright (el de número más alto), para no
 * bajar otro de 170 MB. `HUB_WHATSAPP_CHROME` manda si está. */
function buscarChrome(env = process.env, base = path.join(os.homedir(), '.cache', 'ms-playwright')) {
    if (env.HUB_WHATSAPP_CHROME) return env.HUB_WHATSAPP_CHROME;
    let carpetas = [];
    try {
        carpetas = fs.readdirSync(base).filter((n) => /^chromium-\d+$/.test(n));
    } catch {
        return null;
    }
    carpetas.sort((a, b) => Number(b.split('-')[1]) - Number(a.split('-')[1]));
    for (const c of carpetas) {
        for (const sub of ['chrome-linux64', 'chrome-linux']) {
            const ruta = path.join(base, c, sub, 'chrome');
            if (fs.existsSync(ruta)) return ruta;
        }
    }
    return null;
}

function serializado(x) {
    if (!x) return '';
    return typeof x === 'object' ? x._serialized || '' : String(x);
}

/**
 * Un mensaje de whatsapp-web.js como línea del JSONL, o null si no se guarda.
 * La multimedia no se descarga: sólo se anota el tipo, y su pie si lo tiene.
 */
function linea(m, chat, origen = 'vivo') {
    if (!m || !m.id) return null;
    const chatId = serializado(chat && chat.id) || serializado(m.fromMe ? m.to : m.from);
    // Los estados son las historias de otros, no una conversación con el dueño.
    if (m.isStatus || chatId === 'status@broadcast') return null;
    if (TIPOS_QUE_NO_SON_CONVERSACION.has(m.type)) return null;
    const grupo = Boolean(chat && chat.isGroup) || chatId.endsWith('@g.us');
    const nombreChat = (chat && chat.name) || chatId;
    let autor;
    if (m.fromMe) autor = 'Yo';
    else if (grupo) autor = (m._data && m._data.notifyName) || serializado(m.author) || '';
    else autor = nombreChat;
    return {
        id: serializado(m.id),
        chat: chatId,
        chat_nombre: nombreChat,
        autor,
        autor_id: m.fromMe ? '' : serializado(m.author) || serializado(m.from),
        de_mi: Boolean(m.fromMe),
        texto: m.body || '',
        hora: new Date((m.timestamp || 0) * 1000).toISOString(),
        grupo,
        tipo: m.type || 'chat',
        multimedia: Boolean(m.hasMedia),
        origen,
    };
}

/** La lista de chats para `chats.json`: lo que la pantalla de Fuentes
 * enseña para elegir «Sólo estas». */
function resumenChats(chats) {
    return chats
        .filter((c) => serializado(c.id) !== 'status@broadcast')
        .map((c) => ({
            id: serializado(c.id),
            nombre: c.name || serializado(c.id),
            grupo: Boolean(c.isGroup),
            no_leidos: c.unreadCount || 0,
            ultimo: c.timestamp ? new Date(c.timestamp * 1000).toISOString() : null,
        }));
}

// ── Escribir lo leído: una sola forma para el colector y los lectores ─────────
// Son mensajes privados: carpeta 700 y archivos 600. Antes la escritura estaba
// copiada en `lector/escritor.js` sin los permisos (C-0123).

function asegurarCarpeta(ruta) {
    fs.mkdirSync(ruta, { recursive: true, mode: 0o700 });
    // `mkdir` no cambia los permisos de una carpeta que ya existía. En Windows
    // (por `\\wsl.localhost`) puede no aplicar: no es motivo para no escribir.
    try { fs.chmodSync(ruta, 0o700); } catch { /* sin permisos POSIX */ }
}

function escribirAtomico(ruta, datos) {
    const tmp = `${ruta}.${process.pid}.tmp`;
    fs.writeFileSync(tmp, JSON.stringify(datos, null, 1), { mode: 0o600 });
    fs.renameSync(tmp, ruta);
}

/** Una línea al JSONL. Una sola escritura con O_APPEND: quien lee nunca ve
 * media línea mezclada con otra, y la fuente de Python además ignora una
 * última línea sin salto (aún escribiéndose). */
function anexar(ruta, obj) {
    fs.appendFileSync(ruta, JSON.stringify(obj) + '\n', { mode: 0o600 });
}

module.exports = {
    rutas, buscarChrome, linea, resumenChats, TIPOS_QUE_NO_SON_CONVERSACION,
    asegurarCarpeta, escribirAtomico, anexar,
};
