/* El chat del secretario (definición 2.x, 5.2 y 6.x; C-0160 lo saca a
 * componente): en /secretario y, en el hub del dueño, en el panel que le
 * sigue por todas las pantallas. Necesita el marcado de
 * `_chat_secretario.html` y `formato-chat.js` antes.
 *
 * Lo que se escribe o se dicta va a `/api/secretario/mensaje`, que sólo lo
 * deja en la base: lo contesta `hub-secretario` (decisión 298). Aquí se
 * pregunta cada poco hasta ver la respuesta.
 *
 * La voz, de ida y de vuelta:
 * - **Hablar** graba en el navegador y transcribe EN CASA (`/api/voz`, el
 *   mismo Whisper del dictado de la terminal).
 * - **Leer en voz alta** usa la voz del propio navegador (`speechSynthesis`),
 *   frase a frase según el secretario la escribe (C-0155): el `locutor` decide
 *   qué toca decir y `VOZ` es sólo cómo suena.
 */
(() => {
  const chat = document.getElementById('sec-chat');
  if (!chat) return;
  const formulario = document.getElementById('sec-escribir');
  const cuadro = document.getElementById('sec-texto');
  const estado = document.getElementById('estado-sec');
  const botonHablar = document.getElementById('sec-hablar');
  const enVoz = document.getElementById('sec-en-voz');
  const manosLibres = document.getElementById('sec-manos-libres');
  const botonModo = document.getElementById('sec-modo-voz');
  const panelVoz = document.getElementById('sec-panel-voz');
  const vozEstado = document.getElementById('sec-voz-estado');
  const vozPausa = document.getElementById('sec-voz-pausa');
  const orbe = document.getElementById('sec-orbe-voz');
  // El modo inglés (C-0159): lo guarda el servidor; aquí sólo cambia el idioma
  // de la voz y de la transcripción.
  const botonIngles = document.getElementById('sec-modo-ingles');
  const enIngles = () => !!botonIngles && botonIngles.dataset.activo === '1';
  if (botonIngles) botonIngles.addEventListener('click', async () => {
    const activo = !enIngles();
    try {
      const r = await fetch('/api/secretario/ingles', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ activo }),
      });
      const d = await r.json();
      if (d.ok) {
        botonIngles.dataset.activo = d.activo ? '1' : '';
        botonIngles.setAttribute('aria-pressed', d.activo ? 'true' : 'false');
        if (estado) estado.textContent = d.activo ? 'English mode: practice, no actions without your OK' : 'modo inglés quitado';
      }
    } catch (e) {
      if (estado) estado.textContent = 'no se pudo cambiar: el hub no contesta';
    }
  });
  /* Lo que el personaje necesita saber (C-0166, decisión 358): lo oye
   * avatar-secretario.js. Se cuenta lo que aquí ya se sabe —la fase de la voz,
   * su nivel, lo que trae cada sondeo—: el personaje no mide nada otra vez. */
  function contar(detalle) {
    try {
      if (typeof document.dispatchEvent === 'function' && typeof CustomEvent === 'function') {
        document.dispatchEvent(new CustomEvent('secretario:estado', { detail: detalle }));
      }
    } catch (e) { /* el personaje es adorno: el chat sigue */ }
  }
  // Cuánto se mueve el orbe (0-1): con tu voz al escuchar, con cada palabra al hablar.
  const nivel = (x) => {
    const v = Math.round(Math.max(0, Math.min(1, x)) * 100) / 100;
    if (orbe) orbe.style.setProperty('--nivel', String(v));
    contar({ nivel: v });
  };
  let pulso = null;
  function latido() {
    nivel(1);
    clearTimeout(pulso);
    pulso = setTimeout(() => nivel(0.2), 140);
  }
  // El modo voz (decisiones 314 y 317): escucha, manda al callar, lee la
  // respuesta y vuelve a escuchar. Es un MODO, como en las apps de voz: se
  // entra con su botón y dura hasta «✕». Callarse un rato o no entender una
  // frase no lo apaga — antes era una casilla que se desmarcaba sola a los 8 s
  // de silencio y el dueño no sabía en qué estaba.
  let continuo = false;
  let pausado = false;
  let silencios = 0;      // escuchas seguidas sin oír a nadie
  let candado = null;     // pantalla encendida mientras dura (Wake Lock)
  let ultimo = Number(chat.dataset.ultimo || 0);
  let esperando = false;
  // El panel trae la conversación al cargar (C-0160): esa primera vez no habla.
  let cargando = !!chat.dataset.cargar;

  const guardar = (clave, valor) => { try { localStorage.setItem(clave, valor ? '1' : ''); } catch (e) { /* sin almacenamiento */ } };
  const leerPref = (clave) => { try { return localStorage.getItem(clave) === '1'; } catch (e) { return false; } };
  if (enVoz) { enVoz.checked = leerPref('secretario.voz'); enVoz.addEventListener('change', () => guardar('secretario.voz', enVoz.checked)); }
  if (manosLibres) { manosLibres.checked = leerPref('secretario.manos'); manosLibres.addEventListener('change', () => guardar('secretario.manos', manosLibres.checked)); }

  const escapar = (s) => String(s ?? '').replace(/[&<>"']/g, c =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const formatear = window.formatearMensaje || escapar;

  function ficha(t) {
    const caja = document.createElement('div');
    caja.className = 'ficha';
    let html = `<strong>${escapar(t.titulo)}</strong>`;
    if (t.tipo === 'tabla') {
      html += '<table>';
      if (t.columnas && t.columnas.length) html += '<tr>' + t.columnas.map(c => `<th>${escapar(c)}</th>`).join('') + '</tr>';
      html += (t.filas || []).map(f => '<tr>' + f.map(x => `<td>${escapar(x)}</td>`).join('') + '</tr>').join('');
      html += '</table>';
    } else if (t.tipo === 'imagenes') {
      /* Lo que se vio (decisión 384): miniaturas que abren la imagen entera.
       * Sólo por `/intercambio/ver`, que sólo sirve raster: el servidor ya
       * descartó lo demás, y aquí se vuelve a mirar la extensión. */
      const notas = Array.isArray(t.notas) ? t.notas : [];
      html += '<div class="adjuntos imagenes">' + (Array.isArray(t.imagenes) ? t.imagenes : []).map((r, i) => {
        if (!esImagen(r)) return '';
        const nota = notas[i] ? String(notas[i]) : '';
        const ver = `/intercambio/ver/${escapar(tramos(r))}`;
        return `<figure><a href="${ver}" target="_blank" rel="noopener">`
             + `<img src="${ver}" alt="${escapar(nota || nombreDe(r))}" loading="lazy"></a>`
             + (nota ? `<figcaption>${escapar(nota)}</figcaption>` : '') + '</figure>';
      }).join('') + '</div>';
    } else {
      html += '<ul>' + (t.filas || []).map(f => `<li>${escapar(f.join(' · '))}</li>`).join('') + '</ul>';
    }
    caja.innerHTML = html;
    return caja;
  }

  /* Lo adjunto (decisión 383): vive en el intercambio, se enseña por
   * `/intercambio/ver` (sólo raster) y lo demás se baja. Cada tramo de la
   * ruta se codifica por separado: la barra separa carpetas y no se toca. */
  const tramos = (ruta) => String(ruta).split('/').map(encodeURIComponent).join('/');
  const esImagen = (ruta) => /\.(png|jpe?g|gif|webp)$/i.test(String(ruta));
  const nombreDe = (ruta) => String(ruta).split('/').pop();
  function adjuntosHtml(lista) {
    if (!Array.isArray(lista) || !lista.length) return '';
    return '<div class="adjuntos">' + lista.map(r => {
      const nombre = escapar(nombreDe(r));
      if (!esImagen(r)) return `<a class="archivo" href="/intercambio/bajar/${escapar(tramos(r))}">${nombre}</a>`;
      const ver = `/intercambio/ver/${escapar(tramos(r))}`;
      return `<a href="${ver}" target="_blank" rel="noopener"><img src="${ver}" alt="${nombre}" loading="lazy"></a>`;
    }).join('') + '</div>';
  }

  function pintar(nodo, t) {
    const aMedias = t.estado === 'escribiendo' && !!t.texto;
    nodo.className = `burbuja ${t.rol}` + (t.estado === 'error' ? ' error' : '') + (t.estado === 'escribiendo' ? ' escribiendo' : '')
                     + (aMedias ? ' a-medias' : '');
    nodo.dataset.turno = t.id;
    nodo.dataset.estado = t.estado;
    if (t.estado === 'escribiendo' && !t.texto) {
      // Lo que hace mientras tanto, dicho también aquí (C-0166): el rótulo
      // ya viene redactado por el servidor (`turno.actividad`).
      const act = t.actividad && t.actividad.estado === 'trabajando' ? t.actividad.rotulo : '';
      nodo.innerHTML = '<span class="puntos" role="img" aria-label="pensando"><i></i><i></i><i></i></span>'
                       + (act ? `<span class="que-hace">${escapar(act)}</span>` : '');
      return;
    }
    nodo.innerHTML = formatear(t.texto || '') + adjuntosHtml(t.adjuntos);
    (t.tarjetas || []).forEach(x => nodo.appendChild(ficha(x)));
    if (t.rol === 'secretario' && t.modelo) {
      const pie = document.createElement('span');
      pie.className = 'pie';
      pie.textContent = `${t.modelo.replace('claude-', '')}${t.segundos ? ` · ${t.segundos} s` : ''}`;
      nodo.appendChild(pie);
    }
  }

  // Lo que vino pintado por el servidor.
  chat.querySelectorAll('.burbuja').forEach(n => {
    let tarjetas = [];
    try { tarjetas = JSON.parse(n.dataset.tarjetas || '[]'); } catch (e) { /* tarjeta rota: se ignora */ }
    let adjuntos = [];
    try { adjuntos = JSON.parse(n.dataset.adjuntos || '[]'); } catch (e) { /* lista rota: se ignora */ }
    pintar(n, { id: n.dataset.turno, rol: n.classList.contains('dueno') ? 'dueno' : 'secretario',
                texto: n.dataset.texto, tarjetas, adjuntos, estado: n.dataset.estado,
                modelo: n.dataset.modelo, segundos: n.dataset.segundos });
  });
  const bajar = () => { chat.scrollTop = chat.scrollHeight; };
  bajar();

  function ponerTurno(t) {
    const vacio = document.getElementById('sec-vacio');
    if (vacio) vacio.remove();
    let nodo = chat.querySelector(`[data-turno="${t.id}"]`);
    const antes = nodo ? nodo.dataset.estado : null;
    if (!nodo) { nodo = document.createElement('div'); chat.appendChild(nodo); }
    pintar(nodo, t);
    const final = t.estado === 'listo' || t.estado === 'error';
    // Un turno «escribiendo» vacío también le llega si ya lo estaba leyendo:
    // es el escalado al modelo mayor, que vacía lo dicho por el menor.
    const escribe = t.estado === 'escribiendo' && (t.texto || locutor.turno() === t.id);
    // Lo que ya estaba contestado al cargar el panel no se lee otra vez.
    if (t.rol === 'secretario' && antes !== 'listo' && (final || escribe) && !(cargando && final)) {
      if (continuo && !pausado) {
        if (locutor.turno() !== t.id) {
          fase('hablando', 'te contesto… háblame para interrumpir');
          locutor.empezar(t.id, () => { soltarVigia(); if (continuo && !pausado) hablar(); });
          vigilarInterrupcion();
        }
        locutor.avanzar(t.texto, final);
      }
      else if (t.estado === 'listo' && enVoz && enVoz.checked) decir(t.texto);
    }
    bajar();
  }

  /* El globo (C-0201, decisión 379): lo que te espera y aún no has visto.
   * La cifra viene en la espera que ya trae el sondeo (`espera.asuntos`, la
   * instantánea que deja hub-secretario) y, al cargar, en la del personaje
   * (`data-espera`): no se pregunta nada aparte. Nunca avisa fuera de aquí.
   * Se llama como el bloque al que lleva (C-0231): «Tiene una sugerencia o
   * una pregunta» era un tercer nombre para lo mismo. */
  const globo = document.getElementById('sec-globo');
  function pintarGlobo(espera) {
    if (!globo) return;
    const n = Math.max(0, Math.floor(Number(espera && espera.asuntos && espera.asuntos.nuevas) || 0));
    globo.hidden = n === 0;
    const texto = globo.querySelector ? globo.querySelector('[data-globo-texto]') : null;
    if (texto && n > 0) {
      texto.textContent = `Te espera: ${n}`;
    }
  }
  /* «Esperan tu sí» (al lado) y la cifra de Pendientes se pintaron al
   * cargar: un permiso pedido a mitad de la conversación no salía hasta
   * recargar (C-0229). Cuando cambia lo que espera, se repintan esas dos
   * regiones, y sólo en su pantalla: en el panel flotante no existen. */
  let esperaVista = null;
  function seguirLaEspera(espera) {
    const firma = espera
      ? `${espera.solicitudes || 0}|${(espera.asuntos && espera.asuntos.nuevas) || 0}` : '';
    const anterior = esperaVista;
    const cambio = anterior !== null && firma !== anterior;
    esperaVista = firma;
    if (!cambio || !window.HubSinRecarga || !document.querySelector('[data-region="lado"]')) return;
    // Si no se pudo, se vuelve a intentar en el sondeo siguiente.
    HubSinRecarga.refrescar(['lado', 'sec-nav']).catch(() => { esperaVista = anterior; });
  }
  try {
    const portador = document.querySelector('[data-espera]');
    const inicial = JSON.parse((portador && portador.dataset && portador.dataset.espera) || 'null');
    pintarGlobo(inicial);
    seguirLaEspera(inicial);
  } catch (e) { pintarGlobo(null); }

  /* Pregunta por lo nuevo. Un turno «escribiendo» se vuelve a pedir hasta que
   * cambie: por eso se pide desde el último que ya está terminado. */
  async function mirar() {
    let d;
    try {
      const r = await fetch(`/api/secretario/turnos?desde=${ultimo}`, { cache: 'no-store' });
      d = await r.json();
    } catch (e) {
      if (estado) estado.textContent = 'el hub no contesta; sigo intentando…';
      contar({ red: 'caida' });
      return;
    }
    contar({ red: 'ok', turnos: d.turnos || [], ...('espera' in d ? { espera: d.espera } : {}) });
    if ('espera' in d) { pintarGlobo(d.espera); seguirLaEspera(d.espera); }
    let pendiente = false;
    for (const t of d.turnos || []) {
      ponerTurno(t);
      const abierto = t.estado === 'escribiendo' || t.estado === 'pendiente' || t.estado === 'atendiendo';
      if (abierto) pendiente = true;
      else if (!pendiente) ultimo = Math.max(ultimo, Number(t.id));
    }
    esperando = pendiente;
    if (estado && !pendiente && estado.textContent === 'pensando…') estado.textContent = '';
    if (!pendiente && continuo && panelVoz && panelVoz.dataset.fase === 'pensando') fase('', '');
  }
  // Rápido mientras se espera una respuesta; despacio el resto del tiempo
  // (una aprobación desde otro aparato también deja un turno). El rápido es
  // una cadena que se corta sola al llegar la respuesta.
  // En el modo voz, a 300 ms: es lo que tarda en empezar a leer cada frase.
  // Una sola cadena a la vez: llamarla de más no duplica el sondeo. Y la
  // arranca también quien descubre un turno abierto sin haberlo mandado (el
  // sondeo lento, desplegar el panel): un mensaje desde el teléfono se quedaba
  // aquí «pensando» para siempre, porque nadie empezaba la cadena (C-0166).
  let cadena = null;
  function seguir() {
    if (!esperando || cadena) return;
    cadena = setTimeout(() => { cadena = null; mirar().then(seguir); }, continuo ? 300 : 1500);
  }
  // En el panel plegado no se pregunta: cada sondeo abre la memoria, y en
  // todas las pestañas a la vez eso es ruido. Al desplegarlo se pone al día.
  const plegado = () => { const p = chat.dataset.cargar && document.getElementById('secretario-panel');
                          return !!p && !p.classList.contains('abierto'); };
  setInterval(() => { if (!esperando && !plegado()) mirar().then(seguir); }, 6000);
  // Al volver a la pestaña, una vez, aunque esté plegado: el personaje de una
  // pantalla abierta horas (/trabajo) no puede seguir enseñando lo de antes.
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden && !esperando && chat.dataset.cargar && !cargando) mirar().then(seguir);
  });
  const abiertos = [...chat.querySelectorAll('.burbuja')].filter(n =>
    ['escribiendo', 'pendiente', 'atendiendo'].includes(n.dataset.estado));
  esperando = abiertos.length > 0;
  // Lo que venía a medias se vuelve a pedir: `data-ultimo` es el último turno
  // pintado, y pidiendo «desde» él el que se estaba escribiendo no volvía
  // nunca y la burbuja se quedaba en «…» hasta recargar (C-0166).
  if (abiertos.length) ultimo = Math.min(ultimo, ...abiertos.map(n => Number(n.dataset.turno) - 1));
  seguir();

  /* ── lo que se adjunta (decisión 383) ──
   * Se sube al momento —pegado, soltado o elegido— y espera aquí, con su
   * miniatura, a que mandes el mensaje: lo que viaja con él son sus rutas.
   * Quitar una no la borra: es de paso y se va sola a los diez días (288). */
  const porMandar = document.getElementById('sec-adjuntos');
  const botonAdjuntar = document.getElementById('sec-adjuntar');
  const eligeArchivo = document.getElementById('sec-archivo');
  let adjuntos = [];      // { ruta, imagen }
  let subidas = [];       // las que aún no han vuelto: mandar las espera
  function pintarPorMandar() {
    if (!porMandar) return;
    porMandar.hidden = !adjuntos.length;
    porMandar.innerHTML = adjuntos.map((a, i) => {
      const nombre = escapar(nombreDe(a.ruta));
      const vista = a.imagen ? `<img src="/intercambio/ver/${escapar(tramos(a.ruta))}" alt="${nombre}">`
                             : `<span class="nombre">${nombre}</span>`;
      return `<span class="adjunto">${vista}<button type="button" class="quitar" data-quitar="${i}"`
             + ` aria-label="Quitar ${nombre}" title="Quitar">✕</button></span>`;
    }).join('');
  }
  // Devuelve '' si subió, o por qué no: mandar no sale sin lo que falló.
  async function subir(archivo, pegado) {
    const datos = new FormData();
    datos.append('archivo', archivo, archivo.name || 'imagen.png');
    // Pegado del portapapeles: se llama con su hora, como en la terminal.
    if (pegado) datos.append('pegado', '1');
    if (estado) estado.textContent = `subiendo ${archivo.name || 'imagen'}…`;
    try {
      const r = await fetch('/api/secretario/adjuntar', { method: 'POST', body: datos });
      const d = await r.json();
      if (!d.ok) {
        if (estado) estado.textContent = `no se adjuntó: ${d.error}`;
        return `${archivo.name || 'la imagen'} no se adjuntó (${d.error})`;
      }
      adjuntos.push({ ruta: d.ruta, imagen: !!d.imagen });
      pintarPorMandar();
      if (estado) estado.textContent = '';
      return '';
    } catch (e) {
      if (estado) estado.textContent = 'no se adjuntó: el hub no contesta';
      return `${archivo.name || 'la imagen'} no se adjuntó (el hub no contesta)`;
    }
  }
  function adjuntar(archivos, pegado) {
    for (const archivo of archivos) {
      const subida = subir(archivo, pegado).finally(() => { subidas = subidas.filter(s => s !== subida); });
      subidas.push(subida);
    }
  }
  if (porMandar) porMandar.addEventListener('click', e => {
    const b = e.target && e.target.closest ? e.target.closest('[data-quitar]') : null;
    if (!b) return;
    adjuntos.splice(Number(b.dataset.quitar), 1);
    pintarPorMandar();
  });
  if (botonAdjuntar && eligeArchivo) {
    botonAdjuntar.addEventListener('click', () => eligeArchivo.click());
    eligeArchivo.addEventListener('change', () => {
      adjuntar(Array.from(eligeArchivo.files || []), false);
      eligeArchivo.value = '';
    });
  }
  // Una captura (Win+Shift+S) llega según el navegador sólo en `items`, no en
  // `files`. Un pegado de texto no se toca: lo pega el cuadro como siempre.
  cuadro.addEventListener('paste', e => {
    const dt = e.clipboardData;
    let archivos = Array.from((dt && dt.files) || []);
    if (!archivos.length && dt && dt.items) {
      archivos = Array.from(dt.items).filter(i => i.kind === 'file').map(i => i.getAsFile()).filter(Boolean);
    }
    if (!archivos.length) return;
    e.preventDefault();
    adjuntar(archivos, true);
  });
  // Soltar un archivo sobre la conversación o el cuadro. Si la página ya lo
  // reclamó (`defaultPrevented`: en /trabajo, todo lo soltado va a la
  // terminal), no se marca el cuadro: parecería que va al chat y no.
  const llevaArchivos = (dt) => Array.from((dt && dt.types) || []).includes('Files');
  for (const zona of [chat, formulario]) {
    zona.addEventListener('dragover', e => {
      if (!llevaArchivos(e.dataTransfer) || e.defaultPrevented) return;
      e.preventDefault();
      formulario.classList.add('soltando');
    });
    zona.addEventListener('dragleave', e => {
      if (!e.relatedTarget || !zona.contains(e.relatedTarget)) formulario.classList.remove('soltando');
    });
    zona.addEventListener('drop', e => {
      formulario.classList.remove('soltando');
      if (!llevaArchivos(e.dataTransfer) || e.defaultPrevented) return;
      e.preventDefault();
      adjuntar(Array.from(e.dataTransfer.files || []), false);
    });
  }

  // Uno a la vez: con la espera de las subidas, dos Enter seguidos mandaban
  // el mismo mensaje dos veces.
  let enviando = false;
  async function enviar(texto) {
    if (enviando) return;
    enviando = true;
    try { await enviarYa(texto); } finally { enviando = false; }
  }
  async function enviarYa(texto) {
    texto = (texto || '').trim();
    if (subidas.length) {
      if (estado) estado.textContent = 'terminando de subir…';
      // Lo que no subió no puede irse callado: él creería que lo mandó.
      const fallos = (await Promise.all(subidas)).filter(Boolean);
      if (fallos.length) {
        if (estado) estado.textContent = `no se mandó: ${fallos[0]}. Pulsa Enviar otra vez para mandarlo sin eso.`;
        return;
      }
    }
    // Con algo adjunto, el texto puede ir vacío: una captura sola ya pregunta.
    if (!texto && !adjuntos.length) return;
    const cuerpo = { texto, voz: continuo };
    const mandados = adjuntos.map(a => a.ruta);
    if (mandados.length) cuerpo.adjuntos = mandados;
    const desde = pantallaActual();
    if (desde) cuerpo.pantalla = desde;
    // La ventana que miras, para que pueda leerla si le hablas de ella (C-0162).
    const enfoque = desde && document.body && document.body.dataset ? document.body.dataset.enfoque : '';
    if (enfoque) cuerpo.enfoque = enfoque;
    if (estado) estado.textContent = 'enviando…';
    try {
      const r = await fetch('/api/secretario/mensaje', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        // `voz`: se le va a leer, y el secretario contesta corto (C-0155).
        body: JSON.stringify(cuerpo),
      });
      const d = await r.json();
      if (!d.ok) { if (estado) estado.textContent = `no se envió: ${d.error}`; return; }
      cuadro.value = '';
      cuadro.style.height = '';
      // Sólo lo mandado: lo que terminó de subir mientras tanto espera al siguiente.
      adjuntos = adjuntos.filter(a => !mandados.includes(a.ruta));
      pintarPorMandar();
      esperando = true;
      contar({ enviado: Date.now() });
      fase('pensando', 'pensando…');
      mirar().then(seguir);
    } catch (e) {
      if (estado) estado.textContent = 'no se envió: el hub no contesta';
    }
  }
  formulario.addEventListener('submit', e => { e.preventDefault(); enviar(cuadro.value); });
  // El cuadro crece con lo que se escribe, hasta su tope; luego desplaza.
  const ajustar = () => { cuadro.style.height = 'auto'; cuadro.style.height = `${cuadro.scrollHeight + 2}px`; };
  cuadro.addEventListener('input', ajustar);
  document.querySelectorAll('[data-idea]').forEach(b => b.addEventListener('click', () => enviar(b.textContent)));
  cuadro.addEventListener('keydown', e => {
    // Enter manda, Mayús+Enter es salto de línea: como cualquier chat.
    if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); enviar(cuadro.value); }
  });

  /* ── la voz de vuelta ── */
  function paraOir(texto) {
    return String(texto || '')
      .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')   // [enlace](ruta) → enlace
      .replace(/[*_`#>]/g, '')
      .replace(/^\s*[-•]\s+/gm, '')
      .replace(/https?:\/\/\S+/g, 'un enlace');
  }
  /* Cómo suena: la única pieza que sabe de `speechSynthesis`. Otra voz
   * (Piper, ElevenLabs) es otro objeto con `decir(frase, fin)` y `callar()`;
   * el locutor y el modo voz no cambian. `decir` encola: frase tras frase. */
  const VOZ = {
    hay: () => !!window.speechSynthesis,
    decir(frase, fin) {
      const u = new SpeechSynthesisUtterance(frase);
      u.onend = fin; u.onerror = fin;
      u.onboundary = latido;   // no todos los navegadores lo dan: el orbe late igual por CSS
      const idioma = enIngles() ? 'en' : 'es';
      u.lang = idioma === 'en' ? 'en-US' : 'es-MX';
      const voces = window.speechSynthesis.getVoices();
      const voz = voces.find(v => v.lang === u.lang) || voces.find(v => (v.lang || '').startsWith(idioma));
      if (voz) u.voice = voz;
      window.speechSynthesis.speak(u);
    },
    callar() { if (window.speechSynthesis) window.speechSynthesis.cancel(); },
  };

  /* Qué decir de una respuesta que llega por trozos (C-0155). Lleva la cuenta
   * de lo ya dicho (`frasesNuevas`, pura) y avisa UNA vez al acabar —por fin
   * de la lectura o porque se le calló—, que es cuando el modo voz vuelve a
   * escuchar. */
  const locutor = (() => {
    // `vez` separa un turno del siguiente: el fin de una frase de antes,
    // callada a medias, no puede descontar las del turno nuevo.
    let id = null, dicho = '', sonando = 0, terminado = true, alAcabar = null, vez = 0;
    function acabar() {
      if (terminado) return;
      terminado = true;
      const f = alAcabar;
      alAcabar = null;
      if (f) f();
    }
    function soltar() { vez += 1; terminado = true; alAcabar = null; sonando = 0; VOZ.callar(); }
    return {
      turno: () => id,
      empezar(turno, despues) {
        if (!terminado) soltar();
        vez += 1;
        id = turno; dicho = ''; sonando = 0; terminado = false; alAcabar = despues || null;
      },
      avanzar(texto, final) {
        if (terminado) return;
        const r = frasesNuevas(dicho, texto, final);
        const fin = final || r.final;
        dicho = r.dicho;
        const esta = vez;
        if (VOZ.hay()) {
          for (const frase of r.frases) {
            const oir = paraOir(frase).trim();
            if (!oir) continue;
            sonando += 1;
            VOZ.decir(oir, () => {
              if (esta !== vez) return;
              sonando = Math.max(0, sonando - 1);
              if (fin && sonando === 0) acabar();
            });
          }
        }
        if (fin && sonando === 0) acabar();
      },
      // Se le calló hablándole: avisa, y el modo voz vuelve a escuchar.
      callar() { const f = alAcabar; soltar(); if (f) f(); },
      // Se deja sin avisar (salir del modo, pausar, pulsar el micro). Conserva
      // el turno: lo que siga llegando de él no se vuelve a empezar a leer.
      olvidar() { if (!terminado) soltar(); },
    };
  })();
  function decir(texto, despues) {
    contar({ voz: 'hablando' });
    locutor.empezar(`suelto-${Date.now()}`, () => { contar({ voz: '' }); if (despues) despues(); });
    locutor.avanzar(texto, true);
  }

  /* ── la voz de ida ── */
  let grabadora = null;
  // `mandar`: lo dicho sale solo, sin pasar por el cuadro (el atajo, C-0172).
  async function transcribir(trozos, tipo, mandar) {
    if (estado) estado.textContent = 'transcribiendo…';
    contar({ voz: 'transcribiendo' });
    try { await transcribirYa(trozos, tipo, mandar); } finally { if (!continuo) contar({ voz: '' }); }
  }
  async function transcribirYa(trozos, tipo, mandar) {
    const ext = tipo.includes('ogg') ? 'ogg' : tipo.includes('mp4') ? 'm4a' : 'webm';
    const datos = new FormData();
    datos.append('audio', new Blob(trozos, { type: tipo }), 'secretario.' + ext);
    datos.append('idioma', enIngles() ? 'en' : 'es');
    try {
      const r = await fetch('/api/voz', { method: 'POST', body: datos });
      const d = await r.json();
      if (!d.ok) {
        if (continuo) pausar(`no se pudo transcribir: ${d.error}`);
        else if (estado) estado.textContent = `no se transcribió: ${d.error}`;
        return;
      }
      if (continuo && !d.texto.trim()) { hablar('no te entendí; repítelo'); return; }
      if (mandar && !d.texto.trim()) { if (estado) estado.textContent = 'no te entendí; vuelve a intentarlo'; return; }
      if (continuo || mandar || (manosLibres && manosLibres.checked)) { enviar(d.texto); return; }
      cuadro.value = (cuadro.value ? cuadro.value + ' ' : '') + d.texto;
      cuadro.focus();
      if (estado) estado.textContent = 'revísalo y pulsa Enviar';
    } catch (e) {
      if (continuo) pausar('el hub no contesta');
      else if (estado) estado.textContent = 'no se transcribió: el hub no contesta';
    }
  }

  /* ── el modo voz (decisión 317) ── */
  // Una frase de estado, en la línea de abajo y en el panel; `nombre` pinta el orbe.
  function fase(nombre, texto) {
    if (estado) estado.textContent = continuo ? '' : texto;
    // Antes del `return` del modo voz: el personaje lo sigue en los dos modos.
    // «pensando» no se dice: lo cuenta el turno, con lo que de verdad hace.
    contar({ voz: nombre === 'pensando' ? '' : nombre });
    if (!continuo || !panelVoz) return;
    if (panelVoz.dataset.fase !== nombre) nivel(0);
    panelVoz.dataset.fase = nombre;
    vozEstado.textContent = texto;
  }
  async function pedirPantalla() {
    try { if (navigator.wakeLock) candado = await navigator.wakeLock.request('screen'); } catch (e) { /* sin candado: sólo se apaga antes */ }
  }
  function soltarPantalla() {
    try { if (candado) candado.release(); } catch (e) { /* ya suelto */ }
    candado = null;
  }
  /* Interrumpirle hablando (decisión 318): mientras lee la respuesta, el
   * micrófono sigue abierto, con cancelación de eco, y si se oye voz por
   * encima de su propio eco se le calla. Callarlo dispara el final de
   * `decir`, que ya vuelve a escuchar: no hace falta nada más. */
  let vigia = null;
  async function vigilarInterrupcion() {
    soltarVigia();
    const Ctx = window.AudioContext || window.webkitAudioContext;
    if (!Ctx || !navigator.mediaDevices) return;
    const propio = {};
    vigia = propio;
    let flujo;
    try {
      flujo = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
    } catch (e) { return; }
    // Terminó de hablar (o se salió del modo) mientras se pedía el micro.
    if (vigia !== propio) { flujo.getTracks().forEach(p => p.stop()); return; }
    const ctx = new Ctx();
    const analizador = ctx.createAnalyser();
    analizador.fftSize = 2048;
    ctx.createMediaStreamSource(flujo).connect(analizador);
    const muestra = new Float32Array(analizador.fftSize);
    let e = interrupcionInicial();
    propio.reloj = setInterval(() => {
      analizador.getFloatTimeDomainData(muestra);
      let suma = 0;
      for (const x of muestra) suma += x * x;
      e = interrupcionTras(e, Math.sqrt(suma / muestra.length), 100);
      if (e.fin && vigia === propio) {
        soltarVigia();
        locutor.callar();
      }
    }, 100);
    propio.soltar = () => { clearInterval(propio.reloj); flujo.getTracks().forEach(p => p.stop()); ctx.close(); };
  }
  function soltarVigia() {
    const v = vigia;
    vigia = null;
    if (v && v.soltar) v.soltar();
  }
  function callarTodo() {
    soltarVigia();
    if (grabadora) { grabadora.descartar = true; grabadora.stop(); }
    locutor.olvidar();
    VOZ.callar();
  }
  function entrarModo() {
    continuo = true;
    pausado = false;
    silencios = 0;
    panelVoz.hidden = false;
    formulario.classList.add('en-modo-voz');
    vozPausa.textContent = 'Pausar';
    pedirPantalla();
    hablar();
  }
  function salirModo() {
    callarTodo();
    fase('', '');
    continuo = false;
    pausado = false;
    panelVoz.hidden = true;
    formulario.classList.remove('en-modo-voz');
    soltarPantalla();
  }
  function pausar(motivo) {
    pausado = true;
    callarTodo();
    vozPausa.textContent = 'Seguir';
    fase('pausa', motivo || 'en pausa');
  }
  function reanudar() {
    pausado = false;
    silencios = 0;
    vozPausa.textContent = 'Pausar';
    pedirPantalla();
    hablar();
  }
  // Cuánto se insiste sin oír a nadie antes de pausar: unas 15 escuchas de
  // 8 s, unos dos minutos. Se pausa, no se sale: el modo sigue a un toque.
  const SILENCIOS_PAUSA = 15;

  // `atajo`: grabando mientras se mantiene Ctrl+Espacio (C-0172); al soltar, se manda.
  async function hablar(aviso, atajo) {
    if (grabadora) { grabadora.stop(); return; }
    // Hablándole mientras lee: se calla y escucha (interrumpir con un toque).
    locutor.olvidar();
    VOZ.callar();
    if (!navigator.mediaDevices || !window.MediaRecorder) {
      if (estado) estado.textContent = 'este navegador no deja grabar aquí (hace falta HTTPS o localhost)';
      return;
    }
    let flujo;
    try {
      flujo = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
    } catch (e) {
      if (estado) estado.textContent = 'sin permiso para el micrófono';
      return;
    }
    const trozos = [];
    const esta = new MediaRecorder(flujo);
    grabadora = esta;
    esta.atajo = atajo || null;
    esta.addEventListener('dataavailable', ev => { if (ev.data && ev.data.size) trozos.push(ev.data); });
    esta.addEventListener('stop', () => {
      flujo.getTracks().forEach(p => p.stop());
      grabadora = null;
      botonHablar.classList.remove('on');
      botonHablar.setAttribute('aria-label', 'Hablar');
      if (!continuo) contar({ voz: '' });
      // Parado por «no oí nada»: lo grabado es ruido, y Whisper le inventaría texto.
      if (esta.descartar) { if (esta.reescuchar && continuo && !pausado) hablar(); return; }
      if (trozos.length) transcribir(trozos, esta.mimeType || 'audio/webm', !!esta.atajo);
      else if (estado) estado.textContent = 'no se grabó nada';
    });
    esta.start();
    // Soltó la tecla mientras se abría el micrófono: eso no es hablar.
    if (esta.atajo && esta.atajo.soltado) { esta.descartar = true; esta.stop(); return; }
    botonHablar.classList.add('on');
    botonHablar.setAttribute('aria-label', 'Parar');
    if (continuo) {
      fase('escuchando', aviso || 'te escucho…');
      escucharSilencio(flujo, esta);
    } else {
      contar({ voz: 'escuchando' });
      if (estado) estado.textContent = esta.atajo ? 'escuchando… suelta Ctrl+Espacio para mandarlo'
                                                  : 'escuchando… vuelve a pulsar el micrófono al terminar';
    }
  }

  /* ── hablarle manteniendo una tecla (C-0172) ──
   * Ctrl+Espacio, mantenido: graba mientras lo tienes pulsado y, al soltar,
   * lo transcribe y lo manda. Una combinación y no una tecla sola porque así
   * no escribe nada y vale también dentro del cuadro, de un campo o de la
   * terminal de /trabajo, que no la ve: se atiende en captura, antes que nadie.
   * (Alt derecha no sirve: en un teclado español es AltGr, la de la @.)
   * Un toque de menos de `ATAJO_MIN_MS` no es hablar y se tira; perder el foco
   * con la tecla pulsada, también: soltarla en otra ventana no llega aquí. */
  const ATAJO_MIN_MS = 350;
  const ATAJO_MAX_MS = 60000;
  let atajo = null;
  let abrirPanel = null;   // lo pone el panel, si lo hay (más abajo)
  const esAtajo = (e) => e.code === 'Space' && e.ctrlKey && !e.altKey && !e.metaKey && !e.shiftKey;
  function soltarAtajo(tirar) {
    const a = atajo;
    atajo = null;
    if (!a) return;
    clearTimeout(a.reloj);
    a.soltado = true;
    const g = grabadora;
    if (!g || g.atajo !== a) return;   // el micrófono aún no se abrió: `hablar` lo tira al abrirse
    if (tirar || Date.now() - a.desde < ATAJO_MIN_MS) {
      g.descartar = true;
      if (estado) estado.textContent = tirar ? '' : 'mantén Ctrl+Espacio mientras hablas';
    }
    g.stop();
  }
  document.addEventListener('keydown', (e) => {
    if (!esAtajo(e)) return;
    e.preventDefault();
    e.stopPropagation();
    if (e.repeat || atajo || continuo || grabadora) return;
    atajo = { desde: Date.now(), soltado: false };
    atajo.reloj = setTimeout(() => soltarAtajo(false), ATAJO_MAX_MS);
    // Plegado no verías la respuesta: se abre el panel.
    if (abrirPanel) abrirPanel(true);
    hablar(undefined, atajo);
  }, true);
  document.addEventListener('keyup', (e) => {
    if (!atajo || (e.code !== 'Space' && e.key !== 'Control')) return;
    e.preventDefault();
    soltarAtajo(false);
  }, true);
  window.addEventListener('blur', () => soltarAtajo(true));
  document.addEventListener('visibilitychange', () => { if (document.hidden) soltarAtajo(true); });

  /* Corta la grabación cuando se deja de hablar. Mide el volumen del micro
   * cada 100 ms; la decisión la toma `silencioTras`, que es pura y se prueba. */
  function escucharSilencio(flujo, esta) {
    const Ctx = window.AudioContext || window.webkitAudioContext;
    if (!Ctx) return;
    const ctx = new Ctx();
    const analizador = ctx.createAnalyser();
    analizador.fftSize = 2048;
    ctx.createMediaStreamSource(flujo).connect(analizador);
    const muestra = new Float32Array(analizador.fftSize);
    let e = silencioInicial();
    const reloj = setInterval(() => {
      if (esta.state !== 'recording') { clearInterval(reloj); ctx.close(); return; }
      analizador.getFloatTimeDomainData(muestra);
      let suma = 0;
      for (const x of muestra) suma += x * x;
      const rms = Math.sqrt(suma / muestra.length);
      e = silencioTras(e, rms, 100);
      nivel((rms - e.fondo) / 0.08);
      if (e.fin) {
        clearInterval(reloj);
        ctx.close();
        if (e.fin === 'nada') {
          // Nadie habló: se tira lo grabado y se vuelve a escuchar, sin salir del modo.
          silencios += 1;
          esta.descartar = true;
          if (silencios >= SILENCIOS_PAUSA) { esta.stop(); pausar('pausé el micrófono tras un rato sin oírte'); return; }
          esta.reescuchar = true;
          esta.stop();
        } else { silencios = 0; esta.stop(); }
      }
    }, 100);
  }

  botonHablar.addEventListener('click', () => hablar());
  if (botonModo && panelVoz) {
    botonModo.addEventListener('click', entrarModo);
    document.getElementById('sec-voz-salir').addEventListener('click', salirModo);
    vozPausa.addEventListener('click', () => (pausado ? reanudar() : pausar()));
    // El círculo: mientras habla, la interrumpe y escucha; mientras escucha,
    // manda ya lo dicho; en pausa, sigue.
    document.getElementById('sec-orbe-voz').addEventListener('click', () => (pausado ? reanudar() : hablar()));
    // En Android, una app en segundo plano pierde el micrófono: mejor decirlo
    // en pausa que dejarlo escuchando a nadie.
    document.addEventListener('visibilitychange', () => {
      if (document.hidden && continuo && !pausado) pausar('en pausa: saliste de la app');
    });
  }

  /* Desde dónde le hablas (C-0160). En /secretario, nada: es su casa. En el
   * panel, la pantalla del hub y, en /trabajo, la ventana que miras
   * (`body.dataset.enfoque`, lo pone esa pantalla). */
  function pantallaActual() {
    if (!chat.dataset.cargar || !location.pathname) return '';   // sólo el panel trae `data-cargar`
    const enfoque = document.body && document.body.dataset ? document.body.dataset.enfoque : '';
    return location.pathname + (document.title ? ` · ${document.title}` : '') + (enfoque ? ` · ventana ${enfoque}` : '');
  }

  // El panel que le sigue por el hub (C-0160): plegado en una pestaña, y
  // «Guíame» lo abre con la pregunta hecha (`HubSecretario.preguntar`).
  const panel = chat.dataset.cargar ? document.getElementById('secretario-panel') : null;
  if (panel) {
    const pestana = document.getElementById('secretario-pestana');
    const CLAVE = 'hub.secretario.abierto';
    const abrir = (si) => {
      panel.classList.toggle('abierto', si);
      pestana.setAttribute('aria-expanded', si ? 'true' : 'false');
      guardar(CLAVE, si);
      if (si) { bajar(); if (!cargando) mirar().then(seguir); }
    };
    pestana.addEventListener('click', () => abrir(!panel.classList.contains('abierto')));
    abrir(leerPref(CLAVE));
    abrirPanel = (si) => { if (si !== panel.classList.contains('abierto')) abrir(si); };
    window.HubSecretario = { preguntar(texto) { abrir(true); enviar(texto); } };
  }
  // En el panel no viene nada pintado: la conversación se pide al cargar.
  if (chat.dataset.cargar) mirar().then(() => { cargando = false; seguir(); });
  else cargando = false;
})();

/* ── «Te espera»: lo que tienes delante deja de ser nuevo (C-0201, 379) ──
 * En Pendientes, los asuntos nuevos que se ven se marcan como vistos por
 * POST: nunca al pintar la página en el servidor (un GET no escribe), y no
 * en cuanto carga, sino cuando estás. Llegar por el globo (`#te-espera`) es
 * estar; si no, el primer toque, tecla o rueda en la página. Así una
 * pantalla que se abre sola —el relevo la abre en la PC (388)— no da por
 * visto lo que nadie ha mirado. Lo que llega al repintar tras un botón tuyo,
 * también. Cada clave sale una vez; si el POST falla, se vuelve a intentar
 * en el siguiente gesto. */
(() => {
  const bloque = document.getElementById('te-espera');
  if (!bloque || !bloque.dataset || !('teEspera' in bloque.dataset)) return;
  const mandadas = new Set();
  let presente = location.hash === '#te-espera';
  function marcar() {
    // Lo que sigue dentro de un plegado cerrado («Te espera» pliega las
    // fichas) no lo tienes delante: se marca al abrirlo (`toggle`).
    const plegados = new Set(document.querySelectorAll('#te-espera details:not([open]) [data-clave][data-nueva]'));
    const claves = [...document.querySelectorAll('#te-espera [data-clave][data-nueva]')]
      .filter((n) => !plegados.has(n))
      .map((n) => n.dataset && n.dataset.clave).filter((c) => c && !mandadas.has(c));
    if (!claves.length) return;
    claves.forEach((c) => mandadas.add(c));
    const olvidar = () => claves.forEach((c) => mandadas.delete(c));
    fetch('/secretario/asuntos/vista', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ claves }),
    }).then((r) => { if (r && r.ok === false) olvidar(); }, olvidar);
  }
  const llega = () => { presente = true; marcar(); };
  ['pointerdown', 'keydown', 'wheel', 'touchstart'].forEach((ev) =>
    document.addEventListener(ev, llega, { passive: true }));
  document.addEventListener('hub:repintado', () => { if (presente) marcar(); });
  // `toggle` no burbujea: se escucha en captura, en el bloque.
  // Sólo si estás: un plegado que se abre solo al cargar (el que recuerda
  // cómo lo dejaste) no es mirarlo.
  bloque.addEventListener('toggle', () => { if (presente) marcar(); }, true);
  if (presente) marcar();
})();

/* ── cuándo se dejó de hablar (decisión 314) ──
 * Un estado y una muestra de volumen (RMS 0-1) cada `ms`. Los primeros 400 ms
 * miden el ruido de fondo; habla quien pasa de 3 veces ese fondo (y de un
 * mínimo). Tras haber hablado, 1,3 s por debajo es el final. Sin hablar en
 * 8 s, se deja de escuchar: el micrófono abierto sin nadie gasta batería y
 * graba lo que no se pidió. Y nunca más de 60 s seguidos. */
/* ── qué falta por decir de una respuesta a medio escribir (C-0155) ──
 * Pura, como `silencioTras`. Devuelve las frases completas nuevas y lo dicho
 * hasta ahora. Una frase se da por completa al ver su punto (o el final de la
 * respuesta); lo que queda a medias espera al siguiente trozo. Si el texto ya
 * no empieza por lo dicho, se ha rehecho: vacío es otra respuesta (el modelo
 * mayor) y se lee desde el principio; con otro texto se espera a la final y
 * se lee ENTERA — repetir una frase es mejor que callarse la respuesta. */
function frasesNuevas(dicho, texto, final) {
  texto = String(texto || '');
  if (!texto.startsWith(dicho)) {
    if (!texto.trim()) return { frases: [], dicho: '', final: false };
    if (!final) return { frases: [], dicho, final: false };
    dicho = '';
  }
  const resto = texto.slice(dicho.length);
  let corte = final ? resto.length : -1;
  if (!final) {
    const re = /[.!?…:](?=\s)|\n/g;
    let m;
    while ((m = re.exec(resto)) !== null) corte = m.index + m[0].length;
  }
  if (corte <= 0) return { frases: [], dicho, final: false };
  const nuevo = resto.slice(0, corte);
  const frases = nuevo.split(/(?<=[.!?…:])\s+|\n+/).map(f => f.trim()).filter(Boolean);
  return { frases, dicho: dicho + nuevo, final: false };
}

function silencioInicial() {
  return { t: 0, fondo: 0, n: 0, hablo: false, callado: 0, fin: null };
}
function silencioTras(e, rms, ms) {
  const s = { ...e, t: e.t + ms };
  if (s.t <= 400) { s.fondo = (s.fondo * s.n + rms) / (s.n + 1); s.n += 1; return s; }
  const umbral = Math.max(s.fondo * 3, 0.012);
  if (rms > umbral) { s.hablo = true; s.callado = 0; }
  else if (s.hablo) s.callado += ms;
  if (s.hablo && s.callado >= 1300) s.fin = 'callado';
  else if (!s.hablo && s.t >= 8000) s.fin = 'nada';
  else if (s.t >= 60000) s.fin = 'largo';
  return s;
}

/* ── cuándo le interrumpes mientras habla (decisión 318) ──
 * Como `silencioTras`, pura. Los primeros 600 ms miden el PICO de lo que
 * llega mientras él habla —su propia voz colada por el altavoz, lo que la
 * cancelación de eco no quita—; interrumpe quien pasa de 2,5 veces ese pico
 * (y de un mínimo) durante 300 ms seguidos. Un golpe suelto no cuenta. */
function interrupcionInicial() {
  return { t: 0, eco: 0, seguido: 0, fin: false };
}
function interrupcionTras(e, rms, ms) {
  const s = { ...e, t: e.t + ms };
  if (s.t <= 600) { s.eco = Math.max(s.eco, rms); return s; }
  const umbral = Math.max(s.eco * 2.5, 0.03);
  s.seguido = rms > umbral ? s.seguido + ms : 0;
  if (s.seguido >= 300) s.fin = true;
  return s;
}
