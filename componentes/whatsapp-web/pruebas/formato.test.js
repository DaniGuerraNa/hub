'use strict';
// Se ejecuta con `npm test` (y lo lanza la suite de Python,
// `tests/test_secretario_whatsapp.py`). Sin navegador ni WhatsApp: lo que
// decide el colector sobre la forma de cada mensaje.

const test = require('node:test');
const assert = require('node:assert');
const fs = require('fs');
const os = require('os');
const path = require('path');

const { rutas, buscarChrome, linea, resumenChats } = require('../formato');

const PRIVADO = { id: { _serialized: '5215550001@c.us' }, name: 'Ana', isGroup: false };
const GRUPO = { id: { _serialized: '1203630@g.us' }, name: 'Equipo', isGroup: true };

function mensaje(extra = {}) {
    return {
        id: { _serialized: 'false_5215550001@c.us_ABC' },
        from: '5215550001@c.us', to: '5215559999@c.us',
        fromMe: false, body: '¿Me mandas el reporte?', type: 'chat',
        timestamp: 1793520000, hasMedia: false, isStatus: false, _data: {},
        ...extra,
    };
}

test('un mensaje de un chat privado lleva el nombre del chat como autor y la hora en UTC', () => {
    const l = linea(mensaje(), PRIVADO);
    assert.strictEqual(l.autor, 'Ana');
    assert.strictEqual(l.chat_nombre, 'Ana');
    assert.strictEqual(l.grupo, false);
    assert.strictEqual(l.hora, '2026-11-01T08:00:00.000Z');
    assert.strictEqual(l.texto, '¿Me mandas el reporte?');
});

test('en un grupo el autor es quien escribió y lo del dueño es «Yo»', () => {
    const l = linea(mensaje({ author: '5215550002@c.us', _data: { notifyName: 'Luis' } }), GRUPO);
    assert.strictEqual(l.autor, 'Luis');
    assert.strictEqual(l.grupo, true);
    assert.strictEqual(linea(mensaje({ fromMe: true }), GRUPO).autor, 'Yo');
});

test('la multimedia no se descarga: queda el tipo y el pie', () => {
    const l = linea(mensaje({ type: 'image', hasMedia: true, body: 'la factura' }), PRIVADO);
    assert.strictEqual(l.tipo, 'image');
    assert.strictEqual(l.multimedia, true);
    assert.strictEqual(l.texto, 'la factura');
});

test('estados, reacciones y avisos del sistema no se guardan', () => {
    assert.strictEqual(linea(mensaje({ isStatus: true }), PRIVADO), null);
    assert.strictEqual(linea(mensaje({ type: 'reaction' }), PRIVADO), null);
    assert.strictEqual(linea(mensaje({ type: 'e2e_notification' }), PRIVADO), null);
    assert.strictEqual(linea(mensaje({ type: 'revoked' }), PRIVADO), null);
});

test('la lista de chats no lleva los estados', () => {
    const r = resumenChats([PRIVADO, { id: { _serialized: 'status@broadcast' }, name: 'Estados' }]);
    assert.deepStrictEqual(r.map((c) => c.nombre), ['Ana']);
});

test('las rutas salen de HUB_HOME y de HUB_SECRETARIO_WHATSAPP', () => {
    const r = rutas({ HUB_HOME: '/x/hub', HUB_SECRETARIO_WHATSAPP: '/y/sec' });
    assert.strictEqual(r.mensajes, '/x/hub/secretario/whatsapp/mensajes.jsonl');
    assert.strictEqual(r.secretos, '/y/sec');
});

test('se usa el Chromium de Playwright de número más alto, salvo que la variable diga otro', () => {
    const base = fs.mkdtempSync(path.join(os.tmpdir(), 'pw-'));
    for (const n of ['chromium-900', 'chromium-1200', 'chromium-1100']) {
        fs.mkdirSync(path.join(base, n, 'chrome-linux64'), { recursive: true });
        fs.writeFileSync(path.join(base, n, 'chrome-linux64', 'chrome'), '');
    }
    assert.strictEqual(buscarChrome({}, base), path.join(base, 'chromium-1200', 'chrome-linux64', 'chrome'));
    assert.strictEqual(buscarChrome({ HUB_WHATSAPP_CHROME: '/otro/chrome' }, base), '/otro/chrome');
    assert.strictEqual(buscarChrome({}, path.join(base, 'no-existe')), null);
    fs.rmSync(base, { recursive: true, force: true });
});

// C-0123: el lector de la extensión y el de escritorio copiaban la escritura
// del colector sin sus permisos, en archivos con mensajes privados.
test('lo que escribe el lector de la página queda sólo para su dueño, como lo del colector', () => {
    const { crear } = require('../lector/escritor');
    const base = fs.mkdtempSync(path.join(os.tmpdir(), 'escritor-'));
    const dir = path.join(base, 'whatsapp');
    const e = crear(dir, 'extension');
    e.recibir('listo');
    e.recibir('chats', [{ id: { _serialized: '1@c.us' }, name: 'Ana', isGroup: false }]);
    e.recibir('mensaje', {
        id: { _serialized: 'false_1@c.us_A' }, from: { _serialized: '1@c.us' },
        type: 'chat', body: 'hola', t: 1793520000, chat: { id: '1@c.us', name: 'Ana', isGroup: false },
    });
    const permisos = (p) => (fs.statSync(p).mode & 0o777).toString(8);
    assert.strictEqual(permisos(dir), '700');
    for (const r of Object.values(e.rutas)) assert.strictEqual(permisos(r), '600', r);
    fs.rmSync(base, { recursive: true, force: true });
});
