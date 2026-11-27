/* El modelo del dictado, junto al micrófono (C-0313, decisión 452).

   Un `<details data-modelo-dictado>` (marcado por `ui.modelo_dictado`): al
   abrirse pregunta `/api/voz/estado?gpu=1` —qué eligió, qué hay descargado,
   qué está cargado y cuánta memoria de la GPU hay en uso— y pinta las
   opciones. Elegir manda `POST /api/voz/modelo`, que contesta cuando el
   anterior ya soltó la memoria y el nuevo está cargado. Nada se pregunta
   mientras el menú está cerrado: `nvidia-smi` cuesta ~0,3 s y no va en un
   sondeo. Todo lo que llega se pinta con `textContent`.

   Un modelo sin descargar se lee «sin descargar» y lleva su «Descargar»
   (C-0505): `POST /api/voz/descargar` vuelve en el acto y, mientras baja y el
   menú sigue abierto, se pregunta `/api/voz/estado?solo=descarga` cada pocos
   segundos (sólo lee dos archivos). Al acabar se repinta: queda elegible, no
   se elige solo. Si no se pudo mirar qué hay, ni «sin descargar» ni botón. */
(function () {
  'use strict';
  if (window.HubModeloDictado) return;

  const CORTO = { 'small': 'ligero', 'large-v3-turbo': 'turbo', 'apagado': 'apagado' };

  function gb(mb) {
    return (mb / 1024).toFixed(1).replace('.', ',');
  }

  // Lo que pesa en disco, en GB de los que dice el sistema (10^9 bytes).
  function peso(bytes) {
    return (bytes / 1e9).toFixed(1).replace('.', ',');
  }

  const SONDEO_MS = 3000;

  function bajando(estado, modelo) {
    const d = estado.descarga;
    return !!(d && d.estado === 'bajando' && (!modelo || d.modelo === modelo));
  }

  function notaDescarga(estado) {
    const d = estado.descarga;
    if (!d) return '';
    if (d.estado === 'bajando') {
      const min = d.desde ? Math.floor((Date.now() / 1000 - d.desde) / 60) : 0;
      return 'Descargando ' + d.nombre + (min >= 1 ? ' (lleva ' + min + ' min)' : '') +
        '. Puedes cerrar el menú: sigue sola, y al acabar lo eliges tú.';
    }
    // Un fallo viejo sobra si el modelo ya está (se bajó por otro lado).
    const ya = (estado.modelos || []).some(function (m) { return m.modelo === d.modelo && m.disponible; });
    if (d.estado === 'fallo' && !ya) return 'No se pudo bajar ' + d.nombre + ': ' + (d.error || 'sin motivo') + '.';
    return '';
  }

  function nota(estado) {
    const partes = [];
    const c = estado.cargado;
    if (estado.eleccion === 'apagado') {
      partes.push('Apagado: cada frase se transcribe en la CPU con el ligero, tarda unos segundos más.');
    } else if (estado.ocupado) {
      partes.push('Está pasando a texto una frase: vuelve a abrir el menú en un momento.');
    } else if (c && c.modelo) {
      partes.push('En memoria: ' + (CORTO[c.modelo] || c.modelo) + ' en ' + (c.dispositivo === 'cuda' ? 'la GPU' : 'la CPU') + '.');
    } else {
      partes.push('Ninguno en memoria: se carga al empezar a dictar y se suelta tras 15 min sin uso.');
    }
    if (estado.gpu) partes.push('GPU: ' + gb(estado.gpu.usada_mb) + ' de ' + gb(estado.gpu.total_mb) + ' GB en uso.');
    return partes.join(' ');
  }

  /* Tres formas (`ui.modelo_dictado`, C-0480). La flecha junto al micrófono
   * es un icono: escribir en su `textContent` lo borraba, así que lo elegido
   * va a su `title` y a su `aria-label`. */
  function rotular(menu, eleccion) {
    const resumen = menu.querySelector('[data-md-resumen]');
    if (!resumen || !eleccion) return;
    const corto = CORTO[eleccion] || eleccion;
    const forma = (menu.dataset && menu.dataset.mdForma) || 'rotulo';
    if (forma === 'flecha') {
      resumen.title = 'Modelo del dictado: ' + corto;
      resumen.setAttribute('aria-label', 'Modelo del dictado: ' + corto);
    } else if (forma === 'seccion') {
      resumen.textContent = 'Modelo del dictado: ' + corto;
    } else {
      resumen.textContent = 'Dictado: ' + corto;
    }
  }

  function pintar(menu, estado) {
    const caja = menu.querySelector('[data-md-opciones]');
    const pie = menu.querySelector('[data-md-nota]');
    caja.textContent = '';
    if (!estado.selector) {
      pie.textContent = estado.motivo || 'No se puede elegir el modelo en esta máquina.';
      return;
    }
    rotular(menu, estado.eleccion);
    for (const m of estado.modelos || []) {
      const b = document.createElement('button');
      b.type = 'button';
      b.dataset.mdModelo = m.modelo;
      const elegido = m.modelo === estado.eleccion;
      b.textContent = (elegido ? '✓ ' : '') + m.nombre;
      b.setAttribute('aria-pressed', elegido ? 'true' : 'false');
      if (!m.disponible) {
        b.disabled = true;
        if (estado.mirado === false) {
          b.title = 'No pude comprobar si está descargado';
        } else {
          b.textContent = m.nombre + ' — sin descargar';
          b.title = 'No está descargado en esta máquina';
        }
      }
      caja.appendChild(b);
      if (!m.disponible && estado.mirado !== false && m.modelo !== 'apagado') caja.appendChild(descargador(estado, m));
    }
    const extra = notaDescarga(estado);
    pie.textContent = nota(estado) + (extra ? ' ' + extra : '');
    if (bajando(estado)) vigilar(menu);
  }

  // Lo que va debajo de un modelo sin descargar: el botón, o por qué no lo hay.
  function descargador(estado, m) {
    if (bajando(estado, m.modelo)) {
      const p = document.createElement('p');
      p.className = 'tenue md-nota';
      p.textContent = 'Descargando…';
      return p;
    }
    if (m.solo_gpu && 'gpu' in estado && !estado.gpu) {
      const p = document.createElement('p');
      p.className = 'tenue md-nota';
      p.textContent = 'Necesita una GPU NVIDIA, y en esta máquina no la veo.';
      return p;
    }
    const b = document.createElement('button');
    b.type = 'button';
    b.dataset.mdDescargar = m.modelo;
    b.textContent = '↓ Descargar' + (m.tamano ? ' (≈' + peso(m.tamano) + ' GB)' : '');
    b.title = 'Lo baja en segundo plano a esta máquina; al acabar lo eliges tú';
    if (bajando(estado)) b.disabled = true;   // de uno en uno
    return b;
  }

  // Mientras baja y el menú sigue abierto: cuando deja de bajar, se repinta entero.
  function vigilar(menu) {
    if (menu.dataset.vigilando === '1') return;
    menu.dataset.vigilando = '1';
    setTimeout(async () => {
      menu.dataset.vigilando = '';
      if (!menu.open) return;
      try {
        const r = await fetch('/api/voz/estado?solo=descarga');
        const e = await r.json();
        if (bajando(e)) vigilar(menu);
        else await cargar(menu);
      } catch (err) { vigilar(menu); }
    }, SONDEO_MS);
  }

  async function descargar(menu, modelo) {
    if (menu.dataset.ocupado === '1') return;
    menu.dataset.ocupado = '1';
    const pie = menu.querySelector('[data-md-nota]');
    for (const b of menu.querySelectorAll('[data-md-descargar]')) b.disabled = true;
    pie.textContent = 'Empezando a bajar ' + (CORTO[modelo] || modelo) + '…';
    try {
      const r = await fetch('/api/voz/descargar', {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body: new URLSearchParams({ modelo: modelo }).toString(),
      });
      const datos = await r.json();
      await cargar(menu);
      if (!datos.ok) pie.textContent = datos.error || 'No se pudo empezar a bajar.';
    } catch (e) {
      await cargar(menu);
      pie.textContent = 'No se pudo empezar a bajar: el hub no contestó.';
    } finally {
      menu.dataset.ocupado = '';
    }
  }

  async function cargar(menu) {
    const pie = menu.querySelector('[data-md-nota]');
    pie.textContent = 'Mirando…';
    try {
      const r = await fetch('/api/voz/estado?gpu=1');
      pintar(menu, await r.json());
    } catch (e) {
      pie.textContent = 'No pude preguntarle al hub qué modelo hay.';
    }
  }

  async function elegir(menu, modelo) {
    if (menu.dataset.ocupado === '1') return;
    menu.dataset.ocupado = '1';
    const pie = menu.querySelector('[data-md-nota]');
    for (const b of menu.querySelectorAll('[data-md-modelo]')) b.disabled = true;
    pie.textContent = modelo === 'apagado' ? 'Soltando la memoria…' : 'Cargando ' + (CORTO[modelo] || modelo) + '… (unos segundos)';
    try {
      const r = await fetch('/api/voz/modelo', {
        method: 'POST',
        headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
        body: new URLSearchParams({ modelo: modelo }).toString(),
      });
      const datos = await r.json();
      if (datos.ok) {
        pintar(menu, datos);
        // Los demás menús de la página dicen lo mismo.
        for (const otro of document.querySelectorAll('[data-modelo-dictado]')) {
          if (otro !== menu) pintar(otro, datos);
        }
      } else {
        await cargar(menu);
        pie.textContent = datos.error || 'No se pudo cambiar.';
      }
    } catch (e) {
      await cargar(menu);   // vuelve a pintar las opciones: no se quedan apagadas
      pie.textContent = 'No se pudo cambiar: el hub no contestó.';
    } finally {
      menu.dataset.ocupado = '';
    }
  }

  // Cerrado, el rótulo dice lo elegido («Dictado: apagado»): sólo lee un archivo.
  async function rotularTodos(menus) {
    if (!menus.length) return;
    try {
      const r = await fetch('/api/voz/estado?solo=eleccion');
      const e = await r.json();
      for (const m of menus) if (e.selector) rotular(m, e.eleccion);
    } catch (e) { /* el rótulo genérico sirve igual */ }
  }

  function enganchar(raiz) {
    const nuevos = [];
    for (const menu of (raiz || document).querySelectorAll('[data-modelo-dictado]')) {
      if (menu.dataset.enganchado === '1') continue;
      menu.dataset.enganchado = '1';
      nuevos.push(menu);
      menu.addEventListener('toggle', () => { if (menu.open) cargar(menu); });
      menu.addEventListener('click', (ev) => {
        const cerca = (sel) => (ev.target && ev.target.closest ? ev.target.closest(sel) : null);
        const d = cerca('[data-md-descargar]');
        if (d && d.dataset && d.dataset.mdDescargar && !d.disabled) { descargar(menu, d.dataset.mdDescargar); return; }
        const b = cerca('[data-md-modelo]');
        if (b && !b.disabled) elegir(menu, b.dataset.mdModelo);
      });
    }
    rotularTodos(nuevos);
  }

  window.HubModeloDictado = { enganchar: enganchar, pintar: pintar };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', () => enganchar(document));
  else enganchar(document);
})();
