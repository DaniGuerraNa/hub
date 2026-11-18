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
    const pc = $('#placa-control');
    if (pc) {
      pc.textContent = modo === 'claude' ? 'Claude tiene el control' : modo === 'parado' ? 'Parado' : 'Tú tienes el Mac';
      pc.className = 'placa ' + (modo === 'claude' ? 'accion' : modo === 'parado' ? 'riesgo' : 'ok');
    }
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
