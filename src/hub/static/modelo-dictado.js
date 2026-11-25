/* El modelo del dictado, junto al micrófono (C-0313, decisión 452).

   Un `<details data-modelo-dictado>` (marcado por `ui.modelo_dictado`): al
   abrirse pregunta `/api/voz/estado?gpu=1` —qué eligió, qué hay descargado,
   qué está cargado y cuánta memoria de la GPU hay en uso— y pinta las
   opciones. Elegir manda `POST /api/voz/modelo`, que contesta cuando el
   anterior ya soltó la memoria y el nuevo está cargado. Nada se pregunta
   mientras el menú está cerrado: `nvidia-smi` cuesta ~0,3 s y no va en un
   sondeo. Todo lo que llega se pinta con `textContent`. */
(function () {
  'use strict';
  if (window.HubModeloDictado) return;

  const CORTO = { 'small': 'ligero', 'large-v3-turbo': 'turbo', 'apagado': 'apagado' };

  function gb(mb) {
    return (mb / 1024).toFixed(1).replace('.', ',');
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
        b.title = 'No está descargado en esta máquina';
      }
      caja.appendChild(b);
    }
    pie.textContent = nota(estado);
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
        const b = ev.target && ev.target.closest ? ev.target.closest('[data-md-modelo]') : null;
        if (b && !b.disabled) elegir(menu, b.dataset.mdModelo);
      });
    }
    rotularTodos(nuevos);
  }

  window.HubModeloDictado = { enganchar: enganchar, pintar: pintar };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', () => enganchar(document));
  else enganchar(document);
})();
