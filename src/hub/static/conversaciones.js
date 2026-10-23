/* Las conversaciones anteriores de un slot, para retomarlas (decisión 290).
 *
 * Rellena cualquier `[data-conversaciones="<slot>"]`: el desplegable de la
 * cabecera de Trabajo y el hueco de un slot sin ventana. Se piden al abrirlo y
 * no con la página porque cada una cuesta leer su archivo, y /trabajo se carga
 * a cada rato.
 *
 * Retomar es un formulario normal: el servidor valida que la conversación es
 * de ese slot y abre la ventana con `claude --resume`.
 */
(function () {
  function escapar(s) {
    return String(s ?? '').replace(/[&<>"']/g, c =>
      ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }

  function cuando(iso) {
    const d = new Date(iso || '');
    if (isNaN(d)) return '';
    const hoy = new Date();
    const hora = d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    if (d.toDateString() === hoy.toDateString()) return `hoy ${hora}`;
    const ayer = new Date(hoy); ayer.setDate(hoy.getDate() - 1);
    if (d.toDateString() === ayer.toDateString()) return `ayer ${hora}`;
    return `${d.toLocaleDateString([], { day: 'numeric', month: 'short' })} ${hora}`;
  }

  function fila(slot, c) {
    const titulo = escapar(c.titulo || c.primera || 'Sin título');
    const datos = `${cuando(c.fin)} · ${c.turnos} mensaje${c.turnos === 1 ? '' : 's'} tuyo${c.turnos === 1 ? '' : 's'}`;
    if (c.viva && c.ventana) {
      const url = `/trabajo?session=${encodeURIComponent(c.ventana.session)}&ventana=${c.ventana.ventana}`;
      return `<a class="boton conv" href="${url}" title="Ya está abierta: ir a su ventana">
        <span class="conv-titulo">${titulo}</span>
        <span class="conv-datos">abierta ahora · ${escapar(datos)}</span></a>`;
    }
    return `<form method="post" action="/slot/${slot}/retomar" data-una-vez="Abriendo…">
      <input type="hidden" name="sesion" value="${escapar(c.id)}">
      <button class="conv" title="Abre una ventana nueva con esta conversación, tal como la dejaste">
        <span class="conv-titulo">${titulo}</span>
        <span class="conv-datos">${escapar(datos)} · Retomar</span></button></form>`;
  }

  async function cargar(caja) {
    if (caja.dataset.cargado) return;
    caja.dataset.cargado = '1';
    const slot = caja.dataset.conversaciones;
    caja.innerHTML = '<p class="conv-nota">Buscando…</p>';
    let datos = null;
    try {
      const r = await fetch(`/api/slot/${encodeURIComponent(slot)}/conversaciones`);
      datos = r.ok ? await r.json() : null;
    } catch (e) { datos = null; }
    if (!datos) {
      delete caja.dataset.cargado;
      caja.innerHTML = '<p class="conv-nota">No se pudieron leer. Vuelve a abrirlo.</p>';
      return;
    }
    const lista = datos.conversaciones || [];
    caja.innerHTML = lista.length
      ? lista.map(c => fila(slot, c)).join('')
        + '<p class="conv-nota">Claude guarda cada conversación entera: al retomarla sigue donde la dejaste.</p>'
      : '<p class="conv-nota">Todavía no hay conversaciones de Claude en este slot.</p>';
  }

  // El desplegable se carga al abrirlo; el hueco de un slot vacío, ya.
  document.querySelectorAll('[data-conversaciones]').forEach(caja => {
    const menu = caja.closest('details');
    if (menu) menu.addEventListener('toggle', () => { if (menu.open) cargar(caja); });
    else cargar(caja);
  });
})();
