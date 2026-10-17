/* Lo que escribe el asistente, pintado: enlaces del hub, negritas y código.
 *
 * Existe para que pueda **llevarte** a un sitio en vez de describírtelo
 * (decisión 271): «[Abrir Trabajo](/trabajo)» se pulsa. Antes todo era texto
 * plano y la única forma de ir era copiar la ruta a la barra de direcciones.
 *
 * 🔴 Sólo enlaces DEL HUB: una ruta que empieza por una sola «/». Nada de
 * `http:`, `javascript:` ni `//otro-sitio`: el texto lo escribe un modelo que
 * ha leído transcripts y archivos de proyectos, y un enlace fuera del hub en
 * su respuesta es exactamente lo que no debe poder colarse. Lo que no pasa el
 * filtro se queda como texto, tal cual se escribió.
 *
 * Se escapa TODO primero y se marca después: el HTML que sale sólo puede
 * llevar las tres etiquetas que se ponen aquí.
 */
(function (raiz) {
  function escapar(s) {
    return String(s ?? '').replace(/[&<>"']/g, c =>
      ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }

  const RUTA_DEL_HUB = /^\/(?!\/)[\w\-./?=&%#+]*$/;

  function formatearMensaje(texto) {
    let html = escapar(texto);
    // El código se aparta antes, para que un `**` o un enlace dentro de él se
    // quede como se escribió.
    const apartados = [];
    html = html.replace(/`([^`\n]+)`/g, (_, codigo) => {
      apartados.push(`<code>${codigo}</code>`);
      return `\u0000${apartados.length - 1}\u0000`;
    });
    html = html.replace(/\[([^\]\n]+)\]\(([^)\s]+)\)/g, (todo, etiqueta, destino) => {
      const real = destino.replace(/&amp;/g, '&');
      return RUTA_DEL_HUB.test(real)
        ? `<a class="ir" href="${destino}">${etiqueta}</a>`
        : todo;
    });
    html = html.replace(/\*\*([^*\n]+)\*\*/g, '<strong>$1</strong>');
    return html.replace(/\u0000(\d+)\u0000/g, (_, i) => apartados[Number(i)]);
  }

  raiz.formatearMensaje = formatearMensaje;
})(typeof window !== 'undefined' ? window : globalThis);
