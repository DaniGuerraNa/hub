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
 *
 * C-0167: qué sección se ve ya lo decide antes del primer pintado el trocito en
 * línea de `ui.seccion_previa()`; esto lo confirma y quita su estilo. Antes se
 * veían todas un instante y luego se plegaban. Y como `sin-recarga.js` puede
 * repintar las secciones, se vuelve a aplicar con `hub:repintado`, y el clic en
 * el índice va por delegación: un oyente atado al índice se perdería con él.
 */
(() => {
  const taller = () => document.querySelector('[data-secciones]');
  const enlaces = () => [...document.querySelectorAll('[data-indice-secciones] a[data-sec]')];
  if (!taller() || !enlaces().length) return;

  const CLAVE = `hub:seccion:${taller().dataset.secciones}`;
  const existe = (s) => document.getElementById(`sec-${s}`) && enlaces().some((a) => a.dataset.sec === s);
  let actual = null;

  function mostrar(sec, recordar = true) {
    const t = taller();
    const lista = enlaces();
    if (!t || !lista.length) return;
    if (!existe(sec)) sec = lista[0].dataset.sec;
    actual = sec;
    // Sólo ahora: hasta aquí la página se ve entera, así que un fallo de script
    // deja una página larga y no una en blanco. La marca le dice a
    // `ui.seccion_previa()` que no deshaga lo suyo al cargar.
    t.classList.add('con-secciones');
    t.dataset.seccionesListo = '1';
    for (const s of t.querySelectorAll('.seccion')) {
      s.classList.toggle('viendo', s.id === `sec-${sec}`);
    }
    for (const a of lista) a.classList.toggle('aqui', a.dataset.sec === sec);
    document.querySelectorAll('style[data-seccion-previa]').forEach((e) => e.remove());
    if (recordar) { try { sessionStorage.setItem(CLAVE, sec); } catch (e) { /* modo privado */ } }
  }

  let guardada = null;
  try { guardada = sessionStorage.getItem(CLAVE); } catch (e) { /* modo privado */ }
  mostrar(location.hash.slice(1) || guardada || enlaces()[0].dataset.sec, false);

  document.addEventListener('click', (e) => {
    const a = e.target.closest && e.target.closest('[data-indice-secciones] a[data-sec]');
    if (!a) return;
    e.preventDefault();
    // replaceState y no el hash directo: así el botón «atrás» sale de la página
    // en vez de recorrer sus secciones una a una.
    history.replaceState(null, '', `#${a.dataset.sec}`);
    mostrar(a.dataset.sec);
  });

  window.addEventListener('hashchange', () => mostrar(location.hash.slice(1)));
  document.addEventListener('hub:repintado', () => mostrar(actual, false));
})();
