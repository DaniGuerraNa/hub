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
    if (!r.ok) {
      const error = new Error((datos && datos.detail) || ('HTTP ' + r.status));
      // Para quien tiene que distinguir un «no» de otro (un 409 que se puede confirmar).
      error.status = r.status;
      error.motivo = r.headers.get('X-Puente-Motivo') || '';
      throw error;
    }
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

  // Cambiar de conversación (abrir, reabrir, una nueva). Con Claude trabajando
  // el puente dice que no (409), porque cerrarla lo corta a medias: se le
  // pregunta a la persona y, si quiere, se repite. null si no quiso.
  async function cambiarConversacion(url, cuerpo) {
    try {
      return await api(url, cuerpo);
    } catch (e) {
      if (e.status !== 409 || e.motivo !== 'trabajando') throw e;
      if (!await confirmar(e.message + ' ¿La cierras igualmente?', { si: 'Cerrarla igualmente', peligro: true })) return null;
      return api(url, Object.assign({}, cuerpo, { aunque_trabaje: true }));
    }
  }

  // ── lo que esta página tiene abierto contra el puente ───────────────────
  // El directo, el mando y la terminal. Antes de reiniciarlo se cierran: el
  // directo no termina mientras se mira, y el puente esperaría por él al parar;
  // el mando de esta página haría creer que se está usando el Mac; y la terminal
  // se reengancharía al puente viejo mientras para. Cada parte apunta aquí cómo
  // se corta y cómo se reanuda, también la de un marco (el panel, en el espacio).
  let cortado = false;
  const alCortar = [];
  function cortar() {
    cortado = true;
    for (const img of $$('img')) {
      const src = img.getAttribute('src') || '';
      if (src.startsWith('/api/pantalla.mjpg')) { img.dataset.directo = src; img.removeAttribute('src'); }
    }
    for (const [c] of alCortar) c();
    for (const f of $$('iframe')) { try { f.contentWindow.PuenteUI.cortar(); } catch (e) { /* aún cargando */ } }
    if (window.PuenteTerminal && window.PuenteTerminal.cortar) window.PuenteTerminal.cortar();
  }
  function reanudar() {
    cortado = false;
    for (const img of $$('img[data-directo]')) { img.setAttribute('src', img.dataset.directo); delete img.dataset.directo; }
    for (const [, r] of alCortar) r();
    for (const f of $$('iframe')) { try { f.contentWindow.PuenteUI.reanudar(); } catch (e) { /* aún cargando */ } }
    if (window.PuenteTerminal && window.PuenteTerminal.reanudar) window.PuenteTerminal.reanudar();
  }

  function pintarJiggler(encendido, texto, forzar) {
    const b = $('#jiggler');
    if (!b || (b.disabled && !forzar)) return;  // el sondeo no pisa lo que se está cambiando
    b.textContent = 'Jiggler: ' + texto;
    b.setAttribute('aria-pressed', encendido ? 'true' : 'false');
  }

  // ── estado en la cabecera (todas las páginas) ────────────────────────────
  const TEXTO_CONTROL = {
    libre: ['Tú tienes el Mac', 'Claude no puede tocar nada. Dale el control cuando no lo estés usando.'],
    claude: ['Claude tiene el control', 'Lo tiene hasta que termine el encargo, también entre una lectura y una escritura. No uses el Mac mientras tanto: lo que teclee va a la ventana que esté al frente. Para usarlo tú, «Usar el Mac desde aquí» se lo quita.'],
    parado: ['Parado', 'Se cortó lo que estuviera haciendo. Claude no puede tocar nada hasta que le des el control otra vez.'],
  };
  let ultimoEstado = null;

  /* El aviso de conexión del panel, con lo que dice el aparato del Mac
     (C-0477). Lo pinta el sondeo: en cuanto vuelve la imagen se va solo.
     Todo con textContent: el error trae texto del aparato y su dirección. */
  function pintarAvisoConexion(e) {
    const caja = $('#aviso-conexion');
    if (!caja) return;
    const d = e.dispositivo || {};
    let titulo = '', texto = '', tono = 'riesgo', despertar = true, ajustes = false;
    // Conectando, el aparato dice «sin conectar» sin que nada haya fallado.
    const conectando = !!e.conectando;
    for (const r of $$('[data-reconectar]')) {
      if (!r.dataset.texto) r.dataset.texto = r.textContent;
      r.disabled = conectando;
      r.textContent = conectando ? 'Reconectando…' : r.dataset.texto;
    }
    if (conectando) {
      titulo = 'Conectando con el JetKVM…';
      texto = 'Puede tardar unos segundos.';
      tono = 'accion';
      despertar = false;
    } else if (d.mac === 'reposo') {
      titulo = 'El Mac está en reposo.';
      texto = 'El JetKVM está conectado, pero no llega imagen. «Despertar el Mac» lo saca del reposo; también vuelve solo si alguien toca su teclado o su ratón.';
      tono = 'accion';
    } else if (d.mac === 'sin_usb') {
      titulo = 'El JetKVM no ve el Mac por USB.';
      texto = (d.conectado ? 'Se ve su pantalla, pero el teclado y el ratón no le llegan, ni la señal de despertar.'
        : 'Ni el teclado ni la señal de despertar le llegan.') + ' ¿Está puesto el cable USB entre los dos?';
      despertar = false;
    } else if (!d.conectado && d.mac === 'despierto') {
      // El USB ya dice que despertó, pero la imagen tarda (un Mac recién
      // despierto, o con la pantalla apagada): no es un fallo de conexión.
      titulo = 'El Mac está despierto, pero aún no llega su imagen.';
      texto = d.senal && d.senal !== 'ok'
        ? 'El JetKVM no recibe señal de vídeo: puede que su pantalla esté apagada o el HDMI suelto. Mover su ratón suele encenderla.'
        : 'Suele llegar en unos segundos.';
      tono = 'accion';
      despertar = false;
    } else if (!d.conectado) {
      titulo = 'No hay conexión con el aparato.';
      texto = e.error_conexion || d.motivo || d.error || '';
      ajustes = true;
    }
    caja.hidden = !titulo;
    caja.className = 'aviso aviso-conexion ' + tono;
    $('#aviso-conexion-titulo').textContent = titulo;
    $('#aviso-conexion-texto').textContent = texto;
    $('#aviso-conexion-despertar').hidden = !despertar;
    $('#aviso-conexion-ajustes').hidden = !ajustes;
    const aparato = $('#aviso-aparato');
    if (aparato) aparato.hidden = !!titulo;
  }

  function pintarEstado(e) {
    ultimoEstado = e;
    const modo = e.control.modo;
    // La de la cabecera y, en «Pantalla grande» (sin cabecera), la de su barra.
    for (const pc of $$('#placa-control, [data-placa-control]')) {
      pc.textContent = modo === 'claude' ? 'Claude tiene el control' : modo === 'parado' ? 'Parado' : 'Tú tienes el Mac';
      pc.className = pc.className.replace(/\b(ok|accion|riesgo)\b/g, '').trim() + ' '
        + (modo === 'claude' ? 'accion' : modo === 'parado' ? 'riesgo' : 'ok');
    }
    pintarAvisoCodigo(e);
    pintarAvisoConexion(e);
    const pa = $('#placa-aparato');
    if (pa) {
      const d = e.dispositivo || {};
      // En reposo, aunque la conexión siga abierta: la imagen está congelada.
      pa.textContent = (d.tipo === 'simulador' ? 'Simulador' : 'JetKVM') +
        (d.mac === 'reposo' ? ' · Mac en reposo' : d.conectado ? ' · ' + (d.resolucion || 'conectado') : ' · sin conexión');
      pa.className = 'placa ' + (d.mac === 'reposo' ? 'accion' : d.conectado ? 'ok' : 'riesgo');
      pa.title = pa.textContent + (d.firmware ? ' · firmware ' + d.firmware : '');
      const pant = $('#pantalla');
      const conectado = d.conectado ? 'si' : 'no';
      if (pant && pant.dataset.conectado !== conectado) {
        pant.dataset.conectado = conectado;
        if (window.PuenteDirecto) window.PuenteDirecto.conectado(d.conectado);
        if (window.PuenteRegion) window.PuenteRegion();
      }
    }
    // El vídeo directo puede llegar después de cargar la página (el aparato conectó
    // luego) o volver tras perderlo: `abrir` no hace nada si ya está abierto o si
    // este navegador no puede.
    const pv = $('#pantalla');
    if (pv && e.video) {
      pv.dataset.video = e.video;
      if (window.PuenteDirecto && e.video === 'h264') window.PuenteDirecto.abrir();
    }
    const ce = $('#control-estado');
    if (ce) {
      ce.textContent = TEXTO_CONTROL[modo][0];
      ce.className = 'control-estado ' + modo;
      let ayuda = TEXTO_CONTROL[modo][1];
      // Entre una tarea y la siguiente del mismo encargo (C-0486): la lectura o el
      // tramo acabó, pero el Mac aún no es suyo. Que no se ponga a corregir.
      if (modo === 'claude' && !e.tarea && (e.claude || {}).estado === 'trabajando') {
        ayuda = 'Claude sigue con el control hasta que termine el encargo: no toques el Mac todavía, aunque ya haya acabado una lectura o un tramo. Te lo devuelve al terminar o si te pregunta algo; para usarlo antes, «Usar el Mac desde aquí» se lo quita.';
      }
      if (modo === 'claude' && e.control.caduca) ayuda += ' Si no hace nada, vuelve a ti a las ' + hora(e.control.caduca).slice(0, 5) + '.';
      const motivo = modo === 'libre' ? e.control.motivo || '' : '';
      if (motivo.startsWith('volvió')) ayuda = 'El control ' + motivo + '.';
      // Sin hooks de Claude, cada tarea lo devuelve al acabar («terminó de escribir: …»).
      if (motivo.startsWith('terminó')) ayuda = 'Claude ' + motivo + '.';
      // El final del encargo, una pregunta de Claude o un encargo cortado con Esc.
      if (motivo.startsWith('Claude ')) ayuda = motivo + '.';
      if (motivo.startsWith('el encargo anterior')) ayuda = 'El' + motivo.slice(2) + '.';
      $('#control-ayuda').textContent = ayuda;
      $('#boton-dar').hidden = modo === 'claude';
      $('#boton-retomar').hidden = modo !== 'claude';
    }
    const sigue = $('#escrito-claude-sigue');
    if (sigue) sigue.hidden = modo !== 'claude';
    const t = $('#tarea');
    if (t) t.textContent = e.tarea ? '⏵ ' + e.tarea + (e.progreso ? ' · ' + e.progreso : '') : '';
    pintarClaude(e.claude || {});
    pintarConversacion(e);
    if (window.PuenteReunion && e.reunion) window.PuenteReunion(e.reunion);
    if (e.jiggler_texto) pintarJiggler(((e.dispositivo || {}).jiggler || {}).encendido, e.jiggler_texto);
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

  // ── tras actualizar: reiniciar el puente y reabrir la conversación ──────
  // Dos pasos con botón, sin comandos (C-0470, decisión 446 del hub). El
  // comando sólo donde el botón no vale: sin systemd (`reinicio` «a_mano»), o
  // con el programa de antes, cuyo /api/estado no trae `reinicio` (y su ruta
  // da 404: ahí se enseña también, esa vez).
  const avisoCodigo = $('#aviso-codigo');
  let reiniciando = false;   // mientras, el sondeo no repinta el aviso
  let reabriendo = false;    // ídem mientras pregunta y reabre: no vuelve a habilitar el botón
  let sinBoton = false;      // la ruta no existía: el comando, hasta que corra el nuevo
  let eraViejo = false;
  function decirCodigo(texto) {
    const p = $('#codigo-estado');
    p.hidden = !texto;
    p.textContent = texto || '';
  }
  function pintarAvisoCodigo(e) {
    if (!avisoCodigo || reiniciando || reabriendo) return;
    const nuevas = 'reinicio' in e;
    const conv = e.conversacion;
    const reabrir = nuevas && !!(conv && conv.herramientas_viejas);
    if (eraViejo && !e.codigo_viejo) { sinBoton = false; decirCodigo(''); }
    eraViejo = !!e.codigo_viejo;
    avisoCodigo.hidden = !e.codigo_viejo && !reabrir;
    if (avisoCodigo.hidden) return;
    const comando = e.codigo_viejo && (!nuevas || e.reinicio !== 'boton' || sinBoton);
    $('[data-codigo="comando"]', avisoCodigo).hidden = !comando;
    // Sin systemd, tras reiniciarlo a mano, Reabrir sí tiene botón.
    $('[data-codigo="pasos"]', avisoCodigo).hidden = comando;
    $('#codigo-titulo').textContent = e.codigo_viejo ? 'El puente se actualizó, pero sigue con el código de antes.'
      : 'Claude sigue con las herramientas de antes de actualizar.';
    $('[data-paso="reiniciar"]', avisoCodigo).hidden = !e.codigo_viejo;
    $('[data-paso="reabrir"]', avisoCodigo).hidden = !reabrir;
    // Primero el puente: unas herramientas nuevas contra el puente viejo no se entenderían.
    const b1 = $('#boton-reiniciar'), b2 = $('#boton-reabrir');
    b1.className = 'cta';
    b2.className = e.codigo_viejo ? '' : 'cta';
    b2.disabled = !!e.codigo_viejo;
    b2.title = e.codigo_viejo ? 'Después de reiniciar el puente' : '';
  }

  // Pregunta el estado cada segundo hasta que `cumple` o pasa el tope. Mientras
  // el puente para y arranca no contesta: eso no es un fallo, se sigue.
  async function esperarEstado(cumple, tope) {
    const fin = Date.now() + tope;
    while (Date.now() < fin) {
      try { if (cumple(await api('/api/estado'))) return true; } catch (e) { /* reiniciándose */ }
      await new Promise((r) => setTimeout(r, 1000));
    }
    return false;
  }

  // Tras pedir el reinicio: «nuevo» en cuanto contesta otro `arrancado`;
  // «igual» si pasados 15 s sigue contestando el mismo (systemd no lo
  // reinició: no hay por qué tener la página cortada los dos minutos); null si
  // en dos minutos no vuelve. Parar dura 5 s como mucho, y mientras para y
  // arranca no contesta: el mismo `arrancado` a los 15 s es que no se paró.
  async function esperarReinicio(antes) {
    const desde = Date.now();
    while (Date.now() - desde < 120000) {
      try {
        const e = await api('/api/estado');
        if (e.arrancado && e.arrancado !== antes) return 'nuevo';
        if (Date.now() - desde > 15000) return 'igual';
      } catch (e) { /* reiniciándose */ }
      await new Promise((r) => setTimeout(r, 1000));
    }
    return null;
  }

  async function reiniciarPuente() {
    if (reiniciando) return;
    reiniciando = true;
    const boton = $('#boton-reiniciar');
    boton.disabled = true;
    decirCodigo('Preparando el reinicio…');
    cortar();
    // El mando de esta página se acaba de cerrar: hasta que el puente lo vea,
    // diría que se está usando el Mac desde la pantalla.
    await esperarEstado((e) => !e.mando, 5000);
    let r = null, datos = null;
    try {
      r = await fetch('/api/reiniciar', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' });
      try { datos = await r.json(); } catch (e) { datos = null; }
    } catch (e) { r = null; }
    if (r && r.ok) {
      decirCodigo('Reiniciando el puente… La página vuelve sola en unos segundos.');
      const quedo = await esperarReinicio(datos && datos.arrancado);
      if (quedo === 'nuevo') {
        location.reload();
        return;
      }
      decirCodigo(quedo === 'igual'
        ? 'No se reinició (mira el registro del servicio: «bash scripts/servicio.sh registro», en la carpeta del '
          + 'puente). Sigue en marcha con el código de antes.'
        : 'El puente no ha vuelto en dos minutos. Recarga la página; si sigue sin contestar, '
          + '«bash scripts/servicio.sh estado», en la carpeta del puente, dice qué le pasa.');
    } else if (r && (r.status === 404 || r.status === 405)) {
      sinBoton = true;
      decirCodigo('Este puente aún corre el programa de antes de este botón: reinícialo esta vez con el comando de '
        + 'arriba. Desde la próxima, ya es un botón.');
    } else {
      decirCodigo((datos && datos.detail) || (r ? 'No se pudo reiniciar (HTTP ' + r.status + ').' : 'El puente no contesta.'));
    }
    reiniciando = false;
    boton.disabled = false;
    reanudar();
    sondear();
  }

  async function reabrirConversacion() {
    if (reabriendo) return;
    reabriendo = true;
    const boton = $('#boton-reabrir');
    boton.disabled = true;
    try {
      const d = await api('/api/conversaciones');
      if (!d.actual) {
        fugaz('No hay una conversación abierta en la lista del puente: abre una con «Nueva».', true);
      } else {
        const c = await cambiarConversacion('/api/conversaciones/' + d.actual.id + '/abrir', {});
        if (c) {
          fugaz('Reabierta: ' + c.nombre + '. Claude ya tiene las herramientas nuevas.');
          if (window.PuenteTerminal && window.PuenteTerminal.reenganchar) window.PuenteTerminal.reenganchar();
        }
      }
    } catch (e) {
      fugaz(e.message, true);
    }
    reabriendo = false;
    boton.disabled = false;
    sondear();
  }
  if (avisoCodigo) {
    $('#boton-reiniciar').addEventListener('click', reiniciarPuente);
    $('#boton-reabrir').addEventListener('click', reabrirConversacion);
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
    const img = $('.superficie:not([hidden])', contenedor) || $('img', contenedor);
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
    // Despertar y el jiggler son del aparato (C-0463): no piden el control,
    // porque los pulsa la persona; para Claude, despertar sí lo pide.
    if ('despertar' in d) {
      const texto = b.textContent;
      b.disabled = true;
      b.textContent = 'Despertando…';
      try {
        const r = await accion(() => api('/api/despertar', {}));
        fugaz(r.texto, !r.despierto);
        // Sin recargar: cortaría el mando y el directo. El sondeo quita el aviso.
        if (r.despierto) sondear();
      } catch (e) { /* ya lo dijo accion */ } finally { b.disabled = false; b.textContent = texto; }
      return;
    }
    if (b.id === 'jiggler') {
      const encender = b.getAttribute('aria-pressed') !== 'true';  // lo que se ve, y se manda explícito
      b.disabled = true;
      try {
        const r = await accion(() => api('/api/jiggler', { encendido: encender }));
        pintarJiggler(r.jiggler && r.jiggler.encendido, r.texto, true);
        fugaz(encender ? 'Jiggler encendido (' + r.texto + '). Lo hace el JetKVM: sigue aunque cierres el puente.' : 'Jiggler apagado.');
      } catch (e) { /* ya lo dijo accion */ } finally { b.disabled = false; }
      return;
    }
    if ('copiarDiagnostico' in d) {
      b.disabled = true;
      // Con la promesa dentro de ClipboardItem, el portapapeles se pide en el
      // mismo clic: tras esperar a la red, Safari y Firefox ya no lo dan.
      const pedido = api('/api/diagnostico').then((r) => r.texto);
      try {
        if (window.ClipboardItem && navigator.clipboard.write) {
          await navigator.clipboard.write([new ClipboardItem({ 'text/plain': pedido.then((t) => new Blob([t], { type: 'text/plain' })) })]);
        } else {
          await navigator.clipboard.writeText(await pedido);
        }
        fugaz('Diagnóstico copiado: pégalo al final de lo que cuentes en el hub. Léelo antes: será público.');
      } catch (e) {
        fugaz('No pude copiarlo: en una terminal, «puente-kvm diagnostico» lo escribe entero.', true);
      } finally { b.disabled = false; }
      return;
    }
    if ('reconectar' in d) {
      // Todos los «Reconectar» a la vez (el panel tiene dos): uno pulsado no deja otro en marcha.
      const botones = $$('[data-reconectar]');
      for (const r of botones) {
        if (!r.dataset.texto) r.dataset.texto = r.textContent;
        r.disabled = true;
        r.textContent = 'Reconectando…';
      }
      try {
        const r = await accion(() => api('/api/reconectar', {}));
        fugaz(r.error_conexion ? 'No conecta: ' + r.error_conexion : 'Conectado. El control vuelve a ti.', !!r.error_conexion);
        // En el panel lo pinta el sondeo, sin recargar (C-0477); en Ajustes, como siempre.
        if ($('#aviso-conexion')) await sondear();
        else setTimeout(() => location.reload(), r.error_conexion ? 2500 : 900);
      } catch (e) { /* ya lo dijo accion */ } finally {
        for (const r of botones) { r.disabled = false; r.textContent = r.dataset.texto; }
      }
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

  // ── el vídeo directo (C-0469, decisión 449 del hub) ─────────────────────
  // Con el JetKVM, la pantalla es su vídeo H.264 tal como llega (/ws/pantalla),
  // decodificado aquí con WebCodecs y pintado en un canvas, como en su web: sin
  // recomprimir nada en la PC. Las imágenes (/api/pantalla.mjpg) se ven hasta que
  // llega el primer fotograma y quedan de reserva: el simulador, un navegador sin
  // WebCodecs, un códec que este navegador no sabe, un decodificador que falla o
  // un puente que dice que no.
  const Directo = (() => {
    const img = $('#directo'), lienzo = $('#directo-video'), pant = $('#pantalla');
    if (!img || !lienzo || !pant) return null;
    const ctx = lienzo.getContext('2d');
    let fuente = img.getAttribute('src');  // las imágenes que tocan (las cambia el zoom)
    let ws = null, decod = null, codec = '', enVideo = false, esperaClave = true;
    let rendido = false, espera = 2000, reintento = 0;
    let configurando = null, enCola = [];  // lo que llega mientras se mira si se sabe decodificar
    const medida = { pintados: 0, descartes: 0, bytes: 0, desde: performance.now() };
    const sabe = () => typeof window.VideoDecoder === 'function' && window.isSecureContext;

    function cerrarVideo() {
      if (ws) { const v = ws; ws = null; v.onclose = null; try { v.close(); } catch (e) { /* ya cerrado */ } }
      if (decod) { try { decod.close(); } catch (e) { /* ya cerrado */ } decod = null; }
      codec = '';
      enCola = [];
      clearTimeout(reintento);
    }
    // Enseñar las imágenes sin cerrar el vídeo: el aparato se desconectó y lo que
    // queda en el canvas es el último fotograma, no el directo. Las imágenes dicen
    // qué pasa («Sin imagen del aparato: …»); al volver, el primer fotograma nuevo
    // devuelve el canvas.
    function verImagenes() {
      if (!enVideo) return;
      enVideo = false;
      lienzo.hidden = true;
      img.hidden = false;
      if (cortado) img.dataset.directo = fuente; else img.setAttribute('src', fuente);
      if (window.PuenteRegion) window.PuenteRegion();
    }
    // `definitivo`: este navegador no puede (sin WebCodecs, códec que no sabe, un
    // decodificador que falla) o el puente no lo da: no se vuelve a pedir hasta
    // recargar. Si no, sólo se perdió ahora, y se vuelve a pedir.
    function aImagenes(motivo, definitivo) {
      cerrarVideo();
      if (definitivo) rendido = true;
      if (motivo) console.info('Puente: la pantalla va por imágenes:', motivo);
      verImagenes();
    }
    function reintentar() {
      clearTimeout(reintento);
      reintento = setTimeout(abrir, espera);
      espera = Math.min(espera * 2, 30000);
    }
    function aVideo() {
      enVideo = true;
      espera = 2000;
      lienzo.hidden = false;
      img.hidden = true;
      img.removeAttribute('src');  // que el puente deje de hacer imágenes que nadie mira
      delete img.dataset.directo;
      if (window.PuenteRegion) window.PuenteRegion();
    }
    // El puente sólo lo manda al empezar y cuando cambia el SPS (otra resolución,
    // otro perfil): se reconfigura siempre, y lo siguiente que llega es su clave.
    function configurar(d) {
      // La primera clave llega justo detrás de esto: se guarda en vez de tirarla y
      // esperar a la siguiente.
      configurando = configurarYa(d).catch((e) => aImagenes('no se pudo configurar: ' + e.message, true)).finally(() => {
        configurando = null;
        const cola = enCola; enCola = [];
        for (const b of cola) trama(b);
      });
    }
    async function configurarYa(d) {
      const config = { codec: d.codec, optimizeForLatency: true };  // sin description: llega en Annex B
      let vale = false;
      try { vale = (await VideoDecoder.isConfigSupported(config)).supported; } catch (e) { vale = false; }
      if (!ws) return;  // se cortó mientras se preguntaba
      if (!vale) return aImagenes('este navegador no decodifica ' + d.codec, true);
      if (!decod || decod.state === 'closed') {
        decod = new VideoDecoder({
          output: (frame) => {
            try {
              if (lienzo.width !== frame.displayWidth || lienzo.height !== frame.displayHeight) {
                lienzo.width = frame.displayWidth; lienzo.height = frame.displayHeight;
              }
              ctx.drawImage(frame, 0, 0);
            } finally {
              frame.close();  // si no, el decodificador se queda sin fotogramas y se para
            }
            medida.pintados++;
            if (!enVideo && pant.dataset.conectado !== 'no') aVideo();
          },
          error: (e) => aImagenes('el decodificador falló: ' + (e && e.message), true),
        });
      }
      try {
        decod.configure(config);
      } catch (e) {
        return aImagenes('no se pudo configurar el decodificador: ' + e.message, true);
      }
      codec = d.codec;
      esperaClave = true;
    }
    function trama(buf) {
      if (configurando) { if (enCola.length < 30) enCola.push(buf); return; }
      medida.bytes += buf.byteLength;
      if (!decod || decod.state !== 'configured') return;
      const vista = new DataView(buf);
      const clave = (vista.getUint8(0) & 1) === 1;
      if (esperaClave && !clave) return;
      // Si el decodificador se atrasa, lo que espera ya es viejo: hasta la siguiente clave.
      if (!clave && decod.decodeQueueSize > 2) { esperaClave = true; medida.descartes++; return; }
      const marca = Number(vista.getBigUint64(1));
      try {
        decod.decode(new EncodedVideoChunk({ type: clave ? 'key' : 'delta', timestamp: Math.round(marca * 1e6 / 90000),
          data: new Uint8Array(buf, 9) }));
        esperaClave = false;
      } catch (e) {
        aImagenes('no se pudo decodificar: ' + e.message, true);
      }
    }
    function abrir() {
      if (ws || rendido || cortado || pant.dataset.video !== 'h264') return;
      clearTimeout(reintento);
      if (!sabe()) { rendido = true; return; }
      const v = new WebSocket((location.protocol === 'https:' ? 'wss://' : 'ws://') + location.host + '/ws/pantalla');
      v.binaryType = 'arraybuffer';
      ws = v;
      v.onmessage = (m) => {
        if (ws !== v) return;
        if (typeof m.data !== 'string') return trama(m.data);
        let d = {}; try { d = JSON.parse(m.data); } catch (e) { return; }
        if (d.no) {
          aImagenes(d.no, !d.otra_vez);
          if (d.otra_vez) reintentar();
        } else if (d.codec) configurar(d);
      };
      // Se cortó sin pedirlo (el puente se reinicia): las imágenes mientras
      // tanto, y se vuelve a intentar, cada vez más despacio.
      v.onclose = () => {
        if (ws !== v) return;
        ws = null;
        aImagenes('se cortó el vídeo directo');
        reintentar();
      };
    }
    alCortar.push([cerrarVideo, abrir]);
    abrir();
    return {
      superficie: () => (enVideo ? lienzo : img),
      esSuperficie: (el) => el === img || el === lienzo,
      // El zoom pide otras imágenes: con el vídeo, sólo se apunta para la reserva.
      fuente(src) {
        fuente = src;
        if (enVideo) return;
        if (cortado) img.dataset.directo = src;
        else if (img.getAttribute('src') !== src) img.setAttribute('src', src);
      },
      modo: () => (enVideo ? 'h264' : 'mjpeg'),
      abrir,
      // Lo dice el sondeo del estado: sin aparato, las imágenes (que dicen por qué).
      conectado(si) { if (!si) verImagenes(); },
      medida,
    };
  })();
  window.PuenteDirecto = Directo;

  // «?medir=1» (docs/pruebas-con-el-aparato.md): lo que pinta el directo y el
  // retraso del puntero, medidos aquí, en el navegador. El retraso es aproximado:
  // de mandar un movimiento a que cambie la pantalla donde tiene que aparecer el
  // puntero del Mac (o algo más que se mueva ahí mismo).
  const Medir = (() => {
    const placa = $('#medida');
    if (!Directo || !placa || !new URLSearchParams(location.search).has('medir')) return null;
    placa.hidden = false;
    const caja = document.createElement('canvas');
    caja.width = caja.height = 16;
    const c2 = caja.getContext('2d', { willReadFrequently: true });
    const retrasos = [];
    let pendiente = null, antes = { p: 0, t: performance.now() };
    function region(x, y) {
      const s = Directo.superficie(), pant = $('#pantalla');
      const ancho = s.tagName === 'CANVAS' ? s.width : s.naturalWidth;
      if (!ancho) return null;
      const e = ancho / (Number(pant.dataset.ancho) || 1920);
      try {
        c2.clearRect(0, 0, 16, 16);
        c2.drawImage(s, x * e, y * e, 16 * e, 16 * e, 0, 0, 16, 16);
        return c2.getImageData(0, 0, 16, 16).data;
      } catch (err) { return null; }
    }
    function distinta(a, b) {
      let d = 0;
      for (let i = 0; i < a.length; i += 4) d += Math.abs(a[i] - b[i]) + Math.abs(a[i + 1] - b[i + 1]) + Math.abs(a[i + 2] - b[i + 2]);
      return d / (a.length / 4) > 24;
    }
    const pct = (p) => { const o = [...retrasos].sort((a, b) => a - b); return o.length ? Math.round(o[Math.min(o.length - 1, Math.round(p * (o.length - 1)))]) : '—'; };
    function cuadro() {
      if (pendiente) {
        const ahora = region(pendiente.x, pendiente.y);
        if (ahora && distinta(ahora, pendiente.r)) {
          retrasos.push(performance.now() - pendiente.t);
          if (retrasos.length > 50) retrasos.shift();
          pendiente = null;
        } else if (performance.now() - pendiente.t > 2000) pendiente = null;
      }
      requestAnimationFrame(cuadro);
    }
    requestAnimationFrame(cuadro);
    setInterval(() => {
      const m = Directo.medida, t = performance.now(), s = (t - antes.t) / 1000;
      const fps = Directo.modo() === 'h264' ? (m.pintados - antes.p) / s : null;
      antes = { p: m.pintados, t };
      placa.textContent = (Directo.modo() === 'h264' ? 'vídeo H.264 · ' + fps.toFixed(1) + ' fotogramas/s · '
        + (m.bytes * 8 / 1e6 / ((t - m.desde) / 1000)).toFixed(1) + ' Mbit/s · ' + m.descartes + ' descartes'
        : 'imágenes (MJPEG)') + ' · puntero p50 ' + pct(0.5) + ' ms, p95 ' + pct(0.95) + ' ms (' + retrasos.length + ')';
    }, 1000);
    return {
      // Cada movimiento mandado sustituye al que aún no se vio: un punto de paso
      // puede no salir en ningún fotograma, y se mide hasta donde paró la mano.
      movido(p) {
        const r = region(p.x, p.y);
        pendiente = r ? { x: p.x, y: p.y, t: performance.now(), r } : null;
      },
    };
  })();

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
  if (pantallaMando && botonUsar && Directo) {
    const casillaCtrl = $('#mando-ctrl');
    const ayuda = $('#mando-ayuda');
    const ayudaQuieto = ayuda.textContent;
    const extras = $$('[data-mando-atajo], #mando-pegar, #mando-teclado-caja');
    const teclado = $('#mando-teclado');
    let pegadoConAcentos = false;
    let ws = null, activo = false, botones = 0, acumulado = 0, movido = null, cuadroMov = 0;
    try { casillaCtrl.checked = localStorage.getItem('puente-mando-ctrl') !== 'no'; } catch (e) { /* sin almacenamiento */ }
    casillaCtrl.addEventListener('change', () => {
      try { localStorage.setItem('puente-mando-ctrl', casillaCtrl.checked ? 'si' : 'no'); } catch (e) { /* idem */ }
    });

    // Lo que se hace antes de que abra (un clic justo después de «Usar el Mac»)
    // espera a que abra, en vez de perderse.
    const antesDeAbrir = [];
    const enviar = (o) => {
      if (ws && ws.readyState === 1) ws.send(JSON.stringify(o));
      else if (ws && ws.readyState === 0 && antesDeAbrir.length < 200) antesDeAbrir.push(o);
    };
    const punto = (e) => {
      const r = Directo.superficie().getBoundingClientRect();
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
      antesDeAbrir.length = 0;
      v.onopen = () => { if (ws === v) for (const o of antesDeAbrir.splice(0)) v.send(JSON.stringify(o)); };
      v.onmessage = (m) => {
        let d = {}; try { d = JSON.parse(m.data); } catch (e) { return; }
        if (d.no) parar(d.no);
        // Al abrir, si Claude tenía el control, el puente lo retoma (C-0484).
        if (d.aviso) { fugaz(d.aviso); sondear(); }
        if (d.espera) fugaz(d.espera);
        // Lo que no es ASCII depende de la fuente de entrada del Mac: si no es
        // la elegida, sale otro carácter y sólo ella lo ve (C-0466).
        if (d.hecho === 'pegar' && pegadoConAcentos) {
          fugaz('Tecleado con el teclado «' + (d.teclado || teclado.selectedOptions[0].textContent) + '». Si los acentos salieron cambiados, el Mac usa otro: cámbialo en «Teclado del Mac».');
        }
      };
      v.onclose = () => { if (ws === v) parar('Se cortó la conexión con el puente.'); };
      activo = true;
      pantallaMando.classList.add('usando');
      botonUsar.textContent = 'Dejar de usar';
      extras.forEach((b) => { b.hidden = false; });
      ayuda.textContent = 'Usando el Mac: lo que teclees y hagas sobre la imagen va al Mac. Para parar, «Dejar de usar» o un clic fuera de la imagen.';
    }
    botonUsar.addEventListener('click', () => (activo ? parar() : cortado ? null : empezar()));
    alCortar.push([() => parar(), () => {}]);  // al reanudar, la persona lo vuelve a pedir si quiere

    // Sólo lo que pasa sobre la imagen (o el vídeo): con zoom, la caja tiene
    // márgenes negros y barras de desplazamiento, y un clic ahí llegaría al Mac
    // como clic en el borde. El movimiento, una vez por cuadro y el último punto:
    // con un tope de 30 ms se perdía el último, y el puntero se quedaba antes de
    // donde paró la mano (C-0469).
    pantallaMando.addEventListener('mousemove', (e) => {
      if (!activo || !Directo.esSuperficie(e.target)) return;
      movido = punto(e);
      if (cuadroMov) return;
      cuadroMov = requestAnimationFrame(() => {
        cuadroMov = 0;
        if (!movido || !activo) return;
        enviar({ t: 'raton', ...movido, b: botones });
        if (Medir) Medir.movido(movido);
        movido = null;
      });
    });
    pantallaMando.addEventListener('mousedown', (e) => {
      if (!activo || !Directo.esSuperficie(e.target)) return;
      e.preventDefault();
      movido = null;  // el clic ya lleva su punto
      // Cancelarlo (para no arrastrar la imagen) también deja el foco donde
      // estaba: en la terminal de Claude, que es de la página de fuera, lo
      // tecleado seguía yendo a ella (20-nov). Se trae aquí a mano.
      if (document.activeElement !== pantallaMando || !document.hasFocus()) pantallaMando.focus({ preventScroll: true });
      botones |= bitDe(e.button);
      enviar({ t: 'raton', ...punto(e), b: botones });
    });
    window.addEventListener('mouseup', (e) => {
      if (!activo || !botones) return;
      movido = null;
      botones &= ~bitDe(e.button);
      enviar({ t: 'raton', ...punto(e), b: botones });
    });
    pantallaMando.addEventListener('contextmenu', (e) => { if (activo) e.preventDefault(); });
    // Como la web del JetKVM (useMouse.ts): cada evento de la rueda cuenta uno, y
    // de 100 en adelante, uno por cada 100. Un touchpad o una rueda suave mandan
    // muchos y pequeños: contar sólo cada 100 píxeles la dejaba lentísima (20-nov).
    pantallaMando.addEventListener('wheel', (e) => {
      if (!activo) return;
      e.preventDefault();
      if (!e.deltaY) return;
      acumulado += Math.abs(e.deltaY) >= 100 ? e.deltaY / 100 : Math.sign(e.deltaY);
      const pasos = Math.trunc(acumulado);
      if (pasos) {
        enviar({ t: 'rueda', pasos });  // positivo: el contenido baja
        acumulado -= pasos;
      }
    }, { passive: false });
    // Un clic fuera de la imagen y de sus barras (la del mando y la del zoom) suelta el Mac.
    document.addEventListener('mousedown', (e) => {
      if (activo && !e.target.closest('#pantalla, #mando, .zoom, #ampliar, #reunion, .velo')) parar();
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
      if (!texto) texto = await pedir('Texto para teclear en el Mac', '', { max: 5000, si: 'Teclear', nota: 'Se teclea letra a letra con el teclado del Mac que eliges junto a «Pegar texto».' });
      if (!texto) return;
      pegadoConAcentos = /[^\x00-\x7f]/.test(texto);
      enviar({ t: 'pegar', texto });
    });
    teclado.addEventListener('change', async () => {
      const antes = teclado.dataset.antes || teclado.querySelector('[selected]')?.value || teclado.value;
      try {
        await api('/api/ajustes', { perfil: { distribucion: teclado.value } });
        teclado.dataset.antes = teclado.value;
        fugaz('Teclado del Mac: ' + teclado.selectedOptions[0].textContent);
      } catch (e) {
        teclado.value = antes;
        fugaz('No se cambió el teclado: ' + e.message, true);
      }
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
      // Al reanudar, la de ahora; con el vídeo, la reserva (el vídeo ya llega entero).
      const src = '/api/pantalla.mjpg?ancho=' + pedir;
      if (Directo) Directo.fuente(src);
      else if (cortado) img.dataset.directo = src;
      else if (img.getAttribute('src') !== src) img.setAttribute('src', src);
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
        if (clave === 'retardo_tecla_ms' || clave === 'retardo_video_ms') v = Number(v);
        if (clave === 'reservadas') v = v.split(',').map((x) => x.trim()).filter(Boolean);
        (datos[seccion] = datos[seccion] || {})[clave] = v;
      }
      const r = await accion(() => api('/api/ajustes', datos), 'Ajustes guardados');
      if (r.error_conexion) fugaz('No conecta: ' + r.error_conexion, true);
      setTimeout(() => location.reload(), 800);
    });
    // Una medida verificada se activa aquí, con un clic de la persona: nunca sola al verificarse.
    for (const b of $$('[data-usar-teclado]', document)) {
      b.addEventListener('click', async () => {
        try {
          await accion(() => api('/api/ajustes', { perfil: { distribucion: b.dataset.usarTeclado } }),
            'Teclado del Mac: la medida está en uso');
          setTimeout(() => location.reload(), 800);
        } catch (e) { /* `accion` ya lo dijo */ }
      });
    }
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

  // ── una reunión (C-0461): lo que suena en el Mac y su pantalla ──────────
  // La empieza y la para la persona con este botón, y nadie más.
  const botonReunion = $('#reunion');
  if (botonReunion) {
    const placa = $('#reunion-placa');
    const aviso = $('#reunion-aviso');
    let reunion = { grabando: false }, recibida = Date.now(), esperando = false;
    const reloj = (s) => {
      const h = Math.floor(s / 3600), m = Math.floor(s / 60) % 60, dd = (n) => String(n).padStart(2, '0');
      return (h ? h + ':' + dd(m) : m) + ':' + dd(s % 60);
    };
    const avisar = (texto, clase) => {
      aviso.hidden = !texto;
      aviso.textContent = texto || '';
      aviso.className = 'aviso aviso-reunion' + (clase ? ' ' + clase : '');
    };
    function pintar() {
      const g = reunion.grabando;
      botonReunion.disabled = esperando;
      botonReunion.textContent = esperando ? (g ? 'Guardando…' : 'Conectando el sonido…')
        : g ? '■ Salí de la reunión' : '● Estoy en reunión';
      placa.hidden = !g;
      if (!g) {
        const u = reunion.ultima;
        if (!u) return avisar('');
        return avisar('Reunión guardada (' + reloj(u.segundos) + ', ' + u.fotos + (u.fotos === 1 ? ' foto' : ' fotos') + ' de la pantalla). En el hub, con el Puente KVM '
          + 'encendido en Ajustes, Reuniones la transcribe y la resume sola.'
          + (u.con_sonido ? '' : ' Ojo: no llegó nada de sonido del Mac.'), u.con_sonido ? 'ok' : 'riesgo');
      }
      // Entre una consulta y la siguiente, el reloj sigue en la pantalla.
      const pasado = Math.floor((Date.now() - recibida) / 1000);
      const mudo = reunion.sin_sonido_s + pasado;
      placa.textContent = 'Grabando ' + reloj(reunion.segundos + pasado);
      if (reunion.error) return avisar(reunion.error, 'riesgo');
      // En silencio el JetKVM no manda nada: no se distingue de la salida mal
      // elegida, así que se dice lo que hay y qué mirar, no que algo esté mal.
      if (mudo >= 30) {
        return avisar('No ha llegado sonido del Mac en ' + reloj(mudo) + '. Si alguien está hablando: en el Mac, '
          + 'Ajustes del Sistema → Sonido → Salida → el dispositivo USB del JetKVM (no «JetKVM v1», que es la pantalla).', 'riesgo');
      }
      avisar('Se graba lo que suena en el Mac y su pantalla cuando cambia. Tu voz no se graba: entra al Mac por su micrófono.');
    }
    window.PuenteReunion = (r) => { if (!esperando) { reunion = r; recibida = Date.now(); pintar(); } };
    setInterval(pintar, 1000);
    botonReunion.addEventListener('click', async () => {
      if (esperando) return;
      esperando = true;
      pintar();
      try {
        reunion = reunion.grabando ? { grabando: false, ultima: await api('/api/reunion/parar', {}) }
          : await api('/api/reunion/empezar', {});
        recibida = Date.now();
      } catch (e) {
        fugaz(e.message, true);
      }
      esperando = false;
      pintar();
    });
  }

  window.PuenteUI = { api, confirmar, pedir, fugaz, cambiarConversacion, cortar, reanudar };
})();
