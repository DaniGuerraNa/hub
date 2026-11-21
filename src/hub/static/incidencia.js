/* Contar un fallo o una idea (C-0468, decisión 445).
 *
 * El texto se arma aquí, en el navegador, y del hub no sale nada: «Abrir en
 * GitHub» es un enlace que abre la persona, al formulario de su plantilla con
 * los campos ya rellenos por su `id`, y lo envía ella con su cuenta. Sin
 * GitHub detrás, sólo se copia.
 *
 * 🔴 En la URL van `template`, `title` y los campos (`que_paso`, `equipo`);
 * nunca `labels` ni `assignees` (GitHub da 404 a quien no tiene permiso) ni
 * `body` (con una plantilla de formulario no rellena nada). Si no cabe en
 * `limite`, lo escrito sale de la URL y se copia en el clic de abrir; la
 * pantalla lo dice antes.
 */
(function () {
  function armar(o) {
    if (!o || !o.destino) return { url: null, recortado: false };
    const limite = Number(o.limite) || 6000;
    const con = (campos) => o.destino + '?' + campos
      .filter((c) => c[1])
      .map((c) => c[0] + '=' + encodeURIComponent(c[1]))
      .join('&');
    const base = [['template', o.plantilla], ['title', o.titulo]];
    const entera = con([...base, ['que_paso', o.que_paso], ['equipo', o.equipo]]);
    if (entera.length <= limite) return { url: entera, recortado: false };
    // Los datos del equipo son pocas líneas y salen de una lista cerrada: lo
    // que no cabe es lo escrito, y es lo que se deja fuera.
    return { url: con([...base, ['equipo', o.equipo]]), recortado: true };
  }
  window.HubIncidencia = { armar };

  const raiz = document.getElementById('incidencia');
  if (!raiz || !raiz.dataset || !raiz.dataset.tipos) return;
  const $ = (id) => document.getElementById(id);
  const tipos = raiz.dataset.tipos.split(' ').map((c) => $('tipo-' + c)).filter(Boolean);
  const titulo = $('inc-titulo');
  const quePaso = $('inc-que-paso');
  const conEquipo = $('inc-con-equipo');
  const equipo = $('inc-equipo');
  const vista = $('inc-vista');
  const rotulo = $('inc-campo');
  const rotuloRecortado = $('inc-campo-recortado');
  const aviso = $('inc-recortado');
  const copiar = $('inc-copiar');
  const destino = raiz.dataset.destino || '';
  // Sin destino la plantilla no pinta el enlace: no hay nada que abrir.
  const abrir = destino ? $('inc-abrir') : null;
  let ultimo = { url: null, recortado: false };

  const tipo = () => tipos.find((t) => t.checked) || tipos[0];
  const datosDelEquipo = () => (conEquipo && conEquipo.checked ? (equipo.textContent || '').trim() : '');

  function texto() {
    const partes = ['Título: ' + (titulo.value.trim() || '(sin título)'), '',
                    '### ' + tipo().dataset.campo, '', quePaso.value.trim() || '(sin escribir)'];
    const delEquipo = datosDelEquipo();
    if (delEquipo) partes.push('', '### Datos del equipo', '', delEquipo);
    return partes.join('\n');
  }

  function pintar() {
    const t = tipo();
    rotulo.textContent = t.dataset.campo;
    if (rotuloRecortado) rotuloRecortado.textContent = t.dataset.campo;
    quePaso.placeholder = t.dataset.ejemplo;
    vista.value = texto();
    ultimo = armar({ destino, plantilla: t.dataset.plantilla, titulo: titulo.value.trim(),
                     que_paso: quePaso.value.trim(), equipo: datosDelEquipo(), limite: raiz.dataset.limite });
    if (abrir && ultimo.url) abrir.href = ultimo.url;
    if (aviso) aviso.hidden = !ultimo.recortado;
  }

  tipos.forEach((t) => t.addEventListener('change', pintar));
  [titulo, quePaso].forEach((campo) => campo.addEventListener('input', pintar));
  if (conEquipo) conEquipo.addEventListener('change', pintar);

  copiar.addEventListener('click', async () => {
    const todo = texto();
    try {
      // Fuera de https o de esta misma máquina no hay portapapeles: lanza, y
      // se cae al plan B en vez de dejar un botón que no hace nada.
      await navigator.clipboard.writeText(todo);
    } catch (e) {
      vista.focus();
      vista.select();
      return HubUI.avisar({ titulo: 'Cópialo tú',
                            mensaje: 'El navegador no dejó usar el portapapeles. El texto ya está seleccionado: Ctrl+C.' });
    }
    copiar.textContent = 'Copiado';
    setTimeout(() => { copiar.textContent = 'Copiar el texto'; }, 1500);
  });

  let yaAvisado = false;
  if (abrir) abrir.addEventListener('click', (e) => {
    pintar();
    if (!ultimo.recortado) return;
    // Lo escrito no cabe en el enlace: se copia en este mismo clic y sin
    // esperar a nada, porque la pestaña nueva se lleva el foco y, con él,
    // el permiso de escribir en el portapapeles.
    quePaso.focus();
    quePaso.select();
    let copiado = false;
    try { copiado = document.execCommand('copy'); } catch (err) { copiado = false; }
    if (copiado || yaAvisado) return;
    e.preventDefault();
    yaAvisado = true;
    HubUI.avisar({ titulo: 'Cópialo antes de abrir',
                   mensaje: 'No se pudo copiar solo. Lo que escribiste ya está seleccionado: Ctrl+C, '
                            + 'y vuelve a pulsar «Abrir en GitHub» para pegarlo allí.' });
  });

  pintar();
})();
