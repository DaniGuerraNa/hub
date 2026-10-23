/* Plegar proyectos en el raíl de la vista de trabajo.
 *
 * Con veinte proyectos indexados, el raíl es más largo que la pantalla y
 * llegar al slot de abajo cuesta varios barridos. Plegar lo que no se toca es
 * lo que hace que el índice quepa.
 *
 * 🔴 **Al entrar, todo plegado salvo el proyecto de lo que se está mirando**
 * (22-oct, lo pidió el dueño). Antes se recordaba lo plegado de cada proyecto,
 * y con proyectos nuevos o desplegados una vez la lista volvía larga en cada
 * F5: había que cerrarlos a mano para ver dónde estabas. Desplegar a mano vale
 * hasta la siguiente carga, a propósito.
 *
 * `mirando` la pone el servidor, que sabe de qué proyecto cuelga el slot
 * abierto. Si no hay ninguno —se entró sin slot—, se queda todo plegado.
 *
 * En archivo aparte y no en la plantilla, como `lienzos.js` y los demás: si
 * esto revienta, la terminal sigue viva — y así se prueba ejecutándolo
 * (regla dura 11).
 */
(() => {
  // La preferencia vieja ya no se usa: se borra para no dejar basura.
  try { localStorage.removeItem('hub.trabajo.plegados'); } catch { /* da igual */ }

  document.querySelectorAll('.proyecto[data-proyecto]').forEach((caja) => {
    const boton = caja.querySelector('.plegar');
    if (!boton) return;

    const aplicar = (plegar) => {
      caja.classList.toggle('plegado', plegar);
      boton.setAttribute('aria-expanded', plegar ? 'false' : 'true');
    };

    aplicar(!caja.classList.contains('mirando'));

    boton.addEventListener('click', () => {
      aplicar(!caja.classList.contains('plegado'));
    });
  });
})();
