/* Navegación por secciones: una pantalla larga se navega, no se recorre.
 *
 * Vivía dentro de `proyecto.html`. Sube aquí en cuanto lo necesitó la segunda
 * pantalla —/canal, con personas, preguntas y un registro de cincuenta líneas
 * uno detrás de otro—, por la misma razón que el CSS del índice ya había subido
 * a `base.html`: dos copias parecidas del mismo componente es lo que hace que
 * una interfaz se sienta descosida, y la copia se desvía en cuanto una de las
 * dos se toca.
 *
 * Se conecta por atributos, no por ids: `data-secciones="<clave>"` en el
 * contenedor y `data-indice-secciones` en el índice. La clave separa lo que
 * cada vista recuerda; sin ella, entrar en /canal te dejaría en la sección que
 * mirabas en un proyecto.
 *
 * El hash manda —así un enlace a #registro lleva ahí— y si no hay, se recuerda
 * la última mirada: estas páginas hacen POST y redirigen, y volver siempre a la
 * primera sección perdía el sitio en cada acción.
 */
(() => {
  const taller = document.querySelector('[data-secciones]');
  const indice = document.querySelector('[data-indice-secciones]');
  if (!taller || !indice) return;

  const enlaces = [...indice.querySelectorAll('a[data-sec]')];
  if (!enlaces.length) return;
  const existe = (s) => document.getElementById(`sec-${s}`) && enlaces.some((a) => a.dataset.sec === s);
  const CLAVE = `hub:seccion:${taller.dataset.secciones}`;

  function mostrar(sec, recordar = true) {
    if (!existe(sec)) sec = enlaces[0].dataset.sec;
    for (const s of taller.querySelectorAll('.seccion')) {
      s.classList.toggle('viendo', s.id === `sec-${sec}`);
    }
    for (const a of enlaces) a.classList.toggle('aqui', a.dataset.sec === sec);
    if (recordar) { try { sessionStorage.setItem(CLAVE, sec); } catch (e) { /* modo privado */ } }
  }

  // Sólo ahora: hasta aquí la página se ve entera, así que un fallo de script
  // deja una página larga y no una en blanco.
  taller.classList.add('con-secciones');

  let guardada = null;
  try { guardada = sessionStorage.getItem(CLAVE); } catch (e) { /* modo privado */ }
  mostrar(location.hash.slice(1) || guardada || enlaces[0].dataset.sec, false);

  indice.addEventListener('click', (e) => {
    const a = e.target.closest('a[data-sec]');
    if (!a) return;
    e.preventDefault();
    // replaceState y no el hash directo: así el botón «atrás» sale de la página
    // en vez de recorrer sus secciones una a una.
    history.replaceState(null, '', `#${a.dataset.sec}`);
    mostrar(a.dataset.sec);
  });

  window.addEventListener('hashchange', () => mostrar(location.hash.slice(1)));
})();
