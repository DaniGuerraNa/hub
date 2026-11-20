/* La web del puente: estado en vivo, botones y diálogos.
   Sin dependencias ni build. Los diálogos son propios (nunca alert/confirm):
   los del navegador se pueden silenciar y bloquean la página. */
(function () {
  'use strict';

  const $ = (s, r) => (r || document).querySelector(s);
  const $$ = (s, r) => Array.from((r || document).querySelectorAll(s));

  // ── red ──────────────────────────────────────────────────────────────────
  async function api(url, cuerpo) {
    const r = await fetch(url, {
      method: cuerpo === undefined ? 'GET' : 'POST',
      headers: cuerpo === undefined ? {} : { 'Content-Type': 'application/json' },
      body: cuerpo === undefined ? undefined : JSON.stringify(cuerpo),
    });
    let datos = null;
    try { datos = await r.json(); } catch (e) { datos = null; }
    if (!r.ok) throw new Error((datos && datos.detail) || ('HTTP ' + r.status));
    return datos;
  }

  // ── avisos y diálogos ────────────────────────────────────────────────────
  // Un aviso a la vez: dos seguidos se pintaban uno encima del otro e ilegibles.
  let avisoFugaz = null;
  function fugaz(texto, riesgo) {
    if (avisoFugaz) avisoFugaz.remove();
    const d = document.createElement('div');
    d.className = 'fugaz' + (riesgo ? ' riesgo' : '');
    d.setAttribute('role', riesgo ? 'alert' : 'status');
    d.textContent = texto;
    document.body.appendChild(d);
    avisoFugaz = d;
    setTimeout(() => { d.remove(); if (avisoFugaz === d) avisoFugaz = null; }, riesgo ? 7000 : 2600);
  }

  function confirmar(texto, opciones) {
    const o = opciones || {};
    return new Promise((resolver) => {
      const velo = document.createElement('div');
      velo.className = 'velo';
      velo.innerHTML = '<div class="dialogo" role="dialog" aria-modal="true"><p></p>' +
        '<div class="fila"><button data-no>Cancelar</button><button data-si></button></div></div>';
      $('p', velo).textContent = texto;
      const si = $('[data-si]', velo);
      si.textContent = o.si || 'Sí';
      si.className = o.peligro ? 'peligro' : 'cta';
      const cerrar = (v) => { velo.remove(); document.removeEventListener('keydown', tecla); resolver(v); };
      const tecla = (e) => { if (e.key === 'Escape') cerrar(false); };
      $('[data-no]', velo).onclick = () => cerrar(false);
      si.onclick = () => cerrar(true);
      velo.onclick = (e) => { if (e.target === velo) cerrar(false); };
      document.addEventListener('keydown', tecla);
      document.body.appendChild(velo);
      si.focus();
    });
  }

  // Pedir un texto (un nombre): como `confirmar`, nunca `prompt`. null si se cancela.
  function pedir(texto, valor, opciones) {
    const o = opciones || {};
    return new Promise((resolver) => {
      const velo = document.createElement('div');
      velo.className = 'velo';
      velo.innerHTML = '<form class="dialogo" role="dialog" aria-modal="true"><label></label><input>' +
        '<p class="sub" style="margin:8px 0 14px"></p>' +
        '<div class="fila"><button type="button" data-no>Cancelar</button><button type="submit" class="cta"></button></div></form>';
      const id = 'pedir-' + Date.now();
      const etiqueta = $('label', velo); etiqueta.textContent = texto; etiqueta.htmlFor = id;
      const campo = $('input', velo); campo.id = id; campo.value = valor || ''; campo.maxLength = o.max || 60;
      $('p', velo).textContent = o.nota || '';
      $('[type=submit]', velo).textContent = o.si || 'Aceptar';
      const cerrar = (v) => { velo.remove(); document.removeEventListener('keydown', tecla); resolver(v); };
      const tecla = (e) => { if (e.key === 'Escape') cerrar(null); };
      $('[data-no]', velo).onclick = () => cerrar(null);
      $('form', velo).onsubmit = (e) => { e.preventDefault(); cerrar(campo.value); };
      velo.onclick = (e) => { if (e.target === velo) cerrar(null); };
      document.addEventListener('keydown', tecla);
      document.body.appendChild(velo);
      campo.focus(); campo.select();
    });
  }

  async function accion(fn, exito) {
    try {
      const r = await fn();
      if (exito) fugaz(exito);
      return r;
    } catch (e) {
      fugaz(e.message, true);
      throw e;
    }
  }

  // ── estado en la cabecera (todas las páginas) ────────────────────────────
  const TEXTO_CONTROL = {
    libre: ['Tú tienes el Mac', 'Claude no puede tocar nada. Dale el control cuando no lo estés usando.'],
    claude: ['Claude tiene el control', 'No uses el Mac mientras tanto: lo que teclee va a la ventana que esté al frente.'],
    parado: ['Parado', 'Se cortó lo que estuviera haciendo. Claude no puede tocar nada hasta que le des el control otra vez.'],
  };
  let ultimoEstado = null;

  function pintarEstado(e) {
    ultimoEstado = e;
    const modo = e.control.modo;
    // La de la cabecera y, en «Pantalla grande» (sin cabecera), la de su barra.
    for (const pc of $$('#placa-control, [data-placa-control]')) {
      pc.textContent = modo === 'claude' ? 'Claude tiene el control' : modo === 'parado' ? 'Parado' : 'Tú tienes el Mac';
      pc.className = pc.className.replace(/\b(ok|accion|riesgo)\b/g, '').trim() + ' '
        + (modo === 'claude' ? 'accion' : modo === 'parado' ? 'riesgo' : 'ok');
    }
    const ac = $('#aviso-codigo');
    if (ac) ac.hidden = !e.codigo_viejo;
    const pa = $('#placa-aparato');
    if (pa) {
      const d = e.dispositivo || {};
      pa.textContent = (d.tipo === 'simulador' ? 'Simulador' : 'JetKVM') +
        (d.conectado ? ' · ' + (d.resolucion || 'conectado') : ' · sin conexión');
      pa.className = 'placa ' + (d.conectado ? 'ok' : 'riesgo');
      pa.title = pa.textContent + (d.firmware ? ' · firmware ' + d.firmware : '');
      const pant = $('#pantalla');
      const conectado = d.conectado ? 'si' : 'no';
      if (pant && pant.dataset.conectado !== conectado) {
        pant.dataset.conectado = conectado;
        if (window.PuenteRegion) window.PuenteRegion();
      }
    }
    const ce = $('#control-estado');
    if (ce) {
      ce.textContent = TEXTO_CONTROL[modo][0];
      ce.className = 'control-estado ' + modo;
      let ayuda = TEXTO_CONTROL[modo][1];
      if (modo === 'claude' && e.control.caduca) ayuda += ' Si no hace nada, vuelve a ti a las ' + hora(e.control.caduca).slice(0, 5) + '.';
      if (modo === 'libre' && e.control.motivo && e.control.motivo.startsWith('volvió')) ayuda = 'El control ' + e.control.motivo + '.';
      if (modo === 'libre' && e.control.motivo && e.control.motivo.startsWith('terminó')) ayuda = 'Claude ' + e.control.motivo + '.';
      $('#control-ayuda').textContent = ayuda;
      $('#boton-dar').hidden = modo === 'claude';
      $('#boton-retomar').hidden = modo !== 'claude';
    }
    const t = $('#tarea');
    if (t) t.textContent = e.tarea ? '⏵ ' + e.tarea + (e.progreso ? ' · ' + e.progreso : '') : '';
    pintarClaude(e.claude || {});
    pintarConversacion(e);
  }

  // La conversación abierta, su modelo y la versión de Claude Code con que corre.
  function pintarConversacion(e) {
    const nombre = $('#conv-nombre');
    if (!nombre) return;
    const c = e.conversacion;
    nombre.textContent = c ? c.nombre : e.conversacion_anterior ? 'Conversación anterior' : 'abriendo…';
    $('#conv-boton').title = (c ? 'Conversación abierta: ' + c.nombre
      : e.conversacion_anterior ? 'Una conversación de antes, sin registro en el puente' : 'Se está abriendo la conversación') +
      '. Pulsa para cambiar, renombrar o quitar.';
    const pm = $('#placa-modelo');
    const version = c && c.claude_code ? c.claude_code : (e.claude_code && e.claude_code.version);
    pm.hidden = !c && !e.conversacion_anterior;
    pm.textContent = (c ? c.modelo_texto : 'modelo sin registro') + (version ? ' · Claude Code ' + version : '');
    pm.title = 'Con qué corre esta conversación' + (e.claude_code && e.claude_code.ruta ? ' (' + e.claude_code.ruta + ')' : '') +
      '. El modelo se cambia en Ajustes → Modelo de Claude y vale para la siguiente que se abra.';
  }

  // Lo que está haciendo Claude, según sus hooks: en la barra de la terminal y en /claude.
  function pintarClaude(c) {
    const trabajando = c.estado === 'trabajando';
    const texto = c.estado === 'sin noticias' ? 'sin actividad'
      : trabajando ? 'trabajando' + (c.skill ? ' · ' + c.skill : '') + (c.herramienta ? ' · ' + c.herramienta : '')
      : 'espera tu mensaje' + (c.skill ? ' · última skill: ' + c.skill : '');
    for (const p of [$('#placa-claude'), $('#claude-ahora')]) {
      if (!p) continue;
      p.textContent = texto;
      p.className = 'placa ' + (trabajando ? 'accion' : c.estado === 'esperando' ? 'ok' : '');
      p.title = texto;
    }
  }

  // /claude: la lista de eventos, al día.
  let ultimoEventoClaude = 0;
  async function eventosClaude() {
    const ul = $('#claude-eventos');
    if (!ul) return;
    try {
      const a = await api('/api/claude/actividad');
      const nuevos = a.eventos.filter((e) => e.t > ultimoEventoClaude).reverse();
      for (const e of nuevos) {
        const vacio = $('.vacio', ul);
        if (vacio) vacio.remove();
        const li = document.createElement('li');
        const h = document.createElement('span'); h.className = 'hora'; h.textContent = hora(e.t);
        const r = document.createElement('span'); r.textContent = e.resumen;
        li.append(h, r);
        ul.prepend(li);
        ultimoEventoClaude = Math.max(ultimoEventoClaude, e.t);
      }
    } catch (e) { /* reintenta */ }
  }
  for (const h of $$('#claude-eventos [data-t]')) ultimoEventoClaude = Math.max(ultimoEventoClaude, Number(h.dataset.t));

  async function sondear() {
    eventosClaude();
    try { pintarEstado(await api('/api/estado')); } catch (e) { /* el servicio se reinicia: se reintenta */ }
  }

  // ── bitácora (panel) ─────────────────────────────────────────────────────
  let ultimaN = 0;
  function hora(t) {
    const d = new Date(t * 1000);
    return d.toLocaleTimeString('es', { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  }
  async function bitacora() {
    const ul = $('#bitacora');
    if (!ul) return;
    try {
      const nuevas = await api('/api/bitacora?desde=' + ultimaN);
      for (const e of nuevas) {
        const li = document.createElement('li');
        li.className = e.quien + ' ' + e.tipo;
        const h = document.createElement('span'); h.className = 'hora'; h.textContent = hora(e.t);
        const c = document.createElement('span');
        const tipo = document.createElement('span'); tipo.className = 'tipo'; tipo.textContent = e.quien + ' · ' + e.tipo;
        c.append(tipo, document.createTextNode(' ' + e.detalle));
        li.append(h, c);
        ul.prepend(li);
        ultimaN = Math.max(ultimaN, e.n);
      }
      while (ul.children.length > 120) ul.lastChild.remove();
    } catch (e) { /* reintenta en la siguiente vuelta */ }
  }

  // ── región del editor sobre la pantalla ─────────────────────────────────
  function pintarRegion(contenedor, region) {
    const caja = $('#region', contenedor);
    if (!caja || !region) return;
    const img = $('img', contenedor);
    const ancho = Number(contenedor.dataset.ancho), alto = Number(contenedor.dataset.alto);
    const ex = img.clientWidth / ancho, ey = img.clientHeight / alto;
    Object.assign(caja.style, {
      left: region[0] * ex + 'px', top: region[1] * ey + 'px',
      width: region[2] * ex + 'px', height: region[3] * ey + 'px',
    });
  }

  // ── clics ────────────────────────────────────────────────────────────────
  document.addEventListener('click', async (ev) => {
    const b = ev.target.closest('button, [data-copiar]');
    if (!b) return;
    const d = b.dataset;

    if (d.control) {
      if (d.control === 'dar') {
        const ok = await confirmar('¿Le das el control del Mac a Claude? No lo uses mientras tanto: lo que teclee irá a la ventana que esté al frente.', { si: 'Dar el control' });
        if (!ok) return;
      }
      await accion(() => api('/api/control', { accion: d.control }),
        d.control === 'parar' ? 'Parado' : d.control === 'dar' ? 'Claude tiene el control' : 'Vuelves a tener el Mac');
      sondear();
      return;
    }
    if ('reconectar' in d) {
      b.disabled = true;
      try {
        const r = await accion(() => api('/api/reconectar', {}));
        fugaz(r.error_conexion ? 'No conecta: ' + r.error_conexion : 'Conectado. El control vuelve a ti.', !!r.error_conexion);
        setTimeout(() => location.reload(), r.error_conexion ? 2500 : 900);
      } finally { b.disabled = false; }
      return;
    }
    if ('leer' in d) {
      const nombre = ($('#nombre-lectura').value || '').trim() || 'documento';
      if (!ultimoEstado || ultimoEstado.control.modo !== 'claude') {
        const ok = await confirmar('Para leer, el puente necesita el control del Mac: irá al principio del documento y bajará página a página. ¿Se lo das ahora?', { si: 'Dar el control y leer' });
        if (!ok) return;
        await accion(() => api('/api/control', { accion: 'dar' }));
      }
      const r = await accion(() => api('/api/lecturas', { nombre }));
      location.href = r.url;
      return;
    }
    if (d.usarSkill) {
      // Deja «/skill » escrito en la terminal de Claude, sin Enter: terminas tú la petición.
      const texto = '/' + d.usarSkill + ' ';
      const t = window.top && window.top.PuenteTerminal;
      if (t) { t.escribir(texto); fugaz('Escrito en la terminal: completa la petición y pulsa Enter'); }
      else { try { await navigator.clipboard.writeText(texto); fugaz('Copiado: pégalo en la terminal de Claude'); } catch (e) { fugaz(texto); } }
      return;
    }
    if (d.copiar) {
      const campo = $('#huella');
      if (campo) campo.value = d.copiar;
      return;
    }
    if (d.resolver) {
      await accion(() => api(location.pathname.replace('/lecturas/', '/api/lecturas/') + '/resolver',
        { linea: Number(d.resolver), texto: d.texto }), 'Línea ' + d.resolver + ' resuelta');
      location.reload();
      return;
    }
    if (d.guardarPagina) {
      const n = d.guardarPagina;
      const texto = $('[data-pagina-texto="' + n + '"]').value;
      const r = await accion(() => api(location.pathname.replace('/lecturas/', '/api/lecturas/') + '/paginas/' + n, { texto }));
      fugaz(r.errores.length ? 'Guardada, con avisos: ' + r.errores[0] : 'Página ' + n + ' guardada', r.errores.length > 0);
      setTimeout(() => location.reload(), 700);
      return;
    }
    if ('huellaLectura' in d) {
      const r = await accion(() => api(location.pathname.replace('/lecturas/', '/api/lecturas/') + '/huella', { referencia: $('#huella').value }));
      fugaz(r.verificada ? 'Exacta: ' + r.variante : 'No coincide', !r.verificada);
      setTimeout(() => location.reload(), 900);
      return;
    }
    const cambio = $('[data-cambio]');
    const base = cambio ? '/api/cambios/' + cambio.dataset.cambio : '';
    if ('aprobar' in d) {
      const ok = await confirmar('¿Apruebas estos tramos? Quedarán listos para teclearse en el editor del Mac. Guardar en la base seguirá siendo cosa tuya.', { si: 'Aprobar' });
      if (!ok) return;
      await accion(() => api(base + '/aprobar', {}), 'Aprobado');
      location.reload();
      return;
    }
    if ('rechazar' in d) {
      await accion(() => api(base + '/rechazar', {}), 'Rechazado');
      location.reload();
      return;
    }
    if ('escribir' in d) {
      const conControl = ultimoEstado && ultimoEstado.control.modo === 'claude';
      const ok = await confirmar(conControl
        ? '¿Escribir ahora en el Mac? No lo toques hasta que termine.'
        : 'Para escribir, el puente necesita el control del Mac. ¿Se lo das y empieza? No lo toques hasta que termine.',
        { si: 'Escribir' });
      if (!ok) return;
      if (!conControl) await accion(() => api('/api/control', { accion: 'dar' }));
      await accion(() => api(base + '/escribir', {}));
      location.reload();
      return;
    }
    if ('huellaCambio' in d) {
      const r = await accion(() => api(base + '/huella', { referencia: $('#huella').value }));
      fugaz(r.verificado ? 'Coincide: la base tiene lo acordado' : 'No coincide', !r.verificado);
      setTimeout(() => location.reload(), 900);
      return;
    }
    if ('simGuardar' in d) {
      await accion(() => api('/api/simulador/guardar', {}), 'Guardado en la base simulada');
      location.reload();
      return;
    }
    if ('marcarRegion' in d) {
      const img = $('#captura-ajustes');
      $('#pantalla-ajustes').hidden = false;
      $('#sin-imagen').hidden = true;
      img.src = '/api/pantalla.jpg?ancho=1600&t=' + Date.now();
      fugaz('Arrastra sobre la captura para marcar el editor');
    }
  });

  // ── usar el Mac desde la pantalla del puente ────────────────────────────
  // El ratón y el teclado de la persona van al Mac por /ws/mando. Se manda la
  // tecla FÍSICA (KeyboardEvent.code → código HID), como la web del JetKVM: el
  // Mac la convierte con su propia distribución. Nada de lo tecleado se guarda.
  const HID = { Enter: 0x28, Escape: 0x29, Backspace: 0x2A, Tab: 0x2B, Space: 0x2C, Minus: 0x2D, Equal: 0x2E,
    BracketLeft: 0x2F, BracketRight: 0x30, Backslash: 0x31, IntlHash: 0x32, Semicolon: 0x33, Quote: 0x34,
    Backquote: 0x35, Comma: 0x36, Period: 0x37, Slash: 0x38, CapsLock: 0x39, PrintScreen: 0x46,
    ScrollLock: 0x47, Pause: 0x48, Insert: 0x49, Home: 0x4A, PageUp: 0x4B, Delete: 0x4C, End: 0x4D,
    PageDown: 0x4E, ArrowRight: 0x4F, ArrowLeft: 0x50, ArrowDown: 0x51, ArrowUp: 0x52, NumLock: 0x53,
    NumpadDivide: 0x54, NumpadMultiply: 0x55, NumpadSubtract: 0x56, NumpadAdd: 0x57, NumpadEnter: 0x58,
    NumpadDecimal: 0x63, IntlBackslash: 0x64, ContextMenu: 0x65, IntlRo: 0x87, IntlYen: 0x89,
    ControlLeft: 0xE0, ShiftLeft: 0xE1, AltLeft: 0xE2, MetaLeft: 0xE3,
    ControlRight: 0xE4, ShiftRight: 0xE5, AltRight: 0xE6, MetaRight: 0xE7 };
  for (let i = 0; i < 26; i++) HID['Key' + String.fromCharCode(65 + i)] = 0x04 + i;
  for (let i = 1; i <= 9; i++) { HID['Digit' + i] = 0x1D + i; HID['Numpad' + i] = 0x58 + i; }
  HID.Digit0 = 0x27; HID.Numpad0 = 0x62;
  for (let i = 1; i <= 12; i++) HID['F' + i] = 0x39 + i;
  // Con «Ctrl = ⌘», Ctrl y ⌘ se cambian el sitio: Windows se queda la tecla ⌘.
  const CAMBIO_CTRL = { ControlLeft: 0xE3, ControlRight: 0xE7, MetaLeft: 0xE0, MetaRight: 0xE4 };

  const pantallaMando = $('#pantalla');
  const botonUsar = $('#mando-usar');
  if (pantallaMando && botonUsar) {
    const imagen = $('#directo');
    const casillaCtrl = $('#mando-ctrl');
    const ayuda = $('#mando-ayuda');
    const ayudaQuieto = ayuda.textContent;
    const extras = $$('[data-mando-atajo], #mando-pegar');
    let ws = null, activo = false, botones = 0, ultimoMov = 0, acumulado = 0;
    try { casillaCtrl.checked = localStorage.getItem('puente-mando-ctrl') !== 'no'; } catch (e) { /* sin almacenamiento */ }
    casillaCtrl.addEventListener('change', () => {
      try { localStorage.setItem('puente-mando-ctrl', casillaCtrl.checked ? 'si' : 'no'); } catch (e) { /* idem */ }
    });

    const enviar = (o) => { if (ws && ws.readyState === 1) ws.send(JSON.stringify(o)); };
    const punto = (e) => {
      const r = imagen.getBoundingClientRect();
      const ancho = Number(pantallaMando.dataset.ancho) || 1920;
      const alto = Number(pantallaMando.dataset.alto) || 1080;
      return { x: Math.round((e.clientX - r.left) / r.width * ancho), y: Math.round((e.clientY - r.top) / r.height * alto) };
    };
    const codigoDe = (e) => (casillaCtrl.checked && e.code in CAMBIO_CTRL) ? CAMBIO_CTRL[e.code] : HID[e.code];
    const bitDe = (boton) => ({ 0: 1, 2: 2, 1: 4 })[boton] || 0;

    function parar(motivo) {
      if (!activo) return;
      activo = false;
      enviar({ t: 'soltar' });
      if (ws) { const v = ws; ws = null; setTimeout(() => v.close(), 50); }
      botones = 0;
      pantallaMando.classList.remove('usando');
      botonUsar.textContent = 'Usar el Mac desde aquí';
      extras.forEach((b) => { b.hidden = true; });
      ayuda.textContent = ayudaQuieto;
      if (motivo) fugaz(motivo, true);
    }
    function empezar() {
      const v = new WebSocket((location.protocol === 'https:' ? 'wss://' : 'ws://') + location.host + '/ws/mando');
      ws = v;
      v.onmessage = (m) => { let d = {}; try { d = JSON.parse(m.data); } catch (e) { return; } if (d.no) parar(d.no); };
      v.onclose = () => { if (ws === v) parar('Se cortó la conexión con el puente.'); };
      activo = true;
      pantallaMando.classList.add('usando');
      botonUsar.textContent = 'Dejar de usar';
      extras.forEach((b) => { b.hidden = false; });
      ayuda.textContent = 'Usando el Mac: lo que teclees y hagas sobre la imagen va al Mac. Para parar, «Dejar de usar» o un clic fuera de la imagen.';
    }
    botonUsar.addEventListener('click', () => (activo ? parar() : empezar()));

    // Sólo lo que pasa sobre la imagen: con zoom, la caja tiene márgenes negros y
    // barras de desplazamiento, y un clic ahí llegaría al Mac como clic en el borde.
    pantallaMando.addEventListener('mousemove', (e) => {
      if (!activo || e.target !== imagen || Date.now() - ultimoMov < 30) return;
      ultimoMov = Date.now();
      enviar({ t: 'raton', ...punto(e), b: botones });
    });
    pantallaMando.addEventListener('mousedown', (e) => {
      if (!activo || e.target !== imagen) return;
      e.preventDefault();
      botones |= bitDe(e.button);
      enviar({ t: 'raton', ...punto(e), b: botones });
    });
    window.addEventListener('mouseup', (e) => {
      if (!activo || !botones) return;
      botones &= ~bitDe(e.button);
      enviar({ t: 'raton', ...punto(e), b: botones });
    });
    pantallaMando.addEventListener('contextmenu', (e) => { if (activo) e.preventDefault(); });
    pantallaMando.addEventListener('wheel', (e) => {
      if (!activo) return;
      e.preventDefault();
      acumulado += e.deltaY;
      const paso = e.deltaMode === 1 ? 3 : 100;  // líneas o píxeles por «clic» de rueda
      while (Math.abs(acumulado) >= paso) {
        const signo = Math.sign(acumulado);
        enviar({ t: 'rueda', pasos: signo });  // positivo: el contenido baja
        acumulado -= signo * paso;
      }
    }, { passive: false });
    // Un clic fuera de la imagen y de sus barras (la del mando y la del zoom) suelta el Mac.
    document.addEventListener('mousedown', (e) => {
      if (activo && !e.target.closest('#pantalla, #mando, .zoom, #ampliar, .velo')) parar();
    }, true);
    const tecla = (e) => {
      if (!activo || $('.velo')) return;  // con un diálogo del puente abierto, el teclado es suyo
      e.preventDefault();
      e.stopPropagation();
      if (e.repeat) return;  // la repetición la hace el Mac mientras la tecla siga abajo
      const codigo = codigoDe(e);
      if (codigo) enviar({ t: 'tecla', codigo, abajo: e.type === 'keydown' });
    };
    document.addEventListener('keydown', tecla, true);
    document.addEventListener('keyup', tecla, true);
    window.addEventListener('blur', () => { if (activo) { botones = 0; enviar({ t: 'soltar' }); } });

    $$('[data-mando-atajo]').forEach((b) => b.addEventListener('click', () => enviar({ t: 'combinacion', atajo: b.dataset.mandoAtajo })));
    $('#mando-pegar').addEventListener('click', async () => {
      let texto = null;
      try { texto = await navigator.clipboard.readText(); } catch (e) { texto = null; }
      if (!texto) texto = await pedir('Texto para teclear en el Mac', '', { max: 5000, si: 'Teclear', nota: 'Se teclea con la distribución de Ajustes, letra a letra.' });
      if (texto) enviar({ t: 'pegar', texto });
    });
  }

  // ── pantalla grande y zoom ──────────────────────────────────────────────
  // «Que se vea más grande, pantalla completa pero dentro de la ventana»: la
  // tarjeta ocupa el navegador (el monitor entero sería la Fullscreen API, y no
  // es lo que se pidió). El zoom va en % del tamaño real del Mac, y el mando no
  // cambia: punto() mide la imagen tal como se pinta, ampliada y desplazada.
  const tarjeta = $('#tarjeta-pantalla');
  if (tarjeta) {
    const pant = $('#pantalla'), marcoMac = $('#marco-mac'), img = $('#directo');
    const valor = $('#zoom-valor'), botonAmpliar = $('#ampliar');
    const PASOS = [0.25, 0.33, 0.5, 0.67, 0.75, 0.9, 1, 1.1, 1.25, 1.5, 1.75, 2, 2.5, 3];
    let zoom = null;  // null: ajustada a la ventana
    try {
      const z = Number(localStorage.getItem('puente-zoom'));
      if (PASOS.includes(z)) zoom = z;
    } catch (e) { /* sin almacenamiento: se empieza ajustada */ }
    const real = () => [Number(pant.dataset.ancho) || 1920, Number(pant.dataset.alto) || 1080];
    const ajuste = () => { const [an, al] = real(); return Math.min(pant.clientWidth / an, pant.clientHeight / al); };
    const ampliada = () => tarjeta.classList.contains('ampliada');

    const pintar = () => {
      const [an] = real();
      let pedir = 1280;
      if (ampliada()) {
        marcoMac.style.width = Math.round(an * (zoom === null ? ajuste() : zoom)) + 'px';
        valor.textContent = zoom === null ? 'Ajustar · ' + Math.round(ajuste() * 100) + ' %' : Math.round(zoom * 100) + ' %';
        valor.title = zoom === null ? 'Ajustada a la ventana' : 'Volver a ajustarla a la ventana';
        // Pintada a más de 1280 px, se pide a su tamaño real: reducida y luego
        // estirada, la letra pequeña no se lee.
        if (marcoMac.clientWidth * (window.devicePixelRatio || 1) > 1300) pedir = an;
      } else {
        marcoMac.style.width = '';
      }
      pant.classList.toggle('desplazable', ampliada()
        && (pant.scrollWidth > pant.clientWidth + 1 || pant.scrollHeight > pant.clientHeight + 1));
      const src = '/api/pantalla.mjpg?ancho=' + pedir;
      if (img.getAttribute('src') !== src) img.setAttribute('src', src);
      if (window.PuenteRegion) window.PuenteRegion();
    };
    const fijarZoom = (z) => {
      zoom = z;
      try { if (z === null) localStorage.removeItem('puente-zoom'); else localStorage.setItem('puente-zoom', String(z)); } catch (e) { /* idem */ }
      pintar();
    };
    const ampliar = (si) => {
      tarjeta.classList.toggle('ampliada', si);
      document.documentElement.classList.toggle('con-pantalla-grande', si);
      botonAmpliar.textContent = si ? '✕ Salir' : '⤢ Pantalla grande';
      botonAmpliar.title = si ? 'Volver a la vista de siempre (o Esc, si no estás usando el Mac)'
        : 'La pantalla del Mac ocupa toda la ventana del navegador, no el monitor';
      // En el espacio de trabajo, la cabecera y la terminal se apartan mientras tanto.
      try { if (window.top !== window && window.top.PuenteEspacio) window.top.PuenteEspacio.ampliar(si); } catch (e) { /* otro origen */ }
      requestAnimationFrame(() => requestAnimationFrame(pintar));  // el marco cambia de tamaño antes
    };
    botonAmpliar.addEventListener('click', () => ampliar(!ampliada()));
    $('#zoom-mas').addEventListener('click', () => {
      const ahora = zoom === null ? ajuste() : zoom;
      const siguiente = PASOS.find((p) => p > ahora * 1.04);
      if (siguiente) fijarZoom(siguiente);
    });
    $('#zoom-menos').addEventListener('click', () => {
      if (zoom === null) return;
      const anterior = [...PASOS].reverse().find((p) => p < zoom * 0.97);
      // Más pequeña que ajustada no sirve de nada: ahí se vuelve a ajustar.
      fijarZoom(anterior && anterior > ajuste() * 1.04 ? anterior : null);
    });
    valor.addEventListener('click', () => fijarZoom(null));
    // Usando el Mac, Esc es del Mac (el mando se lo queda antes de que llegue aquí).
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && ampliada() && !pant.classList.contains('usando') && !$('.velo')) ampliar(false);
    });
    window.addEventListener('resize', pintar);
    // Sin usar el Mac, arrastrar mueve la imagen ampliada; usándolo, el ratón es del Mac.
    let arrastre = null;
    pant.addEventListener('mousedown', (e) => {
      if (!pant.classList.contains('desplazable') || pant.classList.contains('usando') || e.button !== 0) return;
      if (!marcoMac.contains(e.target)) return;  // las barras de desplazamiento van solas
      e.preventDefault();
      arrastre = { x: e.clientX, y: e.clientY, l: pant.scrollLeft, t: pant.scrollTop };
      pant.classList.add('arrastrando');
    });
    window.addEventListener('mousemove', (e) => {
      if (!arrastre) return;
      pant.scrollLeft = arrastre.l - (e.clientX - arrastre.x);
      pant.scrollTop = arrastre.t - (e.clientY - arrastre.y);
    });
    window.addEventListener('mouseup', () => {
      if (arrastre) { arrastre = null; pant.classList.remove('arrastrando'); }
    });
  }

  // ── ajustes: guardar y marcar la región arrastrando ─────────────────────
  const form = $('#ajustes');
  if (form) {
    form.addEventListener('submit', async (ev) => {
      ev.preventDefault();
      // Una sección por prefijo del nombre del campo (dispositivo., perfil., claude.).
      const datos = {};
      for (const campo of $$('[name]', form)) {
        const [seccion, clave] = campo.name.split('.');
        let v = campo.type === 'checkbox' ? campo.checked : campo.value;
        if (clave === 'region_editor' || clave === 'aparcar_raton') v = v.split(',').map((x) => Number(x.trim()));
        if (clave === 'retardo_tecla_ms') v = Number(v);
        (datos[seccion] = datos[seccion] || {})[clave] = v;
      }
      const r = await accion(() => api('/api/ajustes', datos), 'Ajustes guardados');
      if (r.error_conexion) fugaz('No conecta: ' + r.error_conexion, true);
      setTimeout(() => location.reload(), 800);
    });
    const cont = $('#pantalla-ajustes');
    const img = $('#captura-ajustes');
    const sel = $('#seleccion');
    let inicio = null;
    const punto = (e) => {
      const r = img.getBoundingClientRect();
      const ex = Number(cont.dataset.ancho) / r.width, ey = Number(cont.dataset.alto) / r.height;
      return { x: Math.round((e.clientX - r.left) * ex), y: Math.round((e.clientY - r.top) * ey),
               px: e.clientX - r.left, py: e.clientY - r.top };
    };
    cont.addEventListener('mousedown', (e) => { e.preventDefault(); inicio = punto(e); sel.hidden = false; });
    window.addEventListener('mousemove', (e) => {
      if (!inicio) return;
      const p = punto(e);
      Object.assign(sel.style, {
        left: Math.min(p.px, inicio.px) + 'px', top: Math.min(p.py, inicio.py) + 'px',
        width: Math.abs(p.px - inicio.px) + 'px', height: Math.abs(p.py - inicio.py) + 'px',
      });
    });
    window.addEventListener('mouseup', (e) => {
      if (!inicio) return;
      const p = punto(e);
      const r = [Math.min(p.x, inicio.x), Math.min(p.y, inicio.y), Math.abs(p.x - inicio.x), Math.abs(p.y - inicio.y)];
      inicio = null;
      if (r[2] < 50 || r[3] < 50) { sel.hidden = true; return; }
      $('#region-campo').value = r.join(', ');
      fugaz('Región marcada: guarda para usarla');
    });
    const repintar = () => pintarRegion(cont, window.PERFIL && window.PERFIL.region_editor);
    img.addEventListener('load', repintar);
    // Sin aparato no hay captura: en vez de un recuadro roto, se dice por qué y qué hacer.
    const sinImagen = () => { cont.hidden = true; $('#sin-imagen').hidden = false; };
    img.addEventListener('error', sinImagen);
    if (img.complete && img.naturalWidth === 0) sinImagen();
    window.addEventListener('resize', repintar);
  }

  // ── lectura: la consulta de la huella, con el objeto que se escriba ─────
  const objeto = $('#objeto');
  if (objeto) {
    objeto.addEventListener('input', () => {
      const nombre = objeto.value.trim() || 'dbo.objeto';
      for (const pre of $$('pre.consulta[data-plantilla]')) pre.textContent = pre.dataset.plantilla.split('{objeto}').join(nombre);
    });
  }

  // ── panel: región sobre el directo ──────────────────────────────────────
  const pantalla = $('#pantalla');
  if (pantalla) {
    const casilla = $('#ver-region');
    // Sin aparato, el directo es un fotograma que lo dice: la región encima sólo confunde.
    const repintar = () => {
      $('#region', pantalla).hidden = !casilla.checked || pantalla.dataset.conectado !== 'si';
      pintarRegion(pantalla, window.PERFIL && window.PERFIL.region_editor);
    };
    window.PuenteRegion = repintar;
    $('#directo').addEventListener('load', repintar);
    casilla.addEventListener('change', repintar);
    window.addEventListener('resize', repintar);
    setTimeout(repintar, 600);
  }

  // Horas legibles en el historial de un cambio.
  for (const h of $$('[data-t]')) h.textContent = hora(Number(h.dataset.t));

  // ── lectura y cambio: recargar mientras haya trabajo en marcha ──────────
  const enCurso = $('[data-estado="capturando"], [data-estado="escribiendo"]');
  let tareaVista = false;
  sondear();
  bitacora();
  let vueltas = 0;
  setInterval(async () => {
    await sondear();
    await bitacora();
    vueltas += 1;
    if (enCurso && ultimoEstado) {
      const p = $('#progreso');
      if (p && ultimoEstado.progreso) p.textContent = 'No toques el Mac (' + ultimoEstado.progreso + '). Si algo va mal, pulsa Parar arriba.';
      if (ultimoEstado.tarea) {
        tareaVista = true;
        // Mientras captura, recargar de vez en cuando enseña las páginas que van llegando.
        if (enCurso.dataset.estado === 'capturando' && vueltas % 4 === 0) location.reload();
      } else if (tareaVista || vueltas === 2) {
        // Terminó (o ya había terminado al abrir la página): una recarga y basta.
        location.reload();
      }
    }
  }, 1000);

  window.PuenteUI = { api, confirmar, pedir, fugaz };
})();
