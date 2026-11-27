/* El chat del secretario (definición 2.x, 5.2 y 6.x; C-0160 lo saca a
 * componente): en /secretario y, en el hub del dueño, en el panel que le
 * sigue por todas las pantallas. Necesita el marcado de
 * `_chat_secretario.html` y `formato-chat.js` antes, y `grabar.js` (en el
 * `<head>` de `base.html`).
 *
 * Lo que se escribe o se dicta va a `/api/secretario/mensaje`, que sólo lo
 * deja en la base: lo contesta `hub-secretario` (decisión 298). Aquí se
 * pregunta cada poco hasta ver la respuesta.
 *
 * La voz, de ida y de vuelta:
 * - **Hablar** graba en el navegador y transcribe EN CASA (`/api/voz`, el
 *   mismo Whisper del dictado de la terminal). Abrir el micrófono, grabar y
 *   subir lo hace `HubGrabar` (C-0311), con las restricciones de la
 *   conversación; aquí se queda la máquina del modo voz: el corte por
 *   silencio, los turnos y el vigía que deja interrumpirle.
 * - **Leer en voz alta** usa la voz del propio navegador (`speechSynthesis`),
 *   frase a frase según el secretario la escribe (C-0155): el `locutor` decide
 *   qué toca decir y `VOZ` es sólo cómo suena.
 */
(() => {
  const chat = document.getElementById('sec-chat');
  if (!chat) return;
  const formulario = document.getElementById('sec-escribir');
  const estado = document.getElementById('estado-sec');
  const botonHablar = document.getElementById('sec-hablar');
  const enVoz = document.getElementById('sec-en-voz');
  const manosLibres = document.getElementById('sec-manos-libres');
  const botonModo = document.getElementById('sec-modo-voz');
  const panelVoz = document.getElementById('sec-panel-voz');
  const vozEstado = document.getElementById('sec-voz-estado');
  const vozPausa = document.getElementById('sec-voz-pausa');
  const orbe = document.getElementById('sec-orbe-voz');
  /* La línea de debajo del cuadro (C-0305). Servía igual para «enviando…»
   * que para «no se envió», en gris pequeño: en el teléfono, con el teclado
   * abierto, un mensaje que no salió se confundía con uno enviado (regla 17).
   * Un fallo va con `tono` «error»: en rojo, con su marca y como alerta. */
  function avisar(texto, tono) {
    if (!estado) return;
    estado.setAttribute('role', tono === 'error' ? 'alert' : 'status');
    if (tono) { estado.dataset.tono = tono; estado.dataset.dicho = texto; } else delete estado.dataset.tono;
    estado.textContent = texto;
  }
  // Lo que escribe en la línea quien no sabe de tonos (el dictado) le quita
  // el rojo: un «escuchando…» después de un fallo no es otro fallo.
  if (estado && typeof MutationObserver === 'function') {
    new MutationObserver(() => {
      if (estado.dataset.tono && estado.textContent !== estado.dataset.dicho) avisar(estado.textContent);
    }).observe(estado, { childList: true, characterData: true, subtree: true });
  }
  // El modo inglés (C-0159): lo guarda el servidor; aquí sólo cambia el idioma
  // de la voz y de la transcripción.
  const botonIngles = document.getElementById('sec-modo-ingles');
  const cuadro = document.getElementById('sec-texto');
  /* Mientras dura, una línea encima del cuadro y el cuadro en inglés (UI-34,
   * C-0364): sólo lo decía el chip relleno, y en este modo lo que haría solo
   * pide permiso (C-0159). Las pinta el servidor al cargar; aquí se siguen. */
  const lineaIngles = document.getElementById('sec-en-ingles');
  const ESCRIBELE = { es: 'Escríbele', en: 'Write to him' };
  const enIngles = () => !!botonIngles && botonIngles.dataset.activo === '1';
  const ponerIngles = (activo) => {
    botonIngles.dataset.activo = activo ? '1' : '';
    botonIngles.setAttribute('aria-pressed', activo ? 'true' : 'false');
    if (lineaIngles) lineaIngles.hidden = !activo;
    if (cuadro) cuadro.placeholder = ESCRIBELE[activo ? 'en' : 'es'];
  };
  let cambiandoIngles = false;
  async function cambiarIngles(activo) {
    cambiandoIngles = true;
    try {
      const r = await fetch('/api/secretario/ingles', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ activo }),
      });
      const d = await r.json();
      if (d.ok) {
        ponerIngles(d.activo);
        // Puesto, ya lo dice su línea; antes salía aquí, y en inglés.
        avisar(d.activo ? '' : 'modo inglés quitado');
      }
    } catch (e) {
      avisar('no se pudo cambiar: el hub no contesta', 'error');
    } finally { cambiandoIngles = false; }
  }
  if (botonIngles) botonIngles.addEventListener('click', () => cambiarIngles(!enIngles()));
  const quitarIngles = document.getElementById('sec-quitar-ingles');
  if (botonIngles && quitarIngles) quitarIngles.addEventListener('click', () => cambiarIngles(false));
  /* El modo lo puede cambiar también el secretario («pon el modo inglés»,
   * C-0422) o él desde otro aparato: el sondeo dice cómo está ahora, y el
   * botón —con él, el idioma de la voz y del dictado— lo sigue. Mientras su
   * propio toque va de camino no se le pisa con lo que decía el hub antes. */
  function seguirElIngles(activo) {
    if (!botonIngles || cambiandoIngles || !!activo === enIngles()) return;
    ponerIngles(!!activo);
  }
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
  /* «Detener» (C-0506): el turno suyo que se está contestando (o espera a
   * que lo tomen), como lo dice el sondeo; el que ya se pidió parar, para no
   * pedirlo dos veces; y, en el modo voz, el que se detuvo hablando: lo que
   * llegue de su respuesta no se lee, se dice «Detenido.» y vuelve a escuchar. */
  let turnoEnCurso = null;
  let deteniendo = null;
  let detenidoEnVoz = null;
  const botonEnviar = document.getElementById('sec-enviar');
  const vozDetener = document.getElementById('sec-voz-detener');
  // El panel trae la conversación al cargar (C-0160): esa primera vez no habla.
  let cargando = !!chat.dataset.cargar;

  const guardar = (clave, valor) => { try { localStorage.setItem(clave, valor ? '1' : ''); } catch (e) { /* sin almacenamiento */ } };
  const leerPref = (clave) => { try { return localStorage.getItem(clave) === '1'; } catch (e) { return false; } };
  if (enVoz) { enVoz.checked = leerPref('secretario.voz'); enVoz.addEventListener('change', () => guardar('secretario.voz', enVoz.checked)); }
  if (manosLibres) { manosLibres.checked = leerPref('secretario.manos'); manosLibres.addEventListener('change', () => guardar('secretario.manos', manosLibres.checked)); }
  // Fuera del modo voz, con «Leer las respuestas en voz alta» (VOZ-23).
  const leerEnVoz = () => !continuo && !!enVoz && !!enVoz.checked;

  const escapar = (s) => String(s ?? '').replace(/[&<>"']/g, c =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  // Con «Copiar» en los bloques de código (C-0306): lo atiende el `click` del chat.
  const formatear = window.formatearMensaje ? (t) => window.formatearMensaje(t, { copiar: true }) : escapar;

  /* Una fuente de una investigación como enlace corto (C-0452, decisión 439):
   * la única excepción a que el chat no enlace nada de fuera (271). Sólo
   * `http:`/`https:` analizado con `URL`; el texto es el host sacado del
   * `href`, nunca un texto del modelo; lo demás, null y se pinta escapado. */
  function enlaceFuente(x) {
    let u;
    try { u = new URL(String(x ?? '')); } catch (e) { return null; }
    if (u.protocol !== 'http:' && u.protocol !== 'https:') return null;
    const host = u.hostname.replace(/^www\./i, '');
    if (!host) return null;
    // Con `<wbr>` tras cada punto: en el móvil el dominio parte por ahí y no
    // le quita a «Qué dice» el ancho de una palabra (medido a 390 px).
    return `<a class="fuente" href="${escapar(u.href)}" title="${escapar(u.href)}" target="_blank" `
         + `rel="noopener noreferrer">${escapar(host).split('.').join('.<wbr>')}</a>`;
  }

  function ficha(t) {
    const caja = document.createElement('div');
    caja.className = 'ficha';
    let html = `<strong>${escapar(t.titulo)}</strong>`;
    if (t.tipo === 'tabla') {
      // Sólo las columnas que la tarjeta declara de enlaces (la de fuentes de
      // `investigar`); una tarjeta sin `enlaces` se pinta toda escapada.
      const enlaces = new Set(Array.isArray(t.enlaces) ? t.enlaces.map(Number) : []);
      html += '<table>';
      if (t.columnas && t.columnas.length) html += '<tr>' + t.columnas.map(c => `<th>${escapar(c)}</th>`).join('') + '</tr>';
      html += (t.filas || []).map(f => '<tr>' + f.map((x, i) =>
        `<td>${(enlaces.has(i) && enlaceFuente(x)) || escapar(x)}</td>`).join('') + '</tr>').join('');
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

  /* Responder a un globo (C-0243, decisión 406), como en WhatsApp Web: la
   * cita encima de tu globo, y pulsarla lleva al original si está pintado
   * (puede ser de una conversación ya cerrada). El texto lo trae el servidor
   * (`turnos` → `cita`), nunca se saca del DOM. */
  const QUIEN = { secretario: 'Secretario', dueno: 'Tú' };
  function citaHtml(c) {
    if (!c || !c.id) return '';
    return `<button type="button" class="cita-globo" data-ir="${escapar(String(c.id))}" title="Ir a ese mensaje">`
         + `<span class="quien">${escapar(QUIEN[c.rol] || '')}</span>`
         + `<span class="txt">${escapar(c.texto || '')}</span></button>`;
  }

  function pintar(nodo, t) {
    const aMedias = t.estado === 'escribiendo' && !!t.texto;
    nodo.className = `burbuja ${t.rol}` + (t.estado === 'error' ? ' error' : '') + (t.estado === 'escribiendo' ? ' escribiendo' : '')
                     + (aMedias ? ' a-medias' : '');
    nodo.dataset.turno = t.id;
    nodo.dataset.estado = t.estado;
    // De qué conversación es (C-0393): con lo anterior pintado, cada una lleva su separador.
    if (t.hilo !== undefined && t.hilo !== null && t.hilo !== '') nodo.dataset.hilo = String(t.hilo);
    if (t.estado === 'escribiendo' && !t.texto) {
      // Lo que hace mientras tanto, dicho también aquí (C-0166): el rótulo
      // ya viene redactado por el servidor (`turno.actividad`).
      const act = t.actividad && t.actividad.estado === 'trabajando' ? t.actividad.rotulo : '';
      nodo.innerHTML = '<span class="puntos" role="img" aria-label="pensando"><i></i><i></i><i></i></span>'
                       + (act ? `<span class="que-hace">${escapar(act)}</span>` : '');
      return;
    }
    nodo.dataset.texto = t.texto || '';
    nodo.dataset.rol = t.rol;
    nodo.innerHTML = citaHtml(t.cita) + formatear(t.texto || '') + adjuntosHtml(t.adjuntos)
                     + (t.estado === 'listo' && t.texto
                        ? '<button type="button" class="citar" data-citar aria-label="Responder a este mensaje"'
                          + ' title="Responder a este mensaje (o doble clic al lado)">↩</button>' : '');
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
    let cita = null;
    try { cita = JSON.parse(n.dataset.cita || 'null'); } catch (e) { /* cita rota: sin cita */ }
    pintar(n, { id: n.dataset.turno, hilo: n.dataset.hilo, rol: n.classList.contains('dueno') ? 'dueno' : 'secretario',
                texto: n.dataset.texto, tarjetas, adjuntos, cita, estado: n.dataset.estado,
                modelo: n.dataset.modelo, segundos: n.dataset.segundos });
  });
  /* Pegado al final (C-0303). Bajar una vez al cargar no basta: lo que llega
   * después cambia el alto —el globo «Te espera» sale encima y encoge el chat
   * 52 px, una imagen termina de cargar, se abre el teclado del móvil— y la
   * última respuesta, la que se viene a leer, quedaba cortada. Si estaba al
   * final, se vuelve a bajar; si subió a leer algo, no se le mueve.
   * El evento `scroll` del propio `bajar` llega después, a veces con el globo
   * ya puesto: medido así parecería que subió él. Por eso se apunta dónde lo
   * dejó `bajar` y ese evento no cuenta. */
  let pegado = true;
  let puesto = -1;
  const bajar = () => { chat.scrollTop = chat.scrollHeight; puesto = chat.scrollTop; pegado = true; };
  const seguirAlFinal = () => { if (pegado) bajar(); };
  chat.addEventListener('scroll', () => {
    // `puesto` es -1 cuando no hay un `bajar` que descontar: sin mirarlo, un
    // scroll que caía justo en 0 no contaba (tras la revisión de C-0393).
    if (puesto >= 0 && Math.abs(chat.scrollTop - puesto) < 2) return;
    puesto = -1;
    pegado = chat.scrollHeight - chat.clientHeight - chat.scrollTop < 32;
  }, { passive: true });
  if (typeof ResizeObserver === 'function') new ResizeObserver(seguirAlFinal).observe(chat);
  // `load` no burbujea: en captura, para las imágenes de los globos.
  chat.addEventListener('load', seguirAlFinal, true);
  bajar();

  /* Lo escrito se paró en el borde de un bloque: el turno sigue abierto pero
   * ya no escribe, usa una herramienta o piensa (`turno.actividad`, 358). El
   * motor no pone nada tras la última frase hasta el mensaje siguiente, y
   * «Déjame mirarlo.» se quedaba callado lo que tardara la herramienta,
   * justo lo que la 353 quería evitar (C-0284). */
  const bloqueCerrado = (t) => t.estado === 'escribiendo' && !!t.texto && !!t.actividad
                                && !!t.actividad.estado && t.actividad.estado !== 'escribiendo';

  /* El hueco del panel mientras llega la conversación (C-0304): se quita con
   * la primera respuesta del hub, y las ideas de «chat vacío» sólo salen si
   * esa respuesta no trae nada. Si el hub no contesta, no se sabe: se queda. */
  let hayTurnos = false;
  function quitarHueco() {
    const hueco = document.getElementById('sec-cargando');
    if (hueco) hueco.remove();
    const vacio = document.getElementById('sec-vacio');
    if (vacio && !hayTurnos) vacio.hidden = false;
  }

  /* Para el lector de pantalla (UI-46, C-0365): la respuesta terminada, una
   * vez, en su región; el chat ya no es una región viva. Una propia y no la
   * del personaje: ésa dice «Listo» a la vez, y una pisaría a la otra. Lo que
   * ya suena en voz alta no se repite, y lo de antes de cargar tampoco. */
  const anuncio = document.getElementById('sec-anuncio');
  const anunciados = new Set();
  function anunciar(t) {
    if (!anuncio || anunciados.has(t.id)) return;
    anunciados.add(t.id);
    // Acotado como lo que se lee (`acotarParaOir`): si se cortó, que lo sepa.
    const entero = String(t.texto || '');
    const resto = acotarParaOir(entero).length < entero.length ? ' El resto sigue en el chat.' : '';
    anuncio.textContent = (t.estado === 'error' ? 'No pudo contestar: ' : 'Contestó: ') + paraOir(entero) + resto;
  }

  function ponerTurno(t) {
    hayTurnos = true;
    const vacio = document.getElementById('sec-vacio');
    if (vacio) vacio.remove();
    let nodo = chat.querySelector(`[data-turno="${t.id}"]`);
    const antes = nodo ? nodo.dataset.estado : null;
    const nuevo = !nodo;
    if (!nodo) { nodo = document.createElement('div'); chat.appendChild(nodo); }
    pintar(nodo, t);
    const final = t.estado === 'listo' || t.estado === 'error';
    // Un turno «escribiendo» vacío también le llega si ya lo estaba leyendo:
    // es el escalado al modelo mayor, que vacía lo dicho por el menor.
    const escribe = t.estado === 'escribiendo' && (t.texto || locutor.turno() === t.id);
    // Lo que ya estaba contestado al cargar el panel no se lee otra vez.
    // Ni la respuesta que él detuvo en el modo voz (C-0506): de ella sólo «Detenido.».
    if (t.rol === 'secretario' && detenidoEnVoz !== null && Number(t.id) > detenidoEnVoz) {
      if (final) acabarDetenidoEnVoz(t);
    } else if (t.rol === 'secretario' && antes !== 'listo' && (final || escribe) && !(cargando && final)) {
      if (final && t.texto && !continuo && !leerEnVoz()) anunciar(t);
      if (continuo && !pausado) {
        if (locutor.turno() !== t.id) {
          fase('hablando', 'te contesto… háblame para interrumpir');
          locutor.empezar(t.id, () => { soltarVigia(); if (continuo && !pausado) hablar(); });
          vigilarInterrupcion();
        }
        locutor.avanzar(t.texto, final, bloqueCerrado(t));
      }
      /* Con la casilla, frase a frase con el mismo locutor (VOZ-23): esperar
       * a «listo» era esperar la respuesta entera (p50 9,4 s, p90 31 s)
       * antes de la primera palabra. Al acabar no se escucha: no es el modo voz. */
      else if (leerEnVoz()) {
        if (locutor.turno() !== t.id) {
          contar({ voz: 'hablando' });
          locutor.empezar(t.id, () => contar({ voz: '' }));
        }
        locutor.avanzar(t.texto, final, bloqueCerrado(t));
      }
    }
    /* Un globo nuevo suyo baja al final: lo acaba de mandar. Lo demás —la
     * respuesta que llega o crece, un turno que sigue esperando— sólo sigue
     * al final si ya estaba ahí (C-0393, tras la revisión): cada sondeo de un
     * turno sin contestar arrastraba al final a quien había subido a leer lo
     * anterior, mientras pensaba o, con el servicio parado, siempre. */
    if (nuevo && t.rol === 'dueno') bajar(); else seguirAlFinal();
  }

  /* ── Lo ya hablado (C-0393) ──
   * El chat pintaba sólo el hilo abierto: cerrado uno (media hora sin
   * hablar), al abrir la app por la mañana salía vacío, y releer una
   * respuesta de ayer costaba pedirla y pagarla otra vez. Lo anterior se pide
   * aparte (`/api/secretario/anteriores`, no el sondeo) y siempre es lo que va
   * justo antes del globo más viejo pintado: cargar un hilo suelto dejaría
   * huecos que el cursor se saltaría. Sólo se pinta: ni se lee en voz alta,
   * ni se anuncia, ni quita las ideas del chat vacío, ni mueve lo que se
   * estaba leyendo. Cada conversación lleva su separador, y el de la abierta
   * dice que lo de arriba el secretario sólo lo recuerda por su resumen: lo
   * verá en pantalla y creería que lo tiene delante (299). */
  const botonAnteriores = document.getElementById('sec-anteriores');
  const infoHilos = {};       // id del hilo → { titulo, abierto_local, cerrado, resumido }
  // El que dice el sondeo (`null`: ninguno); hasta que hable, el de lo que
  // pintó el servidor, y sin eso no se sabe (`undefined`).
  let hiloAbierto;
  let trayendo = null;        // una petición de lo anterior a la vez
  const globos = () => [...chat.querySelectorAll('.burbuja')];
  const idDe = (n) => Number(n && n.dataset ? n.dataset.turno : NaN);
  const esSeparador = (n) => !!n && !!n.classList && n.classList.contains('sep-hilo');
  {
    const pintados = globos();
    if (pintados.length && pintados[pintados.length - 1].dataset.hilo) hiloAbierto = pintados[pintados.length - 1].dataset.hilo;
  }
  function rotuloHilo(h) {
    const info = infoHilos[h];
    const abierta = hiloAbierto !== undefined ? String(h) === String(hiloAbierto) : !!info && !info.cerrado;
    if (abierta) return 'Esta conversación · lo de arriba lo recuerda sólo por su resumen';
    if (!info) return 'Conversación anterior';
    return `Conversación del ${info.abierto_local}` + (info.titulo ? ` · ${info.titulo}` : '')
           + (info.resumido ? ' · resumida' : '');
  }
  /* Un separador delante del primer globo de cada conversación, en cuanto
   * hay más de una pintada. Una sola regla para lo anterior y para el sondeo:
   * una conversación nueva con la página abierta se pegaba a la vieja sin
   * marca. No rehace lo que ya está bien: se llama en cada sondeo con turnos. */
  // Si una conversación pintada ya no es la de ahora.
  const esAnterior = (h) => (hiloAbierto !== undefined ? String(h) !== String(hiloAbierto)
                                                        : !!infoHilos[h] && !!infoHilos[h].cerrado);
  function separar() {
    const lista = globos();
    const hilos = new Set(lista.map(g => g.dataset.hilo || ''));
    // Con una sola, también si no es la de ahora (tras la revisión): por la
    // mañana, sin hilo abierto, salían los globos de ayer sin nada que dijera
    // que son de antes ni que él ya no los tiene delante.
    const sola = hilos.size === 1 ? [...hilos][0] : '';
    const varios = hilos.size > 1 || (sola !== '' && esAnterior(sola));
    const quedan = new Set();
    let previo = null;
    for (const g of lista) {
      const h = g.dataset.hilo || '';
      if (varios && h !== previo) {
        let sep = g.previousElementSibling;
        if (!esSeparador(sep) || sep.dataset.sep !== h) {
          sep = document.createElement('p');
          sep.className = 'sep-hilo';
          sep.dataset.sep = h;
          chat.insertBefore(sep, g);
        }
        const texto = rotuloHilo(h);
        if (sep.textContent !== texto) sep.textContent = texto;
        quedan.add(sep);
      }
      previo = h;
    }
    [...chat.querySelectorAll('.sep-hilo')].forEach(s => { if (!quedan.has(s)) s.remove(); });
  }
  // En su sitio por id, y una vez: el mismo turno puede llegar también por el sondeo.
  function ponerAnterior(t) {
    if (!t || t.id === undefined || t.id === null || chat.querySelector(`[data-turno="${t.id}"]`)) return;
    const nodo = document.createElement('div');
    pintar(nodo, t);
    let ref = globos().find(g => idDe(g) > Number(t.id)) || null;
    if (ref && esSeparador(ref.previousElementSibling)) ref = ref.previousElementSibling;
    // Sin nada después, encima de las ideas del chat vacío: siguen debajo.
    const vacio = document.getElementById('sec-vacio');
    if (!ref && vacio && vacio.parentNode === chat) ref = vacio;
    chat.insertBefore(nodo, ref);
  }
  /* Lo que crece por arriba no mueve lo que se lee: pegado al final, sigue
   * pegado; si había subido, se le suma al scroll lo que creció. */
  function sinMover(cambiar) {
    const alto = chat.scrollHeight;
    const arriba = chat.scrollTop;
    const alFinal = pegado;
    cambiar();
    if (alFinal) { bajar(); return; }
    chat.scrollTop = arriba + (chat.scrollHeight - alto);
    puesto = chat.scrollTop;
  }
  // `n`: cuántos (el servidor lo acota). `diciendo`: si falla, decirlo; al
  // cargar solo, un fallo no merece la línea roja.
  function cargarAnteriores(n, diciendo) {
    if (!trayendo) trayendo = traerAnteriores(n, diciendo).finally(() => { trayendo = null; });
    return trayendo;
  }
  async function traerAnteriores(n, diciendo) {
    const ids = globos().map(idDe).filter(x => x > 0);
    const antesDe = ids.length ? Math.min(...ids) : 0;
    if (botonAnteriores) botonAnteriores.disabled = true;
    let d;
    try {
      const r = await fetch(`/api/secretario/anteriores?antes_de=${antesDe}` + (n ? `&n=${n}` : ''), { cache: 'no-store' });
      d = await r.json();
    } catch (e) {
      if (diciendo) avisar('no pude traer lo anterior: el hub no contesta', 'error');
      return null;
    } finally {
      if (botonAnteriores) botonAnteriores.disabled = false;
    }
    if (!d || !Array.isArray(d.turnos)) return null;
    Object.assign(infoHilos, d.hilos || {});
    // El botón también cambia el alto: dentro, o al cargar faltaban por bajar
    // sus 40-56 px donde no hay anclaje de scroll (Safari; tras la revisión).
    sinMover(() => {
      d.turnos.forEach(ponerAnterior);
      separar();
      if (botonAnteriores) botonAnteriores.hidden = !d.hay_mas;
    });
    return d;
  }
  if (botonAnteriores) botonAnteriores.addEventListener('click', () => cargarAnteriores(0, true));
  /* Abrir una conversación de la lista (`/secretario?hilo=<id>`): se cargan
   * páginas seguidas hasta alcanzarla —siempre contiguo, nunca un hilo
   * suelto— y se baja a su separador. Con tope: si no llega, se dice. */
  const PAGINAS_PARA_IR = 10;
  const POR_PAGINA_PARA_IR = 50;
  async function irAHilo(h) {
    h = Number(h);
    const pasada = () => globos().some(g => Number(g.dataset.hilo) < h);
    let mas = true;
    for (let i = 0; i < PAGINAS_PARA_IR && mas && !pasada(); i++) {
      const d = await cargarAnteriores(POR_PAGINA_PARA_IR, true);
      if (!d) return;      // no contestó: ya lo dijo
      mas = !!d.hay_mas;
    }
    const primero = globos().find(g => Number(g.dataset.hilo) === h);
    if (!primero) {
      avisar(mas && !pasada() ? 'Esa conversación queda más atrás: pulsa «Ver lo anterior» para seguir.'
                              : 'Esa conversación no tiene mensajes.', 'aviso');
      return;
    }
    const sep = esSeparador(primero.previousElementSibling) ? primero.previousElementSibling : primero;
    sep.scrollIntoView({ block: 'start' });
    // Ya no está al final: lo que llegue no lo baja.
    pegado = false;
    puesto = -1;
  }
  /* Lo adjunto de hace más de diez días ya no está en el intercambio (288):
   * la miniatura que no carga deja su nombre, no una imagen rota. */
  chat.addEventListener('error', e => {
    const img = e.target;
    if (!img || img.tagName !== 'IMG' || !img.closest || !img.closest('.adjuntos')) return;
    const nombre = document.createElement('span');
    nombre.className = 'ido';
    nombre.textContent = img.alt || 'imagen';
    nombre.title = 'Ya no está: lo adjunto se guarda diez días';
    (img.closest('a') || img).replaceWith(nombre);
  }, true);

  /* «Respondiendo a…» (C-0243): la cita que sale con el próximo mensaje.
   * Los oyentes van en `#sec-chat` y no en cada globo: `pintar` rehace su
   * contenido en cada sondeo y un oyente puesto en el ↩ se perdería. */
  const citando = document.getElementById('sec-citando');
  let cita = null;
  function citar(nodo) {
    if (!nodo || !nodo.dataset || nodo.dataset.estado !== 'listo' || !/^\d+$/.test(String(nodo.dataset.turno || ''))) return;
    cita = { id: Number(nodo.dataset.turno) };
    if (citando) {
      citando.querySelector('[data-citando-quien]').textContent = QUIEN[nodo.dataset.rol] || '';
      citando.querySelector('[data-citando-texto]').textContent = (nodo.dataset.texto || '').slice(0, 300);
      citando.hidden = false;
    }
    cuadro.focus();
  }
  function quitarCita() {
    cita = null;
    if (citando) citando.hidden = true;
  }
  const quitarBoton = document.getElementById('sec-citando-quitar');
  if (quitarBoton) quitarBoton.addEventListener('click', () => { quitarCita(); cuadro.focus(); });
  /* «Copiar» de un bloque de código (C-0306): lo que se ve, sin las marcas.
   * Con el plan B de la terminal (`execCommand`): el permiso del portapapeles
   * se puede denegar, y un «Copiado» sin copiar sería peor que nada. */
  async function copiarCodigo(boton) {
    const codigo = boton.parentElement && boton.parentElement.querySelector('code');
    const texto = codigo ? codigo.textContent : '';
    let ok = false;
    try {
      await navigator.clipboard.writeText(texto);
      ok = true;
    } catch (e) {
      try {
        const caja = document.createElement('textarea');
        caja.value = texto;
        caja.style.cssText = 'position:fixed;top:-9999px;opacity:0';
        document.body.appendChild(caja);
        caja.select();
        ok = document.execCommand('copy');
        caja.remove();
      } catch (e2) { ok = false; }
    }
    boton.textContent = ok ? 'Copiado' : 'No se pudo copiar';
    setTimeout(() => { boton.textContent = 'Copiar'; }, 1600);
  }
  chat.addEventListener('click', e => {
    const t = e.target;
    if (!t || !t.closest) return;
    const copiar = t.closest('[data-copiar-codigo]');
    if (copiar) { copiarCodigo(copiar); return; }
    if (t.closest('[data-citar]')) { citar(t.closest('.burbuja')); return; }
    const ir = t.closest('[data-ir]');
    if (ir) {
      const original = chat.querySelector(`[data-turno="${ir.dataset.ir}"]`);
      if (!original) { avisar('ese mensaje ya no está en esta conversación'); return; }
      const quieto = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
      original.scrollIntoView({ block: 'center', behavior: quieto ? 'auto' : 'smooth' });
      original.classList.add('resaltado');
      setTimeout(() => original.classList.remove('resaltado'), 1600);
    }
  });
  // Doble clic EN EL HUECO al lado de un globo, no encima: encima, el doble
  // clic selecciona una palabra, como en WhatsApp Web.
  chat.addEventListener('mousedown', e => { if (e.detail > 1 && e.target === chat) e.preventDefault(); });
  chat.addEventListener('dblclick', e => {
    if (e.target !== chat) return;
    const cajas = [...chat.querySelectorAll('.burbuja')].map(n => {
      const r = n.getBoundingClientRect();
      return { id: n.dataset.turno, top: r.top, bottom: r.bottom };
    });
    const id = turnoEnAltura(cajas, e.clientY);
    if (id) citar(chat.querySelector(`[data-turno="${id}"]`));
  });

  /* El globo (C-0201, decisión 379): lo que te espera y aún no has visto.
   * La cifra viene en la espera que ya trae el sondeo (`espera.asuntos`, la
   * instantánea que deja hub-secretario) y, al cargar, en la del personaje
   * (`data-espera`): no se pregunta nada aparte. Nunca avisa fuera de aquí.
   * Se llama como el bloque al que lleva (C-0231): «Tiene una sugerencia o
   * una pregunta» era un tercer nombre para lo mismo. Y dice «nuevas», como
   * el modo monitor (C-0367): el bloque tiene más, y «Te espera: 4» al lado
   * de «Te espera 77» parecían dos cifras de lo mismo. */
  const globo = document.getElementById('sec-globo');
  function pintarGlobo(espera) {
    if (!globo) return;
    const n = Math.max(0, Math.floor(Number(espera && espera.asuntos && espera.asuntos.nuevas) || 0));
    globo.hidden = n === 0;
    const texto = globo.querySelector ? globo.querySelector('[data-globo-texto]') : null;
    if (texto && n > 0) {
      texto.textContent = `Te espera: ${n} ${n === 1 ? 'nueva' : 'nuevas'}`;
    }
    // Va encima del chat y lo encoge (C-0303): sin esperar al ResizeObserver.
    seguirAlFinal();
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
  let hayPermisosAlCargar = false;
  try {
    const portador = document.querySelector('[data-espera]');
    const inicial = JSON.parse((portador && portador.dataset && portador.dataset.espera) || 'null');
    pintarGlobo(inicial);
    seguirLaEspera(inicial);
    hayPermisosAlCargar = !!(inicial && inicial.solicitudes > 0);
  } catch (e) { pintarGlobo(null); }

  /* ── «Pide tu permiso» (C-0421) ──
   * Lo que el secretario espera que apruebes sale aquí, al final del chat:
   * antes había que irse a Pendientes para decir que sí a lo que él mismo
   * acababa de pedir. Viene en el sondeo (`permisos`, la misma lectura que
   * Pendientes) y se decide por la ruta que ya usaba la notificación.
   * 🔴 Todo con `textContent`: el motivo y los datos los escribe el modelo, y
   * lo que se aprueba puede acabar en una terminal. Y enteros, sin plegar:
   * se decide viendo el texto exacto (395); si es largo, la caja desplaza.
   * Una tarjeta por solicitud, que no se rehace en cada sondeo: rehacerla
   * a mitad de un toque lo perdía, y devolvía el scroll arriba. */
  const permisos = document.getElementById('sec-permisos');
  const tarjetasPermiso = new Map();    // id de la solicitud → { nodo, botones, yendo }
  function crear(etiqueta, clase, texto) {
    const n = document.createElement(etiqueta);
    if (clase) n.className = clase;
    if (texto !== undefined && texto !== null) n.textContent = String(texto);
    return n;
  }
  function tarjetaPermiso(p) {
    const sid = String(p.id);
    const nodo = crear('div', p.con_techo ? 'permiso con-techo' : 'permiso');
    nodo.dataset.sid = sid;
    nodo.appendChild(crear('span', 'rotulo', 'Pide tu permiso'));
    nodo.appendChild(crear('strong', 'nombre', p.nombre || p.accion || ''));
    if (p.motivo) nodo.appendChild(crear('p', 'motivo', p.motivo));
    // La orden para su PC, aparte y tal cual: es lo que se va a correr.
    if (p.orden) nodo.appendChild(crear('code', 'orden', p.orden));
    const datos = Array.isArray(p.datos) ? p.datos : [];
    if (datos.length) {
      const lista = crear('dl', 'datos');
      for (const par of datos) {
        lista.appendChild(crear('dt', '', par[0]));
        lista.appendChild(crear('dd', '', par[1]));
      }
      nodo.appendChild(lista);
    }
    if (p.riesgo_rotulo) nodo.appendChild(crear('span', 'riesgo', p.riesgo_rotulo));
    // Cuándo lo pidió (C-0395): para no aprobar a ciegas algo de hace horas.
    if (p.creada_local) nodo.appendChild(crear('span', 'cuando', `Lo pidió el ${p.creada_local}`));
    const fila = crear('div', 'botones');
    const t = { nodo, botones: [], yendo: false, conservar: false, porQue: null, texto: null, fila };
    [['Rechazar', 'boton', () => decidirPermiso(sid, 'rechazar', '')],
     ['Rechazar y decir por qué', 'boton', () => abrirPorQue(t, sid)],
     ['Aprobar', 'boton aceptar', () => decidirPermiso(sid, 'aprobar', '')]].forEach(([texto, clase, alPulsar]) => {
      const b = crear('button', clase, texto);
      b.type = 'button';
      b.addEventListener('click', alPulsar);
      fila.appendChild(b);
      t.botones.push(b);
    });
    nodo.appendChild(fila);
    return t;
  }
  /* «Rechazar y decir por qué» (C-0395): el campo, dentro de la tarjeta y
   * hecho al pulsarlo; ni un diálogo ni el cuadro de escribir. La tarjeta no
   * se rehace en cada sondeo, así que lo escrito a medias no se pierde, y si
   * el hub no contesta sigue ahí. El motivo viaja con el rechazo: antes iba
   * aparte, y con dos rechazadas el secretario no sabía a cuál contestaba. */
  function abrirPorQue(t, sid) {
    if (!t.porQue) {
      t.porQue = crear('div', 'por-que');
      t.texto = crear('textarea');
      t.texto.rows = 2;
      t.texto.placeholder = 'Qué estaba mal: le llega como un mensaje tuyo';
      t.texto.setAttribute('aria-label', 'Por qué la rechazas');
      t.porQue.appendChild(t.texto);
      const fila = crear('div', 'botones');
      t.cancelar = crear('button', 'boton', 'Cancelar');
      t.cancelar.type = 'button';
      t.cancelar.addEventListener('click', () => {
        // Ya resuelta en otro sitio, no queda nada que decidir: se quita.
        if (t.conservar) { t.conservar = false; quitarPermiso(sid); return; }
        t.porQue.hidden = true;
        t.fila.hidden = false;
      });
      const mandar = crear('button', 'boton', 'Rechazar');
      mandar.type = 'button';
      mandar.addEventListener('click', () => decidirPermiso(sid, 'rechazar', t.texto.value));
      fila.appendChild(t.cancelar);
      fila.appendChild(mandar);
      t.porQue.appendChild(fila);
      t.filaPorQue = fila;
      t.nodo.appendChild(t.porQue);
      t.botones.push(mandar);
    }
    t.fila.hidden = true;
    t.porQue.hidden = false;
    if (t.texto.focus) t.texto.focus();
    // Con varias, la caja de permisos tiene tope y desplaza: sus botones
    // quedaban cortados por debajo (tras la revisión, panel a 1200 px).
    if (t.filaPorQue.scrollIntoView) t.filaPorQue.scrollIntoView({ block: 'nearest' });
  }
  function quitarPermiso(sid) {
    const t = tarjetasPermiso.get(sid);
    if (!t) return;
    t.nodo.remove();
    tarjetasPermiso.delete(sid);
    if (permisos) permisos.hidden = tarjetasPermiso.size === 0;
  }
  function pintarPermisos(lista) {
    if (!permisos) return;
    const vivos = new Set();
    // Llegan las más nuevas primero; se leen en el orden en que las pidió.
    for (const p of [...(Array.isArray(lista) ? lista : [])].reverse()) {
      const sid = String(p.id);
      vivos.add(sid);
      if (tarjetasPermiso.has(sid)) continue;
      const t = tarjetaPermiso(p);
      tarjetasPermiso.set(sid, t);
      permisos.appendChild(t.nodo);
    }
    // La que ya no espera (decidida aquí, en Pendientes o desde el teléfono)
    // se va; la que se está decidiendo ahora la quita su propia respuesta, y
    // la que guarda un porqué escrito se queda hasta que él la quite.
    for (const [sid, t] of [...tarjetasPermiso]) if (!vivos.has(sid) && !t.yendo && !t.conservar) quitarPermiso(sid);
    permisos.hidden = tarjetasPermiso.size === 0;
    // Va debajo del chat y lo encoge: lo último sigue a la vista (C-0303).
    seguirAlFinal();
  }
  /* `porQue`: lo que escribió en la tarjeta. Vacío es rechazar a secas; con
   * algo, entra como un mensaje suyo que cita el «No lo hago…», y el chat
   * se pone a esperar la respuesta como al mandar un mensaje (C-0395). */
  async function decidirPermiso(sid, decision, porQue) {
    sid = String(sid);
    const t = tarjetasPermiso.get(sid);
    // Dos toques seguidos son una sola decisión.
    if (!t || t.yendo) return;
    const motivo = decision === 'rechazar' ? String(porQue || '').trim() : '';
    t.yendo = true;
    t.botones.forEach(b => { b.disabled = true; });
    const cuerpo = { decision };
    if (motivo) cuerpo.por_que = motivo;
    let d;
    try {
      const r = await fetch(`/api/secretario/solicitud/${encodeURIComponent(sid)}`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(cuerpo),
      });
      d = await r.json();
    } catch (e) {
      // No se sabe si llegó: la tarjeta sigue, con lo escrito, y se puede
      // volver a tocar. Si llegó, el sondeo siguiente la quita.
      t.yendo = false;
      t.botones.forEach(b => { b.disabled = false; });
      avisar('no se pudo decidir: el hub no contesta', 'error');
      return;
    }
    t.yendo = false;
    if (d && d.ok) {
      quitarPermiso(sid);
      if (motivo) { esperando = true; avisar('pensando…'); }
    } else if (motivo) {
      // Ya estaba resuelta: no se le escribió nada, y lo que había escrito
      // se queda en la tarjeta para que no se pierda; «Cancelar» la quita.
      t.conservar = true;
      if (t.cancelar) t.cancelar.textContent = 'Quitar';
      avisar((d && d.error) || 'No se pudo decidir.', 'aviso');
    } else {
      quitarPermiso(sid);
      avisar((d && d.error) || 'No se pudo decidir.', 'aviso');
    }
    seguirAlFinal();
    // Lo que diga al hacerlo (o su «No lo hago…» y el motivo) son turnos
    // nuevos. Si no se decidió, la solicitud sigue pendiente y este sondeo
    // la vuelve a pintar.
    mirar().then(seguir);
  }

  /* Pregunta por lo nuevo. Un turno «escribiendo» se vuelve a pedir hasta que
   * cambie: por eso se pide desde el último que ya está terminado. */
  const SIN_RED = 'el hub no contesta; sigo intentando…';
  const DETENIENDO = 'deteniendo…';
  async function mirar() {
    let d;
    try {
      const r = await fetch(`/api/secretario/turnos?desde=${ultimo}`, { cache: 'no-store' });
      d = await r.json();
    } catch (e) {
      avisar(SIN_RED, 'error');
      contar({ red: 'caida' });
      return;
    }
    // De vuelta: el «sigo intentando» se quedaba escrito con el hub ya contestando.
    if (estado && estado.textContent === SIN_RED) avisar('');
    contar({ red: 'ok', turnos: d.turnos || [], ...('espera' in d ? { espera: d.espera } : {}) });
    if ('espera' in d) { pintarGlobo(d.espera); seguirLaEspera(d.espera); }
    if ('permisos' in d) pintarPermisos(d.permisos);
    if ('ingles' in d) seguirElIngles(d.ingles);
    const otroHilo = 'hilo' in d && String(d.hilo ?? '') !== String(hiloAbierto ?? '');
    if ('hilo' in d) hiloAbierto = d.hilo ?? null;
    let pendiente = false;
    let enCurso = null;
    for (const t of d.turnos || []) {
      ponerTurno(t);
      const abierto = t.estado === 'escribiendo' || t.estado === 'pendiente' || t.estado === 'atendiendo';
      if (abierto) pendiente = true;
      else if (!pendiente) ultimo = Math.max(ultimo, Number(t.id));
      if (enCurso === null && t.rol === 'dueno' && (t.estado === 'pendiente' || t.estado === 'atendiendo')) {
        enCurso = Number(t.id);
      }
    }
    // Parado o terminado, lo dice el sondeo y no la respuesta del POST (C-0506, regla 17).
    if (enCurso !== turnoEnCurso) deteniendo = null;
    turnoEnCurso = enCurso;
    if (enCurso === null && estado && estado.textContent === DETENIENDO) avisar('');
    pintarEnviar();
    if (otroHilo || (d.turnos || []).length) separar();
    esperando = pendiente;
    quitarHueco();
    quizaAnteriores();
    verSiContesta(d.vivo, pendiente);
    verSiLoEmpieza(d.turnos || [], d.vivo);
    if (estado && !pendiente && estado.textContent === 'pensando…') estado.textContent = '';
    if (!pendiente && continuo && panelVoz && panelVoz.dataset.fase === 'pensando') fase('', '');
  }
  /* Sin `hub-secretario` (C-0302): lo escrito entra en la base y no lo
   * contesta nadie hasta que arranque. El chat se quedaba «pensando…» para
   * siempre —desde el panel de otra pantalla parecía perdido— y preguntando
   * cada 1,5 s. Se dice tras unos segundos esperando (puede estar arrancando,
   * y un reinicio no llega a dejar de latir: su latido vale dos minutos), con
   * el enlace a su pantalla, que dice por qué y ofrece encenderlo (400). */
  const SIN_SECRETARIO = 'El secretario no está en marcha: lo contestará al volver.';
  const ESPERA_APAGADO_MS = 5000;
  const verQueLePasa = document.getElementById('sec-apagado');
  let esperaDesde = 0;
  let apagado = false;
  function verSiContesta(vivo, pendiente) {
    if (!pendiente) esperaDesde = 0;
    else if (!esperaDesde) esperaDesde = Date.now();
    const antes = apagado;
    apagado = pendiente && vivo === false && Date.now() - esperaDesde >= ESPERA_APAGADO_MS;
    if (verQueLePasa) verQueLePasa.hidden = !apagado;
    if (apagado && !antes) {
      if (continuo) pausar(SIN_SECRETARIO, dichoEn('El secretario no está en marcha: te contestará cuando vuelva.',
                                                    'The secretary is not running: it will answer when it is back.'));
      else avisar(SIN_SECRETARIO, 'aviso');
    } else if (antes && !apagado) {
      // De vuelta. El modo voz sigue en pausa hasta «Seguir» (el micrófono no
      // se abre solo), pero ya no dice que está parado.
      if (continuo && pausado && vozEstado && vozEstado.textContent === SIN_SECRETARIO) {
        fase('pausa', 'Ya está en marcha: pulsa Seguir.');
      } else if (estado && estado.textContent === SIN_SECRETARIO) avisar(pendiente ? 'pensando…' : '');
    }
  }
  /* La cola callada (VOZ-28, C-0362): lo dicho espera a veces a que el
   * secretario lo tome —acaba otro turno, o el servicio se reinicia— y se
   * midieron esperas de 56 s y 124 s con el panel en «pensando…». En el modo
   * voz el silencio se lee como «no me oyó», y se repite o se va. Si su turno
   * sigue `pendiente` (no `atendiendo`) a los `COLA_MS`, dice «un momento»
   * una vez y, si lo sabe, por qué. Sin secretario en marcha no: eso lo dice
   * `verSiContesta`, que pausa. */
  const COLA_MS = 3000;
  let enCola = { id: null, desde: 0, dicho: false };
  function verSiLoEmpieza(turnos, vivo) {
    const suyo = [...turnos].reverse().find(t => t.rol === 'dueno' && t.estado === 'pendiente');
    if (!suyo) { enCola = { id: null, desde: 0, dicho: false }; return; }
    if (enCola.id !== suyo.id) enCola = { id: suyo.id, desde: Date.now(), dicho: false };
    if (enCola.dicho || !continuo || pausado || vivo === false || Date.now() - enCola.desde < COLA_MS) return;
    enCola.dicho = true;
    const otro = turnos.some(t => Number(t.id) < Number(suyo.id)
                                  && ['pendiente', 'atendiendo', 'escribiendo'].includes(t.estado));
    // Lo entendido sigue a la vista (C-0289): se añade, no se pisa.
    const entendido = vozEstado && panelVoz.dataset.fase === 'pensando' ? vozEstado.textContent : '';
    fase('pensando', (entendido ? `${entendido} · ` : '')
                     + (otro ? 'Un momento: está acabando lo anterior.' : 'Un momento: aún no lo ha empezado.'));
    decir(dichoEn('Un momento.', 'One moment.'));
  }
  // Rápido mientras se espera una respuesta; despacio el resto del tiempo
  // (una aprobación desde otro aparato también deja un turno). El rápido es
  // una cadena que se corta sola al llegar la respuesta.
  // En el modo voz, a 300 ms: es lo que tarda en empezar a leer cada frase. Y
  // leyendo en voz alta fuera de él, igual: lee del mismo modo (VOZ-23).
  // Una sola cadena a la vez: llamarla de más no duplica el sondeo. Y la
  // arranca también quien descubre un turno abierto sin haberlo mandado (el
  // sondeo lento, desplegar el panel): un mensaje desde el teléfono se quedaba
  // aquí «pensando» para siempre, porque nadie empezaba la cadena (C-0166).
  // Sin nadie que conteste (C-0302), cada 6 s y sólo con la pestaña a la vista:
  // al volver a ella, la cadena sigue.
  let cadena = null;
  function seguir() {
    if (!esperando || cadena || (apagado && document.hidden)) return;
    cadena = setTimeout(() => { cadena = null; mirar().then(seguir); }, apagado ? 6000 : continuo || leerEnVoz() ? 300 : 1500);
  }
  // En el panel plegado no se pregunta: cada sondeo abre la memoria, y en
  // todas las pestañas a la vez eso es ruido. Al desplegarlo se pone al día.
  // Con la regla común (`HubSondeo`, C-0277): oculta la pestaña, se calla, y
  // al volver pregunta enseguida.
  const plegado = () => { const p = chat.dataset.cargar && document.getElementById('secretario-panel');
                          return !!p && !p.classList.contains('abierto'); };
  const cada = (window.HubSondeo && window.HubSondeo.cada) || ((fn, ms) => setInterval(fn, ms));
  cada(() => { if (!esperando && !plegado()) mirar().then(seguir); }, 6000);
  // Al volver a la pestaña, una vez y plegado: el personaje de una pantalla
  // abierta horas (/trabajo) no puede seguir enseñando lo de antes. Desplegado
  // ya lo hace el sondeo de arriba.
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) return;
    if (!esperando && chat.dataset.cargar && !cargando && plegado()) mirar().then(seguir);
    seguir();
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
    pintarEnviar();
  }
  // Devuelve '' si subió, o por qué no: mandar no sale sin lo que falló.
  async function subir(archivo, pegado) {
    const datos = new FormData();
    datos.append('archivo', archivo, archivo.name || 'imagen.png');
    // Pegado del portapapeles: se llama con su hora, como en la terminal.
    if (pegado) datos.append('pegado', '1');
    avisar(`subiendo ${archivo.name || 'imagen'}…`);
    try {
      const r = await fetch('/api/secretario/adjuntar', { method: 'POST', body: datos });
      const d = await r.json();
      if (!d.ok) {
        avisar(`no se adjuntó: ${d.error}`, 'error');
        return `${archivo.name || 'la imagen'} no se adjuntó (${d.error})`;
      }
      adjuntos.push({ ruta: d.ruta, imagen: !!d.imagen });
      pintarPorMandar();
      avisar('');
      return '';
    } catch (e) {
      avisar('no se adjuntó: el hub no contesta', 'error');
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
  // `dictado`: el texto salió de Whisper y nadie lo tocó (C-0291).
  // `delCuadro`: es lo escrito en el cuadro, y si no sale ahí sigue (C-0305).
  async function enviar(texto, conCita = true, dictado = false, delCuadro = false) {
    if (enviando) return;
    enviando = true;
    try { await enviarYa(texto, conCita, dictado, delCuadro); } finally { enviando = false; }
  }
  /* Lo que no salió (C-0305): se dice como fallo y espera a «Reintentar». En
   * el modo voz no hay cuadro a la vista ni nadie mirando la pantalla: se
   * pausa y se dice en voz alta, como un fallo del micrófono. Antes el panel
   * se quedaba en «transcribiendo» sin volver a escuchar, y lo dicho se perdía. */
  function noSalio(motivo, pendiente) {
    // Lo del cuadro sigue en el cuadro: se apunta que hay que mandarlo, no qué.
    if (pendiente.delCuadro) porReintentar.cuadro = true; else porReintentar.mensaje = pendiente;
    pintarReintentar();
    if (continuo) pausar(motivo, dichoEn('Pausé el micrófono: no pude mandar lo que dijiste.',
                                         'I paused the microphone: I could not send what you said.'));
    else avisar(motivo, 'error');
  }
  async function enviarYa(texto, conCita = true, dictado = false, delCuadro = false) {
    texto = (texto || '').trim();
    const pendiente = { texto, conCita, dictado, delCuadro };
    if (subidas.length) {
      avisar('terminando de subir…');
      // Lo que no subió no puede irse callado: él creería que lo mandó.
      const fallos = (await Promise.all(subidas)).filter(Boolean);
      if (fallos.length) {
        noSalio(`no se mandó: ${fallos[0]}. Pulsa Reintentar para mandarlo sin eso.`, pendiente);
        return;
      }
    }
    // Con algo adjunto, el texto puede ir vacío: una captura sola ya pregunta.
    // Sin nada que mandar, tampoco queda nada que reintentar.
    if (!texto && !adjuntos.length) { despachado(pendiente); return; }
    // `voz`: se le va a leer, en el modo voz o con la casilla (VOZ-23).
    const cuerpo = { texto, voz: continuo || leerEnVoz() };
    if (dictado) cuerpo.dictado = true;
    // Lo que pregunta «Guíame» no contesta a nada: la cita espera a lo suyo.
    if (cita && conCita) cuerpo.responde_a = cita.id;
    const mandados = adjuntos.map(a => a.ruta);
    if (mandados.length) cuerpo.adjuntos = mandados;
    const desde = pantallaActual();
    if (desde) cuerpo.pantalla = desde;
    // La ventana que miras, para que pueda leerla si le hablas de ella (C-0162).
    const enfoque = desde && document.body && document.body.dataset ? document.body.dataset.enfoque : '';
    if (enfoque) cuerpo.enfoque = enfoque;
    avisar('enviando…');
    try {
      const r = await fetch('/api/secretario/mensaje', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        // Con `voz` el secretario contesta corto y para el oído (C-0155, VOZ-21).
        body: JSON.stringify(cuerpo),
      });
      const d = await r.json();
      if (!d.ok) { noSalio(`no se envió: ${d.error}`, pendiente); return; }
      // Salió: si era lo que esperaba a «Reintentar», ya no espera (lo grabado sin subir, sí).
      despachado(pendiente);
      cuadro.value = '';
      dictadoEnCuadro = null;
      cuadro.style.height = '';
      if (conCita) quitarCita();
      // Sólo lo mandado: lo que terminó de subir mientras tanto espera al siguiente.
      adjuntos = adjuntos.filter(a => !mandados.includes(a.ruta));
      pintarPorMandar();
      esperando = true;
      contar({ enviado: Date.now() });
      // En el modo voz, lo entendido a la vista mientras piensa (C-0289): si
      // oyó mal, se ve de un vistazo y se le interrumpe antes de que actúe.
      fase('pensando', continuo && texto ? `Entendí: «${recortar(texto, 160)}»` : 'pensando…');
      mirar().then(seguir);
    } catch (e) {
      noSalio(`no se envió: el hub no contesta${delCuadro ? '. Lo escrito sigue en el cuadro' : ''}`, pendiente);
    }
  }
  const recortar = (s, n) => (s.length > n ? s.slice(0, n - 1).trimEnd() + '…' : s);
  /* Lo dictado al cuadro (C-0291): si se manda tal cual, sigue siendo lo que
   * oyó Whisper y va marcado; si lo tocó, ya es suyo. */
  let dictadoEnCuadro = null;
  const enviarCuadro = () => enviar(cuadro.value, true, dictadoEnCuadro !== null && cuadro.value === dictadoEnCuadro, true);
  // Lo decide lo que hay ahora y no cómo quedó pintado: un texto dictado al
  // cuadro no dispara `input`, y el botón no puede tragarse lo que él escribió.
  formulario.addEventListener('submit', e => {
    e.preventDefault();
    if (turnoEnCurso !== null && !hayQueMandar()) { detener(); return; }
    enviarCuadro();
  });
  // El cuadro crece con lo que se escribe, hasta su tope; luego desplaza.
  const ajustar = () => { cuadro.style.height = 'auto'; cuadro.style.height = `${cuadro.scrollHeight + 2}px`; };
  cuadro.addEventListener('input', ajustar);
  cuadro.addEventListener('input', pintarEnviar);

  /* ── Detener (C-0506) ──
   * Mientras contesta y no hay nada por mandar, el botón de enviar es
   * «Detener»; con algo escrito o adjunto vuelve a ser «Enviar» (lo escrito
   * entra en cola, como siempre). Pedirlo no es haberlo hecho (regla 17): el
   * POST sólo deja la petición, y «Detenido.» lo pinta el sondeo de siempre
   * cuando el secretario de verdad paró. Corta entre herramientas: lo hecho
   * queda hecho y lo que pidió permiso sigue en Pendientes. */
  function hayQueMandar() { return !!cuadro.value.trim() || adjuntos.length > 0 || subidas.length > 0; }
  function pintarEnviar() {
    const parar = turnoEnCurso !== null && !hayQueMandar();
    if (botonEnviar) {
      botonEnviar.dataset.modo = parar ? 'detener' : '';
      botonEnviar.setAttribute('aria-label', parar ? 'Detener' : 'Enviar');
      botonEnviar.title = parar ? 'Detener la respuesta (lo ya hecho queda hecho)' : 'Enviar';
      const enviarIco = botonEnviar.querySelector('[data-ico="enviar"]');
      const detenerIco = botonEnviar.querySelector('[data-ico="detener"]');
      if (enviarIco) enviarIco.hidden = parar;
      if (detenerIco) detenerIco.hidden = !parar;
    }
    if (vozDetener) vozDetener.hidden = turnoEnCurso === null;
  }
  function acabarDetenidoEnVoz(t) {
    detenidoEnVoz = null;
    if (!continuo || pausado) return;
    // Pudo acabar solo antes de que la petición llegara (gana lo terminado):
    // entonces no se dice «Detenido.», y la respuesta entera está en el chat.
    const parado = /Detenido\.$|Detenido\.\s/.test(String(t && t.texto || ''));
    const dicho = parado ? dichoEn('Detenido.', 'Stopped.')
                         : dichoEn('Ya había terminado.', 'It had already finished.');
    fase('hablando', dicho);
    decir(dicho, () => { if (continuo && !pausado) hablar(); });
  }
  async function detener() {
    const id = turnoEnCurso;
    if (id === null || deteniendo === id) return;
    deteniendo = id;
    // En el modo voz, como interrumpirle hablando (318) y además el POST:
    // se calla y no lee lo que quede de esa respuesta.
    if (continuo) { detenidoEnVoz = id; callarTodo(); fase('pensando', dichoEn('Deteniendo…', 'Stopping…')); }
    else { locutor.olvidar(); VOZ.callar(); avisar(DETENIENDO); }
    let d;
    try {
      const r = await fetch('/api/secretario/detener', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ turno: id }),
      });
      d = await r.json();
    } catch (e) {
      d = { ok: false, error: 'el hub no contesta' };
    }
    if (!d.ok || d.ya_terminado) {
      deteniendo = null;
      const enVoz = detenidoEnVoz !== null;
      detenidoEnVoz = null;
      if (d.ok) {
        // Gana lo terminado: su respuesta ya está entera en el chat.
        if (enVoz && continuo) { fase('', ''); if (!pausado) hablar(); } else avisar('ya había terminado');
      } else if (enVoz && continuo) {
        pausar(`no se pudo detener: ${d.error}`, dichoEn('No pude detenerlo.', 'I could not stop it.'));
      } else avisar(`no se pudo detener: ${d.error}`, 'error');
    }
    mirar().then(seguir);
  }
  if (vozDetener) vozDetener.addEventListener('click', () => detener());
  document.querySelectorAll('[data-idea]').forEach(b => b.addEventListener('click', () => enviar(b.textContent)));
  cuadro.addEventListener('keydown', e => {
    if (e.key === 'Escape' && cita) { e.preventDefault(); quitarCita(); return; }
    // Enter manda, Mayús+Enter es salto de línea: como cualquier chat.
    if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); enviarCuadro(); }
  });

  /* ── la voz de vuelta ──
   * Qué se dice de cada frase lo decide `paraOir`, pura y fuera de aquí. */
  /* Cómo suena: la única pieza que sabe de `speechSynthesis`. Otra voz
   * (Piper, ElevenLabs) es otro objeto con `decir(frase, fin)` y `callar()`;
   * el locutor y el modo voz no cambian. `decir` encola: frase tras frase.
   *
   * Con vigía (C-0288): Chrome, con voces de red, puede parar una frase larga
   * sin dar `onend`, y el modo voz se quedaba «hablando» sin volver a
   * escuchar nunca. Cada frase tiene un tope —unos 10 caracteres por segundo
   * y 3 s de margen, contado desde que acabaría la anterior de la cola—; si
   * vence, se calla la voz y lo que quedaba en cola se da por dicho, sin
   * repetirlo: es lo que el navegador ya no iba a decir. */
  const VOZ = {
    cola: [],     // las frases encoladas que aún no han acabado
    plazo: 0,     // cuándo debería haber acabado la última de la cola
    voces: [],    // las del navegador, en cuanto las da
    esperan: [],  // lo dicho antes de que las diera
    reloj: null,
    esperadas: false,
    hay: () => !!window.speechSynthesis,
    leerVoces() {
      try { VOZ.voces = window.speechSynthesis.getVoices() || []; } catch (e) { VOZ.voces = []; }
      return VOZ.voces;
    },
    /* Chrome da `getVoices()` vacío la primera vez y avisa con
     * `voiceschanged` (VOZ-24): sin esperar, la primera frase sonaba con la
     * voz que escogiera él y no con la elegida en este aparato. Se espera una
     * vez, como mucho `ESPERA_VOCES_MS`; luego, con lo que haya. */
    decir(frase, fin) {
      if (VOZ.leerVoces().length || VOZ.esperadas) { VOZ.ya(frase, fin); return; }
      VOZ.esperan.push([frase, fin]);
      if (VOZ.reloj) return;
      const listas = () => {
        if (!VOZ.reloj) return;
        clearTimeout(VOZ.reloj);
        VOZ.reloj = null;
        VOZ.esperadas = true;
        VOZ.leerVoces();
        const esperan = VOZ.esperan;
        VOZ.esperan = [];
        esperan.forEach(([f, alAcabar]) => VOZ.ya(f, alAcabar));
      };
      VOZ.reloj = setTimeout(listas, ESPERA_VOCES_MS);
      try { window.speechSynthesis.addEventListener('voiceschanged', listas); } catch (e) { /* sin el evento: vale el tope */ }
    },
    ya(frase, fin) {
      const u = new SpeechSynthesisUtterance(frase);
      // La voz y la velocidad de este aparato (VOZ-24), en el idioma del modo.
      // Sin una que se pueda usar no se lee (VOZ-22): se da por dicha, como
      // la que el navegador no dice, y el modo voz vuelve a escuchar.
      const ajustes = ajustesVoz();
      const idioma = enIngles() ? 'en' : 'es';
      if (!ponerVoz(u, idioma, VOZ.voces, ajustes)) {
        sinVoz(idioma, vocesDe(VOZ.voces, idioma).length > 0);
        setTimeout(fin, 0);
        return;
      }
      const esta = { hecho: false, reloj: null };
      esta.acabar = () => {
        if (esta.hecho) return;
        esta.hecho = true;
        clearTimeout(esta.reloj);
        VOZ.cola = VOZ.cola.filter(x => x !== esta);
        if (!VOZ.cola.length) VOZ.plazo = 0;
        fin();
      };
      u.onend = esta.acabar; u.onerror = esta.acabar;
      u.onboundary = latido;   // no todos los navegadores lo dan: el orbe late igual por CSS
      const ahora = Date.now();
      VOZ.plazo = Math.max(VOZ.plazo, ahora) + frase.length * 100 / ajustes.velocidad + 3000;
      esta.reloj = setTimeout(() => VOZ.atascada(), VOZ.plazo - ahora);
      VOZ.cola.push(esta);
      window.speechSynthesis.speak(u);
    },
    atascada() {
      const quedan = VOZ.cola;
      VOZ.cola = [];
      VOZ.plazo = 0;
      window.speechSynthesis.cancel();
      quedan.forEach(x => x.acabar());
    },
    // Callar no da nada por dicho: el `onend`/`onerror` de lo cancelado llega
    // como siempre. Sólo se quitan los topes, que callarían lo que venga después.
    callar() {
      VOZ.cola.forEach(x => clearTimeout(x.reloj));
      VOZ.cola = [];
      VOZ.esperan = [];
      VOZ.plazo = 0;
      if (window.speechSynthesis) window.speechSynthesis.cancel();
    },
  };
  const ESPERA_VOCES_MS = 1500;
  // Pedirlas ya: es lo que hace que Chrome empiece a cargarlas.
  if (VOZ.hay()) VOZ.leerVoces();
  /* Sin voz de este aparato, callado (VOZ-22, C-0359): la de red manda el
   * texto —su agenda, nombres de terceros— a Google o a Microsoft para
   * leerlo, y eso no lo ha decidido nadie (regla 22, decisión 302). Suena
   * sólo si él la elige en Ajustes → Voz. Se dice una vez por visita, y
   * «Elegir voz» se queda en la línea de abajo: en el modo voz esa línea se
   * borra en cada fase. */
  const enlaceSinVoz = document.getElementById('sec-sin-voz');
  let dichoSinVoz = false;
  function sinVoz(idioma, hayDeRed) {
    if (enlaceSinVoz) enlaceSinVoz.hidden = false;
    if (dichoSinVoz) return;
    dichoSinVoz = true;
    avisar(hayDeRed ? 'No te lo leo en voz alta: en este aparato sólo hay voces de red, que mandan el texto a internet.'
                      + ' Si te parece bien, elige una en Ajustes → Voz.'
                    : `No te lo leo en voz alta: este navegador no tiene ninguna voz ${idioma === 'en' ? 'en inglés' : 'en español'}.`,
           'aviso');
  }

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
      avanzar(texto, final, cerrado) {
        if (terminado) return;
        const r = frasesNuevas(dicho, texto, final, cerrado);
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
  /* La grabación en curso: la toma de `HubGrabar` con lo que el modo voz
   * necesita saber de ella. `descartar` (lo grabado es ruido o no cuenta) y
   * `reescuchar` (tras tirarlo, volver a escuchar) se marcan antes de
   * `stop()`; `atajo`, si se graba con Ctrl+Espacio. */
  let grabadora = null;
  // `mandar`: lo dicho sale solo, sin pasar por el cuadro (el atajo, C-0172).
  async function transcribir(audio, mandar) {
    if (estado) estado.textContent = 'transcribiendo…';
    contar({ voz: 'transcribiendo' });
    // Que no siga diciendo «te escucho…» con el micrófono ya cerrado (C-0289):
    // parecía que no le había oído, y en frío esto tarda unos segundos.
    if (continuo) fase('transcribiendo', 'te oí; lo paso a texto…');
    try { await transcribirYa(audio, mandar); } finally { if (!continuo) contar({ voz: '' }); }
  }
  /* Lo que espera a «Reintentar» (C-0314), cada cosa en su ranura: compartían
   * una, y dictar con el hub caído y luego escribir dejaba sólo el texto —el
   * audio se perdía al reintentar—.
   * - `audio`: lo grabado cuya subida falló (C-0287). Un corte de un segundo
   *   —la red del teléfono, `hub-web` reiniciando— costaba una explicación
   *   entera: `HubGrabar.subir` reintenta una vez sola y, si tampoco, espera
   *   aquí. Se descarta cuando llega otro audio; sólo vive en esta pestaña.
   * - `mensaje`: lo que no salió y no está en ningún cuadro (lo dictado que
   *   sale solo, una idea, «Guíame»), tal cual (C-0305).
   * - `cuadro`: lo escrito que no salió. Sigue en el cuadro y se manda como
   *   esté entonces; guardarlo aquí pisaría el `mensaje`.
   * Cada una se vacía cuando lo suyo se acepta y no al pulsar: `enviar`, con
   * otro mensaje saliendo, vuelve sin hacer nada. */
  const botonReintentar = document.getElementById('sec-reintentar');
  const porReintentar = { audio: null, mensaje: null, cuadro: false };
  function pintarReintentar() {
    if (botonReintentar) botonReintentar.hidden = !(porReintentar.audio || porReintentar.mensaje || porReintentar.cuadro);
  }
  // Salió (o no había nada que mandar): deja de esperar, si era lo que esperaba.
  function despachado(p) {
    if (p.delCuadro) porReintentar.cuadro = false;
    else if (porReintentar.mensaje && porReintentar.mensaje.texto === p.texto) porReintentar.mensaje = null;
    pintarReintentar();
  }
  let reintentando = false;
  if (botonReintentar) botonReintentar.addEventListener('click', async () => {
    const { audio: grabado, mensaje, cuadro: delCuadro } = porReintentar;
    // Dos toques seguidos subirían dos veces lo grabado.
    if (reintentando || !(grabado || mensaje || delCuadro)) return;
    reintentando = true;
    try {
      // En el modo voz, reintentar es seguir la conversación: la respuesta se leerá.
      if (continuo && pausado) { pausado = false; vozPausa.textContent = 'Pausar'; pedirPantalla(); }
      // De una en una: `enviar` no admite dos a la vez. Lo escrito antes que
      // lo grabado, que sin el modo voz va al cuadro a que lo revises.
      if (mensaje) await enviar(mensaje.texto, mensaje.conCita, mensaje.dictado);
      if (delCuadro) await enviarCuadro();
      if (grabado) await transcribir(grabado.audio, grabado.mandar);
    } finally { reintentando = false; }
  });
  async function transcribirYa(audio, mandar) {
    // El idioma de la voz y quién dicta, para medir cada voz aparte (C-0246).
    const d = await HubGrabar.subir(audio, { campos: { idioma: enIngles() ? 'en' : 'es', origen: 'secretario' } });
    if (d.red) {
      porReintentar.audio = { audio, mandar };
      pintarReintentar();
      if (continuo) pausar('no pude mandar lo que dijiste: el hub no contesta',
                           dichoEn('Pausé el micrófono: el hub no contesta.', 'I paused the microphone: the hub is not answering.'));
      // Los fallos, por `avisar` (C-0314): escritos a mano salían en gris y
      // el vigía del tono le quitaba el rojo al fallo de antes.
      else avisar('no se transcribió: el hub no contesta (lo grabado no se pierde)', 'error');
      return;
    }
    // Llegó otro audio: el que esperaba ya no es lo último que dijo. Sólo lo
    // grabado: un mensaje que no salió sigue esperando (C-0314).
    porReintentar.audio = null;
    pintarReintentar();
    if (continuo && (d.nada || (d.ok && !String(d.texto || '').trim()))) { noTeEntendi(); return; }
    if (!d.ok) {
      if (continuo) pausar(`no se pudo transcribir: ${d.error}`, dichoEn('Pausé el micrófono: no pude pasar tu voz a texto.',
                                                                         'I paused the microphone: I could not transcribe you.'));
      else avisar(`no se transcribió: ${d.error}`, 'error');
      return;
    }
    if (mandar && !d.texto.trim()) { avisar('no te entendí; vuelve a intentarlo', 'error'); return; }
    // Sin pasar por el cuadro nadie lo ha leído: va como dictado (C-0291).
    if (continuo || mandar || (manosLibres && manosLibres.checked)) { enviar(d.texto, true, true); return; }
    cuadro.value = (cuadro.value ? cuadro.value + ' ' : '') + d.texto;
    pintarEnviar();
    dictadoEnCuadro = cuadro.value;
    cuadro.focus();
    if (estado) estado.textContent = 'revísalo y pulsa Enviar';
  }
  // Lo que se dice en voz alta va en el idioma de la voz: el modo inglés lee en en-US.
  const dichoEn = (es, en) => (enIngles() ? en : es);
  /* Whisper no oyó palabras —una tos, una puerta— (C-0286): no es un error y
   * no pausa. Se pregunta en voz alta, porque en manos libres nadie mira la
   * pantalla, y vuelve a escuchar. Cuenta como una escucha vacía más. */
  function noTeEntendi() {
    silencios += 1;
    if (silencios >= SILENCIOS_PAUSA) { pausar('pausé el micrófono tras un rato sin entenderte'); return; }
    fase('hablando', 'no te entendí');
    decir(dichoEn('¿Perdón?', 'Sorry?'), () => { if (continuo && !pausado) hablar('no te entendí; repítelo'); });
  }

  /* ── el modo voz (decisión 317) ── */
  // Una frase de estado, en la línea de abajo y en el panel; `nombre` pinta el orbe.
  function fase(nombre, texto) {
    avisar(continuo ? '' : texto);
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
   * `decir`, que ya vuelve a escuchar: no hace falta nada más.
   * El micrófono lo abre `HubGrabar.microfono`, sin grabar: aquí sólo se
   * mide el volumen. Si no se puede abrir, se calla: la respuesta se lee
   * igual, sólo que sin poder interrumpirla de palabra. */
  let vigia = null;
  async function vigilarInterrupcion() {
    soltarVigia();
    const Ctx = window.AudioContext || window.webkitAudioContext;
    if (!Ctx || !HubGrabar.puede()) return;
    const propio = {};
    vigia = propio;
    let flujo;
    try {
      flujo = await HubGrabar.microfono(HubGrabar.RESTRICCIONES.conversacion);
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
  // `dicho`: una pausa por un fallo se dice también en voz alta (C-0286):
  // con el teléfono lejos, el panel no lo ve nadie.
  function pausar(motivo, dicho) {
    pausado = true;
    callarTodo();
    vozPausa.textContent = 'Seguir';
    fase('pausa', motivo || 'en pausa');
    if (dicho) decir(dicho);
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

  /* Por qué no hay micrófono (C-0290): sin permiso, sin micrófono u ocupado
   * por otra aplicación —una reunión— se arreglan de formas distintas, y
   * antes todo era «sin permiso». El motivo lo da `HubGrabar` (C-0311). En el
   * modo voz se pausa y se dice: el panel se quedaba en la fase de antes,
   * «te contesto…», sin escuchar a nadie. */
  function sinMicro(motivo) {
    if (continuo) pausar(motivo, dichoEn('Pausé el micrófono: no puedo usarlo.', 'I paused the microphone: I cannot use it.'));
    else avisar(motivo, 'error');
  }

  /* Al empezar a grabar, que el Whisper cargado se vaya cargando (C-0292): la
   * frase dura uno o dos segundos como poco y la carga queda casi tapada. Con
   * una vez cada 30 s basta —el servidor se queda 15 min—: cada escucha del
   * modo voz no tiene por qué pedirlo. Si falla, se dicta como siempre. */
  let calentadoEn = 0;
  function calentarVoz() {
    const ahora = Date.now();
    if (ahora - calentadoEn < 30000) return;
    calentadoEn = ahora;
    HubGrabar.calentar();
  }

  /* Mientras se abre el micrófono no hay `grabadora` que parar (C-0427): un
   * segundo toque abría otro, y salir o pausar el modo voz no tenía qué
   * callar, así que al abrirse se quedaba grabando fuera del modo. */
  let abriendoMicro = false;
  // `atajo`: grabando mientras se mantiene Ctrl+Espacio (C-0172); al soltar, se manda.
  async function hablar(aviso, atajo) {
    if (grabadora) { grabadora.stop(); return; }
    if (abriendoMicro) return;
    // Hablándole mientras lee: se calla y escucha (interrumpir con un toque).
    locutor.olvidar();
    VOZ.callar();
    if (!HubGrabar.puede()) {
      sinMicro('este navegador no deja grabar aquí (hace falta HTTPS o localhost)');
      return;
    }
    calentarVoz();
    const enModo = continuo;
    let toma;
    abriendoMicro = true;
    try {
      // Sin el eco de su propia voz ni el ruido: no se unifica con el dictado (C-0311).
      toma = await HubGrabar.grabar({ restricciones: HubGrabar.RESTRICCIONES.conversacion });
    } catch (e) {
      sinMicro(e.message);
      return;
    } finally {
      abriendoMicro = false;
    }
    // Se salió del modo, se entró o se pausó mientras se abría: lo abierto
    // se tira. Si quedó en el modo y sin pausa, se vuelve a escuchar.
    if (continuo !== enModo || (continuo && pausado)) {
      toma.descartar();
      if (continuo && !pausado) hablar(aviso);
      return;
    }
    const esta = {
      atajo: atajo || null, descartar: false, reescuchar: false,
      grabando: () => toma.grabadora.state === 'recording',
      // Lo descartado ni llega a armarse: no queda audio que subir por error.
      stop() { if (esta.descartar) toma.descartar(); else toma.parar(); },
    };
    grabadora = esta;
    toma.terminado.then((audio) => {
      if (grabadora === esta) grabadora = null;
      botonHablar.classList.remove('on');
      botonHablar.setAttribute('aria-label', 'Hablar');
      if (!continuo) contar({ voz: '' });
      // Parado por «no oí nada»: lo grabado es ruido, y Whisper le inventaría texto.
      if (esta.descartar) { if (esta.reescuchar && continuo && !pausado) hablar(); return; }
      if (audio) transcribir(audio, !!esta.atajo);
      else avisar('no se grabó nada', 'error');
    });
    // Soltó la tecla mientras se abría el micrófono: eso no es hablar.
    if (esta.atajo && esta.atajo.soltado) { esta.descartar = true; esta.stop(); return; }
    botonHablar.classList.add('on');
    botonHablar.setAttribute('aria-label', 'Parar');
    if (continuo) {
      fase('escuchando', aviso || 'te escucho…');
      escucharSilencio(toma.flujo, esta);
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
  let sinPanelALaVista = () => false;   // ídem: la interfaz nueva, en una ventana donde no se pinta
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
    // Sin panel a la vista (la interfaz nueva, en una ventana estrecha) no se graba:
    // sería hablarle a ciegas, sin ver que escucha ni lo que contesta. A su
    // pantalla, como «Guíame»; allí el atajo se ve.
    if (sinPanelALaVista()) { location.assign('/secretario'); return; }
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
      if (!esta.grabando()) { clearInterval(reloj); ctx.close(); return; }
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
    // En la interfaz nueva (C-0169) es el mismo panel flotante, con la misma
    // clave (C-0450): un panel, un sitio, una clave. Añade `Ctrl .`, y por
    // debajo de 861 px no se pinta: ahí el secretario es un destino de la barra.
    const enMarco = document.documentElement.dataset.interfaz === 'nueva';
    const sinSitio = () => enMarco && !!window.matchMedia && window.matchMedia('(max-width: 860px)').matches;
    const abierto = () => panel.classList.contains('abierto');
    const abrir = (si, recordar = true) => {
      panel.classList.toggle('abierto', si);
      pestana.setAttribute('aria-expanded', si ? 'true' : 'false');
      if (recordar) guardar(CLAVE, si);
      if (si) { bajar(); if (!cargando) mirar().then(seguir); }
    };
    pestana.addEventListener('click', () => abrir(!abierto()));
    // Sin sitio, abrirlo por lo guardado lo dejaría abierto sin verse,
    // sondeando cada 6 s; y plegarlo no lo decidió nadie: la clave se queda.
    if (sinSitio()) abrir(false, false);
    else abrir(leerPref(CLAVE));
    abrirPanel = (si) => { if (!sinSitio() && si !== abierto()) abrir(si); };
    sinPanelALaVista = sinSitio;
    window.HubSecretario = { preguntar(texto) {
      // Sin panel a la vista, la respuesta se lee en su pantalla.
      if (sinSitio()) { enviar(texto, false).then(() => location.assign('/secretario')); return; }
      abrir(true); enviar(texto, false);
    } };
    /* `Ctrl .` lo abre y lo pliega (C-0169). En captura, como Ctrl+Espacio: en
     * /trabajo el foco está en la terminal y, si no, el punto se escribiría en
     * la sesión. Al abrir, el foco va al cuadro; al plegar, vuelve a donde
     * estaba —la terminal—, para seguir tecleando sin tocar el ratón. */
    if (enMarco) {
      let antes = null;
      // Sin Meta, como `esAtajo`: en Windows, `Win + .` es el panel de emojis.
      const esPunto = (e) => (e.key === '.' || e.code === 'Period') && e.ctrlKey && !e.altKey && !e.metaKey && !e.shiftKey;
      document.addEventListener('keydown', (e) => {
        if (!esPunto(e) || sinSitio()) return;
        e.preventDefault();
        e.stopPropagation();
        if (e.repeat) return;
        if (!abierto()) {
          antes = document.activeElement || null;
          abrir(true);
          if (cuadro.focus) cuadro.focus();
        } else {
          abrir(false);
          if (antes && antes.focus && antes !== document.body) antes.focus();
          antes = null;
        }
      }, true);
    }
  }
  /* Lo anterior, una vez y con el chat a la vista (C-0393): en el panel,
   * tras el primer sondeo desplegado; en /secretario y en el monitor, ya, que
   * lo del hilo abierto vino pintado. Luego, con «Ver lo anterior». */
  let anterioresPedidos = false;
  function quizaAnteriores() {
    if (anterioresPedidos || plegado()) return;
    anterioresPedidos = true;
    const ir = Number(chat.dataset.irHilo || 0);
    if (ir > 0) irAHilo(ir); else cargarAnteriores();
  }
  // En el panel no viene nada pintado: la conversación se pide al cargar.
  if (chat.dataset.cargar) mirar().then(() => { cargando = false; seguir(); });
  else {
    cargando = false;
    quizaAnteriores();
    // Con algo esperando su sí, la tarjeta no aguarda al sondeo lento (C-0421).
    if (permisos && hayPermisosAlCargar) mirar().then(seguir);
  }
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

/* ── Ajustes → Voz (VOZ-24, C-0361) ──
 * Qué voces tiene este navegador, cuál suena y a qué velocidad, con
 * «Probar». Las voces sólo las sabe el navegador: el servidor pinta el hueco
 * y aquí se llena, también cuando llegan tarde (`voiceschanged`). */
(() => {
  const bloque = document.getElementById('voz-ajustes');
  if (!bloque || !bloque.dataset || !('vozAjustes' in bloque.dataset)) return;
  const sintesis = window.speechSynthesis;
  const PRUEBA = { es: 'Hola, así te leo las respuestas.', en: 'Hi, this is how I read you the answers.' };
  const velocidad = document.getElementById('voz-velocidad');
  const valor = document.getElementById('voz-velocidad-valor');
  const escapar = (t) => String(t ?? '').replace(/[&<>"']/g, c =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const coma = (v) => Number(v).toFixed(1).replace('.', ',');
  const voces = () => { try { return (sintesis && sintesis.getVoices()) || []; } catch (e) { return []; } };
  const deDonde = (v) => (esLocal(v) ? 'de este aparato' : 'de red: el texto sale a internet');
  const pieza = (nombre, idioma) => document.getElementById(`voz-${nombre}${idioma}`);
  function pintar() {
    const lista = voces();
    const a = ajustesVoz();
    for (const idioma of Object.keys(PRUEBA)) {
      const elegir = pieza('', idioma);
      const suena = pieza('suena-', idioma);
      if (!sintesis) {
        suena.textContent = 'Este navegador no sabe leer en voz alta.';
        elegir.disabled = true;
        pieza('probar-', idioma).hidden = true;
        continue;
      }
      const delIdioma = vocesDe(lista, idioma);
      elegir.innerHTML = '<option value="">La primera de este aparato</option>' + delIdioma.map(v =>
        `<option value="${escapar(idDeVoz(v))}">${escapar(v.name)} · ${deDonde(v)}</option>`).join('');
      elegir.value = delIdioma.some(v => idDeVoz(v) === a[idioma]) ? a[idioma] : '';
      const v = elegirVoz(lista, idioma, a[idioma]);
      suena.textContent = !lista.length ? 'Mirando qué voces tiene este aparato…'
        : v ? `Suena: ${v.name}, ${esLocal(v) ? 'de este aparato' : 'de red: lo que te lee sale a internet'}.`
        : delIdioma.length ? 'No te lee en voz alta: aquí sólo hay voces de red, que mandan el texto a internet.'
                             + ' Si te parece bien, elige una arriba.'
        : `Este aparato no tiene ninguna voz ${idioma === 'en' ? 'en inglés' : 'en español'}.`;
    }
    velocidad.value = String(a.velocidad);
    valor.textContent = coma(a.velocidad);
  }
  for (const idioma of Object.keys(PRUEBA)) {
    const elegir = pieza('', idioma);
    elegir.addEventListener('change', () => { guardarAjustesVoz({ ...ajustesVoz(), [idioma]: elegir.value }); pintar(); });
    pieza('probar-', idioma).addEventListener('click', () => {
      if (!sintesis) return;
      const u = new SpeechSynthesisUtterance(PRUEBA[idioma]);
      // Sin voz de este aparato ni una elegida, la prueba tampoco habla
      // (C-0359): el navegador usaría la suya por omisión, quizá de red.
      if (!ponerVoz(u, idioma, voces(), ajustesVoz())) {
        pieza('suena-', idioma).textContent = 'No lo pruebo: no hay voz de este aparato'
          + (vocesDe(voces(), idioma).length ? ' y no has elegido una de red. Si te parece bien, elige una arriba.' : '.');
        return;
      }
      sintesis.cancel();
      sintesis.speak(u);
    });
  }
  velocidad.addEventListener('input', () => {
    guardarAjustesVoz({ ...ajustesVoz(), velocidad: Number(velocidad.value) });
    valor.textContent = coma(ajustesVoz().velocidad);
  });
  pintar();
  if (sintesis) try { sintesis.addEventListener('voiceschanged', pintar); } catch (e) { /* se pintó con lo que había */ }
})();

/* ── qué globo está al lado de un doble clic (C-0243) ──
 * Pura, como `silencioTras`: el de cuya franja vertical es `y`. En el hueco
 * entre dos globos, ninguno (mejor no citar que citar el que no era). */
function turnoEnAltura(cajas, y) {
  const c = (cajas || []).find(k => y >= k.top && y <= k.bottom);
  return c ? c.id : null;
}


/* ── qué falta por decir de una respuesta a medio escribir (C-0155) ──
 * Pura, como `silencioTras`. Devuelve las frases completas nuevas y lo dicho
 * hasta ahora. Una frase se da por completa al ver su punto (o el final de la
 * respuesta); lo que queda a medias espera al siguiente trozo. Si el texto ya
 * no empieza por lo dicho, se ha rehecho: vacío es otra respuesta (el modelo
 * mayor) y se lee desde el principio; con otro texto se espera a la final y
 * se lee ENTERA — repetir una frase es mejor que callarse la respuesta.
 * `cerrado`: lo escrito acaba en el borde de un bloque (C-0284), y entonces
 * el punto del final también cierra frase. Sin eso hace falta un espacio
 * detrás, porque «las 10.» puede seguir con «30».
 * El punto de una abreviatura («Sr.», «p. ej.») no cierra nada (VOZ-20): la
 * frase se partía en dos, con su pausa en medio. */
function frasesNuevas(dicho, texto, final, cerrado) {
  texto = String(texto || '');
  if (!texto.startsWith(dicho)) {
    if (!texto.trim()) return { frases: [], dicho: '', final: false };
    if (!final) return { frases: [], dicho, final: false };
    dicho = '';
  }
  const desde = dicho.length;
  const fines = finesDeFrase(texto, desde, cerrado && !final);
  const corte = final ? texto.length : (fines.length ? fines[fines.length - 1] : -1);
  if (corte <= desde) return { frases: [], dicho, final: false };
  const frases = [];
  let inicio = desde;
  for (const f of fines) {
    if (f >= corte) break;
    frases.push(texto.slice(inicio, f));
    inicio = f;
  }
  frases.push(texto.slice(inicio, corte));
  return { frases: frases.map(f => f.trim()).filter(Boolean), dicho: texto.slice(0, corte), final: false };
}

/* Dónde acaba cada frase de `texto` a partir de `desde`: la posición justo
 * detrás de su signo o de su salto de línea. */
function finesDeFrase(texto, desde, cerrado) {
  const re = cerrado ? /[.!?…:](?=\s|$)|\n/g : /[.!?…:](?=\s)|\n/g;
  re.lastIndex = desde;
  const fines = [];
  let m;
  while ((m = re.exec(texto)) !== null) {
    if (m[0] === '.' && esAbreviatura(texto, m.index)) continue;
    fines.push(m.index + m[0].length);
  }
  return fines;
}

/* Si el punto de `texto[i]` cierra una abreviatura de la lista. Ni «etc.» ni
 * una letra suelta: casi siempre acaban la frase («faltan 2 h.»). */
function esAbreviatura(texto, i) {
  const m = /(?:^|[^\p{L}])(\p{L}+)$/u.exec(texto.slice(Math.max(0, i - 12), i));
  if (!m) return false;
  return ['p', 'ej', 'sr', 'sra', 'srta', 'dr', 'dra', 'lic', 'ing', 'arq', 'mtro', 'mtra',
    'prof', 'ud', 'uds', 'aprox', 'núm', 'pág', 'págs', 'vs', 'tel', 'av', 'col', 'ee', 'uu'].includes(m[1].toLowerCase());
}

/* Lo que se lee o se anuncia, acotado antes de limpiarlo (C-0357). Las
 * regex de `paraOir` no son exponenciales, pero desde cada posición recorren
 * lo que queda de una racha sin espacios ni barras: cuadráticas, y 100 000
 * caracteres seguidos tardaban 6,6 s. Nadie escucha ni lee en un anuncio
 * más de unos miles: se corta en el último fin de frase de la segunda mitad
 * del tope; si no lo hay, en el último espacio; si tampoco, en seco. */
function acotarParaOir(texto) {
  const TOPE = 4000;
  texto = String(texto || '');
  if (texto.length <= TOPE) return texto;
  const trozo = texto.slice(0, TOPE);
  let corte = -1;
  const re = /[.!?…](?=\s)|\n/g;
  let m;
  while ((m = re.exec(trozo)) !== null) corte = m.index + m[0].length;
  if (corte < TOPE / 2) corte = trozo.lastIndexOf(' ');
  if (corte < TOPE / 2) corte = TOPE;
  return trozo.slice(0, corte);
}

/* ── lo que se dice en voz alta (VOZ-20, C-0357) ──
 * Pura, como `frasesNuevas`: el texto que escribió el secretario, como hay
 * que decirlo. Sin esto la voz leía «barra», «flecha a la derecha», los
 * nombres de los emojis, «ce guion cero ciento cincuenta y cinco» o «tres
 * coma dos ese». Va por tablas para poder llevarla tal cual a un TTS de
 * servidor (C-0156). Es una red: lo que mejor suena es lo que el modelo ya
 * escribe para el oído (VOZ-21). `anio`, el año en curso: una fecha de este
 * año se dice sin él. */
function paraOir(texto, anio) {
  texto = acotarParaOir(texto);
  anio = Number(anio) || new Date().getFullYear();
  const MESES = ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio', 'agosto', 'septiembre',
                 'octubre', 'noviembre', 'diciembre'];
  const UNIDADES = { ms: ['milisegundo', 'milisegundos'], s: ['segundo', 'segundos'], min: ['minuto', 'minutos'],
                     h: ['hora', 'horas'], GB: ['giga', 'gigas'], MB: ['mega', 'megas'], '%': ['por ciento', 'por ciento'] };
  const EXT = '(?:py|js|ts|css|html|md|ya?ml|json|toml|txt|sh|db|sqlite|csv|pdf|png|jpe?g|log|ini|cfg)';
  const conExtension = new RegExp(`\\.${EXT}$`, 'i');
  // Una ruta o un archivo se dice por su último nombre, sin extensión ni
  // guiones: «conversacion», no «ese erre ce barra…». Sin nombre, «un archivo».
  const nombre = (ruta) => {
    const tramos = String(ruta).split('/').filter(t => /[\p{L}\d]/u.test(t));
    const ultimo = (tramos[tramos.length - 1] || '').replace(conExtension, '').replace(/^\.+/, '');
    return ultimo.replace(/[_\-.]+/g, ' ').trim() || 'un archivo';
  };
  return String(texto || '')
    .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')                       // [enlace](ruta) → enlace
    // Las citas de una investigación (C-0452): detrás de un signo o en grupo,
    // que es como las escribe `investigar`; un «elige la [2]» suelto se queda.
    .replace(/([.!?…;:,)»])\s*(?:\[\d+\])+|(?:\s*\[\d+\]){2,}/g, '$1')
    .replace(/https?:\/\/\S+/g, 'un enlace')
    .replace(/[\p{Extended_Pictographic}\u{1F1E6}-\u{1F1FF}️‍⃣]/gu, '')
    .replace(/\b(\d{4})-(\d{2})-(\d{2})\b/g, (m, a, mes, d) => (MESES[Number(mes) - 1]
      ? `${Number(d)} de ${MESES[Number(mes) - 1]}${Number(a) === anio ? '' : ` de ${a}`}` : m))
    // Antes que la ficha: «cambios/C-0244-algo.md» es una ruta.
    .replace(/(?:~|\.{1,2})?(?:\/[\p{L}\d_.-]+)+\/?|[\p{L}\d_.-]+(?:\/[\p{L}\d_.-]+)+\/?/gu, (todo) => {
      // El punto que cierra la frase no es de la ruta.
      const cola = /[.-]*$/.exec(todo)[0];
      const m = todo.slice(0, todo.length - cola.length);
      if (/^[\d/.,-]+$/.test(m)) return todo;                        // 12/11, 1/2: cifras, no rutas
      if (/^[~./]/.test(m) || m.split('/').length > 2 || conExtension.test(m)) return nombre(m) + cola;
      const [a, b] = m.split('/');
      return (a.toLowerCase() === 'y' && b.toLowerCase() === 'o' ? 'o' : `${a} o ${b}`) + cola;   // «sí/no», «y/o»
    })
    .replace(new RegExp(`(?<![\\p{L}\\d_./-])[\\p{L}\\d_-]+(?:\\.[\\p{L}\\d_-]+)*\\.${EXT}(?![\\p{L}\\d_])`, 'giu'),
             (m) => nombre(m))
    .replace(/\b(?:([Ll])a\s+)?C-0*(\d+)\b/g, (m, l, n) => `${l ? `${l}a` : 'la'} ficha ${n}`)
    .replace(/(\d+(?:[.,]\d+)?)\s?(ms|s|min|h|GB|MB|%)(?![\p{L}\d])/gu,
             (m, n, u) => `${n} ${UNIDADES[u][n === '1' ? 0 : 1]}`)
    .replace(/\bp\.\s?ej\./gi, 'por ejemplo')
    .replace(/\s*(?:→|->)\s*/g, ' a ')
    .replace(/\s*·\s*/g, ', ')
    .replace(/[*`#>]/g, '')
    .replace(/_/g, ' ')                                              // hub_estado → «hub estado», no «hubestado»
    .replace(/^\s*[-•]\s+/gm, '')
    .replace(/[ \t]{2,}/g, ' ')
    .replace(/ +([,.;:!?])/g, '$1')
    .trim();
}

/* ── qué voz le lee, en este aparato (VOZ-24, C-0361) ──
 * La voz es la del navegador, así que se elige en cada aparato y se guarda
 * en el suyo: `localStorage`, siempre con su `try` (puede no haberlo, o
 * fallar en una ventana privada). Lo usan el chat al leer y Ajustes → Voz al
 * pintar y al probar: una sola forma de escoger. */
/* Funciones y no constantes: Ajustes → Voz, más arriba, las usa al cargar. */
function idDeVoz(v) { return String((v && (v.voiceURI || v.name)) || ''); }
function vocesDe(voces, idioma) {
  return (voces || []).filter(v => String(v.lang || '').toLowerCase().replace('_', '-').startsWith(idioma));
}
// Lo que no dice que es de red es de este aparato: el navegador siempre lo dice.
function esLocal(v) { return !!v && v.localService !== false; }

/* La voz del idioma (`es` o `en`): la elegida si sigue estando —también una
 * de red: elegirla es su sí (VOZ-22)— y, si no, la primera DE ESTE APARATO
 * del país (es-MX, en-US) o del idioma. Sin ninguna, null: no se lee. */
function elegirVoz(voces, idioma, preferida) {
  const lista = vocesDe(voces, idioma);
  if (preferida) {
    const elegida = lista.find(v => idDeVoz(v) === preferida);
    if (elegida) return elegida;
  }
  const locales = lista.filter(esLocal);
  const pais = idioma === 'en' ? 'en-us' : 'es-mx';
  return locales.find(v => String(v.lang || '').toLowerCase().replace('_', '-') === pais) || locales[0] || null;
}

function ajustesVoz() {
  let a = {};
  try { a = JSON.parse(localStorage.getItem('secretario.voz.ajustes') || '{}') || {}; } catch (e) { a = {}; }
  const v = Number(a.velocidad);
  return { es: String(a.es || ''), en: String(a.en || ''), velocidad: v >= 0.9 && v <= 1.3 ? v : 1 };
}

function guardarAjustesVoz(a) {
  const limpio = { es: String(a.es || ''), en: String(a.en || ''), velocidad: Number(a.velocidad) || 1 };
  try { localStorage.setItem('secretario.voz.ajustes', JSON.stringify(limpio)); } catch (e) { /* sin almacenamiento: vale para esta vez */ }
}

/* Prepara una frase para decirla: idioma, velocidad y voz. Devuelve la voz,
 * o null si no hay ninguna que usar. */
function ponerVoz(u, idioma, voces, ajustes) {
  u.lang = idioma === 'en' ? 'en-US' : 'es-MX';
  u.rate = ajustes.velocidad;
  const voz = elegirVoz(voces, idioma, ajustes[idioma]);
  if (voz) u.voice = voz;
  return voz;
}

/* ── cuándo se dejó de hablar (decisión 314) ──
 * Un estado y una muestra de volumen (RMS 0-1) cada `ms`. Los primeros 400 ms
 * miden el ruido de fondo; habla quien pasa de 3 veces ese fondo (y de un
 * mínimo). Tras haber hablado, 1,3 s por debajo es el final. Sin hablar en
 * 8 s, se deja de escuchar: el micrófono abierto sin nadie gasta batería y
 * graba lo que no se pidió. Y nunca más de 60 s seguidos.
 *
 * El fondo es el MÍNIMO de esos 400 ms, acotado a 0,02, y lo oído
 * mientras se medía cuenta al cerrar la medida (C-0285). Con la media, quien
 * contestaba al instante —o seguía hablando tras interrumpirle (318)— era su
 * propio fondo: el umbral quedaba por encima de su voz y a los 8 s se tiraba
 * lo dicho. Con el tope, el umbral nunca pasa de 0,06. */
function silencioInicial() {
  return { t: 0, fondo: 0, midiendo: [], hablo: false, callado: 0, fin: null };
}
function silencioTras(e, rms, ms) {
  const s = { ...e, t: e.t + ms };
  if (s.t <= 400) {
    s.midiendo = [...s.midiendo, [rms, ms]];
    s.fondo = Math.min(...s.midiendo.map(m => m[0]), 0.02);
    return s;
  }
  const umbral = Math.max(s.fondo * 3, 0.012);
  const oir = (valor, paso) => {
    if (valor > umbral) { s.hablo = true; s.callado = 0; }
    else if (s.hablo) s.callado += paso;
  };
  // Lo que se oyó mientras se medía, ya con el umbral: un «sí» rápido es hablar.
  for (const [valor, paso] of s.midiendo) oir(valor, paso);
  s.midiendo = [];
  oir(rms, ms);
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
