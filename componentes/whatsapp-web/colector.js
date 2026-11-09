#!/usr/bin/env node
'use strict';
/**
 * Colector PROVISIONAL de WhatsApp para el secretario del hub (decisión 323).
 *
 * Abre el WhatsApp Web real en un Chromium sin ventana (whatsapp-web.js) y
 * vuelca lo que llega a `HUB_HOME/secretario/whatsapp/mensajes.jsonl`. La
 * fuente de Python (`src/hub/secretario/fuentes/whatsapp.py`) lo lee de ahí:
 * el hub no habla con WhatsApp, sólo lee un archivo.
 *
 * 🔴 Sólo lectura, por construcción y no por buena voluntad:
 *   - no se llama nunca a sendMessage, sendSeen, ni a nada que escriba;
 *   - no se abre ningún chat: WhatsApp Web marca leído al abrirlo en pantalla,
 *     y aquí no hay pantalla, sólo su almacén de mensajes;
 *   - al estar listo se anuncia «no disponible» (sendPresenceUnavailable): el
 *     dueño no aparece «en línea» por esto y su teléfono sigue recibiendo los
 *     avisos, que WhatsApp corta mientras hay un cliente «en línea».
 *
 * 🔴 La sesión es una llave de la cuenta entera (regla dura 5): vive en
 * `HUB_SECRETARIO_WHATSAPP` (por omisión ~/.secretos/secretario-whatsapp/,
 * permisos 700), nunca en HUB_HOME ni en el repo.
 *
 * Órdenes:
 *   entrar     pinta el QR, espera a que se escanee, guarda la sesión y sale
 *   escuchar   proceso largo: escucha y vuelca; si la sesión se cae, lo dice y para
 *   comprobar  carga WhatsApp Web con una sesión de usar y tirar, espera al QR y
 *              sale SIN vincular nada: sirve para saber si la librería sigue
 *              funcionando con la versión de hoy de WhatsApp Web
 */

const fs = require('fs');
const os = require('os');
const path = require('path');

const {
    rutas, buscarChrome, linea, resumenChats, asegurarCarpeta, escribirAtomico, anexar,
} = require('./formato');

const R = rutas();
const AL_ARRANCAR = Number.parseInt(process.env.HUB_WHATSAPP_AL_ARRANCAR ?? '20', 10) || 0;
// Un tope de chats en la recogida inicial: cada uno puede pedir historial al
// servidor, y pedir de golpe el de cien chats no es lo que hace una persona.
const CHATS_AL_ARRANCAR = 40;
const LATIDO_MS = 60_000;
const PRESENCIA_MS = 5 * 60_000;
const CHATS_MS = 10 * 60_000;

function log(...partes) {
    console.log(new Date().toISOString(), '·', ...partes);
}

function leerEstado() {
    try {
        return JSON.parse(fs.readFileSync(R.estado, 'utf-8'));
    } catch {
        return {};
    }
}

/** El latido: la fuente de Python distingue «no ha llegado nada» de «el
 * colector está parado» por esto, no por la fecha del JSONL, que en un día
 * tranquilo no se mueve. */
function ponerEstado(estado, detalle = '') {
    escribirAtomico(R.estado, { estado, detalle, latido: new Date().toISOString(), pid: process.pid });
}

const escritos = new Set();
function volcar(obj) {
    if (!obj || escritos.has(obj.id)) return false;
    escritos.add(obj.id);
    anexar(R.mensajes, obj);
    return true;
}

function crearCliente(carpetaSesion) {
    const { Client, LocalAuth } = require('whatsapp-web.js');
    const chrome = buscarChrome();
    if (!chrome) {
        throw new Error('no encuentro Chromium: define HUB_WHATSAPP_CHROME con la ruta del ejecutable '
            + '(o instala el de Playwright: npx playwright install chromium)');
    }
    log('Chromium:', chrome);
    const args = [];
    // En algunos contenedores el sandbox de Chromium no arranca; fuera de
    // ellos se deja puesto, porque esta página ejecuta el código de un tercero.
    if (process.env.HUB_WHATSAPP_SIN_SANDBOX === '1') args.push('--no-sandbox', '--disable-setuid-sandbox');
    return new Client({
        authStrategy: new LocalAuth({ dataPath: carpetaSesion }),
        puppeteer: { executablePath: chrome, headless: true, args },
        webVersionCache: { type: 'local', path: R.cacheWeb },
        // Si el dueño abre WhatsApp Web en otro navegador, gana él: el
        // colector no le quita la sesión (es el valor por omisión, se deja
        // escrito para que nadie lo cambie sin pensarlo).
        takeoverOnConflict: false,
        // Cuántos QR seguidos antes de rendirse en `entrar` (cada uno dura ~20 s).
        qrMaxRetries: 6,
        // Se deja el agente que trae la librería. Con `userAgent: false` (el del
        // navegador) Chromium sin ventana se anuncia «HeadlessChrome» y WhatsApp
        // Web no llega a dar el QR: medido el 1-nov, «auth timeout».
    });
}

async function nombreDe(m, cache) {
    const id = m.fromMe ? m.to : m.from;
    if (cache.has(id)) return cache.get(id);
    try {
        const c = await m.getChat();
        const chat = { id: c.id, name: c.name, isGroup: c.isGroup };
        cache.set(id, chat);
        return chat;
    } catch (e) {
        log('no pude leer el chat de un mensaje:', e.message || e);
        return null;
    }
}

async function guardarChats(cliente) {
    try {
        const chats = await cliente.getChats();
        escribirAtomico(R.chats, resumenChats(chats));
        return chats;
    } catch (e) {
        log('no pude leer la lista de chats:', e.message || e);
        return [];
    }
}

/**
 * Lo que llegó mientras el colector estaba parado. `fetchMessages` lee el
 * almacén de WhatsApp Web y, si faltan, pide más con `loadEarlierMsgs` (lo
 * mismo que subir en un chat); ninguno de los dos llama a `sendSeen` —está
 * comprobado en el código de whatsapp-web.js 1.34.7, `Chat.fetchMessages`—,
 * así que no marca nada como leído.
 */
async function recogerAlArrancar(cliente, chats, latidoPrevio, cache) {
    if (AL_ARRANCAR <= 0) return;
    const desde = latidoPrevio ? Date.parse(latidoPrevio) / 1000 : 0;
    const candidatos = chats
        .filter((c) => c.unreadCount > 0 || (desde && c.timestamp > desde))
        .filter((c) => c.id && c.id._serialized !== 'status@broadcast')
        .slice(0, CHATS_AL_ARRANCAR);
    let n = 0;
    for (const c of candidatos) {
        try {
            const msgs = await c.fetchMessages({ limit: AL_ARRANCAR });
            cache.set(c.id._serialized, { id: c.id, name: c.name, isGroup: c.isGroup });
            for (const m of msgs) {
                if (desde && m.timestamp <= desde && !(c.unreadCount > 0)) continue;
                if (volcar(linea(m, { id: c.id, name: c.name, isGroup: c.isGroup }, 'arranque'))) n++;
            }
        } catch (e) {
            log(`no pude recoger «${c.name}»:`, e.message || e);
        }
    }
    log(`recogida al arrancar: ${n} mensajes de ${candidatos.length} chats`);
}

function pintarQR(qr) {
    require('qrcode-terminal').generate(qr, { small: true });
}

// ── entrar ──────────────────────────────────────────────────────────────────

async function entrar() {
    asegurarCarpeta(R.secretos);
    asegurarCarpeta(R.datos);
    const cliente = crearCliente(R.secretos);
    cliente.on('qr', (qr) => {
        ponerEstado('esperando-qr', 'corre: node colector.js entrar');
        log('Escanea este código con WhatsApp → Dispositivos vinculados → Vincular un dispositivo:');
        pintarQR(qr);
    });
    cliente.on('authenticated', () => log('código aceptado; cargando los chats…'));
    cliente.on('auth_failure', (m) => {
        log('WhatsApp rechazó la sesión:', m);
        process.exit(2);
    });
    cliente.on('disconnected', (motivo) => {
        log('desconectado sin terminar de entrar:', motivo);
        process.exit(2);
    });
    cliente.on('ready', async () => {
        await cliente.sendPresenceUnavailable().catch(() => {});
        const chats = await guardarChats(cliente);
        // `LocalAuth` crea la carpeta de la sesión antes de escanear nada: que
        // exista no dice que haya cuenta vinculada. Esto sí.
        ponerEstado('vinculada', 'falta arrancar: node colector.js escuchar');
        log(`Dentro. ${chats.length} chats. La sesión está en ${R.secretos}.`);
        log('Ahora: node colector.js escuchar (o déjalo en una ventana de tmux).');
        await cliente.destroy().catch(() => {});
        process.exit(0);
    });
    await cliente.initialize();
}

// ── comprobar ───────────────────────────────────────────────────────────────

async function comprobar() {
    // Sesión de usar y tirar: esta orden jamás toca la de verdad, y como sale
    // al primer QR no hay forma de que se vincule nada.
    const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'hub-whatsapp-comprobar-'));
    const cliente = crearCliente(tmp);
    let cerrando = false;
    const cerrar = async (codigo) => {
        cerrando = true;
        await cliente.destroy().catch(() => {});
        fs.rmSync(tmp, { recursive: true, force: true });
        process.exit(codigo);
    };
    const limite = setTimeout(() => {
        log('en 120 s WhatsApp Web no llegó a pedir el QR: algo no funciona');
        cerrar(1);
    }, 120_000);
    cliente.on('qr', async (qr) => {
        clearTimeout(limite);
        const version = await cliente.getWWebVersion().catch(() => '?');
        log(`WhatsApp Web ${version} cargó y emitió un QR (${qr.length} caracteres). No se vincula nada; cerrando.`);
        cerrar(0);
    });
    // Cerrar el navegador a mitad de `initialize` lo hace fallar: ese fallo
    // es el cierre que pedimos, no un error que contar.
    await cliente.initialize().catch(async (e) => {
        if (cerrando) return new Promise(() => {});
        clearTimeout(limite);
        log('falló:', e.message || e);
        await cerrar(1);
    });
}

// ── escuchar ────────────────────────────────────────────────────────────────

function haySesion() {
    return fs.existsSync(path.join(R.secretos, 'session'));
}

async function escuchar() {
    if (!haySesion()) {
        asegurarCarpeta(R.datos);
        ponerEstado('sin-sesion', 'corre: node colector.js entrar');
        log(`no hay sesión en ${R.secretos}: primero node colector.js entrar`);
        process.exit(2);
    }
    asegurarCarpeta(R.datos);
    const latidoPrevio = leerEstado().latido;
    let espera = 30_000;
    // El bucle no muere por un fallo (regla dura 2): se reintenta con espera
    // creciente. Sólo para cuando WhatsApp cierra la sesión, porque eso no se
    // arregla reintentando y reintentar a ciegas es una señal mala más.
    for (;;) {
        const fin = await unaVuelta(latidoPrevio).catch((e) => ({ motivo: `error: ${e.message || e}` }));
        if (fin.parar) {
            ponerEstado(fin.estado, fin.motivo);
            log(fin.motivo);
            process.exit(2);
        }
        ponerEstado('reintentando', fin.motivo);
        log(`${fin.motivo}; reintento en ${espera / 1000} s`);
        await new Promise((r) => setTimeout(r, espera));
        espera = Math.min(espera * 2, 10 * 60_000);
    }
}

function unaVuelta(latidoPrevio) {
    return new Promise((resolve, reject) => {
        const cliente = crearCliente(R.secretos);
        const cache = new Map();
        let latido = null;
        let listaChats = null;
        let presencia = null;
        const terminar = async (fin) => {
            clearInterval(latido);
            clearInterval(presencia);
            clearInterval(listaChats);
            await cliente.destroy().catch(() => {});
            resolve(fin);
        };
        ponerEstado('arrancando');
        cliente.on('qr', () => {
            // Con sesión guardada no debería pedir QR: si lo pide, la sesión
            // ya no vale. Un proceso largo no se queda esperando a que alguien
            // escanee una pantalla que nadie mira.
            terminar({ parar: true, estado: 'sin-sesion',
                motivo: 'WhatsApp pide escanear otra vez: la sesión ya no vale (node colector.js entrar)' });
        });
        cliente.on('auth_failure', (m) => terminar({ parar: true, estado: 'sin-sesion', motivo: `WhatsApp rechazó la sesión: ${m}` }));
        cliente.on('disconnected', (motivo) => {
            if (motivo === 'LOGOUT') {
                terminar({ parar: true, estado: 'sesion-cerrada',
                    motivo: 'WhatsApp cerró la sesión (desvinculado desde el teléfono o por WhatsApp): vuelve a entrar' });
            } else {
                terminar({ motivo: `desconectado (${motivo})` });
            }
        });
        cliente.on('ready', async () => {
            await cliente.sendPresenceUnavailable().catch((e) => log('no pude anunciarme no disponible:', e.message || e));
            ponerEstado('escuchando');
            latido = setInterval(() => ponerEstado('escuchando'), LATIDO_MS);
            // Mientras WhatsApp crea que esta sesión está «en línea», el teléfono
            // del dueño deja de recibir notificaciones. Una vez al arrancar no
            // basta: se repite cada 5 minutos.
            presencia = setInterval(() => cliente.sendPresenceUnavailable().catch(() => {}), PRESENCIA_MS);
            const chats = await guardarChats(cliente);
            listaChats = setInterval(() => guardarChats(cliente), CHATS_MS);
            log(`escuchando; ${chats.length} chats`);
            await recogerAlArrancar(cliente, chats, latidoPrevio, cache);
        });
        // `message_create` y no sólo `message`: `message` no trae lo que el
        // dueño escribe desde el teléfono, y el secretario saca de ahí lo que
        // dijo que haría (los compromisos, decisión 302), igual que la fuente
        // de Telegram lee los suyos como «Yo». Es el mismo almacén local: no
        // pide nada al servidor.
        cliente.on('message_create', async (m) => {
            try {
                const chat = await nombreDe(m, cache);
                volcar(linea(m, chat));
            } catch (e) {
                log('no pude guardar un mensaje:', e.message || e);
            }
        });
        cliente.initialize().catch(reject);
    });
}

// ── arranque ────────────────────────────────────────────────────────────────

const ORDENES = { entrar, escuchar, comprobar };
const orden = process.argv[2];
if (!ORDENES[orden]) {
    console.log('uso: node colector.js entrar | escuchar | comprobar');
    process.exit(64);
}
for (const senal of ['SIGINT', 'SIGTERM']) {
    process.on(senal, () => {
        log('parado a mano');
        if (orden === 'escuchar') {
            try { ponerEstado('parado', 'parado a mano'); } catch { /* sin carpeta aún */ }
        }
        process.exit(0);
    });
}
ORDENES[orden]().catch((e) => {
    log('falló:', e.stack || e);
    process.exit(1);
});
