/* Plegar proyectos en el raíl de la vista de trabajo.
 *
 * Con veinte proyectos indexados, el raíl es más largo que la pantalla de un
 * teléfono y llegar al slot de abajo cuesta tres barridos de pulgar. Plegar lo
 * que hoy no se toca es lo que hace que el índice quepa.
 *
 * 🔴 Lo plegado se recuerda por proyecto en `localStorage`, y **nunca se pliega
 * el proyecto de lo que se está mirando**: esconder justo el slot que acabas de
 * abrir se lee como que el hub lo perdió.
 *
 * En archivo aparte y no en la plantilla, como `lienzos.js` y los demás: si
 * esto revienta, la terminal sigue viva — y así se prueba ejecutándolo
 * (regla dura 11), que es lo que pide este proyecto de todo su JavaScript.
 */
(() => {
  const CLAVE = 'hub.trabajo.plegados';

  const leer = () => {
    // Un `localStorage` que no se puede leer —modo privado, permisos— no puede
    // dejar el raíl sin funcionar: se pierde la preferencia, no la lista.
    try { return new Set(JSON.parse(localStorage.getItem(CLAVE)) || []); }
    catch { return new Set(); }
  };
  const guardar = (plegados) => {
    try { localStorage.setItem(CLAVE, JSON.stringify([...plegados])); } catch { /* da igual */ }
  };

  const plegados = leer();

  document.querySelectorAll('.proyecto[data-proyecto]').forEach((caja) => {
    const id = caja.dataset.proyecto;
    const boton = caja.querySelector('.plegar');
    if (!boton) return;

    const aplicar = (plegar) => {
      caja.classList.toggle('plegado', plegar);
      boton.setAttribute('aria-expanded', plegar ? 'false' : 'true');
    };

    // La marca la pone el servidor, que ya sabe de qué proyecto cuelga el slot
    // abierto: si es éste, se despliega aunque estuviera guardado plegado.
    if (plegados.has(id) && !caja.classList.contains('mirando')) aplicar(true);

    boton.addEventListener('click', () => {
      const plegar = !caja.classList.contains('plegado');
      aplicar(plegar);
      if (plegar) { plegados.add(id); } else { plegados.delete(id); }
      guardar(plegados);
    });
  });
})();
