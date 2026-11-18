/* El marco de la interfaz nueva (C-0169): lo poco que su navegación necesita
 * de JavaScript. «Más» —las secciones que no caben en la barra del teléfono—
 * es un `<details>`: se abre, se cierra y se navega sin este archivo. Aquí
 * sólo va lo que el HTML no da: cerrarla con Escape o tocando fuera, y dejar
 * a la vista, en la tira del teléfono, la pantalla en la que estás.
 *
 * Por delegación en `document`: la barra vive en la región `rail`, que
 * `sin-recarga.js` sustituye entera, y un oyente atado a un nodo de dentro se
 * perdería. Por lo mismo no toca el DOM al cargar: lo que una región trae del
 * servidor tiene que casar con lo que el servidor vuelva a mandar.
 *
 * Y plegar la barra (C-0450): el raíl y, en /trabajo, la lista de proyectos,
 * juntos y por aparato. `HubMarco.barra` es la puerta.
 *
 * El panel del secretario (abrirlo, plegarlo, `Ctrl .`) es de
 * `chat-secretario.js`, que es su dueño.
 */
(function () {
  const mas = () => document.getElementById('marco-mas');

  /* La barra plegada se recuerda por aparato, con el prefijo y el JSON de lo
   * que guarda /trabajo (`hub.sinNota`). El estado EFECTIVO —guardada y con
   * sitio, desde 861 px— va en `<html data-barra>`: fuera de la región `rail`,
   * que `sin-recarga.js` sustituye entera. Al cargar lo pone ya el guion de
   * antes de pintar de `nueva/base.html`; aquí sólo se cambia, y al cambiar se
   * avisa con `hub:barra`, que /trabajo oye para esconder su lista. Sin
   * almacenamiento (una ventana privada) no se recuerda, pero vale para esta
   * página. */
  const CLAVE_BARRA = 'hub.sinBarra';
  const raiz = document.documentElement;
  // La misma pregunta que el CSS que enseña el botón de abrir (`min-width: 861px`), no su
  // contraria: con un ancho fraccionario (zoom, escala de Windows) entre 860 y 861 las dos
  // darían «ni estrecha ni ancha», y la barra quedaría plegada sin botón con que abrirla.
  const estrecha = () => !!window.matchMedia && !window.matchMedia('(min-width: 861px)').matches;
  let quiere = (() => { try { return JSON.parse(localStorage.getItem(CLAVE_BARRA)) === true; } catch (e) { return false; } })();
  const plegada = () => raiz.dataset.barra === 'plegada';
  function aplicar() {
    const si = quiere && !estrecha();
    if (si === plegada()) return;
    if (si) raiz.dataset.barra = 'plegada';
    else delete raiz.dataset.barra;
    document.dispatchEvent(new CustomEvent('hub:barra', { detail: { plegada: si } }));
  }
  function poner(si) {
    quiere = !!si;
    try { localStorage.setItem(CLAVE_BARRA, JSON.stringify(quiere)); } catch (e) { /* sin almacenamiento */ }
    aplicar();
  }
  // Al cruzar los 861 px: en el teléfono no aplica, y al volver al PC sí.
  const medida = window.matchMedia && window.matchMedia('(min-width: 861px)');
  if (medida && medida.addEventListener) medida.addEventListener('change', aplicar);

  function cerrar(devolverFoco) {
    const d = mas();
    if (!d || !d.open) return false;
    d.open = false;
    const resumen = d.querySelector('summary');
    if (devolverFoco && resumen && resumen.focus) resumen.focus();
    return true;
  }

  document.addEventListener('keydown', (e) => {
    // Con el foco dentro vuelve a «Más»: quien navega con teclado no se pierde.
    if (e.key === 'Escape' && cerrar(true)) e.preventDefault();
  });

  document.addEventListener('click', (e) => {
    // Los botones de la barra, por delegación: viven en la región `rail`. El
    // que se pulsa desaparece, así que el foco pasa al otro, que aparece.
    const boton = e.target && e.target.closest && e.target.closest('[data-marco-barra]');
    const pide = boton && boton.dataset ? boton.dataset.marcoBarra : '';
    if (pide === 'plegar' || pide === 'abrir') {
      poner(pide === 'plegar');
      const otro = document.querySelector(`[data-marco-barra="${pide === 'plegar' ? 'abrir' : 'plegar'}"]`);
      if (otro && otro.focus) otro.focus();
    }
    const d = mas();
    if (!d || !d.open) return;
    const dentro = e.target && e.target.closest && e.target.closest('#marco-mas');
    if (!dentro) cerrar(false);
  });

  /* En el teléfono la tira de pantallas va en una línea que se desliza. Que
   * la pantalla en la que estás no quede fuera de la vista al llegar: se
   * centra. Sólo mueve el desplazamiento de la tira —que no es de ninguna
   * región—, y sólo si no cabe entera. */
  function centrarTira() {
    const tira = document.querySelector('.marco-tira');
    const aqui = tira && tira.querySelector && tira.querySelector('.aqui');
    if (!aqui || !(tira.scrollWidth > tira.clientWidth)) return;
    const caja = tira.getBoundingClientRect();
    const suya = aqui.getBoundingClientRect();
    tira.scrollLeft += (suya.left + suya.width / 2) - (caja.left + caja.width / 2);
  }
  centrarTira();

  window.HubMarco = { cerrarMas: () => cerrar(false), centrarTira, barra: { plegada, poner } };
})();
