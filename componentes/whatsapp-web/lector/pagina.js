'use strict';
/**
 * El lector que corre DENTRO de WhatsApp Web (decisión 331): en tu Chrome, como
 * parte de la extensión, o en la app de escritorio, inyectado por
 * `escritorio.js`. Es el mismo archivo en los dos casos, para que lo que se
 * compara sea la forma de llegar y no el lector.
 *
 * Escucha la colección de mensajes que la propia página ya tiene en memoria
 * (`WAWebCollections`, la misma que usa whatsapp-web.js): ve todos los chats
 * sin abrirlos. **Sólo lee**: no llama a nada que envíe, marque leído o cambie
 * la presencia. Cada mensaje nuevo sale por `window.__hubEnviar(tipo, datos)`,
 * que pone quien lo inyecta, con la forma de un mensaje de whatsapp-web.js
 * para que `formato.linea` lo convierta igual que al colector.
 */
(function () {
    if (window.__lectorHub) return;
    window.__lectorHub = { desde: Date.now(), mensajes: 0 };

    const CHATS_CADA_MS = 10 * 60 * 1000;

    function ser(x) {
        if (!x) return '';
        if (typeof x === 'string') return x;
        return x._serialized || (x.toString ? String(x) : '');
    }

    function chatDe(Chat, remoto) {
        try {
            const c = Chat.get(remoto);
            if (!c) return { id: { _serialized: ser(remoto) } };
            return {
                id: { _serialized: ser(c.id) },
                name: c.name || c.formattedTitle || (c.contact && (c.contact.name || c.contact.pushname)) || '',
                isGroup: Boolean(c.isGroup) || ser(c.id).endsWith('@g.us'),
                unreadCount: c.unreadCount || 0,
                timestamp: c.t || 0,
            };
        } catch (e) {
            return { id: { _serialized: ser(remoto) } };
        }
    }

    function mensaje(m) {
        const id = m.id || {};
        return {
            id: { _serialized: ser(id) },
            fromMe: Boolean(id.fromMe),
            from: { _serialized: ser(m.from) },
            to: { _serialized: ser(m.to) },
            author: m.author ? { _serialized: ser(m.author) } : null,
            type: m.type || 'chat',
            body: m.type === 'chat' ? (m.body || '') : (m.caption || ''),
            timestamp: m.t || Math.floor(Date.now() / 1000),
            hasMedia: Boolean(m.isMedia || m.mediaData || (m.type && m.type !== 'chat' && m.directPath)),
            isStatus: ser(id.remote) === 'status@broadcast',
            _data: { notifyName: m.notifyName || (m.senderObj && m.senderObj.pushname) || '' },
            remoto: ser(id.remote),
        };
    }

    function enviar(tipo, datos) {
        try { window.__hubEnviar(tipo, datos); } catch (e) { /* sin puente: nada que hacer */ }
    }

    function chats(Chat) {
        try {
            const todos = (Chat.getModelsArray ? Chat.getModelsArray() : Chat.models || []);
            // Recién abierta la página la colección aún está vacía (medido el
            // 2-nov): una lista vacía no pisa la buena, y se reintenta antes.
            if (!todos.length) return false;
            enviar('chats', todos.map((c) => chatDe(Chat, c.id)));
            return true;
        } catch (e) {
            enviar('error', 'chats: ' + String(e).slice(0, 200));
        }
    }

    function empezar() {
        let col;
        try {
            col = window.require('WAWebCollections');
        } catch (e) {
            col = null;
        }
        if (!col || !col.Msg || !col.Chat || typeof col.Msg.on !== 'function') {
            setTimeout(empezar, 3000);   // aún cargando, o sin sesión: se reintenta
            return;
        }
        const { Msg, Chat } = col;
        Msg.on('add', (m) => {
            // Sólo lo que LLEGA ahora: abrir un chat también «añade» su historial.
            if (!m || !m.isNewMsg) return;
            try {
                const datos = mensaje(m);
                datos.chat = chatDe(Chat, (m.id || {}).remote);
                window.__lectorHub.mensajes += 1;
                enviar('mensaje', datos);
            } catch (e) {
                enviar('error', 'mensaje: ' + String(e).slice(0, 200));
            }
        });
        enviar('listo', { desde: window.__lectorHub.desde });
        const primera = () => { if (!chats(Chat)) setTimeout(primera, 15000); };
        primera();
        setInterval(() => chats(Chat), CHATS_CADA_MS);
    }

    empezar();
})();
