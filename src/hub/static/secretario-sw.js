/* El service worker del secretario: sólo avisos (decisión 311).
 *
 * 🔴 Sin `fetch` a propósito. El hub no tenía service worker para no cachear
 * (decisión 168): enseñar una pantalla vieja como si fuera de ahora es la
 * forma de mentir que tiene prohibida. Éste no intercepta ninguna petición;
 * existe sólo porque Web Push no llega sin él.
 *
 * El mensaje llega en el formato declarativo de Apple (`notification` con
 * `title`, `body` y `navigate`) más lo propio (`secretario`). En iOS 18.4+
 * el sistema lo enseña aunque esto falle; en los demás lo enseña esto, y
 * 🔴 SIEMPRE enseña algo: en iOS un push sin notificación hace que Safari
 * retire el permiso.
 */
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (e) => e.waitUntil(self.clients.claim()));

function leer(e) {
  let d;
  try { d = e.data ? e.data.json() : {}; } catch (err) {
    return { notification: { title: 'Secretario', body: e.data ? e.data.text() : '' } };
  }
  // `null`, un número o una lista son JSON válido y no son un aviso: con
  // `null`, `d.notification` reventaba y no se enseñaba nada (LLA-13).
  return d && typeof d === 'object' && !Array.isArray(d) ? d : {};
}

self.addEventListener('push', (e) => {
  const d = leer(e);
  const n = d.notification || {};
  const s = d.secretario || {};
  const opciones = {
    body: n.body || '',
    icon: '/static/icono-192.png',
    badge: '/static/icono-192.png',
    data: { url: n.navigate || '/secretario', solicitud: s.solicitud || null, compromiso: s.compromiso || null },
  };
  if (s.solicitud) {
    // Una por solicitud: si se repite, sustituye a la anterior en vez de apilarse.
    opciones.tag = `solicitud-${s.solicitud}`;
    opciones.requireInteraction = true;
    // Lo que no tiene vuelta atrás llega sin botones: se decide con la app abierta.
    if (s.decidir) opciones.actions = [{ action: 'aprobar', title: 'Aprobar' }, { action: 'rechazar', title: 'Rechazar' }];
  } else if (s.compromiso) {
    // Un recordatorio se cierra o se aplaza sin abrir la app (C-0407): de 20,
    // 11 seguían abiertos. Son los gestos de Pendientes («Hecho» tampoco
    // pregunta allí). Sin `tag` a propósito: no cambia cómo suena, y el de
    // «En 1 h» no debe llegar mudo sustituyendo a otro.
    opciones.actions = [{ action: 'hecho', title: 'Hecho' }, { action: 'aplazar', title: 'En 1 h' }];
  }
  e.waitUntil(self.registration.showNotification(n.title || 'Secretario', opciones));
});

async function abrir(url) {
  const ventanas = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
  for (const v of ventanas) {
    if (new URL(v.url).pathname.startsWith('/secretario') && 'focus' in v) {
      // La app vive en `/secretario` y este service worker en `/secretario/`:
      // no la controla, y `navigate` rechaza siempre. Se le pide a la página
      // que vaya ella (C-0158); antes el aviso sólo la traía al frente.
      try { await v.navigate(url); } catch (err) { v.postMessage({ tipo: 'abrir', url }); }
      return v.focus();
    }
  }
  return self.clients.openWindow(url);
}

// Lo que se contesta desde el propio aviso: un POST con JSON a la API del hub
// (el navegador pone el `Origin`, que el hub exige en todo POST) y otro aviso
// con lo que pasó, sólo cuando el hub lo confirma.
async function contestar(ruta, cuerpo, bien, tag, url) {
  try {
    const r = await fetch(ruta, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(cuerpo),
    });
    const d = await r.json();
    const texto = d.ok ? bien : `No se pudo: ${d.error || r.status}`;
    await self.registration.showNotification('Secretario', { body: texto, tag, icon: '/static/icono-192.png',
                                                             data: { url } });
  } catch (err) {
    // Sin red o sin sesión (fuera de casa sin Acceso): se abre la app para hacerlo ahí.
    await abrir(url);
  }
}

const decidir = (solicitud, decision, url) => contestar(
  `/api/secretario/solicitud/${solicitud}`, { decision },
  decision === 'aprobar' ? 'Aprobado: lo hace en unos segundos.' : 'Rechazado.', `decision-${solicitud}`, url);

const aplazarOCerrar = (compromiso, accion, url) => contestar(
  `/api/secretario/compromiso/${compromiso}`, { accion },
  accion === 'hecho' ? 'Hecho.' : 'Te lo vuelvo a recordar en una hora.', `compromiso-${compromiso}`, url);

self.addEventListener('notificationclick', (e) => {
  e.notification.close();
  const { url, solicitud, compromiso } = e.notification.data || {};
  if (solicitud && (e.action === 'aprobar' || e.action === 'rechazar')) {
    e.waitUntil(decidir(solicitud, e.action, url || '/secretario?p=pendientes'));
    return;
  }
  if (compromiso && (e.action === 'hecho' || e.action === 'aplazar')) {
    e.waitUntil(aplazarOCerrar(compromiso, e.action, url || '/secretario?p=pendientes'));
    return;
  }
  e.waitUntil(abrir(url || '/secretario'));
});

// El navegador renovó la suscripción por su cuenta: se da de alta la nueva.
// Con la dirección vieja el hub le deja el nombre que tenía y quita la fila
// vieja, y si el dueño había quitado ese aparato, no lo vuelve a apuntar
// (C-0232). «renovada» queda sólo para cuando el hub no la reconoce.
self.addEventListener('pushsubscriptionchange', (e) => {
  const vieja = e.oldSubscription;
  const clave = vieja && vieja.options && vieja.options.applicationServerKey;
  if (!clave) return;
  e.waitUntil(self.registration.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: clave })
    .then((sub) => fetch('/api/secretario/push/alta', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ...sub.toJSON(), aparato: 'renovada', motivo: 'renovar', anterior: vieja.endpoint || '' }),
    })));
});
