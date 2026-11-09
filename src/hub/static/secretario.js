/* La app del secretario: lo que no es la conversación (decisiones 311, 312 y
 * 316). Instalarla como app, activar los avisos en este aparato, el teclado
 * del iPhone, el filtro de notas, el número de pendientes en el icono y, con
 * la app abierta, ir al enlace del aviso que se toca (C-0158). La
 * conversación es `chat-secretario.js` (C-0160).
 */
// El alcance del service worker de avisos: sólo esta app.
const PUSH = '/secretario/';
// La oferta de instalar del navegador (decisión 316). Arriba porque el arranque
// de abajo ya la lee.
let ofertaInstalar = null;
window.addEventListener('beforeinstallprompt', (e) => { e.preventDefault(); ofertaInstalar = e; pintarInstalar(); });
window.addEventListener('appinstalled', () => { ofertaInstalar = null; pintarInstalar(); });

// Tocar un aviso con la app ya abierta: el service worker no la controla y
// pide desde aquí ir al enlace (C-0158). Sólo a una ruta de este mismo hub:
// si el aviso trae otro origen (se suscribió desde otra dirección), se toma
// sólo su ruta.
if (navigator.serviceWorker && navigator.serviceWorker.addEventListener) {
  navigator.serviceWorker.addEventListener('message', (e) => {
    const d = (e && e.data) || {};
    if (d.tipo !== 'abrir' || !d.url) return;
    let u;
    try { u = new URL(d.url, location.href); } catch (err) { return; }
    location.assign(location.origin + u.pathname + u.search + u.hash);
  });
  if (navigator.serviceWorker.startMessages) navigator.serviceWorker.startMessages();
}

(() => {
  const raiz = document.getElementById('sec');
  if (!raiz) return;
  avisos();
  instalar();
  teclado();
  filtrarNotas();
  // Después de que `sin-recarga.js` guarde cómo llegaron las regiones (va
  // detrás en la página): tocadas antes, lo guardado no casaba, y el primer
  // envío que volviera con un fallo se llevaba lo escrito (revisor, C-0229).
  const enganchar = () => { formularioDisparador(); elegirConversaciones(); };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', enganchar);
  else enganchar();
  numeroEnIcono();
  /* Aprobar, guardar o borrar ya no recargan (C-0167): `sin-recarga.js`
   * cambia sólo las regiones y avisa con `hub:repintado`. Sin esto, el número
   * del icono esperaba a la próxima carga y el filtro a la próxima tecla
   * (C-0181). */
  document.addEventListener('hub:repintado', () => {
    numeroEnIcono();
    aplicarFiltroNotas();
    // Fuentes y disparadores guardan sin recargar (C-0229): sus nodos son
    // nuevos y llegan sin oyentes. Las dos funciones saltan lo ya enganchado.
    formularioDisparador();
    elegirConversaciones();
  });
})();

/* El número sale de la barra de secciones, que es una región: la raíz `#sec`
 * no se repinta, y leído de ahí se quedaba con el de la carga. */
function numeroEnIcono() {
  const portador = document.querySelector('[data-pendientes]');
  const n = Number((portador && portador.dataset.pendientes) || 0);
  try {
    if (n > 0 && navigator.setAppBadge) navigator.setAppBadge(n);
    else if (navigator.clearAppBadge) navigator.clearAppBadge();
  } catch (e) { /* sin permiso para el número: no pasa nada */ }
}

/* ── el teclado en el iPhone ──
 * Android encoge la página solo (`interactive-widget=resizes-content`); Safari
 * todavía no, y el teclado tapaba el cuadro de escribir. Aquí se mide lo que
 * queda visible y la página se ajusta a eso. */
function teclado() {
  const vv = window.visualViewport;
  if (!vv || !document.body.classList.contains('app-conv')) return;
  const medir = () => {
    const tapado = window.innerHeight - vv.height;
    const abierto = tapado > 120 && window.innerWidth <= 860;
    document.body.classList.toggle('teclado', abierto);
    document.body.style.height = abierto ? `${vv.height}px` : '';
    if (abierto) window.scrollTo(0, 0);
  };
  vv.addEventListener('resize', medir);
  vv.addEventListener('scroll', medir);
}

/* ── filtrar notas ──
 * Se aplica también tras un repintado: las notas llegan nuevas, todas a la
 * vista, y el filtro escrito seguía en la caja sin filtrar nada. */
function filtrarNotas() {
  const caja = document.getElementById('filtro-notas');
  if (!caja || !document.getElementById('notas')) return;
  caja.addEventListener('input', aplicarFiltroNotas);
}
function aplicarFiltroNotas() {
  const caja = document.getElementById('filtro-notas');
  const notas = document.getElementById('notas');
  if (!caja || !notas) return;
  const q = caja.value.trim().toLowerCase();
  notas.querySelectorAll('.nota').forEach(n => {
    const texto = (n.querySelector('textarea').value + ' ' + n.querySelector('.tenue').textContent).toLowerCase();
    n.hidden = Boolean(q) && !texto.includes(q);
  });
}

/* ── instalarla como app (decisión 316) ──
 * Chrome no enseña nada en la página: «Instalar app» vive en su menú, y el
 * dueño no lo encontró. Cuando el navegador lo permite, avisa con
 * `beforeinstallprompt` y se ofrece un botón; cuando no (iPhone, otro
 * navegador, ya instalada), se dice dónde está, sin prometer un botón. */
/* El bloque y su botón salen pintados del servidor y no cambian de tamaño al
 * cargar (C-0229): antes venían ocultos y aparecían después, empujando la
 * página. Sin la oferta del navegador, el botón explica cómo se hace. */
function pintarInstalar() {
  const caja = document.getElementById('instalar');
  if (!caja) return;
  caja.hidden = esApp();
}

function comoInstalar() {
  if (esIOS()) return 'En iPhone: toca Compartir → Añadir a pantalla de inicio, y ábrela desde su icono.';
  return 'En Chrome: menú ⋮ → Instalar app (o «Agregar a la pantalla principal»). Si ya la instalaste, '
    + 'ábrela desde su icono. Otros navegadores pueden no ofrecerlo.';
}

function instalar() {
  const boton = document.getElementById('instalar-boton');
  if (!boton) return;
  boton.addEventListener('click', async () => {
    if (!ofertaInstalar) {
      HubUI.avisar({ titulo: 'Instalar en este aparato', mensaje: comoInstalar() });
      return;
    }
    const oferta = ofertaInstalar;
    ofertaInstalar = null;   // el navegador sólo deja usarla una vez
    oferta.prompt();
    await oferta.userChoice;
    pintarInstalar();
  });
  pintarInstalar();
}

/* ── elegir conversaciones tocando ──
 * Las fichas son las conversaciones ya leídas; tocar una la pone o la quita
 * de «Sólo estas». El campo de texto sigue mandando: es lo que se guarda. */
function elegirConversaciones() {
  document.querySelectorAll('.vistas').forEach(caja => {
    if (caja.dataset.enganchada) return;
    caja.dataset.enganchada = '1';
    const form = caja.closest('form');
    const campo = form && form.querySelector(`input[name="${caja.dataset.para}"]`);
    if (!campo) return;
    const lista = () => campo.value.split(',').map(x => x.trim()).filter(Boolean);
    const pintar = () => {
      const hay = new Set(lista().map(x => x.toLowerCase()));
      caja.querySelectorAll('.chip').forEach(b => b.classList.toggle('on', hay.has(b.dataset.conv.toLowerCase())));
    };
    caja.querySelectorAll('.chip').forEach(b => b.addEventListener('click', () => {
      const actual = lista();
      const i = actual.findIndex(x => x.toLowerCase() === b.dataset.conv.toLowerCase());
      if (i >= 0) actual.splice(i, 1); else actual.push(b.dataset.conv);
      campo.value = actual.join(', ');
      pintar();
    }));
    campo.addEventListener('input', pintar);
    pintar();
  });
}

/* ── el formulario de disparadores (decisión 320) ──
 * Enseña sólo los campos de lo elegido. Sin JavaScript se ven todos y el
 * servidor ignora los que no tocan: el formulario sigue sirviendo. */
function formularioDisparador() {
  const form = document.getElementById('disparador-nuevo');
  if (!form || form.dataset.enganchado) return;
  form.dataset.enganchado = '1';
  const clase = document.getElementById('disp-clase');
  const que = document.getElementById('disp-que');
  const pintar = () => {
    form.querySelectorAll('.disp-si').forEach(n => { n.hidden = n.dataset.clase !== clase.value; });
    form.querySelectorAll('.disp-que').forEach(n => { n.hidden = n.dataset.que !== que.value; });
  };
  clase.addEventListener('change', pintar);
  que.addEventListener('change', pintar);
  pintar();
  // Desde aquí manda `hidden`: el CSS sólo cubría el primer pintado (C-0229).
  form.classList.add('pintado');
}

/* ── avisos en este aparato (Web Push, decisión 311) ──
 * El permiso se pide SÓLO al pulsar «Activar avisos aquí», nunca al cargar:
 * el navegador da una sola oportunidad, y en iPhone sólo vale si sale de un
 * toque. Cada vez que se abre la app se vuelve a dar de alta la suscripción
 * que haya: en iOS desaparecen solas al cabo de un tiempo. */
function nombreAparato() {
  const ua = navigator.userAgent;
  const so = /iPhone/.test(ua) ? 'iPhone' : /iPad/.test(ua) ? 'iPad' : /Android/.test(ua) ? 'Android'
    : /Windows/.test(ua) ? 'Windows' : /Mac/.test(ua) ? 'Mac' : /Linux/.test(ua) ? 'Linux' : 'Aparato';
  const nav = /Edg\//.test(ua) ? 'Edge' : /Firefox\//.test(ua) ? 'Firefox' : /Chrome\//.test(ua) ? 'Chrome'
    : /Safari\//.test(ua) ? 'Safari' : '';
  const app = esApp() ? ' (app)' : '';
  return `${so}${nav ? ' · ' + nav : ''}${app}`;
}
function esIOS() {
  return /iPad|iPhone|iPod/.test(navigator.userAgent) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
}
function esApp() {
  return window.matchMedia('(display-mode: standalone)').matches || navigator.standalone === true;
}
function bytesDeClave(b64) {
  const relleno = '='.repeat((4 - (b64.length % 4)) % 4);
  const crudo = atob((b64 + relleno).replace(/-/g, '+').replace(/_/g, '/'));
  return Uint8Array.from([...crudo].map(c => c.charCodeAt(0)));
}
/* Lo que contestó el hub, o por qué no: la pantalla decía «recibe avisos»
 * aunque el hub hubiera rechazado el alta (C-0229). `motivo` es 'abrir' (la de
 * siempre al abrir la app) o 'activar' (el botón): sólo el botón vuelve a
 * apuntar un aparato que el dueño quitó de la lista, y entonces el hub
 * contesta `quitado` en vez de apuntarlo (C-0232). */
async function darDeAlta(sub, motivo) {
  try {
    const r = await fetch('/api/secretario/push/alta', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ...sub.toJSON(), aparato: nombreAparato(), motivo }),
    });
    const d = await r.json().catch(() => ({}));
    if (r.ok && d.ok) return { fallo: '' };
    if (r.ok && d.quitado) return { fallo: '', quitado: true };
    return { fallo: d.error || `el hub contestó ${r.status}` };
  } catch (e) {
    return { fallo: 'el hub no contesta' };
  }
}

async function avisos() {
  const caja = document.getElementById('push');
  const puede = 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window;
  // Fuera de la pantalla de avisos sólo se re-sincroniza lo que ya estaba activado.
  if (!caja) {
    if (!puede || Notification.permission !== 'granted') return;
    try {
      const reg = await navigator.serviceWorker.getRegistration(PUSH);
      const sub = reg && await reg.pushManager.getSubscription();
      if (sub) await darDeAlta(sub, 'abrir');
    } catch (e) { /* se reintenta la próxima vez que se abra */ }
    return;
  }
  const texto = document.getElementById('push-texto');
  const bActivar = document.getElementById('push-activar');
  const bProbar = document.getElementById('push-probar');
  const bQuitar = document.getElementById('push-quitar');
  const decir = (t) => { texto.innerHTML = t; };
  const ver = (activar, activos) => { bActivar.hidden = !activar; bProbar.hidden = !activos; bQuitar.hidden = !activos; };
  const publica = caja.dataset.publica;

  if (!puede) {
    ver(false, false);
    if (esIOS() && !esApp()) {
      decir('En iPhone los avisos sólo llegan a la app instalada. Toca <strong>Compartir</strong> → ' +
            '<strong>Añadir a pantalla de inicio</strong>, ábrela desde el icono y vuelve aquí.');
    } else if (!window.isSecureContext) {
      decir('Este navegador sólo permite avisos por HTTPS. Entra por el nombre de Tailscale (el de Acceso).');
    } else {
      decir('Este navegador no puede recibir avisos.');
    }
    return;
  }
  if (!publica) {
    ver(false, false);
    decir('El secretario aún no preparó los avisos: hace falta que el servicio <code>hub-secretario</code> arranque una vez.');
    return;
  }
  if (Notification.permission === 'denied') {
    ver(false, false);
    decir('Los avisos están <strong>bloqueados</strong> para esta página. Se desbloquean en los ajustes del navegador ' +
          '(o, en iPhone, en Ajustes → Notificaciones → Secretario); luego recarga.');
    return;
  }
  let reg;
  try {
    reg = await navigator.serviceWorker.register('/secretario/sw.js', { scope: PUSH });
  } catch (e) {
    ver(false, false);
    decir(`No se pudo preparar este aparato: ${e.message}`);
    return;
  }
  const pintar = async () => {
    const sub = await reg.pushManager.getSubscription();
    if (sub) {
      const { fallo, quitado } = await darDeAlta(sub, 'abrir');
      if (quitado) {
        // El navegador sigue suscrito, pero el dueño lo quitó desde otro aparato:
        // «Mandar uno de prueba» no llegaría, y lo que lo trae de vuelta es activar.
        ver(true, false);
        decir('Quitaste este aparato de la lista: <strong>no recibe avisos</strong>. ' +
              '«Activar avisos aquí» para volver a recibirlos.');
        return;
      }
      ver(false, true);
      if (fallo) {
        texto.textContent = `Este navegador tiene los avisos activados, pero el hub no lo apuntó (${fallo}). Recarga para reintentarlo.`;
        return;
      }
      decir('Este aparato <strong>recibe avisos</strong>: recordatorios, permisos que te pide y lo que manden tus disparadores.');
    } else {
      ver(true, false);
      decir('Este aparato no recibe avisos todavía. Al activarlos, el navegador te pedirá permiso una vez.');
    }
  };
  bActivar.addEventListener('click', async () => {
    try {
      // Directo desde el toque: en iPhone el permiso sólo se concede así.
      const sub = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: bytesDeClave(publica) });
      const { fallo } = await darDeAlta(sub, 'activar');
      if (fallo) { texto.textContent = `No se pudo activar: ${fallo}`; return; }
      location.reload();
    } catch (e) {
      decir(Notification.permission === 'denied'
        ? 'Dijiste que no. Si cambias de idea, se desbloquea en los ajustes del navegador.'
        : `No se pudo activar: ${e.message}`);
    }
  });
  bProbar.addEventListener('click', async () => {
    bProbar.disabled = true;
    let fallo = '';
    try {
      const r = await fetch('/api/secretario/push/prueba', { method: 'POST' });
      if (!r.ok) fallo = `el hub contestó ${r.status}`;
    } catch (e) { fallo = 'el hub no contesta'; }
    if (fallo) texto.textContent = `No se pudo pedir (${fallo}). Prueba otra vez en un momento.`;
    else decir('Enviado. Debería llegarte en unos segundos; si no llega, mira «Aparatos con avisos» abajo.');
    setTimeout(() => { bProbar.disabled = false; }, 4000);
  });
  bQuitar.addEventListener('click', async () => {
    const sub = await reg.pushManager.getSubscription();
    if (sub) {
      await fetch('/api/secretario/push/baja', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ endpoint: sub.endpoint }),
      });
      await sub.unsubscribe();
    }
    location.reload();
  });
  pintar();
}
