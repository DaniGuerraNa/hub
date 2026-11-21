/* El espacio de trabajo: el puente en el marco de la izquierda y la terminal
   de Claude Code a la derecha, sin salir de la página.

   La terminal es un `tmux attach` por WebSocket: la conversación vive en tmux
   y sobrevive a recargar la página o reiniciar el servicio. Lo aprendido en
   otra terminal web, aplicado tal cual: el padding en `.xterm` (no en el
   marco), recortar columnas si aun así no caben, y Ctrl+V para pegar. */
(function () {
  'use strict';

  const $ = (s, r) => (r || document).querySelector(s);
  const UI = window.PuenteUI;
  const marco = $('#marco');
  const rejilla = $('#espacio');

  // ── preferencias de quien mira (sólo comodidad: si no hay almacenamiento, da igual) ──
  const leer = (k, d) => { try { const v = localStorage.getItem(k); return v === null ? d : v; } catch (e) { return d; } };
  const guardar = (k, v) => { try { localStorage.setItem(k, v); } catch (e) { /* sin almacenamiento */ } };

  // ── la terminal ──────────────────────────────────────────────────────────
  const term = new Terminal({
    fontFamily: "ui-monospace, 'SF Mono', Menlo, 'DejaVu Sans Mono', monospace",
    fontSize: Number(leer('puente.fuente', '13')),
    cursorBlink: true,
    scrollback: 5000,
    allowProposedApi: true,
    theme: {
      background: '#0b0f15', foreground: '#e3e9f2', cursor: '#3fb9d4', selectionBackground: '#2f6d8066',
      black: '#1a232e', red: '#e8735c', green: '#4ec98a', yellow: '#e0a95c', blue: '#7aa2f7',
      magenta: '#b48ce8', cyan: '#3fb9d4', white: '#c9d3ee', brightBlack: '#6b7a91', brightRed: '#ffab94',
      brightGreen: '#9ae0c2', brightYellow: '#f0cd97', brightBlue: '#aed0ef', brightMagenta: '#d9c0f7',
      brightCyan: '#a3e0e0', brightWhite: '#ffffff',
    },
  });
  const ajuste = new FitAddon.FitAddon();
  term.loadAddon(ajuste);
  term.open($('#terminal'));

  // Copiar. Con el ratón selecciona tmux (así la rueda recorre su historial), y al
  // soltar avisa de lo copiado con OSC 52: sin atenderlo, lo seleccionado no
  // llegaba nunca al portapapeles de la PC, y el Ctrl+C de después le mandaba ^C
  // a Claude (20-nov). Sólo justo después de soltar el ratón en la terminal: si
  // no, lo que se pinta en ella podría escribir en el portapapeles por su cuenta.
  let soltadoEn = 0, copiadoEn = 0;
  $('#terminal').addEventListener('mouseup', () => { soltadoEn = Date.now(); });
  function copiar(texto) {
    const fugaz = (m, r) => window.PuenteUI && window.PuenteUI.fugaz(m, r);
    navigator.clipboard.writeText(texto).then(() => { copiadoEn = Date.now(); fugaz('Copiado'); },
      () => fugaz('El navegador no dejó copiar: selecciona con Mayús y pulsa Ctrl+C', true));
  }
  term.parser.registerOscHandler(52, (datos) => {
    const b64 = datos.slice(datos.indexOf(';') + 1);
    if (!b64 || b64 === '?' || Date.now() - soltadoEn > 2000) return true;  // leer el portapapeles, nunca
    try {
      copiar(new TextDecoder().decode(Uint8Array.from(atob(b64), (c) => c.charCodeAt(0))));
    } catch (e) { /* no era base64: nada que copiar */ }
    return true;
  });

  // Ctrl+V (y Cmd+V) es pegar, no mandar ^V a la terminal: se le deja al navegador.
  // Ctrl+C con algo seleccionado (con Mayús, la selección es del navegador) o
  // recién copiado es copiar, no interrumpir a Claude: para eso está Esc.
  term.attachCustomKeyEventHandler((e) => {
    if (e.type !== 'keydown') return true;
    const tecla = (e.key || '').toLowerCase();
    const atajo = (e.ctrlKey || e.metaKey) && !e.altKey;
    if (atajo && tecla === 'v') return false;
    if (e.shiftKey && e.key === 'Insert') return false;
    if (atajo && tecla === 'c') {
      if (term.hasSelection()) {
        copiar(term.getSelection());
        term.clearSelection();
        return false;
      }
      if (Date.now() - copiadoEn < 15000) {
        copiadoEn = 0;
        if (window.PuenteUI) window.PuenteUI.fugaz('Ya estaba copiado. Para interrumpir a Claude, Esc');
        return false;
      }
    }
    if (!['control', 'meta', 'shift', 'alt'].includes(tecla)) copiadoEn = 0;
    return true;
  });

  let ws = null;
  let espera = 500;
  const placa = $('#placa-terminal');
  const codificar = new TextEncoder();

  function estadoTerminal(texto, clase) {
    placa.textContent = texto;
    placa.className = 'placa ' + clase;
  }

  function encajar() {
    // Plegada o apartada por la pantalla grande, la terminal mide cero: encajarla
    // ahí le quitaría columnas a la sesión de Claude, que se repinta a lo estrecho.
    if (rejilla.classList.contains('plegado') || document.body.classList.contains('pantalla-grande')) return;
    try { ajuste.fit(); } catch (e) { return; }
    // Si aun así la pantalla de xterm no cabe en su caja, se quitan columnas:
    // una letra cortada en silencio es peor que una columna de menos.
    const pantalla = $('.xterm-screen'), caja = $('.xterm-viewport');
    const celda = term._core && term._core._renderService ? term._core._renderService.dimensions.css.cell.width : 8;
    let guardia = 8;
    while (pantalla && caja && pantalla.offsetWidth > caja.clientWidth - celda * 1.5 && term.cols > 20 && guardia-- > 0) {
      term.resize(term.cols - 1, term.rows);
    }
    if (ws && ws.readyState === 1) ws.send(JSON.stringify({ filas: term.rows, columnas: term.cols }));
  }

  // Cortada mientras el puente se reinicia (app.js, «Reiniciar el puente»): no
  // se reengancha al viejo mientras para; al reanudar, al nuevo.
  let cortada = false;

  function conectar() {
    const proto = location.protocol === 'https:' ? 'wss://' : 'ws://';
    const este = new WebSocket(proto + location.host + '/ws/terminal');
    ws = este;
    este.binaryType = 'arraybuffer';
    estadoTerminal('conectando…', 'espera');
    este.onopen = () => {
      espera = 500;
      estadoTerminal('conectada', 'ok');
      encajar();
      term.focus();
    };
    este.onmessage = (ev) => {
      term.write(typeof ev.data === 'string' ? ev.data : new Uint8Array(ev.data));
    };
    este.onclose = () => {
      if (ws !== este) return;  // ya hay otra: la de reanudar
      if (cortada) { estadoTerminal('en pausa', 'espera'); return; }
      estadoTerminal('reconectando…', 'riesgo');
      setTimeout(conectar, espera);
      espera = Math.min(espera * 2, 8000);
    };
  }
  term.onData((d) => { if (ws && ws.readyState === 1) ws.send(codificar.encode(d)); });
  term.onBinary((d) => {
    if (!ws || ws.readyState !== 1) return;
    const b = new Uint8Array(d.length);
    for (let i = 0; i < d.length; i++) b[i] = d.charCodeAt(i) & 0xff;
    ws.send(b);
  });

  // Para el botón «Usar» de una skill (en el marco): escribe en la terminal, sin Enter.
  // Y para el aviso de código viejo (app.js): cortarla y reanudarla alrededor del
  // reinicio del puente, y reengancharla tras reabrir la conversación.
  window.PuenteTerminal = {
    escribir(texto) {
      if (ws && ws.readyState === 1) ws.send(codificar.encode(texto));
      term.focus();
    },
    cortar() {
      cortada = true;
      if (ws) ws.close();
    },
    reanudar() {
      if (!cortada) return;
      cortada = false;
      espera = 500;
      conectar();
    },
    reenganchar() { reenganchar(); },
  };

  // «Pantalla grande» en el panel (app.js): la pantalla del Mac ocupa la ventana,
  // sin la cabecera ni la terminal; al volver, la terminal se encaja otra vez.
  window.PuenteEspacio = {
    ampliar(si) {
      document.body.classList.toggle('pantalla-grande', !!si);
      if (!si) requestAnimationFrame(encajar);
    },
  };

  new ResizeObserver(() => encajar()).observe($('#terminal'));
  conectar();

  // ── reparto entre el puente y la terminal ───────────────────────────────
  const anchoGuardado = leer('puente.dock', '');
  if (anchoGuardado) rejilla.style.setProperty('--ancho-dock', anchoGuardado);
  const altoGuardado = leer('puente.dock.alto', '');
  if (altoGuardado) rejilla.style.setProperty('--alto-dock', altoGuardado);
  if (leer('puente.plegado', '0') === '1') rejilla.classList.add('plegado');

  // En pantallas estrechas el puente y la terminal van uno encima del otro
  // (ver app.css): el divisor reparte el alto en vez del ancho.
  const apilado = window.matchMedia('(max-width: 900px)');
  const divisor = $('#divisor');
  divisor.setAttribute('aria-orientation', apilado.matches ? 'horizontal' : 'vertical');
  apilado.addEventListener('change', () => divisor.setAttribute('aria-orientation', apilado.matches ? 'horizontal' : 'vertical'));
  divisor.addEventListener('pointerdown', (e) => {
    e.preventDefault();
    divisor.setPointerCapture(e.pointerId);
    divisor.classList.add('arrastrando');
    marco.style.pointerEvents = 'none'; // si no, el marco se traga el arrastre
  });
  divisor.addEventListener('pointermove', (e) => {
    if (!divisor.classList.contains('arrastrando')) return;
    const r = rejilla.getBoundingClientRect();
    if (apilado.matches) {
      const px = Math.max(140, Math.min(r.bottom - e.clientY, r.height - 140));
      rejilla.style.setProperty('--alto-dock', (px / r.height * 100).toFixed(1) + '%');
      return;
    }
    const px = Math.max(320, Math.min(r.right - e.clientX, r.width - 360));
    const pct = (px / r.width * 100).toFixed(1) + '%';
    rejilla.style.setProperty('--ancho-dock', pct);
  });
  const soltar = () => {
    if (!divisor.classList.contains('arrastrando')) return;
    divisor.classList.remove('arrastrando');
    marco.style.pointerEvents = '';
    if (apilado.matches) guardar('puente.dock.alto', rejilla.style.getPropertyValue('--alto-dock'));
    else guardar('puente.dock', rejilla.style.getPropertyValue('--ancho-dock'));
    encajar();
  };
  divisor.addEventListener('pointerup', soltar);
  divisor.addEventListener('pointercancel', soltar);

  document.addEventListener('click', async (ev) => {
    const b = ev.target.closest('button');
    if (!b) return;
    if ('plegar' in b.dataset) {
      rejilla.classList.toggle('plegado');
      guardar('puente.plegado', rejilla.classList.contains('plegado') ? '1' : '0');
      setTimeout(encajar, 50);
    }
    if ('reiniciarClaude' in b.dataset) await nuevaConversacion();
  });

  // ── las conversaciones con Claude ───────────────────────────────────────
  // Una sola abierta a la vez: cambiar cierra la abierta (Claude Code la guarda)
  // y abre la otra en la misma terminal; el control del Mac vuelve a la persona.
  const botonConv = $('#conv-boton');
  const menuConv = $('#conv-menu');
  const AVISO_CAMBIO = 'La abierta se cierra (Claude Code la guarda) y el control del Mac vuelve a ti.';

  function haceCuanto(t) {
    const s = Math.max(0, Date.now() / 1000 - t);
    if (s < 90) return 'hace un momento';
    if (s < 3600) return 'hace ' + Math.round(s / 60) + ' min';
    if (s < 86400) return 'hace ' + Math.round(s / 3600) + ' h';
    return 'hace ' + Math.round(s / 86400) + ' días';
  }

  function nombrePorOmision() {
    const d = new Date();
    const dos = (n) => String(n).padStart(2, '0');
    return 'Conversación del ' + dos(d.getDate()) + '-' + dos(d.getMonth() + 1) + ' ' + dos(d.getHours()) + ':' + dos(d.getMinutes());
  }

  // Tras cambiar, la terminal se engancha sola a la conversación nueva.
  function reenganchar() { term.reset(); if (ws) ws.close(); }

  async function nuevaConversacion() {
    cerrarMenu(false);
    const nombre = await UI.pedir('Nombre de la conversación nueva', nombrePorOmision(),
      { si: 'Abrir', nota: AVISO_CAMBIO + ' El nombre no sale del puente ni va a la bitácora.' });
    if (nombre === null) return;
    try {
      const c = await UI.cambiarConversacion('/api/conversaciones', { nombre });
      if (!c) return;
      UI.fugaz('Conversación nueva: ' + c.nombre + ' (' + c.modelo_texto + ')');
      reenganchar();
    } catch (e) { UI.fugaz(e.message, true); }
  }

  function elemento(tipo, clase, texto) {
    const e = document.createElement(tipo);
    if (clase) e.className = clase;
    if (texto !== undefined) e.textContent = texto;
    return e;
  }

  function pintarMenu(d) {
    menuConv.replaceChildren();
    const cab = elemento('div', 'conv-cab');
    cab.append(elemento('b', '', 'Conversaciones'),
      elemento('p', 'sub', 'Una sola abierta a la vez. ' + AVISO_CAMBIO + ' La siguiente se abre con ' + d.modelo_siguiente + ' (Ajustes → Modelo de Claude).'));
    menuConv.append(cab);
    const lista = elemento('ul', 'conv-lista');
    if (d.anterior) {
      const li = elemento('li', 'conv-item abierta');
      li.append(elemento('span', 'conv-nombre', 'Conversación anterior'),
        elemento('span', 'sub', 'Abierta ahora, de antes de que el puente llevara la lista. Al cambiar se cierra y desde aquí no se puede retomar (en Claude Code, /resume la encuentra).'));
      lista.append(li);
    }
    for (const c of d.lista) {
      const abierta = d.actual && d.actual.id === c.id;
      const li = elemento('li', 'conv-item' + (abierta ? ' abierta' : ''));
      const fila = elemento('div', 'conv-fila');
      fila.append(elemento('span', 'conv-nombre', c.nombre));
      if (abierta) fila.append(elemento('span', 'placa accion', 'abierta'));
      if (c.otra_carpeta) {
        const p = elemento('span', 'placa espera', 'otra carpeta');
        p.title = 'Nació en ' + c.espacio + '; el espacio de trabajo ahora es ' + d.espacio + '. Claude Code la retoma igual, pero trabajará en la carpeta de ahora.';
        fila.append(p);
      }
      li.append(fila, elemento('span', 'sub', c.modelo_texto + (c.claude_code ? ' · Claude Code ' + c.claude_code : '') + ' · usada ' + haceCuanto(c.usada)));
      const acciones = elemento('div', 'fila conv-acciones');
      const abrir = elemento('button', '', abierta ? 'Reabrir' : 'Abrir');
      abrir.title = abierta ? 'Cerrarla y volver a abrirla: carga el código del puente y el modelo de ahora' : 'Cambiar a esta conversación';
      abrir.onclick = async () => {
        const texto = (abierta ? '¿Reabrir «' + c.nombre + '»? Claude Code se cierra y la retoma, con el modelo elegido ahora.'
          : '¿Cambiar a «' + c.nombre + '»? ' + AVISO_CAMBIO) + (c.otra_carpeta ? ' Ojo: nació en otra carpeta; se retoma en la de ahora.' : '');
        if (!await UI.confirmar(texto, { si: abierta ? 'Reabrir' : 'Cambiar' })) return;
        try {
          if (!await UI.cambiarConversacion('/api/conversaciones/' + c.id + '/abrir', {})) return;
          cerrarMenu(false); UI.fugaz('Abierta: ' + c.nombre); reenganchar();
        } catch (e) { UI.fugaz(e.message, true); }
      };
      const renombrar = elemento('button', '', 'Renombrar');
      renombrar.onclick = async () => {
        const nuevo = await UI.pedir('Nombre nuevo', c.nombre,
          { si: 'Renombrar', nota: abierta ? 'Claude Code lo enseña al reabrirla.' : '' });
        if (nuevo === null) return;
        try { await UI.api('/api/conversaciones/' + c.id + '/renombrar', { nombre: nuevo }); await abrirMenu(); } catch (e) { UI.fugaz(e.message, true); }
      };
      const quitar = elemento('button', '', 'Quitar');
      quitar.disabled = abierta;
      quitar.title = abierta ? 'Es la abierta: cambia a otra antes de quitarla' : 'Quitarla de esta lista (no borra nada de Claude Code)';
      quitar.onclick = async () => {
        const ok = await UI.confirmar('¿Quitar «' + c.nombre + '» de la lista del puente? No se borra nada de Claude Code: su /resume la sigue encontrando.', { si: 'Quitar', peligro: true });
        if (!ok) return;
        try { const r = await UI.api('/api/conversaciones/' + c.id + '/quitar', {}); UI.fugaz(r.aviso); await abrirMenu(); } catch (e) { UI.fugaz(e.message, true); }
      };
      acciones.append(abrir, renombrar, quitar);
      li.append(acciones);
      lista.append(li);
    }
    if (!d.anterior && !d.lista.length) lista.append(elemento('li', 'vacio', 'Aún no hay conversaciones en la lista.'));
    menuConv.append(lista);
    const pie = elemento('div', 'conv-pie');
    const nueva = elemento('button', 'cta', 'Nueva conversación…');
    nueva.onclick = nuevaConversacion;
    pie.append(nueva);
    menuConv.append(pie);
  }

  async function abrirMenu() {
    try { pintarMenu(await UI.api('/api/conversaciones')); } catch (e) { UI.fugaz(e.message, true); return; }
    menuConv.hidden = false;
    botonConv.setAttribute('aria-expanded', 'true');
  }

  function cerrarMenu(devolverFoco) {
    if (menuConv.hidden) return;
    menuConv.hidden = true;
    botonConv.setAttribute('aria-expanded', 'false');
    if (devolverFoco) botonConv.focus();
  }

  botonConv.addEventListener('click', async () => {
    if (!menuConv.hidden) { cerrarMenu(true); return; }
    await abrirMenu();
    const primero = menuConv.querySelector('button:not([disabled])');
    if (primero) primero.focus();
  });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && !menuConv.hidden && !document.querySelector('.velo')) cerrarMenu(true);
  });
  document.addEventListener('pointerdown', (e) => {
    if (!menuConv.hidden && !menuConv.contains(e.target) && !botonConv.contains(e.target) && !e.target.closest('.velo')) cerrarMenu(false);
  });

  // ── la navegación del marco, reflejada arriba ───────────────────────────
  marco.addEventListener('load', () => {
    window.PuenteEspacio.ampliar(false);  // otra página en el marco: la pantalla grande era de la anterior
    let ruta = '/panel';
    try { ruta = marco.contentWindow.location.pathname + marco.contentWindow.location.search; } catch (e) { /* otro origen */ }
    for (const a of document.querySelectorAll('[data-nav]')) a.classList.toggle('activa', ruta.startsWith(a.dataset.nav));
    history.replaceState(null, '', ruta === '/panel' ? '/' : '/?ver=' + encodeURIComponent(ruta));
  });

  // ── avisos: lo que Claude deja listo para ti ────────────────────────────
  let ultima = null;
  let aviso = null;
  function avisar(texto, ruta, boton) {
    if (aviso) aviso.remove();
    aviso = document.createElement('div');
    aviso.className = 'aviso-flotante';
    const t = document.createElement('span'); t.textContent = texto;
    const ir = document.createElement('button'); ir.className = 'cta'; ir.textContent = boton;
    const cerrar = document.createElement('button'); cerrar.textContent = '×'; cerrar.title = 'Cerrar';
    ir.onclick = () => { marco.src = ruta; aviso.remove(); aviso = null; };
    cerrar.onclick = () => { aviso.remove(); aviso = null; };
    aviso.append(t, ir, cerrar);
    document.body.appendChild(aviso);
  }
  async function vigilar() {
    try {
      const nuevas = await UI.api('/api/bitacora?desde=' + (ultima || 0));
      if (ultima === null) { // la primera vez sólo se mira dónde va: lo viejo no se anuncia
        ultima = nuevas.length ? nuevas[nuevas.length - 1].n : 0;
        return;
      }
      for (const e of nuevas) {
        ultima = Math.max(ultima, e.n);
        if (e.tipo === 'propuesta' && e.cambio) avisar('Claude propone un cambio: ' + e.detalle, '/cambios/' + e.cambio, 'Revisar');
        else if (e.tipo === 'lectura' && e.lectura && /páginas$/.test(e.detalle)) avisar('Lectura capturada: ' + e.detalle, '/lecturas/' + e.lectura, 'Ver');
        else if (e.tipo === 'tramo' && e.cambio && /escrito/.test(e.detalle)) { /* el aviso llega al terminar */ }
      }
    } catch (e) { /* el servicio se reinicia: se reintenta */ }
  }
  vigilar();
  setInterval(vigilar, 1500);
})();
