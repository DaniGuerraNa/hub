'use strict';
// El lector de la página y sus dos caminos (decisión 331), ejecutados: el
// lector en una ventana falsa, el anfitrión de la extensión por su stdin con
// el formato de Chrome, y `escritorio.js` contra un Chromium de verdad con
// una página que imita a WhatsApp Web. Sin cuenta de WhatsApp.

const test = require('node:test');
const assert = require('node:assert');
const fs = require('fs');
const os = require('os');
const path = require('path');
const http = require('http');
const vm = require('vm');
const { spawn } = require('child_process');

const { buscarChrome } = require('../formato');
const { crear } = require('../lector/escritor');

const LECTOR = path.join(__dirname, '..', 'lector');
const PAGINA = fs.readFileSync(path.join(LECTOR, 'pagina.js'), 'utf-8');

// Lo mínimo de `WAWebCollections` que usa el lector, en texto: se evalúa igual
// en la ventana falsa de vm y en la página que carga Chromium.
const FALSO_WA = `
(function () {
  const oyentes = [];
  const chats = {
    '5215550001@c.us': { id: { _serialized: '5215550001@c.us' }, name: 'Ana', isGroup: false, unreadCount: 2, t: 1793520000 },
    '1203630@g.us': { id: { _serialized: '1203630@g.us' }, name: 'Equipo', isGroup: true, unreadCount: 0, t: 1793520100 },
  };
  const Msg = { on: (ev, f) => { if (ev === 'add') oyentes.push(f); } };
  const Chat = { get: (id) => chats[id._serialized || id], getModelsArray: () => Object.values(chats) };
  window.require = (m) => { if (m !== 'WAWebCollections') throw new Error('módulo ' + m); return { Msg, Chat }; };
  window.__emitir = (m) => oyentes.forEach((f) => f(m));
})();`;

const NUEVO = {
    id: { fromMe: false, remote: { _serialized: '1203630@g.us' }, _serialized: 'false_1203630@g.us_XYZ' },
    from: { _serialized: '1203630@g.us' }, to: { _serialized: '5215559999@c.us' },
    author: { _serialized: '5215550002@c.us' }, notifyName: 'Luis',
    type: 'chat', body: 'Mañana a las 10 la revisión', t: 1793520200, isNewMsg: true,
};

test('el lector sólo pasa lo que llega ahora, con la forma que entiende formato.linea', () => {
    const enviados = [];
    const ventana = { setTimeout, setInterval: () => 0, Date };
    ventana.window = ventana;
    ventana.__hubEnviar = (tipo, datos) => enviados.push({ tipo, datos });
    vm.createContext(ventana);
    vm.runInContext(FALSO_WA + PAGINA, ventana);
    ventana.__emitir({ ...NUEVO, isNewMsg: false });   // historial al abrir un chat
    ventana.__emitir(NUEVO);
    assert.deepStrictEqual(enviados.map((e) => e.tipo), ['listo', 'chats', 'mensaje']);
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'lector-'));
    const l = crear(dir, 'extension').recibir('mensaje', JSON.parse(JSON.stringify(enviados[2].datos)));
    assert.strictEqual(l.autor, 'Luis');
    assert.strictEqual(l.chat_nombre, 'Equipo');
    assert.strictEqual(l.grupo, true);
    assert.strictEqual(l.texto, 'Mañana a las 10 la revisión');
    assert.strictEqual(l.origen, 'extension');
    assert.strictEqual(enviados[1].datos.length, 2);
});

test('sin sesión el lector espera y no envía nada', () => {
    const enviados = [];
    const esperas = [];
    const ventana = { setTimeout: (f, ms) => esperas.push(ms), setInterval: () => 0, Date };
    ventana.window = ventana;
    ventana.require = () => { throw new Error('aún no'); };
    ventana.__hubEnviar = (tipo) => enviados.push(tipo);
    vm.createContext(ventana);
    vm.runInContext(PAGINA, ventana);
    assert.deepStrictEqual(enviados, []);
    assert.deepStrictEqual(esperas, [3000]);
});

function trama(obj) {
    const cuerpo = Buffer.from(JSON.stringify(obj));
    const cabeza = Buffer.alloc(4);
    cabeza.writeUInt32LE(cuerpo.length, 0);
    return Buffer.concat([cabeza, cuerpo]);
}

test('el anfitrión de la extensión escribe lo que Chrome le pasa y dice parado al cerrarse', async () => {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'anfitrion-'));
    for (const f of ['anfitrion.js', 'escritor.js']) fs.copyFileSync(path.join(LECTOR, f), path.join(dir, f));
    fs.copyFileSync(path.join(__dirname, '..', 'formato.js'), path.join(dir, 'formato.js'));
    const destino = path.join(dir, 'datos');
    fs.writeFileSync(path.join(dir, 'config.json'), JSON.stringify({ destino }));
    const p = spawn(process.execPath, [path.join(dir, 'anfitrion.js')]);
    const datos = { ...NUEVO, id: { _serialized: NUEVO.id._serialized }, fromMe: false, _data: { notifyName: 'Luis' },
        chat: { id: { _serialized: '1203630@g.us' }, name: 'Equipo', isGroup: true } };
    // Dos mensajes en un solo trozo y uno partido en dos: como llegan por una tubería.
    const todo = Buffer.concat([trama({ tipo: 'listo', datos: {} }), trama({ tipo: 'mensaje', datos })]);
    p.stdin.write(todo.subarray(0, 7));
    p.stdin.write(todo.subarray(7));
    await new Promise((r) => setTimeout(r, 300));
    p.stdin.end();
    await new Promise((r) => p.on('exit', r));
    const [l] = fs.readFileSync(path.join(destino, 'mensajes.jsonl'), 'utf-8').trim().split('\n').map(JSON.parse);
    assert.strictEqual(l.id, 'false_1203630@g.us_XYZ');
    assert.strictEqual(l.origen, 'extension');
    assert.strictEqual(JSON.parse(fs.readFileSync(path.join(destino, 'estado.json'))).estado, 'parado');
});

test('escritorio.js se engancha por CDP a la página, inyecta el lector y escribe lo que llega', { timeout: 60000 }, async (t) => {
    const chrome = buscarChrome();
    if (!chrome) return t.skip('sin Chromium de Playwright');
    const servidor = http.createServer((req, res) => {
        res.setHeader('Content-Type', 'text/html; charset=utf-8');
        res.end(`<!doctype html><title>wa falso</title><script>${FALSO_WA}
          setInterval(() => window.__emitir(${JSON.stringify(NUEVO)}), 300);</script>`);
    });
    await new Promise((r) => servidor.listen(0, '127.0.0.1', r));
    const url = `http://127.0.0.1:${servidor.address().port}/`;
    const perfil = fs.mkdtempSync(path.join(os.tmpdir(), 'cdp-'));
    const puerto = 9400 + Math.floor(Math.random() * 400);
    const nav = spawn(chrome, ['--headless=new', '--no-sandbox', `--remote-debugging-port=${puerto}`,
        `--user-data-dir=${perfil}`, url], { stdio: 'ignore' });
    const destino = path.join(perfil, 'datos');
    const lector = spawn(process.execPath, [path.join(LECTOR, 'escritorio.js')], {
        env: { ...process.env, HUB_WA_CDP: String(puerto), HUB_WA_URL: url, HUB_WA_DESTINO: destino, HUB_WA_VUELTA_MS: '500' }, stdio: 'ignore',
    });
    try {
        const ruta = path.join(destino, 'mensajes.jsonl');
        for (let i = 0; i < 100 && !fs.existsSync(ruta); i++) await new Promise((r) => setTimeout(r, 200));
        const l = JSON.parse(fs.readFileSync(ruta, 'utf-8').split('\n')[0]);
        assert.strictEqual(l.origen, 'escritorio');
        assert.strictEqual(l.autor, 'Luis');
        assert.ok(JSON.parse(fs.readFileSync(path.join(destino, 'chats.json'))).length === 2);
    } finally {
        lector.kill();
        nav.kill();
        servidor.close();
    }
});

test('la extensión, cargada en Chromium, lleva lo que ve en WhatsApp Web hasta el anfitrión', { timeout: 90000 }, async (t) => {
    const chrome = buscarChrome();
    if (!chrome) return t.skip('sin Chromium de Playwright');
    const base = fs.mkdtempSync(path.join(os.tmpdir(), 'ext-'));
    // La extensión como la deja instalar.sh: sus archivos y el lector al lado.
    const ext = path.join(base, 'extension');
    fs.cpSync(path.join(LECTOR, 'extension'), ext, { recursive: true });
    fs.copyFileSync(path.join(LECTOR, 'pagina.js'), path.join(ext, 'pagina.js'));
    const id = fs.readFileSync(path.join(ext, 'ID'), 'utf-8').trim();
    // El anfitrión, registrado en el perfil (Chromium en Linux también mira ahí).
    const anf = path.join(base, 'anfitrion');
    fs.mkdirSync(anf);
    for (const f of ['anfitrion.js', 'escritor.js']) fs.copyFileSync(path.join(LECTOR, f), path.join(anf, f));
    fs.copyFileSync(path.join(__dirname, '..', 'formato.js'), path.join(anf, 'formato.js'));
    const destino = path.join(base, 'datos');
    fs.writeFileSync(path.join(anf, 'config.json'), JSON.stringify({ destino }));
    fs.writeFileSync(path.join(anf, 'anfitrion.sh'), `#!/bin/sh\nexec "${process.execPath}" "${anf}/anfitrion.js"\n`, { mode: 0o755 });
    const perfil = path.join(base, 'perfil');
    fs.mkdirSync(path.join(perfil, 'NativeMessagingHosts'), { recursive: true });
    fs.writeFileSync(path.join(perfil, 'NativeMessagingHosts', 'com.hub.whatsapp_lector.json'), JSON.stringify({
        name: 'com.hub.whatsapp_lector', description: 'prueba', path: path.join(anf, 'anfitrion.sh'), type: 'stdio',
        allowed_origins: [`chrome-extension://${id}/`],
    }));
    const puerto = 9800 + Math.floor(Math.random() * 150);
    const nav = spawn(chrome, ['--headless=new', '--no-sandbox', `--remote-debugging-port=${puerto}`,
        `--user-data-dir=${perfil}`, `--disable-extensions-except=${ext}`, `--load-extension=${ext}`, 'about:blank'],
    { stdio: 'ignore' });
    try {
        let pagina = null;
        for (let i = 0; i < 50 && !pagina; i++) {
            await new Promise((r) => setTimeout(r, 200));
            try {
                const lista = await (await fetch(`http://127.0.0.1:${puerto}/json/list`)).json();
                pagina = lista.find((x) => x.type === 'page');
            } catch { /* aún arrancando */ }
        }
        // web.whatsapp.com servido por CDP con la página falsa: la extensión
        // decide por la URL, y la URL es la de verdad.
        const ws = new WebSocket(pagina.webSocketDebuggerUrl);
        await new Promise((r) => { ws.onopen = r; });
        let n = 0;
        const enviar = (method, params = {}) => ws.send(JSON.stringify({ id: ++n, method, params }));
        const html = `<!doctype html><title>wa falso</title><script>${FALSO_WA}
          setInterval(() => window.__emitir(${JSON.stringify(NUEVO)}), 300);</script>`;
        ws.onmessage = (ev) => {
            const m = JSON.parse(ev.data);
            if (m.method === 'Fetch.requestPaused') {
                enviar('Fetch.fulfillRequest', { requestId: m.params.requestId, responseCode: 200,
                    responseHeaders: [{ name: 'Content-Type', value: 'text/html; charset=utf-8' }],
                    body: Buffer.from(html).toString('base64') });
            }
        };
        enviar('Fetch.enable', { patterns: [{ urlPattern: 'https://web.whatsapp.com/*' }] });
        enviar('Page.navigate', { url: 'https://web.whatsapp.com/' });
        const ruta = path.join(destino, 'mensajes.jsonl');
        for (let i = 0; i < 150 && !fs.existsSync(ruta); i++) await new Promise((r) => setTimeout(r, 200));
        const l = JSON.parse(fs.readFileSync(ruta, 'utf-8').split('\n')[0]);
        assert.strictEqual(l.origen, 'extension');
        assert.strictEqual(l.chat_nombre, 'Equipo');
        ws.close();
    } finally {
        nav.kill();
    }
});
