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
 * llevar las etiquetas que se ponen aquí (enlace, negrita, código y el bloque
 * de código con su «Copiar»), nunca algo que venga en el texto.
 */
(function (raiz) {
  function escapar(s) {
    return String(s ?? '').replace(/[&<>"']/g, c =>
      ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }

  const RUTA_DEL_HUB = /^\/(?!\/)[\w\-./?=&%#+]*$/;

  // `opciones.copiar`: los bloques de código llevan «Copiar». Sólo quien
  // atiende ese botón lo pide (el chat del secretario, C-0306).
  function formatearMensaje(texto, opciones) {
    const copiar = !!(opciones && opciones.copiar);
    let html = escapar(texto);
    // El código se aparta antes, para que un `**` o un enlace dentro de él se
    // quede como se escribió.
    const apartados = [];
    const apartar = (trozo) => { apartados.push(trozo); return `\u0000${apartados.length - 1}\u0000`; };
    // Los bloques de tres comillas, lo primero (C-0306): quedaban literales y en
    // letra normal, y una orden o una ruta no se distinguía ni se copiaba. Uno
    // sin cerrar al final es una respuesta que aún se escribe (C-0155): ya es
    // código. Los saltos de alrededor se los come el bloque, que va aparte.
    html = html.replace(/\n?```[^`\n]*\n([\s\S]*?)(?:\n?```[ \t]*(?:\n|$)|$)/g, (_, codigo) =>
      apartar('<div class="bloque-codigo">'
              + (copiar ? '<button type="button" class="copiar-codigo" data-copiar-codigo>Copiar</button>' : '')
              + `<pre><code>${codigo}</code></pre></div>`));
    html = html.replace(/```([^`\n]+)```|`([^`\n]+)`/g, (_, triple, simple) => apartar(`<code>${triple || simple}</code>`));
    html = html.replace(/\[([^\]\n]+)\]\(([^)\s]+)\)/g, (todo, etiqueta, destino) => {
      const real = destino.replace(/&amp;/g, '&');
      return RUTA_DEL_HUB.test(real)
        ? `<a class="ir" href="${destino}">${etiqueta}</a>`
        : todo;
    });
    // Un título (`#`, `##`…), en negrita: las almohadillas sólo eran ruido.
    html = html.replace(/^#{1,6}[ \t]+(.+)$/gm, '<strong class="titulo">$1</strong>');
    html = html.replace(/\*\*([^*\n]+)\*\*/g, '<strong>$1</strong>');
    return html.replace(/\u0000(\d+)\u0000/g, (_, i) => apartados[Number(i)]);
  }

  raiz.formatearMensaje = formatearMensaje;
})(typeof window !== 'undefined' ? window : globalThis);
